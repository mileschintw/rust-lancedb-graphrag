# Evaluation Report: multihop_rag_levers_heldout


## Run Metadata

| Parameter | Value |
|---|---|
| **Corpus** | `multihop_rag_levers_heldout` |
| **Run Date** | `2026-10-10T16:47:29.943938+00:00` |
| **Commit SHA** | `5f8324fe3512d89e0c6cfc0d20818a571c4bf62e` |
| **Generation Model** | `deepseek/deepseek-v4-flash-0731` |
| **Embedding Model** | `voyageai/voyage-4-large` |
| **Judge Model** | `meta-llama/llama-3.3-70b-instruct` |
| **Judge Temperature** | `0.0` |
| **Judge Prompt Version** | `v1` |
| **Sampling Seed** | `42` |
| **Deterministic Sample Size** | `351` |
| **Judged Sample Size** | `0` |
| **Completed Calibration Dual Scores** | `0` |
| **Index Generation** | `lance-703` |
| **Result Hash** | `64bad6f11b7678a2` |
| **Dependency Lock Hash** | `8e71ea9ce7a3532b` |
| **Arm Labels** | `hybrid, hybrid+graph, hybrid+rerank, hybrid+metadata, hybrid+answer-format, hybrid+graph-v2, hybrid+all` |
| **Notes** | No judge-versus-human calibration was performed; judged dimensions are uncalibrated. all-arm P_all, not the decisional population: |P_all| = 304 of 308 held-out G questions (coverage 0.987). The per-arm cells are on this population; below any coverage floor they are labelled, never refused, and compare-levers reads one pairwise population per comparison (D-161). |


## Evaluation Dimensions

| Dimension | Status | Score | Sample Size (n) | Details / Reason |
|---|---|---|---|---|


| `unusable_record_rate` | ok | **0.002** | 2457 | unusable_n=4, n_journal=2457, unusable_rate=0.002, ci_lower=0.001, ci_upper=0.004, collapsed_records_n=0 |



| `vector_yield` | ok | **1.000** | 351 | mean_count=32, positive_n=351, n_eval=351, missing_meta_n=0, ci_lower=0.989, ci_upper=1, retrieve_p50_ms=109, retrieve_p95_ms=140.5 |



| `bm25_yield` | ok | **1.000** | 351 | mean_count=32, positive_n=351, n_eval=351, missing_meta_n=0, ci_lower=0.989, ci_upper=1, retrieve_p50_ms=109, retrieve_p95_ms=140.5 |



| `retrieve_latency_ms` | ok | **109.0** | 351 | retrieve_p95_ms=140.5, missing_timing_n=0, n_eval=351 |



| `graph_presence_rate` | ok | **0.570** | 351 | positive_n=200, n_eval=351, missing_meta_n=0, ci_lower=0.518, ci_upper=0.621, investigation_floor=0.200, floor_miss=0, no_match_rate=0, completed_graph_n=349 |



| `graph_influence_rate` | ok | **0.570** | 351 | positive_n=200, n_eval=351, missing_influence_n=0, ci_lower=0.518, ci_upper=0.621 |



| `graph_latency_ms` | ok | **600.0** | 351 | graph_p95_ms=2082.5, missing_timing_n=0, n_eval=351 |



| `retrieval_evidence_coverage` | ok | **0.356** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `context_precision_at_k` | ok | **0.213** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `ranking_quality` | ok | **0.541** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `answer_exact_match` | ok | **0.000** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `answer_f1` | ok | **0.014** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `final_answer_em` | ok | **0.552** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `final_answer_containment` | ok | **0.653** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `answer_usable` | ok | **0.565** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `final_answer_missing_rate` | ok | **0.000** | 308 | errors=0, sample_size=308, excluded_payload_records=0 |



| `answer_faithfulness` | skipped | — | 0 | Deferred to LLM-as-judge scoring pass (--no-judge specified); judged_slice_committed=0, verdicts_obtained=0, judged_slice_state=0, usage_absent_fallback_count=0 |



| `answer_groundedness` | skipped | — | 0 | Deferred to LLM-as-judge scoring pass (--no-judge specified); judged_slice_committed=0, verdicts_obtained=0, judged_slice_state=0, usage_absent_fallback_count=0 |



| `graph_ablation_delta` | ok | **-0.010** | 308 | n_pairs=308, pairing_coverage=0.877, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, single_arm_usable_drops=0, missing_arm_drops=0, null_gold_drops=43, provenance_drops=0, ci_lower=-0.027, ci_upper=0.008, delta_comparison_query=0.004, n_pairs_comparison_query=125, delta_temporal_query=-0.015, n_pairs_temporal_query=78, delta_inference_query=-0.022, n_pairs_inference_query=105 |



| `graph_ablation_delta_exact_match` | ok | **0.000** | 308 | n_pairs=308, pairing_coverage=0.877, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=0, ci_upper=0, delta_comparison_query=0, n_pairs_comparison_query=125, delta_temporal_query=0, n_pairs_temporal_query=78, delta_inference_query=0, n_pairs_inference_query=105 |



| `graph_ablation_delta_f1` | ok | **0.000** | 308 | n_pairs=308, pairing_coverage=0.877, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.001, ci_upper=0.001, delta_comparison_query=0.000, n_pairs_comparison_query=125, delta_temporal_query=-0.001, n_pairs_temporal_query=78, delta_inference_query=0.001, n_pairs_inference_query=105 |



| `graph_ablation_delta_context_precision` | ok | **-0.008** | 308 | n_pairs=308, pairing_coverage=0.877, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.019, ci_upper=0.002, delta_comparison_query=0, n_pairs_comparison_query=125, delta_temporal_query=-0.010, n_pairs_temporal_query=78, delta_inference_query=-0.017, n_pairs_inference_query=105 |



| `graph_ablation_delta_ranking_quality` | ok | **-0.038** | 308 | n_pairs=308, pairing_coverage=0.877, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.063, ci_upper=-0.014, delta_comparison_query=-0.037, n_pairs_comparison_query=125, delta_temporal_query=-0.037, n_pairs_temporal_query=78, delta_inference_query=-0.040, n_pairs_inference_query=105 |



| `graph_ablation_latency_delta` | ok | **-18.5** | 308 | n_pairs=308, pairing_coverage=0.877, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-277.114, ci_upper=238.084, delta_comparison_query=-152.560, n_pairs_comparison_query=125, delta_temporal_query=-300.192, n_pairs_temporal_query=78, delta_inference_query=350.238, n_pairs_inference_query=105 |



| `graph_ablation_prompt_token_delta` | ok | **198.1** | 308 | n_pairs=308, pairing_coverage=0.877, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=174.607, ci_upper=222.231, delta_comparison_query=218.296, n_pairs_comparison_query=125, delta_temporal_query=235.603, n_pairs_temporal_query=78, delta_inference_query=146.257, n_pairs_inference_query=105 |



| `abstention_on_unanswerable` | ok | **0.953** | 43 | null_samples=43, excluded_payload_records=0 |



| `null_abstention_correctness` | ok | **0.953** | 43 | null_samples=43, excluded_payload_records=0 |



| `wire_contract_conformance` | ok | **1.000** | 2457 | n_journal=2457, conforming_n=2457, violations_n=0, unparseable_n=0, contradiction_n=0, ci_lower=0.998, ci_upper=1 |



| `community_summary_quality` | skipped | — | 0 | Deferred to Phase 999.1 (community summaries not yet implemented in engine) |



| `run_traceability` | ok | **1.000** | 2457 | traced_records=2457, total_records=2457 |



| `p4_size` | ok | **304.000** | 304 | coverage=0.987, n_heldout_g=308, n_heldout_null=43, excluded_own_failure__hybrid=0, excluded_provenance__hybrid=0, excluded_other_arm_failure__hybrid=4, excluded_own_failure__hybrid_graph=0, excluded_provenance__hybrid_graph=0, excluded_other_arm_failure__hybrid_graph=4, pairwise_join_size__hybrid_graph=308, excluded_own_failure__hybrid_rerank=0, excluded_provenance__hybrid_rerank=0, excluded_other_arm_failure__hybrid_rerank=4, pairwise_join_size__hybrid_rerank=308, excluded_own_failure__hybrid_metadata=2, excluded_provenance__hybrid_metadata=0, excluded_other_arm_failure__hybrid_metadata=2, pairwise_join_size__hybrid_metadata=306, excluded_own_failure__hybrid_answer_format=1, excluded_provenance__hybrid_answer_format=0, excluded_other_arm_failure__hybrid_answer_format=3, pairwise_join_size__hybrid_answer_format=307, excluded_own_failure__hybrid_graph_v2=0, excluded_provenance__hybrid_graph_v2=0, excluded_other_arm_failure__hybrid_graph_v2=4, pairwise_join_size__hybrid_graph_v2=308, excluded_own_failure__hybrid_all=0, excluded_provenance__hybrid_all=1, excluded_other_arm_failure__hybrid_all=3, pairwise_join_size__hybrid_all=307 |



| `arm_provenance_conformance` | ok | **1.000** | 2457 | code_a=0, code_b=0, code_c=0, code_d=0, code_e=0, code_f=0, code_g=0, code_h=0, code_i=2, code_j=0, records_checked=2457, records_failing_zero_tolerance=0 |



| `paper_hits_at_4__hybrid` | ok | **0.694** | 304 | n_excluded=4, n_unscorable=0, successes=211, ci_lower=0.640, ci_upper=0.743, type_comparison_query_n=123, type_comparison_query_value=0.724, type_comparison_query_ci_lower=0.639, type_comparison_query_ci_upper=0.795, type_inference_query_n=103, type_inference_query_value=0.767, type_inference_query_ci_lower=0.677, type_inference_query_ci_upper=0.838, type_temporal_query_n=78, type_temporal_query_value=0.551, type_temporal_query_ci_lower=0.441, type_temporal_query_ci_upper=0.657 |



| `paper_hits_at_4__hybrid_graph` | ok | **0.678** | 304 | n_excluded=4, n_unscorable=0, successes=206, ci_lower=0.623, ci_upper=0.728, type_comparison_query_n=123, type_comparison_query_value=0.707, type_comparison_query_ci_lower=0.622, type_comparison_query_ci_upper=0.780, type_inference_query_n=103, type_inference_query_value=0.748, type_inference_query_ci_lower=0.656, type_inference_query_ci_upper=0.822, type_temporal_query_n=78, type_temporal_query_value=0.538, type_temporal_query_ci_lower=0.429, type_temporal_query_ci_upper=0.645 |



| `paper_hits_at_4__hybrid_rerank` | ok | **0.852** | 304 | n_excluded=4, n_unscorable=0, successes=259, ci_lower=0.808, ci_upper=0.887, type_comparison_query_n=123, type_comparison_query_value=0.911, type_comparison_query_ci_lower=0.847, type_comparison_query_ci_upper=0.949, type_inference_query_n=103, type_inference_query_value=0.845, type_inference_query_ci_lower=0.762, type_inference_query_ci_upper=0.902, type_temporal_query_n=78, type_temporal_query_value=0.769, type_temporal_query_ci_lower=0.664, type_temporal_query_ci_upper=0.849 |



| `paper_hits_at_4__hybrid_metadata` | ok | **0.694** | 304 | n_excluded=4, n_unscorable=0, successes=211, ci_lower=0.640, ci_upper=0.743, type_comparison_query_n=123, type_comparison_query_value=0.724, type_comparison_query_ci_lower=0.639, type_comparison_query_ci_upper=0.795, type_inference_query_n=103, type_inference_query_value=0.767, type_inference_query_ci_lower=0.677, type_inference_query_ci_upper=0.838, type_temporal_query_n=78, type_temporal_query_value=0.551, type_temporal_query_ci_lower=0.441, type_temporal_query_ci_upper=0.657 |



| `paper_hits_at_4__hybrid_answer_format` | ok | **0.694** | 304 | n_excluded=4, n_unscorable=0, successes=211, ci_lower=0.640, ci_upper=0.743, type_comparison_query_n=123, type_comparison_query_value=0.724, type_comparison_query_ci_lower=0.639, type_comparison_query_ci_upper=0.795, type_inference_query_n=103, type_inference_query_value=0.767, type_inference_query_ci_lower=0.677, type_inference_query_ci_upper=0.838, type_temporal_query_n=78, type_temporal_query_value=0.551, type_temporal_query_ci_lower=0.441, type_temporal_query_ci_upper=0.657 |



| `paper_hits_at_4__hybrid_graph_v2` | ok | **0.681** | 304 | n_excluded=4, n_unscorable=0, successes=207, ci_lower=0.627, ci_upper=0.731, type_comparison_query_n=123, type_comparison_query_value=0.724, type_comparison_query_ci_lower=0.639, type_comparison_query_ci_upper=0.795, type_inference_query_n=103, type_inference_query_value=0.757, type_inference_query_ci_lower=0.666, type_inference_query_ci_upper=0.830, type_temporal_query_n=78, type_temporal_query_value=0.513, type_temporal_query_ci_lower=0.404, type_temporal_query_ci_upper=0.621 |



| `paper_hits_at_4__hybrid_all` | ok | **0.852** | 304 | n_excluded=4, n_unscorable=0, successes=259, ci_lower=0.808, ci_upper=0.887, type_comparison_query_n=123, type_comparison_query_value=0.911, type_comparison_query_ci_lower=0.847, type_comparison_query_ci_upper=0.949, type_inference_query_n=103, type_inference_query_value=0.845, type_inference_query_ci_lower=0.762, type_inference_query_ci_upper=0.902, type_temporal_query_n=78, type_temporal_query_value=0.769, type_temporal_query_ci_lower=0.664, type_temporal_query_ci_upper=0.849 |



| `paper_hits_at_10__hybrid` | ok | **0.836** | 304 | n_excluded=4, n_unscorable=0, successes=254, ci_lower=0.790, ci_upper=0.873, type_comparison_query_n=123, type_comparison_query_value=0.886, type_comparison_query_ci_lower=0.818, type_comparison_query_ci_upper=0.931, type_inference_query_n=103, type_inference_query_value=0.854, type_inference_query_ci_lower=0.774, type_inference_query_ci_upper=0.910, type_temporal_query_n=78, type_temporal_query_value=0.731, type_temporal_query_ci_lower=0.623, type_temporal_query_ci_upper=0.817 |



| `paper_hits_at_10__hybrid_graph` | ok | **0.812** | 304 | n_excluded=4, n_unscorable=0, successes=247, ci_lower=0.765, ci_upper=0.852, type_comparison_query_n=123, type_comparison_query_value=0.870, type_comparison_query_ci_lower=0.799, type_comparison_query_ci_upper=0.918, type_inference_query_n=103, type_inference_query_value=0.845, type_inference_query_ci_lower=0.762, type_inference_query_ci_upper=0.902, type_temporal_query_n=78, type_temporal_query_value=0.679, type_temporal_query_ci_lower=0.570, type_temporal_query_ci_upper=0.773 |



| `paper_hits_at_10__hybrid_rerank` | ok | **0.918** | 304 | n_excluded=4, n_unscorable=0, successes=279, ci_lower=0.881, ci_upper=0.944, type_comparison_query_n=123, type_comparison_query_value=0.943, type_comparison_query_ci_lower=0.887, type_comparison_query_ci_upper=0.972, type_inference_query_n=103, type_inference_query_value=0.942, type_inference_query_ci_lower=0.879, type_inference_query_ci_upper=0.973, type_temporal_query_n=78, type_temporal_query_value=0.846, type_temporal_query_ci_lower=0.750, type_temporal_query_ci_upper=0.910 |



| `paper_hits_at_10__hybrid_metadata` | ok | **0.832** | 304 | n_excluded=4, n_unscorable=0, successes=253, ci_lower=0.786, ci_upper=0.870, type_comparison_query_n=123, type_comparison_query_value=0.878, type_comparison_query_ci_lower=0.809, type_comparison_query_ci_upper=0.925, type_inference_query_n=103, type_inference_query_value=0.854, type_inference_query_ci_lower=0.774, type_inference_query_ci_upper=0.910, type_temporal_query_n=78, type_temporal_query_value=0.731, type_temporal_query_ci_lower=0.623, type_temporal_query_ci_upper=0.817 |



| `paper_hits_at_10__hybrid_answer_format` | ok | **0.832** | 304 | n_excluded=4, n_unscorable=0, successes=253, ci_lower=0.786, ci_upper=0.870, type_comparison_query_n=123, type_comparison_query_value=0.878, type_comparison_query_ci_lower=0.809, type_comparison_query_ci_upper=0.925, type_inference_query_n=103, type_inference_query_value=0.854, type_inference_query_ci_lower=0.774, type_inference_query_ci_upper=0.910, type_temporal_query_n=78, type_temporal_query_value=0.731, type_temporal_query_ci_lower=0.623, type_temporal_query_ci_upper=0.817 |



| `paper_hits_at_10__hybrid_graph_v2` | ok | **0.816** | 304 | n_excluded=4, n_unscorable=0, successes=248, ci_lower=0.768, ci_upper=0.855, type_comparison_query_n=123, type_comparison_query_value=0.870, type_comparison_query_ci_lower=0.799, type_comparison_query_ci_upper=0.918, type_inference_query_n=103, type_inference_query_value=0.845, type_inference_query_ci_lower=0.762, type_inference_query_ci_upper=0.902, type_temporal_query_n=78, type_temporal_query_value=0.692, type_temporal_query_ci_lower=0.583, type_temporal_query_ci_upper=0.784 |



