---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 01
subsystem: retrieval
tags: [rust, lancedb, bm25, unicode, rrf, reranking]

# Dependency graph
requires:
  - phase: 02-ingestion-chunking-vector-storage
    provides: Completed LanceDB nodes schema and Rust-owned vector data plane
provides:
  - Full-Unicode BM25 snapshot construction and querying over completed node metadata
  - Typed shared query/filter normalization and bounded LanceDB dense candidate selection
  - Deterministic weighted full-precision RRF fusion with chunk-ID deduplication and source ranks
  - Object-safe boxed-future NoOpReranker pass-through seam
affects: [03-02, 03-03, 03-04, 03-05, 999.2-reranking, RAG query coordinator]

# Tech tracking
tech-stack:
  added: [unicode-normalization, unicode-casefold, unicode-segmentation]
  patterns: [schema-driven Arrow extraction, shared typed QueryRequest/QueryFilters, deterministic rank tie keys]

key-files:
  created:
    - engine/src/retrieval/bm25.rs
    - engine/src/retrieval/dense.rs
    - engine/src/retrieval/fusion.rs
    - engine/src/retrieval/tests.rs
    - engine/src/rerank/mod.rs
    - engine/src/rerank/tests.rs
  modified:
    - engine/Cargo.toml
    - engine/Cargo.lock
    - engine/src/main.rs
    - engine/src/retrieval/mod.rs

key-decisions:
  - "Use NFKC, full Unicode case folding, UAX word boundaries, and identifier subtokens without stemming or stop-word removal."
  - "Compute BM25 document frequency over the complete snapshot while applying normalized metadata filters before candidate limits."
  - "Keep full-precision weighted RRF scores, retain both source ranks and scores, and resolve ties by the D-51 identity key."
  - "Expose reranking through a Send + Sync boxed-future trait with NoOpReranker as the Phase 03 pass-through implementation."

patterns-established:
  - "Dense and lexical retrieval consume one normalized typed request and preserve canonical nullable provenance."
  - "LanceDB fixtures use unique temporary paths, schema-driven nullable arrays, and drop all handles before cleanup."

requirements-completed: [RAG-02, RAG-04]

coverage:
  - id: D1
    description: "Full-Unicode BM25 analyzer, global IDF, metadata preservation, and typed empty-content rejection"
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/retrieval/tests.rs#bm25_full_unicode_analyzer_and_global_idf"
        status: pass
      - kind: unit
        ref: "engine/src/retrieval/tests.rs#bm25_rejects_empty_required_content"
        status: pass
    human_judgment: false
  - id: D2
    description: "Filtered dense LanceDB candidates and deterministic weighted RRF fusion"
    requirement: RAG-02
    verification:
      - kind: integration
        ref: "engine/src/retrieval/tests.rs#retrieval_filter_fusion_and_determinism"
        status: pass
      - kind: other
        ref: "cargo test --manifest-path engine/Cargo.toml --locked"
        status: pass
    human_judgment: false
  - id: D3
    description: "Async NoOpReranker preserves fused candidate order, scores, ranks, identity, and provenance"
    requirement: RAG-04
    verification:
      - kind: unit
        ref: "engine/src/rerank/tests.rs#noop_reranker_preserves_candidates"
        status: pass
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-08-02
status: complete
---

# Phase 03 Plan 01: Hybrid Retrieval Basic RAG Path Summary

**Full-Unicode BM25, filtered LanceDB dense retrieval, deterministic weighted RRF, and an async NoOp reranking seam**

## Performance

- **Duration:** 25 min
- **Started:** 2026-08-02T01:42:59Z
- **Completed:** 2026-08-02T02:07:01Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Added approved Unicode analysis dependencies and a fail-fast initial BM25 snapshot build before the engine reaches query-ready startup.
- Implemented shared bounded query/filter contracts, schema-driven dense LanceDB selection, and full-Unicode BM25 scoring with preserved nullable provenance.
- Added weighted full-precision RRF with chunk-ID deduplication, source-rank retention, D-51 tie ordering, and deterministic repeated-run behavior.
- Added the Send + Sync boxed-future `Reranker` port and field-preserving `NoOpReranker`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Unicode BM25 retrieval slice** - `c28f525` (`feat`)
2. **Task 2: Expand to dense retrieval, fusion, and NoOp reranking** - `4f50780` (`feat`)

**Plan metadata:** final state/docs commit is created after this Summary and is recorded in the completion report.

## Files Created/Modified

- `engine/Cargo.toml`, `engine/Cargo.lock` - Approved Unicode analyzer dependencies with locked resolution.
- `engine/src/main.rs` - Retrieval module wiring and initial BM25 snapshot construction during startup.
- `engine/src/retrieval/mod.rs` - Shared normalized request, typed filters, bounds, candidate metadata, and exports.
- `engine/src/retrieval/bm25.rs` - Unicode analyzer, global-statistics BM25 index/query path, and typed build errors.
- `engine/src/retrieval/dense.rs` - Bounded LanceDB nearest-vector selection, typed predicates, and Arrow extraction.
- `engine/src/retrieval/fusion.rs` - Weighted RRF, deduplication, provenance ranks, and deterministic ordering.
- `engine/src/retrieval/tests.rs` - Unicode, global-IDF, isolated LanceDB filter/fusion, and determinism coverage.
- `engine/src/rerank/mod.rs`, `engine/src/rerank/tests.rs` - Async reranker port, NoOp implementation, and byte-preservation coverage.

