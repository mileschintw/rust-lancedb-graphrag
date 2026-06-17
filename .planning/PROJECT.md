# Lancet

## What This Is

Lancet is an end-to-end, high-performance, systems-oriented Retrieval-Augmented Generation (RAG) and GraphRAG platform designed as a resume-oriented engineering artifact. It uses a split-service architecture: a Go API gateway as the control plane for HTTP APIs, sessions, metadata, and document management, and a Rust RAG engine as the data plane for document parsing, custom chunking, hybrid retrieval, graph traversal, and lightweight workflow orchestration.

The first version should be local-first and demoable: ingest a coherent corpus, answer questions with cited evidence, emit streaming workflow events, and expose traces/metrics that make the system's retrieval and orchestration decisions explainable.

## Core Value

Demonstrate strong engineering judgment by building a narrow but deep RAG/GraphRAG system that combines practical AI relevance with systems-level signals: custom data-plane mechanisms, explicit orchestration boundaries, retrieval quality evaluation, and production-like observability.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Define a stable gRPC contract between the Go API gateway and Rust RAG engine.
- [ ] Build a Go API gateway with document upload, RAG query, graph query, session handling, and metadata persistence.
- [ ] Build a Rust RAG engine with gRPC server, async runtime, tracing, and service boundaries.
- [ ] Implement document ingestion for Markdown, plain text, JSON, and other lightweight text-like sources before attempting PDF-heavy ingestion.
- [ ] Implement custom structure-aware recursive chunking with at least fixed-size and structure-aware strategies for comparison.
- [ ] Persist chunks and metadata in LanceDB as the local-first vector/graph store.
- [ ] Implement hybrid retrieval that combines dense vector search, local lexical/BM25 retrieval, metadata filtering, and deduplication.
- [ ] Extract entities and relationships during ingestion and persist them as graph nodes/edges in LanceDB.
- [ ] Query graph context with `lance-graph`/Cypher-style pattern matching and compile it into RAG prompt context.
- [ ] Implement a lightweight Rust state machine for the fixed RAG path: receive query, reformulate, retrieve hybrid, extract graph context, assemble prompt, generate answer, complete/failed.
- [ ] Emit client-facing workflow events such as node started/completed/failed, answer chunks, final answer, and workflow completed.
- [ ] Support degraded mode when graph extraction or one retrieval path fails, while still returning a useful vector/BM25-backed answer when possible.
- [ ] Add cancellation, timeouts, and retry/fallback behavior for node execution.
- [ ] Add lightweight checkpoints or snapshots for workflow state during development and debugging.
- [ ] Add OpenTelemetry-compatible tracing across Go, gRPC, Rust nodes, retrieval, graph queries, and LLM calls.
- [ ] Add an offline evaluation script using a fixed test set and LLM-as-judge or similar scoring for retrieval recall, context precision, groundedness, and faithfulness.
- [ ] Provide a local development path with `go run`, `cargo run`, and Docker Compose for PostgreSQL/Jaeger and optional local LLM fallback.
- [ ] Provide a README/design narrative that explains the architecture, alternatives considered, custom-vs-existing-tool choices, and how to run/evaluate the system.

### Out of Scope

- Full LangGraph, Dify, or generic workflow-engine clone — Lancet should borrow orchestration concepts but implement only the fixed RAG path needed for this project.
- Visual workflow editor, full workflow DSL, dynamic node loading, plugin marketplace, or generic tool planner — these would pull the project away from its core systems/RAG story.
- Full multi-agent framework or complex human-in-the-loop workflow — useful later, but not part of the initial MVP.
- Heavy PDF-first ingestion as the first ingestion target — start with text-like sources and make PDF support a later expansion.
- Full checkpoint database — simple in-memory/JSON/PostgreSQL-backed snapshots are enough for v1.
- Distributed workflow execution or production cloud deployment — local-first demo and evaluation come first.
- Product-facing web UI as a primary goal — CLI/API and minimal response streaming are sufficient unless a later phase explicitly adds UI.

## Context

The project is intended to be attractive to North American engineering interviews, especially for infrastructure, backend, data systems, AI platform, and RAG/AI-agent roles. It should show that the builder can make mature trade-offs: use existing tools for commodity infrastructure, rebuild high-leverage layers where custom implementation demonstrates understanding, and avoid overbuilding frameworks.

The current architectural direction is a Go/Rust split:

- **Go API Gateway / control plane:** HTTP API, authentication/session state, document metadata, PostgreSQL or SQLite fallback, request orchestration.
- **Rust RAG Engine / data plane:** gRPC server, async RAG pipeline, custom chunking, LanceDB vector/graph storage, hybrid retrieval, GraphRAG context extraction, prompt assembly, LLM generation, event streaming.
- **Inter-service communication:** gRPC with Protocol Buffers.
- **Storage:** LanceDB embedded in Rust for vector/graph data; PostgreSQL for metadata/sessions; Jaeger for traces.
- **Evaluation:** offline Python/Rust evaluation script with a fixed corpus/test set and metrics such as retrieval recall, context precision, groundedness, and faithfulness.

The `.discussion/` folder contains prior brainstorming, implementation planning, final architectural decisions, and a lightweight state-machine plan. The final implementation decisions should be treated as the strongest source of current direction.

## Constraints

- **Architecture:** Use the Go gateway + Rust engine split unless a later decision explicitly changes it — this is central to the control-plane/data-plane story.
- **Local-first development:** The project must run locally with `go run` and `cargo run`, plus Docker Compose for supporting services.
- **Core data-plane customness:** Chunking, retrieval composition, and orchestration should be custom enough to demonstrate understanding, not hidden behind a black-box framework.
- **Selective tool use:** Use mature tools for commodity pieces such as gRPC, tracing, storage, and LLM providers.
- **Demoability:** The first shippable version should show an end-to-end ingest → retrieve → answer flow with citations/events/traces.
- **Scope discipline:** Avoid rebuilding full workflow frameworks, generic agent systems, or broad product platforms before the core RAG/GraphRAG engine works.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Go API gateway + Rust RAG engine | Separates user-facing/control-plane concerns from performance-sensitive data-plane engineering | ✓ Good |
| gRPC/Protobuf service contract | Makes service boundaries explicit and interview-discussable | ✓ Good |
| LanceDB for vector/graph storage | Local-first, Arrow-native, aligned with systems/data-plane story | ✓ Good |
| PostgreSQL for metadata/sessions | Practical relational store for users, documents, sessions, and trace metadata | ✓ Good |
| Custom chunking and hybrid retrieval | High-leverage custom layers that demonstrate RAG understanding without rebuilding vector DB internals | ✓ Good |
| Lightweight Rust state machine instead of LangGraph/Dify clone | Borrows useful orchestration concepts while preserving narrow scope | ✓ Good |
| OpenTelemetry/Jaeger tracing | Makes latency and failure points visible across Go, Rust, gRPC, retrieval, graph, and LLM calls | ✓ Good |
| Offline evaluation script | Turns answer quality and retrieval quality into measurable claims | ✓ Good |
| Avoid full workflow framework | Keeps the project finishable and focused on RAG/GraphRAG engineering | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-17 after initialization from .discussion/*