| `paper_hits_at_10__hybrid_all` | ok | **0.918** | 304 | n_excluded=4, n_unscorable=0, successes=279, ci_lower=0.881, ci_upper=0.944, type_comparison_query_n=123, type_comparison_query_value=0.943, type_comparison_query_ci_lower=0.887, type_comparison_query_ci_upper=0.972, type_inference_query_n=103, type_inference_query_value=0.942, type_inference_query_ci_lower=0.879, type_inference_query_ci_upper=0.973, type_temporal_query_n=78, type_temporal_query_value=0.846, type_temporal_query_ci_lower=0.750, type_temporal_query_ci_upper=0.910 |



| `paper_hits_at_10_delta__hybrid_graph` | ok | **-0.023** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.039, ci_upper=-0.007, n_pairs=304, mean_x=0.812, mean_hybrid=0.836, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.016, type_comparison_query_ci_lower=-0.041, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=-0.010, type_inference_query_ci_lower=-0.029, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.051, type_temporal_query_ci_lower=-0.103, type_temporal_query_ci_upper=-0.013 |



| `paper_hits_at_10_delta__hybrid_rerank` | ok | **0.082** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.043, ci_upper=0.125, n_pairs=304, mean_x=0.918, mean_hybrid=0.836, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.057, type_comparison_query_ci_lower=0.008, type_comparison_query_ci_upper=0.114, type_inference_query_n_pairs=103, type_inference_query_delta=0.087, type_inference_query_ci_lower=0.019, type_inference_query_ci_upper=0.165, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.115, type_temporal_query_ci_lower=0.013, type_temporal_query_ci_upper=0.218 |



| `paper_hits_at_10_delta__hybrid_metadata` | ok | **-0.003** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.010, ci_upper=0, n_pairs=304, mean_x=0.832, mean_hybrid=0.836, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.008, type_comparison_query_ci_lower=-0.024, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `paper_hits_at_10_delta__hybrid_answer_format` | ok | **-0.003** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.010, ci_upper=0, n_pairs=304, mean_x=0.832, mean_hybrid=0.836, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.008, type_comparison_query_ci_lower=-0.024, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `paper_hits_at_10_delta__hybrid_graph_v2` | ok | **-0.020** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.036, ci_upper=-0.007, n_pairs=304, mean_x=0.816, mean_hybrid=0.836, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.016, type_comparison_query_ci_lower=-0.041, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=-0.010, type_inference_query_ci_lower=-0.029, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.038, type_temporal_query_ci_lower=-0.090, type_temporal_query_ci_upper=0 |



| `paper_hits_at_10_delta__hybrid_all` | ok | **0.082** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.043, ci_upper=0.125, n_pairs=304, mean_x=0.918, mean_hybrid=0.836, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.057, type_comparison_query_ci_lower=0.008, type_comparison_query_ci_upper=0.114, type_inference_query_n_pairs=103, type_inference_query_delta=0.087, type_inference_query_ci_lower=0.019, type_inference_query_ci_upper=0.165, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.115, type_temporal_query_ci_lower=0.013, type_temporal_query_ci_upper=0.218 |



| `paper_mrr_at_10__hybrid` | ok | **0.583** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.535, ci_upper=0.630, type_comparison_query_n=123, type_comparison_query_value=0.599, type_comparison_query_ci_lower=0.526, type_comparison_query_ci_upper=0.669, type_inference_query_n=103, type_inference_query_value=0.652, type_inference_query_ci_lower=0.570, type_inference_query_ci_upper=0.730, type_temporal_query_n=78, type_temporal_query_value=0.466, type_temporal_query_ci_lower=0.372, type_temporal_query_ci_upper=0.561 |



| `paper_mrr_at_10__hybrid_graph` | ok | **0.544** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.497, ci_upper=0.592, type_comparison_query_n=123, type_comparison_query_value=0.562, type_comparison_query_ci_lower=0.491, type_comparison_query_ci_upper=0.633, type_inference_query_n=103, type_inference_query_value=0.610, type_inference_query_ci_lower=0.529, type_inference_query_ci_upper=0.688, type_temporal_query_n=78, type_temporal_query_value=0.429, type_temporal_query_ci_lower=0.335, type_temporal_query_ci_upper=0.523 |



| `paper_mrr_at_10__hybrid_rerank` | ok | **0.763** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.723, ci_upper=0.804, type_comparison_query_n=123, type_comparison_query_value=0.808, type_comparison_query_ci_lower=0.747, type_comparison_query_ci_upper=0.865, type_inference_query_n=103, type_inference_query_value=0.767, type_inference_query_ci_lower=0.696, type_inference_query_ci_upper=0.833, type_temporal_query_n=78, type_temporal_query_value=0.688, type_temporal_query_ci_lower=0.597, type_temporal_query_ci_upper=0.777 |



| `paper_mrr_at_10__hybrid_metadata` | ok | **0.583** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.535, ci_upper=0.630, type_comparison_query_n=123, type_comparison_query_value=0.598, type_comparison_query_ci_lower=0.525, type_comparison_query_ci_upper=0.668, type_inference_query_n=103, type_inference_query_value=0.652, type_inference_query_ci_lower=0.571, type_inference_query_ci_upper=0.731, type_temporal_query_n=78, type_temporal_query_value=0.467, type_temporal_query_ci_lower=0.373, type_temporal_query_ci_upper=0.562 |



| `paper_mrr_at_10__hybrid_answer_format` | ok | **0.583** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.535, ci_upper=0.630, type_comparison_query_n=123, type_comparison_query_value=0.598, type_comparison_query_ci_lower=0.525, type_comparison_query_ci_upper=0.668, type_inference_query_n=103, type_inference_query_value=0.652, type_inference_query_ci_lower=0.570, type_inference_query_ci_upper=0.730, type_temporal_query_n=78, type_temporal_query_value=0.467, type_temporal_query_ci_lower=0.373, type_temporal_query_ci_upper=0.562 |



| `paper_mrr_at_10__hybrid_graph_v2` | ok | **0.556** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.509, ci_upper=0.603, type_comparison_query_n=123, type_comparison_query_value=0.567, type_comparison_query_ci_lower=0.496, type_comparison_query_ci_upper=0.638, type_inference_query_n=103, type_inference_query_value=0.640, type_inference_query_ci_lower=0.557, type_inference_query_ci_upper=0.718, type_temporal_query_n=78, type_temporal_query_value=0.426, type_temporal_query_ci_lower=0.332, type_temporal_query_ci_upper=0.518 |



| `paper_mrr_at_10__hybrid_all` | ok | **0.763** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.723, ci_upper=0.804, type_comparison_query_n=123, type_comparison_query_value=0.808, type_comparison_query_ci_lower=0.747, type_comparison_query_ci_upper=0.864, type_inference_query_n=103, type_inference_query_value=0.767, type_inference_query_ci_lower=0.696, type_inference_query_ci_upper=0.833, type_temporal_query_n=78, type_temporal_query_value=0.688, type_temporal_query_ci_lower=0.597, type_temporal_query_ci_upper=0.777 |



| `paper_mrr_at_10_delta__hybrid_graph` | ok | **-0.039** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.064, ci_upper=-0.013, n_pairs=304, mean_x=0.544, mean_hybrid=0.583, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.037, type_comparison_query_ci_lower=-0.082, type_comparison_query_ci_upper=0.006, type_inference_query_n_pairs=103, type_inference_query_delta=-0.042, type_inference_query_ci_lower=-0.079, type_inference_query_ci_upper=-0.004, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.037, type_temporal_query_ci_lower=-0.081, type_temporal_query_ci_upper=0.005 |



| `paper_mrr_at_10_delta__hybrid_rerank` | ok | **0.180** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.135, ci_upper=0.228, n_pairs=304, mean_x=0.763, mean_hybrid=0.583, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.209, type_comparison_query_ci_lower=0.142, type_comparison_query_ci_upper=0.278, type_inference_query_n_pairs=103, type_inference_query_delta=0.115, type_inference_query_ci_lower=0.035, type_inference_query_ci_upper=0.194, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.222, type_temporal_query_ci_lower=0.125, type_temporal_query_ci_upper=0.324 |



| `paper_mrr_at_10_delta__hybrid_metadata` | ok | **-0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.001, ci_upper=0.001, n_pairs=304, mean_x=0.583, mean_hybrid=0.583, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.001, type_comparison_query_ci_lower=-0.003, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0.000, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.001, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.001, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.003 |



| `paper_mrr_at_10_delta__hybrid_answer_format` | ok | **-0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.001, ci_upper=0.001, n_pairs=304, mean_x=0.583, mean_hybrid=0.583, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.001, type_comparison_query_ci_lower=-0.003, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.001, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.003 |



| `paper_mrr_at_10_delta__hybrid_graph_v2` | ok | **-0.027** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.049, ci_upper=-0.005, n_pairs=304, mean_x=0.556, mean_hybrid=0.583, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.032, type_comparison_query_ci_lower=-0.075, type_comparison_query_ci_upper=0.010, type_inference_query_n_pairs=103, type_inference_query_delta=-0.012, type_inference_query_ci_lower=-0.044, type_inference_query_ci_upper=0.020, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.040, type_temporal_query_ci_lower=-0.076, type_temporal_query_ci_upper=-0.008 |



| `paper_mrr_at_10_delta__hybrid_all` | ok | **0.180** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.135, ci_upper=0.227, n_pairs=304, mean_x=0.763, mean_hybrid=0.583, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.209, type_comparison_query_ci_lower=0.142, type_comparison_query_ci_upper=0.278, type_inference_query_n_pairs=103, type_inference_query_delta=0.115, type_inference_query_ci_lower=0.035, type_inference_query_ci_upper=0.194, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.222, type_temporal_query_ci_lower=0.125, type_temporal_query_ci_upper=0.324 |



| `paper_map_at_10__hybrid` | ok | **0.282** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.257, ci_upper=0.309, type_comparison_query_n=123, type_comparison_query_value=0.336, type_comparison_query_ci_lower=0.294, type_comparison_query_ci_upper=0.379, type_inference_query_n=103, type_inference_query_value=0.255, type_inference_query_ci_lower=0.219, type_inference_query_ci_upper=0.291, type_temporal_query_n=78, type_temporal_query_value=0.234, type_temporal_query_ci_lower=0.181, type_temporal_query_ci_upper=0.287 |



| `paper_map_at_10__hybrid_graph` | ok | **0.264** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.238, ci_upper=0.289, type_comparison_query_n=123, type_comparison_query_value=0.317, type_comparison_query_ci_lower=0.275, type_comparison_query_ci_upper=0.362, type_inference_query_n=103, type_inference_query_value=0.239, type_inference_query_ci_lower=0.204, type_inference_query_ci_upper=0.275, type_temporal_query_n=78, type_temporal_query_value=0.211, type_temporal_query_ci_lower=0.162, type_temporal_query_ci_upper=0.260 |



| `paper_map_at_10__hybrid_rerank` | ok | **0.406** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.380, ci_upper=0.432, type_comparison_query_n=123, type_comparison_query_value=0.497, type_comparison_query_ci_lower=0.455, type_comparison_query_ci_upper=0.538, type_inference_query_n=103, type_inference_query_value=0.347, type_inference_query_ci_lower=0.310, type_inference_query_ci_upper=0.383, type_temporal_query_n=78, type_temporal_query_value=0.341, type_temporal_query_ci_lower=0.289, type_temporal_query_ci_upper=0.393 |



| `paper_map_at_10__hybrid_metadata` | ok | **0.282** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.257, ci_upper=0.309, type_comparison_query_n=123, type_comparison_query_value=0.336, type_comparison_query_ci_lower=0.293, type_comparison_query_ci_upper=0.378, type_inference_query_n=103, type_inference_query_value=0.255, type_inference_query_ci_lower=0.219, type_inference_query_ci_upper=0.291, type_temporal_query_n=78, type_temporal_query_value=0.235, type_temporal_query_ci_lower=0.182, type_temporal_query_ci_upper=0.287 |



| `paper_map_at_10__hybrid_answer_format` | ok | **0.282** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.257, ci_upper=0.308, type_comparison_query_n=123, type_comparison_query_value=0.335, type_comparison_query_ci_lower=0.292, type_comparison_query_ci_upper=0.377, type_inference_query_n=103, type_inference_query_value=0.255, type_inference_query_ci_lower=0.219, type_inference_query_ci_upper=0.291, type_temporal_query_n=78, type_temporal_query_value=0.234, type_temporal_query_ci_lower=0.182, type_temporal_query_ci_upper=0.287 |



| `paper_map_at_10__hybrid_graph_v2` | ok | **0.269** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.243, ci_upper=0.294, type_comparison_query_n=123, type_comparison_query_value=0.320, type_comparison_query_ci_lower=0.277, type_comparison_query_ci_upper=0.364, type_inference_query_n=103, type_inference_query_value=0.249, type_inference_query_ci_lower=0.214, type_inference_query_ci_upper=0.285, type_temporal_query_n=78, type_temporal_query_value=0.213, type_temporal_query_ci_lower=0.165, type_temporal_query_ci_upper=0.262 |



| `paper_map_at_10__hybrid_all` | ok | **0.406** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.380, ci_upper=0.432, type_comparison_query_n=123, type_comparison_query_value=0.497, type_comparison_query_ci_lower=0.455, type_comparison_query_ci_upper=0.538, type_inference_query_n=103, type_inference_query_value=0.348, type_inference_query_ci_lower=0.311, type_inference_query_ci_upper=0.384, type_temporal_query_n=78, type_temporal_query_value=0.340, type_temporal_query_ci_lower=0.288, type_temporal_query_ci_upper=0.392 |



| `paper_map_at_10_delta__hybrid_graph` | ok | **-0.019** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.031, ci_upper=-0.007, n_pairs=304, mean_x=0.264, mean_hybrid=0.282, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.019, type_comparison_query_ci_lower=-0.042, type_comparison_query_ci_upper=0.004, type_inference_query_n_pairs=103, type_inference_query_delta=-0.015, type_inference_query_ci_lower=-0.028, type_inference_query_ci_upper=-0.003, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.023, type_temporal_query_ci_lower=-0.048, type_temporal_query_ci_upper=-0.000 |



| `paper_map_at_10_delta__hybrid_rerank` | ok | **0.124** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.101, ci_upper=0.147, n_pairs=304, mean_x=0.406, mean_hybrid=0.282, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.160, type_comparison_query_ci_lower=0.121, type_comparison_query_ci_upper=0.202, type_inference_query_n_pairs=103, type_inference_query_delta=0.092, type_inference_query_ci_lower=0.060, type_inference_query_ci_upper=0.125, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.107, type_temporal_query_ci_lower=0.066, type_temporal_query_ci_upper=0.150 |



| `paper_map_at_10_delta__hybrid_metadata` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.000, ci_upper=0.001, n_pairs=304, mean_x=0.282, mean_hybrid=0.282, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.000, type_comparison_query_ci_lower=-0.001, type_comparison_query_ci_upper=0.001, type_inference_query_n_pairs=103, type_inference_query_delta=-0.000, type_inference_query_ci_lower=-0.001, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.001, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.002 |



| `paper_map_at_10_delta__hybrid_answer_format` | ok | **-0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.001, ci_upper=0.000, n_pairs=304, mean_x=0.282, mean_hybrid=0.282, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.001, type_comparison_query_ci_lower=-0.003, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.000, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.001 |



| `paper_map_at_10_delta__hybrid_graph_v2` | ok | **-0.014** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.025, ci_upper=-0.003, n_pairs=304, mean_x=0.269, mean_hybrid=0.282, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.017, type_comparison_query_ci_lower=-0.038, type_comparison_query_ci_upper=0.005, type_inference_query_n_pairs=103, type_inference_query_delta=-0.005, type_inference_query_ci_lower=-0.015, type_inference_query_ci_upper=0.005, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.021, type_temporal_query_ci_lower=-0.041, type_temporal_query_ci_upper=-0.003 |



| `paper_map_at_10_delta__hybrid_all` | ok | **0.123** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.101, ci_upper=0.147, n_pairs=304, mean_x=0.406, mean_hybrid=0.282, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.160, type_comparison_query_ci_lower=0.121, type_comparison_query_ci_upper=0.201, type_inference_query_n_pairs=103, type_inference_query_delta=0.093, type_inference_query_ci_lower=0.061, type_inference_query_ci_upper=0.126, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.106, type_temporal_query_ci_lower=0.065, type_temporal_query_ci_upper=0.149 |



