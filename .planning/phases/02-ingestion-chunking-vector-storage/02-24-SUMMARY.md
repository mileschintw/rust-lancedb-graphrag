---
phase: 02-ingestion-chunking-vector-storage
plan: 24
status: completed
last_updated: "2026-07-30T03:00:00Z"
---

# Plan 02-24 Summary: Bounded Gateway Admission, Staging-Aware Polling, Isolated Database Fixtures, and Exit-Gate Closure

## Executive Summary

Executed Plan 02-24 to close CR-02, the Go gateway portions of CR-03 and WR-01, and execute the deterministic ADR-02-002 five-gap exit gate per D-44, D-45, D-46, and D-48.
The Go gateway now enforces a thin `maxChunkSize = 1048576` mirror matching Rust's authoritative ceiling before PostgreSQL insertion or gRPC streaming, preserves queued/recoverable status without terminal mutation during status polling, and executes database reconciliation lease integration tests within per-test isolated PostgreSQL schemas, eliminating unqualified table wipes and protecting unrelated rows.

All unit, integration, Rust engine, Python live-evidence, privacy probe, and placeholder verification gates passed cleanly.

## Task Execution & Findings

### Task 1: Keep one accepted document truthful across HTTP admission and restart-facing polling
- **Files Modified:** `gateway/main.go`, `gateway/main_test.go`.
- **Key Changes:**
  - Defined `const maxChunkSize = 1048576` in `gateway/main.go` as the mirror of Rust's authoritative `MAX_CHUNK_SIZE`.
  - Parsed `chunk_size` with `strconv.ParseInt(reqSize, 10, 32)` and rejected values below 1 or above `maxChunkSize` (such as 1048577 or int32 overflow 2147483648) with HTTP 400 before document allocation, store insertion, or gRPC streaming.
  - Aligned `getDocument` polling with Rust's staging-aware status contract: queued staging responses perform no terminal store mutation, while `codes.NotFound` confirms absence from both registry and staging, performing the terminal failed transition and winner reread.
  - Added 3 regression tests in `gateway/main_test.go`: `TestCreateDocumentChunkSizeBoundaries`, `TestGetDocumentRecoverableStagingRemainsQueued`, and `TestGetDocumentNotFoundMarksFailedAfterRustConfirmsAbsence`.

### Task 2: Scope reconciliation lease fixtures and run the five-gap exit gate
- **Files Modified:** `gateway/db/document_test.go`, `scripts/test_phase02_live_evidence.py`.
- **Key Changes:**
  - Implemented `createIsolatedTestPool` helper in `gateway/db/document_test.go` to create a cryptographically unique PostgreSQL schema per test, clone production table shapes (`documents`, `document_reconciliation_intents`), and set the claimant connection pool's `search_path` to that schema.
  - Updated `TestReconciliationIntentClaimLeaseIsExclusive` to run inside an isolated schema, removing the table-wide `DELETE FROM documents"` statement.
  - Added `TestReconciliationIntentClaimLeasePreservesUnrelatedDocumentAndIntent` to verify that claiming due intents in an isolated schema leaves unrelated document and intent rows completely unchanged and leaves public table counts untouched.
  - Updated relative path resolution in `scripts/test_phase02_live_evidence.py` to ensure temporary test challenge/evidence paths resolve relative to `ROOT`.

## Verification Results

1. **Go Unit & Integration Suite**:
   - `go test -count=1 .` in `gateway`: PASSED (`ok github.com/lancet/gateway`).
   - `go test -count=1 ./...` with `TEST_DATABASE_URL` in `gateway`: PASSED (`ok github.com/lancet/gateway/db`).
   - `go vet ./...` in `gateway`: PASSED cleanly with 0 warnings.
   - Unqualified destructive SQL check (`rg -n 'DELETE FROM documents"' . -g '*_test.go'`): PASSED (0 occurrences).

2. **Rust Engine Suite**:
   - `cargo test --manifest-path engine/Cargo.toml`: PASSED (all 55 tests passed across lib, main, inspect_lancedb, and config_startup).

3. **Python Live Evidence & Privacy Gate**:
   - `python -O -I scripts/test_phase02_live_evidence.py`: PASSED (15/15 tests ok).
   - Raw content privacy probe `{"rawContent":"do-not-publish"}`: exited with code 1, reported `raw_content` category, and omitted the submitted value.

4. **Placeholder Gate**:
   - Required path placeholder scan for `[TODO]`: PASSED with 0 markers found.

## Artifacts Produced & Modified

- `gateway/main.go` — Added `maxChunkSize` constant and bounded base-10 32-bit `chunk_size` parsing in `createDocument`.
- `gateway/main_test.go` — Added boundary and status polling regression tests (`TestCreateDocumentChunkSizeBoundaries`, `TestGetDocumentRecoverableStagingRemainsQueued`, `TestGetDocumentNotFoundMarksFailedAfterRustConfirmsAbsence`).
- `gateway/db/document_test.go` — Added `createIsolatedTestPool` helper, updated `TestReconciliationIntentClaimLeaseIsExclusive`, and added `TestReconciliationIntentClaimLeasePreservesUnrelatedDocumentAndIntent`.
- `scripts/test_phase02_live_evidence.py` — Fixed relative path resolution for temporary test challenge/evidence paths against `ROOT`.
- `.planning/phases/02-ingestion-chunking-vector-storage/02-24-SUMMARY.md` — This summary document.
