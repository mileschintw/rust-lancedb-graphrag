---
phase: 05-state-machine-workflow-events
verified: 2026-08-18T00:00:00Z
status: human_needed
score: 5/5 roadmap success criteria verified (plan-level must_haves.truths not separately enumerated — see Scope note)
behavior_unverified: 0
overrides_applied: 0
mode: mvp
unverified_prohibitions: 15 # unverified-prohibition — human review recommended (all judgment-tier, no verification tier declared; verdicts below are NON-AUTHORITATIVE)
re_verification:
  previous_status: gaps_found
  previous_score: 1/5
  previous_verified: 2026-08-13
  note: "The previous verification predated plans 05-08 through 05-24 (landed 2026-08-17). Every success criterion was re-derived from the current codebase at HEAD d84cee2; no prior verdict was carried forward."
  gaps_closed:
    - "SC1 — production `query_rag` now builds and runs the real five-node runner (`build_production_workflow`, main.rs:1523-1609); `execute_inline_query_rag_remainder` deleted in af42b10 (zero repo-wide references)."
    - "SC2 — full event set (node_started/node_completed per node, answer_chunk, final_answer, workflow_completed) now reaches an HTTP SSE client across a real Rust engine process; proven by TestRAGQueryCrossRuntime."
    - "SC3 — `EngineSettings` now has a `workflow: WorkflowConfigSettings` field (main.rs:289); all seven `[engine.workflow]` keys parse and reach `WorkflowRunner::with_timeouts` (main.rs:1562-1568). Timeout firing proven with real wall-clock timing; retry and cancellation proven."
    - "SC3 — client-disconnect cancellation now works: `CancelOnDropStream` (main.rs:1774-1794) cancels the workflow token on stream drop; proven end-to-end by TestRAGQueryClientDisconnectCancelsRustWorkflow."
    - "SC4 — `events::checkpoint` now serializes the full accumulated WorkflowContext (19 stable keys, `CHECKPOINT_SNAPSHOT_KEYS`), and the production RetrieveHybridNode populates `vector_results`/`bm25_results`/`final_candidates` (retrieve.rs:84,116,176)."
    - "SC4 — gateway no longer discards DispatchPending; `RetainPending` is called on the pending envelope (main.go:800-805)."
    - "Traceability — 05-02 and 05-03 requirement-ID drift formally corrected by 05-12-TRACEABILITY-ERRATA.md."
  gaps_remaining: []
  regressions:
    - id: WR-05
      truth: "Engine emits the `x-lancet-*` gRPC trailers the gateway reads for pre-stream error identity."
      introduced_by: "af42b10 (plan 05-22, 2026-08-17) — deleted `fn d1_status` from engine/src/main.rs along with the inline remainder."
      detail: "Repo-wide, the only Rust code that inserts `x-lancet-session-id` / `x-lancet-correlation-id` / `x-lancet-error-kind` is a test double at engine/src/tests.rs:2493-2500. gateway/main.go:774-782 (`handlePreStreamError`) still reads all three, and gateway/main_test.go:1089-1241 proves the Go reader against a fake engine that still sets them. The passing Go suite therefore gives false assurance on a contract the real engine no longer honors."
      affects_success_criteria: false
      rationale: "The trailers feed `handlePreStreamError` only — the pre-stream gRPC error path. They carry no workflow events. SC2 is proven independently and end-to-end by TestRAGQueryCrossRuntime over real SSE. Degradation is graceful (headers simply absent; InvalidArgument still maps to 400)."
      escalation: "Developer decision required: restore trailer emission in the engine's `query_rag` error paths, OR delete the gateway reader plus its test doubles. Leaving both halves is the only outcome that keeps a green suite over a broken contract."
