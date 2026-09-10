## 06.3.4-01

### Summary

This plan correctly diagnoses three live harness defects that would otherwise destroy the corrected run: `Journal.write_header` latches `partial` on first write (`eval/src/lancet_eval/journal.py:113??24`), `score` / `render_markdown` refuse a partial journal (`eval/src/lancet_eval/cli.py:348??55`, `eval/src/lancet_eval/report.py:149??53`), and `resolve_run_dir(..., resume=True)` would append to `eval/runs/2026-09-03-multihop_rag/` (`eval/src/lancet_eval/cli.py:214??27, 256??62`). The committed floors, `--no-resume --limit 2` first invocation, and one-way header reconcile are the right machinery. The spend-cap work is specified against a control flow that does not exist: `drive()` has no sequential loop and submits every remaining work unit to `ThreadPoolExecutor` before any result is observed (`eval/src/lancet_eval/run.py:218??37`). Porting `measure.py:505??14` as written will not halt spend on this driver.

### Strengths

- The header latch, score-render refusal, and newest-match resume hazard are all real and cited at the right lines. `write_header` only fires when the file is missing or empty (`journal.py:115`); `score_run` still returns a report for a partial journal but skips `report.json` (`score.py:1065??069`); the `score` CLI then raises on `render_markdown`.
- Decision inputs match `06.3.1-AI-SPEC.md` (coverage 0.80 at-or-above, yield 0.20 at-or-above, complement strictly above 0.80, calibration N=12, kappa and Spearman ??0.70). Caps are read from `06.3.3-BUDGETS.md` ($2.00 / $5.00 / $5.00) rather than restated.
- Gate key names match landed builders: `graph_ablation_delta.detail["pairing_coverage"]` (`dimensions.py:95??06`), `graph_presence_rate.score` and `detail["no_match_rate"]` (`dimensions.py:450??27`). Requiring tests to build reports from those builders rather than hand-written dicts is the right anti-drift check.
- Completeness via `load_done` (`journal.py:75??03`) is the correct predicate: that function skips every unparseable line, not only a trailing truncation, and resume already uses it (`run.py:183`).
- The first paid recipe (`--no-resume --limit 2`) plus the identity assertion before any provider call closes the D-45 append-to-evidence hazard that a post-hoc `git diff` cannot undo.
- `docs/` does not exist yet; this plan correctly does not create it. Store baseline is `graph_disposition: populated` (`06.3.3-STORE-BASELINE.md`), so the yield-floor suspension branch is specified as a real path rather than assumed away.

### Concerns

- **HIGH ??Cap stop-rule is specified against a sequential loop `drive()` does not have.** `drive()` always builds `future_to_unit` by submitting *every* remaining unit up front (`run.py:223??37`), even with the CLI default `--workers 1`. `measure.py:505??14` only checks spend in the `workers <= 1` for-loop; its own pooled branch (`measure.py:530??53`) also submits all units first and never consults the cap. Checking spend in `as_completed` cannot ?ot dispatch??work already queued. Plan 01 `.planning/phases/06.3.4-corrected-re-drive-calibration-and-root-cause-documentation/06.3.4-01-PLAN.md:214??15` still asks for a check ?n both the sequential branch and the ThreadPoolExecutor branch,??and the acceptance test at `:263` assumes a sequential branch exists. This is the residual of the prior HIGH on `run.py:220??37`: `--stage-cap` was added to the plan, but the dispatch model that made the cap theater was not.
- **HIGH ??Staged pairing-coverage floor will not measure what D-44 locked.** AI-SPEC states `pairing_coverage = n_pairs / n_questions_in_committed_sample` with staged denominator 50 (`06.3.1-AI-SPEC.md:930??33`). Landed scoring uses `coverage_denom = join_res.total_distinct_questions` (`score.py:793??09`) and then `n_pairs = len(diffs)` after dropping unscorable pairs (`pairing.py:194??95`). A cap-stopped prefix of 10 questions can report 0.80 against denom 10 while the intended statistic is 8/50 = 0.16. The gate reads that landed key as-is (`06.3.4-01-PLAN.md:441??44`).
- **MEDIUM ??`--no-resume` retry duplicates work units.** `resume=False` sets `done_keys = set()` (`run.py:183`). Re-running the tracer on the same calendar day appends four more records into a non-empty journal whose header cannot be rewritten. Later verifies that assert unique keys (`06.3.4-03-PLAN.md:163`) then fail on a journal that is already the run of record.
- **LOW ??`NodeTiming` field list in `read_first` is wrong.** `journal.py:20??6` is `node_name` + `duration_ms` only. `started_at_ms` / `completed_at_ms` live on `WorkflowWireMeta` (`journal.py:32??2`). Acceptance criteria do not depend on the misattribution.

