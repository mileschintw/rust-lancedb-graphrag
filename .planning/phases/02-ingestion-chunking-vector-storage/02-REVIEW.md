---
phase: 02-ingestion-chunking-vector-storage
reviewed: 2026-07-29T10:51:54Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - config/config.toml
  - config/config.verify.toml
  - engine/Cargo.lock
  - engine/Cargo.toml
  - engine/src/bin/inspect_lancedb.rs
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
  - engine/src/db/mod.rs
  - engine/src/db/tests.rs
  - engine/src/inspect_lancedb_tests.rs
  - engine/src/main.rs
  - engine/src/tests.rs
  - gateway/db/document_test.go
  - gateway/db/query.sql
  - gateway/db/query.sql.go
  - gateway/db/schema.hcl
  - gateway/db/schema.sql
  - gateway/go.mod
  - gateway/go.sum
  - gateway/main.go
  - gateway/main_test.go
  - proto/lancet/v1/lancet.proto
  - scripts/phase02_live_evidence.py
  - scripts/test_phase02_live_evidence.py
findings:
  critical: 3
  warning: 2
  info: 0
  total: 5
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-29T10:51:54Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

The supplied Phase 02 implementation has three ship-blocking defects: its privacy gate can be bypassed with camel-case sensitive-field names, a database integration test can erase every document in the configured database, and graceful engine shutdown abandons queued documents that have already been acknowledged to clients. Two further robustness issues affect chunk-setting integrity and test isolation.

The privacy bypass was reproduced directly: piping `{"rawContent":"do-not-publish"}` to `check-privacy` exited successfully and printed `privacy prohibition check: PASS`.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Camel-case sensitive fields bypass the privacy prohibition

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/scripts/phase02_live_evidence.py:110-115,122-134`

**Issue:** `classify_sensitive_field` only lowercases and replaces non-alphanumeric separators. It does not split camel-case, so `rawContent`, `storedDocumentText`, `authorizationHeader`, and `bearerToken` normalize to values such as `rawcontent`, which do not contain the underscore-form keywords. The recursive checker then accepts these fields and their values. This defeats the required fail-closed privacy guard for JSON artifacts.

**Fix:** Canonicalize both camel-case and separators before matching, and add negative tests for each camel-case alias.

```python
snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()
canonical = re.sub(r"[^a-z0-9]", "", snake)

if "rawcontent" in canonical:
    return "raw_content"
```

### CR-02: Database integration test deletes all documents in the configured database

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/gateway/db/document_test.go:196-218`

**Issue:** `TestReconciliationIntentClaimLeaseIsExclusive` executes `DELETE FROM documents` without a predicate or transaction. With `TEST_DATABASE_URL` set, this deletes every document in that database and cascades its reconciliation intents. A mispointed environment variable therefore turns an ordinary test run into production data loss.

**Fix:** Never clear a shared table in a test. Run the test against an isolated temporary database/schema, or constrain setup and cleanup to UUIDs created by that test.

```go
// Do not issue DELETE FROM documents.
t.Cleanup(func() {
    _, _ = pool.Exec(context.Background(), "DELETE FROM documents WHERE id = $1", docID)
})
```

### CR-03: Graceful shutdown drops acknowledged queued ingestions

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/engine/src/main.rs:867-881,931-959`; `D:/Repos/lancet/gateway/main.go:548-578`

**Issue:** The worker's biased `select!` chooses the shutdown notification before `receiver.recv()` and breaks immediately. Any jobs already sitting in the channel have been accepted by `ingest_document` and persisted only as staged raw bytes, but are never processed. On restart the in-memory status map is empty; a later gateway poll treats the engine `NotFound` as authoritative and marks the PostgreSQL document as `failed`. The only shutdown test covers one active job, not queued jobs, so this permanent loss of acknowledged work is untested.

**Fix:** Drain work accepted before shutdown and implement startup recovery that requeues durable staged rows. Do not mark an engine `NotFound` as terminal while a matching durable staging record exists.

```rust
// Stop new sends, then use the existing status-processing body to drain the queue.
receiver.close();
while let Some(job) = receiver.recv().await {
    process_and_record_status(job).await;
}
```

## Warnings

### WR-01: Unbounded chunk size wraps when persisted to PostgreSQL

**Classification:** WARNING

**File:** `D:/Repos/lancet/gateway/main.go:478-515`; `D:/Repos/lancet/engine/src/main.rs:122-157`

**Issue:** The gateway accepts every positive machine-sized integer, then casts it to `int32` for `InsertDocumentParams`. On normal 64-bit builds, `chunk_size=2147483648` passes validation and is stored as a negative `chunk_size`, while the Rust service receives and accepts the original positive value as `usize`. The persisted ingestion settings therefore no longer describe the chunking that ran, and an extremely large requested size is not bounded.

**Fix:** Parse to a bounded integer before the cast, enforce the same explicit maximum in Rust, and add boundary tests.

```go
parsed, err := strconv.ParseInt(reqSize, 10, 32)
if err != nil || parsed < 1 || parsed > maxChunkSize {
    http.Error(w, "invalid chunk_size", http.StatusBadRequest)
    return
}
chunkSize := int(parsed)
```

### WR-02: Live-evidence test overwrites and deletes real runtime artifacts

**Classification:** WARNING

**File:** `D:/Repos/lancet/scripts/test_phase02_live_evidence.py:481-489,570-572`

**Issue:** `test_captured_inspector_arguments_explicit_path` writes directly to the real Phase 02 challenge/evidence runtime paths, then unconditionally unlinks both in `finally`. Running the test concurrently with a human verification run can overwrite or delete that run's evidence, making the test destructive and flaky.

**Fix:** Execute the shell test in an isolated fixture checkout or parameterize the runtime-artifact paths so the test can use a temporary directory. At minimum, save and restore any pre-existing files rather than deleting them.

---

_Reviewed: 2026-07-29T10:51:54Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
