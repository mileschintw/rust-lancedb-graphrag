---
phase: 5
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-13T00:00:29Z
plans_reviewed:
  - 05-01-PLAN.md
  - 05-02-PLAN.md
  - 05-03-PLAN.md
  - 05-04-PLAN.md
  - 05-05-PLAN.md
  - 05-06-PLAN.md
reviewer_models:
  antigravity: gemini-3.6-flash-high
  claude: opus
reviewer_effort:
  antigravity: high
  claude: medium
---

# Cross-AI Plan Review — Phase 5

## Antigravity Review (gemini-3.6-flash-high, high)

# Cross-AI Plan Review: Phase 5 (State Machine & Workflow Events)

## 1. Summary

The 6-plan execution suite for Phase 5 (`05-01-PLAN.md` through `05-06-PLAN.md`) presents a highly disciplined, well-structured architecture for formalizing Lancet's linear RAG pipeline into a typed Rust state machine (`engine/`) with server-streaming gRPC and a Go gateway SSE relay (`gateway/`). The plan set demonstrates exemplary domain awareness by decoupling pre-stream HTTP validation from in-stream workflow lifecycle events, resolving critical timeout interactions (such as exempting `/rag/query` from chi's global 60s middleware), bounding cross-variant RRF fusion memory, establishing a non-blocking PostgreSQL checkpointing pipeline, and providing a comprehensive fault-injected test matrix. While the overall design is outstanding, minor risks exist around intermediate build-state drift during multi-wave protobuf code generation, subtle `buf` tool behavior when toggling output plugins, and the strict synchronization requirements between `14000ms` graph operation deadlines and `15000ms` runner backstops. Overall, the plans achieve the phase requirements (ORCH-01 through ORCH-05) with exceptional architectural rigor.

---

## 2. Strengths

- **Coordinated Wave Sequencing & API Boundary Protection:**
  - Wave 1 ([`05-01-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md)) isolates the Rust-side state machine and tracer before Wave 2 ([`05-06-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-06-PLAN.md)) lands the full Go and Rust protobuf codegen transition, avoiding broken inter-service contracts during intermediate development steps.
