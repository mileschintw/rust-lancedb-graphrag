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
#   721 -- Phase 06.3.4.1 plan 16 Task 1: the seeding diagnostics and the per-chunk graph flag on the
#         wire (additive proto: `WorkflowMetadata` tags 12 to 16, `StructuredCitation` tag 10), with 9
#         `tests::graph_wire` tests (a graph-on workflow, the cited chunks never flagged, a graph-off
#         workflow, seeds without a path, a failed workflow, the next-free-tag and round-trip pin, an
#         older message decoding to the defaults, the span declaration and record, and a production
#         graph-on query over a temp store), 712->721. The lib count rises 628->637.
#         `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/config_startup unchanged
#         (44/18/22).
#   722 -- Phase 06.3.5 plan 01 Task 2: one tests::retrieval_mode_pins test (the default-request
#         node-chain golden recorded at 00fed3e424832650d2103b51b83f50b9335be1c4), 721->722. The lib
#         count rises 637->638. `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (44/18/22).
#   731 -- Phase 06.3.5 plan 01 Task 3: nine `inspect_lancedb` tests for the read-only `--chunk-text`
#         mode (flag parsing and the canonical `lance-<N>` generation, a malformed ID refused by line
#         number without echoing it, batching at the IN-predicate limit, the pinned-version read in
#         request order, an absent table version, a valid ID missing at the version, table versions
#         unchanged after a run, the SHA-256 vectors, and the JSONL row shape), 722->731.
#         inspect_lancedb rises 44->53. lib stays 638; `engine (bin)`/reconcile_eval_store/
#         config_startup unchanged (0/18/22).
#   732 -- Phase 06.3.5 plan 03 Task 2: the tracer test
#         `retrieval::tests::dense_only_request_skips_bm25_and_carries_the_ranking` (a dense_only
#         request with the ranking flag through `WorkflowContext::new` and `RetrieveHybridNode` over
#         fakes: the BM25 port is never called, the snapshot echoes the mode, the ranking's head is
#         the retrieved set), 731->732. The lib count rises 638->639. `engine (bin)` stays 0;
#         inspect_lancedb/reconcile_eval_store/config_startup unchanged (53/18/22).
#   741 -- Phase 06.3.5 plan 04 Task 1: nine `tests::retrieval_mode_pins` tests (bm25_only with the
#         graph off takes no query embedding and makes no dense call; bm25_only with the graph on
#         embeds once; the embedding call count for every mode and graph setting; dense_only keeps the
#         dense order and carries no bm25 rank; bm25_only over two variants equals the cross-variant
#         RRF of the two BM25 lists; the flag-on and explicit-hybrid scenarios equal the recorded
#         golden; the ranking head, rank contiguity and graph flag; a fused-score tie across the
#         final limit keeps the truncation order), 732->741. The lib count rises 639->648.
#         `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/config_startup unchanged
#         (53/18/22).
#   749 -- Phase 06.3.5 plan 18 Task 1: eight `abstention_` tests for the owner's 2026-10-07
#         grounded-abstention decision, at both seams that reject a cited `model_only`
#         abstention (the OpenRouter adapter's shape check and `GenerateAnswerNode`'s grounding
#         validation). Six in `generation::tests` (the live 954-character fixture through the
#         adapter and the node; a substantive `model_only` answer and an uncited abstention both
#         still rejected; the tolerant match table; the prompt-literal tie; the view's
#         preconditions) and two in `workflow_phase5` (unresolvable markers and the
#         repair-disabled cited-ID check, both still rejected), 741->749. The lib count rises
#         648->656. `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/config_startup
#         unchanged (53/18/22).
#   753 -- Phase 06.3.5 review fix CR-01: the abstention check now finds the model's own trailing
#         answer line ASCII-case-insensitively and through `*`/`_` emphasis (`answer: Yes`,
#         `**answer:** Yes`), so a contradicting model line can no longer be normalised to an
#         abstention. Four `abstention_` tests: the label-variant table in `abstains`, the
#         view's refusal for both forms, and two end-to-end regressions through the adapter
#         (lower case and markdown, both still rejected as `model_only`), 749->753. The lib
#         count rises 656->660. `engine (bin)` stays 0; inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (53/18/22).
#   758 -- Phase 06.3.6 plan 02 Task 2: five `inspect_lancedb` tests for the read-only
#         `--graph-dump` mode (flag parsing and the `--out` requirement, both tables written
#         sorted without vectors with a matching `dump_meta.json`, table versions unchanged and
#         byte-identical output across two runs, a refused overwrite, and an empty store),
#         753->758. inspect_lancedb rises 53->58. lib stays 660; `engine (bin)`/
#         reconcile_eval_store/config_startup unchanged (0/18/22).
#   759 -- Phase 06.3.6 plan 05 Task 1: the Wave-0 provider-message golden test
#         (`provider_messages_for_the_default_request_are_byte_identical_to_the_recorded_pre_change_output`,
#         recorded at the pre-change HEAD 895ec05a before any prompt-side edit), 758->759.
#         lib rises 660->661; `engine (bin)`/inspect_lancedb/reconcile_eval_store/config_startup
#         unchanged (0/58/18/22).
#   760 -- Phase 06.3.6 plan 05 Task 2: the `levers` tracer test
#         (`levers_pins::a_levers_request_is_admitted_and_echoed`, a service-level `query_rag`
#         that names `binary_answer_format` and reads it back from the final snapshot), 759->760.
#         lib rises 661->662; `engine (bin)`/inspect_lancedb/reconcile_eval_store/config_startup
#         unchanged (0/58/18/22).
#   765 -- Phase 06.3.6 plan 05 Task 3: five tests for the fail-closed `levers` contract:
#         four in `levers_pins` (an explicit empty list renders the recorded default-request
#         golden, the echo is ascending enum order whatever order the client sent, the `LeverSet`
#         refusal kinds, and `contains`/`iter`) and one in `graph_wire` (the declared tags 8, 15,
#         17 and 18 and their absent-field defaults). The admission rows added to
#         `bad_input_matrix` are rows of one existing test and do not move the count.
#         760->765. lib rises 662->667; `engine (bin)`/inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (0/58/18/22).
#   768 -- Phase 06.3.6 plan 06 Task 2: three `workflow_phase5` tests for the D-158 IN-02
#         `derive_degraded_mode` fix (the exact-message `BasisReconciled` notice for a normalised
#         grounded abstention is not degraded, alone or beside a real degradation; every other
#         reconciliation text, including one that merely contains the normalisation text, still is;
#         `RerankDegraded` still is), 765->768. lib rises 667->670; `engine (bin)`/inspect_lancedb/
#         reconcile_eval_store/config_startup unchanged (0/58/18/22).
#   776 -- Phase 06.3.6 plan 06 Task 1: eight `tests::query_embedding_retry` tests for the D-152
#         bounded query-embedding retry on a paused clock (a first-attempt success takes one call
#         and no pause; a timeout then success retries once after the blake3 jitter and counts it;
#         two timeouts fail with the existing timeout error after exactly two attempts; a
#         non-timeout error returns at once; a cancel during the pause returns cancelled with no
#         second attempt; the jitter is deterministic, bounded and spread; the attempt count; and
#         the retry count reaching `WorkflowMetadata` while a clean record omits the field),
#         768->776. lib rises 670->678; `engine (bin)`/inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (0/58/18/22).
#   777 -- Phase 06.3.6 plan 06 Task 1 (step 4): one `config::tests` test
#         (`graph_node_timeout_below_the_retry_budget_is_rejected_at_the_boundary`) pinning the
#         D-152 nesting rule in `WorkflowSettings::validate`: a node budget equal to
#         2 x query_embedding_timeout_ms + RETRY_JITTER_MAX_MS + graph_operation_timeout_ms passes
#         and one millisecond below it is refused with an error naming the key and the sum,
#         776->777. lib rises 678->679; `engine (bin)`/inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (0/58/18/22).
#   797 -- Phase 06.3.6 plan 09 Task 1: the query-taking `Reranker` port and the OpenRouter rerank
#         adapter (`rerank/mod.rs`, `rerank/openrouter.rs`). `rerank::tests` replaces its one
#         pass-through test with 21: the NoOp identity ranking, `reorder` over a permutation and
#         over five non-permutations, the request shape (one POST, bearer key, exact body with
#         `allow_fallbacks` false), the tie-break and score order, a missing `usage`, the reply
#         `model` rule (D-186), eight malformed-reply cases, the twelve listed statuses, a refused
#         connection, a timeout, a body over the cap, a reply between the two caps, an empty list
#         without a call, a blank query, blank key and config values, the class-only error phrases,
#         the sentinel key over errors, logs and `Debug`, the no-spawn source pin, and the
#         three-way rerank default agreement, 679->699 (+20). `engine (bin)`/inspect_lancedb/
#         reconcile_eval_store/config_startup unchanged (0/58/18/22).
#   798 -- Phase 06.3.6 plan 09 Task 1 (adapter and config keys): one `config::tests` test
#         (`rerank_endpoint_and_model_agree_with_both_files_and_are_validated`) pinning the
#         `[openrouter]` `rerank_endpoint` and `rerank_model` defaults against both config files
#         and startup's refusal of a blank value, 699->700. The two keys also joined the
#         `config_example_matches_effective_rag_contract` key and annotation tables (no test
#         added). `engine (bin)`/inspect_lancedb/reconcile_eval_store/config_startup unchanged
#         (0/58/18/22).
#   810 -- Phase 06.3.6 plan 09 Task 2: the rerank lever in the node, the per-request selection and
#         the provisional D-135 budget. Eleven `tests::levers_pins` tests (the recorded default
#         output and the ranking, final list and result hash over an identity lever, the D-133
#         capture after a rotating reranker, a lever reranker left uncalled for a plain request,
#         a stalled reranker cut at its limit under a paused clock with generation still running,
#         the six failure classes and their outcomes, the allowance cut to the node budget left
#         minus the reserve, a spent node budget that makes no call, the D-166 score overwrite
#         with the prompt following the reranked order, `rerank` availability, and the per-request
#         choice between the lever and the service reranker) and one `config::tests` test
#         (`workflow_budget_rerank_timeout_is_validated_against_the_retrieve_budget`),
#         798->810. lib rises 700->712; `engine (bin)`/inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (0/58/18/22).
#   827 -- Phase 06.3.6 plan 11 Task 1: `PromptOptions`, the metadata headers and the two lever
#         policy sentences (`doc_meta.rs`, `prompt.rs`, the provider adapter and `GenerationRequest`).
#         Three `doc_meta::tests` (a blank entry is not stored, an empty map, a later pair replaces an
#         earlier one), twelve `prompt::tests` (the flag-off bytes, the seven header subsets, a
#         tag-breaking value escaped, an instruction override setting `suspicious`, the constants
#         verbatim and ordered after the base policy, the five constraints of the format rules,
#         `PromptOptions` from the levers, the wrapper equal to the `_with` function, the fixed
#         policy order, the evidence section unchanged by the options, eight maximal headers not
#         evicting a typical chunk) and two `generation::tests` (the provider messages carry the
#         sentences the request selects, the request equality compares `prompt_options`),
#         810->827. lib rises 712->729; `engine (bin)`/inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (0/58/18/22).
#   836 -- Phase 06.3.6 plan 11 Task 2: the per-snapshot `DocMetaMap`, the attach step under the
#         `evidence_metadata` lever and its availability. Nine `tests::levers_pins` tests (the
#         dense and BM25 lists, final list and snapshot equal to the recorded golden for each prompt
#         lever alone, the ranking and result hash unchanged, the entry attached to the blocks of
#         its document only, no metadata without the lever, the citation title unchanged, the lever
#         available only over a non-empty map, the options reaching the generation request through
#         the service, and the map carried through a successful and through each degraded rebuild),
#         738 lib, 827->836. `engine (bin)`/inspect_lancedb/reconcile_eval_store/config_startup
#         unchanged (0/58/18/22).
#   857 -- Phase 06.3.6 plan 12 Task 1: lever 2 branch B (graph-list precision, D-139). Ten
#         `graph::tests::seed_paths` tests (the exact ranked list of `All`, `MultiCited(2)` and
#         `EdgeEvidence` over one bridge fixture, a threshold of one equal to `All` and a threshold
#         above the citations empty, the variant changing only the chunk list, a capped edge-evidence
#         list holding a chunk the capped multi-cited list lacks, edge evidence read from the kept
#         paths only, a hop with no shared chunk, each entity counted once, and the nesting property
#         over 300 seeded random graphs with each capped list checked against the rank keys and `All`
#         against `seed_chunk_candidates`), five `config::tests` (default and both files agree on
#         `graph_v2_chunk_precision`, an unknown variant refused at load, the name parser, the
#         variant-to-selection mapping, the path settings carrying the selection in force), two
#         `tests` env-override tests (`LANCET_ENGINE__GRAPH__GRAPH_V2_CHUNK_PRECISION` applied and an
#         unknown value refused) and four `tests::levers_pins` tests (`graph_v2` availability, the
#         per-request selection, the workflow builder taking the per-request settings, and admission
#         and echo through the service with D-165 still refusing the combination), 836->857. The
#         `levers_graph_v2_admitted` check is part of the existing `bad_input_matrix` test and does not
#         move the count. lib rises 738->759; `engine (bin)`/inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (0/58/18/22).
#   872 -- Phase 06.3.6 plan 14 Task 1: the 22-column `nodes` schema and the 10-column staging
#         schema (the evidence-metadata columns `doc_title`, `source`, `published_date`, D-144, D-168),
#         ingest persistence, both legacy staging upgrades, staged recovery of the three keys, the
#         engine's re-validation of them, and the fail-closed old store. Fifteen
#         `tests::ingest_metadata` tests (the 22-column and 10-column schema shapes, the three values on
#         every chunk row with the title kept, absent keys and empty values stored as null, the refused
#         and accepted values table, the validate-before-write source pin, the 6-column and 7-column
#         staging forms each empty and populated upgrading to strict equality, staged recovery with and
#         without the keys, and a 19-column `nodes` table failing `initialize` and `open_and_validate`
#         closed with the staging table untouched), 857->872. The lib count rises 759->774. `engine
#         (bin)`/inspect_lancedb/reconcile_eval_store/config_startup unchanged (0/58/18/22).
#   881 -- Phase 06.3.6 plan 14 Task 2: the production `DocMetaMap` scan (`ingest::load_doc_meta`, one
#         named-projection scan of `document_id` and the three metadata columns at the snapshot's
#         `nodes` version), called at startup after the v1 graph build and on the ingest rebuild path,
#         where a failed scan degrades the rebuild like the BM25 and graph builds do. Nine
#         `tests::ingest_metadata` tests (one entry for the document with metadata and none for the
#         other, an empty map and an unavailable lever for a store without metadata, an available lever
#         over a scanned snapshot, a handle at another version refused, the shared handle left unpinned,
#         a second rebuild picking up a newly ingested document, a failed scan keeping the prior
#         snapshot whole, the `main.rs` call-order pin and the rebuild-path pin), 872->881. The plan 11
#         rebuild test was rewritten in place (it pinned the superseded carry-forward) and does not move
#         the count. The lib count rises 774->783. `engine (bin)`/inspect_lancedb/reconcile_eval_store/
#         config_startup unchanged (0/58/18/22).
#   908 -- Phase 06.3.6 plan 14 Task 3: `db::backfill` (`backfill_nodes_metadata` over one
#         `Table::add_columns` with a scan-order `Reader`, the strict post-state check and restore,
#         `verify_backfill_on_copy` and its five COPY assertions, the legacy 19-column schema, the
#         sidecar) and the new bin `backfill_evidence_metadata` (dry run, `--apply`,
#         `--verify-on-copy`, `--migrate-only`). Thirteen `tests::ingest_metadata` tests (one version
#         and the strict 22-column schema with the 19 digests, old data files and values checked,
#         short and long readers refused, the second run failing with "already exists", a sidecar id
#         absent from `nodes`, a forced post-state mismatch restored, an empty table, backfilled equal
#         to a fresh ingest, the sidecar shape and its refusals, the schema classifier, three COPY
#         verification runs and the source pin) and fourteen bin tests (the argument modes, the eval,
#         copy and migrate isolation, the snapshot guard, a dry run that writes nothing, the refused
#         applies, an apply that moves only the `nodes` version, `--verify-on-copy` with its five
#         assertions and a failing one, `--migrate-only`, and the source pin), 881->908. The lib count
#         rises 783->796 and the new `backfill_evidence_metadata (bin)` count is 14.
#         `engine (bin)`/inspect_lancedb/reconcile_eval_store/config_startup unchanged (0/58/18/22).
#   915 -- Phase 06.3.6 plan 16 (D-191, generation pinned to Sail Research): the
#         `[openrouter] generation_provider_order` key and the `provider.order` / `allow_fallbacks`
#         request fields. Seven tests: one `generation::openrouter::tests` test (the exact `provider`
#         bytes pinned, unpinned and with two slugs), two `generation::tests` tests (the chat body
#         over a mock carries `order` and `allow_fallbacks = false` when pinned and the D-96 object
#         when the order is empty), two `config::tests` tests (the entry validation at startup, and
#         the pin in both committed files and the `verify` overlay with the open default), and two
#         `tests` tests (no environment override moves the pin, and `main.rs` pins the generation
#         config only). The key also joined the `config_example_matches_effective_rag_contract`
#         key and annotation tables (no test added). 908->915. lib rises 796->803;
#         `engine (bin)`/inspect_lancedb/reconcile_eval_store/backfill_evidence_metadata/
#         config_startup unchanged (0/58/18/14/22).
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
BIN_BACKFILL_COUNT=$(awk '/Running unittests src\/bin\/backfill_evidence_metadata\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")
INTEG_CONFIG_COUNT=$(awk '/Running tests\/config_startup\.rs/ {found=1; next} found && /tests?, 0 benchmarks/ {print $1; exit}' "$TMP_FILE")

LIB_COUNT=${LIB_COUNT:-0}
BIN_MAIN_COUNT=${BIN_MAIN_COUNT:-0}
BIN_INSPECT_COUNT=${BIN_INSPECT_COUNT:-0}
BIN_SEED_COUNT=${BIN_SEED_COUNT:-0}
BIN_RECONCILE_COUNT=${BIN_RECONCILE_COUNT:-0}
BIN_BACKFILL_COUNT=${BIN_BACKFILL_COUNT:-0}
INTEG_CONFIG_COUNT=${INTEG_CONFIG_COUNT:-0}

echo "engine (lib): $LIB_COUNT"
echo "engine (bin): $BIN_MAIN_COUNT"
echo "inspect_lancedb (bin): $BIN_INSPECT_COUNT"
echo "seed_rag_fixture (bin): $BIN_SEED_COUNT"
echo "reconcile_eval_store (bin): $BIN_RECONCILE_COUNT"
echo "backfill_evidence_metadata (bin): $BIN_BACKFILL_COUNT"
echo "config_startup (test): $INTEG_CONFIG_COUNT"

LIB_BIN_SUM=$(( LIB_COUNT + BIN_MAIN_COUNT ))
TOTAL=$(( LIB_BIN_SUM + BIN_INSPECT_COUNT + BIN_SEED_COUNT + BIN_RECONCILE_COUNT + BIN_BACKFILL_COUNT + INTEG_CONFIG_COUNT ))

echo "TOTAL: $TOTAL (lib+bin: $LIB_BIN_SUM, inspect_lancedb: $BIN_INSPECT_COUNT, seed_rag_fixture: $BIN_SEED_COUNT, reconcile_eval_store: $BIN_RECONCILE_COUNT, backfill_evidence_metadata: $BIN_BACKFILL_COUNT, config_startup: $INTEG_CONFIG_COUNT)"

# Assert invariants (9 named assertions)
if [ "$TOTAL" -ne 915 ]; then
  echo "FAIL: TOTAL test count mismatch: expected 915, got $TOTAL" >&2
  exit 1
fi

if [ "$LIB_BIN_SUM" -ne 803 ]; then
  echo "FAIL: lib + bin test count mismatch: expected 803, got $LIB_BIN_SUM (lib=$LIB_COUNT, bin=$BIN_MAIN_COUNT)" >&2
  exit 1
fi

if [ "$LIB_COUNT" -ne 803 ]; then
  echo "FAIL: engine (lib) test count mismatch: expected 803, got $LIB_COUNT" >&2
  exit 1
fi

if [ "$BIN_MAIN_COUNT" -ne 0 ]; then
  echo "FAIL: engine (bin) test count mismatch: expected 0, got $BIN_MAIN_COUNT" >&2
  exit 1
fi

if [ "$BIN_INSPECT_COUNT" -ne 58 ]; then
  echo "FAIL: inspect_lancedb test count mismatch: expected 58, got $BIN_INSPECT_COUNT" >&2
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

if [ "$BIN_BACKFILL_COUNT" -ne 14 ]; then
  echo "FAIL: backfill_evidence_metadata test count mismatch: expected 14, got $BIN_BACKFILL_COUNT" >&2
  exit 1
fi

if [ "$INTEG_CONFIG_COUNT" -ne 22 ]; then
  echo "FAIL: config_startup test count mismatch: expected 22, got $INTEG_CONFIG_COUNT" >&2
  exit 1
fi

echo "All 9 Rust test target invariants verified successfully."
exit 0
