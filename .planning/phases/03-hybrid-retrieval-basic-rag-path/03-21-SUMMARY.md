---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 21
subsystem: retrieval
tags: [limits, bm25, dense, validation]
requires:
  - RAG-01
  - RAG-03
provides:
  - Service-wide absolute ceilings for retrieval limits and weights
  - Bounded workspace pre-allocation for filters and BM25 candidate retention
affects:
  - engine/src/retrieval/mod.rs
  - engine/src/retrieval/bm25.rs
  - engine/src/retrieval/dense.rs
  - engine/src/retrieval/tests.rs
  - config/config.example.toml
tech-stack:
  added: []
  patterns: [absolute-service-ceilings, bounded-candidate-retention]
key-files:
  created: []
  modified:
    - engine/src/retrieval/mod.rs
    - engine/src/retrieval/bm25.rs
    - engine/src/retrieval/dense.rs
    - engine/src/retrieval/tests.rs
    - config/config.example.toml
key-decisions:
  - "Enforce absolute service maximum ceilings (500 candidates, 100 final, 8192 query bytes, 100 filter values, 16.0 RRF weight, 1M rrf_k)."
  - "Use pre-allocated candidate retention bounded by candidate_limit during BM25 scanning instead of document-length allocation."
requirements-completed:
  - RAG-01
  - RAG-03
duration: 20 min
completed: 2026-08-05
coverage:
  - deliverable: Service ceilings and bounded candidate retention for retrieval paths
    verification:
      kind: test
      ref: engine/src/retrieval/tests.rs#service_ceiling_rejects_each_absolute_maximum
      status: pass
    human_judgment: false
---

# Phase 03 Plan 21: Retrieval Limits & BM25 Bounds Summary

Hybrid retrieval now enforces absolute service maximum ceilings on `RetrievalSettings` and limits candidate retention memory in BM25 search under ADR-03-002 (P24-RETRIEVE).

## Key Changes

1. **Absolute Service Ceilings**:
   - Added `MAX_SERVICE_CANDIDATE_LIMIT = 500`, `MAX_SERVICE_FINAL_LIMIT = 100`, `MAX_SERVICE_QUERY_MAX_BYTES = 8192`, `MAX_SERVICE_FILTER_VALUES_PER_KEY = 100`, `MAX_SERVICE_RRF_WEIGHT = 16.0`, and `MAX_SERVICE_RRF_K = 1000000.0` in `engine/src/retrieval/mod.rs`.
   - Updated `RetrievalSettings::validate` to enforce these ceilings at startup and per-query request.

2. **Bounded Filter Pre-allocation & Deduplication**:
   - `QueryFilters::normalize_with_limits` pre-allocates HashSet capacity bounded by `limit.min(input.len())` and rejects items immediately if unique items exceed `limit`.

3. **BM25 Bounded Candidate Workspace**:
   - Replaced unbounded `Vec::with_capacity(self.documents.len())` in `Bm25Index::query` with `insert_bounded_candidate` retaining at most `candidate_limit` items during scanning.

4. **Operator Documentation**:
   - Updated range comments in `config/config.example.toml` to reflect exact maximum service ceilings.

## Verification

- `cargo test --manifest-path engine/Cargo.toml --locked service_ceiling` passed.
- `cargo test --manifest-path engine/Cargo.toml --locked filter_limit` passed.
- `cargo test --manifest-path engine/Cargo.toml --locked bm25_candidate_workspace_respects_effective_limit` passed.

## Self-Check: PASSED
