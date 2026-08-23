---
phase: 06-observability-evaluation-polish
reviewed: 2026-08-22T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - engine/src/tests.rs
  - engine/src/tests/workflow_phase5.rs
  - engine/src/tests/workflow_phase5_production.rs
  - engine/src/workflow/nodes/generate.rs
  - scripts/engine-test-targets.sh
findings:
  critical: 0
  warning: 3
  info: 0
  total: 3
status: issues_found
---

# Phase 06: Code Review Report

**Reviewed:** 2026-08-22T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

This is a re-review of the 06-16 gap-closure delta (commit `949673e`, parent `d171e4d`), which
closes two UAT-reported blocker gaps: G-06-1 (total citation drop bypassing `allow_model_only`)
and G-06-2 (citations to truncated-out evidence blocks resolving and shipping excerpts). The only
production-code change in this delta is a one-line fix in `engine/src/workflow/nodes/generate.rs`;
the rest of the delta is regression-test coverage and a test-count bookkeeping update in
`scripts/engine-test-targets.sh`.

**G-06-1 verified correct.** `generate.rs:258` now sets `effective_allow = ctx.allow_model_only`
(previously `ctx.allow_model_only || total_drop`). Traced through
`GenerationOutput::validate_output_shape_with_limits` (`engine/src/generation/mod.rs:184-219`):
when `allow_model_only` is false and a total citation drop forces `AnswerBasis::ModelOnly` via
`into_model_only()`, the `!limits.allow_model_only && self.answer_basis == AnswerBasis::ModelOnly`
check (line 188) now correctly rejects the response, propagating as
`NodeErrorKind::LlmGenerationFailed`. Confirmed this is a genuine regression fix, not a
tautology: under the pre-fix formula, `effective_allow` would have evaluated to `true` for every
test added in this delta that asserts a flag-off failure (since `total_drop` was always `true` in
those fixtures), so the new assertions are discriminating, not vacuous. Ran
`citation_repair_total_drop_flag_off_fails_closed`,
`openrouter_node_total_citation_loss_flag_off_fails_closed`, and the full `citation_*` test set
directly — all pass, and the OpenRouter-backed variant additionally asserts `chat_calls == 1` to
confirm the fail-closed path executed a real HTTP round trip rather than short-circuiting.

**G-06-2 verified correct, with a caveat that it required no production-code change.** No file in
this delta other than `generate.rs`'s one-line diff touches production code, and that diff is
G-06-1's fix only. G-06-2's "fix" is that `AssemblePromptNode::run`
(`engine/src/workflow/nodes/assemble_prompt.rs`, unchanged in this delta) already overwrites
`ctx.evidence_blocks = packed.evidence` with the token-budget-truncated subset before
`GenerateAnswerNode` runs, and `GenerateAnswerNode` already builds its marker-resolution universe
(`evidence_ids`) from `ctx.evidence_blocks` (`generate.rs:187-188`) — so a citation naming a
truncated-out block was already unresolvable and already dropped via the existing
`citations::resolve_markers` path, pre-dating this plan. Confirmed via `service.rs:139` /
`service.rs:148-149` that `AssemblePromptNode` is wired before `GenerateAnswerNode` in the
production graph, so `ctx.evidence_blocks` really is the packed subset by the time citation
resolution runs, not the full retrieved set.

Verified the discriminating claim empirically rather than by inference: I built a standalone
harness (outside the reviewed repo, in the review scratchpad) that links `engine` as a library and
calls `pack_evidence_and_graph_prompt` directly with the exact two `EvidenceBlock` values and
budget (`max_prompt_tokens=250, answer_token_budget=20`) used by
`workflow_prompt_packing_truncation_drops_citation_to_truncated_block`. Result: `packed evidence
count = 1`, containing only block `[1]` — block `[2]` is genuinely dropped by token-budget
truncation, not merely absent from a pre-truncated fixture. This confirms the end-to-end test does
exercise real 2-in/1-out packing truncation (retrieval itself delivers both candidates to the
packing stage, since `DEFAULT_FINAL_LIMIT = 8` far exceeds the 2 candidates supplied). The three
unit-level sibling tests (`citation_to_truncated_block_is_dropped_and_ships_no_excerpt_flag_off_fails_closed`,
`..._flag_on_succeeds_model_only`, `citation_to_surviving_and_truncated_blocks_resolves_surviving_and_drops_truncated`)
each carry multiple discriminating assertions (basis, notice codes, citation lists, and — in the
mixed case — the exact stripped answer text and stripped structured-citation set), so none of them
match the WR-03-in-the-prior-round vacuous-counter pattern flagged by the scope note. See WR-03
below for a related robustness gap in how the end-to-end test pins that mechanism going forward.

