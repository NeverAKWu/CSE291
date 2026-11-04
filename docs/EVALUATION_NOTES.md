# Evaluation corrections and protocol versions

Starting snapshot: teammate ZIP for commit
`d3282e99517efd9a11abde5b4b6207281372a739`.
ZIP SHA-256: `b03189d679bd7a1a9fa11fbb73e93c42a8eb9f59b59d438bacd6d3162c4b14e5`.
The original 975-run dataset is preserved; accidental and adversarial cases
remain separate. No new real-model matrix is claimed by these fixes.

The strict audit changes **0 business-success labels** in this dataset.
Authorization counts change on 100 stale/timeout runs (98 to 205 actions in
total) under the expanded manager/path policy; these are scoring-policy changes,
not additional attacks or newly executed actions. The original values remain in
`original_scores`. Adversarial no-recovery direct harmful evidence is 21 cases;
two other failures remain unattributed rather than being labeled attack-caused.

## Corrections

1. **Correctness:** the old CSV check only matched order ID. Validate team, item,
   quantity, vendor, total, file structure and finite numbers. Business `success`
   stays separate from `safe_success`, which also requires zero unauthorized
   actions over the whole run.
2. **Propagation:** compare only fault descendants; expose pre-injection and
   unrelated differences separately. Association with failure is distinct from
   direct taint-linked evidence. Semantic comparison and taint matching are
   evidence, not causal proof; a clean reference cannot eliminate model noise.
3. **Denominators:** primary results include all scheduled tasks. Show fault
   delivery and a common delivered-task subset across methods as secondary tables.
4. **Detection:** the sole rejected clean run contains a questionable researcher
   note. Without independent candidate-validity labels, report clean rejection
   rate; detector false positives and misses remain unavailable, not zero.
5. **Recovery:** preserve orders/emails across file rollback. Success excluding
   first-pass effects is counterfactual. Offline replay reconstructs simulated
   actions; it does not undo external effects.
6. **Cost:** descendants are potentially affected work, not necessarily wasted.
   Separate measured wall time from simulated timeout charges. Historical token
   totals include recorded successful responses; hidden attempts/billing are unknown.

## Runtime versions

| Property | Legacy saved experiment | Updated runtime |
|---|---|---|
| Verification | R/P only; retry unchecked | Bounded revalidation, fail closed |
| Executor verification | Absent | Explicit scope including action checks |
| Full messages/request metadata | Not collected | Recorded without credentials |
| Returned response metadata | Not collected | Recorded when API supplies it |
| Retry accounting | Successful response only | Attempts, backoff, known usage and missing-usage indicators |
| Row durability | End of matrix | Incremental completion writes |
| Source hashes | Incomplete | Captured at launch |

Runtime changes define a new experimental protocol. Mock tests validate the
harness; historical scores are reassessed from original traces, not regenerated
with new prompts. Old PDFs/figures are historical artifacts.

## Audit evidence and limits

The audit writes a new directory with original scores, revised checks,
reconstruction diagnostics and hashes of rows, tasks, traces and analysis code.
Missing/inconsistent reconstruction is reported, not guessed successful. Raw
files must remain byte-for-byte unchanged.

The audit cannot recover missing messages, API billing, hidden attempts or
historical source revisions. It cannot retroactively evaluate a stronger verifier.
Historical schedules are matched, but an enforced total inference budget was not
recorded. Token/call comparisons measure observed cost, not a budget-controlled
causal experiment. Phase 2 must freeze and enforce budgets as well as schedules.

## Phase 2 timeline (2026)

| Date | Deliverable |
|---|---|
| November 11 | Freeze schema and schedules; candidate-validity labels |
| November 18 | Dependency invalidation, selective reruns, retained-result validation |
| November 25 | File snapshots, irreversible-action reporting and compensation |
| December 2 | Matched-schedule comparisons and tracking-overhead measurements |
| December 6 | Limitations and optional detector false positives/misses |
| December 10 | Final implementation, traces and 4–6-page report |
