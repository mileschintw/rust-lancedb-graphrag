---
status: diagnosed
trigger: "CR-01: measure honours the stage spend cap when workers > 1. (UAT test 3, phase 06.3.4.1; user: 'CR-01 fix it too.')"
created: 2026-10-06T19:00:00Z
updated: 2026-10-06T19:20:00Z
goal: find_root_cause_only
---

## Current Focus

bug_class: Bohrbug (deterministic; reproduces every run with workers>1 and a binding cap)
hypothesis: CONFIRMED -- run_measurement_pass workers>1 branch (measure.py:660-683) submits all units up front and never consults stage_spend_cap; independent second route via unvalidated NaN/inf --stage-cap (cli.py:1034-1040)
test: differential repro workers=1 vs workers=4 with patched measure_one/compute_spend (done); NaN cap serial repro (done)
expecting: n/a -- diagnosed
next_action: return ROOT CAUSE FOUND to orchestrator; plan-phase --gaps owns the fix (G-06.3.4.1-3b)

## Symptoms

expected: (UAT test 3, phase 06.3.4.1) CR-01 triaged and scheduled; truth: measure honours the stage spend cap when workers > 1
actual: User reported "...CR-01 fix it too." Review 06.3.4.1-REVIEW.md CR-01: workers>1 branch submits all units, never consults stage_spend_cap
errors: None reported
reproduction: Test 3 in UAT (06.3.4.1-UAT.md); code-level: lancet-eval measure --workers 4 --sample-size 500
started: Discovered during UAT / code review of 06.3.4.1 (latent; recorded drives used --workers 1)

## Eliminated

## Evidence

- timestamp: 2026-10-06T19:05:00Z
  checked: eval/src/lancet_eval/measure.py run_measurement_pass (lines 546-743, HEAD 77d1f399; last touched e1685120)
  found: |
    Serial branch `if workers <= 1:` (635-659) calls `compute_spend(records, include_embeddings=True)` before each unit and `break`s when `spend >= stage_spend_cap` (638-644).
    Parallel branch `else:` (660-683) builds `futures = [executor.submit(measure_one, ...) for u in work_units]` (664-678) -- every unit queued at once -- then drains with `as_completed` (679-683). No reference to stage_spend_cap or compute_spend anywhere in 660-683.
    stage_spend_cap only reappears in the summary dict `spend_summary.stage_spend_cap` (721). The summary has no `stopped_by_cap` and no `workers` key (704-737); serial branch only logger.warning()s on cap hit, so a capped serial pass is also indistinguishable from a full one in measurement.json.
  implication: Line numbers in REVIEW.md CR-01 (660-683) still match exactly. Parallel path is structurally uncapped; serial path is capped but does not record that it stopped.

- timestamp: 2026-10-06T19:06:00Z
  checked: eval/src/lancet_eval/run.py drive() (236-390)
  found: |
    Reusable bounded-window pattern: `remaining_iter = iter(remaining_units)`, `in_flight: set[Future]` (320-321); prime at most `effective_workers` submits (328-346); `while in_flight: done, in_flight = wait(in_flight, FIRST_COMPLETED)` (348-352); journal each done record (353-357); top-up loop `while len(in_flight) < effective_workers and not stopped_by_cap:` checks `compute_spend(records) >= stage_spend_cap` before every further submit (360-382). Also pre-dispatch check `initial_spend >= stage_spend_cap` (293-295). Returns DriveResult(executed_count, stopped_by_cap, observed_spend).
    Known wart in the pattern (REVIEW WR-01): cap check at 361-364 runs BEFORE `next(remaining_iter)` (366), so stopped_by_cap=True is set when the final record crosses the cap even though no units remain.
  implication: The pattern to reuse exists, but should be copied with the WR-01 ordering fix (pull next unit first, then check cap) or the measure summary will mislabel complete passes as capped.

- timestamp: 2026-10-06T19:07:00Z
  checked: eval/src/lancet_eval/cli.py measure_latency (999-1078)
  found: |
    `--workers/-w` int default 1 (1049-1056) forwarded as `workers=workers` (1068). `--stage-cap` float default 5.0 (1034-1040), no finiteness/positivity validation (WR-02); `run --stage-cap` by contrast is required. `--cheap-model` declared (1027-1033) but never forwarded (WR-03). CLI prints total records and spend but nothing about a cap stop (1070-1075).
  implication: `lancet-eval measure --workers 4` reaches the uncapped branch with a silent $5.00 default cap that is never enforced; `--stage-cap nan` would also defeat even the serial branch.

- timestamp: 2026-10-06T19:08:00Z
  checked: eval/tests/ (grep stopped_by_cap|stage_spend_cap|workers|ThreadPool|run_measurement_pass)
  found: |
    test_measure.py never passes `workers` to run_measurement_pass; its only end-to-end call (test_ordinal_assigned_at_dispatch_time_and_two_armed_adjacency, 88-159) uses default workers=1 and default cap 5.0 with a mocked run_query. test_measurement_pass_evidence_post_hoc_invariants (481+) reads a historical eval/runs artifact (restart_ordinal shape) and only asserts spend <= cap after the fact (603). Tests 779-830 are inspect.getsource/allowance checks.
    test_stage_cap.py covers ONLY run.drive (signature, stopped_by_cap, submit-count bound) and only with workers=1 (lines 56, 103, 150, 163, 251). No test anywhere exercises run_measurement_pass with workers>1 or with a cap that binds.
  implication: No gate existed for this class; the defect is invisible to the 416+ test suite.

