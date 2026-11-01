# Lever comparison: multihop_rag_s2x_dev

- Run: `2026-11-01-s2-multihop_rag_s2x_dev`; pre-registration `PREREGISTRATION_S2X`; reference arm `merged/hybrid+rerank+metadata`.
- No judge ran and no judged figure exists in this phase (D-153).
- dev population: |H_G| = 90, |H_N| = 10; coverage floor 0.8 per comparison (exact).
- `report.json` cells are on the all-arm P_all, not the decisional population.

## Familywise error

Two Holm families, one per primary, each at its family-wise error rate (m fixed at the registered arm count). Across both families the family-wise error rate can reach 0.10 (the Bonferroni bound over two families), and this report states it. Defaults read only the decisional family (at most 0.05). The guards can only veto a rejection, so they never raise the error rate.

Bootstrap CIs are 95% percentile intervals, labelled 'unadjusted, estimation only'. A CI that excludes 0 without a Holm rejection is not significant.

## Holm family `answer_usable` (decisional; m = 2, alpha = 0.05)

| arm | n (P_X) | coverage | n_pos | n_neg | p | Holm p | decision | delta | 95% CI (unadjusted, estimation only) | mean arm | mean hybrid on P_X |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata@haiku-5.5 | 89 | 0.989 | 6 | 27 | 0.0001 | 0.0002 | significant | -0.1854 | [-0.2753, -0.1011] | 0.6629 | 0.8483 |
| merged/hybrid+rerank+metadata@sonnet-5.5 | 89 | 0.989 | 6 | 10 | 0.1561 | 0.1561 | not significant | -0.0562 | [-0.1292, 0.0112] | 0.7921 | 0.8483 |

| arm | own failure | own provenance | reference-only failure | sum (= |H_G| - n) | of which rerank degrade | of which reference own failure | of which reference provenance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata@haiku-5.5 | 0 | 0 | 1 | 1 | 0 | 1 | 0 |
| merged/hybrid+rerank+metadata@sonnet-5.5 | 0 | 0 | 1 | 1 | 0 | 1 | 0 |

## Guard 1: null-abstention paired drop (D-148)

| arm | decisional | predicate | N_X | needs | b | c | net loss | margin | reading | one-sided 95% bound | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata@haiku-5.5 | True | `metrics.is_abstention` | 20 | 16 | 0 | 0 | 0.0000 | 0.1 | PASS | 0.0000 | net loss 0 of 20, at most the margin 0.1 |
| merged/hybrid+rerank+metadata@sonnet-5.5 | True | `metrics.is_abstention` | 20 | 16 | 0 | 0 | 0.0000 | 0.1 | PASS | 0.0000 | net loss 0 of 20, at most the margin 0.1 |

## Guard 2: answer-mix disclosure (reported only)

### merged/hybrid+rerank+metadata@haiku-5.5

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 36 | arm | 0.361 | 0.389 | 0.194 | 0.056 |
| comparison_query | 36 | hybrid | 0.611 | 0.222 | 0.083 | 0.083 |
| comparison_query | 36 | gold | 0.667 | 0.278 | - | 0.056 |
| comparison_query | 36 | constant-Yes / constant-No answer_usable | 0.667 | 0.278 | - | - |
| binary_gold | 55 | arm | 0.327 | 0.364 | 0.255 | 0.055 |
| binary_gold | 55 | hybrid | 0.600 | 0.218 | 0.145 | 0.036 |
| binary_gold | 55 | gold | 0.655 | 0.345 | - | 0.000 |
| binary_gold | 55 | constant-Yes / constant-No answer_usable | 0.655 | 0.345 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 4 | 2 | 9 | 14 | 14 | 89 |
| comparison_query | 2 | 1 | 7 | 7 | 7 | 36 |
| inference_query | 0 | 0 | 0 | 3 | 3 | 31 |
| temporal_query | 2 | 1 | 2 | 4 | 4 | 22 |

