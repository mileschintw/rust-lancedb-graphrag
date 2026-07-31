# Phase 3: Hybrid Retrieval & Basic RAG Path - Pattern Map

**Mapped:** 2026-07-31
**Scope:** MVP happy-path vertical tracer only: HTTP JSON -> Go gRPC forwarding -> Rust validation/retrieval -> bounded evidence -> one structured generation call -> structured response.
**Files analyzed:** 24
**Analogs found:** 24 / 24 (14 exact/same-file/generated matches, 7 strong/role matches, 3 partial matches; no exact analog exists for BM25, RRF, or prompt assembly)

The broader context contract mentions degraded retrieval, model-only answers, citation repair, retries, provider fallback, graph context, and streaming. They are deliberately not assigned below. Preserve only the typed boundary fields and injectable seams needed by the happy path.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `engine/src/retrieval/mod.rs` | service | request-response + transform | `engine/src/chunker/mod.rs` | role-match |
| `engine/src/retrieval/dense.rs` | service | CRUD + request-response | `engine/src/bin/inspect_lancedb.rs` | strong |
| `engine/src/retrieval/bm25.rs` | utility/service | batch + transform + request-response | `engine/src/chunker/mod.rs` | partial |
| `engine/src/retrieval/fusion.rs` | utility | transform | `engine/src/bin/inspect_lancedb.rs` | partial |
| `engine/src/retrieval/tests.rs` | test | CRUD + transform | `engine/src/inspect_lancedb_tests.rs` | role-match |
| `engine/src/rerank/mod.rs` | service | request-response + transform | `EmbeddingProvider` in `engine/src/main.rs` and `EntityResolver` in `engine/src/db/mod.rs` | role-match |
| `engine/src/rerank/tests.rs` | test | request-response | `engine/src/client/tests.rs` | role-match |
| `engine/src/prompt.rs` | utility/service | transform | `engine/src/chunker/mod.rs` | partial |
| `engine/src/generation/mod.rs` | service | request-response | `EmbeddingProvider` in `engine/src/main.rs` | role-match |
| `engine/src/generation/openrouter.rs` | service | request-response | `engine/src/client/mod.rs` | strong |
| `engine/src/main.rs` | controller/service | request-response + event-driven startup | current `LancetServiceImpl` and `main` in the same file | exact |
| `engine/src/tests.rs` | test | CRUD + request-response | existing worker/fake-provider tests in the same file | exact |
| `engine/tests/config_startup.rs` | test | event-driven startup | existing engine readiness tests in the same file | exact |
| `engine/Cargo.toml` | config | config | current dependency manifest in the same file | exact |
| `engine/Cargo.lock` | config/generated | config | current lockfile in the same file | exact |
| `config/config.toml` | config | config | current `[engine]`/`[openrouter]` layout | exact |
| `config/config.example.toml` | config | config | committed example overlay in the same file | exact |
| `proto/lancet/v1/lancet.proto` | contract | request-response | existing unary `QueryRAG` messages in the same file | exact/additive |
| `engine/src/pb/lancet/v1/lancet.v1.rs` | generated contract | request-response | current prost output in the same file | generated |
| `engine/src/pb/lancet/v1/lancet.v1.tonic.rs` | generated service | request-response | current tonic output in the same file | generated |
| `gateway/proto/lancet/v1/lancet.pb.go` | generated contract | request-response | current protoc-gen-go output in the same file | generated |
| `gateway/proto/lancet/v1/lancet_grpc.pb.go` | generated service | request-response | current protoc-gen-go-grpc output in the same file | generated |
| `gateway/main.go` | controller/service | request-response | current chi routes, `grpcEngine`, and `writeJSON` in the same file | exact |
| `gateway/main_test.go` | test | request-response | current `fakeStore`, `engineFunc`, and httptest route tests in the same file | exact |

