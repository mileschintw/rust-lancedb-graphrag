---
phase: 05-state-machine-workflow-events
verified: 2026-08-19T03:10:00Z
status: human_needed
score: 4/5 roadmap success criteria verified (1 present, behavior-unverified)
behavior_unverified: 1
overrides_applied: 0
mode: mvp
head: 721485c
unverified_prohibitions: 0 # RESOLVED — UAT Test 4 records an explicit human acceptance of all 15 judgment-tier prohibitions from plans 05-01..05-07
re_verification:
  previous_status: human_needed
  previous_score: 5/5
  previous_verified: 2026-08-18
  previous_head: d84cee2
  note: |
    Full re-derivation at HEAD 721485c. No prior verdict was carried forward. Since the
    previous pass the following landed: edaf907 (d1_status restoration, resolving prior
    regression WR-05), 989003b (config.toml generation_model -> dots-studio/dots-3-note-preview:free),
    967a897 + c360669 (plan 05-25, G-05-1 Blocker A), c815af1 + fde6fb2 (plan 05-26,
    G-05-1 Blocker B), e6e153f (roadmap/state reconciliation), 721485c (05-REVIEW refresh).
    05-UAT.md was authored between the two passes and records four human tests.
    Score moved 5/5 -> 4/5 NOT because anything regressed, but because SC4 was re-graded
    honestly: the previous pass counted three Postgres-backed checkpoint tests as PASS
    against a live container. That container is unavailable in this environment, those
    tests SKIP, and a skip is not a pass.
  gaps_closed:
    - "WR-05 (x-lancet-* gRPC trailer regression) — RESOLVED. `fn d1_status` re-derived at engine/src/main.rs:1159-1180; it inserts x-lancet-session-id, x-lancet-correlation-id, x-lancet-error-kind into the Status metadata. It is the error constructor on all three pre-stream paths (1777, 1786, 1835). gateway/main.go:774-782 reader and its doubles left in place — contract restored, not deleted. Human disposition recorded in 05-UAT.md Test 2 (result: pass)."
    - "Traceability bookkeeping — RESOLVED. REQUIREMENTS.md:32-38 now shows ORCH-01..ORCH-05 all [x], plus GATE-01 and GATE-02 formalized as real requirements with Phase 05 attribution and an errata pointer. GATE-03 was removed as unbacked. Human disposition recorded in 05-UAT.md Test 3 (result: pass)."
    - "15 judgment-tier prohibitions — RESOLVED by explicit human acceptance, 05-UAT.md Test 4 (result: pass). Not re-flagged this pass."
    - "G-05-1 Blocker A (code half) — validate_schema now carries an actionable remediation clause (engine/src/db/mod.rs:167-172)."
    - "G-05-1 Blocker A (data half) — EMPIRICALLY VERIFIED this pass: `./engine/target/debug/inspect_lancedb.exe --lancedb-path ./data/lancedb --document-id <uuid4>` reaches `DatabaseManager::open_and_validate` (bin/inspect_lancedb.rs:366) and gets past it, failing only downstream on a document-lookup invariant. Transfer to main()'s startup path confirmed by source: main.rs:3215 calls `initialize` -> `initialize_tables`, which iterates the SAME `table_schemas()` set and calls the SAME `validate_schema` per table (db/mod.rs:106) as `open_and_validate` (db/mod.rs:58); `initialize` is strictly MORE permissive (it creates missing tables and applies the additive `staged_documents_v2` generation-column migration BEFORE validating). Passing the stricter path therefore implies the startup gate passes. `data/lancedb.pre-05-25.bak` preserved."
    - "G-05-1 Blocker B — RESOLVED in code. engine/src/main.rs:661-668 adds explicit LANCET_OPENROUTER__GENERATION_MODEL and LANCET_OPENROUTER__EMBEDDING_MODEL overrides; gateway/main_test.go:2212 and :3519 pin the spawned engine's generation_model, and :2786-2787 add both to the assertCleanRAGChildEnv allowlist. The real-engine tests no longer read ambient config.toml for the model."
  gaps_remaining: []
  regressions: []
