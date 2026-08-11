---
phase: 5
reviewers: [codex, antigravity]
reviewed_at: 2026-08-11T08:44:40Z
plans_reviewed:
  - 05-01-PLAN.md
  - 05-02-PLAN.md
  - 05-03-PLAN.md
  - 05-04-PLAN.md
  - 05-05-PLAN.md
---

# Cross-AI Plan Review — Phase 5

## Codex Review

# Phase 5 Plan Review

## Summary

The revised plans have a strong architecture and address most earlier review findings: the graph-before-retrieval order is correct, the D-03 short-circuit preserves existing response semantics, Tier 1 tests use the existing in-process Rust pattern, and client-visible events use reliable delivery. However, the phase is not execution-ready. Plan 05-05 contains two compile-level contract defects, and the checkpoint sidecar design still allows large snapshots to backpressure the primary query stream. Additional gaps remain around cancellation supervision, retry testability, timeout validation, and exact context-field contracts.

## Strengths

- The plans correctly preserve the shipped pipeline order: graph augmentation at [`engine/src/main.rs:1426`](/D:/Repos/lancet/engine/src/main.rs:1426) precedes dense retrieval at [`engine/src/main.rs:1450`](/D:/Repos/lancet/engine/src/main.rs:1450), and 05-02 explicitly wires the nodes in that order at [05-02-PLAN.md:168](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:168).

- The D-03 zero-evidence behavior is grounded in the existing implementation at [`engine/src/main.rs:1508`](/D:/Repos/lancet/engine/src/main.rs:1508). The plans preserve its notice, snapshot, and session identity through `WorkflowCompleted`, rather than fabricating an answer.

- The first-frame prefetch is an important correction. Plan 05-01 explicitly performs `Recv()` before committing SSE headers at [05-01-PLAN.md:313](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:313), addressing the difference between gRPC stream creation and delivery of a server-side validation error.

- The in-process Rust test strategy is appropriate. Existing tests already call the service handler directly, and the plan avoids generating a Rust client while `buf.gen.yaml` intentionally uses `no_client=true`.

- Reliable `.send(...).await` for client-visible workflow events is the correct consequence of the event-contract requirements. Plan 05-01 makes this explicit at [05-01-PLAN.md:288](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:288).

- Plan 05-02 gives the cross-variant RRF merge a concrete formula and exact-score test requirement, reusing the existing fusion implementation at [`engine/src/retrieval/fusion.rs:58`](/D:/Repos/lancet/engine/src/retrieval/fusion.rs:58).

- Plan 05-05 correctly recognizes that sqlc reads `db/schema.sql`, not Atlas HCL. The plan updates both schema sources at [05-05-PLAN.md:130](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:130), consistent with [`gateway/sqlc.yaml:3`](/D:/Repos/lancet/gateway/sqlc.yaml:3).

## Concerns

- **HIGH — Checkpoint trace identity is inconsistent and will not compile.** Plan 05-01 defines `Checkpoint` with only `node_name` and `context_snapshot_json` at [05-01-PLAN.md:257](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:257), while 05-05 calls `cp.TraceId` at [05-05-PLAN.md:155](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:155). The trace ID is on the enclosing `WorkflowEvent`, not the checkpoint sidecar. Pass `event.TraceId` separately to `persistCheckpoint`, or add the field consistently to the protobuf contract.

- **HIGH — Full checkpoint serialization is not implementable as written.** 05-05 serializes the entire `WorkflowContext` with `serde_json::to_string` at [05-05-PLAN.md:152](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:152). But `QueryRequest` currently lacks `Serialize` at [`engine/src/retrieval/mod.rs:343`](/D:/Repos/lancet/engine/src/retrieval/mod.rs:343), and generated protobuf types such as `Notice` are prost-only at [`engine/src/pb/lancet/v1/lancet.v1.rs:68`](/D:/Repos/lancet/engine/src/pb/lancet/v1/lancet.v1.rs:68). Adding derives directly to generated files will be lost on the next `buf generate`. Use an explicit serializable checkpoint DTO, or configure protobuf generation with stable serde attributes.

