---
phase: 06-observability-evaluation-polish
plan: 01
subsystem: engine
tags: [refactor, module-graph, rust, chunker, config]
requires: []
provides:
  - "engine::chunker"
  - "engine::config"
  - "scripts/engine-test-targets.sh"
affects:
  - "engine/src/lib.rs"
  - "engine/src/main.rs"
  - "engine/src/chunker/mod.rs"
  - "engine/src/config.rs"
  - "scripts/engine-test-targets.sh"
tech-stack:
  added: []
  patterns:
    - "Library-owned configuration module and chunker"
    - "scripts/engine-test-targets.sh invariant checker"
key-files:
  created:
    - "scripts/engine-test-targets.sh"
    - "engine/src/config.rs"
  modified:
    - "engine/src/lib.rs"
    - "engine/src/main.rs"
    - "engine/src/chunker/mod.rs"
key-decisions:
  - "Moved engine::chunker and engine::config to engine/src/lib.rs with zero pub use aliases in main.rs (M-SINGLE-ITEM-PATH)."
  - "Preserved all 18 distinct LANCET_* environment variable literal bindings byte-for-byte in engine::config."
  - "Maintained 288 total test cases across 5 cargo targets, moving 6 chunker tests into the library target (lib: 133 -> 139, bin: 128 -> 122)."
requirements-completed:
  - RAG-03
coverage:
  - deliverable: "Per-target test invariant gate and chunker library relocation"
    verification:
      kind: command
      ref: "sh scripts/engine-test-targets.sh"
      status: pass
    human_judgment: false
  - deliverable: "Configuration surface relocation into engine::config"
    verification:
      kind: command
      ref: "cargo test --manifest-path engine/Cargo.toml --test config_startup"
      status: pass
    human_judgment: false
duration: "10 min"
completed: "2026-08-20T18:48:00Z"
---

# Phase 06 Plan 01: Rust Module-Graph Restructure (Chunker & Config) Summary

Relocated `engine::chunker` and `engine::config` into the `engine` library crate, shrinking `engine/src/main.rs` and establishing the per-target test invariant gate `scripts/engine-test-targets.sh`.

## Accomplishments

1. **Per-Target Invariant Gate (`scripts/engine-test-targets.sh`)**:
   - Implemented POSIX shell script asserting test counts across cargo test targets with path-normalization and fail-closed validation.
   - Enforces 288 total test cases: `lib + bin == 261`, `inspect_lancedb == 18`, `seed_rag_fixture == 0`, `config_startup == 9`.

2. **Chunker Relocation (`engine::chunker`)**:
   - Added `pub mod chunker;` to `engine/src/lib.rs`.
   - Added `//!` doc comment header to `engine/src/chunker/mod.rs`.
   - Updated `engine/src/main.rs` to import `engine::chunker::{chunk_fixed_size, chunk_markdown, estimate_tokens, Chunk}` with no re-export aliases.

3. **Configuration Relocation (`engine::config`)**:
   - Extracted settings structs (`Settings`, `EngineSettings`, `EffectiveRagSettings`, `WorkflowSettings`, `GraphSettings`, `RetrievalConfigSettings`, `Bm25ConfigSettings`, `OpenRouterSettings`), `new_index_generation`, `load_settings`, and default helpers into `engine/src/config.rs`.
   - Maintained all 18 `LANCET_*` environment variable bindings and fail-open/fail-closed behaviors without key rename.
   - Declared `pub mod config;` in `engine/src/lib.rs`.

## Verification and Metrics

### Pre-Move Baseline
- **Pre-move LANCET distinct-literal count**: `18`
- **Pre-move test target distribution**:
  - `engine (lib)`: 133
  - `engine (bin)`: 128
  - `inspect_lancedb (bin)`: 18
  - `seed_rag_fixture (bin)`: 0
  - `config_startup (test)`: 9
  - **TOTAL**: 288 (lib+bin: 261)

### Post-Move Verification
- **Post-move LANCET distinct-literal count**: `18` (matches pre-move count exactly)
- **Post-move test target distribution**:
  - `engine (lib)`: 139 (+6 from chunker unit tests)
  - `engine (bin)`: 122 (-6)
  - `inspect_lancedb (bin)`: 18
  - `seed_rag_fixture (bin)`: 0
  - `config_startup (test)`: 9
  - **TOTAL**: 288 (lib+bin: 261)

All automated verification checks passed:
- `cargo build --manifest-path engine/Cargo.toml` passed
- `cargo clippy --manifest-path engine/Cargo.toml -- -D warnings` passed
- `cargo test --manifest-path engine/Cargo.toml --locked` passed (288 tests passed)
- Zero `pub use` aliases in `engine/src/main.rs`

## Deviations from Plan

### Auto-fixed Lint Adjustments
- **[Rule 1 - Bug/Lint Fix] Clippy Cleanliness in engine**:
  - Derived `Default` on `Settings` and `ContextAssemblyStrategy`.
  - Added `#[allow(clippy::too_many_arguments)]` on `OpenRouterGenerationConfig::new`.
  - Removed unnecessary `.clone()` calls on `Copy` type `NodeErrorKind` in `runner.rs` and `workflow/mod.rs`.
  - Replaced `.into_iter()` on zip arg in `main.rs` and single-iteration loop in `seed_rag_fixture.rs`.
  - All adjustments preserved semantics and allowed `cargo clippy -- -D warnings` to pass.

## Self-Check: PASSED
