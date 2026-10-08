# Evaluation Report: multihop_rag_heldout


## Run Metadata

| Parameter | Value |
|---|---|
| **Corpus** | `multihop_rag_heldout` |
| **Run Date** | `2026-10-08T01:08:34.728504+00:00` |
| **Commit SHA** | `8af27322beee804a2a75296e120a1656dceed2fe` |
| **Generation Model** | `deepseek/deepseek-v4-flash-0731` |
| **Embedding Model** | `voyageai/voyage-4-large` |
| **Judge Model** | `meta-llama/llama-3.3-70b-instruct` |
| **Judge Temperature** | `0.0` |
| **Judge Prompt Version** | `v1` |
| **Sampling Seed** | `42` |
| **Deterministic Sample Size** | `351` |
| **Judged Sample Size** | `0` |
| **Completed Calibration Dual Scores** | `0` |
| **Index Generation** | `lance-702` |
| **Result Hash** | `b6b5255c322b4f7e` |
| **Dependency Lock Hash** | `8e71ea9ce7a3532b` |
| **Arm Labels** | `dense-only, bm25-only, hybrid, hybrid+graph` |
| **Notes** | No judge-versus-human calibration was performed; judged dimensions are uncalibrated. |


## Evaluation Dimensions

| Dimension | Status | Score | Sample Size (n) | Details / Reason |
|---|---|---|---|---|


| `unusable_record_rate` | ok | **0.009** | 1404 | unusable_n=13, n_journal=1404, unusable_rate=0.009, ci_lower=0.005, ci_upper=0.016, collapsed_records_n=0 |



| `vector_yield` | ok | **1.000** | 349 | mean_count=32, positive_n=349, n_eval=349, missing_meta_n=0, ci_lower=0.989, ci_upper=1.000, retrieve_p50_ms=113, retrieve_p95_ms=163.2 |



| `bm25_yield` | ok | **1.000** | 349 | mean_count=32, positive_n=349, n_eval=349, missing_meta_n=0, ci_lower=0.989, ci_upper=1.000, retrieve_p50_ms=113, retrieve_p95_ms=163.2 |



| `retrieve_latency_ms` | ok | **113.0** | 349 | retrieve_p95_ms=163.2, missing_timing_n=0, n_eval=349 |



| `graph_presence_rate` | ok | **0.570** | 349 | positive_n=199, n_eval=349, missing_meta_n=0, ci_lower=0.518, ci_upper=0.621, investigation_floor=0.200, floor_miss=0, no_match_rate=0, completed_graph_n=347 |



| `graph_influence_rate` | ok | **0.570** | 349 | positive_n=199, n_eval=349, missing_influence_n=0, ci_lower=0.518, ci_upper=0.621 |



| `graph_latency_ms` | ok | **617.0** | 349 | graph_p95_ms=1970.0, missing_timing_n=0, n_eval=349 |



| `retrieval_evidence_coverage` | ok | **0.357** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `context_precision_at_k` | ok | **0.214** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `ranking_quality` | ok | **0.539** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `answer_exact_match` | ok | **0.000** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `answer_f1` | ok | **0.014** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `final_answer_em` | ok | **0.562** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `final_answer_containment` | ok | **0.647** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `answer_usable` | ok | **0.565** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `final_answer_missing_rate` | ok | **0.000** | 306 | errors=2, sample_size=306, excluded_payload_records=0 |



| `answer_faithfulness` | skipped | — | 0 | Deferred to LLM-as-judge scoring pass (--no-judge specified); judged_slice_committed=0, verdicts_obtained=0, judged_slice_state=0, usage_absent_fallback_count=0 |



| `answer_groundedness` | skipped | — | 0 | Deferred to LLM-as-judge scoring pass (--no-judge specified); judged_slice_committed=0, verdicts_obtained=0, judged_slice_state=0, usage_absent_fallback_count=0 |



| `graph_ablation_delta` | ok | **-0.005** | 301 | n_pairs=301, pairing_coverage=0.858, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, single_arm_usable_drops=8, missing_arm_drops=0, null_gold_drops=42, provenance_drops=0, ci_lower=-0.023, ci_upper=0.012, delta_comparison_query=0.008, n_pairs_comparison_query=123, delta_temporal_query=-0.015, n_pairs_temporal_query=77, delta_inference_query=-0.014, n_pairs_inference_query=101 |



| `graph_ablation_delta_exact_match` | ok | **0.000** | 301 | n_pairs=301, pairing_coverage=0.858, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=0, ci_upper=0, delta_comparison_query=0, n_pairs_comparison_query=123, delta_temporal_query=0, n_pairs_temporal_query=77, delta_inference_query=0, n_pairs_inference_query=101 |



| `graph_ablation_delta_f1` | ok | **-0.000** | 301 | n_pairs=301, pairing_coverage=0.858, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.001, ci_upper=0.001, delta_comparison_query=-0.001, n_pairs_comparison_query=123, delta_temporal_query=-0.000, n_pairs_temporal_query=77, delta_inference_query=0.000, n_pairs_inference_query=101 |



| `graph_ablation_delta_context_precision` | ok | **-0.005** | 301 | n_pairs=301, pairing_coverage=0.858, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.016, ci_upper=0.006, delta_comparison_query=0.002, n_pairs_comparison_query=123, delta_temporal_query=-0.010, n_pairs_temporal_query=77, delta_inference_query=-0.010, n_pairs_inference_query=101 |



| `graph_ablation_delta_ranking_quality` | ok | **-0.038** | 301 | n_pairs=301, pairing_coverage=0.858, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.063, ci_upper=-0.012, delta_comparison_query=-0.036, n_pairs_comparison_query=123, delta_temporal_query=-0.038, n_pairs_temporal_query=77, delta_inference_query=-0.040, n_pairs_inference_query=101 |



| `graph_ablation_latency_delta` | ok | **356.7** | 301 | n_pairs=301, pairing_coverage=0.858, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-30.003, ci_upper=774.764, delta_comparison_query=404.358, n_pairs_comparison_query=123, delta_temporal_query=127.844, n_pairs_temporal_query=77, delta_inference_query=473.228, n_pairs_inference_query=101 |



| `graph_ablation_prompt_token_delta` | ok | **198.4** | 301 | n_pairs=301, pairing_coverage=0.858, n_answerable_in_sample=308, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=175.056, ci_upper=222.525, delta_comparison_query=221.886, n_pairs_comparison_query=123, delta_temporal_query=236.610, n_pairs_temporal_query=77, delta_inference_query=140.752, n_pairs_inference_query=101 |



| `abstention_on_unanswerable` | ok | **0.953** | 43 | null_samples=43, excluded_payload_records=0 |



| `null_abstention_correctness` | ok | **0.953** | 43 | null_samples=43, excluded_payload_records=0 |



| `wire_contract_conformance` | ok | **1.000** | 1404 | n_journal=1404, conforming_n=1404, violations_n=0, unparseable_n=0, contradiction_n=0, ci_lower=0.997, ci_upper=1.000 |



| `community_summary_quality` | skipped | — | 0 | Deferred to Phase 999.1 (community summaries not yet implemented in engine) |



| `run_traceability` | ok | **0.991** | 1404 | traced_records=1392, total_records=1404 |



| `p4_size` | ok | **296.000** | 296 | coverage=0.961, n_heldout_g=308, n_heldout_null=43, excluded_own_failure__dense_only=5, excluded_provenance__dense_only=0, excluded_other_arm_failure__dense_only=7, pairwise_join_size__dense_only=298, excluded_own_failure__bm25_only=0, excluded_provenance__bm25_only=0, excluded_other_arm_failure__bm25_only=12, pairwise_join_size__bm25_only=303, excluded_own_failure__hybrid=5, excluded_provenance__hybrid=0, excluded_other_arm_failure__hybrid=7, excluded_own_failure__hybrid_graph=2, excluded_provenance__hybrid_graph=0, excluded_other_arm_failure__hybrid_graph=10, pairwise_join_size__hybrid_graph=301 |



| `arm_provenance_conformance` | ok | **1.000** | 1404 | code_a=0, code_b=0, code_c=0, code_d=0, code_e=10, code_f=0, code_g=0, records_checked=1404, records_failing_zero_tolerance=0 |



| `paper_hits_at_4__dense_only` | ok | **0.740** | 296 | n_excluded=12, n_unscorable=0, successes=219, ci_lower=0.687, ci_upper=0.787, type_comparison_query_n=121, type_comparison_query_value=0.802, type_comparison_query_ci_lower=0.722, type_comparison_query_ci_upper=0.863, type_inference_query_n=99, type_inference_query_value=0.778, type_inference_query_ci_lower=0.686, type_inference_query_ci_upper=0.848, type_temporal_query_n=76, type_temporal_query_value=0.592, type_temporal_query_ci_lower=0.480, type_temporal_query_ci_upper=0.696 |



| `paper_hits_at_4__bm25_only` | ok | **0.564** | 296 | n_excluded=12, n_unscorable=0, successes=167, ci_lower=0.507, ci_upper=0.619, type_comparison_query_n=121, type_comparison_query_value=0.570, type_comparison_query_ci_lower=0.481, type_comparison_query_ci_upper=0.655, type_inference_query_n=99, type_inference_query_value=0.586, type_inference_query_ci_lower=0.487, type_inference_query_ci_upper=0.678, type_temporal_query_n=76, type_temporal_query_value=0.526, type_temporal_query_ci_lower=0.416, type_temporal_query_ci_upper=0.635 |



| `paper_hits_at_4__hybrid` | ok | **0.689** | 296 | n_excluded=12, n_unscorable=0, successes=204, ci_lower=0.634, ci_upper=0.739, type_comparison_query_n=121, type_comparison_query_value=0.719, type_comparison_query_ci_lower=0.633, type_comparison_query_ci_upper=0.791, type_inference_query_n=99, type_inference_query_value=0.768, type_inference_query_ci_lower=0.675, type_inference_query_ci_upper=0.840, type_temporal_query_n=76, type_temporal_query_value=0.539, type_temporal_query_ci_lower=0.428, type_temporal_query_ci_upper=0.647 |



