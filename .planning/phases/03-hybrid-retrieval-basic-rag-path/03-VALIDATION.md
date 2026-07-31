---
phase: 03
slug: hybrid-retrieval-basic-rag-path
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-31
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Rust built-in tests with `#[tokio::test]`, Go standard `testing`/`httptest`, Buf CLI checks |
| **Config file** | Rust: `engine/Cargo.toml`; Go: `gateway/go.mod`; API matrix: `COVERAGE.md` |
| **Quick run command** | `cargo test --manifest-path engine/Cargo.toml --locked retrieval` |
| **Full suite command** | `cargo test --manifest-path engine/Cargo.toml --locked`; `Push-Location gateway; go test ./...; $exitCode = $LASTEXITCODE; Pop-Location; if ($exitCode -ne 0) { exit $exitCode }`; `buf lint` |
| **Estimated runtime** | ~60 seconds locally, excluding the explicitly ignored live OpenRouter smoke |

## Sampling Rate

- **After every task commit:** Run the task's focused Rust, Go, Buf, or API-coverage command from the map below.
- **After every plan wave:** Run the full Rust suite, `go test ./...`, and `buf lint`; repeat `buf generate` stability checks after contract changes.
- **Before `/gsd-verify-work`:** Full suite must be green; the live provider smoke is run only when its user setup precondition is available.
- **Max feedback latency:** 60 seconds for local checks; external provider smoke is an explicit ignored check with network-dependent latency.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | RAG-02/RAG-03/RAG-04 | T-03-01-01 / T-03-01-02 / T-03-01-05 | Typed filters, isolated evidence IDs, bounded query/evidence path | integration + contract | `buf lint`; stable `buf generate`; `cargo test --manifest-path engine/Cargo.toml --locked`; `go test ./...` from `gateway` | ✅ existing production seams; tracer edits pending | ⬜ pending |
| 03-01-02 | 01 | 1 | RAG-02/RAG-03/RAG-04 | T-03-01-01 / T-03-01-02 | Temporary corpus isolation, valid marker-to-citation mapping, one generation call | Rust service integration | `cargo test --manifest-path engine/Cargo.toml --locked query_rag` | ❌ Wave 0: `engine/src/tests.rs` | ⬜ pending |
| 03-02-01 | 02 | 2 | RAG-02 | T-03-02-SC / T-03-02-04 | Approved dependencies, Unicode analysis parity, global IDF, bounded lexical index | Rust unit + build | `cargo check --manifest-path engine/Cargo.toml --locked`; `cargo test --manifest-path engine/Cargo.toml --locked bm25` | ❌ Wave 0: BM25 tests are added by the task | ⬜ pending |
| 03-02-02 | 02 | 2 | RAG-02 | T-03-02-01 / T-03-02-02 | Same typed filters before limits, schema-safe Arrow reads, stable full-precision fusion | Rust unit + LanceDB integration | `cargo test --manifest-path engine/Cargo.toml --locked retrieval` | ❌ Wave 0: `engine/src/retrieval/tests.rs` | ⬜ pending |
| 03-02-03 | 02 | 2 | RAG-04/RAG-02 | T-03-02-03 / T-03-02-04 | NoOp field preservation and readiness only after initial BM25 build | Rust unit + process integration | `cargo test --manifest-path engine/Cargo.toml --locked rerank`; `cargo test --manifest-path engine/Cargo.toml --locked --test config_startup` | ❌ Wave 0: `engine/src/rerank/tests.rs`, startup fixture | ⬜ pending |
| 03-03-01 | 03 | 2 | RAG-03/RAG-04 | T-03-03-01 / T-03-03-02 / T-03-03-03 | Closed model output, valid marker resolution, prompt boundary, capability check | Rust provider-contract + prompt tests | `cargo test --manifest-path engine/Cargo.toml --locked generation`; `cargo test --manifest-path engine/Cargo.toml --locked prompt` | ❌ Wave 0: `engine/src/generation/tests.rs` | ⬜ pending |
| 03-03-02 | 03 | 2 | RAG-03 | T-03-03-04 / T-03-03-06 | Strict body/status mapping, context forwarding, metadata preservation, local cross-runtime path | Go contract + cross-runtime integration | `Push-Location gateway; go test ./...; $exitCode = $LASTEXITCODE; Pop-Location; if ($exitCode -ne 0) { exit $exitCode }`; `node D:\Repos\lancet\.codex\gsd-core\bin\gsd-tools.cjs check api-coverage.verify-pre D:\Repos\lancet\.planning\phases\03-hybrid-retrieval-basic-rag-path` | ❌ Wave 0: gateway RAG tests | ⬜ pending |

The ignored live smoke is mapped to 03-03-01 and runs only with the declared `OPENROUTER_API_KEY` setup: `cargo test --manifest-path engine/Cargo.toml --locked openrouter_structured_output_smoke -- --ignored`.

## Wave 0 Requirements

- [x] Existing Rust, Go, `httptest`, Buf, and Cargo infrastructure covers the phase; no new test framework installation is needed.
- [x] The three Unicode packages required by the BM25 contract have an approved Package Legitimacy Audit in `03-RESEARCH.md`.
- [ ] Test scaffolds listed in the verification map are created at the start of their owning task before production assertions are finalized; a separate standalone Wave 0 plan is not required because the phase remains three vertical plans.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | — | All Phase 03 acceptance behaviors have an automated local check. The real-provider smoke is an explicitly ignored automated test gated by user setup. | — |

## Validation Sign-Off

- [x] All revised tasks have an `<automated>` verify command.
- [x] Sampling continuity: no task lacks an automated command.
- [ ] Wave 0 test scaffolds are created before their task assertions run.
- [x] No watch-mode flags are used.
- [x] Local feedback commands target the 60-second budget; the ignored provider smoke is separately identified.
- [ ] `nyquist_compliant: true` set in frontmatter after execution and validation.

**Approval:** pending
