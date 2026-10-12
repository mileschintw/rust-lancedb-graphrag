# Lancet

## What This Is

Lancet is an end-to-end, high-performance, systems-oriented Retrieval-Augmented Generation (RAG) and GraphRAG platform designed as a resume-oriented engineering artifact. It uses a split-service architecture: a Go API gateway as the control plane for HTTP APIs, document management, workflow-checkpoint persistence and metadata, and a Rust RAG engine as the data plane for document parsing, custom chunking, hybrid retrieval, graph traversal, and lightweight workflow orchestration.

The first version should be local-first and demoable: ingest a coherent corpus, answer questions with cited evidence, emit streaming workflow events, and expose traces/metrics that make the system's retrieval and orchestration decisions explainable.

## Core Value

Demonstrate strong engineering judgment by building a narrow but deep RAG/GraphRAG system that combines practical AI relevance with systems-level signals: custom data-plane mechanisms, explicit orchestration boundaries, retrieval quality evaluation, and production-like observability.

## Requirements

### Validated

- ✓ Define a stable gRPC contract between the Go API gateway and Rust RAG engine. — Phase 01
- ✓ Extract entities and relationships during ingestion and persist them as graph nodes/edges in LanceDB. — Phase 04.1
- ✓ Query graph context with `lance-graph`/Cypher-style pattern matching and compile it into RAG prompt context, including a `ContextAssemblyStrategy` enum/trait supporting `PrecomputedSemantics` and `SourceChunks` (fallback). — Phase 04.1
- ✓ Implement a lightweight Rust state machine for the fixed RAG path: receive query, reformulate, retrieve hybrid, extract graph context, assemble prompt, generate answer, complete/failed. — Phase 05 (confirmed live end-to-end against real OpenRouter: all five nodes, no stream_error)
- ✓ Emit client-facing workflow events such as node started/completed/failed, answer chunks, final answer, and workflow completed. — Phase 05 (confirmed live: node_started/node_completed pairs, one answer_chunk, one final_answer, one workflow_completed)
- ✓ Add cancellation, timeouts, and retry/fallback behavior for node execution. — Phase 05
- ✓ Add lightweight checkpoints or snapshots for workflow state during development and debugging. — Phase 05 (PostgreSQL-backed `workflow_checkpoints`; FIFO drain and cancellation atomicity proven against live Postgres)
- ✓ Support degraded mode when graph extraction or one retrieval path fails, while still returning a useful vector/BM25-backed answer when possible. — Phase 06 (RAG-03: model-only opt-in with explicit notice, per-path `RETRIEVAL_DEGRADED`, citation repair with `CITATION_REPAIRED`/`CITATION_DROPPED` and basis downgrade, table-driven bad-input matrix, `GRAPH_UNAVAILABLE` on both silent-degrade paths — 11/11 must-haves verified, 06-VERIFICATION.md)
- ✓ Add OpenTelemetry-compatible tracing, metrics, and structured logs across Go, gRPC, Rust nodes, retrieval, graph queries, and LLM calls with Grafana visualization. — Phase 06.2
- ✓ Add an offline evaluation script using a fixed test set and LLM-as-judge or similar scoring for retrieval recall, context precision, groundedness, and faithfulness. — Phase 06.3
- ✓ Empirically measure retrieval node latency distributions, establish collapse root cause (budget undersizing vs memory decay), enforce engine provider-contract invariant at startup, and derive/apply six synchronized production timeout budgets. — Phase 06.3.3

- ✓ Report standard-RAG baselines (dense-only, BM25-only, hybrid, hybrid+graph) beside the graph on a committed held-out question set with the benchmark's own retrieval convention, judged dimensions and a human-calibrated slice, and measure each quality lever (reranker, graph repair, evidence metadata, answer format) as its own arm before it becomes a default. — OBS-06, Phases 06.3.5 and 06.3.6 (closed 2026-10-10: 06.3.6 run of record; rerank and evidence_metadata ship as default levers, graph-v2 and answer-format stay off)
- ✓ Provide a README/design narrative that explains the architecture, alternatives considered, custom-vs-existing-tool choices, and how to run/evaluate the system. — Phase 06.4 (README front door plus `docs/observability.md`, `docs/evaluation.md`, `docs/design-narrative.md`, `docs/api-contract.md`, `docs/build-history.md`; quickstart verified from fresh clones on Windows and WSL; owner UAT 4/4)

