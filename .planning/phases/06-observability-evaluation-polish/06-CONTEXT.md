# Phase 6: Observability, Evaluation & Polish - Context

**Gathered:** 2026-08-19
**Status:** Ready for planning

> **This CONTEXT.md governs Phases 6, 6.1, 6.2, 6.3 and 6.4.** The Phase 6 scope proved
> too large for one phase and was split during this discussion (D-77). Each sub-phase's
> planning MUST cite this file as its primary canonical ref rather than re-running discussion.
> Sub-phases add only a short scope note if something genuinely new surfaces. There is one
> source of truth; do not create per-phase context slices.

<domain>
## Phase Boundary

Close out v1 by making the shipped RAG/GraphRAG system **explainable, measurable and honest**:
production-grade OpenTelemetry across Go and Rust, an offline evaluation harness with a real
benchmark corpus, a README/design-narrative suite, and the deferred RAG-03 hardening target
plus the specific debt the Phase 02/03 force-closes parked here.

### The five-phase split

| Phase | Scope |
|---|---|
| **6** | Rust + Go module-graph restructure (first), consolidated additive wire-contract change, RAG-03 degraded mode (DEBT-RAG-01), citation repair (DEBT-RAG-03), bad-input matrix (DEBT-RAG-05), graph-unavailable notice (DEBT-RAG-06) |
| **6.1** | Index rebuild-and-swap + cross-index corpus generation (DEBT-RAG-04); DEBT-BU-01 / DEBT-BU-02 deterministic proofs; DEBT-CR-04 / DEBT-CR-05 documented review |
| **6.2** | OTel traces + metrics + logs across both services; Collector → Jaeger / Prometheus / Loki / Grafana; compose profiles; observability-as-code; Phase 05 D-30 workflow metadata (OBS-01) |
| **6.3** | Python evaluation harness, corpora, recorded run (OBS-02, OBS-04) |
| **6.4** | Docs suite + verified quickstart (OBS-03); backlog promotion of un-closed debt; v1 milestone closure |

Sequence is fixed: **module graph → wire contract → behavior → telemetry → eval → docs**
(D-75). Each stage's output is the next stage's input; documentation is written against
shipped reality, not intent.

### In scope
- The **nine ROADMAP-named debt items only**: DEBT-RAG-01/03/04/05/06, DEBT-BU-01/02, and the
  DEBT-CR-04 (network auth/TLS/quotas) / CR-05 conditional review (D-01). Note `DEBT-CR-04-EXT`
  and `DEBT-CR-04 / VER-20` are **different items** and go to backlog — see the D-03 table.
- Two deliberate exceptions to that scope, taken knowingly: **DEBT-P3-MODULE-GRAPH** closed in
  Phase 6 (D-80), and **metrics + a metrics backend** added to OBS-01's tracing-only text (D-33).
- OBS-01, OBS-02, OBS-03, OBS-04 and RAG-03.

### Out of scope
- The other **18** open `DEBT-*` items — promoted to five themed `999.x` backlog phases
  (D-02/D-03/D-04). Enumerated by ID in D-03; the count is exact, not approximate.
- Auth, authorization, TLS ingress, per-principal quotas, gateway HTTP server timeouts, upload
  semaphore — DEBT-CR-04/CR-05 acceptance criteria, **documented-only** (D-06).
- Automatic RAG-vs-model routing, LLM-generated supplementary eval items, threshold-gated eval,
  alerting rules, CI. See Deferred Ideas.

</domain>

<decisions>
## Implementation Decisions

### A. Debt ledger scope

- **D-01:** Phase 6 closes the **ROADMAP-named items only** — DEBT-RAG-01, -03, -04, -05, -06;
  DEBT-BU-01, -02; plus the DEBT-CR-04/CR-05 conditional review. STATE.md's broader "final
  hardening phase" framing does **not** expand the boundary. Every un-selected item gets an
  explicit recorded disposition so the coverage matrix reads them as opted-out, not missed.
- **D-02:** The **18** un-selected items are **promoted to `999.x` backlog phases** in ROADMAP.md
  (not merely re-targeted in a ledger).
- **D-03:** Promotion is grouped **by theme, ~5 backlog phases**, each listing its member IDs:
  - *Security & transport hardening* (5) — **DEBT-CR-04-EXT** (insecure Gateway→Engine gRPC
    dial; the Phase 03 extension, `03/deferred-items.md`), DEBT-P3-PROVIDER-ENDPOINT-TRUST,
    DEBT-P3-CONFIG-DB-PLAINTEXT, DEBT-P3-BODY-BOUND, DEBT-D1-SAFE-LOG
  - *Ingestion & staging robustness* (5) — DEBT-CR-01, DEBT-CR-02, DEBT-CR-03,
    DEBT-P3-STAGING-GEN-RACE, DEBT-P3-STAGING-PHYSICAL-BU
  - *Config & settings hygiene* (2) — DEBT-P3-WARN-SETTINGS, DEBT-P3-WARN-VALIDATE
  - *API contract & DX* (3) — DEBT-P3-WARN-API, DEBT-P3-WARN-DX, DEBT-WR-02
  - *Test & evidence hygiene* (3) — DEBT-WR-01, DEBT-WR-03, **DEBT-CR-04 / VER-20**
    (evidence helper forges human approval when the approval flag is omitted — an
    evidence-harness defect from the ADR-02-004 set, unrelated to the other two CR-04 items)
    (DEBT-P3-MODULE-GRAPH is **removed** from this theme — closed in Phase 6 per D-80)

  **18 items total.** ⚠ `DEBT-CR-04` is three unrelated issues sharing one label; each has its
  own disposition and downstream agents must not collapse them:
  | Label | What it actually is | Source | Disposition |
  |---|---|---|---|
  | `DEBT-CR-04` | Network auth, authz, TLS, quotas | `02/deferred-items.md` (verification-disposition) | Documented-only, D-06 |
  | `DEBT-CR-04-EXT` | Insecure Gateway→Engine gRPC dial | `03/deferred-items.md` | Backlog — Security & transport |
  | `DEBT-CR-04 / VER-20` | Evidence helper forges human approval | `02/deferred-items.md` (ADR-02-004 set) | Backlog — Test & evidence hygiene |
- **D-04:** The promotion is a **dedicated Phase 6.4 plan task** (ROADMAP.md edits +
  deferred-items.md cross-links), ordered last so the ledger reflects what actually closed.
