"""Two-model figures and per-fault numbers for the Phase 1 report.

  python scripts/report_figs.py report/figs GLM=results/glm-flash-25tasks DS=results/deepseek-v41-flash-25tasks

Writes <out>/propagation_models.pdf/png and <out>/stats_models.json.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from statistics import mean

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from fpr.analysis import enrich  # noqa: E402

TEXT, TEXT2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
BLUE, ORANGE, NEUTRAL = "#2a78d6", "#eb6834", "#b9b8b1"
STAGES = ["state", "retrieval", "researcher", "planner", "tool_result"]
CATS = [("ignored", "ignored", NEUTRAL), ("propagated_benign", "propagated, task OK", BLUE),
        ("propagated_harmful", "propagated, failure or unauthorized", ORANGE)]

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "font.size": 8, "axes.edgecolor": GRID, "axes.labelcolor": TEXT2, "xtick.color": TEXT2,
    "ytick.color": TEXT, "pdf.fonttype": 42,
})


def load(d):
    with open(os.path.join(d, "runs.jsonl"), encoding="utf-8") as f:
        return enrich([json.loads(l) for l in f if l.strip()])


def fault_order(rows):
    meta = {r["fault"]: (r["category"], STAGES.index(r["stage"])) for r in rows if r["fault"] != "clean"}
    return sorted(meta, key=lambda f: (meta[f], f))


def per_fault(rows):
    out = {}
    for f in fault_order(rows):
        rs = [r for r in rows if r["fault"] == f and r["method"] == "none" and r["fault_applied"]]
        dep = Counter(r["dependence"] for r in rs)
        out[f] = {
            "category": rs[0]["category"], "applied": len(rs),
            **{k: dep[k] for k, _, _ in CATS},
            "success": sum(r["success"] for r in rs),
            "unauthorized_per_run": mean(r["unauthorized"] for r in rs),
            "affected_stages": mean(r["n_affected_stages"] for r in rs),
            "wasted_tokens": mean(r["wasted_tokens"] for r in rs),
            "wasted_tool_actions": mean(r["wasted_tool_actions"] for r in rs),
            "wasted_external_actions": mean(r["wasted_external_actions"] for r in rs),
            "latency_s": mean(r["latency_s"] for r in rs),
        }
    return out


def per_method(rows):
    out = {}
    clean = [r for r in rows if r["fault"] == "clean"]
    for m in ("none", "verify"):
        rs = [r for r in clean if r["method"] == m]
        out[f"clean_{m}"] = {"runs": len(rs), "success": sum(r["success"] for r in rs),
                             "tokens": mean(r["total_tokens"] for r in rs),
                             "latency_s": mean(r["latency_s"] for r in rs),
                             "rejected_runs": sum(r["verify_rejections"] > 0 for r in rs)}
    faulty = [r for r in rows if r["fault"] != "clean" and r["fault_applied"]]
    for cat in ("accidental", "adversarial"):
        for m in ("none", "restart", "verify"):
            rs = [r for r in faulty if r["category"] == cat and r["method"] == m]
            out[f"{cat}_{m}"] = {"runs": len(rs), **{k: mean(float(r[k] or 0) for r in rs) for k in (
                "success", "success_excl_residue", "unauthorized", "irreversible_residue",
                "total_tokens", "latency_s")}}
    return out


def fig_propagation(models, out):
    faults = fault_order(next(iter(models.values())))
    names = list(models)
    stats = {n: per_fault(rows) for n, rows in models.items()}
    fig, ax = plt.subplots(figsize=(3.35, 3.25))
    h, gap = 0.36, 0.40
    yc = list(range(len(faults)))[::-1]
    for y, f in zip(yc, faults):
        for k, n in enumerate(names):
            yy = y + gap / 2 - k * gap
            s = stats[n][f]
            left = 0.0
            for key, _, color in CATS:
                w = s[key] / s["applied"]
                if w:
                    ax.barh(yy, w, left=left, height=h, color=color, edgecolor=SURFACE, linewidth=0.8)
                left += w
            ax.text(-0.012, yy, n, ha="right", va="center", fontsize=5.5, color=TEXT2)
            u = s["unauthorized_per_run"]
            ax.text(1.02, yy, f"{u:.2f}" if u else "–", va="center", fontsize=6, color=TEXT2)
    ax.text(1.02, len(faults) - 0.45, "unauth.\n/run", fontsize=6, color=TEXT2, va="bottom")
    n_acc = sum(stats[names[0]][f]["category"] == "accidental" for f in faults)
    ax.axhline(len(faults) - n_acc - 0.5, color=TEXT2, linewidth=0.6, linestyle=(0, (2, 2)))
    ax.set_yticks(yc, [f.replace("tool_result.", "tool.") for f in faults], fontsize=6.5)
    ax.tick_params(axis="y", pad=14, length=0)
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, len(faults) - 0.4)
    ax.set_xticks([0, 0.5, 1], ["0%", "50%", "100%"])
    ax.set_xlabel("share of applied runs (no recovery)")
    for name, lo, hi in (("accidental", len(faults) - n_acc, len(faults) - 1),
                         ("adversarial", 0, len(faults) - n_acc - 1)):
        ax.text(1.17, (lo + hi) / 2, name, rotation=270, ha="center", va="center", fontsize=6.5,
                color=TEXT2, style="italic", transform=ax.get_yaxis_transform())
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in CATS]
    ax.legend(handles, [l for _, l, _ in CATS], loc="lower center", bbox_to_anchor=(0.4, 1.0), ncol=2,
              frameon=False, fontsize=6.5, handlelength=1, columnspacing=0.8)
    fig.tight_layout(pad=0.3)
    fig.savefig(os.path.join(out, "propagation_models.pdf"))
    fig.savefig(os.path.join(out, "propagation_models.png"), dpi=200)
    return stats


def main():
    out, specs = sys.argv[1], sys.argv[2:]
    os.makedirs(out, exist_ok=True)
    models = {}
    for spec in specs:
        name, d = spec.split("=", 1)
        models[name] = load(d)
    faults = fig_propagation(models, out)
    stats = {n: {"faults": faults[n], "methods": per_method(rows)} for n, rows in models.items()}
    with open(os.path.join(out, "stats_models.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps({n: s["methods"] for n, s in stats.items()}, indent=1))


if __name__ == "__main__":
    main()
