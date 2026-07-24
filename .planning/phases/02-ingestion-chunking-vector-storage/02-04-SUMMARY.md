---
phase: 02-ingestion-chunking-vector-storage
plan: 04
subsystem: ingestion
tags: [tokio, grpc, lancedb, openrouter, postgres, polling]

requires:
  - phase: 02-03
    provides: OpenRouter embeddings client, LanceDB schemas, and exact-match entity resolver
provides:
  - Sequential background indexing from queued raw documents to embedded LanceDB nodes and edges
  - UUIDv4-safe ingestion with replacement semantics and graceful worker shutdown
  - Gateway status polling with transactional terminal-state reconciliation
  - End-to-end upload, poll, and PostgreSQL verification script
affects: [retrieval, graph-rag, ingestion-observability]

tech-stack:
  added: [uuid]
  patterns:
    - Single-consumer Tokio ingestion with dependency-injected embeddings
    - Terminal-only gateway status reconciliation
    - Delete-dependent-rows-first document replacement

key-files:
  created:
    - verify-ingestion.sh
  modified:
    - engine/src/main.rs
    - engine/src/client/mod.rs
    - engine/src/db/mod.rs
    - engine/Cargo.toml
    - engine/Cargo.lock
    - gateway/main.go
    - gateway/main_test.go
    - gateway/db/query.sql
    - gateway/db/query.sql.go

key-decisions:
  - "Keep durable raw-content staging in the gRPC handler after queue reservation, then let the single worker replace all document, node, and edge rows as one ordered indexing operation."
  - "Persist only completed or failed engine states in PostgreSQL; queued and processing remain live engine states until terminal reconciliation."
  - "Generate and validate RFC 4122 UUIDv4 document IDs at both gateway and engine boundaries."

patterns-established:
  - "Indexing stage spans: chunk_document, embed_document, and persist_document carry the document ID."
  - "Worker shutdown is observed between jobs, so an active document always reaches a terminal status before exit."

requirements-completed: [DATA-01, RAG-06]

coverage:
  - id: D1
    description: "Queued documents are chunked, embedded with concurrency capped at five, entity-resolved, and replacement-written to LanceDB by one background consumer."
    requirement: RAG-06
    verification:
      - kind: integration
        ref: "cargo test --manifest-path engine/Cargo.toml (20 passed)"
        status: pass
      - kind: other
        ref: "cargo build --manifest-path engine/Cargo.toml"
        status: pass
    human_judgment: false
  - id: D2
    description: "GET /documents/{id} polls queued/processing documents and transactionally persists completed or failed status, chunk count, and error text."
    requirement: DATA-01
    verification:
      - kind: unit
        ref: "gateway/main_test.go#TestGetDocumentPollsAndPersistsNonTerminalStatus"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestGetDocumentDoesNotPersistNonTerminalEngineStatus"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestGetDocumentPersistsFailedStatusAndError"
        status: pass
      - kind: other
        ref: "go test -v ./... and go build ./... (gateway)"
        status: pass
    human_judgment: false
  - id: D3
    description: "verify-ingestion.sh uploads a sample, polls the returned document location, and checks the final PostgreSQL row."
    requirement: DATA-01
    verification:
      - kind: other
        ref: "bash -n verify-ingestion.sh"
        status: pass
    human_judgment: true
    rationale: "A live run requires PostgreSQL, the gateway and engine processes, a network-reachable OpenRouter endpoint, and a valid OPENROUTER_API_KEY."

duration: 25 min
completed: 2026-07-24
status: complete
---

# Phase 2 Plan 4: Async Background Indexing & Status Polling Summary

**Sequential Tokio indexing now turns queued UUIDv4 documents into embedded LanceDB graph rows, while the Go gateway reconciles terminal engine status into PostgreSQL.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-24T15:57:00-07:00
- **Completed:** 2026-07-24T16:22:13-07:00
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Completed the single-consumer Rust indexing pipeline with structure-aware/fixed chunking, bounded OpenRouter embeddings, exact-match section resolution, node/edge persistence, replacement cleanup, failure status, and active-job-safe shutdown.
- Completed gateway polling so only terminal engine results are written transactionally to PostgreSQL, with UUIDv4-compatible upload IDs and a returned polling location.
- Added an executable end-to-end script that uploads a document, waits for completion, checks chunk count, and validates PostgreSQL state.

