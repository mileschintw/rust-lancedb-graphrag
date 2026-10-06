# Unpark Gates (drive2)

## Gates

| Gate | Status | n | Reason |
|---|---|---|---|
| SC-1 | PASS | 200 | header partial matches completeness_comparison() and report.json state is consistent |
| SC-4 | PASS | 89 | presence rate 0.6629 >= floor 0.20 and Wilson lower bound 0.5598 > 0.098 over pairs(G) |
| SC-5 | PASS | 65 | composition change 0.5385 >= floor 0.10 (35/65 pairs(V)) |

## Re-reported as disclosures (not gates on drive 2)

| Reading | Status | n | Reason |
|---|---|---|---|
| SC-2 | PASS | 200 | error mode and RetrieveHybrid flatness both pass |
| D-69 companion | PASS | 199 | citation_marker_mismatch=0, total and null rates within committed bounds |
| SC-3 | PASS | 90 | usable rate 0.5778 >= floor 0.5120 |

## Graph-off invariance vs the baseline run (disclosure, no threshold)

- questions in both journals: 100 (comparable: 99)
- answer_usable agrees: 84; differs: 6 ['mhr-17e563aaa33e', 'mhr-37132816abed', 'mhr-608cc5fc4d2f', 'mhr-7e7714eeb997', 'mhr-9de3cfe1bb58', 'mhr-e877f9f62d20']
- final retrieved set equal: 95; differs: 4 ['mhr-2180fee6aa67', 'mhr-3426cbec820e', 'mhr-414d8e1b6f1f', 'mhr-ad4eee299dc7']
- same set in the same order: 89
- only in the baseline: 0; only in this run: 0
- duplicate records collapsed: {'baseline': 0, 'drive2': 0}
- any difference: True
