Owner decision 2026-11-01 (coordinator session): "全部接受" (items B and C of the coordinator's package). Budget pre-approved within reason: "只要是在合理範圍我們的credit可支付的情況下都直接同意".

## Ask

Two reader runs that build stores first. Both are dev-only and exploratory; they decide nothing. Each has a D-73 pre-registration freeze before it reads anything.

**B. 2Wiki readers (hybrid, no graph).**
- Build the 2Wiki hybrid store from #145's pinned passages, ingested as given.
- Run `hybrid+rerank+metadata` on the D-243 dev questions (100) with deepseek, then replay the context to Claude readers:
  - Haiku 5.5 K=2;
  - Sonnet 5.5 K=1 (sync, `between_tools`, as in S2);
  - Opus 5.5 K=1 (Batch, effort low);
  - deepseek K=2.
- Report `answer_usable`, with #147's yes/no and evidence splits where available.
- Never read the 900 held-out questions.

**C. Full MultiHop-RAG, fresh split first.**
1. From question IDs alone, list every MultiHop-RAG question never read by any run so far: not in `questions.diag.jsonl` and not in the current split's held-out set. Read no held-out content.
2. Carve a fresh dev/held-out split from them with a committed seed and record its SHA-256. The fresh held-out is never read in this issue; it is reserved for #146.
3. Build a full 609-document small store (structure-aware 500/50).
4. Run deepseek `small/hybrid+rerank+metadata` on up to 1,000 fresh-dev questions at K=2.
5. Replay the context to Haiku 5.5 K=2, Sonnet 5.5 K=1 (sync) and Opus 5.5 K=1 (Batch).

Ceiling: Claude $70, OpenRouter $3.

## Files

- New: `eval/corpora/twowiki_s3b_dev.toml`, `eval/corpora/multihop_rag_full*.toml`, and the new split file under `eval/corpora/multihop_rag/` (never `heldout_split.json`)
- `thresholds.py` › new pre-registration constants, each in its own D-73 freeze commit
- New: `experiments/v1.1/EXPLORE-B-2WIKI-READERS.md`, `EXPLORE-C-MHR-FULL.md`
- Run dirs under `eval/runs/`