## Decisions Made

- Full Unicode normalization/case folding and UAX tokenization are shared by BM25 index and query analysis; technical identifiers additionally receive whole and subtoken terms.
- Metadata filters are normalized once, applied before source candidate limits, and do not redefine global BM25 IDF statistics.
- Dense queries explicitly select the canonical `embedding` vector because the nodes schema also contains `summary_vector`.
- RRF retains full precision and deterministic source ranks; the reranker boundary remains replaceable while Phase 03 uses a pass-through implementation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed fusion candidate ownership during compilation**
- **Found during:** Task 2 (dense retrieval, fusion, and NoOp reranking)
- **Issue:** The accumulator initializer moved a candidate into a closure before source-score retention could read it.
- **Fix:** Clone only for entry initialization and capture the source score before insertion.
- **Files modified:** `engine/src/retrieval/fusion.rs`
- **Verification:** Task 2 focused tests and full locked Rust suite passed.
- **Committed in:** `4f50780`

**2. [Rule 1 - Bug] Selected the canonical dense vector column explicitly**
- **Found during:** Task 2 isolated LanceDB fixture
- **Issue:** LanceDB rejected auto-detection because the canonical nodes schema has both `embedding` and `summary_vector` vector columns.
- **Fix:** Set the dense query column to `embedding` before applying filters and executing the bounded search.
- **Files modified:** `engine/src/retrieval/dense.rs`
- **Verification:** `retrieval_filter_fusion_and_determinism` and the full locked Rust suite passed.
- **Committed in:** `4f50780`

**3. [Rule 1 - Bug] Corrected the RRF tie fixture to produce equal source contributions**
- **Found during:** Task 2 deterministic fusion test
- **Issue:** The initial fixture ordered both source lists identically, so the first candidate correctly had a higher RRF score instead of exercising D-51 tie ordering.
- **Fix:** Reverse the second source ranking and assert the documented identity-key order.
- **Files modified:** `engine/src/retrieval/tests.rs`
- **Verification:** Focused retrieval test and full locked Rust suite passed.
- **Committed in:** `4f50780`

**4. [Rule 3 - Blocking] Restored the phase-local plan count required by state transitions**
- **Found during:** Post-Summary canonical state updates
- **Issue:** `STATE.md` had project-wide plan totals but no body `Total Plans in Phase` field, so `state.advance-plan` could not parse the active phase.
- **Fix:** Added the recoverable phase-local count of five plans, then reran the canonical advance/progress/metric/session commands successfully.
- **Files modified:** `.planning/STATE.md`
- **Verification:** `state.advance-plan`, `state.update-progress`, `state.record-metric`, `state.record-session`, and `roadmap.update-plan-progress` completed successfully.
- **Committed in:** final state/docs metadata commit

---

**Total deviations:** 4 auto-fixed (2 Rule 1, 2 Rule 3)
**Impact on plan:** All fixes were directly required for compilation, correct LanceDB operation, or valid acceptance coverage; no scope was added.

## Issues Encountered

- The exact audited `unicode-casefold` package was not present in the initial offline Cargo cache; Cargo resolved it after the offline flag was temporarily relaxed. An unrelated attempted lock refresh was restored, leaving only the approved dependency changes.
- The plan’s PowerShell test-list guard treats captured output arrays as element arrays; the equivalent joined-output guard was used so registered-test checks were reliable on Windows PowerShell.
- The sandbox initially denied Git index writes; authorized elevated Git permissions were used for the two requested commits.
- The compiler reports dead-code warnings for retrieval seams not yet called by the later query coordinator; all locked tests, formatting, checks, and doc tests passed.
- The required Windows ledger append was attempted but the existing `.planning/WINDOWS.md` parser rejected its CRLF frontmatter. The same pre-existing QueryRAG placeholder is already tracked as open ledger entry 1.

## Known Stubs

- `engine/src/main.rs:550` - Existing `QueryRAG` handler still returns a placeholder answer. This plan intentionally delivers the retrieval data-plane seams; later Phase 03 plan work wires the end-to-end query response. The defect is already tracked by `.planning/WINDOWS.md` entry 1; a duplicate append was not created after the parser rejected the existing CRLF frontmatter.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The dense, BM25, fusion, and NoOp reranker seams are committed and ready for the remaining Phase 03 plans to integrate into the happy-path query coordinator.
- No authentication gate or user decision checkpoint occurred.
- The existing placeholder query handler remains the intentional integration boundary for subsequent plan work; deferred degraded retrieval, fallback, citation repair, graph, and restart behavior remain outside this plan.

## Self-Check: PASSED

- Summary and all created implementation files exist.
- Task commits `c28f525` and `4f50780` resolve in repository history.
- Required deliverable/test markers and `status: complete` are present.

---
*Phase: 03-hybrid-retrieval-basic-rag-path*
*Completed: 2026-08-02*
