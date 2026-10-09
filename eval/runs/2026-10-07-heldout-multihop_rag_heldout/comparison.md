# Four-arm comparison: multihop_rag_heldout

Run `2026-10-07-heldout-multihop_rag_heldout`, run date 2026-10-08T07:41:26.575929+00:00, commit `f79de2b9f92144357c8db5bd68bce35b909dcae9`, index generation `lance-702`. Generation of this file is offline: it reads `report.json` and `judged-result.json`, and computes only the two pre-registered inference families and the per-type deltas of the primaries.

Arms: dense-only, bm25-only, hybrid, hybrid+graph. Reference arm: `hybrid`. Judge: `meta-llama/llama-3.3-70b-instruct`, prompt `v1`. Embedding model: `voyageai/voyage-4-large`.

## Population (P4)

P4 is the set of held-out G questions with an ok record on all four arms. |P4| = 296 of 308 held-out G questions (coverage 0.9610; pre-registered complete-case floor 0.8). Null questions (43) feed only the null abstention row.

The coverage floor is met, so both primary families are evaluable.

Exclusions per arm, by reason, beside each pairwise join size with `hybrid`:

| arm | own failure | provenance | other arm's failure | pairwise join |
| --- | --- | --- | --- | --- |
| dense-only | 5 | 0 | 7 | 298 |
| bm25-only | 0 | 0 | 12 | 303 |
| hybrid | 5 | 0 | 7 | - |
| hybrid+graph | 2 | 0 | 10 | 301 |


## Pre-registered inference: two Holm families

Two Holm families, one per primary, each at familywise error rate 0.05 (m = 3). Across both primaries the familywise error rate can reach 0.10 (the Bonferroni bound), and this report states it.

Test: the exact two-sided paired sign-flip test (the exact McNemar test) over the discordant pairs of the per-question 0/1 values on P4, then Holm step-down per family at familywise error rate 0.05. Only a Holm rejection is printed as significant. A CI that excludes 0 without a Holm rejection is printed as exactly that, and every CI below is unadjusted, estimation only. Results are published in either direction (D-49).

### Family: `paper_hits_at_4` (ID rule)

| comparison | n pairs | discordant (+/-) | raw p (exact) | Holm-adjusted p | decision | delta | 95% CI (unadjusted, estimation only) | note | text-rule decision | matching-rule robustness |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dense-only - hybrid | 296 | 37/22 | 0.0674 | 0.1349 | not significant | 0.0507 | [0.0000, 0.1014] |  | not significant | robust to the matching rule |
| bm25-only - hybrid | 296 | 14/51 | 0.0000 | 0.0000 | significant | -0.1250 | [-0.1757, -0.0743] |  | significant | robust to the matching rule |
| hybrid+graph - hybrid | 296 | 6/9 | 0.6072 | 0.6072 | not significant | -0.0101 | [-0.0372, 0.0169] |  | not significant | robust to the matching rule |


### Family: `answer_usable` (on P4)

| comparison | n pairs | discordant (+/-) | raw p (exact) | Holm-adjusted p | decision | delta | 95% CI (unadjusted, estimation only) | note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dense-only - hybrid | 296 | 27/24 | 0.7798 | 1.0000 | not significant | 0.0101 | [-0.0372, 0.0574] |  |
| bm25-only - hybrid | 296 | 7/60 | 0.0000 | 0.0000 | significant | -0.1791 | [-0.2297, -0.1284] |  |
| hybrid+graph - hybrid | 296 | 15/18 | 0.7283 | 1.0000 | not significant | -0.0101 | [-0.0507, 0.0270] |  |


## Matching-rule cross-check (D-102)

The paper metrics were recomputed under the official text rule at index generation `lance-702` (official script commit `c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8`). Holm was re-run on the text-rule `paper_hits_at_4` values; a decision that differs reads `not robust to the matching rule` in the table above. Records whose figure differs between the two rules, per arm, over P4:

| arm | P4 n | hit@4 differs | hit@10 differs | first-hit rank differs | AP differs |
| --- | --- | --- | --- | --- | --- |
| dense-only | 296 | 0 | 0 | 0 | 1 |
| bm25-only | 296 | 0 | 0 | 0 | 0 |
| hybrid | 296 | 0 | 0 | 0 | 0 |
| hybrid+graph | 296 | 0 | 0 | 0 | 1 |


## Four-arm table

Every per-arm figure is on P4 unless its row says otherwise. Intervals are Wilson for rates and percentile bootstrap (B = 10000, seed 42) for means.

### Retrieval, paper convention (ID rule on the D-100 pre-truncation ranking) and the cited reference rows

| row | Hits@4 | Hits@10 | MRR@10 | MAP@10 | label |
| --- | --- | --- | --- | --- | --- |
| dense-only (P4) | 0.7399 [0.6870, 0.7865] (n=296) | 0.8514 [0.8063, 0.8874] (n=296) | 0.5620 [0.5174, 0.6069] (n=296) | 0.2745 [0.2499, 0.2982] (n=296) | ID rule |
| bm25-only (P4) | 0.5642 [0.5072, 0.6195] (n=296) | 0.6757 [0.6204, 0.7265] (n=296) | 0.4564 [0.4066, 0.5051] (n=296) | 0.2138 [0.1889, 0.2393] (n=296) | ID rule |
| hybrid (P4) | 0.6892 [0.6343, 0.7392] (n=296) | 0.8311 [0.7842, 0.8695] (n=296) | 0.5719 [0.5235, 0.6182] (n=296) | 0.2762 [0.2505, 0.3016] (n=296) | ID rule |
| hybrid+graph (P4) | 0.6791 [0.6239, 0.7297] (n=296) | 0.8108 [0.7623, 0.8513] (n=296) | 0.5362 [0.4880, 0.5820] (n=296) | 0.2589 [0.2338, 0.2845] (n=296) | ID rule |
| dense-only (script-faithful, all 308 G) | 0.7305 [0.6784, 0.7770] (n=308) | 0.8377 [0.7924, 0.8746] (n=308) | 0.5510 [0.5065, 0.5957] (n=308) | 0.2705 [0.2467, 0.2950] (n=308) | ID rule |
| bm25-only (script-faithful, all 308 G) | 0.5714 [0.5156, 0.6255] (n=308) | 0.6851 [0.6312, 0.7344] (n=308) | 0.4616 [0.4131, 0.5110] (n=308) | 0.2170 [0.1925, 0.2419] (n=308) | ID rule |
| hybrid (script-faithful, all 308 G) | 0.6818 [0.6278, 0.7313] (n=308) | 0.8182 [0.7713, 0.8572] (n=308) | 0.5667 [0.5187, 0.6140] (n=308) | 0.2738 [0.2486, 0.2996] (n=308) | ID rule |
| hybrid+graph (script-faithful, all 308 G) | 0.6786 [0.6245, 0.7283] (n=308) | 0.8084 [0.7608, 0.8485] (n=308) | 0.5400 [0.4925, 0.5858] (n=308) | 0.2614 [0.2365, 0.2867] (n=308) | ID rule |
| Paper reference (cited; not comparable, see caveat): bge-large-en-v1.5 | 0.5221 | 0.6718 | 0.4298 | 0.3423 | arXiv 2401.15391 v1, Table 5 |
| Paper reference (cited; not comparable, see caveat): voyage-02 | 0.4619 | 0.6506 | 0.3934 | 0.3143 | arXiv 2401.15391 v1, Table 5 |


