# Roadmap: Lancet

## Milestones

- ✅ **v1.0 MVP**: Phases 1-6.4, shipped 2026-10-11. Archive: [`milestones/v1.0-ROADMAP.md`](milestones/v1.0-ROADMAP.md), [`milestones/v1.0-REQUIREMENTS.md`](milestones/v1.0-REQUIREMENTS.md), [`milestones/v1.0-MILESTONE-AUDIT.md`](milestones/v1.0-MILESTONE-AUDIT.md).
- 📋 **v1.1**: not yet planned. Start it with `/gsd-new-milestone`.

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-6.4): SHIPPED 2026-10-11 (override closeout; known gaps in MILESTONES.md)</summary>

- [x] Phase 1: Basic Gateway & Rust Engine Ping (1/1 plans), completed 2026-07-13
- [x] Phase 2: Ingestion, Chunking & Vector Storage (28/28 plans), completed 2026-07-30 (ADR-02-004)
- [x] Phase 3: Hybrid Retrieval & Basic RAG Path (23/23 plans), completed 2026-08-05 (ADR-03-003)
- [x] Phase 4: Knowledge Graph Extraction & Query, spike (1/1 plans), completed 2026-08-06
- [x] Phase 4.1: Knowledge Graph Extraction & Query, full implementation (9/9 plans), completed 2026-08-09
- [x] Phase 5: State Machine & Workflow Events (27/27 plans), completed 2026-08-19
- [x] Phase 6: Observability, Evaluation & Polish (16/16 plans), completed 2026-08-22
- [x] Phase 6.1: Index Rebuild-and-Swap, BU Proofs, CR-04/CR-05 Review (4/4 plans), completed 2026-08-23
- [x] Phase 6.2: OpenTelemetry Traces, Metrics and Logs (12/12 plans), completed 2026-08-28
- [x] Phase 6.3: Evaluation Harness, Corpora and Recorded Run (11/11 plans), completed 2026-09-04
- [x] Phase 6.3.1: Retrieval Citation Collapse and Graph Ablation Fidelity (4/4 plans), completed 2026-09-05
- [x] Phase 6.3.2: Eval Harness Diagnostics, Scored Dimensions and Paired Ablation (6/6 plans), completed 2026-09-06
- [x] Phase 6.3.3: Retrieval Latency Measurement and Timeout Budgets (6/6 plans), completed 2026-09-07
- [x] Phase 6.3.4: Corrected Re-drive, Calibration and Root-Cause Docs (10/10 plans), completed 2026-09-10
- [x] Phase 6.3.4.1: Retrieval Diagnosis, Index Identity and Graph-Yield Repair (34/34 plans), completed 2026-10-06
- [x] Phase 6.3.5: Retrieval Ablation Matrix, Paper-Convention Metrics, Judged Pass (18/18 plans), completed 2026-10-09
- [x] Phase 6.3.6: Quality Levers Measured as Arms (23/23 plans), completed 2026-10-11
- [x] Phase 6.4: Docs Suite, Verified Quickstart and v1 Closure (17/17 plans), completed 2026-10-12

Phase directories stay in `.planning/phases/` by owner decision D-232 (`--no-archive-phases`), so the docs' links keep working.

</details>

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

### Phase 999.2: Reranking (BACKLOG — PROMOTED into Phase 06.3.6 lever 1, 2026-10-06)

**Goal:** A second-pass cross-encoder model to re-score merged retrieval candidates. Promoted on 2026-10-06 (`.planning/research/NEXT-STEPS-2026-10-06.md` §3): the `Reranker` port already exists (RAG-04) and this is the most likely single gain for standard-RAG metrics. Implemented and measured as an arm in Phase 06.3.6; this backlog entry is retained as the pointer.
**Requirements:** RAG-04
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

### Phase 999.6: Knowledge Drift Detection and Node Merging (BACKLOG — lite form PROMOTED into Phase 06.3.6 lever 2, 2026-10-06)

