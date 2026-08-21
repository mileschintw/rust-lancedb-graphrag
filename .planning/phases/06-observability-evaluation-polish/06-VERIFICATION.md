---
phase: 06-observability-evaluation-polish
verified: 2026-08-21T11:40:00Z
status: gaps_found
score: 5/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "SC3 — When both retrieval paths fail or evidence is absent and the caller has opted in (default off), the workflow returns answer_basis = MODEL_ONLY with an explicit notice and zero citations; with the flag off, today's fail-closed behavior is unchanged (D-10, D-11, D-12)."
    status: failed
    reason: >-
      The opt-in half cannot produce an answer on the production path. AssemblePromptNode
      writes pack_model_only_prompt(..) into ctx.assembled_prompt, but nothing on the
      generation path reads that field; GenerateAnswerNode builds a fresh GenerationRequest
      from (original_query, evidence_blocks) and OpenRouterGenerator::execute_one_call then
      unconditionally calls pack_evidence_and_graph_prompt, which returns EmptyEvidence on an
      empty evidence slice. The error maps to GenerationErrorKind::InvalidRequest, which is not
      in the retryable set, so the run terminates as NODE_ERROR_KIND_LLM_GENERATION_FAILED
      before the model is contacted. The flag-OFF half of SC3 is verified and unchanged.
    artifacts:
      - path: "engine/src/workflow/nodes/generate.rs"
        issue: "Lines 102-103 build GenerationRequest::new(ctx.original_query, ctx.evidence_blocks); ctx.assembled_prompt is never passed to the generator."
      - path: "engine/src/generation/openrouter.rs"
        issue: "execute_one_call (l.477-495) calls pack_evidence_and_graph_prompt with no empty-evidence branch; the outbound JSON schema (l.521-524) pins answer_basis to [\"retrieval\", \"mixed\"], so a structured-output provider cannot return model_only."
      - path: "engine/src/prompt.rs"
        issue: "pack_evidence_and_graph_prompt returns PromptAssemblyError::EmptyEvidence at l.338-340 (pinned by a passing shipped test). pack_model_only_prompt (l.215-217) reuses base_system_policy(), which instructs the model to answer using ONLY the provided evidence blocks and to cite numbered markers — contradicting the mode."
      - path: "engine/src/workflow/nodes/assemble_prompt.rs"
        issue: "Line 77 writes ctx.assembled_prompt on the model-only branch; the only non-test consumers of that field are workflow/mod.rs:266 (test-only inline remainder) and workflow/events.rs:229 (checkpoint serializer)."
      - path: "engine/src/tests/workflow_phase5.rs"
        issue: "The covering test model_only_opt_in_true_zero_evidence_runs_generation_and_emits_notice (l.5160-5200) constructs GenerateAnswerNode::new(Some(fake_gen)) with no .with_settings(..), leaving grounding_limits: None, and uses FakeGenerator, which never touches pack_evidence_and_graph_prompt or the JSON schema. Production always sets both (service.rs:148-157, main.rs:96)."
    missing:
      - "An empty-evidence branch in OpenRouterGenerator::execute_one_call that uses pack_model_only_prompt instead of pack_evidence_and_graph_prompt (or threading ctx.assembled_prompt through GenerationRequest so AssemblePromptNode's output is load-bearing)."
      - "\"model_only\" admitted to the outbound answer_basis JSON schema enum at openrouter.rs:521-524."
      - "A model-only system policy that does not instruct the model to cite evidence blocks that do not exist."
      - "A test driving GenerateAnswerNode WITH .with_settings(limits, ..) against a generator that actually calls pack_evidence_and_graph_prompt on empty evidence."
  - truth: "SC5 — Citation repair (DEBT-RAG-03) normalizes near-miss markers locally, strips anything still unresolved, emits CITATION_REPAIRED/CITATION_DROPPED, and downgrades the basis if all grounding is lost — no second provider call (D-14)."
    status: partial
    reason: >-
      The mechanism exists and the no-second-provider-call clause is pinned by a test, but the
      repair pass converts its own target case into a hard run failure. repaired_citations is
      built one entry per extracted marker OCCURRENCE (citations::extract_markers pushes per
      occurrence with no dedup; citations::resolve_markers is a 1:1 .map), and that list is
      handed to validate_grounding_with_limits, which rejects duplicate IDs
      (generation/mod.rs:320-329). Two reproductions: (1) repeated marker — answer "…[1]…[1]…"
      with evidence ["[1]"] yields two Unchanged("[1]") → duplicate → LlmGenerationFailed;
      (2) mixed spellings — "[ 7 ]" and "[7]" with evidence ["[7]"] yields Repaired("[7]") +
      Unchanged("[7]") → same failure. Case (2) is exactly what the widened extractor
      (citations.rs:82-118) was added to normalize. This is a regression against the
      repair-disabled path, which compares inline markers as a HashSet (mod.rs:344-357) and
      tolerates a repeated marker.
    artifacts:
      - path: "engine/src/workflow/nodes/generate.rs"
        issue: "Lines 185-231 push one repaired_citations entry per marker occurrence with no de-duplication before validation."
      - path: "engine/src/generation/citations.rs"
        issue: "extract_markers (l.82-118) emits one ExtractedMarker per occurrence; resolve_markers (l.171-198) maps 1:1. Neither de-duplicates by resolved evidence id."
      - path: "engine/src/prompt.rs"
        issue: "resolve_citations_with_max_chars (l.576-614) also does not de-duplicate, so a downstream-only fix would produce duplicate StructuredCitation entries on the wire instead of a failure."
      - path: "engine/src/tests/workflow_phase5.rs"
        issue: "All eight repair tests (l.5807-6130) use a single distinct marker per answer. No test exercises a repeated marker or a mixed-spelling pair, so the regression is invisible to the green suite."
    missing:
      - "De-duplication at construction in generate.rs, preserving first-occurrence order, while keeping the per-occurrence span-edit and notice logic unchanged."
      - "A repair test whose answer repeats the same marker, and one that mixes [ 7 ] with [7] against evidence [\"[7]\"]."
