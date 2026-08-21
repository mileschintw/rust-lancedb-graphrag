---
phase: 6
reviewers: [antigravity, claude]
reviewed_at: 2026-08-21T23:30:58Z
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md, 06-08-PLAN.md, 06-09-PLAN.md, 06-10-PLAN.md, 06-11-PLAN.md, 06-12-PLAN.md, 06-13-PLAN.md, 06-14-PLAN.md]
models:
  antigravity: "gemini-3.7-flash-high (reasoning=high)"
  claude: "opus (reasoning=high)"
model_sources:
  antigravity: "pinned"
  claude: "pinned"
---

# Cross-AI Plan Review — Phase 6

This file **replaces** the stale 2026-08-20 review (`antigravity` + `claude` over plans 06-01…06-12). ROADMAP now lists **14 plans** (12 executed + 2 gap-closure). This pass re-reviews the live plan set, including `06-13-PLAN.md` and `06-14-PLAN.md`, against the working tree.

Both lanes ran source-grounded against `D:/Repos/lancet` with tool use and permission auto-approve. Neither output carries a `[reviewed-without-repo-access]` or `[reviewed-without-source-citations]` marker, so both verdicts count at full consensus weight. The assembled prompt was untrimmed. No `trimmed_reviewers` block is recorded.

Antigravity: `agy --model gemini-3.7-flash-high --effort high --dangerously-skip-permissions --add-dir --print-timeout 20m`. The CLI model catalog has no bare `gemini-3.7-flash` id; high effort is the `-high` suffix plus `--effort high`.
Claude: `claude --model opus --effort high --allow-dangerously-skip-permissions --dangerously-skip-permissions --permission-mode bypassPermissions`.

## Consensus Summary

The prior-round 06-01…06-12 defects are treated as **landed**. Both reviewers independently confirm the remaining blockers are the two gap-closure plans: **SC3 / 06-13** (`OpenRouterGenerator::execute_one_call` still packs empty evidence via `pack_evidence_and_graph_prompt` → `EmptyEvidence` → `LlmGenerationFailed`) and **SC5 / 06-14** (`repaired_citations` one entry per marker occurrence → duplicate-id rejection in `validate_grounding_with_limits`). Both traced the same sites (`openrouter.rs:477-495`, `prompt.rs:338-340`, `generate.rs:195-224`, `generation/mod.rs:320-329`).

The material disagreement is **whether 06-13/06-14 as written will close those SCs under the same verification standard that opened them**. Claude rates the gap-plan **verify gates HIGH** (name-filtered `cargo test` exits 0 when zero tests match) and SC3's node-vs-adapter split HIGH. Antigravity rates 06-13 **LOW–MEDIUM** and 06-14 **LOW** and recommends executing both as written. Consensus planning weight: keep the 06-13/06-14 designs, but add Claude's fail-closed `--list | grep -qF` gates and one production-shaped SC3 runner test before treating SC3 closed.

### Agreed Strengths

- **Wave sequencing still matches file overlap.** Wave 12's `depends_on: [06-11, 06-13]` is load-bearing (`generate.rs`, `prompt.rs`, `workflow_phase5.rs`, test-count gate).
- **SC3 and SC5 root-cause claims survive source checks.** Empty-evidence packing abort and per-occurrence `repaired_citations` → duplicate-id validation are both real.
- **06-14's fix site is the right one.** Deduplicate at `repaired_citations` construction, not inside `extract_markers`/`resolve_markers`, so per-occurrence span edits stay intact.
- **Module-graph + additive proto front-load remains endorsed** (D-75/D-80/D-81/D-74). Per-target test-count gates are still the load-bearing invariant.

### Agreed Concerns

- **[HIGH on Claude / acknowledged as the original defect by both] Production path vs mock.** 06-10/06-11 tests used `FakeGenerator` / single-marker answers; production OpenRouter packing and duplicate repaired ids were untested. 06-13/06-14 exist to close that. Claude: still no single test that wires nodes the way `service.rs:116-157` does.
- **[HIGH on Claude only — treat as planning input] 06-13 and 06-14 `<verify>` blocks are name-filtered `cargo test`, which is not fail-closed.** A missing test still exits 0. Prefix with `cargo test -- --list | grep -qF '<name>'`.
- **[MEDIUM on Claude] 06-13 Task 1 leaves the packing helper signature and empty-branch validation slice (`&[]`) unspecified.**
- **[MEDIUM on Claude] `run_inline_prompt_generation_remainder` still omits `allow_model_only`** (`workflow/mod.rs`; not in 06-13 `files_modified`).

### Divergent Views

- **Overall risk:** Antigravity **LOW** on the remaining gap plans and recommends executing 06-13 then 06-14. Claude **MEDIUM**, with fail-closed gates and a production-shaped SC3 test required before calling SC3 closed. Follow Claude on verification rigor; follow both on the code-level fix sites.
- **SSE `degraded_mode: false` synthesis** when metadata is nil (`gateway/internal/sse/sse.go:123-135`): Antigravity MEDIUM; Claude did not raise it. Phase 6.2 owns metadata population — flag, do not block 06-13/06-14.
- **D-19 vs D-10 outbound schema enum admission of `model_only`:** Claude MEDIUM (record the disposition). Antigravity treats it as required for SC3.
- **config-rs prefix_separator / LANCET__ trap** (`config.rs:600`): Antigravity LOW; Claude did not raise it. Future cleanup, not a Phase 6 blocker.