gaps: []
deferred: []
warnings:
  - id: CR-01
    title: "run_node cancels before emitting NodeFailed — latent, precondition unreachable today"
    file: "engine/src/workflow/runner.rs:348-356, 361-371, 391-398"
    detail: "On both the preparation-failure and timeout branches, `cancel.cancel()` runs BEFORE the corresponding NodeFailed is emitted. `send_event` -> `flush_pending_checkpoints`/`send_envelope` use a biased select whose first arm is `cancel.cancelled()`, but that arm is only reachable when `self.tx.capacity() == 0`."
    verifier_arithmetic: "The sink channel is per-request `mpsc::channel(100)` (main.rs:1798). Maximum events for one workflow = 5 nodes x (node_started + node_completed + checkpoint) = 15, + 1 answer_chunk on GenerateAnswer = 16, + terminal (final_answer + terminal_success checkpoint + workflow_completed) = 19. 19 < 100, so `capacity()` can never reach 0 and the biased cancellation arm is never entered. NodeFailed and WorkflowCompleted are therefore never dropped, and a Timeout is never masked as Cancelled."
    corroborating_test: "workflow_phase5_config_verify_generation_timeout (engine/src/tests/workflow_phase5_production.rs:569) independently observes NodeFailed{category=Timeout} delivered after `cancel.cancel()` has already fired."
    severity: warning
    becomes_live_if: "per-token streaming AnswerChunks are added (planned 999.x), the 100-slot buffer is reduced, or a sink is shared across workflows."
    recommended_fix: "Emit the failure event first, then cancel; never let a delivery failure replace the node error."
  - id: WR-01
    title: "dispatcher.Close() is unreachable — buffered checkpoints lost at shutdown"
    file: "gateway/main.go:1076, 1087-1089"
    detail: "`defer dispatcher.Close()` is registered in main(), but main() only exits via `logger.Fatal` (os.Exit, skips defers) or a ListenAndServe return; nothing installs a signal handler or calls server.Shutdown. On SIGINT the process dies without draining. Bounded loss (<= the 1-slot channel + 4-slot overflow) of in-flight checkpoints; already-dispatched rows are durable."
    severity: warning
  - id: WR-03
    title: "WorkflowSettings::validate() enforces only non-zero; no cross-field invariants"
    file: "engine/src/main.rs:257-282, config/config.verify.toml:9,18"
    detail: "config.verify.toml pairs generation_node_timeout_ms=7000 with generation_timeout_secs=30, so the node deadline expires before even a single provider attempt can complete — the 2-attempt retry design cannot execute under that config. This is intentional for the verify overlay (it is exactly what workflow_phase5_config_verify_generation_timeout asserts), but nothing prevents the same shape from being committed to config.toml. The shipped config.toml (65000 vs 30s x2 = 60s) is consistent."
    severity: warning
  - id: WR-04
    title: "Every non-2xx chat response classified ProviderError, so 401/400 is retried"
    file: "engine/src/generation/openrouter.rs"
    detail: "GenerateAnswerNode retries on GenerationErrorKind::ProviderError (generate.rs:116-117). A permanent 401/400 therefore burns a second full provider timeout before failing."
    severity: warning
  - id: WR-06
    title: "run_inline_prompt_generation_remainder is exported production API reachable only from tests"
    file: "engine/src/workflow/mod.rs:164-259"
    detail: "Verified independently: exactly 3 call sites, all in engine/src/tests/workflow_phase5.rs (1520, 1606, 1717), each via `WorkflowRunner::run_tracer` — which itself has no non-test call site. The function passes `evidence: vec![]` to the generator (mod.rs:200-203), so it can only produce a grounded answer against a fake. Dead in production, but `pub` and thus a trap for a future caller. Recommend removal or `#[cfg(test)]`."
    severity: warning
  - id: TRACE-GATE
    title: "05-11-SUMMARY closes three requirement IDs that do not exist"
    file: ".planning/phases/05-state-machine-workflow-events/05-11-SUMMARY.md"
    detail: "Declares `requirements-completed: [ORCH-01, ORCH-02, ORCH-03, ORCH-04, GATE-01, GATE-02, GATE-03]`. Its PLAN declares [ORCH-02, ORCH-03, ORCH-04]. GATE-01/02/03 return zero hits in .planning/REQUIREMENTS.md. Unlike the 05-02 and 05-03 phantom IDs, this one is NOT covered by 05-12-TRACEABILITY-ERRATA.md — 05-11 executed in Wave 18, after the errata was authored."
    also_uncorrected:
      - "05-06-SUMMARY.md closes [ORCH-01, ORCH-04] while its PLAN declares [ORCH-02, ORCH-03, ORCH-04] — it closes one ID the plan never declared and drops two it did. Errata section 2 corrects 05-06's narrative only, not its IDs."
      - "Ten SUMMARYs carry no `requirements-completed` field at all: 05-13, 05-14, 05-15, 05-16, 05-17, 05-18, 05-19, 05-22, 05-23, 05-24. Requirement closure for those plans is inferable only from their PLAN declarations and is never asserted by the SUMMARY."
    severity: warning
  - id: TRACE-CHECKBOX
    title: "REQUIREMENTS.md understates completion"
    file: ".planning/REQUIREMENTS.md:32,36"
    detail: "ORCH-01 and ORCH-05 are still `[ ]` while ORCH-02/03/04 are `[x]`. Both are satisfied with codebase evidence (see Requirements Coverage). Bookkeeping only."
    severity: warning
  - id: IN-01
    title: "SUMMARY overclaim — engine/src/workflow/context.rs never existed"
    file: ".planning/phases/05-state-machine-workflow-events/05-01-SUMMARY.md"
    detail: "Listed under key-files.created. The file does not exist and has no git history. `pub struct WorkflowContext` lives at engine/src/workflow/mod.rs:32 and is complete (19 fields), fully populated on the production path. Benign documentation overclaim; no missing deliverable."
    severity: info
behavior_unverified_items: []
human_verification:
  - test: "Run one real query against the live OpenRouter provider end-to-end (engine + gateway + curl on /rag/query with a real OPENROUTER_API_KEY), and watch the SSE frame sequence."
    expected: "node_started/node_completed for all five nodes, one answer_chunk, one final_answer, one workflow_completed, no stream_error; the answer is grounded with real citations."
    why_human: "Every automated proof of the pipeline — including the decisive TestRAGQueryCrossRuntime — substitutes an httptest mock for OpenRouter's /embeddings, /models, and /chat/completions. The one live-provider test in the repo (generation::tests::openrouter_structured_output_smoke) is `#[ignore]` and did not run. Real provider latency, streaming semantics, and structured-output conformance have never been exercised against this state machine."
  - test: "Decide the disposition of the WR-05 `x-lancet-*` trailer regression, then apply it."
    expected: "Either engine/src/main.rs::query_rag re-attaches x-lancet-session-id / x-lancet-correlation-id / x-lancet-error-kind to its Status errors, or gateway/main.go:771-783 and the doubles at gateway/main_test.go:1089-1241 are deleted. Not both left as-is."
    why_human: "This is a cross-runtime contract ownership decision, not a defect with one correct fix. The engine side was deliberately deleted with the inline remainder in af42b10; whether the D-1 status metadata contract from Phase 03 is still wanted is a product/architecture call."
  - test: "Reconcile Phase 05 traceability bookkeeping."
    expected: "05-11-SUMMARY's GATE-01/GATE-02/GATE-03 are corrected (or added to 05-12-TRACEABILITY-ERRATA.md), and REQUIREMENTS.md ORCH-01 and ORCH-05 are checked."
    why_human: "Requires a human decision on whether GATE-* were intended as new requirement IDs or were transcription noise; a verifier cannot invent the intent."
  - test: "Review the 15 judgment-tier prohibitions carried forward from plans 05-01 through 05-07 (listed in the Prohibitions section below)."
    expected: "Each prohibition is explicitly accepted or rejected by a human."
    why_human: "None declares a `verification:` tier, so all 15 are judgment-tier per ADR-550 D4. The verifier's spot-verdicts below are NON-AUTHORITATIVE and must never be absorbed into a silent pass."
