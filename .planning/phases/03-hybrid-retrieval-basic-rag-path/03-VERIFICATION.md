---
phase: 03-hybrid-retrieval-basic-rag-path
verified: 2026-08-02T23:18:33Z
status: gaps_found
score: 7/15 must-haves verified
behavior_unverified: 1
overrides_applied: 0
gaps:
  - truth: "Bounded, isolated evidence remains untrusted and honors the configured prompt and excerpt limits."
    status: failed
    reason: "Corpus-controlled title/section metadata is interpolated into prompt attributes without escaping, the first evidence block bypasses the token budget, and runtime prompt/excerpt assembly ignores the committed evidence and excerpt settings."
    artifacts:
      - path: "engine/src/prompt.rs"
        issue: "Unescaped provenance attributes, first-block budget bypass, and byte-indexed Unicode excerpt truncation."
      - path: "engine/src/main.rs"
        issue: "QueryRAG calls prompt assembly with constants rather than effective configuration."
    missing:
      - "Escape every corpus-controlled metadata/content field with one structured encoding boundary."
      - "Reject or omit an over-budget first block and fail closed when no complete evidence block fits."
      - "Use configured evidence/excerpt limits and truncate excerpts on Unicode character boundaries with accurate truncation state."
  - truth: "Every accepted provider answer is closed-schema validated and every valid marker produces a provenance-correct bounded citation from the cited evidence object."
    status: failed
    reason: "The adapter requests json_object rather than strict JSON Schema, ModelOutput accepts unknown fields, invalid IDs are silently removed, finish reason and grounding invariants are unchecked, and response citations take score/rank from citation position rather than cited evidence identity."
    artifacts:
      - path: "engine/src/generation/mod.rs"
        issue: "ModelOutput is not deny_unknown_fields and has no complete semantic validator."
      - path: "engine/src/generation/openrouter.rs"
        issue: "Uses json_object and silently retains-away unsupported citation IDs."
      - path: "engine/src/main.rs"
        issue: "Structured citation metadata is paired by enumeration index and warnings are discarded."
    missing:
      - "Send strict JSON Schema with required fields and additionalProperties false."
      - "Reject empty/truncated/unknown-field/invalid-marker or marker-ID-mismatch outputs before publishing an answer."
      - "Resolve citation metadata by engine-issued evidence/chunk identity and preserve title, section, content type, score, rank, and truncation from that same source."
  - truth: "A valid QueryRAG call routes fused candidates through the configured NoOpReranker before evidence assembly."
    status: failed
    reason: "The Reranker trait and NoOpReranker are substantive and unit-tested, but LancetServiceImpl has no reranker field and QueryRAG sends fused candidates directly to evidence assembly."
    artifacts:
      - path: "engine/src/rerank/mod.rs"
        issue: "Orphaned from the production QueryRAG path; compiler reports the trait unused and NoOpReranker never constructed."
      - path: "engine/src/main.rs"
        issue: "No injected reranker or rerank invocation after fusion."
    missing:
      - "Inject Arc<dyn Reranker>, construct NoOpReranker at startup, and invoke it after fusion."
      - "Add a service-level recording-reranker test proving exactly one call and field/order preservation."
  - truth: "Committed retrieval, embedding, generation, evidence, and snapshot settings control the behavior the service reports."
    status: failed
    reason: "Several settings deserialize but are inert: startup builds BM25 with defaults, evidence/excerpt limits are unused, generation sampling/timeout/output are hardcoded, the embedding model is compile-time, and the snapshot hardcodes or narrows effective values."
    artifacts:
      - path: "config/config.toml"
        issue: "Declares settings that are not consistently consumed."
      - path: "engine/src/main.rs"
        issue: "Builds BM25 with Bm25Config::default and hardcodes snapshot values."
      - path: "engine/src/client/mod.rs"
        issue: "Embedding request model and timeout remain compile-time constants."
      - path: "engine/src/generation/openrouter.rs"
        issue: "Timeout, temperature, top-p, output limit, and prompt limits remain fixed constants."
    missing:
      - "Validate effective settings before readiness and use the same BM25 settings for index build and query."
      - "Pass validated embedding/generation/evidence configuration into adapters and service assembly."
      - "Report exact effective snapshot values without hardcoding or lossy casts."
  - truth: "The Go /rag/query boundary accepts a bounded strict JSON envelope and rejects over-limit bodies before allocation/provider work."
    status: failed
    reason: "Unknown and trailing JSON are rejected and InvalidArgument maps to HTTP 400, but queryRAG decodes r.Body without MaxBytesReader and the server has no request-body read timeout."
    artifacts:
      - path: "gateway/main.go"
        issue: "The RAG body is unbounded; MaxBytesReader is used only for document upload."
      - path: "gateway/main_test.go"
        issue: "No one-byte-over-limit RAG body or huge-filter body test."
    missing:
      - "Bound /rag/query JSON before decoding, close it, and return HTTP 413 for over-limit input."
      - "Add an appropriate request-body deadline and focused over-limit tests."
