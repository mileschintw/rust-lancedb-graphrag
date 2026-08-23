---
phase: 06-observability-evaluation-polish
reviewed: 2026-08-22T14:20:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - engine/src/generation/mod.rs
  - engine/src/generation/openrouter.rs
  - engine/src/prompt.rs
  - engine/src/service.rs
  - engine/src/tests/workflow_phase5.rs
  - engine/src/tests/workflow_phase5_production.rs
  - engine/src/workflow/mod.rs
  - engine/src/workflow/nodes/generate.rs
  - scripts/engine-test-targets.sh
findings:
  critical: 0
  warning: 6
  info: 7
  total: 13
status: issues_found
orchestrator_ruling:
  applied: true
  ruled_at: 2026-08-22T00:00:00Z
  downgraded:
    - id: CR-01
      from: critical
      to: info
      reason: >-
        Applies the branch-1 (SC3) notice contract to the branch-2 (D-18) total-drop path.
        06-15-PLAN.md Task 1 explicitly instructs "Leave the existing model-only notice block
        (NoticeCode::ModelOnly) and its condition unchanged", and must_haves specifies a
        BASIS_RECONCILED notice — not MODEL_ONLY — for the total-drop path. Spec-conformant.
    - id: CR-02
      from: critical
      to: info
      reason: >-
        No plan contradiction exists. must_haves requires the total-drop downgrade "even with
        allow_model_only false"; Task 3 requires "the downgrade must not depend on the SC3
        opt-in"; the P1b design table documents
        `effective_allow = ctx.allow_model_only || total_drop` as the intended construction.
        The must_have the reviewer cited as conflicting ("with the flag off, today's fail-closed
        behavior is unchanged") is scoped to the empty-evidence branch-1 path (D-10/D-11/D-12),
        not the branch-2 post-repair total-drop path (D-18/DEBT-RAG-03). Spec-conformant.
  confirmed:
    - id: WR-03
      severity: warning
      note: >-
        Orchestrator-verified real. `chat_calls` is never cloned into the server thread and never
        incremented in this test, so `assert_eq!(chat_calls, 0)` is vacuous. Severity held at
        warning, NOT escalated: the test's other assertions are substantive — it asserts
        `Err(LlmGenerationFailed)` whose message contains "prompt assembly failed", which pins the
        fail-closed point upstream of chat dispatch, and the mock server accepts exactly one
        connection (consumed by check_supported_parameters) so an attempted POST /chat would have
        surfaced as a connection error instead. SC3's flag-off half remains proven; the dead
        counter and its assertion should be wired or removed.
---

# Phase 6 Gap-Closure Delta (plan 06-15): Code Review Report

**Reviewed:** 2026-08-22
**Depth:** standard
**Files Reviewed:** 9 (delta of `30fdc46^..84baf5e` — commits `30fdc46`, `4fb4859`, `84baf5e`)
**Status:** issues_found

## Summary

This is a targeted re-review of the third SC3/SC5 gap-closure delta (plan 06-15), which relocated
grounding *marker* validation out of `OpenRouterGenerator::execute_one_call` and into the workflow
layer by splitting `validate_grounding_with_limits` into `validate_output_shape_with_limits`
(adapter) + `validate_marker_grounding` (downstream). Scope was pinned to the nine files the three
commits touched.

> **`files_reviewed: 9` is a delta scope, not a coverage regression.** The phase's full 57-file scope
> was reviewed at `195edb2`; the eight-file gap-closure delta was reviewed at `953b22c`. All 25
> prior findings (7 from the `953b22c` round + its 18-row full-scope table) are dispositioned in the
> **Carry-Forward From Prior Round** section below and are not counted in the frontmatter totals.

### What genuinely closed

**Prior CR-01 (SC5 repair unreachable) is RESOLVED, and the reachability proof is real.** I traced
each of the three new SC5 mock bodies against the *pre-split* adapter and confirmed every one was
rejected before repair could run:

| New test | Mock body | Pre-split adapter rejection |
|---|---|---|
| `openrouter_node_standalone_near_miss_marker_is_repaired` | answer `"Padded standalone marker [ 7 ] in text."`, cited `["[7]"]` | `extract_inline_markers` (strict, digit-only) does not match `[ 7 ]` → `inline_set == {}` ≠ `{"[7]"}` → set-equality mismatch (`mod.rs:361-370`) |
| `openrouter_node_strict_visible_unresolvable_marker_is_dropped` | answer `"...healthy [1] and unresolvable [9]."`, cited `["[1]"]` | inline marker `[9]` not in packed evidence (`mod.rs:352-358`) |
| `openrouter_node_total_citation_loss_downgrades_basis_to_model_only` | answer `"Answer citing only unresolvable [9]."`, cited `["[9]"]` | `cited_evidence_id '[9]' is not in packed evidence` (`mod.rs:341-347`) |

Post-split the adapter runs shape checks only (`openrouter.rs:787-797`), so all three inputs now
reach `GenerateAnswerNode` branch 2 and are repaired/dropped as designed. All five new tests drive a
real `OpenRouterGenerator::new_with_config` against a `TcpListener`-backed mock server through
`GenerateAnswerNode::run` and assert on `WorkflowContext`; none of the five uses `FakeGenerator` or
`PackingTestGenerator`. Measured, not inferred: `grep -c validate_marker_grounding
engine/src/generation/openrouter.rs` = 0, `grep -c validate_output_shape_with_limits
engine/src/generation/openrouter.rs` = 1, `grep -c OpenRouterGenerator
engine/src/tests/workflow_phase5_production.rs` = 7. The file's ten pre-existing
`FakeGenerator`/`PackingTestGenerator` references belong to older tests outside this delta and are not
offered as SC3/SC5 proof.

**Prior CR-02 (SC3 model-only contingent on the model guessing) is RESOLVED — both halves.**
`prompt.rs:221` now appends *"Set answer_basis to model_only with an empty cited_evidence_ids list."*,
and `generate.rs:150-166` builds `for_validation = output.into_model_only()`, validates **that**
binding, and passes `&for_validation` to `update_from_model_output`. The engine, not the model,
decides. `openrouter_node_optin_empty_evidence_retrieval_basis_still_yields_model_only` proves it
honestly: its mock body declares `"answer_basis": "retrieval"` with `cited_evidence_ids: []`, so
reading the body does not reveal the asserted basis. The adapter also returns the **raw**
`model_output` (`openrouter.rs:798`), not the corrected view, so the node owns the decision.

**Fail-open enumeration verified complete.** I did not take the plan's two-surface claim on faith:

- `grep "\.generate("` across non-test code returns exactly four call sites in two functions:
  `generate.rs:114` / `:140` and `workflow/mod.rs:302` / `:307`. D-14's "no second provider call"
  clause holds.
- `grep "update_from_model_output"` across non-test code returns exactly four mutation sites:
  `generate.rs:166`, `:282`, `:334` and `workflow/mod.rs:353`. There is no fifth surface writing
  provider text into `WorkflowContext`.
- Direct `ctx` field writes of `answer` / `citations` / `answer_basis` / `structured_citations`
  outside `update_from_model_output` are confined to `workflow/mod.rs:358` and `generate.rs:295, 355`
  — all downstream of a gate on their own branch.
- Provider text *egress* (`events::answer_chunk`) has exactly two non-test emitters:
  `workflow/mod.rs:368`, which now fires after the Task-1 gate, and `runner.rs:368`, which fires only
  in the `Ok(())` arm of `node.run(..)` — i.e. after the node's validation returned success.

So there is **no third ungated path** in the sense the plan enumerated. The residual gap is
conditional, not structural, and is WR-01 below.

**The Task-1 remainder gate is correctly placed.** `workflow/mod.rs:311-350`: limits are built from
`deps.grounding_limits.with_allow_model_only(ctx.allow_model_only)` (wired in `service.rs:106` from
`effective_settings.grounding_limits()`), validation runs *before* the first `ctx` mutation, and the
failure path emits `events::node_failed(name_gen, ..)` and returns `Err`. It mirrors branch 1 of the
node exactly. No partial write is possible.

**The test-gate arithmetic is self-consistent and empirically confirmed.** `351 + 0 + 18 + 0 + 17 =
386` matches `scripts/engine-test-targets.sh:56-89`, and I measured the library count rather than
trusting the pin: `cargo test --lib -- --list` reports `351 tests, 0 benchmarks`. All three library
constants moved by the same delta (+6).

### Where it still breaks

Two critical defects, and they share one root cause: **moving the gate downstream did not just make
the repair pass reachable — it made the `citation_repair` total-drop branch reachable, and that
branch violates the `allow_model_only = false` opt-out.** Before this delta no `OpenRouterGenerator`
run could reach `total_drop` (every input that produces it was rejected at the adapter's cited- or
inline-membership check). After it, a run with the SC3 flag explicitly **off** can terminate `Ok`
with `ANSWER_BASIS_MODEL_ONLY`, zero citations, and no `NOTICE_CODE_MODEL_ONLY`. The delta ships a
test that asserts this as correct behavior.

---

## Narrative Findings (AI reviewer)

## Critical Issues

> **⚠ ORCHESTRATOR RULING (execute-phase code_review_gate) — both criticals below were
> DOWNGRADED TO INFO after verification against `06-15-PLAN.md`.** They are retained verbatim
> for the audit trail; they are NOT open critical findings and do not gate the phase. This
> follows the same precedent as the prior round's WR-01 severity correction recorded in STATE.md.
>
> **CR-01 — downgraded (spec-conformant).** The finding applies branch 1's (SC3) notice contract
> to branch 2's (D-18) total-drop path. `06-15-PLAN.md` Task 1 instructs verbatim: *"Leave the
> existing model-only notice block (`NoticeCode::ModelOnly`) and its condition unchanged"*, and
> `must_haves` specifies the total-drop path emits a **BASIS_RECONCILED** notice, not a
> MODEL_ONLY notice. The absent `NOTICE_CODE_MODEL_ONLY` is the specified behavior. The
> observation that a basis-to-notice asymmetry now exists across branches is a legitimate design
> observation and is preserved as Info.
>
> **CR-02 — downgraded (no contradiction; spec-conformant).** The claimed plan self-contradiction
> does not exist. The two clauses govern different code paths:
> - `must_haves` *"with the flag off, today's fail-closed behavior is unchanged"* is scoped by its
>   own opening clause — *"When both retrieval paths fail or **evidence is absent**"* — to the
>   **branch-1 empty-evidence path** (D-10/D-11/D-12). That path is unchanged and is covered by
>   `openrouter_node_model_only_flag_off_stays_fail_closed`.
> - `must_haves` separately and explicitly requires the **branch-2 post-repair total-drop path**
>   (D-18 / DEBT-RAG-03) to downgrade *"even with `allow_model_only` false"*, Task 3 requires
>   *"the downgrade must not depend on the SC3 opt-in"* (giving the reason: with the flag true,
>   branch 1 swallows the case before repair runs, so the test would never exercise `total_drop`),
>   and the P1b design table documents `effective_allow = ctx.allow_model_only || total_drop` as
>   the intended construction.
>
> `effective_allow = ctx.allow_model_only || total_drop` at `generate.rs:258` is therefore the
> specified design, not a regression. The residual semantic surface it creates — a caller who
> passed `allow_model_only: false` can receive an `Ok` with a zero-citation MODEL_ONLY basis — is
> real, specified by D-18, and signalled to the caller via the `CitationDropped` +
> `BasisReconciled` notice pair. Preserved as Info.
>
> **WR-03 — CONFIRMED real** by orchestrator inspection (`chat_calls` has no `chat_calls_server`
> clone and no `fetch_add` in this test, unlike all four sibling tests), and held at **warning**
> rather than escalated. See `orchestrator_ruling.confirmed` in the frontmatter for why SC3's
> flag-off half is still proven despite the dead assertion.

### CR-01: A run now terminates with `ANSWER_BASIS_MODEL_ONLY` and zero citations while emitting no `NOTICE_CODE_MODEL_ONLY` — and this is newly production-reachable

**File:** `engine/src/workflow/nodes/generate.rs:238-284` (with
`engine/src/generation/openrouter.rs:787-797`, `engine/src/workflow/mod.rs:162-196`)

**Issue:** Branch 2's total-drop path emits only `CitationRepaired` / `CitationDropped` notices
(`generate.rs:203-224`), and `update_from_model_output` adds `BasisReconciled` (`mod.rs:183-195`).
Neither adds `NoticeCode::ModelOnly`. Branch 1 and the inline remainder both do
(`generate.rs:167-171`, `mod.rs:361-365`), so the basis-to-notice invariant holds on every path
**except** the one this delta just made reachable.

The delta's own test is the proof. `openrouter_node_total_citation_loss_downgrades_basis_to_model_only`
(`workflow_phase5_production.rs`) asserts:

```rust
assert!(ctx.citations.is_empty());
assert_eq!(ctx.answer_basis, v1::AnswerBasis::ModelOnly);
assert!(ctx.notices.iter().any(|n| n.typed_code == v1::NoticeCode::CitationDropped as i32));
assert!(ctx.notices.iter().any(|n| n.typed_code == v1::NoticeCode::BasisReconciled as i32));
```

— no `NoticeCode::ModelOnly` assertion, because none is emitted. A client that parses `notices` to
distinguish a grounded answer from an ungrounded one (the phase's stated user story) sees
`BASIS_RECONCILED` and `CITATION_DROPPED` but never the code that means "this answer has no corpus
grounding." `to_query_rag_response` (`mod.rs:150-160`) ships that state verbatim.

**Why this is new, not pre-existing.** The branch-2 total-drop logic is 06-14 code and is byte-identical
here. What changed is reachability: pre-split, `execute_one_call` ran the full marker validator, and
every input that yields `total_drop` (all markers unresolvable, therefore either an out-of-set cited
ID or an out-of-set strict inline marker) was rejected as `SchemaValidation` → non-retryable →
`LlmGenerationFailed`. `OpenRouterGenerator` is the sole wired production generator and
`citation_repair_enabled` defaults true, so this is the default production configuration.

**Fix:** Emit the disclosure alongside the downgrade, at the single place that knows `total_drop`:

```rust
// engine/src/workflow/nodes/generate.rs — after `ctx.update_from_model_output(&reentry);`
if total_drop {
    ctx.structured_citations.clear();
    ctx.add_notice(crate::workflow::notice(
        crate::pb::lancet::v1::NoticeCode::ModelOnly,
        "All citation markers were unresolvable; the answer retains no corpus grounding.",
        crate::pb::lancet::v1::NoticeSeverity::Warning,
    ));
}
```

`Warning` rather than `Info` is deliberate: unlike branch 1, this ungrounded answer was produced
*despite* successful retrieval. Then extend the existing test to assert the notice, so the invariant
"`answer_basis == MODEL_ONLY` implies a `MODEL_ONLY` notice" is pinned on all three paths.

---

### CR-02: The `allow_model_only = false` fail-closed contract changed, and the plan's own text contradicts itself on whether that was intended

**File:** `engine/src/workflow/nodes/generate.rs:238-256` (`total_drop` / `effective_allow`), with
`engine/src/tests/workflow_phase5_production.rs`
(`openrouter_node_total_citation_loss_downgrades_basis_to_model_only`)

**Issue:** `effective_allow = ctx.allow_model_only || total_drop` (`generate.rs:255`) means the
engine grants itself the model-only relaxation on a request that explicitly opted **out**. Traced end
to end with the delta's own fixture (`allow_model_only = Some(false)`, evidence `[1]`, model answer
`"Answer citing only unresolvable [9]."`, cited `["[9]"]`, basis `retrieval`):

1. Adapter shape check runs with `limits.allow_model_only = false`; basis is `Retrieval` and cited
   IDs are non-empty, so it passes (`openrouter.rs:787-797`).
2. Node branch 1 is skipped (`ctx.allow_model_only` false).
3. Branch 2 repair drops `[9]`, `repaired_citations` is empty, `total_drop = true`,
   `effective_allow = true`, and `validate_grounding_with_limits` therefore accepts a `ModelOnly`
   view that the same validator would reject for any other caller with the flag off
   (`mod.rs:187-192`, the `!limits.allow_model_only && basis == ModelOnly` guard).
4. `update_from_model_output` reconciles down to `AnswerBasis::ModelOnly`.
5. The run returns `Ok`.

The caller asked "never give me an ungrounded answer"; it got a 200 with
`ANSWER_BASIS_MODEL_ONLY`. Before this delta the same exchange produced `LlmGenerationFailed`.

**This needs an orchestrator ruling, not a unilateral fix, because the plan contradicts itself:**

- `06-15-PLAN.md` must-have: *"with the flag off, today's fail-closed behavior is unchanged (D-10,
  D-11, D-12)"* — and the threat model's P1c row asserts the fail-closed branch is the only one that
  changes nothing.
