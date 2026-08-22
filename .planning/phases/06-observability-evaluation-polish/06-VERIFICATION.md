---
phase: 06-observability-evaluation-polish
verified: 2026-08-22T18:40:00Z
status: gaps_found
score: 5/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/7
  gap_closure_plans:
    - plan: 06-13-PLAN.md
      targets: SC3
      resolution: partial
    - plan: 06-14-PLAN.md
      targets: SC5
      resolution: partial
  gaps_closed: []
  gaps_partially_closed:
    - "SC3 — production packing path repaired (empty-evidence branch + schema enum + policy exist and are reachable); the answer_basis contract is still unpinned, so the run succeeds only if the model volunteers `model_only` unprompted"
    - "SC5 — the duplicate-ID self-inflicted failure is genuinely fixed and both prior repro inputs now survive end to end; but the provider adapter rejects every repairable input that does not carry a healthy cited marker alongside it, so SC5's core clauses remain unreachable in production"
  gaps_remaining:
    - "SC3 (was: failed) — now partial"
    - "SC5 (was: partial) — still partial, different root cause than the prior report identified"
  regressions: []
gaps:
  - truth: "When both retrieval paths fail or evidence is absent and the caller has opted in (default off), the workflow returns answer_basis = MODEL_ONLY with an explicit notice and zero citations; with the flag off, today's fail-closed behavior is unchanged (D-10, D-11, D-12)"
    status: partial
    reason: >-
      Plan 06-13 closed the packing half of the prior gap: the empty-evidence branch, the
      ungrounded system policy, the schema enum and the request-flag plumbing all exist and are
      reachable from production. What is still missing is the outbound contract that makes the
      opted-in run deterministic. `model_only_system_policy()` never tells the model to set
      `answer_basis: "model_only"`, the outbound JSON schema lists `retrieval` first with no
      description, and BOTH validation sites reject the natural alternative output
      (`answer_basis: "retrieval"` + empty `cited_evidence_ids`) as a non-retryable
      SchemaValidation error. The engine's own doc comment says "the engine — not the model's own
      claim — decides the run is model-only", but the ordering makes the model's claim decisive.
      SC3's opted-in half therefore succeeds only when the model guesses an instruction it was
      never given; the failure mode is terminal (no retry) and 100% reachable in production
      because `OpenRouterGenerator` is the sole wired generator (`engine/src/main.rs:96`).
      The flag-OFF half of SC3 remains VERIFIED and unregressed.
    artifacts:
      - path: "engine/src/prompt.rs"
        issue: "`model_only_system_policy()` (lines 218-223) omits any `answer_basis` instruction. It says only \"do not cite evidence markers\"."
      - path: "engine/src/generation/mod.rs"
        issue: "Lines 210-220 hard-reject empty `cited_evidence_ids` unless `answer_basis == ModelOnly`, even when `allow_model_only` is true."
      - path: "engine/src/workflow/nodes/generate.rs"
        issue: "Line 153 validates the UNMODIFIED `output`; `into_model_only()` is applied only afterwards at line 165, so the node repeats the adapter's rejection instead of correcting it."
      - path: "engine/src/generation/tests.rs"
        issue: "`openrouter_empty_evidence_opt_in_reaches_chat_with_model_only_schema` (lines 881-980) hardcodes `\"answer_basis\": \"model_only\"` in the mock response body — the only reason the test is green."
      - path: "engine/src/tests/workflow_phase5.rs"
        issue: "`PackingTestGenerator` (lines 5630-5668) hardcodes `AnswerBasis::ModelOnly` in its return value. No test anywhere exercises a `retrieval`-basis response on an opted-in empty-evidence request."
    missing:
      - "An explicit `answer_basis` instruction in `model_only_system_policy()` — e.g. `Set answer_basis to \"model_only\" and leave cited_evidence_ids empty.` (this sentence was in the pre-gap-closure review's proposed text and was dropped in implementation)"
      - "Validate what will actually be emitted: at `generate.rs:147-165`, build `let for_validation = output.into_model_only();` and validate/re-enter THAT, so an engine-decided model-only run does not depend on the model's self-label"
      - "Apply the same correction at the adapter seam (`openrouter.rs:788-792`), or the node fix is unreachable because the adapter rejects first"
      - "A mock-server test whose response body carries `\"answer_basis\": \"retrieval\"` with empty `cited_evidence_ids` on an opted-in empty-evidence request, asserting the run still terminates with ANSWER_BASIS_MODEL_ONLY and a NOTICE_CODE_MODEL_ONLY notice. A FakeGenerator/PackingTestGenerator test cannot detect this defect class."
  - truth: "Citation repair (DEBT-RAG-03) normalizes near-miss markers locally, strips anything still unresolved, emits CITATION_REPAIRED/CITATION_DROPPED, and downgrades the basis if all grounding is lost — no second provider call (D-14)"
    status: partial
    reason: >-
      Plan 06-14's dedup fix is real and correct — both of the prior report's repro inputs now
      survive end to end, and the guard is placed so that per-occurrence span rewrites,
      per-occurrence notices and `total_drop` are all preserved. But the prior report identified
      the wrong root cause. `OpenRouterGenerator::execute_one_call` runs the FULL grounding
      validator on the RAW model output inside the adapter (`openrouter.rs:792`), before
      `GenerateAnswerNode`'s repair pass can normalize anything. That validator uses the strict
      digit-only `extract_inline_markers` (`mod.rs:409-430`) and enforces exact set equality
      (`mod.rs:355-364`) plus known-ID membership (`mod.rs:333-341`, `344-353`). Case-split against
      those four checks, the operative rule is: repair executes ONLY when a correctly-cited,
      strict-visible marker rides along in the same answer to satisfy set equality. A standalone
      near-miss, a standalone padded marker, any strict-visible unresolvable marker, and the whole
      total-drop basis-downgrade clause are unreachable. See the Gaps Summary for the exact split.
      This is pre-existing behavior, not a regression from 953b22c — SC5's repair pass has never
      been reachable for its stated purpose. `citation_repair_enabled` defaults to TRUE
      (`config.rs:143-145`), so this is the default configuration, and `OpenRouterGenerator` is
      the sole wired production generator (`main.rs:96`).
    artifacts:
      - path: "engine/src/generation/openrouter.rs"
        issue: "Line 792 calls `model_output.validate_grounding_with_limits(&validation_evidence, limits)` on the raw output inside the adapter — the fail-closed gate sits upstream of the repair seam that exists to fix exactly these inputs."
      - path: "engine/src/generation/mod.rs"
        issue: "`extract_inline_markers` (409-430) is digit-only and does not match `[ 7 ]`; the set-equality check at 355-364 and the known-ID checks at 333-341 / 344-353 therefore reject any answer whose repairable markers stand alone."
      - path: "engine/src/tests/workflow_phase5.rs"
        issue: "All 10 `citation_repair_*` tests (lines 5978-6360) drive `GenerateAnswerNode` with `FakeGenerator`, which never validates. `grep -c OpenRouterGenerator engine/src/tests/workflow_phase5.rs` = 0. `citation_repair_enabled_drops_internal_whitespace_marker_when_unresolvable` (:6050) uses a standalone padded marker cited as `[ 7 ]` against evidence `[1]` — an input the adapter rejects outright."
    missing:
      - "Split `validate_grounding_with_limits` (`generation/mod.rs:184-368`) so the adapter keeps only the non-repairable shape checks (answer non-empty, length, notice/warning and usage bounds) and the four marker checks (`mod.rs:331-365`) move to the seam that owns repair"
      - "Run `citations::extract_markers` / `resolve_markers` in `GenerateAnswerNode` FIRST, then call the full grounding validator on the post-repair output (the node already does this at `generate.rs:243-266`)"
      - "Keep the repair-DISABLED branch fail-closed — it already runs its own validation at `generate.rs:317-331` plus a completeness check at `generate.rs:341-352`, so no hole opens there (verified)"
      - "A regression test that drives the repair path through `OpenRouterGenerator` against the mock-server harness (`generation/tests.rs:881-985` is the template) with a response body containing a STANDALONE near-miss `[ 7 ]` (no valid cited companion) and, separately, a strict-visible unresolvable `[9]`, asserting the run succeeds with CITATION_REPAIRED / CITATION_DROPPED notices. Do NOT use a companion-marker input — those already pass today and would mask the defect."
