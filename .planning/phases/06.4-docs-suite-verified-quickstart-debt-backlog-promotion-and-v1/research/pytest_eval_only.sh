#!/usr/bin/env bash
# Validation Architecture: eval/tests only (the quickstart-facing suite), fresh Windows clone.
set -u
C="$1"; cd "$C"
( time uv run --project eval pytest eval/tests -q -p no:cacheprovider ) > "$C/../pytest_eval_only.log" 2>&1; echo "pytest eval/tests exit=$?"; tail -6 "$C/../pytest_eval_only.log"
