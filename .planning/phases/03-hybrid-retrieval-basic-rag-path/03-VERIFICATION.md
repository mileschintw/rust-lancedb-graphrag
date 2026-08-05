---
phase: 03-hybrid-retrieval-basic-rag-path
verified: 2026-08-05T06:46:30Z
status: gaps_found
score: 76/79 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 64/65 must-haves verified
  gaps_closed:
    - "The previous fixed-default usage comparison is now exercised with non-default effective budgets; the focused provider-usage and startup-ceiling tests pass."
    - "The late D1 and D2 implementations are present and their focused Rust, Go, and cross-runtime tests pass on the current checkout."
  gaps_remaining:
    - "The G1 one-carrier invariant is not implemented: EffectiveRagSettings stores scalar budgets and OpenRouter constructs a separate carrier."
    - "D1 infrastructure logging still interpolates the full error message instead of identity-only structured fields."
    - "Provider response and retrieval/fusion resource bounds are not fail-closed at the allocation and serialization boundaries."
  regressions:
    - "The stale report did not cover plans 03-16, 03-17, or 03-18; this report verifies all 18 plan/summary pairs."
gaps:
  - truth: "G1: one GroundingLimits carrier derived from EffectiveRagSettings governs evidence packing, provider max output, derived total usage, shared grounding validation, and OpenRouter usage validation."
    status: failed
    reason: "EffectiveRagSettings::try_from_settings validates scalar budgets but does not store a GroundingLimits carrier. Query code derives one carrier, while startup OpenRouterGenerationConfig::new derives another; with_grounding_limits also accepts public carrier fields without revalidating service ceilings."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "EffectiveRagSettings has grounding_limits() but no grounding_limits field; the carrier is reconstructed at call sites."
      - path: "engine/src/generation/mod.rs"
        issue: "GroundingLimits fields are public and no public validation method protects callers that construct or deserialize the struct."
      - path: "engine/src/generation/openrouter.rs"
        issue: "with_grounding_limits stores the supplied carrier and only validates unrelated config fields."
    missing:
      - "Store one validated GroundingLimits value in EffectiveRagSettings and pass that same value through packing, generation, usage, and grounding validation."
      - "Make carrier construction/deserialization validate the service ceilings, or make the fields private and validate every constructor path."
  - truth: "P24: provider answer, evidence-ID, notice, warning, usage, and wrapper payload sizes are bounded before untrusted output reaches public response construction."
    status: failed
    reason: "The chat path calls response.bytes() before checking the 256 KiB limit, so the full untrusted body is buffered before rejection. The model-metadata path calls response.json() with no body-size guard."
    artifacts:
      - path: "engine/src/generation/openrouter.rs"
        issue: "The 256 KiB check is after full-body buffering at lines 438-456, and model metadata is parsed directly at lines 279-287."
    missing:
      - "Use a bounded streaming/read path that stops before allocating an oversized response and apply an equivalent bound to model metadata."
  - truth: "D1: infrastructure failures preserve identity and safe structured logs while preventing generation or model-only continuation."
    status: failed
    reason: "The fail-closed status helper preserves identity metadata and skips generation, but its tracing warning interpolates the full msg. That contradicts the plan's identity-only safe-log contract because transport/provider messages can contain untrusted or sensitive details."
    artifacts:
      - path: "engine/src/main.rs"
        issue: "d1_status logs QueryRAG infrastructure failure: {msg} in addition to session_id, correlation_id, and error_kind."
    missing:
      - "Log only session_id, correlation_id, error_kind, and a fixed event name; keep detailed error text out of the structured warning."
      - "Add a regression assertion that the D1 warning cannot contain the error message or payload details."
  - truth: "Roadmap success criterion 1 / RAG-02: valid completed-corpus hybrid retrieval produces deterministic bounded evidence for a grounded answer."
    status: failed
    reason: "The normal seeded happy path is deterministic and passes, but current valid configuration permits effectively unbounded candidate/query/filter limits up to i32::MAX, BM25 allocates for the full document set before truncating, and finite source scores can overflow fused_score. The Go JSON encoder error is ignored after headers are committed, so a non-finite fused result can escape as an HTTP 200 with an invalid body."
    artifacts:
      - path: "engine/src/retrieval/mod.rs"
        issue: "Validation caps limits only at i32::MAX rather than service-safe ceilings."
      - path: "engine/src/retrieval/bm25.rs"
        issue: "The in-memory result vector is allocated from the full document count before candidate truncation."
      - path: "engine/src/retrieval/fusion.rs"
        issue: "RRF contribution and fused_score accumulation have no finite/overflow guard."
      - path: "gateway/main.go"
        issue: "writeJSON ignores Encoder.Encode errors after WriteHeader."
    missing:
      - "Enforce explicit service-safe retrieval, query, and filter ceilings before work or allocation."
      - "Fail closed on non-finite RRF arithmetic and encode the response before committing a success status, or handle encoding failure with a safe error path."
