---
status: diagnosed
trigger: "CR-02: unpark gates never score a partial or incomplete journal — main computes completeness_comparison once, every gate MISSes on an incomplete journal, and gates enforce n-vs-denominator coverage floors (SC-1 cannot PASS on a partial journal)."
created: 2026-10-06T19:00:00Z
updated: 2026-10-06T19:00:00Z
goal: find_root_cause_only
symptoms_prefilled: true
---

## Current Focus

bug_class: Bohrbug (deterministic: a missing guard; same input -> same wrong PASS every time)
known_pattern_candidate: none (no knowledge-base.md in .planning/debug/; MemPalace not queried)
hypothesis: H1 CONFIRMED - completeness_comparison is consulted ONLY inside evaluate_sc1 and only to check header consistency, so (a) an honestly-labelled partial journal with no report.json reads SC-1 PASS and (b) main() runs SC-2/D-69/SC-3/SC-4/SC-5 over whatever records exist with no completeness gate and no expected-population denominator.
test: done - control byte-identical; p1_halt40 and p2_one_pair read all-PASS on the drive-2 gates
expecting: n/a
next_action: return ROOT CAUSE FOUND (goal find_root_cause_only); no source edits, no commit

reasoning_checkpoint:
  hypothesis: "An incomplete journal yields a PASS gate table because (1) evaluate_sc1 (unpark_gates.py:122-142) treats completeness only as the expected value of the header flag, so honest partial + no report.json = zero reasons = PASS, and (2) main (:1323-1365) computes every other reading independently, never calling completeness_comparison or consulting SC-1, and (3) no evaluator compares its n to an expected-population denominator (none exists in code or thresholds.py)."
  confirming_evidence:
    - "p1_halt40 (40/200 units, header partial:true, no report.json): SC-1..SC-5 all PASS, exit 0"
    - "p2_one_pair (2/200 units): SC-1, SC-3, SC-4, SC-5 PASS at n=1"
    - "control re-run on the real drive-2 dir is byte-identical to the committed gates-drive2.{md,json}, so the reproduction runs the recorded code path"
    - "grep: completeness_comparison has exactly one call site, unpark_gates.py:122"
  falsification_test: "If any reading in the truncated-journal run had come back MISS citing missing units, or if main referenced sc1/completeness anywhere, H1 would be false. Neither happened."
  fix_rationale: "Gating every reading on one completeness computation in main removes the partial-journal PASS path at its single choke point; a committed coverage floor on n / |expected-sample & G| (SC-3, SC-4) and n / |expected-sample & V| (SC-5) closes the complete-but-shrunken-n path (WR-04), which completeness alone cannot (load_done counts error records as done)."
  blind_spots: "Did not exercise a resumed journal with duplicate records (IN-01) under the fix; did not check drive1's SC-3 n=88 shrink cause in detail; did not query MemPalace (no knowledge-base.md exists)."
  candidate_causes:
    - "code: main has no completeness gate and assembles independent readings (unpark_gates.py:1323-1365)"
    - "code/spec: evaluate_sc1 encodes D-87a's metadata-honesty clause only; the 'journal under gate is complete' precondition was presupposed by the spec wording ('the run of record's journal') and never encoded (:122-142)"
    - "data/config: no expected denominator available - diag_selection.json G/V are corpus-wide (398/291), only drawn_question_ids (100) is sample-scoped; thresholds.py has no coverage literal (only gate.py:21 STAGED_PAIRING_COVERAGE_FLOOR for 06.3.4)"
    - "test: every unpark_gates fixture writes partial:true via _write_journal and no test covers honest-partial + no report.json for SC-1, so the PASS path was never observed"
  and_gate: "yes - the all-PASS table on a partial journal needs BOTH the SC-1 predicate gap AND main's missing completeness gate (fixing SC-1 alone would leave SC-3/SC-4/SC-5 PASS rows beside an SC-1 MISS). The coverage-floor gap is a third, independent cause of a second failure mode (complete journal whose G/V records error out), which the completeness gate does not cover."

