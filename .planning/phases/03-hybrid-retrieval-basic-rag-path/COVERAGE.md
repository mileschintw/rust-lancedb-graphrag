# API Coverage — OpenRouter

> Full coverage by default. Every capability outside the Phase 03 integrated surface has an explicit opt-out with a reason.

Phase 03 integrates the existing OpenRouter embeddings surface for query-vector creation and the structured, unary chat-completion surface for one grounded answer. The provider-neutral Rust `Generator` seam remains integrated so another adapter can be added without changing retrieval or prompt contracts.

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

## Verification contract

- Plan 03-02 Task 2 performs the supported-parameters preflight and strict one-call adapter contract against a deterministic local metadata/chat mock. The ignored command `cargo test --manifest-path engine/Cargo.toml --locked openrouter_structured_output_smoke -- --ignored` is the optional manual live-provider check when `OPENROUTER_API_KEY` is available; it is not required for the provider-independent path.
- Plan 03-04 Task 2 proves that the existing Rust embedding client can target an explicit endpoint override while retaining its production OpenRouter default, timeout, retry, concurrency, and dimension checks.
- Plan 03-05 Task 1 runs `TestRAGQueryCrossRuntime` through the real Go route and Rust process. One localhost server deterministically handles query embeddings, model `supported_parameters` metadata, and one strict chat completion; a reusable seed binary creates an isolated temporary completed LanceDB corpus and cleanup waits for all handles and child processes.
- Plan 03-05 Task 2 maintains this matrix and keeps automated proof limited to the accepted valid-query path: grounded citations, usage/model metadata, strict input mapping, initial BM25 readiness, and no PostgreSQL or live credentials.

## Deferred boundary coverage

- **DEBT-RAG-05**
  - **Deferred boundary:** Automated MVP proof covers valid query/filter inputs and only the basic guards needed to reach the happy path; exhaustive malformed, oversized, unmatched, and combinatorial input behavior is not claimed.
  - **Rationale:** The first slice must make the hybrid retrieval-to-generation path runnable before expanding the public negative-input matrix.
  - **Trigger:** External callers, fuzzing/property testing, or a requirement for complete public API contract coverage.
  - **Target:** Phase 06 hardening/evaluation.
  - **Future acceptance criteria:** Empty/oversized queries, malformed IDs, unsupported content types, and filter limits are rejected before retrieval/provider work with stable HTTP 400 and gRPC `InvalidArgument` behavior.

The capability subtraction is intentional: Phase 03 exposes only the unary, one-shot structured path. Streaming, tools/function calling, alternate providers, retries/fallback, degraded retrieval, citation repair, and dynamic re-ingestion/restart recovery remain explicit OPT-OUT/debt decisions and are not hidden inside the tracer.