- **HIGH — D-27 is only partially isolated.** Detaching the PostgreSQL insert at [05-05-PLAN.md:155](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:155) prevents the database write itself from blocking the Go handler. However, the full snapshot is still attached to the reliable primary `NodeCompleted` event at [05-05-PLAN.md:154](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:154). A large snapshot can block Rust's event channel while Go writes or flushes SSE, so query progression can still be delayed by transport backpressure. The plan needs a bounded snapshot policy or a separate checkpoint transport path.

- **MEDIUM — Cancellation supervision is underspecified.** Plan 05-01 requires a `tx.closed()` watcher at [05-01-PLAN.md:288](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:288), but does not define the supervisor task that owns the runner, receiver closure, cancellation token, and terminal outcome. This is especially important because the current handler is unary at [`gateway/main.go:654`](/D:/Repos/lancet/gateway/main.go:654), while the new implementation will return immediately after spawning the workflow. Define one explicit `tokio::select!` supervisor and test cancellation as internal termination when the receiver is dropped.

- **MEDIUM — The Go streaming interface and trailer ownership need a concrete type.** The current interface returns a unary response at [`gateway/main.go:203`](/D:/Repos/lancet/gateway/main.go:203), and the current implementation owns trailer metadata locally at [`gateway/main.go:280`](/D:/Repos/lancet/gateway/main.go:280). The plan says to return a stream plus a "lazily-consulted trailer" at [05-01-PLAN.md:313](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:313), but does not specify the wrapper or method signature. Define a concrete stream wrapper exposing both `Recv()` and trailer metadata. Also obtain `http.Flusher` before committing the 200 response.

- **MEDIUM — Cargo lockfile and task ordering are incomplete.** Plan 05-01 adds direct dependencies but does not list `engine/Cargo.lock` among modified files. The direct dependency declaration is currently at [`engine/Cargo.toml:7`](/D:/Repos/lancet/engine/Cargo.toml:7), while the locked package dependency list is recorded in `engine/Cargo.lock`. Its `cargo build --locked` acceptance criterion will fail unless the lockfile is regenerated. Additionally, Task 1 updates `EngineSettings` literals at [05-01-PLAN.md:261](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:261) before the new settings field is introduced in the later Rust task.

- **MEDIUM — RetrieveHybrid's context contract remains ambiguous.** 05-02 allows the executor to choose between `vector_results`/`bm25_results` and a merged field at [05-02-PLAN.md:199](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:199), while 05-03 repeats "whatever" field shape at [05-03-PLAN.md:148](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:148). Prompt assembly and checkpoint fidelity depend on this state. Define an exact `final_candidates` field and separate raw/per-variant fields before execution.

- **MEDIUM — Timeout invariants are configuration claims, not runtime guarantees.** 05-02 requires `graph_outer_timeout_ms > graph_timeout_ms` at [05-02-PLAN.md:167](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:167), but the current `EngineSettings` has no workflow section at [`engine/src/main.rs:177`](/D:/Repos/lancet/engine/src/main.rs:177). Add validation for zero, overflow, and the inner/outer ordering, including environment overrides.

- **MEDIUM — The retry tests overclaim what `GenerationRequest` proves.** The plan asks the fake to compare model, temperature, and top-p at [05-03-PLAN.md:21](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:21), but `GenerationRequest` currently contains none of those fields at [`engine/src/generation/mod.rs:374`](/D:/Repos/lancet/engine/src/generation/mod.rs:374). Also, the existing `FakeGenerator` has no delay or synchronization hook at [`engine/src/generation/mod.rs:459`](/D:/Repos/lancet/engine/src/generation/mod.rs:459), despite scenarios requiring timeout and cancellation between attempts. Add deterministic barriers/delays and either compare only request fields that exist or record the fully materialized provider payload.

- **MEDIUM — Retry policy is broader than the stated transient-failure intent.** 05-03 retries both transport and grounding/schema failures at [05-03-PLAN.md:176](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:176), apparently for every first-attempt error. Existing `GenerationErrorKind` distinguishes provider, timeout, schema, invalid-request, and cancellation classes. Explicitly exclude cancellation and permanent request/configuration errors from retry.

