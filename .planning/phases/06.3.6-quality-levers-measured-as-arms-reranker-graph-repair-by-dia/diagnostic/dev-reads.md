# Dev reads ledger (D-154)

Rendered from `dev-reads.jsonl`: 10 entries, in file order. The jsonl is the record; this file is derived from it.

## 1. rule [dev-protocol-o7-o12-o13]

- entry_id: `rule-dcec22e856f9`
- rule_id: dev-protocol-o7-o12-o13
- plan: 06.3.6-16
- decisions: ["D-178", "D-179", "D-180"]
- reply: all-recommended (06.3.6-16 Task 1 checkpoint:decision, pre-answered by D-178, D-179 and D-180 in 06.3.6-CONTEXT.md 'Pre-answered checkpoints'; quoted, not waited for)
- written_before_read_1: true
- branch: B (lever 2 selection graph_list_precision; graph-v2 is the chunk-precision variant)
- o7_blanket_cap: {"cap_usd": 2.0, "decision": "D-178", "estimate_for_1200_records": "mean $0.98, all-max $4.63 (research/cost_caps_06_3_6_dev1200.out); one 100-record lever read is about $0.07; the cap is about 2.0x the mean", "output_price_decision": "D-173 (plan 06.3.6-03 raised GENERATION_OUTPUT_PRICE_PER_1M from 0.32 to 1.28), so the $2.00 figure applies, not $1.50", "output_price_per_1m": 1.28, "preflight": "the dev arm-canary preflight (about $0.005) runs uncapped before each session and is acknowledged by D-178; a RERANK_DEGRADED canary is counted and reported per arm, not failed alone; the preflight fails when a rerank-bearing arm has no successful rerank canary or when the degraded canaries over the rerank-bearing arms reach PREFLIGHT_RERANK_DEGRADE_HALT (the dev corpus has no pre-registration)", "record_bound": "100 x each session's arm count, at most 600 per session, so at most 1,200 dev records over both sessions", "scope": "every dev read, sessions 1 and 2, under one cap; session 2 runs under the remainder; a resume keeps the same whole-session --stage-cap and a different cap needs a new D-86 checkpoint", "unit": "harness-estimate dollars (run.py caps against compute_spend, which includes the rerank line, D-176)"}
- o13_session_reference: {"decision": "D-179", "rule": "each dev session runs its own hybrid (and hybrid+graph when graph-v2 is read) on the same 100 dev questions, at --workers 1 --retries 0, in a new run directory; drive-2 dev records are not reused", "session_1_arms": ["hybrid", "hybrid+graph", "hybrid+rerank", "hybrid+metadata", "hybrid+answer-format", "hybrid+graph-v2"], "session_1_records_at_most": 600}
- o12_precision_read_2: {"decision": "D-180", "rule": "graph-v2 (branch B): read 1 runs ChunkSelection EdgeEvidence; read 2 (MultiCited(2)) runs iff read 1's dev paired delta of answer_usable (hybrid+graph-v2 minus the same-session hybrid) is <= 0", "session_1_override": "LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION=edge_evidence"}
- read2_triggers: {"answer_format": "one revised sentence at the implementer's discretion; the reason is written first (D-147); the dev Yes/No/abstain shares and the dev null pairs (n = 10) are disclosed beside each reading and no wording is chosen for moving them", "graph_v2_branch_A_er": "not applicable on this branch (the next lower sweep threshold if the dev delta <= 0, the next higher if the merge audit found more than 2 false merges of 20)", "graph_v2_branch_B": "O12 above", "metadata": "one revised policy sentence at the implementer's discretion; the reason is written to the ledger first (D-143)", "rerank": "only the D-135 lower-bound case (derive-rerank-timeout label lower_bound); read 2 then runs with rerank_timeout_ms = max(3412, ceil(2 x lower bound)) and retrieve_timeout_ms = 294 + that + 500 through the dev-only overrides LANCET_ENGINE__WORKFLOW__RERANK_TIMEOUT_MS and LANCET_ENGINE__WORKFLOW__RETRIEVE_TIMEOUT_MS"}
- freeze_choice: for every lever the read with the larger dev delta against its own session's hybrid; a tie keeps read 1 (D-154)
- limits: at most 2 paid dev reads per lever overall (D-154); dev IDs only through the dev split role (D-170, D-106); no held-out number is read or quoted to set a parameter (D-129)
- mechanical: each trigger is applied as written to the session's measured numbers; none is revised after read 1

