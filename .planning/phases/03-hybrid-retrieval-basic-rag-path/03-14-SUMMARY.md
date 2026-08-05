---
phase: 03-hybrid-retrieval-basic-rag-path
plan: "14"
subsystem: integration
tags: [rust, go, openrouter, configuration, identity, startup]

requires:
  - phase: 03-hybrid-retrieval-basic-rag-path
    provides: 03-13 fail-closed grounding and OpenRouter output bounds
provides:
  - OpenRouter adapter wired to validated EffectiveRagSettings evidence budget and max completion tokens
  - Identity-preserving generation error mapping carrying session, correlation UUID, and error-kind trailers to public Go HTTP headers
  - Fail-closed startup credential validation rejecting missing or blank OPENROUTER_API_KEY
affects:
  - 03-15 deterministic test doubles and locked phase gate

tech-stack:
  added: []
  patterns:
    - Effective Rag Settings evidence budget propagation to provider prompt packing
    - gRPC metadata trailer mapping to public HTTP headers for request identity and error classification

key-files:
  created: []
  modified:
    - engine/src/generation/openrouter.rs
    - engine/src/generation/tests.rs
    - engine/src/main.rs
    - engine/src/tests.rs
    - engine/tests/config_startup.rs
    - gateway/main.go
    - gateway/main_test.go

key-decisions:
  - "OpenRouter prompt packing and completion bounds consume EffectiveRagSettings evidence_token_budget and max_output_tokens"
  - "Generation errors generate a correlation UUID attached to gRPC trailer metadata alongside session_id and error_kind"
  - "Gateway copies gRPC trailers x-lancet-session-id, x-lancet-correlation-id, and x-lancet-error-kind to X-Lancet-* HTTP headers while preserving HTTP 502/400"
  - "Startup fails closed if OPENROUTER_API_KEY is missing, empty, or whitespace-only"

patterns-established:
  - "Trailer-based identity context propagation: error responses map tracing context from engine gRPC trailers to gateway HTTP headers without leaking prompt/credential payloads"

requirements-completed: [RAG-02]

coverage:
  - id: D1
    description: "Production OpenRouter adapter consumes validated EffectiveRagSettings evidence token budget"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/generation/tests.rs#generation_request_uses_effective_settings"
        status: pass
    human_judgment: false
  - id: D2
    description: "QueryRAG generation errors attach session ID, correlation UUID, and error kind trailers"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_generation_error_preserves_identity"
        status: pass
    human_judgment: false
  - id: D3
    description: "Go gateway copies session/correlation/error-kind trailers to HTTP response headers"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "gateway/main_test.go#TestRAGQueryProviderErrorPreservesIdentity"
        status: pass
    human_judgment: false
  - id: D4
    description: "Startup refuses readiness when OPENROUTER_API_KEY is missing or blank"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/tests/config_startup.rs#missing_openrouter_api_key_blocks_readiness"
        status: pass
      - kind: unit
        ref: "engine/tests/config_startup.rs#blank_openrouter_api_key_blocks_readiness"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-08-04
status: complete
---

# Phase 03 Plan 14: Effective Settings, Error Metadata, and Startup Credentials Summary

**Production OpenRouter adapter wired to validated effective evidence settings, structured gRPC error identity headers propagated to gateway HTTP response, and fail-closed startup credential validation.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-04T05:06:36Z
- **Completed:** 2026-08-04T05:10:05Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Wired `EffectiveRagSettings.evidence_token_budget` and `max_output_tokens` into `OpenRouterGenerationConfig` and `pack_evidence_prompt`.
- Generated correlation UUID at the `QueryRAG` boundary and attached `x-lancet-session-id`, `x-lancet-correlation-id`, and `x-lancet-error-kind` as trailing gRPC metadata on generation failure.
- Updated Go gateway to capture gRPC trailers and populate `X-Lancet-Session-ID`, `X-Lancet-Correlation-ID`, and `X-Lancet-Error-Kind` HTTP response headers while retaining HTTP 502/400 error status.
- Added strict startup validation for `OPENROUTER_API_KEY` requiring non-empty, non-whitespace keys before readiness.

## Task Commits

1. **Task 1: Route EffectiveRagSettings through the production OpenRouter evidence packer** - `feat(03-14): wire effective evidence budget to OpenRouter adapter`
2. **Task 2: Preserve generation identity and reject fake-key startup** - `feat(03-14): preserve request identity metadata and enforce non-blank API key startup`

## Files Created/Modified
- `engine/src/generation/openrouter.rs` - Added `evidence_token_budget` to config and evidence packing call
- `engine/src/generation/tests.rs` - Updated config constructors in generation unit tests
- `engine/src/main.rs` - Wired effective settings into OpenRouter config, attached error trailers in QueryRAG, and validated OPENROUTER_API_KEY
- `engine/src/tests.rs` - Added `query_rag_generation_error_preserves_identity` test
- `engine/tests/config_startup.rs` - Added `missing_openrouter_api_key_blocks_readiness` and `blank_openrouter_api_key_blocks_readiness`
- `gateway/main.go` - Wrapped gRPC engine calls with `trailerError` and copied trailers to HTTP headers
- `gateway/main_test.go` - Added `TestRAGQueryProviderErrorPreservesIdentity` unit test

## Decisions Made
- `OpenRouterGenerationConfig` takes `evidence_token_budget` and passes it directly to `pack_evidence_prompt`.
- `QueryRAG` generates a correlation UUID on every request to attach to gRPC trailers on failure.
- Gateway copies `x-lancet-*` trailers to `X-Lancet-*` HTTP headers without leaking request/response body payloads.

## Deviations from Plan
None - plan executed as specified.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 03-14 is complete. Ready for Plan 03-15 (deterministic test doubles and locked test suite verification).
