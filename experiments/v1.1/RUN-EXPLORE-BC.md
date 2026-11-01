# Run guide: exploratory runs B and C (#149)

For the run-lane worker. Follow the steps in order, one command at a time. The pre-registrations are
[EXPLORE-C-MHR-FULL.md](EXPLORE-C-MHR-FULL.md) and [EXPLORE-B-2WIKI-READERS.md](EXPLORE-B-2WIKI-READERS.md); this guide
only says how to run them. Each run builds a hybrid store with no graph, drives deepseek over its dev questions, then
replays that context to the Claude readers, as S2X did.

**C goes first.** Its Claude readers cost most and the Claude credit expires on 2026-11-03, so submit C's readers
(step C5) as soon as its context export exists, then build B while they run.

## Rules for the whole run

- **Main checkout only** (`D:\Repos\lancet`, Git Bash, repository root), on `main` at or after the commit that merged
  `PREREGISTRATION_EXPLORE_B` and `PREREGISTRATION_EXPLORE_C`. Worktrees lack the live stores. `replay-init` and every
  `batch submit` run the D-73 check and refuse a dirty `eval/src/lancet_eval`, so `git status --short --
  eval/src/lancet_eval` must print nothing before each of them.
- **`PYTHONUTF8=1` on every `uv run` command** (#84).
- **Spend.** The owner pre-approved spend within #149's ceilings: **Claude credit $70, OpenRouter credit $3**. Print
  each step's estimate (this guide's table, and each command's own estimate line) and go on when it is within the
  ceiling; stop and ask when it is not. OpenRouter credit is shared with other lanes: stop if its balance would fall
  below $1. Read the balance before steps C2 and B2, and after C5 (the key stays in the environment; print only the
  number). If the endpoint refuses the key, report it and go on only while this guide's OpenRouter figures stay
  under $1.25 in all:

  ```bash
  PYTHONUTF8=1 uv run --project eval python -c "import httpx,os; d=httpx.get('https://openrouter.ai/api/v1/credits', headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY']}, timeout=30).json()['data']; print('balance', round(d['total_credits']-d['total_usage'], 2))"
  ```

- **No mid-run cap** (D-258). `run` requires `--stage-cap`; pass `--stage-cap 3`.
- **A non-zero exit stops the run.** A `batch submit` that exits non-zero after printing its manifest path may have
  reached the endpoint: never resubmit it; report it.
- **Count after each drive and each finished arm** (#75), the later record of a question and arm winning:

  ```bash
  PYTHONUTF8=1 uv run --project eval python -c "from collections import Counter; from lancet_eval.journal import load_records; from lancet_eval.pairing import deduplicate_by_arm; rs, _ = deduplicate_by_arm(load_records('<RUN>/journal.jsonl')); [print(arm, outcome, n) for (arm, outcome), n in sorted(Counter((r.graph_arm, r.outcome) for r in rs).items())]; [print('error', r.graph_arm, r.question_id, r.replicate, r.error_type, r.error) for r in rs if r.outcome == 'error']"
  ```

  An arm short of its count: stop and report, with the counts and every `error` line.
- **Never touch** `data/lancedb-eval`, `data/lancedb-eval-s1`, their schemas, or `eval/corpora/multihop_rag/
  {heldout_split.json,questions.heldout.jsonl,diag_selection.json}`. Steps C1 and B1 create the new stores'
  schemas only.
- **Held-out:** no held-out question is read. C's 1,056 fresh held-out questions and B's 900 D-243 held-out
  questions are never sent anywhere.
- **Keys.** `OPENROUTER_API_KEY` must be set; every reader goes through OpenRouter (BYOK on Claude credit). Never
  print a key or write it to a file.
- **Run directories.** Fix them with the date step C2 starts, and write the literal paths wherever a command says
  `<C_DRIVE>`, `<C_RUN>`, `<B_DRIVE>` or `<B_RUN>`:
  - `<C_DRIVE>` = `eval/runs/<YYYY-MM-DD>-explore-c-drive-multihop_rag_full_dev`
  - `<C_RUN>` = `eval/runs/<YYYY-MM-DD>-explore-c-multihop_rag_full_dev`
  - `<B_DRIVE>` = `eval/runs/<YYYY-MM-DD>-explore-b-drive-twowiki_s3b_dev`
  - `<B_RUN>` = `eval/runs/<YYYY-MM-DD>-explore-b-twowiki_s3b_dev`

  `.gitignore` un-ignores all four so they can be committed; `-explore-` is the tag `test_journal.py` reads.
- **Starting and stopping a stack.** Start each of its two processes with `run_in_background`, and go on only after
  the engine logs that it serves gRPC and the gateway logs that it listens on 8080. The engine's log must also say
  `ingest_extraction = false: ingestion extracts no graph`; without it, stop: the build would pay for extraction.
  Never run two stacks at once: they share the ports. A `batch submit` or `batch fetch` needs no stack.

## Prices behind the estimates

From S2X's measured spend (EXPLORE-S2-MERGED.md › Result, merged store, about 6,600 Claude prompt tokens a request):
Sonnet 5.5 sync $0.0179 a request, Opus 5.5 batch $0.0173, Haiku 5.5 batch $0.00043, deepseek sync $0.00027. C's
small-store prompts are shorter (about 2,700 to 3,000 deepseek tokens against 3,760), so S2X's rates are an upper
estimate for C. B's prompts hold eight short passages, about half of C's. Embeddings: `voyageai/voyage-4-large` at
$0.12 per M tokens. Rerank: at most $0.00031 a call. BYOK fees fall inside OpenRouter's free monthly allowance.

| Step | Requests | Claude credit | OpenRouter credit |
|---|---|---|---|
| C2 store build (609 articles, about 1.5 M tokens embedded) | – | – | about $0.20 |
| C3 deepseek drive (1,000 questions, rerank included) | 1,000 | – | about $0.30 to $0.60 |
| C5 Haiku 5.5, K = 2 (batch) | 2,000 | about $0.70 to $0.90 | – |
| C5 Sonnet 5.5, K = 1 (sync) | 1,000 | about $13 to $18 | – |
| C5 Opus 5.5, K = 1 (batch) | 1,000 | about $13 to $18 | – |
| C5 deepseek replicate 2 (sync) | 1,000 | – | about $0.30 |
| B2 store build (6,119 passages, about 0.5 M tokens) | – | – | about $0.06 |
| B3 deepseek drive (100 questions) | 100 | – | about $0.05 |
| B5 the three readers and deepseek replicate 2 | 500 | about $1 to $2 | about $0.02 |
| **Total** | | **about $28 to $39** | **about $0.75 to $1.25** |

Both totals are inside the ceilings. The engine caps (8,192 evidence tokens and 2,048 completion tokens a request)
would allow more, about $0.038 a Sonnet or Opus request: if C's Sonnet arm, read from its records' usage after its
first 200 answers, runs above $0.025 a request, stop and report before it goes on.

## Step 0: checkout and build

1. `git pull --ff-only` on `main`; `git status` must be clean.
2. Build the engine (it has `[engine.graph] ingest_extraction`), then the release bins the harness runs: `inspect_lancedb`
   for the index identity check and `generate_from_context` for `batch submit` and `fetch`. Run the second with
   `run_in_background`; start no paid step before both exit 0.

   ```bash
   cargo build --manifest-path engine/Cargo.toml --locked
   ```

   ```bash
   cargo build --manifest-path engine/Cargo.toml --locked --release --bin inspect_lancedb --bin generate_from_context
   ```

3. Check the source files. Each prints its digest; the corpus pins it, and `seed` refuses a mismatch.

   ```bash
   PYTHONUTF8=1 uv run --project eval python -c "from lancet_eval.split import lf_sha256; print(lf_sha256('eval/corpora/multihop_rag/.cache/corpus.json'))"
   ```

   It must print `20b61b5ab84de84a927420c5d265b7ec8d859ae49980699958a787ade9e4d28f`. If the file is missing, run
   `PYTHONUTF8=1 uv run --project eval lancet-eval corpus fetch --corpus multihop_rag` first.

   ```bash
   PYTHONUTF8=1 uv run --project eval python -m lancet_eval.twowiki fetch
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval python -m lancet_eval.twowiki_b
   ```

   The last must print split `54a15e0781a5…` and `twowiki/.cache/documents.jsonl: 57d038e26b2b…`. It reads held-out
   rows for their `_id` alone.

## Part C: full MultiHop-RAG

### C1: schema (free)

```bash
docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_full;"
```

```bash
(cd gateway && atlas schema apply --env eval-full --auto-approve)
```

### C2: store build (Paid, about $0.20)

Start the C stack:

```bash
LANCET_ENV=eval-full ./engine/target/debug/engine
```

```bash
(cd gateway && LANCET_ENV=eval-full LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_full' go run .)
```

Seed the 609 articles. It writes `data/lancedb-eval-full`, `lancet_eval_full` and
`eval/corpora/multihop_rag_full/document_map.eval-full.json`:

```bash
LANCET_ENV=eval-full PYTHONUTF8=1 uv run --project eval lancet-eval seed --corpus multihop_rag_full_dev --store eval-full
```

Check the chunking took and every article completed; the first must print one row, `structure-aware`, 500, 50, 609,
and the second none:

```bash
docker exec lancet-postgres psql -U postgres -d lancet -c "SELECT chunk_strategy, chunk_size, chunk_overlap, count(*) FROM lancet_eval_full.documents WHERE status = 'completed' GROUP BY 1, 2, 3;"
```

```bash
docker exec lancet-postgres psql -U postgres -d lancet -c "SELECT id, status, error_message FROM lancet_eval_full.documents WHERE status <> 'completed';"
```

Then preflight the store (store isolation, index identity, chunking, reachability, one generation probe):

```bash
LANCET_ENV=eval-full PYTHONUTF8=1 uv run --project eval lancet-eval preflight --store eval-full --corpus multihop_rag_full_dev
```

### C3: deepseek drive (Paid, about $0.30 to $0.60)

A one-question smoke drive first, then the rest into the same journal (`run` resumes by default):

```bash
LANCET_ENV=eval-full PYTHONUTF8=1 uv run --project eval lancet-eval run --corpus multihop_rag_full_dev --arms full/hybrid+rerank+metadata --out <C_DRIVE>/journal.jsonl --stage-cap 3 --limit 1
```

Check its one record is `success` with a non-empty answer, then:

```bash
LANCET_ENV=eval-full PYTHONUTF8=1 uv run --project eval lancet-eval run --corpus multihop_rag_full_dev --arms full/hybrid+rerank+metadata --out <C_DRIVE>/journal.jsonl --stage-cap 3
```

Read the output for `Drive stopped early`. Count: `full/hybrid+rerank+metadata` must reach 1,000.
`<C_DRIVE>/context_export.jsonl` must exist with one row per `success` record. Stop the C stack.

### C4: carry into the run of record (free)

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval replay-init --source-run <C_DRIVE> --arms full/hybrid+rerank+metadata --run <C_RUN> --corpus multihop_rag_full_dev
```

Count: `full/hybrid+rerank+metadata` must reach 1,000 (replicate 1).

### C5: readers (Paid, about $27 to $37 of Claude credit)

Submit Haiku's and Opus's batches, one after the other, without waiting; then Sonnet's and deepseek's, which go
through the sync API in the foreground (run each with `run_in_background`; Sonnet's 1,000 requests take hours).
Read each `Cost estimate` line. Haiku sends 2,000 requests (K = 2), Sonnet and Opus 1,000 each (K = 1,
`reader_replicates`), deepseek 1,000 (replicate 2).

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <C_RUN> --arm full/hybrid+rerank+metadata@haiku-5.5
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <C_RUN> --arm full/hybrid+rerank+metadata@opus-5.5
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <C_RUN> --arm full/hybrid+rerank+metadata@sonnet-5.5
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <C_RUN> --arm full/hybrid+rerank+metadata
```

If a sync submit is interrupted, rerun the same command: it sends only the answers that hold no record yet. B may be
built (Part B, steps B1 to B3) while Sonnet's answers run: a submit needs no stack.

Fetch the batch arms about every 10 minutes until it reports `0 batch(es) still pending`; each `Routing (<arm>): …`
line must say 0:

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch fetch --run <C_RUN>
```

Count: deepseek 2,000 (1,000 carried and 1,000 new), Haiku 2,000, Sonnet 1,000, Opus 1,000. For an arm whose `error`
lines show an expired or errored request, resubmit only those, at most twice:

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <C_RUN> --arm <ARM> --retry-errors
```

## Part B: 2Wiki

### B1: schema (free)

```bash
docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_2wiki;"
```

```bash
(cd gateway && atlas schema apply --env eval-2wiki --auto-approve)
```

### B2: store build (Paid, about $0.06)

Start the B stack (C's must be stopped):

```bash
LANCET_ENV=eval-2wiki ./engine/target/debug/engine
```

```bash
(cd gateway && LANCET_ENV=eval-2wiki LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_2wiki' go run .)
```

```bash
LANCET_ENV=eval-2wiki PYTHONUTF8=1 uv run --project eval lancet-eval seed --corpus twowiki_s3b_dev --store eval-2wiki
```

The chunking query must print one row, `fixed-size`, 8192, 0, 6119 (one chunk per passage), and the second none:

```bash
docker exec lancet-postgres psql -U postgres -d lancet -c "SELECT chunk_strategy, chunk_size, chunk_overlap, count(*) FROM lancet_eval_2wiki.documents WHERE status = 'completed' GROUP BY 1, 2, 3;"
```

```bash
docker exec lancet-postgres psql -U postgres -d lancet -c "SELECT id, status, error_message FROM lancet_eval_2wiki.documents WHERE status <> 'completed';"
```

```bash
LANCET_ENV=eval-2wiki PYTHONUTF8=1 uv run --project eval lancet-eval preflight --store eval-2wiki --corpus twowiki_s3b_dev
```

### B3: deepseek drive (Paid, about $0.05)

```bash
LANCET_ENV=eval-2wiki PYTHONUTF8=1 uv run --project eval lancet-eval run --corpus twowiki_s3b_dev --arms twowiki/hybrid+rerank+metadata --out <B_DRIVE>/journal.jsonl --stage-cap 3 --limit 1
```

```bash
LANCET_ENV=eval-2wiki PYTHONUTF8=1 uv run --project eval lancet-eval run --corpus twowiki_s3b_dev --arms twowiki/hybrid+rerank+metadata --out <B_DRIVE>/journal.jsonl --stage-cap 3
```

Count: 100. Stop the B stack.

### B4 and B5: carry and readers (Paid, about $1 to $2)

As C4 and C5, with `<B_DRIVE>`, `<B_RUN>`, corpus `twowiki_s3b_dev` and the `twowiki/` arms. Counts: deepseek 200,
Haiku 200, Sonnet 100, Opus 100.

## Readout (free)

For each run, `<RUN>` and `<CORPUS>` being `<C_RUN>` with `multihop_rag_full_dev` or `<B_RUN>` with
`twowiki_s3b_dev`:

```bash
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.explore_readout --run <RUN> --corpus <CORPUS>
```

```bash
PYTHONUTF8=1 uv run --project eval python -m lancet_eval.evidence_split --run <RUN> --corpus <CORPUS>
```

`score` and `compare-levers` are not run: they read the v1.0 gold-chunk table, which holds none of these questions,
and one K for every arm. No answer judges.

## Record

Fill each EXPLORE file's Result: the run directories, both readout tables, each prediction held or not on the point
estimates, the counts and every `error` line, each arm's batch IDs (`<RUN>/batches/`) and the spend per arm from the
records' usage at the declared prices. Commit the four run directories and the two Results on a new branch, never on
`main`, push it, and leave the main checkout on `main`, clean.
