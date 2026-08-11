---
phase: 5
reviewers: [codex, antigravity]
reviewed_at: 2026-08-11T23:24:00Z
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

The plans are thoughtful and cover the phase requirements unusually well, especially the D-04 validation boundary, corrected graph-before-retrieval order, reliable event delivery, generation retry policy, SSE prefetch, and checkpoint payload isolation. However, the set is not yet execution-ready. Several remaining issues are implementation blockers rather than polish: the planned fake retrieval/reformulation ports cannot be injected through the current service, timeout budgets do not match the real configurable provider timeout, synchronous prompt assembly is not preemptible by Tokio timeouts, the checkpoint fallback shape is internally inconsistent, and `sqlc`'s generated model file is omitted. Overall risk is HIGH until these are resolved.

## Plan 05-01

### Strengths

- Preserves the actual D-04 boundary: validation and ID creation occur before the stream opens, matching the current handler at [engine/src/main.rs:1346](/D:/Repos/lancet/engine/src/main.rs:1346), including separate session and correlation IDs at [engine/src/main.rs:1354](/D:/Repos/lancet/engine/src/main.rs:1354) and [engine/src/main.rs:1368](/D:/Repos/lancet/engine/src/main.rs:1368).

- The first-frame prefetch is the correct response to converting the current unary RPC at [proto/lancet/v1/lancet.proto:11](/D:/Repos/lancet/proto/lancet/v1/lancet.proto:11) into server streaming. It prevents pre-stream gRPC failures from becoming false HTTP 200 SSE responses.

- Structurally excluding `/rag/query` from the existing blanket timeout is correct. The current router applies `middleware.Timeout(60*time.Second)` globally at [gateway/main.go:462](/D:/Repos/lancet/gateway/main.go:462), which is incompatible with the planned worst-case workflow duration.

- Keeping Rust's internal event enum separate from generated protobuf types is a sound boundary, and reliable `Sender::send().await` is appropriate for client-visible protocol events.

### Concerns

- **HIGH — The cancellation test has no defined observable outcome channel.** The plan requires `spawn_workflow(runner, ctx)` to take only those two arguments and says the test should inspect a shared outcome, but no outcome sink, `JoinHandle`, callback, or returned result is specified. Once the receiving stream is dropped, the runner intentionally cannot send `NodeFailed` or `WorkflowCompleted`. The test therefore cannot prove the claimed category without an additional API. Define a `WorkflowHandle` or return a join/result channel from `spawn_workflow`; otherwise separate runner cancellation testing from stream-drop transport testing. See the plan's own unresolved mechanism at [05-01-PLAN.md:304](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:304).

- **MEDIUM — The planned `tokio_stream::StreamExt` import conflicts with the existing `futures::StreamExt` import.** The current file already imports `StreamExt` at [engine/src/main.rs:14](/D:/Repos/lancet/engine/src/main.rs:14). Use an alias or fully qualified adapter call.

- **MEDIUM — The fixed 120-second gateway timeout is not tied to configurable engine timeouts.** The plan makes `generation_timeout_secs` configurable, but a user can raise it enough that the 120-second route budget is again too short. Derive the gateway budget from configuration, remove the route timeout, or establish and validate a cross-service upper bound.

- **LOW — The existing `query_rag` tracing span may no longer cover node execution.** The current span is instrumented around the handler future at [engine/src/main.rs:1706](/D:/Repos/lancet/engine/src/main.rs:1706). A detached runner task needs to inherit `Span::current()` explicitly if retaining that span is intended.

## Plan 05-02

### Strengths

- Correctly follows the shipped graph-before-retrieval order: graph augmentation begins around [engine/src/main.rs:1426](/D:/Repos/lancet/engine/src/main.rs:1426), before dense retrieval.

- The two-pass cross-variant RRF design is explicit and testable rather than accidentally passing because the current NoOp reformulator returns one variant.

- The distinction between empty evidence and infrastructure failure is important and well specified. The current implementation's zero-evidence branch carries a snapshot at [engine/src/main.rs:1508](/D:/Repos/lancet/engine/src/main.rs:1508), so preserving that on `WorkflowCompleted` is correct.

- Moving graph and dense retrieval behind ports is the right direction for deterministic timeout and failure tests.

