# Build History

Every phase of Lancet v1, in order, with its plan count and completion date. The [README](../README.md#how-it-was-built)
gives the same history in one line per group. Goals, success criteria and full plan lists are in
[`.planning/ROADMAP.md`](../.planning/ROADMAP.md), and each phase's PLAN, SUMMARY, VERIFICATION, review and UAT
records are under [`.planning/phases/`](../.planning/phases).

v1 is 250 plans across 18 phases. Phase numbers with a decimal (04.1, 6.1, 06.3.4.1 and so on) were inserted between
the original phases as the work showed they were needed.

### ✅ Phase 1: Basic Gateway & Rust Engine Ping (1 plan — 2026-07-13)
Repo structure, Go HTTP API, Rust gRPC server, Protobuf contract, Docker Compose for PostgreSQL and Jaeger.

### ✅ Phase 2: Ingestion, Chunking & Vector Storage (28 plans — 2026-07-30, force-closed per ADR-02-004)
Markdown, plain-text and JSON ingestion; fixed-size and structure-aware chunkers; embeddings and metadata in LanceDB; schema ports for future community and summary columns. Remaining gaps recorded as `DEBT-*` and paid down in Phases 6 and 6.1.

### ✅ Phase 3: Hybrid Retrieval & Basic RAG Path (23 plans — 2026-08-05, force-closed per ADR-03-003)
Dense + BM25 hybrid retrieval with metadata filters, deterministic fusion and deduplication; the first end-to-end RAG answer path; the `Reranker` port. Degraded-mode hardening (RAG-03) deliberately deferred to Phase 6.

### ✅ Phase 4: Knowledge Graph — Compatibility Spike (1 plan — 2026-08-06)
De-risked the `lance-graph` / LanceDB / Arrow version compatibility with a feature-gated proof before committing to the full build.

### ✅ Phase 04.1: Knowledge Graph Extraction & Query (9 plans — 2026-08-09)
Entity and relation extraction into `entities` / `entity_edges` at ingestion; Cypher-style pattern queries; graph context compiled into the prompt beside chunk evidence; the `ContextAssemblyStrategy` port.

### ✅ Phase 5: State Machine & Workflow Events (27 plans — UAT 10/10, 2026-08-19)
The Rust state machine with typed client-facing events streamed through the gateway over SSE; timeouts, retries and cancellation; PostgreSQL checkpoints with FIFO drain and graceful-shutdown guarantees; verified live against OpenRouter. Two quality-gate requirements (GATE-01 wire framing, GATE-02 checkpoint ownership) were formalized here.

### ✅ Phase 6: Module Graph, Wire Contract and Degraded-Mode Hardening (16 plans — 2026-08-22)
Rust and Go module-graph restructure; one consolidated additive wire-contract change; RAG-03 delivered: opt-in model-only answers with explicit notices, per-path `RETRIEVAL_DEGRADED`, citation repair with `CITATION_REPAIRED` / `CITATION_DROPPED` and basis downgrade, a table-driven bad-input matrix, `GRAPH_UNAVAILABLE` on both silent-degrade paths. Two human UAT rulings tightened the contract (a total citation drop must not bypass the model-only flag; citations resolve only against what the model actually saw).

### ✅ Phase 6.1: Index Rebuild-and-Swap and Deterministic Proofs (4 plans — 2026-08-23)
Index rebuild-and-swap with cross-index corpus generation (`DEBT-RAG-04`), deterministic proofs for two staging-race debt items, and the documented review of the local-only exposure constraint.

### ✅ Phase 6.2: OpenTelemetry Traces, Metrics and Logs (12 plans — 2026-08-27)
OTel across Go and Rust through a Collector to Jaeger, Prometheus and Loki, Grafana provisioned as code with a typed dashboard generator, trace-to-log correlation, and rate-limited exporter diagnostics under Collector outage.

### ✅ Phase 6.3: Evaluation Harness, Corpora and Recorded Run (11 plans — 2026-09-04)
The `lancet-eval` harness: MultiHop-RAG corpus sampling with fixed seeds, isolated eval store, two-arm drive, deterministic IR and answer metrics, cached LLM-as-judge scoring with a calibration worksheet, dated run records with pinned provenance. Its first full run (2026-09-03) is what the next five phases had to correct.

### ✅ Phases 06.3.1 – 06.3.4: Making the evaluation signal trustworthy (26 plans — 2026-09-05 to 2026-09-13)
A new requirement, OBS-05, formalized mid-milestone: a failed query path must be visible on the wire and in the report, every record carries provenance, retrieval and graph health are measured per path, and the graph effect is a per-question paired comparison. Delivered as: engine and config failure signalling (06.3.1, 4 plans); harness diagnostics, scored dimensions and paired ablation with bootstrap CIs (06.3.2, 6 plans); a censoring-aware latency measurement pass that replaced guessed timeouts with six p95-derived budgets and an enforced provider-attempt invariant (06.3.3, 6 plans); a staged re-drive with pre-committed gates, fail-closed journal completeness, and the root-cause record (06.3.4, 10 plans; its own full drive halted and is marked not a run of record).

### ✅ Phase 06.3.4.1: Retrieval Diagnosis, Index Identity and Graph-Yield Repair (34 plans — 2026-10-06)
Separated corpus/index drift from retrieval health from graph architecture. Fixed index identity (the eval index may contain only the mapped document set, with a regenerated gold-coverage table), fixed a `RetrieveHybrid` slowdown, added answer-usability metrics, and replaced whole-question cosine seeding with mention extraction, multi-seed matching, bounded seed-to-seed path search and a graph RRF list. Three paid drives under per-stage caps; the third is the first run of record and passed all pre-committed unpark gates. UAT 4/4, verification 10/10, security audit 156/156 threats closed.

### ✅ Phase 06.3.5: Retrieval Ablation Matrix, Paper-Convention Metrics, Judged Pass and Calibration (18 plans — 2026-10-09)
A retrieval mode on the wire contract and four arms (dense-only, BM25-only, hybrid, hybrid+graph) on a committed dev/held-out split; MultiHop-RAG's own Hits@k and MRR beside Lancet's metrics; a judged pass with a human-calibrated slice, which failed its calibration floor, so no judged figure is a finding; one four-arm comparison against hybrid as the reference. Its run of record is the baseline the levers were measured against; its error-mode gate missed on query-embedding timeouts, and the owner continued with the miss disclosed. Results: [`docs/evaluation.md`](evaluation.md#baseline-run-four-retrieval-arms).

### ✅ Phase 06.3.6: Quality Levers Measured as Arms (23 plans — 2026-10-11)
Four levers, each developed on the dev split and read once on held-out against the same day's hybrid with a pre-registered primary metric: a reranker (promoted from backlog 999.2), a graph repair selected by a per-question diagnosis of the no-path questions (graph-list precision, shipped as `graph_v2`), evidence metadata (title, source and publish date) and answer-format prompting. Rerank and evidence metadata beat hybrid after correction and ship as defaults, metadata by the pre-registered rule and rerank by owner disposition with its latency caveat; graph-v2 and answer-format stay off. Results: [`docs/evaluation.md`](evaluation.md#lever-run-seven-arms).

### ✅ Phase 6.4: Docs Suite, Verified Quickstart and v1 Milestone Closure (17 plans — 2026-10-11)
A code-first slice before the docs: a request field to opt out of the configured default levers, graph context shipped default-off and opt-in per request with a new informational notice, a harness preflight that checks every arm's echoed graph and lever settings, engine startup-ordering and metadata-coverage logging fixes, a `rerank_request` span, and a guard on the latency-measurement command. Then the README, the design narrative, the observability walkthrough, the evaluation results page with a generated forest plot, the API contract, a quickstart verified from a fresh clone on Windows and WSL, the promotion of the remaining debt to themed backlog phases, and the v1 closure ledgers.

## Backlog

The backlog phases (999.x) are listed, with their status, in the
[ROADMAP backlog](../.planning/ROADMAP.md#backlog) and summarised in the README's
[Backlog & Extension Points](../README.md#-backlog--extension-points).
