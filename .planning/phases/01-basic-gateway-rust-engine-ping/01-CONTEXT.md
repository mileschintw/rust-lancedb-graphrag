# Phase 1: Basic Gateway & Rust Engine Ping - Context

**Gathered:** 2026-06-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish the foundational split-service architecture (Go control plane + Rust data plane) and ensure they can communicate via gRPC.

</domain>

<decisions>
## Implementation Decisions

### Protobuf Compilation Workflow
- **D-01:** Use the modern `buf` CLI to compile and generate Protobuf code. This simplifies configurations via `buf.gen.yaml` and handles plugins cleanly.
- **D-02:** Generate the compiled code in-place inside each service (e.g., `/gateway/proto` and `/engine/src/proto`) for direct imports and clean directory dependencies.

### Ping Protocol & HTTP Health Check Format
- **D-03:** The Go gateway's `/health` endpoint will return structured JSON indicating both Go and Rust status, plus roundtrip gRPC ping latency (e.g., `{"status":"ok","engine":{"status":"ok","latency_ms":5}}`).
- **D-04:** If the Rust engine is unreachable via gRPC, the Go gateway will return an HTTP 503 Service Unavailable status code.

### Database Driver & Query Style
- **D-05:** Use `sqlc` to compile raw SQL queries into type-safe Go code.
- **D-06:** Use `pgx/v5` as the underlying driver and connection pool for PostgreSQL.
- **D-07:** Use `atlas` as the declarative schema management and migration tool.

### Logging Libraries
- **D-08:** Use `uber-go/zap` in the Go gateway for structured, high-performance logging.
- **D-09:** Use `tracing` and `tracing-subscriber` in the Rust engine to enable high-performance instrumentation and prepare for OpenTelemetry.

### the agent's Discretion
- Code structural patterns, directory names (e.g., source file organization), and standard libraries (like `go-chi/chi` for routing in Go and `tonic`/`tokio` in Rust) are left to the agent's best engineering practices.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Decisions
- [final_implementation_decision_document.md](file:///d:/Repos/lancet/.discussion/final_implementation_decision_document.md) — Main architecture split, boundaries, and tech stack choices.
- [lightweight_state_machine_plan.md](file:///d:/Repos/lancet/.discussion/lightweight_state_machine_plan.md) — Reference for future orchestration states and integration patterns.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — Greenfield monorepo project setup.

### Established Patterns
- None — Greenfield monorepo project setup. Patterns will be established in this phase.

### Integration Points
- Establish the `/gateway` (Go API), `/engine` (Rust RAG engine), and `/proto` (Shared Protobuf definitions) directories as the primary code namespaces.

</code_context>

<specifics>
## Specific Ideas

- Database migrations and schema files will be managed via `atlas` with declarative schemas.
- Go database interactions will utilize `sqlc` for clean type safety and fast development loop without full ORM overhead.

</specifics>

<deferred>
## Deferred Ideas

- Ingestion, chunking, and LanceDB storage (Deferred to Phase 2).
- Hybrid Retrieval and RAG logic (Deferred to Phase 3).
- OpenTelemetry tracing integration (Deferred to Phase 6, basic scaffolding in Go/Rust can be initialized now).

</deferred>

---

*Phase: 01-Basic Gateway & Rust Engine Ping*
*Context gathered: 2026-06-19*