deferred:
  - truth: "WorkflowMetadata / degraded_mode is populated by the engine on the terminal WorkflowCompletedEvent."
    addressed_in: "Phase 6.2"
    evidence: "Phase 6.2 success criterion 8: 'Phase 05 D-30's workflow metadata lands both as span attributes and as additive WorkflowCompletedEvent protobuf fields (D-41).'"
  - truth: "gateway/internal/telemetry performs real telemetry setup (Init() called from main.go)."
    addressed_in: "Phase 6.2"
    evidence: "Phase 6.2 goal: 'Ship production-grade OTel traces, metrics and logs across Go and Rust…'; the package doc string and 06-04-PLAN both name it a reserved compiling stub for Phase 6.2 (D-36/D-38/D-43)."
human_verification:
  - test: "Adjudicate plan 06-12's flagged prohibition: 'MUST NOT treat the unclassified RAG-03 probe edge as covered or auto-resolved. No 06-SPEC.md exists; the edge remains unresolved pending manual review at phase verification.'"
    expected: "An explicit owner decision recorded — either the probe edge is accepted as out of scope for Phase 06, or a follow-up item is filed. It must not be silently absorbed into a pass."
    why_human: "The prohibition carries status: flagged-unverified with verification: manual and names phase verification as its resolution point. There is no 06-SPEC.md to check it against, so no programmatic evidence can resolve it."
  - test: "Decide whether the citation total-drop relaxation (generate.rs:233-266, `let effective_allow = ctx.allow_model_only || total_drop`) is the intended contract."
    expected: "Either (a) the total-drop route also emits NoticeCode::ModelOnly so a client filtering on typed_code == NOTICE_CODE_MODEL_ONLY cannot miss an ungrounded answer, or (b) the relaxation is documented as a separate, explicitly named configuration key rather than an implicit override of allow_model_only_answers, or (c) the current behavior is accepted in writing."
    why_human: "The disjunction is deliberate and commented as such, but it means an operator with allow_model_only_answers = false and a caller sending allow_model_only: false still receive a MODEL_ONLY answer whenever every marker is unresolvable — while plan 06-10's own prohibition states a model-only answer 'must never be returned without its notice'. Whether that is a defect or an accepted trade-off is a design judgment, not a code fact."
---

# Phase 6: Observability, Evaluation & Polish — Verification Report

