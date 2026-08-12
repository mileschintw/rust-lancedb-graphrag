---
phase: 05
slug: state-machine-workflow-events
# This is a planning-time validation contract. Execution and /gsd-validate-phase
# must supply results before the lifecycle can become validated.
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-12
---

# Phase 05 — Validation Strategy

> Nyquist validation is enabled for this phase. This artifact is intentionally
> pre-execution: `nyquist_compliant: false`, `wave_0_complete: false`, pending
> task rows, and `Approval: pending` do not claim test results. The executable
> substitute is the phase-specific command map below; the executor runs each
> owning task's commands, and `/gsd-validate-phase 05` records the final evidence.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Rust built-in tests with `#[tokio::test]`, Go `testing`/`httptest`, Buf generation/lint, Atlas/sqlc checks |
| **Config file** | Rust: `engine/Cargo.toml`; Go: `gateway/go.mod`; workflow timeout overlays: `config/config.toml`, `config/config.example.toml`, `config/config.verify.toml` |
| **Quick run command** | Run the exact `<verify><automated>` commands in the owning task row below; Wave 1 uses Rust/codegen-only checks until 05-06 lands the coordinated Go API. |
| **Full suite command** | `cargo test --manifest-path engine/Cargo.toml --locked; $cargoExit = $LASTEXITCODE; if ($cargoExit -ne 0) { exit $cargoExit }; $goOutput = & go -C gateway test ./...; $goExit = $LASTEXITCODE; if ($goExit -ne 0) { exit $goExit }; $bufOutput = & buf lint; $bufExit = $LASTEXITCODE; if ($bufExit -ne 0) { exit $bufExit }` |
| **Estimated runtime** | ~60 seconds locally for the Rust suite, gateway suite, and Buf checks; PostgreSQL-backed tests additionally depend on the local database environment. |

## Sampling Rate

