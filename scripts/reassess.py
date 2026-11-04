"""Re-score existing traces without model calls; write a new audited result set.

  python scripts/reassess.py results/glm-flash-25tasks --out results/glm-flash-25tasks-audited-v2

Original scores are retained in each derived row. No raw file is modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fpr.analysis import REPO_ROOT, resolve_trace_path  # noqa: E402
from fpr.reassessment import reassess_trace  # noqa: E402
from fpr.tasks import Task  # noqa: E402
from scripts.analyze import sha256, write_analysis  # noqa: E402


def reassess(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("reassessment output must be a NEW directory")
    runs_path, tasks_path = source / "runs.jsonl", source / "tasks.jsonl"
    rows = [json.loads(line) for line in runs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    task_data = [json.loads(line) for line in tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    tasks = {task["task_id"]: Task(**task) for task in task_data}
    if len(tasks) != len(task_data):
        raise ValueError("duplicate task_id in input tasks")
    if len({row["run_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate run_id in input runs")
    source_runs_hash = sha256(runs_path)
    rescored = []
    # All replay and path checks complete before any output is written.
    for row in rows:
        trace = resolve_trace_path(row["trace"], source)
        scores = reassess_trace(tasks[row["task_id"]], trace)
        original = {k: row[k] for k in scores if k in row}
        revised = {**row, **scores, "original_scores": original, "trace": str(trace),
                   "source_trace_sha256": sha256(trace), "source_runs_sha256": source_runs_hash}
        rescored.append(revised)
    output.mkdir(parents=True)
    (output / "tasks.jsonl").write_text(tasks_path.read_text(encoding="utf-8"), encoding="utf-8")
    with (output / "runs_reassessed.jsonl").open("w", encoding="utf-8") as stream:
        for row in rescored:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    provenance = {"runs": str(runs_path), "runs_sha256": sha256(runs_path),
                  "tasks": str(tasks_path), "tasks_sha256": sha256(tasks_path),
                  "checker_sha256": sha256(REPO_ROOT / "fpr/checker.py"),
                  "reassessment_sha256": sha256(REPO_ROOT / "fpr/reassessment.py"),
                  "replay_environment_sha256": sha256(REPO_ROOT / "fpr/env.py"),
                  "historical_raw_requests": "unavailable where not recorded; never reconstructed as original evidence"}
    report = write_analysis(rescored, source, output, provenance=provenance)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(reassess(args.source, args.out))


if __name__ == "__main__":
    main()
