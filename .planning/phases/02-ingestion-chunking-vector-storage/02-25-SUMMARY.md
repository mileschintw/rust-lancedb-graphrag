# Plan 02-25 Execution Summary

## Overview
Phase 02 Plan 25 addresses staging lifecycle gaps according to ADR-02-003 (D-01 through D-04).

## Key Accomplishments

### Task 1: Single Staging Table Initializer & Worker-First Startup Replay (D-01, D-02)
- Removed all legacy migration logic (`LegacyMigrationEntry`, `LegacyMigrationManifest`, `initialize_with_migration`) from `engine/src/db/mod.rs`.
- `DatabaseManager::initialize` operates directly on `staged_documents_v2` and is fully idempotent over existing non-empty tables.
- Spawns the ingestion worker task in `engine/src/main.rs` before reading and enqueuing staged jobs on startup.
- Propagates channel errors if the worker task exits during replay.
- Verified with Rust regression tests:
  - `startup_recovery_exceeds_queue_capacity_without_deadlock` (stages 101 jobs > QUEUE_CAPACITY 100 without deadlock)
  - `startup_recovery_fails_when_worker_exits`
  - `initialize_is_idempotent_over_non_empty_staging`

### Task 2: Durable Proven Absence & Cross-Runtime Convergence (D-03, D-04)
- Updated `LancetServiceImpl::get_ingestion_status` in `engine/src/main.rs` to map staging count query failures to `tonic::Status::unavailable` instead of falling back to `NotFound`.
- Updated `spawn_worker_with_boundary` error path in `engine/src/main.rs` to require successful `StagingDelete` before inserting `failed` status into the in-memory status map. If deletion fails, removes in-memory status so queries fall back to `staged_documents_v2` (returning `queued`) to ensure replayability upon restart.
- Added cross-runtime Go integration test `TestEmbeddingFailureRestartConvergesAcrossRuntime` in `gateway/main_test.go` and Rust fixture `d04_cross_runtime_grpc_fixture`.
- Verified with Go and Rust regression tests:
  - `staging_read_error_is_unavailable`
  - `staging_delete_failure_remains_replayable`
  - `embedding_failure_restart_converges_cross_store`
  - `TestGetDocumentLeavesTransientEngineFailureQueued`
  - `TestEmbeddingFailureRestartConvergesAcrossRuntime`

## Verification Results
- `cargo test --manifest-path engine/Cargo.toml --locked` (60 passed, 0 failed).
- `go test -count=1 -run '^TestGetDocumentLeavesTransientEngineFailureQueued$' .` (PASS).
- `go test -count=1 -run '^TestEmbeddingFailureRestartConvergesAcrossRuntime$' .` (PASS).

## Commits
- Task 1: `71eb544` - `feat(engine): worker-first replay and single staging initializer (D-01, D-02)`
- Task 2: `d8f5cef` - `feat(engine,gateway): durable status and cross-runtime restart convergence (D-03, D-04)`
