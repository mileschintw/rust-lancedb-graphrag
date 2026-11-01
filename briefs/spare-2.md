Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "Confirm and start" (2026-11-01), confirming #146's plan relayed from side session local_31cb9ac6 (owner there: "可以，就這麼做"), whose free prep step (2) is "fix #128 so paper retrieval metrics (Hits@10, MRR@10) can be compared".
Depends on: none
Waits for (same section): none

- **Lane:** key `spare-2`, now #128. The issue body is the spec, plus one addition from the owner's #146 plan: chunk-ID retrieval metrics (Hits@10, MRR@10, recall/nDCG) must become evaluable on non-v1.0 stores (merged, the full 609-document stores), not only "not evaluable". Build each store's gold chunk set from the question's evidence text against that store's own chunks (the `gold_contained` matching rule, D-276 folds), per arm, and read each arm's own chunk size. Where a store has no chunk text available, report not evaluable as #125 does.
- **Branch** from origin/main (68f0009c or later) in your own worktree. Free work only; no paid calls; never use the main checkout `D:/Repos/lancet` (spare-1 holds it for #163, then #146's prep lane).
- **Files:** `eval/src/lancet_eval/score.py`, `comparison.py`, gold-chunk loading, tests. Do not touch `thresholds.py` constants or any run directory under `eval/runs/` (re-score in tests on copies only).
- **Check:** re-scoring the v1.0 lever run must keep every recorded figure unchanged (the slow test, see #152 for its existing D-276 drift; do not fix #152 here). Show one merged-store run's new Hits@10/MRR@10 in the report.
- **Rules:** no keys or env values in records; prefix commands with `PYTHONUTF8=1`; eval-only, skip cargo and Go.
- **Resumed 2026-11-01** (owner: "可以，就這麼辦"): #128 is now an S3 prerequisite, not #146 prep. Finish it: review, full checks, the merged-store demo (read-only store dumps as approved earlier), PR body. Push, write `done`; I open the PR and merge on green.
- **Then #164** (`score` always loads the v1.0 document map; the issue body is the spec), after #128 merges, on a fresh branch from main with the same rules. Its PR body says Closes #164.
- **Closes:** #128 (first PR), #164 (second PR)
