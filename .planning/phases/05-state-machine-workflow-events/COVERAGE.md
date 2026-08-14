# Phase 05 API Coverage

No external API integration: Phase 05 reuses existing provider and local-service
boundaries and adds no new vendor endpoint, SDK, credential, or third-party
service capability.

## Reviewed Capability Surface

The following surfaces were reviewed even though the gate is satisfied by the
reasoned no-external-API declaration:

- Existing OpenRouter chat/embedding APIs: reused through the Rust `Generator`
  port in 05-03; no new provider endpoint, SDK, credential, or capability.
- `LancetService.QueryRAG`: the Rust-only server-streaming transition and
  codegen precondition land in 05-01; the coordinated Rust/Go generated
  contract is completed in 05-06.
- `/rag/query`: internal HTTP route changes to SSE-only forwarding with
  first-frame prefetch in 05-06. 05-01 owns only the Rust transition/codegen
  precondition and does not own gateway SSE.
- PostgreSQL / Atlas / sqlc: existing local Docker service and toolchain receive
  the Go-owned checkpoint table and detached insert path in 05-05.
- `QueryGraph` RPC: existing internal API explicitly left unchanged per D-10 in
  05-02; it is a scope fence, not a new external capability.

## Continuation coverage note (2026-08-13)

Plans 05-17 through 05-21 modify only the existing internal protobuf/runtime contract, Rust workflow seams, Go SSE mapping, and retrieval fusion types. They add no vendor endpoint, SDK, credential, third-party service, or external API capability; the protobuf additions are source-owned and generated through the repository's existing Buf configuration.
