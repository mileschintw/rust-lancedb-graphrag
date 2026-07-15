# Project Roadmap

**6 phases** | **23 requirements mapped** | All v1 requirements covered ✓

| # | Phase | Goal | Requirements |
|---|-------|------|--------------|
| 1 | 1/1 | Complete    | 2026-07-13 |
| 2 | Ingestion, Chunking & Vector Storage | Ingest text/markdown, chunk, and store in LanceDB | DATA-01, DATA-02, DATA-03, DATA-06, DATA-07, DATA-08, DATA-09, RAG-06 |
| 3 | Hybrid Retrieval & Basic RAG Path | Implement hybrid retrieval and a simple end-to-end RAG answer generation | RAG-02, RAG-03, RAG-04 |
| 4 | Knowledge Graph Extraction & Query | Extract entities/relations, store in LanceDB, and compile into context | DATA-04, DATA-05, RAG-05 |
| 5 | State Machine & Workflow Events | Formalize orchestration via Rust state machine with streaming events | ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05 |
| 6 | Observability, Evaluation & Polish | Add OpenTelemetry tracing, offline eval script, and README | OBS-01, OBS-02, OBS-03, OBS-04 |

## Phase Details

### Phase 1: Basic Gateway & Rust Engine Ping

**Goal:** Establish repo structure, Go HTTP API, and Rust gRPC server
**Mode:** mvp
**Requirements:** ARCH-01, ARCH-02, ARCH-03, RAG-01
**Success Criteria:**

1. Go gateway starts and serves an HTTP health check.
2. Rust engine starts and serves a gRPC health check.
3. Go gateway can successfully ping the Rust engine via gRPC.
4. Local dev environment (Docker Compose for Postgres/Jaeger) is functional.

### Phase 2: Ingestion, Chunking & Vector Storage

**Goal:** Ingest text/markdown, chunk, and store in LanceDB
**Mode:** mvp
**Requirements:** DATA-01, DATA-02, DATA-03, DATA-06, DATA-07, DATA-08, DATA-09, RAG-06
**Success Criteria:**

1. Users can upload a document via the Go HTTP API.
2. Rust engine receives document via gRPC and chunks it.
3. Chunks and embeddings are successfully stored in an embedded LanceDB instance.
4. Schema includes community_ids array placeholder field on nodes and registers placeholder communities table (Port for 999.1).
5. Schema includes nullable summary (Text) and summary_vector (Float Array) columns on nodes (Port for 999.4) and edges (Port for 999.5), plus unsummarized_refs (Text Array) on nodes (Port for 999.4).
6. Define EntityResolver Rust trait and ExactMatchResolver pass-through implementation (Port for 999.6).
7. Implement pass-through Tokio channel worker task in Rust engine (Port for 999.4).

### Phase 3: Hybrid Retrieval & Basic RAG Path

**Goal:** Implement hybrid retrieval and a simple end-to-end RAG answer generation
**Mode:** mvp
**Requirements:** RAG-02, RAG-03, RAG-04
**Success Criteria:**

1. Rust engine can perform hybrid (vector + BM25) search against LanceDB.
2. Go gateway exposes an endpoint to ask a question and receives an LLM-generated answer using retrieved context.
3. System falls back gracefully if vector retrieval fails (degraded mode).
4. Define pluggable async Reranker trait and NoOpReranker pass-through implementation (Port for 999.2).

### Phase 4: Knowledge Graph Extraction & Query

**Goal:** Extract entities/relations, store in LanceDB, and compile into context
**Mode:** mvp
**Requirements:** DATA-04, DATA-05, RAG-05
**Success Criteria:**

1. Rust engine extracts entities and relationships from chunks during ingestion.
2. Graph data is stored in LanceDB tables.
3. Queries successfully traverse graph context to compile additional prompts for the LLM.
4. Define ContextAssemblyStrategy trait/enum and implement SourceChunks fallback strategy (Port for 999.5).

### Phase 5: State Machine & Workflow Events

**Goal:** Formalize orchestration via Rust state machine with streaming events
**Mode:** mvp
**Requirements:** ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05
**Success Criteria:**

1. RAG pipeline is formalized into a defined state machine.
2. Workflow events (node started, chunk generated, completed) stream from Rust to Go to Client.
3. Node timeouts and retries handle failure scenarios predictably.
4. Snapshots of the workflow state can be captured for debugging.
5. QueryReformulator trait defined with pass-through node in state machine (Port for 999.3).

### Phase 6: Observability, Evaluation & Polish

**Goal:** Add OpenTelemetry tracing, offline eval script, and README
**Mode:** mvp
**Requirements:** OBS-01, OBS-02, OBS-03, OBS-04
**Success Criteria:**

1. OpenTelemetry traces span Go, gRPC, and Rust components.
2. Offline eval script successfully scores retrieval and answer quality on a test set.
3. README provides clear architecture docs and instructions on how to run/evaluate.
4. Include placeholder metric for global GraphRAG evaluation.

## Backlog

### Phase 999.1: Community Summaries (Global Graph Summarization) (BACKLOG)

**Goal:** Pre-computed, hierarchical summary layer built on top of the knowledge graph.
**Requirements:** TBD
**Plans:** 1/1 plans complete

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.5: Compile-Time Semantics on Graph Nodes (BACKLOG)

**Goal:** Pre-compute node and edge summaries during indexing so traversers read rich pre-built context instead of re-deriving meaning at query time (closely related to Phase 999.1).
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.2: Reranking (BACKLOG)

**Goal:** A second-pass cross-encoder model to re-score merged retrieval candidates.
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.3: Query Reformulation Strategies (BACKLOG)

**Goal:** LLM-based query expansion techniques like HyDE and multi-query expansion.
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.4: LLM-Assisted Synthesis at Ingestion Time (BACKLOG)

**Goal:** Generate synthesized, consolidated prose descriptions for extracted entities/relationships during document ingestion and store them in LanceDB alongside vectors.
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.6: Knowledge Drift Detection and Node Merging (BACKLOG)

**Goal:** Implement semantic entity resolution and node merging using vector similarity and LLM verification to maintain a self-healing, clean knowledge graph.
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.7: CPU execution isolation with Rayon (BACKLOG)

**Goal:** For CPU-heavy tasks, such as: chunking、embedding、entity extraction 或 graph post-processing, etc, import and use bounded ThreadPool from Rayon
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

