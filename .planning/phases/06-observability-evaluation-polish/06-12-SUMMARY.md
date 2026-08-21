---
phase: 06-observability-evaluation-polish
plan: 12
subsystem: testing
tags: [grpc, http, error-taxonomy, table-driven-tests, api-contract, rag-03]

requires:
  - phase: 06-observability-evaluation-polish (plan 06-07)
    provides: typed Notice constructor and NoticeCode enum (NO_EVIDENCE used by the non-rejection rows)
  - phase: 06-observability-evaluation-polish (plan 06-11)
    provides: the last engine-test-targets.sh baseline this plan reconciles against (337/17/372)
provides:
  - "engine/src/tests/bad_input_matrix.rs — the D-15 bad-input matrix as a //! header table plus one table-driven gRPC test over the real query_rag entry point"
  - "gateway/main_test.go::TestBadInputMatrixHTTP — the same matrix's HTTP derivation, stub-driven per row"
  - "Phase-final reconciliation of both gate scripts' expected totals against the 06-03..06-12 delta chain"
affects: [06.4-docs-and-limitations, rag-query-http-contract]

actuals:
  tokens: 33000
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Table-driven test shape introduced into the Rust test tree (no prior analog): a Row struct with an Outcome enum (Reject{code,error_kind} | Succeed), one #[tokio::test] iterating a Vec<Row> against the real service.query_rag entry point"

key-files:
  created:
    - engine/src/tests/bad_input_matrix.rs
  modified:
    - engine/src/tests.rs
    - gateway/main_test.go
    - scripts/engine-test-targets.sh
    - scripts/gateway-test-targets.sh

key-decisions:
  - "Dense/lexical retrieval non-invocation on a rejecting row is proven structurally (by citing the exact unreachable code path in service.rs), not via injected FakeDenseRetrievalPort/FakeBm25RetrievalPort call counters — LancetServiceImpl's nodes/bm25_index/database fields are concrete production types with no seam to inject fakes at the gRPC entry point without a production-code change this test-only task does not have scope for. Constructing unused fakes just to read .calls()==0 would be tautological (rust-guidelines.md M-TAUTOLOGICAL-TESTS)."
  - "The generator's non-invocation IS proven by a real, wired counter (FakeGenerator::calls()) — and it holds for all twelve rows, not just the ten rejecting ones: WorkflowRunner::run_workflow skips both AssemblePrompt and GenerateAnswer whenever evidence is genuinely empty and allow_model_only is false, which is exactly what the two non-rejection rows construct. This was discovered empirically (an initial assumption that 06-11's citation-repair total-drop reconciliation would call the generator was wrong; the runner short-circuits before either node)."
  - "The two non-rejection rows are backed by one real, ingested document (not an empty database) so 'matches nothing' is a genuine claim about a populated corpus, not a tautology over an empty one — per advisor review during planning."
  - "max_content_types is set to 2 (below the 3 system-wide valid content-type strings) for the whole test's shared EffectiveRagSettings, because the default bound of 16 can never be exceeded by unique valid content-type values — only 3 exist. This is the only way to exercise the content-type filter-limit row without an unreachable duplicate."
  - "RAG-03 was NOT marked complete in REQUIREMENTS.md despite requirements.ready-ids reporting it ready (all Phase-06 sibling plans declaring it now have summaries). REQUIREMENTS.md's own traceability table documents a cross-phase split (06-CONTEXT.md D-77/D-78): DEBT-RAG-04 (index rebuild-and-swap) is deferred to Phase 06.1, which has not executed. The ready-ids check only looks at sibling plans within this phase directory, not the cross-phase split recorded in prose — marking the checkbox now would misrepresent DEBT-RAG-04 as done. See Deviations."

patterns-established:
  - "Row { label, request, outcome: Outcome::{Reject{code,error_kind}|Succeed} } table shape for future bad-input-style matrices in engine/src/tests/"

requirements-completed: []

