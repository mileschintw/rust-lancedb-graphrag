---
phase: 03-hybrid-retrieval-basic-rag-path
plan: "17"
subsystem: retrieval
tags: [rust, go, fail-closed, embedding, dense-retrieval, metadata]

requires:
  - phase: 03-hybrid-retrieval-basic-rag-path
    provides: 03-16 GroundingLimits and service-safe ceiling validation
provides:
  - Fail-closed embedding transport and payload error classification with exact tonic status
  - DenseRetriever error propagation for Snapshot and internal failure classes
  - Preserved session_id, correlation_id, and error_kind trailers across engine and gateway
  - Generation-skip test regressions for all D1 retrieval infrastructure failure modes
affects:
  - phase 03 gap closure

tech-stack:
  added: []
  patterns:
    - Early correlation UUID allocation ensuring all failure paths preserve request identity
    - Fail-closed retrieval mapping skipping generator call on any infrastructure failure
    - Gateway HTTP 502 Bad Gateway mapping preserving X-Lancet identity headers

key-files:
  created:
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-17-SUMMARY.md
  modified:
    - engine/src/main.rs
    - engine/src/tests.rs
    - gateway/main_test.go

key-decisions:
  - "Embedding transport errors map to tonic Unavailable with error_kind embedding_transport"
  - "Invalid embedding payload (empty, multi-vector, wrong-dimension, non-finite) maps to tonic Internal with error_kind embedding_invalid_payload"
  - "DenseRetriever snapshot errors map to tonic Unavailable with error_kind dense_retrieval"
  - "Every retrieval failure preserves session ID, correlation UUID, and error kind trailers while bypassing generation"

patterns-established:
  - "d1_status helper attaches x-lancet-* metadata and emits safe structured log without sensitive payloads"

requirements-completed: [RAG-02]

coverage:
  - id: D1-embedding-transport
    description: "Embedding transport failure returns Unavailable with embedding_transport identity and leaves generator call count at zero"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_fail_closed_embedding_transport"
        status: pass
  - id: D1-embedding-payload
    description: "Empty, multi-vector, wrong-dimension, and non-finite embedding payloads map to Internal with embedding_invalid_payload identity and skip generation"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_fail_closed_embedding_empty_payload"
        status: pass
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_fail_closed_embedding_multi_vector"
        status: pass
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_fail_closed_embedding_wrong_dimension"
        status: pass
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_fail_closed_embedding_non_finite"
        status: pass
  - id: D1-dense-retrieval
    description: "DenseRetriever failure maps to Unavailable with dense_retrieval identity and skips generation"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_fail_closed_dense_snapshot"
        status: pass
  - id: D1-gateway-propagation
    description: "Gateway translates D1 retrieval status failures into HTTP 502 Bad Gateway while copying X-Lancet headers"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "gateway/main_test.go#TestRAGQueryEmbeddingTransportIdentity"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestRAGQueryEmbeddingInvalidPayloadIdentity"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestRAGQueryDenseRetrievalIdentity"
        status: pass

duration: 20min
completed: 2026-08-04
status: complete
---

# Phase 03 Plan 17: Fail-Closed Embedding and Dense Retrieval Infrastructure Summary

**Implementation of ADR-03-001 decision D1 ensuring embedding and dense retrieval infrastructure failures fail closed with exact status classes, preserved identity metadata, and zero generator invocations.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-08-04T21:37:00Z
- **Completed:** 2026-08-04T21:40:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Implemented `d1_status` helper in `engine/src/main.rs` to attach `x-lancet-session-id`, `x-lancet-correlation-id`, and `x-lancet-error-kind` metadata and structured warning logs.
- Allocated `correlation_id` early in `query_rag` so all retrieval failure paths carry matching correlation identity.
- Mapped `EmbeddingProvider` transport failures to `Unavailable` (`embedding_transport`) and invalid payload classes to `Internal` (`embedding_invalid_payload`), skipping generation without vector substitution.
- Propagated `DenseRetriever` snapshot errors as `Unavailable` (`dense_retrieval`), distinguishing retrieval errors from valid empty candidate sets.
- Added 6 focused Rust service tests in `engine/src/tests.rs` proving generation call counts remain 0 and identity metadata is preserved.
- Added 3 Go gateway tests in `gateway/main_test.go` asserting HTTP 502 translation and `X-Lancet-*` header propagation.

## Task Commits

1. **Task 1: Trace retrieval infrastructure failure to fail-closed tonic status** - `feat(03-17): implement D1 fail-closed retrieval status mapping and Rust test coverage`
2. **Task 2: Verify gateway propagation of retrieval failure identity** - `test(03-17): add Go gateway D1 retrieval identity header regression tests`

## Files Created/Modified
- `engine/src/main.rs` - Added `d1_status` helper, early correlation UUID generation, and fail-closed embedding/dense error handling in `query_rag`
- `engine/src/tests.rs` - Added `FailingEmbedder`, `PayloadEmbedder`, and 6 `query_rag_fail_closed_*` test cases
- `gateway/main_test.go` - Added `TestRAGQueryEmbeddingTransportIdentity`, `TestRAGQueryEmbeddingInvalidPayloadIdentity`, and `TestRAGQueryDenseRetrievalIdentity`

## Decisions Made
- Correlation UUID is assigned immediately after session ID validation so all failure paths bear full tracing identity.
- Valid empty dense query results (`Ok(vec![])`) remain legitimate inputs for search fusion, while database infrastructure failures fail closed.

## Deviations from Plan
None - plan executed as specified.

## Issues Encountered
None - all unit and gateway tests passed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 03-17 complete and committed. Proceed to Plan 03-18.
