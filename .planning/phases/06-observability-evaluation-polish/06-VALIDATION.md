---
phase: 6
slug: observability-evaluation-polish
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-20
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded by `/gsd-plan-phase 6` from `06-RESEARCH.md` § Validation Architecture.
> The per-task map below is populated by `/gsd-validate-phase` once PLAN.md task IDs exist.

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

**Measured baseline — the invariant every plan must preserve** (per-target counts, measured during research):

| Target | Cases |
|--------|-------|
| `unittests src/lib.rs` (library) | 133 |
| `unittests src/main.rs` (bin `engine`) | 128 |
| `unittests src/bin/inspect_lancedb.rs` | 18 |
| `unittests src/bin/seed_rag_fixture.rs` | 0 |
| `tests/config_startup.rs` (integration) | 9 |
| **Rust total** | **288** |
| Go `func Test…` in `gateway` | 67 |

> D-80's "285-test suite" is an attribute grep, not what the runner enumerates. The D-80/D-82
> restructure plans **redistribute** cases across targets; the totals (288 Rust / 67 Go) must not move.

---

## Sampling Rate

- **After every task commit:** the single most relevant target — `cargo test --manifest-path engine/Cargo.toml --lib` for engine work, `cd gateway && go test ./...` for gateway work.
- **After every plan wave:** the full configured gate — `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)`
- **After every D-80/D-82 restructure step:** additionally re-run per-target enumeration and diff the five counts against the 133/128/18/0/9 baseline.
- **After every D-74 wire-contract commit:** additionally `buf lint`, `buf format --diff --exit-code`, and `git status --porcelain` showing exactly the five expected regenerated paths.
- **Before `/gsd-verify-work`:** full suite green + `cargo clippy -- -D warnings` + `cargo fmt --check` + `go vet ./...`
- **Max feedback latency:** 30 seconds (quick run), full gate at wave boundaries.

> **D-85: there is no CI.** These commands *are* the verification path.

---

## Per-Task Verification Map

