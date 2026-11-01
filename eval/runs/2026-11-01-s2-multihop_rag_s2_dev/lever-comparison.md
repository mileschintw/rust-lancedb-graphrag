# Lever comparison: multihop_rag_s2_dev

- Run: `2026-11-01-s2-multihop_rag_s2_dev`; pre-registration `PREREGISTRATION_S2`; reference arm `small/hybrid+rerank+metadata`.
- No judge ran and no judged figure exists in this phase (D-153).
- dev population: |H_G| = 90, |H_N| = 10; coverage floor 0.8 per comparison (exact).
- `report.json` cells are on the all-arm P_all, not the decisional population.

## Familywise error

Two Holm families, one per primary, each at its family-wise error rate (m fixed at the registered arm count). Across both families the family-wise error rate can reach 0.10 (the Bonferroni bound over two families), and this report states it. Defaults read only the decisional family (at most 0.05). The guards can only veto a rejection, so they never raise the error rate.

Bootstrap CIs are 95% percentile intervals, labelled 'unadjusted, estimation only'. A CI that excludes 0 without a Holm rejection is not significant.

## Holm family `answer_usable` (decisional; m = 2, alpha = 0.05)

| arm | n (P_X) | coverage | n_pos | n_neg | p | Holm p | decision | delta | 95% CI (unadjusted, estimation only) | mean arm | mean hybrid on P_X |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata@haiku-5.5 | 90 | 1.000 | 6 | 28 | 0.0000 | 0.0001 | significant | -0.1600 | [-0.2356, -0.0911] | 0.6933 | 0.8533 |
| small/hybrid+rerank+metadata@sonnet-5.5 | 90 | 1.000 | 7 | 14 | 0.0613 | 0.0613 | not significant (CI excludes 0; not significant after Holm) | -0.0622 | [-0.1267, -0.0044] | 0.7911 | 0.8533 |

| arm | own failure | own provenance | reference-only failure | sum (= |H_G| - n) | of which rerank degrade | of which reference own failure | of which reference provenance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata@haiku-5.5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| small/hybrid+rerank+metadata@sonnet-5.5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Guard 1: null-abstention paired drop (D-148)

| arm | decisional | predicate | N_X | needs | b | c | net loss | margin | reading | one-sided 95% bound | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata@haiku-5.5 | True | `metrics.is_abstention` | 35 | 40 | 0 | 0 | 0.0000 | 0.1 | NOT EVALUABLE (fails closed) | 0.0000 | 35 null pairs, fewer than the 40 needed (ceil(0.8 x 50)) |
| small/hybrid+rerank+metadata@sonnet-5.5 | True | `metrics.is_abstention` | 35 | 40 | 0 | 0 | 0.0000 | 0.1 | NOT EVALUABLE (fails closed) | 0.0000 | 35 null pairs, fewer than the 40 needed (ceil(0.8 x 50)) |

## Guard 2: answer-mix disclosure (reported only)

### small/hybrid+rerank+metadata@haiku-5.5

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 36 | arm | 0.417 | 0.333 | 0.194 | 0.056 |
| comparison_query | 36 | hybrid | 0.639 | 0.194 | 0.083 | 0.083 |
| comparison_query | 36 | gold | 0.667 | 0.278 | - | 0.056 |
| comparison_query | 36 | constant-Yes / constant-No answer_usable | 0.667 | 0.278 | - | - |
| binary_gold | 56 | arm | 0.429 | 0.286 | 0.268 | 0.018 |
| binary_gold | 56 | hybrid | 0.607 | 0.196 | 0.125 | 0.071 |
| binary_gold | 56 | gold | 0.661 | 0.339 | - | 0.000 |
| binary_gold | 56 | constant-Yes / constant-No answer_usable | 0.661 | 0.339 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 1 | 0 | 6 | 14 | 14 | 90 |
| comparison_query | 0 | 0 | 4 | 5 | 5 | 36 |
| inference_query | 0 | 0 | 0 | 4 | 4 | 31 |
| temporal_query | 1 | 0 | 2 | 5 | 5 | 23 |

Non-binary gold (n = 34): arm 0.8529, hybrid 0.9706, delta -0.1176 [-0.2353, -0.0294] (unadjusted, estimation only).