coverage:
  - id: D1
    description: "The bad-input matrix is an enumerated, table-driven data structure — one gRPC table asserting the InvalidArgument status paired with the stable error-kind string per rejecting row, and one HTTP table asserting status 400 paired with the error-kind response header per row."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/bad_input_matrix.rs#bad_input_matrix_rejects_and_dispositions_are_stable"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestBadInputMatrixHTTP"
        status: pass
    human_judgment: false
  - id: D2
    description: "Every rejecting row is proven to reach neither retrieval nor the provider before any work happens."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/bad_input_matrix.rs#bad_input_matrix_rejects_and_dispositions_are_stable (FakeGenerator::calls() == 0 assertion)"
        status: pass
    human_judgment: true
    rationale: "The generator's zero-call assertion is a real, wired proof. Dense/lexical retrieval non-invocation on a rejecting row is a structural property proven by reading the admission path (cited in the module's //! header and in Deviations below), not by an injected mock call counter — LancetServiceImpl has no seam to inject FakeDenseRetrievalPort/FakeBm25RetrievalPort at the gRPC entry point without a production-code change out of this task's scope. A human should confirm this substitution is an acceptable proof of the property."
  - id: D3
    description: "The unmatched and contradictory filter rows are recorded as successes carrying the zero-evidence notice, not as rejections, and are backed by a real ingested document so the non-match is a genuine corpus claim."
    requirement: "RAG-03"
    verification:
      - kind: unit
        ref: "engine/src/tests/bad_input_matrix.rs#bad_input_matrix_rejects_and_dispositions_are_stable (unmatched_filter, contradictory_filter rows)"
        status: pass
      - kind: unit
        ref: "gateway/main_test.go#TestBadInputMatrixHTTP (unmatched_filter, contradictory_filter subtests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "No new validation module, no duplicated rule on the Go side, and no production source file changed by this plan."
    requirement: "RAG-03"
    verification:
      - kind: other
        ref: "git diff --stat 0d3205fe..HEAD (touches only test files and the two gate scripts)"
        status: pass
    human_judgment: false

duration: ~105min
completed: 2026-08-21
status: complete
---

# Phase 6 Plan 12: D-15 Bad-Input Matrix Summary

**Enumerated the RAG bad-input surface as a committed table-driven test artifact on both the gRPC and HTTP surfaces — nine rejection classes over ten rows plus two recorded non-rejection dispositions, reusing the existing nine-variant retrieval error taxonomy with zero new validation code.**

## Performance

- **Duration:** ~105 min (estimated; no explicit start-time gate ran in this worktree-executor mode)
- **Started:** ~2026-08-21T09:15:00Z (approx.)
- **Completed:** 2026-08-21T11:01:00Z
- **Tasks:** 2
- **Files modified:** 4 modified, 1 created

## Accomplishments

- **`engine/src/tests/bad_input_matrix.rs`** (new): a `//!` module-header table enumerating every input class (empty/whitespace query, oversized query, malformed/wrong-version session id, malformed document id, unsupported content type, empty filter value, both filter-count-limit bounds, the unmatched-filter and contradictory-filter non-rejections, and the negative-filter-bound mapping note), plus one table-driven `#[tokio::test]` that drives the real `LancetServiceImpl::query_rag` entry point per row. Expectations are literal `tonic::Code` values and literal error-kind strings — never re-derived from `RetrievalErrorKind` — per `rust-guidelines.md` M-TAUTOLOGICAL-TESTS.
- **`gateway/main_test.go::TestBadInputMatrixHTTP`** (new): the same matrix's HTTP derivation. Every rejecting row is driven through a stubbed engine gRPC status (the gateway does no field validation of its own) and asserts both HTTP 400 and the `X-Lancet-Error-Kind` header; every row also asserts the stub was actually reached, proving the body was forwarded rather than rejected locally. A dedicated row proves a non-`InvalidArgument` engine status derives to 502, not 400. The three pre-existing malformed-body rows are unchanged.
- **Both non-rejection dispositions proven, not asserted by assumption.** The unmatched-filter and contradictory-filter rows are backed by one real, ingested document on both surfaces, so "matches nothing" is a genuine claim about a populated corpus.
- **Test-count gates reconciled.** `scripts/engine-test-targets.sh` (library 337 → 338, TOTAL 372 → 373) and `scripts/gateway-test-targets.sh` (`gateway` package 64 → 65, TOTAL 79 → 80), each updated in the same commit as the tests that moved them.
- **Zero production source files touched.** `git diff --stat` against the plan's base commit touches only the two new/extended test files and the two gate scripts' expected totals.

## Task Commits

Each task was committed atomically:

1. **Task 1: Enumerate the matrix and drive it as a table-driven gRPC test** — `83c37f9` (test)
2. **Task 2: Drive the same matrix over the HTTP surface** — `c45b4fc` (test)