deferred:
  - truth: "Degraded retrieval continuation, disclosed model-only answers, and infrastructure recovery."
    addressed_in: "Phase 06"
    evidence: "ROADMAP and deferred-items.md assign RAG-03 and DEBT-RAG-01 to the later hardening phase; current valid-path D1 failures remain fail-closed."
  - truth: "Citation repair or downgrade."
    addressed_in: "Phase 06"
    evidence: "deferred-items.md DEBT-RAG-03 explicitly retains fail-closed citation validation and defers repair/downgrade."
  - truth: "Re-ingestion lifecycle recovery after restart."
    addressed_in: "Phase 06"
    evidence: "deferred-items.md DEBT-RAG-04 keeps initial BM25 build-before-readiness and defers restart/lifecycle recovery."
  - truth: "Exhaustive malformed, bound, unmatched, and combinatorial filter matrix."
    addressed_in: "Phase 06"
    evidence: "deferred-items.md DEBT-RAG-05 ships only the valid zero-match branch for Phase 03."
  - truth: "Graph retrieval and graph-unavailable fallback."
    addressed_in: "Phase 04 / Phase 06"
    evidence: "deferred-items.md DEBT-RAG-06 keeps Phase 03 source-chunk-only and assigns the graph seam to Phase 04 with fallback hardening later."
human_verification:
  - test: "Run the Rust engine and Go gateway with an approved live provider configuration and submit a valid query over a completed corpus."
    expected: "The provider responds within the declared bounded contract and the gateway returns one grounded answer whose citations resolve to returned evidence, with no provider-specific failure or redaction issue."
    why_human: "External provider behavior and real credential/network integration are not reproducible from the local deterministic mocks."
next_action: "Keep Phase 03 pending; plan targeted gap closure and rerun the verification gate. Do not update ROADMAP or STATE to complete."
next_command: "/gsd-plan-phase 03 --gaps"
---

# Phase 03: Hybrid Retrieval & Basic RAG Path Verification Report

**Phase Goal:** As a chat service API user, I want to ask a question using hybrid vector and BM25 retrieval, so that the LLM returns an answer grounded in completed corpus evidence.

**Verified:** 2026-08-05T06:46:30Z

**Status:** gaps_found

**Re-verification:** Yes — the prior report was stale and did not cover plans 03-16 through 03-18.

## Contract Inputs

| Input | Applied verification contract |
| --- | --- |
| ROADMAP.md | Phase goal, MVP mode, four roadmap success criteria, and the live plan tracker. The tracker still says 15/18 executed; the checkout contains 18 PLAN/SUMMARY pairs, so the tracker was not used as completion evidence. |
| REQUIREMENTS.md | RAG-02 and RAG-04 are the Phase 03 requirements; RAG-03 is mapped to Phase 06. |
| 03-CONTEXT.md | Accepted slice is the valid completed-corpus path with dense plus BM25 retrieval, deterministic fusion, bounded evidence, one grounded response, and initial BM25 readiness. |
| 03-AI-SPEC.md | Provider-neutral generation, strict grounding/citation validation, fail-closed provider/error behavior, and no unapproved model-only fallback on the valid path. |
| COVERAGE.md | The valid-provider matrix and explicit RAG-03 opt-out/debt surface; coverage prehook passed with 19 surfaces, 12 integration cases, and 7 opt-outs. |
| deferred-items.md | Canonical D1-D5 scope ledger; deferred degradation, citation repair, re-ingestion recovery, filter matrix expansion, and graph fallback were not counted as Phase 03 gaps unless current valid-path code violated fail-closed behavior. |
| GSD verifier gates | MVP user-story validation passed; previous verification was loaded in re-verification mode; no documented probes were present. |

## User Flow Coverage

