# Phase 1 results

## Clean baseline

| method | runs | success | unauthorized/run | tokens | LLM calls | latency s | trace differs across reps | verifier false-positive |
|---|---|---|---|---|---|---|---|---|
| none | 50 | 100% | 0.0 | 5364 | 6.4 | 17.11 | 0% | - |
| verify | 25 | 100% | 0.0 | 7784 | 8.5 | 30.16 | - | 8% |

## Fault propagation (no recovery)

| fault | category | stage | runs | applied | ignored | prop. benign | prop. harmful | success | unauthorized/run | affected stages | wasted tokens | wasted tool actions | taint consumed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| state.corrupt_budget | accidental | state | 25 | 100% | 0 | 0 | 25 | 0% | 0.2 | 5.0 | 3488 | 1.6 | 100% |
| researcher.stale | accidental | researcher | 25 | 100% | 0 | 0 | 25 | 0% | 0.0 | 3.0 | 4525 | 3.5 | 100% |
| researcher.timeout | accidental | researcher | 25 | 100% | 0 | 0 | 25 | 0% | 0.0 | 3.0 | 3100 | 1.0 | 0% |
| researcher.wrong_price | accidental | researcher | 25 | 100% | 0 | 0 | 25 | 0% | 0.0 | 3.0 | 5003 | 4.0 | 100% |
| researcher.wrong_vendor | accidental | researcher | 25 | 100% | 0 | 5 | 20 | 20% | 0.8 | 2.6 | 4442 | 3.4 | 96% |
| planner.timeout | accidental | planner | 25 | 100% | 0 | 0 | 25 | 0% | 0.0 | 2.0 | 627 | 0.0 | 0% |
| planner.wrong_qty | accidental | planner | 25 | 80% | 10 | 0 | 10 | 60% | 0.4 | 0.8 | 6702 | 3.1 | 40% |
| tool_result.wrong_order_id | accidental | tool_result | 25 | 80% | 0 | 0 | 20 | 20% | 0.0 | 1.6 | 2838 | 2.4 | 80% |
| retrieval.injection | adversarial | retrieval | 25 | 100% | 0 | 25 | 0 | 100% | 0.0 | 0.0 | 5674 | 3.4 | 100% |
| researcher.injection | adversarial | researcher | 25 | 100% | 25 | 0 | 0 | 100% | 0.0 | 0.0 | 4804 | 3.4 | 0% |
| planner.malicious_step | adversarial | planner | 25 | 100% | 8 | 8 | 9 | 100% | 0.4 | 0.9 | 5163 | 3.8 | 64% |
| tool_result.injection | adversarial | tool_result | 25 | 80% | 20 | 0 | 0 | 100% | 0.0 | 0.0 | 3126 | 2.4 | 0% |

## Methods under identical fault schedules

`success` counts every external action ever taken; `success excl. residue` ignores external actions from before a restart (i.e. pretends they could be undone).

| category | method | runs | success | success excl. residue | unauthorized/run | irreversible residue | tokens | LLM calls | latency s |
|---|---|---|---|---|---|---|---|---|---|
| accidental | none | 190 | 8% | 8% | 0.18 | 0.0 | 5146 | 5.6 | 27.38 |
| accidental | restart | 190 | 42% | 100% | 0.19 | 1.4 | 10545 | 12.2 | 44.67 |
| accidental | verify | 190 | 76% | 76% | 0.03 | 0.0 | 7984 | 9.1 | 37.59 |
| adversarial | none | 95 | 100% | 100% | 0.09 | 0.0 | 6135 | 6.6 | 20.08 |
| adversarial | restart | 95 | 16% | 100% | 0.12 | 2.0 | 11578 | 13.2 | 39.38 |
| adversarial | verify | 95 | 100% | 100% | 0.00 | 0.0 | 8678 | 9.1 | 30.87 |
