# Review: Phase 06.3.4 ??Corrected Re-Drive, Calibration, and Root-Cause Documentation

Reviewed against `D:\Repos\lancet` at `2969a4c`. Every code/line reference below was checked against the working tree; observations marked **[verified]** were confirmed by reading files or running read-only commands, **[observed]** are environmental facts from this machine.

## Cross-cutting findings (apply to several plans)

**CC-1 ??Mixed POSIX + `uv` verify commands run in neither available shell as written (MEDIUM).** Plans 03, 04, 05 and 06 use `<automated>` lines of the form `RUN=$(uv run ...) && uv run ... && D=... && test -s ... && grep ...`. On this machine `uv` resolves to `C:\Users\user3\.local\bin\uv.exe` in PowerShell, but inside `bash -c` neither `uv` nor `python` is on `PATH` **[observed]**. PowerShell 7 cannot run `RUN=$(...)`, `D=...;`, `test -s`, or `! grep`. The 06.3.3 precedent the plans lean on (`06.3.3-02-SUMMARY.md` ran `bash -c 'test -s ... && grep ...'`) only proves the `test`/`grep` idiom, not `uv` inside bash. Pure-pytest verifies (01 T1/T2, 02, 05 T1) and pure-POSIX verifies (01 T3, 06 T1/T2, 07) are fine. Fix: either make bash's PATH include `~/.local/bin` as an explicit step in `06.3.4-DRIVE-PRECONDITIONS.md`, or split the verify into a Python-only script invoked via `uv run` that performs the file/grep checks itself.

**CC-2 ??Per-invocation cap semantics on resume (MEDIUM).** The stop rule being ported (`measure.py:505-514`) sums `compute_spend(records, ...)` over the in-memory `records` list of *this* invocation **[verified]**. Ported verbatim into `drive()`, a capped stop followed by `--resume` resets spend to zero, so the "$5.00 full" cap becomes "$5.00 per invocation". Plan 04 says resuming "requires a fresh recorded decision", but that is process control, not the fail-closed mechanism BUDGETS asks for. Plan 01 should state the semantics explicitly (per-invocation vs. cumulative-in-journal), and ideally make `drive()` seed spend from records already in the journal for the same stage.

**CC-3 ??Overshoot bound is unstated (LOW).** The check is `spend >= cap` *before* dispatch, so sequential mode can overshoot by one query and pooled mode by up to `workers` in-flight queries. With graph-on p95 of ~30 s and generation pricing, this is small in dollars, but the plans should record the bound so a reader of the summary doesn't read a $2.07 stage as a cap failure.

