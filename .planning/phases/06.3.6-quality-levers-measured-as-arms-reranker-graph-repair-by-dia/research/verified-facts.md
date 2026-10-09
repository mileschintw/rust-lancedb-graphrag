# Verified facts for Phase 06.3.6 (ground truth for research, planning and plan checking)

The orchestrator read every fact below from source at HEAD `73e449b0` on 2026-10-08/09, or fetched it
from the named external URL. Treat these facts as ground truth.

**Rules for using this file:**
- Cite `path:line` when you use a fact.
- Mark anything the phase adds as **PROPOSED**.
- Where a fact here and your own reading of the code disagree, say so explicitly. Do not silently pick one.
- Run any snippet you put in the spec, or label it "illustrative, not run".

**D-129 (binding on every agent).** Held-out numbers in `06.3.5-RUN-OF-RECORD.md` must not motivate any lever
parameter, margin, floor or threshold. The only held-out-informed choice in this phase is the *framing* of the
D-148 guards (the constant-Yes 0.64 vs `hybrid` 0.45 comparison-stratum quote). Derive everything else from dev
(drive-2, `eval/runs/2026-10-06-drive2-multihop_rag_diag/`) or from earlier committed rules.

---

## A. Reranker (lever 1, D-131..D-135)

### A1. The port has no query

`engine/src/rerank/mod.rs:11-16`:
```rust
pub trait Reranker: Send + Sync {
    fn rerank<'a>(&'a self, candidates: Vec<FusedCandidate>)
        -> BoxFuture<'a, Result<Vec<FusedCandidate>, RetrievalError>>;
}
```

- **The question is not passed.** A real cross-encoder reranker cannot work without it, so the signature must
  change (**PROPOSED**: add `query: &str`, or a request struct).
- **Implementors that must follow the change:**
  - `NoOpReranker` (`rerank/mod.rs:28`). It must stay order- and byte-preserving.
  - `RecordingReranker` (`engine/src/tests.rs:838`).
  - `FailingReranker` (`engine/src/tests.rs:871`).
  - `FakeReranker` (`engine/src/workflow/ports.rs:617`).

### A2. Wiring is one service-wide instance today

- `engine/src/main.rs:165` sets `reranker: Arc::new(rerank::NoOpReranker::new())` on `LancetServiceImpl`
  (field at `engine/src/service.rs:120`).
- `service.rs:159` builds `reranker_adapter = Arc::clone(&self.reranker)` per request, and
  `service.rs:170` passes `reranker_port: Some(reranker_adapter)` into `WorkflowDependencies`
  (`workflow/mod.rs:342`; `None` in `WorkflowDependencies::new()` at `:357`).
