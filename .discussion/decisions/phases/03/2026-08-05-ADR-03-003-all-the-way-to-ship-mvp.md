---
title: "ADR-03-003: Phase 03 Force-Close Disposition of Verification Gaps"
status: accepted
date: 2026-08-05
decider: mileschintw (project owner)
scope: Phase 03 Hybrid Retrieval & Basic RAG Path (force-close) → Phase 04 entry
source_material:
  - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-VERIFICATION.md
  - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-REVIEW.md
  - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-REVIEWS.md
  - phase03-force-close-decision-memo.md (decision session 2026-08-05)
  - Prior Phase 02 force-close / DEBT-CR-04 precedent
supersedes: null
superseded_by: null
---

# Purpose

This ADR records the force-close decisions for Phase 03 after verification returned `gaps_found` (98/101 plan truths) while roadmap happy-path success criteria remained green. The operating context is a single-host, local-only MVP: loopback Go gateway to Rust engine, operator-controlled config, sequential document ingest for demos, and Phase 04 (graph) blocked until Phase 03 exits. Decision criteria were: (R1) happy-path primacy for hybrid RAG demo value; (R2) no silent drop of findings; (R3) prefer named debt over multi-day redesign; (R4) local-only trust assumptions; (R5) do not pull RAG-03 into this close. The only pre-exit code change authorized is mechanical `cargo fmt`. All other residual verification blockers and warnings are deferred with tracking IDs, constraints, and escalation triggers.

# Decision Summary

| ID           | Finding                                                                             | Decision                     | Priority | Target                                                      |
| ------------ | ----------------------------------------------------------------------------------- | ---------------------------- | -------- | ----------------------------------------------------------- |
| META         | Force-close Phase 03 under R1–R5; enter Phase 04                                    | Ship (process)               | P1       | Immediate close package                                     |
| FMT          | `cargo fmt --check` drift in engine                                                 | Ship                         | P3       | Before Phase 03 close commit                                |
| CR-01        | Provider body bound is post-`chunk` materialization                                 | Defer                        | P1       | Phase 06 / security or non-local provider                   |
| CR-02        | Staging `generation` RMW race; equal-gen fail-closed                                | Defer                        | P1       | Phase 06 / concurrent same-doc ingest                       |
| T2           | Delete-fail physical row retention unproven                                         | Defer                        | P3       | Phase 06 test hardening                                     |
| CR-03        | Committed DB password + `sslmode=disable`                                           | Defer                        | P2       | Phase 06 / non-local Postgres                               |
| CR-04        | Gateway→Engine gRPC always insecure                                                 | Defer                        | P2       | Phase 06 / non-loopback `engine_addr` (extend `DEBT-CR-04`) |
| CR-05        | Arbitrary provider endpoint receives bearer token                                   | Defer                        | P2       | Phase 06 / untrusted config source                          |
| WARN-DX      | Seeder non-idempotent; empty multipart ambiguity                                    | Defer                        | P3       | Phase 06 DX                                                 |
| WARN-API     | Mixed disclosure; capacity→400; D1 identity gaps                                    | Defer                        | P2       | Phase 06 API hardening                                      |
| WARN-SET     | Env ignore; dual budgets; chunk saturate                                            | Defer                        | P3       | Phase 06 settings                                           |
| WARN-VAL     | Staging nulls; non-finite embed/BM25                                                | Defer                        | P2       | Phase 06 validation                                         |
| MOD-GRAPH    | Dual lib/bin production module graph                                                | Defer                        | P3       | Phase 06 engine layout                                      |
| REJ-GEN      | Remove custom `generation` column as “fix”                                          | Reject                       | —        | Invalid approach                                            |
| REJ-REDESIGN | CAS/merge_insert staging redesign, mTLS, allowlist, warning behavior fixes in close | Reject (for this exit)       | —        | Not in force-close budget                                   |
| RAG-02       | Requirement checkbox wording                                                        | Accept-as-is (MVP qualified) | P1       | Close package                                               |
| RAG-04       | Reranker seam                                                                       | Accept-as-is (satisfied)     | —        | Already verified                                            |
| RAG-03       | Degraded/model-only/citation-repair family                                          | Defer (pre-existing)         | P2       | Phase 06 (unchanged)                                        |

