# Writer pilot (#117)

An input to the S3 grill, not an experiment of record: S3's pre-registered question is writer vs writer
([PLAN.md](PLAN.md)), and this pilot measures what a Claude writer would cost and extract before the Claude credit
expires on 2026-11-03. It builds no store and runs no query. The **Result** section is filled in after the paid run.

## Method

- **Documents.** 40 of the 346 in `eval/corpora/multihop_rag/documents.subset.jsonl`, drawn with seed 42
  (`writer_pilot.select_documents`). No held-out file is read.
- **Chunks.** The engine's `structure-aware` chunking at the gateway default of 500/50 characters, the v1.0 small
  store S1 kept, ported to Python from `engine/src/chunker/mod.rs`. Chunks the engine does not extract (under 40
  bytes trimmed) are dropped. The 40 documents give **1,803 extractable chunks** (15 to 228 a document, median 31;
  about 250 characters a chunk). They are in [writer-pilot/chunks.jsonl](writer-pilot/chunks.jsonl), and every
  writer gets the same chunks.
- **Request.** The engine's extraction request (`OpenRouterExtractionGenerator::build_request_payload`): its system
  and user messages, the strict `knowledge_graph_extraction` JSON schema, `max_completion_tokens` 16,384 (D-272). A
  test checks the prompt strings and limits against the Rust source.
- **Writers.**

