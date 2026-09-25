# Plan 06.3.4.1-07 Executor Handoff (2026-09-25, continuation after Task 3 checkpoint)

Written mid-flight while `primary-r2` runs in the background (potentially hours). This
supersedes the prior handoff (which covered Tasks 1-2 up to the first, invalid primary run).
Keep reading the plan's own Task 2/3/4/5 text alongside this file — this file is state, not a
restatement of the plan.

## Where things stand

HEAD at this handoff: `ef553b26`. Tree clean except the running replay's untracked scratch
files under `data/replay/` and `data/lancedb-replay/` (gitignored, expected, reuse — do not
delete while `primary-r2` is in flight or after, until Task 7's cleanup).

**Task 3 checkpoint: RESOLVED** by the user as `rerun-primary` (full text in
`06.3.4.1-HANDOVER.md`). This handoff covers executing that resolution.

**What's committed in this continuation session** (after `13150385`, the pause commit):
- `12e965d8` test(06.3.4.1-07): RED for stub vector-map builder
- `0d339ae3` feat(06.3.4.1-07): GREEN -- stub vector-map builder + CLI subcommands
- `ef553b26` docs(06.3.4.1-07): resume execution (STATE.md back to `executing`)

**New tooling added** (`eval/src/lancet_eval/oi02.py`, tests in `eval/tests/test_oi02.py`,
27/27 passing, full oi02/oi02_replay/provider_stub suite 73/73):
- `extract_chunk_ids_for_replay` / `oi02.py extract-chunk-ids`: builds
  `question_id -> production top-ranked chunk_id` (rank==1 from `snapshot.retrieved_chunks`,
  preferring the `graph-off` arm) for every question in a replay journal, plus the deduped
  `chunk_ids.json` `retrieval_soak --export-embeddings` needs.
- `load_chunk_embeddings`, `load_question_texts`: small loaders.
- `build_stub_vectors` / `oi02.py build-stub-vectors`: joins everything into
  `provider_stub.load_vector_map`'s `{"text": ..., "embedding": [...]}` row shape, keyed by
  the exact question text (confirmed via source read: `ctx.variants[0]` == `ctx.original_query`
  unmodified end to end, since `reformulation_used` was `None`/false for all 350 records in the
  first primary -- no reformulation ever fires, so no risk of a derived/reformulated embed
  input missing the map).

## The stub-vectors.jsonl build, exactly reproducible

```bash
uv run --project eval python -m lancet_eval.oi02 extract-chunk-ids \
  --replay-journal .planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/replay/pre-fix/primary/journal.jsonl \
  --prod-journal eval/runs/2026-09-09-multihop_rag/journal.jsonl \
  --out-chunk-ids data/replay/chunk_ids.json \
  --out-map data/replay/question-chunk-map.json
# -> {"replay_questions": 175, "matched_to_prod_top_chunk": 174, "unique_chunk_ids": 139}

engine/target/debug/retrieval_soak.exe --export-embeddings data/replay/chunk_ids.json \
  --lancedb-path data/lancedb-replay > data/replay/chunk-embeddings.jsonl
# -> 137/139 chunk ids found in the reconciled store copy (2 absent, D-88 store drift)

uv run --project eval python -m lancet_eval.oi02 build-stub-vectors \
  --replay-journal .planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/replay/pre-fix/primary/journal.jsonl \
  --map data/replay/question-chunk-map.json \
  --embeddings data/replay/chunk-embeddings.jsonl \
  --questions eval/corpora/multihop_rag/questions.sample.jsonl \
  --out data/replay/stub-vectors.jsonl
# -> {"total": 175, "no_prod_chunk": 1, "no_embedding": 2, "no_question_text": 0, "matched": 172}
```

**172/175 questions (98.3%) got the real production top-chunk vector; 3 fall back to the
stub's deterministic hash vector** (1 had no production top chunk at all -- likely an
error/timeout record; 2 had a production top chunk absent from the reconciled store copy, a
D-88 store-drift artifact, not a bug). This is the fallback count to disclose in the profile
write-up. `data/replay/` (chunk_ids.json, question-chunk-map.json, chunk-embeddings.jsonl,
stub-vectors.jsonl) is gitignored and scratch -- Task 7 deletes it; it is NOT reproduced from
anything committed except via the three commands above plus the committed primary journal and
the production journal, so if you need to rebuild it, redo those three commands verbatim
(same order, same paths).

## Smoke validation BEFORE launching primary-r2 (do not skip this step if you ever rebuild the vectors)

