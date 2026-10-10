# Lever comparison: multihop_rag_levers_heldout

- Run: `2026-10-10-levers-heldout-multihop_rag_levers_heldout`; pre-registration `PREREGISTRATION_06_3_6`; reference arm `hybrid`.
- No judge ran and no judged figure exists in this phase (D-153).
- |H_G| = 308, |H_N| = 43; coverage floor 0.8 per comparison (exact).
- `report.json` cells are on the all-arm P_all, not the decisional population.

## Familywise error

Two Holm families, one per primary, each at its family-wise error rate (m fixed at the registered arm count). Across both families the family-wise error rate can reach 0.10 (the Bonferroni bound over two families), and this report states it. Defaults read only the decisional family (at most 0.05). The guards can only veto a rejection, so they never raise the error rate.

Bootstrap CIs are 95% percentile intervals, labelled 'unadjusted, estimation only'. A CI that excludes 0 without a Holm rejection is not significant.

## Holm family `answer_usable` (decisional; m = 4, alpha = 0.05)

| arm | n (P_X) | coverage | n_pos | n_neg | p | Holm p | decision | delta | 95% CI (unadjusted, estimation only) | mean arm | mean hybrid on P_X |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid+rerank | 308 | 1.000 | 39 | 14 | 0.0008 | 0.0032 | significant | 0.0812 | [0.0357, 0.1266] | 0.6526 | 0.5714 |
| hybrid+graph-v2 | 308 | 1.000 | 16 | 22 | 0.4177 | 0.4177 | not significant | -0.0195 | [-0.0584, 0.0195] | 0.5519 | 0.5714 |
| hybrid+metadata | 306 | 0.994 | 28 | 9 | 0.0026 | 0.0077 | significant | 0.0621 | [0.0261, 0.1013] | 0.6340 | 0.5719 |
| hybrid+answer-format | 307 | 0.997 | 12 | 25 | 0.0470 | 0.0941 | not significant (CI excludes 0; not significant after Holm) | -0.0423 | [-0.0814, -0.0033] | 0.5309 | 0.5733 |

| arm | own failure | own provenance | reference-only failure | sum (= |H_G| - n) | of which rerank degrade | of which reference own failure | of which reference provenance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid+rerank | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hybrid+graph-v2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hybrid+metadata | 2 | 0 | 0 | 2 | 0 | 0 | 0 |
| hybrid+answer-format | 1 | 0 | 0 | 1 | 0 | 0 | 0 |

## Holm family `paper_hits_at_4` (supporting; m = 2, alpha = 0.05)

| arm | n (P_X) | coverage | n_pos | n_neg | p | Holm p | decision | delta | 95% CI (unadjusted, estimation only) | mean arm | mean hybrid on P_X |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid+rerank | 308 | 1.000 | 58 | 10 | 0.0000 | 0.0000 | significant | 0.1558 | [0.1071, 0.2045] | 0.8539 | 0.6981 |
| hybrid+graph-v2 | 308 | 1.000 | 6 | 10 | 0.4545 | 0.4545 | not significant | -0.0130 | [-0.0390, 0.0130] | 0.6851 | 0.6981 |

| arm | own failure | own provenance | reference-only failure | sum (= |H_G| - n) | of which rerank degrade | of which reference own failure | of which reference provenance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid+rerank | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hybrid+graph-v2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Guard 1: null-abstention paired drop (D-148)

| arm | decisional | predicate | N_X | needs | b | c | net loss | margin | reading | one-sided 95% bound | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid+rerank | False | `metrics.is_abstention` | 43 | 35 | 2 | 0 | 0.0465 | 0.1 | would pass | 0.0465 | net loss 2 of 43, at most the margin 0.1 |
| hybrid+graph-v2 | False | `metrics.is_abstention` | 43 | 35 | 0 | 0 | 0.0000 | 0.1 | would pass | 0.0000 | net loss 0 of 43, at most the margin 0.1 |
| hybrid+metadata | True | `metrics.is_abstention` | 43 | 35 | 0 | 1 | -0.0233 | 0.1 | PASS | 0.0209 | net loss -1 of 43, at most the margin 0.1 |
| hybrid+answer-format | True | `metrics.is_abstention` | 43 | 35 | 1 | 1 | 0.0000 | 0.1 | PASS | 0.0442 | net loss 0 of 43, at most the margin 0.1 |

