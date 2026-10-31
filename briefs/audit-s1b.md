Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "Start audit part 2" (2026-10-31 14:44 -0700), within the S1→S2 path approved on "核准路線與兩個檢查任務" (2026-10-31)
Depends on: none
Waits for (same section): none

- **Lane:** key `audit-s1b`. Audit part 2: a read-only paper audit of **S1 step 4** (`experiments/v1.1/RUN-S0-S1.md`) and the **S2 run path**, against current origin/main, before the paid S1 and S2 runs. **No code changes, no paid calls, no live stack, no store writes, no held-out reads.** Output: `reports/audit-s1b.md` and a GitHub issue for each blocker (search for duplicates first; fix nothing). No PR.
- **S1 step 4:** each command and flag exists and does what the guide says. Check the arm labels (`small/`, `merged/`) through drive, score and `compare-levers`; the #75 per-arm count checks; that the D-252/D-263/D-264 decision rules match what `compare-levers` computes; the cost estimate (guide: about $0.5, dev only).
- **S2 path:** `replay-init` → rewrite → `batch` (submit/poll/fetch) → `render` → `score`/`compare-levers`, per `experiments/v1.1/PLAN.md` D-254 to D-265 and `decisions-2026-10-30.md` in the records folder. Check the reader arms (`@<reader>`) through every layer, the D-257/D-265 replay clauses, and the pilot (`batch submit --limit N`: what it checks: `is_byok`, `reasoning_tokens`, strict schema, Sonnet `between_tools`).
- **S1→S2 handoff:** which S1 arm S2 replays, where S2 reads that choice from (file, command or hand step), and whether anything refuses a wrong or missing choice. A hand step with no check is a finding.
- **Is there a run guide for S2?** If none covers the S2 commands end to end, say so as a finding with an outline of the missing steps. Do not write the guide.
- **Format:** as `reports/audit-s012.md` and `reports/audit-s1a.md`: each finding with file:line, the step it breaks, and blocks S1 / S2 / neither. Use subagents in parallel (S1 step 4; S2 path; handoff).
- **Known, do not refile:** #77/#78 (lane 77, cost estimates and export gates), #100 (README), and audit-s1a's A1-A6 (`reports/audit-s1a.md`).
- **Timing:** report S1 step 4 first, as a status update and a message to the coordinator; S1 can run once the store is built. Then S2.
- **Closes:** none