## 2. read: rerank (read 1)

- entry_id: `read-718ec5daee51`
- run_dir: eval/runs/2026-10-10-levers-s1-multihop_rag_levers_dev
- session: s1
- read: 1
- index_generation: lance-703
- reference: the same session's hybrid arm (O13, D-179)
- engine_settings: {"generation_provider_pin": "D-191 order [\"sail-research\"], allow_fallbacks false", "head_sha_at_launch": "c077bef25d6a7e93b273ec368a05b6a583bee21d", "overrides_in_force": {"LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION": "edge_evidence"}, "prompt_sentences_commit": "e4ef66272713750b52af1fa5fe9627e17d837c6a", "rerank_timeout_ms": 1706, "retrieve_timeout_ms": 2500}
- label: unadjusted, estimation only
- lever: rerank
- arm: hybrid+rerank
- delta_answer_usable: 0.03409090909090917
- ci: [-0.045454545454545456, 0.11363636363636363]
- n_pairs: 88
- n_pos: 8
- n_neg: 5
- null_pairs: {"b": 0, "c": 0, "n": 10}
- mean_arm: 0.5909090909090909
- mean_hybrid: 0.5568181818181818
- comparison_shares: {"arm": {"insufficient_information": 0.29411764705882354, "no": 0.14705882352941177, "other": 0.058823529411764705, "yes": 0.5}, "hybrid": {"insufficient_information": 0.35294117647058826, "no": 0.11764705882352941, "other": 0.11764705882352941, "yes": 0.4117647058823529}, "n": 34}
- mean_prompt_tokens: 2315.2272727272725
- hits_at_4: {"available": true, "ci_hi": 0.2159090909090909, "ci_label": "unadjusted, estimation only", "ci_lo": 0.03409090909090909, "delta": 0.125, "mean_arm": 0.8863636363636364, "mean_hybrid": 0.7613636363636364, "n": 88, "note": null}
- records: 100
- records_with_retries: 0
- rerank_outcomes: {"completed": 98, "degraded_timeout": 1, "degraded_transport": 1}
- read2_decision: none
- read2_rule_applied: rerank read 2 only in the D-135 lower-bound case; the derivation label is censored_above_p95_rank(1) (is_lower_bound false), so the trigger did not fire
- note: T = 2286 ms does not nest in retrieve_timeout_ms 2500 (required 3080); that is the O11 freeze question for plan 06.3.6-18, not a read-2 trigger

## 3. read: graph-v2 (read 1)

