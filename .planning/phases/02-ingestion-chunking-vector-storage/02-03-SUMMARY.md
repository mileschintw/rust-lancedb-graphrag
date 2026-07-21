---
phase: 02-ingestion-chunking-vector-storage
plan: 03
subsystem: database
tags: [openrouter, embeddings, lancedb, arrow, rust]

requires:
  - phase: 02-02
    provides: structure-aware chunks with stable offsets and token estimates
provides:
  - concurrency-limited OpenRouter embedding client with bounded retries
  - validated LanceDB schemas for documents, nodes, edges, and communities
  - async entity resolver contract with exact-match implementation
affects: [02-04, ingestion, indexing, vector-storage]

tech-stack:
  added: [reqwest, futures, serde_json]
  patterns: [startup schema validation, bounded async fan-out, mock HTTP integration tests]

key-files:
  created:
    - engine/src/client/mod.rs
    - engine/src/client/tests.rs
    - engine/src/db/mod.rs
    - engine/src/db/tests.rs
  modified:
    - engine/src/main.rs
    - engine/Cargo.toml
    - engine/Cargo.lock
    - gateway/go.mod
    - gateway/go.sum

key-decisions:
  - "Declare Rust dependencies as ~major.minor so manifests show two components and permit patch-only updates."
  - "Keep Arrow on the latest 58.3 patch line because LanceDB 0.31 exposes Arrow 58 types."
  - "Reject any persisted LanceDB field drift during startup instead of silently migrating schemas."
  - "Test OpenRouter behavior against a local mock server; reserve live provider validation for a configured API key."

patterns-established:
  - "External API clients bound concurrency before issuing requests and classify retryable HTTP failures explicitly."
  - "LanceDB tables are created from canonical Arrow schemas and revalidated on every startup."

requirements-completed: [DATA-03, DATA-06, DATA-07, DATA-08, DATA-09]

coverage:
  - id: D1
    description: OpenRouter embedding client batches inputs with concurrency five and bounded exponential retries.
    requirement: DATA-03
    verification:
      - kind: unit
        ref: engine/src/client/tests.rs#client test suite
        status: pass
    human_judgment: false
  - id: D2
    description: Four LanceDB tables initialize with canonical Arrow schemas and reject drift.
    requirement: DATA-06
    verification:
      - kind: integration
        ref: engine/src/db/tests.rs#initializes_and_validates_all_table_schemas
        status: pass
      - kind: integration
        ref: engine/src/db/tests.rs#schema_drift_fails_database_initialization
        status: pass
    human_judgment: false
  - id: D3
    description: Exact-match entity resolution is callable through an async resolver trait.
    requirement: DATA-09
    verification:
      - kind: unit
        ref: engine/src/db/tests.rs#exact_match_resolver_returns_only_identical_entities
        status: pass
    human_judgment: false
  - id: D4
    description: Production OpenRouter credentials and the configured free model work against the live provider.
    requirement: DATA-03
    verification: []
    human_judgment: true
    rationale: A real provider call requires the user's OPENROUTER_API_KEY and external account authorization.

duration: 1h 25m
completed: 2026-07-21
status: complete
---

# Phase 2 Plan 3: OpenRouter Embeddings & LanceDB Storage Summary

**Retrying OpenRouter embeddings, four drift-validated LanceDB schemas, and exact-match entity resolution for indexing**

## Performance

- **Duration:** 1h 25m
- **Started:** 2026-07-21T06:55:00Z
- **Completed:** 2026-07-21T08:19:30Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- Added a credential-safe OpenRouter client that preserves input order while limiting concurrent requests to five and retrying transient failures.
- Added canonical Arrow schemas and startup drift validation for the documents, nodes, edges, and communities LanceDB tables.
- Added an async `EntityResolver` contract and exact-match implementation.
- Updated Rust and Go dependency graphs in an isolated user-requested commit and verified both stacks.

## Task Commits

Each task was committed atomically:

1. **Dependency update: current Rust and Go libraries** - `c3d9f6f` (chore)
2. **Task 1: Build OpenRouter Embeddings Client** - `e017c66` (feat)
3. **Task 2: Configure LanceDB Schemas, Drift Detection, and Entity Resolution** - `2621b0c` (feat)

## Files Created/Modified

- `engine/src/client/mod.rs` - OpenRouter request, retry, timeout, and concurrency behavior.
- `engine/src/client/tests.rs` - Local mock-server coverage for retries, timeouts, concurrency, and credential handling.
- `engine/src/db/mod.rs` - Database manager, canonical schemas, drift validation, and entity resolution.
- `engine/src/db/tests.rs` - Embedded LanceDB initialization, drift, and resolver tests.
- `engine/src/main.rs` - Initializes validated tables and persists raw content to the canonical documents schema.
- `engine/Cargo.toml` / `engine/Cargo.lock` - Current compatible Rust dependencies with two-component patch-line constraints.
- `gateway/go.mod` / `gateway/go.sum` - Current Go direct and transitive modules.

## Decisions Made

- Used `~major.minor` Cargo requirements to match the requested two-component declarations while allowing patch-only updates.
- Kept Arrow at 58.3 because upgrading the direct Arrow types to 59 would be incompatible with LanceDB 0.31's public Arrow 58 types.
- Made persisted schema drift a startup error so incompatible storage never proceeds to indexing.
- Kept live OpenRouter validation separate from deterministic mock tests because no user credential was supplied.

## Deviations from Plan

### User-Directed Scope Addition

**1. Updated repository Rust and Go dependencies**
- **Found during:** Task 1
- **Issue:** The user requested all code dependencies be brought current and isolated from feature work.
- **Fix:** Queried official registries, refreshed manifests and lock files, retained Arrow 58 compatibility, and verified both language suites.
- **Files modified:** `engine/Cargo.toml`, `engine/Cargo.lock`, `gateway/go.mod`, `gateway/go.sum`
- **Verification:** `cargo test` and `go test ./...`
- **Committed in:** `c3d9f6f`

---

**Total deviations:** 1 user-directed scope addition. **Impact:** Dependencies are current and separately reviewable; no feature work was mixed into the dependency commit.

## Issues Encountered

- The first Rust rebuild exceeded the command timeout while compiling the refreshed native dependency graph, but the compiler completed successfully; a cached rerun and the full 17-test suite passed.
- Live OpenRouter authorization was not tested because no API key was provided. The local mock suite covers client behavior without transmitting credentials.

## User Setup Required

Set `OPENROUTER_API_KEY` in the engine runtime environment before making live embedding requests. Do not commit the key. A live request remains a manual verification item.

## Next Phase Readiness

- Wave 4 can connect chunk production to embeddings and the validated nodes/documents tables.
- No automated-test blockers remain; live OpenRouter access depends on runtime credentials and provider availability.

## Self-Check: PASSED

- `cargo test`: 17 passed, 0 failed.
- `go test ./...`: all gateway packages passed.
- All four created module/test files exist.
- Production, dependency, and summary changes are isolated into atomic commits.

---
*Phase: 02-ingestion-chunking-vector-storage*
*Completed: 2026-07-21*