- timestamp: 2026-10-06T19:09:00Z
  checked: every recorded measure invocation (BUDGETS.md, GENANSWER-DIAG.md, 25-SUMMARY.md, plans 11/18/25/26) and eval/runs/*measure*/measurement.json
  found: All five recorded passes (2026-09-06, passA, genprobe, genconfirm, passB) ran `--workers 1`; spends 0.075-0.171 against caps 0.50-5.0; no summary carries stopped_by_cap or workers.
  implication: Latent defect; no recorded reading is contradicted. Matches VERIFICATION.md:180 "Latent. Drives of record: workers 1."

- timestamp: 2026-10-06T19:15:00Z
  checked: Zero-cost differential repro (scratchpad repro_cr01.py; output_dir in scratchpad, nothing under eval/runs/). Patched measure_one (counting stub returning MeasurementRecord), compute_spend (0.01 * len(records)), require_index_identity, load_corpus (10 questions), check_provider_allowance, read_effective_workflow_config; client=MagicMock(); warm_up_count=0; sample_size_questions=10 (20 units); stage_spend_cap=0.005.
  found: |
    workers=1: measure_one calls=1 of 20; records=1; spend=0.010 vs cap 0.005; logger "Stage spend cap $0.01 reached. Halting drive."
    workers=4: measure_one calls=20 of 20; records=20; spend=0.200 vs cap 0.005 (40x the cap)
    Both: 'stopped_by_cap' in summary = False; 'workers' in summary = False
  implication: CONFIRMED. Same inputs, only `workers` differs; the parallel branch dispatches every unit regardless of the cap. Side note: the cap-hit log line formats the cap with %.2f, so 0.005 prints as "$0.01".

- timestamp: 2026-10-06T19:17:00Z
  checked: Same repro, workers=1, stage_spend_cap=float("nan") (WR-02 route)
  found: workers=1: measure_one calls=20 of 20; spend=0.200; cap=nan
  implication: CONFIRMED independent second route to the same truth failing: `spend >= nan` is always False, so even the capped serial branch (and any ported bounded window) is uncapped when the cap is NaN/inf. CLI passes typer's float through unvalidated (cli.py:1034-1040).

- timestamp: 2026-10-06T19:18:00Z
  checked: git log -S "as_completed(futures)" and -S "stage_spend_cap" on measure.py; git show c4607150
  found: Both introduced in c4607150 (2026-09-06, feat(06.3.3-01) latency measurement spine). The original diff already had the `workers <= 1` serial cap check and the fire-all `executor.submit` list + `as_completed` drain with no cap.
  implication: Born uncapped in 06.3.3-01, not a regression. The parallel branch has never honoured the cap. (The 2026-09-06 measurement.json keys within_cap/is_lower_bound are an older summary shape, not a removed cap-aware parallel path.)

## Resolution

root_cause: |
  Primary (code): run_measurement_pass's `workers > 1` branch (eval/src/lancet_eval/measure.py:660-683) submits every work unit to the ThreadPoolExecutor in one list comprehension (664-678) and drains with as_completed (679-683); it never calls compute_spend or compares against stage_spend_cap. Only the `workers <= 1` branch (635-659) gates dispatch on `compute_spend(records) >= stage_spend_cap` (638-644). The cap is otherwise only echoed into summary.spend_summary (721), and the summary has no stopped_by_cap field for either branch (704-737), so a capped pass is indistinguishable from a full one. Born this way in c4607150 (06.3.3-01).
  Secondary, independent (config/input, WR-02): `measure --stage-cap` (cli.py:1034-1040) silently defaults to 5.0 and accepts NaN/inf/non-positive values; `spend >= nan` is always False, so a NaN cap defeats the serial branch today and would defeat a ported bounded window too.
  AND-gate: no. workers>1 alone is sufficient (repro: 20/20 units at 40x cap with a finite cap). The NaN path is a separate sufficient route to the same truth failing.
reasoning_checkpoint:
  hypothesis: "measure ignores the stage cap when workers > 1 because the parallel branch at measure.py:664-678 enqueues all work units before any spend is observed and has no compute_spend check, unlike the serial branch at 638-644"
  confirming_evidence:
    - "Code read: no reference to stage_spend_cap/compute_spend in measure.py:660-683"
    - "Differential repro, identical inputs: workers=1 -> 1/20 calls, halts; workers=4 -> 20/20 calls, spend 0.200 vs cap 0.005"
    - "git: parallel branch uncapped since its introduction in c4607150"
  falsification_test: "If workers=4 had dispatched <= workers(+1) units under a cap that binds after record 1, the hypothesis would be false"
  fix_rationale: "Replacing fire-all-then-drain with run.drive's prime-then-top-up window (cap checked before each submit) bounds dispatch at the source of the defect rather than reporting overspend after the fact"
  blind_spots: "Did not exercise real measure_one/compute_spend pricing or a live engine (paid; forbidden). Bounded-window still overshoots by up to workers-1 in-flight units after the crossing record -- bounded, not a hard ceiling."
  candidate_causes:
    - "code: fire-all-then-drain parallel branch with no cap check (measure.py:660-683) -- CONFIRMED"
    - "config/input: unvalidated, silently defaulted --stage-cap (cli.py:1034-1040) -- CONFIRMED as independent route"
    - "environment: none -- no env-dependent path in the dispatch loop"
  and_gate: "no -- each cause is independently sufficient"
fix: ""
verification: ""
files_changed: []
