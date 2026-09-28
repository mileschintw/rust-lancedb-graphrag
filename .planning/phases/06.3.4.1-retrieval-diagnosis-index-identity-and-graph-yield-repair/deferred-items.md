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

- `flatness.records_from_run_journal` returns n=0 on every `measure` journal (06.3.4.1-11)
  status: open
  **What:** it loads lines via `journal.load_records`, which validates as `RunRecord`
  (`extra="forbid"`) and silently skips `MeasurementRecord` lines (`ordinal`, `segment`,
  `warm_up`, ...). `flatness_verdict` then reports `reason="n=0"`. Reproduced on pass A's
  journal and on 06.3.3's `2026-09-06-measure-multihop_rag`. `oi02.load_timeline_records`
  already falls back across both shapes; the flatness loader does not.
  **Evidence:** `06.3.4.1-BUDGETS.md` "flatness.py" table.

- OI-02 instrumentation reaches Loki lossily under the engine's unfiltered log volume (06.3.4.1-11)
  status: open
  **What:** pass A delivered `request_process_state` for 287/324 requests and
  `retrieve_hybrid_substages` for 236/324 executions while the engine emitted ~12.7M
  trace/debug lines in 41 minutes. Cause unverified (exporter/batch queue, collector or
  Loki ingestion). Drive 1's live OI-02 diagnosis depends on these events arriving.
  **Evidence:** `data/oi02-evidence/passA-2026-09-28/loki/manifest.json`, `06.3.4.1-BUDGETS.md`.

- `measure.compute_spend` undercounts real provider spend (06.3.4.1-11)
  status: open
  **What:** pass A's estimate was $0.0748 against an OpenRouter usage delta of $0.2178.
  Records whose `GenerateAnswer` failed carry zero wire tokens but were billed, so the
  `--stage-cap` stop-rule runs on a low estimate.
  **Evidence:** `06.3.4.1-BUDGETS.md` "Stage caps (D-86)".
