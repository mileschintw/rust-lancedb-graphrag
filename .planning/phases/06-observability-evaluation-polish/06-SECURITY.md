---
phase: 06
slug: observability-evaluation-polish
status: verified
threats_open: 0
asvs_level: 1
created: 2026-08-22
---

# Phase 06 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail for Phase 06 (Observability, Evaluation & Polish).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Process Environment → Engine / Gateway Configuration | `LANCET_*__*` environment variables cross into configuration loaders (`engine::config::load_settings`, `gateway/internal/config`). | Configuration keys, database URLs, port numbers, feature flags |
| HTTP Client → Gateway Request Body | Untrusted JSON crosses strict decoder (`ragQueryRequestBody`, ingestion requests). | User query strings, session UUIDs, corpus documents, filter expressions, request flags |
| Gateway → Engine gRPC Connection | gRPC request messages and streaming events cross loopback channel (`QueryRAGRequest`, `IngestRequest`). | Typed request parameters, presence flags, document chunks, status trailers |
| Engine Admission → Retrieval & Generator Nodes | Validated request parameters decide node execution paths. | Session IDs, query texts, filter limits, ablation and model-only flags |
| Vector & Lexical Stores → Retrieval Node | Candidate chunks from LanceDB / BM25 cross into node assembly. | Retrieved chunk text, chunk identifiers, vector distances, BM25 scores |
| Retrieved Evidence / Prompt → LLM Provider | Prompt template and packed evidence sent to external LLM provider via OpenRouter API. | System prompt instructions, packed evidence blocks, user query |
| LLM Provider Output → Engine Generation State | Serde-deserialized `ModelOutput` JSON crosses into engine workflow state. | Generated answer text, citation markers, self-reported basis, token usage |
| Citation Repair Engine → Client-Visible Citations | Unnormalized markers and spans resolved against retrieved evidence blocks. | Repaired citation IDs, stripped answer text spans, citation notices |
| Engine Streaming Events → Gateway SSE → HTTP Client | Workflow events, final responses, error kinds, and notice codes emitted over SSE stream. | Token streams, structured citations, typed notice codes, terminal metadata |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-06-01-01 | Tampering | `engine::config::load_settings` environment-override block | high | mitigate | Byte-for-byte literal relocation with 18 distinct `LANCET_*` variables gated. | closed |
| T-06-01-02 | Information Disclosure | Relocated `EffectiveRagSettings` / `OpenRouterSettings` visibility | low | accept | Types contain no secrets; visibility scoped within internal crate. | closed |
| T-06-01-03 | Denial of Service | Engine test coverage during chunker/config move | high | mitigate | `scripts/engine-test-targets.sh` validates 5 distinct test targets. | closed |
| T-06-02-01 | Tampering | Relocated `query_rag` admission validation | high | mitigate | UUIDv4 and `QueryRequest::from_values` checks run before stream/channel creation. | closed |
| T-06-02-02 | Repudiation | Relocated `d1_status` error identity contract | high | mitigate | Preserves 5-parameter signature, `x-lancet-session-id` metadata, and warning fields. | closed |
| T-06-02-03 | Denial of Service | Relocated ingestion bounds (`MAX_DOCUMENT_BYTES`, `MAX_CHUNK_SIZE`, `QUEUE_CAPACITY`) | medium | mitigate | Named constants moved with unchanged bounds; parser rejects over-limit configurations. | closed |
| T-06-02-04 | Denial of Service | Engine test coverage during service/ingest move | high | mitigate | Per-target test count gates enforced in `scripts/engine-test-targets.sh`. | closed |
| T-06-02-05 | Information Disclosure | Widened visibility of service internals | low | accept | In-repo crate producing binaries; only items named by `main()` or test roots are `pub`. | closed |
| T-06-03-01 | Denial of Service | Test coverage during binary-to-library test rehoming | high | mitigate | Explicit 261 lib / 0 bin target assertions in `scripts/engine-test-targets.sh`. | closed |
| T-06-03-02 | Tampering | Replacement glob import against library root | high | mitigate | Explicit prohibition against `use engine::*`; named module imports enforced. | closed |
| T-06-03-03 | Spoofing | Re-export alias reviving `crate::`-rooted path | high | mitigate | Zero non-comment re-export lines in `engine/src/main.rs`. | closed |
| T-06-03-04 | Tampering | Source-text guard test over `generation/mod.rs` | medium | mitigate | File untouched in 06-03; guard tests executed as part of full suite. | closed |
| T-06-04-01 | Tampering | Relocated `viper` environment bindings in gateway | high | mitigate | 3 binding literals appear once in `gateway/internal/config` and zero in `main.go`. | closed |
| T-06-04-02 | Tampering | Relocated fail-closed configuration checks | high | mitigate | Empty `database_url` and `sslmode=disable`-in-prod checks preserved. | closed |
| T-06-04-03 | Information Disclosure | Relocated DTO JSON tags leaking fields | medium | mitigate | JSON struct tags moved byte-for-byte in `gateway/internal/sse/dto.go`. | closed |
| T-06-04-04 | Repudiation | Notice-list precedence in SSE terminal events | high | mitigate | `workflow_completed` carries `notices` only when `final_response` is nil. | closed |
| T-06-04-05 | Denial of Service | Silent loss of Go test coverage during package split | high | mitigate | `scripts/gateway-test-targets.sh` asserts per-package rows and total counts. | closed |
| T-06-04-06 | Elevation of Privilege | OpenTelemetry dependency pulled into reserved stub | medium | mitigate | Zero `go.opentelemetry.io` references in `gateway/internal/telemetry`. | closed |
| T-06-05-01 | Info Disclosure / Tampering | Gateway→engine gRPC connection without TLS | high | transfer | Local loopback transport; tracked as `DEBT-CR-04-EXT` per D-03 / D-06 backlog. | closed |
| T-06-05-02 | Repudiation | Relocated trailer-carrying error type | high | mitigate | Status and trailer accessors preserved in `gateway/internal/engineclient`. | closed |
| T-06-05-03 | Tampering | Test double exported from production package | medium | mitigate | Function-field stub double kept in `gateway/main_test.go`, unexported from package. | closed |
| T-06-05-04 | Denial of Service | Silent loss of Go test coverage during 74-site migration | high | mitigate | Gated on `func Test` counts in `main_test.go` and `document_test.go`. | closed |
| T-06-05-05 | Tampering | Expectation loosened to make mis-qualified test pass | high | mitigate | Plan scope restricted to qualification refactoring; assertions unchanged. | closed |
| T-06-06-01 | Elevation of Privilege | Fake port/generator reachable in release build | high | mitigate | `#[cfg(test)]` placed individually on all fake types and implementations in `engine::testkit`. | closed |
| T-06-06-02 | Tampering | Extra JSON keys entering published payload unobserved | high | mitigate | Exact-key-set assertions on sorted literal keys in `gateway/main_test.go`. | closed |
| T-06-06-03 | Repudiation | Notice-list precedence drifting into both lists populated | high | mitigate | Terminal-frame test covers both branches in `gateway/main_test.go`. | closed |
| T-06-06-04 | Denial of Service | Silent loss of test coverage during ~100-site migration | high | mitigate | Per-target test counts enforced across engine and gateway test suites. | closed |
| T-06-06-05 | Tampering | Guard test broken by reorganizing generation module | medium | mitigate | Constructors appended without modifying preceding declarations/markers. | closed |
| T-06-07-01 | Elevation of Privilege | New request flags widening engine behavior by default | high | mitigate | Presence-preserving pointer fields with false default resolved in engine admission. | closed |
| T-06-07-02 | Tampering | Loosening strict unknown-field JSON decoder | high | mitigate | Single decoder call verified; test proves unrecognised fields return HTTP 400. | closed |
| T-06-07-03 | Repudiation | Notice carrying typed code with empty string code | high | mitigate | Typed notice constructor derives non-empty string directly from enum. | closed |
| T-06-07-04 | Tampering | Publishing enum value nothing can emit | high | mitigate | Tag 17 declared reserved with reason; all published enum variants tested. | closed |
| T-06-07-05 | Tampering | Desynchronized protobuf binding generation | high | mitigate | Root `buf generate` touches exactly 5 paths committed atomically. | closed |
| T-06-07-06 | Information Disclosure | Metadata object carrying fabricated values | medium | mitigate | Generated zero-values used for unpopulated fields; no synthesized metrics. | closed |
| T-06-07-07 | Tampering | Hand-editing generated protobuf binding files | high | mitigate | Generated files carry generated markers; strictly produced by pinned `buf` plugins. | closed |
| T-06-08-01 | Repudiation | Degraded answer indistinguishable from healthy one | high | mitigate | 3 non-failure empty-graph paths emit notices; distinct messages prevent collapse. | closed |
| T-06-08-02 | Elevation of Privilege | Request flag widening what caller can turn off | medium | mitigate | Flag only disables graph context, default false, resolved at admission. | closed |
| T-06-08-03 | Tampering | Caller-requested ablation reported as real outage | high | mitigate | Distinct `GRAPH_CONTEXT_DISABLED` notice code vs `GRAPH_UNAVAILABLE`. | closed |
| T-06-08-04 | Denial of Service | Graph work started before ablation early return | low | mitigate | Early return precedes port presence check and timeout invocation. | closed |
| T-06-08-05 | Tampering | Silent regression of existing graph failure notices | high | mitigate | Failure branches preserved and verified with regression tests. | closed |
| T-06-09-01 | Repudiation | Answer assembled from partial corpus presented as complete | high | mitigate | Path-specific notices (`RETRIEVAL_DEGRADED_DENSE` / `RETRIEVAL_DEGRADED_BM25`) emitted. | closed |
| T-06-09-02 | Denial of Service | Unbounded notice list under repeated per-variant failure | medium | mitigate | Notice message keyed on failure kind; de-duplicated across variants. | closed |
| T-06-09-03 | Tampering | Per-variant failure silently discarding accumulated candidates | high | mitigate | Retrieval loop continues on variant failure, retaining surviving candidates. | closed |
| T-06-09-04 | Repudiation | Converted path failing workflow while appearing to degrade | high | mitigate | Terminal success event emitted; verified by absence of node failure events. | closed |
| T-06-09-05 | Tampering | Suppressing zero-evidence notice when degrade notice present | high | mitigate | Zero-evidence emission unchanged; multi-notice ordering tested. | closed |
| T-06-10-01 | Repudiation | Model-only answer mistaken for grounded answer | high | mitigate | `AnswerBasis::ModelOnly` + `NoticeCode::ModelOnly` + empty citation list enforced. | closed |
| T-06-10-02 | Elevation of Privilege | Model-only opt-in widening behavior by default | high | mitigate | Config default false; resolution request-then-configuration-then-false. | closed |
| T-06-10-03 | Tampering | Mistyped environment value silently selecting wrong default | high | mitigate | Fail-closed configuration check in `engine::config::load_settings`. | closed |
| T-06-10-04 | Tampering | Lifting empty-citation guard unconditionally | high | mitigate | Guard relaxation strictly conditional on resolved flag AND declared basis. | closed |
| T-06-10-05 | Repudiation | Production and tracer paths diverging on same input | high | mitigate | Both gates updated symmetrically; tracer path verified by dedicated test. | closed |
| T-06-10-06 | Information Disclosure | Synthesized citation on model-only answer | medium | mitigate | Structured and unstructured citation lists asserted empty on model-only responses. | closed |
| T-06-10-07 | Denial of Service | Opted-in path adding generation call | low | accept | Opt-in feature per request; default path incurs zero generation cost. | closed |
| T-06-10-08 | Tampering | Runner bypass without updating empty-evidence hard fail | high | mitigate | `assemble_prompt.rs` only fails on empty evidence when `allow_model_only` is false. | closed |
| T-06-11-01 | Repudiation / Tampering | Fabricated or unresolvable citations presented as grounding | high | mitigate | Exact equality normalization; unresolved markers stripped from text and citation list. | closed |
| T-06-11-02 | Tampering | Repair guessing plausible citation target | high | mitigate | Ties dropped immediately, never assigned; symmetric normalization applied. | closed |
| T-06-11-03 | Tampering / Elev Privilege | Prompt injection via retrieved evidence with precedence | medium | accept | Documented user design decision: corpus evidence prioritised over model priors. | closed |
| T-06-11-04 | Repudiation | Reconciliation strengthening provenance claim | high | mitigate | One-directional conservatism: weaker basis always selected. | closed |
| T-06-11-05 | DoS / Info Disclosure | Second provider call inside citation repair pass | high | mitigate | Synchronous, local string normalization with zero LLM provider round-trips. | closed |
| T-06-11-06 | Tampering | Mistyped repair environment variable selecting fail-closed | high | mitigate | Fail-closed configuration check on `LANCET_ENGINE__WORKFLOW__CITATION_REPAIR_ENABLED`. | closed |
| T-06-11-07 | Tampering | Editing structured-output schema while changing prompt | high | mitigate | LLM JSON schema frozen; provider request format unchanged. | closed |
| T-06-12-01 | Denial of Service | Oversized or malformed input reaching retrieval or provider | high | mitigate | Admission validation executes before stream/channel creation; fake calls assert 0. | closed |
| T-06-12-02 | Denial of Service | Filter-parameter abuse via oversized identifier lists | medium | mitigate | Maximum count bounds verified by bad-input table test cases. | closed |
| T-06-12-03 | Tampering | Injection via malformed session or document identifier | high | mitigate | Strict UUID parsing in engine admission rejects malformed input. | closed |
| T-06-12-04 | Repudiation | Missing or unstable error identity on rejection | high | mitigate | Gated on gRPC status code + error-kind string, and HTTP status + header. | closed |
| T-06-12-05 | Tampering | Gateway validation rule drifting from engine validation | high | mitigate | Gateway passes through engine error status without duplicated local validation. | closed |
| T-06-12-06 | Tampering | Converting valid zero-match query into rejection | high | mitigate | Unmatched/contradictory filter queries return success with `NO_EVIDENCE` notice. | closed |
| T-06-12-07 | Repudiation | Tautological test table passing against broken validator | high | mitigate | Expected error kinds and status codes asserted as literal constants. | closed |
| T-06-13-01 | Spoofing | MODEL_ONLY response on empty-evidence opt-in path | high | mitigate | `AnswerBasis::ModelOnly` + `NoticeCode::ModelOnly` + empty citations verified. | closed |
| T-06-13-02 | Elevation of Privilege | OpenRouter schema enum admitting model_only | high | mitigate | `model_only` added as enum variant; conservative reconciliation prevents over-claiming. | closed |
| T-06-13-03 | Tampering | `pack_evidence_and_graph_prompt` empty-evidence failure | high | mitigate | Hard fail retained when flag off; gated on empty evidence AND `allow_model_only`. | closed |
| T-06-13-04 | Information Disclosure | Model-only prompt policy leaking evidence formatting | medium | mitigate | Dedicated ungrounded prompt policy without citation instructions or raw body logging. | closed |
| T-06-13-SC | Tampering | Supply-chain dependency tampering in plan 06-13 | high | accept | Zero crate dependencies added; `Cargo.lock` locked. | closed |
| T-06-14-01 | Tampering | Citation repair de-duplication | high | mitigate | Exact-one-match resolution; de-dupe only identical resolved IDs; ties dropped. | closed |
| T-06-14-02 | Spoofing | Duplicate citation IDs on wire | high | mitigate | Unique first-occurrence repaired citations emitted to prevent double-counting. | closed |
| T-06-14-03 | Information Disclosure | Collapsing citation notices during ID de-duplication | medium | mitigate | Per-occurrence `CITATION_REPAIRED` / `CITATION_DROPPED` notices preserved. | closed |
| T-06-14-SC | Tampering | Supply-chain dependency tampering in plan 06-14 | high | accept | Zero crate dependencies added; `Cargo.lock` locked. | closed |
| T-06-15-01 | Spoofing | Marker checks relocated from `execute_one_call` to node | high | mitigate | Every generation call path (P0, P1a, P1b, P1c, P2) terminates in named composed validator. | closed |
| T-06-15-02 | Elevation of Privilege | `run_inline_prompt_generation_remainder` validation-free | high | mitigate | Composed grounding validator added before context mutation. | closed |
| T-06-15-03 | Spoofing | Known-ID universe widening from packed to retrieved evidence | medium | mitigate | `resolve_markers` drops ties/unmatched; `resolve_citations` matches real chunks. | closed |
| T-06-15-04 | Tampering | Repair-disabled branch losing fail-closed behavior | high | mitigate | Branch 3 unedited; fail-closed behavior pinned by regression tests. | closed |
| T-06-15-05 | Information Disclosure | Model-only answer leaking evidence marker | medium | mitigate | `into_model_only()` validated with empty citation expectation; fails closed if marker present. | closed |
| T-06-15-06 | Repudiation | Rejected generation stopping silently on remainder path | low | mitigate | `NodeFailed` event emitted with error kind and description. | closed |
| T-06-15-SC | Tampering | Supply-chain dependency tampering in plan 06-15 | high | accept | Zero new dependencies; builds locked to pinned lockfiles. | closed |

