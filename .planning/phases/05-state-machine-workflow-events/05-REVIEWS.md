---
phase: 5
reviewers: [codex, antigravity]
reviewed_at: 2026-08-10T21:25:58Z
plans_reviewed:
  - 05-01-PLAN.md
  - 05-02-PLAN.md
  - 05-03-PLAN.md
  - 05-04-PLAN.md
  - 05-05-PLAN.md
---

# Cross-AI Plan Review — Phase 5

## Codex Review

# Summary

The plans show strong architectural judgment and good awareness of the existing pipeline, but they are not execution-ready yet. The highest risks are in 05-01: streaming validation errors will likely become HTTP 200 SSE responses, the proposed Rust integration harness lacks a generated client and fake-provider injection path, and the new event contract drops existing session/no-evidence response data. Additional blockers include a 05-02/05-04 dependency mismatch, contradictory event ordering in 05-03, and a 05-05 sqlc schema omission. Overall risk is **HIGH** until these are resolved.

## Strengths

- **05-01 preserves the important validation boundary.** The plan correctly keeps request/session validation before workflow execution, matching the current handler at [engine/src/main.rs:1346](/D:/Repos/lancet/engine/src/main.rs:1346) and existing trailer handling at [gateway/main.go:280](/D:/Repos/lancet/gateway/main.go:280).

- **05-02 follows the shipped graph-before-retrieval order.** The current code performs graph augmentation at [engine/src/main.rs:1426](/D:/Repos/lancet/engine/src/main.rs:1426) before dense retrieval at [engine/src/main.rs:1450](/D:/Repos/lancet/engine/src/main.rs:1450); the plan explicitly preserves this at [05-02-PLAN.md:155](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:155).

- **The plans reuse existing domain mechanisms rather than introducing unnecessary frameworks.** The `Generator`/`FakeGenerator` seam already exists at [engine/src/generation/mod.rs:459](/D:/Repos/lancet/engine/src/generation/mod.rs:459), RRF fusion is centralized at [engine/src/retrieval/fusion.rs:58](/D:/Repos/lancet/engine/src/retrieval/fusion.rs:58), and prompt packing is already implemented at [engine/src/prompt.rs:255](/D:/Repos/lancet/engine/src/prompt.rs:255).

- **05-03 has a clear no-fabrication goal.** The retry ceiling and honest failure behavior are explicit at [05-03-PLAN.md:22](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:22) and [05-03-PLAN.md:182](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:182).

- **05-04 correctly identifies the missing retrieval test seams.** Introducing ports for graph and dense retrieval is a justified response to the current concrete dependencies and is better than pretending real LanceDB latency tests are deterministic.

## Concerns

- **HIGH — 05-01 does not actually preserve HTTP 4xx behavior for pre-stream validation failures.** The current Go client has a unary `QueryRAG` method at [gateway/main.go:207](/D:/Repos/lancet/gateway/main.go:207), but the existing streaming precedent uses `NewStream` and defers status delivery until stream operations at [gateway/proto/lancet/v1/lancet_grpc.pb.go:57](/D:/Repos/lancet/gateway/proto/lancet/v1/lancet_grpc.pb.go:57). The plan handles errors from opening the stream, then writes SSE headers before entering `stream.Recv()` at [05-01-PLAN.md:276](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:276). A Rust validation error will therefore likely arrive from `Recv()` after HTTP 200 is committed, violating the plan’s own D-04 requirement.

  Fix: receive and classify the first gRPC frame/status before `WriteHeader`; only commit SSE headers after the first successful event, or add an explicit preflight validation RPC.

