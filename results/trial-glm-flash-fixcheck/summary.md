# Phase 1 results

## Clean baseline

| method | runs | success | unauthorized/run | tokens | LLM calls | latency s | trace differs across reps | verifier false-positive |
|---|---|---|---|---|---|---|---|---|
| none | 6 | 100% | 0.0 | 5971 | 7.0 | 46.64 | 0% | - |

## Fault propagation (no recovery)

| fault | category | stage | runs | applied | ignored | prop. benign | prop. harmful | success | unauthorized/run | affected stages | wasted tokens | wasted tool actions | taint consumed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| researcher.timeout | accidental | researcher | 3 | 100% | 0 | 0 | 3 | 0% | 0.0 | 3.0 | 2323 | 1.0 | 0% |
| planner.wrong_qty | accidental | planner | 3 | 100% | 3 | 0 | 0 | 100% | 0.0 | 0.0 | 4833 | 4.0 | 0% |

## Methods under identical fault schedules

`success` counts every external action ever taken; `success excl. residue` ignores external actions from before a restart (i.e. pretends they could be undone).

| category | method | runs | success | success excl. residue | unauthorized/run | irreversible residue | tokens | LLM calls | latency s |
|---|---|---|---|---|---|---|---|---|---|
| accidental | none | 6 | 50% | 50% | 0.00 | 0.0 | 4740 | 5.5 | 35.00 |