### small/hybrid+rerank+metadata@sonnet-5.5

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 36 | arm | 0.444 | 0.250 | 0.194 | 0.111 |
| comparison_query | 36 | hybrid | 0.639 | 0.194 | 0.083 | 0.083 |
| comparison_query | 36 | gold | 0.667 | 0.278 | - | 0.056 |
| comparison_query | 36 | constant-Yes / constant-No answer_usable | 0.667 | 0.278 | - | - |
| binary_gold | 56 | arm | 0.429 | 0.268 | 0.250 | 0.054 |
| binary_gold | 56 | hybrid | 0.607 | 0.196 | 0.125 | 0.071 |
| binary_gold | 56 | gold | 0.661 | 0.339 | - | 0.000 |
| binary_gold | 56 | constant-Yes / constant-No answer_usable | 0.661 | 0.339 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 1 | 0 | 2 | 9 | 9 | 90 |
| comparison_query | 0 | 0 | 2 | 5 | 5 | 36 |
| inference_query | 0 | 0 | 0 | 0 | 0 | 31 |
| temporal_query | 1 | 0 | 0 | 4 | 4 | 23 |

Non-binary gold (n = 34): arm 0.9706, hybrid 0.9706, delta 0.0000 [0.0000, 0.0000] (unadjusted, estimation only).

## D-140 descriptive rows

| row | n | primary | delta | 95% CI (unadjusted, estimation only) | n_pos | n_neg | label |
| --- | --- | --- | --- | --- | --- | --- | --- |

| graph-on arm | records | degree_capped_count |
| --- | --- | --- |

## Sensitivity: P_dec (sensitivity line, decides nothing)

P_dec: ok on the reference and on every decisional lever arm; n = 90, coverage 1.000.

| arm | n | p | Holm p | decision | delta |
| --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata@haiku-5.5 | 90 | 0.0000 | 0.0001 | significant | -0.1600 |
| small/hybrid+rerank+metadata@sonnet-5.5 | 90 | 0.0613 | 0.0613 | not significant | -0.0622 |

## Secondaries on P_X (no p-value; unadjusted, estimation only)

| arm | metric | n | mean arm | mean hybrid | delta | 95% CI |
| --- | --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata@haiku-5.5 | paper_hits_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@haiku-5.5 | paper_mrr_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@haiku-5.5 | paper_map_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@haiku-5.5 | coverage_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@haiku-5.5 | all_gold_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@haiku-5.5 | final_answer_em | 90 | 0.6667 | 0.7800 | -0.1133 | [-0.2000, -0.0333] |
| small/hybrid+rerank+metadata@haiku-5.5 | gold_containment | 90 | 0.7844 | 0.9244 | -0.1400 | [-0.2089, -0.0756] |
| small/hybrid+rerank+metadata@haiku-5.5 | final_answer_missing_rate | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| small/hybrid+rerank+metadata@haiku-5.5 | abstention_rate_g | 90 | 0.1867 | 0.1089 | 0.0778 | [0.0200, 0.1400] |
| small/hybrid+rerank+metadata@haiku-5.5 | prompt_tokens_mean | 90 | 4724.8556 | 2548.9556 | 2175.9000 | [2155.8556, 2195.4333] |
| small/hybrid+rerank+metadata@haiku-5.5 | latency_total_ms_mean | 90 | 0.0000 | 726.4022 | -726.4022 | [-772.8822, -687.1800] |
| small/hybrid+rerank+metadata@haiku-5.5 | retrieve_node_ms_mean | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@haiku-5.5 | spend_usd_mean | 90 | 0.0003 | 0.0008 | -0.0004 | [-0.0005, -0.0004] |
| small/hybrid+rerank+metadata@haiku-5.5 | context_tokens_mean | 90 | 565.5889 | 565.5889 | 0.0000 | [0.0000, 0.0000] |
| small/hybrid+rerank+metadata@sonnet-5.5 | paper_hits_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@sonnet-5.5 | paper_mrr_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@sonnet-5.5 | paper_map_at_10 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@sonnet-5.5 | coverage_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@sonnet-5.5 | all_gold_at_4 | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@sonnet-5.5 | final_answer_em | 90 | 0.7378 | 0.7800 | -0.0422 | [-0.1178, 0.0267] |
| small/hybrid+rerank+metadata@sonnet-5.5 | gold_containment | 90 | 0.8422 | 0.9244 | -0.0822 | [-0.1444, -0.0267] |
| small/hybrid+rerank+metadata@sonnet-5.5 | final_answer_missing_rate | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| small/hybrid+rerank+metadata@sonnet-5.5 | abstention_rate_g | 90 | 0.1667 | 0.1089 | 0.0578 | [0.0022, 0.1178] |
| small/hybrid+rerank+metadata@sonnet-5.5 | prompt_tokens_mean | 90 | 4724.8556 | 2548.9556 | 2175.9000 | [2155.8556, 2195.4333] |
| small/hybrid+rerank+metadata@sonnet-5.5 | latency_total_ms_mean | 90 | 0.0000 | 726.4022 | -726.4022 | [-772.8822, -687.1800] |
| small/hybrid+rerank+metadata@sonnet-5.5 | retrieve_node_ms_mean | 0 | n/a | n/a | n/a | [n/a, n/a] |
| small/hybrid+rerank+metadata@sonnet-5.5 | spend_usd_mean | 90 | 0.0071 | 0.0008 | 0.0063 | [0.0062, 0.0064] |
| small/hybrid+rerank+metadata@sonnet-5.5 | context_tokens_mean | 90 | 565.5889 | 565.5889 | 0.0000 | [0.0000, 0.0000] |

