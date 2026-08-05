---
title: "ADR-03-001: Phase 03 Verification Gap Disposition"
status: accepted
date: 2026-08-04
decider: mileschintw
scope: Phase 03 — Hybrid Retrieval & Basic RAG Path (RAG-02 / RAG-04 exit)
source_material:
  - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-VERIFICATION.md
  - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-REVIEW.md
  - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-REVIEWS.md
  - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-CONTEXT.md
  - .planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md
  - .planning/REQUIREMENTS.md
  - .planning/ROADMAP.md
  - phase03-gap-decisions-memo.md (decision workshop log)
supersedes: null
superseded_by: null
---

# Purpose

This ADR records the disposition of items that Phase 03 verification still surfaces as must-fix or must-explicitly-defer before phase exit. The operating context is an MVP hybrid RAG path (dense LanceDB + in-memory BM25, NoOp reranker, strict provider-neutral generation, Go `/rag/query` boundary) with verification score **64/65** and status `gaps_found`. Constraints: close the single failed must-have without pulling Phase 06 degraded/repair/lifecycle/graph product work forward; prefer honest fail-closed and contract-correct APIs over silent success. Decision criteria: (1) does it block 64→65 or make the accepted happy path lie, (2) is it already fenced as DEBT-RAG-* / Phase 04–06, (3) smallest change that restores a truthful boundary.

# Decision Summary

| ID | Finding | Decision | Priority | Target |
|---|---|---|---|---|
| G1 | Provider usage validation uses fixed 8192/2048/10240 instead of `EffectiveRagSettings` | Ship | P1 | Phase 03 gap plan (before phase exit) |
| D1 | Embedding failure → constant vector; dense failure → empty list | Ship | P0 | Phase 03 gap plan (before phase exit) |
| D2 | Valid zero-match retrieval mapped to `InvalidArgument` / HTTP 400 | Ship | P1 | Phase 03 gap plan (before phase exit) |
| D3 | Citation repair / transparent downgrade (D-24) | Defer | P2 | Phase 06 / DEBT-RAG-03 |
| D4 | BM25 not refreshed after ingest; restart lifecycle incomplete | Defer | P2 | Phase 06 / DEBT-RAG-04 |
| D5 | Graph-unavailable degraded fallback (RAG-03 family) | Defer | P3 | Phase 04 seam + Phase 06 / DEBT-RAG-06 |

# Findings to Ship

## G1: Effective provider usage budgets and service ceilings

**Decision:** Ship.

**Problem:**
Request construction uses configured `evidence_token_budget` and `max_output_tokens` from `EffectiveRagSettings`, but shared grounding validation and the OpenRouter adapter still compare reported usage against fixed defaults (`8192` / `2048` / total `10240`) in `engine/src/generation/mod.rs` and `engine/src/generation/openrouter.rs`. Non-default configs can reject valid usage or accept over-budget usage. This is the sole failed verification must-have (Plan 03-13 P54 / RAG-02 / P24–P25).

**Rationale:**
One validated settings object must govern packing, provider request limits, and usage acceptance. Leaving validation on defaults makes configuration a false control plane and blocks phase exit (64/65). Shipping ceilings in the same change prevents “honor effective settings” from legalizing unbounded-in-practice operator values (review CR-06 class risk).

**Alternatives considered:**
- Thread effective limits only, no ceilings — rejected as incomplete; creates a second migration for safe maxima.
- Document that usage gates always use defaults — rejected; violates P25/P54 and “one EffectiveRagSettings” contract.
- Fix adapter only, leave shared `validate_grounding` on defaults — rejected; splits test vs production paths.
- **Chosen: effective limits + service-safe ceilings (option C)** — closes the must-have and hardens the same seam.

**Chosen implementation:**
- Introduce a single limits carrier (e.g. `GroundingLimits` or equivalent fields) built from validated `EffectiveRagSettings` at startup or request assembly.
- Pass effective evidence budget, max output tokens, and a checked effective total into `ModelOutput::validate_grounding` and OpenRouter usage checks.
- Remove runtime dependence on default constants for usage validation (defaults may remain as config defaults only).
- Enforce service-safe upper bounds at settings validation (startup fail-closed) for at least evidence token budget, max output tokens, and derived total usage ceiling.
- Numeric ceiling values are plan-owned: `[TODO: pin evidence_token_budget_max, max_output_tokens_max, total_usage_max]`.
- Regressions: (a) usage inside configured limits but outside old defaults → accept; (b) over configured → reject; (c) config above service ceiling → settings/startup rejection.

