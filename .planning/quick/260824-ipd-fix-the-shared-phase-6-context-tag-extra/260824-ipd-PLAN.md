---
phase: 260824-ipd-fix-the-shared-phase-6-context-tag-extra
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/phases/06-observability-evaluation-polish/06-CONTEXT.md
autonomous: true
requirements: []
estimate:
  tokens: 18000
  raw_tokens: 18000
  tasks: 2
  confidence: low
must_haves:
  truths:
    - Shared Phase 6 CONTEXT has exactly one decisions opening-tag hit: the real tag near line 52; D-77 Known consequence prose has zero such hits
    - Phases 6.1–6.4 still have no local *-CONTEXT.md (D-77: Continue without context)
    - Dry-running plan-phase §13a against the 6.2 phase dir with no local context_path skips the coverage gate (not a fake 9/9 on D-78–86, not an ~86-wide parent-file run)
    - Quick-task SUMMARY names the trackable 6.2 subset D-27–43 and states that the next `/gsd-plan-phase 6.2 --reviews` must Continue without context and assert those IDs by reading the plans
  artifacts:
    - .planning/phases/06-observability-evaluation-polish/06-CONTEXT.md
    - .planning/quick/260824-ipd-fix-the-shared-phase-6-context-tag-extra/260824-ipd-SUMMARY.md
  key_links:
    - D-77 Known consequence prose → no second decisions opening-tag substring (fixes decisions.cjs extractTaggedBlocks stop-at-next-open truncation)
    - 6.2 phase dir local CONTEXT absence → §13a gate skip path (CONTEXT_PATH empty)
    - Manual coverage for 6.2 → D-27 through D-43 in parent 06-CONTEXT.md section D (OBS-01)
---

<objective>
Remove the shared Phase 6 CONTEXT parser landmine: one prose rewrite in D-77 so `decisions.cjs` no longer truncates the real decisions block at a second opening-tag substring. Do not add any per-phase CONTEXT.md under 6.1–6.4.

Purpose: Unblock honest `/gsd-plan-phase 6.2 --reviews` coverage behavior (gate skip when context_path is null; manual assert of D-27–43). A fake 9/9 on D-78–86 is failure.
Output: Prose-fixed `06-CONTEXT.md`; verification A–D passed; SUMMARY records the 6.2 subset and Continue-without-context instruction.
</objective>

<execution_context>
@D:/Repos/lancet/.cursor/gsd-core/workflows/execute-plan.md
@D:/Repos/lancet/.cursor/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md
@.cursor/gsd-core/workflows/plan-phase.md
@.cursor/gsd-core/bin/lib/decisions.cjs
</context>

