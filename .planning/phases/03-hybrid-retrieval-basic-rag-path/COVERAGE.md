# API Coverage — OpenRouter

> Current MVP coverage is explicit. Every capability outside the accepted Phase 03 happy path has an explicit opt-out with a reason and a debt-ledger pointer.

Phase 03 integrates the existing OpenRouter embeddings surface for query-vector creation and the structured, unary chat-completion surface for one grounded answer when both vector and BM25 retrieval paths succeed over a completed corpus. The provider-neutral Rust `Generator` seam remains integrated so another adapter can be added without changing retrieval or prompt contracts. RAG-03 is explicitly opted out of this phase; its future degraded, citation-repair, graph-unavailability, and lifecycle targets remain in `deferred-items.md`.

## Five-plan ownership matrix

| Plan | Automated evidence owner | Boundary kept out of MVP coverage |
|---|---|---|
| 03-01 | Unicode analyzer, BM25 snapshot statistics, filtered dense retrieval, deterministic RRF fusion, and NoOp reranking | Provider calls and generation |
| 03-02 | Provider-neutral evidence assembly plus strict OpenRouter supported-parameters and structured-output contract tests | Live credentials and alternate providers |
| 03-03 | Additive QueryRAG gRPC contract, initial BM25 build/readiness safeguard, and Rust service coordination | Restart/re-ingestion recovery |
| 03-04 | Go `/rag/query` boundary mapping and endpoint-injectable query embeddings | PostgreSQL-backed gateway startup |
| 03-05 | `TestRAGQueryCrossRuntime` with seeded LanceDB, deterministic embedding/metadata/chat endpoints, real direct Rust process, generated-gRPC Ping, and bounded cleanup | Degraded/fallback/repair/retry/graph behavior |

The ownership is intentionally vertical: each row names the one current plan that proves that acceptance surface, while the final row closes the real local Go-to-Rust happy path without promoting deferred behavior.

| capability | decision | reason |
|---|---|---|
| Query embeddings via `POST /api/v1/embeddings` | INTEGRATE | Dense retrieval needs the configured embedding model and the existing Rust OpenRouter client already owns this boundary. |
| Configurable chat model selection | INTEGRATE | The generation model is a runtime configuration value and must be checked for structured-output support before a live smoke. |
| Unary chat completion via `POST /api/v1/chat/completions` | INTEGRATE | The Phase 03 answer path makes one bounded provider call for each valid query. |
| Separate system policy, question, and evidence messages | INTEGRATE | The prompt contract keeps corpus text as untrusted data and preserves the instruction boundary. |
| Strict JSON Schema response format | INTEGRATE | The provider must return answer text, cited evidence IDs, answer basis, and notices in the closed Rust contract. |
| Structured-output model capability check | INTEGRATE | The selected model must advertise the requested structured-output parameter before provider-backed verification. |
| Deterministic sampling controls (`temperature=0`, `top_p=1`) | INTEGRATE | These are the locked Phase 03 generation defaults and remain configurable. |
| Bounded output control (`max_completion_tokens=2048` by default) | INTEGRATE | The answer budget is reserved before evidence packing and is included in the generation contract. |
| Provider usage and model metadata | INTEGRATE | Token usage, model identity, and retrieval snapshot metadata are retained for the structured response and diagnostics. |
| Request timeout and cancellation propagation | INTEGRATE | The single generation future is bounded and cancellation-safe through Tokio and reqwest. |
| Non-success provider response classification | INTEGRATE | Transport, HTTP, timeout, and structured-output failures become typed provider errors with correlation/session identity. |
| Provider-neutral `Generator` adapter seam | INTEGRATE | OpenRouter is the default implementation while service semantics remain independent of the vendor. |
| Streaming chat completions | OPT-OUT | Phase 03 exposes unary `POST /rag/query`; streaming workflow events are owned by Phase 05. |
| Tools and function calling | OPT-OUT | The Phase 03 model input is limited to the question and explicitly framed evidence; no model tools are exposed. |
| Alternate provider runtime adapters | OPT-OUT | The provider-neutral trait is integrated, but alternate concrete providers are outside this phase and have no selected contract or credentials. |
| Provider retry and alternate-provider fallback | OPT-OUT | The accepted MVP path makes one generation attempt; retry and fallback orchestration is deferred to Phase 05 and the recorded debt ledger. |
| Degraded retrieval and model-only fallback | OPT-OUT | RAG-03 is not a Phase 03 acceptance requirement; D-11 through D-16 remain DEBT-RAG-01 and graph unavailability remains DEBT-RAG-06 for future hardening. |
| Citation repair and transparent downgrade | OPT-OUT | Valid structured markers are checked on the MVP path; D-24 repair/removal/downgrade remains DEBT-RAG-03. |
| Re-ingestion/restart atomic visibility and recovery | OPT-OUT | Initial BM25 build/readiness is integrated as a trust safeguard; D-41 through D-43 lifecycle behavior remains DEBT-RAG-04. |

