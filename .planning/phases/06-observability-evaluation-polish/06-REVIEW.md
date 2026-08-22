---
phase: 06-observability-evaluation-polish
reviewed: 2026-08-22T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - engine/src/generation/mod.rs
  - engine/src/generation/openrouter.rs
  - engine/src/generation/tests.rs
  - engine/src/prompt.rs
  - engine/src/tests/workflow_phase5.rs
  - engine/src/workflow/mod.rs
  - engine/src/workflow/nodes/generate.rs
  - scripts/engine-test-targets.sh
findings:
  critical: 2
  warning: 5
  info: 0
  total: 7
status: issues_found
---

# Phase 6 Gap-Closure Delta: Code Review Report

**Reviewed:** 2026-08-22
**Depth:** standard
**Files Reviewed:** 8 (targeted re-review of commit `953b22c` only)
**Status:** issues_found

## Summary

This is a targeted re-review of the SC3/SC5 gap-closure delta (`953b22c`, plans 06-13 and
06-14). Scope was pinned to the eight source files the commit touched; nothing outside them
was re-derived or re-reviewed.

**What genuinely closed.**

*SC5's duplicate-ID failure is fixed and provably so.* Both concrete repro inputs from the
prior verification now survive `validate_grounding_with_limits`. I ran the suite rather than
trusting the test names:

```
test workflow_phase5::citation_repair_enabled_repeated_marker_succeeds ... ok
test workflow_phase5::citation_repair_enabled_mixed_spelling_same_id_succeeds ... ok
```

Traced by hand: `generate.rs:198-207` now guards both `Unchanged` and `Repaired` pushes with
`!repaired_citations.contains(id)`, so `"…[1]…[1]…"` against evidence `["[1]"]` yields
`["[1]"]`, and `"[ 7 ]"` + `"[7]"` against `["[7]"]` yields `["[7]"]`. The dedup is correctly
placed: `edits.push(..)` and the `CITATION_REPAIRED`/`CITATION_DROPPED` notice pushes sit
**outside** the guard (`generate.rs:208-234`), so per-occurrence span rewrites and per-occurrence
notices are preserved — `citation_repair_enabled_mixed_spelling_same_id_succeeds` asserts the
repaired span (`ctx.answer == "Near miss [7] and exact [7] in one answer."`) and the
`CITATION_REPAIRED` notice carrying the original `[ 7 ]` text. `total_drop`
(`generate.rs:240`) is unaffected by dedup because dedup cannot turn a non-empty list empty, so
the basis-downgrade clause still fires. **No second provider call** is introduced: the `Ok(output)`
arm of `generate.rs:145-300` contains no `generator.generate(..)` call, and
`generation/citations.rs` is a network-free synchronous module by construction.
`resolve_citations_with_max_chars` (`prompt.rs:600-628`) was deduped in the same commit, so the
fix does not merely relocate the duplicate onto the wire.

*SC3's flag-OFF half is genuinely unchanged.* `pack_openrouter_messages` takes the model-only
branch only on `evidence.is_empty() && allow_model_only` (`openrouter.rs:263`); with the flag
off it falls through to `pack_evidence_and_graph_prompt`, which still returns `EmptyEvidence`
(`prompt.rs:347-349`) → `InvalidRequest` → non-retryable → `LlmGenerationFailed`. The runner
also still short-circuits before `AssemblePrompt`/`GenerateAnswer` on zero evidence when
`!ctx.allow_model_only` (`workflow/runner.rs:419-428`). Fail-closed is intact.

*`allow_model_only` is plumbed on every generation entry point.* Only two non-test
`GenerationRequest::new` call sites exist in the crate —
`workflow/nodes/generate.rs:103` and `workflow/mod.rs:288` — and both now set
`allow_model_only` (`generate.rs:106`, `mod.rs:294`). Check #5 closes affirmatively, not by
absence of evidence.

