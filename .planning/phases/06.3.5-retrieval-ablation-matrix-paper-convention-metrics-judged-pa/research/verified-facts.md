# Verified facts for Phase 06.3.5 (ground truth for research, planning and plan checking)

The orchestrator read every fact below from source on 2026-10-06. Treat them as ground truth.
Cite `path:line` when you use one. Mark anything the phase adds as **PROPOSED**. When a fact
here and your own reading of the code disagree, say so explicitly: do not silently pick one.

- **Part A** was first verified during `/gsd-ai-integration-phase 06.3.5` (judge, scoring, official
  script). It is carried over unchanged, except that one class name is corrected (`EvalSettings`).
- **Part B** was added for `/gsd-plan-phase 06.3.5` (engine, wire, gateway, harness arm surface).

No source code has changed since Part A was written. The only commits since then touch
`.planning/`.

---

## Part A: judge, scoring, agreement, official script

### Judge (`eval/src/lancet_eval/judge.py`)
- `JUDGE_PROMPT_VERSION = "v1"`. The `JUDGE_SYSTEM_V1` rubric scores two dimensions on 1-5:
  - **Groundedness:** 5 = every claim is supported; 3 = the core is supported but details are not; 1 = the central claims are unsupported.
  - **Faithfulness:** 5 = no contradiction, overstatement or outside knowledge; 3 = overstates certainty or drops qualifiers; 1 = contradicts the evidence or answers from priors.
  - The prompt says NOTHING about abstentions, "Insufficient information", meta-statements about the evidence, or the final `Answer:` line.
- `JudgeVerdict(BaseModel)` has these fields, with `extra="ignore"`:
  - `groundedness: Score5` and `faithfulness: Score5`, where `Score5 = Annotated[int, Field(ge=1, le=5)]`;
  - `unsupported_claims: list[str]` (max 10);
  - `rationale: str` (max 600).
- `judge_once(client, *, api_key, model, question, answer, evidence, prompt_version, endpoint, temperature, max_tokens, max_reasks=1)`:
  - returns `(verdict|None, error|None, usage|None)`;
  - empty evidence returns `(None, "no evidence returned; groundedness undefined", None)`;
  - uses `response_format` `json_object`, with one bounded re-ask on a validation failure.
- `truncate_evidence(citations)` takes `structured_citations` excerpts in wire order.
  - Budgets: `PER_PASSAGE_CHAR_BUDGET` 1500 and `EVIDENCE_CHAR_BUDGET` 12000.
  - Overflow appends `"[TRUNCATED: n further passages omitted]"`.
- `cache_key = sha256(prompt_version \x1f judge_model \x1f question \x1f answer \x1f post_truncation_evidence)`.
  **The arm is not in the key**, so two arms with the same answer and evidence share one cache entry.
- `JudgeCache(path)` is a plain JSON file, `judge_cache.json`, in the run directory.
- Judge config, from `eval/corpora/multihop_rag.toml` and `multihop_rag_diag.toml` `[models]`:
  - `judge_model "meta-llama/llama-3.3-70b-instruct"`, temperature 0.0, `max_tokens` 400, `judge_prompt_version "v1"`;
  - `sample_seed` 42 is in `[questions]`.
  - The class default `judge_model` is `"openai/gpt-4o-mini"` on `EvalSettings` (`eval/src/lancet_eval/config.py:54`, field at `:72`). The TOML overrides it. The class is `EvalSettings`, NOT `EvalConfig`. `EvalConfigError` is an exception at `config.py:15`.

### Scoring (`eval/src/lancet_eval/score.py`, 1669 lines)
- `_is_judgeable(rec, gold_map)` (`score.py:141`) is true when gold exists for the `question_id` AND
  `structured_citations` is non-empty.
  - `gold_map` is built from ALL sampled questions, including null questions, so today a null question
    with citations is judgeable.
