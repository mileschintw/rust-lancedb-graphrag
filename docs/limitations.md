[← Back to README](../README.md)

# Limitations, Debt and Backlog

What v1 does not do, what it does not measure, and where the open debt went. The README keeps one line on this;
this page holds the full list.

## Honest limitations

* **Local-only by design.** There is no end-user identity, authentication, access control, TLS, quota or per-principal rate limiting; a `session_id` groups requests and authenticates nobody. The listeners bind to loopback. `DEBT-CR-04`'s trigger conditions, [below](#local-only-exposure-constraint-debt-cr-04), say what must not happen before that is revisited (06-CONTEXT D-06).
* **Committed local-dev credentials.** The Postgres (`postgres`/`postgres`) and Grafana (`admin`/`admin`) logins are committed local-dev credentials. They are fine on loopback and wrong anywhere else.
* **A fired debt trigger kept in backlog.** `DEBT-D1-SAFE-LOG` names a shared log sink as its trigger, and that trigger fired when Phase 6.2 began exporting full engine logs to Loki. It stays in backlog because Loki runs in the same local compose, for one user, bound to loopback (06-CONTEXT D-09).
* **The open debt is in backlog, by theme.** The debt v1 did not pay is promoted to backlog phases with these names: 999.13 Security and transport hardening, 999.14 Ingestion and staging robustness, 999.15 Config and settings hygiene, 999.16 API contract and DX, and 999.17 Test and evidence hygiene. Two more hold the 06.3.6 review carry-forwards: 999.18, eval-harness provenance and protocol hardening, and 999.19, engine, gateway and test robustness. They are listed in the [ROADMAP backlog](../.planning/ROADMAP.md#backlog).
* **What the evaluation stands on.** Every reading is on one corpus (MultiHop-RAG: a 346-document subset of mostly two-document news questions), one generation model from one provider, and one seed, and the null-abstention guard rests on n = 43 unanswerable questions. The models are pinned, paid OpenRouter models, not free-tier ones: `deepseek/deepseek-v4-flash-0731` for generation, `voyageai/voyage-4-large` for embeddings and `voyageai/rerank-2.5-lite` for rerank. A default chosen here is a statement about this system on this population. How the evaluation was made trustworthy in the first place is in [`docs/evaluation-fidelity-and-graph-yield.md`](evaluation-fidelity-and-graph-yield.md).
* **What it does not measure.** The evidence-vs-priors claim, that the generator prefers retrieved evidence over its own knowledge, is enforced by the prompt contract but ships unmeasured (06-CONTEXT D-17, D-45). Chunking strategy (fixed-size against structure-aware) is unmeasured, and so are community-level questions, which MultiHop-RAG does not ask. The shipped default, rerank and metadata together, was never measured as one arm; the only evidence about combinations is a descriptive arm that also carries the two levers that stayed off.
* **The graph costs without a measured gain.** On held-out, `hybrid+graph` read -0.0101 on `answer_usable` against `hybrid`, not significant, and it adds prompt tokens and retrieval time on every graph request ([graph cost](evaluation.md#graph-cost-reconciled)). Its paths often find nothing on this benchmark: `GRAPH_UNAVAILABLE` ("graph query returned no facts") appears on about 42% of graph-arm records. Before the redesign, Phase 06.3.3 measured the graph's hub expansion at tens of seconds and raised the budget rather than hide the cost ([`06.3.3-BUDGETS.md`](../.planning/phases/06.3.3-retrieval-latency-measurement-pass-and-timeout-budget-deriva/06.3.3-BUDGETS.md)); Phase 06.3.4.1 replaced that design, and its figures do not compare with today's.
* **Two levers stayed off, with their readings.** graph-v2, the graph repair chosen by diagnosis, read -0.0195 on `answer_usable`, not significant. The answer-format lever read -0.0423, on the harmful side, and not significant after correction. Both are built and can be named per request; neither is a default ([`06.3.6-CLOSEOUT.md`](../.planning/phases/06.3.6-quality-levers-measured-as-arms-reranker-graph-repair-by-dia/06.3.6-CLOSEOUT.md)).
* **The judge is uncalibrated.** The LLM-as-judge groundedness and faithfulness scores failed their human calibration, so no judged figure is a v1 finding, and the results page labels the judged rows as not findings. A fresh calibration and the judge's carry-forwards move to `v1.1` (Phase 06.3.6 D-153, Phase 06.4 D-208).
* **Rerank latency.** Rerank is on by default by an owner decision rather than by the pre-registered rule, because its latency-flatness gate missed: the rerank provider drifted into a slow mode partway through the drive. Every request that names no lever pays a rerank call, and in that slow mode it can pay up to the 2,286 ms rerank budget. The slow mode was seen once, on that drive.
* **The LLM provider is not a controlled variable.** OpenRouter may route a model across providers mid-drive, and did once; a local inference endpoint is a backlog item.
* **Accepted v1 residual debt.** Open review findings and ledger rows that no Phase 6.4 decision covers are accepted as listed v1 residual debt, recorded by source in [`06.4-CLOSURE.md`](../.planning/phases/06.4-docs-suite-verified-quickstart-debt-backlog-promotion-and-v1/06.4-CLOSURE.md#v1-residual-debt-d-229) (D-229).

## Local-only exposure constraint (`DEBT-CR-04`)

> [!IMPORTANT]
> **Local-Only Service Scope**
> The Go API Gateway listener binds explicitly to loopback (`127.0.0.1:<port>`). This is a standing v1/local-first constraint, not scoped to any single phase — trusted local callers only. The service is unauthenticated and lacks TLS or per-principal rate limiting. Reviewed and documented as accepted in Phase 6.1; it stays open and accepted for v1.

### Review & Reclassification Triggers (`DEBT-CR-04`)
The local-only disposition must be immediately reviewed and reclassified as blocking before any of the following deployment changes occur:
- Binding the gateway or engine listeners to a non-loopback interface (`0.0.0.0` or shared network adapter)
- Exposing the service via reverse proxy, tunnel, port forwarding, or shared LAN access
- Deploying into multi-tenant, container-host, VM-host, remote, or cloud environments
- Allowing external or automated untrusted callers to submit document ingestion requests


## Backlog and extension points

The backlog is in [`.planning/ROADMAP.md`](../.planning/ROADMAP.md#backlog); the 2026-10-06 triage is in [`NEXT-STEPS-2026-10-06.md`](../.planning/research/NEXT-STEPS-2026-10-06.md#3-backlog-triage).

**Built in v1 from the backlog:**
1. **Reranking (999.2)** — shipped as the `rerank` lever, default-on.
2. **Entity resolution, lite (999.6)** — considered for Phase 06.3.6, but the no-path diagnosis selected graph-list precision (graph-v2) instead, so it was not built.

**Debt themes promoted at v1 close:** 999.13 Security and transport hardening, 999.14 Ingestion and staging robustness, 999.15 Config and settings hygiene, 999.16 API contract and DX, 999.17 Test and evidence hygiene, 999.18 eval-harness provenance and protocol hardening, and 999.19 engine, gateway and test robustness.

**`v1.1` candidates:**
3. **Local inference endpoint (999.11)** — an OpenAI-compatible local endpoint so the provider becomes a controlled variable; a local rerank endpoint would also remove the rerank latency caveat.
4. **Measuring the shipped default** — rerank plus metadata as one decisional arm, and a fresh judge calibration.
5. **Query reformulation strategies (999.3)** — HyDE and multi-query as additional arms; the `reformulate` node and multi-variant fusion already exist. One direction for the graph, with no promise attached.
6. **S3-compatible storage for LanceDB (999.8)**.

**v2:**
7. **Community summaries (999.1), compile-time node semantics (999.5), ingestion-time synthesis (999.4)** — global GraphRAG, the other direction for the graph; it needs a benchmark with community-level questions.
8. **Knowledge drift detection and LLM-verified node merging (999.6, full)**, **Rayon CPU isolation (999.7)**, **LLM wiki second brain (999.9)**, **session memory in LanceDB (999.10)**, **PageIndex retrieval (999.12)**.
