# Run guide: S2 reader

For the run-lane worker. Follow the steps in order, one command at a time. The pre-registration is
[EXPERIMENT-S2.md](EXPERIMENT-S2.md); this guide only says how to run it. S2 drives no stack. `replay-init` copies S1
records, `batch submit` and `batch fetch` read the Claude arms through a batch API, and `score` and `compare-levers`
read the run offline.

## Rules for the whole run

- **Main checkout only** (`D:\Repos\lancet`, Git Bash, repository root), on `main`.
- **Two phases (D-73, #109).** Steps 1 to 3 run from the working tree: the constant is pasted in but not committed,
  and the pilot run (`replay-init --pilot`) skips the D-73 check. Step 4 commits the constant once. From step 5 on,
  the run of record's `replay-init` and every `batch submit` run the D-73 check on `PREREGISTRATION_S2` and refuse
  a dirty tree, or a constant changed since the commit that added it, before any paid call. So from step 5 on,
  `git status --short` must print nothing before each of them, and the constant is never edited again.
- **Ask the user first, once per step**, before each step marked *Paid*. Ask in Traditional Chinese. Give the step
  number, its commands, the step's estimate and ceiling from this guide, and what it reads and writes. A yes covers
  that step's commands only. Run nothing on a guess.
- **No mid-run cap** (D-258). Each `batch submit` prints a `Cost estimate (D-258, never refuses)` line before it
  submits. Compare it with this guide's figure. If it is above the step's ceiling, the submit has already gone: let
  it finish, and tell the user both figures before the next submit.
- **A non-zero exit stops the run.** Tell the user what failed, with the last lines of output. A `batch submit` that
  exits non-zero after printing its manifest path may have reached the endpoint. Never resubmit it: tell the user,
  who checks the endpoint for the batch and fixes or deletes the manifest by hand (`batch.py`'s pending rule).
- **Count after each `replay-init` and each finished arm** (#75). An `error` record is a missing pair. Count the
  journal's records per arm and outcome, the later record of a question and arm winning, as `score` reads them
  (`<RUN>` is `<PILOT_RUN>` or `<S2_RUN>`):

  ```bash
  uv run --project eval python -c "from collections import Counter; from lancet_eval.journal import load_records; from lancet_eval.pairing import deduplicate_by_arm; rs, _ = deduplicate_by_arm(load_records('<RUN>/journal.jsonl')); [print(arm, outcome, n) for (arm, outcome), n in sorted(Counter((r.graph_arm, r.outcome) for r in rs).items())]; [print('error', r.graph_arm, r.question_id, r.error_type, r.error) for r in rs if r.outcome == 'error']"
  ```

  It prints one line per arm and outcome, then one `error` line per error record. Each step gives the count each arm
  must reach (success plus error). If an arm is short of its count, stop and tell the user, with the counts and every
  `error` line. With every count met, go on, and name every `error` line in the run report.
- **Held-out budget** (D-237): S2 reads only the dev pool. `replay-init` refuses a non-dev source run or corpus.
- **Keys.** `OPENROUTER_API_KEY` must be set. A Sonnet arm on the native target also needs `ANTHROPIC_API_KEY`, which
  `.env.example` does not list. Never print a key or write it to a file.
- **Run directories.** In step 0, fix three paths and tell the user each one:
  - `<S1_RUN>`: the S1 run of record named in EXPERIMENT-S1.md › Result.
  - `<PILOT_RUN>` = `eval/runs/<YYYY-MM-DD>-s2-pilot`. `.gitignore` ignores it, and it is never committed.
  - `<S2_RUN>` = `eval/runs/<YYYY-MM-DD>-s2-multihop_rag_s2_dev`, dated the day step 5 starts.

  Also fix `<WINNER>`, S1's winning arm label. Write the literal values wherever a command below says `<S1_RUN>`,
  `<PILOT_RUN>`, `<S2_RUN>` or `<WINNER>`, including inside the Python strings. Shell variables do not survive
  between tool calls.

## Prices behind the estimates

Sync list prices from `PREREGISTRATION_S2` (USD per M tokens, in / out): Haiku 5.5 0.10 / 0.50, Sonnet 5.5 2 / 10,
Opus 5.5 4 / 20. The Batch API bills half. S1's answers used about 3,500 prompt tokens and 300 completion tokens
(merged store; about 2,700 to 3,000 on the small store). So one batch request costs about $0.00025 with Haiku and
$0.005 with Sonnet. The ceiling assumes every request uses the engine's caps: 8,192 tokens of evidence plus about
500 of policy and question, and 2,048 completion tokens. That is at most $0.00095 for Haiku and $0.019 for Sonnet.
Opus thinks at effort low; its estimate allows 1,000 reasoning tokens a request. `--retry-errors` resubmits only
requests that were never billed.

| Step | Estimate | Ceiling |
|---|---|---|
| 2 Pilot, 5 questions × 2 readers | about $0.03 | about $0.10 |
| 6 Haiku 5.5 arm, 100 questions | about $0.03 | about $0.10 |
| 6 Sonnet 5.5 arm, 100 questions | about $0.50 | about $1.90 |
| 8 Opus 5.5 arm, only if it joins | about $2.00 | about $3.80 |
| **Total without Opus** | **about $0.56** | **about $2.10** |

A native Sonnet re-pilot (step 3) adds about $0.03.

## Step 0: blockers, prerequisites, build

Check each blocker with `gh issue view <N> --repo mileschintw/rust-lancedb-graphrag`. A blocker is cleared when the
issue is closed and its fix is on `main` (`git log origin/main --oneline --grep "#<N>"` or the merged PR's commit).

| Issue | Blocks | Why |
|---|---|---|
| #107 OpenRouter batch payload | steps 2 to 8 | the OpenRouter batch request lacks top-level fields the endpoint needs |
| #108 schema `maxLength`/`maxItems` | steps 2 to 8 | Anthropic may reject the strict output schema; if so the owner needs a new D-ID |
| #109 D-73 before the spend; pilot records | steps 2 to 8 | without it `replay-init` does not check `replay_source_arm` or the S1 arm's completeness |

Then check the prerequisites. Stop and tell the user if any fails.

1. EXPERIMENT-S1.md › Result names the winner and the S1 run directory. That arm is `<WINNER>`, and the directory is
   `<S1_RUN>`.
2. `<S1_RUN>/context_export.jsonl` exists, and its row count equals the number of the S1 journal's `success`
   records (RUN-S0-S1.md step 4.5).
3. The BYOK key on OpenRouter is set to "Never use shared capacity" (PLAN.md › Model access). Ask the user to confirm
   it. You cannot read that setting.

Then `git pull --ff-only` on `main`, check that `git status` is clean, fix the run directories, and build the one
release bin S2 runs, `generate_from_context` (`pack` before a submit, `render` in a fetch). A cold release build
takes about 70 to 74 minutes on this machine (`docs/testing.md`, #56). Start it with `run_in_background`:

```bash
cargo build --manifest-path engine/Cargo.toml --locked --release --bin generate_from_context
```

Start no *Paid* step until this build has exited 0.

## Step 1: paste the constant into the working tree

`PREREGISTRATION_S2` is not in `thresholds.py` on `main`. D-73 dates a constant by the first commit that adds its name
to that file, so the name enters it once, in step 4. Its draft is the code block in EXPERIMENT-S2.md › The constant,
and `eval/corpora/multihop_rag_s2_dev.toml` holds the same placeholder `S1_WINNER_UNSET` where the winner goes. This
snippet appends the block to `thresholds.py` and fills both with `<WINNER>`. Commit nothing yet.

```bash
uv run --project eval python -c "
from pathlib import Path
arm = '<WINNER>'
doc = Path('experiments/v1.1/EXPERIMENT-S2.md').read_text(encoding='utf-8')
block = doc.split('### The constant (draft)')[1].split('~~~python')[1].split('~~~')[0]
t = Path('eval/src/lancet_eval/thresholds.py')
s = t.read_text(encoding='utf-8')
assert 'PREREGISTRATION_S2' not in s, 'the constant is already in thresholds.py'
t.write_text(s + chr(10) * 2 + block.replace('S1_WINNER_UNSET', arm).lstrip(), encoding='utf-8', newline=chr(10))
c = Path('eval/corpora/multihop_rag_s2_dev.toml')
c.write_text(c.read_text(encoding='utf-8').replace('S1_WINNER_UNSET', arm), encoding='utf-8', newline=chr(10))
"
```

Check:

```bash
uv run --project eval pytest -p no:xdist -q eval/tests/test_s2_preregistration.py eval/tests/test_s2_run_guide.py
```

Every test passes except `test_the_committed_constant_holds_no_todo`, which fails while a TODO is left. The TODOs are
settled in step 4.

## Step 2: pilot (Paid)

Ask once for steps 2.1 to 2.5: **about $0.03, ceiling about $0.10**. The pilot checks what the code cannot settle
offline:

- `is_byok` and the provider;
- `reasoning_tokens`;
- the model the response names;
- whether Anthropic accepts the strict output schema;
- whether Sonnet's `between_tools` passes through OpenRouter (D-260).

It runs in `<PILOT_RUN>`, never in the run of record. Only a run made with `--pilot` takes `--limit` (#109).

1. Carry the winner into the pilot run. This is free.

   ```bash
   uv run --project eval lancet-eval replay-init --pilot --source-run <S1_RUN> --arms <WINNER> --run <PILOT_RUN> --corpus multihop_rag_s2_dev
   ```

   Count (*Count after each*): `<WINNER>` must reach 100, the same as its count in S1.

2. Submit five questions per reader. Read each cost estimate line first.

   ```bash
   uv run --project eval lancet-eval batch submit --run <PILOT_RUN> --arm <WINNER>@haiku-5.5 --limit 5
   ```

   ```bash
   uv run --project eval lancet-eval batch submit --run <PILOT_RUN> --arm <WINNER>@sonnet-5.5 --limit 5
   ```

3. Fetch. The test batch on 2026-10-25 took 10.9 minutes, and a batch may take up to 24 hours. Rerun this command
   about every 10 minutes until it reports `0 batch(es) still pending`. A fetch is free and re-runnable.

   ```bash
   uv run --project eval lancet-eval batch fetch --run <PILOT_RUN>
   ```

4. Print each reader record's provenance:

   ```bash
   uv run --project eval python -c "from lancet_eval.journal import load_records; [print(r.graph_arm, r.question_id, r.outcome, r.replay.model, r.replay.provider, r.replay.is_byok, r.replay.reasoning_tokens, r.replay.content_block_types) if r.replay else print(r.graph_arm, r.question_id, r.outcome, r.error_type, r.error) for r in load_records('<PILOT_RUN>/journal.jsonl') if '@' in r.graph_arm]"
   ```

5. Run the replay clauses `score` runs (D-257, D-265). `score` itself refuses the pilot, because the constant is not
   committed (D-73):

   ```bash
   uv run --project eval python -c "
   from lancet_eval import preregistration
   from lancet_eval.context_export import read_export
   from lancet_eval.journal import load_records, read_journal_header
   from lancet_eval.pairing import deduplicate_by_arm
   from lancet_eval.provenance import replay_run_failures
   from lancet_eval.replay import source_row_hashes
   run = '<PILOT_RUN>'
   records, _ = deduplicate_by_arm(load_records(run + '/journal.jsonl'))
   rows = {(r.question_id, r.arm): r for r in read_export(run + '/context_export.jsonl')}
   hashes = source_row_hashes(read_journal_header(run + '/journal.jsonl'))
   readers = preregistration.readers_of(preregistration.resolve('PREREGISTRATION_S2'))
   failures = replay_run_failures(records, export_rows=rows, source_row_sha256=hashes, readers=readers)
   [print(f.code, f.label, f.detail) for f in failures]
   print(len(failures), 'replay clause failure(s)')
   "
   ```

## Step 3: read the pilot and settle Sonnet's target

Read the lines from steps 2.4 and 2.5. All five requests of each reader must be `success`, step 2.5 must print
`0 replay clause failure(s)`, and:

| Field | Haiku 5.5 | Sonnet 5.5, OpenRouter |
|---|---|---|
| model | `anthropic/claude-haiku-5.5` exactly | `anthropic/claude-sonnet-5.5` exactly |
| provider | `Anthropic` | `Anthropic` |
| `is_byok` | `True` | `True` |
| `reasoning_tokens` | `0` | `0` |

- **Haiku fails any row**, an error record's message names the schema (#108), or a model is a dated variant: stop and
  tell the user. Each needs an owner decision.
- **Sonnet's `reasoning_tokens` is above 0, or is -1:** OpenRouter dropped `between_tools`, and Sonnet goes native
  (D-260). The same holds if a Sonnet request was refused for its `thinking` field. To switch:
  1. In the working tree's `PREREGISTRATION_S2` and in EXPERIMENT-S2.md › The constant, change the `sonnet-5.5` row
     to `slug="claude-sonnet-5-5"`, `target="anthropic"`. In EXPERIMENT-S2.md › Readers, mark the native target as
     chosen, citing the pilot.
  2. Delete `<PILOT_RUN>`.
  3. Re-run step 2 for Sonnet only (2.1, the Sonnet line of 2.2, then 2.3 to 2.5), with `ANTHROPIC_API_KEY` set.
     Ask the user first: about $0.03.

  On the native target, the Sonnet lines must show:
  - the model `claude-sonnet-5-5`;
  - the provider `api.anthropic.com`;
  - `is_byok` `None`;
  - `reasoning_tokens` 0;
  - content block types without `thinking` or `redacted_thinking` (D-265).
- **Every row holds:** Sonnet stays on OpenRouter.

Write the pilot's lines and the decision into the run report. Then delete `<PILOT_RUN>`. Its records cannot enter the
run of record.

## Step 4: freeze the pre-registration (D-73)

1. The five TODOs in EXPERIMENT-S2.md › Open questions must be settled by the owner. Write each answer into
   EXPERIMENT-S2.md and into the working tree's constant, and delete every TODO from both. An open TODO stops the run
   here: tell the user which.
2. In EXPERIMENT-S2.md, change the status line to "pre-registered <date>, before any S2 data" and write `<WINNER>`
   under Arms. Delete the `DRAFT` sentences from the corpus's header comment.
3. Run step 1's check again. Every test must pass.
4. Commit `thresholds.py`, the corpus and EXPERIMENT-S2.md as one commit, on the run lane's own branch, with no other
   change. It is the commit that adds the name `PREREGISTRATION_S2` to `thresholds.py`, so D-73 dates the constant by
   it. The coordinator merges it to `main` through a PR. Then pull `main` in the main checkout. From here on the
   constant is never edited: any change makes D-73 refuse the run of record.

## Step 5: carry the winner into the run of record

Free. `git status --short` must print nothing.

```bash
uv run --project eval lancet-eval replay-init --source-run <S1_RUN> --arms <WINNER> --run <S2_RUN> --corpus multihop_rag_s2_dev
```

It refuses an arm other than `replay_source_arm`, an S1 arm that is partial or short of a question, and a failed D-73
check (#109). Count (*Count after each*): `<WINNER>` must reach 100, the same as its count in S1, error records
included.

## Step 6: reader arms (Paid)

Ask once for steps 6.1 to 6.3: **about $0.53, ceiling about $2.00**. Do one arm at a time: Haiku 5.5, then Sonnet 5.5.

1. Submit the whole arm. Read the cost estimate line first.

   ```bash
   uv run --project eval lancet-eval batch submit --run <S2_RUN> --arm <WINNER>@haiku-5.5
   ```

2. Fetch, about every 10 minutes, until it reports `0 batch(es) still pending`:

   ```bash
   uv run --project eval lancet-eval batch fetch --run <S2_RUN>
   ```

3. Count (*Count after each*). The arm must reach 100. If any `error` line shows an expired or errored request,
   resubmit only those, then repeat 6.2 and the count:

   ```bash
   uv run --project eval lancet-eval batch submit --run <S2_RUN> --arm <WINNER>@haiku-5.5 --retry-errors
   ```

   Retry at most twice. Error records that are left, and render errors (billed, never retried), are missing pairs.
   Name each one in the run report.

Then the same three steps for `<WINNER>@sonnet-5.5`.

## Step 7: score and compare

Offline and free.

```bash
uv run --project eval lancet-eval score --run <S2_RUN> --no-judge
```

```bash
uv run --project eval lancet-eval compare-levers --run <S2_RUN>
```

`score` fails closed on any replay clause. A failure names the record and the clause: stop and tell the user. Then
read the result by EXPERIMENT-S2.md › Decision rule:

- the family rows and null guards in `lever-comparison.json`;
- `reader_comparison` for each reader's `answer_usable`, paired differences and cost per answered question.

Ignore `default_decisions`. S2 is applied by hand.

## Step 8: Opus 5.5 (Paid, only if it joins)

Opus joins only if the Sonnet 5.5 delta minus the Haiku 5.5 delta is at least +5 points (D-252). If it does not, skip
this step. If it does, the way its arm is pre-registered is EXPERIMENT-S2.md › Open questions 1. Follow the answer
recorded there, and commit it before any Opus submit. Then ask the user (**about $2, ceiling about $3.80**), and run
step 6 for `<WINNER>@opus-5.5`, then step 7 again.

## Step 9: record

Write the choice into EXPERIMENT-S2.md › Result:

- the run directory name;
- the winning reader, and whether D-245's switch rule holds;
- each arm's batch IDs (from `<S2_RUN>/batches/`);
- the actual batch spend per arm (the OpenRouter activity page and, for a native arm, the Anthropic console), next to
  this guide's estimates.

Commit `<S2_RUN>` and the filled Result on the run lane's own branch, never on `main`. The coordinator opens and merges
the PR.