- `score_run(*, run_dir, no_judge=True, sample=None, emit_calibration_worksheet=None, calibration_file=None, api_key=None, client=None, stage_spend_cap=None) -> CorpusReport` (`score.py:191`).
- **Arms are hard-coded:** `records_by_arm: dict[str, list[RunRecord]] = {"graph-on": [], "graph-off": []}` (`score.py:287`).
  - Records with any other `graph_arm` value are silently dropped (`score.py:289-290`).
  - Records are deduplicated per `(question_id, graph_arm)` (`score.py:244`, `pairing.py:57-64`).
  - The provenance check applies only to `arm == "graph-off"` (`score.py:322`, `:412`).
  - `_check_provenance` (`score.py:128-138`) requires a `GRAPH_ABLATION` notice and no `GRAPH_UNAVAILABLE`.
  - The primary arm falls back to graph-off (`score.py:419-420`).
- **Only one arm is judged.** The judge loop, the cached-verdict count and the calibration worksheet all
  use `p_records`, the "primary arm" (graph-on preferred, else graph-off). The other arm is never judged.
- **Judging and judged aggregates happen in the same `score_run` call.**
  - `--emit-calibration-worksheet` requires judging to be enabled (it raises `ScoreError` under `no_judge`).
  - That same call rewrites `report.json` with judged aggregates.
  - So today, D-113's "the owner scores before any judged aggregate is shown" cannot hold.
- **Worksheet layout:**
  - The header row is `{type, corpus, judge_prompt_version, judge_model, generated_at}`.
  - The body is the FIRST 20 judged, judgeable, cached records of `p_records`, in journal order (`score.py:959-980`). The draw is not seeded and not stratified.
  - Each row has `question_id, query_type, cache_key, question, answer, evidence, human_groundedness=None, human_faithfulness=None`.
  - The verdict is not in the row, but `cache_key` is, and `judge_cache.json` is in the same run dir. One lookup reveals the verdict, so the worksheet is not truly blind.
- **Calibration ingest:**
  - The header's prompt version must match.
  - Human scores must be ints in 1..5 for BOTH dimensions.
  - Rows are joined to verdicts by `cache_key`. Unmatched rows are counted as excluded.
  - Per dimension it computes: exact-match rate, MAD, QWK (`quadratic_weighted_kappa`, min 1, max 5), Spearman, and bootstrap CIs.
  - The CIs come from `bootstrap_agreement_ci(..., seed=config.sample_seed)` WITHOUT `b`, so b = 1000, the function default.
- **`calibration_state`, per dimension:**
  - SATISFIED iff kappa >= `AGREEMENT_TARGET` AND spearman >= `AGREEMENT_TARGET`;
  - BELOW_TARGET otherwise;
  - NONE when there are no scores.
  - `AGREEMENT_TARGET = 0.70` is in `gate.py`, together with `CALIBRATION_SIZE = 12`, `STAGED_SIZE = 50` and `STAGED_PAIRING_COVERAGE_FLOOR = 0.80`.
  - This existing gate is NOT D-114's floor. D-114/D-119 is a per-dimension QWK point estimate only, as a new constant in `thresholds.py`.

### Agreement (`eval/src/lancet_eval/agreement.py`)
- `quadratic_weighted_kappa(r1, r2, *, min_rating=1, max_rating=5) -> AgreementResult(value|None, state)`. The state is `"computed"` or `"undefined_expected_agreement"`.
- `spearman_rank_correlation(r1, r2)` uses mid-rank ties and returns an `AgreementResult`; the undefined state is `"undefined_zero_variance"`.
- `bootstrap_agreement_ci(r1, r2, metric 'kappa'|'spearman', *, min_rating=1, max_rating=5, seed=42, b=1000) -> (lo, hi) | None`. It takes the 2.5/97.5 percentiles over row resamples and drops undefined resamples.

### Stats
- `stats.py` has `BOOTSTRAP_B = 10_000`; `bootstrap_mean_ci(b=BOOTSTRAP_B)`.
- `pairing.py` `compute_paired_delta` defaults to `b=BOOTSTRAP_B`.
- `unpark_gates` paired deltas use B=10000, seed 42.

