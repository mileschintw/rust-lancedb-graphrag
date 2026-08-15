---
phase: 5
scope: gap-closure
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-15T01:17:07Z
source_head: 6db88628ce90726e635d164421c22c14c88e1c6a
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
  antigravity: 29644
  claude: 21540
---

# Cross-AI Plan Review — Phase 05 Gap Closure (Fresh)

## Antigravity Review

# Adversarial Plan Review: Phase 05 Gap-Closure Plans (05-08 through 05-21)

This review evaluates the 14 additive gap-closure plans (`05-08-PLAN.md` through `05-21-PLAN.md`) for Phase 05 (*State Machine, Workflow Events & Live RAG Verification*). Every relative path and source citation has been verified against the physical repository at `D:\Repos\lancet`.

---

## 1. Plan 05-08: Five-Node Production Workflow Wiring & Adapters

### Summary
Plan 05-08 replaces the monolithic inline remainder execution in [engine/src/main.rs:1716-1748](file:///D:/Repos/lancet/engine/src/main.rs#L1716-L1748) with real production adapter wiring across all five workflow nodes (`ReformulateQueryNode`, `ExtractGraphContextNode`, `RetrieveHybridNode`, `AssemblePromptNode`, `GenerateAnswerNode`). It instantiates concrete adapters (`LanceDbGraphPort`, `LanceDbDensePort`, `TantivyBm25Port`, `OpenRouterGenerator`) and connects `WorkflowContext` population directly to the production `QueryRAG` gRPC handler.

### Strengths
- **Directly eliminates monolithic remainder execution**: Connects all five nodes defined in [engine/src/workflow/nodes/](file:///D:/Repos/lancet/engine/src/workflow/nodes/) to the production execution path, removing `LancetServiceImpl::execute_inline_query_rag_remainder` ([engine/src/main.rs:1234-1538](file:///D:/Repos/lancet/engine/src/main.rs#L1234-L1538)).
- **Populates production dependencies**: Populates `WorkflowDependencies` ([engine/src/workflow/mod.rs:111-135](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L111-L135)) with live database, vector, BM25, and LLM generator instances rather than `None`.
- **Strict adherence to pipeline order**: Preserves the locked order `ExtractGraphContext` -> `RetrieveHybrid` (D-06), seeding graph augmentation from variant zero's embedding.

### Concerns
- **[MEDIUM] Infallible vs. Option-wrapped runtime dependency validation** ([engine/src/workflow/mod.rs:111-135](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L111-L135)): `WorkflowDependencies` fields are currently wrapped in `Option<Arc<dyn Trait>>`. If any adapter fails to initialize or is omitted during `build_production_workflow`, failures manifest at runtime during request execution.
- **[LOW] Test-double and production constructor duality** ([engine/src/workflow/nodes/graph_context.rs:20-30](file:///D:/Repos/lancet/engine/src/workflow/nodes/graph_context.rs#L20-L30)): `ExtractGraphContextNode::new` allows `None` ports for tests, which can mask missing production dependencies if misconfigured.

### Suggestions
- Validate that all required production ports are non-`None` in `build_production_workflow` at service startup to fail fast if an adapter is misconfigured.

### Risk Assessment
**LOW**: The plan has clear ownership, directly addresses the primary verification gap, and replaces placeholder remainder logic with modular node orchestration.

---

## 2. Plan 05-09: Live Workflow Settings, Node Deadlines & Stream Cancellation

### Summary
Plan 05-09 wires the unparsed `[engine.workflow]` configuration section into `EngineSettings` in [engine/src/main.rs:171-180](file:///D:/Repos/lancet/engine/src/main.rs#L171-L180), applies per-node timeout durations to `WorkflowRunner`, and corrects the contradictory timeouts in [config/config.verify.toml](file:///D:/Repos/lancet/config/config.verify.toml) so that live wall-clock timeouts can be verified. It also binds gRPC client disconnects to `CancellationToken`.

### Strengths
- **Fixes unparsed configuration**: Adds `WorkflowConfigSettings` to `EngineSettings` with deserialization fallbacks matching [config/config.toml](file:///D:/Repos/lancet/config/config.toml).
- **Corrects impossible verification timeouts**: Increases `openrouter.generation_timeout_secs = 30` and sets realistic upstream node timeouts in [config/config.verify.toml:5-14](file:///D:/Repos/lancet/config/config.verify.toml#L5-L14) so that the 7000ms `generation_node_timeout_ms` can be proven without hitting upstream timeouts or a 1-second provider cutoff.
- **Enforces cancellation propagation**: Ensures cancellation tokens are passed through `run_node` into async I/O futures.

### Concerns
- **[HIGH] Stream-drop detection on spawned Tokio tasks** ([engine/src/main.rs:1730-1753](file:///D:/Repos/lancet/engine/src/main.rs#L1730-L1753)): `tokio::spawn` detaches the workflow execution. If a gRPC client disconnects, Tonic drops the `ReceiverStream`, but `cancel.cancel()` is only triggered if the event sink detects channel closure on `send_event` or a dedicated cancellation guard monitors stream drops.
- **[MEDIUM] Runner select bias under timeout** ([engine/src/workflow/runner.rs:128-135](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L128-L135)): `tokio::select!` with `biased;` checks `cancel.cancelled()` before the timeout. If a child future does not yield or poll cancellation internally, cancellation may be delayed until the node future completes.

### Suggestions
- Attach a drop-guard to the response stream in `query_rag` that explicitly triggers `cancel.cancel()` when the Tonic client drops the connection.

### Risk Assessment
**MEDIUM**: Asynchronous cancellation in Tonic streaming requires tight coordination between channel drops and token cancellation to prevent orphaned runner execution.

---

## 3. Plan 05-10: Typed Event Delivery, Sequence Integrity & Full Snapshots

### Summary
Plan 05-10 fixes event sequencing and snapshot persistence across the workflow. It eliminates the double-increment ordinal bug in [engine/src/workflow/runner.rs:145-146,284-285](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L145-L146) and expands `events::checkpoint` in [engine/src/workflow/events.rs:106-115](file:///D:/Repos/lancet/engine/src/workflow/events.rs#L106-L115) to serialize the full accumulated `WorkflowContext` (including graph context, assembled prompt, citations, notices, and snapshot).

### Strengths
- **Resolves sequence ordinal duplication (WR-03)**: Unifies sequence numbering so `send_event` is the single source of ordinal increments, ensuring sequential ordinals (1..N).
- **Implements full context snapshots (WR-04, D-28)**: Replaces partial JSON serialization in [engine/src/workflow/events.rs:106-115](file:///D:/Repos/lancet/engine/src/workflow/events.rs#L106-L115) with complete context serialization matching the database schema in [gateway/db/models.go](file:///D:/Repos/lancet/gateway/db/models.go).
- **Guarantees terminal emission idempotence**: Emits exactly one `WorkflowCompleted` event per execution, accompanied by `FinalAnswer` on success and no answer frames on failure.

### Concerns
- **[MEDIUM] Event sink backpressure on channel saturation** ([engine/src/workflow/runner.rs:47](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L47)): `tx.try_send` drops events silently if the channel fills up. If the 100-item channel capacity is exceeded, sequence ordinals will have gaps on the receiver side.
- **[LOW] JSON snapshot serialization overhead** ([engine/src/workflow/events.rs:106-115](file:///D:/Repos/lancet/engine/src/workflow/events.rs#L106-L115)): Serializing large assembled prompts and evidence blocks into JSON at every checkpoint creates minor allocation pressure in high-throughput settings.

### Suggestions
- Ensure `WorkflowEventSink` logs a warning or uses async `send` if channel capacity is saturated, preventing unnoticed event loss.

### Risk Assessment
**LOW**: Fixes concrete, well-isolated state-machine bugs in event construction and ordinal accounting.

---

## 4. Plan 05-11: Cross-Runtime Engine-to-Gateway SSE & Checkpoint Dispatch

### Summary
Plan 05-11 implements a live end-to-end cross-runtime test verifying the full gRPC-to-SSE pipeline between the Rust engine and Go gateway. It updates [engine/src/bin/seed_rag_fixture.rs](file:///D:/Repos/lancet/engine/src/bin/seed_rag_fixture.rs) to seed `entities` and `entity_edges` tables for graph augmentation, and resolves the `DispatchPending` drop bug in [gateway/checkpoint_sink.go:168-189](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L168-L189).

### Strengths
- **True cross-runtime integration**: Exercises real network communication between Go gateway and Rust engine over gRPC and raw HTTP SSE streams.
- **Fixes graph fixture seeding gap**: Populates `entities` and `entity_edges` tables in `seed_rag_fixture.rs:72-188`, allowing graph augmentation to return valid graph facts during live tests.
- **Closes checkpoint backpressure drop gap**: Ensures `DispatchPending` results returned when the dispatcher queue is full are retried or drained rather than silently dropped ([gateway/main.go:765-768](file:///D:/Repos/lancet/gateway/main.go#L765-L768)).

### Concerns
- **[HIGH] Hardcoded timeout in Postgres sink** ([gateway/checkpoint_sink.go:99](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L99)): `PostgresCheckpointSink.SaveCheckpoint` creates its own `context.WithTimeout(context.Background(), 5*time.Second)`, ignoring the passed-in context. During gateway shutdown (`d.Close()`), this can delay shutdown if PostgreSQL is slow or unavailable.
- **[MEDIUM] Silent stream termination on transport errors** ([gateway/main.go:726-734](file:///D:/Repos/lancet/gateway/main.go#L726-L734)): If the gRPC stream terminates with an error before `WorkflowCompleted` is received, `queryRAG` breaks out of the loop without emitting an in-band error or diagnostic notice to the SSE client.

### Suggestions
- Pass the parent context into `PostgresCheckpointSink.SaveCheckpoint` rather than instantiating `context.Background()`.
- Add an error-frame or log emission in `gateway/main.go` if the gRPC stream drops before a terminal event is received.

### Risk Assessment
**MEDIUM**: Cross-process integration and database dispatcher shutdown require careful context propagation and error-state handling.

---

## 5. Plan 05-12: Traceability Errata & Documentation Alignment

### Summary
Plan 05-12 updates planning documents (`REQUIREMENTS.md`, `ROADMAP.md`, `STATE.md`, `05-AI-SPEC.md`) to resolve requirement ID ambiguities (e.g., ORCH-01 through ORCH-05 mapping) and align historical documentation with the actual five-node architecture.

### Strengths
- **No code churn**: Confines changes entirely to `.planning/` documentation and specification artifacts.
- **Resolves requirements discrepancies**: Maps all requirements cleanly to test assertions and design contracts.

### Concerns
- **[LOW] Documentation drift**: Must be kept up-to-date with subsequent wave execution outcomes.

### Suggestions
- Verify that requirements traceability tables match the exact automated verification script outputs.

### Risk Assessment
**LOW**: Pure documentation and requirements metadata synchronization with zero runtime impact.

---

## 6. Plan 05-13: OpenRouter Preflight Isolation, Capability Cache & Bounded Retry

### Summary
Plan 05-13 isolates OpenRouter model capability preflights from the 30-second generation attempt budget. It assigns preflights a dedicated 5-second timeout, caches successful capabilities keyed by model/endpoint, maps transient preflight errors to retryable `ProviderError`, and bounds `GenerateAnswerNode` to exactly one byte-identical retry without alternate providers (D-11, D-12, D-13).

### Strengths
- **Decouples preflight from provider attempt budget**: Removes `check_supported_parameters` from the inner generation loop ([engine/src/generation/openrouter.rs:376](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L376)), preventing capability lookups from stealing generation attempt time.
- **Fixes error classification flaw**: Corrects [engine/src/generation/openrouter.rs:305-312](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L305-L312) where transient transport/timeout errors during preflight were misclassified as fatal `SupportedParameters` errors.
- **Reuses cancellation tokens**: Eliminates `CancellationToken::new()` in [engine/src/generation/openrouter.rs:383](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L383), properly forwarding the parent cancellation token into prompt packing.

### Concerns
- **[MEDIUM] Multi-endpoint capability cache keying** ([engine/src/generation/openrouter.rs:39-48](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L39-L48)): The capability cache must key on both `model` and `models_endpoint` to avoid cache collision between production OpenRouter endpoints and local mock servers in test environments.
- **[LOW] In-flight cancellation between attempts** ([engine/src/workflow/nodes/generate.rs:78-84](file:///D:/Repos/lancet/engine/src/workflow/nodes/generate.rs#L78-L84)): The retry loop must check `cancel.is_cancelled()` immediately before dispatching the second generation attempt.

### Suggestions
- Use `(models_endpoint, model)` as the composite cache key in `OpenRouterGenerator`.

### Risk Assessment
**LOW**: Replaces problematic ad-hoc preflight logic with an isolated, cached, cancellation-aware adapter contract.

---

## 7. Plan 05-14: Exhaustive Typed `NodeKind` Dispatch & Early Variant Admission

### Summary
Plan 05-14 defines a closed `NodeKind` enum (`ReformulateQuery`, `ExtractGraphContext`, `RetrieveHybrid`, `AssemblePrompt`, `GenerateAnswer`) and replaces string-based matching in [engine/src/workflow/runner.rs:105-112,173-175](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L105-L112) with exhaustive pattern matching. It also moves the 8-variant limit check to the completion boundary of `ReformulateQueryNode`.

### Strengths
- **Eliminates stringly-typed dispatch**: Replaces string comparisons with compiler-enforced `NodeKind` matches for timeouts, checkpoint names, lifecycle events, and answer-chunk eligibility.
- **Early DoS protection for query fan-out**: Enforces the 8-variant ceiling immediately after reformulation, rejecting excessive variants before calling embedding, graph, or retrieval adapters.
- **Compiler-enforced exhaustiveness**: Adding or modifying a node requires updating all runner match arms, preventing unhandled fallback branches.

### Concerns
- **[LOW] Node trait signature expansion** ([engine/src/workflow/node.rs:17](file:///D:/Repos/lancet/engine/src/workflow/node.rs#L17)): Adding `fn kind(&self) -> NodeKind` requires updates across all node structs and test doubles, but all 5 nodes and test harnesses are explicitly updated in the plan.

### Suggestions
- Implement `Node::name(&self)` as `self.kind().as_str()` to prevent desynchronization between string names and typed kinds.

### Risk Assessment
**LOW**: Clean, idiomatic Rust refactoring that enhances type safety and eliminates runtime string parsing.

---

## 8. Plan 05-15: Prompt API Contract & Test-Double Compilation Isolation

### Summary
Plan 05-15 restores comprehensive rustdoc documentation for the asynchronous prompt packing API in [engine/src/prompt.rs:300-360](file:///D:/Repos/lancet/engine/src/prompt.rs#L300-L360), defines exact `graph_weight` inclusion semantics (0.0 hard-excludes graph facts, >0.0 includes them with retrieval-controlled rank), and gates all `Fake*` workflow ports in [engine/src/workflow/ports.rs:69-363](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L69-L363) behind `#[cfg(test)]`.

### Strengths
- **Resolves WR-10/WR-11**: Documents parameter contracts, cancellation behavior, and `PromptAssemblyError` error variants for `pack_evidence_prompt` and `pack_evidence_and_graph_prompt`.
- **Eliminates production test-double contamination**: Moves `FakeQueryReformulator`, `FakeQueryEmbeddingPort`, `FakeGraphQueryPort`, `FakeDenseRetrievalPort`, `FakeBm25RetrievalPort`, `FakeReranker`, and `FakeGenerator` behind `#[cfg(test)]`, preventing test doubles from being compiled into release binaries.
- **Adds source boundary assertions**: Includes automated source inspection tests ensuring no ungated fake symbols exist in production modules.

### Concerns
- **[MEDIUM] Test target module visibility** ([engine/src/workflow/ports.rs:69](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L69)): Gating ports under `cfg(test)` requires that tests in separate files compile under the library test harness rather than an external binary crate. Plan 05-18 coordinates this split.

### Suggestions
- Verify that `NoOpQueryReformulator` remains available outside `cfg(test)` as it is required for production pass-through reformulation (ORCH-05).

### Risk Assessment
**LOW**: Excellent hygiene improvement that enforces separation between test doubles and production code.

---

## 9. Plan 05-16: Machine-Readable Graph Notices, Typed Graph Port & Notice Merge

### Summary
Plan 05-16 standardizes graph outcome notices to exact machine-readable codes (`GRAPH_TIMEOUT` and `GRAPH_DEGRADED`), upgrades `GraphQueryPort::query_graph` from returning `String` to returning `Vec<GraphFactBlock>`, and implements non-destructive notice accumulation across the workflow context.

### Strengths
- **Fixes miscoded graph degradation notices**: Resolves the bug in [engine/src/workflow/nodes/graph_context.rs:121-125](file:///D:/Repos/lancet/engine/src/workflow/nodes/graph_context.rs#L121-L125) where all graph failures were emitted with `code: "GRAPH_TIMEOUT"`.
- **Aligns GraphQueryPort with Prompt Assembly**: Migrates `GraphQueryPort` from unstructured `String` ([engine/src/workflow/ports.rs:39-45](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L39-L45)) to structured `Vec<GraphFactBlock>`, matching `pack_evidence_and_graph_prompt` ([engine/src/prompt.rs:306-389](file:///D:/Repos/lancet/engine/src/prompt.rs#L306-L389)).
- **Preserves accumulated notices**: Ensures notices from earlier nodes (e.g. graph degradation) are not wiped out by subsequent nodes (e.g. `NO_EVIDENCE` in [engine/src/workflow/nodes/retrieve.rs:159-164](file:///D:/Repos/lancet/engine/src/workflow/nodes/retrieve.rs#L159-L164)).

### Concerns
- **[HIGH] Breaking signature change across port implementations** ([engine/src/workflow/ports.rs:39-45](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L39-L45)): Changing `query_graph` return type from `Result<String, NodeError>` to `Result<Vec<GraphFactBlock>, NodeError>` impacts all implementors (`LanceDbGraphPort`, `FakeGraphQueryPort`) and consumers (`ExtractGraphContextNode`). This must be coordinated carefully across plans 05-08, 05-15, and 05-16.
- **[MEDIUM] Notice deduplication on retry**: If a node or adapter executes multiple attempts, notice appending must avoid creating duplicate notice entries in `WorkflowContext.notices`.

### Suggestions
- Ensure `WorkflowContext::push_notice` or notice merge logic deduplicates identical notices while preserving arrival order.

### Risk Assessment
**MEDIUM**: Port signature migration touches multiple adapters and nodes, requiring synchronized updates to compile cleanly.

---

## 10. Plan 05-17: Protobuf Schema Extensions & Code Generation Preservation

### Summary
Plan 05-17 extends the Protobuf schema in [proto/lancet/v1/lancet.proto](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto) to add `variant_count` (field 10) and `variant_identities` (field 11) to `RetrievalSnapshot`, and `notices` (field 6) to `WorkflowCompletedEvent`. It fixes [buf.gen.yaml:2](file:///D:/Repos/lancet/buf.gen.yaml#L2) by setting `clean: false` and adding pre/post guards so that `buf generate` does not delete [engine/src/pb/mod.rs](file:///D:/Repos/lancet/engine/src/pb/mod.rs).

### Strengths
- **Prevents code-generation file deletion**: Corrects `clean: true` in `buf.gen.yaml`, which previously deleted the hand-written `engine/src/pb/mod.rs` during generation.
- **Full backward compatibility**: Adds fields using standard additive Protobuf numbering (fields 6, 10, 11) without altering existing field IDs or semantics.
- **Pre-generates Rust and Go bindings**: Commits generated `lancet.v1.rs` and `lancet.pb.go` to the repository, ensuring builds succeed even without the `buf` CLI.

### Concerns
- **[HIGH] External plugin dependencies during `buf generate`** ([buf.gen.yaml:4-17](file:///D:/Repos/lancet/buf.gen.yaml#L4-L17)): Remote plugin calls (`neoeinstein-prost`, `neoeinstein-tonic`, `protocolbuffers/go`) require network access if regenerating bindings from scratch in offline CI environments.
- **[LOW] Protobuf field ordering**: The chosen field tags (10, 11 on `RetrievalSnapshot` and 6 on `WorkflowCompletedEvent`) are contiguous and correct.

### Suggestions
- Include the generated `.rs` and `.pb.go` files directly in the commit to avoid mandatory remote `buf` execution during standard builds.

### Risk Assessment
**MEDIUM**: Schema generation touches both Rust and Go codebases; keeping committed generated files guarantees offline build reliability.

---

## 11. Plan 05-18: Library vs. Binary Test Target Separation

### Summary
Plan 05-18 restructures the Rust test architecture by registering generic workflow tests ([engine/src/tests/workflow_phase5.rs](file:///D:/Repos/lancet/engine/src/tests/workflow_phase5.rs)) under [engine/src/lib.rs](file:///D:/Repos/lancet/engine/src/lib.rs) for library unit testing, while keeping binary-only tests ([engine/src/tests/workflow_phase5_production.rs](file:///D:/Repos/lancet/engine/src/tests/workflow_phase5_production.rs)) under [engine/src/tests.rs](file:///D:/Repos/lancet/engine/src/tests.rs).

### Strengths
- **Enables `cfg(test)` port isolation**: Allows `Fake*` workflow ports to be compiled under `cargo test --lib` while remaining completely excluded from production binary compilation.
- **Clean separation of test scopes**: Fast unit tests run under `--lib` with simulated components, while production wiring tests run under `--bin engine`.
- **Maintains existing test coverage**: Preserves all existing Phase 05 test cases while splitting them cleanly across appropriate targets.

### Concerns
- **[MEDIUM] Module re-export synchronization** ([engine/src/tests.rs:11](file:///D:/Repos/lancet/engine/src/tests.rs#L11)): Moving `pub mod workflow_phase5;` from `tests.rs` to `lib.rs` requires verifying that all downstream test scripts and verify commands target `--lib` or `--bin engine` explicitly.

### Suggestions
- Audit all verification commands across all plans to ensure every `cargo test` invocation specifies the correct target flag (`--lib` or `--bin engine`).

### Risk Assessment
**LOW**: Standard, idiomatic Rust project structuring that eliminates circular compilation dependencies between test doubles and the binary target.

---

## 12. Plan 05-19: Failure Terminal Notice Propagation from Runner to SSE

### Summary
Plan 05-19 propagates accumulated context notices (e.g. `GRAPH_DEGRADED` or `GRAPH_TIMEOUT`) onto failure terminal events. It populates `WorkflowCompletedEvent.notices` in [engine/src/workflow/events.rs](file:///D:/Repos/lancet/engine/src/workflow/events.rs) and [engine/src/workflow/runner.rs](file:///D:/Repos/lancet/engine/src/workflow/runner.rs) when a workflow fails, and maps them in [gateway/main.go:806-816](file:///D:/Repos/lancet/gateway/main.go#L806-L816) into the final SSE frame while omitting answer payloads.

### Strengths
- **Resolves notice loss on terminal failure (WR-07)**: Guarantees that diagnostic notices accumulated prior to a failure are delivered to the client in the `workflow_completed` event.
- **Preserves answer-free failure contract (D-05, D-13)**: Emits no `AnswerChunk` or `FinalAnswer` events on failure, and leaves `final_response` absent in the `workflow_completed` SSE payload.
- **Dual Rust and Go verification**: Contains exact test assertions in both `engine/src/tests/workflow_phase5.rs` and `gateway/main_test.go` verifying notice delivery on failure.

### Concerns
- **[LOW] JSON serialization of absent fields** ([gateway/main.go:813-815](file:///D:/Repos/lancet/gateway/main.go#L813-L815)): Gateway must verify `final_response` key is omitted from JSON output when nil, avoiding null field pollution.

### Suggestions
- Assert that `final_response` is omitted from the raw JSON string in `gateway/main_test.go` when `success` is false.

### Risk Assessment
**LOW**: Clear, well-bounded data propagation fix that closes a client observability gap without architectural risk.

---

## 13. Plan 05-20: Capability Preflight Bootstrap Seam & Budget Timing Regression

### Summary
Plan 05-20 introduces a `Node::prepare` bootstrap seam executed before `GenerateAnswerNode` starts its 65000ms timer. It proves through a timing regression that a 5000ms preflight followed by two 30000ms provider attempts fits within the derived workflow budget without premature cancellation. It gates execution of the 9 production binary filters until after target registration.

### Strengths
- **Solves the retry timeout race**: Separates the one-time capability preflight from the 65-second node timer, ensuring two full 30-second provider attempts can execute without being cut short by preflight overhead.
- **Formalizes runner bootstrap phase**: Adds an explicit `prepare` lifecycle hook on `Node` for preflight operations before the per-node execution deadline starts.
- **Enforces strict test execution gating**: Defers production binary filter execution until after target registration in 05-18 and fixture handoffs in 05-16.

### Concerns
- **[MEDIUM] Default trait implementation for `Node::prepare`** ([engine/src/workflow/node.rs:17](file:///D:/Repos/lancet/engine/src/workflow/node.rs#L17)): `Node::prepare` must provide a default no-op implementation (`async { Ok(()) }`) so that the other four nodes do not require boilerplate overrides.
- **[LOW] Simulated time in tests**: Wall-clock timeout tests must avoid real 65-second sleeps in automated CI by using Tokio mock time or scaled test timeouts.

### Suggestions
- Provide a default `prepare` method on `Node` returning `Box::pin(async { Ok(()) })`.
- Use `tokio::time::pause()` in unit tests to simulate timing budgets deterministically without real-time delay.

### Risk Assessment
**LOW**: Cleanly resolves the timing budget collision between provider preflight and node retry execution.

---

## 14. Plan 05-21: Typed Fusion Provenance Source & Dead Serde Cleanup

### Summary
Plan 05-21 refactors [engine/src/retrieval/fusion.rs:15-35](file:///D:/Repos/lancet/engine/src/retrieval/fusion.rs#L15-L35) to replace `source: String` in `VariantProvenance` with a strongly typed `VariantProvenanceSource` enum (`Vector`, `Bm25`), and removes the ineffective `#[serde(default)]` annotation on `variant_provenance`.

### Strengths
- **Type safety for fusion provenance**: Prevents invalid source strings and eliminates runtime string allocations during candidate fusion.
- **Removes dead code**: Removes `#[serde(default)]` from `FusedCandidate` (which only derives `Serialize`, not `Deserialize`).
- **Preserves JSON serialization format**: Uses `#[serde(rename_all = "lowercase")]` to maintain stable `"vector"` and `"bm25"` output strings in serialized API responses.

### Concerns
- **[LOW] API contract stability**: Serialization format is verified by unit tests to remain lowercase string values.

### Suggestions
- Add a test verifying `serde_json::to_string` of `VariantProvenance` matches the expected lowercase JSON strings.

### Risk Assessment
**LOW**: Minor, high-quality cleanup of type definitions and serialization attributes with zero regression risk.

---

## 15. Cross-Plan Synthesis & Phase 05 Verdict

### Wave Dependency Graph & Execution Order
The 14 plans form a well-ordered dependency DAG across waves 7 through 17:
1. **Wave 7**: Plan 05-08 (Production Node Wiring) & Plan 05-12 (Traceability & Requirements Errata)
2. **Wave 8**: Plan 05-09 (Workflow Settings, Node Timeouts & Stream Cancellation)
3. **Wave 9**: Plan 05-13 (OpenRouter Preflight Isolation & Bounded Retry)
4. **Wave 10**: Plan 05-14 (Exhaustive Typed `NodeKind` Dispatch)
5. **Wave 11**: Plan 05-17 (Protobuf Extension & `buf.gen.yaml` fix) & Plan 05-18 (Library/Binary Test Target Split)
6. **Wave 12**: Plan 05-15 (Async Prompt Docs & `cfg(test)` Fake Ports)
7. **Wave 13**: Plan 05-16 (Machine-Readable Graph Notices & Typed Graph Port)
8. **Wave 14**: Plan 05-10 (Typed Events, Sequence Ordinals & Full Snapshots) & Plan 05-21 (Typed Fusion Source)
9. **Wave 15**: Plan 05-19 (Failure Terminal Notice SSE Propagation)
10. **Wave 16**: Plan 05-20 (Preflight Bootstrap Seam & Timing Regression)
11. **Wave 17**: Plan 05-11 (Real Engine-to-Gateway SSE & Lossless Checkpoint Drain)

### Gap-Closure Verification
Together, plans 05-08 through 05-21 completely cover all gaps identified in the baseline verification report and review findings:
- **Five-node production execution**: 05-08 and 05-14 replace inline remainder execution with full five-node runner dispatch.
- **Workflow settings & timeouts**: 05-09 wires `[engine.workflow]` settings and validates 7000ms node timeout against 30s provider budget.
- **Preflight & retry separation**: 05-13 and 05-20 isolate 5s preflight from two 30s generation attempts.
- **Event sequencing & full snapshots**: 05-10 and 05-19 eliminate duplicate ordinals, serialize full context snapshots, and deliver notices on failure.
- **Test-double & schema hygiene**: 05-15, 05-17, 05-18, and 05-21 gate test fakes to `cfg(test)`, fix `buf.gen.yaml`, split test targets, and type provenance sources.
- **Cross-runtime end-to-end integration**: 05-11 validates live gRPC-to-SSE streaming, entity fixture seeding, and lossless checkpoint sink dispatch under backpressure.

### Final Recommendation
The gap-closure plan suite is **approved for execution** according to the wave schedule. Execution should follow the wave sequence without skipping intermediate compilation checks.

---

## Claude Review

# Cross-AI Plan Review — Phase 05 Gap Closure (05-08 … 05-21)

*Independent review against the working tree at `D:\Repos\lancet`, HEAD `6db8862` (confirmed via `git rev-parse HEAD`). `05-REVIEWS.md` was read only to identify which prior findings the revision claims to close; every such claim was re-derived from source. No repository or planning files were edited.*

---

## 1. Summary

This revision closes the three HIGH findings from the prior cycle, and I confirmed each closure against source rather than against the plans' own prose. 05-17 now owns all four exhaustive generated-message literals (`retrieve.rs:145`, `main.rs:1352`, `main.rs:1499`, `events.rs:131`) and gates them with `cargo check --lib` + `--bin`, so the additive proto fields no longer break the crate at wave 11; I verified there are no `RetrievalSnapshot`/`WorkflowCompletedEvent` literals in Rust test code and that every Go literal is keyed, so `cargo check` is genuinely sufficient there. 05-08 now registers `workflow_phase5_production` itself, owns the 25 `Fake*Port` call sites in `engine/src/tests.rs`, and runs `cargo test --bin engine --no-run` **and** `--lib --no-run` at wave 7 — which both closes the GraphQueryPort compile break and narrows the knowingly-red binary-test window from seven waves to two (11–13), now explicitly documented in `05-VALIDATION.md`. 05-08 Task 3 also takes ownership of the four `service.query_rag(` call sites I confirmed at `engine/src/tests.rs:352,2378,2442,3403`, including the `query_rag_tracer` that `05-VERIFICATION.md` names as the mechanism by which the suite stayed green. 05-12's frozen baseline is verifiably exact: I checked all fourteen literal blob hashes against `git rev-parse HEAD:<path>` and all fourteen match byte-for-byte.

The residual risk has shifted from *structural* to *guard quality*. One verification guard (05-16's replacement for the previously-vacuous BM25 check) is anchored on the wrong region and will throw on a correct implementation while leaving its two negative assertions inert. Separately, three plans author test bodies into a module that is already compilable and choose not to compile it, and two plans (05-13/05-20) both claim removal of the OpenRouter preflight from `execute_one_call` — an ambiguity that, under one reading, silently drops the D-27 capability check for seven waves and breaks roughly eleven existing mock-server tests that neither plan names.

None of this is a design problem. The BM25 guard is a two-line regex fix; the rest are file-inventory and ownership-sentence additions.

---

## 2. Strengths

**The prior HIGH-1 compile break is genuinely fixed, and the fix is minimal-touch as recommended.** `05-17-PLAN.md` `files_modified` now includes `engine/src/workflow/nodes/retrieve.rs`, `engine/src/workflow/events.rs`, and `engine/src/main.rs`, and its `<scope_rationale>` states the initialize-empty/enrich-later split explicitly. I confirmed all four sites are exhaustive field-init with no `..Default::default()`:

| Site | Message | Compiled by |
|---|---|---|
| `engine/src/workflow/nodes/retrieve.rs:145-155` | `RetrievalSnapshot` | lib + bin |
| `engine/src/main.rs:1352-1375` | `RetrievalSnapshot` | bin |
| `engine/src/main.rs:1499-1526` | `RetrievalSnapshot` | bin |
| `engine/src/workflow/events.rs:131-137` | `WorkflowCompletedEvent` | lib + bin |

A grep for those two message names across `engine/src/tests.rs`, `engine/src/tests/`, `engine/src/retrieval/tests.rs`, and `engine/src/generation/tests.rs` returns nothing, and `gateway/main_test.go:719,841,934,2356,2391` all use keyed struct literals — so 05-17's `cargo check --lib`/`--bin` pair is a sufficient gate. The defensive `cargo check` addition recommended last cycle was adopted.

**05-08's production-builder guard remains the strongest in the set, and its region extraction is sound.** The `(?s)async fn query_rag\b.*?(?=\n\s*(?:pub\s+)?(?:async\s+)?fn\b|\z)` idiom anchors on `engine/src/main.rs:1656` and terminates at `async fn query_graph(` (~1781), correctly bracketing the whole handler body — I checked for nested `fn` inside that span and found none. The guard requires five `self.*` service fields, ≥7 `Some(` slots against the seven-field `WorkflowDependencies` (`engine/src/workflow/mod.rs:111-120`), exactly five `add_node` calls, positional D-06 ordering, and rejects any `Fake*` type. The `self.nodes` omission flagged last cycle is closed: Task 3's guard now requires `self.nodes`, matching the real dense source at `engine/src/main.rs:1293` (`DenseRetriever::new(self.nodes.clone())`), a distinct field from the five originally listed.

**Retiring the inline monolith is now correctly specified as a deletion.** `execute_inline_query_rag_remainder` has exactly one caller repo-wide (`engine/src/main.rs:1742`, from `query_rag`), so 05-08 Task 3's absence guard is achievable without leaving dead private code — the LOW-2 suggestion was adopted verbatim.

**05-18's BM25 arithmetic is exact.** `grep -cE 'RwLock::new\(bm25_index(1|2)?\)' engine/src/tests.rs` returns **18**, and `grep -cE 'RwLock::new\('` also returns 18 — so old and new patterns are provably non-overlapping and there are no unrelated `RwLock::new` fixtures to catch by accident. `engine/src/tests.rs:11` is confirmed the only `pub mod workflow_phase5;`, and `engine/src/lib.rs:3-11` declares no test module.

**05-11's fixture design is grounded in the real schema and the real mock.** `entities_schema()` (`engine/src/db/mod.rs:231-243`) and `entity_edges_schema()` (`:246-256`) contain exactly the columns the plan names; `entities_table()`/`entity_edges_table()` exist at `:144`/`:152` while `engine/src/bin/seed_rag_fixture.rs:73-75` opens only documents/nodes/edges — the gap is real. Critically, the `[1.0, 2047 zeros]` name-vector contract is not arbitrary: `gateway/main_test.go:2058-2059` already builds exactly `vector := make([]float32, 2048); vector[0] = 1` as the mock embedding response, so a matching seeded `name_vector` yields zero distance, and `dense_score(distance)` (`engine/src/retrieval/dense.rs:162`, consumed at `main.rs:1121-1123`) is compared against `seed_match_min_score`. The two literals the guard pins in the Go body are correct, not decorative.

**05-13's provider diagnosis is exact at the line level.** `execute_one_call` opens with `self.check_supported_parameters().await?` (`openrouter.rs:376`); that function maps *every* `reqwest` send failure — including timeouts — to `GenerationErrorKind::SupportedParameters` (`:297-302`); and `GenerateAnswerNode` treats exactly that kind as non-retryable (`nodes/generate.rs:73-76`). All wrapped in the shared `timeout(self.config.timeout, …)` at `:629`.

**05-09's config diagnosis and durable-regression fix are both correct.** `EngineSettings` (`main.rs:172-179`) has no `workflow` field and no `deny_unknown_fields`. The shipped `config_workflow_timeout_overlays_match_contract` (`engine/src/tests.rs:259-289`) asserts only `content.contains(key)` — no value anywhere. Strengthening that named test converts a one-shot plan guard into a repository regression. The LOW-1 coupling concern is correctly resolved: `scripts/phase02_live_evidence.py:177-196` reads only `engine.lancedb_path` from `config.verify.toml`, so raising `generation_timeout_secs` 1→30 is safe.

**05-12's preservation guard is verified correct, not aspirational.** All fourteen declared blobs match `HEAD` (`05-01-PLAN 1862cb91…`, `05-02-PLAN 2a80165e…`, `05-06-PLAN 8e4511e1…`, `05-07-SUMMARY b7bdad3e…`, and the remaining ten likewise). Using both `git rev-parse HEAD:<path>` and `git hash-object` with path-scoped staged/unstaged checks is stronger than a bare `git diff --check`, and the path scoping means 05-08 editing `main.rs` in the same wave cannot trip it.

**The wave DAG is acyclic and monotonic**, and 05-18's documented rejection of a direct 05-16 edge (`05-18-PLAN.md:51`) is correct reasoning — `05-16 → 05-15 → 05-18` already exists.

**Scope discipline holds.** `QueryGraph` is still unary at `proto/lancet/v1/lancet.proto:12` and untouched (D-10); the two proto additions are framed as D-07/D-08 provenance, not deferred D-30 metadata; and no plan introduces token counts, `degraded_mode`, per-node spans, resume, a backup provider, or a checkpoint fetch API.

---

## 3. Concerns

### HIGH-1 — 05-16's replacement BM25 guard anchors on the struct field, not the adapter: it will throw on a correct implementation, and its two negative assertions are inert

`05-16-PLAN.md` Task 2 replaces the previously-vacuous `clone()` check with:

```powershell
$bm25Region = [regex]::Match($main,
  '(?s)(?:bm25_index|Bm25RetrievalPort).*?(?=\n\s*(?:pub\s+)?(?:async\s+)?fn\b|\z)').Value
if ([string]::IsNullOrWhiteSpace($bm25Region) -or $bm25Region -notmatch 'Arc::clone\s*\(') { throw … }
```

`[regex]::Match` returns the **leftmost** match. The first `bm25_index` in `engine/src/main.rs` is the struct field at line 864, and the lazy `.*?` terminates at the first `\n\s*fn\b` — `fn d1_status(` at line 872:

```
864:     bm25_index: Arc<tokio::sync::RwLock<Bm25Index>>,
…
870: }
871:
872: fn d1_status(
```

The extracted region is lines 864–870 — remaining struct fields and a closing brace. Renaming the field's *type* to `RwLock<Arc<Bm25Index>>` does not move it. Consequences, both bad:

- **False blocker.** That region contains no `Arc::clone(`, so the guard throws `'production BM25 snapshot region does not show inner Arc cloning'` even when the adapter is implemented exactly as specified. The same expression appears in Task 2's first automated block, so the task cannot pass.
- **Inert negatives.** `if ($bm25Region -match 'read\(\)\.await[\s\S]{0,300}(?:\.await|retrieve\s*\()')` and the `to_vec()`/clone-before-`retrieve` check operate on the same field-declaration region, which contains no `.await` and no `retrieve(` — so the two invariants the plan exists to protect are never checked. The real hazard lives at `main.rs:1311-1321`, far outside the region.

Only the final file-scope check (`$main -notmatch 'RwLock\s*<\s*Arc\s*<\s*Bm25Index\s*>'`) is sound, and it only pins the field type. The behavioural test `workflow_phase5_bm25_snapshot_releases_lock` remains the real proof — and the plan is right that it must supply its own writer, since `grep 'bm25_index.write'` over `engine/src` returns nothing.

### MEDIUM-1 — 05-13 and 05-20 both claim removal of the preflight from `execute_one_call`

05-13 Task 1: *"Move capability preflight out of the per-attempt request body…"*
05-20 Task 1: *"…**remove that preflight from execute_one_call**."*

05-20 (wave 16) assumes the call site is still there; 05-13 (wave 9) says it moves it out. Under the **benign** reading, 05-13 hoists the call to `generate()` outside the `timeout(self.config.timeout, …)` wrapper at `openrouter.rs:629` and 05-20's clause is a no-op. Under the **literal** reading, 05-13 deletes it and no replacement caller exists until `Node::prepare` at wave 16 — D-27 capability verification silently does not run for seven waves. Nothing in either plan disambiguates.

### MEDIUM-2 — 05-13's successful-only cache contradicts a named existing test; ~11 mock servers assume a `/models`-then-`/chat` accept sequence

`engine/src/generation/tests.rs` has ~11 OpenRouter tests whose `TcpListener` threads accept `/models` first and `/chat/completions` second, because `execute_one_call` always preflights today (`:298, :406, :499, :582, :742, :818, :885, :947, :1013, :1080, :1241`).

`openrouter_effective_usage_limits` is the sharp case: its mock accepts **four** connections — models, chat, **models again**, chat — for two `generate()` calls on the *same* adapter (`:1084-1168`). 05-13's acceptance criterion states *"A successful capability response is fetched once for repeated calls with the same configured model/endpoint"* — a direct contradiction. Worse, the failure mode is not a red build: with the third `accept()` unsatisfied, the server thread parks and `server_handle.join()` at `:1202` blocks — a CI hang.

The WR-04 text this derives from literally suggests a `OnceCell`. 05-13 says "keyed to the configured model and endpoint identity" but never says instance-scoped vs. process-global — and since every test binds a fresh random port, only this test distinguishes the two. `generation/tests.rs` **is** in 05-13's `files_modified`, so it is fixable in scope; the plan simply never mentions it.

### MEDIUM-3 — Three waves author test bodies into an already-compilable module while gating only with `cargo check`

05-08 registers `workflow_phase5_production` at wave 7 and proves it compiles with `cargo test --bin engine --no-run`. That capability then goes unused:

| Wave | Plan | Bodies authored | Gate used |
|---|---|---|---|
| 8 | 05-09 | `…_settings_applied_to_production`, `…_config_verify_generation_timeout` | `cargo check --bin engine` |
| 9 | 05-13 | `…_generation_retry_tracer`, `…_generation_retry_exhausted` | `cargo check --bin engine` |
| 10 | 05-14 | `…_nodekind_tracer`, `…_dispatch`, `…_exhaustive` | `cargo check --bin engine` |

`cargo check --bin engine` does not compile `#[cfg(test)]` code (`main.rs:3173-3174` gates `mod tests;`), so all seven bodies are validated only by `.Contains('<name>')`. The BM25 break that justifies the Waves 7–13 exception does not begin until wave 11, so waves 8–10 could each run `--no-run` at no cost. As written, all nine production filters still first *execute* at wave 16.

### MEDIUM-4 — 05-08's anti-fabrication guard forces a behaviour change that three shipped tests drive

05-08 Tasks 2/3 scan `engine/src/workflow/mod.rs` for `'Answer for {'` and throw if present. That is `mod.rs:212` — the no-generator placeholder inside `run_inline_prompt_generation_remainder`, which currently emits `answer_chunk(is_final=true)` + `final_answer` + `workflow_completed(success=true)` with `AnswerBasis::Retrieval`. Removing it (correctly) changes the contract for its only callers: `engine/src/tests.rs:7134`, `:7210`, `:7323`. That file is in scope, but no task text or acceptance criterion mentions those three sites — and Task 2 explicitly *permits* the helper to survive without saying its placeholder branch must nonetheless change.

### LOW-1 — 05-11's function-scoped guard requires a literal (`graph-fact`) the action never specifies

The guard requires `@('enginePath','LANCET_OPENROUTER__CHAT_ENDPOINT','exec.Command','/rag/query','graph-fact','parseSSEEvents')` in the `TestRAGQueryCrossRuntime` body. A repo-wide grep shows `graph-fact` appears only in Rust (`generation/mod.rs:380`, `prompt.rs:393`, `tests.rs:5743,5953,6937,7021`) and **nowhere in `gateway/`**. The action instead specifies `GRAPH_FIXTURE_MARKER_SEED`/`_NEIGHBOR`/`_RELATION`. (The sibling whole-file needle list is also weak — it checks `$source`, so `node_started`/`GenerateAnswer` can be satisfied by any other test in the 3000-line file. The exact-literal block, by contrast, correctly pins real code at `main_test.go:2058-2059`.)

### LOW-2 — 05-11's seeder column contract under-enumerates what `validate_schema` requires

`validate_schema` (`db/mod.rs:161-174`) compares `actual.fields() != expected.fields()` — a strict full-field comparison. `entities_schema()` requires nine fields including nullable `summary`, `summary_vector`, `unsummarized_refs`, `community_ids`; `entity_edges_schema()` requires eight including `summary` and `summary_vector`. The plan names only "nullable summary columns". A `RecordBatch` missing any field fails `try_new` before the read-back assertions run.

### LOW-3 — 05-15 offers a remediation option its file inventory cannot execute

05-15 Task 1 offers `#[cfg(test)] pub(crate)` **or** removal "after updating their callers". The callers of `pack_evidence_prompt_sync`/`pack_evidence_and_graph_prompt_sync` (`prompt.rs:234,255`) live in `generation/tests.rs` and `tests.rs`, neither in `files_modified`. Only the gating option is executable. *(Gating is otherwise safe: `main.rs:35` declares its own `pub mod prompt;` alongside `lib.rs:8`, so `prompt.rs` compiles into both targets.)*

### LOW-4 — `clean: false` disables stale-output cleanup for the Go roots too

`buf.gen.yaml:2` sets `clean` above all four plugin `out` roots. Flipping it to `false` correctly protects `engine/src/pb/mod.rs` (the `include!` glue that `05-VERIFICATION.md:201` records as hand-restored once already), but the declared compensations — a four-path existence inventory and `buf lint` — cannot detect a *stale* file left behind after a future message rename.

---

## 4. Suggestions

1. **(HIGH-1)** Rewrite 05-16's region extraction to anchor on the adapter (e.g. `(?s)impl\s+Bm25RetrievalPort\s+for\s+\w+.*?(?=\n\}\s*\n|\z)`), or drop region extraction and assert at file scope that `main.rs` contains `RwLock<Arc<Bm25Index>>` **and** no `bm25_guard` binding surviving a subsequent `.await`. The guard must be able to fail on a wrong implementation and pass on the right one; the current expression does the opposite of both.
2. **(MEDIUM-1)** Add one sentence to 05-13 Task 1 stating whether the preflight is *relocated within `generate()`* or *deleted*. If relocated, delete the corresponding clause from 05-20 Task 1.
3. **(MEDIUM-2)** Name `openrouter_effective_usage_limits` (`generation/tests.rs:1080`) in 05-13's action, state the cache is per-`OpenRouterGenerator` instance (not a global `OnceCell`), and add an acceptance line covering the other ten mocks' accept sequencing. Consider bounding the affected `server_handle.join()` calls so a regression fails rather than hangs.
4. **(MEDIUM-3)** Add `cargo test --bin engine --manifest-path engine/Cargo.toml --locked --no-run` to 05-09, 05-13, and 05-14's verify blocks — safe at waves 8–10, and it compile-checks seven test bodies six waves earlier.
5. **(MEDIUM-4)** Add an explicit line to 05-08 Task 2 that `run_inline_prompt_generation_remainder`'s placeholder branch (`workflow/mod.rs:210-218`) becomes a typed `LlmGenerationFailed`, and that `tests.rs:7134/7210/7323` are updated accordingly.
6. **(LOW-1)** Replace `'graph-fact'` with `'GRAPH_FIXTURE_MARKER_SEED'` in 05-11's needle list; consider switching the whole-file list to `$body`.
7. **(LOW-2)** Enumerate all nine `entities` and eight `entity_edges` columns in 05-11's seeder action.
8. **(LOW-3)** Drop the "or remove them" option from 05-15 Task 1.

---

## 5. Coverage Assessment

| Verified gap | Owning plans | Assessment |
|---|---|---|
| **SC1** — pipeline not a state machine in production | 05-08, 05-14, 05-16 | **Covered.** 05-08's guard is un-satisfiable by a library-only change. Weakened at the margin by MEDIUM-4. |
| **SC2** — events not emitted; `AnswerChunk` unreachable | 05-08, 05-10, 05-11, 05-17, 05-19 | **Covered.** The generated `notices` field the failure path needs now lands compile-clean at wave 11. |
| **SC3** — timeouts/retry/cancellation unwired | 05-09, 05-13, 05-14, 05-20 | **Covered.** `5000 + 97000 = 102000` and `65000 = 2×30000 + 5000` both check out; 4999ms and 9999ms pre-deadline regressions added (closing IN-05); the live proof is now protected by a durable assertion. Residual risk is MEDIUM-1/2. |
| **SC4** — snapshots hollow; `DispatchPending` discarded | 05-08, 05-10, 05-11, 05-16 | **Covered.** 05-10's 19-field list is exactly `WorkflowContext`'s current 18 fields (`workflow/mod.rs:29-48`) plus the `graph_facts` field 05-08 adds. |
| **SC5** — `QueryReformulator` port | 05-08, 05-14 | **Covered.** Nine-variant admission correctly moves ahead of `NodeCompleted`, fixing the `runner.rs:180-201` completed-then-failed sequence. |
| **Traceability** | 05-12 | **Covered and verified.** Corrections match the PLAN declarations; all fourteen historical blobs hash-verified. |

**Review-ledger coverage** (8 CR / 14 WR / 5 IN): every finding retains a named owner, no orphans. WR-14 → 05-16 (guard defective per HIGH-1, behavioural test sound). **05-21** is small and correctly grounded: `VariantProvenance.source` is a `String` (`fusion.rs:19`) filtered by `== "vector"`/`"bm25"` at `:145,153` while `Source` already exists at `:180-184`, and `#[serde(default)]` at `:33` sits on a `Serialize`-only struct.

---

## 6. Overall Risk Assessment

**MEDIUM** — down from HIGH, and the reduction is earned rather than asserted.

Design risk is **LOW**: real mechanisms at real line numbers, unusually specific guards, a provably acyclic DAG, a git-verified frozen baseline, and all three prior HIGHs closed with source-level evidence including the one that was a hard stop.

Execution risk is **MEDIUM**: HIGH-1 will halt 05-16 Task 2 on a correct implementation and, if patched around carelessly, discards the two invariants it exists to protect. MEDIUM-1 and MEDIUM-2 compound — the ambiguous preflight ownership is what makes the mock-sequencing break plausible rather than theoretical, and its sharpest instance fails by *hanging* rather than failing red. MEDIUM-3 is pure missed opportunity.

With suggestions 1–5 applied (one regex rewrite, two disambiguating sentences, three `--no-run` additions, one ownership sentence) I would rate this **LOW-MEDIUM** and recommend execution. As written, I recommend one bounded revision pass — smaller than the last, and confined to verify blocks and ownership prose rather than plan structure.

*Full review also written to `C:\Users\user3\.claude\plans\cross-ai-plan-validated-simon.md`.*

---

## Consensus Summary

This is a fresh review of the live checkout at the source_head above. The prompt supplied to both reviewers excluded the prior 05-REVIEWS.md and scoped review to the revised 05-08 through 05-21 plans. Claude mentions inspecting the prior artifact locally to identify claimed closures, but states that its findings were re-derived against current source; no prior verdict is reused here.

### Agreed Strengths

- The 14-plan wave DAG is coherent and covers the verified Phase 05 gaps: production five-node wiring, live settings and deadlines, event/snapshot propagation, cross-runtime SSE, test-target separation, protobuf compatibility, and traceability.
- The revised plans contain unusually concrete source and verification ownership. In particular, 05-08 production-builder guards, 05-12 frozen-plan hash checks, and 05-17/05-18 target and generated-code gates materially reduce the risk of silently passing a library-only or stale-artifact implementation.
- The timing design separating capability preflight from the generation node budget, and the event/snapshot/terminal-notice path across Rust and Go, is directionally sound and addresses the baseline verification failures.

### Agreed Concerns

- Clarify the ownership and lifecycle of OpenRouter capability preflight across 05-13 and 05-20. Both reviewers identified cache/endpoint or sequencing risk; the plans should state whether preflight is relocated within generation, performed by Node::prepare, or removed, and whether the successful-only cache is per generator instance and keyed by model plus endpoint.
- Make test-target execution guarantees explicit at each wave. Both reviewers noted that production binary versus library test visibility is a real seam; code that is only text-checked or compiled with cargo check can leave newly authored cfg(test) bodies uncompiled until much later.
- Keep event delivery and cancellation lossless under saturation and client disconnect. Antigravity specifically flagged try_send backpressure and detached-task cancellation; these remain execution-sensitive even though the plans assign ownership to the sink/stream work.

### Divergent Views

- Overall readiness differs: Antigravity rates the suite LOW risk and recommends execution; Claude rates it MEDIUM and recommends one bounded revision pass before execution.
- Claude identifies a HIGH, source-specific blocker in 05-16: the BM25 PowerShell region regex begins at the first bm25_index field declaration, so it cannot see Arc::clone and leaves the intended await/lock assertions inert. Antigravity did not flag this guard defect.
- Claude also identifies 05-13/05-20 preflight wording ambiguity, the existing OpenRouter mock sequencing/hang risk, missing early cargo test --no-run gates, 05-08 placeholder-test ownership, and several lower-severity fixture/guard inventory issues. Antigravity instead emphasizes runtime dependency validation, detached stream cancellation, checkpoint sink timeout behavior, remote buf plugin availability, and protobuf/test-module synchronization.
- The practical combined disposition is therefore MEDIUM execution risk despite strong design coverage: the plan structure is close, but the 05-16 guard and preflight/test-gating ownership should be corrected or explicitly accepted before starting the 21-plan execution wave.