## Context per arm (D-250; descriptive, decides nothing)

| arm | n | evidence_hits_at_4 | context_tokens_mean | prompt_tokens_mean (not compared) |
| --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata | 90 | 0.9000 | 565.6 | 2549.0 |
| small/hybrid+rerank+metadata@haiku-5.5 | 90 | n/a | 565.6 | 4724.9 |
| small/hybrid+rerank+metadata@sonnet-5.5 | 90 | n/a | 565.6 | 4724.9 |
| small/hybrid+rerank+metadata@opus-5.5 | 90 | n/a | 565.6 | 4725.9 |

## Rerank operation

| arm | attempts | degrades | rate | timeout | status | malformed | transport | unknown | p50 ms | p95 ms | max ms | cost credits | calls without cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 276.0 | 400.5 | 710.0 | 0.012909 | 0 |
| small/hybrid+rerank+metadata@haiku-5.5 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | 0.000000 | 0 |
| small/hybrid+rerank+metadata@sonnet-5.5 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | 0.000000 | 0 |
| small/hybrid+rerank+metadata@opus-5.5 | 0 | 0 | n/a | 0 | 0 | 0 | 0 | 0 | n/a | n/a | n/a | 0.000000 | 0 |

## Provenance and retry counts

| arm | records | (h) failures | (j) failures | (i) degraded | query_embedding_retries |
| --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata | 100 | 0 | 0 | 0 | 0 |
| small/hybrid+rerank+metadata@haiku-5.5 | 100 | 0 | 0 | 0 | 0 |
| small/hybrid+rerank+metadata@sonnet-5.5 | 100 | 0 | 0 | 0 | 0 |
| small/hybrid+rerank+metadata@opus-5.5 | 100 | 0 | 0 | 0 | 0 |

## Readers of `small/hybrid+rerank+metadata` (D-257; direction-finding, D-252)

Every reader is scored on the same G questions: the ones every reader of the group is ok on (a reader replaying a rerank-degraded context is dropped with its base). cost per answered question = sync list price x the reader's tokens over those questions, divided by its answer_usable answers among them; the retrieval every reader shares is left out. The batch spend is the reader's actual usage at the batch rate (0.5 x the sync price), apart from the comparison.

| arm | reader | answer_usable (G) | n | excluded | price in/out per MTok | sync USD | answered | USD per answered question | batch spend USD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata | engine (carried) | 0.8533 | 90 | 0 | 0.0448 / 0.3000 (preregistration) | 0.091956 | 384 | 0.000239 | 0.080632 |
| small/hybrid+rerank+metadata@haiku-5.5 | haiku-5.5 | 0.6933 | 90 | 0 | 0.1000 / 0.5000 (preregistration) | 0.303928 | 312 | 0.000974 | 0.166836 |
| small/hybrid+rerank+metadata@sonnet-5.5 | sonnet-5.5 | 0.7911 | 90 | 0 | 2.0000 / 10.0000 (preregistration) | 6.371660 | 356 | 0.017898 | 3.511075 |
| small/hybrid+rerank+metadata@opus-5.5 | opus-5.5 | 0.8244 | 90 | 0 | 4.0000 / 20.0000 (preregistration) | 12.219200 | 371 | 0.032936 | 6.752350 |

Every row is scored on the 90 of 90 G questions every reader is ok on, so each row excludes the questions any reader drops: `small/hybrid+rerank+metadata` drops 0; `small/hybrid+rerank+metadata@haiku-5.5` drops 0; `small/hybrid+rerank+metadata@sonnet-5.5` drops 0; `small/hybrid+rerank+metadata@opus-5.5` drops 0. The paired differences below keep their own pairwise populations.

