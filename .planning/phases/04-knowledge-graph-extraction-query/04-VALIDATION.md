---
phase: 04
slug: knowledge-graph-extraction-query
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-06
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `cargo test` (built-in Rust test harness), matching the existing `engine/src/tests.rs` convention (Phase 2 precedent) |
| **Config file** | none — Cargo's built-in test runner needs no separate config |
| **Quick run command** | `cargo test --manifest-path engine/Cargo.toml graph::` (once the `graph` module/tests exist) |
| **Full suite command** | `cargo test --manifest-path engine/Cargo.toml --locked` |
| **Estimated runtime** | ~30 seconds (consistent with the existing engine suite; this spike-scoped phase is not expected to add heavy fixtures) |

---

## Sampling Rate

- **After every task commit:** Run `cargo test --manifest-path engine/Cargo.toml graph::` if the `graph` module exists this phase, otherwise the existing engine suite
- **After every plan wave:** Run `cargo test --manifest-path engine/Cargo.toml --locked`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

> Phase 04 is a SPIDR **Spike** (compatibility spike for `lance-graph` x `lancedb`) — its acceptance bar is "we know enough to plan Phase 04.1," not shipped extraction/query functionality (see `spidr-splitting.md`). RESEARCH.md already closed the spike's core unknown empirically: a throwaway crate was built, compiled, and executed to prove the integration pattern, then deleted — no production code landed in this repository from that proof. The table below is forward-looking to what **Phase 04.1** (the deferred implementation phase, not yet created) must cover; the planner should scope Phase 04's own PLAN.md tasks to whatever this spike phase actually commits (documentation/decision artifacts, and/or a checked-in proof-of-concept), not the full table below.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04.1-01-01 (forward ref) | 01 | 1 | DATA-05 | — | arrow ~58.3 ↔ arrow ^56.2 IPC bridge round-trips a `RecordBatch` losslessly | unit | `cargo test --manifest-path engine/Cargo.toml graph::bridge::tests` | ❌ Wave 0 (04.1) | ⬜ pending |
| 04.1-01-02 (forward ref) | 01 | 1 | DATA-05 | — | Fixed single-hop Cypher query returns correct neighbor + relationship properties for a known fixture graph | unit | `cargo test --manifest-path engine/Cargo.toml graph::tests::single_hop` | ❌ Wave 0 (04.1) | ⬜ pending |
| 04.1-01-03 (forward ref) | 01 | 1 | DATA-05 | — | Variable-length (`*1..hop_cap`) Cypher query returns correct multi-hop neighbors, using node-only `RETURN` (relationship variable cannot be projected under a variable-length quantifier) | unit | `cargo test --manifest-path engine/Cargo.toml graph::tests::multi_hop` | ❌ Wave 0 (04.1) | ⬜ pending |
| 04.1-01-04 (forward ref) | 01 | 1 | DATA-05 | — | Open-vocabulary `relation_type` filtering via `WHERE` on the generic wrapper label returns only matching-type edges | unit | `cargo test --manifest-path engine/Cargo.toml graph::tests::relation_type_filter` | ❌ Wave 0 (04.1) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `engine/src/graph/mod.rs`, `engine/src/graph/bridge.rs` — do not exist yet; deferred to Phase 04.1's Wave 0 unless Phase 04's own plan chooses to check in a proof-of-concept under a different path.
- [ ] `engine/src/graph/tests.rs` (or `engine/tests/graph_*.rs`) — deferred to Phase 04.1; covers the four behaviors in the table above.
- [ ] `engine/Cargo.toml` additions (`lance-graph`, IPC bridge deps) — deferred to Phase 04.1; this spike's dependency additions were made in a throwaway crate only, never committed to this repository.

*Phase 04 itself requires no test-framework changes — its spike used a disposable scratch crate's default `cargo test` harness, now deleted. If Phase 04's plan commits any code, align its own Wave 0 with what that plan actually introduces.*

---

## Manual-Only Verifications

*No phase-04 behaviors require manual-only verification. See PLAN.md for the actual task-level breakdown once planning completes.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
