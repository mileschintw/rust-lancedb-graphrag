# v1 Requirements

## Architecture & Gateway

- [x] **ARCH-01**: Define a stable gRPC contract between the Go API gateway and Rust RAG engine.
- [x] **ARCH-02**: Build a Go API gateway with document upload, RAG query, graph query, session handling, and metadata persistence.
- [x] **ARCH-03**: Provide a local development path with `go run`, `cargo run`, and Docker Compose for PostgreSQL/Jaeger and optional local LLM fallback.

## RAG Engine Core

- [x] **RAG-01**: Build a Rust RAG engine with gRPC server, async runtime, tracing, and service boundaries.
- [x] **RAG-02**: Implement hybrid retrieval that combines dense vector search, local lexical/BM25 retrieval, metadata filtering, and deduplication. **SATISFIED (MVP, see DEBT-P3-*)**
- [x] **RAG-03**: **Future hardening target — deferred from Phase 03 to Phase 06.** Support degraded mode when graph extraction or one retrieval path fails, returning a useful vector/BM25-backed answer. See DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-04, DEBT-RAG-05, and DEBT-RAG-06 for the preserved target contracts.
- [x] **RAG-04**: Define a pluggable async `Reranker` trait in Rust; implement a pass-through `NoOpReranker` as the v1 default, allowing external/local rerankers to be dropped in later (Port for 999.2).
- [x] **RAG-05**: Define a `ContextAssemblyStrategy` enum/trait in the Rust engine supporting both `PrecomputedSemantics` and `SourceChunks` retrieval, defaulting to `SourceChunks` (Port for 999.5). **SATISFIED — Phase 04.1.**
- [ ] **RAG-06**: Implement an async background worker task structure (e.g. Tokio channel reader) in the Rust engine that defaults to NoOp execution (Port for 999.4).

## Data & Graph Processing

- [ ] **DATA-01**: Implement document ingestion for Markdown, plain text, JSON, and other lightweight text-like sources.
- [ ] **DATA-02**: Implement custom structure-aware recursive chunking with at least fixed-size and structure-aware strategies.
- [ ] **DATA-03**: Persist chunks and metadata in LanceDB as the local-first vector/graph store.
- [x] **DATA-04**: Extract entities and relationships during ingestion and persist them as graph nodes/edges in LanceDB. **SATISFIED — Phase 04.1.**
- [x] **DATA-05**: Query graph context with `lance-graph`/Cypher-style pattern matching and compile it into RAG prompt context. **SATISFIED — Phase 04.1.**
- [ ] **DATA-06**: Prepare database schemas for hierarchical global summarization by adding an optional `community_ids` array on nodes and registering an empty placeholder `communities` table (Port for 999.1).
- [ ] **DATA-07**: Register nullable `summary` (Text) and `summary_vector` (Float Array) columns, along with an `unsummarized_refs` list column on the `nodes` table (Port for 999.4).
- [ ] **DATA-08**: Define separate `nodes` and `edges` tables in LanceDB. The `edges` table must include nullable `summary` (Text) and `summary_vector` (Float Array) columns (Port for 999.5).
- [ ] **DATA-09**: Define an async `EntityResolver` trait in Rust for ingestion, implementing a pass-through `ExactMatchResolver` as the default (Port for 999.6).

## Orchestration & State

- [x] **ORCH-01**: Implement a lightweight Rust state machine for the fixed RAG path (query -> reformulate -> retrieve -> graph -> prompt -> answer -> complete/failed). **SATISFIED — Phase 05.**
- [x] **ORCH-02**: Emit client-facing workflow events (node started/completed/failed, answer chunks, final answer, completed).
- [x] **ORCH-03**: Add cancellation, timeouts, and retry/fallback behavior for node execution.
- [x] **ORCH-04**: Add lightweight checkpoints or snapshots for workflow state during development and debugging.
- [x] **ORCH-05**: Include a dedicated `reformulate` stage in the Rust state machine, defaulting to a pass-through node in v1, leaving a clean slot for future expansion (Port for 999.3). **SATISFIED — Phase 05.**
- [x] **GATE-01**: Wire contract roundtrip and error framing for SSE streaming between the Rust engine and Go gateway (retrieval snapshot wire compatibility, post-open receive failure and EOF-without-terminal framing). **SATISFIED — Phase 05.** Added during Phase 05 planning as a quality-gate requirement not covered by ORCH-01..05; retroactively formalized here (see 05-12-TRACEABILITY-ERRATA.md §8).
- [x] **GATE-02**: Preserve workflow checkpoint ownership across pending backpressure, graceful shutdown, and PostgreSQL persistence (strict FIFO drain: primary -> overflow -> pending). **SATISFIED — Phase 05.** Added during Phase 05 planning as a quality-gate requirement not covered by ORCH-01..05; retroactively formalized here (see 05-12-TRACEABILITY-ERRATA.md §8).

## Observability & Evaluation

- [ ] **OBS-01**: Add OpenTelemetry-compatible tracing across Go, gRPC, Rust nodes, retrieval, graph queries, and LLM calls.
- [ ] **OBS-02**: Add an offline evaluation script using a fixed test set and LLM-as-judge or similar scoring for retrieval/answer quality.
- [ ] **OBS-03**: Provide a README/design narrative that explains the architecture, alternatives, choices, and how to run/evaluate.
- [ ] **OBS-04**: Add a placeholder metric (e.g. `global_faithfulness` or `global_coverage`) returning a simulated score or skipped flag in the offline evaluation script framework.

## Traceability

| Requirement | Current phase mapping | Scope status |
|---|---|---|
| RAG-02 | Phase 03 | Current MVP acceptance: successful dense/BM25 hybrid retrieval, valid filters, deterministic fusion, and deduplication. |
| RAG-03 | Phase 06, Phase 06.1 | Deferred hardening target; not covered or accepted by Phase 03. Split during Phase 6 discussion (06-CONTEXT.md D-77/D-78): DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-05 and DEBT-RAG-06 clauses → Phase 06; DEBT-RAG-04 (index rebuild-and-swap) → Phase 06.1. |
| RAG-04 | Phase 03 | Current MVP acceptance: async `Reranker` port and `NoOpReranker` pass-through. |
| OBS-01 | Phase 06.2 | OpenTelemetry traces, metrics and logs across Go and Rust (06-CONTEXT.md D-78). |
| OBS-02 | Phase 06.3 | Offline evaluation harness against MultiHop-RAG (06-CONTEXT.md D-78). |
| OBS-03 | Phase 06.4 | README/design-narrative suite and verified quickstart (06-CONTEXT.md D-78). |
| OBS-04 | Phase 06.3 | Placeholder global-evaluation metric, registered as an explicit `skipped` dimension (06-CONTEXT.md D-78, D-51). |

The Phase 03 source audit and coverage matrix must show RAG-03 as opted out/deferred rather than covered.

## v2 Requirements (Deferred)

- [ ] Heavy PDF-first ingestion.
- [ ] Full checkpoint database (PostgreSQL-backed snapshots beyond MVP).
- [ ] Dynamic node loading, plugin marketplace.
- [ ] Distributed workflow execution.

## Out of Scope

- Full LangGraph, Dify, or generic workflow-engine clone — limits scope to fixed RAG path needed for this project.
- Visual workflow editor, full workflow DSL — pulls project away from core systems/RAG story.
- Product-facing web UI — CLI/API and minimal response streaming are sufficient for MVP.
