---
phase: 02-ingestion-chunking-vector-storage
reviewed: 2026-07-30T09:43:51Z
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
  critical: 4
  warning: 3
  info: 0
  total: 7
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-30T09:43:51Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

The 24 scoped source, configuration, dependency, protocol, and test files were reviewed in full at standard depth. The current implementation fixes the previous report's literal defects, including isolated PostgreSQL claim tests, staging-query error propagation, retained replay state after a worker deletion failure, and redacted privacy diagnostics. It still contains four ship-blocking correctness or evidence-integrity defects and three robustness warnings.

The most serious risks are a completed canonical ingestion being downgraded to failed after an engine restart, replay state being destroyed after an incomplete rollback, a failed admission being stranded without a durable reconciliation intent, and an attestation CLI that records human approval even when no approval flag was supplied.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: A completed canonical ingestion can be downgraded to failed after engine restart

**Classification:** BLOCKER
**Files:** `D:/Repos/lancet/engine/src/main.rs:508-538`, `D:/Repos/lancet/engine/src/main.rs:902-904`, `D:/Repos/lancet/engine/src/main.rs:1045-1053`, `D:/Repos/lancet/gateway/main.go:562-582`
**Issue:** Successful replacement deletes its durable staging row before the worker publishes `completed` into the process-local `DashMap`. `get_ingestion_status` consults that volatile map and then only the staging table; it never checks the canonical documents or nodes tables. If the engine stops after the canonical writes and staging deletion but before the gateway persists the terminal result—or simply restarts before the gateway next polls—the map is lost and the status RPC returns `NotFound`. The gateway treats that response as authoritative absence and changes the still-queued/processing PostgreSQL row to `failed`, even though the canonical LanceDB generation completed successfully.

**Fix:** Persist terminal ingestion outcome durably, or make the status RPC check canonical document/node state after staging is absent and return `completed` with the authoritative node count. Return `NotFound` only after volatile status, staging, and canonical state all confirm absence. Add a cross-runtime regression that completes the canonical mutation, restarts Rust before the gateway poll, and asserts PostgreSQL converges to `completed` with the canonical chunk count.

### CR-02: Rollback failure destroys replay state and can leave partial canonical data terminally failed

**Classification:** BLOCKER
**File:** `D:/Repos/lancet/engine/src/main.rs:629-667`, `D:/Repos/lancet/engine/src/main.rs:1056-1079`
**Issue:** `rollback_replacement` records errors from the three `restore_version` calls but attempts to delete staging regardless. Its caller then handles every processing error with another unconditional staging deletion and publishes terminal `failed` when that deletion succeeds. If any canonical table restoration fails while another succeeds, the durable replay row can therefore be removed while documents, nodes, and edges represent different generations. The worker then exposes this split state as a terminal failure with no remaining input from which startup replay can converge.

**Fix:** Treat incomplete restoration as a distinct replayable/fatal outcome. Do not delete staging when any canonical restore fails, and make the worker skip its generic staging deletion and terminal publication for that outcome. Add an injectable `restore_version` failure test that proves staging remains present, no terminal state is published, and a restarted worker can replay to a consistent generation.

### CR-03: Failed admission can be stranded queued without any durable reconciliation intent

**Classification:** BLOCKER
**File:** `D:/Repos/lancet/gateway/main.go:275-319`
**Issue:** `compensateFailedIngest` attempts `CreateReconciliationIntent` once and discards its error, then makes only five synchronous status-update attempts. A PostgreSQL interruption that begins after the original queued document insert can make both the intent insert and all five updates fail. The handler then returns with a durable queued document but no reconciliation intent for the background claimant. Recovery depends on a future GET even though the reconciliation design promises convergence independent of polling.

**Fix:** Create the queued document and its potential reconciliation obligation atomically, or retry/require successful durable intent persistence before finite compensation exits. The function may return once either the terminal status is persisted or an intent that the reconciler can claim is confirmed durable. Add a regression combining `createIntentErr` with five update failures, restore the database, run the reconciler without issuing GET, and assert convergence to `failed`.

### CR-04: The evidence helper forges human approval when the approval flag is omitted

**Classification:** BLOCKER
**Files:** `D:/Repos/lancet/scripts/phase02_live_evidence.py:616-620`, `D:/Repos/lancet/scripts/phase02_live_evidence.py:669-676`, `D:/Repos/lancet/scripts/phase02_live_evidence.py:761-765`, `D:/Repos/lancet/scripts/test_phase02_live_evidence.py:699-758`
**Issue:** Both `build_attestation` and the CLI argument default `human_approved` to true. Because `--human-review-approved` is a `store_true` argument whose default is already true, omitting the flag is indistinguishable from explicit approval. The success-path test invokes the gate without the approval flag and expects an attestation to be retained, codifying the bypass. An automated caller can therefore manufacture `human_disclosure_review.approved=true` and the named blocking-checkpoint provenance without a human decision.

