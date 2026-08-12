# Phase 05 API Coverage

No external API integration: Phase 05 reuses existing provider and local-service
boundaries and adds no new vendor endpoint, SDK, credential, or third-party
service capability.

## Reviewed Capability Surface

The following surfaces were reviewed even though the gate is satisfied by the
reasoned no-external-API declaration:

- Existing OpenRouter chat/embedding APIs: reused through the Rust `Generator`
  port in 05-03; no new provider endpoint, SDK, credential, or capability.
- `LancetService.QueryRAG`: internal Go-to-Rust gRPC contract changed to the
  locked server-streaming event contract in 05-01.
- `/rag/query`: internal HTTP route changed to SSE-only forwarding with
  first-frame prefetch in 05-01.
- PostgreSQL / Atlas / sqlc: existing local Docker service and toolchain receive
  the Go-owned checkpoint table and detached insert path in 05-05.
- `QueryGraph` RPC: existing internal API explicitly left unchanged per D-10 in
  05-02; it is a scope fence, not a new external capability.