Ran `-Label smoke -Questions 9` (18 records, reusing the store copy and scratch DB). **Found
and fixed a real gotcha #11 here, add to the "don't re-discover" list:**

**`JournalWriter` (`eval/src/lancet_eval/journal.py:258,265`) always opens in append mode
(`"a"`).** `oi02-replay.ps1` never truncates an arm's `journal.jsonl` before a run -- it
assumes a fresh `$ArmDir`. Re-running the SAME `-Label` a second time (e.g. re-smoking after
fixing the vectors, weeks after the first smoke that used the OLD hash-fallback vectors and
was already git-committed) silently APPENDS the new run's records after the old committed
ones. The result reads as internal contradiction (same question_id appearing twice with
different retrieved chunks and different notice codes) unless you notice the record count
doesn't match `-Questions * 2`. **Before reusing a `-Label` that has ever run before, either
delete that arm's `journal.jsonl` (and the other per-run files) first, or take only the last
`-Questions * 2` records as the real run and disregard the rest.** `primary-r2` is a brand-new
label, so it is not exposed to this -- only matters if you ever re-run `smoke` again.

After identifying and discounting the stale prefix, the smoke's own 18 records (9 questions x
2 arms) validated cleanly, and were then **reverted** (`git checkout --` on the tracked smoke
files, `rm -f` on the new untracked `raw_events/*` files) to leave the smoke directory at its
original Task 2 committed state -- this diagnostic re-run was not itself a plan-required
artifact, so nothing new needed to persist once it had proven the vectors work:

- `stub-stats.json`: `embedding_fallback_count: 0` out of 18 embedding calls (every one of the
  9 smoke questions was among the 172 matched).
- **18/18 records' `snapshot.retrieved_chunks[rank=1].chunk_id` exactly matched production's
  top-ranked chunk** for that same `question_id` -- the strongest possible proof the vector map
  is doing its job (verified by direct comparison against `question-chunk-map.json`).
- **6/9 graph-on records got real graph traversal** (empty `notices`, `ExtractGraphContext`
  duration ~1200-2600ms, vs ~347ms for the matched graph-off/ablated arm) -- 3/9 still got
  `GRAPH_UNAVAILABLE` (graph timeout/no-seed variance, not a vector-map defect; one of the two
  questions independently confirmed graph-positive in production also got `GRAPH_UNAVAILABLE`
  here, likely cold-engine/timing variance on a 9-question smoke, not disqualifying). This is
  the qualitative confirmation the checkpoint resolution asked for: **NOT every record is
  GRAPH_ABLATION/GRAPH_UNAVAILABLE**, a categorical change from the first primary's 0/350.

This satisfies checkpoint-resolution step 1's smoke gate. Cleared to launch `primary-r2`.

## primary-r2: launched, in flight

Launched via the same launcher pattern as the first primary, changing only `-Label`:

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/oi02-replay-launch.ps1 `
  -LogDir "<temp dir>" -RunName primary-r2 `
  -ReplayArgsJoined "-Label|primary-r2|-Phase|pre-fix|-Questions|175|-Retries|2|-Workers|1|-StubEmbedDelayMs|343|-StubChatDelayMs|6970"
```

**Every other parameter left at default, matching `primary/header.json`'s recorded values
exactly** (`-Observability on` default, `-StoreSource reconciled` default, `-EngineLaunch`
default resolves to the same `cargo run --manifest-path engine/Cargo.toml --locked --bin
engine` production launch, `-StageCap 1.00` default, `-WarmupQuestions 0` default). The ONLY
intended difference between `primary` and `primary-r2` is `stub_vector_source`
(`hash-fallback-only` -> `data/replay/stub-vectors.jsonl`). **Do not `check-arm
--same-config-as primary` for this pair** -- it compares `stub_delays`/vector source among
other fields and `stub_vector_source` differs by design; diff the two `header.json`s by hand
instead and confirm only that field (plus PIDs/timestamps/commit, which `--same-config-as`
already ignores) changed.

Launched at commit `ef553b26`. `data/lancedb-replay/` and the `lancet_replay` scratch DB were
both reused (already existed from the first primary), so no store-copy/DB-restore wait this
time -- startup should be faster than the first primary's run.

**Do not build anything, run any other agent, or start any other soak while this runs** (CPU
contention confounds latency -- this is the whole point of the replay).

Poll the done marker (`<LogDir>\primary-r2.done`), do NOT read `primary-r2.out.log` while the
process is still running (torn reads, gotcha #2 from the original handoff). Once the marker
exists:

```bash
uv run --project eval python -m lancet_eval.oi02 check-arm \
  .planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/replay/pre-fix/primary-r2 \
  --min-records 350