- `06-15-PLAN.md` Task 3 action text: *"Leave `allow_model_only` FALSE on the request — the downgrade
  must not depend on the SC3 opt-in"* — which instructs exactly the behavior above.

The implementation followed Task 3. The must-have is now false as written: flag-off behavior on this
input class changed from a hard failure to a downgraded success. The delta's SC3 flag-off regression
test (`openrouter_node_model_only_flag_off_stays_fail_closed`) does **not** cover this — it exercises
only the empty-evidence prompt-assembly failure, which never reaches the provider, so it cannot
detect the change.

This is prior **CR-03**, which the previous round rated Critical. It was arguably latent then; it is
production-reachable now.

**Fix (decide, do not patch blindly):**

* If the D-10/D-11 opt-out is the contract: scope the relaxation to the disclosure, not the gate —
  keep `effective_allow = ctx.allow_model_only` and return `LlmGenerationFailed` on `total_drop` when
  the flag is off, or (softer) keep the downgrade but gate it behind the opt-in and fail closed
  otherwise. Update the Task 3 test to assert `Err` in the flag-off case and add a flag-**on** twin
  that asserts the downgrade.
* If total-drop downgrade is intended to be flag-independent: correct the must-have text and the P1c
  threat-model row, and land CR-01's `MODEL_ONLY` notice so the client can at least detect it.

