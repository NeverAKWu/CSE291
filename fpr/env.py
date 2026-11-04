"""Simulated environment: restorable shared files + an irreversible external world.

`files` model shared state that a snapshot can roll back (budgets.json,
orders.csv). `external` models side effects that leave the system (placed
vendor orders, sent emails): a snapshot restore never undoes them, which is
exactly the "environment has moved on" problem Phase 2 has to face.
"""
from __future__ import annotations

import copy
import hashlib
import json

TOOL_SPECS = {
    "place_order": {"args": "vendor, item, qty, unit_price", "returns": "{order_id, status}",
                    "reversible": False, "external": True},
    "send_email": {"args": "to, subject, body", "returns": "{status}",
                   "reversible": False, "external": True},
    "append_record": {"args": "path, row", "returns": "{status}",
                      "reversible": True, "external": False},
    "update_budget": {"args": "team, amount (deducted)", "returns": "{status, remaining}",
                      "reversible": True, "external": False},
    "read_file": {"args": "path", "returns": "{content}", "reversible": True, "external": False},
    "delete_file": {"args": "path", "returns": "{status}", "reversible": True, "external": False},
}


def tools_doc() -> str:
    return "\n".join(f"- {name}({s['args']}) -> {s['returns']}" for name, s in TOOL_SPECS.items())


class Sandbox:
    def __init__(self, files: dict[str, str]):
        self.files = dict(files)
        self.writers = {p: "init" for p in files}  # path -> artifact id of last writer
        self.external: list[dict] = []
        self.action_log: list[dict] = []
        self._seq = 0

    # ---- snapshots (files only; the external world cannot be rolled back) ----
    def snapshot(self) -> dict:
        return {"files": dict(self.files), "writers": dict(self.writers), "seq": self._seq}

    def restore(self, snap: dict) -> None:
        self.files = dict(snap["files"])
        self.writers = dict(snap["writers"])

    # ---- state access with provenance ----
    def read(self, path: str) -> tuple[str | None, str | None]:
        return self.files.get(path), self.writers.get(path)

    def budgets(self) -> dict:
        return json.loads(self.files.get("budgets.json", "{}"))

    def execute(self, call: dict) -> tuple[dict, list[str], list[str]]:
        """Run one tool call. Returns (result, writer ids read, paths written)."""
        tool, args = call.get("tool"), call.get("args") or {}
        reads: list[str] = []
        writes: list[str] = []
        try:
            if tool == "place_order":
                self._seq += 1
                key = f"{args['vendor']}|{args['item']}|{args['qty']}|{self._seq}"
                order_id = "ORD-" + hashlib.sha1(key.encode()).hexdigest()[:6].upper()
                self.external.append({"type": "order", "order_id": order_id, "vendor": args["vendor"],
                                      "item": args["item"], "qty": int(float(args["qty"])),
                                      "unit_price": float(args["unit_price"])})
                result = {"order_id": order_id, "status": "confirmed"}
            elif tool == "send_email":
                self.external.append({"type": "email", "to": str(args["to"]),
                                      "subject": str(args.get("subject", "")),
                                      "body": str(args.get("body", ""))})
                result = {"status": "sent"}
            elif tool == "append_record":
                path = args["path"]
                reads.append(self.writers.get(path, "init"))
                row = str(args["row"]).rstrip("\n")
                self.files[path] = self.files.get(path, "") + row + "\n"
                writes.append(path)
                result = {"status": "ok"}
            elif tool == "update_budget":
                reads.append(self.writers.get("budgets.json", "init"))
                budgets = self.budgets()
                team = args["team"]
                budgets[team] = round(budgets[team] - float(args["amount"]), 2)
                self.files["budgets.json"] = json.dumps(budgets, indent=2)
                writes.append("budgets.json")
                result = {"status": "ok", "remaining": budgets[team]}
            elif tool == "read_file":
                reads.append(self.writers.get(args["path"], "init"))
                result = {"content": self.files.get(args["path"])}
            elif tool == "delete_file":
                self.files.pop(args["path"], None)
                writes.append(args["path"])
                result = {"status": "deleted"}
            else:
                result = {"error": f"unknown tool {tool!r}"}
        except Exception as e:  # malformed args from the LLM
            result = {"error": f"{type(e).__name__}: {e}"}
        self.action_log.append({"call": copy.deepcopy(call), "result": result,
                                "external": TOOL_SPECS.get(tool, {}).get("external", False),
                                "reversible": TOOL_SPECS.get(tool, {}).get("reversible", True)})
        return result, reads, writes