| User-story step | Expected outcome | Current evidence | Status |
| --- | --- | --- | --- |
| Submit a valid query | Go accepts the strict request, validates the session/filter, and forwards it to Rust gRPC. | gateway/main.go strict decoder and RAG handler; Go request-boundary tests; cross-runtime smoke. | VERIFIED |
| Retrieve evidence | Dense and BM25 retrieval use the same query/filter contract, fuse deterministically, deduplicate, and pass through the async reranker seam. | Rust retrieval/fusion/rerank tests; seeded LanceDB plus BM25 cross-runtime fixture. | PARTIAL — normal path passes, but resource/finite-arithmetic bounds remain a blocker. |
| Generate one grounded response | Rust calls the provider-neutral generator once only after non-empty evidence, validates grounding/citations, and returns the structured response. | Rust happy-path, citation, fail-closed, and provider-usage tests; cross-runtime smoke. | PARTIAL — provider body-bound implementation is not allocation-bounded. |
| Achieve the outcome | The valid completed-corpus path returns an answer grounded in completed corpus evidence with resolving citations. | TestRAGQueryCrossRuntime passes against the local deterministic provider and seeded completed corpus. | PARTIAL — the accepted default path works, but the phase contract is not safe for all valid configurations. |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Roadmap SC1: valid completed-corpus vector+BM25 retrieval yields deterministic bounded evidence, one structured answer, and resolving citations. | FAILED | Default seeded cross-runtime path passes, but retrieval limits/allocations and fused-score/JSON error handling are not fail-closed for valid configurations. |
| 2 | Roadmap SC2: Go /rag/query receives the structured grounded answer through Rust gRPC. | VERIFIED | Go boundary tests and TestRAGQueryCrossRuntime pass; DTO fields are explicit rather than omitted. |
| 3 | Roadmap SC3: initial BM25 build completes before readiness and failure prevents serving. | VERIFIED | config_startup initial_bm25 tests and full locked Rust suite pass; startup builds BM25 before serving. |
| 4 | Roadmap SC4: async pluggable Reranker exists with NoOp pass-through. | VERIFIED | Reranker trait, NoOp injection, and pass-through tests pass. |
| 5 | Plan truths across 03-01 through 03-12 and 03-14 through 03-15. | VERIFIED | 54/54 plan truths supported by current source, wiring, and focused/full tests. |
| 6 | Plan 03-13 provider-boundary and grounding hardening truths. | FAILED | 3/4 pass; output rejection is present, but the provider body is fully buffered before the size check and metadata JSON has no equivalent bound. |
| 7 | Plan 03-16 G1 effective-limit carrier truths. | FAILED | 3/4 pass; configured ceiling tests pass, but there is no single carrier derived and retained by EffectiveRagSettings. |
| 8 | Plan 03-17 D1 fail-closed identity/error truths. | FAILED | 3/4 pass; transport/invalid-payload mapping and generation suppression pass, but d1_status logs the full message. |
| 9 | Plan 03-18 D2 zero-match and scope-fence truths. | VERIFIED | 6/6 pass; exact zero-match Rust/Go shape, malformed-input behavior, D1 behavior, and deferred D3/D4/D5 boundaries are present. |

**Score:** 76/79 must-haves verified (73/76 plan truths plus 3/4 roadmap success criteria). Behavior-unverified truths: 0. The remaining failures are static contract violations, not merely untested transitions.

### All Plan/Summary Pair Reconciliation

All 18 PLAN files and all 18 SUMMARY files were read. The following counts are PLAN frontmatter truth counts; a summary claim is not treated as evidence unless current source and tests support it.

| Plan | Truths verified | Current assessment |
| --- | ---: | --- |
| 03-01 | 4/4 | Hybrid retrieval core is present and wired. |
| 03-02 | 5/5 | Evidence packing and grounding path are present for normal bounded settings. |
| 03-03 | 4/4 | Provider-neutral generation path is present; its SUMMARY metadata overclaims RAG-03, which remains deferred by the canonical scope documents. |
| 03-04 | 3/3 | Query API and request validation are present. |
| 03-05 | 5/5 | Citation/evidence response contract is present and tested. |
| 03-06 | 3/3 | Ingestion/query integration claims are supported on the valid path. |
| 03-07 | 5/5 | Metadata/filter and response mapping claims are supported on the valid path. |
| 03-08 | 5/5 | Coverage addendum and valid-provider matrix are reflected in code/tests. |
| 03-09 | 4/4 | Initial end-to-end RAG path claims are supported by current tests. |
| 03-10 | 2/2 | Reranker seam and NoOp behavior are wired. |
| 03-11 | 5/5 | Provider/error/citation contract claims are supported except for the later body-allocation defect tracked under 03-13. |
| 03-12 | 6/6 | Fail-closed and deterministic valid-path claims are supported for exercised inputs. |
| 03-13 | 3/4 | Summary claims wrapper bounds, but response.bytes buffers the whole body before rejecting it and models metadata is unbounded. |
| 03-14 | 4/4 | Configuration/startup and gateway hardening claims are present on exercised paths. |
| 03-15 | 3/3 | The prior effective-usage gap is covered by non-default budget tests; the G1 authority issue is a later 03-16 failure. |
| 03-16 | 3/4 | Summary claims one G1 carrier; current code re-derives scalar-equivalent carriers at separate call sites. |
| 03-17 | 3/4 | Summary claims identity-only safe logs; current d1_status includes the full message in tracing output. |
| 03-18 | 6/6 | D2 valid zero-match branch and explicit D3/D4/D5 deferrals are verified. |