human_verification: []
---

# Phase 6: Observability, Evaluation & Polish — Verification Report

**Phase Goal:** Rust + Go module-graph restructure, consolidated additive wire-contract change, and RAG-03 degraded-mode hardening (model-only answers, citation repair, bad-input matrix, graph-unavailable notice)
**Verified:** 2026-08-22T18:40:00Z
**Status:** gaps_found
**Re-verification:** Yes — after gap closure (`953b22c`, plans 06-13 and 06-14)

---

## Re-verification Trail (gap → plan → resolution)

This report OVERWRITES the prior verification. The full trail is preserved here.

| Prior gap | Prior status | Closing plan | Commit | Resolution now |
|---|---|---|---|---|
| **SC3** — model-only opt-in cannot produce an answer on the production path | `failed` | **06-13-PLAN.md** (Wave 11, `gap_closure: true`) | `953b22c` | **partial** — packing path fixed and reachable; the `answer_basis` contract is still unpinned |
| **SC5** — citation repair converts its own target case into a hard run failure (duplicate IDs) | `partial` | **06-14-PLAN.md** (Wave 12, `gap_closure: true`) | `953b22c` | **partial** — the stated duplicate-ID defect is genuinely fixed; a deeper, pre-existing adapter-ordering defect keeps SC5's core clauses unreachable |

**Prior `missing` list disposition — SC3 (GAP 1), 4 items:**

