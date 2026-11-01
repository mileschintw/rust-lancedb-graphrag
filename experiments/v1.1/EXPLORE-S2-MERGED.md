# S2X: S2's readers on the merged store (exploratory)

Status: **predictions written 2026-11-01, before any data of this run.** The **Result** section is filled in after the
run, and nothing above it changes.

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

Not run yet.
