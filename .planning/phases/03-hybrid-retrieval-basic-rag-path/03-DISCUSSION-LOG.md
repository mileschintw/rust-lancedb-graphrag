# Phase 3: Hybrid Retrieval & Basic RAG Path - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-30
**Phase:** 3-Hybrid Retrieval & Basic RAG Path
**Areas discussed:** Hybrid ranking and deduplication, Metadata scope and filtering, Degraded-mode and insufficient-evidence behavior, Answer/citation/API contract, Cross-index freshness and re-ingestion visibility, Prompt trust boundary, Generation limits and provider failure behavior, BM25 text analysis and field semantics, Deterministic ranking and reproducibility, Query validation and request bounds, Generation style and sampling defaults

---

## Hybrid Ranking and Deduplication

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Fusion | Reciprocal Rank Fusion | Normalized weighted scores; union and deduplicate |
| Duplicate identity | `chunk_id`, retaining both source ranks | `content_hash`; preserve both results |
| Path weights | Equal `1.0` defaults with overrides | Fixed equal weights; vector-biased default |
| RRF constant | Configurable, default `k = 60` | Fixed `k = 60`; derive from pool size |

**User's choice:** Selected the recommended option for all four decisions.
**Notes:** Existing configurable candidate/final limits and the Phase 999.2 `NoOpReranker` port carry forward.

---

## Metadata Scope and Filtering

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Exposed filters | Document IDs and content types | Document IDs only; all approved metadata fields |
| Boolean logic | OR within fields, AND across fields | AND everywhere; user-authored Boolean expressions |
| Filter timing | Apply to both paths before fusion | Post-fusion; asymmetric vector/BM25 timing |
| Invalid/unmatched values | Validate syntax; valid zero matches are allowed | Reject unknown values; map every invalid value to no matches |

**User's choice:** Selected the recommended option for all four decisions.
**Notes:** Global-corpus search remains the default when filters are absent.

---

## Degraded Mode and Insufficient Evidence

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| One path fails | Continue with either surviving path | Only vector-to-BM25 fallback; fail all partial retrieval |
| Client disclosure | Structured degraded status and warnings | Answer-text warning; logs only |
| Weak/empty/unneeded evidence | Always permit generation and model-owned knowledge | Abstain on zero candidates; minimum fused-score gate |
| Basis decision | Generation-time classification | Separate relevance call; empty-results-only rule |
| Both paths fail | Continue with disclosed model-only answer | Retrieval error; configurable strictness |

**User's choice:** Selected the recommended option except for the initial insufficient-evidence question, where the user explicitly chose always to call the LLM.
**Notes:** User clarification: “even allow LLM works solely if the searched data is too weak or unneeded… Do mention we use solely LLM when this happen.” This produced the explicit `retrieval` / `mixed` / `model_only` contract and human-readable model-only notice.

---

## Answer, Citation, and API Contract

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| HTTP route | Unary `POST /rag/query` | `POST /query`; session-nested route |
| Citation shape | Structured evidence object | IDs only; display text only |
| Claim linkage | Inline numbered markers plus objects | Objects only; source names inline |
| Invalid citation | Validate, repair once, then transparent model-only downgrade | Fail request; return unchanged |
| Provider boundary | Provider-neutral Rust trait, OpenRouter default | OpenRouter-only; OpenAI-compatible wire contract |
| Session behavior | Validate supplied ID or generate UUID; always return it | Echo only; require ID |
| Citation excerpt | Bounded relevant passage with truncation status | Whole chunk; no source text |
| Model-only disclosure | Machine-readable basis plus separate human notice | Prefix answer; basis field only |

**User's choice:** Selected the recommended option for all eight decisions.
**Notes:** Streaming remains outside Phase 3.

---

## Cross-Index Freshness and Re-ingestion Visibility

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Meaning of `completed` | Vector and BM25 both query-ready | Vector ready/BM25 eventual; storage only |
| Re-ingestion visibility | Previous completed version until atomic replacement | Temporary absence; expose indexes independently |
| Restart readiness | Rebuild BM25 before serving queries | Early vector-only degradation; lazy rebuild |
| Rebuild failure | Fail startup clearly | Persistent degraded mode; selectively reject retrieval |

**User's choice:** Selected the recommended option for all four decisions.
**Notes:** Runtime retrieval failures may degrade to model-only, but failure to establish the startup index invariant is fail-fast.