| Prior missing item | Now | Evidence |
|---|---|---|
| Empty-evidence branch in `execute_one_call` using `pack_model_only_prompt` rather than `pack_evidence_and_graph_prompt` | ✓ **DONE** | `openrouter.rs:263-267` — `if evidence.is_empty() && allow_model_only` returns `(model_only_system_policy(), "Question: {q}\n", vec![])` before `pack_evidence_and_graph_prompt` is reached |
| `"model_only"` admitted to the outbound `answer_basis` JSON schema enum | ✓ **DONE** | `openrouter.rs:570` — `"enum": ["retrieval", "mixed", "model_only"]` |
| A model-only system policy that does not instruct citing non-existent evidence blocks | ⚠️ **DONE, BUT INCOMPLETE** | `prompt.rs:218-223` exists and does not ask for markers — but also never instructs `answer_basis: "model_only"`, which is what the validator then requires |
| A test driving `GenerateAnswerNode` WITH `.with_settings(limits, ..)` against a generator that actually calls `pack_evidence_and_graph_prompt` on empty evidence | ✓ **DONE** | `PackingTestGenerator` (`workflow_phase5.rs:5630-5668`) calls the real `pack_openrouter_messages`; used at `workflow_phase5.rs:5686` and `:5726` |

**Prior `missing` list disposition — SC5 (GAP 2), both repro cases:**

| Prior repro | At the node | Through the production adapter |
|---|---|---|
| (1) repeated marker — `"…[1]…[1]…"` vs evidence `["[1]"]` | ✓ **FIXED** — `generate.rs:199,204` dedup guards yield `["[1]"]` | ✓ **reachable** — `inline_set = {"[1]"}` equals `seen_cited`, so the adapter passes it |
| (2) mixed spellings — `"[ 7 ]"` + `"[7]"` vs evidence `["[7]"]` | ✓ **FIXED** — dedup yields `["[7]"]`, `CITATION_REPAIRED` emitted | ✓ **reachable** — the strict extractor sees only the exact `[7]`, so `inline_set = {"[7]"} = seen_cited` and the adapter passes it |

Both prior repros are genuinely closed end-to-end. The gap that remains is a **different, wider one**
the prior report did not identify: both repros happened to carry a healthy cited marker, which is
precisely the condition under which the adapter lets repair run at all (see Gaps Summary).

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria SC1–SC7)

| # | Truth | Status | Evidence |
|---|---|---|---|
| SC1 | Rust binary imports all production modules from the library crate; dual `lib.rs`/`main.rs` declaration ends. Go `main.go` symmetrically split into packages | ✓ VERIFIED (carried forward from prior run; regression-checked only — outside the `953b22c` delta) | `grep "^mod \|^pub mod " engine/src/main.rs` → **0 matches**; `engine/src/lib.rs` declares 16 `pub mod`. `gateway/internal/{config,engineclient,sse,telemetry}` all exist; `gateway/main.go:33-36` imports all four |
| SC2 | One consolidated additive protobuf change — model-only flag, graph-ablation flag, `WorkflowCompletedEvent` fields, typed notice-code enum — with regenerated Rust and Go bindings | ✓ VERIFIED (carried forward; regression-checked) | `proto/lancet/v1/lancet.proto:61` `optional bool allow_model_only = 4`, `:66` `optional bool disable_graph_context = 5`, `:72-98` `enum NoticeCode` (codes 10-22 appended, 0-5 untouched → additive), `:119` `NoticeCode typed_code = 4`, `:245` `message WorkflowCompletedEvent`. Rust bindings regenerated (`engine/src/pb/lancet/v1/lancet.v1.rs:330-384`) |
| SC3 | Opted-in zero-evidence run returns `answer_basis = MODEL_ONLY` + notice + zero citations; flag off keeps fail-closed | ✗ **FAILED (partial)** | Flag-OFF half VERIFIED (`openrouter.rs:263` falls through to `pack_evidence_and_graph_prompt` → `EmptyEvidence`; `runner.rs:420` short-circuits). Opted-in half is contingent on undirected model behavior — see CR-02 adjudication |
| SC4 | One retrieval path failing keeps `answer_basis = RETRIEVAL` with a machine-readable `RETRIEVAL_DEGRADED` notice naming the failed path | ✓ VERIFIED (carried forward; regression-checked) | `engine/src/workflow/nodes/retrieve.rs:88` `NoticeCode::RetrievalDegradedDense`, `:141` `NoticeCode::RetrievalDegradedBm25` — per-path, non-test code |
| SC5 | Citation repair normalizes near-miss markers, strips unresolved, emits `CITATION_REPAIRED`/`CITATION_DROPPED`, downgrades basis on total loss — no second provider call | ✗ **FAILED (partial)** | Repair runs only when a healthy cited marker rides along in the same answer; standalone repairable markers and the total-drop clause are rejected at `openrouter.rs:792` — see CR-01 adjudication |
| SC6 | Bad-input matrix is an enumerated, table-driven test (gRPC and HTTP) rejecting before retrieval/provider work with stable HTTP 400 / gRPC `InvalidArgument` | ✓ VERIFIED (carried forward from prior run; **not re-checked** — outside the `953b22c` delta) | `engine/src/tests/bad_input_matrix.rs` present. The HTTP half was verified in the prior run and is carried forward unre-examined |
| SC7 | `GRAPH_UNAVAILABLE` notice fires on the two silent-degrade paths (empty-result, absent `graph_port`); source-chunk queries proven never to require graph data | ✓ VERIFIED (carried forward; regression-checked) | `engine/src/workflow/nodes/graph_context.rs:129` and `:175` — exactly two `NoticeCode::GraphUnavailable` emission sites in non-test code, matching the two named paths |

