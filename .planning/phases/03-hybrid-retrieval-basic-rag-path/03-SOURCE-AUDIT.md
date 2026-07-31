# Phase 03 Source Coverage Audit

**Phase:** 03 — Hybrid Retrieval and Basic RAG Path
**Audit status:** complete; no unplanned in-scope items
**Scope authority:** `ROADMAP.md`, `REQUIREMENTS.md`, `03-RESEARCH.md`, locked decisions in `03-CONTEXT.md`, and the accepted debt ledger in `deferred-items.md`

The revised executable slice is five sequential vertical handoffs. Together they prove one valid query over a query-ready completed corpus through the real Go gateway, Rust gRPC service, dense/BM25 retrieval, bounded evidence, and one structured generation call. Deferred failure paths remain visible below and are not executable tasks.

## GOAL and REQ coverage

| source | ID | feature or requirement | plan | status | notes |
|---|---|---|---|---|---|
| GOAL | — | A chat service user asks a question through hybrid vector and BM25 retrieval and receives a grounded LLM answer. | 03-01, 03-02, 03-03, 03-04, 03-05 | COVERED | Plans 03-01 through 03-04 establish sequential handoffs; 03-05 runs the provider-independent real-process proof. |
| REQ | RAG-02 | Dense vector plus local BM25 retrieval, metadata filtering, and deduplication. | 03-01, 03-03, 03-05 | COVERED | Plan 03-01 owns full Unicode BM25, dense retrieval, RRF, filters, and deterministic tests; Plan 03-03 makes the initial snapshot query-ready; Plan 03-05 proves the real combined path. |
| REQ | RAG-03 | Degraded retrieval when one path fails. | 03-02, 03-03, 03-04, 03-05 | COVERED — BOUNDARY/DEFERRED | Typed independent outcomes, answer-basis/warning capacity, provider errors, and gateway mapping are preserved; degraded retrieval/model-only behavior is `DEBT-RAG-01`, graph unavailability is `DEBT-RAG-06`, and citation repair is `DEBT-RAG-03`. |
| REQ | RAG-04 | Async `Reranker` port with pass-through `NoOpReranker`. | 03-01, 03-03, 03-05 | COVERED | Plan 03-01 owns the port and deterministic pass-through; later plans carry it through Rust service startup and the real smoke. |

## RESEARCH coverage

