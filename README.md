# Coordination records

The `coord` branch: an orphan branch that never merges into the default branch. The coordinator commits and pushes it; workers only write their own files here.

| Path | What | Written by |
|---|---|---|
| `project.md` | Project settings relay reads | setup, then the user |
| `plan.md`, `plan-history.md` | The living plan and what moved out of it | coordinator |
| `briefs/<key>.md` | Lane briefs (`_template.md` is the form) | coordinator |
| `status/<key>.md` | Lane status, via `relay.py status` | worker |
| `reports/<key>.md` | A worker's full report | worker |
| `pr-bodies/<key>.md` | PR body drafts | worker |
| `decisions-<date>.md` | Decisions the user made in a session the coordinator opened to collect them, with their words | that session |
| `compact-instruction.md` | The coordinator's latest compact instruction | coordinator |
| `snapshot/` | Copies of scratchpads and notes folders the app may clear (not committed) | coordinator |