## Verification contract

- Plan 03-01 proves the Unicode analyzer, global BM25 statistics, typed filters, dense/BM25 fusion, and NoOp reranker through the named retrieval tests `bm25_full_unicode_analyzer_and_global_idf`, `retrieval_filter_fusion_and_determinism`, and `noop_reranker_preserves_candidates`.
- Plan 03-02 Task 1 also asserts that suspicious evidence remains marked and unexecuted and that a valid corpus conflict returns mixed basis with an explicit disclosure while citing only supplied evidence. Task 2 performs the supported-parameters preflight and strict one-call adapter contract against a deterministic local metadata/chat mock. The ignored command `cargo test --manifest-path engine/Cargo.toml --locked openrouter_structured_output_smoke -- --ignored` is the optional manual live-provider check when `OPENROUTER_API_KEY` is available; it is not required for the provider-independent path.
- Plan 03-03 carries the additive QueryRAG contract into both generated runtimes, verifies the exact `supported_parameters` metadata key, proves service-level QueryRAG behavior plus safe-default compatibility for all existing config_startup base/overlay fixtures, and proves the initial BM25 build/readiness safeguard before serving; it does not claim restart recovery.
- Plan 03-04 Task 2 proves that the existing Rust embedding client can target an explicit endpoint override while retaining its production OpenRouter default, timeout, retry, concurrency, and dimension checks.
- Plan 03-05 Task 1 runs `TestRAGQueryCrossRuntime` through the real Go route and Rust process. One localhost server deterministically handles query embeddings, model `supported_parameters` metadata, and one strict chat completion; a reusable seed binary creates an isolated temporary completed LanceDB corpus, the engine and seeder are built once and launched as resolved direct binaries from the repository root with scrubbed application environments, the serving log is followed by a bounded generated-gRPC `Ping` probe against the exact loopback endpoint, and cleanup reaps the process tree before a rename/remove check proves the LanceDB path is released.
- Plan 03-05 Task 2 maintains this matrix and keeps automated proof limited to the accepted valid-query path: both retrieval paths succeeding, grounded valid citations, the mock completion's usage and model metadata, the Rust retrieval snapshot, strict request validation, timeout/cancellation seams, the initial BM25 build/readiness safeguard, and no PostgreSQL or live credentials.

## RAG-03 deferred boundary

RAG-03 is **OPT-OUT / DEFERRED** for Phase 03 and is mapped to the Phase 06 hardening target. The current plans may preserve typed fields, provider errors, valid-marker validation, and initial-build safeguards required to make the happy path trustworthy, but they do not implement or accept the future failure branches.

- `DEBT-RAG-01` — **OPT-OUT:** D-11 through D-16 degraded retrieval and model-only behavior have no Phase 03 failure-path gate; see `deferred-items.md`.
- `DEBT-RAG-03` — **OPT-OUT:** D-24 citation repair, removal, and transparent downgrade are deferred; Phase 03 accepts valid markers only; see `deferred-items.md`.
- `DEBT-RAG-04` — **OPT-OUT:** D-41 through D-43 re-ingestion/restart visibility and recovery are deferred; only the initial build/readiness safeguard is in scope; see `deferred-items.md`.
- `DEBT-RAG-05` — **OPT-OUT:** Exhaustive invalid-input and filter edge coverage is deferred; basic happy-path guards remain; see `deferred-items.md`.
- `DEBT-RAG-06` — **OPT-OUT:** Graph-extraction unavailability in the eventual RAG-03 contract is deferred; Phase 03 uses source chunks only; see `deferred-items.md`.

Each debt item retains its rationale, trigger, target, and future acceptance criteria in [deferred-items.md](deferred-items.md).

## Deferred boundary coverage

- **DEBT-RAG-05**
  - **Deferred boundary:** Automated MVP proof covers valid query/filter inputs and only the basic guards needed to reach the happy path; exhaustive malformed, oversized, unmatched, and combinatorial input behavior is not claimed.
  - **Rationale:** The first slice must make the hybrid retrieval-to-generation path runnable before expanding the public negative-input matrix.
  - **Trigger:** External callers, fuzzing/property testing, or a requirement for complete public API contract coverage.
  - **Target:** Phase 06 hardening/evaluation.
  - **Future acceptance criteria:** Empty/oversized queries, malformed IDs, unsupported content types, and filter limits are rejected before retrieval/provider work with stable HTTP 400 and gRPC `InvalidArgument` behavior.

The capability subtraction is intentional: Phase 03 exposes only the unary, one-shot structured happy path. Streaming, tools/function calling, alternate providers, retries/fallback, RAG-03 degraded behavior, citation repair, and dynamic re-ingestion/restart recovery remain explicit OPT-OUT/debt decisions and are not hidden inside the tracer.

Dynamic re-ingestion/restart recovery remains deferred as `DEBT-RAG-04`; it is not part of the initial-readiness proof.