**Phase Goal:** Rust + Go module-graph restructure, consolidated additive wire-contract change, and RAG-03 degraded-mode hardening (model-only answers, citation repair, bad-input matrix, graph-unavailable notice)
**Verified:** 2026-08-21
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP Success Criterion) | Status | Evidence |
|---|---|---|---|
| 1 | Rust binary imports all production modules from the library crate; dual `lib.rs`/`main.rs` declaration ends; Go `main.go` symmetrically split into packages | ✓ VERIFIED | `engine/src/lib.rs` declares all 12 production modules (`chunker`, `client`, `config`, `db`, `generation`, `graph`, `ingest`, `pb`, `prompt`, `rerank`, `retrieval`, `service`, `workflow`). `engine/src/main.rs` contains **zero** `mod` declarations and reaches every relocated item by `use engine::…` (l.7-16). Gateway has `internal/config`, `internal/sse`, `internal/engineclient`, `internal/telemetry`; `main.go` calls `config.Load()` (l.723), `engineclient.New`/`engineclient.Engine` (l.162, 754), `sse.WriteStreamError`/`sse.WriteWorkflowEvent` (l.613, 619, 651), and contains **zero** inline SSE frame writes. Landed as plans 06-01/06-02/06-03 (waves 1-3) and 06-04/06-05 (waves 1-2), i.e. first. |
| 2 | One consolidated additive protobuf change (model-only flag, graph-ablation flag, `WorkflowCompletedEvent` metadata fields, typed notice-code enum) with regenerated Rust and Go bindings, before any behavior plan | ✓ VERIFIED | `proto/lancet/v1/lancet.proto`: `optional bool allow_model_only = 4` (l.61), `optional bool disable_graph_context = 5` (l.66), `NoticeCode typed_code = 4` (l.119), `message WorkflowMetadata` (l.231), `WorkflowMetadata metadata = 7` (l.252), `enum NoticeCode` values 0-5 and 10-22 with tag 17 reserved. Additive only — no tag renumbered or reused. Bindings agree: `engine/src/pb/lancet/v1/lancet.v1.rs:330-390` and `gateway/proto/lancet/v1/lancet.pb.go:40-44, 693-762, 1745`. Landed in plan 06-07 (wave 5); every behavior plan is wave 6-10. See WARNINGS — the contract landed, population did not (deferred to Phase 6.2 SC8). |
| 3 | Both paths fail / evidence absent + caller opted in (default off) → `answer_basis = MODEL_ONLY`, explicit notice, zero citations; flag off → fail-closed unchanged | ✗ FAILED | **Flag-off half verified.** `git show 0c96720:engine/src/workflow/runner.rs` shows the zero-evidence `break` already existed pre-phase; Phase 6 only added the `!ctx.allow_model_only &&` guard, so flag-off behavior is genuinely unchanged. **Opt-in half fails on the production path** — see gaps. Chain: `runner.rs:417-425` correctly does NOT break when `allow_model_only` is true, so generation IS reached; `generate.rs:102-103` discards `ctx.assembled_prompt`; `openrouter.rs:477-495` unconditionally packs evidence; `prompt.rs:338-340` returns `EmptyEvidence`. Production wires the real adapter with limits (`service.rs:148-157`, `main.rs:96`); the covering test uses neither. |
| 4 | One retrieval path failing keeps `answer_basis = RETRIEVAL` with a machine-readable notice naming the failed path | ✓ VERIFIED | `retrieve.rs:88` emits `NoticeCode::RetrievalDegradedDense`, `retrieve.rs:141` emits `RetrievalDegradedBm25` — the failed path is named by the typed code, message carries the failure kind. Behavioral evidence: `retrieval_degraded_dense_returns_grounded_answer_from_surviving_lexical` asserts `answer_basis == Retrieval`, non-empty structured citations from the surviving lexical path, exactly one dense degrade notice, and no `NodeFailed` event — **run, passed**. 16 further `retrieval_degraded_*` tests cover per-variant tolerance, de-duplication and ordering. |
| 5 | Citation repair normalizes near-miss markers locally, strips unresolved, emits `CITATION_REPAIRED`/`CITATION_DROPPED`, downgrades basis if all grounding lost — no second provider call | ✗ FAILED (gap status: `partial`) | Mechanism present and the "no second provider call" clause is pinned (`citation_repair_makes_no_additional_provider_call`, l.5965). But the repair pass hard-fails any answer whose markers resolve to the same evidence id twice — including the mixed-spelling `[ 7 ]` + `[7]` case the widened extractor exists to normalize. See gaps for the traced reproduction. |
| 6 | Bad-input matrix is an enumerated, table-driven test (gRPC and HTTP) covering malformed query/session/document IDs, content type and filter bounds, all rejecting before retrieval or provider work with stable HTTP 400 / gRPC `InvalidArgument` | ✓ VERIFIED | gRPC: `engine/src/tests/bad_input_matrix.rs` — `struct Row` + `rows: Vec<Row>` driven by one loop; rows cover `empty_query`, `whitespace_only_query`, `query_too_long`, `malformed_session_id`, `wrong_version_session_id`, `invalid_document_id`, `unsupported_content_type`, `empty_filter_value`, `filter_limit_exceeded` (×2), plus two recorded non-rejection dispositions. Asserts `tonic::Code::InvalidArgument` + the `x-lancet-error-kind` trailer per row, and `fake_gen.calls() == 0` across the whole table — that is the "before provider work" proof. HTTP: `gateway/main_test.go:1415 TestBadInputMatrixHTTP` — `rows []badInputMatrixRow` with matching names, each asserting `http.StatusBadRequest` and the error-kind header. Scope note: the HTTP rows drive **stubbed engine statuses** — by design the gateway performs no field-level validation of its own, documented at `main_test.go:1408-1414` — so what each HTTP row proves is the gRPC-status → HTTP-status derivation, and the "rejects before retrieval or provider work" property is proven on the gRPC side by `fake_gen.calls() == 0`, not independently on the HTTP surface. SC6 stays VERIFIED on the plain reading of its text. Behavioral evidence: `bad_input_matrix_rejects_and_dispositions_are_stable` **run, passed**. |
| 7 | `GRAPH_UNAVAILABLE` fires on the two silent-degrade paths (empty-result, absent `graph_port`) that don't already emit `GRAPH_TIMEOUT`/`GRAPH_DEGRADED`; source-chunk queries proven never to require graph data | ✓ VERIFIED | `graph_context.rs:126-132` (empty-result) and `graph_context.rs:172-178` (absent port) emit distinct `NoticeCode::GraphUnavailable` notices. The timeout/degraded branch (l.150-168) is untouched and still emits `GraphTimeout`/`GraphDegraded`. Proof clause: `run_source_chunk_proof_pipeline` (l.4157) plus four tests — `source_chunk_query_succeeds_when_graph_{empty,absent,failing,ablated}`. Behavioral evidence: `source_chunk_query_succeeds_when_graph_absent` and `graph_unavailable_notice_on_empty_result` **run, passed**. |

