---
phase: 5
scope: gap-closure
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-14T05:49:07.4873436Z
source_head: d4007206b2367577c2bf625488dae4e874a0f54a
stale_review_excluded: true
plans_reviewed:
  - 05-08-PLAN.md
  - 05-09-PLAN.md
  - 05-10-PLAN.md
  - 05-11-PLAN.md
  - 05-12-PLAN.md
  - 05-13-PLAN.md
  - 05-14-PLAN.md
  - 05-15-PLAN.md
  - 05-16-PLAN.md
  - 05-17-PLAN.md
  - 05-18-PLAN.md
  - 05-19-PLAN.md
  - 05-20-PLAN.md
  - 05-21-PLAN.md
reviewer_models:
  antigravity: gemini-3.7-flash-high
  claude: opus
reviewer_effort:
  antigravity: high
  claude: high
reviewer_output_bytes:
  antigravity: 18464
  claude: 22484
---
# Cross-AI Plan Review — Phase 05 Gap Closure (Fresh)

Review scope is the current pending additive plan set 05-08 through 05-21 at d4007206b2367577c2bf625488dae4e874a0f54a. The prior 05-REVIEWS.md was excluded from both reviewer prompts.

## Antigravity Review (gemini-3.7-flash-high, high)

# Cross-AI Plan Review: Lancet Phase 5 Additive Gap Closure (Plans 05-08 through 05-21)

## 1. Summary

