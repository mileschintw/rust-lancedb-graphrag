---
phase: 02-ingestion-chunking-vector-storage
reviewed: 2026-07-30T03:15:25Z
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
  - gateway/main_test.go
  - gateway/main.go
  - proto/lancet/v1/lancet.proto
  - scripts/phase02_live_evidence.py
  - scripts/test_phase02_live_evidence.py
findings:
  critical: 6
  warning: 2
  info: 0
  total: 8
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-30T03:15:25Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Plans 02-22 through 02-24 close only part of the previous five-finding snapshot. The six locked camel-case aliases are now rejected, the Go and Rust chunk-size ceilings prevent the prior `int32` wrap, the specifically identified table-wide document deletion is gone, and a clean Python run leaves the canonical challenge/evidence paths alone. Shutdown now drains its in-memory receiver.

The phase is still not shippable. Another public-schema integration test leases unrelated reconciliation rows, recovery can deadlock before the worker starts, the selected legacy migration cannot produce a store that normal startup will accept, storage read failures are converted into authoritative absence, and terminal worker failures can leave replayable staging behind after PostgreSQL has committed `failed`. The privacy classifier also echoes an attacker-controlled forbidden key in its failure diagnostic.

The accepted ledger items `DEBT-CR-04`, `DEBT-CR-05`, `DEBT-BU-01`, and `DEBT-BU-02` remain non-blocking under their recorded constraints and are not reclassified here. The findings below are separate current correctness, data-integrity, privacy, and test-isolation defects.

Verification run during review:

- `cargo test --manifest-path engine/Cargo.toml --locked`: passed, 55 tests.
- `go test ./...`: passed, but all PostgreSQL integration tests were skipped because `TEST_DATABASE_URL` was unset.
- `python -O -I scripts/test_phase02_live_evidence.py`: passed, 15 tests, after a clean rerun.
- The required `rawContent` probe exits nonzero. A second probe with a sensitive value embedded in the field key reproduces CR-06 and prints that value.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: A remaining database test leases unrelated public reconciliation intents

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/gateway/db/document_test.go:116-196`

**Issue:** `TestReconciliationIntentRecordAndClaim` still connects directly to `TEST_DATABASE_URL` with the default `public` search path. Its call to `ClaimDueReconciliationIntents` has no document predicate and claims up to ten oldest due rows, updating their `next_attempt_at` to fifteen minutes in the future. Pointing the test at a populated database therefore mutates and temporarily suppresses unrelated reconciliation work. If ten older rows exist, it can also fail without ever claiming its own fixture. Plans 02-24 isolated two lease tests but left this destructive cross-row test on the shared schema.

**Fix:** Run every claim/lease integration test through `createIsolatedTestPool` and create all fixtures through the returned claimant pool. Do not execute a batch claim against the configured public schema.

```go
_, claimantPool, _ := createIsolatedTestPool(t, databaseURL)
q := New(claimantPool)
// Insert and claim only inside the per-test schema.
```

### CR-02: Startup recovery deadlocks when durable staging exceeds queue capacity

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/engine/src/main.rs:1071-1080`

**Issue:** Startup sends every recovered job into the bounded 100-item channel before spawning the worker. Once the channel fills, `sender.send(job).await` waits for a receiver that cannot run because `spawn_worker` is below the loop. A crash can legitimately leave one active staged job plus a full 100-item queue, so 101 acknowledged rows are enough to hang startup permanently before the gRPC listener opens.

**Fix:** Spawn the worker before awaiting recovery sends, retain the requirement that all recovered jobs are admitted before serving gRPC, and fail startup if the worker exits while replay is being enqueued.

```rust
let worker = spawn_worker(receiver, statuses.clone(), database, embedder, shutdown_rx);
for job in staged_jobs {
    statuses.insert(job.document_id.clone(), IngestionStatus::queued());
    sender.send(job).await.map_err(|_| "recovery worker stopped")?;
}
// Only now construct and serve the gRPC service.
```

### CR-03: The legacy staging migration can never yield a normally restartable store

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/engine/src/db/mod.rs:120-136,231-256`; `D:/Repos/lancet/engine/src/main.rs:1066-1068`

**Issue:** `initialize_with_migration` copies legacy rows into `staged_documents_v2` but intentionally leaves the non-empty legacy table unchanged and records no completed migration/disposition marker. Every subsequent production start calls `DatabaseManager::initialize(..., None)`, sees those same legacy rows, and fails again demanding a manifest. Re-running migration also appends the rows to an existing v2 table without conflict checks, creating duplicate document IDs that `read_staged_jobs` later resolves by silently keeping an arbitrary row. The selected transition therefore cannot complete safely across a restart.

**Fix:** Make the transition idempotent and persist an auditable completion state. For example, validate a manifest, reject conflicting v2 IDs, atomically write each migrated row, and record a versioned migration marker containing legacy row IDs/content hashes. Normal initialization should accept a non-empty preserved legacy table only when that marker proves every row was dispositioned. Add tests for normal restart after migration, repeated migration, and v2 ID conflicts.

### CR-04: A staging-table read failure is reported as authoritative NotFound

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/engine/src/main.rs:503-527`; `D:/Repos/lancet/gateway/main.go:562-585`

