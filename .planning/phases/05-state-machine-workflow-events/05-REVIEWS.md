---
phase: 5
reviewers: [codex, antigravity]
reviewed_at: 2026-08-11T22:05:30Z
plans_reviewed:
  - 05-01-PLAN.md
  - 05-02-PLAN.md
  - 05-03-PLAN.md
  - 05-04-PLAN.md
  - 05-05-PLAN.md
---

# Cross-AI Plan Review — Phase 5

## Codex Review

## Summary

The five plans are well researched and align closely with the locked Phase 5 decisions. The live source confirms the proposed extraction seams: the current unary pipeline starts at `[engine/src/main.rs:1346](/D:/Repos/lancet/engine/src/main.rs:1346)`, graph augmentation precedes retrieval at `[engine/src/main.rs:1426](/D:/Repos/lancet/engine/src/main.rs:1426)`, and the gateway is still unary with a global 60-second timeout at `[gateway/main.go:207](/D:/Repos/lancet/gateway/main.go:207)` and `[gateway/main.go:464](/D:/Repos/lancet/gateway/main.go:464)`. However, the plans are not yet execution-ready: Wave 4 has a file conflict, the Rust event-stream type conversion is underspecified, cancellation/error-send behavior is incomplete, and the checkpoint "size bound" does not actually guarantee a bounded payload.

## Strengths

- **Plan 01 preserves the validation boundary correctly.** It keeps `QueryRequest::from_values` before the stream opens and adds first-frame prefetch so gRPC validation failures can still become HTTP 4xx responses. This directly addresses the current handler boundary at `[engine/src/main.rs:1376](/D:/Repos/lancet/engine/src/main.rs:1376)` and unary gateway path at `[gateway/main.go:280](/D:/Repos/lancet/gateway/main.go:280)`.

- **The pipeline order is source-faithful.** Plan 02 correctly retains graph-before-retrieval ordering and introduces injectable graph/dense ports instead of hiding new behavior inside LanceDB calls. The existing ordering is visible at `[engine/src/main.rs:1426](/D:/Repos/lancet/engine/src/main.rs:1426)` and `[engine/src/main.rs:1450](/D:/Repos/lancet/engine/src/main.rs:1450)`.

- **The cross-variant RRF design is concrete.** Plan 02 specifies weighting, rank handling, provenance selection, tie-breaking, and an exact-score test rather than relying on the v1 NoOp reformulator. This is a meaningful improvement over an implementation that would only pass because one variant is currently returned. The existing single-pass fusion seam is `[engine/src/retrieval/fusion.rs:57](/D:/Repos/lancet/engine/src/retrieval/fusion.rs:57)`.

- **Plan 03 uses the existing generation contracts well.** `GenerationRequest` already derives `Clone` and `PartialEq` at `[engine/src/generation/mod.rs:375](/D:/Repos/lancet/engine/src/generation/mod.rs:375)`, and the provider already has a 30-second per-attempt timeout at `[engine/src/generation/openrouter.rs:24](/D:/Repos/lancet/engine/src/generation/openrouter.rs:24)`. The plan correctly separates that from the node-level retry budget.

- **Plan 04 closes a real validation gap.** Testing `AssemblePrompt` through the generic runner is appropriate because it has no natural I/O fake, and the full-pipeline trace consistency test is useful.

- **Plan 05 handles the database boundary thoughtfully.** It updates both Atlas's `schema.hcl` and sqlc's actual `schema.sql`, uses isolated test schemas modeled on `[gateway/main_test.go:1635](/D:/Repos/lancet/gateway/main_test.go:1635)`, threads `trace_id` from the enclosing event, and explicitly excludes checkpoint payloads from SSE.

## Concerns

- **HIGH — Wave 4 is not safely parallel.** The roadmap marks Plans 04 and 05 as parallel at `[.planning/ROADMAP.md:339](/D:/Repos/lancet/.planning/ROADMAP.md:339)`, but both modify `engine/src/tests.rs`: `[05-04-PLAN.md:5](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-04-PLAN.md:5)` and `[05-05-PLAN.md:5](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:5)`. This creates an avoidable merge conflict.

