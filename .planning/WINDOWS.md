---
schema_version: 1
open_count: 4
waived_count: 0
fixed_count: 0
total_count: 4
last_updated: 2026-09-24T22:15:20.670Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 02 | stub | engine/src/main.rs | 329 | Pre-existing query_rag placeholder answer and empty citations; deferred to Phase 03. | open |  | 2026-07-26T04:04:35.521Z |  |
| 2 | 02 | stub | engine/src/main.rs | 340 | Pre-existing query_graph scaffolding payload; deferred to Phase 04. | open |  | 2026-07-26T04:04:36.220Z |  |
| 3 | 06.3.4.1 | stub | eval/src/lancet_eval/diagnostic.py |  | DiagnosticRow columns (c) c_gold_in_vector_top4, (d) d_graph_seed_hit/seed_count/path_found stay None in plan 01 by design; resolved by plans -09/-13/-17 (Recall@4 probe, graph seeding) per plan 01's own Artifacts section. | open |  | 2026-09-24T01:19:58.210Z |  |
| 4 | 06.3.4.1 | lint-warning | eval/src eval/tests |  | Pre-existing ruff debt (~250-300 errors), out of scope for 06.3.4.1-05; see phase deferred-items.md | open |  | 2026-09-24T22:15:20.670Z |  |

````json
[
  {
    "id": 1,
    "kind": "stub",
    "phase": "02",
    "file": "engine/src/main.rs",
    "line": 329,
    "description": "Pre-existing query_rag placeholder answer and empty citations; deferred to Phase 03.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-07-26T04:04:35.521Z",
    "resolved_at": null
  },
  {
    "id": 2,
    "kind": "stub",
    "phase": "02",
    "file": "engine/src/main.rs",
    "line": 340,
    "description": "Pre-existing query_graph scaffolding payload; deferred to Phase 04.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-07-26T04:04:36.220Z",
    "resolved_at": null
  },
  {
    "id": 3,
    "kind": "stub",
    "phase": "06.3.4.1",
    "file": "eval/src/lancet_eval/diagnostic.py",
    "line": null,
    "description": "DiagnosticRow columns (c) c_gold_in_vector_top4, (d) d_graph_seed_hit/seed_count/path_found stay None in plan 01 by design; resolved by plans -09/-13/-17 (Recall@4 probe, graph seeding) per plan 01's own Artifacts section.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-09-24T01:19:58.210Z",
    "resolved_at": null,
    "milestone": "v1.0"
  },
  {
    "id": 4,
    "kind": "lint-warning",
    "phase": "06.3.4.1",
    "file": "eval/src eval/tests",
    "line": null,
    "description": "Pre-existing ruff debt (~250-300 errors), out of scope for 06.3.4.1-05; see phase deferred-items.md",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-09-24T22:15:20.670Z",
    "resolved_at": null,
    "milestone": "v1.0"
  }
]
````
