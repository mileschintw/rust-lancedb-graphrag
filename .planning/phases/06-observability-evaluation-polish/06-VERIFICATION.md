---
phase: 06-observability-evaluation-polish
verified: 2026-08-22T21:05:00Z
status: human_needed
score: 7/7 must-haves verified
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
    - plan: 06-15-PLAN.md
      targets: SC3, SC5
      resolution: resolved
  gaps_closed:
    - "SC3 — the opted-in zero-evidence run is now ENGINE-decided, not model-decided. `generate.rs:150` builds `for_validation = output.into_model_only()`, validates THAT, and passes `&for_validation` to `update_from_model_output` (`:166`). Proven end to end by `openrouter_node_optin_empty_evidence_retrieval_basis_still_yields_model_only` — a real `OpenRouterGenerator` against a mock HTTP server whose body carries `answer_basis: \"retrieval\"` with empty `cited_evidence_ids`, asserting on `ctx.answer_basis == ModelOnly`, `ctx.citations.is_empty()` and a `NoticeCode::ModelOnly` notice. Flag-off half unregressed for the scenario SC3 names."
    - "SC5 — all three previously-unreachable clauses now execute in production. The adapter was reduced to `validate_output_shape_with_limits` (`openrouter.rs:797`) and the four marker checks moved downstream to `validate_marker_grounding`, run post-repair at `generate.rs:261`. Standalone near-miss `[ 7 ]` → repaired; strict-visible unresolvable `[9]` → dropped; total citation loss → basis downgraded to MODEL_ONLY with BASIS_RECONCILED. All three proven through a real `OpenRouterGenerator` against mock HTTP servers with assertions on `WorkflowContext`. All three mock bodies independently re-derived against the PRE-split validator (`953b22c:openrouter.rs:792`) and confirmed rejected there."
  gaps_remaining: []
  regressions: []
deferred: []
coincidental_reliance_items:
  - truth: "Citation repair (DEBT-RAG-03) normalizes near-miss markers locally, strips anything still unresolved, emits CITATION_REPAIRED/CITATION_DROPPED, and downgrades the basis if all grounding is lost — no second provider call (D-14)"
    reason: undeclared-precondition
    harden: >-
      All four new SC5/SC3 proofs use a single-block (or empty) evidence set, so
      `ctx.evidence_blocks == packed_evidence.evidence` holds in every one of them. Their green
      status therefore depends on a no-truncation precondition that production does not guarantee —
      `pack_evidence_and_graph_prompt` (`prompt.rs:337-...`) drops blocks that exceed
      `allowed_evidence_tokens`. Promote "the packed subset equals the retrieved set" into a
      declared precondition, or add a multi-block test whose evidence set is deliberately truncated
      by the budget. Advisory only — score and status unaffected.
human_verification:
  - test: >-
      Decide the intended flag-off semantics on the D-18 total-drop path, then pin it with a test.
      Set `allow_model_only = false`, evidence `["[1]"]`, and have the model return
      `answer_basis: "retrieval"` with `cited_evidence_ids: ["[9]"]` and answer text citing only
      `[9]`. Today `effective_allow = ctx.allow_model_only || total_drop` (`generate.rs:255`) makes
      the run succeed with `ANSWER_BASIS_MODEL_ONLY`.
    expected: >-
      Either (a) confirm the downgrade is intentionally flag-independent and record that decision,
      or (b) scope the relaxation to the disclosure and keep `LlmGenerationFailed` when the flag is
      off. Before this delta the same exchange returned `LlmGenerationFailed`.
    why_human: >-
      This is a contract choice, not a defect. No ROADMAP Success Criterion governs it — SC3's
      flag-off clause is scoped by its own parenthetical to (D-10, D-11, D-12), the empty-evidence
      and retrieval-failure decisions, while the total-drop reconciliation path is D-18, grouped
      with DEBT-RAG-03/SC5 in the ROADMAP plan list (06-11). Code review raised it as CR-02; the
      orchestrator ruled it spec-conformant. The behavior change is real and newly
      production-reachable either way, and `openrouter_node_model_only_flag_off_stays_fail_closed`
      cannot detect it because that test never reaches the provider.
  - test: >-
      T-06-15-03 / backstop must_have. Construct a retrieval result whose evidence set is larger
      than what fits in `allowed_evidence_tokens`, so `pack_evidence_and_graph_prompt` truncates
      block `[N]` out of the prompt. Have the model emit `[N]` as a citation.
    expected: >-
      Decide whether a citation naming a retrieved-but-truncated block should resolve (today it
      does, and its excerpt is shipped to the client via `resolve_citations(&ctx.citations,
      &ctx.evidence_blocks)`) or fail closed (pre-split behavior).
    why_human: >-
      `insufficient_spec` — this must_have carries `verification: backstop` in 06-15-PLAN.md, and
      Step 5b forbids inferring it from presence and wiring. No test in the repository exercises a
      truncated-block marker. Confirmed by primary evidence: at `953b22c:openrouter.rs:792` the
      adapter validated markers against `validation_evidence = packed_evidence.evidence` (the
      subset actually sent to the model); today no code path validates against the packed subset —
      the adapter discards it as `_validation_evidence` (`openrouter.rs:534`) and all four
      downstream gates bind to `ctx.evidence_blocks`.
  - test: >-
      Decide whether the D-18 total-drop path should emit `NOTICE_CODE_MODEL_ONLY` alongside the
      basis downgrade. Today it emits `CITATION_DROPPED` + `BASIS_RECONCILED` and sets
      `answer_basis = MODEL_ONLY`, but no `MODEL_ONLY` notice — unlike branch 1
      (`generate.rs:167-171`) and the inline remainder (`workflow/mod.rs:361-365`).
    expected: >-
      Either add the notice so "MODEL_ONLY basis implies a MODEL_ONLY notice" holds on all three
      paths, or record that `BASIS_RECONCILED` is the intended machine-readable disclosure for this
      path.
    why_human: >-
      SC5's text requires only "downgrades the basis if all grounding is lost" — it does not require
      a MODEL_ONLY notice, and `BASIS_RECONCILED` + `CITATION_DROPPED` are both machine-readable, so
      the phase user story ("without parsing prose") is satisfied. This is a cross-path invariant
      question, not an SC failure. Raised as CR-01; orchestrator downgraded to info as
      spec-conformant.
  - test: >-
      Review the four specless-probe edges 06-15-PLAN.md declares unresolved (unclassified RAG-03,
      DEBT-RAG-01, DEBT-RAG-06; DEBT-RAG-05 concurrency) and decide whether each needs coverage
      before the phase closes.
    expected: "Each edge is either given a probe/test or explicitly recorded as accepted-uncovered."
    why_human: >-
      judgment-tier prohibition, status `flagged-unverified`. No `06-SPEC.md` exists, so there is no
      contract to verify against — the plan explicitly declines to treat them as covered and this
      report does not absorb them into the pass. Prohibitions P2 (no ungated generator path) and P3
      (no test double as SC3/SC5 proof) were affirmatively resolved by codebase evidence this round
      and are NOT carried forward.
  - test: "Run `/gsd-secure-phase 6` to produce `06-SECURITY.md`."
    expected: "The phase security gate closes."
    why_human: >-
      `workflow.security_enforcement` is active and no `06-SECURITY.md` exists. Non-blocking for
      goal achievement; blocking for phase advancement. Routing item only.
  - test: "Run `/gsd-validate-phase 6` to refresh `06-VALIDATION.md`."
    expected: "Nyquist coverage is established for plans 06-08 through 06-15."
    why_human: >-
      `06-VALIDATION.md` is `status: draft`, `nyquist_compliant: false`, dated 2026-08-20 — it
      predates plans 06-08..06-15. The §7.5 gate checks existence only, so coverage for the new
      work is not established. Routing item only.
