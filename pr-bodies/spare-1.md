Freezes the run plan of S3's held-out reader grid on 2Wiki, and adds what its cells need to run, before any held-out cell runs.

Refs #163

## Why

#163 asks for S3's held-out reader grid: 4 readers by 6 context columns over 2Wiki's 900 held-out questions. Claude batches go in stages before the credit expires on 2026-11-03, and nothing is scored until an analysis plan is frozen. The harness could not run any of it:

- `replay-init` refused every non-dev corpus (D-237).
- There was no closed-book path.
- A replay pre-registration had to carry a Holm family, which is analysis.
- There was no held-out split or question file for 2Wiki.

The coordinator ruled that this harness code belongs in #163's scope.

## What changes

- **D-291** (`experiments/v1.1/PLAN.md`) freezes the plan in two steps:
  - the run plan first: which cells run, K, transports and thinking, and no analysis;
  - then blinding: no run is scored or read for its answers until a separate analysis constant is frozen; then every run is scored once.
- **`RUN_PLAN_S3_HELDOUT`** (`thresholds.py`, type `ReaderGridRunPlan`) is frozen alone in commit `99b9d29e` (D-73). It holds:
  - 24 cells: Sonnet's graph-haiku, graph-sonnet and graph-opus cells are `optional`, every other cell is `core`;
  - Claude on OpenRouter's Batch API: Haiku thinking off, Sonnet and Opus on at effort low;
  - deepseek: replicate 1 from the engine drive, replicate 2 through the sync API;
  - K: deepseek and Haiku 2, Sonnet and Opus 1 (D-283).
- **Run-plan plumbing:**
  - A corpus names one column with `[preregistration] column`, and `preregistration.resolve(token, column)` returns that column's `ColumnRunPlan`.
  - A run plan without a column is refused.
  - `score`, `compare-levers`, `explore_readout`, `evidence_split`, `judge`, `judge-answers` and the unpark gates refuse a run-plan corpus.
- **Held-out replay gate:**
  - `replay-init` carries a held-out corpus only when its token and column resolve to a run-plan column.
  - The source run must come from the same corpus.
  - A run-plan source run is carried into no other corpus.
- **Closed-book column:**
  - A new arm, `twowiki/closed-book`, sits outside the engine registry, so no drive sends it.
  - `lancet-eval closed-book-init` writes one export row per question with no evidence, packed with the engine's own model-only prompt. The bin runs with `allow_model_only_answers` on for these rows only.
  - `batch submit` sends deepseek's replicates 1..K through the sync API, then the readers over the same rows.
- **2Wiki held-out files** (`twowiki_h`):
  - `twowiki/s3h_split.json`: the D-243 split with every held-out ID in G. It is built from IDs alone, since every 2Wiki question has an answer.
  - The held-out questions file, gitignored.
  - A question-type map with no answers, so the analysis can split by question type (#167).
- **Six column corpora** (`twowiki_s3h_*.toml`) and four engine overlays (`config.eval-2wiki-s3h-<writer>.toml`, graph table set `s3h_<writer>`) for the graph columns.
- **`experiments/v1.1/RUN-S3-HELDOUT.md`**: the run guide, with cost estimates against the lane's ceilings.

## Testing

- `uv run --project eval pytest -n auto --dist loadfile`: 3252 passed, 14 skipped.
- New tests, each against a fake bin and fake endpoints:
  - the run-plan type and its column views;
  - corpus column resolution;
  - the held-out replay gate, including a pilot run and the cross-corpus case;
  - the closed-book run from end to end, init through fetch, with `model_only` on every bin call;
  - blinding refusals for score, compare-levers, both readouts, both judges and the unpark gates;
  - the 2Wiki held-out split, pinned;
  - the frozen constant, the corpora and the overlays, pinned.
- Cargo and Go tiers not run: the lane changes no Rust or Go code, only adds `config/` overlay files the engine reads under their own `LANCET_ENV`.

## Review

Two-axis code review (standards, spec) at origin/main, then a second round on the fix commit.

- **Spec blocker, fixed:** `judge-answers`, the judge stage and the unpark gates could read a run-plan run. They now refuse it.
- **Spec blocker, fixed:** the held-out replay gate checked only that a `column` key was present (a pilot skipped the token check), and a dev corpus could carry a source run from a run-plan corpus. Both are closed now.
- **Spec blocker, fixed:** the closed-book cost estimate counted zero output. It now uses deepseek's usage, or the output bound.
- **Standards note, fixed:** `_dev_corpus` renamed to `_replayable_corpus`; docstrings completed.
- **Standards note, kept:** the fail-open in `score._refuse_blinded` on an unloadable corpus is commented. A corpus that does not load fails `score` later anyway.
- **Standards notes, left:**
  - grid cells are string triples, as the existing constants use pair tuples;
  - `closed_book.py` imports private helpers from `replay.py`, which is repo practice;
  - `is_closed_book_arm` branches five times in `batch.py`.
- **Left:** the frozen `blinding_rule` text names only score, compare-levers and the readouts. The harness now refuses more, and the constant cannot change after its freeze.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
