---
phase: 03-hybrid-retrieval-basic-rag-path
verified: 2026-08-04T13:23:37Z
status: gaps_found
score: "64/65 must-haves verified"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: "49/54 must-haves verified"
  gaps_closed:
    - "Fail-closed Retrieval/Mixed grounding, ModelOnly rejection, and provider answer/ID/notice/warning/body bounds are present and exercised."
    - "Generation errors now carry session/correlation/error-kind metadata through tonic and the Go HTTP boundary."
    - "Startup now rejects missing or blank OPENROUTER_API_KEY before readiness."
    - "The deterministic citation fixture passes in isolation, the current locked Rust gate passes, and the affected engine binary target passes serially."
  gaps_remaining:
    - "Provider usage validation still uses fixed default budgets instead of effective configured evidence and output budgets."
  regressions: []
gaps:
  - truth: "RAG-02 / P24-P25 / Plan 03-13: provider usage bounds must follow validated EffectiveRagSettings on the production adapter path."
    status: failed
    reason: "EffectiveRagSettings reaches prompt packing and max_completion_tokens, but shared grounding validation and OpenRouter response validation compare usage against fixed 8192/2048/10240 constants. A non-default configured budget can therefore be rejected or accepted under the wrong limits."
    artifacts:
      - path: "engine/src/generation/mod.rs"
        issue: "ModelOutput::validate_grounding uses fixed default budget constants rather than receiving effective limits."
      - path: "engine/src/generation/openrouter.rs"
        issue: "execute_one_call repeats fixed usage checks after construction with configurable limits."
      - path: "engine/src/main.rs"
        issue: "Startup passes configured evidence_token_budget and max_output_tokens to the adapter, but usage validation does not consume them."
    missing:
      - "Thread effective evidence/output limits into the shared usage validator and production adapter, including a checked effective total."
      - "Add a non-default OpenRouter adapter regression for usage inside configured limits but outside defaults, and the over-budget case."
next_action: "Keep Phase 03 pending; plan and implement effective provider usage-budget threading, then rerun the focused adapter test and phase gates."
next_command: "/gsd-plan-phase 03 --gaps"
---

# Phase 03: Hybrid Retrieval & Basic RAG Path Verification Report

Phase Goal: As a chat service API user, I want to ask a question using hybrid vector and BM25 retrieval, so that the LLM returns an answer grounded in completed corpus evidence.

Verified: 2026-08-04T13:23:37Z

Status: gaps_found

Re-verification: Yes. This is a fresh live-checkout verification. Existing reports, plans, summaries, reviews, and roadmap metadata were treated as claims or scope inputs; source and test results below are current evidence.

## Scope and accounting

All 15 03-*-PLAN.md and 03-*-SUMMARY.md pairs were read, along with 03-CONTEXT.md, 03-AI-SPEC.md, 03-RESEARCH.md, COVERAGE.md, deferred-items.md, the Phase 03 roadmap section, REQUIREMENTS.md, and the source/tests named by the plans. The roadmap still says Plans: 12/15; the checkout contains 15 plan/summary pairs and the later implementation commits, so live source was used.

The plans contain 62 truth clauses. The four roadmap success criteria were also checked; the initial-BM25 criterion is a duplicate of a plan truth. The resulting non-duplicative must-have count is 65. One plan truth fails: 64/65 verified.

## User Flow Coverage

| Step | Expected | Live evidence | Status |
|---|---|---|---|
| Ask | POST /rag/query accepts a bounded strict JSON request with question, typed filter, and session ID. | gateway/main.go:653-690; strict-decoder, forwarding, body-limit, and filter tests pass. | VERIFIED |
| Retrieve | Rust validates the query, applies common filters to dense and BM25, fuses/deduplicates deterministically, and invokes the reranker before final limiting. | engine/src/main.rs:948-1009 and engine/src/retrieval plus rerank modules; focused/full Rust tests pass. | VERIFIED |
| Assemble | Candidates become bounded encoded evidence with preserved identity and Unicode-bounded citation excerpts. | engine/src/prompt.rs:186-324; budget, adversarial, Unicode, and citation tests pass. | VERIFIED |
| Generate | One provider-neutral request reaches strict OpenRouter-compatible schema after capability preflight, with finish and response bounds. | engine/src/generation/openrouter.rs:223-505; local provider mock and adapter tests pass. | VERIFIED for valid/default path |
| Return grounded answer | Retrieval/mixed output with exact evidence identity reaches Go with basis, citations, notices, and snapshot. | engine/src/generation/mod.rs:79-231 and engine/src/main.rs:1061-1145; cross-runtime smoke passes. | BLOCKED for non-default provider usage budgets |