- `RetrieveHybridNode::new(dense, bm25, reranker, settings)` is called at `service.rs:196-200`.
- **So production always has `Some(NoOp)`.** Per-request selection (D-131: "the reranker is chosen per
  request") is a **PROPOSED** change at the `service.rs:159-170` construction site: it picks the
  OpenRouter reranker when `levers` contains the rerank value, else NoOp.

### A3. Capture, rerank and truncation order

From `engine/src/workflow/nodes/retrieve.rs:369-395`, in order:
1. **`:369-375`.** The D-100 `pre_truncation_ranking` is built from `fused_candidates`, before the reranker,
   via `ranked_candidates(&fused_candidates, self.settings.candidate_limit)`. It is built only if
   `ctx.include_pre_truncation_ranking`.
2. **`:377-391`.** `reranker.rerank(fused_candidates)`. On `Err`, it returns
   `NodeError::new(NodeErrorKind::RetrievalFailed, "Reranker failure: …")`.
3. **`:393-396`.** `.take(self.settings.final_limit)`. So the reranker receives the whole fused list
   (≤ `candidate_limit = 32`), and truncation to 8 comes after it.

**Consequence for D-133 (moving the capture to after the reranker):**
- Harness provenance clause (c) (`eval/src/lancet_eval/provenance.py:222-225`, `_prefix_details`) requires
  the ranking's first `final_limit` rows to equal `retrieved_chunks`.
- With the capture **before** the rerank, clause (c) would fail on every reranked record.
- With the capture **after** the rerank (D-133), clause (c) holds on the rerank arm unchanged.
- Under NoOp, both orders are identical.

### A4. Candidate content available to a reranker

`FusedCandidate` (`engine/src/retrieval/fusion.rs:48-56`) holds `candidate: Candidate` with:
- `content: String`, `title: Option<String>`, `document_id`, `chunk_id`, `chunk_index`;
- `section_path`, `content_type`, `embedding_model`, `ingested_at`, `score`.

Defined at `engine/src/retrieval/mod.rs:428-441`.

### A5. The rerank call sits inside the RetrieveHybrid node budget

From `config/config.toml`:
- **`[engine.workflow]`:** `query_embedding_timeout_ms = 2000` (`:71`), `retrieve_timeout_ms = 2500` (`:72`),
  `graph_operation_timeout_ms = 2424`, `graph_node_timeout_ms = 12500`.
- **`[engine.retrieval]`:** `candidate_limit = 32` (`:81`), `final_limit = 8` (`:82`).

How the budgets nest:
- **`config.toml:48`:** "retrieve (2500) is lifted to query_embedding (2000) + 500ms". Pass A's rule value was
  294 ms.
- **Nesting tests:** `engine/src/config.rs:1146-1165` (`workflow_budget_defaults_nest_and_pass_startup_validation`)
  asserts `retrieve_timeout_ms >= query_embedding_timeout_ms + 500` (`NESTING_SLACK_MS`, `:1069`).
- **Defaults must agree with the config files:** test `workflow_budget_defaults_agree_with_config_files`.

**Consequence:**
- A network rerank inside `RetrieveHybrid` that overruns the node budget fires the **node** timeout. That
  yields a failure, not D-134's degrade-with-notice.
- So D-135's derived rerank timeout must nest inside `retrieve_timeout_ms`, leaving room for the node's own
  search time.
- If the derived value does not fit, `retrieve_timeout_ms` must move. That is a ceiling shared by **every
  arm**, the reference included. It is an owner-visible change, and it must be in the D-154 freeze commit,
  before the held-out cap checkpoint. The config tests above move with it.

### A6. The 06.3.3 derivation rule (D-135 applies it)

From `06.3.3-…/06.3.3-BUDGETS.md:5`:
- **Committed rule:** `proposed_ms = ceil(p95 × multiplier + allowance)`, with `multiplier = 1.5`,
  `derivation_percentile = 0.95`, `allowance_ms = 0` and `slack_ms = 500` (nesting).
- **Censoring status is recorded per budget.** A censored-from-above sample gives a lower bound, not a
  percentile (`06.3.3-BUDGETS.md:34`, `graph_operation` row).

### A7. OpenRouter rerank: fetched 2026-10-09 ~06:06 UTC

Copies are in `research/fetched/`.

**Model listing.** `GET https://openrouter.ai/api/v1/models?output_modalities=rerank` (no auth) returns 9 models,
`voyageai/rerank-2.5-lite` among them.
- File: `fetched/openrouter-rerank-models-2026-10-09.json`, sha256 `4991ef55…c2c` (pretty-printed copy).
- `canonical_slug` is `voyageai/rerank-2.5-lite-20260727`, `context_length` is 32000, and modality is
  `text->rerank`.
- **`pricing.prompt` and `pricing.completion` are both `"0"`.** The listing does **not** expose a rerank price.
  The endpoint detail (`/api/v1/models/voyageai/rerank-2.5-lite-20260727/endpoints`) shows the same 0/0,
  provider "VoyageAI by MongoDB", and uptime 100.
- The plain `GET /api/v1/models` (469 chat models) does **not** list rerank models.

**Endpoint shape.** From the OpenAPI spec `POST /rerank` on server `https://openrouter.ai/api/v1`, fetched from
`https://openrouter.ai/docs/api/api-reference/rerank/submit-a-rerank-request.md` (file
`fetched/openrouter-submit-a-rerank-request-2026-10-09.md`, sha256 `f8d3629d…e806`):
- **Request:** `{model, query, documents: [string | {text, image}], top_n?, provider?, session_id?, user?}`.
  `model`, `query` and `documents` are required.
- **200 response:** `{id, model, provider?, results: [{index, relevance_score, document:{text}}], usage:{cost?, search_units?, total_tokens?}}`.
  `results` is "sorted by relevance". `index` is the position in the input list. `usage.cost` is "Cost of the
  request in credits".
- **Errors:** 400, 401, 402 (insufficient credits) and 503. **No streaming.**
- **Auth:** the security scheme is `apiKey`, a bearer token, the same OpenRouter key the engine uses for
  generation.

**Unauthenticated probes:**

| Request | Status |
|---|---|
| `POST /api/v1/rerank` | **401** |
| `POST /api/v1/nonexistent-xyz` | **404** |
| `POST /api/v1/embeddings` | 401 |

So the route exists and requires auth.

**Voyage direct pricing** (`https://docs.voyageai.com/docs/pricing`, fetched 2026-10-09):
- rerank-2.5-lite costs **$0.02 / 1M tokens**, and the first 200M tokens are free per Voyage account.
- Billed tokens = query tokens × number of documents + the sum of document tokens.
- **Not verified:** that this price or allowance applies through OpenRouter.

**STATUS of D-131's verification gate:**
- **Verified:** the model is served on the rerank route, the endpoint shape, and the auth path (bearer key,
  401 without).
- **NOT verified:** an authenticated 200 for this model, and the price actually billed through OpenRouter.
  The orchestrator did not spend money.
- **So the plan must close this first.** A sub-cent authenticated probe (2 documents) must run before any
  lever-1 code is committed. It records the status, `usage.cost` and latency. If it fails, D-131 stops and the
  owner is asked (no fallback).
- **Spend reconciliation** reads `usage.cost` from each response. Do **not** hard-code a constant from the
  listing (0/0) or from Voyage-direct pricing.
- **Rough order of magnitude, illustrative and not run:** 32 documents of ~a few hundred tokens each is
  ~10–20k billed tokens per query. At $0.02/1M that is ~$0.0003 per query. Two rerank-bearing arms × 351 is
  ~700 calls, ~$0.2.

---

## B. Wire contract (D-136)

**`proto/lancet/v1/lancet.proto` `QueryRAGRequest` (`:64-90`):**

| Field | Number | Notes |
|---|---|---|
| `query` | 1 | |
| `session_id` | 2 | |
| `filter` | 3 | |
| `optional bool allow_model_only` | 4 | |
| `optional bool disable_graph_context` | 5 | |
| `RetrievalMode retrieval_mode` | 6 | plain enum, 0 = UNSPECIFIED = HYBRID |
| `bool include_pre_truncation_ranking` | 7 | |

The next free field number is **8**.

**Other messages:**
- **`RetrievalSnapshot` (`:174-192`)** goes up to field 14, `pre_truncation_ranking`. Field 13 is the
  `retrieval_mode` echo. So the `levers` echo is **PROPOSED** as field 15.
- **`NoticeCode` (`:92-…`)** already has values 1–5 and 10–15+. A new `RERANK_DEGRADED` (D-134) and a
  query-embedding retry event (D-152) are **PROPOSED** additions. Notice codes are derived from the enum by one
  mapping function (D-76 comment at `:89-91`).

**`WorkflowContext` (`engine/src/workflow/mod.rs:80-…`):**
- It holds `disable_graph_context`, `retrieval_mode` and `include_pre_truncation_ranking`, each resolved once
  at admission.
- `levers` joins these (**PROPOSED**).

**D-52 regen:** `buf.gen.yaml` writes `engine/src/pb` and `gateway/proto` (vendored
`gateway/proto/lancet/v1/lancet.pb.go`).

**Ingest needs no proto change.**
- `IngestDocumentRequest` (`lancet.proto:24-29`) already has `map<string,string> metadata = 4`.
- The gateway fills it with only `chunk_strategy`, `chunk_size` and `chunk_overlap`
  (`gateway/internal/engineclient/engineclient.go:88-95`).
- `eval/src/lancet_eval/seed.py:430-438` uploads only a multipart `file` part named
  `_sanitize_filename(corpus_id)` (`seed.py:353-358`: non-`\w-_.` → `_`, max 60 chars, then `.txt`).
- **So D-144's "ingestion learns the fields" needs:**
  - `seed.py` to send the fields;
  - the gateway's multipart handler to forward them into `metadata`;
  - the engine to persist them.
- **The only new proto field in this phase is `levers`** (plus the snapshot echo and notice codes).

---

## C. Evidence metadata (lever 3, D-142..D-145)

### C1. Store schemas

- **`documents_schema()` (`engine/src/db/mod.rs:214-219`)** has only `document_id` and `raw_content`
  (Binary). It has no metadata columns.
- **`nodes_schema()` (`db/mod.rs:221-243`), the chunk table:**
  - `document_id`, `chunk_id`, `chunk_index`, `char_start`, `char_end`, `content`, `embedding`;
  - `token_estimate`, `token_estimate_scheme`, `token_estimate_version`;
  - `title` (nullable), `section_path`, `page_start`, `page_end`, `content_hash`, `chunker_version`;
  - `embedding_model`, `ingested_at`, `content_type`.
- Table set (`db/mod.rs:322-332`): communities, documents, edges, entities, entity_edges, nodes,
  staged_documents_v2.

### C2. `nodes.title` feeds retrieval

**Do NOT overwrite it.**
- **BM25** indexes it with `title_boost = 2.0` (`config/config.toml:100`; `engine/src/retrieval/bm25.rs:134,181,204,273`).
- **The dense projection** reads it (`engine/src/retrieval/dense.rs:33,227`) into `Candidate.title`.
- That becomes the prompt `<TITLE>` (`engine/src/prompt.rs:44,50`) and `StructuredCitation.title`.
- **So the real title must go in a NEW column** (**PROPOSED**, e.g. `doc_title`), next to `source` and
  `published_at`.
- Overwriting `title` would change BM25 on every arm, which breaks D-145 and comparability with 06.3.5.

### C3. Today's prompt evidence block

From `engine/src/prompt.rs`:
- **`EvidenceBlock::from_candidate` (`:41-…`).** `title` falls back to "Untitled Document" and `section` to
  "Root". The `provenance` string is `document_id=…, chunk_index=…, title="…", section="…"`.
- **`EncodedEvidence::render_prompt_block` (`:89-95`)** renders
  `<EVIDENCE id suspicious><TITLE><SECTION><PROVENANCE><CONTENT_TYPE><TEXT>`.
- **`encode_evidence_block` (`:98-…`)** entity-escapes every corpus-controlled field.
- **`base_system_policy()` (`:212-224`)** is one pinned string. It already says
  "Answer: <the shortest answer: yes, no, an entity name, or a short phrase>" and the
  "Answer: Insufficient information" rule. Its byte-identical prefix tests are at `prompt.rs:708-790`.

### C4. Corpus metadata

From `eval/corpora/multihop_rag/documents.subset.jsonl`:
- **346 documents.** Keys: author, body, category, published_at, source, title, url.
- **Missing values:** title 0, source 0, published_at 0, category 0, url 0. So in the eval corpus the
  "missing field" path of SC-4 is exercised only by unit tests, never by data.
- **Examples:** `published_at` looks like `'2023-10-07T15:37:43+00:00'`, and every document is from 2023.
  `source` is a full publication name (e.g.
  `'Business Today | Latest Stock Market And Economy News India'`). There are 44 distinct sources.
- **Titles are HTML-entity-escaped** in the JSONL (e.g. `&#039;`).

**Join key for the backfill:**
- `eval/corpora/multihop_rag/document_map.json` has `{corpus, seeded_at, index_generation, entries, aliases}`.
- `entries` has 346 rows keyed by gateway `document_id`, each `{corpus_id, document_id, title, url}`.
- `corpus_id` is the JSONL `title` string (`seed.py:408-410`: `title or url or id`).
- So the backfill is `document_id → entries[].corpus_id → JSONL row by title`. **PROPOSED:** verify that the
  join is 1:1, with 346 of 346 matched, as a test.

---

## D. Index generation (D-144, D-159, SC-6)

- **Derivation.** `engine/src/workflow/ports.rs:16-18`:
  `corpus_generation_from_nodes_version(v) = format!("lance-{v}")`.
  - The generation is the **`nodes` table's Lance version only**.
- **When it changes:**
  - It is set in `rebuild_and_swap_with_graph_builder` (`engine/src/ingest.rs:1596-1760`, new snapshot at
    `:1743-1749`).
  - The graph index is built in memory from the db there (`graph::index::GraphIndex::build`, `:1585`).
- **What bumps it and what doesn't:**
  - A column backfill on `nodes` writes a new Lance version, so the generation bump is **automatic**.
  - D-138 side tables (new entity/edge tables) do **not** change `nodes_version`. If ER is selected, SC-6
    needs the side-table versions recorded next to the generation (**PROPOSED**).
- **The running engine pins dense checkouts** to its snapshot's `nodes_version`
  (`service.rs:615`, `nodes.checkout(self.nodes_version)`), and the snapshot is rebuilt only on the ingest
  path.
  - So after an out-of-band backfill the engine must be **restarted**, or a rebuild triggered, before any
    `evidence_metadata` or `graph_v2` read.
  - **PROPOSED:** make the restart an explicit step in the D-159 order, followed by a check that the
    snapshot's `index_generation` equals the post-backfill value.
- **The eval store is `lance-702` today** (06.3.5 run of record, CONTEXT D-144).

---

## E. Query-embedding retry (D-152)

- **`engine/src/workflow/nodes/graph_context.rs:78-97`:**
  - one `tokio::time::timeout(self.embedding_timeout, embedder.embed_variant_zero(…))`;
  - on elapse, `NodeError::new(NodeErrorKind::Timeout, "Query embedding timed out")`, returned (node fails).
  - It is skipped only for an explicit `bm25_only` request with the graph off (D-125, `:73-77`).
- **Nesting with one retry:** 2 × 2000 + jitter + `graph_operation` 2424 + 500 slack ≈ 6.9 s + jitter, which is
  inside `graph_node_timeout_ms = 12500`.
  - **PROPOSED:** make startup validation account for the retry explicitly (`config.rs` nesting checks).

---

## F. Graph (lever 2, D-137..D-141)

- **`engine/src/graph/paths.rs`:**
  - `DEGREE_CAP = 33` (`:51`), `MAX_PATH_FACTS = 8` (`:72`), `MAX_PATH_FACTS_CEILING = 16` (`:84`).
  - **`rank_chunks(index, entities, cap)` (`:330-357`)** ranks the chunks that the path entities cite. Order:
    the number of citing entities, descending; then the earliest position in any entity's list; then the
    best entity rank; then `chunk_id`.
  - D-139 read 2 ("chunks cited by ≥ 2 path entities") is a filter on the first key of this ranking.
  - `seed_chunk_candidates` (`:367-375`) is offline only (`paths-only` was chosen 2026-10-05).
- **`EntityResolver` (`engine/src/db/mod.rs:334-341`):** `async fn resolve(&self, entity: &str, known_entities: &[String]) -> Result<Option<String>, String>`.
  - The only implementation is `ExactMatchResolver` (`:343-357`), an exact string match.
  - **It has no similarity or vector parameter.** A name-vector resolver (D-138) needs either a new
    implementation that holds an embedder, or a port change (**PROPOSED**).
- **Seed probe** (`06.3.4.1-…/diagnostic/seed_probe_summary.json`, dev, 100 questions):
  - question types: comparison 36, inference 31, null 10, temporal 23;
  - 454 seed matches: exact 365, normalized 1, vector 88;
  - `path_found` on 62 of 100.
- **The D-137 table inputs:**
  - `eval/runs/2026-10-06-drive2-multihop_rag_diag/` (journal.jsonl, report.json, diagnostic/);
  - `06.3.4.1-…/diagnostic/seed_probe.jsonl`, with per-question mentions and seeds (entity_id, match_kind,
    degree, source_document_ids).

---

## G. Harness (eval/src/lancet_eval)

### G1. Arm registry

`arms.py:27-75`:
- `ArmLabel = Literal["dense-only", "bm25-only", "hybrid", "hybrid+graph"]`.
- `ArmSpec(label, retrieval_mode, disable_graph_context, legacy_aliases)` is frozen, with `extra="forbid"`.
- **No `levers` field.** **PROPOSED:** add `levers: tuple[str, ...] = ()` and the D-149 labels.
- **`request_fields` (`arms.py:140-163`)** emits `retrieval_mode`, `disable_graph_context` and
  `include_pre_truncation_ranking=True` for canonical labels.

### G2. Provenance

`provenance.py:148-251`, clauses (a)–(g):
- **(a)** is the retrieval_mode echo, filtered by **substring** `if "retrieval_mode" in message` (`:203`).
  That is IN-04.
- **(b)** requires a ranking present and ≤ `candidate_limit`.
- **(c)** requires the ranking prefix to equal the final list.
- **(d)** is the per-mode rank shape. It holds that a graph-off arm has no `graph_rank`.
- **(e)** requires GRAPH_ABLATION present and GRAPH_UNAVAILABLE absent on graph-off arms (`usability.py:70-81`).
- **(f)** is the snapshot config (`rrf_k`, `candidate_limit`, `final_limit` and the weights).
- **(g)** is corroboration only.
- `is_ok(record)` (`:254-…`) = `is_usable` and no failure in (a)–(f).
- **PROPOSED:** a new clause for the `levers` echo, plus a RERANK_DEGRADED → off-arm rule (D-134).

### G3. Pre-registration

`thresholds.py:242-300`, `AblationPreRegistration` + `PREREGISTRATION_06_3_5`:
- `primaries=("paper_hits_at_4","answer_usable")`, `reference_arm="hybrid"`;
- **`comparison_arms` is ONE tuple shared by both primaries**: `("dense-only","bm25-only","hybrid+graph")`;
- `family="per_primary"`, `family_alpha=0.05`, `test="paired_sign_flip_exact_two_sided"`;
- `population="P4: … ok(r) on all four arms"`, `complete_case_floor=0.80`;
- `bootstrap_b=10_000`, `bootstrap_seed=42`.

**D-150 needs different comparison arms per family:**
- `answer_usable`: m = 4 or 3;
- Hits@4: rerank and graph-v2, m ≤ 2.

So the dataclass needs a per-family arm set (**PROPOSED**), or a new class for 06.3.6.

### G4. Metrics and pricing

- **`ABSTENTION_METRICS = ("abstention_rate_g", "null_abstention_correctness")`** (`comparison.py:182`).
  The null-abstention metric already exists.
- **Prices in `measure.py`:**
  - `JUDGE_INPUT_PRICE_PER_1M = 0.12` and `JUDGE_OUTPUT_PRICE_PER_1M = 0.30` (`:96-99`, comment
    "Recorded on 2026-09-10"). D-153 / carry-forward #5 re-checks these.
  - `GENERATION_*` at `:60-61` and `EMBEDDING_PRICE_PER_1M = 0.12` at `:64`.
  - **There is no rerank cost line.**

### G5. D-73 git gate

- Lives in `gitcheck.py` (06.3.5-08), and is used by `drive` and `judge_stage.py:192-216`.
- D-158 (WR-02 remainder) extends it to `compare`.

### G6. Preflight (IN-03)

`preflight.py:1326-1331`: `try: corpus_config = load_corpus_config(corpus_name) except Exception: corpus_config = None`. The legacy
canaries then run. That is the silent fallback IN-03 closes.

---

## H. Not verified by the orchestrator (agents must not state these as fact)

- An authenticated OpenRouter rerank 200, its billed price, and its latency distribution. See A7.
- The class split of the 38 drive-2 `GRAPH_UNAVAILABLE` questions (D-137). It is regenerated in-phase, and
  **no agent may pre-guess it**. §4/§5 must cover all three branches: ER, precision, neither.
- Whether a Lance `add_columns`/`merge` backfill on `nodes` preserves the existing FTS/vector indexes without
  a rebuild. **The planner must verify it on a copy before touching `data/lancedb-eval`.**

---

## I. Corrections and additions from the §3/§4 research pass (orchestrator spot-checked 2026-10-09)

These supersede the matching lines above where they conflict.

- **No per-request seam today.** `LancetServiceImpl::build_production_workflow(&self, snapshot)`
  (`engine/src/service.rs:133-136`) takes only the snapshot, so there is no per-request seam yet.
  - Per-request reranker selection needs this builder to take the request's lever set (**PROPOSED**), or the
    retrieve node to choose between two injected rerankers.
  - This corrects A2's "at the `service.rs:159-170` construction site".
- **The prompt packer re-sorts evidence by score.** `engine/src/prompt.rs:469` sorts the packed candidates
  descending by normalised score.
  - The evidence score is `candidate.fused_score` (`prompt.rs:68`).
  - So a reranker that only reorders the list, leaving `fused_score` untouched, mostly changes *which* 8
    survive truncation, not the prompt order. The §4 rerank design must say which it does.
- **`EntityResolver` does not resolve entities today.** Its only production use is section-path resolution
  during ingest (`engine/src/ingest.rs:755-768`, `ExactMatchResolver` over `known_sections`).
  - D-138's entity merge is a new use of the port, not a change to an existing entity path.
- **Judge prices in `measure.py` are stale.** The public `GET /api/v1/models` listing (fetched 2026-10-09,
  `research/fetched/openrouter-models-2026-10-09/models.json`) prices `meta-llama/llama-3.3-70b-instruct` at
  $0.22 / 1M prompt and $0.50 / 1M completion. `measure.py:98-99` holds 0.12 and 0.30.
  - The researcher also reports that `GENERATION_OUTPUT_PRICE_PER_1M` (0.32) is below the listing. That
    constant is outside D-153's text, and the owner decides.
- **The 06.3.6 D-73 gate and `compare` (researcher report; re-checked by the orchestrator in §J below):**
  - The `gitcheck.py` D-73 token is hard-coded to 06.3.5, so a 06.3.6 drive would pass it vacuously.
  - `compare` reads `PREREGISTRATION_06_3_5` at several sites and assumes a judged result.

---

## J. Orchestrator re-checks at `/gsd-plan-phase 06.3.6` (2026-10-09, HEAD `b5f448e3`)

These confirm §I's last bullet and the price row the owner must decide. Read from source, not from a report.

- **D-73 token is a module constant.** `eval/src/lancet_eval/gitcheck.py:29`:
  `PREREGISTRATION_TOKEN = "PREREGISTRATION_06_3_5"`.
  - `run.py:429-440` (the drive gate) passes `(gitcheck.PREREGISTRATION_TOKEN,)` to
    `gitcheck.preregistration_problems`.
  - `score.py:269-280` passes `(gitcheck.PREREGISTRATION_TOKEN, gitcheck.TRUST_FLOOR_TOKEN)`.
  - `judge_stage.py:209-221` passes `(gitcheck.TRUST_FLOOR_TOKEN,)`.
  - So a 06.3.6 corpus run today is gated on the 06.3.5 block, which is already committed: the gate passes
    vacuously. AI-SPEC §4 item 7c / §5 select the token per corpus (`[preregistration] token`) instead
    (**PROPOSED**).
- **`compare` is 06.3.5-specific and judged.**
  - `comparison.py:49` imports `PREREGISTRATION_06_3_5`; it is read at `:556`, `:609`, `:906`, `:998`,
    `:1402`, `:1926` and `:1929`.
  - `comparison.py:1-9` (module docstring): it reads a run directory that `score --judged` has completed, and
    `_load_judged` (`:735-748`) refuses when `judged-result.json` is missing.
  - The CLI entry is `@app.command("compare")` at `eval/src/lancet_eval/cli.py:967`.
  - `compare` has **no** D-73 git gate today (no `gitcheck` import in `comparison.py`). That is WR-02's
    remainder (D-158).
- **Generation price constants and the listing.**
  - `eval/src/lancet_eval/measure.py:60-61`: `GENERATION_INPUT_PRICE_PER_1M = 0.14`,
    `GENERATION_OUTPUT_PRICE_PER_1M = 0.32`. The committed rule at `:50-58` (06.3.4.1-23, 2026-09-29): a price
    constant is never lowered, and is raised when the public listing is higher.
  - `research/fetched/openrouter-models-2026-10-09/models.json` lists `deepseek/deepseek-v4-flash-0731`
    (canonical `deepseek/deepseek-v4-flash-20260731`, the `config/config.toml:130` `generation_model`) at
    `0.0000000137` prompt and `0.00000128` completion USD per token, i.e. $0.0137 and **$1.28** per 1M.
  - Under the rule, input stays 0.14 and output rises to 1.28 (AI-SPEC §4 item 7f). The output row is outside
    D-153's text (judge constants only), so it is an **owner decision** before any cap is proposed (O9).
  - Judge listing: `meta-llama/llama-3.3-70b-instruct` at $0.22 / $0.50 per 1M; `measure.py:98-99` holds
    0.12 / 0.30. That fix is in scope under D-153.

---

## K. Corrections from research and planning (`/gsd-plan-phase 06.3.6`, 2026-10-09)

These supersede §A–§J where they conflict. They come from `06.3.6-RESEARCH.md` "Corrections" (C-numbers) and
from the planner and plan checkers.
- **[re-checked]** means the orchestrator re-read the cited source or output itself.
- **[research]** means it rests on the researcher's executed probe or source read, cited.

**Lance and the store (supersedes the backfill part of §H):**
- **C1 [re-checked].** Lance's SQL planner has no `CASE` (`lance-datafusion-8.0.0/src/planner.rs`, the fallthrough
  `"Expression '…' is not supported SQL in lance"` near `:838`; no `Case` arm in the file). So
  `add_columns(NewColumnTransform::SqlExpressions(… CASE …))` is rejected, and the table version is unchanged.
  `NewColumnTransform::Reader` works. This was executed on a throwaway 5-fragment table with deletion vectors:
  one new version, all 19 old column digests equal, old data files byte-identical, strict 22-column schema
  equality (`research/lance_add_columns_probe.out`, sha256 `c87fc79b…b723`). **Still pending:** the COPY
  verification on a copy of the real `nodes.lance` (plan 06.3.6-15).