- **HIGH — The Rust event stream has a likely type mismatch.** Plan 01 defines a custom Rust `WorkflowEvent` enum, then describes a channel of that type being returned directly through `ReceiverStream` at `[05-01-PLAN.md:59](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:59)`. But tonic's generated server trait requires a stream of generated protobuf `WorkflowEvent` values; the current generated trait is protobuf-specific at `[engine/src/pb/lancet/v1/lancet.v1.tonic.rs:33](/D:/Repos/lancet/engine/src/pb/lancet/v1/lancet.v1.tonic.rs:33)`. The plan mentions conversion at `[05-01-PLAN.md:295](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:295)` but does not specify the required `map(|event| Ok(event.into_proto()))` adapter or make the channel carry protobuf messages directly.

- **HIGH — The checkpoint size guard is not actually bounded.** Plan 05 serializes full `FusedCandidate` values, whose candidates contain raw `content` at `[engine/src/retrieval/mod.rs:418](/D:/Repos/lancet/engine/src/retrieval/mod.rs:418)`, plus `PackedEvidence`, which contains the prompt, evidence, and encoded evidence blocks at `[engine/src/prompt.rs:168](/D:/Repos/lancet/engine/src/prompt.rs:168)` and `[engine/src/prompt.rs:71](/D:/Repos/lancet/engine/src/prompt.rs:71)`. Truncating only evidence text and graph-fact text, as specified at `[05-05-PLAN.md:158](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:158)`, can leave large duplicated strings in `prompt`, `encoded_blocks`, and `final_candidates`. The oversized test only checks `truncated == true` at `[05-05-PLAN.md:160](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:160)`; it does not assert the final serialized size is ≤256 KiB.

- **HIGH — Cancellation behavior on failed event sends is incomplete.** The runner is required to use reliable `.send().await` at `[05-01-PLAN.md:294](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:294)`, but the plan does not define how `SendError` is mapped into the runner's `Result<_, NodeError>`. After a client disconnects, the receiver is gone, so the runner cannot actually deliver the promised `NodeFailed{Cancelled}` and `WorkflowCompleted` events. The `spawn_workflow` ownership description also passes `tx` separately while saying the runner owns the original sender at `[05-01-PLAN.md:300](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:300)`. This needs one explicit ownership model and a best-effort terminal-send policy.

- **MEDIUM — The route-timeout option can accidentally leave the 60-second timeout active.** The current global middleware applies to every route at `[gateway/main.go:464](/D:/Repos/lancet/gateway/main.go:464)`. Plan 01 offers `r.With(middleware.Timeout(120s))` as one option at `[05-01-PLAN.md:325](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:325)`, but nesting a 120-second timeout under the existing 60-second middleware does not remove the 60-second parent deadline. The plan should require `/rag/query` to be structurally excluded from the blanket middleware and test behavior beyond 60 seconds.

- **MEDIUM — The checkpoint builder API is incomplete as written.** The proposed signature at `[05-05-PLAN.md:158](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-05-PLAN.md:158)` has no `node_name` parameter even though it constructs a `Checkpoint` containing one. It is also described as a private `fn`, while the tests live in the sibling `tests` module declared at `[engine/src/main.rs:3125](/D:/Repos/lancet/engine/src/main.rs:3125)`. It should be a `pub(crate)` function such as `build_checkpoint_snapshot(ctx, node_name) -> Result<Option<Checkpoint>, ...>`.

- **MEDIUM — Retry cancellation testing is still nondeterministic.** Plan 03 adds delays to `FakeGenerator` at `[05-03-PLAN.md:189](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:189)`, but a delay stalls attempt one; it does not create a deterministic synchronization point after attempt one returns and before attempt two begins. The cancellation-between-attempts requirement at `[05-03-PLAN.md:185](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:185)` needs a `Notify`, barrier, or callback-controlled fake.

