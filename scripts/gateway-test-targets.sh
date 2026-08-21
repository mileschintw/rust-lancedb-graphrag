#!/bin/sh
set -e

TOTAL=0
TMP_COUNTS=$(mktemp)
trap 'rm -f "$TMP_COUNTS"' EXIT

# Find all _test.go files under gateway, count ^func Test after removing comments, grouped by package directory
find gateway -type f -name "*_test.go" | sort | while IFS= read -r test_file; do
  pkg_dir=$(dirname "$test_file" | tr '\\' '/')
  count=$(grep -v '^[[:space:]]*//' "$test_file" | grep -c '^func Test' || true)
  echo "$pkg_dir $count"
done | awk '
{
  counts[$1] += $2
}
END {
  for (pkg in counts) {
    print pkg, counts[pkg]
  }
}' | sort > "$TMP_COUNTS"

while IFS= read -r line; do
  [ -z "$line" ] && continue
  pkg=$(echo "$line" | awk '{print $1}')
  count=$(echo "$line" | awk '{print $2}')
  echo "$pkg $count"
  TOTAL=$(( TOTAL + count ))
done < "$TMP_COUNTS"

echo "TOTAL: $TOTAL"

if [ "$TOTAL" -ne 67 ]; then
  echo "FAIL: gateway test count mismatch: expected 67, got $TOTAL" >&2
  exit 1
fi

echo "Go test target invariants verified successfully."
exit 0