evidence_commands:
  - "cargo test --manifest-path engine/Cargo.toml --locked -> 280 passed, 0 failed, 1 ignored (exit 0). 128 lib + 125 main + 18 inspect_lancedb + 9 config_startup."
  - "cd gateway && go test ./... -count=1 -> ok (exit 0); 11 tests SKIP without TEST_DATABASE_URL."
  - "cd gateway && TEST_DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable go test . -count=1 -run 'TestWorkflowCheckpointPersistence|TestWorkflowCheckpointCancellationAtomicity|TestWorkflowCheckpointPendingDrainAndPersistence' -> 3 PASS against live Postgres (lancet-postgres container, healthy)."
  - "cd gateway && TEST_DATABASE_URL=... go test . -count=1 -run 'TestWorkflowCheckpointTracer|TestWorkflowCheckpointSchemaArtifacts|TestWorkflowCheckpointBackpressureDoesNotStallSSE|TestCheckpointDispatcherSixthEnvelopeReturnsPending' -> 4 PASS."
  - "cd gateway && go test . -count=1 -run 'TestRAGQueryCrossRuntime|TestRAGQueryClientDisconnectCancelsRustWorkflow|TestRAGQuerySSEFirstFrame|TestQueryRAGRealInvalidRequestAndDisconnect' -> 4 PASS (spawns the real engine binary)."
  - "Debt-marker scan over all 50 phase-modified source files (git diff --name-only 9a60d55~1..HEAD, filtered to engine/ gateway/ proto/ config/ buf*): zero TBD, FIXME, XXX, TODO, HACK, PLACEHOLDER, 'not yet implemented', 'coming soon', unimplemented!."
---

# Phase 5: State Machine & Workflow Events — Verification Report

**Phase Goal (User Story):** As a Lancet engineer, I want to formalize RAG orchestration into a Rust state machine, so that I can debug and extend the pipeline with predictable failure handling.
**Mode:** mvp
**Verified:** 2026-08-18 at HEAD `d84cee2`
**Status:** human_needed
**Score:** 5/5 roadmap success criteria verified (see Scope of This Verification)
**Re-verification:** Yes — full re-derivation. The previous report (2026-08-13, `gaps_found`, 1/5) predated plans 05-08 through 05-24 and is superseded in its entirety.

---

## Re-verification Note

The previous verification failed SC1 and SC2 on the finding that the five workflow nodes were test-only and that production `query_rag` delegated all real work to an inline monolith with no event sink. **That finding was correct at the time and is now obsolete.** I did not carry any prior verdict forward and I did not assume the gaps were closed — each was re-derived from the working tree and, where behavior was at stake, re-proven by executing a test.

The single most important structural change: `execute_inline_query_rag_remainder` was deleted in commit `af42b10` (plan 05-22). `grep -rn "execute_inline_query_rag_remainder" --include=*.rs .` now returns **zero hits repo-wide**. The production path is the runner.

---

## Scope of This Verification