- **MEDIUM — Error sanitization is asserted but not concretely designed.** The runner action forwards `err.to_string()` at `[05-01-PLAN.md:294](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:294)`, while current dense retrieval errors include formatted LanceDB details at `[engine/src/retrieval/dense.rs:60](/D:/Repos/lancet/engine/src/retrieval/dense.rs:60)`. Add category-specific public messages and retain detailed errors only in tracing fields; test with an injected path/connection-string error.

- **MEDIUM — The test inventory is stale.** Plan 01 says there are 17 existing query tests at `[05-01-PLAN.md:228](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md:228)`, but the live source has 29 direct `.query_rag(...)` call sites, including later graph-observability tests at `[engine/src/tests.rs:6232](/D:/Repos/lancet/engine/src/tests.rs:6232)`. The signature migration needs a generated checklist from `rg`, not only the enumerated 17-test list.

- **LOW/MEDIUM — `generate_max_retries` is a misleading configuration key.** Plan 03 adds the key but explicitly hardcodes one retry regardless of its value at `[05-03-PLAN.md:192](/D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-03-PLAN.md:192)`. Remove the key while D-12 is fixed, or validate and enforce it.

## Suggestions

- Make Plan 05 depend on Plan 04, or move Plan 04 and Plan 05 tests into separate Rust test modules/files.
- Choose one canonical wire representation: generated protobuf events in the channel, or an explicit Rust-to-protobuf mapping before `ReceiverStream`.
- Add a runner `send_event` helper that handles closed receivers as cancellation and never attempts terminal sends after the stream is gone.
- Replace full domain-object checkpoint serialization with a compact DTO containing bounded excerpts and metadata; assert the final JSON byte length.
- Add deterministic cancellation hooks to `FakeGenerator`.
- Make route exclusion from the global timeout an acceptance criterion, not merely one implementation option.
- Add explicit checkpoint serialization-failure handling so checkpoint generation can never fail or panic the user's query.
- Add a central error-sanitization mapper and a complete old-API reference scan before the streaming signature changes.

## Risk Assessment

Overall risk: **HIGH for execution, MEDIUM for architecture**.

The architecture and phase boundaries are strong, and the plans address most historical review feedback. The remaining risks are concentrated in shared infrastructure: the stream type conversion, cancellation ownership, Wave 4 merge conflict, and checkpoint payload bounding. Resolving those before execution should reduce the phase to a manageable medium-risk implementation.

---

## Antigravity Review

# Implementation Plan Review: Phase 5 State Machine & Workflow Events

## 1. Summary

The implementation plans for Phase 5 (`05-01-PLAN.md` through `05-05-PLAN.md`) provide a comprehensive, highly rigorous blueprint for formalizing Lancet's linear RAG query pipeline into a typed Rust state machine (`Node`/`WorkflowRunner`), converting `QueryRAG` from unary gRPC to server-streaming gRPC with an SSE HTTP boundary (`text/event-stream`), enforcing per-node timeouts and generation-only retries, and persisting full-snapshot checkpoints to PostgreSQL via Go. The design cleanly preserves established architectural boundaries—Go manages HTTP/SSE transport and PostgreSQL persistence, while Rust encapsulates data-plane state machine orchestration—and incorporates defensive error-handling patterns, such as Go first-frame prefetching to maintain HTTP 4xx statuses on pre-stream validation failures, reliable `.send().await` channels, and size-bounded JSON checkpoint snapshots.

## 2. Strengths

