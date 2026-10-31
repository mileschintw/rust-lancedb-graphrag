Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "核准路線與兩個檢查任務" (2026-10-31 14:21 -0700), approving the S1→S2 path in plan.md › Waiting for the user's decision (first relayed from side session local_b18259ae-8393-499e-aa94-ced26b2c14e6: "可以，就照這個規劃通知coordinator")
Depends on: none
Waits for (same section): none

- **Lane:** key `audit-s1a`. Audit part 1: a read-only paper audit of `experiments/v1.1/RUN-S0-S1.md` **step 1 (the S1 store build)** against current origin/main, before the paid build. **No code changes, no paid calls, no live stack, no store writes, no held-out reads.** Output: `reports/audit-s1a.md` and a GitHub issue for each blocker (search for duplicates first; fix nothing). No PR.
- **Check:**
  - every command and flag in step 1 exists on main and does what the guide says, including the deferred Atlas `lancet_eval_s1` schema step (plan.md › Waiting for the user to be present);
  - the pre-registration constants step 1 relies on match `experiments/v1.1/EXPERIMENT-S1.md`;
  - the cost estimate for the build: tokens, prices from `measure.py`, and a ceiling. Earlier estimate: ~$2-3, ceiling ~$11;
  - that the build never touches `data/lancedb-eval` (v1.0 store) and writes only the S1 store;
  - #74 (release bins up front) and #75 (per-arm counts) are on main as of PR #96: check the guide's step 1 uses them where they apply.
- **Format:** as `reports/audit-s012.md`: each finding with file:line, the step it breaks, and blocks S1 / does not.
- **Timing:** report within about 45 minutes. The coordinator asks the owner to start the paid build once this passes.
- **Before and after:** audit part 2 (S1 step 4 and the S2 run path) starts after this passes.
- **Closes:** none
