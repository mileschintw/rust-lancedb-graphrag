# Quick Task Summary: 260831-az7 — Paid Model Migration and Eval Reseed Execution

**Date:** 2026-08-31  
**Task ID:** 260831-az7  
**Status:** Executed & Verified (Phase 6.3 Reseed In Progress)

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

## 5. Corpus Reseed Status (Task 3)

- **Engine & Gateway**: Running in LANCET_ENV=eval mode with isolated lancet_eval PostgreSQL schema and ./data/lancedb-eval LanceDB directory.
- **Reseed Execution**: Running via uv run --project eval lancet-eval reseed --corpus multihop_rag --confirm.
- **Live Performance**: Chunks and documents are completing steadily with 0 rate limit errors and high extraction accuracy. Incremental mapping writes to eval/corpora/multihop_rag/document_map.json upon each completed document.
