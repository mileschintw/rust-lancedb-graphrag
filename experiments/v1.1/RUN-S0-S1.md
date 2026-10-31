# Run guide: S1 store, LlamaIndex checks, S0, S1

For the run-lane worker. Follow the steps in order, one command at a time. The pre-registrations are
[EXPERIMENT-S0.md](EXPERIMENT-S0.md) and [EXPERIMENT-S1.md](EXPERIMENT-S1.md); this guide only says how to run them.

## Rules for the whole run

- **Main checkout only** (`D:\Repos\lancet`, Git Bash, repository root), on `main` at or after the commit that added
  `PREREGISTRATION_S0` and `PREREGISTRATION_S1`, with a clean tree. Worktrees lack the live store, and the drive
  refuses a dirty `eval/src/` (D-73).
- **Ask the user first** before every step marked *Paid*, *Store build* or *Held-out read*. In the question, give the
  step number, the command, the estimate from this guide and what it reads and writes. Run nothing on a guess.
- **No mid-run cap** (D-258). `run` and `run-external` require `--stage-cap`; pass `--stage-cap 100`, which no step
  here can reach. A step that fails partway is resumed with the same command (both default to `--resume`).
- **Never touch** `data/lancedb-eval`, the `lancet_eval` schema or `eval/corpora/multihop_rag/{heldout_split.json,
  questions.heldout.jsonl,diag_selection.json}`. No `reseed` without `--store eval-s1`.
- **Held-out budget** (D-237): S0 is held-out read 1 of 2. Steps 3.2, 3.4 and 3.5 are that one read. Nothing else
  here touches held-out questions.
- `OPENROUTER_API_KEY` must be set in the shell. Never print it or write it to a file.
- Set the run directories once per shell, with the date the run starts:

  ```bash
  S0_RUN=eval/runs/2026-11-01-s0-multihop_rag_s0_heldout
  S1_RUN=eval/runs/2026-11-01-s1-multihop_rag_s1_dev
  ```

## Prices behind the estimates

From the code's defaults (`eval/src/lancet_eval/measure.py`, `config/config.toml`), USD:

| Item | Price |
|---|---|
| Reader and extraction, `deepseek/deepseek-v4-flash-0731` | $0.14 per M input, $1.28 per M output |
| Embedding, `voyageai/voyage-4-large` | $0.12 per M tokens |
| Rerank, `voyageai/rerank-2.5-lite` | at most $0.00031 per call (`RERANK_UNREPORTED_CALL_CEILING_USD`, an upper bound) |

Token counts used below: the 346 seeded documents hold 812,734 o200k body tokens. A v1.0 held-out answer used
2,700 to 3,000 prompt and about 300 completion tokens (`2026-10-10-levers-heldout`), so one Lancet question costs about
$0.0011 with rerank. The engine caps a prompt at 8,192 tokens and an answer at 2,048, so no question can cost more
than $0.0042.

| Step | Estimate | Ceiling |
|---|---|---|
| 1 S1 store build | about $2-3 | about $11 |
| 2 LlamaIndex live checks | about $0.15 | $0.20 |
| 3 S0 | about $1 | about $3.5 |
| 4 S1 | about $0.5 | about $1.8 |
| **Total** | **about $4-5** | **about $16** |

## Step 0: blockers to check first

Read each issue's state with `gh issue view <N> --repo mileschintw/rust-lancedb-graphrag`.

- **#67** (seed sends no chunking): until it merges, `seed --store eval-s1` builds paragraph fragments, not merged
  chunks. **Do not run step 1 before #67 merges.**
- **#65** (two-store context export): until it merges, step 4.5 uses the stopgap given there.

Then `git pull --ff-only` on `main`, check `git status` is clean, and build the engine once:

```bash
cargo build --manifest-path engine/Cargo.toml --locked
```

The generate-only bin (`generate_from_context`) is built by cargo on its first use in step 3.

## Step 1: S1 store build (Store build, Paid)

Builds the second store `data/lancedb-eval-s1` and the schema `lancet_eval_s1`. It reads no held-out question.

