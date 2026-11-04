"""Merge a patch run into a base run: rows with the same (task, fault, method, rep)
are replaced by the patch rows, new rows (e.g. extra tasks) are added, and the
merged directory is re-analyzed.

  python scripts/merge_runs.py results/<base> results/<patch> results/<merged>
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpr.analysis import summarize  # noqa: E402


def load(d):
    with open(os.path.join(d, "runs.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    base, patch, out = sys.argv[1:4]
    key = lambda r: (r["task_id"], r["fault"], r["method"], r["rep"])
    rows = {key(r): r for r in load(base)}
    patched = load(patch)
    rows.update({key(r): r for r in patched})
    rows = sorted(rows.values(), key=lambda r: r["run_id"])

    os.makedirs(out, exist_ok=True)
    tasks = {}
    for d in (base, patch):
        path = os.path.join(d, "tasks.jsonl")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                tasks.update({json.loads(l)["task_id"]: l for l in f if l.strip()})
    with open(os.path.join(out, "tasks.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(tasks[k] for k in sorted(tasks))
    with open(os.path.join(out, "runs.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(out, "MERGED.md"), "w", encoding="utf-8") as f:
        f.write(f"base: {base}\npatch: {patch} ({len(patched)} rows replaced or added)\n"
                "Trace paths in runs.jsonl point into the base and patch directories.\n")
    report, _ = summarize(rows)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print(report)


if __name__ == "__main__":
    main()
