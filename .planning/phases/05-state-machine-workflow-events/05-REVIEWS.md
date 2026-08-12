---
phase: 5
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-12T06:25:47Z
plans_reviewed:
  - 05-01-PLAN.md
  - 05-02-PLAN.md
  - 05-03-PLAN.md
  - 05-04-PLAN.md
  - 05-05-PLAN.md
  - 05-06-PLAN.md
reviewer_models:
  antigravity: gemini-3.1-pro
  claude: sonnet
reviewer_effort: high
---

# Cross-AI Plan Review — Phase 5

## Antigravity Review (gemini-3.1-pro, high)

> Review quality note: This reviewer returned a non-empty review covering all six plans, but did not include the requested concrete `file:line` citations. Treat its findings as high-level review observations and verify them against source during planning.

# Cross-AI Plan Review: Phase 5 - State Machine & Workflow Events

## Overview
The set of implementation plans (05-01 through 05-06) is exceptionally well-structured, logically ordered, and meticulously aligned with the context, architectural decisions (D-01 through D-31), and the specific repository rules (e.g., `AGENTS.md`). The formalization of the pipeline into a Rust state machine (`WorkflowRunner` and `Node` trait) and the adaptation of the Go gateway for Server-Sent Events (SSE) and decoupled PostgreSQL persistence are handled with high precision.

