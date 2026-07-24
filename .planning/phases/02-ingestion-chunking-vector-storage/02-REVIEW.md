---
phase: 02
phase_name: ingestion-chunking-vector-storage
status: issues_found
depth: standard
files_reviewed: 28
findings:
  critical: 0
  warning: 3
  info: 1
  total: 4
reviewed_at: 2026-07-24T16:27:00-07:00
---

# Phase 02 Code Review

## Scope

Reviewed the 28 existing source/config files changed by Phase 02, derived from the phase commit range and SUMMARY artifacts. Generated protobuf/sqlc outputs were checked for consistency with their source definitions. Automated evidence:

- `cargo test --manifest-path engine/Cargo.toml`: 20 passed
- `cargo build --manifest-path engine/Cargo.toml`: passed
- `go test -v ./...` from `gateway/`: passed (database integration test skipped without `TEST_DATABASE_URL`)
- `go build ./...` and `go vet ./...` from `gateway/`: passed
- `sqlc generate`: generated output remained consistent
- `cargo clippy --all-targets -- -D warnings`: one test-only style finding

## Findings

### WR-01 — Failed engine enqueue leaves an indefinitely queued PostgreSQL row

- **Severity:** Warning
- **File:** `gateway/main.go:205`
- **Category:** Correctness / recovery

The gateway inserts the document row before calling `engine.Ingest`. When the engine rejects a full queue or ingestion fails, the handler returns 429/502 but leaves the PostgreSQL row in `queued`. Since the caller receives no accepted document response or polling location, that row has no normal path to a terminal status and accumulates as orphaned metadata.

**Recommendation:** On ingestion failure, either delete the newly inserted row in a compensating transaction or update it to `failed` with the engine error. Add tests for both queue-full and generic gRPC failure persistence behavior.

### WR-02 — Concurrent terminal polls can turn a successful completion into HTTP 500

- **Severity:** Warning
- **Files:** `gateway/main.go:241`, `gateway/db/query.sql:40`
- **Category:** Concurrency

The conditional update correctly avoids overwriting an already-terminal row, but it returns no row once another request wins the update race. A second concurrent poll then receives `pgx.ErrNoRows` from `UpdateStatus` and maps it to HTTP 500, even though the document has successfully reached a terminal state.

**Recommendation:** Treat `pgx.ErrNoRows` as a reconciliation race and re-read the document, returning the existing terminal row. Add a store/handler test that simulates the lost update race.

### WR-03 — Cross-table replacement does not meet the plan's atomic-upsert contract

- **Severity:** Warning
- **File:** `engine/src/main.rs:342`
- **Category:** Data integrity

`replace_document` deletes edges, nodes, and the raw document in separate LanceDB operations, then inserts the replacement document, nodes, and edges in separate operations. Any failure after the first delete can discard the previously valid indexed representation and leave a partial replacement. The worker reports `failed`, but the plan explicitly requires an atomic upsert.

**Recommendation:** Use a single-table/versioned write model with a commit marker, or stage replacement rows under an ingestion version and switch the active version only after every batch succeeds. If LanceDB cannot provide a cross-table transaction, document the weaker retry-repair guarantee and add failure-injection tests at each write boundary.

### IN-01 — Clippy strict mode fails on a test helper

- **Severity:** Info
- **File:** `engine/src/client/tests.rs:103`
- **Category:** Maintainability

`cargo clippy --all-targets -- -D warnings` flags `repeat("0.25").take(2048)` as `manual_repeat_n`.

**Recommendation:** Replace it with `std::iter::repeat_n("0.25", 2048)` so the strict lint gate passes.

## Security Review

- UUIDv4 validation prevents document IDs from injecting LanceDB predicates or path-like content.
- Upload size limits and queue reservation are enforced before Rust durable staging.
- OpenRouter credentials are read from the environment and are not logged or included in errors.
- No critical or high-severity security finding was identified at standard depth.

## Verdict

The phase builds and its automated suites pass, but three correctness/data-integrity warnings should be addressed before treating ingestion as production-safe. None is a high-severity security blocker under the configured ASVS gate.