---


## Antigravity Review

# Cross-AI Plan Review: Phase 6 (Observability, Evaluation & Polish)

## Executive Summary

Phase 6 implements the Rust and Go module-graph restructure, consolidated additive Protobuf changes, and RAG-03 degraded-mode hardening across 14 plans (Waves 1–12, including Gap Closure plans 06-13 and 06-14). The foundational architectural refactorings (Plans 06-01 through 06-05) successfully eliminated the dual `lib.rs`/`main.rs` declaration in Rust (`DEBT-P3-MODULE-GRAPH`) and extracted modular Go packages (`internal/config`, `internal/sse`, `internal/engineclient`), enforcing strict per-target test accounting. The additive wire contract (Plan 06-07) cleanly established typed notice codes and opt-in flags. While the initial behavior execution (Plans 06-08 through 06-12) delivered partial retrieval degradation and bad-input rejection, verification surfaced two blockers on production paths: model-only prompt assembly failure on empty evidence (SC3) and duplicate citation ID validation failure on repeated markers (SC5). Plans 06-13 and 06-14 provide targeted, precise gap closures for these regressions. Overall phase execution and gap-closure design are robust and well-bounded.

---

## Phase-Level Evaluation

### Strengths
- **Rigid Invariant Gates:** Plans 06-01 through 06-03 enforced exact test counts across targets (`scripts/engine-test-targets.sh`), guaranteeing zero test loss during extensive module moves.
- **Additive-Only Wire Evolution:** Protobuf changes in `proto/lancet/v1/lancet.proto:61-125` preserved backwards compatibility, reserved tag 17, and generated synchronized Rust and Go stubs in a single wave (Plan 06-07) before behavior changes began.
- **Zero-Network Degraded Mode:** Partial retrieval failures (`engine/src/workflow/nodes/retrieve.rs:88,141`), graph unavailabilities (`engine/src/workflow/nodes/graph_context.rs:126,172`), and citation repairs (`engine/src/generation/citations.rs:171`) operate deterministically in-process with machine-readable notice emission without triggering secondary LLM provider calls.
- **Explicit Gap Remediation:** Plans 06-13 and 06-14 directly address the subtle production-adapter gaps identified during initial phase verification rather than relying on synthetic testkit mocks.

### Key Risks & Concerns
- **Production Path vs. Mock Divergence (HIGH - Addressed in 06-13):** Plan 06-10 tested model-only generation against `FakeGenerator` without grounding limits (`engine/src/tests/workflow_phase5.rs:5160`), allowing `openrouter.rs:477` to fail silently in production due to `pack_evidence_and_graph_prompt` returning `PromptAssemblyError::EmptyEvidence`. Plan 06-13 is required to bridge this gap.
- **Citation Repair Duplicate Invalidation (HIGH - Addressed in 06-14):** In Plan 06-11, `engine/src/workflow/nodes/generate.rs:195-202` pushed resolved citation markers per occurrence into `repaired_citations`, triggering duplicate ID rejection in `validate_grounding_with_limits` (`engine/src/generation/mod.rs:320-329`). Plan 06-14 resolves this via first-occurrence deduplication.
- **Gateway SSE Degraded-Mode Serialization (MEDIUM):** In `gateway/internal/sse/sse.go:123-135`, when `WorkflowCompletedEvent.metadata` is `nil` (deferred to Phase 6.2), the gateway synthesizes `"degraded_mode": false`, emitting a misleading false-healthy claim on degraded runs.
- **Declarative Environment Variable Prefix Trap (LOW):** In `engine/src/config.rs:600`, `Environment::with_prefix("LANCET").separator("__")` without `.prefix_separator("_")` causes declarative viper parsing to expect `LANCET__` rather than `LANCET_`. Hand-written override helpers at `config.rs:652-674` bypass this for specific keys, but general keys remain affected.

---

## Detailed Plan-by-Plan Review

---

### Plan 06-01: Rust Module Graph Step 1 (Chunker & Config)

#### 1. Summary
Moves `chunker` and configuration loading into the library crate root (`engine/src/lib.rs`), introducing `scripts/engine-test-targets.sh` to enforce per-target test invariants across the refactor.

#### 2. Strengths
- Adheres to `rust-guidelines.md` M-SINGLE-ITEM-PATH by exporting canonical paths (`engine::chunker`, `engine::config`) from `lib.rs:7-9`.
- Introduces `scripts/engine-test-targets.sh` tracking target-specific test counts (lib, engine binary, inspect_lancedb, config_startup).
- Preserves exact environment variable naming conventions (`LANCET_*__*`) across the relocation.