| `answer_usable_p4__hybrid` | ok | **0.572** | 304 | n_excluded=4, n_unscorable=0, usable_blank_answer_count=0, successes=174, ci_lower=0.516, ci_upper=0.627, type_comparison_query_n=123, type_comparison_query_value=0.455, type_comparison_query_ci_lower=0.370, type_comparison_query_ci_upper=0.543, type_inference_query_n=103, type_inference_query_value=0.961, type_inference_query_ci_lower=0.904, type_inference_query_ci_upper=0.985, type_temporal_query_n=78, type_temporal_query_value=0.244, type_temporal_query_ci_lower=0.162, type_temporal_query_ci_upper=0.349, type_comparison_query_constant_yes_baseline=0.634, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_p4__hybrid_graph` | ok | **0.566** | 304 | n_excluded=4, n_unscorable=0, usable_blank_answer_count=0, successes=172, ci_lower=0.510, ci_upper=0.620, type_comparison_query_n=123, type_comparison_query_value=0.463, type_comparison_query_ci_lower=0.378, type_comparison_query_ci_upper=0.551, type_inference_query_n=103, type_inference_query_value=0.961, type_inference_query_ci_lower=0.904, type_inference_query_ci_upper=0.985, type_temporal_query_n=78, type_temporal_query_value=0.205, type_temporal_query_ci_lower=0.130, type_temporal_query_ci_upper=0.308, type_comparison_query_constant_yes_baseline=0.634, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_p4__hybrid_rerank` | ok | **0.651** | 304 | n_excluded=4, n_unscorable=0, usable_blank_answer_count=0, successes=198, ci_lower=0.596, ci_upper=0.703, type_comparison_query_n=123, type_comparison_query_value=0.545, type_comparison_query_ci_lower=0.457, type_comparison_query_ci_upper=0.630, type_inference_query_n=103, type_inference_query_value=0.981, type_inference_query_ci_lower=0.932, type_inference_query_ci_upper=0.995, type_temporal_query_n=78, type_temporal_query_value=0.385, type_temporal_query_ci_lower=0.284, type_temporal_query_ci_upper=0.496, type_comparison_query_constant_yes_baseline=0.634, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_p4__hybrid_metadata` | ok | **0.635** | 304 | n_excluded=4, n_unscorable=0, usable_blank_answer_count=0, successes=193, ci_lower=0.579, ci_upper=0.687, type_comparison_query_n=123, type_comparison_query_value=0.561, type_comparison_query_ci_lower=0.473, type_comparison_query_ci_upper=0.646, type_inference_query_n=103, type_inference_query_value=0.981, type_inference_query_ci_lower=0.932, type_inference_query_ci_upper=0.995, type_temporal_query_n=78, type_temporal_query_value=0.295, type_temporal_query_ci_lower=0.205, type_temporal_query_ci_upper=0.404, type_comparison_query_constant_yes_baseline=0.634, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_p4__hybrid_answer_format` | ok | **0.530** | 304 | n_excluded=4, n_unscorable=0, usable_blank_answer_count=0, successes=161, ci_lower=0.473, ci_upper=0.585, type_comparison_query_n=123, type_comparison_query_value=0.439, type_comparison_query_ci_lower=0.354, type_comparison_query_ci_upper=0.527, type_inference_query_n=103, type_inference_query_value=0.893, type_inference_query_ci_lower=0.819, type_inference_query_ci_upper=0.939, type_temporal_query_n=78, type_temporal_query_value=0.192, type_temporal_query_ci_lower=0.120, type_temporal_query_ci_upper=0.293, type_comparison_query_constant_yes_baseline=0.634, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_p4__hybrid_graph_v2` | ok | **0.553** | 304 | n_excluded=4, n_unscorable=0, usable_blank_answer_count=0, successes=168, ci_lower=0.496, ci_upper=0.608, type_comparison_query_n=123, type_comparison_query_value=0.439, type_comparison_query_ci_lower=0.354, type_comparison_query_ci_upper=0.527, type_inference_query_n=103, type_inference_query_value=0.942, type_inference_query_ci_lower=0.879, type_inference_query_ci_upper=0.973, type_temporal_query_n=78, type_temporal_query_value=0.218, type_temporal_query_ci_lower=0.141, type_temporal_query_ci_upper=0.322, type_comparison_query_constant_yes_baseline=0.634, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_p4__hybrid_all` | ok | **0.743** | 304 | n_excluded=4, n_unscorable=0, usable_blank_answer_count=0, successes=226, ci_lower=0.692, ci_upper=0.789, type_comparison_query_n=123, type_comparison_query_value=0.707, type_comparison_query_ci_lower=0.622, type_comparison_query_ci_upper=0.780, type_inference_query_n=103, type_inference_query_value=0.942, type_inference_query_ci_lower=0.879, type_inference_query_ci_upper=0.973, type_temporal_query_n=78, type_temporal_query_value=0.538, type_temporal_query_ci_lower=0.429, type_temporal_query_ci_upper=0.645, type_comparison_query_constant_yes_baseline=0.634, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `abstention_rate_g__hybrid` | ok | **0.388** | 304 | n_excluded=4, n_unscorable=0, successes=118, ci_lower=0.335, ci_upper=0.444, type_comparison_query_n=123, type_comparison_query_value=0.472, type_comparison_query_ci_lower=0.386, type_comparison_query_ci_upper=0.559, type_inference_query_n=103, type_inference_query_value=0.039, type_inference_query_ci_lower=0.015, type_inference_query_ci_upper=0.096, type_temporal_query_n=78, type_temporal_query_value=0.718, type_temporal_query_ci_lower=0.610, type_temporal_query_ci_upper=0.806 |



| `abstention_rate_g__hybrid_graph` | ok | **0.401** | 304 | n_excluded=4, n_unscorable=0, successes=122, ci_lower=0.348, ci_upper=0.457, type_comparison_query_n=123, type_comparison_query_value=0.472, type_comparison_query_ci_lower=0.386, type_comparison_query_ci_upper=0.559, type_inference_query_n=103, type_inference_query_value=0.039, type_inference_query_ci_lower=0.015, type_inference_query_ci_upper=0.096, type_temporal_query_n=78, type_temporal_query_value=0.769, type_temporal_query_ci_lower=0.664, type_temporal_query_ci_upper=0.849 |



| `abstention_rate_g__hybrid_rerank` | ok | **0.266** | 304 | n_excluded=4, n_unscorable=0, successes=81, ci_lower=0.220, ci_upper=0.319, type_comparison_query_n=123, type_comparison_query_value=0.317, type_comparison_query_ci_lower=0.241, type_comparison_query_ci_upper=0.404, type_inference_query_n=103, type_inference_query_value=0.019, type_inference_query_ci_lower=0.005, type_inference_query_ci_upper=0.068, type_temporal_query_n=78, type_temporal_query_value=0.513, type_temporal_query_ci_lower=0.404, type_temporal_query_ci_upper=0.621 |



| `abstention_rate_g__hybrid_metadata` | ok | **0.319** | 304 | n_excluded=4, n_unscorable=0, successes=97, ci_lower=0.269, ci_upper=0.373, type_comparison_query_n=123, type_comparison_query_value=0.398, type_comparison_query_ci_lower=0.316, type_comparison_query_ci_upper=0.487, type_inference_query_n=103, type_inference_query_value=0.019, type_inference_query_ci_lower=0.005, type_inference_query_ci_upper=0.068, type_temporal_query_n=78, type_temporal_query_value=0.590, type_temporal_query_ci_lower=0.479, type_temporal_query_ci_upper=0.692 |



| `abstention_rate_g__hybrid_answer_format` | ok | **0.424** | 304 | n_excluded=4, n_unscorable=0, successes=129, ci_lower=0.370, ci_upper=0.481, type_comparison_query_n=123, type_comparison_query_value=0.463, type_comparison_query_ci_lower=0.378, type_comparison_query_ci_upper=0.551, type_inference_query_n=103, type_inference_query_value=0.107, type_inference_query_ci_lower=0.061, type_inference_query_ci_upper=0.181, type_temporal_query_n=78, type_temporal_query_value=0.782, type_temporal_query_ci_lower=0.678, type_temporal_query_ci_upper=0.859 |



| `abstention_rate_g__hybrid_graph_v2` | ok | **0.411** | 304 | n_excluded=4, n_unscorable=0, successes=125, ci_lower=0.357, ci_upper=0.467, type_comparison_query_n=123, type_comparison_query_value=0.488, type_comparison_query_ci_lower=0.401, type_comparison_query_ci_upper=0.575, type_inference_query_n=103, type_inference_query_value=0.058, type_inference_query_ci_lower=0.027, type_inference_query_ci_upper=0.121, type_temporal_query_n=78, type_temporal_query_value=0.756, type_temporal_query_ci_lower=0.651, type_temporal_query_ci_upper=0.838 |



| `abstention_rate_g__hybrid_all` | ok | **0.161** | 304 | n_excluded=4, n_unscorable=0, successes=49, ci_lower=0.124, ci_upper=0.207, type_comparison_query_n=123, type_comparison_query_value=0.130, type_comparison_query_ci_lower=0.082, type_comparison_query_ci_upper=0.201, type_inference_query_n=103, type_inference_query_value=0.058, type_inference_query_ci_lower=0.027, type_inference_query_ci_upper=0.121, type_temporal_query_n=78, type_temporal_query_value=0.346, type_temporal_query_ci_lower=0.250, type_temporal_query_ci_upper=0.457 |



| `abstention_rate_g_delta__hybrid_graph` | ok | **0.013** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.023, ci_upper=0.049, n_pairs=304, mean_x=0.401, mean_hybrid=0.388, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=-0.081, type_comparison_query_ci_upper=0.073, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=-0.029, type_inference_query_ci_upper=0.029, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.051, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.115 |



| `abstention_rate_g_delta__hybrid_rerank` | ok | **-0.122** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.168, ci_upper=-0.076, n_pairs=304, mean_x=0.266, mean_hybrid=0.388, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.154, type_comparison_query_ci_lower=-0.244, type_comparison_query_ci_upper=-0.065, type_inference_query_n_pairs=103, type_inference_query_delta=-0.019, type_inference_query_ci_lower=-0.049, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.205, type_temporal_query_ci_lower=-0.308, type_temporal_query_ci_upper=-0.103 |



| `abstention_rate_g_delta__hybrid_metadata` | ok | **-0.069** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.112, ci_upper=-0.026, n_pairs=304, mean_x=0.319, mean_hybrid=0.388, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.073, type_comparison_query_ci_lower=-0.154, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=-0.019, type_inference_query_ci_lower=-0.049, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.128, type_temporal_query_ci_lower=-0.231, type_temporal_query_ci_upper=-0.026 |



| `abstention_rate_g_delta__hybrid_answer_format` | ok | **0.036** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.007, ci_upper=0.079, n_pairs=304, mean_x=0.424, mean_hybrid=0.388, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.008, type_comparison_query_ci_lower=-0.089, type_comparison_query_ci_upper=0.073, type_inference_query_n_pairs=103, type_inference_query_delta=0.068, type_inference_query_ci_lower=0.019, type_inference_query_ci_upper=0.126, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.064, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.141 |



| `abstention_rate_g_delta__hybrid_graph_v2` | ok | **0.023** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.016, ci_upper=0.062, n_pairs=304, mean_x=0.411, mean_hybrid=0.388, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.016, type_comparison_query_ci_lower=-0.057, type_comparison_query_ci_upper=0.089, type_inference_query_n_pairs=103, type_inference_query_delta=0.019, type_inference_query_ci_lower=-0.019, type_inference_query_ci_upper=0.058, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.038, type_temporal_query_ci_lower=-0.038, type_temporal_query_ci_upper=0.115 |



| `abstention_rate_g_delta__hybrid_all` | ok | **-0.227** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.286, ci_upper=-0.168, n_pairs=304, mean_x=0.161, mean_hybrid=0.388, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.341, type_comparison_query_ci_lower=-0.439, type_comparison_query_ci_upper=-0.244, type_inference_query_n_pairs=103, type_inference_query_delta=0.019, type_inference_query_ci_lower=-0.029, type_inference_query_ci_upper=0.078, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.372, type_temporal_query_ci_lower=-0.500, type_temporal_query_ci_upper=-0.231 |



| `final_answer_em__hybrid` | ok | **0.559** | 304 | n_excluded=4, n_unscorable=0, successes=170, ci_lower=0.503, ci_upper=0.614, type_comparison_query_n=123, type_comparison_query_value=0.439, type_comparison_query_ci_lower=0.354, type_comparison_query_ci_upper=0.527, type_inference_query_n=103, type_inference_query_value=0.951, type_inference_query_ci_lower=0.891, type_inference_query_ci_upper=0.979, type_temporal_query_n=78, type_temporal_query_value=0.231, type_temporal_query_ci_lower=0.151, type_temporal_query_ci_upper=0.336 |



| `final_answer_em__hybrid_graph` | ok | **0.553** | 304 | n_excluded=4, n_unscorable=0, successes=168, ci_lower=0.496, ci_upper=0.608, type_comparison_query_n=123, type_comparison_query_value=0.447, type_comparison_query_ci_lower=0.362, type_comparison_query_ci_upper=0.535, type_inference_query_n=103, type_inference_query_value=0.951, type_inference_query_ci_lower=0.891, type_inference_query_ci_upper=0.979, type_temporal_query_n=78, type_temporal_query_value=0.192, type_temporal_query_ci_lower=0.120, type_temporal_query_ci_upper=0.293 |



| `final_answer_em__hybrid_rerank` | ok | **0.635** | 304 | n_excluded=4, n_unscorable=0, successes=193, ci_lower=0.579, ci_upper=0.687, type_comparison_query_n=123, type_comparison_query_value=0.520, type_comparison_query_ci_lower=0.433, type_comparison_query_ci_upper=0.607, type_inference_query_n=103, type_inference_query_value=0.971, type_inference_query_ci_lower=0.918, type_inference_query_ci_upper=0.990, type_temporal_query_n=78, type_temporal_query_value=0.372, type_temporal_query_ci_lower=0.273, type_temporal_query_ci_upper=0.483 |



| `final_answer_em__hybrid_metadata` | ok | **0.622** | 304 | n_excluded=4, n_unscorable=0, successes=189, ci_lower=0.566, ci_upper=0.674, type_comparison_query_n=123, type_comparison_query_value=0.537, type_comparison_query_ci_lower=0.449, type_comparison_query_ci_upper=0.622, type_inference_query_n=103, type_inference_query_value=0.971, type_inference_query_ci_lower=0.918, type_inference_query_ci_upper=0.990, type_temporal_query_n=78, type_temporal_query_value=0.295, type_temporal_query_ci_lower=0.205, type_temporal_query_ci_upper=0.404 |



| `final_answer_em__hybrid_answer_format` | ok | **0.530** | 304 | n_excluded=4, n_unscorable=0, successes=161, ci_lower=0.473, ci_upper=0.585, type_comparison_query_n=123, type_comparison_query_value=0.439, type_comparison_query_ci_lower=0.354, type_comparison_query_ci_upper=0.527, type_inference_query_n=103, type_inference_query_value=0.893, type_inference_query_ci_lower=0.819, type_inference_query_ci_upper=0.939, type_temporal_query_n=78, type_temporal_query_value=0.192, type_temporal_query_ci_lower=0.120, type_temporal_query_ci_upper=0.293 |



| `final_answer_em__hybrid_graph_v2` | ok | **0.536** | 304 | n_excluded=4, n_unscorable=0, successes=163, ci_lower=0.480, ci_upper=0.591, type_comparison_query_n=123, type_comparison_query_value=0.415, type_comparison_query_ci_lower=0.331, type_comparison_query_ci_upper=0.503, type_inference_query_n=103, type_inference_query_value=0.932, type_inference_query_ci_lower=0.866, type_inference_query_ci_upper=0.967, type_temporal_query_n=78, type_temporal_query_value=0.205, type_temporal_query_ci_lower=0.130, type_temporal_query_ci_upper=0.308 |



| `final_answer_em__hybrid_all` | ok | **0.737** | 304 | n_excluded=4, n_unscorable=0, successes=224, ci_lower=0.685, ci_upper=0.783, type_comparison_query_n=123, type_comparison_query_value=0.699, type_comparison_query_ci_lower=0.613, type_comparison_query_ci_upper=0.773, type_inference_query_n=103, type_inference_query_value=0.932, type_inference_query_ci_lower=0.866, type_inference_query_ci_upper=0.967, type_temporal_query_n=78, type_temporal_query_value=0.538, type_temporal_query_ci_lower=0.429, type_temporal_query_ci_upper=0.645 |



| `final_answer_em_delta__hybrid_graph` | ok | **-0.007** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.039, ci_upper=0.030, n_pairs=304, mean_x=0.553, mean_hybrid=0.559, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.008, type_comparison_query_ci_lower=-0.065, type_comparison_query_ci_upper=0.081, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=-0.029, type_inference_query_ci_upper=0.029, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.038, type_temporal_query_ci_lower=-0.090, type_temporal_query_ci_upper=0.013 |



| `final_answer_em_delta__hybrid_rerank` | ok | **0.076** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.030, ci_upper=0.122, n_pairs=304, mean_x=0.635, mean_hybrid=0.559, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.081, type_comparison_query_ci_lower=-0.008, type_comparison_query_ci_upper=0.179, type_inference_query_n_pairs=103, type_inference_query_delta=0.019, type_inference_query_ci_lower=-0.019, type_inference_query_ci_upper=0.058, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.141, type_temporal_query_ci_lower=0.051, type_temporal_query_ci_upper=0.231 |



| `final_answer_em_delta__hybrid_metadata` | ok | **0.062** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.020, ci_upper=0.105, n_pairs=304, mean_x=0.622, mean_hybrid=0.559, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.098, type_comparison_query_ci_lower=0.024, type_comparison_query_ci_upper=0.171, type_inference_query_n_pairs=103, type_inference_query_delta=0.019, type_inference_query_ci_lower=-0.019, type_inference_query_ci_upper=0.058, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.064, type_temporal_query_ci_lower=-0.026, type_temporal_query_ci_upper=0.154 |



| `final_answer_em_delta__hybrid_answer_format` | ok | **-0.030** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.069, ci_upper=0.010, n_pairs=304, mean_x=0.530, mean_hybrid=0.559, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=-0.073, type_comparison_query_ci_upper=0.073, type_inference_query_n_pairs=103, type_inference_query_delta=-0.058, type_inference_query_ci_lower=-0.117, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.038, type_temporal_query_ci_lower=-0.103, type_temporal_query_ci_upper=0.026 |



