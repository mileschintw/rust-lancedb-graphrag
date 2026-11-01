Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "audit＋免費預演 (Recommended)" (2026-10-31), answering: re-audit the S2 run path before the pilot, as for S0 and S1
Depends on: lane 123 (#123, #127) merged to main. You are parked until GO.
Waits for (same section): none

- **Lane:** key `audit-s2`. It is read-only for the repo: no commits, no PR, no issue edits. Your products are `reports/audit-s2.md` and the status file. Use the format of `reports/audit-s1b.md` and `reports/audit-s012.md` (blockers vs logged findings, each with file:line).
- **Part 1, paper audit:** on main after GO, walk `experiments/v1.1/RUN-S2.md` step by step, from step 0 to step 8, including the new Step 7.1 answer judges. Check:
  - every command, subcommand and flag exists, with the arguments the guide gives;
  - the EXPERIMENT-S2.md draft constant and its readers table match the code types in `thresholds.py`, and match D-274 (K=5, permutation test, question-level bootstrap), D-275 (cheapest unless significantly better after Holm) and D-276 (normalisation, dual judge);
  - the D-73 trap: no `PREREGISTRATION_S2` literal in `thresholds.py` before step 4;
  - the S1→S2 handoff: `replay_source_arm` = `small/hybrid+rerank+metadata`, from S1 run `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`;
  - Claude requests pin `provider.only: ["anthropic"]` and fail closed unless `is_byok` is true. The owner set BYOK to "Never use OpenRouter's Anthropic capacity for any model", but other hosts can still bill OpenRouter credit;
  - deepseek replicates pin D-271 (wafer/us, `allow_fallbacks: false`, max_price);
  - the cost estimates per step and in total, separately for Claude credit (BYOK) and OpenRouter credit. The owner has about $200 of Claude credit and about $7.6 of OpenRouter credit, and the OpenRouter side must fit with a margin.
- **Part 2, free rehearsal:** run the K=5 path end to end with no network spend: pack, batch submit and fetch for every reader including the deepseek replicates, replay records, score, `reader_comparison`/`lever_comparison` with the new test, and `judge-answers`. Use the repo's fakes, for example `provider_stub.py` or the test transports in the batch and judge tests, against a scratch copy of the run dir outside `eval/runs/`. If no free route exists for some step, say which step and what is missing, and do not pay to get around it. Do not start the engine stack, and do not write to any store.
- **Off limits:** held-out files; `eval/runs/` writes; paid calls; the `PREREGISTRATION_S2` literal.
- **Each blocker:** name it in the report with a proposed fix and its file. The coordinator opens the issues.
- **Closes:** none