### Suggestions

- Change `drive()` to submit incrementally (or cancel pending futures) and check spend *before* `executor.submit`, matching the acceptance phrase ?o further work unit dispatched.??Do not copy `measure.py`? pooled branch. Rewrite the sequential-branch language to match the tree: there is only a pool, and `workers=1` is still eager submit-all.
- Have the gate recompute pairing coverage against the locked staged size 50 (and later 500), or refuse to pass coverage when the journal? distinct-question count is below that size. Do not treat `detail["pairing_coverage"]` as D-44? statistic without stating the denominator mismatch.
- First invocation should use `--no-resume --out <fresh dated path>` *or* `--resume` once that path exists, so a tracer retry cannot duplicate keys.

### Risk Assessment

**HIGH** ??The identity and header-latch fixes are sound and necessary. The phase? paid control surface (`--stage-cap` on a hundred- and thousand-query drive) is specified against the wrong loop, and the staged coverage floor can pass on a truncated journal.

---

## 06.3.4-02

### Summary

This plan lands the two D-48 statistics on the standard library before any human score exists, and it puts the uncalibrated label in the only fields the live schema allows. That placement is empirically right: `_validate_consistency` raises `status 'ok' cannot have a reason` (`dimensions.py:30??4`), judged builders return `status="ok"` whenever verdicts exist (`dimensions.py:190??96, 240??46`), and `report.md.j2:38??9` renders `format_details(d.detail)` rather than `reason` for an ok row. Remaining issues are encoding collisions in the state-float table and ambiguity about whether kappa/Spearman run on 12 groundedness pairs, 12 faithfulness pairs, or 24 pooled ratings.

### Strengths

- Calibration today is only exact-match and MAD (`score.py:448??19`, `dimensions.py:186??89`). Neither is the ??0.70 target in AI-SPEC `:969??71`. Building both statistics before ratings exist is the correct anti-fishing order.
- `RunMetadata.notes` already exists (`report.py:45`) and is already rendered (`report.md.j2:30`). `detail: dict[str, float]` already carries calibration floats. Smallest blast radius, and `extra="forbid"` on both models is respected.
- Degenerate outcomes as `value=None` plus a named `state`, never NaN, matches JSON Schema and `DimensionResult.detail` typing.
- Existing guards at `score.py:332??56` (calibration file without judging; sample narrower than cached verdicts) are left untouched and named as 05? ordering constraint.
- Target and calibration size are read from `gate.py` rather than restated. Exact-match/MAD are kept beside the new stats.

### Concerns

- **MEDIUM ??`calibration_kappa_state` encoding copies Spearman? degenerate case.** The table at `06.3.4-02-PLAN.md:228??32` gives kappa_state `2.0` as ?ndefined because a rank vector had no variance,??which is Spearman? condition. Kappa? only named degenerate is `undefined_expected_agreement`. A shared 0/1/2 encoding across two keys with different meanings will be mis-read by 05? republication asserts.
- **MEDIUM ??D-48 says ??2 paired integers??and also ??4 ratings.??* The worksheet is 12 rows ? groundedness + faithfulness. The plan puts the same `detail` keys on both judged builders without saying whether each dimension gets its own n=12 statistic, both get a pooled n=24 statistic, or both get a copy of one overall figure. That choice changes whether n=12 kappa is even identified.
- **LOW ??`calibration_state` 0/1/2 and `calibration_kappa_state` 0/1/2 are adjacent floats with different legends.** Documented, but a machine consumer that reads the wrong key will treat ?o calibration??as ?omputed.??
### Suggestions

- Give kappa and Spearman independent state enums (or disjoint float codes) and state the pairing population in one sentence: e.g. ?appa and Spearman are computed once per dimension over the 12 human/judge integer pairs for that dimension; they are not pooled across groundedness and faithfulness.??- Pin the published worked examples (Cohen? quadratic-weighted kappa; Spearman-with-ties mid-rank) in the test names as the plan already requires, so the golden values cannot silently become self-generated.

### Risk Assessment

**LOW** ??Schema placement is the hard part and it is correct. The remaining issues are executor-ambiguity, not a blocked path.

---

## 06.3.4-03

### Summary

