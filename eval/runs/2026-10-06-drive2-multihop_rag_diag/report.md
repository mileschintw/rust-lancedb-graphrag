# Evaluation Report: multihop_rag_diag


## Run Metadata

| Parameter | Value |
|---|---|
| **Corpus** | `multihop_rag_diag` |
| **Run Date** | `2026-10-06T09:44:23.056967+00:00` |
| **Commit SHA** | `2a3fab25cb04aa3b2024a943fcd1c62ae8cc28f9` |
| **Generation Model** | `deepseek/deepseek-v4-flash-0731` |
| **Embedding Model** | `voyageai/voyage-4-large` |
| **Judge Model** | `meta-llama/llama-3.3-70b-instruct` |
| **Judge Temperature** | `0.0` |
| **Judge Prompt Version** | `v1` |
| **Sampling Seed** | `42` |
| **Deterministic Sample Size** | `100` |
| **Judged Sample Size** | `0` |
| **Completed Calibration Dual Scores** | `0` |
| **Index Generation** | `lance-702` |
| **Result Hash** | `c6db7a116d65fbb1` |
| **Dependency Lock Hash** | `8e71ea9ce7a3532b` |
| **Arm Labels** | `graph-on, graph-off` |
| **Notes** | No judge-versus-human calibration was performed; judged dimensions are uncalibrated. |


## Evaluation Dimensions

| Dimension | Status | Score | Sample Size (n) | Details / Reason |
|---|---|---|---|---|


| `unusable_record_rate` | ok | **0.015** | 200 | unusable_n=3, n_journal=200, unusable_rate=0.015, ci_lower=0.005, ci_upper=0.043, collapsed_records_n=0 |



| `vector_yield` | ok | **1.000** | 98 | mean_count=32, positive_n=98, n_eval=98, missing_meta_n=0, ci_lower=0.962, ci_upper=1, retrieve_p50_ms=116, retrieve_p95_ms=166.1 |



| `bm25_yield` | ok | **1.000** | 98 | mean_count=32, positive_n=98, n_eval=98, missing_meta_n=0, ci_lower=0.962, ci_upper=1, retrieve_p50_ms=116, retrieve_p95_ms=166.1 |



| `retrieve_latency_ms` | ok | **116.0** | 98 | retrieve_p95_ms=166.1, missing_timing_n=0, n_eval=98 |



| `graph_presence_rate` | ok | **0.622** | 98 | positive_n=61, n_eval=98, missing_meta_n=0, ci_lower=0.524, ci_upper=0.712, investigation_floor=0.200, floor_miss=0, no_match_rate=0, completed_graph_n=98 |



| `graph_influence_rate` | ok | **0.622** | 98 | positive_n=61, n_eval=98, missing_influence_n=0, ci_lower=0.524, ci_upper=0.712 |



| `graph_latency_ms` | ok | **283.0** | 98 | graph_p95_ms=1605.1, missing_timing_n=0, n_eval=98 |



| `retrieval_evidence_coverage` | ok | **0.388** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `context_precision_at_k` | ok | **0.236** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `ranking_quality` | ok | **0.540** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `answer_exact_match` | ok | **0.000** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `answer_f1` | ok | **0.021** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `final_answer_em` | ok | **0.551** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `final_answer_containment` | ok | **0.697** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `answer_usable` | ok | **0.562** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `final_answer_missing_rate` | ok | **0.000** | 89 | errors=2, sample_size=89, excluded_payload_records=0 |



| `answer_faithfulness` | skipped | — | 0 | Deferred to LLM-as-judge scoring pass (--no-judge specified); judged_slice_committed=0, verdicts_obtained=0, judged_slice_state=0, usage_absent_fallback_count=0 |



| `answer_groundedness` | skipped | — | 0 | Deferred to LLM-as-judge scoring pass (--no-judge specified); judged_slice_committed=0, verdicts_obtained=0, judged_slice_state=0, usage_absent_fallback_count=0 |



| `graph_ablation_delta` | ok | **-0.010** | 89 | n_pairs=89, pairing_coverage=0.890, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, single_arm_usable_drops=2, missing_arm_drops=0, null_gold_drops=9, provenance_drops=0, ci_lower=-0.044, ci_upper=0.022, delta_comparison_query=-0.032, n_pairs_comparison_query=36, delta_inference_query=-0.008, n_pairs_inference_query=30, delta_temporal_query=0.022, n_pairs_temporal_query=23 |



| `graph_ablation_delta_exact_match` | ok | **0.000** | 89 | n_pairs=89, pairing_coverage=0.890, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=0, ci_upper=0, delta_comparison_query=0, n_pairs_comparison_query=36, delta_inference_query=0, n_pairs_inference_query=30, delta_temporal_query=0, n_pairs_temporal_query=23 |



| `graph_ablation_delta_f1` | ok | **-0.001** | 89 | n_pairs=89, pairing_coverage=0.890, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.003, ci_upper=0.000, delta_comparison_query=-0.002, n_pairs_comparison_query=36, delta_inference_query=-0.002, n_pairs_inference_query=30, delta_temporal_query=-0.001, n_pairs_temporal_query=23 |



| `graph_ablation_delta_context_precision` | ok | **-0.006** | 89 | n_pairs=89, pairing_coverage=0.890, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.022, ci_upper=0.011, delta_comparison_query=-0.014, n_pairs_comparison_query=36, delta_inference_query=-0.008, n_pairs_inference_query=30, delta_temporal_query=0.011, n_pairs_temporal_query=23 |



| `graph_ablation_delta_ranking_quality` | ok | **-0.081** | 89 | n_pairs=89, pairing_coverage=0.890, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.136, ci_upper=-0.026, delta_comparison_query=-0.098, n_pairs_comparison_query=36, delta_inference_query=-0.071, n_pairs_inference_query=30, delta_temporal_query=-0.067, n_pairs_temporal_query=23 |



| `graph_ablation_latency_delta` | ok | **1220.6** | 89 | n_pairs=89, pairing_coverage=0.890, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=692.270, ci_upper=1767.461, delta_comparison_query=969.167, n_pairs_comparison_query=36, delta_inference_query=1322.200, n_pairs_inference_query=30, delta_temporal_query=1481.696, n_pairs_temporal_query=23 |



| `graph_ablation_prompt_token_delta` | ok | **211.0** | 89 | n_pairs=89, pairing_coverage=0.890, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=163.315, ci_upper=260.506, delta_comparison_query=258.750, n_pairs_comparison_query=36, delta_inference_query=135.300, n_pairs_inference_query=30, delta_temporal_query=234.826, n_pairs_temporal_query=23 |



| `abstention_on_unanswerable` | ok | **1.000** | 9 | null_samples=9, excluded_payload_records=0 |



| `null_abstention_correctness` | ok | **1.000** | 9 | null_samples=9, excluded_payload_records=0 |



| `wire_contract_conformance` | ok | **1.000** | 200 | n_journal=200, conforming_n=200, violations_n=0, unparseable_n=0, contradiction_n=0, ci_lower=0.981, ci_upper=1 |



| `community_summary_quality` | skipped | — | 0 | Deferred to Phase 999.1 (community summaries not yet implemented in engine) |



| `run_traceability` | ok | **0.995** | 200 | traced_records=199, total_records=200 |



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