---
phase: 05-state-machine-workflow-events
plan: 16
type: execute
status: completed
executed_at: "2026-08-17T22:20:00.000Z"
requirements:
  - ORCH-01
  - ORCH-03
  - ORCH-04
files_modified:
  - engine/src/main.rs
  - engine/src/workflow/mod.rs
  - engine/src/workflow/nodes/graph_context.rs
  - engine/src/workflow/nodes/retrieve.rs
  - engine/src/tests/workflow_phase5.rs
  - engine/src/tests/workflow_phase5_production.rs
---

# Plan 05-16 Execution Summary: Graph Degradation, Notice Accumulation, Retrieval Provenance, and BM25 Concurrency Safety

## Overview

Plan 05-16 (Wave 15) addressed key workflow integrity and safety findings:
1. **Graph Degradation Codes & Notice Accumulation**:
   - Defined machine-readable notice codes `GRAPH_TIMEOUT` and `GRAPH_DEGRADED` at the workflow boundary (`engine/src/workflow/mod.rs`).
   - Implemented `WorkflowContext::add_notice` and `WorkflowContext::merge_notices` to preserve ordered notice history, avoid duplicate entries for identical `(code, message)` pairs, and ensure prior notices survive degradation or failure.
   - Updated `ExtractGraphContextNode` to report `GRAPH_TIMEOUT` on inner timeout and `GRAPH_DEGRADED` on no-match or graph logical error without failing the workflow (D-09).
   - Added unit regression test `workflow_phase5_graph_notice_merge` verifying that pre-existing notices survive subsequent graph outcomes, timeouts, and terminal failures in exact order.

2. **Retrieval Snapshot Provenance & BM25 Concurrency Safety**:
   - Populated `RetrievalSnapshot.variant_count` (`u32`) and ordered `variant_identities` (`Vec<String>`) across all Rust production snapshot literals in `engine/src/main.rs` and `engine/src/workflow/nodes/retrieve.rs`.
   - Updated `ProductionBm25RetrievalPort` to clone an inner `Arc<Bm25Index>` from `Bm25IndexStore` and release the `RwLock` read guard *before* entering async retrieval, preventing blocked ingestion writes during long-running or stalled retrievals.
   - Added production suite tests `workflow_phase5_retrieval_snapshot_variants` and `workflow_phase5_bm25_snapshot_releases_lock` in `engine/src/tests/workflow_phase5_production.rs`.

## Key Changes

1. **`engine/src/workflow/mod.rs`**:
   - Exported constants `GRAPH_TIMEOUT` and `GRAPH_DEGRADED`.
   - Added `add_notice(&mut self, notice: Notice)` and `merge_notices(&mut self, new_notices: impl IntoIterator<Item = Notice>)` on `WorkflowContext`.
   - Updated `update_from_model_output` to route info notices and warnings through `add_notice`.

2. **`engine/src/workflow/nodes/graph_context.rs`**:
   - Updated `ExtractGraphContextNode::run` to emit `GRAPH_DEGRADED` for no-match/logical errors and `GRAPH_TIMEOUT` for timeouts via `ctx.add_notice`.

3. **`engine/src/workflow/nodes/retrieve.rs`**:
   - Populated `variant_count: ctx.variants.len() as u32` and `variant_identities: ctx.variants.clone()` in `RetrieveHybridNode`'s `RetrievalSnapshot`.

4. **`engine/src/main.rs`**:
   - Updated `ProductionBm25RetrievalPort` to scope and drop the `RwLock` read guard before `retrieve(...).await`.
   - Populated `variant_count` and `variant_identities` in zero-evidence and completed `RetrievalSnapshot` construction sites.

5. **`engine/src/tests/workflow_phase5.rs`**:
   - Added `workflow_phase5_graph_notice_merge` to verify notice ordering, deduplication, degradation codes, and persistence through failure.

6. **`engine/src/tests/workflow_phase5_production.rs`**:
   - Added `workflow_phase5_retrieval_snapshot_variants` to verify variant provenance in the production snapshot.
   - Added `workflow_phase5_bm25_snapshot_releases_lock` to prove writer lock acquisition and index swapping progress without blocking during retrieval.

## Verification

- **Task 1 Verification**:
  - `workflow_phase5_graph_notice_merge` passed registration check and executed cleanly.
- **Task 2 Verification**:
  - `cargo test --bin engine --manifest-path engine/Cargo.toml --locked --no-run` passed compilation.
  - `workflow_phase5_retrieval_snapshot_variants` and `workflow_phase5_bm25_snapshot_releases_lock` passed execution.
  - Source-scoped regex checks on `engine/src/main.rs` and `engine/src/workflow/nodes/retrieve.rs` passed without errors.
  - Full production regression suite (`workflow_phase5_production_five_node`, `workflow_phase5_production_dependencies_are_real`, `workflow_phase5_production_context_population`, `workflow_phase5_settings_applied_to_production`, `workflow_phase5_config_verify_generation_timeout`) passed.
  - Full library test suite `cargo test --lib --manifest-path engine/Cargo.toml --locked` (114 tests) passed with 0 failures.
