---
phase: 6
slug: observability-evaluation-polish
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-20
updated: 2026-08-23
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded by `/gsd-plan-phase 6` from `06-RESEARCH.md` § Validation Architecture.
> Re-audited 2026-08-23: Gemini commit `0bb1257` stamped compliance but swapped the
> RESEARCH behavior→test map for truncated plan-task greps and left Go counts stale.
> This revision restores the behavior map to live filter names and re-verified counts.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (Rust)** | Built-in `cargo test` + `#[tokio::test]` (tokio `~1.53`, `test-util` feature for the paused clock) |
| **Framework (Go)** | Built-in `go test` + `net/http/httptest` |
| **Config file** | none — cargo and go conventions only; targets declared by `engine/Cargo.toml` + `#[path]`/`mod` declarations |
| **Quick run command (Rust)** | `cargo test --manifest-path engine/Cargo.toml --lib` |
| **Quick run command (Go)** | `cd gateway && go test ./...` |
| **Full suite command** | `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)` |
| **Build command** | `cargo build --manifest-path engine/Cargo.toml && (cd gateway && go build ./...)` |
| **Supplementary gates** | `cargo clippy --manifest-path engine/Cargo.toml -- -D warnings`, `cargo fmt --check`, `go vet ./...`, `buf lint`, `buf format --diff --exit-code` |
| **Estimated runtime** | ~30s incremental per target; full gate under a few minutes |

**Measured baseline and verified post-restructure distribution** (per-target counts):

| Target | Baseline Cases | Post-Phase Cases | Status |
|--------|----------------|------------------|--------|
| `unittests src/lib.rs` (library) | 133 | 351 (350 passed, 1 ignored) | ✅ Verified 2026-08-23 |
| `unittests src/main.rs` (bin `engine`) | 128 | 0 (all modules library-homed) | ✅ Verified 2026-08-23 |
| `unittests src/bin/inspect_lancedb.rs` | 18 | 18 | ✅ Verified 2026-08-23 |
| `unittests src/bin/seed_rag_fixture.rs` | 0 | 0 | ✅ Verified 2026-08-23 |
| `tests/config_startup.rs` (integration) | 9 | 17 | ✅ Verified 2026-08-23 |
| **Rust total** | **288** | **386** | ✅ Verified 2026-08-23 |
| Go `go test ./... -list .` (`^Test`) | 67 | **80** | ✅ Verified 2026-08-23 |

> D-80/D-82 redistribute cases; totals grow when Wave 0+ behavior tests land. Re-enumerate via
> `scripts/engine-test-targets.sh` / `scripts/gateway-test-targets.sh` after restructure steps.
> Do **not** treat the pre-phase 67 Go figure as an invariant after plans 06-06..06-12.

---

## Sampling Rate

- **After every task commit:** the single most relevant target — `cargo test --manifest-path engine/Cargo.toml --lib` for engine work, `cd gateway && go test ./...` for gateway work.
- **After every plan wave:** the full configured gate — `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)`
- **After every D-80/D-82 restructure step:** additionally re-run per-target enumeration via `scripts/engine-test-targets.sh` / `scripts/gateway-test-targets.sh`.
- **After every D-74 wire-contract commit:** additionally `buf lint`, `buf format --diff --exit-code`, and `git status --porcelain` showing exactly the five expected regenerated paths.
- **Before `/gsd-verify-work`:** full suite green + `cargo clippy -- -D warnings` + `cargo fmt --check` + `go vet ./...`
- **Max feedback latency:** 30 seconds (quick run), full gate at wave boundaries.

> **D-85: there is no CI.** These commands *are* the verification path.

---

## Per-Requirement Verification Map

Behavior rows from `06-RESEARCH.md` § Validation Architecture, mapped to **live** test filters
(RESEARCH placeholder names → actual names). Plan task IDs note ownership; plan `<automated>`
blocks remain in each `06-XX-PLAN.md` and are not duplicated here when they are presence greps.