Either way, add a test that pins the *chosen* semantics with `allow_model_only` false, since today
that semantics exists only as an incidental consequence of an `||`.

---

## Warnings

### WR-01: `GenerateAnswerNode.grounding_limits` is still `Option`, so the published node has an ungated configuration — the same defect Task 1 fixed on the sibling surface, in the same commit

**File:** `engine/src/workflow/nodes/generate.rs:15, 22-29, 151, 172, 248, 319, 341`
(with `engine/src/workflow/mod.rs:225, 240`)

**Issue:** Every validation site in the node is wrapped in `if let Some(limits) = self.grounding_limits`.
With `grounding_limits == None`:

- branch 1 skips validation entirely but still calls `ctx.update_from_model_output(&for_validation)`
  (`generate.rs:166`);
- branch 2 is unreachable — its guard is `self.citation_repair_enabled && self.grounding_limits.is_some()`
  (`generate.rs:172`) — so control falls through to branch 3;
- branch 3 skips validation *and* skips the resolve-completeness check, which is itself guarded by
  `self.grounding_limits.is_some()` (`generate.rs:341`), then writes raw provider output into `ctx`
  (`generate.rs:334`).

Pre-split the adapter caught ungrounded output on that path regardless of node configuration. Post-split
nothing does. `GenerateAnswerNode` is re-exported publicly (`workflow/nodes/mod.rs:8`,
`workflow/mod.rs:19`) and `GenerateAnswerNode::new(Some(gen))` compiles without `with_settings`;
`Default for GenerateAnswerNode` is `new(None)`.

