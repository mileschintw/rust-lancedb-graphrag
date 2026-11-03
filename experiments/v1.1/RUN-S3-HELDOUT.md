# Run guide: S3's held-out reader grid on 2Wiki (#163)

For the run-lane worker. `RUN_PLAN_S3_HELDOUT` in [`thresholds.py`](../../eval/src/lancet_eval/thresholds.py) fixes the
grid (D-291 in [PLAN.md](PLAN.md)). This guide only says how to run it. The grid has four readers (deepseek, Haiku 5.5,
Sonnet 5.5, Opus 5.5) and six context columns (closed-book, hybrid, and graph with each of the four writers' graphs),
over 2Wiki's 900 D-243 held-out questions.

**Blinding (D-291).** No run of this grid is scored or read for its answers until the analysis constant is frozen in
its own commit. Never run `score`, `compare-levers`, `explore_readout`, `evidence_split`, `judge`, `judge-answers`
or the unpark gates on these runs (the harness refuses each on these corpora), and never open a journal, export or
questions file to read an answer or a gold answer. The counts below read outcomes only. Record run directories, counts, error lines, batch IDs and spend.

## Rules for the whole run

- **Main checkout only** (`D:\Repos\lancet`, Git Bash, repository root), on `main` at or after the commit that merged
  `RUN_PLAN_S3_HELDOUT`. Worktrees lack the `eval-2wiki` store. `run`, `replay-init`, `closed-book-init` and every
  `batch submit` run the D-73 check and refuse a dirty `eval/src/lancet_eval`, so `git status --short --
  eval/src/lancet_eval` must print nothing before each of them.
- **`PYTHONUTF8=1` on every `uv run` command** (#84).
- **Spend.** Ceilings for #163: **Claude credit $34.50, OpenRouter credit $3**, raised during the run by the owner
  to $36.50 and $6 (see **Result**). Print each step's estimate (this guide's
  table, and each command's own `Cost estimate` line) and go on when the running total stays within the ceiling; stop
  and ask the coordinator when it does not. Read the OpenRouter balance before each drive (print the number only):

  ```bash
  PYTHONUTF8=1 uv run --project eval python -c "import httpx,os; d=httpx.get('https://openrouter.ai/api/v1/credits', headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY']}, timeout=30).json()['data']; print('balance', round(d['total_credits']-d['total_usage'], 2))"
  ```

- **Deadline.** Every Claude batch is submitted before 2026-11-03 (Pacific), when the Claude credit expires.
- **No mid-run cap** (D-258). `run` requires `--stage-cap`; pass `--stage-cap 3`.
- **A non-zero exit stops the run.** A `batch submit` that exits non-zero after printing its manifest path may have
  reached the endpoint: never resubmit it; report it.
- **Count after each drive and each finished arm** (#75), the later record of a question and arm winning. It prints
  outcomes and error lines, never an answer:

  ```bash
  PYTHONUTF8=1 uv run --project eval python -c "from collections import Counter; from lancet_eval.journal import load_records; from lancet_eval.pairing import deduplicate_by_arm; rs, _ = deduplicate_by_arm(load_records('<RUN>/journal.jsonl')); [print(arm, k, outcome, n) for (arm, k, outcome), n in sorted(Counter((r.graph_arm, r.replicate, r.outcome) for r in rs).items())]; [print('error', r.graph_arm, r.question_id, r.replicate, r.error_type, r.error) for r in rs if r.outcome == 'error']"
  ```

  An arm short of its count: stop and report, with the counts and every `error` line.
- **Never touch** `data/lancedb-eval`, `data/lancedb-eval-s1`, `data/lancedb-eval-full`, or the `eval-2wiki` store's own
  tables. Step 3 adds graph table sets beside them and never writes the store's tables.
- **Keys.** `OPENROUTER_API_KEY` must be set; every reader goes through OpenRouter (Claude over BYOK on Claude credit).
  Never print a key or write it to a file.
- **Run directories.** Fix the date `<D>` when step 1 starts and write the literal paths wherever a command names one:
  - `<CB_RUN>` = `eval/runs/<D>-s3h-twowiki_s3h_closed_book` (no drive)
  - `<H_DRIVE>` = `eval/runs/<D>-s3h-drive-twowiki_s3h_hybrid`, `<H_RUN>` = `eval/runs/<D>-s3h-twowiki_s3h_hybrid`
  - for each writer `<w>` (`deepseek`, `haiku`, `sonnet`, `opus`): `<G_DRIVE_w>` =
    `eval/runs/<D>-s3h-drive-twowiki_s3h_graph_<w>`, `<G_RUN_w>` = `eval/runs/<D>-s3h-twowiki_s3h_graph_<w>`

  `.gitignore` un-ignores `*-twowiki_s3h_*` directories so they can be committed; `-s3h-` is the tag
  `test_journal.py` reads.
- **One stack at a time.** Start each of its two processes with `run_in_background`; go on only after the engine logs
  that it serves gRPC and the gateway logs that it listens on 8080. The engine's log must say `ingest_extraction =
  false`. A `batch submit`, `batch fetch` or `closed-book-init` needs no stack.

## Cells, K and transports

| Reader | K | Transport | Thinking |
|---|---|---|---|
| deepseek | 2 | replicate 1 from the column's drive, replicate 2 through OpenRouter's sync API (D-278); closed-book: both through the sync API | off (D-271's pin) |
| Haiku 5.5 | 2 | OpenRouter Batch API, BYOK | off |
| Sonnet 5.5 | 1 | OpenRouter Batch API, BYOK (not D-280's sync path) | on, effort low |
| Opus 5.5 | 1 | OpenRouter Batch API, BYOK | on, effort low |

Every cell is `core` except Sonnet on graph-haiku, graph-sonnet and graph-opus (`optional`: only if new credit
arrives).

## Prices behind the estimates

Per answer, from run B's measured spend on the 2Wiki dev questions (EXPLORE-B-2WIKI-READERS.md, Result), the hybrid
column: Haiku batch $0.0003, Opus batch $0.012, Sonnet $0.0122 on the sync API, so about $0.006 to $0.007 on the batch
(half price, plus a few reasoning tokens at effort low), deepseek sync $0.0002, a deepseek drive $0.0008 a question
(embedding, rerank and answer). Graph columns add graph facts to the prompt; they are estimated at 1.3 times the hybrid
figures. A closed-book prompt is the model-only policy and the question (about 150 tokens).

| Column | deepseek (OpenRouter) | Haiku 5.5, K = 2 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|---|
| closed-book | 1,800 sync answers, about $0.10 | about $0.15 | about $1.5 | about $3 |
| hybrid | drive about $0.70, replicate 2 about $0.20 | about $0.55 | about $6 | about $11 |
| each graph column | drive about $0.70, replicate 2 about $0.25 | about $0.70 | about $8 (optional on three) | about $14 |

- **Steps 1 and 2** (closed-book and hybrid, every reader): about **$22 of Claude credit**, about $1 of OpenRouter.
- **Step 3**, in its order: Opus on graph-deepseek about $14 more. That brings the Claude total to about $36, above
  the $34.50 ceiling. Then the Haiku graph cells (about $3 together), Sonnet on graph-deepseek (about $8), and Opus on
  the other three graphs (about $42).
- **OpenRouter**: the four graph drives and their replicates come to about $4 more, about $5 in all, above the $3
  ceiling.

Read each step's own `Cost estimate` lines. They replace these figures, and stop at the first step whose running
total passes a ceiling.

## Step 0: checkout, build and files (free)

1. `git pull --ff-only` on `main`; `git status` must be clean.
2. Build the engine, then the release bins the harness runs: `inspect_lancedb` for the index identity check,
   `generate_from_context` for `closed-book-init`, `batch submit` and `fetch`, and `import_graph_extractions` for step
   3. Run the second with `run_in_background`; start no paid step before both exit 0.

   ```bash
   cargo build --manifest-path engine/Cargo.toml --locked
   ```

   ```bash
   cargo build --manifest-path engine/Cargo.toml --locked --release --bin inspect_lancedb --bin generate_from_context --bin import_graph_extractions
   ```

3. Write the source files. Each command prints its digests.

   ```bash
   PYTHONUTF8=1 uv run --project eval python -m lancet_eval.twowiki fetch
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval python -m lancet_eval.twowiki_b
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval python -m lancet_eval.twowiki_h
   ```

   `twowiki_b` must print `twowiki/.cache/documents.jsonl: 57d038e26b2b…`. `twowiki_h` must print split
   `7590e2b3281d…` and writes `twowiki/.cache/questions.heldout.jsonl`, whose sha256 goes into the report. It holds the
   held-out gold answers: never open it. It also writes `twowiki/.cache/question_types.heldout.json`, each question's
   2Wiki type and nothing else (#167); its sha256 goes into the report too.
4. Check each column's gates: D-73, the split's inputs and the 900 held-out IDs. Each prints `900`:

   ```bash
   for c in closed_book hybrid; do PYTHONUTF8=1 uv run --project eval python -c "import sys; from lancet_eval.corpus import load_corpus; from lancet_eval.run import require_split_gates; c = load_corpus(sys.argv[1]); require_split_gates(c, c.questions); print(len(c.questions))" twowiki_s3h_$c; done
   ```

## Step 1: closed-book column (Paid, about $4.65 of Claude credit and $0.10 of OpenRouter)

Write the rows (free; one model-only row per question, packed by the bin):

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval closed-book-init --run <CB_RUN> --corpus twowiki_s3h_closed_book
```

It must print 900 rows. Send deepseek's 1,800 sync answers first, with `run_in_background` (about $0.10):

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <CB_RUN> --arm twowiki/closed-book
```

A closed-book question has no drive record, so each Claude submit estimates from deepseek's answer to that question.
Where deepseek has none yet, it assumes the request's full output limit, so the estimate is a high bound. With
deepseek's answers in (or, if the deadline presses, on that bound), submit the three Claude batches one after the
other without waiting:

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <CB_RUN> --arm twowiki/closed-book@opus-5.5
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <CB_RUN> --arm twowiki/closed-book@sonnet-5.5
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <CB_RUN> --arm twowiki/closed-book@haiku-5.5
```

Go on to step 2 while these run. Fetch about every 10 minutes until it reports `0 batch(es) still pending`; each
`Routing (<arm>): …` line must say 0:

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch fetch --run <CB_RUN>
```

Count: `twowiki/closed-book` 900 at replicate 1 and 900 at replicate 2, Haiku 900 at each of replicates 1 and 2,
Sonnet 900, Opus 900. For an arm whose `error` lines show an expired or errored request, resubmit only those, at most
twice:

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <CB_RUN> --arm <ARM> --retry-errors
```

## Step 2: hybrid column (Paid, about $17.5 of Claude credit and $0.90 of OpenRouter)

Start the 2Wiki stack:

```bash
LANCET_ENV=eval-2wiki ./engine/target/debug/engine
```

```bash
(cd gateway && LANCET_ENV=eval-2wiki LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_2wiki' go run .)
```

Preflight (store isolation, index identity, chunking, reachability, one generation probe):

```bash
LANCET_ENV=eval-2wiki PYTHONUTF8=1 uv run --project eval lancet-eval preflight --store eval-2wiki --corpus twowiki_s3h_hybrid
```

Drive deepseek over the 900 questions:

```bash
LANCET_ENV=eval-2wiki PYTHONUTF8=1 uv run --project eval lancet-eval run --corpus twowiki_s3h_hybrid --arms twowiki/hybrid+rerank+metadata --out <H_DRIVE>/journal.jsonl --stage-cap 3
```

Read the output for `Drive stopped early`. Count: 900. `<H_DRIVE>/context_export.jsonl` must exist with one row per
`success` record. Stop the stack. As in run B, `run` leaves `partial: true` in the header, since the corpus also lists
the reader arms; with every question holding a record, set that one field to `false` by hand and keep the rest of the
file byte-identical.

Carry the drive into the run of record (free). The corpus must be the drive's own (D-291):

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval replay-init --source-run <H_DRIVE> --arms twowiki/hybrid+rerank+metadata --run <H_RUN> --corpus twowiki_s3h_hybrid
```

Submit Opus's, Sonnet's and Haiku's batches, then deepseek's replicate 2 (sync, `run_in_background`):

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <H_RUN> --arm twowiki/hybrid+rerank+metadata@opus-5.5
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <H_RUN> --arm twowiki/hybrid+rerank+metadata@sonnet-5.5
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <H_RUN> --arm twowiki/hybrid+rerank+metadata@haiku-5.5
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <H_RUN> --arm twowiki/hybrid+rerank+metadata
```

Fetch as in step 1. Count: deepseek 1,800 (900 carried and 900 new), Haiku 1,800, Sonnet 900, Opus 900.

## Step 3: graph columns (after #145's deepseek extraction merges; the coordinator says when)

Not yet runnable; this lane fills it in before it runs. Per writer, in the order Opus x graph-deepseek first:

1. Build `answers.jsonl` (`{"text": <passage unit>, "content": <answer>}` a line) from #145's extraction results
   for that writer, and import it into the `eval-2wiki` store as the writer's own graph table set with
   `import_graph_extractions` (#148's path; `--check` first, then the import), under `LANCET_ENV=eval-2wiki-s3h-<w>`
   (`config/config.eval-2wiki-s3h-<w>.toml`: table set `s3h_<w>`), with `--chunk-strategy fixed-size --chunk-size 8192
   --chunk-overlap 0`. Record the set's entity and edge counts, and that the store's own tables are unchanged.
2. Start the stack with the engine on `LANCET_ENV=eval-2wiki-s3h-<w>` (its log names `graph_table_set="s3h_<w>"`) and
   the gateway and harness on `eval-2wiki`, preflight, and drive `twowiki/hybrid+graph+rerank+metadata` with corpus
   `twowiki_s3h_graph_<w>` into `<G_DRIVE_w>`, as in step 2.
3. `replay-init` into `<G_RUN_w>` and submit as in step 2, Opus first; Sonnet only on graph-deepseek unless new credit
   arrives.

## Record

For each run directory: its corpus and column, the counts per arm and replicate and every `error` line, each arm's
batch IDs (`<RUN>/batches/`), the thinking setting sent and the measured `reasoning_tokens` (total and per answer,
D-289), and the spend per arm from the records' usage at the declared prices (Claude at half the list price, deepseek's
sync answers at the reference price). No score of any kind (D-291).

Commit the full run directories on a new branch, never on `main`, with the record in this file's **Result** section
below; push it and leave the main checkout on `main`, clean:

- Gzip every file over 50 MB (`gzip -9 -n`) and check that each unpacked file matches its sha256. Add a `README.md` to
  each directory that holds a `.gz`, saying how to unpack it: `find <dir> -name '*.gz' -exec gunzip -k {} \;`.
- Give each directory a `.gitattributes` of `* -text`: the runs write some files with CRLF, and `core.autocrlf` would
  change their bytes.
- Copy `eval/corpora/twowiki/.cache/question_types.heldout.json` into each run directory as `question_types.json`
  (#167), so the analysis can split by 2Wiki question type from the run directories alone. It holds no answer.
- The run files hold Wikipedia passage text; the owner chose to commit run directories in full ("全都公開repo備份全文").

## Result

Run 2026-11-01 to 2026-11-02 from main `19998782` (the harness of #173). Nothing was scored or read for its answers
(D-291); every count below is of record outcomes, and every spend is from the records' usage.

### Cells

15 of the 24 cells ran; the other 9 wait for new Claude credit (owner's ruling below).

| Column | deepseek (K=2) | Haiku (K=2) | Sonnet (K=1) | Opus (K=1) |
|---|---|---|---|---|
| closed-book | ran | ran | ran | ran |
| hybrid | ran | ran | ran | ran |
| graph-deepseek | ran | ran | waits (core) | ran |
| graph-haiku | ran | ran | waits (optional) | waits (core) |
| graph-sonnet | ran | waits (core) | waits (optional) | waits (core) |
| graph-opus | ran | waits (core) | waits (optional) | waits (core) |

A waiting cell needs only `batch submit` and `batch fetch` on its committed run directory: every graph column's
deepseek drive, replay run and replicate 2 are already here.

### Owner's rulings during the run

- Claude credit: "Raise cap to ~$36.5". Run closed-book and hybrid for all readers, then Opus × graph-deepseek in
  full; every other graph Claude cell waits for the next credit, and no cell runs in part.
- OpenRouter credit: "Raise to $6 (Recommended)", enough for every deepseek cell with its replicate.
- Backups: "每一輪實驗跑完都應該要做備份，這才是好習慣". Each run directory was committed and pushed as soon as its run
  finished, on this branch.
- Pause: "這一輪還開著、還在進行的工作做完就收尾，下次繼續". The run stopped on 2026-11-02 at 02:50 after the
  graph-sonnet drive.
- Resume: "Yes, resume today", to the coordinator's plan. With the $3.06 left: Haiku × graph-deepseek and
  Haiku × graph-haiku; then rerun only the 4 drive records that ended in `RetrieveHybrid timed out`, blind, keeping
  the original errors; then the remaining deepseek cells.

### Graph tables

`import_graph_extractions` wrote one side table set per writer into `data/lancedb-eval-2wiki`, from #172's committed
extraction results, with `--chunk-strategy fixed-size --chunk-size 8192 --chunk-overlap 0`:

| Set | Answers imported | Entities | Entity edges |
|---|---|---|---|
| `s3h_deepseek` | 6,077 | 33,811 | 41,187 |
| `s3h_haiku` | 6,119 | 36,476 | 49,416 |
| `s3h_sonnet` | 6,119 | 35,658 | 50,111 |
| `s3h_opus` | 6,119 | 34,108 | 47,953 |

The store's own seven tables are unchanged: the path, size and mtime of all 116,282 of their files match a listing
taken before the first import. Only `__manifest` changed, as it registers the new tables.

### What differed from this guide

- **First graph-deepseek drive, set aside.** It ran while the Haiku, Sonnet and Opus imports still ran. Dense
  retrieval took about 2.7 s of the 3,080 ms retrieve budget, so five reranks in a row timed out and the rerank
  tripwire stopped the drive after 5 records ($0.0052). Those records are not in any run directory; the drive was
  rerun from empty after the imports finished, with dense retrieval back at about 1.2 s.
- **Preflight warm-up.** A fresh engine twice failed `corpus_generation` on the graph columns: the probe came back
  without a snapshot. One query through the gateway first made it pass every time after.
- **Header `partial`.** As in step 2, each drive left `partial: true` (the corpus lists reader arms too), set to
  `false` by hand before `replay-init`, every other byte unchanged.
- **Reruns of four retrieval timeouts.** Four drive records ended in `RetrieveHybrid timed out` after both retries:
  graph-haiku `a3ac1ca2…`, `5498821a…`, `122324e8…` and graph-sonnet `cea1f56e…`. The harness has no single-question
  rerun, so each column got a `<date>-s3h-drive-twowiki_s3h_graph_<w>-rerun` directory:
  1. A copy of the drive journal without those records, which `run --resume` then drove alone.
  2. The new records appended byte for byte to the drive journal and to the run of record. A carried record is the
     drive record unchanged, since both use one corpus (checked on all 900). The original errors stay; the later
     record of a question wins (#75).
  3. Each new success's export row appended to both exports, and its `export_row_sha256` inserted into the run
     header's `replay_source.row_sha256`, as `replay-init` computes it.
  4. The `-rerun` directory then trimmed to its header, the rerun records and their export rows.

  `122324e8…` and `cea1f56e…` succeeded. `a3ac1ca2…` and `5498821a…` timed out again on all three attempts with the
  machine otherwise idle, so they stay errors.
- **`122324e8…` has one deepseek answer.** Its replicate-2 slot holds the `base_error` record that the replicate-2
  submit wrote while its drive record was still an error, and `batch submit` treats that as final. Sending its
  replicate 2 would need a harness change. The Haiku batch on graph-haiku went after the rerun and includes it.
- **Two over-length prompts.** Every Claude reader on the hybrid and graph columns failed `f06252fc…` and
  `a1d9a65c…`: `OpenRouter prompt_tokens 10218` and `8702 exceeds budget 8192`. Claude's tokenizer counts those
  packed contexts above the engine's 8,192 budget. The errors are billed and final.

### Spend

- **Claude:** $34.50 of the $36.50 ceiling, at half list price from the records' usage.
  - closed-book $6.09
  - hybrid $16.61
  - Opus × graph-deepseek $10.74
  - Haiku × graph-deepseek $0.53
  - Haiku × graph-haiku $0.53
- **OpenRouter:** $4.82 by the records, of the $6 ceiling: $3.95 for the five column drives at their observed
  spend, $0.87 for the six sync runs at the reference price, and $0.005 for the drive set aside. That covers
  the deepseek cells, but not the entity-name embeddings of the four imports, which are not itemised. The account
  balance fell only $2.80 ($17.85 to $15.05), so the drives' observed spend overstates what was billed.

### Per run directory

Counts are per arm and replicate after #75's deduplication; an error line lists every question ID that ended in
it. A drive row's spend is the drive's observed spend; a sync or batch row's is from usage at the declared prices.
Each graph and hybrid run of record carries its drive's records, so its replicate-1 deepseek row is the drive. The
drive directories (`<date>-s3h-drive-…`) and the two `-rerun` directories are committed alongside the six below.

### `eval/runs/2026-11-01-s3h-twowiki_s3h_closed_book`

Corpus `twowiki_s3h_closed_book`, column `closed-book`.

| Arm | Replicate | Success | Error | Prompt / completion tokens | Reasoning tokens (per answer) | Thinking | Spend | Batch IDs |
|---|---|---|---|---|---|---|---|---|
| `twowiki/closed-book` | 1 | 892 | 8 | 67,237 / 132,701 | 0 (0.0) | off (D-271) | $0.0428 | `sync-twowiki_closed_book-1-1793575483` |
| `twowiki/closed-book` | 2 | 891 | 9 | 67,237 / 127,983 | 0 (0.0) | off (D-271) | $0.0414 | `sync-twowiki_closed_book-1-1793575483` |
| `twowiki/closed-book@haiku-5.5` | 1 | 900 | 0 | 484,634 / 216,029 | 0 (0.0) | off | $0.0782 | `batch-1793578474-zHxjRSpMpBLXvaVgEKEZ` |
| `twowiki/closed-book@haiku-5.5` | 2 | 900 | 0 | 484,634 / 218,591 | 0 (0.0) | off | $0.0789 | `batch-1793578474-zHxjRSpMpBLXvaVgEKEZ` |
| `twowiki/closed-book@opus-5.5` | 1 | 900 | 0 | 485,534 / 325,449 | 127,523 (141.7) | on, effort low | $4.2256 | `batch-1793578463-ZRhDqLcyj0dnjGpGV102` |
| `twowiki/closed-book@sonnet-5.5` | 1 | 900 | 0 | 485,534 / 244,111 | 2,006 (2.2) | on, effort low | $1.7061 | `batch-1793578469-ft4pcsEQRV5uzXI1hYaI` |

Errors (each a final record; the later record of a question wins, #75):

- `twowiki/closed-book` r1, 7: OpenRouter completion incomplete: finish_reason 'length' (0083038e…, 0495b7fc…, 1900f760…, 5674280a…, 695689d2…, 7a894f7c…, cbb5ca82…)
- `twowiki/closed-book` r1, 1: notice length exceeds limit 1024 (e2c19fd8…)
- `twowiki/closed-book` r2, 4: OpenRouter completion incomplete: finish_reason 'length' (0495b7fc…, 5674280a…, a6160eee…, d323fb02…)
- `twowiki/closed-book` r2, 5: notice length exceeds limit 1024 (036c8248…, 08b4d30e…, b6aec5ee…, e2c19fd8…, f3a16239…)

### `eval/runs/2026-11-01-s3h-twowiki_s3h_hybrid`

Corpus `twowiki_s3h_hybrid`, column `hybrid`.

| Arm | Replicate | Success | Error | Prompt / completion tokens | Reasoning tokens (per answer) | Thinking | Spend | Batch IDs |
|---|---|---|---|---|---|---|---|---|
| `twowiki/hybrid+rerank+metadata` | 1 | 900 | 0 | n/a (drive) | 0 (0.0) | off (D-271) | $0.7822 (drive, observed) | drive |
| `twowiki/hybrid+rerank+metadata` | 2 | 892 | 8 | 2,258,893 / 187,045 | 0 (0.0) | off (D-271) | $0.1573 | `sync-twowiki_hybrid_rerank_metadata-1-1793579380` |
| `twowiki/hybrid+rerank+metadata@haiku-5.5` | 1 | 898 | 2 | 4,153,152 / 232,438 | 0 (0.0) | off | $0.2658 | `batch-1793579368-4p04yiR2ZhqjbCJaVlQz` |
| `twowiki/hybrid+rerank+metadata@haiku-5.5` | 2 | 898 | 2 | 4,153,152 / 233,441 | 0 (0.0) | off | $0.2660 | `batch-1793579368-4p04yiR2ZhqjbCJaVlQz` |
| `twowiki/hybrid+rerank+metadata@opus-5.5` | 1 | 898 | 2 | 4,154,052 / 241,834 | 2,086 (2.3) | on, effort low | $10.7264 | `batch-1793579350-THfK2ZEuPLAB9L6pGK6l` |
| `twowiki/hybrid+rerank+metadata@sonnet-5.5` | 1 | 898 | 2 | 4,154,052 / 238,286 | 0 (0.0) | on, effort low | $5.3455 | `batch-1793579358-oJdno8lb1X06n3Mu1eRR` |

Errors (each a final record; the later record of a question wins, #75):

- `twowiki/hybrid+rerank+metadata` r2, 2: OpenRouter completion incomplete: finish_reason 'length' (3602458e…, a431a938…)
- `twowiki/hybrid+rerank+metadata` r2, 6: answer basis 'mixed' requires at least one cited evidence ID (1d507a43…, 433bcf3d…, 594ca256…, 90ecd947…, ace717d0…, e437dddd…)
- `twowiki/hybrid+rerank+metadata@haiku-5.5` r1, 1: OpenRouter prompt_tokens 10218 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+rerank+metadata@haiku-5.5` r1, 1: OpenRouter prompt_tokens 8702 exceeds budget 8192 (a1d9a65c…)
- `twowiki/hybrid+rerank+metadata@haiku-5.5` r2, 1: OpenRouter prompt_tokens 10218 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+rerank+metadata@haiku-5.5` r2, 1: OpenRouter prompt_tokens 8702 exceeds budget 8192 (a1d9a65c…)
- `twowiki/hybrid+rerank+metadata@opus-5.5` r1, 1: OpenRouter prompt_tokens 10219 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+rerank+metadata@opus-5.5` r1, 1: OpenRouter prompt_tokens 8703 exceeds budget 8192 (a1d9a65c…)
- `twowiki/hybrid+rerank+metadata@sonnet-5.5` r1, 1: OpenRouter prompt_tokens 10219 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+rerank+metadata@sonnet-5.5` r1, 1: OpenRouter prompt_tokens 8703 exceeds budget 8192 (a1d9a65c…)

### `eval/runs/2026-11-01-s3h-twowiki_s3h_graph_deepseek`

Corpus `twowiki_s3h_graph_deepseek`, column `graph-deepseek`.

| Arm | Replicate | Success | Error | Prompt / completion tokens | Reasoning tokens (per answer) | Thinking | Spend | Batch IDs |
|---|---|---|---|---|---|---|---|---|
| `twowiki/hybrid+graph+rerank+metadata` | 1 | 900 | 0 | n/a (drive) | 0 (0.0) | off (D-271) | $0.7740 (drive, observed) | drive |
| `twowiki/hybrid+graph+rerank+metadata` | 2 | 890 | 10 | 2,261,169 / 184,930 | 0 (0.0) | off (D-271) | $0.1568 | `sync-twowiki_hybrid_graph_rerank_metadata-1-1793605866` |
| `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` | 1 | 898 | 2 | 4,156,667 / 234,502 | 0 (0.0) | off | $0.2665 | `batch-1793668571-Ci1mWuUJYmemW8ITBPOb` |
| `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` | 2 | 898 | 2 | 4,156,667 / 235,526 | 0 (0.0) | off | $0.2667 | `batch-1793668571-Ci1mWuUJYmemW8ITBPOb` |
| `twowiki/hybrid+graph+rerank+metadata@opus-5.5` | 1 | 898 | 2 | 4,157,567 / 242,323 | 2,115 (2.4) | on, effort low | $10.7384 | `batch-1793605854-cSuRCk8qjIA1WkyU7ZOt` |

Errors (each a final record; the later record of a question wins, #75):

- `twowiki/hybrid+graph+rerank+metadata` r2, 10: answer basis 'mixed' requires at least one cited evidence ID (0277d678…, 3f04140e…, 48c0c6fa…, 5f9dfa7c…, 90ecd947…, cea1f56e…, d323fb02…, d58ede7c…, dcf15106…, f34d1886…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r1, 1: OpenRouter prompt_tokens 10218 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r1, 1: OpenRouter prompt_tokens 8702 exceeds budget 8192 (a1d9a65c…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r2, 1: OpenRouter prompt_tokens 10218 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r2, 1: OpenRouter prompt_tokens 8702 exceeds budget 8192 (a1d9a65c…)
- `twowiki/hybrid+graph+rerank+metadata@opus-5.5` r1, 1: OpenRouter prompt_tokens 10219 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+graph+rerank+metadata@opus-5.5` r1, 1: OpenRouter prompt_tokens 8703 exceeds budget 8192 (a1d9a65c…)

### `eval/runs/2026-11-01-s3h-twowiki_s3h_graph_haiku`

Corpus `twowiki_s3h_graph_haiku`, column `graph-haiku`.

| Arm | Replicate | Success | Error | Prompt / completion tokens | Reasoning tokens (per answer) | Thinking | Spend | Batch IDs |
|---|---|---|---|---|---|---|---|---|
| `twowiki/hybrid+graph+rerank+metadata` | 1 | 896 | 4 | n/a (drive) | 0 (0.0) | off (D-271) | $0.8263 (drive, observed) | drive |
| `twowiki/hybrid+graph+rerank+metadata` | 2 | 882 | 18 | 2,248,577 / 182,942 | 0 (0.0) | off (D-271) | $0.1556 | `sync-twowiki_hybrid_graph_rerank_metadata-1-1793611501` |
| `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` | 1 | 894 | 6 | 4,138,210 / 237,603 | 0 (0.0) | off | $0.2663 | `batch-1793669092-R22CVvoloMK9FrymB9G2` |
| `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` | 2 | 894 | 6 | 4,138,210 / 233,293 | 0 (0.0) | off | $0.2652 | `batch-1793669092-R22CVvoloMK9FrymB9G2` |

Errors (each a final record; the later record of a question wins, #75):

- `twowiki/hybrid+graph+rerank+metadata` r1, 2: Node 'RetrieveHybrid' timed out (5498821a…, a3ac1ca2…)
- `twowiki/hybrid+graph+rerank+metadata` r1, 2: answer basis 'mixed' requires at least one cited evidence ID (90ecd947…, ae85fccd…)
- `twowiki/hybrid+graph+rerank+metadata` r2, 13: answer basis 'mixed' requires at least one cited evidence ID (38da155f…, 3cc3895c…, 82de9a9f…, 899ecc9e…, 9301d39a…, ace717d0…, b4f937fa…, c21f7548…, cce18dc7…, dcf15106…, dfe3407a…, e7f8e988…, f92dceb2…)
- `twowiki/hybrid+graph+rerank+metadata` r2, 5: the base arm's record is an error (None): nothing to replay (122324e8…, 5498821a…, 90ecd947…, a3ac1ca2…, ae85fccd…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r1, 1: OpenRouter prompt_tokens 10218 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r1, 1: OpenRouter prompt_tokens 8702 exceeds budget 8192 (a1d9a65c…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r1, 4: the base arm's record is an error (None): nothing to replay (5498821a…, 90ecd947…, a3ac1ca2…, ae85fccd…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r2, 1: OpenRouter prompt_tokens 10218 exceeds budget 8192 (f06252fc…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r2, 1: OpenRouter prompt_tokens 8702 exceeds budget 8192 (a1d9a65c…)
- `twowiki/hybrid+graph+rerank+metadata@haiku-5.5` r2, 4: the base arm's record is an error (None): nothing to replay (5498821a…, 90ecd947…, a3ac1ca2…, ae85fccd…)

### `eval/runs/2026-11-01-s3h-twowiki_s3h_graph_sonnet`

Corpus `twowiki_s3h_graph_sonnet`, column `graph-sonnet`.

| Arm | Replicate | Success | Error | Prompt / completion tokens | Reasoning tokens (per answer) | Thinking | Spend | Batch IDs |
|---|---|---|---|---|---|---|---|---|
| `twowiki/hybrid+graph+rerank+metadata` | 1 | 898 | 2 | n/a (drive) | 0 (0.0) | off (D-271) | $0.7911 (drive, observed) | drive |
| `twowiki/hybrid+graph+rerank+metadata` | 2 | 882 | 18 | 2,254,270 / 183,288 | 0 (0.0) | off (D-271) | $0.1560 | `sync-twowiki_hybrid_graph_rerank_metadata-1-1793669209` |

Errors (each a final record; the later record of a question wins, #75):

- `twowiki/hybrid+graph+rerank+metadata` r1, 2: answer basis 'mixed' requires at least one cited evidence ID (48c0c6fa…, 90ecd947…)
- `twowiki/hybrid+graph+rerank+metadata` r2, 16: answer basis 'mixed' requires at least one cited evidence ID (0277d678…, 11854514…, 1d507a43…, 3f04140e…, 821e65dc…, 82de9a9f…, 899ecc9e…, 8bb8b730…, 9301d39a…, ace717d0…, c9238c7c…, d88af85e…, e1a69e46…, e7f8e988…, f34d1886…, f7ff22da…)
- `twowiki/hybrid+graph+rerank+metadata` r2, 2: the base arm's record is an error (None): nothing to replay (48c0c6fa…, 90ecd947…)

### `eval/runs/2026-11-02-s3h-twowiki_s3h_graph_opus`

Corpus `twowiki_s3h_graph_opus`, column `graph-opus`.

| Arm | Replicate | Success | Error | Prompt / completion tokens | Reasoning tokens (per answer) | Thinking | Spend | Batch IDs |
|---|---|---|---|---|---|---|---|---|
| `twowiki/hybrid+graph+rerank+metadata` | 1 | 900 | 0 | n/a (drive) | 0 (0.0) | off (D-271) | $0.7761 (drive, observed) | drive |
| `twowiki/hybrid+graph+rerank+metadata` | 2 | 880 | 20 | 2,258,154 / 185,543 | 0 (0.0) | off (D-271) | $0.1568 | `sync-twowiki_hybrid_graph_rerank_metadata-1-1793674094` |

Errors (each a final record; the later record of a question wins, #75):

- `twowiki/hybrid+graph+rerank+metadata` r2, 1: OpenRouter completion incomplete: finish_reason 'length' (e9940b6a…)
- `twowiki/hybrid+graph+rerank+metadata` r2, 18: answer basis 'mixed' requires at least one cited evidence ID (4e9561d4…, 5905858e…, 6718770a…, 695689d2…, 75d4c76e…, 8055aca4…, 82de9a9f…, 90ecd947…, 9301d39a…, a2468754…, ad193b18…, c2b303ae…, c5d5e525…, e7e76caa…, f329c007…, f7ff22da…, f92dceb2…, fd848f86…)
- `twowiki/hybrid+graph+rerank+metadata` r2, 1: notice length exceeds limit 1024 (3f2eb012…)
