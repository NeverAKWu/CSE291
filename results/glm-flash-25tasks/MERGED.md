Merged GLM result (25 tasks, 975 runs). Built in two steps with scripts/merge_runs.py:

1. results/glm-flash-10tasks (tasks 0-9, full matrix)
   + results/glm-flash-10tasks-researcher-patch (90 rows: researcher wrong_price /
   wrong_vendor / stale rerun after those faults were made internally consistent)
2. + results/glm-flash-tasks10-24 (tasks 10-24, full matrix)

Trace paths in runs.jsonl point into those three directories, so keep them.
