# Deferred Items (Phase 06.3.5)

## Deferred Items

- 06.3.5-10: `eval/src/lancet_eval/score.py` carries 22 pre-existing ruff findings
  status: open
  **What:** `ruff check --preview eval/src/lancet_eval/score.py` reports 22 findings (21 `E501` line-too-long, 1 `I001` unsorted-imports). All 22 exist at 32bdc18e, before this plan; 06.3.5-10 added none (its new lines are clean).
  **Why it matters:** the Task 3 `<verify>` of 06.3.5-10 runs `ruff check --preview` over `score.py` and requires a zero exit, so that command cannot pass until the findings are fixed. Every other file in that command (`strata.py`, `paper_text_crosscheck.py`, the three new test files) is clean.
  **Out of scope:** the findings are in code this plan did not write (the legacy per-arm loop, the judge loop and the report assembly). Also logged in `.planning/WINDOWS.md` as a `lint-warning`.
