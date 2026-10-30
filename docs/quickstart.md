[← Back to README](../README.md)

<!-- quickstart:start -->
# Quickstart (Windows native and Linux via WSL)

> Verified on a fresh clone: Windows 11 native on 2026-10-11 at commit 1c000271 (06.4-QS-TRANSCRIPT-WINDOWS.md); WSL Ubuntu 24.04 on 2026-10-11 at commit 752c8ae0 (06.4-QS-TRANSCRIPT-WSL.md).

This takes a clean clone to a traced answer over a five-document sample, on Windows native and on Linux inside WSL. Both platforms run the same commands; where a shell differs, both variants are shown. Run every command from the repository root unless a step says otherwise. The only thing you supply is an OpenRouter API key.

## Prerequisites

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

## Steps

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

**11. Query again, then ask the two-hop question.** Re-run the step 9 query: the printed JSON no longer lists `DEFAULT_LEVER_UNAVAILABLE`, and `levers` is now `["rerank", "evidence_metadata"]`. Then ask a question that names two linked entities (the Alder Optics profile alone names the builder and where it is based, and the observatory overview confirms that Marisol Vega directs Harbor Light Observatory), first with the defaults and then with the graph opted in:

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

## What the shipped defaults do

- The committed `[engine.levers] defaults = ["rerank", "evidence_metadata"]` make every query that names no lever a paid rerank call.
- A store without document metadata boots with the startup WARN above, and responses carry `DEFAULT_LEVER_UNAVAILABLE` and `degraded_mode = true` until documents with metadata are ingested or the store is backfilled (D-194).
- A legacy 19-column store needs `backfill_evidence_metadata --migrate-only` first (D-197).
- An empty `LANCET_ENGINE__LEVERS__DEFAULTS` starts the engine lever-free (bash: `LANCET_ENGINE__LEVERS__DEFAULTS= cargo run --manifest-path engine/Cargo.toml --release --bin engine`). PowerShell cannot hold an empty environment variable, so there set `defaults = []` under `[engine.levers]` in `config/config.toml`.
- Graph context is off by default and opted into per request with `"disable_graph_context": false` (D-207). `quickstart.py query ... --graph` sends it.
- `"disable_default_levers": true` runs exactly the levers a request names, even none (D-198). `quickstart.py query ... --no-default-levers` sends it.

The evaluation harness runs against an isolated store under `LANCET_ENV=eval`; its commands and the isolation setup are in [`eval/README.md`](../eval/README.md).
<!-- quickstart:end -->

## Running the test gates

v1.0 had no CI (06-CONTEXT D-85). Since v1.1 (#44), every change passes the fast tier, run from the repository root, and pull requests run it in GitHub Actions, one job per module:

```bash
cargo test --manifest-path engine/Cargo.toml --locked && sh scripts/engine-test-targets.sh
(cd gateway && go test -count=1 -short ./...) && sh scripts/gateway-test-targets.sh
uv run --project eval pytest -n auto --dist loadfile
```

- The two `scripts/*-test-targets.sh` scripts check a floor of test functions in every target, so a test target that stops compiling fails the gate instead of quietly vanishing from a total.
- `-count=1` turns off Go's test cache, which could otherwise replay a cached pass for a test that reads the config files.
- The opt-in slow tier, the live tier, the time budgets and the CI jobs are in [`testing.md`](testing.md).
- Beyond the tests, every phase after Phase 1 has a code review on record (its `*-REVIEW.md`), and Phase 6.4's code-first slice was reviewed before the quickstart was verified (D-205).
- The quickstart above was followed verbatim from a fresh clone on both platforms, and the runs are committed as transcripts: [`06.4-QS-TRANSCRIPT-WINDOWS.md`](../.planning/phases/06.4-docs-suite-verified-quickstart-debt-backlog-promotion-and-v1/06.4-QS-TRANSCRIPT-WINDOWS.md) and [`06.4-QS-TRANSCRIPT-WSL.md`](../.planning/phases/06.4-docs-suite-verified-quickstart-debt-backlog-promotion-and-v1/06.4-QS-TRANSCRIPT-WSL.md).
