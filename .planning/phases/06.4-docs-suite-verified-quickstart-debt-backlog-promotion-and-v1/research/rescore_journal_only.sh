#!/usr/bin/env bash
# D-200: is journal.jsonl alone enough for score+report on a temp dir? (copy minimal => 44 MB instead of 51 MB, but fewer cp surprises)
set -u
REPO=/d/Repos/lancet
SRC="$REPO/eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout"
TMP="${TMPDIR:-/tmp}/lancet-rescore-min-$$"; mkdir -p "$TMP/run"
cp "$SRC/journal.jsonl" "$TMP/run/"
cd "$REPO"
uv run --project eval lancet-eval score --run "$TMP/run" --no-judge > "$TMP/score.log" 2>&1; echo "score exit=$?"
uv run --project eval lancet-eval report --run "$TMP/run" > "$TMP/report.log" 2>&1; echo "report exit=$?"
ls -la "$TMP/run"
python -I - "$SRC" "$TMP/run" <<'PY'
import json,sys,pathlib
a=pathlib.Path(sys.argv[1]);b=pathlib.Path(sys.argv[2])
A=json.loads((a/"report.json").read_text(encoding="utf-8"));B=json.loads((b/"report.json").read_text(encoding="utf-8"))
print("dimensions equal:",A["dimensions"]==B["dimensions"])
print("result_hash equal:",A["metadata"]["result_hash"]==B["metadata"]["result_hash"])
print("differing metadata keys:",[k for k in A["metadata"] if A["metadata"][k]!=B["metadata"][k]])
PY
echo "git status eval/runs: [$(git status --porcelain -- eval/runs)]"
echo "TMP=$TMP"