| `final_answer_em_delta__hybrid_graph_v2` | ok | **-0.023** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.062, ci_upper=0.016, n_pairs=304, mean_x=0.536, mean_hybrid=0.559, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.024, type_comparison_query_ci_lower=-0.098, type_comparison_query_ci_upper=0.049, type_inference_query_n_pairs=103, type_inference_query_delta=-0.019, type_inference_query_ci_lower=-0.058, type_inference_query_ci_upper=0.019, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.026, type_temporal_query_ci_lower=-0.103, type_temporal_query_ci_upper=0.051 |



| `final_answer_em_delta__hybrid_all` | ok | **0.178** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.122, ci_upper=0.234, n_pairs=304, mean_x=0.737, mean_hybrid=0.559, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.260, type_comparison_query_ci_lower=0.171, type_comparison_query_ci_upper=0.358, type_inference_query_n_pairs=103, type_inference_query_delta=-0.019, type_inference_query_ci_lower=-0.078, type_inference_query_ci_upper=0.039, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.308, type_temporal_query_ci_lower=0.179, type_temporal_query_ci_upper=0.436 |



| `gold_containment__hybrid` | ok | **0.681** | 304 | n_excluded=4, n_unscorable=0, successes=207, ci_lower=0.627, ci_upper=0.731, type_comparison_query_n=123, type_comparison_query_value=0.593, type_comparison_query_ci_lower=0.505, type_comparison_query_ci_upper=0.676, type_inference_query_n=103, type_inference_query_value=0.990, type_inference_query_ci_lower=0.947, type_inference_query_ci_upper=0.998, type_temporal_query_n=78, type_temporal_query_value=0.410, type_temporal_query_ci_lower=0.308, type_temporal_query_ci_upper=0.521 |



| `gold_containment__hybrid_graph` | ok | **0.655** | 304 | n_excluded=4, n_unscorable=0, successes=199, ci_lower=0.600, ci_upper=0.706, type_comparison_query_n=123, type_comparison_query_value=0.569, type_comparison_query_ci_lower=0.481, type_comparison_query_ci_upper=0.653, type_inference_query_n=103, type_inference_query_value=0.981, type_inference_query_ci_lower=0.932, type_inference_query_ci_upper=0.995, type_temporal_query_n=78, type_temporal_query_value=0.359, type_temporal_query_ci_lower=0.261, type_temporal_query_ci_upper=0.470 |



| `gold_containment__hybrid_rerank` | ok | **0.753** | 304 | n_excluded=4, n_unscorable=0, successes=229, ci_lower=0.702, ci_upper=0.798, type_comparison_query_n=123, type_comparison_query_value=0.667, type_comparison_query_ci_lower=0.579, type_comparison_query_ci_upper=0.744, type_inference_query_n=103, type_inference_query_value=1, type_inference_query_ci_lower=0.964, type_inference_query_ci_upper=1, type_temporal_query_n=78, type_temporal_query_value=0.564, type_temporal_query_ci_lower=0.454, type_temporal_query_ci_upper=0.669 |



| `gold_containment__hybrid_metadata` | ok | **0.737** | 304 | n_excluded=4, n_unscorable=0, successes=224, ci_lower=0.685, ci_upper=0.783, type_comparison_query_n=123, type_comparison_query_value=0.667, type_comparison_query_ci_lower=0.579, type_comparison_query_ci_upper=0.744, type_inference_query_n=103, type_inference_query_value=0.990, type_inference_query_ci_lower=0.947, type_inference_query_ci_upper=0.998, type_temporal_query_n=78, type_temporal_query_value=0.513, type_temporal_query_ci_lower=0.404, type_temporal_query_ci_upper=0.621 |



| `gold_containment__hybrid_answer_format` | ok | **0.618** | 304 | n_excluded=4, n_unscorable=0, successes=188, ci_lower=0.563, ci_upper=0.671, type_comparison_query_n=123, type_comparison_query_value=0.537, type_comparison_query_ci_lower=0.449, type_comparison_query_ci_upper=0.622, type_inference_query_n=103, type_inference_query_value=0.971, type_inference_query_ci_lower=0.918, type_inference_query_ci_upper=0.990, type_temporal_query_n=78, type_temporal_query_value=0.282, type_temporal_query_ci_lower=0.194, type_temporal_query_ci_upper=0.390 |



| `gold_containment__hybrid_graph_v2` | ok | **0.664** | 304 | n_excluded=4, n_unscorable=0, successes=202, ci_lower=0.610, ci_upper=0.715, type_comparison_query_n=123, type_comparison_query_value=0.577, type_comparison_query_ci_lower=0.489, type_comparison_query_ci_upper=0.661, type_inference_query_n=103, type_inference_query_value=0.990, type_inference_query_ci_lower=0.947, type_inference_query_ci_upper=0.998, type_temporal_query_n=78, type_temporal_query_value=0.372, type_temporal_query_ci_lower=0.273, type_temporal_query_ci_upper=0.483 |



| `gold_containment__hybrid_all` | ok | **0.812** | 304 | n_excluded=4, n_unscorable=0, successes=247, ci_lower=0.765, ci_upper=0.852, type_comparison_query_n=123, type_comparison_query_value=0.756, type_comparison_query_ci_lower=0.673, type_comparison_query_ci_upper=0.823, type_inference_query_n=103, type_inference_query_value=1, type_inference_query_ci_lower=0.964, type_inference_query_ci_upper=1, type_temporal_query_n=78, type_temporal_query_value=0.654, type_temporal_query_ci_lower=0.543, type_temporal_query_ci_upper=0.750 |



| `gold_containment_delta__hybrid_graph` | ok | **-0.026** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.062, ci_upper=0.010, n_pairs=304, mean_x=0.655, mean_hybrid=0.681, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.024, type_comparison_query_ci_lower=-0.098, type_comparison_query_ci_upper=0.049, type_inference_query_n_pairs=103, type_inference_query_delta=-0.010, type_inference_query_ci_lower=-0.029, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.051, type_temporal_query_ci_lower=-0.128, type_temporal_query_ci_upper=0.026 |



| `gold_containment_delta__hybrid_rerank` | ok | **0.072** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.023, ci_upper=0.122, n_pairs=304, mean_x=0.753, mean_hybrid=0.681, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.073, type_comparison_query_ci_lower=-0.024, type_comparison_query_ci_upper=0.171, type_inference_query_n_pairs=103, type_inference_query_delta=0.010, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.029, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.154, type_temporal_query_ci_lower=0.051, type_temporal_query_ci_upper=0.256 |



| `gold_containment_delta__hybrid_metadata` | ok | **0.056** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.010, ci_upper=0.102, n_pairs=304, mean_x=0.737, mean_hybrid=0.681, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.073, type_comparison_query_ci_lower=-0.008, type_comparison_query_ci_upper=0.154, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.103, type_temporal_query_ci_lower=-0.013, type_temporal_query_ci_upper=0.218 |



| `gold_containment_delta__hybrid_answer_format` | ok | **-0.062** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.102, ci_upper=-0.023, n_pairs=304, mean_x=0.618, mean_hybrid=0.681, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.057, type_comparison_query_ci_lower=-0.138, type_comparison_query_ci_upper=0.016, type_inference_query_n_pairs=103, type_inference_query_delta=-0.019, type_inference_query_ci_lower=-0.049, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.128, type_temporal_query_ci_lower=-0.218, type_temporal_query_ci_upper=-0.038 |



| `gold_containment_delta__hybrid_graph_v2` | ok | **-0.016** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.059, ci_upper=0.023, n_pairs=304, mean_x=0.664, mean_hybrid=0.681, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.016, type_comparison_query_ci_lower=-0.089, type_comparison_query_ci_upper=0.057, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.038, type_temporal_query_ci_lower=-0.141, type_temporal_query_ci_upper=0.064 |



| `gold_containment_delta__hybrid_all` | ok | **0.132** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.079, ci_upper=0.184, n_pairs=304, mean_x=0.812, mean_hybrid=0.681, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.163, type_comparison_query_ci_lower=0.065, type_comparison_query_ci_upper=0.260, type_inference_query_n_pairs=103, type_inference_query_delta=0.010, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.029, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.244, type_temporal_query_ci_lower=0.115, type_temporal_query_ci_upper=0.359 |



| `final_answer_missing_rate__hybrid` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.012, type_comparison_query_n=123, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.030, type_inference_query_n=103, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.036, type_temporal_query_n=78, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.047 |



| `final_answer_missing_rate__hybrid_graph` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.012, type_comparison_query_n=123, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.030, type_inference_query_n=103, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.036, type_temporal_query_n=78, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.047 |



| `final_answer_missing_rate__hybrid_rerank` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.012, type_comparison_query_n=123, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.030, type_inference_query_n=103, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.036, type_temporal_query_n=78, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.047 |



| `final_answer_missing_rate__hybrid_metadata` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.012, type_comparison_query_n=123, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.030, type_inference_query_n=103, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.036, type_temporal_query_n=78, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.047 |



| `final_answer_missing_rate__hybrid_answer_format` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.012, type_comparison_query_n=123, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.030, type_inference_query_n=103, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.036, type_temporal_query_n=78, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.047 |



| `final_answer_missing_rate__hybrid_graph_v2` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.012, type_comparison_query_n=123, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.030, type_inference_query_n=103, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.036, type_temporal_query_n=78, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.047 |



| `final_answer_missing_rate__hybrid_all` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.012, type_comparison_query_n=123, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.030, type_inference_query_n=103, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.036, type_temporal_query_n=78, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.047 |



| `final_answer_missing_rate_delta__hybrid_graph` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=304, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `final_answer_missing_rate_delta__hybrid_rerank` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=304, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `final_answer_missing_rate_delta__hybrid_metadata` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=304, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `final_answer_missing_rate_delta__hybrid_answer_format` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=304, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `final_answer_missing_rate_delta__hybrid_graph_v2` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=304, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `final_answer_missing_rate_delta__hybrid_all` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=304, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `coverage_at_4__hybrid` | ok | **0.363** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.328, ci_upper=0.398, type_comparison_query_n=123, type_comparison_query_value=0.428, type_comparison_query_ci_lower=0.371, type_comparison_query_ci_upper=0.484, type_inference_query_n=103, type_inference_query_value=0.328, type_inference_query_ci_lower=0.281, type_inference_query_ci_upper=0.378, type_temporal_query_n=78, type_temporal_query_value=0.306, type_temporal_query_ci_lower=0.235, type_temporal_query_ci_upper=0.376 |



| `coverage_at_4__hybrid_graph` | ok | **0.353** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.317, ci_upper=0.388, type_comparison_query_n=123, type_comparison_query_value=0.432, type_comparison_query_ci_lower=0.373, type_comparison_query_ci_upper=0.493, type_inference_query_n=103, type_inference_query_value=0.306, type_inference_query_ci_lower=0.261, type_inference_query_ci_upper=0.354, type_temporal_query_n=78, type_temporal_query_value=0.291, type_temporal_query_ci_lower=0.220, type_temporal_query_ci_upper=0.361 |



| `coverage_at_4__hybrid_rerank` | ok | **0.542** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.505, ci_upper=0.578, type_comparison_query_n=123, type_comparison_query_value=0.665, type_comparison_query_ci_lower=0.608, type_comparison_query_ci_upper=0.721, type_inference_query_n=103, type_inference_query_value=0.481, type_inference_query_ci_lower=0.422, type_inference_query_ci_upper=0.538, type_temporal_query_n=78, type_temporal_query_value=0.427, type_temporal_query_ci_lower=0.357, type_temporal_query_ci_upper=0.498 |



| `coverage_at_4__hybrid_metadata` | ok | **0.365** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.330, ci_upper=0.399, type_comparison_query_n=123, type_comparison_query_value=0.428, type_comparison_query_ci_lower=0.371, type_comparison_query_ci_upper=0.484, type_inference_query_n=103, type_inference_query_value=0.328, type_inference_query_ci_lower=0.281, type_inference_query_ci_upper=0.378, type_temporal_query_n=78, type_temporal_query_value=0.312, type_temporal_query_ci_lower=0.239, type_temporal_query_ci_upper=0.385 |



| `coverage_at_4__hybrid_answer_format` | ok | **0.362** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.328, ci_upper=0.396, type_comparison_query_n=123, type_comparison_query_value=0.425, type_comparison_query_ci_lower=0.369, type_comparison_query_ci_upper=0.481, type_inference_query_n=103, type_inference_query_value=0.328, type_inference_query_ci_lower=0.281, type_inference_query_ci_upper=0.378, type_temporal_query_n=78, type_temporal_query_value=0.306, type_temporal_query_ci_lower=0.235, type_temporal_query_ci_upper=0.376 |



| `coverage_at_4__hybrid_graph_v2` | ok | **0.354** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.320, ci_upper=0.389, type_comparison_query_n=123, type_comparison_query_value=0.432, type_comparison_query_ci_lower=0.375, type_comparison_query_ci_upper=0.491, type_inference_query_n=103, type_inference_query_value=0.313, type_inference_query_ci_lower=0.268, type_inference_query_ci_upper=0.361, type_temporal_query_n=78, type_temporal_query_value=0.286, type_temporal_query_ci_lower=0.214, type_temporal_query_ci_upper=0.359 |



| `coverage_at_4__hybrid_all` | ok | **0.541** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.504, ci_upper=0.578, type_comparison_query_n=123, type_comparison_query_value=0.665, type_comparison_query_ci_lower=0.608, type_comparison_query_ci_upper=0.721, type_inference_query_n=103, type_inference_query_value=0.483, type_inference_query_ci_lower=0.424, type_inference_query_ci_upper=0.540, type_temporal_query_n=78, type_temporal_query_value=0.423, type_temporal_query_ci_lower=0.353, type_temporal_query_ci_upper=0.496 |



| `coverage_at_4_delta__hybrid_graph` | ok | **-0.010** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.028, ci_upper=0.008, n_pairs=304, mean_x=0.353, mean_hybrid=0.363, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.004, type_comparison_query_ci_lower=-0.033, type_comparison_query_ci_upper=0.041, type_inference_query_n_pairs=103, type_inference_query_delta=-0.023, type_inference_query_ci_lower=-0.046, type_inference_query_ci_upper=-0.001, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.015, type_temporal_query_ci_lower=-0.041, type_temporal_query_ci_upper=0.009 |



| `coverage_at_4_delta__hybrid_rerank` | ok | **0.179** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.146, ci_upper=0.212, n_pairs=304, mean_x=0.542, mean_hybrid=0.363, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.237, type_comparison_query_ci_lower=0.179, type_comparison_query_ci_upper=0.297, type_inference_query_n_pairs=103, type_inference_query_delta=0.152, type_inference_query_ci_lower=0.102, type_inference_query_ci_upper=0.200, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.122, type_temporal_query_ci_lower=0.066, type_temporal_query_ci_upper=0.177 |



| `coverage_at_4_delta__hybrid_metadata` | ok | **0.002** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0, ci_upper=0.005, n_pairs=304, mean_x=0.365, mean_hybrid=0.363, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.006, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.019 |



| `coverage_at_4_delta__hybrid_answer_format` | ok | **-0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.003, ci_upper=0, n_pairs=304, mean_x=0.362, mean_hybrid=0.363, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.003, type_comparison_query_ci_lower=-0.008, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `coverage_at_4_delta__hybrid_graph_v2` | ok | **-0.008** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.024, ci_upper=0.008, n_pairs=304, mean_x=0.354, mean_hybrid=0.363, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.004, type_comparison_query_ci_lower=-0.027, type_comparison_query_ci_upper=0.038, type_inference_query_n_pairs=103, type_inference_query_delta=-0.015, type_inference_query_ci_lower=-0.036, type_inference_query_ci_upper=0.003, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.019, type_temporal_query_ci_lower=-0.045, type_temporal_query_ci_upper=0.004 |



| `coverage_at_4_delta__hybrid_all` | ok | **0.178** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.146, ci_upper=0.212, n_pairs=304, mean_x=0.541, mean_hybrid=0.363, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.237, type_comparison_query_ci_lower=0.179, type_comparison_query_ci_upper=0.297, type_inference_query_n_pairs=103, type_inference_query_delta=0.155, type_inference_query_ci_lower=0.104, type_inference_query_ci_upper=0.202, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.118, type_temporal_query_ci_lower=0.064, type_temporal_query_ci_upper=0.173 |



| `precision_at_4__hybrid` | ok | **0.220** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.201, ci_upper=0.241, type_comparison_query_n=123, type_comparison_query_value=0.228, type_comparison_query_ci_lower=0.197, type_comparison_query_ci_upper=0.258, type_inference_query_n=103, type_inference_query_value=0.243, type_inference_query_ci_lower=0.211, type_inference_query_ci_upper=0.274, type_temporal_query_n=78, type_temporal_query_value=0.179, type_temporal_query_ci_lower=0.138, type_temporal_query_ci_upper=0.221 |



| `precision_at_4__hybrid_graph` | ok | **0.212** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.192, ci_upper=0.231, type_comparison_query_n=123, type_comparison_query_value=0.228, type_comparison_query_ci_lower=0.197, type_comparison_query_ci_upper=0.258, type_inference_query_n=103, type_inference_query_value=0.226, type_inference_query_ci_lower=0.194, type_inference_query_ci_upper=0.257, type_temporal_query_n=78, type_temporal_query_value=0.170, type_temporal_query_ci_lower=0.131, type_temporal_query_ci_upper=0.208 |



