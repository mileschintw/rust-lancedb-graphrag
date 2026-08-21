---
gsd_state_version: 1.0
milestone: v1.0
current_phase: 6
current_phase_name: observability-evaluation-polish
current_plan: Not started
status: executing
stopped_at: Phase 6 context gathered (governs 6, 6.1, 6.2, 6.3, 6.4)
last_updated: "2026-08-21T01:13:56.025Z"
state_head: faf5d30ec35ca845bc5264f6265e2df05783b7e3
progress:
  total_phases: 11
  completed_phases: 6
  total_plans: 101
  completed_plans: 89
milestone_name: milestone
---

# Project State

## Current Status

- Phase 1 completed successfully.
- Phase 2 completed (force-closed per ADR-02-004; all open gaps marked as technical debt deferred to Phase 6 final hardening).
- Phase 3 completed (force-closed per ADR-03-003; 23/23 plans executed; residual verification gaps recorded as technical debt DEBT-P3-* deferred to Phase 6 final hardening; next phase = Phase 4).
- Phase 4 completed (lance-graph/lancedb compatibility spike only, per ROADMAP's "Deferred target" note; UAT 3/3 passed, SECURITY.md verified threats_open: 0; full extraction/storage/query-traversal implementation deferred to Phase 04.1, not yet created; next phase = Phase 5).
- Phase 04.1 Plan 03 executed: concurrent bounded extraction, WR-01 IPC multi-batch bridge fix, extraction retries with confidence validation, and re-ingestion rollback proof.
- Phase 04.1 Plan 04 executed: QueryGraph RPC as a Cypher-constrained induced-neighborhood query with bounded/validated input, including a fix for a pre-existing fetch_neighborhood bidirectional-BFS edge-duplication bug.
- Phase 05 Wave 10 Plan 05-14 executed: closed `NodeKind` enum with 5 variants, exhaustive typed runner dispatch, early 9-variant admission rejection, and focused dispatch tests.
- Phase 05 Wave 11 Plan 05-17 executed: additive protobuf fields (RetrievalSnapshot tags 10/11, WorkflowCompletedEvent tag 6) and synchronized Rust/Go bindings with protected module glue.
- Phase 05 Wave 12 Plan 05-23 executed: repaired exhaustive Rust RetrievalSnapshot and WorkflowCompletedEvent message literals, verified clean compilation, and proved additive tags 10/11 round-trip fidelity.
- Phase 05 Wave 13 Plan 05-18 executed: split Phase 5 workflow tests into library unit-test target (`workflow_phase5`) and binary-owned production module (`workflow_phase5_production`), introduced `Bm25IndexStore` alias, migrated 18 BM25 test constructions, and verified library execution and binary compilation.
- Phase 05 Wave 17 Plan 05-19 executed: preserved accumulated notices on failure terminal events through Rust runner and Go raw SSE stream while keeping failure terminals answer-free.
- Phase 05 Wave 17 Plan 05-24 executed: closed resolved cross-variant RRF contract with two-pass fusion (`fuse_candidates` in loop, `fuse_cross_variant_candidates` merge pass), retired `fuse_variant_candidates`, and verified exact scoring and deterministic tie resolution.
- Phase 05 Wave 18 Plan 05-22 executed: completed production typed graph-fact handoff and end-to-end query_rag workflow tests.
- Phase 05 Wave 19 Plan 05-20 executed: separated capability preflight from the GenerateAnswer node timer and proved the two-attempt retry path fits the 65s node timer with paused-clock timing proofs.
- Phase 05 Wave 20 Plan 05-11 executed: proved and hardened real engine-to-gateway SSE stream across 5-node lifecycle and graph fixtures, verified client cancellation propagation, structured stream error framing, and lossless checkpoint persistence under backpressure.
- Phase 05 post-execution gates RE-RUN (2026-08-19) after gap-closure plans 05-25 and 05-26 landed: all 26 plans complete; ROADMAP plan checkboxes and plan counts reconciled for 05-25/05-26 (commit e6e153f).
  - Code review REFRESHED at HEAD (05-REVIEW.md, standard depth, 37 of 48 scoped files, commit 721485c): 1 Critical, 15 Warnings, 18 Info (34 total), superseding the stale 2026-08-18T09:43 report of 27. Every finding re-derived at HEAD, not carried forward. Prior WR-05 (`x-lancet-*` trailer regression) confirmed RESOLVED by edaf907. `engine/src/db/mod.rs` + `db/tests.rs` newly in scope (05-25). 10 new findings, incl. WR-12 (runner.rs capacity() TOCTOU, coupled to CR-01) and WR-13/IN-15 (05-25's remediation hint is appended after multi-KB schema dumps; its test asserts only `contains`, so it does not protect the property the plan meant to deliver). 11 files excluded (generated code + large test files), recorded verbatim in the report.
  - Regression gate PASSED: `cargo test --manifest-path engine/Cargo.toml --locked` 281 passed / 0 failed / 1 ignored, exit 0; `cd gateway && go test ./...` 54 passed / 0 failed / 11 SKIPPED, exit 0. The 11 skips are ALL `TEST_DATABASE_URL`-gated and could NOT be run here (Docker Desktop not running; nothing listening on 127.0.0.1:5432) — recorded explicitly, NOT counted as passes. 05-26's actual risk surface is not env-gated and DID run: TestRAGQueryCrossRuntime (3.09s) and TestRAGQueryClientDisconnectCancelsRustWorkflow (2.22s) both pass.
  - Verification REFRESHED (05-VERIFICATION.md, commit e604f5f): 4/5 roadmap success criteria verified, 1 present-but-behavior-unverified. Score moved 5/5 -> 4/5 NOT from a regression but from honest re-grading — the prior pass counted three Postgres-backed checkpoint tests as PASS against a container that is no longer up. SC4 splits: capture half provable from source (CHECKPOINT_SNAPSHOT_KEYS, 19 keys); persistence half (FIFO drain, cancellation atomicity) has no fresh evidence. SC3 stands — CR-01/WR-12's precondition re-derived as unreachable at the current 100-slot buffer depth. Requirements traceability clean: ORCH-01..05 all [x], GATE-01/02 formalized, GATE-03 removed as unbacked, no orphans. `regressions: []`, `gaps_remaining: []`.
  - G-05-1 CLOSED IN CODE by 05-25 + 05-26 (Blocker A verified empirically — inspect_lancedb.exe passes open_and_validate against ./data/lancedb; Blocker B closed at main.rs:661-668). Closing the blockers UNBLOCKS UAT Test 1; it does not constitute it. The live OpenRouter run still requires a real API key and a human.
  - New warning the plans did not flag (WARN-NEW-01): 05-26's decoupling pins the real-engine tests to `openai/gpt-4o-mini` while production ships `dots-studio/dots-3-note-preview:free`, so the structured-output capability preflight (openrouter.rs:425-434) is now exercised by NO automated test.
  - 05-UAT.md MERGED, not regenerated: Tests 2/3/4 and their three recorded human resolutions preserved verbatim; Test 1 reopened as `pending` (blockers closed) with its prior failure kept on the record; Tests 5 (Postgres-gated suite) and 6 (CR-01/WR-12 disposition) added. Now 6 total / 3 passed / 3 pending.
  - Security gate: `workflow.security_enforcement` is active and NO 05-SECURITY.md exists — run `/gsd-secure-phase 5` before advancing.
  - Phase NOT marked complete: `phase.complete` is gated on verification returning `passed`; it returns `human_needed`. Next: `/gsd-verify-work 5`.
- Phase 05 tail gates RE-RUN AGAIN (2026-08-19T07:20) at HEAD `bb58a60`, after the 16 remediation commits (CR-01 + WR-01..WR-15) and gap-closure plan 05-27 landed. All 27 plans complete. The `--gaps` token in the invocation is a `/gsd-plan-phase` flag, not an execute-phase filter; no filter was applied and `incomplete_count` was 0, so this run consisted only of the tail gates.
  - Code review REFRESHED at HEAD (05-REVIEW.md, standard depth, commit 25d4fda): **0 Critical / 13 Warnings / 24 Info (37 total)**, 33 of 49 declared files reviewed line-by-line. `critical: 0` is a real result — prior CR-01 verified closed at `runner.rs:342-351`/`:383-393`. Scope note recorded on the record: the raw git diff from the phase base surfaced 2,051 changed paths, of which 2,002 are vendored GSD runtime installs (`.codex/` 730, `.claude/` 723, `.agents/` 549) — tooling, not Phase 05 source — excluded by the orchestrator before the reviewer was spawned.
  - Fix verification of the 16 claimed-closed findings: **9 CLOSED, 4 PARTIAL, 1 NOT CLOSED, 2 REGRESSED.** Not auto-fixed — advisory per the workflow. Notable: prior WR-12 REGRESSED (`5354d1e` removed the `capacity()` TOCTOU but added a new un-cancellable `reserve().await` at `runner.rs:167`); prior WR-01 CLOSED but introduced an exit-code regression (gateway bind failure now exits 0, `main.go:1094-1098`); prior WR-09 NOT CLOSED (`wrap_next_event` untouched, ordinals still burned); prior WR-13 NOT CLOSED (`db/tests.rs:107` byte-identical, still `contains`-only); prior WR-14 NOT CLOSED (guard unreachable in the shipped config).
  - Regression gate PASSED with MORE evidence than the prior run. `cargo test --manifest-path engine/Cargo.toml --locked` → **285 passed / 0 failed / 1 ignored**, exit 0 (was 281). `cd gateway && go test ./...` run with `TEST_DATABASE_URL` exported → **65 passed / 0 failed / 0 SKIPPED**, exit 0 (was 54 passed / 11 skipped). `lancet-postgres` (postgres:16-alpine) WAS running this time with the `workflow_checkpoints` schema applied, so all 11 previously-unrunnable Postgres tests actually ran and passed — including `TestWorkflowCheckpointPersistence`, `TestWorkflowCheckpointCancellationAtomicity` and `TestWorkflowCheckpointPendingDrainAndPersistence`. The tests create and drop isolated schemas; `public` was not mutated.
  - Verification REFRESHED (05-VERIFICATION.md, commit e0ea391): **5/5 roadmap success criteria verified**, `behavior_unverified: 0`. SC4 moved 4/5 → 5/5 not by relaxing the bar but because the FIFO-drain/ordering evidence the prior pass lacked now exists: `TestWorkflowCheckpointPendingDrainAndPersistence` (`gateway/main_test.go:3795-3860`) asserts exactly 10 rows, contiguous `sequence_ordinal` 1..10, FIFO-consistent `node_name` order, `json.Valid` on every snapshot, and all 19 snapshot keys — against a real database at this HEAD.
  - Two 05-REVIEW.md findings did NOT survive the verifier's re-derivation, both routing/severity disagreements rather than factual ones: prior WR-03's unenforced generation retry-budget invariant (the violating value at `config/config.verify.toml:19` is an intentional test fixture that `workflow_phase5_config_verify_generation_timeout` asserts on; the shipped `config.toml` satisfies the invariant), and prior WR-05's residual `?`-masking in `run_inline_prompt_generation_remainder` (no production consumer — all 4 call sites are in `tests/workflow_phase5.rs`; production takes `run_workflow` at `main.rs:1914`). Both retained as debt.
  - Two regressions recorded, neither breaking a success criterion: REG-01 (`runner.rs:161-170`, from `5354d1e`) and REG-02 (`gateway/main.go:1094-1098`, from `e8982d0`, where the naive `logger.Fatal` fix would reintroduce the defect `e8982d0` closed). Dispositions deferred to UAT Tests 7 and 8.
  - 05-UAT.md MERGED, not regenerated — verified by diff: only 4 metadata lines changed, all 6 prior tests and their human-recorded resolutions preserved verbatim, `## Gaps` G-05-1 block intact. Tests 7-10 added. Now **10 total / 5 passed / 1 issue / 4 pending**. Test 1 stays `result: issue` but is now UNBLOCKED — `MAX_MODELS_METADATA_BODY_BYTES = 10MB` (`engine/src/client/mod.rs:16`, applied at `openrouter.rs:386-388`) closes G-05-1's root cause in code; the live run still needs a real API key and a human.
  - TRACE-01 RECONCILED: ROADMAP.md said "26/26" and its checkbox list ended at 05-26 while `05-27-PLAN.md` existed with a SUMMARY and landed `e831be3` — the commit closing the gap the roadmap tracks. Corrected to 27/27 with 05-27 added to both the plan list and a new Wave 22.
  - Security gate UNCHANGED: `workflow.security_enforcement` is active and NO 05-SECURITY.md exists — `/gsd-secure-phase 5` still required before advancing.
  - Phase still NOT marked complete: verification returns `human_needed`, not `passed`. Next: `/gsd-verify-work 5`.
- Phase 05 UAT completed (2026-08-19) via `/gsd-verify-work 5`, resuming the in-flight session. G-05-1 reconciled `resolved` (root causes closed in code by 05-25/05-26/05-27). Test 1 re-run live against real OpenRouter: full 5-node frame sequence, no `stream_error`, citations grounded in the local dev LanceDB store's fixture data (fixture content, not a real corpus — pipeline mechanics fully proven). Tests 7-10 (judgment-tier dispositions) resolved: buffer-depth invariant re-accepted at the post-`5354d1e` code site (Test 7); gateway bind-failure exit-code regression found ALREADY fixed by `fe83e71` and verified empirically (`exit=1`) (Test 8); terminal-event suppression on FinalAnswer failure found ALREADY fixed by `0c96720a` (Test 9); checkpoint sequence-ordinal burning on failed delivery accepted as debt, `wrap_next_event` found already lazy via the same `0c96720a` refactor (Test 10). Final: **10/10 passed, 0 issues**. `05-SECURITY.md` confirmed present with `threats_open: 0` (security gate clear). Verification canonicalized `human_needed` → `passed`. Phase 05 marked complete via `phase.complete`; PROJECT.md evolved (4 requirements moved to Validated, 4 new Key Decisions logged); next phase = Phase 6.

## Active Phase

- **Phase:** 6 — Observability, Evaluation & Polish
- **Status:** Ready to execute
- **Current Plan:** Not started
- **Total Plans in Phase:** 12
- **Completed Plans in Phase:** 0
- **Progress:** [░░░░░░░░░░] 0.0%

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
| update-readme-with-all-the-decision-and- | 2026-08-19 | Update README with all decisions and progress to date, preserving personal-side-project/showcase framing and adding AI-collaboration angle | Complete |

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
| Phase 05 P10 | 112m | 2 tasks | 4 files |
| Phase 05 P21 | 7 min | 2 tasks | 2 files |

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
- [Phase 05-17]: Protobuf schema introduces additive RetrievalSnapshot variant fields (tags 10/11) and WorkflowCompletedEvent notices (tag 6) with clean: false Buf protection for hand-written Rust module glue; compile repair is owned by 05-23.
- [Phase 05-23]: Repaired exhaustive Rust message literals across engine/src (retrieve.rs, events.rs, main.rs) with explicit additive field initialization and proved the RetrievalSnapshot wire contract and tag ordering (tags 1..=11) in retrieval::tests.
- [Phase ?]: CheckpointSnapshot in events.rs is the canonical Rust-owned nineteen-field stable JSON contract.
- [Phase ?]: query_embedding is represented by dimension plus a deterministic fixed-size hexadecimal digest, not the raw vector.
- [Phase ?]: WorkflowCompleted carries the accumulated ordered notices so degradation remains visible through terminal failure.

## Session

**Last session:** 2026-08-20T01:01:23.373Z
**Stopped at:** Phase 6 context gathered (governs 6, 6.1, 6.2, 6.3, 6.4)
**Resume file:** .planning/phases/06-observability-evaluation-polish/06-CONTEXT.md

## Accumulated Context

### Roadmap Evolution

- Phase 04.1 inserted after Phase 4: Knowledge Graph Extraction & Query (Full Implementation) (URGENT)
- Phase 6.1 inserted after Phase 6: Phase 6 split into 6, 6.1-6.4 per 06-CONTEXT.md D-77 (scope too large for one phase)
- Phase 6.2 inserted after Phase 6: OTel traces/metrics/logs (OBS-01), split from Phase 6 per 06-CONTEXT.md D-77
- Phase 6.3 inserted after Phase 6: Evaluation harness (OBS-02, OBS-04), split from Phase 6 per 06-CONTEXT.md D-77
- Phase 6.4 inserted after Phase 6: Docs suite + v1 closure (OBS-03), split from Phase 6 per 06-CONTEXT.md D-77