- **HIGH — The planned Rust Tier 1 harness cannot work with the current code-generation and crate layout.** `buf.gen.yaml` explicitly disables the Rust client with `no_client=true` at [buf.gen.yaml:15](/D:/Repos/lancet/buf.gen.yaml:15). The plan nevertheless requires `engine/tests/workflow_events.rs` to connect as a tonic client at [05-01-PLAN.md:275](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:275). Additionally, the library target exposes only modules listed at [engine/src/lib.rs:3](/D:/Repos/lancet/engine/src/lib.rs:3), while `EmbeddingProvider` is private to the binary at [engine/src/main.rs:1971](/D:/Repos/lancet/engine/src/main.rs:1971). The spawned binary always constructs OpenRouter clients and requires `OPENROUTER_API_KEY` at [engine/src/main.rs:3034](/D:/Repos/lancet/engine/src/main.rs:3034); no fake-provider injection seam exists.

  Fix: either generate a Rust client and move shared workflow/service types into the library, or make these deterministic tests in-process/unit-level. If process-level testing is required, specify a real injection mechanism, such as a configurable local mock OpenRouter endpoint.

- **HIGH — The new event contract loses existing successful-response semantics.** The current zero-evidence path returns a `QueryRAGResponse` containing `session_id`, a `NO_EVIDENCE` notice, and a retrieval snapshot at [engine/src/main.rs:1508](/D:/Repos/lancet/engine/src/main.rs:1508). The existing response schema is defined at [proto/lancet/v1/lancet.proto:103](/D:/Repos/lancet/proto/lancet/v1/lancet.proto:103). The planned `FinalAnswer` omits `session_id`, while `WorkflowCompleted` contains only `bool success` at [05-01-PLAN.md:244](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:244). Meanwhile, D-03 deliberately emits no answer events on zero evidence at [05-02-PLAN.md:200](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:200).

  Result: a successful no-evidence query cannot deliver the existing notice/snapshot/session information, and normal successful queries cannot deliver `session_id`.

  Fix: add session/terminal response data to the terminal event, or define an explicit no-evidence terminal payload while still skipping prompt assembly and generation.

- **HIGH — `WorkflowContext` omits the validated query filters and normalized query.** `QueryRequest` contains filters at [engine/src/retrieval/mod.rs:343](/D:/Repos/lancet/engine/src/retrieval/mod.rs:343), and the current dense, BM25, and prompt stages all consume that validated request at [engine/src/main.rs:1453](/D:/Repos/lancet/engine/src/main.rs:1453), [engine/src/main.rs:1480](/D:/Repos/lancet/engine/src/main.rs:1480), and [engine/src/main.rs:1552](/D:/Repos/lancet/engine/src/main.rs:1552). The planned context fields at [05-01-PLAN.md:268](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:268) contain no filters or `QueryRequest`, and the planned retrieval node fields at [05-02-PLAN.md:185](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:185) do not provide an alternative source.

  This risks dropping document/content-type filters and using raw `req.query` instead of the normalized query. It also leaves D-07 underspecified: all variants use the same embedding, but the BM25 request must use each variant’s text.

  Fix: carry the validated `QueryRequest` or its filters and normalized query in `WorkflowContext`; clone it with `query = variant` for each BM25 pass.

- **HIGH — `try_send` is applied to client-visible workflow events, not just fire-and-forget checkpoints.** The plan requires `try_send` for `NodeStarted`, terminal events, and completion at [05-01-PLAN.md:270](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:270), and explicitly accepts dropping events when full at [05-01-PLAN.md:309](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:309). The AI-SPEC’s nonblocking rule is specifically motivated by the checkpoint side channel at [05-AI-SPEC.md:266](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-AI-SPEC.md:266).

  A full channel can drop `NodeCompleted`, `NodeFailed`, or `WorkflowCompleted`, violating the exactly-one event contract. The 05-04 “never-draining receiver” test at [05-04-PLAN.md:97](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-04-PLAN.md:97) also cannot observe a `FinalAnswer` if it never drains the same channel.

  Fix: separate reliable client-event delivery from lossy/detached checkpoint persistence. Treat `Closed` as cancellation, but do not silently drop required client events on `Full`.

- **HIGH — 05-02 requires a deterministic graph-timeout test before the graph port exists.** 05-02 requires a stalling graph test at [05-02-PLAN.md:164](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:164), but its node still directly owns `DatabaseManager` at [05-02-PLAN.md:155](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:155). The injectable `GraphQueryPort` is only introduced later in 05-04 at [05-04-PLAN.md:77](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-04-PLAN.md:77).

  The plan cannot provide the claimed deterministic test in Wave 2 without either a slow real LanceDB fixture or undocumented refactoring. Also, the graph node’s inner timeout and runner timeout appear to use the same configured budget, so the outer timeout can win the race and incorrectly fail the query.

  Fix: move the graph-timeout acceptance test to 05-04, move the port seam into 05-02, or define separate inner-degrade and outer-backstop durations.

