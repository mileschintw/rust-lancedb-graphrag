# Plan 06-08 Summary: Make Graph Absence Observable

## Overview
Plan 06-08 made graph absence observable across the entire Lancet workflow pipeline, closing **DEBT-RAG-06** and fulfilling Phase 6 Success Criterion 7:
1. Implemented the `disable_graph_context` request admission flag on `WorkflowContext` and added an early return in `ExtractGraphContextNode` emitting `NoticeCode::GraphAblation` (`"GRAPH_ABLATION"`).
2. Instrumented the two previously silent graph degradation branches in `ExtractGraphContextNode` (`facts.is_empty()` and unconfigured graph port) with distinct informational `NoticeCode::GraphUnavailable` notices (`"GRAPH_UNAVAILABLE"`), while leaving existing timeout and degraded failure branch behavior byte-for-byte unchanged.
3. Added end-to-end integration tests proving that source-chunk queries reach grounded answers with valid retrieval answer basis and resolving citations under all four graph conditions (empty facts, absent port, failing port, ablated graph).

---

## 1. Work Accomplished by Task

### Task 1: End-to-End Graph Ablation Tracer (TDD)
- **Files Modified**:
  - `engine/src/workflow/mod.rs`: Added `pub disable_graph_context: bool` to `WorkflowContext` with documentation per `M-DOCUMENTED-MAGIC` explaining single admission resolution, initialized in `WorkflowContext::new`.
  - `engine/src/service.rs`: Resolved `disable_graph_context` once at `query_rag` admission.
  - `engine/src/workflow/nodes/graph_context.rs`: Added early return before graph port presence check and graph query execution, clearing `graph_context` and `graph_facts` and emitting `notice(NoticeCode::GraphAblation, "Graph context disabled by caller request", NoticeSeverity::Info)`.
  - `engine/src/tests/workflow_phase5.rs`: Added 5 tests covering e2e service streaming, empty context/facts with grounded answer, default behavior on absent flag, explicit false flag, and verification that `FakeGraphQueryPort` call count is exactly 0 when ablated.
- **Commit**: `936ce71` (`feat(06-08): implement graph ablation request flag and observable notice`)

### Task 2: Machine-Readable Notices on Silent Graph Paths (TDD)
- **Files Modified**:
  - `engine/src/workflow/nodes/graph_context.rs`:
    - Success branch empty-result path (`facts.is_empty()`): Emits `notice(NoticeCode::GraphUnavailable, "Graph query returned no facts for this query", NoticeSeverity::Info)`.
    - Absent-port path (`self.graph_port.is_none()`): Emits `notice(NoticeCode::GraphUnavailable, "Graph context is not configured; answer produced from source chunks only", NoticeSeverity::Info)`.
    - Retained identical failure handling for `GraphTimeout` and `GraphDegraded`.
  - `engine/src/tests/workflow_phase5.rs`: Added 6 tests covering empty result notice, absent port notice, distinct message survival across deduplication, timeout regression preservation, degraded regression preservation, and non-cooccurrence with ablation.
- **Commit**: `65d0b5b` (`feat(06-08): emit distinct GraphUnavailable notices on empty-result and absent-port paths`)

### Task 3: Source-Chunk Query Proof & Test Invariants
- **Files Modified**:
  - `engine/src/tests/workflow_phase5.rs`: Added 4 workflow tests driving the full 5-node `WorkflowRunner` pipeline proving that queries with source chunks produce grounded answers with `AnswerBasis::Retrieval`, non-empty answer, resolving structured citations, and no `NodeFailed` events under empty, absent, failing, and ablated graph conditions.
  - `engine/src/tests.rs`: Updated two existing test assertions (`query_rag_citation_identity_and_notices` and `query_rag_valid_zero_match`) to accommodate the newly observable `GRAPH_UNAVAILABLE` notice.
  - `scripts/engine-test-targets.sh`: Updated test count invariants from 271 to 286 for `engine (lib)` (+15 new tests) and 298 to 313 for `TOTAL`.
- **Commit**: `a288728` (`test(06-08): prove source-chunk queries succeed without graph data and update test target counts`)

---

## 2. Test Target Distribution Changes

### Rust (`scripts/engine-test-targets.sh`)
- `engine (lib)`: **286** tests (was 271; +15 tests across tasks 1, 2, and 3)
- `engine (bin)`: **0** tests (unchanged)
- `inspect_lancedb (bin)`: **18** tests (unchanged)
- `seed_rag_fixture (bin)`: **0** tests (unchanged)
- `config_startup (test)`: **9** tests (unchanged)
- **TOTAL**: **313** tests (was 298; all 7 assertions verified green)

### Go Gateway (`gateway`)
- All gateway tests passing (`go test ./...` exits 0).

---

## 3. Debt and Criteria Closure
- **DEBT-RAG-06**: **CLOSED**. Graph absence is no longer silent. Empty graph queries and absent graph configurations emit distinct, machine-readable `GRAPH_UNAVAILABLE` notices. Intentional ablations emit `GRAPH_ABLATION`. Queries with source chunks never fail or stall due to missing or failing graph data.
- **Phase 6 Success Criterion 7**: **CLOSED**.

---

## 4. Commits
- `936ce71`: `feat(06-08): implement graph ablation request flag and observable notice`
- `65d0b5b`: `feat(06-08): emit distinct GraphUnavailable notices on empty-result and absent-port paths`
- `a288728`: `test(06-08): prove source-chunk queries succeed without graph data and update test target counts`