- ✓ Build a Go API gateway with document upload, RAG query and metadata persistence. — v1.0 (narrowed at the v1.0 audit: graph context is served inside `/rag/query`, the standalone `QueryGraph` RPC stays gRPC-only per 04 D-25, and session IDs are engine-issued with no session table; the HTTP graph route and a session table are backlog 999.16)
- ✓ Build a Rust RAG engine with gRPC server, async runtime, tracing, and service boundaries. — v1.0 (Phases 01-06)
- ✓ Implement document ingestion for Markdown, plain text, JSON, and other lightweight text-like sources before attempting PDF-heavy ingestion. — v1.0 (Phase 02, DATA-01)
- ✓ Implement custom structure-aware recursive chunking with at least fixed-size and structure-aware strategies for comparison. — v1.0 (Phase 02, DATA-02)
- ✓ Implement hybrid retrieval that combines dense vector search, local lexical/BM25 retrieval, metadata filtering, and deduplication. — v1.0 (Phase 03, RAG-02 MVP scope under ADR-03-003; measured as arms in 06.3.5)
- ✓ Provide a local development path with `go run`, `cargo run`, and Docker Compose for PostgreSQL/Jaeger. — v1.0 (quickstart verified from fresh clones on Windows and WSL, Phase 06.4; the optional local LLM fallback was not built, see backlog 999.11)
- ✓ The LanceDB `nodes`/`edges` port tables with nullable summary columns. — v1.0 (DATA-06..08; the summary and community columns live on `entities` after the 04.1 relocation)

### Active

Next milestone (v1.1) candidates; `/gsd-new-milestone` turns these into fresh requirements.

- [ ] Persist chunks and metadata in LanceDB as the local-first vector/graph store (DATA-03, carried from v1.0 by owner decision; the 06.3.4.1 data-state gap on the earlier corpus is unresolved).
- [ ] Give the background worker structure a NoOp default execution path (RAG-06 NoOp clause; v1.0 accepted it as partial).
- [ ] Measure the actual default shape decisionally: hybrid plus rerank plus evidence metadata together (v1.0 tested the combination only descriptively).
- [ ] Fresh human calibration of the judged dimensions and the 06.3.6 D-153 judge carry-forwards.
- [ ] Settle the rerank latency regime (a local rerank endpoint or a provider comparison; related to 999.11).

### Out of Scope

- Full LangGraph, Dify, or generic workflow-engine clone — Lancet should borrow orchestration concepts but implement only the fixed RAG path needed for this project.
- Visual workflow editor, full workflow DSL, dynamic node loading, plugin marketplace, or generic tool planner — these would pull the project away from its core systems/RAG story.
- Full multi-agent framework or complex human-in-the-loop workflow — useful later, but not part of the initial MVP.
- Heavy PDF-first ingestion as the first ingestion target — start with text-like sources and make PDF support a later expansion.
- Full checkpoint database — simple in-memory/JSON/PostgreSQL-backed snapshots are enough for v1.
- Distributed workflow execution or production cloud deployment — local-first demo and evaluation come first.
- Product-facing web UI as a primary goal — CLI/API and minimal response streaming are sufficient unless a later phase explicitly adds UI.

## Current State

**Shipped:** v1.0 MVP on 2026-10-11 (tag `v1.0`; override closeout, known gaps in `.planning/MILESTONES.md`). 18 phases, 250 plans, 118 days. About 79k lines of Rust, 15k of Go and 92k of Python.

A Go gateway and a Rust engine ingest Markdown, text and JSON into LanceDB. They answer over hybrid dense plus BM25 retrieval with rerank and evidence metadata as default levers, and graph context is opt-in. Answers stream as SSE workflow events. Every request is traced through OpenTelemetry to Jaeger, Prometheus, Loki and Grafana. A Python harness evaluates against MultiHop-RAG with runs of record on a held-out split. A README and a `docs/` suite document the system, with a quickstart verified from fresh clones.

**Known debt:** `06.4-DEBT-LEDGER.md`, promoted into backlog phases 999.13-999.19.

## Next Milestone Goals

