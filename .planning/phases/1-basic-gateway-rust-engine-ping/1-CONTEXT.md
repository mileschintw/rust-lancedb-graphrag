# Phase 1: Basic Gateway & Rust Engine Ping

## Domain
Establish the foundational split-service architecture (Go control plane + Rust data plane) and ensure they can communicate via gRPC.

## Locked Requirements (from PROJECT.md / REQUIREMENTS.md)
- Define a stable gRPC contract between Go and Rust.
- Build a Go API gateway handling HTTP and metadata persistence.
- Build a Rust RAG engine with a gRPC server and async runtime.
- Provide local development path (Docker Compose, `go run`, `cargo run`).

## Implementation Decisions

### Repository Structure
- **Decision:** Monorepo with top-level directories: `/gateway` (Go API), `/engine` (Rust RAG engine), and `/proto` (Shared Protobuf definitions).
- **Rationale:** Keeps service code cleanly separated while easily sharing the gRPC contract.

### Service Boundaries & Communication
- **Decision:** Use **gRPC** over a structured Protobuf schema for all inter-service communication.
- **Rationale:** Ensures strict typing and performance for the data-plane connection.

### Core Frameworks
- **Decision:** Go API Gateway will use `go-chi/chi` for routing. Rust RAG Engine will use `tonic` for gRPC and `tokio` for async.
- **Rationale:** Maximizes systems engineering signaling. Avoids black-box frameworks while leveraging `chi`'s excellent middleware support.

### Build & Dev Environment
- **Decision:** Hybrid local-first (`go run` / `cargo run`) backed by Docker Compose for PostgreSQL (metadata) and Jaeger (traces).
- **Scope for Phase 1:** Only establish and verify the DB/Jaeger connections. Database migration tooling is deferred.
- **Rationale:** Fast development loop while maintaining a production-like dependencies setup. Keeps Phase 1 focused strictly on health checks and pinging.

## Code Context
- **Reusable Assets:** Standard Protobuf definitions for the Ping/Health service.
- **Patterns:** Go dependency injection for DB access; Rust `tokio` runtime initialization and `tonic` server setup.

## Canonical References
- `.discussion/final_implementation_decision_document.md`
- `.discussion/lightweight_state_machine_plan.md`

## Deferred Ideas
- Document ingestion, chunking, and LanceDB storage (Deferred to Phase 2).
- Hybrid Retrieval and RAG logic (Deferred to Phase 3).
- OpenTelemetry tracing (Deferred to Phase 6, though basic scaffolding can start now if convenient).
