---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 05
subsystem: cross-runtime-rag-smoke
tags: [rust, go, lancedb, grpc, httptest, openrouter, process-isolation]

# Dependency graph
requires:
  - phase: 03-hybrid-retrieval-basic-rag-path
    provides: Dense/BM25 fusion, bounded evidence, structured generation, QueryRAG gRPC, Go /rag/query route, and injectable embedding endpoint
provides:
  - Reusable deterministic completed-corpus LanceDB seeder
  - Real Go-to-Rust process-level RAG smoke with local embedding, metadata, and chat contracts
  - Five-plan Phase 03 coverage matrix with explicit manual-provider and deferred boundaries
affects: [Phase 03 verification, RAG-02, RAG-04, Phase 06 hardening]

# Tech tracking
tech-stack:
  added: []
  patterns: [direct resolved binary launch, scrubbed child environments, generated-gRPC readiness probe, bounded Windows process-tree cleanup]

key-files:
  created:
    - engine/src/bin/seed_rag_fixture.rs
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-05-SUMMARY.md
  modified:
    - gateway/main_test.go
    - engine/src/main.rs
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/COVERAGE.md

key-decisions:
  - "Use one deterministic localhost server for embeddings, model supported-parameters metadata, and exactly one strict structured chat completion."
  - "Seed stable UUIDv4 document/chunk rows into a caller-provided temporary LanceDB path and prove the path can be renamed and removed after teardown."
  - "Treat the Rust serving log as a milestone only; the exact loopback endpoint must answer generated-gRPC Ping before /rag/query is issued."

patterns-established:
  - "Cross-runtime tests build once per test, launch direct resolved binaries from the repository root, and use only test-scoped application environment variables."
  - "The accepted MVP proves valid hybrid retrieval and grounded generation while live-provider, degraded, repair, retry/fallback, graph, and lifecycle recovery behavior remains deferred."

requirements-completed: [RAG-02, RAG-04]

coverage:
  - id: D1
    description: "Real Go HTTP route to Rust gRPC QueryRAG happy path over seeded dense and lexical LanceDB evidence"
    requirement: RAG-02
    verification:
      - kind: e2e
        ref: "gateway/main_test.go#TestRAGQueryCrossRuntime"
        status: pass
      - kind: other
        ref: "cargo test --manifest-path engine/Cargo.toml --locked"
        status: pass
      - kind: other
        ref: "go test . in gateway"
        status: pass
    human_judgment: false
  - id: D2
    description: "Reusable isolated fixture seeding, local provider contract validation, gRPC Ping readiness, and Windows handle-release cleanup"
    requirement: RAG-04
    verification:
      - kind: integration
        ref: "gateway/main_test.go#TestRAGQueryCrossRuntime"
        status: pass
      - kind: other
        ref: "cargo build --manifest-path engine/Cargo.toml --locked --bin engine --bin seed_rag_fixture"
        status: pass
    human_judgment: false

# Metrics
duration: 30min
completed: 2026-08-02
status: complete
---

# Phase 03 Plan 05: Hybrid Retrieval Basic RAG Path Summary

**Provider-independent cross-runtime RAG smoke with deterministic LanceDB seeding and strict localhost provider contracts**

## Performance

- **Duration:** 30 min
- **Started:** 2026-08-02T21:35:00Z
- **Completed:** 2026-08-02T22:05:05Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added `seed_rag_fixture` to initialize the canonical LanceDB schema and write stable completed document, node, and edge rows with finite 2,048-wide embeddings, complete provenance metadata, and no staging rows.
- Added `TestRAGQueryCrossRuntime`, which builds the Rust engine and seeder once, launches direct binaries with scrubbed child environments, validates embedding/metadata/chat contracts, probes generated-gRPC Ping, and exercises the real Go `/rag/query` route.
- Added deterministic process-tree teardown and bounded LanceDB rename/remove release proof, with no PostgreSQL or live provider credential dependency.
- Synchronized coverage ownership across Plans 03-01 through 03-05 and retained the manual OpenRouter check plus DEBT-RAG-05 future negative-input suite outside MVP automation.

## Task Commits

Each task was committed atomically:

1. **Task 1: Trace the real local Go-to-Rust RAG request with seeded LanceDB and three provider mocks** - `ae8c0f3` (feat)
2. **Task 2: Synchronize the Phase 03 coverage and manual-provider boundary** - `12bb3cf` (docs)

**Plan metadata:** final state/docs commit is created after this Summary and is recorded in the completion report.

## Files Created/Modified