| Writer | Model | Transport | Thinking | Price, $/MTok (in / out) |
|---|---|---|---|---|
| deepseek | `deepseek/deepseek-v4-flash-0731` | sync API, the engine body unchanged, D-271 pin (`wafer/us`, no fallbacks, `max_price`) | `reasoning: {effort: none}` (the engine's) | 0.0448 / 0.30 (D-277), full price |
| Haiku 5.5 | `anthropic/claude-haiku-5.5` | OpenRouter Batch API, BYOK (`provider: {only: ["anthropic"], allow_fallbacks: false}`) | off (`reasoning: {enabled: false}`) | 0.10 / 0.50, half price |
| Sonnet 5.5 | `anthropic/claude-sonnet-5.5` | OpenRouter Batch API, BYOK | on at effort low (`reasoning: {effort: "low"}`) | 2 / 10, half price |

  Each Claude body is the deepseek body rewritten as S2's readers are (`reader_request.rewrite_pack_body`): the slug,
  the BYOK pin, no `temperature` or `top_p`, and the thinking setting. The thinking settings are the lowest each
  model supports (owner ruling, 2026-11-01). Sonnet 5.5's `between_tools` is refused by the Batch API (D-280), so it
  runs at effort low and its reasoning tokens are reported, not required to be 0. A batch holds at most 500 requests,
  the size the S2 readers ran in, so each Claude writer is 4 batches.
- **BYOK.** Every Claude answer must report `is_byok: true` and provider `Anthropic` (D-265; a batch row takes its
  batch's `is_byok`, D-279); every deepseek answer `is_byok: false`. The sync runs stop at the first answer that
  breaks this.

## Running it

From the repo root, with `OPENROUTER_API_KEY` set:

```bash
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot plan                 # free: chunks + estimates
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot canary haiku-5.5     # paid: 1 chunk, sync
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot canary sonnet-5.5
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot submit haiku-5.5     # paid: 4 batches
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot submit sonnet-5.5 --parts 1   # staged: batch 1 first
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot submit sonnet-5.5     # the rest, once batch 1's cost scales under the ceiling
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot deepseek             # paid: 1,803 sync calls
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot fetch haiku-5.5      # free, until finished
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot fetch sonnet-5.5
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot report               # free: summary.json
```

## Estimate (D-258; printed by `plan` before any spend)

Input is counted with o200k (Claude's tokenizer differs, so treat it as a proxy) at about 260 tokens a request,
most of it the schema. Output is assumed at 400 tokens a chunk until deepseek has answered.

| Writer | Expected | If every answer hit 16,384 tokens |
|---|---|---|
| deepseek (OpenRouter credit) | about $0.24 | $8.88 |
| Haiku 5.5 (Claude credit) | about $0.20 | $7.41 |
| Sonnet 5.5 (Claude credit) | about $4.08, plus about $0.90 per 100 reasoning tokens a chunk | $148.17 |
| Canaries (2 sync calls) | under $0.01 | |

## Result

Run on 2026-11-01 after the owner's go-ahead ("Approve, in stages"): the two canaries, Haiku's 4 batches and Sonnet's
first batch, then Sonnet's batches 2 to 4 once batch 1 scaled to $4.27 (under the $15 line the coordinator set), and
deepseek through the sync API. Every request was answered. Batch IDs are in the `*.batch.json` manifests; the figures
are `summary.json` (`writer_pilot report`).

### Routing and thinking

| Writer | Setting sent | Measured reasoning tokens | `is_byok` | Provider |
|---|---|---|---|---|
| deepseek | `reasoning: {effort: none}` | 0 | false on all 1,803 | Wafer |
| Haiku 5.5 | thinking off | 0 | true on all 1,803 (batch level, D-279) | Anthropic |
| Sonnet 5.5 | thinking on, effort low | **0** on all 1,803 | true on all 1,803 (batch level) | Anthropic |

Sonnet 5.5 at effort low reported no reasoning tokens on any of these short chunks, in the batch or in its sync
canary. Both canaries returned schema-valid JSON over BYOK.

### Tokens and cost

Cost is tokens times list price times the transport's share (half on the Batch API, full on the sync API).

| Writer | Input tokens / chunk | Output tokens / chunk | Cost / chunk | Cost / document | Total, 1,803 chunks |
|---|---|---|---|---|---|
| deepseek (sync, OpenRouter credit) | 101 | 439 | $0.000136 | $0.0061 | **$0.245** |
| Haiku 5.5 (batch, Claude credit) | 618 | 324 | $0.000112 | $0.0050 | **$0.202** |
| Sonnet 5.5 (batch, Claude credit) | 619 | 331 | $0.0023 | $0.102 | **$4.10** |

Canaries: about $0.005 on Claude credit. Total spend: about **$4.31 of Claude credit and $0.25 of OpenRouter credit**,
within the $20 and $1 ceilings.

- **Claude bills about 6 times deepseek's input.** The same request is 618 input tokens on Claude and 101 on deepseek's
  endpoint; Claude counts the strict JSON schema (about 370 tokens of structured-output overhead, measured by the
  canaries against the o200k estimate of 278), and deepseek's endpoint bills it as about nothing. At 250 characters a
  chunk the schema dominates every Claude request, so a larger chunk (the merged store's 256 tokens) would cut
  Claude's cost per document.
- **deepseek's whitespace runaways.** 23 of 1,803 deepseek answers (1.3%) ran into whitespace until the 16,384-token
  cap (`finish_reason: length`), which the engine rejects as "EOF while parsing" and retries up to 3 times. Those 23
  answers are 48% of deepseek's output tokens and $0.113 of its $0.245. Neither Claude writer had one. Some of the
  S1 seed's truncations that D-272 met may have been this failure; the higher cap makes each runaway dearer and does
  not stop it.

### Entities and relations

| Writer | Valid answers | Entities / chunk | Relations / chunk | Dangling relations | Date junk | Publisher junk | Entity Jaccard vs deepseek | Relation-pair Jaccard vs deepseek |
|---|---|---|---|---|---|---|---|---|
| deepseek | 1,780 (23 runaways) | 4.24 | 3.39 | 363 | 112 | 39 | | |
| Haiku 5.5 | 1,803 | 5.24 | 4.78 | 238 | 209 | 58 | 0.67 | 0.43 |
| Sonnet 5.5 | 1,803 | 5.46 | 4.84 | **14** | 177 | 64 | 0.62 | 0.38 |

A dangling relation names an end that is not among the answer's entities. Junk is #126's kind: a month, weekday, year
or date, or a name equal to a corpus publisher (`junk_kind`). Jaccard is over normalised entity names, and over
unordered relation end pairs, per chunk.

### Spot-check against deepseek

Five chunks drawn with seed 7 from those deepseek answered normally, read by hand, plus the corpus-wide counts:

- **The three writers agree on the core entities.** On a sports blurb (d044-c059) all three return Roschon Johnson
  plays_for Bears. On a product review (d016-c031) all three list the same product, size, resolution, camera and
  comparison. They differ in naming and granularity: Sonnet adds a parent entity ("Sennheiser soundbar" is_a
  "soundbar") and an organisation (Apple made_by), Haiku and deepseek name the attribute bare.
- **deepseek brings in entities from outside the chunk.** On d013-c008, a Zelda chunk that names only Link and "the
  sequel", deepseek returns "Breath of the Wild" and "Tears of the Kingdom" with a prequel_of relation; Haiku and
  Sonnet keep to "sequel". The ungrounded-name count (an entity name not found in the chunk text: deepseek 259, Haiku
  514, Sonnet 853) does not separate this from paraphrase: most of Sonnet's are canonical forms ("Floyd Mayweather" for
  "Mayweather", "Eero subscription"), so it is not a hallucination rate.
- **Sonnet's graph is the most internally consistent.** 14 dangling relations in 8,727, against 238 for Haiku and 363
  for deepseek: Sonnet nearly always lists both ends of a relation as entities, which the engine's graph needs to join
  an edge to its nodes.
- **No writer avoids #126's junk.** Every writer emits publisher entities (WIRED is the top junk name for all three:
  24, 43 and 49) and dates (years, "November 6, 2023"); the Claude writers emit more of both, in line with their
  larger entity counts. The junk comes from the prompt, which does not exclude dates or sources, so #126's fix
  (prompt or seeding stoplist) is needed whichever writer S3 picks.
- **Abstract chunks.** On an opinion paragraph (d012-c029) Sonnet extracts 13 concept entities ("competitive edge",
  "final product"), Haiku 7 and deepseek 9: Sonnet extracts the most, including generic concepts the prompt calls
  trivial.

### Recommendation for the S3 grill

- **Add Haiku 5.5 as the third writer.** It costs less per chunk than deepseek here ($0.000112 against $0.000136 on
  the Batch API, because deepseek's runaways cost more than Claude's schema overhead), never ran away or broke the
  schema in 1,803 answers, extracts about 25% more entities and 40% more relations, and agrees with deepseek on two
  thirds of entity names. It is the cheapest test of whether a second writer changes the graph.
- **Sonnet 5.5 only if S3 can afford it.** Its one clear gain is relation consistency (14 dangling against 238); its
  entity and relation counts are close to Haiku's at about 20 times the price, and in the five spot-checked chunks
  its extra entities were parent or generic ones ("soundbar", "first down"), not facts Haiku missed.
- **Writer budget for a full store.** The 40 documents are 1,803 chunks; the subset's 346 documents scale to about
  15,600 chunks at the same rate (documents vary from 15 to 228 chunks, so this is rough). One full extraction:
  deepseek about $2.1 (sync, OpenRouter), Haiku 5.5 about $1.7 on the Batch API ($3.5 at sync list price), Sonnet
  5.5 about $35 on the Batch API ($71 sync). The Claude credit expires on 2026-11-03, so an S3 Claude store built
  later is paid at these prices from new money. A budget of about $5 a store covers Haiku with margin; Sonnet needs
  about $40.
- **Fix the runaways and the junk before S3 compares writers.** deepseek's runaways lose 1.3% of chunks to a failed
  extraction (and three billed retries each in the engine); #126's junk appears for every writer. Both bias a
  writer-vs-writer comparison if left in.
