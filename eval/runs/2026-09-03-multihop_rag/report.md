# Evaluation Report: multihop_rag


## Run Metadata

| Parameter | Value |
|---|---|
| **Corpus** | `multihop_rag` |
| **Run Date** | `2026-09-04T13:22:51.810113+00:00` |
| **Commit SHA** | `05302e6e146f722d96c101ec2b2c132123bd1812` |
| **Generation Model** | `deepseek/deepseek-v4-flash-0731` |
| **Embedding Model** | `voyageai/voyage-4-large` |
| **Judge Model** | `meta-llama/llama-3.3-70b-instruct` |
| **Judge Temperature** | `0.0` |
| **Judge Prompt Version** | `v1` |
| **Sampling Seed** | `42` |
| **Deterministic Sample Size** | `500` |
| **Judged Sample Size** | `500` |
| **Index Generation** | `lance-701` |
| **Result Hash** | `36e12fd0dcf553f2` |
| **Dependency Lock Hash** | `8e71ea9ce7a3532b` |
| **Arm Labels** | `graph-on, graph-off` |


## Evaluation Dimensions

| Dimension | Status | Score | Sample Size (n) | Details / Reason |
|---|---|---|---|---|


| `retrieval_evidence_coverage` | ok | **0.427** | 16 | errors=0.0, sample_size=16.0 |



| `context_precision_at_k` | ok | **0.250** | 16 | errors=0.0, sample_size=16.0 |



| `ranking_quality` | ok | **0.665** | 16 | errors=0.0, sample_size=16.0 |



| `answer_exact_match` | ok | **0.000** | 447 | errors=0.0, sample_size=447.0 |



| `answer_f1` | ok | **0.001** | 447 | errors=0.0, sample_size=447.0 |



| `answer_faithfulness` | ok | **4.88** | 16 | judged_n=16.0, judge_errors=0.0, skipped_no_evidence=484.0 |



| `answer_groundedness` | ok | **4.62** | 16 | judged_n=16.0, judge_errors=0.0, skipped_no_evidence=484.0 |



| `graph_ablation_delta` | ok | **0.010** | 33 | graph_on_score=0.4270833333333333, graph_on_n=16.0, graph_on_errors=0.0, graph_off_score=0.41666666666666663, graph_off_n=17.0, graph_off_errors=4.0, delta=0.010416666666666685 |



| `abstention_on_unanswerable` | ok | **0.000** | 53 | null_samples=53.0 |



| `wire_contract_conformance` | ok | **1.000** | 1000 | total_records=1000.0, error_records=0.0 |



| `community_summary_quality` | skipped | — | 0 | Deferred to Phase 999.1 (community summaries not yet implemented in engine) |



| `run_traceability` | ok | **0.034** | 1000 | traced_records=34.0, total_records=1000.0 |



## Methodological Caveats & Notes

1. **Evidence Matching Rule:** A retrieved chunk matches a gold fact if and only if the chunk's normalized text contains the fact's normalized text as a contiguous substring. Facts straddling chunk boundaries resolve to misses and are surfaced separately in the `boundary_attributable_misses` diagnostic count.
2. **Evidence Source Distinction:** Every retrieval metric is computed over the response's retrieved-chunk list (what the retriever returned), not over the citations the model emitted. Judged dimensions are computed over cited evidence instead.
3. **Chunk Size & Overlength Facts:** Gold facts longer than the corpus's chunk size cannot appear verbatim in any single chunk, are excluded from the recall denominator, and are reported as their own count.
4. **Paper Comparability:** Lancet's answer metrics are not comparable to the MultiHop-RAG paper's reported accuracy, because the reference scorer credits any shared lowercased token.
5. **Ranking Metric Convention:** Neither reported ranking metric is the MultiHop-RAG paper's own convention unless the additive reference-convention figure is present and labelled.
6. **Failed Query Snapshot Exclusion:** A query whose generation failed carries no retrieval snapshot on the wire and is excluded from retrieval denominators rather than scored as zero.
7. **Rounding & Advisory Status:** This report is advisory only with no automated pass/fail gate. Scores are rounded using banker's rounding (3 decimals for ratios, 2 decimals for judged scales). Full float precision is recorded in report.json.