**Goal:** Implement semantic entity resolution and node merging using vector similarity and LLM verification to maintain a self-healing, clean knowledge graph. On 2026-10-06 a lite form (alias merge by normalised name + name-vector similarity behind the existing `EntityResolver` port, DATA-09) was promoted into Phase 06.3.6 as a candidate graph repair, conditional on that phase's no-path diagnosis selecting it. LLM-verified merging and drift detection stay here for v2.
**Requirements:** DATA-09
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

### Phase 999.12: Add pageindex concept implementation as third option of source retrieval (BACKLOG)

**Goal:** Add pageindex concept implementation as third option of source retrieval.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.13: Security and transport hardening (BACKLOG)

**Goal:** Pay down the five security and transport debt items Phase 6 left un-selected: the plaintext Gateway to Engine gRPC dial, provider-endpoint trust before the bearer key is attached, committed database credentials with TLS off, the post-chunk provider body bound, and full-message provider detail in engine logs. Promoted from the Phase 02 and Phase 03 deferred-items records by Phase 6.4 (06-CONTEXT D-02, D-03).
**Requirements:** TBD
**Plans:** 0 plans
**Member IDs:** DEBT-CR-04-EXT, DEBT-P3-PROVIDER-ENDPOINT-TRUST, DEBT-P3-CONFIG-DB-PLAINTEXT, DEBT-P3-BODY-BOUND, DEBT-D1-SAFE-LOG
**Sources:** `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` at `:176` (DEBT-CR-04-EXT, the "Extended with Phase 03 evidence" record), `:187` (DEBT-P3-PROVIDER-ENDPOINT-TRUST), `:165` (DEBT-P3-CONFIG-DB-PLAINTEXT), `:132` (DEBT-P3-BODY-BOUND), `:31` (DEBT-D1-SAFE-LOG)

DEBT-D1-SAFE-LOG's shared-log-sink trigger fired with the Phase 6.2 Loki export; kept in backlog by owner decision (06-CONTEXT D-09). The loopback-bound single-user compose stack is why the multi-tenant risk the debt describes does not apply here.

DEBT-CR-04 is three unrelated issues sharing one label (06-CONTEXT D-03): the plain DEBT-CR-04 (network auth, TLS, quotas; `.planning/phases/02-ingestion-chunking-vector-storage/deferred-items.md:13`) is documented-only per D-06 and is NOT promoted; DEBT-CR-04-EXT (the insecure Gateway to Engine dial) is promoted here; DEBT-CR-04 / VER-20 (the evidence helper that forges human approval) is promoted to Phase 999.17.

The 06.3.6 review finding A-IN-02 (an unvalidated `rerank_endpoint`) is the same class as DEBT-P3-PROVIDER-ENDPOINT-TRUST and lives in Phase 999.19.

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.14: Ingestion and staging robustness (BACKLOG)

**Goal:** Pay down the five ingestion and staging debt items: a completed ingestion downgraded to failed after an engine restart, rollback failure that destroys replay state, a failed admission stranded as queued with no durable reconciliation intent, the staging generation allocation race, and unproven physical row retention after a delete failure. Promoted by Phase 6.4 (06-CONTEXT D-02, D-03).
**Requirements:** TBD
**Plans:** 0 plans
**Member IDs:** DEBT-CR-01, DEBT-CR-02, DEBT-CR-03, DEBT-P3-STAGING-GEN-RACE, DEBT-P3-STAGING-PHYSICAL-BU
**Sources:** `.planning/phases/02-ingestion-chunking-vector-storage/deferred-items.md` at `:59` (DEBT-CR-01 / VER-16), `:63` (DEBT-CR-02), `:67` (DEBT-CR-03); `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` at `:143` (DEBT-P3-STAGING-GEN-RACE), `:154` (DEBT-P3-STAGING-PHYSICAL-BU)

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.15: Config and settings hygiene (BACKLOG)