### `thresholds.py`
- It holds committed constants with provenance comments. The pattern is a comment, then the constant:
  `# 06.3.4.1 D-xx: committed before paid drive N (AI-SPEC §5 #k).` then `NAME: type = value`.
  The most recent example is `COMMITTED_DECAY_THRESHOLDS_06341`, which carries a `provenance=` string.
- Existing constants: `COMMITTED_THRESHOLDS` (`DecisionThresholds`), `GRAPH_YIELD_INVESTIGATION_FLOOR` 0.20,
  `CITATION_REJECTION_TRIPWIRE` 0.159, `VECTOR_BASELINE_USABLE_FLOOR` 0.512, `GRAPH_PRESENCE_WILSON_LOWER_FLOOR` 0.098,
  `GRAPH_COMPOSITION_CHANGE_FLOOR` 0.10, `SC5_VISIBILITY_RULE`, `UNPARK_GATE_COVERAGE_FLOOR` 0.80.
- There is NO judge-agreement floor in `thresholds.py` yet, and no `PREREGISTRATION_06_3_5` yet (D-119, D-123: PROPOSED).

### Journal record shape (`eval/runs/2026-10-06-drive2-multihop_rag_diag/journal.jsonl`)
- Record keys: answer, corpus, correlation_id, duration_ms, error, error_type, graph_arm ("graph-on"|"graph-off"),
  index_generation, node_failures, node_timings, notices, outcome, partial, question_id, session_id, snapshot,
  structured_citations, workflow_meta.
- Snapshot keys, as the harness sees them through the gateway DTO: index_generation, embedding_model,
  vector_weight, bm25_weight, rrf_k (60), candidate_limit (32), final_limit (8), active_filter, result_hash,
  retrieved_chunks.
  - `retrieved_chunks` holds the final 8. Each carries chunk_id `"<document_id>:<n>"`, document_id, title,
    section_path, excerpt, is_truncated, score, rank, content_type and graph_boosted.
  - `variant_count` and `variant_identities` are NOT on the gateway JSON (see B.4).
- `structured_citations` items carry chunk_id, document_id, title, section_path, excerpt, is_truncated, score,
  rank, content_type and graph_boosted.
- **Answer shape** (drive-1b/2 prompt, D-71): multi-sentence prose with `[n]` markers and meta-statements, for
  example "Evidence [2]... were checked but do not directly address the comparison.". It ends with a final
  line `Answer: <short>`.
- **Drive-2 final-line census** (both arms, about 100 questions each):
  - `Answer: Insufficient information`: 40 graph-off and 39 graph-on, ALL with non-empty citations, so all judgeable today;
  - `Answer: Yes`: 18 and 18;
  - named entities otherwise;
  - 2 graph-on records with an empty answer and no citations.

### Gold chunk mapping
- `.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/diagnostic/post-reconcile/gold_chunks.jsonl`
  has 1185 rows, one per `(question_id, evidence_index)`: `{question_id, evidence_index, title, document_id, state, chunk_ids}`.
  - `state` is `"in_chunk"` for 1136 rows (1133 with one chunk_id, 3 with two).
  - `state` is `"split_across_chunks"` for 49 rows, which have empty `chunk_ids`.
  - It covers 447 question_ids, including all 398 G and 291 V questions (`populations.json`).
- Questions (`eval/corpora/multihop_rag/questions.sample.jsonl`): `{query, answer, question_type (comparison_query|inference_query|temporal_query|null_query), evidence_list[{title, author, url, source, category, published_at, fact}]}`.

### Official MultiHop-RAG script (pinned)
- Repo `yixuantt/MultiHop-RAG`, commit `c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8`, file `retrieval_evaluate.py`:
  `https://github.com/yixuantt/MultiHop-RAG/blob/c1c1287aa60a94acf9c4d20c891c9cd611a0f6e8/retrieval_evaluate.py`.
  - **Its licence has NOT been checked. Do not vendor it into the repo.** The AI-SPEC directs committing
    precomputed golden vectors instead.