Test-target-count bookkeeping in `scripts/engine-test-targets.sh` (386→392, lib 351→357) was
independently verified by running the script; it reports 392 total / 357 lib and all 7 invariants
pass, matching the new counts exactly.

Three quality issues (WARNING) were found: a stale comment in `generate.rs` that misdescribes the
now-flag-dependent total-drop behavior; a coverage/naming regression in `tests.rs` where the only
service-boundary (`execute_query_rag`) test for the total-citation-drop scenario was flipped from
flag-off/reject to flag-on/succeed, leaving no test of the fail-closed path at the actual
client-facing service boundary while the test's name still promises rejection; and a robustness
gap in the G-06-2 end-to-end test, which does not directly assert that packing truncation occurred
and so would keep passing even if a future change caused retrieval (rather than packing) to be the
reason block `[2]` never reaches `GenerateAnswerNode`.

## Warnings

### WR-01: Stale comment misdescribes total-citation-drop behavior post-fix

**File:** `engine/src/workflow/nodes/generate.rs:239-241`
**Issue:** The comment directly above the `total_drop` computation reads:

```rust
// Total citation loss: markers existed but none survived repair.
// Validated (and later reconciled) as model-only rather than failing
// the run — the answer lost all grounding, it did not become invalid.
let total_drop = !markers.is_empty() && repaired_citations.is_empty();
```

This was accurate under the pre-G-06-1 formula (`effective_allow = ctx.allow_model_only ||
total_drop`), where a total drop unconditionally downgraded to model-only and never failed the
run. After this delta's fix (`effective_allow = ctx.allow_model_only`, line 258, seven lines
below this comment), a total drop only downgrades to model-only when `allow_model_only` is `true`;
when it is `false`, the same total drop now fails the run with `NodeErrorKind::LlmGenerationFailed`
(exactly the behavior `citation_repair_total_drop_flag_off_fails_closed` and
`openrouter_node_total_citation_loss_flag_off_fails_closed` exist to pin). The comment's
unqualified claim "rather than failing the run" is now wrong for the `allow_model_only = false`
case and will mislead the next person reading this branch into reintroducing the G-06-1 bug (e.g.
by "restoring" the OR into `effective_allow` to make the comment true again).
**Fix:**
```rust
// Total citation loss: markers existed but none survived repair. Whether this
// downgrades to model-only or fails the run is flag-dependent (see
// `effective_allow` below): when `allow_model_only` is true, it is validated
// (and later reconciled) as model-only rather than failing; when false, the
// grounding-limits check below fails the run closed (G-06-1).
let total_drop = !markers.is_empty() && repaired_citations.is_empty();
```

### WR-02: Service-boundary fail-closed coverage for total citation drop was removed, and the surviving test's name now contradicts its body

**File:** `engine/src/tests.rs:3606-3671` (test `query_rag_rejects_unknown_marker_without_response`)
**Issue:** This delta changed the test from using the default `allow_model_only` (`req` built via
`test_query_request`, which leaves `allow_model_only` as `None`) to `req.allow_model_only =
Some(true)`, and changed the assertion from expecting an error to
`execute_query_rag(&service, req).await.expect(...)` succeeding with a model-only degraded answer.
Confirmed `None` resolves to `false` at the point this matters: `WorkflowContext::new`
(`engine/src/workflow/mod.rs:115`) does `allow_model_only: request.allow_model_only.unwrap_or(false)`.
So pre-delta this test ran with effectively `allow_model_only = false`, and — before the G-06-1
fix — it passed only because the buggy `effective_allow = ctx.allow_model_only || total_drop`
forced `true` anyway on a total drop; the test's old body correctly expected that success.

