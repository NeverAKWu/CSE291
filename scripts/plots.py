"""Figures with explicit full scheduled denominators, written to a new directory.

  python scripts/plots.py results/glm-flash-25tasks-audited-v2 report/revised/figs

Original figures and raw experiment files are never overwritten.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from fpr.analysis import aggregate_stats, enrich  # noqa: E402

TEXT, TEXT2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#ffffff"
BLUE, ORANGE, NEUTRAL = "#2a78d6", "#eb6834", "#b9b8b1"
STAGES = ["state", "retrieval", "researcher", "planner", "tool_result"]
plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8,
                     "axes.edgecolor": GRID, "axes.labelcolor": TEXT2, "xtick.color": TEXT2,
                     "ytick.color": TEXT, "axes.titlesize": 8, "pdf.fonttype": 42})


def label(f):
    return f.replace("tool_result.", "tool.")


def fault_order(rows):
    metadata = {r["fault"]: (r["category"], STAGES.index(r["stage"]) if r["stage"] in STAGES else 99)
                for r in rows if r["fault"] != "clean"}
    return sorted(metadata, key=lambda fault: (metadata[fault], fault))


def _save(fig, out, name):
    fig.tight_layout(pad=0.4)
    fig.savefig(out / (name + ".pdf"))
    fig.savefig(out / (name + ".png"), dpi=200)
    plt.close(fig)


def fig_propagation(rows, out):
    none = [r for r in rows if r["method"] == "none" and r["fault"] != "clean"]
    faults = fault_order(none)
    if not faults:
        return
    categories = [("not_applied", "not delivered", "#eeeeee"), ("ignored", "ignored", NEUTRAL),
                  ("propagated_benign", "propagated, task OK", BLUE),
                  ("propagated_harmful", "direct harmful evidence", ORANGE),
                  ("propagated_failure_unattributed", "failure, attribution uncertain", "#8b70b4"),
                  ("propagation_unobserved", "ancestry unobserved", "#656565")]
    fig, ax = plt.subplots(figsize=(6.6, 3.7))
    for yi, fault in enumerate(faults[::-1]):
        subset = [r for r in none if r["fault"] == fault]
        counts = Counter(r.get("dependence", "propagation_unobserved") for r in subset)
        left = 0
        for category, _, color in categories:
            width = counts[category] / len(subset)
            if width:
                ax.barh(yi, width, left=left, height=0.65, color=color, edgecolor=SURFACE, linewidth=0.6)
            left += width
        ax.text(1.01, yi, f"n={len(subset)}", va="center", fontsize=7)
    ax.set_yticks(range(len(faults)), [label(f) for f in faults[::-1]], fontsize=7)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, .5, 1], ["0%", "50%", "100%"])
    ax.set_xlabel("All scheduled no-recovery runs, including undelivered faults")
    handles = [plt.Rectangle((0, 0), 1, 1, color=color) for _, _, color in categories]
    ax.legend(handles, [name for _, name, _ in categories], loc="lower center", bbox_to_anchor=(.5, 1.01),
              ncol=2, frameon=False, fontsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    _save(fig, out, "propagation")


def fig_methods(rows, out):
    faulty = [r for r in rows if r["fault"] != "clean"]
    faults = fault_order(faulty)
    if not faults:
        return
    columns = [(method, field, title + "\n" + metric)
               for method, title in (("none", "No recovery"), ("restart", "Full restart"), ("verify", "Verify"))
               for field, metric in (("success", "correct"), ("safe_success", "safe + correct"))]
    grid, labels = [], []
    for fault in faults:
        values, annotations = [], []
        for method, field, _ in columns:
            subset = [r for r in faulty if r["fault"] == fault and r["method"] == method and r.get(field) is not None]
            values.append(mean(bool(r[field]) for r in subset) if subset else float("nan"))
            annotations.append(f"{sum(bool(r[field]) for r in subset)}/{len(subset)}" if subset else "n/a")
        grid.append(values)
        labels.append(annotations)
    cmap = LinearSegmentedColormap.from_list("seq", ["#ffffff", "#cde2fb", "#3987e5", "#0d366b"])
    fig, ax = plt.subplots(figsize=(6.6, 3.7))
    ax.imshow(grid, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    for i, row in enumerate(grid):
        for j, value in enumerate(row):
            ax.text(j, i, labels[i][j], ha="center", va="center", fontsize=7,
                    color=SURFACE if value > .55 else TEXT)
    ax.set_xticks(range(len(columns)), [c[2] for c in columns], fontsize=7)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(faults)), [label(f) for f in faults], fontsize=7)
    ax.set_xlabel("Correct / scheduled runs (ITT); irreversible actions remain in the outcome")
    ax.tick_params(length=0)
    _save(fig, out, "methods")


def fig_stages(rows, out):
    faulty = [r for r in rows if r["fault"] != "clean" and r["method"] == "none"]
    faults = fault_order(faulty)
    stages = ["retrieval", "researcher", "planner", "executor", "tool_result"]
    if not faults:
        return
    grid, denominators = [], []
    for fault in faults:
        subset = [r for r in faulty if r["fault"] == fault]
        grid.append([sum(stage in r.get("affected_stages", []) for r in subset) / len(subset) for stage in stages])
        denominators.append(len(subset))
    fig, ax = plt.subplots(figsize=(5.3, 3.7))
    ax.imshow(grid, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i, row in enumerate(grid):
        for j, value in enumerate(row):
            ax.text(j, i, f"{round(value * denominators[i])}/{denominators[i]}", ha="center", va="center", fontsize=7,
                    color=SURFACE if value > .55 else TEXT)
    ax.set_yticks(range(len(faults)), [label(f) for f in faults], fontsize=7)
    ax.set_xticks(range(len(stages)), [s.replace("tool_result", "tool result") for s in stages], rotation=20)
    ax.set_xlabel("Runs with a changed fault descendant / all scheduled no-recovery runs")
    ax.tick_params(length=0)
    _save(fig, out, "affected_stages")


def stats(rows, out):
    result = aggregate_stats(rows)
    (Path(out) / "stats.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.source.resolve():
        parser.error("figure output must differ from experiment input")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("figure directory must be empty or new")
    args.output.mkdir(parents=True, exist_ok=True)
    enriched = args.source / "runs_enriched.jsonl"
    source = enriched if enriched.is_file() else args.source / "runs.jsonl"
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not enriched.is_file():
        rows = enrich(rows, result_dir=args.source)
    fig_propagation(rows, args.output)
    fig_methods(rows, args.output)
    fig_stages(rows, args.output)
    print(json.dumps(stats(rows, args.output), indent=2))


if __name__ == "__main__":
    main()