## Symptoms

expected: (UAT test 3, phase 06.3.4.1) Owner agrees CR-02 is a latent defect and schedules a fix before any further gated drive or Phase 6.4 unpark.
actual: User reported "CR-02 agreed latent, but fix now in gap closure (completeness computed once in main, all gates MISS on incomplete journal, plus n-vs-denominator coverage floors). CR-03 is the same as G-2, fold it in. CR-01 fix it too."
errors: None reported
reproduction: Test 3 in UAT (06.3.4.1-UAT.md); prior evidence 06.3.4.1-REVIEW.md §CR-02, §WR-04
started: Discovered during UAT (code review of phase 06.3.4.1)

## Eliminated

- hypothesis: H0 - CR-02's line references have drifted / the defect was already fixed after the review
  evidence: HEAD 77d1f399; evaluate_sc1 :78-160, main :1274-1401, SC-5 rule_a :1078, SC-3 p>=floor :436 all at the review's cited lines; the reproduction reads all-PASS on partial journals.
  timestamp: 2026-10-06T19:27:00Z

- hypothesis: H2 - the recorded drive-2 (or drive 1/1b) verdict was itself produced from a partial journal, so the defect is active, not latent
  evidence: completeness_comparison True / 0 missing for all three recorded drives; headers partial:false; report.json present; control re-run byte-identical.
  timestamp: 2026-10-06T19:29:00Z

- hypothesis: H3 - SC-4's Wilson lower-bound clause already protects SC-4 against thin partial populations
  evidence: p2_one_pair: 1/1 gives Wilson lower 0.2065 > 0.098, SC-4 PASS at n=1.
  timestamp: 2026-10-06T19:27:00Z

- hypothesis: H4 - SC-5's paired-delta pairing_coverage is a usable coverage denominator
  evidence: coverage_denominator = len(attempted & v_ids) where attempted = IDs present in the journal (:1025, :1040, :1050); it reads 1.0 on any partial journal. Same self-shrinking-denominator defect 06.3.4-STAGED-GATE.md :17 already ruled out for the D-44 floor.
  timestamp: 2026-10-06T19:20:00Z

## Evidence

- timestamp: 2026-10-06T19:05:00Z
  checked: eval/src/lancet_eval/unpark_gates.py (1405 lines, HEAD 77d1f399) - every call site of completeness_comparison
  found: imported at :26, called exactly once at :122 inside evaluate_sc1. evaluate_sc1 builds `reasons` only from (header_partial != expected_partial) :130, (header_partial and report_exists) :135, (not header_partial and not report_exists) :139; status = PASS if not reasons :142. An incomplete journal honestly labelled partial:true with no report.json produces zero reasons -> PASS. is_complete is never surfaced as a field (detail has header_partial/expected_partial/missing_units/report_json_exists, :152-157).
  implication: SC-1 enforces header honesty, not completeness. Line numbers in REVIEW CR-02 have not drifted.

- timestamp: 2026-10-06T19:06:00Z
  checked: unpark_gates.py main() :1274-1401
  found: main calls evaluate_sc1 :1323, evaluate_sc2 :1324, citation_rejection_rate :1339, build_rows + evaluate_sc3 :1341-1345, evaluate_sc4 :1356, evaluate_sc5 :1359, graph_off_invariance :1362 unconditionally. It never calls completeness_comparison, never reads sc1.status or sc1.detail, and has no branch that converts any reading to MISS on an incomplete journal. Always exits 0 :1401.
  implication: the gate table is assembled from independent readings; SC-1's outcome cannot influence SC-2..SC-5.

