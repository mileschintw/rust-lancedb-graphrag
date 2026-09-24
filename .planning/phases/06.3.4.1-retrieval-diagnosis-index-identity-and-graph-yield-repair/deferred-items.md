## Deferred Items

- Pre-existing ruff debt in `eval/src` and `eval/tests`, mostly `line-too-long` (~250-300
  errors repo-wide as of 06.3.4.1-05), predates this plan and is out of scope per the
  executor's scope-boundary rule (only auto-fix issues directly caused by the current
  task's changes).
  status: open
  **What:** `uv run --project eval ruff check --preview eval/src eval/tests` does not exit
  clean, and never did before 06.3.4.1-05. The plan's own Task 2 verify command
  (`uv run --project eval pytest -q && uv run --project eval ruff check --preview eval/src
  eval/tests`) therefore cannot pass literally as written on this codebase without a
  separate cleanup pass across many unrelated files (e.g. `eval/tests/test_stage_cap.py`,
  `eval/tests/test_gate.py`'s pre-existing lines, `eval/src/lancet_eval/score.py`'s
  pre-existing lines).
  **Evidence:** Verified two ways in `06.3.4.1-05-SUMMARY.md`'s "Issues Encountered"
  section -- (1) scoping ruff to exactly this plan's 8 touched files still shows the
  pre-existing errors, all outside this plan's edits; (2) a line-by-line diff against the
  pre-plan baseline commit `179a8526` confirms zero of the remaining errors fall on a line
  this plan added.
  **Suggested resolution:** A dedicated cleanup plan (or `/gsd-quick` task) running
  `ruff check --preview --fix` across `eval/src eval/tests` plus manual review of the
  non-autofixable `line-too-long` violations, scoped as its own change so it doesn't get
  entangled with feature work's diff review.