| source | item | plan | status | notes |
|---|---|---|---|---|
| RESEARCH | Rust-owned custom provider-neutral pipeline using existing Tokio, LanceDB, Arrow, reqwest, Serde, tiktoken-rs, tonic/prost, Go chi, and generated bindings. | 03-01, 03-02, 03-03, 03-04, 03-05 | COVERED | The five plans preserve Rust semantic ownership, a thin Go boundary, and the existing client/tooling stack. |
| RESEARCH | Approved Unicode analysis dependencies and package legitimacy audit for `unicode-normalization`, `unicode-casefold`, and `unicode-segmentation`. | 03-01 | COVERED | `engine/Cargo.toml` and `engine/Cargo.lock` are in the first plan that compiles the full analyzer; no reduced analyzer is permitted. |
| RESEARCH | Canonical completed LanceDB rows plus a derived BM25 snapshot. | 03-01, 03-03, 03-05 | COVERED | Retrieval tests cover derived indexing, startup builds the current snapshot before readiness, and the real smoke seeds the same canonical completed schema in an isolated temporary store. Replacement/restart atomicity remains debt. |
| RESEARCH | Same-filter dense and BM25 candidate selection, global IDF, field boosts, technical identifier analysis, weighted RRF, deduplication, and stable tie-breaking. | 03-01, 03-03, 03-05 | COVERED | Plan 03-01 implements and tests the semantics; Plan 03-03 wires the settings; Plan 03-05 exercises a dense hit and a lexical identifier hit. |
| RESEARCH | Async `NoOpReranker` extension port. | 03-01, 03-03, 03-05 | COVERED | The pass-through port is introduced with the retrieval contract and reaches the real service/smoke path. |
| RESEARCH | Bounded whole-chunk evidence, generated provenance IDs, escaped delimiters, and untrusted-evidence framing. | 03-02, 03-03, 03-05 | COVERED | Prompt assembly and citation semantics remain Rust-owned; the smoke checks the structured marker/provenance result. |
| RESEARCH | Closed Serde model output, one OpenRouter structured chat call, configurable model and sampling, timeout, usage metadata, typed provider errors, and `supported_parameters` preflight/live smoke. | 03-02, 03-03, 03-05 | COVERED | Local metadata/chat mocks prove the automated contract; the real provider check remains an ignored manual test. |
| RESEARCH | Additive protobuf evolution, generated Rust and Go bindings, thin Go route, context forwarding, and stable HTTP status mapping. | 03-03, 03-04, 03-05 | COVERED | The contract is generated from one additive proto source, the route is strict/lossless, and the smoke traverses the generated client to the real Rust process. |
| RESEARCH | Query/session/filter validation and bounds. | 03-03, 03-04, 03-05 | COVERED | Rust owns normalized bounds and typed predicates; Go owns strict envelope decoding and status mapping; the real smoke proves the valid path. |
| RESEARCH | Isolated LanceDB fixtures, fake embedding/generator seams, startup readiness proof, provider-independent Go-to-generated-gRPC-to-Rust smoke, and Rust/Go test commands. | 03-01, 03-02, 03-03, 03-04, 03-05 | COVERED | Unit fixtures and fake Generator are introduced at their owning handoffs; Plan 03-04 adds the embedding endpoint seam; Plan 03-05 supplies the reusable real seed, three deterministic provider mocks, child-process cleanup, and the cross-runtime assertion. |
| RESEARCH | Security controls for session/input validation, typed predicates, prompt injection, credential redaction, context bounds, and cross-index consistency. | 03-01, 03-02, 03-03, 03-04, 03-05 | COVERED | Every plan carries a STRIDE register with concrete mitigations. |
| RESEARCH | Resolved assumptions A1–A5: metadata-checked configurable model, isolated fixtures, explicit candidate/final/evidence bounds, stable provider/internal mapping, and no PostgreSQL dependency for deterministic tests. | 03-02, 03-03, 03-04, 03-05 | COVERED | Provider settings and preflight are in Plans 03-02/03; endpoint injection is in 03-04; the isolated no-PostgreSQL process proof is in 03-05. |
| RESEARCH | External OpenRouter API surface and explicit capability subtraction. | 03-02, 03-05 | COVERED | `COVERAGE.md` records the integrated unary surface and Plan 03-05 proves the equivalent `localhost` contracts; live access remains optional/manual. |
| RESEARCH | Graph context, workflow state machine, streaming, retries, provider fallback, evaluation tuning, tracing, and non-NoOp reranking. | — | EXCLUDED | Explicitly scoped to later phases or the accepted debt ledger; no plan claims these behaviors. |

## CONTEXT decision coverage

