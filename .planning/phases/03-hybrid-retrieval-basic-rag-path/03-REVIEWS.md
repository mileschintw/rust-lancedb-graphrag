---
phase: 03
reviewers: [agy]
reviewed_at: 2026-08-04T12:59:15Z
plans_reviewed: [03-01-PLAN.md, 03-02-PLAN.md, 03-03-PLAN.md, 03-04-PLAN.md, 03-05-PLAN.md, 03-06-PLAN.md, 03-07-PLAN.md, 03-08-PLAN.md, 03-09-PLAN.md, 03-10-PLAN.md, 03-11-PLAN.md, 03-12-PLAN.md, 03-13-PLAN.md, 03-14-PLAN.md, 03-15-PLAN.md]
---

# Cross-AI Plan Review — Phase 03

## AgY Review

### Summary

This cross-AI plan review evaluates the implementation plans and live repository state for Phase 03 — Hybrid Retrieval & Basic RAG Path in Lancet. The review verified the full end-to-end request lifecycle across the Go API gateway (`gateway/`), gRPC service boundary (`proto/lancet/v1/lancet.proto`), Rust RAG engine (`engine/`), hybrid vector/BM25 retrieval engine (`engine/src/retrieval/`), evidence assembly (`engine/src/prompt.rs`), provider-neutral LLM generation adapter (`engine/src/generation/`), and citation resolution.

The plans successfully establish a modular, provider-neutral architecture that combines dense LanceDB vector search with an in-memory Unicode-aware BM25 index using Reciprocal Rank Fusion (RRF). However, severe discrepancies exist between the plan claims, the recorded design contracts (`03-CONTEXT.md`, `03-AI-SPEC.md`), and the actual implementation in `engine/src/main.rs` and `gateway/main.go`. Most notably, silent fallbacks for embedding/dense retrieval errors violate fail-closed principles, valid zero-result queries are incorrectly mapped to HTTP 400 Bad Request errors, and documentation drift leaves completed plans marked as unexecuted in `ROADMAP.md`.

### Strengths

1. **Provider-Neutral Trait Design**: The async `Generator` trait (`engine/src/generation/mod.rs:27-40`) decouples the core RAG data plane from vendor-specific LLM SDKs, allowing OpenRouter to serve as an injectable adapter without lock-in.
2. **Pluggable Reranker Port (RAG-04)**: The `Reranker` trait (`engine/src/rerank/mod.rs:15-30`) and `NoOpReranker` implementation fulfill requirement RAG-04, creating a clean extension point for cross-encoder reranking (Phase 999.2).
3. **Full Unicode Lexical Analysis**: The BM25 tokenizer (`engine/src/retrieval/bm25.rs:45-120`) applies NFKC normalization, full Unicode case-folding, and technical sub-token splitting (camelCase, underscores, hyphens) per D-44..D-48 without destructive stemming.
4. **Structured Evidence Boundary & Escaping**: Prompt assembly (`engine/src/prompt.rs:80-160`) treats retrieved text strictly as untrusted evidence, assigning engine-generated block IDs and escaping delimiter-like text to prevent prompt injection.
5. **Request Identity & Error Context Propagation**: Trailer metadata (`x-lancet-session-id`, `x-lancet-correlation-id`, `x-lancet-error-kind`) in tonic gRPC responses (`engine/src/main.rs:1049-1058`) is correctly copied by the Go gateway into client HTTP headers (`gateway/main.go:692-703`) for observability.

### Concerns

#### 1. Silent Degradation & Fallback on Embedding/Dense Failures Violates Fail-Closed Contract

- **Severity**: HIGH
- **Plan ID(s)**: `03-02-PLAN.md`, `03-03-PLAN.md`, `03-06-PLAN.md`, `03-13-PLAN.md`
- **File:Line Evidence**: `engine/src/main.rs:967-984`
- **Mechanism**: `03-AI-SPEC.md` and `03-CONTEXT.md` state that degraded retrieval is deferred (`DEBT-RAG-01`) and is not part of Phase 03 acceptance. Phase 03 therefore requires failing closed on retrieval error. However, `engine/src/main.rs:973` catches embedding errors and silently falls back to a fake constant vector `vec![0.25; 2048]`. Furthermore, `engine/src/main.rs:984` uses `.unwrap_or_default()` on `dense_retriever.query()`, converting LanceDB or snapshot failures into an empty candidate list. This conceals backend failure as a clean zero-result search and permits generation to proceed with ungrounded or weakened evidence.
- **Recommendation**: Remove the constant-vector fallback and `.unwrap_or_default()` call. Propagate embedding and dense retrieval errors immediately as typed `tonic::Status::unavailable` or `tonic::Status::internal` results.

