# Shrag Implementation Plan

Shrag is an end-to-end, high-performance, systems-oriented Retrieval-Augmented Generation (RAG) and GraphRAG platform. It features a split-service architecture: a user-facing API gateway in Go (control plane) and a high-performance RAG and document processing engine in Rust (data plane) communicating via gRPC. 

The project emphasizes systems programming, custom core data-plane mechanisms (chunking, hybrid retrieval, graph traversal), and production-grade observability (OpenTelemetry tracing, LLM-as-a-judge evaluation).

---

## User Review Required

Please review the architectural choices and proposed file structure. The system is designed to run locally with hybrid execution (Go and Rust processes running natively, with supporting services like PostgreSQL and Jaeger run via Docker Compose).

---

## Open Questions

> [!NOTE]
> We have successfully aligned on the core parameters (Go/Rust split, gRPC, LanceDB + lance-graph, hybrid local development, OpenTelemetry, general heterogeneous data sources). There are currently no critical open questions blocking the initiation of this plan.

---

## Proposed Changes

### 1. Protobuf Definitions (gRPC Contract)

#### [NEW] [shrag.proto](file:///c:/Users/user3/Shrag/proto/shrag.proto)
Defines the gRPC interface between the Go API Gateway and the Rust RAG Engine:
- `IngestDocument(Stream IngestRequest) returns (IngestResponse)`
- `QueryRAG(QueryRequest) returns (QueryResponse)`
- `QueryGraph(GraphRequest) returns (GraphResponse)`

---

### 2. Rust RAG Engine (`engine`)

#### [NEW] [Cargo.toml](file:///c:/Users/user3/Shrag/engine/Cargo.toml)
Configures dependencies for the Rust service:
- `tonic`/`prost` for gRPC.
- `lancedb` for vector storage.
- `lance-graph` for native LanceDB GraphRAG entity-relationship representation and Cypher querying.
- `tokio` for async runtime.
- `opentelemetry` & `tracing` for instrumentation.
- `reqwest`/`serde` for LLM client integration (OpenAI/Anthropic/Gemini).

#### [NEW] [main.rs](file:///c:/Users/user3/Shrag/engine/src/main.rs)
Bootstraps the gRPC server, registers handlers, and initializes the OpenTelemetry tracer.

#### [NEW] [chunker.rs](file:///c:/Users/user3/Shrag/engine/src/chunker.rs)
Implements the custom structure-aware recursive chunker. Supports Markdown, JSON, and plain text.

#### [NEW] [store.rs](file:///c:/Users/user3/Shrag/engine/src/store.rs)
Manages connection to LanceDB and abstract vector search queries.

#### [NEW] [graph.rs](file:///c:/Users/user3/Shrag/engine/src/graph.rs)
Extracts entities and relationships using LLM prompts, maps them as a property graph, and queries them using Cypher queries via `lance-graph` stored directly in LanceDB.

#### [NEW] [retriever.rs](file:///c:/Users/user3/Shrag/engine/src/retriever.rs)
Implements the hybrid retriever: combines LanceDB vector search results with a local lexical BM25 index and applies optional metadata filters.

#### [NEW] [orchestrator.rs](file:///c:/Users/user3/Shrag/engine/src/orchestrator.rs)
Implements the RAG state machine: query reformulation, GraphRAG sub-graph extraction, prompt assembly, and streaming generation.

---

### 3. Go API Gateway (`gateway`)

#### [NEW] [go.mod](file:///c:/Users/user3/Shrag/gateway/go.mod)
Defines Go dependencies: `gin` or standard library for HTTP server, `pgx` for PostgreSQL, `google.golang.org/grpc`, `go.opentelemetry.io`.

#### [NEW] [main.go](file:///c:/Users/user3/Shrag/gateway/main.go)
Initializes Go HTTP server, session/auth middleware, and handles routing. Exposes endpoints for:
- Document upload (`POST /v1/documents`)
- RAG Query (`POST /v1/query`)
- Graph Query (`GET /v1/graph`)

#### [NEW] [db.go](file:///c:/Users/user3/Shrag/gateway/db.go)
Handles PostgreSQL database connection, user sessions, and document metadata persistence.

---

### 4. Infrastructure & Deployment

#### [NEW] [docker-compose.yml](file:///c:/Users/user3/Shrag/docker-compose.yml)
Defines services for:
- PostgreSQL (Go metadata database).
- Jaeger (OpenTelemetry tracing backend).
- Local LLM fallback (optional, e.g., Ollama) or configures API keys for OpenAI/Gemini/Anthropic.

---

### 5. Evaluation Script

#### [NEW] [eval.py](file:///c:/Users/user3/Shrag/eval/eval.py)
A Python/Rust script to run test queries through the system, compute metrics (Retrieval Recall, Precision, Groundedness, Faithfulness) using an LLM-as-a-judge, and print a final benchmark report.

---

## Verification Plan

### Automated Tests
- Run unit tests for custom Rust chunker: `cargo test -p engine chunker`
- Run integration tests for Go/Rust gRPC flow.
- Run the offline evaluation script: `python eval/eval.py`

### Manual Verification
- Start supporting containers: `docker compose up -d`
- Run Go Gateway: `go run gateway/main.go`
- Run Rust Engine: `cargo run --manifest-path engine/Cargo.toml`
- Upload a test corpus (e.g. mix of PDFs and Markdown files).
- Query the system and verify traces in Jaeger (`http://localhost:16686`).