---

## Prompt Trust Boundary and Retrieved Instructions

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Retrieved instructions | Untrusted evidence only | Follow domain instructions; provider decides |
| Prompt framing | Isolated structured evidence blocks | Concatenated context; summaries only |
| Injection-like text | Keep as marked evidence, never obey, flag diagnostically | Exclude; fail query |
| Evidence/model conflict | Prefer corpus evidence and disclose conflict | Prefer model; refuse all conflicts |

**User's choice:** Selected the recommended option for all four decisions.
**Notes:** Conflicting external model knowledge is separated and makes the answer basis `mixed`.

---

## Generation Limits and Provider Failure Behavior

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Retries | No retries in Phase 3 | One transient retry; match ingestion retries |
| Timeout | Configurable, default 30 seconds | Default 60 seconds; provider-only timeout |
| Context packing | Reserve answer tokens, then whole chunks in RRF order | Fixed top-N; blind truncation |
| Generation failure | Structured provider error, no fabricated answer | Extractive fallback; alternate provider |

**User's choice:** Chose no retries rather than the recommended one-retry option; selected the recommended option for the other three decisions.
**Notes:** Retry and provider-fallback orchestration is intentionally deferred to Phase 5.

---

## BM25 Text Analysis and Field Semantics

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Tokenization | Unicode-aware lowercase, no stemming/stop-word removal | English analyzer; whitespace split |
| Fields | Content, title, section path | Content only; all string metadata |
| Multi-term match | Any term may match; cumulative BM25 relevance | Require all; phrase/proximity boost |
| Technical IDs | Whole token plus camel/snake/kebab subtokens | Whole only; subtokens only |
| Parameters | Configurable `k1 = 1.2`, `b = 0.75` | Fixed; corpus-derived |
| Field boosts | Content `1.0`, title `2.0`, section path `1.5` | All `1.0`; title-heavy |
| Unicode normalization | NFKC plus Unicode case folding | Lowercase only; none |
| IDF population | Global completed corpus | Filtered subset; per-content-type statistics |

**User's choice:** Selected the recommended option for all eight decisions.
**Notes:** Original source text remains unchanged for citations.

---

## Deterministic Ranking and Reproducibility

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Tie-break chain | Best source rank, document ID, chunk index, chunk ID | Vector-first; storage order |
| Score precision | Full internally, rounded only for API diagnostics | Pre-ranking rounding; hide scores |
| Response provenance | Compact retrieval snapshot | Logs only; index generation only |
| Guarantee | Exact ordered IDs for same query/filter/index/config | Candidate-set only; best effort |

**User's choice:** Selected the recommended option for all four decisions.
**Notes:** The exact guarantee applies to retrieval, not necessarily generated wording.

---

## Query Validation and Request Bounds

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Empty query | Reject before retrieval/provider calls | Conversational response; model-only response |
| Query limit | Configurable 8 KiB UTF-8 | 4,096 characters; provider limit |
| Filter limits | 100 document IDs, 16 content types by default | Tighter limits; unbounded |
| Query normalization | Preserve original semantics; derive retrieval views | Normalize once everywhere; raw everywhere |

**User's choice:** Selected the recommended option for all four decisions.
**Notes:** Filter values are normalized and deduplicated before limits are enforced.

---

## Generation Style and Sampling Defaults

| Decision | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Sampling | Temperature `0`, top-p `1`, configurable | Temperature `0.2`; provider defaults |
| Output budget | Configurable 2,048 tokens | 1,024; 512 |
| Model output | Validated structured schema | Free-form marker parsing; multiple calls |
| Writing style | Direct answer first, proportional supported detail | Fixed sections; provider/model discretion |

**User's choice:** Selected deterministic sampling, structured output, and direct-answer-first style. Chose the larger 2,048-token output budget instead of the recommended 1,024-token default.
**Notes:** Inline citations remain close to supported claims without imposing a fixed response template.

---

## the agent's Discretion

- Exact internal module layout and error type names.
- Configuration key names.
- Fixed score-display precision.
- Default citation-excerpt limit.
- Initial configurable OpenRouter generation model.

## Deferred Ideas

- Phase 4: graph context extraction and graph contribution to prompts.
- Phase 5: state machine, streaming events, node retries, and provider fallback.
- Phase 6: evaluation-driven tuning, observability, and benchmark claims.
- Phase 999.2: non-NoOp reranker implementations.
