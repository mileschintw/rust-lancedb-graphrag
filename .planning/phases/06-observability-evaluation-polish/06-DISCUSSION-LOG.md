# Phase 6: Observability, Evaluation & Polish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-19
**Phase:** 6-Observability, Evaluation & Polish
**Mode:** `--all` (all gray areas auto-selected, discussion fully interactive)
**Areas discussed:** Debt ledger scope, Degraded-mode behavior (RAG-03), Index lifecycle & recovery (DEBT-RAG-04), Trace propagation & span granularity (OBS-01), Eval corpus & metrics & harness (OBS-02/OBS-04), README & design narrative depth (OBS-03), Wire contract & phase sequencing, Test strategy & operational surface

---

## Debt ledger scope

**Q: Which debt does Phase 6 actually close before v1 MVP is declared complete?**

| Option | Description | Selected |
|--------|-------------|----------|
| ROADMAP-named only | Close the 9 items ROADMAP SC5-7 names; everything else stays open with recorded disposition | ✓ |
| Named + security/config hygiene | The 9 plus items with real off-loopback exposure risk | |
| Full ledger closure | All ~27 open items; would require a 6/6.1 split | |
| Triage item-by-item now | Walk the full ledger marking close/defer/withdraw | |

**Notes:** ROADMAP SC5-7 names 9 items; STATE.md and the two force-close ADRs park ~18 more here by calling Phase 6 "the final hardening phase". The conflict was surfaced explicitly and resolved toward the ROADMAP boundary.

**Q: How should the ~18 un-selected items be dispositioned?**

| Option | Description | Selected |
|--------|-------------|----------|
| Re-target to v2, list by ID | Opt-out ledger in CONTEXT.md, deferred-items.md stays source of record | |
| Re-target + new ADR | Same plus a dated ADR mirroring ADR-02-004 / ADR-03-003 | |
| Promote to backlog phases | Convert into real 999.x ROADMAP entries | ✓ |

**Q: How granular should the backlog promotion be?**

| Option | Description | Selected |
|--------|-------------|----------|
| By theme (~5 phases) | Security/transport, ingestion/staging, config/settings, API/DX, engine layout | ✓ |
| Two phases | Security-and-resource vs quality-and-DX grab bags | |
| One per item (~18) | Maximum traceability, much longer Backlog section | |

**Q: When does the backlog promotion happen?**

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 6 plan task | ROADMAP edits land through a plan commit, ordered last | ✓ |
| Now, before planning | Bookkeeping step outside any plan's commit trail | |

**Q: How should DEBT-RAG-02 be recorded?**

| Option | Description | Selected |
|--------|-------------|----------|
| Close as satisfied by Ph05 | D-11/D-12 retry + D-13 honest failure is the whole policy | ✓ |
| Close, but verify in eval | Same closure gated on trace evidence | |
| Promote to backlog | Treat multi-provider fallback as still open | |

**Q: What does the SC6 review of DEBT-CR-04 / DEBT-CR-05 produce?**

| Option | Description | Selected |
|--------|-------------|----------|
| CR-05 code, CR-04 documented | Implement server timeouts + upload semaphore; document CR-04 | |
| Both documented only | Verify guardrail, record re-acceptance, no code | ✓ |
| Both implemented | Full auth/TLS/quotas + resource bounds | |

**Notes:** User's stated rationale: "as this is a local only project". The consequence — the gateway ships with no HTTP `ReadTimeout`/`WriteTimeout`/`IdleTimeout` and no bounded upload semaphore — was named in the option description before selection and accepted knowingly.

**Q: How should DEBT-BU-01 / DEBT-BU-02 behavioral proofs run?**

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic tests, no live run | Controlled clock + SHA-256/byte preservation assertions, runs in the normal suite | ✓ |
| Deterministic + one live UAT | Same plus one recorded live evidence run | |
| Live evidence run only | Original harness framing, not repeatable | |

**Q: What is left to close for DEBT-RAG-06?**

| Option | Description | Selected |
|--------|-------------|----------|
| Add the notice, keep behavior | Notice on missing/failed graph context; behavior unchanged | ✓ |
| Notice + answer_basis effect | Graph-unavailable also downgrades the basis | |
| Already satisfied, document it | Declare closed by 04.1 D-32 + Phase 05 D-09 | |

**Notes:** Grounding found mid-discussion: `GRAPH_TIMEOUT`/`GRAPH_DEGRADED` already fire on graph *failure* (`graph_context.rs:135-137`). The genuinely silent paths are the empty-result (`:112-115`) and absent-`graph_port` (`:145-148`) branches, which narrowed the remaining work.

**Q: How should Phase 6 handle DEBT-D1-SAFE-LOG given OBS-01 exports traces?**

| Option | Description | Selected |
|--------|-------------|----------|
| Backlog, note the trigger | Keep in security theme, record that OTel export fires the trigger | ✓ |
| Scrub in the span layer | Keep raw provider detail out of exported spans | |
| Close it fully here | Identity-only structured logging everywhere | |

