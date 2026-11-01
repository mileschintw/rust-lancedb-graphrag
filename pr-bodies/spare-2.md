## Summary

`score` stops loading the v1.0 document map for every journal. A corpus on #149's stores (all 609 MultiHop-RAG documents, 2Wiki) has no `document_map.json`, so it used to stop before reading any record.

```diff
 score_run
-  doc_map = load v1.0 map                      # always; fails without document_map.json
   for each record with retrieved chunks
     check its document IDs against the map of its arm's store   # loaded on first use
   if the journal holds an external record
-    check external IDs against the v1.0 map
+    check external IDs against the map of [documents] external_store (unset: v1.0)
```

A corpus file can now name the store whose document map an external arm's (D-247) document IDs are checked against:

```toml
[documents]
external_store = "full"   # a store prefix (small, merged, full, twowiki); unset keeps the v1.0 map
```

`compare-levers` re-checks the external clauses against the same store. An unknown or non-string value is refused when the corpus loads. #146's LlamaIndex arm on the 609 documents carries `eval-full`'s document IDs, so its corpus sets `external_store = "full"`.

Closes #164

## Evidence

- **Before:** a journal with only merged-store arms and no v1.0 map fails with `ScoreError: Could not load document map for corpus 'levers_split': no document map for store 'eval'`. The first test below fails this way on main.
  **After:** `eval/tests/test_score_store_maps.py`:
  - `test_a_journal_with_no_v1_arm_scores_without_the_v1_map`: it scores, and only the merged store's map is loaded.
  - `test_a_v1_arm_still_needs_the_v1_map`: an unprefixed arm still refuses without one.
- **External store:** `eval/tests/test_score_external_store.py`:
  - With `external_store = "merged"`, `score` reads the merged map for the external arm.
  - An external document ID from the other (v1.0) store is refused (D-247), in `score` and in `compare-levers`.
  - The key defaults to unset; an unknown or non-string prefix is refused.
- **Fast tier:** `PYTHONUTF8=1 uv run --project eval pytest -n auto --dist loadfile` gives 3222 passed and 14 skipped on `31c1da79`. The touched files pass again on `084746bb`: 239 passed.

## Review

One round (Standards and Spec together): no blocker.
- **Fixed:** the comment now says the attribute holds the store name; a non-string `external_store` is refused as `CorpusError`, with a test; `compare-levers` reads `config.external_store` directly; a test name that claimed more than it showed was renamed.
- **Left:** the store-resolution line is repeated in `score.py` and `lever_comparison.py` (two call sites).
- **Left:** the tests reuse the `s0` fixture and helpers from `test_run_external.py`, `test_provenance.py` and `test_s1_store_arms.py`, instead of a `conftest.py` move outside this change.
- **Left:** `external_store = "small"` loads the v1.0 map under a second cache key, which is harmless.

## Merge Danger

**Door:** two-way

A corpus without `external_store` scores exactly as before, except that a run with no v1.0-store arm no longer needs the v1.0 map.

**Blast Radius:** scoring

Only `score` and `compare-levers` map checks change. Engine, gateway and stores are untouched.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