deferred:
  - truth: "Transparent surviving-path or model-only behavior after retrieval/provider failure."
    addressed_in: "Phase 6"
    evidence: "Phase 6 success criterion 7 implements the deferred RAG-03 hardening target, including DEBT-RAG-01 and DEBT-RAG-06."
  - truth: "One bounded repair/downgrade flow for malformed or unknown citation markers."
    addressed_in: "Phase 6"
    evidence: "Phase 6 success criterion 7 includes DEBT-RAG-03; Phase 03 still must reject rather than silently publish an invalid marker."
  - truth: "Atomic BM25/vector visibility across re-ingestion and restart recovery."
    addressed_in: "Phase 6"
    evidence: "Phase 6 success criterion 7 includes DEBT-RAG-04; Phase 03 only owns the initial-build safeguard."
behavior_unverified_items:
  - truth: "Initial BM25 construction completes before the first query-ready state, and an initial BM25 build failure prevents serving the valid path."
    test: "Create a database that opens successfully but contains a schema-valid completed row whose required content is whitespace-only, then start the engine."
    expected: "BM25 construction reports the offending row/field and the engine emits no serving signal or listening socket."
    why_human: "The positive ordering test passes, but the named failure test points LanceDB at an ordinary corrupt file and exits during database initialization before BM25 construction is reached."
---

# Phase 3: Hybrid Retrieval & Basic RAG Path Verification Report

**Phase Goal:** As a chat service API user, I want to ask a question using hybrid vector and BM25 retrieval, so that the LLM returns an answer grounded in completed corpus evidence.
**Verified:** 2026-08-02T23:18:33Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## User Flow Coverage

User story: “As a chat service API user, I want to ask a question using hybrid vector and BM25 retrieval, so that the LLM returns an answer grounded in completed corpus evidence.”

| Step | Expected | Evidence | Status |
|---|---|---|---|
| Ask | A valid `POST /rag/query` reaches the generated gRPC client with query/session/filter values. | `gateway/main.go:443,629-663`; `TestRAGQueryCrossRuntime` passed independently. | ✓ VERIFIED |
| Retrieve | Rust obtains dense and BM25 candidates from a completed LanceDB corpus and deterministically fuses them. | `engine/src/main.rs:832-864`; the real-process smoke rejects the chat request unless both fixture markers reach the prompt (`gateway/main_test.go:1573-1575`). | ✓ VERIFIED for the successful default path |
| Generate | One capability-checked local provider call returns a structured answer through the real Rust process. | `gateway/main_test.go:1503-1782`; exact test passed in 2.53s. | ✓ VERIFIED for the cooperative fixture |
| Ground and cite | Accepted answer markers resolve to the correct bounded evidence object with trustworthy provenance. | `engine/src/main.rs:897-913` pairs citation metadata by enumeration index; `engine/src/generation/openrouter.rs:243-265` accepts permissive output and silently drops unknown IDs. | ✗ FAILED |
| Outcome | The returned LLM answer is observably grounded in completed-corpus evidence. | The first-citation fixture works, but the general citation/evidence invariants required by the outcome do not hold. | ✗ FAILED |

The MVP flow stops at the grounding/citation outcome. The technical sections below document the evidence used to classify the blockers; passing lower-level steps do not override the failed outcome.

## Goal Achievement

### Observable Truths

The four roadmap success criteria were kept verbatim. Twenty-one PLAN truths were merged and deduplicated into eleven additional observable truths; no PLAN reduced roadmap scope.

