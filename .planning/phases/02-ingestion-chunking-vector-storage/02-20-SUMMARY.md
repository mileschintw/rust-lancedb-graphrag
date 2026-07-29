# Phase 02-20 Summary: Inspector Read-Only Enforcement, Vector Sanitization, and Missing Schema Rollback Seam

## Summary
- **Plan File:** [02-20-PLAN.md](file:///d:/Repos/lancet/.planning/phases/02-ingestion-chunking-vector-storage/02-20-PLAN.md)
- **Status:** Completed
- **Findings Addressed:** CR-06, WR-05, BU-03, BU-04, WR-03 (Rust paths)

## Work Completed

### Task 1: Non-Mutating Inspector and Persisted Value Sanitization (`CR-06`, `WR-05`, `BU-03`)
- Created `DatabaseManager::open_and_validate(path)` in `engine/src/db/mod.rs` as a dedicated read-only diagnostic connection seam separate from `DatabaseManager::initialize`.
- Enforced read-only validation: checks existing table names, opens required tables, and validates schemas without calling table creation, migration, restore, add, delete, or replacement mutations.
- Updated `engine/src/bin/inspect_lancedb.rs` to switch exclusively to `DatabaseManager::open_and_validate`.
- Sanitized inspector diagnostics per D-31/D-32: replaced raw `embedding_model` string interpolation with class-only error reporting (`LanceDB contains unknown embedding_model class`) so secret-like or untrusted values never reach logs/terminals.
- Expanded Float32 vector child validations and created discrete real LanceDB test fixtures in `engine/src/inspect_lancedb_tests.rs` for:
  - `null` child values (fails closed)
  - `NaN` child values (fails closed)
  - `+infinity` child values (fails closed)
  - `-infinity` child values (fails closed)
  - Finite control (passes inspection)
- Added regression tests asserting sentinel string omission in unknown model errors, before/after durable store state immutability, and missing table non-mutation.

### Task 2: True Missing Schema Field Rollback and Ingestion Worker Survival (`WR-03`, `BU-04`)
- Added `field_with_name` method to `ReplacementMutationBoundary` in `engine/src/main.rs`, replacing the inaccurate `NodesAdd` failure injection.
- Wired production `field_with_name` calls during node/edge null array creation through `mutations.field_with_name`.
- Added `spawn_worker_with_boundary` and `process_job_with_boundary` to allow test injection through active worker task loops.
- Implemented `rollback_replacement` staging cleanup per D-35: when document replacement fails, any uncommitted `staged_documents` row for that document is cleaned up.
- Replaced misleading test in `engine/src/tests.rs` with `schema_field_lookup_failure_rolls_back_and_worker_survives`:
  - Drives a missing schema field lookup failure on `"page_start"` after version capture through an active worker.
  - Verifies terminal `failed` status in status map with dedicated schema field error class.
  - Asserts prior durable generation and row/version counts remain unchanged, and staging table is cleared.
  - Verifies the same worker receiver stays alive and successfully completes a subsequent document ingestion job (`job_3`).

## Verification Results

### Automated Tests
- `cargo test --manifest-path engine/Cargo.toml --bin inspect_lancedb`: **PASS** (18/18 passed in 0.97s)
- `cargo test --manifest-path engine/Cargo.toml schema_field_lookup_failure_rolls_back_and_worker_survives`: **PASS** (1/1 passed in 1.11s)
- `cargo test --manifest-path engine/Cargo.toml`: **PASS** (49/49 passed in 12.18s)
- `cargo clippy --manifest-path engine/Cargo.toml --all-targets -- -D warnings`: **PASS** (0 warnings)
- `cargo fmt --manifest-path engine/Cargo.toml -- --check`: **PASS** (clean formatting)

## Key Files Modified
- [engine/src/db/mod.rs](file:///d:/Repos/lancet/engine/src/db/mod.rs): Added `DatabaseManager::open_and_validate(path)` and derived `Debug` implementation.
- [engine/src/bin/inspect_lancedb.rs](file:///d:/Repos/lancet/engine/src/bin/inspect_lancedb.rs): Switched to `open_and_validate` and sanitized unknown model errors to class-only output.
- [engine/src/inspect_lancedb_tests.rs](file:///d:/Repos/lancet/engine/src/inspect_lancedb_tests.rs): Added tests for sentinel omission, store immutability, missing tables, and discrete null/NaN/+inf/-inf/finite vector fixtures.
- [engine/src/main.rs](file:///d:/Repos/lancet/engine/src/main.rs): Extended `ReplacementMutationBoundary` with `field_with_name`, updated `rollback_replacement` to clear staging, and added `spawn_worker_with_boundary`.
- [engine/src/tests.rs](file:///d:/Repos/lancet/engine/src/tests.rs): Added `FaultingSchemaFieldBoundary` and replaced fault test with `schema_field_lookup_failure_rolls_back_and_worker_survives`.
