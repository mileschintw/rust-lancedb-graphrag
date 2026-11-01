# B: the S2 readers on 2Wiki, hybrid without a graph (exploratory)

Status: **run 2026-11-01; predictions written 2026-11-01, before any data of this run.** The **Result** section is filled in after the
run, and nothing above it changes.

This run is exploratory (#149, item B). It decides nothing and changes no S2 or S3 decision; S3's design is its own
(D-234). Owner, 2026-11-01: "全部接受" (the coordinator's package, items B and C).

## Question

How do the S2 readers do on 2WikiMultiHopQA, S3's second benchmark, with the hybrid retriever and no graph? S3 will
compare graph arms against this kind of baseline. This run gives each reader's level, the gap between readers, and
where they fail (retrieval or reading), before S3 spends anything on the graph.

## Arms

C's arms and K on the 2Wiki store: deepseek and Haiku 5.5 answer each question **2 times**, Sonnet 5.5 and Opus 5.5
**once**. Each reader keeps its S2 transport and thinking.

| Arm label | Reader | K | How it is read |
|---|---|---|---|
| `twowiki/hybrid+rerank+metadata` (reference) | deepseek | 2 | replicate 1 driven by `run` on the 2Wiki store; replicate 2 by OpenRouter's sync API, pinned as in D-278 |
| `twowiki/hybrid+rerank+metadata@haiku-5.5` | Haiku 5.5 | 2 | OpenRouter batch, BYOK, thinking off |
| `twowiki/hybrid+rerank+metadata@sonnet-5.5` | Sonnet 5.5 | 1 | OpenRouter's sync API, BYOK, `between_tools` (D-280) |
| `twowiki/hybrid+rerank+metadata@opus-5.5` (descriptive) | Opus 5.5 | 1 | OpenRouter batch, BYOK, thinking on at effort low |

## Data

- **Store** `eval-2wiki` (`data/lancedb-eval-2wiki`, schema `lancet_eval_2wiki`): #145's 6,119 passages from
  `osunlp/HippoRAG_2` at revision `5ec05b38deecc3318bb432c69865959c56058990`, ingested as given. Each passage is one
  document whose body is its title, a newline and its text (HippoRAG 2's unit), and one chunk: fixed-size windows of
  8,192 characters hold the longest passage (6,457). No graph (`[engine.graph] ingest_extraction = false`). The
  passages are Wikipedia text, so the documents file stays in the gitignored `.cache/`; the corpus pins its sha256.
- **Questions:** the 100 dev questions of the D-243 split (`eval/corpora/twowiki/split.json`, seed 243), carried
  into the drive's split model as `eval/corpora/twowiki/s3b_split.json`. Each gold fact is a supporting sentence from
  the question's own context. The 900 held-out questions are never read here.
- Corpus `twowiki_s3b_dev`: 100 records per K per arm, 600 answers in all.

## Pre-registration constant

`PREREGISTRATION_EXPLORE_B` in [`thresholds.py`](../../eval/src/lancet_eval/thresholds.py):
`PREREGISTRATION_EXPLORE_C` with every arm moved to `twowiki/`. Readers, prices, thinking, K and every number are
C's, and so S2X's (a test pins this). `compare-levers` reads one K for every arm, so this run is read by hand.

## Predictions

Written before the run. Each is checked once against the Result and never tuned to it.

1. **A middling level.** Each reader's `answer_usable` over the 100 dev questions is between 0.35 and 0.80: the
   hybrid retriever often misses one of the two hops, and `answer_usable` needs the exact gold string (2Wiki gives no
   aliases here).
2. **Comparison is easier.** For every reader, `answer_usable` on the `comparison` and `bridge_comparison` questions
   is higher than on the `compositional` and `inference` questions, whose second hop names an entity the question
   does not.
3. **Retrieval, not reading, limits the open questions.** For every reader, `answer_usable` on the questions whose
   context holds every supporting sentence is at least 0.20 above that on the questions whose context misses one.
4. **The Claude readers abstain more.** Haiku 5.5's and Sonnet 5.5's abstention rates are each above deepseek's.

Each prediction is read on the point estimates.

## What the Result reports

Per reader:

- `answer_usable` over all its answers, and its abstention rate (`metrics.is_abstention`);
- both, split by 2Wiki question type, by yes/no against open questions (#147), and by evidence (complete, partial:
  `metrics.gold_contained` over the context, as `evidence_split` reads it);
- the paired per-question difference against deepseek, with a bootstrap 95% interval;
- `reasoning_tokens` (total and mean per record) and the spend.

## How to run it

[RUN-EXPLORE-BC.md](RUN-EXPLORE-BC.md), part B.

## Result

**Retrieval limits every reader, and Opus 5.5 reads the partial contexts best.** Over the 100 D-243 dev questions,
`answer_usable` is 0.56 for Opus 5.5, 0.44 for Sonnet 5.5, 0.42 for deepseek and 0.39 for Haiku 5.5. Only Opus differs
clearly from deepseek: 14.0 points above (95% CI +8.0 to +20.5). Half the questions (51) get a context missing a
supporting sentence, and there every reader except Opus answers almost nothing usable. All four predictions hold on
the point estimates. The run decides nothing.

- Runs: the deepseek drive `eval/runs/2026-11-01-explore-b-drive-twowiki_s3b_dev`, carried by `replay-init` into the
  run of record `eval/runs/2026-11-01-explore-b-twowiki_s3b_dev`. Both are committed, uncompressed.
  [`explore-bc-runs.json`](explore-bc-runs.json) records every file's size and sha256.
  Both ran on `main` at `68c100a5` (#157). Pre-registration `PREREGISTRATION_EXPLORE_B`, frozen by `45633be1`. Dev
  only (D-243); none of the 900 held-out questions was read.
- Store `eval-2wiki`: 6,119 of 6,119 passages completed, all fixed-size 8,192/0 (one chunk each), no graph. As on C,
  the seed's final probe recorded the index generation before it settled; a second `seed` recorded the live one
  (`lance-12239`) and every preflight check passed. The drive's header `partial` field was set to `false` by hand, as
  on C (EXPLORE-C-MHR-FULL.md › Result).
- Counts, each arm at its K: deepseek 200 (199 `success`), Haiku 5.5 200 (200), Sonnet 5.5 100 (100), Opus 5.5 100
  (100). Every `Routing` line printed 0. The one error record is deepseek's replicate 2 of
  `8820c510086411ebbd5eac1f6bf848b6`, a billed render error (`answer basis 'mixed' requires at least one cited evidence
  ID`), not retried.
- Per reader, all answers (`explore_readout`; the paired delta as in C). Every dev question has gold evidence, so
  there is no null stratum:

  | Reader | K | answers | answer_usable | abstention | delta vs deepseek [95% CI] | reasoning tokens |
  |---|---|---|---|---|---|---|
  | deepseek | 2 | 199 | 0.422 | 0.452 | – | 0 |
  | Haiku 5.5 | 2 | 200 | 0.385 | 0.545 | -3.5 [-9.0, +1.5] (100) | 0 |
  | Sonnet 5.5 | 1 | 100 | 0.440 | 0.470 | +2.0 [-3.5, +7.5] (100) | 0 |
  | Opus 5.5 | 1 | 100 | 0.560 | 0.380 | +14.0 [+8.0, +20.5] (100) | 640 (6 per answer) |

- By 2Wiki question type, `answer_usable` (questions: 26 bridge-comparison, 25 comparison, 40 compositional, 9
  inference):

  | Reader | bridge_comparison | comparison | compositional | inference |
  |---|---|---|---|---|
  | deepseek | 0.216 | 0.940 | 0.200 | 0.556 |
  | Haiku 5.5 | 0.038 | 0.920 | 0.200 | 0.722 |
  | Sonnet 5.5 | 0.115 | 0.920 | 0.275 | 0.778 |
  | Opus 5.5 | 0.500 | 0.960 | 0.300 | 0.778 |

- Evidence and kind, usable / abstention. The context holds every supporting sentence for 49 questions and misses one
  for 51. 15 questions have a yes/no gold answer (#147; balanced accuracy beside it, the better constant scoring
  0.667 of them):

  | Reader | complete (49) | partial (51) | yes/no (15) | yes/no balanced accuracy | open (85) |
  |---|---|---|---|---|---|
  | deepseek | 0.724 / 0.112 | 0.129 / 0.782 | 0.833 / 0.100 | 0.875 | 0.349 / 0.515 |
  | Haiku 5.5 | 0.745 / 0.143 | 0.039 / 0.931 | 0.600 / 0.267 | 0.675 | 0.347 / 0.594 |
  | Sonnet 5.5 | 0.816 / 0.082 | 0.078 / 0.843 | 0.733 / 0.133 | 0.800 | 0.388 / 0.529 |
  | Opus 5.5 | 0.837 / 0.082 | 0.294 / 0.667 | 0.867 / 0.067 | 0.900 | 0.506 / 0.435 |

- Predictions, on the point estimates:
  1. **A middling level: holds.** Every reader is between 0.35 and 0.80 (0.385 to 0.560).
  2. **Comparison is easier: holds**, pooled over the two kinds each side. Comparison and bridge-comparison against
     compositional and inference: deepseek 0.574 against 0.265, Haiku 0.470 against 0.296, Sonnet 0.510 against
     0.367, Opus 0.725 against 0.388. The gain is all `comparison`: `bridge_comparison` is the hardest type for every
     reader but Opus.
  3. **Retrieval limits the open questions: holds.** Complete against partial evidence is 0.54 to 0.74 apart for
     every reader, far above the 0.20 predicted.
  4. **The Claude readers abstain more: holds**, narrowly for Sonnet 5.5: Haiku 0.545 and Sonnet 0.470 against
     deepseek's 0.452.
- Spend, from each record's usage at the declared prices:

  | Arm | requests | spend |
  |---|---|---|
  | deepseek drive (embedding, rerank and answers; the drive's observed spend) | 100 | $0.08 |
  | deepseek replicate 2 (sync) | 100 | $0.02 |
  | Haiku 5.5 (batch) | 200 | $0.06 |
  | Sonnet 5.5 (sync) | 100 | $1.22 |
  | Opus 5.5 (batch) | 100 | $1.20 |
  | **Claude credit** | | **$2.48** |
  | **OpenRouter credit** (plus the store build's embeddings, a few cents) | | **about $0.10** |

  With C, #149 spent about $30.82 of Claude credit and about $1.50 of OpenRouter credit, inside the ceilings ($70,
  $3).
- Batch IDs: Haiku 5.5 `batch-1793554847-sl3oSTr43khYATjfXWvJ`; Opus 5.5 `batch-1793554851-3zKeCVwboCmvAILOYqeg`;
  Sonnet 5.5 `sync-twowiki_hybrid_rerank_metadata_sonnet_5_5-1-1793554858`; deepseek
  `sync-twowiki_hybrid_rerank_metadata-1-1793555154`.
- `score` and `compare-levers` were not run (RUN-EXPLORE-BC.md › Readout). No answer judges.