| `paper_hits_at_4__hybrid_graph` | ok | **0.679** | 296 | n_excluded=12, n_unscorable=0, successes=201, ci_lower=0.624, ci_upper=0.730, type_comparison_query_n=121, type_comparison_query_value=0.719, type_comparison_query_ci_lower=0.633, type_comparison_query_ci_upper=0.791, type_inference_query_n=99, type_inference_query_value=0.747, type_inference_query_ci_lower=0.654, type_inference_query_ci_upper=0.823, type_temporal_query_n=76, type_temporal_query_value=0.526, type_temporal_query_ci_lower=0.416, type_temporal_query_ci_upper=0.635 |



| `paper_hits_at_10__dense_only` | ok | **0.851** | 296 | n_excluded=12, n_unscorable=0, successes=252, ci_lower=0.806, ci_upper=0.887, type_comparison_query_n=121, type_comparison_query_value=0.901, type_comparison_query_ci_lower=0.835, type_comparison_query_ci_upper=0.942, type_inference_query_n=99, type_inference_query_value=0.869, type_inference_query_ci_lower=0.788, type_inference_query_ci_upper=0.922, type_temporal_query_n=76, type_temporal_query_value=0.750, type_temporal_query_ci_lower=0.642, type_temporal_query_ci_upper=0.834 |



| `paper_hits_at_10__bm25_only` | ok | **0.676** | 296 | n_excluded=12, n_unscorable=0, successes=200, ci_lower=0.620, ci_upper=0.726, type_comparison_query_n=121, type_comparison_query_value=0.719, type_comparison_query_ci_lower=0.633, type_comparison_query_ci_upper=0.791, type_inference_query_n=99, type_inference_query_value=0.657, type_inference_query_ci_lower=0.559, type_inference_query_ci_upper=0.743, type_temporal_query_n=76, type_temporal_query_value=0.632, type_temporal_query_ci_lower=0.519, type_temporal_query_ci_upper=0.731 |



| `paper_hits_at_10__hybrid` | ok | **0.831** | 296 | n_excluded=12, n_unscorable=0, successes=246, ci_lower=0.784, ci_upper=0.869, type_comparison_query_n=121, type_comparison_query_value=0.876, type_comparison_query_ci_lower=0.806, type_comparison_query_ci_upper=0.923, type_inference_query_n=99, type_inference_query_value=0.859, type_inference_query_ci_lower=0.777, type_inference_query_ci_upper=0.914, type_temporal_query_n=76, type_temporal_query_value=0.724, type_temporal_query_ci_lower=0.614, type_temporal_query_ci_upper=0.812 |



| `paper_hits_at_10__hybrid_graph` | ok | **0.811** | 296 | n_excluded=12, n_unscorable=0, successes=240, ci_lower=0.762, ci_upper=0.851, type_comparison_query_n=121, type_comparison_query_value=0.868, type_comparison_query_ci_lower=0.796, type_comparison_query_ci_upper=0.917, type_inference_query_n=99, type_inference_query_value=0.848, type_inference_query_ci_lower=0.765, type_inference_query_ci_upper=0.906, type_temporal_query_n=76, type_temporal_query_value=0.671, type_temporal_query_ci_lower=0.559, type_temporal_query_ci_upper=0.766 |



| `paper_hits_at_10_delta__dense_only` | ok | **0.020** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.017, ci_upper=0.057, n_pairs=296, mean_x=0.851, mean_hybrid=0.831, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.025, type_comparison_query_ci_lower=-0.033, type_comparison_query_ci_upper=0.083, type_inference_query_n_pairs=99, type_inference_query_delta=0.010, type_inference_query_ci_lower=-0.040, type_inference_query_ci_upper=0.061, type_temporal_query_n_pairs=76, type_temporal_query_delta=0.026, type_temporal_query_ci_lower=-0.053, type_temporal_query_ci_upper=0.105 |



| `paper_hits_at_10_delta__bm25_only` | ok | **-0.155** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.203, ci_upper=-0.111, n_pairs=296, mean_x=0.676, mean_hybrid=0.831, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.157, type_comparison_query_ci_lower=-0.223, type_comparison_query_ci_upper=-0.091, type_inference_query_n_pairs=99, type_inference_query_delta=-0.202, type_inference_query_ci_lower=-0.283, type_inference_query_ci_upper=-0.121, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.092, type_temporal_query_ci_lower=-0.197, type_temporal_query_ci_upper=0 |



| `paper_hits_at_10_delta__hybrid_graph` | ok | **-0.020** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.041, ci_upper=-0.003, n_pairs=296, mean_x=0.811, mean_hybrid=0.831, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.008, type_comparison_query_ci_lower=-0.041, type_comparison_query_ci_upper=0.017, type_inference_query_n_pairs=99, type_inference_query_delta=-0.010, type_inference_query_ci_lower=-0.030, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.053, type_temporal_query_ci_lower=-0.105, type_temporal_query_ci_upper=-0.013 |



| `paper_mrr_at_10__dense_only` | ok | **0.562** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.517, ci_upper=0.607, type_comparison_query_n=121, type_comparison_query_value=0.637, type_comparison_query_ci_lower=0.568, type_comparison_query_ci_upper=0.705, type_inference_query_n=99, type_inference_query_value=0.556, type_inference_query_ci_lower=0.482, type_inference_query_ci_upper=0.632, type_temporal_query_n=76, type_temporal_query_value=0.450, type_temporal_query_ci_lower=0.361, type_temporal_query_ci_upper=0.544 |



| `paper_mrr_at_10__bm25_only` | ok | **0.456** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.407, ci_upper=0.505, type_comparison_query_n=121, type_comparison_query_value=0.485, type_comparison_query_ci_lower=0.408, type_comparison_query_ci_upper=0.563, type_inference_query_n=99, type_inference_query_value=0.462, type_inference_query_ci_lower=0.378, type_inference_query_ci_upper=0.548, type_temporal_query_n=76, type_temporal_query_value=0.404, type_temporal_query_ci_lower=0.310, type_temporal_query_ci_upper=0.501 |



| `paper_mrr_at_10__hybrid` | ok | **0.572** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.523, ci_upper=0.618, type_comparison_query_n=121, type_comparison_query_value=0.589, type_comparison_query_ci_lower=0.516, type_comparison_query_ci_upper=0.663, type_inference_query_n=99, type_inference_query_value=0.643, type_inference_query_ci_lower=0.563, type_inference_query_ci_upper=0.722, type_temporal_query_n=76, type_temporal_query_value=0.452, type_temporal_query_ci_lower=0.355, type_temporal_query_ci_upper=0.550 |



| `paper_mrr_at_10__hybrid_graph` | ok | **0.536** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.488, ci_upper=0.582, type_comparison_query_n=121, type_comparison_query_value=0.560, type_comparison_query_ci_lower=0.489, type_comparison_query_ci_upper=0.632, type_inference_query_n=99, type_inference_query_value=0.601, type_inference_query_ci_lower=0.522, type_inference_query_ci_upper=0.681, type_temporal_query_n=76, type_temporal_query_value=0.414, type_temporal_query_ci_lower=0.318, type_temporal_query_ci_upper=0.507 |



| `paper_mrr_at_10_delta__dense_only` | ok | **-0.010** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.049, ci_upper=0.032, n_pairs=296, mean_x=0.562, mean_hybrid=0.572, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.048, type_comparison_query_ci_lower=-0.022, type_comparison_query_ci_upper=0.119, type_inference_query_n_pairs=99, type_inference_query_delta=-0.087, type_inference_query_ci_lower=-0.155, type_inference_query_ci_upper=-0.016, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.002, type_temporal_query_ci_lower=-0.059, type_temporal_query_ci_upper=0.056 |



| `paper_mrr_at_10_delta__bm25_only` | ok | **-0.116** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.154, ci_upper=-0.078, n_pairs=296, mean_x=0.456, mean_hybrid=0.572, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.104, type_comparison_query_ci_lower=-0.157, type_comparison_query_ci_upper=-0.052, type_inference_query_n_pairs=99, type_inference_query_delta=-0.181, type_inference_query_ci_lower=-0.257, type_inference_query_ci_upper=-0.106, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.048, type_temporal_query_ci_lower=-0.113, type_temporal_query_ci_upper=0.018 |



| `paper_mrr_at_10_delta__hybrid_graph` | ok | **-0.036** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.061, ci_upper=-0.010, n_pairs=296, mean_x=0.536, mean_hybrid=0.572, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.029, type_comparison_query_ci_lower=-0.075, type_comparison_query_ci_upper=0.014, type_inference_query_n_pairs=99, type_inference_query_delta=-0.042, type_inference_query_ci_lower=-0.082, type_inference_query_ci_upper=-0.003, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.038, type_temporal_query_ci_lower=-0.082, type_temporal_query_ci_upper=0.004 |



| `paper_map_at_10__dense_only` | ok | **0.274** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.250, ci_upper=0.298, type_comparison_query_n=121, type_comparison_query_value=0.355, type_comparison_query_ci_lower=0.314, type_comparison_query_ci_upper=0.397, type_inference_query_n=99, type_inference_query_value=0.219, type_inference_query_ci_lower=0.187, type_inference_query_ci_upper=0.252, type_temporal_query_n=76, type_temporal_query_value=0.218, type_temporal_query_ci_lower=0.171, type_temporal_query_ci_upper=0.269 |



| `paper_map_at_10__bm25_only` | ok | **0.214** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.189, ci_upper=0.239, type_comparison_query_n=121, type_comparison_query_value=0.254, type_comparison_query_ci_lower=0.213, type_comparison_query_ci_upper=0.296, type_inference_query_n=99, type_inference_query_value=0.178, type_inference_query_ci_lower=0.142, type_inference_query_ci_upper=0.217, type_temporal_query_n=76, type_temporal_query_value=0.197, type_temporal_query_ci_lower=0.147, type_temporal_query_ci_upper=0.249 |



| `paper_map_at_10__hybrid` | ok | **0.276** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.251, ci_upper=0.302, type_comparison_query_n=121, type_comparison_query_value=0.329, type_comparison_query_ci_lower=0.286, type_comparison_query_ci_upper=0.373, type_inference_query_n=99, type_inference_query_value=0.250, type_inference_query_ci_lower=0.215, type_inference_query_ci_upper=0.287, type_temporal_query_n=76, type_temporal_query_value=0.226, type_temporal_query_ci_lower=0.174, type_temporal_query_ci_upper=0.281 |