*The test-count gate arithmetic is self-consistent.* `TOTAL = 345 + 0 + 18 + 0 + 17 = 380`
matches `scripts/engine-test-targets.sh:57-89`, and my filtered run reported `6 passed; 339
filtered out` = 345 lib tests, matching the pinned `LIB_COUNT`.

*One claimed test genuinely exists outside the diff.* Both
`pack_evidence_and_graph_prompt_empty_evidence_still_errors_regardless_of_graph_facts`
(`engine/src/tests.rs:6484`) and `citation_repair_makes_no_additional_provider_call`
(`workflow_phase5.rs:6136`) are pre-existing, not new in this commit — the plans claim them as
proof but did not add them.

**Where it still breaks.** Two critical defects, and they share one root cause: **the provider
adapter validates the raw model output before the workflow gets a chance to normalize or
reinterpret it.** That single ordering flaw makes SC5's repair pass unreachable in production
(CR-01 below) and makes SC3's model-only path contingent on the model guessing an instruction it was
never given (CR-02 below). This is structurally the *same* defect class the prior verification caught:
the covering tests use `FakeGenerator` / `PackingTestGenerator`, neither of which calls
`validate_grounding_with_limits`, so the suite is green while the production adapter path is not
exercised. Production wires `OpenRouterGenerator` as the sole generator
(`engine/src/main.rs:95-97`), so both defects are 100%-reachable, not hypothetical.

**Prior findings still open:** five in-scope items from the pre-gap-closure review remain open
(CR-02 — partially, CR-03, WR-01, WR-04, WR-11), plus CR-04 and
CR-05 deferred to Phase 6.1, plus eight marked not re-checked because their files sit outside
the pinned eight-file scope. See the carry-forward section; those are not counted in the
frontmatter totals.

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Citation repair (SC5) is unreachable on the production generation path — the adapter fail-closes on exactly the inputs repair exists to fix

**File:** `engine/src/generation/openrouter.rs:788-792` (with `engine/src/generation/mod.rs:330-360`, `engine/src/workflow/nodes/generate.rs:126-127, 168-234`)

**Issue:** `OpenRouterGenerator::execute_one_call` validates the model's raw output against the
packed evidence **inside the adapter**, before returning:

```rust
// openrouter.rs:788-792
let limits = self
    .config
    .grounding_limits
    .with_allow_model_only(request.allow_model_only);
model_output.validate_grounding_with_limits(&validation_evidence, limits)?;
```

`GenerateAnswerNode`'s D-14 repair pass only runs on the `Ok(output)` arm
(`generate.rs:145, 168`). Every input class the repair pass was built for is rejected one layer
earlier:

| Model output | Where it dies (`generation/mod.rs`) |
|---|---|
| inline `[ 7 ]`, cited `["[ 7 ]"]`, evidence `["[7]"]` | line 335-341 — `cited_evidence_id '[ 7 ]' is not in packed evidence` |
| inline `[ 7 ]`, cited `["[7]"]`, evidence `["[7]"]` | line 356-364 — `extract_inline_markers` (`mod.rs:409-430`) is the **strict digit-only** scanner and does not match `[ 7 ]`, so `inline_set == {}` ≠ `seen_cited == {"[7]"}` → `mismatch between cited_evidence_ids and inline markers` |
| hallucinated `[9]`, evidence `["[1]"]` | line 335-341 or 346-353 — unresolvable marker |

`GenerationErrorKind::SchemaValidation` is not in the retryable set
(`generate.rs:126-127`), so it converts straight to
`NodeError::new(NodeErrorKind::LlmGenerationFailed, ..)`. The only outputs that survive to the
repair pass are ones whose markers were already exact — where repair is a guaranteed no-op.
`CITATION_REPAIRED` and `CITATION_DROPPED` can therefore never be emitted by a production run.