**Notes:** Re-raised later in the tracing area once the decision to export **full engine logs to Loki** made the "shared log sink" trigger unambiguous rather than arguable. Re-confirmed: keep in backlog, local-only reasoning, trigger recorded as fired.

---

## Degraded-mode behavior (RAG-03)

**Q: Both-path retrieval failure — model-only answer, or fail closed?**

| Option | Description | Selected |
|--------|-------------|----------|
| Fail closed, don't answer | Keep the ModelOnly guard; narrows DEBT-RAG-01's written criteria | |
| Model-only, as written | Lift the guard unconditionally | |
| Model-only, opt-in per request | Implemented but gated, default off | ✓ |

**Notes:** User's own words: *"in the future, I want it to have ability to decide if certain question need to do RAG or it's better answer by model. Cause sometimes, RAG can also retrieve no data and we still want an answer. The only key is when we have certain data that against the model-owned knowledge, we want to use our own data."* The automatic-routing half was redirected to Deferred Ideas as a new capability; the evidence-precedence principle was kept in scope as a prompt/answer-basis contract decision.

**Q: How does the opt-in flag interact with Phase 05 D-03's zero-evidence short-circuit?**

| Option | Description | Selected |
|--------|-------------|----------|
| Flag overrides the short-circuit | One flag governs zero-evidence and both-path failure alike | ✓ |
| Separate the two cases | Zero evidence keeps D-03 unconditionally | |
| Flag governs, weak evidence too | Also covers weak evidence; needs a threshold | |

**Q: Where does the opt-in live?**

| Option | Description | Selected |
|--------|-------------|----------|
| Proto request field | Per-request only | |
| Config default + request override | TOML/env default plus per-call override | ✓ |
| Config only, no request field | Engine-wide, loses per-request control | |

**Q: What answer_basis does a surviving-path answer carry?**

| Option | Description | Selected |
|--------|-------------|----------|
| RETRIEVAL + degraded notice | Basis means what grounded the answer, not pipeline health | ✓ |
| MIXED + degraded notice | Signals reduced coverage; overloads MIXED | |
| RETRIEVAL, notice severity WARNING | Distinction carried by severity alone | |

**Q: What does DEBT-RAG-03 citation repair mean concretely?**

| Option | Description | Selected |
|--------|-------------|----------|
| Normalize, then strip | Local near-miss resolution, then strip + notice + basis downgrade | ✓ |
| Strip only, no normalization | Fully deterministic, discards salvageable markers | |
| Keep fail-closed for illegal markers | Partial closure, narrowest change | |

**Q: How exhaustive is DEBT-RAG-05's invalid-input coverage?**

| Option | Description | Selected |
|--------|-------------|----------|
| Enumerated matrix, table-driven | Full case table, one test per surface, doubles as API docs | ✓ |
| Representative case per class | One per rejection class | |
| Matrix + property/fuzz pass | Adds bounded fuzzing | |

**Q: Does "weak evidence" get a real threshold?**

| Option | Description | Selected |
|--------|-------------|----------|
| No threshold, drop the concept | RRF scores aren't calibrated across queries | ✓ |
| Count-based notice only | LOW_EVIDENCE notice below a configured count | |
| Score threshold with basis effect | Fusion-score floor downgrading toward MODEL_ONLY | |

**Q: How is "retrieved evidence overrides model knowledge" enforced?**

| Option | Description | Selected |
|--------|-------------|----------|
| Prompt contract + eval metric | Precedence instruction plus a scored eval dimension | ✓ |
| Prompt contract only | Claimed but unmeasured | |
| Prompt + conflict notice | Extends the locked Phase 3 D-28 schema | |

**Notes:** Later **amended** during the eval area — deferring the generated test set left this metric with nothing to run on, and the user chose to defer the metric too. Net v1 outcome is effectively "prompt contract only", recorded explicitly as an accepted gap rather than arrived at silently.

**Q: When should an answer report MIXED?**

| Option | Description | Selected |
|--------|-------------|----------|
| Model self-reports in schema | Engine trusts the declaration | |
| Engine-derived, model advisory | Deterministic from observable facts | |
| Both, with a reconciliation rule | Disagreement resolves to the more conservative basis + notice | ✓ |

---

## Index lifecycle & recovery (DEBT-RAG-04)

**Q: BM25 staleness after in-process ingest (restart currently required)?**

| Option | Description | Selected |
|--------|-------------|----------|
| Rebuild-and-swap after ingest | Wire a trigger to the existing Arc swap | ✓ |
| Incremental index update | Incremental IDF/doc-length bookkeeping | |
| Keep restart, make it explicit | Readiness/generation check plus notice | |

**Notes:** Grounding: `Bm25IndexStore = Arc<RwLock<Arc<Bm25Index>>>` (`ports.rs:13`) is already swappable but only built once at startup (`main.rs:3250`) — the mechanism exists, nothing triggers it.