## Guard 2: answer-mix disclosure (reported only)

### hybrid+rerank

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 125 | arm | 0.392 | 0.200 | 0.312 | 0.096 |
| comparison_query | 125 | hybrid | 0.304 | 0.176 | 0.480 | 0.040 |
| comparison_query | 125 | gold | 0.640 | 0.336 | - | 0.024 |
| comparison_query | 125 | constant-Yes / constant-No answer_usable | 0.640 | 0.336 | - | - |
| binary_gold | 194 | arm | 0.366 | 0.165 | 0.402 | 0.067 |
| binary_gold | 194 | hybrid | 0.247 | 0.139 | 0.582 | 0.031 |
| binary_gold | 194 | gold | 0.603 | 0.397 | - | 0.000 |
| binary_gold | 194 | constant-Yes / constant-No answer_usable | 0.603 | 0.397 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 35 | 4 | 5 | 9 | 9 | 308 |
| comparison_query | 20 | 3 | 4 | 7 | 7 | 125 |
| inference_query | 2 | 0 | 0 | 0 | 0 | 105 |
| temporal_query | 13 | 1 | 1 | 2 | 2 | 78 |

Non-binary gold (n = 114): arm 0.9386, hybrid 0.9386, delta 0.0000 [-0.0351, 0.0351] (unadjusted, estimation only).

### hybrid+graph-v2

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 125 | arm | 0.272 | 0.168 | 0.496 | 0.064 |
| comparison_query | 125 | hybrid | 0.304 | 0.176 | 0.480 | 0.040 |
| comparison_query | 125 | gold | 0.640 | 0.336 | - | 0.024 |
| comparison_query | 125 | constant-Yes / constant-No answer_usable | 0.640 | 0.336 | - | - |
| binary_gold | 194 | arm | 0.222 | 0.119 | 0.613 | 0.046 |
| binary_gold | 194 | hybrid | 0.247 | 0.139 | 0.582 | 0.031 |
| binary_gold | 194 | gold | 0.603 | 0.397 | - | 0.000 |
| binary_gold | 194 | constant-Yes / constant-No answer_usable | 0.603 | 0.397 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 12 | 4 | 3 | 19 | 22 | 308 |
| comparison_query | 8 | 3 | 2 | 11 | 12 | 125 |
| inference_query | 1 | 0 | 0 | 3 | 3 | 105 |
| temporal_query | 3 | 1 | 1 | 5 | 7 | 78 |

Non-binary gold (n = 114): arm 0.9298, hybrid 0.9386, delta -0.0088 [-0.0526, 0.0263] (unadjusted, estimation only).

### hybrid+metadata

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 124 | arm | 0.363 | 0.202 | 0.403 | 0.032 |
| comparison_query | 124 | hybrid | 0.306 | 0.177 | 0.476 | 0.040 |
| comparison_query | 124 | gold | 0.637 | 0.339 | - | 0.024 |
| comparison_query | 124 | constant-Yes / constant-No answer_usable | 0.637 | 0.339 | - | - |
| binary_gold | 193 | arm | 0.337 | 0.161 | 0.487 | 0.016 |
| binary_gold | 193 | hybrid | 0.249 | 0.140 | 0.580 | 0.031 |
| binary_gold | 193 | gold | 0.601 | 0.399 | - | 0.000 |
| binary_gold | 193 | constant-Yes / constant-No answer_usable | 0.601 | 0.399 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 25 | 3 | 2 | 7 | 12 | 306 |
| comparison_query | 15 | 2 | 1 | 3 | 8 | 124 |
| inference_query | 2 | 0 | 0 | 0 | 0 | 104 |
| temporal_query | 8 | 1 | 1 | 4 | 4 | 78 |

Non-binary gold (n = 113): arm 0.9558, hybrid 0.9381, delta 0.0177 [0.0000, 0.0442] (unadjusted, estimation only).

