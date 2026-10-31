# Lever comparison: multihop_rag_s0_heldout

- Run: `2026-10-31-s0-multihop_rag_s0_heldout`; pre-registration `PREREGISTRATION_S0`; reference arm `hybrid+rerank+metadata`.
- No judge ran and no judged figure exists in this phase (D-153).
- |H_G| = 308, |H_N| = 43; coverage floor 0.8 per comparison (exact).
- `report.json` cells are on the all-arm P_all, not the decisional population.

## Familywise error

Two Holm families, one per primary, each at its family-wise error rate (m fixed at the registered arm count). Across both families the family-wise error rate can reach 0.10 (the Bonferroni bound over two families), and this report states it. Defaults read only the decisional family (at most 0.05). The guards can only veto a rejection, so they never raise the error rate.

Bootstrap CIs are 95% percentile intervals, labelled 'unadjusted, estimation only'. A CI that excludes 0 without a Holm rejection is not significant.

## Holm family `answer_usable` (decisional; m = 1, alpha = 0.05)

| arm | n (P_X) | coverage | n_pos | n_neg | p | Holm p | decision | delta | 95% CI (unadjusted, estimation only) | mean arm | mean hybrid on P_X |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llamaindex | 297 | 0.964 | 25 | 26 | 1.0000 | 1.0000 | not significant | -0.0034 | [-0.0505, 0.0438] | 0.7306 | 0.7340 |

| arm | own failure | own provenance | reference-only failure | sum (= |H_G| - n) | of which rerank degrade | of which reference own failure | of which reference provenance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| llamaindex | 0 | 0 | 11 | 11 | 0 | 0 | 11 |

## Guard 1: null-abstention paired drop (D-148)

| arm | decisional | predicate | N_X | needs | b | c | net loss | margin | reading | one-sided 95% bound | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llamaindex | True | `metrics.is_abstention` | 42 | 35 | 0 | 1 | -0.0238 | 0.1 | PASS | 0.0214 | net loss -1 of 42, at most the margin 0.1 |

## Guard 2: answer-mix disclosure (reported only)

### llamaindex

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 120 | arm | 0.400 | 0.250 | 0.217 | 0.133 |
| comparison_query | 120 | hybrid | 0.433 | 0.233 | 0.192 | 0.142 |
| comparison_query | 120 | gold | 0.650 | 0.325 | - | 0.025 |
| comparison_query | 120 | constant-Yes / constant-No answer_usable | 0.650 | 0.325 | - | - |
| binary_gold | 187 | arm | 0.422 | 0.214 | 0.257 | 0.107 |
| binary_gold | 187 | hybrid | 0.412 | 0.203 | 0.246 | 0.139 |
| binary_gold | 187 | gold | 0.604 | 0.396 | - | 0.000 |
| binary_gold | 187 | constant-Yes / constant-No answer_usable | 0.604 | 0.396 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 16 | 9 | 8 | 18 | 26 | 297 |
| comparison_query | 7 | 6 | 6 | 8 | 12 | 120 |
| inference_query | 0 | 0 | 1 | 4 | 4 | 102 |
| temporal_query | 9 | 3 | 1 | 6 | 10 | 75 |

Non-binary gold (n = 110): arm 0.9273, hybrid 0.9727, delta -0.0455 [-0.0909, -0.0091] (unadjusted, estimation only).

## D-140 descriptive rows

| row | n | primary | delta | 95% CI (unadjusted, estimation only) | n_pos | n_neg | label |
| --- | --- | --- | --- | --- | --- | --- | --- |

| graph-on arm | records | degree_capped_count |
| --- | --- | --- |

## Sensitivity: P_dec (sensitivity line, decides nothing)

P_dec: ok on the reference and on every decisional lever arm; n = 297, coverage 0.964.

| arm | n | p | Holm p | decision | delta |
| --- | --- | --- | --- | --- | --- |
| llamaindex | 297 | 1.0000 | 1.0000 | not significant | -0.0034 |

## Secondaries on P_X (no p-value; unadjusted, estimation only)

| arm | metric | n | mean arm | mean hybrid | delta | 95% CI |
| --- | --- | --- | --- | --- | --- | --- |
| llamaindex | paper_hits_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| llamaindex | paper_mrr_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| llamaindex | paper_map_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| llamaindex | coverage_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| llamaindex | all_gold_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| llamaindex | final_answer_em | 297 | 0.6801 | 0.6768 | 0.0034 | [-0.0471, 0.0539] |
| llamaindex | gold_containment | 297 | 0.8215 | 0.8013 | 0.0202 | [-0.0269, 0.0673] |
| llamaindex | final_answer_missing_rate | 297 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| llamaindex | abstention_rate_g | 297 | 0.1785 | 0.1549 | 0.0236 | [-0.0202, 0.0673] |
| llamaindex | prompt_tokens_mean | 297 | 3720.0943 | 2793.1010 | 926.9933 | [908.8552, 944.4815] |
| llamaindex | latency_total_ms_mean | 297 | 0.0000 | 6091.4040 | -6091.4040 | [-6282.9562, -5905.7845] |
| llamaindex | retrieve_node_ms_mean | 0 | n/a | n/a | n/a | [n/a, n/a] |
| llamaindex | spend_usd_mean | 297 | 0.0009 | 0.0009 | 0.0000 | [-0.0000, 0.0000] |
| llamaindex | context_tokens_mean | 297 | 1494.4141 | 563.6599 | 930.7542 | [916.4209, 944.5791] |

## Context per arm (D-250; descriptive, decides nothing)

| arm | n | evidence_hits_at_4 | context_tokens_mean | prompt_tokens_mean (not compared) |
| --- | --- | --- | --- | --- |
| hybrid+rerank+metadata | 297 | 0.8552 | 563.7 | 2793.1 |
| llamaindex | 308 | 0.8604 | 1493.4 | 3721.6 |

## Rerank operation

| arm | attempts | degrades | rate | timeout | status | malformed | transport | unknown | p50 ms | p95 ms | max ms | cost credits | calls without cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid+rerank+metadata | 351 | 12 | 0.034 | 12 | 0 | 0 | 0 | 0 | 287.0 | 451.0 | 1812.0 | 0.043981 | 12 |

## Provenance and retry counts

| arm | records | (h) failures | (j) failures | (i) degraded | query_embedding_retries |
| --- | --- | --- | --- | --- | --- |
| hybrid+rerank+metadata | 351 | 0 | 0 | 12 | 0 |
| llamaindex | 351 | 0 | 0 | 0 | 0 |

## Default decisions (D-150, O16)

| lever | decision | answer_usable | delta | Hits@4 support | reasons |
| --- | --- | --- | --- | --- | --- |
| llamaindex | stays off: not significant | not significant | -0.0034 | n/a (not in the supporting family) | no Holm rejection |

If two levers win, D-157 flips both. The combination is never tested decisionally; hybrid+all is its only, descriptive, evidence.
