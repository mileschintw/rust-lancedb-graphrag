---
gsd_state_version: 1.0
milestone: v1.0
current_phase: 06.3
current_phase_name: Evaluation Harness, Corpora and Recorded Run (OBS-02, OBS-04) (INSERTED)
status: executing
stopped_at: Phase 6.3 post-execution gates run — gaps_found, 6/9 must-haves, phase not complete
last_updated: "2026-08-30T21:51:52.096Z"
last_activity: 2026-08-30
state_head: 3177a830a494a2a09a59894fd346b1514d79f164
progress:
  total_phases: 11
  completed_phases: 6
  total_plans: 131
  completed_plans: 129
milestone_name: milestone
current_plan: 8
---

# Project State

## Current Status

- **Phase 06.3 (Evaluation Harness, Corpora and Recorded Run): All 8 plans executed and committed:**
  - `06.3-08` (Wave 1): Additive `retrieved_chunks` on `RetrievalSnapshot` wire format (`b7d50b4`).
  - `06.3-01` (Wave 2): `eval/` uv package, SSE client, `DimensionResult`, `CorpusReport` schema, Typer CLI (`ddc1d73`, `0278256`).
  - `06.3-02` (Wave 2): Generation model drift-anchored Rust tests and raised engine test invariants (`5e12605`, `9adb2a1`).
  - `06.3-03` (Wave 3): Deterministic corpora loaders, MultiHop-RAG sample, deterministic IR & answer metrics, registered dimensions (`07d4b83`, `000dd75`, `c19418e`, `8a454b9`).
  - `06.3-04` (Wave 4): Database isolation (`schema.eval.hcl`), store paths, document seeder, atomic `document_map.json`, preflight checks (`6a00834`, `0973b65`).
  - `06.3-05` (Wave 5): Resumable journal, two-armed driver, offline deterministic scorer, graph ablation dimension (`a3028d2`, `54f604b`).
  - `06.3-06` (Wave 6): LLM-as-judge scoring, calibration slice, OpenRouter cache (`ed9801c`, `e1092a5`).
  - `06.3-07` (Wave 7): Report generator, run-record layout, publication preconditions, reviewer checklist (`2bea5e8`, `3858d25`).
  - **Test Suite:** 119/119 unit/integration tests passing offline across `eval/tests/`.
  - **Boundary:** Stopped before phase-level code review, regression gate, verification, or UAT per user directive.
- **Quick Task 260831-az7 (Paid Model Migration & Full Reseed Execution - 2026-08-31 / 2026-09-02):**
  - **Task 1 (Engine Models & Invariants):** Migrated embedding model to `voyageai/voyage-4-large` with explicit `dimensions: 2048` parameter; migrated generation model to `deepseek/deepseek-v4-flash-0731` with explicit `"reasoning": {"effort": "none"}` to suppress chain-of-thought token depletion. All 488/488 Rust tests and Go tests passing.
  - **Task 2 (Eval Harness Models & Pytest):** Repinned judge model to `meta-llama/llama-3.3-70b-instruct` (paid tier) and generator fallback to `deepseek/deepseek-v4-flash-0731`. All 136/136 eval pytest tests passing offline.
  - **Task 3 (Corpus Reseed & Concurrency Optimization):** Successfully seeded all **346 / 346 articles** of `multihop_rag` with `LANCET_ENV=eval` isolated store (PostgreSQL + LanceDB). Migrated extraction concurrency (`15`) and embedding concurrency (`12`) into explicit configuration parameters (`config/config.toml` & `engine/src/config.rs`) to maximize throughput under paid tier API limits. Optimized LanceDB entity deletions to batched `IN (...)` queries, eliminating version bloat and stalling.
  - **Task 4 (Preflight Health Verification):** Verified `lancet-eval preflight --corpus multihop_rag` passed all checks (`store_isolation`, `gateway_reachable`, `engine_reachable`, `corpus_generation` at `lance-701`, and `openrouter_api`).
  - **Task Summary:** `.planning/quick/260831-az7-phase-6-3-is-currently-stuck-the-previou/260831-az7-SUMMARY.md` produced and committed.