**Q: How is "no mixed evidence" proven?**

| Option | Description | Selected |
|--------|-------------|----------|
| Generation stamp + assertion tests | Concurrency test asserting exactly one generation | ✓ |
| Generation stamp + fault injection | Adds failed-rebuild fault seam | |
| Generation stamp only | Property documented, not proven | |

**Q: What happens to queries during a rebuild?**

| Option | Description | Selected |
|--------|-------------|----------|
| Serve previous, swap when done | Only startup gates readiness | ✓ |
| Gate readiness on every rebuild | Strictest freshness, costs availability | |
| Serve previous with a staleness notice | Availability plus per-answer visibility | |

**Q: Where is the post-ingest rebuild triggered?**

| Option | Description | Selected |
|--------|-------------|----------|
| Engine ingestion worker | Debounced, inside the component owning LanceDB | ✓ |
| Explicit gateway-triggered endpoint | Adds API surface, freshness becomes caller's job | |
| Both | Automatic plus manual | |

**Q: Does the dense side need matching generation discipline?**

| Option | Description | Selected |
|--------|-------------|----------|
| Single corpus generation | Both representations agree or serve the previous | ✓ |
| BM25 generation only | Claim narrows to the lexical index | |
| Single generation + replacement test | Adds an explicit re-ingestion test | |

**Q: What happens when a BM25 rebuild fails?**

| Option | Description | Selected |
|--------|-------------|----------|
| Startup fails, post-ingest degrades | Fail-closed at boot; previous generation + warning after | ✓ |
| Both degrade to dense-only | Never fatal; engine can come up half-working | |
| Both fatal | Transient ingest failure takes down a running service | |

**Q: Does the corpus generation survive restart?**

| Option | Description | Selected |
|--------|-------------|----------|
| Derived at startup | From persisted LanceDB state, no counter | ✓ |
| Persisted counter | Monotonic, but a second source of truth | |
| Process-local, reset on restart | Meaningless across restarts | |

---

## Trace propagation & span granularity (OBS-01)

**Q: OTel trace ID vs Phase 05 D-29's correlation_id-as-trace_id?**

| Option | Description | Selected |
|--------|-------------|----------|
| OTel trace ID is authoritative | correlation_id becomes a span attribute, contract untouched | ✓ |
| Derive trace ID from correlation_id | Keeps D-29 literally, constrains the format forever | |
| Both IDs, both in the response | Adds a wire field for jump-to-trace | |

**Q: Honour inbound W3C traceparent?**

| Option | Description | Selected |
|--------|-------------|----------|
| Honour if present, else start root | Standard propagator behavior | ✓ |
| Always start a fresh root | Discards the distributed-tracing property | |

**Q: Span depth inside the Rust engine?**

| Option | Description | Selected |
|--------|-------------|----------|
| Nodes + leaf I/O calls | Five node spans plus a child per external call | ✓ |
| Nodes only | Can't attribute a slow retrieval to dense/BM25/fusion | |
| Nodes + leaf I/O + fusion detail | Fusion spans mostly carry attributes, not duration | |

**Q: Is ingestion traced?**

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, ingestion pipeline traced | Upload through index rebuild | ✓ |
| Query path only | Longest, most failure-prone path stays invisible | |
| Query path + ingestion entry/exit only | Coarse span per document | |

**Q: Metrics as well as traces?**

| Option | Description | Selected |
|--------|-------------|----------|
| Traces only | OBS-01's literal text | |
| Traces + OTLP metrics, no backend | Unverifiable end to end | |
| Traces + metrics + backend | Full pipeline with a real metrics store | ✓ |

**Notes:** Flagged at selection time as a deliberate widening of OBS-01's "tracing" wording, justified by PROJECT.md's "expose traces/metrics" demo goal. Recorded in CONTEXT.md as intentional so the planner does not treat it as scope creep.

**Q: Behavior when no OTLP collector is listening?**

| Option | Description | Selected |
|--------|-------------|----------|
| Degrade silently to stdout | One warning, stdout keeps working | ✓ |
| Explicit opt-in via config | No connection attempt unless enabled | |
| Fail startup if configured but unreachable | Hostile to a local-first demo | |

**Q: Observability backend topology?**

| Option | Description | Selected |
|--------|-------------|----------|
| Collector → Prometheus + Jaeger | Canonical production topology | |
| Direct: Jaeger + Prometheus scrape | Mixes push and pull, adds HTTP to the engine | |
| Collector → Prometheus + Jaeger + Grafana | Adds a single pane for the demo | ✓ |

**Q: Which metrics?**

| Option | Description | Selected |
|--------|-------------|----------|
| RAG-quality operational set | Every metric maps to a phase decision | ✓ |
| RED metrics only | Nothing about it says "RAG system" | |
| RED + a few RAG counters | Middle ground | |

**Q: Where does Phase 05 D-30's workflow metadata land?**

