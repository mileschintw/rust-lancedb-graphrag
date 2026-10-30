# Plan

Last updated: 2026-10-29 18:48 -0700

Current state only. Done work moves to `plan-history.md` with a one-line pointer here; nothing is deleted. These always stay in this file: the sessions in **Now**, **Rulings** not yet carried by a repo doc, both **Waiting for the user** sections, **Deadlines**, and the user's standing instructions under **Handover**.

## Handover

- **Coordinator:** title unknown, worktree D:/Repos/lancet/.claude/worktrees/vigorous-elgamal-87e693, id local_e5497074-397c-4170-ba22-60a6e066d35b, mode normal.
- **Standing instructions:** none.
- **Unattended log:** none.

## Rulings

1. Lane workers (7, 8, 9) may push their own lane branch to origin; PR open and merge still need the user's yes. User's words (2026-10-29 18:55 -0700), answering lane 8's push question: "都開worktree再merge", then on clarifying (local merge without push vs push then PR): "不對，可以 push 再開 PR". Sent to all three lanes.
2. S1 per-store document map is its own issue, #18, which blocks #15 and is blocked by #9 (sub-issue of #6). User's words (2026-10-29, answering the lane 9 finding): "New issue, blocks #15".
3. #18 moves whole into lane 9 (writer already on its branch at 25940d63, plus all readers); lane 9's PR closes #9 and #18; the #18 → #9 blocking link was removed since both land in one PR. User's words (2026-10-29 19:24 -0700): "整個搬到 lane 9".

Not a lane: PR #17 `docs/no-triage-labels` ("docs(agents): record that this repo uses no triage labels"), opened 2026-10-29 19:21 -0700 outside relay; left to the user.

## Now

| Key | Issues | Session | State | Parked until |
|---|---|---|---|---|
| 9 | #9, #18 | local_480eb168-cfbd-41d1-8c41-a352e6f35553 (worktree `lane-9-fa5fe0`, branch `claude/lane-9-fa5fe0`) | catching up with main after #19, rerunning pytest; then PR + merge on the user's "先追 main 重跑，再開 PR 並 merge" (2026-10-29 20:0x) | — |

Started 2026-10-29 18:52 -0700 on the user's "Start 7, 8, 9". The app's branch names are `claude/lane-<key>-<suffix>`, not `lane-<key>`. Lanes 7 and 8 merged → `plan-history.md`.

Approved, not yet started: lanes 10, 11, 12, 13, 16, 20 (briefs written, ab789a1f) on the user's "六個都開 (Recommended)" (2026-10-29 20:12 -0700). The app refused `start_session` because that turn began from a session event, not a typed message; start all six in the next turn the user types.

## Roadmap

Every open issue, once. "Order" is the wave (1 = can start now). "Kind" is `free` (needs no user decision, account, special machine or release) or `limited: <what>`.

#6 is the parent spec (closes when #7 to #15 are merged); it gets no lane. Shared files across lanes (owners to be named in briefs at lane start): `eval/src/lancet_eval/cli.py` (#7, #9, #11, #14, #15), `score.py` (#7, #10, #12), `run.py` (#7, #14, #15), `arms.py`, `preregistration.py` (#12, #15), `preflight.py` (#9, #15), `lever_comparison.py`, `eval/tests/levers_fixture.py` (#10, #12), `eval/pyproject.toml`/`uv.lock` (#7, #10).

| Issue | Order | Blocked by (GitHub) | Same-section wait | Files it owns | Kind |
|---|---|---|---|---|---|
| #6 | — | — | — | spec only | limited: parent spec |
| #9 | 1 | — | none set | `config.py`, `seed.py`, `test_seed.py`, `test_stack_preflight.py` | free |
| #10 | 1 | #7 (closed) | none set | `metrics.py`, `report.py`, `test_metrics.py` | free |
| #11 | 1 | #7 (closed) | none set | new `engine/src/bin/generate_from_context.rs`, `generation/openrouter.rs`, new `parity.py` | free |
| #12 | 1 | #7 (closed) | none set | `provenance.py`, `usability.py`, `p4.py`, `journal.py` (record kind) | free |
| #13 | 1 | #7 (closed) | none set | new `baselines/llamaindex/` | free |
| #14 | 3 | #11, #12 | none set | new `external_run.py`, `test_run_external.py` | free |
| #18 | 1 (lane 9) | — | none set | in lane 9: `seed.py` › `load_document_map`, map lookup in `identity.py`, `diagnostic.py`, `preflight.py`, `cli.py` | free |
| #15 | 3 | #8, #9, #12, #18 | none set | `corpus.py`, `test_run_arms.py` | free |
| #16 | 1 | — | none set | `.gitattributes` | free |
| #20 | 1 | — | none set | `cli.py` › `run` command (shared with #14, #15) | free |

Lane 7 notes for later briefs: #11 may need `validate_row(data, *, lancet: bool | None = None)` to require prompt + correlation_id for Lancet arms (entry points `validate_row`, `read_export`, `ContextExportRow` are stable); #10/#12 extend the one `require_export_rows` block in `score_run`; #14/#15 extend `_with_context_export` in `drive()`; #12 also edits `journal.py`, where lane 7 added the `context_export` header key. Live check still open: Postgres checkpoint export after a real drive (gateway writes checkpoints async), first live drive in the main checkout.

For #15's brief: lane 9 (293536bd) left `score.py` reading the v1.0 map, since one journal can hold both stores' arms; #15's store-prefixed arm labels must pick the map per arm. #18's "every reader incl. score" criterion is thus partly carried by #15; say so in lane 9's PR body.

`scripts/engine-test-targets.sh` hardcodes Rust test counts (`TOTAL`, `lib`): every lane adding `#[test]`s bumps them, in its own commit; lane 8 owns those lines this wave; a lane merging later (e.g. #11) re-adds its delta on catch-up. Name this in every brief that adds Rust tests.

Baseline notes from lane 7 (2026-10-29 19:15 -0700): on `main`, root-level pytest fails one `scripts/` test on Windows because of CRLF in `*.sh` (→ #16); repo-wide `ruff check` on `eval` has ~740 errors, so lanes hold their own files to zero new ruff errors and PR bodies must say so; parallel cold `cargo` builds have hit rustc `STATUS_STACK_BUFFER_OVERRUN`, so rerun before calling a Rust check failed. Lane 9 (19:20) adds: `cl.exe` 0xc000012d (out of commit memory) and rustc "only metadata stub found"; ruling to lanes: `CARGO_BUILD_JOBS=2` for every cargo command and rerun once before reporting a failure.

## Waiting for the user to be present

- Live Atlas for S1 (lane 9 / #9), main checkout only, deferred on the user's "等 S1 建 store 時再跑" (2026-10-29): `docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"` then `(cd gateway && atlas schema apply --env eval-s1 --auto-approve)`. Run when the S1 store is built (#15 / S1), with the user's yes.

- Reminder (user's request 2026-10-29 18:48 -0700, "#7 到 #15 全部 merge 之後、S1 付費跑分之前，提醒我跑 S2 程式碼準備的 grill → spec → tickets（範圍見 #6 的留言）"): once #7 to #15 are all merged, and before the S1 paid run, remind the user to run the S2 code-prep grill → spec → tickets round. Scope is the owner comment on #6: OpenRouter Batch submission script; Claude provider-field rewrite (`require_parameters`, `order`); prompt-cache breakpoint; `render` mode turning batch results into `Answer:` lines; scoring for Claude reader arms. S3 (2Wiki) gets its own round after S2's result. Owner action, no lane. Since 2026-10-29.

## Waiting for the user's decision

none

## Deadlines

none
