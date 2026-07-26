---
phase: 02-ingestion-chunking-vector-storage
plan: 08
subsystem: testing
tags: [openrouter, reqwest, lancedb, rust, integrity, inspector]

# Dependency graph
requires:
  - phase: 02-ingestion-chunking-vector-storage
    provides: production ingestion client, canonical LanceDB schemas, and live-gate inspector surface from Plans 02-01 through 02-07
provides:
  - Locked ten-second OpenRouter request timeout with behavioral coverage and the four-attempt retry policy
  - Fail-closed LanceDB inspector deriving provider, model, generation, uniqueness, continuity, and edge-integrity facts from durable rows
affects: [phase-02-live-evidence, ingestion-verification, phase-03-hybrid-retrieval]

# Tech tracking
tech-stack:
  added: []
  patterns: [shared reqwest client builder, sanitized LanceDB column projections, real-store adversarial fixtures]

key-files:
  created:
    - engine/src/inspect_lancedb_tests.rs
  modified:
    - engine/src/client/mod.rs
    - engine/src/client/tests.rs
    - engine/src/bin/inspect_lancedb.rs

key-decisions:
  - "Keep REQUEST_TIMEOUT as the single ten-second reqwest builder contract; the test seam may vary endpoint and retries but never the production timeout."
  - "Derive inspector identity and integrity verdicts only from filtered durable LanceDB rows, rejecting missing, mixed, duplicate, stale, or non-contiguous state before JSON output."
  - "Keep real LanceDB inspector fixtures in engine/src/inspect_lancedb_tests.rs so Cargo does not discover test-only code as a production src/bin target."

patterns-established:
  - "OpenRouter timeout behavior is tested through the same fixed-timeout builder used by OpenRouterClient::new."
  - "Sanitized inspectors select only the exact durable columns needed for validation and never serialize content, raw bytes, embeddings, headers, or credentials."

requirements-completed: [DATA-03, DATA-08]

coverage:
  - id: D1
    description: "OpenRouter uses a fixed ten-second per-call timeout with three retries after the initial request and preserves the maximum-five concurrency cap."
    requirement: DATA-03
    verification:
      - kind: unit
        ref: "engine/src/client/tests.rs#client::tests::production_client_times_out_at_locked_ten_seconds"
        status: pass
      - kind: unit
        ref: "cargo test --manifest-path engine/Cargo.toml client::tests -- --nocapture"
        status: pass
    human_judgment: false
  - id: D2
    description: "The LanceDB inspector derives sanitized provider/model/generation/uniqueness/continuity and edge referential-integrity facts from durable rows and rejects adversarial fixtures."
    requirement: DATA-08
    verification:
      - kind: integration
        ref: "cargo test --manifest-path engine/Cargo.toml --bin inspect_lancedb tests::<nine required exact names> -- --exact --nocapture"
        status: pass
      - kind: automated
        ref: "cargo check --manifest-path engine/Cargo.toml --bin inspect_lancedb"
        status: pass
    human_judgment: false

# Metrics
duration: 35 min
completed: 2026-07-26
status: complete
---

# Phase 02 Plan 08: OpenRouter Timeout and Durable Inspector Summary

**Locked ten-second OpenRouter timeout with four-attempt backoff and fail-closed LanceDB identity/integrity inspection**

## Performance

- **Duration:** 35 min
- **Started:** 2026-07-26T04:09:00Z
- **Completed:** 2026-07-26T04:44:17Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Replaced the production 30-second OpenRouter timeout with a shared ten-second reqwest builder, retaining three retries after the initial attempt, 1/2/4-second backoff, and concurrency cap five.
- Added a slow local endpoint behavior test that reaches the production timeout builder and returns a timeout-class error at approximately 10 seconds.
- Replaced fixed inspector attestations with direct filtered LanceDB reads for persisted embeddings, model, generation, chunk identity/indexes, and edge endpoints; invalid durable state fails before success JSON is emitted.
- Added one valid and eight adversarial real-LanceDB fixtures covering model identity, generation, chunk uniqueness/continuity, edge uniqueness, and stale endpoint rejection.

## Task Commits

Each task was committed atomically; TDD tasks have separate RED/GREEN commits:

