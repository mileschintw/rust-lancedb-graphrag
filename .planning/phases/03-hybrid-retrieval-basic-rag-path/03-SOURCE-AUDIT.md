# Phase 03 Source Coverage Audit

**Phase:** 03 — Hybrid Retrieval and Basic RAG Path
**Audit status:** complete; no unplanned in-scope items
**Scope authority:** accepted MVP Paths split in the planning request, `03-CONTEXT.md`, and `deferred-items.md`

The executable slice is one valid-query path over a query-ready completed corpus. The failure-path behaviors listed as accepted debt remain visible below and are not executable tasks.

## GOAL and REQ coverage

| source | ID | feature or requirement | plan | status | notes |
|---|---|---|---|---|---|
| GOAL | — | A chat service user asks a question through hybrid vector and BM25 retrieval and receives a grounded LLM answer. | 03-01 | COVERED | Full HTTP-to-provider tracer. |
| REQ | RAG-02 | Dense vector plus local BM25 retrieval, metadata filtering, and deduplication. | 03-01, 03-02 | COVERED | Real LanceDB and in-memory BM25 paths, RRF, filters, and deterministic tests. |
| REQ | RAG-03 | Degraded retrieval when one path fails. | 03-01, 03-03 | COVERED — BOUNDARY/DEFERRED | Typed per-path result capacity and public fields are preserved; retrieval/model fallback is `DEBT-RAG-01` and graph-extraction unavailability is explicitly `DEBT-RAG-06` in `deferred-items.md`. |
| REQ | RAG-04 | Async `Reranker` port with pass-through `NoOpReranker`. | 03-01, 03-02 | COVERED | Injectable boxed-future port and order-preserving implementation. |

## RESEARCH coverage

| source | item | plan | status | notes |
|---|---|---|---|---|
| RESEARCH | Rust-owned custom provider-neutral pipeline using existing Tokio, LanceDB, Arrow, reqwest, Serde, tiktoken-rs, tonic/prost, Go chi, and generated bindings. | 03-01 | COVERED | No RAG framework or second search service is introduced. |
| RESEARCH | Approved Unicode analysis dependencies and package legitimacy audit for `unicode-normalization`, `unicode-casefold`, and `unicode-segmentation`. | 03-01 | COVERED | Cargo manifest and lockfile use the approved crates and locked versions. |
| RESEARCH | Canonical completed LanceDB rows plus a derived BM25 snapshot. | 03-01, 03-02 | COVERED | Current completed corpus is indexed before query readiness; replacement/restart atomicity remains debt. |
| RESEARCH | Same-filter dense and BM25 candidate selection, global IDF, field boosts, technical identifier analysis, weighted RRF, deduplication, and stable tie-breaking. | 03-01, 03-02 | COVERED | D-01 through D-10 and D-44 through D-53 are traced to implementation and tests. |
| RESEARCH | Async `NoOpReranker` extension port. | 03-01, 03-02 | COVERED | No non-pass-through reranker is planned. |
| RESEARCH | Bounded whole-chunk evidence, generated provenance IDs, escaped delimiters, and untrusted-evidence framing. | 03-01, 03-03 | COVERED | Prompt assembly is Rust-owned and source text remains data. |
| RESEARCH | Closed Serde model output, one OpenRouter structured chat call, configurable model and sampling, timeout, usage metadata, typed provider errors, and supported-parameters preflight/live smoke. | 03-01, 03-03 | COVERED | Local mock tests prove request shape and one-call behavior; Plan 03-03 adds metadata preflight plus an explicitly ignored real-provider smoke. |
| RESEARCH | Additive protobuf evolution, generated Rust and Go bindings, thin Go route, context forwarding, and stable HTTP status mapping. | 03-01, 03-03 | COVERED | Existing field numbers remain intact. |
| RESEARCH | Query/session/filter validation and bounds. | 03-01, 03-03 | COVERED | 8 KiB query, UUID session, normalized filter limits, strict body decoding, and invalid-argument mapping. |
| RESEARCH | Isolated LanceDB fixtures, fake embedding/generator seams, startup readiness proof, provider-independent Go-to-generated-gRPC-to-Rust smoke, and Rust/Go test commands. | 03-01, 03-02, 03-03 | COVERED | Fixtures are temporary; the cross-runtime smoke uses a localhost provider mock and does not stub the Rust QueryRAG RPC. |
| RESEARCH | Security controls for session/input validation, typed predicates, prompt injection, credential redaction, context bounds, and cross-index consistency. | 03-01, 03-02, 03-03 | COVERED | Each plan contains a STRIDE register. |
| RESEARCH | Resolved assumptions A1–A5: metadata-checked configurable model, isolated fixtures, explicit candidate/final/evidence bounds, stable provider/internal mapping, and no PostgreSQL dependency for deterministic tests. | 03-01, 03-03 | COVERED | Answers are recorded in `03-RESEARCH.md` under `## Open Questions (RESOLVED)` and in the revised plans. |
| RESEARCH | External OpenRouter API surface and explicit capability subtraction. | 03-03 | COVERED | `COVERAGE.md` enumerates the integrated surface and opt-outs. |
| RESEARCH | Graph context, workflow state machine, streaming, retries, provider fallback, evaluation tuning, tracing, and non-NoOp reranking. | — | EXCLUDED | Explicitly scoped to Phases 4–6 or Phase 999.2; not Phase 03 executable work. |

