# API Coverage — Phase 6 (Observability, Evaluation & Polish)

No external API integration: Phase 6 restructures in-repo Rust modules and Go packages, edits the
project's own protobuf contract, and changes engine-internal RAG behavior — the only external service
(OpenRouter) is pre-existing and explicitly untouched by this phase (06-AI-SPEC.md §4.4).

## Why the detector fired

The deterministic scan matched `wire` + `grpc` in plan `06-08`'s tracer task
(`<action>Wire one path from the gRPC entry point to the serialized response.`). That gRPC surface is
**this project's own** `LancetService`, defined in `proto/lancet/v1/lancet.proto` and implemented in
`engine/src/service.rs` — the gateway is its only client and both live in this repository. It is an
internal service boundary, not a third-party API being integrated.

Re-read of the phase scope confirms the same for every other candidate signal:

| Candidate surface | External? | Note |
|---|---|---|
| `lancet.v1.LancetService` (gRPC) | no | Defined and implemented in this repo; the contract change is D-74's own additive edit |
| `/rag/query` (HTTP/SSE) | no | This project's own endpoint, served by `gateway/main.go` |
| OpenRouter chat + embeddings | no change | Pre-existing integration. Phase 6 adds no call, changes no endpoint, and no model pin. D-14 forbids a second provider call. D-19 still freezes the structured-output *object shape* (properties and required keys). Plan 06-13 admits the already-published proto value `model_only` as one extra `answer_basis` enum member on that same chat schema (D-10); that is not a new external API. |
| `buf.build` remote plugins | no | A build-time code generator, not a runtime API integration. Pinned by exact version in `buf.gen.yaml`. Phase 6.07 treats network-or-`~/.cache/buf` as an execution prerequisite, not a product API surface. |
| OpenTelemetry / OTLP collectors | out of scope | Phase 6.2 (D-36/D-38/D-43). `gateway/internal/telemetry` ships as an OTel-free stub in plan 06-04 |

Fabricating a coverage matrix row for a capability that does not exist would be worse than this
declaration: it would record decisions about a surface this phase never touches.

## Related enumerations that do exist in this phase

Not API-coverage matrices, but recorded here so a reviewer can find them:

- **Notice-code vocabulary** — the complete published enum, decided at plan `06-07`'s
  `checkpoint:decision` and enumerated in that plan's "Artifacts this phase produces" section. One tag
  is deliberately reserved and unpublished because nothing can emit it.
- **Bad-input matrix** — the enumerated rejection surface with its dispositions, built in plan `06-12`
  and reproduced verbatim in `06-12-SUMMARY.md` for Phase 6.4 to publish.
