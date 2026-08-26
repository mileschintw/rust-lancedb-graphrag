# Project Roadmap

**10 phases** | **23 requirements mapped** | All v1 requirements covered ✓

| # | Phase | Goal | Requirements |
|---|-------|------|--------------|
| 1 | 1/1 | Complete    | 2026-07-13 |
| 2 | 28/28 | Complete (ADR-02-004 deferral to Phase 6) | 2026-07-30 |
| 3 | 23/23 | Complete (ADR-03-003 force-close; DEBT-P3-* to Phase 6) | 2026-08-05 |
| 4 | Knowledge Graph Extraction & Query | Extract entities/relations, store in LanceDB, and compile into context | DATA-04, DATA-05, RAG-05 |
| 5 | State Machine & Workflow Events | Formalize orchestration via Rust state machine with streaming events | ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05 |
| 6 | Observability, Evaluation & Polish (module graph, wire contract, RAG-03 core) | Module-graph restructure, consolidated wire contract, degraded-mode/citation-repair/bad-input/graph-unavailable hardening | RAG-03 |
| 6.1 | Index Rebuild-and-Swap, BU Proofs, CR-04/CR-05 Review (INSERTED) | Rebuild-and-swap index lifecycle, DEBT-BU-01/02 deterministic proofs, documented CR-04/CR-05 review | RAG-03 |
| 6.2 | OpenTelemetry Traces, Metrics and Logs (INSERTED) | OTel across Go and Rust via Collector to Jaeger/Prometheus/Loki/Grafana | OBS-01 |
| 6.3 | Evaluation Harness, Corpora and Recorded Run (INSERTED) | Python eval harness against MultiHop-RAG with deterministic + LLM-judged metrics | OBS-02, OBS-04 |
| 6.4 | Docs Suite, Verified Quickstart and v1 Closure (INSERTED) | README/docs suite, verified quickstart, debt backlog promotion, milestone closure | OBS-03 |

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
**Verification:** Force-closed per ADR-03-003 — 98/101 plan truths verified; residual gaps (DEBT-P3-BODY-BOUND, DEBT-P3-STAGING-GEN-RACE, DEBT-P3-STAGING-PHYSICAL-BU, DEBT-P3-CONFIG-DB-PLAINTEXT, DEBT-CR-04 extension, DEBT-P3-PROVIDER-ENDPOINT-TRUST, DEBT-P3-WARN-*, DEBT-P3-MODULE-GRAPH) deferred to Phase 6 hardening as technical debt.
**Deferred target:** RAG-03 is explicitly deferred from Phase 03 to Phase 06 hardening/evaluation; its target behavior remains in `deferred-items.md` as DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-04, DEBT-RAG-05, and DEBT-RAG-06. It is not a Phase 03 acceptance requirement.
**Plans:** 23/23 plans executed

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

- [x] 03-12-PLAN.md — Wire NoOpReranker into production query_rag and enforce zero-weight retrieval-source exclusion.

**Wave 11** *(blocked on Wave 10 completion)*

- [x] 03-13-PLAN.md — Enforce fail-closed retrieval grounding and bounded OpenRouter output.

**Wave 12** *(blocked on Wave 11 completion)*

- [x] 03-14-PLAN.md — Route effective settings through the provider and preserve generation identity with explicit credentials.

**Wave 13** *(blocked on Wave 12 completion)*

- [x] 03-15-PLAN.md — Stabilize citation identity fixtures and restore the complete locked Rust regression gate.

**Wave 14** *(blocked on Wave 13 completion)*

- [x] 03-16-PLAN.md — Close G1 with effective provider usage limits and service-safe ceilings.

**Wave 15** *(blocked on Wave 14 completion)*

- [x] 03-17-PLAN.md — Fail closed on embedding and dense retrieval infrastructure errors with identity propagation.

**Wave 16** *(blocked on Wave 15 completion)*

- [x] 03-18-PLAN.md — Return valid zero-match success responses and confirm deferred RAG boundaries.

**Wave 17** *(blocked on Wave 16 completion)*

- [x] 03-19-PLAN.md — Carry effective grounding limits end-to-end and reconcile the D1-LOG waiver documentation.

**Wave 18** *(blocked on Wave 17 completion; parallel)*

- [x] 03-20-PLAN.md — Enforce bounded provider request bodies and metadata/embedding request contracts.
- [x] 03-21-PLAN.md — Enforce retrieval service ceilings and normalized, deduplicated filter limits.

**Wave 19** *(blocked on Wave 18 completion)*

- [x] 03-22-PLAN.md — Prove finite deterministic fusion and gateway write-error handling.

**Wave 20** *(blocked on Wave 19 completion)*

- [x] 03-23-PLAN.md — Persist raw ingestion generations with the gated Lance schema migration checkpoint.

**Success Criteria:**

1. For a valid query over a completed corpus where both vector and BM25 retrieval paths succeed, the Rust engine fuses deterministic, bounded evidence and returns one structured answer with valid citations resolving to that evidence.
2. Go gateway exposes `/rag/query` and receives that retrieval-grounded structured answer through the Rust gRPC boundary.
3. Initial BM25 construction completes before the first query-ready state, and an initial build failure prevents serving the valid path.
4. Define pluggable async Reranker trait and NoOpReranker pass-through implementation (Port for 999.2).