- **MEDIUM — 05-02’s cross-variant RRF semantics are not fully defined.** Existing `fuse_candidates` combines vector/BM25 ranks and weights at [engine/src/retrieval/fusion.rs:58](/D:/Repos/lancet/engine/src/retrieval/fusion.rs:58), using internal accumulation logic at [engine/src/retrieval/fusion.rs:123](/D:/Repos/lancet/engine/src/retrieval/fusion.rs:123). The new merge receives already-fused lists but is instructed to reuse the same weighted formula at [05-02-PLAN.md:184](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-02-PLAN.md:184). It does not define whether the existing vector/BM25 weights apply again, whether variants have equal weight, or how source-rank provenance is retained.

  Fix: define the outer variant-RRF score and tie-break explicitly, then test exact scores as well as order.

- **MEDIUM — 05-03 contradicts itself on answer-event ordering.** The must-have says `AnswerChunk` and `FinalAnswer` occur after `GenerateAnswer`’s `NodeCompleted` at [05-03-PLAN.md:24](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:24), while the implementation task requires them before `NodeCompleted` at [05-03-PLAN.md:183](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:183).

  Fix: choose one canonical sequence and assert it in every Rust and Go test.

- **MEDIUM — The retry tests do not prove byte-identical requests.** The plan requires identical retry parameters at [05-03-PLAN.md:21](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:21), but the existing `FakeGenerator` exposes call count and configured responses at [engine/src/generation/mod.rs:467](/D:/Repos/lancet/engine/src/generation/mod.rs:467), not the requests received. The planned scenarios at [05-03-PLAN.md:187](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:187) only require call-count assertions.

  Fix: record cloned `GenerationRequest` values in the fake and compare attempt 1 with attempt 2 field-by-field.

- **HIGH — 05-05 updates the wrong schema source for sqlc.** `sqlc.yaml` reads `db/schema.sql` at [gateway/sqlc.yaml:3](/D:/Repos/lancet/gateway/sqlc.yaml:3), and the current table definitions are in [gateway/db/schema.sql:5](/D:/Repos/lancet/gateway/db/schema.sql:5). However, the plan’s file list only includes `gateway/db/schema.hcl`, `query.sql`, and generated Go at [05-05-PLAN.md:116](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:116).

  `sqlc generate` will not know about `workflow_checkpoints` unless `schema.sql` is also updated or the sqlc source configuration changes.

  Fix: add `gateway/db/schema.sql` to the task and keep it synchronized with the Atlas source at [gateway/atlas.hcl:6](/D:/Repos/lancet/gateway/atlas.hcl:6).

- **MEDIUM — Fire-and-forget checkpoint writes have no bounded lifetime or test synchronization.** The plan explicitly uses `context.Background()` and detached goroutines at [05-05-PLAN.md:142](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:142). The gateway already uses a five-second bounded background context for compensation writes at [gateway/main.go:45](/D:/Repos/lancet/gateway/main.go:45) and [gateway/main.go:308](/D:/Repos/lancet/gateway/main.go:308).

  An unbounded database call can leak goroutines during a DB outage, while tests that query immediately after SSE completion can race the detached insert.

  Fix: use a bounded background timeout and have integration tests poll for the expected rows or expose a test-only drain hook.

- **MEDIUM — 05-04 omits AssemblePrompt from timeout coverage.** The AI-SPEC explicitly includes `AssemblePrompt` in the parametrized timeout scenario at [05-AI-SPEC.md:475](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-AI-SPEC.md:475), but 05-04 excludes it at [05-04-PLAN.md:97](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-04-PLAN.md:97). This leaves one of the five node timeout contracts untested.

  Fix: add a deterministic runner-level blocking-node test or a focused prompt-node timeout test; no production fake is necessarily required.