Non-binary gold (n = 34): arm 0.8824, hybrid 0.9706, delta -0.0882 [-0.2059, 0.0294] (unadjusted, estimation only).

### merged/hybrid+rerank+metadata@sonnet-5.5

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 36 | arm | 0.500 | 0.222 | 0.167 | 0.111 |
| comparison_query | 36 | hybrid | 0.611 | 0.222 | 0.083 | 0.083 |
| comparison_query | 36 | gold | 0.667 | 0.278 | - | 0.056 |
| comparison_query | 36 | constant-Yes / constant-No answer_usable | 0.667 | 0.278 | - | - |
| binary_gold | 55 | arm | 0.473 | 0.218 | 0.218 | 0.091 |
| binary_gold | 55 | hybrid | 0.600 | 0.218 | 0.145 | 0.036 |
| binary_gold | 55 | gold | 0.655 | 0.345 | - | 0.000 |
| binary_gold | 55 | constant-Yes / constant-No answer_usable | 0.655 | 0.345 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 3 | 0 | 3 | 7 | 7 | 89 |
| comparison_query | 1 | 0 | 3 | 5 | 5 | 36 |
| inference_query | 0 | 0 | 0 | 0 | 0 | 31 |
| temporal_query | 2 | 0 | 0 | 2 | 2 | 22 |

Non-binary gold (n = 34): arm 1.0000, hybrid 0.9706, delta 0.0294 [0.0000, 0.0882] (unadjusted, estimation only).

## D-140 descriptive rows

| row | n | primary | delta | 95% CI (unadjusted, estimation only) | n_pos | n_neg | label |
| --- | --- | --- | --- | --- | --- | --- | --- |

| graph-on arm | records | degree_capped_count |
| --- | --- | --- |

## Sensitivity: P_dec (sensitivity line, decides nothing)

P_dec: ok on the reference and on every decisional lever arm; n = 90, coverage 1.000.

| arm | n | p | Holm p | decision | delta |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata@haiku-5.5 | 90 | 0.0001 | 0.0001 | significant | -0.1889 |
| merged/hybrid+rerank+metadata@sonnet-5.5 | 90 | 0.2144 | 0.2144 | not significant | -0.0500 |

## Secondaries on P_X (no p-value; unadjusted, estimation only)

| arm | metric | n | mean arm | mean hybrid | delta | 95% CI |
| --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata@haiku-5.5 | paper_hits_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@haiku-5.5 | paper_mrr_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@haiku-5.5 | paper_map_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@haiku-5.5 | coverage_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@haiku-5.5 | all_gold_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@haiku-5.5 | final_answer_em | 89 | 0.6348 | 0.8090 | -0.1742 | [-0.2697, -0.0787] |
| merged/hybrid+rerank+metadata@haiku-5.5 | gold_containment | 89 | 0.7640 | 0.9213 | -0.1573 | [-0.2303, -0.0899] |
| merged/hybrid+rerank+metadata@haiku-5.5 | final_answer_missing_rate | 89 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+rerank+metadata@haiku-5.5 | abstention_rate_g | 89 | 0.2135 | 0.1180 | 0.0955 | [0.0169, 0.1798] |
| merged/hybrid+rerank+metadata@haiku-5.5 | prompt_tokens_mean | 89 | 6647.4944 | 3778.3146 | 2869.1798 | [2838.7865, 2899.1124] |
| merged/hybrid+rerank+metadata@haiku-5.5 | latency_total_ms_mean | 89 | 0.0000 | 1667.6292 | -1667.6292 | [-1731.6798, -1602.5787] |
| merged/hybrid+rerank+metadata@haiku-5.5 | retrieve_node_ms_mean | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@haiku-5.5 | spend_usd_mean | 89 | 0.0004 | 0.0011 | -0.0006 | [-0.0007, -0.0006] |
| merged/hybrid+rerank+metadata@haiku-5.5 | context_tokens_mean | 89 | 1747.6854 | 1747.6854 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | paper_hits_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | paper_mrr_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | paper_map_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | coverage_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | all_gold_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | final_answer_em | 89 | 0.7191 | 0.8090 | -0.0899 | [-0.1685, -0.0112] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | gold_containment | 89 | 0.8652 | 0.9213 | -0.0562 | [-0.1180, 0.0000] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | final_answer_missing_rate | 89 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | abstention_rate_g | 89 | 0.1348 | 0.1180 | 0.0169 | [-0.0449, 0.0843] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | prompt_tokens_mean | 89 | 6647.4944 | 3778.3146 | 2869.1798 | [2838.7865, 2899.1124] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | latency_total_ms_mean | 89 | 0.0000 | 1667.6292 | -1667.6292 | [-1731.6798, -1602.5787] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | retrieve_node_ms_mean | 0 | n/a | n/a | n/a | [n/a, n/a] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | spend_usd_mean | 89 | 0.0090 | 0.0011 | 0.0079 | [0.0078, 0.0080] |
| merged/hybrid+rerank+metadata@sonnet-5.5 | context_tokens_mean | 89 | 1747.6854 | 1747.6854 | 0.0000 | [0.0000, 0.0000] |