| Option | Description | Selected |
|--------|-------------|----------|
| Span attributes + WorkflowCompleted | Both, since D-30 listed them as response fields | ✓ |
| Span attributes only | API becomes less self-describing | |
| WorkflowCompleted only | Wastes the tracing layer | |

**Q: How does Rust bridge to OTel?**

| Option | Description | Selected |
|--------|-------------|----------|
| Spans to OTel, logs stay tracing | — | |
| Spans and logs both to OTel | — | |
| Reconsider — use the bridge | — | |
| **User-specified** | `tracing` + `tracing-opentelemetry` → SdkTracerProvider → OTLP; `info!`/`error!` + `opentelemetry-appender-tracing` → SdkLoggerProvider → OTLP; metrics via OTel Meter API | ✓ |

**Notes:** The user first answered "move all implementation to OTel SDK entirely". That was flagged: `tracing` is doing double duty as both span API and logging facade (`main.rs:3242`), and the Rust OTel **logs** SDK is far less mature than its traces SDK — so "entirely" changed the size of the work a lot. On clarification the user specified the bridge architecture above, which is a wiring change rather than a rewrite.

**Q: Go gateway instrumentation?**

| Option | Description | Selected |
|--------|-------------|----------|
| otelhttp + otelgrpc middleware | Auto extraction/injection and span naming | ✓ |
| Manual spans throughout | Re-implements propagation | |
| Middleware + manual for Postgres | Adds pgx spans | |

**Notes:** User specified zap + `go.opentelemetry.io/contrib/bridges/otelzap` for the logs half, mirroring the Rust bridge approach.

**Q: Where do OTLP logs land?**

| Option | Description | Selected |
|--------|-------------|----------|
| Loki, Grafana correlates all three | Completes the three-signal story | ✓ |
| Collector debug exporter only | No queryable log store | |
| Keep logs local, don't export | Contradicts the appender bridge choice | |

**Q: Root span lifetime over a long-lived SSE stream?**

| Option | Description | Selected |
|--------|-------------|----------|
| Root spans the whole stream | Duration equals user-perceived latency | ✓ |
| Root ends at stream open | Loses total latency | |

**Q: Sampling policy?**

| Option | Description | Selected |
|--------|-------------|----------|
| Always-on, config-overridable | Demo volume is tiny; production reasoning documented | ✓ |
| Parent-based, always-on root | OTel default | |
| Ratio-based | The trace you wanted isn't there | |

---

## Eval corpus, metrics & harness (OBS-02 / OBS-04)

**Q: What corpus does evaluation run against?**

| Option | Description | Selected |
|--------|-------------|----------|
| Curated domain corpus, in-repo | Full control, you build it | |
| Public QA benchmark subset | Ground truth free, comparable numbers | ✓ (later superseded) |
| The project's own docs | Small, technical, hard to question | |

**Q: Where does ground truth come from?**

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-authored, ~30-50 items | Real retrieval labels, slow | |
| LLM-generated, human-reviewed | Fast volume, shallow questions | ✓ |
| Hybrid: hand-authored core + generated bulk | Best coverage-per-hour | |

**Q: How do benchmark Q/A and generated items combine?**

| Option | Description | Selected |
|--------|-------------|----------|
| Benchmark Q/A + generated extras | Comparable core plus Lancet-specific supplement | |
| Benchmark passages, all Q/A generated | Loses comparability | |
| Benchmark Q/A only, generation later | Smallest scope for v1 | ✓ |

**Q: How is GraphRAG capability measured given snippet-style benchmark passages?**

| Option | Description | Selected |
|--------|-------------|----------|
| Multi-hop benchmark + graph subset | Ablation with graph on/off | ✓ |
| Second small prose corpus for graph | Two corpora to build | |
| Accept it, document the gap | Leaves the distinctive feature unevaluated | |

**Q: The evidence-vs-priors conflict metric has no items left. Resolve how?**

| Option | Description | Selected |
|--------|-------------|----------|
| Small hand-authored conflict subset | ~8-12 deliberately constructed items | |
| Defer the conflict metric too | Prompt contract ships, measurement waits | ✓ |
| Bend a benchmark subset into conflict cases | Loses comparability, needs provenance marking | |

**Notes:** This amends the degraded-mode area's "prompt contract + eval metric" decision. The tension was surfaced at the moment it arose rather than discovered later.

**Q: Harness language and driven surface?**

| Option | Description | Selected |
|--------|-------------|----------|
| Python driving HTTP/SSE | Measures the whole stack as a user sees it | ✓ |
| Python driving gRPC directly | Leaves gateway and SSE unmeasured | |
| Rust binary, in-process | Fast, misses service-boundary failures | |

**Q: Which metrics?**

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic + LLM-judged, split | Deterministic half free, instant, no API key | ✓ |
| All four via LLM judge | Makes set-overlap math cost money and vary | |
| Deterministic retrieval only | Drops groundedness and faithfulness | |