### Concerns

- **HIGH — The planned service-level tests cannot inject the planned fakes.** Plan 05-01 constructs `NoOpQueryReformulator` directly at the handler call site, while the current `LancetServiceImpl` has no reformulator, graph-port, or dense-port fields at [engine/src/main.rs:864](/D:/Repos/lancet/engine/src/main.rs:864). Plan 05-02 nevertheless requires `service.query_rag(...)` tests using `FakeQueryReformulator` and `FakeDenseRetrievalPort`. Add injectable dependencies to `LancetServiceImpl` or test the runner/nodes directly; as written, the claimed in-process tests are not wired to the fakes.

- **HIGH — D-03 snapshot construction lacks required inputs.** The planned `RetrieveHybridNode` fields omit `index_generation` and embedding model identity, but the existing zero-evidence snapshot requires both at [engine/src/main.rs:1510](/D:/Repos/lancet/engine/src/main.rs:1510). Add those values to the context/node or create a shared snapshot builder.

- **MEDIUM — Empty reformulator output can panic.** The plan embeds `ctx.reformulated_query[0]`, but it does not specify rejection of an empty `Vec<String>`. A future reformulator implementation could violate that assumption. Validate non-empty output and define bounds/normalization for every variant.

- **MEDIUM — BM25 remains concrete and uninjectable.** Dense retrieval gets a fake, but BM25 still uses the concrete `Bm25Index` path. The tests prove dense failure, not BM25 failure or lock/contention behavior. Either introduce a BM25 port or narrow the stated coverage.

- **MEDIUM — Graph degradation is not represented in durable state.** Timeout and logical graph failures become an apparently successful node with empty graph context. Since workflow metadata and `degraded_mode` are deferred, checkpoint data will not distinguish "no graph match" from "graph query failed" unless an internal reason is retained.

## Plan 05-03

### Strengths

- Retry classification matches the existing closed error taxonomy at [engine/src/generation/mod.rs:406](/D:/Repos/lancet/engine/src/generation/mod.rs:406), rather than retrying permanent request/configuration errors.

- Whole-struct request equality is a strong proof of byte-equivalent retry input; `GenerationRequest` already derives `PartialEq` at [engine/src/generation/mod.rs:375](/D:/Repos/lancet/engine/src/generation/mod.rs:375).

- Reusing the existing prompt packing function preserves Phase 3 behavior. The function is defined at [engine/src/prompt.rs:255](/D:/Repos/lancet/engine/src/prompt.rs:255), and the canonical `PackedEvidence` shape is already available at [engine/src/prompt.rs:168](/D:/Repos/lancet/engine/src/prompt.rs:168).

- The no-fabrication control flow and `NodeCompleted → AnswerChunk → FinalAnswer` ordering are clear and well tested in the plan.

### Concerns

- **HIGH — The generation timeout invariant is based on the wrong timeout.** The plan validates `generate_timeout_ms > 30s`, but the production generator uses configurable `generation_timeout_secs` at [engine/src/main.rs:3090](/D:/Repos/lancet/engine/src/main.rs:3090). The 30-second `GENERATION_TIMEOUT` constant at [engine/src/generation/openrouter.rs:24](/D:/Repos/lancet/engine/src/generation/openrouter.rs:24) is only the convenience-constructor default. A 65-second node budget is not enough for two full 60-second configured attempts, and `>30s` only guarantees that one attempt can fit. Validate against the actual effective provider timeout, ideally requiring two attempts plus explicit slack.

- **HIGH — The AssemblePrompt timeout is not preemptive.** `pack_evidence_and_graph_prompt` performs synchronous tokenization and substantial loops, including BPE initialization at [engine/src/prompt.rs:272](/D:/Repos/lancet/engine/src/prompt.rs:272) and synchronous packing through [engine/src/prompt.rs:342](/D:/Repos/lancet/engine/src/prompt.rs:342). Wrapping this future in `tokio::time::timeout` cannot interrupt work that does not yield. The plan needs a deliberate `spawn_blocking`/cooperative-yield strategy or must narrow what the timeout promises.