### Phase 4: Knowledge Graph Extraction & Query

**Goal:** As a Lancet engineer, I want to prototype lance-graph's LanceDB integration for entity/relationship storage, so that I know enough to plan graph extraction and query.
**Mode:** mvp
**Requirements:** DATA-04, DATA-05, RAG-05
**Deferred target:** The full extraction/storage/query-traversal implementation (original Success Criteria below) and full closure of DATA-04, DATA-05, and RAG-05 are deferred to Phase 04.1 (not yet created — see `/gsd insert-phase` guidance after planning completes). Phase 4 itself only needs to close the `lance-graph`/`lancedb` compatibility unknown flagged CONDITIONAL in `04-AI-SPEC.md`.
**Success Criteria:**

1. `lance-graph` 0.5.4's Cypher traversal API surface (path/URI vs. typed `Dataset` handle) is empirically confirmed, not just inferred from docs.
2. The `04-AI-SPEC.md` "Critical Finding" version-conflict question (`lance-graph` requires `lance ^1.0.0`; `lancedb ~0.31` requires `lance =8.0.0`) is resolved with a documented, reproducible integration pattern.
3. `04-AI-SPEC.md`'s Framework Decision status is updated from `CONDITIONAL` to confirmed/locked, citing the empirical evidence.
4. Phase 04.1 can be planned with the `lance-graph`/`lancedb` integration pattern as a known quantity, not an open risk.

*(Deferred — Phase 04.1 Success Criteria, carried forward unchanged:)*

1. Rust engine extracts entities and relationships from chunks during ingestion.
2. Graph data is stored in LanceDB tables.
3. Queries successfully traverse graph context to compile additional prompts for the LLM.
4. Define ContextAssemblyStrategy trait/enum and implement SourceChunks fallback strategy (Port for 999.5).

**Plans:** 1/1 plans complete

Plans:
**Wave 1**

- [x] 04-01-PLAN.md — Resolve the real lancedb+lance-graph manifest, check in a feature-gated PoC reproducing 04-RESEARCH.md's proven bridge/Cypher patterns, and lock 04-AI-SPEC.md's Framework Decision to CONFIRMED.

### Phase 04.1: Knowledge Graph Extraction & Query (Full Implementation) (INSERTED)

