# Run guide: S1 store, LlamaIndex checks, S0, S1

For the run-lane worker. Follow the steps in order, one command at a time. The pre-registrations are
[EXPERIMENT-S0.md](EXPERIMENT-S0.md) and [EXPERIMENT-S1.md](EXPERIMENT-S1.md); this guide only says how to run them.

## Rules for the whole run

- **Main checkout only** (`D:\Repos\lancet`, Git Bash, repository root), on `main` at or after the commit that added
  `PREREGISTRATION_S0` and `PREREGISTRATION_S1`, with a clean tree. Worktrees lack the live store. For a `dev`
  corpus the drive does not check the tree (D-170); only `score` and `compare-levers` refuse a dirty
  `eval/src/lancet_eval/` (D-73), after the spend. So before step 4, `git status --short eval/src/` must print
  nothing.
- **`LANCET_ENV` in the harness shell.** The seed and arm-store checks, and preflight's timeout check, read
  `LANCET_ENV` from the harness's own environment. Every `seed`, `preflight`, `run`, `run-external` and `identity`
  command below sets it inline to its stack's store: `eval-s1` in steps 1.3 to 1.5, 4.3 and 4.4, `eval` elsewhere.
  Keep it.
- **Ask the user first, once per step**, before each step marked *Paid*, *Store build*, *Store change* or
  *Held-out read*. Ask in Traditional Chinese. Give the step number, its commands, the step's total estimate from
  this guide and what it reads and writes. A yes covers that step's commands only. Run nothing on a guess.
- **No mid-run cap** (D-258). `run` and `run-external` require `--stage-cap`; pass `--stage-cap 100`, which no step
  here can reach.
- **A non-zero exit stops the run.** Tell the user what failed, with the last lines of output. Resuming a paid
  command (same command again; `run` and `run-external` default to `--resume`) needs a new yes.