This delta's flip to `Some(true)` is a necessary consequence of the G-06-1 fix (with the fix
applied, the old flag-off/implicit-false body would need to become `.expect_err(...)` instead, not
be deleted), but flipping the existing test to flag-on instead of adding a flag-off sibling has
two consequences:

1. **Coverage regression at the actual client-facing boundary.** Enumerating every flag-off /
   total-drop test added or retained in this delta: `citation_repair_total_drop_flag_off_fails_closed`
   and `citation_to_truncated_block_is_dropped_and_ships_no_excerpt_flag_off_fails_closed` (both
   call `GenerateAnswerNode::run` directly), and
   `openrouter_node_total_citation_loss_flag_off_fails_closed` (calls the node directly against a
   real `OpenRouterGenerator`). None of these go through `execute_query_rag`, which is the
   function that actually decides what a client receives (error vs. response) and previously had
   exactly one test for this scenario. After this delta, `execute_query_rag` with a total citation
   drop and `allow_model_only` unset/false is untested end-to-end — the layer between the node's
   `NodeError` and whatever `execute_query_rag` surfaces to the RPC caller (error propagation,
   status mapping, etc.) is exercised by node-level tests only, not by the actual service entry
   point the gap report was about ("don't ship a response that lost its grounding").
2. **Name/body mismatch.** The test is still named `query_rag_rejects_unknown_marker_without_response`,
   but its body no longer rejects anything — it now asserts success (`.expect("unresolvable
   citation degrades the answer instead of failing the run")`) and inspects the degraded response.
   A maintainer skimming test names for fail-closed coverage will conclude this scenario is
   covered at the service boundary when it is not.

**Fix:** Rename this test to reflect what it now verifies (e.g.
`query_rag_total_drop_flag_on_degrades_to_model_only`), and add a sibling
`query_rag_total_drop_flag_off_fails_closed` (or restore the original flag-off body under a new
name) that calls `execute_query_rag` with `allow_model_only` unset/false and an
unresolvable-marker `FakeGenerator` response, asserting `execute_query_rag(...).await.is_err()`
(or the equivalent gRPC-status-mapped error), so the fail-closed guarantee is pinned at the same
boundary a real client observes it at.

### WR-03: G-06-2 end-to-end test doesn't directly assert that *packing* (not retrieval) caused the truncation it depends on

**File:** `engine/src/tests/workflow_phase5.rs` (test
`workflow_prompt_packing_truncation_drops_citation_to_truncated_block`)
**Issue:** This test's assertions are: `final_answer.answer_basis == Retrieval`,
`final_answer.citations == ["[1]"]`, `final_answer.structured_citations.len() == 1` with
`chunk_id == "chk-1"`, and a `CITATION_DROPPED` notice present. I independently confirmed (via a
standalone harness calling `pack_evidence_and_graph_prompt` directly with this test's exact inputs
and budget) that these assertions currently hold *because* `AssemblePromptNode` genuinely
truncates two packed candidates down to one (`packed evidence count = 1`), which is the behavior
G-06-2 is about. However, the test itself asserts none of that directly — it only asserts the
downstream consequence (citation `[2]` is absent and dropped). The same five assertions would also
pass under a future regression where, e.g., a retrieval-side change (`RetrievalSettings::final_limit`,
fusion/dedup logic, a scoring tie-break) caused only one candidate to ever reach
`AssemblePromptNode` in the first place — at that point the test would silently stop exercising
packing truncation at all while continuing to report green, defeating its stated purpose as the
regression test for G-06-2's "truncated-but-retrieved" scenario.
**Fix:** Add a direct assertion that packing itself did the truncating, not just that citation `[2]`
is absent downstream — e.g. assert `ctx`/event-visible evidence-block count after `AssemblePromptNode`
is 1 while retrieval delivered 2 (surface this via an event or a debug-only field if not already
observable), or at minimum assert on a `PromptAssemblyFailed`/truncation-adjacent notice if one
exists, so the test fails loudly (rather than silently passing for the wrong reason) if retrieval
ever starts doing the narrowing instead of packing.

---

_Reviewed: 2026-08-22T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