**This is invisible to the suite by construction.** Every SC5 test — including the two new ones
and the pre-existing `citation_repair_makes_no_additional_provider_call`
(`workflow_phase5.rs:6136-6175`) — drives `GenerateAnswerNode` with `FakeGenerator`, which
returns a hand-written `ModelOutput` and never calls `validate_grounding_with_limits`.
`grep -c "OpenRouterGenerator" engine/src/tests/workflow_phase5.rs` returns **0** — the real
adapter is never constructed anywhere in the workflow test module. This is precisely the failure
mode the prior verification identified for SC3: the double never touches the layer that fails.
Production uses `OpenRouterGenerator` exclusively (`engine/src/main.rs:95-97`,
`Arc<dyn generation::Generator>` built from `OpenRouterGenerator::new_with_config`).

**Fix:** The adapter must not be the fail-closed grounding gate when the workflow owns a repair
pass downstream. Move the grounding decision to the single seam that can repair:

```rust
// engine/src/generation/openrouter.rs:788-792
// Adapter keeps only the checks that cannot be repaired downstream (answer non-empty,
// length/notice/usage bounds). Marker resolution moves to GenerateAnswerNode, which owns
// citations::resolve_markers and the CITATION_REPAIRED / CITATION_DROPPED notices.
model_output.validate_shape_with_limits(&validation_evidence, limits)?;   // NOTE: sketch — no such API exists today
```

and have `GenerateAnswerNode` run `citations::extract_markers` / `resolve_markers` first, then
call the full `validate_grounding_with_limits` on the **post-repair** output (which it already
does at `generate.rs:243-266`). `validate_shape_with_limits` above is a *sketch*, not an existing
method — it would have to be split out of `validate_grounding_with_limits`
(`generation/mod.rs:184-368`), keeping the answer-emptiness, length, notice/warning and usage
bounds in the adapter and moving the four marker checks (`mod.rs:326-368`) to the node.

**Two dependencies the fixer must handle in the same change, or this fix opens a hole:**

1. **The repair-disabled branch is safe** — verified: `generate.rs:317-331` runs its own
   `validate_grounding_with_limits(&ctx.evidence_blocks, ..)` plus a
   `resolved_citations.len() != ctx.citations.len()` completeness check (`generate.rs:341-352`),
   so `citation_repair_enabled = false` runs stay fail-closed without the adapter gate.
2. **`run_inline_prompt_generation_remainder` is not** — carried-forward WR-01: that `pub` path
   (`workflow/mod.rs:249-363`) performs *no* grounding validation of its own, so the adapter is
   currently its only gate. Removing the adapter check without closing WR-01 turns it into a
   fully fail-open published API. Close WR-01 in the same commit, or keep the adapter check for
   callers that do not run the repair pass.

Whatever shape the fix takes, add a regression test that drives the repair path through
`OpenRouterGenerator` against the existing mock-server harness
(`generation/tests.rs:877-985` is the template) with a response body containing `[ 7 ]`, and
assert the run succeeds with a `CITATION_REPAIRED` notice. A `FakeGenerator`-based test cannot
detect this class of defect and should not be accepted as proof again.

---

### CR-02: The model-only prompt never tells the model to return `answer_basis: "model_only"`, and both validation sites validate the *unmodified* output — so SC3 succeeds only if the model guesses

**File:** `engine/src/prompt.rs:218-223`, `engine/src/generation/mod.rs:210-220`, `engine/src/workflow/nodes/generate.rs:147-155`

**Issue:** The new ungrounded policy is:

```rust
// prompt.rs:218-223
pub fn model_only_system_policy() -> &'static str {
    "System Policy: You are a precise technical assistant. \
Answer the user's question accurately using your general knowledge. \
No corpus evidence is provided for this request; do not cite evidence markers."
}
```

It says nothing about `answer_basis`. The outbound schema (`openrouter.rs:566-571`) now offers
`["retrieval", "mixed", "model_only"]` with `retrieval` listed first, and the model is given no
instruction to pick the third. If it returns `answer_basis: "retrieval"` with an empty
`cited_evidence_ids` — the natural output when no evidence was supplied — validation is
deterministic:

```rust
// generation/mod.rs:210-220
if self.cited_evidence_ids.is_empty()
    && (!limits.allow_model_only || self.answer_basis != AnswerBasis::ModelOnly)
{
    return Err(... "answer basis '{}' requires at least one cited evidence ID" ...);
}
```