**Q: OBS-04 placeholder metric behavior?**

| Option | Description | Selected |
|--------|-------------|----------|
| Registered, returns skipped | Real dimension, explicit skipped status and reason | ✓ |
| Returns a simulated score | A fake number in a quality report is a trap | |
| Trait/interface only, no registration | Port invisible in output | |

**Q: Judge cost and reproducibility?**

| Option | Description | Selected |
|--------|-------------|----------|
| Cached results + pinned judge | Cache keyed by content hash, model/date reported | ✓ |
| Pinned judge, no cache | Every re-run costs; drift hides regressions | |
| Cached + sample-size control | — | (folded in later, see below) |

**Q: Output format and gating?**

| Option | Description | Selected |
|--------|-------------|----------|
| Markdown + JSON, advisory | Committed diffable artifact, no false-alarm gate | ✓ |
| Markdown + JSON with thresholds | Enforceable but noisy on a small set | |
| JSON only | Loses the checkable artifact | |

**Q: Which multi-hop benchmark, and how vendored?**

| Option | Description | Selected |
|--------|-------------|----------|
| 2WikiMultihopQA subset, vendored | Explicit reasoning paths map to graph traversal | ✓ (superseded) |
| HotpotQA subset, vendored | Better known, no relation labels | |
| Downloaded at setup time | Loses offline reproducibility | |

**Notes:** **Superseded by the user mid-area:** *"Actually, I changed my mind. I want to use MultiHop-RAG as main benchmark (maybe randomly take 500 questions) and GraphRAG-Bench Novel as supplement if need to showcase graph rag ability further."* MultiHop-RAG's corpus is full news articles rather than snippets, so structure-aware chunking and entity extraction are genuinely exercised.

**Q: Graph on/off ablation toggle?**

| Option | Description | Selected |
|--------|-------------|----------|
| Config setting, engine restart | Exercises the real degraded path, no new API | |
| Per-request flag | One engine serves both arms, no restart | ✓ |
| Reuse the model-only opt-in field | Conflates two different concepts | |

**Q: Run size, given 500 questions × LLM judge?**

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed-seed sample + --sample flag | Reproducible selection, iteration slice, prominent sample size | ✓ |
| Commit the sampled question IDs | Most auditable, less flexible | |
| Full set every run, no sampling | Full bill each iteration | |

**Q: Corpus seeding and isolation?**

| Option | Description | Selected |
|--------|-------------|----------|
| Isolated eval store + seed script | Own LanceDB path and Postgres schema, real ingestion path | ✓ |
| Isolated store, cached after first seed | Adds a staleness-invalidation question | |
| Seed into the dev store | Non-idempotent seeder accumulates duplicates | |

**Q: Seed cost bounding (embedding + extraction over ~600 articles)?**

| Option | Description | Selected |
|--------|-------------|----------|
| Reduced doc subset + persistent store | Seed only referenced documents plus distractors | ✓ |
| Full corpus, seed once | Realistic distractor pressure, large one-time bill | |
| Full corpus, extraction off for eval | Kills the graph ablation | |

**Q: Which models run during eval?**

| Option | Description | Selected |
|--------|-------------|----------|
| Pin and record all three roles | Generation, embedding, judge — plus close Phase 05's WARN-NEW-01 | ✓ |
| Pin generation and judge only | Embedding changes silently invalidate retrieval comparisons | |
| Pin all three, leave WARN-NEW-01 | Numbers on a model path no test covers | |

**Q: Free-tier model risk?**

| Option | Description | Selected |
|--------|-------------|----------|
| Keep free defaults, pin + document | Anyone can run it; limits and comparability stated plainly | ✓ |
| Paid models for eval, free for demo | Eval measures a config the demo doesn't use | |
| Add retry/backoff for rate limits | Doesn't address silent deprecation | |

**Q: Is GraphRAG-Bench (Novel) v1 scope?**

| Option | Description | Selected |
|--------|-------------|----------|
| Optional second corpus, same harness | Harness proves it handles both; only MultiHop-RAG required | ✓ |
| Both required for v1 | Doubles cost and closure surface | |
| MultiHop-RAG only, GraphRAG-Bench to backlog | Ablation runs on one corpus | |

**Q: Multi-corpus reporting?**

| Option | Description | Selected |
|--------|-------------|----------|
| Per-corpus sections, no aggregate | Averaging incommensurable schemas is meaningless | ✓ |
| Per-corpus plus headline aggregate | Reads well, invites misreading | |

**Q: Eval Postgres schema creation?**

| Option | Description | Selected |
|--------|-------------|----------|
| Same Atlas migrations, different schema | Identical DDL, no second definition | ✓ |
| Ad-hoc setup script | Will drift from the migrations | |

**Q: Checkpoint row growth across eval runs?**

