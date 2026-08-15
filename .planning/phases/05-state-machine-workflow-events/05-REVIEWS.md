---
phase: 5
scope: gap-closure
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-15T09:10:19Z
source_head: 7b2f5b0410f9da415d3c5900f530a68ae94f432b
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
  antigravity: 35154
  claude: 51917
---

# Cross-AI Plan Review — Phase 05 Gap Closure (Fresh)

## Antigravity Review

# Comprehensive Architecture and Plan Review: Phase 05 Gap-Closure Plans (05-08 through 05-21)

This review evaluates the fourteen additive gap-closure plans (`05-08-PLAN.md` through `05-21-PLAN.md`) for **Phase 05: State Machine & Workflow Events** in the Lancet codebase at `HEAD 7b2f5b0410f9da415d3c5900f530a68ae94f432b`. All file paths are resolved against the repository root `D:\Repos\lancet`.

---

## 1. Plan-by-Plan Detailed Analysis

### Plan 05-08: Production Five-Node Wiring, Adapter Dependencies, and Context Flow (Wave 7)

#### Summary
Plan 05-08 establishes the concrete production wiring for the five-node state machine (`ReformulateQuery -> ExtractGraphContext -> RetrieveHybrid -> AssemblePrompt -> GenerateAnswer`), eliminating the temporary inline shortcut in `engine/src/main.rs:1738-1748` and the placeholder fallback in `engine/src/workflow/mod.rs:210-218`. It restores the typed `Vec<GraphFactBlock>` contract on `GraphQueryPort` (`engine/src/workflow/ports.rs:39-45`), ensures `WorkflowDependencies` are populated with live service adapters, and introduces four dedicated production regression tests in `engine/src/tests/workflow_phase5_production.rs`. The plan is structurally sound, highly feasible, and directly restores core architecture alignment.

#### Strengths
- **Eliminates Architectural Bypass**: Removes the inline remainder execution in `engine/src/main.rs:1738-1748` where retrieval, prompt assembly, and generation bypassed the workflow node pipeline.
- **Removes Synthetic Fallbacks**: Completely deletes the fallback path in `engine/src/workflow/mod.rs:210-218` that fabricated fake answers when generator dependencies were omitted.
- **Restores Typed Graph Context**: Updates `GraphQueryPort::query_graph` (`engine/src/workflow/ports.rs:39-45`) to return structured `Vec<GraphFactBlock>` matching `engine/src/prompt.rs:164-166`, preserving graph entity metadata for prompt assembly.
- **Dedicated Production Test Target**: Establishes binary-owned test fixtures in `engine/src/tests/workflow_phase5_production.rs` to verify production dependency injection without depending on test fakes.

