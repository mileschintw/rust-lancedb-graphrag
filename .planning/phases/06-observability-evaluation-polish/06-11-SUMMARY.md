---
phase: 06-observability-evaluation-polish
plan: 11
subsystem: rag-generation
tags: [citation-repair, unicode-normalization, answer-basis, prompt-policy, config]

requires:
  - phase: 06-observability-evaluation-polish (plan 06-07)
    provides: typed Notice constructor and the CitationRepaired/CitationDropped/BasisReconciled NoticeCode enum values
  - phase: 06-observability-evaluation-polish (plan 06-06)
    provides: malformed-citation fake-generator constructors (near-miss / unresolvable) used as design references
  - phase: 06-observability-evaluation-polish (plan 06-10)
    provides: the fail-closed env-override shape (D-84) and WorkflowConfigSettings/WorkflowSettings pattern this plan mirrors for citation_repair_enabled
provides:
  - "engine::generation::citations — deterministic, network-free citation-marker extraction, normalization and resolution"
  - "engine.workflow.citation_repair_enabled configuration key with fail-closed env override"
  - "D-18 conservative-wins answer-basis reconciliation at the single WorkflowContext::update_from_model_output seam"
  - "D-17 evidence-over-priors precedence sentence in the system policy"
  - "repair-strip-notice integration replacing the fail-closed citation branch in GenerateAnswerNode"
affects: [06.4-docs-and-limitations, rag-query-http-contract]

actuals:
  tokens: 18005
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "Pure-transform module (engine/src/generation/citations.rs) mirroring engine/src/retrieval/fusion.rs's shape: free functions, no I/O, deterministic tie rules, module-level //! doc contract"
    - "Basis-agnostic vs basis-forcing ModelOutput clone helpers (with_answer_and_citations, into_model_only) that route through the single reconciliation seam instead of writing ctx.answer_basis a second time"
    - "Config toggle mirrors the D-84 fail-closed env-override shape from 06-10 (allow_model_only_answers -> citation_repair_enabled)"

key-files:
  created:
    - engine/src/generation/citations.rs
  modified:
    - engine/src/generation/mod.rs
    - engine/src/config.rs
    - config/config.toml
    - engine/tests/config_startup.rs
    - engine/src/workflow/mod.rs
    - engine/src/prompt.rs
    - engine/src/workflow/nodes/generate.rs
    - engine/src/service.rs
    - engine/src/tests/workflow_phase5.rs
    - engine/src/tests/workflow_phase5_production.rs
    - engine/src/tests.rs
    - scripts/engine-test-targets.sh

key-decisions:
  - "Repair-then-validate ordering: the repair pass runs on the raw ModelOutput and validate_grounding_with_limits runs on the repaired view, not the reverse — validation's citation-identity checks would otherwise reject a near-miss marker before repair ever saw it."
  - "Citation repair only replaces the fail-closed branch that existed when grounding_limits is configured; when grounding_limits is None (no strict validation applies), citation resolution is unchanged from before this plan."
  - "The engine's observable assessment for D-18 reconciliation is two-valued: citations present -> retrieval-strength, citations absent -> model-only. There is no engine signal to distinguish retrieval from mixed independently of the model's own claim."
  - "FakeGenerator::malformed_citation_near_miss()'s marker '(1)' is parenthesized; the locked widened-extraction grammar is bracket-delimited only, so that fixture is unreachable by the repair pass. Task 3's repair-path tests build ModelOutput inline with bracketed near-miss markers instead (documented under Known Gaps)."

patterns-established:
  - "citations.rs: extract_markers (widened [ ws? digits ws? ] scan) -> resolve_markers (normalize + exact-one-match) -> resolve_answer_markers convenience composition"

requirements-completed: [RAG-03]