- **MEDIUM — Citation-resolution failure is not assigned a retry/error policy.** The current code's unresolved-citation path is a plain internal error at [engine/src/main.rs:1619](/D:/Repos/lancet/engine/src/main.rs:1619), not a `GenerationErrorKind`. "Reuse the exact code" is insufficient: specify whether it maps to `LlmGenerationFailed`, whether it is retryable, and test it.

- **MEDIUM — The cancellation rendezvous does not actually prove cancellation between attempts.** The proposed `FakeGenerator` pauses before returning attempt 1's error, so cancellation occurs during attempt 1, not after the retry loop receives the error and before it starts attempt 2. Add a retry-loop gate or callback immediately before attempt 2.

- **MEDIUM — The final snapshot has the same missing-input issue as Plan 05-02.** `GenerateAnswerNode`'s listed fields omit `index_generation`, while the current successful snapshot requires it at [engine/src/main.rs:1670](/D:/Repos/lancet/engine/src/main.rs:1670). Centralize snapshot construction rather than duplicating incomplete node-local inputs.

## Plan 05-04

### Strengths

- The runner-level `StallingTestNode` is a reasonable way to test generic timeout machinery for AssemblePrompt without pretending that prompt assembly has an external I/O dependency.

- Full-pipeline trace consistency is a useful invariant once all event types exist.

### Concerns

- **MEDIUM — The trace/session assertion is ambiguous and partly incorrect.** D-29 makes `trace_id` equal to `correlation_id`, not `session_id`. The current handler generates those independently at [engine/src/main.rs:1354](/D:/Repos/lancet/engine/src/main.rs:1354) and [engine/src/main.rs:1368](/D:/Repos/lancet/engine/src/main.rs:1368). The test should assert all event trace IDs match and that `WorkflowCompleted.session_id` matches the request/session value; it should not require trace ID to equal session ID.

- **MEDIUM — The AssemblePrompt test proves only the generic runner, not the actual node's timeout behavior.** Given the synchronous implementation described above, the generic stalling-node test may pass while the real prompt node remains non-preemptible. Add a focused test or explicitly document that this is only runner coverage after fixing the CPU-bound execution model.

- **LOW — The "all reference scenarios are covered" claim depends on later Go/Postgres tests that are skipped when the integration environment is absent.** The verification should distinguish locally executed tests from environment-gated coverage.

## Plan 05-05

### Strengths

- Updating both Atlas's HCL source and sqlc's actual SQL schema is correct. The sqlc configuration explicitly reads `db/schema.sql` at [gateway/sqlc.yaml:3](/D:/Repos/lancet/gateway/sqlc.yaml:3).

- A Go-generated UUID primary key is appropriate for the existing isolated-schema test pattern and avoids sequence-sharing problems.

- Threading `trace_id` from the enclosing event rather than inventing it on the checkpoint sidecar is correct.

- Bounded, detached Postgres writes with a context timeout correctly place D-27's fire-and-forget behavior at the Go persistence boundary.

### Concerns

- **HIGH — `gateway/db/models.go` is missing from `files_modified`.** The current generated models file contains only `Document`, `DocumentReconciliationIntent`, and `User`, beginning at [gateway/db/models.go:11](/D:/Repos/lancet/gateway/db/models.go:11). An `INSERT ... RETURNING *` for a new table will cause sqlc to generate a `WorkflowCheckpoint` model there. Add the file and verify it is committed.

- **HIGH — The checkpoint fallback shape is not implementable as specified.** The plan requires `CheckpointSnapshotV1` to have all D-28 fields, then says the fallback contains only a marker and candidate count. A single ordinary Rust struct cannot have both shapes unless fields are optional and conditionally serialized. Define a separate `CheckpointFallbackV1` or an enum such as `Full(CheckpointSnapshotV1) | Fallback(...)`, then test the actual serialized shape.

- **MEDIUM — The size ladder must explicitly bound every unbounded field.** `PackedEvidence` contains `prompt`, `evidence`, and `encoded_blocks` at [engine/src/prompt.rs:168](/D:/Repos/lancet/engine/src/prompt.rs:168), while each fused candidate includes raw candidate content at [engine/src/retrieval/fusion.rs:16](/D:/Repos/lancet/engine/src/retrieval/fusion.rs:16). The final fallback can guarantee the limit, but the intermediate truncation steps should explicitly replace all of those fields and handle serialization errors at every step.

