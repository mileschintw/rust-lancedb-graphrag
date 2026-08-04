---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 11
subsystem: retrieval/startup
tags: [rust, rag, retrieval, bm25, settings, readiness, openrouter]

# Dependency graph
requires:
  - phase: 03-09
    provides: retrieval construction, BM25 indexing, query and snapshot contracts
  - phase: 03-10
    provides: configured embedding and generation provider adapters
provides:
  - production startup wiring from one validated EffectiveRagSettings value
  - process-level readiness guards for invalid settings and initial BM25 failures
  - binary-target contract coverage for the secret-free, annotated operator example
affects: [RAG-02, Phase 03 Plan 12, engine startup, operator configuration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - one validated settings object is passed to retrieval, prompt, providers, persistence, and snapshots
    - startup failures are asserted through bounded child processes and readiness absence
    - operator configuration is checked through the production binary target and raw-line annotations

key-files:
  created: []
  modified:
    - engine/src/main.rs
    - engine/src/retrieval/bm25.rs
    - engine/src/tests.rs
    - engine/tests/config_startup.rs
    - config/config.example.toml
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md

key-decisions:
  - "Keep EffectiveRagSettings as the single validated source for startup consumers and provider identities."
  - "Require schema-valid BM25 fixtures and row-level diagnostics before treating initial readiness failure as proven."
  - "Keep credentials environment-only and enforce the exact 24-key annotated example contract in the binary target."

patterns-established:
  - "Startup readiness is advertised only after settings validation, BM25 construction, provider construction, and service registration succeed."
  - "Focused process tests assert both nonzero termination and absence of the listening/readiness signal."

requirements-completed: [RAG-02]

coverage:
  - id: D1
    description: "Production RAG startup and one query use one validated EffectiveRagSettings value across retrieval, providers, persistence, citations, and snapshots."
    requirement: RAG-02
    verification:
      - kind: integration
        ref: "engine/src/tests.rs#configured_provider_settings_reach_query_requests"
        status: pass
      - kind: integration
        ref: "engine/src/tests.rs#configured_embedding_identity_persists_and_reports"
        status: pass
      - kind: integration
        ref: "engine/src/tests.rs#configured_bm25_and_evidence_settings_reach_query"
        status: pass
    human_judgment: false
  - id: D2
    description: "Invalid settings and a genuine schema-valid initial BM25 indexing failure block readiness with precise diagnostics."
    requirement: RAG-02
    verification:
      - kind: integration
        ref: "engine/tests/config_startup.rs#invalid_rag_settings_block_readiness"
        status: pass
      - kind: integration
        ref: "engine/tests/config_startup.rs#initial_bm25_failure_blocks_readiness"
        status: pass
    human_judgment: false
  - id: D3
    description: "The binary target validates the exact 24-key, annotated, secret-free operator configuration example."
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/tests.rs#config_example_matches_effective_rag_contract"
        status: pass
    human_judgment: false

# Metrics
duration: 35min
completed: 2026-08-04
status: complete
---

# Phase 03 Plan 11: Production Settings and Startup Readiness Summary

**Production RAG settings now flow through one validated object, with precise startup readiness guards and a tested annotated operator configuration example.**

## Performance

- **Duration:** approximately 35 minutes including continuation from the existing RED checkpoint
- **Started:** 2026-08-03T20:48:59-07:00
- **Completed:** 2026-08-03T21:21:45-07:00
- **Tasks:** 3
- **Files modified:** 5 implementation/test/config files, plus the deferred-items ledger

## Accomplishments

- Completed the existing production-settings RED/GREEN slice and verified that configured provider, retrieval, prompt, persistence, citation, and snapshot consumers agree.
- Added schema-valid process fixtures proving invalid settings and whitespace-only BM25 content fail before listening or readiness, with the offending setting or row identity in diagnostics.
- Added the binary-only exact-key contract and synchronized all 24 effective RAG settings in `config/config.example.toml` with adjacent units/ranges and environment-only credential guidance.

## Task Commits

Each TDD task was committed atomically:

1. **Task 1: Prove production settings reach one provider query** - `ef33ac9` (RED), `d7ccf3a` (GREEN; existing continuation commit)
2. **Task 2: Block readiness on invalid settings and genuine initial BM25 failure** - `8850756` (RED), `431acd2` (GREEN)
3. **Task 3: Validate and synchronize the operator configuration example** - `47e5306` (RED), `b6e76dc` (GREEN)

Plan metadata is captured separately after state and roadmap updates.

## Files Created/Modified

- `engine/src/main.rs` - builds startup components from validated effective settings and labels initial BM25 construction failures.
- `engine/src/retrieval/bm25.rs` - includes document/chunk identity in required-field build diagnostics.
- `engine/src/tests.rs` - records effective provider behavior and validates the example through the binary target; the pre-existing citation-test edit remains unstaged and untouched.
- `engine/tests/config_startup.rs` - supplies isolated schema-valid readiness failure fixtures and bounded process assertions.
- `config/config.example.toml` - documents the exact effective RAG keys, units, ranges, and environment-only secret convention.
- `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` - records the unrelated pre-existing citation-test failure discovered by the full-suite check.

## Decisions Made

- Use one validated `EffectiveRagSettings` value as the source for all production RAG consumers.
- Treat initial BM25 construction as a readiness prerequisite and make failure diagnostics identify the invalid field and unique row.
- Keep the example contract in `engine/src/tests.rs` so it exercises the real binary-owned `Settings` and `EffectiveRagSettings` types without adding a parser dependency.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical diagnostic] Added actionable initial BM25 failure context**