- **MEDIUM — New workflow configuration is missing from the configuration contract.** The example file currently contains only the existing sections at [config/config.example.toml:14](/D:/Repos/lancet/config/config.example.toml:14), and the configuration tests enumerate allowed sections and required keys at [engine/src/tests.rs:15](/D:/Repos/lancet/engine/src/tests.rs:15) and [engine/src/tests.rs:181](/D:/Repos/lancet/engine/src/tests.rs:181). The plans add workflow keys only to `config/config.toml`, beginning at [05-01-PLAN.md:244](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:244).

  Fix: update `config.example.toml`, configuration-contract tests, env override documentation, and all `EngineSettings` literals in existing tests.

- **MEDIUM — Full snapshots may become an oversized and overexposing SSE payload.** `Candidate` includes raw chunk content and is serializable at [engine/src/retrieval/mod.rs:412](/D:/Repos/lancet/engine/src/retrieval/mod.rs:412); `PackedEvidence` is also serializable at [engine/src/prompt.rs:168](/D:/Repos/lancet/engine/src/prompt.rs:168). The plan serializes the entire context at every node boundary and forwards the checkpoint sidecar through SSE at [05-05-PLAN.md:139](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:139).

  D-23 accepts raw content in local Postgres, but it does not define a payload-size limit or whether clients should receive the raw checkpoint. Repeated full prompts, candidates, graph facts, and embeddings can materially increase memory, gRPC, SSE, and database usage.

  Fix: bound or redact checkpoint fields, cap serialized size, and consider persisting the sidecar in Go without forwarding its full contents to the client.

## Suggestions

- Add a Wave 0 contract gate before 05-01:
  - finalize terminal-event/session/no-evidence semantics;
  - generate a Rust client or change the Tier 1 test architecture;
  - move shared workflow types and test seams into the library;
  - specify first-frame prefetch behavior for gateway error mapping.

- Add validated query state to `WorkflowContext`, including filters and the normalized query. Build a per-variant BM25 `QueryRequest` while retaining the single D-08 embedding.

- Separate client-facing event delivery from checkpoint persistence. Required workflow events should not be silently dropped; only the Postgres side effect should be lossy/nonblocking.

- Reorder 05-04 ahead of graph-timeout acceptance, or move the port seam into 05-02. Define distinct graph inner and runner backstop timeouts.

- Resolve the 05-03 event-order contradiction and add request-capture assertions to the retry fake.

- Add `gateway/db/schema.sql` to 05-05, then verify both `sqlc generate` and Atlas apply against the same schema.

- Bound detached checkpoint writes, wait/poll for asynchronous inserts in tests, and define a maximum serialized snapshot size.

## Risk Assessment

**Overall: HIGH.** The architecture is coherent and the plans contain valuable tests and explicit failure semantics, but several first-order assumptions currently prevent faithful implementation: streaming pre-validation, Rust client/test injection, response-contract preservation, event reliability, and sqlc generation. Resolving those in a revised Wave 0 should reduce execution risk to MEDIUM.


---

## Antigravity Review

# Cross-AI Plan Review: Phase 5 (State Machine & Workflow Events)

## 1. Summary

The Phase 5 plan suite (`05-01-PLAN.md` through `05-05-PLAN.md`) provides a well-structured, wave-sequenced implementation strategy for formalizing Lancet's fixed RAG pipeline into a Rust async state machine with streaming workflow events and PostgreSQL checkpoint persistence. It demonstrates exceptional attention to codebase details, accurately resolving prior plan inconsistencies against live code (such as correcting the pipeline node execution order in D-06 to match `engine/src/main.rs:1426` vs `1450`), preserving the D-04 synchronous pre-stream validation boundary (`engine/src/main.rs:1346-1393` and `gateway/main.go:692-711`), and introducing clean testability ports (`GraphQueryPort`, `DenseRetrievalPort`) to achieve deterministic fault-injection testing. Minor risks exist around indiscriminate channel `try_send` usage dropping client-facing answer frames under backpressure and Rust test compilation requirements for `#[ignore]` attributes, but overall the plan suite is robust, realistic, and directly satisfies requirements ORCH-01 through ORCH-05.