Paired `answer_usable` differences on G; exact paired sign-flip p, reported, not used (direction-finding, D-252).

| arm - against | n_pairs | delta | 95% CI | n_pos/n_neg | raw p |
| --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata@haiku-5.5 - small/hybrid+rerank+metadata | 90 | -0.1600 | [-0.2356, -0.0911] | 6/28 | 0.0000 |
| small/hybrid+rerank+metadata@sonnet-5.5 - small/hybrid+rerank+metadata | 90 | -0.0622 | [-0.1267, -0.0044] | 7/14 | 0.0613 |
| small/hybrid+rerank+metadata@opus-5.5 - small/hybrid+rerank+metadata | 90 | -0.0289 | [-0.0844, 0.0222] | 8/9 | 0.3527 |
| small/hybrid+rerank+metadata@sonnet-5.5 - small/hybrid+rerank+metadata@haiku-5.5 | 90 | 0.0978 | [0.0378, 0.1622] | 17/5 | 0.0024 |
| small/hybrid+rerank+metadata@opus-5.5 - small/hybrid+rerank+metadata@haiku-5.5 | 90 | 0.1311 | [0.0711, 0.1978] | 22/3 | 0.0001 |
| small/hybrid+rerank+metadata@opus-5.5 - small/hybrid+rerank+metadata@sonnet-5.5 | 90 | 0.0333 | [0.0089, 0.0644] | 6/0 | 0.0312 |

Null guard of each reader against every other reader.

| arm | against | N pairs | b | c | net loss | status |
| --- | --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata | small/hybrid+rerank+metadata@haiku-5.5 | 35 | 0 | 0 | 0.0000 | NOT EVALUABLE (fails closed) |
| small/hybrid+rerank+metadata | small/hybrid+rerank+metadata@sonnet-5.5 | 35 | 0 | 0 | 0.0000 | NOT EVALUABLE (fails closed) |
| small/hybrid+rerank+metadata | small/hybrid+rerank+metadata@opus-5.5 | 35 | 0 | 0 | 0.0000 | NOT EVALUABLE (fails closed) |
| small/hybrid+rerank+metadata@haiku-5.5 | small/hybrid+rerank+metadata | 35 | 0 | 0 | 0.0000 | NOT EVALUABLE (fails closed) |
| small/hybrid+rerank+metadata@haiku-5.5 | small/hybrid+rerank+metadata@sonnet-5.5 | 50 | 0 | 0 | 0.0000 | PASS |
| small/hybrid+rerank+metadata@haiku-5.5 | small/hybrid+rerank+metadata@opus-5.5 | 50 | 0 | 0 | 0.0000 | PASS |
| small/hybrid+rerank+metadata@sonnet-5.5 | small/hybrid+rerank+metadata | 35 | 0 | 0 | 0.0000 | NOT EVALUABLE (fails closed) |
| small/hybrid+rerank+metadata@sonnet-5.5 | small/hybrid+rerank+metadata@haiku-5.5 | 50 | 0 | 0 | 0.0000 | PASS |
| small/hybrid+rerank+metadata@sonnet-5.5 | small/hybrid+rerank+metadata@opus-5.5 | 50 | 0 | 0 | 0.0000 | PASS |
| small/hybrid+rerank+metadata@opus-5.5 | small/hybrid+rerank+metadata | 35 | 0 | 0 | 0.0000 | NOT EVALUABLE (fails closed) |
| small/hybrid+rerank+metadata@opus-5.5 | small/hybrid+rerank+metadata@haiku-5.5 | 50 | 0 | 0 | 0.0000 | PASS |
| small/hybrid+rerank+metadata@opus-5.5 | small/hybrid+rerank+metadata@sonnet-5.5 | 50 | 0 | 0 | 0.0000 | PASS |

## Default decisions (D-150, O16)

| lever | decision | answer_usable | delta | Hits@4 support | reasons |
| --- | --- | --- | --- | --- | --- |
| small/hybrid+rerank+metadata@haiku-5.5 | significantly worse, stays off | significant | -0.1600 | n/a (not in the supporting family) | Holm rejection with a negative delta |
| small/hybrid+rerank+metadata@sonnet-5.5 | stays off: not significant | not significant | -0.0622 | n/a (not in the supporting family) | no Holm rejection |

If two levers win, D-157 flips both. The combination is never tested decisionally; hybrid+all is its only, descriptive, evidence.