### Retrieval, lancet convention (final eight chunks, excerpt matching)

| metric | dense-only | bm25-only | hybrid | hybrid+graph |
| --- | --- | --- | --- | --- |
| `coverage_at_4` | 0.3722 [0.3387, 0.4046] (n=296) | 0.2632 [0.2334, 0.2942] (n=296) | 0.3578 [0.3235, 0.3925] (n=296) | 0.3542 [0.3195, 0.3899] (n=296) |
| `precision_at_4` | 0.2264 [0.2078, 0.2449] (n=296) | 0.1596 [0.1427, 0.1774] (n=296) | 0.2171 [0.1968, 0.2373] (n=296) | 0.2128 [0.1934, 0.2323] (n=296) |


### Answer

| metric | dense-only | bm25-only | hybrid | hybrid+graph |
| --- | --- | --- | --- | --- |
| `answer_usable_p4` | 0.5811 [0.5242, 0.6359] (n=296) | 0.3919 [0.3380, 0.4486] (n=296) | 0.5709 [0.5140, 0.6261] (n=296) | 0.5608 [0.5039, 0.6162] (n=296) |
| `answer_usable_sc3_definition` | 0.5875 [0.5313, 0.6415] (n=303) | 0.3994 [0.3462, 0.4550] (n=308) | 0.5677 [0.5114, 0.6222] (n=303) | 0.5654 [0.5093, 0.6198] (n=306) |
| `final_answer_em` | 0.5608 [0.5039, 0.6162] (n=296) | 0.3818 [0.3283, 0.4383] (n=296) | 0.5574 [0.5005, 0.6129] (n=296) | 0.5574 [0.5005, 0.6129] (n=296) |
| `gold_containment` | 0.6757 [0.6204, 0.7265] (n=296) | 0.5574 [0.5005, 0.6129] (n=296) | 0.6622 [0.6065, 0.7137] (n=296) | 0.6453 [0.5892, 0.6976] (n=296) |
| `final_answer_missing_rate` | 0.0000 [0.0000, 0.0128] (n=296) | 0.0000 [0.0000, 0.0128] (n=296) | 0.0000 [0.0000, 0.0128] (n=296) | 0.0000 [0.0000, 0.0128] (n=296) |


### Abstention (G and null)

| metric | dense-only | bm25-only | hybrid | hybrid+graph |
| --- | --- | --- | --- | --- |
| `abstention_rate_g` | 0.3547 [0.3024, 0.4108] (n=296) | 0.5541 [0.4971, 0.6096] (n=296) | 0.3818 [0.3283, 0.4383] (n=296) | 0.4020 [0.3478, 0.4588] (n=296) |
| `null_abstention_correctness` | 0.9302 [0.8139, 0.9760] (n=43) | 0.9767 [0.8794, 0.9959] (n=43) | 0.9524 [0.8421, 0.9868] (n=42) | 0.9535 [0.8454, 0.9872] (n=43) |


Abstention census per arm, beside the answer_usable and judged rows:

| arm | G abstention rate (n) | null correctness (n) | hallucinated on null | NO_EVIDENCE count | leak count | usable blank answers |
| --- | --- | --- | --- | --- | --- | --- |
| dense-only | 0.3547 (n=296) | 0.9302 (n=43) | 3 | 0 | 0 | 0 |
| bm25-only | 0.5541 (n=296) | 0.9767 (n=43) | 1 | 0 | 0 | 0 |
| hybrid | 0.3818 (n=296) | 0.9524 (n=42) | 2 | 0 | 0 | 0 |
| hybrid+graph | 0.4020 (n=296) | 0.9535 (n=43) | 2 | 0 | 0 | 0 |


### Latency and cost

Latency p50 and p95 are descriptive per-arm values with no delta. The bm25-only latency and cost rows carry no embedding caveat label: D-125 skips the query embedding on the bm25-only arm with the graph off, which resolves AI-SPEC section 3 Pitfall 5.

| metric | dense-only | bm25-only | hybrid | hybrid+graph |
| --- | --- | --- | --- | --- |
| `latency_total_ms_p50` | 9966.5 (n=296) | 9092.0 (n=296) | 9566.0 (n=296) | 9938.0 (n=296) |
| `latency_total_ms_p95` | 15690.2 (n=296) | 13755.8 (n=296) | 14399.2 (n=296) | 14916.8 (n=296) |
| `latency_total_ms_mean` | 10212.9 [9878.8, 10554.7] (n=296) | 9473.2 [9182.1, 9778.2] (n=296) | 9945.8 [9657.2, 10242.1] (n=296) | 10350.0 [9978.2, 10776.3] (n=296) |
| `retrieve_node_ms_p50` | 49.0000 (n=296) | 48.5000 (n=296) | 99.0000 (n=296) | 115.0 (n=296) |
| `retrieve_node_ms_p95` | 64.0000 (n=296) | 73.0000 (n=296) | 126.0 (n=296) | 164.2 (n=296) |
| `retrieve_node_ms_mean` | 51.9054 [50.7736, 53.2500] (n=296) | 50.3682 [49.0304, 51.7466] (n=296) | 101.2 [99.5169, 102.9] (n=296) | 117.1 [114.1, 120.2] (n=296) |
| `prompt_tokens_mean` | 2263.1 [2247.8, 2278.2] (n=296) | 2218.1 [2200.6, 2235.0] (n=296) | 2262.5 [2247.1, 2277.8] (n=296) | 2461.4 [2432.6, 2490.7] (n=296) |
| `spend_usd_mean` | 0.000429 [0.000426, 0.000433] (n=296) | 0.000406 [0.000402, 0.000411] (n=296) | 0.000427 [0.000424, 0.000431] (n=296) | 0.000453 [0.000448, 0.000459] (n=296) |


### Judged rows (secondary; the D-114 label sets how far they are trusted)

Judged means are over J_a (P4, judgeable, non-abstaining, non-error verdicts) and are not comparable across arms; compare arms only through the paired delta. Every row sits beside the arm's abstention rate and its n (D-118). Read, not recomputed, from `judged-result.json`.

| dimension | scored pairs | QWK | QWK 95% CI | floor | D-114 label | Spearman | exact agreement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| groundedness | 20 | -0.0256 | [-0.3226, 0.2565] | 0.7000 | uncalibrated | -0.0382 | 0.2000 |
| faithfulness | 20 | 0.0659 | [-0.3006, 0.5914] | 0.7000 | uncalibrated | 0.0228 | 0.5000 |


Agreement companions (the kappa paradox remedy; disclosures, the QWK floor alone sets the label):

| dimension | Spearman (95% CI) | exact agreement | MAD | mean signed difference (judge - human) | judge marginals 1..5 | human marginals 1..5 | joint 5/5 share | dropped resamples (QWK / Spearman) | per-arm exact agreement |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| groundedness | -0.0382 [-0.5423, 0.4779] | 0.2000 | 1.1000 | 0.6000 | 1/0/2/1/16 | 0/0/4/13/3 | 0.1000 | 0 / 109 | dense-only 1/5, bm25-only 0/5, hybrid 2/5, hybrid+graph 1/5 |
| faithfulness | 0.0228 [-0.4001, 0.5892] | 0.5000 | 0.8000 | 0.2000 | 1/0/2/0/17 | 0/1/2/5/12 | 0.5000 | 0 / 363 | dense-only 3/5, bm25-only 1/5, hybrid 3/5, hybrid+graph 3/5 |