The staged drive, gate, projection, and `checkpoint:decision` close on a plan boundary are the phase? actual control surface, and the round-1 holes (newest-match resume, missing header assertion, POSIX `ls | tail`) are closed in this revision: directory resolution excludes `2026-09-03-multihop_rag` and requires exactly one remaining candidate (`06.3.4-03-PLAN.md:127??35`), header `partial: true` is a precondition (`:96, :170`), and `--out "$RUN/journal.jsonl"` bypasses `resolve_run_dir` entirely. Residual risk is inherited: the cap this stage passes to `drive()` will not stop eager-queued work, and the coverage number the gate reads is not the locked 50-denominator statistic.

### Strengths

- `--limit 50` is a prefix of `load_sample_questions` file order (`run.py:173??75`; `corpus.py:168??87` preserves JSONL order). The sample file? first ids (`mhr-0073ab564e55`, `mhr-0085f76defbe`, `mhr-00fc91a80765`) are already in `question_id` order; Task 3? ledger check against the file is the right place to pin that.
- Preflight-before-drive plus live `index_generation` from `preflight.py:195??37` (not copied from the superseded `metadata.json`) is the D-33 lesson.
- `--resume --out` means the micro-slice? four keys are skipped via `load_done` (`run.py:183??89`) rather than re-paid. `--limit 50` keeps new records `partial=True` for 04? attribution.
- Hold / go / go-with-investigation as `checkpoint:decision gate="blocking-human"` (`06.3.4-03-PLAN.md:256`) is the correct type under `human_verify_mode = end-of-phase`.
- Cap-stopped shortfall is at least *recorded* (`:154??57, :172`). Store suspension is read from the landed `populated` verdict rather than re-inspected.
- Projection from staged per-query cost, with an explicit ban on `$0.0199`, matches why the superseded run was cheap.

### Concerns

- **HIGH ??This stage? `--stage-cap 2.00` is only as real as 01? dispatch rewrite.** Default `--workers 1` still submits all remaining units (up to 96 new + any undriven) before spend is observed (`run.py:223??37`). A $2.00 cap cannot interrupt an already-queued hundred-query pool. Plan 03 `:148??50` treats 01? stop rule as the control; if 01 copies `measure`? sequential snippet into a pool that has already submitted, 03 overshoots while ?nforcing??the cap.
- **HIGH ??Gate coverage on a shortened or journal-relative denominator is not D-44.** Plan 03 `:156??57` evaluates the gate on ?hatever was actually driven.??Combined with `score.py:793` (`total_distinct_questions` as denom) and `pairing.py:194` (scored-pair numerator), a truncated prefix can clear 0.80 for a reason that has nothing to do with pairing integrity on the committed 50.
- **MEDIUM ??`--sample`-style prefix composition is not a random 50.** Already admitted; 01? first-fifty null count (AI-SPEC: 5 null ??max 0.90) must be in the ledger before a coverage miss is treated as an environment failure rather than the locked ceiling.

### Suggestions

- Make a cap-stopped staged drive a *hold* on the coverage comparison, or recompute coverage as `n_pairs / 50` and fail-closed if distinct questions < 50. Do not pass a truncated journal as ?he staged gate.??- Assert `--workers 1` *and* incremental dispatch in the recorded invocation, or pin `workers=1` plus a test that a cap of `$0.00` after the micro-slice? four units dispatches zero further units.

### Risk Assessment

**HIGH** ??Identity, header, and decision-boundary work is now solid. The go/no-go still consumes a coverage statistic that is not the locked one, and the $2.00 cap still sits on eager submit-all.

---

## 06.3.4-04

### Summary

The full drive is correctly authorized only by 03? dated entry, correctly omits `--limit` so full-stage records stay `partial=False` (`run.py:173, 139`), and correctly treats incomplete journals as ?tay staged, do not force the header.??Publication with `--no-judge` keeps judged spend in 05. `score` writes `report.json` only (`score.py:1065??069`); `report` writes `report.md` and `metadata.json` (`cli.py:423??31`) ??the plan now names both commands. This is an `autonomous: true` thousand-work-unit drive whose only in-process brake is the same underspecified `drive()` cap.

### Strengths