- `calculate_metrics(retrieved_lists, gold_lists)`:
  - Strips ALL spaces and newlines from gold facts and retrieved texts (`.replace(" ", "").replace("\n", "")`).
  - Iterates `retrieved[:11]` with rank starting at 1. An item is relevant iff `any(gold_item in retrieved_item for gold_item in gold)`.
    That is fact-in-chunk matching: the gold FACT text must be a substring of the retrieved CHUNK text. It is not document level.
  - **Hits@10 / Hits@4:** a query is a hit if any relevant item is at rank <= 10 / <= 4.
  - **MRR@10:** 1 / first relevant rank (<= 10), else 0.
  - **MAP@10 (NON-STANDARD):** for each relevant rank r <= 10, count the gold facts found in this item that
    were NOT found at an earlier rank (the `find_gold` list) and add count / r. AP = sum / min(len(gold), 10).
    Standard AP would use cumulative hits / r; this script uses new facts at this rank / r.
  - All four are averaged over `len(gold_lists)`.
- `main_eval`:
  - skips `question_type == 'null_query'`;
  - the retrieved list is `[m['text'] for m in d['retrieval_list']]`;
  - gold is `[m['fact'] for m in d['gold_list']]`;
  - the denominator is every non-null query in the file.
- **Mapping to lancet:** "gold fact in retrieved chunk" ≡ the retrieved chunk_id is in `gold_chunks.jsonl`'s
  `chunk_ids` for that `(question_id, evidence_index)` with state `in_chunk`.
  - A `split_across_chunks` fact has no chunk_ids and can never be a substring of one chunk, so it never
    matches under either rule. The two rules agree there.
  - **Possible divergence:** the same fact text in a chunk not listed in `gold_chunks` (for example a duplicate
    article). The ID rule would miss it and the text rule would count it.
  - Ranks 9-10 exist only in the D-100 ID-only ranking field, which has no text. So at @10 the ID rule is the only option.
- Hits@4 can be computed from `snapshot.retrieved_chunks` (the final 8). Hits@10, MRR@10 (ranks 9-10) and
  MAP@10 need the D-100 pre-truncation list (up to 32, IDs and ranks only).

---

## Part B: engine, wire, gateway, harness (added for plan-phase)

### B.1 The byte-identity golden is fusion-level only
- `engine/src/retrieval/testdata/graph_off_fusion.golden` is read by exactly ONE test,
  `graph_off_fusion_is_byte_identical_to_the_recorded_pre_change_output`
  (`engine/src/retrieval/tests.rs:1465-1476`). It was recorded at HEAD `8899b6b5`, before the graph list existed (`tests.rs:1309-1315`).
- Its scenarios (`tests.rs:1397-1463`) call the pure functions `fuse_candidates` and `fuse_cross_variant_candidates`
  on synthetic `pin_candidate` lists, with `pin_settings()` = candidate_limit 12, final_limit 8, vector_weight 1.0,
  bm25_weight 0.75, rrf_k 60.0 (`tests.rs:1342-1351`).
  - **It does NOT exercise `RetrieveHybridNode`.** It cannot by itself prove that the default request through
    the node (SC-1, D-99) or the flag-on ranking field (D-100) leaves the node's output byte-identical.
  - That needs a node-level (or workflow-level) pin with fake ports. The test fixtures for that already exist (B.3).
- Note: the scenarios already fuse `fuse_candidates(vec![], bm25_list, ...)` (`tests.rs:1417-1442`), which is how
  variants 1..n look today (empty dense list).

### B.2 What `RetrieveHybridNode` does today (`engine/src/workflow/nodes/retrieve.rs`, 588 lines)
- **Dense runs once, for variant 0 only.** `dense_port.retrieve_dense(&ctx.original_query, embedding, ctx.filter.as_ref(), cancel)`
  (`retrieve.rs:197-241`). A failure adds `NoticeCode::RetrievalDegradedDense` and degrades to an empty list.
- **BM25 runs once per variant** (`retrieve.rs:256-316`). A failure adds `NoticeCode::RetrievalDegradedBm25` and degrades to empty.
- **Per-variant fusion:** `fuse_candidates(vector_candidates, bm25_candidates, &self.settings)` (`retrieve.rs:322-335`).
  Variant 0 gets the dense list; variants 1..n get `Vec::new()` for dense (`retrieve.rs:266-270`).
