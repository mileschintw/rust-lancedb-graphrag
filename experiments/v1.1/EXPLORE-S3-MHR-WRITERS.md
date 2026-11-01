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

Run 2026-11-01 (#148), dev pool only, no held-out read. **Reading: open.** The Claude writers' graphs read below 0,
but exactly 5 points below deepseek's, which is not within 5 points (below). It decides nothing: the graph stays out.

**The loss does not reproduce on deepseek's re-extracted graph.** S1's -8.9 points came from the v1.0 graph. On the
same store, deepseek's own re-extraction at the grid's granularity reads +1.7 points.

### Answers (`answer_usable`, K = 2, paired against the reference on the 90 G questions)

| Writer's graph | All 90: arm / reference, delta | n_pos / n_neg | p | Yes/no (56) delta | Open (34) delta | Null guard |
|---|---|---|---|---|---|---|
| deepseek | 0.878 / 0.861, **+1.7** | 8 / 5 | 0.654 | +2.7 | 0.0 | passes (10 pairs, drop 0) |
| Haiku 5.5 | 0.828 / 0.861, **-3.3** | 4 / 10 | 0.333 | -6.2 | +1.5 | passes (10 pairs, drop 0) |
| Sonnet 5.5 | 0.828 / 0.861, **-3.3** | 4 / 10 | 0.268 | -6.2 | +1.5 | passes (10 pairs, drop 0) |

- Every comparison is evaluable: 90 of 90 G questions pair, as do 10 of 10 nulls.
- Haiku's and Sonnet's figures are equal, but their answers are not. They differ on 14 questions. Each loses on 10
  questions, and 5 of those are the same questions for both.
- **Rule.** The Claude deltas are -6/180 and deepseek's is +3/180, so they are exactly 5 points apart.
  - "Within 5 points" is read as a distance on either side, with 5 points apart not within. That is the boundary
    `s3m_reading`'s tests fixed before any S3M run (deepseek -9, Sonnet -4: open).
  - The script first checked only the side above deepseek. It was corrected to the frozen text after this run's
    numbers were in. That one-sided version would have read "does not explain".
  - Either way, every p is above 0.25 and the gap is within the 10 to 13 points a significant difference needs, so
    no reading here is a finding.
- Read with `python -m lancet_eval.s3m_reading` → [s3m-writers/reading.json](s3m-writers/reading.json).

### Extraction (`writer_grid report` → [s3m-writers/summary.json](s3m-writers/summary.json))

| Writer | Chunks | Entities / chunk | Relations / chunk | Dates per 1,000 entities | Publishers per 1,000 | Entity Jaccard vs deepseek | Runaways (#156) |
|---|---|---|---|---|---|---|---|
| deepseek | 15,264 | 4.08 | 3.22 | 16.9 | 3.9 | – | 245 |
| Haiku 5.5 | 15,264 | 4.99 | 4.45 | 25.0 | 3.7 | 0.67 | 0 |
| Sonnet 5.5 | 15,264 | 5.21 | 4.52 | 23.2 | 3.6 | 0.63 | 0 |
| *Pilot's 1,803 chunks:* deepseek | 1,803 | 4.24 | 3.39 | 14.8 | 5.2 | – | 23 |
| Haiku 5.5 | 1,803 | 5.24 | 4.78 | 22.1 | 6.1 | 0.67 | 0 |
| Sonnet 5.5 | 1,803 | 5.46 | 4.84 | 18.0 | 6.5 | 0.62 | 0 |
| Opus 5.5 (spot check) | 1,803 | 4.57 | 3.91 | 14.3 | 10.0 | 0.66 | 0 |

- **deepseek's 245 runaways** run to the 16,384-token cap on whitespace. They are its only invalid answers, so 15,019
  of its 15,264 chunks have an answer. Opus 5.5 had 2 answers stopped by Anthropic's content filter.
- **Top 10 junk names.**
  - deepseek: TechCrunch 71, 2023 70, 2024 42, 2022 37, The Verge 33, WIRED 31, Polygon 27, Engadget 26,
    November 23, 1989 21.
  - Haiku 5.5: 2023 101, TechCrunch 74, 2021 64, 2022 62, WIRED 59, 2024 50, 2019 37, 2020 37, The Verge 33, 2018 32.
  - Sonnet 5.5: 2023 106, TechCrunch 74, WIRED 65, 2022 59, 2021 57, 2024 56, 2019 44, 2020 39, 2018 38,
    The Verge 36.
- **Graph side tables** in `data/lancedb-eval`, built by `import_graph_extractions` (346 documents; recomputed chunks
  equal the store's `nodes`, chunk for chunk):

  | Set | Entities | Entity edges |
  |---|---|---|
  | `s3m_deepseek` | 25,955 | 45,333 |
  | `s3m_haiku` | 32,935 | 65,881 |
  | `s3m_sonnet` | 35,272 | 68,830 |

  The store's own graph has 27,855 entities. Every file of the store's existing tables, and its manifest, has the
  same name, size and modification time before and after the imports.

### Predictions

1. **deepseek repeats S1: fails.** deepseek's delta is +1.7, not below 0.
2. **Fewer junk entities: fails for every writer.** Each Claude writer extracts more dates per 1,000 entities than
   deepseek (Opus 5.5 is the exception, 14.3 against 14.8). Dates and publishers together are also higher:
   - grid: Haiku 28.7 and Sonnet 26.8 against deepseek 20.8;
   - pilot chunks: Haiku 28.2, Sonnet 24.5 and Opus 24.3 against deepseek 20.0.
3. **The writer does not explain the loss: fails, at the boundary.** Both Claude deltas are below 0, but exactly 5
   points from deepseek's, not within 5.

### Runs and counts

- **Run directories** `eval/runs/2026-11-01-s3m-<run>-multihop_rag_s3m_dev`, all on the v1.0 store at generation
  `lance-703`:
  - `ref1`, `ref2`: engine `LANCET_ENV=eval`, no `graph_table_set` line.
  - `deepseek1`, `deepseek2`: engine `LANCET_ENV=eval-s3m-deepseek`, which logs `graph_table_set="s3m_deepseek"`.
  - `haiku1`, `haiku2`: `eval-s3m-haiku`, `graph_table_set="s3m_haiku"`.
  - `sonnet1`, `sonnet2`: `eval-s3m-sonnet`, `graph_table_set="s3m_sonnet"`.

  The gateway and the harness ran with `LANCET_ENV=eval`. Each stack's preflight passed before its drive.
- **Counts.** Each run holds 100 records of its one arm. 3 of the 800 are `error`: ref2, deepseek2 and sonnet1 each
  have one empty answer on `mhr-dd03ecc9ba3d` after 2 retries. That question's arm score is then the mean of its one
  success, and it still pairs.
- **Graph use.** As in S1's run, every record of both arms reports `degraded_mode`. The graph arm draws graph facts
  into the prompt: 2.70 per answer in Haiku's first run, against 2.44 in S1's small graph arm.
- **Sonnet's first import** stopped at about document 300 of 346 on a Lance decoding assertion
  (`lance-encoding` `primitive.rs:305`). It was dropped with `--replace` and imported again in full. Haiku's and
  deepseek's imports ran once each.

### Spend

| Item | Claude credit | OpenRouter |
|---|---|---|
| Haiku 5.5 extraction | $1.43 | – |
| Sonnet 5.5 extraction | $29.14 | – |
| Opus 5.5 extraction | $7.21 | – |
| Canaries | about $0.01 | – |
| deepseek extraction (from usage) | – | $2.03 |
| 8 drives (observed, smoke drive included) | – | $0.82 |
| Entity-name embeddings and 4 preflights | – | a few cents |
| **Total** | **about $37.8** (ceiling $45) | **about $2.85** (ceiling raised to $3.50 by the coordinator) |

The OpenRouter balance moved from $19.79 to $18.99 over the imports and drives.