| `precision_at_4__hybrid_rerank` | ok | **0.334** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.312, ci_upper=0.356, type_comparison_query_n=123, type_comparison_query_value=0.356, type_comparison_query_ci_lower=0.325, type_comparison_query_ci_upper=0.386, type_inference_query_n=103, type_inference_query_value=0.367, type_inference_query_ci_lower=0.323, type_inference_query_ci_upper=0.410, type_temporal_query_n=78, type_temporal_query_value=0.256, type_temporal_query_ci_lower=0.218, type_temporal_query_ci_upper=0.295 |



| `precision_at_4__hybrid_metadata` | ok | **0.221** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.201, ci_upper=0.242, type_comparison_query_n=123, type_comparison_query_value=0.228, type_comparison_query_ci_lower=0.197, type_comparison_query_ci_upper=0.258, type_inference_query_n=103, type_inference_query_value=0.243, type_inference_query_ci_lower=0.211, type_inference_query_ci_upper=0.274, type_temporal_query_n=78, type_temporal_query_value=0.183, type_temporal_query_ci_lower=0.141, type_temporal_query_ci_upper=0.224 |



| `precision_at_4__hybrid_answer_format` | ok | **0.220** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.200, ci_upper=0.239, type_comparison_query_n=123, type_comparison_query_value=0.226, type_comparison_query_ci_lower=0.195, type_comparison_query_ci_upper=0.256, type_inference_query_n=103, type_inference_query_value=0.243, type_inference_query_ci_lower=0.211, type_inference_query_ci_upper=0.274, type_temporal_query_n=78, type_temporal_query_value=0.179, type_temporal_query_ci_lower=0.138, type_temporal_query_ci_upper=0.221 |



| `precision_at_4__hybrid_graph_v2` | ok | **0.214** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.194, ci_upper=0.233, type_comparison_query_n=123, type_comparison_query_value=0.228, type_comparison_query_ci_lower=0.199, type_comparison_query_ci_upper=0.258, type_inference_query_n=103, type_inference_query_value=0.233, type_inference_query_ci_lower=0.201, type_inference_query_ci_upper=0.265, type_temporal_query_n=78, type_temporal_query_value=0.167, type_temporal_query_ci_lower=0.128, type_temporal_query_ci_upper=0.208 |



| `precision_at_4__hybrid_all` | ok | **0.334** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.312, ci_upper=0.356, type_comparison_query_n=123, type_comparison_query_value=0.356, type_comparison_query_ci_lower=0.325, type_comparison_query_ci_upper=0.386, type_inference_query_n=103, type_inference_query_value=0.369, type_inference_query_ci_lower=0.325, type_inference_query_ci_upper=0.413, type_temporal_query_n=78, type_temporal_query_value=0.253, type_temporal_query_ci_lower=0.215, type_temporal_query_ci_upper=0.292 |



| `precision_at_4_delta__hybrid_graph` | ok | **-0.008** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.019, ci_upper=0.002, n_pairs=304, mean_x=0.212, mean_hybrid=0.220, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=-0.022, type_comparison_query_ci_upper=0.020, type_inference_query_n_pairs=103, type_inference_query_delta=-0.017, type_inference_query_ci_lower=-0.034, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.010, type_temporal_query_ci_lower=-0.026, type_temporal_query_ci_upper=0.003 |



| `precision_at_4_delta__hybrid_rerank` | ok | **0.113** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.093, ci_upper=0.134, n_pairs=304, mean_x=0.334, mean_hybrid=0.220, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.128, type_comparison_query_ci_lower=0.098, type_comparison_query_ci_upper=0.161, type_inference_query_n_pairs=103, type_inference_query_delta=0.124, type_inference_query_ci_lower=0.085, type_inference_query_ci_upper=0.163, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.077, type_temporal_query_ci_lower=0.042, type_temporal_query_ci_upper=0.112 |



| `precision_at_4_delta__hybrid_metadata` | ok | **0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0, ci_upper=0.002, n_pairs=304, mean_x=0.221, mean_hybrid=0.220, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.003, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.010 |



| `precision_at_4_delta__hybrid_answer_format` | ok | **-0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.002, ci_upper=0, n_pairs=304, mean_x=0.220, mean_hybrid=0.220, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.002, type_comparison_query_ci_lower=-0.006, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=103, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=78, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `precision_at_4_delta__hybrid_graph_v2` | ok | **-0.007** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.016, ci_upper=0.003, n_pairs=304, mean_x=0.214, mean_hybrid=0.220, type_comparison_query_n_pairs=123, type_comparison_query_delta=0, type_comparison_query_ci_lower=-0.018, type_comparison_query_ci_upper=0.018, type_inference_query_n_pairs=103, type_inference_query_delta=-0.010, type_inference_query_ci_lower=-0.024, type_inference_query_ci_upper=0.002, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.013, type_temporal_query_ci_lower=-0.029, type_temporal_query_ci_upper=0 |



| `precision_at_4_delta__hybrid_all` | ok | **0.113** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.093, ci_upper=0.134, n_pairs=304, mean_x=0.334, mean_hybrid=0.220, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.128, type_comparison_query_ci_lower=0.098, type_comparison_query_ci_upper=0.161, type_inference_query_n_pairs=103, type_inference_query_delta=0.126, type_inference_query_ci_lower=0.087, type_inference_query_ci_upper=0.165, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.074, type_temporal_query_ci_lower=0.042, type_temporal_query_ci_upper=0.106 |



| `prompt_tokens_mean__hybrid` | ok | **2262.6** | 304 | n_excluded=4, n_unscorable=0, ci_lower=2247.382, ci_upper=2277.562, type_comparison_query_n=123, type_comparison_query_value=2249.236, type_comparison_query_ci_lower=2223.366, type_comparison_query_ci_upper=2275.512, type_inference_query_n=103, type_inference_query_value=2275.311, type_inference_query_ci_lower=2250.835, type_inference_query_ci_upper=2299.612, type_temporal_query_n=78, type_temporal_query_value=2266.872, type_temporal_query_ci_lower=2239.077, type_temporal_query_ci_upper=2294.603 |



| `prompt_tokens_mean__hybrid_graph` | ok | **2462.1** | 304 | n_excluded=4, n_unscorable=0, ci_lower=2433.132, ci_upper=2490.562, type_comparison_query_n=123, type_comparison_query_value=2471.081, type_comparison_query_ci_lower=2421.407, type_comparison_query_ci_upper=2520.699, type_inference_query_n=103, type_inference_query_value=2420.932, type_inference_query_ci_lower=2377.243, type_inference_query_ci_upper=2466.922, type_temporal_query_n=78, type_temporal_query_value=2502.474, type_temporal_query_ci_lower=2450.205, type_temporal_query_ci_upper=2555 |



| `prompt_tokens_mean__hybrid_rerank` | ok | **2321.4** | 304 | n_excluded=4, n_unscorable=0, ci_lower=2306.789, ci_upper=2335.618, type_comparison_query_n=123, type_comparison_query_value=2309.927, type_comparison_query_ci_lower=2284.146, type_comparison_query_ci_upper=2335.927, type_inference_query_n=103, type_inference_query_value=2326.466, type_inference_query_ci_lower=2305.505, type_inference_query_ci_upper=2346.718, type_temporal_query_n=78, type_temporal_query_value=2332.923, type_temporal_query_ci_lower=2306.282, type_temporal_query_ci_upper=2360.359 |



| `prompt_tokens_mean__hybrid_metadata` | ok | **2734.2** | 304 | n_excluded=4, n_unscorable=0, ci_lower=2719.020, ci_upper=2748.622, type_comparison_query_n=123, type_comparison_query_value=2728.179, type_comparison_query_ci_lower=2703.366, type_comparison_query_ci_upper=2753.244, type_inference_query_n=103, type_inference_query_value=2739.194, type_inference_query_ci_lower=2713.757, type_inference_query_ci_upper=2764.379, type_temporal_query_n=78, type_temporal_query_value=2736.923, type_temporal_query_ci_lower=2710.103, type_temporal_query_ci_upper=2762.936 |



| `prompt_tokens_mean__hybrid_answer_format` | ok | **2352.7** | 304 | n_excluded=4, n_unscorable=0, ci_lower=2337.355, ci_upper=2367.786, type_comparison_query_n=123, type_comparison_query_value=2338.691, type_comparison_query_ci_lower=2312.756, type_comparison_query_ci_upper=2364.992, type_inference_query_n=103, type_inference_query_value=2365.767, type_inference_query_ci_lower=2340.961, type_inference_query_ci_upper=2390.194, type_temporal_query_n=78, type_temporal_query_value=2357.564, type_temporal_query_ci_lower=2329.538, type_temporal_query_ci_upper=2385.333 |



| `prompt_tokens_mean__hybrid_graph_v2` | ok | **2463.5** | 304 | n_excluded=4, n_unscorable=0, ci_lower=2434.582, ci_upper=2491.816, type_comparison_query_n=123, type_comparison_query_value=2465.740, type_comparison_query_ci_lower=2416.016, type_comparison_query_ci_upper=2515.252, type_inference_query_n=103, type_inference_query_value=2433.010, type_inference_query_ci_lower=2389.417, type_inference_query_ci_upper=2478.670, type_temporal_query_n=78, type_temporal_query_value=2500.256, type_temporal_query_ci_lower=2448.756, type_temporal_query_ci_upper=2551.654 |



| `prompt_tokens_mean__hybrid_all` | ok | **3083.9** | 304 | n_excluded=4, n_unscorable=0, ci_lower=3055.891, ci_upper=3111.168, type_comparison_query_n=123, type_comparison_query_value=3107.902, type_comparison_query_ci_lower=3058.984, type_comparison_query_ci_upper=3157.260, type_inference_query_n=103, type_inference_query_value=3027.233, type_inference_query_ci_lower=2987.699, type_inference_query_ci_upper=3069.621, type_temporal_query_n=78, type_temporal_query_value=3120.756, type_temporal_query_ci_lower=3072.154, type_temporal_query_ci_upper=3170.872 |



| `prompt_tokens_delta__hybrid_graph` | ok | **199.5** | 304 | n_excluded=4, n_unscorable=0, ci_lower=175.122, ci_upper=223.632, n_pairs=304, mean_x=2462.145, mean_hybrid=2262.595, type_comparison_query_n_pairs=123, type_comparison_query_delta=221.846, type_comparison_query_ci_lower=181.220, type_comparison_query_ci_upper=262.699, type_inference_query_n_pairs=103, type_inference_query_delta=145.621, type_inference_query_ci_lower=110.864, type_inference_query_ci_upper=182.641, type_temporal_query_n_pairs=78, type_temporal_query_delta=235.603, type_temporal_query_ci_lower=188.179, type_temporal_query_ci_upper=284.692 |



| `prompt_tokens_delta__hybrid_rerank` | ok | **58.8** | 304 | n_excluded=4, n_unscorable=0, ci_lower=47.069, ci_upper=71.046, n_pairs=304, mean_x=2321.431, mean_hybrid=2262.595, type_comparison_query_n_pairs=123, type_comparison_query_delta=60.691, type_comparison_query_ci_lower=40.846, type_comparison_query_ci_upper=80.439, type_inference_query_n_pairs=103, type_inference_query_delta=51.155, type_inference_query_ci_lower=31.602, type_inference_query_ci_upper=70.282, type_temporal_query_n_pairs=78, type_temporal_query_delta=66.051, type_temporal_query_ci_lower=41.590, type_temporal_query_ci_upper=90.397 |



| `prompt_tokens_delta__hybrid_metadata` | ok | **471.6** | 304 | n_excluded=4, n_unscorable=0, ci_lower=466.914, ci_upper=476.224, n_pairs=304, mean_x=2734.155, mean_hybrid=2262.595, type_comparison_query_n_pairs=123, type_comparison_query_delta=478.943, type_comparison_query_ci_lower=470.593, type_comparison_query_ci_upper=487.358, type_inference_query_n_pairs=103, type_inference_query_delta=463.883, type_inference_query_ci_lower=457.971, type_inference_query_ci_upper=470.350, type_temporal_query_n_pairs=78, type_temporal_query_delta=470.051, type_temporal_query_ci_lower=461.218, type_temporal_query_ci_upper=479.538 |



| `prompt_tokens_delta__hybrid_answer_format` | ok | **90.1** | 304 | n_excluded=4, n_unscorable=0, ci_lower=89.046, ci_upper=90.924, n_pairs=304, mean_x=2352.707, mean_hybrid=2262.595, type_comparison_query_n_pairs=123, type_comparison_query_delta=89.455, type_comparison_query_ci_lower=87.211, type_comparison_query_ci_upper=91.049, type_inference_query_n_pairs=103, type_inference_query_delta=90.456, type_inference_query_ci_lower=88.845, type_inference_query_ci_upper=91.524, type_temporal_query_n_pairs=78, type_temporal_query_delta=90.692, type_temporal_query_ci_lower=90.077, type_temporal_query_ci_upper=91 |



| `prompt_tokens_delta__hybrid_graph_v2` | ok | **200.9** | 304 | n_excluded=4, n_unscorable=0, ci_lower=177.385, ci_upper=224.536, n_pairs=304, mean_x=2463.507, mean_hybrid=2262.595, type_comparison_query_n_pairs=123, type_comparison_query_delta=216.504, type_comparison_query_ci_lower=176.081, type_comparison_query_ci_upper=256.959, type_inference_query_n_pairs=103, type_inference_query_delta=157.699, type_inference_query_ci_lower=123.718, type_inference_query_ci_upper=194.165, type_temporal_query_n_pairs=78, type_temporal_query_delta=233.385, type_temporal_query_ci_lower=186.513, type_temporal_query_ci_upper=281.654 |



| `prompt_tokens_delta__hybrid_all` | ok | **821.3** | 304 | n_excluded=4, n_unscorable=0, ci_lower=795.378, ci_upper=847.441, n_pairs=304, mean_x=3083.868, mean_hybrid=2262.595, type_comparison_query_n_pairs=123, type_comparison_query_delta=858.667, type_comparison_query_ci_lower=813.756, type_comparison_query_ci_upper=904.447, type_inference_query_n_pairs=103, type_inference_query_delta=751.922, type_inference_query_ci_lower=714.961, type_inference_query_ci_upper=790.165, type_temporal_query_n_pairs=78, type_temporal_query_delta=853.885, type_temporal_query_ci_lower=803.872, type_temporal_query_ci_upper=906.154 |



| `latency_total_ms_mean__hybrid` | ok | **8505.1** | 304 | n_excluded=4, n_unscorable=0, ci_lower=8284.306, ci_upper=8739.312, type_comparison_query_n=123, type_comparison_query_value=8791.203, type_comparison_query_ci_lower=8399.553, type_comparison_query_ci_upper=9205.447, type_inference_query_n=103, type_inference_query_value=8015.233, type_inference_query_ci_lower=7680.233, type_inference_query_ci_upper=8349.913, type_temporal_query_n=78, type_temporal_query_value=8700.654, type_temporal_query_ci_lower=8274.205, type_temporal_query_ci_upper=9144.308 |



| `latency_total_ms_mean__hybrid_graph` | ok | **8474.7** | 304 | n_excluded=4, n_unscorable=0, ci_lower=8271.191, ci_upper=8687.487, type_comparison_query_n=123, type_comparison_query_value=8610.634, type_comparison_query_ci_lower=8267.789, type_comparison_query_ci_upper=8970.252, type_inference_query_n=103, type_inference_query_value=8368.680, type_inference_query_ci_lower=8021.068, type_inference_query_ci_upper=8721.903, type_temporal_query_n=78, type_temporal_query_value=8400.462, type_temporal_query_ci_lower=8018.897, type_temporal_query_ci_upper=8796.577 |



| `latency_total_ms_mean__hybrid_rerank` | ok | **8802.0** | 304 | n_excluded=4, n_unscorable=0, ci_lower=8569.562, ci_upper=9046.155, type_comparison_query_n=123, type_comparison_query_value=9072.967, type_comparison_query_ci_lower=8671.024, type_comparison_query_ci_upper=9501.976, type_inference_query_n=103, type_inference_query_value=8241.544, type_inference_query_ci_lower=7889.146, type_inference_query_ci_upper=8604.854, type_temporal_query_n=78, type_temporal_query_value=9114.769, type_temporal_query_ci_lower=8665.244, type_temporal_query_ci_upper=9575.410 |



| `latency_total_ms_mean__hybrid_metadata` | ok | **8466.4** | 304 | n_excluded=4, n_unscorable=0, ci_lower=8247.530, ci_upper=8690.638, type_comparison_query_n=123, type_comparison_query_value=8335.398, type_comparison_query_ci_lower=8016.065, type_comparison_query_ci_upper=8661.992, type_inference_query_n=103, type_inference_query_value=8664.058, type_inference_query_ci_lower=8237.058, type_inference_query_ci_upper=9116.039, type_temporal_query_n=78, type_temporal_query_value=8412.064, type_temporal_query_ci_lower=8036.218, type_temporal_query_ci_upper=8790.564 |



| `latency_total_ms_mean__hybrid_answer_format` | ok | **8196.6** | 304 | n_excluded=4, n_unscorable=0, ci_lower=7972.599, ci_upper=8428.891, type_comparison_query_n=123, type_comparison_query_value=8467.431, type_comparison_query_ci_lower=8071.789, type_comparison_query_ci_upper=8874.366, type_inference_query_n=103, type_inference_query_value=8205.466, type_inference_query_ci_lower=7850.961, type_inference_query_ci_upper=8589.767, type_temporal_query_n=78, type_temporal_query_value=7757.859, type_temporal_query_ci_lower=7415.769, type_temporal_query_ci_upper=8107.449 |