| Option | Description | Selected |
|--------|-------------|----------|
| Eval store isolated, truncate on reseed | Falls out of the isolation already chosen | ✓ |
| Disable checkpoints during eval runs | Leaves the checkpoint path unexercised | |
| Add a retention policy | Reverses Phase 05 D-24 | |

**Q: How much of the SSE contract does the Python client reimplement?**

| Option | Description | Selected |
|--------|-------------|----------|
| Thin client, assert the contract | Eval becomes a second independent contract consumer | ✓ |
| Minimal parser, terminal event only | Can't distinguish well-formed from lucky | |

**Q: Harness behavior without an API key or with services down?**

| Option | Description | Selected |
|--------|-------------|----------|
| Preflight, fail fast with guidance | Avoids failing 40 minutes into a run | ✓ |
| Fail on first error | Late, partial, unclear validity | |

**Q: Where does the harness live and how are dependencies managed?**

| Option | Description | Selected |
|--------|-------------|----------|
| eval/ dir with pyproject + uv | Lockfile gives "reproducible eval" real meaning | ✓ |
| scripts/ with requirements.txt | No lock | |
| eval/ with requirements.txt | Clean location, no lock | |

**Notes:** Grounding: the repo has **no** Python dependency manifest at all today.

---

## README / design narrative depth (OBS-03)

**Q: Where does the OBS-03 material go?**

| Option | Description | Selected |
|--------|-------------|----------|
| README as hub + docs/ deep-dives | Scannable front door, depth one click away | ✓ |
| One long README | 500-700 lines, past where people scroll | |
| README + one design doc | One long mixed-purpose doc | |

**Q: How is "alternatives considered" written?**

| Option | Description | Selected |
|--------|-------------|----------|
| Curated narrative, links to ADRs | Reads as engineering judgment | ✓ |
| Table of decisions | Can't carry the reasoning | |
| Index the ADRs | Makes the reader synthesize | |

**Q: How verified are the run/evaluate instructions?**

| Option | Description | Selected |
|--------|-------------|----------|
| Executable, verified end-to-end | Walked on a clean checkout | ✓ |
| Written, spot-checked | Environment-specific steps hide stale instructions | |
| Written, plus a make/script target | Script becomes cross-platform maintenance | |

**Q: What visual evidence?**

| Option | Description | Selected |
|--------|-------------|----------|
| Architecture diagram + trace + Grafana | — | |
| Diagram only | Observability stays an assertion | |
| Diagram + trace + Grafana + eval chart | Fullest showcase | ✓ |

**Q: Does the framing shift?**

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve, add engineering depth | Keep the voice and AI-collaboration narrative, layer OBS-03 around it | ✓ |
| Shift to conventional engineering README | Discards a differentiator just invested in | |
| Split by audience | Narrative risks going unread | |

**Q: Does debt surface publicly?**

| Option | Description | Selected |
|--------|-------------|----------|
| Honest limitations section | Knowing your system's limits reads as senior | ✓ |
| Keep the existing DEBT-CR-04 section only | Reader learns nothing about eval blind spots | |
| No public debt discussion | Unacknowledged ledger reads worse than a stated one | |

**Q: What does the observability deep-dive walk through?**

| Option | Description | Selected |
|--------|-------------|----------|
| One query, traced end-to-end | Teaches the design by example | ✓ |
| Component-by-component reference | Reads like docs for a system you already know | |
| Failure-scenario driven | Memorable, needs staged failures | |

**Q: One documentation plan or several?**

| Option | Description | Selected |
|--------|-------------|----------|
| One doc plan per subject, ordered last | Each written against shipped behavior | ✓ |
| Single documentation plan at the end | One failure blocks all docs | |
| Docs alongside each feature | Cross-cutting narrative written piecemeal | |

**Q: How do eval numbers stay honest as the system changes?**

| Option | Description | Selected |
|--------|-------------|----------|
| Dated, versioned run records | Stamped with commit SHA, judge model, sample size, generation | ✓ |
| Single latest-results page | Loses history | |
| Numbers in README, detail in docs | Headline most likely to go stale | |

**Q: How many diagrams?**

| Option | Description | Selected |
|--------|-------------|----------|
| Four: system, query, ingest, telemetry | The four things this phase makes true | ✓ |
| Two: system and query flow | Ingest and telemetry stay prose-only | |
| One system diagram | State machine and pipeline explained worse in paragraphs | |

**Q: What does "verified end-to-end" mean, platform-wise?**

| Option | Description | Selected |
|--------|-------------|----------|
| Verify on Windows, document Linux/macOS | Honest verification of the actual dev platform | |
| Verify on Linux via containers | Not how the project is developed | |
| **Verify both — Windows native and Linux via WSL** | User-specified | ✓ |

---

## Wire contract & phase sequencing

**Q: How do the several proto changes land?**

| Option | Description | Selected |
|--------|-------------|----------|
| One additive contract change, first | One regeneration, one review, settled contract | ✓ |
| Per-feature proto changes | Several regeneration cycles across two languages | |
| One change, but late | Large late change, gateway waits | |