| # | Truth | Source | Status | Evidence |
|---|---|---|---|---|
| 1 | For a valid query over a completed corpus where both vector and BM25 retrieval paths succeed, the Rust engine fuses deterministic, bounded evidence and returns one structured answer with valid citations resolving to that evidence. | ROADMAP SC1 | ✗ FAILED | Retrieval/fusion and the cooperative smoke pass, but prompt bounds, closed output validation, and citation identity/provenance fail (`prompt.rs:35-40,129-143,175-180`; `openrouter.rs:192-194,243-265`; `main.rs:897-913`). |
| 2 | Go gateway exposes `/rag/query` and receives that retrieval-grounded structured answer through the Rust gRPC boundary. | ROADMAP SC2 | ✓ VERIFIED | Real Go route → generated gRPC client → Rust process passes in `TestRAGQueryCrossRuntime`. |
| 3 | Initial BM25 construction completes before the first query-ready state, and an initial build failure prevents serving the valid path. | ROADMAP SC3 | ⚠ PRESENT_BEHAVIOR_UNVERIFIED | `initial_bm25_ready_before_serving` passes, but `initial_bm25_failure_blocks_readiness` fails during database open rather than BM25 build (`config_startup.rs:215-245`). |
| 4 | Define pluggable async Reranker trait and NoOpReranker pass-through implementation (Port for 999.2). | ROADMAP SC4 | ✓ VERIFIED | Object-safe trait and pass-through exist (`rerank/mod.rs:10-35`); preservation unit test passes. Runtime use is a separate truth below. |
| 5 | Rust builds a Unicode-aware BM25 snapshot from completed rows while preserving original evidence metadata and repeatability. | 03-01 | ✓ VERIFIED | Substantive analyzer/index code plus `bm25_full_unicode_analyzer_and_global_idf` and `bm25_rejects_empty_required_content` pass. |
| 6 | Dense and BM25 use one normalized filter model and fuse with deterministic full-precision weighted RRF and chunk-ID deduplication. | 03-01 | ✓ VERIFIED | `QueryRequest`/`QueryFilters`, dense/BM25 code, fusion ordering, and `retrieval_filter_fusion_and_determinism` pass. |
| 7 | A valid QueryRAG call routes fused candidates through NoOpReranker without field/order loss. | 03-01, 03-03 | ✗ FAILED | `LancetServiceImpl` has no reranker and `main.rs:854-864` goes directly from fusion to truncation; compiler says the trait is unused and NoOp is never constructed. |
| 8 | Ordered candidates become bounded isolated evidence; suspicious corpus text/metadata cannot become executable instruction and configured limits are honored. | 03-02 | ✗ FAILED | Unescaped provenance attributes, first-block budget bypass, ignored settings, and byte slicing violate the trust/bounds contract. |
| 9 | Valid markers resolve only to supplied evidence and citations preserve bounded excerpts and correct provenance under a closed provider output contract. | 03-02 | ✗ FAILED | Invalid IDs are silently removed; output is not closed-schema validated; citation metadata is taken from the wrong candidate for non-prefix citation order. |
| 10 | OpenRouter performs one timeout-bounded strict structured call after capability preflight, using effective settings, while automated tests remain provider-independent. | 03-02 | ✗ FAILED | Provider independence, preflight, and one call are present, but the request is `json_object`, not strict JSON Schema, and timeout/sampling/output settings are hardcoded. |
| 11 | The additive QueryRAG wire contract carries typed filters, effective session, answer basis, notices, structured citations, and retrieval snapshot fields without renumbering prior fields. | 03-03 | ✓ VERIFIED | Proto fields are additive (`lancet.proto:48-110`), generated Rust/Go bindings compile, and `buf lint` passes. Runtime field correctness is evaluated in truth 9. |
| 12 | Committed TOML/environment settings actually control the retrieval and generation behavior the service reports. | 03-03 | ✗ FAILED | Startup uses `Bm25Config::default()` (`main.rs:1516`), prompt uses constants (`main.rs:866-872`), and provider/snapshot values are hardcoded. |
| 13 | Go accepts a bounded strict `/rag/query` envelope and maps caller validation failures to HTTP 400. | 03-04 | ✗ FAILED | Unknown/trailing JSON and InvalidArgument mapping work, but the route body is unbounded (`gateway/main.go:629-640`). |
| 14 | The production embedding client retains its default while startup can inject a configured endpoint for local verification. | 03-04 | ✓ VERIFIED | `new_with_endpoint`/`from_env_with_endpoint` are wired from `main.rs:1519-1521`; focused endpoint test passes. The artifact query's missing `embedding_endpoint` literal in `client/mod.rs` is a heuristic false positive, not a stub. |
| 15 | A provider-independent real-process smoke uses isolated completed-corpus LanceDB, local embedding/metadata/chat mocks, generated-gRPC Ping, clean child environments, and bounded cleanup to return an answer through the real route. | 03-05 | ✓ VERIFIED | `TestRAGQueryCrossRuntime` passed exactly; test code verifies all three mocks, both evidence markers, Ping, direct binaries, scrubbed env, process teardown, and path release. |