---

## 2. Strengths

- **Accurate Codebase Seams & Order Resolution (D-06)**: Plan 02 (`05-02-PLAN.md`) correctly identifies and resolves a contradiction in prior context documents by verifying against live code (`engine/src/main.rs:1426` graph augmentation vs `1450` dense retrieval), ensuring `ExtractGraphContextNode` executes before `RetrieveHybridNode` as required by D-06.
- **Preservation of Pre-Stream Validation Boundary (D-04)**: Plan 01 (`05-01-PLAN.md`) maintains synchronous validation in `query_rag` (`engine/src/main.rs:1354-1393`) before opening the gRPC stream. This preserves `gateway/main.go:692-711`'s `trailerError` handling for returning HTTP 400 Bad Request with `X-Lancet-*` headers on invalid requests.
- **Route-Scoped HTTP Timeout Resolution**: Plan 01 (`05-01-PLAN.md`) correctly identifies that the blanket `middleware.Timeout(60*time.Second)` at `gateway/main.go:464` would prematurely abort long-running SSE streams (where node timeouts total ~97s), and replaces it with a route-scoped timeout for `/rag/query`.
- **Infallible Graph Degradation & Timeout Alignment (D-09)**: Plan 02 (`05-02-PLAN.md`) wraps `attempt_graph_augmentation` (`engine/src/main.rs:1426-1448`) in an inner `tokio::select!` timeout race, ensuring both logical failures (`GraphAugmentationOutcome::AttemptedAndFailed`) and graph query timeouts degrade gracefully to empty graph context without failing the overall RAG query.
- **Single-Retry & Honest Failure Contract (D-11, D-12, D-13)**: Plan 03 (`05-03-PLAN.md`) enforces a hard two-attempt limit on `GenerateAnswerNode` (`engine/src/generation/mod.rs:459-464`), reusing identical request parameters and ensuring that double generation failures result in `WorkflowCompleted{success: false}` without substituting fabricated or unvalidated answers.
- **Deterministic DI Port Seams for Storage & Graph (ORCH-03)**: Plan 04 (`05-04-PLAN.md`) introduces `GraphQueryPort` and `DenseRetrievalPort` traits in `engine/src/workflow/ports.rs`, mirroring the `Generator` DI pattern in `engine/src/generation/mod.rs:459-490`, enabling deterministic stall/failure testing without relying on uncoordinated network/storage timing.
- **Fire-and-Forget Checkpoint Persistence (D-26, D-27, ORCH-04)**: Plan 05 (`05-05-PLAN.md`) decouples Postgres writes from the hot query path by dispatching `go a.persistCheckpoint(cp)` in a detached goroutine (`context.Background()`) off `gateway/main.go`'s SSE loop, using Atlas HCL (`gateway/db/schema.hcl`) and sqlc (`gateway/db/query.sql`) conventions.

---

## 3. Concerns

- **HIGH: Indiscriminate `try_send` on bounded channels risks dropping client-facing answer events (`AnswerChunk` / `FinalAnswer`) under backpressure**
  - **File / Location**: `05-01-PLAN.md:1211`, `05-03-PLAN.md:1700`, `05-05-PLAN.md:2048`
  - **Mechanism**: The plans specify sending all events (`NodeStarted`, `NodeCompleted`, `AnswerChunk`, `FinalAnswer`, `WorkflowCompleted`) via `try_send` on `mpsc::Sender<WorkflowEvent>`. While D-27 requires fire-and-forget for *checkpoint sidecar writes*, applying `try_send` to primary response payload events (`AnswerChunk`, `FinalAnswer`) means that if the bounded channel experiences temporary backpressure, `try_send` will drop `FinalAnswer` or `AnswerChunk`. The client stream will close without receiving the generated answer or citations despite successful LLM generation.
  - **Impact**: Silent data loss and broken client contract on high-concurrency or backpressured streams.