**Score:** 5/7 truths verified (0 present, behavior-unverified)

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|---|---|---|
| 1 | `WorkflowMetadata` / `degraded_mode` populated by the engine | Phase 6.2 | SC8: "Phase 05 D-30's workflow metadata lands both as span attributes and as additive `WorkflowCompletedEvent` protobuf fields (D-41)." |
| 2 | `internal/telemetry` performs real setup | Phase 6.2 | Phase 6.2 goal (OTel across Go and Rust). Package doc and 06-04-PLAN both name it a reserved compiling stub. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `engine/src/lib.rs` | Single production module declaration root | ✓ VERIFIED | 12 `pub mod` declarations + `extern crate self as engine`. No re-export aliases beyond the `LancetService` trait. |
| `engine/src/main.rs` | Startup wiring only, imports by path | ✓ VERIFIED | Zero `mod` declarations; imports `engine::{client, config, db, generation, graph, ingest, pb, rerank, retrieval, service}`. M-SINGLE-ITEM-PATH holds. |
| `engine/src/service.rs`, `engine/src/ingest.rs` | Library-owned gRPC service and ingestion pipeline | ✓ VERIFIED | Declared from `lib.rs`; `main.rs` reaches both by import. |
| `gateway/internal/config/config.go` | Config loading extracted | ✓ VERIFIED | `config.Load()` called from `main.go:723`. Viper prefix `LANCET` with `"." -> "__"` replacer. |
| `gateway/internal/sse/sse.go` | SSE handling extracted | ✓ VERIFIED | `WriteStreamError`/`WriteWorkflowEvent` are the only frame writers; `main.go` has zero inline SSE writes. |
| `gateway/internal/engineclient/engineclient.go` | Engine client extracted | ✓ VERIFIED | `engineclient.Engine` is the app's engine field type; `engineclient.New(...)` at `main.go:754`. |
| `gateway/internal/telemetry/telemetry.go` | Telemetry package seam | ⚠️ ORPHANED (intentional) | 8-line stub. `Init()` is never called; `main.go:36` blank-imports the package. Explicitly a reserved Phase 6.2 stub per its own doc comment, 06-04-PLAN and the ROADMAP plan line. Deferred, not a gap. |
| `proto/lancet/v1/lancet.proto` | Consolidated additive change | ✓ VERIFIED | All four items present, additive, tag 17 reserved. |
| `engine/src/pb/lancet/v1/lancet.v1.rs` | Regenerated Rust bindings | ✓ VERIFIED | Enum values, `WorkflowMetadata`, `metadata: Option<WorkflowMetadata>` all match the source. |
| `gateway/proto/lancet/v1/lancet.pb.go` | Regenerated Go bindings | ✓ VERIFIED | Presence-preserving `*bool` for both request flags; `WorkflowMetadata` struct present. |
| `engine/src/workflow/nodes/graph_context.rs` | Notices on the two silent paths + ablation early return | ✓ VERIFIED | Three notice sites: `GraphAblation`, and `GraphUnavailable` ×2. |
| `engine/src/workflow/nodes/retrieve.rs` | Per-path degrade notices | ✓ VERIFIED | `RetrievalDegradedDense` and `RetrievalDegradedBm25` with failure-kind-derived messages. |
| `engine/src/generation/citations.rs` | Local normalize/resolve, no invention | ✓ VERIFIED (substantive) | NFKC + case-fold + whitespace collapse + marker-syntax strip; a marker matching zero or >1 evidence id is `Dropped`, never assigned. Network-free. |
| `engine/src/tests/bad_input_matrix.rs` | Table-driven gRPC matrix | ✓ VERIFIED | 345 lines, one `struct Row` table, one loop, generator-call assertion. |
| `gateway/main_test.go` (`TestBadInputMatrixHTTP`) | Table-driven HTTP matrix | ✓ VERIFIED | Row struct + slice, status 400 + error-kind header per row. |
| `engine/src/prompt.rs` (`pack_model_only_prompt`) | Model-only prompt helper | ⚠️ ORPHANED | Exists and is called from `assemble_prompt.rs:77`, but its output never reaches a provider — see gap SC3. |
| `engine/src/workflow/events.rs` (`WorkflowMetadata`) | Terminal metadata | ⚠️ HOLLOW | `metadata: None` hardcoded at l.372; `WorkflowMetadata` appears nowhere in the engine outside generated code. Deferred to Phase 6.2. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `engine/src/main.rs` | `engine/src/service.rs` | `use engine::service` | ✓ WIRED | `main.rs:16` |
| `engine/src/main.rs` | `engine/src/config.rs` | `use engine::config::{load_settings, EffectiveRagSettings}` | ✓ WIRED | `main.rs:8` |
| `gateway/main.go` | `internal/sse` | `sse.WriteWorkflowEvent` | ✓ WIRED | `main.go:651`, plus 613/619 |
| `gateway/main.go` | `internal/engineclient` | `engineclient.New(...)` | ✓ WIRED | `main.go:754` |
| `gateway/main.go` | `internal/config` | `config.Load()` | ✓ WIRED | `main.go:723` |
| `gateway/main.go` | `internal/telemetry` | blank import | ✗ NOT_WIRED | `Init()` never called. Intentional stub — deferred to Phase 6.2. |
| `QueryRAGRequest.allow_model_only` | `WorkflowContext.allow_model_only` | `service.rs:824` request → config → false | ✓ WIRED | Presence-preserving `Option<bool>`; default `false` in `config.rs:140-142` and `config/config.toml`. |
| `QueryRAGRequest.disable_graph_context` | `WorkflowContext.disable_graph_context` | `workflow/mod.rs:114` | ✓ WIRED | Note: `service.rs:764` binds a dead `let _disable_graph_context`; the live path is `WorkflowContext::new`. See WR-03 below. |
| `AssemblePromptNode` (`ctx.assembled_prompt`) | `GenerateAnswerNode` / provider adapter | intended prompt handoff | ✗ NOT_WIRED | **Root cause of gap SC3.** Only non-test consumers of `ctx.assembled_prompt` are `workflow/mod.rs:266` (test-only remainder) and `workflow/events.rs:229` (checkpoint serializer). |
| `WorkflowRunner::emit_terminal_once` | `WorkflowCompletedEvent.metadata` | derivation from notice set | ✗ NOT_WIRED | `events.rs:372` hardcodes `metadata: None`. Deferred to Phase 6.2 SC8. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `sse.WriteWorkflowEvent` | `metaMap["degraded_mode"]` | `e.WorkflowCompleted.GetMetadata()`, else a zero-filled literal | ✗ (engine always sends `nil`) | ⚠️ STATIC — the `else` branch at `sse.go:123-135` always fires, so every run publishes `"degraded_mode": false`, including runs carrying `RETRIEVAL_DEGRADED_*`, `GRAPH_UNAVAILABLE` or `NO_EVIDENCE`. |
| `resp.notices` | `ctx.notices` | typed notice constructor at each degrade site | ✓ | ✓ FLOWING — asserted end-to-end by the degrade and graph tests. |
| `resp.structured_citations` | `ctx.structured_citations` | resolved against `ctx.evidence_blocks` | ✓ | ✓ FLOWING — `resp.structured_citations[0].chunk_id == "chk-lex-1"` asserted from a real surviving retrieval path. |
| `resp.answer_basis` | `ctx.answer_basis` | model output + reconciliation | ✓ (retrieval/mixed paths) | ✓ FLOWING for SC4; ✗ unreachable for `MODEL_ONLY` via the opt-in (gap SC3). |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Source-chunk query succeeds with no graph port (SC7) | `cargo test --lib source_chunk_query_succeeds_when_graph_absent` | 1 passed | ✓ PASS |
| `GRAPH_UNAVAILABLE` on empty graph result (SC7) | `cargo test --lib graph_unavailable_notice_on_empty_result` | 1 passed | ✓ PASS |
| Dense-path failure keeps `answer_basis = RETRIEVAL` + names the failed path (SC4) | `cargo test --lib retrieval_degraded_dense_returns_grounded_answer_from_surviving_lexical` | 1 passed | ✓ PASS |
| Bad-input matrix rejects before provider work (SC6) | `cargo test --lib bad_input_matrix_rejects_and_dispositions_are_stable` | 1 passed | ✓ PASS |
| Empty evidence rejects prompt assembly — the crux of gap SC3 | `cargo test --lib pack_evidence_and_graph_prompt_empty_evidence_still_errors_regardless_of_graph_facts` | 1 passed (asserts `Err(EmptyEvidence)`) | ✓ PASS — corroborates the SC3 failure chain behaviorally, not just statically |
| Model-only opt-in against the real adapter with grounding limits | — | No such test exists | ? SKIP — that absence **is** the finding (gap SC3) |

