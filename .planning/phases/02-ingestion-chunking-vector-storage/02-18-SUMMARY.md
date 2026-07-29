# Phase 02-18 Summary: Durable PostgreSQL Reconciliation Contract (CR-03)

## Accomplishments

1. **Durable Intent Schema (`document_reconciliation_intents`)**
   - Declared canonical Atlas HCL table in `gateway/db/schema.hcl` and updated DDL in `gateway/db/schema.sql`.
   - Table fields: `document_id` (PK, FK to `documents(id)` ON DELETE CASCADE), `desired_status` (CHECK = 'failed'), `reason_class`, `retry_count` (CHECK >= 0), `next_attempt_at`, `last_error_class`, `created_at`, `updated_at`.
   - Migration applied to live PostgreSQL via `atlas schema apply --env local --auto-approve`.

2. **Typed sqlc Query Surface**
   - Added queries in `gateway/db/query.sql`:
     - `CreateReconciliationIntent`: Conditional insert/upsert while document status is `queued`.
     - `ClaimDueReconciliationIntents`: Atomic claim with `FOR UPDATE SKIP LOCKED` returning bounded batch.
     - `RescheduleReconciliationIntent`: Reschedule with incremented `retry_count`, new `next_attempt_at`, and class-only `last_error_class`.
     - `DeleteReconciliationIntent`: Conditional delete after document reaches terminal status (`completed` or `failed`).
     - `GetReconciliationIntent`: Diagnostic single-intent reader.
   - Generated Go query contract in `gateway/db/models.go` and `gateway/db/query.sql.go` using `sqlc v1.31.1`.

3. **Behavioral PostgreSQL Lifecycle Tests**
   - Implemented real PostgreSQL integration tests in `gateway/db/document_test.go`:
     - `TestReconciliationIntentRecordAndClaim`: Proves conditional creation of failed-admission intent and atomic lease advancement.
     - `TestReconciliationIntentClaimLeaseIsExclusive`: Proves two concurrent claimers cannot claim the same intent before lease expiry.
     - `TestReconciliationIntentPersistsAcrossPoolRestart`: Proves intent survives process restart across distinct database pool connections.
     - `TestReconciliationIntentReschedulesAndCompletes`: Proves retry incrementing, last error tracking, terminal status requirement for deletion, and deletion idempotency.

## Verification Results

```bash
cmd /c "set TEST_DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&& go test -count=1 -v ./... && go vet ./..."
```

Output:
```
=== RUN   TestDocumentQueries
--- PASS: TestDocumentQueries (0.01s)
=== RUN   TestConditionalTerminalUpdateRace
--- PASS: TestConditionalTerminalUpdateRace (0.01s)
=== RUN   TestReconciliationIntentRecordAndClaim
--- PASS: TestReconciliationIntentRecordAndClaim (0.03s)
=== RUN   TestReconciliationIntentClaimLeaseIsExclusive
--- PASS: TestReconciliationIntentClaimLeaseIsExclusive (0.04s)
=== RUN   TestReconciliationIntentPersistsAcrossPoolRestart
--- PASS: TestReconciliationIntentPersistsAcrossPoolRestart (0.02s)
=== RUN   TestReconciliationIntentReschedulesAndCompletes
--- PASS: TestReconciliationIntentReschedulesAndCompletes (0.02s)
PASS
ok  	github.com/lancet/gateway/db	0.813s
```
