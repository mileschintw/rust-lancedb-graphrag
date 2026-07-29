# Phase 02 Plan 19 Summary: Gateway Durable Intent Reconciliation

## Objective Executed
Closed CR-03 by wiring the durable intent contract into the gateway's real failure and process lifecycle.

## Changes Implemented

### 1. Gateway Store & Durable Handoff (`gateway/main.go`)
- Extended `documentStore` and implemented intent operations in `postgresStore`:
  - `CreateReconciliationIntent`
  - `ClaimDueReconciliationIntents`
  - `DeleteReconciliationIntent`
  - `RescheduleReconciliationIntent`
  - `GetReconciliationIntent`
- Updated `compensateFailedIngest` to create a `failed_admission` durable intent with a fresh bounded context before running finite request retries.
- Deleted the intent upon terminal status update or when a terminal winner (`completed` or `failed`) is verified.
- Left the intent durable if request retries exhaust, allowing background reconciliation to complete convergence.

### 2. Gateway Background Reconciler Worker (`gateway/main.go`)
- Implemented `durableReconciler` background worker lifecycle:
  - Atomically claims due intent batches with lease expiration (`SKIP LOCKED`).
  - Performs conditional queued-to-failed status updates.
  - Rereads `pgx.ErrNoRows` to preserve terminal winners without overwriting status.
  - Reschedules failed updates with exponential backoff and class-only errors.
  - Per-intent isolation to ensure failing intent items do not starve other due items.
- Wired the reconciler into gateway `main()` with graceful cancelable context lifecycle.

### 3. Verification Suite (`gateway/main_test.go`)
- Updated `fakeStore` to support thread-safe intent storage and mock intent operations.
- Added comprehensive unit test coverage:
  - `TestDurableReconcilerMoreThanFiveFailures`: Verifies intent persistence after 5 failed status retries.
  - `TestDurableReconcilerConvergesWithoutGet`: Verifies autonomous convergence of queued items to failed without client GET requests.
  - `TestDurableReconcilerIgnoresRequestCancellation`: Verifies request context cancellation does not prevent intent creation or status update.
  - `TestDurableReconcilerRestartRecovery`: Verifies background worker restart over persisted intent state.
  - `TestDurableReconcilerPreservesTerminalWinner`: Verifies completed/failed terminal winners are not overwritten.
  - `TestDurableReconcilerBoundedBatchAndBackoff`: Verifies per-intent isolation and exponential backoff on transient errors.
  - `TestDurableReconcilerStopsCleanly`: Verifies worker shutdown on context cancellation without goroutine leaks.

## Test Results

### `go test -count=1 ./...`
```
ok  	github.com/lancet/gateway	1.014s
ok  	github.com/lancet/gateway/db	0.689s
```

All verification criteria for Plan 02-19 are met.