- **LOW/MEDIUM — Checkpoint tests need explicit database isolation and migration commands.** 05-05 requires a live table but leaves the Atlas command unspecified at [05-05-PLAN.md:130](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:130). Existing integration tests use isolated schemas; the new tests should create the checkpoint table in the same per-test schema and use deterministic synchronization for detached goroutines. Given indefinite retention, add a `(trace_id, created_at)` index or document the query-performance tradeoff.

## Suggestions

1. Correct the protobuf/Go checkpoint identity contract first: pass the enclosing event's `trace_id` into `persistCheckpoint`.
2. Replace whole-struct serde with an explicit versioned `WorkflowCheckpointSnapshot` DTO.
3. Decide whether full checkpoint payloads remain on the primary event stream. If so, add a size limit and measure serialization/send latency.
4. Define a concrete Rust workflow supervisor and Go stream wrapper, including trailer access and receiver-drop cancellation.
5. Add `Cargo.lock` regeneration and move all workflow settings/schema changes into the same compilation step.
6. Freeze the exact `WorkflowContext` fields before 05-02/05-03 execution and validate all timeout relationships.
7. Add deterministic fake-generator barriers and narrow retryable error categories.
8. Specify the Atlas apply command and extend the existing isolated PostgreSQL test fixture to include `workflow_checkpoints`.

## Risk Assessment

**Overall risk: HIGH.** The architectural direction is sound, but 05-05 currently has compile-level defects, and the checkpoint sidecar can still impose backpressure on the query path despite the detached database write. Plans 05-01 through 05-04 are viable after tightening their contracts and cancellation/test mechanics; the phase should not begin execution until the checkpoint schema, serialization, trace identity, and stream-supervision issues are resolved.

---

## Antigravity Review

# Plan Review: Phase 5 (State Machine & Workflow Events)

## Summary

The Phase 5 plan set (`05-01` through `05-05`) delivers a comprehensive, type-safe Rust state machine (`WorkflowRunner` / `Node`) and Go SSE streaming transport for the fixed RAG path (`QueryRAG`). It faithfully implements all locked decisions (D-01 through D-31) and phase requirements (ORCH-01 through ORCH-05). The plans demonstrate exceptional engineering rigor by directly resolving prior peer review feedback—substituting lossy `try_send` calls with reliable channel `.send().await`, synchronizing `gateway/db/schema.hcl` and `gateway/db/schema.sql` for sqlc codegen, codifying an explicit cross-variant RRF fusion formula in `engine/src/retrieval/fusion.rs`, and defining injectable port seams (`GraphQueryPort`, `DenseRetrievalPort`) with extended `FakeGenerator` request recording for byte-identical retry verification.

## Strengths

- **Direct Resolution of Review Concerns & Edge Cases**: The plans incorporate solutions for complex edge cases raised in previous reviews, including sqlc schema source alignment (`schema.sql`), eliminating lossy `try_send` event drops, and adding `GenerationRequest` recording to `FakeGenerator` for exact field-by-field retry assertions.
- **Clean Service & State Boundaries (D-04, D-26)**: Pre-stream request validation (`ReceiveQuery`) remains synchronous in the tonic gRPC handler, returning standard gRPC `Status` with trailer metadata (`d1_status`) prior to stream initiation. Go retains sole ownership of PostgreSQL for checkpoint writes via detached goroutines (`go a.persistCheckpoint(cp)`), avoiding DB driver complexity inside the Rust engine.
- **Fault Isolation & Graceful Degradation (D-03, D-09)**: `ExtractGraphContextNode` wraps graph context extraction in an inner timeout (`graph_timeout_ms = 15s`) and degrades to an empty graph context on both logical failure and timeout without aborting the query. `RetrieveHybridNode` correctly implements the D-03 zero-evidence short-circuit to send `WorkflowCompleted{success: true, notices: [NO_EVIDENCE], snapshot: Some(...)}` immediately without entering downstream prompt assembly or generation nodes.
- **Deterministic Multi-Tier Test Strategy**: Tier 1 tests in `engine/src/tests.rs` leverage in-process trait doubles (`FakeGraphQueryPort`, `FakeDenseRetrievalPort`, `FakeGenerator`, `StallingTestNode`) to verify timeout arithmetic, cancellation, and byte-identical retry requests deterministically without external process flakiness. Tier 2 tests in `gateway/main_test.go` validate end-to-end SSE framing, DB snapshot fidelity, and cancellation atomicity against a live Postgres instance.
- **Event Granularity & Privacy Controls (D-01, D-02, D-20)**: SSE client payloads strictly strip internal `checkpoint` context snapshots, while progress events maintain a predictable, forward-compatible sequence (`NodeStarted` → `NodeCompleted` → `AnswerChunk` → `FinalAnswer` → `WorkflowCompleted`).

