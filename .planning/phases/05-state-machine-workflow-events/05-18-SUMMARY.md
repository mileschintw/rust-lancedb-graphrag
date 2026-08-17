---
phase: 05-state-machine-workflow-events
plan: 18
type: execute
status: completed
executed_at: "2026-08-17T21:49:00.000Z"
requirements:
  - ORCH-01
  - ORCH-02
  - ORCH-03
files_modified:
  - engine/src/lib.rs
  - engine/src/tests.rs
  - engine/src/tests/workflow_phase5.rs
  - engine/src/tests/workflow_phase5_production.rs
  - engine/src/workflow/ports.rs
  - engine/src/main.rs
---

# Plan 05-18 Execution Summary: Split Workflow Tests by Target and Migrate BM25 Ownership Alias

## Overview

Plan 05-18 (Wave 13) split the Phase 5 workflow orchestration tests by compilation target:
1. Registered generic workflow fake-dependent tests under `#[cfg(test)]` in `engine/src/lib.rs` (`mod workflow_phase5;`).
2. Removed the duplicate generic `workflow_phase5` module declaration from the binary-side `engine/src/tests.rs`, retaining only `workflow_phase5_production`.
3. Relocated all 25 fake-port call sites from `engine/src/tests.rs` into `engine/src/tests/workflow_phase5.rs`.
4. Introduced the production-visible `Bm25IndexStore` type alias (`Arc<RwLock<Arc<Bm25Index>>>`) in `engine/src/workflow/ports.rs` and updated `LancetServiceImpl` and `ProductionBm25RetrievalPort` in `engine/src/main.rs`.
5. Migrated all 18 BM25 test fixture constructions and 37 references in `engine/src/tests.rs` to the `Arc` snapshot ownership shape.
6. Added the side-effect-free compile probe `workflow_phase5_library_target_fake_ports_compile` referencing all six workflow fake ports in the library target.

## Key Changes

1. **`engine/src/lib.rs`**:
   - Added `#[cfg(test)] #[path = "tests/workflow_phase5.rs"] pub mod workflow_phase5;`.
2. **`engine/src/workflow/ports.rs`**:
   - Added `pub type Bm25IndexStore = Arc<RwLock<Arc<Bm25Index>>>;`.
3. **`engine/src/main.rs`**:
   - Updated `LancetServiceImpl.bm25_index` and `ProductionBm25RetrievalPort.bm25_index` to use `workflow::ports::Bm25IndexStore`.
   - Updated server initialization to wrap initial BM25 index in `Arc::new(tokio::sync::RwLock::new(Arc::new(bm25_index)))`.
4. **`engine/src/tests.rs`**:
   - Removed `pub mod workflow_phase5;`.
   - Relocated 12 test functions containing 25 fake-port call sites to `workflow_phase5.rs`.
   - Updated all 18 BM25 fixture constructions to `Arc::new(tokio::sync::RwLock::new(Arc::new(bm25_index)))`.
5. **`engine/src/tests/workflow_phase5.rs`**:
   - Received relocated test cases and `candidate_with_score` helper.
   - Added `workflow_phase5_library_target_fake_ports_compile` probe test.

## Verification & Determinism

- **Task 1 Verification**:
  - `workflow_phase5_happy_path` confirmed listed and passing via `cargo test --lib`.
  - Library `workflow_phase5` registration verified for `cfg(test)` and `path` attributes.
  - Zero workflow fake call sites remaining in binary `engine/src/tests.rs`.
  - Exactly 37 `bm25_index` references and 18 `RwLock::new(Arc::new(bm25_index...))` constructions verified in `engine/src/tests.rs`.
  - `cargo test --bin engine --manifest-path engine/Cargo.toml --locked --no-run` passed.
- **Task 2 Verification**:
  - `workflow_phase5_library_target_fake_ports_compile` listed and passed in library target.
  - Binary target compiled cleanly with `cargo test --bin engine --manifest-path engine/Cargo.toml --locked --no-run`.
  - Full suite `cargo test --lib --manifest-path engine/Cargo.toml --locked` passed (111 passed, 0 failed, 1 ignored).

## Commits

- `feat(05-18): route fake-dependent tests and BM25 ownership shape before cfg(test) gating`
- `test(05-18): prove cfg(test) fake-port seam and binary test compilation`