# Findings to Ship

## META: Phase 03 force-close and Phase 04 entry

**Decision:** Ship.

**Problem:**
Verification status is `gaps_found` with five blocker-class findings and clustered warnings. Continuing `/gsd:plan-phase 03 --gaps` indefinitely blocks Phase 04 while the observable hybrid RAG happy path (dense+BM25, fusion, grounded answer, cross-runtime test, BM25 readiness, NoOp reranker) already runs.

**Rationale:**
Phase goal value for the product roadmap is the demoable RAG path, not 101/101 plan-safety closure. Phase 02 already established force-close-with-debt. Without an explicit exit ADR, planning tools and humans disagree on whether Phase 03 is complete.

**Alternatives considered:**
- Keep Phase 03 open until all blockers ship - rejected: delays graph work without proportional MVP value.
- Mark verification `passed` without debt - rejected: false confidence; violates R2.
- Close with no ledger updates - rejected: silent drop.
- Chosen: force-close with named debt, qualified RAG-02, fmt-only code, Phase 04 next.

**Chosen implementation:**
- Update `STATE.md`: Phase 03 completed (force-closed; debt recorded); next = Phase 04.
- Update `ROADMAP.md`: Phase 03 complete under MVP force-close; pointer to debt ledger and Phase 06.
- Update Phase 03 `deferred-items.md` (and any canonical debt index) with all IDs in this ADR.
- Extend existing `DEBT-CR-04` with Phase 03 gateway evidence; do not mint `DEBT-P3-GRPC-INSECURE`.
- REQUIREMENTS: RAG-04 satisfied; RAG-02 = SATISFIED (MVP, see DEBT-P3-*); RAG-03 unchanged deferred.
- Do not flip verification report historical status to `passed`; close is process/roadmap, not re-verification PASS.
- Optional: short `03-FORCE-CLOSE.md` linking this ADR; not required for exit if STATE/ROADMAP/deferred-items are complete.

**Estimated effort:** Small

**Acceptance criteria:**
- STATE and ROADMAP show Phase 03 force-closed and Phase 04 as next.
- Every deferred ID in the Decision Summary appears in the debt ledger with owner, trigger, and constraint.
- REQUIREMENTS wording matches RAG-02 MVP qualification and RAG-04 satisfied.
- No functional production logic change is required for META beyond ledger/docs (fmt is separate ship item).

**Risk if not fixed:**
Phase 03 remains limbo; Phase 04 cannot start cleanly; future agents re-open gap plans forever.

**Consequences:**
- Good: Unblocks Phase 04; preserves audit trail; matches MVP economics.
- Bad: Residual safety/security debt is real; operators must honor local-only and single-writer constraints.

## FMT: Engine formatting gate

**Decision:** Ship.

**Problem:**
`cargo fmt --manifest-path engine/Cargo.toml --all -- --check` fails on current engine sources (including test modules). This is a quality-gate red without behavioral meaning.

**Rationale:**
The only code change consistent with all deferred security/integrity decisions is mechanical formatting. Shipping fmt removes a noisy gate and avoids creating `DEBT-P3-FMT`.

**Alternatives considered:**
- Defer fmt as `DEBT-P3-FMT` - rejected by explicit close decision L2.
- Mix fmt with functional fixes - rejected: expands close scope.
- Chosen: fmt-only.

**Chosen implementation:**
- Run `cargo fmt --manifest-path engine/Cargo.toml --all`.
- Confirm `cargo fmt ... -- --check` exits 0.
- Do not edit logic, configs, gateway, or staging protocol in the same change set except incidental fmt touch of those files’ whitespace/order.

**Estimated effort:** Small

**Acceptance criteria:**
- `cargo fmt --manifest-path engine/Cargo.toml --all -- --check` passes.
- Diff is formatting-only (no intentional semantic edits).
- Recommended (not blocking this ADR item alone): `cargo test --manifest-path engine/Cargo.toml --locked` still passes after fmt.

**Risk if not fixed:**
Chronic red fmt gate; review noise; temptation to bundle unrelated fixes later.

**Consequences:**
- Good: Clean format gate; no new fmt debt.
- Bad: Large whitespace churn possible in one commit.