#### 3. Concerns
- **[LOW]** `engine/src/config.rs:600`: `config-rs` 0.15 without `.prefix_separator("_")` skips declarative parsing for standard `LANCET_ENGINE__*` variables (mitigated by custom override parsers for critical flags at `config.rs:652-674`).

#### 4. Suggestions
- Add `.prefix_separator("_")` to `Environment::with_prefix("LANCET")` in `config.rs:600` in a future cleanup phase for consistent declarative env handling.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Pure refactoring step backed by deterministic test target counters.

---

### Plan 06-02: Rust Module Graph Step 2 (Ingest & Service)

#### 1. Summary
Relocates the ingestion pipeline and gRPC service implementation into `engine::ingest` and `engine::service`, exposing them from `engine/src/lib.rs`.

#### 2. Strengths
- Exposes `LancetService` (`engine/src/lib.rs:18`) to integration test harnesses and library consumers.
- Preserves gRPC service routing and async pipeline boundaries without runtime churn.

#### 3. Concerns
- **[LOW]** `engine/src/service.rs:763-764`: Dead binding `let _disable_graph_context = req.disable_graph_context.unwrap_or(false);` remained after refactoring (live path reads from `WorkflowContext::new`).

#### 4. Suggestions
- Remove unused binding in `engine/src/service.rs:763-764` during subsequent cleanup.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Straightforward code relocation verified by unit and integration suites.

---

### Plan 06-03: Rust Module Graph Step 3 (Binary Test Rehoming & main.rs Minimization)

#### 1. Summary
Rehomes integration and workflow tests under `engine/src/tests/` and reduces `engine/src/main.rs` to minimal startup wiring without `mod` statements.

#### 2. Strengths
- Fully resolves `DEBT-P3-MODULE-GRAPH` (D-80); `main.rs` contains zero module declarations and only imports from `engine::*`.
- Standardizes test discovery and accelerates execution under `cargo test --lib`.

#### 3. Concerns
- **[LOW]** `engine/src/workflow/mod.rs:249-363`: `run_inline_prompt_generation_remainder` remains marked `pub` rather than `#[cfg(test)] pub(crate)`.

#### 4. Suggestions
- Restrict visibility of test-only workflow execution paths to `#[cfg(test)]`.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Complete structural stabilization of the engine crate.

---

### Plan 06-04: Go Package Split Part A (internal/config, internal/sse, internal/telemetry)

#### 1. Summary
Splits Go gateway concerns by extracting `internal/config`, `internal/sse`, and creating the `internal/telemetry` stub, introducing `scripts/gateway-test-packages.sh`.

#### 2. Strengths
- Removes repetitive and error-prone SSE framing strings from `gateway/main.go`, delegating to `sse.WriteStreamError` and `sse.WriteWorkflowEvent`.
- Establishes a multi-package Go test verification script.

#### 3. Concerns
- **[MEDIUM]** `gateway/internal/sse/sse.go:123-135`: When `WorkflowCompletedEvent.metadata` is `nil`, the `else` block serializes `"degraded_mode": false`, broadcasting an inaccurate non-degraded status for degraded runs.

#### 4. Suggestions
- Omit `degraded_mode` or metadata serialization when `GetMetadata()` is `nil` instead of synthesizing a false negative.

#### 5. Risk Assessment
- **Risk Level:** **LOW to MEDIUM**. SSE serialization issue is minor but impacts client observability fidelity until Phase 6.2.

---

### Plan 06-05: Go Package Split Part B (internal/engineclient)

#### 1. Summary
Extracts gRPC client initialization and communication into `gateway/internal/engineclient`, preserving existing test suite compatibility.

#### 2. Strengths
- Encapsulates `lancetv1.NewLancetServiceClient` creation and gRPC dial management in `gateway/internal/engineclient/engineclient.go`.
- Retains compatibility with all existing gateway test fixtures.

#### 3. Concerns
- **[LOW]** Insecure credentials dial is retained (`DEBT-CR-04-EXT`), properly acknowledged and deferred to Backlog Phase 999.1.

#### 4. Suggestions
- None.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Clean separation of concerns with no behavioral divergence.

---

### Plan 06-06: Wave-0 Test Surface (engine::testkit & Port Fakes)

#### 1. Summary
Constructs `engine::testkit` helpers (`StubCandidatePool`, `FakeGraphPort`, `FakeSearchBackend`) and exact payload key assertions in Go to support behavior plans.

#### 2. Strengths
- Eliminates brittle boilerplate literals across 100+ tests by centralizing testkit builders.
- Provides controlled failure injection mechanisms for graph and retrieval ports.

#### 3. Concerns
- **[LOW]** Testkit abstractions must be maintained alongside production port trait evolutions.

#### 4. Suggestions
- Ensure testkit components remain isolated under test-only compilation flags.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Significantly increases maintainability of subsequent test suites.

---

### Plan 06-07: Consolidated Additive Wire Contract

#### 1. Summary
Implements single consolidated Protobuf modifications in `proto/lancet/v1/lancet.proto`, regenerates Rust and Go bindings via `buf`, and introduces typed notice constructors.