**Goal:** As a Lancet engineer, I want to extract entities and relationships from chunks during ingestion, persist them as a knowledge graph in LanceDB, and traverse them at query time via the now-confirmed `lance-graph` integration, so that RAG queries are grounded with graph context alongside the existing hybrid-retrieval evidence.
**Mode:** mvp
**Requirements:** DATA-04, DATA-05, RAG-05
**Depends on:** Phase 4
**Success Criteria:** *(carried forward unchanged from Phase 4's original deferred target)*

1. Rust engine extracts entities and relationships from chunks during ingestion.
2. Graph data is stored in LanceDB tables.
3. Queries successfully traverse graph context to compile additional prompts for the LLM.
4. Define ContextAssemblyStrategy trait/enum and implement SourceChunks fallback strategy (Port for 999.5).

**Plans:** 9/9 plans complete

Plans:
**Wave 1**

- [x] 04.1-01-PLAN.md — Promote graph out of graph-spike, lock the entities/entity_edges schema-restructure decision, and migrate every existing fixture/test to the restructured schema.

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04.1-02-PLAN.md — Prove extract→persist→traverse→render→reach-the-provider end-to-end (tracer), including the provider-payload-capture fix, seed-inclusive fetch_neighborhood, and reserve-one-citable-chunk packing.

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04.1-03-PLAN.md — Concurrent bounded extraction (D-09), real min-content-length skip (D-07), idempotent re-ingestion by construction, documented stale-entity semantics, and the WR-01 bridge multi-batch fix.

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 04.1-04-PLAN.md — Redesign the standalone QueryGraph RPC as an induced-neighborhood query with a structured, hop-bounded contract, correct relation-type filtering at any hop depth, and validated input.

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 04.1-05-PLAN.md — Score-interleave graph facts with chunk evidence under a validated, configurable graph_weight, and prove graph_augmentation outcome tagging observable end-to-end.

**Wave 6** *(gap closure — blocked on Wave 5 completion)*

- [x] 04.1-06-PLAN.md — Prove Cypher genuinely narrows the response on disagreement (Gap 1) including the zero-confirmed-neighbors total-disagreement case (REVIEWS.md MEDIUM); fix a previously-undiscovered one-sided directional gap in Cypher confirmation (lance-graph 0.5.4's RelationshipMapping has no bidirectional option) that empirical full-suite regression testing proved was a required prerequisite for the fallback fix above; fix and regression-test CR-01's edge-dedup identity defect; and fix and regression-test WR-01's final-hop frontier-cap gap plus the pre-existing MAX_TOTAL_EDGES rejection's first test.

**Wave 7** *(gap closure — blocked on Wave 6 completion)*

- [x] 04.1-07-PLAN.md — Prove extraction/graph-augmentation reach the provider through the real worker queue (not a direct call), and prove GraphFact orientation is preserved on the RAG path when the seed is the edge's target.

**Wave 8** *(review closure — blocked on Wave 7 completion)*

- [x] 04.1-08-PLAN.md — Fix the inverted exact-score tie-breaker in pack_evidence_and_graph_prompt and add field-level tracing::debug! diagnostics to validate_extraction_output's confidence-out-of-range failure (REVIEWS.md LOW findings, closed with real code changes since Plans 03/05 already executed).

**Wave 9** *(gap closure — blocked on Wave 8 completion)*

- [x] 04.1-09-PLAN.md — Fix the fresh CR-01 defect where fetch_neighborhood's MAX_TOTAL_EDGES bound double-counted bidirectionally re-matched edges before dedup, wrongly rejecting genuinely in-bounds multi-hop query_graph requests; rename WR-04's misleadingly-scoped fail-open test; explicit disposition recorded for every other still-open 04.1-REVIEW.md finding.

### Phase 5: State Machine & Workflow Events

**Goal:** As a Lancet engineer, I want to formalize RAG orchestration into a Rust state machine, so that I can debug and extend the pipeline with predictable failure handling.
**Mode:** mvp
**Requirements:** ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05
**Success Criteria:**

1. RAG pipeline is formalized into a defined state machine.
2. Workflow events (node started, chunk generated, completed) stream from Rust to Go to Client.
3. Node timeouts and retries handle failure scenarios predictably.
4. Snapshots of the workflow state can be captured for debugging.
5. QueryReformulator trait defined with pass-through node in state machine (Port for 999.3).

**Plans:** 27/27 plans complete

Plans:

- [x] 05-07-PLAN.md
- [x] 05-08-PLAN.md — Production five-node wiring, real adapter dependencies, and WorkflowContext population.
- [x] 05-09-PLAN.md — Live workflow settings, real-I/O deadlines, and stream-owned cancellation.
- [x] 05-10-PLAN.md — Reliable typed event delivery, terminal idempotence, sequence integrity, and full snapshots.
- [x] 05-11-PLAN.md — Real engine-to-gateway SSE and lossless checkpoint dispatch under backpressure.
- [x] 05-12-PLAN.md — Additive historical-summary traceability errata and source coverage audit.
- [x] 05-13-PLAN.md — OpenRouter preflight classification, successful-only capability caching, and bounded generation retry.
- [x] 05-14-PLAN.md — Exhaustive typed NodeKind dispatch and early reformulation admission.
- [x] 05-15-PLAN.md — Prompt API contract and cfg(test)-only workflow fakes.
- [x] 05-16-PLAN.md — Graph notice merge, variant provenance, and immutable BM25 snapshotting.
- [x] 05-17-PLAN.md — Shared protobuf provenance and failure-terminal notice fields with synchronized Rust/Go bindings.
- [x] 05-18-PLAN.md — Library-target Phase 5 tests and cfg(test) fake-port seam.
- [x] 05-19-PLAN.md — Failure-terminal notice preservation from Rust workflow events through Go SSE.
- [x] 05-20-PLAN.md — Preflight bootstrap timing, worst-case retry budget, and bounded workflow tests.
- [x] 05-21-PLAN.md — Typed fusion provenance and review cleanup guards.
- [x] 05-22-PLAN.md — Typed graph-fact prompt/generation handoff and exact production reachability assertions.
- [x] 05-23-PLAN.md — Generated-field Rust compile repair and RetrievalSnapshot wire-contract proof.
- [x] 05-24-PLAN.md — Executable two-pass cross-variant RRF contract with exact scores and deterministic ordering.
- [x] 05-25-PLAN.md — Gap closure (G-05-1 Blocker A): rebuild/reseed the stale local LanceDB nodes table and add a remediation hint to validate_schema's fail-closed error.
- [x] 05-26-PLAN.md — Gap closure (G-05-1 Blocker B): decouple gateway's real-engine integration tests from ambient config.toml's generation_model via an explicit env override.
- [x] 05-27-PLAN.md — Gap closure (G-05-1 root cause): raise the OpenRouter models-metadata body ceiling to 10MB while keeping embeddings/chat at 256KB.

**Wave 1** *(atomic coordinated landing group: 05-01 + 05-06; validate and land together)*

- [x] 05-01-PLAN.md — Tracer: streaming QueryRAG wire contract, one-node Rust Node/WorkflowRunner, and independent checkpoint channel.
- [x] 05-06-PLAN.md — Generated stream to Go SSE, timeout configuration, and deterministic transport/config regression tests.

**Wave 2** *(blocked on the Wave 1 atomic landing group)*

- [x] 05-07-PLAN.md — Append the typed InputValidation NodeErrorKind member and regenerate the Rust/Go wire bindings.

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 05-02-PLAN.md — ExtractGraphContext + RetrieveHybrid nodes, D-06 corrected order, D-07 cross-variant RRF merge, D-03 short-circuit with full retrieval-source context.

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 05-03-PLAN.md — AssemblePrompt + GenerateAnswer nodes, D-12/D-13 retry-then-honest-failure, D-01/D-02 AnswerChunk/FinalAnswer, and full accumulated snapshots.

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 05-04-PLAN.md — Full deterministic Rust orchestration matrix, cooperative cancellation cleanup, and fault-injection coverage.

**Wave 6** *(blocked on Wave 5 completion and the completed Wave 1 dispatcher contract)*

- [x] 05-05-PLAN.md — PostgreSQL-backed workflow_checkpoints persistence (ORCH-04), detached standalone checkpoint events, and full-snapshot fidelity.

**Wave 7** *(additive gap closure starts; documentation is independent of Rust implementation files)*

- [x] 05-08-PLAN.md — Production five-node wiring, real adapter dependencies, and WorkflowContext population.
- [x] 05-12-PLAN.md — Additive historical-summary traceability errata and source coverage audit.

**Wave 8** *(blocked on production wiring)*

- [x] 05-09-PLAN.md — Live workflow settings, real-I/O deadlines, and stream-owned cancellation.

**Wave 9** *(blocked on live timeout and cancellation controls)*

- [x] 05-13-PLAN.md — OpenRouter preflight classification, successful-only capability caching, and bounded generation retry.

**Wave 10** *(blocked on the provider retry contract and live timeout/cancellation controls)*

- [x] 05-14-PLAN.md — Exhaustive typed NodeKind dispatch and early reformulation admission.

**Wave 11** *(blocked on typed dispatch; generated wire contract lands before target-aware fixture migration)*

- [x] 05-17-PLAN.md — Shared protobuf provenance and failure-terminal notice fields with synchronized Rust/Go bindings.

**Wave 12** *(blocked on the shared protobuf contract and generated-field compile repair)*

- [x] 05-23-PLAN.md — Repair generated Rust message literals and prove the additive RetrievalSnapshot wire contract.

**Wave 13** *(blocked on generated-field compile repair, production wiring, and target-aware handoff)*

- [x] 05-18-PLAN.md — Library-target Phase 5 tests, BM25 ownership migration, and cfg(test) fake-port seam.

**Wave 14** *(blocked on the target-aware fixture seam)*

- [x] 05-15-PLAN.md — Prompt API contract and cfg(test)-only workflow fakes.

**Wave 15** *(blocked on the prompt/fake seam and shared protobuf contract)*

- [x] 05-16-PLAN.md — Graph notice merge, variant provenance, and immutable BM25 snapshotting.

**Wave 16** *(parallel after the shared retrieval/event contracts; 05-10 owns the shared workflow event/context module before 05-22)*

- [x] 05-10-PLAN.md — Reliable typed event delivery, terminal idempotence, sequence integrity, and full snapshots.
- [x] 05-21-PLAN.md — Typed fusion provenance and review cleanup guards.

**Wave 17** *(blocked on terminal contract, test-target ownership, resolved cross-variant fusion contract, and 05-10 workflow event/context ownership)*

- [x] 05-19-PLAN.md — Failure-terminal notice preservation from Rust workflow events through Go SSE.
- [x] 05-24-PLAN.md — Executable two-pass cross-variant RRF contract with exact scores and deterministic ordering.

**Wave 18** *(blocked on 05-19 terminal ownership, generated-field repair, provider retry, and production wiring seams)*

- [x] 05-22-PLAN.md — Typed graph-fact prompt/generation handoff and exact production reachability assertions.

**Wave 19** *(blocked on provider retry, target handoff, terminal-event, and serialized 05-22 seams)*

- [x] 05-20-PLAN.md — Preflight bootstrap timing, worst-case retry budget, and bounded workflow tests.

**Wave 20** *(blocked on all engine event/timing, terminal, retrieval, and checkpoint contract work)*

- [x] 05-11-PLAN.md — Real engine-to-gateway SSE and lossless checkpoint dispatch under backpressure.

**Wave 21** *(gap closure for G-05-1, discovered during UAT Test 1; both plans are independent — no file overlap, no dependency on each other)*

- [x] 05-25-PLAN.md — Rebuild/reseed the stale local LanceDB nodes table; add a remediation hint to validate_schema's fail-closed error.
- [x] 05-26-PLAN.md — Decouple gateway's real-engine integration tests from ambient config.toml's generation_model via an explicit env override.

**Wave 22** *(gap closure for G-05-1 root cause, discovered during UAT Test 1 re-run after Wave 21)*

- [x] 05-27-PLAN.md — Raise the OpenRouter models-metadata body ceiling to 10MB via read_body_limited_with_limit, keeping embeddings/chat bounded at 256KB.

### Phase 6: Observability, Evaluation & Polish

**Goal:** Rust + Go module-graph restructure, consolidated additive wire-contract change, and RAG-03 degraded-mode hardening (model-only answers, citation repair, bad-input matrix, graph-unavailable notice)
**Mode:** mvp
**Requirements:** RAG-03 (DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-05, DEBT-RAG-06 clauses)
**Canonical refs:** `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` — governs Phases 6, 6.1, 6.2, 6.3 and 6.4 (D-77). Sub-phases carry the same reference; there is one source of truth.
**Success Criteria:**

> Phase 6's original seven success criteria were rewritten and redistributed across the five-phase split per 06-CONTEXT.md D-79. Mapping: SC1 → 6.2; SC2 and SC4 → 6.3; SC3 → 6.4; SC5 and SC6 → 6.1; SC7 → 6 and 6.1.

1. The Rust binary imports all production modules from the library crate; the dual `lib.rs`/`main.rs` declaration ends (`DEBT-P3-MODULE-GRAPH`, D-80), landed as the first Phase 6 plan (D-81). The Go gateway's `main.go` is symmetrically split into packages (telemetry setup, SSE handling, engine client, config) before telemetry work lands (D-82).
2. One consolidated additive protobuf change — the model-only request flag, the graph-ablation request flag, `WorkflowCompletedEvent` workflow-metadata fields, and the typed notice-code enum — lands with regenerated Rust and Go bindings before any behavior plan starts (D-74, D-76).
3. When both retrieval paths fail or evidence is absent and the caller has opted in (default off), the workflow returns `answer_basis = MODEL_ONLY` with an explicit notice and zero citations; with the flag off, today's fail-closed behavior is unchanged (D-10, D-11, D-12).
4. One retrieval path failing keeps `answer_basis = RETRIEVAL` with a machine-readable `RETRIEVAL_DEGRADED` notice naming the failed path (D-13).
5. Citation repair (`DEBT-RAG-03`) normalizes near-miss markers locally, strips anything still unresolved, emits `CITATION_REPAIRED`/`CITATION_DROPPED`, and downgrades the basis if all grounding is lost — no second provider call (D-14).
6. The bad-input matrix (`DEBT-RAG-05`) is an enumerated, table-driven test (gRPC and HTTP) covering malformed query/session/document IDs, content type, and filter bounds, all rejecting before retrieval or provider work with stable HTTP 400 / gRPC `InvalidArgument` (D-15).
7. The graph-unavailable notice (`DEBT-RAG-06`) fires on the two silent-degrade paths (empty-result and absent-`graph_port`) that don't already emit `GRAPH_TIMEOUT`/`GRAPH_DEGRADED`; source-chunk queries are proven to never require graph data (D-08).

**Plans:** 16/16 plans complete

Plans:
**Wave 1**

- [x] 06-01-PLAN.md — Rust module graph, step 1: move `chunker` and the whole configuration surface into the library crate; establish the per-target test invariant gate (D-80/D-81).
- [x] 06-04-PLAN.md — Go package split, part A: extract `internal/config` and `internal/sse`, create the reserved `internal/telemetry` stub, and establish the per-package Go test gate (D-82).

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 06-02-PLAN.md — Rust module graph, step 2: relocate the ingestion pipeline and the whole gRPC service implementation into `engine::ingest` and `engine::service` (D-80).
- [x] 06-05-PLAN.md — Go package split, part B: extract `internal/engineclient` and migrate the 67-test suite onto it; the insecure engine dial moves unchanged (D-82, D-03/D-06).

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 06-03-PLAN.md — Rust module graph, step 3: rehome the binary test root into the library target and reduce `main.rs` to startup wiring; pin the post-restructure distribution (D-80).

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 06-06-PLAN.md — Wave-0 test surface: `engine::testkit` constructors migrating ~100 exhaustive literals, the D-83 fake-port failure modes, and the Go exact-payload-key assertions.

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 06-07-PLAN.md — The consolidated additive wire contract: one proto edit, one regeneration, the single typed notice constructor, and the gateway plumbing for both request flags (D-74/D-76).

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 06-08-PLAN.md — Behavior tracer: end-to-end graph-context ablation, plus the `GRAPH_UNAVAILABLE` notice on the two silent-degrade paths and the source-chunk proof (D-47, D-08 / DEBT-RAG-06).

**Wave 7** *(blocked on Wave 6 completion)*

- [x] 06-09-PLAN.md — Convert both retrieval paths from fail-closed to degrade with per-path notices and per-variant tolerance (D-13 / DEBT-RAG-01).

**Wave 8** *(blocked on Wave 7 completion)*

- [x] 06-10-PLAN.md — Model-only opt-in: fail-closed config key, both grounding guards conditional, both zero-evidence gates bypassed (D-10/D-11/D-12/D-84 / DEBT-RAG-01).

**Wave 9** *(blocked on Wave 8 completion)*

- [x] 06-11-PLAN.md — Citation repair (normalize-then-strip), conservative basis reconciliation, and the evidence-over-priors prompt precedence (D-14/D-18/D-17/D-19/D-84 / DEBT-RAG-03).

**Wave 10** *(blocked on Wave 9 completion)*

- [x] 06-12-PLAN.md — The enumerated bad-input matrix, table-driven on both the gRPC and HTTP surfaces, with the unmatched-filter disposition recorded (D-15 / DEBT-RAG-05). Depends on 06-07 for content; ordered last because it shares the two test-count gate scripts with every behavior plan.

**Wave 11** *(gap closure; blocked on Wave 8 / 06-10)*

- [x] 06-13-PLAN.md — SC3 production packing: empty-evidence OpenRouter branch, model-only policy, answer_basis schema admits model_only, production-shaped runner, fail-closed test gates (D-10/D-11 / DEBT-RAG-01).

**Wave 12** *(gap closure; blocked on Wave 9 / 06-11 and Wave 11 / 06-13 because generate.rs, prompt.rs, workflow_phase5.rs, and the test-count gate overlap)*

- [x] 06-14-PLAN.md — SC5 citation-repair de-dupe: first-occurrence unique ids plus repeated-marker and mixed-spelling tests, fail-closed test gates (D-14 / DEBT-RAG-03).

**Wave 13** *(gap closure; blocked on Wave 11 / 06-13 and Wave 12 / 06-14 — same five Rust files plus the test-count gate)*

- [x] 06-15-PLAN.md — SC3 + SC5 root cause: gate the published inline remainder, split the grounding validator so the adapter keeps only shape checks, pin the engine-decided `answer_basis` at both validation sites, and prove both gaps end to end through the real `OpenRouterGenerator` (D-10/D-11/D-12/D-14/D-18/D-19 / DEBT-RAG-01, DEBT-RAG-03).

**Wave 14** *(gap closure; blocked on Wave 13 / 06-15)*

- [x] 06-16-PLAN.md — G-06-1 + G-06-2 UAT gap closure: flag-dependent allow_model_only on D-18 total-drop and dropped citations to truncated blocks (RAG-03).

### Phase 6.1: Index Rebuild-and-Swap, BU Deterministic Proofs, CR-04/CR-05 Documented Review (INSERTED)

**Goal:** Wire index rebuild-and-swap with cross-index corpus generation (DEBT-RAG-04), close DEBT-BU-01/DEBT-BU-02 with deterministic proofs, and complete the documented-only DEBT-CR-04/DEBT-CR-05 review
**Mode:** mvp
**Requirements:** RAG-03 (DEBT-RAG-04 clause)
**Depends on:** Phase 6
**Canonical refs:** `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` — governs Phases 6, 6.1, 6.2, 6.3 and 6.4 (D-77). Do not re-run discussion; this file is the canonical decision record.
**Success Criteria:**

1. On ingestion batch completion, BM25 is rebuilt from the nodes table and atomically swapped into the existing `Arc<RwLock<Arc<Bm25Index>>>`, debounced/coalesced so a burst of documents causes one rebuild, triggered from the Rust ingestion worker (D-20, D-23).
2. A query concurrent with an index swap returns results from exactly one generation, proven by a generation-stamped assertion test; queries never block on a rebuild and keep serving the previous generation until the instantaneous swap (D-21, D-22).
3. A single corpus generation covers both dense and BM25 representations — a query is served entirely from one generation or the other, never mixed (D-24), derived at startup from persisted LanceDB state with no stored counter (D-26).
4. A failed startup build stops the engine (fail-closed); a failed post-ingest rebuild keeps the previous generation serving with a warning notice and error-level logs/spans (D-25).
5. `DEBT-BU-01` closes via a deterministic test using a controlled/injected clock: matching challenge/evidence identity and issue times, exceeding only `issued_at`→`generated_at`, asserting the dedicated complete-run-window error classification (D-07).
6. `DEBT-BU-02` closes via a deterministic test: caller-fixture SHA-256 and bytes preserved across success plus representative early and post-upload failures, using script-created temporary inputs only, no live run (D-07).
7. `DEBT-CR-04` (network auth/authz/TLS/quotas) and `DEBT-CR-05` (pre-admission bounds) are reviewed as documented-only conditional gates: the loopback guardrail is verified to hold, no trigger fired, re-acceptance is recorded, and no new code ships for either (D-06).

**Plans:** 4/4 plans complete

Plans:
**Wave 1** *(parallel — no shared files)*

- [x] 06.1-01-PLAN.md — Index rebuild-and-swap (D-20..D-26): durable lance-{nodes.version()} generation, same-snapshot dense+BM25 pin, worker debounce, IndexRebuildFailed, fail-closed config (RAG-03).
- [x] 06.1-02-PLAN.md — Controlled-clock evidence window proof (DEBT-BU-01) and three-scenario caller-fixture preservation harness (DEBT-BU-02) (D-07 / RAG-03).
- [x] 06.1-03-PLAN.md — Documented security and guardrail review of DEBT-CR-04 (network auth/TLS) and DEBT-CR-05 (pre-admission bounds/timeouts/semaphore) (D-06 / RAG-03).

**Wave 2** *(gap closure — depends on 06.1-01)*

- [x] 06.1-04-PLAN.md — Close SC2/SC3/SC4: independent Table via database.nodes_table() for dense+rebuild (CR-01/CR-02/WR-01) and checkout_latest degrade (WR-02) (RAG-03).

### Phase 6.2: OpenTelemetry Traces, Metrics and Logs (OBS-01) (INSERTED)

**Goal:** Ship production-grade OTel traces, metrics and logs across Go and Rust, exported through a Collector to Jaeger/Prometheus/Loki with Grafana as the correlated pane, provisioned as code
**Mode:** mvp
**Requirements:** OBS-01
**Depends on:** Phase 6
**Canonical refs:** `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` — governs Phases 6, 6.1, 6.2, 6.3 and 6.4 (D-77). Do not re-run discussion; this file is the canonical decision record.
**Success Criteria:**

1. The OTel trace ID is authoritative; `correlation_id` is retained as a span attribute for continuity (D-27). Inbound W3C `traceparent` is honoured when present, otherwise the gateway starts the root (D-28).
2. Every RAG query produces roughly 8–10 spans: the five existing node spans plus a child span per real external call (embedding request, dense LanceDB search, BM25 query, graph Cypher traversal, and each LLM attempt) (D-29). The root span covers the whole SSE stream and carries the terminal outcome (`answer_basis`, degraded flags) as attributes plus span status (D-31).
3. Ingestion is fully traced end to end: upload → admission → chunking → embedding → staging write → graph extraction → index rebuild (D-30), making Phase 6.1's rebuild-and-swap observable.
4. Metrics ship with a real backend — a RAG-quality operational set (query latency by outcome, retrieval-path failure counter, degraded-answer counter by `answer_basis`, citation repair/drop counter, generation retry counter, evidence-set size histogram, ingest document/chunk counters, index rebuild duration and corpus generation gauge) (D-33, D-35).
5. Both services export OTLP to an OpenTelemetry Collector, fanning out to Jaeger (traces), Prometheus (metrics), and Loki (logs), correlated in Grafana by `trace_id` (D-34).
6. `docker-compose` exposes a core profile (PostgreSQL only) and an `observability` profile (Collector, Jaeger, Prometheus, Loki, Grafana); Collector pipelines, scrape/log config, and Grafana datasources/dashboards are committed and auto-provisioned with no manual UI state, dashboards generated from typed code (D-39, D-40).
7. A missing collector degrades silently to stdout in both services — telemetry initialization never fails the service (D-38). Service identity (`service.name`, `service.version`, `deployment.environment`) is set via the standard resource detector (D-43).
8. Phase 05 D-30's workflow metadata lands both as span attributes and as additive `WorkflowCompletedEvent` protobuf fields (D-41).

**Plans:** 9/12 plans complete

Plans:
**Wave 1** *(tracer — the foundation every later plan expands)*

- [x] 06.2-01-PLAN.md — Tracer slice: W3C propagation across HTTP → gRPC → the Rust workflow, all three signal providers in both services, one real metric and one correlated log site, fail-closed telemetry config (D-84), and a Collector/Jaeger compose profile (D-27, D-28, D-32, D-36, D-37, D-38, D-43, D-84 / OBS-01).

**Wave 2** *(parallel — engine source vs. deployment files, no shared files)*

- [x] 06.2-02-PLAN.md — Query-path span surface: five runner-owned node spans, leaf spans at every real external call including one per LLM attempt, and the SSE root span's terminal outcome and status (D-29, D-31, D-42 / OBS-01).
- [x] 06.2-03-PLAN.md — Observability stack as code: Prometheus, Loki and Grafana on the `observability` profile, file-provisioned datasources with trace-to-log correlation, and a typed Foundation SDK dashboard generator with its committed output (D-34, D-39, D-40 / OBS-01).

**Wave 3**

- [x] 06.2-04-PLAN.md — Ingestion trace end to end: one trace per document carried across the ingestion queue through graph extraction, leaf spans at every external call that extraction makes (one per LLM attempt, the graph read, the entity-name embedding, the graph write), plus an `index_rebuild` span linked to every coalesced triggering document (D-30 / OBS-01).

**Wave 4**

- [x] 06.2-05-PLAN.md — The ten D-35 RAG-operational instruments with structurally bounded dimensions, a numeric corpus-generation gauge, and a test proving every committed dashboard panel resolves (D-33, D-35, D-42 / OBS-01).

**Wave 5**

- [x] 06.2-06-PLAN.md — Log correlation expanded across every request-owned site in both services, and D-41's workflow metadata populated in both places from one enumerated `degraded_mode` derivation (D-36, D-41, D-31 / OBS-01).

**Wave 6** *(gap closure — 08 engine vs 09 gateway; no shared files)*

- [x] 06.2-08-PLAN.md — Close CR-03: gen_ai.request.model from embedder.model_id() and Generator::model_id() (D-42 / OBS-01).
- [x] 06.2-09-PLAN.md — Close CR-04: gateway OTLP exporters honor https TLS vs http insecure; named WithInsecure grep gate; COVERAGE.md TLS row (D-84 / OBS-01).

**Wave 7** *(gap closure — after 08 so engine-test-targets.sh does not compile a half-edited crate)*

- [x] 06.2-07-PLAN.md — Close CR-02/CR-01: Collector prometheus exporter without extra prefix, live :8889 all-dashboard-stem round-trip (including ms histograms) on the compose-pinned Collector image, gitignore dashboard_gen binaries, scrape-derived 06.2-03-SUMMARY rule, re-own BLOCKING manual checks (D-34, D-40 / OBS-01).

**Wave 8** *(gap closure — UAT round 2, G-06.2-1; serialized after Wave 9/10's shared-file plans, see below)*

- [ ] 06.2-10-PLAN.md — Close G-06.2-1: Grafana trace-to-logs correlation — remove the unresolvable `trace_id` tag mapping from `tracesToLogsV2`, retain `filterByTraceID` (D-34, D-40 / OBS-01).

**Wave 9** *(gap closure — G-06.2-2; depends on 06.2-10, shares `telemetry_metrics.rs`/`engine-test-targets.sh`/VALIDATION.md with Waves 8 and 10, so serialized rather than parallel)*

- [ ] 06.2-11-PLAN.md — Close G-06.2-2: Operations dashboard Panel 1 latency fix — `histogram_quantile` p95 duration instead of a throughput rate, regenerated committed dashboard JSON (D-35, D-40 / OBS-01).

**Wave 10** *(gap closure — G-06.2-4; depends on 06.2-01, 06.2-09, 06.2-11, same shared-file serialization reason as Wave 9)*

- [ ] 06.2-12-PLAN.md — Close G-06.2-4: bounded OTel diagnostics suppression in Go (`otel.SetErrorHandler`) and Rust (`tracing-subscriber` layer filter) telemetry init — degrade silently to stdout on Collector outage without unbounded stderr spam (D-38 / OBS-01).

### Phase 6.3: Evaluation Harness, Corpora and Recorded Run (OBS-02, OBS-04) (INSERTED)

**Goal:** Build the Python evaluation harness against MultiHop-RAG, run and commit a scored evaluation report with deterministic and LLM-judged metrics
**Mode:** mvp
**Requirements:** OBS-02, OBS-04
**Depends on:** Phase 6
**Canonical refs:** `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` — governs Phases 6, 6.1, 6.2, 6.3 and 6.4 (D-77). Do not re-run discussion; this file is the canonical decision record.
**Success Criteria:**

1. MultiHop-RAG (~500 sampled questions, fixed committed seed) is the primary benchmark; GraphRAG-Bench (Novel) is an optional graph-showcase supplement on the same corpus-agnostic harness — only MultiHop-RAG results are required for closure (D-44, D-53, D-59).
2. The harness is Python, drives the gateway's `/rag/query` HTTP/SSE endpoint like a real client, and lives in a dedicated `eval/` directory with `pyproject.toml` plus a lockfile run via `uv` (D-48, D-49). The SSE client asserts the wire contract (terminal event, exactly one `final_answer`, notices attached) (D-65).
3. Deterministic metrics (retrieval recall@k, context precision, MRR/nDCG, answer EM/F1) run over the full set with no LLM and require no API key; LLM-as-judge scores only groundedness and faithfulness, using a judge model pinned distinct from the generator, temperature 0, with judgements cached by `(question, answer, evidence)` hash (D-50, D-52, D-62).
4. Graph capability is measured by ablation — the same question set run with graph context on and off via a per-request flag on one running engine, scored as its own dimension, kept distinct from the model-only opt-in (D-46, D-47).
5. OBS-04's placeholder dimension registers and returns an explicit `skipped` status with a reason — never a fabricated number (D-51).
6. The eval store is fully isolated (its own LanceDB path and PostgreSQL schema via the existing Atlas migrations), seeded once through the real ingestion path over a documented reduced document subset, reseed is an explicit command (D-55, D-56, D-57).
7. The harness preflights gateway/engine reachability, eval-store seed state and generation, and API key presence for judged dimensions, failing fast with guidance rather than 40 minutes in (D-64).
8. Output is a committed Markdown report plus machine-readable JSON, advisory only (no pass/fail gate), reported per corpus with run metadata (judge model, sample size, date, index generation, commit SHA) and no cross-corpus aggregate (D-54, D-60, D-61).
9. At least one automated test exercises the shipped generation model's (`dots-studio/dots-3-note-preview:free`) structured-output preflight, closing Phase 05's WARN-NEW-01 (D-63).

### Phase 6.4: Docs Suite, Verified Quickstart and v1 Milestone Closure (OBS-03) (INSERTED)

**Goal:** Ship the README/docs design-narrative suite with a verified quickstart, promote the un-closed debt backlog, and close out the v1 milestone
**Mode:** mvp
**Requirements:** OBS-03
**Depends on:** Phase 6
**Canonical refs:** `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` — governs Phases 6, 6.1, 6.2, 6.3 and 6.4 (D-77). Do not re-run discussion; this file is the canonical decision record.
**Success Criteria:**

1. The README stays the readable front door (story, architecture sketch, quickstart, headline results, links); `docs/` gains a design narrative (alternatives-considered, linking ADRs), an observability walkthrough following one real query end to end, and an evaluation methodology + results page — each written after the implementation it documents (D-66, D-67, D-72, D-73).
2. The quickstart is executable and verified end-to-end on a clean checkout — compose up, migrate, `cargo run`/`go run`, ingest, query, open Jaeger and Grafana, run the eval — on both Windows native and Linux via WSL (D-68).
3. Four Mermaid diagrams (system/deployment topology, query-path state machine including degraded branches, ingestion pipeline through index rebuild-and-swap, telemetry topology) plus three captured artifacts (Jaeger trace screenshot, Grafana dashboard, eval-results chart) are present (D-69).
4. The README carries an honest limitations section: local-only by design (no auth/TLS/quotas, DEBT-CR-04's trigger conditions), the open debt themes linked to their backlog phases, and what the eval does and does not measure, including the unmeasured evidence-vs-priors claim (D-71).
5. The notice-code vocabulary (`NO_EVIDENCE`, `GRAPH_DEGRADED`, `GRAPH_TIMEOUT`, `RETRIEVAL_DEGRADED`, `CITATION_REPAIRED`/`CITATION_DROPPED`, `MODEL_ONLY`, `GRAPH_UNAVAILABLE`, index-staleness codes) is documented in `docs/` as part of the API contract (D-76).
6. The 18 un-selected `DEBT-*` items are promoted to five themed `999.x` backlog phases in ROADMAP.md (Security & transport hardening; Ingestion & staging robustness; Config & settings hygiene; API contract & DX; Test & evidence hygiene), each phase listing its member IDs, cross-linked to the source `deferred-items.md` files (D-02, D-03, D-04).
7. v1 milestone closure — requirements reconciliation and the debt ledger — lands as a Phase 6.4 task rather than a separate post-phase workflow (D-86).

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

### Phase 999.11: Add compatibility of using a local sglang endpoint as inference api instead of just openrouter (BACKLOG)

**Goal:** Add compatibility for using a local SGLang endpoint as an inference API alongside or instead of OpenRouter.
**Requirements:** TBD
**Plans:** 0 plans

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

