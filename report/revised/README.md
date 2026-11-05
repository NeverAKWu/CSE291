# Revised Phase 1 evaluation

Read the [audited report](../../output/pdf/phase1_audited_report.pdf) (2 main
pages plus timeline appendix) and [full numerical tables](../../results/glm-flash-25tasks-audited-v2/summary.md).

These compact print figures use all 25 scheduled tasks per fault as the primary denominator.
Common-delivery results are reported separately. `stats.json` exactly matches
the audited result directory. The primary LaTeX source and compiled PDF are
`../report.tex` and `../report.pdf`. Original reports are in `../legacy/`, and
original figures remain in `../figs/`.

Rebuild using `python3 scripts/audit_phase1.py --out /tmp/phase1-rebuild-new`
from the repository root after installing `requirements-report.txt` and
Tectonic. See `../README.md`. No model inference is performed.