| Req | Plan | Behavior | Test Type | Automated Command | File | Status |
|-----|------|----------|-----------|-------------------|------|--------|
| D-80 | 01–03 | Per-target redistribution; lib absorbs former bin cases | invariant | `cargo test --manifest-path engine/Cargo.toml --lib -- --list` → 351; `--bin engine -- --list` → 0 | `scripts/engine-test-targets.sh` | ✅ green |
| D-80 | 01–03 | No `pub use` re-exports a second path from `main.rs` | static | `rg -c "^pub use" engine/src/main.rs` → 0 (or empty) | `engine/src/main.rs` | ✅ green |
| D-82 | 04–05 | Gateway builds; full Go suite green after package split | regression | `cd gateway && go build ./... && go test ./...` | `gateway/` | ✅ green |
| D-74 | 07 | Proto regen is reproducible (five binding paths) | contract | `buf lint && buf format --diff --exit-code && buf generate && git status --porcelain` | `proto/` + generated trees | ✅ green |
| D-74 | 07 | Request edge flags parse under `DisallowUnknownFields` (absent ≠ unknown) | integration | `cd gateway && go test ./... -run TestQueryRAG_EdgeFlagsAndDisallowUnknownFields` | `gateway/main_test.go` | ✅ green |
| D-74/D-76 | 07 | Every published notice yields non-empty `code` via `as_str_name()` | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- test_notice_constructor_all_published_values_yield_non_empty_code_and_match_derivation -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-13/D-74 | 07 | Every `NoticeCode` has an emission site or Phase 6.1 reservation | static/unit | `cargo test --manifest-path engine/Cargo.toml --lib -- test_notice_published_enum_reachability_or_reservation -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-08 | 08 | `GRAPH_UNAVAILABLE` on empty graph result | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- graph_unavailable_notice_on_empty_result -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-08 | 08 | `GRAPH_UNAVAILABLE` on absent `graph_port` | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- graph_unavailable_notice_on_absent_graph_port -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-08 | 08 | `GRAPH_TIMEOUT` / `GRAPH_DEGRADED` unchanged | regression | `cargo test --manifest-path engine/Cargo.toml --lib -- graph_timeout_notice_regression_unchanged graph_degraded_notice_regression_unchanged` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-08 | 08 | Source-chunk queries never require graph data | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- source_chunk_query_succeeds_when_` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-47 | 08 | `disable_graph_context` honored (ablation; no graph facts / port idle) | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- graph_ablation_` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-13 | 09 | Dense fails → degrade, surviving BM25, `RETRIEVAL_DEGRADED_DENSE` | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- retrieval_degraded_dense_` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-13 | 09 | BM25 fails → degrade, surviving dense | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- retrieval_degraded_bm25_` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-13 | 09 | BM25 per-variant tolerance | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- retrieval_degraded_bm25_per_variant_preserves_earlier_succeeded_variants -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-13 | 09 | Both paths fail → two degrade notices + `NO_EVIDENCE` | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- retrieval_degraded_both_paths_fail_produces_three_notices_in_ordered_sequence -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-10/D-11/D-12 | 10 | Opt-in on, zero evidence → `MODEL_ONLY` + notice + zero citations | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- model_only_opt_in_true_zero_evidence_runs_generation_and_emits_notice -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-10/D-11 | 10 | Opt-in off, zero evidence → short-circuit unchanged | regression | `cargo test --manifest-path engine/Cargo.toml --lib -- model_only_opt_in_false_zero_evidence_short_circuits_unchanged -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-11 | 10 | Bypass applies on tracer path | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- model_only_opt_in_true_zero_evidence_tracer_path -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-12/D-84 | 10 | Config default / env override / invalid env fail-closed | unit | `cargo test --manifest-path engine/Cargo.toml --test config_startup -- model_only_answers` | `engine/tests/config_startup.rs` | ✅ green |
| D-14 | 11 | Near-miss marker → `CITATION_REPAIRED` | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- citation_repair_enabled_repairs_near_miss_marker_and_emits_notice -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-14 | 11 | Unresolvable marker → `CITATION_DROPPED` | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- citation_repair_enabled_drops_unresolvable_marker_and_emits_notice -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-14 | 11 | Repair makes no second provider call | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- citation_repair_makes_no_additional_provider_call -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-14/D-18 | 11 | Total drop → basis downgrade (`BASIS_RECONCILED`) | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- citation_repair_total_drop_downgrades_basis_and_succeeds -- --exact` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-18 | 11 | Conservative basis reconciliation when self-report disagrees with evidence | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- basis_reconciliation_` | `engine/src/tests/workflow_phase5.rs` | ✅ green |
| D-15 | 12 | Table-driven gRPC bad-input matrix + no generator work | table-driven | `cargo test --manifest-path engine/Cargo.toml --lib -- bad_input_matrix_rejects_and_dispositions_are_stable -- --exact` | `engine/src/tests/bad_input_matrix.rs` | ✅ green |
| D-15 | 12 | Table-driven HTTP bad-input matrix | table-driven | `cd gateway && go test ./... -run TestBadInputMatrixHTTP` | `gateway/main_test.go` | ✅ green |
| D-83 | 06 | Fault modes stay `cfg(test)`; SSE payload key set pinned | unit / regression | `cargo test --manifest-path engine/Cargo.toml --lib --locked`; `cd gateway && go test ./internal/sse -run TestQueryRAGResponseDTOJSONKeys` | `engine/src/testkit.rs`, `gateway/internal/sse/sse_test.go` | ✅ green |
| SC3/SC5 | 13–15 | Production-shaped model-only + citation repair through real adapter | node-level mock e2e | `cargo test --manifest-path engine/Cargo.toml --lib --locked -- openrouter_node_` | `engine/src/tests/workflow_phase5_production.rs` | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**RESEARCH name → live filter aliases** (for anyone still holding Wave 0 placeholder names):

