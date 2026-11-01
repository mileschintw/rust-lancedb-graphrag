# B: the S2 readers on 2Wiki, hybrid without a graph (exploratory)

Status: **predictions written 2026-11-01, before any data of this run.** The **Result** section is filled in after the
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
- both, split by 2Wiki question type and by evidence (complete, partial: `metrics.gold_contained` over the context,
  as `evidence_split` reads it);
- the paired per-question difference against deepseek, with a bootstrap 95% interval;
- `reasoning_tokens` (total and mean per record) and the spend.

## How to run it

[RUN-EXPLORE-BC.md](RUN-EXPLORE-BC.md), part B.

## Result

Not run yet.