**Score:** 5/7 truths verified (0 present-but-behavior-unverified)

### A note on `Mode: mvp` and the phase goal format

ROADMAP marks Phase 6 `**Mode:** mvp`, but the phase goal is a deliverables statement, not a
`As a … I want to … so that …` User Story. Under a strict MVP-mode reading the verifier would
refuse and route to `/gsd mvp-phase`. That is not done here: this is a scoped re-verification with
an explicit seven-criterion contract, there is no `[outcome]` clause to narrow to, and the seven
numbered Success Criteria are the actual contract. Recorded as a documentation discrepancy, not a
gap.

### The D-79 redistribution note is NOT a Step-9b deferral — do not read it as one

ROADMAP's Phase 6 block carries this line immediately above the criteria:

> Phase 6's original seven success criteria were rewritten and redistributed across the five-phase
> split per 06-CONTEXT.md D-79. Mapping: SC1 → 6.2; SC2 and SC4 → 6.3; **SC3 → 6.4**; **SC5** and
> SC6 → 6.1; SC7 → 6 and 6.1.

Read naively, that mapping would defer both of this report's gaps to later phases and flip the
phase to `passed`. **It does not apply.** The mapping describes the *original, pre-split*
observability criteria, not the seven currently listed. Proof: current SC1 is the Rust/Go module
graph, not observability; the note claims "SC1 → 6.2" and Phase 6.2 is OpenTelemetry — the two
cannot be the same SC1. Cross-checked positively as well: Phase 6.1's criteria are index
rebuild-and-swap, `DEBT-BU-01`/`DEBT-BU-02` and the documented-only `DEBT-CR-04`/`DEBT-CR-05`
review; Phase 6.4's are the docs suite. **Neither mentions model-only answers or citation repair.**
So SC3 and SC5 as currently written are Phase 6's own contract and have no downstream owner. They
are real gaps, not deferred items.

### Deferred Items

None. (See the D-79 analysis above — the apparent deferral does not hold.)

---

## Adjudication of the 06-REVIEW.md criticals

Both criticals are **UPHELD** — with CR-01 restated more precisely. I confirmed every load-bearing
code fact by reading the files rather than trusting the review.

### CR-01 (SC5) — UPHELD, but the review's "never" is too broad

The review asserts "`CITATION_REPAIRED` and `CITATION_DROPPED` can therefore never be emitted by a
production run." **That is falsifiable, and the review's own quoted passing test is a
counterexample.** The real rule is narrower and sharper:

> **Repair executes only when a correctly-cited, strict-visible marker rides along in the same
> answer to satisfy the adapter's set-equality check.** Any answer whose repairable markers stand
> alone is rejected upstream at `openrouter.rs:792`.

Worked example of the reachable case. Input: answer `"Near miss [ 7 ] and exact [7] in one
answer."`, `cited_evidence_ids: ["[7]"]`, packed evidence `["[7]"]`. `extract_inline_markers`
(`mod.rs:409-430`) skips `[ 7 ]` (the byte after `[` is a space, so `is_num` stays false) and yields
`["[7]"]` → `inline_set = {"[7]"}` equals `seen_cited = {"[7]"}` at `mod.rs:355-364`, and
`[7] ∈ known_ids` at `mod.rs:333-341`, `344-353`. **The adapter passes it.** It then reaches
`GenerateAnswerNode`, whose widened `citations::extract_markers` finds *both* spellings →
`Repaired("[7]")` + `Unchanged("[7]")` → deduped at `generate.rs:199,204` → `CITATION_REPAIRED`
fires.

Full clause-by-clause reachability:

| SC5 clause | Production reachability | Where it dies / why it survives |
|---|---|---|
| "normalizes near-miss markers locally" — *standalone* near-miss (`[ 7 ]`, no valid companion) | ✗ **UNREACHABLE** | cited `["[7]"]` → `inline_set = {}` ≠ `{"[7]"}` at `mod.rs:355-364`; cited `["[ 7 ]"]` → not in `known_ids` at `mod.rs:333-341` |
| "normalizes near-miss markers" — near-miss *alongside* an exact cited copy of the same ID | ✓ **reachable (narrow)** | worked example above; adapter passes, repaired at `generate.rs:199-217` |
| "strips anything still unresolved" — strict-visible unresolvable marker (`[9]` vs evidence `["[1]"]`) | ✗ **UNREACHABLE** | fails `mod.rs:344-353` if inline-only, or `mod.rs:333-341` if also cited |
| "strips anything still unresolved" — *padded* unresolvable marker **with** a valid cited companion | ✓ **reachable (narrow)** | `"Fact [1] and bogus [ 99 ]."`, cited `["[1]"]`, evidence `["[1]"]`: the strict extractor skips `[ 99 ]`, so `inline_set = {"[1]"} = seen_cited` → adapter passes → the node's widened extractor normalizes `[ 99 ]` → not in `evidence_ids` → `Resolution::Dropped` |
| "emits `CITATION_REPAIRED` / `CITATION_DROPPED`" | ✓ **reachable only in the two companion cases above** | never for a standalone repairable marker |
| "downgrades the basis if all grounding is lost" | ✗ **UNREACHABLE** | `total_drop` (`generate.rs:241`) needs EVERY marker dropped. All-padded forces strict `inline_set = {}`, so either cited is non-empty (mismatch → adapter rejects) or cited is empty, which requires `answer_basis = ModelOnly` at `mod.rs:210-220` — and that routes to the model-only branch at `generate.rs:148`, skipping the repair pass entirely |
| "no second provider call" | ✓ **VERIFIED** | the `Ok(output)` arm of `generate.rs:145-300` contains no `generator.generate(..)`; `generation/citations.rs` is synchronous and network-free |