**Score:** 7/15 truths verified (1 present, behavior-unverified)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|---|---|---|
| 1 | Transparent surviving-path/model-only behavior after retrieval/provider failure | Phase 6 | ROADMAP Phase 6 SC7; RAG-03 and DEBT-RAG-01/06. The current silent fallback was confirmed but is not counted as a Phase 03 acceptance gap. |
| 2 | Citation repair and transparent downgrade after an invalid marker | Phase 6 | ROADMAP Phase 6 SC7; DEBT-RAG-03. Phase 03 still must reject invalid output rather than silently publish it. |
| 3 | Atomic vector/BM25 visibility across re-ingestion and restart | Phase 6 | ROADMAP Phase 6 SC7; DEBT-RAG-04. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `engine/Cargo.toml` / `engine/Cargo.lock` | Approved Unicode dependencies and locked resolution | ✓ VERIFIED | Artifact query passes; locked Rust suite passes. |
| `engine/src/retrieval/bm25.rs` | Unicode BM25 snapshot/query | ✓ VERIFIED | Substantive, wired at startup/query, and focused tests pass. |
| `engine/src/retrieval/fusion.rs` | Weighted RRF/dedup/source ranks | ✓ VERIFIED | Substantive and used by QueryRAG; deterministic test passes. |
| `engine/src/rerank/mod.rs` | Async port and NoOp default | ⚠ ORPHANED | Substantive and unit-tested, but not injected or called by the service. |
| `engine/src/prompt.rs` | Bounded untrusted evidence and citation resolution | ✗ DEFECTIVE | Wired, but prompt-boundary escaping, first-block budget, and Unicode excerpt invariants fail. |
| `engine/src/generation/mod.rs` | Closed provider-neutral output | ✗ DEFECTIVE | Substantive/wired; schema is permissive and semantic grounding validation is absent. |
| `engine/src/generation/openrouter.rs` | Strict one-shot OpenRouter adapter | ✗ DEFECTIVE | Wired and one-shot, but uses `json_object` and hardcoded settings. |
| `engine/src/generation/tests.rs` | Prompt/provider/citation tests | ⚠ PARTIAL | Tests pass but omit adversarial provenance, first-block overflow, unknown fields, invalid IDs, marker mismatch, and finish reason; one test intentionally returns invalid `Format-1`. |
| `proto/lancet/v1/lancet.proto` and generated bindings | Additive typed QueryRAG contract | ✓ VERIFIED | Compiles in both workspaces; `buf lint` passes. |
| `engine/src/main.rs` | QueryRAG coordinator and startup readiness | ✗ DEFECTIVE | Full path is wired, but reranker, citation mapping, bounds, and settings are incomplete. |
| `config/config.toml` / `config/config.example.toml` | Explicit non-secret defaults | ⚠ PARTIAL | Values exist, but several are inert at runtime. |
| `engine/tests/config_startup.rs` | Readiness order and BM25 failure proof | ⚠ PARTIAL | Positive order test is valid; negative test never reaches BM25 construction. |
| `gateway/main.go` | Thin strict bounded `/rag/query` adapter | ✗ DEFECTIVE | Route/gRPC mapping work; request body is unbounded. |
| `gateway/main_test.go` | HTTP contracts and real cross-runtime smoke | ✓ VERIFIED / ⚠ GAP | Happy path is strong and passes; over-limit and adversarial citation/provider cases are absent. |
| `engine/src/client/mod.rs` / `engine/src/client/tests.rs` | Endpoint-injectable embedding client | ✓ VERIFIED | Explicit endpoint parameter and focused test prove the seam despite the frontmatter literal-pattern mismatch. |
| `engine/src/bin/seed_rag_fixture.rs` | Canonical deterministic completed-corpus fixture | ✓ VERIFIED | Built and exercised by the exact cross-runtime smoke. |
| `COVERAGE.md` | Five-plan coverage/deferred boundary | ✓ VERIFIED | Contains all plan ownership and debt markers; documentation was not treated as behavioral proof. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Query normalization | Dense + BM25 | One `QueryRequest`/`QueryFilters` | ✓ WIRED | Both paths receive the same normalized values in the public service path. |
| Dense + BM25 | Fusion | `fuse_candidates` | ✓ WIRED | Called in `main.rs:854-859`. |
| Fusion | Reranker | `Reranker::rerank` | ✗ NOT WIRED | Automated key-link query found a target symbol only; manual usage scan finds calls only in reranker unit tests. |
| Fusion | Prompt/evidence | `assemble_evidence_blocks` | ✓ WIRED, DEFECTIVE | Data flows, but trust/budget transformations are incorrect. |
| Prompt | Generator/OpenRouter | `GenerationRequest` / `Generator::generate` | ✓ WIRED, DEFECTIVE | One call occurs, but strict schema and effective settings do not flow. |
| Proto | Generated Rust/Go bindings | Buf generation contract | ✓ WIRED | Both language suites compile; `buf lint` passes. |
| TOML/env | Runtime settings | `load_settings` | ⚠ PARTIAL | Endpoint/address values flow; BM25, evidence, excerpt, embedding-model, timeout, sampling, output, and snapshot values do not all flow. |
| Go route | Generated gRPC client | `grpcEngine.QueryRAG(r.Context(), req)` | ✓ WIRED | Real-process smoke passes. |
| Seeder | Engine nodes table | Shared temporary LanceDB path/schema | ✓ WIRED | Real process opens the seeded completed corpus. |
| Local mocks | Embedder + metadata preflight + chat | Injected loopback endpoints | ✓ WIRED | Exact smoke observes one call to each expected contract. |

