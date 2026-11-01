# Lever comparison: multihop_rag_s1_dev

- Run: `2026-10-31-s1-multihop_rag_s1_dev`; pre-registration `PREREGISTRATION_S1`; reference arm `small/hybrid+rerank+metadata`.
- No judge ran and no judged figure exists in this phase (D-153).
- dev population: |H_G| = 90, |H_N| = 10; coverage floor 0.8 per comparison (exact).
- `report.json` cells are on the all-arm P_all, not the decisional population.

## Familywise error

Two Holm families, one per primary, each at its family-wise error rate (m fixed at the registered arm count). Across both families the family-wise error rate can reach 0.10 (the Bonferroni bound over two families), and this report states it. Defaults read only the decisional family (at most 0.05). The guards can only veto a rejection, so they never raise the error rate.

Bootstrap CIs are 95% percentile intervals, labelled 'unadjusted, estimation only'. A CI that excludes 0 without a Holm rejection is not significant.

## Holm family `answer_usable` (decisional; m = 2, alpha = 0.05)

| arm | n (P_X) | coverage | n_pos | n_neg | p | Holm p | decision | delta | 95% CI (unadjusted, estimation only) | mean arm | mean hybrid on P_X |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 90 | 1.000 | 4 | 5 | 1.0000 | 1.0000 | not significant | -0.0111 | [-0.0778, 0.0556] | 0.8667 | 0.8778 |
| small/hybrid+graph+rerank+metadata | 90 | 1.000 | 2 | 10 | 0.0386 | 0.0771 | not significant (CI excludes 0; not significant after Holm) | -0.0889 | [-0.1667, -0.0222] | 0.7889 | 0.8778 |

| arm | own failure | own provenance | reference-only failure | sum (= |H_G| - n) | of which rerank degrade | of which reference own failure | of which reference provenance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| small/hybrid+graph+rerank+metadata | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Guard 1: null-abstention paired drop (D-148)

| arm | decisional | predicate | N_X | needs | b | c | net loss | margin | reading | one-sided 95% bound | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | True | `metrics.is_abstention` | 10 | 8 | 0 | 0 | 0.0000 | 0.1 | PASS | 0.0000 | net loss 0 of 10, at most the margin 0.1 |
| small/hybrid+graph+rerank+metadata | True | `metrics.is_abstention` | 10 | 8 | 0 | 0 | 0.0000 | 0.1 | PASS | 0.0000 | net loss 0 of 10, at most the margin 0.1 |

## Guard 2: answer-mix disclosure (reported only)

### merged/hybrid+rerank+metadata

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 36 | arm | 0.611 | 0.222 | 0.083 | 0.083 |
| comparison_query | 36 | hybrid | 0.639 | 0.194 | 0.083 | 0.083 |
| comparison_query | 36 | gold | 0.667 | 0.278 | - | 0.056 |
| comparison_query | 36 | constant-Yes / constant-No answer_usable | 0.667 | 0.278 | - | - |
| binary_gold | 56 | arm | 0.607 | 0.214 | 0.143 | 0.036 |
| binary_gold | 56 | hybrid | 0.607 | 0.196 | 0.125 | 0.071 |
| binary_gold | 56 | gold | 0.661 | 0.339 | - | 0.000 |
| binary_gold | 56 | constant-Yes / constant-No answer_usable | 0.661 | 0.339 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 3 | 1 | 1 | 4 | 4 | 90 |
| comparison_query | 2 | 0 | 1 | 2 | 2 | 36 |
| inference_query | 0 | 1 | 0 | 0 | 0 | 31 |
| temporal_query | 1 | 0 | 0 | 2 | 2 | 23 |

Non-binary gold (n = 34): arm 0.9412, hybrid 0.9118, delta 0.0294 [0.0000, 0.0882] (unadjusted, estimation only).