# Findings Deferred, Rejected, or Accepted As-Is

## CR-01: Provider body bound post-chunk (Plan 03-20 T1)

**Decision:** Defer.

**Problem:**
`engine/src/client/mod.rs` `read_body_limited` uses `reqwest::Response::chunk` and checks the 256 KiB policy after a chunk is materialized. An oversize single frame can allocate before rejection. Plan 03-20 T1 required a pre-materialization stream bound. Chat, metadata, and embeddings share this helper.

**Decision rationale:**
Under local MVP with mock/local provider and normal OpenRouter payload sizes, practical exposure is low. Full stream-cap work is hardening, not required to demo hybrid RAG (R1/R3).

**Minimum guardrail to ship now:**
- None beyond existing Content-Length check and aggregate length reject.
- Operators must not point the engine at untrusted provider endpoints (see CR-05 constraint).

**Known risk:**
- Likelihood now: Low (trusted/local provider)
- Impact if realized: High (Engine memory pressure / DoS)
- Residual exposure: Malicious or buggy upstream can force large frame allocation before reject.

**Current operating constraints:**
- MVP trusts the configured provider transport path.
- Do not expose Engine provider egress to untrusted networks without revisiting this debt.

**Tracking:** `DEBT-P3-BODY-BOUND`

**Target:**
Phase 06 resource/security hardening, or earlier if escalation triggers.

**Escalation trigger:**
Non-loopback deployment, untrusted provider path, or formal security review of provider I/O.

**Future acceptance criteria:**
- Reader never retains a frame that exceeds remaining budget.
- Shared 262144-byte policy remains for chat, metadata, embeddings.
- Regression covers a single over-limit frame, not only multi-chunk aggregates.
- Plan 03-20 T1 can be re-verified pass.

## CR-02: Staging generation allocation race (Plan 03-23 T1)

**Decision:** Defer.

**Problem:**
`persist_raw_with_boundary` in `engine/src/main.rs` reads max `generation` then appends `max+1` without per-document lock, CAS, or uniqueness. Concurrent `IngestDocument` for the same `document_id` can create duplicate generation values. `select_latest_staged_rows` fail-closes on equal generations, which can stick a document until manual repair. This is an application protocol issue; Lance table MVCC does not enforce per-document generation uniqueness.

**Decision rationale:**
MVP/demo ingest is sequential single-writer per document. The race is real but outside the supported operating mode (R4 + explicit single-writer assumption). Redesign (CAS, merge_insert) exceeds force-close budget. Removing the `generation` column was considered and rejected (see REJ-GEN).

**Minimum guardrail to ship now:**
- None in code.
- Operational: do not concurrent-replace the same `document_id`; one in-flight ingest per document.

**Known risk:**
- Likelihood now: Low under sequential ingest; High if clients double-submit same UUID
- Impact if realized: High (document stuck in staging/replay/status)
- Residual exposure: Ambiguous equal-generation rows; fail-closed read prevents silent wrong winner but also blocks recovery automation.

**Current operating constraints:**
- Single writer per `document_id` at a time.
- Keep `generation` Int64 column and append-verify-delete protocol unchanged until this debt is closed.
- Multi-replica Engine writers are out of MVP support.

**Tracking:** `DEBT-P3-STAGING-GEN-RACE`

**Target:**
Phase 06 ingestion hardening.

**Escalation trigger:**
Concurrent same-`document_id` ingest in product use, multi-replica Engine, or production incident with stuck staging docs.

**Future acceptance criteria:**
- Generation allocation is atomic or serialized per document (in-process mutex minimum; multi-process needs stronger mechanism).
- Concurrent same-document replacement test exists and passes.
- Equal-generation poison state is not creatable under supported concurrency, or is automatically repaired by defined policy.

## T2: Physical row retention after delete failure (Plan 03-23 T2)

**Decision:** Defer.

**Problem:**
Plan requires that after successor verification, old-generation deletion failure leaves both physical rows, returns error, and does not delete the successor. Existing tests prove latest-wins selection and sequential ordering; they do not prove physical Lance row retention under injected delete faults. Verification marked this behavior_unverified (P), not failed (F).

