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
- **Spend.** Ceilings for #163: **Claude credit $34.50, OpenRouter credit $3**. Print each step's estimate (this guide's
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

Not run yet.
