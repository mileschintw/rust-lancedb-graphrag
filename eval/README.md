# Lancet Evaluation Harness (`lancet-eval`)

The Lancet evaluation harness (`eval/`) is a Python package managed by `uv` that measures retrieval quality and generation performance across multi-hop question answering benchmarks.

## Overview

The harness operates as a black-box HTTP/SSE client driving the `/rag/query` endpoint of the Lancet gateway, asserting streaming contracts, extracting deterministic IR metrics (recall@k, context precision@k, MRR@10, nDCG@k, SQuAD EM/F1, abstention rate) without LLM dependencies, and running cached LLM-as-judge groundedness/faithfulness evaluations.

## Two-Armed Ablation Execution (D-46, D-47, D-207)

The harness evaluates the arms of every benchmark question against a single running engine instance. Since D-207 the engine's configured default for graph context is off (`[engine.graph] context_default_enabled = false`), so an absent `disable_graph_context` field means "the configured default", which is now off. Every canonical arm therefore sends the field explicitly:
- **Graph-on arms** (for example `hybrid+graph`): the request body sets `disable_graph_context: false`, so graph context runs.
- **Graph-off arms:** the request body sets `disable_graph_context: true` and the response carries the typed notice `GRAPH_ABLATION` (code 18). A request that omits the field and meets the configured default instead carries `GRAPH_DISABLED_BY_CONFIG` (code 25), not `GRAPH_ABLATION`.
- **Levers:** every canonical arm also sends `disable_default_levers: true` (D-198), so an arm runs exactly the levers it declares and never inherits the engine's configured default levers.
- **Legacy labels:** the `graph-on` and `graph-off` labels recorded the earlier drives with the graph field absent. Those request bodies stay byte-identical so the recorded runs still re-score, and they are never sent again.
- **Ablation Delta:** `delta = graph_on_score - graph_off_score`. Near-zero or negative deltas are published as-is to report honest empirical results.
- **Provenance Verification:** graph-off arm responses must carry the typed notice `GRAPH_ABLATION` (code 18) and must not carry `GRAPH_UNAVAILABLE` (code 10).

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

