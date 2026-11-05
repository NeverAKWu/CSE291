"""Compile the audited report with the teammate's LaTeX template.

Install Tectonic 0.17.0 (or set FPR_TECTONIC). No ReportLab rendering is used.
The output PDF and build manifest must be new files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RUNS_SHA256 = "f30225f77fdc8a20f7134b5ed5da2338b5973d1231bbba429840601397a537b1"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_tectonic(explicit=None):
    requested = explicit or os.environ.get("FPR_TECTONIC")
    if requested:
        engine = shutil.which(str(requested))
        if not engine:
            raise FileNotFoundError("Requested Tectonic executable was not found")
        return Path(engine).resolve()
    system = shutil.which("tectonic")
    if system:
        return Path(system).resolve()
    cached = Path.home() / ".cache/cse291-tools/tectonic/0.17.0/tectonic"
    if cached.is_file() and os.access(cached, os.X_OK):
        return cached
    raise FileNotFoundError(
        "Install Tectonic 0.17.0 or set FPR_TECTONIC; see report/README.md")


def build(source, figures, output, *, tectonic=None):
    source, figures, output = (Path(path).resolve() for path in (source, figures, output))
    manifest_path = output.with_suffix(".build.json")
    log_path = output.with_suffix(".build.log")
    if any(path.exists() for path in (output, manifest_path, log_path)):
        raise ValueError("report output and build records must be new files")
    lineage_path = source / "lineage.json"
    lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
    if lineage.get("inputs", {}).get("runs_sha256") != EXPECTED_RUNS_SHA256:
        raise ValueError("qualitative case analysis requires the original legacy dataset")
    canonical_stats = ROOT / "results/glm-flash-25tasks-audited-v2/stats.json"
    stats = json.loads((source / "stats.json").read_text(encoding="utf-8"))
    if stats != json.loads(canonical_stats.read_text(encoding="utf-8")):
        raise ValueError("report statistics changed: update and review report/report.tex first")

    engine = find_tectonic(tectonic)
    version = subprocess.run([str(engine), "--version"], check=True,
                             capture_output=True, text=True).stdout.strip()
    tex_source = ROOT / "report/report.tex"
    if not tex_source.is_file():
        raise FileNotFoundError("report/report.tex is missing")
    # Isolate the build: only the reviewed source and chosen figures are inputs.
    # Tectonic's untrusted mode disables shell escape and other unsafe TeX features.
    with tempfile.TemporaryDirectory(prefix="phase1-latex-") as temp:
        work = Path(temp)
        (work / "report.tex").write_bytes(tex_source.read_bytes())
        target_figures = work / "revised/figs"
        target_figures.mkdir(parents=True)
        figure_hashes = {}
        for name in ("propagation.pdf", "methods.pdf", "affected_stages.pdf"):
            source_figure = figures / name
            shutil.copyfile(source_figure, target_figures / name)
            figure_hashes[name] = sha256(source_figure)
        command = [str(engine), "--untrusted", "--keep-logs", "--outdir", str(work),
                   str(work / "report.tex")]
        run = subprocess.run(command, cwd=work, capture_output=True, text=True,
                             errors="replace", timeout=300)
        tex_log = work / "report.log"
        log = run.stdout + run.stderr
        if tex_log.is_file():
            log += "\n--- LaTeX log ---\n" + tex_log.read_text(
                encoding="utf-8", errors="replace")
        output.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(log, encoding="utf-8")
        compiled = work / "report.pdf"
        if run.returncode or not compiled.is_file():
            raise RuntimeError(f"LaTeX compilation failed; see {log_path}")
        pdf = compiled.read_bytes()
        if not pdf.startswith(b"%PDF-"):
            raise RuntimeError("compiler did not produce a PDF")
        output.write_bytes(pdf)
    manifest = {
        "renderer": "LaTeX", "compiler": version,
        "source": "report/report.tex", "source_sha256": sha256(tex_source),
        "source_runs_sha256": EXPECTED_RUNS_SHA256,
        "audit_stats_sha256": sha256(source / "stats.json"),
        "audit_lineage_sha256": sha256(lineage_path),
        "figure_sha256": figure_hashes,
        "pdf_sha256": sha256(output),
        "log_sha256": sha256(log_path),
        "untrusted_mode": True,
        "overfull_hbox_warnings": log.count("Overfull \\hbox"),
        "overfull_vbox_warnings": log.count("Overfull \\vbox"),
        "undefined_reference_warnings": log.count("undefined references"),
        "protocol": "historical R/P verification; no new model inference",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "results/glm-flash-25tasks-audited-v2")
    parser.add_argument("--figures", type=Path, default=ROOT / "report/revised/figs")
    parser.add_argument("--out", type=Path, default=ROOT / "output/pdf/phase1_audited_report.pdf")
    parser.add_argument("--tectonic", help="compiler executable; otherwise PATH or FPR_TECTONIC")
    args = parser.parse_args()
    build(args.source, args.figures, args.out, tectonic=args.tectonic)
    print(args.out.resolve())


if __name__ == "__main__":
    main()