The sharp version: **Task 1 made `WorkflowDependencies::grounding_limits` a non-`Option` field
defaulting to `GroundingLimits::default_limits()`, with the plan stating the rationale as "so a caller
that forgets it gets a gate rather than no gate." The same commit left the sibling surface `Option`,
defaulting to `None` = no gate.** Same defect class, opposite treatment.

**Severity note.** This is NOT rated Critical, deliberately. Production constructs the node at
`service.rs:149-158` and does call `.with_settings(..)`, so there is no live fail-open path — the same
reasoning by which the orchestrator previously corrected prior WR-01 down from Critical to
dead-surface. Rating it Critical would make the ledger incoherent.

It does, however, answer the plan's open prohibition — *"MUST NOT leave any non-test path that reaches
a `Generator` without a named downstream grounding gate after the adapter is reduced to shape checks"*,
`status: flagged-unverified`. The verified answer is: every *constructed* production path is gated;
the *published constructor* is not.

**Fix:** Mirror Task 1. Make the field non-optional with a safe default:

```rust
pub struct GenerateAnswerNode {
    generator: Option<Arc<dyn Generator>>,
    grounding_limits: GroundingLimits,   // was Option<GroundingLimits>
    ...
}

impl GenerateAnswerNode {
    pub fn new(generator: Option<Arc<dyn Generator>>) -> Self {
        Self { generator, grounding_limits: GroundingLimits::default_limits(), .. }
    }
}
```

and delete the four `if let Some(limits)` wrappers. `citation_excerpt_max_chars` can stay `Option` —
it is not a gate. If the `None` semantics is load-bearing for some existing test, make that explicit
with a named `without_grounding_gate()` builder rather than leaving the unsafe state as the default.

### WR-02: T-06-15-03's accepted residual lets a client-visible citation excerpt come from a chunk the model never saw — and the acceptance rests on the wrong baseline comparison

**File:** `engine/src/generation/openrouter.rs:534, 787-797` (with
`engine/src/workflow/nodes/generate.rs:190-192, 285-294`, `engine/src/prompt.rs:337-460`)

**Issue:** The adapter still computes the packed evidence subset but now discards it — the third tuple
element was renamed to `_validation_evidence` (`openrouter.rs:534`). Marker validation now binds to
`ctx.evidence_blocks`, the **full retrieved set**.

`pack_evidence_and_graph_prompt` hard-errors only if the *first* block does not fit
(`prompt.rs:394-399`); every later block that exceeds the remaining budget is silently skipped by the
scoring loop (`prompt.rs:427-470`). Evidence IDs are assigned by retrieval, not by packing, so if
blocks `[1]..[3]` were packed out of a retrieved `[1]..[8]`, the model sees `[1]..[3]` and a
hallucinated `[5]` now **resolves**. Chain: `citations::resolve_markers` maps it to a real ID →
`repaired_citations` keeps it → `validate_marker_grounding` accepts it (it is in `ctx.evidence_blocks`)
→ `resolve_citations_with_max_chars` (`generate.rs:285-294`) builds a `StructuredCitation` with the
real chunk's `excerpt`, `title`, `document_id` → `to_query_rag_response` ships it. The user is shown
supporting text the model never read.