#### Concerns
- **MEDIUM**: *Per-request runner construction overhead* in [`engine/src/main.rs:1716-1718`](file:///D:/Repos/lancet/engine/src/main.rs#L1716-L1718). Constructing `WorkflowRunner` and cloning `WorkflowDependencies` on every incoming `query_rag` request must ensure shared state handles (e.g., `Arc<DatabaseManager>`, `Arc<Client>`) are cloned as cheap reference counts rather than triggering resource-heavy initialization per stream.
- **LOW**: *Trait signature migration ripple* in [`engine/src/workflow/ports.rs:44`](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L44). Changing `GraphQueryPort::query_graph` from returning `Result<String, NodeError>` to `Result<Vec<GraphFactBlock>, NodeError>` impacts existing mock implementations. Task 1 correctly updates production implementations, while 05-18 synchronizes test fixtures.

#### Suggestions
- Ensure `build_production_workflow` is a lightweight helper returning an instantiated pipeline where node structs are stateless or wrap `Arc` handles.
- Add an explicit assertion in `workflow_phase5_production_dependencies_are_real` verifying that all five adapter fields in `WorkflowDependencies` are `Some(...)` and reject `None` defaults in production mode.

#### Risk Assessment
**LOW**: The plan is well-scoped, addresses a known architectural debt item, and provides executable verification guards for live dependency wiring.

---

### Plan 05-09: Live Workflow Settings, Real-I/O Deadlines, and Stream-Owned Cancellation (Wave 8)

#### Summary
Plan 05-09 wires the seven workflow timeout configuration keys from `config/config.toml` and `config/config.verify.toml` into runtime execution, binds live node timer overrides, and implements stream-owned cancellation via `tokio_stream::wrappers::ReceiverStream` drop guards (`engine/src/main.rs:1704`). It provides an end-to-end live 7000ms deadline test while strictly separating live overlay verification from semantic paused-clock tests. The plan is well-contained and fulfills decisions D-16 and D-17.

#### Strengths
- **Exhaustive Configuration Keys**: Wires all seven required timeout settings (`reformulate_query_timeout_ms`, `extract_graph_context_timeout_ms`, `retrieve_hybrid_timeout_ms`, `assemble_prompt_timeout_ms`, `generate_answer_timeout_ms`, `node_wall_clock_timeout_ms`, `total_workflow_timeout_ms`) into `Settings` (`engine/src/main.rs:125-250`).
- **Stream-Owned Cancellation**: Implements D-16 by attaching a drop guard to the gRPC streaming response in `engine/src/main.rs:1704-1706`, ensuring client disconnections cancel in-flight TokIo tasks and abort downstream provider requests.
- **Dual-Environment Test Strategy**: Employs `config/config.verify.toml` with a 7000ms live timeout overlay for fast integration checks while preserving default 97000ms budgets in `config/config.toml`.

#### Concerns
- **MEDIUM**: *Orphaned task propagation on node timeout* in [`engine/src/workflow/runner.rs`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs). When a node wall-clock timeout expires, the runner must explicitly invoke `cancel.cancel()` on the node's local cancellation token before emitting `NodeFailed`, ensuring underlying Tokio tasks (such as LanceDB vector queries or HTTP chat completions) terminate immediately.
- **LOW**: *Environment variable naming parity* in [`config/config.toml`](file:///D:/Repos/lancet/config/config.toml). Ensure `LANCET_ENGINE__WORKFLOW__*` env var overrides properly map to nested structs under `config::Config` deserialization.

#### Suggestions
- Verify that `tokio::time::timeout` wrapper inside `runner.rs` drops the future immediately upon timeout, and that provider adapters observe the cancellation token at `.await` points.

#### Risk Assessment
**LOW**: Standard Tokio timeout and cancellation pattern with clear configuration boundaries.

---

### Plan 05-10: Reliable Typed Event Delivery, Terminal Idempotence, Sequence Integrity, and Full Snapshots (Wave 14)

#### Summary
Plan 05-10 guarantees event delivery reliability, strict sequence monotonicity, atomic terminal guard protection (preventing duplicate `WorkflowCompleted` events), and full 19-field `WorkflowContext` serialization in checkpoints. It eliminates race conditions between node failure, timeout, and cancellation, ensuring the event sink delivers an intact, unbroken stream to the client.

#### Strengths
- **Strict Sequence Integrity**: Uses `Arc<AtomicU64>` in `EventSequence` (`engine/src/workflow/events.rs:16`) to guarantee monotonically increasing event sequence ordinals across all emitted lifecycle, answer, and checkpoint events.
- **Atomic Terminal Invariant**: Implements an atomic compare-and-swap or mutex guard in `WorkflowRunner` / `WorkflowEventSink` ensuring exactly one terminal event (`WorkflowCompleted`) is dispatched per stream (D-02, D-05).
- **Full Context Snapshots**: Enforces serialization of all 19 fields of `WorkflowContext` (`engine/src/workflow/mod.rs:29-49`) into checkpoint payloads, preventing information loss during step persistence (D-23, D-28).

#### Concerns
- **MEDIUM**: *Channel buffer exhaustion during rapid checkpoint emission* in [`engine/src/workflow/runner.rs`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs) and [`engine/src/main.rs:1703`](file:///D:/Repos/lancet/engine/src/main.rs#L1703). The mpsc channel capacity is bounded to 100. Emitting large snapshots synchronously must not block the workflow execution thread if the gRPC transport lags.
- **LOW**: *Payload footprint of full snapshots* in [`engine/src/workflow/events.rs`](file:///D:/Repos/lancet/engine/src/workflow/events.rs). Full 19-field snapshots containing assembled prompts and evidence blocks may reach 50–100 KB; JSON serialization should use efficient buffer re-use.

#### Suggestions
- Add a property test verifying that interleaving cancellation tokens, node errors, and normal completion always produces exactly one terminal event with contiguous sequence numbers.

#### Risk Assessment
**LOW**: Core event plumbing with solid concurrency controls and exhaustive state serialization.

---

### Plan 05-11: Real Engine-to-Gateway SSE, Lossless Checkpoint Dispatch Under Backpressure, and PostgreSQL Persistence (Wave 17)

#### Summary
Plan 05-11 unifies cross-runtime integration between the Rust engine and Go gateway. It enhances `engine/src/bin/seed_rag_fixture.rs` to populate realistic knowledge graph entities/edges, rectifies context misuse in `gateway/checkpoint_sink.go:99`, and ensures lossless `CheckpointDispatcher` draining on shutdown (D-26). It also handles mid-stream gRPC transport failures cleanly in `gateway/main.go`.

#### Strengths
- **Comprehensive Fixture Seeding**: Expands `engine/src/bin/seed_rag_fixture.rs:100-185` to seed graph entities and edges alongside document chunks, allowing cross-runtime integration tests to exercise `ExtractGraphContext` without degradation.
- **Fixes Gateway Context Propagation**: Replaces hardcoded `context.Background()` in `gateway/checkpoint_sink.go:99` with proper parent request context timeout propagation.
- **Backpressure & Lossless Drain**: Replaces the fire-and-forget submission in `gateway/main.go:765-767` with proper handling of `DispatchPending` and graceful queue draining during gateway shutdown.

#### Concerns
- **HIGH**: *Claim/lease test database isolation review convention* in [`gateway/main_test.go`](file:///D:/Repos/lancet/gateway/main_test.go). As specified in `AGENTS.md`, any test interacting with PostgreSQL checkpoints must use an isolated per-test database/schema, and all external snapshot before/after count query assertions must use fatal checks (`t.Fatalf`) rather than non-fatal errors (`t.Errorf`) to prevent false-passing comparisons.
- **MEDIUM**: *Mid-stream SSE error encoding* in [`gateway/main.go:730-732`](file:///D:/Repos/lancet/gateway/main.go#L730-L732). If gRPC stream fails after HTTP 200 headers have been flushed, breaking the loop silently drops the client stream without formatting an in-band `node_failed` or terminal event.

#### Suggestions
- Explicitly implement per-test schema isolation in `gateway/main_test.go` database fixtures using UUID schema names (e.g. `CREATE SCHEMA test_<uuid>`).
- Ensure `writeWorkflowEventSSE` handles non-EOF stream errors by emitting an in-band error event frame before terminating the SSE stream.

#### Risk Assessment
**MEDIUM**: Multi-runtime boundary crossing (Rust gRPC streaming -> Go HTTP SSE -> PostgreSQL storage) with complex backpressure and database lifecycle constraints.

---

### Plan 05-12: Additive Historical-Summary Traceability Errata and Source Coverage Audit (Wave 7)

#### Summary
Plan 05-12 is a documentation and governance plan creating `.planning/phases/05-state-machine-workflow-events/05-01-07-ERRATA.md`. It reconciles discrepancies between earlier milestone summaries (plans 05-01 through 05-07) and the actual codebase state without modifying historical files or changing executable code.

#### Strengths
- **Immutability of Historical Milestones**: Leaves historical planning artifacts intact while capturing audited deviations in a dedicated errata record.
- **Cryptographic Auditability**: Computes and records frozen SHA-256 baseline hashes for all past plan files.
- **Zero Production Risk**: Modifies no source code or test targets; purely additive governance.

#### Concerns
- **LOW**: *Tooling reliance on errata*. Ensure future automated planning or validation scripts treat the errata document as informational context and not as an executable schema or code dependency.

#### Suggestions
- Include a summary table mapping each errata item directly to the corresponding gap-closure plan (05-08 through 05-21) that resolved it.

#### Risk Assessment
**LOW**: Safe, zero-risk documentation artifact.

---

### Plan 05-13: OpenRouter Preflight Classification, Successful-Only Capability Caching, and Bounded Generation Retry (Wave 9)

#### Summary
Plan 05-13 refactors the OpenRouter generator adapter in `engine/src/generation/openrouter.rs`. It separates capability discovery (`/models`) from generation chat completions (`/chat/completions`), introduces a dedicated 5000ms preflight deadline, implements a successful-only in-memory capability cache, and enforces a single bounded retry on transient transport errors (D-11, D-12, D-13, D-14).

#### Strengths
- **Successful-Only Caching**: Transient preflight failures (such as temporary DNS or connection drops) are not cached, allowing subsequent queries to re-attempt capability resolution.
- **Decoupled Preflight Budget**: Separates the 5000ms `/models` check from the 30000ms chat completion timeout, preventing preflight latency from eating into generation time.
- **Strict Error Classification**: Differentiates retryable transient errors (HTTP 5xx, timeouts) from non-retryable fatal errors (`SupportedParameters`, `SchemaValidation`, `Authentication`).

#### Concerns
- **MEDIUM**: *Cancellation token propagation in OpenRouter generator* in [`engine/src/generation/openrouter.rs:383-391`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L383-L391). `execute_one_call` currently instantiates a new local `CancellationToken::new()` rather than passing through the cancellation token from `GenerationRequest`. The refactored generator must forward the request-level token to ensure cancelled queries abort in-flight HTTP requests immediately.
- **LOW**: *Concurrent preflight deduplication* in [`engine/src/generation/openrouter.rs`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs). Multiple concurrent requests hitting an uncached capability should avoid redundant parallel `/models` calls through a synchronization primitive (e.g. `tokio::sync::OnceCell` or read-write lock).

#### Suggestions
- Use `tokio::sync::RwLock<Option<bool>>` or `tokio::sync::OnceCell` for thread-safe capability caching.
- Pass `&request.cancel` directly into `reqwest` calls using Tokio select loops to guarantee responsive request cancellation.

#### Risk Assessment
**LOW**: Solves acute capability check flakiness and establishes deterministic generation retry semantics.

---

### Plan 05-14: Typed NodeKind Dispatch and Early Variant Admission (Wave 10)

#### Summary
Plan 05-14 replaces string-based node identification and dispatch with an exhaustive, closed `NodeKind` enum (`ReformulateQuery`, `ExtractGraphContext`, `RetrieveHybrid`, `AssemblePrompt`, `GenerateAnswer`). It enforces early rejection of excessive reformulation variants (>8) at the `ReformulateQueryNode` boundary before downstream retrieval adapters are invoked.

#### Strengths
- **Type-Safe Dispatch**: Replaces string comparisons with exhaustive pattern matching on `NodeKind` across runner timeouts, lifecycle events, and checkpoint labels.
- **Early DoS Mitigation (T-05-14-02)**: Validates and rejects excess reformulation variants (e.g., 9 variants) immediately at the `ReformulateQueryNode` boundary, preventing downstream fan-out to dense/BM25 retrieval.
- **Clean Retryability Plumbing**: Propagates typed `NodeError::retryable` flags to `NodeFailed` events without inventing redundant retry event types (D-15).

#### Concerns
- **LOW**: *Preservation of zero-evidence skip semantics* in [`engine/src/workflow/runner.rs`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs). Exhaustive matching on `NodeKind` must ensure `RetrieveHybridNode`'s zero-evidence bypass (D-03) jumps directly to completion without invoking prompt assembly or generation.

#### Suggestions
- Add a compiler assertion / lint ensuring `NodeKind` has no `#[non_exhaustive]` attribute, guaranteeing that any newly added node causes a compile-time exhaustiveness error in `WorkflowRunner`.

#### Risk Assessment
**LOW**: Clean, robust type refactoring that eliminates stringly-typed dispatch risks.

---

### Plan 05-15: Asynchronous Prompt API Documentation and Production Test-Double Hygiene (Wave 12)

#### Summary
Plan 05-15 restores comprehensive rustdoc documentation for asynchronous prompt helpers in `engine/src/prompt.rs:214-231`, defines an explicit `graph_weight` contract (`0.0` omits graph facts, positive values include them), restricts synchronous prompt helpers to `#[cfg(test)] pub(crate)`, and places all `Fake*` workflow port test doubles behind `#[cfg(test)]` guards.

#### Strengths
- **Eliminates Test Doubles from Production**: Encloses `FakeQueryReformulator`, `FakeGraphQueryPort`, `FakeDenseRetrievalPort`, `FakeBm25RetrievalPort`, `FakeReranker`, and `FakeGenerator` in `engine/src/workflow/ports.rs` and `engine/src/generation/mod.rs` under `#[cfg(test)]`.
- **Prevents Blocking Calls**: Removes public synchronous prompt wrappers from production visibility, preventing runtime thread-pool starvation.
- **Explicit Graph Weight Semantics**: Clarifies and tests `graph_weight` behavior without perturbing retrieval evidence ranking.

#### Concerns
- **LOW**: *Module visibility across library test target* in [`engine/src/workflow/ports.rs`](file:///D:/Repos/lancet/engine/src/workflow/ports.rs). Gating fakes behind `#[cfg(test)]` requires that `engine/src/lib.rs` exports these types to `engine/src/tests/workflow_phase5.rs` under test compilation. Handled in coordination with 05-18.

#### Suggestions
- Add a static source assertion checking that `Fake*` symbols do not appear in `cargo check --bin engine` symbol tables.

#### Risk Assessment
**LOW**: Standard Rust conditional compilation and documentation cleanup.

---

### Plan 05-16: Machine-Readable Graph Notices, Retrieval Provenance, and Lock-Free BM25 Snapshotting (Wave 13)

#### Summary
Plan 05-16 addresses critical concurrency and diagnostic requirements: it introduces exact machine-readable graph notice codes (`GRAPH_TIMEOUT`, `GRAPH_DEGRADED`) in `engine/src/workflow/nodes/graph_context.rs`, non-destructive `WorkflowContext::merge_notices` accumulation, multi-variant `RetrievalSnapshot` provenance (`variant_count`, `variant_identities`), and replaces `RwLock<Bm25Index>` with `RwLock<Arc<Bm25Index>>` snapshotting to prevent holding read locks across async `.await` boundaries (`engine/src/main.rs:1311-1321`).

#### Strengths
- **Eliminates Ingestion Concurrency Bottleneck**: By snapshotting `Arc<Bm25Index>` before async retrieval and immediately dropping the `RwLock` read guard, background document ingestion writes can proceed without being wedged by in-flight searches.
- **Non-Destructive Diagnostic Accumulation**: `WorkflowContext::merge_notices` ensures that earlier graph degradation notices survive subsequent node completions or terminal failures (D-28).
- **Multi-Variant Provenance**: Populates `RetrievalSnapshot` with exact variant counts and ordered variant strings without introducing out-of-scope metadata (D-30).

#### Concerns
- **MEDIUM**: *Coordinated BM25 fixture migration* across [`engine/src/main.rs`](file:///D:/Repos/lancet/engine/src/main.rs) and [`engine/src/tests.rs`](file:///D:/Repos/lancet/engine/src/tests.rs). Changing the index ownership type to `RwLock<Arc<Bm25Index>>` affects 19 construction sites (1 production + 18 test fixtures). The plan correctly delegates test-fixture updates to 05-18 Task 2, but strict compilation gating is required to avoid breaking intermediate builds.
- **LOW**: *Memory overhead of index snapshots*. Cloning `Arc<Bm25Index>` is an $O(1)$ atomic increment; ensure no deep-copying of token inverted index vectors occurs during snapshotting.

#### Suggestions
- Include a specific test where a writer acquires the BM25 write lock while a simulated dense/BM25 retrieval future is pending, proving non-blocking progress.

#### Risk Assessment
**MEDIUM**: Core index concurrency and type migration spanning multiple production and test files.

---

### Plan 05-17: Protobuf Wire Contract Extensions and Synchronized Binding Generation (Wave 11)

#### Summary
Plan 05-17 manages the protobuf schema evolution in `proto/lancet/v1/lancet.proto`. It adds field tags 10 (`variant_count`) and 11 (`variant_identities`) to `RetrievalSnapshot`, and field tag 6 (`notices`) to `WorkflowCompletedEvent`. It configures `buf.gen.yaml` with `clean: false` to preserve hand-written `engine/src/pb/mod.rs`, runs `buf generate`, checks in synchronized Rust/Go bindings, and updates Rust construction sites.

#### Strengths
- **Strict Backward Compatibility**: Preserves existing field numbers (tags 1–9 on `RetrievalSnapshot`, tags 1–5 on `WorkflowCompletedEvent`), adding only new fields at unallocated tags.
- **Protects Hand-Written Module Glue**: Sets `clean: false` in `buf.gen.yaml` and enforces pre/post byte-for-byte validation of `engine/src/pb/mod.rs`.
- **Synchronized Generated Bindings**: Commits both Rust prost/tonic and Go protobuf bindings simultaneously to eliminate remote plugin build dependencies.
- **Exhaustive Construction Site Ledger**: Updates non-generated Rust literals in `retrieve.rs`, `events.rs`, and `main.rs` with default values so compilation remains green immediately.

#### Concerns
- **MEDIUM**: *Uncleaned stale generated artifacts with `clean: false`* in [`buf.gen.yaml`](file:///D:/Repos/lancet/buf.gen.yaml). Disabling Buf cleanup could leave orphaned `.rs` or `.go` files if schemas are restructured. Task 1 mitigates this with an exact post-generation file allowlist check.
- **LOW**: *Field type consistency*. Ensure `variant_count` (uint32) and `variant_identities` (repeated string) map seamlessly to `usize` / `Vec<String>` in Rust and `uint32` / `[]string` in Go.

#### Suggestions
- Ensure `buf lint` runs as part of standard CI to catch schema style or breaking changes early.

#### Risk Assessment
**LOW**: Safe additive schema evolution backed by strict compile and round-trip wire tests.

---

### Plan 05-18: Library vs. Binary Test Target Split and BM25 Fixture Migration (Wave 11)

#### Summary
Plan 05-18 resolves the Cargo test target compilation split. It registers generic fake-port workflow tests in `engine/src/lib.rs` under `#[cfg(test)]`, retains binary-owned real-service tests in `engine/src/tests/workflow_phase5_production.rs`, and migrates all 18 BM25 test fixture constructions in `engine/src/tests.rs` to `Arc<RwLock<Arc<Bm25Index>>>`.

#### Strengths
- **Resolves Multi-Target Compilation Mismatch**: Allows `engine/src/tests/workflow_phase5.rs` to access `#[cfg(test)]` fake ports in library scope while `engine/src/tests/workflow_phase5_production.rs` verifies binary-scoped real production wiring.
- **Atomic Fixture Migration**: Updates all 18 BM25 fixture instantiation sites in `engine/src/tests.rs`, providing the necessary test-side support for 05-16's production BM25 lock-free changes.
- **Compile Probe Verification**: Adds `workflow_phase5_library_target_fake_ports_compile` to guarantee test doubles remain fully functional in library scope.

#### Concerns
- **MEDIUM**: *Target synchronization during handoffs* between [`engine/src/lib.rs`](file:///D:/Repos/lancet/engine/src/lib.rs) and [`engine/src/tests.rs`](file:///D:/Repos/lancet/engine/src/tests.rs). `cargo check --bin engine` validates non-test binary code; full binary test target verification is deferred to 05-16 Task 2.
- **LOW**: *Duplicate test registration risk*. Strict checks in Task 1 verify that `workflow_phase5` is registered exactly once in `lib.rs` and absent from `tests.rs`.

#### Suggestions
- Include a verification step in CI running both `cargo test --lib` and `cargo test --bin engine` to prevent regressions in either target.

#### Risk Assessment
**LOW**: Clean structural separation of test scopes.

---

### Plan 05-19: Failure-Terminal Notice Preservation and In-Band SSE Propagation (Wave 15)

#### Summary
Plan 05-19 consumes the protobuf `WorkflowCompletedEvent.notices` field (tag 6) introduced in 05-17. It ensures that failed workflows emit accumulated diagnostic notices (e.g., `GRAPH_TIMEOUT`, `GRAPH_DEGRADED`) in the terminal event, propagates them through Go gateway SSE serialization (`gateway/main.go:771-800`), and guarantees that failed streams emit no `final_response`, `answer_chunk`, or `final_answer` frames (D-05, D-13, D-18, D-19).

#### Strengths
- **Diagnostic Preservation on Failure**: Delivers full context notices to the client even when generation or prompt assembly encounters a hard error.
- **Strict Answer Exclusion**: Verifies that failed terminals emit HTTP 200 SSE streams containing `node_failed` and failed `workflow_completed` frames with `success: false` while strictly omitting answer events.
- **Cross-Runtime Consistency**: Provides matching test coverage in Rust (`workflow_phase5_failure_terminal_preserves_notices_without_answer_events`) and Go (`TestRAGQueryFailureTerminalNoticesSSE`).

#### Concerns
- **LOW**: *JSON serialization schema alignment* in [`gateway/main.go`](file:///D:/Repos/lancet/gateway/main.go). Ensure `noticeDTO` formatting in gateway SSE matches frontend JSON expectations.

#### Suggestions
- Verify that notice severities (`INFO`, `WARNING`, `ERROR`) serialize consistently as integers or uppercase strings across all gateway endpoints.

#### Risk Assessment
**LOW**: Targeted, reliable diagnostic delivery mechanism.

---

### Plan 05-20: Capability Bootstrap Seam, Node Budget Arithmetic, and Worst-Case Paused-Clock Timing (Wave 16)

#### Summary
Plan 05-20 resolves the timing and budget derivation conflict between capability preflight and generation retries. It introduces an asynchronous `prepare` hook on `Generator` and `Node` (`engine/src/workflow/node.rs`), executing OpenRouter capability preflight (5000ms) before `GenerateAnswerNode`'s 65000ms node timer begins. It verifies the complete worst-case budget ($97\text{s pre-preflight} + 5\text{s preflight} = 102\text{s total}$) using Tokio paused-clock tests and bounds event receiver draining in test fixtures.

#### Strengths
- **Eliminates Timer Contention**: Moves capability preflight outside the 65000ms node budget, ensuring two full 30000ms generation attempts plus 5000ms inter-attempt slack remain intact (D-17).
- **Deterministic Paused-Clock Testing**: Uses `tokio::time::pause()` and clock advancement in `workflow_phase5_generation_preflight_worst_case_budget` to prove worst-case timing in milliseconds without sleeping for 65+ real seconds.
- **Exact Boundary Assertions**: Tests 4999ms (reformulation) and 9999ms (retrieval) boundaries to confirm pre-deadline operations do not falsely trigger timeouts.
- **Liveness-Bounded Test Cleanup**: Wraps receiver drain in `workflow_phase5_happy_path` with a 5-second timeout and `AbortOnDrop` task cleanup.

#### Concerns
- **LOW**: *Default trait implementation safety* in [`engine/src/generation/mod.rs`](file:///D:/Repos/lancet/engine/src/generation/mod.rs) and [`engine/src/workflow/node.rs`](file:///D:/Repos/lancet/engine/src/workflow/node.rs). Default `prepare` methods must return `Ok(())` so non-OpenRouter generators and the other four nodes require no changes.

#### Suggestions
- Ensure `GenerateAnswerNode` is the only workflow node overriding `Node::prepare`, delegating directly to `generator.prepare()`.

#### Risk Assessment
**LOW**: Robust architectural separation of preflight bootstrap from timed execution.

---

### Plan 05-21: Type-Safe Fusion Provenance, Dead Serde Cleanup, and Wire Compatibility (Wave 14)

#### Summary
Plan 05-21 cleans up reciprocal rank fusion provenance in `engine/src/retrieval/fusion.rs`. It replaces string-based provenance tags (`"vector"`, `"bm25"`) with a typed `VariantProvenanceSource` enum, updates candidate filtering in `fusion.rs:145,153`, and removes the ineffective `#[serde(default)]` annotation on `FusedCandidate.variant_provenance` (`fusion.rs:33`).

#### Strengths
- **Type-Safe Filtering**: Replaces string comparisons with enum variant matching in fusion candidate selection.
- **Dead Annotation Removal**: Deletes `#[serde(default)]` on serialize-only structs.
- **Wire Compatibility**: Uses custom serde serialization to ensure enum variants continue emitting lowercase `"vector"` and `"bm25"` in API responses.

#### Concerns
- **LOW**: *Minimal surface area*. Confined to two files (`fusion.rs` and `tests.rs`) with no external runtime side effects.

#### Suggestions
- Maintain unit tests verifying both enum equality and JSON serialization formatting.

#### Risk Assessment
**LOW**: Low-risk, high-quality code cleanup.

---

## 2. Phase-Level Synthesis & Cross-Plan Review

### Dependency Graph & Wave Sequencing
The 14 plans form a coherent, acyclic directed dependency graph organized into 11 execution waves (Waves 7 through 17):

```
Wave 07: [05-08 Production Wiring]  [05-12 Traceability Errata]
               │
Wave 08: [05-09 Live Settings & Cancellation]
               │
Wave 09: [05-13 OpenRouter Preflight & Retry]
               │
Wave 10: [05-14 Typed NodeKind Dispatch]
               │
Wave 11: [05-17 Protobuf Schemas] ──► [05-18 Test Target Split & BM25 Fixtures]
               │                                      │
Wave 12:       │                             [05-15 Prompt Docs & Fakes]
               │                                      │
Wave 13: [05-16 Graph Notices & Lock-Free BM25] ◄─────┘
               │
Wave 14: [05-10 Reliable Events & Full Snapshots] ──► [05-21 Fusion Provenance]
               │
Wave 15: [05-19 Terminal Notices & SSE]
               │
Wave 16: [05-20 Capability Bootstrap & Budget Timing]
               │
Wave 17: [05-11 End-to-End SSE & Checkpoint Persistence]
```

All inter-plan dependencies are properly ordered:
1. Schema updates (`05-17`) and fixture migrations (`05-18`) precede the production BM25 lock-free changes (`05-16`).
2. Typed `NodeKind` dispatch (`05-14`) and capability retry classification (`05-13`) precede bootstrap timing (`05-20`).
3. Event sink sequence integrity (`05-10`) precedes failure notice wiring (`05-19`) and full cross-runtime persistence (`05-11`).

### Invariant & Decision Coverage Matrix

| Decision / Invariant | Covered By Plans | Status & Enforcement Mechanism |
|---|---|---|
| **D-01, D-02** (Single answer chunk + FinalAnswer) | `05-08`, `05-10`, `05-14`, `05-19` | Enforced in runner & event sink; failure paths emit zero answer chunks. |
| **D-03** (Zero-evidence fast completion) | `05-08`, `05-14`, `05-16` | RetrieveHybrid returns empty candidates -> jumps directly to Complete. |
| **D-04, D-05** (Pre-stream vs in-band errors) | `05-09`, `05-10`, `05-11`, `05-19` | gRPC pre-stream validation errors return Status; in-band errors emit NodeFailed. |
| **D-06** (ExtractGraphContext before RetrieveHybrid) | `05-08`, `05-14`, `05-16` | Fixed five-node execution order in `WorkflowRunner`. |
| **D-07, D-08** (Multi-variant BM25, variant-0 dense) | `05-14`, `05-16`, `05-17`, `05-21` | Fusion takes all BM25 variants and variant 0 embeddings with provenance. |
| **D-09** (Graph failure degradation) | `05-08`, `05-16`, `05-19` | Graph timeouts/errors emit notices and continue with empty graph context. |
| **D-11, D-12, D-13, D-14, D-15** (Single retry, byte-identical payload, no retry event) | `05-13`, `05-14`, `05-20` | OpenRouter generator retries once on transient errors; runner emits no retrying event. |
| **D-16, D-17** (Stream cancellation, distinct timeouts) | `05-09`, `05-13`, `05-20` | Drop guard cancels token; 5s preflight + 2x30s attempts + 5s slack = 65s node budget. |
| **D-18, D-19** (Streaming gRPC to SSE) | `05-10`, `05-11`, `05-19` | Go gateway forwards gRPC events to SSE frames with HTTP 200 on in-band failures. |
| **D-20, D-22** (Lifecycle granularity, typed errors) | `05-10`, `05-14`, `05-16` | NodeStarted, NodeCompleted, NodeFailed carry typed NodeErrorKind and notices. |
| **D-23, D-26, D-27, D-28** (PostgreSQL checkpoints, full snapshots) | `05-10`, `05-11`, `05-16`, `05-19` | Go gateway drains checkpoints to DB; snapshots contain 19 full fields. |
| **D-30, D-31** (No out-of-scope metadata / tracing spans) | `05-14`, `05-16`, `05-17`, `05-19` | Plans strictly exclude extraneous vector/bm25 count fields and extra tracing spans. |

### Threat Model & Trust Boundaries
- **Tampering (Protobuf Tags)**: Additive tags (10, 11 on `RetrievalSnapshot`; 6 on `WorkflowCompletedEvent`) protect existing wire serialization (`05-17`).
- **Denial of Service (Fan-Out Amplification)**: Early variant validation rejects $>8$ reformulation queries at the boundary before calling downstream retrieval services (`05-14`).
- **Denial of Service (Lock Contention across Await)**: Snapshotting `Arc<Bm25Index>` releases the read lock before async retrieval, preventing blocked ingestion writes (`05-16`).
- **Repudiation (Lost Diagnostic History)**: Non-destructive notice merging ensures graph timeout/degradation diagnostics survive terminal failures (`05-16`, `05-19`).
- **Denial of Service (Timer Contention)**: Preflight bootstrap isolation prevents capability checks from consuming the generation retry window (`05-20`).

### Test Architecture & Compilation Boundaries
The plans cleanly separate test execution across two Cargo targets:
1. **Library Target (`cargo test --lib`)**: Executes unit tests and fake-port matrices (`engine/src/tests/workflow_phase5.rs`, `engine/src/prompt.rs`, `engine/src/retrieval/tests.rs`, `engine/src/generation/tests.rs`) where `#[cfg(test)]` fakes reside (`05-15`, `05-18`).
2. **Binary Target (`cargo test --bin engine`)**: Executes production-wiring integration tests (`engine/src/tests/workflow_phase5_production.rs`, `engine/src/tests.rs`) validating live service adapters, lock-free BM25 behavior, and settings overlays (`05-08`, `05-09`, `05-16`, `05-20`).
3. **Gateway Target (`go test ./...`)**: Executes Go SSE forwarding, failure terminal JSON parsing, and PostgreSQL checkpoint persistence tests (`05-11`, `05-19`).

---

## 3. Review Verdict & Recommendations

### Overall Assessment
The 14 gap-closure plans (`05-08` through `05-21`) provide a comprehensive, rigorous, and logically consistent roadmap for completing Phase 05. The plans directly address all identified review findings, eliminate architectural bypasses, establish sound concurrency primitives for BM25 search and ingestion, enforce strict wire compatibility, and ensure full diagnostic visibility.

### Critical Execution Recommendations
1. **Enforce Claim/Lease Test Schema Isolation**: Ensure that `gateway/main_test.go` in Plan 05-11 adheres strictly to the `AGENTS.md` convention by executing all checkpoint queries within isolated per-test database schemas and failing fatally on count assertions.
2. **Plumb Cancellation Tokens to HTTP Requests**: In Plan 05-13 and 05-20, ensure `OpenRouterGenerator` passes the request's `CancellationToken` into Tokio select loops to abort in-flight network requests immediately when clients disconnect.
3. **Follow Target Compilation Gates**: Maintain the strict compilation handoff sequence between 05-18 (fixture migration) and 05-16 (production BM25 field) using `cargo test --bin engine --no-run` before running exact binary test filters.


---

## Claude Review

# Cross-AI Review — Phase 5 Gap-Closure Plans (05-08 through 05-21)

**Repo:** `D:\Repos\lancet` @ `7b2f5b0` · **Scope:** 14 additive gap-closure plans · **Method:** every structural claim below was checked against the files the plans cite.

---

## Baseline: the diagnosis is accurate

Before the per-plan analysis, the shared premise checks out against source. This is the strongest thing about the set — these plans are not reviewing themselves, they are reacting to a real, verified gap:

| Claim made across the plans | Verified at |
|---|---|
| Production `query_rag` registers one node and runs the old inline path | `engine/src/main.rs:1716-1719` (`WorkflowRunner::new()` + a single `ReformulateQueryNode`), `:1742` calling `execute_inline_query_rag_remainder` (defined `:1234`) |
| Production dependencies are all-`None` | `engine/src/workflow/mod.rs:122-135` |
| A no-generator branch fabricates an answer | `engine/src/workflow/mod.rs:210-218` — `ctx.answer = format!("Answer for {}", ...)` then `answer_chunk` + success |
| `GraphQueryPort` is string-typed | `engine/src/workflow/ports.rs:39-45` |
| Workflow timeout config is dead | keys exist at `config/config.toml:10-17`; `with_timeouts` appears **only** in tests (`engine/src/tests.rs:7580`, `engine/src/tests/workflow_phase5.rs:331,397`) |
| Checkpoint snapshots are partial | `engine/src/workflow/events.rs:106-114` serializes 7 of 18 `WorkflowContext` fields |
| Event sends are unchecked | `engine/src/workflow/runner.rs:47` — `let _ = self.tx.try_send(...)` |
| Sequence ordinals double-increment | `runner.rs:145-146` — `next_sequence_ordinal()` then `send_event` allocates again; the checkpoint's outer ordinal is always inner+1 |
| BM25 holds an `RwLock` guard across `.await` | `main.rs:1311-1320` |
| Preflight runs inside every provider attempt, uncached | `openrouter.rs:375-376` inside `execute_one_call`, itself wrapped by `timeout(self.config.timeout /* 30s */, ...)` at `:629` |
| Fusion provenance is stringly + dead serde default | `retrieval/fusion.rs:18`, `:33` (`#[serde(default)]` on a `Serialize`-only struct), `:145`, `:153` |
| Public sync prompt helpers exist | `prompt.rs:234`, `:255` |
| Proto tags 10/11 and 6 are free | `proto/lancet/v1/lancet.proto:91-101` (snapshot ends at 9), `:184-190` (WC ends at 5) |
| Checkpoints are dropped past 5 in flight | `gateway/checkpoint_sink.go:168-188`; result discarded at `gateway/main.go:766` |
| Two SUMMARY requirement lists are wrong | `05-02-SUMMARY.md` claims `[ORCH-03, RAG-01, RAG-02]` vs PLAN `[ORCH-01, ORCH-03, ORCH-05]`; `05-03-SUMMARY.md` claims `[GEN-01, GEN-02, GEN-03, EVENT-03]` vs PLAN `[ORCH-01, ORCH-02, ORCH-03]`. `RAG-02` is a Phase 03 requirement (`.planning/REQUIREMENTS.md:49`) |

One claim I expected to fail and which **holds**: 05-09's "the `/rag/query` route remains outside the gateway's blanket 60-second timeout" — `gateway/main.go:465-474` puts `/rag/query` in a separate `r.Group` that omits `middleware.Timeout(60*time.Second)`. Important, because 05-20 derives a 102-second worst-case budget that would otherwise be unreachable.

---

## 05-08 — Production five-node wiring, real adapters, WorkflowContext population

**Summary.** The keystone of the set and correctly placed at Wave 7. Its diagnosis is exact, its file inventory (10 files) is genuinely atomic, and its acceptance criteria target reachability rather than existence. The weakness is not the plan's intent but its enforcement: the gates that decide whether it landed are almost entirely PowerShell substring/count greps over extracted regions of `main.rs`, and one of its three compile gates is vacuous today.

**Strengths**
- The "reachability" framing is right. Asserting `query_rag` invokes a *named* builder (`build_production_workflow`) and that the extracted region contains no inline-remainder call is a much better contract than "five node types exist somewhere".
- Task 2 correctly assigns the `Answer for {}` fabrication (`workflow/mod.rs:210-218`) and names its exact three callers — `engine/src/tests.rs:7134`, `:7210`, `:7323` — all three verified present and exact.
- The `GraphQueryPort` string→`Vec<GraphFactBlock>` migration is the right fix at the right layer: `assemble_prompt.rs:92` currently passes a literal `&[]` for graph facts, and `generate.rs:53` builds `GenerationRequest` without them, so today graph context provably cannot reach the provider through the node path.
- `<scope_rationale>` explicitly cedes the BM25 and library-registration work to 05-18 rather than silently expanding — good discipline for a 10-file plan.

**Concerns**
- **HIGH — the `cargo test --lib --no-run` gate is vacuous.** `engine/src/lib.rs` is 13 lines with no `mod tests`; `mod tests` exists only at `engine/src/main.rs:3173-3174` under `#[cfg(test)]`, and `engine/src/tests.rs:11` re-exports `workflow_phase5`. So Task 3's third gate ("library fake-port and GraphQueryPort call sites do not compile") compiles **zero** Phase 5 tests at Wave 7 and remains vacuous until 05-18 lands at Wave 11. The acceptance criterion "all library fake-port fixtures compile after the string-to-fact migration" is unprovable in this plan's own wave.
- **MEDIUM — "not backed by a Fake* type" is not a runtime-checkable property.** Acceptance says "the dedicated dependency test fails if any slot is None or backed by a `Fake*` type," but the deps are `Option<Arc<dyn Trait>>`; without `Any` downcasting there is no way for a test to observe the concrete type. The verify block delivers this as a source grep (`if ($builder -match 'Fake(?:Query|Graph|...)')`), which is text, not behavior. The criterion promises more than the gate can deliver.
- **MEDIUM — region-extraction guards are brittle.** `(?s)fn build_production_workflow\b.*?(?=\n\s*(?:pub\s+)?(?:async\s+)?fn\b|\z)` terminates at the *first* subsequent `fn` at any indentation. A nested helper `fn`, or a builder placed as the last method in an `impl`, silently changes what the guard sees. The `Some\s*\(` ≥ 7 count and `add_node` == 5 count are then computed over that region — a doc comment listing the seven slots satisfies the first; a commented-out `add_node` satisfies the second.
- **LOW — D-06 ordering is proven by `IndexOf` of type names in builder text**, so a `use` statement or comment naming `RetrieveHybridNode` before `ExtractGraphContextNode` fails the guard for a correct implementation, and vice versa. Only the lifecycle-event assertion in `workflow_phase5_production_reachability` genuinely proves order.

**Suggestions**
- Replace the "no Fake" acceptance with something observable: have the production builder return a small `DependencyProvenance` struct (or have each adapter expose a `&'static str` id) and assert on that. It is checkable, revertible, and survives refactors that greps do not.
- Prove D-06 order from the emitted `NodeStarted` sequence only, and demote the `IndexOf` check to advisory — the event sequence is the contract, the source order is an implementation detail.
- Drop the `--lib --no-run` gate from this plan (it cannot mean anything at Wave 7) and state explicitly that library-target proof arrives at 05-18. As written it reads as coverage that does not exist.

---

## 05-09 — Live workflow settings, real-I/O deadlines, stream-owned cancellation

**Summary.** Closes the single most under-appreciated gap: seven timeout keys are shipped, documented, echoed by config tests, and **never applied**. The plan's insistence on separating "fast deterministic semantic evidence" from "live wall-clock overlay evidence" is unusually mature and directly answers the way the current tests hide the bug.

**Strengths**
- The gap is real and the current tests actively mask it: `engine/src/tests.rs:7580` and `workflow_phase5.rs:331,397` call `.with_timeouts(5000, 15000, 10000, 2000, 65000)` — the same literals the config file carries — so every existing timing test passes whether or not config is read. The plan names this failure mode.
- The `config.verify.toml` design (7000 ms node deadline vs 30 s provider attempt) is the right shape for a live proof: it makes the node timer, not the provider timer, the observable cause.
- The explicit inequality assertions (`10000 + 4000 < 15000`, `65000 >= 2*30000 + 5000`, `30s > 7000ms`) turn D-17's amended arithmetic into executable invariants rather than prose.
- Stream-owned cancellation is correctly identified as the missing half: `main.rs:1707-1749` creates a `CancellationToken` that nothing ever cancels, and `runner.rs:47` swallows the send failure, so today a disconnected client's query runs to completion — including paid provider calls.

**Concerns**
- **MEDIUM — the `config.verify.toml` edit has blast radius.** The overlay currently sets `generation_timeout_secs = 1` (`config/config.verify.toml:5`); this plan requires `= 30`. Any existing verification path relying on a 1-second provider timeout (the `verify-live-evidence.sh` / `config.verify` harness) changes behavior or wall-clock cost. No acceptance criterion enumerates the other consumers of that overlay.
- **MEDIUM — cancellation acceptance is split across plans in a way that leaves a hole.** 05-09 proves in-process teardown "binary-owned"; the real HTTP disconnect proof is explicitly handed to 05-11 at Wave 17 — eight waves later. Between Waves 8 and 16 the tree can claim ORCH-03 cancellation with no end-to-end evidence.
- **LOW — "unknown workflow fields are rejected"** is asserted but the plan does not say where the deny-unknown behavior lands (serde `deny_unknown_fields` on a new struct vs. the existing key-list validation in `tests.rs:37,120`). Two very different implementations satisfy the wording.

**Suggestions**
- Add an acceptance criterion enumerating every consumer of `config.verify.toml` and asserting each still passes after `generation_timeout_secs: 1 → 30`; state the expected runtime delta.
- Assert that the production runner's effective timeouts are *observable* (e.g. logged once at construction, or exposed via a getter asserted in the production test) so a future `WorkflowRunner::new()` regression fails loudly instead of silently reverting to the hardcoded defaults at `runner.rs:76-80`, which happen to equal the config values.

---

## 05-10 — Reliable event delivery, terminal idempotence, sequence integrity, full snapshots

**Summary.** Four genuine defects, all verified, bundled coherently at the event/snapshot boundary with clean ownership fences against 05-14 (dispatch) and 05-16 (notice semantics). The one place it overreaches is the snapshot payload.

**Strengths**
- Every named defect is real: unchecked `try_send` (`runner.rs:47`), ordinal double-allocation (`runner.rs:145-146`, `:284`), 7-of-18-field snapshots (`events.rs:106-114`), and notice overwrites (`main.rs` assigns `ctx.notices = proto_notices` wholesale in the inline path, destroying any `GRAPH_TIMEOUT` notice pushed by `graph_context.rs:120-125`).
- Distinguishing *client-visible* delivery (Sent/Closed) from *checkpoint* delivery (Sent/owned-Pending) is exactly right given D-27's fire-and-forget rule — it lets checkpoints degrade without letting answer events degrade.
- "The query response DTO contains no checkpoint-only snapshot JSON" is a good negative assertion; `gateway/main.go:763-767` already returns early on checkpoints, and this locks that in.

**Concerns**
- **MEDIUM — mandating the full 2048-float embedding in every checkpoint is a self-inflicted cost D-28 does not require.** D-28 enumerates "original_query, reformulated_query variants, vector_results, bm25_results, graph_context, assembled_prompt, answer" — `query_embedding` is not in that list. At ~20–40 KB of JSON per snapshot and 6–7 snapshots per query, this pushes ~200 KB per query through the same `mpsc::channel(100)` used for answer events and into a dispatcher whose capacity is 1 + 4 (`checkpoint_sink.go:159-161`). The plan accepts the storage cost (D-24) but does not analyze the *transport* cost, which is where 05-11's drop problem lives.
- **MEDIUM — "terminal idempotence" is latent, not shipped.** `emit_terminal_once` (`runner.rs:274`) has no guard, but today there is exactly one call site per path (`:205`, `:270`). Making it genuinely idempotent is correct hardening; presenting it as a current defect slightly overstates. Worth stating accurately so the summary does not repeat the overclaiming pattern 05-12 exists to correct.
- **LOW — the zero-evidence short-circuit is not tightened here.** `runner.rs:173-178` breaks before prompt/generation when `NO_EVIDENCE` **or** `final_candidates.is_empty() && evidence_blocks.is_empty()`. The disjunction means a *mis-registered pipeline* (RetrieveHybrid dropped) also short-circuits and terminates with `success = true` and an empty answer. D-03 is satisfied; a wiring regression is masked.

**Suggestions**
- Store a digest of `query_embedding` (dimension + hash + first/last few values) rather than 2048 floats; it still satisfies D-28's enumerated fields, keeps the snapshot debuggable, and removes the dominant term from both channel and Postgres pressure. If the full vector is genuinely wanted, gate it behind a config key defaulting to off.
- Make the short-circuit require an explicit `NO_EVIDENCE` notice set by `RetrieveHybrid` (`retrieve.rs:158-163` already sets it) and drop the derived `is_empty()` disjunction, so an unregistered retrieval node fails rather than "succeeds empty".

---

## 05-11 — Real engine-to-gateway SSE and lossless checkpoint dispatch

**Summary.** The end-to-end proof plan, and the most overloaded plan in the set: six `depends_on`, Wave 17, and a Task 1 carrying ten acceptance criteria that range from SSE error framing to exact fixture UUIDs. The technical content is sound; the packaging concentrates too much terminal risk in one unit.

**Strengths**
- The dispatcher defect is verified and precisely described: `Submit` returns `DispatchPending` past 1 + 4 in flight (`checkpoint_sink.go:179-187`) and the caller drops it (`gateway/main.go:766` ignores the return). "No result is discarded" is the correct contract.
- `STREAM_EOF_WITHOUT_TERMINAL` and `GRPC_RECV_ERROR` are a genuine improvement — today `gateway/main.go:724-732` `break`s on *any* receive error and closes the stream cleanly, so a mid-stream engine crash is indistinguishable from success to the client.
- Per-test isolated Postgres schemas with `t.Fatalf` on every snapshot/count error closes the "empty comparison passes vacuously" failure mode, which is a real hazard in the existing gateway suite.
- Building the graph fixture is genuinely necessary: `engine/src/bin/seed_rag_fixture.rs` seeds chunks and edges but no entity rows with 2048-dim name vectors, so no existing test can prove graph facts reach the provider.

**Concerns**
- **MEDIUM — the only end-to-end proof that graph facts reach the provider lands in the final wave.** 05-08 (Wave 7) asserts typed graph facts flow into `GenerationRequest`, but its check is a regex over `generate.rs` (`GenerationRequest[\s\S]{0,1600}graph_facts\s*=`). The behavioral proof (`GRAPH_FIXTURE_MARKER_*` observed in the real provider request) is here at Wave 17. Ten waves of work rest on a regex.
- **MEDIUM — dispatcher drain order is inverted and unaddressed.** `nextEnvelope` drains `overflow` before `primary` (`checkpoint_sink.go:204-213`), but overflow entries are strictly *newer* than the envelope already sitting in `primary`. Under backpressure checkpoints persist out of order. The acceptance criterion says "ordered trace and sequence rows" — if the test orders by `sequence_ordinal` in SQL, it will pass while the defect stands.
- **MEDIUM — Task 1 is not one task.** Real cross-runtime SSE, two error-framing behaviors, disconnect cancellation, the wire-contract test, the fixture rewrite with exact UUID literals, and a sweeping "every gateway integration fixture" hygiene rule are six independently revertible changes with different risk profiles.
- **LOW — exact UUID literals (`...0101/0102/0103`) as acceptance criteria** over-specify. The property that matters is "seed entity resolves to the neighbor via an edge with weight 1.0 and score ≥ 0.5", which the plan also states; the literals add churn without adding proof.

**Suggestions**
- Split Task 1 into (a) SSE correctness + error framing, (b) the graph fixture + cross-runtime marker proof, (c) disconnect cancellation. (b) in particular should move much earlier — ideally right after 05-08 — so the graph-fact path has behavioral evidence before eight plans build on it.
- Add an explicit acceptance criterion that persisted checkpoints are in **submission** order under backpressure, and assert it by insertion order (a monotonic serial column), not by sorting on `sequence_ordinal`.

---

## 05-12 — Traceability errata and source coverage audit

**Summary.** The substantive correction is right and worth doing — two SUMMARY requirement lists are demonstrably wrong and two narratives overclaim. But the plan wraps a documentation fix in a git-forensics apparatus (blob-hash freezes, staged/unstaged path checks, a boundary-commit precondition) that is disproportionate for a single-developer local-first demo whose PROJECT.md constraint is "avoid speculative hardening."

**Strengths**
- Both corrections are verified exactly: `[ORCH-01, ORCH-03, ORCH-05]` for 05-02 and `[ORCH-01, ORCH-02, ORCH-03]` for 05-03 match the PLAN frontmatter, and the summaries' `RAG-01/RAG-02/GEN-*/EVENT-03` IDs are either Phase 03 requirements or not in `.planning/REQUIREMENTS.md` at all.
- Additive-errata over rewriting history is the correct call — it preserves execution history while giving downstream verifiers a canonical source.
- The "Evidence Timing and Timeout Contract" distinction (sub-second deterministic vs. `config.verify.toml` 7000 ms live) is the single most valuable artifact in this plan; it names the exact way the existing suite deceived itself.
- Correctly placed in Wave 7 with no Rust dependency.

**Concerns**
- **MEDIUM — scope creep in process weight.** Fourteen frozen blob hashes, staged *and* unstaged path checks, `git diff --check`, plus a precondition that "the final plan-document boundary commit contains the exact frozen blobs" before execution may begin. This is more ceremony than the artifact it protects, and it makes the plan fail for reasons unrelated to its content.
- **MEDIUM — the errata documents a planned compile-break window as acceptable.** It records that full-suite sampling is suspended for Waves 7–13 because of the GraphQueryPort/BM25 handoffs. Writing that down is honest, but it institutionalizes a seven-wave window in which the binary test target is knowingly not green (see Cross-Plan #2).
- **LOW — self-referential acceptance.** Several criteria are "the errata contains string X". A document whose acceptance test is that it contains its own required sentences is not verifiable in the sense the rest of this set uses the word.

**Suggestions**
- Keep the two requirement-list corrections, the overclaiming corrections, and the evidence-timing taxonomy. Drop the blob-hash preservation guard to a single `git status --porcelain -- <14 paths>` emptiness check — same protection, a fraction of the failure surface.
- Since this plan exists to prevent overclaiming, add one criterion with teeth: the errata must state, per ORCH requirement, whether evidence today is *source-guard*, *deterministic-semantic*, or *live-runtime*. That classification is what future readers actually need.

---

## 05-13 — OpenRouter preflight classification, success-only caching, bounded retry

**Summary.** The sharpest diagnosis in the set. The current code has a defect worse than the plan states, and closing it is a prerequisite for D-12's retry meaning anything.

**Strengths**
- The failure chain is verified end to end: `openrouter.rs:375-376` calls `check_supported_parameters()` inside `execute_one_call`, which is wrapped by `timeout(self.config.timeout /* 30 s */, ...)` at `:629`. So the preflight (a) runs on **every** attempt including the retry, (b) consumes the per-attempt budget, and (c) on any transport failure returns `GenerationErrorKind::SupportedParameters` (`:299`).
- **That third point is more severe than the plan says.** `generate.rs:71-75` treats `SupportedParameters` as **non-retryable**. So today a transient network blip against the `/models` endpoint — a pure transport error — permanently disables the retry D-12 mandates. The plan's fix (transient transport → retryable; genuine unsupported-parameter → non-retryable) is precisely correct.
- Instance-scoped, success-only cache keyed by `(models_endpoint, model)` is the right cache contract: it cannot poison on failure and cannot leak across differently-configured generators.
- "Only the two serialized `GenerationRequest` values are identical" is a well-chosen assertion — it proves D-12's byte-identical replay without over-constraining unrelated request state.

**Concerns**
- **MEDIUM — 05-13 and 05-20 are the same change, split across seven waves.** 05-13 (Wave 9) gives preflight its own deadline *inside* the node; 05-20 (Wave 16) moves it *out* of the node timer into a `Node::prepare` hook. Both touch `openrouter.rs`, `generate.rs`, and `node.rs`. The second largely supersedes the first's timing rationale, so the tree carries an intermediate design for seven waves and pays for two rounds of test rework.
- **MEDIUM — "typed retryability available to `NodeFailed` construction"** has no consumer in this plan. `events.rs:74-86` takes `retryable: bool` and every call site passes `false` (`runner.rs:153`, `:196`, `:250`). The field only becomes observable when 05-11 forwards it to SSE, at Wave 17. Producing a value nothing reads for eight waves invites it drifting back to a literal.
- **LOW — "the named `openrouter_effective_usage_limits` mock … a cache regression fails promptly rather than hanging a listener join"** is a good catch, but the criterion describes a symptom, not a bound. Name the timeout.

**Suggestions**
- Merge the `Node::prepare`/bootstrap seam from 05-20 Task 1 into this plan. The preflight belongs outside the node timer *because* of the very arithmetic 05-13 is establishing; doing it in one place removes an intermediate design and a rework cycle.
- Add a regression that specifically encodes the sharp bug: a `/models` connection reset followed by a healthy retry must produce a successful answer. That single test is the whole value of this plan.

---

## 05-14 — Exhaustive typed NodeKind dispatch and early reformulation admission

**Summary.** A clean, well-bounded refactor with a real correctness payload hidden inside it — the variant-admission fix changes observable event behavior, not just types.

**Strengths**
- Both defects verify. `runner.rs:104-113` dispatches on `&'static str` with a silent `_ => 5000ms` fallback, so a renamed or new node gets a wrong timeout with no compile error. And the ≥9-variant check at `runner.rs:185-201` runs **after** `run_node` has already emitted `NodeCompleted` *and* a checkpoint for `ReformulateQuery` — so a rejected request currently emits `NodeCompleted` followed by `NodeFailed` for the same node, which no event-contract reading permits.
- Exhaustive `match` over a five-variant enum makes the "add a node, forget a match arm" class impossible — the right use of the type system for a locked node set.
- Task decomposition (reformulate → graph/retrieve → prompt/generate) is genuinely incremental and each step is independently compilable.

**Concerns**
- **MEDIUM — `runner.rs` is edited by four plans across Waves 10, 14, 15, 16** (05-14, 05-10, 05-19, 05-20). Sequencing is respected, but 05-10 rewrites the same `match` arms this plan makes exhaustive, and 05-20 changes the node-timer boundary those arms select. High churn on a 311-line file that is the phase's central control flow.
- **LOW — the duplicate-lifecycle fix is not stated as an acceptance criterion.** "Nine variants fail before ReformulateQuery completion" implies it, but the observable contract ("exactly one lifecycle event for the rejected node; no `NodeCompleted`; no checkpoint") should be asserted directly — that is the client-visible change.
- **LOW — 05-02's SUMMARY already claimed this** ("a distinct `variants.len() <= 8` admission step … before ExtractGraphContext"). Literally true (it does precede the next node) but not in the sense the phrase implies. Worth adding to 05-12's errata as a third overclaim.

**Suggestions**
- Assert the event cardinality for the rejection path explicitly: `NodeStarted(ReformulateQuery)` → `NodeFailed(InputValidation)` → `WorkflowCompleted(failed)`, with no `NodeCompleted` and no checkpoint between.
- Consider folding 05-10's runner changes into this plan's Task 3 — they touch the same arms and are both pre-05-11 infrastructure.

---

## 05-15 — Prompt API contract and `cfg(test)`-only workflow fakes

**Summary.** Two unrelated hygiene items in one plan. The prompt-documentation half is low-risk and correct. The fake-gating half is the highest-risk change in the set, and its risk is not acknowledged anywhere in the plan.

**Strengths**
- The findings verify: `prompt.rs:234` (`pack_evidence_prompt_sync`) and `:255` (`pack_evidence_and_graph_prompt_sync`) are public blocking helpers in an async service, and `ports.rs:69-362` compiles six `Fake*` types into every production binary.
- The `graph_weight` executable contract (zero excludes, positive includes, without changing evidence-selection authority) is a good way to pin a parameter that currently has no test distinguishing its two regimes.
- `PromptAssemblyError::Cancelled` round-trip coverage is worth having — `assemble_prompt.rs` maps it to `NodeError::cancelled()` and nothing currently proves that mapping.

**Concerns**
- **HIGH — gating `ports.rs` fakes behind `cfg(test)` breaks the binary test target.** `engine/src/tests.rs` contains **25** references to `crate::workflow::ports::Fake*` / `engine::workflow::ports::Fake*` (lines 7103–7807), inside `#[cfg(test)] mod tests` declared at `main.rs:3174`. Because `workflow` reaches the binary via `use engine::workflow;` (`main.rs:38`) — i.e. through the **library crate, compiled without `cfg(test)`** — those fakes vanish for the binary test build. 05-18 removes only the `pub mod workflow_phase5;` declaration (`tests.rs:11`); it does not relocate the 25 call sites, and no plan in this set does. This detail is subtle and the plan gets one part of it *right by accident*: `FakeGenerator` is safe, because `main.rs:33` declares `pub mod generation;` locally, so the binary compiles its own `cfg(test)`-enabled copy. The `workflow::ports` fakes have no such second compilation.
- **MEDIUM — two unrelated concerns in one plan.** Prompt docs and test-double compilation boundaries share no failure mode; bundling them means a revert of the risky half also reverts the safe half.
- **LOW — "synchronous helpers are absent from the public API or are `cfg(test)` crate-visible only"** offers two materially different outcomes as equally acceptable. Pick one; "or" in an acceptance criterion is a deferred decision.

**Suggestions**
- Before gating, add an explicit acceptance criterion: *every* `crate::workflow::ports::Fake*` / `engine::workflow::ports::Fake*` reference in `engine/src/tests.rs` is either relocated to the library target or the enclosing test is moved. Enumerate them — there are 25, at `tests.rs:7103, 7104, 7105, 7121, 7161, 7162, 7195-7197, 7253, 7269, 7305-7308, 7366-7372, 7698, 7734, 7765, 7807`.
- Split into 05-15a (prompt docs + `graph_weight` contract, no dependencies) and 05-15b (fake gating, dependent on the relocation above). 15a can run much earlier.

---

## 05-16 — Graph notice merge, variant provenance, immutable BM25 snapshotting

**Summary.** Four real defects, correctly grouped by the layer they live in. The BM25 lock fix is the most operationally significant change in the whole set, and it is under-weighted relative to the notice cosmetics it shares a plan with.

**Strengths**
- All four verify. `graph_context.rs:122` stamps `code: "GRAPH_TIMEOUT"` on **every** graph failure including logical degradation (whose message is `graph_degrade: …`, line `:119`), so a client cannot distinguish timeout from no-match. `retrieve.rs:102-105` flattens per-variant BM25 results into one list, destroying variant provenance. `retrieve.rs:145-152` writes a snapshot with `index_generation: ""`, `embedding_model: ""`, `result_hash: ""`. And `main.rs:1311-1320` holds `self.bm25_index.read().await`'s guard across the `.retrieve(...).await`.
- **The BM25 finding is a genuine production hazard**, not a code-quality nit: `bm25_index` is `Arc<RwLock<Bm25Index>>` (`main.rs:864`) and ingestion takes the write lock. A stalled retrieval therefore wedges ingestion for the duration of the node timeout. Requiring an O(1) `Arc` handle snapshot before any await is exactly right.
- The scope fence is disciplined: it explicitly declines to edit `engine/src/tests.rs` (ceded to 05-18) and refuses to create a second production population path for the new snapshot fields (ceded to 05-17's contract).

**Concerns**
- **HIGH (sequencing) — the BM25 fixture migration precedes the type it migrates to.** 05-18 (Wave 11) is required to convert the 18 `bm25_index:` constructions in `engine/src/tests.rs` to "the new Arc snapshot ownership shape," but that shape is introduced *here*, at Wave 13. 05-18's own verification acknowledges this by running only `cargo check --bin engine` (non-test) and deferring `cargo test --bin engine --no-run` to this plan's Task 2. The binary test target is therefore knowingly non-compiling from Wave 11 to Wave 13.
- **MEDIUM — the notice-code split is a client-visible contract change with no versioning note.** Today every graph failure emits `GRAPH_TIMEOUT`; after this, half emit `GRAPH_DEGRADED`. D-22 governs `NodeFailed` categories, not notice codes, so nothing locked is violated — but any consumer keying on `GRAPH_TIMEOUT` silently loses half its matches.
- **MEDIUM — the BM25 change is bundled with cosmetics.** Notice codes and variant provenance are display concerns; the lock fix changes concurrency behavior between the query path and the ingestion worker. They have different revert profiles.
- **LOW — "the source guard is scoped to the BM25 production adapter … checks the ownership type plus guard-release ordering"** — guard-release ordering is a lifetime property. A grep can check that no `.await` textually follows `.read().await` before a `drop`, but the robust proof is a test that takes the write lock concurrently and asserts it is granted while a retrieval is stalled.

**Suggestions**
- Have 05-18 introduce the new ownership shape as a **compatibility alias** (or land the type change itself, deferring only the call-site semantics) so the 18 fixtures migrate to something that exists. That collapses the Wave 11–13 non-compiling window to zero.
- Prove the lock fix behaviorally: stall a BM25 retrieval, assert an ingestion write-lock acquisition completes while it is stalled. That is the property that matters and no grep can establish it.

---

## 05-17 — Shared protobuf provenance and failure-terminal notice fields

**Summary.** A textbook additive wire change: correct tags, correct preservation guarantees, and — importantly — it owns the compile repair of every exhaustive construction site rather than leaving the crate broken for downstream plans.

**Strengths**
- The tag choices are verified free and non-breaking: `RetrievalSnapshot` ends at tag 9 (`lancet.proto:91-101`) and `WorkflowCompletedEvent` at tag 5 (`:184-190`), so 10/11 and 6 are additive.
- The "Review-mode compile-order correction" in `<scope_rationale>` is the single best piece of sequencing reasoning in the set: it identifies the four exhaustive Rust literals that break the instant Buf adds fields (`retrieve.rs:145`, both `main.rs` production regions, `events.rs:131`) and initializes them with zero values *at the introducing wave*, leaving semantic population to 05-16/05-19. This is exactly the pattern the BM25 handoff (Cross-Plan #2) should have followed.
- The `clean: false` trade-off is stated with a compensating control (post-generation exact-allowlist inventory + `buf lint`) rather than silently accepted — `engine/src/pb/mod.rs` is hand-written and lives in the Rust output root, so cleanup genuinely cannot be enabled.
- The ownership census ("every `RetrievalSnapshot {` and `WorkflowCompletedEvent {` literal is assigned to 05-17 / 05-16 / 05-19 / 05-11") is the right way to prevent a silently orphaned construction site.

**Concerns**
- **MEDIUM — checked-in generated bindings mean the review gate is a diff, not a build.** `engine/src/pb/lancet/v1/lancet.v1.rs`, the tonic file, and both Go files are committed artifacts. "Generated output is source-derived and `git diff --check` is clean" does not prove the checked-in files were actually regenerated from the edited `.proto` rather than hand-edited to match. A determinism check (regenerate, diff against HEAD, require empty) would.
- **LOW — `WorkflowCompletedEvent.notices` sits at the edge of D-30.** D-30 prohibits workflow *metadata* on `WorkflowCompleted`; notices are arguably payload, not metadata, and 05-19 needs them. The reasoning is sound but it touches a locked decision and deserves the same explicit amendment treatment D-17 received in `05-CONTEXT.md`, not just an inline assertion.
- **LOW — eleven files including four generated ones** makes the diff hard to review by eye. Unavoidable given checked-in bindings, but a stated split ("schema + config in one commit, regenerated artifacts in a second") would help.

**Suggestions**
- Add a regeneration-determinism gate: `buf generate` into a temp dir, byte-compare against the checked-in bindings, fail on any difference. That converts "was regenerated" from a claim into a check.
- Record the `WorkflowCompletedEvent.notices` addition as a dated D-30 clarification in `05-CONTEXT.md`, mirroring the D-17 amendment format.

---

## 05-18 — Library-target Phase 5 tests and `cfg(test)` fake-port seam

**Summary.** Fixes the structural problem underneath several other plans' verification claims. Correctly identifies that Phase 5's tests live in the wrong target; its own verification is deliberately, and problematically, partial.

**Strengths**
- The premise verifies precisely: `lib.rs` has no `mod tests`; `main.rs:3173-3174` declares `#[cfg(test)] mod tests;`; `tests.rs:11` re-exports `workflow_phase5`. So all 780 lines of `engine/src/tests/workflow_phase5.rs` are binary-target-only today, and every `--lib` gate in the set is vacuous until this lands.
- "Exactly one registration" counting (source-level declaration counts *plus* `cargo test --list` filters) is the right defense against a silently skipped module — the failure mode where tests exist, compile, and never run.
- Splitting generic fake-port coverage (library) from production-builder coverage (binary) is the correct axis: production tests need `main.rs`'s service type, generic tests need `cfg(test)` fakes, and no single target provides both.

**Concerns**
- **HIGH — this plan owns the 18 BM25 fixture migrations but not the type they migrate to** (see 05-16). Its verification runs only `cargo check --bin engine` (non-test binary) and explicitly defers the binary test compile to 05-16 Task 2, two waves later. The plan is transparent about this, which is to its credit, but transparency does not make the window safe: during Waves 11–13, 05-15 and 05-19 land library-target changes against a tree whose binary test target does not build, so 05-08's Task 3 gate cannot be re-run as a regression.
- **HIGH (inherited) — moving `workflow_phase5.rs` to the library does not solve the 25 `crate::workflow::ports::Fake*` references still in `engine/src/tests.rs`** at lines 7103–7807. Those are in the binary's own test module, not the moved file, and 05-15 (next wave) removes the types they reference. This plan is the natural owner of that relocation and does not claim it.
- **MEDIUM — "18 BM25 test-service constructions"** is exact (`grep -c 'bm25_index:' engine/src/tests.rs` → 18), but the same file has 37 total `bm25_index` references. If the field's *type* changes, non-construction uses (reads, guards) also break. The criterion counts constructions only.

**Suggestions**
- Take ownership of the fake relocation: either move the workflow-fake-dependent tests at `tests.rs:7103-7807` into `tests/workflow_phase5.rs` (now library-target), or have the binary declare its own `mod workflow;` so `cfg(test)` applies. Either closes the 05-15 break; the first is cleaner.
- Land the new BM25 ownership type (or an alias) here rather than only migrating call sites to it, so `cargo test --bin engine --no-run` stays green from Wave 11 onward and the "intermediate compile-break window" in 05-12's errata disappears.

---

## 05-19 — Failure-terminal notice preservation through Go SSE

**Summary.** Small, focused, well-sequenced, and closes a real client-visible hole. One of the two cleanest plans in the set.

**Strengths**
- The gap is real and complete: on failure, `runner.rs:294-302` emits `WorkflowCompleted` with `final_response: None`, and `WorkflowCompletedEvent` has no notices field, so every accumulated notice — including `GRAPH_TIMEOUT`/`GRAPH_DEGRADED` from `graph_context.rs:120-125` — is silently discarded. A client is told "generation failed" with no indication the graph had already degraded.
- Correctly sequenced behind 05-17 (field) and 05-16 (notice semantics) and 05-18 (library target) — the `depends_on` list is accurate, not decorative.
- The negative assertions are the right ones: no `AnswerChunk`, no `FinalAnswer`, no `final_response` on failure. This directly preserves D-05 and D-13's "no fabricated answer" and prevents the very fabrication pattern `workflow/mod.rs:210-218` exhibits today.
- Three-task split (Rust construction → Rust assertions → Go SSE assertions) mirrors the data flow and gives each layer its own revert point.

**Concerns**
- **LOW — "the raw SSE test fails if notices are … serialized under a different shape"** is under-specified. `gateway/main.go:875-895`'s `queryRAGResponseDTO` already has a `noticeDTO` shape; the plan should name whether failure notices reuse it (they should) rather than leaving the shape open.
- **LOW — no criterion for the *success* path carrying notices.** Task 1 says "on success and failure," but every assertion is about failure. Success-path notices currently ride inside `final_response.notices`; after this change they exist in two places, and nothing says whether that duplication is intended.

**Suggestions**
- State explicitly that `WorkflowCompletedEvent.notices` reuses the existing `Notice` message and the gateway's existing `noticeDTO`, and pin whether success terminals populate both `notices` and `final_response.notices` or only the latter.

---

## 05-20 — Preflight bootstrap timing, worst-case retry budget, bounded tests

**Summary.** The arithmetic is correct and the `Node::prepare` seam is the right structural answer. Its problem is placement: it is a Wave 16 correction to a Wave 9 design decision, in the same files.

**Strengths**
- The budget arithmetic checks out: 5 + 15 + 10 + 2 + 65 = 97 s of node timers, plus a 5 s preflight bootstrap = 102 s worst case. And the gateway route genuinely permits it — `/rag/query` is in the `r.Group` at `gateway/main.go:471-474` that omits `middleware.Timeout(60*time.Second)`, unlike the document routes at `:465-470`. That claim, which would have invalidated the whole budget, is true.
- Moving preflight outside the node timer is the correct resolution of a real conflict: D-17's amendment widened the node budget to 65 s specifically to fit 2 × 30 s + 5 s slack, and a 5 s in-timer preflight consumes exactly that slack.
- `Node::prepare` with a default no-op and exactly one overriding node is a minimal, well-scoped trait extension — it does not turn `Node` into a lifecycle framework.
- The 4999 ms / 9999 ms pre-deadline boundary tests catch the off-by-one class that timeout code reliably produces, and the bounded receiver drain on `workflow_phase5_happy_path` closes a genuine hang risk.

**Concerns**
- **MEDIUM — seven waves of rework.** This plan re-opens `openrouter.rs`, `generate.rs`, and `node.rs` to relocate the preflight that 05-13 just finished bounding in place. Tests written against the 05-13 design at Wave 9 are rewritten at Wave 16.
- **MEDIUM — 102 s is a derived sum, not an enforced ceiling.** Nothing in `runner.rs` enforces a whole-workflow deadline; the figure is the sum of independent node timers. A client can hold an SSE stream for ~102 s with no single component exceeding its budget, and the gateway deliberately does not cap it. That is a defensible design for a local demo, but it should be *stated* as an accepted risk rather than implied by an arithmetic proof.
- **LOW — the nine binary filters are gated behind three prior conditions** (05-18 registration, 05-16 BM25 handoff, 05-16 Task 2's `--no-run`). Correct sequencing, but it means the definitive execution evidence for nine tests — including all four of 05-08's production regressions — arrives at Wave 16, nine waves after the code they test.

**Suggestions**
- Merge Task 1 into 05-13 (see that plan's suggestion). The preflight's timing seam and its classification/caching contract are one design.
- Add an explicit accepted-risk note for the unenforced 102 s ceiling, or add a single whole-workflow deadline in `run_workflow` — one `tokio::time::timeout` around the node loop is cheap and makes the derived budget real.

---

## 05-21 — Typed fusion provenance and review cleanup guards

**Summary.** The smallest, cleanest, lowest-risk plan in the set. Two verified defects, two files, no cross-plan entanglement.

**Strengths**
- Both findings verify exactly: `fusion.rs:18` stores `source: String`, filtering compares string literals at `:145` (`p.source == "vector"`) and `:153` (`== "bm25"`), and `:33` carries `#[serde(default)]` on a field of a `Serialize`-only struct — genuinely dead, since `default` only affects `Deserialize`.
- Preserving lowercase `"vector"` / `"bm25"` on the wire while typing the internal representation is the right trade: it is a pure refactor at the boundary that matters and a type change everywhere else.
- "The tracer proves one merged vector/BM25 path without altering RRF scores, ranks, or candidate ordering" is the correct invariant for a refactor of fusion internals — behavior-preservation is the whole acceptance criterion.
- Only file dependency is on 05-16's retrieval work, and Wave 14 respects it.

**Concerns**
- **LOW — the two source guards are greps** ("no free-form string comparison at the provenance filter boundary", "no ineffective serde default"). The first is largely obviated by the enum itself: once `source` is an enum, `p.source == "vector"` will not compile. The guard is belt-and-braces, which is fine, but it is not what enforces the property.
- **LOW — no criterion pins the `Display`/`Serialize` implementation** as the single source of the lowercase strings. If the enum serializes via a derive *and* a separate `to_string`, they can drift.

**Suggestions**
- Assert the round-trip once — enum → JSON → exact lowercase literal — from a single serialization path, and note that the enum's existence is itself the guard against string filtering.

---

## Cross-Plan Findings

These are the issues no single-plan reading surfaces, and they are where the real risk in this set lives.

**1. HIGH — The `cfg(test)` fake gating (05-15, Wave 12) breaks the binary test target, and no plan owns the fix.**
`engine/src/tests.rs` holds 25 references to `crate::workflow::ports::Fake*` / `engine::workflow::ports::Fake*` (lines 7103–7807), inside `#[cfg(test)] mod tests` at `main.rs:3174`. The `workflow` module reaches the binary through `use engine::workflow;` (`main.rs:38`) — the **library crate, compiled without `cfg(test)`** — so gating those types removes them from the binary's test build. 05-18 removes only the `pub mod workflow_phase5;` line; 05-08 *edits and retains* four of these call sites (7104, 7162, 7307, 7368). The break surfaces at Wave 13, where 05-16 Task 2 makes `cargo test --bin engine --no-run` its gating command.
Note the asymmetry that makes this easy to miss: `FakeGenerator` is **safe**, because `main.rs:33` declares `pub mod generation;` locally, giving the binary its own `cfg(test)`-enabled copy. Only `workflow::ports` lacks that second compilation.
*Fix:* assign the relocation of `tests.rs:7103-7807` to 05-18 explicitly, or have `main.rs` declare its own `mod workflow;`.

**2. HIGH — A deliberate three-wave compile-break window (Waves 11–13) removes regression coverage from four plans.**
05-18 (Wave 11) migrates 18 BM25 fixtures to an ownership shape 05-16 (Wave 13) has not yet introduced. 05-18's verification runs only `cargo check --bin engine` (non-test); 05-12's errata formalizes the gap by suspending full-suite sampling for Waves 7–13. During that window 05-15 and 05-19 land, and 05-08's Task 3 gate (`cargo test --bin engine --no-run`) cannot be re-run.
This is doubly notable because **05-17 solves the identical problem correctly** — it takes ownership of the four exhaustive construction sites and initializes them with zero values at the introducing wave, so the crate never stops compiling. Apply that pattern here: land the BM25 type (or an alias) in 05-18.

**3. MEDIUM — The verify blocks are the real acceptance gates, and they are overwhelmingly text checks.**
Roughly 80% of the `<automated>` content is PowerShell substring/count/regex over source. Concretely:
- 05-08 Task 1: `Some\s*\(` count ≥ 7, `add_node` count == 5, `$builder.Contains('self.embedder')`, D-06 order via `IndexOf` of type names. A comment block satisfies several; a commented-out `add_node` satisfies another.
- 05-08 Task 2/3: fabrication guards search for the literals `'Content of chunk'` (`assemble_prompt.rs:71`) and `'Answer for {'` (`workflow/mod.rs:212`). Both match today — but renaming the literal satisfies the guard without changing behavior.
- Region extraction `(?s)fn NAME\b.*?(?=\n\s*(?:pub\s+)?(?:async\s+)?fn\b|\z)` terminates at the first nested `fn` at any indentation, so a helper closure or inner `fn` silently changes what every downstream `.Contains()` in that block inspects.

This is a *class*, not a per-plan defect, and the set is aware of it — several plans explicitly demand behavioral proofs. The recommendation is to rank: for each plan, name the one test whose *failure* would mean the gap is not closed, and treat the greps as regression tripwires rather than acceptance.

**4. MEDIUM — Behavioral evidence is heavily back-loaded.**
The four production regressions introduced by 05-08 at Wave 7 are not *executed* under a registered binary filter until 05-20 at Wave 16. The graph-facts-reach-the-provider proof lands at 05-11, Wave 17. Cancellation's end-to-end proof lands at Wave 17. For Waves 7–15, ORCH-01/02/03 rest on source guards and library-target semantic tests. Any single-wave slip at 15–17 leaves the phase claiming closure on grep evidence.
*Fix:* pull the graph fixture + marker proof (05-11 Task 1, criteria 7–8) forward to immediately after 05-08, and pull 05-08's four production filters forward to 05-18's wave once registration exists.

**5. MEDIUM — Two plan pairs are one change each, split across many waves.**
05-13 (Wave 9) / 05-20 (Wave 16) both restructure the preflight in the same three files, the second superseding the first's timing rationale. 05-16 (Wave 13) / 05-18 (Wave 11) split a type change from its call sites in the wrong order. Merging each pair removes an intermediate design, a rework cycle, and — in the BM25 case — the compile-break window in finding #2.

**6. MEDIUM — Snapshot payload growth is designed in one plan and paid for in another.**
05-10 (Wave 14) mandates 19-field checkpoints including the full 2048-float `query_embedding`; 05-11 (Wave 17) must then make that survive a dispatcher whose capacity is 1 + 4 (`checkpoint_sink.go:159-161`) over an `mpsc::channel(100)` shared with answer events. Neither plan sizes the payload. At ~20–40 KB per snapshot × 6–7 snapshots, this is the dominant term in both transport and storage — and `query_embedding` is not among D-28's enumerated fields. Storing a digest instead keeps D-28 compliance and removes the pressure.

**7. LOW — Same-wave file collisions are clean.** Wave 7 (05-08 Rust / 05-12 docs), Wave 11 (05-17 proto+generated / 05-18 test registration), and Wave 14 (05-10 runner+events / 05-21 fusion) share no `files_modified` entries. Parallel execution within waves is safe as declared.

**8. LOW — Cumulative churn on `engine/src/workflow/runner.rs`.** Edited by 05-10, 05-14, 05-19, and 05-20 across Waves 10–16 — four plans on a 311-line file that is the phase's central control flow. Sequencing is correct; the merge/review burden is real.

---

## Risk Assessment

**Overall: MEDIUM-HIGH.**

*What lowers the risk:* The diagnosis underlying all 14 plans is verified accurate — I checked every structural claim above against source and found no fabricated gap. Wave dependencies are honest (`depends_on` lists match the roadmap and the actual data flow). Locked decisions are respected: D-03's zero-evidence short-circuit, D-06's graph-before-retrieval order, D-10's untouched `QueryGraph` RPC, D-12's single retry, D-13's no-fabricated-answer rule, D-30/D-31's deferred observability. The additive proto design (05-17) is wire-safe with free tags. Several plans (05-19, 05-21, 05-17) are genuinely clean and low-risk. And the set is self-aware: 05-12 exists specifically to stop the phase from overclaiming again, which is the correct instinct after summaries mis-stated their own requirement IDs.

*What raises it:* Two structural sequencing defects (findings #1 and #2) predict compile failures at Waves 12–13 that the current verification design will not catch early — 05-18's non-test-only `cargo check` is precisely the gate that lets them through. The acceptance apparatus is dominated by source-text greps, so several plans can be marked complete on evidence that does not establish the behavior they claim (finding #3), and 05-08's `--lib` gate is vacuous in its own wave. Behavioral proof concentrates in Waves 15–17, so a late slip strands the phase on grep evidence (finding #4). And the plan set is large for what it delivers: 14 plans, 17 waves, several of which are one change split in two.

*Highest-value corrections, in order:*
1. Assign relocation of the 25 `crate::workflow::ports::Fake*` call sites in `engine/src/tests.rs` before 05-15 gates the fakes.
2. Land the BM25 ownership type (or an alias) in 05-18 alongside its fixture migration, eliminating the Waves 11–13 non-compiling window — apply 05-17's already-correct compile-repair pattern.
3. For each plan, designate the single behavioral test whose failure means the gap is open; demote the source greps to tripwires.
4. Merge 05-13 with 05-20 Task 1, and pull 05-11's graph-fixture marker proof forward to just after 05-08.
5. Replace the full 2048-float embedding in checkpoints with a digest.

With those five applied, this set closes the Phase 5 gaps convincingly. Without #1 and #2 in particular, execution is likely to stall mid-wave on a compile break that none of the current gates detect until two waves after it is introduced.


---

## Consensus Summary

Both reviewers independently source-grounded the current 14-plan gap-closure set against HEAD `7b2f5b0` and found that the underlying Phase 5 diagnosis is real. The plans have coherent wave ownership, preserve the locked D-03/D-06/D-10/D-12/D-13/D-30/D-31 decisions, and use additive protobuf tags with synchronized generated bindings. The disagreement is about execution assurance: AgY judged the revised DAG broadly low risk, while Claude identified concrete cross-plan acceptance and compilation hazards that should be resolved before execution.

### Agreed Strengths

- The production gap is correctly targeted: the current `query_rag` path registers only `ReformulateQuery` and still reaches the inline remainder; 05-08 directly owns five-node production wiring and typed context flow (`engine/src/main.rs:1716-1748`, `engine/src/workflow/mod.rs:1234-1537`).
- The plan set has explicit ownership boundaries and mostly coherent dependency ordering across production wiring, configuration, event delivery, protobuf evolution, test-target migration, and gateway persistence.
- The revised plans include meaningful executable evidence: production reachability tests, live timeout overlays, retry/cancellation tracers, cross-runtime SSE/checkpoint tests, wire round trips, and BM25 concurrency/fixture coverage.
- Cancellation must reach the in-flight generation/provider operation rather than creating a fresh token inside the adapter. Both reviews called out this boundary around `engine/src/generation/openrouter.rs` and the 05-13/05-20 handoff.
- Snapshot size and bounded delivery are coupled risks. Full checkpoint context, including large retrieval/generation payloads, flows through bounded Rust and Go queues (`engine/src/workflow/runner.rs:47`, `gateway/checkpoint_sink.go:159-188`); the plans need a deliberate backpressure, ordering, and storage-cost proof.

### Agreed Concerns

- Test-target handoffs around 05-15/05-16/05-18 are the highest-risk execution seam. The reviews agree that BM25 fixture migration and binary-test compilation must be gated at the introducing boundary; Claude found a specific unowned set of `engine/src/tests.rs` `workflow::ports::Fake*` references that may disappear when fakes become `cfg(test)`-only, while AgY also flagged the target synchronization requirement.
- The plan set relies heavily on source-text guards for some acceptance claims. This is useful as a cheap regression net, but it does not replace behavioral proof for concrete adapter identity, five-node order, graph facts reaching the provider, or exact event cardinality. Prefer executable tests where the plan claims runtime behavior.
- The generation preflight/retry/cancellation design is split between 05-13 and 05-20. The final owner must be unambiguous, and the earlier plan's tests must not encode an intermediate timing contract that the later plan supersedes.

### Divergent Views

- Risk level: AgY concluded the revised plan set is broadly low risk (with 05-11 and 05-16 at medium), whereas Claude concluded overall risk is medium-high.
- Fake gating: AgY treated the `cfg(test)` seam as a low-risk coordination item; Claude rated it HIGH because `engine/src/tests.rs` retains 25 binary-test references and no current plan explicitly relocates them before the fakes disappear.
- Acceptance quality: AgY generally accepted the guards and dependency ordering as sufficient with targeted execution recommendations; Claude found several gates vacuous or brittle, including the Wave 7 `cargo test --lib --no-run` gate, region-extraction/index-based checks, and the intentional Waves 11–13 binary-test compile gap.
- Packaging: AgY viewed 05-11 and the 05-13/05-20 split as workable with disciplined handoffs; Claude viewed the end-to-end gateway task as overloaded and the preflight work as one change split across distant waves.

### Recommended Planning Follow-up

Run `/gsd-plan-phase 5 --reviews` against this fresh artifact before execution. Prioritize the concrete Claude findings that are also consistent with the shared target/backpressure concerns: assign the 25 fake-port call sites or preserve their provider, eliminate or explicitly accept the three-wave binary-test compile gap, add behavioral graph/provider and event-cardinality checks earlier, preserve request cancellation through OpenRouter, and prove checkpoint ordering/backpressure rather than only sorting persisted rows by sequence.