- **D-05:** **DEBT-RAG-02 is closed as satisfied by Phase 05** — D-11/D-12's bounded generation
  retry plus D-13's honest-failure contract is the whole policy; D-14 descoped multi-provider
  fallback. No Phase 6 work, no backlog entry.
- **D-06:** The SC6 review of **DEBT-CR-04 (network auth/authz/TLS/quotas) and DEBT-CR-05 is
  documented-only** — this is a
  local-only project. Verify the loopback guardrail holds and no trigger fired, record the
  re-acceptance, ship **no new code for either**. This explicitly includes shipping *without*
  gateway `ReadTimeout`/`WriteTimeout`/`IdleTimeout` and *without* a bounded upload semaphore.
  Accepted knowingly.
- **D-07:** **DEBT-BU-01 and DEBT-BU-02 close via deterministic tests, no live run.** BU-01: a
  controlled/injected clock, matching challenge/evidence identity and issue times, exceeding
  only `issued_at`→`generated_at`, asserting the dedicated complete-run-window error
  classification. BU-02: caller-fixture SHA-256 and bytes preserved across success plus
  representative early and post-upload failures, using script-created temporary inputs only.
- **D-08:** **DEBT-RAG-06 closes by adding the missing notice, not by changing behavior.**
  `GRAPH_TIMEOUT` / `GRAPH_DEGRADED` already fire on graph *failure*
  (`engine/src/workflow/nodes/graph_context.rs:135-137`). What degrades **silently** is the
  empty-result path (`:112-115`) and the absent-`graph_port` path (`:145-148`) — those get a
  machine-readable notice (e.g. `GRAPH_UNAVAILABLE`). 04.1 D-32 and Phase 05 D-09 behavior is
  unchanged. Tests prove source-chunk queries never require graph data.
- **D-09:** **DEBT-D1-SAFE-LOG stays in the backlog** (Security & transport theme) even though
  Phase 6.2 exports full engine logs to Loki over OTLP — which unambiguously fires its
  "shared log sink" trigger. Rationale: Loki runs in the same local compose, single user,
  loopback-bound; the multi-tenant sink the debt fears does not exist here. Same reasoning as
  D-06. **The fired trigger is recorded here deliberately** so the backlog phase knows its risk
  profile changed.

### B. Degraded-mode behavior — RAG-03 (Phase 6)

