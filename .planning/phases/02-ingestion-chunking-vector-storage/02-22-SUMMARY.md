---
phase: 02-ingestion-chunking-vector-storage
plan: 22
status: completed
last_updated: "2026-07-30T02:52:00Z"
---

# Plan 02-22 Summary: Graceful Shutdown Drain, Startup Recovery, and Chunk Ceiling

## Executive Summary

Executed Plan 02-22 to close the Rust-owned portions of CR-03 and WR-01 per D-45, D-46, and D-48.
The engine now persists full `IngestionJob` records into a versioned side-by-side staging table (`staged_documents_v2`), drains all acknowledged queue items upon graceful shutdown, reconstructs and enqueues staged jobs during startup recovery before serving gRPC callers, falls back to durable staging in status queries, and enforces the authoritative Rust chunk size limit (`MAX_CHUNK_SIZE = 1048576`).

## Task Execution & Findings

### Task 0: Select the one-way durable-staging transition
- **Decision:** Selected Option `versioned-side-by-side` ("Versioned side-by-side table").
- **Rationale:** Preserves legacy two-column `staged_documents` table byte-for-byte intact while creating a new 6-column `staged_documents_v2` table. If legacy rows exist without an explicit migration manifest, startup fails fast with count/class-only guidance per D-22.

### Task 1: Complete recoverable staging, shutdown drain, startup recovery, and staged status fallback
- **Files Modified:** `engine/src/db/mod.rs`, `engine/src/db/tests.rs`, `engine/src/main.rs`, `engine/src/tests.rs`, `engine/src/inspect_lancedb_tests.rs`.
- **Key Changes:**
  - **Schema & Migration Seam:** Created `staged_documents_v2_schema()` with 6 fields (`document_id`, `filename`, `raw_content`, `chunk_strategy`, `chunk_size`, `chunk_overlap`). Implemented `LegacyMigrationManifest` and `initialize_with_migration` to validate and migrate legacy rows losslessly while leaving legacy tables byte-identical.
  - **Durable Staging:** Updated `LancetServiceImpl::persist_raw` to write all validated job fields to `staged_documents_v2`.
  - **Startup Recovery:** Implemented `read_staged_jobs(&database)` to reconstruct `IngestionJob`s from durable staging and enqueue them before serving gRPC callers.
  - **Graceful Shutdown Drain:** Refactored `spawn_worker_with_boundary` so observing shutdown closes the receiver channel and drains all acknowledged items to completion before exiting.
  - **Staged Status Fallback:** Updated `get_ingestion_status` to consult `staged_documents_v2` when the in-memory registry misses a document ID, returning `"queued"` status rather than `NotFound`.
  - **Unit Tests:** Added 5 named behavioral tests (`shutdown_drains_acknowledged_queue`, `startup_recovery_processes_staged_document`, `status_falls_back_to_staged_document`, `legacy_staging_transition_is_versioned_and_lossless`, `legacy_staging_transition_rejects_incomplete_metadata`).

### Task 2: Authoritative Rust chunk-size ceiling
- **Files Modified:** `engine/src/main.rs`, `engine/src/tests.rs`.
- **Key Changes:**
  - Defined `pub const MAX_CHUNK_SIZE: usize = 1048576;` in `engine/src/main.rs`.
  - Updated `parse_chunk_settings` to reject values above `MAX_CHUNK_SIZE` with gRPC `InvalidArgument`.
  - Added `chunk_size_boundaries_are_engine_authoritative` test asserting that 1048576 is accepted and 1048577 or integer overflow returns `InvalidArgument`.

## Verification Results

- `cargo test --manifest-path engine/Cargo.toml`: All 55 tests passed cleanly across lib (4), main (30), inspect_lancedb (18), and config_startup (3).
- `cargo clippy --manifest-path engine/Cargo.toml --all-targets -- -D warnings`: Passed cleanly with 0 warnings.

## Artifacts Produced & Modified

- `engine/src/db/mod.rs` — Versioned `staged_documents_v2` schema, legacy table check, and `LegacyMigrationManifest` implementation.
- `engine/src/db/tests.rs` — Updated expected table names to `staged_documents_v2`.
- `engine/src/main.rs` — `MAX_CHUNK_SIZE`, `read_staged_jobs`, shutdown drain, staged status fallback, and `persist_raw`.
- `engine/src/tests.rs` — 6 new behavioral regression tests.
- `engine/src/inspect_lancedb_tests.rs` — Table initializer fix for `staged_documents_v2`.
