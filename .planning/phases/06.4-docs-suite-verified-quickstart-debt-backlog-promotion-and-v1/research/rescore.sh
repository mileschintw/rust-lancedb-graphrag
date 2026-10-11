#!/usr/bin/env bash
# D-200 offline re-score experiment (free, no API key). Copies the committed 06.3.6 run OUTSIDE the repo,
# runs score --no-judge and report on the copy, then diffs the copy against the committed run.
set -u
REPO=/d/Repos/lancet
SRC="$REPO/eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout"
TMP="${TMPDIR:-/tmp}/lancet-rescore-$$"
mkdir -p "$TMP"
cp -r "$SRC" "$TMP/run"
echo "copy at: $TMP/run"
cd "$REPO"
echo "--- git status before"; git status --porcelain -- eval/runs
( time uv run --project eval lancet-eval score --run "$TMP/run" --no-judge ) > "$TMP/score.log" 2>&1; echo "score exit=$?"
tail -5 "$TMP/score.log"
( time uv run --project eval lancet-eval report --run "$TMP/run" ) > "$TMP/report.log" 2>&1; echo "report exit=$?"
tail -5 "$TMP/report.log"
echo "--- git status after (must be empty)"; git status --porcelain -- eval/runs
echo "TMP=$TMP"
