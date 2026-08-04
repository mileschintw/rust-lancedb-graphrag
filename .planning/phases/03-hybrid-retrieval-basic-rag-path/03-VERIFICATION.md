---
phase: 03-hybrid-retrieval-basic-rag-path
verified: 2026-08-04T09:04:52Z
status: gaps_found
score: "49/54 must-haves verified"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: "7/15"
  gaps_closed:
    - "The injected Reranker/NoOpReranker seam is now present, wired after fusion, and covered by focused service tests."
    - "The Go /rag/query body is bounded at 32 KiB, closes the body, and rejects oversized requests before the engine call."
    - "Unicode evidence encoding, complete-block packing, bounded excerpts, and the basic unknown-marker rejection path are implemented and tested."
  gaps_remaining:
    - "The retrieval-backed output contract still accepts model_only and citationless retrieval answers."
    - "The production OpenRouter adapter repacks evidence with hardcoded 8192/2048 limits instead of the effective runtime settings."
    - "Provider failures lose the available session/correlation identity, startup accepts a fake credential fallback, and the locked Rust suite still has one failing test."
  regressions:
    - "The current checkout's full Rust suite fails query_rag_citation_identity_and_notices in both parallel and serial runs; its single-test invocation passes."
gaps:
  - truth: "RSC-1 / P09 / P24: only a complete retrieval-backed provider result with valid evidence markers can reach the public QueryRAG response."
    status: failed
    reason: "ModelOutput::validate_grounding checks known, duplicate, and inline marker identity but does not require citations for retrieval/mixed output or reject model_only for this Phase 03 path. The OpenRouter schema also has no answer, array, or item size bounds."
    artifacts:
      - path: "engine/src/generation/mod.rs"
        issue: "validate_grounding compares cited IDs with inline markers but permits an empty equal set and does not constrain answer_basis."
      - path: "engine/src/generation/openrouter.rs"
        issue: "The strict schema enumerates model_only and leaves answer/notices/warnings/ID arrays unbounded."
      - path: "engine/src/main.rs"
        issue: "query_rag maps every accepted ModelOutput into QueryRAGResponse without a Phase 03 retrieval-backed basis/citation guard."
    missing:
      - "Reject model_only and citationless retrieval/mixed output before response assembly, or explicitly revise the Phase 03 contract."
      - "Add bounded output fields/array limits at the provider boundary and a named regression for these cases."
  - truth: "P25 / P41: one validated EffectiveRagSettings value controls production retrieval, evidence, provider, and generation behavior."
    status: failed
    reason: "query_rag uses configured evidence_token_budget and max_output_tokens, but OpenRouterGenerator::execute_one_call repacks the same evidence with literal 8192 and 2048 values. The configured service tests use a recording generator and therefore do not exercise this production adapter path."
    artifacts:
      - path: "engine/src/generation/openrouter.rs"
        issue: "pack_evidence_prompt(&request.question, &request.evidence, 8192, 2048) bypasses effective settings."
      - path: "engine/src/main.rs"
        issue: "Production startup constructs the adapter from EffectiveRagSettings, but the adapter does not consume all relevant limits from that object."
    missing:
      - "Pass the effective prompt/output limits through the provider-neutral request/configuration and assert a non-default production-adapter request."
  - truth: "D-31 generation failures preserve session/correlation identity in a structured provider error without fabricating an answer."
    status: failed
    reason: "query_rag sets session_id but never sets correlation_id, and maps GenerationError to a plain tonic Status using only err.message(), discarding the error's retained identity fields."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "gen_req.correlation_id is never populated and the error mapper drops GenerationError.session_id/correlation_id."
      - path: "engine/src/generation/mod.rs"
        issue: "The identity fields exist, but no service-level response/status path consumes them."
    missing:
      - "Generate/propagate a correlation identity and expose session/correlation metadata in the provider failure boundary."
  - truth: "P41: production startup must construct a usable configured provider path from validated settings and explicit credentials."
    status: failed
    reason: "Missing OPENROUTER_API_KEY is replaced with the literal fake-key value, allowing the engine to announce readiness with a provider configuration that cannot make a real request."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "main() uses std::env::var(\"OPENROUTER_API_KEY\").unwrap_or_else(|_| \"fake-key\".to_owned())."
    missing:
      - "Fail closed on a missing production credential, or make the test-only credential injection explicit and unreachable in production startup."
  - truth: "The current locked Rust regression gate passes for the completed Phase 03 checkout."
    status: failed
    reason: "cargo test --manifest-path engine/Cargo.toml --locked failed in both the parallel and -- --test-threads=1 runs: 70 engine binary tests passed, one failed, one was ignored. The failure is query_rag_citation_identity_and_notices at engine/src/tests.rs:2851 (assertion sc.is_truncated); the focused named test passes alone."
    artifacts:
      - path: "engine/src/tests.rs"
        issue: "The citation/truncation assertion is order-sensitive or otherwise not isolated under the full binary test target."
    missing:
      - "Make the citation fixture/assertion deterministic and rerun the complete locked Rust gate."