### small/hybrid+graph+rerank+metadata

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 36 | arm | 0.694 | 0.139 | 0.111 | 0.056 |
| comparison_query | 36 | hybrid | 0.639 | 0.194 | 0.083 | 0.083 |
| comparison_query | 36 | gold | 0.667 | 0.278 | - | 0.056 |
| comparison_query | 36 | constant-Yes / constant-No answer_usable | 0.667 | 0.278 | - | - |
| binary_gold | 56 | arm | 0.679 | 0.143 | 0.161 | 0.018 |
| binary_gold | 56 | hybrid | 0.607 | 0.196 | 0.125 | 0.071 |
| binary_gold | 56 | gold | 0.661 | 0.339 | - | 0.000 |
| binary_gold | 56 | constant-Yes / constant-No answer_usable | 0.661 | 0.339 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 2 | 0 | 6 | 4 | 4 | 90 |
| comparison_query | 1 | 0 | 3 | 2 | 2 | 36 |
| inference_query | 0 | 0 | 0 | 0 | 0 | 31 |
| temporal_query | 1 | 0 | 3 | 2 | 2 | 23 |

Non-binary gold (n = 34): arm 0.9118, hybrid 0.9118, delta 0.0000 [0.0000, 0.0000] (unadjusted, estimation only).

## D-140 descriptive rows

| row | n | primary | delta | 95% CI (unadjusted, estimation only) | n_pos | n_neg | label |
| --- | --- | --- | --- | --- | --- | --- | --- |

| graph-on arm | records | degree_capped_count |
| --- | --- | --- |
| small/hybrid+graph+rerank+metadata | 100 | 362 |
| merged/hybrid+graph+rerank+metadata | 100 | 279 |

## Sensitivity: P_dec (sensitivity line, decides nothing)

P_dec: ok on the reference and on every decisional lever arm; n = 90, coverage 1.000.

| arm | n | p | Holm p | decision | delta |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 90 | 1.0000 | 1.0000 | not significant | -0.0111 |
| small/hybrid+graph+rerank+metadata | 90 | 0.0386 | 0.0771 | not significant | -0.0889 |

## Secondaries on P_X (no p-value; unadjusted, estimation only)

| arm | metric | n | mean arm | mean hybrid | delta | 95% CI |
| --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | paper_hits_at_10 | 90 | 0.0000 | 0.9556 | -0.9556 | [-0.9889, -0.9111] |
| merged/hybrid+rerank+metadata | paper_mrr_at_10 | 90 | 0.0000 | 0.7734 | -0.7734 | [-0.8402, -0.7032] |
| merged/hybrid+rerank+metadata | paper_map_at_10 | 90 | 0.0000 | 0.4087 | -0.4087 | [-0.4551, -0.3638] |
| merged/hybrid+rerank+metadata | coverage_at_4 | 90 | 0.5648 | 0.5593 | 0.0056 | [-0.0380, 0.0491] |
| merged/hybrid+rerank+metadata | all_gold_at_4 | 90 | 0.0000 | 0.2444 | -0.2444 | [-0.3333, -0.1556] |
| merged/hybrid+rerank+metadata | final_answer_em | 90 | 0.8444 | 0.8000 | 0.0444 | [-0.0333, 0.1222] |
| merged/hybrid+rerank+metadata | gold_containment | 90 | 0.9444 | 0.9333 | 0.0111 | [-0.0333, 0.0556] |
| merged/hybrid+rerank+metadata | final_answer_missing_rate | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+rerank+metadata | abstention_rate_g | 90 | 0.1000 | 0.0889 | 0.0111 | [-0.0444, 0.0667] |
| merged/hybrid+rerank+metadata | prompt_tokens_mean | 90 | 3778.8444 | 2548.9556 | 1229.8889 | [1191.0333, 1269.2889] |
| merged/hybrid+rerank+metadata | latency_total_ms_mean | 90 | 3339.3556 | 3632.0111 | -292.6556 | [-523.7222, -87.4889] |
| merged/hybrid+rerank+metadata | retrieve_node_ms_mean | 90 | 623.5111 | 940.0111 | -316.5000 | [-356.4111, -274.4667] |
| merged/hybrid+rerank+metadata | spend_usd_mean | 90 | 0.0012 | 0.0009 | 0.0003 | [0.0003, 0.0004] |
| merged/hybrid+rerank+metadata | context_tokens_mean | 90 | 1748.7111 | 565.5889 | 1183.1222 | [1147.5556, 1218.3556] |
| small/hybrid+graph+rerank+metadata | paper_hits_at_10 | 90 | 0.9556 | 0.9556 | 0.0000 | [0.0000, 0.0000] |
| small/hybrid+graph+rerank+metadata | paper_mrr_at_10 | 90 | 0.7734 | 0.7734 | 0.0000 | [0.0000, 0.0000] |
| small/hybrid+graph+rerank+metadata | paper_map_at_10 | 90 | 0.4087 | 0.4087 | -0.0000 | [-0.0002, 0.0002] |
| small/hybrid+graph+rerank+metadata | coverage_at_4 | 90 | 0.5593 | 0.5593 | 0.0000 | [0.0000, 0.0000] |
| small/hybrid+graph+rerank+metadata | all_gold_at_4 | 90 | 0.2444 | 0.2444 | 0.0000 | [0.0000, 0.0000] |
| small/hybrid+graph+rerank+metadata | final_answer_em | 90 | 0.7778 | 0.8000 | -0.0222 | [-0.1000, 0.0556] |
| small/hybrid+graph+rerank+metadata | gold_containment | 90 | 0.8778 | 0.9333 | -0.0556 | [-0.1111, 0.0000] |
| small/hybrid+graph+rerank+metadata | final_answer_missing_rate | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| small/hybrid+graph+rerank+metadata | abstention_rate_g | 90 | 0.1111 | 0.0889 | 0.0222 | [-0.0333, 0.0778] |
| small/hybrid+graph+rerank+metadata | prompt_tokens_mean | 90 | 2754.3000 | 2548.9556 | 205.3444 | [164.0222, 249.1556] |
| small/hybrid+graph+rerank+metadata | latency_total_ms_mean | 90 | 4094.8333 | 3632.0111 | 462.8222 | [213.9222, 690.5556] |
| small/hybrid+graph+rerank+metadata | retrieve_node_ms_mean | 90 | 1004.1667 | 940.0111 | 64.1556 | [37.6556, 90.6778] |
| small/hybrid+graph+rerank+metadata | spend_usd_mean | 90 | 0.0009 | 0.0009 | 0.0000 | [0.0000, 0.0001] |
| small/hybrid+graph+rerank+metadata | context_tokens_mean | 90 | 565.6333 | 565.5889 | 0.0444 | [-3.2222, 3.5000] |