- **MEDIUM — Existing test doubles will stop satisfying `documentStore`.** Adding `InsertWorkflowCheckpoint` to the interface requires updating `fakeStore`, which currently begins at [gateway/main_test.go:45](/D:/Repos/lancet/gateway/main_test.go:45). The plan should explicitly add a no-op/recording implementation before claiming the Go suite will compile.

- **MEDIUM — Database environment names are inconsistent with the repository.** Existing integration tests use `TEST_DATABASE_URL` at [gateway/main_test.go:1708](/D:/Repos/lancet/gateway/main_test.go:1708), while Atlas defaults to its own URL in [gateway/atlas.hcl:1](/D:/Repos/lancet/gateway/atlas.hcl:1). The plan's `DATABASE_URL` precondition is not the current convention. Choose one variable and specify how Atlas, tests, and Docker use it; Docker's service is `db` at [docker-compose.yml:2](/D:/Repos/lancet/docker-compose.yml:2).

- **MEDIUM — Checkpoints are attached only to successful `NodeCompleted` events.** That omits the most useful debugging state for failed or cancelled nodes. Either attach snapshots to `NodeFailed` as well or explicitly narrow ORCH-04 to successful boundaries.

- **LOW/MEDIUM — Detached persistence tests need lifecycle control.** A blocking fake store can leave goroutines running into schema cleanup. Add a wait mechanism or ensure the fake returns on context cancellation before closing the isolated pool/schema.

## Suggestions

- Introduce a `WorkflowDependencies` structure on `LancetServiceImpl` containing the reformulator, graph port, dense port, and BM25 port. Production construction supplies real implementations; tests supply fakes. This resolves the current mismatch between [engine/src/tests.rs:713](/D:/Repos/lancet/engine/src/tests.rs:713) and the planned service-level fault tests.

- Make `spawn_workflow` return a handle containing cancellation, completion, and terminal outcome channels. Use the stream close only to trigger cancellation; use the handle to assert cancellation categories deterministically.

- Centralize retrieval snapshot construction so `index_generation`, embedding model, filters, result hash, and limits cannot be omitted by individual nodes.

- Tie `generate_timeout_ms` to the effective provider timeout and make the route budget derive from the same maximum, or remove the gateway timeout and rely on bounded node budgets plus cancellation.

- Define the checkpoint payload as an explicit full/fallback enum and add `gateway/db/models.go` to Plan 05-05. Update every `documentStore` fake and use one canonical database environment variable.

- Extend the config-contract updates across all plans. The current test requires an exact key set at [engine/src/tests.rs:204](/D:/Repos/lancet/engine/src/tests.rs:204) and only allows listed sections at [engine/src/tests.rs:181](/D:/Repos/lancet/engine/src/tests.rs:181); every new workflow timeout needs a required-key entry, annotation entry, allowed section, and adjacent example comment.

- Run full unfiltered Rust and Go suites after each contract migration, not only name-filtered commands. Also run a real invalid-request HTTP test and a real client-disconnect test through Go → gRPC → Rust, since fake-stream tests cannot validate trailer propagation and cancellation across the actual boundary.

## Risk Assessment

**Overall: HIGH.**

The architecture and decisions are strong, and the phase can achieve its goals after correction. The risk is concentrated in the one-way unary-to-streaming migration, the absence of a complete dependency-injection path for the planned fault tests, timeout semantics that currently do not match production configuration or synchronous CPU work, and the checkpoint code-generation/fallback gaps. These are likely to cause compile failures or false-positive validation unless resolved before execution.

---

## Antigravity Review

# Cross-AI Plan Review: Phase 5 (State Machine & Workflow Events)

## 1. Summary

The implementation plan for **Phase 5: State Machine & Workflow Events** formalizes Lancet's RAG pipeline into a typed Rust async state machine (`Node`/`WorkflowRunner`) and establishes a server-streaming gRPC contract mapped to Server-Sent Events (SSE) at the Go API gateway. Across five well-structured waves, the plan successfully addresses prior design concerns from rounds 1–3, incorporating robust error handling, reliable event delivery, explicit failure classification, and durable PostgreSQL checkpointing. The architectural boundaries—separating Rust's performance-oriented data plane from Go's control plane—are strictly preserved. Verification against the live codebase confirms that all file paths, function signatures, configuration targets, and schema conventions are accurate and feasible.