**CC-4 ??Two sources for the full-drive cap (LOW).** Plan 01's `gate.py` reads caps from `06.3.3-BUDGETS.md` at runtime (coupling eval code to a `.planning/` path). Plan 04 passes `--stage-cap <figure from 06.3.4-STAGED-GATE.md's decision entry>` ??an operator-transcribed figure, which is the thing the plans elsewhere forbid. Either have the gate's decision entry be machine-readable and read by the same reader, or state that the full-drive figure is transcribed and cross-checked against BUDGETS' $5.00.

**CC-5 ??"Landed sibling contracts" tables are accurate [verified].** `NOTICE_CODE_RETRIEVAL_FAILED = 19` at `lancet.proto:96`; tags 16/18 are `RETRIEVAL_DEGRADED_BM25`/`GRAPH_ABLATION`; `resolve_run_dir` (`cli.py:214-227`) globs `????-??-??-{corpus}` and takes `max()` by name, so `--resume` with no corrected dir selects `2026-09-03-multihop_rag`, and `2026-09-06-measure-multihop_rag` does **not** match the glob; `journal.py:write_header` is one-shot; `render_markdown`/`render_json` raise on `partial`; `score_run` skips `report.json` on a partial header; `DimensionResult` is `extra="forbid"` with `detail: dict[str, float]` and forbids `reason` on `ok`; `eval/pyproject.toml` has no numpy/scipy, so the standard-library constraint in Plan 02 is real; the superseded run dir has exactly 7 tracked files, satisfying Plan 06's `-ge 7`.

---

## 06.3.4-01 ??Tracer: gate evaluator, header reconciliation, stage cap, drive preconditions

**Summary.** The strongest plan in the set. It correctly identifies the two latches that would otherwise sink the staged-then-full design (the one-shot `partial` header and the newest-match resolver), puts the resolver-identity check in a `<precondition>` before any paid call, and ports a real in-process stop rule instead of relying on operator vigilance. Key names it reads (`graph_ablation_delta.detail["pairing_coverage"]`, `graph_presence_rate` + `detail["no_match_rate"]`, `graph_influence_rate`) match `dimensions.py` **[verified]**. The micro-slice (`--no-resume --limit 2`) hits two `comparison_query` questions with gold evidence (`mhr-0073?圳, `mhr-0085?圳) **[verified]**, so the tracer will actually form pairs rather than exercise only the empty-input branch.

**Strengths.**
- Halt-on-absent-key with no defaulting; test fixture built from `dimensions.py` builders so a rename fails the test, not the drive.
- `--stage-cap` required on `run` (Typer error on omission) rather than copying `measure`'s `= 5.0`.
- Task 3 `git diff --quiet -- eval/runs/2026-09-03-multihop_rag/` guards the superseded run's immutability at every step.
- Edge semantics (??at floor satisfies; trigger fires strictly above) are pinned in tests.

**Concerns.**
- **MEDIUM (CC-2)** ??resume resets the cap; state and test the semantics.
- **MEDIUM** ??`staged-gate` calls `score_run(..., judge=False)` on a 4-record journal. `score_run` runs the full dimension set; confirm none of the non-judged dimensions raises on tiny N (e.g., `graph_presence_rate` needs usable graph-on records with `workflow_meta`; if the micro-drive's engine build doesn't emit it, the gate will legitimately halt and the tracer's "chain proven" claim fails for a reason unrelated to the gate).
- **LOW** ??`gate.py` parsing a markdown table in `.planning/` at runtime is brittle; a test needs a fixture copy and the parser must fail loudly on a column reorder (the plan says it raises on absent/unparseable ??good, but a *wrong* column that still parses as a number would not be caught).
- **LOW** ??Header reconciliation (`reconcile` command) flips `partial` from `True` to `False` by rewriting line 1 of a journal. The plan should require an atomic write (`journal.jsonl.tmp` + rename; the `.gitignore` already ignores `journal.jsonl.tmp` **[verified]**) and refuse if any non-header line count differs after rewrite.

**Suggestions.**
- Define `stage_spend_cap` as cumulative over the journal for the current stage, or record "per-invocation" in DRIVE-PRECONDITIONS with the resume caveat.
- Add a test that `reconcile` refuses when `limit` was applied in the most recent invocation (i.e., the reconciliation should only be legal after an unlimited resume completes the sample).
- Record expected overshoot bound (`workers ? max per-query cost`) beside the cap in the summary.

**Risk: LOW?EDIUM.** Well-grounded; residual risk is in cap semantics on resume and the runtime coupling to a planning doc.

---

## 06.3.4-02 ??Agreement statistics and report carriage

**Summary.** Correct and carefully scoped. QWK with explicit scale bounds and tie-aware Spearman (Pearson over mid-ranks) are the right formulations; the `AgreementResult(value|None, state)` shape is a good fit for `detail: dict[str, float]` and the `reason`-on-`ok` prohibition **[verified]**. Golden vectors from published examples, order-invariance and no-NaN tests are appropriate.

**Strengths.**
- Standard-library-only is verified by import inspection plus `uv lock --check`.
- Degenerate branches (`undefined_zero_variance`, `undefined_expected_agreement`) are named states, not exceptions or NaN ??important at N=12.
- `calibration_completed_n` field designed to coexist with 05's `calibration_size_committed`.

**Concerns.**
- **MEDIUM** ??At N=12 the sampling variance of both 庥 and ? is large; a point-estimate ??0.70 pass/fail is fragile in both directions. The plan computes no interval or permutation p-value. `stats.py` has `bootstrap_mean_ci` but nothing for correlation.
- **LOW** ??The plan cites "existing `test_dimensions.py` coverage of that validator"; the file tests `ok`-requires-score, `skipped`/`error` branches and `extra="forbid"`, but has **no** test for `ok`-cannot-carry-`reason` **[verified]**. Task 2 should add it since it's the constraint the design depends on.
- **LOW** ??Currently `score.py:503-505` silently skips worksheet rows whose cache key has no verdict **[verified]**; Task 2 must count those as exclusions (the plan implies it but should say so in acceptance criteria).

**Suggestions.**
- Add a bootstrap CI over row resampling for both statistics (pure Python, seeded), carried as `*_ci_lower/upper` floats, and have 05's disposition read the interval, not just the point.
- Add the missing validator test.

**Risk: LOW.** Pure offline code with strong tests.

---

## 06.3.4-03 ??Staged drive and gate verdict (blocking-human checkpoint)

**Summary.** Sound sequencing: preflight ??`--resume --limit 50 --stage-cap 2.00` ??`staged-gate` ??dated decision entry. The plan correctly anticipates that null-gold questions cap achievable pairing coverage below 1.0: `form_pairs` drops null gold but `total_distinct_questions` still counts them, and `pairing_coverage = n_pairs / total_distinct_questions` **[verified]**. The first 50 sample questions contain 5 `null_query` **[verified]**, so the ceiling is 0.90 against a 0.80 floor ??only 5 answerable drops of headroom.

**Strengths.**
- Explicit derivation of the coverage ceiling in the ledger rather than restating the floor.
- Differentiates a coverage miss (stop) from a yield miss (provisional floor; investigate before 6.4) ??matches AI-SPEC's provisional wording.
- Spend/allowance read before and after as corroboration of the mechanical cap.

**Concerns.**
- **MEDIUM (CC-1)** ??both verifies are `uv`-inside-bash.
- **MEDIUM** ??Headroom is tight: with 45 answerable questions in the prefix, any 6 usable/provenance/missing-arm drops fails the 0.80 floor. The plan should pre-state this so the checkpoint reader knows a 0.78 is "4 drops too many", not a collapse.
- **LOW** ??`--resume` into the micro-drive's directory relies on it being lexicographically newer than `2026-09-03`. If 01 and 03 run on the same day this is fine; if 03 runs on a *later* day without `--resume` it creates a second directory and the "exactly one corrected run" assertion fails ??correct behaviour, but the plan should say the intended path is always `--resume` after 01.

**Suggestions.**
- Put "ceiling = (50 ??nulls)/50 = 0.90; floor 0.80 ????5 answerable drops" in the gate rendering itself.
- Consider also rendering coverage over answerable questions (`n_pairs / n_answerable`) as an additional detail float so the reader sees both.

**Risk: MEDIUM.** First paid drive after the collapse; controls are good, but margin against the coverage floor is narrow and the verify commands need the shell fix.

---

## 06.3.4-04 ??Full two-arm drive, reconcile, publish

**Summary.** Correct dependency on 03's decision entry via `<precondition>`, and the "one-way task with no in-file checkpoint" is deliberately explained. Sequence `run --resume --stage-cap` ??`reconcile` ??`score --no-judge` ??`report` is consistent with the landed latches: `score_run` will only write `report.json` after the header is `partial: False`, and `render_*` will only render then **[verified]**.

**Strengths.**
- Index-generation attribution verified per record (`unattributable`, `snapshot_only` counts) ??directly addresses the 966-blank-generation failure in the superseded journal **[verified: 966/1000 blank]**.
- Duplicate work-unit key assertion.

**Concerns.**
- **MEDIUM (CC-2/CC-4)** ??Cap semantics on resume and operator-transcribed figure.
- **MEDIUM** ??A capped stop mid-full-drive leaves a journal with `partial: True` (header from 01's `--limit 2`) and an incomplete sample. `reconcile` must refuse to flip the header unless record count == 2 ? sample size (1000) and both arms present per question; the plan says it flips "when the sample is complete" ??make that check explicit and tested (record count, arm parity, no duplicates, one index generation).
- **LOW** ??`score --no-judge` publishes a report with groundedness/faithfulness `skipped` (`score.py:770`) **[verified]**; 05 republishes. Fine, but the 04 summary should label the intermediate report as pre-calibration so it isn't cited.

**Suggestions.**
- Make `reconcile` compute completeness from `questions.sample.jsonl` (500 ? 2 arms) rather than trusting the operator.
- Have the drive summary record wall-clock and per-arm p50/p95 from `node_timings` for the 6.4 write-up.

**Risk: MEDIUM.** Largest spend; mechanical cap present but resume semantics undefined; reconcile is the new single point where an incomplete run could be marked publishable.

---

## 06.3.4-05 ??Fresh calibration (N=12) and republish

**Summary.** Correctly refuses to carry forward the 16 superseded human scores and forbids agent back-fill via a blocking-human checkpoint. Worksheet-size option and `calibration_size_committed` metadata field tie the committed N to the report. `--stage-cap` required on `score` when judging is on ??consistent with BUDGETS' $5.00 judging cap.

**Strengths.**
- Worksheet validation (one header, non-null `cache_key`, blank human fields) before the human step.
- Acceptance asserts `ok` judged dimensions carry no `reason` ??matches the validator.

**Concerns.**
- **MEDIUM** ??Judge spend cap on `score`: unlike `drive()`, judging iterates a sampled slice and caches to `judge_cache.json`. A cap stop mid-judging leaves a partially-judged sample; the plan should define whether groundedness/faithfulness then publish as `ok` with reduced `n`, or `skipped` with a reason naming the cap. Publishing a reduced-n `ok` silently would repeat the 06.3.1 false-green pattern in miniature.
- **MEDIUM** ??With N=12 and a ??0.70 target on two statistics for two dimensions (four comparisons), the chance of at least one point estimate falling below 0.70 under true agreement ??0.75 is substantial. Without CIs (see 02), the "uncalibrated" label may be applied for noise. Decide in advance whether the label is per-dimension or global, and whether a CI overlapping 0.70 counts.
- **LOW** ??Worksheet selection should be deterministic and stratified by question type (the sample is 500 with a known type distribution); the plan should name the seed and stratification so the 12 rows are reproducible.
- **LOW (CC-1)** ??Task 2/4 verifies.

**Suggestions.**
- Carry the agreement CI (from 02) and define the label rule on it.
- Record the judge's exact model id and prompt version hash (`JUDGE_SYSTEM_V1`) in metadata alongside the agreement figures.

**Risk: MEDIUM.** Small-N statistics plus a human-in-the-loop step; mechanical controls are adequate, statistical decision rule is under-specified.

---

## 06.3.4-06 ??Root-cause doc, SUPERSEDED marker, docs, ROADMAP update

**Summary.** Documentation-only plan with tight, greppable verifies. Dependencies (`06.3.3-MEASUREMENT.md`, `STORE-BASELINE.md`, `decay_present: False`, `populated` store) exist and say what the plan says they say **[verified]**. The ROADMAP verify locates the single "notice-code vocabulary" line in the 6.4 entry (`ROADMAP.md:896`) **[verified]** and diff-checks that only that line changed ??good discipline.

**Strengths.**
- Immutability of the superseded run enforced by `git status --porcelain` filtering for `SUPERSEDED` only.
- `-ge 7` tracked-file assertion matches reality.
- Notice-code name derived from the proto at the free tag rather than typed.

**Concerns.**
- **LOW** ??Notice codes are exposed by the gateway with the `NOTICE_CODE_` prefix trimmed (`gateway/main.go`) **[verified]**; the doc should state the wire form (`RETRIEVAL_FAILED`) and the proto form, since the existing ROADMAP line already uses the trimmed form.
- **LOW** ??Task 1's root cause must cite `process_state` as the *supported* hypothesis, not proven; MEASUREMENT.md frames it that way, and the doc should not upgrade it.
- **LOW (CC-1)** ??Task 3 verify uses `uv` (but is pure Python; runs fine from PowerShell if the surrounding shell is PowerShell ??the only issue is if run under bash).

**Suggestions.**
- Add a one-line forward reference from `SUPERSEDED.md` to the corrected run directory's literal path pinned in DRIVE-PRECONDITIONS.

**Risk: LOW.**

---

## 06.3.4-07 ??Findings: yield disposition and ablation reading

**Summary.** Reads the republished report by dimension/detail key and writes `06.3.4-FINDINGS.md`. Scope is correct ??it interprets, it does not re-score. Verifies are pure POSIX and consistent with the 06.3.3 precedent.

**Strengths.**
- Reads `graph_presence_rate`, `graph_influence_rate`, `graph_ablation_delta` with stratification and intervals by key, so a rename fails loudly.
- Superseded-run immutability re-asserted.

**Concerns.**
- **MEDIUM** ??The plan should state how a *provisional* yield-floor miss (allowed to proceed under 03) is dispositioned here: the yield investigation is "owed before 6.4 publishes", and 07 is the last plan before 06 (wave 6). If the miss persists at full scale, 07 must either contain the investigation or explicitly open a follow-up phase; otherwise the debt is silently discharged.
- **LOW** ??Ablation delta interpretation must condition on pairing coverage and `excluded_unscorable_pairs` (`dimensions.py:104-109`) **[verified]**; the plan should require both to be quoted next to the delta.
- **LOW** ??Stratified deltas per question type at N??0??20 per stratum will have wide intervals; state that stratum-level conclusions are descriptive.

**Suggestions.**
- Add an explicit "open items for 6.4" section with the yield investigation status as a required row.

**Risk: LOW?EDIUM.** Interpretive; the risk is under-disposition of a provisional miss.

---

## Overall assessment

The phase is well-structured and the plans have absorbed the prior review round accurately: the landed-sibling tables are correct against the tree, the resolver and header latches are handled before paid calls, and cap enforcement is mechanical. The residual risks that should be fixed before execution are (1) the `uv`-inside-bash verify commands (CC-1), which will fail as written on this machine; (2) undefined stage-cap semantics on `--resume` (CC-2), which matters most for Plan 04; and (3) the under-specified N=12 agreement decision rule (Plans 02/05). None require redesign.
