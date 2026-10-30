# Plan

Last updated: 2026-10-30 15:02 -0700

Current state only. Done work moves to `plan-history.md` with a one-line pointer here; nothing is deleted. These always stay in this file: the sessions in **Now**, **Rulings** not yet carried by a repo doc, both **Waiting for the user** sections, **Deadlines**, and the user's standing instructions under **Handover**.

## Handover

- **Coordinator:** title unknown, worktree D:/Repos/lancet/.claude/worktrees/vigorous-elgamal-87e693, id local_e5497074-397c-4170-ba22-60a6e066d35b, mode normal.
- **Standing instructions:** (1) each PR open/merge needs the user's yes per lane, asked as the PR-and-merge question; no CI exists, so "merge once CI passes" means merge with `--match-head-commit` at the sha `ready` prints. (2) After each merge, delete that lane's `engine/target` (user's "清 lane 7、8、9 的 target (Recommended)", 2026-10-29 21:20 -0700); never the main checkout's. (3) After each merge, fast-forward the main checkout's `main` to origin (new worktrees cut from it). (4) Sessions start only in a turn the user typed; an answer to AskUserQuestion inside an event turn is refused by the app.
- **Alarm:** a background `sleep 1200` is re-armed after each wake; on wake run `ready` and read `status/`.
- **Unattended log:** none.
- **Pause (user, 2026-10-29 23:26 -0700):** "現在還在執行的session結束之後，我們先wrap up，做總結並暫時休息". Done 2026-10-29 23:58 -0700. Resumed 2026-10-30 on the user's "繼續開始"; lanes 14, 25, 34, 36 started on "Start all four".

## Rulings

1. Lane workers (7, 8, 9) may push their own lane branch to origin; PR open and merge still need the user's yes. User's words (2026-10-29 18:55 -0700), answering lane 8's push question: "都開worktree再merge", then on clarifying (local merge without push vs push then PR): "不對，可以 push 再開 PR". Sent to all three lanes.
2. S1 per-store document map is its own issue, #18, which blocks #15 and is blocked by #9 (sub-issue of #6). User's words (2026-10-29, answering the lane 9 finding): "New issue, blocks #15".
3. #18 moves whole into lane 9 (writer already on its branch at 25940d63, plus all readers); lane 9's PR closes #9 and #18; the #18 → #9 blocking link was removed since both land in one PR. User's words (2026-10-29 19:24 -0700): "整個搬到 lane 9".
4. #15 adds the pre-registration type that carries external pipelines (e.g. `@dataclass(frozen=True) class StagePreRegistration(LeverPreRegistration): external_pipelines: tuple[tuple[str, ExternalPipeline], ...] = ()` in `thresholds.py`), type only, no stage constant. User's words (2026-10-29 21:35 -0700), answering lane 12's question: "放進 #15 (Recommended)". Copy into #15's brief; also: #14 fills `generation_model`/`generation_provider_order` in the `external` block from what the generate-only bin actually sent (lane 12 report).
5. #25 (clippy `-D warnings` on main) gets a lane, started only after #11 and #23 have both merged. User's words (2026-10-29 21:58 -0700), answering "When should the #25 clippy lane start?": "After #11 and #23". When both merge: write `briefs/25.md`, then start it in the next turn the user types (the app refuses starts from event turns); this answer is the go-ahead. #11's "cargo clippy passes" criterion is carried by #25; say so in lane 11's PR body.

6. The LlamaIndex baseline (#13) sends the rerank model only the chunk body, as Lancet does, not LlamaIndex's metadata header plus body (fairness rule 5, `experiments/v1.1/RESEARCH.md`). User's words (2026-10-29 22:38 -0700), answering lane 13's open question: "改成只送內文 (Recommended)". Sent to lane 13. Done: lane 13 pushed f3b462e0; PR #31 merged on the user's "開 PR 並 merge (Recommended)" from the same answer set.

Not a lane: PR #17 `docs/no-triage-labels` ("docs(agents): record that this repo uses no triage labels"), opened 2026-10-29 19:21 -0700 outside relay; left to the user.

## Now

| Key | Issues | Session | State | Parked until |
|---|---|---|---|---|
| — | — | none running | — | — |

Lane 46 started 2026-10-30 14:43 -0700 on the user's typed "Start 46".

Lane 39 started 2026-10-30 13:35 -0700 on the user's typed "Start 39". Lanes 14, 25, 34, 36 started 2026-10-30 13:03 -0700 on the user's typed "Start all four". No same-section overlap: #14 owns `cli.py` › `run-external`, `run.py` helpers, `external_run.py`; #25 owns `engine/`; #34 `comparison.py`; #36 `score.py` › `_judged_dimensions` detail keys (`comparison.py` does not read them). Brief 14 carries lane 11's open `chunk_index` question (`<doc>#<n>` vs `<doc>:<n>`) for the worker to decide or escalate.

Started 2026-10-29 18:52 -0700 on the user's "Start 7, 8, 9". The app's branch names are `claude/lane-<key>-<suffix>`, not `lane-<key>`. Lanes 7, 8, 9, 10, 11, 12, 13, 15, 16, 20, 23, 14, 25, 29, 30, 34, 36, 39 and 46 merged (#6 closed with #14, PR #45) → `plan-history.md`. Lanes 15 and 23 started 2026-10-29 21:40 -0700 on the user's "Start 15 and 23". Lanes 29 and 30 started 2026-10-29 23:03 -0700 on the user's typed "Start 29 and 30". Contract lane 12 ↔ 13 (external `pipeline` echo keys, label `llamaindex`) is in briefs 12 and 13; #14's brief must copy it.

Lanes 10, 11, 12, 13, 16, 20 approved on the user's "六個都開 (Recommended)" (2026-10-29 20:12 -0700); the app refused the start from an event turn, so started 2026-10-29 20:15 -0700 on the user's typed "Start the six lanes".

## Roadmap

Every open issue, once. "Order" is the wave (1 = can start now). "Kind" is `free` (needs no user decision, account, special machine or release) or `limited: <what>`.

#6 is the parent spec (closes when #7 to #15 are merged); it gets no lane. Shared files across lanes (owners to be named in briefs at lane start): `eval/src/lancet_eval/cli.py` (#7, #9, #11, #14, #15), `score.py` (#7, #10, #12), `run.py` (#7, #14, #15), `arms.py`, `preregistration.py` (#12, #15), `preflight.py` (#9, #15), `lever_comparison.py`, `eval/tests/levers_fixture.py` (#10, #12), `eval/pyproject.toml`/`uv.lock` (#7, #10).

| Issue | Order | Blocked by (GitHub) | Same-section wait | Files it owns | Kind |
|---|---|---|---|---|---|
| #47 | 1 | — (Refs #14, #11, #13) | none set | `engine/src/bin/generate_from_context.rs` chunk-ID parsing or `baselines/llamaindex` chunk IDs; decision first (fairness rules, RESEARCH.md) (opened by coordinator 2026-10-30 on the user's "chunk_index 公平性 (Recommended)") | limited: the fix needs the user's choice among the three options in the issue |
| #44 | 2 (code prep closed 2026-10-30) | — | none set | pytest markers, the slow opt-in tier, `scripts/engine-test-targets.sh` (removes hardcoded counts) (opened 2026-10-30 from a forked side session on the user's request) | limited: scope it in the S2 grill round or after the S1 paid run; no lane now |

Lane 7 notes for later briefs: #11 may need `validate_row(data, *, lancet: bool | None = None)` to require prompt + correlation_id for Lancet arms (entry points `validate_row`, `read_export`, `ContextExportRow` are stable); #10/#12 extend the one `require_export_rows` block in `score_run`; #14/#15 extend `_with_context_export` in `drive()`; #12 also edits `journal.py`, where lane 7 added the `context_export` header key. Live check still open: Postgres checkpoint export after a real drive (gateway writes checkpoints async), first live drive in the main checkout.

Lane 15 (21:50) edits outside its sections, accepted: `score.py` `_four_arm_dimensions` uses new `arms.in_registry_order`; `hybrid+graph+rerank+metadata` added to ARMS exclusion in `tests/levers_fixture.py` and to `_built_lever_arms` in `tests/test_preregistration.py`. Lane 10 merged first (PR #27); lane 15 told to merge origin/main and keep both sides.

For #15's brief: lane 9 (293536bd) left `score.py` reading the v1.0 map, since one journal can hold both stores' arms; #15's store-prefixed arm labels must pick the map per arm. #18's "every reader incl. score" criterion is thus partly carried by #15; say so in lane 9's PR body.

`scripts/engine-test-targets.sh` hardcodes Rust test counts (`TOTAL`, `lib`): every lane adding `#[test]`s bumps them, in its own commit; lane 8 owns those lines this wave; a lane merging later (e.g. #11) re-adds its delta on catch-up. Name this in every brief that adds Rust tests.

Baseline notes from lane 7 (2026-10-29 19:15 -0700): on `main`, root-level pytest fails one `scripts/` test on Windows because of CRLF in `*.sh` (→ #16); repo-wide `ruff check` on `eval` has ~740 errors, so lanes hold their own files to zero new ruff errors and PR bodies must say so; parallel cold `cargo` builds have hit rustc `STATUS_STACK_BUFFER_OVERRUN`, so rerun before calling a Rust check failed. Disk (2026-10-29 21:20 -0700): D: filled (each worktree's `engine/target` is 35-47 GB; main checkout's 81 GB); lane 13's link failed with "no space on device". On the user's "清 lane 7、8、9 的 target (Recommended)" the coordinator deleted those three merged lanes' `engine/target` (D: 33 GB → 180 GB free); after each later merge, delete that lane's `engine/target` too (same yes covers the practice). Main checkout's target is untouched. Lane 9 (19:20) adds: `cl.exe` 0xc000012d (out of commit memory) and rustc "only metadata stub found"; ruling to lanes: `CARGO_BUILD_JOBS=2` for every cargo command and rerun once before reporting a failure.

## Waiting for the user to be present

- Live Atlas for S1 (lane 9 / #9), main checkout only, deferred on the user's "等 S1 建 store 時再跑" (2026-10-29): `docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"` then `(cd gateway && atlas schema apply --env eval-s1 --auto-approve)`. Run when the S1 store is built (#15 / S1), with the user's yes.

- Live checks for the LlamaIndex baseline (lane 13 / #13), deferred on the user's "S0 付費跑分時再跑 (Recommended)" (2026-10-29 22:38 -0700). Both are paid calls, so check D-246's S0 cap and ask first: the `input_type` forwarding check (fairness rule 7; command in `baselines/llamaindex/README.md` › Embedding `input_type`) and the 346-document export `uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag --arm llamaindex --out <dir>`.

- Reminder (user's request 2026-10-29 18:48 -0700, "#7 到 #15 全部 merge 之後、S1 付費跑分之前，提醒我跑 S2 程式碼準備的 grill → spec → tickets（範圍見 #6 的留言）"): once #7 to #15 are all merged, and before the S1 paid run, remind the user to run the S2 code-prep grill → spec → tickets round. Condition met 2026-10-30 14:42 -0700 (#14 merged, PR #45); reminder given the same turn. On the user's "幫我開一個新session做 grill → spec → tickets 這套流程以及所有相關需要決策的事務" (2026-10-30 14:47 -0700), decision session local_ab3487b9-5b99-46f4-8d1c-2ed3f5e8f4b6 ("S2 code prep: grill → spec → tickets", branch `claude/s2-code-prep-spec-*`) runs the round. It also collects decisions on #47, #44, lane 14's lever/generation-model points and lane 15's `PREREGISTRATION_S1` name and S1 question set. Answers go to `decisions-2026-10-30.md` here (the coordinator commits it). Read that file before acting on any of them. Scope is the owner comment on #6: OpenRouter Batch submission script; Claude provider-field rewrite (`require_parameters`, `order`); prompt-cache breakpoint; `render` mode turning batch results into `Answer:` lines; scoring for Claude reader arms. S3 (2Wiki) gets its own round after S2's result. Owner action, no lane. Since 2026-10-29. Also raise #44 (test suite tiering and time budget) in that round, or in the gap after the S1 paid run (forked side session local_04f7c00e-2215-4c3e-a90b-c054163bf26c, 2026-10-30, relaying the user's "可以，開issue並通知coordinator").

## Waiting for the user's decision

none

## Deadlines

none