v1.1 is not yet defined. See the Active list above and the "What's next" section of `06.4-MILESTONE-SUMMARY.md`. Start it with `/gsd-new-milestone`.

## Context

The project is intended to be attractive to North American engineering interviews, especially for infrastructure, backend, data systems, AI platform, and RAG/AI-agent roles. It should show that the builder can make mature trade-offs: use existing tools for commodity infrastructure, rebuild high-leverage layers where custom implementation demonstrates understanding, and avoid overbuilding frameworks.

The current architectural direction is a Go/Rust split:

- **Go API Gateway / control plane:** HTTP API, authentication/session state, document metadata, PostgreSQL or SQLite fallback, request orchestration.
- **Rust RAG Engine / data plane:** gRPC server, async RAG pipeline, custom chunking, LanceDB vector/graph storage, hybrid retrieval, GraphRAG context extraction, prompt assembly, LLM generation, event streaming.
- **Inter-service communication:** gRPC with Protocol Buffers.
- **Storage:** LanceDB embedded in Rust for vector/graph data; PostgreSQL for document metadata and workflow checkpoints; Jaeger, Prometheus and Loki for traces, metrics and logs.
- **Evaluation:** offline Python/Rust evaluation script with a fixed corpus/test set and metrics such as retrieval recall, context precision, groundedness, and faithfulness.

The `.discussion/` folder contains prior brainstorming, implementation planning, final architectural decisions, and a lightweight state-machine plan. The final implementation decisions should be treated as the strongest source of current direction.

## Constraints

