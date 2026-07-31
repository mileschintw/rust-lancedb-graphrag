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

Plan 03-03 Task 1 performs a supported-parameters preflight for the configured model and requires the provider metadata to advertise structured-output support before a real request. The ignored command `cargo test --manifest-path engine/Cargo.toml --locked openrouter_structured_output_smoke -- --ignored` then verifies one real structured response when `OPENROUTER_API_KEY` is available. Normal tests use a local mock and do not depend on provider access.

The capability subtraction is intentional: Phase 03 exposes only the unary, one-shot structured path. Streaming, tools/function calling, alternate providers, and retries/fallback remain explicit OPT-OUT decisions and are not hidden inside the tracer.