- **C2 [re-checked].** For `SqlExpressions` the `read_columns` argument is recomputed inside lance
  (`lance-8.0.0/src/dataset/schema_evolution.rs:347`). For `Reader`, pass `None`.
- **C3 [re-checked].** `DatabaseManager::open_and_validate` (`engine/src/db/mod.rs:35-60`) validates every table in
  `table_schemas()`. `inspect_lancedb` (`bin/inspect_lancedb.rs:1488,1733`) and `diag_probe` call it, and
  `identity.py:56-70` shells out to `inspect_lancedb`. So once `nodes_schema()` gains the three columns, every store
  opener fails closed until the backfill runs. The D-137 store read must happen before that commit.
- **C4 [re-checked].** The `staged_documents_v2` upgrade compares against exactly the 6-column legacy schema
  (`db/mod.rs:88`, `:296`). After D-168 the 7-column form is legacy too, so both must upgrade. The upgrade is a
  store write at the first engine start; it does not move `nodes_version`.
- **C10 [research, executed].** `checkout(v)` then `restore()` adds a version (10 → 11 in the probe). A rollback
  therefore changes `lance-{nodes_version}`, so the generation is recorded only after the final store state.
- **COPY check 4 of AI-SPEC §4 item 4f is replaced** (planner). It compared result hashes from an engine
  restarted before and after the backfill. After the schema commit no engine opens the pre-backfill store (C3),
  and dense retrieval depends on a provider embedding. Plan 06.3.6-15 instead compares the `bm25-only`
  `result_hash` of the 3 rehearsal questions with both 06.3.5 rehearsal journals.
  - **[re-checked]** `result_hash` is blake3 over the final `final_limit` candidates' `chunk_id`s, each followed
    by `\x00` (`engine/src/workflow/nodes/retrieve.rs:397-401`). It contains no answer, snapshot bytes or
    `index_generation`, so it is a retrieval-only fingerprint.