Plans 03-16, 03-17, and 03-18 are not summary-only artifacts: their source/test changes are in the current checkout and their focused tests pass. Their passing tests close the exercised behavior claims, but they do not erase the two static contract deviations above or the independent RAG-02 resource-bound gap.

The 03-03 SUMMARY lists RAG-03 under requirements-completed. That is not accepted as a scope change: ROADMAP.md, 03-CONTEXT.md, COVERAGE.md, and deferred-items.md all keep degraded/model-only/citation-repair/re-ingestion hardening deferred. Current code also rejects ModelOnly output and keeps D1/citation failures fail-closed, so no current valid-path violation requires pulling RAG-03 into this phase.

## Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| engine/src/retrieval/mod.rs, dense.rs, bm25.rs, fusion.rs | Real vector/BM25 retrieval, filtering, deterministic fusion, deduplication, and bounded candidates. | PARTIAL / BLOCKER | Real LanceDB and in-memory BM25 data flow is wired; service-safe ceilings and finite RRF arithmetic are missing. |
| engine/src/generation/mod.rs | Shared grounding limits, validation, citation identity, and provider-neutral generator contract. | PARTIAL / BLOCKER | Shared validation exists, but the carrier is publicly constructible without validation and is not retained as one EffectiveRagSettings authority. |
| engine/src/generation/openrouter.rs | Provider adapter with bounded wrapper/model responses and usage validation. | PARTIAL / BLOCKER | Usage and schema validation are wired; chat bytes are fully buffered before the 256 KiB check and model metadata uses direct JSON parsing. |
| engine/src/main.rs | Startup/readiness, query orchestration, fail-closed D1 behavior, and NoOp injection. | PARTIAL / BLOCKER | Startup order, query path, error identities, and generation suppression are wired; the carrier is re-derived and D1 logs include msg. |
| engine/src/rerank.rs | Async Reranker trait and NoOp pass-through. | VERIFIED | Imported and injected into the query service; focused pass-through test passes. |
| gateway/main.go and proto/lancet/v1/lancet.proto | Strict HTTP boundary, gRPC mapping, structured response DTO, and error identity propagation. | PARTIAL | Normal and cross-runtime paths pass; writeJSON ignores encoding errors after committing the HTTP status. |
| engine/tests, gateway tests, and fixture seeder | Behavioral evidence for valid path, fail-closed behavior, zero-match, startup, limits, and cross-runtime mapping. | VERIFIED | Focused tests, full locked Rust, full Go, and cross-runtime smoke all exit 0. |
| .planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md | Canonical scope/debt ledger for excluded RAG-03 behavior. | VERIFIED | D1-D5 boundaries and later-phase ownership are explicit and consistent with current fail-closed code. |

## Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| HTTP /rag/query | Rust QueryRAG | Go gRPC client call and strict DTO conversion | WIRED | Go focused boundary tests and cross-runtime smoke pass. |
| QueryRAG | embedder, DenseRetriever, BM25Retriever | validated QueryRequest and shared filter | WIRED | Query orchestration calls both retrievers and maps transport/invalid-payload failures. |
| Dense/BM25 results | RRF fusion | retrieval::fuse with deterministic sort key | WIRED | Fusion and determinism tests pass; arithmetic overflow guard is missing. |
| Fusion results | Reranker | async Reranker trait with NoOpReranker | WIRED | NoOp pass-through test and service injection pass. |
| Reranked candidates | evidence packer/generator | final_limit, prompt packing, one provider call | WIRED | Happy path and generator-call-count tests pass; provider body bound is late. |
| Model output | grounding validator/citation resolver/DTO | shared limits and source chunk IDs | PARTIAL | Normal grounding/citation tests pass; the one-carrier limit authority is not implemented. |
| Startup config | BM25 build/readiness | build before Server::serve | WIRED | Initial-BM25 startup tests pass. |

## Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
| --- | --- | --- | --- | --- |
| DenseRetriever | vector candidates | LanceDB query over seeded completed corpus | Yes | FLOWING |
| Bm25Retriever | lexical candidates | in-memory BM25 index built from completed corpus | Yes | FLOWING |
| fusion and NoOpReranker | fused/reranked candidates | both retrieval branches | Yes | FLOWING, with missing finite-arithmetic guard |
| prompt packing and generator | evidence blocks and model output | fused source chunks plus local deterministic provider in tests | Yes | FLOWING, with provider body-bound defect |
| grounding/citation response | answer, citations, notices, snapshot | validated model output and source IDs | Yes | FLOWING on tested normal path |
| zero-match response | empty answer/citations plus snapshot | valid empty fused result; generator is not called | Yes | FLOWING; exact Rust/Go tests pass |

## Behavioral Spot-Checks

| Behavior | Exact command | Result |
| --- | --- | --- |
| Full locked Rust suite | cargo test --manifest-path engine/Cargo.toml --locked -- --test-threads=1 | PASS, exit 0; targets reported 34 passed/1 ignored, 90 passed/1 ignored, 18 passed, and 9 passed. |
| Effective provider usage limits | cargo test --manifest-path engine/Cargo.toml --locked openrouter_effective_usage_limits -- --test-threads=1 | PASS, exit 0. |
| Startup service ceilings | cargo test --manifest-path engine/Cargo.toml --locked --test config_startup service_ceiling_rejects_above_effective_limits -- --test-threads=1 | PASS, exit 0; 1 passed. |
| D1 fail-closed family | cargo test --manifest-path engine/Cargo.toml --locked query_rag_fail_closed_ -- --test-threads=1 | PASS, exit 0; 6 passed. |
| Valid zero-match | cargo test --manifest-path engine/Cargo.toml --locked query_rag_valid_zero_match -- --test-threads=1 | PASS, exit 0; 1 passed. |
| Retrieval filter/fusion | cargo test --manifest-path engine/Cargo.toml --locked retrieval_filter_fusion_and_determinism -- --test-threads=1 | PASS, exit 0. |
| NoOp reranker | cargo test --manifest-path engine/Cargo.toml --locked noop_reranker_preserves_candidates -- --test-threads=1 | PASS, exit 0. |
| Rust query happy path | cargo test --manifest-path engine/Cargo.toml --locked query_rag_happy_path_service -- --test-threads=1 | PASS, exit 0. |
| Citation identity/notices | cargo test --manifest-path engine/Cargo.toml --locked query_rag_citation_identity_and_notices -- --test-threads=1 | PASS, exit 0. |
| Initial BM25 readiness | cargo test --manifest-path engine/Cargo.toml --locked --test config_startup initial_bm25 -- --test-threads=1 | PASS, exit 0; 2 passed. |
| Go RAG boundary and D1 mapping | from gateway: go test -count=1 -run '^(TestRAGQueryNoResults|TestRAGQueryValidMapping|TestRAGQueryInvalidArgumentStatus|TestRAGQueryRejectsUnknownOrTrailingJSON|TestRAGQueryEmbeddingTransportIdentity|TestRAGQueryEmbeddingInvalidPayloadIdentity|TestRAGQueryDenseRetrievalIdentity)$' ./... | PASS, exit 0. |
| Go/Rust cross-runtime contract | from gateway: go test -count=1 -run '^TestRAGQueryCrossRuntime$' ./... | PASS, exit 0. |
| Full Go suite | from gateway: go test -count=1 ./... | PASS, exit 0. |
| Go static checks | from gateway: go vet ./... | PASS, exit 0. |
| Protobuf lint | buf lint | PASS, exit 0. |
| Rust formatting check | cargo fmt --manifest-path engine/Cargo.toml --all -- --check | FAIL, exit 1; current formatting drift remains in engine files. No formatting changes were made. |
| Protobuf formatting check | buf format --diff --exit-code | BLOCKED by environment, exit 1; buf could not execute diff because diff is not on PATH. |

## Probe Execution

