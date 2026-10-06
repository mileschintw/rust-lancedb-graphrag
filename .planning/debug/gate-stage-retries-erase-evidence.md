---
status: diagnosed
trigger: "G-06.3.4.1-2: A gate-stage drive cannot pass SC-2 by retrying timeouts away: retries > 0 is refused on gate-stage drives, or every retried attempt is recorded in the journal (folds in CR-03). User: fix it: refuse retries > 0 on gate-stage drives or at least record accordingly"
created: 2026-10-06T19:00:00Z
updated: 2026-10-06T19:28:00Z
goal: find_root_cause_only
---

## Current Focus

bug_class: Bohrbug (deterministic; reproduced 3/3 configurations)
hypothesis: CONFIRMED - drive_one's retry loop (run.py:87-225) rebinds last_record per attempt and returns only the final one; RunRecord/header persist no attempt or retry provenance; CLI defaults --retries 2 with no stage/gate notion on the drive side, so a retried-away timeout/D-69 rejection vanishes from SC-2, D-69 and compute_spend inputs and nothing downstream can detect it.
test: done (repro + code read)
expecting: n/a
next_action: return ROOT CAUSE FOUND (goal find_root_cause_only)

reasoning_checkpoint:
  hypothesis: "Gate readings can pass after a retried-away failure because drive_one (run.py:87-225) overwrites last_record on every attempt and journals only the final RunRecord, RunRecord/header have no field recording attempts or max_retries (journal.py:52-80, :256-267), and `lancet-eval run` defaults --retries 2 (cli.py:433-440) with no stage/gate parameter that could refuse it. classify_record ignores outcome!=error (diagnostic.py:47-48), so SC-2 (unpark_gates.py:209-231) and D-69 (:293-311) never see the discarded failures, and compute_spend (measure.py:183-221) never charges them."
  confirming_evidence:
    - "Repro: identical timeout-then-success gateway; retries=0 -> SC-2 class_counts {timeout:1}, timeout_dominant True; retries=1 -> class_counts {}, timeout_dominant False, 2 gateway calls, 1 journal record, identical spend"
    - "grep: no test passes max_retries/--retries; header/RunRecord carry no attempt field; only stage notion is unpark_gates --stage (post hoc)"
    - "DRIVE1.md:76 discloses the 06.3.4 D-69 baseline was recorded under --retries 2 and is a lower bound"
  falsification_test: "A record with outcome=success after a failed attempt carrying any field that classify_record/SC-2/D-69/compute_spend read, or a header field recording max_retries, or a test asserting retry behaviour. None found."
  fix_rationale: "Diagnosis only. The cause is the absence of attempt persistence plus the absence of a drive-side gate-stage refusal; either (or both) closes it. Refusal alone needs a new drive-side key; recording alone needs a schema change plus gate/spend consumers reading attempts."
  blind_spots: "D-69 retry-erasure established from code (client.py:334-336 -> run.py:99/186-200), not separately reproduced with a node_failed SSE frame. Repro's ReadTimeout is transport-level, so it shows the record-count shortfall in compute_spend, not a billed provider call. Engine-level GenerateAnswer retry (generate.rs:198-242) is a separate, also-invisible layer, out of scope. Interaction with --resume (header write is a no-op on a non-empty file, so a header-only retry field would describe only the first invocation)."
  candidate_causes:
    - "code: drive_one retry loop discards non-final attempts (run.py:87-225)"
    - "code/data: journal schema has no attempts/retry provenance (journal.py:52-80, :256-267)"
    - "config: CLI default --retries 2 with no gate-stage key or validation (cli.py:433-440)"
    - "process: gate-stage drives distinguished only by operator-typed flags and a post-hoc unpark_gates --stage label"
  and_gate: "yes - the failure requires (1) retries>0 reaching drive_one AND (2) the discarded attempt leaving no persisted trace. Closing either branch closes the gap: refusing retries>0 on gate drives removes (1); persisting every attempt and having SC-2/D-69/compute_spend read them removes (2)."

## Symptoms

expected: The relabel half is enforced by wired tests. The retry-away half has no code enforcement (CLI default --retries 2; CR-03 shows retried failures vanish from the journal). Run of record was clean only because --retries 0 was passed.
actual: User reported: "fix it: refuse retries > 0 on gate-stage drives or at least record accordingly"
errors: None reported
reproduction: UAT test 2 (06.3.4.1-UAT.md)
started: Discovered during UAT 2026-10-06
prior_evidence: 06.3.4.1-REVIEW.md CR-03 (run.py:87-225, cli.py:433-440), WR-01; VERIFICATION.md coincidental_reliance_items

## Eliminated

## Evidence

