---
phase: 04
slug: knowledge-graph-extraction-query
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-08-06
---

# Phase 04 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| hop_cap (internal Rust `u32`) to Cypher string | `traverse_multi_hop` builds a Cypher `*1..{hop_cap}` bound via `format!` — Cypher cannot parameterize this bound, so the value must be range-checked before interpolation. No network/gRPC caller reaches this in Phase 04; Phase 04.1's `QueryGraph` RPC will inherit this boundary unchanged. | internal u32, not user/network-controlled in this phase |
| Cargo registry to build output | The four new optional dependencies (`lance-graph`, `arrow-ipc`, `arrow-lg`, `arrow-ipc-lg`) enter `engine/Cargo.lock`; only `graph-spike`-feature builds compile them. | build-time dependency code |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-04-01-01 | Tampering | `format!`-built Cypher string in `traverse_multi_hop` (hop_cap interpolation) | medium | mitigate | `clamp_hop_cap` in `engine/src/graph/mod.rs` rejects `0` and values above `MAX_HOP_CAP` (3) before interpolation; proven by `clamp_hop_cap_rejects_zero_and_over_max` in `engine/src/graph/tests.rs` | closed |
| T-04-01-02 | Information Disclosure | `bridge_batch`/`bridge_batch_back` error paths | low | accept | PoC operates only on synthetic, non-sensitive fixture data — no real `lancedb` table, no gRPC/HTTP surface exists in this phase. `GraphSpikeError` messages carry only Arrow IPC codec error text, never row values. Revisit when Phase 04.1 wires this against real `entities`/`edges` tables. | closed (accepted) |
| T-04-01-SC | Tampering | Cargo dependency install (`lance-graph`, `arrow-ipc`, `arrow-lg`, `arrow-ipc-lg`) | high | mitigate | 04-RESEARCH.md's Package Legitimacy Audit confirmed `lance-graph` verdict `[OK]` (crates.io, ~3,659 downloads/week, repository independently confirmed as `github.com/lancedb/lance-graph`); `arrow-lg`/`arrow-ipc-lg` are renamed references to the already-vetted upstream `apache/arrow-rs` project. No `[ASSUMED]`/`[SUS]` verdicts among this phase's additions. | closed |
| T-04-01-03 | Denial of Service (build/CI cost, not runtime) | Full transitive dependency footprint (~350+ crates, cloud/geospatial deps) | low | accept | Build-time/CI-budget concern, not a runtime attack surface — the tree is feature-gated and does not compile under default `cargo build`/`cargo test --locked`. Phase 04.1 should budget CI time for the `graph-spike`-enabled build. | closed (accepted) |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-04-01 | T-04-01-02 | PoC-only, synthetic fixture data, no real table/network surface in this phase; error messages carry no row values. | Phase 04 plan (04-01-PLAN.md) | 2026-08-06 |
| AR-04-02 | T-04-01-03 | Build/CI-time concern only, not a runtime attack surface; feature-gated tree excluded from default builds. | Phase 04 plan (04-01-PLAN.md) | 2026-08-06 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-08-06 | 4 | 4 | 0 | /gsd-secure-phase (short-circuit: register_authored_at_plan_time=true, asvs_level=1, threats_open=0) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-08-06