coverage:
  - id: D1
    description: "Near-miss citation markers (case, whitespace, marker-syntax variants, and the [ 7 ] internal-whitespace case) normalize onto the correct evidence identifier and are repaired in both the answer text and the citation list, with a CITATION_REPAIRED notice naming the original span."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/generation/citations.rs#tests (11 cases)"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#citation_repair_enabled_repairs_near_miss_marker_and_emits_notice"
        status: pass
    human_judgment: false
  - id: D2
    description: "An unresolvable citation marker is stripped from the answer text and both citation lists (never left half-removed), with a CITATION_DROPPED notice naming the original span; two distinct unresolvable spans produce two distinct notices."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#citation_repair_enabled_drops_unresolvable_marker_and_emits_notice"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#citation_repair_enabled_drops_internal_whitespace_marker_when_unresolvable"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#citation_repair_enabled_two_dropped_markers_produce_two_distinct_notices"
        status: pass
    human_judgment: false
  - id: D3
    description: "The repair pass makes no additional provider call; a repaired run's generator invocation count equals an unrepaired run's."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#citation_repair_makes_no_additional_provider_call"
        status: pass
    human_judgment: false
  - id: D4
    description: "Total citation loss (every marker dropped) downgrades the answer basis and succeeds instead of failing the run, with a BASIS_RECONCILED notice alongside the drop notices."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#citation_repair_total_drop_downgrades_basis_and_succeeds"
        status: pass
      - kind: unit
        ref: "engine/src/tests.rs#query_rag_rejects_unknown_marker_without_response (updated to the new contract)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Repair disabled reproduces today's exact fail-closed behavior (same NodeErrorKind, same message), and the healthy all-resolved path is silent (no repair/drop notices)."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#citation_repair_disabled_fails_exactly_as_before"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#citation_repair_healthy_path_emits_no_repair_or_drop_notices"
        status: pass
    human_judgment: false
  - id: D6
    description: "D-18 conservative-wins basis reconciliation: agreement is silent, disagreement weakens toward model-only and emits BASIS_RECONCILED, and reconciliation never strengthens a claim (model-only self-report with resolving citations stays model-only)."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#basis_reconciliation_retrieval_self_report_with_resolving_citations_stays_retrieval"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#basis_reconciliation_retrieval_self_report_with_no_citations_weakens_and_notes"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#basis_reconciliation_mixed_self_report_with_no_citations_weakens_and_notes"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#basis_reconciliation_model_only_self_report_with_resolving_citations_stays_model_only"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#basis_reconciliation_agreement_stays_silent"
        status: pass
    human_judgment: false
  - id: D7
    description: "The evidence-over-priors precedence sentence is in the system policy and appears exactly once in an assembled grounded-query prompt; the structured-output schema and provider request contract are unchanged."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#system_policy_states_evidence_precedence_exactly_once"
        status: pass
      - kind: unit
        ref: "engine/src/tests/workflow_phase5.rs#generation_request_contract_unchanged_by_precedence_change"
        status: pass
    human_judgment: true
    rationale: "No test exercises the live OpenRouter request body (that machinery lives in engine/src/generation/tests.rs, outside this plan's file scope); schema/response-format invariance is proven structurally instead (git diff on openrouter.rs and Cargo.toml is empty) and via the GenerationRequest contract test. A human should confirm this substitution is acceptable rather than auto-passing on it."
  - id: D8
    description: "The citation-repair configuration key (citation_repair_enabled) fails closed on a present-but-invalid environment value, naming the key and the offending value; empty/whitespace is treated as absent; true/false and 1/0 are both recognized."
    requirement: "RAG-03"
    verification:
      - kind: integration
        ref: "engine/tests/config_startup.rs#citation_repair_enabled_invalid_env_fails_closed"
        status: pass
      - kind: integration
        ref: "engine/tests/config_startup.rs#citation_repair_enabled_recognizes_true_and_false_env_overrides"
        status: pass
      - kind: integration
        ref: "engine/tests/config_startup.rs#citation_repair_enabled_defaults_to_true_with_shipped_config"
        status: pass
      - kind: integration
        ref: "engine/tests/config_startup.rs#citation_repair_enabled_empty_or_whitespace_env_treated_as_absent"
        status: pass
    human_judgment: false

duration: 95min
completed: 2026-08-21
status: complete
---

# Phase 6 Plan 11: Citation Repair, Basis Reconciliation, and Evidence Precedence Summary

**Unresolvable citations degrade instead of failing the run: a local normalize-then-strip pass repairs near-miss markers or strips unresolvable ones, the answer basis reconciles conservatively against what the engine can actually observe, and the prompt states that evidence outranks the model's priors.**