The exact Rust module layout is discretionary. If the planner chooses `engine/src/prompt/mod.rs` instead of `prompt.rs), apply the same assignment and analog.

## Pattern Assignments

### `engine/src/retrieval/mod.rs` (service, request-response + transform)

**Analog:** `engine/src/chunker/mod.rs`, lines 1-36 and 194-195; secondary integration seam: `engine/src/main.rs`, lines 434-549.

Use the existing Rust module convention: imports at the top, small public domain types, pure helpers kept private, and a separate test module.

**Module/test shape** (from `engine/src/chunker/mod.rs`, lines 1-3 and 194-195):

```rust
use pulldown_cmark::{Event, HeadingLevel, Parser, Tag, TagEnd};
use std::sync::OnceLock;
use tiktoken_rs::{o200k_base, CoreBPE};

#[cfg(test)]
mod tests;
```

Make this module own the validated query/filter types, candidate/evidence metadata, retriever coordinator, candidate limits, and the call sequence:

1. normalize/validate once;
2. derive the embedding and BM25 query views;
3. invoke dense and BM25 against the same typed filter;
4. fuse/dedupe deterministically;
5. invoke `NoOpReranker`;
6. return the bounded ordered evidence to prompt assembly.

Keep the tonic method thin and return typed errors that `main.rs` maps to `Status::invalid_argument` or an internal/provider status. Do not put LanceDB predicates, BM25 scoring, or HTTP concerns in Go.

### `engine/src/retrieval/dense.rs` (service, CRUD + request-response)

**Analog:** `engine/src/bin/inspect_lancedb.rs`, lines 46-98 and 281-337.

Copy the Arrow column access and LanceDB query pipeline. The existing code checks the column’s presence and Arrow type rather than unwrapping an assumed layout:

```rust
fn string_column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a StringArray, String> {
    batch
        .column_by_name(name)
        .ok_or_else(|| format!("LanceDB query did not return {name}"))?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| format!("LanceDB column {name} has an unexpected type"))
}

async fn query_columns(
    table: &Table,
    filter: &str,
    columns: &[&str],
) -> Result<Vec<RecordBatch>, String> {
    table
        .query()
        .only_if(filter)
        .select(Select::columns(columns))
        .execute()
        .await
        .map_err(|error| error.to_string())?
        .try_collect()
        .await
        .map_err(|error| error.to_string())
}
```

For the dense path, extend this shape with `nearest_to(query_embedding)`, the configured candidate limit, and the same pre-filter before `execute`. Extract required identity/content/embedding metadata with the same null/type checks; nullable title, section path, and content type must remain absent rather than fabricated. Use `engine/src/db/mod.rs`, lines 111-136, as the canonical schema source.

### `engine/src/retrieval/bm25.rs` (utility/service, batch + transform + request-response)

**Analog:** `engine/src/chunker/mod.rs`, lines 7-33 and 159-193. This is a partial analog only; no BM25 index exists in the repository.

Follow the chunker’s deterministic, source-preserving transform style. The existing `Chunk` keeps original content and provenance separate from token estimation:

```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Chunk {
    pub content: String,
    pub char_start: usize,
    pub char_end: usize,
    pub section_path: Option<String>,
    pub estimated_tokens: i32,
}

