# v1 Requirements

## Architecture & Gateway
- [ ] **ARCH-01**: Define a stable gRPC contract between the Go API gateway and Rust RAG engine.
- [ ] **ARCH-02**: Build a Go API gateway with document upload, RAG query, graph query, session handling, and metadata persistence.
- [ ] **ARCH-03**: Provide a local development path with `go run`, `cargo run`, and Docker Compose for PostgreSQL/Jaeger and optional local LLM fallback.

## RAG Engine Core
- [ ] **RAG-01**: Build a Rust RAG engine with gRPC server, async runtime, tracing, and service boundaries.
- [ ] **RAG-02**: Implement hybrid retrieval that combines dense vector search, local lexical/BM25 retrieval, metadata filtering, and deduplication.
- [ ] **RAG-03**: Support degraded mode when graph extraction or one retrieval path fails, returning a useful vector/BM25-backed answer.

## Data & Graph Processing
- [ ] **DATA-01**: Implement document ingestion for Markdown, plain text, JSON, and other lightweight text-like sources.
- [ ] **DATA-02**: Implement custom structure-aware recursive chunking with at least fixed-size and structure-aware strategies.
- [ ] **DATA-03**: Persist chunks and metadata in LanceDB as the local-first vector/graph store.
- [ ] **DATA-04**: Extract entities and relationships during ingestion and persist them as graph nodes/edges in LanceDB.
- [ ] **DATA-05**: Query graph context with `lance-graph`/Cypher-style pattern matching and compile it into RAG prompt context.

## Orchestration & State
- [ ] **ORCH-01**: Implement a lightweight Rust state machine for the fixed RAG path (query -> reformulate -> retrieve -> graph -> prompt -> answer -> complete/failed).
- [ ] **ORCH-02**: Emit client-facing workflow events (node started/completed/failed, answer chunks, final answer, completed).
- [ ] **ORCH-03**: Add cancellation, timeouts, and retry/fallback behavior for node execution.
- [ ] **ORCH-04**: Add lightweight checkpoints or snapshots for workflow state during development and debugging.

## Observability & Evaluation
- [ ] **OBS-01**: Add OpenTelemetry-compatible tracing across Go, gRPC, Rust nodes, retrieval, graph queries, and LLM calls.
- [ ] **OBS-02**: Add an offline evaluation script using a fixed test set and LLM-as-judge or similar scoring for retrieval/answer quality.
- [ ] **OBS-03**: Provide a README/design narrative that explains the architecture, alternatives, choices, and how to run/evaluate.

## Traceability
(Updated by ROADMAP.md)

## v2 Requirements (Deferred)
- [ ] Heavy PDF-first ingestion.
- [ ] Full checkpoint database (PostgreSQL-backed snapshots beyond MVP).
- [ ] Dynamic node loading, plugin marketplace.
- [ ] Distributed workflow execution.

## Out of Scope
- Full LangGraph, Dify, or generic workflow-engine clone — limits scope to fixed RAG path needed for this project.
- Visual workflow editor, full workflow DSL — pulls project away from core systems/RAG story.
- Product-facing web UI — CLI/API and minimal response streaming are sufficient for MVP.