- timestamp: 2026-10-06T19:05:00Z
  checked: eval/src/lancet_eval/run.py:62-233 (drive_one) and :236-390 (drive)
  found: drive_one loops `for attempt in range(max_retries + 1)` (L88); each attempt rebinds `last_record` (L166 success path, L205 exception path); success+non-empty answer returns immediately (L186-187); otherwise sleeps and `continue`s (L189-200, L214-224). Only the returned RunRecord reaches drive(), which does `journal.append(record); records.append(record)` (L354-356). Earlier attempts are discarded in memory; nothing is logged to the journal except a logger.warning (L190-198, L215-222).
  implication: CR-03 line numbers still accurate. A unit that times out / D-69-rejects on attempt 1 and succeeds on attempt 2 is journaled as a single outcome="success" record.

- timestamp: 2026-10-06T19:06:00Z
  checked: eval/src/lancet_eval/cli.py:392-488 (`run` command)
  found: `--retries/-r` default 2 (L433-440), passed straight to drive(max_retries=retries) (L472). No validation, no `--stage`/gate option, no refusal. Only surfaced in the console banner (L460). drive() itself defaults max_retries=0 (run.py:246) - the dangerous default lives only in the CLI.
  implication: default CLI invocation retries twice per unit; the run of record was clean only because operator passed --retries 0.

- timestamp: 2026-10-06T19:07:00Z
  checked: eval/src/lancet_eval/journal.py:52-80 (RunRecord), :256-267 (write_header), :175-246 (reconcile_header)
  found: RunRecord is `extra="forbid"` with no attempts/attempt_count/retry field. Header written once with only {type, corpus, partial, created_at}; reconcile_header only rewrites `partial`. max_retries is persisted nowhere.
  implication: a journal produced with retries>0 is byte-indistinguishable from one produced with retries=0; no downstream reader (score, unpark_gates) can detect or refuse it post hoc. Adding an `attempts` field needs a RunRecord schema change (extra=forbid) and any MeasurementRecord subclass inherits it.

- timestamp: 2026-10-06T19:08:00Z
  checked: eval/src/lancet_eval/measure.py:155-221 (compute_spend, _failed_generation_attempts)
  found: compute_spend sums wire tokens over `records`, charges count_failed_generation_attempts(records) x ceiling, and embeddings as len(records) x 120 tokens. It is per-record; the "2 attempts" charge at L169 is for the ENGINE GenerateAnswer node retry (generate.rs is_retryable) read from node_failures, a different layer from the harness retry.
  implication: tokens/failed-generation charges from discarded harness attempts never reach compute_spend; drive()'s in-process cap check (run.py:361-364) and final observed_spend (L387) both undercount by up to max_retries provider calls per unit.

- timestamp: 2026-10-06T19:09:00Z
  checked: eval/src/lancet_eval/diagnostic.py:38-70 (classify_record); unpark_gates.py:163-268 (evaluate_sc2), :271-380 (citation_rejection_rate), :1274-1401 (main)
  found: classify_record returns None when record.outcome != "error" (L47-48). evaluate_sc2 tallies class_counts only over classify_record != None (L209-214); timeout_dominant computed from that tally (L222-231). citation_rejection_rate numerator = classify_record in D-69 classes, denominator = records reaching GenerateAnswer (L293-311). Both read load_records(journal) only.
  implication: a retried-away timeout or D-69 rejection is absent from the error tally AND converted into a success in the D-69 denominator -> SC-2 error-mode and D-69 tripwire can PASS on a run that experienced real timeouts/rejections. This is the "retry it away" path the 01-PLAN prohibition forbids.

- timestamp: 2026-10-06T19:10:00Z
  checked: stage/gate identification across run.py, cli.py, unpark_gates.py
  found: The only stage notion is unpark_gates.main `--stage` (free-form, required, L1288) with DRIVE2_STAGE="drive2" (L51) switching on SC-4/SC-5; drive1/drive1b/any other label = SC-1/SC-2/D-69/SC-3. It is applied post hoc by the gate reader, after the journal exists. The drive side (`lancet-eval run`, drive(), drive_one) has no stage/gate parameter at all.
  implication: "refuse retries>0 on gate-stage drives" has nothing to key on at drive time today. Either (a) a drive-side stage/gate flag must be added and persisted in the header, or (b) attempt counts must be persisted so the gate reader (which DOES know it is a gate stage) can refuse/MISS. Without persistence, unpark_gates cannot enforce anything.

