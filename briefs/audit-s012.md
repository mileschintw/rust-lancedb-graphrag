Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "開稽核 session (Recommended)" (2026-10-31, answering the coordinator; plan relayed from the user's side session local_adc211cd-77b7-418f-9611-ef413a3bab17, where the user said "可以，就這樣做"); start: <pending: the user's typed start>
Depends on: none
Waits for (same section): none

- **Lane:** key `audit-s012`. A read-only paper audit of the S0, S1 and S2 pipelines before any paid run. **No code changes, no paid calls, no live stack, no held-out reads.** The output is a list of issues opened on GitHub (search for duplicates first; fix nothing) and `reports/audit-s012.md`. There is no PR.
- **Where to look:** `experiments/v1.1/RUN-S0-S1.md`, `EXPERIMENT-S0.md` and `EXPERIMENT-S1.md` are on branch `claude/lane-prereg-s01-73d291` (PR #70) until it merges. The S2 plan is in `experiments/v1.1/PLAN.md` (D-254 to D-260) and the spec is issue #49, with tickets #50 to #54.
- **How:** run parallel reviewers (subagents), one per stage:
  - **S0:** RUN steps 2 and 3.
  - **S1:** RUN steps 1 and 4.
  - **S2:** `replay-init` → rewrite → batch → `render` → `score` / `compare-levers`.

  Each reviewer traces every command against the code. Check for each one:
  - what each step reads and writes: config, files, schema, store, env;
  - settings that are parsed but never read (the class of #67);
  - hardcoded held-out or v1.0 assumptions (the class of #68 and #69);
  - whether every layer accepts the arm labels (`small/`, `merged/`, `@<reader>`);
  - D-237 held-out read counting;
  - D-258 cost-estimate printing.
- **Known, do not refile:**
  - #65 (two-store export), #67 (seed chunking), #68 (dev-role scoring) and #69 (S1 identity schema): lanes 65, 67 and 68 are fixing them.
  - #50 (`render`, lane 50) and #53 (batch, not built yet).
  - Note in the report where a step depends on these.
- **Order and timing:**
  - Report the **S0 section first**, as a separate status update and a message to the coordinator, within 30 to 60 minutes. The user decides tonight whether to run S0.
  - Then S1 and S2.
  - Then propose (do not build) an offline end-to-end fixture test for S1/S2. It should be xfail on #65, #67 and #68 until those merge.
- **Lane tests:** none (read-only). In the report, give each finding a file:line, the RUN step it breaks, and whether it blocks S0, S1 or S2.
- **Before and after:**
  - If the S0 section is clean, the coordinator asks the user to start a free `provider_stub` rehearsal of S0 in the main checkout (rehearsal question set, never held-out).
  - After that comes the S0/S1 run lane.
- **Closes:** none