*Status: 83 closed · 0 open*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| RISK-06-01 | T-06-01-02 | Widened visibility of `EffectiveRagSettings` and `OpenRouterSettings` within library crate. The relocated types contain no secret values; `config.toml` defaults `database_url = ""` and API keys are passed out-of-band. | Plan 06-01 | 2026-08-22 |
| RISK-06-02 | T-06-02-05 | Widened visibility of service internals to library consumers. Crate produces two binaries in one repository with no external consumers; only items required by binaries/tests are `pub`. | Plan 06-02 | 2026-08-22 |
| RISK-06-03 | T-06-05-01 | Gateway→engine gRPC dial without transport security (`DEBT-CR-04-EXT`). Architecture is local-only and loopback-bound (`127.0.0.1`); transferred to Security & transport backlog per D-03 / D-06. | Plan 06-05 | 2026-08-22 |
| RISK-06-04 | T-06-10-07 | Opted-in model-only path adds generation call where empty-evidence previously returned error. Opt-in feature explicitly requested by caller; default path remains false with zero LLM cost. | Plan 06-10 | 2026-08-22 |
| RISK-06-05 | T-06-11-03 | Precedence instruction elevates retrieved evidence authority over model priors. Deliberate user requirement to ensure grounded corpus evidence takes precedence over training memory. | Plan 06-11 | 2026-08-22 |
| RISK-06-06 | T-06-13-SC, T-06-14-SC, T-06-15-SC | External dependency supply-chain risk. Zero new package dependencies added across Phase 06; all builds verified against pinned `Cargo.lock` / `go.mod`. | Plans 06-13, 06-14, 06-15 | 2026-08-22 |
| RISK-06-07 | T-06-15-03 | Known-ID universe widens from packed evidence subset to retrieved evidence set during node-level validation. Markers naming retrieved but prompt-truncated chunks resolve instead of rejecting; mitigated by strict single-match resolution and chunk binding. | Plan 06-15 | 2026-08-22 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-08-22 | 83 | 83 | 0 | gsd-secure-phase |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-08-22