_Note: this plan was not executed under TDD gate discipline (`tdd_mode: false` in config.json); each task's test and its target-count reconciliation landed together in one commit, verified green before committing._

## Files Created/Modified

- `engine/src/tests/bad_input_matrix.rs` (new) — the matrix header table and its table-driven gRPC test; 1 test function.
- `engine/src/tests.rs` — declares `pub mod bad_input_matrix;`.
- `gateway/main_test.go` — adds `TestBadInputMatrixHTTP`; 1 new top-level test function (`go test -list` counts functions, not subtests).
- `scripts/engine-test-targets.sh` — library target 337 → 338, TOTAL 372 → 373.
- `scripts/gateway-test-targets.sh` — `gateway` package 64 → 65, TOTAL 79 → 80.

## Decisions Made

See `key-decisions` in the frontmatter for full detail. In brief:
- Dense/lexical retrieval non-invocation on a rejecting row is proven structurally (by citation of the unreachable code path), not by an injected mock call counter, to avoid a tautological test.
- The generator's zero-call assertion is real and holds across **all twelve rows** (not just the ten rejecting ones) — an empirical discovery that corrected an initial (wrong) assumption that citation-repair reconciliation would still invoke the generator on zero evidence; `WorkflowRunner` actually skips generation entirely in that case.
- `max_content_types` is deliberately reduced to 2 for the whole test's settings so the content-type filter-limit row is reachable at all (only 3 valid content-type strings exist system-wide; the default bound of 16 can never be exceeded by unique valid values).
- RAG-03 was **not** marked complete despite `requirements.ready-ids` reporting it ready — see Deviations.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed without any Rule 1-3 auto-fixes to code. Two implementation-detail findings surfaced and were resolved by design decisions documented above and in the module's own `//!` header, both anticipated by the plan's own escape valve ("If a row cannot be expressed without changing production code, record it in the summary as a finding rather than changing behavior in a test-only task").

### Process Correction (not a Rule 1-4 deviation — a self-caught tooling gap)

**1. Reverted a `requirements.mark-complete RAG-03` write after discovering it was premature**
- **Found during:** Post-Task-2, SUMMARY preparation.
- **Issue:** `requirements.ready-ids` for this plan's `RAG-03` reported `1/1 requirement(s) ready to mark complete` (the standard gate: every sibling *plan* in this phase directory declaring `RAG-03` now has a `*-SUMMARY.md`). Running `requirements.mark-complete RAG-03` accordingly flipped the checkbox in `.planning/REQUIREMENTS.md`. On review, `REQUIREMENTS.md`'s own traceability table states the requirement is split **across phases**, not just across plans: "DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-05 and DEBT-RAG-06 clauses → Phase 06; DEBT-RAG-04 (index rebuild-and-swap) → Phase 06.1" (06-CONTEXT.md D-77/D-78). Phase 06.1 has not executed (`STATE.md` `current_phase: 6`). The `ready-ids` check only inspects sibling plans within *this* phase directory — it has no visibility into a cross-phase requirement split recorded only in prose, so it reported "ready" for a requirement that is genuinely only 4/5 done.
- **Fix:** `git checkout -- .planning/REQUIREMENTS.md` before the change was staged or committed. The checkbox remains `[ ]`. `RAG-03` should be marked complete by whichever plan lands DEBT-RAG-04 in Phase 06.1.
- **Files affected:** `.planning/REQUIREMENTS.md` (change made and reverted; final diff is empty).
- **Verification:** `git diff .planning/REQUIREMENTS.md` is empty; `git status` shows no pending change to this file.
- **Impact:** None on shipped code. Flagging this as a process note: `requirements.ready-ids`'s sibling-plan check is a same-phase-only signal and should not be trusted blindly against a traceability table that documents a cross-phase split.

---

**Total deviations:** 0 code auto-fixes; 1 self-caught and reverted process error (premature requirement checkbox).
**Impact on plan:** None — all code changes match the plan as written; the reverted file has an empty diff.

## Known Stubs

None.

## Known Gaps

