# Lane 81 compact instruction

- Role: relay worker (relay:work skill) for lane key `81`, closing #81 (S2 reader comparison: deepseek list price, paired per-reader rows).
- Worktree: D:\Repos\lancet\.claude\worktrees\lane-81-559d88, branch `claude/lane-81-559d88` (no commits yet).
- Records folder: D:/Repos/lancet-coord; brief: D:/Repos/lancet-coord/briefs/81.md; coordinator id: local_e5497074-397c-4170-ba22-60a6e066d35b.
- State: parked until `GO #81` (waited for #68, now merged as PR #83). Nothing edited or committed.
- On GO: reread the relay:work skill, the brief, project.md and #81; `git fetch`; `git reset --hard origin/main`; push; run the eval fast tier; status `working`.
- Build test-first in `lever_comparison.py` (`_reader_price`, `_reader_row`, reader table), `measure.py` (list-price constant 0.0137/1.28 only), `eval/tests/test_reader_comparison.py`: price deepseek at list price; per-reader `answer_usable` rows on the common all-arms-`ok` question set, stating per-arm drops and why.
- Then review, checks (fast tier + slow v1.0 re-score, ruff), PR body draft in pr-bodies/81.md, report in reports/81.md (Traditional Chinese), status `done`.
