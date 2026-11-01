# Run guide: S2 reader

For the run-lane worker. Follow the steps in order, one command at a time. The pre-registration is
[EXPERIMENT-S2.md](EXPERIMENT-S2.md); this guide only says how to run it. S2 drives no stack. `replay-init` copies S1
records, `batch submit` and `batch fetch` read the Claude arms through a batch API, and `score` and `compare-levers`
read the run offline.

## Rules for the whole run

- **Main checkout only** (`D:\Repos\lancet`, Git Bash, repository root), on `main`, except while step 4.3 commits
  the constant on its own branch.
- **Two phases (D-73, #109).** Steps 1 to 3 run from the working tree: the constant is pasted in but not committed,
  and the pilot run (`replay-init --pilot`) skips the D-73 check. Step 4 commits the constant once. From step 5 on,
  the run of record's `replay-init` and every `batch submit` run the D-73 check on `PREREGISTRATION_S2` and refuse
  a dirty `eval/src/lancet_eval`, or a constant changed since the commit that added it, before any paid call. So from
  step 5 on, `git status --short -- eval/src/lancet_eval` must print nothing before each of them, and the constant is
  never edited again. The rest of the tree may show changes: `<S2_RUN>` appears as untracked from step 5, since
  `.gitignore` un-ignores it (`!eval/runs/*-multihop_rag_s2_dev/`) so it can be committed (D-73 checks only
  `eval/src/lancet_eval`, as in RUN-S0-S1.md).
- **`PYTHONUTF8=1` on every command** (#84). This machine's console is cp950, and a non-ASCII error string would stop
  a Python snippet with `UnicodeEncodeError`. Every `uv run` command below starts with it; keep it when you copy one.
- **Ask the user first, once per step**, before each step marked *Paid*. Ask in Traditional Chinese. Give the step
  number, its commands, the step's estimate and ceiling from this guide, and what it reads and writes. A yes covers
  that step's commands only. Run nothing on a guess.
- **No mid-run cap** (D-258). Each `batch submit` prints a `Cost estimate (D-258, never refuses)` line and submits
  right after it, in the same command, so read the line as it prints. Compare its `about` figure with this guide's
  row for that arm (Prices behind the estimates). If it is above the row's ceiling, the submit has already gone:
  let it finish, and tell the user both figures before the next submit. Opus's printed estimate counts no reasoning tokens, so it prints well below this guide's Opus row
  (about $4 for step 6, against $10); that is expected.
- **A non-zero exit stops the run.** Tell the user what failed, with the last lines of output. A `batch submit` that
  exits non-zero after printing its manifest path may have reached the endpoint. Never resubmit it: tell the user,
  who checks the endpoint for the batch and fixes or deletes the manifest by hand (`batch.py`'s pending rule).
- **Count after each `replay-init` and each finished arm** (#75). An `error` record is a missing pair. Count the
  journal's records per arm and outcome, the later record of a question and arm winning, as `score` reads them
  (`<RUN>` is `<PILOT_RUN>` or `<S2_RUN>`):

  ```bash
  PYTHONUTF8=1 uv run --project eval python -c "from collections import Counter; from lancet_eval.journal import load_records; from lancet_eval.pairing import deduplicate_by_arm; rs, _ = deduplicate_by_arm(load_records('<RUN>/journal.jsonl')); [print(arm, outcome, n) for (arm, outcome), n in sorted(Counter((r.graph_arm, r.outcome) for r in rs).items())]; [print('error', r.graph_arm, r.question_id, r.error_type, r.error) for r in rs if r.outcome == 'error']"
  ```

  It prints one line per arm and outcome, then one `error` line per error record. Each step gives the count each arm
  must reach (success plus error). If an arm is short of its count, stop and tell the user, with the counts and every
  `error` line. With every count met, go on, and name every `error` line in the run report.
- **Held-out budget** (D-237): S2 reads only the dev pool. `replay-init` refuses a non-dev source run or corpus.
- **Keys.** `OPENROUTER_API_KEY` must be set. A Sonnet arm on the native target also needs `ANTHROPIC_API_KEY`, which
  `.env.example` does not list. It is billed to the organisation the key belongs to, so it must be a key of the
  organisation that holds the Claude credit; ask the user to confirm that before step 3's native re-pilot. Never print
  a key or write it to a file.
- **Run directories.** In step 0, fix three paths and tell the user each one:
  - `<S1_RUN>`: the S1 run of record named in EXPERIMENT-S1.md › Result.
  - `<PILOT_RUN>` = `eval/runs/<YYYY-MM-DD>-s2-pilot`. `.gitignore` ignores it, and it is never committed.
  - `<S2_RUN>` = `eval/runs/<YYYY-MM-DD>-s2-multihop_rag_s2_dev`, dated the day step 5 starts.

  Also fix `<WINNER>`, S1's winning arm label. Write the literal values wherever a command below says `<S1_RUN>`,
  `<PILOT_RUN>`, `<S2_RUN>` or `<WINNER>`, including inside the Python strings. Shell variables do not survive
  between tool calls.

## Prices behind the estimates

Every arm answers each question 5 times (K = 5, D-274), so every figure below is 5 requests per question. The deepseek
arm's first answer is S1's, carried; its other 4 are new requests.

Sync list prices from `PREREGISTRATION_S2` (USD per M tokens, in / out): Haiku 5.5 0.10 / 0.50, Sonnet 5.5 2 / 10,
Opus 5.5 4 / 20. The Claude readers' Batch API bills half, over BYOK on Claude credit. S1's answers used about 3,500
prompt tokens and 300 completion tokens (merged store; about 2,700 to 3,000 on the small store). So one batch request
costs about $0.00025 with Haiku and $0.005 with Sonnet. Opus thinks at effort low; its estimate allows 1,000 reasoning
tokens a request, about $0.02. The ceiling assumes every request uses the engine's caps: 8,192 tokens of evidence
plus about 500 of policy and question, and 2,048 completion tokens, reasoning included. That is at most $0.00095 for
Haiku, $0.019 for Sonnet and $0.038 for Opus.

deepseek's replicates run on OpenRouter credit, pinned to wafer/us under D-271's cap ($0.07 / $0.45 per M tokens).
They go through sync `/chat/completions`, since deepseek-v4-flash-0731 has no batch variant (D-278), so there is no
batch discount: about $0.08 for step 6's 400 requests. `--retry-errors` resubmits only requests that were never
billed.

The answer judges (step 7.1, D-276) run at sync list price, one request per distinct line: at most 90 G questions × 4
arms × 5 answers = 1,800 a judge, fewer where lines repeat. Sonnet judges on Claude credit through BYOK (about 252
prompt tokens a request; its ceiling is `MAX_TOKENS` = 300 output tokens each); gpt-4o-mini ($0.15 / $0.60 per M
tokens) judges on OpenRouter credit.

BYOK requests also cost OpenRouter's BYOK fee, 5% of the list price, taken from OpenRouter credit (PLAN.md › Model
access). Pay-as-you-go includes a free BYOK allowance of $25,000 a month at list price, so inside it the fee is $0;
outside it, about $1.40 (ceiling about $3.40) more on OpenRouter credit.

| Step | Claude credit (BYOK) | Claude ceiling | OpenRouter credit | OpenRouter ceiling |
|---|---|---|---|---|
| 2 Pilot readers, 5 questions × 5 answers × 3 readers | about $0.63 | about $1.44 | – | – |
| 2 Pilot deepseek, 5 questions × 4 answers | – | – | about $0.01 | about $0.06 |
| 3 Native Sonnet re-pilot, only if needed | about $0.13 | about $0.47 | – | – |
| 6 Haiku 5.5 arm, 100 questions × 5 | about $0.13 | about $0.47 | – | – |
| 6 Sonnet 5.5 arm, 100 questions × 5 | about $2.50 | about $9.47 | – | – |
| 6 Opus 5.5 arm, 100 questions × 5 (descriptive, D-267) | about $10.00 | about $18.93 | – | – |
| 6 deepseek replicates 2 to 5, 100 questions × 4, sync (D-278) | – | – | about $0.08 | about $1.10 |
| 7.1 Sonnet judge, at most 1,800 requests | about $2.20 to $2.35 | about $6.31 | – | – |
| 7.1 gpt-4o-mini judge, at most 1,800 requests | – | – | about $0.14 to $0.15 | about $0.39 |
| BYOK fee, inside the free allowance | – | – | about $0 | about $0 |
| **Total, without the native re-pilot** | **about $15.50** | **about $36.60** | **about $0.25** | **about $1.55** |

The judges' lower figures are the audit's; `judge-answers --estimate-only` prints the higher ones, since it allows 80
output tokens a verdict. Claude credit stays far below the $200 of Claude credit (PLAN.md › Budget sketch).

## Step 0: blockers, prerequisites, build

Check each blocker with `gh issue view <N> --repo mileschintw/rust-lancedb-graphrag`. A blocker is cleared when the
issue is closed and its fix is on `main` (`git log origin/main --oneline --grep "#<N>"` or the merged PR's commit).

| Issue | Blocks | Why |
|---|---|---|
| #107 OpenRouter batch payload | steps 2 to 7 | the OpenRouter batch request lacks top-level fields the endpoint needs |
| #109 D-73 before the spend; pilot records | steps 2 to 7 | without it `replay-init` does not check `replay_source_arm` or the S1 arm's completeness |

#108 (schema `maxLength`/`maxItems`) is not a blocker here, even while it is open: the pilot answers it (step 3). If
Anthropic rejects the strict output schema there, stop and ask the owner for a new D-ID.

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
snippet inserts the block into `thresholds.py` before the 06.3.6 freeze block (beside S0 and S1), fills both with `<WINNER>`, and drops the `noqa` the import of
`ReaderPrice` carries until the constant uses it. Commit nothing yet.

```bash
PYTHONUTF8=1 uv run --project eval python -c "
from pathlib import Path
arm = '<WINNER>'
doc = Path('experiments/v1.1/EXPERIMENT-S2.md').read_text(encoding='utf-8')
block = doc.split('### The constant (draft)')[1].split('~~~python')[1].split('~~~')[0]
t = Path('eval/src/lancet_eval/thresholds.py')
s = t.read_text(encoding='utf-8')
assert 'PREREGISTRATION_S2' not in s, 'the constant is already in thresholds.py'
s = s.replace('  # ReaderPrice: for the S2 constant (RUN-S2.md)', '').replace('ReaderPrice,  # noqa: F401', 'ReaderPrice,')
i = s.index('# 06.3.6 D-154 freeze')
t.write_text(s[:i] + block.replace('S1_WINNER_UNSET', arm).lstrip() + chr(10) * 2 + s[i:], encoding='utf-8', newline=chr(10))
c = Path('eval/corpora/multihop_rag_s2_dev.toml')
c.write_text(c.read_text(encoding='utf-8').replace('S1_WINNER_UNSET', arm), encoding='utf-8', newline=chr(10))
"
```

The snippet writes both files with LF line ends; git warns about it on commit. That is harmless: D-73 compares the
constant's AST, not its bytes.

Check:

```bash
PYTHONUTF8=1 uv run --project eval pytest -p no:xdist -q eval/tests/test_s2_preregistration.py eval/tests/test_s2_run_guide.py
```

It must print `22 passed, 1 skipped`. The one skip is `test_the_fill_snippet_inserts_the_draft_and_fills_the_corpus`,
which skips once the snippet has run.

## Step 2: pilot (Paid)

Ask once for steps 2.1 to 2.5: **about $0.65, ceiling about $1.50** (Claude credit about $0.63, ceiling about $1.44;
OpenRouter credit about $0.01, ceiling about $0.06). The pilot checks what the code cannot settle offline:

- `is_byok` and the provider;
- `reasoning_tokens`;
- the model the response names;
- whether Anthropic accepts the strict output schema, for every reader (#108);
- whether Sonnet's `between_tools` passes through OpenRouter (D-260);
- the replicate path (D-274): 5 answers per question, each its own request and record;
- the deepseek path (D-274): whether OpenRouter's batch endpoint takes the engine's own deepseek body with its
  wafer/us pin, and which provider name, `is_byok` and reasoning count its responses report.

It runs in `<PILOT_RUN>`, never in the run of record. Only a run made with `--pilot` takes `--limit` (#109).

1. Carry the winner into the pilot run. This is free.

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval replay-init --pilot --source-run <S1_RUN> --arms <WINNER> --run <PILOT_RUN> --corpus multihop_rag_s2_dev
   ```

   Count (*Count after each*): `<WINNER>` must reach 100, the same as its count in S1.

2. Submit five questions per arm. `--limit 5` takes every answer of the first five questions: 25 requests per reader
   (answers 1 to 5) and 20 for deepseek (answers 2 to 5). Read each cost estimate line as it prints; the submit goes
   out right after it.

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <PILOT_RUN> --arm <WINNER>@haiku-5.5 --limit 5
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <PILOT_RUN> --arm <WINNER>@sonnet-5.5 --limit 5
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <PILOT_RUN> --arm <WINNER>@opus-5.5 --limit 5
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <PILOT_RUN> --arm <WINNER> --limit 5
   ```

   The last one is deepseek's: it refuses before any request if the packed body lacks D-271's pin (one `order` entry,
   `allow_fallbacks: false`, a `max_price`).

3. Fetch. The test batch on 2026-10-25 took 10.9 minutes, and a batch may take up to 24 hours. Rerun this command
   about every 10 minutes until it reports `0 batch(es) still pending`. A fetch is free and re-runnable.

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch fetch --run <PILOT_RUN>
   ```

4. Print each batch record's provenance, the reader arms' and deepseek's answers 2 to 5:

   ```bash
   PYTHONUTF8=1 uv run --project eval python -c "from lancet_eval.journal import load_records; [print(r.graph_arm, r.question_id, r.replicate, r.outcome, r.replay.model, r.replay.provider, r.replay.is_byok, r.replay.reasoning_tokens, r.replay.content_block_types) if r.replay else print(r.graph_arm, r.question_id, r.replicate, r.outcome, r.error_type, r.error) for r in load_records('<PILOT_RUN>/journal.jsonl') if '@' in r.graph_arm or r.replicate > 1]"
   ```

5. Run the replay clauses `score` runs (D-257, D-265). `score` itself refuses the pilot, because the constant is not
   committed (D-73). The snippet starts at column 0 so it can be pasted as it is:

```bash
PYTHONUTF8=1 uv run --project eval python -c "
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

Read the lines from steps 2.4 and 2.5. All 25 requests of each reader (replicates 1 to 5 of five questions) and all
20 of deepseek (replicates 2 to 5) must be `success`, step 2.5 must print `0 replay clause failure(s)`, and:

| Field | Haiku 5.5 | Sonnet 5.5, OpenRouter | Opus 5.5 | deepseek, replicates 2 to 5 |
|---|---|---|---|---|
| model | `anthropic/claude-haiku-5.5` exactly | `anthropic/claude-sonnet-5.5` exactly | `anthropic/claude-opus-5.5` exactly | the `pack` body's model, `deepseek/deepseek-v4-flash-0731` |
| provider | `Anthropic` | `Anthropic` | `Anthropic` | the pinned provider, `Wafer` (matched without case to `wafer` of `wafer/us`) |
| `is_byok` | `True` | `True` | `True` | `False` (OpenRouter credit) |
| `reasoning_tokens` | `0` | `0` | any; thinking on is exempt (D-265) | `0` |

- **An error record's message names the schema**, for any reader: Anthropic rejected the strict output schema (#108).
  Stop and ask the owner for a new D-ID; run nothing more until it exists.
- **Haiku or Opus fails any row**, or a model is a dated variant: stop and tell the user. Each needs an owner
  decision.
- **deepseek fails any row**, or OpenRouter's batch endpoint refused its requests: stop and tell the user, with the
  lines. A provider name other than `Wafer` fails the `provider` clause even when the route was wafer/us; the owner
  decides whether that clause's name match changes (D-274).
- **Sonnet's `reasoning_tokens` is above 0, or is -1:** OpenRouter dropped `between_tools`, and Sonnet goes native
  (D-260). The same holds if a Sonnet request was refused for its `thinking` field. To switch:
  1. In the working tree's `PREREGISTRATION_S2` and in EXPERIMENT-S2.md › The constant, change the `sonnet-5.5` row
     to `slug="claude-sonnet-5-5"`, `target="anthropic"`. In EXPERIMENT-S2.md › Readers, mark the native target as
     chosen, citing the pilot.
  2. Delete `<PILOT_RUN>`.
  3. Re-run step 2 for Sonnet only (2.1, the Sonnet line of 2.2, then 2.3 to 2.5), with `ANTHROPIC_API_KEY` set.
     Ask the user first: about $0.13, ceiling about $0.47.

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

1. In EXPERIMENT-S2.md, change the status line to "pre-registered <date>, before any S2 data" and write `<WINNER>`
   under Arms. Delete the `DRAFT` sentences from the corpus's header comment.
2. Run step 1's check again. It must print `22 passed, 1 skipped`, as in step 1.
3. Commit `thresholds.py`, the corpus and EXPERIMENT-S2.md as one commit with no other change. It is the commit that
   adds the name `PREREGISTRATION_S2` to `thresholds.py`, so D-73 dates the constant by it. The main checkout is on
   `main`, so:
   1. `git switch -c <run lane branch>`, carrying the working-tree changes over.
   2. Commit the three files, and nothing else:

      ```bash
      git add eval/src/lancet_eval/thresholds.py eval/corpora/multihop_rag_s2_dev.toml experiments/v1.1/EXPERIMENT-S2.md
      ```

      ```bash
      git commit -m "Pre-register S2: PREREGISTRATION_S2, S2 corpus and EXPERIMENT-S2 (D-73)"
      ```

   3. Ask the user, then `git push -u origin HEAD`. The coordinator opens the PR and merges it to `main`.
   4. Once it is merged: `git switch main` and `git pull --ff-only`. Then
      `git log --oneline -1 -- eval/src/lancet_eval/thresholds.py` must print that commit's subject, "Pre-register
      S2: ..." (its hash may differ after a squash merge), and
      `git status --short -- eval/src/lancet_eval` must print nothing.

   From here on the constant is never edited: any change makes D-73 refuse the run of record.

## Step 5: carry the winner into the run of record

Free. `git status --short -- eval/src/lancet_eval` must print nothing.

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval replay-init --source-run <S1_RUN> --arms <WINNER> --run <S2_RUN> --corpus multihop_rag_s2_dev
```

It refuses an arm other than `replay_source_arm`, an S1 arm that is partial or short of a question, and a failed D-73
check (#109). Count (*Count after each*): `<WINNER>` must reach 100, the same as its count in S1, error records
included. These are its replicate-1 answers.

## Step 6: batch arms (Paid)

Ask once for steps 6.1 to 6.3: **about $12.75, ceiling about $30.00** (Claude credit about $12.65, ceiling about
$28.90; OpenRouter credit, deepseek, about $0.08, ceiling about $1.10). The four batch arms run in parallel (D-267): a
pending batch blocks only another submit of its own arm.

1. Submit the four arms, one after the other, without waiting. Read each cost estimate line as it prints; Opus's
   prints low (*No mid-run cap*). Each reader sends 500 requests (100 questions × 5 answers); deepseek sends 400
   (answers 2 to 5).

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <S2_RUN> --arm <WINNER>@haiku-5.5
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <S2_RUN> --arm <WINNER>@sonnet-5.5
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <S2_RUN> --arm <WINNER>@opus-5.5
   ```

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <S2_RUN> --arm <WINNER>
   ```

2. Fetch every arm, about every 10 minutes, until it reports `0 batch(es) still pending`:

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch fetch --run <S2_RUN>
   ```

3. Count (*Count after each*). Each of the four arms must reach 500, `<WINNER>` included (its 100 carried answers
   and 400 new ones); `score` checks only the first answer of each, so this count is the completeness check for the
   other four. For each arm whose `error` lines show an expired or errored request, resubmit only those (`<ARM>` is
   `<WINNER>@haiku-5.5`, `<WINNER>@sonnet-5.5`, `<WINNER>@opus-5.5` or `<WINNER>`), then repeat 6.2 and the count:

   ```bash
   PYTHONUTF8=1 uv run --project eval lancet-eval batch submit --run <S2_RUN> --arm <ARM> --retry-errors
   ```

   Retry at most twice. Error records that are left, and render errors (billed, never retried), are missing answers:
   a question with fewer than 5 ok answers under an arm leaves that arm's comparisons (D-274). Name each one in the
   run report.


## Step 7: score and compare

Offline and free.

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval score --run <S2_RUN> --no-judge
```

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval compare-levers --run <S2_RUN>
```

`score` fails closed on any replay clause. A failure names the record and the clause: stop and tell the user. Then
read the result by EXPERIMENT-S2.md › Decision rule:

- the family rows and null guards in `lever-comparison.json`. Each row's `raw_p` is D-274's sign-flip permutation
  test on the per-question means over 5 answers; `paired_t_p` beside it is a cross-check only. The null guards count
  answer pairs (5 per null question);
- `reader_comparison` for each reader's `answer_usable` (over all 5 answers; `n_answers`), paired differences and cost
  per answered question. Opus 5.5 is a descriptive row: report it, and leave it out of the choice (D-267);
- D-275's reader choice: start from the eligible reader with the lowest cost per answered question, take every
  pair of eligible readers from `reader_comparison` › `pairs`, run Holm over all of them by hand, and step up to a
  dearer reader only when Holm rejects its pair with the current pick in its favour (EXPERIMENT-S2.md › Decision
  rule 2). Write the Holm arithmetic into the Result. A null guard's pass or fail is read; its printed bound is not
  (D-274).

Ignore `default_decisions`. S2 is applied by hand.

### Step 7.1: answer judges (Paid, D-276)

The secondary: gpt-4o-mini and Sonnet 5.5 judge whether each G record's final line is equivalent to the gold. Each
sees only the question, the gold answer and the line. It decides nothing. Print the estimate first, free:

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval judge-answers --run <S2_RUN> --estimate-only
```

Ask the user, with that estimate. This guide's figure: **about $2.35 to $2.50, ceiling about $6.70** (Sonnet on
Claude credit about $2.20 to $2.35, ceiling about $6.31; gpt-4o-mini on OpenRouter credit about $0.14 to $0.15,
ceiling about $0.39).
Every replicate is judged, up to 90 G questions × 4 arms × 5 answers a judge; a line that repeats is asked once.

If step 3 moved the Sonnet reader to the native target because OpenRouter dropped `between_tools`, the Sonnet judge
(still on OpenRouter) thinks too: its spend runs above the estimate, up to the ceiling, which caps output tokens
reasoning included. Say so when you ask.

Then run it with `OPENROUTER_API_KEY` set:

```bash
PYTHONUTF8=1 uv run --project eval lancet-eval judge-answers --run <S2_RUN>
```

It writes `<S2_RUN>/answer-judge.json` and caches each verdict in `<S2_RUN>/answer-judge-cache.json`, so a rerun asks
only the requests that failed. If it prints `judge request(s) failed`, run it again, at most twice, and name what is
left in the run report. Report each judge's per-arm rate beside the primary in EXPERIMENT-S2.md › Result, and give the
owner the `disagreements` list to review.

## Step 8: record

Write the choice into EXPERIMENT-S2.md › Result:

- the run directory name;
- the winning reader, and whether D-245's switch rule holds;
- each arm's batch IDs (from `<S2_RUN>/batches/`);
- the actual batch spend per arm (the OpenRouter activity page and, for a native arm, the Anthropic console), next to
  this guide's estimates.

Commit `<S2_RUN>` and the filled Result on the run lane's own branch, never on `main`. The coordinator opens and merges
the PR.
