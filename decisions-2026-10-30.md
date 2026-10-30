# Decisions 2026-10-30 (S2 code-prep grill round)

Recorded by the S2 decision session (branch `claude/s2-code-prep-spec-491e69`). Times are -0700. The user answered in
three rounds; the times are when each answer arrived, to the minute where known (round 3 at 15:17, the earlier two
approximately 15:05 and 15:12). Each item quotes the user's words. The coordinator commits this file.

Repo D-IDs: D-254 to D-259 in `experiments/v1.1/PLAN.md` on branch `claude/s2-code-prep-spec-491e69`, commit 8f91c894, PR #55, merged as a81021d0 on the user's "Merge PR #55" (2026-10-30).
Spec and tickets created on the user's "全部照做 (Recommended)" (2026-10-30, ~15:30): spec #49; tickets #50 (`render`
mode), #51 (Claude request rewrite), #52 (reader arms and replay record kind), #53 (batch submit/fetch), #54 (reader
comparison and cost); #44 and #47 attached as sub-issues with decision comments. Blocked-by: #47←#44; #51←#44;
#50←#44,#47; #52←#44,#51; #53←#50,#51,#52; #54←#52. #44 runs first and alone.

## S2 code prep (grill)

Context facts found in the round (from the code and docs, not decisions):
- The engine's system message is one sentence; the static policy (about 400 o200k tokens) opens the user message,
  below the 512-token cache minimum of Haiku 5.5 and Sonnet 5.5.
- Current list prices: Sonnet 5.5 $2/$10 per MTok, Haiku 5.5 $0.10/$0.50; Batch is half. An S2 dev arm costs about
  $0.5 (Sonnet) and $0.03 (Haiku), far below PLAN's budget sketch.
- Sonnet 5.5 rejects `thinking: disabled` (only `between_tools`); Haiku 5.5 accepts `disabled` at effort high or
  below. OpenRouter maps `reasoning: {enabled: false}` to `thinking: disabled` and documents no `between_tools`.
  Since API version 2026-10-21, Anthropic rejects `temperature`/`top_p`.