- **Count after each drive** (#75). A drive can stop early and still exit 0: the rerank degrade tripwire (D-262) and
  a spend cap both print `Drive stopped early` in yellow. An `error` record is a missing pair. After steps 3.2, 3.5,
  4.2 and 4.4, read the drive's output for `Drive stopped early`, then count the journal's records per arm and
  outcome, the later record of a question and arm winning, as `score` reads them (`<RUN>` is `<S0_RUN>` or
  `<S1_RUN>`):

  ```bash
  uv run --project eval python -c "from collections import Counter; from lancet_eval.journal import load_records; from lancet_eval.pairing import deduplicate_by_arm; rs, _ = deduplicate_by_arm(load_records('<RUN>/journal.jsonl')); [print(arm, outcome, n) for (arm, outcome), n in sorted(Counter((r.graph_arm, r.outcome) for r in rs).items())]; [print('error', r.graph_arm, r.question_id, r.error_type, r.error) for r in rs if r.outcome == 'error']"
  ```

  It prints one line per arm and outcome, then one `error` line per error record. Each drive step gives the count
  each arm must reach (success plus error). On `Drive stopped early`, or on an arm short of its count, stop and tell
  the user, with the counts and every `error` line. Re-driving after a tripwire halt is the user's decision (D-174):
  ask them, and run nothing until they answer. With every count met, go on, and name every `error` line in the run
  report.
- **Never touch** `data/lancedb-eval`, the `lancet_eval` schema or `eval/corpora/multihop_rag/{heldout_split.json,
  questions.heldout.jsonl,diag_selection.json}`. No `reseed` without `--store eval-s1`.
- **Held-out budget** (D-237): S0 is held-out read 1 of 2. Steps 3.2, 3.4 and 3.5 are that one read. Nothing else
  here touches held-out questions.
- `OPENROUTER_API_KEY` must be set in the environment. Never print it or write it to a file.
- **Run directories.** In step 0, fix two paths with the date step 3 or step 4 starts, and tell the user both:
  `<S0_RUN>` = `eval/runs/<YYYY-MM-DD>-s0-multihop_rag_s0_heldout` and `<S1_RUN>` =
  `eval/runs/<YYYY-MM-DD>-s1-multihop_rag_s1_dev`. Write the literal path wherever a command below says `<S0_RUN>` or
  `<S1_RUN>`, including inside the Python strings. Shell variables do not survive between tool calls.
- **Starting and stopping a stack.** Start each of its two processes with `run_in_background`, and go on only after
  the engine logs that it serves gRPC and the gateway logs that it listens on 8080. Stop a stack by stopping both
  processes. Never run the v1.0 and the S1 stack at once: they share the ports.

## Prices behind the estimates

From the code's defaults (`eval/src/lancet_eval/measure.py`, `config/config.toml`), USD:

| Item | Price |
|---|---|
| Reader and extraction, `deepseek/deepseek-v4-flash-0731` | $0.14 per M input, $1.28 per M output |
| Embedding, `voyageai/voyage-4-large` | $0.12 per M tokens |
| Rerank, `voyageai/rerank-2.5-lite` | at most $0.00031 per call (`RERANK_UNREPORTED_CALL_CEILING_USD`, an upper bound) |

Token counts used below: the 346 seeded documents hold 812,734 o200k body tokens. A v1.0 held-out answer used
2,700 to 3,000 prompt and about 300 completion tokens (`2026-10-10-levers-heldout`), so one Lancet question costs about
$0.0011 with rerank. The engine caps the evidence at 8,192 tokens and an answer at 2,048, so one attempt stays under
about $0.0042; the ceilings below assume every question pays that once. `run` retries a failed question up to twice
(`--retries 2`), and a resumed `run-external` re-reads an `error` question up to twice; both can add to the ceiling for
the questions that fail.

| Step | Estimate | Ceiling |
|---|---|---|
| 1 S1 store build | about $2-3 | about $11 |
| 2 LlamaIndex live checks | about $0.15 | $0.20 |
| 3 S0 | about $1 | about $3.5 |
| 4 S1 | about $0.5 | about $1.8 |
| **Total** | **about $4-5** | **about $16** |

## Step 0: blockers, checkout, build

Check each blocker with `gh issue view <N> --repo mileschintw/rust-lancedb-graphrag`. A blocker is cleared when the
issue is closed and its fix is on `main` (`git log origin/main --oneline --grep "#<N>"` or the merged PR's commit).

| Issue | Blocks | Why |
|---|---|---|
| #67 seed sends no chunking | step 1 | `seed --store eval-s1` would build paragraph fragments, not merged chunks |
| #69 identity check reads only `lancet_eval` | steps 1.5, 4.3, 4.4 | `preflight --store eval-s1` and the merged drive's identity gate fail on a correct S1 store |
| #65 two-store context export | steps 4.4, 4.5 | the merged drive's export and `export-context` read only one store's checkpoints |
| #68 dev-role scoring | steps 4.6 to 4.8 | `score` and `compare-levers` read only held-out IDs and refuse a dev run |

Steps 2 and 3 do not depend on any of them. With #67 or #69 open, run steps 2 and 3 and stop before step 1. With #65
open, the run stops before step 4.4. With #68 open, steps 4.1 to 4.5 may run, and the run stops before 4.6 until it
clears.

Then `git pull --ff-only` on `main`, check that `git status` is clean, fix `<S0_RUN>` and `<S1_RUN>`, and build the
engine once:

```bash
cargo build --manifest-path engine/Cargo.toml --locked
```

Then build the two release bins the harness runs through `cargo run --release` (#74): `inspect_lancedb` for the
index identity check (steps 1.5, 3.1, 3.2, 4.1 to 4.4) and `generate_from_context` for steps 3.3 and 3.5. The harness
gives each such call 1800 s, and a cold release build takes about 70-74 minutes on this machine with
`CARGO_BUILD_JOBS=2` (`docs/testing.md`, #56), so a build left to the first call times out, possibly after a paid step. Start it with `run_in_background`:

```bash
cargo build --manifest-path engine/Cargo.toml --locked --release --bin inspect_lancedb --bin generate_from_context
```

Start no *Paid* step until this build has exited 0. A failed build stops the run.

## Step 1: S1 store build (Store build, Paid)

Ask once for the whole step: **about $2-3, ceiling about $11**. It builds the second store `data/lancedb-eval-s1` and
the schema `lancet_eval_s1`, and reads no held-out question. Needs #67 and #69 cleared.

1. Create the schema and apply the eval tables. Free; touches only `lancet_eval_s1`.

   ```bash
   docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"
   ```

   ```bash
   (cd gateway && atlas schema apply --env eval-s1 --auto-approve)
   ```

2. Start the S1 stack (see *Starting and stopping a stack*):

   ```bash
   LANCET_ENV=eval-s1 ./engine/target/debug/engine
   ```

   ```bash
   (cd gateway && LANCET_ENV=eval-s1 LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_s1' go run .)
   ```

3. Seed the 346 documents into the S1 store.
   - Estimate: embeddings for about 0.85 M tokens, about $0.10. Deepseek extraction, one call per merged chunk: at an
     average of about 200 tokens per chunk that is about 4,000 calls. Each call sends about 550 input tokens (system
     prompt and schema of about 300, plus the chunk), about $0.31 for all of them, and returns 300 to 500 output
     tokens, about $1.5-2.6. Total **about $2-3**; ceiling about $11 if every call hit the 2,048-token output cap.
   - Writes: `data/lancedb-eval-s1`, `lancet_eval_s1`, `eval/corpora/multihop_rag/document_map.eval-s1.json`.

   ```bash
   LANCET_ENV=eval-s1 uv run --project eval lancet-eval seed --corpus multihop_rag_s1_dev --store eval-s1
   ```

4. Check the chunking took. Step 1.5's preflight reports it as its `store_chunking` check (added by #67); this query
   checks the same thing directly, over the completed documents:

   ```bash
   docker exec lancet-postgres psql -U postgres -d lancet -c "SELECT chunk_strategy, chunk_size, chunk_overlap, count(*) FROM lancet_eval_s1.documents WHERE status = 'completed' GROUP BY 1, 2, 3;"
   ```

   It must print one row: `structure-merge`, 256, 25, 346. Anything else: stop and tell the user; the store is not
   the S1 store. Then list the documents that did not complete:

   ```bash
   docker exec lancet-postgres psql -U postgres -d lancet -c "SELECT id, status, error_message FROM lancet_eval_s1.documents WHERE status <> 'completed';"
   ```

   - No rows: go to step 1.5.
   - Only `failed` rows: a transient ingestion failure, which `seed` retried under a new upload; the gateway keeps
     the first upload's row (#79). The identity check skips these rows on the S1 store, but remove them so the
     store holds only the seeded documents. This is a *Store change*: ask the user first, naming the IDs.
     1. Dry run. It must list exactly the `failed` IDs above; anything else, stop and tell the user.

        ```bash
        LANCET_ENV=eval-s1 uv run --project eval lancet-eval identity pg-delete-extras --store eval-s1 --corpus multihop_rag_s1_dev
        ```

     2. Back up the schema, which `--apply` requires (`data/` is gitignored), then delete:

        ```bash
        docker exec lancet-postgres pg_dump -U postgres -d lancet -n lancet_eval_s1 > data/pg-dump-lancet_eval_s1-before-79.sql
        ```

        ```bash
        LANCET_ENV=eval-s1 uv run --project eval lancet-eval identity pg-delete-extras --store eval-s1 --corpus multihop_rag_s1_dev --apply --pg-dump data/pg-dump-lancet_eval_s1-before-79.sql
        ```

     3. Rerun the `status <> 'completed'` query; it must print no rows.
   - Any other status (`queued`, `processing`): stop and tell the user; the seed did not finish.

5. Preflight the store. It sends the arm canaries of the two merged arms, a few cents. Every check must pass,
   `store_chunking` and `index_identity` included:

   ```bash
   LANCET_ENV=eval-s1 uv run --project eval lancet-eval preflight --store eval-s1 --corpus multihop_rag_s1_dev
   ```

Stop the S1 stack.

## Step 2: LlamaIndex live checks (Paid)

Ask once for the whole step: **about $0.15, ceiling $0.20**. Neither command reads a held-out question.

1. **`input_type` forwarding** (fairness rule 7). Two embedding calls of a few tokens: under $0.0001. Writes nothing.
   It prints `dropped or ignored` or `forwarded`. Either result is fine for S0 (neither arm sends the field); record
   which one in the run report.

   ```bash
   uv run --project baselines/llamaindex python -c "import httpx,os; k=os.environ['OPENROUTER_API_KEY']; f=lambda **x: httpx.post('https://openrouter.ai/api/v1/embeddings', headers={'Authorization':'Bearer '+k}, json={'model':'voyageai/voyage-4-large','input':['Who won the match?'],'dimensions':2048,**x}, timeout=30).json()['data'][0]['embedding']; a,b=f(),f(input_type='query'); print('forwarded' if a!=b else 'dropped or ignored', max(abs(x-y) for x,y in zip(a,b)))"
   ```

2. **The 346-document export**, over the dev questions of `multihop_rag_s1_dev` (not held-out). It indexes all 346
   documents and retrieves for 100 questions: about 0.95 M embedded tokens (chunk text plus the embedded metadata),
   about $0.12, plus 100 rerank calls, at most $0.03. It writes `context_export.jsonl` and `pipeline_config.json` under
   `eval/runs/llamaindex-check/` (gitignored, not a run of record). S0 does not reuse it, since its questions differ.

   ```bash
   uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag_s1_dev --arm llamaindex --out eval/runs/llamaindex-check
   ```

   Check `pipeline_config.json`: `framework_version` must be `0.14.25`, `documents` 346, and `chunk_size`,
   `chunk_overlap`, `dense_top_k`, `rerank_model` and `keep` must equal `PREREGISTRATION_S0.external_pipelines`
   (256, 25, 20, `voyageai/rerank-2.5-lite`, 8). On a mismatch, stop and tell the user; `run-external` would refuse
   the export.

## Step 3: S0 (Held-out read 1 of 2, Paid)

Ask once for the whole step, naming it as held-out read 1 of 2: **about $1, ceiling about $3.5**. It runs on the v1.0
store. Start the v1.0 stack:

```bash
LANCET_ENV=eval ./engine/target/debug/engine
```

```bash
(cd gateway && LANCET_ENV=eval LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval' go run .)
```

1. Preflight, under a cent. A two-arm corpus sends no arm canary; this checks store isolation, index identity,
   gateway and engine reachability, and answers one corpus-generation probe question.

   ```bash
   LANCET_ENV=eval uv run --project eval lancet-eval preflight --corpus multihop_rag_s0_heldout
   ```

2. Drive the Lancet arm over the 351 held-out questions. Estimate 351 × $0.0011, **about $0.40** (ceiling $1.5).
   It writes `<S0_RUN>/journal.jsonl`, `raw_events/` and, at the end, `context_export.jsonl`. No `--gate-stage`:
   `run-external` refuses a gate-stage journal.

   ```bash
   LANCET_ENV=eval uv run --project eval lancet-eval run --corpus multihop_rag_s0_heldout --arms hybrid+rerank+metadata --out <S0_RUN>/journal.jsonl --stage-cap 100
   ```

   Count (*Count after each drive*): `hybrid+rerank+metadata` must reach 351.

3. Prompt parity (D-247), offline and free. It re-packs each Lancet row and compares it with the checkpointed
   prompt.

   ```bash
   uv run --project eval lancet-eval check-prompt-parity --run <S0_RUN>
   ```

4. Export the LlamaIndex arm over the held-out questions. Estimate about 0.95 M embedded tokens, $0.12, plus 351
   rerank calls, at most $0.11: **about $0.25**. Writes `<S0_RUN>/llamaindex/`. Check its `pipeline_config.json` as
   in step 2.2.

   ```bash
   uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag_s0_heldout --arm llamaindex --out <S0_RUN>/llamaindex
   ```

5. Answer the LlamaIndex arm with the engine's reader. Estimate 351 questions at about 3,300 prompt tokens (eight
   256-token chunks, their metadata and the policy) and 300 completion tokens: **about $0.30** (ceiling $1.5). It
   appends to `<S0_RUN>/journal.jsonl` and copies the rows into `<S0_RUN>/context_export.jsonl`.

   ```bash
   LANCET_ENV=eval uv run --project eval lancet-eval run-external --corpus multihop_rag_s0_heldout --arm llamaindex --export <S0_RUN>/llamaindex/context_export.jsonl --out <S0_RUN>/journal.jsonl --stage-cap 100
   ```

   Count (*Count after each drive*): both arms must reach 351. `run` retried each failed Lancet question twice
   inside the drive; `run-external` gives the `llamaindex` arm the same budget across resumes, re-reading only its
   `error` questions, each at most twice. So while `llamaindex` has `error` lines, ask the user for a yes to run the
   same command again (each re-read costs about $0.001 per question), at most twice, and count after each.

6. Score and compare, offline and free. Writes `report.json`, `report.md`, `lever-comparison.json` and
   `lever-comparison.md` in `<S0_RUN>`.

   ```bash
   uv run --project eval lancet-eval score --run <S0_RUN> --no-judge
   ```

   ```bash
   uv run --project eval lancet-eval compare-levers --run <S0_RUN>
   ```

7. Read the result by EXPERIMENT-S0.md › Decision rule. From `lever-comparison.json`, take the `answer_usable`
   family's `llamaindex` row (`evaluable`, `rejected`, `delta`, `ci_lo`, `ci_hi`, `n_pos`, `n_neg`, `raw_p`) and the
   `null_guards` entry for `llamaindex` (`n_pairs`, `min_pairs`, `b`, `c`, `status`). That guard is the `llamaindex`
   direction. Work out the Lancet direction by hand from the same entry: it passes iff `n_pairs >= min_pairs` and
   `(c - b) / n_pairs <= 0.10`. Write the reading into EXPERIMENT-S0.md › Result with the run directory name, then
   stop the stack.

## Step 4: S1 (Paid, dev only)

Ask once for steps 4.1 to 4.4: **about $0.5, ceiling about $1.8**. Steps 4.5 to 4.8 are offline. Step 1 must be
done. Each store's arms are driven against their own stack into one journal (D-251).

1. Small-store arms, on the v1.0 stack (start it as in step 3). Preflight sends the two small arms' canaries, a few
   cents:

   ```bash
   LANCET_ENV=eval uv run --project eval lancet-eval preflight --corpus multihop_rag_s1_dev
   ```

2. Drive the two small-store arms over the 100 dev questions. Estimate 200 × $0.0011, **about $0.22**. It writes
   `<S1_RUN>/journal.jsonl` and its export.

   ```bash
   LANCET_ENV=eval uv run --project eval lancet-eval run --corpus multihop_rag_s1_dev --arms small/hybrid+rerank+metadata,small/hybrid+graph+rerank+metadata --out <S1_RUN>/journal.jsonl --stage-cap 100
   ```

   Count (*Count after each drive*): both small arms must reach 100.

   Stop the v1.0 stack and start the S1 stack (step 1.2).

3. Preflight the S1 store, a few cents:

   ```bash
   LANCET_ENV=eval-s1 uv run --project eval lancet-eval preflight --store eval-s1 --corpus multihop_rag_s1_dev
   ```

4. Drive the two merged-store arms into the same journal. Estimate 200 questions at about 3,500 prompt tokens,
   **about $0.25**.

   ```bash
   LANCET_ENV=eval-s1 uv run --project eval lancet-eval run --corpus multihop_rag_s1_dev --arms merged/hybrid+rerank+metadata,merged/hybrid+graph+rerank+metadata --out <S1_RUN>/journal.jsonl --stage-cap 100
   ```

   Count (*Count after each drive*): all four arms must reach 100.

5. Build the two-store context export, offline. Keep the S1 stack's Postgres up (it is the same container). It reads
   each store's checkpoints from its own schema:

   ```bash
   uv run --project eval lancet-eval export-context --run <S1_RUN>
   ```

   The export's row count must equal the number of journal records whose `outcome` is `success`. Count them with:

   ```bash
   uv run --project eval python -c "from lancet_eval.journal import load_records; print(sum(r.outcome == 'success' for r in load_records('<S1_RUN>/journal.jsonl')))"
   ```

   Stop the S1 stack.

6. Score and compare, offline and free. Needs #68 cleared.

   ```bash
   uv run --project eval lancet-eval score --run <S1_RUN> --no-judge
   ```

   ```bash
   uv run --project eval lancet-eval compare-levers --run <S1_RUN>
   ```

7. The merged-store graph reading (D-263), offline and free. It first runs the D-73 check on
   `PREREGISTRATION_S1_MERGED_GRAPH` itself (`compare-levers` checks only the corpus token), then writes
   `lever-comparison-merged-graph.json` and `.md` the way `compare-levers` writes its files (LF, no NaN):

   ```bash
   uv run --project eval python -c "
   import json, sys
   from pathlib import Path
   from lancet_eval import gitcheck
   from lancet_eval.journal import read_journal_header
   from lancet_eval.lever_comparison import build_lever_comparison, render_markdown
   from lancet_eval.thresholds import PREREGISTRATION_S1_MERGED_GRAPH
   run = Path('<S1_RUN>')
   created = read_journal_header(run / 'journal.jsonl')['created_at']
   problems = gitcheck.preregistration_problems(('PREREGISTRATION_S1_MERGED_GRAPH',), created_at=float(created), require_clean_tree=True, unchanged_since_introduction=True)
   if problems: sys.exit('D-73: ' + '; '.join(problems))
   payload = build_lever_comparison(run, prereg=PREREGISTRATION_S1_MERGED_GRAPH)
   (run / 'lever-comparison-merged-graph.json').write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
   (run / 'lever-comparison-merged-graph.md').write_text(render_markdown(payload), encoding='utf-8', newline='\n')
   "
   ```

8. Read the result by EXPERIMENT-S1.md › Decision rule:
   - Chunking: the `merged/hybrid+rerank+metadata` row and guard in `lever-comparison.json`.
   - Graph: if small is kept, the `small/hybrid+graph+rerank+metadata` row and guard in the same file; if merged is
     adopted, the `merged/hybrid+graph+rerank+metadata` row and guard in `lever-comparison-merged-graph.json`.
   - Ignore `default_decisions`; S1 is applied by hand.

   Print each row and guard the rule reads (`<FILE>` is `lever-comparison.json` or
   `lever-comparison-merged-graph.json`):

   ```bash
   uv run --project eval python -c "
   import json, math
   d = json.load(open('<S1_RUN>/<FILE>', encoding='utf-8'))
   for c in d['families'][0]['comparisons']:
       ok = c['evaluable']
       print(c['arm'], 'evaluable', ok, 'n_pairs', c['n_pairs'], 'coverage', c['coverage'], 'n_pos', c['n_pos'], 'n_neg', c['n_neg'], 'delta', c['delta'])
       print('  chunking (above 0):', ok and c['n_pos'] > c['n_neg'], ' graph (+5 points):', ok and c['n_pos'] - c['n_neg'] >= math.ceil(0.05 * c['n_pairs']))
   for g in d['null_guards']:
       print('guard', g['arm'], 'evaluable', g['evaluable'], 'passes', g['passes'], 'n_pairs', g['n_pairs'], 'b', g['b'], 'c', g['c'])
   "
   ```

   Quote `evaluable`, `n_pairs`, `coverage`, `n_pos`, `n_neg` and `delta` for each row the rule reads, and the
   guard's `evaluable` and `passes`. Decide from the integers, not from the float `delta` (D-266):
   - A row with `evaluable: false` keeps small (chunking) or keeps the graph out (graph).
   - Chunking: `delta` above 0 is `n_pos > n_neg`.
   - Graph: +5 points is `n_pos - n_neg >= ceil(0.05 * n_pairs)`: a net gain of 5 at 81 to 90 pairs, 4 at 72 to 80.
     At 80 pairs a net gain of 4 can print `delta` as `0.049999999999999996`; it is +5 points and the graph passes.
   - A guard that fails or is not evaluable vetoes the choice it guards (D-264).

   Write the choice into EXPERIMENT-S1.md › Result with the run directory name. S2 replays the chosen
   `<store>/hybrid+rerank+metadata` arm, or its graph-on arm if the graph joined.

## After the run

Commit the two run directories, the filled Result sections and the S1 document map
`eval/corpora/multihop_rag/document_map.eval-s1.json` (written by step 1.3; `score` reads it for every `merged/`
record) on the run lane's own branch, never on `main`; the coordinator opens and merges the PR. Report each step's
real spend (the `observed spend` lines and the OpenRouter activity page) beside these estimates.