## Goal Achievement

### Roadmap success criteria

| # | Truth | Status | Evidence |
|---:|---|---|---|
| RSC-1 | Successful dense and BM25 retrieval over completed corpus yields deterministic bounded evidence, one structured answer, and citations resolving to that evidence. | VERIFIED | TestRAGQueryCrossRuntime exercises the real Go route, Rust process, seeded completed LanceDB corpus, dense/BM25 markers, strict chat mock, exact citation, and snapshot. The effective-usage defect is recorded separately. |
| RSC-2 | Go /rag/query receives the structured retrieval-grounded answer through Rust gRPC. | VERIFIED | go test -count=1 -run '^TestRAGQueryCrossRuntime$' ./... exits 0 using generated gRPC types and a real Rust child. |
| RSC-3 | Initial BM25 construction completes before readiness and failure prevents serving. | VERIFIED | engine/src/main.rs:1738-1815 builds BM25 before the serving log; config_startup readiness, invalid-settings, and BM25-failure tests pass. |
| RSC-4 | Pluggable async reranker and NoOp pass-through exist. | VERIFIED | engine/src/rerank/mod.rs:10-35, startup injection at engine/src/main.rs:1811, and one-call/order/failure tests pass. |

### Plan truth coverage

Each range is positional within that plan's must_haves.truths; all clauses were checked individually. P54 is the sole failed clause because its effective usage sub-contract is not implemented.

| Plan truths | Result | Evidence |
|---|---:|---|
| 03-01 P01-P04: Unicode BM25 snapshot/metadata, shared filters, full-precision deterministic RRF/dedup, NoOp, repeatability | 4/4 | engine/src/retrieval and rerank; Unicode, filter/fusion, zero-weight, deterministic, and NoOp tests pass. |
| 03-02 P05-P09: bounded isolated evidence, one strict call, suspicious/conflict handling, capability preflight, valid provider-neutral output | 5/5 | engine/src/prompt.rs and generation modules; adversarial, mixed-basis, supported-parameters, one-call, finish, timeout, and budget tests pass. |
| 03-03 P10-P13: additive QueryRAG proto, full gRPC path, initial readiness, settings overlays | 4/4 | proto source/generated bindings, engine main, config-startup tests, and buf lint pass. |
| 03-04 P14-P16: bounded strict Go boundary, response preservation, configurable embedding endpoint | 3/3 | gateway source/tests and engine client source/tests pass. The artifact helper's missing embedding_endpoint pattern is a mechanical false negative; the client field is endpoint and is wired through the configured constructor. |
| 03-05 P17-P21: isolated process smoke, deterministic provider mocks, Ping/readiness/teardown | 5/5 | gateway/main_test.go cross-runtime test exits 0 and asserts all mock calls, evidence markers, strict output, Ping ordering, and cleanup. |
| 03-06 P22-P24: complete encoded evidence, strict valid output, no repair/fabrication | 3/3 | Prompt, validator, and service tests reject invalid output before public response construction. |
| 03-07 P25-P29: one effective settings object, token/character units, identity, invalid-before-readiness | 5/5 | EffectiveRagSettings, prompt packing, citation projection, snapshots, and invalid-settings tests pass. The provider usage limitation is the later 03-13 gap. |
| 03-08 P30-P34: 32 KiB body boundary, closure, 60-second timeout, strict compatibility | 5/5 | gateway/main.go:654-677,736-742 and boundary/timeout/cross-runtime tests pass. |
| 03-09 P35-P38: citation identity, bounded metadata/excerpt/truncation, notices | 4/4 | resolve_citations_with_max_chars, QueryRAG projection, deterministic rank-two fixture, and notices assertions pass. |
| 03-10 P39-P40: configured embedding identity and generation model/endpoint/timeout/sampling/output | 2/2 | engine client/generation sources and effective-settings request tests pass. |
| 03-11 P41-P45: startup construction/readiness, identity persistence/snapshot, exact config example | 5/5 | engine main, config_startup, engine tests, and config example; startup/key/BM25/example tests pass. |
| 03-12 P46-P51: reranker call/order, NoOp, source disablement, RRF, final identity, failure short-circuit | 6/6 | engine main, fusion, rerank; one-call, order, zero-weight, identity, and failure tests pass. |
| 03-13 P52-P55: fail-closed grounding, ModelOnly rejection, bounded output, valid path | 3/4; P54 failed | Answer/ID/notice/warning/body bounds and grounding pass. Usage checks at engine/src/generation/mod.rs:157-180 and openrouter.rs:468-492 use fixed defaults, not effective config. |
| 03-14 P56-P59: effective adapter settings, error identity metadata, Go error headers, explicit credentials | 4/4 | engine main:1021-1076,1753-1799, gateway/main.go:679-717, and identity/startup tests pass. |
| 03-15 P60-P62: deterministic citation fixtures, valid fake outputs, locked regression evidence | 3/3 | Isolated citation test, full locked workspace test, and serial engine binary target all pass. |

