---
phase: 02-ingestion-chunking-vector-storage
plan: 01
subsystem: ingestion
tags: [postgresql, sqlc, atlas, grpc, lancedb, tokio, chi, viper]

requires:
  - phase: 01-basic-gateway-rust-engine-ping
    provides: Go HTTP gateway, Rust tonic engine, and shared protobuf service
provides:
  - PostgreSQL document metadata schema and parameterized sqlc queries
  - Multipart document upload and status APIs backed by the Rust engine
  - LanceDB raw-document persistence with a bounded sequential Tokio worker
affects: [02-02, 02-03, 02-04, ingestion, chunking, vector-storage]

tech-stack:
  added: [viper, config-rs, dashmap, lancedb, arrow-array, arrow-schema]
  patterns: [transactional metadata writes, 64KB grpc client streaming, bounded queue admission, in-memory ingestion registry]

key-files:
  created:
    - config/config.toml
    - config/config.dev.toml
    - gateway/db/document_test.go
    - gateway/main_test.go
    - .planning/phases/02-ingestion-chunking-vector-storage/02-USER-SETUP.md
  modified:
    - gateway/db/schema.hcl
    - gateway/db/schema.sql
    - gateway/db/query.sql
    - gateway/main.go
    - proto/lancet/v1/lancet.proto
    - engine/src/main.rs

key-decisions:
  - "Reserve bounded Tokio queue capacity before LanceDB persistence so rejected uploads cannot create orphaned raw documents."
  - "Use a shared base TOML plus LANCET_ENV overlays and double-underscore environment overrides in both runtimes."
  - "Keep ingestion status in an Arc<DashMap> while PostgreSQL remains the durable gateway-facing metadata store."

patterns-established:
  - "Gateway persistence operations that change document state run in explicit pgx transactions through sqlc-generated queries."
  - "Upload bytes cross the gateway-engine boundary in fixed 64KB gRPC stream messages and are admitted through a capacity-100 queue."

requirements-completed: [DATA-01, DATA-02]

coverage:
  - id: D1
    description: "PostgreSQL document metadata schema and parameterized insert, update, and lookup queries"
    requirement: DATA-01
    verification:
      - kind: integration
        ref: "gateway/db/document_test.go#TestDocumentQueries"
        status: pass
      - kind: other
        ref: "atlas schema apply --env local --auto-approve"
        status: pass
      - kind: other
        ref: "sqlc generate"
        status: pass
    human_judgment: false
  - id: D2
    description: "Multipart upload and status APIs stream documents to LanceDB and persist terminal worker status"
    requirement: DATA-01
    verification:
      - kind: integration
        ref: "gateway/main_test.go#TestCreateDocumentMapsFullQueueTo429"
        status: pass
      - kind: integration
        ref: "gateway/main_test.go#TestGetDocumentPollsAndPersistsNonTerminalStatus"
        status: pass
      - kind: manual_procedural
        ref: "live gateway-engine upload/status smoke test"
        status: pass
    human_judgment: false
  - id: D3
    description: "Capacity-100 sequential worker records processing/completed states and mock chunk counts"
    requirement: DATA-02
    verification:
      - kind: unit
        ref: "engine/src/main.rs#worker_completes_jobs_and_records_mock_chunks"
        status: pass
      - kind: unit
        ref: "engine/src/main.rs#bounded_queue_rejects_work_when_full"
        status: pass
    human_judgment: false

duration: 1h 16m
completed: 2026-07-19
status: complete
---

# Phase 2 Plan 1: Ingestion Database & gRPC Scaffolding Summary

**Transactional PostgreSQL metadata, bounded gRPC-to-LanceDB ingestion, and pollable background-worker status now form a working end-to-end document path.**

## Performance

- **Duration:** 1h 16m
- **Started:** 2026-07-19T05:06:23Z
- **Completed:** 2026-07-19T06:22:12Z
- **Tasks:** 2
- **Files modified:** 21

## Accomplishments

- Added the `documents` schema and compiled parameterized sqlc operations for queued insertion, status changes, and lookup.
- Added size-limited multipart upload and status endpoints that stream 64KB chunks to the Rust engine and map queue exhaustion to HTTP 429.
- Added LanceDB raw-file persistence, bounded queue admission, status tracking, sequential mock indexing, configuration overlays, and graceful worker draining.

## Task Commits

Each task was committed atomically:

1. **Task 1: Define PostgreSQL documents metadata schema and compile queries** - `c8738d6` (feat)
2. **Task 2: Implement end-to-end ingestion flow scaffolding** - `452cbcb` (feat)

## Files Created/Modified

- `gateway/db/schema.hcl`, `gateway/db/schema.sql` - matching PostgreSQL document metadata definitions.
- `gateway/db/query.sql`, generated Go DB files - parameterized insert, update, and lookup operations.
- `gateway/db/document_test.go` - transaction-rolled-back database integration coverage.
- `gateway/main.go`, `gateway/main_test.go` - HTTP upload/status handlers, gRPC client streaming, and routing tests.
- `proto/lancet/v1/lancet.proto` and generated bindings - ingestion-status RPC contract for Go and Rust.
- `engine/src/main.rs` - LanceDB persistence, bounded queue, state registry, worker, and graceful shutdown.
- `config/config.toml`, `config/config.dev.toml` - shared local and development runtime settings.

## Decisions Made