*Populated by `/gsd-validate-phase` after PLAN.md task IDs exist. The behavior→test rows below are
lifted from `06-RESEARCH.md` § Validation Architecture and are the source the map must cover.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | RAG-03 / D-80 | — | Per-target test redistribution preserved; totals stay 288 / 67 | invariant | `cargo test --manifest-path engine/Cargo.toml -- --list` | ✅ | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-80 | — | No `pub use` alias re-introduces a second path to a moved item | static | `grep -c "^pub use" engine/src/main.rs` → `0` | ✅ | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-82 | — | Gateway builds and all 67 tests pass after the package split | regression | `cd gateway && go build ./... && go test ./...` | ✅ | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-74 | — | Proto edit regenerates exactly five files, reproducibly | contract | `buf lint && buf format --diff --exit-code && buf generate && git status --porcelain` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-74 | — | `optional bool` round-trips presence (absent ≠ false) over gRPC | unit | `cargo test … --lib -- request_flag_presence` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-74, D-76 | — | Every emitted notice has non-empty `code` derived from `typed_code` via `as_str_name()` | unit | `cargo test … --lib -- notice_code_derivation` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-74 | T-06-INPUT | Posting `allow_model_only` / `disable_graph_context` to `/rag/query` does not 400 under `DisallowUnknownFields` | integration | `cd gateway && go test ./... -run TestRAGQueryNewRequestFields` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-06 / D-08 | — | `GRAPH_UNAVAILABLE` fires on the empty-result path | unit | `cargo test … --lib -- graph_unavailable_empty_result` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-06 / D-08 | — | `GRAPH_UNAVAILABLE` fires on the absent-`graph_port` path | unit | `cargo test … --lib -- graph_unavailable_no_port` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-06 / D-08 | — | `GRAPH_TIMEOUT`/`GRAPH_DEGRADED` behavior byte-for-byte unchanged | regression | existing tests stay green | ✅ | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-06 / D-08 | — | Source-chunk queries never require graph data | unit | `cargo test … --lib -- source_chunk_query_without_graph` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-01 / D-13 | — | Dense fails → no `NodeFailed`, no failure terminal; `answer_basis == RETRIEVAL`; surviving BM25 evidence; `RETRIEVAL_DEGRADED_DENSE` notice | unit | `cargo test … --lib -- retrieval_degraded_dense` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-01 / D-13 | — | BM25 fails → same, distinct notice; surviving dense evidence returned | unit | `cargo test … --lib -- retrieval_degraded_bm25` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-01 / D-13 | — | BM25 fails on variant k>0 → variants `0..k` still contribute | unit | `cargo test … --lib -- retrieval_degraded_bm25_per_variant` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-01 / D-13 | — | Both paths fail → two distinct degrade notices plus `NO_EVIDENCE`, all surviving de-dup, still no failure terminal | unit | `cargo test … --lib -- retrieval_degraded_both` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-13, D-74 | — | No emitted notice carries an unreachable code — every `NoticeCode` variant has ≥1 emission site | static/unit | `cargo test … --lib -- notice_code_all_reachable` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-47 | — | Engine honors `disable_graph_context`: flag set → no graph facts reach the prompt; flag absent → unchanged | unit | `cargo test … --lib -- disable_graph_context_honored` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-01 / D-10, D-11, D-12 | — | Opt-in on, zero evidence → `MODEL_ONLY` + notice + zero citations | unit | `cargo test … --lib -- model_only_opt_in` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-01 / D-10, D-11 | — | Opt-in off, zero evidence → today's short-circuit, byte-for-byte | regression | existing Phase 05 D-03 tests stay green | ✅ | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-01 / D-11 | — | The bypass applies in both `run_workflow` and `run_tracer` | unit | `cargo test … --lib -- model_only_tracer_path` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-12, D-84 | T-06-CONFIG | Config default `false`; request `Some(true)` overrides; present-but-invalid env → hard error | unit | `cargo test --manifest-path engine/Cargo.toml --test config_startup -- allow_model_only` | ⚠️ target exists | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-03 / D-14 | — | Near-miss marker normalized → `CITATION_REPAIRED`, citation retained | unit | `cargo test … --lib -- citation_repair_normalizes` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-03 / D-14 | — | Unresolvable marker stripped from answer text and from `citations[]`/`structured_citations[]` → `CITATION_DROPPED` | unit | `cargo test … --lib -- citation_repair_drops` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-03 / D-14 | — | Repair makes no second provider call | unit | `cargo test … --lib -- citation_repair_no_second_call` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-03 / D-14, D-18 | — | All citations dropped → basis downgrades transparently (`BASIS_RECONCILED`) | unit | `cargo test … --lib -- basis_downgrade_on_total_drop` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-18 | — | Model self-reports `RETRIEVAL`, engine observes no resolving citations → conservative wins | unit | `cargo test … --lib -- basis_reconciliation_conservative` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-05 / D-15 | T-06-INPUT | Table-driven gRPC matrix: each row → expected `tonic::Code` + `err_kind` string | unit, table-driven | `cargo test … -- bad_input_matrix_grpc` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-05 / D-15 | T-06-INPUT | Table-driven HTTP matrix: each row → 400 + `X-Lancet-Error-Kind` | integration, table-driven | `cd gateway && go test ./... -run TestBadInputMatrixHTTP` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | DEBT-RAG-05 / D-15 | T-06-INPUT | Every rejection happens before retrieval/provider work | unit | `cargo test … -- bad_input_rejects_before_work` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RAG-03 / D-83 | — | Fault modes stay `cfg(test)`; no production fault-injection switch exists | static + guard test | `cargo test … --lib -- fake_generator_cfg_test_gated` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] **Test-fixture constructor for `QueryRagRequest`** (`#[cfg(test)]`, `..Default::default()`-based) plus migration of all 80 exhaustive struct literals — **must land before the D-74 proto edit**, or the contract review D-74 exists to enable cannot happen.
- [ ] **Test-fixture constructor for `Notice`** covering the 19 exhaustive literals, so the typed-code enum can be added additively.
- [ ] **Failure-mode extensions to the Phase 05 `cfg(test)` fake-port seam** (D-83): error, timeout, empty, malformed-citation variants on the dense, BM25, graph, and generator fakes. No production fault-injection switch.
- [ ] **`buf generate` reproducibility check** — a no-op `buf generate` + `git diff --exit-code` as the first task of the D-74 plan (verifies the pinned remote plugins produce the committed bindings before any proto edit).
- [ ] **Go whole-payload assertion for `/rag/query`** — Go has zero whole-payload equality assertions today, so added JSON keys are invisible to all 67 tests.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| D-16 weak-evidence threshold is deliberately **absent** | RAG-03 | A deliberate scope narrowing, not a behavior — nothing to assert | Recorded in the plan; reviewer confirms no threshold logic was added |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] Per-target baseline (133/128/18/0/9 = 288 Rust, 67 Go) re-verified after every restructure step
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