## Context per arm (D-250; descriptive, decides nothing)

| arm | n | evidence_hits_at_4 | context_tokens_mean | prompt_tokens_mean (not compared) |
| --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 90 | 0.9000 | 1748.7 | 3778.8 |
| merged/hybrid+rerank+metadata@haiku-5.5 | 90 | n/a | 1748.7 | 6647.4 |
| merged/hybrid+rerank+metadata@sonnet-5.5 | 90 | n/a | 1748.7 | 6647.4 |
| merged/hybrid+rerank+metadata@opus-5.5 | 90 | n/a | 1748.7 | 6648.4 |

## Rerank operation

| arm | attempts | degrades | rate | timeout | status | malformed | transport | unknown | p50 ms | p95 ms | max ms | cost credits | calls without cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 361.5 | 716.0 | 1259.0 | 0.027831 | 0 |
| merged/hybrid+rerank+metadata@haiku-5.5 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | 0.000000 | 0 |
| merged/hybrid+rerank+metadata@sonnet-5.5 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | 0.000000 | 0 |
| merged/hybrid+rerank+metadata@opus-5.5 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | 0.000000 | 0 |

## Provenance and retry counts

| arm | records | (h) failures | (j) failures | (i) degraded | query_embedding_retries |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 100 | 0 | 0 | 0 | 0 |
| merged/hybrid+rerank+metadata@haiku-5.5 | 100 | 0 | 0 | 0 | 0 |
| merged/hybrid+rerank+metadata@sonnet-5.5 | 100 | 0 | 0 | 0 | 0 |
| merged/hybrid+rerank+metadata@opus-5.5 | 100 | 0 | 0 | 0 | 0 |

## Readers of `merged/hybrid+rerank+metadata` (D-257; direction-finding, D-252)

Every reader is scored on the same G questions: the ones every reader of the group is ok on (a reader replaying a rerank-degraded context is dropped with its base). cost per answered question = sync list price x the reader's tokens over those questions, divided by its answer_usable answers among them; the retrieval every reader shares is left out. The batch spend is the reader's actual usage at the batch rate (0.5 x the sync price), apart from the comparison.

| arm | reader | answer_usable (G) | n | excluded | price in/out per MTok | sync USD | answered | USD per answered question | batch spend USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | engine (carried) | 0.8483 | 89 | 1 | 0.0448 / 0.3000 (preregistration) | 0.046943 | 151 | 0.000311 | 0.026542 |
| merged/hybrid+rerank+metadata@haiku-5.5 | haiku-5.5 | 0.6629 | 89 | 1 | 0.1000 / 0.5000 (preregistration) | 0.154737 | 118 | 0.001311 | 0.086276 |
| merged/hybrid+rerank+metadata@sonnet-5.5 | sonnet-5.5 | 0.7921 | 89 | 1 | 2.0000 / 10.0000 (preregistration) | 3.202848 | 141 | 0.022715 | 1.788223 |
| merged/hybrid+rerank+metadata@opus-5.5 | opus-5.5 | 0.8258 | 89 | 1 | 4.0000 / 20.0000 (preregistration) | 6.185968 | 147 | 0.042081 | 3.461946 |