---

# Phase 6: Observability, Evaluation & Polish — Verification Report

**Phase Goal:** Rust + Go module-graph restructure, consolidated additive wire-contract change, and RAG-03 degraded-mode hardening (model-only answers, citation repair, bad-input matrix, graph-unavailable notice)
**Verified:** 2026-08-22T21:05:00Z
**Status:** human_needed
**Re-verification:** Yes — third gap-closure round (`4fb4859`, `30fdc46`, `84baf5e`; plan 06-15)

---

## Headline

**SC3 and SC5 both close on this attempt.** 7/7 ROADMAP Success Criteria verified. This is not a
generous third-try grade: the two criteria failed on inputs the old code rejected, and the new
proofs are exactly the artifact the prior report demanded and did not get twice — real
`OpenRouterGenerator` instances driven against local mock HTTP servers through
`GenerateAnswerNode::run`, asserting on `WorkflowContext` state, with mock bodies that do **not**
hardcode the field under assertion.

The phase is **not** `passed`, because five items require a human decision (§Human Verification).
None of them is an SC failure; three are contract questions the ROADMAP does not adjudicate, two are
process gates. Under the Step 9 decision tree a non-empty human-verification section forces
`human_needed` regardless of score.

---

## Re-verification Trail (gap → plan → resolution)

| Round | Gap | Prior status | Closing plan | Resolution |
|---|---|---|---|---|
| 1 | SC3 — model-only opt-in cannot produce an answer on the production path | `failed` | **06-13-PLAN.md** | **partial** — packing path fixed; `answer_basis` contract unpinned |
| 2 | SC5 — citation repair converts its own target case into a hard run failure | `partial` | **06-14-PLAN.md** | **partial** — dedup fixed; deeper adapter-ordering defect kept core clauses unreachable |
| 3 | SC3 **and** SC5 | both `partial` | **06-15-PLAN.md** | ✓ **resolved** — validator split; both proven through the real adapter |

Root cause 06-15 targeted, as diagnosed by round 2: `OpenRouterGenerator::execute_one_call` ran the
FULL grounding validator on the RAW model output, upstream of the seam that owns repair (SC5) and
the model-only basis decision (SC3). Both behaviors sat downstream of a gate that rejected their own
inputs. Independently confirmed against the pre-split source: `953b22c:openrouter.rs:792` reads
`model_output.validate_grounding_with_limits(&validation_evidence, limits)?`.

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria SC1–SC7)

| # | Truth | Status | Evidence |
|---|---|---|---|
| SC1 | Rust binary imports all production modules from the library crate; Go `main.go` symmetrically split | ✓ VERIFIED (carried forward; regression-checked) | `engine/src/main.rs` declares no `mod`; `gateway/internal/{config,engineclient,sse,telemetry}` all present |
| SC2 | One consolidated additive protobuf change with regenerated Rust and Go bindings | ✓ VERIFIED (carried forward; regression-checked) | `proto/lancet/v1/lancet.proto` — optional fields 4/5 appended, `NoticeCode` values 10-22 appended with 0-5 untouched |
| SC3 | Opted-in zero-evidence run returns `MODEL_ONLY` + notice + zero citations; flag off keeps fail-closed | ✓ **VERIFIED — closed this round** | See §1 below |
| SC4 | One retrieval path failing keeps `RETRIEVAL` basis with a per-path `RETRIEVAL_DEGRADED` notice | ✓ VERIFIED (carried forward) | `retrieve.rs:88` `RetrievalDegradedDense`, `:141` `RetrievalDegradedBm25` |
| SC5 | Citation repair normalizes, strips, emits `CITATION_REPAIRED`/`CITATION_DROPPED`, downgrades on total loss — no second provider call | ✓ **VERIFIED — closed this round** | See §2 below |
| SC6 | Bad-input matrix is an enumerated, table-driven test (gRPC and HTTP) rejecting before retrieval/provider work | ✓ VERIFIED (re-checked this round) | `engine/src/tests/bad_input_matrix.rs` — `struct Row` (`:82`), `let rows = vec![...]` 12 rows (`:147`), `for row in rows` (`:302`); HTTP half table-driven in `gateway/main_test.go` |
| SC7 | `GRAPH_UNAVAILABLE` fires on the two silent-degrade paths; source-chunk queries never require graph data | ✓ VERIFIED (carried forward) | `graph_context.rs:129`, `:175` — exactly two non-test emission sites |