| `paper_map_at_10__hybrid_graph` | ok | **0.259** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.234, ci_upper=0.284, type_comparison_query_n=121, type_comparison_query_value=0.314, type_comparison_query_ci_lower=0.270, type_comparison_query_ci_upper=0.358, type_inference_query_n=99, type_inference_query_value=0.236, type_inference_query_ci_lower=0.201, type_inference_query_ci_upper=0.272, type_temporal_query_n=76, type_temporal_query_value=0.202, type_temporal_query_ci_lower=0.154, type_temporal_query_ci_upper=0.251 |



| `paper_map_at_10_delta__dense_only` | ok | **-0.002** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.021, ci_upper=0.018, n_pairs=296, mean_x=0.274, mean_hybrid=0.276, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.026, type_comparison_query_ci_lower=-0.012, type_comparison_query_ci_upper=0.065, type_inference_query_n_pairs=99, type_inference_query_delta=-0.032, type_inference_query_ci_lower=-0.058, type_inference_query_ci_upper=-0.004, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.007, type_temporal_query_ci_lower=-0.033, type_temporal_query_ci_upper=0.018 |



| `paper_map_at_10_delta__bm25_only` | ok | **-0.062** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.079, ci_upper=-0.046, n_pairs=296, mean_x=0.214, mean_hybrid=0.276, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.075, type_comparison_query_ci_lower=-0.103, type_comparison_query_ci_upper=-0.048, type_inference_query_n_pairs=99, type_inference_query_delta=-0.072, type_inference_query_ci_lower=-0.099, type_inference_query_ci_upper=-0.045, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.029, type_temporal_query_ci_lower=-0.058, type_temporal_query_ci_upper=-0.000 |



| `paper_map_at_10_delta__hybrid_graph` | ok | **-0.017** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.030, ci_upper=-0.005, n_pairs=296, mean_x=0.259, mean_hybrid=0.276, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.016, type_comparison_query_ci_lower=-0.039, type_comparison_query_ci_upper=0.007, type_inference_query_n_pairs=99, type_inference_query_delta=-0.014, type_inference_query_ci_lower=-0.028, type_inference_query_ci_upper=-0.001, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.024, type_temporal_query_ci_lower=-0.050, type_temporal_query_ci_upper=-0.000 |



| `answer_usable_p4__dense_only` | ok | **0.581** | 296 | n_excluded=12, n_unscorable=0, usable_blank_answer_count=0, successes=172, ci_lower=0.524, ci_upper=0.636, type_comparison_query_n=121, type_comparison_query_value=0.537, type_comparison_query_ci_lower=0.449, type_comparison_query_ci_upper=0.624, type_inference_query_n=99, type_inference_query_value=0.939, type_inference_query_ci_lower=0.874, type_inference_query_ci_upper=0.972, type_temporal_query_n=76, type_temporal_query_value=0.184, type_temporal_query_ci_lower=0.113, type_temporal_query_ci_upper=0.286, type_comparison_query_constant_yes_baseline=0.645, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.487 |



| `answer_usable_p4__bm25_only` | ok | **0.392** | 296 | n_excluded=12, n_unscorable=0, usable_blank_answer_count=0, successes=116, ci_lower=0.338, ci_upper=0.449, type_comparison_query_n=121, type_comparison_query_value=0.231, type_comparison_query_ci_lower=0.165, type_comparison_query_ci_upper=0.314, type_inference_query_n=99, type_inference_query_value=0.758, type_inference_query_ci_lower=0.665, type_inference_query_ci_upper=0.831, type_temporal_query_n=76, type_temporal_query_value=0.171, type_temporal_query_ci_lower=0.103, type_temporal_query_ci_upper=0.271, type_comparison_query_constant_yes_baseline=0.645, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.487 |



| `answer_usable_p4__hybrid` | ok | **0.571** | 296 | n_excluded=12, n_unscorable=0, usable_blank_answer_count=0, successes=169, ci_lower=0.514, ci_upper=0.626, type_comparison_query_n=121, type_comparison_query_value=0.455, type_comparison_query_ci_lower=0.369, type_comparison_query_ci_upper=0.543, type_inference_query_n=99, type_inference_query_value=0.960, type_inference_query_ci_lower=0.901, type_inference_query_ci_upper=0.984, type_temporal_query_n=76, type_temporal_query_value=0.250, type_temporal_query_ci_lower=0.166, type_temporal_query_ci_upper=0.358, type_comparison_query_constant_yes_baseline=0.645, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.487 |



| `answer_usable_p4__hybrid_graph` | ok | **0.561** | 296 | n_excluded=12, n_unscorable=0, usable_blank_answer_count=0, successes=166, ci_lower=0.504, ci_upper=0.616, type_comparison_query_n=121, type_comparison_query_value=0.455, type_comparison_query_ci_lower=0.369, type_comparison_query_ci_upper=0.543, type_inference_query_n=99, type_inference_query_value=0.960, type_inference_query_ci_lower=0.901, type_inference_query_ci_upper=0.984, type_temporal_query_n=76, type_temporal_query_value=0.211, type_temporal_query_ci_lower=0.134, type_temporal_query_ci_upper=0.315, type_comparison_query_constant_yes_baseline=0.645, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.487 |



| `abstention_rate_g__dense_only` | ok | **0.355** | 296 | n_excluded=12, n_unscorable=0, successes=105, ci_lower=0.302, ci_upper=0.411, type_comparison_query_n=121, type_comparison_query_value=0.364, type_comparison_query_ci_lower=0.283, type_comparison_query_ci_upper=0.452, type_inference_query_n=99, type_inference_query_value=0.051, type_inference_query_ci_lower=0.022, type_inference_query_ci_upper=0.113, type_temporal_query_n=76, type_temporal_query_value=0.737, type_temporal_query_ci_lower=0.628, type_temporal_query_ci_upper=0.823 |



| `abstention_rate_g__bm25_only` | ok | **0.554** | 296 | n_excluded=12, n_unscorable=0, successes=164, ci_lower=0.497, ci_upper=0.610, type_comparison_query_n=121, type_comparison_query_value=0.661, type_comparison_query_ci_lower=0.573, type_comparison_query_ci_upper=0.739, type_inference_query_n=99, type_inference_query_value=0.242, type_inference_query_ci_lower=0.169, type_inference_query_ci_upper=0.335, type_temporal_query_n=76, type_temporal_query_value=0.789, type_temporal_query_ci_lower=0.685, type_temporal_query_ci_upper=0.866 |



| `abstention_rate_g__hybrid` | ok | **0.382** | 296 | n_excluded=12, n_unscorable=0, successes=113, ci_lower=0.328, ci_upper=0.438, type_comparison_query_n=121, type_comparison_query_value=0.463, type_comparison_query_ci_lower=0.376, type_comparison_query_ci_upper=0.551, type_inference_query_n=99, type_inference_query_value=0.040, type_inference_query_ci_lower=0.016, type_inference_query_ci_upper=0.099, type_temporal_query_n=76, type_temporal_query_value=0.697, type_temporal_query_ci_lower=0.587, type_temporal_query_ci_upper=0.789 |



| `abstention_rate_g__hybrid_graph` | ok | **0.402** | 296 | n_excluded=12, n_unscorable=0, successes=119, ci_lower=0.348, ci_upper=0.459, type_comparison_query_n=121, type_comparison_query_value=0.471, type_comparison_query_ci_lower=0.384, type_comparison_query_ci_upper=0.560, type_inference_query_n=99, type_inference_query_value=0.040, type_inference_query_ci_lower=0.016, type_inference_query_ci_upper=0.099, type_temporal_query_n=76, type_temporal_query_value=0.763, type_temporal_query_ci_lower=0.656, type_temporal_query_ci_upper=0.845 |



| `abstention_rate_g_delta__dense_only` | ok | **-0.027** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.074, ci_upper=0.024, n_pairs=296, mean_x=0.355, mean_hybrid=0.382, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.099, type_comparison_query_ci_lower=-0.198, type_comparison_query_ci_upper=-0.008, type_inference_query_n_pairs=99, type_inference_query_delta=0.010, type_inference_query_ci_lower=-0.020, type_inference_query_ci_upper=0.051, type_temporal_query_n_pairs=76, type_temporal_query_delta=0.039, type_temporal_query_ci_lower=-0.066, type_temporal_query_ci_upper=0.145 |



| `abstention_rate_g_delta__bm25_only` | ok | **0.172** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.122, ci_upper=0.226, n_pairs=296, mean_x=0.554, mean_hybrid=0.382, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.198, type_comparison_query_ci_lower=0.099, type_comparison_query_ci_upper=0.289, type_inference_query_n_pairs=99, type_inference_query_delta=0.202, type_inference_query_ci_lower=0.121, type_inference_query_ci_upper=0.293, type_temporal_query_n_pairs=76, type_temporal_query_delta=0.092, type_temporal_query_ci_lower=0.013, type_temporal_query_ci_upper=0.184 |



| `abstention_rate_g_delta__hybrid_graph` | ok | **0.020** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.020, ci_upper=0.061, n_pairs=296, mean_x=0.402, mean_hybrid=0.382, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.008, type_comparison_query_ci_lower=-0.074, type_comparison_query_ci_upper=0.091, type_inference_query_n_pairs=99, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=76, type_temporal_query_delta=0.066, type_temporal_query_ci_lower=-0.013, type_temporal_query_ci_upper=0.158 |



| `final_answer_em__dense_only` | ok | **0.561** | 296 | n_excluded=12, n_unscorable=0, successes=166, ci_lower=0.504, ci_upper=0.616, type_comparison_query_n=121, type_comparison_query_value=0.496, type_comparison_query_ci_lower=0.408, type_comparison_query_ci_upper=0.584, type_inference_query_n=99, type_inference_query_value=0.929, type_inference_query_ci_lower=0.861, type_inference_query_ci_upper=0.965, type_temporal_query_n=76, type_temporal_query_value=0.184, type_temporal_query_ci_lower=0.113, type_temporal_query_ci_upper=0.286 |



