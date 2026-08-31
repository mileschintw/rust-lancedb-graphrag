# Quick Task 260831-az7: phase 6.3 is currently stuck, the previous config with all free model from openrouter is unsufficient and so we need to find a new setup that can run cost-efficiently yet still with good performance for refresh all dataset and do this before plan continue. - Context

**Gathered:** 2026-08-31
**Status:** Ready for planning

<domain>
## Task Boundary

Phase 6.3 (Python Evaluation Harness, Benchmark Corpora, and Recorded Run) is paused at Plan 06.3-10 Task 1 (Corpus Seeding), stalled at 6/346 documents because the engine and eval config are pinned to `:free`-suffixed OpenRouter models (embedding, generation, and judge), which are rate-limited independent of account credit. This task replaces those three model pins with a cost-efficient, working paid-tier setup, verifies the change empirically, and unblocks the full 346-document reseed so Plan 06.3-10 can resume. Full handover/root-cause doc: `.planning/phases/06.3-python-evaluation-harness-benchmark-corpora-and-recorded-run/06.3-HANDOVER.md`.

</domain>

<decisions>
## Implementation Decisions

### Root blocker (discovered during discussion, not in the handover doc)
- The stall is **not purely a `:free` model-name problem**. The project's `OPENROUTER_API_KEY` itself has a hard **$0/day spend limit** configured at the key level (`GET /api/v1/key` → `limit: 0, limit_reset: "daily"`), independent of account balance. Paid-model calls 403'd with "Key limit exceeded (daily limit)" even after picking paid models; `:free` calls "worked" only because they cost $0.
- User raised the key's daily limit to $5/day via the OpenRouter dashboard during this discussion (confirmed empirically: `limit: 5, limit_remaining: 5`). This must stay raised (or be raised again if it resets/lapses) for the plan's paid-model calls to succeed — planner/executor should not assume this is a one-time fix if the key or limit changes again.

### Model selection
- **Embedding:** `voyageai/voyage-4-large`. Chosen over `openai/text-embedding-3-large` and `perplexity/pplx-embed-v1-4b` (both also empirically confirmed capable of 2048-dim output) because Voyage's retrieval-quality track record (MTEB retrieval leaderboards) is the strongest of the three for this specific RAG/retrieval eval use case, and the ~$0.10/M price gap across the three options is a rounding error at this corpus's token volume (~1M tokens). `openai/text-embedding-3-small` is **disqualified** — its dimension ceiling is 1536, empirically confirmed unable to reach 2048 (`HTTP 400: Invalid value for 'dimensions' = 2048. Must be less than or equal to 1536`).
  - **Critical technical requirement, confirmed empirically, not assumed:** `voyageai/voyage-4-large` defaults to **1024 dims** when no `dimensions` param is sent (tested live). The engine hardcodes `EMBEDDING_DIMENSION = 2048` in three places (`engine/src/client/mod.rs:9`, `engine/src/db/mod.rs:6`, and validated again in `engine/src/ingest.rs:609-610`). The current `EmbeddingRequest` struct in `engine/src/client/mod.rs` only sends `model` and `input` — it does **not** send a `dimensions` field. **The plan must add an explicit `"dimensions": 2048` field to the OpenRouter embedding request** (confirmed empirically: passing `dimensions: 2048` to `voyageai/voyage-4-large` returns exactly 2048-dim vectors). This is a small additive Rust code change, not just a config value — it is required regardless of which of the three working embedding models is chosen, since none of them default to 2048 except the current free nvidia model being replaced.