Full regression gate (established input, not re-run): `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)` exits 0 — 372 Rust passed / 0 failed / 1 ignored; all Go packages ok.

### Probe Execution

| Probe | Command | Result | Status |
|---|---|---|---|
| — | `find scripts -path '*/tests/probe-*.sh'` | no matches; no PLAN or SUMMARY declares a probe path | N/A — no probes declared for this phase |

Note: plan 06-12 carries a `specless-probe` prohibition (`status: flagged-unverified`, `verification: manual`) that names phase verification as its resolution point. It is routed to human verification below, not silently absorbed.

### Requirements Coverage

RAG-03 is deliberately split across phases. REQUIREMENTS.md traceability records: DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-05, DEBT-RAG-06 → Phase 06; DEBT-RAG-04 → Phase 06.1. Phase 06.1 has not executed.

| Requirement / clause | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| RAG-03 · DEBT-RAG-01 (degraded mode) | 06-09, 06-10 | Per-path retrieval degrade + model-only opt-in | ⚠️ PARTIAL | Retrieval degrade SATISFIED (SC4 verified). Model-only opt-in **BLOCKED** — cannot produce an answer on the production path (gap SC3). |
| RAG-03 · DEBT-RAG-03 (citation repair) | 06-11 | Normalize-then-strip, notices, basis downgrade | ✗ BLOCKED | Mechanism present but regresses on repeated / mixed-spelling markers (gap SC5). |
| RAG-03 · DEBT-RAG-05 (bad-input matrix) | 06-12 | Enumerated table-driven matrix, gRPC + HTTP | ✓ SATISFIED | SC6 verified with a passing behavioral run. |
| RAG-03 · DEBT-RAG-06 (graph-unavailable) | 06-08 | Notices on the two silent-degrade paths + source-chunk proof | ✓ SATISFIED | SC7 verified with two passing behavioral runs. |
| RAG-03 · DEBT-RAG-04 (index rebuild-and-swap) | — | Not claimed by any Phase 06 plan | ⏭ OUT OF SCOPE | Assigned to Phase 06.1 (ROADMAP Phase 6.1 SC1-4). |
| DEBT-P3-MODULE-GRAPH (D-80) | 06-01, 06-02, 06-03, 06-04, 06-05 | Module-graph restructure exception | ✓ SATISFIED | SC1 verified. |