## Performance

- **Duration:** 95 min
- **Started:** 2026-08-21T00:00:00Z (approx.)
- **Completed:** 2026-08-21
- **Tasks:** 3
- **Files modified:** 12 modified, 1 created

## Accomplishments

- **`engine/src/generation/citations.rs`** (new): a pure, synchronous, network-free module that extracts widened `[` + optional ASCII whitespace + digits + optional ASCII whitespace + `]` marker spans from an answer, normalizes both markers and evidence identifiers through one shared function, and resolves each marker to exactly one evidence identifier or drops it (zero matches or an exact tie both drop — never assigned to a candidate). 11 behavior tests, zero occurrences of `reqwest`/`http`/`Client`/`async`/`await`.
- **`citation_repair_enabled`** configuration key (default `true`) in `[engine.workflow]`, with a fail-closed `LANCET_ENGINE__WORKFLOW__CITATION_REPAIR_ENABLED` override matching the D-84 shape from plan 06-10. 4 new `config_startup.rs` integration tests.
- **D-18 conservative-wins basis reconciliation** at the single `WorkflowContext::update_from_model_output` seam: the model's self-reported basis is weakened toward the engine's own (coarse) observation — citations present is treated as at-least-retrieval-strength, citations absent as model-only — and a `BASIS_RECONCILED` notice fires only when the reconciled value differs from the self-report. 7 behavior tests.
- **D-17 evidence-over-priors precedence sentence** appended to the existing system policy string in `engine/src/prompt.rs`; the structured-output schema is untouched (verified by an empty diff on `engine/src/generation/openrouter.rs`).
- **The fail-closed citation branch in `GenerateAnswerNode::run`** is replaced, when `citation_repair_enabled` and `grounding_limits` are both set, with repair-strip-notice: near-miss markers are repaired in place (answer text + citation list), unresolvable ones are stripped from both, and total citation loss re-enters as model-only through the single reconciliation seam instead of failing. Repair disabled (or no `grounding_limits`) reproduces today's behavior exactly. 8 behavior tests.

## Task Commits

Each task was committed atomically:

1. **Task 1: Build the deterministic citation normalization module and its configuration toggle** — `3bd539f` (feat)
2. **Task 2: Reconcile the answer basis conservatively and state the evidence-over-priors precedence in the prompt** — `d5b18dc` (feat)
3. **Task 3: Replace the fail-closed citation branch with repair, strip and notice** — `aa5615f` (feat)

_Note: this plan was not executed under TDD gate discipline (no separate RED/GREEN commits); each task's tests and implementation landed together in one commit, verified green before committing._

## Files Created/Modified

- `engine/src/generation/citations.rs` (new) — extraction, normalization, and resolution; 11 unit tests.
- `engine/src/generation/mod.rs` — `pub mod citations;`; three new `ModelOutput` helpers (`should_treat_as_model_only`, `into_model_only`, `with_answer_and_citations`).
- `engine/src/config.rs`, `config/config.toml` — `citation_repair_enabled` setting and fail-closed env override.
- `engine/tests/config_startup.rs` — 4 new integration tests (startup-configuration target 13 -> 17).
- `engine/src/workflow/mod.rs` — reconciliation logic (`weaker_basis`, `basis_label`) inside `update_from_model_output`.
- `engine/src/prompt.rs` — precedence sentence appended to `base_system_policy()`.
- `engine/src/workflow/nodes/generate.rs` — repair integration; D-10 model-only branch refactored to route through the new `ModelOutput` helpers so the file makes zero assignments to `answer_basis`.
- `engine/src/service.rs` — wires `citation_repair_enabled` into `GenerateAnswerNode` (deviation, see below).
- `engine/src/tests/workflow_phase5.rs` — 7 Task 2 tests + 8 Task 3 tests.
- `engine/src/tests/workflow_phase5_production.rs`, `engine/src/tests.rs` — pre-existing-test fixes (deviations, see below).
- `scripts/engine-test-targets.sh` — startup-configuration 13 -> 17, library 311 -> 337, total 342 -> 372.

## Implementation Details (required by plan `<output>`)

### Normalization steps, as implemented

`engine::generation::citations::normalize(value: &str) -> String`, applied identically to a marker's original text and to an evidence identifier before comparison:

