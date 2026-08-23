---
phase: 6
slug: observability-evaluation-polish
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-20
updated: 2026-08-22
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded by `/gsd-plan-phase 6` from `06-RESEARCH.md` § Validation Architecture.
> Fully populated and verified by `/gsd-validate-phase 6`.

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

| Target | Baseline Cases | Post-Restructure Cases | Status |
|--------|----------------|------------------------|--------|
| `unittests src/lib.rs` (library) | 133 | 351 (350 passed, 1 ignored) | ✅ Verified |
| `unittests src/main.rs` (bin `engine`) | 128 | 0 (all modules library-homed) | ✅ Verified |
| `unittests src/bin/inspect_lancedb.rs` | 18 | 18 | ✅ Verified |
| `unittests src/bin/seed_rag_fixture.rs` | 0 | 0 | ✅ Verified |
| `tests/config_startup.rs` (integration) | 9 | 17 | ✅ Verified |
| **Rust total** | **288** | **386** | ✅ Verified |
| Go `func Test…` in `gateway` | 67 | 67 | ✅ Verified |

---

## Sampling Rate

- **After every task commit:** the single most relevant target — `cargo test --manifest-path engine/Cargo.toml --lib` for engine work, `cd gateway && go test ./...` for gateway work.
- **After every plan wave:** the full configured gate — `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)`
- **After every D-80/D-82 restructure step:** additionally re-run per-target enumeration via `scripts/engine-test-targets.sh` and verify test redistribution invariants.
- **After every D-74 wire-contract commit:** additionally `buf lint`, `buf format --diff --exit-code`, and `git status --porcelain` showing exactly the five expected regenerated paths.
- **Before `/gsd-verify-work`:** full suite green + `cargo clippy -- -D warnings` + `cargo fmt --check` + `go vet ./...`
- **Max feedback latency:** 30 seconds (quick run), full gate at wave boundaries.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior / Description | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-------------------------------|-----------|-------------------|-------------|--------|
| T-06-01-01 | 01 | 1 | RAG-03 / D-80 | — | Task 1: Establish the per-target test invariant gate and move `chunker` into the library crate | invariant / unit | `cargo build --manifest-path engine/Cargo.toml && grep -q '^pub mod chunk...` | ✅ | ✅ green |
| T-06-01-02 | 01 | 1 | RAG-03 / D-80 | — | Task 2: Move the whole configuration surface into `engine::config` | invariant / unit | `cargo build --manifest-path engine/Cargo.toml && grep -q '^pub mod confi...` | ✅ | ✅ green |
| T-06-02-01 | 02 | 2 | RAG-03 / D-80 | — | Task 1: Move the ingestion pipeline into `engine::ingest` | unit / integration | `cargo build --manifest-path engine/Cargo.toml && grep -q '^pub mod inges...` | ✅ | ✅ green |
| T-06-02-02 | 02 | 2 | RAG-03 / D-80 | — | Task 2: Move `LancetServiceImpl` and the gRPC surface into `engine::service` | unit / integration | `cargo build --manifest-path engine/Cargo.toml && grep -q '^pub mod servi...` | ✅ | ✅ green |
| T-06-03-01 | 03 | 3 | RAG-03 / D-80 | — | Task 1: Rehome `engine/src/tests.rs` from the binary target to the library target | invariant / static | `cargo build --manifest-path engine/Cargo.toml && grep -q '^pub mod tests...` | ✅ | ✅ green |
| T-06-03-02 | 03 | 3 | RAG-03 / D-80 | — | Task 2: Sweep the `main.rs` residue and pin the post-restructure distribution in the gate script | invariant / static | `test "$(grep -c '^\(pub \)\?\(async \)\?fn \\|^\(pub \)\?struct \\|^\(pub ...` | ✅ | ✅ green |
| T-06-04-01 | 04 | 1 | RAG-03 / D-82 | — | Task 1: Establish the per-package Go test invariant gate | package / unit | `sh scripts/gateway-test-targets.sh && sh scripts/gateway-test-targets.sh...` | ✅ | ✅ green |
| T-06-04-02 | 04 | 1 | RAG-03 / D-82 | — | Task 2: Extract `gateway/internal/config` | package / unit | `test -f gateway/internal/config/config.go && grep -q '^package config' g...` | ✅ | ✅ green |
| T-06-04-03 | 04 | 1 | RAG-03 / D-82 | — | Task 3: Extract `gateway/internal/sse` and create the reserved `gateway/internal/telemetry` | package / unit | `grep -q '^package sse' gateway/internal/sse/sse.go && grep -q '^package ...` | ✅ | ✅ green |
| T-06-05-01 | 05 | 2 | RAG-03 / D-82 | — | Task 1: Create `gateway/internal/engineclient` and rewire production code | package / unit | `grep -q '^package engineclient' gateway/internal/engineclient/engineclie...` | ✅ | ✅ green |
| T-06-05-02 | 05 | 2 | RAG-03 / D-82 | — | Task 2: Migrate `gateway/main_test.go` onto the new package and restore the green suite | package / unit | `grep -q 'github.com/lancet/gateway/internal/engineclient' gateway/main_t...` | ✅ | ✅ green |
| T-06-06-01 | 06 | 4 | RAG-03 / D-83 | — | Task 1: Create `engine::testkit` and migrate every exhaustive request and notice literal in the test tree | unit / regression | `grep -q 'pub fn test_query_request' engine/src/testkit.rs && grep -q 'pu...` | ✅ | ✅ green |
| T-06-06-02 | 06 | 4 | RAG-03 / D-83 | — | Task 2: Extend the `cfg(test)` fake-port seam with D-83's four failure modes | unit / regression | `cargo build --manifest-path engine/Cargo.toml --release && test "$(grep ...` | ✅ | ✅ green |
| T-06-06-03 | 06 | 4 | RAG-03 / D-83 | — | Task 3: Assert the exact SSE payload key set on the Go side | unit / regression | `test "$(grep -c '^func Test' gateway/main_test.go)" = "62" && test "$(gr...` | ✅ | ✅ green |
| T-06-07-01 | 07 | 5 | RAG-03 / D-74 | — | Publish the research-corrected vocabulary (recommended) | contract / integration | `cargo test` | ✅ | ✅ green |
| T-06-07-02 | 07 | 5 | RAG-03 / D-74 | — | Task 1: Prove regeneration reproducibility, then land the additive protobuf edit and regenerate both binding trees | contract / integration | `buf lint && buf format --diff --exit-code && buf generate && grep -q 'en...` | ✅ | ✅ green |
| T-06-07-03 | 07 | 5 | RAG-03 / D-74 | — | Task 2: Introduce the single typed notice constructor and derive the string code at every emission site | contract / integration | `cargo build --manifest-path engine/Cargo.toml && test "$(cat engine/src/...` | ✅ | ✅ green |
| T-06-07-04 | 07 | 5 | RAG-03 / D-74 | T-06-INPUT | Task 3: Carry both request flags and the typed notice code across the gateway's HTTP edge | contract / integration | `grep -q 'allow_model_only' gateway/main.go && grep -q 'disable_graph_con...` | ✅ | ✅ green |
| T-06-08-01 | 08 | 6 | DEBT-RAG-06 / D-08 | — | Task 1: End-to-end "answer this query without graph context" — one path only | unit / integration | `cargo build --manifest-path engine/Cargo.toml && grep -q 'disable_graph_...` | ✅ | ✅ green |
| T-06-08-02 | 08 | 6 | DEBT-RAG-06 / D-08 | — | Task 2: Give the two silently-degrading graph paths a machine-readable notice | unit / integration | `cargo build --manifest-path engine/Cargo.toml && test "$(grep -c 'Notice...` | ✅ | ✅ green |
| T-06-08-03 | 08 | 6 | DEBT-RAG-06 / D-08 | — | Task 3: Prove a source-chunk query never requires graph data | unit / integration | `cargo test --manifest-path engine/Cargo.toml --lib && cargo clippy --man...` | ✅ | ✅ green |
| T-06-09-01 | 09 | 7 | DEBT-RAG-01 / D-13 | — | Task 1: Convert the dense retrieval path from fail-closed to degrade | unit / regression | `cargo build --manifest-path engine/Cargo.toml && test "$(grep -c 'return...` | ✅ | ✅ green |
| T-06-09-02 | 09 | 7 | DEBT-RAG-01 / D-13 | — | Task 2: Convert the lexical retrieval path with per-variant tolerance, and pin the both-paths-failed notice shape | unit / regression | `cargo build --manifest-path engine/Cargo.toml && test "$(grep -c 'return...` | ✅ | ✅ green |
| T-06-10-01 | 10 | 8 | DEBT-RAG-01 / D-10, D-11, D-12 | T-06-CONFIG | Task 1: Add the model-only configuration key with fail-closed parsing and resolve it once at admission | unit / integration | `cargo build --manifest-path engine/Cargo.toml && grep -q 'allow_model_on...` | ✅ | ✅ green |
| T-06-10-02 | 10 | 8 | DEBT-RAG-01 / D-10, D-11, D-12 | — | Task 2: Make BOTH grounding guards conditional on the resolved opt-in | unit / integration | `cargo build --manifest-path engine/Cargo.toml && grep -q 'allow_model_on...` | ✅ | ✅ green |
| T-06-10-03 | 10 | 8 | DEBT-RAG-01 / D-10, D-11, D-12 | — | Task 3: Bypass both zero-evidence gates when opted in, and emit the model-only contract | unit / integration | `cargo build --manifest-path engine/Cargo.toml && test "$(grep -c 'allow_...` | ✅ | ✅ green |
| T-06-11-01 | 11 | 9 | DEBT-RAG-03 / D-14, D-18 | — | Task 1: Build the deterministic citation normalization module and its configuration toggle | unit / regression | `cargo build --manifest-path engine/Cargo.toml && head -1 engine/src/gene...` | ✅ | ✅ green |
| T-06-11-02 | 11 | 9 | DEBT-RAG-03 / D-14, D-18 | — | Task 2: Reconcile the answer basis conservatively and state the evidence-over-priors precedence in the prompt | unit / regression | `cargo build --manifest-path engine/Cargo.toml && test "$(grep -cE '\bNot...` | ✅ | ✅ green |
| T-06-11-03 | 11 | 9 | DEBT-RAG-03 / D-14, D-18 | — | Task 3: Replace the fail-closed citation branch with repair, strip and notice | unit / regression | `cargo build --manifest-path engine/Cargo.toml && grep -q 'citations::' e...` | ✅ | ✅ green |
| T-06-12-01 | 12 | 10 | DEBT-RAG-05 / D-15 | T-06-INPUT | Task 1: Enumerate the matrix and drive it as a table-driven gRPC test | table-driven | `head -1 engine/src/tests/bad_input_matrix.rs \| grep -q '^//!' && grep -q...` | ✅ | ✅ green |
| T-06-12-02 | 12 | 10 | DEBT-RAG-05 / D-15 | T-06-INPUT | Task 2: Drive the same matrix over the HTTP surface | table-driven | `grep -q 'func TestBadInputMatrixHTTP' gateway/main_test.go && test "$(gr...` | ✅ | ✅ green |
| T-06-13-01 | 13 | 11 | RAG-03 / DEBT-RAG-01 | — | Task 1: End-to-end opted-in empty evidence through production packing | unit / e2e | `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --list \| ...` | ✅ | ✅ green |
| T-06-13-02 | 13 | 11 | RAG-03 / DEBT-RAG-01 | — | Task 2: Dedicated model-only system policy | unit / e2e | `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --list \| ...` | ✅ | ✅ green |
| T-06-13-03 | 13 | 11 | RAG-03 / DEBT-RAG-01 | — | Task 3: Admit model_only on the outbound answer_basis schema | unit / e2e | `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --list \| ...` | ✅ | ✅ green |
| T-06-14-01 | 14 | 12 | RAG-03 / DEBT-RAG-03 | — | Task 1: De-dupe repaired citation ids and pin both SC5 reproductions | unit / regression | `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --list \| ...` | ✅ | ✅ green |
| T-06-14-02 | 14 | 12 | RAG-03 / DEBT-RAG-03 | — | Task 2: First-occurrence unique structured citations | unit / regression | `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --list \| ...` | ✅ | ✅ green |
| T-06-15-01 | 15 | 13 | RAG-03 / DEBT-RAG-01, DEBT-RAG-03 | — | Task 1: Gate the published inline generation remainder before anything is moved | node-level mock e2e | `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --list \| ...` | ✅ | ✅ green |
| T-06-15-02 | 15 | 13 | RAG-03 / DEBT-RAG-01, DEBT-RAG-03 | — | Task 2: Split the validator, pin answer_basis at both sites, and prove one SC3 path end to end | node-level mock e2e | `cargo test --lib --manifest-path engine/Cargo.toml --locked -- model_only` | ✅ | ✅ green |
| T-06-15-03 | 15 | 13 | RAG-03 / DEBT-RAG-01, DEBT-RAG-03 | — | Task 3: Prove SC5's three unreachable clauses and the SC3 flag-off regression through the real adapter | node-level mock e2e | `cargo test --lib --manifest-path engine/Cargo.toml --locked -- --list \| ...` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] **Test-fixture constructor for `QueryRagRequest`** (`#[cfg(test)]`, `..Default::default()`-based) plus migration of all exhaustive struct literals (Plan 06-06).
- [x] **Test-fixture constructor for `Notice`** covering exhaustive literals (Plans 06-06, 06-07).
- [x] **Failure-mode extensions to the Phase 05 `cfg(test)` fake-port seam** (D-83): error, timeout, empty, malformed-citation variants on the dense, BM25, graph, and generator fakes (Plan 06-06).
- [x] **`buf generate` reproducibility check** — `buf generate` + `git diff --exit-code` verified (Plan 06-07).
- [x] **Go whole-payload assertion for `/rag/query`** — SSE payload assertions implemented in `gateway/main_test.go` (Plans 06-06, 06-07).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| D-16 weak-evidence threshold is deliberately **absent** | RAG-03 | A deliberate scope narrowing, not a behavior — nothing to assert | Recorded in the plan; reviewer confirms no threshold logic was added |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] Per-target baseline (386 Rust cases across targets, 67 Go cases) verified
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-22

---

## Validation Audit 2026-08-22
| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