Score: 64/65 non-duplicative truths verified. behavior_unverified: 0; all phase state transitions and ordering invariants have named tests or the cross-runtime process test.

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| engine/src/retrieval/{mod,bm25,dense,fusion}.rs | Unicode BM25, typed filters, dense retrieval, weighted RRF/dedup | VERIFIED | Substantive, imported by main, backed by real LanceDB/BM25 data flow, and covered by focused tests. |
| engine/src/rerank/mod.rs | Async Reranker port and NoOp | VERIFIED | Injected into production and tested for order, field preservation, and failure. |
| engine/src/prompt.rs | Evidence encoding, token packing, Unicode excerpts, resolver | VERIFIED | Wired from retrieval through generation and response projection. |
| engine/src/generation/mod.rs | Closed provider-neutral output/error contract | PARTIAL | Grounding and size checks are wired, but usage validation is hardcoded to defaults. |
| engine/src/generation/openrouter.rs | Configured strict OpenRouter adapter | PARTIAL | Capability, one-call, schema, finish, body, timeout, and settings wiring pass; effective usage validation is incomplete. |
| engine/src/main.rs | Rust query/startup/settings/provider/reranker/response integration | PARTIAL | Valid path flows real data; downstream provider usage guard does not honor every effective limit. |
| proto/lancet/v1/lancet.proto plus generated Rust/Go bindings | Additive QueryRAG contract | VERIFIED | Field identities/types match; buf lint, compilation, and smoke assertions pass. |
| gateway/main.go and gateway/main_test.go | Thin bounded /rag/query boundary | VERIFIED | Strict decoding, 32 KiB cap, closure, timeout, forwarding, error mapping, and smoke pass. |
| engine/src/client/mod.rs and tests | Configured embedding endpoint/model/retry seam | VERIFIED | Endpoint/model, timeout, retry, concurrency, dimension, and redaction tests pass. |
| config/config.toml and config/config.example.toml | Effective non-secret settings | VERIFIED | Real binary contract accepts example; no credential assignment. |
| engine/tests/config_startup.rs, engine/src/tests.rs, gateway smoke | Executable startup/service evidence | VERIFIED | Current full Rust, serial engine target, Go, vet, and cross-runtime checks pass. |

