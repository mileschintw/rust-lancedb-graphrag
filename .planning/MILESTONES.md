# Milestones

## v1.0 MVP (Shipped: 2026-10-11)

**Delivered:** A Go HTTP gateway and a Rust gRPC engine that ingest Markdown, text and JSON into LanceDB, answer questions
over hybrid vector plus BM25 retrieval with an optional knowledge-graph context, stream workflow events over SSE, trace
every request through OpenTelemetry to Jaeger, Prometheus, Loki and Grafana, and are evaluated by a Python harness
against MultiHop-RAG. The runs of record, the limitations and a quickstart verified from fresh clones are written up in
the README and `docs/`.

**Phases completed:** 18 phases (1, 2, 3, 4, 4.1, 5, 6, 6.1, 6.2, 6.3, 6.3.1-6.3.6, 6.4); 250 plans; 403 tasks by the
`milestone.complete` count. `06.4-MILESTONE-SUMMARY.md` counts 639 `<task>` elements in the plan files.

**Key accomplishments:**
- **Contract, gateway and engine (Phases 1-3).** A stable gRPC contract between the Go gateway and the Rust engine, and
  a local dev path (`go run`, `cargo run`, Docker Compose). The engine does fixed-size and structure-aware chunking into
  LanceDB, dense plus BM25 hybrid retrieval with RRF fusion and deduplication, and grounded, cited answers.
- **Knowledge graph (Phases 4, 4.1).** Entity and relation extraction persisted as graph tables, and graph context
  compiled into the prompt.
- **A fixed RAG state machine (Phase 5).** Query, reformulate, retrieve, graph, prompt, answer, then complete or failed.
  It has cancellation, timeouts, retries, PostgreSQL-backed checkpoints and SSE workflow events.
- **Hardening and observability (Phases 6-6.2).** Degraded-mode, citation-repair and bad-input hardening (RAG-03), an
  index rebuild-and-swap lifecycle, and OpenTelemetry traces, metrics and logs across Go and Rust (OBS-01).
- **An evaluation signal that can be believed (Phases 6.3-6.3.6).** A MultiHop-RAG harness with failure-visible
  provenance, and a held-out four-arm retrieval matrix with Hits@k and MRR. Four quality levers were each measured as
  an arm. Rerank and evidence metadata ship as defaults; graph-v2 and the binary answer format stay off.
- **Docs and a verified quickstart (Phase 6.4).** A README plus a `docs/` suite: design narrative, evaluation,
  observability, API contract and build history. The quickstart was run from a fresh clone on Windows and on WSL.
  Residual debt was promoted to backlog phases 999.13-999.19.

**Stats:** 118 days from the initial commit `f3f2fab2` (2026-06-15) to 2026-10-11. At the 06.4-17 count: 79,330 lines
of Rust, 15,409 of Go and 91,894 of Python. Git range: `f3f2fab2` to tag `v1.0`.

**Closeout type:** override_closeout.

**Known verification overrides:** 53 newly acknowledged, 0 carried forward from a prior close (see STATE.md Deferred
Items). That is 10 debug sessions, 1 quick task, 1 UAT gap (06), 1 verification gap (03) and 40 deferred items. Three of
the 40 were mapping-table rows in `03/deferred-items.md`, rewritten as prose because the CLI cannot acknowledge table
rows.

**Phases not `passed` at close (owner override, 2026-10-11):**

| Phase | State | Reason |
|-------|-------|--------|
| 01 | no VERIFICATION.md | UAT 5/5 and SECURITY `threats_open: 0`; a single-plan ping whose verify step never wrote a report |
| 02 | complete_with_debt (15/20) | Force-closed under ADR-02-004; debt in `06.4-DEBT-LEDGER.md` |
| 03 | gaps_found (98/101) | Force-closed under ADR-03-003; `DEBT-P3-*` in `06.4-DEBT-LEDGER.md` |
| 06.3.3-06.4 | passed on disk; `init.manager` reports them stale | Covered source files changed after the verifier ran; 06.3.4 passed via the D-208 override |

### Known Gaps

From `milestones/v1.0-MILESTONE-AUDIT.md`, status gaps_found: 25 of 31 requirements, 5 of 6 flows.
- **RAG-06** (accepted partial, owner 2026-10-11): the Tokio channel worker runs real ingestion rather than a NoOp default.
- **DATA-03** (carried to v1.1, owner 2026-10-11): the box stays unchecked per the 06.3.4.1 owner decision.
- **ARCH-01..03** have no phase VERIFICATION.md. Behaviour is evidenced by 01-UAT and the 06.4 quickstart. **OBS-01** is
  verified by 06.2 but not listed in any SUMMARY frontmatter.
- **ARCH-02 narrowed** (audit G1-G3, `08903e06`): graph query is served inside `/rag/query`, `QueryGraph` stays
  gRPC-only (04 D-25), and there is no session table. The HTTP route, a session table and the unused `users` table are
  routed to backlog 999.16.

Details: `.planning/milestones/v1.0-ROADMAP.md`, `.planning/milestones/v1.0-REQUIREMENTS.md`,
`.planning/phases/06.4-docs-suite-verified-quickstart-debt-backlog-promotion-and-v1/06.4-MILESTONE-SUMMARY.md`.

---