#### 2. Valid Zero-Result Filter Queries Mapped to HTTP 400 Bad Request

- **Severity**: HIGH
- **Plan ID(s)**: `03-03-PLAN.md`, `03-04-PLAN.md`, `03-05-PLAN.md`, `03-12-PLAN.md`
- **File:Line Evidence**: `engine/src/main.rs:1011-1019`, `engine/src/prompt.rs:202-204`, `gateway/main.go:705-708`
- **Mechanism**: Decision D-10 specifies that valid filters matching no documents produce empty evidence rather than a validation error. When a valid query has no matches, prompt packing returns `PromptError::EmptyEvidence`, the engine maps it to `tonic::Status::invalid_argument`, and the gateway translates `InvalidArgument` to HTTP 400. Clients therefore receive an invalid-request error instead of a valid zero-result response or a distinct no-evidence outcome.
- **Recommendation**: Handle an empty final candidate list before prompt packing by constructing a valid zero-result response or a distinct server-side outcome. Reserve `InvalidArgument` strictly for malformed input such as invalid UUIDs or oversized requests.

#### 3. HTTP 200 OK Committed Before JSON Encoding Validates Float Values

- **Severity**: HIGH
- **Plan ID(s)**: `03-01-PLAN.md`, `03-03-PLAN.md`, `03-04-PLAN.md`
- **File:Line Evidence**: `gateway/main.go:713, 723-727`, `engine/src/retrieval/fusion.rs:123-134`
- **Mechanism**: `writeJSON` writes the HTTP status before encoding the response and ignores the encoder error. If RRF weights or scores produce `NaN` or `+Inf`, Go JSON encoding fails after HTTP 200 has been committed, yielding a truncated or malformed successful response.
- **Recommendation**: Marshal into a buffer before calling `WriteHeader`; return HTTP 500 if encoding fails. Also validate that every fused score is finite before constructing the protobuf response.

#### 4. Roadmap & Plan Tracking Drift (Plans 13–15 Unmarked in Roadmap)

- **Severity**: MEDIUM
- **Plan ID(s)**: `03-13-PLAN.md`, `03-14-PLAN.md`, `03-15-PLAN.md`
- **File:Line Evidence**: `.planning/ROADMAP.md:139-195` versus the three corresponding `*-SUMMARY.md` files
- **Mechanism**: The roadmap records 12/15 plans executed and leaves Waves 11–13 unchecked, while the three summary files and their source changes show execution on 2026-08-04. This documentation drift makes external reviewers and planning tools see Phase 03 as incomplete.
- **Recommendation**: Update roadmap plan counters and check off 03-13, 03-14, and 03-15 only after reconciling the post-execution verification result. Do not mark the phase complete from summaries alone.

#### 5. Response Token Usage Validation Evaluates Static Defaults Rather Than EffectiveRagSettings

- **Severity**: MEDIUM
- **Plan ID(s)**: `03-07-PLAN.md`, `03-13-PLAN.md`, `03-14-PLAN.md`
- **File:Line Evidence**: `engine/src/generation/mod.rs:75-77, 157-180`, `engine/src/main.rs:1062-1076`
- **Mechanism**: `ModelOutput::validate_grounding` validates prompt and completion usage against hardcoded defaults (`8192` and `2048`) rather than active `EffectiveRagSettings`. A configured evidence budget above 8192 can reject valid responses, while a smaller configured budget is not enforced consistently.
- **Recommendation**: Pass `EffectiveRagSettings` or explicit active limits into grounding validation and remove duplicate default-only enforcement from the runtime path.

#### 6. BM25 Index Invalidation & Ingestion Replay Lifecycle Gap