#### 2. Strengths
- Consolidates all wire additions (fields 4 & 5 on `QueryRAGRequest`, field 4 on `Notice`, field 7 on `WorkflowCompletedEvent`, and `NoticeCode` enum) into one atomic change (D-74).
- Preserves tag 17 as reserved and guarantees field presence preservation via `optional bool` / `*bool`.
- Introduces `crate::workflow::notice(code, message, severity)` enforcing enum synchronization.

#### 3. Concerns
- **[LOW]** `WorkflowCompletedEvent.metadata` field added to the schema remains unpopulated (`metadata: None` in `engine/src/workflow/events.rs:372`), correctly deferred to Phase 6.2 (OBS-01).

#### 4. Suggestions
- None; contract changes follow best practices.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Clean schema evolution with full backwards compatibility.

---

### Plan 06-08: Behavior Tracer (Graph Ablation & Graph Unavailable Notices)

#### 1. Summary
Implements the `disable_graph_context` ablation request flag and emits `NoticeCode::GraphUnavailable` on silent degrade paths, backed by source-chunk retrieval independence proofs.

#### 2. Strengths
- Resolves `DEBT-RAG-06` by emitting typed notices on previously silent paths: empty graph results (`engine/src/workflow/nodes/graph_context.rs:126-132`) and absent graph ports (`engine/src/workflow/nodes/graph_context.rs:172-178`).
- Proof tests (`source_chunk_query_succeeds_when_graph_*`) conclusively demonstrate source-chunk query independence from graph availability.

#### 3. Concerns
- **[LOW]** Clients must properly handle distinction between deliberate ablation (`GraphAblation`) and unconfigured/empty store (`GraphUnavailable`).

#### 4. Suggestions
- Ensure client documentation reflects notice semantics.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Fully verified by unit and integration tests.

---

### Plan 06-09: Retrieval Degraded Mode

#### 1. Summary
Converts dense vector and BM25 lexical retrieval nodes from fail-closed to degrade mode, emitting `RetrievalDegradedDense` and `RetrievalDegradedBm25` notices while preserving surviving results.

#### 2. Strengths
- Implements core RAG-03 (DEBT-RAG-01) requirement: partial retrieval failure returns grounded answers with `answer_basis = RETRIEVAL` and machine-readable notices (`engine/src/workflow/nodes/retrieve.rs:88,141`).
- Robust handling of multi-variant BM25 errors, preventing duplicate notice pollution while retaining distinct error messages.

#### 3. Concerns
- **[LOW]** Total retrieval failure (both dense and lexical failing) leaves evidence empty, falling through to the model-only decision path.

#### 4. Suggestions
- None.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Critical reliability improvement, heavily tested across 16+ failure scenarios.

---

### Plan 06-10: Model-Only Opt-In

#### 1. Summary
Adds the `allow_model_only` request override and `allow_model_only_answers` configuration key, bypassing zero-evidence short-circuits and returning ungrounded answers with `NoticeCode::ModelOnly`.

#### 2. Strengths
- Enforces strict contract: ungrounded answers are explicitly declared (`answer_basis = MODEL_ONLY`), citation lists are cleared (`ctx.structured_citations.clear()`), and a notice is emitted.
- Preserves fail-closed behavior when `allow_model_only` is false.

#### 3. Concerns
- **[HIGH]** **Production Path Defect (Gap SC3):** The plan only validated against `FakeGenerator` without grounding limits (`engine/src/tests/workflow_phase5.rs:5160`). In production (`service.rs:148-157`), `OpenRouterGenerator::execute_one_call` unconditionally called `pack_evidence_and_graph_prompt`, which returns `PromptAssemblyError::EmptyEvidence` and terminates the run with `LLM_GENERATION_FAILED`. Furthermore, the outbound JSON schema excluded `model_only` from `answer_basis`. (Remediated by Plan 06-13).
- **[MEDIUM]** `engine/src/workflow/nodes/generate.rs:233-266`: `effective_allow = ctx.allow_model_only || total_drop` sets `answer_basis = MODEL_ONLY` on total citation drop even when `allow_model_only` is false, but emits `CITATION_DROPPED` / `BASIS_RECONCILED` rather than `NoticeCode::ModelOnly`.

#### 4. Suggestions
- Execute Plan 06-13 to complete the wiring on the real OpenRouter packing and schema paths.

#### 5. Risk Assessment
- **Risk Level:** **HIGH** (in isolation; mitigated by Plan 06-13).

---

### Plan 06-11: Citation Repair (Normalize-then-Strip)

#### 1. Summary
Implements local citation normalization and stripping for near-miss markers (`DEBT-RAG-03`), emits repair/drop notices, and enforces conservative basis reconciliation without secondary provider calls.

#### 2. Strengths
- Pure local resolution (`engine/src/generation/citations.rs:171-198`) using NFKC normalization, whitespace trimming, and bracket stripping without network roundtrips.
- Prompt precedence rule enforced in `engine/src/prompt.rs:211` ("When evidence contradicts your prior knowledge, the evidence is authoritative; say so.").
- Conservative basis reconciliation downgrades basis if grounding is lost.