1. Create the schema and apply the eval tables. Free; one-time; touches only `lancet_eval_s1`.

   ```bash
   docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"
   ```

   ```bash
   (cd gateway && atlas schema apply --env eval-s1 --auto-approve)
   ```

2. Start the S1 stack, each in its own terminal, and leave both running for steps 1.3 to 1.4:

   ```bash
   LANCET_ENV=eval-s1 ./engine/target/debug/engine
   ```

   ```bash
   (cd gateway && LANCET_ENV=eval-s1 LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_s1' go run .)
   ```

3. Seed the 346 documents into the S1 store. **Store build, Paid.**
   - Estimate: embeddings for about 0.85 M tokens, about $0.10. Deepseek extraction, one call per merged chunk: the
     seed prints the chunk count, and at an average of about 200 tokens per chunk it is about 4,000 calls. Each call
     sends about 550 input tokens (system prompt and schema of about 300, plus the chunk), about $0.31 for all of them,
     and returns 300 to 500 output tokens, about $1.5-2.6. Total **about $2-3**; ceiling about $11 if every call hit the
     2,048-token output cap.
   - Writes: `data/lancedb-eval-s1`, `lancet_eval_s1`, `eval/corpora/multihop_rag/document_map.eval-s1.json`.

   ```bash
   uv run --project eval lancet-eval seed --corpus multihop_rag_s1_dev --store eval-s1
   ```

4. Check the store. Preflight sends a few canary questions: about $0.01, Paid.

   ```bash
   uv run --project eval lancet-eval preflight --store eval-s1 --corpus multihop_rag_s1_dev
   ```

   Also confirm the chunking took: once #67 has merged, preflight reports it. Otherwise query
   `SELECT chunk_strategy, chunk_size, chunk_overlap, count(*) FROM lancet_eval_s1.documents GROUP BY 1, 2, 3;`
   through `docker exec lancet-postgres psql -U postgres -d lancet -c "..."`. Every row must read
   `structure-merge`, 256, 25. Anything else: stop and tell the user; the store is not the S1 store.

Stop the S1 stack when done.

## Step 2: LlamaIndex live checks (Paid)

Neither reads a held-out question.

1. **`input_type` forwarding** (fairness rule 7). Two embedding calls of a few tokens: under $0.0001. Writes nothing.
   Prints `dropped or ignored` or `forwarded`. Either result is fine for S0 (neither arm sends the field); record
   which one in the run report.

   ```bash
   uv run --project baselines/llamaindex python -c "import httpx,os; k=os.environ['OPENROUTER_API_KEY']; f=lambda **x: httpx.post('https://openrouter.ai/api/v1/embeddings', headers={'Authorization':'Bearer '+k}, json={'model':'voyageai/voyage-4-large','input':['Who won the match?'],'dimensions':2048,**x}, timeout=30).json()['data'][0]['embedding']; a,b=f(),f(input_type='query'); print('forwarded' if a!=b else 'dropped or ignored', max(abs(x-y) for x,y in zip(a,b)))"
   ```

2. **The 346-document export**, over the dev questions of `multihop_rag_s1_dev` (not held-out). It indexes all 346
   documents and retrieves 100 questions. Estimate: about 0.95 M embedded tokens (chunk text plus the embedded
   metadata) about $0.12, plus 100 rerank calls at most $0.03: **about $0.15**. Writes `context_export.jsonl` and
   `pipeline_config.json` under `eval/runs/llamaindex-check/`. It proves the live pipeline builds an index and writes
   a valid export; S0 does not reuse it (its questions differ).

   ```bash
   uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag_s1_dev --arm llamaindex --out eval/runs/llamaindex-check
   ```

   Check `pipeline_config.json`: `framework_version` must be `0.14.25`, `documents` 346, and `chunk_size`,
   `chunk_overlap`, `dense_top_k`, `rerank_model` and `keep` must equal `PREREGISTRATION_S0.external_pipelines`
   (256, 25, 20, `voyageai/rerank-2.5-lite`, 8). A mismatch: stop and tell the user; `run-external` would refuse it.

