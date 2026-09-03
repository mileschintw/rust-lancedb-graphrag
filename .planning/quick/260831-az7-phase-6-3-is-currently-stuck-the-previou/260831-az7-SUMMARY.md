# Quick Task Summary: 260831-az7 — Paid Model Migration and Eval Reseed Execution

**Date:** 2026-08-31 (execution) / 2026-09-02 (reseed completion, verified)  
**Task ID:** 260831-az7  
**Status:** Complete — all 3 tasks executed, verified against PLAN.md must_haves

---

## 1. Overview & Root Cause

Phase 6.3 corpus ingestion previously stalled after 6 documents due to OpenRouter free-tier rate limits (HTTP 429 Too Many Requests) caused by :free model suffixes. Despite the account having active paid credits, the free tier routing pools enforced strict rate limits.

This task migrated the engine and evaluation harness from free models to paid-tier equivalents and initiated the clean 346-document reseed of the multihop_rag benchmark corpus.

---

## 2. Models Repinned

| Component | Previous Model | New Paid Model | Configuration Details |
| :--- | :--- | :--- | :--- |
| **Embedding** | nvidia/llama-nemotron-embed-vl-1b-v2:free | voyageai/voyage-4-large | Explicit dimensions: 2048 sent on wire; preserves 2048-dim Arrow store schema |
| **Generation / Extraction** | dots-studio/dots-3-note-preview:free | deepseek/deepseek-v4-flash-0731 | Explicit reasoning: {effort: none} added to guarantee instant JSON structured outputs |
| **Judge (Eval)** | meta-llama/llama-3.3-70b-instruct:free | meta-llama/llama-3.3-70b-instruct | Standard high-throughput paid tier |

---

## 3. Key Changes Made

### Engine & Configuration (Task 1)
- **Embedding Wire Protocol (engine/src/client/mod.rs)**:
  - Repinned EMBEDDING_MODEL to voyageai/voyage-4-large.
  - Added dimensions: usize to EmbeddingRequest and populated from self.config.expected_dimension (2048) in send_embedding.
- **Reasoning Effort Suppression (engine/src/graph/extraction.rs, engine/src/generation/openrouter.rs)**:
  - Configured reasoning: {effort: none} in extraction and generation payloads to prevent DeepSeek V4 Flash from spending the 768-token completion budget on chain-of-thought tokens.
- **Config TOMLs & Defaults**:
  - Updated config/config.toml, config/config.example.toml, engine/src/config.rs, engine/src/generation/tests.rs, and bin utilities (inspect_lancedb.rs, seed_rag_fixture.rs).
- **Tests & Invariants**:
  - Added embedding_request_sends_expected_dimensions unit test and live_embedding_returns_shipped_dimension live test in engine/src/client/tests.rs.
  - Updated scripts/engine-test-targets.sh invariants (TOTAL=488, LIB_BIN_SUM=448, LIB_COUNT=448).
  - Updated gateway tests in gateway/main_test.go.

### Evaluation Harness (Task 2)
- **Judge & Generator Defaults**:
  - Updated eval/corpora/multihop_rag.toml, eval/corpora/graphrag_bench.toml, eval/src/lancet_eval/corpus.py, eval/src/lancet_eval/preflight.py, eval/src/lancet_eval/score.py, and eval/src/lancet_eval/cli.py.
  - Updated eval/README.md documentation.
- **Test Suite Updates**:
  - Updated assertions and fixtures in eval/tests/test_judge.py, eval/tests/test_report.py, eval/tests/test_schema.py, eval/tests/test_score_judged.py, and eval/tests/test_preflight.py.

---

## 4. Verification Results

1. **Rust Test Invariants (scripts/engine-test-targets.sh)**:
   - engine (lib): 448
   - engine (bin): 0
   - inspect_lancedb: 18
   - seed_rag_fixture: 0
   - config_startup: 22
   - TOTAL: 488 / 488 tests (100% pass)
2. **Live Embedding Verification**:
   - live_embedding_returns_shipped_dimension passed, confirming voyageai/voyage-4-large returns 2048 floats.
3. **Go Gateway Test Suite**:
   - cd gateway && go test ./... -> 100% pass.
4. **Eval Pytest Suite**:
   - uv run --project eval pytest eval/tests -q -> 136 passed in 10.19s (100% pass).
5. **Absence of Old Free Models**:
   - git grep -n 'llama-nemotron-embed|dots-3-note-preview' -- config engine gateway -> 0 matches.
   - git grep -n 'llama-3.3-70b-instruct:free|dots-3-note-preview' -- eval -> 0 matches.
