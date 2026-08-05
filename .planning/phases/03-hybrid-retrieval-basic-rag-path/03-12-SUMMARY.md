---
phase: 03-hybrid-retrieval-basic-rag-path
plan: "12"
subsystem: retrieval
tags: [rust, rag, reranker, rrf, bm25, citations]

# Dependency graph
requires:
  - phase: 03-hybrid-retrieval-basic-rag-path
    provides: deterministic hybrid retrieval, prompt evidence packing, citation validation, and the NoOpReranker port from Plans 03-08 and 03-11
provides:
  - production post-fusion reranker injection and final-context limiting
  - exact-zero retrieval-source disablement with focused RRF regressions
  - service-level grounding and citation identity coverage after reranking
affects: [RAG-02, RAG-04, phase-03-quality-gates]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Inject Arc<dyn Reranker> at service construction and use NoOpReranker at startup."
    - "Pass the complete fused candidate pool through the reranker before final-context limiting and evidence packing."
    - "Skip exact-zero retrieval sources before candidate insertion while preserving enabled-source weighted RRF."

key-files:
  created: []
  modified:
    - engine/src/main.rs
    - engine/src/tests.rs
    - engine/src/retrieval/fusion.rs
    - engine/src/retrieval/tests.rs
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md

key-decisions:
  - "Keep NoOpReranker as the Phase 03 production implementation; learned or remote reranking remains deferred to Phase 999.2."
  - "Apply final_context_limit only after the single reranker call so model evidence and citations use final reranked identities."
  - "Treat an exact zero vector_weight or bm25_weight as complete source disablement, including candidate membership and rank metadata."

patterns-established:
  - "Recording and failing reranker doubles prove one-call ordering, identity grounding, and fail-closed generation behavior."
  - "Positive-weight fusion remains full-precision, deduplicated, tie-deterministic, and byte-stable across identical runs."

requirements-completed: [RAG-02, RAG-04]

coverage:
  - id: D1
    description: "Injected reranker receives the full fused pool once before final limiting, and reranked identities flow into generation and citations."
    requirement: RAG-04
    verification:
      - kind: integration
        ref: "engine/src/tests.rs#query_rag_invokes_recording_reranker_once"
        status: pass
      - kind: integration
        ref: "engine/src/tests.rs#query_rag_grounding_uses_reranked_identity"
        status: pass
      - kind: integration
        ref: "engine/src/tests.rs#query_rag_noop_reranker_preserves_fused_order"
        status: pass
      - kind: integration
        ref: "engine/src/tests.rs#query_rag_reranker_failure_skips_generation"
        status: pass
    human_judgment: false
  - id: D2
    description: "Exact-zero vector and BM25 weights exclude their source candidates and rank metadata symmetrically."
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/retrieval/tests.rs#zero_vector_weight_excludes_vector_only_candidates"
        status: pass
      - kind: unit
        ref: "engine/src/retrieval/tests.rs#zero_bm25_weight_excludes_bm25_only_candidates"
        status: pass
    human_judgment: false
  - id: D3
    description: "Enabled-source weighted RRF preserves deduplication, full-precision scores, deterministic ties, and repeat stability."
    requirement: RAG-02
    verification:
      - kind: unit
        ref: "engine/src/retrieval/tests.rs#positive_weights_preserve_rrf_dedup_and_ties"
        status: pass
    human_judgment: false

# Metrics
duration: 13m
completed: 2026-08-04
status: complete
---

# Phase 03 Plan 12: Hybrid reranker seam and zero-weight fusion Summary

**Production RAG queries now rerank the complete fused candidate pool once before final limiting, while exact-zero retrieval weights fully disable their sources without changing enabled-source RRF determinism.**

## Performance

- **Duration:** approximately 13 minutes for this continuation
- **Started:** 2026-08-04T04:49:00Z
- **Completed:** 2026-08-04T05:02:00Z
- **Tasks:** 2
- **Files modified:** 5 plan/production files, plus this summary and execution metadata

## Accomplishments

- Stored an injected `Arc<dyn Reranker>` on `LancetServiceImpl`, wired `NoOpReranker` at startup, and placed one reranker call after fusion and before final limiting, evidence packing, grounding validation, and citation projection.
- Added service regressions proving full-pool observation, deliberate reranked identity grounding, NoOp order preservation, and reranker failure short-circuiting with zero generator calls.
- Made exact-zero vector and BM25 weights exclude source candidates before fusion while preserving enabled-source RRF scores, ranks, deduplication, deterministic tie-breaking, and repeat stability.