deferred:
  - truth: "Degraded vector/BM25/provider behavior and model-only fallback"
    addressed_in: "Phase 06 / DEBT-RAG-01 and DEBT-RAG-06"
    evidence: "deferred-items.md states Phase 03 requires both retrieval paths to succeed and Phase 06 owns degraded/model-only acceptance."
  - truth: "Citation repair/downgrade after invalid markers"
    addressed_in: "Phase 06 / DEBT-RAG-03"
    evidence: "03-CONTEXT.md D-24 and roadmap Phase 06 SC7 defer repair."
  - truth: "Dynamic BM25 re-ingestion/restart switching and recovery"
    addressed_in: "Phase 06 / DEBT-RAG-04"
    evidence: "03-CONTEXT.md D-41 through D-43 and roadmap Phase 06 SC7 own lifecycle behavior."
  - truth: "Exhaustive unmatched, malformed, oversized, and combinatorial filter contract"
    addressed_in: "Phase 06 / DEBT-RAG-05"
    evidence: "COVERAGE.md and deferred-items.md preserve the future negative-input matrix."
  - truth: "Graph-unavailable RAG-03 fallback"
    addressed_in: "Phase 04 seam plus Phase 06 hardening / DEBT-RAG-06"
    evidence: "Phase 04 owns graph context; Phase 03 is source-chunk-only."
---

# Phase 03: Hybrid Retrieval & Basic RAG Path Verification Report

**Phase Goal:** As a chat service API user, I want to ask a question using hybrid vector and BM25 retrieval, so that the LLM returns an answer grounded in completed corpus evidence.

**Verified:** 2026-08-04T09:04:52Z
**Status:** gaps_found
**Re-verification:** Yes — fresh verification after the prior `gaps_found` report; summaries, the prior report, and both review artifacts were treated as claims to re-check.

## User Flow Coverage

The roadmap marks this phase `mode: mvp`, and the goal passes the canonical user-story validator. The API-user flow is observable in the current checkout, but the final outcome is blocked by the provider-output contract gaps below.

| Step | Expected | Evidence | Status |
|------|----------|----------|--------|
| Ask | POST a valid question to `/rag/query` with an optional typed filter and session ID. | `gateway/main.go:630-667`, `engine/src/main.rs:922-965` | ✓ |
| Retrieve | The Rust engine searches dense LanceDB rows and the completed-corpus BM25 snapshot, fuses and reranks the candidate pool. | `engine/src/main.rs:967-1009`, `engine/src/retrieval/{dense,bm25,fusion}.rs`, `engine/src/rerank/mod.rs` | ✓ |
| Generate | The selected evidence is encoded and sent through one strict structured generation call. | `engine/src/prompt.rs:180-243`, `engine/src/generation/openrouter.rs:283-440` | ✓ on the valid local mock path |
| See grounded answer | The LLM answer is retrieval-backed and every citation resolves to the selected completed-corpus evidence. | `gateway/main_test.go:1600-1900` passes locally, but `engine/src/generation/mod.rs:71-123` permits citationless retrieval/model-only output. | ✗ BLOCKED |

## Goal Achievement

### Observable Truths

The roadmap success criteria are mandatory. Plan truths that clearly restated the initial-BM25 criterion are deduplicated into RSC-3 and counted once; all other plan-specific truths are included below. `Pxx` refers to the corresponding `must_haves.truths` item in `03-xx-PLAN.md`.

