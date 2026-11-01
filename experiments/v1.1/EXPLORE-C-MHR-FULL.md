# C: full MultiHop-RAG on fresh questions (exploratory)

Status: **run 2026-11-01; predictions written 2026-11-01, before any data of this run.** The **Result** section is filled in after the
run, and nothing above it changes.

This run is exploratory (#149, item C). It decides nothing and changes no S2 or S3 decision. Owner, 2026-11-01:
"全部接受" (the coordinator's package, items B and C).

## Question

How do the S2 readers compare on many more questions, over all 609 MultiHop-RAG documents? S0 to S2 read the same
100 dev questions (90 G) against a 346-document subset, which detects only gaps of about 8 points (#146). This run
reads 1,000 questions no earlier run read, so it shows each reader's level and its gap to deepseek with about a third
of that noise, on a store whose distractors are every other article in the dataset. It also sets up #146: the fresh
held-out set it reserves is the one #146 can read once.

## Arms

S2X's four arms on the full store. Each reader keeps its S2 transport and thinking (PREREGISTRATION_S2X's
declarations), so each one compares with S2 and S2X directly. K per the accepted principle 3: deepseek and Haiku 5.5
answer each question **2 times**, Sonnet 5.5 and Opus 5.5 **once**.

| Arm label | Reader | K | How it is read |
|---|---|---|---|
| `full/hybrid+rerank+metadata` (reference) | deepseek | 2 | replicate 1 driven by `run` on the full store; replicate 2 by OpenRouter's sync API, pinned as in D-278 |
| `full/hybrid+rerank+metadata@haiku-5.5` | Haiku 5.5 | 2 | OpenRouter batch, BYOK, thinking off |
| `full/hybrid+rerank+metadata@sonnet-5.5` | Sonnet 5.5 | 1 | OpenRouter's sync API, BYOK, `between_tools` (D-280) |
| `full/hybrid+rerank+metadata@opus-5.5` (descriptive) | Opus 5.5 | 1 | OpenRouter batch, BYOK, thinking on at effort low |

## Data

- **Store** `eval-full` (`data/lancedb-eval-full`, schema `lancet_eval_full`): all 609 articles of MultiHop-RAG's
  `corpus.json`, chunked structure-aware 500/50 as the v1.0 store is, with no graph (`[engine.graph]
  ingest_extraction = false`). The article texts stay in the gitignored `.cache/`; the corpus pins the file's sha256.
- **Questions:** the 1,000 dev questions of `eval/corpora/multihop_rag/fresh_split.json` (seed 149, split sha256
  `30d3dee89824cf4ef89b960a26889a2f1f8bed9128a47d341b93da0376d80e7d`). The pool is every MultiHop-RAG question whose
  ID is in no committed question file and not in the D-105 split: 2,056 of 2,556. The split was built from question IDs
  alone. Its other 1,056 questions are held out for #146 and never read here; nothing sorted them into G and null.
- Corpus `multihop_rag_full_dev`: 1,000 records per K per arm, 6,000 answers in all. No held-out question is read
  (D-237).

## Pre-registration constant

`PREREGISTRATION_EXPLORE_C` in [`thresholds.py`](../../eval/src/lancet_eval/thresholds.py): `PREREGISTRATION_S2X`
with every arm moved to `full/` and `reader_replicates` giving Sonnet and Opus K = 1. Readers, prices, thinking, test
and every number are S2X's (a test pins this). The family is `decisional` only because the class needs one.
`compare-levers` reads one K for every arm, so this run is read by hand, as below.

## Predictions

Written before the run. Each is checked once against the Result and never tuned to it. S2's 90 G questions (small
store, K = 5) gave `answer_usable` 0.853 for deepseek, 0.693 for Haiku 5.5, 0.791 for Sonnet 5.5 and 0.824 for Opus
5.5 (EXPLORE-S2-MERGED.md).

1. **Same order.** On the fresh G questions, `answer_usable` (all answers of each arm) ranks deepseek ≥ Opus 5.5 ≥
   Sonnet 5.5 > Haiku 5.5, as in S2.
2. **The gap is the abstention on partial evidence.** For Haiku 5.5 and Sonnet 5.5, the deepseek-minus-reader gap
   in `answer_usable` is larger on the G questions whose context holds only part of the gold facts than on those
   whose context holds all of them, and each Claude reader abstains more than deepseek on the partial ones.
3. **Yes/no carries the gap.** For Haiku 5.5 and Sonnet 5.5, the deepseek-minus-reader gap is larger on yes/no G
   questions than on open G questions (#147: `answer_usable` rewards guessing on yes/no).
4. **The bigger store costs a little.** Each reader's `answer_usable` on the fresh G questions is within 8 points
   below its S2 value, and not above it: the fresh questions and the 263 extra distractor articles together make the
   task no easier.

Each prediction is read on the point estimates. Where the Result gives a paired interval, it says whether the
interval excludes 0.

## What the Result reports

Per reader:

- `answer_usable` over all its answers, and its abstention rate (`metrics.is_abstention`), on the fresh G questions;
- the null questions' abstention rate;
- both, split by evidence (complete, partial: `metrics.gold_contained` over the context, as `evidence_split` reads
  it) and by kind (yes/no, open);
- the paired per-question difference against deepseek, with a bootstrap 95% interval;
- `reasoning_tokens` (total and mean per record) and the spend.

## How to run it

[RUN-EXPLORE-BC.md](RUN-EXPLORE-BC.md), part C.

## Result

**Opus 5.5 beats deepseek, Sonnet 5.5 ties it, Haiku 5.5 trails.** On the 882 fresh G questions over all 609
articles, Opus 5.5 scores 5.0 points above deepseek (95% CI +2.4 to +7.8), Sonnet 5.5 1.5 points above (CI -1.1 to
+4.2), and Haiku 5.5 5.6 points below (CI -8.0 to -2.9). With S2's 90 questions, Sonnet and Opus looked a little behind
deepseek; at this size that gap is gone, and Opus leads. Prediction 1 does not hold, predictions 2 and 3 hold, and
prediction 4 holds for Sonnet and Opus only. The run decides nothing.

- Runs: the deepseek drive `eval/runs/2026-11-01-explore-c-drive-multihop_rag_full_dev`, carried by `replay-init`
  into the run of record `eval/runs/2026-11-01-explore-c-multihop_rag_full_dev`. Both are committed; every file over
  10 MB is gzipped (each directory's `README.md`). [`explore-bc-runs.json`](explore-bc-runs.json) records every
  uncompressed file's size and sha256.
  Both ran on `main` at `68c100a5`
  (#157). Pre-registration `PREREGISTRATION_EXPLORE_C`, frozen by `6b5274b7`. Dev only (1,000 fresh dev questions: 882
  G, 118 null). No held-out question was read.
- Store `eval-full`: 609 of 609 articles completed, all structure-aware 500/50, no graph. Preflight passed after one
  re-record of the index generation: the seed's final probe ran before the engine's background index work settled
  (`lance-1205` against `lance-1219`), and a second `seed` uploaded nothing and recorded `lance-1219`.
- `run` writes `partial: true` into every drive journal's header, and `lancet-eval reconcile` flips it once every
  work unit of the corpus has a record. Here the corpus also lists the reader arms, which a drive never runs, so
  `reconcile` reports 3,000 missing units. With a record of every question under the driven arm (which `replay-init`
  checks itself), the one field was set to `false` by hand before `replay-init`. The rest of the file is
  byte-identical; the original header began
  `{"type": "header", "corpus": "multihop_rag_full_dev", "partial": true, "created_at": 1793534890.1003654, …}`.
- Counts, each arm at its K: deepseek 2,000 (1,969 `success`), Haiku 5.5 2,000 (1,991), Sonnet 5.5 1,000 (997), Opus 5.5
  1,000 (996). Every `Routing` line printed 0. The error records:
  - 3 questions whose deepseek drive failed in `GenerateAnswer` after 2 retries (`mhr-11d9213f77f1`,
    `mhr-30de94fdea76`, `mhr-bf6e3d9cc4d9`). They have no context, so every reader's records for them are `base_error`.
  - deepseek replicate 2: 25 billed render errors, `answer basis 'mixed' requires at least one cited evidence ID`.
  - Haiku 5.5: 3 billed render errors (`mhr-a00d259af24f` r1, `mhr-e259b6542b7d` r2: no cited evidence ID;
    `mhr-fa81dcbc9b69` r2: `finish_reason 'length'`). Opus 5.5: 1 (`mhr-b53d4e307cb7`: `ModelOnly answer basis is
    not supported`). Billed render errors are not retried.
- Per reader, all answers (`explore_readout`; the paired delta is the mean over the G questions both answered of the
  reader's per-question mean minus deepseek's, with a bootstrap 95% interval):

  | Reader | K | G answers | answer_usable | abstention | null abstention | delta vs deepseek [95% CI] | reasoning tokens |
  |---|---|---|---|---|---|---|---|
  | deepseek | 2 | 1,761 | 0.763 | 0.138 | 0.966 | – | 0 |
  | Haiku 5.5 | 2 | 1,761 | 0.708 | 0.171 | 0.996 | -5.6 [-8.0, -2.9] (882) | 0 |
  | Sonnet 5.5 | 1 | 882 | 0.778 | 0.137 | 0.991 | +1.5 [-1.1, +4.2] (882) | 0 |
  | Opus 5.5 | 1 | 882 | 0.813 | 0.105 | 0.991 | +5.0 [+2.4, +7.8] (882) | 4,512 (5 per answer) |

- Yes/no against open (#147), all G answers. Balanced accuracy is the mean of the gold-Yes and gold-No rates; any
  constant answer scores 0.5:

  | Reader | yes/no usable | open usable | yes/no balanced accuracy | better constant |
  |---|---|---|---|---|
  | deepseek | 0.662 | 0.919 | 0.652 | 0.538 |
  | Haiku 5.5 | 0.590 | 0.889 | 0.590 | 0.538 |
  | Sonnet 5.5 | 0.676 | 0.934 | 0.678 | 0.537 |
  | Opus 5.5 | 0.721 | 0.954 | 0.723 | 0.537 |

- Evidence split (`evidence_split`), usable / abstention. The context holds every gold fact for 276 of the 882 G
  questions (194 yes/no, 82 open), and only part of them for 606 (340 yes/no, 266 open):

  | Reader | complete | partial | partial yes/no | partial open |
  |---|---|---|---|---|
  | deepseek | 0.790 / 0.078 | 0.751 / 0.165 | 0.602 / 0.268 | 0.942 / 0.034 |
  | Haiku 5.5 | 0.765 / 0.075 | 0.681 / 0.215 | 0.507 / 0.334 | 0.904 / 0.062 |
  | Sonnet 5.5 | 0.895 / 0.018 | 0.724 / 0.191 | 0.550 / 0.318 | 0.947 / 0.030 |
  | Opus 5.5 | 0.920 / 0.004 | 0.764 / 0.152 | 0.603 / 0.262 | 0.970 / 0.011 |

- By question type, `answer_usable`:

  | Reader | comparison | inference | temporal |
  |---|---|---|---|
  | deepseek | 0.718 | 0.975 | 0.560 |
  | Haiku 5.5 | 0.610 | 0.946 | 0.543 |
  | Sonnet 5.5 | 0.697 | 0.987 | 0.627 |
  | Opus 5.5 | 0.730 | 0.997 | 0.697 |

- Predictions, on the point estimates:
  1. **Same order: does not hold.** The order is Opus 5.5 (0.813) > Sonnet 5.5 (0.778) > deepseek (0.763) > Haiku 5.5
     (0.708). deepseek is third, not first.
  2. **The gap is the abstention on partial evidence: holds.** The deepseek-minus-reader gap is larger on partial
     than on complete evidence for Haiku 5.5 (7.0 against 2.5 points) and Sonnet 5.5 (2.7 against -10.5 points), and
     both abstain more than deepseek on partial evidence (0.215 and 0.191 against 0.165).
  3. **Yes/no carries the gap: holds, by a hair for Sonnet.** Haiku 5.5: 7.2 points on yes/no against 3.0 on open.
     Sonnet 5.5: -1.4 against -1.5 points, a difference far inside the noise.
  4. **The bigger store costs a little: holds for Sonnet 5.5 and Opus 5.5 only.** Against S2 (small store, 90
     questions): Sonnet 0.791 → 0.778 and Opus 0.824 → 0.813, each within 8 points below. deepseek falls 9.0 points
     (0.853 → 0.763), more than 8. Haiku rises (0.693 → 0.708).
- Read with care: the delta's interval treats the 882 questions as the population and ignores the per-question
  sampling of K; Sonnet and Opus give one answer per question, so their per-question values are noisier than
  deepseek's mean of two.
- Spend, from each record's usage at the declared prices (Haiku and Opus at the batch rate, Sonnet and deepseek at
  the sync price). The OpenRouter activity page was not read.

  | Arm | requests | spend |
  |---|---|---|
  | deepseek drive (embedding, rerank and answers; the drive's observed spend) | 1,000 | $0.98 |
  | deepseek replicate 2 (sync) | 997 | $0.20 |
  | Haiku 5.5 (batch) | 1,994 | $0.67 |
  | Sonnet 5.5 (sync) | 997 | $14.16 |
  | Opus 5.5 (batch) | 997 | $13.51 |
  | **Claude credit** | | **$28.34** |
  | **OpenRouter credit** (plus the store build's embeddings, about $0.20) | | **about $1.40** |

  Both are inside the guide's estimates (Claude $27-37) and the ceilings ($70, $3).
- Batch IDs: Haiku 5.5 `batch-1793539362-VYat98UIMCauB62LY5j1`; Opus 5.5
  `batch-1793539374-tGDmasDW1ynki5zsHLIZ`; Sonnet 5.5 `sync-full_hybrid_rerank_metadata_sonnet_5_5-1-1793539384`;
  deepseek `sync-full_hybrid_rerank_metadata-1-1793544356`.
- `score` and `compare-levers` were not run (RUN-EXPLORE-BC.md › Readout). No answer judges.