**RAG-03 checkbox:** correctly remains `- [ ]` in `.planning/REQUIREMENTS.md:52`. Independently confirmed by reading the file. Plan 06-12's executor reverted a premature `requirements.mark-complete RAG-03` after `requirements.ready-ids` mis-reported it ready (a same-phase-only signal with no visibility into the cross-phase split). That revert was correct and is verified in the file. **This verification does not mark RAG-03 complete** — two of its four Phase-06 clauses are blocked, and DEBT-RAG-04 remains Phase 06.1's work.

**Orphaned requirements:** none. REQUIREMENTS.md maps only RAG-03 to Phase 06, and all 12 plans declare it.

### Prohibitions Disposition

Four plans declare `must_haves.prohibitions`. Each is dispositioned here; none is silently absorbed.

| Plan | Prohibition (abridged) | Declared | Verification tier | Disposition |
|---|---|---|---|---|
| 06-08 | MUST NOT return a degraded answer a client cannot distinguish from a healthy one — every path that silently empties the graph context must carry a machine-readable notice naming which happened | `resolved` | test | ✓ **UPHELD.** All three empty-graph paths emit a distinct typed notice: `GraphAblation` (`graph_context.rs:100`), `GraphUnavailable` on empty result (l.126-132) and on absent port (l.172-178); timeout/degraded branch unchanged. Enforcement evidence wired and passing (`graph_unavailable_notice_on_empty_result` run, passed; `graph_unavailable_distinct_messages_survive_deduplication`, `graph_ablation_does_not_emit_graph_unavailability_notice`). |
| 06-10 | MUST NOT allow a model-only answer to be presentable as a grounded one — never a retrieval/mixed basis, never citations, **never returned without its notice** | `resolved` | test | ⚠️ **CONTESTED — routed to human item #2.** The opt-in route upholds it (`generate.rs:166-170` emits `NoticeCode::ModelOnly`, clears `structured_citations`, calls `into_model_only()`) — though that route is unreachable in production for a separate reason (gap SC3). The **total-drop route** reaches the same client-visible `answer_basis = MODEL_ONLY` and emits `CITATION_DROPPED` + `BASIS_RECONCILED` but **not** `MODEL_ONLY`. Whether those notices satisfy "its notice" in spirit is genuinely arguable; the current behavior is pinned by `citation_repair_enabled_drops_unresolvable_marker_and_emits_notice` (l.5845), so changing it means changing a shipped test. Not marked green. |
| 06-11 | MUST NOT invent, substitute or guess a citation target — a marker matching nothing, or more than one, is dropped and disclosed, never assigned to a plausible candidate | `resolved` | test | ✓ **UPHELD.** `citations::resolve_markers` (l.171-198) resolves only by symmetric `normalize()` equality on both sides; `None` candidate → `Dropped`, and a second candidate → `Dropped`. No fuzzy/nearest match exists. Repair never introduces a citation the model did not write. (Note: the *converse* failure — rejecting citations the model legitimately did write twice — is gap SC5.) |
| 06-12 | MUST NOT treat the unclassified RAG-03 probe edge as covered or auto-resolved; no 06-SPEC.md exists, edge unresolved pending manual review at phase verification | `flagged-unverified` | manual | ⚠️ **UNRESOLVED — routed to human item #1.** Declared unverified by the plan itself and names phase verification as its resolution point. Recorded as a human-verification item, never absorbed into a pass. |

