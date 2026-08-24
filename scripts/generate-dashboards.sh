#!/bin/sh
set -e

# Ensure go is found
GO_CMD="go"
if ! command -v go >/dev/null 2>&1; then
  for p in "/mnt/c/Program Files/Go/bin" "/c/Program Files/Go/bin" "$HOME/go/bin"; do
    if [ -d "$p" ]; then
      export PATH="$p:$PATH"
    fi
  done
  if command -v go.exe >/dev/null 2>&1; then
    GO_CMD="go.exe"
  fi
fi

COMMITTED="deploy/grafana/dashboards/lancet-rag-operations.json"
TMP_OUT="deploy/grafana/dashboards/.lancet-rag-operations.tmp.json"
trap 'rm -f "$TMP_OUT"' EXIT

(cd deploy/grafana/dashboard_gen && "$GO_CMD" run main.go -output "../dashboards/.lancet-rag-operations.tmp.json")

if [ ! -f "$COMMITTED" ]; then
  echo "Committed dashboard $COMMITTED does not exist. Writing generated output..."
  cp "$TMP_OUT" "$COMMITTED"
  exit 0
fi

if ! cmp -s "$TMP_OUT" "$COMMITTED"; then
  echo "FAIL: Generated dashboard differs from committed $COMMITTED" >&2
  diff -u "$COMMITTED" "$TMP_OUT" || true
  exit 1
fi

echo "Dashboard $COMMITTED is up to date and byte-identical."
exit 0