| # | Truth | Status | Evidence |
|---:|---|---|---|
| RSC-1 | A valid query with successful dense and BM25 retrieval produces deterministic bounded evidence, one structured answer, and citations resolving to that evidence. | ✗ FAILED | The local cross-runtime happy path passes, but the response guard accepts an empty citation set for retrieval output and accepts `model_only`; see `engine/src/generation/mod.rs:71-123` and Gap 1. |
| RSC-2 | Go `/rag/query` receives the retrieval-grounded structured answer through Rust gRPC. | ✓ VERIFIED | `go test -count=1 ./...` and focused `TestRAGQueryCrossRuntime` both pass; the test exercises real Go HTTP, Rust process, generated Ping, local embedding/metadata/chat mocks, and structured citations. |
| RSC-3 | Initial BM25 construction completes before query readiness, and an initial build failure prevents serving. | ✓ VERIFIED | `engine/src/main.rs:1708-1770` builds BM25 before the serving log; `initial_bm25_ready_before_serving`, `initial_bm25_failure_blocks_readiness`, and `invalid_rag_settings_block_readiness` pass as focused tests. |
| RSC-4 | A pluggable async `Reranker` trait and NoOp pass-through implementation exist. | ✓ VERIFIED | `engine/src/rerank/mod.rs:11-40`, production injection at `engine/src/main.rs:1762`, and focused one-call/order/failure tests pass. |
| P01 | Rust builds a Unicode-aware BM25 snapshot from completed LanceDB rows while preserving evidence metadata. | ✓ VERIFIED | `engine/src/retrieval/bm25.rs:171-304` preserves candidate fields and uses NFKC/case folding/UAX analysis; `bm25_full_unicode_analyzer_and_global_idf` and startup fixtures pass. |
| P02 | Dense and BM25 paths use one validated filter model, weighted full-precision RRF, deterministic deduplication by chunk ID. | ✓ VERIFIED | `engine/src/retrieval/mod.rs:75-203`, `dense.rs:41-84`, and `fusion.rs:36-125`; `retrieval_filter_fusion_and_determinism` passes. |
| P03 | NoOpReranker is object-safe async and preserves every fused candidate field and order. | ✓ VERIFIED | `engine/src/rerank/mod.rs:11-40`; reranker unit test and `query_rag_noop_reranker_preserves_fused_order` pass. |
| P04 | The retrieval core is repeatable for the same normalized query, filters, snapshot, and settings; dynamic replacement/restart remains debt. | ✓ VERIFIED | Deterministic fusion/retrieval tests and opaque generation test pass; dynamic lifecycle is explicitly deferred as DEBT-RAG-04. |
| P05 | An ordered candidate set becomes bounded isolated evidence and one strict provider-neutral generation request. | ✓ VERIFIED | `engine/src/prompt.rs:22-243` creates complete encoded blocks; `GenerationRequest` is passed once by `query_rag`; local cross-runtime and generation tests pass. |
| P06 | Valid numbered markers resolve only to engine evidence with bounded excerpts and provenance. | ✓ VERIFIED | `engine/src/prompt.rs:280-324` resolves by evidence ID/chunk identity and Unicode-bounds excerpts; focused citation and cross-runtime checks pass. |
| P07 | Suspicious corpus text remains marked data and valid corpus conflict can disclose a mixed basis. | ✓ VERIFIED | `prompt.rs:146-178` and generation tests `adversarial_evidence_fields_cannot_forge_prompt_boundary`, `suspicious_evidence_remains_marked_unexecuted`, and `corpus_conflict_returns_mixed_basis_with_disclosure` pass. |
| P08 | OpenRouter performs a capability check followed by one timeout-bounded structured call; tests remain provider-independent. | ✓ VERIFIED | `engine/src/generation/openrouter.rs:214-285,350-450`; supported-parameters, finish-reason, one-call, and timeout tests pass against local mocks. |
| P09 | Phase 03 accepts only the valid retrieval-backed branch while retaining future typed basis/notice capacity. | ✗ FAILED | `answer_basis` includes `model_only` in the provider schema and `validate_grounding` has no basis/citation requirement; this violates the accepted valid-path contract even though degraded behavior itself is deferred. |
| P10 | QueryRAG's additive gRPC contract carries filters, session, structured citations, basis, notices/warnings, and snapshot without renumbering fields. | ✓ VERIFIED | `proto/lancet/v1/lancet.proto:44-109`, generated Rust/Go bindings, `buf lint`, and Go/Rust compilation/tests pass. |
| P11 | A valid gRPC QueryRAG call reaches retrieval, NoOpReranker, evidence, and Generator and returns the structured response. | ✓ VERIFIED | `engine/src/main.rs:922-1129`, focused Rust service tests, and `TestRAGQueryCrossRuntime` pass. |
| P13 | Committed TOML and environment overlays expose locked retrieval/generation bounds and defaults; lifecycle switching remains DEBT-RAG-04. | ✓ VERIFIED | `config/config.toml`, `config/config.example.toml`, `EffectiveRagSettings`, config-startup tests, and the example contract test agree on the key set. |
| P14 | Go accepts a bounded strict `/rag/query` envelope, forwards context/typed fields, and maps caller validation failures to HTTP 400. | ✓ VERIFIED | `gateway/main.go:630-675`; focused malformed/trailing/oversized/filter and full Go tests pass. |
| P15 | Gateway preserves session, structured basis, notices/warnings, citations, and retrieval snapshot without reimplementing semantics. | ✓ VERIFIED | `gateway/main.go:656-675`, `TestRAGQueryValidMapping`, and the real cross-runtime response assertions pass. |
| P16 | The Rust embedding client targets a configured endpoint while retaining production defaults and its existing retry/timeout behavior. | ✓ VERIFIED | `engine/src/client/mod.rs:20-145,180-250`; endpoint, model, retry, timeout, and redaction tests pass. |
| P17 | A provider-independent process smoke runs the real Rust engine against an isolated LanceDB corpus and real Go route. | ✓ VERIFIED | `gateway/main_test.go:1600-1900`; focused `TestRAGQueryCrossRuntime` passes. |
| P18 | The deterministic mock exercises embedding, model capability, strict chat, dense/BM25 retrieval, fusion, evidence, and generation without OpenRouter/PostgreSQL. | ✓ VERIFIED | `gateway/main_test.go` tracks all three mock endpoints and asserts dense and lexical fixture markers; focused smoke passes. |
| P19 | The serving log is only a milestone; generated-gRPC Ping succeeds before `/rag/query`. | ✓ VERIFIED | Cross-runtime test probes the exact configured loopback address after the serving log and before calling the Go route. |
| P20 | Child environments are exact and teardown reaps processes and releases the isolated LanceDB path on Windows. | ✓ VERIFIED | `gateway/main_test.go:1890-1960` scrubs/whitelists environment variables, uses process-tree teardown, and rename/removal release proof; Windows-focused smoke passes. |
| P21 | Smoke fixtures/processes are isolated and cleaned; live-provider checking is separate/manual. | ✓ VERIFIED | `t.TempDir`, isolated seeder/engine environment, deferred cleanup, and the current coverage/deferred ledger provide this boundary. |
| P22 | Corpus metadata/content cannot escape the single evidence encoding boundary or become executable prompt instructions. | ✓ VERIFIED | `engine/src/prompt.rs:88-178`; all-field adversarial encoding test passes and preserves `suspicious=true`. |
| P23 | Over-budget first blocks fail closed, no-fit creates no prompt, and Unicode excerpts truncate only at character boundaries. | ✓ VERIFIED | `pack_evidence_prompt` reserves budgets and returns `NoEvidenceFits`; `prompt_rejects_over_budget_first_block_and_unicode_excerpt` passes. |
| P24 | Only complete schema-valid provider output with exact evidence-marker identity reaches response assembly. | ✗ FAILED | Unknown/duplicate/mismatched IDs fail, but empty retrieval citations and `model_only` pass; provider output strings/arrays also have no max bounds. |
| P25 | One validated runtime settings object controls retrieval, evidence, citation, embedding, and generation behavior. | ✗ FAILED | Service-side settings are threaded, but `openrouter.rs:288` repacks with literal 8192/2048; the configured-provider tests do not cover this adapter implementation. |
| P26 | Evidence budget is token-based while citation excerpts independently use Unicode character units. | ✓ VERIFIED | `main.rs:1012-1019`, `prompt.rs:224-243`, and `configured_evidence_token_budget_is_exact` plus Unicode tests pass. The adapter bypass is tracked separately under P25. |
| P27 | Configured provider model identities are retained and reported in persistence/snapshot state. | ✓ VERIFIED | `engine/src/client/mod.rs:126-145`, `main.rs` snapshot construction, and `configured_embedding_identity_persists_and_reports`/provider tests pass. |
| P28 | RetrievalSnapshot reports exact settings and an opaque stable per-service index generation. | ✓ VERIFIED | `snapshot_rrf_k`, `snapshot_limit`, snapshot assembly, and `service_index_generation_is_opaque_and_stable` pass. |
| P29 | Invalid settings fail before database/provider construction or readiness. | ✓ VERIFIED | `main.rs:1701-1712` validates EffectiveRagSettings before DB construction; `invalid_rag_settings_block_readiness` passes. |
| P30 | Bodies over `maxRAGQueryBodyBytes` receive HTTP 413 before engine work. | ✓ VERIFIED | `gateway/main.go:35,630-654`; oversized and huge-filter focused tests pass with zero engine calls and closed bodies. |
| P31 | The 32 KiB boundary accommodates the locked query/filter/session maxima while bounding decoder work. | ✓ VERIFIED | Gateway cap plus 8 KiB query/100 UUID/16 content-type engine limits are present; boundary tests and full Go suite pass. |
| P32 | Gateway closes the body, distinguishes MaxBytesError from malformed JSON, and uses a 60-second ReadTimeout. | ✓ VERIFIED | `gateway/main.go:631-654,701-705`; focused boundary/timeout tests pass. |
| P33 | Cross-runtime happy path remains compatible with strict JSON schema, completion-token, and stop-finish requirements. | ✓ VERIFIED | Local provider mock asserts strict schema, required fields, max completion tokens, stop finish reason, and top-level usage; focused smoke passes. |
| P34 | COVERAGE.md records the HTTP 413 surface without promoting RAG-03/deferred debt. | ✓ VERIFIED | `COVERAGE.md:60-73` and the phase debt ledger preserve the scope fence. |
| P35 | Returned citations resolve by validated evidence ID rather than model position. | ✓ VERIFIED | `prompt.rs:280-304` looks up marker IDs/chunk IDs; `query_rag_citation_identity_and_notices` passes when run alone and asserts rank-2 identity. |
| P36 | Citation identity, metadata, configured Unicode excerpt, and truncation state come from the selected evidence item. | ✓ VERIFIED | `main.rs:1040-1068`; the named citation test passes alone and the cross-runtime test asserts structured provenance. The full-suite isolation failure is reported separately. |
| P37 | Notices and warnings cross the service boundary with deterministic INFO/WARNING severities. | ✓ VERIFIED | `main.rs:1078-1090`; citation/notices test asserts order and enum values. |
| P38 | Unknown evidence identity cannot produce a successful or partial QueryRAG response. | ✓ VERIFIED | `query_rag_rejects_unknown_marker_without_response` passes; response assembly is after validation/resolution and checks resolution cardinality. |
| P39 | Configured embedding model is used in the provider request and reported as persistence/snapshot identity. | ✓ VERIFIED | `client/tests.rs` request capture and `engine/src/tests.rs` configured identity test pass. |
| P40 | Configured generation model/endpoints/timeout/sampling/max completion tokens govern the strict OpenRouter request. | ✓ VERIFIED | `OpenRouterGenerationConfig` fields feed the payload at `openrouter.rs:323-345`; `generation_request_uses_effective_settings` passes. P25 covers the separate hardcoded evidence-pack limits. |
| P41 | Production startup constructs retrieval/prompt/embedding/generation components from one validated EffectiveRagSettings value. | ✗ FAILED | Startup takes most component settings from the effective object, but the provider adapter has its own prompt defaults and startup falls back to `fake-key`; see Gaps 2 and 4. |
| P42 | Configured embedding identity is stable across provider request, persisted metadata, and snapshot; generation is opaque per service. | ✓ VERIFIED | Configured identity and opaque-generation tests pass; source keeps `embedder.model_id()` and `index_generation` in the response path. |
| P43 | Startup does not report readiness until initial BM25 succeeds over a schema-valid completed corpus. | ✓ VERIFIED | `initial_bm25_ready_before_serving` and the schema-valid invalid-content fixture test pass. |
| P44 | Invalid settings and genuine initial BM25 failures exit nonzero with diagnostics and no listener/readiness signal. | ✓ VERIFIED | `config_startup.rs:342-445`; focused invalid-settings and BM25-failure tests pass. |
| P45 | The committed example is deserialized by the real binary Settings/EffectiveRagSettings types, documents exact keys/units/ranges, and assigns no credentials. | ✓ VERIFIED | `config_example_matches_effective_rag_contract` passes; `config/config.example.toml` contains the annotated 24-key contract and environment-only credential guidance. |
| P46 | Production query_rag invokes the injected Reranker once after fusion and before final limiting/evidence packing. | ✓ VERIFIED | `main.rs:993-1011`; `query_rag_invokes_recording_reranker_once` and `query_rag_grounding_uses_reranked_identity` pass. |
| P47 | Startup injects NoOpReranker and preserves fused order. | ✓ VERIFIED | `main.rs:1762` and `query_rag_noop_reranker_preserves_fused_order` pass. |
| P48 | A source with configured weight zero contributes no candidates, ranks, or ordering influence. | ✓ VERIFIED | `fusion.rs:43-74` skips exact-zero sources; symmetric zero-weight tests pass. |
| P49 | Enabled-source RRF remains deduplicated, full-precision, deterministically tie-broken, and repeatable. | ✓ VERIFIED | `fusion.rs:75-125` and retrieval tests pass. |
| P50 | Final reranked/limited evidence identities flow into grounding validation and citation projection. | ✓ VERIFIED | `query_rag_grounding_uses_reranked_identity` passes and asserts generator evidence equals public structured-citation identity. |
| P51 | A reranker error returns no QueryRAG response and skips generation after one reranker call. | ✓ VERIFIED | `query_rag_reranker_failure_skips_generation` passes; `main.rs:1000-1004` propagates the error before generator invocation. |