No slice item was dropped for a judge error.

- legacy (06.3), non-governing: calibration_state for groundedness = below_target (QWK -0.0256, Spearman -0.0382, target 0.70)
- legacy (06.3), non-governing: calibration_state for faithfulness = below_target (QWK 0.0659, Spearman 0.0228, target 0.70)

| arm | dimension | mean over J_a (95% CI) | judge errors | abstention rate (n) | D-114 label |
| --- | --- | --- | --- | --- | --- |
| dense-only | groundedness | 4.6021 [4.4817, 4.7120] (n=191) | 0 | 0.3547 (n=296) | uncalibrated (QWK -0.0256, 95% CI [-0.3226, 0.2565], n=20) |
| dense-only | faithfulness | 4.7644 [4.6649, 4.8534] (n=191) | 0 | 0.3547 (n=296) | uncalibrated (QWK 0.0659, 95% CI [-0.3006, 0.5914], n=20) |
| bm25-only | groundedness | 4.1591 [3.9470, 4.3561] (n=132) | 0 | 0.5541 (n=296) | uncalibrated (QWK -0.0256, 95% CI [-0.3226, 0.2565], n=20) |
| bm25-only | faithfulness | 4.6364 [4.4545, 4.7955] (n=132) | 0 | 0.5541 (n=296) | uncalibrated (QWK 0.0659, 95% CI [-0.3006, 0.5914], n=20) |
| hybrid | groundedness | 4.5082 [4.3716, 4.6393] (n=183) | 0 | 0.3818 (n=296) | uncalibrated (QWK -0.0256, 95% CI [-0.3226, 0.2565], n=20) |
| hybrid | faithfulness | 4.7486 [4.6393, 4.8415] (n=183) | 0 | 0.3818 (n=296) | uncalibrated (QWK 0.0659, 95% CI [-0.3006, 0.5914], n=20) |
| hybrid+graph | groundedness | 4.4520 [4.3107, 4.5876] (n=177) | 0 | 0.4020 (n=296) | uncalibrated (QWK -0.0256, 95% CI [-0.3226, 0.2565], n=20) |
| hybrid+graph | faithfulness | 4.7232 [4.6215, 4.8192] (n=177) | 0 | 0.4020 (n=296) | uncalibrated (QWK 0.0659, 95% CI [-0.3006, 0.5914], n=20) |


Paired judged deltas against `hybrid` over the questions both arms answered and both have a usable verdict for (CIs are unadjusted, estimation only):

| comparison | dimension | delta (95% CI, unadjusted, estimation only) | n pairs | dropped: only arm / only hybrid / both / judge unavailable | judge errors arm / hybrid | abstention rate arm (n) / hybrid (n) | abstention delta (95% CI) | flag | D-114 label |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dense-only - hybrid | groundedness | 0.0625 [-0.0813, 0.2062] | 160 | 23 / 31 / 82 / 0 | 0 / 0 | 0.3547 (n=296) / 0.3818 (n=296) | -0.0270 [-0.0743, 0.0236] |  | uncalibrated |
| dense-only - hybrid | faithfulness | -0.0250 [-0.1625, 0.1125] | 160 | 23 / 31 / 82 / 0 | 0 / 0 | 0.3547 (n=296) / 0.3818 (n=296) | -0.0270 [-0.0743, 0.0236] |  | uncalibrated |
| bm25-only - hybrid | groundedness | -0.3770 [-0.5656, -0.1885] | 122 | 61 / 10 / 103 / 0 | 0 / 0 | 0.5541 (n=296) / 0.3818 (n=296) | 0.1723 [0.1216, 0.2264] | abstention differs: conditional on both arms answering; not an arm effect on grounding | uncalibrated |
| bm25-only - hybrid | faithfulness | -0.1557 [-0.3525, 0.0328] | 122 | 61 / 10 / 103 / 0 | 0 / 0 | 0.5541 (n=296) / 0.3818 (n=296) | 0.1723 [0.1216, 0.2264] | abstention differs: conditional on both arms answering; not an arm effect on grounding | uncalibrated |
| hybrid+graph - hybrid | groundedness | -0.0248 [-0.1180, 0.0621] | 161 | 22 / 16 / 97 / 0 | 0 / 0 | 0.4020 (n=296) / 0.3818 (n=296) | 0.0203 [-0.0203, 0.0608] |  | uncalibrated |
| hybrid+graph - hybrid | faithfulness | -0.0186 [-0.1180, 0.0807] | 161 | 22 / 16 / 97 / 0 | 0 / 0 | 0.4020 (n=296) / 0.3818 (n=296) | 0.0203 [-0.0203, 0.0608] |  | uncalibrated |


## Secondary paired deltas against hybrid (unadjusted, estimation only)

Read from `report.json`, never recomputed. Each delta is the mean paired difference over P4 with its bootstrap CI. The latency, retrieve-node and spend deltas are taken on the per-question mean (the 06.3.5-10 route); the p50 and p95 rows stay per-arm descriptive values in the four-arm table.