| `latency_total_ms_mean__hybrid_graph_v2` | ok | **8668.9** | 304 | n_excluded=4, n_unscorable=0, ci_lower=8435.770, ci_upper=8902.770, type_comparison_query_n=123, type_comparison_query_value=9049.927, type_comparison_query_ci_lower=8654.081, type_comparison_query_ci_upper=9449.114, type_inference_query_n=103, type_inference_query_value=8242.961, type_inference_query_ci_lower=7881.223, type_inference_query_ci_upper=8607.087, type_temporal_query_n=78, type_temporal_query_value=8630.321, type_temporal_query_ci_lower=8179.692, type_temporal_query_ci_upper=9092.577 |



| `latency_total_ms_mean__hybrid_all` | ok | **9202.8** | 304 | n_excluded=4, n_unscorable=0, ci_lower=8915.401, ci_upper=9563.424, type_comparison_query_n=123, type_comparison_query_value=9039.764, type_comparison_query_ci_lower=8703.260, type_comparison_query_ci_upper=9378.333, type_inference_query_n=103, type_inference_query_value=9068.524, type_inference_query_ci_lower=8441.845, type_inference_query_ci_upper=9973.689, type_temporal_query_n=78, type_temporal_query_value=9637.064, type_temporal_query_ci_lower=9200.603, type_temporal_query_ci_upper=10076.397 |



| `latency_total_ms_delta__hybrid_graph` | ok | **-30.3** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-292.941, ci_upper=227.408, n_pairs=304, mean_x=8474.730, mean_hybrid=8505.059, type_comparison_query_n_pairs=123, type_comparison_query_delta=-180.569, type_comparison_query_ci_lower=-645.805, type_comparison_query_ci_upper=289.691, type_inference_query_n_pairs=103, type_inference_query_delta=353.447, type_inference_query_ci_lower=-25.010, type_inference_query_ci_upper=735.398, type_temporal_query_n_pairs=78, type_temporal_query_delta=-300.192, type_temporal_query_ci_lower=-762.333, type_temporal_query_ci_upper=153.910 |



| `latency_total_ms_delta__hybrid_rerank` | ok | **296.9** | 304 | n_excluded=4, n_unscorable=0, ci_lower=18.789, ci_upper=578.957, n_pairs=304, mean_x=8801.993, mean_hybrid=8505.059, type_comparison_query_n_pairs=123, type_comparison_query_delta=281.764, type_comparison_query_ci_lower=-216.520, type_comparison_query_ci_upper=783.260, type_inference_query_n_pairs=103, type_inference_query_delta=226.311, type_inference_query_ci_lower=-173.845, type_inference_query_ci_upper=623.320, type_temporal_query_n_pairs=78, type_temporal_query_delta=414.115, type_temporal_query_ci_lower=-154.038, type_temporal_query_ci_upper=954.769 |



| `latency_total_ms_delta__hybrid_metadata` | ok | **-38.6** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-317.066, ci_upper=242.753, n_pairs=304, mean_x=8466.424, mean_hybrid=8505.059, type_comparison_query_n_pairs=123, type_comparison_query_delta=-455.805, type_comparison_query_ci_lower=-917.065, type_comparison_query_ci_upper=2, type_inference_query_n_pairs=103, type_inference_query_delta=648.825, type_inference_query_ci_lower=152.544, type_inference_query_ci_upper=1175.019, type_temporal_query_n_pairs=78, type_temporal_query_delta=-288.590, type_temporal_query_ci_lower=-754.128, type_temporal_query_ci_upper=149.244 |



| `latency_total_ms_delta__hybrid_answer_format` | ok | **-308.4** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-565.283, ci_upper=-61.036, n_pairs=304, mean_x=8196.612, mean_hybrid=8505.059, type_comparison_query_n_pairs=123, type_comparison_query_delta=-323.772, type_comparison_query_ci_lower=-776.472, type_comparison_query_ci_upper=120.276, type_inference_query_n_pairs=103, type_inference_query_delta=190.233, type_inference_query_ci_lower=-180.398, type_inference_query_ci_upper=567.194, type_temporal_query_n_pairs=78, type_temporal_query_delta=-942.795, type_temporal_query_ci_lower=-1379.628, type_temporal_query_ci_upper=-517.821 |



| `latency_total_ms_delta__hybrid_graph_v2` | ok | **163.8** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-105.020, ci_upper=422.602, n_pairs=304, mean_x=8668.852, mean_hybrid=8505.059, type_comparison_query_n_pairs=123, type_comparison_query_delta=258.724, type_comparison_query_ci_lower=-218.146, type_comparison_query_ci_upper=720.659, type_inference_query_n_pairs=103, type_inference_query_delta=227.728, type_inference_query_ci_lower=-172.971, type_inference_query_ci_upper=637.835, type_temporal_query_n_pairs=78, type_temporal_query_delta=-70.333, type_temporal_query_ci_lower=-521.141, type_temporal_query_ci_upper=382.923 |



| `latency_total_ms_delta__hybrid_all` | ok | **697.7** | 304 | n_excluded=4, n_unscorable=0, ci_lower=370.914, ci_upper=1083.533, n_pairs=304, mean_x=9202.763, mean_hybrid=8505.059, type_comparison_query_n_pairs=123, type_comparison_query_delta=248.561, type_comparison_query_ci_lower=-198.220, type_comparison_query_ci_upper=662.049, type_inference_query_n_pairs=103, type_inference_query_delta=1053.291, type_inference_query_ci_lower=356.097, type_inference_query_ci_upper=2004.893, type_temporal_query_n_pairs=78, type_temporal_query_delta=936.410, type_temporal_query_ci_lower=449.679, type_temporal_query_ci_upper=1401.038 |



| `retrieve_node_ms_mean__hybrid` | ok | **96.118** | 304 | n_excluded=4, n_unscorable=0, ci_lower=94.872, ci_upper=97.444, type_comparison_query_n=123, type_comparison_query_value=92.220, type_comparison_query_ci_lower=90.455, type_comparison_query_ci_upper=94.089, type_inference_query_n=103, type_inference_query_value=101.379, type_inference_query_ci_lower=99.233, type_inference_query_ci_upper=103.660, type_temporal_query_n=78, type_temporal_query_value=95.321, type_temporal_query_ci_lower=93.154, type_temporal_query_ci_upper=97.500 |



| `retrieve_node_ms_mean__hybrid_graph` | ok | **110.161** | 304 | n_excluded=4, n_unscorable=0, ci_lower=107.908, ci_upper=112.451, type_comparison_query_n=123, type_comparison_query_value=106.667, type_comparison_query_ci_lower=103.398, type_comparison_query_ci_upper=110.073, type_inference_query_n=103, type_inference_query_value=114.350, type_inference_query_ci_lower=110.184, type_inference_query_ci_upper=118.563, type_temporal_query_n=78, type_temporal_query_value=110.141, type_temporal_query_ci_lower=106.090, type_temporal_query_ci_upper=114.231 |



| `retrieve_node_ms_mean__hybrid_rerank` | ok | **552.789** | 304 | n_excluded=4, n_unscorable=0, ci_lower=519.984, ci_upper=588.174, type_comparison_query_n=123, type_comparison_query_value=529.512, type_comparison_query_ci_lower=481.496, type_comparison_query_ci_upper=582.439, type_inference_query_n=103, type_inference_query_value=569.757, type_inference_query_ci_lower=514.796, type_inference_query_ci_upper=629.709, type_temporal_query_n=78, type_temporal_query_value=567.090, type_temporal_query_ci_lower=503.436, type_temporal_query_ci_upper=636.628 |



| `retrieve_node_ms_mean__hybrid_metadata` | ok | **96.671** | 304 | n_excluded=4, n_unscorable=0, ci_lower=95.378, ci_upper=98.007, type_comparison_query_n=123, type_comparison_query_value=93.667, type_comparison_query_ci_lower=91.911, type_comparison_query_ci_upper=95.602, type_inference_query_n=103, type_inference_query_value=102.272, type_inference_query_ci_lower=100, type_inference_query_ci_upper=104.631, type_temporal_query_n=78, type_temporal_query_value=94.013, type_temporal_query_ci_lower=91.731, type_temporal_query_ci_upper=96.526 |



| `retrieve_node_ms_mean__hybrid_answer_format` | ok | **95.480** | 304 | n_excluded=4, n_unscorable=0, ci_lower=94.220, ci_upper=96.753, type_comparison_query_n=123, type_comparison_query_value=91.772, type_comparison_query_ci_lower=90.106, type_comparison_query_ci_upper=93.585, type_inference_query_n=103, type_inference_query_value=100.612, type_inference_query_ci_lower=98.621, type_inference_query_ci_upper=102.718, type_temporal_query_n=78, type_temporal_query_value=94.551, type_temporal_query_ci_lower=92.128, type_temporal_query_ci_upper=96.987 |



| `retrieve_node_ms_mean__hybrid_graph_v2` | ok | **110.250** | 304 | n_excluded=4, n_unscorable=0, ci_lower=108.072, ci_upper=112.411, type_comparison_query_n=123, type_comparison_query_value=106.650, type_comparison_query_ci_lower=103.569, type_comparison_query_ci_upper=109.797, type_inference_query_n=103, type_inference_query_value=113.165, type_inference_query_ci_lower=109.175, type_inference_query_ci_upper=117.243, type_temporal_query_n=78, type_temporal_query_value=112.077, type_temporal_query_ci_lower=107.705, type_temporal_query_ci_upper=116.487 |



| `retrieve_node_ms_mean__hybrid_all` | ok | **587.826** | 304 | n_excluded=4, n_unscorable=0, ci_lower=554.648, ci_upper=622.799, type_comparison_query_n=123, type_comparison_query_value=568.943, type_comparison_query_ci_lower=517.415, type_comparison_query_ci_upper=623.268, type_inference_query_n=103, type_inference_query_value=617.893, type_inference_query_ci_lower=558.301, type_inference_query_ci_upper=682.738, type_temporal_query_n=78, type_temporal_query_value=577.897, type_temporal_query_ci_lower=519.192, type_temporal_query_ci_upper=645.269 |



| `retrieve_node_ms_delta__hybrid_graph` | ok | **14.043** | 304 | n_excluded=4, n_unscorable=0, ci_lower=11.822, ci_upper=16.283, n_pairs=304, mean_x=110.161, mean_hybrid=96.118, type_comparison_query_n_pairs=123, type_comparison_query_delta=14.447, type_comparison_query_ci_lower=11.106, type_comparison_query_ci_upper=17.813, type_inference_query_n_pairs=103, type_inference_query_delta=12.971, type_inference_query_ci_lower=8.893, type_inference_query_ci_upper=16.951, type_temporal_query_n_pairs=78, type_temporal_query_delta=14.821, type_temporal_query_ci_lower=10.744, type_temporal_query_ci_upper=18.718 |



| `retrieve_node_ms_delta__hybrid_rerank` | ok | **456.671** | 304 | n_excluded=4, n_unscorable=0, ci_lower=423.836, ci_upper=492.164, n_pairs=304, mean_x=552.789, mean_hybrid=96.118, type_comparison_query_n_pairs=123, type_comparison_query_delta=437.293, type_comparison_query_ci_lower=389.512, type_comparison_query_ci_upper=490.512, type_inference_query_n_pairs=103, type_inference_query_delta=468.379, type_inference_query_ci_lower=413.427, type_inference_query_ci_upper=528.505, type_temporal_query_n_pairs=78, type_temporal_query_delta=471.769, type_temporal_query_ci_lower=407.910, type_temporal_query_ci_upper=541.282 |



| `retrieve_node_ms_delta__hybrid_metadata` | ok | **0.553** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.799, ci_upper=1.911, n_pairs=304, mean_x=96.671, mean_hybrid=96.118, type_comparison_query_n_pairs=123, type_comparison_query_delta=1.447, type_comparison_query_ci_lower=-0.675, type_comparison_query_ci_upper=3.691, type_inference_query_n_pairs=103, type_inference_query_delta=0.893, type_inference_query_ci_lower=-1.583, type_inference_query_ci_upper=3.369, type_temporal_query_n_pairs=78, type_temporal_query_delta=-1.308, type_temporal_query_ci_lower=-3.500, type_temporal_query_ci_upper=0.897 |



| `retrieve_node_ms_delta__hybrid_answer_format` | ok | **-0.638** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-1.947, ci_upper=0.688, n_pairs=304, mean_x=95.480, mean_hybrid=96.118, type_comparison_query_n_pairs=123, type_comparison_query_delta=-0.447, type_comparison_query_ci_lower=-2.520, type_comparison_query_ci_upper=1.642, type_inference_query_n_pairs=103, type_inference_query_delta=-0.767, type_inference_query_ci_lower=-3.029, type_inference_query_ci_upper=1.466, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.769, type_temporal_query_ci_lower=-3.218, type_temporal_query_ci_upper=1.692 |



| `retrieve_node_ms_delta__hybrid_graph_v2` | ok | **14.132** | 304 | n_excluded=4, n_unscorable=0, ci_lower=11.938, ci_upper=16.319, n_pairs=304, mean_x=110.250, mean_hybrid=96.118, type_comparison_query_n_pairs=123, type_comparison_query_delta=14.431, type_comparison_query_ci_lower=11.171, type_comparison_query_ci_upper=17.634, type_inference_query_n_pairs=103, type_inference_query_delta=11.786, type_inference_query_ci_lower=7.796, type_inference_query_ci_upper=15.835, type_temporal_query_n_pairs=78, type_temporal_query_delta=16.756, type_temporal_query_ci_lower=12.449, type_temporal_query_ci_upper=21.103 |



| `retrieve_node_ms_delta__hybrid_all` | ok | **491.707** | 304 | n_excluded=4, n_unscorable=0, ci_lower=458.691, ci_upper=526.970, n_pairs=304, mean_x=587.826, mean_hybrid=96.118, type_comparison_query_n_pairs=123, type_comparison_query_delta=476.724, type_comparison_query_ci_lower=425.163, type_comparison_query_ci_upper=531.228, type_inference_query_n_pairs=103, type_inference_query_delta=516.515, type_inference_query_ci_lower=456.699, type_inference_query_ci_upper=581.563, type_temporal_query_n_pairs=78, type_temporal_query_delta=482.577, type_temporal_query_ci_lower=423.846, type_temporal_query_ci_upper=549.231 |



| `spend_usd_mean__hybrid` | ok | **0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.001, ci_upper=0.001, type_comparison_query_n=123, type_comparison_query_value=0.001, type_comparison_query_ci_lower=0.001, type_comparison_query_ci_upper=0.001, type_inference_query_n=103, type_inference_query_value=0.001, type_inference_query_ci_lower=0.001, type_inference_query_ci_upper=0.001, type_temporal_query_n=78, type_temporal_query_value=0.001, type_temporal_query_ci_lower=0.001, type_temporal_query_ci_upper=0.001 |



| `spend_usd_mean__hybrid_graph` | ok | **0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.001, ci_upper=0.001, type_comparison_query_n=123, type_comparison_query_value=0.001, type_comparison_query_ci_lower=0.001, type_comparison_query_ci_upper=0.001, type_inference_query_n=103, type_inference_query_value=0.001, type_inference_query_ci_lower=0.001, type_inference_query_ci_upper=0.001, type_temporal_query_n=78, type_temporal_query_value=0.001, type_temporal_query_ci_lower=0.001, type_temporal_query_ci_upper=0.001 |



| `spend_usd_mean__hybrid_rerank` | ok | **0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.001, ci_upper=0.001, type_comparison_query_n=123, type_comparison_query_value=0.001, type_comparison_query_ci_lower=0.001, type_comparison_query_ci_upper=0.001, type_inference_query_n=103, type_inference_query_value=0.001, type_inference_query_ci_lower=0.001, type_inference_query_ci_upper=0.001, type_temporal_query_n=78, type_temporal_query_value=0.001, type_temporal_query_ci_lower=0.001, type_temporal_query_ci_upper=0.001 |



| `spend_usd_mean__hybrid_metadata` | ok | **0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.001, ci_upper=0.001, type_comparison_query_n=123, type_comparison_query_value=0.001, type_comparison_query_ci_lower=0.001, type_comparison_query_ci_upper=0.001, type_inference_query_n=103, type_inference_query_value=0.001, type_inference_query_ci_lower=0.001, type_inference_query_ci_upper=0.001, type_temporal_query_n=78, type_temporal_query_value=0.001, type_temporal_query_ci_lower=0.001, type_temporal_query_ci_upper=0.001 |



| `spend_usd_mean__hybrid_answer_format` | ok | **0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.001, ci_upper=0.001, type_comparison_query_n=123, type_comparison_query_value=0.001, type_comparison_query_ci_lower=0.001, type_comparison_query_ci_upper=0.001, type_inference_query_n=103, type_inference_query_value=0.001, type_inference_query_ci_lower=0.001, type_inference_query_ci_upper=0.001, type_temporal_query_n=78, type_temporal_query_value=0.001, type_temporal_query_ci_lower=0.001, type_temporal_query_ci_upper=0.001 |



| `spend_usd_mean__hybrid_graph_v2` | ok | **0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.001, ci_upper=0.001, type_comparison_query_n=123, type_comparison_query_value=0.001, type_comparison_query_ci_lower=0.001, type_comparison_query_ci_upper=0.001, type_inference_query_n=103, type_inference_query_value=0.001, type_inference_query_ci_lower=0.001, type_inference_query_ci_upper=0.001, type_temporal_query_n=78, type_temporal_query_value=0.001, type_temporal_query_ci_lower=0.001, type_temporal_query_ci_upper=0.001 |



