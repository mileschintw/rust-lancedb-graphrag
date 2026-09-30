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
#   520 — Phase 06.3.4.1 plan 04 Task 1: `--document-ids` mode added 2 inspect_lancedb tests
#         (document_ids_lists_sorted_dedup_sets, document_ids_empty_store_yields_empty), 36->38.
#         lib/config_startup unchanged (460/22).
#   538 — Phase 06.3.4.1 plan 04 Task 2: new bin `reconcile_eval_store` (18 tests) — cascade
#         reconcile with dry-run-by-default and apply guards. All other counts unchanged (520+18).
#   540 — Phase 06.3.4.1 plan 06 Task 3: `--graph-population`'s `DegreeDistribution` gained `p99`
#         (D-77 cap derivation needs it, not estimable from p95/max alone) and
#         `GraphPopulationReport` gained a 10-bucket decile `degree_histogram` plus
#         `highest_degree_entity_name` (resolved for free from the existing entities read). Added 2
#         inspect_lancedb tests (empty_store_has_no_degree_histogram,
#         hub_and_spoke_percentiles_and_histogram_partition_every_entity), 38->40. lib/config_startup
#         unchanged (460/22).
#   548 — Phase 06.3.4.1 plan 08 Task 1/2: D-71 final-answer instruction in
#         `base_system_policy()` plus the `cl100k_base_singleton()` allocation-removal
#         refactor. Added 4 `prompt::tests` (existing-sentence guard, new-instruction guard,
#         singleton-usage source check, singleton-vs-fresh-build token-count equality) and 4
#         `workflow_phase5` validator/repair golden tests for the Answer line (accepted exactly
#         like the base answer, resolvable marker joins the citation set, unresolvable bracketed
#         year dropped with a notice, repair path never yields citation_marker_mismatch),
#         460->468. inspect_lancedb/reconcile_eval_store/config_startup unchanged (40/18/22).
#   552 — Phase 06.3.4.1 plan 09 Task 3: fixed `classify_evidence_item`'s adjacent-window
#         (b)/split-fact check, which naive-space-joined two overlapping chunks
#         (`format!("{a} {b}")`) instead of merging their shared `DEFAULT_CHUNK_OVERLAP`-sized
#         overlap once -- the duplicated overlap plus an inserted space that never existed in
#         the source document broke the substring match for any fact crossing the boundary
#         beyond the overlap, misclassifying it `absent` instead of `split_across_chunks` (this
#         produced 49 false `absent` states on the reconciled live-store probe). Added the
#         overlap-aware `merge_overlapping_chunks` helper and 4 inspect_lancedb tests
#         (merge_overlapping_chunks_removes_the_duplicated_overlap_once,
#         merge_overlapping_chunks_falls_back_to_space_join_without_overlap,
#         merge_overlapping_chunks_picks_the_longest_matching_overlap,
#         gold_chunks_probe_split_across_chunks_crossing_the_overlap_boundary), 40->44.
#         lib/reconcile_eval_store/config_startup unchanged (468/18/22).
#   561 -- Phase 06.3.4.1 plan 22 Task 1: D-90 default level filter. `resolve_log_filter`,
#         `assemble_subscriber` (the one stack both `build_providers_and_layers` branches use)
#         and `build_profile` in `telemetry/mod.rs`, with 9 `telemetry::log_filter_tests`
#         (default and override resolution, blank and malformed values, the OTLP-shaped and
#         console-only real stack on in-memory exporters, the override reaching every layer,
#         the console-only branch of `build_providers_and_layers`, `build_profile`),
#         468->477. inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   571 -- Phase 06.3.4.1 plan 22 Task 2: D-91 `generation_output_rejected` capture in
#         `generation/mod.rs` (`bounded_excerpt`, `emit_generation_output_rejected`) and the
#         provider rejection sites in `generation/openrouter.rs`, with 10 `generation::tests`
#         (parse failure with a trailing Answer line, short parse failure, finish_reason length
#         and missing, provider shape validation, usage over budget, prompt/evidence/key
#         sentinel, char-boundary excerpt, one-line fmt rendering, silent on success),
#         477->487. inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   577 -- Phase 06.3.4.1 plan 22 Task 3: D-91 grounding-validation capture in
#         `workflow/nodes/generate.rs` (`emit_validation_rejection` at all three
#         `validate_grounding_with_limits` sites), with 6 `workflow_phase5` tests (mixed answer
#         without markers, total citation drop, model-only branch, repair-disabled branch,
#         silent on a valid cited answer, routed through the D-90 default filter),
#         487->493. inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   579 -- Phase 06.3.4.1 plan 26 Task 2: F-1 (user-approved, D-71 costly) appended one clause to
#         `base_system_policy()` stating that the final `Answer:` line belongs inside the JSON
#         `answer` field, plus 2 `prompt::tests` (the clause is present; the pre-F-1 guard and D-71
#         text is a byte-identical prefix), 493->495. Four budget-boundary tests (three in
#         `tests.rs`, one in `workflow_phase5`) had their token budgets widened by the clause's ~35
#         tokens so they still exercise the same boundary; no test was added or removed for that.
#         inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   582 -- Phase 06.3.4.1 plan 27 Task 1: D-66 write-together of the seven `[engine.workflow]`
#         timeout budgets decided at 06.3.4.1-24, with 3 `config::tests` in `config.rs` (the
#         three-way agreement of `config/config.toml`, `config/config.example.toml` and the
#         `default_*_timeout_ms` functions, a pin of the seven decided values, and the nesting
#         slack plus startup-validation check), 495->498. inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (44/18/22).
#   586 -- Phase 06.3.4.1 plan 28 Task 1: D-93 prompt tokenizer warm-up at engine start
#         (`warm_prompt_tokenizer` in `prompt.rs`, called from `main.rs` before the serving line),
#         with 4 `prompt::tests` (prompt_tokenizer_warmup_counts_the_sample_with_the_singleton,
#         prompt_tokenizer_warmup_reads_the_singleton,
#         prompt_tokenizer_warmup_precedes_the_serving_line_in_main,
#         prompt_tokenizer_ready_line_passes_the_default_filter), 498->502. `engine (bin)` stays
#         0 (no test module in `main.rs`); inspect_lancedb/reconcile_eval_store/config_startup
#         unchanged (44/18/22).
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
BIN_RECONCILE_COUNT=$(awk '/Running unittests src\/bin\/reconcile_eval_store\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")
INTEG_CONFIG_COUNT=$(awk '/Running tests\/config_startup\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")

LIB_COUNT=${LIB_COUNT:-0}
BIN_MAIN_COUNT=${BIN_MAIN_COUNT:-0}
BIN_INSPECT_COUNT=${BIN_INSPECT_COUNT:-0}
BIN_SEED_COUNT=${BIN_SEED_COUNT:-0}
BIN_RECONCILE_COUNT=${BIN_RECONCILE_COUNT:-0}
INTEG_CONFIG_COUNT=${INTEG_CONFIG_COUNT:-0}

echo "engine (lib): $LIB_COUNT"
echo "engine (bin): $BIN_MAIN_COUNT"
echo "inspect_lancedb (bin): $BIN_INSPECT_COUNT"
echo "seed_rag_fixture (bin): $BIN_SEED_COUNT"
echo "reconcile_eval_store (bin): $BIN_RECONCILE_COUNT"
echo "config_startup (test): $INTEG_CONFIG_COUNT"

LIB_BIN_SUM=$(( LIB_COUNT + BIN_MAIN_COUNT ))
TOTAL=$(( LIB_BIN_SUM + BIN_INSPECT_COUNT + BIN_SEED_COUNT + BIN_RECONCILE_COUNT + INTEG_CONFIG_COUNT ))

echo "TOTAL: $TOTAL (lib+bin: $LIB_BIN_SUM, inspect_lancedb: $BIN_INSPECT_COUNT, seed_rag_fixture: $BIN_SEED_COUNT, reconcile_eval_store: $BIN_RECONCILE_COUNT, config_startup: $INTEG_CONFIG_COUNT)"

# Assert invariants (8 named assertions)
if [ "$TOTAL" -ne 586 ]; then
  echo "FAIL: TOTAL test count mismatch: expected 586, got $TOTAL" >&2
  exit 1
fi

if [ "$LIB_BIN_SUM" -ne 502 ]; then
  echo "FAIL: lib + bin test count mismatch: expected 502, got $LIB_BIN_SUM (lib=$LIB_COUNT, bin=$BIN_MAIN_COUNT)" >&2
  exit 1
fi

if [ "$LIB_COUNT" -ne 502 ]; then
  echo "FAIL: engine (lib) test count mismatch: expected 502, got $LIB_COUNT" >&2
  exit 1
fi

if [ "$BIN_MAIN_COUNT" -ne 0 ]; then
  echo "FAIL: engine (bin) test count mismatch: expected 0, got $BIN_MAIN_COUNT" >&2
  exit 1
fi

if [ "$BIN_INSPECT_COUNT" -ne 44 ]; then
  echo "FAIL: inspect_lancedb test count mismatch: expected 44, got $BIN_INSPECT_COUNT" >&2
  exit 1
fi

if [ "$BIN_SEED_COUNT" -ne 0 ]; then
  echo "FAIL: seed_rag_fixture test count mismatch: expected 0, got $BIN_SEED_COUNT" >&2
  exit 1
fi

if [ "$BIN_RECONCILE_COUNT" -ne 18 ]; then
  echo "FAIL: reconcile_eval_store test count mismatch: expected 18, got $BIN_RECONCILE_COUNT" >&2
  exit 1
fi

if [ "$INTEG_CONFIG_COUNT" -ne 22 ]; then
  echo "FAIL: config_startup test count mismatch: expected 22, got $INTEG_CONFIG_COUNT" >&2
  exit 1
fi

echo "All 8 Rust test target invariants verified successfully."
exit 0