### Data-Flow Trace (Level 4)

| Artifact / stage | Data variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `gateway/main.go` | `ragQueryRequestBody` → `pb.QueryRAGRequest` | HTTP JSON | Yes | ✓ FLOWING |
| `engine/src/main.rs` | `query_request` | Generated gRPC request | Yes; validated and normalized | ✓ FLOWING |
| Dense/BM25 | `dense_candidates`, `bm25_candidates` | Canonical completed `nodes` table + query embedding | Yes; real LanceDB exercised in smoke | ✓ FLOWING |
| Fusion | `fused` | Both candidate vectors | Yes; deterministic RRF/dedup | ✓ FLOWING |
| Reranker | expected reranked vector | `fused` | No production call | ✗ DISCONNECTED |
| Prompt | `packed_evidence` | Final fused candidates | Real data, but unsafe/unbounded first-block transform | ✗ INVALID TRANSFORM |
| Generator | `model_output` | One local/provider response | Real response, insufficient validation | ✗ UNTRUSTED TRANSFORM |
| Citations | `proto_structured_citations` | Resolved evidence + final candidates | Mixed identities for non-prefix citation order | ✗ CORRUPTED MAPPING |
| Go response | protobuf JSON | Rust `QueryRagResponse` | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Rust workspace | `cargo test --manifest-path engine/Cargo.toml --locked` | 82 passed, 0 failed, 2 ignored; compiler warns Reranker unused/NoOp never constructed | ✓ PASS suite / blocker corroborated |
| Go workspace | `GOTELEMETRY=off; cd gateway; go test ./...` | All packages passed | ✓ PASS |
| Real cross-runtime user flow | `go test . -run '^TestRAGQueryCrossRuntime$' -count=1 -v` | PASS in 2.53s | ✓ PASS cooperative happy path |
| Initial BM25 positive ordering | Full Rust suite, `initial_bm25_ready_before_serving` | PASS | ✓ PASS |
| Initial BM25 failure boundary | Full Rust suite, `initial_bm25_failure_blocks_readiness` | Test passes, but setup fails during DB initialization | ⚠ TEST PASSES, TRUTH UNPROVEN |
| Proto lint | `buf lint` | Exit 0 | ✓ PASS |
| Formatting | `cargo fmt --manifest-path engine/Cargo.toml -- --check` | Exit 0 | ✓ PASS |
| Patch hygiene | `git diff --check` | Exit 0 | ✓ PASS |

### Probe Execution

No `probe-*.sh` path is declared by the phase plans/summaries, and no conventional project probe was found. **SKIPPED (no probes declared).**

### Requirements Coverage