| metric | arm - hybrid | delta | 95% CI | n_pairs | mean (arm) | mean (hybrid) | label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `paper_hits_at_10` | dense-only - hybrid | 0.0203 | [-0.0169, 0.0574] | 296 | 0.8514 | 0.8311 | unadjusted, estimation only |
| `paper_hits_at_10` | bm25-only - hybrid | -0.1554 | [-0.2027, -0.1115] | 296 | 0.6757 | 0.8311 | unadjusted, estimation only |
| `paper_hits_at_10` | hybrid+graph - hybrid | -0.0203 | [-0.0405, -0.0034] | 296 | 0.8108 | 0.8311 | unadjusted, estimation only |
| `paper_mrr_at_10` | dense-only - hybrid | -0.0099 | [-0.0492, 0.0325] | 296 | 0.5620 | 0.5719 | unadjusted, estimation only |
| `paper_mrr_at_10` | bm25-only - hybrid | -0.1155 | [-0.1535, -0.0784] | 296 | 0.4564 | 0.5719 | unadjusted, estimation only |
| `paper_mrr_at_10` | hybrid+graph - hybrid | -0.0358 | [-0.0611, -0.0104] | 296 | 0.5362 | 0.5719 | unadjusted, estimation only |
| `paper_map_at_10` | dense-only - hybrid | -0.0017 | [-0.0210, 0.0182] | 296 | 0.2745 | 0.2762 | unadjusted, estimation only |
| `paper_map_at_10` | bm25-only - hybrid | -0.0623 | [-0.0791, -0.0461] | 296 | 0.2138 | 0.2762 | unadjusted, estimation only |
| `paper_map_at_10` | hybrid+graph - hybrid | -0.0173 | [-0.0296, -0.0051] | 296 | 0.2589 | 0.2762 | unadjusted, estimation only |
| `abstention_rate_g` | dense-only - hybrid | -0.0270 | [-0.0743, 0.0236] | 296 | 0.3547 | 0.3818 | unadjusted, estimation only |
| `abstention_rate_g` | bm25-only - hybrid | 0.1723 | [0.1216, 0.2264] | 296 | 0.5541 | 0.3818 | unadjusted, estimation only |
| `abstention_rate_g` | hybrid+graph - hybrid | 0.0203 | [-0.0203, 0.0608] | 296 | 0.4020 | 0.3818 | unadjusted, estimation only |
| `final_answer_em` | dense-only - hybrid | 0.0034 | [-0.0439, 0.0507] | 296 | 0.5608 | 0.5574 | unadjusted, estimation only |
| `final_answer_em` | bm25-only - hybrid | -0.1757 | [-0.2264, -0.1284] | 296 | 0.3818 | 0.5574 | unadjusted, estimation only |
| `final_answer_em` | hybrid+graph - hybrid | 0.0000 | [-0.0372, 0.0372] | 296 | 0.5574 | 0.5574 | unadjusted, estimation only |
| `gold_containment` | dense-only - hybrid | 0.0135 | [-0.0338, 0.0608] | 296 | 0.6757 | 0.6622 | unadjusted, estimation only |
| `gold_containment` | bm25-only - hybrid | -0.1047 | [-0.1588, -0.0541] | 296 | 0.5574 | 0.6622 | unadjusted, estimation only |
| `gold_containment` | hybrid+graph - hybrid | -0.0169 | [-0.0574, 0.0203] | 296 | 0.6453 | 0.6622 | unadjusted, estimation only |
| `final_answer_missing_rate` | dense-only - hybrid | 0.0000 | [0.0000, 0.0000] | 296 | 0.0000 | 0.0000 | unadjusted, estimation only |
| `final_answer_missing_rate` | bm25-only - hybrid | 0.0000 | [0.0000, 0.0000] | 296 | 0.0000 | 0.0000 | unadjusted, estimation only |
| `final_answer_missing_rate` | hybrid+graph - hybrid | 0.0000 | [0.0000, 0.0000] | 296 | 0.0000 | 0.0000 | unadjusted, estimation only |
| `coverage_at_4` | dense-only - hybrid | 0.0144 | [-0.0169, 0.0465] | 296 | 0.3722 | 0.3578 | unadjusted, estimation only |
| `coverage_at_4` | bm25-only - hybrid | -0.0946 | [-0.1222, -0.0681] | 296 | 0.2632 | 0.3578 | unadjusted, estimation only |
| `coverage_at_4` | hybrid+graph - hybrid | -0.0037 | [-0.0214, 0.0144] | 296 | 0.3542 | 0.3578 | unadjusted, estimation only |
| `precision_at_4` | dense-only - hybrid | 0.0093 | [-0.0093, 0.0279] | 296 | 0.2264 | 0.2171 | unadjusted, estimation only |
| `precision_at_4` | bm25-only - hybrid | -0.0574 | [-0.0743, -0.0414] | 296 | 0.1596 | 0.2171 | unadjusted, estimation only |
| `precision_at_4` | hybrid+graph - hybrid | -0.0042 | [-0.0152, 0.0068] | 296 | 0.2128 | 0.2171 | unadjusted, estimation only |
| `prompt_tokens` | dense-only - hybrid | 0.5507 | [-11.0034, 12.0676] | 296 | 2263.1 | 2262.5 | unadjusted, estimation only |
| `prompt_tokens` | bm25-only - hybrid | -44.4595 | [-56.6216, -32.4730] | 296 | 2218.1 | 2262.5 | unadjusted, estimation only |
| `prompt_tokens` | hybrid+graph - hybrid | 198.9 | [174.5, 223.7] | 296 | 2461.4 | 2262.5 | unadjusted, estimation only |
| `latency_total_ms` | dense-only - hybrid | 267.1 | [-96.3243, 640.7] | 296 | 10212.9 | 9945.8 | unadjusted, estimation only |
| `latency_total_ms` | bm25-only - hybrid | -472.6 | [-814.8, -127.7] | 296 | 9473.2 | 9945.8 | unadjusted, estimation only |
| `latency_total_ms` | hybrid+graph - hybrid | 404.1 | [24.0203, 823.1] | 296 | 10350.0 | 9945.8 | unadjusted, estimation only |
| `retrieve_node_ms` | dense-only - hybrid | -49.2872 | [-51.2635, -47.2838] | 296 | 51.9054 | 101.2 | unadjusted, estimation only |
| `retrieve_node_ms` | bm25-only - hybrid | -50.8243 | [-52.4764, -49.2365] | 296 | 50.3682 | 101.2 | unadjusted, estimation only |
| `retrieve_node_ms` | hybrid+graph - hybrid | 15.9020 | [13.1284, 18.8243] | 296 | 117.1 | 101.2 | unadjusted, estimation only |
| `spend_usd` | dense-only - hybrid | 0.000002 | [-0.000002, 0.000006] | 296 | 0.000429 | 0.000427 | unadjusted, estimation only |
| `spend_usd` | bm25-only - hybrid | -0.000021 | [-0.000025, -0.000017] | 296 | 0.000406 | 0.000427 | unadjusted, estimation only |
| `spend_usd` | hybrid+graph - hybrid | 0.000026 | [0.000021, 0.000030] | 296 | 0.000453 | 0.000427 | unadjusted, estimation only |


## Per-type strata (D-40; secondary, never decisive)

Cells read `value [ci_lo, ci_hi] (n)`, or `value (n = k; n < 10, no CI)` below the cell size of 10. Each answer_usable stratum shows its constant-Yes baseline beside it, and each judged stratum its abstention rate and n. Every per-type delta CI is unadjusted, estimation only.

### `abstention_rate_g`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.3636 [0.2833, 0.4523] (121) | 0.0505 [0.0218, 0.1128] (99) | 0.7368 [0.6282, 0.8227] (76) |
| bm25-only | 0.6612 [0.5730, 0.7394] (121) | 0.2424 [0.1687, 0.3354] (99) | 0.7895 [0.6850, 0.8660] (76) |
| hybrid | 0.4628 [0.3765, 0.5514] (121) | 0.0404 [0.0158, 0.0993] (99) | 0.6974 [0.5867, 0.7891] (76) |
| hybrid+graph | 0.4711 [0.3844, 0.5595] (121) | 0.0404 [0.0158, 0.0993] (99) | 0.7632 [0.6564, 0.8446] (76) |


### `answer_usable_p4`

| arm | question_type | value | constant-Yes baseline |
| --- | --- | --- | --- |
| dense-only | comparison_query | 0.5372 [0.4486, 0.6235] (121) | 0.6446 |
| dense-only | inference_query | 0.9394 [0.8740, 0.9719] (99) | 0.0000 |
| dense-only | temporal_query | 0.1842 [0.1130, 0.2858] (76) | 0.4868 |
| bm25-only | comparison_query | 0.2314 [0.1652, 0.3141] (121) | 0.6446 |
| bm25-only | inference_query | 0.7576 [0.6646, 0.8313] (99) | 0.0000 |
| bm25-only | temporal_query | 0.1711 [0.1028, 0.2710] (76) | 0.4868 |
| hybrid | comparison_query | 0.4545 [0.3686, 0.5433] (121) | 0.6446 |
| hybrid | inference_query | 0.9596 [0.9007, 0.9842] (99) | 0.0000 |
| hybrid | temporal_query | 0.2500 [0.1663, 0.3578] (76) | 0.4868 |
| hybrid+graph | comparison_query | 0.4545 [0.3686, 0.5433] (121) | 0.6446 |
| hybrid+graph | inference_query | 0.9596 [0.9007, 0.9842] (99) | 0.0000 |
| hybrid+graph | temporal_query | 0.2105 [0.1340, 0.3150] (76) | 0.4868 |


