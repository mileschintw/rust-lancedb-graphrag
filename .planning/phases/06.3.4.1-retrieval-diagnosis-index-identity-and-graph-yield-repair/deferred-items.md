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

- `uv run --project eval pytest -q` from the repo root fails one Phase 02 test under plain pytest (06.3.4.1-21)
  status: open
  **What:** `scripts/test_phase02_live_evidence.py::Phase02LiveEvidenceTests::test_wrong_model_is_rejected_in_optimized_isolated_subprocess`
  asserts `sys.flags.optimize == 1`, so it needs an `-O` interpreter. Plain `pytest -q` collects `scripts/` and
  reports 1 failed / 746 passed; `python -O -m pytest scripts/test_phase02_live_evidence.py` passes 26/26.
  It is an interpreter-flag artifact, unchanged by 06.3.4.1-21 (`pytest eval/tests` alone is 721/721). Any plan
  criterion that reads "`pytest -q` exits 0" from the repo root cannot pass literally until that test is
  scoped, skipped without `-O`, or the invocation is fixed.
  **Evidence:** baseline run before any 06.3.4.1-21 edit, and the STATE.md 2026-09-13 note on the same test.

- Ruff totals after 06.3.4.1-21 (context for the entry above)
  status: resolved
  **What:** `ruff check --preview eval/src eval/tests` reported 565 findings before this plan and 550 after (new
  files `decay_materiality.py` and `test_decay_materiality.py` are clean; the drop is docstring reflow in
  `flatness.py`). The plan's verify line over `flatness.py`/`oi02.py`/`thresholds.py` cannot read zero because
  `flatness.py` (15) and `oi02.py` (109) carry older `line-too-long` findings.

- Ruff findings already in `eval/src/lancet_eval/cli.py` make 06.3.4.1-28 Task 3's ruff verify unreadable as zero (06.3.4.1-28)
  status: open
  **What:** `ruff check --preview eval/src/lancet_eval/cli.py` reports 10 findings (9 `line-too-long` and 1 `too-many-blank-lines`, lines 445-694 after this plan) in the `reconcile`, `score` and `run` commands. The same 10 are present at the planning base `a58c6ae2`, so they predate 06.3.4.1-28. The plan's verify line lists `cli.py` among three files and reads exit 0, which cannot hold until those lines are fixed. `preflight.py` and `test_preflight_accepted_miss.py` are clean, and 06.3.4.1-28 added no finding to `cli.py`. Not fixed here: unrelated code outside the task.
  **Evidence:** `ruff check --preview --output-format concise` on `git show a58c6ae2:eval/src/lancet_eval/cli.py` (10 errors) and on the committed file (the same 10).

- `config_startup::initial_bm25_failure_blocks_readiness` can fail on a port race (06.3.4.1-16)
  status: open
  **What:** the test starts the engine with a failing BM25 build and asserts nothing listens on a port it picked; in one full `cargo test` run it reported `engine must not open a listening socket at 127.0.0.1:62503`, and it passed alone on the rerun. Another process on the machine can hold the port. No 06.3.4.1-16 change touches startup.
  **Evidence:** the full-run log and the single-test rerun of 2026-10-06.
