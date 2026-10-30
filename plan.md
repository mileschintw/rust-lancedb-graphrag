# Plan

Last updated: 2026-10-29 18:48 -0700

Current state only. Done work moves to `plan-history.md` with a one-line pointer here; nothing is deleted. These always stay in this file: the sessions in **Now**, **Rulings** not yet carried by a repo doc, both **Waiting for the user** sections, **Deadlines**, and the user's standing instructions under **Handover**.

## Handover

- **Coordinator:** title unknown, worktree D:/Repos/lancet/.claude/worktrees/vigorous-elgamal-87e693, id unknown, mode normal.
- **Standing instructions:** none.
- **Unattended log:** none.

## Rulings

none

## Now

| Key | Issues | Session | State | Parked until |
|---|---|---|---|---|

## Roadmap

Every open issue, once. "Order" is the wave (1 = can start now). "Kind" is `free` (needs no user decision, account, special machine or release) or `limited: <what>`.

#6 is the parent spec (closes when #7 to #15 are merged); it gets no lane. Shared files across lanes (owners to be named in briefs at lane start): `eval/src/lancet_eval/cli.py` (#7, #9, #11, #14, #15), `score.py` (#7, #10, #12), `run.py` (#7, #14, #15), `arms.py`, `preregistration.py` (#12, #15), `preflight.py` (#9, #15), `lever_comparison.py`, `eval/tests/levers_fixture.py` (#10, #12), `eval/pyproject.toml`/`uv.lock` (#7, #10).

| Issue | Order | Blocked by (GitHub) | Same-section wait | Files it owns | Kind |
|---|---|---|---|---|---|
| #6 | — | — | — | spec only | limited: parent spec |
| #7 | 1 | — | none set | new `eval/src/lancet_eval/context_export.py`, `test_context_export.py` | free |
| #8 | 1 | — | none set | `engine/src/chunker/`, `engine/src/ingest.rs`, `gateway/main.go` | free |
| #9 | 1 | — | none set | `config.py`, `seed.py`, `test_seed.py`, `test_stack_preflight.py` | free |
| #10 | 2 | #7 | none set | `metrics.py`, `report.py`, `test_metrics.py` | free |
| #11 | 2 | #7 | none set | new `engine/src/bin/generate_from_context.rs`, `generation/openrouter.rs`, new `parity.py` | free |
| #12 | 2 | #7 | none set | `provenance.py`, `usability.py`, `p4.py`, `journal.py` (record kind) | free |
| #13 | 2 | #7 | none set | new `baselines/llamaindex/` | free |
| #14 | 3 | #11, #12 | none set | new `external_run.py`, `test_run_external.py` | free |
| #15 | 3 | #8, #9, #12 | none set | `corpus.py`, `test_run_arms.py` | free |

## Waiting for the user to be present

- Reminder (user's request 2026-10-29 18:48 -0700, "#7 到 #15 全部 merge 之後、S1 付費跑分之前，提醒我跑 S2 程式碼準備的 grill → spec → tickets（範圍見 #6 的留言）"): once #7 to #15 are all merged, and before the S1 paid run, remind the user to run the S2 code-prep grill → spec → tickets round. Scope is the owner comment on #6: OpenRouter Batch submission script; Claude provider-field rewrite (`require_parameters`, `order`); prompt-cache breakpoint; `render` mode turning batch results into `Answer:` lines; scoring for Claude reader arms. S3 (2Wiki) gets its own round after S2's result. Owner action, no lane. Since 2026-10-29.

## Waiting for the user's decision

none

## Deadlines

none
