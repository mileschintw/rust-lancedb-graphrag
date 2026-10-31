Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "今晚開 S0 run lane (Recommended)" (2026-10-31, answering the coordinator after the audit's S0 section); start: <pending: the user's typed start>
Depends on: none
Waits for (same section): none

- **Lane:** key `run-s01`. Run S0 tonight in the **main checkout** (`D:\Repos\lancet`, no worktree), following `experiments/v1.1/RUN-S0-S1.md` step by step. That means step 0, then step 2 (LlamaIndex live checks), then step 3 (S0). S1 (steps 1 and 4) is not in scope tonight: the coordinator sends `GO S1` once #68 has merged and the user says so. There is no PR, unless the guide says to commit run records; if it does, ask the coordinator.
- **Ask the user before every paid call, store build, install and held-out read**, in this session, in Traditional Chinese, with the guide's cost estimate and ceiling. S0 is held-out read 1 of 2 (D-237): steps 3.2, 3.4 and 3.5 are that one read. D-258: no mid-run caps; print the estimate first.
- **Audit corrections (audit-s012, `reports/audit-s012.md` › S0):**
  - #74: step 0 must also build the release bins up front: `cargo build --manifest-path engine/Cargo.toml --locked --release --bin inspect_lancedb --bin generate_from_context`. `cargo run --release` has a 1800 s timeout, and a cold release build takes far longer. sccache is on; use `CARGO_BUILD_JOBS` from `docs/testing.md` (lane 56's rule, once PR #71 merges; until then 4, since no other lane builds release now). Never set `CARGO_TARGET_DIR` or `CARGO_PROFILE_*`.
  - #75: the rerank tripwire halt exits 0, and run-external error records are final. After steps 3.2 and 3.5, count the records per arm. Each arm must have 351; report any shortfall to the user before you go on.
  - #76: the free stub rehearsal cannot run. Before step 3's full run, do a **paid 3-question rehearsal** (a few cents). Ask the user first, and use non-held-out questions only (rehearsal or dev set; never held-out).
  - #77 (no estimate printed) and #78 (held-out reads not counted by the tool) block nothing. Print the estimate yourself, and log the held-out read in the report.
- **Checkout rule:** while this lane runs, the coordinator does not fast-forward the main checkout. Do not pull, switch branches or edit tracked files. `scratch_new.txt` in the checkout root is not yours; leave it alone. The live stack, `data/lancedb-eval` and the stores: modify none, except where the guide says to.
- **Unattended:** if a command exits non-zero, or a count check fails, stop and tell the user and the coordinator. Resuming needs the user's yes.
- **Report:** `reports/run-s01.md`. Include each step's command, exit code, record counts, actual cost, run directory paths, the held-out read log, and S0's decision readout from EXPERIMENT-S0.md.
- **Closes:** none
