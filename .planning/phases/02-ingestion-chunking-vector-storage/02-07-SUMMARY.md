---
phase: 02-ingestion-chunking-vector-storage
plan: 07
subsystem: ingestion-integrity
tags: [rust, lancedb, arrow, go, postgresql, testing]

# Dependency graph
requires:
  - phase: 02-06
    provides: challenge-bound live ingestion and direct PostgreSQL/LanceDB verification baseline
provides:
  - production-used replacement mutation boundaries with one rollback funnel
  - persisted failure-boundary and retry-convergence coverage for all seven canonical mutations
  - Arrow-null node summary persistence
  - bounded detached PostgreSQL compensation after canceled ingestion requests
  - isolated Rust integrity tests in a dedicated test module
affects: [ingestion, lancedb, gateway, phase-02-gap-closure]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - production mutation boundary with deterministic test fault injection
    - post-snapshot errors routed through one three-table rollback funnel
    - bounded context.Background compensation for canceled requests
    - dedicated cfg-gated Rust test module for test-only fixtures and assertions

key-files:
  created:
    - engine/src/tests.rs
    - .planning/phases/02-ingestion-chunking-vector-storage/deferred-items.md
  modified:
    - engine/src/main.rs
    - gateway/main.go
    - gateway/main_test.go

key-decisions:
  - "Capture canonical LanceDB versions before mutation and route every post-snapshot error, including staging cleanup, through one rollback funnel."
  - "Use a five-second context.Background compensation timeout so request cancellation cannot strand failed-ingest metadata."
  - "Keep all Rust fault fixtures and integrity tests in engine/src/tests.rs, leaving production code with only the standard test-module declaration."

patterns-established:
  - "Named ReplacementMutation boundaries make every delete/add/staging operation injectable and auditable."
  - "Nullable LanceDB fields are constructed from their schema data types rather than empty-string sentinels."

requirements-completed: [DATA-01, DATA-03, DATA-07, DATA-08, RAG-06]

coverage:
  - id: D1
    description: "Production replacement mutation boundary routes documents-add failures through rollback and preserves retry convergence."
    requirement: DATA-03
    verification:
      - kind: integration
        ref: "cargo test --manifest-path engine/Cargo.toml tests::replacement_documents_add_failure_rolls_back_and_retry_converges -- --exact --nocapture"
        status: pass
    human_judgment: false
  - id: D2
    description: "All seven replacement failure boundaries preserve the prior generation and converge on a clean retry."
    requirement: DATA-03
    verification:
      - kind: integration
        ref: "cargo test --manifest-path engine/Cargo.toml tests::replacement_failure_boundaries_preserve_prior_generation_and_retry_converges -- --exact --nocapture"
        status: pass
    human_judgment: false
  - id: D3
    description: "Persisted node summaries use Arrow nulls while nullable schema initialization remains regression-safe."
    requirement: DATA-07
    verification:
      - kind: integration
        ref: "cargo test --manifest-path engine/Cargo.toml tests::persisted_node_summary_is_arrow_null -- --exact --nocapture"
        status: pass
    human_judgment: false
  - id: D4
    description: "Canceled ingestion requests still receive bounded detached PostgreSQL failed-status compensation."
    requirement: RAG-06
    verification:
      - kind: integration
        ref: "go test -count=1 -run ^TestCreateDocumentCompensatesWithDetachedContextAfterRequestCancellation$ ."
        status: pass
    human_judgment: false

# Metrics
duration: 58 min
completed: 2026-07-26
status: complete
---

# Phase 02 Plan 07: Canonical Replacement Integrity Summary

**Canonical LanceDB replacements now roll back at every mutation boundary, nullable node summaries persist as Arrow nulls, and canceled uploads receive bounded detached compensation.**

## Performance

- **Duration:** 58 min
- **Started:** 2026-07-26T03:07:19Z
- **Completed:** 2026-07-26T04:05:01Z
- **Tasks:** 3
- **Files modified:** 9 including implementation, test, deferred-item, and tracking files