**The acceptance reasoning does not hold.** The threat model justifies the residual with *"the node
already validated against `ctx.evidence_blocks` in all three of its pre-existing branches, so no gate
universe regresses relative to the node."* That compares against one of the two gates. The **effective**
pre-split universe was the intersection — adapter (packed) ∩ node (full) = packed. Post-split it is
the node alone = full. The universe did widen; the mitigation text elides that by picking the looser
of the two baselines.

**Severity rationale (WARNING, not BLOCKER).** Exploitation requires the model to emit an ID it was
never shown, and under default config (`DEFAULT_EVIDENCE_TOKEN_BUDGET = 8192`,
`DEFAULT_MAX_OUTPUT_TOKENS = 2048`, `generation/mod.rs:78-80`) truncation is not the common case for
typical chunk sizes — the residual is latent rather than routine. It is nonetheless a real
misattribution channel that the recorded acceptance under-describes, and it escalates if the budget is
tightened or top-k raised. Do not treat "accepted in the SUMMARY" as closing it.

**Fix:** The packed subset is already computed and already crosses the layer boundary as the third
tuple element of `pack_openrouter_messages`; it just has no carrier back to the node. Two options that
do not touch the serde-deserialized `ModelOutput`:

1. Have `GenerateAnswerNode` re-derive the packed subset with `pack_evidence_and_graph_prompt` before
   validating, and pass that instead of `ctx.evidence_blocks` to `validate_marker_grounding` /
   `resolve_citations`; or
2. Keep `validate_marker_grounding(&_validation_evidence)` in the adapter as a *non-fatal* pre-check
   whose result is surfaced as a notice, so a marker outside the packed set is disclosed rather than
   silently resolved.

If neither is taken, the residual must be re-recorded with the corrected baseline reasoning.

### WR-03: The SC3 flag-off test's `chat_calls == 0` assertion is vacuous — the counter it reads is never incremented

**File:** `engine/src/tests/workflow_phase5_production.rs`
(`openrouter_node_model_only_flag_off_stays_fail_closed`)

**Issue:** The test creates `let chat_calls = Arc::new(AtomicUsize::new(0));` and asserts
`assert_eq!(chat_calls.load(Ordering::SeqCst), 0);` — but unlike the other four tests it never creates
a `chat_calls_server` clone, and its server thread has **no `POST /chat` branch** (only the
`GET /models` arm). The counter cannot become non-zero regardless of what the code under test does.
The assertion passes identically on correct and broken code.

The plan's acceptance criterion — *"Test 4 asserts `NodeErrorKind::LlmGenerationFailed` and a
chat-request count of 0"* — is therefore met only nominally. This is the same "mock body hardcodes the
outcome the test claims to prove" failure class the plan explicitly prohibited, recurring inside the
delta that was written to eliminate it.

**To be accurate: the test is not worthless.** The sibling assertion
`err.message.contains("prompt assembly failed")` does discriminate, because a run that reached the
chat endpoint would fail with a provider/connection error instead (the listener loop is
`while conn_count < 1`, so it closes after the preflight). One of the two named proofs is real; the
other is theatre.

**Fix:**

```rust
let chat_calls_server = Arc::clone(&chat_calls);   // currently missing
// ...and inside the accept loop, alongside the GET /models arm:
} else if req_str.contains("POST /chat") {
    chat_calls_server.fetch_add(1, Ordering::SeqCst);
    // respond 200 with a well-formed body, so a regression fails on the counter
    //  rather than on a connection error
}
```

and raise the loop bound to `conn_count < 2` so the counter can actually record a violation.

### WR-04: ~700 lines of mock-server scaffolding duplicated verbatim five times — and that duplication is how WR-03 happened

**File:** `engine/src/tests/workflow_phase5_production.rs` (the five new `#[tokio::test]` functions,
+713 lines)

**Issue:** Each of the five new tests carries an independently-copied ~140-line block: identical
`use` statements inside the function body, identical `TcpListener::bind("127.0.0.1:0")`, identical
non-blocking accept loop with the same 5s deadline and 10ms sleep, identical
`OpenRouterGenerationConfig::new(.., 0.0, 1.0, 2048, 8192)`, identical `HTTP/1.1 200 OK` formatting,
identical `EvidenceBlock` literal with twelve fields. The only genuine variation is the model id, the
chat response body, and the assertions.

This is not a style complaint: the copy that dropped one line — `chat_calls_server` — is precisely the
test whose central assertion became vacuous (WR-03). Five hand-maintained copies of a security-relevant
harness will diverge again.

**Fix:** Extract a helper in the same test module, e.g.

```rust
struct MockOpenRouter { addr: SocketAddr, chat_calls: Arc<AtomicUsize>, models_calls: Arc<AtomicUsize>, handle: JoinHandle<()> }

fn spawn_mock_openrouter(model_id: &str, chat_body: Option<serde_json::Value>, max_conns: usize) -> MockOpenRouter;
fn evidence_block(id: &str, n: u32) -> crate::prompt::EvidenceBlock;
fn node_with_default_limits(gen: Arc<OpenRouterGenerator>) -> GenerateAnswerNode;
```

`chat_body: None` then models the flag-off case explicitly (endpoint present, never expected to fire)
and makes the counter meaningful by construction.

### WR-05: The adapter re-derives `pack_openrouter_messages`' model-only condition instead of learning it from the packer — two copies that must stay in sync

**File:** `engine/src/generation/openrouter.rs:791-795` (with `:263-267`)

**Issue:**

```rust
let validation_view = if request.evidence.is_empty() && request.allow_model_only {
    model_output.into_model_only()
} else {
    model_output.clone()
};
```

