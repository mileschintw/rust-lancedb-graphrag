---
status: testing
phase: 06-observability-evaluation-polish
source: [06-VERIFICATION.md]
started: 2026-08-22T21:30:00.000Z
updated: 2026-08-22T21:30:00.000Z
---

## Current Test

number: 1
name: Decide the intended flag-off semantics on the D-18 total-drop path, then pin it with a test
expected: |
  Either (a) confirm the downgrade is intentionally flag-independent and record that decision,
  or (b) scope the relaxation to the disclosure and keep `LlmGenerationFailed` when the flag is
  off. Before this delta the same exchange returned `LlmGenerationFailed`.
awaiting: user response

## Tests

### 1. Decide the intended flag-off semantics on the D-18 total-drop path, then pin it with a test

Set `allow_model_only = false`, evidence `["[1]"]`, and have the model return `answer_basis:
"retrieval"` with `cited_evidence_ids: ["[9]"]` and answer text citing only `[9]`. Today
`effective_allow = ctx.allow_model_only || total_drop` (`generate.rs:255`) makes the run succeed
with `ANSWER_BASIS_MODEL_ONLY`.

expected: Either (a) confirm the downgrade is intentionally flag-independent and record that decision, or (b) scope the relaxation to the disclosure and keep `LlmGenerationFailed` when the flag is off. Before this delta the same exchange returned `LlmGenerationFailed`.
why_human: Contract choice, not a defect. No ROADMAP Success Criterion governs it — SC3's flag-off clause is scoped by its own parenthetical to (D-10, D-11, D-12), while the total-drop reconciliation path is D-18, grouped with DEBT-RAG-03/SC5 (06-11). Raised as code-review CR-02; orchestrator ruled it spec-conformant. The behavior change is real and newly production-reachable either way, and `openrouter_node_model_only_flag_off_stays_fail_closed` cannot detect it because that test never reaches the provider.
result: [pending]

### 2. T-06-15-03 / backstop must_have — citation naming a retrieved-but-truncated block

Construct a retrieval result whose evidence set is larger than what fits in
`allowed_evidence_tokens`, so `pack_evidence_and_graph_prompt` truncates block `[N]` out of the
prompt. Have the model emit `[N]` as a citation.

expected: Decide whether a citation naming a retrieved-but-truncated block should resolve (today it does, and its excerpt is shipped to the client via `resolve_citations(&ctx.citations, &ctx.evidence_blocks)`) or fail closed (pre-split behavior).
why_human: `insufficient_spec` — this must_have carries `verification: backstop` in 06-15-PLAN.md, and Step 5b forbids inferring it from presence and wiring. No test in the repository exercises a truncated-block marker. Confirmed by primary evidence: at `953b22c:openrouter.rs:792` the adapter validated markers against `validation_evidence = packed_evidence.evidence` (the subset actually sent to the model); today no code path validates against the packed subset — the adapter discards it as `_validation_evidence` (`openrouter.rs:534`) and all four downstream gates bind to `ctx.evidence_blocks`.
result: [pending]

### 3. Decide whether the D-18 total-drop path should emit `NOTICE_CODE_MODEL_ONLY`

Today it emits `CITATION_DROPPED` + `BASIS_RECONCILED` and sets `answer_basis = MODEL_ONLY`, but
no `MODEL_ONLY` notice — unlike branch 1 (`generate.rs:167-171`) and the inline remainder
(`workflow/mod.rs:361-365`).

expected: Either add the notice so "MODEL_ONLY basis implies a MODEL_ONLY notice" holds on all three paths, or record that `BASIS_RECONCILED` is the intended machine-readable disclosure for this path.
why_human: SC5's text requires only "downgrades the basis if all grounding is lost" — it does not require a MODEL_ONLY notice, and `BASIS_RECONCILED` + `CITATION_DROPPED` are both machine-readable, so the phase user story ("without parsing prose") is satisfied. Cross-path invariant question, not an SC failure. Raised as CR-01; orchestrator downgraded to info as spec-conformant.
result: [pending]

### 4. Review the four unresolved specless-probe edges

Review the four specless-probe edges 06-15-PLAN.md declares unresolved (unclassified RAG-03,
DEBT-RAG-01, DEBT-RAG-06; DEBT-RAG-05 concurrency) and decide whether each needs coverage before
the phase closes.

expected: Each edge is either given a probe/test or explicitly recorded as accepted-uncovered.
why_human: judgment-tier prohibition, status `flagged-unverified`. No `06-SPEC.md` exists, so there is no contract to verify against — the plan explicitly declines to treat them as covered and the verification report does not absorb them into the pass. Prohibitions P2 (no ungated generator path) and P3 (no test double as SC3/SC5 proof) were affirmatively resolved by codebase evidence this round and are NOT carried forward.
result: [pending]

### 5. Run `/gsd-secure-phase 6` to produce `06-SECURITY.md`

expected: The phase security gate closes.
why_human: `workflow.security_enforcement` is active and no `06-SECURITY.md` exists. Non-blocking for goal achievement; blocking for phase advancement. Routing item only.
result: [pending]

### 6. Run `/gsd-validate-phase 6` to refresh `06-VALIDATION.md`

expected: Nyquist coverage is established for plans 06-08 through 06-15.
why_human: `06-VALIDATION.md` is `status: draft`, `nyquist_compliant: false`, dated 2026-08-20 — it predates plans 06-08..06-15. The §7.5 gate checks existence only, so coverage for the new work is not established. Routing item only.
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