The additive gap-closure plan suite for Phase 5 ([`05-08-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md) through [`05-21-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-21-PLAN.md), 14 plans in total) provides a comprehensive, rigorous, and source-grounded strategy to bridge the gap between the baseline state-machine library implementation and true production reachability. By systematically decomposing work into focused waves—retiring the legacy inline remainder in [`engine/src/main.rs`](file:///D:/Repos/lancet/engine/src/main.rs#L1733-L1750), wiring real adapter dependencies into [`WorkflowDependencies`](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L24-L34), enforcing live TOML workflow timeouts and stream-disconnect cancellation, isolating OpenRouter capability preflight from the generation node timer, enforcing typed `NodeKind` dispatch, resolving Rust test-target collisions between binary and library crates, preserving failed terminal notices through Protobuf and Go SSE, ensuring lock-free BM25 retrieval across async yields, and making checkpoint persistence lossless under backpressure—the updated plan set effectively addresses the architectural, concurrency, and validation shortcomings identified in prior audits while strictly honoring the locked phase boundaries and decision invariants (D-01 through D-31).

---

## 2. Strengths

1. **Definitive Production Wiring & Elimination of Dual Paths ([05-08](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md)):**
   - In the live codebase, [`query_rag`](file:///D:/Repos/lancet/engine/src/main.rs#L1656-L1755) registers only `ReformulateQueryNode` on a runner with empty dependencies (`deps = WorkflowDependencies::new()`, where all slots are `None` per [`ports.rs:24-34`](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L24-L34)), delegating the actual pipeline execution to [`execute_inline_query_rag_remainder`](file:///D:/Repos/lancet/engine/src/main.rs#L1234-L1647).
   - Plan 05-08 introduces `build_production_workflow` to construct concrete `Arc<dyn ...>` adapters for all 6 service ports (`EmbeddingProvider`, `GraphQueryPort`, `DenseRetrievalPort`, `Bm25RetrievalPort`, `Reranker`, `Generator`) and registers all 5 nodes in strict D-06 order (`ReformulateQueryNode` -> `ExtractGraphContextNode` -> `RetrieveHybridNode` -> `AssemblePromptNode` -> `GenerateAnswerNode`).
   - Fixes a subtle bug in [`GenerateAnswerNode::run`](file:///D:/Repos/lancet/engine/src/workflow/nodes/generate.rs#L53-L60), where `req.graph_facts` was omitted during `GenerationRequest` instantiation despite graph augmentation succeeding upstream.

2. **Decoupled Preflight & Multi-Attempt Generation Timing ([05-09](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-09-PLAN.md), [05-13](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-13-PLAN.md), [05-20](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-20-PLAN.md)):**
   - In [`engine/src/generation/openrouter.rs`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L600-L636), capability preflight was executed within `execute_one_call`, sharing the 30s per-attempt budget and mapping transport errors to non-retryable errors.
   - Plan 05-13 moves preflight to a dedicated 5s timeout with successful-only caching (preventing transient failure caching), and Plan 05-20 introduces a `Node::prepare` / `Generator::prepare` lifecycle hook executed *before* the 65s `GenerateAnswer` node timer begins.
   - Correctly sizes the end-to-end worst-case pipeline latency budget ($5\text{s} + 10\text{s} + 15\text{s} + 2\text{s} + 65\text{s} = 97\text{s}$ node sequential total $+ 5\text{s}$ preflight bootstrap $= 102\text{s}$), ensuring the 65s generation node timer provides two full 30s provider attempts ($30\text{s} + 30\text{s} + 5\text{s}$ inter-attempt slack) without preflight stealing retry budget.

3. **Concurrency Safety & Lock-Free BM25 Async Yield ([05-16](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-16-PLAN.md)):**
   - Guarding against holding an `RwLockReadGuard` on `Bm25Index` across `.await` points avoids stalling background document ingestion workers in [`engine/src/main.rs:1880`](file:///D:/Repos/lancet/engine/src/main.rs). Plan 05-16 mandates obtaining an $O(1)$ immutable snapshot handle (`Arc<RwLock<Arc<Bm25Index>>>` or index handle clone) and immediately releasing the lock prior to running async lexical scoring.

4. **Target-Aware Test Architecture & Fake Gating ([05-15](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-15-PLAN.md), [05-18](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-18-PLAN.md)):**
   - Resolves the Rust crate target collision where test doubles (`FakeQueryReformulator`, `FakeDenseRetrievalPort`, `FakeGenerator`, etc. in [`engine/src/workflow/ports.rs`](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L89-L358)) could not be gated with `#[cfg(test)]` without breaking binary-target tests in [`engine/src/tests.rs`](file:///D:/Repos/lancet/engine/src/tests.rs#L11).
   - Plan 05-18 separates generic workflow unit tests into [`engine/src/lib.rs`](file:///D:/Repos/lancet/engine/src/lib.rs) (`cargo test --lib`), while keeping binary-owned production tests in [`engine/src/tests/workflow_phase5_production.rs`](file:///D:/Repos/lancet/engine/src/tests/workflow_phase5_production.rs) (`cargo test --bin engine`).

5. **Lossless Checkpoint Dispatching & Strict Schema Isolation ([05-11](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md)):**
   - In [`gateway/checkpoint_sink.go`](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L168-L189) and [`gateway/main.go:765-767`](file:///D:/Repos/lancet/gateway/main.go#L765-L767), `DispatchPending` results were previously unhandled and discarded when channel overflowed. Plan 05-11 ensures `CheckpointDispatcher` tracks and drains pending/overflow queues completely on `Close()`.
   - Adheres strictly to the `AGENTS.md` review convention requiring per-test schema isolation (`search_path`) and fatal assertions on snapshot queries for PostgreSQL integration tests.

6. **Wire-Synchronized Provenance & Terminal Notices ([05-17](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-17-PLAN.md), [05-19](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-19-PLAN.md)):**
   - Adds additive field tags to [`proto/lancet/v1/lancet.proto`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto#L91-L101) (`RetrievalSnapshot.variant_count = 10`, `variant_identities = 11`) and [`WorkflowCompletedEvent.notices = 6`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto#L184-L190).
   - Generates Rust tonic/prost and Go protobuf bindings synchronously via `buf generate` and guarantees that degraded or failed workflows surface accumulated notices (such as `GRAPH_TIMEOUT` and `GRAPH_DEGRADED`) in-band over SSE without fabricating an answer or final response.

---

## 3. Concerns

### [MEDIUM] Concern 1: Gateway SSE Stream Error Writing on Client Disconnect
- **File & Location:** [`gateway/main.go#L725-L735`](file:///D:/Repos/lancet/gateway/main.go#L725-L735) (addressed in [05-11-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md))
- **Mechanism:** Plan 05-11 specifies converting mid-stream gRPC receive errors (`stream.Recv()`) into terminal `stream_error` frames (`GRPC_RECV_ERROR` or `STREAM_EOF_WITHOUT_TERMINAL`). If the reason `stream.Recv()` failed was a client-initiated HTTP disconnect (`r.Context().Done()`), attempting to write and flush the `stream_error` frame to `http.ResponseWriter` will result in a broken pipe / write error.
- **Risk:** If write errors are treated as fatal panics or unhandled errors, it could pollute gateway error logs.
- **Mitigation:** Ensure `writeWorkflowEventSSE` explicitly checks `r.Context().Err()` prior to writing a `stream_error` frame and swallows/logs expected broken pipe errors as debug info when the client has already disconnected.

### [LOW] Concern 2: Dead Code & Unused Warnings upon Retiring Inline Remainder
- **File & Location:** [`engine/src/main.rs#L872`](file:///D:/Repos/lancet/engine/src/main.rs#L872), [`engine/src/main.rs#L1047`](file:///D:/Repos/lancet/engine/src/main.rs#L1047), [`engine/src/main.rs#L1234-L1647`](file:///D:/Repos/lancet/engine/src/main.rs#L1234-L1647)
- **Mechanism:** When `query_rag` switches to `build_production_workflow` in [05-08-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md), helper functions such as `execute_inline_query_rag_remainder`, `d1_status`, and several graph extraction helpers (e.g. `cypher_confirmed_neighbor_ids`, `extract_with_retry`) become unreferenced from production entry points.
- **Risk:** Cargo builds currently emit unused warnings (verified during `cargo check`). While not a compilation blocker, unreferenced functions could accumulate as dead code or trigger compiler warnings in `--deny warnings` environments.
- **Mitigation:** Plan 05-08 and 05-15 should explicitly remove dead remainder helper functions or gate test-only helpers behind `#[cfg(test)]`.

### [LOW] Concern 3: Stream Drop Guard Race with Normal Completion EOF
- **File & Location:** [`engine/src/main.rs#L1704-L1706`](file:///D:/Repos/lancet/engine/src/main.rs#L1704-L1706) (addressed in [05-09-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-09-PLAN.md) & [05-10-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-10-PLAN.md))
- **Mechanism:** When the client finishes reading the stream and tonic drops the `ReceiverStream`, the drop guard triggers `cancel.cancel()`. If the spawned runner task has completed all nodes but is executing terminal cleanup, `cancel.cancel()` could trigger concurrently.
- **Risk:** Race condition could cause a spurious `Cancelled` log or secondary event emission if the runner checks cancellation during shutdown.
- **Mitigation:** Plan 05-10's atomic compare-and-set terminal guard (`WorkflowEventSink`) correctly guarantees that once `WorkflowCompleted` has been emitted, subsequent cancellation signals are ignored and cannot emit duplicate or conflicting events.

---

## 4. Suggestions

1. **Explicit Client Disconnect Check in Gateway SSE Handler:**
   - In [`gateway/main.go`](file:///D:/Repos/lancet/gateway/main.go), inside the `for { ev, recvErr := stream.Recv(); ... }` loop, wrap the stream error emission in a context check:
     ```go
     if recvErr != nil {
         if errors.Is(r.Context().Err(), context.Canceled) {
             return // Client initiated disconnect; skip writing SSE error frame
         }
         a.writeSSEStreamError(w, rc, "GRPC_RECV_ERROR", recvErr.Error())
         return
     }
     ```
   - This prevents redundant write attempts to a closed connection.

2. **Automate Buf Synchronization Guard in CI / Pre-commit:**
   - In [05-17-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-17-PLAN.md), ensure that `git diff --exit-code engine/src/pb gateway/proto` is asserted after running `buf generate` to guarantee that generated files are always in sync with [`proto/lancet/v1/lancet.proto`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto).

3. **Verify Timeout Ordering in Unit Test Fixtures:**
   - In [05-09-PLAN.md](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-09-PLAN.md), when testing timeout handling in `ExtractGraphContextNode`, ensure the graph operation timeout ($4\text{s}$) is strictly tested as nested within the outer graph node backstop ($15\text{s}$) so that degradation occurs before the node-level deadline aborts.

---

## 5. Coverage Assessment

| Success Criteria / Requirement | Primary Plan(s) | Verification Mechanism | Status |
|---|---|---|---|
| **SC-1 / ORCH-01:** RAG pipeline formalized into Rust state machine | [05-08](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md), [05-14](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-14-PLAN.md) | `workflow_phase5_production_five_node`, `workflow_phase5_nodekind_exhaustive` | **Covered** |
| **SC-2 / ORCH-02:** Workflow events stream Rust -> Go -> Client | [05-08](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md), [05-10](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-10-PLAN.md), [05-11](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md), [05-19](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-19-PLAN.md) | `TestRAGQueryCrossRuntime`, `workflow_phase5_event_delivery_tracer`, `TestRAGQueryFailureTerminalNoticesSSE` | **Covered** |
| **SC-3 / ORCH-03:** Node timeouts, single retry, cancellation handling | [05-09](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-09-PLAN.md), [05-13](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-13-PLAN.md), [05-20](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-20-PLAN.md) | `workflow_phase5_config_verify_generation_timeout`, `workflow_phase5_generation_retry_tracer`, `workflow_phase5_generation_preflight_worst_case_budget` | **Covered** |
| **SC-4 / ORCH-04:** Checkpoints & full state snapshots | [05-08](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md), [05-10](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-10-PLAN.md), [05-11](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md), [05-16](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-16-PLAN.md), [05-17](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-17-PLAN.md) | `workflow_phase5_checkpoint_full_snapshot`, `TestWorkflowCheckpointPendingDrainAndPersistence` | **Covered** |
| **SC-5 / ORCH-05:** `QueryReformulator` pass-through port | [05-08](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md), [05-12](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-12-PLAN.md), [05-14](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-14-PLAN.md) | `workflow_phase5_production_reachability`, `workflow_phase5_nodekind_tracer` | **Covered** |

### Prior Gap Theme Disposition
- **CR-01 (Dead settings) & CR-04 (Dead cancellation):** Fully closed by [05-09](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-09-PLAN.md).
- **CR-02 (Production dual path) & CR-03 (Missing graph facts in request):** Fully closed by [05-08](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md).
- **CR-05 (Send outcomes) & WR-13 (Terminal idempotence):** Fully closed by [05-10](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-10-PLAN.md).
- **CR-06 / CR-07 (Stream error visibility) & CR-08 (Pending checkpoint loss):** Fully closed by [05-11](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md).
- **WR-01 (Early 9-variant admission):** Fully closed by [05-14](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-14-PLAN.md).
- **WR-02 / WR-04 (Preflight classification & retry):** Fully closed by [05-13](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-13-PLAN.md) and [05-20](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-20-PLAN.md).
- **WR-06 / WR-07 (Graph notices & failure terminal notices):** Fully closed by [05-16](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-16-PLAN.md), [05-17](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-17-PLAN.md), and [05-19](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-19-PLAN.md).
- **WR-09 / WR-14 (Variant provenance & BM25 lock release):** Fully closed by [05-16](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-16-PLAN.md) and [05-17](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-17-PLAN.md).
- **WR-10 / WR-11 (Prompt API docs & fakes isolation):** Fully closed by [05-15](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-15-PLAN.md) and [05-18](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-18-PLAN.md).
- **IN-01 / IN-02 / IN-03 (Typed dispatch & fusion types):** Fully closed by [05-14](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-14-PLAN.md) and [05-21](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-21-PLAN.md).

---

## 6. Risk Assessment

**Overall Risk Rating: LOW**

**Justification:**
1. **Zero Architectural Drift:** The plan suite rigorously maintains the split-service architecture (Go HTTP/PostgreSQL control plane, Rust data plane), reuses established communication contracts (server-streaming gRPC), and strictly preserves all locked decisions (D-01 through D-31).
2. **Deterministic & Staged Dependency Ordering:** The dependency graph across Waves 7 through 17 is strictly acyclic and structured so that lower-level foundational traits, wire bindings, and compilation boundaries land before higher-level node integrations, event sinks, and gateway SSE mappings.
3. **Execution Feasibility:** The codebase is healthy (Rust `cargo check` and Go tests compile cleanly), historical frozen hashes match HEAD exactly, and test coverage spans both deterministic fast paused-clock unit tests and live wall-clock cross-runtime integration tests.
4. **Resilience & Defensiveness:** Every known failure mode (timeouts, cancellations, backpressure, transient provider errors, corrupt caches, and lock contention) is backed by an explicit typed handler and automated regression test.

The additive gap-closure plans are complete, well-scoped, and ready for execution.


---

## Claude Review (opus, high)

# Cross-AI Plan Review — Phase 5 Additive Gap Closure (05-08 … 05-21)

*Independent review performed against the working tree at `D:\Repos\lancet`, HEAD `d400720`. Every claim below was checked against source; the stale `05-REVIEWS.md` was not consulted for conclusions. No files were edited.*

---

## 1. Summary

This is a strong, source-accurate plan set. I sampled the load-bearing factual claims and they hold: production `query_rag` genuinely registers exactly one node and delegates to the pre-existing monolith (`engine/src/main.rs:1716-1717`, `:1742-1746`; `grep -c add_node` = 1); `[engine.workflow]` is genuinely dead configuration (`config/config.toml:10-17` vs. `EngineSettings` with no `workflow` field); the `CancellationToken` at `main.rs:1706` is genuinely never cancelled; OpenRouter preflight genuinely runs inside every attempt with no cache and maps *all* transport errors — including timeouts — to the non-retryable `SupportedParameters` kind (`openrouter.rs:376`, `:297-302` vs. `generate.rs:73-76`); `events.rs:106-115` genuinely serializes 7 of 18 context fields; the BM25 read guard genuinely spans an unbounded await (`main.rs:1311-1320`); and all six 05-12 frozen blob hashes I spot-checked match `git rev-parse HEAD:<path>` byte-for-byte. The wave DAG is acyclic and strictly monotonic (verified below). Two concerns raised by the prior review cycle — the graph-fact carrier and the binary/library test-target collision — have been genuinely addressed in this revision (05-08 Task 2 and the 05-08/05-18 module split), and 05-09's live-overlay reachability is now closed by committing realistic upstream values and asserting `NodeStarted{GenerateAnswer}`.

The risk is not design; it is **executability**. Four defects will each produce a deterministic build or test failure at a specific wave, and three of them stem from the same root cause: a plan's `<action>` mandates a change to a file its `files_modified` inventory does not own. They are all fixable with bounded edits.

---

## 2. Strengths

**The DAG is genuinely correct.** I walked every `depends_on` against every `wave:`:

| Plan | Wave | depends_on (their waves) |
|---|---|---|
| 05-08, 05-12 | 7 | 05-05, 05-07 (executed) |
| 05-09 | 8 | 05-08 (7) |
| 05-13 | 9 | 05-09 (8) |
| 05-14 | 10 | 05-09 (8), 05-13 (9) |
| 05-17, 05-18 | 11 | 05-14 (10); 05-08 (7) + 05-14 (10) |
| 05-15 | 12 | 05-13 (9), 05-18 (11) |
| 05-16 | 13 | 05-14 (10), 05-15 (12), 05-17 (11) |
| 05-10, 05-21 | 14 | 05-14/15/16 (10/12/13); 05-16 (13) |
| 05-19 | 15 | 05-10 (14), 05-16 (13), 05-17 (11), 05-18 (11) |
| 05-20 | 16 | 05-13, 05-14, 05-16, 05-19 (all ≤ 15) |
| 05-11 | 17 | 05-10, 05-13, 05-16, 05-19, 05-20 (all ≤ 16) |

No cycle, no back-edge. 05-18's explicit rejection of a direct 05-16 dependency (`05-18-PLAN.md:47-48`) is correct reasoning — 05-16 → 05-15 → 05-18 already exists, so the suggested edge would have closed a cycle.

**The bin/lib target seam is now correctly modelled.** `engine/src/lib.rs:1-13` exports `workflow` but not `main.rs`; `main.rs:1656+`'s `query_rag` and `LancetServiceImpl` (`:859-870`) are binary-only. 05-08 creating a *binary-owned* `engine/src/tests/workflow_phase5_production.rs` (which does not exist today — `ls engine/src/tests/` returns only `workflow_phase5.rs`) and 05-18 moving only the generic module to the library target is the right structural resolution, and 05-16/05-20 re-run all four production tests after their adapter changes (`05-16-PLAN.md:126-129`, `05-20-PLAN.md:106-109`).

**05-08's Task 1 guard is the strongest in the set.** It extracts the `query_rag` and `build_production_workflow` regions by regex, requires all five real service fields (`self.embedder`, `self.database`, `self.bm25_index`, `self.reranker`, `self.generator` — all verified present at `main.rs:859-870`), requires ≥7 `Some(` slots against the seven-field `WorkflowDependencies` (`workflow/mod.rs:111-120`), counts exactly five `add_node` calls, asserts positional D-06 ordering, and rejects both `Fake*` and `execute_inline_query_rag_remainder`. A library-only change cannot satisfy it.

**05-13's provider analysis is exactly right.** `execute_one_call` calls `check_supported_parameters()` unconditionally at `openrouter.rs:376`; that function has no timeout, no cache, and maps every `reqwest` error — including `is_timeout()` — to `GenerationErrorKind::SupportedParameters` (`:297-302`), which `generate.rs:73-76` treats as non-retryable. A transient DNS blip currently suppresses the D-12 mandated retry. The fix targets the precise mechanism.

**05-11's cross-runtime guard is now function-scoped** (`(?s)func\s+TestRAGQueryCrossRuntime\b.*?(?=\nfunc\s|\z)`) and requires `enginePath` and `LANCET_OPENROUTER__CHAT_ENDPOINT` inside the extracted region — both of which exist only inside that function today (`main_test.go:2167`, `:2205`). The harness it builds on is real and non-skippable: it runs `cargo build` and `t.Fatalf`s if the binary is missing (`:2160-2177`).

**05-12's preservation guard is machine-checkable and now correctly path-scoped.** `git diff --check -- <14 frozen paths>` no longer collides with 05-08 editing `engine/src/main.rs` in the same wave.

---

## 3. Concerns

### HIGH-1 — `buf generate` with `clean: true` deletes `engine/src/pb/mod.rs`, and 05-17 has no machine check for it

`buf.gen.yaml:2` sets `clean: true`, and the prost/tonic plugins both output to `engine/src/pb` (`:4-9`). `engine/src/pb/mod.rs` is **hand-written module glue** living inside that output directory:

```rust
pub mod lancet { pub mod v1 { include!("lancet/v1/lancet.v1.rs"); } }
```

It is not produced by any plugin. Running `buf generate` from the repo root wipes `engine/src/pb` and removes it, after which `engine/src/main.rs:47` (`use engine::pb::lancet::v1::...`) and the entire engine crate fail to compile.

This is a *recurring, previously-realized* hazard: `05-VERIFICATION.md:201` records that "`engine/src/pb/mod.rs` was hand-restored per the 05-07 SUMMARY." 05-17 acknowledges it in prose — acceptance criterion five states "the existing `engine/src/pb/mod.rs` module glue remains present and unchanged … Buf generation does not silently remove it" — but its `<verify>` block checks only the four generated artifacts and never `Test-Path engine/src/pb/mod.rs`, and `files_modified` omits the file entirely. The one acceptance criterion protecting a whole-crate build break is the only one with no corresponding guard.

### HIGH-2 — 05-08 mandates a typed graph-fact carrier but does not own `engine/src/workflow/ports.rs`

05-08 Task 2 requires: "Add a typed graph-fact carrier using the existing `prompt::GraphFactBlock` representation … to WorkflowContext, make ExtractGraphContext populate it." `ExtractGraphContextNode`'s only graph source is `GraphQueryPort`, whose signature is

```rust
fn query_graph<'a>(…) -> BoxFuture<'a, Result<String, NodeError>>;   // ports.rs:39-45
```

A `String` cannot populate `Vec<GraphFactBlock>`. The trait must change — and `engine/src/workflow/ports.rs` is not in 05-08's `files_modified` (which lists `main.rs`, `workflow/mod.rs`, the four node files, and three test files). The plan's own Task 2 guard (`if ($production -notmatch 'graph_facts|GraphFactBlock')`) will therefore fail against a file inventory that forbids the change needed to satisfy it. `WorkflowContext` itself is fine — it lives in `workflow/mod.rs:29-48`, which *is* owned.

### HIGH-3 — 05-11 requires a graph-fact marker the cross-runtime fixture cannot produce, and no plan owns the seeder

05-11 Task 1 requires "the running mock provider to observe the graph-fact marker in the outbound generation request." Tracing that end-to-end:

- `attempt_graph_augmentation` reads `database.entities_table()` (`main.rs:1056`) and, for edges, `entity_edges_table()` — the 04.1 restructured schema.
- The cross-runtime fixture is seeded by `engine/src/bin/seed_rag_fixture.rs`, which touches `documents_table` (`:73`), `nodes_table` (`:74`, chunks), and `edges_table` (`:75`). `grep -c entities engine/src/bin/seed_rag_fixture.rs` returns **0**.
- With no entities, graph augmentation returns `NoMatchFound`, graph facts are empty, and the mock's content check (`main_test.go:2117`) returns HTTP 400 — the same mechanism that currently enforces `DENSE_FIXTURE_MARKER` / `LEXICAL_FIXTURE_IDENTIFIER_2026`.

`engine/src/bin/seed_rag_fixture.rs` appears in no plan's `files_modified` across 05-08 … 05-21. As written, `TestRAGQueryCrossRuntime` fails deterministically at wave 17 — the last wave, after everything else is green.

### HIGH-4 — 05-16's `bm25_index` type change breaks 17 construction sites in a file it does not own

05-16 Task 2 requires "`Arc<RwLock<Arc<Bm25Index>>>` or an equivalent existing ownership pattern." The field is declared `Arc<tokio::sync::RwLock<Bm25Index>>` (`main.rs:864`). `grep -rn "bm25_index: Arc::new"` returns **19 sites across two files**: 2 in `engine/src/main.rs` (owned) and **17 in `engine/src/tests.rs`** (e.g. `:338`, `:878`, `:1862`, `:1941`), which is *not* in 05-16's `files_modified` (`main.rs`, `workflow/mod.rs`, `nodes/graph_context.rs`, `nodes/retrieve.rs`, `tests/workflow_phase5.rs`, `tests/workflow_phase5_production.rs`). Every one of those literals stops compiling, and 05-16's own verify block runs four `--bin engine` tests that will fail to build.

### MEDIUM-1 — 05-16's BM25 acceptance criterion tests a writer that does not exist in production

The lock-across-await fix itself is correct and worth doing — holding a read guard across an unbounded, uncancellable await (`main.rs:1311-1320`) is wrong regardless of who else contends. But the acceptance criterion — "A stalled retrieval does not wedge a concurrent BM25 ingestion/write operation" — implies a production writer. There is none: `grep -rn "bm25_index.write"` over `engine/src` returns **zero hits**, and the only non-test build site is `Bm25Index::from_table` at `main.rs:3077`, executed once at startup and never rebuilt. The test must synthesize its own `.write()` contender. That is acceptable, but the criterion should say so rather than asserting a property of an ingestion path that isn't wired.

### MEDIUM-2 — 05-09 Task 2's file ownership can strand production-builder tests in a file 05-18 later relocates

05-09 (wave 8) lists `engine/src/tests/workflow_phase5.rs` in Task 2's `<files>` and instructs "fast semantic cases that exercise the production builder from 05-08." The production builder lives in `main.rs` (binary-only). At wave 8 `workflow_phase5.rs` is bin-registered (`engine/src/tests.rs:11` — `pub mod workflow_phase5;`), so such tests compile. At wave 11, 05-18 moves that exact file to the library target, where `build_production_workflow` is unreachable. 05-18's guard would surface this as a compile failure (its `cargo test --lib -- --list` exits non-zero), so it is caught — but it is caught as a wave-11 breakage rather than prevented. 05-09 Task 1 correctly scopes its production test to the binary-owned module; Task 2 should carry the same constraint explicitly.

### MEDIUM-3 — 05-17 and 05-16 both claim ownership of populating the variant provenance fields in `retrieve.rs`

05-17 Task 2 says to "populate `variant_count` and ordered `variant_identities` at the production retrieve-node boundary" (`files_modified` includes `nodes/retrieve.rs`). 05-16 Task 2 says to "Set the count equal to the accepted reformulation count and the identities to the corresponding reformulated query strings in order" (same file). Both cannot be the first writer. On the positive side, 05-17's literal coverage claim checks out: the only non-generated `RetrievalSnapshot` construction sites are `engine/src/workflow/nodes/retrieve.rs` (1), `engine/src/main.rs` (2), and `gateway/main_test.go` (3) — all three files are in 05-17's inventory. The Rust literals use exhaustive field initialization (`retrieve.rs:145-155`), so adding tags 10/11 does break them, which is exactly what 05-17 is guarding.

### MEDIUM-4 — 05-10's 19-field checkpoint is a real storage and payload commitment with no bound

05-10 Task 2 enumerates 19 fields including `query_embedding` and `evidence_blocks`. `query_embedding` is a 2048-dimension `Vec<f32>` (fixture at `tests/workflow_phase5.rs:85` uses `vec![0.1; 2048]`); serialized to JSON text that is tens of kilobytes. `evidence_blocks` carries full chunk text. That payload crosses the wire as `CheckpointEvent.context_snapshot` (a proto3 `string`, `lancet.proto:181`) through a 100-slot `mpsc` channel (`main.rs:1703`), then into a `jsonb NOT NULL` column (`schema.sql:51`) retained indefinitely by D-24. Five checkpoints per query. The plan neither bounds nor acknowledges this; given the project's "high-performance systems" framing, an explicit decision (truncate embeddings, or state the accepted cost) belongs in the plan rather than emerging at runtime.

### LOW-1 — 05-12's own regex guard can be tripped by documenting the historical errors

The check `if ($raw -match 'requirements-completed:\s*\[[^\]]*(GEN-|EVENT-|RAG-)') { throw }` rejects any `requirements-completed:` line containing `GEN-`, `EVENT-`, or `RAG-`. The two errors being corrected are exactly `requirements-completed: [GEN-01, GEN-02, GEN-03, EVENT-03]` (`05-03-SUMMARY.md:46`) and `[ORCH-03, RAG-01, RAG-02]` (`05-02-SUMMARY.md:47`). Reading the action text carefully, 05-12 only *requires* recording the corrected PLAN declarations, so quoting the originals is optional — this is a drafting trap, not a contradiction. Worth one sentence of guidance in the plan so the executor doesn't hit it.

### LOW-2 — 05-15's `FakeGenerator` gating survives only by way of a known debt item

05-15 Task 2 requires gating `FakeGenerator` (`generation/mod.rs:467-512`) under `cfg(test)`, while `engine/src/tests.rs` references it **29 times**. This does not break, because `main.rs:31` declares `pub mod generation;` — the binary compiles its own copy of the generation module, with `cfg(test)` active under `cargo test --bin engine`. That is `DEBT-P3-MODULE-GRAPH` ("dual lib/bin production module graph", `STATE.md:67`) doing load-bearing work. It is correct today; it will silently stop being correct if that debt is ever paid. Worth one line in 05-15 so the dependency is explicit.

### LOW-3 — 05-08's prose and its own guard disagree about the inline remainder

Task 2's prose allows the helper to survive for isolated tests ("if a helper remains for isolated tests, it must not be callable by `query_rag`"), while its second guard throws if `execute_inline_query_rag_remainder` appears anywhere in `main.rs`. The guard is the stricter and better contract; the prose should match it. Related: `run_inline_prompt_generation_remainder` has 4 call sites across `engine/src/workflow/mod.rs` (definition, `:143`) and `engine/src/tests.rs` — both files are owned, so removal is feasible.

### LOW-4 (open question, not a claim) — server-level timeout vs. the 102s budget

`newHTTPServer` sets `ReadTimeout: 60 * time.Second` (`gateway/main.go:983`) with no `WriteTimeout`, while 05-20 derives a 102-second worst-case end-to-end budget. `/rag/query` is correctly exempted from chi's `middleware.Timeout` (route group at `main.go:471-474` vs. `:466`), so that half is closed. Whether Go's `connReader.backgroundRead` read deadline can terminate a >60s SSE response is **not verified** — I did not confirm the semantics. Flagging as an open question worth a five-minute empirical check during wave 17 rather than a finding.

---

## 4. Suggestions

1. **05-17** — add `engine/src/pb/mod.rs` to `files_modified`, and add to the Task 1 `<verify>` block, immediately after `buf generate`: assert `Test-Path engine/src/pb/mod.rs` and that its content still contains `include!("lancet/v1/lancet.v1.rs")`. Alternatively (cleaner) move the glue out of the buf output tree — e.g. declare the module inline in `lib.rs` — so `clean: true` can never reach it.
2. **05-08** — add `engine/src/workflow/ports.rs` to `files_modified` and state the target signature in Task 2's action (e.g. `query_graph(…) -> Result<Vec<GraphFactBlock>, NodeError>`, or a parallel typed method preserving the existing `String` for `graph_context`). Add a source guard asserting `ports.rs` no longer returns a bare `String` from the graph port.
3. **05-11** (or a new task in 05-08) — add `engine/src/bin/seed_rag_fixture.rs` to a plan's `files_modified` and seed `entities` / `entity_edges` rows whose `name_vector` matches the fixture query embedding, so `attempt_graph_augmentation` returns `Succeeded`. Without this the graph-fact marker requirement is unsatisfiable at wave 17.
4. **05-16** — add `engine/src/tests.rs` to `files_modified` (17 `bm25_index: Arc::new` literals), and reword the second acceptance criterion to "a stalled retrieval does not block a concurrent writer acquiring the `bm25_index` write lock (the test supplies the writer; no production rebuild path exists today)."
5. **05-09** — constrain Task 2 explicitly: any test that touches `build_production_workflow` or `LancetServiceImpl` goes in `engine/src/tests/workflow_phase5_production.rs`; only fake-port/paused-clock tests may go in `engine/src/tests/workflow_phase5.rs`.
6. **05-16 / 05-17** — state that 05-17 introduces the fields *and* the initial production population, and 05-16 only adds the auditability assertions, so `retrieve.rs:145-155` has one owner.
7. **05-10** — add an explicit decision on `query_embedding` and `evidence_blocks` in the checkpoint payload (bound, elide, or accept-and-document), since D-24 retains every row indefinitely.
8. **05-12** — note in the action that quoting the erroneous historical `requirements-completed:` lists verbatim will trip the plan's own regex guard.

---

## 5. Coverage Assessment

Mapped independently against `ROADMAP.md:317-323` and `05-VERIFICATION.md`, not against the prior review.

| Roadmap success criterion | Plans | Assessment |
|---|---|---|
| 1. RAG pipeline formalized into a defined state machine | 05-08, 05-14, 05-16 | **Covered by design; blocked by HIGH-2.** Five-node registration, real adapters, and D-06 ordering are guarded at source level. The graph-fact half cannot be implemented under 05-08's current file inventory. |
| 2. Workflow events stream Rust → Go → Client | 05-08, 05-10, 05-17, 05-19, 05-11 | **Covered; blocked by HIGH-3 at wave 17.** Typed delivery, terminal idempotence, one-source ordinals, failure-terminal notices, and post-open `stream_error` frames are all owned. The end-to-end proof cannot pass without a graph-seeded fixture. |
| 3. Node timeouts and retries handle failures predictably | 05-09, 05-13, 05-14, 05-20 | **Covered.** Seven typed settings with `deny_unknown_fields`, stream-drop cancellation, dedicated 5s preflight hoisted outside the node timer, the `102000 = 97000 + 5000` derivation (graph node counted once at 15s with 10s+4s nested — arithmetic checks out), and both 4999ms/9999ms pre-deadline regressions. The prior cycle's live-overlay concern is genuinely closed: 05-09 now commits 5000/10000/10000/4000/15000/2000 upstream and asserts `NodeStarted{GenerateAnswer}` before the 7000ms timeout, with `generation_timeout_secs = 30` outlasting it. |
| 4. Snapshots capturable for debugging | 05-10, 05-11, 05-16 | **Covered.** 19-field serialization, explicit `DispatchPending` ownership, drain-on-close, context-honoring sink, isolated-schema PostgreSQL tests. MEDIUM-4 is a cost concern, not a coverage gap. |
| 5. QueryReformulator pass-through in the state machine | 05-08, 05-14 | **Covered.** Retained on the production path with typed `NodeKind::ReformulateQuery` and early nine-variant admission (correctly moved ahead of `NodeCompleted`, fixing the current `runner.rs:180-201` completed-then-failed sequence). |

**Review-ledger coverage** (`05-REVIEW.md`, 8 CR / 14 WR / 5 IN): every finding has a named owner. CR-01/04 → 05-09; CR-02/03 → 05-08; CR-05 → 05-10; CR-06/07/08 → 05-11; WR-01 → 05-14; WR-02/04 → 05-13 + 05-10; WR-03/13 → 05-10; WR-05 → 05-08; WR-06 → 05-16; WR-07 → 05-16 + 05-19; WR-08/09 → 05-16 + 05-17; WR-10/11 → 05-15; WR-12 → accepted under D-24; WR-14 → 05-16 (with MEDIUM-1's caveat); IN-01/04 → 05-14 + 05-08; IN-02/03 → 05-21; IN-05 → 05-20 (now covering **both** named tests — `workflow_phase5_reformulate_predeadline_4999ms_no_timeout` and `workflow_phase5_retrieve_predeadline_9999ms_no_timeout`, `05-20-PLAN.md:94`). No orphans.

**Locked-decision compliance:** no regression found. D-04 (pre-stream validation), D-10 (`QueryGraph` untouched — still unary at `lancet.proto:12`, no plan modifies it), D-18/D-19, D-21, D-23–D-29 are all preserved; D-30/D-31 fences are respected, and 05-17 correctly frames `variant_count`/`variant_identities` as D-07/D-08 provenance rather than deferred metadata. One client-visible addition — 05-11's `stream_error` event with `GRPC_RECV_ERROR` / `STREAM_EOF_WITHOUT_TERMINAL` codes (neither string exists in `gateway/` today) — sits inside CONTEXT's "Claude's Discretion — exact SSE framing details" and is recorded in 05-12's errata. Defensible.

---

## 6. Risk Assessment

**MEDIUM-HIGH — on executability, not on design.**

The design risk is low. The plans target real mechanisms at real line numbers, the guards are unusually specific (05-08's region-extraction regex and 05-12's blob-hash preservation are both stronger than typical), the DAG is provably acyclic, and the two structural objections from the prior cycle have been genuinely resolved rather than papered over.

The execution risk is elevated because four defects will each stop the wave they land in, and three of them (HIGH-1, HIGH-2, HIGH-4) share one root cause: an `<action>` mandating a change to a file outside its own `files_modified`. HIGH-3 is the most consequential in scheduling terms — it fails at wave 17, the final wave, after every other gate is green, and it fails inside the one test the set relies on as its end-to-end proof.

None of the four requires re-architecting. Three are one-line additions to a `files_modified` inventory plus a guard; the fourth is a fixture-seeding task that needs an owner. With those applied, and with MEDIUM-1's acceptance-criterion wording corrected and MEDIUM-2's file scoping tightened, I would rate this set **LOW-MEDIUM** and recommend execution.


---

## Consensus Summary

Both reviewers independently examined the current additive plans 05-08 through 05-21 against HEAD `d400720` and did not use the stale `05-REVIEWS.md` as review evidence. They agree that the revised set is materially stronger than the prior version: the wave DAG is acyclic and monotonic, production five-node wiring is now guarded against the old one-node/inline path, the graph-fact transfer is explicitly asserted in the intended path, the live timeout overlay reaches `GenerateAnswer`, the cross-runtime guard is function-scoped, and the OpenRouter preflight/retry and bin/lib test-target seams are well targeted.

### Agreed Strengths

- The plans target real current production seams rather than merely expanding test-only scaffolding: `engine/src/main.rs`, `engine/src/workflow/`, `engine/src/generation/openrouter.rs`, `gateway/main.go`, checkpoint dispatch, and the generated protobuf boundaries.
- Dependency ordering from Waves 7 through 17 is internally consistent and preserves the locked Phase 5 decisions, including D-06 node ordering, D-07/D-08 variant behavior, D-09 graph degradation, D-12 retry limits, D-17 timing, and D-30/D-31 scope fences.
- 05-08's production-region/source guards, 05-09's realistic verification overlay and `GenerateAnswer` reachability assertion, 05-13's provider-error classification, 05-18's library/binary target separation, and 05-11's function-scoped cross-runtime guard are concrete improvements over the prior review cycle.
- The five roadmap success criteria are covered by design and have named focused verification, although execution remains blocked by the priority concerns below.

### Agreed Concerns

The reviewers did not converge on a shared blocker: AgY rated the revised set LOW risk and considered the prior ledger closed, while Claude rated execution MEDIUM-HIGH and identified four deterministic wave failures. Those source-cited Claude findings are therefore recorded as priority concerns rather than mislabeled as consensus approval.

### Priority Source-Grounded Concerns

- **HIGH — Protobuf generation can delete required module glue.** `buf.gen.yaml:2-9` uses `clean: true` with output under `engine/src/pb`, while `engine/src/pb/mod.rs` is hand-written glue. 05-17 protects its presence only in prose; its file inventory and automated guard omit `engine/src/pb/mod.rs`, so `buf generate` can remove the module required by `engine/src/main.rs:47`.
- **HIGH — The typed graph-fact carrier has no owning plan boundary.** 05-08 requires `GraphFactBlock` data to flow through `WorkflowContext`, but the current `GraphQueryPort` still returns `Result<String, NodeError>` in `engine/src/workflow/ports.rs:39-45`, and 05-08's owned-file lists omit `ports.rs`. Its own guard therefore requires a change outside its declared inventory.
- **HIGH — The final cross-runtime graph-fact assertion has no fixture seeder.** 05-11 requires the mock provider to observe a graph-fact marker, but `engine/src/bin/seed_rag_fixture.rs` seeds documents/chunks/edges without the entities/entity-edges needed by the graph augmentation path. No current gap-closure plan owns that fixture file, so the wave-17 end-to-end proof can fail after earlier gates pass.
- **HIGH — The BM25 ownership change omits existing construction sites.** 05-16 requires changing the production `bm25_index` ownership to an `Arc` snapshot pattern, but many `bm25_index: Arc::new(...)` fixtures remain in `engine/src/tests.rs`, which 05-16 does not own. The binary tests it invokes can therefore stop compiling.
- **MEDIUM — Additional execution clarity is needed.** 05-16's writer-progress acceptance test should state that the test supplies the writer because no production BM25 write path exists; 05-09 should keep production-builder tests in the binary-owned module that 05-18 does not move; 05-16/05-17 should assign one owner for variant provenance population; and 05-10 should explicitly bound or accept the retained size of 19-field checkpoint payloads containing embeddings and evidence text.

### Divergent Views

- AgY assessed the plans as LOW risk and emphasized architectural fidelity, staged dependencies, and complete prior-gap disposition. It additionally raised a medium gateway client-disconnect/SSE write concern and low dead-code/drop-guard concerns.
- Claude assessed the plans as MEDIUM-HIGH execution risk, with the four HIGH findings above and lower-severity guard/ownership issues. Claude's findings cite exact file inventories, source signatures, fixture rows, and the specific wave where each failure would appear; they should control the next planning revision until disproved or owned.

### Recommended Planning Follow-up

Before execution, revise the additive plans to: (1) guard or relocate `engine/src/pb/mod.rs` around `buf generate`; (2) give 05-08 ownership of the typed graph-port/carrier change; (3) give a plan ownership of graph-bearing fixture seeding for the cross-runtime marker; (4) include `engine/src/tests.rs` or otherwise make the BM25 ownership migration compile-safe; and (5) tighten the 05-09/05-16/05-17 ownership and checkpoint-payload wording. Then rerun an independent plan checker/review before executing the phase.