1. Unicode compatibility composition (NFKC) via `unicode-normalization`.
2. Full Unicode case folding via `unicode-casefold`.
3. ASCII-whitespace trimming with internal-whitespace collapse (runs of any Unicode whitespace collapse to one ASCII space).
4. Stripping of surrounding marker syntax: `trim_matches` over `['[', ']', '(', ')']`, then a final `.trim()`.

### Tie rule

A marker resolves when its normalized form equals the normalized form of **exactly one** evidence identifier. Zero matches and two-or-more matches are both **dropped** — an ambiguous match is never assigned to the first or best candidate. A marker whose raw text equals the resolved identifier exactly, before normalization, is reported **unchanged** rather than **repaired**.

### Message templates, verbatim

- Repair: `citation marker '{original}' repaired to '{resolved}'`
- Drop: `citation marker '{original}' could not be resolved and was dropped`
- Reconciliation: `model self-reported basis '{self_reported}' but the engine observed '{engine_observed}'; reconciled to the more conservative basis '{reconciled}'`
  (basis labels are `retrieval` / `mixed` / `model_only`, matching `generation::AnswerBasis`'s existing `Display` spelling)

### Precedence sentence, verbatim

`When evidence contradicts your prior knowledge, the evidence is authoritative; say so.`

Appended to the existing system-policy literal in `engine/src/prompt.rs::base_system_policy()`, in the same backslash-continued-string style as the existing sentences.

### Engine-observable facts feeding reconciliation

The engine's observation is deliberately coarse, computed from the `ModelOutput` handed to `update_from_model_output` at the moment it is called:

- `cited_evidence_ids` **non-empty** -> treated as `retrieval`-strength (the engine has no independent signal to distinguish `retrieval` from `mixed`; that distinction is the model's own admission).
- `cited_evidence_ids` **empty** -> treated as `model_only` (the weakest tier).

For the repair path, this check runs against the **post-repair** citation list (the re-entry clone's `cited_evidence_ids`), so total citation loss — markers existed but none survived repair — naturally computes an `engine_observed` of `model_only` and reconciles down, without any special-cased basis assignment in `generate.rs`.

### Pre-existing tests changed by this plan, by name, with old and new expectations

- **`engine/src/tests.rs::query_rag_rejects_unknown_marker_without_response`** — Old: asserted `execute_query_rag(...).await.is_err()` for a model output citing a nonexistent marker `[99]`, under `EffectiveRagSettings::default()`. New: with `citation_repair_enabled` defaulting to `true`, the run now succeeds; asserts the response answer no longer contains `[99]`, both citation lists are empty, and a `CITATION_DROPPED` notice names `[99]`.
- No test in the codebase asserted the literal string `"failed to resolve all cited evidence identities completely"` before this plan (confirmed by search) — that branch existed in code but was unreachable in practice because `validate_grounding_with_limits`'s `cited_evidence_id ... is not in packed evidence` check already rejected an unknown marker first, whenever `grounding_limits` was configured. This plan's own `citation_repair_disabled_fails_exactly_as_before` test therefore asserts the message that check actually produces, not the resolve-count message; see Known Gaps.

### Accepted prompt-injection trade-off (deferred, recorded per D-17/D-19/D-71)

The precedence instruction deliberately raises the authority of retrieved evidence over the model's own priors: "when evidence contradicts your prior knowledge, the evidence is authoritative." This means hostile corpus content is trusted *more* after this change, not less — a corpus chunk that contradicts the model's training is now explicitly told to win. The existing mitigations are unchanged and still apply: the evidence token budget bounds what is packed, the structured-output schema constrains the response shape, and citations must resolve to real evidence chunks (repair strengthens this last one — an unresolvable citation can no longer silently pass through). The trade is intentional per the user's stated principle recorded in `06-CONTEXT.md`'s D-17.

**The eval metric for this instruction is deliberately deferred** — v1 ships the behavior unmeasured, matching D-17's recorded gap (D-45 tracks eventual measurement; Phase 6.4's D-71 is the docs home for this limitation).

### Test-target gate: before/after rows, verbatim

| Target | Before (06-10 baseline) | After Task 1 | After Task 3 (final) |
|---|---|---|---|
| `engine (lib)` | 311 | 311 (unchanged; Task 1's 11 module tests land inside the library count, but the script's LIB assertion was intentionally left red between Task 1 and Task 3 per the plan's protocol — see note) | 337 |
| `engine (bin)` | 0 | 0 | 0 |
| `inspect_lancedb (bin)` | 18 | 18 | 18 |
| `seed_rag_fixture (bin)` | 0 | 0 | 0 |
| `config_startup (test)` | 13 | 17 | 17 |
| **TOTAL** | 342 | (script red between Task 1 and Task 3 by design) | 372 |

Note on the "After Task 1" column: the script's `LIB_COUNT`/`LIB_BIN_SUM`/`TOTAL` assertions were deliberately **not** updated in Task 1's commit — only `INTEG_CONFIG_COUNT` (13 -> 17) — per the plan's scope rationale ("Task 1 updates the startup-configuration target ... All three tasks add library tests ... the library target is updated once, at the end of Task 3"). Running the full gate script against the Task-1-only commit would report `FAIL: TOTAL test count mismatch: expected 342, got 353` (311 library tests present but not yet asserted, plus the already-updated config count) — this is expected, not a defect; it was verified manually during development (not committed as a red state) and Task 3's commit lands the single library/total update that reconciles it. Final measured delta: **+26 library tests** = 11 (citations module, Task 1) + 7 (basis reconciliation + precedence, Task 2) + 8 (repair integration, Task 3).

Final gate run: `sh scripts/engine-test-targets.sh` exits 0 — "All 7 Rust test target invariants verified successfully." (lib: 337, bin: 0, inspect_lancedb: 18, seed_rag_fixture: 0, config_startup: 17, TOTAL: 372).

## Decisions Made

- **Repair-then-validate ordering.** `validate_grounding_with_limits`'s citation-identity checks (`cited_evidence_id ... is not in packed evidence`, inline-marker set equality) run on the **repaired** view (`for_validation`, built via `ModelOutput::with_answer_and_citations`), not the raw model output. Running validation on the raw output first — as the pre-existing code order did — would reject a near-miss marker before the repair pass ever saw it, since the identity check has no concept of "near miss," only "known" or "unknown." This ordering choice is the single most load-bearing decision in the plan; getting it backward would make repair unreachable for exactly the malformed inputs it exists to fix.
- **Repair gated on `grounding_limits.is_some()`.** D-14 replaces the fail-closed branch that existed specifically when `grounding_limits` is configured — that's the only place an unresolved citation was ever fatal. Discovered via a real regression: `workflow_answer_contract_preserves_all_fields` (a pre-existing test with no `grounding_limits` configured) broke when repair unconditionally derived the citation list from answer-text markers alone, discarding a valid `cited_evidence_ids` the model reported correctly but never echoed as an inline bracket in the answer text. Gating repair on `grounding_limits.is_some()` restores that path to its pre-plan behavior exactly.
- **The engine's observable assessment is two-valued, not three.** D-18 asks for "the more conservative basis wins" between the model's self-report and the engine's observation, but the engine genuinely cannot distinguish `retrieval` from `mixed` on its own — only "citations survived" (>= retrieval-strength) or "citations did not" (model-only). This is stated explicitly in the module's implementation rather than left implicit, since a future reader might otherwise assume a three-way engine judgment exists.
- **D-10's model-only branch was refactored, not left alone.** Task 3's acceptance criteria require zero occurrences of the substring `answer_basis` anywhere in `generate.rs`, but the pre-existing D-10 opt-in branch (from plan 06-10) both read and assigned `ctx.answer_basis` directly. Two new `ModelOutput` helpers (`should_treat_as_model_only`, `into_model_only`) move that logic into `generation/mod.rs` so the D-10 path also routes through the single `update_from_model_output` reconciliation seam instead of writing the field a second time. This was necessary to satisfy the plan's own acceptance gate, not optional polish.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `WorkflowSettings` exhaustive struct literal broke on the new field**
- **Found during:** Task 1, first full build after adding `citation_repair_enabled` to `WorkflowConfigSettings`/`WorkflowSettings`.
- **Issue:** `engine/src/tests/workflow_phase5_production.rs::workflow_phase5_settings_applied_to_production` constructs `WorkflowSettings { ... }` as an exhaustive literal (no `..Default::default()`); the compiler correctly rejected it as missing the new field.
- **Fix:** Added `citation_repair_enabled: true,` to the literal.
- **Files modified:** `engine/src/tests/workflow_phase5_production.rs`
- **Verification:** `cargo build --tests` succeeds.
- **Committed in:** `3bd539f` (Task 1 commit)

**2. [Rule 1 - Bug/regression] Tie-breaking test's razor-thin token budget broke from the D-17 sentence**
- **Found during:** Task 2, full test run after appending the precedence sentence to the system policy.
- **Issue:** `engine/src/tests.rs::pack_evidence_and_graph_prompt_breaks_exact_ties_in_evidence_favor` used a deliberately tight `max_prompt_tokens: 350` tuned to admit exactly 2 evidence blocks and exclude 1 graph fact. The precedence sentence raised the system policy's fixed token overhead, tightening the available evidence budget enough that only 1 evidence block fit instead of 2 — the test's tie-breaking assertion (`packed.evidence.len() == 2`) failed for a token-arithmetic reason unrelated to tie-breaking logic.
- **Fix:** Widened the budget `350 -> 380` (documented inline) to restore the boundary the test was designed to exercise.
- **Files modified:** `engine/src/tests.rs`
- **Verification:** `cargo test --lib` — test passes; `packed.evidence.len() == 2 && packed.graph_facts.len() == 0` holds again.
- **Committed in:** `d5b18dc` (Task 2 commit)

**3. [Rule 2 - Missing critical functionality] `citation_repair_enabled` was never wired into production**
- **Found during:** Task 3, after implementing the config key (Task 1) and the node-level toggle (Task 3's own `GenerateAnswerNode::with_citation_repair_enabled`).
- **Issue:** The plan's `files_modified` frontmatter does not list `engine/src/service.rs`, but without a call to `.with_citation_repair_enabled(effective_settings.workflow.citation_repair_enabled)` at the single `GenerateAnswerNode` construction site, the `citation_repair_enabled` config key — including its fail-closed environment override — would have no effect on the running service. The node's own default (`true`) happens to match the config default, masking the gap in the common case, but an operator setting the config or env var to `false` would have silently changed nothing. Threat register row T-06-11-06 (`mitigate`) depends on this key actually reaching production.
- **Fix:** Added the one-line `.with_citation_repair_enabled(...)` call in `service.rs`'s node-construction chain.
- **Files modified:** `engine/src/service.rs`
- **Verification:** `cargo build`; `query_rag_rejects_unknown_marker_without_response` (full-service integration test) now exercises this exact wiring end-to-end.
- **Committed in:** `aa5615f` (Task 3 commit)

**4. [Rule 2 - Missing critical functionality, structural] D-10 model-only branch refactored through new `ModelOutput` helpers**
- **Found during:** Task 3, running the task's own acceptance-criteria grep (`grep -c 'answer_basis' engine/src/workflow/nodes/generate.rs` must equal `0`).
- **Issue:** The pre-existing (06-10) D-10 opt-in branch read `ctx.answer_basis` in its condition and assigned it directly — both textually present as `answer_basis` in `generate.rs`, which the plan's own Task 3 acceptance criterion forbids (to keep basis assignment at the single `update_from_model_output` seam).
- **Fix:** Added `ModelOutput::should_treat_as_model_only(no_evidence: bool) -> bool` and `ModelOutput::into_model_only(&self) -> Self` in `generation/mod.rs`; `generate.rs` now calls these instead of touching the field directly, and the model-only branch re-enters through `ctx.update_from_model_output(&output.into_model_only())` rather than a second direct assignment.
- **Files modified:** `engine/src/generation/mod.rs`, `engine/src/workflow/nodes/generate.rs`
- **Verification:** `grep -c 'answer_basis' engine/src/workflow/nodes/generate.rs` = 0; `grep -c 'self.answer_basis' engine/src/workflow/mod.rs` = 2 (the pre-existing read in `to_query_rag_response` plus this plan's single reconciliation assignment); existing D-10 model-only tests (`model_only_opt_in_true_*`) all still pass unchanged.
- **Committed in:** `aa5615f` (Task 3 commit)

---

**Total deviations:** 4 auto-fixed (1 blocking compile break, 1 test-budget regression, 2 missing-critical-functionality gaps).
**Impact on plan:** All four were necessary for correctness (the missing-wiring ones) or to unblock the build/test suite (the other two). No scope creep beyond what each deviation required to fix.

## Known Stubs

None — no stubs introduced. `FakeGenerator::malformed_citation_near_miss()` (added by plan 06-06) is documented as **unused** by this plan's tests (see Known Gaps below) rather than silently ignored.

## Known Gaps

- **`FakeGenerator::malformed_citation_near_miss()` is unreachable by the repair pass and is not exercised by this plan's tests.** Its marker `"(1)"` is parenthesized; the locked widened-extraction grammar (Task 1's `extract_markers`) is bracket-delimited only (`[` ... `]`, tolerating interior whitespace) per the plan's own locked option (b), so a parenthesized marker is never located by the scan. Task 3's repair-path tests instead build `ModelOutput` inline with bracketed near-miss markers (e.g. `[ 7 ]` vs evidence `[7]`), matching the plan's own `<behavior>` block, which names only bracketed near-miss forms. `FakeGenerator::malformed_citation_unresolvable()` (bracketed `[9999]`) is used for the drop-path fixture reference. This is a finding, not a defect: the fixture remains available (and tested at the `FakeGenerator` level in `engine/src/generation/tests.rs`, unchanged by this plan) for a future plan that may want a citation-list-only (not answer-text) repair path.
- **The D-17 precedence instruction's effect is unmeasured (deferred by design, D-17/D-45).** No eval metric exists yet for whether the model actually follows the "evidence is authoritative" instruction; this ships as prompt text only, per the plan's explicit scope.
- **Structured-output-request byte-identity (`GenerationRequest::new` contract test) is a proxy, not a live-wire assertion.** The actual OpenRouter HTTP payload construction and its mock-server test harness live in `engine/src/generation/tests.rs`, outside every task's declared file scope for this plan. `git diff` confirms `engine/src/generation/openrouter.rs` and `engine/Cargo.toml` are both empty, which is the structural guarantee the plan's acceptance criteria actually require; the `GenerationRequest` contract test is additional, narrower proof. Flagged `human_judgment: true` in the coverage block above for this reason.

## Issues Encountered

None beyond the four deviations documented above, all resolved during execution.

## User Setup Required

None — no external service configuration required. The new `citation_repair_enabled` config key ships with a safe default (`true`) in `config/config.toml`; no action needed unless an operator wants to opt out.

## Next Phase Readiness

- All four RAG-03 clauses this phase set out to deliver are now complete: graph-unavailable degrade (06-08), per-path retrieval degrade (06-09), model-only opt-in (06-10), and citation repair with basis reconciliation (this plan).
- `sh scripts/engine-test-targets.sh`, `cargo test --manifest-path engine/Cargo.toml --locked`, `cargo clippy -- -D warnings`, `cargo fmt --check`, and `(cd gateway && go test ./...)` all exit 0 at HEAD.
- No blockers for Phase 6.4 (docs and limitations) or plan 06-12 (bad-input matrix); the latter's `<files>` and threat model are independent of this plan's changes.

---
*Phase: 06-observability-evaluation-polish*
*Plan: 11*
*Completed: 2026-08-21*

## Self-Check: PASSED

- `engine/src/generation/citations.rs` — FOUND
- `.planning/phases/06-observability-evaluation-polish/06-11-SUMMARY.md` — FOUND
- Commit `3bd539f` (Task 1) — FOUND
- Commit `d5b18dc` (Task 2) — FOUND
- Commit `aa5615f` (Task 3) — FOUND
- Full verification suite at HEAD (`cargo test --manifest-path engine/Cargo.toml --locked`, `cargo clippy -- -D warnings`, `cargo fmt --check`, `sh scripts/engine-test-targets.sh`, `(cd gateway && go test ./...)`) — all exit 0.
- `requirements.ready-ids` for RAG-03 — 0/1 ready (blocked by sibling plan(s) still pending in this phase); not marked complete, correctly deferred.