## Concerns

- **Go Gateway Global Middleware Timeout Collision (MEDIUM)**: `gateway/main.go:464` applies `middleware.Timeout(60*time.Second)` globally across all routes in `routes()`. However, `generate_timeout_ms` is set to 65s (allowing two 30s LLM generation attempts plus slack), which means a valid query experiencing a transient LLM retry will be aborted at 60s by Chi's HTTP middleware before completing. While `05-01` and `05-RESEARCH.md` identify this risk, `05-01`'s task action must explicitly ensure `/rag/query` is exempted from the global 60s timeout via route grouping or `r.With(...)`.
- **Unbounded PostgreSQL Checkpoint Growth (LOW)**: Each `NodeCompleted` event persists a full `WorkflowContext` JSON snapshot (D-28). Per D-24, no TTL or cleanup job is included in v1. While acceptable for a local-first demo, high query volume during local testing could lead to rapid growth in `workflow_checkpoints`.
- **Cross-Variant Candidate Buffering (LOW)**: In `RetrieveHybridNode` (`05-02` Task 2), iterating over `Vec<String>` reformulation variants creates per-variant candidate lists before cross-variant RRF merging. While NoOp reformulator yields 1 variant in v1, pre-allocating candidate vectors will prevent unnecessary allocations when Phase 999.3 introduces multi-query expansion.

## Suggestions

- **Explicit Chi Route Exemption in 05-01**: Update `routes()` in `gateway/main.go` to apply `middleware.Timeout(60*time.Second)` selectively to `/documents` and `/health`, leaving `/rag/query` governed by client disconnects (D-16) and Rust node timeouts (D-17).
- **Schema Sync Verification**: Ensure `sqlc generate` and Atlas migration apply steps in `05-05` verify that both `gateway/db/schema.hcl` and `gateway/db/schema.sql` stay strictly synchronized.

## Risk Assessment

- **Overall Risk Level**: **LOW**
- **Justification**: The 5-plan wave breakdown is modular, well-ordered, and achievable. The design strictly respects domain boundaries, avoids black-box frameworks, and enforces critical invariants (retry bounds, honest failure propagation, zero-evidence short-circuiting) through deterministic unit and integration test suites.

---

## Consensus Summary

The two reviewers strongly agree on what the plans get *right*, but diverge sharply on overall execution readiness — Codex rates the plan set **HIGH risk** and not execution-ready; Antigravity rates it **LOW risk** and ready to proceed. Codex's HIGH-severity findings are specific, line-cited, compile-level claims that Antigravity's review does not address at all (neither confirming nor refuting them), so they should be treated as open and verified directly against source before execution, not resolved by the risk-level disagreement alone.