- **MEDIUM: Rust compiler `#[ignore]` semantics misunderstood for broken test call sites**
  - **File / Location**: `05-01-PLAN.md:1150-1152`, `1215`, `engine/src/tests.rs:2181+`
  - **Mechanism**: Plan 01 instructs marking ~12 existing `query_rag_*` integration tests in `engine/src/tests.rs` with `#[ignore = "pending 05-0N"]` while updating `QueryRAG`'s gRPC signature from unary to server-streaming. In Rust, `#[ignore]` skips test execution at runtime, but the compiler still type-checks all `#[ignore]`'d functions during `cargo test`.
  - **Impact**: Any test calling `.query_rag(req).await` expecting a unary `Result<Response<QueryRagResponse>, Status>` will fail `cargo test` at compile time unless the call site expressions are updated to compile against the streaming signature.

- **LOW: Heavy payload duplication in full accumulated JSON snapshots**
  - **File / Location**: `05-05-PLAN.md:2038-2048`, `gateway/db/schema.hcl:5-27`
  - **Mechanism**: Plan 05 serializes full `WorkflowContext` snapshots (`serde_json::to_string(ctx)`) into `jsonb` columns for every `NodeCompleted` event (5 rows per 5-node query). Since `WorkflowContext` contains 2048-dim float embeddings (`query_embedding`) and full chunk text content inside `vector_results`/`bm25_results`, each query writes ~150–250 KB of JSON across 5 rows.
  - **Impact**: Negligible for local MVP demo, but without retention cleanup (D-24), Postgres storage will grow rapidly during extensive local evaluation runs.

---

## 4. Suggestions

- **Differentiate Event Delivery (`send().await`) from Checkpoint Sidecars (`try_send`)**:
  - **File / Location**: `engine/src/workflow/runner.rs`, `engine/src/workflow/events.rs`
  - **Action**: In `WorkflowRunner::run`, use `events.send(event).await` for primary protocol events (`NodeStarted`, `NodeCompleted`, `AnswerChunk`, `FinalAnswer`, `WorkflowCompleted`) so backpressure pauses node execution rather than dropping answers. Restrict `try_send` (or non-blocking channel drop) exclusively to optional checkpoint sidecars or background worker queues.

- **Explicitly Update Test Signatures in `engine/src/tests.rs`**:
  - **File / Location**: `engine/src/tests.rs:2181+`, `05-01-PLAN.md:1215`
  - **Action**: Ensure Task 2 of Plan 01 updates the response handling invocation (e.g. consuming or taking the first stream frame) for all 17 tests in `engine/src/tests.rs` so that `cargo test --locked` compiles cleanly, before adding `#[ignore = "..."]` for tests whose functional assertions await future nodes.

- **Pre-allocate Buffer for `Vec<Vec<FusedCandidate>>` Cross-Variant RRF Merge**:
  - **File / Location**: `engine/src/retrieval/fusion.rs:58-100`, `05-02-PLAN.md:1458-1463`
  - **Action**: When implementing `merge_fused_candidate_lists` in `fusion.rs`, pre-allocate the candidate map with capacity matching `variants.len() * settings.candidate_limit` to prevent repeated re-allocations during multi-variant RRF fusion.

---

## 5. Risk Assessment

**Overall Risk Level: LOW**

**Justification**:
The implementation plans are exceptionally well-prepared, highly detailed, and thoroughly grounded in the existing Lancet codebase. They map directly onto the validated requirements (ORCH-01 through ORCH-05) and decisions (D-01 through D-31). The plans accurately anticipate gRPC streaming changes (`proto/lancet/v1/lancet.proto:11`), Go HTTP SSE forwarding (`gateway/main.go:654-715`), Atlas/sqlc migration patterns (`gateway/db/schema.hcl` & `query.sql`), and Rust async cancellation/timeout mechanics (`tokio::select!`). The identified concerns (`try_send` usage on answer events and Rust test compilation requirements) are straightforward to address during execution and do not compromise the core architectural integrity of the phase.

---

## Consensus Summary

Both reviewers had full repo access and grounded their findings in `file:line` citations against the live codebase — no ungrounded or blind reviews to down-weight. However, they land on **sharply different overall risk verdicts** (Antigravity: LOW, Codex: HIGH), driven by Codex surfacing several first-order execution blockers that Antigravity's pass did not catch.

### Agreed Strengths

