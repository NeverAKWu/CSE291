"""Offline analysis into a new directory; never overwrite raw experiment files.

  python scripts/analyze.py results/glm-flash-25tasks --output report/reanalysis
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fpr.analysis import aggregate_stats, resolve_trace_path, summarize  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_rows(directory):
    directory = Path(directory).resolve()
    path = directory / "runs_reassessed.jsonl"
    if not path.is_file():
        path = directory / "runs.jsonl"
    with path.open(encoding="utf-8") as stream:
        return path, [json.loads(line) for line in stream if line.strip()]


def write_analysis(rows, result_dir, output, *, provenance=None):
    result_dir, output = Path(result_dir).resolve(), Path(output).resolve()
    if result_dir == output:
        raise ValueError("analysis output must differ from the raw input directory")
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in ("summary.md", "runs_enriched.jsonl", "lineage.json")):
        raise ValueError("analysis outputs already exist; choose a new output directory")
    report, enriched = summarize(rows, result_dir=result_dir)
    trace_manifest = []
    for row in rows:
        trace = resolve_trace_path(row["trace"], result_dir)
        trace_manifest.append({"run_id": row["run_id"], "source_trace": str(trace), "sha256": sha256(trace)})
    (output / "summary.md").write_text(report, encoding="utf-8")
    with (output / "runs_enriched.jsonl").open("w", encoding="utf-8") as stream:
        for row in enriched:
            # Derived rows are relocatable under the known repository results tree.
            row = {**row, "trace": str(resolve_trace_path(row["trace"], result_dir))}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    fields = sorted({k for row in enriched for k in row if k not in ("checks", "trace")})
    with (output / "runs_enriched.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in enriched:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items() if k in fields})
    lineage = {"schema_version": 1, "analysis_source_sha256": sha256(Path(__file__).parents[1] / "fpr/analysis.py"),
               "analysis_driver_sha256": sha256(Path(__file__)),
               "inputs": provenance or {}, "traces": trace_manifest,
               "raw_inputs_modified": False, "runs": len(rows)}
    (output / "lineage.json").write_text(json.dumps(lineage, indent=2), encoding="utf-8")
    (output / "stats.json").write_text(json.dumps(aggregate_stats(enriched), indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, help="new directory; defaults to a sibling with -reanalysis suffix")
    args = parser.parse_args()
    source = args.source.resolve()
    path, rows = load_rows(source)
    output = args.output or source.with_name(source.name + "-reanalysis")
    print(write_analysis(rows, source, output, provenance={"runs": str(path), "runs_sha256": sha256(path)}))


if __name__ == "__main__":
    main()