**Read `citation_repair_enabled_drops_internal_whitespace_marker_when_unresolvable`
(`workflow_phase5.rs:6050-6088`) before citing it either way.** Its answer is `"Unsupported
near-miss span [ 7 ] appears here."` with `cited_evidence_ids: ["[ 7 ]"]` and evidence `["[1]"]` —
the padded marker stands alone and the cited ID is not in `known_ids`, so **that exact input is
adapter-rejected** and the test proves nothing about production. The companion variant in the table
above is the reachable one.

Supporting datum independently reproduced: `grep -c "OpenRouterGenerator"
engine/src/tests/workflow_phase5.rs` → **0**. All 10 `citation_repair_*` tests use `FakeGenerator`.
The only two `OpenRouterGenerator` constructions in the workflow test surface
(`workflow_phase5_production.rs:867`, `:969`) are retry and cancellation tests, not repair. So no
test anywhere drives repair through the layer that rejects it.

This defect is **pre-existing**, not introduced by `953b22c` — the adapter has always validated raw
output. `953b22c` only added `.with_allow_model_only(request.allow_model_only)` to the limits. The
prior verification identified a real but *shallower* defect; 06-14 fixed exactly that one.

### CR-02 (SC3) — UPHELD in full

Confirmed line by line:

- `prompt.rs:218-223` — `model_only_system_policy()` says only *"No corpus evidence is provided for
  this request; do not cite evidence markers."* No `answer_basis` instruction.
- `openrouter.rs:566-571` — the outbound schema offers `["retrieval", "mixed", "model_only"]` with
  `retrieval` first and no per-value description.
- `mod.rs:210-220` — with `allow_model_only = true` and the model returning
  `answer_basis: "retrieval"` + empty `cited_evidence_ids`, the predicate is
  `is_empty() && (!true || Retrieval != ModelOnly)` = `true && (false || true)` = **true** → hard
  `SchemaValidation` error.
- `generate.rs:126-127` — `SchemaValidation` is not in the retryable set (`Timeout` /
  `ProviderError` only), so there is no second attempt: the run terminates as
  `NodeErrorKind::LlmGenerationFailed`.
- `generate.rs:153` validates the **unmodified** `output`; `into_model_only()` is applied only at
  `:165`. So the node repeats the adapter's rejection instead of correcting it — lifting the
  adapter check alone would not fix SC3.
- Directly contradicts the engine's own documented design at `generation/mod.rs:379`: *"the engine —
  not the model's own claim — decides the run is model-only."* Ordering makes the model's claim
  decisive.
- Test blindness confirmed by reading bodies, not names:
  `openrouter_empty_evidence_opt_in_reaches_chat_with_model_only_schema`
  (`generation/tests.rs:881-980`) hardcodes `"answer_basis": "model_only"` in the mock response
  body; `PackingTestGenerator` (`workflow_phase5.rs:5630-5668`) hardcodes `AnswerBasis::ModelOnly`
  in its return value.

### Three review-adjacent claims I checked and found NOT to be gaps

- **No D-17/D-19 prompt regression.** `pack_openrouter_messages`'s grounded branch hardcodes
  `system_msg = "You are a precise technical RAG engine."` (`openrouter.rs:296`), which looks like
  it dropped the D-17/D-19 clauses. It did not: `base_system_policy()` is still embedded into the
  packed prompt at `prompt.rs:363-372`, and that prompt becomes `messages[1]`. "Cite evidence using
  numbered markers like [1], [2]" and "When evidence contradicts your prior knowledge, the evidence
  is authoritative" both still reach the wire, just as the user message. WR-01 is therefore a dead
  public field (`GenerationRequest::system_policy`), a cleanliness warning — not a behavior gap.
- **`run_inline_prompt_generation_remainder` is test-only.** Grepping `engine/` and `gateway/`, its
  only callers are `workflow_phase5.rs:1594, 1702, 1834, 1917, 5304`. It is `pub` and ungated
  (carried-forward WR-01 from the pre-gap-closure review), which matters as a *dependency* of the
  CR-01 fix — do not remove the adapter gate without closing it — but it is not a live production
  fail-open path today.