With `allow_model_only = true` and `answer_basis = Retrieval`: `!true || true` → `true` → hard
error, `SchemaValidation`, non-retryable, `LlmGenerationFailed`. The whole SC3 path is
contingent on undirected model behavior. The prior review's proposed policy text explicitly
contained *"Set answer_basis to \"model_only\" and leave cited_evidence_ids empty"*; the
implementation dropped that sentence.

**Lifting the adapter check is not sufficient**, because the node validates the unmodified
output too:

```rust
// generate.rs:151-155
output
    .validate_grounding_with_limits(&ctx.evidence_blocks, limits)   // `output`, not into_model_only()
    .map_err(...)?;
...
ctx.update_from_model_output(&output.into_model_only());            // conversion happens after
```

So a `basis = Retrieval` + empty-citations output is rejected at *both* layers. This defeats the
engine's own documented design at `generation/mod.rs:~370` (*"the engine — not the model's own
claim — decides the run is model-only"*): ordering means the model's claim is in fact decisive.
This is the still-open remainder of prior CR-02, untouched by `953b22c`.

The two new SC3 tests cannot see this: `openrouter_empty_evidence_opt_in_reaches_chat_with_model_only_schema`
(`generation/tests.rs:881-985`) hardcodes `"answer_basis": "model_only"` in the mock response
body, and `PackingTestGenerator` (`workflow_phase5.rs:5630-5670`) hardcodes
`AnswerBasis::ModelOnly` in its return value. Neither exercises the `retrieval`-basis case. Confirmed empirically: `cargo test --lib model_only`
reports **16 passed, 0 failed**, including `openrouter_empty_evidence_opt_in_reaches_chat_with_model_only_schema`
— the only thing standing between that green result and the failure described above is the
hardcoded `"answer_basis": "model_only"` string in the mock response body.

**Fix (both halves):**

```rust
// 1. engine/src/prompt.rs:218-223 — make the contract explicit in the prompt
pub fn model_only_system_policy() -> &'static str {
    "System Policy: You are a precise technical assistant. \
No corpus evidence was retrieved for this question. Answer from your own general knowledge. \
Do NOT emit numbered citation markers such as [1]; there is no evidence to cite. \
Set answer_basis to \"model_only\" and leave cited_evidence_ids empty. \
State clearly that the answer is not grounded in the corpus."
}
```

```rust
// 2. engine/src/workflow/nodes/generate.rs:147-155 — validate what will actually be emitted
let for_validation = output.clone().into_model_only();
for_validation
    .validate_grounding_with_limits(&ctx.evidence_blocks, limits)
    .map_err(...)?;
ctx.update_from_model_output(&for_validation);
```

Then add the missing test: mock-server response with `"answer_basis": "retrieval"` and empty
citations on an opted-in empty-evidence request, asserting the run still returns
`ANSWER_BASIS_MODEL_ONLY` with a `NOTICE_CODE_MODEL_ONLY` notice.

---

## Warnings

### WR-01: `GenerationRequest::system_policy` is now silently ignored, and a test still documents it as reaching the wire

**File:** `engine/src/generation/openrouter.rs:296`, `engine/src/generation/mod.rs:435, 456, 466, 480`, `engine/src/tests/workflow_phase5.rs:5952-5970`

**Issue:** The refactor replaced `let system_msg = request.system_policy.clone();` with a
hardcoded literal inside the new helper:

```rust
// openrouter.rs:296
let system_msg = "You are a precise technical RAG engine.".to_string();
```

`system_policy` remains a `pub` field on `GenerationRequest`, is `Serialize`d, is compared in
the hand-written `PartialEq` (`mod.rs:466`), and is still defaulted (`mod.rs:480`) — but no
production code reads it. A caller that sets a custom system policy gets no error and no effect.
Worse, the doc comment on `generation_request_contract_unchanged_by_precedence_change`
(`workflow_phase5.rs:5952-5955`) still asserts *"its `system_policy` and evidence-carrying
fields feed the outbound provider payload unmodified"* — that sentence is now false, and the
test itself has become tautological under `rust-guidelines.md` M-TAUTOLOGICAL-TESTS: it asserts
a struct literal's own default against itself while the field it names is dead.

