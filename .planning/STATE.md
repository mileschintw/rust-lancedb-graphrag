---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 5
current_phase_name: State Machine & Workflow Events
current_plan: Not started
status: executing
stopped_at: Phase 5 context gathered
last_updated: "2026-08-12T02:43:59.044Z"
progress:
  total_phases: 6
  completed_phases: 5
  total_plans: 68
  completed_plans: 62
---

# Project State

## Current Status

- Phase 1 completed successfully.
- Phase 2 completed (force-closed per ADR-02-004; all open gaps marked as technical debt deferred to Phase 6 final hardening).
- Phase 3 completed (force-closed per ADR-03-003; 23/23 plans executed; residual verification gaps recorded as technical debt DEBT-P3-* deferred to Phase 6 final hardening; next phase = Phase 4).
- Phase 4 completed (lance-graph/lancedb compatibility spike only, per ROADMAP's "Deferred target" note; UAT 3/3 passed, SECURITY.md verified threats_open: 0; full extraction/storage/query-traversal implementation deferred to Phase 04.1, not yet created; next phase = Phase 5).
- Phase 04.1 Plan 03 executed: concurrent bounded extraction, WR-01 IPC multi-batch bridge fix, extraction retries with confidence validation, and re-ingestion rollback proof.
- Phase 04.1 Plan 04 executed: QueryGraph RPC as a Cypher-constrained induced-neighborhood query with bounded/validated input, including a fix for a pre-existing fetch_neighborhood bidirectional-BFS edge-duplication bug.

## Active Phase

- **Phase:** 5 — State Machine & Workflow Events
- **Status:** Ready to execute
- **Current Plan:** Not started
- **Total Plans in Phase:** 6
- **Progress:** [█████████░] 91%

## Completed Phases

- **Phase 1: Basic Gateway & Rust Engine Ping** (Completed: 2026-07-13)
- **Phase 2: Ingestion, Chunking & Vector Storage** (Completed: 2026-07-30 via ADR-02-004 debt deferral to Phase 6)
- **Phase 3: Hybrid Retrieval & Basic RAG Path** (Completed: 2026-08-05 via ADR-03-003 debt deferral to Phase 6)
- **Phase 4: Knowledge Graph Extraction & Query** (Completed: 2026-08-06 — lance-graph compatibility spike only; full implementation deferred to Phase 04.1)

## Known Issues & Debt

- Accepted ADR `.discussion/decisions/phases/02/2026-07-30-ADR-02-004-all-the-way-to-ship-mvp.md` force-closed Phase 02 to focus on MVP progress across all must-have functions.
- All remaining Phase 02 findings are deferred as technical debt to the final hardening phase (Phase 6):
  - `DEBT-CR-01 / VER-16`: Completed canonical ingestion downgraded to failed after engine restart
  - `DEBT-CR-02`: Rollback failure destroys replay state
  - `DEBT-CR-03`: Failed admission stranded queued without durable reconciliation intent
  - `DEBT-CR-04 / VER-20`: Evidence helper forges human approval when approval flag omitted
  - `DEBT-WR-01 / VER-19`: Test cleanup deletes another process's fixtures and fails full suite
  - `DEBT-WR-02`: Empty uploads become durable failed jobs and misleading 502 response
  - `DEBT-WR-03`: Cross-runtime recovery tests can hang indefinitely on failure
- Accepted ADR `.discussion/decisions/phases/03/2026-08-05-ADR-03-003-all-the-way-to-ship-mvp.md` force-closed Phase 03 to focus on Phase 04 Knowledge Graph progress.
- All remaining Phase 03 findings are deferred as technical debt to the final hardening phase (Phase 6):
  - `DEBT-P3-BODY-BOUND`: Provider body limit bound is post-chunk materialization
  - `DEBT-P3-STAGING-GEN-RACE`: Staging generation RMW max generation allocation race under equal-gen fail-closed
  - `DEBT-P3-STAGING-PHYSICAL-BU`: Delete-fail physical row retention unproven under fault injection
  - `DEBT-P3-CONFIG-DB-PLAINTEXT`: Committed plaintext DB credentials and sslmode=disable local dev defaults
  - `DEBT-CR-04` (extended): Insecure Gateway->Engine gRPC dial on loopback
  - `DEBT-P3-PROVIDER-ENDPOINT-TRUST`: Provider endpoint URL trust and bearer token sending
  - `DEBT-P3-WARN-DX`: Seeder non-idempotence and empty multipart upload ambiguity
  - `DEBT-P3-WARN-API`: Mixed answer basis without conflict notice, NoEvidenceFits mapped to 400, D1 identity gaps
  - `DEBT-P3-WARN-SETTINGS`: Env ignore, scalar vs carrier dual budget, chunk limit saturation
  - `DEBT-P3-WARN-VALIDATE`: Staging reader null checks, non-finite embedding/BM25 boost overflow
  - `DEBT-P3-MODULE-GRAPH`: Dual lib/bin production module graph
- Pre-existing Phase 02 security/resource debt items (`DEBT-CR-04` loopback guardrail, `DEBT-CR-05` pre-admission bounds, `DEBT-BU-01`, `DEBT-BU-02`) remain active and non-blocking until their triggers or Phase 6.
- Pre-existing RAG and graph query stubs remain recorded in the phase deferred-items ledger for Phase 03 and Phase 04.
- Phase 03 does not claim RAG-03 delivery: DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-04, DEBT-RAG-05, and DEBT-RAG-06 remain the source-of-record future hardening contracts; the initial BM25 build/readiness guard is the only lifecycle safeguard retained in the MVP path.
- Phase 04 only closed the `lance-graph`/`lancedb` compatibility unknown via a feature-gated PoC (`engine/src/graph/`, not wired into the default build). DATA-04 (entity/relationship extraction), DATA-05 (full graph query traversal wired into RAG), and RAG-05 (ContextAssemblyStrategy) remain unimplemented against real data — deferred to Phase 04.1.

## Deployment & Environments

- Local PostgreSQL connectivity and Atlas schema application verified for plan 02-01.

## Quick Tasks Completed

| Slug | Date | Description | Status |
|------|------|-------------|--------|
| update-readme-blueprint | 2026-06-19 | Update README.md with GSD planning documents and backlog details | Complete |
| check-backlog-ports | 2026-06-19 | Verify and add missing Port annotations for Phase 999.1, 999.2, and 999.3 in REQUIREMENTS.md and ROADMAP.md | Complete |
| setup-gitignore | 2026-07-12 | Check and make/update a proper git.ignore based on the designed stack | Complete |
| check-dep-updates | 2026-07-14 | Check if dependencies of this project is able to update and keep working, like rust cargo and jaeger image | Complete |
| buf-rust-codegen | 2026-07-14 | Migrate Rust protobuf code generation to Buf v2 with prost and tonic plugins | Complete |

## Performance Metrics

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 02 P01 | 1h 16m | 2 tasks | 21 files |
| Phase 02 P02 | 57m | 2 tasks | 5 files |
| Phase 02 P03 | 1h 25m | 2 tasks | 9 files |
| Phase 02 P04 | 25 min | 2 tasks | 10 files |
| Phase 02 P05 | 35 min | 3 tasks | 9 files |
| Phase 02 P06 | 2h 24m | 3 tasks | 4 files |
| Phase 02 P07 | 58 min | 3 tasks | 9 files |
| Phase 02 P08 | 35 min | 2 tasks | 4 files |
| Phase 02 P09 | 45 min | 2 tasks | 5 files |
| Phase 02 P10 | 24 min | 3 tasks | 0 files |
| Phase 03 P01 | 25min | 2 tasks | 10 files |
| Phase 03 P05 | 30min | 2 tasks | 4 files |
| Phase 03 P10 | 18 min | 2 tasks | 4 files |
| Phase 03 P11 | 35min | 3 tasks | 5 files |
| Phase 03 P12 | 13m | 2 tasks | 5 files |
| Phase 04 P01 | 45min | 3 tasks | 8 files |
| Phase 04.1 P01 | 20min | 2 tasks | 9 files |
| Phase 04.1 P02 | 40min | 3 tasks | 10 files |
| Phase 04.1 P03 | 45min | 3 tasks | 5 files |
| Phase 04.1 P04 | 50min | 2 tasks | 5 files |

## Decisions

- [Phase 02-01]: Reserve bounded Tokio queue capacity before LanceDB persistence so rejected uploads cannot create orphaned raw documents. — Queue exhaustion must reject before consuming durable local storage.
- [Phase 02-01]: Use a shared base TOML plus LANCET_ENV overlays in both runtimes. — Go and Rust need one environment-selection contract.
- [Phase 02-01]: Keep live ingestion state in Arc DashMap while PostgreSQL remains the gateway metadata source. — This is the thinnest viable scaffold for polling before later persistence work.
- [Phase 02-02]: Force JSON uploads through fixed-size chunking. — JSON strings may contain Markdown-like tokens but must remain raw text.
- [Phase 02-02]: Cache o200k_base in OnceLock and estimate tokens before persistence. — Downstream embedding and vector-storage work receives stable per-chunk token counts.
- [Phase 02-03]: Use ~major.minor Cargo requirements for two-component declarations with patch-only updates. — Matches the requested manifest format without permitting automatic minor-version drift.
- [Phase 02-03]: Keep direct Arrow crates on the 58.3 patch line. — LanceDB 0.31 exposes Arrow 58 types; Arrow 59 would create incompatible public types.
- [Phase 02-03]: Fail startup on any LanceDB schema field drift. — Indexing must not proceed against incompatible persisted storage.
- [Phase 02-04]: Keep durable raw-content staging after queue reservation, then let the single worker replace document graph rows. — Preserves queue rejection semantics while making re-ingestion repairable.
- [Phase 02-04]: Persist only completed or failed engine states in PostgreSQL. — Queued and processing remain live engine states until terminal reconciliation.
- [Phase 02-04]: Generate and validate RFC 4122 UUIDv4 document IDs at both runtime boundaries. — Prevents predicate/path injection and keeps gateway/engine IDs compatible.
- [Phase 02-05]: Keep raw admission data in staged_documents until a complete canonical replacement succeeds.
- [Phase 02-05]: Recover a lost conditional terminal update only by re-reading and verifying the winner.
- [Phase 02-06]: Run the final live gate against a dedicated verification LanceDB store so pre-existing schema generations cannot influence acceptance.
- [Phase 02-06]: Preserve only the fresh validated run as canonical verification data and remove stale Phase 02 rows, stores, challenges, and evidence.
- [Phase 02-07]: Capture canonical LanceDB versions before mutation and route every post-snapshot error, including staging cleanup, through one rollback funnel.
- [Phase 02-07]: Use a five-second context.Background compensation timeout so request cancellation cannot strand failed-ingest metadata.
- [Phase 02-07]: Keep all Rust fault fixtures and integrity tests in engine/src/tests.rs, leaving production code with only the standard test-module declaration.
- [Phase 02-08]: Keep REQUEST_TIMEOUT as the single ten-second reqwest builder contract; the test seam may vary endpoint and retries but never the production timeout.
- [Phase 02-08]: Derive inspector identity and integrity verdicts only from filtered durable LanceDB rows, rejecting missing, mixed, duplicate, stale, or non-contiguous state before JSON output.
- [Phase 02-08]: Keep real LanceDB inspector fixtures outside engine/src/bin so Cargo does not discover test-only code as a production binary target.
- [Phase 02]: Run every challenge, evidence, freshness, privacy, and durable-store decision through explicit Python checks under isolated mode.
- [Phase 02]: Copy provider/model/generation/duplicate/stale/continuity facts directly from the Plan 02-08 inspector output; do not attest hardcoded verdicts.
- [Phase 02]: Keep challenge and evidence paths as exact ignored files and remove both only after final current-store reconciliation succeeds.
- [Phase 02]: Keep all fixtures and negative tests in scripts/test_phase02_live_evidence.py; production shell files contain no test-only harness.
- [Phase 02-10]: Final acceptance required the validator exit zero and direct current PostgreSQL/LanceDB comparison before cleanup.
- [Phase 02-10]: Git Bash was used for the unchanged validator because the WSL launcher had incompatible Cargo path semantics.
- [Phase 02-10]: Challenge and evidence artifacts remain exact-ignored and absent after success.
- [Phase 03]: Use NFKC, full Unicode case folding, UAX word boundaries, and identifier subtokens without stemming or stop-word removal.
- [Phase 03]: Compute BM25 document frequency over the complete snapshot while applying normalized metadata filters before candidate limits.
- [Phase 03]: Keep full-precision weighted RRF scores, retain both source ranks and scores, and resolve ties by the D-51 identity key.
- [Phase 03]: Expose reranking through a Send + Sync boxed-future trait with NoOpReranker as the Phase 03 pass-through implementation.
- [Phase 04.1-01]: Restructure entity tables to `entities` (entity_id primary key) and `entity_edges` (document_id indexed), migrating all code and test fixtures to the new schema.
- [Phase 04.1-02]: Wire extract_and_persist_entities into the worker loop, prove end-to-end extraction and graph-fact prompt packing, and reserve 1 evidence chunk for citations.
- [Phase 04.1-03]: Concurrently extract per-chunk entities using buffer_unordered(5) while collecting non-fatal extraction errors without failing document ingestion.
- [Phase 04.1-03]: Decode all batches in IPC streams via DecodeAllBatches in bridge.rs to prevent multi-batch stream truncation across Arrow crate boundaries (WR-01).
- [Phase 04.1-03]: Enforce 2 retries (3 total attempts) with confidence range validation [0.0, 1.0] and log coverage regressions on re-ingestion.
- [Phase 04.1-04]: Fixed a pre-existing fetch_neighborhood bug where bidirectional multi-hop BFS double-counted an edge re-matched from a later hop's frontier; deduplicated by (source, target, relation_type, weight) identity.
- [Phase 04.1-04]: QueryGraph seed_entity_name lookup case-folds via .trim().to_lowercase() (this codebase's D-05 write-time merge convention) over a full table scan, returning Status::not_found on zero matches.

## Session

**Last session:** 2026-08-10T08:15:36.854Z
**Stopped at:** Phase 5 context gathered
**Resume file:** .planning/phases/05-state-machine-workflow-events/05-CONTEXT.md

## Accumulated Context

### Roadmap Evolution

- Phase 04.1 inserted after Phase 4: Knowledge Graph Extraction & Query (Full Implementation) (URGENT)