**Goal:** Pay down the two config and settings debt items: invalid numeric environment overrides that are silently ignored with chunk limits that saturate, and validation gaps for nulls and non-finite values in staging readers, embeddings and BM25 boosts. Promoted by Phase 6.4 (06-CONTEXT D-02, D-03).
**Requirements:** TBD
**Plans:** 0 plans
**Member IDs:** DEBT-P3-WARN-SETTINGS, DEBT-P3-WARN-VALIDATE
**Sources:** `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` at `:220` (DEBT-P3-WARN-SETTINGS), `:231` (DEBT-P3-WARN-VALIDATE)

**Also routed here (06.4 code review, counted separately from the 18 and the 27):** 06.4-REVIEW IN-03, the compiled-in `context_default_enabled = true` that is the opposite of the shipped default (`engine/src/config.rs:204-221`); see `06.4-DEBT-LEDGER.md` table (d).

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.16: API contract and DX (BACKLOG)

**Goal:** Pay down the three API contract and developer-experience debt items: mixed answer basis without conflict disclosure with `NoEvidenceFits` mapped to a client error and missing D1 identity, a non-idempotent seeder with an ambiguous empty upload, and empty uploads that become durable failed jobs with a misleading 502. Promoted by Phase 6.4 (06-CONTEXT D-02, D-03).
**Requirements:** TBD
**Plans:** 0 plans
**Member IDs:** DEBT-P3-WARN-API, DEBT-P3-WARN-DX, DEBT-WR-02
**Sources:** `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` at `:209` (DEBT-P3-WARN-API), `:198` (DEBT-P3-WARN-DX); `.planning/phases/02-ingestion-chunking-vector-storage/deferred-items.md` at `:79` (DEBT-WR-02)

**Also routed here (06.4 owner decision, counted separately from the 18 and the 27):** DEBT-06.4-DEFAULT-RUN, add `default-run = "engine"` to `engine/Cargo.toml` so a plain `cargo run` works (the engine crate has seven binaries; the README uses `--bin engine`; found by plan 06.4-09); see `06.4-DEBT-LEDGER.md` table (d). Also from the v1.0 milestone audit (2026-10-12): G1 (no gateway HTTP route for `QueryGraph`, 04 D-25), G2 (no session table) and G3 (unused `users` table and sqlc queries); see `.planning/milestones/v1.0-MILESTONE-AUDIT.md` and table (d).

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.17: Test and evidence hygiene (BACKLOG)

**Goal:** Pay down the three test and evidence debt items: test cleanup that deletes another process's fixtures, cross-runtime recovery tests that can hang indefinitely on failure, and the evidence helper that forges human approval when the approval flag is omitted. Promoted by Phase 6.4 (06-CONTEXT D-02, D-03).
**Requirements:** TBD
**Plans:** 0 plans
**Member IDs:** DEBT-WR-01, DEBT-WR-03, DEBT-CR-04 / VER-20
**Sources:** `.planning/phases/02-ingestion-chunking-vector-storage/deferred-items.md` at `:75` (DEBT-WR-01 / VER-19), `:83` (DEBT-WR-03), `:71` (DEBT-CR-04 / VER-20)

The plain DEBT-CR-04 (`.planning/phases/02-ingestion-chunking-vector-storage/deferred-items.md:13`, network auth, TLS, quotas) is documented-only per 06-CONTEXT D-06 and is NOT promoted; DEBT-CR-04 / VER-20 above is a different, unrelated item that shares its label.

**Also routed here (06.4 owner decision of 2026-10-11, counted separately from the 18 and the 27):** OB-44, the per-document ingestion span count that 06.2-04 never measured (`06.4-OBLIGATIONS.md`); see `06.4-DEBT-LEDGER.md`, "Also routed to 999.17". Also from the 06.4 phase-end code review (2026-10-12): IN-07, IN-09, IN-10 and IN-11 (doc-drift test blind spots) and the stale "three of the five documents" line in `eval/corpora/ATTRIBUTION.md:33`; see `06.4-DEBT-LEDGER.md` table (d).

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.18: Eval-harness provenance and protocol hardening (06.3.6 review carry-forward) (BACKLOG)