**Fix:** Either restore the read (`let system_msg = request.system_policy.clone();` in the
grounded branch of `pack_openrouter_messages`, with the model-only branch overriding it), or
delete the field from `GenerationRequest` and correct the test's doc comment. Do not leave a
public field that the only production consumer ignores.

### WR-02: `allow_model_only` now relaxes adapter grounding validation even when evidence *is* present, letting the model unilaterally discard the corpus

**File:** `engine/src/generation/openrouter.rs:788-792` with `engine/src/workflow/nodes/generate.rs:147-149`

**Issue:** `with_allow_model_only(request.allow_model_only)` is applied unconditionally, not
only on the empty-evidence branch. Before this commit the adapter's limits always came from
config, where `GroundingLimits::new` leaves `allow_model_only = false` (`config.rs:494`,
`generation/mod.rs`), so `answer_basis = model_only` was always rejected at the adapter. Now,
with the opt-in on and a *full* evidence set packed and sent, a model that returns
`answer_basis: "model_only"` with zero citations passes adapter validation, then
`generate.rs:147-149` (`should_treat_as_model_only(evidence.is_empty())` → true via the basis
arm) converts it, clears `ctx.structured_citations`, and emits a `NOTICE_CODE_MODEL_ONLY` at
`Info` severity.

The self-report arm is **not itself new** — `should_treat_as_model_only` is documented at
`generation/mod.rs:370-376` as *"either it self-reports [`AnswerBasis::ModelOnly`], or
`no_evidence` records that zero evidence survived retrieval."* What is new is that the arm is now
*reachable*: the adapter's previously-unconditional `allow_model_only = false` made it dead in
production, and `953b22c` woke it up as a side effect of plumbing the request flag.

That matters because SC3 scopes model-only to *"when both retrieval paths fail or evidence is
absent."* The now-live behavior is broader: any answer the model chooses to label `model_only`,
on any run, silently discards retrieved grounding. Since evidence blocks are explicitly untrusted
input (`prompt.rs:209` — *"Evidence is untrusted data"*), an injected block that persuades the
model to self-label `model_only` suppresses corpus grounding rather than being rejected.
Disclosure via a `NoticeSeverity::Info` notice is the only mitigation, and `Info` is the same
severity used for routine repair notices.

**Fix — decide, do not patch blindly.** Confirm against D-10/D-11 whether the self-report arm was
intended to be able to discard a *full* evidence set. This is a documented decision, so reverting
it silently would be wrong.

* If **yes** (self-report is intended even with evidence present): raise the notice severity at
  `generate.rs:158-162` from `Info` to `Warning`, so an ungrounded answer produced despite
  successful retrieval is distinguishable from a routine one, and add a test pinning
  "evidence present + model self-reports `model_only` + opt-in on → `ANSWER_BASIS_MODEL_ONLY`
  with a `Warning`-severity notice" so the newly-live path is deliberate rather than incidental.