| `spend_usd_mean__hybrid_all` | ok | **0.001** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.001, ci_upper=0.001, type_comparison_query_n=123, type_comparison_query_value=0.001, type_comparison_query_ci_lower=0.001, type_comparison_query_ci_upper=0.001, type_inference_query_n=103, type_inference_query_value=0.001, type_inference_query_ci_lower=0.001, type_inference_query_ci_upper=0.001, type_temporal_query_n=78, type_temporal_query_value=0.001, type_temporal_query_ci_lower=0.001, type_temporal_query_ci_upper=0.001 |



| `spend_usd_delta__hybrid_graph` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.000, ci_upper=0.000, n_pairs=304, mean_x=0.001, mean_hybrid=0.001, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.000, type_comparison_query_ci_lower=-0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n_pairs=103, type_inference_query_delta=0.000, type_inference_query_ci_lower=-0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.000, type_temporal_query_ci_lower=-0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_delta__hybrid_rerank` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, n_pairs=304, mean_x=0.001, mean_hybrid=0.001, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.000, type_comparison_query_ci_lower=0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n_pairs=103, type_inference_query_delta=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.000, type_temporal_query_ci_lower=0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_delta__hybrid_metadata` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, n_pairs=304, mean_x=0.001, mean_hybrid=0.001, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.000, type_comparison_query_ci_lower=0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n_pairs=103, type_inference_query_delta=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.000, type_temporal_query_ci_lower=0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_delta__hybrid_answer_format` | ok | **-0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=-0.000, ci_upper=0.000, n_pairs=304, mean_x=0.001, mean_hybrid=0.001, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.000, type_comparison_query_ci_lower=-0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n_pairs=103, type_inference_query_delta=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=78, type_temporal_query_delta=-0.000, type_temporal_query_ci_lower=-0.000, type_temporal_query_ci_upper=-0.000 |



| `spend_usd_delta__hybrid_graph_v2` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, n_pairs=304, mean_x=0.001, mean_hybrid=0.001, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.000, type_comparison_query_ci_lower=-0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n_pairs=103, type_inference_query_delta=0.000, type_inference_query_ci_lower=-0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.000, type_temporal_query_ci_lower=-0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_delta__hybrid_all` | ok | **0.000** | 304 | n_excluded=4, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, n_pairs=304, mean_x=0.001, mean_hybrid=0.001, type_comparison_query_n_pairs=123, type_comparison_query_delta=0.000, type_comparison_query_ci_lower=0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n_pairs=103, type_inference_query_delta=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=78, type_temporal_query_delta=0.000, type_temporal_query_ci_lower=0.000, type_temporal_query_ci_upper=0.000 |



| `latency_total_ms_p50__hybrid` | ok | **8130.0** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=8196, type_inference_query_n=103, type_inference_query_value=8095, type_temporal_query_n=78, type_temporal_query_value=8296.500 |



| `latency_total_ms_p95__hybrid` | ok | **11777.5** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=12865.100, type_inference_query_n=103, type_inference_query_value=10542.500, type_temporal_query_n=78, type_temporal_query_value=12893.100 |



| `latency_total_ms_p50__hybrid_graph` | ok | **8173.0** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=8263, type_inference_query_n=103, type_inference_query_value=8158, type_temporal_query_n=78, type_temporal_query_value=8147 |



| `latency_total_ms_p95__hybrid_graph` | ok | **11801.6** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=12149.100, type_inference_query_n=103, type_inference_query_value=11687.200, type_temporal_query_n=78, type_temporal_query_value=11459.300 |



| `latency_total_ms_p50__hybrid_rerank` | ok | **8399.5** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=8408, type_inference_query_n=103, type_inference_query_value=8246, type_temporal_query_n=78, type_temporal_query_value=8833 |



| `latency_total_ms_p95__hybrid_rerank` | ok | **12441.2** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=13346.000, type_inference_query_n=103, type_inference_query_value=11525.800, type_temporal_query_n=78, type_temporal_query_value=13283.100 |



| `latency_total_ms_p50__hybrid_metadata` | ok | **8095.5** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=8090, type_inference_query_n=103, type_inference_query_value=8097, type_temporal_query_n=78, type_temporal_query_value=8113.500 |



| `latency_total_ms_p95__hybrid_metadata` | ok | **11860.3** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=11714, type_inference_query_n=103, type_inference_query_value=12881.600, type_temporal_query_n=78, type_temporal_query_value=10796.650 |



| `latency_total_ms_p50__hybrid_answer_format` | ok | **8064.0** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=8107, type_inference_query_n=103, type_inference_query_value=8059, type_temporal_query_n=78, type_temporal_query_value=7062 |



| `latency_total_ms_p95__hybrid_answer_format` | ok | **11723.6** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=12764.400, type_inference_query_n=103, type_inference_query_value=11724.100, type_temporal_query_n=78, type_temporal_query_value=10477.850 |



| `latency_total_ms_p50__hybrid_graph_v2` | ok | **8335.0** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=8719, type_inference_query_n=103, type_inference_query_value=8158, type_temporal_query_n=78, type_temporal_query_value=8123 |



| `latency_total_ms_p95__hybrid_graph_v2` | ok | **12423.9** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=12942.600, type_inference_query_n=103, type_inference_query_value=11654.500, type_temporal_query_n=78, type_temporal_query_value=12227.500 |



| `latency_total_ms_p50__hybrid_all` | ok | **8961.5** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=9047, type_inference_query_n=103, type_inference_query_value=8436, type_temporal_query_n=78, type_temporal_query_value=9528.500 |



| `latency_total_ms_p95__hybrid_all` | ok | **12110.2** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=12021.600, type_inference_query_n=103, type_inference_query_value=12023.400, type_temporal_query_n=78, type_temporal_query_value=13356.550 |



| `retrieve_node_ms_p50__hybrid` | ok | **95.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=91, type_inference_query_n=103, type_inference_query_value=100, type_temporal_query_n=78, type_temporal_query_value=94.500 |



| `retrieve_node_ms_p95__hybrid` | ok | **116.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=109, type_inference_query_n=103, type_inference_query_value=121.900, type_temporal_query_n=78, type_temporal_query_value=111.150 |



| `retrieve_node_ms_p50__hybrid_graph` | ok | **111.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=108, type_inference_query_n=103, type_inference_query_value=116, type_temporal_query_n=78, type_temporal_query_value=112 |



| `retrieve_node_ms_p95__hybrid_graph` | ok | **142.850** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=136.600, type_inference_query_n=103, type_inference_query_value=158.200, type_temporal_query_n=78, type_temporal_query_value=135.300 |



| `retrieve_node_ms_p50__hybrid_rerank` | ok | **419.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=400, type_inference_query_n=103, type_inference_query_value=436, type_temporal_query_n=78, type_temporal_query_value=419 |



| `retrieve_node_ms_p95__hybrid_rerank` | ok | **1172.100** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=1147.800, type_inference_query_n=103, type_inference_query_value=1172.400, type_temporal_query_n=78, type_temporal_query_value=1193.100 |



| `retrieve_node_ms_p50__hybrid_metadata` | ok | **95.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=92, type_inference_query_n=103, type_inference_query_value=99, type_temporal_query_n=78, type_temporal_query_value=93.500 |



| `retrieve_node_ms_p95__hybrid_metadata` | ok | **119.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=114.600, type_inference_query_n=103, type_inference_query_value=124.900, type_temporal_query_n=78, type_temporal_query_value=109.450 |



| `retrieve_node_ms_p50__hybrid_answer_format` | ok | **94.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=90, type_inference_query_n=103, type_inference_query_value=100, type_temporal_query_n=78, type_temporal_query_value=92 |



| `retrieve_node_ms_p95__hybrid_answer_format` | ok | **115.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=106.600, type_inference_query_n=103, type_inference_query_value=116.800, type_temporal_query_n=78, type_temporal_query_value=118 |



| `retrieve_node_ms_p50__hybrid_graph_v2` | ok | **112.000** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=110, type_inference_query_n=103, type_inference_query_value=117, type_temporal_query_n=78, type_temporal_query_value=115 |



| `retrieve_node_ms_p95__hybrid_graph_v2` | ok | **139.850** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=133.700, type_inference_query_n=103, type_inference_query_value=150.400, type_temporal_query_n=78, type_temporal_query_value=140.300 |



| `retrieve_node_ms_p50__hybrid_all` | ok | **459.500** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=438, type_inference_query_n=103, type_inference_query_value=467, type_temporal_query_n=78, type_temporal_query_value=468 |



| `retrieve_node_ms_p95__hybrid_all` | ok | **1216.550** | 304 | n_excluded=4, n_unscorable=0, type_comparison_query_n=123, type_comparison_query_value=1209.300, type_inference_query_n=103, type_inference_query_value=1351.100, type_temporal_query_n=78, type_temporal_query_value=1214.450 |



| `paper_hits_at_4_script_faithful__hybrid` | ok | **0.698** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=215, ci_lower=0.645, ci_upper=0.747, type_comparison_query_n=125, type_comparison_query_value=0.728, type_comparison_query_ci_lower=0.644, type_comparison_query_ci_upper=0.798, type_inference_query_n=105, type_inference_query_value=0.771, type_inference_query_ci_lower=0.682, type_inference_query_ci_upper=0.841, type_temporal_query_n=78, type_temporal_query_value=0.551, type_temporal_query_ci_lower=0.441, type_temporal_query_ci_upper=0.657 |



| `paper_hits_at_10_script_faithful__hybrid` | ok | **0.838** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=258, ci_lower=0.792, ci_upper=0.875, type_comparison_query_n=125, type_comparison_query_value=0.888, type_comparison_query_ci_lower=0.821, type_comparison_query_ci_upper=0.932, type_inference_query_n=105, type_inference_query_value=0.857, type_inference_query_ci_lower=0.778, type_inference_query_ci_upper=0.911, type_temporal_query_n=78, type_temporal_query_value=0.731, type_temporal_query_ci_lower=0.623, type_temporal_query_ci_upper=0.817 |



| `paper_mrr_at_10_script_faithful__hybrid` | ok | **0.583** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.536, ci_upper=0.630, type_comparison_query_n=125, type_comparison_query_value=0.597, type_comparison_query_ci_lower=0.525, type_comparison_query_ci_upper=0.667, type_inference_query_n=105, type_inference_query_value=0.653, type_inference_query_ci_lower=0.574, type_inference_query_ci_upper=0.730, type_temporal_query_n=78, type_temporal_query_value=0.466, type_temporal_query_ci_lower=0.372, type_temporal_query_ci_upper=0.561 |



| `paper_map_at_10_script_faithful__hybrid` | ok | **0.283** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.258, ci_upper=0.309, type_comparison_query_n=125, type_comparison_query_value=0.335, type_comparison_query_ci_lower=0.292, type_comparison_query_ci_upper=0.377, type_inference_query_n=105, type_inference_query_value=0.257, type_inference_query_ci_lower=0.220, type_inference_query_ci_upper=0.292, type_temporal_query_n=78, type_temporal_query_value=0.234, type_temporal_query_ci_lower=0.181, type_temporal_query_ci_upper=0.287 |



| `paper_hits_at_4_script_faithful__hybrid_graph` | ok | **0.682** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=210, ci_lower=0.628, ci_upper=0.731, type_comparison_query_n=125, type_comparison_query_value=0.712, type_comparison_query_ci_lower=0.627, type_comparison_query_ci_upper=0.784, type_inference_query_n=105, type_inference_query_value=0.752, type_inference_query_ci_lower=0.662, type_inference_query_ci_upper=0.825, type_temporal_query_n=78, type_temporal_query_value=0.538, type_temporal_query_ci_lower=0.429, type_temporal_query_ci_upper=0.645 |



| `paper_hits_at_10_script_faithful__hybrid_graph` | ok | **0.815** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=251, ci_lower=0.768, ci_upper=0.854, type_comparison_query_n=125, type_comparison_query_value=0.872, type_comparison_query_ci_lower=0.802, type_comparison_query_ci_upper=0.920, type_inference_query_n=105, type_inference_query_value=0.848, type_inference_query_ci_lower=0.767, type_inference_query_ci_upper=0.904, type_temporal_query_n=78, type_temporal_query_value=0.679, type_temporal_query_ci_lower=0.570, type_temporal_query_ci_upper=0.773 |



| `paper_mrr_at_10_script_faithful__hybrid_graph` | ok | **0.545** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.497, ci_upper=0.590, type_comparison_query_n=125, type_comparison_query_value=0.561, type_comparison_query_ci_lower=0.490, type_comparison_query_ci_upper=0.631, type_inference_query_n=105, type_inference_query_value=0.613, type_inference_query_ci_lower=0.533, type_inference_query_ci_upper=0.689, type_temporal_query_n=78, type_temporal_query_value=0.429, type_temporal_query_ci_lower=0.335, type_temporal_query_ci_upper=0.523 |



| `paper_map_at_10_script_faithful__hybrid_graph` | ok | **0.264** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.239, ci_upper=0.289, type_comparison_query_n=125, type_comparison_query_value=0.316, type_comparison_query_ci_lower=0.272, type_comparison_query_ci_upper=0.359, type_inference_query_n=105, type_inference_query_value=0.241, type_inference_query_ci_lower=0.206, type_inference_query_ci_upper=0.277, type_temporal_query_n=78, type_temporal_query_value=0.211, type_temporal_query_ci_lower=0.162, type_temporal_query_ci_upper=0.260 |



| `paper_hits_at_4_script_faithful__hybrid_rerank` | ok | **0.854** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=263, ci_lower=0.810, ci_upper=0.889, type_comparison_query_n=125, type_comparison_query_value=0.912, type_comparison_query_ci_lower=0.849, type_comparison_query_ci_upper=0.950, type_inference_query_n=105, type_inference_query_value=0.848, type_inference_query_ci_lower=0.767, type_inference_query_ci_upper=0.904, type_temporal_query_n=78, type_temporal_query_value=0.769, type_temporal_query_ci_lower=0.664, type_temporal_query_ci_upper=0.849 |



| `paper_hits_at_10_script_faithful__hybrid_rerank` | ok | **0.919** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=283, ci_lower=0.883, ci_upper=0.944, type_comparison_query_n=125, type_comparison_query_value=0.944, type_comparison_query_ci_lower=0.889, type_comparison_query_ci_upper=0.973, type_inference_query_n=105, type_inference_query_value=0.943, type_inference_query_ci_lower=0.881, type_inference_query_ci_upper=0.974, type_temporal_query_n=78, type_temporal_query_value=0.846, type_temporal_query_ci_lower=0.750, type_temporal_query_ci_upper=0.910 |



| `paper_mrr_at_10_script_faithful__hybrid_rerank` | ok | **0.765** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.723, ci_upper=0.805, type_comparison_query_n=125, type_comparison_query_value=0.807, type_comparison_query_ci_lower=0.747, type_comparison_query_ci_upper=0.864, type_inference_query_n=105, type_inference_query_value=0.771, type_inference_query_ci_lower=0.704, type_inference_query_ci_upper=0.837, type_temporal_query_n=78, type_temporal_query_value=0.688, type_temporal_query_ci_lower=0.597, type_temporal_query_ci_upper=0.777 |



| `paper_map_at_10_script_faithful__hybrid_rerank` | ok | **0.408** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.382, ci_upper=0.433, type_comparison_query_n=125, type_comparison_query_value=0.496, type_comparison_query_ci_lower=0.455, type_comparison_query_ci_upper=0.536, type_inference_query_n=105, type_inference_query_value=0.352, type_inference_query_ci_lower=0.315, type_inference_query_ci_upper=0.388, type_temporal_query_n=78, type_temporal_query_value=0.341, type_temporal_query_ci_lower=0.289, type_temporal_query_ci_upper=0.393 |



| `paper_hits_at_4_script_faithful__hybrid_metadata` | ok | **0.692** | 308 | n_excluded=0, n_no_valid_ranking=2, successes=213, ci_lower=0.638, ci_upper=0.741, type_comparison_query_n=125, type_comparison_query_value=0.720, type_comparison_query_ci_lower=0.636, type_comparison_query_ci_upper=0.791, type_inference_query_n=105, type_inference_query_value=0.762, type_inference_query_ci_lower=0.672, type_inference_query_ci_upper=0.833, type_temporal_query_n=78, type_temporal_query_value=0.551, type_temporal_query_ci_lower=0.441, type_temporal_query_ci_upper=0.657 |



| `paper_hits_at_10_script_faithful__hybrid_metadata` | ok | **0.828** | 308 | n_excluded=0, n_no_valid_ranking=2, successes=255, ci_lower=0.782, ci_upper=0.866, type_comparison_query_n=125, type_comparison_query_value=0.872, type_comparison_query_ci_lower=0.802, type_comparison_query_ci_upper=0.920, type_inference_query_n=105, type_inference_query_value=0.848, type_inference_query_ci_lower=0.767, type_inference_query_ci_upper=0.904, type_temporal_query_n=78, type_temporal_query_value=0.731, type_temporal_query_ci_lower=0.623, type_temporal_query_ci_upper=0.817 |



| `paper_mrr_at_10_script_faithful__hybrid_metadata` | ok | **0.578** | 308 | n_excluded=0, n_no_valid_ranking=2, ci_lower=0.530, ci_upper=0.625, type_comparison_query_n=125, type_comparison_query_value=0.592, type_comparison_query_ci_lower=0.519, type_comparison_query_ci_upper=0.663, type_inference_query_n=105, type_inference_query_value=0.644, type_inference_query_ci_lower=0.565, type_inference_query_ci_upper=0.722, type_temporal_query_n=78, type_temporal_query_value=0.467, type_temporal_query_ci_lower=0.373, type_temporal_query_ci_upper=0.562 |