No conventional scripts/*/tests/probe-*.sh probes were found and no phase PLAN/SUMMARY declares a probe path. Probe execution was skipped; there was no missing documented probe.

## Requirements Coverage

| Requirement | Source | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| RAG-02 | ROADMAP.md, REQUIREMENTS.md, plans 03-01 through 03-18 | Hybrid dense/vector plus local BM25 retrieval with filtering and deduplication. | BLOCKED | The valid default/cross-runtime path and core tests pass, but current resource ceilings, fused-score finite handling, and provider boundary defects prevent accepting the requirement as fully achieved. |
| RAG-04 | ROADMAP.md, REQUIREMENTS.md, plans 03-10 and 03-14 | Async pluggable Reranker trait with NoOp default. | SATISFIED | Trait, NoOp implementation/injection, pass-through test, and cross-runtime path are present. |
| RAG-03 | REQUIREMENTS.md Phase 06 mapping, COVERAGE.md, deferred-items.md | Degraded/model-only/citation-repair/re-ingestion hardening. | DEFERRED, NOT A PHASE 03 GAP | The scope fence is explicit; current valid-path failures remain fail-closed and ModelOnly is rejected. |

No additional Phase 03 requirement is orphaned in REQUIREMENTS.md: the phase maps to RAG-02 and RAG-04, while RAG-03 is mapped to Phase 06. Several late PLAN files use blank requirements metadata, but that does not reduce the roadmap contract and does not create an unclaimed Phase 03 requirement.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | ---: | --- | --- | --- |
| engine/src/main.rs | 770 | D1 structured warning interpolates the full msg | BLOCKER | Violates the identity-only safe-log contract even though status metadata and generation suppression work. |
| engine/src/generation/openrouter.rs | 279-287, 438-456 | Direct JSON metadata parse and full response.bytes buffer before size rejection | BLOCKER | Untrusted provider payloads are not bounded before allocation. |
| engine/src/retrieval/mod.rs; dense.rs; bm25.rs | 250-275; 85; 244-262 | Limits allow i32::MAX-scale work and BM25 allocates from full document count | BLOCKER | A valid configuration can defeat the bounded-evidence/resource contract. |
| engine/src/retrieval/fusion.rs; gateway/main.go | 125-134; 845-848 | Fused score overflow/non-finite path and ignored JSON encoder error | BLOCKER | Invalid response serialization can escape after HTTP 200. |
| engine/src/generation/mod.rs; generation/openrouter.rs | 85-89; 90-109 | Public GroundingLimits fields and an unvalidated carrier injection path | WARNING | Related to the failed G1 one-carrier truth and a future bypass of service ceilings. |
| engine/src/retrieval/bm25.rs | 233-263 | Direct BM25 query validates settings but not QueryRequest | WARNING | Production QueryRAG validates first, but the lower-level API has a weaker contract. |
| engine/src/lib.rs; engine/src/main.rs | module declarations | Retrieval/generation modules are declared through duplicate library/binary paths | WARNING | Maintenance risk and possible divergence; current binary path is exercised. |
| engine/src/db/tests.rs | 11 | Test name contains placeholder wording | INFO | Test-only naming; no production stub or unreferenced TODO/FIXME/XXX marker was found. |
| engine formatting | multiple files | cargo fmt --check drift | WARNING | Quality gate remains red; no source was reformatted during verification. |

## Human Verification Required

1. Live provider integration

   Test: Run the engine and gateway with approved OpenRouter credentials and submit a valid query over a completed corpus.

   Expected: One grounded structured answer is returned, citations resolve to returned evidence, usage stays within the effective limits, and provider/network failures are surfaced without sensitive logging or model-only continuation.

   Why human: External provider behavior, credentials, and network integration are not reproducible from the local deterministic mocks. This item does not change the current status precedence: the four automated blockers keep the phase at gaps_found.

## Gaps Summary

The valid default path is real and exercised: dense and BM25 data flow from a completed seeded corpus through deterministic fusion, NoOp reranking, bounded prompt packing, one local generation call, grounding validation, citation resolution, Rust gRPC, and Go DTO conversion. The full locked Rust suite, full Go suite, focused D1/D2/limit tests, and cross-runtime smoke all pass.

The phase is nevertheless not achieved. The G1 implementation does not provide the promised single effective limits carrier; D1 logs include the full error message; provider response limits are checked only after buffering and model metadata is unbounded; and the RAG-02 path still admits effectively unbounded retrieval work and unchecked fused-score/JSON serialization failure. These are current-code blockers, not deferred RAG-03 behavior. Keep the phase pending and route the structured gaps to targeted planning.

The existing unrelated working-tree change gateway/tmp-go-cache-regression/ was preserved. No production source, ROADMAP, STATE, or phase-completion marker was modified.

---

Verified: 2026-08-05T06:46:30Z

Verifier: the agent (gsd-verifier)
