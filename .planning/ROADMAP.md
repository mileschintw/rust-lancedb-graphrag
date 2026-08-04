# Project Roadmap

**6 phases** | **23 requirements mapped** | All v1 requirements covered ✓

| # | Phase | Goal | Requirements |
|---|-------|------|--------------|
| 1 | 1/1 | Complete    | 2026-07-13 |
| 2 | 28/28 | Complete (ADR-02-004 deferral to Phase 6) | 2026-07-30 |
| 3 | Hybrid Retrieval & Basic RAG Path | Implement the valid hybrid retrieval and one structured RAG answer path | RAG-02, RAG-04 |
| 4 | Knowledge Graph Extraction & Query | Extract entities/relations, store in LanceDB, and compile into context | DATA-04, DATA-05, RAG-05 |
| 5 | State Machine & Workflow Events | Formalize orchestration via Rust state machine with streaming events | ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05 |
| 6 | Observability, Evaluation & Polish | Add OpenTelemetry tracing, offline eval script, README, and RAG hardening | RAG-03, OBS-01, OBS-02, OBS-03, OBS-04 |

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

**Goal:** As a Lancet API user, I want to ingest and safely replace text or Markdown documents, so that the last completed LanceDB index and PostgreSQL status remain trustworthy through failures and concurrent polling.
**Mode:** mvp
**Requirements:** DATA-01, DATA-02, DATA-03, DATA-06, DATA-07, DATA-08, DATA-09, RAG-06
**Plans:** 28/28 plans executed
**Verification:** Force-closed per ADR-02-004 — 15/20 must-haves verified; all open gaps (CR-01..04, WR-01..03, VER-16, VER-19, VER-20) deferred to Phase 6 hardening as technical debt.
**Wave 1**

- [x] 02-01-PLAN.md

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03-PLAN.md

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 02-04-PLAN.md

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 02-05-PLAN.md

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 02-06-PLAN.md

**Wave 7** *(blocked on Wave 6 completion; parallel)*

- [x] 02-07-PLAN.md — Route every replacement failure through rollback, prove retry convergence, persist node summaries as null, and harden canceled-request compensation.
- [x] 02-08-PLAN.md — Enforce the 10-second OpenRouter timeout and derive inspector identity/generation facts from durable rows.

**Wave 8** *(blocked on Wave 7 completion)*

- [x] 02-09-PLAN.md — Make live evidence validation optimization-resistant, consume derived inspector facts, and ignore/clean both private runtime artifacts.

**Wave 9** *(blocked on Wave 8 completion)*

- [x] 02-10-PLAN.md — Execute a fresh post-change OpenRouter ingestion and accept it only after challenge-bound PostgreSQL/LanceDB reinspection and success-only runtime-artifact cleanup.

**Wave 10** *(blocked on Wave 9 completion; parallel)*

- [x] 02-11-PLAN.md — Resolve ambiguous gRPC admission, retry terminal reconciliation, repair engine NotFound, and validate response identity.
- [x] 02-12-PLAN.md — Bound challenge freshness, preserve caller-owned input, and stop the build-output ignore from hiding Rust binaries.
- [x] 02-13-PLAN.md — Make explicit-path LanceDB inspection configuration-independent and reject null or non-finite embedding children.

**Wave 11** *(blocked on Wave 10 completion)*

- [x] 02-14-PLAN.md — Route schema lookup failures through rollback and restore a green all-target Rust lint gate.

**Wave 12** *(blocked on Wave 11 completion)*

- [x] 02-15-PLAN.md — Machine-wire privacy prohibition enforcement and require human review of nondeterministic disclosure surfaces.

**Wave 13** *(blocked on Wave 12 completion)*

- [x] 02-16-PLAN.md — Run fresh OpenRouter validation only after deterministic closure, then reconcile current state and clean evidence on full success.

**Wave 14** *(executed Phase 02 baseline; parallel)*

- [x] 02-17-PLAN.md — Honor the shared config directory, make persisted chunk settings execute end to end, and enforce the local-only loopback guardrail.
- [x] 02-18-PLAN.md — Add the durable PostgreSQL reconciliation-intent contract and generated query surface.

**Wave 15** *(blocked on Wave 14; parallel)*

- [x] 02-19-PLAN.md — Run the restart-safe gateway reconciler until failed admission reaches a verified terminal state.
- [x] 02-20-PLAN.md — Make LanceDB inspection read-only and non-disclosing, and prove real schema-field rollback plus worker survival.

**Wave 16** *(blocked on Wave 15)*

- [x] 02-21-PLAN.md — Consolidate privacy and verification configuration in fail-closed Python tooling and run the deterministic Phase 02 exit gate.

**Wave 17** *(blocked on Wave 16; parallel)*

- [x] 02-22-PLAN.md — Drain acknowledged work during shutdown and restore staged ingestion safely after restart.
- [x] 02-23-PLAN.md — Reject camel-case privacy aliases and isolate live-evidence runtime paths.

**Wave 18** *(blocked on Wave 17)*

- [x] 02-24-PLAN.md — Bound and validate persisted chunk settings, make polling staging-aware, and isolate database fixtures.

**Wave 19** *(blocked on Wave 18; parallel)*

- [x] 02-25-PLAN.md — Complete the Rust staging lifecycle with worker-first replay, idempotent initialization, truthful absence, and delete-before-terminal convergence.
- [x] 02-26-PLAN.md — Isolate the remaining PostgreSQL claimant test, make snapshot failures fatal, and add the review checklist.
- [x] 02-27-PLAN.md — Make privacy diagnostics category-only and live-evidence fixture cleanup process-owned.

**Wave 20** *(blocked on Wave 19)*