- **Cross-variant RRF:** `fuse_cross_variant_candidates(per_variant_fused, graph_candidates, &self.settings)` (`retrieve.rs:338-353`).
- **Graph list (D-76):** `fetch_graph_candidates` (`retrieve.rs:509-567`) reads graph chunk rows through
  `dense_port.fetch_chunks_by_id`.
  - This is a LanceDB row fetch, not a dense search.
  - It returns empty when there is no dense port, `ctx.graph_chunk_candidates` is empty, or `graph_rrf_weight == 0.0`.
- **Reranker:** `reranker.rerank(fused_candidates)` (`retrieve.rs:355-368`). Production uses a NoOp reranker.
- **Truncation:** `.take(self.settings.final_limit)` (`retrieve.rs:370-373`). This is where the full fused ranking
  (up to `candidate_limit`) is lost. D-100's ranking must be captured from `final_fused` before this `take`.
- **`result_hash`:** blake3 over the taken chunk_ids, each followed by `\x00` (`retrieve.rs:375-379`).
- **Snapshot:** the snapshot is seeded at `retrieve.rs:180-193` (the partial-snapshot path, D-33) and completed at
  `retrieve.rs:421-434`. Both are full `RetrievalSnapshot { .. }` struct literals.
- **Sub-stage timings** (`dense_ms`, `bm25_ms`, `graph_fetch_ms`, `fusion_ms`, `total_ms`) are in `RetrieveSubStageReport` (`retrieve.rs:47-62`).
- **`FusedCandidate`** (`engine/src/retrieval/fusion.rs`) carries `candidate` (chunk_id, document_id, ...),
  `fused_score`, `vector_rank`, `bm25_rank`, `vector_score`, `bm25_score` and `variant_provenance`
  (`variant_index`, `source`, `rank`, `score`, `contribution`). See the fields rendered at `tests.rs:1354-1386`.

### B.3 The query embedding is computed in the GRAPH node, before retrieval
- `ExtractGraphContextNode::run` (`engine/src/workflow/nodes/graph_context.rs:56-105`):
  - computes `ctx.query_embedding` via `embedder.embed_variant_zero(variant_zero, cancel)` at `:73-93`. This runs
    **on every request, graph on or off**, because dense retrieval needs it;
  - an embedding failure returns `Err`, which fails the node and the query;
  - **only after that**, if `ctx.disable_graph_context`, it adds `NoticeCode::GraphAblation`
    ("Graph context disabled by caller request", Info) and returns early (`:95-105`).
- **Open design point for D-99:** `bm25-only` "never calls the dense port", but as the code stands it still pays the
  query-embedding call, with its latency, cost and failure mode, unless the graph node also learns `retrieval_mode`.
  The research must state which reading D-99 needs and recommend one. Context: D-99 says per-arm latency and cost
  must "show the real cost of each path".
- **Test doubles** (`engine/src/workflow/ports.rs`, all `#[cfg(test)]`, every one counts calls via `.calls()`):
  `FakeQueryEmbeddingPort` (`:209`), `FakeGraphQueryPort` (`:322`), `FakeDenseRetrievalPort` (`:404`, which also
  records `fetch_requests()`), `FakeBm25RetrievalPort` (`:502`, with a per-query map) and `FakeReranker` (`:579`).
  - Node-level `RetrieveHybridNode` tests already use them: `engine/src/retrieval/tests.rs:921`, `:1222`, `:1265`, `:1297`.
  - Workflow-level tests through `WorkflowRunner` use them in `engine/src/tests/workflow_phase5.rs` (for example `:368`)
    and `engine/src/tests/graph_wire.rs:110-122`.
  - "dense-only never calls BM25" is therefore directly assertable as `fake_bm25.calls() == 0`.

