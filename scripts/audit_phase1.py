"""One-command, zero-inference rebuild: tests -> replay audit -> figures -> PDF.

Install requirements-report.txt first. --out must be a NEW directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "output" / (
        "audit-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    args = parser.parse_args()
    output = args.out.resolve()
    if output.exists():
        parser.error("--out must be new; existing evidence is never overwritten")
    if find_spec("matplotlib") is None:
        parser.error("install dependencies: python3 -m pip install -r requirements-report.txt")
    sys.path.insert(0, str(ROOT))
    from scripts.build_audited_report import find_tectonic
    try:
        find_tectonic()
    except FileNotFoundError as exc:
        parser.error(str(exc))
    commands = [
        ["-m", "unittest", "discover", "-s", "tests", "-v"],
        ["scripts/reassess.py", "results/glm-flash-25tasks", "--out", str(output / "results")],
        ["scripts/plots.py", str(output / "results"), str(output / "figs"), "--compact"],
        ["scripts/build_audited_report.py", "--source", str(output / "results"),
         "--figures", str(output / "figs"), "--out", str(output / "phase1_audited_report.pdf")],
    ]
    for step, command in enumerate(commands, 1):
        print(f"[{step}/{len(commands)}] {command[0]}", flush=True)
        subprocess.run([sys.executable, *command], cwd=ROOT, check=True)
    print(f"Complete: {output}", flush=True)


if __name__ == "__main__":
    main()
