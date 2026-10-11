#!/usr/bin/env bash
# D-200/I: does a SHALLOW clone break score_run's D-73 [split] git-ancestry check?  Free, local only.
set -u
BASE="${TMPDIR:-/tmp}/lancet-shallow-$$"
mkdir -p "$BASE"
git clone --depth 1 "file:///d/Repos/lancet" "$BASE/clone" 2>&1 | tail -2
cd "$BASE/clone"
echo "shallow? $(git rev-parse --is-shallow-repository)  commits visible: $(git rev-list --count HEAD)"
RUN=eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout
cp -r "$RUN" "$BASE/run"
( time uv run --project eval lancet-eval score --run "$BASE/run" --no-judge ) > "$BASE/score.log" 2>&1; echo "score exit=$?"
tail -12 "$BASE/score.log"
echo "BASE=$BASE"
