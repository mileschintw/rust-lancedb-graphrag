# Lancet 🚀

> [!NOTE]
> **Project Status (2026-10-06): v1 engineering complete through Phase 06.3.4.1 — evaluation closure in progress, docs phase parked.**
> 192 plans have been executed across 15 completed phases (Phases 1–5, Phase 04.1, and the Phase 6 family 6, 6.1, 6.2, 6.3, 6.3.1–6.3.4.1). A Go API gateway, a Rust RAG/GraphRAG engine, a full OpenTelemetry stack and a Python evaluation harness exist and are tested in this repository — see [`gateway/`](./gateway), [`engine/`](./engine), [`proto/`](./proto), [`deploy/`](./deploy) and [`eval/`](./eval). The validated run of record is [`eval/runs/2026-10-06-drive2-multihop_rag_diag/`](./eval/runs/2026-10-06-drive2-multihop_rag_diag). Two evaluation phases (06.3.5 retrieval ablation matrix, 06.3.6 quality levers) are planned next; the docs-and-closure phase (6.4) stays parked until they publish. The honest headline so far: **the graph path works mechanically and buys no measurable answer quality yet** — see [Evaluation results](#-evaluation-results-so-far).

**Lancet** is an end-to-end, systems-oriented Retrieval-Augmented Generation (RAG) and GraphRAG platform. It is built to show data-plane engineering depth and evaluation discipline: a Go control plane and a Rust data plane joined by gRPC, custom chunking, hybrid dense + BM25 + graph retrieval over embedded LanceDB, a lightweight Rust state machine with degraded modes, production-style observability, and a benchmark harness whose results can be believed — including when they are negative.

---

## 📖 The Story & Motivation

Most RAG applications are built on high-level orchestration frameworks and pre-packaged API wrappers. That is convenient, and it hides the data-plane complexity, the database access patterns and the performance characteristics that decide whether a system holds up.

Lancet builds the core data plane from scratch instead: custom chunkers, index lifecycle, hybrid retrieval and fusion, graph seeding and path search, prompt assembly and a state-machine orchestrator in **Rust**, behind a lightweight **Go** gateway, with **gRPC/Protobuf** as the boundary. Mature tools are used where they are commodity — PostgreSQL, LanceDB, OpenTelemetry, Jaeger, Prometheus, Loki, Grafana, OpenRouter — and rebuilt where building them demonstrates understanding.

The second half of the project is the way it was built. All 192 plans were planned and executed with an AI-agent-assisted workflow (the GSD methodology, run with Claude Code), and the trail is under [`.planning/`](.planning): every phase has its PLAN, SUMMARY, VERIFICATION, code review, security audit and UAT record. This is human-directed collaboration, not autonomous authorship. The human part is directing, reviewing, holding the agent to explicit verification gates, and making the calls it cannot make. Two kinds of call stand out:

- **Force-closing on schedule with a debt ledger.** [ADR-02-004](.discussion/decisions/phases/02/2026-07-30-ADR-02-004-all-the-way-to-ship-mvp.md) and [ADR-03-003](.discussion/decisions/phases/03/2026-08-05-ADR-03-003-all-the-way-to-ship-mvp.md) closed Phases 2 and 3 with their remaining gaps named as `DEBT-*` items and carried forward, rather than letting them block progress or silently drop. Phases 6 and 6.1 then paid most of that debt down.
- **Refusing a result that looked good.** The first full benchmark run (2026-09-03) reported 1,000 successful queries and a positive graph effect. The harness's own provenance checks showed that 966 of the 1,000 answers were empty, 904 queries had been clipped at a retrieval timeout, and the ablation delta had been computed over two arms that shared 1.6% of their questions. That finding spawned the 06.3.1–06.3.4.1 family: fail-closed reporting, paired per-question ablation, censoring-aware latency measurement and derived timeout budgets, pre-registered gates committed before each paid drive, and a graph-retrieval redesign — ending in a run of record whose numbers are modest and trustworthy. The forensic trail is [`06.3.1-ROOT-CAUSE.md`](.planning/phases/06.3.1-fix-retrieval-citation-collapse-and-graph-ablation-measureme/06.3.1-ROOT-CAUSE.md) and the public note is [`docs/evaluation-fidelity-and-graph-yield.md`](docs/evaluation-fidelity-and-graph-yield.md).

---

## 🎯 Architecture

```mermaid
graph TD
    User([User / Client]) -->|HTTP REST + SSE| GoGateway[Go API Gateway <br> Control Plane]
    GoGateway -->|gRPC / Protobuf| RustEngine[Rust RAG Engine <br> Data Plane]

    subgraph Control Plane Storage
        GoGateway -->|SQL via Atlas-managed schema| Postgres[(PostgreSQL <br> Documents, Sessions, Workflow Checkpoints)]
    end

    subgraph Data Plane Components
        RustEngine --> Chunker[Custom Chunker <br> fixed-size + Markdown structure-aware]
        RustEngine --> Store[LanceDB <br> chunks + vectors, rebuild-and-swap index]
        RustEngine --> GraphStore[LanceDB entities / entity_edges <br> seeding + bounded path search]
        RustEngine --> Retriever[Hybrid Retriever <br> dense + BM25 + graph list, weighted RRF]
        RustEngine --> Orchestrator[Rust State Machine <br> 5 nodes, timeouts, retries, degraded modes]
        RustEngine -->|HTTPS| LLM[OpenRouter <br> embeddings + chat]
    end

    subgraph Observability
        GoGateway -.->|OTLP| Collector[OTel Collector]
        RustEngine -.->|OTLP| Collector
        Collector -.-> Jaeger[(Jaeger <br> traces)]
        Collector -.-> Prometheus[(Prometheus <br> metrics)]
        Collector -.-> Loki[(Loki <br> logs)]
        Jaeger & Prometheus & Loki -.-> Grafana[Grafana <br> provisioned dashboard, trace↔log links]
    end

    subgraph Evaluation
        Eval[lancet-eval <br> Python / uv harness] -.->|/rag/query, two arms| GoGateway
        Eval -.->|LLM-as-judge| LLM
    end
```

### What is built

1. **Go API Gateway (control plane, [`gateway/`](./gateway)).** HTTP REST server with document upload and ingestion, the `/rag/query` endpoint streaming workflow events over SSE, graph query, session handling, PostgreSQL persistence for documents, sessions and workflow checkpoints (Atlas-managed schema, separate `local` and `eval` environments), graceful shutdown that drains buffered checkpoints, and an OTel pipeline with a rate-limited exporter error handler. The listener binds to loopback only (see [Local-only constraint](#-local-only-exposure-constraint--debt-triggers-debt-cr-04)).
2. **Rust RAG Engine (data plane, [`engine/`](./engine)).** An asynchronous gRPC server implementing:
   - **Ingestion and chunking.** Markdown, plain text and JSON sources; fixed-size and Markdown structure-aware chunkers; embeddings via OpenRouter; staged writes with an index **rebuild-and-swap** lifecycle and cross-index corpus generation so a query never reads a half-built index.
   - **Hybrid retrieval.** Embedded LanceDB dense search, a local BM25 lexical index, metadata filtering, deduplication and deterministic weighted Reciprocal Rank Fusion with documented tie rules; multi-variant reformulation fusion; a `Reranker` port with a pass-through default.
   - **GraphRAG.** Entity and relation extraction at ingestion into `entities` / `entity_edges` LanceDB tables; at query time, model-free mention extraction, seed matching (exact name, normalised name, then name-vector nearest neighbour), bounded seed-to-seed one- and two-hop path search with a degree cap derived from the store's p99, path facts injected into the prompt under a token-budget-derived cap, and the path entities' source chunks fused as a third RRF list. Cypher-style pattern queries via `lance-graph` for the graph API.
   - **Orchestration.** A five-node state machine (reformulate → retrieve hybrid → extract graph context → assemble prompt → generate answer) with per-node timeouts derived from measured p95s, retries, cancellation, PostgreSQL-backed checkpoints with strict FIFO drain, and typed client-facing events.
   - **Degraded modes as contract, not accident.** Every fallback is a typed notice on the wire: `NO_EVIDENCE`, `GRAPH_TIMEOUT`, `GRAPH_DEGRADED`, `GRAPH_UNAVAILABLE`, `RETRIEVAL_DEGRADED_DENSE`, `RETRIEVAL_FAILED`, `CITATION_REPAIRED`, `CITATION_DROPPED`, `MODEL_ONLY`, `BASIS_RECONCILED`, `GRAPH_ABLATION`, `INDEX_STALE`, `INDEX_GENERATION_MISMATCH`, among others. Model-only answers are opt-in and fail closed by default. Citation repair never ships an excerpt the model did not see.
3. **gRPC contract ([`proto/`](./proto)).** The Protobuf boundary between the two services, including the per-request ablation flag the evaluation harness uses.
4. **Observability ([`deploy/`](./deploy), `docker-compose.yml`).** OpenTelemetry traces, metrics and structured logs from both services through an OTel Collector to Jaeger, Prometheus and Loki, with a provisioned Grafana dashboard (`histogram_quantile` latency panels, trace-to-log correlation via `trace_id`). Ingestion is traced end to end through chunking, embedding, graph extraction and index swap.
5. **Evaluation harness ([`eval/`](./eval), `lancet-eval`).** A `uv`-managed Python package that drives the gateway as a black box over the MultiHop-RAG benchmark with two arms per question (graph-on, graph-off), journals every attempt with provenance, computes deterministic retrieval and answer metrics without an LLM, runs cached LLM-as-judge groundedness and faithfulness scoring with a human calibration path, enforces per-stage spend caps reconciled against the provider account, refuses to publish an incomplete journal as complete, and reads pre-committed gates. Isolated from the dev stack by a separate LanceDB path and PostgreSQL schema.

Tests: roughly 700 Rust, 120 Go and 1,000+ Python test functions, all runnable offline except the explicitly live-evidence suites.

---

## 📊 Evaluation results so far

The run of record is [`eval/runs/2026-10-06-drive2-multihop_rag_diag/`](./eval/runs/2026-10-06-drive2-multihop_rag_diag) (full readings and the decision record in [`06.3.4.1-RUN-OF-RECORD.md`](.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/06.3.4.1-RUN-OF-RECORD.md)). It is a 100-question diagnostic sample of MultiHop-RAG (90 answerable, 10 unanswerable) over a 346-document index, two arms per question, generation by `deepseek/deepseek-v4-flash-0731` and embeddings by `voyageai/voyage-4-large` through OpenRouter.

| What was measured | Reading | Notes |
|---|---|---|
| Hybrid retrieval latency (node, on the wire) | p50 116 ms, p95 166 ms | flat across the drive; slope −0.02 ms/query |
| Graph path found (graph-on, answerable pairs) | 59 / 89 = 0.66 | Wilson 95% CI [0.56, 0.75]; zero `GRAPH_TIMEOUT` |
| Graph changed the final retrieved set | 35 / 65 = 0.54 of gold-in-vector pairs | pre-committed floor 0.10 |
| Answer usable, graph-off (answerable) | 52 / 90 = 0.58 | by type: inference 0.90, comparison 0.58, temporal 0.13 |
| Paired delta, graph-on − graph-off, `answer_usable` | −0.03 | 95% CI includes 0 |
| Paired delta, ranking quality | −0.08 | 95% CI excludes 0 (negative) |
| Graph cost per query | +1.2 to +1.6 s, +210 prompt tokens | 95% CIs exclude 0 |
| Abstention on unanswerable questions | 9 / 9 | both arms |
| Drive spend | $0.07 of a $0.91 pre-authorised cap | reconciled against the provider account |

What this says, plainly: the pre-registered gates passed with margin, the measurement is trustworthy, the graph path is mechanically alive, and **on this benchmark the graph does not yet improve answers**. Three disclosures stand with the result and are not toggled off: the negative but non-significant quality deltas with a real latency and token cost, a mid-drive provider switch that was not a controlled variable, and a small graph-off retrieved-set difference against the previous drive of undetermined cause.

What has **not** been measured yet, and is the subject of the next two phases:

- Standard-RAG baselines. Dense-only, BM25-only and hybrid have never been compared; the contract's only ablation flag is the graph one.
- LLM-judged faithfulness and groundedness, and a human-calibrated slice. The machinery exists; the pass has not been run on the repaired system.
- Anything on a sample larger than 100 questions on the repaired system. Confidence intervals are about ±10 points.
- Chunking strategy comparison (fixed-size versus structure-aware).

The 2026-09-03 and 2026-09-09 runs under `eval/runs/` are retained as superseded evidence; their numbers are not comparable to the run of record and say so in their markers.

---

<!-- quickstart:start -->
## 🚀 Quickstart (Windows native and Linux via WSL)

> Verified on a fresh clone: Windows 11 native on 2026-10-11 at commit 1c000271 (06.4-QS-TRANSCRIPT-WINDOWS.md); WSL Ubuntu 24.04 on 2026-10-11 at commit 752c8ae0 (06.4-QS-TRANSCRIPT-WSL.md).

This takes a clean clone to a traced answer over a five-document sample, on Windows native and on Linux inside WSL. Both platforms run the same commands; where a shell differs, both variants are shown. Run every command from the repository root unless a step says otherwise. The only thing you supply is an OpenRouter API key.

### Prerequisites

| Need | Windows (PowerShell) | WSL Ubuntu 24.04 |
|---|---|---|
| Docker | Docker Desktop | Docker Desktop with WSL integration enabled |
| Rust | cargo 1.95 | cargo 1.95 |
| `protoc` | on `PATH` | `protobuf-compiler` (below) |
| Go | 1.25 or later | 1.26.5 official tarball (below) |
| Atlas | on `PATH` | official installer (below) |
| uv | on `PATH` | `~/.local/bin/uv` |
| Git | on `PATH` | on `PATH` |
| Chrome and Node 22+ | only for the optional screenshot scripts | not needed |

On WSL, install the system packages, the pinned Go toolchain and Atlas once. Any Go 1.25 or later works; 1.26.5 is the toolchain the Windows run uses.

```bash
sudo apt-get install -y pkg-config libssl-dev protobuf-compiler
curl -fsSLo /tmp/go1.26.5.linux-amd64.tar.gz https://go.dev/dl/go1.26.5.linux-amd64.tar.gz
sudo rm -rf /usr/local/go
sudo tar -C /usr/local -xzf /tmp/go1.26.5.linux-amd64.tar.gz
curl -sSf https://atlasgo.sh | sh
```

A non-login WSL shell does not have uv, cargo or Go on its `PATH`, so add them in every terminal:

```bash
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/go/bin:$PATH"
```

### Steps

**1. Clone.** It must be a full clone: never use `--depth`. The offline re-score in step 13 checks git history (a pre-registration commit has to be older than the run it scores), and a shallow clone makes `score` refuse. `git fetch --unshallow` repairs a shallow one.

```bash
git clone https://github.com/mileschintw/rust-lancedb-graphrag.git lancet-qs
cd lancet-qs
```

The compose commands below all pass `-p lancet-qs`, so the quickstart never shares volumes with a dev stack you already run. Container names and loopback ports are fixed, though, so stop a running Lancet dev stack first (`docker compose -p lancet down`, without `-v`).

**2. Set the key and export `.env`.** `.env.example` holds an empty `OPENROUTER_API_KEY=`; copy it to `.env`, fill in the key and export the file into the current shell. Nothing loads `.env` by itself, and `.env` is gitignored. Every new terminal repeats the export.

```bash
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY
set -a; . ./.env; set +a
```

```powershell
Copy-Item .env.example .env
# edit .env and set OPENROUTER_API_KEY
Get-Content .env | % { if ($_ -match '^\s*([^#=\s]+)\s*=\s*(.*)$') { Set-Item "env:$($Matches[1])" $Matches[2].Trim('"') } }
$env:PYTHONUTF8 = "1"
```

The last PowerShell line makes Windows Python read text as UTF-8 instead of the system codepage (cp950 on one machine this was tried on); without it, scores do not match across platforms. The Postgres (`postgres`/`postgres`) and Grafana (`admin`/`admin`) logins used below are committed local-dev credentials, not secrets.

**3. Start the infrastructure.**

```bash
docker compose -p lancet-qs --profile observability up -d
```

The `observability` profile is what starts Jaeger, Prometheus, Loki, the OpenTelemetry collector and Grafana. Without it only Postgres starts.

**4. Apply the database schema.**

```bash
cd gateway
atlas schema apply --env local --auto-approve
cd ..
```

**5. Config.** `config/config.toml` is tracked and carries the shipped defaults, so nothing is copied over it.

**6. Start the engine** in its own terminal (repeat the step 2 export there). The first build takes about 20 minutes on a cold clone. The engine crate holds several binaries, so `--bin engine` names the one to run.

```bash
cargo run --manifest-path engine/Cargo.toml --release --bin engine
```

The engine also logs many `lance::` dataset lines. Filtered, a start over the empty store prints these, in this order (`build_ms` varies):

```
 INFO engine: telemetry_mode telemetry_mode="otlp" endpoint=http://127.0.0.1:4317
 INFO engine: BM25 snapshot built document_count=0 generation=lance-1 nodes_version=1 graph_entities=0 doc_meta_documents=0
 WARN engine: configured default lever is unavailable: a request that names no lever runs without it and carries a DEFAULT_LEVER_UNAVAILABLE notice; apply the remedy or set [engine.levers] defaults = [] to start lever-free lever="evidence_metadata" reason="the corpus snapshot holds no document metadata" remedy="ingest documents with doc_title, source or published_date, or run `backfill_evidence_metadata`; a legacy 19-column store runs `--migrate-only` first"
 INFO engine: Prompt tokenizer ready tokenizer="cl100k_base" build_ms=224.369 sample_tokens=10
 INFO engine: Staged ingestion jobs replayed replayed_jobs=0
 INFO engine: Rust RAG Engine serving addr=127.0.0.1:50051 build_profile="release" log_filter=info,engine=debug
```

The WARN is expected: the committed defaults want document metadata and the store has none yet.

**7. Start the gateway** in a second terminal (repeat the step 2 export there). The Go module lives in `gateway/`, so run it from that directory.

```bash
cd gateway
go run .
```

**8. Check health.** In PowerShell use `curl.exe`; plain `curl` is an alias for `Invoke-WebRequest`.

```bash
curl http://127.0.0.1:8080/health
```

```powershell
curl.exe http://127.0.0.1:8080/health
```

**9. Query before ingesting anything.** `quickstart.py` is a small helper so PowerShell and bash run identical commands. It sends a W3C `traceparent` header and prints the trace id.

```bash
uv run --project eval python eval/scripts/quickstart.py query "Who directs Harbor Light Observatory?"
```

The store is empty, so the printed JSON shows `"degraded_mode": true`, a `notice_codes` list that includes 24 and 25, a `notices` list that includes `DEFAULT_LEVER_UNAVAILABLE` and `GRAPH_DISABLED_BY_CONFIG`, and `"levers": ["rerank"]`. Other notices can appear beside those two; those are the ones to look for. This is the shipped behaviour of a store without document metadata (see below), not a fault.

**10. Ingest the sample.** The five documents in `eval/corpora/quickstart/` are project-authored fiction under this repository's MIT license, each posted with a `doc_title`, a `source` and a `published_date`.

```bash
uv run --project eval python eval/scripts/quickstart.py ingest
```

It prints one JSON line per document and exits non-zero if a document fails or the 420-second deadline expires. Then wait until the engine terminal shows a line containing `evidence_metadata became available again` and a line containing `index.swap.metadata_coverage: documents_with_metadata=5 documents=5` (a 2-second debounce plus the index rebuild). Coverage lines with smaller counts can appear while the five documents finish; the 5-of-5 line is the one to wait for.

**11. Query again, then ask the two-hop question.** Re-run the step 9 query: the printed JSON no longer lists `DEFAULT_LEVER_UNAVAILABLE`, and `levers` is now `["rerank", "evidence_metadata"]`. Then ask a question that needs three of the five documents, first with the defaults and then with the graph opted in:

```bash
uv run --project eval python eval/scripts/quickstart.py query "Which company built the spectrograph at Harbor Light Observatory, which Marisol Vega directs, and where is that company based?"
uv run --project eval python eval/scripts/quickstart.py query "Which company built the spectrograph at Harbor Light Observatory, which Marisol Vega directs, and where is that company based?" --graph
```

The expected answer is Alder Optics, based in Port Marlow. The question names two entities, Harbor Light Observatory and Marisol Vega, because the graph looks for a path between entities the question names; a question that names only one cannot produce a path. `graph_path_found` says whether the graph found a path between the question's entities; it only means something with `--graph`, and whether entity extraction links the documents is not guaranteed on a five-document sample.

**12. Open the traces and dashboard.** In Jaeger, <http://127.0.0.1:16686>, pick the service `lancet-gateway` and paste the printed `trace_id` (or open `http://127.0.0.1:16686/trace/<trace_id>` directly). Grafana is at <http://127.0.0.1:3000>, dashboard "Lancet RAG Operations", login `admin`/`admin` (a committed local-dev credential).

**13. Re-score a recorded run offline.** This is free and needs no key. It scores a temporary copy of the 06.3.6 run of record's journal and compares the result with the committed report, so nothing under `eval/runs/` is written.

```bash
RUN=eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout
TMP=$(mktemp -d) && cp "$RUN/journal.jsonl" "$TMP/"
uv run --project eval lancet-eval score --run "$TMP" --no-judge
uv run --project eval lancet-eval report --run "$TMP"
uv run --project eval python eval/scripts/compare_rescore.py "$RUN" "$TMP"
git status --porcelain -- eval/runs
```

```powershell
$run = "eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout"
$tmp = New-Item -ItemType Directory -Path (Join-Path $env:TEMP "lancet-rescore-$(Get-Random)")
Copy-Item "$run/journal.jsonl" $tmp
uv run --project eval lancet-eval score --run $tmp --no-judge
uv run --project eval lancet-eval report --run $tmp
uv run --project eval python eval/scripts/compare_rescore.py $run $tmp
git status --porcelain -- eval/runs
```

`score` takes about 3 minutes. The re-score reproduces the run when every scored dimension and the `result_hash` are equal; `compare_rescore.py` checks that and exits non-zero otherwise. Only metadata fields may legitimately differ: `commit_sha`, `run_date`, and, on a checkout with CRLF line endings (Windows with `core.autocrlf`), `dependency_lock_hash`. The final `git status` must print nothing. If `score` refuses with a pre-registration commit error, the clone is shallow: run `git fetch --unshallow`.

**14. Check a live stack.** This sends three canary questions through all nine evaluation arms (27 requests) and checks that each arm's graph and lever fields are echoed as declared. It takes about 5 minutes and costs a few cents. It refuses to run while any `LANCET_ENGINE__GRAPH__*` or `LANCET_ENGINE__LEVERS__*` variable is set.

```bash
uv run --project eval lancet-eval preflight --stack
```

**15. Tear down.** Stop the engine and gateway with Ctrl+C, then remove the stack and its volumes:

```bash
docker compose -p lancet-qs --profile observability down -v
```

### What the shipped defaults do

- The committed `[engine.levers] defaults = ["rerank", "evidence_metadata"]` make every query that names no lever a paid rerank call.
- A store without document metadata boots with the startup WARN above, and responses carry `DEFAULT_LEVER_UNAVAILABLE` and `degraded_mode = true` until documents with metadata are ingested or the store is backfilled (D-194).
- A legacy 19-column store needs `backfill_evidence_metadata --migrate-only` first (D-197).
- An empty `LANCET_ENGINE__LEVERS__DEFAULTS` starts the engine lever-free (bash: `LANCET_ENGINE__LEVERS__DEFAULTS= cargo run --manifest-path engine/Cargo.toml --release --bin engine`). PowerShell cannot hold an empty environment variable, so there set `defaults = []` under `[engine.levers]` in `config/config.toml`.
- Graph context is off by default and opted into per request with `"disable_graph_context": false` (D-207). `quickstart.py query ... --graph` sends it.
- `"disable_default_levers": true` runs exactly the levers a request names, even none (D-198). `quickstart.py query ... --no-default-levers` sends it.

The evaluation harness runs against an isolated store under `LANCET_ENV=eval`; its commands and the isolation setup are in [`eval/README.md`](./eval/README.md).
<!-- quickstart:end -->

---

## 📂 Repository Contents

### 💻 Source and deployment
* [gateway/](./gateway) — Go control plane: HTTP API, SSE streaming, PostgreSQL, Atlas schema.
* [engine/](./engine) — Rust data plane: ingestion, chunking, LanceDB, hybrid retrieval, graph, state machine, OTel.
* [proto/](./proto) — Protobuf service contract shared between gateway and engine.
* [eval/](./eval) — `lancet-eval` Python harness, corpora definitions and committed run records.
* [deploy/](./deploy) — OTel Collector, Prometheus, Loki and Grafana provisioning.
* [config/](./config) — engine configuration (`config.toml`, the `eval` overlay, the example file with derived timeout budgets documented).
* [docs/](./docs) — public-facing notes; today the evaluation-fidelity and graph-yield note.

### 🧠 Design & Discussion Documents
* [.discussion/rag_side_project_brainstorming_document.md](.discussion/rag_side_project_brainstorming_document.md) — initial brainstorming on trade-offs, technology choices and resume impact.
* [.discussion/final_implementation_decision_document.md](.discussion/final_implementation_decision_document.md) — the finalized architecture, storage and custom-vs-framework choices.
* [.discussion/implementation_plan.md](.discussion/implementation_plan.md) — the bootstrap plan for the gRPC contract, directories and files.
* [.discussion/lightweight_state_machine_plan.md](.discussion/lightweight_state_machine_plan.md) — design of the custom async state machine.
* [.discussion/decisions/](.discussion/decisions) — ADRs, including the force-close decisions for Phases 2 and 3.

### 📋 GSD Planning Blueprint (under [.planning/](.planning))
* [PROJECT.md](.planning/PROJECT.md) — project definition, validated requirements and the key-decision log.
* [REQUIREMENTS.md](.planning/REQUIREMENTS.md) — requirement IDs with traceability to phases (ARCH, RAG, DATA, ORCH, GATE, OBS).
* [ROADMAP.md](.planning/ROADMAP.md) — every phase with goals, success criteria, plan lists and the backlog.
* [STATE.md](.planning/STATE.md) — the living progress log.
* [research/NEXT-STEPS-2026-10-06.md](.planning/research/NEXT-STEPS-2026-10-06.md) — the analysis that inserted Phases 06.3.5 and 06.3.6 and triaged the backlog.

---

## 🗺️ Implementation Roadmap

Fifteen phases are complete (192 plans). Two are planned. One is parked. Details, success criteria and plan lists are in [`.planning/ROADMAP.md`](.planning/ROADMAP.md).

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

### ✅ Phase 5: State Machine & Workflow Events (27 plans; UAT 10/10)
The Rust state machine with typed client-facing events streamed through the gateway over SSE; timeouts, retries and cancellation; PostgreSQL checkpoints with FIFO drain and graceful-shutdown guarantees; verified live against OpenRouter. Two quality-gate requirements (GATE-01 wire framing, GATE-02 checkpoint ownership) were formalized here.

### ✅ Phase 6: Module Graph, Wire Contract and Degraded-Mode Hardening (16 plans — 2026-08-22)
Rust and Go module-graph restructure; one consolidated additive wire-contract change; RAG-03 delivered: opt-in model-only answers with explicit notices, per-path `RETRIEVAL_DEGRADED`, citation repair with `CITATION_REPAIRED` / `CITATION_DROPPED` and basis downgrade, a table-driven bad-input matrix, `GRAPH_UNAVAILABLE` on both silent-degrade paths. Two human UAT rulings tightened the contract (a total citation drop must not bypass the model-only flag; citations resolve only against what the model actually saw).

### ✅ Phase 6.1: Index Rebuild-and-Swap and Deterministic Proofs (4 plans — 2026-08-23)
Index rebuild-and-swap with cross-index corpus generation (`DEBT-RAG-04`), deterministic proofs for two staging-race debt items, and the documented review of the local-only exposure constraint.

### ✅ Phase 6.2: OpenTelemetry Traces, Metrics and Logs (12 plans — 2026-08-27)
OTel across Go and Rust through a Collector to Jaeger, Prometheus and Loki, Grafana provisioned as code with a typed dashboard generator, trace-to-log correlation, and rate-limited exporter diagnostics under Collector outage.

### ✅ Phase 6.3: Evaluation Harness, Corpora and Recorded Run (11 plans — 2026-09-04)
The `lancet-eval` harness: MultiHop-RAG corpus sampling with fixed seeds, isolated eval store, two-arm drive, deterministic IR and answer metrics, cached LLM-as-judge scoring with a calibration worksheet, dated run records with pinned provenance. Its first full run (2026-09-03) is what the next five phases had to correct.

### ✅ Phases 6.3.1 – 6.3.4: Making the evaluation signal trustworthy (26 plans — 2026-09-05 to 2026-09-13)
A new requirement, OBS-05, formalized mid-milestone: a failed query path must be visible on the wire and in the report, every record carries provenance, retrieval and graph health are measured per path, and the graph effect is a per-question paired comparison. Delivered as: engine and config failure signalling (6.3.1); harness diagnostics, scored dimensions and paired ablation with bootstrap CIs (6.3.2); a censoring-aware latency measurement pass that replaced guessed timeouts with six p95-derived budgets and an enforced provider-attempt invariant (6.3.3); a staged re-drive with pre-committed gates, fail-closed journal completeness, and the root-cause record (6.3.4; its own full drive halted and is marked not a run of record).

### ✅ Phase 06.3.4.1: Retrieval Diagnosis, Index Identity and Graph-Yield Repair (34 plans — 2026-10-06)
Separated corpus/index drift from retrieval health from graph architecture. Fixed index identity (the eval index may contain only the mapped document set, with a regenerated gold-coverage table), fixed a `RetrieveHybrid` slowdown, added answer-usability metrics, and replaced whole-question cosine seeding with mention extraction, multi-seed matching, bounded seed-to-seed path search and a graph RRF list. Three paid drives under per-stage caps; the third is the run of record and passed all pre-committed unpark gates. UAT 4/4, verification 10/10, security audit 156/156 threats closed.

### 🔜 Phase 06.3.5: Retrieval Ablation Matrix, Paper-Convention Metrics, Judged Pass and Calibration (planned)
A retrieval mode on the contract and four arms — dense-only, BM25-only, hybrid, hybrid+graph — on a committed dev/held-out split; MultiHop-RAG's own Hits@k and MRR beside Lancet's metrics; the judged pass with a human-calibrated slice; one four-arm comparison against hybrid as the reference. The system under test is unchanged so results stay comparable to the run of record.

### 🔜 Phase 06.3.6: Quality Levers Measured as Arms (planned)
Reranker (promoted from the backlog), a graph repair selected by a per-question diagnosis of the no-path questions (entity resolution or graph-evidence precision), publish-date metadata, and answer-format prompting — each developed on the dev set and read once on held-out with a pre-registered primary metric. A lever becomes a default only when its paired delta's CI excludes zero. More hops is explicitly not a lever.

### ⏸️ Phase 6.4: Docs Suite, Verified Quickstart and v1 Milestone Closure (parked)
README front door, design narrative, observability walkthrough, evaluation methodology and results pages, four diagrams, a verified quickstart on Windows and WSL, the honest-limitations section, backlog promotion of the remaining debt, and milestone closure. Parked until 06.3.5 and 06.3.6 publish; the unpark is an explicit owner decision.

---

## 🔑 Key Decisions & Trade-offs

A selection of the most discussable calls (full log in [`.planning/PROJECT.md`](.planning/PROJECT.md)):

* **Go gateway + Rust engine over gRPC.** Separates control-plane concerns from the latency-sensitive data plane and makes the boundary explicit and type-safe.
* **Embedded LanceDB for vectors and graph.** Local-first, Arrow-native, no separate database service; the graph lives in two tables beside the chunks.
* **Custom chunking, hybrid retrieval and weighted RRF with documented tie rules.** High-leverage layers built in the open rather than behind a framework; the graph joins fusion as a third ranked list instead of replacing it.
* **A lightweight Rust state machine instead of a workflow framework.** Borrows the useful orchestration concepts and keeps the scope finishable.
* **Degraded modes as typed wire notices, failing closed by default.** A reader of the stream can always tell what the system did not do.
* **Force-close discipline with a named debt ledger (ADR-02-004, ADR-03-003).** Phases close on schedule; gaps become tracked items, not silence.
* **Evaluation fidelity as a requirement (OBS-05), then comparative evaluation (OBS-06).** Reports fail closed on incomplete journals; gates and floors are committed before a paid drive; negative results are published, not re-run until they look better; spend is capped per stage and reconciled to the bill.
* **Timeout budgets derived from censoring-aware measurement, not guessed.** The original budgets were unit-test guesses that clipped 90% of queries; the replacements come from a measured p95 with the censoring explicitly counted.
* **Graph retrieval redesigned around seeds and bounded paths.** Whole-question cosine seeding with `limit(1)` gave 9.8% presence; mention extraction, multi-seed matching and a degree-capped seed-to-seed path search give 66%, with the fact cap and degree cap derived from the store and the prompt budget. The value of that path is now measured honestly and is still an open question.

---

## ⚠️ Honest limitations (current)

* **Local-only by design.** No authentication, TLS or per-principal rate limiting; loopback listeners only (see below).
* **The graph has not paid for itself yet.** On MultiHop-RAG it changes retrieval composition on about half the questions, costs 1.2–1.6 s and about 210 prompt tokens per query, and produces no significant answer-quality gain; ranking quality is slightly worse. This is reported, not hidden, and is the subject of 06.3.6.
* **No standard-RAG baseline yet.** Dense-only, BM25-only and hybrid have not been compared; 06.3.5 adds them.
* **Judged dimensions are unrun on the repaired system** and no human calibration has been performed yet.
* **Small sample.** 100 questions; intervals of roughly ±10 points.
* **The LLM provider is not a controlled variable.** OpenRouter may route a model across providers mid-drive, and did; a local endpoint is a v1.1 backlog item.
* **Unmeasured claims are labelled as such** in the run reports and will be in the 6.4 docs: chunking strategy comparison, community-level questions, and the evidence-versus-priors behaviour of the generator.

---

## 🚀 Backlog & Extension Points

Triage as of 2026-10-06 ([details](.planning/research/NEXT-STEPS-2026-10-06.md#3-backlog-triage)):

**Promoted into v1 (Phase 06.3.6):**
1. **Reranking (999.2)** — cross-encoder re-scoring behind the existing `Reranker` port.
2. **Entity resolution, lite (999.6)** — alias merging behind the existing `EntityResolver` port, if the no-path diagnosis selects it.

**v1.1 candidates:**
3. **Local inference endpoint (999.11)** — an OpenAI-compatible local endpoint so the provider becomes a controlled variable.
4. **Query reformulation strategies (999.3)** — HyDE and multi-query as additional arms; the `reformulate` node and multi-variant fusion already exist.
5. **S3-compatible storage for LanceDB (999.8)**.

**v2:**
6. **Community summaries (999.1), compile-time node semantics (999.5), ingestion-time synthesis (999.4)** — global GraphRAG; needs a benchmark with community-level questions.
7. **Knowledge drift detection and LLM-verified node merging (999.6, full)**, **Rayon CPU isolation (999.7)**, **LLM wiki second brain (999.9)**, **session memory in LanceDB (999.10)**, **PageIndex retrieval (999.12)**.

---

## 🔒 Local-Only Exposure Constraint & Debt Triggers (`DEBT-CR-04`)

> [!IMPORTANT]
> **Local-Only Service Scope**
> The Go API Gateway listener binds explicitly to loopback (`127.0.0.1:<port>`). This is a standing v1/local-first constraint, not scoped to any single phase — trusted local callers only. The service is unauthenticated and lacks TLS or per-principal rate limiting. Reviewed and documented as accepted in Phase 6.1; it stays open and accepted for v1.

### Review & Reclassification Triggers (`DEBT-CR-04`)
The local-only disposition must be immediately reviewed and reclassified as blocking before any of the following deployment changes occur:
- Binding the gateway or engine listeners to a non-loopback interface (`0.0.0.0` or shared network adapter)
- Exposing the service via reverse proxy, tunnel, port forwarding, or shared LAN access
- Deploying into multi-tenant, container-host, VM-host, remote, or cloud environments
- Allowing external or automated untrusted callers to submit document ingestion requests