The GSD artifact query found all structured artifacts substantive except the Plan 03-04 embedding_endpoint pattern false negative described above. Plans 03-14/03-15 use unstructured entries and were manually checked. The key-link helper reports false negatives for later links because their via text has no searchable pattern; manual tracing below is authoritative.

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Go HTTP handler | generated QueryRAG client | grpcEngine.QueryRAG with request context | WIRED | gateway/main.go:279-285,679-690; cross-runtime reaches real Rust. |
| Proto source | generated Rust/Go types | additive fields/service methods | WIRED | Proto lint, compilation, and runtime mapping pass. |
| query_rag | dense + BM25 | DenseRetriever query plus startup Bm25Index | WIRED | Both candidate lists feed fusion at engine/src/main.rs:976-998. |
| dense/BM25 | fusion | fuse_candidates | WIRED | fusion.rs:36-95 applies weights, deduplicates chunk_id, and sorts deterministically. |
| fusion | injected reranker | one awaited rerank before final limit | WIRED | main.rs:1000-1009; one-call/order/failure tests pass. |
| final candidates | prompt/evidence | assemble_evidence_blocks then pack_evidence_prompt | WIRED | main.rs:1011-1019; complete blocks and configured prompt budget flow to generator. |
| packed evidence | generator/grounding | GenerationRequest then validate_grounding | WIRED | main.rs:1023-1062; invalid markers/basis produce no public response. |
| validated IDs | structured citations | resolve_citations_with_max_chars | WIRED | main.rs:1078-1108; identity and bounded metadata/excerpt come from selected evidence. |
| EffectiveRagSettings | OpenRouter adapter | constructor to packing/max completion/usage validation | PARTIAL | Constructor, packing, and outbound max tokens use configured values; usage validation still uses constants. |
| generation error | tonic to Go identity headers | status metadata/trailer extraction | WIRED | main.rs:1028-1058 and gateway/main.go:692-717 preserve identity and error kind. |
| startup | BM25/readiness/key/NoOp | validate, build BM25, validate key, construct service | WIRED | main.rs:1743-1815; failure/readiness and blank-key tests pass. |

## Data-Flow Trace

| Artifact | Data variable | Source | Real data | Status |
|---|---|---|---|---|
| DenseRetriever | dense candidates | canonical LanceDB nodes nearest-vector query | Yes | FLOWING |
| Bm25Index | lexical candidates | completed nodes rows and global IDF snapshot | Yes | FLOWING |
| fuse_candidates | fused candidates | both rankings and configured weights | Yes | FLOWING |
| query_rag | final evidence | injected reranker output after fusion and final limit | Yes | FLOWING |
| OpenRouterGenerator | model output | deterministic local metadata/chat provider in cross-runtime; configured endpoint in production | Yes on accepted local smoke | FLOWING; live provider not required |
| QueryRAGResponse | citations/snapshot/basis/notices | validated model IDs resolved against packed evidence and effective settings | Yes | FLOWING, subject to the usage gap |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Locked Rust workspace | cargo test --manifest-path engine/Cargo.toml --locked | Exit 0; 33 + 82 + 18 + 8 passed, 2 ignored, 0 failed. | PASS |
| Citation identity in isolation | cargo test --manifest-path engine/Cargo.toml --locked 'tests::query_rag_citation_identity_and_notices' -- --exact --test-threads=1 | Exit 0; one named engine test passed. | PASS |
| Affected Rust target serially | cargo test --manifest-path engine/Cargo.toml --locked --bin engine -- --test-threads=1 | Exit 0; 82 passed, 1 ignored, 0 failed. | PASS |
| Go tests | go test -count=1 ./... from gateway | Exit 0; gateway and database packages passed. | PASS |
| Real cross-runtime path | go test -count=1 -run '^TestRAGQueryCrossRuntime$' ./... from gateway | Exit 0; real processes, Ping, isolated corpus, dense/BM25 markers, strict schema, citation, snapshot, and teardown passed. | PASS |
| Go vet | go vet ./... from gateway | Exit 0. | PASS |
| Protobuf lint | buf lint | Exit 0. | PASS |
| Protobuf formatting | buf format --diff --exit-code | Environment failure: no diff executable in PATH. No source was rewritten. | ENVIRONMENT |

The Rust gate emitted non-fatal dead-code warnings from target structure. No test failure or credential leak was observed.

## Probe Execution