- entry_id: `read-a99163059b46`
- run_dir: eval/runs/2026-10-10-levers-s1-multihop_rag_levers_dev
- session: s1
- read: 1
- index_generation: lance-703
- reference: the same session's hybrid arm (O13, D-179)
- engine_settings: {"generation_provider_pin": "D-191 order [\"sail-research\"], allow_fallbacks false", "head_sha_at_launch": "c077bef25d6a7e93b273ec368a05b6a583bee21d", "overrides_in_force": {"LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION": "edge_evidence"}, "prompt_sentences_commit": "e4ef66272713750b52af1fa5fe9627e17d837c6a", "rerank_timeout_ms": 1706, "retrieve_timeout_ms": 2500}
- label: unadjusted, estimation only
- lever: graph-v2
- arm: hybrid+graph-v2
- delta_answer_usable: -0.011111111111111183
- ci: [-0.06666666666666667, 0.044444444444444446]
- n_pairs: 90
- n_pos: 3
- n_neg: 4
- null_pairs: {"b": 0, "c": 0, "n": 10}
- mean_arm: 0.5444444444444444
- mean_hybrid: 0.5555555555555556
- comparison_shares: {"arm": {"insufficient_information": 0.4444444444444444, "no": 0.08333333333333333, "other": 0.1388888888888889, "yes": 0.3333333333333333}, "hybrid": {"insufficient_information": 0.3333333333333333, "no": 0.1111111111111111, "other": 0.1388888888888889, "yes": 0.4166666666666667}, "n": 36}
- mean_prompt_tokens: 2470.9333333333334
- hits_at_4: {"available": true, "ci_hi": 0.022222222222222223, "ci_label": "unadjusted, estimation only", "ci_lo": -0.06666666666666667, "delta": -0.022222222222222254, "mean_arm": 0.7333333333333333, "mean_hybrid": 0.7555555555555555, "n": 90, "note": null}
- records: 100
- records_with_retries: 0
- variant_read: ChunkSelection EdgeEvidence (GRAPH_V2_CHUNK_PRECISION=edge_evidence)
- v1_control_hybrid_graph: {"ci": [-0.07865168539325842, 0.056179775280898875], "comparison_shares": {"arm": {"insufficient_information": 0.3611111111111111, "no": 0.08333333333333333, "other": 0.1111111111111111, "yes": 0.4444444444444444}, "hybrid": {"insufficient_information": 0.3333333333333333, "no": 0.1111111111111111, "other": 0.1388888888888889, "yes": 0.4166666666666667}, "n": 36}, "delta_answer_usable": -0.011235955056179803, "hits_at_4": null, "mean_arm": 0.5393258426966292, "mean_hybrid": 0.550561797752809, "mean_prompt_tokens": 2467.4606741573034, "n_neg": 5, "n_pairs": 89, "n_pos": 4, "null_pairs": {"b": 0, "c": 0, "n": 10}, "records": 100, "records_with_retries": 0}
- read2_decision: TRIGGERED
- read2_rule_applied: O12 (D-180): read 2 (MultiCited(2)) iff read 1 dev paired delta of answer_usable <= 0; read 1 delta = -0.011111 <= 0

## 4. read: metadata (read 1)

- entry_id: `read-3289c9eebbea`
- run_dir: eval/runs/2026-10-10-levers-s1-multihop_rag_levers_dev
- session: s1
- read: 1
- index_generation: lance-703
- reference: the same session's hybrid arm (O13, D-179)
- engine_settings: {"generation_provider_pin": "D-191 order [\"sail-research\"], allow_fallbacks false", "head_sha_at_launch": "c077bef25d6a7e93b273ec368a05b6a583bee21d", "overrides_in_force": {"LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION": "edge_evidence"}, "prompt_sentences_commit": "e4ef66272713750b52af1fa5fe9627e17d837c6a", "rerank_timeout_ms": 1706, "retrieve_timeout_ms": 2500}
- label: unadjusted, estimation only
- lever: metadata
- arm: hybrid+metadata
- delta_answer_usable: 0.09999999999999998
- ci: [0.022222222222222223, 0.17777777777777778]
- n_pairs: 90
- n_pos: 11
- n_neg: 2
- null_pairs: {"b": 0, "c": 0, "n": 10}
- mean_arm: 0.6555555555555556
- mean_hybrid: 0.5555555555555556
- comparison_shares: {"arm": {"insufficient_information": 0.25, "no": 0.1111111111111111, "other": 0.08333333333333333, "yes": 0.5555555555555556}, "hybrid": {"insufficient_information": 0.3333333333333333, "no": 0.1111111111111111, "other": 0.1388888888888889, "yes": 0.4166666666666667}, "n": 36}
- mean_prompt_tokens: 2724.4444444444443
- hits_at_4: null
- records: 100
- records_with_retries: 0
- read2_decision: none
- read2_rule_applied: discretionary (D-143): none. Read 1 delta is positive (see ci) and no defect in the sentence was observed that a revision would fix on principle; choosing a revised sentence from 90 dev questions would be tuning wording on the dev numbers. The freeze keeps read 1.

## 5. read: answer-format (read 1)