**Fix:** Default the function parameter and parser destination to false and reject attestation construction unless explicit approval was supplied:

```python
build_att.add_argument(
    "--human-review-approved",
    dest="human_approved",
    action="store_true",
    default=False,
)
require(human_approved, "explicit human disclosure approval is required")
```

Add a negative gate test that omits the flag, expects failure, preserves the source evidence, and produces no replacement attestation. The success test must pass the flag only after the blocking human checkpoint.

## Warnings

### WR-01: Test cleanup can delete another process's fixtures and overwrite caller-owned files

**Classification:** WARNING
**File:** `D:/Repos/lancet/scripts/test_phase02_live_evidence.py:165-170`, `D:/Repos/lancet/scripts/test_phase02_live_evidence.py:640-655`, `D:/Repos/lancet/scripts/test_phase02_live_evidence.py:670-704`, `D:/Repos/lancet/scripts/test_phase02_live_evidence.py:760-765`
**Issue:** `tearDownClass` deletes every `.phase02-live-test-*` entry in the shared scripts directory rather than only resources owned by this process. Concurrent test runs can delete one another's fixtures, and a leftover matching directory makes `unlink` fail. The alleged foreign-fixture regression removes its file via `addCleanup` before class teardown, so it never tests the dangerous sweep. Other tests also use fixed `.test-caller-sample.tmp` and attestation filenames, overwriting and later deleting any pre-existing or concurrently owned file at those paths.

**Fix:** Remove the class-wide glob and allocate every fixture under a process/test-specific `TemporaryDirectory`, retaining exact owned paths for cleanup. Use unique temporary paths for caller samples and attestations. Exercise cleanup ownership through a dedicated cleanup helper or a subprocess so the assertion occurs after the cleanup operation being tested.

### WR-02: Empty uploads become durable failed jobs and a misleading 502 response

**Classification:** WARNING
**Files:** `D:/Repos/lancet/gateway/main.go:208-249`, `D:/Repos/lancet/gateway/main.go:512-545`, `D:/Repos/lancet/engine/src/main.rs:457-483`
**Issue:** The Go client sends its first metadata-bearing stream frame only when the reader yields bytes. An empty upload therefore closes a zero-message stream, which Rust rejects as `InvalidArgument("empty ingestion stream")`. The HTTP handler does not reject a zero-byte multipart file before inserting it, so a client input error creates a queued row, compensates it to failed, and returns 502 as if the engine were unavailable.

**Fix:** Define empty-document behavior explicitly. If unsupported, reject `header.Size == 0` with HTTP 400 before `Insert`. If supported, send an explicit first frame containing metadata and empty data, and teach Rust to accept it. Add handler and gRPC-stream regressions for the chosen contract.

### WR-03: Cross-runtime recovery tests can hang indefinitely on failure

**Classification:** WARNING
**Files:** `D:/Repos/lancet/engine/src/tests.rs:731-735`, `D:/Repos/lancet/engine/src/tests.rs:752-755`, `D:/Repos/lancet/engine/src/tests.rs:795-799`, `D:/Repos/lancet/engine/src/tests.rs:1422-1465`, `D:/Repos/lancet/engine/src/tests.rs:1490-1497`, `D:/Repos/lancet/gateway/main_test.go:1166-1170`, `D:/Repos/lancet/gateway/main_test.go:1219-1223`
**Issue:** Multiple Rust test and fixture loops poll state or stop files without any deadline. In the D04 fixture, the stop-file watcher is not started until after the unbounded pre-server state loop. If startup never reaches serving, the Go test eventually fails its bounded ping loop, but its deferred `cmd.Wait()` can then block forever because writing the stop file cannot affect a watcher that was never launched.

**Fix:** Wrap every Rust polling loop in `tokio::time::timeout`, launch stop/cancellation observation before recovery waits, and have Go start the child with a context deadline plus a bounded wait/kill fallback. Tests should fail with the unresolved state and child output rather than deadlock the suite.

## Validation Evidence

- `cargo test --manifest-path engine/Cargo.toml --locked` passed all 60 Rust tests.
- `go test ./...` passed all Go package suites. PostgreSQL-backed integration cases were not exercised because `TEST_DATABASE_URL` was unset.
- `python -O -I scripts/phase02_live_evidence.py self-test` passed.
- The full Python live-evidence suite was not run because WR-01 proves its current shared-path teardown is destructive under concurrent or pre-existing fixtures.

---

_Reviewed: 2026-07-30T09:43:51Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