### `answer_usable_sc3_definition`

| arm | question_type | value | constant-Yes baseline |
| --- | --- | --- | --- |
| dense-only | comparison_query | 0.5366 [0.4487, 0.6223] (123) | 0.6423 |
| dense-only | inference_query | 0.9417 [0.8787, 0.9730] (103) | 0.0000 |
| dense-only | temporal_query | 0.1948 [0.1218, 0.2969] (77) | 0.4805 |
| bm25-only | comparison_query | 0.2320 [0.1667, 0.3133] (125) | 0.6400 |
| bm25-only | inference_query | 0.7714 [0.6824, 0.8413] (105) | 0.0000 |
| bm25-only | temporal_query | 0.1667 [0.1001, 0.2646] (78) | 0.4744 |
| hybrid | comparison_query | 0.4435 [0.3591, 0.5314] (124) | 0.6371 |
| hybrid | inference_query | 0.9608 [0.9035, 0.9846] (102) | 0.0000 |
| hybrid | temporal_query | 0.2468 [0.1640, 0.3535] (77) | 0.4805 |
| hybrid+graph | comparison_query | 0.4516 [0.3668, 0.5393] (124) | 0.6452 |
| hybrid+graph | inference_query | 0.9615 [0.9053, 0.9849] (104) | 0.0000 |
| hybrid+graph | temporal_query | 0.2179 [0.1408, 0.3216] (78) | 0.4744 |


### `coverage_at_4`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.4793 [0.4242, 0.5344] (121) | 0.2980 [0.2584, 0.3384] (99) | 0.2982 [0.2325, 0.3662] (76) |
| bm25-only | 0.2948 [0.2452, 0.3444] (121) | 0.2247 [0.1801, 0.2719] (99) | 0.2632 [0.1974, 0.3311] (76) |
| hybrid | 0.4187 [0.3623, 0.4752] (121) | 0.3274 [0.2778, 0.3796] (99) | 0.3004 [0.2303, 0.3750] (76) |
| hybrid+graph | 0.4311 [0.3719, 0.4917] (121) | 0.3131 [0.2643, 0.3653] (99) | 0.2851 [0.2149, 0.3596] (76) |


### `final_answer_em`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.4959 [0.4083, 0.5837] (121) | 0.9293 [0.8612, 0.9653] (99) | 0.1842 [0.1130, 0.2858] (76) |
| bm25-only | 0.2231 [0.1581, 0.3052] (121) | 0.7475 [0.6538, 0.8227] (99) | 0.1579 [0.0927, 0.2560] (76) |
| hybrid | 0.4380 [0.3529, 0.5270] (121) | 0.9495 [0.8872, 0.9782] (99) | 0.2368 [0.1554, 0.3436] (76) |
| hybrid+graph | 0.4545 [0.3686, 0.5433] (121) | 0.9495 [0.8872, 0.9782] (99) | 0.2105 [0.1340, 0.3150] (76) |


### `final_answer_missing_rate`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.0000 [0.0000, 0.0308] (121) | 0.0000 [0.0000, 0.0374] (99) | 0.0000 [0.0000, 0.0481] (76) |
| bm25-only | 0.0000 [0.0000, 0.0308] (121) | 0.0000 [0.0000, 0.0374] (99) | 0.0000 [0.0000, 0.0481] (76) |
| hybrid | 0.0000 [0.0000, 0.0308] (121) | 0.0000 [0.0000, 0.0374] (99) | 0.0000 [0.0000, 0.0481] (76) |
| hybrid+graph | 0.0000 [0.0000, 0.0308] (121) | 0.0000 [0.0000, 0.0374] (99) | 0.0000 [0.0000, 0.0481] (76) |


### `gold_containment`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.6446 [0.5561, 0.7243] (121) | 0.9798 [0.9293, 0.9944] (99) | 0.3289 [0.2338, 0.4406] (76) |
| bm25-only | 0.4298 [0.3450, 0.5188] (121) | 0.8586 [0.7765, 0.9139] (99) | 0.3684 [0.2688, 0.4808] (76) |
| hybrid | 0.5785 [0.4894, 0.6628] (121) | 0.9899 [0.9450, 0.9982] (99) | 0.3684 [0.2688, 0.4808] (76) |
| hybrid+graph | 0.5455 [0.4567, 0.6314] (121) | 0.9798 [0.9293, 0.9944] (99) | 0.3684 [0.2688, 0.4808] (76) |


### `latency_total_ms_mean`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 10422.7273 [9910.0744, 10933.5041] (121) | 10031.2222 [9371.5859, 10740.5758] (99) | 10115.5789 [9587.0000, 10659.1053] (76) |
| bm25-only | 9590.5950 [9143.5372, 10058.2066] (121) | 9164.9697 [8695.8586, 9660.7273] (99) | 9687.8816 [9097.4079, 10303.1711] (76) |
| hybrid | 10041.1818 [9562.0909, 10524.3140] (121) | 9662.0505 [9189.8182, 10170.6768] (99) | 10163.7500 [9634.5132, 10741.3158] (76) |
| hybrid+graph | 10436.5702 [9869.4380, 11019.1570] (121) | 10272.3838 [9524.5758, 11316.3535] (99) | 10313.1053 [9825.4211, 10804.4605] (76) |


### `latency_total_ms_p50`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 10385.0000 (n = 121; n < 10, no CI) | 9513.0000 (n = 99; n < 10, no CI) | 10242.5000 (n = 76; n < 10, no CI) |
| bm25-only | 9123.0000 (n = 121; n < 10, no CI) | 8824.0000 (n = 99; n < 10, no CI) | 9403.5000 (n = 76; n < 10, no CI) |
| hybrid | 9796.0000 (n = 121; n < 10, no CI) | 9323.0000 (n = 99; n < 10, no CI) | 9615.5000 (n = 76; n < 10, no CI) |
| hybrid+graph | 10180.0000 (n = 121; n < 10, no CI) | 9670.0000 (n = 99; n < 10, no CI) | 10119.0000 (n = 76; n < 10, no CI) |


### `latency_total_ms_p95`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 15618.0000 (n = 121; n < 10, no CI) | 16077.4000 (n = 99; n < 10, no CI) | 13894.7500 (n = 76; n < 10, no CI) |
| bm25-only | 13869.0000 (n = 121; n < 10, no CI) | 13390.4000 (n = 99; n < 10, no CI) | 14244.0000 (n = 76; n < 10, no CI) |
| hybrid | 14526.0000 (n = 121; n < 10, no CI) | 13852.7000 (n = 99; n < 10, no CI) | 14511.0000 (n = 76; n < 10, no CI) |
| hybrid+graph | 15397.0000 (n = 121; n < 10, no CI) | 14311.0000 (n = 99; n < 10, no CI) | 14509.0000 (n = 76; n < 10, no CI) |