```

Then read `replay/pre-fix/primary-r2/summary.json` for M1/M2.

## Next steps after primary-r2 completes

1. `check-arm --min-records 350` on `primary-r2` (above).
2. Read M1 (ratio, both references, met/not met) and M2 (grows/not grows/ambiguous) from
   `summary.json`, alongside the committed `flatness_verdict`.
3. Write up `### Full-stack replay (07)` in the profile -- **primary-r2 REPLACES primary as the
   reference everywhere per the Task 3 resolution text.** Disclose: the first primary's
   hash-fallback-vector invalidity, the fix (this handoff's build steps), the 172/175 match
   rate and 3 fallback questions, the smoke validation (18/18 chunk match, 6/9 real graph
   traversal), then primary-r2's own fidelity table, M1/M2, process/session-cache trends, and
   the live-store-untouched proof. Commit as a `feat(06.3.4.1-07): ...` continuation of Task 2.
4. **Route per the plan's Task 3/4 table, without asking the user again** (already
   pre-authorized in `06.3.4.1-HANDOVER.md`):
   - **M2 grows:** Route A, bisect on HEAD (plan Task 4, default arm order: `obs-off`, stderr
     sink, engine console-only telemetry, `release`, `retries0`, `unpaced`, gateway telemetry
     off, `prereconcile-store`).
   - **M2 not grows/ambiguous:** Route B, starting with the drive-era whole stack (worktree at
     `drive_era_commit` = `33e774bd71034b54ec14f8079e3cfac83aee56f1` from `forensics.json`, at
     `../lancet-oi02-drive-era`, against a pre-reconcile store copy -- copy source
     `data/lancedb-eval.pre-06.3.4.1-reconcile/`, restored scratch DB from
     `data/backups/lancet_eval.pre-06.3.4.1-reconcile.sql`, never the live store/dump in
     place). Weigh the handover's hint that production grew on every node including pure-CPU
     AssemblePrompt (2.2x) when ordering arms -- suggests a process/machine-wide cause.
5. Build the drive-era worktree (if Route B) BEFORE launching the next long arm, never during
   one (keeps the machine quiet while an arm runs).
6. Continue Task 4's arm loop (cap 10 arms, each ~30-60+ min, background + poll every time).
7. Write `### Bisection (07)` plus either `### Named mechanism (07)` or
   `### What remains untested (07)` (and `### Starting gap (07)` if M1 was not met).
8. **Stop at Task 5** exactly as originally specified: return the structured
   `checkpoint:decision` (`gate="blocking"`) per the plan's Task 5 `<context>` block. Do NOT
   choose an option. The paid-replay pre-authorization (cap $0.25, `--stage-cap 0.25`) is
   already recorded in `06.3.4.1-HANDOVER.md` -- restate it at the checkpoint per the
   objective's instruction, but prefer presenting the option rather than running it yourself
   unless Route B's routing makes it the only remaining step before Task 5.
9. Do not write a plan-level SUMMARY.md at Task 5 -- it's mid-plan. Update STATE.md only via
   `state.record-session` with the checkpoint description; do not run `advance-plan`/
   `update-progress`.
10. If context fills again before reaching Task 5: update this file at the next clean
    committed point (after the current arm's write-up is committed, never mid-arm), commit it,
    and return a `## HANDOFF` message instead of continuing.

## Reminders carried forward from the original handoff (still true, don't re-discover)

All ten gotchas from the original `07-HANDOFF.md` (never let `cargo build`/`cargo run`/
`go run .`/`uv run python` run inline in the detached process tree; never read a
`*>`-redirected log while its writer runs; launcher catch-block plain-string logging;
`docker compose` corrupts captured logs in this detached context (use `docker start`/`stop`);
`Start-Job` produced zero samples, use `Start-Process`; OTLP connection sampling is
`-State`-unfiltered; `stub-stats.json` queried before killing the stub; LanceDB manifest
filenames are not small ints; pg_dump/restore via `cmd /c` redirection only;
`document_reconciliation_intents` has no `status` column, it's `desired_status`) still apply
verbatim. Plus the new #11 above (journal append-mode contamination on label reuse).

`config_toml_at_drive_time` is still `"unknown"` in `forensics.json` -- the replay uses
whatever `config/config.toml`/`config.eval.toml` are checked out at HEAD (WIDE
06.3.3-derived-budget values), a disclosed fidelity gap, not a resolved match.
