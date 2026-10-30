#!/bin/sh
# Per-package Go test enumeration and floor gate for the gateway module (#44).
#
# Counts are taken from `go test -list`, not from grepping source. That matters: `-list`
# compiles every test binary, so a package that stops being compiled into the test run
# fails here (threat T-06-04-05) instead of silently vanishing from an aggregate. It does
# NOT run any test, so no PostgreSQL instance is required.
#
# Each floor is a minimum count of top-level Test functions, not an exact count: a lane that
# adds tests changes nothing here. Raise a floor when you want the gate to hold new tests in
# place. Lower one only in the commit that deletes or merges those tests, and say in that
# commit which tests now cover them. A package that reports tests but has no floor fails
# until it is added below on purpose. The exact counts this script used to pin (67 up to
# 124) are in its git history.
set -e

# "<import-path-suffix> <floor>", one per line.
FLOORS="gateway 83
gateway/db 7
gateway/internal/config 4
gateway/internal/engineclient 1
gateway/internal/sse 17
gateway/internal/telemetry 11"

# Ensure go is found in standard user environments
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

TMP_COUNTS=$(mktemp)
TMP_LIST=$(mktemp)
trap 'rm -f "$TMP_COUNTS" "$TMP_LIST"' EXIT

# `go test -list` emits the test names for a package followed by an `ok <import-path>`
# summary line; packages without tests emit `?   <import-path> [no test files]`.
(cd gateway && "$GO_CMD" test -list '.*' ./...) | tr -d '\r' > "$TMP_LIST"

awk '
/^ok[ \t]/  { pkg = $2; sub(/^github\.com\/lancet\//, "", pkg); print pkg, pending; pending = 0; next }
/^\?[ \t]/  { pkg = $2; sub(/^github\.com\/lancet\//, "", pkg); print pkg, 0;       pending = 0; next }
/^(FAIL|---|PASS)/ { next }
/^Test/     { pending++; next }
' "$TMP_LIST" | sort > "$TMP_COUNTS"

STATUS=0
TOTAL=0
while read -r pkg count; do
  [ -z "$pkg" ] && continue
  echo "$pkg $count"
  TOTAL=$(( TOTAL + count ))
  if [ "$count" -gt 0 ] && ! echo "$FLOORS" | awk -v p="$pkg" '$1 == p { found = 1 } END { exit !found }'; then
    echo "FAIL: package $pkg reports $count tests but has no floor; add it to FLOORS deliberately" >&2
    STATUS=1
  fi
done < "$TMP_COUNTS"
echo "TOTAL: $TOTAL"

while read -r pkg floor; do
  [ -z "$pkg" ] && continue
  got=$(awk -v p="$pkg" '$1 == p { print $2; found = 1 } END { if (!found) print "MISSING" }' "$TMP_COUNTS")
  if [ "$got" = "MISSING" ]; then
    echo "FAIL: package $pkg is absent from the test run (floor $floor); it no longer compiles into \`go test ./...\`" >&2
    STATUS=1
  elif [ "$got" -lt "$floor" ]; then
    echo "FAIL: package $pkg has $got tests, below its floor of $floor" >&2
    STATUS=1
  fi
done <<EOF
$FLOORS
EOF

if [ "$STATUS" -ne 0 ]; then
  exit 1
fi

echo "Every gateway test package is at or above its floor."
exit 0