- timestamp: 2026-10-06T19:07:00Z
  checked: each evaluator for a completeness or expected-denominator check
  found: |
    evaluate_sc2 :163-268 - load_records, n = len(records); only n==0 -> MISS (:190). No completeness, no denominator.
    citation_rejection_rate :271-380 - denominator = records that reached GenerateAnswer; only total==0 -> MISS (:314). No completeness. (IN-01: gold_map empty when corpus missing silently drops the null clause.)
    evaluate_sc3 :383-536 - g_ids = selection g_question_ids :411; n = len(scored_rows) where scored_rows filters e_answer_usable is not None :418; PASS iff p >= floor :436 (point estimate). len(g_ids) read but never compared to n; no completeness. WR-04: non-D-69 graph-off errors drop out of n undisclosed (excluded_generate_answer_failures counts only D-69 classes :456-458).
    evaluate_sc4 :698-800 - n = pairs(G) presence n_eval :765; only n==0 -> MISS :766. g_ids :736 used only as a filter. Wilson lower-bound clause :779 provides some small-n protection but no coverage check.
    evaluate_sc5 :955-1138 - only `not pairs_v` -> MISS :1073; rule_a = composition rate >= floor :1078 with no min n (rule_b requires n_pairs>=2 :1083 but rule_a does not). v_ids :1022 used only as a filter. The paired-delta `pairing_coverage` uses coverage_denominator=len(attempted_ids & v_ids) :1040/1050 where attempted = question IDs present in the journal :1025 - a self-shrinking denominator that reads 1.0 on a partial journal.
    graph_off_invariance :1141 - disclosure only, no threshold.
  implication: no gate has an expected-population denominator; the only denominators that exist (SC-5 pairing_coverage) are journal-relative and cannot detect a partial journal.

- timestamp: 2026-10-06T19:08:00Z
  checked: eval/src/lancet_eval/journal.py:151-172 completeness_comparison
  found: expected = {journal_key(corpus, q.id, arm) for q in load_sample_questions(corpus) for arm in config.arms}; missing = expected - load_done(journal). It is keyed to the journal header's corpus sample, not to the selection file.
  implication: the natural expected denominator for a coverage floor is the same sample set completeness_comparison uses, intersected with G or V.

- timestamp: 2026-10-06T19:09:00Z
  checked: eval/corpora/multihop_rag/diag_selection.json + load_sample_questions("multihop_rag_diag")
  found: g_question_ids = 398, v_question_ids = 291 (corpus-wide populations over multihop_rag), drawn_question_ids = 100. multihop_rag_diag sample (questions.diag.jsonl, sample_size 100) == drawn_question_ids exactly. sample & G = 90, sample & V = 65, V subset of G, 10 nulls (not in G).
  implication: CRITICAL for the fix - REVIEW CR-02's literal wording "report n against len(g_ids) or len(v_ids)" uses the corpus-wide populations. Drive 2's complete run gives 90/398 = 0.226 (SC-3), 89/398 = 0.224 (SC-4), 65/291 = 0.223 (SC-5); any floor above ~0.22 on that denominator would flip the recorded run of record to MISS on all three. The correct denominator is expected-sample & G (= 90) and expected-sample & V (= 65).

- timestamp: 2026-10-06T19:10:00Z
  checked: eval/runs/2026-10-06-drive2-multihop_rag_diag/ (journal.jsonl 201 lines, header partial:false; gates-drive2.json; metadata.json partial false; drive-console retries=0, workers=1)
  found: completeness_comparison(drive2, multihop_rag_diag) -> is_complete True, 0 missing. Recorded readings: SC-1 PASS n=200; SC-2 PASS n=200 (both_arm_error_question_count 1); D-69 PASS n=199; SC-3 PASS n=90 (52/90 = 0.5778, floor 0.512); SC-4 PASS n=89 (59/89, pairs_G n_records 89, missing_meta_n 0); SC-5 PASS n=65 (35/65 composition, pairs_V n_pairs 65, pairing_coverage 1.0). pairs_G pairing_coverage 0.9889 = 89/90.
  implication: under a fix with the correct denominator, drive-2 coverage = SC-3 90/90 = 1.000, SC-4 89/90 = 0.989, SC-5 65/65 = 1.000; the completeness clause is a no-op (complete). A strict 1.0 floor on SC-4's pairs(G)/|sample & G| WOULD flip drive 2's SC-4 to MISS (one G question has no pair: the one both-arm-error question).