- [x] 02-28-PLAN.md — Run the deterministic exit gate, fresh provider-backed cross-store validation, and private disclosure review.

**Success Criteria:**

1. Users can upload a document via the Go HTTP API.
2. Rust engine receives document via gRPC and chunks it.
3. Chunks and embeddings are successfully stored in an embedded LanceDB instance.
4. Schema includes community_ids array placeholder field on nodes and registers placeholder communities table (Port for 999.1).
5. Schema includes nullable summary (Text) and summary_vector (Float Array) columns on nodes (Port for 999.4) and edges (Port for 999.5), plus unsummarized_refs (Text Array) on nodes (Port for 999.4).
6. Define EntityResolver Rust trait and ExactMatchResolver pass-through implementation (Port for 999.6).
7. Implement pass-through Tokio channel worker task in Rust engine (Port for 999.4).

### Phase 3: Hybrid Retrieval & Basic RAG Path

**Goal:** As a chat service API user, I want to ask a question using hybrid vector and BM25 retrieval, so that the LLM returns an answer grounded in completed corpus evidence.
**Mode:** mvp
**Requirements:** RAG-02, RAG-04
**Deferred target:** RAG-03 is explicitly deferred from Phase 03 to Phase 06 hardening/evaluation; its target behavior remains in `deferred-items.md` as DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-04, DEBT-RAG-05, and DEBT-RAG-06. It is not a Phase 03 acceptance requirement.
**Plans:** 11/12 plans executed

Plans:
**Wave 1**

- [x] 03-01-PLAN.md — Add approved Unicode BM25 dependencies and prove deterministic dense/BM25 fusion and NoOp retrieval.

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-02-PLAN.md — Build bounded evidence and the strict provider-neutral/OpenRouter generation contract.

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03-03-PLAN.md — Expose additive QueryRAG gRPC and make initial BM25 build part of Rust readiness.

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 03-04-PLAN.md — Add the strict Go HTTP boundary and endpoint-injectable query embeddings.

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 03-05-PLAN.md — Run the isolated real-process smoke with local embedding, metadata, and chat mocks.

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 03-06-PLAN.md — Close prompt and provider grounding-integrity blockers with fail-closed evidence and validated-output regressions.

**Wave 7** *(blocked on Wave 6 completion; parallel)*

- [x] 03-07-PLAN.md — Thread validated effective settings through retrieval, evidence, providers, persistence identity, and snapshots.
- [x] 03-08-PLAN.md — Enforce the 32 KiB HTTP body boundary and 60-second read timeout while preserving the cross-runtime path.

**Wave 8** *(blocked on Wave 7 completion; parallel)*

- [x] 03-09-PLAN.md — Project identity-correct citations, Unicode-bounded excerpts, and severity-correct diagnostics.
- [x] 03-10-PLAN.md — Build configuration-based embedding and generation adapters with exact request-capture tests.

**Wave 9** *(blocked on Wave 8 completion)*

- [x] 03-11-PLAN.md — Wire effective configuration and providers into production startup and prove initial readiness guards.

**Wave 10** *(blocked on Wave 9 completion)*

- [ ] 03-12-PLAN.md — Wire NoOpReranker into production query_rag and enforce zero-weight retrieval-source exclusion.

**Success Criteria:**

1. For a valid query over a completed corpus where both vector and BM25 retrieval paths succeed, the Rust engine fuses deterministic, bounded evidence and returns one structured answer with valid citations resolving to that evidence.
2. Go gateway exposes `/rag/query` and receives that retrieval-grounded structured answer through the Rust gRPC boundary.
3. Initial BM25 construction completes before the first query-ready state, and an initial build failure prevents serving the valid path.
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

**Goal:** Add OpenTelemetry tracing, offline eval script, README, and post-MVP hardening
**Mode:** mvp
**Requirements:** RAG-03, OBS-01, OBS-02, OBS-03, OBS-04
**Success Criteria:**

1. OpenTelemetry traces span Go, gRPC, and Rust components.
2. Offline eval script successfully scores retrieval and answer quality on a test set.
3. README provides clear architecture docs and instructions on how to run/evaluate.
4. Include placeholder metric for global GraphRAG evaluation.
5. Close `DEBT-BU-01` and `DEBT-BU-02` with their recorded behavioral proofs before declaring the v1 MVP complete.
6. Review `DEBT-CR-04` and `DEBT-CR-05` as conditional security/resource gates if neither has triggered earlier; any non-loopback/shared/remote/public caller or bulk/scheduled/concurrent/larger-uncontrolled ingestion trigger makes the corresponding review immediate and overrides Phase 6 timing.
7. Implement and verify the deferred RAG-03 hardening target, including DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-04, DEBT-RAG-05, and DEBT-RAG-06 acceptance criteria, before claiming degraded/citation-repair/re-ingestion coverage.

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

**Goal:** For CPU-heavy tasks, such as: chunking、embedding、entity extraction or graph post-processing, etc, import and use bounded ThreadPool from Rayon
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.8: S3-compatible storage for LanceDB (BACKLOG)

**Goal:** Move the place store lance/lancedb from local file system to s3-compatible system, e.g. SeaweedFS or garage
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.9: Karpathy-style LLM wiki second brain (BACKLOG)

**Goal:** Implement karpathy style llm wiki as user's or even team's second brain. Should be store and version control/ PR review with git in MD format. Put the projection embedding and chunk of wiki in lancedb as a part of retriveable data source with a switch for user to choose include or not.
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.10: Store session conversation context in LanceDB (BACKLOG)

**Goal:** Import lance-context to store full-session conversation into LanceDB for context window long-term memory and audit trail
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)