## Task Commits

Each production task was committed atomically. The first two entries are the inherited TDD RED and production commits already present when this continuation began.

1. **Task 1 RED: reranker seam regressions** - `9f2b1f9` (`test`)
2. **Task 1 GREEN: wire reranker after fusion** - `1864dd1` (`feat`)
3. **Task 2 RED: zero-weight fusion regressions** - `e2ec787` (`test`)
4. **Task 2 GREEN: disable zero-weight retrieval sources** - `b5c8b9c` (`feat`)

**Plan metadata:** added in the close-out commit after state and roadmap updates.

## Files Created/Modified

- `engine/src/main.rs` - Stores the reranker dependency, invokes it once after fusion, and applies final limiting afterward.
- `engine/src/tests.rs` - Contains the inherited recording/failing reranker fixtures and service regressions; the pre-existing citation-test edit remains unstaged and untouched.
- `engine/src/retrieval/fusion.rs` - Excludes exact-zero sources and returns the complete bounded fused pool before final limiting.
- `engine/src/retrieval/tests.rs` - Covers symmetric zero-weight exclusion and enabled-source RRF invariants.
- `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` - Records out-of-scope citation-test, formatting, and user-stopped gate findings.

## TDD Gate Compliance

- Task 1 RED evidence: `9f2b1f9`; GREEN evidence: `1864dd1`; all four focused service tests pass.
- Task 2 RED evidence: `e2ec787`; the two new zero-weight tests failed before implementation as expected. The positive-weight test was intentionally green in RED because it characterizes behavior that must be preserved; it passes again after the source-disablement fix in `b5c8b9c`.

## Verification Evidence

- Task 1 tracer feedback gate: PASS after `1864dd1`; focused test discovery and all four service tests passed.
- Task 2 focused verification: PASS; all three retrieval tests passed after `b5c8b9c`.
- File-local `rustfmt --check` for `engine/src/retrieval/fusion.rs` and `engine/src/retrieval/tests.rs`: PASS.
- Full Rust library suite: 24 passed, 1 ignored.
- Full Rust binary suite: 70 passed, 1 failed, 1 ignored. The sole failure is the preserved pre-existing `engine/src/tests.rs:2842` citation assertion (`Root` expected versus `/Document Beta` produced).
- Repository-wide `cargo fmt --check`: FAILS on pre-existing formatting drift in `engine/src/generation/*` and `engine/src/prompt.rs`; no unrelated formatting was applied.
- Go, cross-runtime `TestRAGQueryCrossRuntime`, `buf lint`, and `buf format --diff --exit-code`: intentionally not completed after the user directed execution to stop phase-final gates.

## Deviations from Plan

None in production implementation. The plan’s requested code and focused tests were completed without dependency, wire-contract, protobuf, schema, or architectural changes. Out-of-scope verification findings and the user-directed stop are recorded under Issues Encountered and in `deferred-items.md`.

## Issues Encountered

- The first post-commit tracer harness used PowerShell’s default native-output capture and falsely failed its test-name check; rerunning with combined stdout/stderr capture passed all four tests. No repository change was needed.
- The full Rust gate is blocked by the explicitly preserved citation-test edit and unrelated repository formatting drift. These are not included in the 03-12 production commits.
- The optional WINDOWS ledger append could not parse the repository’s existing CRLF frontmatter (`last_updated` was read with a trailing carriage return); the append is best-effort and no ledger repair was attempted.

## Authentication Gates

None.

## Known Stubs

None introduced by this plan.

## Next Phase Readiness

The 03-12 production implementation and focused acceptance evidence are complete. Do not treat the phase as fully verified or transitioned until the preserved citation-test edit is reconciled and the user requests the remaining Rust formatting, Go/cross-runtime, and protobuf gates.

## Self-Check: PASSED

- Summary file exists at `.planning/phases/03-hybrid-retrieval-basic-rag-path/03-12-SUMMARY.md`.
- Commits `9f2b1f9`, `1864dd1`, `e2ec787`, and `b5c8b9c` are present in git history.
- Phase plan index reports `03-12` with `has_summary: true` and no incomplete plans.
- Stub scan found no tracked placeholder/stub patterns in the plan’s modified source and test files.

---
*Phase: 03-hybrid-retrieval-basic-rag-path*
*Plan: 12*
*Completed: 2026-08-04*