- **Dense/lexical retrieval non-invocation on the two non-rejection rows is real, not skipped.** Unlike generation (skipped by `WorkflowRunner` for genuine zero evidence), `RetrieveHybridNode` always runs — the corpus really is queried and really does come back empty for `unmatched_filter` and `contradictory_filter`. This is intentional and matches the plan's requirement that dense/lexical retrieval actually execute for the two non-rejection dispositions; only the ten *rejecting* rows structurally never reach retrieval at all.
- **The negative-filter-bound disposition has no runtime test row** (by design — the request surface cannot express a negative value; see the module's `//!` header for the mapping to the existing `invalid_settings` configuration-error-kind category). This is documentation-only, matching the plan's own instruction.

## Issues Encountered

None beyond the reverted-checkbox process note documented above under Deviations.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 6's four RAG-03 hardening clauses assigned to this phase (graph-unavailable degrade, per-path retrieval degrade, model-only opt-in, citation repair/basis reconciliation, and this plan's bad-input matrix) are all complete with green gates: `cargo test --manifest-path engine/Cargo.toml --locked`, `cargo clippy -- -D warnings`, `cargo fmt --check`, `sh scripts/engine-test-targets.sh`, `(cd gateway && go build ./... && go vet ./... && go test ./...)`, and `sh scripts/gateway-test-targets.sh` all exit 0 at HEAD.
- `RAG-03`'s checkbox in `.planning/REQUIREMENTS.md` remains `[ ]` on purpose — DEBT-RAG-04 (index rebuild-and-swap) is Phase 06.1's work, not this phase's. Phase 06.1 should mark `RAG-03` complete when it lands that clause.
- Phase 6.4 (docs and limitations) can lift this plan's two matrix header tables (`engine/src/tests/bad_input_matrix.rs`'s `//!` doc and `gateway/main_test.go::TestBadInputMatrixHTTP`'s comment) verbatim as API-contract documentation, per this plan's `<output>` instruction.
- **Phase-final gate-script reconciliation (from `06-03-SUMMARY.md`'s post-restructure baseline through this plan):**

  | Plan | Engine lib delta | Engine total (after) | Gateway `gateway` pkg delta | Gateway TOTAL (after) |
  |---|---|---|---|---|
  | 06-03 baseline | — | 311 / N/A | — | 67 (relocation baseline, pre-06-07) |
  | 06-06 | (D-83 fake-port failure modes; no lib count recorded in this plan's traceable summary text — carried forward) | 311 (unchanged per 06-11's own reconciliation table) | — | — |
  | 06-07 | (typed Notice/NoticeCode plumbing; carried in the 311 baseline 06-11 cites) | 311 | +8 (`gateway/internal/sse` package-local, not the `gateway` package itself) | 75 |
  | 06-08 | included in 06-11's reconciled delta | — | — | — |
  | 06-09 | included in 06-11's reconciled delta | — | — | — |
  | 06-10 | included in 06-11's reconciled delta | — | — | — |
  | 06-11 | +26 (11 citations.rs + 7 basis/precedence + 8 repair integration) | 337 / TOTAL 372 | 0 (no gateway changes) | 75 (unchanged) |
  | **06-12 (this plan)** | **+1** (`bad_input_matrix_rejects_and_dispositions_are_stable`) | **338 / TOTAL 373** | **+1** (`TestBadInputMatrixHTTP`) | **80** |

  **Residue note:** 06-11's summary explicitly could not itemize the 06-06/06-08/06-09/06-10 per-plan deltas against the 311 figure it inherited from 06-03 — its own table states the 311→337 library delta as a single +26 spanning only 06-11's three tasks, treating 311 as an already-reconciled baseline rather than re-deriving it from 06-03's original number. This plan's own scope is `06-07` and `06-11` as declared `depends_on`; it does not have first-hand `git log` access to the intervening 06-06/06-08/06-09/06-10 commits' individual deltas beyond what their own summaries recorded, and re-deriving them from raw commits was outside this task's `<files>` scope. **This is the residue this plan's `<output>` instruction anticipates and asks to be reported rather than silently reconciled**: the chain from 311 (06-03) to 337 (pre-06-12) is attested plan-by-plan in each intervening `*-SUMMARY.md` but this plan does not re-verify each one against raw `git log` — only the final two hops (06-11 → 06-12) are independently reconciled here from measured `cargo test --list` / `go test -list` output. The two measured endpoints (337/372 before this plan, 338/373 after; 65/80 gateway after) are directly verified by this plan's own gate-script runs above.

---
*Phase: 06-observability-evaluation-polish*
*Plan: 12*
*Completed: 2026-08-21*
