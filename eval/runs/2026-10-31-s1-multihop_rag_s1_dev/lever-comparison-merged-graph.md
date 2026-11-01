# Lever comparison: multihop_rag_s1_dev

- Run: `2026-10-31-s1-multihop_rag_s1_dev`; pre-registration `PREREGISTRATION_S1`; reference arm `merged/hybrid+rerank+metadata`.
- No judge ran and no judged figure exists in this phase (D-153).
- dev population: |H_G| = 90, |H_N| = 10; coverage floor 0.8 per comparison (exact).
- `report.json` cells are on the all-arm P_all, not the decisional population.

## Familywise error

Two Holm families, one per primary, each at its family-wise error rate (m fixed at the registered arm count). Across both families the family-wise error rate can reach 0.10 (the Bonferroni bound over two families), and this report states it. Defaults read only the decisional family (at most 0.05). The guards can only veto a rejection, so they never raise the error rate.

Bootstrap CIs are 95% percentile intervals, labelled 'unadjusted, estimation only'. A CI that excludes 0 without a Holm rejection is not significant.

## Holm family `answer_usable` (decisional; m = 1, alpha = 0.05)

| arm | n (P_X) | coverage | n_pos | n_neg | p | Holm p | decision | delta | 95% CI (unadjusted, estimation only) | mean arm | mean hybrid on P_X |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+graph+rerank+metadata | 90 | 1.000 | 2 | 5 | 0.4531 | 0.4531 | not significant | -0.0333 | [-0.0889, 0.0222] | 0.8333 | 0.8667 |

| arm | own failure | own provenance | reference-only failure | sum (= |H_G| - n) | of which rerank degrade | of which reference own failure | of which reference provenance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+graph+rerank+metadata | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Guard 1: null-abstention paired drop (D-148)

| arm | decisional | predicate | N_X | needs | b | c | net loss | margin | reading | one-sided 95% bound | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+graph+rerank+metadata | True | `metrics.is_abstention` | 10 | 8 | 0 | 0 | 0.0000 | 0.1 | PASS | 0.0000 | net loss 0 of 10, at most the margin 0.1 |

## Guard 2: answer-mix disclosure (reported only)

### merged/hybrid+graph+rerank+metadata

_reported only, never decisional; beating constant-Yes is not a default condition_

| subset | n | side | yes | no | insufficient | other |
| --- | --- | --- | --- | --- | --- | --- |
| comparison_query | 36 | arm | 0.611 | 0.194 | 0.111 | 0.083 |
| comparison_query | 36 | hybrid | 0.611 | 0.222 | 0.083 | 0.083 |
| comparison_query | 36 | gold | 0.667 | 0.278 | - | 0.056 |
| comparison_query | 36 | constant-Yes / constant-No answer_usable | 0.667 | 0.278 | - | - |
| binary_gold | 56 | arm | 0.589 | 0.179 | 0.143 | 0.089 |
| binary_gold | 56 | hybrid | 0.607 | 0.214 | 0.143 | 0.036 |
| binary_gold | 56 | gold | 0.661 | 0.339 | - | 0.000 |
| binary_gold | 56 | constant-Yes / constant-No answer_usable | 0.661 | 0.339 | - | - |

| stratum | abstain->correct | wrong->correct | correct->wrong | correct->abstain | answer->abstain | n |
| --- | --- | --- | --- | --- | --- | --- |
| all | 2 | 0 | 2 | 3 | 3 | 90 |
| comparison_query | 0 | 0 | 2 | 2 | 2 | 36 |
| inference_query | 0 | 0 | 0 | 0 | 0 | 31 |
| temporal_query | 2 | 0 | 0 | 1 | 1 | 23 |

Non-binary gold (n = 34): arm 0.9412, hybrid 0.9412, delta 0.0000 [0.0000, 0.0000] (unadjusted, estimation only).

## D-140 descriptive rows

| row | n | primary | delta | 95% CI (unadjusted, estimation only) | n_pos | n_neg | label |
| --- | --- | --- | --- | --- | --- | --- | --- |

| graph-on arm | records | degree_capped_count |
| --- | --- | --- |
| merged/hybrid+graph+rerank+metadata | 100 | 279 |
| small/hybrid+graph+rerank+metadata | 100 | 362 |

## Sensitivity: P_dec (sensitivity line, decides nothing)

