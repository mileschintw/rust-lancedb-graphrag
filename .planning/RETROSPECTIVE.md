# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — MVP

**Shipped:** 2026-10-11
**Phases:** 18 | **Plans:** 250 | **Sessions:** not tracked

### What Was Built
- A Go gateway and a Rust gRPC engine that ingest Markdown, text and JSON into LanceDB. The engine answers over hybrid
  dense plus BM25 retrieval, with rerank and evidence metadata as default levers, and graph context is opt-in.
- A fixed RAG state machine with SSE workflow events, PostgreSQL checkpoints, degraded-mode and citation-repair
  hardening, and an index rebuild-and-swap lifecycle.
- OpenTelemetry traces, metrics and logs across Go and Rust, exported to Jaeger, Prometheus, Loki and Grafana.
- A MultiHop-RAG evaluation harness with runs of record on a held-out split: four retrieval arms and four quality levers
  measured as arms under pre-registered rules.
- A README and `docs/` suite with a quickstart verified from fresh clones on Windows and WSL.

### What Worked
- Measuring before promoting. Every quality lever was an arm with a pre-registered Holm rule, so rerank and metadata
  shipped on evidence and graph-v2 and answer-format stayed off. A first run was marked SUPERSEDED, not rewritten.
- Inserted decimal phases (6.1-6.4, 6.3.1-6.3.6) absorbed discoveries without re-planning the milestone.
- Debt ledgers with source pointers. The force-closed Phase 02 and 03 debt was promoted into themed backlog phases
  (999.13-999.19) instead of being lost.
- Owner checkpoints on irreversible or judgment calls (D-223 requirement reconciliation, D-232 archive mode) kept the
  close honest.

### What Was Inefficient
- Phases 01-03 predate the verification conventions. Phase 01 has no VERIFICATION.md, and 02 and 03 were force-closed.
  The v1.0 audit therefore had to treat ARCH-01..03 as orphaned and close with an override.
- The evaluation track grew from one phase (6.3) to seven (6.3-6.3.6). OBS-05 and OBS-06 were added mid-milestone after
  early runs could not be believed (citation collapse, index drift, timeout budgets).
- The milestone audit caught an ARCH-02 overclaim late: the README promised a gateway graph-query route that 04 D-25 had
  deliberately not built.
- GSD tooling friction recurred:
  - `phase.complete` flips shared requirement IDs.
  - Non-plan `*-SUMMARY.md` files inflate plan counts.
  - "stale" verification flags appear after later source edits.
  - deferred-item table rows cannot be acknowledged.
  - `milestone.complete` pastes every SUMMARY one-liner into MILESTONES.md.

### Patterns Established
- Run-of-record documents are frozen (D-201). The docs quote only those figures, enforced by a quote checker.
- Live drives run sequentially on main with an orchestrator-side wait. Worktrees lack the gitignored eval store.
- The quickstart is verified live from fresh clones on each platform before it ships.
- Review findings get one disposition ledger per phase, merged by hand across re-reviews.

### Key Lessons
1. Write a VERIFICATION.md for every phase, including a one-plan spike. An unverified foundation phase surfaces as an
   orphaned requirement at milestone close.
2. Re-check README claims against the routes and schema that actually ship, not against requirement wording.
3. Define the evaluation's trustworthiness bar (OBS-05) before the first recorded run, not after it.
4. After any GSD state-mutating command, diff REQUIREMENTS.md and ROADMAP.md by hand.

### Cost Observations
- Model mix: not tracked per milestone. Opus orchestrated, with Opus and Sonnet executors and Sonnet reviewers and
  auditors.
- Sessions: not tracked.
- Notable: paid evaluation spend was capped per phase. 06.4's two quickstart verifications cost $0.0159 in total.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | not tracked | 18 | Measurement-first evaluation with pre-registered arms; debt promoted to themed backlog phases |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|-------------------|
| v1.0 | 963 Rust + 124 Go test functions, 2,357 Python tests | not measured | not tracked |

### Top Lessons (Verified Across Milestones)

1. (Fill in after v1.1.)
