---
phase: 5
scope: gap-closure
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-16T06:55:12.7878050Z
source_head: 4e37c168498cf10ac658cd30192281dd979f0d7b
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
  - 05-22-PLAN.md
  - 05-23-PLAN.md
  - 05-24-PLAN.md
reviewer_models:
  antigravity: gemini-3.7-flash-high
  claude: opus
reviewer_effort:
  antigravity: high
  claude: high
reviewer_output_bytes:
  antigravity: 21358
  claude: 16593
---

# Cross-AI Plan Review — Phase 05 Gap Closure (Fresh)

This review was rebuilt from the current checkout at HEAD 4e37c168498cf10ac658cd30192281dd979f0d7b. The prior 05-REVIEWS.md contents were excluded as stale evidence. The reviewed scope is the 17 current additive gap-closure plans 05-08 through 05-24.

## Antigravity Review

# Plan Set Review: Phase 05 Gap-Closure (05-08 through 05-24)

## 1. Summary

The 17-plan additive gap-closure suite for Phase 05 ([`05-08-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md) through [`05-24-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-24-PLAN.md)) provides a comprehensive, highly defensive, and rigorously sequenced strategy to transition the RAG workflow from its initial prototype state into a fully production-wired, five-node state machine. The plan set systematically resolves the architectural gaps identified in [`05-VERIFICATION.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-VERIFICATION.md)—specifically the retirement of the monolithic inline fallback [`run_inline_prompt_generation_remainder`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L143-L223) in favor of the real five-node state machine ([`ReformulateQueryNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/reformulate.rs), [`ExtractGraphContextNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/graph_context.rs), [`RetrieveHybridNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/retrieve.rs), [`AssemblePromptNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/assemble_prompt.rs), and [`GenerateAnswerNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/generate.rs)), the elimination of fabricated response texts, type-safe [NodeKind](file:///D:/Repos/lancet/engine/src/workflow/node.rs) and [VariantProvenance](file:///D:/Repos/lancet/engine/src/retrieval/fusion.rs#L15-L22) dispatch, lossless event streaming, non-blocking BM25 snapshot concurrency, and end-to-end gRPC-to-SSE cross-runtime verification.

---

## 2. Strengths

- **Strict Compilation Sequencing and Target Seam Isolation**:
  The plan set establishes an explicit, compile-safe dependency ordering between protobuf schema evolution, Rust message construction repair, test harness splitting, and fake port visibility:
  - [`05-17-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-17-PLAN.md) adds wire fields ([`RetrievalSnapshot`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto#L91-L101) tags 10/11 and [`WorkflowCompletedEvent`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto#L184-L190) tag 6).
  - [`05-23-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-23-PLAN.md) immediately repairs all exhaustive Rust struct literals in [`engine/src/workflow/nodes/retrieve.rs`](file:///D:/Repos/lancet/engine/src/workflow/nodes/retrieve.rs), [`engine/src/workflow/events.rs`](file:///D:/Repos/lancet/engine/src/workflow/events.rs), and [`engine/src/main.rs`](file:///D:/Repos/lancet/engine/src/main.rs) with wire round-trip tests before downstream consumers run.
  - [`05-18-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-18-PLAN.md) splits generic workflow tests into the library target ([`engine/src/tests/workflow_phase5.rs`](file:///D:/Repos/lancet/engine/src/lib.rs)) and production-builder tests into the binary target ([`engine/src/tests/workflow_phase5_production.rs`](file:///D:/Repos/lancet/engine/src/tests.rs)), and migrates all 18 BM25 fixture constructions in [`engine/src/tests.rs`](file:///D:/Repos/lancet/engine/src/tests.rs).
  - [`05-15-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-15-PLAN.md) gates fake ports behind `#[cfg(test)]` in [`engine/src/workflow/ports.rs`](file:///D:/Repos/lancet/engine/src/workflow/ports.rs) only after the binary target has passed `cargo test --bin engine --no-run`.
  This prevents any intermediate compilation failure across Waves 11–18.

- **Protobuf Generation Protection**:
  In [`05-17-PLAN.md:89`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-17-PLAN.md#L89), the plan explicitly updates [`buf.gen.yaml:2`](file:///D:/Repos/lancet/buf.gen.yaml#L2) from `clean: true` to `clean: false` and establishes pre- and post-generation byte-identity assertions for the hand-written module glue [`engine/src/pb/mod.rs`](file:///D:/Repos/lancet/engine/src/pb/mod.rs#L1-L6), preventing Buf from wiping [`engine/src/pb/mod.rs`](file:///D:/Repos/lancet/engine/src/pb/mod.rs).

- **Lock-Free Concurrency for Lexical Ingestion & BM25 Retrieval**:
  [`05-16-PLAN.md:128`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-16-PLAN.md#L128) eliminates the threat of stalled asynchronous retrieval holding an `RwLock` read-guard across `.await` points in [`engine/src/workflow/nodes/retrieve.rs`](file:///D:/Repos/lancet/engine/src/workflow/nodes/retrieve.rs). By defining `Bm25IndexStore` as `Arc<RwLock<Arc<Bm25Index>>>`, the production adapter acquires the outer read lock, clones the inner `Arc<Bm25Index>` handle in $O(1)$, and immediately drops the `RwLockReadGuard` before initiating retrieval, ensuring concurrent background document ingestion is never blocked.

- **Deterministic Decoupling of Preflight Capability Check and Generation Node Timers**:
  [`05-13-PLAN.md:102`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-13-PLAN.md#L102) and [`05-20-PLAN.md:78`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-20-PLAN.md#L78) decouple OpenRouter `/models` capability validation from [`OpenRouterGenerator::execute_one_call`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L371-L376). By moving preflight into a runner bootstrap preparation phase (`Node::prepare`) with its own bounded 5-second deadline and single-flight cache (`Mutex<HashMap<CapabilityKey, Arc<OnceCell<ModelCapabilities>>>>`), the 65-second [`GenerateAnswerNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/generate.rs) timeout cleanly accommodates two full 30-second provider attempts (`2 x 30000ms + 5000ms` inter-attempt slack) without budget starvation.

- **Elimination of Response Fabrication & Stringly-Typed Logic**:
  [`05-21-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-21-PLAN.md) replaces raw string matching with a typed [`VariantProvenanceSource`](file:///D:/Repos/lancet/engine/src/retrieval/fusion.rs#L18) enum and removes the dead `#[serde(default)]` attribute on [`FusedCandidate.variant_provenance`](file:///D:/Repos/lancet/engine/src/retrieval/fusion.rs#L33-L35). [`05-22-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-22-PLAN.md) strips all placeholder text (`"Content of chunk..."` in [`AssemblePromptNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/assemble_prompt.rs#L71) and `"Answer for..."` in [`run_inline_prompt_generation_remainder`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L212)), binding prompt assembly and generation directly to authoritative [`WorkflowContext.graph_facts`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L40).

- **Complete Cross-Runtime Streaming & Event Validation**:
  [`05-11-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md) and [`05-19-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-19-PLAN.md) establish end-to-end test coverage connecting Rust tonic gRPC streams to Go chi SSE handlers via [`TestRAGQueryCrossRuntime`](file:///D:/Repos/lancet/gateway/main_test.go), verifying HTTP 200 in-band terminal event delivery, ordered diagnostics, and absence of answer events on failure paths.

---

## 3. Concerns

### MEDIUM: Checkpoint Context Snapshot JSON Schema Uniformity and Postgres Ingestion
- **Evidence**: [`05-10-PLAN.md:106-120`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-10-PLAN.md#L106-L120) expands the JSON context snapshot emitted in [`events::checkpoint`](file:///D:/Repos/lancet/engine/src/workflow/events.rs#L101-L122) to serialize all 19 [`WorkflowContext`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L29-L48) fields, including `query_embedding` (represented as an 8-float digest), `variants`, `graph_facts`, and `evidence_blocks`. In [`gateway/checkpoint_sink.go:107`](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L107), Go inserts `[]byte(env.ContextSnapshot)` into PostgreSQL column `context_snapshot JSONB`.
- **Mechanism / Impact**: If future gateway or diagnostic services deserialize `context_snapshot` into typed Go structs, discrepancies in field naming (e.g. snake_case vs camelCase) or structural variance across nodes (e.g., `query_embedding` present only post-retrieval) could cause unmarshaling panics or silent payload drop if schema contracts are not strictly validated across both languages.
- **Plan Reference**: [`05-10-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-10-PLAN.md), [`05-11-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md).

### MEDIUM: Derived Whole-Workflow Budget vs. Uncapped HTTP/SSE Connection Lifetimes
- **Evidence**: [`05-20-PLAN.md:97-105`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-20-PLAN.md#L97-L105) documents that individual node timeouts ($5\text{s} + 15\text{s} + 10\text{s} + 2\text{s} + 65\text{s} = 97\text{s}$) plus the 5-second preflight bootstrap result in a derived, non-enforced whole-workflow execution bound of 102 seconds. In [`gateway/main.go:697-735`](file:///D:/Repos/lancet/gateway/main.go#L697-L735), the HTTP handler delegates stream lifecycle to `r.Context()`.
- **Mechanism / Impact**: If an upstream client does not enforce an HTTP request timeout, a degraded workflow experiencing worst-case timeouts across multiple nodes can hold open gateway gRPC connections, response controllers, and Postgres checkpoint buffer slots for over 100 seconds before emitting a terminal event.
- **Plan Reference**: [`05-20-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-20-PLAN.md), [`05-09-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-09-PLAN.md).

### LOW: Test Database Schema Isolation Convention for Checkpoint Integration Tests
- **Evidence**: [`AGENTS.md`](file:///D:/Repos/lancet/AGENTS.md) specifies that integration tests writing to mutable database tables must utilize unique per-test schemas or isolated test databases. [`05-11-PLAN.md:104`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md#L104) introduces [`TestRAGQueryCrossRuntime`](file:///D:/Repos/lancet/gateway/main_test.go) and exercises [`PostgresCheckpointSink`](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L68-L116).
- **Mechanism / Impact**: If concurrent test runners execute against a shared PostgreSQL database instance without per-test search paths (`SET search_path TO ...`), checkpoint row insertions or sequence verifications could experience data contamination or race conditions.
- **Plan Reference**: [`05-11-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md).

### LOW: Capability Cache Scope Across Future Dynamic Config Reloads
- **Evidence**: [`05-13-PLAN.md:102`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-13-PLAN.md#L102) implements the model capabilities cache inside [`OpenRouterGenerator`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs) keyed by `(models_endpoint, model)`.
- **Mechanism / Impact**: The cache is instance-scoped and only caches successful results. In Phase 05 this is fully safe because configuration is immutable per engine process lifetime. If dynamic configuration reloading is introduced in future phases without instantiating a new [`OpenRouterGenerator`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs), stale capabilities could theoretically survive endpoint reconfigurations.
- **Plan Reference**: [`05-13-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-13-PLAN.md).

---

## 4. Suggestions

1. **Verify JSONB Round-Trip Validity in Gateway Cross-Runtime Tests**:
   - *Plan*: [`05-11-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md) (Task 1).
   - *Action*: In [`gateway/main_test.go`](file:///D:/Repos/lancet/gateway/main_test.go), ensure [`TestRAGQueryCrossRuntime`](file:///D:/Repos/lancet/gateway/main_test.go) asserts that the serialized `context_snapshot` string written by Rust [`events::checkpoint`](file:///D:/Repos/lancet/engine/src/workflow/events.rs#L101-L122) can be parsed cleanly as valid JSON and successfully inserted into PostgreSQL `context_snapshot JSONB` without formatting errors.

2. **Explicit Per-Test Schema Setup in Gateway Postgres Checkpoint Tests**:
   - *Plan*: [`05-11-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md) (Task 2).
   - *Action*: Adhere strictly to the [`AGENTS.md`](file:///D:/Repos/lancet/AGENTS.md) review convention by creating an isolated PostgreSQL schema per test run (`CREATE SCHEMA test_...; SET search_path TO ...`) before running [`PostgresCheckpointSink`](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L68-L116) assertions.

3. **Document Gateway Keep-Alive and Client Timeout Guidance for 102s Cumulative Ceiling**:
   - *Plan*: [`05-20-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-20-PLAN.md) (Task 2) & [`05-09-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-09-PLAN.md) (Task 1).
   - *Action*: In [`engine/src/workflow/runner.rs`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs) and [`gateway/main.go`](file:///D:/Repos/lancet/gateway/main.go), add docstrings clarifying that the derived 102-second sum is the cumulative component timeout bound, ensuring HTTP client timeouts and proxy buffers (e.g. reverse proxy read timeouts) are configured for $\ge 120\text{s}$.

---

## 5. Risk Assessment

- **Overall Plan Set Risk: LOW**
- **Justification**:
  The 17 gap-closure plans are exceptionally well-architected, highly detailed, and thoroughly defended against subtle regressions. Every major risk area—such as compiler lockouts during trait/mock splitting, Buf code generation overwrites, async deadlocks on BM25 indexes, timer starvation in LLM retries, and cross-runtime gRPC/SSE event framing—has an assigned plan owner, explicit wave dependency, and automated validation command.

---

## 6. Plan Coverage & Cross-Plan Findings

| Wave | Plan ID | Primary Focus & Covered Files | Dependencies & Handoffs |
| :--- | :--- | :--- | :--- |
| **Wave 7** | [`05-08-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md) | Production 5-node builder in [`engine/src/main.rs`](file:///D:/Repos/lancet/engine/src/main.rs#L1650-L1760); populates all 7 [`WorkflowDependencies`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L111-L135) ports from engine fields. | Foundation for production state machine. |
| **Wave 7** | [`05-12-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-12-PLAN.md) | Historical summary errata and source traceability matrix audit for Phase 05. | Metadata & audit trail integrity. |
| **Wave 8** | [`05-09-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-09-PLAN.md) | Typed `[engine.workflow]` TOML config with `deny_unknown_fields`; node deadlines; drop-guard stream cancellation. | Depends on `05-08`. Establishes timing baseline. |
| **Wave 9** | [`05-13-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-13-PLAN.md) | OpenRouter `/models` capability preflight timeout & single-flight cache; single-retry generation with byte-identical requests. | Depends on `05-09`. Hands off preflight preparation hook to `05-20`. |
| **Wave 10** | [`05-14-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-14-PLAN.md) | Closed [`NodeKind`](file:///D:/Repos/lancet/engine/src/workflow/node.rs) enum; exhaustive runner dispatch; early 8-variant admission limit on reformulation. | Depends on `05-09`, `05-13`. Consumed by `05-10` and `05-16`. |
| **Wave 11** | [`05-17-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-17-PLAN.md) | Additive protobuf fields in [`proto/lancet/v1/lancet.proto`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto); `clean: false` in [`buf.gen.yaml`](file:///D:/Repos/lancet/buf.gen.yaml) protecting [`engine/src/pb/mod.rs`](file:///D:/Repos/lancet/engine/src/pb/mod.rs). | Depends on `05-14`. Hands off generated bindings to `05-23`. |
| **Wave 12** | [`05-23-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-23-PLAN.md) | Immediate Rust compilation repair for exhaustive protobuf literals; Rust wire round-trip tests. | Depends on `05-08`, `05-14`, `05-17`. Unblocks `05-18`. |
| **Wave 13** | [`05-18-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-18-PLAN.md) | Target split: library-owned generic tests ([`engine/src/tests/workflow_phase5.rs`](file:///D:/Repos/lancet/engine/src/lib.rs)) vs binary-owned production tests ([`engine/src/tests/workflow_phase5_production.rs`](file:///D:/Repos/lancet/engine/src/tests.rs)); 18 BM25 fixture migrations. | Depends on `05-08`, `05-09`, `05-14`, `05-17`, `05-23`. |
| **Wave 14** | [`05-15-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-15-PLAN.md) | `#[cfg(test)]` gating on fake workflow ports; async prompt documentation; `graph_weight` inclusion semantics. | Depends on `05-13`, `05-18`. Gates test doubles out of production builds. |
| **Wave 15** | [`05-16-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-16-PLAN.md) | `GRAPH_TIMEOUT`/`GRAPH_DEGRADED` notice merge; $O(1)$ `Arc<RwLock<Arc<Bm25Index>>>` handle snapshot releasing read-guard before `.await`. | Depends on `05-14`, `05-15`, `05-17`, `05-18`, `05-23`. |
| **Wave 16** | [`05-10-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-10-PLAN.md) | Reliable event delivery; atomic terminal CAS; complete 19-field [`WorkflowContext`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L29-L48) snapshot JSON with 8-float embedding digest. | Depends on `05-08`, `05-09`, `05-13`, `05-14`, `05-16`, `05-18`. |
| **Wave 16** | [`05-21-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-21-PLAN.md) | Type-safe [`VariantProvenanceSource`](file:///D:/Repos/lancet/engine/src/retrieval/fusion.rs#L18) enum; removal of dead `#[serde(default)]` in [`engine/src/retrieval/fusion.rs`](file:///D:/Repos/lancet/engine/src/retrieval/fusion.rs#L33). | Depends on `05-16`, `05-23`. |
| **Wave 17** | [`05-19-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-19-PLAN.md) | Failure-terminal notice propagation in Rust runner and Go SSE without answer chunks or fabricated final responses. | Depends on `05-10`, `05-16`, `05-17`, `05-18`. |
| **Wave 17** | [`05-22-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-22-PLAN.md) | Complete `GraphFactBlock` handoff into [`AssemblePromptNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/assemble_prompt.rs) and [`GenerateAnswerNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/generate.rs); deletion of response-shaped fabrication strings. | Depends on `05-08`, `05-10`, `05-13`, `05-14`, `05-16`, `05-18`, `05-23`. |
| **Wave 17** | [`05-24-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-24-PLAN.md) | Two-pass RRF cross-variant fusion formula auditing, single-variant parity proof, deterministic tie-breaking. | Depends on `05-16`, `05-21`, `05-23`. |
| **Wave 18** | [`05-20-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-20-PLAN.md) | Capability preflight runner bootstrap before node timer starts; paused-clock worst-case timing proof; 4999ms/9999ms boundary regressions. | Depends on `05-13`, `05-14`, `05-16`, `05-18`, `05-19`, `05-22`. |
| **Wave 19** | [`05-11-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-11-PLAN.md) | Go SSE relay, [`TestRAGQueryCrossRuntime`](file:///D:/Repos/lancet/gateway/main_test.go), graph fixture seeding, checkpoint dispatcher lossless drain on close, isolated PostgreSQL schemas. | Depends on `05-08`, `05-09`, `05-10`, `05-16`, `05-17`, `05-18`, `05-19`, `05-20`, `05-22`. |

### Remaining Blockers to Execution
There are **no remaining blockers** preventing the execution of this plan set. Every inter-plan dependency is directed and acyclic, file ownership boundaries are strictly partitioned to avoid merge collisions, and all verification gates are fully automated with exact Cargo and Go test filters. Execution should proceed starting with Wave 7 ([`05-08-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-08-PLAN.md) and [`05-12-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-12-PLAN.md)).


---

## Claude Review

# Cross-AI Plan Review — Phase 05 Refresh (HEAD 4e37c16)

## 1. Summary

This is a materially stronger plan set than a typical gap-closure round: the ownership graph across 05-08…05-24 is acyclic, wave numbers are consistent with `depends_on`, and several load-bearing claims are exact against HEAD rather than approximate. I independently confirmed 05-18's three migration counts (37 `bm25_index` refs, 25 `workflow::ports::Fake*` sites, 18 `RwLock::new(bm25_index…)` constructions in `engine/src/tests.rs`), 05-11's graph-fixture premises (`DOCUMENT_ID`/`CHUNKS` in `engine/src/bin/seed_rag_fixture.rs`, `entities_table`/`entity_edges_table` in `engine/src/db/mod.rs`, and the `vector := make([]float32, 2048); vector[0] = 1` mock at `gateway/main_test.go:2059-2060`), and the real reason 05-18's library-target move is necessary (`use engine::workflow;` at `engine/src/main.rs:38` means `crate::workflow` in the bin resolves to the **lib** copy, built without `cfg(test)`). The `clean: false` fix in 05-17 is a genuine defect repair, not ceremony.

Three problems are serious enough to block clean execution. (a) Deleting `execute_inline_query_rag_remainder` from `main.rs` is asserted by 05-22 but owned by no plan that can edit `main.rs`. (b) 05-13 must migrate roughly eleven models-first `TcpListener` fixtures but names one, and the failure mode is a hang on `server_handle.join()` rather than a red test. (c) 05-24 replaces the shipped single-pass `fuse_variant_candidates` without saying what happens to that function or to the three existing tests that pin its exact provenance semantics. Beyond those, a recurring pattern is guards whose acceptance criteria promise more than the automated check delivers.

## 2. Strengths

- **05-18's migration counts are exact, not estimated.** `rg -c 'bm25_index' engine/src/tests.rs` → 37; `rg -c 'workflow::ports::Fake' engine/src/tests.rs` → 25; `rg -c 'RwLock::new\(bm25_index' engine/src/tests.rs` → 18. All three match `05-18-PLAN.md:83` verbatim, and the guards assert post-migration counts rather than "some".

- **05-18's target split is load-bearing for the correct reason.** `engine/src/main.rs:38` is `use engine::workflow;` — a private root-level `use`, not `mod workflow;` (main.rs declares only `chunker`, `generation`, `graph`, `prompt`, `tests`). So `crate::workflow::ports::Fake*` at `engine/src/tests.rs:7103` resolves to the **library** module, compiled without `cfg(test)` when building the bin test target. Once 05-15 gates the fakes, those 25 sites and `engine/src/tests/workflow_phase5.rs:12` genuinely break. The relocation is required and correctly sequenced before 05-15.

- **05-17's `clean: false` change fixes a real hazard.** `buf.gen.yaml:2` is currently `clean: true`, and hand-written `engine/src/pb/mod.rs` lives inside the configured Rust `out: engine/src/pb`. The pre/post byte-comparison guard at `05-17-PLAN.md:98` is well targeted.

- **05-11's graph fixture is grounded end-to-end.** The mock embedding it must match exists verbatim (`gateway/main_test.go:2059-2060`), the seeding surface exists (`engine/src/db/mod.rs:144,152`), and the seed-score inequality is real: `retrieval::dense::dense_score(distance)` at `engine/src/main.rs:1121` compared against `settings.seed_match_min_score` at `:1123`. It extends the **existing** `TestRAGQueryCrossRuntime` (`gateway/main_test.go:2028`) rather than inventing a parallel harness.

- **05-08's service-field claims are all real.** `LancetServiceImpl` (`engine/src/main.rs:859-870`) has exactly `nodes`, `bm25_index`, `effective_settings`, `generator`, `embedder`, `reranker`, `database`.

- **The 05-10 → 05-22 serialization is a real fix.** Both modify `engine/src/workflow/mod.rs`; 05-22 declares the dependency and sits at wave 17 vs 05-10's 16. I traced 05-08…05-24 and found no cycle and no wave inversion.

- **05-08 Task 2's inline-branch change is safe against its existing callers.** I read all three (`engine/src/tests.rs:7134`, `:7210`, `:7323`). `workflow_retrieve_graph` asserts only fake call counts; `zero_evidence_short_circuits_generation` never reaches the remainder (`runner.rs:260-266`); `nine_variants_are_rejected_before_retrieval` fails at admission. None asserts the fabricated `format!("Answer for {}", …)` from `workflow/mod.rs:212`.

- **05-09's shared-overlay concern is correctly scoped.** `scripts/phase02_live_evidence.py:179` reads `config/config.verify.toml` but extracts only `engine.lancedb_path` (`:193`), so rewriting the timeout values is safe for Phase 02 tooling.

## 3. Concerns

### HIGH-1 — Deleting `execute_inline_query_rag_remainder` is asserted by 05-22 but owned by nobody

`engine/src/main.rs:1234` defines it; `engine/src/main.rs:1742` calls it.

- 05-08 Task 1 (`05-08-PLAN.md:121`) checks only the extracted `query_rag` region: `if ($query -match 'execute_inline_query_rag_remainder') { throw … }`. Removing the *call* satisfies it. 05-08's objective even says "removal **or isolation**" (`05-08-PLAN.md:57`).
- 05-22 Task 2 checks the **whole file**: `if ($main.Contains('execute_inline_query_rag_remainder') …) { throw 'retired inline production remainder remains reachable' }`.
- 05-22's `files_modified` is `assemble_prompt.rs, generate.rs, workflow/mod.rs, tests.rs, workflow_phase5_production.rs` — **`engine/src/main.rs` is absent**.

Mechanism: an executor satisfying 05-08 by isolation leaves 05-22 with a guard it cannot legally satisfy. Secondary: an unreferenced inherent method in the bin crate triggers `dead_code`, which the all-target lint gate restored in Phase 02 (02-14) would surface.

### HIGH-2 — 05-13 must migrate ~11 preflight mocks but names one; the failure mode is a hang

05-13 Task 2 (`05-13-PLAN.md:123`) says update "every existing models-first `TcpListener` fixture … (including `openrouter_effective_usage_limits` …)". `engine/src/generation/tests.rs` has 11 `server_handle.join()` fixtures; the models-first ones are at `:298`, `:406`, `:499`, `:582`, `:742`, `:818`, `:885`, `:947`, `:1013`, `:1080`, `:1241`.

Once 05-13 removes the preflight from `execute_one_call` (`engine/src/generation/openrouter.rs:376`), each blocks on `listener.accept()` for a `/models` connection that never arrives, then on `server_handle.join()`. 05-13's verification runs three named library tests plus `--no-run` — none touches the other ten. Contrast 05-18, which states and asserts its counts.

### HIGH-3 — 05-24 replaces a shipped algorithm without disposing of it or its three pinning tests

`engine/src/retrieval/fusion.rs:80-178` is a **single-pass** accumulator: vector for variant 0 (`:98-114`), then per-variant BM25 (`:117-136`), summed into one `BTreeMap`. 05-24 mandates a **two-pass** design — one `fuse_candidates` per variant, then `fuse_cross_variant_candidates` over the fused lists.

Three existing tests pin current semantics and go unmentioned:
- `cross_variant_provenance_is_bounded` (`engine/src/retrieval/tests.rs:706`) asserts `variant_provenance.len() == 9` — meaningful only under single-pass accumulation.
- `fusion_cross_variant_tracer` (`:657`) asserts lengths 2 and 1.
- `variant_zero_one_variant_matches_existing_scores` (`:677`) compares the two functions.

Under two-pass, per-variant `fuse_candidates` delegates to `fuse_variant_candidates(vector, vec![bm25])` (`fusion.rs:76`), so every inner provenance entry carries `variant_index: 0`; the second pass must re-tag indices for "retained typed provenance" to mean anything. 05-24's verification is two exact filters with no suite gate, and it is silent on whether `fuse_variant_candidates` survives — retaining it while `RetrieveHybrid` stops calling it ships two divergent fusion implementations.

### MEDIUM-1 — 05-09's timeout-ordering guard is vacuously satisfiable

`05-09-PLAN.md:147` compares **file-wide first-occurrence** `IndexOf('cancel.cancel()')` vs `IndexOf('NodeFailed')` over `runner.rs`. Any earlier `cancel.cancel()` (e.g. the closed-sender cancellation 05-10 adds to `WorkflowEventSink`) satisfies it while the timeout path still relies on future-drop alone. Also, `NodeFailed` does not currently appear in `runner.rs` — it uses `events::node_failed` (`:149`, `:193`, `:248`).

### MEDIUM-2 — 05-17's stale-output acceptance criterion has no backing check

Criterion 4 claims "no stale output is silently accepted." The blocks at `:98`/`:99` check field presence, `clean: false`, `mod.rs` byte-identity, **existence** of four files, lint, `git diff --check`, and repeated-generation hashes. Nothing enumerates the output roots. Since `clean: true` → `false` is exactly what makes stale output possible, this criterion most needed a real check.

### MEDIUM-3 — 05-10's snapshot-field guard passes on test-only presence

`if ($source -notmatch field -and $tests -notmatch field) { throw … }` — the `-and` lets a field name appearing **only** in the test file satisfy the guard while `events.rs` still omits it. Given the SC4 gap is that `events.rs:106-115` serializes 7 of 17 fields, the source check should stand alone.

### MEDIUM-4 — Wave-17 retrieval changes are not re-gated by their wave-15/16 owners

05-24 modifies `retrieve.rs` and `fusion.rs`. Neither 05-16's `workflow_phase5_retrieval_snapshot_variants` / `workflow_phase5_bm25_snapshot_releases_lock` nor 05-21's `fusion_variant_provenance_source_is_typed` is rerun by 05-24, and 05-20's nine production filters exclude the 05-16 pair. The `variant_count`/`variant_identities` population 05-16 owns lives in the node body 05-24 rewrites.

### MEDIUM-5 — 05-22 targets caller line numbers that 05-18 relocates

`05-12-PLAN.md` records 05-22 as updating `engine/src/tests.rs:7134`, `:7210`, `:7323`. Those blocks contain `Fake*` references and fall inside the 7103-7807 range 05-18 (wave 13) relocates to `workflow_phase5.rs`, which is not in 05-22's inventory. Impact is limited (those callers need no changes), but 05-22's `$tests.Contains('LlmGenerationFailed')` then depends on an unrelated test carrying that token.

### LOW-1 — 05-16's BM25 impl-region regex is brittle
`impl\s+Bm25RetrievalPort\s+for\s+\w+` won't match generic/lifetime/path-qualified adapter types, and requiring a literal `drop(` fails a correct scope-based release.

### LOW-2 — 05-18's lib registration guard under-specifies the module path
A bare `mod workflow_phase5;` in `lib.rs` resolves to `src/workflow_phase5.rs`, which doesn't exist; a `#[path]` attribute is mandatory. The guard asserts neither it nor `#[cfg(test)]`.

### LOW-3 — No `buf breaking` check despite wire compatibility being 05-17's premise
`buf lint` does not verify tag compatibility.

### LOW-4 — 05-09 doesn't guard `lancedb_path` survival in the shared overlay
`phase02_live_evidence.py:193` depends on it; 05-09 asserts eight values, none of them that key.

### LOW-5 — 05-08's `Some(` heuristic
`Count -lt 7` is satisfiable by seven unrelated `Some(` calls; backed by adjacent field checks, so impact is small.

## 4. Suggestions

1. **(HIGH-1)** Add `engine/src/main.rs` to 05-22's `files_modified` with an explicit action to delete `main.rs:1234-1537` — or move the deletion into 05-08 and make its guard file-scoped so both plans assert the same property. Owner: 05-08 **or** 05-22 (currently neither).
2. **(HIGH-2)** Give 05-13 Task 2 the 05-18 treatment: enumerate the eleven fixtures by name/line, add a count guard (every `server_handle.join()` preceded by a bounded accept timeout), and add one full `cargo test --lib` run so a hang surfaces in the owning wave. Owner: 05-13.
3. **(HIGH-3)** Extend 05-24 to state the disposition of `fuse_variant_candidates` and to update the three pinning tests with the new provenance shape and variant re-tagging rule; add a library-suite run. Owner: 05-24.
4. **(MEDIUM-1)** Rescope 05-09's guard to the timeout branch — extract the `run_node` timeout arm and assert `cancel.cancel()` within that region. Owner: 05-09.
5. **(MEDIUM-2)** Add a directory-inventory assertion to 05-17: enumerate `engine/src/pb/**` and `gateway/proto/**` and fail on any path outside the five-entry allowlist. Owner: 05-17.
6. **(MEDIUM-3)** Require each of the nineteen fields in `events.rs`, keeping the test-file check separate. Owner: 05-10.
7. **(MEDIUM-4)** Add the two 05-16 tests and 05-21's typed-provenance test to 05-24's rerun set (or 05-20's matrix), with a 05-12 validation row. Owner: 05-24.
8. **(MEDIUM-5)** Repoint 05-22's action text and 05-12's errata to `engine/src/tests/workflow_phase5.rs`. Owner: 05-22 + 05-12.
9. **(LOW-1)** Loosen 05-16's regex to `impl\s+Bm25RetrievalPort\s+for\s+[^\{]+\{` and accept a closing scope in place of `drop(`.
10. **(LOW-2)** Assert the full attribute trio in 05-18's guard.
11. **(LOW-3/4)** Add `buf breaking` to 05-17 and a `lancedb_path` retention assertion to 05-09.

## 5. Risk Assessment

**MEDIUM–HIGH.**

The architecture is sound: the iteration 6–9 ownership boundaries (05-08/05-22 production split, 05-17/05-23 schema/compile split, 05-18's introducing `--no-run` gate, 05-10→05-22 serialization) are real fixes, the dependency graph is clean, and where the plans cite counts and symbols they are correct.

Risk is concentrated in three execution-blocking items rather than spread thin. HIGH-1 is a hard stop — 05-22 cannot pass its own guard within its file inventory. HIGH-2 converts into a CI hang, the worst available failure mode, nine waves before any full-suite gate. HIGH-3 rewrites shipped retrieval math in a plan whose verification cannot detect the resulting breakage. All three are cheap to fix at planning time and expensive at wave 17–19. The MEDIUM items are guard-quality issues that would let a partially-correct implementation pass — the same defect class the original verification found (green tests, unwired production).

## 6. Plan Coverage / Cross-Plan Findings

| Plan | Wave | Assessment |
|---|---|---|
| 05-08 | 7 | Service fields verified real (`main.rs:859-870`); inline-branch change safe against its 3 callers. **HIGH-1**, LOW-5. |
| 05-09 | 8 | Overlay rewrite safe for `phase02_live_evidence.py`. **MEDIUM-1**, LOW-4. |
| 05-10 | 16 | Correctly serialized before 05-22. **MEDIUM-3**. |
| 05-11 | 19 | Strongest-grounded plan in the set; fixture, mock vector, seed-score path all verified. No findings. |
| 05-12 | 7 | Frozen-hash guard well constructed. Carries **MEDIUM-5**'s stale references. |
| 05-13 | 9 | **HIGH-2**. Single-flight `OnceCell` design otherwise sound. |
| 05-14 | 10 | Typed `NodeKind` scope clean; no findings. |
| 05-15 | 14 | cfg(test) gating correctly sequenced after 05-18; no findings. |
| 05-16 | 15 | **MEDIUM-4**, LOW-1. Adapter-region rescoping is a genuine improvement over the prior file-wide `clone()` guard. |
| 05-17 | 11 | `clean: false` is a real fix. **MEDIUM-2**, LOW-3. |
| 05-18 | 13 | Counts exact; target rationale correct. LOW-2. |
| 05-19 | 17 | `noticeDTO` reuse matches `gateway/main.go:852`. No findings. |
| 05-20 | 18 | Preflight/node-timer separation and the non-enforced 102 s accepted risk stated honestly. No findings. |
| 05-21 | 16 | Typed provenance scope clean; exposed to **MEDIUM-4** via 05-24. |
| 05-22 | 17 | **HIGH-1**, **MEDIUM-5**. |
| 05-23 | 12 | Compile-repair boundary correctly placed between 05-17 and 05-18. No findings. |
| 05-24 | 17 | **HIGH-3**. |

**Cross-plan themes.** (i) *Guard–criterion mismatch*: 05-17, 05-09, 05-10, 05-08 each state an acceptance criterion stronger than the check enforces — the same shape as the original phase failure. (ii) *Uneven enumeration discipline*: 05-18 and 05-11 name exact counts/constants; 05-13 and 05-24 leave multi-site migrations to executor discovery. (iii) *File-inventory vs. asserted property*: 05-22 asserts a property of a file it cannot edit — worth a mechanical pre-execution check that every `throw`-guarded path appears in some plan's `files_modified`.

**Blockers:** HIGH-1 (05-22 unexecutable as written), HIGH-2 (CI hang with no owning-wave detection), HIGH-3 (no mechanism to detect the breakage it causes). Remaining findings are evidence-quality issues that should be fixed but do not prevent a run.

**Open questions (not asserted as defects).** Whether `fuse_variant_candidates` is intended to survive 05-24; whether 05-13's preflight-removal window (waves 9–18, during which no capability check runs in production) is a deliberate accepted risk — neither plan states it.

The review is saved at `C:\Users\user3\.claude\plans\cross-ai-plan-functional-pelican.md`. No repository files were modified.


---

## Consensus Summary

### Agreed Strengths

Both reviewers found the revised plan set materially stronger and source-grounded in several important areas:

- The 17-plan gap-closure set has a coherent dependency/wave structure and directly targets the verified production gaps rather than reopening completed 05-01 through 05-07 work.
- The protobuf/generated-output repair is concrete: 05-17 addresses the current buf.gen.yaml clean-output hazard and 05-23 repairs exhaustive Rust literals before downstream consumers.
- The 05-18 target split and fake-port/BM25 migration are grounded in exact current call-site counts and are necessary for Rust library/bin test compilation.
- The plans improve production wiring, event streaming, checkpoint serialization, timeout/retry/cancellation behavior, typed retrieval provenance, and cross-runtime validation with concrete source seams.

### Agreed Concerns

Both reviewers raised concerns about executable completeness and the boundaries between plan ownership:

- The plan set needs stronger end-to-end proof that the expanded workflow and checkpoint payload are wired through the actual production path, not merely present in library/test code.
- The 05-10/05-22 snapshot work should preserve a stable, explicitly verified schema across Rust serialization and Go/Postgres ingestion; field completeness and structural compatibility need direct checks.
- The derived per-node timeout budget does not itself enforce a whole-workflow or gateway lifetime bound; the interaction with SSE/gRPC cancellation and long-lived connections needs an explicit decision and test.
- Verification guards should prove the claimed mechanism in the correct implementation region and should not pass from test-only occurrences, stale line references, or broad/vacuous text matches.

### Divergent Views

AgY rated the revised plan set LOW overall risk and considered the remaining issues mostly medium/low design risks. Claude rated it MEDIUM-HIGH and identified three execution blockers that AgY did not elevate:

1. HIGH: 05-22 asserts deleting execute_inline_query_rag_remainder from engine/src/main.rs, but its files_modified list does not include main.rs and 05-08 can legally satisfy its guard by isolating the call. Assign deletion ownership explicitly to 05-08 or 05-22 and align both guards.
2. HIGH: 05-13 must migrate approximately eleven models-first TcpListener fixtures in engine/src/generation/tests.rs, but names only one and does not add a count/full-suite gate; the unhandled fixtures can hang at server_handle.join() after preflight removal.
3. HIGH: 05-24 replaces the shipped single-pass fusion algorithm without specifying the disposition of fuse_variant_candidates or updating the three existing provenance/score pinning tests. Define the two-pass provenance re-tagging contract, update or retire the existing tests, and add a library-suite gate.

These three Claude findings should be treated as the current blockers for planning convergence despite AgY's lower aggregate risk rating.

### Recommended Planning Actions

- Revise 05-08/05-22 to give engine/src/main.rs deletion of execute_inline_query_rag_remainder a single owner, update files_modified, and make the guard and dependency chain agree.
- Revise 05-13 to enumerate and count every models-first fixture, bound every accept, and run the complete relevant library test target so a hang cannot escape the owning wave.
- Revise 05-24 to specify the lifecycle of fuse_variant_candidates, preserve/re-tag variant provenance across the two-pass algorithm, update the three existing fusion tests, and add an executable library-suite check.
- Tighten 05-09, 05-10, 05-17, 05-18, and 05-22 guards so they match the intended implementation region and verify all claimed fields/artifacts rather than relying on broad textual presence or stale line references.

### Overall Assessment

The refreshed review is materially current and source-grounded, but it does not support execution without another targeted planning revision. Claude's three HIGH findings are concrete ownership, hang-safety, and regression-coverage defects; resolve them and re-run the independent review/checker before executing Phase 05.