**Notes:** Grounded in Phase 05 history — plans 05-17 and 05-23 were both spent repairing generated-field drift from incremental protobuf changes.

**Q: How should Phase 6 be ordered?**

| Option | Description | Selected |
|--------|-------------|----------|
| Contract → behavior → telemetry → eval → docs | Each stage's output feeds the next | ✓ |
| Telemetry first, behavior after | Metric set is defined by behavior that doesn't exist yet | |
| Parallel tracks, converge at eval | Both tracks touch workflow nodes; conflicts likely | |

**Q: Should notice codes be formalized?**

| Option | Description | Selected |
|--------|-------------|----------|
| Typed enum in proto + documented table | Exhaustive matching, stops ad-hoc invention | ✓ |
| Keep strings, add constants + doc table | Nothing prevents a stray literal | |
| Keep as-is, document only | Table goes stale immediately | |

**Q: Phase 6 is very large. Split it?**

| Option | Description | Selected |
|--------|-------------|----------|
| Keep as one phase | Phase 05 proves this size is executable | |
| Split: 6 hardening, 6.1 observability+eval | Two coherent phases | |
| Split: 6 delivers, 6.1 documents | Docs-only phases tend not to get executed | |
| **Split finer, decisions carried through all** | User-specified | ✓ |

**Q: Where do the seams fall?**

| Option | Description | Selected |
|--------|-------------|----------|
| Five: 6, 6.1, 6.2, 6.3, 6.4 | Follows contract→behavior→telemetry→eval→docs exactly | ✓ |
| Four: fold debt proofs into 6 | Phase 6 becomes the biggest | |
| Six: split telemetry in two | Six boundaries for one milestone | |

**Q: How is the decision record shared across sub-phases?**

| Option | Description | Selected |
|--------|-------------|----------|
| One CONTEXT.md, sub-phases inherit | One source of truth, no drift | ✓ |
| Shared CONTEXT + per-phase slices | Five files to keep consistent | |

**Q: Who creates the 6.1-6.4 roadmap entries and when?**

| Option | Description | Selected |
|--------|-------------|----------|
| Now, as the next step | Mirrors how 04.1 was inserted | ✓ |
| First Phase 6 plan task | Phase 6 planned against a stale roadmap entry | |
| Defer — plan Phase 6 only | Coverage matrix won't reconcile | |

**Q: How are success criteria rewritten after the split?**

| Option | Description | Selected |
|--------|-------------|----------|
| Redistribute, no new claims | Reconciles item for item against the original seven | |
| Rewrite per phase from the decisions | More specific and testable; mapping must be documented | ✓ |

**Q: Is the prompt precedence change a schema change?**

| Option | Description | Selected |
|--------|-------------|----------|
| Prompt text only, schema untouched | D-28 and D-01 both hold | ✓ |
| Prompt + schema field for precedence | Reopens the locked generation contract | |

---

## Test strategy & operational surface

**Q: How are degraded paths tested?**

| Option | Description | Selected |
|--------|-------------|----------|
| Extend the cfg(test) fake-port seam | Reuses the Phase 05 pattern; no production surface | ✓ |
| Runtime fault-injection config | A "break yourself" switch in production code | |
| Fakes plus one live scenario | Adds a staged live failure for screenshots | |

**Q: docker-compose grows to six containers against the local-first constraint.**

| Option | Description | Selected |
|--------|-------------|----------|
| Compose profiles | Core (Postgres) vs observability profile | ✓ |
| One stack, all up | Contributors pay for five unneeded containers | |
| Separate observability compose file | Two files to keep in sync | |

**Q: How are Grafana dashboards provisioned?**

| Option | Description | Selected |
|--------|-------------|----------|
| Provisioned from committed JSON | — | |
| Datasources provisioned, dashboard manual | Fresh clone shows empty Grafana | |
| No Grafana config, screenshots only | Observability claim unverifiable | |
| **Observability as code** | User-specified: everything deterministic and committed | ✓ |

**Q: How are dashboards authored?**

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-authored JSON, provisioned | Tolerable now, unpleasant as it grows | |
| Generated from code, committed output | Dashboards become reviewable code | ✓ |
| Export-from-UI, committed | Snapshot of exactly the manual state to avoid | |

**Q: How far does "observability as code" reach?**

| Option | Description | Selected |
|--------|-------------|----------|
| All configs committed, no alerting | No on-call, nowhere to route alerts | ✓ |
| All configs + alert rules as code | Documents SLO thinking | |
| All configs + alerts + recording rules | Optimizes nothing at local cardinality | |

**Q: New config knobs on a settings surface with a known defect?**

| Option | Description | Selected |
|--------|-------------|----------|
| New knobs fail closed, old ones unchanged | Contains the defect without reopening a deferred item | ✓ |
| Accept it, note the growth | Telemetry could silently stop working | |
| Pull the settings fix into Phase 6 | Deliberate scope exception | |