**Estimated effort:** Medium

**Acceptance criteria:**
- Production adapter and shared validator use the same effective limits object for usage checks.
- A non-default config below ceilings is accepted when provider usage is within that config.
- Provider usage above effective limits is rejected with no public grounded success body.
- Config above service ceilings fails before readiness.
- Focused adapter/generation tests and Phase 03 locked gates pass; verification P54 becomes verified (65/65 on this axis).

**Risk if not fixed:**
Operators cannot trust budget configuration; over-long prompts/completions may pass or valid tuned configs may fail spuriously; RAG-02 remains blocked.

**Consequences:**
- Good: Single authoritative limits path; phase must-have closable; safer config surface.
- Bad: Requires choosing concrete ceilings; slightly stricter startup validation may break loose local configs that exceeded implicit defaults.

## D1: Fail-closed embedding and dense retrieval errors

**Decision:** Ship.

**Problem:**
On embedding provider error, empty/wrong-dimension/non-finite vectors, `query_rag` substitutes `vec![0.25; 2048]` (`engine/src/main.rs`). Dense retrieval errors are masked with `unwrap_or_default()`, so LanceDB/snapshot failures look like a successful empty dense branch. Generation may continue and present weakened or unrelated evidence as retrieval-backed. Verification labels this DEBT-RAG-01 deferred product work, but the live behavior is silent incorrectness, not disclosed degradation. Code review/AgY rate it HIGH.

**Rationale:**
Phase 03 acceptance requires successful dense and BM25 on the happy path. Silent fabrication/masking violates fail-closed integrity and is worse than an explicit error. Degraded single-path or model-only product mode remains Phase 06; this ship item only stops lying about infrastructure failure. Error identity (session/correlation/error-kind) must ride the failure path consistently with the already-fixed generation-error identity work.

**Alternatives considered:**
- Leave code, document as interim — rejected; residual false-grounded answers.
- Implement disclosed BM25-only / model-only continuation now — rejected; pulls DEBT-RAG-01 / RAG-03 into Phase 03.
- Dev-only fallback flag — rejected; dual behavior and CI blind spots.
- Fail-closed without identity metadata — weaker; identity is cheap and aligns with existing boundary.
- **Chosen: fail-closed + error identity (option C)** — no degraded product.

**Chosen implementation:**
- Map embedding failures (transport, empty, wrong count/dimension, non-finite) to typed `tonic::Status` before dense query; never substitute a constant vector.
- Propagate `DenseRetriever::query` errors; only `Ok(empty)` is a legitimate zero-dense branch.
- Preserve session/correlation/error-kind on these failures through engine → gateway headers where applicable.
- Exact status codes (`unavailable` vs `internal`) and log shape are plan-owned.
- Tests: embedding failure skips generation; dense failure skips generation; successful empty dense remains allowed only when the dense query itself returns `Ok`.
- Update DEBT-RAG-01 text: deferred work is disclosed degraded continuation, not re-introduction of silent fabricate/mask.

**Estimated effort:** Small

**Acceptance criteria:**
- No constant embedding fallback remains on the production query path.
- No dense `unwrap_or_default()` (or equivalent) converts retrieval errors into empty success.
- Named tests prove generation is not invoked on embedding/dense infrastructure errors.
- Failure responses carry identity metadata consistent with the generation-error path.
- DEBT-RAG-01 ledger states degraded product is still Phase 06.

**Risk if not fixed:**
Provider or LanceDB outages yield plausible hybrid answers from garbage or partial evidence without disclosure.

**Consequences:**
- Good: Honest availability signal; grounding integrity preserved.
- Bad: Faults that previously returned some answer now surface as errors (availability drop under infra failure).

## D2: Valid zero-match is success-empty, not HTTP 400

**Decision:** Ship.