That predicate is a hand-copied duplicate of the branch condition inside `pack_openrouter_messages`
(`openrouter.rs:263`), evaluated ~530 lines away with no compile-time link between them. If the packer's
model-only admission rule is ever narrowed or widened (e.g. to add a graph-facts conjunct), the
validation view silently disagrees with the prompt that was actually sent: either the adapter rejects
a legitimately model-only response, or it relaxes the empty-citations guard for a request that was
packed with evidence. The plan even fences the packer's signature as owned by 06-13, which makes the
drift risk structural rather than hypothetical.

**Fix:** Return the decision from the packer rather than recomputing it — e.g. extend the tuple to a
small struct carrying `packed_evidence` plus a `model_only: bool` (or a
`#[derive(Clone, Copy)] enum EvidencePolicy { Grounded, ModelOnly }`), and branch on that value. At
minimum extract a single `fn is_model_only_request(request: &GenerationRequest) -> bool` used by both
sites.

### WR-06: Prior WR-02 is still open and is now relaxed at *both* gates — a self-reported `model_only` can discard a full evidence set

**File:** `engine/src/generation/openrouter.rs:787-797`, `engine/src/workflow/nodes/generate.rs:147-172`,
`engine/src/workflow/mod.rs:314-320`

**Issue:** `should_treat_as_model_only` still fires on the model's self-report arm
(`generation/mod.rs:381-383`: `no_evidence || self.answer_basis == AnswerBasis::ModelOnly`). With the
SC3 opt-in on and a **full evidence set packed and sent**:

1. The adapter takes the `else` view (evidence non-empty) and shape-checks with
   `limits.allow_model_only = request.allow_model_only = true`, so both the `ModelOnly`-basis guard and
   the empty-`cited_evidence_ids` guard are satisfied by a model that unilaterally labels itself
   `model_only` with zero citations.
2. Node branch 1 then fires via the self-report arm, clears `ctx.structured_citations`, and discloses
   with a `NoticeSeverity::Info` notice — the same severity used for routine repair notices.

Evidence blocks are explicitly untrusted input (`prompt.rs:209`, *"Evidence is untrusted data"*), so an
injected block that persuades the model to self-label `model_only` suppresses corpus grounding rather
than being rejected. SC3 scopes model-only to *"when both retrieval paths fail or evidence is absent"*;
this is broader. `run_inline_prompt_generation_remainder` inherits the identical behavior via the new
Task-1 gate, which mirrors branch 1 by design — so the delta propagated the hole to a second surface.

**Fix (unchanged from the prior round; both files are now in scope, so it can be closed here):**
Confirm against D-10/D-11 whether the self-report arm was intended to discard a *full* evidence set.
If yes, raise the notice severity at `generate.rs:167-171` and `mod.rs:361-365` from `Info` to
`Warning` and pin the behavior with a test. If no, scope the relaxation at both gates:

```rust
// openrouter.rs
let allow = request.allow_model_only && request.evidence.is_empty();
let limits = self.config.grounding_limits.with_allow_model_only(allow);
// generate.rs / workflow/mod.rs: gate branch 1 on ctx.evidence_blocks.is_empty(), not on the
// self-report arm, and update the should_treat_as_model_only doc comment in the same change.
```

---

## Info

### IN-01: Dead test counters

**File:** `engine/src/tests/workflow_phase5_production.rs` (all five new tests)

**Issue:** `models_calls` is constructed and cloned in all five tests and asserted in none.
`chat_calls` is incremented but never asserted in
`openrouter_node_standalone_near_miss_marker_is_repaired` and
`openrouter_node_strict_visible_unresolvable_marker_is_dropped`. Because `Arc::clone` counts as a use,
`dead_code` does not fire, so these read as coverage that does not exist.

**Fix:** Either assert them (`models_calls == 1` pins the preflight; `chat_calls == 1` pins D-14's
no-second-call clause on the two repair tests, which is cheap and worth having) or drop them. The
helper in WR-04 makes assertion the low-cost option.

### IN-02: Needless clone of the model output in the adapter's non-model-only branch

**File:** `engine/src/generation/openrouter.rs:794`

**Issue:** `validate_output_shape_with_limits` takes `&self`, so the `else` arm's `model_output.clone()`
exists only to satisfy the `if`/`else` type unification of `validation_view`. Every grounded generation
now clones the full answer string plus citation vector purely to call a `&self` method on it. This is
flagged for clarity, not throughput — the code reads as though the view were required.

**Fix:**

```rust
if request.evidence.is_empty() && request.allow_model_only {
    model_output.into_model_only().validate_output_shape_with_limits(limits)?;
} else {
    model_output.validate_output_shape_with_limits(limits)?;
}
```

### IN-03: The model-only validation view silently skips the `cited_evidence_ids` count and length bounds

**File:** `engine/src/generation/mod.rs:219-238` (with `openrouter.rs:791-795`,
`workflow/nodes/generate.rs:150`, `workflow/mod.rs:317-321`)

**Issue:** `into_model_only()` clears `cited_evidence_ids` *before* `validate_output_shape_with_limits`
runs, so on every model-only path the `MAX_CITED_EVIDENCE_IDS` count check and the per-ID
`MAX_EVIDENCE_ID_CHARS` check are applied to an empty vector and can never fire. The bounds exist to
cap attacker-influenced provider output; on this path they are structurally unreachable at all three
gates (adapter, node branch 1, inline remainder).

Impact is small — the cleared IDs are discarded rather than propagated, so the only exposure is the
transient allocation from deserialization, itself bounded by the HTTP response size — but the checks
are now decorative on that path and a future change that *keeps* the IDs would inherit no bound.

**Fix:** Validate shape on the raw output and apply the model-only correction afterwards, or move the
two bound checks into `validate_marker_grounding` where they run against the un-cleared list.

