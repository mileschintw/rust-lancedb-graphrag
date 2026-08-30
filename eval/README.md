# Lancet Evaluation Harness (`lancet-eval`)

The Lancet evaluation harness (`eval/`) is a Python package managed by `uv` that measures retrieval quality and generation performance across multi-hop question answering benchmarks.

## Overview

The harness operates as a black-box HTTP/SSE client driving the `/rag/query` endpoint of the Lancet gateway, asserting streaming contracts, extracting deterministic IR metrics (recall@k, context precision@k, MRR@10, nDCG@k, SQuAD EM/F1, abstention rate) without LLM dependencies, and running cached LLM-as-judge groundedness/faithfulness evaluations.

## Two-Armed Ablation Execution (D-46, D-47)

The harness evaluates both arms of every benchmark question against a single running engine instance:
- **`graph-on`:** Standard RAG execution with graph context enabled (request body omits `disable_graph_context`).
- **`graph-off`:** Ablated execution without graph context (request body sets `disable_graph_context: true`).
- **Ablation Delta:** `delta = graph_on_score - graph_off_score`. Near-zero or negative deltas are published as-is to report honest empirical results.
- **Provenance Verification:** `graph-off` responses must carry the typed notice `GRAPH_ABLATION` (code 18) and must not carry `GRAPH_UNAVAILABLE` (code 10).

## Isolated Evaluation Store (D-56, D-57, D-84)

The evaluation stack is completely isolated from the development environment across both storage layers:
- **LanceDB Vector & Graph Store:** `./data/lancedb-eval` (configured via `LANCET_ENV=eval` overlay `config/config.eval.toml`).
- **PostgreSQL Relational & Checkpoints:** `lancet_eval` schema (configured via DSN `search_path=lancet_eval`).

### 1. Database Schema Setup with Atlas

```bash
# Connect to PostgreSQL and create the eval schema:
docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval;"

# Apply Atlas schema migrations to lancet_eval:
cd gateway
atlas schema apply --env eval --auto-approve
```

### 2. Starting the Isolated Services

```bash
# Terminal 1 — Start Engine from repository root with eval overlay:
LANCET_ENV=eval ./engine/target/debug/engine

# Terminal 2 — Start Gateway with eval schema:
LANCET_ENV=eval LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval' go run ./gateway
```

## Running Commands

All evaluation commands are executed from the **repository root** using `uv run --project eval`:

```bash
# Run unit and contract tests (offline, no gateway or API key required)
uv run --project eval pytest

# Run linter
uv run --project eval ruff check --preview eval/src eval/tests

# Run preflight health and isolation check
uv run --project eval lancet-eval preflight --corpus multihop_rag

# Seed benchmark corpus into isolated evaluation store
uv run --project eval lancet-eval seed --corpus multihop_rag

# Drive full two-armed benchmark run (resumable across quota interruptions)
uv run --project eval lancet-eval run --corpus multihop_rag

# Smoke test a run with limited questions (stamped partial: true)
uv run --project eval lancet-eval run --corpus multihop_rag --limit 3

# Score completed run offline with zero HTTP requests
uv run --project eval lancet-eval score --run eval/runs/latest --no-judge
```

## CLI Sub-commands

| Command | Status | Phase / Plan | Description |
|---|---|---|---|
| `lancet-eval corpus fetch` | **Implemented** | Plan 06.3-03 | Fetch and verify raw MultiHop-RAG dataset to local `.cache/` |
| `lancet-eval corpus sample` | **Implemented** | Plan 06.3-03 | Sample question subsets with fixed seed and extract document subset |
| `lancet-eval preflight` | **Implemented** | Plan 06.3-04 | Verify store isolation, engine/gateway health, and model pins |
| `lancet-eval seed` | **Implemented** | Plan 06.3-04 | Ingest evaluation documents into isolated evaluation store |
| `lancet-eval reseed` | **Implemented** | Plan 06.3-04 | Drop and recreate isolated evaluation store schema |
| `lancet-eval probe` | **Implemented** | Plans 06.3-01 / 06.3-03 | Single-question end-to-end smoke check with deterministic scoring |
| `lancet-eval run` | **Implemented** | Plan 06.3-05 | Execute benchmark questions with graph-on / graph-off arms |
| `lancet-eval score` | **Implemented** | Plan 06.3-05 | Compute deterministic offline IR & answer metrics |
| `lancet-eval report` | Planned | Plan 06.3-07 | Emit final dated Markdown and JSON evaluation reports |

## Offline Testing

The test suite in `eval/tests/` passes completely offline with no network access, no running gateway, and no `OPENROUTER_API_KEY`:

```bash
uv run --project eval pytest eval/tests/ -v
```