| `final_answer_em__bm25_only` | ok | **0.382** | 296 | n_excluded=12, n_unscorable=0, successes=113, ci_lower=0.328, ci_upper=0.438, type_comparison_query_n=121, type_comparison_query_value=0.223, type_comparison_query_ci_lower=0.158, type_comparison_query_ci_upper=0.305, type_inference_query_n=99, type_inference_query_value=0.747, type_inference_query_ci_lower=0.654, type_inference_query_ci_upper=0.823, type_temporal_query_n=76, type_temporal_query_value=0.158, type_temporal_query_ci_lower=0.093, type_temporal_query_ci_upper=0.256 |



| `final_answer_em__hybrid` | ok | **0.557** | 296 | n_excluded=12, n_unscorable=0, successes=165, ci_lower=0.500, ci_upper=0.613, type_comparison_query_n=121, type_comparison_query_value=0.438, type_comparison_query_ci_lower=0.353, type_comparison_query_ci_upper=0.527, type_inference_query_n=99, type_inference_query_value=0.949, type_inference_query_ci_lower=0.887, type_inference_query_ci_upper=0.978, type_temporal_query_n=76, type_temporal_query_value=0.237, type_temporal_query_ci_lower=0.155, type_temporal_query_ci_upper=0.344 |



| `final_answer_em__hybrid_graph` | ok | **0.557** | 296 | n_excluded=12, n_unscorable=0, successes=165, ci_lower=0.500, ci_upper=0.613, type_comparison_query_n=121, type_comparison_query_value=0.455, type_comparison_query_ci_lower=0.369, type_comparison_query_ci_upper=0.543, type_inference_query_n=99, type_inference_query_value=0.949, type_inference_query_ci_lower=0.887, type_inference_query_ci_upper=0.978, type_temporal_query_n=76, type_temporal_query_value=0.211, type_temporal_query_ci_lower=0.134, type_temporal_query_ci_upper=0.315 |



| `final_answer_em_delta__dense_only` | ok | **0.003** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.044, ci_upper=0.051, n_pairs=296, mean_x=0.561, mean_hybrid=0.557, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.058, type_comparison_query_ci_lower=-0.025, type_comparison_query_ci_upper=0.140, type_inference_query_n_pairs=99, type_inference_query_delta=-0.020, type_inference_query_ci_lower=-0.061, type_inference_query_ci_upper=0.020, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.053, type_temporal_query_ci_lower=-0.158, type_temporal_query_ci_upper=0.053 |



| `final_answer_em_delta__bm25_only` | ok | **-0.176** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.226, ci_upper=-0.128, n_pairs=296, mean_x=0.382, mean_hybrid=0.557, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.215, type_comparison_query_ci_lower=-0.298, type_comparison_query_ci_upper=-0.132, type_inference_query_n_pairs=99, type_inference_query_delta=-0.202, type_inference_query_ci_lower=-0.293, type_inference_query_ci_upper=-0.121, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.079, type_temporal_query_ci_lower=-0.158, type_temporal_query_ci_upper=0 |



| `final_answer_em_delta__hybrid_graph` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.037, ci_upper=0.037, n_pairs=296, mean_x=0.557, mean_hybrid=0.557, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.017, type_comparison_query_ci_lower=-0.058, type_comparison_query_ci_upper=0.091, type_inference_query_n_pairs=99, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.026, type_temporal_query_ci_lower=-0.105, type_temporal_query_ci_upper=0.053 |



| `gold_containment__dense_only` | ok | **0.676** | 296 | n_excluded=12, n_unscorable=0, successes=200, ci_lower=0.620, ci_upper=0.726, type_comparison_query_n=121, type_comparison_query_value=0.645, type_comparison_query_ci_lower=0.556, type_comparison_query_ci_upper=0.724, type_inference_query_n=99, type_inference_query_value=0.980, type_inference_query_ci_lower=0.929, type_inference_query_ci_upper=0.994, type_temporal_query_n=76, type_temporal_query_value=0.329, type_temporal_query_ci_lower=0.234, type_temporal_query_ci_upper=0.441 |



| `gold_containment__bm25_only` | ok | **0.557** | 296 | n_excluded=12, n_unscorable=0, successes=165, ci_lower=0.500, ci_upper=0.613, type_comparison_query_n=121, type_comparison_query_value=0.430, type_comparison_query_ci_lower=0.345, type_comparison_query_ci_upper=0.519, type_inference_query_n=99, type_inference_query_value=0.859, type_inference_query_ci_lower=0.777, type_inference_query_ci_upper=0.914, type_temporal_query_n=76, type_temporal_query_value=0.368, type_temporal_query_ci_lower=0.269, type_temporal_query_ci_upper=0.481 |



| `gold_containment__hybrid` | ok | **0.662** | 296 | n_excluded=12, n_unscorable=0, successes=196, ci_lower=0.607, ci_upper=0.714, type_comparison_query_n=121, type_comparison_query_value=0.579, type_comparison_query_ci_lower=0.489, type_comparison_query_ci_upper=0.663, type_inference_query_n=99, type_inference_query_value=0.990, type_inference_query_ci_lower=0.945, type_inference_query_ci_upper=0.998, type_temporal_query_n=76, type_temporal_query_value=0.368, type_temporal_query_ci_lower=0.269, type_temporal_query_ci_upper=0.481 |



| `gold_containment__hybrid_graph` | ok | **0.645** | 296 | n_excluded=12, n_unscorable=0, successes=191, ci_lower=0.589, ci_upper=0.698, type_comparison_query_n=121, type_comparison_query_value=0.545, type_comparison_query_ci_lower=0.457, type_comparison_query_ci_upper=0.631, type_inference_query_n=99, type_inference_query_value=0.980, type_inference_query_ci_lower=0.929, type_inference_query_ci_upper=0.994, type_temporal_query_n=76, type_temporal_query_value=0.368, type_temporal_query_ci_lower=0.269, type_temporal_query_ci_upper=0.481 |



| `gold_containment_delta__dense_only` | ok | **0.014** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.034, ci_upper=0.061, n_pairs=296, mean_x=0.676, mean_hybrid=0.662, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.066, type_comparison_query_ci_lower=-0.025, type_comparison_query_ci_upper=0.157, type_inference_query_n_pairs=99, type_inference_query_delta=-0.010, type_inference_query_ci_lower=-0.030, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.039, type_temporal_query_ci_lower=-0.158, type_temporal_query_ci_upper=0.079 |



| `gold_containment_delta__bm25_only` | ok | **-0.105** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.159, ci_upper=-0.054, n_pairs=296, mean_x=0.557, mean_hybrid=0.662, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.149, type_comparison_query_ci_lower=-0.240, type_comparison_query_ci_upper=-0.066, type_inference_query_n_pairs=99, type_inference_query_delta=-0.131, type_inference_query_ci_lower=-0.202, type_inference_query_ci_upper=-0.071, type_temporal_query_n_pairs=76, type_temporal_query_delta=0, type_temporal_query_ci_lower=-0.118, type_temporal_query_ci_upper=0.118 |



| `gold_containment_delta__hybrid_graph` | ok | **-0.017** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.057, ci_upper=0.020, n_pairs=296, mean_x=0.645, mean_hybrid=0.662, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.033, type_comparison_query_ci_lower=-0.107, type_comparison_query_ci_upper=0.041, type_inference_query_n_pairs=99, type_inference_query_delta=-0.010, type_inference_query_ci_lower=-0.030, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=76, type_temporal_query_delta=0, type_temporal_query_ci_lower=-0.092, type_temporal_query_ci_upper=0.092 |



| `final_answer_missing_rate__dense_only` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.013, type_comparison_query_n=121, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.031, type_inference_query_n=99, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.037, type_temporal_query_n=76, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.048 |



| `final_answer_missing_rate__bm25_only` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.013, type_comparison_query_n=121, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.031, type_inference_query_n=99, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.037, type_temporal_query_n=76, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.048 |



| `final_answer_missing_rate__hybrid` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.013, type_comparison_query_n=121, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.031, type_inference_query_n=99, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.037, type_temporal_query_n=76, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.048 |



| `final_answer_missing_rate__hybrid_graph` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, successes=0, ci_lower=0, ci_upper=0.013, type_comparison_query_n=121, type_comparison_query_value=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0.031, type_inference_query_n=99, type_inference_query_value=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0.037, type_temporal_query_n=76, type_temporal_query_value=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0.048 |



| `final_answer_missing_rate_delta__dense_only` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=296, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=121, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=99, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=76, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `final_answer_missing_rate_delta__bm25_only` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=296, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=121, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=99, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=76, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `final_answer_missing_rate_delta__hybrid_graph` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0, ci_upper=0, n_pairs=296, mean_x=0, mean_hybrid=0, count_x=0, count_hybrid=0, count_delta=0, type_comparison_query_n_pairs=121, type_comparison_query_delta=0, type_comparison_query_ci_lower=0, type_comparison_query_ci_upper=0, type_inference_query_n_pairs=99, type_inference_query_delta=0, type_inference_query_ci_lower=0, type_inference_query_ci_upper=0, type_temporal_query_n_pairs=76, type_temporal_query_delta=0, type_temporal_query_ci_lower=0, type_temporal_query_ci_upper=0 |



| `coverage_at_4__dense_only` | ok | **0.372** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.339, ci_upper=0.405, type_comparison_query_n=121, type_comparison_query_value=0.479, type_comparison_query_ci_lower=0.424, type_comparison_query_ci_upper=0.534, type_inference_query_n=99, type_inference_query_value=0.298, type_inference_query_ci_lower=0.258, type_inference_query_ci_upper=0.338, type_temporal_query_n=76, type_temporal_query_value=0.298, type_temporal_query_ci_lower=0.232, type_temporal_query_ci_upper=0.366 |



| `coverage_at_4__bm25_only` | ok | **0.263** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.233, ci_upper=0.294, type_comparison_query_n=121, type_comparison_query_value=0.295, type_comparison_query_ci_lower=0.245, type_comparison_query_ci_upper=0.344, type_inference_query_n=99, type_inference_query_value=0.225, type_inference_query_ci_lower=0.180, type_inference_query_ci_upper=0.272, type_temporal_query_n=76, type_temporal_query_value=0.263, type_temporal_query_ci_lower=0.197, type_temporal_query_ci_upper=0.331 |



