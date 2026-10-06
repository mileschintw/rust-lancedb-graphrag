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
#   592 -- Phase 06.3.4.1 plan 29 Task 1: D-95 end to end. `ModelOutput.final_answer`, the required
#         strict-schema `final_answer` property, `generation/final_answer.rs`
#         (`render_final_answer_line`) and the single render seam `update_from_model_output`, with
#         6 `d95_` tests (d95_openrouter_schema_requires_final_answer_and_the_adapter_returns_it,
#         d95_mock_provider_final_answer_is_rendered_by_the_generate_node,
#         d95_model_output_without_final_answer_parses_and_serializes_as_before,
#         d95_rendered_answer_ends_with_a_line_start_answer_line,
#         d95_absent_or_blank_final_answer_leaves_the_answer_byte_identical,
#         d95_answer_events_carry_the_rendered_text), 502->508. `engine (bin)` stays 0;
#         inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   594 -- Phase 06.3.4.1 plan 29 Task 2: D-95 appended one sentence (31 cl100k tokens) to
#         `base_system_policy()` (the JSON `final_answer` field), with 2 `prompt::tests` goldens
#         (d95_policy_states_the_final_answer_field,
#         d95_policy_keeps_the_pre_d95_text_as_a_byte_identical_prefix), 508->510. The four
#         budget-boundary tests (three in `tests.rs`, one in `workflow_phase5`) failed on the longer
#         policy and had their token budgets widened by the sentence's 31 tokens (460->491,
#         510->541, 535->566, 380->411); no test was added or removed for that.
#         `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/config_startup unchanged
#         (44/18/22).
#   605 -- Phase 06.3.4.1 plan 29 Task 3: D-95 guards on the rendered line in
#         `generation/final_answer.rs` (field sanitising, trailing model Answer segment strip,
#         whole-field fit against MAX_ANSWER_CHARS), with 8 `final_answer::tests` (the markers
#         and brackets, leading label, whitespace collapse, 256-char truncation, whole-field fit,
#         trailing-segment strip, kept bracketed/non-final segment, last-line invariant) and 3
#         `workflow_phase5` tests (d95_bracketed_final_answer_never_reaches_validation,
#         d95_final_answer_does_not_change_a_rejection,
#         d95_rendered_answer_revalidates_like_the_original), 510->521. `engine (bin)` stays 0;
#         inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   611 -- Phase 06.3.4.1 plan 29 Task 4: D-96 `provider: {"require_parameters": true}` on every
#         OpenRouter chat payload, and one INFO `generation_served` event per provider response
#         (generation ID, served model, provider and correlation ID, bounded and escaped) in
#         `generation/openrouter.rs`, with 6 `generation::tests` (d96_chat_payload_requires_parameters,
#         d96_generation_served_logs_the_response_id_model_and_provider,
#         d96_generation_served_without_response_fields_never_fails,
#         d96_generation_served_tolerates_non_string_fields,
#         d96_generation_served_is_logged_for_a_rejected_output,
#         d96_generation_served_bounds_and_escapes_provider_text), 521->527. `engine (bin)` stays 0;
#         inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   641 -- Phase 06.3.4.1 plan 13 Task 1: OI-01 library code. `graph::index` (`GraphIndex`, built
#         from one scan of `entities` and one of `entity_edges`), `graph::seeding` (mention
#         extraction, exact / normalised / vector seed matching, the batched multi-vector
#         `LanceMentionVectorSearch`) and `graph::paths` (bounded seed-to-seed path search, the
#         degree cap, ranked candidate chunks), with 30 `graph::tests::seed_paths` tests, 527->557.
#         `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/config_startup unchanged
#         (44/18/22).
#   642 -- Phase 06.3.4.1 plan 13 Task 2: one more `graph::tests::seed_paths` test
#         (a_lower_case_connector_never_starts_a_mention) for a mention-extraction bug the offline
#         probe's first output showed (a leading `the` left by a stripped stop-word became part of
#         the mention), 557->558. `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (44/18/22).
#   643 -- Phase 06.3.4.1 plan 13 Task 2: one more `graph::tests::seed_paths` test
#         (a_vector_candidate_whose_name_has_no_letters_or_digits_is_never_a_seed). The offline
#         probe found one entity named with spaces only that the vector search returned for 20 of
#         the 100 questions at exactly the minimum score, because it embeds to a degenerate
#         vector, 558->559. `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (44/18/22).
#   644 -- Phase 06.3.4.1 plan 13 Task 3: one more `graph::tests::seed_paths` test
#         (the_confirmed_path_fact_cap_is_the_budget_formula_at_the_measured_p95) pinning the new
#         `MAX_PATH_FACTS` constant (8, confirmed by the user on 2026-10-05) to
#         `derive_max_path_facts(8192, 2048, 69)` and below the ceiling, 559->560. `engine (bin)`
#         stays 0; inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   650 -- Phase 06.3.4.1 plan 14 Task 1: the corpus snapshot carries an immutable
#         `Arc<GraphIndex>` built at startup and rebuilt and swapped with BM25, with 6
#         `graph::tests::snapshot_graph_index` tests (the empty index, a rebuild reflecting the
#         latest entities and edges, an old snapshot keeping the old index, a graph-index build
#         failure keeping the whole prior snapshot degraded, recovery on the next rebuild, and
#         main.rs building the index once before the first snapshot), 560->566. `engine (bin)`
#         stays 0; inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   654 -- Phase 06.3.4.1 plan 14 Task 2: D-77 graph settings (`max_seeds`, `mention_vector_top_k`,
#         `degree_cap`, `max_path_facts`, `max_graph_chunk_candidates`) in `config.rs`,
#         `config/config.toml` and `config/config.example.toml`, with 4 `config::tests` (the
#         three-way agreement of the files and the `default_*` functions, a pin of the decided
#         values, the chunk-candidate cap equal to `final_limit`, and startup rejecting a zero
#         `max_seeds`, `degree_cap` or `max_path_facts`), 566->570. `engine (bin)` stays 0;
#         inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   676 -- Phase 06.3.4.1 plan 14 Task 3: the production graph cutover. Mention seeding and
#         seed-to-seed path facts replace the single nearest-entity seeding in
#         `attempt_graph_augmentation`, the graph port takes the question text and returns a
#         `GraphQueryOutput`, and the node records the D-79 fields. 21 `tests::graph_cutover`
#         tests (the service function over a temp store: a two-hop path, seeds without a path and
#         no chunk candidates under paths-only, no mention, no vector match, a vector seed, a failed
#         search, the seed and degree caps, an empty index, the settings mapping; the production
#         port; the node's fields, graph-off, the original question, the timeout; the removed
#         seeding and the unused seed-chunk fallback as source checks; the directional path text in
#         the prompt and the confirmed cap) and one `telemetry_query` span test (seed count and
#         path found recorded, no question or entity text), 570->592. Two existing tests were
#         rewritten in place (`attempt_graph_augmentation_over_an_empty_store_finds_no_match` and
#         `graph_fact_preserves_stored_edge_orientation_when_seed_is_target`). `engine (bin)` stays
#         0; inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   677 -- Phase 06.3.4.1 plan 14 Task 3 (fix): one more `graph::tests::seed_paths` test
#         (a_two_hop_fact_relation_text_points_each_hop_the_way_its_edge_is_stored). The relation
#         attribute of a two-hop `GraphFact` used one arrow for both hops, so for a hop stored against
#         the path it contradicted the readable text of the same fact; each arrow now follows its
#         hop, at the same length, 592->593. `engine (bin)` stays 0;
#         inspect_lancedb/reconcile_eval_store/config_startup unchanged (44/18/22).
#   691 -- Phase 06.3.4.1 plan 15 Task 1: the graph chunk list as a third RRF list. The graph list is
#         applied once to the cross-variant result (so its contribution does not scale with the
#         variant count) with provenance source `graph` and the new `graph_rrf_weight` setting
#         (default 1.0, separate from the D-30 prompt-packing `graph_weight`), with 11 fusion tests in
#         `retrieval::tests` (graph-only entry, summed score with dense, reorder and tie order, graph
#         rank order, zero weight, variant-count independence, dedupe and candidate limit, non-finite
#         score, provenance serialisation, `graph_weight` never reaching fusion, weight validation),
#         one graph-off pin against the output recorded before the change
#         (`retrieval/testdata/graph_off_fusion.golden`) and 2 `config::tests` (the three-way
#         agreement of `graph_rrf_weight`, its separation from `graph_weight`), 677->691. The lib
#         count rises 593->607. `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (44/18/22).
#   711 -- Phase 06.3.4.1 plan 15 Task 2: RetrieveHybrid fetches the graph's candidate chunks at the
#         snapshot's `nodes` version (`DenseRetrievalPort::fetch_chunks_by_id`), merges them once per
#         query as the third RRF list and flags every chunk the graph contributed to
#         (`EvidenceBlock.graph_boosted`, `WorkflowContext.graph_boosted_chunk_count`), with 20
#         `tests::graph_boost` tests (two graph-off pins against the node output recorded before the
#         change, a stale count reset, the zero-weight and empty-list cases, a graph-only chunk, a
#         chunk dense also found, the count over the final set only, one fetch for three variants, the
#         graph node's hand-off through the context, chunk ID validation, malformed IDs dropped and
#         logged without their text, a repeated ID, a fetch failure that degrades, the request
#         filter, the evidence block flag and its omission from the checkpoint, and four production
#         port tests over a temp store: the pinned version, request order, a refused malformed ID and
#         the untouched dense sub-stage timings), 691->711. The lib count rises 607->627.
#         `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/config_startup unchanged
#         (44/18/22).
#   712 -- Phase 06.3.4.1 plan 15 Task 2: one more `tests::graph_boost` test, written after the
#         implementation (it passed on its first run and was shown to fail with the graph list
#         turned off): a graph-on query over the production ports and a temp store retrieves the
#         path entities' chunk in place of the second dense filler, flagged and counted, and the same
#         question with the graph disabled does not, 711->712. The lib count rises 627->628.
#         `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/config_startup unchanged
#         (44/18/22).
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
if [ "$TOTAL" -ne 712 ]; then
  echo "FAIL: TOTAL test count mismatch: expected 712, got $TOTAL" >&2
  exit 1
fi

if [ "$LIB_BIN_SUM" -ne 628 ]; then
  echo "FAIL: lib + bin test count mismatch: expected 628, got $LIB_BIN_SUM (lib=$LIB_COUNT, bin=$BIN_MAIN_COUNT)" >&2
  exit 1
fi

if [ "$LIB_COUNT" -ne 628 ]; then
  echo "FAIL: engine (lib) test count mismatch: expected 628, got $LIB_COUNT" >&2
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