- **First-Frame Prefetch for HTTP Error Preservation (`05-01`)**: In [`gateway/main.go`](file:///D:/Repos/lancet/gateway/main.go#L280-L287), creating a gRPC server-stream succeeds before server-side validation runs in [`engine/src/main.rs:1346`](file:///D:/Repos/lancet/engine/src/main.rs#L1346). The plan's first-frame `stream.Recv()` prefetch ensures pre-stream validation errors (such as invalid `session_id` UUIDs or bad `QueryRequest` filters) map to HTTP 4xx/502 trailer errors before any HTTP `200 OK` header or `text/event-stream` body is committed.
- **Injectable Port Seam & In-Process Deterministic Testing (`05-01`, `05-02`, `05-04`)**: Defining `GraphQueryPort` and `DenseRetrievalPort` as `Arc<dyn Trait>` abstractions in `engine/src/workflow/ports.rs` (alongside existing [`Generator`](file:///D:/Repos/lancet/engine/src/generation/mod.rs#L100) and `EmbeddingProvider` traits) enables complete fault-injection, timeout, and degradation test coverage in `engine/src/tests.rs` without relying on flaky live network calls or unmanaged external I/O.
- **Strict Classification of LLM Retries (`05-03`)**: `GenerateAnswerNode` explicitly restricts automatic single-retry attempts to transient error kinds (`ProviderError`, `Timeout`, `SchemaValidation`). Non-retryable permanent errors (`InvalidRequest`, `SupportedParameters`, `SessionCorrelation`, `Cancelled`) fail immediately after one attempt, preventing redundant LLM calls while guaranteeing zero fabricated/unvalidated fallback answers on exhaustion.
- **Decoupled Fire-and-Forget Checkpointing (`05-05`)**: Rust builds a versioned, size-capped `CheckpointSnapshotV1` DTO sent as a sidecar on `NodeCompleted` events. Go persists these events asynchronously via a detached goroutine (`go a.persistCheckpoint(...)`) using a bounded 5-second `context.WithTimeout`, ensuring PostgreSQL write latency never degrades the client's SSE stream.
- **Synchronized Dual Schema Files & Safe PK Selection (`05-05`)**: Updates both [`gateway/db/schema.hcl`](file:///D:/Repos/lancet/gateway/db/schema.hcl) (Atlas source) and [`gateway/db/schema.sql`](file:///D:/Repos/lancet/gateway/db/schema.sql) (the file [`gateway/sqlc.yaml`](file:///D:/Repos/lancet/gateway/sqlc.yaml#L3) actually targets for `sqlc generate`) in lockstep. Utilizing a Go-generated `varchar(36)` UUID primary key avoids sequence state pollution across isolated test schemas (`LIKE public.workflow_checkpoints INCLUDING ALL`).

## 3. Concerns

- **MEDIUM: Environment Override Coupling for Inner vs. Outer Graph Timeouts (`05-02`)**: `05-02-PLAN.md` introduces a startup validation check in `EffectiveRagSettings::validate()` requiring `graph_outer_timeout_ms > graph_timeout_ms`. If a deployer overrides `LANCET_WORKFLOW__GRAPH_TIMEOUT_MS` to a higher value (e.g., `20000`) without also increasing `graph_outer_timeout_ms` above `20000`, application initialization will fail.
- **LOW: Node-Level vs. Provider-Level Timeout Interaction (`05-03`)**: `generate_timeout_ms` (65,000 ms default) is enforced at the node level by `WorkflowRunner`, while [`openrouter.rs:24`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L24) enforces an internal `GENERATION_TIMEOUT = 30s` per attempt. If attempt 1 takes 29.5s and fails, and attempt 2 takes another 29.5s plus 6.1s of accumulated tokio task scheduling or network overhead, the outer node-level timeout (65s) will trigger before attempt 2 returns, categorizing the failure as `NodeFailed{category: Timeout}` rather than `LlmGenerationFailed`. Both result in `WorkflowCompleted{success: false}`, so the user impact is negligible.
- **LOW: Edge-Case Truncation Scope in `build_checkpoint_snapshot` (`05-05`)**: `build_checkpoint_snapshot` truncates `assembled_prompt`'s evidence text and `graph_context`'s fact text if the JSON payload exceeds 256 KiB. In the improbable scenario that an oversized query string or candidate list alone exceeds 256 KiB, evidence/graph text truncation may not reduce the total payload size below 256 KiB.

## 4. Suggestions

- **Config Documentation**: In [`config/config.example.toml`](file:///D:/Repos/lancet/config/config.example.toml), add clear comments documenting that `graph_outer_timeout_ms` must always be configured to a value strictly greater than `graph_timeout_ms`.
- **Defensive Checkpoint Serialization**: In `engine/src/workflow/events.rs`, ensure `build_checkpoint_snapshot` includes a secondary truncation fallback (e.g., truncating `final_candidates` or `original_query`) if truncating `assembled_prompt` and `graph_context` still leaves the JSON payload above 256 KiB.

## 5. Risk Assessment

- **Overall Risk Level**: **LOW-MEDIUM**
- **Justification**: The plans exhibit exceptional attention to detail, strict adherence to architectural boundaries, and thorough risk mitigation. All major failure modes—such as client disconnections, stream buffer backpressure, provider errors, and database delays—are covered by explicit execution rules and backed by comprehensive Tier 1 (in-process Rust unit) and Tier 2 (Go + PostgreSQL integration) automated tests.

---

## Consensus Summary

Both reviewers independently confirm the plans against live source (not just the plan text): the graph-before-retrieval pipeline order, the first-frame prefetch fix, the injectable port seams, and the dual Atlas/sqlc schema sync all check out against the cited `file:line` locations in both reviews.

### Agreed Strengths

- **First-frame `stream.Recv()` prefetch preserves HTTP 4xx semantics** for pre-stream gRPC validation failures, verified against `gateway/main.go:280` and `engine/src/main.rs:1346`/`1376` by both reviewers.
- **Injectable `GraphQueryPort`/`DenseRetrievalPort` seams** enable deterministic Tier 1 fault-injection and timeout testing without live network calls.
- **Dual schema synchronization** (`gateway/db/schema.hcl` for Atlas, `gateway/db/schema.sql` for sqlc) is correctly kept in lockstep, with a Go-generated UUID primary key avoiding sequence-pollution risk across isolated test schemas.
- **LLM retry classification is strict and correct**: transient errors get exactly one retry, permanent errors fail fast, and no fabricated answers are produced on exhaustion.

### Agreed Concerns

- **Checkpoint payload size is not reliably bounded.** Both reviewers independently flag `build_checkpoint_snapshot` (05-05-PLAN.md:158-160): Codex rates this **HIGH**, showing that truncating only evidence/graph-fact text leaves full `FusedCandidate.content`, `PackedEvidence.prompt`, and `encoded_blocks` unbounded, and that the existing test only asserts `truncated == true` rather than the final serialized size; Antigravity rates the same mechanism **LOW**, framing it as an edge case limited to oversized query strings or candidate lists. The underlying code gap is the same in both reviews — treat this as a real gap to close (assert final byte size ≤256 KiB, and truncate `final_candidates`/`encoded_blocks` as a fallback, not just evidence/graph text), with Codex's severity assessment as the operative one since it identifies concrete unbounded fields rather than a narrow edge case.

### Divergent Views

- **Overall risk verdict diverges sharply**: Codex rates the plan set **HIGH risk for execution** (though MEDIUM for architecture), while Antigravity rates it **LOW-MEDIUM** overall. The gap is explained by scope, not disagreement — Codex surfaced four additional HIGH-severity findings that Antigravity's review does not mention at all:
  - **Wave 4 parallel-execution file conflict**: `05-04-PLAN.md` and `05-05-PLAN.md` both modify `engine/src/tests.rs` despite being scheduled to run in parallel per `ROADMAP.md:339`.
  - **Rust `WorkflowEvent` / protobuf type mismatch**: `05-01-PLAN.md:59` describes a channel of the custom Rust event enum being returned through `ReceiverStream` where tonic's generated server trait (`engine/src/pb/lancet/v1/lancet.v1.tonic.rs:33`) requires protobuf-typed messages, without specifying the conversion adapter.
  - **Incomplete cancellation/send-error handling**: no defined mapping from a failed `.send().await` (`SendError`, receiver dropped on client disconnect) into the runner's `Result<_, NodeError>`, plus an ownership ambiguity around who holds the event-channel sender.
  - **Route-timeout nesting bug**: wrapping `/rag/query` in a 120s `middleware.Timeout` does not remove the existing global 60s timeout middleware it would be nested under (`gateway/main.go:464`), so the route could still be cut off at 60s.

  These are concrete, source-verified defects rather than stylistic disagreements — since Antigravity's review does not contradict them (it simply doesn't examine that code path/wiring), they should be treated as confirmed gaps requiring plan revision before execution, not as an unresolved disagreement between reviewers.
