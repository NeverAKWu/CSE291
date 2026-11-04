"""Run a versioned matrix, saving each completion and a frozen source manifest.

Use --mock for a zero-cost pipeline check. Existing output directories are never
reused: merge or analyze their saved results separately.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpr.analysis import summarize  # noqa: E402
from fpr.faults import FAULTS  # noqa: E402
from fpr.llm import make_llm  # noqa: E402
from fpr.methods import METHODS, run_one  # noqa: E402
from fpr.tasks import make_task  # noqa: E402
from fpr.workflow import PROTOCOL_VERSION  # noqa: E402


def freeze_sources(out_dir: Path) -> tuple[dict, str]:
    """Persist exactly the source bytes whose hashes the launch records."""
    sources = sorted(ROOT.glob("fpr/*.py")) + sorted(ROOT.glob("scripts/*.py"))
    sources += [ROOT / name for name in ("requirements.txt",) if (ROOT / name).exists()]
    hashes = {}
    for source in sources:
        relative = source.relative_to(ROOT)
        data = source.read_bytes()
        hashes[str(relative)] = hashlib.sha256(data).hexdigest()
        target = out_dir / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    (out_dir / "source_manifest.json").write_text(json.dumps(
        {"sha256": digest, "files": hashes}, indent=2) + "\n", encoding="utf-8")
    return hashes, digest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("FPR_MODEL", "api-glm-5.3-flash"))
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--n-tasks", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--task-offset", type=int, default=0)
    ap.add_argument("--faults", default="all")
    ap.add_argument("--methods", default=",".join(METHODS))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-clean", action="store_true")
    ap.add_argument("--verification-scope", choices=("rp", "rpe"), default="rpe")
    ap.add_argument("--max-verification-retries", type=int, default=1)
    ap.add_argument("--max-tokens", type=int, default=2048)
    args = ap.parse_args()
    if args.n_tasks < 1 or args.workers < 1 or args.max_verification_retries < 0 or args.max_tokens < 1:
        ap.error("tasks/workers/max-tokens must be positive; verification retries nonnegative")
    faults = list(FAULTS) if args.faults == "all" else args.faults.split(",")
    methods = args.methods.split(",")
    unknown = [f for f in faults if f not in FAULTS] + [m for m in methods if m not in METHODS]
    if unknown:
        ap.error(f"unknown fault/method: {unknown}")
    if len(set(faults)) != len(faults) or len(set(methods)) != len(methods):
        ap.error("duplicate fault/method would collide run IDs")

    name = args.out or time.strftime("%Y%m%d-%H%M%S") + ("-mock" if args.mock else "")
    out_dir = ROOT / "results" / name
    # Create once, before API clients are initialized; no silent overwrites.
    out_dir.mkdir(parents=True, exist_ok=False)
    trace_dir = out_dir / "traces"
    trace_dir.mkdir()
    hashes, source_hash = freeze_sources(out_dir)
    tasks = [make_task(i, args.seed) for i in range(args.task_offset, args.task_offset + args.n_tasks)]
    with (out_dir / "tasks.jsonl").open("x", encoding="utf-8") as stream:
        for task in tasks:
            stream.write(json.dumps(task.to_dict()) + "\n")
    jobs = []
    for task in tasks:
        if not args.skip_clean:
            jobs += [(task, None, "none", 0), (task, None, "none", 1)]
            if "verify" in methods:
                jobs.append((task, None, "verify", 0))
        jobs += [(task, fault, method, 0) for fault in faults for method in methods]
    try:
        openai_version = metadata.version("openai")
    except metadata.PackageNotFoundError:
        openai_version = None
    environment = {"python": platform.python_version(), "python_implementation": platform.python_implementation(),
                   "platform": platform.platform(), "openai_version": openai_version}
    config = {**vars(args), "environment": environment, "faults": faults, "methods": methods, "protocol_version": PROTOCOL_VERSION,
              "launch_source_sha256": hashes, "source_manifest_sha256": source_hash,
              "planned_runs": len(jobs), "started_at_unix": time.time(), "status": "running"}
    config_path = out_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    llm = make_llm(args.model, args.mock, max_tokens=args.max_tokens)
    print(f"{len(jobs)} runs -> {out_dir}", flush=True)
    rows, failed = [], []
    # Append+flush each completion so an interrupted matrix retains completed rows.
    with (out_dir / "runs.jsonl").open("x", encoding="utf-8") as row_stream, \
            (out_dir / "failures.jsonl").open("x", encoding="utf-8") as failure_stream, \
            ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(run_one, task, llm, fault, method, str(trace_dir), rep,
                            args.verification_scope, args.max_verification_retries, source_hash):
                (task.task_id, fault, method, rep) for task, fault, method, rep in jobs}
        for index, future in enumerate(as_completed(futs), 1):
            try:
                row = future.result()
                rows.append(row)
                row_stream.write(json.dumps(row) + "\n")
                row_stream.flush()
            except Exception as exc:
                task_id, fault, method, rep = futs[future]
                run_id = f"{task_id}__{fault or 'clean'}__{method}__r{rep}"
                failure = {"run_id": run_id, "error_type": type(exc).__name__,
                           "trace": str(trace_dir / (run_id + ".jsonl"))}
                failed.append(failure)
                failure_stream.write(json.dumps(failure) + "\n")
                failure_stream.flush()
                print(f"FAILED {run_id}: {type(exc).__name__}", file=sys.stderr, flush=True)
            if index % 20 == 0 or index == len(jobs):
                print(f"  {index}/{len(jobs)} done ({len(failed)} failed)", flush=True)
    config.update(status="completed_with_failures" if failed else "completed",
                  completed_runs=len(rows), failed_runs=len(failed), finished_at_unix=time.time())
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    report, _ = summarize(rows, result_dir=out_dir, repo_root=ROOT)
    (out_dir / "summary.md").write_text(report, encoding="utf-8")
    print(report)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