gaps: []
deferred: []
behavior_unverified_items:
  - truth: "SC4 (persistence half) — workflow checkpoints are durably persisted to PostgreSQL with strict FIFO drain (primary -> overflow -> pending) and cancellation atomicity."
    test: "Start the Postgres dev container, then: cd gateway && TEST_DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable go test . -count=1 -run 'TestWorkflowCheckpointPersistence|TestWorkflowCheckpointCancellationAtomicity|TestWorkflowCheckpointPendingDrainAndPersistence|TestEmbeddingFailureRestartConvergesAcrossRuntime'"
    expected: "All four PASS, plus the 7 gateway/db document/reconciliation-intent tests."
    why_human: "These 11 tests are TEST_DATABASE_URL-gated and SKIPPED in this environment (Docker Desktop not running; nothing listening on 127.0.0.1:5432). Persistence ordering and cancellation atomicity are state-transition invariants — presence of InsertWorkflowCheckpoint (gateway/checkpoint_sink.go:106-115) and RetainPending (main.go:802) proves the code is wired, not that the ordering invariant holds. The previous verification counted these as PASS against a container that is no longer up; that evidence is not reproducible at HEAD."
human_verification:
  - test: "Run one real query against the live OpenRouter provider end-to-end (engine + gateway + curl on /rag/query with a real OPENROUTER_API_KEY), and watch the SSE frame sequence."
    expected: "node_started/node_completed for all five nodes, one answer_chunk, one final_answer, one workflow_completed, no stream_error; the answer is grounded with real citations."
    why_human: "STILL NOT PERFORMED. 05-UAT.md Test 1 is result: issue, severity: blocker. Both of its root causes (G-05-1 Blocker A and B) are now closed in code and, for Blocker A, empirically at the store level — but closing the blockers only UNBLOCKS the test; it does not constitute the test. The run needs a real OpenRouter API key and a human observer; a verifier cannot perform it. Reinforced by WARN-NEW-01 below: after plan 05-26 the real-engine tests pin openai/gpt-4o-mini, so the shipped generation_model (dots-studio/dots-3-note-preview:free) and its structured-output capability preflight at engine/src/generation/openrouter.rs:425-434 are now exercised by NO automated test at all."
  - test: "Restore Postgres and run the 11 TEST_DATABASE_URL-gated tests (see behavior_unverified_items)."
    expected: "All 11 PASS."
    why_human: "Requires Docker/Postgres availability that this environment does not have."
  - test: "Decide the disposition of CR-01 + WR-12 (the coupled cancellation-path defects in engine/src/workflow/runner.rs)."
    expected: "Either the capacity() fast path is deleted in favour of the unconditional biased select (the review's recommended fix), or the current behaviour is explicitly accepted with the buffer-depth invariant recorded as a load-bearing assumption."
    why_human: "Not a gap today — the arithmetic below shows the precondition is unreachable at the current buffer depth. It is a design-debt acceptance decision, and the guard is an emergent property of a size constant rather than an enforced invariant."
