"""Merge patch rows into a NEW portable result directory, retaining input lineage.

  python scripts/merge_runs.py results/base results/patch results/new-merged

Tasks and observed fault metadata must agree. Available configuration fields are
checked; missing historical source/protocol hashes are reported, never invented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fpr.analysis import resolve_trace_path, summarize  # noqa: E402


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(directory):
    with (Path(directory) / "runs.jsonl").open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def merge(base, patch, out):
    base, patch, out = (Path(p).resolve() for p in (base, patch, out))
    if out.exists():
        raise ValueError("merge output must be a new directory")
    key = lambda row: (row["task_id"], row["fault"], row["method"], row["rep"])
    tasks, rows, origins, configs, inputs, faults = {}, {}, {}, {}, [], {}
    warnings = []
    for directory in (base, patch):
        config_path = directory / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else None
        configs[str(directory)] = config
        if config is None:
            warnings.append(f"no historical config.json: {directory}")
        source_rows = load(directory)
        tasks_path = directory / "tasks.jsonl"
        if not tasks_path.is_file():
            raise ValueError(f"tasks.jsonl missing: {directory}")
        for line in tasks_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            task = json.loads(line)
            ident = task["task_id"]
            if ident in tasks and tasks[ident] != task:
                raise ValueError(f"task definition mismatch for {ident}")
            tasks[ident] = task
        seen = set()
        for row in source_rows:
            ident = key(row)
            if ident in seen:
                raise ValueError(f"duplicate run key within {directory}: {ident}")
            seen.add(ident)
            if row["task_id"] not in tasks:
                raise ValueError(f"missing task definition: {row['task_id']}")
            if row["fault"] != "clean":
                protocol = tuple(row.get(k) for k in ("category", "stage", "kind"))
                old = faults.setdefault(row["fault"], protocol)
                if old != protocol:
                    raise ValueError(f"fault protocol metadata mismatch: {row['fault']}")
            rows[ident] = dict(row)
            origins[ident] = directory
        inputs.append({"directory": str(directory), "runs_sha256": _sha(directory / "runs.jsonl"),
                       "tasks_sha256": _sha(tasks_path), "config_sha256": _sha(config_path) if config else None,
                       "run_count": len(source_rows)})
    row_protocols = {row.get("protocol_version", "legacy-unrecorded") for row in rows.values()}
    if len(row_protocols) > 1:
        raise ValueError("cannot pool different row protocol versions; analyze as separate cohorts")
    available = [c for c in configs.values() if c]
    for field in ("model", "mock", "seed", "temperature", "max_tokens", "protocol_sha256", "source_sha256",
                  "protocol_version", "verification_scope", "max_verification_retries", "source_manifest_sha256"):
        values = [c[field] for c in available if field in c]
        if values and any(v != values[0] for v in values[1:]):
            raise ValueError(f"configuration mismatch: {field}")
        if len(values) < len(configs):
            warnings.append(f"historical field unavailable in at least one input: {field}")
    # Validate every referenced path before creating outputs, preventing unsafe or partial merges.
    selected = sorted(rows, key=lambda ident: rows[ident]["run_id"])
    paths = {ident: resolve_trace_path(rows[ident]["trace"], origins[ident]) for ident in selected}
    run_ids = [rows[ident]["run_id"] for ident in selected]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("run_id collision across different experiment keys")
    if any(Path(ident).name != ident or "/" in ident or "\\" in ident for ident in run_ids):
        raise ValueError("unsafe run_id for trace destination")
    out.mkdir(parents=True)
    (out / "traces").mkdir()
    manifest = []
    for ident in selected:
        row = rows[ident]
        relative = Path("traces") / (row["run_id"] + ".jsonl")
        shutil.copy2(paths[ident], out / relative)
        manifest.append({"run_id": row["run_id"], "source_directory": str(origins[ident]),
                         "source_trace": str(paths[ident]), "sha256": _sha(paths[ident])})
        row["trace"] = relative.as_posix()
    merged = [rows[ident] for ident in selected]
    with (out / "runs.jsonl").open("w", encoding="utf-8") as stream:
        for row in merged:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "tasks.jsonl").open("w", encoding="utf-8") as stream:
        for ident in sorted(tasks):
            stream.write(json.dumps(tasks[ident], ensure_ascii=False) + "\n")
    provenance = {"schema_version": 1, "inputs": inputs, "source_configs": configs,
                  "observed_fault_metadata": faults, "selected_traces": manifest, "warnings": warnings,
                  "limitation": "observed metadata agrees; missing historical source/protocol hashes cannot be recovered"}
    (out / "merge_provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    (out / "config.json").write_text(json.dumps({"merged": True, "source_configs": configs,
                                                  **{k: available[0][k] for k in ("model", "mock", "seed")
                                                     if available and k in available[0]}}, indent=2), encoding="utf-8")
    report, _ = summarize(merged, result_dir=out)
    (out / "summary.md").write_text(report, encoding="utf-8")
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("patch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = merge(args.base, args.patch, args.output)
    print(f"Merged {len(rows)} runs into {args.output}; see merge_provenance.json for input hashes and limitations")


if __name__ == "__main__":
    main()