**Decision rationale:**
No known counterexample; gap is evidence quality. Building fault-injection physical-row harness is test engineering with low demo value for force-close.

**Minimum guardrail to ship now:**
- None.
- Do not treat latest-wins reader success as proof of physical retention invariants.

**Known risk:**
- Likelihood now: Unknown (unproven)
- Impact if realized: Medium–High (incorrect failure retention / possible data loss on fault paths)
- Residual exposure: Delete-fail semantics may not match the written contract.

**Current operating constraints:**
- Rely on sequential happy-path replace only for confidence.
- Any staging protocol change must re-open T2 proof requirements.

**Tracking:** `DEBT-P3-STAGING-PHYSICAL-BU`

**Target:**
Phase 06 test hardening or next staging protocol change.

**Escalation trigger:**
Staging failure-injection work starts, or staging write protocol is modified.

**Future acceptance criteria:**
- Injected delete failure leaves countable old + successor physical rows.
- Error returned; successor not deleted.
- Assertions inspect storage rows/payloads, not only latest-wins API output.

## CR-03: Committed database credentials and disabled TLS

**Decision:** Defer.

**Problem:**
`config/config.toml` and `config/config.example.toml` contain reusable plaintext DB credentials (e.g. `postgres:postgres`) and `sslmode=disable`. Examples are copy-paste templates for environment config.

**Decision rationale:**
Matches intentional local docker-style MVP defaults under R4. Full secrets platform and history purge are out of force-close scope. User explicitly chose pure debt (not example hygiene commit).

**Minimum guardrail to ship now:**
- None in code.
- Documentation/ledger must state these are local-dev defaults only, not a supported remote posture.

**Known risk:**
- Likelihood now: Medium (credentials in git; easy mis-copy)
- Impact if realized: High if used on shared/non-local DB
- Residual exposure: Secret material in tree/history; unencrypted DB traffic if remote.

**Current operating constraints:**
- Single-host local Postgres only.
- Do not deploy committed defaults to shared, staging, or production databases.

**Tracking:** `DEBT-P3-CONFIG-DB-PLAINTEXT`

**Target:**
Phase 06 secrets/config hygiene.

**Escalation trigger:**
Non-local Postgres, shared environment, or secrets review.

**Future acceptance criteria:**
- No reusable live credentials in committed tracked config.
- Example uses placeholders; secrets from env/secret manager.
- TLS required for non-local DB connections; insecure local mode explicit opt-in.

## CR-04: Insecure Gateway→Engine gRPC

**Decision:** Defer.

**Problem:**
`gateway/main.go` dials the engine with `insecure.NewCredentials()` while `engine_addr` is configurable. No TLS and no peer authentication on that channel.

**Decision rationale:**
Loopback single-host MVP makes plaintext gRPC acceptable. Full mTLS is Phase 06 sized. User chose pure debt and to extend Phase 02 `DEBT-CR-04` rather than a new primary ID; loopback startup guard was not nominated for the close.

**Minimum guardrail to ship now:**
- None in code.
- Operational: `engine_addr` must remain loopback / single-host only.

**Known risk:**
- Likelihood now: Low on true loopback; High if addr is remote
- Impact if realized: High (MITM, spoofed engine, plaintext ingest/query)
- Residual exposure: Misconfiguration to a network address silently stays insecure.

**Current operating constraints:**
- Engine reachable only via loopback or equivalent single-host path.
- Multi-host compose without TLS is unsupported.

**Tracking:** `DEBT-CR-04` (Phase 02 origin; **extended** with Phase 03 evidence)

**Target:**
Phase 06 transport hardening (or earlier on trigger).

**Escalation trigger:**
Non-loopback `engine_addr`, multi-host deployment, or shared network path to Engine.

**Future acceptance criteria:**
- TLS with cert/hostname validation (prefer mTLS or equivalent engine auth) for non-local.
- Or hard fail startup when insecure credentials pair with non-loopback address.
- Phase 03 gateway insecure dial evidence closed or explicitly limited to dev-only mode enforced in code.

**Ledger note:**
Do not create `DEBT-P3-GRPC-INSECURE` as a second primary ID. Phase 03 deferred-items may include a one-line see-also to `DEBT-CR-04`.