**Score:** 49/54 truths verified. `P12` (the plan's initial-BM25 truth) is intentionally counted under RSC-3 rather than double-counted. No accepted state-transition/cancellation invariant is presence-only: the named reranker, timeout, startup, and citation tests were run where applicable, so `behavior_unverified: 0`. The full-suite failure is a separate blocking regression gate, not a silent behavior pass.

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `engine/src/retrieval/{mod,bm25,dense,fusion}.rs` | Unicode BM25, typed filters, dense retrieval, weighted RRF/dedup | ✓ VERIFIED | Substantive source, imported by `main.rs`, real LanceDB/BM25 data flows, and focused retrieval tests pass. |
| `engine/src/rerank/mod.rs` and `engine/src/rerank/tests.rs` | Async Reranker port and NoOp implementation | ✓ VERIFIED | Imported/used by `LancetServiceImpl`; production and focused tests confirm call/order/failure behavior. |
| `engine/src/prompt.rs` | Encoded evidence, token packing, Unicode excerpts, citation resolver | ✓ VERIFIED | Substantive and wired to query/generation/response; adversarial, budget, and citation checks pass. |
| `engine/src/generation/mod.rs` | Closed provider-neutral output/error contract | ⚠️ PARTIAL | Serde closure and marker checks exist, but basis/citation cardinality and output-size guards are incomplete. |
| `engine/src/generation/openrouter.rs` | Configured strict OpenRouter adapter | ⚠️ PARTIAL | One-shot capability/timeout/schema path is real, but prompt budgets are hardcoded and response fields are unbounded. |
| `engine/src/main.rs` | Rust service/query/startup integration | ⚠️ PARTIAL | Fully wired and data-flowing on the local happy path; fallback, fake-key, settings, and error-identity gaps remain. |
| `proto/lancet/v1/lancet.proto` plus generated Rust/Go bindings | Additive QueryRAG contract | ✓ VERIFIED | `buf lint`, compilation, and cross-runtime mapping pass. |
| `gateway/main.go` and `gateway/main_test.go` | Thin bounded `/rag/query` HTTP boundary | ✓ VERIFIED | Strict decoding, 32 KiB cap, timeout, forwarding, and local process smoke pass. |
| `engine/src/client/mod.rs` and tests | Configured embedding endpoint/model/retry seam | ✓ VERIFIED | Endpoint/model capture, timeout, retries, concurrency, and redaction tests pass. The artifact query's `embedding_endpoint` pattern was a false negative; manual source inspection confirms the field and use. |
| `config/config.toml` and `config/config.example.toml` | Effective non-secret RAG settings | ✓ VERIFIED | Example contract test passes; tracked local config contains development DB defaults but no provider secret. |
| `engine/tests/config_startup.rs`, `engine/src/tests.rs`, `gateway` smoke | Executable startup/service evidence | ⚠️ PARTIAL | Focused tests and smoke pass, but the full locked Rust suite fails one citation assertion. |

The GSD artifact query reported all listed artifacts present/substantive for Plans 03-01 through 03-03 and 03-05 through 03-12, and 3/4 for Plan 03-04 only because its pattern checker did not find the literal `embedding_endpoint` in `engine/src/client/mod.rs`; the manual three-level check above confirms that artifact exists, is substantive, and is wired.

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `gateway/main.go` | generated `QueryRAG` client | `grpcEngine.QueryRAG` | ✓ WIRED | HTTP handler forwards typed request/context and writes the engine response. |
| `proto/lancet/v1/lancet.proto` | generated Rust/Go types | buf generation artifacts | ✓ WIRED | Additive fields compile and are exercised by the cross-runtime smoke. |
| `engine/src/main.rs` | dense/BM25/fusion modules | `query_rag` calls both paths then `fuse_candidates` | ✓ WIRED | Real nodes table and BM25 snapshot feed the fused pool. |
| `engine/src/main.rs` | `engine/src/rerank/mod.rs` | `Arc<dyn Reranker>` and one awaited call | ✓ WIRED | The local link checker missed the path-string relationship, but source and named tests prove the call. |
| fusion output | final evidence/citations | rerank → final limit → prompt → validation → resolver | ✓ WIRED | `main.rs:993-1068` and reranked-identity test prove identity continuity. |
| `EffectiveRagSettings` | OpenRouter prompt/provider | constructors and payload fields | ⚠️ PARTIAL | Model/endpoint/timeout/sampling/output fields flow; evidence/output packing still uses literal 8192/2048. |
| generation error | session/correlation identity | `GenerationError` → tonic status | ✗ NOT WIRED | Error identity is stored by the type but discarded by `query_rag`; no correlation ID is assigned. |
| ingestion worker | live BM25 snapshot | completed replacement → `bm25_index` refresh | ✗ NOT WIRED (deferred) | Worker processes/replaces rows but does not republish the in-memory BM25 snapshot; DEBT-RAG-04 explicitly defers this lifecycle. |

## Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
|---|---|---|---|---|
| `DenseRetriever` | dense candidates | LanceDB `nodes` nearest-vector query | Yes | ✓ FLOWING |
| `Bm25Index` | lexical candidates | completed `nodes` rows at startup | Yes | ✓ FLOWING |
| `query_rag` | fused/reranked evidence | both candidate lists, RRF, injected reranker | Yes | ✓ FLOWING on valid path |
| `OpenRouterGenerator` | model output | local deterministic provider mock in smoke; real adapter in source | Yes in local smoke | ⚠️ LIVE PROVIDER UNVERIFIED |
| `QueryRAGResponse` | structured citations/snapshot | selected evidence and effective settings | Yes | ✓ FLOWING; contract guard is incomplete |
| worker → BM25 | post-ingestion lexical state | no update/rebuild edge exists | No | ⚠️ STATIC/DEFERRED under DEBT-RAG-04 |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Go gateway and DB package tests | `go test -count=1 ./...` from `gateway` | Gateway and DB packages passed. | ✓ PASS |
| Real Go → Rust → local provider path | `go test -count=1 -run '^TestRAGQueryCrossRuntime$'` from `gateway` | PASS; real processes, Ping, dense/BM25 fixture markers, strict chat, citation, and snapshot assertions passed. | ✓ PASS |
| HTTP boundary guards | `go test -count=1 -run 'TestRAGQueryRejectsOversizedBody|TestRAGQueryRejectsHugeFilterBody|TestRAGQueryRejectsUnknownOrTrailingJSON|TestHTTPServerReadTimeouts'` | PASS. | ✓ PASS |
| Full parallel Rust gate | `cargo test --manifest-path engine/Cargo.toml --locked` | 24 library passed/1 ignored; engine binary 70 passed/1 failed/1 ignored; failure at `engine/src/tests.rs:2851`, `sc.is_truncated`. | ✗ FAIL |
| Full serial Rust gate | `cargo test --manifest-path engine/Cargo.toml --locked -- --test-threads=1` | Same `query_rag_citation_identity_and_notices` failure; current checkout does not reproduce the submitted claim that serial execution passes. | ✗ FAIL |
| Named citation test | `cargo test --manifest-path engine/Cargo.toml --locked tests::query_rag_citation_identity_and_notices -- --exact --test-threads=1` | One binary test passed when isolated. | ✓ PASS (isolated) |
| Named startup guards | `cargo test ... --test config_startup initial_bm25_failure_blocks_readiness` and `invalid_rag_settings_block_readiness` | Both passed. | ✓ PASS |
| Named reranker guards | `cargo test ... tests::query_rag_grounding_uses_reranked_identity`, `query_rag_noop_reranker_preserves_fused_order`, `query_rag_reranker_failure_skips_generation` | Passed individually. | ✓ PASS |
| Named retrieval/grounding guards | `cargo test ... retrieval::tests::retrieval_filter_fusion_and_determinism` and `generation::tests::model_output_marker_identity_validation` | Passed individually. | ✓ PASS |
| Protobuf lint | `buf lint` | Passed. | ✓ PASS |
| Rust formatting | `cargo fmt --manifest-path engine/Cargo.toml -- --check` | Failed on existing formatting drift across generation/prompt/main/test files; no formatter writes were made. | ⚠️ WARNING |
| Buf formatting | `buf format --diff --exit-code` | Could not execute the requested diff gate because this Windows environment has no `diff` executable; `buf lint` and generated-code compilation passed. | ⚠️ ENVIRONMENT |

## Probe Execution

No `scripts/*/tests/probe-*.sh` file exists and no Phase 03 plan declares a probe path. **SKIPPED (no probes declared or found).** The old report's probe wording was not treated as a current probe declaration.

## Requirements Coverage

| Requirement | Source | Description | Status | Evidence |
|---|---|---|---|---|
| RAG-02 | `.planning/REQUIREMENTS.md:12,49` and Plans 03-01 through 03-12 | Dense + local BM25 retrieval, typed metadata filters, deterministic fusion, and chunk deduplication. | ✓ SATISFIED for the stated retrieval contract | Unicode BM25, dense filters, RRF/dedup tests, focused service tests, and real cross-runtime smoke all pass. The broader grounded-answer gate remains blocked by the provider-output gaps above. |
| RAG-04 | `.planning/REQUIREMENTS.md:14,51` and Plans 03-01/03-03/03-05/03-12 | Pluggable async Rust `Reranker` and NoOp pass-through default. | ✓ SATISFIED | `engine/src/rerank/mod.rs`, startup injection, one-call/order/identity/failure tests, and cross-runtime path verify the requirement. |

No Phase 03 requirement is orphaned. RAG-03 is explicitly mapped to Phase 06 and is not an acceptance requirement for this phase.

## Reconciliation with `03-REVIEW.md` and refreshed `03-REVIEWS.md`

The refreshed Antigravity review is a single reviewer input, not a verdict. Its positive RAG-04 claim and the local happy-path claim are supported by source/tests. The following review findings were independently checked:

| Review finding | Independent result | Disposition |
|---|---|---|
| CR-01 embedding errors become `[0.25; 2048]` | Confirmed at `engine/src/main.rs:967-974`. | Explicit DEBT-RAG-01 failure/degraded behavior; deferred because Phase 03 accepts only successful dense/BM25 retrieval. Still listed as a risk, never treated as a pass. |
| CR-02 dense errors become an empty list | Confirmed at `engine/src/main.rs:976-984`. | Same DEBT-RAG-01 disposition. |
| CR-03 BM25 is not refreshed after worker ingestion | Confirmed; no worker path updates `bm25_index`. | DEBT-RAG-04 / Phase 06, explicitly outside initial-readiness acceptance. |
| CR-04 grounding permits citationless retrieval/model-only output | Confirmed in `generation/mod.rs:71-123` and service response mapping. | BLOCKER; this contradicts the accepted valid retrieval-backed answer contract. |
| CR-05 provider output and prompt budgets are insufficiently bounded | Confirmed: schema fields have no max bounds and adapter uses literal 8192/2048. | BLOCKER for the settings/output contract; included in Gaps 1 and 2. |
| CR-06 generation error/correlation identity is discarded | Confirmed: no `correlation_id` assignment and plain tonic mapping. | BLOCKER against D-31; included in Gap 3. |
| CR-07 missing key falls back to `fake-key` | Confirmed at `engine/src/main.rs:1715`. | BLOCKER for usable explicit provider startup; included in Gap 4. |
| CR-08 valid no-match becomes HTTP 400 | Confirmed through EmptyEvidence → InvalidArgument mapping. | Deferred to DEBT-RAG-05/Phase 06's exhaustive unmatched/invalid-input contract; not silently counted as verified. |
| CR-09 delete-before-add raw persistence mutation | Confirmed at `engine/src/main.rs:751-776`. | Warning outside the Phase 03 RAG-02/RAG-04 acceptance surface; lifecycle/atomicity work is separately tracked. |
| WR-05 citation assertion is order-sensitive | Confirmed by both full-suite failures and isolated-test pass. | BLOCKER regression gate; included in Gap 5. |

## Deferred Items

These items are explicitly excluded by `03-CONTEXT.md`, `03-AI-SPEC.md`, `COVERAGE.md`, `deferred-items.md`, or later roadmap criteria. They do not repair the blockers above and are not included in the 49/54 score.

| Item | Addressed in | Evidence |
|---|---|---|
| Degraded vector/BM25/provider behavior and model-only fallback | Phase 06 / DEBT-RAG-01 and DEBT-RAG-06 | `deferred-items.md` states Phase 03 requires both retrieval paths to succeed and Phase 06 owns degraded/model-only acceptance. |
| Citation repair/downgrade after invalid markers | Phase 06 / DEBT-RAG-03 | `03-CONTEXT.md` D-24 and roadmap Phase 06 SC7 explicitly defer repair. The current valid-marker rejection path is verified, but repair is not claimed. |
| Dynamic BM25 re-ingestion/restart switching and recovery | Phase 06 / DEBT-RAG-04 | Initial build/readiness is verified; `03-CONTEXT.md` D-41 through D-43 and roadmap Phase 06 SC7 own lifecycle behavior. |
| Exhaustive unmatched, malformed, oversized, and combinatorial filter contract | Phase 06 / DEBT-RAG-05 | `COVERAGE.md:65-69` and `deferred-items.md` preserve the future negative-input matrix. |
| Graph-unavailable RAG-03 fallback | Phase 04 seam plus Phase 06 hardening / DEBT-RAG-06 | Phase 04 owns graph context; Phase 03 is source-chunk-only. |

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `engine/src/main.rs` | 973, 984 | Constant embedding fallback and `unwrap_or_default` dense failure suppression | ⚠️ Deferred risk | Can produce vector-only or unrelated results on failure; explicitly excluded degraded behavior, but unsafe for production until DEBT-RAG-01 closes. |
| `engine/src/generation/mod.rs` | 71-123 | Empty citation set and model-only basis pass grounding | 🛑 Blocker | A plausible answer can be published without the Phase 03 evidence guarantee. |
| `engine/src/generation/openrouter.rs` | 288, 298-320 | Hardcoded prompt budgets and unbounded provider output schema | 🛑 Blocker | Effective settings do not govern the production adapter and output resource bounds are absent. |
| `engine/src/main.rs` | 1025-1038 | Error mapper discards correlation/session identity | 🛑 Blocker | Violates D-31 structured failure identity. |
| `engine/src/main.rs` | 1715 | `fake-key` credential fallback | 🛑 Blocker | Missing credentials do not fail closed before readiness. |
| `engine/src/tests.rs` | 2851 | Full-suite order-sensitive truncation assertion | 🛑 Blocker | Complete locked Rust gate fails although the named test passes alone. |
| `engine/src/main.rs` | 751-776 | Delete-before-add raw persistence replacement | ⚠️ Warning | Potential lifecycle/data-loss risk; outside current RAG-02/RAG-04 goal and not silently accepted as phase evidence. |
| `engine/src/generation/*`, `engine/src/prompt.rs`, `engine/src/main.rs`, `engine/src/tests.rs` | — | Repository `cargo fmt --check` drift | ⚠️ Warning | Formatting gate is not clean; no `TBD`, `FIXME`, or `XXX` markers were found in the phase-modified source/config/test set. |

## Human Verification Required

Automated local-provider evidence is strong for the happy path, but a real provider integration is inherently external and was not run here. This item remains subordinate to the blocking code gaps.

### 1. Real configured-provider user flow

**Test:** With an explicit `OPENROUTER_API_KEY`, a real completed corpus, and the configured endpoints/model, start the Rust engine, confirm readiness, submit a valid question through the Go `/rag/query` route, and inspect the returned answer, basis, citations, excerpt bounds, and snapshot.

**Expected:** One strict structured provider response produces a retrieval-backed answer whose markers resolve to the displayed completed-corpus evidence; no credential or raw prompt is exposed.

**Why human:** The local smoke uses deterministic HTTP mocks and cannot establish external provider/model compatibility, network behavior, or live answer quality.

## Gaps Summary

The phase delivers the core hybrid retrieval implementation, additive contract, bounded gateway, initial BM25 readiness gate, real local cross-runtime path, and RAG-04 reranker seam. It does not yet meet the complete Phase 03 goal contract because the provider path can publish citationless/model-only output, the production adapter bypasses configured evidence/output settings and lacks output size limits, provider errors lose correlation identity, startup silently substitutes a fake credential, and the current full Rust regression gate fails one test. The explicitly deferred degraded, citation-repair, unmatched-input, graph, and dynamic-lifecycle concerns were filtered to their later phases rather than reported as newly missing Phase 03 work.

**Next action:** keep Phase 03 pending and plan closure for the five structured gaps above before advancing to the next phase.

---

_Verified: 2026-08-04T09:04:52Z_
_Verifier: the agent (gsd-verifier)_
