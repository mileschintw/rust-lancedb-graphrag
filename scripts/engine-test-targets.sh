#!/bin/sh
# Per-target Rust test enumeration and floor gate for the engine crate (#44).
#
# Counts come from `cargo test -- --list`, which compiles every test target but runs no test.
# A target that drops out of the build, or a module whose tests stop being compiled in, falls
# below its floor and fails here by name instead of vanishing from a total.
#
# Each floor is a minimum, not an exact count: a lane that adds tests changes nothing here.
# Raise a floor when you want the gate to hold new tests in place. Lower one only in the
# commit that deletes or merges those tests, and say in that commit which tests now cover them.
# A target that reports tests but has no floor fails until it is added below on purpose.
# The exact per-commit counts this script used to pin (488 up to 982) are in its git history.
set -e

# Ensure cargo is found in standard user environments
CARGO_CMD="cargo"
if ! command -v cargo >/dev/null 2>&1; then
  for p in "$HOME/.cargo/bin" "/mnt/c/Users/user3/.cargo/bin" "/c/Users/user3/.cargo/bin"; do
    if [ -d "$p" ]; then
      export PATH="$p:$PATH"
    fi
  done
  if command -v cargo.exe >/dev/null 2>&1; then
    CARGO_CMD="cargo.exe"
  fi
fi

# "<target source path> <floor>", one per line. The path is what cargo prints after
# `Running` (`unittests` dropped), with forward slashes.
FLOORS="src/lib.rs 854
src/bin/inspect_lancedb.rs 58
src/bin/reconcile_eval_store.rs 18
src/bin/backfill_evidence_metadata.rs 14
src/bin/generate_from_context.rs 9
tests/config_startup.rs 27"

TMP_LIST=$(mktemp)
TMP_COUNTS=$(mktemp)
trap 'rm -f "$TMP_LIST" "$TMP_COUNTS"' EXIT

"$CARGO_CMD" test --manifest-path engine/Cargo.toml --locked -- --list 2>&1 | tr '\\' '/' | tr -d '\r' > "$TMP_LIST"

# One "<target> <count>" line per `Running` block.
awk '
/^ *Running / { target = $2; if (target == "unittests") target = $3; next }
target != "" && /^[0-9]+ tests?, [0-9]+ benchmarks?/ { print target, $1; target = ""; next }
' "$TMP_LIST" | sort > "$TMP_COUNTS"

if [ ! -s "$TMP_COUNTS" ]; then
  tail -n 40 "$TMP_LIST" >&2
  echo "FAIL: cargo test -- --list listed no target (did the build fail?)" >&2
  exit 1
fi

STATUS=0
TOTAL=0
while read -r target count; do
  [ -z "$target" ] && continue
  echo "$target: $count"
  TOTAL=$(( TOTAL + count ))
  if [ "$count" -gt 0 ] && ! echo "$FLOORS" | awk -v t="$target" '$1 == t { found = 1 } END { exit !found }'; then
    echo "FAIL: target $target reports $count tests but has no floor; add it to FLOORS deliberately" >&2
    STATUS=1
  fi
done < "$TMP_COUNTS"
echo "TOTAL: $TOTAL"

while read -r target floor; do
  [ -z "$target" ] && continue
  got=$(awk -v t="$target" '$1 == t { print $2; found = 1 } END { if (!found) print "MISSING" }' "$TMP_COUNTS")
  if [ "$got" = "MISSING" ]; then
    echo "FAIL: target $target is absent from cargo test --list (floor $floor)" >&2
    STATUS=1
  elif [ "$got" -lt "$floor" ]; then
    echo "FAIL: target $target has $got tests, below its floor of $floor" >&2
    STATUS=1
  fi
done <<EOF
$FLOORS
EOF

if [ "$STATUS" -ne 0 ]; then
  exit 1
fi

echo "Every Rust test target is at or above its floor."
exit 0