**Q: Does Phase 6 own v1 milestone closure?**

| Option | Description | Selected |
|--------|-------------|----------|
| Phase closes, milestone separate | Keeps criteria about work, not paperwork | |
| Phase 6 owns milestone closure | One pass, nothing forgotten between steps | ✓ |

**Q: DEBT-P3-MODULE-GRAPH, given five phases of new engine code on that seam?**

| Option | Description | Selected |
|--------|-------------|----------|
| New code lives in lib, binary imports it | Shrinks the drift surface at no cost | |
| Accept, note the trigger fired | Drift surface grows across five phases | |
| Close it in Phase 6 | Deliberate exception to ROADMAP-named-only scope | ✓ |

**Q: Where does the module-graph restructure sit?**

| Option | Description | Selected |
|--------|-------------|----------|
| First in Phase 6, before new code | Pure-refactor plan with the 285-test suite as safety net | ✓ |
| Last in Phase 6, after behavior | Has to move code written during the phase | |
| Its own phase before 6 | A sixth boundary for a refactor | |

**Q: Does the Go gateway get restructured too?**

| Option | Description | Selected |
|--------|-------------|----------|
| Extract packages as work lands | Lower risk, incremental | |
| Restructure first, like the engine | Symmetric treatment, clean foundation | ✓ |
| Leave it, keep adding to main.go | Grows past 1,500 lines with telemetry | |

**Q: Span and metric naming?**

| Option | Description | Selected |
|--------|-------------|----------|
| Semconv where it exists, domain elsewhere | Interoperable without contorting Lancet's concepts | ✓ |
| Domain-first naming throughout | Discards gen_ai.* interoperability | |
| Strict semconv only | Leaves fusion/graph/degraded uninstrumented | |

**Q: Service identity in telemetry?**

| Option | Description | Selected |
|--------|-------------|----------|
| lancet-gateway / lancet-engine + version | Traces attributable to a specific build | ✓ |
| Service names only | Can't tie a trace to a build | |

**Q: Does Phase 6 add CI?**

| Option | Description | Selected |
|--------|-------------|----------|
| No CI, document the gate commands | Consistent with local-first and prior phases | ✓ |
| Minimal CI: build + test | Postgres-gated tests need a service container | |
| CI including deterministic eval | Real infrastructure work on a large phase | |

---

## Claude's Discretion

The user did not select a "you decide" option on any question. Discretion items in CONTEXT.md
were derived from decisions that fixed semantics without fixing implementation:

- Rust and Go module/package layout produced by the restructures
- Protobuf field numbers, message shapes and enum value names in the consolidated contract change
- Configuration key names for the new telemetry, model-only, rebuild-debounce and eval knobs
- Grafana Foundation SDK vs grafonnet for dashboard generation
- Notice code string values beyond the fixed semantics
- Debounce window for rebuild coalescing
- MultiHop-RAG document-subset selection algorithm (must be documented)
- Internal structure of the `eval/` package and its report schema

## Deferred Ideas

- Automatic RAG-vs-model routing — the system deciding per question whether retrieval is needed
- LLM-generated + human-reviewed supplementary eval items
- The evidence-vs-model-priors eval metric (deferred with the generated set)
- Weak-evidence scoring band / calibrated fusion-score threshold (explicitly dropped)
- Threshold-gated eval with a pass/fail exit code
- Alert rules and Prometheus recording rules
- CI (`.github/workflows`), including deterministic eval metrics
- Gateway HTTP server timeouts and bounded upload semaphore (DEBT-CR-05 criteria)
- Auth, authorization, TLS ingress, per-principal quotas (DEBT-CR-04 criteria)
- Identity-only structured logging with no raw provider detail (DEBT-D1-SAFE-LOG — trigger fired)
- Multi-provider / backup-model generation fallback (descoped by Phase 05 D-14)

## Superseded During Discussion

Recorded so the reasoning trail stays legible:

1. **Corpus choice** — "public QA benchmark subset" → 2WikiMultihopQA → **MultiHop-RAG** (main,
   ~500 sampled) **+ GraphRAG-Bench Novel** (optional supplement). User-directed reversal.
2. **Rust OTel approach** — "move all implementation to OTel SDK entirely" → **bridge
   architecture** (`tracing-opentelemetry` + `opentelemetry-appender-tracing` + Meter API), after
   the double-duty role of `tracing` as logging facade was flagged.
3. **Evidence-vs-priors enforcement** — "prompt contract + eval metric" → **prompt contract, metric
   deferred**, once the generated test set was deferred.
4. **DEBT-D1-SAFE-LOG** — dispositioned to backlog, then re-raised when the decision to export
   full engine logs to Loki made its trigger unambiguous. **Re-confirmed** as backlog, local-only.
5. **Phase shape** — one phase → **five phases (6, 6.1, 6.2, 6.3, 6.4)** under one governing
   CONTEXT.md.