<scope_lock>
- Touch ONLY `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` for the fix (plus this quick task's SUMMARY on completion).
- Do NOT create, copy, or excerpt any `*-CONTEXT.md` into 6.1 / 6.2 / 6.3 / 6.4. Do NOT `cp` 06-CONTEXT.md.
- Do NOT patch vendor `decisions.cjs` under `.claude` / `.cursor` / `.codex` / `.agents`. If a parser change were truly required, stop and report; prefer this one-line prose fix.
- Do NOT edit `06.2-*-PLAN.md`, 06.1 plans, `engine/`, `gateway/`, or ROADMAP. Do NOT reopen D-27–43. Do NOT run discuss-phase. Do NOT insert a ROADMAP phase.
- Do NOT change any D-* ID, decision body, rating, or heading — only the D-77 Known consequence prose mention of the decisions opening tag.
</scope_lock>

<!-- planner-discipline-allow: <decisions> -->

<tasks>

<task type="tracer">
  <name>Task 1: Rewrite D-77 Known consequence prose landmine</name>
  <files>.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md</files>
  <read_first>
    - `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` around the D-77 bullet (Known consequence, accepted) — landmine is the quoted plan-phase gate sentence that embeds a second decisions opening-tag substring mid-prose (currently near line 438). Real opening tag remains near line 52.
    - Confirm section D still lists D-27 through D-43 unchanged (OBS-01 / Phase 6.2).
  </read_first>
  <action>
    In `06-CONTEXT.md`, inside the D-77 **Known consequence, accepted** paragraph only, rewrite the quoted plan-phase gate wording so the file contains no second decisions opening-tag substring outside the real opening tag at the top of the Implementation Decisions block.

    Use wording such as "the decisions block" or "CONTEXT decisions section" (per locked diagnosis). Keep the same meaning: every trackable decision in that block must be referenced by at least one plan; the gate still skips when there is no local CONTEXT.md.

    Do not change any D-* ID, decision body text outside that one mention, rating, heading, or Canonical refs. Do not add or remove decisions. Do not create any new CONTEXT file.
  </action>
  <verify>
    <automated>rg -n '<decisions>' .planning/phases/06-observability-evaluation-polish/06-CONTEXT.md; $count = (rg -c '<decisions>' .planning/phases/06-observability-evaluation-polish/06-CONTEXT.md | ForEach-Object { if ($_ -match ':(\d+)$') { [int]$Matches[1] } else { [int]$_ } } | Measure-Object -Sum).Sum; if ($count -ne 1) { throw "expected exactly 1 hit, got $count" }; if (rg -n 'D-77' -A 20 .planning/phases/06-observability-evaluation-polish/06-CONTEXT.md | Select-String -SimpleMatch '<decisions>') { throw 'D-77 prose still contains opening-tag substring' }</automated>
  </verify>
  <done>
    Exactly one opening-tag hit in the file (real tag near line 52). Zero hits inside D-77 Known consequence prose. All D-* IDs and bodies otherwise unchanged.
  </done>
</task>

<task type="auto">
  <name>Task 2: Run verifies A–D and record 6.2 coverage instruction</name>
  <files>.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md, .planning/quick/260824-ipd-fix-the-shared-phase-6-context-tag-extra/260824-ipd-SUMMARY.md</files>
  <action>
    After Task 1, run verification suite A–D (same facts; PowerShell-safe equivalents OK):

    A. Re-run Task 1's rg count on shared `06-CONTEXT.md` — exactly one opening-tag hit; none in D-77 prose.

    B. Confirm phase dirs `06.1-*`, `06.2-*`, `06.3-*`, and `06.4-*` under `.planning/phases/` still have no local `*-CONTEXT.md`.

    C. Dry-run plan-phase §13a against the 6.2 phase directory only: resolve `CONTEXT_PATH` as the first `*-CONTEXT.md` inside `.planning/phases/06.2-opentelemetry-traces-metrics-and-logs-across-go-and-rust-wit` (expect null/empty). Do not pass the parent shared CONTEXT. Expected: coverage gate skipped / `check.decision-coverage-plan` not invoked. A 9/9 on D-78–86 is failure. An ~86-wide result against the parent file is also failure — do not "fix" that by adding plan references.

    D. Write `.planning/quick/260824-ipd-fix-the-shared-phase-6-context-tag-extra/260824-ipd-SUMMARY.md` naming the trackable 6.2 subset **D-27–43** and stating that the next `/gsd-plan-phase 6.2 --reviews` must answer **Continue without context** and assert those IDs by reading the plans, not by trusting a coverage percentage.

    Still forbidden: creating per-phase CONTEXT files; editing `decisions.cjs`, plans, engine/, gateway/, ROADMAP.
  </action>
  <verify>
    <automated>powershell -NoProfile -Command "& { $ErrorActionPreference='Stop'; $p='.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md'; $n=(rg -n '<decisions>' $p | Measure-Object).Count; if ($n -ne 1) { throw \"A FAIL: expected 1 hit, got $n\" }; Get-ChildItem .planning/phases -Directory | Where-Object { $_.Name -match '^06\.[1-4]-' } | ForEach-Object { $c=Get-ChildItem $_.FullName -Filter '*-CONTEXT.md' -EA SilentlyContinue; if ($c) { throw \"B FAIL: $($_.Name) has CONTEXT\" } }; $phaseDir=(Get-ChildItem .planning/phases -Directory | Where-Object { $_.Name -like '06.2-*' } | Select-Object -First 1).FullName; $ctx=Get-ChildItem $phaseDir -Filter '*-CONTEXT.md' -EA SilentlyContinue | Select-Object -First 1; if ($null -ne $ctx) { throw 'C FAIL: context_path not null' }; Write-Output 'C OK: GATE SKIPPED (no local CONTEXT; check.decision-coverage-plan not invoked)'; $sum='.planning/quick/260824-ipd-fix-the-shared-phase-6-context-tag-extra/260824-ipd-SUMMARY.md'; if (-not (Test-Path $sum)) { throw 'D FAIL: SUMMARY missing' }; $s=Get-Content $sum -Raw; if ($s -notmatch 'D-27') { throw 'D FAIL: must name D-27–43' }; if ($s -notmatch 'D-43') { throw 'D FAIL: must name D-27–43' }; if ($s -notmatch 'Continue without context') { throw 'D FAIL: must state Continue without context' }; Write-Output 'A-D OK' }"</automated>
  </verify>
  <done>
    A–D all pass. No new CONTEXT.md under 6.1–6.4. §13a dry-run skipped the gate. SUMMARY names D-27–43 and the Continue-without-context + manual plan-assert instruction for the next 6.2 `--reviews` run.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Planner tooling → CONTEXT.md | Decision-coverage gate parses XML-like tags in markdown; prose must not inject a second opener |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-260824-ipd-01 | Tampering | 06-CONTEXT.md D-77 prose | medium | mitigate | Remove second decisions opening-tag substring so extractTaggedBlocks cannot truncate the real block |
| T-260824-ipd-02 | Information disclosure | N/A (docs-only) | low | accept | No secrets; planning metadata only |
| T-260824-ipd-SC | Tampering | package installs | low | accept | No npm/pip/cargo installs in this plan |
</threat_model>

<verification>
- Exactly one decisions opening-tag hit in shared `06-CONTEXT.md`
- Zero local CONTEXT files under 6.1–6.4
- §13a dry-run with null context_path skips the gate
- SUMMARY documents D-27–43 + Continue without context for `/gsd-plan-phase 6.2 --reviews`
</verification>

<success_criteria>
Prose landmine gone; no new per-phase CONTEXT.md; 6.2 coverage gate no longer reports a fake 9/9; next 6.2 reviews planning is instructed to assert D-27–43 manually.
</success_criteria>

<output>
Create `.planning/quick/260824-ipd-fix-the-shared-phase-6-context-tag-extra/260824-ipd-SUMMARY.md` when done
</output>
