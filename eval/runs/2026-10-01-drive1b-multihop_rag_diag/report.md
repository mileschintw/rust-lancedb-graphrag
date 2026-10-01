# Evaluation Report: multihop_rag_diag


## Run Metadata

| Parameter | Value |
|---|---|
| **Corpus** | `multihop_rag_diag` |
| **Run Date** | `2026-10-01T22:39:04.282703+00:00` |
| **Commit SHA** | `75433e423e6445f7fba3872a5d25463ec6ad1b79` |
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
| **Result Hash** | `bf3c3285d9f124dc` |
| **Dependency Lock Hash** | `8e71ea9ce7a3532b` |
| **Arm Labels** | `graph-on, graph-off` |
| **Notes** | No judge-versus-human calibration was performed; judged dimensions are uncalibrated. |


## Evaluation Dimensions

| Dimension | Status | Score | Sample Size (n) | Details / Reason |
|---|---|---|---|---|


| `unusable_record_rate` | ok | **0.000** | 200 | unusable_n=0, n_journal=200, unusable_rate=0, ci_lower=0, ci_upper=0.019, collapsed_records_n=0 |



| `vector_yield` | ok | **1.000** | 100 | mean_count=32, positive_n=100, n_eval=100, missing_meta_n=0, ci_lower=0.963, ci_upper=1.000, retrieve_p50_ms=98, retrieve_p95_ms=139.1 |



| `bm25_yield` | ok | **1.000** | 100 | mean_count=32, positive_n=100, n_eval=100, missing_meta_n=0, ci_lower=0.963, ci_upper=1.000, retrieve_p50_ms=98, retrieve_p95_ms=139.1 |



| `retrieve_latency_ms` | ok | **98.0** | 100 | retrieve_p95_ms=139.1, missing_timing_n=0, n_eval=100 |



| `graph_presence_rate` | ok | **0.250** | 100 | positive_n=25, n_eval=100, missing_meta_n=0, ci_lower=0.175, ci_upper=0.343, investigation_floor=0.200, floor_miss=0, no_match_rate=0.010, completed_graph_n=100 |



| `graph_influence_rate` | ok | **0.250** | 100 | positive_n=25, n_eval=100, missing_influence_n=0, ci_lower=0.175, ci_upper=0.343 |



| `graph_latency_ms` | ok | **370.0** | 100 | graph_p95_ms=463.7, missing_timing_n=0, n_eval=100 |



| `retrieval_evidence_coverage` | ok | **0.396** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `context_precision_at_k` | ok | **0.242** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `ranking_quality` | ok | **0.616** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `answer_exact_match` | ok | **0.000** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `answer_f1` | ok | **0.023** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `final_answer_em` | ok | **0.556** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `final_answer_containment` | ok | **0.722** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `answer_usable` | ok | **0.578** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `final_answer_missing_rate` | ok | **0.000** | 90 | errors=0, sample_size=90, excluded_payload_records=0 |



| `answer_faithfulness` | skipped | — | 0 | Deferred to LLM-as-judge scoring pass (--no-judge specified); judged_slice_committed=0, verdicts_obtained=0, judged_slice_state=0, usage_absent_fallback_count=0 |



| `answer_groundedness` | skipped | — | 0 | Deferred to LLM-as-judge scoring pass (--no-judge specified); judged_slice_committed=0, verdicts_obtained=0, judged_slice_state=0, usage_absent_fallback_count=0 |



| `graph_ablation_delta` | ok | **0.000** | 90 | n_pairs=90, pairing_coverage=0.900, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, single_arm_usable_drops=0, missing_arm_drops=0, null_gold_drops=10, provenance_drops=0, ci_lower=0, ci_upper=0, delta_comparison_query=0, n_pairs_comparison_query=36, delta_inference_query=0, n_pairs_inference_query=31, delta_temporal_query=0, n_pairs_temporal_query=23 |



| `graph_ablation_delta_exact_match` | ok | **0.000** | 90 | n_pairs=90, pairing_coverage=0.900, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=0, ci_upper=0, delta_comparison_query=0, n_pairs_comparison_query=36, delta_inference_query=0, n_pairs_inference_query=31, delta_temporal_query=0, n_pairs_temporal_query=23 |



| `graph_ablation_delta_f1` | ok | **0.001** | 90 | n_pairs=90, pairing_coverage=0.900, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.001, ci_upper=0.004, delta_comparison_query=0.001, n_pairs_comparison_query=36, delta_inference_query=0.002, n_pairs_inference_query=31, delta_temporal_query=0.002, n_pairs_temporal_query=23 |



| `graph_ablation_delta_context_precision` | ok | **0.000** | 90 | n_pairs=90, pairing_coverage=0.900, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=0, ci_upper=0, delta_comparison_query=0, n_pairs_comparison_query=36, delta_inference_query=0, n_pairs_inference_query=31, delta_temporal_query=0, n_pairs_temporal_query=23 |



| `graph_ablation_delta_ranking_quality` | ok | **0.002** | 90 | n_pairs=90, pairing_coverage=0.900, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-0.014, ci_upper=0.019, delta_comparison_query=0.006, n_pairs_comparison_query=36, delta_inference_query=0, n_pairs_inference_query=31, delta_temporal_query=0, n_pairs_temporal_query=23 |



| `graph_ablation_latency_delta` | ok | **174.8** | 90 | n_pairs=90, pairing_coverage=0.900, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=-459.089, ci_upper=799.333, delta_comparison_query=287.556, n_pairs_comparison_query=36, delta_inference_query=-170.323, n_pairs_inference_query=31, delta_temporal_query=463.609, n_pairs_temporal_query=23 |



| `graph_ablation_prompt_token_delta` | ok | **152.8** | 90 | n_pairs=90, pairing_coverage=0.900, n_answerable_in_sample=90, bootstrap_seed=42, excluded_unscorable_pairs=0, ci_lower=73.189, ci_upper=253.167, delta_comparison_query=161.722, n_pairs_comparison_query=36, delta_inference_query=38.613, n_pairs_inference_query=31, delta_temporal_query=292.913, n_pairs_temporal_query=23 |



| `abstention_on_unanswerable` | ok | **1.000** | 10 | null_samples=10, excluded_payload_records=0 |



| `null_abstention_correctness` | ok | **1.000** | 10 | null_samples=10, excluded_payload_records=0 |



| `wire_contract_conformance` | ok | **1.000** | 200 | n_journal=200, conforming_n=200, violations_n=0, unparseable_n=0, contradiction_n=0, ci_lower=0.981, ci_upper=1 |



| `community_summary_quality` | skipped | — | 0 | Deferred to Phase 999.1 (community summaries not yet implemented in engine) |



| `run_traceability` | ok | **1.000** | 200 | traced_records=200, total_records=200 |



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