| RESEARCH placeholder | Live filter / test |
|----------------------|--------------------|
| `notice_code_derivation` | `test_notice_constructor_all_published_values_yield_non_empty_code_and_match_derivation` |
| `notice_code_all_reachable` | `test_notice_published_enum_reachability_or_reservation` |
| `TestRAGQueryNewRequestFields` | `TestQueryRAG_EdgeFlagsAndDisallowUnknownFields` |
| `graph_unavailable_empty_result` | `graph_unavailable_notice_on_empty_result` |
| `graph_unavailable_no_port` | `graph_unavailable_notice_on_absent_graph_port` |
| `source_chunk_query_without_graph` | `source_chunk_query_succeeds_when_*` |
| `disable_graph_context_honored` | `graph_ablation_*` |
| `model_only_opt_in` / `model_only_tracer_path` | `model_only_opt_in_true_zero_evidence_*` |
| `citation_repair_normalizes` / `_drops` / `_no_second_call` | `citation_repair_enabled_repairs_*` / `_drops_*` / `citation_repair_makes_no_additional_provider_call` |
| `basis_downgrade_on_total_drop` | `citation_repair_total_drop_downgrades_basis_and_succeeds` |
| `basis_reconciliation_conservative` | `basis_reconciliation_*` |
| `bad_input_matrix_grpc` / `bad_input_rejects_before_work` | `bad_input_matrix_rejects_and_dispositions_are_stable` (includes `fake_gen.calls() == 0`) |
| `request_flag_presence` | Covered by `TestQueryRAG_EdgeFlagsAndDisallowUnknownFields` + `graph_ablation_absent_flag_defaults_to_graph_enabled` |

---

## Wave 0 Requirements

- [x] **Test-fixture constructor for `QueryRagRequest`** (`#[cfg(test)]`, `..Default::default()`-based) plus migration of all exhaustive struct literals (Plan 06-06).
- [x] **Test-fixture constructor for `Notice`** covering exhaustive literals (Plans 06-06, 06-07).
- [x] **Failure-mode extensions to the Phase 05 `cfg(test)` fake-port seam** (D-83): error, timeout, empty, malformed-citation variants on the dense, BM25, graph, and generator fakes (Plan 06-06).
- [x] **`buf generate` reproducibility check** — `buf generate` + `git diff --exit-code` verified (Plan 06-07).
- [x] **Go whole-payload assertion for `/rag/query`** — SSE payload assertions in `gateway/internal/sse/sse_test.go` (`TestQueryRAGResponseDTOJSONKeys`) (Plans 06-06, 06-07).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| D-16 weak-evidence threshold is deliberately **absent** | RAG-03 | A deliberate scope narrowing, not a behavior — nothing to assert | Recorded in the plan; reviewer confirms no threshold logic was added |
| D-18 total-drop flag-off contract choice | DEBT-RAG-03 / CR-02 | Spec choice recorded in `06-VERIFICATION.md` human_verification — not an SC failure | Confirm intended flag-off semantics, then pin if product wants a regression |
| Truncated packed-evidence citation backstop | T-06-15-03 | `insufficient_spec` / undeclared precondition in verification report | Decide resolve-vs-fail for retrieved-but-truncated blocks, then add a multi-block budget test |
| MODEL_ONLY notice on D-18 total-drop path | DEBT-RAG-03 / CR-01 | Spec-conformant either way; cross-path invariant question | Decide notice vs `BASIS_RECONCILED`-only disclosure |

---

## Validation Sign-Off

- [x] All RESEARCH behaviors have automated verify (or deliberate manual-only)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all former MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] Per-target counts re-verified (386 Rust; 80 Go)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-23 (re-audit of `0bb1257`)

---

## Validation Audit 2026-08-22

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

> Prior Gemini pass (`0bb1257`): marked compliant via plan-task greps; did not remap RESEARCH behaviors or refresh Go counts.

---

## Validation Audit 2026-08-23

| Metric | Count |
|--------|-------|
| Gaps found | 4 (docs: wrong map unit, stale Go=67, truncated commands, filter-name drift) |
| Resolved | 4 (VALIDATION.md rewritten; spot-suite green) |
| Escalated | 0 |
| New test files | 0 (behaviors already covered under live names) |

**Spot-check (all green):** notice derivation/reachability; `graph_unavailable_*` + `graph_ablation_*`; `retrieval_degraded_*`; `model_only_opt_in_*` + `citation_repair_*` + `basis_reconciliation_*`; `bad_input_matrix_rejects_and_dispositions_are_stable`; `config_startup` model-only/citation-repair; `TestQueryRAG_EdgeFlagsAndDisallowUnknownFields` + `TestBadInputMatrixHTTP` + `TestQueryRAGResponseDTOJSONKeys`.