P_dec: ok on the reference and on every decisional lever arm; n = 90, coverage 1.000.

| arm | n | p | Holm p | decision | delta |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+graph+rerank+metadata | 90 | 0.4531 | 0.4531 | not significant | -0.0333 |

## Secondaries on P_X (no p-value; unadjusted, estimation only)

| arm | metric | n | mean arm | mean hybrid | delta | 95% CI |
| --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+graph+rerank+metadata | paper_hits_at_10 | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+graph+rerank+metadata | paper_mrr_at_10 | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+graph+rerank+metadata | paper_map_at_10 | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+graph+rerank+metadata | coverage_at_4 | 90 | 0.5648 | 0.5648 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+graph+rerank+metadata | all_gold_at_4 | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+graph+rerank+metadata | final_answer_em | 90 | 0.7778 | 0.8444 | -0.0667 | [-0.1333, 0.0000] |
| merged/hybrid+graph+rerank+metadata | gold_containment | 90 | 0.9000 | 0.9444 | -0.0444 | [-0.0889, -0.0111] |
| merged/hybrid+graph+rerank+metadata | final_answer_missing_rate | 90 | 0.0000 | 0.0000 | 0.0000 | [0.0000, 0.0000] |
| merged/hybrid+graph+rerank+metadata | abstention_rate_g | 90 | 0.1000 | 0.1000 | 0.0000 | [-0.0556, 0.0556] |
| merged/hybrid+graph+rerank+metadata | prompt_tokens_mean | 90 | 3963.2222 | 3778.8444 | 184.3778 | [141.2000, 229.2000] |
| merged/hybrid+graph+rerank+metadata | latency_total_ms_mean | 90 | 3752.7333 | 3339.3556 | 413.3778 | [241.8667, 582.1889] |
| merged/hybrid+graph+rerank+metadata | retrieve_node_ms_mean | 90 | 687.8111 | 623.5111 | 64.3000 | [22.2000, 107.5556] |
| merged/hybrid+graph+rerank+metadata | spend_usd_mean | 90 | 0.0012 | 0.0012 | 0.0000 | [-0.0000, 0.0000] |
| merged/hybrid+graph+rerank+metadata | context_tokens_mean | 90 | 1747.8556 | 1748.7111 | -0.8556 | [-2.5667, 0.0000] |

## Context per arm (D-250; descriptive, decides nothing)

| arm | n | evidence_hits_at_4 | context_tokens_mean | prompt_tokens_mean (not compared) |
| --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 90 | 0.9000 | 1748.7 | 3778.8 |
| merged/hybrid+graph+rerank+metadata | 90 | 0.9000 | 1747.9 | 3963.2 |
| small/hybrid+rerank+metadata | 90 | 0.9000 | 565.6 | 2549.0 |
| small/hybrid+graph+rerank+metadata | 90 | 0.9000 | 565.6 | 2754.3 |

## Rerank operation

| arm | attempts | degrades | rate | timeout | status | malformed | transport | unknown | p50 ms | p95 ms | max ms | cost credits | calls without cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 361.5 | 716.0 | 1259.0 | 0.027831 | 0 |
| merged/hybrid+graph+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 367.0 | 656.8 | 1231.0 | 0.028654 | 0 |
| small/hybrid+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 276.0 | 400.5 | 710.0 | 0.012909 | 0 |
| small/hybrid+graph+rerank+metadata | 100 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 280.5 | 440.4 | 792.0 | 0.013613 | 0 |

## Provenance and retry counts

| arm | records | (h) failures | (j) failures | (i) degraded | query_embedding_retries |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+rerank+metadata | 100 | 0 | 0 | 0 | 0 |
| merged/hybrid+graph+rerank+metadata | 100 | 0 | 0 | 0 | 0 |
| small/hybrid+rerank+metadata | 100 | 0 | 0 | 0 | 0 |
| small/hybrid+graph+rerank+metadata | 100 | 0 | 0 | 0 | 0 |

## Default decisions (D-150, O16)

| lever | decision | answer_usable | delta | Hits@4 support | reasons |
| --- | --- | --- | --- | --- | --- |
| merged/hybrid+graph+rerank+metadata | stays off: not significant | not significant | -0.0333 | n/a (not in the supporting family) | no Holm rejection |

If two levers win, D-157 flips both. The combination is never tested decisionally; hybrid+all is its only, descriptive, evidence.