warnings:
  - id: CR-01
    title: "run_node cancels before emitting NodeFailed — latent, precondition re-derived as unreachable at HEAD"
    file: "engine/src/workflow/runner.rs:335-398"
    severity: warning
    re_derived: true
    detail: |
      On the preparation-failure and timeout branches, cancel.cancel() runs BEFORE the
      corresponding NodeFailed is emitted. A Cancelled delivery result can only be produced by
      the biased select at runner.rs:100-110, which is reached ONLY when the tx.capacity() > 0
      fast path at runner.rs:90-98 is not taken.
    verifier_arithmetic: |
      Re-derived from source this pass, not carried forward:
        - The sink channel is per-request: `let (tx, rx) = mpsc::channel(100)` at main.rs:1861,
          feeding the single `WorkflowEventSink::new(...)` at main.rs:1870.
        - Repo-wide (excluding engine/src/tests*), WorkflowEventSink appears only at main.rs:1870,
          mod.rs:26/167 and runner.rs:39/48/335/407/442/449/487. There is NO `.clone()` of the sink
          at any production call site, so exactly one sender holds tx.
        - Event bound for one workflow: 5 nodes x (node_started + node_completed + checkpoint) = 15,
          + exactly one answer_chunk (runner.rs:381 is the sole AnswerChunk emitter, is_final=true;
          there is no per-token streaming), + terminal (final_answer + terminal checkpoint +
          workflow_completed) = 19 on the clean path. Retries raise this: GenerateAnswerNode retries
          on ProviderError, and each extra attempt adds a node_started + node_failed pair. Even with
          every node retried the total lands around 30 — well under 100, with >=70 slots always spare.
      Therefore capacity() can never reach 0, the fast path is always taken, the biased arm is never
      entered, and NodeFailed/WorkflowCompleted are never dropped nor a Timeout masked as Cancelled.
      SC3 is NOT compromised.
    coupling_with_WR12: |
      WR-12 (new this review) correctly identifies the fast path as a check-then-act TOCTOU: the
      reserve().await inside it has no cancellation arm. But the race requires a SECOND sender to
      consume the last permit between the capacity() read and the reserve(). With a single sender
      and a 100-slot channel carrying at most 19 events, no permit contention exists. WR-12 does
      NOT invalidate the CR-01 arithmetic at HEAD; the two share the same unreachability premise
      and would go live together.
    becomes_live_if: "per-token streaming AnswerChunks are added (planned 999.x), the 100-slot buffer is reduced, or the sink is cloned / shared across workflows."
    recommended_fix: "Delete the capacity() fast path; always use the biased select. Emit the failure event before cancelling."
  - id: WARN-NEW-01
    title: "Plan 05-26's decoupling pins the real-engine tests to a model that is NOT the shipped one"
    file: "gateway/main_test.go:2212, 3519; config/config.toml"
    severity: warning
    detail: |
      05-26 correctly removed the ambient-config dependency, but did so by pinning
      LANCET_OPENROUTER__GENERATION_MODEL=openai/gpt-4o-mini to match the 5 pre-existing hardcoded
      httptest /models mocks. The shipped config.toml value is dots-studio/dots-3-note-preview:free
      (989003b). Net effect: TestRAGQueryCrossRuntime and TestRAGQueryClientDisconnectCancelsRustWorkflow
      are now permanently immune to config.toml drift — and permanently blind to it. The capability
      preflight at engine/src/generation/openrouter.rs:425-434 (which hard-requires response_format /
      json_schema / structured_outputs) is never exercised against the model production actually uses.
      This is a deliberate, defensible trade (structural test stability over config fidelity), not a
      defect — but it is a fresh, independent reason the live end-to-end run remains mandatory.
  - id: WR-13
    title: "05-25's remediation guidance is appended after two full 19-field schema dumps"
    file: "engine/src/db/mod.rs:167-172"
    severity: warning
    detail: |
      Verified verbatim at HEAD: the format string is
      \"...drift detected for {name}: expected {:?}, found {:?}. Remediation: ...\".
      Both {:?} render full Vec<Field> dumps (19 fields each, with nested FixedSizeList types), so the
      actionable clause lands hundreds of characters into a wall of type noise. The deliverable exists
      and is substantive; its stated purpose ('a developer gets an actionable remediation hint in the
      error message itself') is only partially achieved. Trivially fixed by moving the clause first.
  - id: WR-01
    title: "dispatcher.Close() is unreachable — buffered checkpoints lost at shutdown"
    file: "gateway/main.go:1076, 1087-1089"
    severity: warning
    detail: "Carried in the review; not re-derived line-by-line this pass. Bounded loss on SIGINT; already-dispatched rows are durable."
  - id: WR-03
    title: "WorkflowSettings::validate() enforces only non-zero; no cross-field invariants"
    file: "engine/src/main.rs:257-282, config/config.verify.toml"
    severity: warning
  - id: WR-04
    title: "Every non-2xx chat response classified ProviderError, so 401/400 is retried"
    file: "engine/src/generation/openrouter.rs"
    severity: warning
  - id: WR-11
    title: "Restored d1_status reflects an unvalidated, unbounded client-supplied session_id into a gRPC trailer and thence an HTTP response header"
    file: "engine/src/main.rs:1159-1180"
    severity: warning
    detail: |
      NEW consequence of the WR-05 fix accepted in UAT Test 2. Re-derived: d1_status does
      `session_id.parse()` into a MetadataValue and inserts it. The parse rejects non-ASCII/illegal
      header bytes (so it degrades gracefully rather than panicking), but there is no length bound
      and the value is reflected to the client via gateway/main.go's handlePreStreamError. Worth a
      length cap. Does not affect any success criterion.
  - id: WR-14
    title: "config/config.toml commits a default Postgres credential with TLS disabled"
    file: "config/config.toml"
    severity: warning
  - id: WR-15
    title: "ReformulateQueryNode enforces the 8-variant ceiling but not a non-empty floor"
    file: "engine/src/workflow/nodes/reformulate.rs"
    severity: warning
    detail: "An empty reformulator result silently degrades to zero evidence. Unreachable with the shipped NoOpQueryReformulator (which returns the original query); becomes live the moment 999.3 supplies a real implementation. Directly relevant to SC5's stated purpose as a port."
evidence_commands:
  - "cargo test --manifest-path engine/Cargo.toml --locked -> 281 passed / 0 failed / 1 ignored (exit 0). [Collected by the orchestrator this session; cited, not re-run.]"
  - "cd gateway && go test ./... -> 54 passed / 0 failed / 11 skipped (exit 0). [Collected by the orchestrator this session; cited, not re-run.] All 11 skips are TEST_DATABASE_URL-gated and could NOT be run (Docker Desktop not running; nothing on 127.0.0.1:5432)."
  - "TestRAGQueryCrossRuntime (3.09s) and TestRAGQueryClientDisconnectCancelsRustWorkflow (2.22s) are NOT env-gated, DID run, and PASSED."
  - "./engine/target/debug/inspect_lancedb.exe --lancedb-path ./data/lancedb --document-id 11111111-2222-4333-8444-555555555555 -> 'LanceDB document or staging row invariant failed' (exit 1). Run by this verifier. Significance: it got PAST DatabaseManager::open_and_validate (bin/inspect_lancedb.rs:366), so validate_schema no longer reports drift against the rebuilt local store."
  - "grep -rn 'execute_inline_query_rag_remainder' --include=*.rs engine/src -> 0 hits."
  - "grep -n 'd1_status(' engine/src/main.rs -> definition at 1159, call sites at 1777, 1786, 1835."
  - "grep -n 'LANCET_OPENROUTER__GENERATION_MODEL' engine/src/main.rs -> 661; gateway/main_test.go -> 2212, 2786, 3519."
---

# Phase 5: State Machine & Workflow Events — Verification Report

**Phase Goal (User Story):** As a Lancet engineer, I want to formalize RAG orchestration into a Rust state machine, so that I can debug and extend the pipeline with predictable failure handling.
**Mode:** mvp
**Verified:** 2026-08-19 at HEAD `721485c`
**Status:** human_needed
**Score:** 4/5 roadmap success criteria verified, 1 present-but-behavior-unverified
**Re-verification:** Yes — full re-derivation. Supersedes the 2026-08-18 report (`human_needed`, 5/5, HEAD `d84cee2`) in its entirety.

---

## Re-verification Note

Every verdict below was re-derived from the working tree at `721485c`. No prior verdict was carried forward, including the ones that previously passed.

**Two things moved in opposite directions since the last pass.**

The prior report's only recorded regression, **WR-05** (the engine had stopped emitting the `x-lancet-*` gRPC trailers the gateway still read), is **resolved and I confirmed it independently**. `fn d1_status` exists at `engine/src/main.rs:1159-1180` and inserts all three trailers; it is the `Status` constructor at every one of the three pre-stream error paths (1777, 1786, 1835). The human disposition — restore emission rather than delete the reader — is recorded in `05-UAT.md` Test 2. WR-05 is **not** carried forward.

Against that, **SC4 was downgraded**. The previous pass scored 5/5 partly on three Postgres-backed checkpoint tests it ran against a live `lancet-postgres` container. That container is not available in this environment, those tests SKIP, and this verifier will not count a skip as a pass. The code half of SC4 (capture) is provable from source and is proven; the persistence half is not. See SC4 below and `behavior_unverified_items`.

---

## User Flow Coverage (MVP Mode)

The goal validates as a User Story. The `so that` clause — *debug and extend the pipeline with predictable failure handling* — is the success condition, and it maps onto exactly the two criteria with the thinnest evidence (SC3's predictability rests on the CR-01/WR-12 arithmetic; SC4's debuggability rests half on unrun tests). That is stated plainly rather than smoothed over.

| # | Flow step | Expected | Evidence in codebase | Status |
|---|---|---|---|---|
| 1 | Engineer issues a RAG query | Production `query_rag` drives a real node graph, not an inline monolith | `build_production_workflow` (main.rs ~1586-1620) constructs `WorkflowRunner::new().with_timeouts(...)` and adds all five nodes; `execute_inline_query_rag_remainder` has **0** repo-wide hits | VERIFIED |
| 2 | Engineer watches the pipeline progress | Per-node lifecycle events reach an HTTP client as SSE | `events.rs` exposes `node_started`/`node_completed`/`node_failed`/`answer_chunk`/`final_answer`/`checkpoint`/`workflow_completed`; `TestRAGQueryCrossRuntime` proves the full sequence over a real engine process (ran, passed, 3.09s) | VERIFIED |
| 3 | A node hangs or a provider errors | Deterministic timeout / retry / cancel, correctly attributed | Per-kind timeouts (runner.rs:270-330), `tokio::time::timeout`, `NodeFailed{category}`; `TestRAGQueryClientDisconnectCancelsRustWorkflow` proves drop-cancellation end-to-end (ran, passed) | VERIFIED |
| 4 | Engineer inspects what the workflow was holding | A full context snapshot is capturable and durable | Capture: `CHECKPOINT_SNAPSHOT_KEYS` (19 keys, events.rs:15-35) + `events::checkpoint`. Durability: `InsertWorkflowCheckpoint` + `RetainPending` present but **unexercised this pass** | PRESENT_BEHAVIOR_UNVERIFIED |
| 5 | Engineer extends the pipeline (999.3) | A reformulation seam exists with a no-op default | `trait QueryReformulator` (ports.rs:15-21), `NoOpQueryReformulator` (ports.rs:23-40), injected into production at main.rs:1586 | VERIFIED |
| 6 | Engineer runs it for real against OpenRouter | Grounded answer, real citations, clean SSE | **Never performed.** `05-UAT.md` Test 1 = `issue`/blocker; its two blockers are now closed but the run itself has not been repeated | NOT PERFORMED — human |

---

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|---|---|---|
| SC1 | RAG pipeline is formalized into a defined state machine | ✓ VERIFIED | `build_production_workflow` in `engine/src/main.rs` builds a `WorkflowRunner` and registers `ReformulateQueryNode`, `ExtractGraphContextNode`, `RetrieveHybridNode`, `AssemblePromptNode`, `GenerateAnswerNode` (one file each under `engine/src/workflow/nodes/`). The former inline path `execute_inline_query_rag_remainder` returns **zero** hits repo-wide. |
| SC2 | Workflow events stream Rust → Go → Client | ✓ VERIFIED | Nine event constructors in `engine/src/workflow/events.rs`; `WorkflowEventSink` (runner.rs:39-111) feeds the per-request `mpsc::channel(100)` at main.rs:1861 → gRPC stream → gateway SSE. Proven end-to-end by `TestRAGQueryCrossRuntime`, which spawns the **real** engine binary and asserts the frame sequence. Ran and passed this session. |
| SC3 | Node timeouts and retries handle failure predictably | ✓ VERIFIED | Per-node-kind timeouts (`reformulate/graph/retrieve/prompt/generation`, runner.rs:270-330) wired from `[engine.workflow]` config via `with_timeouts`; `tokio::time::timeout` enforcement; `NodeFailed` carries a category and `retryable`; retry on `ProviderError` in `generate.rs`. Client-disconnect cancellation proven by `TestRAGQueryClientDisconnectCancelsRustWorkflow` (ran, passed). CR-01/WR-12 re-derived as unreachable at HEAD — see below. |
| SC4 | Snapshots of workflow state can be captured for debugging | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | **Capture half VERIFIED:** `CHECKPOINT_SNAPSHOT_KEYS: [&str; 19]` (events.rs:15-35) with `events::checkpoint`, emitted per node. **Persistence half UNVERIFIED:** `gateway/checkpoint_sink.go:106-115` builds `InsertWorkflowCheckpointParams` and calls `InsertWorkflowCheckpoint`; `main.go:802` calls `RetainPending`. Both are present and wired, but the FIFO-drain ordering and cancellation-atomicity invariants are state transitions that only the three `TEST_DATABASE_URL`-gated tests exercise — and all three **SKIPPED**. |
| SC5 | QueryReformulator trait defined with pass-through node (Port for 999.3) | ✓ VERIFIED | `pub trait QueryReformulator` at `engine/src/workflow/ports.rs:15-21` (async via `BoxFuture`, cancellation-aware); `NoOpQueryReformulator` at :23-40; `ReformulateQueryNode::with_reformulator(...)` receives `Arc::new(NoOpQueryReformulator::new())` in `build_production_workflow` (main.rs:1586) — a real production injection point, not a test-only seam. |

**Score:** 4/5 truths verified (1 present, behavior-unverified)

### The CR-01 × WR-12 re-derivation (SC3's load-bearing argument)

The refreshed review raises one **critical** finding (CR-01) and a coupled new warning (WR-12). Because SC3 is literally about *predictable* failure handling, a `Timeout` surfacing as `Cancelled` would be a direct hit on the criterion — so I re-derived the argument from source rather than reusing the prior pass's arithmetic.

- `send_envelope` (runner.rs:81-111) has two paths: a `capacity() > 0` fast path (90-98) with a bare `reserve().await`, and a `biased` select (100-110) whose first arm returns `Cancelled`.
- `ClientEventDelivery::Cancelled` can therefore **only** originate from the select path, which is **only** reached when `capacity() == 0`.
- The channel is `mpsc::channel(100)`, constructed per request at main.rs:1861 and handed to the single `WorkflowEventSink::new(...)` at main.rs:1870.
- Repo-wide, excluding `engine/src/tests*`, `WorkflowEventSink` appears only at main.rs:1870, mod.rs:26/167, runner.rs:39/48/335/407/442/449/487. **No production `.clone()` of the sink exists**, so there is exactly one sender.
- Events per workflow: 5 nodes × (node_started + node_completed + checkpoint) = 15, plus exactly **one** `answer_chunk` (runner.rs:381 is the sole emitter, `is_final=true`; there is no per-token streaming), plus 3 terminal events = **19 on the clean path**. Retries push this up — `GenerateAnswerNode` retries on `ProviderError`, and each additional attempt adds a `node_started` + `node_failed` pair — but even retrying *every* node lands around **30**. The bound that matters is not the exact figure: it is that the event count stays **well under 100**, leaving ≥70 slots permanently spare.

Under 100 with a single sender ⇒ `capacity()` never reaches 0 ⇒ the biased arm is never entered ⇒ `NodeFailed` is never replaced by `Cancelled`. **CR-01 does not compromise SC3 at HEAD.**

WR-12's TOCTOU is real as written but shares the same premise: its race needs a *second* sender to steal the last permit, and with one sender and 81 spare slots there is no permit contention. **WR-12 does not invalidate the arithmetic** — the two findings are coupled and go live together, under the same conditions (per-token streaming, a smaller buffer, or a shared sink).

The honest caveat: this guard is an *emergent consequence of a size constant*, not an enforced invariant. Nothing in the type system or a test pins `19 < 100`. That is why the CR-01/WR-12 disposition is listed as a human decision rather than silently absorbed.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|---|---|---|---|
| ORCH-01 | Lightweight Rust state machine for the fixed RAG path | ✓ SATISFIED | SC1 evidence; `REQUIREMENTS.md:32` `[x]` |
| ORCH-02 | Client-facing workflow events | ✓ SATISFIED | SC2 evidence; `REQUIREMENTS.md:33` `[x]` |
| ORCH-03 | Cancellation, timeouts, retry/fallback | ✓ SATISFIED | SC3 evidence; `REQUIREMENTS.md:34` `[x]` |
| ORCH-04 | Lightweight checkpoints/snapshots | ⚠️ PARTIAL | Capture verified; Postgres persistence unexercised (see SC4). `REQUIREMENTS.md:35` `[x]` |
| ORCH-05 | Dedicated `reformulate` stage, pass-through in v1 | ✓ SATISFIED | SC5 evidence; `REQUIREMENTS.md:36` `[x]` |
| GATE-01 | SSE wire contract roundtrip & error framing | ✓ SATISFIED | `REQUIREMENTS.md:37` `[x]`, retroactively formalized per UAT Test 3 + errata §8 |
| GATE-02 | Checkpoint ownership across pending/shutdown/Postgres | ⚠️ PARTIAL | Same persistence caveat as ORCH-04. `REQUIREMENTS.md:38` `[x]` |

**On the two ⚠️ PARTIAL rows carrying a `[x]`:** this is deliberate, not the contradiction it looks like. ORCH-04 and GATE-02 are graded PARTIAL because the *evidence* for their persistence half could not be produced in this environment (Postgres down) — not because an implementation is missing. The checkbox tracks delivery, and delivery is complete: the code is present, wired, and covered by tests that exist and are named. I am therefore **not** recommending the checkboxes be reverted; doing so would recreate the prior pass's TRACE-CHECKBOX warning in mirror image. The shortfall is recorded where it belongs — in `behavior_unverified_items`.

**All five phase requirement IDs (ORCH-01..ORCH-05) are accounted for. No orphans.** The prior pass's `TRACE-GATE` and `TRACE-CHECKBOX` warnings are both resolved: GATE-01/GATE-02 are now real, described, Phase-05-attributed requirements; GATE-03 was removed as having zero coverage behind it; ORCH-01 and ORCH-05 are checked.

### G-05-1 gap closure assessment

| Blocker | Fix claimed | Verified at HEAD? |
|---|---|---|
| A — code half | `validate_schema` gains remediation guidance | ✓ YES — `engine/src/db/mod.rs:167-172` carries `"Remediation: schema reconciliation is fail-closed by design; rename or remove the stale LanceDB store directory and regenerate tables (e.g. via seed_rag_fixture or re-ingestion)."`. Note it is appended *after* two full 19-field `{:?}` dumps (WR-13) — present, but poorly placed for an operator. |
| A — data half | Local `./data/lancedb` rebuilt and reseeded | ✓ YES, empirically. `data/` is gitignored so repo state cannot show this, but I ran `inspect_lancedb.exe` against the store: it passed `DatabaseManager::open_and_validate` and failed only on a downstream document-lookup invariant. **Transfer to the startup path confirmed by source** (see note below). `data/lancedb.pre-05-25.bak` is preserved as planned. |
| A — design decision | `validate_schema` stays strict fail-closed, no auto-migration | ✓ CONFIRMED — the check at `db/mod.rs:166` is still `actual.fields() != expected.fields()` with no reconciliation path. This is the plan's stated intent, not a shortfall. |
| B | Explicit model env overrides + test decoupling | ✓ YES — `engine/src/main.rs:661` (`LANCET_OPENROUTER__GENERATION_MODEL`) and `:666` (`LANCET_OPENROUTER__EMBEDDING_MODEL`); `gateway/main_test.go:2212` and `:3519` pin the spawned engine's model; `:2786-2787` extend the `assertCleanRAGChildEnv` allowlist. See WARN-NEW-01 for the residual cost. |

**Note on the Blocker A transfer.** My probe exercises `open_and_validate`, while 05-25's stated key link is `main() → initialize → validate_schema`. These are not the same function, so I checked whether the result transfers rather than assuming it. It does, and conservatively: `initialize` (db/mod.rs:21) delegates to `initialize_tables`, which iterates the **same** `table_schemas()` set and calls the **same** `validate_schema` per table (db/mod.rs:106) that `open_and_validate` calls at db/mod.rs:58. The only differences make `initialize` *more* permissive — it creates missing tables instead of erroring, and applies the additive `staged_documents_v2` `generation`-column migration **before** validating. So the path I exercised is the stricter of the two; passing it implies `main()`'s startup gate (main.rs:3215) passes. What remains unexercised is only the rest of `main()`'s boot sequence after the DB gate, which is covered by the live-run human item.

**Both blockers are closed in code. The live end-to-end run of UAT Test 1 has NOT been performed.** Closing the blockers removes the obstacles to the test; it is not a substitute for it. The run requires a real `OPENROUTER_API_KEY` and a human at the terminal, and no verifier can produce that evidence.

### Anti-Patterns

Debt-marker scan over the files touched by the post-verification commits (`engine/src/db/mod.rs`, `engine/src/db/tests.rs`, `engine/src/main.rs`, `engine/src/tests.rs`, `gateway/main_test.go`, `config/config.toml`): **zero** `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, `PLACEHOLDER`, `unimplemented!`. No blocker-severity anti-patterns.

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist in this repository, and no PLAN in this phase declares one. Step 7c: **SKIPPED (no probes defined)**.

---

## Scope of This Verification

Stated plainly so the next reader can calibrate:

1. **Roadmap success criteria (5) were verified exhaustively from source.** These are the contract.
2. **Plan-level `must_haves.truths` across all 26 plans were NOT separately enumerated.** For plans 05-25 and 05-26 — the only two the prior pass did not cover — I read the frontmatter and checked each truth against HEAD (all satisfied, with the WARN-NEW-01 caveat on 05-26). For 05-01..05-24 I relied on roadmap-SC coverage plus the refreshed 05-REVIEW.
3. **No test suite was re-run by this verifier.** The engine (281/0/1) and gateway (54/0/11) results were collected by the orchestrator this session and are cited, not reproduced. The one command I ran myself is the `inspect_lancedb` schema probe.
4. **11 gateway tests could not run.** Docker Desktop is not running; nothing listens on 127.0.0.1:5432. This is why SC4 is not green.
5. **`05-UAT.md` was read, not modified.** Its three recorded human resolutions (Tests 2, 3, 4) are treated as authoritative and are reflected in `gaps_closed`.

## Gaps Summary

**No gaps.** Nothing is missing, stubbed, unwired, or regressed. The state machine is real, production-wired, event-emitting, timeout-governed, cancellable, and extensible at the reformulation seam. The prior pass's single regression is fixed and its traceability warnings are reconciled.

What stands between this phase and `passed` is **evidence that cannot be produced without a human and infrastructure**:

- the live OpenRouter run (needs a real API key — and is now *more* necessary, not less, because 05-26 pinned the integration tests to a model that is not the shipped one);
- the eleven Postgres-gated tests (needs a database).

Both are recorded above. The phase is functionally complete; its verification is not.

---

_Verified: 2026-08-19T03:10:00Z at HEAD `721485c`_
_Verifier: Claude (gsd-verifier)_