## CR-05: Provider endpoint trust and bearer exfiltration

**Decision:** Defer.

**Problem:**
Effective settings validate provider endpoints only as non-blank. Embedding and generation clients attach the API bearer token. `OpenRouterGenerationConfig::with_endpoints` can replace endpoints after construction. A typo or attacker-controlled URL can receive the credential.

**Decision rationale:**
MVP treats operator-supplied endpoints like other local secrets/config (R4). Allowlist/HTTPS productization is Phase 06. Distinct from CR-01 (body size) and likely distinct from Phase 02 `DEBT-CR-05` (pre-admission bounds); do not merge by default.

**Minimum guardrail to ship now:**
- None in code.
- Operators must only configure intended provider base URLs.

**Known risk:**
- Likelihood now: Low–Medium (typo / bad config)
- Impact if realized: High (API key exfiltration)
- Residual exposure: Any nonblank URL may receive bearer credentials.

**Current operating constraints:**
- Provider endpoint is operator-trusted input.
- Do not accept endpoint values from untrusted multi-tenant config sources.

**Tracking:** `DEBT-P3-PROVIDER-ENDPOINT-TRUST`

**Target:**
Phase 06.

**Escalation trigger:**
Multi-tenant or untrusted config source, security review, or non-operator-controlled endpoint injection.

**Future acceptance criteria:**
- Parse/validate endpoint at final construction boundary.
- HTTPS required except explicit loopback dev mode.
- Host allowlist or equivalent policy before attaching bearer.
- `with_endpoints` revalidates or is test-only.

## WARN-DX: Fixture and upload DX issues

**Decision:** Defer.

**Problem:**
Fixture seeder appends duplicate stable IDs on re-run (non-idempotent). Empty multipart uploads can yield ambiguous gateway/engine failures instead of deterministic 400.

**Decision rationale:**
Developer-experience and edge-upload clarity; not blocking happy-path RAG demo.

**Minimum guardrail to ship now:**
- None.
- Prefer clean fixture paths or manual reset when re-seeding.

**Known risk:**
- Likelihood now: Medium for seeder re-runs; Low for empty upload in demos
- Impact if realized: Low–Medium (flaky tests / confusing errors)
- Residual exposure: Duplicate corpus rows; ambiguous empty-file errors.

**Current operating constraints:**
- Treat seeder as non-idempotent; reset DB/fixture dir when needed.

**Tracking:** `DEBT-P3-WARN-DX`

**Target:**
Phase 06 DX/fixture overhaul.

**Escalation trigger:**
CI flake from duplicate seeds or user-facing empty-upload incidents.

**Future acceptance criteria:**
- Seeder reset/upsert or refuse non-empty without flag.
- Empty multipart rejected with clear HTTP 400 or explicitly supported empty-doc contract.

## WARN-API: API semantics and D1 identity gaps

**Decision:** Defer.

**Problem:**
Mixed answer basis accepted without required conflict disclosure. `NoEvidenceFits` mapped to invalid_argument/HTTP 400 (capacity blamed on client). BM25/fusion/rerank failures may omit D1 session/correlation/error-kind metadata that dense/generation paths attach.

**Decision rationale:**
Adjacent to later API/RAG hardening; some neighbor RAG-03 themes. Not required for verified happy path. Must not expand into RAG-03 feature delivery in this close (R5).

**Minimum guardrail to ship now:**
- None beyond existing fail-closed paths already verified for core D1 cases.

**Known risk:**
- Likelihood now: Medium on edge paths
- Impact if realized: Medium (client mis-handling; harder ops correlation)
- Residual exposure: Misleading status codes; incomplete error identity on some pipeline stages.

**Current operating constraints:**
- Clients should not assume Mixed always carries conflict notices.
- Capacity failures may appear as 400 until debt closes.

**Tracking:** `DEBT-P3-WARN-API`

**Target:**
Phase 06 API contract hardening.

**Escalation trigger:**
External client integration depends on precise status/identity, or hardening sprint starts.

**Future acceptance criteria:**
- Mixed requires bounded conflict disclosure notice/warning.
- `NoEvidenceFits` maps to capacity-appropriate status (e.g. ResourceExhausted) with matching HTTP.
- BM25/fusion/rerank infrastructure errors use `d1_status` (or equivalent) with stable error kinds.

