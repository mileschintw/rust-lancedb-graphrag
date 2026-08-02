---
phase: 03-hybrid-retrieval-basic-rag-path
plan: "04"
subsystem: gateway-and-client-boundary
tags: [go, rust, http, grpc, openrouter, rag, client]

# Dependency graph
requires:
  - plan: 03-03
    provides: Complete Rust engine QueryRAG gRPC coordination pipeline and proto types
provides:
  - Public Go HTTP POST /rag/query route forwarding to generated gRPC QueryRAG client
  - Lossless response mapping for answer, session_id, answer_basis, citations, structured_citations, notices, and snapshot
  - Strict Go HTTP request body validation with DisallowUnknownFields and trailing-byte rejection
  - Endpoint-injectable OpenRouterClient embedding constructor (from_env_with_endpoint) for local integration testing
affects: [03-05, Go Gateway, Rust Engine]

# Tech tracking
tech-stack:
  added: [chi, reqwest]
  patterns: [strict JSON boundary validation, gRPC status code to HTTP mapping, endpoint-injectable HTTP client]

key-files:
  created:
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-04-SUMMARY.md
  modified:
    - gateway/main.go
    - gateway/main_test.go
    - engine/src/client/mod.rs
    - engine/src/client/tests.rs
    - engine/src/main.rs
    - config/config.toml
    - config/config.example.toml

key-decisions:
  - "Expose POST /rag/query as a thin Go HTTP boundary validating input strictly and forwarding directly to QueryRAG gRPC client."
  - "Map gRPC InvalidArgument status to HTTP 400 and other upstream errors to HTTP 502 Bad Gateway."
  - "Provide OpenRouterClient::from_env_with_endpoint to allow local test servers to inject mock embedding endpoints without weakening production defaults."

requirements-completed: [RAG-02]

coverage:
  - id: D1
    description: "Go HTTP POST /rag/query route forwarding and contract tests"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "gateway/main_test.go#TestRAGQueryValidMapping"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestRAGQueryCallerSessionAndFilters"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestRAGQueryRejectsUnknownOrTrailingJSON"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestRAGQueryInvalidArgumentStatus"
        status: pass
    human_judgment: false
  - id: D2
    description: "Endpoint-injectable Rust embedding client seam"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/client/tests.rs#client_embedding_endpoint_override"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-08-01
status: complete
---

# Phase 03 Plan 04: Gateway HTTP Route & Embedding Endpoint Seam Summary

**Strict Go HTTP POST /rag/query boundary route and endpoint-injectable Rust embedding client seam**

## Performance

- **Duration:** 20 min
- **Started:** 2026-08-01T20:37:00Z
- **Completed:** 2026-08-01T20:41:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

1. **Go HTTP Route & Contract Mapping (Task 1)**:
   - Added `QueryRAG` to `engine` interface and `grpcEngine` in `gateway/main.go`.
   - Registered `POST /rag/query` on the chi router with strict JSON envelope decoding using `json.Decoder.DisallowUnknownFields` and trailing-content checks.
   - Forwarded `r.Context()`, query, session ID, and filters to `QueryRAG` gRPC client.
   - Mapped `codes.InvalidArgument` to HTTP 400 Bad Request and engine failures to HTTP 502 Bad Gateway.
   - Added unit test cases (`TestRAGQueryValidMapping`, `TestRAGQueryCallerSessionAndFilters`, `TestRAGQueryRejectsUnknownOrTrailingJSON`, `TestRAGQueryInvalidArgumentStatus`) in `gateway/main_test.go`.

2. **Endpoint-Injectable Rust Embedding Client (Task 2)**:
   - Added `from_env_with_endpoint` and `new_with_endpoint` constructors to `OpenRouterClient` in `engine/src/client/mod.rs`.
   - Updated `OpenRouterSettings` and `main()` in `engine/src/main.rs` to pass `settings.openrouter.embedding_endpoint`.
   - Added `embedding_endpoint` configuration entries to `config/config.toml` and `config/config.example.toml`.
   - Added focused unit test `client_embedding_endpoint_override` in `engine/src/client/tests.rs`.
   - Verified cargo test, cargo check, cargo fmt, and go test suites.

## Next Steps

- Proceed to Phase 03 Wave 5 (Plan 03-05: Local cross-runtime integration happy path proof).