- `engine/src/bin/seed_rag_fixture.rs` - Reusable deterministic completed-corpus seeder accepting `--lancedb-path`.
- `gateway/main_test.go` - Real process-level smoke with local three-endpoint provider mock, readiness, environment, teardown, and release assertions.
- `engine/src/main.rs` - Exact test/deployment endpoint overrides and configured chat/metadata endpoint wiring; existing `models_endpoint` TOML remains accepted as an alias.
- `.planning/phases/03-hybrid-retrieval-basic-rag-path/COVERAGE.md` - Five-plan evidence ownership and deferred-boundary matrix.

## Decisions Made

- The localhost mock returns a deterministic 2,048-dimensional query vector, advertises `response_format` and `structured_outputs`, and accepts exactly one strict `json_object` chat request.
- The real engine environment uses only the exact task-scoped `LANCET_*` endpoint/path/address variables and `OPENROUTER_API_KEY=test-key`; the seeder receives no application configuration.
- The response contract asserts grounded `[1]` citation provenance, retrieval snapshot metadata, effective caller session identity, and both dense and lexical fixture content in Rust-owned evidence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected canonical Arrow schema borrow ownership in the fixture seeder**
- **Found during:** Task 1 build
- **Issue:** Nullable-field closures borrowed the LanceDB schema while `RecordBatch::try_new` attempted to move it.
- **Fix:** Clone the schema references for record-batch construction while retaining the borrowed schema for nullable columns.
- **Files modified:** `engine/src/bin/seed_rag_fixture.rs`
- **Verification:** Locked Cargo build and full Cargo test suite passed.
- **Committed in:** `ae8c0f3`

**2. [Rule 1 - Bug] Wired the exact plan endpoint environment names into Rust settings**
- **Found during:** Task 1 cross-runtime smoke
- **Issue:** The existing config environment deserialization left the direct child on repository defaults, so the test endpoint and loopback address were ignored.
- **Fix:** Applied explicit `LANCET_ENGINE__*` and `LANCET_OPENROUTER__*` boundary overrides, mapped `MODEL_METADATA_ENDPOINT`, preserved the existing `models_endpoint` TOML alias, and always applied configured chat/metadata endpoints to the generator.
- **Files modified:** `engine/src/main.rs`
- **Verification:** `TestRAGQueryCrossRuntime`, locked Cargo tests, and startup configuration tests passed.
- **Committed in:** `ae8c0f3`

---

**Total deviations:** 2 auto-fixed (1 Rule 3 blocking, 1 Rule 1 bug)
**Impact on plan:** Both fixes were required for the specified direct-process environment and seeder compilation; no deferred behavior or architectural scope was added.

## Issues Encountered

- The restricted global Go build cache was inaccessible. Verification was rerun successfully with `GOTELEMETRY=off` and a task-scoped temporary `GOCACHE`.
- PowerShell returned native Go test output as an array, so the plan’s zero-test/pass guards were evaluated with immediate `$LASTEXITCODE` capture and line-based matching to avoid false negatives.
- Existing Rust dead-code warnings remain for retrieval seams already covered by prior plans; they do not fail the locked suite and are outside this plan’s scope.

## User Setup Required

None - automated verification is provider-independent. The optional ignored live OpenRouter structured-output check remains manual and requires the user’s own credential/network access.

## Known Stubs

None introduced by this plan. Deferred degraded retrieval, model-only fallback, citation repair/downgrade, provider retry/fallback, graph behavior, restart/re-ingestion recovery, and exhaustive invalid-input/filter coverage remain explicitly tracked debt rather than hidden stubs.

## Next Phase Readiness

- The selected Phase 03 plan is complete and its local happy path is executable from the real Go route through Rust retrieval and structured generation.
- The orchestrator may perform its separately requested phase-level review/verification workflow; this execution did not run phase-final review, `VERIFICATION.md`, or transition work.

## Self-Check: PASSED

- `engine/src/bin/seed_rag_fixture.rs`, `gateway/main_test.go`, `engine/src/main.rs`, `COVERAGE.md`, and this Summary exist.
- Task commits `ae8c0f3` and `12bb3cf` resolve in repository history.
- `git diff --check` passes; existing `.planning/ROADMAP.md` and `.planning/STATE.md` edits were preserved while normal executor tracking updates were applied.
- Locked Cargo build/tests, filtered cross-runtime Go smoke, full Go suite, and Task 2 coverage assertions passed.

---
*Phase: 03-hybrid-retrieval-basic-rag-path*
*Completed: 2026-08-02*