## WARN-SET: Settings consistency warnings

**Decision:** Defer.

**Problem:**
Invalid numeric env overrides can be silently ignored. Public scalar grounding budgets coexist with private `GroundingLimits` carrier. Invalid chunk settings may default or saturate to `i32::MAX` on persistence.

**Decision rationale:**
Maintainability and fail-closed consistency; startup happy path with valid config works.

**Minimum guardrail to ship now:**
- None.
- Operators should set valid env overrides only and prefer file config for critical limits.

**Known risk:**
- Likelihood now: Low–Medium
- Impact if realized: Medium (silent wrong budgets/chunking)
- Residual exposure: Config looks loaded but effective values differ from intent.

**Current operating constraints:**
- Validate critical overrides manually when using env.
- Do not treat public scalar fields as authority over the private carrier.

**Tracking:** `DEBT-P3-WARN-SETTINGS`

**Target:**
Phase 06 settings refactor.

**Escalation trigger:**
Production config via env at scale, or settings-related incidents.

**Future acceptance criteria:**
- Present-but-invalid env overrides fail startup with named variable.
- Single authority for grounding budgets (carrier-only accessors).
- Chunk settings validation fail-closed; no silent saturate of durable policy fields.

## WARN-VAL: Validation gaps (nulls and non-finite)

**Decision:** Defer.

**Problem:**
Staging readers may call `.value(i)` without null checks on required fields. Embeddings checked for count/dimension but not `f32::is_finite`. BM25 finite boosts can still overflow to non-finite scores before fusion reject.

**Decision rationale:**
Corrupt/partial rows and hostile numeric payloads are secondary under controlled local corpora and providers. Fusion already rejects some non-finite paths downstream.

**Minimum guardrail to ship now:**
- None beyond existing fusion finite checks where present.

**Known risk:**
- Likelihood now: Low on clean local data
- Impact if realized: Medium–High (panic, bad vectors, invalid intermediate scores)
- Residual exposure: Malformed Lance rows or non-finite embeddings/scores enter durable or intermediate state.

**Current operating constraints:**
- Do not feed untrusted embedding providers without review.
- Treat staging corruption as stop-the-line ops issue if observed.

**Tracking:** `DEBT-P3-WARN-VALIDATE`

**Target:**
Phase 06 validation sweep.

**Escalation trigger:**
Untrusted embedding source, observed staging corruption, or numeric incidents in retrieval.

**Future acceptance criteria:**
- Required staging fields null-checked with typed corruption errors.
- All embedding components finite at provider boundary and before Lance write.
- BM25 applies boost ceilings and rejects non-finite scores at retrieval boundary.

## MOD-GRAPH: Dual library/binary module graph

**Decision:** Defer.

**Problem:**
`engine/src/lib.rs` and `engine/src/main.rs` both declare overlapping production modules (`generation`, `prompt`, `rerank`, `retrieval`, etc.), risking drift between test/library types and the running binary.

**Decision rationale:**
Structural maintainability debt; current binary path is what cross-runtime tests exercise. Refactor is invasive relative to force-close.

**Minimum guardrail to ship now:**
- None.
- Prefer running service-path tests against the binary-used modules when adding critical tests.

**Known risk:**
- Likelihood now: Medium over time
- Impact if realized: Medium (tests pass, service diverges)
- Residual exposure: Silent dual implementation drift.

**Current operating constraints:**
- Critical fixes must land on the path the binary actually compiles/uses.
- Avoid “library-only” fixes for service behavior.

**Tracking:** `DEBT-P3-MODULE-GRAPH`

**Target:**
Phase 06 engine layout refactor.

**Escalation trigger:**
Next large engine module change, or observed lib/bin behavioral drift.

**Future acceptance criteria:**
- Binary imports shared modules from the library crate.
- Only binary-local modules remain in `main.rs`.
- Dead/duplicate module warnings resolved for the shared surface.

## REJ-GEN: Remove custom `generation` column

**Decision:** Reject.

**Problem:**
Proposal to delete application-level `generation` to “fix” CR-02 because Lance is append-only/multi-version.