pub fn estimate_tokens(chunk: &str) -> i32 {
    static TOKENIZER: OnceLock<CoreBPE> = OnceLock::new();
    let tokenizer = TOKENIZER.get_or_init(|| {
        o200k_base().expect("the embedded o200k_base tokenizer should always initialize")
    });
    i32::try_from(tokenizer.encode_ordinary(chunk).len()).unwrap_or(i32::MAX)
}
```

Implement the new BM25 analyzer/index from the phase contract, not from a nonexistent local search library:

- NFKC normalization, full Unicode case folding, and Unicode word segmentation;
- no stemming or stop-word removal;
- whole technical identifiers plus camel-case, underscore, and hyphen subtokens;
- content/title/section-path fields with boosts 1.0/2.0/1.5;
- global completed-corpus document frequency, while request filters only constrain candidates;
- configurable `k1=1.2` and `b=0.75`;
- original source strings retained for evidence/citations.

Build the snapshot from canonical completed LanceDB rows before readiness. Keep `build`, `query`, and analyzer functions deterministic and independently testable; do not silently make the service vector-only if index construction fails.

### `engine/src/retrieval/fusion.rs` (utility, transform)

**Analog:** `engine/src/bin/inspect_lancedb.rs`, lines 111-200, for explicit identity/invariant checks and `HashSet` use. No RRF/ranking analog exists.

The implementation is a pure transform: take dense and BM25 candidate vectors, retain each source rank, deduplicate by `chunk_id`, calculate full-precision weighted RRF, and sort by:

1. descending fused score;
2. best individual source rank;
3. `document_id`;
4. `chunk_index`;
5. `chunk_id`.

Use 1-based ranks and round only serialized diagnostics. The research contract’s concrete shape is the fallback for the missing repository analog:

```rust
for (rank, candidate) in vector_results.iter().enumerate() {
    let rank = rank + 1;
    fused.entry(candidate.chunk_id.clone())
        .or_default()
        .add_vector(candidate, vector_weight / (rrf_k + rank as f64));
}
for (rank, candidate) in bm25_results.iter().enumerate() {
    let rank = rank + 1;
    fused.entry(candidate.chunk_id.clone())
        .or_default()
        .add_bm25(candidate, bm25_weight / (rrf_k + rank as f64));
}
```

Do not sort by rounded scores or map iteration order. Do not recompute BM25 IDF on the filtered subset.

### `engine/src/retrieval/tests.rs` (test, CRUD + transform)

**Analog:** `engine/src/inspect_lancedb_tests.rs`, lines 54-155; secondary: `engine/src/db/tests.rs`, lines 14-61.

Copy the isolated temporary LanceDB fixture style:

```rust
fn database_path(test_name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-inspector-{test_name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

let node_schema = node_table.schema().await.unwrap();
let nullable = |name: &str| {
    new_null_array(
        node_schema.field_with_name(name).unwrap().data_type(),
        node_count,
    )
};
```

Populate the canonical `nodes` schema through `RecordBatch` with deterministic IDs, contents, title/section/content-type variants, and finite 2,048-dimensional embeddings. Test Unicode analyzer parity, global IDF, field boosts, typed filters (OR within a field and AND across fields), empty valid filters, RRF duplicate retention/source ranks, locked tie-breaking, and repeat-run order. Drop all database handles before removing the temporary path.

The existing fake provider pattern in `engine/src/tests.rs`, lines 9-17, is the model for deterministic embeddings:

```rust
struct FakeEmbedder;

impl EmbeddingProvider for FakeEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move { Ok(texts.iter().map(|_| vec![0.25; 2048]).collect()) })
    }
}
```

### `engine/src/rerank/mod.rs` (service, request-response + transform)

**Analogs:** boxed async `EmbeddingProvider` in `engine/src/main.rs`, lines 563-576; async `EntityResolver` in `engine/src/db/mod.rs`, lines 238-257.

Use an injectable async port, with `NoOpReranker` preserving candidate order, fused scores, source ranks, and evidence metadata. The existing object-safe boxed-future seam is:

```rust
trait EmbeddingProvider: Send + Sync {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>>;
}