- Authorization is a read of `06.3.4-STAGED-GATE.md`, not ?he gate passed.??A hold stops here (`06.3.4-04-PLAN.md:118??19`).
- Mixed-generation abort is real (`score.py:173??78`). Comparing this preflight? generation to 03? before driving is the right stop.
- Exclude-the-superseded-run recipe plus `--out "$RUN/journal.jsonl"` cannot silently extend `2026-09-03-multihop_rag`. Decorated directory names are correctly called out as a silent fork (`:137??38`).
- Index-generation audit is unified on `RunRecord.index_generation` (`journal.py:62`) with `snapshot_only` as corroboration, closing the prior 03-vs-04 field split. Empty generation on the `drive_one` exception path (`run.py:144??52`) is counted, not asserted away.
- Completeness ??reconcile ??`score --no-judge` ??`report` is the only order that produces all three publish artifacts on a journal that began partial.
- Cap-stop requires a fresh recorded decision rather than a silently raised figure (`:161??62`).

### Concerns

- **HIGH ??Autonomous 1000-unit drive with a cap that cannot cancel in-flight work.** Plan 04 `:155??57` repeats ?hecked before each dispatched work unit in both the sequential and the pooled branch.??There is no sequential branch. Graph-on p95 of 30.4 s (`06.3.3-BUDGETS.md`) means a queued pool runs for hours after the cap is notionally hit. This is the same residual HIGH as 01, now on the run of record.
- **MEDIUM ??Verify line 171 contains a literal `&lt;=` in the plan file.** If the executor XML-unescapes, it becomes `<=` and runs. If a human copy-pastes the fenced command, it is a Python syntax error on the journal that 04 just paid for. Same class as `&amp;&amp;` in the reconcile verify at `:232`.
- **LOW ??`score --no-judge` is already the CLI default** (`cli.py:313??19`). Harmless redundancy; 05 relies on this exact argv shape remaining valid without `--stage-cap`.

### Suggestions

- Do not start this plan until 01? cap test proves zero further `executor.submit` after the cap, including under `ThreadPoolExecutor`. That test is the confirming gate for 04? autonomy, not an implementation detail of 01.
- Unescape the verify Python to `<=` in the plan source so the recorded command is runnable without an XML processor.

### Risk Assessment

**HIGH** ??Authorization, publication split, and D-45 isolation are right. The irreversible spend sits behind a cap whose specified mechanism cannot stop the live dispatcher.

---

## 06.3.4-05

### Summary

Judged-slice derivation before seeing `J`, worksheet size as a parameter, `checkpoint:decision` for human scoring, and conditional `--stage-cap` on `--judge` only are the right shape. The hardcoded `== 20` break (`score.py:567??68`) and empty-citation skip (`score.py:399??01`) are real and correctly targeted. Two gaps remain that will shrink or mis-measure the first real judged population: `--sample N` does not sample from the judgeable set `J` is defined on, and ?bserved judged spend??has no token source because `judge_once` discards the provider response after parsing content (`judge.py:312??31`).

### Strengths

- `N = min(J, N_cap)` committed in the plan file before the drive exists is the anti-fishing rule D-47 needs. Empty-citation condition on `J` matches the loop that actually requests verdicts (`score.py:399??01`). `N >= V0` matches the narrower-sample guard (`score.py:347??56`).
- Conditional cap (`float | None = None`, raise in the command body when judging is on) is the only Typer-compatible way to keep `score --run <dir> --no-judge` working for 04 Task 3 and 05 Task 4. That regression test is necessary, not decorative.
- `calibration_size_committed` vs 02? `calibration_completed_n` vs `sample_size_judged` (`score.py:1051`) are three different populations; forbidding rename-into-each-other is correct under `RunMetadata` `extra="forbid"`.
- Halt type is `checkpoint:decision`, not `human-verify`. No agent back-fill; superseded sixteen scores are not reused. Feed-back at the same `--sample` and seed, with cache verdict count asserted unchanged, respects `score.py:332??46`.
- Worksheet default remains 20 so `test_score_judged.py` stays green; explicit size is opt-in. Correcting the ?epresentative items across query types??comment at `score.py:545` without adding stratification mid-family is the right call.
- No `judgeable` dimension exists in `dimensions.py`? registry; preferring the report then falling back to a journal predicate is honest.

### Concerns