#### 3. Concerns
- **[HIGH]** **Duplicate Marker Failure (Gap SC5):** `generate.rs:185-231` appended to `repaired_citations` for every marker occurrence. When passed to `validate_grounding_with_limits` (`engine/src/generation/mod.rs:320-329`), answers with repeated markers (`[1]...[1]`) or mixed spellings (`[ 7 ]` and `[7]`) were rejected as duplicate IDs, causing `LlmGenerationFailed`. (Remediated by Plan 06-14).

#### 4. Suggestions
- Execute Plan 06-14 to deduplicate `repaired_citations` while preserving individual text replacement spans.

#### 5. Risk Assessment
- **Risk Level:** **HIGH** (in isolation; mitigated by Plan 06-14).

---

### Plan 06-12: Enumerated Bad-Input Matrix

#### 1. Summary
Establishes table-driven tests on gRPC and HTTP gateway surfaces verifying immediate rejection of malformed IDs, lengths, and filter bounds with `InvalidArgument` / HTTP 400 before retrieval or LLM execution.

#### 2. Strengths
- Comprehensive test matrix (`engine/src/tests/bad_input_matrix.rs`) asserting `fake_gen.calls() == 0`, proving rejection prior to resource-intensive processing.
- Symmetric validation testing on Go gateway (`gateway/main_test.go:1415`).

#### 3. Concerns
- **[LOW]** Contains a flagged-unverified manual prohibition regarding the unclassified RAG-03 probe edge from the specless probe report, properly escalated to human verification in `06-VERIFICATION.md`.

#### 4. Suggestions
- Formally log the disposition of the unclassified RAG-03 probe edge during milestone closure.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Solidifies API input validation boundaries.

---

### Plan 06-13: Gap Closure for SC3 (OpenRouter Model-Only Production Path)

#### 1. Summary
Closes Gap SC3 by plumbing `allow_model_only` to `GenerationRequest`, introducing `model_only_system_policy`, adding an empty-evidence packing branch in `OpenRouterGenerator`, and admitting `model_only` to the outbound JSON schema enum.

#### 2. Strengths
- **Root-Cause Fix:** Prevents `execute_one_call` from calling `pack_evidence_and_graph_prompt` when evidence is empty and `allow_model_only` is true, eliminating `PromptAssemblyError::EmptyEvidence` aborts.
- **Policy Alignment:** Replaces contradictory evidence citation instructions in `pack_model_only_prompt` with a dedicated `model_only_system_policy` (`engine/src/prompt.rs`).
- **Schema Admission:** Adds `"model_only"` to the `answer_basis` enum (`engine/src/generation/openrouter.rs:524`), allowing structured-output models to emit the valid basis.
- **Realistic Testing:** Introduces `generate_answer_node_model_only_empty_evidence_uses_production_packing_path` utilizing `.with_settings(...)` and real packing logic.

#### 3. Concerns
- **[LOW]** LLM providers using strict JSON schema validation must accept the expanded enum (supported by OpenRouter and OpenAI).

#### 4. Suggestions
- Verify in mock HTTP tests that the serialized request body contains the updated JSON schema enum.

#### 5. Risk Assessment
- **Risk Level:** **LOW to MEDIUM**. Essential for fulfilling Success Criterion 3.

---

### Plan 06-14: Gap Closure for SC5 (Citation Repair Deduplication)

#### 1. Summary
Closes Gap SC5 by deduplicating `repaired_citations` in `GenerateAnswerNode` and `resolve_citations_with_max_chars` in `engine/src/prompt.rs`, allowing repeated and mixed-spelling markers to succeed.

#### 2. Strengths
- **Surgical Fix:** Deduplicates `repaired_citations` at insertion time in `generate.rs` without altering 1:1 marker occurrence extraction or right-to-left text replacement spans.
- **Structured Citation Uniqueness:** Updates `resolve_citations_with_max_chars` (`engine/src/prompt.rs:581`) to prevent duplicate `StructuredCitation` objects on the wire.
- **Targeted Test Coverage:** Adds explicit tests for repeated markers (`[1]...[1]`) and mixed spellings (`[ 7 ]` + `[7]`) resolving to the same evidence ID.

#### 3. Concerns
- **[LOW]** None identified.

#### 4. Suggestions
- Ensure first-occurrence ranking and excerpt metadata are preserved when deduplicating structured citations.

#### 5. Risk Assessment
- **Risk Level:** **LOW**. Clean, well-tested bug fix completing Success Criterion 5.

---

## Conclusion

The architecture, refactoring, and degraded-mode mechanisms designed across Phase 6 are exceptionally well-structured and disciplined. Plans 06-01 through 06-12 successfully established the new module graphs and wire contracts. The two substantive production defects discovered during verification (SC3 and SC5) are cleanly resolved by Gap Closure Plans 06-13 and 06-14. Approval and execution of Plans 06-13 and 06-14 are recommended to complete Phase 6 and unblock Phase 6.1.

---

## Claude Review

## Cross-AI Plan Review — Lancet Phase 6 (`06-01` … `06-14`)

