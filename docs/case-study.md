[← Back to README](../README.md)

# Case Study: Building a RAG Engine You Can Believe

This page is the interview version of Lancet. It covers what I set out to prove, the moment the project nearly
published a wrong result, the calls that shaped the system, and how I directed AI coding agents across 250 plans
without losing control of quality. Each section links to the deeper record.

## The goal

Most RAG projects wrap a framework and call an API. They hide the parts that decide whether a system holds up: data
layout, retrieval fusion, timeouts, failure handling, and whether the benchmark measures what it claims to.

Lancet builds that data plane from scratch and treats evaluation as a product requirement:

- **Built from scratch, in Rust.** Chunkers, index lifecycle, hybrid retrieval and fusion, graph seeding and path
  search, prompt assembly, and the orchestrator.
- **Bought where it's a commodity.** PostgreSQL, LanceDB, OpenTelemetry, Jaeger, Prometheus, Loki, Grafana and
  OpenRouter.
- **The proof.** A benchmark harness whose results hold up, including the negative ones.

## The run I refused to publish

On 2026-09-03 the first full benchmark run finished. The report said **1,000 successful queries** and a **positive
graph effect**. It looked like the headline result.

The harness's own provenance checks said otherwise:

| What the report said | What was true |
|---|---|
| 1,000 successful queries | **966** of the 1,000 answers were empty |
| Retrieval completed | **904** queries were clipped at a retrieval timeout |
| The graph helps | the two arms being compared shared **1.6%** of their questions |

**Root cause.** The node timeouts were guesses taken from unit tests, and they were far too tight for multi-hop
search over a real corpus. A stream-truncation bug in the gateway then recorded the aborted runs as successes. On top
of that, the comparison wasn't paired, so the arms were measured on different questions.

**Fix.** I didn't tune until the numbers looked better. I opened a family of phases (06.3.1 to 06.3.4.1) to make the
signal trustworthy first:

1. **Fail-closed reporting.** An incomplete journal can't be published as complete.
2. **Paired, per-question comparison.** Every arm runs the same questions, with exact paired tests and Holm
   correction.
3. **Measured timeout budgets.** Budgets come from a censoring-aware p95 measurement. The old budgets clipped 90% of
   queries.
4. **Pre-registered gates.** Each gate is committed to git before the paid run it judges, and the harness checks
   that the commit is older than the run.
5. **Graph retrieval redesign.** Graph presence went from **9.8% to 66%**, using question-mention seeding and
   degree-capped seed-to-seed path search.

**Outcome.** Three runs of record with modest numbers I trust. The forensic trail is
[`06.3.1-ROOT-CAUSE.md`](../.planning/phases/06.3.1-fix-retrieval-citation-collapse-and-graph-ablation-measureme/06.3.1-ROOT-CAUSE.md),
and the public note is [`evaluation-fidelity-and-graph-yield.md`](evaluation-fidelity-and-graph-yield.md).

## What the trustworthy numbers said

All readings are on held-out data, each paired against plain hybrid retrieval on the same day
([full tables](evaluation.md)):

- **Rerank:** about **+16 points Hits@4** and **+8 points `answer_usable`**, Holm-significant. It ships on by
  default.
- **Evidence metadata** (title, source and date headers on each evidence block): about **+6 points**,
  significant. It ships on by default.
- **Knowledge graph:** built, observable, and costs about +199 prompt tokens per request, with **no significant
  gain**. Neither did graph-v2, the repair a per-question diagnosis chose. **The graph ships off**, and a request can
  turn it on.

Shipping the headline feature turned off was the hardest call in the project. It was also the right one: a
default should follow the evidence, not the plan.

## Design calls worth discussing

Each of these has a full write-up with the alternatives in the [design narrative](design-narrative.md).

| Call | Instead of | Why |
|---|---|---|
| Go gateway + Rust engine over gRPC | one language | keeps control-plane concerns out of the latency-sensitive data plane, behind an explicit, typed boundary |
| Embedded LanceDB for vectors **and** graph | pgvector, Qdrant, Neo4j | local-first, Arrow-native, no extra service; the graph is two tables beside the chunks |
| A 5-node Rust state machine | LangGraph, Dify | keeps the useful ideas (timeouts, retries, checkpoints, typed events) at a finishable scope |
| Weighted RRF with documented tie rules | a framework's retriever | the graph joins fusion as a third ranked list instead of replacing retrieval |
| Degraded modes as typed wire notices | silent fallbacks | 18 notice codes; a client can always tell what the system did not do, and model-only answers fail closed |
| Index rebuild-and-swap | in-place writes | a query never reads a half-built index |
| Levers measured as arms, defaults by a pre-registered rule | tuning by eye | each lever is developed on dev, read once on held-out, and becomes a default only on a significant gain |

## Shipping with a debt ledger

Phases 2 and 3 hit their schedule with gaps still open. I didn't let the gaps block progress, and I didn't let them
silently disappear: each one became a named `DEBT-*` item and was carried forward
([ADR-02-004](../.discussion/decisions/phases/02/2026-07-30-ADR-02-004-all-the-way-to-ship-mvp.md),
[ADR-03-003](../.discussion/decisions/phases/03/2026-08-05-ADR-03-003-all-the-way-to-ship-mvp.md)). Phases 6 and 6.1
paid most of it down, and v1 closed with the rest promoted to themed backlog phases. The full list is in
[limitations](limitations.md).

## Directing AI agents at scale

Every plan was planned and executed with AI coding agents (the GSD methodology, run with Claude Code). The full trail
is under [`.planning/`](../.planning): each phase has a PLAN, SUMMARY, VERIFICATION, code review, security audit and
UAT record.

The agents wrote code; I set direction and held the gates:

- **Explicit verification gates.** No phase closes without its verification, review and UAT records. The local test
  gates pin the number of test functions per target, so a test that stops compiling fails the gate instead of
  vanishing from a total.
- **Judgement the agents couldn't make.** Refusing the first run, shipping the graph off, accepting rerank's latency
  cost by owner decision with the caveat published, and force-closing phases with a ledger.
- **A reproducible end state.** The quickstart was followed verbatim from a fresh clone on Windows and on WSL, and
  both transcripts are committed.

| Scale | |
|---|---|
| Phases / plans | 18 / 250 |
| Duration | 2026-07-13 to 2026-10-11 |
| Tests | 963 Rust, 124 Go, 2,357 Python |
| Commits | about 1,900 |

The per-phase timeline is in [build history](build-history.md).

## What I'd do next

- **A local inference endpoint.** It would make the LLM provider a controlled variable; OpenRouter re-routed a model
  mid-run once.
- **The shipped default as one arm.** Rerank and metadata were each measured alone, never together, so measure them
  as a single arm.
- **A fresh judge calibration.** The LLM judge failed human calibration, so no judged score counts as a v1 finding.
- **Global GraphRAG (community summaries).** This needs a benchmark that asks community-level questions, which
  MultiHop-RAG doesn't.