## Strengths & Completeness
- **Architectural Boundary Adherence**: The plans strictly respect the control-plane/data-plane divide (D-26). Go retains ownership of PostgreSQL and HTTP transport, while Rust retains vector/graph processing and RAG orchestration without creating cross-boundary database connections.
- **Workflow Correctness**: `05-02-PLAN.md` correctly supersedes the original design document by enforcing D-06 (`ExtractGraphContext` runs *before* `RetrieveHybrid`). The zero-evidence early return (D-03) is preserved cleanly.
- **Resilience and Retries**: `05-03-PLAN.md` accurately scopes generation retries to exactly one replay, handling transient errors without applying arbitrary fallbacks (D-12, D-13, D-14).
- **Timeout Fixes**: The plans successfully recognize and mitigate the chi global timeout issue (Pitfall #1) in `05-06-PLAN.md`, isolating the `/rag/query` route and adding sub-second timeout config overrides for deterministic Tier 1 testing.
- **Decoupled Checkpointing**: The asynchronous, bounded FIFO drain checkpoint mechanism (`CheckpointHandoff`) designed across `05-01` and `05-05` avoids coupling heavy PostgreSQL writes to the critical path of the SSE client response (D-27).
- **Rule Adherence (`AGENTS.md`)**: `05-05-PLAN.md` strictly adheres to the unique per-test schema requirement (`newWorkflowCheckpointsIsolatedPostgres`), dynamically scoping the `search_path`, and applying `t.Fatalf` on query setup errors to prevent false-passing snapshot counts.

## Risks & Minor Recommendations

1. **Timeout vs. Cancellation Conflation (Pitfall Avoidance)**
   While `05-01` and `05-04` correctly map cancellation scenarios, ensure the `tokio::select!` block in `WorkflowRunner` explicitly differentiates between a completed `tokio::time::timeout` and the cancellation token. A generic timeout error must never be conflated with a client-initiated cancellation; the exact `NodeErrorKind` mappings (Timeout vs. Cancelled) must remain distinct.

2. **Graph Context Degradation**
   `05-02-PLAN.md` successfully captures the need for `ExtractGraphContextNode` to own its *inner* timeout race. Because `attempt_graph_augmentation` is natively infallible for logical failures, ensuring the inner timeout degrades silently (empty `graph_context`) instead of escalating to a hard `NodeFailed` correctly satisfies D-09. The implementation should be scrutinized during execution to verify the outer `tokio::select!` doesn't preempt the inner node-degrade timeout.

3. **Cross-Variant Fusion Complexity**
   In `05-02-PLAN.md`, the plan dictates running `fuse_candidates` per reformulation variant and then performing a cross-variant RRF pass (`fuse_across_variants`). While currently inert due to the `NoOpQueryReformulator`, ensure the new `fuse_across_variants` strictly bounds deduplicated memory consumption (via chunk identity) so it doesn't open a resource exhaustion vector when real HyDE/Multi-Query expansion lands in Phase 999.3.

4. **SSE Event Stream Drops**
   `05-06-PLAN.md` handles SSE transport framing. Keep in mind that SSE lacks a standard mid-stream error frame. The gateway must immediately close the connection on a gRPC `Recv()` transport failure without writing malformed data or a partial JSON frame.

## Final Verdict
**Approved.** The execution wave strategy (1 through 5) is safe and correctly unblocks dependencies sequentially. The plans demonstrate an advanced understanding of the codebase's abstractions, the `AGENTS.md` test isolation constraints, and the complex asynchronous Rust-to-Go gRPC boundaries. No critical structural or logical gaps were identified.

---

## Claude Review (sonnet, high)

The requested Claude lane completed with the recognized sonnet model at high effort. The full source-grounded review follows.

# Independent Review: Phase 5 Plans (05-01 through 05-06) — Lancet "State Machine & Workflow Events"

## Context

The user requested a cross-AI independent review of six execution plans for Phase 5 of the Lancet project (formalizing the `QueryRAG` pipeline into a Rust state machine with streaming events, PostgreSQL checkpoints, and a Go SSE gateway). This is a review/analysis task, not an implementation task — no code changes are proposed. The task explicitly requires verifying every plan claim against the actual repository source rather than trusting the plan text, so this review is built entirely from direct `Read`/`Grep`/`Bash` verification against `D:\Repos\lancet` (via two parallel read-only exploration passes plus targeted follow-up checks), not from re-stating the plans' own claims.

One limitation: `05-AI-SPEC.md` (552 lines, confirmed to exist at `.planning/phases/05-state-machine-workflow-events/05-AI-SPEC.md`) is referenced by all six plans as the authoritative source for the Rust `Node`/`WorkflowRunner` pattern, but its content was not provided in the review request and was not read for this pass. Claims that defer to it are flagged as unverified rather than asserted true or false.

---

## Cross-Cutting Finding (applies to 05-01 and 05-06 jointly)

**`buf.gen.yaml` drift window — the single biggest structural risk in this plan set.**

Confirmed via direct read, the repo's checked-in `buf.gen.yaml` is a **single unified template** covering both runtimes:

```yaml
version: v2
clean: true
plugins:
  - remote: buf.build/protocolbuffers/go:v1.31.0
    out: gateway/proto
  - remote: buf.build/grpc/go:v1.3.0
    out: gateway/proto
  - remote: buf.build/community/neoeinstein-prost:v0.5.0
    out: engine/src/pb
  - remote: buf.build/community/neoeinstein-tonic:v0.5.0
    out: engine/src/pb
```

`05-01-PLAN.md` Task 1 deliberately avoids running this template, instead running a **hand-rolled inline Rust-only template** in its `<verify>` block (`buf generate --template '{"version":"v2","plugins":[...engine/src/pb only...]}'`) so that `gateway/proto/*.pb.go` is left untouched and `gateway/main.go`'s existing unary `engine.QueryRAG` interface (confirmed `gateway/main.go:207`) keeps compiling.

This is the *correct* tactical choice for 05-01 in isolation, but it means that **between 05-01 landing and 05-06 landing**, the repository is in a state where:
- `proto/lancet/v1/lancet.proto` declares `QueryRAG` as server-streaming.
- The checked-in `buf.gen.yaml` — the standard, documented codegen command for this repo — would regenerate `gateway/proto/*.pb.go` with a **streaming** Go client if run as-is.
- `gateway/main.go` (confirmed unchanged until 05-06) still implements the **unary** `engine` interface (`main.go:207`, `grpcEngine.QueryRAG` at `main.go:280-287`).

Any developer, CI job, or parallel branch that runs the standard `buf generate` command during this window breaks the Go build. Neither plan documents this hazard, adds a guard, or notes that 05-01→05-06 must land as an effectively-atomic unit with no intervening standard codegen runs. This is worth flagging explicitly before execution, even though it doesn't block correctness of either plan's own file surface.

---

## 05-01-PLAN.md — Tracer: streaming wire contract, one-node runner, checkpoint channel

**Summary:** A well-grounded tracer plan. Every load-bearing citation (`query_rag` at `main.rs:1346`, `d1_status` at `main.rs:877-898` setting all three trailer keys, `LancetServiceImpl` fields at `main.rs:864-875` as `Arc<dyn Trait>`) checks out exactly against source. The plan correctly identifies that no server-streaming gRPC precedent exists in this codebase and correctly scopes itself to avoid breaking the Go build mid-wave.

**Strengths:**
- `main.rs:1346` (`query_rag`), `main.rs:877-898` (`d1_status`, confirmed sets `x-lancet-session-id`/`-correlation-id`/`-error-kind` trailer metadata) — both exact.
- `LancetServiceImpl` (not "RagEngineService" as some phase docs call it) confirmed at `main.rs:864-875` with `generator: Arc<dyn generation::Generator>`, `embedder: Arc<dyn EmbeddingProvider>`, `reranker: Arc<dyn rerank::Reranker>` — the exact DI shape the plan's `Node`/port pattern needs to mirror.
- `FakeGenerator` (`generation/mod.rs:467-512`, `call_count: AtomicUsize` + `responses: Mutex<Vec<Result<...>>>` + `with_responses`) is correctly identified as reusable — confirmed already used 20+ times in `engine/src/tests.rs` (e.g. `tests.rs:2709-2712` for two-response retry scenarios), so this isn't a speculative reuse claim.
- Correctly avoids touching `gateway/proto/*.pb.go`, keeping the Go build green through this plan alone (verified `gateway/main.go:207`/`280-287` untouched by 05-01's file list).

**Concerns:**
- **HIGH** — The `buf.gen.yaml` drift window described above. 05-01 introduces the hazard (05-06 later closes it), and nothing in 05-01 documents or guards against it.
- **MEDIUM** — `attempt_graph_augmentation` (`main.rs:1056-1236`, confirmed by direct read — `pub(crate) async fn attempt_graph_augmentation(database: &DatabaseManager, query_embedding: &[f32], settings: &GraphSettings) -> GraphAugmentationOutcome`) spans ~180 lines, substantially more than the ~1046-1080 range cited in the phase's own RESEARCH/PATTERNS docs. Doesn't block 05-01 itself, but is inherited context for 05-02.
- **MEDIUM** — The `CheckpointHandoff`'s "owned FIFO overflow sized to the maximum checkpoint boundaries for the fixed workflow" is a reasonable bound (≤5 nodes ⇒ ≤5 checkpoint records per query) but the plan never pins this as an explicit number anywhere in its must_haves or action text, leaving capacity sizing to executor judgment.
- **LOW** — Task 2's verify step gates on `--list` output containing the substring `workflow`, which confirms *some* test matched the filter but not that the specific new tests actually ran under that name.

**Suggestions:**
- Explicitly note the `buf.gen.yaml` hazard in the plan (or land 05-01+05-06 atomically) so a parallel branch/CI run can't silently break the Go build.
- Pin the `CheckpointHandoff` overflow capacity to a concrete number/formula in the plan text.

**Risk Assessment: MEDIUM** — sound design, but the undocumented `buf.gen.yaml` drift window is a real, currently-unmitigated build-breakage risk for anyone touching the repo mid-wave.

---

## 05-02-PLAN.md — ExtractGraphContext + RetrieveHybrid nodes, D-06 order, cross-variant RRF

**Summary:** Correctly reuses existing, verified retrieval/graph primitives (`Bm25Index` at `retrieval/bm25.rs:114`, `DenseRetriever` at `retrieval/dense.rs:25`, `attempt_graph_augmentation`) and grounds the D-06 graph-before-retrieval order in a real, confirmed code invariant rather than an assumption. The cross-variant RRF design is the plan's weakest point — technically sound but architecturally novel and effectively untested for its real target case.

**Strengths:**
- D-06's order is not just asserted but empirically confirmed: embed (`main.rs:1395-1424`) → graph (`main.rs:1426-1431`) → dense retrieval (`main.rs:1450-1476`), exactly matching the plan's claimed sequence and line numbers.
- `fuse_candidates`'s real signature (`fusion.rs:58-62`, `fn fuse_candidates(vector_candidates: Vec<Candidate>, bm25_candidates: Vec<Candidate>, settings: &RetrievalSettings) -> Result<Vec<FusedCandidate>, RetrievalError>`) is confirmed single-variant/single-pass — the plan's premise that cross-variant merging is genuinely new work (not duplicating an existing capability) holds.
- Confirmed no internal timeout inside `attempt_graph_augmentation` (grep for `tokio::time::timeout`/`Duration::from_sec` inside its body returns nothing), correctly motivating the plan's requirement that `ExtractGraphContextNode` own its own inner timeout race rather than relying solely on the runner's outer one.
- The `WorkflowDependencies` DI struct is explicitly framed as closing a real review-flagged gap ("the service-level dependency-injection correction for the Codex HIGH review finding") — appropriate given graph/dense/BM25 today have no injectable seam (only `Generator`/`EmbeddingProvider` do, confirmed via `LancetServiceImpl`'s fields).

**Concerns:**
- **MEDIUM** — The cross-variant fusion design (`fuse_candidates` once per variant, then a second RRF pass over each variant's *already rank-collapsed* `FusedCandidate` list, "sum deterministic `1/(rrf_k + rank)` contributions across variant-local fused ranks") is RRF-of-RRF: the second pass only sees each variant's already-compressed rank, not the underlying dense/BM25 scores. This is a defensible but non-standard composition invented for this plan, not an established retrieval pattern. Because the NoOp reformulator makes this dead code in v1 (single variant only), the risk is inert today but genuinely untested for real multi-variant behavior — the plan's "two-variant exact scores" unit test proves the *arithmetic* is deterministic, not that the retrieval-quality tradeoff of discarding per-source score magnitude twice is sound.
- **MEDIUM** — `attempt_graph_augmentation`'s real complexity (180 lines, confirmed) is understated by the phase's own upstream citations; the plan's Task 1 action text doesn't restate this, risking executor underestimation of the wrapping effort (entities-table access, embedding-based traversal, Cypher pattern matching per Phase 04.1 all live inside this function).
- **LOW** — The plan doesn't explicitly state that `Arc<dyn GraphQueryPort>`'s production adapter must own a *cloned* `DatabaseManager` (confirmed `#[derive(Clone)]` at `db/mod.rs:8-11`) rather than borrow one, which the `'static` bound implied by mirroring `Generator`'s `Arc<dyn Trait>` shape requires — likely obvious to a competent executor, but not stated.

**Suggestions:**
- Note `attempt_graph_augmentation`'s real span (~1056-1236) in the plan so the wrapping task isn't underscoped.
- Require at least one test with genuinely different (not just distinguishably-scored) per-variant rankings to validate the cross-variant RRF formula produces retrieval-sane output, ahead of 999.3 depending on it.

**Risk Assessment: MEDIUM** — architecture is sound and well-grounded in real code, but the double-RRF design is a novel, untested-at-scale invention, and the graph-node wrapping is more involved than the phase's own upstream docs suggest.

---

## 05-03-PLAN.md — AssemblePrompt + GenerateAnswer nodes, retry, full snapshots

**Summary:** Correctly separates the new cooperative-cancellation prompt path from the existing, Phase-3-locked synchronous `pack_evidence_and_graph_prompt` (confirmed at `prompt.rs:255`) rather than mutating it in place, and correctly distinguishes the per-attempt provider timeout from a new node-level budget. The plan's two largest pieces of new, must-be-correct logic — cooperative cancellation granularity and the checkpoint size-truncation ladder — are both underspecified relative to their complexity.

**Strengths:**
- `pack_evidence_and_graph_prompt` confirmed as a synchronous function at `prompt.rs:255`; introducing a new async `_cooperative` sibling rather than rewriting it in place is a low-risk way to add yield/cancellation points without disturbing Phase 3's locked semantics (which the plan explicitly requires to stay unchanged).
- Correctly distinguishes `GENERATION_TIMEOUT` (`openrouter.rs:24`, confirmed `Duration::from_secs(30)`, wrapped per-call at `openrouter.rs:626`) from the new node-level outer budget — this is a previously-flagged real bug risk (reusing the per-attempt constant as the node's wall-clock budget) that the plan correctly avoids.
- The retryable/non-retryable `GenerationErrorKind` split is grounded in the actual seven confirmed variants (`generation/mod.rs:406-414`: `InvalidRequest, SupportedParameters, ProviderError, SchemaValidation, Timeout, Cancelled, SessionCorrelation`), with no invented categories.

**Concerns:**
- **HIGH** — "Cooperative prompt assembly" (checking a `CancellationToken` and yielding between bounded work units inside the candidate/render/tokenization loop, explicitly rejecting a bare non-preemptible `spawn_blocking`) is the right *design* call, but the plan gives no concrete yield granularity (e.g., "once per candidate" vs. "once per N tokens"). Too coarse a yield interval means the node isn't actually preemptible before its timeout fires (defeating the whole point of this task); too fine adds scheduling overhead. This is left entirely to executor judgment despite being the crux of the task's stated purpose.
- **MEDIUM** — The checkpoint size-truncation ladder (full DTO → replace prompt/evidence/graph-fact text with markers → replace candidate content/`encoded_blocks` → fixed `CheckpointFallbackV1` on any serialization error, asserted ≤262144 bytes) is a multi-stage must-never-fail contract. The acceptance criteria cover "oversized" and "NaN/Infinity-score" fixtures but not the case where a *single* field (e.g. `assembled_prompt` alone) already exceeds the budget before any candidate-level truncation runs — a plausible real scenario given large evidence packing — which could silently over-trigger the Fallback path without a test catching it.

**Suggestions:**
- Specify a concrete yield granularity for the cooperative prompt-packing loop (e.g., yield once per evidence candidate, bounded by existing `RetrievalSettings` limits).
- Add a fixture where a single oversized field alone exceeds the 256 KiB budget, to prove the size ladder degrades correctly at that stage too, not just in aggregate.

**Risk Assessment: MEDIUM** — correct design intent throughout, but the two pieces of genuinely new, must-be-infallible logic (cooperative cancellation, checkpoint size ladder) are underspecified relative to how much can silently go subtly wrong in each.

---

## 05-04-PLAN.md — Tier 1 deterministic test harness (Wave 5, depends on 05-03)

**Summary:** The most soundly-grounded plan of the six. It builds directly on already-proven, already-heavily-used fixture patterns (`configured_service` at `tests.rs:713-739`, `FakeGenerator::with_responses` already used 20+ times) rather than inventing new test infrastructure, and its explicit prohibition against testing a "disconnected toy runner" targets a real, previously-identified failure mode.

**Strengths:**
- `configured_service` (`tests.rs:713-739`) confirmed to already build a `LancetServiceImpl` from injected `Arc<dyn EmbeddingProvider>`/`Arc<dyn generation::Generator>`/`Arc<dyn rerank::Reranker>` — extending this exact factory to also populate `WorkflowDependencies`, rather than building a parallel harness, is the correct reuse.
- `FakeGenerator::with_responses` confirmed already exercised for multi-call and failure-injection scenarios (`tests.rs:2709-2712`, `tests.rs:3109`) — the plan's retry/cancellation-gate tests extend a pattern with real prior mileage in this codebase, not a speculative one.
- The prohibition on "a fake path that bypasses `LancetServiceImpl` dependency construction" is a concrete, testable guard against the single most common way this kind of test suite silently loses coverage.

**Concerns:**
- **MEDIUM** — `engine/src/tests.rs` is confirmed to already be 6,870 lines / 244KB. This plan adds substantial new fixtures (multiple new `Fake*` port types, `RecordingCheckpointSink`, ~15 named scenarios) into the same already-enormous single file. Not a correctness risk, but a navigability/merge-conflict risk the plan doesn't address (e.g. via a `workflow`-scoped test submodule).
- **LOW** — The instruction to wrap `Notify::notified()` rendezvous waits in bounded timeouts *and* give spawned fakes an abort-on-drop guard is sound anti-hang advice, but the plan doesn't state that the guard must be explicitly disarmed after a successful join — if missed, a `Drop`-triggered abort racing against an already-successful task completion could produce noisy (if harmless) abort-on-drop log output on green runs.

**Suggestions:**
- Consider a `engine/src/workflow/tests.rs`-style submodule for new Phase 5 fixtures rather than continuing to grow the single 6,800-line file (non-blocking, hygiene only).
- State explicitly that abort-handle guards must be disarmed on the success path before/after the join.

**Risk Assessment: LOW** — the strongest plan in the set; its risks are code-organization hygiene, not functional correctness.

---

## 05-05-PLAN.md — PostgreSQL checkpoint persistence (Wave 5, depends on 05-03 and 05-06)

**Summary:** Correctly anticipates and mitigates a real, easy-to-miss gap this review independently found: `gateway/sqlc.yaml` and `gateway/atlas.hcl` point at two *separate* schema files (`db/schema.sql` vs. `db/schema.hcl`) with no automated sync tooling in the repo. The plan explicitly requires mirroring the new table into both. Its main open risk is coordination with 05-04 over a shared concurrency contract, both landing in the same nominally-parallel wave.

**Strengths:**
- Confirmed the dual-schema-source gap is real (`gateway/sqlc.yaml` → `db/schema.sql`; `gateway/atlas.hcl` → `db/schema.hcl`; no `migrations/`, `Makefile`, or `justfile` enforcing parity) — the plan's Task 1 action text explicitly requires updating both files, correctly closing a gap that would otherwise silently desync generated Go types from the Atlas-applied DB schema.
- Confirmed `gateway/db/models.go`/`query.sql.go` are genuinely sqlc-generated (header: `sqlc v1.31.1`) with no `WorkflowCheckpoint` type or `jsonb` column precedent anywhere today — the plan's explicit requirement that `models.go` contain the generated model (framed as correcting "the review's missing-model-file finding") targets a real, confirmed gap.
- Correctly avoids extending `newD04IsolatedPostgres` (confirmed at `main_test.go:1635-1680`, which only clones `documents` and `document_reconciliation_intents` at lines 1645-1646) — building a dedicated `newWorkflowCheckpointsIsolatedPostgres` instead keeps that helper's scope from silently growing to cover an unrelated table.
- The blocking `checkpoint:decision` gate before schema/codegen changes matches the plan's own `reversibility="one-way"` framing for a durable schema addition — appropriate use of a human checkpoint.

**Concerns:**
- **MEDIUM** — 05-05 (Wave 5) and 05-04 (also Wave 5, "parallel" per ROADMAP.md) both depend on the `CheckpointHandoff`/`CheckpointDispatcher` Full/Closed/Pending contract established in 05-01/05-06, and both build their own test coverage against it (05-04's `TestWorkflowCheckpointPersistenceUnderBackpressure` on the Rust side, 05-05's Go-side backpressure tests) without a stated dependency on each other. If an executor for either plan resolves an ambiguous edge case in that shared contract differently, both plans' tests could pass in isolation while asserting subtly inconsistent semantics — nothing in either plan states that both must treat 05-01/05-06's contract as the single source of truth rather than independently re-deriving compatible-but-not-identical behavior.
- **LOW** — Task 1's blocking verify command runs `docker compose up -d db` unconditionally; a developer with a pre-existing local Postgres already bound to `127.0.0.1:5432` (the exact binding confirmed in `docker-compose.yml`) could get a confusing silent-connect-to-wrong-instance failure mode rather than a clear error. Not something the plan needs to solve, but a one-line troubleshooting note would help.

**Suggestions:**
- Add a cross-reference note in both 05-04 and 05-05 stating that the `CheckpointHandoff`/`Pending`/overflow semantics from 05-01/05-06 are the single source of truth for both plans' tests.

**Risk Assessment: MEDIUM** — very well-grounded in real repo state (the dual-schema-source and missing-generated-model risks are both correctly caught), but the same-wave, no-stated-dependency relationship with 05-04 over a shared concurrency contract is an unaddressed coordination risk.

---

## 05-06-PLAN.md — Gateway SSE adapter, timeout config (Wave 2, depends on 05-01)

**Summary:** Correctly identifies and fixes the two most dangerous pre-existing Go-side gaps: the blanket 60-second `chi` timeout (confirmed to apply to `/rag/query` with no existing override) and the complete absence of any SSE/streaming-HTTP precedent in this codebase. Shares the `buf.gen.yaml` drift-window risk described above, since 05-06 is the plan that must close it.

**Strengths:**
- Confirmed `gateway/main.go:464`'s `r.Use(middleware.RequestID, middleware.RealIP, middleware.Recoverer, middleware.Timeout(60*time.Second))` applies globally, including to `Post("/rag/query", a.queryRAG)` at line 468, with no existing per-route override — the plan's requirement to exempt `/rag/query` (without a fixed replacement) is the correct fix given the aggregate worst-case node-timeout budget (5+10+15+2+65s ≈ 97s) already exceeds 60s.
- Confirmed zero existing SSE precedent (`text/event-stream`, `http.Flusher`, `http.NewResponseController` all absent from `gateway/`) and zero existing server-streaming gRPC precedent (`IngestDocument` is the only streaming RPC and is client-streaming only, confirmed `lancet.proto:9`, `lancet_grpc.pb.go:180-200/286`) — the plan correctly treats this as genuinely new infrastructure and budgets a dedicated wave for it rather than tucking it into the Rust-side work.
- The "first-frame prefetch" design (calling `Recv()` once before committing SSE headers/status 200) correctly accounts for a real, non-obvious gRPC-Go semantics gap: a server-streaming call that opens successfully can still fail on its first `Recv()` if the server errors before sending any message, so headers can't safely commit until one frame is confirmed.
- `trailerError`'s forwarding path (confirmed via a structural interface check `err.(interface{ Trailer() metadata.MD })` at `main.go:693`, not a concrete-type assertion) is correctly preserved as the pre-stream-error path distinct from the new in-band event/checkpoint path.

**Concerns:**
- **HIGH** — Task 1 explicitly runs "the repository's full `buf generate`" using the confirmed unified `buf.gen.yaml` template. This is exactly the command that, if run by anyone *before* 05-06 (i.e., during the 05-01→05-06 gap), would break the Go build. 05-06 is the plan that legitimately closes the gap, but nothing enforces that it runs immediately after 05-01 with zero intervening standard-codegen runs by any other actor (developer, CI, parallel branch).
- **MEDIUM** — The `CheckpointDispatcher`'s in-memory default sink (built in 05-06, ahead of 05-05's PostgreSQL sink one wave later) has no stated ownership after 05-05 lands — should it remain available as a test double, or be removed? 05-05's must_haves don't address this either. Likely resolves fine in practice (interface persists, only the default implementation changes) but is not explicitly stated in either plan.
- **LOW** — The "no fixed replacement gateway deadline" acceptance criterion is verifiable by code inspection (absence of a chi middleware wrapper) but the plan doesn't check whether `gateway/main.go`'s `http.Server` (if constructed explicitly) sets its own `ReadTimeout`/`WriteTimeout`/`IdleTimeout`, which could reintroduce the same problem at a different layer even after the chi-level fix lands.

**Suggestions:**
- Treat 05-01+05-06 as an effectively-atomic landing unit, or add an explicit repo-level guard/note against running the standard `buf generate` in between.
- Verify (or have the plan verify) whether `gateway/main.go` sets explicit `http.Server` timeout fields that could independently cap `/rag/query`.

**Risk Assessment: MEDIUM-HIGH** — correctly targets the two most dangerous pre-existing Go-side gaps, but is one half of the `buf.gen.yaml` drift-window risk, and that risk is only fully closed once both 05-01 and 05-06 have landed with nothing running standard codegen in between.

---

## Overall Assessment

Across all six plans, the phase-level `CONTEXT.md` decisions (D-01 through D-31) are consistently and correctly grounded in verified source citations — the plans are not inventing behavior contrary to the locked decisions, and most line-number citations checked out exactly or within a few lines. The two genuinely structural risks that recur across multiple plans are:

1. **The `buf.gen.yaml` drift window** (05-01 → 05-06) — a real, currently undocumented build-breakage hazard for anyone running standard codegen mid-wave.
2. **The Wave-5 coordination gap between 05-04 and 05-05** over the shared `CheckpointHandoff` concurrency contract, run "in parallel" per ROADMAP.md with no stated cross-dependency.

Neither is a fundamental design flaw — both are process/sequencing gaps in otherwise well-evidenced, well-scoped plans. The weakest *design* (as opposed to process) choice is 05-02's cross-variant RRF-of-RRF composition, which is architecturally defensible but untested against realistic multi-variant input and will remain so until Phase 999.3 lands.

**No plan should be blocked on these findings** — they are risks to flag and mitigate during execution (e.g., landing 05-01+05-06 together, adding a shared-contract note between 05-04/05-05, pinning the RRF-of-RRF test to non-trivial variant data), not defects requiring a re-plan.

---

## Consensus Summary

Both successful reviewers evaluated all six Phase 5 plans. Claude supplied concrete `file:line` evidence; AgY supplied a higher-level independent assessment without source-line citations.

### Agreed Strengths

- The plans preserve the Rust-owned orchestration boundary and the Go transport/control-plane boundary.
- The corrected graph-before-retrieval order in `05-02-PLAN.md` is well grounded and preserves the zero-evidence path.
- The plans take timeout, retry, streaming, and decoupled checkpointing concerns seriously, with the SSE first-frame and bounded checkpoint designs called out as important integration points.

### Agreed Concerns

- **Cross-variant retrieval fusion needs stronger validation.** Both reviewers flagged the novel cross-variant RRF composition as a risk area; add tests using genuinely different per-variant rankings and keep memory bounded before relying on the future reformulation port.
- **Cancellation and timeout behavior needs explicit implementation-level proof.** Both reviewers called out the need to preserve distinct cancellation/timeout semantics and to make cooperative cancellation yield granularity concrete enough to be effective without excessive scheduling overhead.

### Divergent Views

- Claude identified a **HIGH** `buf.gen.yaml` drift window between 05-01 and 05-06: standard code generation can produce streaming Go stubs while `gateway/main.go` still expects unary APIs. AgY did not identify this risk. Treat 05-01 and 05-06 as an effectively coordinated landing unit or add an explicit guard/note.
- Claude rated 05-06 MEDIUM-HIGH and identified additional coordination risks between 05-04 and 05-05 over the shared checkpoint contract; AgY gave an overall approval with only minor cautions.

### Follow-up

Use `/gsd-plan-phase 5 --reviews` to incorporate the findings. Give priority to the `buf.gen.yaml` sequencing hazard, explicit cancellation/truncation tests, cross-variant RRF validation, and a single source of truth for Wave-5 checkpoint concurrency semantics.