- Phase 06.1 Plan 06.1-01 executed: implemented index rebuild-and-swap, CorpusStore snapshot isolation, same-snapshot dense/BM25 pinning, worker burst debouncing, fail-closed rebuild_debounce_ms configuration, and degraded notice emission (NoticeCode::IndexRebuildFailed).
- Phase 06.1 Plan 06.1-02 executed: deterministic proofs for DEBT-BU-01 (run_window evaluation before challenge validation) and DEBT-BU-02 (sample_owned cleanup isolation harness and 26/26 passing unit tests).
- Phase 06.1 Plan 06.1-03 executed: documented code review and factual re-acceptance of DEBT-CR-04 and DEBT-CR-05 (0 production diffs; 06.1-CR-REVIEW.md produced).
- Phase 06.1 post-execution gates RUN (2026-08-23) — **code review + verification found a real structural gap; phase NOT complete.**
  - **Code review** (`06.1-REVIEW.md`, `d3267c6`; scope pinned via `--files` to the 14-file `541bade^..e794613` product delta — cross-checked against all three plans' SUMMARY key-files/artifacts lists, exact match, no drift): `status: issues_found` — 2 critical, 2 warning, 2 info. CR-01/CR-02: `rebuild_and_swap` (`engine/src/ingest.rs:1454-1459`) and `ProductionDenseRetrievalPort::retrieve_dense` (`engine/src/service.rs:502-538`) both `.clone()` and `.checkout()`/`.checkout_latest()` the *same* long-lived `lancedb::Table` handle (one `database.nodes_table()` call in `main.rs:30`, shared into `LancetServiceImpl.nodes` and the debounce task). Both the reviewer and the orchestrator independently verified against the vendored `lancedb` 0.31.0 source (`src/table.rs:727-732`, `src/table/dataset.rs:18-33,111-117`) that `Table::clone()` shares one `Arc<Mutex<DatasetState>>` `pinned_version` cell — concurrent `checkout()` calls race on it, so a query can be served from a different LanceDB version than the one it recorded in its own `RetrievalSnapshot.index_generation`. WR-02: `ingest.rs:1455` discards `checkout_latest()`'s error (`let _ = ...`) and reports the rebuild as successful instead of degrading.
  - **Regression gate PASSED but is not evidence for the gap above** (orchestrator-run, not executor self-report): `cargo test --manifest-path engine/Cargo.toml --locked` = 404/404 (366 lib + 1 ignored + 18 `inspect_lancedb` + 19 `config_startup`, matching `scripts/engine-test-targets.sh`'s updated pins, script + full execution both independently run); `cd gateway && go test ./...` = all packages ok; `python -O -m unittest discover -s scripts -p "test_*.py"` = 26/26 (includes the six named BU-01/BU-02 proofs). WR-01 (code review) explains why: none of the existing "isolation" tests exercise the shared-checkout race — `rebuild_swap_generation_atomicity` only asserts a string prefix set at construction time, and `test_checkout_clone_isolated_from_live_writes` proves isolation between two *independently-opened* tables, not the shared-clone path production code actually uses.
  - **Verification** (`06.1-VERIFICATION.md`, `9533ef0`): `status: gaps_found`, **4/7 must-haves**. SC1 VERIFIED (rebuild/debounce/config machinery, named tests). SC2 FAILED (single-generation query isolation — the checkout race above). SC3 FAILED (dense/BM25 never-mixed — same root cause; BM25 half via `Arc<CorpusSnapshot>` is genuinely isolated, dense half is not). SC4 FAILED (narrower, independent: discarded `checkout_latest()` error means a real failure reports `rebuild_degraded: false` instead of taking the correctly-implemented degraded/`IndexRebuildFailed`-notice branch). SC5/SC6/SC7 VERIFIED (DEBT-BU-01/BU-02 deterministic proofs; DEBT-CR-04/CR-05 documented review — content cross-checked against `gateway/main.go` directly). Two of Plan 06.1-01's own frontmatter prohibitions are violated *in effect*: the checkout-isolation prohibition was followed literally (clone-then-checkout) but its assumption about what `.clone()` isolates was wrong.
  - **`requirements.revert-phase` deliberately NOT run** (orchestrator judgment call, not a mechanical skip — see [[requirement-revert-shared-id-footgun-lancet]]): RAG-03 is cited by both Phase 6 (completed 2026-08-22, 11/11 must-haves, human-verified UAT) and Phase 6.1 (this round, DEBT-RAG-04 clause only). REQUIREMENTS.md has one shared `- [x]` checkbox for both — `cmdRequirementsRevertPhase`'s checkbox surface has no per-phase attribution, so reverting is all-or-nothing on a requirement two phases jointly own. #2388's own stated intent argues FOR reverting (a `gaps_found` verdict shouldn't leave a premature `Complete` standing, and this verification report itself scores RAG-03 coverage `✗ BLOCKED (partial)`) — that's a legitimate reading. Chose not to revert because Phase 6's own delivery is independently complete and unaffected by Phase 6.1's gap, and the open work is fully visible in this VERIFICATION.md and this STATE.md entry regardless of the checkbox. A future session could reasonably choose the other way. (The traceability-row surface is a confirmed no-op either way — this table's column is named "Scope status", not "Status", so `updateTableCell` returns `unknown column` and never writes.) REQUIREMENTS.md left untouched.
  - **Phase 6.1 NOT complete.** `phase.complete` correctly NOT run. Next: `/gsd-plan-phase 6.1 --gaps` to plan the fix (give `ProductionDenseRetrievalPort` and `rebuild_and_swap` a `DatabaseManager` handle and open an independent `Table` per call instead of cloning the shared one; propagate the `checkout_latest()` error into the existing degraded-snapshot branch), then `/gsd-execute-phase 6.1 --gaps-only`.

- Phase 1 completed successfully.
- Phase 2 completed (force-closed per ADR-02-004; all open gaps marked as technical debt deferred to Phase 6 final hardening).
- Phase 3 completed (force-closed per ADR-03-003; 23/23 plans executed; residual verification gaps recorded as technical debt DEBT-P3-* deferred to Phase 6 final hardening; next phase = Phase 4).
- Phase 4 completed (lance-graph/lancedb compatibility spike only, per ROADMAP's "Deferred target" note; UAT 3/3 passed, SECURITY.md verified threats_open: 0; full extraction/storage/query-traversal implementation deferred to Phase 04.1, not yet created; next phase = Phase 5).
- Phase 04.1 Plan 03 executed: concurrent bounded extraction, WR-01 IPC multi-batch bridge fix, extraction retries with confidence validation, and re-ingestion rollback proof.
- Phase 04.1 Plan 04 executed: QueryGraph RPC as a Cypher-constrained induced-neighborhood query with bounded/validated input, including a fix for a pre-existing fetch_neighborhood bidirectional-BFS edge-duplication bug.
- Phase 05 Wave 10 Plan 05-14 executed: closed `NodeKind` enum with 5 variants, exhaustive typed runner dispatch, early 9-variant admission rejection, and focused dispatch tests.
- Phase 05 Wave 11 Plan 05-17 executed: additive protobuf fields (RetrievalSnapshot tags 10/11, WorkflowCompletedEvent tag 6) and synchronized Rust/Go bindings with protected module glue.
- Phase 05 Wave 12 Plan 05-23 executed: repaired exhaustive Rust RetrievalSnapshot and WorkflowCompletedEvent message literals, verified clean compilation, and proved additive tags 10/11 round-trip fidelity.
- Phase 05 Wave 13 Plan 05-18 executed: split Phase 5 workflow tests into library unit-test target (`workflow_phase5`) and binary-owned production module (`workflow_phase5_production`), introduced `Bm25IndexStore` alias, migrated 18 BM25 test constructions, and verified library execution and binary compilation.
- Phase 05 Wave 17 Plan 05-19 executed: preserved accumulated notices on failure terminal events through Rust runner and Go raw SSE stream while keeping failure terminals answer-free.
- Phase 05 Wave 17 Plan 05-24 executed: closed resolved cross-variant RRF contract with two-pass fusion (`fuse_candidates` in loop, `fuse_cross_variant_candidates` merge pass), retired `fuse_variant_candidates`, and verified exact scoring and deterministic tie resolution.
- Phase 05 Wave 18 Plan 05-22 executed: completed production typed graph-fact handoff and end-to-end query_rag workflow tests.
- Phase 05 Wave 19 Plan 05-20 executed: separated capability preflight from the GenerateAnswer node timer and proved the two-attempt retry path fits the 65s node timer with paused-clock timing proofs.
- Phase 05 Wave 20 Plan 05-11 executed: proved and hardened real engine-to-gateway SSE stream across 5-node lifecycle and graph fixtures, verified client cancellation propagation, structured stream error framing, and lossless checkpoint persistence under backpressure.
- Phase 05 post-execution gates RE-RUN (2026-08-19) after gap-closure plans 05-25 and 05-26 landed: all 26 plans complete; ROADMAP plan checkboxes and plan counts reconciled for 05-25/05-26 (commit e6e153f).
  - TRACE-01 RECONCILED: ROADMAP.md said "26/26" and its checkbox list ended at 05-26 while `05-27-PLAN.md` existed with a SUMMARY and landed `e831be3` — the commit closing the gap the roadmap tracks. Corrected to 27/27 with 05-27 added to both the plan list and a new Wave 22.
  - Security gate UNCHANGED: `workflow.security_enforcement` is active and NO 05-SECURITY.md exists — `/gsd-secure-phase 5` still required before advancing.
  - Phase still NOT marked complete: verification returns `human_needed`, not `passed`. Next: `/gsd-verify-work 5`.
- Phase 05 UAT completed (2026-08-19) via `/gsd-verify-work 5`, resuming the in-flight session. G-05-1 reconciled `resolved` (root causes closed in code by 05-25/05-26/05-27). Test 1 re-run live against real OpenRouter: full 5-node frame sequence, no `stream_error`, citations grounded in the local dev LanceDB store's fixture data (fixture content, not a real corpus — pipeline mechanics fully proven). Tests 7-10 (judgment-tier dispositions) resolved: buffer-depth invariant re-accepted at the post-`5354d1e` code site (Test 7); gateway bind-failure exit-code regression found ALREADY fixed by `fe83e71` and verified empirically (`exit=1`) (Test 8); terminal-event suppression on FinalAnswer failure found ALREADY fixed by `0c96720a` (Test 9); checkpoint sequence-ordinal burning on failed delivery accepted as debt, `wrap_next_event` found already lazy via the same `0c96720a` refactor (Test 10). Final: **10/10 passed, 0 issues**. `05-SECURITY.md` confirmed present with `threats_open: 0` (security gate clear). Verification canonicalized `human_needed` → `passed`. Phase 05 marked complete via `phase.complete`; PROJECT.md evolved (4 requirements moved to Validated, 4 new Key Decisions logged); next phase = Phase 6.
- Phase 06 Wave 6 Plan 06-08 executed: implemented graph ablation flag and distinct `GRAPH_UNAVAILABLE` notices; proved source-chunk query survival.
- Phase 06 Wave 7 Plan 06-09 executed: converted dense and lexical retrieval paths from fail-closed to degrade (D-13 / DEBT-RAG-01); pinned 3-notice sequence on both-paths degradation.
- Phase 06 Wave 8 Plan 06-10 executed: supported model-only answers as an explicit, per-request, default-off opt-in (D-10/D-11/D-12/D-84 / DEBT-RAG-01).
- Phase 06 Wave 11 Plan 06-13 executed: closed SC3 gap with OpenRouter empty-evidence packing branch, dedicated model-only system policy, GenerationRequest allow_model_only plumbing, and answer_basis schema enum admission.
- Phase 06 Wave 12 Plan 06-14 executed: closed SC5 gap with first-occurrence de-duplication of repaired citation IDs in GenerateAnswerNode and resolve_citations_with_max_chars.
- Phase 06 Wave 13 Plan 06-15 executed: split grounding validator into shape and marker validation, relocated marker checks from OpenRouter provider adapter to GenerateAnswerNode and gated run_inline_prompt_generation_remainder; proved SC3 and SC5 reachability through real OpenRouterGenerator across five mock-server tests; updated test target invariants to 386/351.
- Phase 06 post-execution gates RUN (2026-08-22) after gap-closure plans 06-13/06-14 landed at `953b22c`:
  - **Code review** (`192cf35`, scope pinned to the 8-file `953b22c` delta per the repo's harness-scope hazard): `status: issues_found` — 2 critical, 5 warning new findings. CR-01: SC5 citation repair is unreachable in production because `execute_one_call` validates raw model output at `openrouter.rs:788-792` before `GenerateAnswerNode`'s repair pass runs. CR-02: `model_only_system_policy` never instructs `answer_basis: "model_only"`, so the natural `retrieval`+empty-citations reply hard-fails at `generation/mod.rs:210-220`. Of the 18 pre-gap-closure findings: prior CR-01 resolved; prior CR-02 partial; CR-03, WR-01, WR-04, WR-11 still open; CR-04/CR-05 deferred to Phase 6.1; 10 not re-checked because their files sit outside the pinned delta scope (WR-02/03/05/06/07/08/09/10/12/13).
  - **WR-01 severity corrected** (orchestrator-verified, the two agents disagreed): `run_inline_prompt_generation_remainder` (`engine/src/workflow/mod.rs:249`) is a dead **test-only** public surface, NOT a live fail-open path. All five call sites are in `engine/src/tests/workflow_phase5.rs`, which `engine/src/lib.rs:19-21` declares under `#[cfg(test)]`. It still matters as a dependency of the CR-01 fix — gate it before moving `validate_grounding_with_limits` out of the provider adapter, or that move makes it genuinely fail-open.
  - **Regression gate PASSED**: Rust 380 tests (344 passed / 1 ignored / 0 failed across lib+bin+integration targets, matching the pinned count in `scripts/engine-test-targets.sh`) and the full Go gateway suite, both exit 0. No cross-phase regressions.
  - **Re-verification** (`e92a544`): `status: gaps_found`, still 5/7 must-haves. SC3 upgraded `failed` → `partial` (all four prior `missing` items implemented, but the model-only contract is model-decided rather than engine-decided). SC5 stays `partial` with a NEW, deeper root cause — the 06-14 dedup fix is correct and both prior repros now pass, but repair only executes when a correctly-cited strict-visible marker rides along in the same answer to satisfy the adapter's set-equality check; standalone near-miss markers and the whole total-drop basis-downgrade clause remain unreachable under the default `citation_repair_enabled: true`.
  - Both gaps share one seam: `validate_grounding_with_limits` running inside the provider adapter. Fixer ordering matters — removing the adapter gate without first gating `run_inline_prompt_generation_remainder` would turn that published path fully fail-open.
  - ROADMAP's "SC3 → 6.4; SC5 and SC6 → 6.1" note maps the ORIGINAL pre-split criteria and does NOT license deferring these two gaps (proof: it sends "SC1 → 6.2", but current SC1 is the module graph, not OpenTelemetry). Phase 6.1 and 6.4 criteria mention neither model-only answers nor citation repair.
  - Phase 6 NOT complete. Security gate still open: `workflow.security_enforcement` active and no `06-SECURITY.md` exists. `06-VALIDATION.md` is dated 2026-08-20 and predates plans 06-08..06-14.

- Phase 06 post-execution gates RUN (2026-08-22) after gap-closure plan 06-15 landed at `84baf5e` - **all three gates cleared; SC3 and SC5 are CLOSED**.
  - **Code review** (`9a09c9f`, orchestrator rulings `ce3f43e`; scope pinned via `--files` to the 9-file `30fdc46^..84baf5e` delta per the repo's harness-scope hazard): `status: issues_found` - **0 critical** (2 raised, both downgraded on orchestrator ruling), 6 warning, 7 info. 25 prior findings carried forward under `## Carry-Forward From Prior Round`; the reviewer discovered the two prior tables shared an ID namespace, which is how a row could previously be silently lost.
  - **Prior CR-01 and prior CR-02 both RESOLVED**, verified not assumed: the reviewer re-derived all three new SC5 mock bodies against the PRE-split validator (`953b22c:openrouter.rs:792`) and confirmed each was rejected there, so the reachability proof is real rather than circular.
  - **Fail-open enumeration closed affirmatively** (the one risk the split created): 4 non-test `.generate()` sites in 2 functions, 4 non-test `update_from_model_output` sites, 2 non-test `events::answer_chunk` emitters - all downstream of a gate. **No third ungated path.** The plan's two-surface enumeration was complete.
  - **Orchestrator ruling - CR-01 and CR-02 downgraded critical -> info** (recorded in `06-REVIEW.md` frontmatter under `orchestrator_ruling`). Both applied branch-1 (SC3) contracts to the branch-2 (D-18) total-drop path. CR-01: 06-15-PLAN Task 1 says verbatim "Leave the existing model-only notice block (`NoticeCode::ModelOnly`) and its condition unchanged", and `must_haves` specifies BASIS_RECONCILED for total-drop, not MODEL_ONLY. CR-02: no plan contradiction exists - the must_have cited as conflicting opens "When both retrieval paths fail or **evidence is absent**", scoping it to branch 1; a separate must_have requires total-drop to downgrade "even with `allow_model_only` false", Task 3 requires "the downgrade must not depend on the SC3 opt-in", and the P1b design table documents `effective_allow = ctx.allow_model_only || total_drop` as intended. The verifier independently reached the same scoping conclusion from SC3's own `(D-10, D-11, D-12)` parenthetical.
  - **WR-03 CONFIRMED real, held at warning** (orchestrator-verified): `openrouter_node_model_only_flag_off_stays_fail_closed` asserts `chat_calls == 0` on a counter with no `chat_calls_server` clone and no `fetch_add`, unlike all four sibling tests - that assertion is vacuous. NOT escalated: the test also asserts `Err(LlmGenerationFailed)` whose message contains "prompt assembly failed", which the verifier confirmed has exactly one producer tree-wide (`openrouter.rs:285`, inside `pack_openrouter_messages`), pinning the fail-closed point upstream of chat dispatch without relying on the counter. SC3's flag-off half stays proven; the dead counter should be wired or removed.
  - **Regression gate PASSED**: `cargo test --manifest-path engine/Cargo.toml --locked` exit 0 - 351 lib (350 passed / 1 ignored) + 18 `inspect_lancedb` + 17 `config_startup` = **386 total**, exactly the counts 06-15 pinned. `cd gateway && go test ./...` exit 0, all packages ok, 0 failures. `sh scripts/engine-test-targets.sh` -> all 7 invariants verified.
  - **Re-verification** (`a593620`): `status: human_needed`, **score 7/7** (up from 5/7). `gaps_remaining: []`, `regressions: []`, `deferred: []`. 06-15 recorded in `re_verification.gap_closure_plans` with `resolution: resolved`.
    - **SC3 CLOSED** - the basis is now ENGINE-decided. `generate.rs:150` builds `for_validation = output.into_model_only()`, validates that, and passes `&for_validation` to `update_from_model_output` (`:166`); `should_treat_as_model_only()` enters the branch on `no_evidence` regardless of the model's claim. Proof test asserts on `ctx.answer_basis` / `ctx.citations` / `ctx.notices` - **not** the generator return - against a real `OpenRouterGenerator` whose mock body carries `answer_basis: "retrieval"`.
    - **SC5 CLOSED** - all three previously-unreachable clauses execute end to end: standalone near-miss `[ 7 ]` repaired, strict-visible unresolvable `[9]` dropped, total citation loss downgraded with BASIS_RECONCILED. All five new tests construct a real `OpenRouterGenerator` against mock HTTP servers; **zero** `FakeGenerator`/`PackingTestGenerator` in the added lines (the plan's `must_haves.prohibitions`). This is what rounds 1 and 2 lacked.
  - **T-06-15-03 residual is BROADER than 06-15-SUMMARY.md records** (verifier's primary-evidence finding, tagged `verification: backstop` -> `insufficient_spec`): at `953b22c:openrouter.rs:792` the adapter validated markers against `validation_evidence = packed_evidence.evidence` - the subset actually sent to the model. Today `openrouter.rs:534` discards it as `_validation_evidence` and **every** downstream gate binds to `ctx.evidence_blocks`, including the repair-*disabled* branch (`generate.rs:322`) and the inline remainder. So a surviving citation can ship a client-visible excerpt from a chunk the model never saw, and it applies system-wide, not only on the repair path. No test in the repo exercises a truncated-block marker -> human decision (UAT item 2).
  - **Advisory `coincidental_reliance: undeclared-precondition`**: all four new SC5/SC3 proofs use a single-block or empty evidence set, so `ctx.evidence_blocks == packed_evidence.evidence` holds trivially in each. Their green status depends on a no-truncation precondition production does not guarantee. Score and status unaffected.
  - **No deferral taken.** The ROADMAP note "SC3 -> 6.4; SC5 and SC6 -> 6.1" maps the ORIGINAL pre-split criteria and does not license deferring these gaps (proof: it sends "SC1 -> 6.2", but current SC1 is the module graph, not OpenTelemetry). Moot this round - both closed on the merits.
  - **Phase 6 NOT complete.** Verification is `human_needed`, not `passed`, so `phase.complete` was correctly NOT run and RAG-03 stays unchecked in REQUIREMENTS.md. 6 human items persisted to `06-UAT.md` (`bbbb07d`): (1) D-18 flag-off contract choice, (2) T-06-15-03 truncated-block binding decision, (3) MODEL_ONLY notice on the total-drop path, (4) four unresolved specless-probe edges, (5) security gate, (6) stale VALIDATION.md. Next: `/gsd-verify-work 6`.
  - Security gate STILL OPEN: `workflow.security_enforcement` active, `verify:post` secure-phase step hook active, and no `06-SECURITY.md` exists. `06-VALIDATION.md` is still `status: draft` / `nyquist_compliant: false`, dated 2026-08-20, predating plans 06-08..06-15.

- Phase 06 gap-closure PLANNED (2026-08-22) via `/gsd-plan-phase 06 --gaps` — `06-15-PLAN.md` (wave 13, `gap_closure: true`, `depends_on: [06-13, 06-14]`, 3 tasks, 78k est). Third attempt at SC3 + SC5; both prior attempts (06-13, 06-14) executed green and re-verified `partial`.
  - **One root cause, one plan.** `OpenRouterGenerator::execute_one_call` runs the full grounding validator on RAW model output at `openrouter.rs:792`, inside the provider adapter — upstream of the workflow layer that owns repair (SC5) and the model-only basis decision (SC3). Both gaps sit downstream of a gate that rejects their own inputs. All three fix steps touch the same five Rust files, so they are one plan, not two.
  - **Ordering is a hard safety sequence,** enforced by sequential task order plus two executable `<precondition>` greps: (1) gate `run_inline_prompt_generation_remainder` (`workflow/mod.rs:249-363`, `pub` and validation-free — test-only today, per the orchestrator-corrected WR-01 severity) → (2) split `validate_grounding_with_limits` into `validate_output_shape_with_limits` + `validate_marker_grounding`, moving the four marker checks (`mod.rs:331-365`) out of the adapter → (3) pin the `answer_basis` contract at both `generate.rs:147-165` and `openrouter.rs:788-792`. Doing (2) before (1) would turn a published surface fully fail-open.
  - **Test shape is the discriminating criterion.** Both prior rounds went green on doubles that never reach the failing layer (`grep -c OpenRouterGenerator engine/src/tests/workflow_phase5.rs` = 0; every SC3 test hardcoded `"answer_basis": "model_only"` in its mock body). 06-15 requires every SC3/SC5 proof to drive a real `OpenRouterGenerator` against a mock HTTP server through `GenerateAnswerNode::run` and assert on `WorkflowContext`, with a STANDALONE near-miss `[ 7 ]` (no healthy companion), a strict-visible unresolvable `[9]`, and the total-drop basis downgrade. `FakeGenerator`/`PackingTestGenerator` are prohibited as proof in `must_haves.prohibitions`.
  - **Accepted residual `T-06-15-03` (medium/mitigate):** post-split the marker checks bind to `ctx.evidence_blocks` (full retrieved set) rather than the packed subset, so a marker naming a retrieved-but-truncated block now resolves. The alternative mitigation is unavailable — retaining the cited-ID membership check in the adapter would re-break the total-drop clause. Disposition must be recorded in `06-15-SUMMARY.md`.
  - Gates: plan-checker **PASSED** (0 blockers / 0 warnings) after 3 iterations, 6 findings all closed (`cc258ab`, `1b6bf55`); requirements coverage 1/1; decision coverage 9/9; `verify.plan-structure` valid. Bounce skipped (`--gaps`).
- Phase 06 Wave 14 Plan 06-16 executed: closed UAT gaps G-06-1 (D-18 total-drop flag-off fail-closed) and G-06-2 (citations to retrieved-but-truncated blocks dropped with CITATION_DROPPED notices, not resolved; excerpt suppression). Updated engine test target distribution to 392 total / 357 lib.
- Phase 06 post-execution gates RE-RUN (2026-08-22) after gap-closure plan 06-16 landed at `949673e` — **all gates cleared, phase marked COMPLETE via `phase.complete`.**
  - **Correction to the two prior entries above:** both claimed "Security gate STILL OPEN... no `06-SECURITY.md` exists" — that was stale even at the time UAT ran. `06-SECURITY.md` (`7d96331`, `status: verified`, `threats_open: 0`) and a refreshed `06-VALIDATION.md` (`0bb1257`/`9d6e62c`) both landed BEFORE the UAT session (`8e84b20`), which is why UAT tests 5 and 6 read `pass`. Both gates were already closed; the STATE.md prose just never caught up.
  - **Code review** (`1d7ce9e`, scope pinned via `--files` to the 5-file `d171e4d..949673e` delta): `status: issues_found` — 0 critical, 3 warning. Both gaps independently verified at the code level (not test-presence): G-06-1's `effective_allow = ctx.allow_model_only` confirmed as the sole production diff; G-06-2 confirmed via a standalone harness calling `pack_evidence_and_graph_prompt` directly that the truncation test is genuine (2-in/1-out), not a pre-truncated fixture. New warnings: WR-01 (stale comment in `generate.rs:239-241`), WR-02 (a `tests.rs` service-boundary test flipped flag-on instead of gaining a flag-off sibling, leaving the fail-closed path untested at that boundary), WR-03 (G-06-2's e2e test asserts the consequence, not that packing caused it).
  - **Regression gate PASSED** (run directly by the orchestrator, not the executor's self-report): `cargo test --manifest-path engine/Cargo.toml --locked` exit 0 — 392 total (357 lib + 18 `inspect_lancedb` + 17 `config_startup`), 0 failed. `cd gateway && go test ./...` exit 0, all packages ok. `sh scripts/engine-test-targets.sh` — all 7 invariants verified.
  - **Re-verification** (`06-VERIFICATION.md`, 2026-08-22T22:15:00Z): `status: passed`, **11/11 must-haves** (7/7 ROADMAP SC + 4/4 gap-closure truths from 06-UAT.md's Gaps section). `human_verification: []`. 06-16 added to `re_verification.gap_closure_plans` with `resolution: resolved`.
    - **G-06-1 CLOSED** exactly as diagnosed — `generate.rs:258` no longer ORs `total_drop` into `effective_allow`; all four discriminating tests (flag-off/flag-on × unit/production-harness) re-run and pass under verification.
    - **G-06-2 CLOSED, but the 06-UAT.md diagnosis was WRONG about the mechanism** — `git diff d171e4d 949673e` shows zero production-code lines changed for G-06-2. The verifier traced that `AssemblePromptNode` (`assemble_prompt.rs:92-94`) already overwrote `ctx.evidence_blocks` with the packed/truncated subset before `GenerateAnswerNode` ran; the human's demanded behavior already held in production. The real gap was missing test coverage of the truncation path, not defective code in `generate.rs`/`openrouter.rs` as originally diagnosed. Closure came from four new tests proving it, plus the independent trace — `06-UAT.md`'s Gaps section now carries a `resolution:` block on G-06-2 recording this correction so a future reader doesn't assume the `missing` items were implemented as originally stated.
    - Also independently re-checked `run_inline_prompt_generation_remainder` (`workflow/mod.rs:251`, the "published inline remainder path" named in the 06-15 round): zero non-test callers repo-wide — dead code, cannot undermine either fix.
  - **`06-UAT.md` reconciled**: both Gaps entries (G-06-1, G-06-2) set to `status: resolved` with `resolution:` evidence blocks. Top-level frontmatter `status:` left as `diagnosed` (no template vocabulary word means "gaps closed by code, not re-observed by a human") and Test 1/Test 2 `result:`/Summary counts left untouched as the historical record of what UAT actually observed in that session — only the Gaps section (the field downstream tooling reads for resolution) was updated.
  - **`phase.complete` ran clean**: REQUIREMENTS.md RAG-03 checkbox flipped `[ ]` → `[x]` (confirmed via diff — this is the first round verification reached `passed`, so the first round this write was live). One residual advisory: the Traceability table's RAG-03 row spans "Phase 06, Phase 06.1" and the auto-annotator skipped it (no single-phase match) — the row's prose is already accurate, just not auto-stamped; not a correctness gap, matches [[gap-analysis-gate-false-zero-lancet]]'s class of tooling quirk in this repo.
  - Phase 6 COMPLETE. `current_phase` advances to 06.1 (Index Rebuild-and-Swap, BU Deterministic Proofs, CR-04/CR-05 Documented Review).

- Phase 06.2 execution completed (2026-08-22 through 2026-08-24) — all 6 plans (foundation tracer slice, query-path span surface, observability infra/dashboard, ingestion spans, operational metrics, log correlation/degraded_mode) executed and summarized, but the session that ran them stopped before code review or verification. Resumed at the phase gates 2026-08-24 (#2868 path — `verification.status` returned `missing` with `incomplete_count: 0`).
- Phase 06.2 post-execution gates RUN (2026-08-24) — **code review + orchestrator-verified live-stack reproduction + verification all found real, confirmed gaps; phase NOT complete.**
  - **Code review** (`06.2-REVIEW.md`, `30e6795`; scope pinned via `--files=` to the 48-file `94993fd..HEAD` product delta, computed directly from `git diff --name-only` rather than the buggy `printf "%02d"` phase-padding execute-phase.md's own advisory check uses for decimal phases — see [[decisions-tag-parser-bug-lancet]]-class quirk, `init.code-review`'s own `padded_phase` resolves the decimal correctly and was used instead): `status: issues_found` — 4 critical, 6 warning, 1 info. CR-01: `deploy/grafana/dashboard_gen/dashboard_gen.exe`, a 3.3MB committed Windows binary, unreferenced by any script. CR-02: Collector Prometheus exporter `namespace: lancet` double-prefixes already-`lancet.`-prefixed instrument names. CR-03: `gen_ai.request.model` span attributes hardcoded to literals that match no configured default (`engine/src/service.rs:431`, `engine/src/workflow/nodes/generate.rs:122,178`), unlike the correct sibling `ingest.rs:1143` (`embedder.model_id()`). CR-04: gateway `telemetry.go` forces `WithInsecure()` unconditionally even for validated `https://` endpoints.
  - **CR-02 independently reproduced live by the orchestrator, not taken on the reviewer's word.** The local `observability` compose profile was already running (collector/grafana/jaeger/prometheus/loki, started outside this session). Pushed a synthetic OTLP metric `lancet.test.probe` directly to the collector's OTLP HTTP receiver (127.0.0.1:4318) and read back `lancet_lancet_test_probe_total` from the Prometheus exporter (127.0.0.1:8889/metrics) — confirmed double-prefixing empirically. Cross-checked all 10 `lancet-rag-operations.json` panel queries via `grep -o '"expr"...'`: all use the single-prefixed form, so all 10 panels will render "No data" against the live stack. This directly contradicts `06.2-03-SUMMARY.md`'s "Observed Prometheus Metric Transformation Rule," which claims this exact transformation was checked against a live scrape per the plan's own `flagged_assumptions` anti-prediction requirement — it wasn't, or the config changed after. Collector container restarted afterward to clear the injected probe series; live stack left in its original (idle) state.
  - **Regression gate PASSED** (orchestrator-run directly, not executor self-report): `cargo test --manifest-path engine/Cargo.toml --locked` exit 0 — 474 total (433 lib passed + 1 ignored + 18 `inspect_lancedb` + 22 `config_startup`), 0 failed. `cd gateway && go test ./...` exit 0, all packages ok. `sh scripts/engine-test-targets.sh` and `sh scripts/gateway-test-targets.sh` — all invariants independently verified (474 Rust / 107 Go).
  - **Verification** (`06.2-VERIFICATION.md`, `b462968`): `status: gaps_found`, **4/8 roadmap success criteria verified** (SC2, SC3, SC4, SC8 — span surface, ingestion tracing, metrics instrument set, workflow-metadata derivation all directly test-confirmed live by the verifier: `query_span_hierarchy_emits_exactly_five_node_spans`, `TestRootSpanStatusSetOnEveryExitPath` 5/5, `ingest_span_hierarchy_covers_document_stages`). 4 gaps, all still unresolved as of verification (re-confirmed against current source, no fix landed since code review): SC5/SC6 gap 1 = the CR-02 double-prefix defect (both roadmap criteria fail on the same root cause: Collector fan-out produces series no consumer can query, so "correlated in Grafana by trace_id" and "dashboards generated from typed code" both fail as-shipped even though the generator/provisioning machinery itself is correct and committed). SC6 gap 2 = the committed `dashboard_gen.exe` (CR-01, contradicts "generated from typed code"). Two carryover code-review blockers held at `failed` rather than folded into SC rows: the CR-03 hardcoded `gen_ai.request.model` literals, and the CR-04 gateway TLS-not-honored bug. 2 items `behavior_unverified` (SC1 cross-process trace continuity, SC7's runtime degrade-to-stdout half) — both are the phase's own designed-in `human_verify_mode: end-of-phase` items, not new gaps.
  - **4 human-verification items persisted** (`06.2-VALIDATION.md`'s "Manual-Only Verifications" table, all four explicitly marked BLOCKING at plan time, none performed by any executor — confirmed via grep across all 6 SUMMARY.md files, consistent with `human_verify_mode: end-of-phase` by design, not an execution gap): (a) Grafana trace↔log↔metric click-through — expected to fail on the Prometheus-series half until CR-02 is fixed; (b) operations dashboard renders against real data — expected to fail outright until CR-02 is fixed; (c) Windows Docker Desktop bind-mount smoke (RESEARCH A6); (d) Collector degrade-to-stdout on missing backend.
  - **`close_parent_artifacts` deliberately skipped, not silently omitted.** Phase 06.2 is a decimal phase, so the #2868 gate-resume path's gap-closure-artifacts.md step looked for a parent UAT and found `06-UAT.md` — but both its gaps (G-06-1, G-06-2) were already resolved weeks earlier by Phase 6's own gap-closure plan 06-16 (2026-08-22), with no causal link to 06.2's work. Running the step's frontmatter-flip (`status: diagnosed` → `resolved`) would have misattributed that closure to 06.2's commit history and overridden a prior session's documented, deliberate choice to leave it `diagnosed`. The two referenced debug session files (`d18-total-drop-flag-off.md`, `truncated-citation-resolution.md`) are still un-moved to `.planning/debug/resolved/` — flagged as an unrelated, separately-spawned cleanup task rather than bundled into this round.
  - **`requirements.revert-phase OBS-01` run defensively, confirmed no-op**: OBS-01 was never checked in REQUIREMENTS.md (unlike RAG-03's shared-ID footgun in Phase 6.1, OBS-01 is exclusively Phase 06.2's own requirement — no sharing risk).
  - **Phase 06.2 NOT complete.** `phase.complete` correctly NOT run; REQUIREMENTS.md OBS-01 stays unchecked. Next: `/gsd-plan-phase 6.2 --gaps` to plan the fix (drop the Collector's `namespace: lancet` prometheus-exporter config or the source-side `lancet.` prefix, not both; `git rm` the committed `.exe` and gitignore the directory; thread the configured model into the two hardcoded `gen_ai.request.model` span sites; branch gateway telemetry TLS setup on the parsed OTLP endpoint scheme), then `/gsd-execute-phase 6.2 --gaps-only`. Security gate also still open: `workflow.security_enforcement` active, no `06.2-SECURITY.md` exists — `/gsd-secure-phase 6.2` still required before advancing.

## Active Phase

- **Phase:** 06.3 — Evaluation Harness, Corpora and Recorded Run (OBS-02, OBS-04)
- **Status:** Executing Phase 06.3
- **Total Plans in Phase:** 10
- **Completed Plans in Phase:** 8/8 (executed; phase-level gates run 2026-08-29/30, gaps found)
- **Progress:** [██████████] 100% execution / gates: gaps_found (6/9 must-haves)
- **Next:** `/gsd-plan-phase 6.3 --gaps`

## Completed Phases

- **Phase 1: Basic Gateway & Rust Engine Ping** (Completed: 2026-07-13)
- **Phase 2: Ingestion, Chunking & Vector Storage** (Completed: 2026-07-30 via ADR-02-004 debt deferral to Phase 6)
- **Phase 3: Hybrid Retrieval & Basic RAG Path** (Completed: 2026-08-05 via ADR-03-003 debt deferral to Phase 6)
- **Phase 4: Knowledge Graph Extraction & Query** (Completed: 2026-08-06 — lance-graph compatibility spike only; full implementation deferred to Phase 04.1)
- **Phase 5: State Machine & Workflow Events** (Completed: 2026-08-19 — UAT 10/10 passed, 0 issues; `05-SECURITY.md` confirmed `threats_open: 0`)
- **Phase 6: Observability, Evaluation & Polish** (Completed: 2026-08-22 — 16/16 plans; re-verification `passed` 11/11 must-haves after gap-closure plan 06-16 closed UAT gaps G-06-1/G-06-2; RAG-03 satisfied)

## Known Issues & Debt

- Accepted ADR `.discussion/decisions/phases/02/2026-07-30-ADR-02-004-all-the-way-to-ship-mvp.md` force-closed Phase 02 to focus on MVP progress across all must-have functions.
- All remaining Phase 02 findings are deferred as technical debt to the final hardening phase (Phase 6):
  - `DEBT-CR-01 / VER-16`: Completed canonical ingestion downgraded to failed after engine restart
  - `DEBT-CR-02`: Rollback failure destroys replay state
  - `DEBT-CR-03`: Failed admission stranded queued without durable reconciliation intent
  - `DEBT-CR-04 / VER-20`: Evidence helper forges human approval when approval flag omitted
  - `DEBT-WR-01 / VER-19`: Test cleanup deletes another process's fixtures and fails full suite
  - `DEBT-WR-02`: Empty uploads become durable failed jobs and misleading 502 response
  - `DEBT-WR-03`: Cross-runtime recovery tests can hang indefinitely on failure
- Accepted ADR `.discussion/decisions/phases/03/2026-08-05-ADR-03-003-all-the-way-to-ship-mvp.md` force-closed Phase 03 to focus on Phase 04 Knowledge Graph progress.
- All remaining Phase 03 findings are deferred as technical debt to the final hardening phase (Phase 6):
  - `DEBT-P3-BODY-BOUND`: Provider body limit bound is post-chunk materialization
  - `DEBT-P3-STAGING-GEN-RACE`: Staging generation RMW max generation allocation race under equal-gen fail-closed
  - `DEBT-P3-STAGING-PHYSICAL-BU`: Delete-fail physical row retention unproven under fault injection
  - `DEBT-P3-CONFIG-DB-PLAINTEXT`: Committed plaintext DB credentials and sslmode=disable local dev defaults
  - `DEBT-CR-04` (extended): Insecure Gateway->Engine gRPC dial on loopback
  - `DEBT-P3-PROVIDER-ENDPOINT-TRUST`: Provider endpoint URL trust and bearer token sending
  - `DEBT-P3-WARN-DX`: Seeder non-idempotence and empty multipart upload ambiguity
  - `DEBT-P3-WARN-API`: Mixed answer basis without conflict notice, NoEvidenceFits mapped to 400, D1 identity gaps
  - `DEBT-P3-WARN-SETTINGS`: Env ignore, scalar vs carrier dual budget, chunk limit saturation
  - `DEBT-P3-WARN-VALIDATE`: Staging reader null checks, non-finite embedding/BM25 boost overflow
  - `DEBT-P3-MODULE-GRAPH`: Dual lib/bin production module graph
- Pre-existing Phase 02 security/resource debt items (`DEBT-CR-04` loopback guardrail, `DEBT-CR-05` pre-admission bounds, `DEBT-BU-01`, `DEBT-BU-02`) remain active and non-blocking until their triggers or Phase 6.
- Pre-existing RAG and graph query stubs remain recorded in the phase deferred-items ledger for Phase 03 and Phase 04.
- Phase 03 does not claim RAG-03 delivery: DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-04, DEBT-RAG-05, and DEBT-RAG-06 remain the source-of-record future hardening contracts; the initial BM25 build/readiness guard is the only lifecycle safeguard retained in the MVP path.
- Phase 04 only closed the `lance-graph`/`lancedb` compatibility unknown via a feature-gated PoC (`engine/src/graph/`, not wired into the default build). DATA-04 (entity/relationship extraction), DATA-05 (full graph query traversal wired into RAG), and RAG-05 (ContextAssemblyStrategy) remain unimplemented against real data — deferred to Phase 04.1.
- Phase 06's final code review (`06-REVIEW.md`, post-06-16) closed with 0 critical / 3 warning findings, ruled advisory for phase-goal purposes (verification `passed`) but left open as residual debt now that the phase is closed and the review artifact goes cold:
  - `DEBT-P6-WR-02`: the only service-boundary (`execute_query_rag`) test for total-citation-drop was flipped from flag-off/reject to flag-on/succeed rather than gaining a flag-off sibling (`engine/src/tests.rs`), so G-06-1's fail-closed contract — a UAT blocker — is untested at the client-facing boundary; the test's name (`..._rejects_unknown_marker_without_response`) also contradicts its body.
  - `DEBT-P6-WR-01`: stale comment in `generate.rs:239-241` still claims total-drop "never fails the run," inaccurate since `allow_model_only = false` now fails closed.
  - `DEBT-P6-WR-03`: the G-06-2 end-to-end test only asserts the downstream consequence (citation dropped), not that packing (vs. retrieval) caused it — a future retrieval-side change could silently turn it into a non-discriminating no-op test while staying green.
- Phase 06.1's code review + verification (2026-08-23, `06.1-REVIEW.md`/`06.1-VERIFICATION.md`) found real gaps, not yet closed — tracked as open blockers, not debt, since `phase.complete` did not run:
  - `GAP-06.1-SC2-SC3`: `ProductionDenseRetrievalPort::retrieve_dense` (`engine/src/service.rs:502-538`) and `rebuild_and_swap` (`engine/src/ingest.rs:1454-1459`) both checkout on `.clone()`s of the one shared `lancedb::Table` built in `main.rs:30`; `Table::clone()` shares a single `Arc<Mutex<DatasetState>>` `pinned_version` cell, so concurrent checkouts race and a query's dense candidates can silently come from a different LanceDB generation than its own recorded `index_generation` and than the BM25 candidates fused alongside them. Fix direction: give both call sites a `DatabaseManager` handle and open an independent `Table` per call via `database.nodes_table()` instead of cloning the shared one.
  - `GAP-06.1-SC4`: `engine/src/ingest.rs:1455` — `let _ = nodes_latest.checkout_latest().await;` discards the error, so a genuine checkout failure reports `rebuild_degraded: false` instead of taking the already-correctly-implemented degraded-snapshot / `IndexRebuildFailed`-notice branch two lines below.
  - Neither gap is caught by the existing test suite (404 Rust + gateway + 26 Python all pass green regardless) — `rebuild_swap_generation_atomicity` and `test_checkout_clone_isolated_from_live_writes` don't exercise the shared-clone race; a new regression test is part of the required fix (06.1-REVIEW.md WR-01).
- Phase 06.2's code review + verification (2026-08-24, `06.2-REVIEW.md`/`06.2-VERIFICATION.md`) found real gaps, not yet closed — tracked as open blockers, not debt, since `phase.complete` did not run:
  - `GAP-06.2-SC5-SC6`: `deploy/collector/otel-collector-config.yaml:27-29` sets `namespace: lancet` on the Collector's Prometheus exporter, but every instrument name is already `lancet.`-prefixed at the source (`engine/src/telemetry/metrics.rs`), so exported series double-prefix (`lancet_lancet_rag_query_duration_ms_count`). Orchestrator-reproduced live via synthetic OTLP push, not just code-read. All 10 dashboard panels in `lancet-rag-operations.json` reference the single-prefixed form and will render "No data" against the live stack. Fix: drop `namespace: lancet` OR the source-side `lancet.` prefix, not both, then re-verify against a live scrape and correct `06.2-03-SUMMARY.md`'s wrong "Observed Prometheus Metric Transformation Rule".
  - `GAP-06.2-SC6-EXE`: `deploy/grafana/dashboard_gen/dashboard_gen.exe`, a 3.3MB committed Windows binary, unreferenced by any script, contradicts "dashboards generated from typed code." Fix: `git rm` and gitignore the directory's `*.exe`.
  - `GAP-06.2-CR-03`: `gen_ai.request.model` span attributes hardcoded to literals matching no configured default at `engine/src/service.rs:431` and `engine/src/workflow/nodes/generate.rs:122,178`, unlike the correct sibling `ingest.rs:1143` (`embedder.model_id()`).
  - `GAP-06.2-CR-04`: gateway `telemetry.go:123,153,173` forces `WithInsecure()` unconditionally even for validated `https://` OTLP endpoints, silently defeating configured TLS.
  - 4 human-verification items pending per `06.2-VALIDATION.md`'s Manual-Only table (Grafana trace↔log↔metric click-through, dashboard-renders-with-real-data, Windows Docker Desktop bind-mount smoke, Collector degrade-to-stdout) — expected by design under `human_verify_mode: end-of-phase`, not gaps in execution, but the first two are expected to fail until `GAP-06.2-SC5-SC6` is fixed.
- Phase 06.2's final code review warnings and technical debt items from `06.2-REVIEW.md` are tracked as residual debt:
  - `DEBT-P6.2-WR-01`: `streamEndedNormally` unreachable in `gateway/main.go` `queryRAG`.
  - `DEBT-P6.2-WR-02`: retrieval `path_failures` kind classified via error-message substring in `retrieve.rs`.
  - `DEBT-P6.2-WR-03`: `REBUILD_TEST_MUTEX` not held by `rebuild_failure_degrades_not_fails` and `rebuild_checkout_latest_failure_degrades_not_fails`.
  - `DEBT-P6.2-WR-04`: Grafana `GF_SECURITY_ADMIN_USER`/`PASSWORD` committed `admin`/`admin`.
  - `DEBT-P6.2-WR-05`: `otelhttp` span names use raw URL path.
  - `DEBT-P6.2-WR-06`: engine `telemetry_handle.shutdown` skipped on startup `?` paths.
  - `DEBT-P6.2-IN-01`: per-call meter instrument construction in `engine/src/telemetry/metrics.rs`.
- **Doc/implementation mismatch found while scoping 06.1's code review:** `.claude/commands/gsd-code-review.md` and `.claude/gsd-local-patches/commands/gsd-code-review.md` document `--files file1,file2,...` (space-separated), but `code-review-flags.cjs`'s parser only recognizes `--files=file1,file2,...` (`=`-joined) — a space-separated invocation is silently treated as an unrecognized flag and falls through to SUMMARY/git-diff scoping with no warning. Worth a doc fix; did not block this session since the `=` form was used after checking the parser source directly.
- Phase 06.3's code review + verification (2026-08-29/30, `06.3-REVIEW.md`/`06.3-VERIFICATION.md`) found real gaps, not yet closed — tracked as open blockers, not debt, since `phase.complete` did not run:
  - `GAP-06.3-SC8`: the phase's headline deliverable — a real, committed evaluation run under `eval/runs/<date>-<corpus>/` (`report.md`, `report.json`, `metadata.json`, journal, judge cache) — was never produced. `eval/runs/` is fully gitignored and has zero git history; the only artifact is an untracked, broken 3-question `eval/runs/smoke_test/` (`commit_sha: "local"`, most dimensions skipped/errored). `06.3-07-SUMMARY.md` marks the "Perform and Commit Recorded Run" task `completed` with no narrative evidence it happened. Fix: actually run `lancet-eval run --corpus multihop_rag` to completion against a fully-seeded store, score it, and commit the resulting run-record directory per `06.3-07-PLAN.md`'s documented 6-step procedure.
  - `GAP-06.3-SC6`: `eval/corpora/multihop_rag/document_map.json` has only 2 entries (matching a single Probe B test upload) against the 346-line committed document subset — the corpus was never actually seeded at scale, so any real run today would hit the same "no evidence" failures visible in the smoke test. Fix: run `lancet-eval seed --corpus multihop_rag` to completion.
  - `GAP-06.3-CR-01`: `eval/src/lancet_eval/seed.py:271-303`'s `reseed_corpus()` never touches the PostgreSQL `lancet_eval` schema despite README/CLI-help/docstring all promising a full drop-and-recreate reset — repeated reseeds accumulate orphaned Postgres rows. Fix: either implement the documented Postgres reset or correct the documentation to describe LanceDB-only reset.
  - 3 of 8 `06.3-VALIDATION.md` manual-check rows show no live-stack evidence despite `status: complete` on their owning tasks: `06.3-01-03` (probe end-to-end against a live gateway), `06.3-04-03` (preflight pass/fail against a live-then-stopped stack), `06.3-06-03` (judge calibration against 20 hand-scored rows) — code exists and is unit-tested in all three; only whether the manual step was actually performed is open.
  - `GAP-06.3-CR-02` (lower severity): `EvalSettings.question_deadline_secs` wired into `probe` but not into `run`'s actual driver — silent no-op for the primary benchmark command.
  - Orphaned test fixture `eval/tests/fixtures/journal_fixture.jsonl` (WR-01) — committed, zero consumers anywhere in the test suite.

## Deployment & Environments

- Local PostgreSQL connectivity and Atlas schema application verified for plan 02-01.

## Quick Tasks Completed

| Slug | Date | Description | Status |
|------|------|-------------|--------|
| update-readme-blueprint | 2026-06-19 | Update README.md with GSD planning documents and backlog details | Complete |
| check-backlog-ports | 2026-06-19 | Verify and add missing Port annotations for Phase 999.1, 999.2, and 999.3 in REQUIREMENTS.md and ROADMAP.md | Complete |
| setup-gitignore | 2026-07-12 | Check and make/update a proper git.ignore based on the designed stack | Complete |
| check-dep-updates | 2026-07-14 | Check if dependencies of this project is able to update and keep working, like rust cargo and jaeger image | Complete |
| buf-rust-codegen | 2026-07-14 | Migrate Rust protobuf code generation to Buf v2 with prost and tonic plugins | Complete |
| update-readme-with-all-the-decision-and- | 2026-08-19 | Update README with all decisions and progress to date, preserving personal-side-project/showcase framing and adding AI-collaboration angle | Complete |
| review-06-01-summary-accuracy | 2026-08-20 | Review commit 35b5854 (plan 06-01) for behavior regressions and plan sufficiency; update 06-01-SUMMARY.md frontmatter with 5 out-of-scope lint-edited files, record cargo fmt --check as pre-existing failing gate, annotate RAG-03 as structural-only | Complete |
| review-06-04-refactor-fidelity | 2026-08-20 | Review commit c7e107ec (plan 06-04) as behavior-preserving refactor; confirmed checkpoint dispatch preserved and DTO/event contract byte-identical; found and FIXED in bfec94b: truncated config fail-closed error string (REG-06-04-01, root cause = Task 2 criterion contradicting its own action text), source-grep test gate rewritten on `go test -list` with per-package named failures (closes T-06-04-05), 8 package-local sse wire-contract tests added (total 67 -> 75), plus export-decision table added to 06-04-SUMMARY per the plan output block. Two criteria await sign-off: invariant 67->75 and Task 2 "exactly once". | Complete |
| ignore-gsd-runtime-dir | 2026-08-21 | Ignore .gsd runtime directory in .gitignore | Complete |
| 260824-ipd | 2026-08-24 | Fix the shared Phase 6 CONTEXT tag-extractor landmine. Do not add any per-phase CONTEXT.md. | Verified |
| commit-cross-ai-review | 2026-08-27 | Commit cross-AI review for plans 10-12 in 06.2-REVIEWS.md | Complete |

## Performance Metrics

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 02 P01 | 1h 16m | 2 tasks | 21 files |
| Phase 02 P02 | 57m | 2 tasks | 5 files |
| Phase 02 P03 | 1h 25m | 2 tasks | 9 files |
| Phase 02 P04 | 25 min | 2 tasks | 10 files |
| Phase 02 P05 | 35 min | 3 tasks | 9 files |
| Phase 02 P06 | 2h 24m | 3 tasks | 4 files |
| Phase 02 P07 | 58 min | 3 tasks | 9 files |
| Phase 02 P08 | 35 min | 2 tasks | 4 files |
| Phase 02 P09 | 45 min | 2 tasks | 5 files |
| Phase 02 P10 | 24 min | 3 tasks | 0 files |
| Phase 03 P01 | 25min | 2 tasks | 10 files |
| Phase 03 P05 | 30min | 2 tasks | 4 files |
| Phase 03 P10 | 18 min | 2 tasks | 4 files |
| Phase 03 P11 | 35min | 3 tasks | 5 files |
| Phase 03 P12 | 13m | 2 tasks | 5 files |
| Phase 04 P01 | 45min | 3 tasks | 8 files |
| Phase 04.1 P01 | 20min | 2 tasks | 9 files |
| Phase 04.1 P02 | 40min | 3 tasks | 10 files |
| Phase 04.1 P03 | 45min | 3 tasks | 5 files |
| Phase 04.1 P04 | 50min | 2 tasks | 5 files |
| Phase 05 P10 | 112m | 2 tasks | 4 files |
| Phase 05 P21 | 7 min | 2 tasks | 2 files |

## Decisions

- [Phase 02-01]: Reserve bounded Tokio queue capacity before LanceDB persistence so rejected uploads cannot create orphaned raw documents. — Queue exhaustion must reject before consuming durable local storage.
- [Phase 02-01]: Use a shared base TOML plus LANCET_ENV overlays in both runtimes. — Go and Rust need one environment-selection contract.
- [Phase 02-01]: Keep live ingestion state in Arc DashMap while PostgreSQL remains the gateway metadata source. — This is the thinnest viable scaffold for polling before later persistence work.
- [Phase 02-02]: Force JSON uploads through fixed-size chunking. — JSON strings may contain Markdown-like tokens but must remain raw text.
- [Phase 02-02]: Cache o200k_base in OnceLock and estimate tokens before persistence. — Downstream embedding and vector-storage work receives stable per-chunk token counts.
- [Phase 02-03]: Use ~major.minor Cargo requirements for two-component declarations with patch-only updates. — Matches the requested manifest format without permitting automatic minor-version drift.
- [Phase 02-03]: Keep direct Arrow crates on the 58.3 patch line. — LanceDB 0.31 exposes Arrow 58 types; Arrow 59 would create incompatible public types.
- [Phase 02-03]: Fail startup on any LanceDB schema field drift. — Indexing must not proceed against incompatible persisted storage.
- [Phase 02-04]: Keep durable raw-content staging after queue reservation, then let the single worker replace document graph rows. — Preserves queue rejection semantics while making re-ingestion repairable.
- [Phase 02-04]: Persist only completed or failed engine states in PostgreSQL. — Queued and processing remain live engine states until terminal reconciliation.
- [Phase 02-04]: Generate and validate RFC 4122 UUIDv4 document IDs at both runtime boundaries. — Prevents predicate/path injection and keeps gateway/engine IDs compatible.
- [Phase 02-05]: Keep raw admission data in staged_documents until a complete canonical replacement succeeds.
- [Phase 02-05]: Recover a lost conditional terminal update only by re-reading and verifying the winner.
- [Phase 02-06]: Run the final live gate against a dedicated verification LanceDB store so pre-existing schema generations cannot influence acceptance.
- [Phase 02-06]: Preserve only the fresh validated run as canonical verification data and remove stale Phase 02 rows, stores, challenges, and evidence.
- [Phase 02-07]: Capture canonical LanceDB versions before mutation and route every post-snapshot error, including staging cleanup, through one rollback funnel.
- [Phase 02-07]: Use a five-second context.Background compensation timeout so request cancellation cannot strand failed-ingest metadata.
- [Phase 02-07]: Keep all Rust fault fixtures and integrity tests in engine/src/tests.rs, leaving production code with only the standard test-module declaration.
- [Phase 02-08]: Keep REQUEST_TIMEOUT as the single ten-second reqwest builder contract; the test seam may vary endpoint and retries but never the production timeout.
- [Phase 02-08]: Derive inspector identity and integrity verdicts only from filtered durable LanceDB rows, rejecting missing, mixed, duplicate, stale, or non-contiguous state before JSON output.
- [Phase 02-08]: Keep real LanceDB inspector fixtures outside engine/src/bin so Cargo does not discover test-only code as a production binary target.
- [Phase 02]: Run every challenge, evidence, freshness, privacy, and durable-store decision through explicit Python checks under isolated mode.
- [Phase 02]: Copy provider/model/generation/duplicate/stale/continuity facts directly from the Plan 02-08 inspector output; do not attest hardcoded verdicts.
- [Phase 02]: Keep challenge and evidence paths as exact ignored files and remove both only after final current-store reconciliation succeeds.
- [Phase 02]: Keep all fixtures and negative tests in scripts/test_phase02_live_evidence.py; production shell files contain no test-only harness.
- [Phase 02-10]: Final acceptance required the validator exit zero and direct current PostgreSQL/LanceDB comparison before cleanup.
- [Phase 02-10]: Git Bash was used for the unchanged validator because the WSL launcher had incompatible Cargo path semantics.
- [Phase 02-10]: Challenge and evidence artifacts remain exact-ignored and absent after success.
- [Phase 03]: Use NFKC, full Unicode case folding, UAX word boundaries, and identifier subtokens without stemming or stop-word removal.
- [Phase 03]: Compute BM25 document frequency over the complete snapshot while applying normalized metadata filters before candidate limits.
- [Phase 03]: Keep full-precision weighted RRF scores, retain both source ranks and scores, and resolve ties by the D-51 identity key.
- [Phase 03]: Expose reranking through a Send + Sync boxed-future trait with NoOpReranker as the Phase 03 pass-through implementation.
- [Phase 04.1-01]: Restructure entity tables to `entities` (entity_id primary key) and `entity_edges` (document_id indexed), migrating all code and test fixtures to the new schema.
- [Phase 04.1-02]: Wire extract_and_persist_entities into the worker loop, prove end-to-end extraction and graph-fact prompt packing, and reserve 1 evidence chunk for citations.
- [Phase 04.1-03]: Concurrently extract per-chunk entities using buffer_unordered(5) while collecting non-fatal extraction errors without failing document ingestion.
- [Phase 04.1-03]: Decode all batches in IPC streams via DecodeAllBatches in bridge.rs to prevent multi-batch stream truncation across Arrow crate boundaries (WR-01).
- [Phase 04.1-03]: Enforce 2 retries (3 total attempts) with confidence range validation [0.0, 1.0] and log coverage regressions on re-ingestion.
- [Phase 04.1-04]: Fixed a pre-existing fetch_neighborhood bug where bidirectional multi-hop BFS double-counted an edge re-matched from a later hop's frontier; deduplicated by (source, target, relation_type, weight) identity.
- [Phase 04.1-04]: QueryGraph seed_entity_name lookup case-folds via .trim().to_lowercase() (this codebase's D-05 write-time merge convention) over a full table scan, returning Status::not_found on zero matches.
- [Phase 05-17]: Protobuf schema introduces additive RetrievalSnapshot variant fields (tags 10/11) and WorkflowCompletedEvent notices (tag 6) with clean: false Buf protection for hand-written Rust module glue; compile repair is owned by 05-23.
- [Phase 05-23]: Repaired exhaustive Rust message literals across engine/src (retrieve.rs, events.rs, main.rs) with explicit additive field initialization and proved the RetrievalSnapshot wire contract and tag ordering (tags 1..=11) in retrieval::tests.
- [Phase ?]: CheckpointSnapshot in events.rs is the canonical Rust-owned nineteen-field stable JSON contract.
- [Phase ?]: query_embedding is represented by dimension plus a deterministic fixed-size hexadecimal digest, not the raw vector.
- [Phase ?]: WorkflowCompleted carries the accumulated ordered notices so degradation remains visible through terminal failure.

## Session

**Last session:** 2026-08-24T20:40:00.000Z
**Last activity:** 2026-08-30
**Stopped at:** Phase 06.2 complete, ready to plan Phase 06.3
**Resume file:** None

## Accumulated Context

### Roadmap Evolution

- Phase 04.1 inserted after Phase 4: Knowledge Graph Extraction & Query (Full Implementation) (URGENT)
- Phase 6.1 inserted after Phase 6: Phase 6 split into 6, 6.1-6.4 per 06-CONTEXT.md D-77 (scope too large for one phase)
- Phase 6.2 inserted after Phase 6: OTel traces/metrics/logs (OBS-01), split from Phase 6 per 06-CONTEXT.md D-77
- Phase 6.3 inserted after Phase 6: Evaluation harness (OBS-02, OBS-04), split from Phase 6 per 06-CONTEXT.md D-77
- Phase 6.4 inserted after Phase 6: Docs suite + v1 closure (OBS-03), split from Phase 6 per 06-CONTEXT.md D-77
