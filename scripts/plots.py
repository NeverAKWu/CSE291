"""Phase 1 figures from a (merged) result directory.

  python scripts/plots.py results/glm-flash-25tasks report/figs
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from statistics import mean

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from fpr.analysis import enrich  # noqa: E402

TEXT, TEXT2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
BLUE, ORANGE, NEUTRAL = "#2a78d6", "#eb6834", "#b9b8b1"
SEQ = ["#ffffff", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
STAGES = ["state", "retrieval", "researcher", "planner", "tool_result"]

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": TEXT2, "xtick.color": TEXT2,
    "ytick.color": TEXT, "axes.titlesize": 8, "pdf.fonttype": 42,
})


def label(f: str) -> str:
    return f.replace("tool_result.", "tool.")


def fault_order(rows):
    meta = {r["fault"]: (r["category"], STAGES.index(r["stage"])) for r in rows if r["fault"] != "clean"}
    return sorted(meta, key=lambda f: (meta[f], f))


def fig_propagation(rows, out):
    none = [r for r in rows if r["method"] == "none" and r["fault"] != "clean"]
    faults = fault_order(none)
    cats = [("ignored", "ignored", NEUTRAL), ("propagated_benign", "propagated, task OK", BLUE),
            ("propagated_harmful", "propagated, failure or unauthorized", ORANGE)]
    fig, ax = plt.subplots(figsize=(3.35, 2.75))
    y = list(range(len(faults)))[::-1]
    for yi, f in zip(y, faults):
        rs = [r for r in none if r["fault"] == f and r["fault_applied"]]
        left = 0.0
        for key, _, color in cats:
            w = sum(r.get("dependence") == key for r in rs) / len(rs)
            if w:
                ax.barh(yi, w, left=left, height=0.62, color=color, edgecolor=SURFACE, linewidth=1)
            left += w
        unauth = mean(r["unauthorized"] for r in rs)
        if unauth:
            ax.text(1.02, yi, f"{unauth:.2f}", va="center", fontsize=7, color=TEXT2)
    ax.text(1.02, len(faults) - 0.3, "unauth.\n/run", fontsize=6.5, color=TEXT2, va="bottom")
    n_acc = sum(1 for f in faults if next(r["category"] for r in none if r["fault"] == f) == "accidental")
    ax.axhline(len(faults) - n_acc - 0.5, color=TEXT2, linewidth=0.6, linestyle=(0, (2, 2)))
    ax.set_yticks(y, [label(f) for f in faults], fontsize=7)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.5, 1], ["0%", "50%", "100%"])
    ax.set_xlabel("share of runs where the fault was applied")
    for name, lo, hi in (("accidental", len(faults) - n_acc, len(faults) - 1), ("adversarial", 0, len(faults) - n_acc - 1)):
        ax.text(1.16, (lo + hi) / 2, name, rotation=270, ha="center", va="center", fontsize=6.5,
                color=TEXT2, style="italic", transform=ax.get_yaxis_transform())
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in cats]
    ax.legend(handles, [l for _, l, _ in cats], loc="lower center", bbox_to_anchor=(0.4, 1.0), ncol=2,
              frameon=False, fontsize=6.5, handlelength=1, columnspacing=0.8)
    fig.tight_layout(pad=0.3)
    fig.savefig(os.path.join(out, "propagation.pdf"))
    fig.savefig(os.path.join(out, "propagation.png"), dpi=200)


def fig_methods(rows, out):
    faulty = [r for r in rows if r["fault"] != "clean" and r["fault_applied"]]
    faults = fault_order(faulty)
    cols = [("none", "success", "no\nrecovery"), ("restart", "success", "full\nrestart"),
            ("restart", "success_excl_residue", "restart if\nundoable*"), ("verify", "success", "always\nverify")]
    grid, unauth = [], []
    for f in faults:
        row, urow = [], []
        for m, field, _ in cols:
            rs = [r for r in faulty if r["fault"] == f and r["method"] == m]
            row.append(mean(bool(r[field]) for r in rs))
            urow.append(any(r["unauthorized"] for r in rs))
        grid.append(row)
        unauth.append(urow)
    cmap = LinearSegmentedColormap.from_list("seq", SEQ)
    fig, ax = plt.subplots(figsize=(3.35, 2.75))
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            ax.text(j, i, f"{v:.0%}" + ("$^\dagger$" if unauth[i][j] else ""), ha="center", va="center", fontsize=6.5, color=SURFACE if v > 0.55 else TEXT)
    ax.set_xticks(range(len(cols)), [c[2] for c in cols], fontsize=6.5)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(faults)), [label(f) for f in faults], fontsize=7)
    n_acc = sum(1 for f in faults if next(r["category"] for r in faulty if r["fault"] == f) == "accidental")
    ax.axhline(n_acc - 0.5, color=TEXT, linewidth=0.8)
    ax.set_xticks([x - 0.5 for x in range(1, len(cols))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(faults))], minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=1.5)
    ax.tick_params(which="both", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.tight_layout(pad=0.3)
    fig.savefig(os.path.join(out, "methods.pdf"))
    fig.savefig(os.path.join(out, "methods.png"), dpi=200)


def stats(rows, out):
    """Numbers quoted in the report text, so the prose can be checked against data."""
    s = {}
    clean = [r for r in rows if r["fault"] == "clean"]
    for m in ("none", "verify"):
        rs = [r for r in clean if r["method"] == m]
        s[f"clean_{m}"] = {"runs": len(rs), "success": mean(r["success"] for r in rs),
                          "tokens": mean(r["total_tokens"] for r in rs), "calls": mean(r["llm_calls"] for r in rs),
                          "latency": mean(r["latency_s"] for r in rs),
                          "verify_fp": mean(r["verify_rejections"] > 0 for r in rs)}
    faulty = [r for r in rows if r["fault"] != "clean" and r["fault_applied"]]
    for cat in ("accidental", "adversarial"):
        for m in ("none", "restart", "verify"):
            rs = [r for r in faulty if r["category"] == cat and r["method"] == m]
            s[f"{cat}_{m}"] = {k: mean(float(r[k] or 0) for r in rs) for k in
                               ("success", "success_excl_residue", "unauthorized", "irreversible_residue",
                                "total_tokens", "llm_calls", "latency_s")}
            s[f"{cat}_{m}"]["runs"] = len(rs)
    dep = defaultdict(lambda: defaultdict(int))
    for r in faulty:
        if r["method"] == "none":
            dep[r["category"]][r["dependence"]] += 1
    s["dependence"] = {k: dict(v) for k, v in dep.items()}
    with open(os.path.join(out, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    return s


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(src, "runs.jsonl"), encoding="utf-8") as f:
        rows = enrich([json.loads(l) for l in f if l.strip()])
    fig_propagation(rows, out)
    fig_methods(rows, out)
    print(json.dumps(stats(rows, out), indent=1))


if __name__ == "__main__":
    main()