**Decision rationale:**
Lance table versions are not per-`document_id` logical generations. Removing the column destroys latest-wins ordering and failure-retention protocol that Plan 03-23 introduced. It does not provide atomic replace semantics.

**Minimum guardrail to ship now:**
- Keep `generation` Int64 and append-verify-delete protocol until a designed replacement (e.g. mutex/CAS/merge_insert) ships under `DEBT-P3-STAGING-GEN-RACE`.

**Known risk:**
- N/A (rejected change). Residual risk remains CR-02 under single-writer constraint.

**Current operating constraints:**
- Do not remove or ignore `generation` as a cleanup.

**Tracking:** N/A (rejected approach; residual tracked under `DEBT-P3-STAGING-GEN-RACE`)

**Target:**
N/A

**Escalation trigger:**
N/A — any future removal requires a new ADR that defines latest-row and failure-retention without `generation`.

**Future acceptance criteria:**
- N/A for this rejected option.

## REJ-REDESIGN: In-close functional hardening bundle

**Decision:** Reject (for Phase 03 force-close exit).

**Problem:**
Candidates included staging mutex/CAS/merge_insert, mTLS, loopback startup guard, config secret strip, provider allowlist/https-only, and behavioral warning fixes.

**Decision rationale:**
Explicit per-item decisions deferred each concern. Force-close code budget is fmt-only. Reopening redesigns re-blocks Phase 04.

**Minimum guardrail to ship now:**
- Operating constraints on each deferred item above.
- Fmt ship item only.

**Known risk:**
- Combined residual risk of all deferred items under violated constraints.

**Current operating constraints:**
- Honor local-only, single-writer, operator-trusted config/endpoint assumptions until debts close.

**Tracking:** Individual DEBT IDs above

**Target:**
Phase 06 (or triggers)

**Escalation trigger:**
Any constraint violation or Phase 06 hardening start.

**Future acceptance criteria:**
- Per deferred item future criteria; not bundled into Phase 03 exit.

## RAG-02: Hybrid retrieval requirement checkbox

**Decision:** Accept-as-is (MVP qualified satisfaction).

**Problem:**
Verification left RAG-02 blocked at full plan-contract level because CR-01 and CR-02 plan truths failed, despite roadmap happy-path success criteria verifying on the exercised path.

**Decision rationale:**
Force-close accepts the demoable completed-corpus hybrid path as MVP satisfaction while residual contract gaps are named debt. Claiming unconditional full-contract satisfaction would overstate quality; leaving phase open forever fails R1.

**Minimum guardrail to ship now:**
- REQUIREMENTS must read **SATISFIED (MVP, see DEBT-P3-*)**, not bare SATISFIED without debt pointer.
- Do not claim verification `passed` or 101/101 plan truths.

**Known risk:**
- Likelihood now: N/A (documentation/process)
- Impact if realized: Medium if readers ignore debt qualifier
- Residual exposure: Stakeholders may over-read “satisfied.”

**Current operating constraints:**
- Marketing/docs internal: hybrid RAG MVP path works under constraints in this ADR.
- Full safety/security contract is Phase 06 residual.

**Tracking:** Residual via `DEBT-P3-BODY-BOUND`, `DEBT-P3-STAGING-GEN-RACE`, and related DEBT-P3-* 

**Target:**
Phase 06 for unqualified full-contract closure if desired.

**Escalation trigger:**
External production readiness review requiring unqualified RAG-02.

**Future acceptance criteria:**
- Blocking DEBT-P3 items that underpinned the original RAG-02 block are closed and re-verified, or a superseding ADR redefines the requirement boundary.

## RAG-04: Pluggable reranker

**Decision:** Accept-as-is.

**Problem:**
None outstanding for Phase 03 acceptance. Async `Reranker` + `NoOpReranker` verified.

**Decision rationale:**
Verification and roadmap SC4 satisfied.

**Minimum guardrail to ship now:**
- None.

**Known risk:**
- None material for this item.

**Current operating constraints:**
- None beyond normal API stability.

**Tracking:** N/A

**Target:**
N/A

**Escalation trigger:**
N/A

**Future acceptance criteria:**
- N/A

## RAG-03: Degraded / model-only / citation-repair family

