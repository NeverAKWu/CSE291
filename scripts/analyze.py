"""Re-analyze a finished run directory: writes summary.md and runs_enriched.csv.

  python scripts/analyze.py results/<run-dir>
"""
from __future__ import annotations

import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fpr.analysis import summarize  # noqa: E402


def main():
    out_dir = sys.argv[1]
    with open(os.path.join(out_dir, "runs.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    report, enriched = summarize(rows)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(report)

    fields = sorted({k for r in enriched for k in r if k not in ("checks", "trace")})
    with open(os.path.join(out_dir, "runs_enriched.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in enriched:
            w.writerow({k: json.dumps(v) if isinstance(v, (list, dict)) else v
                        for k, v in r.items() if k in fields})
    print(report)


if __name__ == "__main__":
    main()
