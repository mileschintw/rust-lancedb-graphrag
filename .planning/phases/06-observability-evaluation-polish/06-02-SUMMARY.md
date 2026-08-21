---
phase: 06-observability-evaluation-polish
plan: 02
subsystem: engine
tags: [refactor, module-graph, rust, ingestion, service, grpc]
requires:
  - "06-01"
provides:
  - "engine::ingest"
  - "engine::service"
affects:
  - "engine/src/lib.rs"
  - "engine/src/main.rs"
  - "engine/src/ingest.rs"
  - "engine/src/service.rs"
tech-stack:
  added: []
  patterns:
    - "Library-owned ingestion pipeline in engine::ingest"
    - "Library-owned gRPC service in engine::service"
    - "Module-scoped CancelOnDropStream"
key-files:
  created:
    - "engine/src/ingest.rs"
    - "engine/src/service.rs"
  modified:
    - "engine/src/lib.rs"
    - "engine/src/main.rs"
key-decisions:
  - "Moved ingestion pipeline (constants, IngestionJob, EmbeddingProvider trait and impl, replacement/rollback boundaries, worker) into engine::ingest."
  - "Moved LancetServiceImpl, tonic LancetService trait impl, d1_status, validate_document_id, and production port adapters into engine::service."
  - "Lifted CancelOnDropStream from inside query_rag body to module scope in engine::service."
  - "Preserved all 10 gRPC error-kind strings byte-for-byte in engine::service."
  - "Maintained exact test target distribution (lib: 139, bin: 122, inspect_lancedb: 18, seed_rag_fixture: 0, config_startup: 9) totaling 288 tests."
  - "Reduced engine/src/main.rs to startup wiring, imports, and single test root declaration with zero pub use aliases."
requirements-completed:
  - RAG-03
coverage:
  - deliverable: "Ingestion and service relocation into library modules"
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
duration: "15 min"
completed: "2026-08-20T22:20:00Z"
---

# Phase 06 Plan 02: Rust Module-Graph Restructure (Ingestion & Service Relocation) Summary

Completed the second half of DEBT-P3-MODULE-GRAPH by extracting the ingestion pipeline and the full gRPC service implementation out of `engine/src/main.rs` into library modules `engine::ingest` and `engine::service`.

## Accomplishments

1. **Ingestion Pipeline Relocation (`engine::ingest`)**:
   - Created `engine/src/ingest.rs` with `//!` module documentation.
   - Relocated constants (`MAX_DOCUMENT_BYTES`, `QUEUE_CAPACITY`, `DEFAULT_CHUNK_SIZE`, `DEFAULT_CHUNK_OVERLAP`, `MAX_CHUNK_SIZE`), structs (`IngestionStatus`, `ChunkSettings`, `IngestionJob`, `ReplacementMutation`, `LanceDbReplacementMutationBoundary`, `StagedJobRow`, `ExtractionPersistSummary`), traits (`ReplacementMutationBoundary`, `EmbeddingProvider`), and functions (`parse_chunk_settings`, `chunk_ingestion_job`, `select_latest_staged_rows`, `read_staged_jobs`, `get_max_staged_generation`, `persist_raw_with_boundary`, `content_hash`, `content_type`, `replace_document`, `restore_version`, `rollback_replacement`, `replace_document_with_faults`, `process_job`, `process_job_with_boundary`, `spawn_worker`, `spawn_worker_with_boundary`).
   - Declared `pub mod ingest;` in `engine/src/lib.rs`.

2. **gRPC Service Implementation Relocation (`engine::service`)**:
   - Created `engine/src/service.rs` with `//!` module documentation.
   - Lifted `CancelOnDropStream` to module scope.
   - Relocated `LancetServiceImpl`, inherent impls (`persist_raw`, `build_production_workflow`), and gRPC `LancetService` implementation (`ping`, `ingest_document`, `get_ingestion_status`, `query_rag`, `query_graph`).
   - Relocated error-identity helper `d1_status` and validation helpers `validate_document_id`, `sanitize_header_value`, `internal`.
   - Relocated production port adapters (`ProductionEmbeddingPort`, `ProductionGraphQueryPort`, `ProductionDenseRetrievalPort`, `ProductionBm25RetrievalPort`) and graph augmentation helpers (`GraphAugmentationOutcome`, `attempt_graph_augmentation`).
   - Preserved all 10 error-kind string literals byte-for-byte (`empty_query`, `query_too_long`, `invalid_document_id`, `unsupported_content_type`, `empty_filter_value`, `filter_limit_exceeded`, `invalid_settings`, `non_finite_score`, `snapshot`, `invalid_session_id`).
   - Declared `pub mod service;` in `engine/src/lib.rs`.

3. **Pruned `engine/src/main.rs`**:
   - Reduced `engine/src/main.rs` strictly to imports, `main()` startup wiring, and the single `#[cfg(test)] mod tests;` module declaration.
   - Removed all redundant definitions and zero `pub use` aliases exist.

## Verification and Metrics

### Test Target Invariant Check (`scripts/engine-test-targets.sh`)
```
engine (lib): 139
engine (bin): 122
inspect_lancedb (bin): 18
seed_rag_fixture (bin): 0
config_startup (test): 9
TOTAL: 288 (lib+bin: 261, inspect_lancedb: 18, seed_rag_fixture: 0, config_startup: 9)
All 5 Rust test target invariants verified successfully.
```

### Verification Matrix
- `cargo build --manifest-path engine/Cargo.toml` — passed (0 errors)
- `cargo clippy --manifest-path engine/Cargo.toml -- -D warnings` — passed (0 warnings)
- `cargo fmt --manifest-path engine/Cargo.toml --check` — passed
- `cargo test --manifest-path engine/Cargo.toml --locked` — passed (288 tests passed)
- `go test ./...` in `gateway/` — passed (all packages green)
- `grep -c '^pub use' engine/src/main.rs` — 0
- Module count in `engine/src/main.rs` — exactly 1 (`mod tests;`)

## Remaining Items in `engine/src/main.rs`
1. Top-level crate imports (`Arc`, `Duration`, `DashMap`, `mpsc`, `watch`, `Server`, `OpenRouterClient`, `EffectiveRagSettings`, `DatabaseManager`, `generation`, `graph`, `read_staged_jobs`, `spawn_worker`, `LancetServiceServer`, `rerank`, `Bm25Index`, `LancetServiceImpl`).
2. Test-scoped `#[cfg(test)]` imports for `tests.rs`.
3. `async fn main() -> Result<(), Box<dyn std::error::Error>>` (105 lines of startup wiring).
4. `#[cfg(test)] mod tests;`.

## Self-Check: PASSED