impl EmbeddingProvider for OpenRouterClient {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move { OpenRouterClient::get_embeddings(self, texts).await })
    }
}
```

The database trait is the alternate repository convention for an async injected implementation:

```rust
#[tonic::async_trait]
pub trait EntityResolver: Send + Sync {
    async fn resolve(
        &self,
        entity: &str,
        known_entities: &[String],
    ) -> Result<Option<String>, String>;
}
```

Prefer the project’s no-new-dependency boxed-future style for the provider-neutral port if object safety is needed. This phase creates only the port and pass-through implementation. Do not add external/local rerankers or soft-fallback behavior.

### `engine/src/rerank/tests.rs` (test, request-response)

**Analog:** `engine/src/client/mod.rs:67-75` for the test-only client constructor, plus `engine/src/client/tests.rs:122-184` for deterministic local-provider assertions.

Use a small in-memory candidate vector and assert that `NoOpReranker` returns exactly the same order, score precision, source ranks, IDs, and metadata. Keep the test independent of OpenRouter and network access; the existing client tests use a controlled test constructor and local mock server for provider-specific tests.

### `engine/src/prompt.rs` (utility/service, transform)

**Analog:** `engine/src/chunker/mod.rs`, lines 7-33; secondary source fields in `engine/src/main.rs`, lines 775-817.

Reuse `tiktoken-rs`’s `o200k_base` convention through the existing `estimate_tokens` helper. Keep each evidence object’s generated ID, document/chunk provenance, original content, title/section metadata, and bounded excerpt together. Reserve the configured answer-token budget first, then pack complete chunks in RRF order; never split a chunk or citation boundary blindly.

Render isolated evidence blocks with an engine-generated ID and escaped delimiter-like source text. The system rule and user question must remain separate from evidence. Retrieved content is data, not an instruction. Preserve suspicious text as evidence; do not implement the deferred citation repair/downgrade policy here.

### `engine/src/generation/mod.rs` (service, request-response)

**Analog:** `EmbeddingProvider` in `engine/src/main.rs`, lines 563-576; provider implementation structure in `engine/src/client/mod.rs`, lines 19-66.

Define the provider-neutral request/output/error types and object-safe async `Generator` port. Copy the existing dependency injection shape, but keep generation separate from the embedding client so its one-shot semantics cannot inherit embedding retries.

The closed model output should follow the phase contract:

```rust
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ModelOutput {
    answer: String,
    cited_evidence_ids: Vec<String>,
    answer_basis: AnswerBasis,
    notices: Vec<String>,
}
```

For the MVP happy path, validate non-empty answer, supported `answer_basis`, and cited IDs against the evidence map. Use a fake generator in tests. Do not add a classifier call, retry, provider fallback, model-only fallback, or citation repair loop.

### `engine/src/generation/openrouter.rs` (service, request-response)

**Analog:** `engine/src/client/mod.rs`, lines 1-66 and 120-162.

Copy the reqwest client construction, bearer authentication, environment credential loading, Serde request/response types, status handling, and contextual error strings:

```rust
fn build_http_client() -> Result<Client, reqwest::Error> {
    Client::builder().timeout(REQUEST_TIMEOUT).build()
}

pub fn from_env() -> Result<Self, String> {
    let api_key = std::env::var("OPENROUTER_API_KEY")
        .map_err(|_| "OPENROUTER_API_KEY is not configured".to_string())?;
    Self::new(api_key)
}

let response = self
    .http
    .post(&self.endpoint)
    .bearer_auth(&self.api_key)
    .json(&request)
    .send()
    .await
    .map_err(|error| error.to_string())?;