Every row is scored on the 89 of 90 G questions every reader is ok on, so each row excludes the questions any reader drops: `merged/hybrid+rerank+metadata` drops 1 (failure 1); `merged/hybrid+rerank+metadata@haiku-5.5` drops 0; `merged/hybrid+rerank+metadata@sonnet-5.5` drops 0; `merged/hybrid+rerank+metadata@opus-5.5` drops 0. The paired differences below keep their own pairwise populations.

Paired `answer_usable` differences on G; exact paired sign-flip p, reported, not used (direction-finding, D-252).

| arm - against | n_pairs | delta | 95% CI | n_pos/n_neg | raw p |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata@haiku-5.5 - merged/hybrid+rerank+metadata | 89 | -0.1854 | [-0.2753, -0.1011] | 6/27 | 0.0001 |
| merged/hybrid+rerank+metadata@sonnet-5.5 - merged/hybrid+rerank+metadata | 89 | -0.0562 | [-0.1292, 0.0112] | 6/10 | 0.1561 |
| merged/hybrid+rerank+metadata@opus-5.5 - merged/hybrid+rerank+metadata | 89 | -0.0225 | [-0.0843, 0.0393] | 6/8 | 0.6028 |
| merged/hybrid+rerank+metadata@sonnet-5.5 - merged/hybrid+rerank+metadata@haiku-5.5 | 90 | 0.1389 | [0.0611, 0.2222] | 19/5 | 0.0017 |
| merged/hybrid+rerank+metadata@opus-5.5 - merged/hybrid+rerank+metadata@haiku-5.5 | 90 | 0.1722 | [0.0889, 0.2611] | 21/5 | 0.0002 |
| merged/hybrid+rerank+metadata@opus-5.5 - merged/hybrid+rerank+metadata@sonnet-5.5 | 90 | 0.0333 | [-0.0056, 0.0833] | 4/2 | 0.2500 |

Null guard of each reader against every other reader.

| arm | against | N pairs | b | c | net loss | status |
| --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | merged/hybrid+rerank+metadata@haiku-5.5 | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata | merged/hybrid+rerank+metadata@sonnet-5.5 | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata | merged/hybrid+rerank+metadata@opus-5.5 | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@haiku-5.5 | merged/hybrid+rerank+metadata | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@haiku-5.5 | merged/hybrid+rerank+metadata@sonnet-5.5 | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@haiku-5.5 | merged/hybrid+rerank+metadata@opus-5.5 | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@sonnet-5.5 | merged/hybrid+rerank+metadata | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@sonnet-5.5 | merged/hybrid+rerank+metadata@haiku-5.5 | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@sonnet-5.5 | merged/hybrid+rerank+metadata@opus-5.5 | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@opus-5.5 | merged/hybrid+rerank+metadata | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@opus-5.5 | merged/hybrid+rerank+metadata@haiku-5.5 | 20 | 0 | 0 | 0.0000 | PASS |
| merged/hybrid+rerank+metadata@opus-5.5 | merged/hybrid+rerank+metadata@sonnet-5.5 | 20 | 0 | 0 | 0.0000 | PASS |

## Default decisions (D-150, O16)

| lever | decision | answer_usable | delta | Hits@4 support | reasons |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata@haiku-5.5 | significantly worse, stays off | significant | -0.1854 | n/a (not in the supporting family) | Holm rejection with a negative delta |
| merged/hybrid+rerank+metadata@sonnet-5.5 | stays off: not significant | not significant | -0.0562 | n/a (not in the supporting family) | no Holm rejection |

If two levers win, D-157 flips both. The combination is never tested decisionally; hybrid+all is its only, descriptive, evidence.