## Task Commits

Each task was committed atomically:

1. **Task 1: Complete Tokio background worker pipeline in Rust engine** - `a287c24` (feat)
2. **Task 2: Implement polling endpoints and database updates in Go Gateway** - `d6cdf08` (feat)

## Files Created/Modified

- `verify-ingestion.sh` - Upload/poll/database-state end-to-end validator.
- `engine/src/main.rs` - UUID validation, indexing orchestration, LanceDB replacement batches, stage tracing, status transitions, and shutdown behavior.
- `engine/src/client/mod.rs` - Ownership-safe bounded embedding stream and exported model metadata.
- `engine/src/db/mod.rs` - Validated nodes and edges table accessors.
- `engine/Cargo.toml` / `engine/Cargo.lock` - UUIDv4 validation/generation support.
- `gateway/main.go` - UUIDv4 IDs, polling location, and terminal-only status reconciliation.
- `gateway/main_test.go` - Upload ID/location and terminal/non-terminal polling coverage.
- `gateway/db/query.sql` / `gateway/db/query.sql.go` - Conditional terminal update that refuses to overwrite an already terminal row.

## Decisions Made

- Retained durable raw-document staging after queue-capacity reservation. The worker then performs ordered dependent-row deletion and replacement, preserving the earlier no-orphan queue decision while making re-ingestion idempotent.
- Kept queued and processing as engine-owned live states. PostgreSQL changes only when the engine reports completed or failed.
- Used dependency injection for embeddings in worker tests, allowing real LanceDB persistence and shutdown behavior to be verified without transmitting credentials.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Made document IDs valid UUIDv4 values across both runtimes**
- **Found during:** Task 1 and Task 2 integration
- **Issue:** The gateway generated unhyphenated random hex IDs, while the plan's path-injection mitigation required strict UUIDv4 validation in Rust.
- **Fix:** Added RFC 4122 UUIDv4 generation in Go and UUIDv4 parsing/version/variant validation in Rust.
- **Files modified:** `gateway/main.go`, `gateway/main_test.go`, `engine/src/main.rs`, `engine/Cargo.toml`, `engine/Cargo.lock`
- **Verification:** Rust UUID rejection test and Go UUID format assertion pass.
- **Committed in:** `a287c24`, `d6cdf08`

**2. [Rule 3 - Blocking] Exposed validated persistence dependencies needed by the worker**
- **Found during:** Task 1
- **Issue:** The planned worker could not open the validated nodes/edges tables or record the embedding model through the existing private interfaces.
- **Fix:** Added DatabaseManager table accessors, exported the client model identifier, and adjusted the embedding stream to own request data safely.
- **Files modified:** `engine/src/db/mod.rs`, `engine/src/client/mod.rs`
- **Verification:** Rust build and all 20 tests pass.
- **Committed in:** `a287c24`

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 blocking).
**Impact on plan:** Both changes were required for secure cross-runtime integration and executable persistence; no unrelated scope was added.

## Issues Encountered

- The live end-to-end script was not executed because the current task did not have a running PostgreSQL/gateway/engine stack or an OpenRouter API key. Its Bash syntax passes, and the component integration paths are covered by automated Rust and Go tests.
- The Go database integration test correctly skipped because `TEST_DATABASE_URL` was not set; handler/store transaction behavior and SQL generation were still verified.

## User Setup Required

None - no new configuration beyond the previously documented `OPENROUTER_API_KEY` and existing local service configuration.

## Next Phase Readiness

- Phase 2 has all four plan summaries and is ready for phase-level code review, regression checks, and verification.
- Live ingestion UAT should run `./verify-ingestion.sh` after PostgreSQL, the Rust engine, and the Go gateway are started with a valid OpenRouter key.

## Self-Check: PASSED

- Key files exist: `engine/src/main.rs`, `gateway/main.go`, and `verify-ingestion.sh`.
- Task commits exist: `a287c24` and `d6cdf08`.
- Rust: 20 tests passed; build passed.
- Go: handler/package tests passed; build passed; database integration test skipped only for missing `TEST_DATABASE_URL`.
- Capability gates: schema drift, codebase drift, and UI safety all non-blocking/passed.

---
*Phase: 02-ingestion-chunking-vector-storage*
*Completed: 2026-07-24*