| ID | locked decision summary | plan | status |
|---|---|---|---|
| D-01 | Weighted Reciprocal Rank Fusion combines dense and BM25 ranks. | 03-01, 03-05 | COVERED |
| D-02 | Merge results by `chunk_id` while retaining both source ranks and one fused score. | 03-01, 03-05 | COVERED |
| D-03 | Vector and BM25 weights default to 1.0 and are configurable. | 03-01, 03-03 | COVERED |
| D-04 | RRF `k` defaults to 60 and is configurable. | 03-01, 03-03 | COVERED |
| D-05 | Candidate/final limits are configurable and the phase supplies `NoOpReranker`. | 03-01, 03-02, 03-03 | COVERED |
| D-06 | No filters search the global completed corpus. | 03-01, 03-03, 03-05 | COVERED |
| D-07 | Query filters expose document IDs and content types. | 03-01, 03-03, 03-04, 03-05 | COVERED |
| D-08 | Values OR within a field and AND across fields. | 03-01, 03-03, 03-05 | COVERED |
| D-09 | Identical filters constrain dense and BM25 before fusion. | 03-01, 03-03, 03-05 | COVERED |
| D-10 | Malformed filters are invalid arguments; valid no-match filters produce empty evidence. | 03-01, 03-03, 03-04 | COVERED as contract guard |
| D-11 | One retrieval-path failure continues with the surviving path. | 03-02, 03-03 | DEFERRED — `DEBT-RAG-01`; only typed independent outcome capacity is carried. |
| D-12 | Both retrieval paths can lead to a model-only answer with warnings. | 03-02, 03-03 | DEFERRED — `DEBT-RAG-01`; response fields are capacity only. |
| D-13 | Empty or weak evidence does not block generation. | 03-02, 03-03 | DEFERRED — `DEBT-RAG-01`; the valid grounded path is the only executed branch. |
| D-14 | Responses report retrieval, mixed, or model-only answer basis. | 03-02, 03-03, 03-05 | COVERED for strict typed output; degraded selection remains deferred. |
| D-15 | Degraded responses identify unavailable retrieval paths. | 03-02, 03-03 | DEFERRED — `DEBT-RAG-01`. |
| D-16 | Model-only responses carry a separate notice and no citations. | 03-02, 03-03 | DEFERRED — `DEBT-RAG-01`. |
| D-17 | The generation output proposes answer basis without a separate classifier call. | 03-02, 03-03, 03-05 | COVERED for valid output; degraded selection remains deferred. |
| D-18 | Gateway exposes unary `POST /rag/query`. | 03-03, 03-04, 03-05 | COVERED |
| D-19 | Request carries question, optional session, and typed filters. | 03-03, 03-04, 03-05 | COVERED |
| D-20 | Session IDs are validated; absent IDs are generated and returned. | 03-03, 03-04, 03-05 | COVERED |
| D-21 | Citations contain structured provenance and retrieval metadata. | 03-02, 03-03, 03-04, 03-05 | COVERED |
| D-22 | Retrieval-backed and mixed text uses numbered citation markers. | 03-02, 03-03, 03-04, 03-05 | COVERED for valid output; markers resolve to ordered engine evidence. |
| D-23 | Excerpts are bounded and expose truncation. | 03-02, 03-03, 03-04, 03-05 | COVERED |
| D-24 | Invalid markers receive repair and downgrade. | 03-02, 03-03 | DEFERRED — `DEBT-RAG-03`; only the bounded validation seam is preserved. |
| D-25 | Responses include a compact retrieval snapshot. | 03-03, 03-04, 03-05 | COVERED |
| D-26 | Generation is an injectable provider-neutral async Rust trait. | 03-02, 03-03 | COVERED |
| D-27 | OpenRouter is the configurable default adapter. | 03-02, 03-03, 03-04, 03-05 | COVERED; Plan 03-04 adds only the endpoint seam needed by deterministic local verification. |
| D-28 | Model output is strict structured data and is validated before response assembly. | 03-02, 03-03, 03-05 | COVERED |
| D-29 | Phase 03 makes one generation attempt. | 03-02, 03-03, 03-05 | COVERED |
| D-30 | Generation timeout defaults to 30 seconds and cancellation reaches provider work. | 03-02, 03-03, 03-05 | COVERED |
| D-31 | Generation failure is a structured provider error with identity and no fabricated answer. | 03-02, 03-03, 03-04, 03-05 | COVERED as contract/boundary behavior; fallback remains deferred. |
| D-32 | Sampling defaults to temperature 0 and top-p 1. | 03-02, 03-03, 03-05 | COVERED |
| D-33 | Output budget defaults to 2,048 tokens. | 03-02, 03-03, 03-05 | COVERED |
| D-34 | Answers are direct, concise, proportional, and citation-adjacent. | 03-02, 03-03, 03-05 | COVERED in prompt and local completion contract. |
| D-35 | Retrieved content is untrusted evidence, not executable instruction. | 03-02, 03-03, 03-05 | COVERED |
| D-36 | Evidence blocks have generated IDs, provenance, and escaped delimiters. | 03-02, 03-03, 03-05 | COVERED |
| D-37 | Prompt-injection text remains marked evidence and is flagged. | 03-02, 03-03, 03-05 | COVERED in framing/notice capacity; no fallback branch is added. |
| D-38 | Corpus conflicts are disclosed and classified as mixed. | 03-02, 03-03, 03-05 | COVERED in the typed model contract and valid response path. |
| D-39 | Answer budget is reserved first and whole evidence chunks are packed in rank order. | 03-02, 03-03, 03-05 | COVERED |
| D-40 | Completed ingestion means vector and BM25 representations are query-ready. | 03-01, 03-03, 03-05 | COVERED for the initial completed snapshot. |
| D-41 | Re-ingestion keeps the previous completed version until atomic switch. | 03-03 | DEFERRED — `DEBT-RAG-04`; plans do not implement dynamic replacement/recovery. |
| D-42 | Restart rebuilds BM25 before readiness. | 03-03, 03-05 | COVERED for initial startup/rebuild ordering; dynamic recovery remains `DEBT-RAG-04`. |
| D-43 | BM25 rebuild failure fails startup rather than serving vector-only. | 03-03 | COVERED for the initial current-corpus build; dynamic recovery remains `DEBT-RAG-04`. |
| D-44 | BM25 uses NFKC, Unicode case folding, and original source preservation. | 03-01, 03-05 | COVERED with the full analyzer in the first plan and real-path proof. |
| D-45 | No stemming or stop-word removal. | 03-01 | COVERED |
| D-46 | Content/title/section fields use 1.0/2.0/1.5 boosts. | 03-01, 03-03 | COVERED |
| D-47 | Any query term can match and cumulative matches score higher. | 03-01, 03-05 | COVERED |
| D-48 | Technical identifiers retain whole and camel/underscore/hyphen subtokens. | 03-01, 03-05 | COVERED |
| D-49 | BM25 defaults are `k1=1.2` and `b=0.75`, configurable. | 03-01, 03-03 | COVERED |
| D-50 | IDF is global; filters only constrain candidates. | 03-01, 03-05 | COVERED |
| D-51 | Equal RRF scores use best source rank, document ID, chunk index, then chunk ID. | 03-01, 03-05 | COVERED |
| D-52 | Full precision ranks internally; diagnostics round only at serialization. | 03-01, 03-05 | COVERED |
| D-53 | Same normalized query/filter/generation/configuration returns identical ordered IDs. | 03-01, 03-05 | COVERED |
| D-54 | Empty questions are rejected before retrieval/provider work. | 03-03, 03-04 | COVERED |
| D-55 | Query input is limited to configurable 8 KiB UTF-8. | 03-03, 03-04 | COVERED |
| D-56 | Filter values normalize/dedupe before 100-ID and 16-type limits. | 03-03, 03-04 | COVERED |
| D-57 | Outer whitespace is trimmed while generation keeps original semantics and retrieval gets normalized views. | 03-03, 03-04, 03-05 | COVERED |

## Accepted deferred scope

`DEBT-RAG-01` through `DEBT-RAG-06` in [deferred-items.md](deferred-items.md) remain out of executable tasks. The plans preserve only the typed seams, validation boundaries, startup safeguards, endpoint seam, and local deterministic test infrastructure needed for a trustworthy valid-query path. In particular, the five-plan split does not promote degraded retrieval, provider fallback/retry, citation repair, dynamic restart/re-ingestion recovery, graph failure handling, or exhaustive invalid-input/filter coverage (`DEBT-RAG-05`).