Reviewed with full repo access at `D:/Repos/lancet`. Every claim below was checked against the working tree; commands run are noted inline.

---

## 1. Summary

This is an unusually disciplined plan set: 12 executed plans that correctly front-load the D-75 sequence (module graph → wire contract → behavior), plus two gap-closure plans written against a real verification report rather than against intent. I verified the two gap-closure plans' root-cause claims line by line and **they are accurate**: `OpenRouterGenerator::execute_one_call` does unconditionally call `pack_evidence_and_graph_prompt` (`engine/src/generation/openrouter.rs:477-495`), which returns `EmptyEvidence` (`engine/src/prompt.rs:338-340`); the outbound schema really does pin `answer_basis` to `["retrieval","mixed"]` (`openrouter.rs:522-525`, asserted at `engine/src/generation/tests.rs:875-878`); `pack_model_only_prompt` really does reuse the grounded `base_system_policy()` (`prompt.rs:215-217`); `ctx.assembled_prompt` really is written (`engine/src/workflow/nodes/assemble_prompt.rs:76`) and never read by the generator (`generate.rs:102-103`); and citation repair really does push one `repaired_citations` entry per marker occurrence (`generate.rs:195-224`) into a validator that rejects duplicate ids (`generation/mod.rs:320-329`), with `citations::resolve_markers` a strict 1:1 `.map` (`citations.rs:171-198`). The fixes proposed are the minimal correct ones. The dominant weakness is **verification rigor, not design**: the per-task `<verify>` gates in both gap plans are name-filtered `cargo test` invocations, which I empirically confirmed exit 0 when the filter matches nothing — so a plan whose named tests are never written passes every gate it declares. That is the same class of blind spot (green suite, bypassed production path) that produced the SC3/SC5 failures in the first place, and neither plan adds a structural guard against it.

---

## 2. Strengths

- **Sequencing is grounded in measured file overlap, not intuition.** ROADMAP Wave 12's stated reason ("generate.rs, prompt.rs, workflow_phase5.rs, and the test-count gate overlap") is correct: `06-13`'s `files_modified` and `06-14`'s intersect on exactly those four paths. The `depends_on: [06-11, 06-13]` on `06-14` is load-bearing, not ceremonial.
- **Root-cause claims survive source verification.** Unlike plans that restate a symptom, `06-13`'s failure chain is traceable end to end. `EmptyEvidence` → `GenerationErrorKind::InvalidRequest` (`openrouter.rs:491-494`) → not in the retryable set (`generate.rs:126-127`) → `LlmGenerationFailed`. The plan's narrative matches the code exactly.
- **`06-14` chooses the minimal correct fix.** It explicitly forbids de-duplicating inside `extract_markers`/`resolve_markers` ("that would skip span edits") and instead de-dupes at `repaired_citations` construction. I traced both reproductions: with dedupe, `seen_cited = {"[1]"}` and `inline_set = {"[1]"}` still satisfy the set-equality check at `generation/mod.rs:356-365`, and per-occurrence span edits at `generate.rs:226-231` remain intact. The fix is correct and surgical.
- **Regression pins are named, not implied.** `06-13` pins `pack_evidence_and_graph_prompt_empty_evidence_still_errors_regardless_of_graph_facts` as a must-stay-passing test; `06-14` pins `citation_repair_makes_no_additional_provider_call`. Both exist and both would genuinely catch the corresponding over-reach.
- **The test-count gate is real and currently green.** `sh scripts/engine-test-targets.sh` → lib 338 / bin 0 / inspect 18 / seed 0 / config_startup 17, TOTAL 373, exit 0. `sh scripts/gateway-test-targets.sh` → gateway 65 / db 7 / sse 8, TOTAL 80, exit 0. The per-target design (rather than one aggregate) is what made the 06-01→06-03 module relocation attributable.
- **Unresolved items are refused rather than absorbed.** Both gap plans restate the two `human_verification` items and the `specless-probe` prohibition as explicitly *not* closed by this work. That is the right disposition and it is rare.

---

## 3. Concerns

### HIGH — Every per-task gate in `06-13` and `06-14` is a name-filtered `cargo test`, which is not fail-closed

Both plans verify their central deliverables exclusively with name filters, e.g. `06-13` Task 1:

```
cargo test --lib --manifest-path engine/Cargo.toml --locked -- generate_answer_node_model_only_empty_evidence_uses_production_packing_path
```

I ran the equivalent against a bogus name:

```
$ cargo test --lib --manifest-path engine/Cargo.toml -- zzz_definitely_not_a_real_test_name
running 0 tests
test result: ok. 0 passed; 0 failed; ... 338 filtered out
EXIT=0
```

A misnamed, mis-scoped (e.g. placed in a `#[cfg(test)]` module that is never declared), or never-written test satisfies the gate. The count gate does not compensate, because the same executor writes the expected value in the same commit — any test satisfies the delta. This applies to all three `06-13` verify blocks and both `06-14` verify blocks.

**Fix:** prefix each with an existence assertion, e.g.
`cargo test --lib --manifest-path engine/Cargo.toml -- --list | grep -qF 'generate_answer_node_model_only_empty_evidence_uses_production_packing_path' && cargo test --lib ... -- <name>`.