- **Architecture:** Use the Go gateway + Rust engine split unless a later decision explicitly changes it — this is central to the control-plane/data-plane story.
- **Local-first development:** The project must run locally with `go run` and `cargo run`, plus Docker Compose for supporting services.
- **Core data-plane customness:** Chunking, retrieval composition, and orchestration should be custom enough to demonstrate understanding, not hidden behind a black-box framework.
- **Selective tool use:** Use mature tools for commodity pieces such as gRPC, tracing, storage, and LLM providers.
- **Demoability:** The first shippable version should show an end-to-end ingest → retrieve → answer flow with citations/events/traces.
- **Scope discipline:** Avoid rebuilding full workflow frameworks, generic agent systems, or broad product platforms before the core RAG/GraphRAG engine works.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Go API gateway + Rust RAG engine | Separates user-facing/control-plane concerns from performance-sensitive data-plane engineering | ✓ Good |
| gRPC/Protobuf service contract | Makes service boundaries explicit and interview-discussable | ✓ Good |
| LanceDB for vector/graph storage | Local-first, Arrow-native, aligned with systems/data-plane story | ✓ Good |
| PostgreSQL for metadata/sessions | Practical relational store for users, documents, sessions, and trace metadata | ✓ Good |
| Custom chunking and hybrid retrieval | High-leverage custom layers that demonstrate RAG understanding without rebuilding vector DB internals | ✓ Good |
| Lightweight Rust state machine instead of LangGraph/Dify clone | Borrows useful orchestration concepts while preserving narrow scope | ✓ Good |
| OpenTelemetry/Jaeger tracing | Makes latency and failure points visible across Go, Rust, gRPC, retrieval, graph, and LLM calls | ✓ Good |
| Offline evaluation script | Turns answer quality and retrieval quality into measurable claims | ✓ Good |
| Avoid full workflow framework | Keeps the project finishable and focused on RAG/GraphRAG engineering | ✓ Good |
| In-place protobuf generation | Simple build chain using Buf | ✓ Phase 01 |
| Standalone Atlas CLI for Windows | Avoids incorrect winget GUI tool package | ✓ Phase 01 |
| `lance-graph` 0.5.4 + arrow-version IPC bridge for Cypher graph traversal | De-risked the `lancedb`/`lance-graph`/arrow-version compatibility unknown before committing to full GraphRAG extraction/query implementation | ✓ Confirmed, Phase 04 (spike only — full extraction/storage/query deferred to Phase 04.1) |
| Event-sink buffer depth (100-slot `mpsc::channel`) accepted as a load-bearing invariant instead of adding a timeout arm to `send_terminal_event`'s permit acquisition | A workflow emits ~19-30 events max, so the channel cannot fill today; a timeout risks dropping the terminal frame it exists to guarantee. Revisit if per-token `AnswerChunk` streaming (999.x), a smaller buffer, or a shared/cloned sink ships | ✓ Accepted, Phase 05 UAT (re-confirmed against `runner.rs:161-170` at HEAD after `5354d1e` moved the risk site) |
| Gateway restores non-zero exit on bind failure via exit-code-after-defers, not `logger.Fatal` | `logger.Fatal`/`os.Exit` would skip `dispatcher.Close()` and lose buffered checkpoints — the exact defect the graceful-shutdown work (WR-01) was written to close | ✓ Shipped, Phase 05 (`fe83e71`; verified empirically — occupied port, `go run .` exits 1) |
| Checkpoint sequence-ordinal burning on failed delivery accepted as debt; client-event ordinal allocation made lazy | `send_checkpoint`'s ordinal is embedded in the event struct at construction, so deferring it changes branch ordering, not a one-line fix; the gap is confined to the failed-delivery edge (queue exhaustion/closed channel), and happy-path contiguity is proven live against Postgres | ✓ Accepted, Phase 05 UAT (`wrap_next_event` already lazy since `0c96720a`; `send_checkpoint:185` left eager) |
| D-18 total-drop honors `allow_model_only` unconditionally: flag off always fails closed with `LlmGenerationFailed`, flag on may downgrade to `MODEL_ONLY` with `CITATION_DROPPED`+`BASIS_RECONCILED` | Human UAT ruling (G-06-1): `effective_allow = ctx.allow_model_only \|\| total_drop` silently widened the opt-in flag's scope beyond what the user asked for — a total citation drop must not become a backdoor around an explicit flag-off choice | ✓ Shipped, Phase 06 (`generate.rs:258`, `949673e`; 4 discriminating tests re-run and passing under `06-VERIFICATION.md`) |
| Citation resolution's known-ID universe is the prompt-packed subset, not the full retrieved set | Human UAT ruling (G-06-2): a citation naming a retrieved-but-truncated block must never resolve or ship a client-visible excerpt the model never saw. Verification found `AssemblePromptNode` already enforced this in production (`assemble_prompt.rs:92-94`) — the gap was untested coverage, not defective code; the diagnosis in `06-UAT.md` was corrected accordingly | ✓ Confirmed, Phase 06 (4 new tests including a genuine 2-in/1-out packing-truncation case, `949673e`) |
| Grafana Loki derived fields mapped via `matcherType: label` / `matcherRegex: trace_id` for bidirectional trace<->log correlation | Standardized on structured metadata labels for OTel trace_id linkage rather than body regex | ✓ Shipped, Phase 06.2 (Plan 10) |
| Typed Go dashboard generator using `histogram_quantile` for duration metrics | Ensured duration dashboard panels represent latency distribution rather than query throughput | ✓ Shipped, Phase 06.2 (Plan 11) |
| Rate-limited exporter diagnostic suppression on Collector outage | Installed custom error handlers in Go and Rust to prevent unbounded console log spam during backend outages while preserving application availability | ✓ Shipped, Phase 06.2 (Plan 12) |
| Isolated evaluation schema via dedicated Atlas environment and store paths | `LANCET_ENV=eval` protects production/dev store integrity with zero risk of database clobbering | ✓ Shipped, Phase 06.3 (Plan 04) |
| Calibration worksheet candidate pool strictly filtered by cached non-null judge verdicts | Ensures human scoring worksheets only contain rows with matching automated judge evaluations | ✓ Shipped, Phase 06.3 (Plan 11) |
| Empirical collapse diagnosis: timeout budget undersizing rather than progressive resource decay | Two-segment measurement pass (320 records across mid-run restart) proved steady negative slope (-6.73 ms/query) and process_state restart jump (-11.3s), ruling out memory leaks | ✓ Shipped, Phase 06.3.3 |
| Six derived production timeout budgets synchronized across TOML and Rust defaults | Replaced uncalibrated 10s guesses with p95 empirical derivations (645 / 16647 / 38595 / 45674 / 1070 / 65000 ms) | ✓ Shipped, Phase 06.3.3 |
| Engine startup validation enforces provider-attempt invariant | `generation_node_timeout_ms >= 2 * per_attempt_timeout_ms` prevents node timer preempting provider retries | ✓ Shipped, Phase 06.3.3 |
| Censoring-aware derivation refuses unobserved nodes | Explicit `derivation_refused_empty_or_unavailable` row prevents fabricating integers via nesting invariants | ✓ Shipped, Phase 06.3.3 |
| Drive 2 (`eval/runs/2026-10-06-drive2-multihop_rag_diag/`) is the run of record; D-83 closed `all-pass-close` with three standing disclosures | Unpark gates were committed before the drive and passed with margin (SC-4 0.6629, SC-5 0.5385); disclosures (negative non-significant paired deltas, mid-drive provider switch, 4/100 graph-off retrieved-set difference) are reported, not toggled off. Phase 6.4 stays parked pending a separate user decision | ✓ Shipped, Phase 06.3.4.1 |
| Gate-stage drives refuse harness retries and every attempt is journaled and charged | UAT G-06.3.4.1-2 (review CR-03): a retried-away timeout erased SC-2 evidence and undercounted spend. `run --gate-stage <label>` requires `--retries 0`; the gate reader MISSes unmarked or retried journals except a closed three-drive legacy registry | ✓ Shipped, Phase 06.3.4.1 (plans 33-34) |
| Unpark gates fail closed on an incomplete journal, with a 0.80 coverage floor over sample-scoped denominators | UAT G-06.3.4.1-3a (CR-02): truncated journals read all-PASS. The floor reuses `gate.py`'s 2026-09-09 literal (no post-hoc threshold) and is measured against sample∩G / sample∩V, not the corpus-wide populations | ✓ Shipped, Phase 06.3.4.1 (plan 32) |
| `measure` honours its stage spend cap at every worker count; `--stage-cap` rejects NaN, infinity and non-positive values | UAT G-06.3.4.1-3b (CR-01, WR-02): with workers > 1 every unit was submitted up front, 40x over cap in a free repro | ✓ Shipped, Phase 06.3.4.1 (plan 31) |
| Two evaluation phases (06.3.5 retrieval ablation matrix + judged pass; 06.3.6 quality levers as arms) inserted before 6.4; backlog 999.2 and a lite 999.6 promoted; "more hops" rejected as a graph lever | Owner decision 2026-10-06 after the 06.3.4.1 close-out (`.planning/research/NEXT-STEPS-2026-10-06.md`): the run of record shows the graph is mechanically alive but buys no measurable answer quality at +1.2-1.6 s per query, and the project has never measured dense-only, BM25-only or hybrid baselines, judged dimensions or a human-calibrated slice. The docs phase writes after the implementation it documents, so the comparative evidence lands first. Levers are measured as arms on a committed held-out split so a lever that does not pay is recorded, not shipped | ✓ Recorded, 2026-10-06 (OBS-06 added; 6.4 depends on 06.3.5 and 06.3.6) |
| A reused journal is refused rather than re-driven, and the legacy gate exemption is bound to record content | Code review WR-03: a second `measure` or `drive --no-resume` into a populated journal restarted the cap's spend at zero. It now raises `JournalReuseError` before any append. WR-01: the three-drive legacy exemption keyed on header text was spoofable, so it now also binds `n_records` and a sha256 over the parsed records. WR-02: the SC-3/4/5 coverage inputs are required | ✓ Shipped, Phase 06.3.4.1 (f04e89a1, c7340a65, a923eb0c) |
| 06.3.5 held-out four-arm drive (`eval/runs/2026-10-07-heldout-multihop_rag_heldout/`) is the run of record. The SC-2 MISS stands, under a post-hoc continue-with-disclosure | 12 of 13 errors were query-embedding timeouts at 2,001-2,016 ms against the 2,000 ms budget. The pre-registered error-mode rule has no minimum count, so it read MISS. A re-drive on unchanged code would most likely repeat it, and a fix would be an engine change after a held-out reading (D-106). Holm: only bm25-only vs hybrid rejects. Both judged dimensions are uncalibrated (QWK -0.026, 0.066, n=20; D-114) | ✓ Recorded, Phase 06.3.5 (owner, 2026-10-08) |
| Plan 18 normalises a cited grounded abstention mislabelled `model_only` to `retrieval`. This is accepted against the goal wording "system under test NOT changed" (G-1 override) | The defect predates the phase (2 records in drive 2). The fix landed before the held-out drive and is disclosed by `BASIS_RECONCILED` on 118 of 1,404 records. Comparability with drive 2 holds for retrieval and is qualified for abstention and error counts. The ROADMAP goal wording is deliberately unchanged | ✓ Owner override, Phase 06.3.5 UAT (2026-10-09) |
| Review fixes after the run of record: CR-01 (case-insensitive model answer label), WR-01 (split and seed markers verified), WR-02 partial (pre-registered values AST-checked; `compare` not yet gated), WR-04, WR-05 | They postdate the drive and do not alter any reading: the verifier re-derived the run at HEAD with the same numbers. 06.3.6 runs on the stricter engine and must say so. WR-03 (prose bound) is an open owner decision | ✓ Shipped, Phase 06.3.5 (a3af9def, c9d84043, fa8f093a, c453d88f, 7a0abe78) |
| 06.3.6 held-out lever drive is the run of record: rerank (+0.0812 `answer_usable`, Holm p 0.0032; Hits@4 +0.1558) and evidence metadata (+0.0621, Holm p 0.0077) become default levers; graph-v2 and answer-format stay off | Pre-registered Holm family over four lever arms against the same-day `hybrid` on one index generation (lance-703). Metadata flips by rule; rerank's arm read SC-2 MISS (a provider-side latency regime change), so its default is the owner's disposition D-193 with the D-192 latency caveat disclosed. The single D-157 flip commit `3d765ea3` postdates the record | ✓ Shipped, Phase 06.3.6 (plans 21-22) |
| An unavailable configured default lever degrades with a notice instead of refusing startup; an explicitly named lever still fails closed | UAT gap D-194: the committed defaults made the engine unbootable over empty, metadata-less and legacy stores, and the refusal ran after the staged-job replay. Now a per-request `DEFAULT_LEVER_UNAVAILABLE` (24) WARNING notice (joins `degraded_mode`), a startup WARN before the workers and replay, and coverage/rebuild warnings. The legacy dev store was migrated once by `--migrate-only` (D-197); the engine still never upgrades `nodes` (D-144) | ✓ Shipped, Phase 06.3.6 (gap plan 23) |
| The lever-free control-arm path is deferred to the next measurement phase's freeze | D-195: arms that omit `levers` now run the committed defaults, so a future drive must choose an empty `LANCET_ENGINE__LEVERS__DEFAULTS`, an eval overlay or a proto opt-out, and launchers must refuse `LANCET_ENGINE__LEVERS__*`. Recorded runs are unaffected (provenance clauses h/j would flag such records) | — Deferred (owner, 2026-10-10) |
| The client can opt out of the default levers (`disable_default_levers`), and graph context is off by default with notice code 25 | D-198/D-207 (06.4): a lever-free control arm needs a wire opt-out, and the graph arm did not earn a default at the 06.3.6 read. Every harness arm now sends graph and lever state explicitly, and a drive refuses `LANCET_ENGINE__GRAPH__*` overrides (D-199) | ✓ Good (06.4) |
| v1 docs quote run-of-record figures only, under a quote checker, and the quickstart is verified live from fresh clones on both platforms before it ships | D-213/D-220 (06.4): a README number that cannot be traced, or a quickstart nobody ran, is the failure the docs phase exists to prevent | ✓ Good (06.4): Windows `1c000271`, WSL `752c8ae0`, spend $0.0159 |
| ARCH-02 narrowed to what the gateway ships instead of building a graph route and session table before v1.0 | v1.0 milestone audit G1-G3 (owner, 2026-10-11): 04 D-25 had deliberately kept `QueryGraph` gRPC-only, so the claim was wrong, not the design | ✓ Good (v1.0): docs-only change `08903e06`; route and session table in backlog 999.16 |
| Close v1.0 with `--no-archive-phases` and an override closeout | D-232: the docs link into `.planning/phases/`; phases 01-03 predate the verification conventions and were force-closed under ADRs | ✓ Good (v1.0): 53 open artifacts acknowledged, reasons recorded in MILESTONES.md |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state
5. Update Roadmap status

---
*Last updated: 2026-10-11 after v1.0 milestone*