## Step 3: S0 (Held-out read 1 of 2, Paid)

Ask the user once for the whole of step 3, naming it as held-out read 1 of 2, with the estimate **about $1, ceiling
about $3.5**. Runs on the v1.0 store; start the v1.0 stack, each in its own terminal:

```bash
LANCET_ENV=eval ./engine/target/debug/engine
```

```bash
(cd gateway && LANCET_ENV=eval LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval' go run .)
```

1. Preflight, about $0.01. Reads only canary questions.

   ```bash
   uv run --project eval lancet-eval preflight --corpus multihop_rag_s0_heldout
   ```

2. Drive the Lancet arm over the 351 held-out questions. Estimate 351 × $0.0011, **about $0.40** (ceiling $1.5).
   Writes `$S0_RUN/journal.jsonl`, `raw_events/` and, at the end, `context_export.jsonl`. No `--gate-stage`:
   `run-external` refuses a gate-stage journal.

   ```bash
   uv run --project eval lancet-eval run --corpus multihop_rag_s0_heldout --arms hybrid+rerank+metadata --out $S0_RUN/journal.jsonl --stage-cap 100
   ```

3. Prompt parity (D-247), offline and free: re-packs each Lancet row and compares it with the checkpointed prompt.

   ```bash
   uv run --project eval lancet-eval check-prompt-parity --run $S0_RUN
   ```

4. Export the LlamaIndex arm over the held-out questions. Estimate about 0.95 M embedded tokens, $0.12, plus 351
   rerank calls at most $0.11: **about $0.25**. Writes `$S0_RUN/llamaindex/`.

   ```bash
   uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag_s0_heldout --arm llamaindex --out $S0_RUN/llamaindex
   ```

5. Answer the LlamaIndex arm with the engine's reader. Estimate 351 questions at about 3,300 prompt tokens (eight
   256-token chunks, their metadata and the policy) and 300 completion tokens: **about $0.30** (ceiling $1.5). Appends
   to `$S0_RUN/journal.jsonl` and copies the rows into `$S0_RUN/context_export.jsonl`.

   ```bash
   uv run --project eval lancet-eval run-external --corpus multihop_rag_s0_heldout --arm llamaindex --export $S0_RUN/llamaindex/context_export.jsonl --out $S0_RUN/journal.jsonl --stage-cap 100
   ```

6. Score and compare, offline and free. Writes `report.json`, `report.md`, `lever-comparison.json` and
   `lever-comparison.md` in `$S0_RUN`.

   ```bash
   uv run --project eval lancet-eval score --run $S0_RUN --no-judge
   ```

   ```bash
   uv run --project eval lancet-eval compare-levers --run $S0_RUN
   ```

7. Read the result by EXPERIMENT-S0.md › Decision rule. From `lever-comparison.json`: the `answer_usable` family's
   `llamaindex` row (`evaluable`, `rejected`, `delta`, `ci_lo`, `ci_hi`, `n_pos`, `n_neg`, `raw_p`) and the
   `null_guards` entry for `llamaindex` (`n_pairs`, `min_pairs`, `b`, `c`, `status`). That guard is the `llamaindex`
   direction. The Lancet direction is by hand from the same entry: it passes iff `n_pairs >= min_pairs` and
   `(c - b) / n_pairs <= 0.10`. Write the reading into EXPERIMENT-S0.md › Result with the run directory name, and
   stop the stack.

## Step 4: S1 (Paid, dev only)

