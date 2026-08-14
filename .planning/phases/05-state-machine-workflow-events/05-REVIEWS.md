---
phase: 5
scope: gap-closure
reviewers: [antigravity, claude]
successful_reviewers: [antigravity, claude]
reviewed_at: 2026-08-14T18:14:02Z
source_head: 7c7ba0b2d0b7be749727a08bdbebc0a586c11314
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
  antigravity: 11632
  claude: 25335
---
# Cross-AI Plan Review — Phase 05 Gap Closure (Fresh)

## Antigravity Review

# Phase 05 Gap-Closure Re-Review: State Machine & Workflow Events (Plans 05-08 through 05-21)

## 1. Summary

This review independently evaluates the 14 additive gap-closure implementation plans (**05-08 through 05-21**) for Phase 05 (*State Machine & Workflow Events*) against the codebase at [`D:/Repos/lancet`](file:///D:/Repos/lancet).

The historical baseline (Plans 05-01 through 05-07) established the foundational gRPC streaming contract and library-level components, but left critical production gaps identified in [`05-VERIFICATION.md`](file:///D:/Repos/lancet/.planning/phases/05-state-machine-workflow-events/05-VERIFICATION.md):
1. **SC1**: [`engine/src/main.rs:1716-1748`](file:///D:/Repos/lancet/engine/src/main.rs#L1716-L1748) registered only 1 node (`ReformulateQueryNode`) and executed the monolithic [`execute_inline_query_rag_remainder`](file:///D:/Repos/lancet/engine/src/main.rs#L1234-L1537) inline path with an empty `WorkflowDependencies` container.
2. **SC2**: The production path discarded the event sink (`_sink` at [`main.rs:1738`](file:///D:/Repos/lancet/engine/src/main.rs#L1738)), emitting zero lifecycle events for the remaining 4 nodes and never emitting `AnswerChunk`.
3. **SC3**: `EngineSettings` ([`main.rs:172-180`](file:///D:/Repos/lancet/engine/src/main.rs#L172-L180)) lacked a `workflow` field, rendering all `[engine.workflow]` TOML keys dead; `query_rag` cancellation was never propagated to [`cancel.cancel()`](file:///D:/Repos/lancet/engine/src/main.rs#L1706); and production generation had no retry loop.
4. **SC4**: `events::checkpoint` ([`engine/src/workflow/events.rs:106-115`](file:///D:/Repos/lancet/engine/src/workflow/events.rs#L106-L115)) serialized only 7 of 19 `WorkflowContext` fields, while [`gateway/main.go:766`](file:///D:/Repos/lancet/gateway/main.go#L766) discarded `DispatchPending` results from [`checkpoint_sink.go`](file:///D:/Repos/lancet/gateway/checkpoint_sink.go#L168-L188).
5. **Traceability**: Historical summaries cited incorrect requirement identifiers.

Plans 05-08 through 05-21 systematically address every verified gap and review finding through a disciplined, 11-wave additive sequence (Waves 7–17).

---

## 2. Strengths

1. **Definitive Production Pipeline Wiring (05-08)**:
   Replaces the monolithic [`execute_inline_query_rag_remainder`](file:///D:/Repos/lancet/engine/src/main.rs#L1234-L1537) with `build_production_workflow`, properly registering all 5 nodes in D-06 order (`ReformulateQueryNode` $\rightarrow$ `ExtractGraphContextNode` $\rightarrow$ `RetrieveHybridNode` $\rightarrow$ `AssemblePromptNode` $\rightarrow$ `GenerateAnswerNode`). Injects real services into [`WorkflowDependencies`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L111-L135) and upgrades [`GraphQueryPort`](file:///D:/Repos/lancet/engine/src/workflow/ports.rs#L39-L45) to return typed `Vec<GraphFactBlock>` rather than unformatted strings.

2. **Clean Separation of Preflight, Provider Attempt, and Node Budgets (05-09, 05-13, 05-20)**:
   Resolves the critical timing risk flagged in prior reviews:
   - **Capability Preflight** (05-13): Separated into a dedicated 5s deadline with a successful-only cache, decoupling it from chat attempts.
   - **Generation Node Budget** (05-09, 05-20): Configured at 65,000ms, encompassing two 30,000ms provider attempts (`generation_timeout_secs = 30`) plus 5,000ms inter-attempt slack.
   - **Bootstrap Timing** (05-20): Introduces `Node::prepare` executed by [`WorkflowRunner`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs) *before* the 65s timer starts, ensuring the 102s total workflow budget ($97\text{s} + 5\text{s}$) holds without timer starvation.

3. **Concurrency-Safe BM25 Index Snapshotting (05-16, 05-18)**:
   Eliminates the lock contention in [`main.rs:1311-1321`](file:///D:/Repos/lancet/engine/src/main.rs#L1311-L1321) where `self.bm25_index.read().await` was held across asynchronous retrieval. Migrates the index ownership to `Arc<RwLock<Arc<Bm25Index>>>`, taking an $O(1)$ `Arc` clone and dropping the read guard immediately before awaiting retrieval, preventing stalled searches from blocking ingestion writes.

4. **Exhaustive Type-Safe Dispatch & Provenance (05-14, 05-17, 05-21)**:
   Replaces stringly dispatch in [`WorkflowRunner`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L105-L113) with a closed `NodeKind` enum (05-14). Protobuf additions (05-17) add `variant_count` (tag 10) and `variant_identities` (tag 11) to `RetrievalSnapshot` and `notices` (tag 6) to `WorkflowCompletedEvent` without changing tags 1–9. `VariantProvenanceSource` (05-21) types the fusion source enum while preserving lowercase wire formatting.

5. **Lossless Checkpoint Dispatch and End-to-End SSE Integrity (05-10, 05-11, 05-19)**:
   - `events::checkpoint` (05-10) now serializes all 19 `WorkflowContext` fields.
   - [`gateway/main.go`](file:///D:/Repos/lancet/gateway/main.go#L763-L769) (05-11) manages `DispatchPending` and drains accepted envelopes on shutdown.
   - Comprehensive cross-runtime SSE tests in [`gateway/main_test.go`](file:///D:/Repos/lancet/gateway/main_test.go) verify real engine execution, client disconnect cancellation via `httptest.NewServer`, EOF watchdog errors (`STREAM_EOF_WITHOUT_TERMINAL`), and terminal notice preservation without fabricated answers (05-19).

6. **Target-Aware Test Seam and Historical Preservation (05-12, 05-18)**:
   - 05-18 splits the compilation targets: `cargo test --lib` tests generic fake-port workflows, while `cargo test --bin engine` tests production service builders, preventing fake symbols from leaking into release binaries (05-15).
   - 05-12 verifies exact git blob hashes for historical plans 05-01 through 05-07, maintaining an immutable audit trail while providing canonical corrections.

---

## 3. Concerns

### MEDIUM Severity

#### 1. In-band Disconnect Guard Race in Gateway SSE Writer (`gateway/main.go`)
- **Location**: [`gateway/main.go:758-827`](file:///D:/Repos/lancet/gateway/main.go#L758-L827) / Plan 05-11 Task 1
- **Mechanism**: In `writeWorkflowEventSSE`, the handler converts gRPC stream errors into `stream_error` SSE frames. When a client disconnects, `r.Context().Done()` fires, and the downstream gRPC call returns a canceled status. If the loop attempts to write a `stream_error` frame to a broken HTTP response writer without first checking `r.Context().Err()`, it can trigger secondary broken-pipe write errors and noisy error logging.
- **Resolution in Plan**: Plan 05-11 Task 1 includes an explicit acceptance criterion requiring `r.Context().Err()` check immediately before writing or flushing any error frame on post-open receive branches.
- **Recommendation**: Ensure the implementation in `gateway/main.go` wraps the SSE write/flush loop with:
  ```go
  if err := r.Context().Err(); err != nil {
      // Client disconnected; do not attempt further SSE writes
      return
  }
  ```

---

### LOW Severity

#### 2. Checkpoint JSON Snapshot Size in PostgreSQL
- **Location**: [`engine/src/workflow/events.rs:106-121`](file:///D:/Repos/lancet/engine/src/workflow/events.rs#L106-L121) / Plan 05-10 Task 2
- **Mechanism**: Serializing all 19 `WorkflowContext` fields—specifically the full 2048-dimensional float embedding (`query_embedding`) and complete prompt/evidence text—yields ~15–25 KB per checkpoint event JSON. Over a 5-node query generating 5 checkpoint rows, each query stores ~100 KB in PostgreSQL `workflow_checkpoints`.
- **Disposition**: Per decision D-23 and D-24, this is an explicitly accepted engineering trade-off for single-user local demo and debugging. Plan 05-10 Task 2 includes a test verifying payload byte size without truncation.

#### 3. Protection of Hand-Written Module Glue During Protobuf Generation
- **Location**: [`engine/src/pb/mod.rs`](file:///D:/Repos/lancet/engine/src/pb/mod.rs), [`buf.gen.yaml`](file:///D:/Repos/lancet/buf.gen.yaml) / Plan 05-17 Task 1
- **Mechanism**: Default `buf generate` behavior can delete unmanaged files in the output directory if `clean: true`. `engine/src/pb/mod.rs` is hand-written glue (`include!("lancet/v1/lancet.v1.rs")`).
- **Disposition**: Plan 05-17 Task 1 explicitly sets `clean: false` in `buf.gen.yaml` and adds an automated pre/post generation file content assertion.

#### 4. Cross-Platform PowerShell Script Assertions
- **Location**: `<verify>` blocks across plans 05-08 through 05-21
- **Mechanism**: The automated verification snippets use Windows PowerShell syntax (`Get-Content`, `$LASTEXITCODE`, `Select-String`, `-match`). On Windows pwsh environments, this executes cleanly, but in standard POSIX bash CI environments, these would require `pwsh` or translation.
- **Disposition**: The project workspace environment is Windows with pwsh, where all verify commands execute natively.

---

## 4. Specific Suggestions

1. **Atomic Stream Drop Guard in Rust (`engine/src/main.rs`)**:
   In Plan 05-09, implement the `CancellationToken` trigger upon tonic stream drop using an explicit wrapper struct around `tokio_stream::wrappers::ReceiverStream`:
   ```rust
   struct CancellableStream<S> {
       inner: S,
       cancel: tokio_util::sync::CancellationToken,
   }
   impl<S: Stream + Unpin> Stream for CancellableStream<S> {
       type Item = S::Item;
       fn poll_next(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Option<Self::Item>> {
           Pin::new(&mut self.inner).poll_next(cx)
       }
   }
   impl<S> Drop for CancellableStream<S> {
       fn drop(&mut self) {
           self.cancel.cancel();
       }
   }
   ```
   This guarantees that if the client closes the connection and tonic drops the response stream, `cancel.cancel()` fires immediately, aborting the spawned Tokio task.

2. **Deduplication in `WorkflowContext::merge_notices` (`engine/src/workflow/mod.rs`)**:
   In Plan 05-16, when merging notices, check for existing identical `(code, message)` pairs so that transient retry or degradation does not produce redundant identical notice entries.

3. **Verify PostgreSQL Schema Isolation in Gateway Tests (`gateway/main_test.go`)**:
   In Plan 05-11 Task 2, adhere strictly to the `AGENTS.md` Code Review Guidelines for database tests: ensure `TEST_DATABASE_URL` uses `CREATE SCHEMA IF NOT EXISTS "test_schema_..."` and all external before/after count queries fail fatally (`t.Fatalf`) on error.

---

## 5. Overall Risk Assessment

| Risk Dimension | Rating | Justification |
|---|---|---|
| **Architectural Soundness** | **LOW RISK** | Preserves the core Go control plane / Rust data plane split. Uses standard Rust async state machine patterns and idiomatic Go gRPC-to-SSE streaming. |
| **Requirements & Gap Closure** | **LOW RISK** | Direct 1:1 closure for all 5 baseline verification failures (SC1–SC4, Traceability) and all review findings (CR-01..08, WR-01..14, IN-01..04). |
| **Dependency & Wave Ordering** | **LOW RISK** | Strict monotonic DAG across Waves 7–17 with no cyclic dependencies. Seams between library fakes, protobuf bindings, BM25 locks, and production binaries are cleanly decoupled. |
| **Backward Compatibility & Scope Discipline** | **LOW RISK** | Additive protobuf tags (10, 11 on snapshot; 6 on completed event) preserve wire compatibility. Observability spans and token metadata remain cleanly fenced for Phase 06. |

### Conclusion
The revised plan set (05-08 through 05-21) is **architecturally sound, meticulously verified against the live codebase, and ready for execution**. It completely resolves the gaps identified in the baseline report and provides rigorous, automated verification gates for every milestone requirement.


---

## Claude Review

# Cross-AI Plan Re-Review — Phase 05 Gap Closure (05-08 … 05-21)

*Independent re-review against the working tree at `D:/Repos/lancet`, HEAD `7c7ba0b`. No prior review artifact was used as evidence; `05-REVIEWS.md` was read only to confirm which prior findings the revision claims to have closed, and every such claim was re-checked against source. No files were edited.*

---

## 1. Summary

The revision closes the three ownership gaps the previous cycle raised, and I confirmed each closure against source: `buf.gen.yaml`'s `clean: true` hazard to the hand-written `engine/src/pb/mod.rs` is now owned by 05-17 with a pre/post byte-comparison guard; the `GraphQueryPort` → typed-`GraphFactBlock` migration now has `engine/src/workflow/ports.rs` in 05-08's `files_modified`; and `engine/src/bin/seed_rag_fixture.rs` is now owned by 05-11 with exact UUIDs and read-back assertions. 05-12's frozen-baseline guard is genuinely sound — I spot-checked eleven of the fourteen literal blob hashes against `git rev-parse HEAD:<path>` and all eleven match byte-for-byte, and `git diff --name-only HEAD~2 HEAD` shows the last two commits touched only 05-08…05-21 plus supporting artifacts.

The remaining risk has moved from *ownership* to *compile ordering*. Reassigning the `RetrievalSnapshot` literal population from 05-17 to 05-16 (the fix for last cycle's MEDIUM-3) removed the only files 05-17 owned that would keep the crate compiling. As written, **05-17 lands two additive protobuf fields at wave 11 that break four exhaustive Rust struct literals in three files it does not own, and 05-17's own Task 2 verification cannot pass.** The crate then stays non-compiling through wave 15. A second, milder instance of the same pattern exists from wave 7 (`GraphQueryPort`) and wave 11 (BM25 fixture shape), where the binary *test* target is knowingly red for several waves and every gate in that window is a `cargo check` that does not compile `#[cfg(test)]` code.

None of this is a design problem. HIGH-1 is a one-line-per-site fix or a wave reorder; HIGH-2 and HIGH-3 are scope additions to plans that already own the neighbouring files.

---

## 2. Strengths

**The 05-12 preservation guard is verifiably correct, not aspirational.** All eleven spot-checked frozen paths match their literal hashes at HEAD:

| Path | Declared | `git rev-parse HEAD:<path>` |
|---|---|---|
| `05-01-PLAN.md` | `1862cb91…` | `1862cb918c2d08179f5739fa215a945abc2325ca` ✓ |
| `05-02-PLAN.md` | `2a80165e…` | `2a80165ebbba5e4a6c4f75d277bc5fda690cf9a6` ✓ |
| `05-06-PLAN.md` | `8e4511e1…` | `8e4511e1200d7c1e8d676a3d770bd408dba554f4` ✓ |
| `05-07-SUMMARY.md` | `b7bdad3e…` | `b7bdad3e680f6a0473680ceab7548269ec3e5d0c` ✓ |

(remaining seven likewise). The guard's use of *both* `git rev-parse HEAD:<path>` and `git hash-object -- <path>` plus staged/unstaged path-scoped diffs is stronger than a plain `git diff --check`, and the path scoping means 05-08 editing `engine/src/main.rs` in the same wave cannot trip it.

**05-13's provider diagnosis is exact.** `execute_one_call` opens with `self.check_supported_parameters().await?` (`engine/src/generation/openrouter.rs:376`), that function maps *every* `reqwest` transport error — including `is_timeout()` — to `GenerationErrorKind::SupportedParameters` (`:297-302`), and `GenerateAnswerNode` treats exactly that kind as non-retryable (`engine/src/workflow/nodes/generate.rs:73-76`). A transient DNS failure therefore suppresses the D-12 mandated retry today. The whole thing is additionally wrapped in the shared `timeout(self.config.timeout, …)` at `:629`, so a slow `/models` eats the generation budget. The fix — dedicated 5s deadline, successful-only cache, split the error kinds — targets the precise mechanism.

**05-18's BM25 arithmetic is right to the count.** `rg 'bm25_index(1|2)?: Arc::new|RwLock::new\(bm25_index'` returns 18 in `engine/src/tests.rs` and 1 in `engine/src/main.rs` — exactly the 18 the plan asserts, plus the single production site 05-16 owns. The old and new regexes are correctly non-overlapping: after migration the text following `RwLock::new(` is `Arc::new(`, so the old pattern cannot match. `engine/src/tests.rs:11` is confirmed to be the only `pub mod workflow_phase5;`, and `engine/src/lib.rs:1-13` has none, so the target split is a clean move.

**05-11's cross-runtime harness is real and non-skippable.** `gateway/main_test.go:2167-2177` resolves `engine/target/debug/engine[.exe]` and `t.Fatalf`s when absent; `:2115` makes the mock provider reject a chat request whose `Messages[1].Content` lacks `DENSE_FIXTURE_MARKER`/`LEXICAL_FIXTURE_IDENTIFIER_2026`; `:2329` asserts both markers in the recorded evidence. Extending that mechanism to three graph markers is the correct shape. The seeder gap it fixes is confirmed: `engine/src/bin/seed_rag_fixture.rs:73-75` opens only `documents_table`, `nodes_table`, `edges_table`, while `engine/src/db/mod.rs:144,152` show `entities_table()`/`entity_edges_table()` exist and are what `attempt_graph_augmentation` reads.

**The wave DAG is acyclic and monotonic.** Re-walked every `depends_on` against every `wave:`; no back-edge. 05-18's explicit rejection of a direct 05-16 edge (`05-18-PLAN.md:48-50`) is correct reasoning — `05-16 → 05-15 → 05-18` already exists.

**The core gap diagnoses hold.** `engine/src/workflow/events.rs:106-115` genuinely serializes 7 of 18 `WorkflowContext` fields; `engine/src/main.rs:1706` genuinely creates a `CancellationToken` nothing cancels; `EngineSettings` genuinely has no `workflow` field while all three overlays ship seven `[engine.workflow]` keys.

---

## 3. Concerns

### HIGH-1 — 05-17's additive proto fields break four exhaustive Rust literals it does not own; its own Task 2 verification cannot pass

`prost` generates plain structs with no `#[non_exhaustive]`, and every in-repo `RetrievalSnapshot` / `WorkflowCompletedEvent` literal is **exhaustive field-init with no `..Default::default()`**:

| Site | Message | Compiled by |
|---|---|---|
| `engine/src/workflow/nodes/retrieve.rs:145-155` | `RetrievalSnapshot` | lib **and** bin |
| `engine/src/main.rs:1352-1372` | `RetrievalSnapshot` | bin |
| `engine/src/main.rs:1499-1527` | `RetrievalSnapshot` | bin |
| `engine/src/workflow/events.rs:131-137` | `WorkflowCompletedEvent` | lib **and** bin |

05-17's `files_modified` is `proto/lancet/v1/lancet.proto`, `buf.gen.yaml`, `engine/src/pb/mod.rs`, four generated bindings, and `engine/src/retrieval/tests.rs`. **None of the four literal sites.** Adding `variant_count = 10` / `variant_identities = 11` and `notices = 6` therefore produces four `missing field` errors the moment `buf generate` runs.

05-17 Task 2's own gate is `cargo test --lib … --exact retrieval_snapshot_variant_provenance_wire_contract`, which compiles the library — and `retrieve.rs` and `events.rs` are both in the library. **05-17 cannot pass its own verification block.**

The window is not brief. Retrieval literals are fixed by 05-16 at **wave 13**; the terminal literal by 05-19 at **wave 15**. 05-17 is **wave 11**. So the crate is non-compiling for both targets across waves 11–15, taking down every gate in that window:

- 05-18 (wave 11, same wave — ordering ambiguous): `cargo test --lib` ×2, `cargo check --bin engine`
- 05-15 (wave 12): `cargo test --lib` ×3
- 05-16 (wave 13): `cargo test --bin engine` ×8
- 05-10 and 05-21 (wave 14): `cargo test --lib` ×5

Go is unaffected and I confirmed why: `gateway/main_test.go:841,934,2356` use named-field literals (additive-safe in Go) and `gateway/main.go:928` builds a local `retrievalSnapshotDTO`, not the generated type.

This is a deterministic hard stop, and it is a *regression introduced by the fix* for last cycle's MEDIUM-3: giving 05-16 sole ownership of the production literals left 05-17 owning nothing that keeps the crate green.

### HIGH-2 — The binary test target is knowingly non-compiling from wave 7, and the repo's own full-suite sampling rule is not exempted

Two deliberate, documented type breaks are hidden behind gates that cannot see them:

1. **`GraphQueryPort` (wave 7).** 05-08 changes `query_graph` from `Result<String, NodeError>` (`engine/src/workflow/ports.rs:39-45`) to a typed fact vector and updates the fakes in `ports.rs`, but its `<scope_rationale>` explicitly defers `engine/src/tests.rs` to 05-18 (wave 11). `engine/src/tests.rs` has **25** `Fake*Port` references. Every gate in waves 7–10 (05-08, 05-09, 05-13, 05-14) is `cargo check --bin engine`, which does **not** compile `#[cfg(test)]` code — so the break is structurally invisible to the plans that cause it.
2. **BM25 ownership (waves 11–13).** 05-18 migrates the 18 `engine/src/tests.rs` fixtures to `Arc<RwLock<Arc<Bm25Index>>>` at wave 11, while the production field `bm25_index: Arc<tokio::sync::RwLock<Bm25Index>>` (`engine/src/main.rs:864`, mirrored at `engine/src/tests.rs:338`) only changes at 05-16, wave 13. Two waves of type mismatch, again gated only by `cargo check --bin engine`.

The plans are honest about this — 05-18's acceptance criteria say "05-16 later compiles the binary/test handoff". But `.planning/config.json`'s `test_command` is `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)`, and `05-VALIDATION.md` §Sampling Rate says *"After every later wave: Run the full suite command above plus the current wave's focused commands."* Neither is exempted for waves 7–12. Any wave-merge sampling run, `/gsd-execute-phase` gate, or CI invocation in that window is red for reasons the plan set considers acceptable but never states.

### HIGH-3 — No plan owns the four existing binary tests that drive the production `query_rag` handler

`engine/src/tests.rs` invokes `service.query_rag(...)` against a directly-constructed `LancetServiceImpl` at **`:352`** (`query_rag_stream`), **`:2378`**, **`:2442`** (inside `query_rag_tracer`, `:2383`), and **`:3403`**. Today those exercise a one-node runner plus `execute_inline_query_rag_remainder`. After 05-08 registers five real nodes backed by real adapters, the same tests run a materially different pipeline — real `attempt_graph_augmentation` against LanceDB, real `DenseRetriever`, real BM25 — with only `FakeEmbedder`/`FakeGenerator` substituted.

05-18 owns `engine/src/tests.rs`, but only for module registration, fake-port call sites, and BM25 fixture shape. Neither it nor 05-08 mentions these four tests.

Worse, `query_rag_tracer` is the specific test `05-VERIFICATION.md` §"Why the green test suite is not evidence" indicts for asserting only *at least one* `NodeStarted` / `NodeCompleted` / `Checkpoint` — satisfied by the single no-op node. **No plan in 05-08…05-21 strengthens or retires it.** After 05-08 it will still pass while asserting nothing about node count, node names, or `AnswerChunk`, so the phase's flagship false-confidence test survives the gap closure intact.

### MEDIUM-1 — 05-08's production test bodies live in an unregistered module, so its gate cannot compile them; nine filters first execute in one wave-16 task

`engine/src/tests/workflow_phase5_production.rs` does not exist (glob over `engine/src/tests/**` returns only `workflow_phase5.rs`). 05-08 creates it, but registration is deferred to 05-18. An unregistered `.rs` under `src/tests/` is compiled by **no** target — so 05-08's, 05-09's, 05-13's, and 05-14's `cargo check` gates pass regardless of whether those bodies are syntactically valid, let alone correct. Their only real check is `Get-Content … .Contains('<test name>')`.

All nine production filters (`workflow_phase5_production_five_node`, `…_dependencies_are_real`, `…_generation_retry_tracer`, `…_generation_retry_exhausted`, `…_nodekind_tracer`, `…_nodekind_dispatch`, `…_nodekind_exhaustive`, `…_production_context_population`, `…_production_reachability`) are first *executed* in 05-20 Task 2, wave 16. Six waves of blind test authoring converge on one late gate; a multi-test failure there is expensive to unwind.

### MEDIUM-2 — 05-08's dependency guard omits the dense-retrieval source, and Task 3's promised `self.nodes` guard is absent from its verify block

Dense retrieval is `DenseRetriever::new(self.nodes.clone())` — `nodes` is a distinct `LancetServiceImpl` field (`engine/src/tests.rs:337`). 05-08 Task 1's required-field loop is `('self.embedder','self.database','self.bm25_index','self.reranker','self.generator')` — no `self.nodes`. Task 3's `<action>` promises "guards for … a production builder with no `self.nodes` registration", but Task 3's `<verify>` block contains no such check. A builder that constructed a dense adapter from something other than the real table would satisfy every shipped guard.

### MEDIUM-3 — 05-16's O(1)-snapshot source guard is vacuous

```powershell
if ($main -notmatch 'Arc::clone|clone\(\)') { throw 'production BM25 snapshot does not show O(1) handle cloning' }
```

`clone()` occurs pervasively throughout `engine/src/main.rs` (e.g. `:1353`, `:1517-1518`, `:1285`), so this condition can never fire. It contributes nothing. The plan's stated invariants — *no `RwLockReadGuard` held across `.await`* and *no corpus deep copy* — are real and worth guarding, but only `workflow_phase5_bm25_snapshot_releases_lock` actually tests them. (The behavioural test is sound; the plan is also right that it must supply its own writer, since `rg 'bm25_index.write'` over `engine/src` returns nothing.)

### MEDIUM-4 — The shipped overlay contract test only checks key presence; no plan strengthens it, so 05-09's value contract has no repository regression

`engine/src/tests.rs:260-290` (`config_workflow_timeout_overlays_match_contract`) asserts only `content.contains(key)` for the seven keys across the three overlays. It does not assert a single value. 05-09 enforces `generation_timeout_secs = 30`, the six upstream 5000/10000/10000/4000/15000/2000 values, and `generation_node_timeout_ms = 7000` **only** through a PowerShell string match inside its own `<verify>` block — which runs once, at execution time, and leaves nothing behind. A later edit reverting `config/config.verify.toml` still passes the shipped suite, and the live 7000ms proof silently stops meaning what it claims.

This matters more than usual because 05-09's live proof is the *only* wall-clock evidence in the phase that configuration reaches production; every other timing check is paused-clock or fake-port semantics by explicit design.

### LOW-1 — 05-09 repurposes a Phase-02-owned overlay without saying so

`config/config.verify.toml` carries `lancedb_path = "./data/lancedb-verify-02-06"` and is consumed by `scripts/phase02_live_evidence.py:179` (`resolve_lancedb_path`). I verified the script reads only `lancedb_path`, so 05-09's `generation_timeout_secs` 1 → 30 change is safe today. But the file now serves two phases' live-evidence harnesses with no comment recording that, and the next Phase-02 debt closure could silently reintroduce a conflict.

### LOW-2 — Retiring `execute_inline_query_rag_remainder` is cleaner than 05-08 allows for

`rg` over `engine/src/tests.rs` shows **zero** references to `execute_inline_query_rag_remainder`; the only inline-bridge test callers are `run_inline_prompt_generation_remainder` at `:7134`, `:7210`, `:7323`. So the production monolith can simply be deleted. 05-08's guard permits it to survive outside the `query_rag` region — in which case it becomes an unreferenced private method and a dead-code warning. Prefer deleting it and asserting its absence from `main.rs` entirely.

### LOW-3 — `clean: false` is right for `mod.rs` but disables cleanup for the Go output roots too

`clean` is a top-level toggle in `buf.gen.yaml:2`, applying to all four plugin `out` roots (`engine/src/pb` ×2, `gateway/proto` ×2). Setting it `false` means stale generated files in `gateway/proto` and `engine/src/pb` will no longer be removed after a message rename or removal. The alternative 05-17 itself mentions — moving the glue out of the output tree (declare the module inline in `lib.rs`/`main.rs`) — preserves cleanup while making the hazard structurally impossible. Worth preferring, given `05-VERIFICATION.md:201` records this file was already hand-restored once after 05-07.

---

## 4. Specific Suggestions

1. **(HIGH-1)** Either add `engine/src/workflow/nodes/retrieve.rs`, `engine/src/main.rs`, and `engine/src/workflow/events.rs` to 05-17's `files_modified` with a minimal "add the new fields with zero/empty values" instruction (05-16 and 05-19 then *populate and assert* them, preserving the ownership split the revision wanted), **or** move 05-17 to wave 12+ and make 05-16/05-19 depend on it while they land the literals in the same wave. The minimal-touch variant is cleaner: 05-17 makes the crate compile, 05-16/05-19 make it correct.
2. **(HIGH-1, defensive)** Add to 05-17 Task 1's verify, after `buf generate`: `cargo check --lib --manifest-path engine/Cargo.toml --locked` and `cargo check --bin engine …`. Any future additive proto change then fails at the wave that introduces it rather than two waves later.
3. **(HIGH-2)** Add one sentence to `05-VALIDATION.md` §Sampling Rate and to 05-08/05-18 stating that `cargo test --bin engine` is expected to be non-compiling from wave 7 until 05-16 lands, and that the full-suite sampling rule is suspended for waves 7–12. Alternatively, pull the `engine/src/tests.rs` fake-port migration forward into 05-08 (it already owns `ports.rs`, so the change is mechanical) and keep only the module registration in 05-18.
4. **(HIGH-3)** Give 05-18 (or 05-08) explicit ownership of `query_rag_stream` (`tests.rs:352`), `query_rag_tracer` (`:2383`), and the `service.query_rag(...)` call sites at `:3403` and `:2378` — at minimum to keep them compiling and passing; ideally to replace `query_rag_tracer`'s "at least one" assertions with exact five-node/one-`AnswerChunk` assertions, since that test is named in `05-VERIFICATION.md` as the mechanism by which the suite stayed green.
5. **(MEDIUM-1)** Have 05-08 register `workflow_phase5_production` in `engine/src/tests.rs` itself (one line), and have 05-18 only *move* the generic module. That makes `cargo check --bin engine` at wave 7 actually compile the production bodies. If the current split must stand, add `cargo test --bin engine --no-run` to 05-18 Task 1 so the four upstream plans' bodies compile at wave 11 rather than wave 16.
6. **(MEDIUM-2)** Add `self.nodes` to 05-08 Task 1's required-field list, and either implement Task 3's promised `self.nodes` guard or delete the promise from its `<action>`.
7. **(MEDIUM-3)** Replace 05-16's vacuous guard with something that can fail — e.g. assert the production BM25 region contains no `.read().await` whose guard binding is still live across a subsequent `.await`, or simply assert the field type text `RwLock<Arc<Bm25Index>>` appears in `engine/src/main.rs` and that `bm25_guard` does not appear within the retrieval adapter body.
8. **(MEDIUM-4)** Extend `config_workflow_timeout_overlays_match_contract` (`engine/src/tests.rs:260`) — or add a sibling in 05-09 — to assert the exact overlay values and the two inequalities (`10000 + 4000 < 15000`; `65000 ≥ 2×30000 + 5000`; `verify: generation_timeout_secs(30s) > generation_node_timeout_ms(7000ms)`), so the live-timeout proof's premises are protected by the repository suite rather than by a one-shot plan guard.
9. **(LOW-1)** Add a header comment to `config/config.verify.toml` naming both consumers (`scripts/phase02_live_evidence.py`, Phase 05 live generation-timeout harness).
10. **(LOW-2)** Change 05-08 Task 2 to delete `execute_inline_query_rag_remainder` outright and guard its absence from `engine/src/main.rs`, rather than only guarding the `query_rag` region.

---

## 5. Coverage Assessment

Mapped independently against `ROADMAP.md:317-323` and `05-VERIFICATION.md`'s five recorded gaps.

| Verified gap | Owning plans | Assessment |
|---|---|---|
| **SC1** — pipeline not a state machine in production | 05-08, 05-14, 05-16 | **Covered by design.** 05-08 Task 1's guard is the strongest in the set: region-extracted `query_rag`/`build_production_workflow`, five real `self.*` fields, ≥7 `Some(` slots against the seven-field `WorkflowDependencies` (`workflow/mod.rs:111-120`), exactly five `add_node`, positional D-06 order, `Fake*` and inline-remainder rejection. A library-only change cannot satisfy it. Weakened by MEDIUM-2 (`self.nodes` omitted) and HIGH-3 (existing production tests unowned). |
| **SC2** — events not emitted; `AnswerChunk` unreachable | 05-08, 05-10, 05-11, 05-17, 05-19 | **Covered; blocked by HIGH-1.** Typed delivery, one-source ordinals, atomic terminal guard, failure-terminal notices, post-open `stream_error` frames, and the real cross-runtime SSE proof are all owned. The generated `notices` field the failure path depends on is exactly what breaks the build at wave 11. |
| **SC3** — timeouts/retry/cancellation unwired | 05-09, 05-13, 05-14, 05-20 | **Covered.** Seven typed settings with `deny_unknown_fields`, stream-drop cancellation, preflight hoisted outside the node timer via a `Node::prepare` seam, the `97000 + 5000 = 102000` derivation (arithmetic checks out — graph counted once at 15s with 10s+4s nested), and both 4999ms/9999ms pre-deadline regressions. The one live wall-clock proof is under-protected (MEDIUM-4). |
| **SC4** — snapshots hollow; `DispatchPending` discarded | 05-08, 05-10, 05-11, 05-16 | **Covered.** 19-field serialization (vs. the 7 at `events.rs:106-115`), explicit pending ownership, drain-on-close, context-honouring sink, isolated-schema PostgreSQL tests. 05-10's explicit accept-and-measure decision on the 2048-dim embedding payload under D-24 answers last cycle's MEDIUM-4 properly. |
| **SC5** — `QueryReformulator` port | 05-08, 05-14 | **Covered.** Retained on the production path with typed `NodeKind::ReformulateQuery`, and the nine-variant admission correctly moved ahead of `NodeCompleted` — fixing the current `runner.rs:180-201` completed-then-failed sequence. |
| **Traceability** — two wrong `requirements-completed` lists, two overclaiming narratives | 05-12 | **Covered and verified.** Corrected lists match the PLAN declarations (`05-02-PLAN.md:22` = `[ORCH-01, ORCH-03, ORCH-05]` vs. `05-02-SUMMARY.md:47` = `[ORCH-03, RAG-01, RAG-02]`; `05-03-PLAN.md:19` = `[ORCH-01, ORCH-02, ORCH-03]` vs. `05-03-SUMMARY.md:46` = `[GEN-01, GEN-02, GEN-03, EVENT-03]`). Additive-only; historical files preserved by a machine-checkable guard. |

**Review-ledger coverage** (`05-REVIEW.md`: 8 CR / 14 WR / 5 IN): every finding has a named owner. CR-01/04 → 05-09; CR-02/03 → 05-08; CR-05 → 05-10; CR-06/07/08 → 05-11; WR-01 → 05-14; WR-02/04 → 05-13 + 05-10; WR-03/13 → 05-10; WR-05 → 05-08; WR-06 → 05-16; WR-07 → 05-16 + 05-19; WR-08/09 → 05-16 + 05-17; WR-10/11 → 05-15; WR-12 → accepted under D-24; WR-14 → 05-16; IN-01/04 → 05-14 + 05-08; IN-02/03 → 05-21; IN-05 → 05-20 (both named boundary tests). No orphans.

**Locked-decision compliance:** no regression. D-04, D-10 (`QueryGraph` still unary at `proto/lancet/v1/lancet.proto:12`; no plan touches it), D-18/D-19, D-21, D-23–D-29 preserved; D-30/D-31 fences respected. 05-17 correctly frames `variant_count`/`variant_identities` as D-07/D-08 provenance rather than deferred D-30 metadata. The one client-visible addition — 05-11's `stream_error` event with `GRPC_RECV_ERROR` / `STREAM_EOF_WITHOUT_TERMINAL` (neither string exists in `gateway/` today) — sits inside CONTEXT's "Claude's Discretion — exact SSE framing details" and is recorded in 05-12's errata. Defensible.

---

## 6. Overall Risk Assessment

**HIGH — on execution ordering, not design.**

Design risk is genuinely low and lower than last cycle: the plans target real mechanisms at real line numbers, the guards are unusually specific, the DAG is provably acyclic, the frozen-baseline guard is verified correct against `git`, and all three prior HIGH findings are closed with evidence.

Execution risk is elevated because HIGH-1 is a **hard stop with no workaround**: 05-17 cannot pass its own verification block as written, and the crate stays non-compiling for both Cargo targets across waves 11–15, taking down five downstream plans' gates. It is not a subtle interaction — it is `missing field` errors at four known line numbers, discoverable by adding one `cargo check --lib` to 05-17's verify block.

HIGH-2 and HIGH-3 are less severe but compound it: the plan set has adopted `cargo check --bin engine` as its standard gate precisely *because* it does not compile test code, which is what allows the wave-7-to-wave-13 binary-test break to stay invisible. That is a coherent strategy, but combined with HIGH-1 it means the phase's actual compile health is unobserved for roughly nine consecutive waves, and the four existing production-handler tests change behaviour inside that window with no owner.

With suggestions 1–4 applied (one file-inventory addition, two verify-block additions, one ownership assignment) I would rate this set **LOW-MEDIUM** and recommend execution. As written, I recommend one more bounded revision pass before the first plan runs.


---

## Consensus Summary

The fresh reviews agree that the revised 05-08 through 05-21 plan set is materially more complete and source-grounded than the prior version. The main disagreement is execution risk: AgY considers the design and dependency graph ready for execution, while Claude identifies deterministic compile-order and test-gate blockers that should be fixed before execution.

### Agreed Strengths

- The plan set directly targets the live verification failures: production five-node reachability and dependency injection (05-08/05-16), event and checkpoint completeness (05-10/05-11/05-17/05-19), timeout/retry/cancellation behavior (05-09/05-13/05-14/05-20), and typed provenance plus test-target seams (05-18/05-21).
- The reviewers found the core architectural direction sound: the Rust workflow owns the production path, real adapters are injected through WorkflowDependencies, the legacy inline remainder is retired or fenced, and the Go gateway remains the transport/SSE boundary.
- The revised ownership fixes are credible. In particular, the reviews confirm that the protobuf-generation hazard, typed GraphQueryPort migration, and seed-fixture ownership were explicitly assigned and backed by source-level guards.
- The wave ordering is a coherent DAG and the plans preserve the locked Phase 5 scope and wire-compatibility constraints.

### Agreed Concerns

- Generated-contract evolution needs a compile-safe guard at the introducing wave. The protobuf additions in 05-17 and protection of hand-written module glue are a shared risk area; the review evidence supports adding a direct Rust compile check and ensuring all exhaustive generated-struct literals are updated under explicit ownership.
- Several validation claims rely on textual or PowerShell assertions rather than durable executable regression tests. The reviewers independently flag the fragility of cross-platform/script-only guards and blind spots where cargo check --bin engine does not compile test code. The plan set should make the relevant test target compile and assert exact configuration values at the wave where the change is introduced.

### Divergent Views

- Overall risk: AgY rates the plan set LOW and ready for execution. Claude rates it HIGH as written, driven by the claimed 05-17 missing-field compile break, the knowingly uncompiled binary test target across several waves, and unowned existing production-handler tests. These are concrete blockers if the cited source state is unchanged.
- Checkpoint payload: AgY raises storage growth from serializing the full context, including the query embedding and prompt/evidence text. Claude treats the full-context payload as an accepted Phase 5 decision and focuses on compile ordering instead. This is a capacity tradeoff rather than a demonstrated correctness failure.
- Gateway disconnect behavior: AgY identifies a possible secondary write/error race when a disconnected client receives a stream_error frame. Claude does not elevate this to a plan blocker, so it should be checked during implementation without displacing the compile/test-gate fixes.