- **Generation:** `deepseek/deepseek-v4-flash-0731`. Cheaper than both `openai/gpt-4o-mini` (the engine's Rust default) and `google/gemini-2.5-flash-lite` at $0.065/M prompt + $0.18/M completion, 1.31M context, supports `structured_outputs`/`response_format`/`tool_choice`. Note: the handover doc's original suggestion (`google/gemini-2.0-flash-001`) **no longer exists in OpenRouter's catalog** — confirmed absent from a live `/api/v1/models` pull. Risk carried forward: this model is untested against this codebase's strict citation-marker grounding validator (`engine/src/generation`); same category of first-run risk any non-`gpt-4o-mini` pick would carry.
- **Judge:** `meta-llama/llama-3.3-70b-instruct` (paid). Direct non-`:free` equivalent of the currently-configured judge model, keeping the judge on a distinct model family from generation per `eval/README.md`'s explicit design intent ("pinned distinctly from the engine's generation model"). $0.71/M prompt+completion.

### Scope: three files pin `:free` models, not two
- The handover doc's Option A table only discussed embedding + generation. Discussion surfaced a **third** file/spot: `eval/corpora/multihop_rag.toml` and `eval/corpora/graphrag_bench.toml` both set `judge_model = "meta-llama/llama-3.3-70b-instruct:free"`, and `eval/src/lancet_eval/cli.py:689` has the same free judge model hardcoded as a CLI default. All three (`config/config.toml` for embedding+generation, both corpus TOML files, and the `cli.py` default) need updating, not just `config/config.toml`.

### Corpus scope and sequencing
- Full 346-document reseed now (not a reduced sample) — matches Plan 06.3-10 Task 1's original scope.
- No data migration path needed: seeding is already stalled at 6/346, so a full clean wipe-and-reseed (`lancet-eval reseed --corpus multihop_rag --confirm`) is fine.
- **Verification order matters:** the plan must verify the embedding dimension change works (a single test embedding call, confirming 2048-dim output) *before* kicking off the full 346-document reseed — this was already done manually during discussion (see above), but the plan/executor should re-verify against the actual engine code path (not just a raw curl test) before committing to the full run, since the raw API behavior and the engine's actual request-construction code are two different things until the code change lands.

### Guardrail scope
- **Config swap only.** Do not add a guardrail/check to prevent `:free` models from being re-selected in the future — keep this task scoped to unblocking Phase 6.3, not hardening the config surface.

### Claude's Discretion
- Exact retry/backoff tuning for the new paid-tier models (existing `MAX_RETRIES`/`INITIAL_BACKOFF` constants in `engine/src/client/mod.rs` were tuned for free-tier rate-limit conditions and may warrant review, though this wasn't discussed explicitly).
- Whether `eval/src/lancet_eval/config.py:72`'s Pydantic default (`judge_model: str = "openai/gpt-4o-mini"`) needs touching — it's already a paid model and isn't the one actually driving eval runs (the TOML files and `cli.py` override it), so likely no change needed, but worth a quick check during planning.

</decisions>

<specifics>
## Specific Ideas

Empirical test results from this discussion (live OpenRouter API calls, not documentation guesses):

```
nvidia/llama-nemotron-embed-vl-1b-v2:free  -> 2048 dims (native, current free model, confirms why 6 docs already ingested fine)
voyageai/voyage-4-large                     -> 1024 dims default, 2048 with explicit "dimensions":2048 param
openai/text-embedding-3-large               -> 3072 dims default, 2048 with explicit "dimensions":2048 param
openai/text-embedding-3-small               -> 1536 dims default, REJECTS dimensions:2048 (ceiling is 1536)
perplexity/pplx-embed-v1-4b                 -> 2560 dims default, 2048 with explicit "dimensions":2048 param
```

API key limit check (`GET https://openrouter.ai/api/v1/key`) before/after the user's dashboard fix:
```
before: limit: 0, limit_reset: "daily", limit_remaining: 0   <- root cause of all paid-model 403s
after:  limit: 5, limit_remaining: 5                          <- user fixed via dashboard
```

</specifics>

<canonical_refs>
## Canonical References

- `.planning/phases/06.3-python-evaluation-harness-benchmark-corpora-and-recorded-run/06.3-HANDOVER.md` — prior session's root-cause writeup and Option A/B/C proposal (superseded in part by this discussion's empirical findings, particularly the API key limit and the actual default embedding dimensions).
- `eval/README.md` (line ~90) — states the judge model must be "pinned distinctly from the engine's generation model."
- `engine/src/client/mod.rs`, `engine/src/db/mod.rs`, `engine/src/ingest.rs` — the three sites enforcing `EMBEDDING_DIMENSION = 2048`.
- OpenRouter embeddings API reference (live-tested during this discussion, not just read): confirms `dimensions` is a real, working request parameter despite some doc pages and per-model `supported_parameters` metadata not listing it.

</canonical_refs>
