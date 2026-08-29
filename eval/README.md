# Lancet Evaluation Harness (`lancet-eval`)

The Lancet evaluation harness (`eval/`) is a Python package managed by `uv` that measures retrieval quality and generation performance across multi-hop question answering benchmarks.

## Overview

The harness operates as a black-box HTTP/SSE client driving the `/rag/query` endpoint of the Lancet gateway, asserting streaming contracts, extracting deterministic IR metrics (recall@k, context precision@k, MRR@10, nDCG@k, SQuAD EM/F1, abstention rate) without LLM dependencies, and running cached LLM-as-judge groundedness/faithfulness evaluations.

## Running Commands

All commands are executed from the **repository root** using `uv run --project eval`:

```bash
# Run unit and contract tests (offline, no gateway or API key required)
uv run --project eval pytest

# Run linter
uv run --project eval ruff check --preview eval/src eval/tests

# Probe a single question end-to-end (requires running stack)
uv run --project eval lancet-eval probe --question "Who is the CEO of OpenAI?" --gold-fact "Sam Altman" --out ./tmp-probe

# Probe a question directly from a benchmark corpus
uv run --project eval lancet-eval probe --corpus multihop_rag --question-id "mhr-0001" --out ./tmp-probe
```

## CLI Sub-commands

| Command | Status | Phase / Plan | Description |
|---|---|---|---|
| `lancet-eval corpus fetch` | **Implemented** | Plan 06.3-03 | Fetch and verify raw MultiHop-RAG dataset to local `.cache/` |
| `lancet-eval corpus sample` | **Implemented** | Plan 06.3-03 | Sample question subsets with fixed seed and extract document subset |
| `lancet-eval probe` | **Implemented** | Plans 06.3-01 / 06.3-03 | Single-question end-to-end smoke check with deterministic scoring |
| `lancet-eval preflight` | Planned | Plan 06.3-04 | Verify store isolation, engine/gateway health, and model pins |
| `lancet-eval seed` | Planned | Plan 06.3-04 | Ingest evaluation documents into isolated evaluation store |
| `lancet-eval reseed` | Planned | Plan 06.3-04 | Drop and recreate isolated evaluation store schema |
| `lancet-eval run` | Planned | Plan 06.3-05 | Execute benchmark questions with graph-on / graph-off arms |
| `lancet-eval score` | Planned | Plans 06.3-05 / 06.3-06 | Compute deterministic and cached LLM-judged metrics |
| `lancet-eval report` | Planned | Plan 06.3-07 | Emit final dated Markdown and JSON evaluation reports |

## Benchmark Corpora

- **MultiHop-RAG:** Tang & Yang (2024), ODC-BY 1.0 license. Committed 500-question sample (`eval/corpora/multihop_rag/questions.sample.jsonl`) and 338-document subset (`eval/corpora/multihop_rag/documents.subset.jsonl`).
- **GraphRAG-Bench:** Unspecified license. Hand-authored synthetic schema fixture (`eval/corpora/graphrag_bench/questions.sample.jsonl`, `fixture_only = true`) used for offline corpus-agnostic loader verification.

## Offline Testing

The test suite in `eval/tests/` passes completely offline with no network access, no running gateway, and no `OPENROUTER_API_KEY`:

```bash
uv run --project eval pytest eval/tests/ -v
```