1. **Task 1: Enforce and behaviorally prove the locked OpenRouter timeout** — `be5deb3` (test RED), `adcb7d1` (feat GREEN)
2. **Task 2: Derive inspector identity and generation facts from durable rows** — `c420b23`, `0caf4e3` (test RED), `2cf4d7b` (feat GREEN), `aad0b88` (fix fixture placement)

**Plan metadata:** committed with the final `docs(02-08)` metadata commit.

## Files Created/Modified

- `engine/src/client/mod.rs` — shared locked timeout builder and explicit timeout classification.
- `engine/src/client/tests.rs` — production-builder timeout behavior and retry/concurrency coverage.
- `engine/src/bin/inspect_lancedb.rs` — sanitized durable-row queries and fail-closed aggregation.
- `engine/src/inspect_lancedb_tests.rs` — real LanceDB valid/adversarial inspector fixtures outside production binary discovery.

## Decisions Made

- Kept endpoint and retry overrides test-only while making the HTTP timeout immutable at the production ten-second contract.
- Used persisted model and generation sets, exact chunk-index range checks, and edge endpoint membership as prerequisites for emitting inspector JSON.
- Selected only identity, integrity, and embedding-width columns; raw document bytes and chunk content remain outside the inspector query and output.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved timeout classification in the client error path**

- **Found during:** Task 1 (timeout behavior verification)
- **Issue:** reqwest's plain error string did not identify a request timeout, so the new behavioral test could not distinguish a timeout-class failure from a generic transport error.
- **Fix:** Map `reqwest::Error::is_timeout()` to an explicit timeout message while retaining the existing retryable failure path.
- **Files modified:** `engine/src/client/mod.rs`
- **Verification:** Focused ten-second behavior test and full `client::tests` suite passed.
- **Committed in:** `adcb7d1`

**2. [Rule 3 - Blocking] Relocated inspector fixtures out of Cargo's binary discovery directory**

- **Found during:** Plan-level verification after Task 2
- **Issue:** A dedicated test file under `engine/src/bin` was auto-discovered as a second production binary, causing `cargo test ... client::tests` to fail on its `super` imports.
- **Fix:** Moved the fixture module to `engine/src/inspect_lancedb_tests.rs`; the production binary retains only a `cfg(test)` path declaration.
- **Files modified:** `engine/src/bin/inspect_lancedb.rs`, `engine/src/inspect_lancedb_tests.rs`
- **Verification:** Client suite, all nine anchored bin-scoped inspector tests, formatter, and bin check passed.
- **Committed in:** `aad0b88`

---

**Total deviations:** 2 auto-fixed (1 Rule 1 bug, 1 Rule 3 blocking issue)
**Impact on plan:** Both fixes were directly required for trustworthy timeout evidence, successful Cargo execution, and the user's test-isolation constraint; no scope creep was introduced.

## Issues Encountered

- The sandbox initially denied `.git/index.lock` writes; repository commits were retried with approved normal Git operations and hooks, without `--no-verify`.
- PowerShell Cargo output contained ANSI highlighting and CRLF line endings that interfered with the plan's anchored listing regex; the verification normalized terminal formatting only before applying the same anchored exact-name check.
- `ctx7`/Context7 was unavailable; the documented CLI fallback was checked and not installed, while the locked local crate sources and compiler verification established the reqwest/LanceDB APIs used.

## User Setup Required

None - no external service configuration or credentials were needed for this plan.

## Next Phase Readiness

- Plan 02-09 can consume `generation_count`, `duplicate_generation`, `stale_generation`, and `chunk_indexes_contiguous` directly from the inspector instead of hardcoded attestations.
- The final real-provider acceptance remains intentionally owned by Plan 02-10 after the live-gate hardening in Plan 02-09.

## Self-Check: PASSED

- All final key files exist on disk.
- Task commits `be5deb3`, `adcb7d1`, `c420b23`, `0caf4e3`, `2cf4d7b`, and `aad0b88` exist in Git history.
- Final formatter, client suite, nine exact inspector tests, and inspector bin check passed.

---
*Phase: 02-ingestion-chunking-vector-storage*
*Completed: 2026-07-26*