| Q | Decision | User's words |
|---|---|---|
| Q1 deepseek arm | Reuse S1's deepseek live records for the chosen arm; Claude arms pair with them | "其他都同意" (round 1, ~15:05) |
| Q2 code placement | Harness subcommands (`lancet-eval batch submit/fetch`), same pattern as `run-external` | "其他都同意" (round 1) |
| Q3 provider rewrite | `model` → Claude slug; `provider` → `{only: ["anthropic"], allow_fallbacks: false}` (drop `require_parameters`, `order`); also delete `temperature`/`top_p`; every other byte as `pack` emits; record the rewritten field list | round 1 "其他都同意", the deletion of `temperature`/`top_p` in round 2 "其他同意" (~15:12) |
| Q4 thinking | Per-reader `reasoning` rewrite table in the pre-registration: Haiku 5.5 `{enabled: false}`; Sonnet 5.5 tried via OpenRouter in the pilot, else the arm goes through the native Anthropic Message Batches API with `thinking: {type: "between_tools"}` (a chat-completions → Messages converter is in scope); `reasoning_tokens > 0` fails closed for a thinking-off arm | round 2 "其他同意" (after the user's own research file on 5.5 thinking controls) |
| Q5 prompt cache | Not built, in S2 or later sessions: the prefix is below the 512-token minimum, and even if cached the saving is about $0.25 for a 351-question Sonnet sync reading. Revisit only if a shared prefix grows (e.g. S3 few-shot extraction) | User asked "所以之後的常session也不用嗎？會不會貴很多？"; answered; then round 2 "其他同意" |
| Q6 `render` mode | Third mode of `generate_from_context`: context-export row + batch result content/usage → the same validation and `Answer:` rendering as `generate`, same output line shape | "其他都同意" (round 1) |
| Q7 spend caps | No mid-run truncation in any stage (amends D-246's hard stops); print a cost estimate before a submit/drive, never refuse. Lane 46's `--stage-cap` (#46, merged as PR #48 before this answer) stays as built, but no cap is set, or an unreachable one | Round 1: "其實我不認為我們有需要在任何環節設上限，因為就算設了上限並提前截斷，我們沒辦法使用只有一半的記錄，等於前面花的錢跟時間都會變成沉沒成本，不如就讓這些測試跑完？" Round 2: "Q7 b 都做到一半甚至可能做完了，就照用但不實際設定上限或設定不可能觸發的上限就好" |
| Q8 reader arm labels and provenance | Label `<S1 arm>@<reader>` (e.g. `merged/hybrid+rerank+metadata@haiku-5.5`); a replay record kind with its own clauses: export row identical to the source row (hash), sent body = `pack` body + declared rewrite, model = declared reader, `is_byok: true`, provider Anthropic, `reasoning_tokens` per Q4, batch id recorded | round 2 "其他同意" |
| Q9 deepseek records | Copied into the S2 run's journal with their export rows, source run and hash recorded, so the S2 run directory scores alone | round 2 "其他同意" |
| Q10 scoring | `answer_usable` on G, paired differences, null guard per reader; cost per answered question at sync list price × tokens for every reader (price table in the pre-registration), actual batch spend reported apart; no evidence Hits@4 | round 2 "其他同意" |
| Q11 batch lifecycle | Manifest (batch id, body hash per request) before submit; refuse a second submit while one is pending; `fetch` is re-runnable; errored/expired requests become error records; `--retry-errors` resubmits only those | "都照建議" (round 3, 15:17) |
| Q12 arms replayed | Generic `--arms`; the S2 stage file names S1's winner | "都照建議" (15:17) |
| Q13 Opus 5.5 | If it joins (D-252), declared "thinking on, effort low" in the same table, exempt from the `reasoning_tokens` refusal; no Opus-specific code | "都照建議" (15:17) |
| Q14 test seams | Offline fixture + fake batch client (primary); `pack` → rewrite → `render` integration test with a built engine (default skip); golden bodies for the Anthropic converter | "都照建議" (15:17) |
| Q15 repo docs | New D-254+ in PLAN.md; notes in the Prompt caching and Budget sketch sections pointing to them; existing D-IDs untouched; one PR | "都照建議" (15:17) |

## #47 chunk_index=0 for external evidence

Decision: the `generate_from_context` bin also parses `<document_id>#<n>`. Not the LlamaIndex export writing
`<document_id>:<n>`, since external chunk IDs would then look like Lancet chunk IDs to ID-matching code (chunk-ID
Hits@4). The fix goes into the S2 tickets. User's words: "都照建議" (2026-10-30 15:17).

## #44 test-suite tiering

Decision: scope as written in #44 (measure, tier fast/slow, remove duplication, drop hardcoded Rust counts; keep the
v1.0 re-score and fail-closed guards). Timing: folded into S2 as its first ticket, run alone before the other S2
lanes (it touches many test files); the S1 paid run needs no S2 code and can proceed in parallel. User's words:
"都照建議" (2026-10-30 15:17).

## Lane 14 open points

1. External reader levers: `evidence_metadata` only is correct. The shipped defaults are
   `["rerank", "evidence_metadata"]` (`config/config.toml`); rerank is retrieval-side and LlamaIndex runs its own, so the
   reader-side levers match. The S0 pre-registration requires nothing more; it states "external reader levers =
   evidence_metadata; rerank is retrieval-side". User's words: "都照建議" (15:17).
2. `generation_model`/`generation_provider_order` taken from the `pack` body: accepted; no engine change. User's
   words: "都照建議" (15:17).

## Lane 15 open points

1. Keep the token name `PREREGISTRATION_S1` (matches D-253's `PREREGISTRATION_06_3_6` form). User's words: "都照建議"
   (15:17).
2. S1 keeps the levers-dev question set (`questions.diag.jsonl`, `heldout_split.json` dev role), the D-237 dev pool of
   100 (90 G, 10 null). User's words: "都照建議" (15:17).

## Scheduled items (unchanged by S2)

Live Atlas at S1 store build and the LlamaIndex live checks at S0 stay as scheduled in plan.md. S2 adds one owner
action after S1: a paid pilot (`batch submit --limit N`) to check `is_byok`, `reasoning_tokens`, the strict schema and
whether Sonnet's `between_tools` passes through OpenRouter.
