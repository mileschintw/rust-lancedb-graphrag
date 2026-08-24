#!/bin/sh
# Per-package Go test target enumeration and invariant gate for the gateway module.
#
# Counts are taken from `go test -list`, not from grepping source. That matters: `-list`
# compiles every test binary, so a package that stops being compiled into the test run
# fails here (threat T-06-04-05) instead of silently vanishing from an aggregate. It does
# NOT run any test, so no PostgreSQL instance is required.
#
# Invariant history:
#   67 — the plan 06-04 relocation baseline (gateway 60 + gateway/db 7). The D-82 package
#        split moved production code only; no test was lost or gained by relocation.
#   75 — 67 plus the 8 package-local tests added to gateway/internal/sse, which owns the
#        /rag/query JSON wire contract that plan 06-07 extends.
#   80 — 75 plus TestBadInputMatrixHTTP (plan 06-12), the D-15 bad-input matrix's HTTP half.
set -e

EXPECTED_TOTAL=90
RELOCATION_BASELINE=67

# Expected per-package counts: "<import-path-suffix> <count>". A package listed here with a
# different count fails by name; a package absent here that reports tests also fails by name.
EXPECTED_PACKAGES="gateway 66
gateway/db 7
gateway/internal/config 4
gateway/internal/sse 8
gateway/internal/telemetry 5"

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

TOTAL=0
while IFS= read -r line; do
  [ -z "$line" ] && continue
  pkg=$(echo "$line" | awk '{print $1}')
  count=$(echo "$line" | awk '{print $2}')
  echo "$pkg $count"
  TOTAL=$(( TOTAL + count ))
done < "$TMP_COUNTS"

echo "TOTAL: $TOTAL"

STATUS=0

# Assert every expected package reports exactly its expected count, naming the package.
echo "$EXPECTED_PACKAGES" | while IFS= read -r expected; do
  [ -z "$expected" ] && continue
  exp_pkg=$(echo "$expected" | awk '{print $1}')
  exp_count=$(echo "$expected" | awk '{print $2}')
  got_count=$(awk -v p="$exp_pkg" '$1 == p { print $2; found = 1 } END { if (!found) print "MISSING" }' "$TMP_COUNTS")
  if [ "$got_count" = "MISSING" ]; then
    echo "FAIL: package $exp_pkg is absent from the test run (expected $exp_count tests) — it no longer compiles into \`go test ./...\`" >&2
    exit 1
  fi
  if [ "$got_count" -ne "$exp_count" ]; then
    echo "FAIL: package $exp_pkg test count moved: expected $exp_count, got $got_count" >&2
    exit 1
  fi
done || STATUS=1

# Assert any package NOT in the expected list reports zero tests, naming the package.
while IFS= read -r line; do
  [ -z "$line" ] && continue
  pkg=$(echo "$line" | awk '{print $1}')
  count=$(echo "$line" | awk '{print $2}')
  [ "$count" -eq 0 ] && continue
  if ! echo "$EXPECTED_PACKAGES" | awk -v p="$pkg" '$1 == p { found = 1 } END { exit !found }'; then
    echo "FAIL: package $pkg reports $count tests but is not in the expected distribution — add it to EXPECTED_PACKAGES deliberately" >&2
    STATUS=1
  fi
done < "$TMP_COUNTS"

if [ "$TOTAL" -ne "$EXPECTED_TOTAL" ]; then
  echo "FAIL: gateway test count mismatch: expected $EXPECTED_TOTAL, got $TOTAL (relocation baseline was $RELOCATION_BASELINE)" >&2
  STATUS=1
fi

if [ "$STATUS" -ne 0 ]; then
  exit 1
fi

echo "Go test target invariants verified successfully."
exit 0