```

Adapt the endpoint/model/strict JSON-schema payload for chat generation and enforce temperature 0, top-p 1, and the 2,048-token cap from configuration. Wrap the one call in a 30-second Tokio timeout at the query orchestration boundary. Do not copy `embed_with_retry`, `MAX_RETRIES`, or backoff: the phase explicitly makes generation one-shot.

### `engine/src/main.rs` (controller/service, request-response + event-driven startup)

**Analog:** the current file, especially `LancetServiceImpl` at lines 381-419, `query_rag` at lines 541-549, and startup at lines 1099-1138.

Preserve the existing tonic service implementation and startup ownership. The current query method is the replacement locus:

```rust
async fn query_rag(
    &self,
    request: Request<QueryRagRequest>,
) -> Result<Response<QueryRagResponse>, Status> {
    let req = request.into_inner();
    Ok(Response::new(QueryRagResponse {
        answer: format!("Placeholder answer for: {}", req.query),
        citations: vec![],
        session_id: req.session_id,
    }))
}
```

The new method should only unpack the request, validate/normalize via the retrieval coordinator, call evidence assembly/generation, and map typed errors to tonic status. Keep vector/LanceDB/BM25 semantics in Rust modules.

Wire BM25 snapshot rebuild into the same startup path that initializes the canonical database, before the service is considered ready. The existing startup pattern initializes the database, opens the staging table, creates statuses/queue, replays staged jobs, then registers `LancetServiceServer`. Preserve that fail-fast sequence and make index-build failure stop startup rather than accepting vector-only queries.

### `engine/src/tests.rs` (test, CRUD + request-response)

**Analog:** the same file, lines 9-18, 99-116, 1380-1510.

Extend the existing external test module with a fake generator, temporary completed-node fixture, and a service-level query test. Reuse the helpers:

```rust
fn database_path(test_name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-worker-{test_name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

async fn query_rows(table: &Table, predicate: &str) -> Vec<RecordBatch> {
    table
        .query()
        .only_if(predicate)
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap()
}
```

The happy-path assertion should cover validated query/filter input, stable fused chunk IDs, bounded evidence, one fake-generator invocation, valid structured output, effective session ID, citations/snapshot fields, and the absence of a second model call. Use local fixtures only. Do not add induced failure-path acceptance for deferred degraded/model-only/retry behavior.

### `engine/tests/config_startup.rs` (test, event-driven startup)

**Analog:** the same file, lines 11-66 and 72-150.

Extend the existing process-level readiness test so a temporary LanceDB corpus rebuilds its lexical snapshot before the readiness log is observed. Copy the isolated config/temp-directory setup and the readiness signal:

```rust
let config_toml = format!(
    "[engine]\ngrpc_addr = \"127.0.0.1:0\"\nlancedb_path = \"{}\"\n",
    lancedb_dir.to_str().unwrap().replace('\\', "/")
);

if line.contains("Rust RAG Engine serving") {
    let _ = tx_out.send(Ok(line));
    return;
}
```

Keep `OPENROUTER_API_KEY=test-key` for startup-only tests and clean the unique temporary directory after child shutdown.

### `engine/Cargo.toml` and `engine/Cargo.lock` (config, config)

**Analog:** the current manifest and lockfile.

Preserve the existing pinned `~` dependency style and add only the direct Unicode analysis crates required by the phase contract (`unicode-normalization`, `unicode-casefold`, `unicode-segmentation`). Update the lockfile through Cargo; do not hand-edit it. Reuse existing Tokio, LanceDB, Arrow, reqwest, Serde, and tiktoken dependencies.

### `config/config.toml` and `config/config.example.toml` (config, config)

**Analog:** current file layout, lines 1-14 in each file, plus Rust `load_settings` at `engine/src/main.rs:49-85`.

Keep the existing `[engine]` and `[openrouter]` tables and environment overlay convention. Add explicit bounded retrieval/generation settings only if the planner exposes them through file-backed configuration; use the same committed-example/no-secret pattern. The model ID, RRF weights/k, BM25 parameters, candidate/final limits, generation timeout, sampling values, and output cap must be configurable, while the exact key names remain discretionary.

### `proto/lancet/v1/lancet.proto` (contract, request-response)

**Analog:** current unary service and query messages in the same file, lines 7-15 and 48-56.

Extend `QueryRAGRequest`/`QueryRAGResponse` additively. Preserve field numbers and use typed nested messages/enums for filters, structured citations, answer basis, notices/warnings, and retrieval snapshot. The current baseline is:

```proto
service LancetService {
  rpc QueryRAG(QueryRAGRequest) returns (QueryRAGResponse);
}

message QueryRAGRequest {
  string query = 1;
  string session_id = 2;
}

message QueryRAGResponse {
  string answer = 1;
  repeated string citations = 2;
  string session_id = 3;
}
```

Do not reuse or renumber existing fields. Keep the public contract sufficient for the happy path; typed capacity for later warnings/bases is a boundary seam, not permission to implement deferred runtime branches.

### Generated bindings (four files, generated contract, request-response)

**Analogs:** the current generated files in place:

- `engine/src/pb/lancet/v1/lancet.v1.rs`, lines 52-66, currently emits prost `QueryRagRequest/Response`.
- `engine/src/pb/lancet/v1/lancet.v1.tonic.rs`, lines 33-45 and 261-290, currently emits the tonic unary `query_rag` dispatch.
- `gateway/proto/lancet/v1/lancet.pb.go`, lines 377-494, currently emits Go query structs/getters.
- `gateway/proto/lancet/v1/lancet_grpc.pb.go`, lines 32-110 and 125-147, currently emits the Go client/server query method.

Regenerate all four with the repository root `buf.gen.yaml` (lines 1-14), which writes Go output under `gateway/proto` and prost/tonic output under `engine/src/pb`. Never hand-edit generated files and never regenerate only one language.

### `gateway/main.go` (controller/service, request-response)

**Analog:** the same file, lines 200-257, 433-450, 453-550, and 622-625.

Add `QueryRAG` to the thin engine interface and forward the request with the incoming context:

```go
type engine interface {
    Ingest(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, src io.Reader) IngestOutcome
    IngestionStatus(context.Context, string) (*pb.GetIngestionStatusResponse, error)
    Ping(context.Context) (time.Duration, error)
}

type grpcEngine struct{ client pb.LancetServiceClient }

func (e grpcEngine) IngestionStatus(ctx context.Context, id string) (*pb.GetIngestionStatusResponse, error) {
    return e.client.GetIngestionStatus(ctx, &pb.GetIngestionStatusRequest{DocumentId: id})
}
```

Register the new route beside the existing chi routes:

```go
r := chi.NewRouter()
r.Use(middleware.RequestID, middleware.RealIP, middleware.Recoverer, middleware.Timeout(60*time.Second))
r.Get("/health", a.health)
r.Post("/documents", a.createDocument)
r.Get("/documents/{id}", a.getDocument)
```

The `POST /rag/query` handler should bound the JSON body, reject unknown fields, validate the session/filter envelope, call generated `QueryRAG` with `r.Context()`, map the happy-path response to JSON, and map gRPC `InvalidArgument` to HTTP 400. Keep retrieval, ranking, prompt assembly, and provider logic out of Go. Reuse `writeJSON` at lines 622-625 for content type and encoding.

### `gateway/main_test.go` (test, request-response)

**Analog:** the same file, lines 39-121, 231-258, 635-671, and 801-814.

Extend `engineFunc` or add a focused fake engine method for `QueryRAG`; keep stateful fakes and real router invocation:

```go
type engineFunc struct {
    ingest    func(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, b []byte) IngestOutcome
    status    *pb.GetIngestionStatusResponse
    statusErr error
}

func (engineFunc) Ping(context.Context) (time.Duration, error) {
    return time.Millisecond, nil
}
```

Add httptest coverage for strict JSON decoding/body bounds, generated session when absent, valid caller session pass-through, typed filters, structured response mapping, and gRPC `codes.InvalidArgument` -> HTTP 400. Assert the fake received the same query/session/filter values and request context. The existing route tests use:

```go
recorder := httptest.NewRecorder()
app{store: store, engine: engine, logger: zap.NewNop()}.
    routes().ServeHTTP(recorder, request)
if recorder.Code != http.StatusBadGateway {
    t.Fatalf("status = %d", recorder.Code)
}
```

Do not add gateway-side retrieval tests or deferred fallback behavior.

## Shared Patterns

### Rust ownership and tonic boundary

**Sources:** `engine/src/main.rs:434-557`, `engine/src/db/mod.rs:17-64`.

Rust owns LanceDB, BM25, filtering, fusion, evidence, and generation semantics. The tonic method validates/dispatches/maps; Go owns only HTTP decoding, context forwarding, and response/status mapping.

### Async dependency seams

**Sources:** `engine/src/main.rs:563-576`, `engine/src/tests.rs:9-18`, `engine/src/db/mod.rs:238-257`.

Use `Send + Sync` injected dependencies and deterministic fakes. Prefer boxed futures for object-safe provider ports without adding an async-trait dependency solely for generation. Keep the fake generator local and count calls to prove exactly one generation attempt.

### LanceDB schema-driven Arrow handling

**Sources:** `engine/src/bin/inspect_lancedb.rs:46-98`, `engine/src/inspect_lancedb_tests.rs:89-155`, `engine/src/db/mod.rs:111-136`.

Read canonical fields by name and expected Arrow type, use `new_null_array` for nullable fields, use pre-filters before candidate limits, and preserve required identity fields. Never interpolate unvalidated document/content filter values into a predicate.

### Config overlays and secrets

**Sources:** `engine/src/main.rs:49-85`, `config/config.example.toml:1-14`, `gateway/main.go:52-83`.

Keep file-backed TOML plus the repository's `LANCET_ENGINE__...` and `LANCET_OPENROUTER__...` environment overrides. Load `OPENROUTER_API_KEY` from the environment, reject missing/blank keys, and never log credentials, raw prompts, or raw evidence.

### Error formatting and boundary mapping

**Sources:** `engine/src/main.rs:419-430`, `gateway/main.go:525-550`, `gateway/main.go:622-625`.

Rust adds context with `map_err`, returns `Status::invalid_argument` for caller contract violations, and uses structured internal/provider errors. Go maps known gRPC codes explicitly and returns stable HTTP JSON/error responses. Preserve request/session identity in Rust errors where the contract requires it.

### Test isolation and readiness

**Sources:** `engine/src/inspect_lancedb_tests.rs:54-155`, `engine/src/db/tests.rs:14-61`, `engine/tests/config_startup.rs:11-66`.

Every LanceDB fixture gets a unique temporary path, all handles are dropped before cleanup, and process-level tests wait for the existing readiness log. Build the BM25 snapshot before that readiness signal.

### Generated protobuf workflow

**Source:** root `buf.gen.yaml:1-14`.

The proto is the source of truth. Regenerate both Rust and Go outputs after additive edits, then compile/test both language sides. Generated files are not handwritten pattern sources.

### MVP scope guard

**Sources:** `03-CONTEXT.md` decisions D-18, D-26, D-28-D-30, D-35-D-39; `03-RESEARCH.md` MVP Scope Fence.

Pattern assignments cover one unary request, deterministic dense+BM25 retrieval, NoOp pass-through, bounded untrusted evidence, one strict provider call, and structured response assembly. Do not copy the existing embedding retry loop into generation, and do not assign patterns for deferred retries, provider fallback, citation repair, model-only/degraded execution, graph, streaming, or state-machine orchestration.

## No Analog Found

| File/Capability | Role | Data Flow | Reason | Planner Guidance |
|---|---|---|---|---|
| `engine/src/retrieval/bm25.rs` | utility/service | batch + transform + request-response | No lexical index, Unicode analyzer, or BM25 scoring implementation exists. | Use the locked D-44-D-50 contract and test index/query analyzer parity, field boosts, global IDF, and filters. |
| `engine/src/retrieval/fusion.rs` | utility | transform | No rank fusion/RRF implementation exists. | Implement the explicit weighted RRF formula and D-51 tie key as a pure deterministic function. |
| `engine/src/prompt.rs` | utility/service | transform | No prompt/evidence assembler exists. | Use chunker token estimation and Phase 3’s isolated evidence-block contract; keep original text and provenance separate. |
| Cross-index publication/rebuild | service/config | batch + event-driven startup | Existing ingestion persists LanceDB rows and replays staging, but no vector+BM25 publication state or readiness gate exists. | Add the smallest startup/query-ready seam in `main.rs`; do not copy the current delete-first replacement sequence as an atomic cross-index protocol. |

## Metadata

**Analog search scope:** `engine/src`, `engine/tests`, `gateway`, `proto`, `config`, root Buf configuration, and Phase 2/999.2 planning artifacts.
**Strong analog families scanned:** LanceDB/Arrow inspection and fixtures; chunking/token budgeting; OpenRouter embedding HTTP client; tonic service/startup; chi gateway and httptest fakes; protobuf generation.
**Pattern extraction date:** 2026-07-31