### Agreed Strengths
- **Shipped pipeline order preserved.** Both reviewers confirm graph-before-retrieval order matches existing code (`engine/src/main.rs:1426` vs `:1450`) and is correctly wired in 05-02.
- **D-03 zero-evidence short-circuit correctly implemented.** Both confirm `WorkflowCompleted{success: true, notices, snapshot}` fires without entering `AssemblePrompt`/`GenerateAnswer`, preserving today's response semantics.
- **Reliable event delivery.** Both explicitly credit the plans for replacing lossy `try_send` with `.send().await` for client-visible workflow events — a fix from the prior review round.
- **sqlc/Atlas schema sync in 05-05.** Both flag that `db/schema.sql` (sqlc's actual source) and the Atlas HCL schema are kept in sync, and both suggest verifying this stays true (Antigravity as a suggestion, Codex implicitly via its DB-isolation concern).
- **In-process Tier 1 test strategy.** Both approve of the no-spawned-process, no-generated-client `engine/src/tests.rs` approach reusing existing fixture patterns.

### Agreed Concerns
- No single concern was raised at the same severity by both reviewers. The closest overlap is checkpoint/database durability: Codex raises DB-isolation and migration-command gaps for `workflow_checkpoints` (LOW/MEDIUM); Antigravity separately raises unbounded checkpoint growth with no TTL (LOW). Both are checkpoint-adjacent but distinct issues — treat as two separate findings, not one confirmed-by-two-reviewers concern.

### Divergent Views
- **Checkpoint trace-ID compile defect — CONFIRMED against plan text (Codex HIGH, unaddressed by Antigravity).** Directly verified: `05-01-PLAN.md:257` defines the proto `Checkpoint` message with only `node_name` and `context_snapshot_json` fields (trace_id lives on the enclosing `WorkflowEvent`, not `Checkpoint`). `05-05-PLAN.md:155` then calls `a.store.InsertWorkflowCheckpoint(ctx, cp.TraceId, cp.NodeName, []byte(cp.ContextSnapshotJson))` — `cp.TraceId` has no backing field in the message 05-01 defines. As written, this will not compile. Codex's finding is correct; Antigravity's LOW-risk verdict did not catch this. **This must be fixed before 05-05 executes** — either add `trace_id` to the `Checkpoint` proto message in 05-01, or thread `event.TraceId` into `persistCheckpoint` as a separate parameter instead of reading it off `cp`.
- **Checkpoint `WorkflowContext` serialization defect (Codex HIGH, not independently re-verified but plausible).** Codex further claims `serde_json::to_string(ctx)` on the full `WorkflowContext` (05-05-PLAN.md:153) won't compile because `QueryRequest` (05-01's context field, `engine/src/retrieval/mod.rs:343`) and generated prost message types like `Notice` aren't `Serialize`. Not independently confirmed line-by-line here, but consistent with prost's default codegen (no serde derives unless configured) — treat as high-confidence and verify `Serialize` is actually derivable for every `WorkflowContext` field before 05-05 executes, per Codex's suggested fix (an explicit versioned DTO rather than serializing the struct directly).
- **Checkpoint backpressure on the primary event channel (Codex HIGH, not raised by Antigravity).** Codex argues the full context snapshot still rides the reliable `NodeCompleted` event even though the Postgres write itself is detached (D-27), so a large snapshot can still stall query progression via channel backpressure. Antigravity's review doesn't engage with this mechanism at all. Worth an explicit design decision: either bound snapshot size or move the snapshot payload off the primary SSE-forwarded channel.
- **Chi route-timeout exemption: settled fix vs. residual risk.** Antigravity flags the global 60s `middleware.Timeout` colliding with the 65s generation-retry budget as an active MEDIUM risk requiring an explicit fix in 05-01. Codex doesn't mention this at all in its concerns list — either because it considers 05-01's route-scoped-timeout language (`sized to at least 120s`) already sufficient, or because it simply didn't focus there. Given Antigravity's specific citation (`gateway/main.go:464`) and the 65s/60s numeric collision, verify the exemption is concretely implemented (not just described) before treating this as closed.
- **Overall risk level.** Codex: HIGH, blocking on 05-05's compile-level defects and cancellation-supervision gaps. Antigravity: LOW, citing strong adherence to locked decisions and a solid test strategy. The disagreement is not really about the quality of 05-01–05-04 (both are positive there) — it hinged on whether Codex's specific 05-05 claims about `Checkpoint.TraceId` and `WorkflowContext` serialization are accurate. That factual question is now resolved for the `TraceId` claim (confirmed real, see above), which tips this toward Codex's HIGH rating: 05-05 is not execution-ready as written, regardless of how sound 05-01–05-04 are.
