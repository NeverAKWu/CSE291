# Phase 1 report (LaTeX)

The primary editable source is `report.tex`; `report.pdf` is compiled from it.
It preserves the teammate's 10pt, two-column Letter template, 7 x 9 inch text
area, Times fonts, title, section style and table conventions. Two main pages
are followed by a timeline/fault-definition appendix. Individual names remain
omitted as requested; the author is Option 5, Group 8.

The source uses the corrected statistics and print figures in `revised/figs/`.
The original teammate source/PDF are archived byte-for-byte in `legacy/`.
The raw experiment dataset is unchanged.

The ready-to-upload [source ZIP](../artifacts/phase1_latex_source.zip) includes
the main `.tex` and all three vector figures, with a file hash manifest.

## Compile

The recommended compiler is Tectonic 0.17.0. It downloads its required TeX
packages on first use, then caches them. On this project's Linux x86_64 setup:

```bash
# From the repository root:
python3 scripts/install_tectonic.py
python3 scripts/build_audited_report.py --out /tmp/phase1-report-new.pdf
```

The installer verifies the pinned official archive SHA-256 and installs only
into the current user's cache. For other platforms, use the
[official Tectonic installation instructions](https://tectonic-typesetting.github.io/book/latest/installation/).
An existing compiler on PATH also works; set `FPR_TECTONIC` or pass
`--tectonic /path/to/tectonic` to select it explicitly.

The build wrapper isolates the reviewed `.tex` and selected PDF figures,
disables unsafe TeX features, compiles the actual LaTeX, and saves a build log
and JSON manifest with compiler, source, data, figure and output hashes. Its
output must be new. The PDF does not use a Python drawing library.

For direct editing with an installed TeX distribution, run from this folder:

```bash
tectonic --untrusted report.tex
```

Alternatively, upload `report.tex` and the `revised/figs/` folder to Overleaf
and select `report.tex` as the main document (pdfLaTeX or XeLaTeX). Keep the
folder structure so figure paths resolve. TeX packages used by the original
template are unchanged.

## Rebuild from the recorded data

Install `requirements-report.txt`, then run
`python3 scripts/audit_phase1.py --out /tmp/phase1-full-rebuild-new` from the
repository root. It runs offline tests/reassessment, regenerates print figures,
and compiles the report. No model inference is performed; first-time TeX
package download requires internet.
