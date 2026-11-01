# S3M: does the graph's loss on MultiHop-RAG come from the writer? (exploratory)

Status: **predictions written 2026-11-01, before any extraction of the grid and any reading run.** The **Result**
section is filled in after the run, and nothing above it changes.

This run is exploratory (#148). It decides nothing and changes no S1, S2 or S3 decision: the graph stays out
(EXPERIMENT-S1.md › Result). Owner, 2026-11-01: "全部接受" (item E of the coordinator's package).

## Question

S1 found the graph hurts on MultiHop-RAG: on the small store, `small/hybrid+graph+rerank+metadata` against
`small/hybrid+rerank+metadata` reads -8.9 points (n_pos 2, n_neg 10). #126 found junk month and publisher entities in
deepseek's extraction. Does a stronger writer's graph remove the loss?

## Writers

Every writer extracts the same chunks: every extractable chunk of S1's 346 documents as the v1.0 small store chunks them
(`structure-aware`, 500/50 characters, D-09): **15,264 chunks**
([s3m-writers/chunks.jsonl](s3m-writers/chunks.jsonl), `python -m lancet_eval.writer_grid plan`). Each gets the
engine's extraction request: its system and user messages, the strict `knowledge_graph_extraction` schema and
`max_completion_tokens` 16,384 (D-272), as #117's writer pilot sends it (`writer_pilot`).

| Writer | Model | Thinking (owner ruling 2026-11-01) | Transport | Graph |
|---|---|---|---|---|
| deepseek | `deepseek/deepseek-v4-flash-0731` | off | OpenRouter sync API, pinned (D-271, D-278) | its own graph side tables |
| Haiku 5.5 | `anthropic/claude-haiku-5.5` | off | OpenRouter Batch API, BYOK | its own graph side tables |
| Sonnet 5.5 | `anthropic/claude-sonnet-5.5` | on, effort low | OpenRouter Batch API, BYOK | its own graph side tables |
| Opus 5.5 | `anthropic/claude-opus-5.5` | on, effort low | OpenRouter Batch API, BYOK | none: a spot check on the pilot's 1,803 chunks |

- **Scope.** The full four-writer grid costs about $105 of Claude credit, which does not fit. The coordinator chose,
  within the owner's spend approval (2026-11-01): Haiku 5.5 and Sonnet 5.5 on every chunk; Opus 5.5 on the pilot's
  1,803 chunks only, compared on extraction figures and never read; deepseek re-extracted with the same script,
  last, since the credit deadline does not bind it.
- The v1.0 store's own graph, the one S1 read, is not a writer here: it was extracted at another granularity, so it
  would confound the writer comparison.
- The pilot's (#117) answers for its 1,803 chunks are reused for every writer it ran: the request is a function of
  the chunk text, and the grid checks the text is the same.
- Each writer's answers are loaded into graph side tables of the v1.0 store, new tables beside the existing ones,
  through the engine's own graph write path, with entity names embedded by Voyage as at ingest. The existing S1, S2
  and v1.0 tables are never modified.
- If deepseek's extraction does not run (OpenRouter balance), the Claude writers are still read, and the reading is
  open (below).

## Arms and runs

Corpus `multihop_rag_s3m_dev`: S1's documents, questions, split and small store (a test pins this). The D-237 dev pool
of 100 (90 G, 10 null). No held-out question is read.

| Runs | Arm | Graph |
|---|---|---|
| 2 reference runs | `small/hybrid+rerank+metadata` | off |
| 2 runs per writer (deepseek, Haiku 5.5, Sonnet 5.5) | `small/hybrid+graph+rerank+metadata` | that writer's graph tables |

Each run answers each question once, with deepseek as reader, so every arm has K = 2 answers per question. The engine
is otherwise the v1.0 small-store stack of S1's run.

## Pre-registration constant

`PREREGISTRATION_S3M` in [`thresholds.py`](../../eval/src/lancet_eval/thresholds.py): `PREREGISTRATION_S1`'s
reference, family arm and every number, with the replicate test (D-274) for K = 2 (a test pins this). It is read once
per writer. The family is `decisional` only because the lever comparison needs one.

`compare-levers` cannot produce this reading: it pairs arms within one run and reads K from a replay constant's
`replicates`. The reading pairs runs across directories and is computed by hand (or a script added with the Result)
from the journals, with the rule above.

## Metrics

Per writer, on the 90 G questions, paired against the reference:

- `answer_usable`: a question's score is the mean of its 2 answers. The paired delta in points, n_pos and n_neg, and
  the exact sign-flip p on the per-question mean differences (reported, not used).
- the same, split into yes/no questions (gold `yes` or `no`) and open questions;
- the null guard on the 10 nulls: margin 0.10, pair fraction 0.80 (D-264);
- #126's junk entities per writer (`writer_pilot.junk_kind`): dates (months, weekdays, years, dates) and corpus
  publishers, as counts and per 1,000 entities, with the top 10 names;
- entities and relations per chunk, and entity-name overlap with deepseek's extraction;
- on the pilot's 1,803 chunks, the same extraction figures for Opus 5.5 beside the other writers;
- the extraction spend per writer.

## Reading

- **The writer explains the loss** if some Claude writer's delta is at least 0 and at least 5 points above deepseek's
  delta in this run.
- **The writer does not explain it** if every Claude writer's delta is below 0 and within 5 points of deepseek's.
- Otherwise, or without a deepseek graph, the reading is open.

With 90 G pairs a significant difference needs about 10 to 13 points net (EXPERIMENT-S1.md › Smallest detectable
effect), so this reading uses point estimates, and either answer is a direction, not a finding.

## Predictions

Written before the run. Each is checked once against the Result and never tuned to it.

1. **deepseek repeats S1.** deepseek's delta in this run is below 0.
2. **Fewer junk entities.** Each Claude writer, Opus 5.5 on its spot check included, extracts fewer date and publisher
   entities per 1,000 entities than deepseek on the same chunks.
3. **The writer does not explain the loss.** The graph context's harm on MultiHop-RAG comes from how the graph context
   enters the prompt, not from who wrote the graph: every Claude writer's delta is below 0, within 5 points of
   deepseek's.

## Spend

- Claude extraction (`writer_grid plan` prints each estimate; the pilot's measured Batch API rates are about $0.11
  per 1,000 chunks for Haiku 5.5 and $2.27 for Sonnet 5.5, and Opus 5.5 is priced at twice Sonnet's rates): Haiku 5.5
  about $1.5 and Sonnet 5.5 about $31 for the 13,461 chunks the pilot did not answer, Opus 5.5 about $8. Ceiling:
  Claude credit $45.
- deepseek extraction (13,461 chunks beyond the pilot's, sync) about $2, and the reading: 8 runs of one arm with
  deepseek as reader, about $0.10 each, plus Voyage embeddings of entity names. Ceiling: OpenRouter $3. deepseek's
  extraction runs only if OpenRouter's balance stays above $1 after lanes 145 and 149.

## Result

Not run yet.