### B.4 Request flow and the hand-mapped gateway
- **Engine admission:**
  - `WorkflowContext::new` (`engine/src/workflow/mod.rs:136-176`) resolves `disable_graph_context: request.disable_graph_context.unwrap_or(false)` at `:142`.
  - The field is declared at `mod.rs:83-86`.
  - `service.rs:943` also reads it into an unused `_disable_graph_context`.
  - The engine proto Rust type is `QueryRagRequest`; the proto message is `QueryRAGRequest`.
- **`derive_degraded_mode`** (`mod.rs:276-308`) is an EXHAUSTIVE `match` on `NoticeCode`. A new notice code is a
  compile error until it is placed in the included (degraded) or excluded set. `GraphAblation` is in the excluded set (`:298-303`).
- **Gateway request:** `ragQueryRequestBody` (`gateway/main.go:530-539`) hand-declares each JSON field, and the
  decoder uses `dec.DisallowUnknownFields()` (`main.go:656`).
  - **A harness that sends `retrieval_mode` before the gateway knows it gets HTTP 400.**
  - The JSON is mapped to `pb.QueryRAGRequest` by hand at `main.go:678-683`.
  - The existing pin test sends `"disable_graph_context":false` and asserts `receivedReq.DisableGraphContext` is `&false` (`gateway/main_test.go:4393-4410`).
- **Gateway response DTO** (`gateway/internal/sse/dto.go`):
  - `RetrievalSnapshotDTO` (`dto.go:56-67`) hand-maps exactly 10 keys.
  - `ToRetrievalSnapshotDTO` (`dto.go:108-142`) says `variant_count` and `variant_identities` "are deliberately
    omitted to preserve the exact 10-key payload contract asserted across gateway tests".
  - The snapshot key set is pinned in `gateway/main_test.go:2837` and `:2919`.
  - Notices pass through generically as `NoticeDTO{code, message, severity, typed_code}` (`dto.go:42-47`, `:160-171`).
  - `extractNoticeCodes` (`main.go:543-568`) names a code via `pb.NoticeCode(n.TypedCode).String()`. A stale
    vendored `.pb.go` would print the bare number.
- **Gateway metadata maps:**
  - `WorkflowMetadata` is hand-mapped twice in `gateway/internal/sse/sse.go`: the success map around `:130` and the fallback map around `:150`.
  - The metadata key set is pinned at `gateway/main_test.go:3008` and `:4488`.
  - The 06.3.4.1-16 precedent: "every new key is mapped explicitly in both gateway maps and named by a Go test and a `main_test.go` key set".
- **Conclusion:** new request fields AND any new snapshot or metadata field need hand-written Go mapping, the DTO
  field, and pin tests. Nothing flows through automatically. A new NoticeCode flows through `NoticeDTO` without a DTO
  change, but needs the regenerated `.pb.go` for its string name.

### B.5 Proto: next free tags and the regeneration command (D-52 pattern)
- `proto/lancet/v1/lancet.proto`:
  - `QueryRAGRequest` uses tags 1-5. `disable_graph_context` is `optional bool` = 5 (`:53-67`). **The next free tag is 6.**
  - `NoticeCode` (`:72-102`) uses 0-5, 10-16, 18-22; 17 is `reserved` (`:92`). `NOTICE_CODE_GRAPH_ABLATION = 18`. **The next free value is 23.**
  - `RetrievalSnapshot` (`:141-155`) uses tags 1-12, with `retrieved_chunks = 12`. **The next free tag is 13.**
  - `StructuredCitation` (`:126-139`) uses 1-10. `WorkflowMetadata` (`:240-268`) uses 1-16.
- **Regeneration:** run `buf generate` from the repo root. `buf.gen.yaml` (v2) uses REMOTE pinned plugins:
  `buf.build/community/neoeinstein-prost:v0.5.0` and `neoeinstein-tonic:v0.5.0` (`no_client=true`) write to
  `engine/src/pb`; `buf.build/protocolbuffers/go:v1.36.5` and `buf.build/grpc/go:v1.5.1` (`paths=source_relative`) write to `gateway/proto`.
  - It needs network access to buf.build. `buf` 1.72.0 is on PATH on this machine.
  - The 06.3.1-01 and 06.3.4.1-16 precedents:
    - one `buf generate` writes both trees (`engine/src/pb/lancet/v1/lancet.v1.rs` and `gateway/proto/lancet/v1/lancet.pb.go`);
    - a second run must change nothing (`bash -c "buf generate && git diff --quiet -- engine/src/pb gateway/proto"`);
    - plugin versions are never bumped;
    - `git diff -- proto/` removes no line.
