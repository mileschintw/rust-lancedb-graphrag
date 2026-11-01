# C: full MultiHop-RAG on fresh questions (exploratory)

Status: **predictions written 2026-11-01, before any data of this run.** The **Result** section is filled in after the
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

Not run yet.