Ask the user once for the whole of step 4, with the estimate **about $0.5, ceiling about $1.8**. Needs step 1 done
(with #67 merged). Each store's arms are driven against their own stack into one journal (D-251).

1. Small-store arms, on the v1.0 stack (start it as in step 3). Preflight, about $0.01:

   ```bash
   uv run --project eval lancet-eval preflight --corpus multihop_rag_s1_dev
   ```

2. Drive the two small-store arms over the 100 dev questions. Estimate 200 × $0.0011, **about $0.22**. Writes
   `$S1_RUN/journal.jsonl` and its export.

   ```bash
   uv run --project eval lancet-eval run --corpus multihop_rag_s1_dev --arms small/hybrid+rerank+metadata,small/hybrid+graph+rerank+metadata --out $S1_RUN/journal.jsonl --stage-cap 100
   ```

   Stop the v1.0 stack and start the S1 stack (step 1.2).

3. Preflight the S1 store, about $0.01:

   ```bash
   uv run --project eval lancet-eval preflight --store eval-s1 --corpus multihop_rag_s1_dev
   ```

4. Drive the two merged-store arms into the same journal. Estimate 200 questions at about 3,500 prompt tokens,
   **about $0.25**.

   ```bash
   uv run --project eval lancet-eval run --corpus multihop_rag_s1_dev --arms merged/hybrid+rerank+metadata,merged/hybrid+graph+rerank+metadata --out $S1_RUN/journal.jsonl --stage-cap 100
   ```

   Until #65 merges, this drive's end-of-drive export fails on the small-store records (their checkpoints are in
   `lancet_eval`, not `lancet_eval_s1`) and `run` exits non-zero. The records are journalled; go on to step 4.5.

5. Build the two-store context export. Free. With #65 merged:

   ```bash
   uv run --project eval lancet-eval export-context --run $S1_RUN
   ```

   Before #65 merges, this stopgap reads each store's checkpoints from its own schema and writes the same file:

   ```bash
   uv run --project eval python -c "
   from pathlib import Path
   from lancet_eval.config import V1_STORE, S1_STORE, load_settings
   from lancet_eval.context_export import PostgresCheckpointSource, read_export
   from lancet_eval.run import write_context_export
   class Both:
       def __init__(self):
           self.sources = [PostgresCheckpointSource(load_settings(store=s)) for s in (V1_STORE, S1_STORE)]
       def terminal_success(self, ids):
           return [row for s in self.sources for row in s.terminal_success(ids)]
   run = Path('$S1_RUN')
   print(len(read_export(write_context_export(run / 'journal.jsonl', Both()))), 'rows')
   "
   ```

   It must print 400 rows less any error records. Stop the S1 stack.

6. Score and compare, offline and free:

   ```bash
   uv run --project eval lancet-eval score --run $S1_RUN --no-judge
   ```

   ```bash
   uv run --project eval lancet-eval compare-levers --run $S1_RUN
   ```

7. The merged-store graph reading (D-263), offline and free. Writes `lever-comparison-merged-graph.json` and `.md`:

   ```bash
   uv run --project eval python -c "
   import json
   from pathlib import Path
   from lancet_eval.lever_comparison import build_lever_comparison, render_markdown
   from lancet_eval.thresholds import PREREGISTRATION_S1_MERGED_GRAPH
   run = Path('$S1_RUN')
   payload = build_lever_comparison(run, prereg=PREREGISTRATION_S1_MERGED_GRAPH)
   (run / 'lever-comparison-merged-graph.json').write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding='utf-8')
   (run / 'lever-comparison-merged-graph.md').write_text(render_markdown(payload), encoding='utf-8')
   "
   ```

8. Read the result by EXPERIMENT-S1.md › Decision rule:
   - Chunking: the `merged/hybrid+rerank+metadata` row and guard in `lever-comparison.json`.
   - Graph: if small is kept, the `small/hybrid+graph+rerank+metadata` row and guard in the same file; if merged is
     adopted, the `merged/hybrid+graph+rerank+metadata` row and guard in `lever-comparison-merged-graph.json`.
   - Ignore `default_decisions`; S1 is applied by hand.

   Write the choice into EXPERIMENT-S1.md › Result with the run directory name. S2 replays the chosen
   `<store>/hybrid+rerank+metadata` arm, or its graph-on arm if the graph joined.

## After the run

The run lane commits the two run directories and the filled Result sections, and reports each step's real spend
(`observed spend` lines and the OpenRouter activity page) beside these estimates.