- **Pre-stream validation boundary is preserved on the engine side (D-04).** Both reviewers confirm `query_rag` keeps synchronous request/session validation before workflow execution begins (`engine/src/main.rs:1346-1393`), matching existing `gateway/main.go` trailer/error handling. (Codex also flags a related but distinct gateway-side gap — see Divergent Views.)
- **Graph-before-retrieval node ordering is correct (D-06).** Both reviewers independently verified the plan's ordering claim against live code: graph augmentation at `engine/src/main.rs:1426` executes before dense retrieval at `:1450`, and 05-02-PLAN.md preserves this.

### Agreed Concerns

- **HIGH — `try_send` risks silently dropping client-facing workflow events under backpressure.** Both reviewers flag that the plans apply non-blocking `try_send` not just to the fire-and-forget checkpoint sidecar (as D-27 intends) but also to primary protocol events — `NodeStarted`, `NodeCompleted`, `AnswerChunk`, `FinalAnswer`, `WorkflowCompleted` (05-01-PLAN.md, 05-03-PLAN.md, 05-05-PLAN.md; AI-SPEC.md:266). A full channel can drop a client's answer or completion signal entirely. Both recommend separating reliable `.send().await` delivery for client-facing events from lossy/detached delivery for checkpoint persistence only.
- **MEDIUM/LOW — Checkpoint/context JSON snapshots may be oversized.** Both reviewers independently flag that serializing full `WorkflowContext`/`Candidate`/`PackedEvidence` snapshots (including raw chunk text and embeddings) at every node boundary produces large payloads (Antigravity estimates ~150-250KB per query across 5 rows) with no defined size cap or redaction — a concern for both Postgres storage growth and, per Codex, potential over-exposure if the sidecar is forwarded to the client via SSE.

### Divergent Views

- **Overall risk level: LOW (Antigravity) vs. HIGH (Codex).** This is the most important disagreement to resolve before execution. Codex's HIGH verdict rests on several concrete blockers Antigravity's pass did not surface:
  - **Streaming validation may not actually yield HTTP 4xx.** Codex argues that once the Go gateway commits SSE headers and calls `stream.Recv()`, a Rust-side validation error arriving from the stream lands *after* HTTP 200 is already committed — undermining the very D-04 guarantee both reviewers credited as a strength. Fix proposed: classify the first gRPC frame/status before `WriteHeader`, or add a preflight validation RPC.
  - **The planned Rust Tier 1 integration test harness may not be buildable as specified.** Codex found `buf.gen.yaml:15` sets `no_client=true`, so no generated Rust gRPC client exists for `engine/tests/workflow_events.rs` to use as planned; it also notes `EmbeddingProvider` is private to the binary and the binary unconditionally requires `OPENROUTER_API_KEY` with no fake-provider injection seam. Antigravity's review did not check for this.
  - **The new event contract may drop existing response data.** Codex identifies that `session_id`, filters, and the no-evidence notice/snapshot present in the current `QueryRAGResponse` schema have no home in the planned `FinalAnswer`/`WorkflowCompleted` events.
  - **Other Codex-only HIGH/MEDIUM findings not raised by Antigravity:** a 05-02/05-04 dependency-ordering mismatch (the graph-timeout test in 05-02 needs `GraphQueryPort`, which isn't introduced until 05-04), a self-contradiction in 05-03 on whether answer events fire before or after `GenerateAnswer`'s `NodeCompleted`, and a sqlc/schema mismatch in 05-05 (`sqlc.yaml` reads `db/schema.sql`, but the plan only updates `db/schema.hcl`).
  - Given Codex's findings are backed by specific, checkable file:line evidence (`buf.gen.yaml:15`, `gateway/sqlc.yaml:3`, `05-03-PLAN.md:24` vs `:183`, etc.), **these should be verified against the repo before proceeding** — they represent a materially different risk picture than Antigravity's LOW verdict.
- **Test-compilation risk (Antigravity only).** Antigravity flags that marking ~12 tests `#[ignore]` in `engine/src/tests.rs` doesn't exempt them from compilation, so call sites must already compile against the new streaming signature — Codex's review did not mention this.