**Goal:** Carry forward the eleven 06.3.6 review findings routed to the eval harness by Phase 6.4 (06.4 D-204, D-229): provenance and protocol checks that trust stored reports or skip silently, and small correctness nits. None sits on the quickstart path or in a 06.4 measurement; each matters before the next paid measurement drive. Counted separately from the 18 promoted DEBT items (SC-6).
**Requirements:** TBD
**Plans:** 0 plans
**Member IDs:** B-WR-01, B-WR-02, B-WR-03, B-WR-04, B-WR-05, B-IN-02, B-IN-03, B-IN-04, B-IN-05, B-IN-06, B-IN-08
**Sources:** `06.3.6-REVIEW.md @ c73dbe3c` (text preserved in `.planning/phases/06.4-docs-suite-verified-quickstart-debt-backlog-promotion-and-v1/research/06.3.6-REVIEW-c73dbe3c.md`); dispositions in `.planning/phases/06.3.6-quality-levers-measured-as-arms-reranker-graph-repair-by-dia/06.3.6-REVIEW-DISPOSITION.md`

**Also routed here (06.4 code review, counted separately from the 18 and the 27):** 06.4-REVIEW IN-01 (`explicit_field_failures` graph-ran evidence is vacuous for `graph_seed_count`), IN-02 (`load_official` re-opens the path after verifying the hash) and IN-05 (the `--preregistered-override` help omits the held-out binding); see `06.4-DEBT-LEDGER.md` table (d). Also from the 06.4 phase-end code review (2026-10-12): IN-08 and IN-12 (`render_forest_plot.py` error handling); see table (d).

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.19: Engine, gateway and test robustness (06.3.6 review carry-forward) (BACKLOG)

**Goal:** Carry forward the sixteen 06.3.6 review findings routed to the engine, gateway and tests by Phase 6.4 (06.4 D-204, D-229): unvalidated rerank endpoint, lever-mask guards, backfill and dump tooling, and test-hygiene findings (coupled or unfalsifiable tests, source-text pins, mutable-config pins). Counted separately from the 18 promoted DEBT items (SC-6).
**Requirements:** TBD
**Plans:** 0 plans
**Member IDs:** A-IN-02, A-IN-03, A-IN-04, A-IN-05, A-IN-06, C-WR-02, C-WR-03, C-WR-04, C-WR-05, C-IN-01, C-IN-02, C-IN-03, C-IN-04, C-IN-05, C-IN-06, C-IN-07
**Sources:** `06.3.6-REVIEW.md @ c73dbe3c` (text preserved in `.planning/phases/06.4-docs-suite-verified-quickstart-debt-backlog-promotion-and-v1/research/06.3.6-REVIEW-c73dbe3c.md`); dispositions in `.planning/phases/06.3.6-quality-levers-measured-as-arms-reranker-graph-repair-by-dia/06.3.6-REVIEW-DISPOSITION.md`

A-IN-02 (an unvalidated `rerank_endpoint` that receives the bearer key) is the same class as DEBT-P3-PROVIDER-ENDPOINT-TRUST in Phase 999.13; it is cross-linked there and not folded into the 18.

**Also routed here (06.4 code review and owner decision, counted separately from the 18 and the 27):** 06.4-REVIEW IN-04 (the engine binds the port while the replay can still block, so a TCP probe sees it up before gRPC serves), 06.4-REVIEW IN-06 (`TestRAGQueryClientDisconnectCancelsRustWorkflow` can reach the real rerank endpoint), and DEBT-06.4-ENGINE-GEN-RETRY, a decision whether the engine should retry a generation that ends with `finish_reason: error` (plan 06.4-09's first stack preflight failed on qs-001 hybrid+graph-v2 with `generation_output_rejected`, `finish_reason` `error` after 2089 completion tokens; the owner-authorised second attempt passed); see `06.4-DEBT-LEDGER.md` table (d).

Plans:

- [ ] TBD (promote with /gsd-review-backlog when ready)