### HIGH — After `06-13`, SC3 is proven in two disjoint halves that never meet

`06-13` Task 1 proves the packing helper at the *node* level (`GenerateAnswerNode.run` with a fake generator that calls the helper). Task 3 proves the empty-evidence branch at the *adapter* level (mock HTTP against `execute_one_call`). Neither drives `WorkflowRunner` with nodes wired the way `LancetServiceImpl::build_production_workflow` wires them (`engine/src/service.rs:116-157`).

That is exactly the shape of the original defect. The existing SC3 test does drive the full runner but constructs `AssemblePromptNode::new()` and `GenerateAnswerNode::new(Some(fake_gen))` (`engine/src/tests/workflow_phase5.rs:5199-5200`) — no `.with_settings(...)`, no `.with_citation_repair_enabled(...)`, default budgets. A re-verifier applying the same standard that produced the SC3 finding could reasonably score SC3 `partial` again after `06-13` lands.

**Fix:** add one test that assembles the runner from the same builder shape as `service.rs:116-157` (or extracts that builder so both production and test share it) and asserts the MODEL_ONLY terminal end to end.

### MEDIUM — `06-13` Task 1 never specifies the extracted packing helper's signature or return contract

The action says only *"Extract the packing decision used by `OpenRouterGenerator::execute_one_call` into a crate-visible helper (same module) so tests can invoke the production packing path without HTTP."* Two things are left open and both matter:

1. **Signature.** `execute_one_call` reads `self.config.evidence_token_budget()` and `self.config.max_completion_tokens()` (`openrouter.rs:482-483`). If the helper takes `&self`, the Task 1 workflow test must construct an `OpenRouterGenerator`, which requires a non-empty API key and builds a `reqwest::Client` (`openrouter.rs:244-261`) — heavy, and awkward inside `workflow_phase5.rs`. If it takes budgets as parameters, the test is trivial. The plan should pick.
2. **Return contract.** `execute_one_call` validates with `&packed_evidence.evidence` (`openrouter.rs:742-745`). On the empty-evidence branch there is no `PackedEvidence`. The plan says to pass `grounding_limits.with_allow_model_only(...)` but never says what evidence slice to validate against. It must be `&[]`, and that choice is load-bearing: it is what makes a model that returns citations on a model-only request fail closed.

### MEDIUM — `run_inline_prompt_generation_remainder` is left behind, re-opening the D-11 production/tracer divergence

`06-10`'s D-11 required parity between the production dispatch gate and the tracer path, and `runner.rs:417-425` / `runner.rs:479-489` both honour `allow_model_only`. But `06-13` adds `allow_model_only` to `GenerationRequest` only in `GenerateAnswerNode` (`generate.rs:102-108`). The tracer remainder builds its own request at `engine/src/workflow/mod.rs:288-296` and would not set it — so on that path OpenRouter would still take the fail-closed branch. `engine/src/workflow/mod.rs` is not in `06-13`'s `files_modified`.

Today this is invisible: `grep -rn "run_inline_prompt_generation_remainder"` shows only `workflow_phase5.rs` callers, all with `FakeGenerator`. But the function is `pub`, not `#[cfg(test)]`, and it already carries a divergent copy of the model-only rule (`mod.rs:311-323`). Leaving one more field out of sync widens a seam the verification report already flagged as drifted.

### MEDIUM — `06-13` changes the outbound JSON schema against D-19's literal text with no decision record

D-19 states *"the JSON schema is untouched. Phase 3 D-28's `response_format`/`json_schema` contract and Phase 05 D-01 both hold."* `06-13` Task 3 edits `schema_json["properties"]["answer_basis"]["enum"]` and argues in `must_haves` that this is *"an enum-member admission of an already published proto value, governed by D-10."*

That reading is defensible — D-19 constrains the *D-17 prompt change*, and the schema in question is the request Lancet sends to OpenRouter, not Lancet's own published API. But the plan resolves a conflict between two locked decisions in its own frontmatter, with no `checkpoint:decision`, no `<reversibility>` element on Task 3, and no CONTEXT/ROADMAP amendment. Given `06-07` gated a comparable one-way vocabulary choice behind an explicit checkpoint, the asymmetry is worth closing — even if only by recording the disposition.

### MEDIUM — The systemic cause of both failures is unaddressed

`grep -c "GenerateAnswerNode::new(" engine/src/tests/workflow_phase5.rs` → **34**; nine of those are bare single-line constructions with no `.with_settings(...)`. Production always sets both settings and repair (`service.rs:147-157`). Similarly, all eight shipped repair tests use one distinct marker per answer, which is why the SC5 duplicate defect was invisible.

Both gap plans fix their specific instance. Neither adds a guard — a shared test constructor mirroring `build_production_workflow`, or a grep-based assertion that node-level generation tests carry `.with_settings` — so the next behavior plan can reproduce the same "green suite, bypassed production" failure.

### LOW — `06-14` Task 2's dedupe touches a public function shared with the fail-closed branch