- **After every task commit:** Run every automated command in that task's verification block. Each registration guard lists exact test names and captures the native command exit code before inspecting output.
- **After Wave 1:** Run the Rust-only transition checks and code-generation/order guard; do not claim the pre-migration Go suite as evidence.
- **After Wave 2:** Run the full generated Rust/Go stream and gateway-focused checks.
- **After every later wave:** Run the full suite command above plus the current wave's focused commands.
- **Before `/gsd-verify-work`:** Full suite must be green; database tests may skip only for an absent `TEST_DATABASE_URL` where their plan explicitly permits it.
- **Max feedback latency:** 60 seconds for local checks, excluding an explicitly unavailable PostgreSQL environment.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 05-01 | 1 | ORCH-01, ORCH-02, ORCH-03, ORCH-05 | T-05-01, T-05-02, T-05-03, T-05-SC | Rust-only protobuf generation succeeds, Go generated outputs remain unchanged, stream service output is present, and the tracer compiles. | codegen + Rust compile | `buf generate`; immediate-exit codegen/order guard; `cargo check --manifest-path engine/Cargo.toml --locked`; `cargo test --manifest-path engine/Cargo.toml --locked query_rag_tracer -- --nocapture` | ❌ created by task | ⬜ pending |
| 05-01-02 | 05-01 | 1 | ORCH-01, ORCH-02, ORCH-03, ORCH-05 | T-05-03 | Exact Rust registrations prove validation, event order, cancellation, pending ownership, and concurrent isolation. | Rust integration/regression | `cargo test --manifest-path engine/Cargo.toml --locked query_rag_tracer_happy_path -- --nocapture`; exact `--list` guard for `query_rag_tracer_happy_path`, `workflow_tracer_cancellation`, `checkpoint_envelope_preserves_pending_ownership`, `workflow_tracer_concurrent_same_input` | ❌ created by task | ⬜ pending |
| 05-02-01 | 05-02 | 3 | ORCH-01, ORCH-03, ORCH-05 | T-05-02-01, T-05-02-02, T-05-02-04, T-05-02-05 | Graph-before-retrieve order, graph degradation, bounded finite fusion, retrieval failures, zero-evidence short-circuit, and bridge ownership are wired. | Rust workflow/fusion | `cargo check --manifest-path engine/Cargo.toml --locked`; `cargo test --manifest-path engine/Cargo.toml --locked fusion_ -- --nocapture`; `cargo test --manifest-path engine/Cargo.toml --locked workflow_retrieve_graph -- --nocapture` | ❌ created by task | ⬜ pending |
| 05-02-02 | 05-02 | 3 | ORCH-01, ORCH-03, ORCH-05 | T-05-02-01, T-05-02-02, T-05-02-04 | Exact Rust registrations prove graph timeout, zero evidence, reranker failure, bounded provenance, and one-variant score identity. | Rust edge/fusion | Exact `--list` guard for `graph_timeout_degrades_to_empty_context`, `zero_evidence_short_circuits_generation`, `reranker_failure_maps_to_retrieval_failed`, `cross_variant_provenance_is_bounded`, `variant_zero_one_variant_matches_existing_scores` | ❌ created by task | ⬜ pending |
| 05-03-01 | 05-03 | 4 | ORCH-01, ORCH-02, ORCH-03 | T-05-03-01, T-05-03-02, T-05-03-03, T-05-03-04, T-05-03-05 | Prompt packing has cooperative yield/checkpoint cancellation, generation has separate 65s/30s budgets, and the explicit final nodes preserve one terminal owner. | Rust workflow/generation | `cargo check --manifest-path engine/Cargo.toml --locked`; `cargo test --manifest-path engine/Cargo.toml --locked workflow_generation_tracer -- --nocapture` | ❌ created by task | ⬜ pending |
| 05-03-02 | 05-03 | 4 | ORCH-01, ORCH-02, ORCH-03 | T-05-03-01, T-05-03-03, T-05-03-04 | Exact Rust registrations prove retry identity/ceiling, timeout arithmetic, prompt cancellation, answer cardinality, and no fabrication. | Rust fault matrix | `cargo test --manifest-path engine/Cargo.toml --locked workflow_phase5_generation -- --nocapture`; exact `--list` guard for `generation_retry_request_is_byte_identical`, `generation_outer_timeout_allows_retry`, `generation_cancellation_between_attempts`, `answer_events_have_exact_cardinality`, `prompt_packing_cancellation_is_cooperative` | ❌ created by task | ⬜ pending |
| 05-04-01 | 05-04 | 5 | ORCH-01, ORCH-02, ORCH-03 | T-05-04-01, T-05-04-02, T-05-04-03, T-05-04-04 | The deterministic Rust happy path proves fixed order, lifecycle pairing, five-or-fewer snapshots, trace identity, and task cleanup. | Rust end-to-end | `cargo test --manifest-path engine/Cargo.toml --locked workflow_phase5_happy_path -- --nocapture` | ❌ created by task | ⬜ pending |
| 05-04-02 | 05-04 | 5 | ORCH-01, ORCH-02, ORCH-03 | T-05-04-01, T-05-04-02, T-05-04-03, T-05-04-04 | Exact Rust registrations prove the failure/timeout/cancel/prompt/full-snapshot matrix; the sixth dispatcher envelope remains Go-owned by 05-06. | Rust matrix | `cargo test --manifest-path engine/Cargo.toml --locked workflow_phase5 -- --nocapture`; exact `--list` guard for `workflow_phase5_happy_path`, `workflow_phase5_graph_timeout`, `workflow_phase5_reranker_failure`, `workflow_phase5_prompt_cancel`, `workflow_phase5_full_snapshot` | ❌ created by task | ⬜ pending |
| 05-05-01 | 05-05 | 6 | ORCH-02, ORCH-04 | T-05-05-01, T-05-05-02, T-05-05-03, T-05-05-04, T-05-05-05 | One full checkpoint reaches the Go dispatcher/sqlc/PostgreSQL boundary without SSE snapshot leakage. | Go schema + tracer | `go -C gateway test -run '^TestWorkflowCheckpointSchemaArtifacts$' -count=1`; `go -C gateway test -run '^TestWorkflowCheckpointTracer$' -count=1`; capture each exit immediately | ❌ created by task | ⬜ pending |
| 05-05-02 | 05-05 | 6 | ORCH-02, ORCH-04 | T-05-05-02, T-05-05-03, T-05-05-04, T-05-05-05 | Exact Go registrations and tests prove isolated schemas, fatal query errors, full JSON snapshots, sequence/trace ordering, cancellation atomicity, detached backpressure, and no SSE leakage. | Go integration + registration | Per-name literal-safe `go -C gateway test -list` with `^` + `[regex]::Escape($name)` + `$` and immediate exit capture for `TestWorkflowCheckpointPersistence`, `TestWorkflowCheckpointCancellationAtomicity`, `TestWorkflowCheckpointBackpressureDoesNotStallSSE`, `TestQueryRAGRealInvalidRequestAndDisconnect`, followed by each exact `-run` command | ❌ created by task | ⬜ pending |
| 05-06-01 | 05-06 | 2 | ORCH-02, ORCH-03, ORCH-04 | T-05-06-01, T-05-06-02, T-05-06-03, T-05-06-04, T-05-06-05 | Full Rust/Go codegen lands together; one live prefetched SSE frame has identity before commit, flushes incrementally, and preserves the route timeout boundary. | Buf + Go/Rust integration | `buf generate`; `go -C gateway test -run '^TestRAGQuerySSEFirstFrame$' -count=1`; `cargo check --manifest-path engine/Cargo.toml --locked` | ❌ generated outputs/task files | ⬜ pending |
| 05-06-02 | 05-06 | 2 | ORCH-02, ORCH-03, ORCH-04 | T-05-06-01, T-05-06-02, T-05-06-03, T-05-06-04 | Exact Go registrations include the sixth-envelope dispatcher handoff, migrated cross-runtime test, and SSE route test; each native command failure is surfaced immediately. | Go stream/dispatcher + Rust stream | Per-name literal-safe `go -C gateway test -list` with `^` + `[regex]::Escape($name)` + `$` and immediate exit capture for `TestRAGQuerySSEFirstFrame`, `TestCheckpointDispatcherSixthEnvelopeReturnsPending`, `TestRAGQueryCrossRuntime`, followed by each exact `-run` command and `cargo test --manifest-path engine/Cargo.toml --locked query_rag_stream -- --nocapture` | ❌ created by task | ⬜ pending |