- **Severity**: MEDIUM
- **Plan ID(s)**: `03-01-PLAN.md`, `03-03-PLAN.md`, `03-11-PLAN.md`
- **File:Line Evidence**: `engine/src/main.rs:986-991, 1568-1607`, `engine/src/retrieval/bm25.rs:180-220`
- **Mechanism**: `Bm25Index` is instantiated once during startup. Ingestion changes vector entries in LanceDB, but no update or rebuild is made to the in-memory BM25 index. Dense retrieval can therefore see updated chunks while lexical retrieval remains stale. Atomic cross-index lifecycle switching is deferred, but the absence of invalidation creates immediate divergence after document changes in a running process.
- **Recommendation**: Add explicit BM25 invalidation or atomic snapshot publication when ingestion completes, or preserve a clearly documented status that lexical index lag is out of scope.

#### 7. Duplicate Candidate RRF Score Inflation

- **Severity**: LOW
- **Plan ID(s)**: `03-01-PLAN.md`
- **File:Line Evidence**: `engine/src/retrieval/fusion.rs:103-154`
- **Mechanism**: `fuse_candidates` adds the RRF contribution for every duplicate returned by one source while retaining only the first rank. A duplicated `chunk_id` can therefore receive inflated fused scores.
- **Recommendation**: Deduplicate candidates per source by `chunk_id` before applying source rank contributions.

### Coverage and Traceability

| Requirement | Plan Ownership | Repository Trace | Status |
|---|---|---|---|
| RAG-02 Hybrid Retrieval & Fusion | 03-01, 03-03, 03-12 | `engine/src/retrieval/fusion.rs`, `engine/src/main.rs:976-998` | Partially verified; functional happy path is compromised by silent retrieval fallback, zero-result mapping, score serialization, and BM25 lifecycle concerns. |
| RAG-04 Pluggable Reranker Seam | 03-01, 03-12 | `engine/src/rerank/mod.rs`, `engine/src/main.rs:1000-1005` | Verified as an async `Reranker` trait with `NoOpReranker`; the review did not identify a current implementation blocker in the seam. |
| RAG-03 Degraded Mode & Fallbacks | Deferred (`DEBT-RAG-01` through `DEBT-RAG-06`) | `deferred-items.md:19-74` | Correctly isolated as deferred, but silent fallbacks in `main.rs` violate the fail-closed assumptions of that scope fence. |

### Risk Assessment

1. **Grounding and integrity**: Silent embedding and dense-search fallback can return irrelevant context while presenting a retrieval-backed answer.
2. **API contract**: Valid zero-result queries returning HTTP 400 break the distinction between malformed input and empty corpus matches.
3. **Transport correctness**: Non-finite fused scores can cause an ignored JSON encoding error after HTTP 200 is committed.
4. **Auditability**: Roadmap drift makes executed plans appear incomplete and can misroute future GSD actions.

### Reviewer Limitations

- No live OpenRouter API invocation was performed; provider behavior was assessed through source and mock contracts.
- No build, test, or binary execution was performed during this read-only plan review.
- The review is one external reviewer’s assessment; the local `03-REVIEW.md` is the independent source-code quality gate.

## Consensus Summary

Only AgY was requested and available, so this is a single-reviewer synthesis rather than a multi-reviewer consensus.

### Agreed Strengths

- The provider-neutral generator and async reranker seams are cleanly separated from vendor implementations.
- Unicode-aware BM25, structured evidence escaping, deterministic fusion, and identity-bearing error propagation are well-founded.
- The valid dense-plus-BM25 happy path and Go-to-Rust request lifecycle are represented by executable tests and deferred scope is documented.

### Agreed Concerns

- The refreshed local code review independently identifies the same high-priority fail-closed and zero-result contract risks: embedding/dense failures are silently weakened and valid no-match queries are mapped to HTTP 400.
- Both reviews identify runtime-limit/configuration mismatches and non-finite score/response handling as remaining quality risks.
- BM25 lifecycle invalidation and roadmap tracking require explicit reconciliation before any phase-completion claim.

### Divergent Views

- AgY also flags plan-level concerns about duplicate per-source RRF contributions and the long-term reranker interface; these are lower-severity or future-extension concerns than the local code-review blockers and should be evaluated during gap planning.