## Context per arm (D-250; descriptive, decides nothing)

| arm | n | evidence_hits_at_4 | context_tokens_mean | prompt_tokens_mean (not compared) |
| --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata | 90 | 0.9000 | 565.6 | 2549.0 |
| merged/hybrid+rerank+metadata | 90 | 0.9000 | 1748.7 | 3778.8 |
| small/hybrid+graph+rerank+metadata | 90 | 0.9000 | 565.6 | 2754.3 |
| merged/hybrid+graph+rerank+metadata | 90 | 0.9000 | 1747.9 | 3963.2 |

## Rerank operation

| arm | attempts | degrades | rate | timeout | status | malformed | transport | unknown | p50 ms | p95 ms | max ms | cost credits | calls without cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 276.0 | 400.5 | 710.0 | 0.012909 | 0 |
| merged/hybrid+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 361.5 | 716.0 | 1259.0 | 0.027831 | 0 |
| small/hybrid+graph+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 280.5 | 440.4 | 792.0 | 0.013613 | 0 |
| merged/hybrid+graph+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 367.0 | 656.8 | 1231.0 | 0.028654 | 0 |

## Provenance and retry counts

| arm | records | (h) failures | (j) failures | (i) degraded | query_embedding_retries |
| --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata | 100 | 0 | 0 | 0 | 0 |
| merged/hybrid+rerank+metadata | 100 | 0 | 0 | 0 | 0 |
| small/hybrid+graph+rerank+metadata | 100 | 0 | 0 | 0 | 0 |
| merged/hybrid+graph+rerank+metadata | 100 | 0 | 0 | 0 | 0 |

## Default decisions (D-150, O16)

| lever | decision | answer_usable | delta | Hits@4 support | reasons |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | stays off: not significant | not significant | -0.0111 | n/a (not in the supporting family) | no Holm rejection |
| small/hybrid+graph+rerank+metadata | stays off: not significant | not significant | -0.0889 | n/a (not in the supporting family) | no Holm rejection |

If two levers win, D-157 flips both. The combination is never tested decisionally; hybrid+all is its only, descriptive, evidence.