### hybrid+answer-format

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 124 | arm | 0.242 | 0.274 | 0.468 | 0.016 |
| comparison_query | 124 | hybrid | 0.306 | 0.177 | 0.476 | 0.040 |
| comparison_query | 124 | gold | 0.637 | 0.339 | - | 0.024 |
| comparison_query | 124 | constant-Yes / constant-No answer_usable | 0.637 | 0.339 | - | - |
| binary_gold | 193 | arm | 0.197 | 0.192 | 0.606 | 0.005 |
| binary_gold | 193 | hybrid | 0.249 | 0.140 | 0.580 | 0.031 |
| binary_gold | 193 | gold | 0.601 | 0.399 | - | 0.000 |
| binary_gold | 193 | constant-Yes / constant-No answer_usable | 0.601 | 0.399 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 9 | 3 | 3 | 22 | 28 | 307 |
| comparison_query | 7 | 2 | 2 | 9 | 13 | 124 |
| inference_query | 1 | 0 | 0 | 8 | 8 | 105 |
| temporal_query | 1 | 1 | 1 | 5 | 7 | 78 |

Non-binary gold (n = 114): arm 0.8684, hybrid 0.9386, delta -0.0702 [-0.1228, -0.0175] (unadjusted, estimation only).

## D-140 descriptive rows

| row | n | primary | delta | 95% CI (unadjusted, estimation only) | n_pos | n_neg | label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid+graph - hybrid | 308 | answer_usable | -0.0065 | [-0.0422, 0.0292] | 14 | 16 | descriptive, decides nothing |
| hybrid+graph - hybrid | 308 | paper_hits_at_4 | -0.0162 | [-0.0422, 0.0065] | 5 | 10 | descriptive, decides nothing |
| hybrid+graph-v2 - hybrid+graph | 308 | answer_usable | -0.0130 | [-0.0455, 0.0195] | 11 | 15 | descriptive, decides nothing |
| hybrid+graph-v2 - hybrid+graph | 308 | paper_hits_at_4 | 0.0032 | [-0.0097, 0.0162] | 3 | 2 | descriptive, decides nothing |
| hybrid+all - hybrid | 307 | answer_usable | 0.1726 | [0.1173, 0.2280] | 68 | 15 | descriptive, decides nothing |
| hybrid+all - hybrid | 307 | paper_hits_at_4 | 0.1564 | [0.1075, 0.2052] | 58 | 10 | descriptive, decides nothing |

| graph-on arm | records | degree_capped_count |
| --- | --- | --- |
| hybrid+graph-v2 | 351 | 1527 |
| hybrid+all | 351 | 1527 |
| hybrid+graph | 351 | 1529 |

## Sensitivity: P_dec (sensitivity line, decides nothing)

P_dec: ok on the reference and on every decisional lever arm; n = 305, coverage 0.990.

| arm | n | p | Holm p | decision | delta |
| --- | --- | --- | --- | --- | --- |
| hybrid+rerank | 305 | 0.0012 | 0.0048 | significant | 0.0787 |
| hybrid+graph-v2 | 305 | 0.4177 | 0.4177 | not significant | -0.0197 |
| hybrid+metadata | 305 | 0.0026 | 0.0077 | significant | 0.0623 |
| hybrid+answer-format | 305 | 0.0470 | 0.0941 | not significant | -0.0426 |

## Sensitivity: rerank intention to treat (sensitivity line, decides nothing)

intention to treat: degraded rerank records kept with their fused-order outcome; n = 308, p = 0.0008, Holm p = 0.0032, significant, delta 0.0812 [0.0357, 0.1266] (unadjusted, estimation only).

## Secondaries on P_X (no p-value; unadjusted, estimation only)

