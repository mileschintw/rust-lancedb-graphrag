# Plan

Last updated: 2026-10-30 15:25 -0700

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
| 44 | #44 | local_926e074a-57c2-4ee7-8614-c320ca44dced (`claude/lane-44-fc59e2`) | started | — |

Lane 44 started 2026-10-30 15:25 -0700 on the user's typed "Start 44"; runs alone (S2's first ticket; scope includes the CI owner comments on #44). Lane 46 started 2026-10-30 14:43 -0700 on the user's typed "Start 46".

Lane 39 started 2026-10-30 13:35 -0700 on the user's typed "Start 39". Lanes 14, 25, 34, 36 started 2026-10-30 13:03 -0700 on the user's typed "Start all four". No same-section overlap: #14 owns `cli.py` › `run-external`, `run.py` helpers, `external_run.py`; #25 owns `engine/`; #34 `comparison.py`; #36 `score.py` › `_judged_dimensions` detail keys (`comparison.py` does not read them). Brief 14 carries lane 11's open `chunk_index` question (`<doc>#<n>` vs `<doc>:<n>`) for the worker to decide or escalate.

Started 2026-10-29 18:52 -0700 on the user's "Start 7, 8, 9". The app's branch names are `claude/lane-<key>-<suffix>`, not `lane-<key>`. Lanes 7, 8, 9, 10, 11, 12, 13, 15, 16, 20, 23, 14, 25, 29, 30, 34, 36, 39 and 46 merged (#6 closed with #14, PR #45) → `plan-history.md`. Lanes 15 and 23 started 2026-10-29 21:40 -0700 on the user's "Start 15 and 23". Lanes 29 and 30 started 2026-10-29 23:03 -0700 on the user's typed "Start 29 and 30". Contract lane 12 ↔ 13 (external `pipeline` echo keys, label `llamaindex`) is in briefs 12 and 13; #14's brief must copy it.

Lanes 10, 11, 12, 13, 16, 20 approved on the user's "六個都開 (Recommended)" (2026-10-29 20:12 -0700); the app refused the start from an event turn, so started 2026-10-29 20:15 -0700 on the user's typed "Start the six lanes".

## Roadmap

Every open issue, once. "Order" is the wave (1 = can start now). "Kind" is `free` (needs no user decision, account, special machine or release) or `limited: <what>`.

#6 is the parent spec (closes when #7 to #15 are merged); it gets no lane. Shared files across lanes (owners to be named in briefs at lane start): `eval/src/lancet_eval/cli.py` (#7, #9, #11, #14, #15), `score.py` (#7, #10, #12), `run.py` (#7, #14, #15), `arms.py`, `preregistration.py` (#12, #15), `preflight.py` (#9, #15), `lever_comparison.py`, `eval/tests/levers_fixture.py` (#10, #12), `eval/pyproject.toml`/`uv.lock` (#7, #10).

| Issue | Order | Blocked by (GitHub) | Same-section wait | Files it owns | Kind |
|---|---|---|---|---|---|
| #49 | — | — | — | S2 spec only (D-254 to D-259, PR #55) | limited: parent spec |
| #44 | 1, lane 44 running | — | none set | many test files (eval/tests, engine tests), pytest markers, slow opt-in tier, `scripts/engine-test-targets.sh` hardcoded counts; runs first and alone (decisions-2026-10-30 › #44) | free |
| #47 | 2 | #44 | none set | `engine/src/bin/generate_from_context.rs` › chunk-ID parsing: also parse `<document_id>#<n>` (D-259; decided "都照建議", 15:17) | free |
| #51 | 2 | #44 | none set | new `eval/src/lancet_eval/reader_request.py`, `test_reader_request.py` | free |
| #56 | 2 (start right after #44 merges, next to #47 and #51) | — (after #44; files overlap) | none set | `engine/Cargo.toml` › `[profile.*]`, new `.cargo/config.toml` if needed, `docs/testing.md` (job-count rule, timings), CI cache check in #44's workflow (opened 2026-10-30 from a forked side session on the user's "把這件事規劃成issue，然後交給coordinator安排如何？") | limited: item 1 (sccache machine setup) needs the user's yes; the rest is free |
| #50 | 3 | #44, #47 | none set | `engine/src/bin/generate_from_context.rs` › new `render` mode (same file as #47) | free |
| #52 | 3 | #44, #51 | none set | `arms.py` reader suffix, `provenance.py`, `journal.py`, new `replay.py`, `preregistration.py`, `thresholds.py`, `cli.py` › `replay-init`, `test_replay.py` | free |
| #53 | 4 | #50, #51, #52 | none set | new `batch.py`, `batch_client.py`, `cli.py` › `batch`, `parity.py` (if needed), `test_batch.py` | free |
| #54 | 4 | #52 | none set | `lever_comparison.py`/`comparison.py`, `score.py` (reader-arm Hits@4 skip), `measure.py` › `compute_spend`, `test_reader_comparison.py` | free |

S2 chain (spec #49, decisions D-254 to D-259 in PR #55, `decisions-2026-10-30.md`): #44 alone → #47 ∥ #51 → #50 (after #47) ∥ #52 (after #51) → #53 ∥ #54. Mechanical overlaps to name in briefs: `cli.py` (#52 `replay-init`, #53 `batch`), `generate_from_context.rs` (#47 then #50, sequential by blocking).

Lane 7 notes for later briefs: #11 may need `validate_row(data, *, lancet: bool | None = None)` to require prompt + correlation_id for Lancet arms (entry points `validate_row`, `read_export`, `ContextExportRow` are stable); #10/#12 extend the one `require_export_rows` block in `score_run`; #14/#15 extend `_with_context_export` in `drive()`; #12 also edits `journal.py`, where lane 7 added the `context_export` header key. Live check still open: Postgres checkpoint export after a real drive (gateway writes checkpoints async), first live drive in the main checkout.

Lane 15 (21:50) edits outside its sections, accepted: `score.py` `_four_arm_dimensions` uses new `arms.in_registry_order`; `hybrid+graph+rerank+metadata` added to ARMS exclusion in `tests/levers_fixture.py` and to `_built_lever_arms` in `tests/test_preregistration.py`. Lane 10 merged first (PR #27); lane 15 told to merge origin/main and keep both sides.

For #15's brief: lane 9 (293536bd) left `score.py` reading the v1.0 map, since one journal can hold both stores' arms; #15's store-prefixed arm labels must pick the map per arm. #18's "every reader incl. score" criterion is thus partly carried by #15; say so in lane 9's PR body.

`scripts/engine-test-targets.sh` hardcodes Rust test counts (`TOTAL`, `lib`): every lane adding `#[test]`s bumps them, in its own commit; lane 8 owns those lines this wave; a lane merging later (e.g. #11) re-adds its delta on catch-up. Name this in every brief that adds Rust tests.

Baseline notes from lane 7 (2026-10-29 19:15 -0700): on `main`, root-level pytest fails one `scripts/` test on Windows because of CRLF in `*.sh` (→ #16); repo-wide `ruff check` on `eval` has ~740 errors, so lanes hold their own files to zero new ruff errors and PR bodies must say so; parallel cold `cargo` builds have hit rustc `STATUS_STACK_BUFFER_OVERRUN`, so rerun before calling a Rust check failed. Disk (2026-10-29 21:20 -0700): D: filled (each worktree's `engine/target` is 35-47 GB; main checkout's 81 GB); lane 13's link failed with "no space on device". On the user's "清 lane 7、8、9 的 target (Recommended)" the coordinator deleted those three merged lanes' `engine/target` (D: 33 GB → 180 GB free); after each later merge, delete that lane's `engine/target` too (same yes covers the practice). Main checkout's target is untouched. Lane 9 (19:20) adds: `cl.exe` 0xc000012d (out of commit memory) and rustc "only metadata stub found"; ruling to lanes: `CARGO_BUILD_JOBS=2` for every cargo command and rerun once before reporting a failure.

## Waiting for the user to be present

- Live Atlas for S1 (lane 9 / #9), main checkout only, deferred on the user's "等 S1 建 store 時再跑" (2026-10-29): `docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"` then `(cd gateway && atlas schema apply --env eval-s1 --auto-approve)`. Run when the S1 store is built (#15 / S1), with the user's yes.

- Live checks for the LlamaIndex baseline (lane 13 / #13), deferred on the user's "S0 付費跑分時再跑 (Recommended)" (2026-10-29 22:38 -0700). Both are paid calls, so ask first (D-258 amends D-246: no mid-run cap; print a cost estimate): the `input_type` forwarding check (fairness rule 7; command in `baselines/llamaindex/README.md` › Embedding `input_type`) and the 346-document export `uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag --arm llamaindex --out <dir>`.

- S2 paid pilot (from `decisions-2026-10-30.md` › Scheduled items): after S1, once #53 has merged, the owner runs `batch submit --limit N` to check `is_byok`, `reasoning_tokens`, the strict schema and whether Sonnet's `between_tools` passes through OpenRouter. Paid; ask first.

The S2 grill reminder was given 2026-10-30 14:42 -0700. The round ran in decision session local_ab3487b9-5b99-46f4-8d1c-2ed3f5e8f4b6 (branch `claude/s2-code-prep-spec-491e69`) on the user's "幫我開一個新session做 grill → spec → tickets 這套流程以及所有相關需要決策的事務". It produced spec #49, tickets #50 to #54, #44 and #47 attached, D-254 to D-259 (PR #55), and `decisions-2026-10-30.md` → plan-history.

## Waiting for the user's decision

none (PR #55 merged by the user 2026-10-30 15:23 -0700 as a81021d0; user's words: "已經merge了")

## Deadlines

none