- entry_id: `read-bb17c830cf89`
- run_dir: eval/runs/2026-10-10-levers-s1-multihop_rag_levers_dev
- session: s1
- read: 1
- index_generation: lance-703
- reference: the same session's hybrid arm (O13, D-179)
- engine_settings: {"generation_provider_pin": "D-191 order [\"sail-research\"], allow_fallbacks false", "head_sha_at_launch": "c077bef25d6a7e93b273ec368a05b6a583bee21d", "overrides_in_force": {"LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION": "edge_evidence"}, "prompt_sentences_commit": "e4ef66272713750b52af1fa5fe9627e17d837c6a", "rerank_timeout_ms": 1706, "retrieve_timeout_ms": 2500}
- label: unadjusted, estimation only
- lever: answer-format
- arm: hybrid+answer-format
- delta_answer_usable: -0.033333333333333326
- ci: [-0.1111111111111111, 0.044444444444444446]
- n_pairs: 90
- n_pos: 5
- n_neg: 8
- null_pairs: {"b": 0, "c": 0, "n": 10}
- mean_arm: 0.5222222222222223
- mean_hybrid: 0.5555555555555556
- comparison_shares: {"arm": {"insufficient_information": 0.3611111111111111, "no": 0.19444444444444445, "other": 0.027777777777777776, "yes": 0.4166666666666667}, "hybrid": {"insufficient_information": 0.3333333333333333, "no": 0.1111111111111111, "other": 0.1388888888888889, "yes": 0.4166666666666667}, "n": 36}
- mean_prompt_tokens: 2347.7
- hits_at_4: null
- records: 100
- records_with_retries: 0
- read2_decision: none
- read2_rule_applied: discretionary (D-147): none. The delta CI spans 0; the Yes/No/other shares moved in the intended direction (other down, No up) and AI-SPEC 4b forbids choosing a wording for moving those shares or the n = 10 null pairs. The freeze keeps read 1.

## 6. derivation: rerank

- entry_id: `derivation-d32847549b91`
- lever: rerank
- session: s1
- run_dir: eval/runs/2026-10-10-levers-s1-multihop_rag_levers_dev
- rule: D-135 censoring-aware derivation (dev_reads derive-rerank-timeout), provisional rerank_timeout_ms 1706, retrieve_timeout_ms 2500
- arm: hybrid+rerank
- budget_censored_status: clean
- budget_rule: p95_multiplier_rule
- ci_high_ms: null
- ci_high_unbounded: true
- ci_low_ms: 1059.0
- decision: does_not_fit
- excluded: {"malformed": 0, "no_telemetry": 0, "status": 0, "transport": 1, "unspecified": 0}
- is_lower_bound: false
- k: 1
- label: censored_above_p95_rank(1)
- multiplier: 1.5
- n: 99
- nests: false
- p95_ms: 1524.0
- percentile: 0.95
- required_retrieve_ms: 3080
- retrieve_timeout_ms: 2500
- schema_version: 1
- search_allowance_ms: 294
- slack_ms: 500.0
- t_ms: 2286

## 7. read2_reason: graph-v2

- entry_id: `read2_reason-073ce4ad04de`
- lever: graph-v2
- trigger: O12 (D-180, rule entry dev-protocol-o7-o12-o13): read 1 (EdgeEvidence) dev paired delta of answer_usable against the same-session hybrid <= 0
- read1_delta_answer_usable: -0.011111111111111183
- read1_ci: [-0.06666666666666667, 0.044444444444444446]
- read1_hits_at_4_delta: -0.022222222222222254
- read2_settings: {"chunk_selection": "MultiCited(2)", "generation_provider_pin": "D-191 order [\"sail-research\"], allow_fallbacks false", "no_other_override": true, "override": "LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION=multi_cited", "reference": "session 2 own hybrid (O13)", "rerank_timeout_ms": 1706, "retrieve_timeout_ms": 2500, "session_2_arms": ["hybrid", "hybrid+graph", "hybrid+graph-v2"]}
- freeze_rule: the read with the larger dev delta against its own session hybrid; a tie keeps read 1 (EdgeEvidence)
- written_before_read_2: true
- other_levers: rerank, metadata and answer-format take no read 2 (see their read entries), so session 2 carries no revised sentence and no rerank override

## 8. read2_reason: graph-v2

