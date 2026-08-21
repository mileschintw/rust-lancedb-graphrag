#!/bin/sh
set -e

TMP_FILE=$(mktemp)
trap 'rm -f "$TMP_FILE"' EXIT

# Run cargo test --list and normalize path separators
cargo test --manifest-path engine/Cargo.toml -- --list 2>&1 | tr '\\' '/' > "$TMP_FILE"

# Extract counts using awk
LIB_COUNT=$(awk '/Running unittests src\/lib\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")
BIN_MAIN_COUNT=$(awk '/Running unittests src\/main\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")
BIN_INSPECT_COUNT=$(awk '/Running unittests src\/bin\/inspect_lancedb\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")
BIN_SEED_COUNT=$(awk '/Running unittests src\/bin\/seed_rag_fixture\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")
INTEG_CONFIG_COUNT=$(awk '/Running tests\/config_startup\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")

LIB_COUNT=${LIB_COUNT:-0}
BIN_MAIN_COUNT=${BIN_MAIN_COUNT:-0}
BIN_INSPECT_COUNT=${BIN_INSPECT_COUNT:-0}
BIN_SEED_COUNT=${BIN_SEED_COUNT:-0}
INTEG_CONFIG_COUNT=${INTEG_CONFIG_COUNT:-0}

echo "engine (lib): $LIB_COUNT"
echo "engine (bin): $BIN_MAIN_COUNT"
echo "inspect_lancedb (bin): $BIN_INSPECT_COUNT"
echo "seed_rag_fixture (bin): $BIN_SEED_COUNT"
echo "config_startup (test): $INTEG_CONFIG_COUNT"

LIB_BIN_SUM=$(( LIB_COUNT + BIN_MAIN_COUNT ))
TOTAL=$(( LIB_BIN_SUM + BIN_INSPECT_COUNT + BIN_SEED_COUNT + INTEG_CONFIG_COUNT ))

echo "TOTAL: $TOTAL (lib+bin: $LIB_BIN_SUM, inspect_lancedb: $BIN_INSPECT_COUNT, seed_rag_fixture: $BIN_SEED_COUNT, config_startup: $INTEG_CONFIG_COUNT)"

# Assert invariants
if [ "$TOTAL" -ne 288 ]; then
  echo "FAIL: TOTAL test count mismatch: expected 288, got $TOTAL" >&2
  exit 1
fi

if [ "$LIB_BIN_SUM" -ne 261 ]; then
  echo "FAIL: lib + bin test count mismatch: expected 261, got $LIB_BIN_SUM (lib=$LIB_COUNT, bin=$BIN_MAIN_COUNT)" >&2
  exit 1
fi

if [ "$BIN_INSPECT_COUNT" -ne 18 ]; then
  echo "FAIL: inspect_lancedb test count mismatch: expected 18, got $BIN_INSPECT_COUNT" >&2
  exit 1
fi

if [ "$BIN_SEED_COUNT" -ne 0 ]; then
  echo "FAIL: seed_rag_fixture test count mismatch: expected 0, got $BIN_SEED_COUNT" >&2
  exit 1
fi

if [ "$INTEG_CONFIG_COUNT" -ne 9 ]; then
  echo "FAIL: config_startup test count mismatch: expected 9, got $INTEG_CONFIG_COUNT" >&2
  exit 1
fi

echo "All 5 Rust test target invariants verified successfully."
exit 0