*Status: ⬜ pending until the owning plan executes and independent verification records results.*

## Wave 0 Requirements

- [x] Existing Rust `cargo test`, Go `gateway/go.mod` testing/httptest, Buf, Atlas, and sqlc infrastructure is present; no new package installation or external service capability is required for planning.
- [ ] Task-owned Rust workflow modules and Go streaming/checkpoint tests are not present yet. No separate Wave 0 plan is introduced because the first owning tasks create the test seams and each plan carries an exact registration guard; `wave_0_complete` therefore remains `false` until those tasks execute.
- [x] The package-legitimacy audit for the only planned Cargo additions (`tokio-util`, `tokio-stream`) is present in `05-RESEARCH.md` and both packages are approved.

## Manual-Only Verifications

None identified. The live SSE, cancellation, code-generation, and checkpoint behaviors have runnable automated contracts; visual/manual UI verification is out of scope for this backend phase.

## Validation Sign-Off

- [x] Every planned task has at least one automated verification command or an explicit checkpoint/precondition.
- [x] Sampling continuity is planned: every task has automated commands, and no three consecutive tasks lack a runnable check.
- [x] Wave 0 dependencies are identified with an executable substitute in the owning tasks.
- [x] No watch-mode flags are used.
- [x] Feedback latency target is under 60 seconds for local checks; PostgreSQL availability is handled only by the explicit environment-gated tests in 05-05.
- [ ] `nyquist_compliant: true` — intentionally deferred until execution and `/gsd-validate-phase 05`; setting it now would fabricate sampling evidence.

**Approval:** pending — planning contract populated on 2026-08-12; execution evidence and final Nyquist sign-off remain outstanding.