### `paper_hits_at_10`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.9008 [0.8346, 0.9424] (121) | 0.8687 [0.7882, 0.9216] (99) | 0.7500 [0.6422, 0.8337] (76) |
| bm25-only | 0.7190 [0.6331, 0.7914] (121) | 0.6566 [0.5588, 0.7427] (99) | 0.6316 [0.5192, 0.7312] (76) |
| hybrid | 0.8760 [0.8055, 0.9234] (121) | 0.8586 [0.7765, 0.9139] (99) | 0.7237 [0.6142, 0.8116] (76) |
| hybrid+graph | 0.8678 [0.7960, 0.9169] (121) | 0.8485 [0.7650, 0.9060] (99) | 0.6711 [0.5594, 0.7662] (76) |


### `paper_hits_at_10_script_faithful`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.8800 [0.8114, 0.9259] (125) | 0.8571 [0.7776, 0.9115] (105) | 0.7436 [0.6369, 0.8274] (78) |
| bm25-only | 0.7280 [0.6441, 0.7983] (125) | 0.6667 [0.5720, 0.7495] (105) | 0.6410 [0.5303, 0.7385] (78) |
| hybrid | 0.8720 [0.8022, 0.9197] (125) | 0.8286 [0.7452, 0.8887] (105) | 0.7179 [0.6097, 0.8057] (78) |
| hybrid+graph | 0.8640 [0.7930, 0.9133] (125) | 0.8381 [0.7559, 0.8964] (105) | 0.6795 [0.5696, 0.7725] (78) |


### `paper_hits_at_4`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.8017 [0.7218, 0.8629] (121) | 0.7778 [0.6864, 0.8484] (99) | 0.5921 [0.4798, 0.6956] (76) |
| bm25-only | 0.5702 [0.4812, 0.6550] (121) | 0.5859 [0.4874, 0.6779] (99) | 0.5263 [0.4155, 0.6346] (76) |
| hybrid | 0.7190 [0.6331, 0.7914] (121) | 0.7677 [0.6754, 0.8399] (99) | 0.5395 [0.4282, 0.6469] (76) |
| hybrid+graph | 0.7190 [0.6331, 0.7914] (121) | 0.7475 [0.6538, 0.8227] (99) | 0.5263 [0.4155, 0.6346] (76) |


### `paper_hits_at_4_script_faithful`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.7840 [0.7040, 0.8471] (125) | 0.7714 [0.6824, 0.8413] (105) | 0.5897 [0.4789, 0.6922] (78) |
| bm25-only | 0.5760 [0.4884, 0.6591] (125) | 0.5905 [0.4948, 0.6797] (105) | 0.5385 [0.4286, 0.6447] (78) |
| hybrid | 0.7200 [0.6356, 0.7912] (125) | 0.7429 [0.6517, 0.8168] (105) | 0.5385 [0.4286, 0.6447] (78) |
| hybrid+graph | 0.7120 [0.6272, 0.7841] (125) | 0.7429 [0.6517, 0.8168] (105) | 0.5385 [0.4286, 0.6447] (78) |


### `paper_map_at_10`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.3554 [0.3145, 0.3966] (121) | 0.2187 [0.1870, 0.2520] (99) | 0.2183 [0.1711, 0.2693] (76) |
| bm25-only | 0.2538 [0.2127, 0.2964] (121) | 0.1781 [0.1420, 0.2166] (99) | 0.1967 [0.1471, 0.2485] (76) |
| hybrid | 0.3291 [0.2862, 0.3735] (121) | 0.2502 [0.2148, 0.2866] (99) | 0.2258 [0.1738, 0.2808] (76) |
| hybrid+graph | 0.3135 [0.2704, 0.3576] (121) | 0.2360 [0.2012, 0.2724] (99) | 0.2017 [0.1545, 0.2513] (76) |


### `paper_map_at_10_script_faithful`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.3474 [0.3064, 0.3888] (125) | 0.2147 [0.1833, 0.2467] (105) | 0.2223 [0.1743, 0.2724] (78) |
| bm25-only | 0.2580 [0.2166, 0.2989] (125) | 0.1775 [0.1424, 0.2133] (105) | 0.2045 [0.1553, 0.2554] (78) |
| hybrid | 0.3289 [0.2859, 0.3715] (125) | 0.2433 [0.2077, 0.2791] (105) | 0.2264 [0.1750, 0.2783] (78) |
| hybrid+graph | 0.3120 [0.2689, 0.3541] (125) | 0.2392 [0.2043, 0.2755] (105) | 0.2103 [0.1621, 0.2597] (78) |


### `paper_mrr_at_10`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.6374 [0.5681, 0.7048] (121) | 0.5559 [0.4822, 0.6320] (99) | 0.4500 [0.3606, 0.5435] (76) |
| bm25-only | 0.4849 [0.4081, 0.5634] (121) | 0.4616 [0.3784, 0.5480] (99) | 0.4043 [0.3105, 0.5009] (76) |
| hybrid | 0.5892 [0.5165, 0.6631] (121) | 0.6429 [0.5633, 0.7217] (99) | 0.4520 [0.3551, 0.5499] (76) |
| hybrid+graph | 0.5599 [0.4890, 0.6318] (121) | 0.6012 [0.5217, 0.6812] (99) | 0.4136 [0.3182, 0.5075] (76) |


### `paper_mrr_at_10_script_faithful`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.6210 [0.5514, 0.6901] (125) | 0.5416 [0.4687, 0.6157] (105) | 0.4513 [0.3626, 0.5414] (78) |
| bm25-only | 0.4902 [0.4134, 0.5669] (125) | 0.4588 [0.3782, 0.5403] (105) | 0.4196 [0.3258, 0.5156] (78) |
| hybrid | 0.5884 [0.5159, 0.6596] (125) | 0.6252 [0.5432, 0.7031] (105) | 0.4532 [0.3585, 0.5481] (78) |
| hybrid+graph | 0.5550 [0.4843, 0.6250] (125) | 0.6050 [0.5259, 0.6808] (105) | 0.4286 [0.3347, 0.5230] (78) |


### `precision_at_4`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.2583 [0.2273, 0.2872] (121) | 0.2247 [0.1970, 0.2525] (99) | 0.1776 [0.1414, 0.2171] (76) |
| bm25-only | 0.1570 [0.1302, 0.1839] (121) | 0.1641 [0.1338, 0.1944] (99) | 0.1579 [0.1217, 0.1974] (76) |
| hybrid | 0.2231 [0.1921, 0.2541] (121) | 0.2399 [0.2071, 0.2727] (99) | 0.1776 [0.1382, 0.2204] (76) |
| hybrid+graph | 0.2273 [0.1963, 0.2583] (121) | 0.2298 [0.1970, 0.2626] (99) | 0.1678 [0.1283, 0.2072] (76) |


### `prompt_tokens_mean`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 2238.2397 [2212.5207, 2264.5041] (121) | 2285.3535 [2261.7677, 2307.9596] (99) | 2273.5395 [2244.2105, 2301.6579] (76) |
| bm25-only | 2209.0165 [2179.7603, 2238.4545] (121) | 2199.8283 [2172.6263, 2227.1414] (99) | 2256.1711 [2223.1579, 2288.9868] (76) |
| hybrid | 2247.1983 [2220.7686, 2273.3471] (121) | 2275.5455 [2251.1616, 2300.4545] (99) | 2269.9079 [2243.0526, 2296.4605] (76) |
| hybrid+graph | 2467.6446 [2416.8017, 2517.0826] (121) | 2415.8990 [2372.7879, 2462.6566] (99) | 2510.5921 [2460.8684, 2562.2368] (76) |