## 2. Strengths

- **Preservation of Pre-Stream Error Boundaries (D-04)**: The plan correctly retains synchronous request validation (`QueryRequest::from_values`) in `engine/src/main.rs:1352-1393` prior to opening gRPC server streams. Coupled with Go's first-frame prefetch (`stream.Recv()`) in `gateway/main.go:691-715` before emitting `http.StatusOK` or `text/event-stream` headers, malformed requests return standard HTTP 4xx errors with trailers rather than opening broken SSE streams.

- **Structural Chi Timeout Isolation**: Rather than nesting route timeouts with `r.With(...)` on a router with pre-applied middleware in `gateway/main.go:464`, Plan 05-01 uses distinct `r.Group()` blocks to isolate `/rag/query` under a dedicated 120s timeout budget, preventing silent stream termination by the default 60s global ceiling (`gateway/main.go:464`).

- **Infallible, Staged 4-Step Checkpoint Truncation**: `build_checkpoint_snapshot` in `engine/src/workflow/events.rs` uses a dedicated `CheckpointSnapshotV1` DTO containing only `Serialize`-derived domain types (`engine/src/retrieval/fusion.rs:15`, `engine/src/prompt.rs:161-167`, `engine/src/generation/mod.rs:55-68`). By avoiding direct `serde_json::to_string(ctx)` calls on `WorkflowContext` (which contains non-serializable types like `retrieval::QueryRequest` at `engine/src/retrieval/mod.rs:343`) and using a 4-step truncation ladder ending in a minimal fixed-shape fallback, snapshot construction guarantees a hard 256 KiB size ceiling without panicking or failing user queries.

- **Dual Database & SQL Query Synchronization**: Plan 05-05 Task 1 synchronizes `gateway/db/schema.hcl` with `gateway/db/schema.sql` (which `gateway/sqlc.yaml:3` references for `sqlc generate`). Using a Go-generated UUID string `id varchar(36)` instead of `serial` prevents sequence pollution across isolated test schemas generated via `LIKE public.x INCLUDING ALL` in `gateway/main_test.go:1635-1680`.

- **Explicit Failure Classification for LLM Retries (D-11/D-12)**: `GenerateAnswerNode` in Plan 05-03 Task 2 explicitly classifies `generation::GenerationErrorKind` (`engine/src/generation/mod.rs:405-414`). Only transient failures (`ProviderError`, `Timeout`, `SchemaValidation`) trigger D-12's single retry with byte-identical `GenerationRequest` instances (`engine/src/generation/mod.rs:374-402`), while permanent configuration errors (`InvalidRequest`, `SupportedParameters`, `SessionCorrelation`) fail immediately without unnecessary retry attempts.

- **Clean Dependency Injection Seams**: Moving `GraphQueryPort` and `DenseRetrievalPort` traits to `engine/src/workflow/ports.rs` in Plan 05-02 provides clean test double seams for deterministic fault injection, eliminating direct dependencies on `DatabaseManager` (`engine/src/main.rs:1056`) and `DenseRetriever` (`engine/src/main.rs:1450`) during unit tests.

## 3. Concerns

- **[MEDIUM] `RetrieveHybridNode` Handling of Empty Reformulation Variants**:
  - *Evidence*: `engine/src/workflow/nodes/retrieve.rs` (Plan 05-02 Task 2) loops over `ctx.reformulated_query`.
  - *Risk*: `NoOpQueryReformulator` returns `vec![original_query]`, but if a future `QueryReformulator` implementation returns an empty `Vec<String>`, the loop executes zero times, yielding zero candidates. This triggers the D-03 short circuit (`NO_EVIDENCE` notice with `WorkflowCompleted{success: true}`) in `engine/src/main.rs:1508-1547` rather than surfacing a pipeline error for invalid reformulation output.