### Anti-Patterns Found

Debt-marker gate: `TBD|FIXME|XXX` scanned across `engine/src/`, `gateway/`, `proto/`, `scripts/`, `config/`, `README.md` (excluding generated `pb`/`.pb.go`) — **zero matches**. Gate passes.

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `engine/src/generation/openrouter.rs` | 521-524 | Outbound JSON schema pins `answer_basis` to `["retrieval","mixed"]` while a third basis is a shipped contract value | 🛑 Blocker | A structured-output provider cannot return `model_only`; blocks SC3 even if the `EmptyEvidence` guard is lifted. |
| `engine/src/workflow/nodes/generate.rs` | 185-231 | Per-occurrence list handed to a duplicate-rejecting validator | 🛑 Blocker | Blocks SC5. |
| `engine/src/workflow/events.rs` | 372 | `metadata: None` hardcoded; `WorkflowMetadata` never constructed anywhere in the engine | ⚠️ Warning | Contract field is inert. Population deferred to Phase 6.2 SC8, so not an SC2 failure — but see the gateway half. |
| `gateway/internal/sse/sse.go` | 123-135 | Zero-filling `else` branch converts *absent* metadata into an asserted `"degraded_mode": false` | ⚠️ Warning | Actively wrong on exactly the degraded runs this channel was built for. A consumer cannot distinguish "not degraded" from "engine never told me". Omitting the key when metadata is nil would be honest; `gateway/internal/sse/sse_test.go` asserts nothing on `metadata`. |
| `engine/src/config.rs` | 600 | `Environment::with_prefix("LANCET").separator("__")` without `.prefix_separator("_")` | ⚠️ Warning | **CR-04 conflict resolved: both statements are true simultaneously.** In `config` 0.15.x, `prefix_separator` falls back to `separator`, so the required prefix is `lancet__` and every documented `LANCET_ENGINE__*` variable is skipped by the declarative source. The two passing tests (`model_only_answers_recognizes_true_and_false_env_overrides`, `citation_repair_enabled_recognizes_true_and_false_env_overrides`) pass because those exact keys have **hand-written** override paths at `config.rs:652-674`, separate from the declarative source. The tests pin the allowlist, not the mechanism. Keys outside the allowlist (all of `engine.retrieval.*`, `engine.graph.seed_match_min_score`, `openrouter.temperature`, …) are silently unoverridable. No SC covers env overrides, so this is a warning, not an SC failure. |
| `engine/src/workflow/nodes/generate.rs` | 233-266 | `effective_allow = ctx.allow_model_only \|\| total_drop` | ⚠️ Warning | Both routes to `answer_basis = MODEL_ONLY` reach the same client-visible value, but only the `should_treat_as_model_only` branch emits `NoticeCode::ModelOnly`. Routed to human verification. |
| `engine/src/service.rs` | 763-764 | `let _disable_graph_context = req.disable_graph_context.unwrap_or(false);` with a comment implying it is load-bearing | ℹ️ Info | Dead binding only. The flag genuinely reaches the workflow via `WorkflowContext::new` (`workflow/mod.rs:114`), and SC7's ablation tests pass. Cosmetic. |
| `engine/src/workflow/mod.rs` | 249-363 | `run_inline_prompt_generation_remainder` is `pub` (not `#[cfg(test)]`), skips grounding validation and carries a divergent copy of the model-only rule | ⚠️ Warning | A published fail-open generation seam that has already drifted from `GenerateAnswerNode`. Only tests call it today. |
| `engine/src/workflow/runner.rs` | 417-425 + `workflow/mod.rs:150-160` | Successful zero-evidence responses serialize `ANSWER_BASIS_UNSPECIFIED` (enum `0`) inside `success: true` | ℹ️ Info | **Pre-existing, not introduced by Phase 6.** `git show 0c96720:engine/src/workflow/runner.rs:426-432` shows the same `break` before the phase; Phase 6 only added the `!ctx.allow_model_only &&` guard. SC3's "flag off, unchanged" clause therefore holds. |

### Human Verification Required

#### 1. Adjudicate plan 06-12's flagged prohibition (specless probe edge)

**Test:** Read plan 06-12's prohibition — *"MUST NOT treat the unclassified RAG-03 probe edge as covered or auto-resolved. No 06-SPEC.md exists; the edge remains unresolved pending manual review at phase verification."* (`status: flagged-unverified`, `verification: manual`).
**Expected:** An explicit owner decision recorded — the edge is either accepted as out of scope for Phase 06, or a follow-up item is filed. It must not be absorbed silently into a pass.
**Why human:** The prohibition names phase verification as its resolution point and there is no 06-SPEC.md to check against. No programmatic evidence can resolve it.

#### 2. Decide whether the citation total-drop relaxation is the intended contract