| `coverage_at_4__hybrid` | ok | **0.358** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.323, ci_upper=0.392, type_comparison_query_n=121, type_comparison_query_value=0.419, type_comparison_query_ci_lower=0.362, type_comparison_query_ci_upper=0.475, type_inference_query_n=99, type_inference_query_value=0.327, type_inference_query_ci_lower=0.278, type_inference_query_ci_upper=0.380, type_temporal_query_n=76, type_temporal_query_value=0.300, type_temporal_query_ci_lower=0.230, type_temporal_query_ci_upper=0.375 |



| `coverage_at_4__hybrid_graph` | ok | **0.354** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.320, ci_upper=0.390, type_comparison_query_n=121, type_comparison_query_value=0.431, type_comparison_query_ci_lower=0.372, type_comparison_query_ci_upper=0.492, type_inference_query_n=99, type_inference_query_value=0.313, type_inference_query_ci_lower=0.264, type_inference_query_ci_upper=0.365, type_temporal_query_n=76, type_temporal_query_value=0.285, type_temporal_query_ci_lower=0.215, type_temporal_query_ci_upper=0.360 |



| `coverage_at_4_delta__dense_only` | ok | **0.014** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.017, ci_upper=0.046, n_pairs=296, mean_x=0.372, mean_hybrid=0.358, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.061, type_comparison_query_ci_lower=0.003, type_comparison_query_ci_upper=0.117, type_inference_query_n_pairs=99, type_inference_query_delta=-0.029, type_inference_query_ci_lower=-0.069, type_inference_query_ci_upper=0.011, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.002, type_temporal_query_ci_lower=-0.059, type_temporal_query_ci_upper=0.057 |



| `coverage_at_4_delta__bm25_only` | ok | **-0.095** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.122, ci_upper=-0.068, n_pairs=296, mean_x=0.263, mean_hybrid=0.358, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.124, type_comparison_query_ci_lower=-0.172, type_comparison_query_ci_upper=-0.076, type_inference_query_n_pairs=99, type_inference_query_delta=-0.103, type_inference_query_ci_lower=-0.141, type_inference_query_ci_upper=-0.066, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.037, type_temporal_query_ci_lower=-0.090, type_temporal_query_ci_upper=0.011 |



| `coverage_at_4_delta__hybrid_graph` | ok | **-0.004** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.021, ci_upper=0.014, n_pairs=296, mean_x=0.354, mean_hybrid=0.358, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.012, type_comparison_query_ci_lower=-0.023, type_comparison_query_ci_upper=0.050, type_inference_query_n_pairs=99, type_inference_query_delta=-0.014, type_inference_query_ci_lower=-0.036, type_inference_query_ci_upper=0.006, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.015, type_temporal_query_ci_lower=-0.042, type_temporal_query_ci_upper=0.009 |



| `precision_at_4__dense_only` | ok | **0.226** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.208, ci_upper=0.245, type_comparison_query_n=121, type_comparison_query_value=0.258, type_comparison_query_ci_lower=0.227, type_comparison_query_ci_upper=0.287, type_inference_query_n=99, type_inference_query_value=0.225, type_inference_query_ci_lower=0.197, type_inference_query_ci_upper=0.253, type_temporal_query_n=76, type_temporal_query_value=0.178, type_temporal_query_ci_lower=0.141, type_temporal_query_ci_upper=0.217 |



| `precision_at_4__bm25_only` | ok | **0.160** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.143, ci_upper=0.177, type_comparison_query_n=121, type_comparison_query_value=0.157, type_comparison_query_ci_lower=0.130, type_comparison_query_ci_upper=0.184, type_inference_query_n=99, type_inference_query_value=0.164, type_inference_query_ci_lower=0.134, type_inference_query_ci_upper=0.194, type_temporal_query_n=76, type_temporal_query_value=0.158, type_temporal_query_ci_lower=0.122, type_temporal_query_ci_upper=0.197 |



| `precision_at_4__hybrid` | ok | **0.217** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.197, ci_upper=0.237, type_comparison_query_n=121, type_comparison_query_value=0.223, type_comparison_query_ci_lower=0.192, type_comparison_query_ci_upper=0.254, type_inference_query_n=99, type_inference_query_value=0.240, type_inference_query_ci_lower=0.207, type_inference_query_ci_upper=0.273, type_temporal_query_n=76, type_temporal_query_value=0.178, type_temporal_query_ci_lower=0.138, type_temporal_query_ci_upper=0.220 |



| `precision_at_4__hybrid_graph` | ok | **0.213** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.193, ci_upper=0.232, type_comparison_query_n=121, type_comparison_query_value=0.227, type_comparison_query_ci_lower=0.196, type_comparison_query_ci_upper=0.258, type_inference_query_n=99, type_inference_query_value=0.230, type_inference_query_ci_lower=0.197, type_inference_query_ci_upper=0.263, type_temporal_query_n=76, type_temporal_query_value=0.168, type_temporal_query_ci_lower=0.128, type_temporal_query_ci_upper=0.207 |



| `precision_at_4_delta__dense_only` | ok | **0.009** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.009, ci_upper=0.028, n_pairs=296, mean_x=0.226, mean_hybrid=0.217, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.035, type_comparison_query_ci_lower=0.004, type_comparison_query_ci_upper=0.066, type_inference_query_n_pairs=99, type_inference_query_delta=-0.015, type_inference_query_ci_lower=-0.043, type_inference_query_ci_upper=0.015, type_temporal_query_n_pairs=76, type_temporal_query_delta=0, type_temporal_query_ci_lower=-0.033, type_temporal_query_ci_upper=0.033 |



| `precision_at_4_delta__bm25_only` | ok | **-0.057** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.074, ci_upper=-0.041, n_pairs=296, mean_x=0.160, mean_hybrid=0.217, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.066, type_comparison_query_ci_lower=-0.091, type_comparison_query_ci_upper=-0.041, type_inference_query_n_pairs=99, type_inference_query_delta=-0.076, type_inference_query_ci_lower=-0.106, type_inference_query_ci_upper=-0.048, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.020, type_temporal_query_ci_lower=-0.049, type_temporal_query_ci_upper=0.010 |



| `precision_at_4_delta__hybrid_graph` | ok | **-0.004** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.015, ci_upper=0.007, n_pairs=296, mean_x=0.213, mean_hybrid=0.217, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.004, type_comparison_query_ci_lower=-0.019, type_comparison_query_ci_upper=0.025, type_inference_query_n_pairs=99, type_inference_query_delta=-0.010, type_inference_query_ci_lower=-0.025, type_inference_query_ci_upper=0.005, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.010, type_temporal_query_ci_lower=-0.026, type_temporal_query_ci_upper=0.003 |



| `prompt_tokens_mean__dense_only` | ok | **2263.1** | 296 | n_excluded=12, n_unscorable=0, ci_lower=2247.838, ci_upper=2278.216, type_comparison_query_n=121, type_comparison_query_value=2238.240, type_comparison_query_ci_lower=2212.521, type_comparison_query_ci_upper=2264.504, type_inference_query_n=99, type_inference_query_value=2285.354, type_inference_query_ci_lower=2261.768, type_inference_query_ci_upper=2307.960, type_temporal_query_n=76, type_temporal_query_value=2273.539, type_temporal_query_ci_lower=2244.211, type_temporal_query_ci_upper=2301.658 |



| `prompt_tokens_mean__bm25_only` | ok | **2218.1** | 296 | n_excluded=12, n_unscorable=0, ci_lower=2200.632, ci_upper=2235.003, type_comparison_query_n=121, type_comparison_query_value=2209.017, type_comparison_query_ci_lower=2179.760, type_comparison_query_ci_upper=2238.455, type_inference_query_n=99, type_inference_query_value=2199.828, type_inference_query_ci_lower=2172.626, type_inference_query_ci_upper=2227.141, type_temporal_query_n=76, type_temporal_query_value=2256.171, type_temporal_query_ci_lower=2223.158, type_temporal_query_ci_upper=2288.987 |



| `prompt_tokens_mean__hybrid` | ok | **2262.5** | 296 | n_excluded=12, n_unscorable=0, ci_lower=2247.135, ci_upper=2277.757, type_comparison_query_n=121, type_comparison_query_value=2247.198, type_comparison_query_ci_lower=2220.769, type_comparison_query_ci_upper=2273.347, type_inference_query_n=99, type_inference_query_value=2275.545, type_inference_query_ci_lower=2251.162, type_inference_query_ci_upper=2300.455, type_temporal_query_n=76, type_temporal_query_value=2269.908, type_temporal_query_ci_lower=2243.053, type_temporal_query_ci_upper=2296.461 |



| `prompt_tokens_mean__hybrid_graph` | ok | **2461.4** | 296 | n_excluded=12, n_unscorable=0, ci_lower=2432.584, ci_upper=2490.699, type_comparison_query_n=121, type_comparison_query_value=2467.645, type_comparison_query_ci_lower=2416.802, type_comparison_query_ci_upper=2517.083, type_inference_query_n=99, type_inference_query_value=2415.899, type_inference_query_ci_lower=2372.788, type_inference_query_ci_upper=2462.657, type_temporal_query_n=76, type_temporal_query_value=2510.592, type_temporal_query_ci_lower=2460.868, type_temporal_query_ci_upper=2562.237 |



| `prompt_tokens_delta__dense_only` | ok | **0.6** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-11.003, ci_upper=12.068, n_pairs=296, mean_x=2263.061, mean_hybrid=2262.510, type_comparison_query_n_pairs=121, type_comparison_query_delta=-8.959, type_comparison_query_ci_lower=-28.058, type_comparison_query_ci_upper=10.314, type_inference_query_n_pairs=99, type_inference_query_delta=9.808, type_inference_query_ci_lower=-11.273, type_inference_query_ci_upper=30.636, type_temporal_query_n_pairs=76, type_temporal_query_delta=3.632, type_temporal_query_ci_lower=-14.474, type_temporal_query_ci_upper=22.079 |



| `prompt_tokens_delta__bm25_only` | ok | **-44.5** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-56.622, ci_upper=-32.473, n_pairs=296, mean_x=2218.051, mean_hybrid=2262.510, type_comparison_query_n_pairs=121, type_comparison_query_delta=-38.182, type_comparison_query_ci_lower=-57.719, type_comparison_query_ci_upper=-19.050, type_inference_query_n_pairs=99, type_inference_query_delta=-75.717, type_inference_query_ci_lower=-96.545, type_inference_query_ci_upper=-54.515, type_temporal_query_n_pairs=76, type_temporal_query_delta=-13.737, type_temporal_query_ci_lower=-34.895, type_temporal_query_ci_upper=7.368 |



