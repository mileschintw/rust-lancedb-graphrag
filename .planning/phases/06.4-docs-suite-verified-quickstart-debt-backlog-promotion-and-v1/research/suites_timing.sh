#!/usr/bin/env bash
# Validation Architecture: time the eval pytest suite and the gateway go test in the fresh Windows clone (local, free, no network calls by the tests).
set -u
C="$1"; cd "$C"
( time uv run --project eval pytest -q -p no:cacheprovider ) > "$C/../pytest.log" 2>&1; echo "pytest exit=$?"; tail -8 "$C/../pytest.log"
cd "$C/gateway" && ( time go test -count=1 ./... ) > "$C/../gotest.log" 2>&1; echo "go test exit=$?"; tail -12 "$C/../gotest.log"