### IN-04: Mock handlers perform a single 8 KiB read without draining the request body

**File:** `engine/src/tests/workflow_phase5_production.rs` (all five new mock server threads)

**Issue:** `let n = stream.read(&mut buf).unwrap_or(0);` reads once into a fixed 8 KiB buffer and
routes on `req_str.contains("POST /chat")`. If a future fixture packs a prompt larger than one TCP
segment, or the headers and body split across reads, the route match becomes timing-dependent and the
test flakes rather than fails. `unwrap_or(0)` additionally swallows read errors into an unmatched
request that produces no response, which surfaces as a client timeout rather than a clear failure.

**Fix:** Read until the end of the header block (`\r\n\r\n`) before routing, and route on the request
line only. Fold this into the WR-04 helper so it is fixed once.

### IN-05: The Task-1 gate test asserts the rejection but not the invariant it exists to prove

**File:** `engine/src/tests/workflow_phase5.rs` (`inline_remainder_rejects_ungrounded_model_output`)

**Issue:** Task 1's stated invariant is that the remainder validates *before any context mutation*. The
test asserts `res.is_err()`, `err.kind == NodeErrorKind::LlmGenerationFailed`, and that a `NodeFailed`
event was emitted -- none of which distinguishes "rejected before writing `ctx`" from "wrote `ctx`, then
rejected." My reading of `workflow/mod.rs:311-350` establishes the ordering, so this is not a defect in
the code; it is an assertion narrower than the claim it is cited for (same class as WR-03).

**Fix:** Add two lines so a future reordering fails the test rather than relying on a reviewer:

```rust
assert!(ctx.answer.is_empty(), "rejected output must not have been written to ctx");
assert!(ctx.citations.is_empty());
```

---

## Carry-Forward From Prior Round

The prior `06-REVIEW.md` (delta review of `953b22c`) recorded 7 findings of its own plus an 18-row
carry-forward table from the full-scope review at `195edb2`. Every one is dispositioned below.
Still-open items are **not** counted in the frontmatter totals.

### Prior round's own findings (delta review of `953b22c`)

IDs here are namespaced `953b22c ...`. The full-scope table below reuses the same letters for
different findings, so the prefix is load-bearing.

| Prior ID | Disposition |
|---|---|
| **`953b22c` CR-01** (SC5 repair unreachable — adapter validates raw output before repair) | **RESOLVED.** Adapter now calls `validate_output_shape_with_limits` only (`openrouter.rs:797`); `grep -c validate_marker_grounding engine/src/generation/openrouter.rs` = 0. I re-derived all three SC5 mock bodies against the pre-split validator and confirmed each was rejected there — see the table in the Summary. The five new tests drive the real `OpenRouterGenerator` through `GenerateAnswerNode::run`; no `FakeGenerator`/`PackingTestGenerator` in `workflow_phase5_production.rs`. |
| **`953b22c` CR-02** (`model_only_system_policy` never instructs `answer_basis: "model_only"`; both sites validate the unmodified output) | **RESOLVED — both halves.** `prompt.rs:221` adds the instruction; `generate.rs:150-166` validates `for_validation = output.into_model_only()` and passes `&for_validation` to `update_from_model_output`. `openrouter_node_optin_empty_evidence_retrieval_basis_still_yields_model_only` proves the engine decides: its mock declares `"answer_basis": "retrieval"` with empty citations, so the body does not reveal the asserted basis. |
| **`953b22c` WR-01** (`GenerationRequest::system_policy` is silently ignored; a test doc comment still claims it reaches the wire) | **still open -- re-checked, unchanged by this delta.** All three files are in the pinned nine. `openrouter.rs:296` still hardcodes `let system_msg = "You are a precise technical RAG engine.".to_string();` in the grounded branch, and `grep -n system_policy engine/src/generation/openrouter.rs` returns only line 264 (`model_only_system_policy()`) -- never `request.system_policy`. The `pub` field is still declared, destructured, `PartialEq`-compared and defaulted (`generation/mod.rs:450, 471, 481, 495`) with no production reader. The doc comment on `generation_request_contract_unchanged_by_precedence_change` (`workflow_phase5.rs:5952-5955`) still asserts its `system_policy` "feed[s] the outbound provider payload unmodified" -- false, and the test remains tautological under `rust-guidelines.md` M-TAUTOLOGICAL-TESTS. This delta's `openrouter.rs` hunks are confined to `:531` and `:784-797`, so nothing here moved. |
| `953b22c` WR-02 (`allow_model_only` relaxes adapter validation even when evidence is present) | **still open** — see new **WR-06**. Both files are in scope; the delta propagated the behavior to the inline remainder as well. |
| `953b22c` WR-03 (two divergent model-only prompt constructions; `ctx.assembled_prompt` is not the prompt sent) | **still open (in-scope half).** `prompt.rs:226` `pack_model_only_prompt` is still called only from `workflow/nodes/assemble_prompt.rs:77` and the test at `workflow_phase5.rs:5792-5798`; `pack_openrouter_messages` still builds its own two-message shape at `openrouter.rs:263-267` and never calls it. The delta did not touch either. The checkpoint/replay half (`assemble_prompt.rs`, `workflow/events.rs`) is **not re-checked — outside pinned scope**. |
| `953b22c` WR-04 (citation dedup predicate broader than the invariant it needs, `prompt.rs:603-605`) | **still open.** `prompt.rs` is in scope; the delta touched only `model_only_system_policy` (line 221). The `|| c.chunk_id == block.chunk_id` disjunct is unchanged and still has no reachable path today. |
| `953b22c` WR-05 (`#[allow]` instead of `#[expect]`; positional bool among positional integers in `pack_openrouter_messages`) | **still open.** `openrouter.rs:245-254` unchanged by the delta; the plan explicitly fenced the packer's signature as owned by 06-13. Now compounded by new **WR-05** above, which adds a second hand-maintained copy of the same boolean condition. |