| `prompt_tokens_delta__hybrid_graph` | ok | **198.9** | 296 | n_excluded=12, n_unscorable=0, ci_lower=174.486, ci_upper=223.676, n_pairs=296, mean_x=2461.365, mean_hybrid=2262.510, type_comparison_query_n_pairs=121, type_comparison_query_delta=220.446, type_comparison_query_ci_lower=180, type_comparison_query_ci_upper=261.496, type_inference_query_n_pairs=99, type_inference_query_delta=140.354, type_inference_query_ci_lower=106.667, type_inference_query_ci_upper=176.566, type_temporal_query_n_pairs=76, type_temporal_query_delta=240.684, type_temporal_query_ci_lower=193.513, type_temporal_query_ci_upper=289.197 |



| `latency_total_ms_mean__dense_only` | ok | **10212.9** | 296 | n_excluded=12, n_unscorable=0, ci_lower=9878.774, ci_upper=10554.669, type_comparison_query_n=121, type_comparison_query_value=10422.727, type_comparison_query_ci_lower=9910.074, type_comparison_query_ci_upper=10933.504, type_inference_query_n=99, type_inference_query_value=10031.222, type_inference_query_ci_lower=9371.586, type_inference_query_ci_upper=10740.576, type_temporal_query_n=76, type_temporal_query_value=10115.579, type_temporal_query_ci_lower=9587, type_temporal_query_ci_upper=10659.105 |



| `latency_total_ms_mean__bm25_only` | ok | **9473.2** | 296 | n_excluded=12, n_unscorable=0, ci_lower=9182.068, ci_upper=9778.182, type_comparison_query_n=121, type_comparison_query_value=9590.595, type_comparison_query_ci_lower=9143.537, type_comparison_query_ci_upper=10058.207, type_inference_query_n=99, type_inference_query_value=9164.970, type_inference_query_ci_lower=8695.859, type_inference_query_ci_upper=9660.727, type_temporal_query_n=76, type_temporal_query_value=9687.882, type_temporal_query_ci_lower=9097.408, type_temporal_query_ci_upper=10303.171 |



| `latency_total_ms_mean__hybrid` | ok | **9945.8** | 296 | n_excluded=12, n_unscorable=0, ci_lower=9657.199, ci_upper=10242.071, type_comparison_query_n=121, type_comparison_query_value=10041.182, type_comparison_query_ci_lower=9562.091, type_comparison_query_ci_upper=10524.314, type_inference_query_n=99, type_inference_query_value=9662.051, type_inference_query_ci_lower=9189.818, type_inference_query_ci_upper=10170.677, type_temporal_query_n=76, type_temporal_query_value=10163.750, type_temporal_query_ci_lower=9634.513, type_temporal_query_ci_upper=10741.316 |



| `latency_total_ms_mean__hybrid_graph` | ok | **10350.0** | 296 | n_excluded=12, n_unscorable=0, ci_lower=9978.179, ci_upper=10776.324, type_comparison_query_n=121, type_comparison_query_value=10436.570, type_comparison_query_ci_lower=9869.438, type_comparison_query_ci_upper=11019.157, type_inference_query_n=99, type_inference_query_value=10272.384, type_inference_query_ci_lower=9524.576, type_inference_query_ci_upper=11316.354, type_temporal_query_n=76, type_temporal_query_value=10313.105, type_temporal_query_ci_lower=9825.421, type_temporal_query_ci_upper=10804.461 |



| `latency_total_ms_delta__dense_only` | ok | **267.1** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-96.324, ci_upper=640.696, n_pairs=296, mean_x=10212.922, mean_hybrid=9945.848, type_comparison_query_n_pairs=121, type_comparison_query_delta=381.545, type_comparison_query_ci_lower=-165.893, type_comparison_query_ci_upper=943.355, type_inference_query_n_pairs=99, type_inference_query_delta=369.172, type_inference_query_ci_lower=-315.283, type_inference_query_ci_upper=1104, type_temporal_query_n_pairs=76, type_temporal_query_delta=-48.171, type_temporal_query_ci_lower=-743.368, type_temporal_query_ci_upper=627.105 |



| `latency_total_ms_delta__bm25_only` | ok | **-472.6** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-814.760, ci_upper=-127.679, n_pairs=296, mean_x=9473.220, mean_hybrid=9945.848, type_comparison_query_n_pairs=121, type_comparison_query_delta=-450.587, type_comparison_query_ci_lower=-976.793, type_comparison_query_ci_upper=85.248, type_inference_query_n_pairs=99, type_inference_query_delta=-497.081, type_inference_query_ci_lower=-1104.131, type_inference_query_ci_upper=99.283, type_temporal_query_n_pairs=76, type_temporal_query_delta=-475.868, type_temporal_query_ci_lower=-1131.447, type_temporal_query_ci_upper=197.526 |



| `latency_total_ms_delta__hybrid_graph` | ok | **404.1** | 296 | n_excluded=12, n_unscorable=0, ci_lower=24.020, ci_upper=823.122, n_pairs=296, mean_x=10349.956, mean_hybrid=9945.848, type_comparison_query_n_pairs=121, type_comparison_query_delta=395.388, type_comparison_query_ci_lower=-168.471, type_comparison_query_ci_upper=961.256, type_inference_query_n_pairs=99, type_inference_query_delta=610.333, type_inference_query_ci_lower=-206, type_inference_query_ci_upper=1637.465, type_temporal_query_n_pairs=76, type_temporal_query_delta=149.355, type_temporal_query_ci_lower=-380.118, type_temporal_query_ci_upper=654.158 |



| `retrieve_node_ms_mean__dense_only` | ok | **51.905** | 296 | n_excluded=12, n_unscorable=0, ci_lower=50.774, ci_upper=53.250, type_comparison_query_n=121, type_comparison_query_value=53.289, type_comparison_query_ci_lower=51.083, type_comparison_query_ci_upper=56.314, type_inference_query_n=99, type_inference_query_value=50.283, type_inference_query_ci_lower=49.293, type_inference_query_ci_upper=51.424, type_temporal_query_n=76, type_temporal_query_value=51.816, type_temporal_query_ci_lower=49.895, type_temporal_query_ci_upper=54.342 |



| `retrieve_node_ms_mean__bm25_only` | ok | **50.368** | 296 | n_excluded=12, n_unscorable=0, ci_lower=49.030, ci_upper=51.747, type_comparison_query_n=121, type_comparison_query_value=46.430, type_comparison_query_ci_lower=44.711, type_comparison_query_ci_upper=48.331, type_inference_query_n=99, type_inference_query_value=54.566, type_inference_query_ci_lower=52.475, type_inference_query_ci_upper=56.798, type_temporal_query_n=76, type_temporal_query_value=51.171, type_temporal_query_ci_lower=48.197, type_temporal_query_ci_upper=54.329 |



| `retrieve_node_ms_mean__hybrid` | ok | **101.193** | 296 | n_excluded=12, n_unscorable=0, ci_lower=99.517, ci_upper=102.916, type_comparison_query_n=121, type_comparison_query_value=97.876, type_comparison_query_ci_lower=95.595, type_comparison_query_ci_upper=100.355, type_inference_query_n=99, type_inference_query_value=106.687, type_inference_query_ci_lower=103.828, type_inference_query_ci_upper=109.828, type_temporal_query_n=76, type_temporal_query_value=99.316, type_temporal_query_ci_lower=96.289, type_temporal_query_ci_upper=102.553 |



| `retrieve_node_ms_mean__hybrid_graph` | ok | **117.095** | 296 | n_excluded=12, n_unscorable=0, ci_lower=114.145, ci_upper=120.226, type_comparison_query_n=121, type_comparison_query_value=112.124, type_comparison_query_ci_lower=108.264, type_comparison_query_ci_upper=116.405, type_inference_query_n=99, type_inference_query_value=121.384, type_inference_query_ci_lower=116.424, type_inference_query_ci_upper=126.566, type_temporal_query_n=76, type_temporal_query_value=119.421, type_temporal_query_ci_lower=112.803, type_temporal_query_ci_upper=126.961 |



| `retrieve_node_ms_delta__dense_only` | ok | **-49.287** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-51.264, ci_upper=-47.284, n_pairs=296, mean_x=51.905, mean_hybrid=101.193, type_comparison_query_n_pairs=121, type_comparison_query_delta=-44.587, type_comparison_query_ci_lower=-47.760, type_comparison_query_ci_upper=-41.174, type_inference_query_n_pairs=99, type_inference_query_delta=-56.404, type_inference_query_ci_lower=-59.697, type_inference_query_ci_upper=-53.374, type_temporal_query_n_pairs=76, type_temporal_query_delta=-47.500, type_temporal_query_ci_lower=-50.711, type_temporal_query_ci_upper=-44.329 |



| `retrieve_node_ms_delta__bm25_only` | ok | **-50.824** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-52.476, ci_upper=-49.236, n_pairs=296, mean_x=50.368, mean_hybrid=101.193, type_comparison_query_n_pairs=121, type_comparison_query_delta=-51.446, type_comparison_query_ci_lower=-53.711, type_comparison_query_ci_upper=-49.273, type_inference_query_n_pairs=99, type_inference_query_delta=-52.121, type_inference_query_ci_lower=-55.172, type_inference_query_ci_upper=-49.323, type_temporal_query_n_pairs=76, type_temporal_query_delta=-48.145, type_temporal_query_ci_lower=-51.697, type_temporal_query_ci_upper=-44.645 |



| `retrieve_node_ms_delta__hybrid_graph` | ok | **15.902** | 296 | n_excluded=12, n_unscorable=0, ci_lower=13.128, ci_upper=18.824, n_pairs=296, mean_x=117.095, mean_hybrid=101.193, type_comparison_query_n_pairs=121, type_comparison_query_delta=14.248, type_comparison_query_ci_lower=10.306, type_comparison_query_ci_upper=18.256, type_inference_query_n_pairs=99, type_inference_query_delta=14.697, type_inference_query_ci_lower=9.980, type_inference_query_ci_upper=19.606, type_temporal_query_n_pairs=76, type_temporal_query_delta=20.105, type_temporal_query_ci_lower=13.921, type_temporal_query_ci_upper=26.921 |



