# S2X: S2's readers on the merged store (exploratory)

Status: **predictions written 2026-11-01, before any data of this run; run and Result 2026-11-01.** Nothing above
the Result changed after the data.

This run is exploratory (#143). It decides nothing and changes no S2 or S3 decision: S2's reader choice stands
(EXPERIMENT-S2.md › Result). Owner, 2026-11-01: "好，執行三個 reader K=2 跟補跑deepseek".

## Question

Do the Claude readers stop abstaining when the context holds every gold fact? In S2 (small store) they lose to deepseek
almost only by abstaining when the evidence is partial. Every Sonnet 5.5 and Opus 5.5 loss is a yes/no question with
partial evidence. S1's merged store gives complete evidence on 42 of the 90 G questions instead of 31, with about 3
times the context words.

## Arms

S2's four arms, moved from S1's `small/hybrid+rerank+metadata` to S1's `merged/hybrid+rerank+metadata`. Each reader
keeps its S2 transport and thinking, so each reader compares with S2 directly. Every arm answers each question **2
times** (K = 2).

| Arm label | Reader | How it is read |
|---|---|---|
| `merged/hybrid+rerank+metadata` (reference) | deepseek | replicate 1 carried from the S1 run of record; replicate 2 by OpenRouter's sync API, pinned as in D-278 |
| `merged/hybrid+rerank+metadata@haiku-5.5` | Haiku 5.5 | OpenRouter batch, BYOK, thinking off |
| `merged/hybrid+rerank+metadata@sonnet-5.5` | Sonnet 5.5 | OpenRouter's sync API, BYOK, `between_tools` (D-280) |
| `merged/hybrid+rerank+metadata@opus-5.5` (descriptive) | Opus 5.5 | OpenRouter batch, BYOK, thinking on at effort low |

## Data

Corpus `multihop_rag_s2x_dev`: S2's documents, questions, split and stores, copied section for section (a test pins
this). The D-237 dev pool of 100 (90 G, 10 null), 2 answers per question and arm: 200 records per arm. No held-out
question is read.

Source: `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`, arm `merged/hybrid+rerank+metadata` (100 `success` records).

## Pre-registration constant

`PREREGISTRATION_S2X` in [`thresholds.py`](../../eval/src/lancet_eval/thresholds.py): `PREREGISTRATION_S2` with
`replay_source_arm` and every arm label moved to the merged arm and `replicates=2`. Readers, prices, thinking, test
and every number are S2's (a test pins this). `PREREGISTRATION_S2` is not edited. The family is `decisional` only
because the lever comparison needs one.

## Evidence split

`python -m lancet_eval.evidence_split` splits each G question by two things:

- whether every gold fact is in the reader's context: `metrics.gold_contained`, with its D-276 plural and list folds,
  over the evidence texts joined by spaces, so a fact may span two neighbouring entries. #143's tables use the same
  match;
- whether the gold answer is a bare yes or no.

For each reader and cell it prints `answer_usable` and the abstention rate (`metrics.is_abstention`) over every
`success` answer. With `--moved <export> <before arm> <after arm>`, it counts only the questions whose evidence is
partial under the first arm and complete under the second.

On S1's context export, 15 G questions move from partial (small) to complete (merged): 9 yes/no and 6 open. Four go the
other way, complete to partial, all yes/no.