`resolve_citations_with_max_chars` (`prompt.rs:576-614`) is used by both the repair-enabled branch (`generate.rs:282-288`) and the repair-*disabled* branch (`generate.rs:330-336`), where its output length is compared strictly against `ctx.citations.len()` (`generate.rs:337-348`). De-duplicating could in principle shorten the result and trip that check — e.g. `cited_evidence_ids = ["[1]", "<chunk_id of block [1]>"]`, which `prompt.rs:591` resolves to the same block twice.

In practice this is unreachable, because `validate_grounding_with_limits` rejects the chunk-id form first (`generation/mod.rs:331-341`, `known_ids` is built from `e.id`), and the length check only runs when `grounding_limits.is_some()`. But the plan does not state that reasoning, so an executor has no basis to be confident the change is safe.

### LOW — `06-13`'s canned `ModelOutput` must be marker-free, and the plan does not say so

The model-only branch still validates (`generate.rs:149-163`), and `validate_grounding_with_limits` enforces set equality between `cited_evidence_ids` and inline markers extracted from the answer (`generation/mod.rs:343-365`). With `cited_evidence_ids: vec![]`, the canned answer must contain no `[N]` marker or the test fails for an unrelated reason.

### LOW — `06-13` Task 1 (`type="tracer"`) has a forward dependency on Task 2

The action concedes it: *"Task 2 may land the dedicated policy in the same commit if needed for the tracer to compile."* Tracer-first exists so the first task proves the spine independently. A cleaner ordering is: land `model_only_system_policy` first (a two-line pure addition), then the tracer.

### LOW — ROADMAP summary-table rows 1–3 are malformed

`.planning/ROADMAP.md:7-9` put plan counts and dates in the `Phase` / `Goal` / `Requirements` columns:

```
| 1 | 1/1 | Complete    | 2026-07-13 |
| 2 | 28/28 | Complete (ADR-02-004 deferral to Phase 6) | 2026-07-30 |
```

D-78 item 2 required the whole table to change coherently. Phase 6.4 owns roadmap reconciliation (D-04/D-86), so this is a carry-forward rather than a blocker — but it should be an explicit 6.4 item, not an accident.

---

## 4. Suggestions

1. **Make the named-test gates fail-closed.** Prepend `cargo test --lib ... -- --list | grep -qF '<name>'` to every name-filtered verify in both gap plans. Cheapest possible fix for the highest-severity finding.
2. **Add one production-shaped SC3 test.** Either extract `build_production_workflow`'s node-assembly into a helper both `service.rs` and the tests call, or add a single test that mirrors `service.rs:116-157` exactly and asserts the MODEL_ONLY terminal from `run_workflow`. Without it, SC3's closure rests on two tests that meet nowhere.
3. **Pin the packing helper's shape in `06-13` Task 1.** Specify a free function taking `(question, evidence, graph_facts, graph_weight, evidence_budget, max_output_tokens, allow_model_only, cancel)` returning the messages *and* the evidence slice used for validation. State that the empty branch validates against `&[]`.
4. **Add `engine/src/workflow/mod.rs` to `06-13`'s scope** for the one-line `req.allow_model_only = ctx.allow_model_only` in `run_inline_prompt_generation_remainder`, or explicitly record the divergence as accepted with a named follow-up.
5. **Record the D-19 vs D-10 schema disposition.** A `<reversibility>` element on `06-13` Task 3 plus a line in `06-CONTEXT.md` or the SUMMARY closes it without a checkpoint.
6. **Add a `06-14` note explaining why the shared-resolver dedupe is safe** (validation rejects unknown ids first; the strict length check only runs with `grounding_limits`).
7. **Schedule the systemic guard.** A small `#[cfg(test)]` constructor mirroring production wiring, plus a grep assertion in the gate script that no generation-behavior test builds `GenerateAnswerNode::new(` without `.with_settings`, would prevent recurrence for the remaining sub-phases (6.1–6.4), all of which add engine behavior.
8. **File the ROADMAP table corruption as an explicit Phase 6.4 task** under D-78/D-04.

---

## 5. Risk Assessment

**MEDIUM.**

Downward pressure: both gap plans correctly diagnose real, verified defects; the fixes are minimal and correct; regression pins are named and real; scope is narrow (`06-13` touches 7 files, `06-14` touches 4); no new dependencies; both gates are green today; and the reversibility profile is genuinely low — the request flag and packing branch are additive and the flag-off path is pinned by an existing passing test.

Upward pressure: the verification gates for both plans are demonstrably not fail-closed, so "all tasks green" carries less information than it appears to; SC3's closure after `06-13` still leaves a seam between the node-level and adapter-level proofs that the same verification standard could reject; and the systemic cause of both Phase 6 failures — tests that construct workflow nodes differently from production — remains in place across 34 construction sites, with four more sub-phases of behavior work queued behind it.

Neither gap plan is likely to break shipped behavior. The realistic failure mode is that they land, the gates pass, and re-verification still returns `gaps_found` on SC3 — costing another cycle rather than causing a regression.

---