## Accomplishments

- Replaced the post-write-only fault seam with the production-used `ReplacementMutationBoundary`, enumerating `EdgesDelete`, `NodesDelete`, `DocumentsDelete`, `DocumentsAdd`, `NodesAdd`, `EdgesAdd`, and `StagingDelete`. Every post-snapshot operation now enters the same three-table rollback path on error.
- Added persisted-state tests proving old-generation preservation and no-fault retry convergence for the documents, nodes, edges, and staging tables at every named boundary.
- Constructed node summary values from the schema data type so persisted summaries are Arrow nulls, while community-table empty/repeated initialization regressions remain covered.
- Detached failed-ingest compensation from the canceled HTTP request with an explicit five-second timeout, preserving the original 429/502 response mapping.
- Relocated all Rust test fixtures, fault injectors, and integrity assertions from the production source body to `engine/src/tests.rs` per the final production-vs-test audit.

## Verification

- `cargo fmt --manifest-path engine/Cargo.toml -- --check` — PASS.
- `cargo test --manifest-path engine/Cargo.toml` — PASS (24 engine tests and 4 inspector tests).
- Exact Rust tracer, all-boundary, and Arrow-null tests — PASS.
- Exact Go canceled-request, full-queue 429, and general compensation regressions — PASS.
- `gofmt`, `go test ./...`, and `go vet ./...` in `gateway` — PASS.
- Final production-vs-test audit and `git diff --check` — PASS. No test-only fixtures, temporary harnesses, or development scaffolding remain in `engine/src/main.rs` or `gateway/main.go`; test code is in `engine/src/tests.rs` and `gateway/main_test.go`.

## Task Commits

Each task was committed atomically, with TDD RED/GREEN commits where applicable:

1. **Task 1: Prove one real canonical mutation failure rolls back and retries end to end** — `f3564af` (test RED), `e3961bd` (feat GREEN).
2. **Task 2: Expand rollback coverage to every mutation boundary and persist node summary as Arrow null** — `9e6169f` (test coverage).
3. **Task 3: Compensate ingestion failure after request cancellation** — `86a8ec8` (test RED), `ca42ef2` (feat GREEN).

The production-vs-test relocation was committed separately in `c518216` (refactor). Plan metadata is committed separately after tracking updates.

## Files Created/Modified

- `engine/src/main.rs` — production replacement boundary, rollback funnel, and schema-derived nullable summary construction; only the standard cfg-gated test-module declaration remains for tests.
- `engine/src/tests.rs` — Rust fault injector, persisted rollback/retry coverage, nullable-summary assertion, and existing engine unit tests.
- `gateway/main.go` — bounded detached compensation context.
- `gateway/main_test.go` — canceled-request compensation fixture and regression coverage.
- `.planning/phases/02-ingestion-chunking-vector-storage/deferred-items.md` — out-of-scope pre-existing query stubs recorded for later phases.
- `.planning/WINDOWS.md` — broken-windows entries for the same pre-existing stubs.

## Decisions Made

- Capture canonical LanceDB versions before the first mutation and funnel all later errors through rollback so no direct error path can strand a partial generation.
- Use `context.Background()` with a five-second timeout only for failed-ingest status compensation; the request context remains used for the engine call and response semantics remain unchanged.
- Keep test-only Rust code in a dedicated test module rather than production implementation paths.

## Deviations from Plan

### Execution and audit adjustments

**1. [User constraint - production/test separation] Relocated Rust test-only code.**
- **Found during:** final production-vs-test audit.
- **Issue:** The plan originally listed `engine/src/main.rs` for both production implementation and Rust tests, which would leave fault fixtures and assertions in a production source path.
- **Fix:** Moved the complete Rust test module to `engine/src/tests.rs`; `main.rs` retains only the standard cfg-gated module declaration.
- **Files modified:** `engine/src/main.rs`, `engine/src/tests.rs`.
- **Verification:** Full Rust test suite and exact 02-07 tests passed after relocation.
- **Committed in:** `c518216`.