**Rerank endpoint (supersedes §A7's error list):**
- **C11 [re-checked].** The fetched OpenAPI (`research/fetched/openrouter-submit-a-rerank-request-2026-10-09.md`)
  documents 12 error statuses for `POST /rerank`: 400, 401, 402, 403, 404, 413, 429, 500, 502, 503, 524 and 529.
  `results[].document` is required in the 200 body, so the reply echoes every document. The adapter needs a
  documented body cap above the 256 KiB default (`engine/src/client/mod.rs:16`).

**Line drift (supersedes §A2 / §I line numbers):**
- **C8 [re-checked].** `pub struct WorkflowDependencies` is at `engine/src/workflow/mod.rs:336` and `pub fn new()`
  at `:350`, not `:342` / `:357`.

**Harness facts found while planning:**
- **[re-checked]** `.gitignore:62` ignores `eval/runs/*`. The negations at `:63-67` cover only the existing corpus
  names, so the 06.3.6 run directories need `!eval/runs/*-multihop_rag_levers_*/` (plan 06.3.6-03).
- **[re-checked]** `preflight.py` appends every provenance clause code to its failures (`failures.extend(… for f in
  provenance_failures(record))`, near `:1220`). A single `RERANK_DEGRADED` canary would therefore fail preflight
  unless clause (i) is counted separately (plan 06.3.6-07).
- **C5 [re-checked].** `corpus.py:105` `_SPLIT_ROLES = frozenset({"heldout", "rehearsal"})`, and the D-73 gate in
  `run.py:427-441` applies to every `[split]` corpus. D-170 adds a `dev` role, exempt from the gate.
- **[planner]** `seed.record_index_generation` (`seed.py:282`) has no CLI command, so plan 06.3.6-15 calls it with
  `python -c`. It POSTs one `/rag/query` probe: the first `document_map.json` entry's title, "The best VPN services
  for 2023".
- **[planner]** `query_embedding_retries` is omitted from the wire when it is zero, so an absent value reads as 0.
- **C6 [research].** `score` builds P4 from the held-out split (`score.py:658-661`), so it cannot score dev
  journals. Plan 06.3.6-10 adds `dev_reads.py`.
- **C7 [research, executed].** At HEAD, `uv run --project eval pytest eval/tests` gives 1802 passed. A repo-root
  `pytest` also collects `scripts/` and fails. `ruff check --preview eval/src eval/tests` reports 556 findings
  before any change, so the lint gate is "no new finding on touched files".

## L. Live facts from plan 06.3.6-01 (the D-131 probe, 2026-10-09)

**[re-checked]** by the orchestrator from `research/probe-result.json` (commit `088d5c08`) and the gitignored settle
readings in `data/oi02-evidence/probe-2026-10-09/`.
- One authenticated `POST /api/v1/rerank` for `voyageai/rerank-2.5-lite` with 2 documents, `top_n` 2 and
  `provider` = `{"allow_fallbacks": false}`: HTTP 200 in 407.3 ms, order `[1, 0]`, scores `[0.90234375, 0.390625]`.
- The reply `model` is the bare **`rerank-2.5-lite`**, not the requested slug and not the dated canonical slug
  (supersedes the "may carry the dated slug" expectation in §A7, RESEARCH C11 and the AI-SPEC). `provider` is
  "VoyageAI by MongoDB".
- `usage` is `{"cost": 4.4e-07, "total_tokens": 22}`.
- Settled account `usage`: 2.983984094 before (2 readings agree), 2.983984534 after (2 readings agree). The delta
  4.4e-07 equals `usage.cost`, so 1 credit = 1 USD is consistent.
- The response-model rule is corrected by D-186 (owner): the reply `model` starts with the requested slug or with its
  bare name after the vendor prefix. A re-probe under that rule follows (plan 06.3.6-01).
