#!/bin/sh
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

# Invariant history:
#   488 — the Phase 06 baseline (TOTAL 488, lib 448, inspect_lancedb 18, config_startup 22).
#   498 — Phase 06.3.1 (TOTAL 498, lib 458): plans 01, 02, 03, 04 added 10 unit/integration tests in engine lib.
#   511 — committed baseline entering Phase 06.3.4.1 (TOTAL 511, lib+bin 458, inspect_lancedb 31, config_startup 22).
#   518 — Phase 06.3.4.1 plan 01 Task 1: raised to the values actually measured on entry to this task
#         (lib+bin 460, inspect_lancedb 36, config_startup 22). Two of those lib tests predate this
#         plan's diff (git status showed zero working-tree changes outside inspect_lancedb.rs /
#         inspect_lancedb_tests.rs before this update), so the lib count was already stale by 2 —
#         raised to match measured reality per this script's own update policy, not investigated
#         further (out of this task's file scope). `--gold-chunks` probe mode itself added 5
#         inspect_lancedb tests (gold_chunks_flags_parse_and_require_pairing,
#         gold_chunks_probe_classifies_evidence_states, gold_chunks_probe_rejects_non_uuid_document_id,
#         gold_chunks_probe_does_not_mutate_table_versions, normalize_ws_matches_python_rule).
# The expected values in this script are measured values from the test topology.
# When a later plan adds tests, it updates them to the newly measured values in the same commit
# as the tests that moved them. Lowering a value to make the gate pass or deleting
# an assertion is never the correct response to a red gate.

TMP_FILE=$(mktemp)
trap 'rm -f "$TMP_FILE"' EXIT

# Run cargo test --list and normalize path separators
"$CARGO_CMD" test --manifest-path engine/Cargo.toml -- --list 2>&1 | tr '\\' '/' | tr -d '\r' > "$TMP_FILE"

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

# Assert invariants (7 named assertions)
if [ "$TOTAL" -ne 518 ]; then
  echo "FAIL: TOTAL test count mismatch: expected 518, got $TOTAL" >&2
  exit 1
fi

if [ "$LIB_BIN_SUM" -ne 460 ]; then
  echo "FAIL: lib + bin test count mismatch: expected 460, got $LIB_BIN_SUM (lib=$LIB_COUNT, bin=$BIN_MAIN_COUNT)" >&2
  exit 1
fi

if [ "$LIB_COUNT" -ne 460 ]; then
  echo "FAIL: engine (lib) test count mismatch: expected 460, got $LIB_COUNT" >&2
  exit 1
fi

if [ "$BIN_MAIN_COUNT" -ne 0 ]; then
  echo "FAIL: engine (bin) test count mismatch: expected 0, got $BIN_MAIN_COUNT" >&2
  exit 1
fi

if [ "$BIN_INSPECT_COUNT" -ne 36 ]; then
  echo "FAIL: inspect_lancedb test count mismatch: expected 36, got $BIN_INSPECT_COUNT" >&2
  exit 1
fi

if [ "$BIN_SEED_COUNT" -ne 0 ]; then
  echo "FAIL: seed_rag_fixture test count mismatch: expected 0, got $BIN_SEED_COUNT" >&2
  exit 1
fi

if [ "$INTEG_CONFIG_COUNT" -ne 22 ]; then
  echo "FAIL: config_startup test count mismatch: expected 22, got $INTEG_CONFIG_COUNT" >&2
  exit 1
fi

echo "All 7 Rust test target invariants verified successfully."
exit 0