# Terminal 2 — Start Gateway with eval schema (the Go module lives in gateway/):
cd gateway
LANCET_ENV=eval LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval' go run .
```

To check a stack that is not the isolated eval store (for example the quickstart stack in the top-level `README.md`), run `uv run --project eval lancet-eval preflight --stack`. It needs no eval store and writes nothing under `eval/runs/`.

### 3. The S1 Store (D-251)

v1.1 S1 builds its merged-chunk store next to the v1.0 store and never touches it:

| Store (`--store`) | Overlay (`LANCET_ENV`) | LanceDB path | PostgreSQL schema | Atlas env |
|---|---|---|---|---|
| `eval` (default, v1.0) | `eval`, `config/config.eval.toml` | `./data/lancedb-eval` | `lancet_eval` | `eval` |
| `eval-s1` (S1) | `eval-s1`, `config/config.eval-s1.toml` | `./data/lancedb-eval-s1` | `lancet_eval_s1` | `eval-s1` |

`seed`, `reseed`, `preflight`, `identity check` and `identity pg-delete-extras` take `--store`. With `--store eval-s1` the harness uses the S1 path and schema whatever `eval/config.toml` or `LANCET_EVAL__*` name, refuses `./data/lancedb-eval` and `lancet_eval` before it drops or deletes anything, and fails when the overlay's `lancedb_path` differs from the harness's path. Preflight's `store_isolation` row names the store, path and schema it checked. `seed` and `reseed` also refuse a `LANCET_ENV` that names the other store, so a forgotten `--store` in an S1 shell never reseeds v1.0. The S1 store keeps its own document map, `eval/corpora/<map corpus>/document_map.eval-s1.json`, beside the v1.0 `document_map.json` (#18). An S1 seed or reseed never reads, writes or deletes the v1.0 map. The identity gate (and so `preflight`, `run` and `measure`) reads the map of the store whose LanceDB path the settings use, preflight's `corpus_generation` reads the selected store's map, and `index_identity` names the map it checked. The diagnostic table builders take a `store` argument (v1.0 by default). `score` still reads the v1.0 map: a journal can hold both stores' arms, so its map follows the store-prefixed arm labels of #15. Without `--store`, every command behaves as before. `--stack` takes no `--store`.

```bash
docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"
(cd gateway && atlas schema apply --env eval-s1 --auto-approve)
LANCET_ENV=eval-s1 ./engine/target/debug/engine
(cd gateway && LANCET_ENV=eval-s1 LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_s1' go run .)
uv run --project eval lancet-eval preflight --store eval-s1 --corpus <S1 corpus>
```

`gateway/db/schema.eval-s1.hcl` is `schema.eval.hcl` with the schema renamed to `lancet_eval_s1` (a test checks they match), so both eval schemas get the same tables.

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

# Drive a full benchmark run on a canonical-arm corpus (resumable across quota interruptions)
uv run --project eval lancet-eval run --corpus <canonical-arm corpus>

# Smoke test a run with limited questions (stamped partial: true)
uv run --project eval lancet-eval run --corpus <canonical-arm corpus> --limit 3

# Score completed run offline with zero HTTP requests
uv run --project eval lancet-eval score --run eval/runs/2026-08-30-multihop_rag --no-judge

# Score completed run with LLM judge sampling and caching
uv run --project eval lancet-eval score --run eval/runs/2026-08-30-multihop_rag --judge --sample 100

# Emit human calibration worksheet
uv run --project eval lancet-eval score --run eval/runs/2026-08-30-multihop_rag --judge --sample 100 --emit-calibration-worksheet eval/runs/2026-08-30-multihop_rag/calibration_worksheet.jsonl

# Score run with human calibration validation and observed agreement
uv run --project eval lancet-eval score --run eval/runs/2026-08-30-multihop_rag --judge --sample 100 --calibration-file eval/runs/2026-08-30-multihop_rag/calibration_completed.jsonl

# Generate final Markdown and JSON report
uv run --project eval lancet-eval report --run eval/runs/2026-08-30-multihop_rag

# Compare report against a previous run
uv run --project eval lancet-eval report --run eval/runs/2026-08-30-multihop_rag --compare-to eval/runs/2026-08-29-multihop_rag
```

`multihop_rag`, `multihop_rag_diag` and `graphrag_bench` list the legacy `graph-on` / `graph-off` labels. `lancet-eval run` refuses them, a resume included (D-198), so they cannot be driven or resumed through `run`; their recorded runs are re-scored with `score` and `report`. The canonical-arm corpora are `multihop_rag_heldout`, `multihop_rag_rehearsal` and the `multihop_rag_levers_*` set. The `preflight` and `seed` examples above name `multihop_rag` because neither starts a drive.

`lancet-eval probe` now defaults to the `hybrid+graph` arm. A probe is a live request, so it refuses legacy labels too.

For a canonical-arm corpus, the `run` command enables `--resume` by default and resolves to the newest existing dated directory for the corpus. Starting a second recorded run requires either passing `--no-resume` or specifying an explicit new dated `--out` path; otherwise, running `lancet-eval run` on the same `<canonical-arm corpus>` appends to the already-published record.

## LLM-as-Judge Evaluation & Calibration (D-52, D-53)

The evaluation harness evaluates answer groundedness and faithfulness using an LLM-as-judge model (`meta-llama/llama-3.3-70b-instruct`) pinned distinctly from the engine's generation model (`deepseek/deepseek-v4-flash-0731`):
- **Groundedness & Faithfulness Rubrics:** 1-5 scale with anchored definitions.
- **Auditable Plain-Text Cache:** All judge verdicts are stored in `judge_cache.json` keyed by `sha256(prompt_version, judge_model, question, answer, post_truncation_evidence)`.
- **Bounded Evidence Truncation:** Passages are truncated in wire ranked order (`PER_PASSAGE_CHAR_BUDGET = 1500`, `EVIDENCE_CHAR_BUDGET = 12000`) with explicit `[TRUNCATED: N further passages omitted]` markers included in the cache key.
- **Empty Citation Handling:** Responses without citations are marked `status: skipped` with reason "no evidence returned; groundedness undefined" without calling the judge.
- **Calibration Slice:** Human evaluators grade ~20 representative questions in a calibration worksheet (`.jsonl`). The worksheet's candidate pool is capped by whatever `--sample` scope the preceding judge pass used, and omitting `--sample` maximizes it up to the run's real citation rate. `score --calibration-file` validates prompt version alignment and calculates exact-match rate and mean absolute difference (MAD).

## Run-Record Directory Layout & Publication

A committed run record lives in `eval/runs/<YYYY-MM-DD>-<corpus>/` and contains 5 required artifacts (a dated corpus run directory is tracked by git, while every other path under `eval/runs/` is scratch and stays ignored):
1. `journal.jsonl`: The durable append-only record of all executed question queries and responses across both arms.
2. `judge_cache.json`: The plain-text auditable verdicts and cached responses from the LLM judge.
3. `report.md`: Human-readable GitHub-Flavored Markdown report with full pins, dimension results, and methodological caveats.
4. `report.json`: Machine-readable evaluation report conforming to `eval/report.schema.json`.
5. `metadata.json`: Execution metadata carrying all required pins (commit SHA, models, seed, sample sizes, index generation, lock hash).

### Pre-Commit Run-Record Reviewer Checklist
Before committing an evaluation run record, verify:
1. **Metadata Complete:** All required pins are present in `metadata.json` and `report.md` (commit SHA, judge model and prompt version, both sample sizes, corpus, index generation, lock hash).
2. **Dimension Statuses:** Every dimension has a status (`ok`, `skipped`, or `error`) with a clear reason for non-`ok` entries.
3. **No Unmeasured Values:** No dimension reports a fabricated or simulated value; skipped dimensions display `—`.
4. **No Cross-Corpus Aggregation:** Each corpus report is standalone; no aggregate or overall score is computed across corpora.
5. **Sample Size Consistency:** Sample sizes match previous runs or changes are explicitly called out.

### 10-Item Reference-Set Spot-Check
Perform a manual end-to-end spot-check on roughly 10 scored records (question, retrieved chunks, model answer, gold facts, and computed metric scores):
- **Weighted Selection:** Focus on records with notices (`GRAPH_ABLATION`), errors, zero citations, judge errors, and exact-match-zero with high F1.
- **Random Selection:** Include 2–3 uniformly random records to ensure the boring majority has no matching bugs.
- **Integrity Rule:** If the spot-check discovers a metric mismatch or parser flaw, record it as a finding rather than committing a false report.

## CLI Sub-commands

| Command | Status | Phase / Plan | Description |
|---|---|---|---|
| `lancet-eval corpus fetch` | **Implemented** | Plan 06.3-03 | Fetch and verify raw MultiHop-RAG dataset to local `.cache/` |
| `lancet-eval corpus sample` | **Implemented** | Plan 06.3-03 | Sample question subsets with fixed seed and extract document subset |
| `lancet-eval preflight` | **Implemented** | Plan 06.3-04 | Verify store isolation, engine/gateway health, and model pins |
| `lancet-eval seed` | **Implemented** | Plan 06.3-04 | Ingest evaluation documents into isolated evaluation store |
| `lancet-eval reseed` | **Implemented** | Plan 06.3-04 | Drop and recreate isolated evaluation store schema |
| `lancet-eval probe` | **Implemented** | Plans 06.3-01 / 06.3-03 | Single-question end-to-end smoke check with deterministic scoring |
| `lancet-eval run` | **Implemented** | Plan 06.3-05 | Execute benchmark questions across a canonical-arm corpus's arms; refuses legacy-label corpora |
| `lancet-eval score` | **Implemented** | Plans 06.3-05 / 06.3-06 | Compute offline IR metrics or cached LLM-as-judge scores |
| `lancet-eval report` | **Implemented** | Plan 06.3-07 | Emit final dated Markdown and JSON evaluation reports |

> **Note on `reseed` implementation:** `lancet-eval reseed` executes a guarded drop-and-recreate of the isolated `lancet_eval` PostgreSQL schema (via direct SQL drop/recreate followed by `atlas schema apply --env eval`) and wipes the evaluation LanceDB directory (`./data/lancedb-eval`). Destructive resets fail closed if the target schema is blank, default (`public`), or collides with the dev database/schema. `reseed --store eval-s1` resets `lancet_eval_s1` with `atlas schema apply --env eval-s1` and wipes only `./data/lancedb-eval-s1`. It refuses the v1.0 path and schema before any reset.

## Offline Testing

The test suite in `eval/tests/` passes completely offline with no network access, no running gateway, and no `OPENROUTER_API_KEY`:

```bash
uv run --project eval pytest eval/tests/ -v
```