- **HIGH ??`--sample N` is not a sample of `J`.** `J` is primary-arm records with gold and non-empty `structured_citations`. `--sample` draws from every primary-arm question that has *any* record (`score.py:377??88`), then skips empty citations inside the loop. Requesting `N = min(J, N_cap)` therefore yields fewer than `N` verdicts whenever the seeded sample includes non-judgeable questions. The superseded run? failure mode ??slice requested, evidence skip silently shrinks the judged population ??is partially reintroduced.
- **HIGH ???ccumulated judged spend??has no observed quantity to accumulate.** `judge_once` returns `(JudgeVerdict | None, str | None)` and never reads `resp_json["usage"]` (`judge.py:261??31`). `compute_spend` (`measure.py:85??13`) sums `workflow_meta.prompt_tokens` / `completion_tokens` on *drive* `RunRecord`s plus a per-query embedding estimate. Applying that to the judge loop would count already-spent generation tokens from the 1000-unit drive ??likely already above the $5 judging cap ??and halt before any judge call. The plan says ?ollowing `measure.py:500??20`? shape??(`06.3.4-05-PLAN.md:232??33`) without naming a judge-token source.
- **MEDIUM ??`p` uses `DEFAULT_MAX_TOKENS = 400` and the evidence char budget, but the loop passes `config.judge_max_tokens` (`score.py:429`).** If corpus config disagrees with 400, `N_cap` and the mechanical cap are derived from different budgets.
- **LOW ??`judged_sample_count` increments before the citation skip** (`score.py:397??01`), so `sample_size_judged` includes `skipped_no_evidence`. The three metadata labels 05 adds will sit next to a fourth count that does not mean ?erdicts obtained.??
### Suggestions

- Select `--sample` from the judgeable question-id set (same predicate as `J`), or inflate the requested sample so the expected judgeable count equals `N`, and record which.
- Extend `judge_once` to return usage tokens (or accumulate `p` per dispatched call as an explicit proxy) and unit-test that `compute_spend` on journal `RunRecord`s is *not* the judged-spend meter.
- Derive `p` from `config.judge_max_tokens` and the same `truncate_evidence` budget the loop uses.

### Risk Assessment

**HIGH** ??Ordering, halt type, and schema discipline are strong. The judged stage can still request the wrong population and enforce the cap against the wrong spend.

---

## 06.3.4-06

### Summary

Root-cause in the 06.3.1 directory, a distilled `docs/` note that is not one of 6.4? three owned pages, an additive `SUPERSEDED.md`, and two scoped ROADMAP edits match SC-6/SC-7 and D-53/D-54. Notice-code spelling via `strings.TrimPrefix(..., "NOTICE_CODE_")` (`gateway/main.go:554`) against `proto/lancet/v1/lancet.proto` is the right read. `docs/` is confirmed absent. Residual risk is editorial (quoting FINDINGS.md, not rewriting numbers) rather than mechanical.

### Strengths

- Placement of `06.3.1-ROOT-CAUSE.md` in 06.3.1? directory is mandated by this phase? own success criterion and is correctly distinguished from a D-46 back-edge (no 06.3.1 plan or code is modified).
- Recompute-from-journal, never from the superseded `report.md`, is the lesson of the false-green report. Quoting `06.3.3-MEASUREMENT.md` (`decay_present: False`) and `06.3.3-STORE-BASELINE.md` (`populated`) by path prevents re-deriving sibling verdicts.
- `NOTICE_CODE_RETRIEVAL_FAILED = 19` is already in `lancet.proto:96`. Halt-if-absent will not fire; the plan still refuses to hard-code an illustrative name. Gateway trim is pinned by `TestRetrievalFailedNoticeRendersAsString` (`gateway/main_test.go:5504??509`).
- SC-5 today lists `RETRIEVAL_DEGRADED` as a single token (`ROADMAP.md:896`) while the wire has `RETRIEVAL_DEGRADED_DENSE` / `_BM25`, plus `GRAPH_ABLATION`, `MODEL_NOTICE`, `BASIS_RECONCILED`. Enumerating the remaining shortfall after one authorized addition is the right D-53 leftover.
- Marker is a new file; verify allows `SUPERSEDED` in `git status --porcelain` and forbids other diffs under that directory. `docs/` creation does not claim the design-narrative / observability / eval-methodology pages.

### Concerns

- **LOW ??ROADMAP ?xactly two lines??is brittle.** SC-5 is one long parenthetical (`ROADMAP.md:896`). A scoped replace that misses `GRAPH_ABLATION` or the DENSE/BM25 split is still a successful `grep` if `RETRIEVAL_FAILED` is inserted. The plan? ?numerate remaining shortfall in the summary??is the real check; the ROADMAP edit itself cannot carry it.
- **LOW ??Verify recipes are POSIX `test`/`grep`.** Fine if GSD runs bash; native PowerShell will not.

### Suggestions