- **The blank telemetry import is intentional, not dead wiring.** `gateway/main.go:36` imports
  `internal/telemetry` as `_`. That is the reserved stub 06-04 planned; SC1 requires the package
  *split*, not telemetry behavior (which is Phase 6.2's SC1-SC8). Consistent with the contract.

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `engine/src/generation/openrouter.rs` | Empty-evidence model-only packing branch; `model_only` in outbound schema | ✓ VERIFIED | `:263-267` branch; `:570` enum. Wired — sole production generator (`main.rs:96`) |
| `engine/src/prompt.rs` | `model_only_system_policy()`, `pack_model_only_prompt()` | ⚠️ HOLLOW | Both exist (`:218-227`). `model_only_system_policy()` IS wired (`openrouter.rs:264`) but under-specifies the contract. `pack_model_only_prompt()` is ORPHANED relative to the wire — its only non-test consumers are `workflow/mod.rs:266` (test-only path) and `workflow/events.rs:229` (checkpoint serializer); the adapter builds a differently-shaped prompt and never calls it |
| `engine/src/workflow/nodes/generate.rs` | Citation-repair pass with dedup; model-only conversion | ⚠️ ORPHANED for its target inputs | Dedup guards at `:199, :204` are correct and correctly placed (notice/edit pushes at `:206-234` sit outside the guard, preserving per-occurrence spans and notices; `total_drop` at `:241` unaffected). But the pass receives its target inputs only when a healthy cited marker happens to accompany them |
| `engine/src/generation/mod.rs` | Grounding validator, `allow_model_only` limits | ✓ VERIFIED (present + wired) | `:184-368`. Its *placement* is the defect, not its existence |
| `engine/src/generation/citations.rs` | Marker extraction / resolution, network-free | ✓ VERIFIED | Synchronous, no provider call — pins the D-14 "no second call" clause |
| `proto/lancet/v1/lancet.proto` + generated bindings | Additive-only wire change | ✓ VERIFIED | Fields 4/5 appended as `optional`; enum values 10-22 appended, 0-5 unchanged |
| `gateway/internal/{config,sse,engineclient,telemetry}` | Go package split | ✓ VERIFIED (carried forward) | All four exist; imported at `gateway/main.go:33-36` |
| `engine/src/tests/bad_input_matrix.rs` | Table-driven bad-input matrix | ✓ VERIFIED (carried forward, not re-checked) | Present; prior run verified content |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `WorkflowContext.allow_model_only` | `GenerationRequest.allow_model_only` | field assignment | ✓ WIRED | `generate.rs:106`; the only other non-test `GenerationRequest::new` site (`workflow/mod.rs:288`) also sets it at `:294` |
| `GenerationRequest.allow_model_only` | `pack_openrouter_messages` | positional arg | ✓ WIRED | `openrouter.rs:534-543` → `:263` |
| `GenerateAnswerNode` repair pass | `OpenRouterGenerator` output | `Ok(output)` arm | ✗ **NOT WIRED for standalone repairable inputs** | The adapter's `validate_grounding_with_limits` (`openrouter.rs:792`) rejects any answer whose repairable markers are not accompanied by a healthy cited marker |
| `model_only_system_policy()` | outbound `messages[0]` | adapter | ✓ WIRED | `openrouter.rs:264` |
| `pack_model_only_prompt()` | outbound payload | — | ✗ **NOT WIRED** | Two divergent model-only prompt constructions exist; the adapter's is the one that ships |
| `AnswerBasis::ModelOnly` decision | model self-report | validator ordering | ✗ **INVERTED** | Engine-decides is documented (`mod.rs:379`) but model-decides is implemented |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `GenerateAnswerNode` | `repaired_citations` | `citations::resolve_markers` over the real answer text | Yes at the node — but only for inputs the adapter already accepted | ⚠️ PARTIAL: for standalone repairable markers, control never arrives |
| `GenerateAnswerNode` | `ctx.notices` (`CITATION_REPAIRED`) | `pending_notices` from `Resolution::Repaired` | Only when a near-miss rides alongside an exact cited copy | ⚠️ PARTIAL |
| `GenerateAnswerNode` | `ctx.notices` (`CITATION_DROPPED`) | `pending_notices` from `Resolution::Dropped` | Only when a *padded* unresolvable marker rides alongside a valid cited companion | ⚠️ PARTIAL |
| `GenerateAnswerNode` | `ctx.answer_basis = ModelOnly` (total-drop downgrade) | `into_model_only()` at `:250` | **No** — `total_drop` is unproducible in production | ✗ DISCONNECTED |
| `GenerateAnswerNode` | `ctx.answer_basis = ModelOnly` (opted-in path) | `output.into_model_only()` at `:165` | Only when the model volunteered `model_only` | ⚠️ STATIC — contingent on undirected model output |

### Behavioral Spot-Checks

Full regression suite was run by the orchestrator (Rust 380 tests: 344 passed / 1 ignored / 0
failed; full Go gateway suite; both exit 0) and is not re-run here. The relevant finding is that a
green suite is **not** evidence for SC3 or SC5, and the checks below establish why by reading test
bodies rather than names.

| Behavior | Command / check | Result | Status |
|---|---|---|---|
| Any SC5 test exercises the production adapter | `grep -c "OpenRouterGenerator" engine/src/tests/workflow_phase5.rs` | `0` | ✗ FAIL — all 10 repair tests use `FakeGenerator`, which never validates |
| The one SC5 drop test uses a production-reachable input | read `workflow_phase5.rs:6050-6088` | standalone `[ 7 ]`, cited `["[ 7 ]"]`, evidence `["[1]"]` | ✗ FAIL — adapter-rejected input; proves nothing about production |
| SC3 adapter test asserts model-decided basis | read `generation/tests.rs:881-980` | mock body hardcodes `"answer_basis": "model_only"` | ✗ FAIL — the assertion is on the mock, not the contract |
| SC3 node test asserts model-decided basis | read `workflow_phase5.rs:5630-5668` | `PackingTestGenerator` hardcodes `AnswerBasis::ModelOnly` | ✗ FAIL — same defect class |
| SC3 packing path is genuinely production-shaped | read `PackingTestGenerator` body | calls the real `pack_openrouter_messages` with `request.allow_model_only` | ✓ PASS — prior missing item #4 genuinely closed |
| Repair defaults on | `grep citation_repair_enabled engine/src/config.rs` | `default_citation_repair_enabled() -> true` (`:143-145`) | ✓ PASS — SC5's gap is in the DEFAULT configuration |
| Model-only defaults off (SC3 flag-off half) | `grep allow_model_only engine/src/config.rs` | `default_allow_model_only_answers() -> false` (`:140-142`) | ✓ PASS |
| Rust binary has no duplicate module declarations | `grep "^mod \|^pub mod " engine/src/main.rs` | no matches | ✓ PASS (SC1) |

### Probe Execution

Not applicable — no `scripts/*/tests/probe-*.sh` exist in this repository and no plan or success
criterion in Phase 6 declares a probe. Step 7c: SKIPPED (no probes declared or discoverable).

### Requirements Coverage

All 14 plans declare exactly `requirements: [RAG-03]`. `REQUIREMENTS.md:52` scopes it: *"DEBT-RAG-01,
DEBT-RAG-03, DEBT-RAG-05 and DEBT-RAG-06 clauses → Phase 06; DEBT-RAG-04 (index rebuild-and-swap)
→ Phase 06.1."* Every ID in the phase requirement line is accounted for below; no orphans.

| Requirement | Clause | Source Plans | Description | Status | Evidence |
|---|---|---|---|---|---|
| RAG-03 | DEBT-RAG-01 (degraded mode — retrieval path failure) | 06-09 | One path failing keeps `RETRIEVAL` basis with a per-path notice | ✓ SATISFIED | `retrieve.rs:88, 141` (SC4) |
| RAG-03 | DEBT-RAG-01 (degraded mode — model-only answers) | 06-10, 06-13 | Opted-in zero-evidence run returns MODEL_ONLY | ✗ **BLOCKED** | SC3 gap — outbound `answer_basis` contract unpinned |
| RAG-03 | DEBT-RAG-03 (citation repair) | 06-11, 06-14 | Normalize, strip, notice, downgrade — no second call | ✗ **BLOCKED** | SC5 gap — repair reachable only with a healthy companion marker; total-drop downgrade unreachable |
| RAG-03 | DEBT-RAG-05 (bad-input matrix) | 06-12 | Enumerated table-driven gRPC + HTTP rejection matrix | ✓ SATISFIED (carried forward, not re-checked) | `engine/src/tests/bad_input_matrix.rs` |
| RAG-03 | DEBT-RAG-06 (graph-unavailable notice) | 06-08 | Notice on the two silent-degrade paths | ✓ SATISFIED | `graph_context.rs:129, 175` (SC7) |
| RAG-03 | DEBT-RAG-04 (index rebuild-and-swap) | — | — | ↪ **OUT OF SCOPE** — explicitly assigned to Phase 6.1 by `REQUIREMENTS.md:52` and Phase 6.1 SC1-SC4 | Correctly not claimed by any Phase 6 plan |

**Net:** RAG-03 is **partially satisfied**. Two of its four in-scope clauses (DEBT-RAG-01's
model-only half, DEBT-RAG-03) are blocked. RAG-03 must remain unchecked in `REQUIREMENTS.md`.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `engine/src/generation/openrouter.rs` | 792 | Fail-closed validation gate placed upstream of the repair seam that exists to fix those inputs | 🛑 Blocker | Root cause of the SC5 gap |
| `engine/src/workflow/nodes/generate.rs` | 153, 165 | Validate-then-convert ordering — the unmodified output is validated, `into_model_only()` applied afterwards | 🛑 Blocker | Root cause of the SC3 gap; inverts the documented engine-decides design |
| `engine/src/generation/tests.rs` | ~910 | Mock hardcodes the exact field under test (`"answer_basis": "model_only"`) | ⚠️ Warning | Green test that cannot fail on the production contract |
| `engine/src/tests/workflow_phase5.rs` | ~5661 | `PackingTestGenerator` hardcodes `AnswerBasis::ModelOnly` | ⚠️ Warning | Same class |
| `engine/src/tests/workflow_phase5.rs` | 6050-6088 | Drop-path test built on an input the production adapter rejects outright | ⚠️ Warning | Reads as SC5 coverage of the drop clause; is not |
| `engine/src/tests/workflow_phase5.rs` | 5790-5798 | `pack_model_only_prompt_uses_ungrounded_policy` pins a function production never invokes | ⚠️ Warning | Reads as SC3 coverage; is not |
| `engine/src/generation/openrouter.rs` | 245 | `#[allow(clippy::too_many_arguments)]` instead of `#[expect(..)]` | ⚠️ Warning | `rust-guidelines.md` M-LINT-OVERRIDE-EXPECT |
| `engine/src/generation/openrouter.rs` | 245-254 | Positional `allow_model_only: bool` wedged between two `usize` params at a security-relevant call site (`:534-543`) | ⚠️ Warning | A transposition is silent at compile time and flips the fail-closed default |
| `scripts/engine-test-targets.sh` | 7, 29 | Hardcoded developer home path (`/mnt/c/Users/user3/.cargo/bin`); unguarded pipeline under `set -e` with no `pipefail` | ⚠️ Warning | A build failure reports as `TOTAL test count mismatch: expected 380, got 0`. Carried forward (WR-11); `953b22c` touched this file but changed only the counts |
| `engine/src/generation/mod.rs` | 435 | `GenerationRequest::system_policy` is `pub`, serialized, compared in `PartialEq` — and read by no production code | ⚠️ Warning | Carried forward (WR-01). Behavior is intact (`base_system_policy()` still reaches the wire via `prompt.rs:363-372`), but a caller setting it gets a silent no-op |

No unreferenced `TBD` / `FIXME` / `XXX` debt markers were found in the files `953b22c` touched.

### Human Verification Required

None. Both gaps are deterministic code paths verified by reading the implementation; neither
requires human judgment or a running service.

---

## Gaps Summary

**The phase goal is not achieved.** Five of seven Success Criteria hold. The two that do not are
exactly the two the gap-closure round targeted, and both moved from "broken" to "partially
reachable" without arriving.

**One root cause spans both gaps: the provider adapter is the fail-closed decision point for
concerns the workflow layer is supposed to own.** `OpenRouterGenerator::execute_one_call` runs the
complete grounding validator on the raw model output at `openrouter.rs:792` — before
`GenerateAnswerNode` can repair a marker (SC5) or before the engine can assert the model-only basis
it already decided on (SC3). Every SC3 and SC5 behavior the phase was supposed to ship is
downstream of a gate that rejects its inputs.

**SC3.** Plan 06-13 fixed the packing half — genuinely and verifiably. The opted-in empty-evidence
request now reaches the provider with the ungrounded policy and a schema that admits `model_only`.
What is missing is the contract: the prompt never asks the model for
`answer_basis: "model_only"`, and both validation layers hard-reject the natural alternative
(`retrieval` basis with zero citations) as a non-retryable error. The engine's own doc comment
promises engine-decided model-only; the implementation delivers model-decided. SC3 currently
succeeds when the model guesses.

**SC5.** Plan 06-14's dedup fix is correct and both prior repro inputs now pass end to end — this is
real progress, not paperwork. But the prior report diagnosed a shallower defect than the one that
actually blocks SC5, and both of its repros happened to satisfy the deeper constraint. Case-split
against `mod.rs:331-365`, the operative rule is: **repair executes only when a correctly-cited,
strict-visible marker rides along in the same answer to satisfy the adapter's set-equality check.**
A near-miss with an exact cited companion is repaired; a padded unresolvable marker with a valid
cited companion is dropped. But a standalone near-miss, a standalone padded marker, any
strict-visible unresolvable marker (`[9]`), and the entire total-drop basis-downgrade clause are all
rejected one layer earlier. That is not "normalizes near-miss markers locally" — it is "normalizes
them if a healthy citation happens to be present in the same answer," on the default configuration
(`citation_repair_enabled = true`).

**Why the suite is green anyway — the same defect class as the prior round.** Every SC5 test uses
`FakeGenerator`, which never validates (`grep -c OpenRouterGenerator
engine/src/tests/workflow_phase5.rs` = 0), and the one drop-path test is built on an input the
adapter rejects. Every SC3 test hardcodes `"answer_basis": "model_only"` in the double. The doubles
never touch the layer that fails. A closure plan for either gap must land a test that drives the
path through `OpenRouterGenerator` against the mock-server harness (`generation/tests.rs:881-985` is
the working template), using a **standalone** repairable marker — a companion-marker input passes
today and would mask the defect. A `FakeGenerator`-based test cannot detect this class and should
not be accepted as proof a third time.

**Ordering note for the fixer.** The two gaps share the adapter seam, so they should be closed in
one plan or in a fixed order. Splitting `validate_grounding_with_limits` to move the four marker
checks (`mod.rs:331-365`) out of the adapter fixes SC5 but does nothing for SC3 on its own, because
`generate.rs:153` independently rejects the same output. And removing the adapter gate without
first gating `run_inline_prompt_generation_remainder` (`workflow/mod.rs:249-363`, currently `pub`
and validation-free — test-only today, but published) would turn that path fully fail-open.

---

_Verified: 2026-08-22T18:40:00Z_
_Verifier: Claude (gsd-verifier)_
_Supersedes the initial Phase 6 verification; the gap → plan → resolution trail is preserved in the Re-verification Trail section above._