| `spend_usd_mean__dense_only` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, type_comparison_query_n=121, type_comparison_query_value=0.000, type_comparison_query_ci_lower=0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n=99, type_inference_query_value=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n=76, type_temporal_query_value=0.000, type_temporal_query_ci_lower=0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_mean__bm25_only` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, type_comparison_query_n=121, type_comparison_query_value=0.000, type_comparison_query_ci_lower=0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n=99, type_inference_query_value=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n=76, type_temporal_query_value=0.000, type_temporal_query_ci_lower=0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_mean__hybrid` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, type_comparison_query_n=121, type_comparison_query_value=0.000, type_comparison_query_ci_lower=0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n=99, type_inference_query_value=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n=76, type_temporal_query_value=0.000, type_temporal_query_ci_lower=0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_mean__hybrid_graph` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, type_comparison_query_n=121, type_comparison_query_value=0.000, type_comparison_query_ci_lower=0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n=99, type_inference_query_value=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n=76, type_temporal_query_value=0.000, type_temporal_query_ci_lower=0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_delta__dense_only` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.000, ci_upper=0.000, n_pairs=296, mean_x=0.000, mean_hybrid=0.000, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.000, type_comparison_query_ci_lower=-0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n_pairs=99, type_inference_query_delta=0.000, type_inference_query_ci_lower=-0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=76, type_temporal_query_delta=0.000, type_temporal_query_ci_lower=-0.000, type_temporal_query_ci_upper=0.000 |



| `spend_usd_delta__bm25_only` | ok | **-0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=-0.000, ci_upper=-0.000, n_pairs=296, mean_x=0.000, mean_hybrid=0.000, type_comparison_query_n_pairs=121, type_comparison_query_delta=-0.000, type_comparison_query_ci_lower=-0.000, type_comparison_query_ci_upper=-0.000, type_inference_query_n_pairs=99, type_inference_query_delta=-0.000, type_inference_query_ci_lower=-0.000, type_inference_query_ci_upper=-0.000, type_temporal_query_n_pairs=76, type_temporal_query_delta=-0.000, type_temporal_query_ci_lower=-0.000, type_temporal_query_ci_upper=-0.000 |



| `spend_usd_delta__hybrid_graph` | ok | **0.000** | 296 | n_excluded=12, n_unscorable=0, ci_lower=0.000, ci_upper=0.000, n_pairs=296, mean_x=0.000, mean_hybrid=0.000, type_comparison_query_n_pairs=121, type_comparison_query_delta=0.000, type_comparison_query_ci_lower=0.000, type_comparison_query_ci_upper=0.000, type_inference_query_n_pairs=99, type_inference_query_delta=0.000, type_inference_query_ci_lower=0.000, type_inference_query_ci_upper=0.000, type_temporal_query_n_pairs=76, type_temporal_query_delta=0.000, type_temporal_query_ci_lower=0.000, type_temporal_query_ci_upper=0.000 |



| `latency_total_ms_p50__dense_only` | ok | **9966.5** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=10385, type_inference_query_n=99, type_inference_query_value=9513, type_temporal_query_n=76, type_temporal_query_value=10242.500 |



| `latency_total_ms_p95__dense_only` | ok | **15690.2** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=15618, type_inference_query_n=99, type_inference_query_value=16077.400, type_temporal_query_n=76, type_temporal_query_value=13894.750 |



| `latency_total_ms_p50__bm25_only` | ok | **9092.0** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=9123, type_inference_query_n=99, type_inference_query_value=8824, type_temporal_query_n=76, type_temporal_query_value=9403.500 |



| `latency_total_ms_p95__bm25_only` | ok | **13755.8** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=13869, type_inference_query_n=99, type_inference_query_value=13390.400, type_temporal_query_n=76, type_temporal_query_value=14244 |



| `latency_total_ms_p50__hybrid` | ok | **9566.0** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=9796, type_inference_query_n=99, type_inference_query_value=9323, type_temporal_query_n=76, type_temporal_query_value=9615.500 |



| `latency_total_ms_p95__hybrid` | ok | **14399.2** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=14526, type_inference_query_n=99, type_inference_query_value=13852.700, type_temporal_query_n=76, type_temporal_query_value=14511 |



| `latency_total_ms_p50__hybrid_graph` | ok | **9938.0** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=10180, type_inference_query_n=99, type_inference_query_value=9670, type_temporal_query_n=76, type_temporal_query_value=10119 |



| `latency_total_ms_p95__hybrid_graph` | ok | **14916.8** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=15397, type_inference_query_n=99, type_inference_query_value=14311.000, type_temporal_query_n=76, type_temporal_query_value=14509 |



| `retrieve_node_ms_p50__dense_only` | ok | **49.000** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=50, type_inference_query_n=99, type_inference_query_value=49, type_temporal_query_n=76, type_temporal_query_value=49 |



| `retrieve_node_ms_p95__dense_only` | ok | **64.000** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=66, type_inference_query_n=99, type_inference_query_value=58.300, type_temporal_query_n=76, type_temporal_query_value=64.500 |



| `retrieve_node_ms_p50__bm25_only` | ok | **48.500** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=45, type_inference_query_n=99, type_inference_query_value=53, type_temporal_query_n=76, type_temporal_query_value=50.500 |



| `retrieve_node_ms_p95__bm25_only` | ok | **73.000** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=65, type_inference_query_n=99, type_inference_query_value=77, type_temporal_query_n=76, type_temporal_query_value=73.250 |



| `retrieve_node_ms_p50__hybrid` | ok | **99.000** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=96, type_inference_query_n=99, type_inference_query_value=105, type_temporal_query_n=76, type_temporal_query_value=97 |



| `retrieve_node_ms_p95__hybrid` | ok | **126.000** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=125, type_inference_query_n=99, type_inference_query_value=130.200, type_temporal_query_n=76, type_temporal_query_value=124.500 |



| `retrieve_node_ms_p50__hybrid_graph` | ok | **115.000** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=112, type_inference_query_n=99, type_inference_query_value=121, type_temporal_query_n=76, type_temporal_query_value=117.500 |



| `retrieve_node_ms_p95__hybrid_graph` | ok | **164.250** | 296 | n_excluded=12, n_unscorable=0, type_comparison_query_n=121, type_comparison_query_value=142, type_inference_query_n=99, type_inference_query_value=166.000, type_temporal_query_n=76, type_temporal_query_value=176.500 |



| `paper_hits_at_4_script_faithful__dense_only` | ok | **0.731** | 308 | n_excluded=0, n_no_valid_ranking=5, successes=225, ci_lower=0.678, ci_upper=0.777, type_comparison_query_n=125, type_comparison_query_value=0.784, type_comparison_query_ci_lower=0.704, type_comparison_query_ci_upper=0.847, type_inference_query_n=105, type_inference_query_value=0.771, type_inference_query_ci_lower=0.682, type_inference_query_ci_upper=0.841, type_temporal_query_n=78, type_temporal_query_value=0.590, type_temporal_query_ci_lower=0.479, type_temporal_query_ci_upper=0.692 |



| `paper_hits_at_10_script_faithful__dense_only` | ok | **0.838** | 308 | n_excluded=0, n_no_valid_ranking=5, successes=258, ci_lower=0.792, ci_upper=0.875, type_comparison_query_n=125, type_comparison_query_value=0.880, type_comparison_query_ci_lower=0.811, type_comparison_query_ci_upper=0.926, type_inference_query_n=105, type_inference_query_value=0.857, type_inference_query_ci_lower=0.778, type_inference_query_ci_upper=0.911, type_temporal_query_n=78, type_temporal_query_value=0.744, type_temporal_query_ci_lower=0.637, type_temporal_query_ci_upper=0.827 |



| `paper_mrr_at_10_script_faithful__dense_only` | ok | **0.551** | 308 | n_excluded=0, n_no_valid_ranking=5, ci_lower=0.506, ci_upper=0.596, type_comparison_query_n=125, type_comparison_query_value=0.621, type_comparison_query_ci_lower=0.551, type_comparison_query_ci_upper=0.690, type_inference_query_n=105, type_inference_query_value=0.542, type_inference_query_ci_lower=0.469, type_inference_query_ci_upper=0.616, type_temporal_query_n=78, type_temporal_query_value=0.451, type_temporal_query_ci_lower=0.363, type_temporal_query_ci_upper=0.541 |



| `paper_map_at_10_script_faithful__dense_only` | ok | **0.270** | 308 | n_excluded=0, n_no_valid_ranking=5, ci_lower=0.247, ci_upper=0.295, type_comparison_query_n=125, type_comparison_query_value=0.347, type_comparison_query_ci_lower=0.306, type_comparison_query_ci_upper=0.389, type_inference_query_n=105, type_inference_query_value=0.215, type_inference_query_ci_lower=0.183, type_inference_query_ci_upper=0.247, type_temporal_query_n=78, type_temporal_query_value=0.222, type_temporal_query_ci_lower=0.174, type_temporal_query_ci_upper=0.272 |



| `paper_hits_at_4_script_faithful__bm25_only` | ok | **0.571** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=176, ci_lower=0.516, ci_upper=0.625, type_comparison_query_n=125, type_comparison_query_value=0.576, type_comparison_query_ci_lower=0.488, type_comparison_query_ci_upper=0.659, type_inference_query_n=105, type_inference_query_value=0.590, type_inference_query_ci_lower=0.495, type_inference_query_ci_upper=0.680, type_temporal_query_n=78, type_temporal_query_value=0.538, type_temporal_query_ci_lower=0.429, type_temporal_query_ci_upper=0.645 |



| `paper_hits_at_10_script_faithful__bm25_only` | ok | **0.685** | 308 | n_excluded=0, n_no_valid_ranking=0, successes=211, ci_lower=0.631, ci_upper=0.734, type_comparison_query_n=125, type_comparison_query_value=0.728, type_comparison_query_ci_lower=0.644, type_comparison_query_ci_upper=0.798, type_inference_query_n=105, type_inference_query_value=0.667, type_inference_query_ci_lower=0.572, type_inference_query_ci_upper=0.750, type_temporal_query_n=78, type_temporal_query_value=0.641, type_temporal_query_ci_lower=0.530, type_temporal_query_ci_upper=0.739 |