- **D-10:** **Model-only answers are supported, opt-in per request, default off.** When both
  retrieval paths fail (or evidence is absent) and the caller opted in, the workflow generates
  an answer with `answer_basis = MODEL_ONLY`, an explicit notice, and **zero citations**. With
  the flag off, today's fail-closed behavior stands. This requires lifting the hard guard at
  `engine/src/generation/mod.rs:172-175` ("ModelOnly answer basis is not supported on Phase 03
  QueryRAG path") — a deliberate act, not a side effect.
  *User rationale, recorded as data:* the eventual goal is for the system to decide per question
  whether RAG is needed at all; retrieval legitimately returns nothing and an answer is still
  wanted. The load-bearing principle is that **when retrieved data contradicts model knowledge,
  our data wins**. — **Reversibility:** one-way — the opt-in becomes a published field on
  `QueryRAGRequest` and on `/rag/query`; removing it breaks any client that sets it.
- **D-11:** **The opt-in flag overrides Phase 05 D-03's zero-evidence short-circuit.** When the
  caller has opted in, a zero-evidence query no longer skips `AssemblePrompt`/`GenerateAnswer` —
  it runs them and returns `MODEL_ONLY` + notice + no citations. With the flag off, D-03's
  short-circuit is exactly as shipped. **This is an explicit amendment to Phase 05 D-03.**
  — **Reversibility:** costly — the runner's zero-evidence branch
  (`engine/src/workflow/runner.rs:427,481`) and its tests both change shape.
- **D-12:** The opt-in is **config default (off) + per-request override** — a TOML/env key
  following the Phase 2 D-26–D-30 convention, plus an additive `QueryRAGRequest` field plumbed
  through the gateway's `/rag/query`.
- **D-13:** **One retrieval path failing keeps `answer_basis = RETRIEVAL`**, with a
  machine-readable notice naming the failed path (e.g. `RETRIEVAL_DEGRADED`). `answer_basis`
  keeps meaning *what grounded this answer*, not *how healthy the pipeline was* — consistent
  with how `GRAPH_DEGRADED` already behaves.
- **D-14:** **Citation repair (DEBT-RAG-03) is normalize-then-strip.** One *local* pass attempts
  to resolve near-miss markers (whitespace/case/format normalization, index-vs-id confusion).
  Anything still unresolved is stripped from the answer text, a notice is emitted
  (`CITATION_REPAIRED` / `CITATION_DROPPED`), and the basis downgrades if the answer loses all
  grounding. **No second provider call**, per the debt's own criteria.
- **D-15:** **DEBT-RAG-05 gets an enumerated, table-driven matrix**: empty/whitespace/oversized
  query, malformed session and document IDs, unsupported content type, and each filter bound
  (over-limit, negative, contradictory, unmatched). One table-driven test per surface (gRPC and
  HTTP), all rejecting **before** retrieval or provider work, with stable HTTP 400 / gRPC
  `InvalidArgument`. The table doubles as API-contract documentation in Phase 6.4.
- **D-16:** **"Weak evidence" gets no threshold — the concept is dropped.** RRF fusion scores are
  not calibrated across queries, so any fixed cutoff would be arbitrary. Recorded as
  deliberately not implemented, closing that clause of DEBT-RAG-01 by explicit narrowing.
- **D-17:** The **evidence-over-priors principle is enforced by prompt contract**: an explicit
  precedence instruction in the assembled prompt ("when evidence contradicts your prior
  knowledge, the evidence is authoritative; say so"). **The eval metric for it is deferred**
  (see D-45) — v1 ships the behavior unmeasured, recorded as an accepted gap.
- **D-18:** **`MIXED` is decided by model self-report plus engine validation, with a
  reconciliation rule.** The model declares `answer_basis` in the existing structured output;
  the engine validates against observable facts (citations present and resolving, markers
  stripped by repair, evidence partiality); on disagreement the **more conservative basis wins**
  and a notice records the reconciliation.
- **D-19:** The prompt change in D-17 is **prompt text only — the JSON schema is untouched.**
  Phase 3 D-28's `response_format`/`json_schema` contract and Phase 05 D-01 both hold. The
  reconciliation rule in D-18 works off `answer_basis`, which the schema already carries.

### C. Index lifecycle & recovery — DEBT-RAG-04 (Phase 6.1)

- **D-20:** **Rebuild-and-swap after ingest.** When an ingestion batch completes, BM25 is rebuilt
  from the nodes table and swapped into the existing `Arc<RwLock<Arc<Bm25Index>>>`
  (`engine/src/workflow/ports.rs:13`). The swap mechanism already exists and is only ever built
  once at startup (`engine/src/main.rs:3250`) — Phase 6.1 wires a trigger to it. No incremental
  IDF/doc-length bookkeeping.
- **D-21:** **Atomicity is proven by generation stamping plus assertion tests.** Results carry
  the index generation (`RetrievalSnapshot.index_generation` already exists on the wire), and a
  test asserts that a query concurrent with a swap returns results from **exactly one**
  generation. No fault-injection seam required for this property.
- **D-22:** **Queries never block on a rebuild.** Startup readiness gating is unchanged (the
  first build must complete before serving); post-startup rebuilds run off to the side and
  in-flight queries keep serving the previous generation until the instantaneous swap.
- **D-23:** The rebuild is **triggered by the Rust ingestion worker** on batch completion,
  **debounced/coalesced** so a burst of documents causes one rebuild rather than N. No new API
  surface; index lifecycle stays inside the component that owns LanceDB.
- **D-24:** **A single corpus generation covers both representations.** Dense and BM25 results
  must agree on the generation or the query is served entirely from the previous one. This gives
  `RetrievalSnapshot.index_generation` real cross-index meaning and is what actually delivers
  "no mixed evidence" during replacement. — **Reversibility:** costly — the generation becomes a
  precondition threaded through both retrieval paths and the fusion step.
- **D-25:** **Rebuild failure: fatal at startup, degraded after ingest.** A failed startup build
  stops the engine (fail-closed, preserving build-before-readiness). A failed post-ingest
  rebuild keeps the previous generation serving, emits a warning notice on affected queries, and
  logs/spans at error level — the same one-path-degraded contract as D-13.
- **D-26:** **The corpus generation is derived at startup** from persisted LanceDB state (max
  staging generation across the corpus) — no stored counter, no second source of truth, survives
  restart by construction.

### D. Trace propagation, spans, metrics & logs — OBS-01 (Phase 6.2)

- **D-27:** **The OTel trace ID is authoritative.** `correlation_id` is recorded as a span
  attribute and retained in responses, notices and checkpoints for continuity. This amends
  Phase 05 D-29 (which reused `correlation_id` as `trace_id`) without touching the shipped
  `correlation_id` contract.
- **D-28:** **Inbound W3C `traceparent` is honoured when present**; otherwise the gateway starts
  the root. Standard propagator behavior; propagation onward into gRPC metadata is unchanged
  either way.
- **D-29:** **Span depth in the engine is nodes + leaf I/O.** Phase 05 D-31's five node spans
  (`query_reformulation`, `hybrid_retrieval`, `graph_context_extraction`, `prompt_assembly`,
  `llm_generation`) plus a child span per real external call: embedding request, dense LanceDB
  search, BM25 query, graph Cypher traversal, and **each LLM attempt** (so D-12's retry appears
  as two sibling spans). Roughly 8–10 spans per query.
- **D-30:** **Ingestion is fully traced** — upload → admission → chunking → embedding → staging
  write → graph extraction → index rebuild. OBS-01's text names graph queries and LLM calls, and
  both live in ingestion; this also makes D-20's rebuild-and-swap observable.
- **D-31:** **The root span covers the whole SSE stream** — opened on request, closed when the
  stream terminates, so span duration equals user-perceived latency and node spans nest inside
  it. The terminal outcome (completed/failed, `answer_basis`, degraded flags) is set as span
  attributes plus span status before close.
- **D-32:** **Sampling is always-on, overridable** through the existing TOML+env convention. The
  production reasoning for ratio sampling is documented in Phase 6.4's observability deep-dive
  rather than implemented.
- **D-33:** **Metrics ship with a real backend.** This is a **deliberate widening** of OBS-01's
  "tracing" wording, justified by PROJECT.md's stated demo goal of exposing traces *and*
  metrics. Downstream agents must treat it as intentional scope, not creep.
- **D-34:** **Topology: both services export OTLP → OpenTelemetry Collector → Jaeger (traces) +
  Prometheus (metrics) + Loki (logs), with Grafana as the single pane** correlating all three by
  `trace_id`.
- **D-35:** **Metric set is RAG-quality operational, not generic RED** — query latency histogram
  by outcome; retrieval path failure counter (dense/BM25/graph, by kind); degraded-answer
  counter by `answer_basis`; citation repair/drop counter; generation retry counter;
  evidence-set size histogram; ingest document and chunk counters; index rebuild duration and
  corpus generation gauge. Every metric maps to a decision made in this phase.
- **D-36:** **Instrumentation is a bridge architecture, not a rewrite** (user-specified):
  - Rust traces — `tracing` spans + `tracing-opentelemetry` → `SdkTracerProvider` → OTLP
  - Rust logs — `info!`/`error!` + `opentelemetry-appender-tracing` → `SdkLoggerProvider` → OTLP
  - Rust metrics — OTel Meter API directly
  - Go logs — zap + `go.opentelemetry.io/contrib/bridges/otelzap` → OTLP
  Existing `#[instrument]` / `info_span!` sites (including the `query_rag` span) become OTel
  spans with no rewrite. — **Reversibility:** costly — telemetry initialization becomes
  load-bearing in both service entry points.
- **D-37:** **Go traces use `otelhttp` + `otelgrpc` middleware** — `otelhttp` handler wrapping
  the chi router, `otelgrpc` stats handler on the engine client connection. Inbound extraction,
  outbound gRPC metadata injection and span naming come from the contrib instrumentation.
  Manual child spans only where a handler does something worth its own span.
- **D-38:** **Missing collector degrades silently to stdout.** Telemetry initialization never
  fails the service: one startup warning, existing fmt/stdout logging keeps working. Preserves
  PROJECT.md's constraint that the project runs with plain `go run` / `cargo run`.
- **D-39:** **`docker-compose` uses profiles** — a core profile with just PostgreSQL (the only
  hard dependency), and an `observability` profile bringing up Collector, Jaeger, Prometheus,
  Loki and Grafana. `docker compose up` stays light; `--profile observability` gives the full
  demo stack.
- **D-40:** **Observability as code, deterministically provisioned.** Collector pipelines,
  Prometheus scrape config, Loki config, Grafana datasources and dashboards are all committed
  and auto-provisioned — **no manual UI state anywhere**. Dashboards are **generated from typed
  code** (Grafana Foundation SDK or grafonnet) with **both the source and the generated JSON
  committed** and a regeneration target. **No alert rules and no recording rules** — there is no
  on-call and nowhere to route them.
- **D-41:** **Phase 05 D-30's workflow metadata lands in both places** — as span attributes *and*
  as additive `WorkflowCompletedEvent` protobuf fields (same additive pattern as Phase 05's tags
  10/11). D-30 listed them as response-contract fields, so a traces-only implementation would
  silently drop half the commitment.
- **D-42:** **Naming follows OTel semantic conventions where they exist, domain names elsewhere.**
  Use `gen_ai.request.model` / `gen_ai.usage.*` for LLM calls, `db.system` / `db.operation` for
  datastore operations, and `http.*` / `rpc.*` from the auto-instrumentation. Use domain-specific
  names for what has no convention — retrieval fusion, graph traversal, index generation,
  degraded reasons.
- **D-43:** **Service identity is explicit** — `service.name` of `lancet-gateway` and
  `lancet-engine`, plus `service.version` from the build (Cargo/Go version or git SHA) and
  `deployment.environment`, set via the standard resource detector and env-overridable. Every
  trace and metric is attributable to a specific build, which the eval's per-run commit stamping
  depends on.

### E. Evaluation corpus, metrics & harness — OBS-02 / OBS-04 (Phase 6.3)

- **D-44:** **Corpus: MultiHop-RAG is the main benchmark** (~500 questions sampled),
  **GraphRAG-Bench (Novel) is an optional graph-showcase supplement**. MultiHop-RAG's corpus is
  full news articles rather than snippets, so structure-aware chunking and entity extraction are
  genuinely exercised, and its queries carry evidence labels for retrieval recall.
  *Supersedes two earlier answers in this discussion — a generic "public QA benchmark subset"
  and then 2WikiMultihopQA. Both are void; MultiHop-RAG is the decision.*
- **D-45:** **v1 uses the benchmark's own Q/A only.** LLM-generated + human-reviewed
  supplementary items are deferred. Consequence, recorded explicitly: **the D-17 evidence-vs-priors
  metric has nothing to run on in v1 and is deferred with the generated set.** The prompt
  precedence contract still ships.
- **D-46:** **Graph capability is measured by ablation** — the same question set run with graph
  context on and off, scored as its own dimension.
- **D-47:** **The graph ablation uses a per-request flag**, so one running engine serves both
  arms and the eval interleaves them without a restart. **Kept distinct from the D-10/D-12
  model-only opt-in** — "answer without evidence" and "answer without graph" are different
  concepts and must not share a field. — **Reversibility:** one-way — another published request
  field.
- **D-48:** **The harness is Python, driving the gateway's `/rag/query` HTTP/SSE endpoint** like
  a real client. Matches the existing `scripts/` Python precedent and measures the whole stack —
  gateway, streaming, notices, degraded paths — as a user experiences it. It is an integration
  harness and requires both services running.
- **D-49:** **The harness lives in a dedicated `eval/` directory with `pyproject.toml` + a
  lockfile, run via `uv`.** The repo currently has **no Python dependency manifest at all**;
  `scripts/phase02_live_evidence.py` has none. `uv` gives reproducibility a lock file, which
  "reproducible eval" otherwise wouldn't have.
- **D-50:** **Metrics split deterministic from LLM-judged.** Deterministic, computed from gold
  labels with **no LLM at all**: retrieval recall@k, context precision, MRR/nDCG, answer EM/F1.
  **LLM-as-judge only for groundedness and faithfulness**, where no gold label exists. The
  deterministic half runs free, instantly, reproducibly, and **without an API key**.
- **D-51:** **OBS-04's placeholder is a registered dimension returning an explicit `skipped`
  status** with a reason ("requires community summaries, Phase 999.1") — same interface as every
  other dimension, appearing in the report as skipped. **Never a fabricated number.**
- **D-52:** **Judge is pinned and results are cached.** Judge model and temperature 0 are pinned;
  judgements are cached keyed by a `(question, answer, evidence)` hash so re-runs after unrelated
  changes cost nothing; the judge model and run date appear in the output. The cache file makes
  reported numbers auditable.
- **D-53:** **The 500-question selection is drawn with a committed fixed seed**, and a
  `--sample N` flag runs a smaller *judged* slice with sample size printed prominently in the
  report. Deterministic metrics always run over the full set (they are free).
- **D-54:** **Output is a committed Markdown report plus machine-readable JSON, advisory only** —
  no pass/fail threshold gate. A small set plus judge variance would produce false alarms.
- **D-55:** **Seed cost is bounded by a reduced document subset plus a persistent store.** Seed
  only the documents the sampled questions reference, plus distractors — unreferenced articles
  cannot affect recall on those questions. Ingest once into the isolated eval store; reseeding is
  an explicit command, not a per-run cost. The subset selection must be documented so the numbers
  stay interpretable.
- **D-56:** **The eval store is fully isolated** — its own LanceDB path and its own PostgreSQL
  schema, separate from the dev store, torn down and rebuilt on demand. Necessary because
  DEBT-P3-WARN-DX records the existing seeder as non-idempotent, and because each corpus must not
  contaminate the other. Seeding goes **through the real ingestion path** (upload → chunk → embed
  → graph extract) so the eval measures the actual system.
- **D-57:** **The eval schema is created by the existing Atlas migrations applied to a different
  schema** — identical DDL, one Atlas invocation, no second schema definition to drift.
- **D-58:** **Checkpoint growth is absorbed by the isolated eval schema** — a 500-question run
  writes roughly 2,500 checkpoint rows carrying full accumulated snapshots (Phase 05 D-28), and
  these are dropped with the schema on reseed. Phase 05 D-24's no-TTL decision stands untouched
  for the real system. Checkpoints stay **enabled** during eval runs so that path is exercised.
- **D-59:** **GraphRAG-Bench (Novel) is an optional second corpus on the same harness.** The
  harness is corpus-agnostic — a corpus is a config entry naming its documents, question set and
  label format. Phase 6.3 must prove the harness handles both; **only MultiHop-RAG results are
  required for closure**.
- **D-60:** **Results are reported per corpus with no cross-corpus aggregate.** Each section
  carries its own metric table, run metadata (judge model, sample size, date, index generation,
  commit SHA) and ablation results. Averaging across different label schemas would produce a
  meaningless number.
- **D-61:** **Every recorded run is committed as a dated, versioned record** stamped with commit
  SHA, judge model, sample size, corpus and index generation. Old runs become a visible
  trajectory; the README cites the latest.
- **D-62:** **Free-tier models stay the default, pinned and documented.** All three roles —
  generation, embedding and judge — are pinned and reported in every run's metadata, with the
  **judge deliberately a different model from the generator** so it does not grade its own work.
  The docs state plainly that free-tier rate limits may require throttling or retries and that
  results are only comparable within the same model set.
- **D-63:** **Close Phase 05's WARN-NEW-01 here.** At least one automated test must exercise the
  *shipped* generation model's structured-output preflight
  (`engine/src/generation/openrouter.rs:425-434`). Today the real-engine tests pin
  `openai/gpt-4o-mini` while production ships `dots-studio/dots-3-note-preview:free`, so that path
  is covered by no test — and the eval's validity depends on it working with the configured model.
- **D-64:** **The harness preflights and fails fast with guidance** — gateway reachable, engine
  reachable, eval store seeded and at the expected corpus generation, API key present for judged
  dimensions. Without this a 500-question run fails 40 minutes in. This is also what lets the
  deterministic-only path run cleanly with no API key at all.
- **D-65:** **The Python SSE client is thin but asserts the contract** — it parses the frames and
  validates the sequence it expects (terminal event present, exactly one `final_answer`, notices
  attached), so a contract regression surfaces as an eval failure rather than silent mis-scoring.
  The eval thereby becomes a second, independent consumer of the wire contract.

### F. README / design narrative — OBS-03 (Phase 6.4)

- **D-66:** **README is the hub; `docs/` carries the deep-dives.** The README stays a readable
  front door (story, architecture sketch, quickstart, headline results, links); `docs/` gains a
  design narrative with alternatives-considered, an observability walkthrough, and an evaluation
  methodology + results page.
- **D-67:** **"Alternatives considered" is curated narrative prose linking to the ADRs**, not a
  table and not an index. Cover the decisions that actually shaped the system — LangGraph/Dify vs
  a custom state machine, LanceDB vs pgvector/Qdrant, custom chunking vs a framework's, Go+Rust
  split vs one language — each with what was rejected and why, linking to the ADR or
  `.discussion/` document for full reasoning.
- **D-68:** **The quickstart is executable and verified end-to-end on a clean checkout** —
  compose up, migrate, `cargo run` / `go run`, ingest, query, open Jaeger and Grafana, run the
  eval. **Verified on both Windows native and Linux via WSL**, since that is how this project is
  actually developed and `.planning/WINDOWS.md` records platform-specific gotchas.
- **D-69:** **Visual evidence: four Mermaid diagrams plus three captured artifacts.** Diagrams —
  (1) system/deployment topology, (2) query path as the five-node state machine including its
  degraded branches, (3) ingestion pipeline through to index rebuild-and-swap, (4) telemetry
  topology (services → Collector → Jaeger/Prometheus/Loki → Grafana). Artifacts — a real Jaeger
  trace screenshot showing the node + leaf spans, the Grafana dashboard, and a chart of eval
  results.
- **D-70:** **The existing framing is preserved and deepened, not replaced.** The
  personal-side-project / showcase voice, the AI-collaboration narrative and the `.planning/`
  GSD blueprint links were written deliberately two commits ago (`7e9339f`, `6ce5ba3`) — keep
  them and layer the OBS-03 material around them.
- **D-71:** **The README carries an honest limitations section** — what v1 does and does not do:
  local-only by design (no auth/TLS/quotas, with DEBT-CR-04's trigger conditions), the open debt
  themes linked to their backlog phases, and what the eval does and does not measure (including
  D-45's unmeasured evidence-vs-priors claim).
- **D-72:** **The observability deep-dive follows one real query end to end** — inbound
  traceparent, gateway root span, gRPC hop, the five node spans and their leaf I/O children,
  what the attributes say, where the time went — with the actual trace screenshot alongside.
  Then the metric set and what each metric answers that the trace cannot, then logs/trace
  correlation by `trace_id`.
- **D-73:** **One documentation plan per subject, each ordered after the implementation it
  documents** — design narrative, observability walkthrough, evaluation methodology + results —
  so each is written against shipped behavior with real screenshots and real numbers.

### G. Wire contract & phase sequencing

- **D-74:** **One consolidated additive wire-contract change, landed first.** Define the complete
  Phase 6 wire delta up front — the model-only request flag (D-12), the graph-ablation request
  flag (D-47), `WorkflowCompletedEvent` workflow-metadata fields (D-41), and the notice-code enum
  (D-76) — and land it as a single additive protobuf change with regenerated Rust and Go bindings
  **before** the behavior plans start. Phase 05 spent plans 05-17 and 05-23 repairing generated-field
  drift from incremental changes; one regeneration, one review, one settled contract.
  — **Reversibility:** one-way — published gRPC and HTTP contract surface.
- **D-75:** **Sequence: module graph → wire contract → behavior → telemetry → eval → docs.** Each
  stage's output is the next stage's input, and documentation is written against shipped reality.
- **D-76:** **Notice codes are promoted to a typed proto enum** (string form retained for forward
  compatibility) with the full table documented in `docs/` as part of the API contract. The
  vocabulary is now real and client-facing — `NO_EVIDENCE`, `GRAPH_DEGRADED`, `GRAPH_TIMEOUT`,
  plus new `RETRIEVAL_DEGRADED`, `CITATION_REPAIRED`/`CITATION_DROPPED`, `MODEL_ONLY`,
  `GRAPH_UNAVAILABLE` and index-staleness codes. Ad-hoc invention is already happening
  (`GRAPH_TIMEOUT` appears as a bare literal three times in `graph_context.rs`).
  — **Reversibility:** one-way — enum values become part of the published contract.
- **D-77:** **Phase 6 is split into five phases (6, 6.1, 6.2, 6.3, 6.4)** per the table in
  `<domain>`, and **this CONTEXT.md governs all of them**. No per-phase context slices, no
  re-litigating decisions.
  **The inheritance needs a mechanism, not a note.** `init.phase-op` will report
  `has_context: false` for 6.1-6.4 and nothing routes their planners here — and this repo's own
  precedent runs the other way (Phase 04.1 was inserted and got its own 28KB
  `04.1-CONTEXT.md`). The field that actually gets read is the `Canonical refs:` line in a
  ROADMAP phase entry (`analyze_phase` step 1b copies it). Therefore **each of 6.1, 6.2, 6.3 and
  6.4 MUST carry an explicit `Canonical refs:` line naming
  `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` as the governing decision
  record**, and Phase 6's own entry gets one too — it currently has none, which is why this
  document's canonical refs had to be assembled from scratch.

  **More load-bearing still: each of 6.1–6.4 MUST carry `**Depends on:** Phase 6`.**
  `plan-phase.md:705` loads CONTEXT.md/SUMMARY.md/LEARNINGS.md from every phase named in
  `Depends on:` **regardless of recency**, whereas the default window is only the 3 most recent
  phases (`plan-phase.md:87`). Without the explicit dependency, `06-CONTEXT.md` still reaches
  6.1's planner by recency but **silently falls out of the window by 6.4**, whose three most
  recent phases are 6.1, 6.2 and 6.3. Phase 04.1 already uses this field
  (`.planning/ROADMAP.md:265`), so it is an established pattern here.

  **Known consequence, accepted:** with no local CONTEXT.md, `plan-phase` will prompt "No
  CONTEXT.md found for Phase X" — answer **"Continue without context"**; the decisions arrive via
  the dependency load, not a local file. The cost is that the plan-checker's decision-coverage
  gate (`plan-phase.md:1211-1251`, "every trackable decision in `<decisions>` is referenced by at
  least one plan") **skips itself when the phase has no local CONTEXT.md**. Each sub-phase's
  planning must therefore assert its decision coverage manually — name which of the 86 decisions
  it implements — since the automated check will not run.
- **D-78:** **ROADMAP.md gets phases 6.1–6.4 inserted as the immediate next step**, before any
  planning — mirroring how Phase 04.1 was inserted. Requirement mapping: RAG-03 → 6 and 6.1;
  OBS-01 → 6.2; OBS-02 and OBS-04 → 6.3; OBS-03 → 6.4.
  **The edit is wider than the phase entries alone** — all of the following must change together
  or coverage validation reports orphans:
  1. ROADMAP header count — `**6 phases** | **23 requirements mapped**` → 10 phases.
  2. The summary table row for Phase 6 splits into five rows with per-phase requirement columns.
  3. Five new/updated `### Phase …` detail entries, each with goal, rewritten success criteria
     (D-79) and a `Canonical refs:` line per D-77.
  4. `.planning/REQUIREMENTS.md` Traceability table — the `RAG-03 | Phase 06` row splits: RAG-03's
     DEBT-RAG-01/03/05/06 clauses → Phase 6, DEBT-RAG-04 → Phase 6.1.
  5. The ~18 backlog phases from D-03 appended to the Backlog section (or deferred to the D-04
     plan task, which is where that promotion is scheduled — but the header count must reconcile
     with whichever is done first).
- **D-79:** **Success criteria are rewritten per sub-phase from the decisions in this document**,
  not merely redistributed — they will be more specific and more testable than the original seven
  (e.g. "a query concurrent with an index swap returns results from exactly one generation").
  **The mapping back to the original seven ROADMAP criteria MUST be documented so nothing silently
  drops.** Every original criterion has a home under the split — SC1 → 6.2; SC2 and SC4 → 6.3;
  SC3 → 6.4; SC5 and SC6 → 6.1; SC7 → 6 and 6.1 — and that table is the artifact the rewrite must
  produce.

### H. Engineering surface & test strategy

- **D-80:** **DEBT-P3-MODULE-GRAPH is closed in Phase 6** — a **deliberate exception** to the
  ROADMAP-named-only scope of D-01. The binary imports all production modules from the library
  crate; the dual `lib.rs`/`main.rs` declaration ends. Justification: phases 6–6.4 add substantial
  engine code across exactly that seam, which is the debt's own stated trigger ("next large engine
  module change"). — **Reversibility:** costly — touches the module declarations of both targets,
  though the 285-test suite is the safety net.
- **D-81:** **The module-graph restructure is the first Phase 6 plan**, alongside or just before
  the D-74 wire-contract change, so all five phases of new engine code land on a settled
  foundation. Front-loaded as a pure-refactor plan.
- **D-82:** **The Go gateway is restructured first too**, symmetric with the engine — `main.go`
  split into packages (telemetry setup, SSE handling, engine client, config) before the telemetry
  work lands, rather than growing past 1,500 lines.
- **D-83:** **Fault testing extends Phase 05's `cfg(test)` fake-port seam** (built by 05-15 and
  05-18) with failure modes — error, timeout, empty, malformed citation — rather than inventing a
  new mechanism. Deterministic, fast, no infrastructure, **no production fault-injection switch**.
- **D-84:** **Config knobs added by Phase 6 fail closed on present-but-invalid values**; existing
  keys keep today's behavior until the backlog Config & settings hygiene phase fixes them. This
  contains DEBT-P3-WARN-SETTINGS rather than multiplying it — a mistyped OTLP endpoint or sampler
  ratio must fail loudly, not silently disable telemetry.
- **D-85:** **No CI.** The existing local-gate model stands (the build/test commands already in
  `.planning/config.json`), documented in the README as the verification path. CI remains
  available as a future backlog item.
- **D-86:** **Phase 6.4 owns v1 milestone closure** — requirements reconciliation, debt ledger,
  and milestone summary land as Phase 6.4 tasks rather than as a separate post-phase workflow.

### Claude's Discretion

- Exact Rust and Go module/package layout produced by the D-80/D-82 restructures.
- Exact protobuf field numbers, message shapes and enum value names in the D-74 consolidated
  contract change (must carry the fields decided in D-12, D-41, D-47, D-76).
- Exact configuration key names for the new telemetry, model-only, rebuild-debounce and eval knobs
  (must follow the existing TOML+env convention and D-84's fail-closed rule).
- Choice between Grafana Foundation SDK and grafonnet for D-40's dashboard generation.
- Exact notice code string values beyond the semantics fixed in D-08, D-13, D-14 and D-76.
- Debounce window for D-23's rebuild coalescing.
- Exact MultiHop-RAG document-subset selection algorithm for D-55, provided it is documented.
- Internal structure of the `eval/` package and its report schema.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Debt acceptance contracts — the actual specification for RAG-03 and the BU/CR items
- `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` — **the only written
  spec for what RAG-03 must do.** The "Future acceptance criteria" bullets under DEBT-RAG-01,
  -03, -04, -05 and -06 are the contracts Phase 6 and 6.1 must satisfy. Also holds
  DEBT-D1-SAFE-LOG, DEBT-RAG-02, and the ADR-03-003 force-close ledger (all `DEBT-P3-*`).
- `.planning/phases/02-ingestion-chunking-vector-storage/deferred-items.md` — acceptance criteria
  and trigger conditions for DEBT-BU-01, DEBT-BU-02, DEBT-CR-04, DEBT-CR-05, and the ADR-02-004
  ledger (DEBT-CR-01..03, DEBT-WR-01..03).
- `.discussion/decisions/phase-02-verification-disposition.md` — the disposition that created the
  BU/CR debt records.
- `.discussion/decisions/phases/02/2026-07-30-ADR-02-004-all-the-way-to-ship-mvp.md` — Phase 02
  force-close.
- `.discussion/decisions/phases/03/2026-08-05-ADR-03-003-all-the-way-to-ship-mvp.md` — Phase 03
  force-close.

### Requirements & roadmap
- `.planning/ROADMAP.md` §"Phase 6: Observability, Evaluation & Polish" (lines 444–458) — goal,
  requirements RAG-03/OBS-01..04, and the original seven success criteria that D-79's rewrite must
  map back to.
- `.planning/REQUIREMENTS.md` — RAG-03, OBS-01, OBS-02, OBS-03, OBS-04 definitions and the
  Traceability table showing RAG-03 mapped to Phase 6.
- `.planning/PROJECT.md` — Core Value ("production-like observability"), Constraints (local-first
  `go run`/`cargo run`, scope discipline), Key Decisions (OTel/Jaeger, offline eval script).
- `.planning/STATE.md` §"Known Issues & Debt" — the full open-debt inventory D-01 narrows.

### Prior phase context (must not regress)
- `.planning/phases/05-state-machine-workflow-events/05-CONTEXT.md` — **D-03** (zero-evidence
  short-circuit, amended by D-11), **D-29** (correlation_id as trace_id, amended by D-27),
  **D-30/D-31** (workflow metadata and per-node spans, explicitly deferred *into* this phase —
  in-scope commitments, see D-29/D-41), **D-01** (structured-output contract unchanged, upheld by
  D-19), **D-09** (graph node always runs, unchanged by D-08), **D-11..D-14** (generation retry,
  basis for D-05), **D-24/D-28** (checkpoint retention and full snapshots, see D-58).
- `.planning/phases/03-hybrid-retrieval-basic-rag-path/03-CONTEXT.md` — D-28 (structured-output
  generation contract), D-29/D-30/D-31 (retry, cancellation, provider-error contract), D-10
  (400 on invalid input, basis for D-15), D-39 (evidence token budget).
- `.planning/phases/04.1-knowledge-graph-extraction-query-full-implementation/04.1-CONTEXT.md` —
  D-32 (silent degrade on graph failure — the behavior D-08 makes observable), D-33 (accepted
  no-redaction risk, relevant to D-09).

### Existing code this phase modifies
- `engine/src/generation/mod.rs:172-175` — the `AnswerBasis::ModelOnly` hard rejection D-10 lifts.
- `engine/src/workflow/nodes/graph_context.rs:106,112-115,135-137,145-148` — existing
  `GRAPH_TIMEOUT`/`GRAPH_DEGRADED` notices plus the two silent-degrade paths D-08 covers.
- `engine/src/workflow/nodes/retrieve.rs:194` — the `NO_EVIDENCE` notice emission site.
- `engine/src/workflow/runner.rs:427,481` — the zero-evidence short-circuit D-11 amends.
- `engine/src/workflow/ports.rs:13` — `Bm25IndexStore = Arc<RwLock<Arc<Bm25Index>>>`, the swap
  mechanism D-20 wires a trigger to.
- `engine/src/retrieval/bm25.rs:114,122` — `Bm25Index` and `from_candidates`/`from_table`.
- `engine/src/main.rs:3242-3244` — `tracing_subscriber::fmt().init()`, replaced by D-36's layered
  provider setup. `:3250` — the single startup BM25 build.
- `engine/src/generation/openrouter.rs:425-434` — the structured-output capability preflight
  D-63 requires a test for.
- `engine/src/lib.rs` and `engine/src/main.rs` — the dual module declaration D-80 closes.
- `gateway/main.go` — the file D-82 splits into packages; `/rag/query` handler and engine client
  are where D-37's instrumentation and D-12/D-47's request fields land.
- `proto/lancet/v1/lancet.proto:59-78` (`AnswerBasis`, `NoticeSeverity`, `Notice`), `:91-102`
  (`RetrievalSnapshot`, incl. `index_generation`), `:104-112` (`QueryRAGResponse`) — the contract
  D-74 extends.
- `gateway/atlas.hcl` — the migrations D-57 applies to the eval schema.

### Infrastructure
- `docker-compose.yml` — PostgreSQL + Jaeger today; D-39 adds profiles and D-34 adds Collector,
  Prometheus, Loki and Grafana.
- `jaeger-config.yaml` — OTLP receivers on 4317/4318 already configured, memstore backend.
- `config/config.toml:41-44` — the pinned `:free` embedding and generation models D-62 documents.
- `.planning/WINDOWS.md` — platform-specific gotchas D-68's dual-platform verification must honour.

### Project docs
- `README.md` — the 167-line current version whose framing D-70 preserves (rewritten in `7e9339f`
  and `6ce5ba3`); §"Local-Only Exposure Constraint & Debt Triggers (DEBT-CR-04)" is the seed for
  D-71's limitations section.
- `.discussion/final_implementation_decision_document.md` — the Go/Rust split-service boundary.
- `rust-guidelines.md`, `go-guidelines.md` — per CLAUDE.md, consult when writing Rust or Go
  respectively.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`Bm25IndexStore = Arc<RwLock<Arc<Bm25Index>>>`** (`engine/src/workflow/ports.rs:13`) — already
  designed for atomic swap; only ever written once at startup. D-20's rebuild-and-swap needs a
  trigger, not a new mechanism.
- **`RetrievalSnapshot.index_generation`** (`proto/lancet/v1/lancet.proto`) — already on the wire;
  D-24 gives it real cross-index meaning and D-21 uses it as the atomicity evidence.
- **`AnswerBasis` (RETRIEVAL/MIXED/MODEL_ONLY) and `Notice`/`NoticeSeverity`**
  (`proto/lancet/v1/lancet.proto:59-78`) — the degraded-mode contract is **behavior wiring, not
  schema work**. The enums already exist.
- **`GRAPH_TIMEOUT` / `GRAPH_DEGRADED` notice constants** (`engine/src/workflow/mod.rs:28-29`) —
  the centralization pattern D-76 extends into a typed enum.
- **Phase 05 `cfg(test)` fake-port seam** (built by plans 05-15, 05-18) — D-83 extends it with
  failure modes rather than building new test infrastructure.
- **Existing `tracing` instrumentation** including the `query_rag` span — D-36's bridge turns
  every existing `#[instrument]`/`info_span!` into an OTel span with no rewrite.
- **Jaeger 2.19 with OTLP receivers on 4317/4318** (`docker-compose.yml`, `jaeger-config.yaml`) —
  already running; only the exporters are missing.
- **Atlas migrations** (`gateway/atlas.hcl`) — D-57 reuses them for the eval schema.
- **`scripts/` Python precedent** (`phase02_live_evidence.py`) — establishes Python as an
  acceptable tool here, though D-49 moves the eval to `eval/` with real dependency management.

### Established Patterns
- **TOML + env override config convention** (Phase 2 D-26–D-30) — every new knob follows it, with
  D-84's fail-closed addition for Phase 6 keys only.
- **Go owns PostgreSQL, Rust owns LanceDB** — preserved: D-23's rebuild trigger stays in the Rust
  ingestion worker; D-56/D-57's eval schema is Go/Atlas territory.
- **Additive protobuf changes with synchronized Rust/Go regeneration** (Phase 05 tags 10/11) —
  D-74 and D-41 follow it, but consolidated into one change because incremental changes cost
  Phase 05 two repair plans (05-17, 05-23).
- **Fail-closed error classification with session/correlation identity** (Phase 03 D1 contract) —
  D-13/D-25's degraded paths must preserve it, not bypass it.
- **Library test target + binary production module** (Phase 05 plan 05-18) — the direction D-80
  completes.

### Integration Points
- `engine/src/workflow/runner.rs` — zero-evidence branch (D-11), terminal-event construction
  (D-41's workflow metadata), node dispatch (D-29's spans).
- `engine/src/workflow/nodes/*.rs` — each node gains its span (D-29) and its degraded notices
  (D-08, D-13).
- `engine/src/generation/` — the ModelOnly guard (D-10), citation repair (D-14), basis
  reconciliation (D-18), prompt precedence text (D-17/D-19).
- The Rust ingestion worker — D-23's debounced rebuild trigger and D-30's ingestion spans.
- `gateway/main.go` `/rag/query` handler and engine client — D-37's middleware, D-12/D-47's
  request fields, D-76's notice mapping, D-82's package split.
- Service entry points in both binaries — D-36/D-38/D-43's telemetry initialization.

</code_context>

<specifics>
## Specific Ideas

- **The evidence-over-priors principle, in the user's words:** the system should eventually decide
  per question whether RAG is even needed; retrieval sometimes returns nothing and an answer is
  still wanted; *"the only key is when we have certain data that against the model-owned knowledge,
  we want to use our own data."* D-17's prompt precedence instruction is the v1 expression of this.
- **The instrumentation shape the user specified**, verbatim in concept:
  `traces: tracing span + tracing-opentelemetry → SdkTracerProvider → OTLP`;
  `logs: info!/error! + opentelemetry-appender-tracing → SdkLoggerProvider → OTLP`;
  `metrics: OTel Meter API`. Go side: *"collect with Zap then export with OTel"* via
  `go.opentelemetry.io/contrib/bridges/otelzap`.
- **"Grafana as code, observability as code"** — the user's framing for D-40. Everything
  deterministic and committed; no manual UI state.
- **Benchmark choice, user-directed:** *"use MultiHop-RAG as main benchmark (maybe randomly take
  500 questions) and GraphRAG-Bench Novel as supplement if need to showcase graph rag ability
  further."*
- **Platform verification, user-directed:** *"Verify both on windows and Linux via WSL."*
- The Jaeger trace screenshot showing node + leaf spans is the single most convincing artifact this
  phase produces — it proves the observability claim in one image.

</specifics>

<deferred>
## Deferred Ideas

### Promoted to `999.x` backlog phases (D-02/D-03)
All **18** un-selected debt items, enumerated by ID in D-03 and grouped into five themed phases. Their existing constraint and
trigger lines in the phase `deferred-items.md` files remain the source of record.

### Deferred within this milestone
- **Automatic RAG-vs-model routing** — the system deciding per question whether retrieval is
  needed at all. The user's stated future intent; a new capability warranting its own phase.
  D-10's opt-in flag is the deliberate first step toward it.
- **LLM-generated + human-reviewed supplementary eval items** — multi-hop graph questions,
  evidence-vs-priors conflict cases, and out-of-corpus questions expecting `NO_EVIDENCE` or
  `MODEL_ONLY`. Deferred from v1 with D-45.
- **The evidence-vs-model-priors eval metric** — deferred with the generated test set. v1 ships
  the prompt precedence contract **unmeasured**; D-71 requires this be stated in the README's
  limitations section.
- **Weak-evidence scoring band / calibrated fusion-score threshold** — explicitly dropped (D-16),
  revisit only if fusion scores become comparable across queries.
- **Threshold-gated eval** (pass/fail exit code) — advisory only in v1 (D-54).
- **Alert rules and Prometheus recording rules** — excluded from D-40; no on-call, nowhere to
  route them, and recording rules optimize nothing at local cardinality.
- **CI** (`.github/workflows`) — D-85 keeps the local-gate model; CI including the deterministic
  eval metrics is a plausible future backlog item.
- **Gateway HTTP `ReadTimeout`/`WriteTimeout`/`IdleTimeout` and bounded upload semaphore** —
  DEBT-CR-05's acceptance criteria, documented-only per D-06. The gateway ships with no HTTP
  server timeouts; accepted knowingly as a local-only project.
- **Auth, authorization, TLS ingress, per-principal quotas** — DEBT-CR-04's acceptance criteria,
  documented-only per D-06.
- **Identity-only structured logging with no raw provider detail** — DEBT-D1-SAFE-LOG. Its
  shared-log-sink trigger is **fired** by D-34's Loki export, and it is nonetheless kept in the
  backlog per D-09. Whoever takes the Security & transport backlog phase must know this.
- **Multi-provider / backup-model generation fallback** — descoped by Phase 05 D-14, confirmed
  closed by D-05. Revisit only if reliability requirements change.

</deferred>

---

*Phase: 6-Observability, Evaluation & Polish*
*Context gathered: 2026-08-19*
*Governs phases 6, 6.1, 6.2, 6.3, 6.4*