- timestamp: 2026-10-06T19:11:00Z
  checked: eval/src/lancet_eval/thresholds.py (218 lines) and eval/src/lancet_eval/gate.py:18-22
  found: thresholds.py has no coverage floor of any kind (literals: GRAPH_YIELD_INVESTIGATION_FLOOR, CITATION_REJECTION_*, SC2_TIMEOUT_DOMINANCE_RULE, FINAL_ANSWER_MISSING_REVIEW_RATE, VECTOR_BASELINE_USABLE_FLOOR, GRAPH_PRESENCE_WILSON_LOWER_FLOOR, GRAPH_COMPOSITION_CHANGE_FLOOR, SC5_VISIBILITY_RULE, decay sets). A committed precedent exists in gate.py:21 STAGED_PAIRING_COVERAGE_FLOOR = 0.80 (06.3.4 D-44), with the recorded design lesson in 06.3.4-STAGED-GATE.md:16-17,45 that the floor applies to n_pairs / locked stage size, never to the harness's journal-relative pairing_coverage "because on a short journal it shrinks its own denominator".
  implication: a coverage floor for unpark gates would be a NEW literal (or a re-use of the 06.3.4 literal). Either way it must be committed before the drive it governs.

- timestamp: 2026-10-06T19:12:00Z
  checked: 06.3.4.1-01-PLAN.md prohibitions :79-99; 06.3.4.1-CONTEXT.md D-73 :198-201; 06.3.4.1-VALIDATION.md :213
  found: test-tier prohibition "MUST NOT publish, label or cite a halted or partial drive ... as a complete scored run" (:86). Judgment-tier "MUST NOT set, move or relax a gate threshold (SC-3 floor, D-69 tripwire, SC-2 reading, SC-4 Wilson clause, composition floor) after the data it tests exists, and MUST NOT suppress, re-run or tune toward a gate miss" (:93). D-73: floor committed in thresholds.py BEFORE the first paid drive. VALIDATION :213 makes it checkable: every thresholds.py commit must precede the first journal record of the drive it governs.
  implication: CR-02 is a breach of the test-tier prohibition in latent form (the gate table can present a partial drive's readings as PASS). A new coverage floor committed now post-dates drive-2's data, so it may only govern future drives; it must not be applied to re-adjudicate drive 2 and its value must not be chosen by looking at drive 2's 90/89/65.

- timestamp: 2026-10-06T19:13:00Z
  checked: eval/tests/test_unpark_gates.py (1772 lines) fixtures
  found: _write_journal :101-108 hard-codes header partial:True and writes a handful of records; it feeds every direct evaluator unit test for D-69 (:114-224), SC-2 (:255-440), SC-4 (:1069-1164), SC-5 (:1229-1409, :1711-1772). _write_sc1_journal :465-488 writes ALL sample units with a chosen header flag; main tests use it with header_partial=True on a complete journal (:919 test_main_writes_markdown..., :1568/:1577 _main_fixture for test_main_for_the_earlier_stages :1620 and test_main_drive2_adds_sc4_sc5 :1643), and those assert the payload key list exactly (:1627 ["SC-1","SC-2","D-69 companion","SC-3"], :1653-1661 seven keys). SC-1 tests :491-563 cover header-false+complete PASS, header-false+omit_last MISS, header-false no report MISS, no journal MISS; there is NO test for header-partial:true + incomplete + no report.json (the CR-02 case that reads PASS). Unit fixtures' selection files carry only g/v lists (no drawn_question_ids) and use corpus "multihop_rag"/"graphrag_bench" with synthetic q000.. IDs.
  implication: a completeness guard placed in main leaves the evaluator unit tests intact; one placed inside each evaluator (or a denominator computed from load_sample_questions(header corpus)) would flip ~40 unit tests. Adding a payload key (e.g. "completeness") breaks the two exact key-list assertions. A new red test is needed for the partial+honest SC-1 case.

- timestamp: 2026-10-06T19:20:00Z
  checked: test-file census (regex over eval/tests/test_unpark_gates.py) + baseline run `uv run --project eval pytest eval/tests/test_unpark_gates.py -q`
  found: 61 passed (60 defs, one parametrized x2). Evaluator-level tests that run on a partial:true header via _write_journal directly or through _presence_journal/_composition_journal/_unpaired_boost_journal: 20 + 5 + 11 + 1 + 1 = 38 (D-69, SC-2, SC-4, SC-5, unpaired-boost, one invariance). main-level tests on _write_sc1_journal(header_partial=True) over a COMPLETE graphrag_bench journal: test_main_writes_markdown_and_json_and_exits_zero :889 (asserts key presence only), test_main_for_the_earlier_stages_writes_exactly_the_four_readings[drive1,drive1b] :1620 (exact key list), test_main_drive2_requires_a_baseline_run :1632, test_main_drive2_adds_sc4_sc5_and_the_invariance_report :1643 (exact key list). SC-3 unit tests (10) pass rows + selection with selection == rows (full coverage) and no corpus. Thin-population test test_sc5_one_pair_with_a_composition_change_passes :1326 uses V = {q000} so its coverage is 1/1: a coverage floor does NOT change it (min-n is a separate question from coverage).
  implication: main-level completeness gating changes no existing assertion except where the payload key list is pinned; the evaluator-level fixtures stay valid only if the coverage denominator is injected by main (expected sample & G/V), not derived inside the evaluator from the journal corpus (synthetic q000.. IDs are not in the multihop_rag sample, so an evaluator-derived denominator would be 0 and flip the 38 fixtures).

- timestamp: 2026-10-06T19:25:00Z
  checked: CONTROL - `python -m lancet_eval.unpark_gates --stage drive2` re-run on the unmodified drive-2 dir (baseline drive1b, populations diag_selection.json, gold-chunks diagnostic/post-reconcile/gold_chunks.jsonl, PIDs 7372/7372), output to the scratchpad
  found: gates md and json byte-identical (CRLF-normalised) to the committed eval/runs/2026-10-06-drive2-multihop_rag_diag/gates-drive2.{md,json}.
  implication: current code reproduces the recorded run-of-record readings; the reproduction below runs the same code path.

- timestamp: 2026-10-06T19:27:00Z
  checked: REPRODUCTION - two truncated copies of the drive-2 journal in the scratchpad, header partial:true (honest), no report.json, same CLI and inputs
  found: |
    p1_halt40 (first 40 of 200 records = a drive halted at 20%; missing_units 160):
      SC-1 PASS n=40 (header_partial True == expected_partial True, report_json_exists False)
      SC-2 PASS n=40; D-69 PASS n=40; SC-3 PASS n=17 (0.7059); SC-4 PASS n=17 (0.6471, Wilson lo 0.4130); SC-5 PASS n=10 (5/10)
      -> an all-PASS table identical in shape to the run of record, exit 0.
    p2_one_pair (2 records, 1 V question with a boosted chunk; missing_units 198):
      SC-1 PASS; SC-3 PASS n=1 (1.0000); SC-4 PASS n=1 (1.0000, Wilson lower bound of 1/1 = 0.2065 > 0.098); SC-5 PASS n=1 (1/1); D-69 PASS; SC-2 MISS only because flatness is unavailable (SC-2 is a disclosure on drive 2).
      -> all three drive-2 GATES (SC-1, SC-4, SC-5) read PASS on 1% of the drive.
  implication: H1 CONFIRMED by direct observation on real run data. Also shows SC-4's Wilson clause is not a small-n guard (1/1 clears it), and SC-5 rule (a) has no min n.

- timestamp: 2026-10-06T19:29:00Z
  checked: recorded drives 1 and 1b (eval/runs/2026-09-30-drive1-..., 2026-10-01-drive1b-...) - completeness and gates-*.json
  found: both complete (0 missing), header partial:false. drive1 SC-3 MISS n=88 (88/90 = 0.978 coverage, 2 G rows dropped from scored_rows - the WR-04 shrink, already a MISS on the floor); drive1b SC-3 PASS n=90 (1.000).
  implication: completeness gating changes no recorded verdict on any of the three drives. A coverage floor <= 89/90 = 0.989 changes no recorded verdict; a strict 1.0 floor would flip only drive-2 SC-4 (89/90) - that value must neither be picked to keep drive 2 passing nor applied retroactively to it.

- timestamp: 2026-10-06T19:30:00Z
  checked: `git log -- eval/src/lancet_eval/thresholds.py` vs drive-2 journal header created_at
  found: last thresholds commit 786e3d3e at 2026-10-06T06:45:44Z (drive-2 literals); drive-2 first record/header created_at 1791278008.61 = 2026-10-06T09:13:28Z. Any new floor committed in this gap closure post-dates all three drives' data.
  implication: under the plan-01 judgment prohibition and VALIDATION :213 (thresholds commit must precede the first record of the drive it governs) the new floor may govern only the NEXT gated drive. Re-running unpark_gates on drive 2 under new code would be a post-hoc reading and must be labelled a disclosure, not a gate verdict; gates-drive2.{md,json} must not be rewritten.

- timestamp: 2026-10-06T19:31:00Z
  checked: journal.py:88-116 load_done
  found: any parseable RunRecord counts as done, including outcome == "error".
  implication: completeness_comparison True does not mean scorable. A complete journal whose G/V records error out still shrinks n in SC-3/SC-4/SC-5 (WR-04). The completeness gate and the coverage floor are two independent guards for two distinct failure modes; neither subsumes the other.

- timestamp: 2026-10-06T19:32:00Z
  checked: D-87a (CONTEXT :287-290) and ROADMAP 06.3.4.1 SC-1 (:918)
  found: D-87a: "the run of record's journal partial flag matches its measured completeness comparison, and score/report accept it through the unmodified fail-closed path. Any halted diagnostic drive stays partial: true and is never reported as complete." ROADMAP SC-1: "Journal completeness metadata matches reality (partial: true if incomplete). No score/report of a halted run as complete."
  implication: evaluate_sc1 implements the metadata-honesty clause literally; the precondition "the journal under gate IS the run of record, i.e. complete" was presupposed by the spec wording and never encoded. The "never reported as complete" clause is what main's all-PASS table violates.

- timestamp: 2026-10-06T19:40:00Z
  checked: `git log -S STAGED_PAIRING_COVERAGE_FLOOR -- eval/src/lancet_eval/gate.py`
  found: introduced in eb893ba1 at 2026-09-09T09:55:54-07:00 (06.3.4-01), before drive 1 (2026-09-30), drive 1b (2026-10-01) and drive 2 (2026-10-06). Against the sample-scoped denominator, 0.80 leaves every recorded verdict unchanged (drive1 SC-3 88/90 = 0.978, already MISS on the usable floor; drive1b SC-3 90/90; drive2 SC-3 90/90, SC-4 89/90 = 0.989, SC-5 65/65) and MISSes both reproductions (p1_halt40: SC-3/SC-4 17/90 = 0.189, SC-5 10/65 = 0.154; p2_one_pair: 1/90, 1/65).
  implication: reusing this pre-existing literal (its value was fixed before any 06.3.4.1 drive data existed) is the strongest available answer to "not tuned against drive-2 data". Still a planner/owner decision, not chosen here.

- timestamp: 2026-10-06T19:41:00Z
  checked: test_the_drive2_literals_are_committed_with_their_values (test_unpark_gates.py:1417-1422); grep for dir()/vars()/__all__ over eval/tests
  found: it pins three values (GRAPH_COMPOSITION_CHANGE_FLOOR 0.10, GRAPH_PRESENCE_WILSON_LOWER_FLOOR 0.098, SC5_VISIBILITY_RULE string); no test pins the module's name surface.
  implication: a new coverage literal in thresholds.py breaks nothing. Changing SC5_VISIBILITY_RULE (e.g. to add a min n to rule (a)) WOULD break it, would require changing _KNOWN_SC5_RULES (:567), would edit an existing pre-registered gate rule (forbidden by the plan-01 judgment prohibition), and would make any later re-read of drive 2 return MISS "unknown SC-5 rule". It is also unnecessary: with the sample-scoped denominator the 1-pair journal is 1/65 coverage and already MISSes.

## Resolution

root_cause: "(1) evaluate_sc1 (eval/src/lancet_eval/unpark_gates.py:122-142) uses completeness_comparison only to derive the expected header flag, so an incomplete journal honestly labelled partial:true with no report.json yields zero reasons and status PASS; (2) main (:1323-1365) never calls completeness_comparison, never reads SC-1, and computes SC-2, D-69, SC-3, SC-4, SC-5 over whatever records exist; (3) no evaluator compares its n to an expected-population denominator - SC-3 n=len(scored_rows) (:430) vs p>=floor (:436), SC-4 only n==0 (:766), SC-5 only `not pairs_v` (:1073) with rule (a) having no min n (:1078) - and the only existing coverage figure (SC-5 pairing_coverage, :1025/:1040) is journal-relative and reads 1.0 on a partial journal. Reproduced: a 40/200-unit and a 2/200-unit truncation of the drive-2 journal both read SC-1/SC-4/SC-5 PASS."
fix: (not applied - goal find_root_cause_only; plan-phase --gaps handles fixes)
suggested_fix_direction: |
  - main: compute (is_complete, missing) = completeness_comparison(journal, header corpus) once; on not is_complete OR no resolvable corpus, every reading (SC-1..SC-5, D-69; disclosures included) is MISS "journal incomplete: N work unit(s) missing". Gate on the measured is_complete, NOT on sc1.status (the main fixtures write complete journals with header_partial=True, which MISS SC-1 on header mismatch - a different condition). Pass is_complete into evaluate_sc1 so SC-1 = header honest AND complete AND report.json present.
  - coverage floors: after n is computed - SC-3 at :430, SC-4 at :765, SC-5 at :1073 (use composition["n"] for rule (a), since unmeasured pairs leave it). Denominator = expected sample & G (90) for SC-3/SC-4 and expected sample & V (65) for SC-5, passed in by main as a keyword-only argument (the corpus= pattern). NOT len(g_ids)/len(v_ids) (corpus-wide 398/291 -> drive 2 reads 0.226/0.224/0.223 and any floor above ~0.22 flips all three recorded gates). NOT the journal-relative pairing_coverage. Report n, expected, coverage in detail; WR-04's excluded_by_class belongs beside SC-3's.
  - threshold discipline: completeness gating and the SC-1 predicate are logic changes, not thresholds. The only new pre-registered literal is the coverage floor; candidate value is gate.py STAGED_PAIRING_COVERAGE_FLOOR = 0.80 (committed 2026-09-09, before any 06.3.4.1 drive). Its provenance comment must scope it to drives started after its commit. Do not rewrite gates-drive2.{md,json}; any re-read of drive 2 under the new code is a labelled disclosure. Do not touch SC5_VISIBILITY_RULE / _KNOWN_SC5_RULES.
  - tests: new red tests for honest-partial SC-1 and for main MISSing every reading on a truncated journal; update the exact payload key lists at test_unpark_gates.py:1627 and :1653-1661 only if a payload key is added.
verification:
files_changed: []
