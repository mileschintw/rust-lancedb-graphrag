---
phase: 6
reviewers: [antigravity, claude]
reviewed_at: 2026-08-20T23:00:00Z
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md, 06-08-PLAN.md, 06-09-PLAN.md, 06-10-PLAN.md, 06-11-PLAN.md, 06-12-PLAN.md]
models:
  antigravity: "gemini-3.7-flash-high (reasoning=high)"
  claude: "opus (reasoning=high)"
model_sources:
  antigravity: "pinned"
  claude: "pinned"
---

# Cross-AI Plan Review — Phase 6

This file **replaces** the stale 2026-08-20T21:43:42Z review (`antigravity` + `cursor`). The twelve plans were revised from that round; this pass re-reviews the current plan text against the live repo.

Both lanes ran source-grounded against `D:/Repos/lancet` with tool use and permission auto-approve. Neither output carries a `[reviewed-without-repo-access]` or `[reviewed-without-source-citations]` marker, so both verdicts count at full consensus weight. The assembled prompt was untrimmed (`planTruncationPct: 0`, `omitted: []`). No `trimmed_reviewers` block is recorded.

Antigravity: `agy --model gemini-3.7-flash-high --effort high --dangerously-skip-permissions --add-dir`.
Claude: `claude --model opus --effort high --dangerously-skip-permissions --permission-mode bypassPermissions`.

## Consensus Summary

Prior-round headline defects **did land** and both reviewers independently confirmed them against source: the Go test-count split is now `60` (`gateway/main_test.go`) + `7` (`gateway/db/document_test.go`) = `67` total; the `\bNotice {` word-boundary gate now closes arithmetically; `assemble_prompt.rs:70` is in the model-only bypass set; `retrieval/tests.rs:896` is in the literal-migration scope; `RETRIEVAL_DEGRADED_GRAPH` is reserved rather than published. Wave ordering (module graph → testkit → one proto edit → behavior → matrix last) remains endorsed.

The remaining material disagreement is **06-11 Task 3's re-entry into `update_from_model_output`**. Both reviewers saw the same mechanism (`mod.rs:107-108` clones `output.answer`; `generate.rs:145` currently calls the seam *before* citation resolution). Claude rates it **HIGH** (re-entry without a post-strip `ModelOutput.answer` restores stripped markers and would pass every automated gate). Antigravity rates the same seam **LOW** (documentation / implementer temptation) and still **APPROVES** 06-11. Assembly confirmed Claude's site: `update_from_model_output` at `engine/src/workflow/mod.rs:107-108` does overwrite `self.answer`. Treat the HIGH reading as the planning input: revise Task 3 before Wave 9.

Secondary: Claude found 06-12 Task 2's `grep -q 'X-Lancet-Error-Kind'` gate already true at HEAD (8 matches) — assembly confirmed. Antigravity did not flag it. Both mentioned 06-07's `blocking-human` checkpoint under `mode: yolo` (LOW).

### Agreed Strengths

- **Wave sequencing is still correct** and load-bearing (06-06 before 06-07, 06-09 before 06-10, 06-12 last).
- **Prior 06-05 test-count defect is closed.** File gate 60 / db 7 / TOTAL 67 via `scripts/gateway-test-targets.sh`.
- **`\bNotice {` arithmetic closes**; unanchored `Notice {` would have been unreachable.
- **`RETRIEVAL_DEGRADED_GRAPH` reserved 17** is confirmed: `RetrieveHybridNode` has no graph port (`retrieve.rs:13-20`).
- **06-10 empty-evidence bypass is complete** (`assemble_prompt.rs:70` plus both `generation/mod.rs` grounding guards).
- **06-02 `CancelOnDropStream` nesting** inside `query_rag` (`main.rs:1874-1895`) is correctly called out.

### Agreed Concerns

- **[HIGH on Claude / LOW on Antigravity — CONFIRMED mechanism] 06-11 Task 3 re-enters `update_from_model_output`.** `engine/src/workflow/mod.rs:108` assigns `self.answer = output.answer.clone()`. Unless the clone's `answer` is the post-strip text, stripped markers come back. Plan must state (a) mutate the clone's `answer` before re-entry, or (b) add a basis-only helper and relax the `-le 2` gate.
- **[LOW] 06-07 `blocking-human` Task 0** can stall a yolo/batch Wave 5 run. Recommended option is listed first.