| `paper_map_at_10_script_faithful__hybrid_metadata` | ok | **0.281** | 308 | n_excluded=0, n_no_valid_ranking=2, ci_lower=0.256, ci_upper=0.307, type_comparison_query_n=125, type_comparison_query_value=0.333, type_comparison_query_ci_lower=0.290, type_comparison_query_ci_upper=0.375, type_inference_query_n=105, type_inference_query_value=0.254, type_inference_query_ci_lower=0.217, type_inference_query_ci_upper=0.290, type_temporal_query_n=78, type_temporal_query_value=0.235, type_temporal_query_ci_lower=0.182, type_temporal_query_ci_upper=0.287 |



| `paper_hits_at_4_script_faithful__hybrid_answer_format` | ok | **0.695** | 308 | n_excluded=0, n_no_valid_ranking=1, successes=214, ci_lower=0.641, ci_upper=0.744, type_comparison_query_n=125, type_comparison_query_value=0.720, type_comparison_query_ci_lower=0.636, type_comparison_query_ci_upper=0.791, type_inference_query_n=105, type_inference_query_value=0.771, type_inference_query_ci_lower=0.682, type_inference_query_ci_upper=0.841, type_temporal_query_n=78, type_temporal_query_value=0.551, type_temporal_query_ci_lower=0.441, type_temporal_query_ci_upper=0.657 |



| `paper_hits_at_10_script_faithful__hybrid_answer_format` | ok | **0.831** | 308 | n_excluded=0, n_no_valid_ranking=1, successes=256, ci_lower=0.785, ci_upper=0.869, type_comparison_query_n=125, type_comparison_query_value=0.872, type_comparison_query_ci_lower=0.802, type_comparison_query_ci_upper=0.920, type_inference_query_n=105, type_inference_query_value=0.857, type_inference_query_ci_lower=0.778, type_inference_query_ci_upper=0.911, type_temporal_query_n=78, type_temporal_query_value=0.731, type_temporal_query_ci_lower=0.623, type_temporal_query_ci_upper=0.817 |



| `paper_mrr_at_10_script_faithful__hybrid_answer_format` | ok | **0.581** | 308 | n_excluded=0, n_no_valid_ranking=1, ci_lower=0.533, ci_upper=0.628, type_comparison_query_n=125, type_comparison_query_value=0.592, type_comparison_query_ci_lower=0.520, type_comparison_query_ci_upper=0.663, type_inference_query_n=105, type_inference_query_value=0.653, type_inference_query_ci_lower=0.574, type_inference_query_ci_upper=0.730, type_temporal_query_n=78, type_temporal_query_value=0.467, type_temporal_query_ci_lower=0.373, type_temporal_query_ci_upper=0.562 |



| `paper_map_at_10_script_faithful__hybrid_answer_format` | ok | **0.282** | 308 | n_excluded=0, n_no_valid_ranking=1, ci_lower=0.256, ci_upper=0.307, type_comparison_query_n=125, type_comparison_query_value=0.332, type_comparison_query_ci_lower=0.289, type_comparison_query_ci_upper=0.374, type_inference_query_n=105, type_inference_query_value=0.257, type_inference_query_ci_lower=0.220, type_inference_query_ci_upper=0.292, type_temporal_query_n=78, type_temporal_query_value=0.234, type_temporal_query_ci_lower=0.182, type_temporal_query_ci_upper=0.287 |



| `paper_hits_at_4_script_faithful__hybrid_graph_v2` | ok | **0.685** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=211, ci_lower=0.631, ci_upper=0.734, type_comparison_query_n=125, type_comparison_query_value=0.728, type_comparison_query_ci_lower=0.644, type_comparison_query_ci_upper=0.798, type_inference_query_n=105, type_inference_query_value=0.762, type_inference_query_ci_lower=0.672, type_inference_query_ci_upper=0.833, type_temporal_query_n=78, type_temporal_query_value=0.513, type_temporal_query_ci_lower=0.404, type_temporal_query_ci_upper=0.621 |



| `paper_hits_at_10_script_faithful__hybrid_graph_v2` | ok | **0.818** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=252, ci_lower=0.771, ci_upper=0.857, type_comparison_query_n=125, type_comparison_query_value=0.872, type_comparison_query_ci_lower=0.802, type_comparison_query_ci_upper=0.920, type_inference_query_n=105, type_inference_query_value=0.848, type_inference_query_ci_lower=0.767, type_inference_query_ci_upper=0.904, type_temporal_query_n=78, type_temporal_query_value=0.692, type_temporal_query_ci_lower=0.583, type_temporal_query_ci_upper=0.784 |



| `paper_mrr_at_10_script_faithful__hybrid_graph_v2` | ok | **0.556** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.509, ci_upper=0.603, type_comparison_query_n=125, type_comparison_query_value=0.566, type_comparison_query_ci_lower=0.494, type_comparison_query_ci_upper=0.637, type_inference_query_n=105, type_inference_query_value=0.642, type_inference_query_ci_lower=0.562, type_inference_query_ci_upper=0.718, type_temporal_query_n=78, type_temporal_query_value=0.426, type_temporal_query_ci_lower=0.332, type_temporal_query_ci_upper=0.518 |



| `paper_map_at_10_script_faithful__hybrid_graph_v2` | ok | **0.269** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.244, ci_upper=0.295, type_comparison_query_n=125, type_comparison_query_value=0.319, type_comparison_query_ci_lower=0.275, type_comparison_query_ci_upper=0.361, type_inference_query_n=105, type_inference_query_value=0.251, type_inference_query_ci_lower=0.216, type_inference_query_ci_upper=0.287, type_temporal_query_n=78, type_temporal_query_value=0.213, type_temporal_query_ci_lower=0.165, type_temporal_query_ci_upper=0.262 |



| `paper_hits_at_4_script_faithful__hybrid_all` | ok | **0.851** | 308 | n_excluded=0, n_no_valid_ranking=1, successes=262, ci_lower=0.807, ci_upper=0.886, type_comparison_query_n=125, type_comparison_query_value=0.912, type_comparison_query_ci_lower=0.849, type_comparison_query_ci_upper=0.950, type_inference_query_n=105, type_inference_query_value=0.838, type_inference_query_ci_lower=0.756, type_inference_query_ci_upper=0.896, type_temporal_query_n=78, type_temporal_query_value=0.769, type_temporal_query_ci_lower=0.664, type_temporal_query_ci_upper=0.849 |



| `paper_hits_at_10_script_faithful__hybrid_all` | ok | **0.916** | 308 | n_excluded=0, n_no_valid_ranking=1, successes=282, ci_lower=0.879, ci_upper=0.942, type_comparison_query_n=125, type_comparison_query_value=0.944, type_comparison_query_ci_lower=0.889, type_comparison_query_ci_upper=0.973, type_inference_query_n=105, type_inference_query_value=0.933, type_inference_query_ci_lower=0.869, type_inference_query_ci_upper=0.967, type_temporal_query_n=78, type_temporal_query_value=0.846, type_temporal_query_ci_lower=0.750, type_temporal_query_ci_upper=0.910 |



| `paper_mrr_at_10_script_faithful__hybrid_all` | ok | **0.761** | 308 | n_excluded=0, n_no_valid_ranking=1, ci_lower=0.720, ci_upper=0.802, type_comparison_query_n=125, type_comparison_query_value=0.807, type_comparison_query_ci_lower=0.746, type_comparison_query_ci_upper=0.864, type_inference_query_n=105, type_inference_query_value=0.762, type_inference_query_ci_lower=0.692, type_inference_query_ci_upper=0.828, type_temporal_query_n=78, type_temporal_query_value=0.688, type_temporal_query_ci_lower=0.597, type_temporal_query_ci_upper=0.777 |



| `paper_map_at_10_script_faithful__hybrid_all` | ok | **0.405** | 308 | n_excluded=0, n_no_valid_ranking=1, ci_lower=0.379, ci_upper=0.431, type_comparison_query_n=125, type_comparison_query_value=0.496, type_comparison_query_ci_lower=0.455, type_comparison_query_ci_upper=0.536, type_inference_query_n=105, type_inference_query_value=0.345, type_inference_query_ci_lower=0.309, type_inference_query_ci_upper=0.381, type_temporal_query_n=78, type_temporal_query_value=0.340, type_temporal_query_ci_lower=0.288, type_temporal_query_ci_upper=0.392 |



| `answer_usable_sc3_definition__hybrid` | ok | **0.571** | 308 | n_excluded=0, successes=176, ci_lower=0.516, ci_upper=0.625, type_comparison_query_n=125, type_comparison_query_value=0.448, type_comparison_query_ci_lower=0.364, type_comparison_query_ci_upper=0.535, type_inference_query_n=105, type_inference_query_value=0.962, type_inference_query_ci_lower=0.906, type_inference_query_ci_upper=0.985, type_temporal_query_n=78, type_temporal_query_value=0.244, type_temporal_query_ci_lower=0.162, type_temporal_query_ci_upper=0.349, type_comparison_query_constant_yes_baseline=0.640, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_sc3_definition__hybrid_graph` | ok | **0.565** | 308 | n_excluded=0, successes=174, ci_lower=0.509, ci_upper=0.619, type_comparison_query_n=125, type_comparison_query_value=0.456, type_comparison_query_ci_lower=0.371, type_comparison_query_ci_upper=0.543, type_inference_query_n=105, type_inference_query_value=0.962, type_inference_query_ci_lower=0.906, type_inference_query_ci_upper=0.985, type_temporal_query_n=78, type_temporal_query_value=0.205, type_temporal_query_ci_lower=0.130, type_temporal_query_ci_upper=0.308, type_comparison_query_constant_yes_baseline=0.640, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_sc3_definition__hybrid_rerank` | ok | **0.653** | 308 | n_excluded=0, successes=201, ci_lower=0.598, ci_upper=0.704, type_comparison_query_n=125, type_comparison_query_value=0.544, type_comparison_query_ci_lower=0.457, type_comparison_query_ci_upper=0.629, type_inference_query_n=105, type_inference_query_value=0.981, type_inference_query_ci_lower=0.933, type_inference_query_ci_upper=0.995, type_temporal_query_n=78, type_temporal_query_value=0.385, type_temporal_query_ci_lower=0.284, type_temporal_query_ci_upper=0.496, type_comparison_query_constant_yes_baseline=0.640, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_sc3_definition__hybrid_metadata` | ok | **0.634** | 306 | n_excluded=2, successes=194, ci_lower=0.579, ci_upper=0.686, type_comparison_query_n=124, type_comparison_query_value=0.556, type_comparison_query_ci_lower=0.469, type_comparison_query_ci_upper=0.641, type_inference_query_n=104, type_inference_query_value=0.981, type_inference_query_ci_lower=0.933, type_inference_query_ci_upper=0.995, type_temporal_query_n=78, type_temporal_query_value=0.295, type_temporal_query_ci_lower=0.205, type_temporal_query_ci_upper=0.404, type_comparison_query_constant_yes_baseline=0.637, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_sc3_definition__hybrid_answer_format` | ok | **0.531** | 307 | n_excluded=1, successes=163, ci_lower=0.475, ci_upper=0.586, type_comparison_query_n=124, type_comparison_query_value=0.435, type_comparison_query_ci_lower=0.351, type_comparison_query_ci_upper=0.523, type_inference_query_n=105, type_inference_query_value=0.895, type_inference_query_ci_lower=0.822, type_inference_query_ci_upper=0.940, type_temporal_query_n=78, type_temporal_query_value=0.192, type_temporal_query_ci_lower=0.120, type_temporal_query_ci_upper=0.293, type_comparison_query_constant_yes_baseline=0.637, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_sc3_definition__hybrid_graph_v2` | ok | **0.552** | 308 | n_excluded=0, successes=170, ci_lower=0.496, ci_upper=0.607, type_comparison_query_n=125, type_comparison_query_value=0.432, type_comparison_query_ci_lower=0.348, type_comparison_query_ci_upper=0.520, type_inference_query_n=105, type_inference_query_value=0.943, type_inference_query_ci_lower=0.881, type_inference_query_ci_upper=0.974, type_temporal_query_n=78, type_temporal_query_value=0.218, type_temporal_query_ci_lower=0.141, type_temporal_query_ci_upper=0.322, type_comparison_query_constant_yes_baseline=0.640, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_sc3_definition__hybrid_all` | ok | **0.744** | 308 | n_excluded=0, successes=229, ci_lower=0.692, ci_upper=0.789, type_comparison_query_n=125, type_comparison_query_value=0.704, type_comparison_query_ci_lower=0.619, type_comparison_query_ci_upper=0.777, type_inference_query_n=105, type_inference_query_value=0.943, type_inference_query_ci_lower=0.881, type_inference_query_ci_upper=0.974, type_temporal_query_n=78, type_temporal_query_value=0.538, type_temporal_query_ci_lower=0.429, type_temporal_query_ci_upper=0.645, type_comparison_query_constant_yes_baseline=0.640, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `null_abstention_correctness__hybrid` | ok | **0.953** | 43 | successes=41, ci_lower=0.845, ci_upper=0.987, n_excluded=0, hallucinated_on_null=2, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__hybrid_graph` | ok | **0.953** | 43 | successes=41, ci_lower=0.845, ci_upper=0.987, n_excluded=0, hallucinated_on_null=2, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__hybrid_rerank` | ok | **0.907** | 43 | successes=39, ci_lower=0.784, ci_upper=0.963, n_excluded=0, hallucinated_on_null=4, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__hybrid_metadata` | ok | **0.977** | 43 | successes=42, ci_lower=0.879, ci_upper=0.996, n_excluded=0, hallucinated_on_null=1, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__hybrid_answer_format` | ok | **0.953** | 43 | successes=41, ci_lower=0.845, ci_upper=0.987, n_excluded=0, hallucinated_on_null=2, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__hybrid_graph_v2` | ok | **0.953** | 43 | successes=41, ci_lower=0.845, ci_upper=0.987, n_excluded=0, hallucinated_on_null=2, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__hybrid_all` | ok | **0.951** | 41 | successes=39, ci_lower=0.839, ci_upper=0.987, n_excluded=2, hallucinated_on_null=2, no_evidence_count=0, leak_count=0 |



## Methodological Caveats & Notes

1. **Evidence Matching Rule:** A retrieved chunk matches a gold fact if and only if the chunk's normalized text contains the fact's normalized text as a contiguous substring. Facts straddling chunk boundaries resolve to misses and are surfaced separately in the `boundary_attributable_misses` diagnostic count.
2. **Evidence Source Distinction:** Every retrieval metric is computed over the response's retrieved-chunk list (what the retriever returned), not over the citations the model emitted. Judged dimensions are computed over cited evidence instead.
3. **Chunk Size & Overlength Facts:** Gold facts longer than the corpus's chunk size cannot appear verbatim in any single chunk, are excluded from the recall denominator, and are reported as their own count.
4. **Paper Comparability:** Lancet's answer metrics are not comparable to the MultiHop-RAG paper's reported accuracy, because the reference scorer credits any shared lowercased token.
5. **Ranking Metric Convention:** Neither reported ranking metric is the MultiHop-RAG paper's own convention unless the additive reference-convention figure is present and labelled.
6. **Infrastructure Failure & Scorable Payload Denominator Exclusion:** Infrastructure-failed records (unusable records) are excluded from every quality denominator, retrieval and answer alike, and their count and rate are published as their own dimension (`unusable_record_rate`). Usable records carrying no scorable payload—lacking a retrieval snapshot or non-blank answer text—are likewise excluded from every quality denominator rather than scored as zero, and their count is published in detail on each affected dimension scoped to that dimension's scored population. Retrieval and answer quality denominators are drawn from a single record population; any difference between retrieval and answer sample sizes arises solely from metric-specific skips published with their reasons, never from disagreement over eligible records. Paired ablation deltas enforce this same payload rule, excluding any pair containing a record without scorable payload from all paired quality deltas.
7. **Arm Provenance Exclusion:** A graph-off record that fails provenance verification is excluded from graph-off quality metrics and recorded as an arm provenance exclusion.
8. **Rounding & Advisory Status:** This report is advisory only with no automated pass/fail gate. Scores are rounded using banker's rounding across three conventions: 3 decimals for ratios, 2 decimals for judged scales, and 1 decimal for absolute magnitudes such as latency milliseconds and prompt token counts. Full float precision is recorded in report.json.
9. **Ablation Comparability:** The 2026-09-03 graph ablation delta value of 0.010 is not comparable to any value this dimension now produces. That historical run averaged sixteen graph-on means against eighteen graph-off means sharing only eight questions (a 1.6% overlap). The dimension is now a per-question paired difference over usable records present in both arms.
10. **Graph Emptiness & Canary Exception:** Graph presence and influence are published numbers; an empty graph result never makes a run fail. The sole exception is the committed preflight canary, whose designated rows assert a graph hit for questions whose entities are known to be present.
11. **Wire Contract Conformance:** The `wire_contract_conformance` dimension counts self-contradiction rather than mere parse success. Its historical value from 2026-09-03 is not comparable; that run would score approximately 0.034 under the current definition.
12. **Raw Event Stream Retention:** Raw streaming events from failing queries and a deterministic baseline sample of successful queries are retained in raw_events/ alongside the journal for bounded post-hoc forensic inspection.
13. **Retrieval Latency Scope:** Reported retrieval latency (`retrieve_latency_ms`) measures the total elapsed duration of the hybrid retrieval node—dense vector search, lexical search, and reciprocal rank fusion together—as captured on the wire, rather than a dense-only timer.