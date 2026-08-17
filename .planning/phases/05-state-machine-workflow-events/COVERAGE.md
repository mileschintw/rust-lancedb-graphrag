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

## Phase 05 Gap-Closure Plan Index and API Scope

The revised executable gap-closure plans (05-08 through 05-24) modify only existing internal components, workflow engines, serialization formats, and test fixtures:

- **05-08:** Production Five-Node State Machine Query Reachability
- **05-09:** Workflow Timeouts and Stream Disconnect Cancellation
- **05-10:** Event Delivery Reliability, Retry Classification, and Checkpoint Digests
- **05-11:** Gateway SSE Streaming and Checkpoint Persistence Verification
- **05-12:** Additive Traceability Errata and Multi-Source Coverage
- **05-13:** OpenRouter Model Metadata Cache and Retry Classification
- **05-14:** Explicit NodeKind Exhaustive Dispatch
- **05-15:** Test Double and Fake Port Isolation
- **05-16:** Production BM25 O(1) Arc Snapshots and Retrieval Provenance
- **05-17:** Additive Wire Schema and Generated Protobuf Bindings (modifies only the internal protobuf contract; adds no external API/vendor capability)
- **05-18:** Library and Binary Target Split with BM25 Fixture Migration
- **05-19:** Terminal Error and Notice Serialization
- **05-20:** Preflight Bootstrap Timing and Wall-Clock Assertions
- **05-21:** Typed Retrieval and Fusion Provenance
- **05-22:** Retire Inline Remainder and Prove Five-Node Production Reachability
- **05-23:** Generated Wire Contract Repair and Protobuf Literal Compilation
- **05-24:** Two-Pass Multi-Variant RRF Fusion (including executable tasks 05-24-01 and 05-24-02)

Plans 05-08 through 05-24 add no vendor endpoint, SDK, credential, third-party service, or external API capability; the protobuf additions are source-owned and generated through the repository's existing Buf configuration.