- **prost struct literals:** after regeneration, every hand-written struct literal of a changed message must name the
  new field, or the crate does not compile. This bit 06.3.1-01 (06.3.1-REVIEWS).
  - **CORRECTED 2026-10-06 after research, by brace-matching (`research/u4_literal_sites.py`, re-run by the orchestrator):**
    - **6** `RetrievalSnapshot` literals list every field and MUST be edited: `engine/src/workflow/nodes/retrieve.rs:180`
      and `:421`, `engine/src/retrieval/tests.rs:972`, `:1089` and `:1156`, and `engine/src/tests/workflow_phase5.rs:3067`.
    - **19** `QueryRagRequest` literals ALL end in `..Default::default()` (the `engine/src/testkit.rs` shim) and need no edit.
  - The earlier raw grep counts of 9 and 20 included fn signatures, return types and `CheckpointRetrievalSnapshot`.
    `cargo test --manifest-path engine/Cargo.toml --locked --no-run` after `buf generate` is the authority.
  - `optional` scalars become `Option<T>`, repeated fields become `Vec<T>`, and message fields become `Option<Msg>`.
    The new field still has to be named in every literal unless the literal uses `..Default::default()`.

### B.6 Harness arm surface (`graph-on`/`graph-off` literals in `eval/src/lancet_eval/`)
SC-2 names `run.py:60` and `unpark_gates.py:596`, but the literal appears in about 20 places. The arm registry change
(D-101) touches all of them, or explicitly routes them through the legacy alias:
- `run.py:59-63` `GRAPH_ARMS: dict[str, bool] = {"graph-on": False, "graph-off": True}`: "The sole durable
  arm-to-flag mapping". `drive_one` validates against it (`run.py:138-142`).
- `run.py:346-348` builds work units as `[(q, arm) for q in questions for arm in config.arms]`. That is already
  question-major (arms interleaved per question), but in the FIXED `config.arms` order. D-107 needs a seeded,
  balanced arm rotation. `--workers > 1` would reorder dispatch; the drive uses `--workers 1`.
- `corpus.py:137` reads `self.arms = list(data.get("arms", {}).get("arms", ["graph-on", "graph-off"]))` from `[arms] arms = [...]` in the corpus TOML.
- `cli.py:807-833` is the single-question `--arm` option, validated to `("graph-on", "graph-off")`. `cli.py:882` sets `disable_graph = arm == "graph-off"`.
- `measure.py:50` `MEASUREMENT_ARMS: tuple[str, str] = ("graph-off", "graph-on")`; `measure.py:341`.
- `preflight.py:54`, `:65` type `graph_arm` as `Literal["graph-on", "graph-off"]`. `preflight.py:862` sets
  `disable_graph = arm == "graph-off"`. The canary provenance check is at `preflight.py:961-969`.
- `pairing.py:102` `rec_off = arm_map.get("graph-off")`. Pairing is keyed on `graph_arm`.
- `score.py:287-290`, `:322`, `:412`, `:419-420` (see Part A).
- `dimensions.py:598`, `:687` (`r.graph_arm == "graph-on"`); `usability.py:91`.
- `unpark_gates.py:339`, `:596` (`graph_off = arms.get("graph-off")`, inside the `answer_usable` gate's exclusion
  count), `:897`, `:1019`, `:1335`, `:1473-1480`.
- `diagnostic.py:175-182`, `:476`, `:568`; `oi02.py:1052-1064`; `report.py:47` `arm_labels` default `["graph-on", "graph-off"]`.
- `journal.py:105` declares `graph_arm: str` (free string). `journal_key(corpus, question_id, graph_arm)` (`journal.py:188-190`)
  is the resume key, so new labels work there unchanged.