- Queue capacity is reserved before raw data is written, preventing a rejected full-queue request from leaving an orphaned LanceDB record.
- Configuration uses `config.toml` as a base, optional `config.<LANCET_ENV>.toml` overlays, and `LANCET_*` double-underscore nested overrides in both runtimes.
- PostgreSQL is the durable API metadata source; the Rust registry supplies live non-terminal status until later persistence work replaces it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Replaced incompatible handwritten protobuf status shim**
- **Found during:** Task 2 generated-binding audit
- **Issue:** The uncommitted Go status messages used a legacy handwritten protobuf interface and were absent from the file descriptor.
- **Fix:** Re-ran Buf generation with the configured official plugins, producing descriptor-consistent Go and Rust bindings.
- **Files modified:** `gateway/proto/lancet/v1/lancet.pb.go`, `gateway/proto/lancet/v1/lancet_grpc.pb.go`, `engine/src/pb/lancet/v1/*`
- **Verification:** `buf generate` and `buf lint` passed; Go and Rust builds passed.
- **Committed in:** `452cbcb`

**2. [Rule 1 - Bug] Fixed moved Rust stream identifier**
- **Found during:** Task 2 first full Rust compilation
- **Issue:** The first stream message moved `document_id` before validating it, causing compiler error E0382.
- **Fix:** Clone the first message identifiers before consistent-ID validation.
- **Files modified:** `engine/src/main.rs`
- **Verification:** `cargo test -p engine` and `cargo check` passed.
- **Committed in:** `452cbcb`

**3. [Rule 2 - Missing Critical] Made bounded queue admission precede persistence**
- **Found during:** Task 2 queue-exhaustion threat review
- **Issue:** Full-queue rejection happened after LanceDB persistence, allowing rejected uploads to consume storage and leave orphaned records.
- **Fix:** Acquire an owned Tokio queue permit before persistence and consume it only after the raw write succeeds.
- **Files modified:** `engine/src/main.rs`
- **Verification:** bounded queue test, worker test, and live upload smoke passed.
- **Committed in:** `452cbcb`

**4. [Rule 1 - Bug] Aligned runtime DB credentials with Docker Compose**
- **Found during:** Task 2 live smoke preparation
- **Issue:** Both TOML files used `lancet:lancet`, while the declared local PostgreSQL service uses `postgres:postgres`.
- **Fix:** Updated both configurations to the repository's actual local database credentials.
- **Files modified:** `config/config.toml`, `config/config.dev.toml`
- **Verification:** database integration tests and live upload/status smoke passed.
- **Committed in:** `452cbcb`

**5. [Rule 1 - Bug] Wired the development configuration overlay**
- **Found during:** Task 2 configuration audit
- **Issue:** `config.dev.toml` existed but neither runtime could select it.
- **Fix:** Added `LANCET_ENV` overlay loading plus consistent nested environment overrides to Go and Rust.
- **Files modified:** `gateway/main.go`, `engine/src/main.rs`
- **Verification:** Go build and Cargo check passed; base configuration powered the live smoke.
- **Committed in:** `452cbcb`

---

**Total deviations:** 5 auto-fixed (4 bugs, 1 missing critical functionality).
**Impact on plan:** All fixes were required for compilable, descriptor-correct, bounded, locally runnable ingestion; no later phase plan was modified.

## Issues Encountered

- The sandbox initially blocked Buf's remote plugins; approved access to the configured official plugins allowed generation to complete.
- The first LanceDB/Arrow Rust build took about 18 minutes and timed out after compiling dependencies, but exposed a concrete compiler error. After fixing it, cached rebuilds and all tests passed.
- Go 1.26 telemetry paths were not writable in the sandbox; verification used temporary `APPDATA` and `GOCACHE` locations without changing repository configuration.
- Docker CLI access was unavailable, but PostgreSQL was demonstrably reachable through Atlas and the non-skipped transaction integration test.
- The state SDK could not parse this project's compact STATE format for plan advancement, so the same position was recorded directly as plan 2 of 4 with phase progress at 25%.

## Verification Evidence

- `atlas schema apply --env local --auto-approve`: schema synced, no changes.
- `sqlc generate`: completed with generated query code compiling.
- `buf generate` and `buf lint`: passed using configured plugins.
- `go test -count=1 -v ./...`: gateway routes and live PostgreSQL document operations passed.
- `go vet ./...` and `go build ./...`: passed.
- `cargo test -p engine`, `cargo check`, and `cargo fmt -- --check`: passed; 2 Rust tests passed.
- Live smoke: health `ok`, upload `queued`, status transitioned to `completed`, and LanceDB appended the raw payload.

## Known Stubs

- `engine/src/main.rs:226` - indexing is intentionally mocked by deriving chunk count from byte length; the plan explicitly scopes real chunking to follow-on work.
- `engine/src/main.rs:194` and `engine/src/main.rs:205` - pre-existing QueryRAG and QueryGraph scaffolds remain placeholders and are outside this ingestion plan.
- `config/config.toml` and `config/config.dev.toml` - OpenRouter API key is intentionally blank because this plan does not call OpenRouter.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: local-file-storage | `engine/src/main.rs` | Upload-controlled raw bytes are persisted under the configured LanceDB path; path access and retention were not covered by this plan's explicit threat register. |

## User Setup Required

The plan-declared local prerequisites were verified and marked complete in [02-USER-SETUP.md](./02-USER-SETUP.md).

## Next Phase Readiness

- Document ingestion scaffolding is ready for plan 02-02.
- The whole phase is not marked complete; plans 02-02 through 02-04 remain untouched and pending.

## Self-Check: PASSED

- All 12 key implementation, setup, and summary artifacts exist.
- Task commits `c8738d6` and `452cbcb` resolve to commits.
- Coverage metadata classified successfully with 3 of 3 deliverables backed by passing verification.

---
*Phase: 02-ingestion-chunking-vector-storage*
*Completed: 2026-07-19*
