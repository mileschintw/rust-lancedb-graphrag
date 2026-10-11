#!/usr/bin/env bash
# D-200/D-220: FULL (non-shallow) fresh clone on Windows native (core.autocrlf=true here); re-score a copy of the run of record.
set -u
BASE="${TMPDIR:-/tmp}/lancet-fresh-$$"
mkdir -p "$BASE"
( time git clone "file:///d/Repos/lancet" "$BASE/clone" ) > "$BASE/clone.log" 2>&1; tail -4 "$BASE/clone.log" | grep -v Updating
cd "$BASE/clone"
echo "shallow? $(git rev-parse --is-shallow-repository)  commits: $(git rev-list --count HEAD)  autocrlf=$(git config core.autocrlf)"
RUN=eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout
echo "journal CRLF count in clone: $(grep -c $'\r' $RUN/journal.jsonl)"
cp -r "$RUN" "$BASE/run"
( time uv run --project eval lancet-eval score --run "$BASE/run" --no-judge ) > "$BASE/score.log" 2>&1; echo "score exit=$?"
tail -6 "$BASE/score.log"
( time uv run --project eval lancet-eval report --run "$BASE/run" ) > "$BASE/report.log" 2>&1; echo "report exit=$?"
echo "--- git status in clone (eval/runs must be empty; eval/.venv ignored?)"; git status --porcelain | head
echo "BASE=$BASE"