| arm | metric | n | mean arm | mean hybrid | delta | 95% CI |
| --- | --- | --- | --- | --- | --- | --- |
| hybrid+rerank | paper_hits_at_10 | 308 | 0.9188 | 0.8377 | 0.0812 | [0.0422, 0.1234] |
| hybrid+rerank | paper_mrr_at_10 | 308 | 0.7646 | 0.5833 | 0.1813 | [0.1355, 0.2284] |
| hybrid+rerank | paper_map_at_10 | 308 | 0.4075 | 0.2827 | 0.1248 | [0.1023, 0.1474] |
| hybrid+rerank | coverage_at_4 | 308 | 0.5452 | 0.3655 | 0.1797 | [0.1475, 0.2132] |
| hybrid+rerank | all_gold_at_4 | 308 | 0.2532 | 0.1006 | 0.1526 | [0.1071, 0.1981] |
| hybrid+rerank | final_answer_em | 308 | 0.6364 | 0.5584 | 0.0779 | [0.0325, 0.1266] |
| hybrid+rerank | gold_containment | 308 | 0.7532 | 0.6786 | 0.0747 | [0.0260, 0.1234] |
| hybrid+rerank | final_answer_missing_rate | 308 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| hybrid+rerank | abstention_rate_g | 308 | 0.2630 | 0.3896 | -0.1266 | [-0.1721, -0.0812] |
| hybrid+rerank | prompt_tokens_mean | 308 | 2320.6039 | 2262.1331 | 58.4708 | [46.5325, 70.2760] |
| hybrid+rerank | latency_total_ms_mean | 308 | 8804.0162 | 8514.9221 | 289.0942 | [10.6396, 571.3442] |
| hybrid+rerank | retrieve_node_ms_mean | 308 | 553.8604 | 96.1136 | 457.7468 | [425.1883, 492.4091] |
| hybrid+rerank | spend_usd_mean | 308 | 0.0009 | 0.0007 | 0.0001 | [0.0001, 0.0001] |
| hybrid+graph-v2 | paper_hits_at_10 | 308 | 0.8182 | 0.8377 | -0.0195 | [-0.0357, -0.0065] |
| hybrid+graph-v2 | paper_mrr_at_10 | 308 | 0.5565 | 0.5833 | -0.0268 | [-0.0491, -0.0049] |
| hybrid+graph-v2 | paper_map_at_10 | 308 | 0.2690 | 0.2827 | -0.0137 | [-0.0243, -0.0032] |
| hybrid+graph-v2 | coverage_at_4 | 308 | 0.3571 | 0.3655 | -0.0084 | [-0.0241, 0.0076] |
| hybrid+graph-v2 | all_gold_at_4 | 308 | 0.1071 | 0.1006 | 0.0065 | [-0.0097, 0.0260] |
| hybrid+graph-v2 | final_answer_em | 308 | 0.5357 | 0.5584 | -0.0227 | [-0.0617, 0.0162] |
| hybrid+graph-v2 | gold_containment | 308 | 0.6623 | 0.6786 | -0.0162 | [-0.0552, 0.0227] |
| hybrid+graph-v2 | final_answer_missing_rate | 308 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| hybrid+graph-v2 | abstention_rate_g | 308 | 0.4123 | 0.3896 | 0.0227 | [-0.0162, 0.0617] |
| hybrid+graph-v2 | prompt_tokens_mean | 308 | 2461.5974 | 2262.1331 | 199.4643 | [176.4545, 223.0812] |
| hybrid+graph-v2 | latency_total_ms_mean | 308 | 8676.1071 | 8514.9221 | 161.1851 | [-96.4221, 420.5422] |
| hybrid+graph-v2 | retrieve_node_ms_mean | 308 | 110.0877 | 96.1136 | 13.9740 | [11.8279, 16.1591] |
| hybrid+graph-v2 | spend_usd_mean | 308 | 0.0007 | 0.0007 | 0.0000 | [0.0000, 0.0000] |
| hybrid+metadata | paper_hits_at_10 | 306 | 0.8333 | 0.8366 | -0.0033 | [-0.0098, 0.0000] |
| hybrid+metadata | paper_mrr_at_10 | 306 | 0.5821 | 0.5822 | -0.0001 | [-0.0010, 0.0007] |
| hybrid+metadata | paper_map_at_10 | 306 | 0.2828 | 0.2828 | 0.0000 | [-0.0005, 0.0005] |
| hybrid+metadata | coverage_at_4 | 306 | 0.3671 | 0.3655 | 0.0016 | [0.0000, 0.0049] |
| hybrid+metadata | all_gold_at_4 | 306 | 0.1046 | 0.1013 | 0.0033 | [0.0000, 0.0098] |
| hybrid+metadata | final_answer_em | 306 | 0.6209 | 0.5588 | 0.0621 | [0.0229, 0.1046] |
| hybrid+metadata | gold_containment | 306 | 0.7353 | 0.6797 | 0.0556 | [0.0098, 0.1013] |
| hybrid+metadata | final_answer_missing_rate | 306 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| hybrid+metadata | abstention_rate_g | 306 | 0.3203 | 0.3889 | -0.0686 | [-0.1111, -0.0261] |
| hybrid+metadata | prompt_tokens_mean | 306 | 2733.2908 | 2261.8987 | 471.3922 | [466.7190, 476.0850] |
| hybrid+metadata | latency_total_ms_mean | 306 | 8483.6928 | 8509.9837 | -26.2908 | [-304.4085, 265.7614] |
| hybrid+metadata | retrieve_node_ms_mean | 306 | 96.6471 | 96.0980 | 0.5490 | [-0.7778, 1.8856] |
| hybrid+metadata | spend_usd_mean | 306 | 0.0008 | 0.0007 | 0.0001 | [0.0000, 0.0001] |
| hybrid+answer-format | paper_hits_at_10 | 307 | 0.8339 | 0.8371 | -0.0033 | [-0.0098, 0.0000] |
| hybrid+answer-format | paper_mrr_at_10 | 307 | 0.5833 | 0.5835 | -0.0002 | [-0.0011, 0.0006] |
| hybrid+answer-format | paper_map_at_10 | 307 | 0.2824 | 0.2828 | -0.0004 | [-0.0011, 0.0002] |
| hybrid+answer-format | coverage_at_4 | 307 | 0.3640 | 0.3651 | -0.0011 | [-0.0033, 0.0000] |
| hybrid+answer-format | all_gold_at_4 | 307 | 0.0977 | 0.1010 | -0.0033 | [-0.0098, 0.0000] |
| hybrid+answer-format | final_answer_em | 307 | 0.5309 | 0.5603 | -0.0293 | [-0.0684, 0.0098] |
| hybrid+answer-format | gold_containment | 307 | 0.6189 | 0.6808 | -0.0619 | [-0.1010, -0.0228] |
| hybrid+answer-format | final_answer_missing_rate | 307 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| hybrid+answer-format | abstention_rate_g | 307 | 0.4235 | 0.3876 | 0.0358 | [-0.0065, 0.0782] |
| hybrid+answer-format | prompt_tokens_mean | 307 | 2352.6156 | 2262.4951 | 90.1205 | [89.0423, 90.9414] |
| hybrid+answer-format | latency_total_ms_mean | 307 | 8191.5863 | 8516.3844 | -324.7980 | [-581.7264, -64.9739] |
| hybrid+answer-format | retrieve_node_ms_mean | 307 | 95.5179 | 96.1075 | -0.5896 | [-1.8795, 0.6580] |
| hybrid+answer-format | spend_usd_mean | 307 | 0.0007 | 0.0007 | -0.0000 | [-0.0000, 0.0000] |

