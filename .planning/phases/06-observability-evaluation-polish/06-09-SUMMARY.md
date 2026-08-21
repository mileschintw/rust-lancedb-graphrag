# Plan 06-09 Summary: Convert Retrieval Paths to Degrade (D-13)

## Overview
Plan 06-09 converted the hybrid retrieval node from a fail-closed architecture to a degrade-and-continue architecture, closing **DEBT-RAG-01** (D-13) and fulfilling Phase 6 Success Criterion 8:
1. Converted the dense retrieval path in `RetrieveHybridNode` so that transport/service errors emit a typed `NoticeCode::RetrievalDegradedDense` notice and yield empty candidates rather than aborting the node.
2. Converted the lexical (BM25) retrieval path in `RetrieveHybridNode` so that errors for any variant emit a typed `NoticeCode::RetrievalDegradedBm25` notice and yield empty candidates for that variant, continuing the variant loop and preserving candidates from succeeding variants.
3. Asserted the deterministic 3-notice ordered sequence `[RETRIEVAL_DEGRADED_DENSE, RETRIEVAL_DEGRADED_BM25, NO_EVIDENCE]` when both paths fail, allowing downstream workflows to complete with machine-readable observability.

---

## 1. Degrade Contracts & Message Templates

### Message Formatting
Errors returned by retrieval ports are converted to notice strings using the following rule:
```rust
let msg = if err.message.is_empty() {
    err.kind
        .as_str_name()
        .trim_start_matches("NODE_ERROR_KIND_")
        .to_string()
} else {
    format!(
        "{}: {}",
        err.kind
            .as_str_name()
            .trim_start_matches("NODE_ERROR_KIND_"),
        err.message
    )
};
```
- **Dense Degrade**: Emits `NoticeCode::RetrievalDegradedDense` (`"RETRIEVAL_DEGRADED_DENSE"`), severity `Info`.
- **Lexical Degrade**: Emits `NoticeCode::RetrievalDegradedBm25` (`"RETRIEVAL_DEGRADED_BM25"`), severity `Info`.

### Cross-Variant Deduplication
- `WorkflowContext::add_notice` de-duplicates notices keyed on `(code, message)`.
- When multiple variants encounter identical BM25 failure kinds and messages, only **one** `RETRIEVAL_DEGRADED_BM25` notice is retained in the workflow context.
- When variants fail with distinct kinds or messages (e.g. `RETRIEVAL_FAILED` on variant 0 vs `TIMEOUT` on variant 1), both notices survive in the final response.

### Both-Paths Degrade Notice Order
When both dense and lexical retrieval fail:
1. `RetrieveHybridNode` executes dense retrieval -> emits `RETRIEVAL_DEGRADED_DENSE`, candidates empty.
2. `RetrieveHybridNode` executes BM25 retrieval -> emits `RETRIEVAL_DEGRADED_BM25`, candidates empty.
3. Candidate fusion produces empty fused candidate list.
4. Zero-evidence check fires -> emits `NO_EVIDENCE`.
5. The ordered notice sequence emitted across the node is strictly:
   `["RETRIEVAL_DEGRADED_DENSE", "RETRIEVAL_DEGRADED_BM25", "NO_EVIDENCE"]`

### Accepted Leftovers
- **Fusion errors remain fatal**: `fuse_candidates` and `fuse_cross_variant_candidates` errors abort the node with `NodeErrorKind::RetrievalFailed`.
- **Reranking errors remain fatal**: `reranker.rerank` errors abort the node with `NodeErrorKind::RetrievalFailed`.
- **Rationale (D-13)**: Fusion and reranking are in-memory deterministic algorithms operating on already-retrieved candidates. Errors at those stages represent code bugs or data corruption invariants rather than external transport/service availability issues.

---

## 2. Pre-Existing Tests Updated

| Test Name | File | Old Assertion | New Assertion (D-13) |
|---|---|---|---|
| `tests::query_rag_fail_closed_dense_snapshot` | `engine/src/tests.rs` | Asserted `execute_query_rag` returned `Err(Status::unavailable)`. | Asserts `execute_query_rag` succeeds with `RETRIEVAL_DEGRADED_DENSE` and `NO_EVIDENCE` notices; `generator.calls() == 0`. |
| `tests::workflow_phase5_production::workflow_phase5_production_reachability` | `engine/src/tests/workflow_phase5_production.rs` | Asserted `fail_terminal.success == false` on dense failure. | Asserts `fail_terminal.success == true` with `RETRIEVAL_DEGRADED_DENSE` notice. |
| `tests::workflow_phase5_production::workflow_phase5_nodekind_dispatch` | `engine/src/tests/workflow_phase5_production.rs` | Used `FailingDensePort` on `RetrieveHybridNode` to test `NodeFailed` retryable flag forwarding. | Updated to use `FailingEmbedder` on `ExtractGraphContextNode` because dense port failures now degrade to notices rather than failing the node. |

---

## 3. Test Target Distribution Changes

### Rust (`scripts/engine-test-targets.sh`)
- `engine (lib)`: **298** tests (was 286; +12 tests: 6 dense degrade tests + 6 lexical/both degrade tests)
- `engine (bin)`: **0** tests (unchanged)
- `inspect_lancedb (bin)`: **18** tests (unchanged)
- `seed_rag_fixture (bin)`: **0** tests (unchanged)
- `config_startup (test)`: **9** tests (unchanged)
- **TOTAL**: **325** tests (was 313; all 7 invariants verified green)

### Go Gateway (`gateway`)
- All gateway tests passing (`go test ./...` exits 0).

---

## 4. Debt and Criteria Closure
- **DEBT-RAG-01**: **CLOSED**. Dense and lexical retrieval paths now degrade gracefully into structured notices rather than failing closed, enabling the workflow to serve answers from surviving retrieval channels.
- **Phase 6 Success Criterion 8**: **CLOSED**.