- entry_id: `read2_reason-aa7e770329ed`
- lever: graph-v2
- launch_intent: true
- is_new_trigger: false
- note: read-2 launch-intent copy (plan 06.3.6-17 Task 1 step 4), not a new trigger. The ledger has no kind for a pre-session intent note (a read entry needs a finished run_dir journal, and Task 3 writes the one read-2 entry), so it is recorded as a read2_reason carrying the settings actually in force at launch.
- copies_read2_reason: read2_reason-073ce4ad04de
- read2_settings: {"chunk_selection": "MultiCited(2)", "generation_provider_pin": "D-191 order [\"sail-research\"], allow_fallbacks false", "no_other_override": true, "override": "LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION=multi_cited", "reference": "session 2 own hybrid (O13)", "rerank_timeout_ms": 1706, "retrieve_timeout_ms": 2500, "session_2_arms": ["hybrid", "hybrid+graph", "hybrid+graph-v2"]}
- in_force_at_launch: {"engine_pid": 21244, "engine_start_time_utc": "2026-10-10T07:13:01.4840129Z", "expected_records": 300, "gateway_pid": 3348, "gateway_start_time_utc": "2026-10-10T07:13:03.9235874Z", "generation": "lance-703", "head_at_launch": "28a4a75585b19a15e23fb2b78c4df58f1a571ae5", "override": "LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION=multi_cited", "preflight": "PASS 9 of 9 arm canaries, generation_served Sail Research", "run_dir": "eval/runs/2026-10-10-levers-s2-multihop_rag_levers_dev2", "stage_cap_derivation": "2.00 - 0.44445306", "stage_cap_usd": 1.55554694}
- written_before_read_2: true

## 9. read: graph-v2 (read 2)

- entry_id: `read-d1b06caf1b12`
- run_dir: eval/runs/2026-10-10-levers-s2-multihop_rag_levers_dev2
- session: s2
- read: 2
- index_generation: lance-703
- reference: the same session's hybrid arm (O13, D-179)
- engine_settings: {"generation_provider_pin": "D-191 order [\"sail-research\"], allow_fallbacks false", "head_sha_at_launch": "28a4a75585b19a15e23fb2b78c4df58f1a571ae5", "overrides_in_force": {"LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION": "multi_cited"}, "prompt_sentences_commit": "e4ef66272713750b52af1fa5fe9627e17d837c6a", "rerank_timeout_ms": 1706, "retrieve_timeout_ms": 2500}
- label: unadjusted, estimation only
- lever: graph-v2
- arm: hybrid+graph-v2
- delta_answer_usable: -0.05555555555555547
- ci: [-0.12222222222222222, 0.0]
- n_pairs: 90
- n_pos: 2
- n_neg: 7
- null_pairs: {"b": 0, "c": 0, "n": 10}
- mean_arm: 0.5222222222222223
- mean_hybrid: 0.5777777777777777
- comparison_shares: {"arm": {"insufficient_information": 0.3611111111111111, "no": 0.1388888888888889, "other": 0.05555555555555555, "yes": 0.4444444444444444}, "hybrid": {"insufficient_information": 0.3333333333333333, "no": 0.1388888888888889, "other": 0.1388888888888889, "yes": 0.3888888888888889}, "n": 36}
- mean_prompt_tokens: 2476.366666666667
- hits_at_4: {"available": true, "ci_hi": 0.022222222222222223, "ci_label": "unadjusted, estimation only", "ci_lo": -0.06666666666666667, "delta": -0.022222222222222254, "mean_arm": 0.7333333333333333, "mean_hybrid": 0.7555555555555555, "n": 90, "note": null}
- records: 100
- records_with_retries: 0
- variant_read: ChunkSelection MultiCited(2) (GRAPH_V2_CHUNK_PRECISION=multi_cited)
- v1_control_hybrid_graph: {"ci": [-0.12222222222222222, 0.011111111111111112], "comparison_shares": {"arm": {"insufficient_information": 0.4166666666666667, "no": 0.16666666666666666, "other": 0.05555555555555555, "yes": 0.3611111111111111}, "hybrid": {"insufficient_information": 0.3333333333333333, "no": 0.1388888888888889, "other": 0.1388888888888889, "yes": 0.3888888888888889}, "n": 36}, "delta_answer_usable": -0.05555555555555547, "hits_at_4": null, "mean_arm": 0.5222222222222223, "mean_hybrid": 0.5777777777777777, "mean_prompt_tokens": 2467.1666666666665, "n_neg": 7, "n_pairs": 90, "n_pos": 2, "null_pairs": {"b": 0, "c": 0, "n": 10}, "records": 100, "records_with_retries": 0}
- read2_decision: final read (no third read, D-154)
- read2_rule_applied: read 2 of the lever; the freeze rule picks the larger dev delta against the same-session hybrid (a tie keeps read 1)
- note: The v1 control hybrid+graph moved by the same amount in this session (delta -0.0556, same n_pos 2 and n_neg 7 as hybrid+graph-v2): the session-2 hybrid reference scored higher (0.578 vs 0.556 in session 1) on a different draw of generations, so part of the read 2 gap is the reference, not the variant. Disclosed (D-139); the rule is not changed.