No scripts/*/tests/probe-*.sh files exist and no Phase 03 plan or summary declares a probe path. SKIPPED: no probes declared or found.

## Requirements Coverage

| Requirement | Source | Description | Status | Evidence |
|---|---|---|---|---|
| RAG-02 | REQUIREMENTS.md:12,49; Plans 03-01 through 03-15 | Hybrid dense plus local BM25 retrieval with metadata filtering, deterministic fusion, deduplication, and grounded answer path. | BLOCKED | Retrieval itself is verified by Unicode BM25, typed-filter, zero-weight, RRF/dedup, service, and cross-runtime tests. Phase-level RAG-02 remains blocked by the production provider usage guard ignoring non-default effective evidence/output limits. |
| RAG-04 | REQUIREMENTS.md:14,51; Plans 03-01, 03-03, 03-05, 03-12 | Pluggable async Rust Reranker with v1 NoOpReranker. | SATISFIED | Reranker source, NoOp injection, exact post-fusion call/order/failure tests, and cross-runtime path verify it. |

No Phase 03 requirement is orphaned. RAG-03 is explicitly mapped to Phase 06 and is not a Phase 03 acceptance requirement.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| engine/src/generation/mod.rs | 157-180 | Usage checks use fixed default constants rather than effective limits | BLOCKER | Configured provider can be validated against wrong prompt/completion/total budgets. |
| engine/src/generation/openrouter.rs | 468-492 | Adapter repeats fixed usage checks despite configurable constructor limits | BLOCKER | Concrete RAG-02/P24-P25 gap. |
| engine/src/main.rs | 967-984 | Embedding failure uses constant vector and dense failure becomes empty list | DEFERRED | DEBT-RAG-01/RAG-03 degraded retrieval is outside the Phase 03 happy-path gate. |
| engine/src/prompt.rs and engine/src/main.rs | 202-204 and 1011-1019 | Valid no-match filters reach EmptyEvidence and become invalid argument | DEFERRED | Literal D-10 behavior is deferred with unmatched/exhaustive filters under DEBT-RAG-05; it is not silently marked verified. |
| Phase source/config/test set | — | TBD, FIXME, or XXX markers | NONE | Only placeholder match is a test name about nullable database placeholders, not an incomplete implementation. |

## Deferred Items

| Item | Addressed in | Evidence and disposition |
|---|---|---|
| Degraded one-path/both-path retrieval and model-only fallback | Phase 06 / DEBT-RAG-01 | D-11-D-16 and deferred-items.md require Phase 03 happy path to use successful dense/BM25. Current valid QueryRAG rejects ModelOnly; future degraded behavior is not claimed. |
| Citation repair/removal/transparent downgrade | Phase 06 / DEBT-RAG-03 | D-24 is future behavior; current valid markers validate and invalid markers fail closed. |
| Re-ingestion/restart BM25 switching and recovery | Phase 06 / DEBT-RAG-04 | Initial BM25 readiness is current and verified; D-41-D-43 are outside this phase. |
| Graph-unavailable RAG-03 fallback | Phase 04 seam plus Phase 06 hardening / DEBT-RAG-06 | Phase 03 uses source chunks and does not claim graph degradation. |
| Exhaustive invalid/unmatched/combinatorial filters | Phase 06 / DEBT-RAG-05 | No-match candidates reach EmptyEvidence rather than a provider call. This is a literal D-10 deviation, but the accepted MVP coverage ledger explicitly defers unmatched/filter-edge behavior; it is reported for visibility and not counted as a current failure. |

## Human Verification Required

None for this verdict. The accepted phase proof is provider-independent and the deterministic local cross-runtime smoke passes. A live OpenRouter call remains optional and would not resolve the code-level effective-budget gap.

## Gaps Summary

The checkout has the complete working local path: bounded Go HTTP -> generated gRPC -> Rust dense/BM25 retrieval -> deterministic fusion -> NoOp reranking -> encoded evidence -> strict provider mock -> grounding validation -> identity-correct citations and snapshot. Startup/readiness, credential rejection, error identity, provider schema/finish/body bounds, filters, source disablement, and RAG-04 wiring are independently exercised.

The phase is not complete because production provider-usage validation is not threaded from EffectiveRagSettings. The adapter uses configured prompt and completion values for request construction, but validates returned usage with default constants. Add the effective-budget path and a non-default regression before advancing. Unmatched-filter, degraded/model-only, citation-repair, graph, and lifecycle items remain explicitly deferred and are not being used to inflate the current gap count.

---

Verified: 2026-08-04T13:23:37Z
Verifier: the agent (gsd-verifier)