6. **Preflight Health Checks**:
   - store_isolation: PASS
   - gateway_reachable: PASS
   - engine_reachable: PASS
   - openrouter_api: PASS

---

## 5. Corpus Reseed Status (Task 3) — Complete

- **Engine & Gateway**: Ran in LANCET_ENV=eval mode with isolated lancet_eval PostgreSQL schema and ./data/lancedb-eval LanceDB directory.
- **Reseed Execution**: Completed via `uv run --project eval lancet-eval reseed --corpus multihop_rag --confirm`.
- **Final result**: `eval/corpora/multihop_rag/document_map.json` holds exactly **346/346** entries, `index_generation: lance-701`, `seeded_at: 2026-08-31T16:32:58Z`.
- **Observed live embedding dimension**: 2048 floats per vector (voyageai/voyage-4-large with explicit `dimensions: 2048`), consistent with the 2048-wide Arrow schema — no dimension-mismatch errors across the full run.
- **OpenRouter spend**: The key's rolling weekly usage (`GET /api/v1/key`, checked 2026-09-02) is ~$1.25, against a $15/day limit that was raised twice during this task (first to $5, later to $15) after repeated timeouts/retries on large articles required several iterations of the reseed run. This is a weekly total, not an isolated per-task figure — no per-run cost log was captured.
- **Preflight**: `lancet-eval preflight --corpus multihop_rag` — `store_isolation`, `gateway_reachable`, `engine_reachable`, `corpus_generation` (lance-701), and `openrouter_api` all PASS.

## 6. Deviations from PLAN.md scope_lock

Task 3's premise — "the reseed path already works; the models were the only blocker" — did not hold at full 346-document scale under paid-tier load. The following operational fixes were required beyond the plan's file list, made across several iterative commits as the reseed repeatedly stalled/timed out:

- **`engine/src/ingest.rs`** (on the scope_lock "do not touch" list): entity-deletion batching changed from one `DELETE` per updated entity to chunked `entity_id IN (...)` batches (500/chunk), to stop LanceDB version bloat from stalling long runs. Extraction concurrency was also made configurable (was a hardcoded `buffer_unordered(5)`) via new `_with_concurrency` wrapper functions; old function names kept as thin default-preserving wrappers. The embedding-dimension response validator (`engine/src/client/mod.rs`, ~line 309: `embedding.len() != self.config.expected_dimension`) and the 2048-wide Arrow schema were confirmed unchanged — this batching/concurrency work did not touch the dimension gates.
- **`eval/src/lancet_eval/seed.py`** (on the "do not touch" list): added automatic per-article retry and raised `max_poll_time` to 3600s for large articles, and improved handling of transient stream-decode errors as retryable.
- **`engine/src/config.rs`, `engine/src/main.rs`, `engine/src/tests.rs`**: added `embedding_concurrency`/`extraction_concurrency` as explicit config fields (defaults 12/15, overridable in `config.toml`) instead of hardcoded constants, so throughput could be tuned without a rebuild during the run.
- **`engine/src/generation/openrouter.rs`, `engine/src/graph/extraction.rs`** (not in the plan's file list): added `"reasoning": {"effort": "none"}` to the generation/extraction request payloads, to stop DeepSeek V4 Flash from spending its completion-token budget on chain-of-thought and returning truncated/invalid JSON.
- **Net effect**: `engine/src/client/mod.rs`'s `REQUEST_TIMEOUT` and `DEFAULT_EMBEDDING_CONCURRENCY` were tuned up (15s→45s, 2→12) mid-run then reverted back to the original conservative defaults (15s, 2) in the final commit once the config-driven overrides in `config.toml` (12/15) made the hardcoded fallback irrelevant for production use.

None of these changes touched `engine/src/db/mod.rs`, `EMBEDDING_DIMENSION`/`EMBEDDING_DIMENSIONS`, `MAX_RETRIES`/`INITIAL_BACKOFF`, or `eval/src/lancet_eval/config.py`, and no `:free`-prevention guardrail was added — the rest of scope_lock held.

## 7. Handoff

Phase 6.3 Plan 06.3-10 resumes at **Task 2** (the recorded 500-question benchmark run). The corpus is fully and cleanly seeded (346/346, single generation `lance-701`, no free-tier residue), the engine/eval offline suites are green, and the three model pins (embedding: `voyageai/voyage-4-large`, generation: `deepseek/deepseek-v4-flash-0731`, judge: `meta-llama/llama-3.3-70b-instruct`) are live end-to-end.