## 10. freeze

- entry_id: `freeze-d2b57135cf7c`
- plan: 06.3.6-17
- candidate: true
- rule: for every lever the read with the larger dev delta against its own session hybrid; a tie keeps read 1 (D-154); computed mechanically after session 2, no held-out number read (D-129)
- branch: B (graph_list_precision); branch A (ER theta) is not applicable, so there is no side-table rebuild and no graph_v2_manifest.json
- levers: {"answer-format": {"chosen_read": 1, "ci": [-0.1111111111111111, 0.044444444444444446], "dev_delta_answer_usable": -0.033333333333333326, "parameter": "BINARY_ANSWER_FORMAT_RULES as committed in e4ef6627 (unchanged)", "reads": 1, "sentence": "If the question can be answered with yes or no, the Answer line and the JSON `final_answer` field must each be exactly Yes or No, with nothing else on them. For such a question, decide from the evidence: when the evidence covers both parts of the claim and they do not match it, answer No rather than Insufficient information. Evidence that does not cover both parts is still insufficient, and the instruction above for insufficient evidence applies unchanged.", "source": "read-bb17c830cf89", "tie_rule_applied": false}, "graph-v2": {"chosen_read": 1, "difference_read1_minus_read2": 0.04444444444444429, "disclosure": "both readings disclosed (D-139); the v1 control hybrid+graph also scored -0.0556 in session 2, so the session-2 reference was higher", "parameter": "ChunkSelection EdgeEvidence (GRAPH_V2_CHUNK_PRECISION=edge_evidence)", "read1": {"ci": [-0.06666666666666667, 0.044444444444444446], "dev_delta_answer_usable": -0.011111111111111183, "entry": "read-a99163059b46", "hits_at_4_delta": -0.022222222222222254, "variant": "EdgeEvidence"}, "read2": {"ci": [-0.12222222222222222, 0.0], "dev_delta_answer_usable": -0.05555555555555547, "hits_at_4_delta": -0.022222222222222254, "variant": "MultiCited(2)"}, "reads": 2, "tie_rule_applied": false}, "metadata": {"chosen_read": 1, "ci": [0.022222222222222223, 0.17777777777777778], "dev_delta_answer_usable": 0.09999999999999998, "parameter": "EVIDENCE_METADATA_POLICY_SENTENCE as committed in e4ef6627 (unchanged)", "reads": 1, "sentence": "Evidence blocks may carry SOURCE, DOC_TITLE and PUBLISHED headers that name the publication, the article title and its publication date. They describe the evidence. Use them when the question refers to a source, an article or a point in time.", "source": "read-3289c9eebbea", "tie_rule_applied": false}, "rerank": {"chosen_read": 1, "ci": [-0.045454545454545456, 0.11363636363636363], "config_retrieve_timeout_ms": 2500, "derivation_entry": "derivation-d32847549b91", "derivation_file": "diagnostic/dev-s1/rerank-derivation.json", "dev_delta_answer_usable": 0.03409090909090917, "label": "censored_above_p95_rank(1)", "nests": false, "note": "no read 2 (lower-bound case did not occur)", "open_owner_choice": "O11 (plan 06.3.6-18 Task 1): the derived T does not nest in retrieve_timeout_ms 2500; (A) raise retrieve_timeout_ms for every arm to 3080, (B) clamp at the 1706 ms room, (C) drop the rerank arm. NOT decided here.", "p95_ms": 1524.0, "parameter": "rerank_timeout_ms derived by D-135, no quality parameter (D-132)", "reads": 1, "required_retrieve_timeout_ms": 3080, "source": "read-718ec5daee51", "t_ms": 2286, "tie_rule_applied": false}}
- branch_a_table_state: not applicable (branch B)
- dev_spend: {"blanket_cap_usd": 2.0, "combined_harness_usd": 0.65626148, "session_1_harness_usd": 0.44445306, "session_2_harness_usd": 0.21180842}