**Score:** 7/7 truths verified (0 present-but-behavior-unverified)

Both newly-closed truths are behavior-dependent (state transitions), so presence + wiring would not
have sufficed. Each is backed by a named passing behavioral test, per the pre-established gate
result (`cargo test --manifest-path engine/Cargo.toml --locked` exit 0; 386 targets).

---

## 1. SC3 — is the model-only basis now ENGINE-decided?

**Ruling: YES. Closed.**

The prior report's exact complaint was that `generate.rs` validated the *unmodified* `output` and
applied `into_model_only()` only afterwards, so a model returning `answer_basis: "retrieval"` with
empty `cited_evidence_ids` died as a non-retryable `SchemaValidation` error. That ordering is gone.

`engine/src/workflow/nodes/generate.rs:147-171`:

```rust
if ctx.allow_model_only
    && output.should_treat_as_model_only(ctx.evidence_blocks.is_empty())
{
    let for_validation = output.into_model_only();
    if let Some(limits) = self.grounding_limits {
        let limits = limits.with_allow_model_only(ctx.allow_model_only);
        for_validation
            .validate_grounding_with_limits(&ctx.evidence_blocks, limits)
            ...
    }
    ctx.update_from_model_output(&for_validation);
```

`should_treat_as_model_only(no_evidence)` returns `no_evidence || basis == ModelOnly`
(`generation/mod.rs:381`), so with empty evidence the branch is entered **regardless of what the
model claimed**. `for_validation` — not `output` — is both validated and fed to
`update_from_model_output`. The engine's documented design at `generation/mod.rs:379` ("the engine —
not the model's own claim — decides the run is model-only") is now what the code does.

The adapter no longer contradicts it either. `openrouter.rs:790-797`:

```rust
let validation_view = if request.evidence.is_empty() && request.allow_model_only {
    model_output.into_model_only()
} else {
    model_output.clone()
};
validation_view.validate_output_shape_with_limits(limits)?;
Ok(model_output)
```

Shape-only, on a model-only-corrected view, returning the **raw** output to the caller.

### CRITICAL CHECK — does the proof test assert on `WorkflowContext`?

**YES.** `openrouter_node_optin_empty_evidence_retrieval_basis_still_yields_model_only`
(`engine/src/tests/workflow_phase5_production.rs:1681-1817`) ends with:

```rust
assert_eq!(ctx.answer_basis, v1::AnswerBasis::ModelOnly);
assert!(ctx.citations.is_empty());
assert!(ctx.structured_citations.is_empty());
assert!(ctx.notices.iter().any(|n| n.typed_code == v1::NoticeCode::ModelOnly as i32));
```

Every assertion is on `WorkflowContext`, not on the generator's return value. It constructs a real
`OpenRouterGenerator::new_with_config` against a `TcpListener`-backed mock server, runs
`check_supported_parameters()`, then `generate_node.run(&mut ctx, &cancel)`. The mock chat body is:

```json
{ "answer": "This is a model-only answer.", "cited_evidence_ids": [],
  "answer_basis": "retrieval", "notices": [], "warnings": [] }
```

`"retrieval"` — the field under assertion is **not** hardcoded to the expected value. This is the
precise input the prior report said no test exercised, and it is the defect class
`PackingTestGenerator` (which hardcoded `AnswerBasis::ModelOnly`) could not detect.

Supporting fix confirmed: `prompt.rs:218-223` now ends *"Set answer_basis to model_only with an empty
cited_evidence_ids list."* — the sentence the prior report flagged as dropped.

### Flag-off half (see §4 for the WR-03 ruling)

`openrouter_node_model_only_flag_off_stays_fail_closed` proves the empty-evidence flag-off path
still fails closed. SC3's flag-off clause is satisfied.

---

## 2. SC5 — are the three previously-unreachable clauses now reachable?

**Ruling: YES, all three. Closed.**

The four marker checks were extracted into `ModelOutput::validate_marker_grounding`
(`generation/mod.rs:317-...`) and now run only downstream, post-repair, at `generate.rs:261` via the
recomposed `validate_grounding_with_limits`. I verified all three inputs are genuinely new
reachability by re-deriving each against the pre-split validator myself (`extract_inline_markers` is
digit-only and skips `[ 7 ]`; set equality at the old `mod.rs:355-364`; known-ID membership at
`333-341` / `344-353`):

