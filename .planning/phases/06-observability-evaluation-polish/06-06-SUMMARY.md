# Phase 6 Plan 06-06 Execution Summary

## Overview

Plan 06-06 established the test infrastructure foundation required for subsequent wire-contract (06-07) and behavior (06-08 through 06-11) plans:
1. Created `engine::testkit` to provide single-source-of-truth `cfg(test)` constructors for `QueryRagRequest` and `Notice` protobuf messages, migrating all 81 exhaustive request literals and 13 test-side notice literals across the Rust test tree.
2. Extended the `cfg(test)` fake-port seam in `engine/src/workflow/ports.rs` and `engine/src/generation/mod.rs` with the four D-83 failure modes (error, timeout/stall, empty, and malformed citations).
3. Asserted exact top-level and element JSON key sets on the Go side (`gateway/main_test.go`) for `/rag/query` SSE payloads (`final_answer` and `workflow_completed`), making any future added or altered wire fields immediately test-visible.

---

## Tasks Completed

| Task | Description | Status | Commits |
|------|-------------|--------|---------|
| 1 | Create `engine::testkit` and migrate exhaustive request & notice literals | Completed | `f5aa5fd` |
| 2 | Extend `cfg(test)` fake-port seam with D-83 failure modes | Completed | `b01fa5b` |
| 3 | Assert exact SSE payload key sets on Go side | Completed | `26ff970`, `3604141` |

---

## Metric & Count Validations

### 1. Protobuf Message Struct Literal Migration (Rust)

| File | Pre-Plan `QueryRagRequest {` | Post-Plan `QueryRagRequest {` | Pre-Plan `Notice {` | Post-Plan `Notice {` |
|------|-----------------------------|------------------------------|---------------------|----------------------|
| `engine/src/tests.rs` | 32 | 0 | 0 | 0 |
| `engine/src/tests/workflow_phase5.rs` | 37 | 0 | 13 | 0 |
| `engine/src/tests/workflow_phase5_production.rs` | 11 | 0 | 0 | 0 |
| `engine/src/retrieval/tests.rs` | 1 | 0 | 0 | 0 |
| `engine/src/testkit.rs` | 0 (new) | 1 (constructor) | 0 (new) | 1 (constructor) |
| **Production files** (`workflow/mod.rs`, `events.rs`, `nodes/graph_context.rs`, `nodes/retrieve.rs`) | 0 | 0 | 4 (untouched) | 4 (untouched) |

### 2. D-83 Fake-Port Seam Additions

- **`FakeDenseRetrievalPort`**: Added `empty()`.
- **`FakeBm25RetrievalPort`**: Added `empty()`.
- **`FakeGraphQueryPort`**: Added `empty()`, `failure_with_retryable(bool)`.
- **`FakeReranker`**: Added `stall()`.
- **`FakeGenerator`**: Added `stall()`, `malformed_citation_near_miss()`, `malformed_citation_unresolvable()`.
- Source-text guard invariant preserved: `#[cfg(test)]\npub struct FakeGenerator` structure remained unmoved.

### 3. Go SSE Exact Key Set Assertions

Pinned pre-06-07 key sets:
- **`final_answer` top-level**: `["answer", "answer_basis", "citations", "notices", "session_id", "snapshot", "structured_citations"]`
- **`structured_citations` elements**: `["chunk_id", "content_type", "document_id", "excerpt", "is_truncated", "rank", "score", "section_path", "title"]`
- **`snapshot` object**: `["active_filter", "bm25_weight", "candidate_limit", "embedding_model", "final_limit", "index_generation", "result_hash", "rrf_k", "vector_weight"]`
- **`workflow_completed` (final response present)**: `["error_kind", "error_message", "final_response", "success", "total_duration_ms"]`
- **`workflow_completed` (final response nil)**: `["error_kind", "error_message", "notices", "success", "total_duration_ms"]`
- **`notices` elements**: `["code", "message", "severity"]`

#### Proof of Assertion Rigor (Injected Extra Key Check)
When temporarily injecting `"unexpected_extra_key"` into the expected key set for `TestQueryRAG_SSE_FinalAnswerPayloadKeySet`, the test failed with:
```
--- FAIL: TestQueryRAG_SSE_FinalAnswerPayloadKeySet (0.00s)
    main_test.go:2684: assertSSEPayloadKeySet mismatch: got keys [answer answer_basis citations notices session_id snapshot structured_citations], want [answer answer_basis citations notices session_id snapshot structured_citations unexpected_extra_key]; payload: ...
```

---

## Test Target Gate Results

### Rust Target Counts (`scripts/engine-test-targets.sh`)

| Target | Pre-Plan 06-06 | Post-Plan 06-06 | Delta |
|--------|----------------|-----------------|-------|
| `engine (lib)` | 261 | 266 | +5 (2 in `ports.rs`, 3 in `generation/tests.rs`) |
| `engine (bin)` | 0 | 0 | 0 |
| `inspect_lancedb (bin)` | 18 | 18 | 0 |
| `seed_rag_fixture (bin)` | 0 | 0 | 0 |
| `config_startup (test)` | 9 | 9 | 0 |
| **TOTAL** | **288** | **293** | **+5** |

All 7 Rust test target invariants verified successfully.

### Go Target Counts (`scripts/gateway-test-targets.sh`)

| Package | Pre-Plan 06-06 | Post-Plan 06-06 | Delta |
|---------|----------------|-----------------|-------|
| `gateway` | 60 | 62 | +2 (`TestQueryRAG_SSE_FinalAnswerPayloadKeySet`, `TestQueryRAG_SSE_WorkflowCompletedPayloadKeySet`) |
| `gateway/db` | 7 | 7 | 0 |
| `gateway/internal/sse` | 8 | 8 | 0 |
| **TOTAL** | **75** | **77** | **+2** |

Go test target invariants verified successfully.

---

## Verification Summary

1. `cargo build --manifest-path engine/Cargo.toml --release`: Clean release build (no test fakes leaked into release).
2. `cargo clippy --manifest-path engine/Cargo.toml -- -D warnings`: Clean, zero warnings.
3. `cargo test --manifest-path engine/Cargo.toml --locked`: 293 passed.
4. `(cd gateway && go build ./... && go vet ./... && go test ./...)`: Passed with race detector enabled.
5. `bash scripts/engine-test-targets.sh`: Exits 0.
6. `bash scripts/gateway-test-targets.sh`: Exits 0.