**Test:** Review `engine/src/workflow/nodes/generate.rs:233-266`, specifically `let effective_allow = ctx.allow_model_only || total_drop;`, against plan 06-10's prohibition ("a model-only answer … must never be returned without its notice") and `config.rs:164-169` ("Whether model-only answers are allowed … Defaults to false").
**Expected:** One of — (a) the total-drop route also emits `NoticeCode::ModelOnly`; (b) the relaxation becomes a separate, explicitly named configuration key; or (c) the current behavior is accepted in writing.
**Why human:** The disjunction is deliberate and commented as such. Whether an operator's `allow_model_only_answers = false` (and a caller's explicit `allow_model_only: false`) should still yield a `MODEL_ONLY` answer when every marker is unresolvable is a design judgment, not a code fact. Note that `citation_repair_enabled_drops_unresolvable_marker_and_emits_notice` (l.5845) pins the current behavior with `ctx.allow_model_only == false`, so changing it means changing a shipped test.

### Recorded Provenance (noted, taken at face value)

`06-04-SUMMARY.md` carries a **Closure Ledger** recording four plan-06-04 acceptance criteria that no longer hold as written. Two were mechanically false but substantively correct (the `stream_error` literal gate, and the "redistribution" wording). Two were judgment calls **escalated rather than self-certified and recorded as accepted by the project owner on 2026-08-20**: raising the Go test invariant 67 → 75 (67 retained as `RELOCATION_BASELINE`), and superseding Task 2's "exactly once" grep with the correct count of 2. The same summary records one regression found and fixed post-execution (REG-06-04-01, a truncated fail-closed operator hint) and three closed gaps. This verification takes that provenance at face value and notes it; none of it bears on the seven success criteria.

### Gaps Summary

The phase's structural and observability work is real and holds up under adversarial reading. The module-graph restructure (SC1) is complete on both sides with only the deliberately-reserved telemetry stub unwired. The consolidated protobuf change (SC2) is genuinely additive, correctly ordered before every behavior plan, and both binding trees agree with the source on every tag and enum value. Three of the four degraded-mode behaviors — per-path retrieval degrade (SC4), the bad-input matrix (SC6), and the graph-unavailable notice with its source-chunk proof (SC7) — are wired, data-flowing, and each backed by a named test that I ran and watched pass.

Two of the seven criteria do not hold, and both failures are invisible to the 372-test green suite because the tests that cover them do not exercise the production path.

**SC3 is the load-bearing failure.** The model-only opt-in — the phase's headline user-facing outcome — cannot produce an answer in production. `AssemblePromptNode` builds a model-only prompt that nothing on the generation path reads; `GenerateAnswerNode` constructs a fresh request from raw query + empty evidence; and `OpenRouterGenerator` then unconditionally calls `pack_evidence_and_graph_prompt`, which rejects an empty evidence slice — a rejection pinned by a shipped, passing test I ran. The error is non-retryable, so every model-only run terminates as `LLM_GENERATION_FAILED` before the provider is contacted. Two further defects sit behind it: the outbound JSON schema does not admit `model_only` as an `answer_basis`, and the model-only prompt reuses a policy that instructs the model to cite evidence blocks that do not exist. The covering test passes only because it omits `.with_settings(..)` (leaving `grounding_limits: None`) and uses a fake generator; production sets both. The flag-OFF half of SC3 is verified and genuinely unchanged from pre-phase behavior — I checked the pre-phase runner source directly rather than assuming.

**SC5 fails on its own target case.** Citation repair builds its citation list one entry per marker *occurrence* and hands it to a validator that rejects duplicate IDs. An answer citing `[1]` twice, or mixing `[ 7 ]` with `[7]` against evidence `["[7]"]`, now hard-fails the run — and the second case is precisely what the widened extractor was added to normalize. With repair disabled the same answer passes, because that path compares inline markers as a set. All eight shipped repair tests use a single distinct marker, so the regression cannot be seen from the suite.

Both gaps are defects on the production path rather than alternative implementations achieving the same intent, so no override is suggested for either.

**Carry-forward.** The two human-verification items are recorded in this report's frontmatter under `human_verification:` even though the overall status is `gaps_found` (the gaps-found rule takes precedence in the decision tree, but the items are not conditional on it). Both persist past gap closure and must be resolved before the phase closes: re-verification must carry them forward, and a later run that closes SC3 and SC5 resolves to `human_needed`, not `passed`, until plan 06-12's flagged prohibition and the total-drop notice question each have an explicit owner decision.

Outside the criteria, two warnings deserve a look before the next phase: the gateway converts absent workflow metadata into an asserted `"degraded_mode": false` on exactly the degraded runs the channel exists for (the engine half is legitimately deferred to Phase 6.2 SC8, but the gateway half should omit the key rather than claim a value), and the engine's declarative environment-override source silently matches no documented variable — which the two passing env tests do not contradict, because those two keys have hand-written override paths of their own.

---

_Verified: 2026-08-21_
_Verifier: Claude (gsd-verifier)_