- timestamp: 2026-10-06T19:14:00Z
  checked: Minimal repro (scratchpad/repro_retry_erasure.py) - httpx.MockTransport gateway that raises ReadTimeout on call 1, returns a valid SSE answer on call 2; drive_one -> Journal -> load_records -> classify_record / compute_spend / evaluate_sc2(pid 1,1) / citation_rejection_rate
  found: |
    retries=0: gateway_calls=1 records=1 outcome=error error_type=ReadTimeout classify=timeout SC2.class_counts={timeout:1} timeout_dominant=True spend=0.00001440
    retries=1: gateway_calls=2 records=1 outcome=success error_type=None classify=None SC2.class_counts={} timeout_dominant=False spend=0.00001440
    retries=2: gateway_calls=2 records=1 outcome=success classify=None SC2.class_counts={} timeout_dominant=False spend=0.00001440
    No attempt/retry field on the record in any case.
  implication: CONFIRMED (Bohrbug, deterministic). The same timeout flips SC-2's error-mode clause from MISS to PASS purely by passing --retries>=1, and the extra billed gateway call is not charged (spend identical with 2 calls vs 1). Same mechanism applies to D-69 rejections: drive_one retries any outcome_literal=="error" (run.py:186-200), so a D-69 node failure that succeeds on retry is removed from citation_rejection_rate's numerator and counted as a non-rejection in its denominator.

- timestamp: 2026-10-06T19:16:00Z
  checked: 06.3.4.1-RUN-OF-RECORD.md:27, DRIVE1.md:20/:76, DRIVE1B.md:20/:76, eval/runs/ dir names
  found: All three gate-stage drives were `lancet-eval run --corpus multihop_rag_diag --out eval/runs/<date>-drive{1,1b,2}-multihop_rag_diag/journal.jsonl --workers 1 --retries 0 --no-resume --stage-cap ...`; the gate stage label (drive1/drive1b/drive2) is only supplied later to `unpark_gates --stage`. DRIVE1.md:76 / DRIVE1B.md:76 already disclose that the 06.3.4 D-69 baseline (43/355) "was recorded under --retries 2 and is a lower bound on the single-attempt rate".
  implication: The control today is purely procedural (operator typed --retries 0). The retry-erasure has already distorted one recorded figure (the 06.3.4 D-69 baseline), so the defect is not purely theoretical. Corpus config (eval/corpora/multihop_rag_diag.toml, corpus.CorpusConfig) carries no gate/stage field either.

- timestamp: 2026-10-06T19:18:00Z
  checked: eval/tests/ for retry coverage; CliRunner usage
  found: No test anywhere passes max_retries or --retries (grep empty). test_run_arms.py:77-92 only covers the default max_retries=0 exception path; test_stage_cap.py monkeypatches drive_one wholesale (L39-48, :85-94, :131-141, :222-242) so the retry loop is never exercised under the cap; test_stage_cap.py:195 is the only CliRunner `run` invocation. Relabel half covered by test_classify_record_*timeout* (VERIFICATION.md:166).
  implication: Zero regression coverage for the retry-away half; any fix needs new tests in test_run_arms.py (drive_one/drive with retries>0), test_stage_cap.py (cap charges every attempt / CLI refusal), test_spend_accounting.py (per-attempt charge), test_unpark_gates.py (SC-2/D-69 see retried failures or MISS on retry provenance), test_diagnostic.py (classify over attempts), test_journal*.py (schema/header round-trip).

- timestamp: 2026-10-06T19:19:00Z
  checked: engine/src/workflow/nodes/generate.rs:156-242, engine/src/workflow/mod.rs:129, runner.rs:434; journal.WorkflowWireMeta
  found: Engine GenerateAnswer node has its own one-shot retry on Timeout/ProviderError; ctx.generation_attempts is recorded only on a tracing span (runner.rs:434), not on the wire; WorkflowWireMeta has no attempts field.
  implication: Separate layer (system under test, not harness). A node-level timeout recovered by the engine's own retry is also invisible in the journal. Out of scope for G-2 (which is harness --retries / CR-03) but noted as a blind spot.

- timestamp: 2026-10-06T19:24:00Z
  checked: CORRECTION to the 19:10 entry ("only stage notion is unpark_gates --stage"). Second gate reader: cli.py:491-537 `lancet-eval staged-gate` -> score_run(no_judge) -> gate.evaluate_staged_gate (gate.py:189+), which reads report.json's graph_ablation_delta.detail["pairing_coverage"] for the D-44 coverage floor. Also journal.reconcile_header (journal.py:175-246) uses "staged/publishable" to mean the completeness `partial` flag, NOT a gate stage.
  found: Two post-hoc gate readers exist (unpark_gates --stage, staged-gate), neither on the drive side; neither can see retries. The "staged" vocabulary in reconcile_header/write_header is completeness, so a refusal cannot key on it.
  implication: Files Involved must include gate.py/staged-gate path; plan-phase must not treat `partial`/"staged" as a gate-stage marker.