## CONTEXT decision coverage

| ID | locked decision summary | plan | status |
|---|---|---|---|
| D-01 | Weighted Reciprocal Rank Fusion combines dense and BM25 ranks. | 03-01, 03-02 | COVERED |
| D-02 | Merge results by `chunk_id` while retaining both source ranks and one fused score. | 03-01, 03-02 | COVERED |
| D-03 | Vector and BM25 weights default to 1.0 and are configurable. | 03-01 | COVERED |
| D-04 | RRF `k` defaults to 60 and is configurable. | 03-01 | COVERED |
| D-05 | Candidate/final limits are configurable and the phase supplies `NoOpReranker`. | 03-01, 03-02 | COVERED |
| D-06 | No filters search the global completed corpus. | 03-01, 03-02 | COVERED |
| D-07 | Query filters expose document IDs and content types. | 03-01, 03-03 | COVERED |
| D-08 | Values OR within a field and AND across fields. | 03-02 | COVERED |
| D-09 | Identical filters constrain dense and BM25 before fusion. | 03-01, 03-02 | COVERED |
| D-10 | Malformed filters are invalid arguments; valid no-match filters produce empty evidence. | 03-01, 03-03 | COVERED as contract guard |
| D-11 | One retrieval-path failure continues with the surviving path. | — | DEFERRED — `DEBT-RAG-01` |
| D-12 | Both retrieval paths can lead to a model-only answer with warnings. | — | DEFERRED — `DEBT-RAG-01` |
| D-13 | Empty or weak evidence does not block generation. | — | DEFERRED — `DEBT-RAG-01` |
| D-14 | Responses report retrieval, mixed, or model-only answer basis. | 03-01, 03-03 | COVERED as typed response/model contract; degraded branches deferred |
| D-15 | Degraded responses identify unavailable retrieval paths. | — | DEFERRED — `DEBT-RAG-01` |
| D-16 | Model-only responses carry a separate notice and no citations. | — | DEFERRED — `DEBT-RAG-01` |
| D-17 | The generation output proposes answer basis without a separate classifier call. | 03-01, 03-03 | COVERED for valid output; degraded selection deferred |
| D-18 | Gateway exposes unary `POST /rag/query`. | 03-01, 03-03 | COVERED |
| D-19 | Request carries question, optional session, and typed filters. | 03-01, 03-03 | COVERED |
| D-20 | Session IDs are validated; absent IDs are generated and returned. | 03-01, 03-03 | COVERED |
| D-21 | Citations contain structured provenance and retrieval metadata. | 03-01, 03-03 | COVERED |
| D-22 | Retrieval-backed and mixed text uses numbered citation markers. | 03-01, 03-03 | COVERED for valid output; each marker resolves to its ordered engine evidence object |
| D-23 | Excerpts are bounded and expose truncation. | 03-01, 03-03 | COVERED |
| D-24 | Invalid markers receive repair and downgrade. | — | DEFERRED — `DEBT-RAG-03` |
| D-25 | Responses include a compact retrieval snapshot. | 03-01 | COVERED |
| D-26 | Generation is an injectable provider-neutral async Rust trait. | 03-01, 03-03 | COVERED |
| D-27 | OpenRouter is the configurable default adapter. | 03-01, 03-03 | COVERED |
| D-28 | Model output is strict structured data and is validated before response assembly. | 03-01, 03-03 | COVERED |
| D-29 | Phase 03 makes one generation attempt. | 03-01, 03-03 | COVERED |
| D-30 | Generation timeout defaults to 30 seconds and cancellation reaches provider work. | 03-01, 03-03 | COVERED |
| D-31 | Generation failure is a structured provider error with identity and no fabricated answer. | 03-03 | COVERED as boundary contract |
| D-32 | Sampling defaults to temperature 0 and top-p 1. | 03-01, 03-03 | COVERED |
| D-33 | Output budget defaults to 2,048 tokens. | 03-01, 03-03 | COVERED |
| D-34 | Answers are direct, concise, proportional, and citation-adjacent. | 03-01, 03-03 | COVERED in prompt contract |
| D-35 | Retrieved content is untrusted evidence, not executable instruction. | 03-01, 03-03 | COVERED |
| D-36 | Evidence blocks have generated IDs, provenance, and escaped delimiters. | 03-01, 03-03 | COVERED |
| D-37 | Prompt-injection text remains marked evidence and is flagged. | 03-01, 03-03 | COVERED in framing/notice seam |
| D-38 | Corpus conflicts are disclosed and classified as mixed. | 03-01, 03-03 | COVERED in typed model contract |
| D-39 | Answer budget is reserved first and whole evidence chunks are packed in rank order. | 03-01, 03-03 | COVERED |
| D-40 | Completed ingestion means vector and BM25 representations are query-ready. | 03-01, 03-02 | COVERED for the current query-ready snapshot; initial build is wave 1 |
| D-41 | Re-ingestion keeps the previous completed version until atomic switch. | — | DEFERRED — `DEBT-RAG-04` |
| D-42 | Restart rebuilds BM25 before readiness. | 03-01, 03-02 | COVERED for initial startup build; dynamic restart/re-ingestion recovery is deferred — `DEBT-RAG-04` |
| D-43 | BM25 rebuild failure fails startup rather than serving vector-only. | 03-01, 03-02 | COVERED for the initial current-corpus build; dynamic restart/re-ingestion recovery is deferred — `DEBT-RAG-04` |
| D-44 | BM25 uses NFKC, Unicode case folding, and original source preservation. | 03-01, 03-02 | COVERED |
| D-45 | No stemming or stop-word removal. | 03-01, 03-02 | COVERED |
| D-46 | Content/title/section fields use 1.0/2.0/1.5 boosts. | 03-01, 03-02 | COVERED |
| D-47 | Any query term can match and cumulative matches score higher. | 03-02 | COVERED |
| D-48 | Technical identifiers retain whole and camel/underscore/hyphen subtokens. | 03-01, 03-02 | COVERED |
| D-49 | BM25 defaults are `k1=1.2` and `b=0.75`, configurable. | 03-01, 03-02 | COVERED |
| D-50 | IDF is global; filters only constrain candidates. | 03-02 | COVERED |
| D-51 | Equal RRF scores use best source rank, document ID, chunk index, then chunk ID. | 03-02 | COVERED |
| D-52 | Full precision ranks internally; diagnostics round only at serialization. | 03-02 | COVERED |
| D-53 | Same normalized query/filter/generation/configuration returns identical ordered IDs. | 03-02 | COVERED |
| D-54 | Empty questions are rejected before retrieval/provider work. | 03-01, 03-03 | COVERED |
| D-55 | Query input is limited to configurable 8 KiB UTF-8. | 03-01, 03-03 | COVERED |
| D-56 | Filter values normalize/dedupe before 100-ID and 16-type limits. | 03-01, 03-03 | COVERED |
| D-57 | Outer whitespace is trimmed while generation keeps original semantics and retrieval gets normalized views. | 03-01, 03-02 | COVERED |

## Accepted deferred scope

`DEBT-RAG-01` through `DEBT-RAG-06` in [deferred-items.md](deferred-items.md) remain out of executable tasks. The plans preserve only the typed seams and safeguards needed for a trustworthy valid-query path; they do not claim full RAG-03 completion.