- In the ROADMAP SC-5 edit, add `RETRIEVAL_FAILED` *and* leave the summary table of still-undocumented wire codes as an acceptance criterion, not only a summary note.
- Quote 07? dispositions by section heading so 06 cannot ?ummarize??a negative delta into a softer sentence.

### Risk Assessment

**LOW** ??Scope, placement, and notice-code provenance are correct. Failure modes are wording drift, not spend or data loss.

---

## 06.3.4-07

### Summary

Splitting the two headline dispositions onto a fresh plan after the paid-judged / human-halt / feed-back unit is the right seam. Floors, complement trigger, and ?egative delta is publishable??match D-32/D-49. The plan is almost entirely documentary; its only mechanical dependencies are that 05 created `06.3.4-FINDINGS.md` with a calibration section and that 04/05 left a readable `report.json` in the single corrected run directory.

### Strengths

- Boundary semantics restated as operators (yield at-or-above 0.20, complement strictly above 0.80) and read from `gate.py`, not restated as new numbers.
- Suspension check is required even though 06.3.3 already recorded `populated` ???ecord that it did not fire??prevents a silent skip.
- Influence rate recorded with ?o floor??matches AI-SPEC. Absent keys halt rather than become zeros ??the family? original confusion.
- Append-only on FINDINGS.md, byte-for-byte calibration section, and exclude-superseded run resolution match 03/04/05.
- Empty join and delta of exactly zero are defined outcomes, not re-drive triggers.

### Concerns

- **MEDIUM ??Task 1 verify greps FINDINGS.md for `calibration` and yield keys, then Task 2 greps the same file again including `graph_ablation_delta`.** That cannot detect a rewrite of the calibration section that still contains the word ?alibration.??The acceptance criterion ?yte-for-byte unchanged??needs a hash or a captured prefix, not `grep -qi calibration`.
- **LOW ??Bounded investigation is specified as prose (?hat will be examined, in what order?? with no time box or artifact path.** D-32 says owed before 6.4 publishes; 06 will quote whatever 07 leaves. If 07 leaves ?nvestigation owed??without an owner, 6.4 inherits an open loop.

### Suggestions

- Snapshot the calibration section (hash or line range) before appending, and assert it in Task 1 and Task 2 verifies.
- If a floor miss or negative delta fires, name the investigation? output path (even if ?ecorded as open in FINDINGS.md, closed in 6.4?? so 06 cannot treat silence as closure.

### Risk Assessment

**LOW** ??Disposition rules are correct. The risk is documentary overwrite and an unbounded ?wed??investigation, not a wrong threshold.

---

## Cross-plan comparison

Wave order matches the ROADMAP: tracer+reconcile (01) ??agreement (02) ??staged drive (03) ??full drive (04) ??judged+halt (05) ??dispositions (07) ??root-cause/docs (06). 04 does not depend on 02; 05 depends on both. That is correct: agreement code must exist before scores exist, but the full drive must not wait on unused statistics.

Three shared mechanisms are now consistent across 03??7: exclude-superseded directory resolution, no newest-match, D-45 non-touch of `2026-09-03`. Those round-1 HIGHs look closed.

Two shared mechanisms are **not** closed and leak across the paid plans:

1. **`drive()` eager `ThreadPoolExecutor` submit-all** (`run.py:223??37`). 01 specifies the cap, 03 and 04 invoke it, 04 is autonomous at 1000 units. Prior review already named `run.py:220??37`; this revision added `--stage-cap` without changing dispatch.
2. **Pairing-coverage definition.** 01? gate, 03? go/no-go, and 07? dispositions all read `graph_ablation_delta.detail["pairing_coverage"]`. Landed code (`score.py:793`, `pairing.py:194`) is not AI-SPEC? `n_pairs / 50|500`.

05 is isolated from (1) but has its own analog: judged spend has no token channel, and `--sample` is not filtered to `J`.

06/07 are appropriately thin once 05 has written FINDINGS.md.

## Overall risk assessment

**HIGH**

The phase goal ??a trustworthy staged-then-full re-drive, fresh human calibration, and an honest root-cause record ??is planned, and the D-45 / header-latch / decision-boundary work is now specific enough to execute. The two numbers this family exists to publish (staged go/no-go, and the run of record under a human cap) still rest on a spend brake that cannot cancel queued work and a coverage statistic that does not use the locked denominator. 05 can additionally judge the wrong slice and meter the wrong spend. 02, 06, and 07 are in good shape and should not be blocked for those reasons; 01? dispatch rewrite and gate denominator are blocking for 03 and 04.
