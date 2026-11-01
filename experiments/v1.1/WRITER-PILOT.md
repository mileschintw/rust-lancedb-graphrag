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
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.writer_pilot submit sonnet-5.5
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

Pending the owner's go-ahead on the estimate.
