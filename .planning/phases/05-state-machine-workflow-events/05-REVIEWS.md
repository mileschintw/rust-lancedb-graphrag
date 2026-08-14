---
phase: 5
scope: gap-closure
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-14T02:38:30.3432085Z
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
---
# Cross-AI Plan Review — Phase 05 Gap Closure

Scope: pending additive plans 05-08 through 05-21. Original plans 05-01 through 05-06 and executed plan 05-07 are baseline context only.

---

## Antigravity Review (gemini-3.7-flash-high, high)

# Phase 05 Gap-Closure Plan Review: Plans 05-08 through 05-21

## 1. Summary

The Phase 05 gap-closure plan suite (`05-08-PLAN.md` through `05-21-PLAN.md`) represents a rigorous, highly disciplined, and comprehensive remediation program that addresses every architectural shortfall, test-isolation flaw, and operational hazard identified in the baseline review. Rather than masking defects with artificial test harnesses or mock boundaries, these 14 additive plans systematically wire the real five-node orchestration pipeline ([`engine/src/main.rs:1716-1753`](file:///D:/Repos/lancet/engine/src/main.rs#L1716-L1753)), establish live configuration and cancellation drop guards ([`engine/src/main.rs:171-189`](file:///D:/Repos/lancet/engine/src/main.rs#L171-L189)), enforce single-allocation sequence ordinals and lossless checkpoint queuing ([`gateway/checkpoint_sink.go:148-247`](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L148-L247)), synchronize the shared Protobuf wire schema ([`proto/lancet/v1/lancet.proto:100-207`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto#L100-L207)), and isolate OpenRouter preflight and retry budgets ([`engine/src/generation/openrouter.rs:289-400`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L289-L400)). The dependency graph across Waves 7 through 17 forms a strictly monotonic, acyclic Directed Acyclic Graph (DAG) with well-separated concerns, zero circularity, and robust verification gates. When executed in sequence, this suite completely closes all 27 previous code review and verification findings (`CR-01`–`CR-08`, `WR-01`–`WR-14`, `IN-01`–`IN-05`) and fulfills the five core Phase 05 roadmap requirements (`ORCH-01` through `ORCH-05`).

---

## 2. Plan-by-Plan Assessment

### 05-08-PLAN.md — Production Five-Node Wiring & Real Adapter Dependencies (Wave 7)
- **Strengths:** Directly dismantles the monolithic fallback bridge [`execute_inline_query_rag_remainder`](file:///D:/Repos/lancet/engine/src/main.rs#L1234-L1537) and replaces it with `build_production_workflow`, registering all five concrete nodes (`ReformulateQueryNode`, `ExtractGraphContextNode`, `RetrieveHybridNode`, `AssemblePromptNode`, `GenerateAnswerNode`) backed by real engine services. Eliminates synthetic evidence fabrication in [`AssemblePromptNode::run`](file:///D:/Repos/lancet/engine/src/workflow/nodes/assemble_prompt.rs#L55-L77) and populates all [`WorkflowContext`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L29-L48) fields from real query execution.
- **Concerns:** High blast radius across [`engine/src/main.rs`](file:///D:/Repos/lancet/engine/src/main.rs) and [`engine/src/workflow/`](file:///D:/Repos/lancet/engine/src/workflow/); requires careful coordination with existing gRPC handlers.
- **Verdict:** **Approved**. Fully closes `CR-02`, `CR-03`, `WR-05`, and `IN-04`.

### 05-09-PLAN.md — Live Workflow Settings, Deadlines & Stream Cancellation (Wave 8)
- **Strengths:** Adds complete TOML deserialization and semantic validation for all seven `[engine.workflow]` configuration keys into [`EngineSettings`](file:///D:/Repos/lancet/engine/src/main.rs#L171-L179) with `deny_unknown_fields`. Wraps the Tonic gRPC response stream in a `GuardedStream` carrying a `DropGuard` on the `CancellationToken`, ensuring client disconnects (`r.Context().Done()`) immediately abort active Tokio tasks and LLM requests.
- **Concerns:** None. Explicitly decouples deterministic sub-second unit tests from wall-clock verification (`config.verify.toml` with 7000ms timeout).
- **Verdict:** **Approved**. Fully closes `CR-01`, `CR-04`, and `SC3`.

### 05-10-PLAN.md — Reliable Event Delivery, Sequence Integrity & Full Snapshots (Wave 14)
- **Strengths:** Replaces fire-and-forget `try_send` in [`WorkflowEventSink::send_event`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L39-L48) with bounded asynchronous dispatch and explicit pending tracking, preventing silent event loss. Fixes the double-increment sequence bug ([`engine/src/workflow/runner.rs:40`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L40) vs [`145`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L145)) by enforcing single sequence allocation inside `wrap_event`. Implements atomic terminal event idempotence (`AtomicBool`) and serializes full execution snapshots in `events::checkpoint`.
- **Concerns:** Depends on Protobuf wire updates from 05-17 and typed nodes from 05-14/05-16. Wave 14 placement correctly satisfies these prerequisites.
- **Verdict:** **Approved**. Fully closes `CR-05`, `WR-03`, and `WR-13`.

### 05-11-PLAN.md — Gateway SSE Stream Hardening & Lossless Checkpoint Backpressure (Wave 17)
- **Strengths:** Eliminates the silent gRPC stream termination bug on receive errors ([`gateway/main.go:730-732`](file:///D:/Repos/lancet/gateway/main.go#L730-L732)) by emitting explicit `stream_error` SSE frames. Guards against nil terminal response panics in [`toQueryRAGResponseDTO`](file:///D:/Repos/lancet/gateway/main.go#L875-L950). Refactors [`CheckpointDispatcher`](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L148-L247) to guarantee full queue draining on `Close()` and synchronous handling of `DispatchPending` overflow items without silent loss. Adds cross-runtime end-to-end integration test `TestRAGQueryCrossRuntime`.
- **Concerns:** Must maintain strict database schema isolation conventions per [`AGENTS.md`](file:///D:/Repos/lancet/AGENTS.md) when testing against PostgreSQL.
- **Verdict:** **Approved**. Fully closes `CR-06`, `CR-07`, `CR-08`, and `WR-12`.

### 05-12-PLAN.md — Additive Traceability Errata & Multi-Source Audit (Wave 7)
- **Strengths:** Strictly preserves historical summary immutability by creating `05-12-TRACEABILITY-ERRATA.md` and asserting byte-for-byte Git blob hashes across all 14 historical baseline files (`05-01` through `05-07`). Corrects historical overclaiming narratives and requirement cross-references without mutating executed records.
- **Concerns:** Purely documentation and verification metadata; zero runtime execution impact.
- **Verdict:** **Approved**. Fully closes `SC5` and traceability defects.

### 05-13-PLAN.md — OpenRouter Preflight Classification, Caching & Generation Retry (Wave 9)
- **Strengths:** Extracts `check_supported_parameters` out of the per-request path ([`engine/src/generation/openrouter.rs:376`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L376)) into a dedicated 5-second deadline with a success-only model capability cache. Reclassifies network transport errors (connect, timeout, reset) as retryable `ProviderError` while preserving parameter rejections as non-retryable `SupportedParameters`. Restricts [`GenerateAnswerNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/generate.rs) to exactly one immediate retry using byte-identical request snapshots.
- **Concerns:** None. Coordinates cleanly with 05-20 for preflight runner bootstrap timing.
- **Verdict:** **Approved**. Fully closes `WR-02` and `WR-04`.

### 05-14-PLAN.md — Typed NodeKind Dispatch & Early Variant Admission (Wave 10)
- **Strengths:** Replaces stringly pattern matching across runner dispatch ([`engine/src/workflow/runner.rs:104-113`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L104-L113)) with an exhaustive, closed `NodeKind` enum (`ReformulateQuery`, `ExtractGraphContext`, `RetrieveHybrid`, `AssemblePrompt`, `GenerateAnswer`). Moves the `variants.len() <= 8` boundary check to occur immediately upon reformulation completion, preventing unnecessary downstream retrieval or LLM fanout.
- **Concerns:** None. Keeps public wire event strings intact while hardening internal Rust dispatch.
- **Verdict:** **Approved**. Fully closes `WR-01` and `IN-01`.

### 05-15-PLAN.md — Async Prompt API Contract & cfg(test) Fake-Port Gates (Wave 12)
- **Strengths:** Fully documents public asynchronous prompt APIs ([`engine/src/prompt.rs`](file:///D:/Repos/lancet/engine/src/prompt.rs)), establishes formal semantic tests for `graph_weight = 0.0` (complete graph exclusion) versus positive values, removes public blocking synchronous helpers, and places all test doubles (`FakeQueryReformulator`, `FakeGraphQueryPort`, etc.) in [`engine/src/workflow/ports.rs`](file:///D:/Repos/lancet/engine/src/workflow/ports.rs) strictly behind `#[cfg(test)]`.
- **Concerns:** Relies on 05-18 to establish the library-target test compilation seam first.
- **Verdict:** **Approved**. Fully closes `WR-10`, `WR-11`, and test double pollution.

### 05-16-PLAN.md — Graph Notice Codes, Retrieval Provenance & BM25 Snapshotting (Wave 13)
- **Strengths:** Standardizes graph notices to machine-readable `GRAPH_TIMEOUT` and `GRAPH_DEGRADED` codes, implementing append/merge logic that preserves prior notices across subsequent node failures. Exposes multi-variant provenance (`variant_count`, `variant_identities`) in `RetrievalSnapshot`. Solves the `RwLock` concurrency hazard in BM25 retrieval by taking an owned immutable snapshot before any `.await` point, preventing blocked document ingestion workers.
- **Concerns:** Depends on Protobuf field updates from 05-17.
- **Verdict:** **Approved**. Fully closes `WR-06`, `WR-07`, `WR-08`, `WR-09`, and `WR-14`.

### 05-17-PLAN.md — Wire Schema Sync: Retrieval Provenance & Terminal Notices (Wave 11)
- **Strengths:** Extends [`proto/lancet/v1/lancet.proto`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto) in a backward- and wire-compatible manner by adding `variant_count` (tag 10) and `variant_identities` (tag 11) to `RetrievalSnapshot`, and `notices` (tag 6) to `WorkflowCompletedEvent`. Executes `buf generate` and updates all Rust prost/tonic and Go protobuf struct literals across the repository.
- **Concerns:** Any manual drift between `.proto` and generated files will break CI; automated round-trip assertions in both Rust and Go mitigate this risk.
- **Verdict:** **Approved**. Fully closes protobuf synchronization gaps.

### 05-18-PLAN.md — Library-Target Phase 5 Test Module Migration (Wave 11)
- **Strengths:** Moves `mod workflow_phase5;` from the binary root [`engine/src/tests.rs:11`](file:///D:/Repos/lancet/engine/src/tests.rs#L11) into library scope [`engine/src/lib.rs`](file:///D:/Repos/lancet/engine/src/lib.rs) under `#[cfg(test)]`. This resolves the classic Rust visibility constraint where `#[cfg(test)]` items in `ports.rs` are inaccessible to binary integration tests, ensuring tests run cleanly under `cargo test --lib`.
- **Concerns:** None.
- **Verdict:** **Approved**. Fully enables clean `#[cfg(test)]` compilation for 05-15.

### 05-19-PLAN.md — Failure-Terminal Notice Preservation through Rust & Go SSE (Wave 15)
- **Strengths:** Ensures that when a workflow fails downstream, all accumulated notices (such as `GRAPH_TIMEOUT` or `GRAPH_DEGRADED`) are preserved on the terminal `WorkflowCompletedEvent` and serialized through Go raw SSE without emitting misleading `answer_chunk` or `final_answer` frames.
- **Concerns:** None. Verifies both Rust runner event streams and Go HTTP/SSE wire output.
- **Verdict:** **Approved**. Fully completes failure-mode observability under `WR-07`.

### 05-20-PLAN.md — Preflight Bootstrap Timing & 102s Workflow Budget Proof (Wave 16)
- **Strengths:** Introduces a `Node::prepare` lifecycle hook that executes capability preflight before the 65-second `GenerateAnswer` timer starts. Provides deterministic mathematical proofs and boundary tests demonstrating that the worst-case cumulative workflow latency across all 5 nodes fits within a 102-second budget. Adds 4999ms boundary regressions and bounded happy-path drain tests.
- **Concerns:** None.
- **Verdict:** **Approved**. Fully closes timeout coupling and latency budget ambiguity.

### 05-21-PLAN.md — Typed Fusion Provenance Enum & Serde Cleanup (Wave 14)
- **Strengths:** Replaces stringly `"vector"` / `"bm25"` matches in [`engine/src/retrieval/fusion.rs:145-153`](file:///D:/Repos/lancet/engine/src/retrieval/fusion.rs#L145-L153) with a strongly typed `VariantProvenanceSource` enum. Cleans up dead `#[serde(default)]` annotations on serialize-only structs like `FusedCandidate`.
- **Concerns:** None.
- **Verdict:** **Approved**. Fully closes `IN-02` and `IN-03`.

---

## 3. Concerns (Categorized by Severity)

### HIGH Severity
*None.* The 14-plan gap-closure design eliminates all previously identified architectural, data-loss, and deadlocking hazards.

### MEDIUM Severity

- **Protobuf Generation Precedence & Build Ordering**
  - **Source Evidence:** [`proto/lancet/v1/lancet.proto:100-207`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto#L100-L207), [`engine/src/pb/lancet/v1/lancet.v1.rs`](file:///D:/Repos/lancet/engine/src/pb/lancet/v1/lancet.v1.rs), [`gateway/proto/lancet/v1/lancet.pb.go`](file:///D:/Repos/lancet/gateway/proto/lancet/v1/lancet.pb.go).
  - **Mechanism:** Plan 05-17 introduces new Protobuf fields (`variant_count = 10`, `variant_identities = 11`, `notices = 6`). If downstream plans (05-10, 05-16, 05-19) are executed in a workspace where `buf generate` has not run or where generated code is out of sync, compilation will fail with missing struct fields.
  - **Mitigation:** The plan DAG correctly places 05-17 in Wave 11, strictly prior to 05-16 (Wave 13), 05-10 (Wave 14), and 05-19 (Wave 15). Verification tasks in 05-17 explicitly include Git diff and cross-runtime round-trip tests to ensure generated files are committed before downstream tasks execute.

- **PostgreSQL Test Schema Isolation Convention Enforcement**
  - **Source Evidence:** [`AGENTS.md:17-23`](file:///D:/Repos/lancet/AGENTS.md#L17-L23), [`gateway/main_test.go`](file:///D:/Repos/lancet/gateway/main_test.go), [`gateway/checkpoint_sink.go`](file:///D:/Repos/lancet/gateway/checkpoint_sink.go).
  - **Mechanism:** Plan 05-11 introduces cross-runtime and checkpoint persistence tests. If integration tests executing against PostgreSQL fail to use isolated per-test schemas or if count queries do not fail fatally on error (`t.Fatalf`), concurrent test execution could cause false-positive test passes or flaky state pollution.
  - **Mitigation:** The acceptance criteria for 05-11 require explicit schema isolation and fatal assertion checks on all database fixtures.

### LOW Severity

- **Transient vs Hard Failure Classification Granularity**
  - **Source Evidence:** [`engine/src/generation/openrouter.rs:297-312`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L297-L312).
  - **Mechanism:** In 05-13, HTTP status codes 429 and 5xx from OpenRouter are classified as transient and retryable, whereas 400/422 are classified as non-retryable `SupportedParameters` or `InvalidRequest`. Unhandled edge cases (such as 401 Unauthorized or 403 Forbidden) must not trigger infinite or wasteful retries.
  - **Mitigation:** The single-retry limit (`max_retries = 1`) and explicit HTTP status match arms prevent retry loops on authentication or permission errors.

---

## 4. Suggestions

1. **Explicit Buf Generation Preflight Assertion in CI:**
   Add a repository-level check in CI that runs `buf generate` and validates `git diff --exit-code` across `engine/src/pb/` and `gateway/proto/` to permanently prevent checked-in binding drift.
2. **Schema-Isolation Linter for Go Gateway Tests:**
   While `AGENTS.md` notes that test database schema isolation is a review convention, adding a lightweight test helper in Go (e.g. `NewIsolatedTestDB(t *testing.T)`) will guarantee compliance with `t.Fatalf` assertions.
3. **Rust Doc-Test Coverage for Public Prompt APIs:**
   In 05-15, include `/// ```rust` doc-tests in `pack_evidence_and_graph_prompt` to ensure rustdoc examples compile directly as part of `cargo test --doc`.

---

## 5. Coverage Assessment

The 14 gap-closure plans comprehensively map to and resolve all historical review findings and phase requirements:

| Finding / Requirement | Description | Resolving Plan(s) | Status |
|---|---|---|---|
| **CR-01 / SC3** | Dead `[engine.workflow]` settings & unparsed TOML | **05-09** | **Closed** |
| **CR-02 / SC1** | Single-node runner registration & inline remainder | **05-08** | **Closed** |
| **CR-03** | Synthetic evidence fabrication in AssemblePrompt | **05-08** | **Closed** |
| **CR-04** | Uncancelled gRPC stream tokens on client disconnect | **05-09** | **Closed** |
| **CR-05 / SC2** | Silent event loss via unhandled `try_send` | **05-10** | **Closed** |
| **CR-06** | Gateway panic on nil terminal gRPC response | **05-11** | **Closed** |
| **CR-07** | Gateway swallows gRPC stream errors after headers | **05-11** | **Closed** |
| **CR-08 / SC4** | Loss of `DispatchPending` checkpoints on dispatcher close | **05-11** | **Closed** |
| **WR-01** | Late validation of reformulation variant counts | **05-14** | **Closed** |
| **WR-02** | Hardcoded `NodeFailed.retryable` booleans | **05-13, 05-10** | **Closed** |
| **WR-03** | Sequence ordinal double-increment in checkpoints | **05-10** | **Closed** |
| **WR-04** | Capability preflight transport failures mapped as hard errors | **05-13** | **Closed** |
| **WR-05** | Inline bridge coupling in `main.rs` | **05-08** | **Closed** |
| **WR-06** | Stringly graph error categorization | **05-16** | **Closed** |
| **WR-07** | Overwritten notices & dropped failure terminal notices | **05-16, 05-19** | **Closed** |
| **WR-08 / WR-09** | Missing variant provenance in `RetrievalSnapshot` | **05-16, 05-17** | **Closed** |
| **WR-10 / WR-11** | Undocumented prompt APIs & blocking sync wrappers | **05-15** | **Closed** |
| **WR-12** | Indefinite checkpoint retention policy clarity | **05-11, 05-12** | **Closed** |
| **WR-13** | Late cancellation / terminal event race | **05-10** | **Closed** |
| **WR-14** | BM25 `RwLockReadGuard` held across `.await` | **05-16** | **Closed** |
| **IN-01** | Stringly node dispatch in runner | **05-14** | **Closed** |
| **IN-02 / IN-03** | Stringly source matching & dead serde attributes in fusion | **05-21** | **Closed** |
| **IN-04** | Empty `WorkflowDependencies` struct | **05-08** | **Closed** |
| **IN-05** | Missing library-target Phase 5 test module | **05-18** | **Closed** |
| **ORCH-01** | Fixed five-node state machine execution | **05-08, 05-14, 05-16** | **Closed** |
| **ORCH-02** | Typed lifecycle, answer, completion & error events | **05-08, 05-10, 05-13, 05-19** | **Closed** |
| **ORCH-03** | Cancellation, timeout, retry & graph degradation | **05-09, 05-13, 05-16, 05-20** | **Closed** |
| **ORCH-04** | Atomic checkpoints & full execution snapshots | **05-10, 05-11, 05-16, 05-17** | **Closed** |
| **ORCH-05** | Pass-through query reformulation port contract | **05-08, 05-12, 05-14** | **Closed** |

---

## 6. Risk Assessment

- **Overall Rating:** **LOW**
- **Justification:** The gap-closure plan suite exhibits exceptional engineering rigor. Each of the 14 plans isolates a specific, bounded architectural seam with explicit must-have invariants, comprehensive threat modeling (STRIDE), exact cargo/go test registration assertions, and reversibility classifications. Wave ordering is strictly causal and acyclic. The suite preserves execution history immutability while delivering complete, verified production behavior across both the Rust engine and Go gateway runtimes. Execution may proceed with high confidence.


---

## Claude Review (opus, high)

# Cross-AI Gap-Closure Plan Review — Phase 05 (05-08 … 05-21)

*Repository read at `D:\Repos\lancet`, branch `main`, HEAD `16bda3f`. No files were edited and no plan file was written — output is the review only, per the request.*

---

## 1. Summary

This is an unusually well-grounded gap-closure set. I spot-checked the plans' factual claims against source and they hold up: `[engine.workflow]` really is dead configuration (`config/config.toml:11-18` defines seven keys; the only Rust consumer is a text-scan at `engine/src/tests.rs:260-290`, and no `WorkflowSettings` type exists), production really does register one node and delegate to the pre-existing monolith (`engine/src/main.rs:1716-1717`, `:1742-1746`), OpenRouter preflight really is inside the per-attempt body with no deadline and no cache (`engine/src/generation/openrouter.rs:376` calling `:290`), checkpoint JSON really is partial (`engine/src/workflow/events.rs:106-115` serializes 7 of 18 context fields), and 05-12's fourteen frozen blob hashes all verify byte-for-byte against `git rev-parse HEAD:<path>`. The wave DAG is mostly sound and the `--lib`/`--bin` split I initially suspected of being broken resolves correctly on inspection (05-13's and 05-17's library tests live in `generation/tests.rs` / `retrieval/tests.rs`, which `engine/src/lib.rs` already exports; 05-10 reaches 05-18 transitively through 05-15).

The problem is not design quality — it is that two structural defects let the whole set execute to completion with every automated gate green while the phase goal remains unmet. First, **graph facts still never reach the model**: `assemble_prompt.rs:92` passes `&[]` for graph facts, `generate.rs:53-56` constructs `GenerationRequest::new(question, evidence)` leaving `graph_facts: Vec::new()` (`generation/mod.rs:396`), and no plan changes the `GraphQueryPort` return type (`ports.rs:44`, `Result<String, NodeError>`), adds a typed carrier to `WorkflowContext`, or touches `GenerationRequest.graph_facts` — so ORCH-01's graph-augmented answer path can be "fully wired" with D-06 and D-09 satisfied and zero graph evidence on the wire. Second, **05-18 destroys 05-08's and 05-16's production proofs**: those plans put the production builder and BM25 adapter in `engine/src/main.rs` (bin-only, method on `LancetServiceImpl` at `main.rs:859`) and their tests in `engine/src/tests/workflow_phase5.rs`, which 05-18 then moves to the library target where bin items are unreachable. Because 05-08's guard runs at wave 7 and nothing re-checks it after wave 11, the phase can finish with its production-reachability evidence deleted and the ledger reporting closure.

---

## 2. Plan-by-plan assessment

### 05-08 — Production five-node wiring, real adapters, WorkflowContext population *(wave 7)*
**Verdict: closes the headline gap, but with two exploitable holes and one downstream collision.**

**Strengths.** The Task 1 guard is the strongest in the set: it extracts the `query_rag` and `build_production_workflow` regions from `main.rs`, requires `self.embedder`/`self.database`/`self.bm25_index`/`self.reranker`/`self.generator` (all real fields — verified at `main.rs:859-870`), requires ≥7 `Some(` slots against the seven-field `WorkflowDependencies` (`workflow/mod.rs:111-120`), counts exactly five `add_node` calls, asserts positional D-06 ordering, rejects `Fake*` references, and rejects `execute_inline_query_rag_remainder` — a function that genuinely exists at `main.rs:1234`. This is a guard that cannot be satisfied by a library-only change.

**Concerns.**
- Task 2's forbidden-behavior list ("must not fabricate evidence text", "no production call path reaches the sink-less inline monolith or the test-only prompt-generation bridge") is prose only. Its sole verification is `cargo test --exact workflow_phase5_production_context_population`, whose contents are unspecified. The fabrication branch is concrete and still present: `assemble_prompt.rs:62-75` synthesizes `document_id: format!("doc_{}", chunk_id)` and `text: format!("Content of chunk {}", chunk_id)`; `workflow/mod.rs:212` fabricates `format!("Answer for {}", ctx.original_query)`. Task 1 shows exactly how to guard this at source level; Task 2 doesn't.
- Graph-fact delivery (see HIGH-1 below).
- `self.nodes` (`main.rs:863`), the LanceDB table `DenseRetriever` is built from (`main.rs:1293`), is not in the required-fields list, so the dense adapter's real backing store is unasserted.

### 05-09 — Live workflow settings, real-I/O deadlines, stream-owned cancellation *(wave 8)*
**Verdict: the semantic half closes; the live wall-clock proof is not executable as written.**

**Strengths.** The seven keys and the asserted production values (5000/10000/10000/4000/15000/2000/65000) match `config/config.toml:11-18` and `config/config.example.toml` exactly. The `deny_unknown_fields` requirement follows an established in-repo precedent (`generation/mod.rs:47`, `graph/extraction.rs:20`). The stream-drop cancellation design is the right fix for `main.rs:1706` — the token is created and never cancelled. The D-17 arithmetic (30s per attempt vs. 65s node budget) is kept correctly separate.

**Concerns.** `config/config.verify.toml` currently sets `generation_timeout_secs = 1`; 05-09 correctly claims ownership and raises it to 30. But it keeps the other overlay values (`reformulate_timeout_ms = 50`, `query_embedding_timeout_ms = 100`, `retrieve_timeout_ms = 100`, `graph_operation_timeout_ms = 40`, `graph_node_timeout_ms = 150`, `prompt_timeout_ms = 20`) untouched while requiring `workflow_phase5_config_verify_generation_timeout` to "load the committed `config/config.verify.toml`, start a running slow provider/engine harness" and reach `GenerateAnswer`. Nothing currently loads that file at runtime — `engine/src/tests.rs:265` only text-scans it — so there is no precedent to lean on, and a real five-node run against real LanceDB/embedding I/O will hit `Timeout` at `ExtractGraphContext` (150 ms) or `RetrieveHybrid` (100 ms) long before generation. See MEDIUM-1.

### 05-10 — Reliable typed event delivery, terminal idempotence, sequence integrity, full snapshots *(wave 14)*
**Verdict: closes as specified.** Every claim verifies. `send_event` drops events silently via `try_send` on a 100-slot channel (`runner.rs:47`, `main.rs:1703`). `emit_terminal_once` (`runner.rs:274`) has no guard despite its name. The double-increment is real: `next_sequence_ordinal()` returns N and `send_event` then allocates N+1 for the envelope, so the outer stream skips an ordinal at every checkpoint (`runner.rs:145-146`, `events.rs:40-52`). The 18-field checkpoint list is a strict superset of the 7 fields serialized today (`events.rs:106-115`). Dependency chain to the library target is correct via 05-15 → 05-18.

### 05-11 — Real engine-to-gateway SSE and lossless checkpoint dispatch *(wave 17)*
**Verdict: closes as specified, behind a guard weak enough to pass on the wrong code.**

**Strengths.** The plan reuses a genuinely existing harness: `TestRAGQueryCrossRuntime` at `gateway/main_test.go:2028` already builds the engine (`:2161`), seeds a fixture (`:2182`), and stands up a mock OpenRouter that enforces the strict JSON-schema contract (`:2109`), single-input embedding (`:2052`, i.e. D-08 variant-zero), and dense+lexical evidence markers (`:2115`). The gaps it targets are real: `node_failed` SSE omits `retryable` (`gateway/main.go:789-795`) and the receive loop breaks silently on error (`:730-732`), which today looks identical to a clean EOF.

**Concerns.** The Task 1 guard is file-scoped (`Get-Content 'gateway/main_test.go' -Raw` then `.Contains(...)`), not function-scoped. Eleven of its sixteen needles already exist elsewhere in the file today (`exec.Command` ×6, `httptest.NewRequest` ×33, `"/rag/query"` ×14, `parseSSEEvents` ×3, `node_started` ×2, `ReformulateQuery` ×2, plus `final_answer` and `workflow_completed`). The five new node names could be added to any unrelated fake-stream test and the guard passes while `TestRAGQueryCrossRuntime` asserts nothing new.

### 05-12 — Traceability errata and source coverage audit *(wave 7)*
**Verdict: closes as specified; one stale embedded artifact and one over-broad guard.**

**Strengths.** All fourteen frozen blob hashes verify against both `git rev-parse HEAD:<path>` and `git hash-object` — I checked every one. The preservation-guard design (hash + staged + unstaged + `git diff --check`) is genuinely machine-checkable, and the "additive errata, never rewrite history" rule is the right call.

**Concerns.** The embedded **Multi-source coverage audit** (lines 111-126) maps GOAL/REQ/RESEARCH/CONTEXT rows only to 05-08 … 05-13, while the action text at line 157 instructs mapping 05-14 … 05-21 and the plan says to "Include the source-audit and gap-disposition tables from this plan." Executing literally reproduces a matrix that is stale by eight plans. The gap-disposition table (lines 131-148) likewise has no row for WR-10, WR-11, IN-02, IN-03, or IN-05 — those appear only in the prose action. Separately, the wave-7 guard runs `git diff --check` unscoped over the whole worktree while 05-08 is executing in the same wave against `engine/src/main.rs`.

### 05-13 — OpenRouter preflight classification, successful-only caching, bounded retry *(wave 9)*
**Verdict: closes as specified. The most accurately-targeted plan in the set.** Every claim checks out against `engine/src/generation/openrouter.rs`: preflight is called unconditionally inside `execute_one_call` (`:376`), has no timeout and no cache (`:290-369`), and maps *all* transport failures — including timeouts and resets — to `GenerationErrorKind::SupportedParameters` (`:297-302`), which `generate.rs:73-76` treats as non-retryable. That is precisely the bug: a transient network blip during preflight is currently classified as a permanent capability failure and suppresses D-12's mandated retry. The `--bin`/`--lib` split is correct (workflow tests bin, `openrouter_*` tests in the lib-exported `generation` module).

### 05-14 — Exhaustive typed NodeKind dispatch, early reformulation admission *(wave 10)*
**Verdict: closes as specified.** `timeout_for_node` is a string match with a silent 5000 ms fallback for unknown names (`runner.rs:104-113`), and `run_node`'s answer-chunk decision is `if name == "GenerateAnswer"` (`:142`). The nine-variant check fires *after* `run_node` has already emitted `NodeCompleted` and a checkpoint (`:180-201`), so today a node both completes and fails — moving admission to the successful-ReformulateQuery boundary is the correct fix.

### 05-15 — Prompt API contract and cfg(test)-only workflow fakes *(wave 12)*
**Verdict: closes as specified, with one omission.** The six named ports are all currently public and ungated (`workflow/ports.rs:69,90,142,194,247,320`; the only `cfg(test)` in that file is none). Both sync helpers are public (`prompt.rs:234`, `:255`). But `FakeGenerator` is equally public and ungated at `generation/mod.rs:467-512`, is imported by the phase test module (`tests/workflow_phase5.rs:12`), and is excluded from 05-15's list; 05-20 further entrenches it ("does not break FakeGenerator"). The test-double hygiene finding therefore closes for ports and stays open for generators.

### 05-16 — Graph notice merge, variant provenance, immutable BM25 snapshotting *(wave 13)*
**Verdict: closes the notice/provenance gaps; the BM25 fix carries a performance risk and a target collision.**

**Strengths.** The notice defect is exact: `graph_context.rs:116-125` emits `code: "GRAPH_TIMEOUT"` for *both* timeout and logical degradation, varying only the message — so `GRAPH_DEGRADED` is unreachable and code-based client logic cannot distinguish them. `ctx.notices.push` is append-only there, but `update_from_model_output` (`workflow/mod.rs:94-107`) also pushes, and nothing in the terminal path preserves them on failure — 05-19 picks that up. The lock-across-await is real: `main.rs:1311-1314` holds `bm25_guard` across `.retrieve(...).await`.

**Concerns.** "acquire the RwLock only long enough to clone/copy the index data needed by the query" invites an O(corpus) deep copy per request — `Bm25Index` derives `Clone` and owns `Vec<IndexedDocument>` plus a `HashMap` (`retrieval/bm25.rs:113-119`). And `workflow_phase5_bm25_snapshot_releases_lock` is verified with `cargo test --lib` while Task 2 modifies the production adapter in `engine/src/main.rs` — same bin/lib collision as 05-08.

### 05-17 — Shared protobuf provenance and failure-terminal notice fields *(wave 11)*
**Verdict: closes as specified.** Additive tags 10/11 on `RetrievalSnapshot` and tag 6 on `WorkflowCompletedEvent`, no renumbering, `buf generate` from `buf.gen.yaml`, all four checked-in bindings regenerated, and cross-runtime round-trip tests in both runtimes. The `--lib` Rust test lands in `engine/src/retrieval/tests.rs`, already inside the library target (`lib.rs` exports `pub mod retrieval`), so it is executable at wave 11 independent of 05-18.

### 05-18 — Library-target Phase 5 tests and cfg(test) fake-port seam *(wave 11)*
**Verdict: structurally conflicts with 05-08 and 05-16. Do not execute as written.**

The move itself is feasible against *today's* file — `tests/workflow_phase5.rs` uses only `engine::` paths and contains zero `crate::` references, and `lib.rs:1` already has `extern crate self as engine;`. But by wave 11 the file will also hold four production tests from 05-08, two from 05-09, two from 05-13/05-14, and one from 05-16, all of which reach into `engine/src/main.rs`. See HIGH-2.

### 05-19 — Failure-terminal notice preservation through Go SSE *(wave 15)*
**Verdict: closes as specified.** Correctly depends on 05-17 for the generated `WorkflowCompletedEvent.notices` field, and correctly identifies that `emit_terminal_once`'s failure arm passes `None` for the response and no notices at all (`runner.rs:294-301`), so every accumulated notice is dropped on failure today. The gateway side maps cleanly onto the existing `noticeDTO` (`gateway/main.go:836`, `:900`).

### 05-20 — Preflight bootstrap timing, worst-case retry budget, bounded tests *(wave 16)*
**Verdict: closes as specified; one sub-finding left partly open.** The timing derivation is arithmetically sound and consistent with the committed config: 5000 + (5000 + 15000 + 10000 + 2000 + 65000) = 102000, with the graph node counted once at 15000 (the 10000 embedding and 4000 graph-operation deadlines nest inside it, 14000 ≤ 15000). Hoisting preflight out of the node timer is the right structural answer to D-17's slack question. However IN-05 names *two* tests — `workflow_phase5_reformulate_timeout_five_seconds` (`tests/workflow_phase5.rs:311`) and `workflow_phase5_retrieve_timeout_ten_seconds` (`:377`) — and 05-20 adds a pre-deadline assertion only for reformulate.

### 05-21 — Typed fusion provenance and review cleanup guards *(wave 14)*
**Verdict: closes as specified.** Both findings verify exactly: `#[serde(default)]` on a `Serialize`-only derive is inert (`retrieval/fusion.rs:25-34`), and the enum `Source` (`:180-184`) is stringified on the way in and then compared as `p.source == "vector"` on the way out (`:130-146`), where a typo silently falls through to `unwrap_or`. Both files are in the library target, so the `--lib` verification is executable at wave 14.

---

## 3. Concerns

### HIGH-1 — Graph facts still never reach the model; the plans specify the outcome in prose but change nothing that could deliver it
**Evidence.** `engine/src/workflow/nodes/assemble_prompt.rs:89-97` calls `pack_evidence_and_graph_prompt(&ctx.original_query, &evidence, &[], 1.0, …)` — a literal empty graph-fact slice. `engine/src/workflow/nodes/generate.rs:53-56` builds `GenerationRequest::new(ctx.original_query.clone(), ctx.evidence_blocks.clone())`, and `GenerationRequest::new` defaults `graph_facts: Vec::new()` (`engine/src/generation/mod.rs:396`). `ctx.assembled_prompt` is never read by `GenerateAnswerNode` at all; the *actual* outbound prompt is re-packed inside the adapter from `request.evidence` and `request.graph_facts` (`engine/src/generation/openrouter.rs:384-392`). The carrier is stringly all the way down: `GraphQueryPort::query_graph` returns `Result<String, NodeError>` (`engine/src/workflow/ports.rs:44`) and `WorkflowContext.graph_context` is a `String` (`engine/src/workflow/mod.rs:36`).

**Why the plans don't close it.** 05-08 Task 2 asserts "AssemblePrompt must consume real evidence and graph context" and criterion "The prompt contains the real evidence blocks and graph facts" — but 05-08's `files_modified` adds no type change, its automated verification is one unnamed-content test, and no plan in 05-08 … 05-21 mentions `graph_facts`, `graph_weight`, or `GraphFactBlock` on the node path (05-15 documents the *helper's* `graph_weight` semantics in isolation; that is the only hit). 05-10's enumerated 18-field checkpoint list keeps `graph_context` and adds no typed graph-fact field, confirming no such carrier is planned.

**Failure mode.** Every 05-08 gate passes (five nodes registered in D-06 order, real adapters, non-empty `graph_context`, `GRAPH_DEGRADED` notices merging per 05-16, `variant_identities` populated per 05-17), the cross-runtime test passes (it asserts `DENSE_FIXTURE_MARKER` and `LEXICAL_FIXTURE_IDENTIFIER_2026` only — `gateway/main_test.go:2115`), and the model receives zero graph facts. ORCH-01's graph-augmented state machine ships as a chunk-only RAG path with graph telemetry attached.

### HIGH-2 — 05-18 makes 05-08's and 05-16's production tests uncompilable, and no gate re-checks them
**Evidence.** 05-08's guard extracts `fn build_production_workflow` from `engine/src/main.rs` and requires it to reference `self.embedder`, `self.database`, `self.bm25_index`, `self.reranker`, `self.generator` — fields of `LancetServiceImpl`, declared at `engine/src/main.rs:859-870` in the **binary** target. `engine/src/lib.rs:1-13` exports `client`, `db`, `generation`, `graph`, `pb`, `prompt`, `rerank`, `retrieval`, `workflow` — `main.rs` is not part of the library crate. 05-08's four tests (`workflow_phase5_production_five_node`, `…_production_dependencies_are_real`, `…_production_context_population`, `…_production_reachability`) live in `engine/src/tests/workflow_phase5.rs` and are verified with `cargo test --bin engine`. 05-18 then registers that exact file under `lib.rs` cfg(test) and asserts `engine/src/tests.rs` contains no `mod workflow_phase5;` (its Task 2 guard regex is explicit about this). 05-16 Task 2 repeats the pattern: it modifies the `main.rs` BM25 adapter but verifies `workflow_phase5_bm25_snapshot_releases_lock` with `cargo test --lib`.

**Failure mode.** Either 05-18 fails to compile at wave 11, or it "succeeds" by dropping the production tests. 05-18's own verification only probes `workflow_phase5_happy_path` and `workflow_phase5_library_target_fake_ports_compile` — neither would notice. 05-08's guard ran at wave 7 and is never re-run, so the phase can end with the production-reachability proof deleted and every gate green.

### MEDIUM-1 — 05-09's live overlay proof is unreachable with the values 05-09 commits
`config/config.verify.toml` currently carries `reformulate_timeout_ms = 50`, `query_embedding_timeout_ms = 100`, `retrieve_timeout_ms = 100`, `graph_operation_timeout_ms = 40`, `graph_node_timeout_ms = 150`, `prompt_timeout_ms = 20`. 05-09 changes only `generation_timeout_secs` (1 → 30) and retains 7000 for the node budget, explicitly keeping the rest. A live harness that must "start a running slow provider/engine harness" and observe a `Timeout` "near 7000ms" has to traverse `ReformulateQuery` → `ExtractGraphContext` → `RetrieveHybrid` → `AssemblePrompt` under 50/150/100/20 ms of real I/O first. Since nothing loads this file today (`engine/src/tests.rs:265` text-scans it), there is no working precedent to inherit.

### MEDIUM-2 — 05-08's anti-fabrication contract has no machine check
`assemble_prompt.rs:62-75` fabricates `document_id`, `title: Some("Document")`, `section_path: Some("Root")`, and `text: format!("Content of chunk {}", chunk_id)`; `workflow/mod.rs:210-218` fabricates `format!("Answer for {}", ctx.original_query)` with `answer_basis = Retrieval`. 05-08 Task 2 forbids both in prose and verifies with one test whose assertions are unspecified. Compare Task 1, which does have a source-level regex guard for the analogous requirement.

### MEDIUM-3 — 05-11's cross-runtime guard cannot distinguish the real harness from a fake one
File-scoped `.Contains` over `gateway/main_test.go`; 11/16 needles already present today (counts in §2). The plan's own text — "must fail if it only observes a library or fake stream" — has no corresponding check.

### MEDIUM-4 — 05-16's BM25 snapshot wording invites an O(corpus) copy per query
`Bm25Index` (`engine/src/retrieval/bm25.rs:113-119`) owns `Vec<IndexedDocument>` (full chunk text), a `HashMap<String, usize>` document-frequency table, and derives `Clone`. "Clone/copy the index data needed by the query" deep-copies the corpus on every request in a service whose stated value is high-performance data-plane engineering.

### MEDIUM-5 — 05-12 embeds a coverage matrix that is stale by eight plans
Lines 111-126 map sources to 05-08 … 05-13 only; lines 131-148 have no rows for WR-10, WR-11, IN-02, IN-03, IN-05. The action text at line 157 does instruct mapping 05-14 … 05-21, but also instructs including these tables — the two instructions conflict, and the tables are what the automated check reads.

### LOW-1 — `FakeGenerator` remains a production symbol
`engine/src/generation/mod.rs:467-512`, public and ungated; imported by `engine/src/tests/workflow_phase5.rs:12`. 05-15 gates six workflow ports and stops there.

### LOW-2 — IN-05 closes for one of the two tests it names
05-20 adds `workflow_phase5_reformulate_predeadline_4999ms_no_timeout`; `workflow_phase5_retrieve_timeout_ten_seconds` (`engine/src/tests/workflow_phase5.rs:377`) keeps the same "asserts the deadline fired, never that it didn't fire earlier" shape.

### LOW-3 — Cancellation cannot interrupt prompt packing inside the provider adapter
`engine/src/generation/openrouter.rs:383` mints a fresh `CancellationToken::new()` for `pack_evidence_and_graph_prompt`, so the workflow token never reaches it. Low impact (CPU-bound, bounded by token budget), but it is a real hole in 05-09's "cancellation drops in-flight work" claim and no plan names it.

### LOW-4 — 05-12's `git diff --check` is unscoped in a shared wave
The hash/staged/unstaged checks are correctly path-scoped to the fourteen frozen files; the trailing `git diff --check` is not, and 05-08 is modifying `engine/src/main.rs` in the same wave.

### LOW-5 — Roadmap wave-11 rationale contradicts the DAG
The roadmap describes wave 11 as "blocked on typed dispatch and prompt/fake boundaries," but 05-15 (the prompt/fake boundary) is wave 12. Documentation-only; the `depends_on` graph is correct.

---

## 4. Suggestions

1. **Add a graph-fact task to 05-08** (or a new plan before 05-16). Concretely: widen `GraphQueryPort::query_graph` to return `Vec<GraphFactBlock>` (or add a parallel typed method), add `graph_facts: Vec<crate::prompt::GraphFactBlock>` to `WorkflowContext`, have `AssemblePromptNode` pass `&ctx.graph_facts` instead of `&[]` at `assemble_prompt.rs:92`, and have `GenerateAnswerNode` set `req.graph_facts` / `req.graph_weight` from context. Add to 05-08 Task 2's verification a source guard in the Task 1 style: fail if `assemble_prompt.rs` still contains a literal `&[]` graph argument, and fail if `generate.rs` constructs `GenerationRequest` without assigning `graph_facts`. Extend the mock at `gateway/main_test.go:2115` to require a graph-fact marker in `messages[1].content`, which turns 05-11's cross-runtime test into the end-to-end proof. Add `graph_facts` to 05-10's 18-field checkpoint list (making it 19).

2. **Resolve the 05-08/05-16/05-18 target conflict.** Preferred: move the production seam into the library — put `build_production_workflow` and the BM25 snapshot adapter in `engine/src/workflow/` (e.g. a `production.rs` module) taking the service's ports as arguments, leave `main.rs` as a thin call site, and update 05-08's guard to extract the builder from the library file while still asserting `query_rag` in `main.rs` invokes it. Alternative: split `workflow_phase5.rs` into a lib-target file and a retained bin-target `workflow_phase5_production.rs`, and change 05-18's Task 2 guard from "no binary registration" to "no *duplicate* registration." Either way, add `05-08` and `05-16` to 05-18's `depends_on`, and add a re-verification step to 05-18 that re-runs 05-08's four production test names in whichever target owns them.

3. **Make 05-09's live proof self-consistent.** Give 05-09 explicit ownership of *all* seven `config.verify.toml` workflow values and raise the four upstream deadlines to values a real engine run can meet (e.g. 5000/10000/10000/4000/15000/2000 with only `generation_node_timeout_ms` held at 7000), or state explicitly which upstream ports the live harness stubs and add an acceptance criterion that the workflow reaches `NodeStarted{GenerateAnswer}` before the timeout fires. Either way, add an assertion that the observed failure is at `GenerateAnswer` — a `Timeout` at `RetrieveHybrid` must not satisfy the gate.

4. **Give 05-08 Task 2 a source guard.** Fail if `engine/src/workflow/nodes/assemble_prompt.rs` matches `Content of chunk`, if `engine/src/workflow/mod.rs` matches `Answer for \{`, and if `run_inline_prompt_generation_remainder` is reachable from any non-`cfg(test)` path. (05-08's existing negative check covers only `execute_inline_query_rag_remainder`; the second, divergent remainder at `workflow/mod.rs:143` is not covered by any guard in the set.)

5. **Scope 05-11's guard to the function.** Extract the `TestRAGQueryCrossRuntime` body by regex before the `.Contains` checks, and add a needle that only the real harness can satisfy — e.g. require `enginePath` or the mock-server env assignment (`LANCET_OPENROUTER__CHAT_ENDPOINT`) inside the extracted region.

6. **Fix 05-16's BM25 wording.** Specify `Arc<tokio::sync::RwLock<Arc<Bm25Index>>>` (or `arc-swap`) so the guard clone is a refcount bump, not a corpus copy, and state the acceptance criterion as "the snapshot operation is O(1) in corpus size."

7. **Regenerate 05-12's tables.** Rewrite the embedded coverage-audit and gap-disposition tables to span 05-08 … 05-21 with explicit rows for WR-10/WR-11 → 05-15, IN-02/IN-03 → 05-21, IN-05 → 05-20, and path-scope the trailing `git diff --check` to the fourteen frozen files.

8. **Small additions.** Gate `FakeGenerator` under `cfg(test)` in 05-15 (or state explicitly why it stays public). Add the retrieve-node 9999 ms pre-deadline case to 05-20 Task 2 alongside the reformulate 4999 ms case. Add `self.nodes` to 05-08's required-field list. Thread the workflow `CancellationToken` into `openrouter.rs:383` in 05-13 or 05-20.

---

## 5. Coverage assessment

**Review ledger (`05-REVIEW.md`: 8 critical / 14 warning / 5 info).** Every finding has a named owner across the set: CR-01 → 05-09; CR-02/CR-03 → 05-08; CR-04 → 05-09; CR-05 → 05-10; CR-06/CR-07/CR-08 → 05-11; WR-01/WR-03 → 05-10 and 05-14; WR-02/WR-04 → 05-13 + 05-10; WR-05 → 05-08; WR-06/WR-07 → 05-16 + 05-19; WR-08/WR-09 → 05-16 + 05-17; WR-10/WR-11 → 05-15; WR-12 → 05-11 (accepted, no behavior); WR-13 → 05-10; WR-14 → 05-16; IN-01/IN-04 → 05-14 and 05-08; IN-02/IN-03 → 05-21; IN-05 → 05-20 (partial, LOW-2). **No ledger item is orphaned.** The only ledger-level defect is that 05-12's *embedded* disposition table has not caught up (MEDIUM-5).

**Verification gaps (`05-VERIFICATION.md` SC1-SC4 plus the fifth snapshot gap).** SC1 → 05-08, SC2 → 05-08/05-10/05-11, SC3 → 05-09/05-13/05-10, SC4 → 05-08/05-10/05-11. Correctly mapped.

**Phase success criteria.**
| # | Criterion | Closed by | Assessment |
|---|---|---|---|
| 1 | RAG pipeline formalized into a defined state machine | 05-08, 05-14 | **Partial.** Structure closes; the graph-augmented *content* does not (HIGH-1). Proof is fragile (HIGH-2). |
| 2 | Workflow events stream Rust → Go → Client | 05-08, 05-10, 05-17, 05-19, 05-11 | **Closes**, subject to MEDIUM-3's guard weakness. |
| 3 | Node timeouts and retries handle failure predictably | 05-09, 05-13, 05-20 | **Closes semantically**; the wall-clock evidence class does not (MEDIUM-1). |
| 4 | Snapshots of workflow state captured for debugging | 05-10, 05-11 | **Closes.** 18-field serialization + Go-owned persistence with explicit pending ownership. |
| 5 | QueryReformulator pass-through in the state machine | 05-08, 05-14 | **Closes.** ORCH-05 retained on the production path and asserted. |

**Locked decisions.** No regression against `05-CONTEXT.md` found. D-04, D-10, D-18, D-19, D-21, D-23-D-29 are preserved; D-30/D-31 scope fences are respected (05-17 correctly frames `variant_count`/`variant_identities` as D-07/D-08 provenance rather than deferred metadata). D-17's amended 30s/65s split is honored throughout. Two additions sit within CONTEXT's "Claude's Discretion — exact SSE framing details": 05-11's new `stream_error` event with `GRPC_RECV_ERROR` / `STREAM_EOF_WITHOUT_TERMINAL` codes. That is defensible, but it is a client-visible contract addition; it deserves an explicit line in 05-12's errata rather than arriving implicitly at wave 17. No scope creep otherwise — all fourteen plans stay inside ORCH-01 … ORCH-05, and none touch the `QueryGraph` RPC (D-10).

---

## 6. Risk Assessment

**Overall: HIGH.**

Not because the set is poorly designed — the opposite is true. The plans are grounded in real source, the guards are unusually specific, the wave DAG is executable, 05-12's frozen hashes verify exactly, 05-13's provider analysis is precisely right, and 05-11 builds on a cross-runtime harness that genuinely exists and already enforces the D-01/D-08 contracts. Most of what I checked, I checked expecting to find drift and found accuracy instead.

The risk is HIGH because two defects share a common shape: **the gates can all go green while the phase's actual value stays unbuilt.** HIGH-1 means the demoable outcome — graph-augmented, cited answers produced by the state machine — can be reported as delivered with zero graph facts ever reaching the model, and the strongest end-to-end test in the repo would not notice. HIGH-2 means the one guard that *cannot* be satisfied by a library-only change runs at wave 7 and is structurally invalidated at wave 11, with no re-check — which is the exact failure mode (`05-VERIFICATION.md`: "the state machine exists as a library only") this entire gap-closure set was created to correct. MEDIUM-1 compounds it by making the phase's designated wall-clock evidence class unreachable as configured.

Both HIGH items are fixable with bounded edits before execution: one added task plus two source guards in 05-08, and one seam relocation across 05-08/05-16/05-18 with a re-verification step. With those in place — and with suggestions 3-5 applied — I would rate this set MEDIUM and recommend execution.


---

## Consensus Summary

Both reviewers found the 14-plan gap-closure set substantially stronger than the original baseline and agreed that its wave ordering, production-wiring intent, typed event/protobuf work, timeout/retry design, and checkpoint/SSE hardening are well targeted. Both reviews had repository access and produced source-cited feedback; the AgY review was broadly approving, while Claude identified concrete closure blockers that should control the planning follow-up.

### Agreed strengths

- The gap-closure plans target the real production seams identified by the current code review: the one-node production runner and inline remainder, dead workflow configuration, event/sequence handling, generated wire fields, OpenRouter preflight/retry classification, and gateway stream/checkpoint behavior.
- The dependency graph from Waves 7 through 17 is broadly causal and the plans use exact file/test/source guards more often than the original set.
- The plans preserve the phase's locked behavior around graph-before-retrieval ordering, bounded reformulation admission, generation-only retry, in-band terminal failure, and Go-owned checkpoint persistence.
- The reviewers agreed that the protobuf regeneration and cross-runtime synchronization work in 05-17 is appropriately placed before consumers.

### Priority concerns

- **HIGH — Graph facts still have no end-to-end carrier to generation.** Claude cites engine/src/workflow/nodes/assemble_prompt.rs:89-97, where the node passes an empty graph-fact slice, and engine/src/workflow/nodes/generate.rs:53-56 / engine/src/generation/mod.rs:396, where GenerationRequest is built with an empty graph_facts vector. The gap-closure plans do not add a typed graph-fact field/port or assign it into the outbound request, so the state machine can be production-wired while answers remain graph-free.
- **HIGH — 05-18 can invalidate earlier production proofs.** Claude cites the binary-only ownership of engine/src/main.rs production builders and BM25 adapters versus 05-18's move of engine/src/tests/workflow_phase5.rs into the library target. The set does not re-run the 05-08 production-reachability tests or preserve a bin-target seam after that move; the plan can therefore finish with green library tests while the production wiring proof is gone or uncompilable.
- **MEDIUM — 05-09's live timeout proof is inconsistent with its committed overlay.** Claude notes that config/config.verify.toml retains 50/100/100/40/150/20 ms upstream values while the plan asks a real workflow to reach GenerateAnswer and observe the 7000 ms node timeout. The harness needs either realistic upstream values, explicit stubs, or an assertion that the observed timeout is specifically at GenerateAnswer.
- **MEDIUM — Several verification guards are weaker than their claimed behavior.** Claude identifies a file-scoped 05-11 cross-runtime guard that can be satisfied by unrelated tests, a prose-only anti-fabrication check in 05-08, and stale/incomplete embedded traceability tables and unscoped git diff --check in 05-12. These should be converted into function/source-scoped checks and regenerated coverage tables.
- **MEDIUM/LOW — Remaining targeted omissions.** Claude flags the potential O(corpus) BM25 clone wording in 05-16, ungated FakeGenerator despite 05-15's fake-port hygiene, only one of the two pre-deadline timeout regressions named by IN-05 in 05-20, and cancellation not reaching the fresh token used for prompt packing in engine/src/generation/openrouter.rs:383.

### Divergent views

- AgY rates the plan set LOW risk and says the full baseline issue set and ORCH-01 through ORCH-05 are closed, with generated-code synchronization as its only material concern.
- Claude rates the set HIGH risk because the two HIGH findings permit all automated gates to pass while the graph-augmented production outcome or production-reachability evidence remains absent. Claude's findings are more specific and source-grounded, so they should drive revision before execution.
- AgY treats 05-18's library-target migration as clean; Claude found a binary/library target collision that requires explicit re-verification. This disagreement should be resolved by checking target ownership in the plan tasks, not by relying on the favorable aggregate verdict.

### Recommended planning follow-up

Run /gsd-plan-phase 5 --reviews with this gap-closure review and revise before execution. At minimum, add a typed graph-fact carrier and outbound generation assignment with source-guarded tests; resolve the 05-08/05-16/05-18 binary-versus-library test ownership and re-run the production proof after the move; make 05-09's live overlay harness reach GenerateAnswer; and strengthen 05-08, 05-11, and 05-12's guards. Then independently re-check the revised plan graph and verification contracts.