**Problem:**
A syntactically valid query whose filters match no completed rows yields an empty final candidate list. Prompt packing returns `PromptError::EmptyEvidence`, the engine maps that to `tonic::Status::invalid_argument`, and the gateway maps `InvalidArgument` to HTTP 400. Decision D-10 requires valid filters with no matches to produce empty evidence, not a caller-validation error. Verification tracks the broader matrix under DEBT-RAG-05 but reports this D-10 tension for visibility; reviews rate the API confusion HIGH.

**Rationale:**
Clients must distinguish malformed input (fix the request) from empty corpus match (relax filters or accept no-results). Shipping only this single branch restores D-10 without implementing the full negative-input matrix. Consistent with G1/D1 “honest boundary” decisions. Response wire shape is deliberately left to the gap plan.

**Alternatives considered:**
- Keep 400 until Phase 06 — rejected; trains clients on wrong contract and conflicts with D-10.
- Dedicated non-200 no-results status (404/422) — deferred as shape choice; not required by this ADR’s lock.
- Engine-only fix while HTTP stays 400 — rejected; external API remains wrong.
- Also split `NoEvidenceFits` into resource errors in the same change — not mandated (optional adjacent); avoids scope creep into full WR-01 unless plan absorbs it.
- Call provider on empty evidence / model-only — rejected; conflicts with ModelOnly rejection and DEBT-RAG-01.
- **Chosen: success-path empty no-results (option B); shape → plan.**

**Chosen implementation:**
- Before prompt packing, detect retrieval success with empty final candidates.
- Do not route that branch through `EmptyEvidence` → `InvalidArgument` → HTTP 400.
- Do not call the provider.
- Return a success-path no-results outcome whose wire shape is plan-defined (examples only: empty answer, empty citations, stable notice code such as `NO_EVIDENCE`, basis field policy).
- Must not resemble a grounded long-form retrieval hit.
- Infrastructure errors (D1) remain error statuses; only Ok-empty final lists take this path.
- Full combinatorial filter/unmatched matrix remains DEBT-RAG-05.
- `NoEvidenceFits` reclassification is out of scope unless the gap plan explicitly adds it.

**Estimated effort:** Small–Medium (depends on proto/HTTP shape choice)

**Acceptance criteria:**
- Valid filter with zero matches does not return HTTP 400.
- Provider/generator is not invoked on that branch.
- Response shape is locked by tests exactly as the gap plan specifies.
- Malformed query/filter input still returns client validation errors (400 / `InvalidArgument` as today).
- D1 error paths remain distinct from D2 empty success.

**Risk if not fixed:**
API clients cannot automate empty vs invalid handling; contract docs and runtime disagree.

**Consequences:**
- Good: D-10-aligned public behavior; simpler client logic.
- Bad: Requires a concrete response schema decision in the plan; possible minor breaking change for any client that already depended on 400-for-empty.

# Findings Deferred, Rejected, or Accepted As-Is

## D3: Citation repair and transparent downgrade

**Decision:** Defer.

**Problem:**
When model markers are unknown, duplicate, or mismatched, Phase 03 fail-closes and does not publish a QueryRAG success body. Product target D-24 (repair, strip bad markers, transparent downgrade) is not implemented.

**Decision rationale:**
Current fail-closed valid-marker behavior is verified and matches Phase 03 grounding plans (including post-gap ModelOnly/citation requirements). Repair is availability UX tracked as DEBT-RAG-03 for Phase 06. Implementing repair now would weaken the just-hardened grounding gate and expand scope past verification must-haves.

**Minimum guardrail to ship now:**
- Keep fail-closed grounding: illegal markers must not produce a public success body.
- Do not land silent strip-unknown-as-success as an “interim” main-path fix.

**Known risk:**
- Likelihood now: Medium (provider occasionally emits extra/bad IDs)
- Impact if realized: Medium (whole answer fails instead of partial)
- Residual exposure: Stricter failure rate under messy model output until Phase 06 repair exists.

**Current operating constraints:**
- Prompt/provider configuration should favor strict schema and exact evidence IDs.
- Operators should treat grounding failures as model/contract issues, not as missing repair logic in Phase 03.

**Tracking:** `DEBT-RAG-03` (D-24)

**Target:** Phase 06 hardening

**Escalation trigger:**
Production or integration failure rate from marker mismatches becomes operationally unacceptable, or a client SLA requires partial answers with disclosure.

