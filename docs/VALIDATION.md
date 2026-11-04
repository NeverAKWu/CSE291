# Validation of the evaluation-fixes branch

Validated locally on November 4, 2026, without model API calls.

- 42 standard-library regression tests pass, covering strict CSV/money checks,
  cumulative safety, irreversible effects, trace consistency, causal-label
  conservatism, cross-platform paths, denominator matching, merge validation,
  bounded verification, visible API retries and incremental outputs.
- One-command audit (`scripts/audit_phase1.py`) completes: tests, replay of 975
  original runs, figures and a 3-page PDF. Rebuilt `stats.json` is exactly equal
  to the committed audit.
- All 17,298 historical artifact hashes match. Every actual simulated tool result
  replays consistently. Original tracked results and original report/figures have
  no diff from upstream commit `d3282e9`.
- 117 new mock runs (3 tasks x 39 schedules including clean controls) finish with
  zero harness failures. Offline replay agrees with all 117 native rows across
  ten business/safety/irreversible-effect fields. This validates the new harness,
  not real-model effectiveness.
- The revised PDF has 2 main pages plus 1 timeline appendix. All pages were
  rendered and inspected; fonts are embedded. Full-size figures are available
  in `report/revised/figs/`.

Raw original calls: 8,509 recorded successful responses; 5,770,667 input and
1,235,682 output tokens. No actual gateway billing or unrecorded attempts are
inferred. This branch adds no inference spend.

Use a new output directory when reproducing. The committed audit is derived
evidence; `lineage.json` records source rows/tasks/traces/checker/analysis hashes.