- **Provenance today:** `_check_provenance` (`score.py:128-138`) and the canary check (`preflight.py:961-969`) look for
  `GRAPH_ABLATION` (typed 18 or string). `usability.py:71`, `:95` does the same.
- **Request side today:** `client.py:198-218` `run_query(client, *, query, session_id="", disable_graph_context=False, deadline_s=600.0, read_timeout_s=None, capture_raw_events=False)`
  POSTs JSON to the gateway's `/rag/query` (SSE) and sets `body["disable_graph_context"] = True` only when true.

### B.7 Dev corpus config, the template for a held-out corpus
- `eval/corpora/multihop_rag_diag.toml`:
  - `[documents] map_corpus = "multihop_rag"`, so it shares the multihop_rag index;
  - `[questions] file = "multihop_rag/questions.diag.jsonl"`, `sample_seed = 42`, `sample_size = 100`;
  - `[models]` holds the judge;
  - `[arms] arms = ["graph-on", "graph-off"]`.
- `drive()` (`run.py:300-348`) calls `require_index_identity(eval_settings, corpus)` (`eval/src/lancet_eval/identity.py:234-251`;
  it has no bypass), then `load_corpus_config(corpus)` and `load_sample_questions(corpus)`.
- Files present in `eval/corpora/multihop_rag/`: `canary.jsonl`, `diag_selection.json`, `document_map.json`,
  `documents.subset.jsonl`, `questions.diag.jsonl`, `questions.sample.jsonl`, `subset_selection.json`.

### B.8 Reading chunk text from the eval store
- `engine/src/bin/inspect_lancedb.rs` accepts `--document-id`, `--graph-population`, `--entity`, `--max-hops`,
  `--entity-name`, `--gold-chunks`, `--map`, `--document-ids` and `--lancedb-path` (`inspect_lancedb.rs:1163-1208`).
  - The 06.3.4.1 run used `--gold-chunks eval/corpora/multihop_rag/questions.sample.jsonl --map eval/corpora/multihop_rag/document_map.json --lancedb-path ./data/lancedb-eval`.
  - Whether an existing mode can emit full chunk TEXT for arbitrary chunk IDs at a given `index_generation`
    (needed by AI-SPEC §5/§6 item 5, the text-rule cross-check) is NOT verified here. The research must check it.
- Engine bins: `diag_probe.rs`, `inspect_lancedb.rs`, `reconcile_eval_store.rs`, `retrieval_soak.rs`, `seed_rag_fixture.rs`.

### B.9 Test-count invariants: new tests must bump them deliberately
- `scripts/engine-test-targets.sh` pins exact counts:
  - `TOTAL` 721 (`:279`), lib 637 (`:284`, `:289`), and `inspect_lancedb` 44;
  - each bump carries a history comment naming the plan and task (for example `#   721 -- Phase 06.3.4.1 plan 16 Task 1: ...`, around `:232`).
- `scripts/gateway-test-targets.sh` pins `EXPECTED_TOTAL=114` (`:20`) and a per-package distribution, `EXPECTED_PACKAGES` (`:25`).
  - It counts with `go test -list`, so no PostgreSQL is needed.
  - The latest history comment says 114 = Phase 06.3.1.
  - **CONFIRMED 2026-10-06 (the orchestrator re-ran it): the script FAILS TODAY.** It reports `TOTAL: 118` against the
    expected 114, and `gateway/internal/sse` 16 against 12. The drift is 4 sse tests from 06.3.4.1-16 (`f74f6b24`).
    `go test ./...` itself passes. A Wave-0 task must reset the script to 118 / sse 16, with a history comment, before
    any plan adds gateway tests.
- Prior phases ran these as `sh scripts/engine-test-targets.sh` and `cargo test --manifest-path engine/Cargo.toml --locked && sh scripts/engine-test-targets.sh`.
- The Python harness tests run as `uv run --project eval pytest <files> -x`, and the full suite as `uv run --project eval pytest -q`.
  Lint is `uv run --project eval ruff check --preview <files>`.