| `paper_mrr_at_10_script_faithful__bm25_only` | ok | **0.462** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.413, ci_upper=0.511, type_comparison_query_n=125, type_comparison_query_value=0.490, type_comparison_query_ci_lower=0.413, type_comparison_query_ci_upper=0.567, type_inference_query_n=105, type_inference_query_value=0.459, type_inference_query_ci_lower=0.378, type_inference_query_ci_upper=0.540, type_temporal_query_n=78, type_temporal_query_value=0.420, type_temporal_query_ci_lower=0.326, type_temporal_query_ci_upper=0.516 |



| `paper_map_at_10_script_faithful__bm25_only` | ok | **0.217** | 308 | n_excluded=0, n_no_valid_ranking=0, ci_lower=0.193, ci_upper=0.242, type_comparison_query_n=125, type_comparison_query_value=0.258, type_comparison_query_ci_lower=0.217, type_comparison_query_ci_upper=0.299, type_inference_query_n=105, type_inference_query_value=0.178, type_inference_query_ci_lower=0.142, type_inference_query_ci_upper=0.213, type_temporal_query_n=78, type_temporal_query_value=0.205, type_temporal_query_ci_lower=0.155, type_temporal_query_ci_upper=0.255 |



| `paper_hits_at_4_script_faithful__hybrid` | ok | **0.682** | 308 | n_excluded=0, n_no_valid_ranking=5, successes=210, ci_lower=0.628, ci_upper=0.731, type_comparison_query_n=125, type_comparison_query_value=0.720, type_comparison_query_ci_lower=0.636, type_comparison_query_ci_upper=0.791, type_inference_query_n=105, type_inference_query_value=0.743, type_inference_query_ci_lower=0.652, type_inference_query_ci_upper=0.817, type_temporal_query_n=78, type_temporal_query_value=0.538, type_temporal_query_ci_lower=0.429, type_temporal_query_ci_upper=0.645 |



| `paper_hits_at_10_script_faithful__hybrid` | ok | **0.818** | 308 | n_excluded=0, n_no_valid_ranking=5, successes=252, ci_lower=0.771, ci_upper=0.857, type_comparison_query_n=125, type_comparison_query_value=0.872, type_comparison_query_ci_lower=0.802, type_comparison_query_ci_upper=0.920, type_inference_query_n=105, type_inference_query_value=0.829, type_inference_query_ci_lower=0.745, type_inference_query_ci_upper=0.889, type_temporal_query_n=78, type_temporal_query_value=0.718, type_temporal_query_ci_lower=0.610, type_temporal_query_ci_upper=0.806 |



| `paper_mrr_at_10_script_faithful__hybrid` | ok | **0.567** | 308 | n_excluded=0, n_no_valid_ranking=5, ci_lower=0.519, ci_upper=0.614, type_comparison_query_n=125, type_comparison_query_value=0.588, type_comparison_query_ci_lower=0.516, type_comparison_query_ci_upper=0.660, type_inference_query_n=105, type_inference_query_value=0.625, type_inference_query_ci_lower=0.543, type_inference_query_ci_upper=0.703, type_temporal_query_n=78, type_temporal_query_value=0.453, type_temporal_query_ci_lower=0.358, type_temporal_query_ci_upper=0.548 |



| `paper_map_at_10_script_faithful__hybrid` | ok | **0.274** | 308 | n_excluded=0, n_no_valid_ranking=5, ci_lower=0.249, ci_upper=0.300, type_comparison_query_n=125, type_comparison_query_value=0.329, type_comparison_query_ci_lower=0.286, type_comparison_query_ci_upper=0.372, type_inference_query_n=105, type_inference_query_value=0.243, type_inference_query_ci_lower=0.208, type_inference_query_ci_upper=0.279, type_temporal_query_n=78, type_temporal_query_value=0.226, type_temporal_query_ci_lower=0.175, type_temporal_query_ci_upper=0.278 |



| `paper_hits_at_4_script_faithful__hybrid_graph` | ok | **0.679** | 308 | n_excluded=0, n_no_valid_ranking=2, successes=209, ci_lower=0.624, ci_upper=0.728, type_comparison_query_n=125, type_comparison_query_value=0.712, type_comparison_query_ci_lower=0.627, type_comparison_query_ci_upper=0.784, type_inference_query_n=105, type_inference_query_value=0.743, type_inference_query_ci_lower=0.652, type_inference_query_ci_upper=0.817, type_temporal_query_n=78, type_temporal_query_value=0.538, type_temporal_query_ci_lower=0.429, type_temporal_query_ci_upper=0.645 |



| `paper_hits_at_10_script_faithful__hybrid_graph` | ok | **0.808** | 308 | n_excluded=0, n_no_valid_ranking=2, successes=249, ci_lower=0.761, ci_upper=0.848, type_comparison_query_n=125, type_comparison_query_value=0.864, type_comparison_query_ci_lower=0.793, type_comparison_query_ci_upper=0.913, type_inference_query_n=105, type_inference_query_value=0.838, type_inference_query_ci_lower=0.756, type_inference_query_ci_upper=0.896, type_temporal_query_n=78, type_temporal_query_value=0.679, type_temporal_query_ci_lower=0.570, type_temporal_query_ci_upper=0.773 |



| `paper_mrr_at_10_script_faithful__hybrid_graph` | ok | **0.540** | 308 | n_excluded=0, n_no_valid_ranking=2, ci_lower=0.493, ci_upper=0.586, type_comparison_query_n=125, type_comparison_query_value=0.555, type_comparison_query_ci_lower=0.484, type_comparison_query_ci_upper=0.625, type_inference_query_n=105, type_inference_query_value=0.605, type_inference_query_ci_lower=0.526, type_inference_query_ci_upper=0.681, type_temporal_query_n=78, type_temporal_query_value=0.429, type_temporal_query_ci_lower=0.335, type_temporal_query_ci_upper=0.523 |



| `paper_map_at_10_script_faithful__hybrid_graph` | ok | **0.261** | 308 | n_excluded=0, n_no_valid_ranking=2, ci_lower=0.236, ci_upper=0.287, type_comparison_query_n=125, type_comparison_query_value=0.312, type_comparison_query_ci_lower=0.269, type_comparison_query_ci_upper=0.354, type_inference_query_n=105, type_inference_query_value=0.239, type_inference_query_ci_lower=0.204, type_inference_query_ci_upper=0.275, type_temporal_query_n=78, type_temporal_query_value=0.210, type_temporal_query_ci_lower=0.162, type_temporal_query_ci_upper=0.260 |



| `answer_usable_sc3_definition__dense_only` | ok | **0.587** | 303 | n_excluded=5, successes=178, ci_lower=0.531, ci_upper=0.641, type_comparison_query_n=123, type_comparison_query_value=0.537, type_comparison_query_ci_lower=0.449, type_comparison_query_ci_upper=0.622, type_inference_query_n=103, type_inference_query_value=0.942, type_inference_query_ci_lower=0.879, type_inference_query_ci_upper=0.973, type_temporal_query_n=77, type_temporal_query_value=0.195, type_temporal_query_ci_lower=0.122, type_temporal_query_ci_upper=0.297, type_comparison_query_constant_yes_baseline=0.642, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.481 |



| `answer_usable_sc3_definition__bm25_only` | ok | **0.399** | 308 | n_excluded=0, successes=123, ci_lower=0.346, ci_upper=0.455, type_comparison_query_n=125, type_comparison_query_value=0.232, type_comparison_query_ci_lower=0.167, type_comparison_query_ci_upper=0.313, type_inference_query_n=105, type_inference_query_value=0.771, type_inference_query_ci_lower=0.682, type_inference_query_ci_upper=0.841, type_temporal_query_n=78, type_temporal_query_value=0.167, type_temporal_query_ci_lower=0.100, type_temporal_query_ci_upper=0.265, type_comparison_query_constant_yes_baseline=0.640, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `answer_usable_sc3_definition__hybrid` | ok | **0.568** | 303 | n_excluded=5, successes=172, ci_lower=0.511, ci_upper=0.622, type_comparison_query_n=124, type_comparison_query_value=0.444, type_comparison_query_ci_lower=0.359, type_comparison_query_ci_upper=0.531, type_inference_query_n=102, type_inference_query_value=0.961, type_inference_query_ci_lower=0.903, type_inference_query_ci_upper=0.985, type_temporal_query_n=77, type_temporal_query_value=0.247, type_temporal_query_ci_lower=0.164, type_temporal_query_ci_upper=0.354, type_comparison_query_constant_yes_baseline=0.637, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.481 |



| `answer_usable_sc3_definition__hybrid_graph` | ok | **0.565** | 306 | n_excluded=2, successes=173, ci_lower=0.509, ci_upper=0.620, type_comparison_query_n=124, type_comparison_query_value=0.452, type_comparison_query_ci_lower=0.367, type_comparison_query_ci_upper=0.539, type_inference_query_n=104, type_inference_query_value=0.962, type_inference_query_ci_lower=0.905, type_inference_query_ci_upper=0.985, type_temporal_query_n=78, type_temporal_query_value=0.218, type_temporal_query_ci_lower=0.141, type_temporal_query_ci_upper=0.322, type_comparison_query_constant_yes_baseline=0.645, type_inference_query_constant_yes_baseline=0, type_temporal_query_constant_yes_baseline=0.474 |



| `null_abstention_correctness__dense_only` | ok | **0.930** | 43 | successes=40, ci_lower=0.814, ci_upper=0.976, n_excluded=0, hallucinated_on_null=3, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__bm25_only` | ok | **0.977** | 43 | successes=42, ci_lower=0.879, ci_upper=0.996, n_excluded=0, hallucinated_on_null=1, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__hybrid` | ok | **0.952** | 42 | successes=40, ci_lower=0.842, ci_upper=0.987, n_excluded=1, hallucinated_on_null=2, no_evidence_count=0, leak_count=0 |



| `null_abstention_correctness__hybrid_graph` | ok | **0.953** | 43 | successes=41, ci_lower=0.845, ci_upper=0.987, n_excluded=0, hallucinated_on_null=2, no_evidence_count=0, leak_count=0 |



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