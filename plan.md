# Plan

Last updated: 2026-10-29 23:01 -0700

Current state only. Done work moves to `plan-history.md` with a one-line pointer here; nothing is deleted. These always stay in this file: the sessions in **Now**, **Rulings** not yet carried by a repo doc, both **Waiting for the user** sections, **Deadlines**, and the user's standing instructions under **Handover**.

## Handover

- **Coordinator:** title unknown, worktree D:/Repos/lancet/.claude/worktrees/vigorous-elgamal-87e693, id local_e5497074-397c-4170-ba22-60a6e066d35b, mode normal.
- **Standing instructions:** (1) each PR open/merge needs the user's yes per lane, asked as the PR-and-merge question; no CI exists, so "merge once CI passes" means merge with `--match-head-commit` at the sha `ready` prints. (2) After each merge, delete that lane's `engine/target` (user's "清 lane 7、8、9 的 target (Recommended)", 2026-10-29 21:20 -0700); never the main checkout's. (3) After each merge, fast-forward the main checkout's `main` to origin (new worktrees cut from it). (4) Sessions start only in a turn the user typed; an answer to AskUserQuestion inside an event turn is refused by the app.
- **Alarm:** a background `sleep 1200` is re-armed after each wake; on wake run `ready` and read `status/`.
- **Unattended log:** none.

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
| 11 | #11 | local_d66def13-7ecf-400a-948a-1c4190ee4f40 (worktree `lane-11-3e9042`, branch `claude/lane-11-3e9042`) | review (58da8f5d) | — |

Started 2026-10-29 18:52 -0700 on the user's "Start 7, 8, 9". The app's branch names are `claude/lane-<key>-<suffix>`, not `lane-<key>`. Lanes 7, 8, 9, 10, 12, 13, 15, 16, 20 and 23 merged → `plan-history.md`. #14 waits for #11. Lanes 15 and 23 started 2026-10-29 21:40 -0700 on the user's "Start 15 and 23". Contract lane 12 ↔ 13 (external `pipeline` echo keys, label `llamaindex`) is in briefs 12 and 13; #14's brief must copy it.

Lanes 10, 11, 12, 13, 16, 20 approved on the user's "六個都開 (Recommended)" (2026-10-29 20:12 -0700); the app refused the start from an event turn, so started 2026-10-29 20:15 -0700 on the user's typed "Start the six lanes".

## Roadmap

Every open issue, once. "Order" is the wave (1 = can start now). "Kind" is `free` (needs no user decision, account, special machine or release) or `limited: <what>`.

#6 is the parent spec (closes when #7 to #15 are merged); it gets no lane. Shared files across lanes (owners to be named in briefs at lane start): `eval/src/lancet_eval/cli.py` (#7, #9, #11, #14, #15), `score.py` (#7, #10, #12), `run.py` (#7, #14, #15), `arms.py`, `preregistration.py` (#12, #15), `preflight.py` (#9, #15), `lever_comparison.py`, `eval/tests/levers_fixture.py` (#10, #12), `eval/pyproject.toml`/`uv.lock` (#7, #10).

| Issue | Order | Blocked by (GitHub) | Same-section wait | Files it owns | Kind |
|---|---|---|---|---|---|
| #6 | — | — | — | spec only | limited: parent spec |
| #11 | 1 | #7 (closed) | none set | new `engine/src/bin/generate_from_context.rs`, `generation/openrouter.rs`, new `parity.py` | free |
| #14 | 3 | #11, #12 | none set | new `external_run.py`, `test_run_external.py` | free |
| #25 | 2 (ruling 5: after #11; #23 merged) | — | none set | clippy `-D warnings` fixes across engine lib, lib tests and two bins (opened by lane 11, 2026-10-29 21:45); shares `engine/src/tests.rs` with #23 and `src/generation/` with #11: start after #11 and #23 merge, or name owners per section | free |
| #29 | 1 (#15 merged) | — (Refs #15) | none set | `raw_events.py` › raw-event dir naming for store-prefixed arms (opened by lane 15, 2026-10-29 22:06) | free |
| #30 | 1 (#15 merged) | — (Refs #15) | none set | `score.py` › judged-dimensions arm list, `calibration.py` draw: use `in_registry_order` (opened by lane 15; blocks nothing for S1, which has no judge) | free |

Lane 7 notes for later briefs: #11 may need `validate_row(data, *, lancet: bool | None = None)` to require prompt + correlation_id for Lancet arms (entry points `validate_row`, `read_export`, `ContextExportRow` are stable); #10/#12 extend the one `require_export_rows` block in `score_run`; #14/#15 extend `_with_context_export` in `drive()`; #12 also edits `journal.py`, where lane 7 added the `context_export` header key. Live check still open: Postgres checkpoint export after a real drive (gateway writes checkpoints async), first live drive in the main checkout.

Lane 15 (21:50) edits outside its sections, accepted: `score.py` `_four_arm_dimensions` uses new `arms.in_registry_order`; `hybrid+graph+rerank+metadata` added to ARMS exclusion in `tests/levers_fixture.py` and to `_built_lever_arms` in `tests/test_preregistration.py`. Lane 10 merged first (PR #27); lane 15 told to merge origin/main and keep both sides.

For #15's brief: lane 9 (293536bd) left `score.py` reading the v1.0 map, since one journal can hold both stores' arms; #15's store-prefixed arm labels must pick the map per arm. #18's "every reader incl. score" criterion is thus partly carried by #15; say so in lane 9's PR body.

`scripts/engine-test-targets.sh` hardcodes Rust test counts (`TOTAL`, `lib`): every lane adding `#[test]`s bumps them, in its own commit; lane 8 owns those lines this wave; a lane merging later (e.g. #11) re-adds its delta on catch-up. Name this in every brief that adds Rust tests.

Baseline notes from lane 7 (2026-10-29 19:15 -0700): on `main`, root-level pytest fails one `scripts/` test on Windows because of CRLF in `*.sh` (→ #16); repo-wide `ruff check` on `eval` has ~740 errors, so lanes hold their own files to zero new ruff errors and PR bodies must say so; parallel cold `cargo` builds have hit rustc `STATUS_STACK_BUFFER_OVERRUN`, so rerun before calling a Rust check failed. Disk (2026-10-29 21:20 -0700): D: filled (each worktree's `engine/target` is 35-47 GB; main checkout's 81 GB); lane 13's link failed with "no space on device". On the user's "清 lane 7、8、9 的 target (Recommended)" the coordinator deleted those three merged lanes' `engine/target` (D: 33 GB → 180 GB free); after each later merge, delete that lane's `engine/target` too (same yes covers the practice). Main checkout's target is untouched. Lane 9 (19:20) adds: `cl.exe` 0xc000012d (out of commit memory) and rustc "only metadata stub found"; ruling to lanes: `CARGO_BUILD_JOBS=2` for every cargo command and rerun once before reporting a failure.

## Waiting for the user to be present

- Live Atlas for S1 (lane 9 / #9), main checkout only, deferred on the user's "等 S1 建 store 時再跑" (2026-10-29): `docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"` then `(cd gateway && atlas schema apply --env eval-s1 --auto-approve)`. Run when the S1 store is built (#15 / S1), with the user's yes.

- Live checks for the LlamaIndex baseline (lane 13 / #13), deferred on the user's "S0 付費跑分時再跑 (Recommended)" (2026-10-29 22:38 -0700). Both are paid calls, so check D-246's S0 cap and ask first: the `input_type` forwarding check (fairness rule 7; command in `baselines/llamaindex/README.md` › Embedding `input_type`) and the 346-document export `uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag --arm llamaindex --out <dir>`.

- Reminder (user's request 2026-10-29 18:48 -0700, "#7 到 #15 全部 merge 之後、S1 付費跑分之前，提醒我跑 S2 程式碼準備的 grill → spec → tickets（範圍見 #6 的留言）"): once #7 to #15 are all merged, and before the S1 paid run, remind the user to run the S2 code-prep grill → spec → tickets round. Scope is the owner comment on #6: OpenRouter Batch submission script; Claude provider-field rewrite (`require_parameters`, `order`); prompt-cache breakpoint; `render` mode turning batch results into `Answer:` lines; scoring for Claude reader arms. S3 (2Wiki) gets its own round after S2's result. Owner action, no lane. Since 2026-10-29.

## Waiting for the user's decision

- Whether to start lanes for #29 and #30 (follow-ups lane 15 opened; both free; #29 owns `raw_events.py`, #30 owns `score.py` › judged arm list and `calibration.py`; no running lane touches them). Not asked yet. Since 2026-10-29 23:01 -0700.

## Deadlines

none