| SC5 clause | Test | Pre-split adapter verdict | Post-split `WorkflowContext` assertion |
|---|---|---|---|
| standalone near-miss `[ 7 ]`, no healthy companion in the answer text | `openrouter_node_standalone_near_miss_marker_is_repaired` (`:1820-1970`) | **REJECTED** — strict `inline_set = {}` ≠ `seen_cited = {"[7]"}` | `ctx.citations == ["[7]"]`; `ctx.answer.contains("[7]")`; `!ctx.answer.contains("[ 7 ]")`; `CitationRepaired` notice present |
| strict-visible unresolvable `[9]` | `openrouter_node_strict_visible_unresolvable_marker_is_dropped` (`:1973-2121`) | **REJECTED** — `inline marker '[9]' is not in packed evidence` | `ctx.citations == ["[1]"]`; `!ctx.answer.contains("[9]")`; `CitationDropped` notice present |
| total citation loss → basis downgrade | `openrouter_node_total_citation_loss_downgrades_basis_to_model_only` (`:2124-2276`) | **REJECTED** — `cited_evidence_id '[9]' is not in packed evidence` | `ctx.citations.is_empty()`; `ctx.answer_basis == ModelOnly`; `CitationDropped` **and** `BasisReconciled` notices present |
| no second provider call | same test | — | `assert_eq!(chat_calls.load(SeqCst), 1)` — and in *this* test `chat_calls_server` **is** cloned and **is** incremented, so the assertion is live. Independently: exactly four non-test `.generate()` sites remain (`generate.rs:114`, `:140`; `workflow/mod.rs:302`, `:307`) — first attempt + retry on each of the two paths |

All four assert on `WorkflowContext`. All drive a real `OpenRouterGenerator` against a mock HTTP
server. No `FakeGenerator`, no `PackingTestGenerator` — the prohibited doubles in
`06-15-PLAN.md must_haves.prohibitions`. No mock body hardcodes the asserted field (all three carry
`"answer_basis": "retrieval"`, and every asserted outcome is produced by engine logic).

The downgrade mechanism traced end to end: `total_drop = !markers.is_empty() &&
repaired_citations.is_empty()` (`generate.rs:241`) → `for_validation = ...into_model_only()` →
`effective_allow = ctx.allow_model_only || total_drop` (`:255`) → re-entry via
`with_answer_and_citations` (basis untouched) → `update_from_model_output` reconciles
`weaker_basis(Retrieval, ModelOnly) = ModelOnly` and emits `BasisReconciled`
(`workflow/mod.rs:178-196`).

Prohibition "MUST NOT invent, substitute or guess a citation target" (test-tier, `status: resolved`)
— **enforcement evidence found**, not assumed: `resolve_markers` (`citations.rs:171-198`) drops on
zero candidates *and* on ≥2 candidates, pinned by `unmatched_marker_reports_dropped` and
`tie_reports_dropped_not_assigned` (`citations.rs` test module).

---

## 3. T-06-15-03 — does the accepted residual preserve SC5's binding property?

**Ruling: SC5's four enumerated clauses still hold, so this does not fail SC5. But the residual is
REAL, it is BROADER than the SUMMARY records, and the property it trades away has no test. Routed to
human decision, not silently accepted.**

I did not restate the disposition; I checked it against the pre-split source.

**The residual is real.** At `953b22c:openrouter.rs:534,792` the adapter validated markers against
`validation_evidence` — the third element of `pack_openrouter_messages`, which is
`packed_evidence.evidence`, **the subset actually sent to the model**
(`openrouter.rs:297` returns it). `pack_evidence_and_graph_prompt` genuinely truncates: it computes
`allowed_evidence_tokens = max_prompt_tokens - (answer_token_budget + base_tokens)`
(`prompt.rs:376-377`) and packs only what fits. So yes — **a surviving citation can now point at
content that was never in the prompt the model saw.** A marker naming a retrieved-but-truncated
block `[N]` resolves against `ctx.evidence_blocks`, survives, and its excerpt is shipped to the
client verbatim by `resolve_citations(&ctx.citations, &ctx.evidence_blocks)`. Pre-split that same
answer was rejected `SchemaValidation`.

**The residual is broader than "the repair path."** 06-15-SUMMARY.md frames this as a citation-repair
consequence. It is not. Today the adapter discards the packed subset entirely — `let (system_msg,
user_msg, _validation_evidence) = pack_openrouter_messages(...)` (`openrouter.rs:534`) — and **every**
downstream gate binds to `ctx.evidence_blocks`: `generate.rs:154` (branch 1, model-only),
`generate.rs:261` (branch 2, repair-enabled), `generate.rs:322` (repair-**disabled**), and
`workflow/mod.rs:321,325` (inline remainder). No code path anywhere validates markers against the
packed subset. The widening applies with `citation_repair_enabled = false` too. That understatement
in the SUMMARY is corrected here.

**Why this is not an SC5 failure.** SC5's contract is "normalizes near-miss markers locally, strips
anything still unresolved, emits CITATION_REPAIRED/CITATION_DROPPED, and downgrades the basis if all
grounding is lost — no second provider call (D-14)." It states no packed-subset binding, and every
surviving citation still binds to a **real retrieved chunk** — `resolve_markers` drops rather than
guesses, and ties drop too. The clause list is satisfied.

**Why it still routes to a human.** 06-15-PLAN.md tags this exact must_have `verification: backstop`.
Step 5b forbids inferring a backstop truth from presence and wiring; it needs a passing held-out test
or directly observed behavior. **There is none** — no test in the repository exercises a
retrieved-but-truncated block, and all four new proofs use single-block or empty evidence sets, so
`ctx.evidence_blocks == packed_evidence` holds trivially in every one of them. Marked
`insufficient_spec` → human-verification item, and recorded advisorily as
`coincidental_reliance: undeclared-precondition`.

