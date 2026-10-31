Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "Start the S1 build" (2026-10-31 14:59 -0700), within the S1→S2 path approved on "核准路線與兩個檢查任務" (2026-10-31)
Depends on: none
Waits for (same section): none

- **Lane:** key `run-s1store`. Build the S1 store in the **main checkout** (`D:\Repos\lancet`, not your worktree: run every command there), following `experiments/v1.1/RUN-S0-S1.md` step 0, then step 1 (1.1 to 1.5). Steps 2 to 4 are out of scope: S1's drive (step 4) waits for #105 and #106 and a separate GO. No PR unless the guide says to commit run records; if it does, ask the coordinator.
- **Ask the user before every paid call, store build and install**, in this session, in Traditional Chinese, with the estimate. Audit-s1a re-checked step 1: about $1.9-2.9, ceiling about $10.8 **excluding extraction retries** (up to 3 per chunk, 5 per failed document); say so. No held-out reads in this lane.
- **Before step 0:**
  - Pull: `git -C D:/Repos/lancet merge --ff-only origin/main` after a fetch (main is at d943d558 or later). The coordinator does not move the main checkout while you run.
  - `scratch_new.txt` (untracked ruff output from 2026-10-29) breaks step 0's clean-tree check. Ask the user whether to delete it; do not delete it unasked.
- **Audit corrections (`reports/audit-s1a.md` in the records folder):**
  - A1: redo step 0's builds after pulling, debug and release (`--bin inspect_lancedb --bin generate_from_context`); step 1.2 runs `./engine/target/debug/engine` directly, and the current binary predates main. `CARGO_BUILD_JOBS=2`; sccache is on; never set `CARGO_TARGET_DIR` or `CARGO_PROFILE_*`.
  - A2: after 1.2 and before 1.3 (seed), check the S1 engine's startup log: the `BM25 snapshot built` line must show `document_count=0` and `graph_entities=0`. Anything else means the stack points at another store: stop, and do not seed.
  - The deferred Atlas step (`docker exec lancet-postgres psql -U postgres -d lancet -c "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"`, then `(cd gateway && atlas schema apply --env eval-s1 --auto-approve)`) is step 1.1.
- **Never touch** `data/lancedb-eval` or the `lancet_eval` schema (v1.0 store). Only one stack at a time; stop any v1.0 stack first.
- **Machine:** the coordinator holds other lanes off engine builds and LLM traffic while you run (S0's rerank timeouts came from load). Tell the coordinator when the build starts and when it ends.
- **Stop rule:** any non-zero exit or failed check: stop, tell the user and the coordinator. Resuming needs the user's yes.
- **Report:** `reports/run-s1store.md`: each step's command, exit code, counts (346 documents completed, one chunking), `document_map.eval-s1.json`, actual cost, and the step 1.5 preflight result.
- **Closes:** none