All PLAN frontmatter requirement IDs were collected. Plans 03-01, 03-02, 03-03, and 03-05 declare `RAG-02`/`RAG-04`; Plan 03-04 declares `RAG-02`. No additional Phase 03 requirement is orphaned in `REQUIREMENTS.md`.

| Requirement | Source Plans | Description | Status | Evidence |
|---|---|---|---|---|
| RAG-02 | 03-01, 03-02, 03-03, 03-04, 03-05 | Dense vector + local BM25 retrieval, metadata filters, and deduplication | ✓ SATISFIED | Shared normalization, real dense/BM25 retrieval, deterministic RRF/dedup test, and cross-runtime completed-corpus smoke pass. |
| RAG-04 | 03-01, 03-02, 03-03, 03-05 | Async Reranker trait with NoOp as v1 default | ✗ BLOCKED | Trait/implementation/test exist, but the production QueryRAG path never constructs or invokes the default. |

`RAG-03` is correctly excluded from PLAN frontmatter and mapped to Phase 6. The `03-03-SUMMARY.md` claim that `RAG-03` completed is contradicted by the live roadmap/requirements and was not accepted as evidence.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `engine/src/main.rs` | 845 | `.unwrap_or_default()` on dense retrieval | ℹ DEFERRED | Confirms silent one-path fallback; transparent degraded semantics are Phase 6 RAG-03 work and are not scored as a Phase 03 blocker. |
| `engine/src/main.rs` | 25-30 | Library modules redeclared in the binary | ⚠ WARNING | Duplicates type/test ownership and generated 24 library warnings plus binary warnings, making dead wiring harder to see. |
| `engine/src/rerank/mod.rs` | 10-35 | Production-dead extension seam | 🛑 BLOCKER | Compiler and usage scan show the planned default is not wired. |
| Phase-modified files | — | `TBD` / `FIXME` / `XXX` / `TODO` / `HACK` / placeholder scan | ✓ NONE | No debt-marker blocker found in the modified-file scope. |

### Review Reconciliation

`03-REVIEW.md` was advisory only. Direct inspection independently confirmed:

- Current-goal blockers: CR-01 through CR-05, CR-07 through CR-12, WR-02, and WR-03, grouped into the five actionable gaps above.
- Confirmed but filtered from the Phase 03 blocker score: CR-06's degraded-path behavior and the failure-path portion of CR-13, because RAG-03/provider hardening is explicitly Phase 6 scope. Their code risks remain real.
- Confirmed warnings: WR-01, WR-04, and WR-05. WR-04 causes the behavior-unverified truth rather than a silent pass.
- The review's blanket “13 critical blockers” count was not copied into this verdict; only findings tied to the live MVP goal/PLAN truths were promoted.

### Human Verification Required

#### 1. Real BM25 build-failure readiness boundary

**Test:** Start the engine against a database that initializes successfully but has a schema-valid completed row with whitespace-only required content.

**Expected:** The BM25 builder identifies the bad row/field, the engine never emits `Rust RAG Engine serving`, and the gRPC endpoint never accepts Ping.

**Why human:** The current named failure test exits before BM25 construction, so static ordering plus a passing unrelated failure fixture cannot prove the state transition.

#### 2. Optional live OpenRouter structured-output smoke (non-gating)

**Test:** With a developer-owned `OPENROUTER_API_KEY`, run the ignored `openrouter_structured_output_smoke` after the deterministic blockers are fixed.

**Expected:** The selected model advertises structured output, exactly one bounded response succeeds, and no credential/raw-evidence content is emitted.

**Why human:** It depends on an external provider and credential. The plan explicitly makes this optional; it does not change the current `gaps_found` verdict.

### Gaps Summary

The implementation is a substantive, executable tracer: the real Go route, generated gRPC boundary, Rust hybrid retrieval, local provider mocks, and completed-corpus data all run. The phase goal is nevertheless not achieved because the final grounding contract is not trustworthy beyond the narrow first-citation fixture. Five grouped concerns block closure: evidence isolation/bounds, provider-output/citation integrity, production reranker wiring, effective configuration, and the bounded public HTTP envelope.

The most efficient closure plan should fix the citation/evidence pipeline first, wire the reranker second, then make configuration and boundary limits executable. The BM25 negative startup fixture should be corrected alongside those changes so the remaining behavior-unverified item can become verified.

---

_Verified: 2026-08-02T23:18:33Z_
_Verifier: the agent (gsd-verifier)_
