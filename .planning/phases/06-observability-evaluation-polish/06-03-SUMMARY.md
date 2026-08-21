---
phase: 06-observability-evaluation-polish
plan: "03"
subsystem: engine
tags: [refactor, module-graph, rust, tests, test-topology]
requires:
  - "06-02"
provides:
  - "engine::tests"
affects:
  - "engine/src/lib.rs"
  - "engine/src/main.rs"
  - "engine/src/tests.rs"
  - "engine/src/tests/workflow_phase5_production.rs"
  - "scripts/engine-test-targets.sh"
tech-stack:
  added: []
  patterns:
    - "Library-owned test root in engine::tests"
    - "Thin binary entry point with zero module declarations"
    - "Seven named test-target invariants in scripts/engine-test-targets.sh"
key-files:
  created: []
  modified:
    - "engine/src/lib.rs"
    - "engine/src/main.rs"
    - "engine/src/tests.rs"
    - "engine/src/tests/workflow_phase5_production.rs"
    - "scripts/engine-test-targets.sh"
key-decisions:
  - "Rehomed engine/src/tests.rs into engine::tests via #[cfg(test)] pub mod tests; in engine/src/lib.rs, closing DEBT-P3-MODULE-GRAPH."
  - "Replaced use super::*; glob in tests.rs with explicit named imports from engine::{client, config, db, generation, graph, ingest, pb, prompt, rerank, retrieval, service, workflow}."
  - "Swept main.rs residue completely: engine/src/main.rs contains 0 module declarations, 0 pub use aliases, and exactly 1 top-level item (async fn main)."
  - "Repointed crate:: references in workflow_phase5_production.rs and tests.rs to crate::config, crate::service, crate::ingest as needed."
  - "Extended scripts/engine-test-targets.sh to assert 7 named invariants including the measured 261 lib / 0 bin distribution."
requirements-completed:
  - RAG-03
coverage:
  - deliverable: "Test root rehoming and main.rs residue sweep"
    verification:
      kind: command
      ref: "sh scripts/engine-test-targets.sh"
      status: pass
      human_judgment: false
  - deliverable: "Full suite test execution across Rust and Go targets"
    verification:
      kind: command
      ref: "cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)"
      status: pass
      human_judgment: false
duration: "18 min"
completed: "2026-08-20T22:50:00Z"
---

# Phase 06 Plan 03: Rust Module-Graph Restructure (Test Root Rehoming & `main.rs` Residue Sweep) Summary

Completed DEBT-P3-MODULE-GRAPH by rehoming the binary test root `engine/src/tests.rs` into the library target (`engine::tests`), eliminating all `super::*` glob coupling, updating all internal resolution paths, sweeping `engine/src/main.rs` down to pure startup wiring (0 modules, 0 `pub use`, 1 top-level item: `async fn main()`), and pinning the final post-restructure test distribution in `scripts/engine-test-targets.sh`.

## Accomplishments

1. **Test Root Rehomed to Library Target (`engine::tests`)**:
   - Declared `#[cfg(test)] pub mod tests;` in `engine/src/lib.rs`.
   - Removed `#[cfg(test)] mod tests;` and all `#[cfg(test)] use ...` blocks from `engine/src/main.rs`.
   - Replaced `use super::*;` in `engine/src/tests.rs` with explicit named imports from `engine::{client, config, db, generation, graph, ingest, pb, prompt, rerank, retrieval, service, workflow}`.
   - Updated helper functions (`database_path`, `stage_document`, `stage_document_with_settings`, `configured_service`) in `tests.rs` with `pub(crate)` visibility.
   - Removed all `super::` prefixes across `tests.rs` (replaced with direct imports or `extraction::*`).

2. **Repointed Resolution Paths in `workflow_phase5_production.rs` and `tests.rs`**:
   - Repointed `crate::EffectiveRagSettings` -> `crate::config::EffectiveRagSettings`.
   - Repointed `crate::EmbeddingProvider` -> `crate::ingest::EmbeddingProvider`.
   - Repointed `crate::QUEUE_CAPACITY` -> `crate::ingest::QUEUE_CAPACITY`.
   - Repointed `crate::LancetServiceImpl` -> `crate::service::LancetServiceImpl`.
   - Repointed `crate::WorkflowSettings` -> `crate::config::WorkflowSettings`.
   - Repointed `crate::Settings` -> `crate::config::Settings`.
   - Repointed `crate::parse_chunk_settings` -> `parse_chunk_settings`.
   - Used `::config::Config` to distinguish the external `config` crate from `engine::config`.

3. **Pruned `engine/src/main.rs` to Single Top-Level Item**:
   - `engine/src/main.rs` contains zero lines matching `^\s*(pub )?mod `.
   - `engine/src/main.rs` contains zero non-comment lines matching `^pub use`.
   - `engine/src/main.rs` contains exactly one top-level item: `async fn main()`.

4. **Extended Gate Script (`scripts/engine-test-targets.sh`)**:
   - Added 2 new named assertions for the library target (`LIB_COUNT == 261`) and the `engine` binary target (`BIN_MAIN_COUNT == 0`).
   - Documented in head comment that target values are measured invariants to be updated in the same commit as tests that move them.
   - Total of 7 named invariant checks.

## Post-Restructure Test Topology Baseline

The following per-target counts were measured and are the canonical baseline that every subsequent Phase 6 plan verifies:

```
engine (lib): 261
engine (bin): 0
inspect_lancedb (bin): 18
seed_rag_fixture (bin): 0
config_startup (test): 9
TOTAL: 288 (lib+bin: 261, inspect_lancedb: 18, seed_rag_fixture: 0, config_startup: 9)
All 7 Rust test target invariants verified successfully.
```

## Verification Matrix

- `cargo build --manifest-path engine/Cargo.toml` — passed (0 errors)
- `cargo clippy --manifest-path engine/Cargo.toml -- -D warnings` — passed (0 warnings)
- `cargo fmt --manifest-path engine/Cargo.toml --check` — passed
- `cargo test --manifest-path engine/Cargo.toml --locked` — passed (288 tests: 260 passed, 1 ignored in lib; 0 in bin; 18 in inspect_lancedb; 0 in seed_rag_fixture; 9 in config_startup)
- `sh scripts/engine-test-targets.sh` — passed (7/7 invariants green)
- `(cd gateway && go test ./...)` — passed (all packages green)
- `grep -c '^\(pub \)\?\(async \)\?fn \|^\(pub \)\?struct \|^\(pub \)\?enum \|^\(pub \)\?trait \|^impl \|^\(pub \)\?const \|^\(pub \)\?static ' engine/src/main.rs` — returns `1`
- `grep -c 'use super::\*' engine/src/tests.rs` — returns `0`
- `grep -c '^[[:space:]]*\(pub \)\?mod ' engine/src/main.rs` — returns `0`

## Self-Check: PASSED