Per Step 2a, the **ROADMAP Success Criteria are the contract** and were verified in full — all five, each with an executed behavioral test. Plan-level `must_haves.truths` blocks across the 24 PLAN frontmatters were **not separately enumerated**; they were verified only where they restate or refine a roadmap SC (which, on inspection, is where the substantial majority of them sit — e.g. 05-02's variant-admission and RRF truths under SC1, 05-03's retry and event-cardinality truths under SC3, 05-05's checkpoint-ownership truths under SC4). The headline `5/5` therefore certifies roadmap-SC coverage, **not** exhaustive plan-truth coverage.

This is a deliberate narrowing, recorded so it is not mistaken for full must-have coverage. The previous report scored both tiers (`1/5 roadmap SCs, plus 5/14 plan-level truths`); a like-for-like second tier is not offered here because plans 05-08 through 05-24 restructured the work such that the earlier plan truths no longer map one-to-one onto shipped artifacts.

---

## User Flow Coverage (MVP Mode)

The outcome clause — *"so that I can debug and extend the pipeline with predictable failure handling"* — is the success condition. Each row is what the engineer would actually do.

| # | Engineer step | Expected | Evidence in codebase | Status |
|---|---------------|----------|----------------------|--------|
| 1 | Issue a query and watch the pipeline execute as discrete named stages | Five named nodes run in a fixed order | `build_production_workflow` (main.rs:1523-1609) registers ReformulateQuery, ExtractGraphContext, RetrieveHybrid, AssemblePrompt, GenerateAnswer. `query_rag` (main.rs:1815-1830) calls `runner.run_workflow(ctx, cancel, sink)` — no bridge, no inline path. `workflow_phase5_production_reachability` asserts `started_nodes == [ReformulateQuery, ExtractGraphContext, RetrieveHybrid, AssemblePrompt, GenerateAnswer]` exactly. | ✓ |
| 2 | Watch stage-by-stage progress arrive at the HTTP client in real time | SSE frames per node, plus answer and terminal | `TestRAGQueryCrossRuntime` (gateway/main_test.go:2030) spawns the **real** `engine.exe`, drives a real gateway over real HTTP, and fails unless `node_started:` AND `node_completed:` are present for all five node names, plus `answer_chunk`, `final_answer`, `workflow_completed`, and no `stream_error`. PASS (2.98s). | ✓ |
| 3 | Debug a run after the fact by inspecting captured state | Durable per-node snapshot of the full accumulated context | `CheckpointSnapshot` (events.rs:168-215) serializes all 19 keys of `WorkflowContext`; `CHECKPOINT_SNAPSHOT_KEYS` is asserted key-for-key by `workflow_phase5_checkpoint_full_snapshot`. Rows land in Postgres: I ran the three previously-skipped DB tests against the live `lancet-postgres` container — all PASS. | ✓ |
| 4 | Rely on a hung node failing at a known deadline rather than hanging | Configured per-node deadline fires; typed Timeout reported | `workflow_phase5_config_verify_generation_timeout` loads the real `config/config.toml` + `config.verify.toml` overlay, builds the production workflow, and asserts wall-clock elapsed in [6500ms, 15000ms) against `generation_node_timeout_ms = 7000` while the provider budget is 30s, with `NodeFailed{category=Timeout}` observed and `cancel.is_cancelled()`. | ✓ |
| 5 | Rely on a transient provider blip being retried exactly once, not fabricated around | One byte-identical retry, scoped to generation only | `GenerateAnswerNode::run` (generate.rs:104-130): attempt 1, retry only on Timeout/ProviderError, byte-identical `request_snapshot.clone()`, cancellation checked before the retry. `workflow_phase5_generation_retry_tracer` and `workflow_phase5_generation_retry_exhausted` drive it against a real TCP listener. | ✓ |
| 6 | Hang up mid-stream and have the engine stop spending money | Client disconnect cancels the workflow | `CancelOnDropStream::drop` (main.rs:1791-1794) calls `self.cancel.cancel()`. `TestRAGQueryClientDisconnectCancelsRustWorkflow` runs a real engine against a mock provider whose `/chat/completions` blocks on `r.Context().Done()` and asserts cancellation is observed. PASS (2.15s). | ✓ |
| 7 | Extend the pipeline with a real query reformulator later | A trait seam exists with a shipped pass-through | `pub trait QueryReformulator` (ports.rs:15-21) + `NoOpQueryReformulator` (ports.rs:23-45, returns `vec![query]`). Registered in production at main.rs:1570-1572. Its node appears in the live SSE stream (step 2). | ✓ |

**All seven steps of the engineer's flow are covered.** The outcome clause holds.

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | RAG pipeline is formalized into a defined state machine. | ✓ VERIFIED | `WorkflowRunner` + typed `NodeKind` (5 variants, exhaustively matched in `run_workflow` at runner.rs:415-426 and `timeout_for_kind` at 309-317). All five nodes registered on the **production** runner with **real** adapters (`ProductionEmbeddingPort`, `ProductionGraphQueryPort`, `ProductionDenseRetrievalPort`, `ProductionBm25RetrievalPort`, real `self.reranker`, real `self.generator`). D-03 zero-evidence short-circuit is a first-class state transition (runner.rs:416-422) and is asserted (`zero_started_nodes == [ReformulateQuery, ExtractGraphContext, RetrieveHybrid]`). Typed failure terminal asserted: `error_kind == RetrievalFailed`, `success == false`. |
| 2 | Workflow events (node started, chunk generated, completed) stream from Rust to Go to Client. | ✓ VERIFIED | Producer: `run_node` emits NodeStarted (339), NodeCompleted (377), AnswerChunk on GenerateAnswer only (381), NodeFailed (392), Checkpoint (389); `emit_terminal_once` emits FinalAnswer + WorkflowCompleted exactly once via a `compare_exchange` latch (492-498). Relay: `writeWorkflowEventSSE` (gateway/main.go:791-877) maps all six client-facing variants and deliberately swallows Checkpoint so snapshot JSON never leaks to the client. Consumer: proven over real HTTP by `TestRAGQueryCrossRuntime`, which additionally verifies Rust-owned evidence (graph + dense + lexical fixture markers) reached the provider. |
| 3 | Node timeouts and retries handle failure scenarios predictably. | ✓ VERIFIED | Config→runtime: `EngineSettings.workflow` (main.rs:289) parses all seven `[engine.workflow]` keys; `WorkflowSettings::validate` rejects zero (258-281); env overrides wired (613-643); values reach `with_timeouts` (1562-1568) and `ExtractGraphContextNode::with_timeouts` for the nested embedding/graph deadlines (1578-1581). Timeout behavior proven with real wall-clock timing (see flow step 4). Retry proven (step 5). Cancellation proven end-to-end (step 6). Capability preflight correctly moved outside the node timer into `Node::prepare()` (generate.rs:55-70, runner.rs:342-359) so the deadline measures work, not warm-up. **Caveat CR-01 adjudicated below — latent, not live.** |
| 4 | Snapshots of the workflow state can be captured for debugging. | ✓ VERIFIED | Serialization: 19-key `CheckpointSnapshot` covering every `WorkflowContext` field, with only `query_embedding` compacted to a `{dimension, hash}` digest (bounded < 20KB, asserted). Population: the production `RetrieveHybridNode` writes `ctx.vector_results` (retrieve.rs:84), `ctx.bm25_results` (116), `ctx.final_candidates` (176) — the previous report's "always empty" finding is closed. Ownership under backpressure: `send_checkpoint` never drops, it retains into a 32-slot bounded queue; the gateway now calls `RetainPending` on `DispatchPending` (main.go:800-805). Durability: **I ran the three previously-skipped Postgres tests against the live database — all PASS**, plus `TestWorkflowCheckpointTracer`'s DB branch which proves the full `pb.WorkflowEvent(Checkpoint)` → envelope → persisted row chain. |
| 5 | QueryReformulator trait defined with pass-through node in state machine (Port for 999.3). | ✓ VERIFIED | `trait QueryReformulator` (ports.rs:15) is cancellation-aware by signature (`&CancellationToken`) and returns `Vec<String>`, so a future multi-variant reformulator needs no signature change. `NoOpQueryReformulator` returns `vec![query]`. Wired into production at main.rs:1570, and the resulting `ReformulateQuery` node is observed in the live SSE stream. `ctx.variants == ["<query>"]` asserted by `workflow_phase5_production_context_population`. |

**Score: 5/5 truths verified (0 present-but-behavior-unverified).**

Every truth here is behavior-dependent (state transitions, cancellation/cleanup/ordering invariants). None was accepted on symbol presence — each is backed by a test I executed in this session.

---

## Claim-vs-Actual Adjudications

These four leads were flagged for explicit adjudication. All four are addressed on the record.

### (a) `engine/src/workflow/context.rs` — SUMMARY overclaim, not a gap

`05-01-SUMMARY.md` lists the file under `key-files.created`. **Confirmed absent:** `ls` fails and `git log -- engine/src/workflow/context.rs` is empty. However `pub struct WorkflowContext` exists at `engine/src/workflow/mod.rs:32-52` with all 19 fields, is constructed on the production path (`main.rs:1814`), populated by every production node, and fully serialized into checkpoints.

**Verdict: documentation overclaim (file-placement fiction), no missing deliverable.** Recorded as info-severity, not a gap.

### (b) WR-05 — `d1_status` deleted; `x-lancet-*` trailer contract now broken. **CONFIRMED, and it is a regression this phase introduced.**

Independently verified:
- `git show af42b10 -- engine/src/main.rs | grep '^-.*fn '` → `-fn d1_status(`, alongside the removal of `execute_inline_query_rag_remainder`, `snapshot_limit`, `snapshot_rrf_k` (349 lines deleted).
- `grep -rn "x-lancet" --include=*.rs engine/src` → the **only** setter is `engine/src/tests.rs:2493-2500`, a test double. Zero production emitters.
- `gateway/main.go:774-782` still reads all three keys in `handlePreStreamError`.
- `gateway/main_test.go:1089-1241` proves the Go reader against a fake engine that still sets them.
- `d1_status` predates this phase (introduced 2026-07/08 by commits `9780d20` / `8841ed6`, phase 03).

**Does it affect SC2? No.** The trailers ride on the terminating gRPC `Status`, not on the event stream, and they are consumed exclusively by `handlePreStreamError` — the pre-stream error path. SC2's subject (node started / chunk generated / completed streaming Rust→Go→Client) is proven independently and end-to-end by `TestRAGQueryCrossRuntime` over real SSE. Degradation is graceful: the headers are simply not set, and `InvalidArgument` still maps to HTTP 400.

**But it is a genuine live contract break with a green test suite over it**, which is the worst combination for future maintenance. Escalated as a developer decision (see Human Verification #2) and recorded under `re_verification.regressions`, not as a gap against a phase success criterion.

### (c) WR-06 — `run_inline_prompt_generation_remainder` is exported but unreachable from production. **CONFIRMED.**

`grep -rn "run_inline_prompt_generation_remainder" --include=*.rs .` returns exactly 4 lines: the definition at `workflow/mod.rs:164` and three call sites, all in `engine/src/tests/workflow_phase5.rs` (1520, 1606, 1717). Each goes through `WorkflowRunner::run_tracer`, whose own call-site enumeration is identical — those same three test lines. `query_rag` calls `run_workflow`, never `run_tracer`.

The review's substantive point holds: the function passes `evidence: vec![]` to the generator (mod.rs:200-203), so against a real grounded generator it could never produce a cited answer. **It is dead in production.** Verdict: WARNING — a `pub` trap for a future caller, not a defect in any shipped path. Recommend `#[cfg(test)]` or deletion.

### (d) CR-01 — cancellation-ordering defect. **Code shape CONFIRMED; stated precondition is UNREACHABLE in production. This corrects the review.**

The code shape is exactly as described: `cancel.cancel()` at runner.rs:349 (preparation branch) and :367 (timeout branch) runs *before* the NodeFailed emission at :350 / :392, and `send_envelope`/`flush_pending_checkpoints` use a `biased` select whose first arm is `cancel.cancelled()`. The `?` at :354 / :396 would indeed replace a real `Timeout` with `Cancelled`.

**But the review's own stated precondition — `self.tx.capacity() == 0`, i.e. 100 buffered events — cannot occur.** The biased arm at runner.rs:100-110 and :134-144 is guarded by `if self.tx.capacity() > 0 { return ... }` immediately above it, so it is entered only when the per-request channel is completely full. Counting the maximum events one workflow can produce:

```
5 nodes x (NodeStarted + NodeCompleted + Checkpoint)   = 15
+ AnswerChunk (GenerateAnswer only, is_final = true)   =  1   -> 16
+ FinalAnswer + terminal_success Checkpoint + WorkflowCompleted = 3 -> 19
```

The channel is `mpsc::channel(100)`, created per request at `main.rs:1798`, and the sink is not shared across workflows. **19 < 100**, and there is no per-token chunk loop — `answer_chunk` is emitted exactly once with the whole answer. `capacity()` therefore never reaches 0, the biased arm is never taken, and NodeFailed / WorkflowCompleted are never dropped.

Empirical corroboration: `workflow_phase5_config_verify_generation_timeout` fires the timeout branch (so `cancel.cancel()` at :367 has already run), and still observes `NodeFailed{node_name: "GenerateAnswer", category: Timeout}` delivered to the receiver, with the returned error kind equal to `Timeout` — not `Cancelled`.

**Verdict: WARNING (latent defensive defect), not a BLOCKER, and SC3 is not defeated.** It becomes live the moment per-token streaming chunks land (planned for 999.x), the buffer shrinks, or a sink is shared. The fix is one line of reordering and should be taken before streaming work begins.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `engine/src/workflow/runner.rs` | Runner + event sink + terminal latch | ✓ VERIFIED | 559 lines. Per-kind timeouts, `prepare()` outside the timer, idempotent terminal via `compare_exchange`, bounded 32-slot pending-checkpoint queue. Wired: constructed in `build_production_workflow`, driven by `query_rag`. |
| `engine/src/workflow/mod.rs` | `WorkflowContext` + `WorkflowDependencies` | ✓ VERIFIED | 19-field context at :32, constructed at main.rs:1814. `WorkflowDependencies` now built with all seven fields `Some(...)` (main.rs:1550-1559) — previously all `None`. |
| `engine/src/workflow/events.rs` | Typed event constructors + full snapshot | ✓ VERIFIED | 370 lines. `CHECKPOINT_SNAPSHOT_KEYS: [&str; 19]`, `CheckpointSnapshot` covering every context field, embedding compacted to a deterministic FNV digest. |
| `engine/src/workflow/ports.rs` | Injectable port traits + pass-through reformulator | ✓ VERIFIED | `QueryReformulator`, `GraphQueryPort`, `DenseRetrievalPort`, `Bm25RetrievalPort`; fakes correctly gated behind `#[cfg(test)]` (:78). |
| `engine/src/workflow/nodes/*.rs` (5 files) | One node per stage | ✓ VERIFIED | All five constructed in `build_production_workflow`. Previous report's "test-only construction" finding is closed for every one of them. |
| `engine/src/main.rs` | Production wiring | ✓ VERIFIED | `build_production_workflow` :1523-1609; `query_rag` :1728-1833; `CancelOnDropStream` :1774-1794; `WorkflowSettings` :241-282; `EngineSettings.workflow` :289. |
| `gateway/main.go` | SSE relay + checkpoint dispatch | ✓ VERIFIED | `writeWorkflowEventSSE` :791-877 (6 event types, checkpoint suppressed from client); `RetainPending` on pending :800-805; dispatcher constructed in main() :1074-1085. |
| `gateway/checkpoint_sink.go` | Detached Postgres dispatcher | ✓ VERIFIED | Wired into `app` in main(); FIFO drain proven by `TestWorkflowCheckpointPendingDrainAndPersistence` against live Postgres. |
| `gateway/db/schema.sql`, `query.sql` | `workflow_checkpoints` table + sqlc statements | ✓ VERIFIED | Parameterized sqlc-generated statements — no injection surface. `TestWorkflowCheckpointSchemaArtifacts` PASS. |
| `proto/lancet/v1/lancet.proto` | Wire contract for all events | ✓ VERIFIED | Rust and Go bindings regenerated and synchronized; `TestRetrievalSnapshotWireContract` PASS. |
| `config/config.toml` + `.example` + `.verify` | Seven `[engine.workflow]` keys | ✓ VERIFIED | All three carry the block; **now actually read** — `workflow_phase5_config_verify_generation_timeout` deserializes the real files off disk. |
| `engine/src/workflow/context.rs` | (claimed by 05-01-SUMMARY) | ⚠️ ABSENT | Never existed. Deliverable satisfied at `mod.rs:32`. Documentation overclaim only — see adjudication (a). |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `query_rag` | `WorkflowRunner` | `runner.run_workflow(ctx, cancel, sink)` | ✓ WIRED | main.rs:1815-1830. Direct call — no bridge, no tracer, no inline remainder. |
| `LancetServiceImpl` adapters | five nodes | `build_production_workflow` | ✓ WIRED | Real embedder/graph/dense/bm25/reranker/generator handles; `Arc::ptr_eq` identity asserted by `workflow_phase5_production_dependencies_are_real`. |
| `config/*.toml` | `WorkflowRunner` deadlines | `EngineSettings.workflow` → `to_workflow_settings()` → `with_timeouts` | ✓ WIRED | main.rs:289 → 482 → 1562-1568. Previously a dead config block. |
| Rust event sink | Go gateway | gRPC server stream (`QueryRAGStream`) | ✓ WIRED | Proven across two real processes by `TestRAGQueryCrossRuntime`. |
| Go gateway | HTTP client | SSE (`text/event-stream`) | ✓ WIRED | `writeWorkflowEventSSE` + `rc.Flush()` per frame; frames parsed and asserted by name in the same test. |
| Checkpoint event | Postgres row | `NewCheckpointEnvelopeFromEvent` → dispatcher → `PostgresCheckpointSink` | ✓ WIRED | End-to-end chain proven by `TestWorkflowCheckpointTracer`'s DB branch (run with live Postgres). |
| HTTP stream drop | workflow cancellation | `CancelOnDropStream::drop` → `cancel.cancel()` | ✓ WIRED | main.rs:1791-1794; proven end-to-end by `TestRAGQueryClientDisconnectCancelsRustWorkflow`. |
| Engine `Status` trailers | gateway `handlePreStreamError` | `x-lancet-*` metadata | ✗ NOT WIRED *(Phase 03 contract — **not** a Phase 05 must-have key link; recorded under `re_verification.regressions` / WR-05, deliberately **not** in `gaps`)* | **Regression WR-05.** Reader present (main.go:774-782); zero production emitters. Does not carry workflow events; does not affect SC2. Escalated. |

---

## Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
|----------|---------------|--------|--------------------|--------|
| `WorkflowContext.variants` | variants | `NoOpQueryReformulator::reformulate` | Yes (`["<query>"]`) | ✓ FLOWING |
| `WorkflowContext.query_embedding` | embedding | `ProductionEmbeddingPort` → real `EmbeddingProvider` | Yes (2048-dim asserted) | ✓ FLOWING |
| `WorkflowContext.graph_facts` | graph facts | `ProductionGraphQueryPort` → LanceDB traversal | Yes (`GRAPH_FIXTURE_MARKER_*` reached the provider prompt in the cross-runtime test) | ✓ FLOWING |
| `WorkflowContext.vector_results` | dense hits | `ProductionDenseRetrievalPort` (retrieve.rs:84) | Yes (`DENSE_FIXTURE_MARKER`) | ✓ FLOWING |
| `WorkflowContext.bm25_results` | lexical hits | `ProductionBm25RetrievalPort` (retrieve.rs:116) | Yes (`LEXICAL_FIXTURE_IDENTIFIER_2026`) | ✓ FLOWING |
| `WorkflowContext.final_candidates` | fused candidates | RRF fusion → evidence blocks (retrieve.rs:176) | Yes | ✓ FLOWING |
| `WorkflowContext.answer` / `citations` | model output | `GenerateAnswerNode` → real `Generator` | Yes (grounded answer + `[1]` citation + structured citation with real document_id) | ✓ FLOWING |
| `CheckpointEvent.context_snapshot` | snapshot JSON | `CheckpointSnapshot::from_context` | Yes (19 keys, all populated fields round-trip) | ✓ FLOWING |
| `workflow_checkpoints.context_snapshot` | persisted row | dispatcher → sqlc INSERT | Yes (rows read back and JSON-validated) | ✓ FLOWING |
| `X-Lancet-*` response headers | error identity | (none in engine) | **No** | ✗ DISCONNECTED — WR-05 |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Whole Rust suite compiles and passes | `cargo test --manifest-path engine/Cargo.toml --locked` | 280 passed / 0 failed / 1 ignored, exit 0 | ✓ PASS |
| Whole Go suite passes | `cd gateway && go test ./... -count=1` | ok, exit 0 (11 DB tests skipped without env) | ✓ PASS |
| Five-node reachability + one AnswerChunk + one FinalAnswer over real SSE | `go test . -run TestRAGQueryCrossRuntime` | PASS (2.98s), real `engine.exe` spawned | ✓ PASS |
| Client disconnect cancels the in-flight provider call | `go test . -run TestRAGQueryClientDisconnectCancelsRustWorkflow` | PASS (2.15s) | ✓ PASS |
| SSE first-frame ordering and pre-stream error path | `go test . -run 'TestRAGQuerySSEFirstFrame\|TestQueryRAGRealInvalidRequestAndDisconnect'` | PASS | ✓ PASS |
| Checkpoint rows land in Postgres (previously SKIPPED) | `TEST_DATABASE_URL=... go test . -run 'TestWorkflowCheckpointPersistence\|...CancellationAtomicity\|...PendingDrainAndPersistence'` | 3 PASS against live `lancet-postgres` | ✓ PASS |
| Event → envelope → persisted row chain (previously SKIPPED branch) | `TEST_DATABASE_URL=... go test . -run TestWorkflowCheckpointTracer` | PASS, `count == 1` for the trace | ✓ PASS |
| Generation node deadline fires at the configured 7000ms, not the 30s provider budget | (in-suite) `workflow_phase5_config_verify_generation_timeout` | PASS, elapsed asserted in [6500, 15000)ms | ✓ PASS |
| `d1_status` / `x-lancet-*` emitted by production engine | `grep -rn "x-lancet" --include=*.rs engine/src` | Only `tests.rs:2493` (test double) | ✗ FAIL (WR-05, out of SC scope) |
| Live OpenRouter round trip | `generation::tests::openrouter_structured_output_smoke` | **ignored** — requires `OPENROUTER_API_KEY` | ? SKIP → human |

**Note on the DB tests.** `go test ./...` reports `ok` while silently skipping 11 database tests, including all three checkpoint-persistence tests. A green suite alone would **not** have proven SC4. I set `TEST_DATABASE_URL` against the running `lancet-postgres` container and executed them; they use `newWorkflowCheckpointsIsolatedPostgres` (unique schema per test), so no shared data was touched. I deliberately did **not** run the broader `gateway/db` integration tests, which ADR-02-002 records as historically capable of unscoped deletes.

---

## Probe Execution

No `scripts/*/tests/probe-*.sh` exist in this repository and no PLAN or SUMMARY in this phase references a probe path.

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| — | — | — | SKIPPED (no probes declared or conventional) |

---

## Requirements Coverage

| Requirement | Declared by plans | Description | Status | Evidence |
|-------------|-------------------|-------------|--------|----------|
| **ORCH-01** | 01, 02, 03, 04, 08, 09, 11(sum), 12, 14, 16, 17, 18, 22, 23, 24 | Lightweight Rust state machine for the fixed RAG path | ✓ SATISFIED | Five-node runner registered and reachable in production; ordering asserted exactly. **REQUIREMENTS.md:32 still shows `[ ]`** — understated. |
| **ORCH-02** | 01, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20, 22, 23 | Client-facing workflow events | ✓ SATISFIED | All six client-facing variants emitted, relayed, and observed at an HTTP client. |
| **ORCH-03** | 01, 02, 03, 04, 06, 08, 09, 10, 11, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24 | Cancellation, timeouts, retry/fallback | ✓ SATISFIED | Config-driven per-node deadlines proven by wall clock; single scoped retry; drop-triggered cancellation proven cross-process. CR-01 latent (adjudicated). |
| **ORCH-04** | 05, 06, 10, 11, 12, 16, 17, 19, 21, 22, 23 | Lightweight checkpoints/snapshots | ✓ SATISFIED | 19-key lossless snapshot; production population; Postgres durability executed and passing. |
| **ORCH-05** | 01, 02, 08, 12, 22, 24 | Dedicated `reformulate` stage, pass-through in v1 | ✓ SATISFIED | `QueryReformulator` trait + `NoOpQueryReformulator` registered in production. **REQUIREMENTS.md:36 still shows `[ ]`** — understated. |

**Orphaned requirements:** none. `grep -E "Phase 5" .planning/REQUIREMENTS.md` maps no ID to this phase beyond the five ORCH IDs, and every one is claimed by at least one plan.

**Phantom requirement IDs closed by SUMMARYs that do not exist in REQUIREMENTS.md:**

| SUMMARY | Phantom IDs | Corrected by errata? |
|---------|-------------|----------------------|
| `05-02-SUMMARY.md` | RAG-01, RAG-02 (also drifted: closed ORCH-03 only, plan declared ORCH-01/03/05) | ✓ Yes — 05-12-TRACEABILITY-ERRATA.md §1 |
| `05-03-SUMMARY.md` | GEN-01, GEN-02, GEN-03, EVENT-03 | ✓ Yes — 05-12-TRACEABILITY-ERRATA.md §1 |
| `05-06-SUMMARY.md` | none phantom, but closes **ORCH-01** (never declared) and drops ORCH-02/ORCH-03 that its PLAN did declare | ✗ **No** — errata §2 corrects 05-06's *narrative* only, not its ID list. |
| `05-11-SUMMARY.md` | **GATE-01, GATE-02, GATE-03** | ✗ **No** — 05-11 executed in Wave 18, *after* the errata was authored. Live and uncorrected. |

**SUMMARYs with no `requirements-completed` field at all (10):** 05-13, 05-14, 05-15, 05-16, 05-17, 05-18, 05-19, 05-22, 05-23, 05-24. For these plans, requirement closure is inferable only from the PLAN's `requirements:` declaration and is never asserted by the executed artifact. All ten declare only ORCH IDs, so no requirement goes unaccounted for — but the closure is one-sided.

Note: `RAG-01`/`RAG-02` do exist in REQUIREMENTS.md (1 hit each) but are not Phase 05 requirements; `GEN-*`, `EVENT-03`, and `GATE-*` return zero hits repo-wide in REQUIREMENTS.md.

This is bookkeeping, not goal achievement — recorded as a WARNING with named remediation. **If this project gates phase completion on clean requirement traceability, the GATE-01/02/03 row is the single item that would flip this verdict.**

---

## Anti-Patterns Found

Scanned all **50** phase-modified source files (`git diff --name-only 9a60d55~1..HEAD`, filtered to `engine/ gateway/ proto/ config/ buf*`; the planning tree and an unrelated GSD tooling bump were excluded). The set includes the 11 generated/test files the code review explicitly excluded from line-by-line reading.

| Pattern class | Matches | Severity |
|---------------|---------|----------|
| `TBD`, `FIXME`, `XXX` (debt-marker gate) | **0** | — |
| `TODO`, `HACK`, `PLACEHOLDER` | **0** | — |
| "not yet implemented", "coming soon", `unimplemented!` | **0** | — |

**The debt-marker gate passes cleanly.** No BLOCKER anti-pattern.

Non-marker observations carried from the code review and independently confirmed:

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `engine/src/workflow/runner.rs` | 348-356, 361-371 | cancel-before-emit ordering | ⚠️ Warning | Latent; precondition unreachable (CR-01 adjudication). |
| `engine/src/workflow/runner.rs` | 246-249 | `unreachable!()` in `wrap_event` on a cloneable sink | ⚠️ Warning | Private helper; only caller is `send_checkpoint`, which always passes a checkpoint. Not currently reachable. |
| `engine/src/workflow/runner.rs` | 319-328 | `timeout_for_node` with a magic 5000ms fallback | ℹ️ Info | Used only by tests; `run_node` uses the typed `timeout_for_kind`. |
| `engine/src/workflow/mod.rs` | 164-259 | `pub fn` dead in production, passes `evidence: vec![]` | ⚠️ Warning | WR-06. Gate behind `#[cfg(test)]` or delete. |
| `gateway/main.go` | 1076 | `defer dispatcher.Close()` unreachable | ⚠️ Warning | WR-01. Bounded shutdown loss (≤5 envelopes). |
| `engine/src/main.rs` | 1826 | `let _ = &deps;` keep-alive | ℹ️ Info | Deliberate lifetime pin for the spawned task; harmless but opaque. |

---

## Prohibitions (15 — all judgment-tier, NON-AUTHORITATIVE)

None of the 15 prohibitions across plans 05-01 through 05-07 declares a `verification:` tier, so all are judgment-tier under ADR-550 D4. Per the autonomous-mode rule these carry a **NON-AUTHORITATIVE LLM-judge verdict plus an `unverified-prohibition — human review recommended` flag**; they are counted as human-verification items and are never silently absorbed into a pass.

| # | Plan | Prohibition (abridged) | Non-authoritative spot-verdict |
|---|------|------------------------|-------------------------------|
| 1 | 05-01 | No raw provider token streaming or JSON fallback transport | Appears held — one `answer_chunk` with `is_final=true` carrying the whole answer; the SSE route is the only `/rag/query` transport. |
| 2 | 05-01 | Rust must not open PostgreSQL; QueryGraph API unchanged | Appears held — no postgres/sqlx/tokio-postgres dependency in `engine/Cargo.toml`. |
| 3 | 05-02 | Retrieval node must not hard-index variant zero or drop non-finite scores | Not independently re-derived. |
| 4 | 05-02 | Standalone QueryGraph API must not change | Appears held — `query_graph` RPC untouched by the workflow path. |
| 5 | 05-03 | Generation must not fabricate, alter the retry request, emit raw chunks, or retry a non-generation node | Appears held — retry is byte-identical `request_snapshot.clone()` and scoped to `GenerateAnswerNode` only. |
| 6 | 05-03 | Prompt assembly must not omit graph/retrieval fields from the snapshot or convert failure to success | Appears held — 19-key snapshot; failure terminal asserts `success == false` with typed kind. |
| 7 | 05-04 | Tests must not use live provider timing or count skipped tests as coverage | **Partially at odds with practice** — the DB tests silently skip in the default `go test ./...` run and were being reported as a green suite. I executed them; see Behavioral Spot-Checks. |
| 8 | 05-04 | Matrix must not conflate zero-evidence / degradation / retrieval-failure / timeout / cancellation / exhaustion | Appears held — distinct `NodeErrorKind` values and distinct notice codes asserted. |
| 9 | 05-05 | Checkpoint JSON must not reach client SSE or a fetch endpoint | Appears held — `writeWorkflowEventSSE` returns early on Checkpoint; `TestWorkflowCheckpointTracer` asserts the DTO contains no `context_snapshot`. |
| 10 | 05-05 | Rust must not own PostgreSQL; no serial sequencing or shared-schema fixtures | Appears held. |
| 11 | 05-06 | Gateway must not buffer the whole workflow, expose JSON fallback, or let `/rag/query` inherit the 60s timeout | Appears held — `newHTTPServer` sets `ReadTimeout`/`ReadHeaderTimeout` only, no `WriteTimeout`, so streaming is not cut off. |
| 12 | 05-06 | Go relay must not reinterpret Rust node semantics or leak provider secrets | Appears held — relay is a pure field mapping. |
| 13 | 05-07 | Do not renumber/rename/remove the nine existing NodeErrorKind variants | Appears held. |
| 14 | 05-07 | Do not hand-edit files under `engine/src/pb/lancet/v1/` or `gateway/proto/lancet/v1/` | Appears held — IN-06's hand-written glue is `engine/src/pb/mod.rs`, outside the prohibited `lancet/v1/` subtree. |
| 15 | 05-07 | 05-07 must not modify `engine/src/workflow/*`, `gateway/main.go`, or `gateway/main_test.go` | Cannot be re-derived at HEAD — later plans legitimately modified those files. |

---

## Gaps Summary

**No gaps block the phase goal.** All five roadmap success criteria are verified, each with an executed behavioral test rather than symbol presence, and the debt-marker gate is clean across all 50 phase-modified source files.

The previous verification's central finding — a state machine that existed only as a library while production ran an inline monolith — is fully and genuinely closed. `execute_inline_query_rag_remainder` no longer exists anywhere in the repository, `build_production_workflow` registers all five nodes on real adapters, and a test that spawns the actual engine binary and reads actual SSE frames over actual HTTP proves the whole chain.

Two things keep this from a clean `passed`:

1. **Nothing in this phase has ever touched a live LLM provider.** Every proof — including the decisive cross-runtime test — substitutes an `httptest` mock for OpenRouter. The one live-provider test is `#[ignore]`. For an MVP phase whose outcome clause is "so that I can debug and extend the pipeline," a single real query is the missing confirmation.

2. **This phase introduced one regression and left three bookkeeping defects**, none of which defeats a success criterion but all of which need a human decision:
   - **WR-05** — the engine stopped emitting `x-lancet-*` trailers that the gateway still reads and that the Go test suite still proves against a stale double. A green suite over a broken contract is worse than a red one.
   - **GATE-01/02/03** in `05-11-SUMMARY.md` — three requirement IDs that do not exist, uncovered by the errata.
   - **REQUIREMENTS.md** still shows ORCH-01 and ORCH-05 unchecked despite both being satisfied.

Separately, **CR-01 should be fixed before per-token streaming work begins.** It is harmless today only because 19 events cannot fill a 100-slot buffer; the arithmetic that makes it safe is precisely the arithmetic that streaming chunks will invalidate.

---

_Verified: 2026-08-18 at HEAD d84cee2_
_Verifier: Claude (gsd-verifier) — adversarial re-verification, superseding the 2026-08-13 report_