- **Root-Cause Timeout Resolution:**
  - `05-06-PLAN.md` explicitly addresses a major bottleneck in [`gateway/main.go:464`](file:///D:/Repos/lancet/gateway/main.go#L464), where `middleware.Timeout(60*time.Second)` would otherwise forcibly close SSE streams before the worst-case ~97s sequential workflow (5s + 10s + 15s + 2s + 65s) completes.
  - `05-03-PLAN.md` cleanly separates the `LLMGeneration` node's wall-clock budget (`generation_node_timeout_ms = 65000`) from the underlying per-attempt provider timeout ([`GENERATION_TIMEOUT = 30s`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L24) in [`engine/src/generation/openrouter.rs:24`](file:///D:/Repos/lancet/engine/src/generation/openrouter.rs#L24)), ensuring a transient 30s attempt failure can trigger a full retry without breaching the node deadline.
- **Fail-Safe Graph Context Degradation:**
  - `05-02-PLAN.md` designs a `GraphTimeoutPolicy` for `ExtractGraphContextNode` that handles no-match, logical error, or operation timeout (`14000ms` deadline vs `15000ms` runner backstop) by degrading to an empty graph context with a `GRAPH_TIMEOUT` notice. This directly honors requirement **D-09** ("mandatory to run, not required to succeed") without triggering a fatal `NodeFailed` or stream abort.
- **Bounded Resource Consumption & Denial-of-Service Defense:**
  - `05-02-PLAN.md` caps `QueryReformulator` variant admission to a strict ceiling of 8 variants; a 9th variant triggers a typed `InputValidation` rejection before any dense vector or BM25 retrieval call is executed, preventing rank-accumulator memory growth from runaway multi-query expansion.
- **Non-Blocking Checkpoint Dispatcher Architecture:**
  - `05-05-PLAN.md` and `05-06-PLAN.md` implement `CheckpointDispatcher` in Go with primary capacity 1, FIFO overflow 5, and explicit `Pending` tracking. This guarantees that durable PostgreSQL writes to `workflow_checkpoints` ([`gateway/db/schema.hcl`](file:///D:/Repos/lancet/gateway/db/schema.hcl)) remain fire-and-forget and cannot stall SSE frame delivery or user query latency (satisfying **D-26** and **D-27**).
- **First-Class Integration Test Schema Isolation:**
  - `05-05-PLAN.md` enforces per-test schema isolation (`newWorkflowCheckpointsIsolatedPostgres`) for all PostgreSQL integration tests in [`gateway/main_test.go`](file:///D:/Repos/lancet/gateway/main_test.go), fully adhering to the repository's code review convention outlined in [`AGENTS.md:38-44`](file:///D:/Repos/lancet/AGENTS.md#L38-L44).

---

## 3. Concerns

- **[MEDIUM] `buf.gen.yaml` Plugin Cleaning Behavior during Partial Transition (Wave 1 vs Wave 2):**
  - *Location:* [`buf.gen.yaml:2`](file:///D:/Repos/lancet/buf.gen.yaml#L2) and [`05-01-PLAN.md:1078-1082`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-01-PLAN.md#L1078-L1082).
  - *Mechanism:* `buf.gen.yaml` currently specifies `clean: true`. `05-01-PLAN.md` instructs the executor to remove Go plugins from `buf.gen.yaml` for a "Rust-only transition" while relying on a hash-comparison check to ensure `gateway/proto/lancet/v1/lancet.pb.go` is not deleted or modified. Depending on `buf` version behavior, editing `buf.gen.yaml` while `clean: true` is set could attempt to clean unlisted output directories or fail.
  - *Risk:* Worktree edits to generated files could be wiped out or cause `buf generate` verification step failures during Wave 1 execution.

- **[MEDIUM] Granular Timer Race in `ExtractGraphContextNode` vs `WorkflowRunner` Backstop:**
  - *Location:* `05-02-PLAN.md` Task 1 (`engine/src/workflow/nodes/graph_context.rs`).
  - *Mechanism:* The plan establishes `14000ms` for `engine.graph.graph_operation_timeout_ms` and `15000ms` for `engine.graph.graph_node_timeout_ms`. In heavily loaded or asynchronous test environments, if thread scheduling delays the inner `tokio::select!` in `ExtractGraphContextNode`, the runner's outer `15000ms` timeout could fire concurrently with or slightly before the inner `14000ms` timeout.
  - *Risk:* If the runner backstop fires before the node's inner degrade handler completes, it could route the timeout through the generic runner `NodeFailed` handler instead of the node's silent degrade path.

- **[LOW] Go `main_test.go` Blast Radius during Unary-to-Streaming Migration:**
  - *Location:* [`gateway/main_test.go`](file:///D:/Repos/lancet/gateway/main_test.go) and [`05-06-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-06-PLAN.md).
  - *Mechanism:* Over 14 test functions in `gateway/main_test.go` mock `engine.QueryRAG` or invoke `POST /rag/query` expecting unary JSON responses (`*pb.QueryRAGResponse`).
  - *Risk:* Until Wave 2 (`05-06-PLAN.md`) completely updates every mock implementation to consume the server stream, running `go test ./...` in `gateway/` will produce compilation errors. `05-01-PLAN.md` correctly notes that `go test` passes are not claimed until Wave 2, but care must be taken that intermediate commits do not break CI expectations if Go tests are triggered automatically.

- **[LOW] Memory Accumulation in Full Workflow Snapshot Checkpoints:**
  - *Location:* `05-03-PLAN.md` and `05-05-PLAN.md` (`context_snapshot` column in `workflow_checkpoints`).
  - *Mechanism:* Each node boundary emits a full accumulated `WorkflowContext` snapshot (**D-28**) containing prompt text, vector results, BM25 candidates, and graph context. A 5-node pipeline generates 5 complete snapshot rows per query.
  - *Risk:* While acceptable for the current single-user local demo scope (**D-24**), high-frequency query benchmarking could cause rapid PostgreSQL table growth in development environments.

---

## 4. Suggestions

1. **Explicitly Set `clean: false` or Use Selective `buf generate --template` in Wave 1:**
   - In `05-01-PLAN.md`, explicitly update `buf.gen.yaml` to set `clean: false` during the Rust-only transition phase to eliminate any risk of `buf` deleting existing `gateway/proto/` files before Wave 2.
2. **Buffer Slack in Graph Operation Deadline:**
   - In `05-02-PLAN.md`, consider widening the gap between `engine.graph.graph_operation_timeout_ms` (e.g., `12000ms` or `13000ms`) and the `15000ms` runner backstop to ensure thread jitter under heavy CPU load never causes the outer runner timeout to preempt the inner node degradation handler.
3. **Add Database Storage Warning / Cleanup Script for Dev:**
   - Add a lightweight `scripts/reset-checkpoints.sh` or `psql` snippet to documentation so developers can easily truncate `workflow_checkpoints` after long benchmarking sessions.

---

## 5. Risk Assessment

- **Overall Risk Level:** **LOW**
- **Justification:**
  The implementation plans are exceptionally detailed, rigorous, and closely aligned with the authoritative requirements, architecture decisions (**D-01** through **D-31**), and existing codebase patterns in `D:\Repos\lancet`. All major failure modes—such as gRPC stream cancellation, chi middleware timeouts, multi-variant RRF bounds, generation retry semantics, and PostgreSQL checkpoint isolation—have been anticipated with precise, test-backed mitigations. The identified concerns are minor execution details that are easily managed within the plan's verification gates.

---

## Claude Review (opus, medium)

# Cross-AI Plan Review — Phase 5 (05-01 … 05-06), Revision 2

**Basis:** verified directly against the working tree at `2197be6`. Every finding below cites `path:line` and the mechanism. Where I could not confirm a claim I say so.

---

## 1. Summary

This revision materially improves on the prior round. All three of `05-REVIEWS.md`'s HIGH findings are genuinely closed, and closed correctly — I verified each against source rather than taking the plans' word for it. What remains is one self-blocking verification gate in 05-01, one genuinely unowned pipeline step (query embedding) that carries a timeout defect neither prior reviewer found, and a small cluster of acceptance criteria that are unsatisfiable as literally written. The architecture, wave graph, and disposition discipline are sound; the defects are executional and localized. Overall risk is **MEDIUM** — down from the prior HIGH, but 05-01 still cannot pass its own first gate as written.

---

## 2. Prior HIGH findings — confirmed resolved

Worth stating explicitly, since a revision review that omits this reads as if nothing changed.

- **Trailer truth statement corrected.** The prior review was right that malformed input returns a bare `Status`: `engine/src/main.rs:1356-1362` (`Status::invalid_argument("session_id must be a valid UUIDv4 string")`, no metadata) and `:1381-1392` (`QueryRequest::from_values` → plain `Status`). 05-01 Task 2 now says precisely that: *"d1-style trailer metadata is only used by existing pre-stream infrastructure paths that actually emit it, never as a claim that malformed validation carries trailers."* Accurate.
- **Identity contract replaced, not retired.** 05-06 Task 1 sets `X-Lancet-Session-ID`/`-Correlation-ID`/`-Error-Kind` from the prefetched first frame before committing HTTP 200. That closes the gap.
- **Generation timeout arithmetic separated.** `openrouter.rs:24` (`GENERATION_TIMEOUT = 30s`) and `config/config.toml:35` (`generation_timeout_secs = 30`) remain per-attempt; the new `generation_node_timeout_ms = 65000` is separately keyed with `65000 >= 2*30000 + 5000` asserted. The D-17 amendment's parenthetical ("slack for inter-attempt dispatch overhead, not the preflight") is also correct — `check_supported_parameters()` sits inside `execute_one_call` (`openrouter.rs:375`), which is itself wrapped by the per-attempt `timeout(...)`, so the preflight is already inside the 30s.
- **05-01's Go-suite gate disclaimed.** `gateway/main_test.go:1893` `TestRAGQueryCrossRuntime` still has no skip (the only `t.Skip` is at `:1710` for `TEST_DATABASE_URL`), and 05-01 no longer claims a Go suite pass. Correct disposition.

One design call deserves credit: **first-frame prefetch is load-bearing, not decoration.** With server-streaming gRPC, `client.QueryRAG(ctx, req)` returns before headers arrive, so an `InvalidArgument` from D-04's validation only surfaces on the first `Recv()`. Prefetching is the only way to preserve the pre-stream 4xx and set identity headers before `WriteHeader`. The plans got a non-obvious thing right.

---

## 3. Concerns

### HIGH — 05-01 Task 1's first verify command fails before it can count anything

Task 1's `<files>` list (13 files) excludes `engine/src/tests.rs`, but its **first** `<verify>` command is `cargo test --manifest-path engine/Cargo.toml --locked -- --list`.

- `mod tests;` is declared at `engine/src/main.rs:3126` — the test module compiles as part of the **bin** target (`engine/src/lib.rs:3-9` declares no `tests` module).
- `engine/src/tests.rs` has **29** `.query_rag(` call sites, including `query_rag_happy_path_service` (`:2181`) and the three `graph_augmentation_*_is_observable_end_to_end` tests (`:6216`, `:6256`, `:6293`).
- The moment `QueryRAG` becomes server-streaming, the tonic server trait returns `Result<Response<Self::QueryRagStream>, Status>`; every `.query_rag(...).await.unwrap().into_inner()` site fails to compile. `$listExit -ne 0` → the gate throws before `query_rag_tracer` is ever counted.

The ordering makes this worse: `cargo check` (verify command 3) does **not** build test cfg, so it passes. The failure lands on command 1, which the guard treats as fatal.

Compounding edges:
- **`query_rag_tracer` has no home.** Task 1 must register it but doesn't own `tests.rs`. Putting it in an inline `#[cfg(test)] mod` inside `runner.rs` contradicts the recorded house convention (`.planning/STATE.md`, Phase 02-07 decision: *"Keep all Rust fault fixtures and integrity tests in engine/src/tests.rs, leaving production code with only the standard test-module declaration"*).
- **The migration obligation vanished between revisions.** `05-REVIEWS.md:101` credits 05-01 for a complete list of 21 named tests to migrate. The current 05-01 contains no such list; Task 2 names only four *new* tests and says it "may add only deterministic regression seams there." ~27 existing tests must be rewritten to drain a stream, and no plan now says so.

*Fix:* add `engine/src/tests.rs` to Task 1's `<files>` with an explicit stream-drain migration obligation (and restore the named test list), or reorder so `cargo check` gates first and the `--list` guard runs only in Task 2.

### HIGH — the query-embedding step has no node owner, and every candidate owner's timeout is too small (05-01, 05-02)

Shipped order is embed (`main.rs:1395`) → graph (`:1426`) → dense retrieval (`:1450`). D-06 preserves graph-before-retrieve, and `attempt_graph_augmentation` consumes `query_embedding`. So the embedding must complete **before** `ExtractGraphContext`.

The plans contradict each other on where it lives:
- 05-01 Task 1: *"pass the reformulator variants and variant-0 embedding through the context"* — i.e. at the `ReformulateQuery` boundary.
- 05-02 Task 1 action 2: *"before invoking embedding, dense, BM25 … reject a reformulator Vec longer than eight … For one through eight variants, embed only variant zero"* — i.e. inside `RetrieveHybrid`, which runs **after** graph.

Both placements are also timeout-defective. `engine/src/client/mod.rs:10` sets `REQUEST_TIMEOUT = Duration::from_secs(10)` for the embedding HTTP call:
- Inside `ReformulateQuery` (D-17 budget **5s**), a legitimate 6–10s embedding is killed — a behavioral regression versus today, where nothing bounds it below 10s.
- Inside `RetrieveHybrid` (budget **10s**), the embedding alone can consume the entire node budget, leaving nothing for dense + BM25 + fusion + rerank.

This is the same class of defect as the 30s/65s generation arithmetic that the prior round caught — and it is unaddressed because no plan ever names the embedding step as a costed unit.

Two dependent edges: (a) D-22's taxonomy has no embedding category, so the plans don't say whether embedding failure maps to `Internal` or `RetrievalFailed`; (b) `main.rs:1408` and `:1417` are the **only** remaining production `d1_status` callers, so where embedding lands determines whether the pre-stream trailer path retains any caller at all — which in turn determines whether `gateway/main_test.go`'s four header-assertion tests remain representative.

### MEDIUM — the new timeout keys will break `config_example_matches_effective_rag_contract` (05-06)

`engine/src/tests.rs:180` restricts the scanned sections to `"engine.retrieval" | "engine.retrieval.bm25" | "engine.graph" | "openrouter"`, and `:203-206` asserts `assert_eq!(observed_keys, required_keys)` — **exact set equality**, plus an adjacent-annotation-comment requirement per key.

05-06 Task 2 registers only the two graph keys in `REQUIRED_EFFECTIVE_RAG_KEYS`/annotations. It never names a section for the other four (`reformulate 5000ms`, `retrieve 10000ms`, `prompt 2000ms`, `generation_node_timeout_ms 65000`). The natural placement for `generation_node_timeout_ms` is under `[openrouter]` beside `generation_timeout_secs` (`config.example.toml:68`) — which is allowlisted, and would fail the exact-set assertion immediately.

Two related inaccuracies:
- 05-06 says *"Put both graph keys in `config/config.toml`"* — but `config/config.toml` is 38 lines and has **no `[engine.graph]` section at all** (only `config.example.toml:50` does). The executor would be creating a partial section that omits `seed_match_min_score`/`max_hop_cap`.
- 05-06 requires *"exact presence in all three overlays"*, but `config/config.verify.toml` is currently three lines (`[engine]` / `lancedb_path`) and the contract test only ever reads `config.example.toml` (`tests.rs:143`). Asserting presence in the other two requires net-new test code the plan mentions only in passing.

### MEDIUM — `pack_evidence_and_graph_prompt`'s async conversion touches a file 05-03 doesn't own

05-03 Task 1 requires prompt packing to become *"a bounded cooperative async loop"* with `yield_now().await` and cancellation checkpoints. The function is a synchronous `pub fn` at `engine/src/prompt.rs:255` with 14 call sites across `main.rs`, `tests.rs`, and — critically — **production** code at `engine/src/generation/openrouter.rs:383`, inside `execute_one_call`. `openrouter.rs` has no `mod tests`, so this is a real production caller.

`engine/src/generation/openrouter.rs` is **not** in 05-03's `files_modified`. Since the plans explicitly prohibit modifying unlisted files, 05-03 is unexecutable as scoped.

The cancellability motivation is legitimate (a sync loop inside `tokio::select!` genuinely can't be preempted), so the right fix is widening the inventory, not dropping the requirement.

### MEDIUM — "byte-identical retry" and the `assembled_prompt` snapshot describe different artifacts (05-03)

`openrouter.rs:379-383` carries a comment marking the in-generator re-pack as a deliberate prior REVIEWS.md HIGH fix (so a configured `graph_weight` provably reaches the wire). That is correct behavior — **not** a defect. But it means the prompt string that goes on the wire is built inside `execute_one_call`, from `self.config.evidence_token_budget()`, while `main.rs:1551` packs separately from `limits.evidence_token_budget()`.

Consequences for 05-03's stated contracts:
- The key_link *"AssemblePrompt → GenerateAnswer exact prompt/request bytes → retry identity"* is imprecise. The retry is byte-identical at the `GenerationRequest` level — which is what actually matters — but the assertion in `generation_retry_request_is_byte_identical` must be pinned to `GenerationRequest` equality, not "same prompt."
- D-28's `assembled_prompt` checkpoint field holds the node's assembled prompt, not the outbound prompt. Label it as such, or the snapshot invites a false debugging conclusion.

### MEDIUM — several acceptance criteria are unsatisfiable as literally written (05-01, 05-03, 05-04)

Three plans require the successful terminal to carry **non-empty** `answer`, `citations`, `structured_citations`, `notices`, and a **non-unspecified** `answer_basis`. Two of those are false against source:

- **Zero-evidence success (D-03).** `engine/src/main.rs:1533-1546` returns `answer: String::new()`, `citations: vec![]`, `answer_basis: AnswerBasis::Unspecified as i32`, `structured_citations: vec![]`. This is a *valid success* under D-03. 05-01's acceptance criteria (*"a valid request … preserve non-empty answer, citations, session_id, answer_basis…"*) and 05-04's `workflow_phase5_happy_path` criteria must be scoped to the evidence-bearing path explicitly.
- **`notices` on the happy path.** Existing fixtures set `notices: vec![]` throughout (`tests.rs:2215`, `:2561`, `:2641`, `:2705`, …). An empty notices list is the *normal* success case; requiring non-empty forces a contrived fixture that pins nothing real. Assert the field is *present and correctly mapped*, not non-empty.

### LOW

- **05-05 schema:** a `varchar(255)` `id` column is declared with no `primary_key` block, while the only index is the non-unique `(trace_id, sequence_ordinal, created_at)`. Either make `id` the PK (matching the `documents` precedent at `gateway/db/schema.hcl:29`) or drop the column — a surrogate key with no uniqueness constraint buys nothing.
- **Checkpoint-count phrasing drift:** 05-01 states *"The valid service path has five checkpoint boundaries"* as absolute; 05-04 correctly says "five or fewer." Under D-03's short-circuit only three nodes run. Align 05-01 to the bounded phrasing.
- **ROADMAP drift:** `.planning/ROADMAP.md:345` describes 05-04 as delivering *"bounded Notify rendezvous cleanup"*; the current 05-04 mentions no `Notify` primitive (it specifies an `AbortOnDrop` guard instead). Stale wave description.
- **Confirmed non-issues** (checked so they don't get re-raised): `google/uuid v1.6.0` is already in `gateway/go.mod`, so 05-05 needs no dependency change; `mod tests;` exists only in `main.rs`, so the `--list` count-of-1 guards can't double-match; and with the Go plugins dropped, `clean: true` (`buf.gen.yaml:2`) cannot touch `gateway/proto` since it is no longer a plugin `out` — 05-01's "must not rely on `clean: false`" framing is correct.

---

## 4. Suggestions

1. **Add `engine/src/tests.rs` to 05-01 Task 1's `<files>`** with the explicit obligation to migrate all 29 `.query_rag(` call sites to a stream-drain helper, and restore the named-test migration list that the prior review verified. Alternatively, reorder the verify block so `cargo check` runs before the `--list` guard.
2. **Assign the embedding step a node and a budget.** The only placement consistent with D-06 is inside `ExtractGraphContext`'s upstream — either fold it into `ReformulateQuery` and raise that node's budget above the 10s `REQUEST_TIMEOUT` (`client/mod.rs:10`), or make it its own costed step. Either way, remove the "embed variant zero" language from 05-02's `RetrieveHybrid`, update the 97s worst-case arithmetic in 05-06, and name the D-22 category for embedding failure.
3. **Name the section for all six timeout keys**, and extend `REQUIRED_EFFECTIVE_RAG_KEYS` + `REQUIRED_EFFECTIVE_RAG_ANNOTATIONS` for every key that lands in an allowlisted section — or place them in a non-allowlisted section (e.g. `[engine.workflow]`) and say so explicitly, accepting that the contract test won't cover them.
4. **Add `engine/src/generation/openrouter.rs` to 05-03's `files_modified`** and note the two-site packing so the executor updates both.
5. **Re-pin the retry-identity assertion to `GenerationRequest` equality**, and relabel the checkpoint field as the node's assembled prompt.
6. **Scope the "non-empty terminal field" truths** to the evidence-bearing path, and replace the `notices` non-empty requirement with a presence/mapping assertion.

---

## 5. Risk Assessment

**Overall: MEDIUM.**

The phase-level design is sound, the wave graph is internally consistent, and the "Review dispositions carried into this plan" sections are a genuinely effective mechanism — the prior round's three HIGH findings are closed with correct, source-accurate fixes rather than restatement. What remains is one blocking gate and one unowned pipeline step, both fixable without re-planning.

Per plan:
- **05-01 — HIGH.** Task 1's first verify command cannot pass; `query_rag_tracer` has no compliant home; the existing-test migration obligation was lost in revision.
- **05-02 — MEDIUM.** Embedding ownership contradicts 05-01 and violates D-06's ordering constraint; otherwise the bounded-RRF and graph-degrade contracts are unusually well specified.
- **05-03 — MEDIUM.** `files_modified` omits a production caller it must change; prompt/request identity language needs pinning.
- **05-06 — MEDIUM.** Config exact-set trap; unnamed sections for four of six new keys.
- **05-05 — LOW-MEDIUM.** Well-grounded against the real Atlas/sqlc dual-schema convention; only the PK/index inconsistency.
- **05-04 — LOW.** Strongest plan; inherits only the terminal-field scoping issue.

---

## Consensus Summary

Both reviewers find the phase architecture strong and substantially improved: the wave graph, streaming boundary, first-frame prefetch/identity handling, bounded retrieval fusion, cooperative cancellation intent, and non-blocking checkpoint seam are well designed. Claude explicitly source-checked the prior HIGH findings as resolved, while AgY independently confirmed the same broad architectural strengths.

### Agreed Strengths

- **Wave-based migration discipline:** The plans sequence Rust workflow work before the full unary-to-server-streaming Go/protobuf transition, reducing the intended API drift window while keeping the migration tractable.
- **Explicit boundedness and resilience:** Both reviews recognized the value of bounded RRF fusion, cooperative async work, timeout/backstop design, fault-injected tests, and checkpoint persistence that does not block SSE delivery.
- **Correct streaming boundary intent:** The first-frame prefetch and synchronous validation/identity-header contract are important details for preserving HTTP semantics once `QueryRAG` becomes server-streaming.

### Agreed Concerns

- **Intermediate build and verification sequencing remains fragile.** AgY flags the partial `buf.gen.yaml`/generated-file transition and the temporary Go test blast radius. Claude identifies a higher-impact version of the same execution risk: 05-01's first `cargo test --list` gate reaches `engine/src/tests.rs` before the existing unary `.query_rag(...)` tests are migrated, so the gate cannot pass as written. The plans should make the migration inventory, gate ordering, and CI expectations explicit.
- **Timeout ownership and slack need one reconciled contract.** AgY identifies a possible 14-second graph-operation versus 15-second node-backstop race. Claude identifies an unowned query-embedding step whose 10-second HTTP timeout does not fit cleanly inside either the 5-second reformulation or 10-second retrieval budget and occurs before graph augmentation. The final plan set should assign embedding to a node, classify its failures, and define per-step budgets/backstop slack consistently.

### Divergent Views

- **Overall risk:** AgY rates the plan set LOW; Claude rates it MEDIUM and identifies two HIGH execution blockers in 05-01/05-02. The detailed Claude findings should drive the next planning revision because they include direct source tracing and exact gate mechanics.
- **`buf clean: true`:** AgY treats the partial-transition behavior as a MEDIUM risk. Claude's source review says this is a confirmed non-issue once Go plugins are removed, because `clean: true` cannot clean `gateway/proto` when that directory is no longer a plugin output. Retain the explicit verification, but do not treat this as a confirmed defect without reproducing the tool behavior.
- **Additional Claude-only plan defects:** the exact-set config contract for six timeout keys; the missing `openrouter.rs` ownership in 05-03's file inventory; the distinction between `GenerationRequest` retry identity and the assembled-prompt checkpoint; and acceptance criteria that require non-empty fields on valid zero-evidence success paths. These were not surfaced by AgY's higher-level review and require direct plan edits if confirmed.
- **Additional AgY-only risks:** graph timer jitter and full snapshot storage growth. These are reasonable operational considerations but lower priority than the Claude-identified blocking gates.

### Recommended Planning Follow-up

Run `/gsd-plan-phase 5 --reviews` and address the two agreed execution-contract concerns first. At minimum, repair 05-01's test ownership/migration gate, assign and budget query embedding before graph augmentation, then reconcile the Claude-only config/file-inventory/acceptance-criteria findings against the current source before execution.