- **[MEDIUM] Manual Environment Override Drift in `load_settings()`**:
  - *Evidence*: `engine/src/main.rs:486-521` explicitly re-binds specific env vars (e.g. `LANCET_ENGINE__GRPC_ADDR`).
  - *Risk*: New configuration keys added under `[engine.workflow]` in `config/config.toml` (e.g. `reformulate_timeout_ms`, `graph_timeout_ms`, `generate_timeout_ms`) rely on generic deserialization via `config::Environment::with_prefix("LANCET")` (`engine/src/main.rs:479-480`). Any subtle naming or casing mismatch in env var overrides could cause settings to silently revert to default values.

- **[LOW] `FakeGenerator` Rendezvous Test Timeout**:
  - *Evidence*: `engine/src/generation/mod.rs:467-512` (Plan 05-03 Task 2).
  - *Risk*: `FakeGenerator` introduces `paused_signal` and `resume` (`Arc<tokio::sync::Notify>`) for attempt-boundary synchronization. If a test assertion fails prior to invoking `resume.notify_one()`, the background task will block indefinitely on `resume.notified().await`, causing the test runner to hang.

## 4. Suggestions

- **Validate Non-Empty Query Variants**: In `engine/src/workflow/nodes/retrieve.rs`, add an explicit check before the retrieval loop:
  ```rust
  if ctx.reformulated_query.is_empty() {
      return Err(NodeError::new(NodeErrorKind::Internal, "query reformulator returned zero variants"));
  }
  ```
- **Explicit `[engine.workflow]` Env Bindings**: Extend `load_settings()` in `engine/src/main.rs:486-521` to explicitly bind `LANCET_ENGINE__WORKFLOW__*` environment variables, mirroring `LANCET_ENGINE__RETRIEVAL__EVIDENCE_TOKEN_BUDGET` at line 511.
- **Timeout Bounded Test Rendezvous**: In `engine/src/generation/mod.rs`, wrap `self.resume.notified()` with a bounded `tokio::time::timeout` in `FakeGenerator::generate` to prevent hanging test suites when assertions fail mid-flight.

## 5. Risk Assessment

- **Overall Risk Level**: **LOW**
- **Justification**: The phase design is mature, well-tested, and meticulously aligned with existing system conventions. Critical failure modes—such as unvalidated answer generation, unhandled stream drops, unbounded channel growth, and database sequence pollution—are thoroughly mitigated through explicit invariants and automated test assertions across all five plans.

---

## Consensus Summary

Both reviewers independently confirm the phase's architecture is sound and the boundary decisions (D-04 pre-stream validation, graph-before-retrieval ordering, checkpoint payload isolation, generation retry classification) are correctly carried through from prior review rounds. They diverge sharply on execution-readiness:

- **Codex (HIGH risk)** found concrete, source-grounded blockers: the planned service-level fakes (`FakeQueryReformulator`, `FakeDenseRetrievalPort`) have no injection point on `LancetServiceImpl` ([engine/src/main.rs:864](/D:/Repos/lancet/engine/src/main.rs:864)); `generate_timeout_ms > 30s` validates against the wrong timeout constant (the real budget is `generation_timeout_secs`, configurable up to 60s+ per attempt); `AssemblePrompt`'s synchronous tokenization ([engine/src/prompt.rs:272](/D:/Repos/lancet/engine/src/prompt.rs:272)) cannot be preempted by `tokio::time::timeout`; the checkpoint fallback shape can't coexist with the full `CheckpointSnapshotV1` in one struct; and `gateway/db/models.go` is missing from Plan 05-05's file list despite `sqlc` needing to regenerate it for the new table.
- **Antigravity (LOW risk)** treated these same mechanisms as correctly designed and flagged only smaller edge cases (empty reformulation variants, env-var override drift, a test rendezvous hang risk) — it did not independently trace the fake-injection path, the effective provider timeout value, or the synchronous-tokenization/timeout interaction that Codex flagged.

Given Codex's findings are backed by specific file:line citations that trace actual code paths (not just plan text), and Antigravity's own strengths section describes the *intended* mechanism rather than verifying the injection seam exists, **the HIGH-risk findings should be treated as the operative signal**. Recommend addressing the five Codex HIGH items (cancellation outcome channel, service-level fake injection, generation timeout validation source, AssemblePrompt preemption strategy, checkpoint fallback shape) plus the `gateway/db/models.go` omission before execution.