* If **no** (SC3's "evidence is absent" clause is the contract): scope the relaxation, and update
  the `should_treat_as_model_only` doc comment in the same change so code and doc agree:

  ```rust
  // openrouter.rs:788-792
  let allow = request.allow_model_only && request.evidence.is_empty();
  let limits = self.config.grounding_limits.with_allow_model_only(allow);
  ```

  mirroring the `ctx.evidence_blocks.is_empty()` conjunct at `generate.rs:146-149`.

### WR-03: Two divergent model-only prompt constructions; `ctx.assembled_prompt` is still not the prompt that reaches the provider, and a new test pins the unused one

**File:** `engine/src/generation/openrouter.rs:263-267`, `engine/src/prompt.rs:225-227`, `engine/src/workflow/nodes/assemble_prompt.rs:77`, `engine/src/workflow/events.rs:229`, `engine/src/tests/workflow_phase5.rs:5790-5798`

**Issue:** `pack_model_only_prompt` (`prompt.rs:225-227`) produces
`"{policy}\n\nQuestion: {q}\n"` as a single string. The adapter produces a *different* shape —
policy as `messages[0]`, `"Question: {q}\n"` as `messages[1]` (`openrouter.rs:263-267`) — and
never calls `pack_model_only_prompt`. Grepping the crate, `ctx.assembled_prompt` still has
exactly two non-test consumers: `workflow/mod.rs:266` (the inline test remainder) and
`workflow/events.rs:229` (the checkpoint serializer). So `AssemblePromptNode`'s model-only
output remains dead relative to the wire, and a checkpoint replay of a model-only run records a
prompt string that was never sent. This is the one sub-item of prior CR-02 that `953b22c` did not
address.

The new test `pack_model_only_prompt_uses_ungrounded_policy` (`workflow_phase5.rs:5790-5798`)
pins a function that production never invokes, which reads as SC3 coverage but is not.

**Fix:** Pick one owner. Either have `pack_openrouter_messages` call
`crate::prompt::pack_model_only_prompt(question)` for its user message (keeping the policy in
`messages[0]` and deriving the user message from the shared function), or delete the
`assemble_prompt.rs:77` branch and let the adapter own model-only prompt construction outright.
Two independently-editable definitions of the same prompt is how the original SC3 gap arose.

### WR-04: The new citation dedup predicate is broader than the invariant it needs

**File:** `engine/src/prompt.rs:603-605`

**Issue:**

```rust
if !citations.iter().any(|c: &StructuredCitation| {
    c.marker_id == block.id || c.chunk_id == block.chunk_id
}) {
```

The `|| c.chunk_id == block.chunk_id` disjunct collapses two *distinct* markers whenever their
resolved blocks share a `chunk_id`, silently emitting one `StructuredCitation` for two cited
markers. Today this has **no reachable path**: fusion keeps one canonical candidate per
`chunk_id` (`engine/src/retrieval/fusion.rs:3, 72-77`), so evidence blocks always carry distinct
`chunk_id`s. It is flagged because the guard is unnecessary for the bug it was added to fix —
`marker_id` alone is sufficient, since `block.id` is what both lookup spellings resolve to — and
because it converts a future fusion-invariant change into silent citation loss rather than a
visible duplicate.

**Fix:** Narrow the predicate to `c.marker_id == block.id`. The existing test
`resolve_citations_with_max_chars_dedupes_duplicate_ids` (both the repeated-marker and
`"7"`/`"[7]"` cases) still passes, since both spellings resolve to the same `block.id`.

### WR-05: New helper uses `#[allow]` instead of `#[expect]` and takes a positional bool among positional integers

**File:** `engine/src/generation/openrouter.rs:245-254`

**Issue:** `rust-guidelines.md` M-LINT-OVERRIDE-EXPECT requires lint overrides to use
`#[expect]` so a no-longer-needed suppression is caught by the compiler; the new
`pack_openrouter_messages` uses `#[allow(clippy::too_many_arguments)]`. Separately, the
signature is `(.., evidence_budget: usize, max_output_tokens: usize, allow_model_only: bool,
cancel: &CancellationToken)` — a bare positional bool wedged between two same-typed integers at
the one call site that decides whether the fail-closed guard applies
(`openrouter.rs:534-543`). A transposition there is silent at compile time and flips the
security-relevant default.

**Fix:** Use `#[expect(clippy::too_many_arguments, reason = "...")]`, and group the packing
inputs into a small `PackingInputs` struct (or at minimum introduce a
`#[derive(Clone, Copy)] enum EvidencePolicy { Grounded, AllowModelOnly }`) so the flag cannot be
positionally confused.

---

## Carried Forward From Pre-Gap-Closure Review

The prior full-scope review (`195edb2`) recorded 18 findings. Dispositions below; still-open
items are **not** counted in the frontmatter totals.

| Prior ID (from `195edb2`) | Disposition |
|---|---|
| CR-01 (citation repair fails on duplicate cited IDs) | **resolved** — dedup guards at `generate.rs:198-207` and `prompt.rs:603-605`; both repro cases verified passing by targeted `cargo test` run |
| CR-02 (model-only opt-in dead in production) | **partial** — adapter empty-evidence branch resolved (`openrouter.rs:263-267`); schema enum resolved (`openrouter.rs:570`); `base_system_policy` reuse resolved (`prompt.rs:218-227`). **Still open:** the policy omits the `answer_basis` instruction and both sites validate the unmodified output (new CR-02 above), and `ctx.assembled_prompt` is still unread on the generation path (new WR-03 above) |
| CR-03 (total-drop yields MODEL_ONLY basis with no MODEL_ONLY notice, against an explicit opt-out) | **still open** — `generate.rs:240-266` is byte-identical in `953b22c`; `citation_repair_enabled_drops_unresolvable_marker_and_emits_notice` still passes with `ctx.allow_model_only == false` and no `NoticeCode::ModelOnly` emitted on that route |
| CR-04 (env-override prefix separator) | **deferred** — Phase 6.1 per `.planning/ROADMAP.md` |
| CR-05 (`degraded_mode` always false) | **deferred** — Phase 6.1 per `.planning/ROADMAP.md` |
| WR-01 (`run_inline_prompt_generation_remainder` is a `pub` generation path with no grounding validation) | **still open** — `workflow/mod.rs:294` adds only the `allow_model_only` field; the function is still `pub`, still never calls `validate_grounding_with_limits`, still never runs the D-14 repair pass, still never populates `ctx.structured_citations`, and still carries its own divergent model-only rule at `mod.rs:311-323` |
| WR-02 (`ANSWER_BASIS_UNSPECIFIED` on successful zero-evidence responses) | not re-checked (outside pinned scope — `runner.rs`, `proto/`) |
| WR-03 (dead `_disable_graph_context` binding) | not re-checked (outside pinned scope — `service.rs`) |
| WR-04 (dead `GRAPH_TIMEOUT`/`GRAPH_DEGRADED` constants) | **still open** — `workflow/mod.rs:27-28` unchanged; grep across `engine/` finds no identifier reference, only unrelated string literals in tests |
| WR-05 (blank telemetry import) | not re-checked (outside pinned scope — `gateway/`) |
| WR-06 (gateway drops two `RetrievalSnapshot` fields) | not re-checked (outside pinned scope — `gateway/`) |
| WR-07 (checkpoint snapshot missing `typed_code` and two context fields) | not re-checked (outside pinned scope — `workflow/events.rs`) |
| WR-08 (`invalid_settings` disposition mismatch) | not re-checked (outside pinned scope — `bad_input_matrix.rs`, `service.rs`) |
| WR-09 (prod TLS guard matches only `sslmode=disable`) | not re-checked (outside pinned scope — `gateway/`) |
| WR-10 (tautological fake-asserting tests) | not re-checked (outside pinned scope — `workflow/ports.rs`) |
| WR-11 (test-gate script: hardcoded developer home path, no `pipefail`) | **still open** — `953b22c` touched this file but changed only the pinned counts. `scripts/engine-test-targets.sh:7` still contains `/mnt/c/Users/user3/.cargo/bin` and `/c/Users/user3/.cargo/bin`; line 29 is still an unguarded pipeline under `/bin/sh` with `set -e` and no `pipefail`, so a build failure still reports as `TOTAL test count mismatch: expected 380, got 0` |
| WR-12 (cancelled run emits spurious `RETRIEVAL_DEGRADED_*`) | not re-checked (outside pinned scope — `nodes/retrieve.rs`) |
| WR-13 (README says Phase 6 has not started) | not re-checked (outside pinned scope — `README.md`) |

---

_Reviewed: 2026-08-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