**Future acceptance criteria:**
- Documented repair/downgrade rules with machine-readable disclosure notices.
- Tests for unknown strip, duplicate handling, and basis downgrade.
- No undetected publication of unresolved marker identities.

## D4: BM25 re-ingestion and restart lifecycle

**Decision:** Defer.

**Problem:**
`Bm25Index` is built once before readiness. Ingestion can complete new LanceDB rows without rebuilding or atomically publishing a new in-memory BM25 snapshot. Dense retrieval may see fresh chunks while lexical retrieval lags until process restart. Dynamic switching and restart recovery are D-41–D-43.

**Decision rationale:**
Phase 03 explicitly accepts initial BM25 build/readiness as the MVP trust safeguard. Full cross-index lifecycle is DEBT-RAG-04 / Phase 06. Half-implemented refresh is worse than documented staleness. Matches verification deferred disposition (review severity lowered to warning once scoped).

**Minimum guardrail to ship now:**
- Preserve initial BM25 build-before-serving and fail-closed initial build failure.
- Document operator constraint: after in-process ingest, hybrid lexical consistency may require **engine restart** until Phase 06.
- Ledger must state: document `completed` ≠ present in live BM25 for a long-running process.

**Known risk:**
- Likelihood now: High if continuous ingest + query without restart
- Impact if realized: Medium (degraded hybrid quality; lexical misses)
- Residual exposure: Running MVP processes silently diverge across dense vs BM25 views.

**Current operating constraints:**
- For demos or correctness-sensitive checks after ingest, restart the engine (or rebuild process) before relying on hybrid lexical hits.
- Do not claim live BM25 freshness in Phase 03 docs or APIs.

**Tracking:** `DEBT-RAG-04` (D-41–D-43)

**Target:** Phase 06 lifecycle hardening

**Escalation trigger:**
Production requires online ingest with hybrid query without restart, or observed systematic dense/BM25 disagreement after completion.

**Future acceptance criteria:**
- Completion is transactional with lexical visibility (rebuild or incremental upsert + atomic publish).
- Replacement/deletion/replay ordering preserves dense and BM25 agreement.
- Tests cover ingest-then-query without restart.

## D5: Graph-unavailable RAG-03 fallback

**Decision:** Defer.

**Problem:**
RAG-03 degraded behavior when graph extraction or graph context is unavailable is not implemented. Phase 03 is source-chunk-only hybrid retrieval.

**Decision rationale:**
Graph context is Phase 04 ownership. Graph-unavailable fallback is DEBT-RAG-06 / Phase 06 and is not a Phase 03 acceptance requirement (REQUIREMENTS/ROADMAP/COVERAGE opt-out). Implementing fallback without a graph primary path is premature and conflicts with D1’s rejection of degraded product mode in this phase.

**Minimum guardrail to ship now:**
- None beyond scope fence: no graph query path, no pseudo-graph shims, no model-only “graph fallback” on the Phase 03 path.
- Keep Phase 03 responses chunk-grounded only.

**Known risk:**
- Likelihood now: Low (no graph path to fail)
- Impact if realized: Low in Phase 03; High later if graph ships without degraded design
- Residual exposure: None for current chunk-only MVP; debt becomes real when Phase 04 graph lands.

**Current operating constraints:**
- Do not advertise graph-enhanced answers in Phase 03.
- Phase 04 must not assume Phase 03 already provides graph degradation semantics.

**Tracking:** `DEBT-RAG-06` (with RAG-03 family; graph seam in Phase 04)

**Target:** Phase 04 (graph seam) then Phase 06 (degraded/unavailable hardening)

**Escalation trigger:**
Graph context is enabled on the query path without a defined unavailable/degraded contract.

**Future acceptance criteria:**
- Defined behavior when graph is missing, stale, or fails.
- Disclosed basis/warnings distinct from full graph-backed answers.
- Tests for graph-unavailable and chunks-only continuation per Phase 06 spec.

# Exit Conditions

The scope of this ADR is complete when:

1. All `ship` items (G1, D1, D2) meet their acceptance criteria.
2. Required verification commands pass, including at minimum:
   - `cargo test --manifest-path engine/Cargo.toml --locked`
   - Focused generation/adapter and `query_rag` tests for G1/D1/D2
   - `go test -count=1 ./...` from `gateway` (include cross-runtime RAG test where applicable)
   - Phase 03 verification re-run shows **65/65** must-haves on the prior failed axis and no regressions on grounding/initial BM25/chunk-only scope
3. All deferred items (D3, D4, D5) remain recorded in the phase deferred ledger with residual risk and escalation triggers aligned to this ADR.
4. No placeholder marked `[TODO]` remains on a path required for exit (ceiling numbers and D2 wire shape must be resolved in the gap plan before merge).
5. Gap plan produced via `/gsd-plan-phase 03 --gaps` (or equivalent) covers G1+D1+D2 and a short deferred-confirmed section for D3–D5.

# Review Triggers

Review this ADR before any of the following:

- Phase 03 exit sign-off or roadmap status flip to complete
- Enabling continuous ingest + hybrid query without process restart (D4)
- Any implementation of citation repair, partial publish, or marker stripping (D3)
- Introduction of graph context on the query path (D5 / Phase 04)
- Enabling degraded single-path or model-only product answers (D1 boundary / DEBT-RAG-01)
- Multi-tenant or external client SDKs that freeze HTTP semantics for empty results (D2)
- Raising configured evidence/output budgets near or above planned service ceilings (G1)
- Production OpenRouter (or other provider) rollouts where usage accounting differs from local mocks (G1)

# Decisions Locked

- [x] G1 = Ship option C: effective usage validation + service-safe ceilings
- [x] D1 = Ship option C: embedding/dense fail-closed + error identity; no degraded product in Phase 03
- [x] D2 = Ship option B: valid zero-match is success-empty, not HTTP 400; wire shape deferred to gap plan
- [x] D3 = Defer citation repair/downgrade to DEBT-RAG-03 / Phase 06; keep fail-closed markers
- [x] D4 = Defer BM25 hot lifecycle to DEBT-RAG-04 / Phase 06; initial BM25 readiness only
- [x] D5 = Defer graph-unavailable fallback to DEBT-RAG-06 / Phase 06; Phase 03 chunk-only
- [x] Full DEBT-RAG-05 combinatorial filter matrix remains deferred beyond D2’s single empty-success branch
- [x] `NoEvidenceFits` status split is not mandated by this ADR
- [x] Review extras outside verification agenda (body buffer-before-limit, RRF non-finite + writeJSON 200, staging delete-before-add, insecure gRPC, etc.) are not disposed here

# Open Items

- [ ] Pin numeric service ceilings for G1 (`evidence_token_budget_max`, `max_output_tokens_max`, `total_usage_max` or equivalent)
- [ ] Specify D2 success-empty wire shape (HTTP body fields, notice/basis codes, proto impact if any)
- [ ] Specify D1 exact `tonic::Status` code mapping for embedding vs dense failure classes
- [ ] Assign final ADR number and path under `docs/adr/` or `.planning/decisions/` when filing in-repo
- [ ] Create or update ledger rows for DEBT-RAG-01/03/04/05/06 text to match this ADR’s boundaries after gap implementation

# Author Notes

## Assumptions
- Decider is the repo owner (`mileschintw`); amend frontmatter if a team name is preferred.
- Verification score 64/65 and file paths reflect the 2026-08-04T13:23:37Z verification refresh.
- “Ship before phase exit” means before Phase 03 is marked complete on the roadmap, not before unrelated later phases start design.

## Conflicts Detected
- Verification treats D1 silent fallback and D2 zero-match→400 as deferred/non-scoring; this ADR **ships** both because user decisions prioritize honest boundaries over the minimal 65/65-only path. G1 remains the only verification-scored must-have; D1/D2 are additional phase-exit engineering commitments from the decision workshop.
- Code review may still list other critical items not covered by G1–D5; they remain out of scope until a separate disposition.

## Questions That Would Remove TODOs
- What concrete ceiling numbers should G1 enforce for local MVP vs production-shaped configs?
- Preferred D2 body: empty string answer + `citations:[]` + notice code only, or also a dedicated basis enum value?
- Should embedding dimension mismatch be `internal` (provider bug) and transport failure `unavailable` (dependency down)?