## Rerank operation

| arm | attempts | degrades | rate | timeout | status | malformed | transport | unknown | p50 ms | p95 ms | max ms | cost credits | calls without cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hybrid+rerank | 351 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 319.0 | 1075.0 | 1450.0 | 0.045800 | 0 |
| hybrid+all | 351 | 2 | 0.006 | 0 | 2 | 0 | 0 | 0 | 344.0 | 1139.0 | 1462.0 | 0.047295 | 2 |

## Provenance and retry counts

| arm | records | (h) failures | (j) failures | (i) degraded | query_embedding_retries |
| --- | --- | --- | --- | --- | --- |
| hybrid | 351 | 0 | 0 | 0 | 1 |
| hybrid+rerank | 351 | 0 | 0 | 0 | 0 |
| hybrid+graph-v2 | 351 | 0 | 0 | 0 | 1 |
| hybrid+metadata | 351 | 0 | 0 | 0 | 0 |
| hybrid+answer-format | 351 | 0 | 0 | 0 | 0 |
| hybrid+all | 351 | 0 | 0 | 2 | 0 |
| hybrid+graph | 351 | 0 | 0 | 0 | 0 |

## Default decisions (D-150, O16)

| lever | decision | answer_usable | delta | Hits@4 support | reasons |
| --- | --- | --- | --- | --- | --- |
| hybrid+rerank | owner disposition: SC-1/SC-2 not PASS (disclosed, never mechanical) | significant | 0.0812 | significant | hybrid+rerank SC-2 reads MISS |
| hybrid+graph-v2 | stays off: not significant | not significant | -0.0195 | not significant | no Holm rejection |
| hybrid+metadata | default | significant | 0.0621 | n/a (not in the supporting family) | all conditions hold |
| hybrid+answer-format | stays off: not significant | not significant | -0.0423 | n/a (not in the supporting family) | no Holm rejection |

If two levers win, D-157 flips both. The combination is never tested decisionally; hybrid+all is its only, descriptive, evidence.
