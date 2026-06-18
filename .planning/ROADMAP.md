# Project Roadmap

**6 phases** | **18 requirements mapped** | All v1 requirements covered ✓

| # | Phase | Goal | Requirements |
|---|-------|------|--------------|
| 1 | Basic Gateway & Rust Engine Ping | Establish repo structure, Go HTTP API, and Rust gRPC server | ARCH-01, ARCH-02, ARCH-03, RAG-01 |
| 2 | Ingestion, Chunking & Vector Storage | Ingest text/markdown, chunk, and store in LanceDB | DATA-01, DATA-02, DATA-03 |
| 3 | Hybrid Retrieval & Basic RAG Path | Implement hybrid retrieval and a simple end-to-end RAG answer generation | RAG-02, RAG-03 |
| 4 | Knowledge Graph Extraction & Query | Extract entities/relations, store in LanceDB, and compile into context | DATA-04, DATA-05 |
| 5 | State Machine & Workflow Events | Formalize orchestration via Rust state machine with streaming events | ORCH-01, ORCH-02, ORCH-03, ORCH-04 |
| 6 | Observability, Evaluation & Polish | Add OpenTelemetry tracing, offline eval script, and README | OBS-01, OBS-02, OBS-03 |

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
**Requirements:** DATA-01, DATA-02, DATA-03
**Success Criteria:**
1. Users can upload a document via the Go HTTP API.
2. Rust engine receives document via gRPC and chunks it.
3. Chunks and embeddings are successfully stored in an embedded LanceDB instance.

### Phase 3: Hybrid Retrieval & Basic RAG Path
**Goal:** Implement hybrid retrieval and a simple end-to-end RAG answer generation
**Mode:** mvp
**Requirements:** RAG-02, RAG-03
**Success Criteria:**
1. Rust engine can perform hybrid (vector + BM25) search against LanceDB.
2. Go gateway exposes an endpoint to ask a question and receives an LLM-generated answer using retrieved context.
3. System falls back gracefully if vector retrieval fails (degraded mode).

### Phase 4: Knowledge Graph Extraction & Query
**Goal:** Extract entities/relations, store in LanceDB, and compile into context
**Mode:** mvp
**Requirements:** DATA-04, DATA-05
**Success Criteria:**
1. Rust engine extracts entities and relationships from chunks during ingestion.
2. Graph data is stored in LanceDB tables.
3. Queries successfully traverse graph context to compile additional prompts for the LLM.

### Phase 5: State Machine & Workflow Events
**Goal:** Formalize orchestration via Rust state machine with streaming events
**Mode:** mvp
**Requirements:** ORCH-01, ORCH-02, ORCH-03, ORCH-04
**Success Criteria:**
1. RAG pipeline is formalized into a defined state machine.
2. Workflow events (node started, chunk generated, completed) stream from Rust to Go to Client.
3. Node timeouts and retries handle failure scenarios predictably.
4. Snapshots of the workflow state can be captured for debugging.

### Phase 6: Observability, Evaluation & Polish
**Goal:** Add OpenTelemetry tracing, offline eval script, and README
**Mode:** mvp
**Requirements:** OBS-01, OBS-02, OBS-03
**Success Criteria:**
1. OpenTelemetry traces span Go, gRPC, and Rust components.
2. Offline eval script successfully scores retrieval and answer quality on a test set.
3. README provides clear architecture docs and instructions on how to run/evaluate.

## Backlog

### Phase 999.1: Community Summaries (Global Graph Summarization) (BACKLOG)

**Goal:** Pre-computed, hierarchical summary layer built on top of the knowledge graph.
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
