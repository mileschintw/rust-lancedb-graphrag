---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 20
subsystem: client
tags: [openrouter, limits, streaming, security]
requires:
  - RAG-02
  - RAG-04
provides:
  - Shared MAX_PROVIDER_RESPONSE_BODY_BYTES 256 KiB streaming reader policy
  - Bounded response parsing for chat, model-metadata, and embeddings
affects:
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
  - engine/src/generation/openrouter.rs
  - engine/src/generation/tests.rs
tech-stack:
  added: []
  patterns: [bounded-streaming-body-reader]
key-files:
  created: []
  modified:
    - engine/src/client/mod.rs
    - engine/src/client/tests.rs
    - engine/src/generation/openrouter.rs
    - engine/src/generation/tests.rs
key-decisions:
  - "Enforce a single 256 KiB MAX_PROVIDER_RESPONSE_BODY_BYTES ceiling across chat, model metadata, and embeddings."
  - "Reject responses early via Content-Length or streaming byte accumulation before JSON deserialization."
requirements-completed:
  - RAG-02
  - RAG-04
duration: 15 min
completed: 2026-08-05
coverage:
  - deliverable: Shared 256 KiB streaming body reader for all provider endpoints
    verification:
      kind: test
      ref: engine/src/client/tests.rs#bounded_provider_body_accepts_exact_limit
      status: pass
    human_judgment: false
---

# Phase 03 Plan 20: Bounded Streaming Provider Body Summary

OpenRouter chat, model metadata, and embedding response paths now share a single 256 KiB `MAX_PROVIDER_RESPONSE_BODY_BYTES` streaming reader policy under ADR-03-002 (P24-BODY).

## Key Changes

1. **Shared Bounded Streaming Reader**:
   - Added `MAX_PROVIDER_RESPONSE_BODY_BYTES = 256 * 1024` and `BoundedBodyError` in `engine/src/client/mod.rs`.
   - `read_body_limited` checks `Content-Length` before reading and streams chunks up to 262144 bytes max before returning `BoundedBodyError::TooLarge`.
   - `OpenRouterGenerator::check_supported_parameters` (model metadata), `OpenRouterGenerator::execute_one_call` (chat completions), and `OpenRouterClient::send_embedding` (embeddings) all route through `read_body_limited`.

2. **Automated Regressions**:
   - Added `bounded_provider_body_accepts_exact_limit`, `bounded_provider_body_rejects_chunked_limit_plus_one`, and `embedding_client_rejects_oversized_streaming_body` in `client/tests.rs`.
   - Added `openrouter_chat_rejects_oversized_streaming_body` and `openrouter_metadata_rejects_oversized_streaming_body` in `generation/tests.rs`.

## Verification

- `cargo test --manifest-path engine/Cargo.toml --locked bounded_provider_body` passed.
- `cargo test --manifest-path engine/Cargo.toml --locked oversized_streaming_body` passed.

## Self-Check: PASSED