### Full-scope carry-forward (from `195edb2`)

IDs here are namespaced `195edb2 ...`.

| Prior ID | Disposition |
|---|---|
| `195edb2` CR-01 (citation repair fails on duplicate cited IDs) | **resolved** (closed at `953b22c`; dedup guards at `generate.rs:198-207` and `prompt.rs:603-605` unchanged by this delta). |
| `195edb2` CR-02 (model-only opt-in dead in production) | **resolved.** The remaining halves recorded as open last round are closed — see `953b22c` CR-02 above. Its `ctx.assembled_prompt` sub-item survives as WR-03, tracked separately. |
| **`195edb2` CR-03** (total-drop yields MODEL_ONLY basis with no MODEL_ONLY notice, against an explicit opt-out) | **still open — and newly production-reachable as a direct result of this commit.** Re-raised at full severity as new **CR-01** (missing `NOTICE_CODE_MODEL_ONLY`) and new **CR-02** (flag-off contract change). Pre-split, every input producing `total_drop` was rejected by the adapter's marker checks; post-split the path is live under the default production configuration, and `openrouter_node_total_citation_loss_downgrades_basis_to_model_only` pins the violating behavior as correct. |
| `195edb2` CR-04 (env-override prefix separator) | **deferred** — Phase 6.1 per `.planning/ROADMAP.md`. Unchanged. |
| `195edb2` CR-05 (`degraded_mode` always false) | **deferred** — Phase 6.1 per `.planning/ROADMAP.md`. Unchanged. |
| `195edb2` WR-01 (`run_inline_prompt_generation_remainder` is a `pub` generation path with no grounding validation) | **resolved by this delta.** The orchestrator's prior severity correction stands: all five callers are in `engine/src/tests/workflow_phase5.rs`, declared `#[cfg(test)]` at `lib.rs:19-21`, so it was a dead test-only surface rather than a live fail-open path. 06-15 gated it anyway in commit `30fdc46`, and gated it *before* reducing the adapter -- the correct order. The gate at `workflow/mod.rs:311-350` precedes every `ctx` mutation, builds limits from `deps.grounding_limits.with_allow_model_only(ctx.allow_model_only)` (wired from `service.rs:106`), and emits `events::node_failed` before returning `Err`. `inline_remainder_rejects_ungrounded_model_output` asserts the error kind and the event; see IN-05 for the assertion it omits. |
| `195edb2` WR-02 (`ANSWER_BASIS_UNSPECIFIED` on successful zero-evidence responses) | not re-checked — outside pinned scope (`engine/src/workflow/runner.rs`, `proto/`). |
| `195edb2` WR-03 (dead `_disable_graph_context` binding) | **re-checked, still open.** `engine/src/service.rs` IS in scope, but the delta touched exactly one line there (`:106`, the `grounding_limits` field). The binding is unchanged. |
| `195edb2` WR-04 (dead `GRAPH_TIMEOUT`/`GRAPH_DEGRADED` constants) | **re-checked, still open.** `engine/src/workflow/mod.rs` is in scope; `grep -rn "GRAPH_TIMEOUT\|GRAPH_DEGRADED" engine/src` finds only generated protobuf names in `pb/lancet/v1/lancet.v1.rs` and unrelated string literals in tests — no identifier reference to the `workflow/mod.rs` constants. |
| `195edb2` WR-05 (blank telemetry import) | not re-checked — outside pinned scope (`gateway/`). |
| `195edb2` WR-06 (gateway drops two `RetrievalSnapshot` fields) | not re-checked — outside pinned scope (`gateway/`). |
| `195edb2` WR-07 (checkpoint snapshot missing `typed_code` and two context fields) | not re-checked — outside pinned scope (`engine/src/workflow/events.rs`). |
| `195edb2` WR-08 (`invalid_settings` disposition mismatch) | **not re-checked — companion file outside scope.** `engine/src/service.rs` is in scope and still contains the `(tonic::Code::InvalidArgument, "invalid_settings")` mapping at `:792`, but the finding's other half lives in `engine/src/tests/bad_input_matrix.rs`, which is not in the pinned nine. Ruling requires both. |
| `195edb2` WR-09 (prod TLS guard matches only `sslmode=disable`) | not re-checked — outside pinned scope (`gateway/`). |
| `195edb2` WR-10 (tautological fake-asserting tests) | not re-checked — outside pinned scope (`engine/src/workflow/ports.rs`). **Connective note:** the same defect class recurs *inside* this scope as new **WR-03** — an assertion (`chat_calls == 0`) that cannot fail because the value it reads is never written. The class is not confined to `ports.rs`. |
| `195edb2` WR-11 (test-gate script: hardcoded developer home path, no `pipefail`) | **still open.** `scripts/engine-test-targets.sh` is in scope and the delta again changed only the pinned counts. Line 7 still contains `/mnt/c/Users/user3/.cargo/bin` and `/c/Users/user3/.cargo/bin`; line 29 is still an unguarded pipeline under `/bin/sh` with `set -e` and no `pipefail`, so a build failure still reports as `TOTAL test count mismatch: expected 386, got 0` rather than as a build failure. The count change itself is correct and internally consistent: `351 + 0 + 18 + 0 + 17 = 386`, and I measured `351 tests, 0 benchmarks` from `cargo test --lib -- --list`. |
| `195edb2` WR-12 (cancelled run emits spurious `RETRIEVAL_DEGRADED_*`) | not re-checked — outside pinned scope (`engine/src/workflow/nodes/retrieve.rs`). |
| `195edb2` WR-13 (README says Phase 6 has not started) | not re-checked — outside pinned scope (`README.md`). |

---

_Reviewed: 2026-08-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