**Decision:** Defer (pre-existing; not reopened).

**Problem:**
RAG-03 behaviors (degraded retrieval, model-only answers, citation repair/downgrade, re-ingestion recovery, expanded negative matrix, graph fallback) are explicitly out of Phase 03.

**Decision rationale:**
R5 and roadmap assign these to Phase 06. Force-close must not pull them in.

**Minimum guardrail to ship now:**
- Keep valid-path fail-closed behavior already implemented (e.g. ModelOnly reject on valid path).
- Do not implement degraded continuation as part of close.

**Known risk:**
- As previously recorded in DEBT-RAG-*.

**Current operating constraints:**
- No model-only fallback on infrastructure failure for the valid path.

**Tracking:** `DEBT-RAG-01`, `DEBT-RAG-03`, `DEBT-RAG-04`, `DEBT-RAG-05`, `DEBT-RAG-06` (existing)

**Target:**
Phase 06

**Escalation trigger:**
Product requirement for degraded answers before Phase 06, or production need for those behaviors.

**Future acceptance criteria:**
- Per existing RAG-03 / debt definitions in roadmap and deferred-items.

# Exit Conditions

The scope of this ADR is complete when:

1. All `ship` items (META, FMT) meet their acceptance criteria.
2. Verification commands for the close package:
   - `cargo fmt --manifest-path engine/Cargo.toml --all -- --check` passes.
   - Recommended: `cargo test --manifest-path engine/Cargo.toml --locked` passes after fmt.
3. All deferred/rejected/accepted-as-is items are recorded in the project debt ledger with residual risk and escalation triggers as specified.
4. STATE/ROADMAP/REQUIREMENTS reflect force-closed Phase 03, Phase 04 next, RAG-02 MVP wording, RAG-04 satisfied, RAG-03 still deferred.
5. No functional redesign from the Reject list is smuggled into the close commit.
6. No placeholder marked `[TODO]` remains on a path required for exit.

# Review Triggers

Review this ADR before any of the following:

- Non-loopback or multi-host deployment of gateway/engine
- Non-local Postgres or shared database environments
- Concurrent same-`document_id` ingest or multi-replica Engine writers
- Untrusted or multi-tenant configuration sources for provider endpoints or secrets
- Security review of provider I/O, credential handling, or transport
- Production readiness review requiring unqualified RAG-02
- Phase 06 hardening sprint start
- Any change to staging generation protocol or removal of `generation`
- Exposure of Engine or Gateway beyond single-operator local trust boundaries

# Decisions Locked

- [x] Adopt force-close criteria R1–R5 for Phase 03 exit
- [x] Force-close Phase 03 and enter Phase 04 after close package
- [x] Ship mechanical `cargo fmt` only as pre-exit code
- [x] Defer CR-01 as `DEBT-P3-BODY-BOUND`
- [x] Defer CR-02 as `DEBT-P3-STAGING-GEN-RACE`; keep `generation`; single-writer/doc MVP
- [x] Defer T2 as `DEBT-P3-STAGING-PHYSICAL-BU`
- [x] Defer CR-03 as `DEBT-P3-CONFIG-DB-PLAINTEXT` (no config hygiene code in close)
- [x] Defer CR-04 by extending `DEBT-CR-04` (no new primary gRPC debt id; no loopback guard code)
- [x] Defer CR-05 as `DEBT-P3-PROVIDER-ENDPOINT-TRUST` (do not default-merge into P02 `DEBT-CR-05`)
- [x] Defer warnings as clustered `DEBT-P3-WARN-DX|API|SETTINGS|VALIDATE` and `DEBT-P3-MODULE-GRAPH`
- [x] Reject removing `generation` as a CR-02 fix
- [x] Reject in-close mTLS, allowlist, mutex/CAS redesign, and warning behavior fixes
- [x] RAG-02 = SATISFIED (MVP, see DEBT-P3-*); RAG-04 satisfied; RAG-03 unchanged deferred
- [x] Do not claim verification status `passed` or 101/101 solely due to force-close
- [x] Cancel `DEBT-P3-FMT` because fmt ships

# Open Items

None.

Ledger write and STATE/ROADMAP/REQUIREMENTS edits are implementation of locked decisions, not open product choices.