### `retrieve_node_ms_mean`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 53.2893 [51.0826, 56.3140] (121) | 50.2828 [49.2929, 51.4242] (99) | 51.8158 [49.8947, 54.3421] (76) |
| bm25-only | 46.4298 [44.7107, 48.3306] (121) | 54.5657 [52.4747, 56.7980] (99) | 51.1711 [48.1974, 54.3289] (76) |
| hybrid | 97.8760 [95.5950, 100.3554] (121) | 106.6869 [103.8283, 109.8283] (99) | 99.3158 [96.2895, 102.5526] (76) |
| hybrid+graph | 112.1240 [108.2645, 116.4050] (121) | 121.3838 [116.4242, 126.5657] (99) | 119.4211 [112.8026, 126.9605] (76) |


### `retrieve_node_ms_p50`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 50.0000 (n = 121; n < 10, no CI) | 49.0000 (n = 99; n < 10, no CI) | 49.0000 (n = 76; n < 10, no CI) |
| bm25-only | 45.0000 (n = 121; n < 10, no CI) | 53.0000 (n = 99; n < 10, no CI) | 50.5000 (n = 76; n < 10, no CI) |
| hybrid | 96.0000 (n = 121; n < 10, no CI) | 105.0000 (n = 99; n < 10, no CI) | 97.0000 (n = 76; n < 10, no CI) |
| hybrid+graph | 112.0000 (n = 121; n < 10, no CI) | 121.0000 (n = 99; n < 10, no CI) | 117.5000 (n = 76; n < 10, no CI) |


### `retrieve_node_ms_p95`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 66.0000 (n = 121; n < 10, no CI) | 58.3000 (n = 99; n < 10, no CI) | 64.5000 (n = 76; n < 10, no CI) |
| bm25-only | 65.0000 (n = 121; n < 10, no CI) | 77.0000 (n = 99; n < 10, no CI) | 73.2500 (n = 76; n < 10, no CI) |
| hybrid | 125.0000 (n = 121; n < 10, no CI) | 130.2000 (n = 99; n < 10, no CI) | 124.5000 (n = 76; n < 10, no CI) |
| hybrid+graph | 142.0000 (n = 121; n < 10, no CI) | 166.0000 (n = 99; n < 10, no CI) | 176.5000 (n = 76; n < 10, no CI) |


### `spend_usd_mean`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 0.0004 [0.0004, 0.0004] (121) | 0.0004 [0.0004, 0.0004] (99) | 0.0004 [0.0004, 0.0004] (76) |
| bm25-only | 0.0004 [0.0004, 0.0004] (121) | 0.0004 [0.0004, 0.0004] (99) | 0.0004 [0.0004, 0.0004] (76) |
| hybrid | 0.0004 [0.0004, 0.0004] (121) | 0.0004 [0.0004, 0.0004] (99) | 0.0004 [0.0004, 0.0004] (76) |
| hybrid+graph | 0.0005 [0.0004, 0.0005] (121) | 0.0004 [0.0004, 0.0005] (99) | 0.0005 [0.0005, 0.0005] (76) |


### `answer_groundedness`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 4.9740 [4.9221, 5.0000] (77); abstention 0.3636 (n = 121) | 4.2128 [4.0000, 4.4149] (94); abstention 0.0505 (n = 99) | 5.0000 [5.0000, 5.0000] (20); abstention 0.7368 (n = 76) |
| bm25-only | 4.9756 [4.9268, 5.0000] (41); abstention 0.6612 (n = 121) | 3.5333 [3.2400, 3.8133] (75); abstention 0.2424 (n = 99) | 5.0000 [5.0000, 5.0000] (16); abstention 0.7895 (n = 76) |
| hybrid | 4.9385 [4.8462, 5.0000] (65); abstention 0.4628 (n = 121) | 4.0947 [3.8737, 4.3053] (95); abstention 0.0404 (n = 99) | 5.0000 [5.0000, 5.0000] (23); abstention 0.6974 (n = 76) |
| hybrid+graph | 4.9219 [4.8125, 5.0000] (64); abstention 0.4711 (n = 121) | 4.0526 [3.8421, 4.2632] (95); abstention 0.0404 (n = 99) | 4.8889 [4.6667, 5.0000] (18); abstention 0.7632 (n = 76) |


### `answer_faithfulness`

| arm | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only | 5.0000 [5.0000, 5.0000] (77); abstention 0.3636 (n = 121) | 4.5213 [4.3298, 4.6915] (94); abstention 0.0505 (n = 99) | 5.0000 [5.0000, 5.0000] (20); abstention 0.7368 (n = 76) |
| bm25-only | 5.0000 [5.0000, 5.0000] (41); abstention 0.6612 (n = 121) | 4.3600 [4.0400, 4.6267] (75); abstention 0.2424 (n = 99) | 5.0000 [5.0000, 5.0000] (16); abstention 0.7895 (n = 76) |
| hybrid | 4.9692 [4.9077, 5.0000] (65); abstention 0.4628 (n = 121) | 4.5368 [4.3474, 4.7158] (95); abstention 0.0404 (n = 99) | 5.0000 [5.0000, 5.0000] (23); abstention 0.6974 (n = 76) |
| hybrid+graph | 5.0000 [5.0000, 5.0000] (64); abstention 0.4711 (n = 121) | 4.4842 [4.3053, 4.6526] (95); abstention 0.0404 (n = 99) | 5.0000 [5.0000, 5.0000] (18); abstention 0.7632 (n = 76) |


### Per-type paired delta against hybrid: `paper_hits_at_4`

| comparison | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only - hybrid | 0.0826 [0.0000, 0.1653] (121) unadjusted, estimation only | 0.0101 [-0.0606, 0.0808] (99) unadjusted, estimation only | 0.0526 [-0.0526, 0.1579] (76) unadjusted, estimation only |
| bm25-only - hybrid | -0.1488 [-0.2314, -0.0661] (121) unadjusted, estimation only | -0.1818 [-0.2727, -0.0909] (99) unadjusted, estimation only | -0.0132 [-0.1053, 0.0789] (76) unadjusted, estimation only |
| hybrid+graph - hybrid | 0.0000 [-0.0496, 0.0496] (121) unadjusted, estimation only | -0.0202 [-0.0606, 0.0202] (99) unadjusted, estimation only | -0.0132 [-0.0395, 0.0000] (76) unadjusted, estimation only |


### Per-type paired delta against hybrid: `answer_usable`

| comparison | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only - hybrid | 0.0826 [-0.0083, 0.1736] (121) unadjusted, estimation only | -0.0202 [-0.0606, 0.0202] (99) unadjusted, estimation only | -0.0658 [-0.1711, 0.0395] (76) unadjusted, estimation only |
| bm25-only - hybrid | -0.2231 [-0.3140, -0.1322] (121) unadjusted, estimation only | -0.2020 [-0.2929, -0.1212] (99) unadjusted, estimation only | -0.0789 [-0.1579, 0.0000] (76) unadjusted, estimation only |
| hybrid+graph - hybrid | 0.0000 [-0.0744, 0.0744] (121) unadjusted, estimation only | 0.0000 [0.0000, 0.0000] (99) unadjusted, estimation only | -0.0395 [-0.1184, 0.0395] (76) unadjusted, estimation only |


