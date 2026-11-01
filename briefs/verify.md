Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "Start it" (2026-11-01), after "Do both" opened the literature-check verification issues.
Depends on: none
Waits for (same section): none

- **Lane:** key `verify`. Four free verification issues; each issue body is its spec: #165 (always-Yes baseline), #166 (official `qa_evaluate.py` on insufficient-information answers), #168 (exact CI for 2Wiki Opus +14), #169 (precision of Haiku's extra relations). Context: `D:/Repos/lancet-coord/reports/lit-check/` (read only; never copy it into the repo).
- **Branch** from origin/main in your own worktree; one PR for all four is fine (Closes #165 #166 #168 #169), or split if one stalls. Never use the main checkout `D:/Repos/lancet` (spare-1 holds it for #163).
- **Read-only** on committed run dirs under `eval/runs/` and `experiments/v1.1/`; never edit them. No held-out reads (D-237); #149's fresh splits' dev parts only.
- **#166:** you may fetch only `qa_evaluate.py` (and what it imports from the same repo) from MultiHop-RAG's official GitHub repo into your scratchpad; run it with `-I`, never install it.
- **#169:** judge by hand, or with a cheap OpenRouter model (no Claude credit); OpenRouter ceiling $1, print the estimate first.
- **Files you own:** new scripts under `eval/scripts/` or `eval/src/lancet_eval/`, their tests, and one short section per finding in the EXPERIMENT/EXPLORE/WRITER-PILOT file the issue names. `score.py` and `comparison.py` belong to spare-2 (#128, #164): do not edit them.
- **Rules:** no keys or env values in records; prefix commands with `PYTHONUTF8=1`; eval-only, skip cargo and Go.
- **Finish:** push, write `done`; I open the PR and merge on green.
- **Closes:** #165 #166 #168 #169