- timestamp: 2026-10-06T19:25:00Z
  checked: Full consumer inventory - grep classify_record(/load_records(/records_from_run_journal(/outcome== across eval/src/lancet_eval/*.py
  found: |
    Every gate input is outcome-sensitive and reads only the final journaled record:
    - SC-2 error-mode: unpark_gates.py:209-231 via classify_record (diagnostic.py:47-48 returns None on success)
    - SC-2 flatness: flatness.records_from_run_journal (flatness.py:250-300) synthesizes a censored RetrieveHybrid observation for a harness ReadTimeout/StreamDeadlineExceeded; a retry replaces the censored observation with an uncensored one
    - D-69 companion: unpark_gates.py:293-311 (numerator classify_record in D-69 classes; denominator records reaching GenerateAnswer)
    - SC-3: diagnostic.build_rows (diagnostic.py:392, :454-470) -> ArmResult.outcome/error_class; unpark_gates.py:457 (graph_off.outcome=="error" and D-69)
    - SC-4/SC-5: unpark_gates.py:694 deduplicate_by_arm(load_records) -> pairing.form_pairs requires is_usable on both arms (pairing.py:108-109); usability.is_usable returns False on outcome=="error" (usability.py:34)
    - graph-off invariance: unpark_gates.py:1161-1170 (outcome=="success" filter)
    - staged-gate D-44 coverage: score.py:297-298 is_usable split -> graph_ablation_delta pairing_coverage -> gate.evaluate_staged_gate
    - spend: run.py:289/293/361/387 and measure.compute_spend (per record)
  implication: A retried-away failure does not only clear SC-2's tally; it also converts an unusable/unpaired record into a usable/paired one, inflating SC-4/SC-5 populations, D-44 pairing coverage and D-69's non-rejection denominator. Plan-phase must decide per reader whether it should see first-attempt (failure evidence) or final (quality) outcomes.

- timestamp: 2026-10-06T19:26:00Z
  checked: client.run_query (client.py:298-351)
  found: node_failed frames append to node_failures (L298-299); workflow_completed.success==False returns QueryOutcome(status="failed") (L334-336). drive_one maps status=="failed" to outcome_literal "error" (run.py:99) and retries it (run.py:186-200). DRIVE1.md:76 recorded 4/200 D-69 rejections classified by classify_record, which only classifies outcome=="error" records.
  implication: D-69 erasure under retries>0 is established from code (no longer only inferred): a D-69 GenerateAnswer rejection is an outcome=="error" record and is retried exactly like a timeout.

- timestamp: 2026-10-06T19:27:00Z
  checked: Spend wording from the 19:14 repro
  found: The mock raises ReadTimeout at the transport layer before any engine work, so the repro does not by itself show a billed provider call. What it does show: 2 gateway calls, 1 journal record, compute_spend input of 1 record (identical spend to the 1-call case).
  implication: CR-03's spend half is established from code (compute_spend iterates journal records only; a discarded attempt that reached GenerateAnswer carried wire tokens or a failed-generation charge that is lost), and the repro shows the record-count shortfall. Refusing retries only on gate-stage drives does NOT close the spend half for non-gate drives with retries>0; that needs per-attempt charging or a global default of 0.

## Resolution

root_cause: "AND-gate of two contributing causes: (1) the harness retry loop in drive_one (eval/src/lancet_eval/run.py:87-225) rebinds last_record on every attempt and returns only the final RunRecord, which drive() journals (run.py:354-356); earlier timeouts, D-69 rejections, empty answers and their billed tokens are discarded in memory, and neither RunRecord (journal.py:52-80, extra=forbid) nor the journal header (journal.py:256-267) records attempts or max_retries, so every outcome-sensitive reader - classify_record (diagnostic.py:47-48), SC-2 error-mode (unpark_gates.py:209-231) and flatness censoring (flatness.py:250-300), D-69 (unpark_gates.py:293-311), SC-3 rows (diagnostic.py:454-470), SC-4/SC-5 pairing via is_usable (usability.py:34, pairing.py:108-109), staged-gate D-44 coverage (score.py:297-298 -> gate.evaluate_staged_gate) and compute_spend (measure.py:183-221) - sees only the post-retry outcome; (2) `lancet-eval run` defaults --retries to 2 (cli.py:433-440) and neither the CLI nor drive() has any stage/gate notion that could refuse retries>0 - the stage labels exist only in post-hoc readers (`unpark_gates --stage`, unpark_gates.py:51/:1288; `lancet-eval staged-gate`, cli.py:491-537), which cannot detect retries because nothing persisted them; the 'staged/publishable' wording in reconcile_header is the completeness flag, not a gate stage."
fix: (not applied - goal find_root_cause_only)
verification:
files_changed: []