### Per-type paired delta against hybrid (judged): `answer_groundedness`

| comparison | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only - hybrid | 0.0377 [0.0000, 0.1132] (53) unadjusted, estimation only | 0.0860 [-0.1505, 0.3226] (93) unadjusted, estimation only | 0.0000 [0.0000, 0.0000] (14) unadjusted, estimation only |
| bm25-only - hybrid | 0.0294 [-0.0882, 0.1765] (34) unadjusted, estimation only | -0.6351 [-0.9324, -0.3378] (74) unadjusted, estimation only | 0.0000 [0.0000, 0.0000] (14) unadjusted, estimation only |
| hybrid+graph - hybrid | 0.0000 [-0.1176, 0.1176] (51) unadjusted, estimation only | -0.0421 [-0.1895, 0.0947] (95) unadjusted, estimation only | 0.0000 [0.0000, 0.0000] (15) unadjusted, estimation only |


### Per-type paired delta against hybrid (judged): `answer_faithfulness`

| comparison | comparison_query | inference_query | temporal_query |
| --- | --- | --- | --- |
| dense-only - hybrid | 0.0377 [0.0000, 0.1132] (53) unadjusted, estimation only | -0.0645 [-0.3011, 0.1720] (93) unadjusted, estimation only | 0.0000 [0.0000, 0.0000] (14) unadjusted, estimation only |
| bm25-only - hybrid | 0.0588 [0.0000, 0.1765] (34) unadjusted, estimation only | -0.2838 [-0.5946, 0.0135] (74) unadjusted, estimation only | 0.0000 [0.0000, 0.0000] (14) unadjusted, estimation only |
| hybrid+graph - hybrid | 0.0392 [0.0000, 0.1176] (51) unadjusted, estimation only | -0.0526 [-0.2105, 0.1158] (95) unadjusted, estimation only | 0.0000 [0.0000, 0.0000] (15) unadjusted, estimation only |


## Paper reference row (cited; not comparable)

Paper reference (cited; not comparable, see caveat): arXiv 2401.15391 v1, Table 5, "Retrieval performance of different embedding models.", Without Reranker half, quoted as printed.

| embedding | MRR@10 | MAP@10 | Hits@10 | Hits@4 |
| --- | --- | --- | --- | --- |
| bge-large-en-v1.5 | 0.4298 | 0.3423 | 0.6718 | 0.5221 |
| voyage-02 | 0.3934 | 0.3143 | 0.6506 | 0.4619 |

These figures are not directly comparable with lancet's. The differences:

- (a) The paper's setup is dense-only, and the paper has no BM25 or hybrid row; lancet's arms include BM25-only, hybrid and hybrid+graph.

- (b) The paper uses LlamaIndex with 256-token chunks and cosine top-K retrieval.

- (c) The paper's reranker columns re-rank 20 retrieved chunks with bge-reranker-large; they are not cited here, because production runs a no-op reranker.

- (d) The paper's prose defines Hit@K as the fraction of evidence that appears in the top-K retrieved set, but the pinned official script counts a query as a hit if any relevant chunk is in the top K, and D-102 says the script governs.

- (e) The official script uses text matching, while lancet's headline figures use chunk-ID matching through the gold-chunk table (the text rule is a cross-check).

- (f) The paper excludes nulls ("NULL queries are excluded in this experiment").

- Lancet's population here is the 308 G-restricted held-out questions, while the paper averages over all non-null queries of its 2,556-question set; G-restriction removes questions whose evidence is split across chunks or absent from the index, which raises lancet's figures relative to a full-population reading.

- Lancet indexes a 346-document subset of the MultiHop-RAG corpus, not the paper's full document set.

- Lancet's chunker and embedder (`voyageai/voyage-4-large`) differ from the paper's.

The comparable lancet line is the script-faithful line (all 308 held-out G questions per arm; a record without a valid ranking scored as a miss; denominator 308), under the official text rule because the cross-check ran (D-122). It stays G-restricted, while the paper averages over all non-null queries.

Lancet's comparable line (official text rule (cross-check ran)):

| arm | Hits@4 (lancet comparable line) | n |
| --- | --- | --- |
| dense-only | 0.7305 (n=308) | 308 |
| bm25-only | 0.5714 (n=308) | 308 |
| hybrid | 0.6818 (n=308) | 308 |
| hybrid+graph | 0.6786 (n=308) | 308 |


## Comparison lines (D-121, D-122)

### D-121: answer_usable, 06.3.4.1 SC-3 definition (comparison line)

The 06.3.4.1 SC-3 definition on per-arm usable records with the inherited exclusions. It bridges to drive 2's figure, but the P4 primary (answer_usable on P4, where a blank answer scores 0) is not directly comparable to drive 2's 0.58. This line decides nothing.

| arm | value (95% CI) | n |
| --- | --- | --- |
| dense-only | 0.5875 [0.5313, 0.6415] (n=303) | 303 |
| bm25-only | 0.3994 [0.3462, 0.4550] (n=308) | 308 |
| hybrid | 0.5677 [0.5114, 0.6222] (n=303) | 303 |
| hybrid+graph | 0.5654 [0.5093, 0.6198] (n=306) | 306 |


### D-122: Script-faithful paper line (all held-out G questions)

Paper-convention Hits@4 over all 308 held-out G questions per arm (denominator 308); a record without a valid ranking scores as a miss. It is a labelled sensitivity line and decides nothing.

| arm | value (95% CI) | n |
| --- | --- | --- |
| dense-only | 0.7305 [0.6784, 0.7770] (n=308) | 308 |
| bm25-only | 0.5714 [0.5156, 0.6255] (n=308) | 308 |
| hybrid | 0.6818 [0.6278, 0.7313] (n=308) | 308 |
| hybrid+graph | 0.6786 [0.6245, 0.7283] (n=308) | 308 |


## Disclosures

Four held-out question IDs (mhr-0073ab564e55, mhr-00fc91a80765, mhr-12912d800c0c, mhr-0279d4a349c3) reached the live system earlier, as floor-only canary checks in drives 1b and 2, before the held-out split existed (D-124). The four-arm preflight used the rehearsal pool only.

Run-integrity gate readings (D-109), as written by `unpark_gates`:

| gate | arm | status |
| --- | --- | --- |
| SC-1 | dense-only | PASS |
| SC-1 | bm25-only | PASS |
| SC-1 | hybrid | PASS |
| SC-1 | hybrid+graph | PASS |
| SC-1 | pooled | PASS |
| SC-2 | dense-only | MISS |
| SC-2 | bm25-only | PASS |
| SC-2 | hybrid | MISS |
| SC-2 | hybrid+graph | MISS |
| SC-2 | pooled | MISS |
| D-69 companion | dense-only | PASS |
| D-69 companion | bm25-only | PASS |
| D-69 companion | hybrid | PASS |
| D-69 companion | hybrid+graph | PASS |
| D-69 companion | pooled | PASS |


Records by serving provider per arm (D-107); 13 record(s) had no served line:

| arm | provider | records |
| --- | --- | --- |
| bm25-only | Sail Research | 351 |
| dense-only | Sail Research | 346 |
| dense-only | null | 5 |
| hybrid | Sail Research | 345 |
| hybrid | null | 6 |
| hybrid+graph | Sail Research | 349 |
| hybrid+graph | null | 2 |

