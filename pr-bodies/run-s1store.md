Records the S1 dev run (RUN-S0-S1.md step 4) and fills EXPERIMENT-S1.md's Result section.

**Result: keep small; the graph stays out.** S2 replays `small/hybrid+rerank+metadata`.

- Chunking: `merged/hybrid+rerank+metadata` against small is n_pos 4, n_neg 5 of 90 pairs, so small is kept.
- Graph on small: n_pos 2, n_neg 10. The net gain is -8, and +5 points needs 5, so the graph stays out.
- All null guards are evaluable and pass (10 null pairs, b = 0, c = 0).
- Each of the four arms has 100 of 100 records, all `success`. The context export holds 400 rows.
- Observed spend was $0.67 ($0.2069 small, $0.4602 merged).

The commit adds:
- `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`, driven on `main` at `971094f5`
- `eval/corpora/multihop_rag/document_map.eval-s1.json`, which `score` reads for every `merged/` record
- the Result section in EXPERIMENT-S1.md

The main checkout still holds untracked copies of the run directory and the document map. Delete them before pulling this merge there.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