### Divergent Views

- **Overall risk:** Antigravity **LOW** and approves all twelve plans. Claude **MEDIUM-HIGH**, with 06-11 needing revision before Wave 9 and 06-12 Task 2 needing an anchoring gate. Consensus planning weight: follow Claude on 06-11 (confirmed at source); treat 06-12 tautological grep as a real but non-blocking gate fix.
- **06-12 Task 2:** Claude only — `X-Lancet-Error-Kind` already occurs 8 times in `gateway/main_test.go`; the task can pass with zero new tests. Antigravity approved the matrix as written.
- **`buf generate` remote plugins:** Antigravity only (repeat of prior-round external-blocker note). Claude did not re-raise it.
- **D-01 / D-05 decision-coverage:** Claude only (scoping decisions with no plan `must_haves` row).

---

## Antigravity Review
# Cross-AI Plan Review: Phase 6 (Observability, Evaluation & Polish — Core Hardening)

## 1. Summary

The revised Phase 6 implementation plans (06-01 through 06-12 across 10 waves) constitute an exceptionally thorough, well-sequenced, and defensible execution plan for closing `DEBT-P3-MODULE-GRAPH` (D-80/D-81), `D-82` (Go package split), `D-74/D-76` (consolidated additive wire contract), and the four target `RAG-03` debt clauses (`DEBT-RAG-01`, `DEBT-RAG-03`, `DEBT-RAG-05`, `DEBT-RAG-06`). The plans adhere strictly to the locked architectural sequence (**module graph → wire contract → behavior tracer → behavior expansions → bad-input matrix**), maintain an invariant per-target test-count gate throughout, and demonstrate rigorous attention to detail. Every finding from previous reviews has been cleanly incorporated (including the Go 60/7/67 test-count split in [06-05-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-05-PLAN.md), the `retrieval/tests.rs:896` literal migration in [06-06-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-06-PLAN.md), the anchored `\bNotice {` regex in [06-07-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-07-PLAN.md), the `assemble_prompt.rs:70` empty-evidence bypass in [06-10-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-10-PLAN.md), and the post-strip basis re-entry in [06-11-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-11-PLAN.md)).

---

## 2. Strengths

