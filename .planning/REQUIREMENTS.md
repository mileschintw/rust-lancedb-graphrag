# v1 Requirements

## Architecture & Gateway
- [ ] **ARCH-01**: Define a stable gRPC contract between the Go API gateway and Rust RAG engine.
- [ ] **ARCH-02**: Build a Go API gateway with document upload, RAG query, graph query, session handling, and metadata persistence.
- [ ] **ARCH-03**: Provide a local development path with `go run`, `cargo run`, and Docker Compose for PostgreSQL/Jaeger and optional local LLM fallback.

## RAG Engine Core
- [ ] **RAG-01**: Build a Rust RAG engine with gRPC server, async runtime, tracing, and service boundaries.
- [ ] **RAG-02**: Implement hybrid retrieval that combines dense vector search, local lexical/BM25 retrieval, metadata filtering, and deduplication.
- [ ] **RAG-03**: Support degraded mode when graph extraction or one retrieval path fails, returning a useful vector/BM25-backed answer.
- [ ] **RAG-04**: Define a pluggable async `Reranker` trait in Rust; implement a pass-through `NoOpReranker` as the v1 default, allowing external/local rerankers to be dropped in later.
- [ ] **RAG-05**: Define a `ContextAssemblyStrategy` enum/trait in the Rust engine supporting both `PrecomputedSemantics` and `SourceChunks` retrieval, defaulting to `SourceChunks` (Port for 999.5).
- [ ] **RAG-06**: Implement an async background worker task structure (e.g. Tokio channel reader) in the Rust engine that defaults to NoOp execution (Port for 999.4).

## Data & Graph Processing
- [ ] **DATA-01**: Implement document ingestion for Markdown, plain text, JSON, and other lightweight text-like sources.
- [ ] **DATA-02**: Implement custom structure-aware recursive chunking with at least fixed-size and structure-aware strategies.
- [ ] **DATA-03**: Persist chunks and metadata in LanceDB as the local-first vector/graph store.
- [ ] **DATA-04**: Extract entities and relationships during ingestion and persist them as graph nodes/edges in LanceDB.
- [ ] **DATA-05**: Query graph context with `lance-graph`/Cypher-style pattern matching and compile it into RAG prompt context.
- [ ] **DATA-06**: Prepare database schemas for hierarchical global summarization by adding an optional `community_ids` array on nodes and registering an empty placeholder `communities` table.
- [ ] **DATA-07**: Register nullable `summary` (Text) and `summary_vector` (Float Array) columns, along with an `unsummarized_refs` list column on the `nodes` table (Port for 999.4).
- [ ] **DATA-08**: Define separate `nodes` and `edges` tables in LanceDB. The `edges` table must include nullable `summary` (Text) and `summary_vector` (Float Array) columns (Port for 999.5).
- [ ] **DATA-09**: Define an async `EntityResolver` trait in Rust for ingestion, implementing a pass-through `ExactMatchResolver` as the default (Port for 999.6).

## Orchestration & State
- [ ] **ORCH-01**: Implement a lightweight Rust state machine for the fixed RAG path (query -> reformulate -> retrieve -> graph -> prompt -> answer -> complete/failed).
- [ ] **ORCH-02**: Emit client-facing workflow events (node started/completed/failed, answer chunks, final answer, completed).
- [ ] **ORCH-03**: Add cancellation, timeouts, and retry/fallback behavior for node execution.
- [ ] **ORCH-04**: Add lightweight checkpoints or snapshots for workflow state during development and debugging.
- [ ] **ORCH-05**: Include a dedicated `reformulate` stage in the Rust state machine, defaulting to a pass-through node in v1, leaving a clean slot for future expansion.

## Observability & Evaluation
- [ ] **OBS-01**: Add OpenTelemetry-compatible tracing across Go, gRPC, Rust nodes, retrieval, graph queries, and LLM calls.
- [ ] **OBS-02**: Add an offline evaluation script using a fixed test set and LLM-as-judge or similar scoring for retrieval/answer quality.
- [ ] **OBS-03**: Provide a README/design narrative that explains the architecture, alternatives, choices, and how to run/evaluate.
- [ ] **OBS-04**: Add a placeholder metric (e.g. `global_faithfulness` or `global_coverage`) returning a simulated score or skipped flag in the offline evaluation script framework.

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