**2. [Verification environment] Adapted exact-name checks for PowerShell output.**
- **Found during:** Task 1 tracer gate.
- **Issue:** PowerShell `Out-String` preserved CRLF/ANSI output, so the plan's literal end-of-line regex rejected an existing exact test name even though the test was present and passing.
- **Fix:** Re-ran the same presence check with Cargo colors disabled and a CRLF-tolerant end anchor; no production behavior was changed.
- **Verification:** `TRACER_VERIFIED=PASS`; the exact tracer test passed.

**3. [TDD gate overlap] Task 2 RED passed before a separate implementation commit.**
- **Found during:** Task 2 RED gate.
- **Issue:** Task 1's GREEN implementation already generalized all seven mutation boundaries and switched summary construction to schema-derived nulls, so Task 2's new tests passed immediately.
- **Resolution:** Kept the test-only Task 2 commit and recorded the overlap; no redundant implementation commit was created.
- **Verification:** Both exact Task 2 tests passed independently, followed by the full Rust suite.

**4. [Verification environment] Used workspace-local Go cache settings.**
- **Found during:** Task 3 and overall Go verification.
- **Issue:** The sandbox could not write the default Go telemetry/cache locations.
- **Fix:** Re-ran the prescribed tests with `GOTELEMETRY=off`, workspace-local `GOCACHE`, and workspace-local `GOTMPDIR` under approved execution.
- **Verification:** Exact Go tests, `go test ./...`, and `go vet ./...` passed.

**5. [Scope boundary - pre-existing] Recorded unrelated query stubs without changing them.**
- **Found during:** final stub scan.
- **Issue:** `query_rag` has a placeholder answer/empty citations at `engine/src/main.rs:329-330`, and `query_graph` has a scaffolding payload at `engine/src/main.rs:340`; both predate 02-07 and belong to later RAG/graph phases.
- **Fix:** Recorded them in `deferred-items.md` and `.planning/WINDOWS.md`; no unrelated production behavior was changed.
- **Verification:** The 02-07 verification suite remains green.

**Total deviations:** 5 documented adjustments (1 user-constraint relocation, 2 verification-environment adaptations, 1 TDD overlap, 1 pre-existing-scope record).
**Impact on plan:** The requested rollback, retry, null-persistence, compensation, and production/test separation outcomes are complete; no plan task was skipped.

## TDD Gate Compliance

- Task 1 has the required RED commit `f3564af` followed by GREEN implementation commit `e3961bd`.
- Task 2 has the required test commit `9e6169f`; its RED tests passed immediately because the preceding Task 1 GREEN implementation already contained the shared production seam and Arrow-null behavior. This was investigated and documented rather than treated as a missing gate.
- Task 3 has the required RED commit `86a8ec8` followed by GREEN implementation commit `ca42ef2`.

## Known Stubs

These are pre-existing and do not prevent the 02-07 goal:

- `engine/src/main.rs:329-330` — `query_rag` returns a placeholder answer and empty citations; deferred to Phase 03.
- `engine/src/main.rs:340` — `query_graph` returns a scaffolding payload; deferred to Phase 04.

Both are recorded in `.planning/WINDOWS.md` as open `stub` entries and in `deferred-items.md`.

## Auth Gates

None.

## Issues Encountered

- WR-02 remains unresolved exactly as specified by the plan: shutdown still discards pending queue entries because restart reconciliation semantics require a separate product decision.

## User Setup Required

None - no external service configuration was added.

## Next Phase Readiness

02-07 is complete and committed in the main checkout. The replacement integrity and canceled-request compensation gaps are closed; subsequent Phase 02 plans may proceed independently. The pre-existing RAG and graph query stubs remain explicitly deferred to their owning phases.

## Self-Check: PASSED

- Summary file exists.
- All six task/TDD commit hashes are present in git history.
- Production files contain no test-only symbols or fixtures; the final audit passed.

---
*Phase: 02-ingestion-chunking-vector-storage*
*Completed: 2026-07-26*