S2's run, split this way (5 answers per question; `--run eval/runs/2026-11-01-s2-multihop_rag_s2_dev --corpus
multihop_rag_s2_dev`):

| S2, small store | usable, complete (31 G) | usable, partial (59 G) | abstain, partial | abstain, the 15 moved | usable, all 90 G |
|---|---|---|---|---|---|
| deepseek | 0.890 | 0.834 | 0.132 | 0.120 | 0.853 |
| Haiku 5.5 | 0.806 | 0.634 | 0.254 | 0.293 | 0.693 |
| Sonnet 5.5 | 0.935 | 0.715 | 0.254 | 0.267 | 0.791 |
| Opus 5.5 | 0.968 | 0.749 | 0.217 | 0.227 | 0.824 |

## Predictions

Written before the run. Each is checked once against the Result and never tuned to it.

1. **Less abstention where the evidence completes.** On the 15 moved questions, each Claude reader's abstention rate in
   this run (merged, K = 2) is below its S2 rate (small, K = 5): Haiku 5.5 below 0.293, Sonnet 5.5 below 0.267, Opus
   5.5 below 0.227.
2. **Sonnet and Opus close the gap to deepseek.** On the 90 G questions, the paired `answer_usable` delta against
   deepseek (`reader_comparison`) is higher on merged than on small: Sonnet 5.5 above -6.2 points, Opus 5.5 above -2.9
   points.

The run is too small to test either prediction: 2 answers per question, and 15 questions for the first. Each one is
read as holding or not on the point estimate, and the Result says so.

## What the Result reports

Per reader, S2 (small) beside this run (merged):

- `answer_usable` and the abstention rate, split by evidence (complete, partial) and by kind (yes/no, open);
- the abstention rate on the 15 moved questions;
- the paired delta against deepseek and the null guards, as `compare-levers` prints them;
- `reasoning_tokens` (total and mean per record);
- the spend.

Retrieval secondaries in `score` and `compare-levers` read v1.0 gold chunks on the merged store (#128). `answer_usable`,
the abstention rate and the evidence split read none of them, so #128 does not touch this result.

## How to run it

RUN-S2.md's path, with `PREREGISTRATION_S2X` in place of `PREREGISTRATION_S2`. Run it in the main checkout on `main`,
after the constant is merged:

- `<WINNER>` = `merged/hybrid+rerank+metadata`;
- `<S1_RUN>` = `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`;
- corpus `multihop_rag_s2x_dev`;
- `<RUN>` = `eval/runs/<date>-s2-multihop_rag_s2x_dev`. Its `-s2-` tag is what `test_journal.py`'s lever-run exemption
  reads.

The steps:

1. `replay-init`.
2. `batch submit` for each of the four arms. A 5-question smoke run in a separate `--pilot` run is allowed first.
3. `batch fetch` until nothing is pending.
4. The count: 200 per arm.
5. `score --no-judge` and `compare-levers`.
6. `evidence_split`, run once plain and once with `--moved eval/runs/2026-10-31-s1-multihop_rag_s1_dev/context_export.jsonl
   small/hybrid+rerank+metadata merged/hybrid+rerank+metadata`, on both this run and S2's.

No answer judges.

Estimate: about $7 (Sonnet sync about $3.5, Opus batch about $3.4, Haiku batch about $0.08, deepseek about $0.02).
Ceiling: $15, Claude credit and OpenRouter credit together. A printed estimate above the ceiling stops the run.

## Result

**Both predictions hold on the point estimates, but the overall gap barely moves.** On the 15 moved questions, every
Claude reader abstains less on merged than on small: Sonnet 5.5 and Opus 5.5 by a lot, Haiku 5.5 only slightly. Across
all 90 G questions, Sonnet 5.5 and Opus 5.5 come under 1 point closer to deepseek, well inside the noise of a K = 2 run.
The merged store does not remove the Claude readers' abstention on partial yes/no evidence; they still abstain on
39-52% of those answers. This run decides nothing, and S2's choice of deepseek stands.

- Run: `eval/runs/2026-11-01-s2-multihop_rag_s2x_dev`, pre-registration `PREREGISTRATION_S2X`. The constant was frozen
  by `c767bff1` and merged in #144 as `639ee82f`. The run ran on `main` at `639ee82f` on 2026-11-01, dev only
  (|H_G| = 90, |H_N| = 10), with no held-out read. Replicate 1 of the deepseek arm is carried from
  `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`, arm `merged/hybrid+rerank+metadata`.
- Smoke run first: 5 questions per arm in an ignored `--pilot` run, since deleted.
  - Every record was `success`; the replay clauses reported 0 failures.
  - Each reader showed the right model and `Anthropic`, with `is_byok` True and reasoning tokens 0.
  - deepseek showed `Wafer`, `is_byok` False and reasoning tokens 0.
- Counts: 200 of 200 records per arm.
  - Haiku 5.5, Sonnet 5.5 and Opus 5.5: 200 `success` each.
  - deepseek: 199 `success` and 1 error record. `mhr-e3837085bd7e` replicate 2 failed with `OpenRouter completion
    incomplete: finish_reason 'length'`. It was billed, so it was not retried. That G question has only 1 ok deepseek
    answer, so it leaves every pair with deepseek: those pairs cover 89 questions, and the pairs between Claude readers
    cover 90.
  - Every `Routing` line printed 0 misrouted records.
- Paired `answer_usable` against deepseek (`reader_comparison`; exact sign-flip p, reported, not used), beside S2:

  | Reader | S2 small (K = 5, 90 pairs) | this run, merged (K = 2, 89 pairs) | n_pos / n_neg | raw p | 95% CI (unadjusted) |
  |---|---|---|---|---|---|
  | deepseek (mean) | 0.8533 | 0.8483 | | | |
  | Haiku 5.5 | -16.0 points | -18.5 points | 6 / 27 | 1.0e-4 | [-27.5, -10.1] |
  | Sonnet 5.5 | -6.2 points | -5.6 points | 6 / 10 | 0.156 | [-12.9, +1.1] |
  | Opus 5.5 (descriptive) | -2.9 points | -2.2 points | 6 / 8 | 0.603 | [-8.4, +3.9] |

  Between Claude readers (90 pairs): Sonnet minus Haiku +13.9 (19 / 5, raw p 0.0017); Opus minus Haiku +17.2 (21 / 5,
  raw p 0.00017); Opus minus Sonnet +3.3 (4 / 2, raw p 0.25).
- Null guards: all evaluable and all pass, against deepseek and between readers (20 null pairs each, b = 0, c = 0).
  The S2 guards were not evaluable because of deepseek's null-question render errors, and none occurred here.
- Evidence split (`evidence_split`), `answer_usable` / abstention rate. The small rows are S2 (5 answers per question);
  the merged rows are this run (2 answers per question):

  | Reader | store | complete, usable | complete, abstain | partial, usable | partial, abstain | partial yes/no, abstain | all 90, usable | all 90, abstain |
  |---|---|---|---|---|---|---|---|---|
  | deepseek | small (31 / 59 G) | 0.890 | 0.065 | 0.834 | 0.132 | 0.243 | 0.853 | 0.109 |
  | deepseek | merged (42 / 48 G) | 0.867 | 0.096 | 0.833 | 0.135 | 0.239 | 0.849 | 0.117 |
  | Haiku 5.5 | small | 0.806 | 0.058 | 0.634 | 0.254 | 0.421 | 0.693 | 0.187 |
  | Haiku 5.5 | merged | 0.655 | 0.131 | 0.656 | 0.281 | 0.522 | 0.656 | 0.211 |
  | Sonnet 5.5 | small | 0.935 | 0.000 | 0.715 | 0.254 | 0.500 | 0.791 | 0.167 |
  | Sonnet 5.5 | merged | 0.881 | 0.024 | 0.719 | 0.229 | 0.478 | 0.794 | 0.133 |
  | Opus 5.5 | small | 0.968 | 0.000 | 0.749 | 0.217 | 0.421 | 0.824 | 0.142 |
  | Opus 5.5 | merged | 0.905 | 0.024 | 0.760 | 0.198 | 0.391 | 0.828 | 0.117 |

  Yes/no against open questions, all 90 G (usable / abstain):

  | Reader | small, yes/no (56) | merged, yes/no | small, open (34) | merged, open |
  |---|---|---|---|---|
  | deepseek | 0.782 / 0.157 | 0.775 / 0.171 | 0.971 / 0.029 | 0.971 / 0.029 |
  | Haiku 5.5 | 0.589 / 0.232 | 0.527 / 0.277 | 0.865 / 0.112 | 0.868 / 0.103 |
  | Sonnet 5.5 | 0.682 / 0.250 | 0.679 / 0.214 | 0.971 / 0.029 | 0.985 / 0.000 |
  | Opus 5.5 | 0.736 / 0.211 | 0.741 / 0.179 | 0.971 / 0.029 | 0.971 / 0.015 |

  Open questions are near the ceiling on both stores for all but Haiku. Every reader's losses sit in yes/no questions.
- The 15 moved questions (partial on small, complete on merged; 9 yes/no, 6 open), usable / abstain:

  | Reader | small (S2) | merged (this run) |
  |---|---|---|
  | deepseek | 0.880 / 0.120 | 0.828 / 0.138 |
  | Haiku 5.5 | 0.640 / 0.293 | 0.467 / 0.267 |
  | Sonnet 5.5 | 0.733 / 0.267 | 0.867 / 0.067 |
  | Opus 5.5 | 0.733 / 0.227 | 0.867 / 0.067 |

- Predictions:
  1. **Holds** for all three readers, on 15 questions at K = 2. Haiku 5.5 0.267 < 0.293, by one answer in 30 over S2's
     rate. Sonnet 5.5 0.067 < 0.267 and Opus 5.5 0.067 < 0.227. On these questions Sonnet 5.5 and Opus 5.5 overtake
     deepseek (0.867 against 0.828). Haiku 5.5 abstains less but answers worse (usable 0.640 to 0.467).
  2. **Holds** on the point estimates: Sonnet 5.5 -5.6 > -6.2, Opus 5.5 -2.2 > -2.9. Both moves are under 1 point,
     against 95% intervals 12 to 14 points wide, and the merged pairs cover 89 questions, not S2's 90. The run cannot
     tell these moves from noise.
- Reading: the abstention gap follows the evidence where it completes, but the store changes which questions have
  complete evidence and not the readers' behaviour on partial yes/no evidence. On merged, the complete set grows from
  31 to 42 G, five of them yes/no (28 to 33), so every reader's usable rate on complete evidence falls. On partial
  yes/no evidence the Claude readers still abstain on 39-52% of answers, against deepseek's 24%.
- `reasoning_tokens` (journal, the new records of each arm):

  | Arm | thinking | total | mean per record |
  |---|---|---|---|
  | deepseek, replicate 2 | the engine's `pack` body unrewritten, temperature 0 (D-278) | 0 over 100 | 0.0 |
  | Haiku 5.5 | off | 0 | 0.0 |
  | Sonnet 5.5 | `between_tools`, sync API (D-280) | 0 | 0.0 |
  | Opus 5.5 | on at effort low (D-265) | 441 (3 of 200 records nonzero) | 2.2 |

- Spend, from each record's usage at the declared prices. Haiku 5.5 and Opus 5.5 are at the batch rate, Sonnet 5.5 and
  deepseek at the sync price. The OpenRouter activity page was not read.

  | Arm | requests | spend |
  |---|---|---|
  | Haiku 5.5 | 200 | $0.0863 |
  | Sonnet 5.5 | 200 | $3.5764 |
  | Opus 5.5 | 200 | $3.4619 |
  | deepseek | 100 | $0.0265 |
  | **Run** | | **$7.15** |
  | Smoke run (5 questions per arm) | 35 | about $0.35 |

  About $7.50 in all, against the estimate of about $7 and the ceiling of $15. The prompts averaged about 6,600 Claude
  tokens a request (about 3,760 for deepseek). `lever-comparison.json` prints Sonnet's `batch_spend` at the batch rate,
  $1.79, half what it cost (#139).
- Batch IDs (`batches/`):
  - Haiku 5.5 `batch-1793526962-UCzzE5jnJkwMFzEMHhrY`
  - Opus 5.5 `batch-1793526966-Y0hXpHREkQhdmWDpGOoC`
  - Sonnet 5.5 `sync-merged_hybrid_rerank_metadata_sonnet_5_5-1-1793526974`
  - deepseek `sync-merged_hybrid_rerank_metadata-1-1793527959`
- #128: the retrieval secondaries in `report.json` and `lever-comparison.json` read v1.0 gold chunks against merged
  chunk IDs, so they are not read here. `answer_usable`, the abstention rate and the evidence split read none of them.
- `lever-comparison.json`'s `default_decisions` (Haiku 5.5 "significantly worse, stays off"; Sonnet 5.5 "not
  significant") are not read: this run decides nothing.
- Every `lancet-eval` command ran with `PYTHONUTF8=1` (#84). No answer judges were run.