- **Found during:** Task 2 GREEN implementation.
- **Issue:** The startup error path did not identify the initial BM25 snapshot or the unique document/chunk row that made the schema-valid fixture fail.
- **Fix:** Added the initial-BM25 context at startup and included document/chunk identity in required-field validation diagnostics.
- **Files modified:** `engine/src/main.rs`, `engine/src/retrieval/bm25.rs`
- **Verification:** `initial_bm25_failure_blocks_readiness` passes and asserts the BM25 label, `content`, both row identifiers, nonzero exit, and no listening socket/readiness signal.
- **Committed in:** `431acd2`

### Out-of-scope preserved working-tree state

The pre-existing unstaged edit in `engine/src/tests.rs` was not staged or modified. The exact full engine suite therefore has one unrelated failure in `query_rag_citation_identity_and_notices` (`/Document Beta` versus the edited `Root` expectation); this is recorded in `deferred-items.md`. The same suite passes with that one pre-existing test excluded, and all 03-11 focused verification commands pass.

**Total deviations:** 1 auto-fixed Rule 2 issue; 1 preserved out-of-scope working-tree issue.

**Impact on plan:** The planned gap closure is complete. No protobuf, schema, dependency, or deferred D-41 through D-43 behavior was added.

## Issues Encountered

- The plan's PowerShell test-list capture required `2>&1` to inspect Cargo's test-list stream; this did not affect production behavior.
- `cargo fmt --check` reports pre-existing formatting differences across unrelated engine files; no broad formatting rewrite was made because it would overlap unrelated work.
- The mandated full suite was run and its single failure is the preserved user edit described above. The excluding-test run passed: 63 engine binary tests, 21 library tests, 18 inspector tests, 6 startup tests, and doc tests, with the existing ignored tests unchanged.
- The existing STATE.md checkpoint counter was stale at plan 3; after the required advance operation, the plan position was reconciled to current plan 12 (03-12 pending) and no phase completion or transition was performed. `requirements.mark-complete RAG-02` made no file change because RAG-02 was already checked in REQUIREMENTS.md.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

03-11 is complete and leaves the settings/readiness contract ready for the separately planned 03-12 work. 03-12 and later phase-final gates were not executed. The preserved `engine/src/tests.rs` working-tree edit remains for its owner to reconcile.

---
*Phase: 03-hybrid-retrieval-basic-rag-path*
*Completed: 2026-08-04*

## Self-Check: PASSED

- SUMMARY file exists at the required path.
- Task commits `ef33ac9`, `d7ccf3a`, `8850756`, `431acd2`, `47e5306`, and `b6e76dc` are present in git history.
- No new stub markers were found in the plan's implementation, test, or configuration files.