**Issue:** `get_ingestion_status` uses `if let Ok(count)` and discards every LanceDB error. A timeout, lock error, corrupted query, or transient storage failure falls through to gRPC `NotFound`. The gateway treats `NotFound` as proof that both the registry and durable staging are absent and irreversibly transitions the PostgreSQL row to `failed`. This recreates the exact false-terminal state that staging-aware polling was meant to prevent.

**Fix:** Return `NotFound` only after a successful count of zero. Map count/query failures to `Internal` or `Unavailable`, which the gateway already leaves non-terminal.

```rust
let count = self
    .table
    .count_rows(Some(predicate))
    .await
    .map_err(|error| Status::unavailable(format!("staging status unavailable: {error}")))?;
if count > 0 {
    return Ok(queued_response(id));
}
Err(Status::not_found("document status not found"))
```

### CR-05: Terminal worker failure leaves replayable staging and splits durable status after restart

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/engine/src/main.rs:927-955,1045-1055`; `D:/Repos/lancet/gateway/main.go:592-610`

**Issue:** Staging is deleted only inside the LanceDB replacement path. If embedding fails before replacement begins, the worker publishes terminal `failed` but leaves the staged row. The gateway then persists `failed` in PostgreSQL and stops polling terminal documents. On the next engine restart, `read_staged_jobs` requeues that leftover row; it may complete and write a canonical LanceDB generation while PostgreSQL remains permanently `failed`. A rollback failure that leaves staging has the same split-brain outcome.

**Fix:** Define one durable state machine for retryable versus terminal failures. Either remove staging successfully before publishing terminal `failed`, or keep the engine status non-terminal/recoverable while staging exists and make the gateway continue polling. Add a regression that fails embedding, persists the gateway result, restarts the engine, and proves PostgreSQL and LanceDB converge to the same terminal state.

### CR-06: Privacy failure diagnostics disclose attacker-controlled sensitive field keys

**Classification:** BLOCKER

**File:** `D:/Repos/lancet/scripts/phase02_live_evidence.py:127-136`

**Issue:** The privacy check correctly avoids printing a forbidden field's value, but its error path includes the raw JSON key. Keys are untrusted input and can themselves contain credentials or document content. For example, `{"Bearer do-not-publish":"x"}` exits nonzero but prints `subject.Bearer do-not-publish` to stderr. The retained validation output can therefore disclose exactly the sensitive material the prohibition is intended to exclude.

**Fix:** Never place raw keys in privacy diagnostics. Report only the normalized class and a structural location composed from safe container/index tokens, and add a subprocess test with a secret-bearing key.

```python
require(
    category is None,
    f"forbidden privacy field class '{category}' below '{path}'",
)
```

## Warnings

### WR-01: Global fixture cleanup violates per-run ownership and can break concurrent suites

**Classification:** WARNING

**File:** `D:/Repos/lancet/scripts/test_phase02_live_evidence.py:159-165`

**Issue:** `tearDownClass` globs every `.phase02-live-test-*` entry in the shared scripts directory and unlinks it, including files owned by another concurrent test process. It also calls `Path.unlink()` on matching directories, which raises instead of cleaning them. The clean suite passes only when no concurrent or interrupted fixture remains; a leftover matching directory reproduced a teardown error during review.

**Fix:** Track only paths created by the current test process and clean those exact paths through `addCleanup`/context managers. Remove the shared-directory glob entirely.

### WR-02: Isolation assertions ignore database query failures and can false-pass

**Classification:** WARNING

**File:** `D:/Repos/lancet/gateway/db/document_test.go:256-258,325-329,342-344,444-448`

**Issue:** Both isolated lease tests discard errors while reading public table counts. If permissions, schema resolution, or connectivity make both the before and after reads fail, all count variables remain zero and the assertion passes without proving public data was preserved.

**Fix:** Fail immediately on every snapshot query error before comparing counts.

```go
if err := adminPool.QueryRow(ctx, "SELECT count(*) FROM public.documents").
    Scan(&initialPublicDocCount); err != nil {
    t.Fatalf("snapshot public documents: %v", err)
}
```

---

_Reviewed: 2026-07-30T03:15:25Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
