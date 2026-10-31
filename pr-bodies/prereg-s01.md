## Summary

S0 and S1 pre-registrations, committed before their paid runs (D-240, D-253), plus a step-by-step run guide.

```diff
 eval/
 ├── corpora/
+│   └── multihop_rag_s0_heldout.toml    # S0 corpus: held-out, 2 arms, token PREREGISTRATION_S0
 ├── src/lancet_eval/thresholds.py
+│   ├── PREREGISTRATION_S0               # Lancet default vs llamaindex, Holm m = 1
+│   ├── PREREGISTRATION_S1               # small-off reference: chunking + small-store graph
+│   └── PREREGISTRATION_S1_MERGED_GRAPH  # merged-off reference: merged-store graph
 └── tests/
+    └── test_stage_preregistrations.py
 experiments/v1.1/
+├── EXPERIMENT-S0.md                     # arms, metrics, decision rule, smallest detectable effect
+├── EXPERIMENT-S1.md
+├── RUN-S0-S1.md                         # S1 store build -> LlamaIndex checks -> S0 -> S1, cost per step
 └── PLAN.md                              # + D-261..D-264
 .gitignore                               # + the S0 and S1 run directories
```

The lever comparison pairs every family arm with the constant's reference arm. That is why S1 needs two constants.

```text
PREREGISTRATION_S1 (ref small/hybrid+rerank+metadata)
  merged/hybrid+rerank+metadata          -> chunking: adopt merged iff delta > 0 and guard passes
  small/hybrid+graph+rerank+metadata     -> graph if small kept: delta >= +0.05 and guard passes
PREREGISTRATION_S1_MERGED_GRAPH (ref merged/hybrid+rerank+metadata)
  merged/hybrid+graph+rerank+metadata    -> graph if merged adopted: delta >= +0.05 and guard passes
```

Every number reuses `PREREGISTRATION_06_3_6`. `PREREGISTRATION_06_3_6` itself is byte-identical. The new constants sit above it, because a test expects it to be the last assignment in the file.

### Owner decisions (2026-10-30, this lane's session)

| D-ID | Question | Owner's answer |
|---|---|---|
| D-261 | S0 null guard: D-252 says "on both arms", but the code reads one direction | "雙向讀，勝方須過 (Recommended)": read both directions; the leader's direction must pass |
| D-262 | S0 thresholds | "全部沿用 v1.0 (Recommended)": alpha 0.05, margin 0.10, pair fraction 0.80, floor 0.80, bootstrap 10,000 / seed 42, tripwire 0.20 / 50 / 5 |
| D-263 | S1 graph rule when small is kept | "在選中的 store 上套用 (Recommended)" |
| D-264 | S1 null guard with 10 dev nulls | "沿用 0.10/0.80，兩個選擇都否決 (Recommended)" |

### Blockers found for the run (filed, not fixed here)

- Refs #67: `seed --store eval-s1` sends no chunking, so the "merged" store would repeat the v1.0 chunker. It blocks RUN step 1.
- Refs #65: a two-store S1 journal's context export reads one schema. RUN step 4.5 carries a stopgap.
- Refs #68: `score` and `compare-levers` read only held-out IDs, so no dev-role run (S1, S2) can be scored. It blocks RUN steps 4.6 to 4.8.

## Evidence

- **Before:** `preregistration.resolve("PREREGISTRATION_S1")` raises `PreregistrationError` (not defined), and the S1 corpus's gates fail closed.
- **After:** `test_stage_preregistrations.py` passes 13/13. Each constant resolves; each corpus drives exactly its constant's arms; S0 runs on held-out (351) and S1 on the dev pool (100); a copy naming an undeclared arm, and S0 without its LlamaIndex pipeline, both fail closed; both S1 readings run through `build_lever_comparison` on an S1-shaped journal (merged-off +0.5 against small-off; merged-on +0.3 against merged-off, guard PASS).
- The eval fast tier and ruff results are in the lane report. Ruff finds no error on a new line. `thresholds.py` keeps main's 10 E501 errors, all on the existing 06.3.6 lines.
- The D-73 check passes for all three tokens at this head (`gitcheck.preregistration_problems(..., unchanged_since_introduction=True)` returns `[]`).

## Merge Danger

**Door:** one-way, deliberately. The constants are pre-registrations. Once a paid run's journal is newer than this commit, D-73 refuses any change to them.

**Blast Radius:** eval-only. Adding three constants changes no existing gate. `thresholds.py` now imports `ExternalPipeline` at runtime (`arms.py` does not import `thresholds`, so there is no cycle).

## Review

Round 1, with three reviewers: standards, spec, and writing-for-agents on RUN-S0-S1.md.

- Blocker, spec: dev-role runs cannot be scored. It is outside this lane's files, so it was filed as #68 and added to the guide's Step 0 and step 4.6.
- Blocker, guide: shell variables don't survive between an agent's tool calls. Fixed with literal `<S0_RUN>`/`<S1_RUN>` paths.
- Blocker, guide: "each in its own terminal". Fixed with background processes, waiting for the listen logs, and never running both stacks at once.
- Blocker, guide: approval granularity. Fixed: ask once per step, in Traditional Chinese.
- Blocker, guide: unbounded paid resumes. Fixed: any non-zero exit stops the run except the one named in 4.4, and a paid resume needs a new yes.
- Note: `PREREGISTRATION_S1_MERGED_GRAPH` is not the corpus token, so `compare-levers` does not D-73-check it. Fixed: the 4.7 recipe runs `gitcheck.preregistration_problems` on it first.
- Note: D-264's "2 or more" holds only at 10 null pairs. The wording is fixed in PLAN.md and EXPERIMENT-S1.md.
- Note: the rerank tripwire does not act on a dev corpus; EXPERIMENT-S1 says so now. S0's preflight sends no canary; the guide says so now. The cost-ceiling wording is fixed (the evidence cap, plus retries).
- Note, left: eval/README.md's list of canonical-arm corpora does not name the S0/S1 corpora.
- Note, left: the new constants repeat the shared numeric fields. D-73 needs every number inside each assignment.
- Note, left: the S1 lever-comparison test uses a held-out-role fixture, so it does not exercise dev scoping (that is #68's job).

Round 2 reviewed the fix commit against round 1's blockers. All seven are fixed, and the round found no new blocker.

- Note: S0's preflight also sends one corpus-generation probe. Fixed: step 3.1 now says "under a cent".
- Note, left: a journal with no header makes the 4.7 recipe stop with a TypeError instead of a D-73 message. It still stops.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
