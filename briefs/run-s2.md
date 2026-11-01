Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: pending, the user's next typed yes (2026-10-31). The user asked for a fresh, clean session to run S2: "要不要直接換新的乾淨session？"
Depends on: none (#123, #124, #125, #127, #133 and #134 are merged; main is f3f036ee)
Waits for (same section): none

- **Lane:** key `run-s2`. Run `experiments/v1.1/RUN-S2.md` in the main checkout `D:/Repos/lancet` on `main`, never in a worktree, because the live store and bins are there. Steps 0 and 1 are free. Then step 2, the paid pilot, and step 3 if needed. **Stop after step 3** and write `blocked` with the pilot readout (step 3's table: `is_byok`, provider, #108 schema, Sonnet `reasoning_tokens`/`between_tools`, deepseek provider = Wafer, and the cost lines as printed). Steps 4 to 8 wait for the coordinator's GO with the owner's yes.
- **Pilot ask:** the owner's yes for steps 2.1 to 2.5 is pending at the coordinator: about $0.65, ceiling about $1.50. Do not start step 2 until the coordinator's message quotes that yes.
- **Context:**
  - S1's run of record is `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`, and `replay_source_arm` = `small/hybrid+rerank+metadata`.
  - D-274 to D-278 are in `experiments/v1.1/PLAN.md`.
  - The free audit and rehearsal is `D:/Repos/lancet-coord/reports/audit-s2.md`; it serves as a map.
  - The engine bins from 2026-10-31 17:03 are current: no engine commit since `a72ef8d5`. Step 0 still rebuilds if the guide says so.
- **Machine:** keep it quiet. No other lane builds or runs while you do. Prefix commands with `PYTHONUTF8=1` (cp950 console).
- **Rules:**
  - Commit the run dir and the step 4 freeze on your own lane branch, as RUN-S2 says, never on `main`.
  - Never touch held-out files, `data/lancedb-eval`, or other runs under `eval/runs/`.
  - Never put API keys or env values in any record.
- **Closes:** none
