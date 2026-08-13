---
phase: 05-state-machine-workflow-events
plan: 02
subsystem: engine
tags: [rust, rrf-fusion, multi-variant, graph-context, retrieve-hybrid, state-machine]

# Dependency graph
requires:
  - phase: 05-state-machine-workflow-events
    plan: 01
    provides: State machine WorkflowRunner framework, WorkflowContext, and event sequence infrastructure
provides:
  - ExtractGraphContextNode with 10s embedding prelude and 4s graph query budget (GraphTimeoutPolicy empty-context degradation)
  - RetrieveHybridNode executing multi-variant dense/BM25 retrieval, RRF fusion, reranker failure mapping, and zero-evidence short-circuit
  - fuse_variant_candidates supporting up to 8 variants with VariantProvenance tracking
  - Workflow port traits (QueryReformulator, GraphQueryPort, DenseRetrievalPort, Bm25RetrievalPort) and request-local test fakes
  - Admission check rejecting >8 query variants post-ReformulateQuery before retrieval
affects: [05-03, 05-04, 05-05]

# Tech tracking
tech-stack:
  added: []
  patterns: [multi-variant RRF fusion, graph degradation policy, zero-evidence short-circuiting, admission control]

key-files:
  created:
    - engine/src/workflow/ports.rs
    - engine/src/workflow/nodes/graph_context.rs
    - engine/src/workflow/nodes/retrieve.rs
  modified:
    - engine/src/retrieval/fusion.rs
    - engine/src/retrieval/mod.rs
    - engine/src/workflow/nodes/mod.rs
    - engine/src/workflow/nodes/reformulate.rs
    - engine/src/workflow/mod.rs
    - engine/src/workflow/runner.rs
    - engine/src/lib.rs
    - engine/src/main.rs
    - engine/src/tests.rs

key-decisions:
  - "ExtractGraphContextNode degrades gracefully on timeout or graph query error by setting ctx.graph_context to empty string and adding GRAPH_TIMEOUT notice without failing workflow."
  - "RetrieveHybridNode executes variant-0 dense retrieval and multi-variant BM25 retrieval, fusing results using fuse_variant_candidates and returning RetrievalFailed on reranker error."
  - "WorkflowRunner short-circuits zero-evidence scenarios directly to emit_terminal_once when final candidates are empty or NO_EVIDENCE notice is present."
  - "WorkflowRunner enforces strict admission control post-ReformulateQuery returning NodeError::InputValidation if variants.len() > 8 before any retrieval."

requirements-completed: [ORCH-03, RAG-01, RAG-02]
---

# Phase 05 Plan 02 Summary

Plan 05-02 expanded the Rust state-machine tracer with `ExtractGraphContextNode` and `RetrieveHybridNode`, multi-variant RRF candidate fusion (`fuse_variant_candidates`), graph context timeout degradation, zero-evidence short-circuiting, and post-reformulation admission bounds.

## Key Changes
1. **Ports and Test Fakes (`engine/src/workflow/ports.rs`)**: Defined object-safe BoxFuture traits (`QueryReformulator`, `GraphQueryPort`, `DenseRetrievalPort`, `Bm25RetrievalPort`) and request-local test doubles for deterministic unit testing.
2. **Multi-Variant RRF Fusion (`engine/src/retrieval/fusion.rs` & `mod.rs`)**: Implemented `fuse_variant_candidates` with up to 8 variants, accumulator scoring, tie-breaking, and `VariantProvenance` tracking. Re-exported in `engine/src/retrieval/mod.rs`.
3. **Graph Context Node (`engine/src/workflow/nodes/graph_context.rs`)**: Implemented `ExtractGraphContextNode` with a 10s embedding prelude, 4s graph query timeout budget, and `GraphTimeoutPolicy` degradation.
4. **Hybrid Retrieval Node (`engine/src/workflow/nodes/retrieve.rs`)**: Implemented `RetrieveHybridNode` performing variant-0 dense retrieval, multi-variant BM25 retrieval, `fuse_variant_candidates` RRF fusion, reranker failure mapping (`RetrievalFailed`), and zero-evidence notice emission (`NO_EVIDENCE`).
5. **State Machine Runner Enhancements (`engine/src/workflow/runner.rs`)**: Added post-`ReformulateQuery` variant limit admission check (>8 rejected as `InputValidation` before retrieval) and zero-evidence short-circuiting directly to `emit_terminal_once`.
6. **Tests & Verification (`engine/src/retrieval/tests.rs` & `engine/src/tests.rs`)**: Added cross-variant fusion unit tests and 5 state-machine tracer integration tests (`workflow_retrieve_graph`, `graph_timeout_degrades_to_empty_context`, `zero_evidence_short_circuits_generation`, `reranker_failure_maps_to_retrieval_failed`, `nine_variants_are_rejected_before_retrieval`). All 270+ engine tests pass clean.
