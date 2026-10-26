# Project settings

What relay needs to know about this project. The coordinator and every worker read this file.

- **Repo:** mileschintw/rust-lancedb-graphrag, default branch `main`.
- **Language:** talk to the user, and write reports, in Traditional Chinese (繁體中文). Repo files, issues, PR bodies, briefs and the plan are written in English.
- **Checks before done:** `cargo test --manifest-path engine/Cargo.toml --locked && sh scripts/engine-test-targets.sh`; `(cd gateway && go test -count=1 ./...) && sh scripts/gateway-test-targets.sh` (`-count=1` is required: the test cache hides config.toml changes); `uv run --project eval pytest` for the Python eval harness.
- **Test bar:** the checks above pass and each new behaviour has a test. Workers build each ticket test-first by calling the `tdd` skill (one red-green slice at a time). No CI exists, so these run locally.
- **Off limits for workers:** `.planning/` and `.discussion/` (read-only v1.0 build record); `eval/runs/` (v1.0 runs of record, read-only); `eval/corpora/multihop_rag/{heldout_split.json,questions.heldout.jsonl,diag_selection.json}` (pre-registration and split hash are bound to them); `data/lancedb-eval` (gitignored live store, not cheaply rebuildable; v1.1 S1 builds a second store, never modify the original); existing decisions D-234–D-246 in `experiments/v1.1/PLAN.md` (may add, never edit); `config/` defaults unless the brief names them. Work that touches the live stack or eval drive runs only in the main checkout, one at a time, because worktrees lack the live store. Workers write only their own `status/`, `reports/` and `pr-bodies/` files in the records folder.
- **Ask the user first, with the exact scope:** creating accounts or VMs, installing into the user's real profile, large downloads, signing in to outside sites, spending money; paid LLM/rerank/embedding calls and eval runs (check each phase against the D-246 spend cap); any held-out read (D-237 allows two for all of v1.1: S0 and Confirm); rebuilding or re-embedding any store; push, merge, opening a PR.
- **Unattended, never:** none beyond relay's default list.
- **Release:** none.
- **Deny list:** none. Records on `coord` must never contain API keys or environment variable values (the OpenRouter key); batch IDs and cost figures are fine.
