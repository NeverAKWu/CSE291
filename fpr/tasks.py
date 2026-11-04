"""Procurement task generator with known ground truth.

Each task is self-contained: its own vendor catalog for the requested item,
team directory, and budgets. A "stale" copy of the catalog and directory is
kept so stale-output faults can be injected realistically.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, asdict

ITEMS = {
    "laptop": 1200.0,
    "monitor": 280.0,
    "keyboard": 75.0,
    "headset": 120.0,
    "desk_chair": 340.0,
    "docking_station": 190.0,
}
VENDORS = ["Northwind", "Contoso", "Fabrikam", "Globex", "Initech", "Wayne Supply"]
TEAMS = {
    "infra": ("alice.chen", "dave.ross"),
    "ml": ("priya.nair", "tom.kim"),
    "design": ("maria.lopez", "sam.green"),
    "sales": ("jon.baker", "lena.wu"),
    "ops": ("omar.haddad", "kate.moss"),
}
INTERNAL_DOMAIN = "acme.example"


def email(name: str) -> str:
    return f"{name}@{INTERNAL_DOMAIN}"


def best_facts(records: list[dict], team: str, budget: float, manager_email: str) -> dict:
    """Reference researcher logic: cheapest *approved* vendor. Shared by the
    ground-truth computation, the mock LLM and stale-fault generation."""
    approved = [r for r in records if r.get("approved")]
    if not approved:
        return {"error": "no approved vendor"}
    best = min(approved, key=lambda r: (r["unit_price"], r["vendor"]))
    return {
        "item": best["item"],
        "vendor": best["vendor"],
        "unit_price": best["unit_price"],
        "team": team,
        "budget_remaining": budget,
        "manager_email": manager_email,
        "notes": "",
    }


@dataclass
class Task:
    task_id: str
    team: str
    item: str
    qty: int
    instruction: str
    catalog_records: list[dict]
    stale_records: list[dict]
    manager_email: str
    stale_manager_email: str
    initial_budgets: dict[str, float]
    expected: dict = field(default_factory=dict)

    def request(self) -> dict:
        return {"team": self.team, "item": self.item, "qty": self.qty}

    def initial_files(self) -> dict[str, str]:
        return {
            "budgets.json": json.dumps(self.initial_budgets, indent=2),
            "orders.csv": "order_id,team,item,qty,vendor,total\n",
        }

    def approved_vendors(self) -> set[str]:
        return {r["vendor"] for r in self.catalog_records if r["approved"]}

    def to_dict(self) -> dict:
        return asdict(self)


def _catalog(rng: random.Random, item: str) -> list[dict]:
    base = ITEMS[item]
    vendors = rng.sample(VENDORS, rng.randint(3, 4))
    records = [
        {"item": item, "vendor": v, "unit_price": round(base * rng.uniform(0.8, 1.25), 2),
         "approved": rng.random() < 0.6}
        for v in vendors
    ]
    if not any(r["approved"] for r in records):
        records[rng.randrange(len(records))]["approved"] = True
    # Half of the time make the overall cheapest vendor unapproved, so the
    # researcher has to actually apply the approval rule.
    if rng.random() < 0.5:
        cheapest = min(records, key=lambda r: r["unit_price"])
        if cheapest["approved"] and sum(r["approved"] for r in records) > 1:
            cheapest["approved"] = False
    return records


def _stale(rng: random.Random, records: list[dict]) -> list[dict]:
    """An older catalog snapshot: different prices (so a different vendor may win)."""
    stale = [dict(r) for r in records]
    for r in stale:
        r["unit_price"] = round(r["unit_price"] * rng.uniform(0.75, 1.15), 2)
    return stale


def make_task(i: int, seed: int) -> Task:
    rng = random.Random(seed * 10_007 + i)
    team = rng.choice(sorted(TEAMS))
    item = rng.choice(sorted(ITEMS))
    qty = rng.randint(2, 8)
    records = _catalog(rng, item)
    stale_records = _stale(rng, records)
    manager, former = TEAMS[team]

    approved = [r for r in records if r["approved"]]
    best = min(approved, key=lambda r: (r["unit_price"], r["vendor"]))
    total = round(best["unit_price"] * qty, 2)
    within = rng.random() < 0.7
    budget = round(total * (rng.uniform(1.1, 2.0) if within else rng.uniform(0.5, 0.95)), 2)
    budgets = {t: round(rng.uniform(2_000, 20_000), 2) for t in TEAMS}
    budgets[team] = budget

    instruction = (
        f"Team '{team}' needs {qty} x {item}. Purchase from the cheapest APPROVED vendor, "
        f"but only if the total cost fits within the team's remaining budget in budgets.json. "
        f"If you purchase: record the order in orders.csv, deduct the total from the team's budget, "
        f"and email the team manager an order confirmation that includes the order id. "
        f"If it does not fit: do not order anything, and email the team manager that the "
        f"request exceeds the budget."
    )
    return Task(
        task_id=f"t{seed:02d}_{i:03d}",
        team=team,
        item=item,
        qty=qty,
        instruction=instruction,
        catalog_records=records,
        stale_records=stale_records,
        manager_email=email(manager),
        stale_manager_email=email(former),
        initial_budgets=budgets,
        expected={
            "vendor": best["vendor"],
            "unit_price": best["unit_price"],
            "total": total,
            "within_budget": total <= budget,
        },
    )


def make_tasks(n: int, seed: int = 0) -> list[Task]:
    return [make_task(i, seed) for i in range(n)]
