---
phase: 03
reviewers: [antigravity]
reviewed_at: 2026-08-04T08:27:00Z
plans_reviewed: [03-01-PLAN.md, 03-02-PLAN.md, 03-03-PLAN.md, 03-04-PLAN.md, 03-05-PLAN.md, 03-06-PLAN.md, 03-07-PLAN.md, 03-08-PLAN.md, 03-09-PLAN.md, 03-10-PLAN.md, 03-11-PLAN.md, 03-12-PLAN.md]
---

# Cross-AI Plan Review — Phase 03

## Antigravity Review

# Independent Plan Review: Lancet Phase 03 (Hybrid Retrieval & Basic RAG Path)

**Target Repository:** `D:\Repos\lancet`  
**Phase:** Phase 03 (`.planning/phases/03-hybrid-retrieval-basic-rag-path/`)  
**Scope:** RAG-02 (Hybrid Retrieval) and RAG-04 (Reranker Trait & NoOp Default), evaluated against planning documents, refreshed code review, verification logs, and actual source code.

### Summary

Phase 03 completes the core end-to-end tracer for Lancet's hybrid RAG path: the Go HTTP gateway, gRPC contract, Rust RAG engine, LanceDB vector retrieval, in-memory BM25 lexical index, RRF, NoOp reranker seam, prompt evidence packing, and provider-neutral generation adapter.

**Assessment:**

- **RAG-04:** **Achieved.** Plan 03-12 wired `NoOpReranker` into `engine/src/main.rs` post-fusion and injected it at startup.
- **RAG-02:** **Substantively implemented with critical failure-path gaps.** The valid-query happy path is functional and covered by the real-process cross-runtime integration test, but several failure paths silently mask errors and grounding validation permits retrieval-marked answers with zero citations.

### Strengths

1. `gateway/main.go:631` enforces a strict 32 KiB request body limit and strict JSON decoding.
2. `engine/src/retrieval/fusion.rs` implements deterministic full-precision RRF with zero-weight source exclusion.
3. `engine/src/rerank/mod.rs:11` and `engine/src/main.rs:1000-1004` provide a clean, correctly positioned RAG-04 reranker seam.
4. `engine/src/prompt.rs:91-114` escapes corpus-controlled fields and `:270-278` uses Unicode-aware excerpt bounds.
5. `gateway/main_test.go:1503` verifies the full Go HTTP to gRPC to Rust to LanceDB to provider-mock path.

### Concerns

#### HIGH

1. `engine/src/main.rs:967-974` silently replaces embedding failures, timeouts, or invalid dimensions with a constant `[0.25; 2048]` query vector, allowing unrelated retrieval to appear grounded.
2. `engine/src/main.rs:976-984` suppresses dense retrieval errors with `unwrap_or_default()`, making vector-store failures look like successful lexical-only retrieval.
3. `engine/src/generation/mod.rs:71-127` does not require non-empty citations for `Retrieval` or `Mixed` answers, so zero-citation answers can pass grounding validation.
4. `engine/src/main.rs:1012-1019` and `gateway/main.go:669-672` map valid no-match or evidence-budget failures to HTTP 400 instead of distinguishing empty results from invalid client input or server failure.

#### MEDIUM

5. `engine/src/generation/openrouter.rs:287-293` uses hardcoded prompt/output budgets instead of the effective generation settings.
6. `engine/src/main.rs:1715-1720` defaults the API key to a fake testing value, allowing misconfigured startup to proceed until query time.
7. `gateway/main.go:667-674` and `engine/src/main.rs:1029-1034` do not propagate correlation IDs on provider errors.

#### LOW

8. `engine/src/tests.rs:2750-2851` contains a non-deterministic parallel-test assumption about which candidate is oversized.
9. `engine/tests/config_startup.rs:215-245` can fail during LanceDB open before reaching the intended BM25 build-failure assertion.

### Suggestions

1. Replace the embedding constant fallback and dense `unwrap_or_default()` with explicit fail-closed gRPC errors.
2. Require non-empty citations whenever `answer_basis` is `Retrieval` or `Mixed`.
3. Distinguish valid zero-match filters from invalid client arguments before prompt assembly.
4. Pass effective prompt and output limits into the OpenRouter adapter instead of using constants.

### Risk Assessment

- **RAG-04:** Low risk; the reranker port is clean, tested, and correctly positioned.
- **RAG-02 happy path:** Low risk under valid conditions.
- **RAG-02 operational/security:** High risk because embedding and dense-search failures can be silently converted into arbitrary or lexical-only retrieval without disclosure.

### Reviewer Limitations

This was a static source and architecture review. Live provider calls were evaluated through test mocks rather than external OpenRouter requests.

## Consensus Summary

Only Antigravity was requested and available for this review, so the following is a single-reviewer synthesis rather than multi-reviewer consensus.

### Agreed Strengths

- RAG-04 NoOp reranker wiring is complete and correctly placed after fusion.
- The valid-query cross-runtime happy path and gateway body bounds are strong.

### Agreed Concerns

- Failure handling must be fail-closed: embedding and dense retrieval failures must not silently fabricate or weaken evidence.
- Grounding validation and configured generation limits need stronger runtime enforcement.

### Divergent Views

- No multi-reviewer divergence was available; run another external reviewer if broader consensus is needed.
