"""Run the Phase 1 experiment matrix.

  python scripts/run_experiment.py --mock --n-tasks 5                 # pipeline check, no API cost
  python scripts/run_experiment.py --model <name> --n-tasks 25 --workers 8

Per task: 2 clean runs (determinism check), 1 clean run with the verifier
(false positives), then every fault x every method under the same schedule.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpr.analysis import summarize  # noqa: E402
from fpr.faults import FAULTS  # noqa: E402
from fpr.llm import make_llm  # noqa: E402
from fpr.methods import METHODS, run_one  # noqa: E402
from fpr.tasks import make_task  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("FPR_MODEL", "gpt-4o-mini"))
    ap.add_argument("--mock", action="store_true", help="use the deterministic mock LLM")
    ap.add_argument("--n-tasks", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--task-offset", type=int, default=0,
                    help="first task index; tasks are deterministic per (seed, index), so runs can be extended")
    ap.add_argument("--faults", default="all", help="comma-separated fault names, or 'all'")
    ap.add_argument("--methods", default=",".join(METHODS))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-clean", action="store_true", help="only fault runs (to patch an existing result dir)")
    args = ap.parse_args()

    faults = list(FAULTS) if args.faults == "all" else args.faults.split(",")
    methods = args.methods.split(",")
    unknown = [f for f in faults if f not in FAULTS] + [m for m in methods if m not in METHODS]
    if unknown:
        sys.exit(f"unknown fault/method: {unknown}")

    name = args.out or time.strftime("%Y%m%d-%H%M%S") + ("-mock" if args.mock else "")
    out_dir = os.path.join("results", name)
    trace_dir = os.path.join(out_dir, "traces")
    os.makedirs(trace_dir, exist_ok=True)

    llm = make_llm(args.model, args.mock)
    tasks = [make_task(i, args.seed) for i in range(args.task_offset, args.task_offset + args.n_tasks)]
    with open(os.path.join(out_dir, "tasks.jsonl"), "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t.to_dict()) + "\n")

    jobs = []
    for t in tasks:
        if not args.skip_clean:
            jobs += [(t, None, "none", 0), (t, None, "none", 1)]
            if "verify" in methods:
                jobs.append((t, None, "verify", 0))
        jobs += [(t, f, m, 0) for f in faults for m in methods]
    print(f"{len(jobs)} runs -> {out_dir}")

    rows, failed = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(run_one, t, llm, f, m, trace_dir, rep): (t.task_id, f, m) for t, f, m, rep in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                rows.append(fut.result())
            except Exception as e:  # keep going; one API failure should not kill the matrix
                failed += 1
                print(f"FAILED {futs[fut]}: {type(e).__name__}: {e}", file=sys.stderr)
            if i % 20 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)} done")

    rows.sort(key=lambda r: r["run_id"])
    with open(os.path.join(out_dir, "runs.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(out_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump({**vars(args), "faults": faults, "methods": methods, "failed_runs": failed}, f, indent=2)

    report, _ = summarize(rows)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    if failed:
        print(f"\n{failed} runs failed; see stderr", file=sys.stderr)


if __name__ == "__main__":
    main()