- **Surgical Literal Containment ([06-06-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-06-PLAN.md)):** Isolating the ~80 exhaustive [`QueryRagRequest`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto#L53-L57) literals and 14 test [`Notice`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto#L73-L77) literals (including the obscure site at [`engine/src/retrieval/tests.rs:896`](file:///D:/Repos/lancet/engine/src/retrieval/tests.rs#L896)) into a dedicated `engine::testkit` module *before* editing [`proto/lancet/v1/lancet.proto`](file:///D:/Repos/lancet/proto/lancet/v1/lancet.proto) prevents a 100+ compile error avalanche inside the wire contract commit.
- **Strict Go 1.25 Target Discipline:** Across all Go plans ([06-04-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-04-PLAN.md), [06-05-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-05-PLAN.md), [06-07-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-07-PLAN.md), [06-12-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-12-PLAN.md)), the plans enforce the [`gateway/go.mod`](file:///D:/Repos/lancet/gateway/go.mod#L3) `go 1.25.0` constraint, explicitly prohibiting Go 1.26 features like `new(val)` and `errors.AsType[T]` despite newer local toolchains.
- **Accurate Per-Target Test Accounting:** The plans maintain exact per-target test invariants in both scripts:
  - [`scripts/engine-test-targets.sh`](file:///D:/Repos/lancet/scripts/engine-test-targets.sh): Tracks `src/lib.rs` (133 → 261 post-restructure), `src/main.rs` (128 → 0), `inspect_lancedb.rs` (18), `seed_rag_fixture.rs` (0), and `tests/config_startup.rs` (9) for a 288 baseline.
  - [`scripts/gateway-test-targets.sh`](file:///D:/Repos/lancet/scripts/gateway-test-targets.sh): Recognizes that HEAD test count is split across [`gateway/main_test.go`](file:///D:/Repos/lancet/gateway/main_test.go) (60 tests) and [`gateway/db/document_test.go`](file:///D:/Repos/lancet/gateway/db/document_test.go) (7 tests) for a total of 67.
- **Unreachable Contract Elimination:** [06-07-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-07-PLAN.md) proactively removes `RETRIEVAL_DEGRADED_GRAPH` (AI-SPEC tag 17) and marks it `reserved 17;` because [`RetrieveHybridNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/retrieve.rs#L13-L20) has no graph port, avoiding shipping a permanent, dead enum value.
- **End-to-End Degraded Path Completeness:**
  - [06-08-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-08-PLAN.md) covers both silent degrade branches in [`engine/src/workflow/nodes/graph_context.rs:112-115,147-150`](file:///D:/Repos/lancet/engine/src/workflow/nodes/graph_context.rs#L112-L150) with `GRAPH_UNAVAILABLE` while adding `GRAPH_CONTEXT_DISABLED` for caller ablation.
  - [06-09-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-09-PLAN.md) converts [`retrieve.rs:76,107`](file:///D:/Repos/lancet/engine/src/workflow/nodes/retrieve.rs#L76-L107) from fail-closed (`return Err`) to degrade while preserving variant loop accumulation.
  - [06-10-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-10-PLAN.md) unblocks model-only by handling both runner gates ([`runner.rs:426-432,481-487`](file:///D:/Repos/lancet/engine/src/workflow/runner.rs#L426-L487)), the prompt assembly guard ([`assemble_prompt.rs:70`](file:///D:/Repos/lancet/engine/src/workflow/nodes/assemble_prompt.rs#L70)), and both grounding validation guards ([`generation/mod.rs:172,193`](file:///D:/Repos/lancet/engine/src/generation/mod.rs#L172-L193)).
  - [06-11-PLAN.md](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-11-PLAN.md) replaces fail-closed citation resolution in [`generate.rs:154-165`](file:///D:/Repos/lancet/engine/src/workflow/nodes/generate.rs#L154-L165) with local normalize-then-strip and conservative basis reconciliation.
- **Fail-Closed Configuration Knobs (D-84):** New keys (`allow_model_only_answers`, `citation_repair_enabled`) reject invalid environment variables at startup, containing `DEBT-P3-WARN-SETTINGS` without disturbing existing fail-open keys.

---

## 3. Concerns

- **[LOW] `06-07-PLAN.md` Human Checkpoint in Semi-Automated Execution:**
  - *Evidence:* [`06-07-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-07-PLAN.md#L4766) sets `autonomous: false` and includes a `blocking-human` checkpoint (`Task 0`) to confirm the notice vocabulary (`research-corrected`).
  - *Risk:* If an automated pipeline executes Wave 5 in non-interactive batch mode, it could stall at Task 0.
  - *Mitigation:* The plan lists `research-corrected` as the recommended default option with explicit resume signals, making manual or automated unblocking straightforward.
- **[LOW] `generate.rs` Re-Entry Seam Documentation:**
  - *Evidence:* In [`06-11-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-11-PLAN.md#L6484-L6486), Task 3 specifies that [`GenerateAnswerNode`](file:///D:/Repos/lancet/engine/src/workflow/nodes/generate.rs#L14-L19) must call [`update_from_model_output`](file:///D:/Repos/lancet/engine/src/workflow/mod.rs#L107) (or the Task 2 basis seam) after citation stripping so that a total drop downgrades through the exact same conservative comparison.
  - *Risk:* An implementer might be tempted to mutate `ctx.answer_basis` directly in `generate.rs` if `update_from_model_output` overwrites `ctx.answer` again.
  - *Mitigation:* Task 3 verification strictly checks `test "$(grep -c 'self.answer_basis' engine/src/workflow/mod.rs)" -le "2"` and verifies `generate.rs` contains zero basis assignment sites.
- **[LOW] Preserved Insecure Dial (`DEBT-CR-04-EXT`):**
  - *Evidence:* [`gateway/main.go:30`](file:///D:/Repos/lancet/gateway/main.go#L30) uses `grpc.WithTransportCredentials(insecure.NewCredentials())`.
  - *Risk:* Relocating this to `gateway/internal/engineclient` might tempt an engineer to add TLS.
  - *Mitigation:* [`06-05-PLAN.md`](file:///D:/Repos/lancet/.planning/phases/06-observability-evaluation-polish/06-05-PLAN.md#L4356) explicitly records `T-06-05-01` and binds the insecure dial to the `999.x` Security & Transport backlog phase per D-03/D-06.

---

## 4. Suggestions

1. **Verify `buf` Connectivity Prior to Wave 5:** Ensure the environment has network access to `buf.build` (or cached remote plugins in `~/.cache/buf`) before triggering `06-07-PLAN.md`. Task 1's dry-run `buf lint && buf generate` on the untouched tree will catch any issue immediately.
2. **Keep the Serialized Wave Ordering:** Do not attempt to merge Wave 4 (`06-06`), Wave 5 (`06-07`), or Wave 6 (`06-08`). The separation of literal containment, proto regeneration, and behavior tracing ensures that every intermediate state compiles and passes the test suite cleanly.

---

## 5. Risk Assessment

- **Overall Risk Level: LOW**
- **Justification:**
  1. The architectural restructuring (Waves 1–3) is 100% pure refactoring with no behavior changes, protected by per-target test-count assertion scripts.
  2. The wire contract change (Waves 4–5) is strictly additive, eliminates proto drift risks, and isolates struct-literal migrations into Wave 4.
  3. The behavioral features (Waves 6–10) are decoupled into distinct, wave-separated plans with robust fallback mechanisms and comprehensive test suites covering all edge cases.
  4. All prior review findings and edge-case concerns have been verified and confirmed resolved against the live codebase at `D:/Repos/lancet`.

---

## 6. Plan Verification Matrix

| Plan | Wave | Requirements / Decisions | Pre-Review Findings Status | Verification Status |
|---|---|---|---|---|
| **06-01** | Wave 1 | D-80, D-81 (`engine::chunker`, `engine::config`) | Verified Windows path separator normalization and exact 18-literal `LANCET_` key count. | **APPROVED** |
| **06-04** | Wave 1 | D-82 (`internal/config`, `internal/sse`, `internal/telemetry`) | Verified target Go 1.25 conformance and comment-stripped test enumeration. | **APPROVED** |
| **06-02** | Wave 2 | D-80 (`engine::ingest`, `engine::service`) | Verified un-nesting of `CancelOnDropStream` to module scope. | **APPROVED** |
| **06-05** | Wave 2 | D-82, D-03, D-06 (`internal/engineclient`) | Verified test gate counts: `main_test.go` = 60, `db/document_test.go` = 7, TOTAL = 67. | **APPROVED** |
| **06-03** | Wave 3 | D-80 (Rehome test roots, `main.rs` to wiring) | Verified `main.rs` single item assertion and 261/0/18/0/9 test distribution. | **APPROVED** |
| **06-06** | Wave 4 | D-83 (`engine::testkit`, fake failure modes, Go key sets) | Verified inclusion of `retrieval/tests.rs:896` and `pb/` exclusion from grep gate. | **APPROVED** |
| **06-07** | Wave 5 | D-74, D-76 (Consolidated proto delta & bindings) | Verified `reserved 17;` for graph degrade, anchored `\bNotice {`, and `ragQueryRequestBody` presence. | **APPROVED** |
| **06-08** | Wave 6 | D-47, D-08, DEBT-RAG-06 (Graph ablation & notices) | Verified 2 silent-degrade paths covered with `GRAPH_UNAVAILABLE` and 4-case source-chunk proof. | **APPROVED** |
| **06-09** | Wave 7 | D-13, DEBT-RAG-01 (Retrieval fail-closed → degrade) | Verified per-variant loop tolerance and 3-notice both-paths sequence. | **APPROVED** |
| **06-10** | Wave 8 | D-10, D-11, D-12, D-84 (Model-only opt-in) | Verified conditional bypass of `assemble_prompt.rs:70`, `generation/mod.rs:172,193`, and runner gates. | **APPROVED** |
| **06-11** | Wave 9 | D-14, D-18, D-17, D-19 (Citation repair & basis) | Verified local normalize-then-strip, conservative reconciliation, and prompt-only precedence text. | **APPROVED** |
| **06-12** | Wave 10 | D-15, DEBT-RAG-05 (Bad-input matrix & reconciliation) | Verified table-driven gRPC/HTTP tests, fake call counts = 0, and final 8-plan test delta reconciliation. | **APPROVED** |
---

## Claude Review
# Cross-AI Plan Review — Phase 6 (Revised Plans, Fresh Re-Review)

**Reviewer note:** Every claim below was checked against the live repo at HEAD. Findings carry `path:line` evidence. I did not read `06-REVIEWS.md`; each plan's own "Review incorporation" table was treated as a claim to verify, not a fact.

---

## 1. Summary

These twelve plans are unusually well-instrumented for a 12-plan phase: the sequencing (module graph → wire contract → behavior) is a locked decision that the plans honor precisely, the per-target test-count gates are a real safety net for a refactor whose only protection is the suite, and nearly every numeric claim I sampled is correct against source. The prior review round's headline defects **did** land: the Go test-count split is now `60` + `7` = `67` (`gateway/main_test.go`, `gateway/db/document_test.go`), the `\bNotice \{` word-boundary gate now closes arithmetically (2+0+1+1 = 4 pre-change, 1 post-change), `CancelOnDropStream`'s nesting inside `query_rag` is called out, the `LANCET_` env-key gate is equality-to-18 rather than `-ge`, and `retrieval/tests.rs`'s missed `QueryRagRequest` literal is now in scope (81 non-generated sites total, generated `pb/` excluded). One material defect survives: **06-11's citation-repair plan forbids the only implementation shape that would work, and the shape it forces silently undoes the answer-text strip it exists to perform.** That is a runtime defect, not a compile-time one, and it is the plan whose own incorporation table claims to have closed it. Secondary concerns are gate quality rather than correctness — two automated gates pass unmodified at HEAD and therefore prove nothing.

---

## 2. Strengths

- **The `\bNotice \{` gate arithmetic actually closes.** Measured at HEAD: `workflow/mod.rs` 2, `workflow/events.rs` **0** (word-boundary), `nodes/graph_context.rs` 1, `nodes/retrieve.rs` 1 → 4. The unanchored `Notice {` pattern would return 3 for those files (`events.rs:113` `pub struct CheckpointNotice` and `:119` `impl From<&Notice> for CheckpointNotice` both match), making 06-07's target of 1 unreachable. The `-E '\bNotice \{'` fix in 06-06 (target 4) and 06-07 (target 1) is correct and load-bearing.
- **06-07's correction that `events.rs` is not a construction site is right.** `engine/src/workflow/events.rs:113-127` defines `CheckpointNotice` and a `From<&Notice>` impl that copies `code`/`message`/`severity` from an already-built notice. It never constructs a `pb::Notice`. Dropping `events.rs` from Task 2's `<files>` and forbidding `CheckpointNotice` migration is the correct call, and it correctly avoids adding `typed_code` to the checkpoint snapshot (which would change the 19-key `CHECKPOINT_SNAPSHOT_KEYS` contract Phase 05 froze).
- **The `RETRIEVAL_DEGRADED_GRAPH` correction is empirically confirmed.** `grep -ci graph engine/src/workflow/nodes/retrieve.rs` → **0**. `RetrieveHybridNode` (`retrieve.rs:13-20`) holds `dense_port`, `bm25_port`, `reranker`, `settings`, `index_generation`, `embedding_model` — no graph port. `06-AI-SPEC.md:604` declares `NOTICE_CODE_RETRIEVAL_DEGRADED_GRAPH = 17`; reserving that tag instead of publishing a permanently-dead one-way enum value is the right decision, and 06-07 gates it (`grep -c 'RETRIEVAL_DEGRADED_GRAPH'` outside comments = 0).
- **06-09's fail-closed→degrade framing is correct, and the gate has teeth.** `retrieve.rs` has exactly **2** `return Err(err)` sites (`:76` dense, `:107` BM25); cancellation and fusion/rerank use `NodeError::new(...)` and don't match. The 2→1→0 progression across Tasks 1 and 2 is a real assertion, not a tautology. Notice ordering (dense at `:65-80`, BM25 loop at `:101-111`, `NO_EVIDENCE` at `:192-198`) confirms the specified three-notice sequence is source-order, so asserting it as an ordered sequence is meaningful.
- **06-02's `CancelOnDropStream` fix is precise.** The type is declared at `engine/src/main.rs:1874-1895`, lexically **inside** `query_rag`'s body (between the `d1_status(...)?;` at `:1871` and the channel setup at `:1897`), despite being at column 0. A naive "cut the impl block" would drop it or split the function. Requiring it be lifted to module scope first is exactly right.
- **06-01's per-target gate design is correct where it matters.** It asserts `lib + bin = 261` combined rather than the split — necessary, because Task 1 moves `chunker`'s **6** tests (`grep -c` over `engine/src/chunker/`) from bin to lib, which would break a fixed split. `18 / 0 / 9` on the untouched targets and `288` total are internally consistent (133+128+18+0+9). `engine/tests/config_startup.rs` confirmed at 9.
- **06-10's empty-evidence finding is accurate and complete.** `assemble_prompt.rs:70-75` returns `PromptAssemblyFailed` on `ctx.evidence_blocks.is_empty()` — bypassing the two runner gates alone would still terminate the workflow, so SC3 could not be met. The revised plan edits the node *and* refuses to relax `pack_evidence_and_graph_prompt`'s `EmptyEvidence` return (`prompt.rs:332-334`), preserving `workflow_phase5.rs:2299-2304` and `tests.rs:6262-6279`. It also correctly identifies that **both** grounding guards must become conditional — `generation/mod.rs:172-177` (basis) and `:193-201` (empty `cited_evidence_ids`) — and I confirm the rest of the validator passes cleanly on an empty-evidence/empty-citation output (`seen_cited == inline_set` with both empty at `:338`).
- **06-05 Task 1 correctly scopes its verify to `go build ./...` only.** `go build` does not compile `_test.go`, so leaving `main_test.go` broken between tasks is legal; `go vet` would compile tests and fail, and the plan omits it. That is deliberate, correct attention to detail.
- **06-03's double-declaration guard is well-targeted.** `engine/src/tests.rs:11` declares only `pub mod workflow_phase5_production;`; `lib.rs:15-17` declares `workflow_phase5` via `#[path]`. `grep -c 'mod workflow_phase5;' tests.rs = 0` correctly does not match `workflow_phase5_production;`.
- **06-12's non-rejection dispositions are correct and non-obvious.** `retrieve.rs:192-198` emits `NO_EVIDENCE` with `Ok(())` for zero candidates — Phase 03's shipped valid-zero-match branch. Recording "unmatched filter" as a 200-row rather than a 400-row prevents contradicting shipped behavior and preserves the abstention signal Phase 6.3 scores on. Its requirement that the two HTTP non-rejection rows use a **success-returning** stub (rather than an `InvalidArgument` stub) is a genuine catch.

---

## 3. Concerns

### HIGH

**C1 — 06-11 Task 3's forced re-entry into the basis seam silently undoes the answer-text strip.**

`engine/src/workflow/mod.rs:107-114`:
```rust
pub fn update_from_model_output(&mut self, output: &ModelOutput) {
    self.answer = output.answer.clone();          // :108
    self.citations = output.cited_evidence_ids.clone();
    self.answer_basis = match output.answer_basis { … };   // :110
```

`engine/src/workflow/nodes/generate.rs:145` calls `ctx.update_from_model_output(&output)` **before** citation resolution at `:146-165`. So the Task 2 reconciliation seam runs against the *pre-repair* citation set.

06-11 Task 3 requires re-entering that seam after the strip, and Task 2/3 both gate `grep -c 'self.answer_basis' engine/src/workflow/mod.rs` at `-le 2` (currently exactly 2: read at `:100`, assign at `:110`). That gate closes off a dedicated `reconcile_basis(&mut self, observed)` helper, forcing the executor to re-call `update_from_model_output` with a mutated `ModelOutput` clone. But that call re-executes `:108` — **`self.answer` is overwritten with the unstripped text** unless the executor also mutates the clone's `answer` field. The plan never says that.

*Failure scenario:* model returns `"… as shown in [7]."` with `cited_evidence_ids: ["[7]"]`, and `[7]` resolves to nothing. Repair strips `[7]` from `ctx.answer` and from both citation lists, emits `CITATION_DROPPED`, then re-enters the seam to downgrade the basis. `:108` restores `"… as shown in [7]."`. The response now carries a `CITATION_DROPPED` notice, an empty `structured_citations`, and an answer that still cites `[7]` — the exact provenance-integrity failure T-06-11-01 exists to prevent, and it would pass every automated gate in the plan (the `-le 2` count holds, `\bNotice \{` holds, the build is green).

This is the finding 06-11's own incorporation table records as *"MEDIUM: Task 3 must re-enter the Task 2 basis seam — incorporated."* The re-entry was added; the consequence of re-entry was not.

**Severity rationale:** runtime-only, on the exact path the phase's transparency prohibition covers, with no gate that catches it.

### MEDIUM

**C2 — 06-12 Task 2's automated verify passes at HEAD without a single new test.**

The gate is `grep -q 'X-Lancet-Error-Kind' gateway/main_test.go && grep -q 'StatusBadGateway' gateway/main_test.go && <diff-scope check>`. Measured at HEAD: `X-Lancet-Error-Kind` = **8**, `StatusBadGateway` = **19**. Both greps are already satisfied. The only remaining real signal is `scripts/gateway-test-targets.sh`'s total — which the same task instructs the executor to update to whatever it measures. An executor that writes zero matrix rows, bumps the total by zero, and runs `go test` passes the whole task.

Contrast the plans that got this right: 06-08 Task 2 gates `grep -c 'GraphUnavailable' graph_context.rs = 2` (HEAD: 0) and `grep -c 'Notice {' = 0` (HEAD: 1); 06-09 gates `return Err(err) = 0` (HEAD: 2). Those genuinely fail before the work and pass after.

**C3 — 06-11 Task 3 has no algorithm for where the drop-notice message and the stripped text meet.**

Task 3 requires removing a dropped marker "from the answer text" and emitting one notice per marker with the marker named. But `ModelOutput.answer` markers are extracted by `extract_inline_markers` (`generation/mod.rs:352-373`), which only recognizes `[<digits>]`. A near-miss marker the repair pass normalizes (case/whitespace, per Task 1) may not match that extractor at all — e.g. `[ 7 ]` is not matched by `extract_inline_markers`, so it is invisible to the existing validator and the plan gives no rule for locating it in the answer string for removal. The normalization contract (Task 1) and the text-removal contract (Task 3) are specified independently and never reconciled. LOW-to-MEDIUM depending on how the executor interprets "marker".

**C4 — 06-04 Task 1's gate pins one implementation spelling rather than a behavior.**

`grep -q "grep -v '\^\[\[:space:\]\]\*//'" scripts/gateway-test-targets.sh` requires the script to contain that exact escaped literal. A behaviorally-identical `sed '/^[[:space:]]*\/\//d'` or `awk` filter fails the gate. The acceptance criterion ("counting pipeline filters comment lines before counting") is the real contract; the grep over-constrains it.

### LOW

**C5 — 06-06 Task 2's `cfg(test)` ratio gate has enormous slack.** HEAD: `cfg(test)` = 26, `struct Fake` = 6 in `ports.rs`. Adding three constructors with zero new gate attributes still passes `26 >= 6`. The real protection is `cargo build --release`, which *does* work here — `ports.rs:9-10` gates the `FusedCandidate`/`RetrievalError` imports and `generation/mod.rs:12-16` gates the `atomic`/`Mutex` imports, so an ungated fake would fail to resolve. Downgraded on that basis, but the ratio assertion contributes nothing.

**C6 — 06-03 Task 2's tamper-check is unautomatable.** "Verify once by temporarily editing the expected total in a scratch copy" is an acceptance criterion with no machine check and no artifact. Same shape in 06-06 Task 3 ("temporarily add an extra key… revert before committing"), though that one at least requires recording the failure message in the SUMMARY.

**C7 — `main.rs`'s column-0 items make 06-03's item-count grep fragile in principle.** `grep -cE '^(pub )?(async )?fn |^(pub )?struct |…'` returns **109** at HEAD and must reach 1. `CancelOnDropStream` at `:1874` is written at column 0 but is lexically inside `query_rag` — the pattern counts it as top-level. After 06-02 moves it this is moot, but the gate would not distinguish a future function-local item from a real top-level one.

**C8 — Two Phase-6-scoped decisions have no plan reference.** D-01 (ROADMAP-named-only scoping) and D-05 (DEBT-RAG-02 closed as satisfied by Phase 05) appear in no plan's `must_haves`. Both are scoping/no-op decisions, but Phase 6 *does* have a local `06-CONTEXT.md`, so the plan-checker's decision-coverage gate runs and may flag them.

**C9 — 06-09 lands on genuinely zero prior coverage.** `FakeDenseRetrievalPort::failure` and `FakeBm25RetrievalPort::failure` have **zero call sites anywhere** in the tree (verified across all spellings; only `success`, `stall`, and `with_map` are used — cf. `FakeReranker::failure` at `workflow_phase5.rs:1026,1664` and `FakeGraphQueryPort::failure` at `:2499`, which *are* used). So 06-09's conversion breaks no existing test — good — but it also means D-83's "the error mode already exists" claim is structurally true and empirically untested for exactly the two ports this phase converts. 06-09's twelve new tests are the entire safety net for the most consequential behavior change in the phase. Worth stating in the SUMMARY rather than leaving implicit.

**C10 — 06-07's `blocking-human` checkpoint under `mode: yolo`.** `.planning/config.json` sets `mode: yolo`. The plan's `gate_rationale` addresses this explicitly and lists the recommended option first as a hedge, which is the right defensive design. Flagged only so the operator confirms the harness honors `blocking-human` before Wave 5 — the enum values are one-way.

---

## 4. Suggestions

1. **Revise 06-11 Task 3 before Wave 9.** Either (a) state explicitly that the re-entry passes a `ModelOutput` clone whose `answer` field is the **post-strip** text and whose `cited_evidence_ids` is the post-repair set — making `:108` idempotent — or (b) relax the `-le 2` gate to `-le 3` and permit one dedicated `reconcile_basis` method that touches only `answer_basis`. (a) is cleaner and keeps the single-seam invariant; either way the plan must say which.
2. **Give 06-12 Task 2 an anchoring gate.** Assert the new test's function name exists, e.g. `grep -q 'func TestBadInputMatrixHTTP' gateway/main_test.go`, and assert `grep -c '^func Test' gateway/main_test.go` equals `62 + N` for the declared N. That converts the task from unverifiable to verifiable at zero cost.
3. **Loosen 06-04 Task 1's comment-filter gate.** Replace the literal-spelling grep with a behavioral check: create a scratch `_test.go` containing a commented-out `// func TestFake(t *testing.T) {}` and assert the script's total is unchanged.
4. **Add a marker-extraction rule to 06-11 Task 1's module header.** State whether the repair pass operates on `extract_inline_markers`'s `[<digits>]` grammar, on a widened grammar, or on `cited_evidence_ids` only — and if widened, how the answer-text removal locates the span. Today Task 1 and Task 3 assume different things.
5. **Record C9 in 06-09's SUMMARY** as "zero pre-existing tests exercised the two retrieval failure constructors; this plan's twelve tests are the first coverage of that path."
6. **Optional:** have 06-01 or 06-12 assert D-01 and D-05 dispositions in `must_haves.truths` so the decision-coverage gate reads them as opted-out rather than missed.

---

## 5. Risk Assessment

**MEDIUM-HIGH overall.**

The structural risk is well-managed and better than the phase's shape would predict. A 12-plan phase in `yolo` mode with a ~2.3k-line single-commit relocation (06-02), eight sequential edits to two gate scripts, and a one-way published contract change is a high-variance setup — and the plans counter it with per-target invariant gates, an explicit no-alias rule enforced by grep, byte-for-byte env-key and error-kind assertions, and a `blocking-human` gate on the only irreversible decision. Wave ordering is correct and load-bearing: 06-09 before 06-10 (degrade converges both model-only triggers onto one observable state), 06-06 before 06-07 (81 literal sites migrated out of the contract diff), 06-12 last (gate-script serialization, correctly explained as the reason rather than a content dependency).

The rating is not LOW because of one thing: **06-11 carries a concrete defect that surfaces at runtime on the transparency path the phase exists to harden, and every gate in that plan passes with the defect present.** Citation repair is the clause where "the system asserts provenance it cannot support" is the failure mode; shipping a plan whose forced implementation shape restores stripped markers into the answer text is the wrong place to have a gap.

**Per-plan readiness:** 06-01 through 06-09 are ready to execute as written, with C2/C4/C5's gate weaknesses worth tightening but not blocking. 06-10 is ready — its revision closed the real gap. **06-11 needs a revision to Task 3 before Wave 9.** 06-12 is ready once Task 2's gate is anchored.
