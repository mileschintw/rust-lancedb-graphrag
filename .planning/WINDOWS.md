---
schema_version: 1
open_count: 2
waived_count: 0
fixed_count: 0
total_count: 2
last_updated: 2026-07-26T04:04:36.220Z
---

# Broken Windows Ledger

> Cross-phase defect register. `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 02 | stub | engine/src/main.rs | 329 | Pre-existing query_rag placeholder answer and empty citations; deferred to Phase 03. | open |  | 2026-07-26T04:04:35.521Z |  |
| 2 | 02 | stub | engine/src/main.rs | 340 | Pre-existing query_graph scaffolding payload; deferred to Phase 04. | open |  | 2026-07-26T04:04:36.220Z |  |

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
  }
]
````