The D-84 must_have ("the repair-DISABLED branch of GenerateAnswerNode is untouched;
`citation_repair_disabled_fails_exactly_as_before` passes unedited; the completeness check still
runs when `grounding_limits` is `Some`") is **VERIFIED as written** — all three sub-claims hold
(`generate.rs:317-352` is unchanged; the `[9999]` message and the `resolved_citations.len() !=
ctx.citations.len()` check are both intact). It does not claim the *composed strictness* of the
repair-off path is unchanged, so the widening above is not a violation of it.

---

## 4. WR-03 — is SC3's flag-off half adequately proven?

**Ruling: YES, adequately proven — with the caveat that the specific `chat_calls == 0` assertion is
dead code and should be wired or deleted.**

The vacuity is real and I confirmed it independently: in
`openrouter_node_model_only_flag_off_stays_fail_closed` (`workflow_phase5_production.rs:2280-2388`)
only `models_calls_server` is cloned into the server thread; there is no `chat_calls_server` and no
`fetch_add` on the chat branch (the thread has no chat branch at all). `chat_calls` is created at
zero and never touched, so `assert_eq!(chat_calls.load(SeqCst), 0)` cannot fail. All four sibling
tests do clone and increment it. Confirmed WARNING.

**But the flag-off half is proven by the test's other assertions, which are substantive:**

```rust
assert_eq!(err.kind, v1::NodeErrorKind::LlmGenerationFailed);
assert!(err.message.contains("prompt assembly failed"), ...);
```

`"prompt assembly failed"` has exactly one producer in the entire tree — `openrouter.rs:285`, inside
`pack_openrouter_messages`, on the `PromptAssemblyError` arm. I grepped for it: two other hits, both
in this test's own assertion. That string can only be produced *before* the chat payload is built or
dispatched, so the assertion pins the fail-closed point upstream of chat dispatch on its own, with
no reliance on the counter. Reinforcing it, the mock server loops `while conn_count < 1` and that one
connection is consumed by `check_supported_parameters()`'s `GET /models`; an attempted `POST /chat`
would have failed to connect and surfaced as a `ProviderError`, not as this message.

Mechanism traced: with `allow_model_only = false` and empty evidence, `pack_openrouter_messages`
skips the model-only branch (`openrouter.rs:263`, requires `allow_model_only`), calls
`pack_evidence_and_graph_prompt`, which returns `PromptAssemblyError::EmptyEvidence`
(`prompt.rs:349-351`), mapped to `InvalidRequest` — not in the retryable set — terminal. Unchanged
from before the delta.

**Materiality to SC3: none.** The dead counter is redundant belt-and-braces on an assertion that
already holds. The genuinely material flag-off issue is a *different* one (CR-02) and is routed to
human decision — see below.

---

## The CR-02 flag-off relaxation — why it is a human decision, not an SC3 gap

Code review CR-02 (orchestrator-downgraded to info) is correct on the facts, and I re-traced them:
with `allow_model_only = false`, evidence `["[1]"]` present, and a model answer citing only an
unresolvable `[9]`, the run now returns `Ok` with `ANSWER_BASIS_MODEL_ONLY`, because
`effective_allow = ctx.allow_model_only || total_drop` (`generate.rs:255`) grants the model-only
relaxation to a caller that explicitly opted out. Before this delta the adapter rejected that exact
exchange.

**It is not an SC3 failure, and the warrant is in SC3's own text, not in the orchestrator's ruling.**
SC3 closes with the parenthetical **`(D-10, D-11, D-12)`**; its antecedent is *"When both retrieval
paths fail or evidence is absent."* The total-drop reconciliation path is governed by **D-18**, which
ROADMAP groups with `DEBT-RAG-03`/SC5 on plan 06-11 (*"Citation repair (normalize-then-strip),
conservative basis reconciliation … (D-14/D-18/…)"*). The decision-record citations partition the two
paths explicitly, and the CR-02 case has evidence *present*, so it falls outside SC3's antecedent on
both counts.

**But no SC governs it either.** A newly-production-reachable relaxation of a fail-closed default
that exists only as an incidental consequence of an `||`, with no test pinning the chosen semantics,
is exactly the class of thing that needs an explicit decision rather than a verifier's silent pass.
Routed to human verification.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `engine/src/generation/mod.rs` | `validate_output_shape_with_limits` + `validate_marker_grounding`; `validate_grounding_with_limits` retained as their composition | ✓ VERIFIED | Both public methods present; composition at `:373-379` is `shape?; markers`. Error strings preserved verbatim |
| `engine/src/generation/openrouter.rs` | Shape-only adapter gate on a model-only-corrected view; raw output returned | ✓ VERIFIED | `:790-799`. Sole `validate_*` call in the adapter is `validate_output_shape_with_limits` |
| `engine/src/workflow/nodes/generate.rs` | Branch 1 validates `output.into_model_only()` | ✓ VERIFIED | `:150-166` — `for_validation` built, validated, and passed to `update_from_model_output` |
| `engine/src/workflow/mod.rs` | `run_inline_prompt_generation_remainder` grounding gate + `WorkflowDependencies::grounding_limits` | ✓ VERIFIED + WIRED | Field at `:225`, default at `:240`, gate at `:313-330` before any `ctx` mutation, `events::node_failed` on rejection. Production value supplied at `service.rs:106` |
| `engine/src/prompt.rs` | `model_only_system_policy()` instructs `answer_basis: model_only` with empty citations | ✓ VERIFIED | `:218-223` — final sentence present and reaches the wire as `messages[0]` via `openrouter.rs:264` |
| `engine/src/tests/workflow_phase5_production.rs` | Five node-level mock-server tests driving the real `OpenRouterGenerator` | ✓ VERIFIED | `:1681`, `:1820`, `:1973`, `:2125`, `:2280` — all five present, all construct `OpenRouterGenerator::new_with_config`, all assert on `WorkflowContext` (test 5 asserts on the returned `NodeError`, correctly, since it is a failure test) |
| `engine/src/tests/bad_input_matrix.rs` | Table-driven bad-input matrix (SC6) | ✓ VERIFIED (re-checked) | `struct Row` `:82`; 12-row `vec![]` `:147`; `for row in rows` `:302` |
| `proto/lancet/v1/lancet.proto` + bindings | Additive-only wire change | ✓ VERIFIED (carried forward) | Unchanged by this delta |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `openrouter.rs` | `generation/mod.rs` | shape-only validation | ✓ WIRED | `:797` `validate_output_shape_with_limits`; zero `validate_marker_grounding`/`validate_grounding_with_limits` calls remain in the adapter |
| `generate.rs` | `generation/mod.rs` | post-repair composed validation owns the four marker checks | ✓ WIRED | `:154`, `:261`, `:322` — all three branches |
| `workflow/mod.rs` | `generation/mod.rs` | remainder gate on the published inline path | ✓ WIRED | `:321`, `:325` — both the model-only and grounded arms |
| `workflow_phase5_production.rs` | `openrouter.rs` | mock-server node tests constructing the real adapter | ✓ WIRED | 5 new tests, all real `OpenRouterGenerator` |
| `AnswerBasis::ModelOnly` decision | engine, not model self-report | validator ordering | ✓ **CORRECTED** (was ✗ INVERTED) | `generate.rs:150,166` |
| `GenerateAnswerNode` repair pass | `OpenRouterGenerator` output | `Ok(output)` arm | ✓ **WIRED for standalone repairable inputs** (was ✗ NOT WIRED) | Adapter no longer runs marker checks |
| marker checks | packed evidence subset | `_validation_evidence` | ✗ **NOT WIRED — intentional (T-06-15-03)** | `openrouter.rs:534` discards it; all gates bind to `ctx.evidence_blocks`. See §3 |

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `GenerateAnswerNode` | `ctx.answer_basis = ModelOnly` (opt-in path) | `output.into_model_only()` at `:150` | **Yes** — engine-decided, independent of the model's claim | ✓ FLOWING (was ⚠️ STATIC) |
| `GenerateAnswerNode` | `ctx.notices` (`CITATION_REPAIRED`) | `Resolution::Repaired` over real answer text | **Yes** — standalone near-miss proven | ✓ FLOWING (was ⚠️ PARTIAL) |
| `GenerateAnswerNode` | `ctx.notices` (`CITATION_DROPPED`) | `Resolution::Dropped` | **Yes** — strict-visible `[9]` proven | ✓ FLOWING (was ⚠️ PARTIAL) |
| `GenerateAnswerNode` | `ctx.answer_basis = ModelOnly` (total-drop) | `total_drop` → `into_model_only()` → reconciliation | **Yes** — proven end to end | ✓ FLOWING (was ✗ DISCONNECTED) |
| `GenerateAnswerNode` | `ctx.structured_citations` excerpts | `resolve_citations(&ctx.citations, &ctx.evidence_blocks)` | Yes, but from the **full retrieved set**, not the packed subset | ⚠️ See §3 — human decision |

## Behavioral Spot-Checks

Regression gates were pre-established by the orchestrator and are relied upon, not re-run (Rust 386
targets exit 0; Go all packages ok; `scripts/engine-test-targets.sh` "All 7 Rust test target
invariants verified successfully"). The checks below are the ones that discriminate — they read test
bodies rather than names, since a green suite was not evidence in either prior round.

| Behavior | Check | Result | Status |
|---|---|---|---|
| SC5 tests exercise the production adapter | `grep -c OpenRouterGenerator` in the new tests | 5 constructions in `workflow_phase5_production.rs:1681-2388` | ✓ PASS — was `0` in the prior round |
| SC3 opt-in mock does **not** hardcode the asserted field | read `:1731-1737` | body carries `"answer_basis": "retrieval"` | ✓ PASS |
| SC3 opt-in test asserts on `WorkflowContext`, not the generator return | read `:1806-1813` | `ctx.answer_basis`, `ctx.citations`, `ctx.notices` | ✓ PASS — the critical check |
| SC5 near-miss input is genuinely standalone | read `:1866-1872` | answer `"Padded standalone marker [ 7 ] in text."` — no exact `[7]` companion in the text | ✓ PASS — adapter-rejected pre-split |
| SC5 total-drop asserts no second call, live counter | read `:2274` + server thread | `chat_calls` cloned **and** incremented; asserts `== 1` | ✓ PASS |
| SC3 flag-off `chat_calls == 0` assertion | read `:2293-2296`, `:2386` | counter never cloned, never incremented | ✗ **VACUOUS** — WR-03; SC3 still proven by the `"prompt assembly failed"` assertion (§4) |
| `"prompt assembly failed"` has a single upstream producer | `grep -rn` across `engine/src` | one non-test hit, `openrouter.rs:285` | ✓ PASS |
| No packed-subset binding survives anywhere | `grep` all `validate_*` call sites | all bind `&ctx.evidence_blocks`; `_validation_evidence` discarded | ⚠️ CONFIRMED — §3 |
| `resolve_markers` never guesses | read `citations.rs:171-198` + tests | drops on 0 candidates and on ties; `tie_reports_dropped_not_assigned` pins it | ✓ PASS |
| Non-test `.generate()` sites unchanged at 4 | `grep -rn "\.generate("` excluding tests | `generate.rs:114,140`; `workflow/mod.rs:302,307` | ✓ PASS (D-14) |
| Every non-test generator path has a downstream gate | enumerate the 4 sites | both paths gated (`generate.rs:154/261/322`, `workflow/mod.rs:321/325`) | ✓ PASS |
| Only one non-test `GenerateAnswerNode::new` | `grep -rn` excluding tests | `service.rs:149`, and it calls `.with_settings(...)` → `grounding_limits: Some` | ✓ PASS (see WR note) |
| SC6 matrix is genuinely table-driven | read `bad_input_matrix.rs:82,147,302` | `struct Row`, 12-row `vec!`, `for row in rows` | ✓ PASS |

## Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` exist in this repository and no Phase 6 plan or
success criterion declares a probe.

## Requirements Coverage

All 15 plans declare exactly `requirements: [RAG-03]`. `REQUIREMENTS.md:52` scopes it: *"DEBT-RAG-01,
DEBT-RAG-03, DEBT-RAG-05 and DEBT-RAG-06 clauses → Phase 06; DEBT-RAG-04 (index rebuild-and-swap) →
Phase 06.1."* Every ID in the phase requirement line is accounted for; no orphans.

| Requirement | Clause | Source Plans | Status | Evidence |
|---|---|---|---|---|
| RAG-03 | DEBT-RAG-01 (retrieval-path degradation) | 06-09 | ✓ SATISFIED | `retrieve.rs:88,141` (SC4) |
| RAG-03 | DEBT-RAG-01 (model-only answers) | 06-10, 06-13, 06-15 | ✓ **SATISFIED — was BLOCKED** | Engine-decided basis, §1 |
| RAG-03 | DEBT-RAG-03 (citation repair) | 06-11, 06-14, 06-15 | ✓ **SATISFIED — was BLOCKED** | All four clauses reachable and proven, §2 |
| RAG-03 | DEBT-RAG-05 (bad-input matrix) | 06-12 | ✓ SATISFIED (re-checked) | `bad_input_matrix.rs` table-driven; HTTP half in `gateway/main_test.go` |
| RAG-03 | DEBT-RAG-06 (graph-unavailable notice) | 06-08 | ✓ SATISFIED | `graph_context.rs:129,175` (SC7) |
| RAG-03 | DEBT-RAG-04 (index rebuild-and-swap) | — | ↪ OUT OF SCOPE | Assigned to Phase 06.1 by `REQUIREMENTS.md:52`; correctly unclaimed |

**Net:** all four in-scope RAG-03 clauses are now satisfied. **RAG-03 must nonetheless remain
unchecked in `REQUIREMENTS.md` while this phase's status is `human_needed`** — the checkbox flips
only after the human-verification items are resolved and the phase completes.

### Specless-probe edges (prohibition, judgment-tier, `flagged-unverified`)

06-15-PLAN.md carries four "flagged assumption" must_haves declaring the unclassified RAG-03,
DEBT-RAG-01 and DEBT-RAG-06 probe edges, and the DEBT-RAG-05 concurrency edge, as **unresolved and
not treated as covered**. No `06-SPEC.md` exists. Verified as declared: this plan does not claim
them, and this report does not absorb them into a pass. They are carried, not closed, and are
routed to human verification (item 6) so they reach the UAT sink rather than dying in prose.

**Disposition of the other three prohibitions** — so a frontmatter-only reader can tell
resolved-by-verifier from silently-skipped:

| Prohibition | Plan status | Verifier disposition |
|---|---|---|
| P1 — MUST NOT invent/substitute/guess a citation target (test-tier) | `resolved` | ✓ **RESOLVED, enforcement evidence found.** `resolve_markers` (`citations.rs:171-198`) drops on zero candidates and on ties; pinned by `unmatched_marker_reports_dropped` and `tie_reports_dropped_not_assigned`. Not fail-closed-flagged — the wired negative test exists |
| P2 — MUST NOT leave a non-test path reaching a `Generator` without a named downstream grounding gate | `flagged-unverified` | ✓ **RESOLVED by codebase evidence this round.** Exactly four non-test `.generate()` sites (`generate.rs:114,140`; `workflow/mod.rs:302,307`); both paths gated (`generate.rs:154/261/322`, `workflow/mod.rs:321/325`). Enumeration re-run independently, not taken from the review. Not carried forward |
| P3 — MUST NOT accept a test double as proof for SC3 or SC5 | `flagged-unverified` | ✓ **RESOLVED by codebase evidence this round.** All five new proofs construct a real `OpenRouterGenerator`; zero `FakeGenerator`/`PackingTestGenerator` use among them. Not carried forward |
| P4 — MUST NOT treat the specless-probe edges as covered | `flagged-unverified` | ⚠️ **CARRIED — human decision required** (human_verification item 6) |

## Anti-Patterns Found

Debt-marker gate: **clean.** No `TBD` / `FIXME` / `XXX` in any of the nine files 06-15 touched.

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `engine/src/tests/workflow_phase5_production.rs` | 2293, 2386 | `chat_calls` counter never cloned into the server thread, never incremented; the assertion reading it cannot fail | ⚠️ Warning (WR-03) | Dead assertion. SC3's flag-off half is proven by the sibling `"prompt assembly failed"` assertion — see §4. Wire the counter or delete it |
| `engine/src/workflow/nodes/generate.rs` | 255 | `effective_allow = ctx.allow_model_only \|\| total_drop` — flag-off callers get the model-only relaxation | ⚠️ Warning (CR-02) | Real, newly production-reachable; no SC governs it → human decision |
| `engine/src/workflow/nodes/generate.rs` | 238-284 | `answer_basis = MODEL_ONLY` reachable with no `NOTICE_CODE_MODEL_ONLY`, unlike the two sibling paths | ⚠️ Warning (CR-01) | Cross-path invariant break; SC5's text does not require the notice and `BASIS_RECONCILED` is machine-readable → human decision |
| `engine/src/generation/openrouter.rs` | 534 | `_validation_evidence` — the packed subset is computed and discarded | ⚠️ Warning (T-06-15-03 / WR-02) | Marker binding widened to the full retrieved set on **every** path. See §3 |
| `engine/src/workflow/nodes/generate.rs` | 15, 151 | `grounding_limits: Option<GroundingLimits>` — a `GenerateAnswerNode` built without `.with_settings(..)` now has **no** marker validation anywhere, since the adapter no longer provides a backstop | ⚠️ Warning (WR-01) | Not production-reachable: the sole non-test construction (`service.rs:149`) always calls `.with_settings(..)`. Latent fail-open for any future constructor; the sibling `WorkflowDependencies.grounding_limits` was made non-`Option` in this same commit |
| `engine/src/tests/workflow_phase5_production.rs` | 1681-2388 | ~700 lines of mock-server scaffolding duplicated verbatim five times | ⚠️ Warning (WR-04) | Mechanism by which WR-03 occurred |
| `engine/src/generation/openrouter.rs` | 245 | `#[allow(clippy::too_many_arguments)]` instead of `#[expect(..)]` | ⚠️ Warning | `rust-guidelines.md` M-LINT-OVERRIDE-EXPECT. Carried forward |
| `scripts/engine-test-targets.sh` | 7, 29 | Hardcoded developer home path; unguarded pipeline under `set -e` without `pipefail` | ⚠️ Warning | Carried forward (WR-11); this delta changed only the counts |
| `engine/src/generation/mod.rs` | ~435 | `GenerationRequest::system_policy` is `pub`, serialized, `PartialEq`-compared, read by no production code | ⚠️ Warning | Carried forward (WR-01, prior round). Behavior intact via `base_system_policy()` in the packed prompt |

## Human Verification Required

Five items — three contract decisions surfaced by this delta, two process gates. Detail in the
frontmatter `human_verification` block; summarized:

1. **CR-02 — flag-off semantics on the D-18 total-drop path.** Decide whether the downgrade is
   intentionally flag-independent, or scope the relaxation to the disclosure and keep the hard
   failure. Pin the chosen semantics with a test; today it exists only as a consequence of an `||`.
2. **T-06-15-03 — truncated-block citation binding** (`verification: backstop`, `insufficient_spec`).
   Decide whether a marker naming a retrieved-but-truncated block should resolve (today it does) or
   fail closed (pre-split). No test covers this and none can be inferred from wiring.
3. **CR-01 — `MODEL_ONLY` basis without a `MODEL_ONLY` notice** on the total-drop path. Add the
   notice, or record `BASIS_RECONCILED` as the intended disclosure.
4. **Security gate open.** `workflow.security_enforcement` is active and no `06-SECURITY.md` exists
   → `/gsd-secure-phase 6`.
5. **Validation stale.** `06-VALIDATION.md` is `status: draft`, `nyquist_compliant: false`, dated
   2026-08-20 — it predates plans 06-08..06-15, so Nyquist coverage for the new work is not
   established → `/gsd-validate-phase 6`.

## A note on `Mode: mvp`

ROADMAP marks Phase 6 `**Mode:** mvp`, but the phase goal is a deliverables statement, not an
`As a … I want to … so that …` User Story (06-15-PLAN.md carries a proper User Story internally). As
in the prior round, MVP-mode refusal is not applied: this is a scoped re-verification against an
explicit seven-criterion contract. Recorded as a documentation discrepancy, not a gap.

## The D-79 redistribution note is NOT a Step-9b deferral

ROADMAP's note (*"SC1 → 6.2; SC2 and SC4 → 6.3; SC3 → 6.4; SC5 and SC6 → 6.1; SC7 → 6 and 6.1"*)
maps the **original, pre-split** criteria, not the seven currently listed. Proof: the note sends
"SC1 → 6.2" (OpenTelemetry), but the current SC1 is the Rust/Go module graph. Phase 6.1's criteria
are index rebuild-and-swap and `DEBT-BU-*`; Phase 6.4's are the docs suite — neither mentions
model-only answers or citation repair. Already adjudicated in `.planning/STATE.md`. **No deferrals
recorded, and none would have been recommended.**

---

## Summary

**The phase goal is achieved.** All seven Success Criteria hold. SC3 and SC5 — failed or partial
across two prior rounds — are closed by 06-15, and closed on the terms the prior report set: real
provider adapter, mock HTTP server, assertions on `WorkflowContext`, mock bodies that do not
hardcode the field under test, and inputs independently confirmed to have been rejected by the
pre-split validator. The root cause the prior round diagnosed — a fail-closed gate sitting upstream
of the seam that exists to repair its own inputs — is genuinely removed, and it was removed in the
safe order: the published inline remainder path was gated (`workflow/mod.rs:313-330`) before the
adapter was reduced, so at no commit did a validation-free published generation path coexist with a
shape-only adapter gate.

The phase is `human_needed` rather than `passed` because moving that gate traded away a property
nothing now tests: markers used to bind to the packed subset the model actually saw, and now bind to
the full retrieved set. That trade is defensible and was declared in the plan — but it was declared
`verification: backstop`, it is broader than 06-15-SUMMARY.md records (it applies on every
generation path, including repair-disabled), and it deserves an explicit human ruling rather than a
verifier's inference. Two adjacent contract questions (CR-01, CR-02) and two process gates
(security, validation) round out the list.

**Recommended next action:** resolve the five human-verification items, then `/gsd-secure-phase 6`
and `/gsd-validate-phase 6`. Do **not** open a fourth gap-closure round for SC3 or SC5 — there is no
unmet clause in either.

---

_Verified: 2026-08-22T21:05:00Z_
_Verifier: Claude (gsd-verifier)_
_Supersedes the 2026-08-22T18:40:00Z report; the full gap → plan → resolution trail across all three rounds is preserved in the Re-verification Trail section above._
