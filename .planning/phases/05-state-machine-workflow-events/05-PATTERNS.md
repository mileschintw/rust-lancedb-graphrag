# Phase 5: State Machine & Workflow Events - Pattern Map

**Mapped:** 2026-08-10
**Files analyzed:** 15
**Analogs found:** 15 / 15

> Note: `05-AI-SPEC.md` Section 3-4 is the **authoritative, already-locked** design contract for the Rust `Node`/`WorkflowRunner` pattern itself (imports, entry-point shape, pitfalls). This file does not re-derive that pattern — it maps each new/modified file to the closest **existing, currently-shipping** codebase analog and extracts concrete excerpts to copy from, per `05-RESEARCH.md`'s verified citations.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `engine/src/workflow/node.rs` (Node trait, NodeError/NodeErrorKind) | utility/trait-port | event-driven | `engine/src/generation/mod.rs` (`Generator` trait + `GenerationError`/`GenerationErrorKind`, lines 1-22, 404-464) | exact |
| `engine/src/workflow/runner.rs` (WorkflowRunner: select!-based timeout/cancel/retry loop) | service (orchestrator) | event-driven | `engine/src/generation/openrouter.rs` (`Generator::generate`'s per-attempt `tokio::time::timeout` wrapping, ~line 626) — timeout-race precedent; no existing multi-step orchestrator to copy structurally | role-match (partial — net-new orchestration shape) |
| `engine/src/workflow/events.rs` (WorkflowEvent enum, checkpoint snapshot builder) | model/DTO | event-driven | `engine/src/generation/mod.rs` (`ModelOutput`/`ModelUsage` closed serde structs, lines 46-68) | role-match |
| `engine/src/workflow/nodes/reformulate.rs` (`QueryReformulator` port, NoOp impl) | service (port) | request-response | `engine/src/generation/mod.rs` (`Generator` trait + `FakeGenerator`, lines 458-512) | exact |
| `engine/src/workflow/nodes/retrieve.rs` (RRF-merge across reformulation variants) | service (pipeline stage) | transform | `engine/src/retrieval/fusion.rs::fuse_candidates` (single-pass RRF, lines 58-165) + `engine/src/main.rs:1450-1495` (existing dense+BM25+fuse call site) | role-match |
| `engine/src/workflow/nodes/graph_context.rs` (wraps `attempt_graph_augmentation` + inner timeout) | service (pipeline stage) | transform | `engine/src/main.rs:1426-1448` (existing `attempt_graph_augmentation` call site + outcome match) | exact |
| `engine/src/workflow/nodes/assemble_prompt.rs` | service (pipeline stage) | transform | `engine/src/main.rs:1549-1559` (existing `pack_evidence_and_graph_prompt` call site) | exact |
| `engine/src/workflow/nodes/generate.rs` (wraps `Generator::generate`, owns D-12 single-retry loop) | service (pipeline stage) | request-response | `engine/src/main.rs:1561-1597` (existing generation call site + error-kind mapping) + `engine/src/generation/mod.rs:466-512` (`FakeGenerator`, retry-test double) | exact |
| `engine/src/main.rs` `query_rag` handler (rewritten: `ReceiveQuery` boundary stays, rest delegates to `WorkflowRunner`, opens `mpsc`/`ReceiverStream`) | controller (tonic handler) | streaming | `engine/src/main.rs:1346-1708` (itself — refactor in place) | exact (self) |
| `proto/lancet/v1/lancet.proto` (`QueryRAG` unary→server-streaming, new `WorkflowEvent` oneof message) | config/contract | streaming | same file's `IngestDocument` (client-streaming RPC, line 9) for streaming-RPC syntax precedent; `QueryRAGRequest`/`QueryRAGResponse` (lines 53-111) for field-shape precedent | role-match |
| `gateway/main.go` `engine.QueryRAG` interface + `grpcEngine.QueryRAG` (unary→stream-consuming client method) | service/adapter | streaming | `gateway/main.go:212-254` (`grpcEngine.Ingest`, the only existing streaming gRPC client call — client-streaming, but same "stream + defer-close + loop" shape) + `gateway/main.go:280-287` (current unary `QueryRAG`, trailer pattern to preserve for pre-stream errors) | role-match |
| `gateway/main.go` `queryRAG` HTTP handler (rewritten: SSE `text/event-stream` forwarding loop) | controller (HTTP handler) | streaming | `gateway/main.go:653-715` (itself — current unary JSON handler, refactor in place); no existing SSE precedent in this codebase (net-new pattern, `05-RESEARCH.md` Pattern 2) | no analog (see below) |
| `gateway/main.go` route registration (`/rag/query` route-scoped timeout override) | config | request-response | `gateway/main.go:462-470` (`routes()` — global `middleware.Timeout(60*time.Second)` applied via `r.Use`, needs `/rag/query`-specific override) | exact |
| `gateway/db/schema.hcl` (+ `workflow_checkpoints` table block) | model/migration | CRUD | `gateway/db/schema.hcl` (`document_reconciliation_intents` table, lines 82-134 — closest existing table with a foreign-key-free-ish write-heavy, non-PK-per-row-identity shape; `documents` table lines 29-80 for the `varchar`+`timestamp`+`CURRENT_TIMESTAMP` convention) | exact |
| `gateway/db/query.sql` (+ `InsertWorkflowCheckpoint` query, sqlc source) | service (data access) | CRUD | `gateway/db/query.sql:10-30` (`InsertDocument` — plain single-row `INSERT ... RETURNING *` pattern) | exact |

## Pattern Assignments

### `engine/src/workflow/node.rs` (trait-port, event-driven)

**Analog:** `engine/src/generation/mod.rs`

**BoxFuture + object-safe async trait pattern** (lines 20-22, 458-464):
```rust
pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// Provider-neutral object-safe async trait for structured generation.
pub trait Generator: Send + Sync {
    fn generate<'a>(
        &'a self,
        request: GenerationRequest,
    ) -> BoxFuture<'a, Result<ModelOutput, GenerationError>>;
}
```
Mirror this exactly for `Node`: `fn run<'a>(&'a self, ctx: &'a mut WorkflowContext, cancel: &'a CancellationToken) -> BoxFuture<'a, Result<(), NodeError>>`.

**Error-struct shape to mirror for `NodeError`/`NodeErrorKind`** (lines 404-456):
```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GenerationErrorKind {
    InvalidRequest,
    SupportedParameters,
    ProviderError,
    SchemaValidation,
    Timeout,
    Cancelled,
    SessionCorrelation,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GenerationError {
    pub kind: GenerationErrorKind,
    pub message: String,
    pub session_id: Option<String>,
    pub correlation_id: Option<String>,
}

impl GenerationError {
    pub fn new(kind: GenerationErrorKind, message: impl Into<String>) -> Self {
        Self { kind, message: message.into(), session_id: None, correlation_id: None }
    }
    pub fn with_correlation(mut self, session_id: Option<String>, correlation_id: Option<String>) -> Self {
        self.session_id = session_id;
        self.correlation_id = correlation_id;
        self
    }
    pub fn message(&self) -> &str { &self.message }
}

impl Display for GenerationError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}: {}", self.kind, self.message)
    }
}
impl std::error::Error for GenerationError {}
```
`NodeErrorKind` variants per D-22's taxonomy: `InputValidation`, `RetrievalFailed`, `GraphQueryFailed`, `PromptAssemblyFailed`, `LlmGenerationFailed`, `Timeout`, `Cancelled`, `Internal`. Reuse the `message`/`with_correlation`/`Display`/`std::error::Error` shape verbatim — this is the established `M-ERRORS-CANONICAL-STRUCTS` house pattern (`rust-guidelines.md:2966`).

**Test double pattern to mirror for a `FakeQueryReformulator`/graph-query stall double** (lines 466-512):
```rust
pub struct FakeGenerator {
    pub call_count: AtomicUsize,
    pub responses: Mutex<Vec<Result<ModelOutput, GenerationError>>>,
}
impl FakeGenerator {
    pub fn with_responses(responses: Vec<Result<ModelOutput, GenerationError>>) -> Self {
        Self { call_count: AtomicUsize::new(0), responses: Mutex::new(responses) }
    }
    pub fn calls(&self) -> usize { self.call_count.load(Ordering::Relaxed) }
}
impl Generator for FakeGenerator {
    fn generate<'a>(&'a self, request: GenerationRequest) -> BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            self.call_count.fetch_add(1, Ordering::Relaxed);
            let mut guard = self.responses.lock().unwrap();
            if guard.is_empty() {
                Err(GenerationError::new(GenerationErrorKind::ProviderError, "FakeGenerator ran out of configured responses")
                    .with_correlation(request.session_id, request.correlation_id))
            } else {
                let res = guard.remove(0);
                res.map_err(|err| err.with_correlation(request.session_id, request.correlation_id))
            }
        })
    }
}
```
This is the exact "fail on Nth call" shape D-12/D-13 retry-scenario tests need — reuse directly for `GenerateAnswerNode`'s retry tests (the real `FakeGenerator` can be injected as-is), and copy this same `call_count`+`Mutex<Vec<Result<...>>>` shape for any new graph-query/dense-retrieval stall/fail-on-Nth-call double (RESEARCH.md Pitfall #3/Open Question 3).

---

### `engine/src/workflow/runner.rs` (WorkflowRunner, event-driven orchestrator)

**Analog:** `engine/src/generation/openrouter.rs` (per-attempt timeout wrapping) — the closest existing precedent for "wrap one async call in a timeout race," though no existing file orchestrates a multi-step sequence; `05-AI-SPEC.md` Section 3's Entry Point Pattern is the authoritative shape for the `select!`+timeout+cancel race, not re-derived here.

**Per-attempt timeout wrapping precedent** (`engine/src/generation/openrouter.rs:24,626`):
```rust
const GENERATION_TIMEOUT: Duration = Duration::from_secs(30); // openrouter.rs:24
// ...
tokio::time::timeout(self.config.timeout, self.execute_one_call(request)).await // openrouter.rs:626
```
Confirms: node-level timeout (D-17) must be a **separate, larger** config value than `GENERATION_TIMEOUT` — do not reuse it as `GenerateAnswerNode`'s wall-clock budget (RESEARCH.md Anti-Pattern, verified real bug risk).

**Cancellation vs. timeout disambiguation** — must use `tokio::select! { biased; _ = cancel.cancelled() => ..., res = timeout(...) => ... }`, NOT a bare `timeout()` call (which cannot distinguish D-22's `Timeout` from `Cancelled`). No existing codebase precedent for this exact pattern — follow `05-AI-SPEC.md` Section 3 verbatim.

**Tracing-span precedent to extend (not with new per-node spans, D-31)** (`engine/src/main.rs:1350`):
```rust
let query_span = tracing::info_span!("query_rag", graph_augmentation = tracing::field::Empty);
```
`d1_status`'s existing session/correlation-scoped `tracing::warn!` pattern (`main.rs:885`) should be mirrored for in-stream `NodeFailed` logging:
```rust
tracing::warn!(%session_id, %correlation_id, %error_kind, "QueryRAG infrastructure failure: {msg}");
```

---

### `engine/src/workflow/nodes/graph_context.rs` (pipeline stage, transform)

**Analog:** `engine/src/main.rs:1426-1448` (existing call site — reuse the outcome-enum match, wrap in own inner timeout per RESEARCH.md Common Pitfall #2)

**Existing call + outcome-match pattern (VERIFIED live)**:
```rust
let graph_outcome = attempt_graph_augmentation(
    &self.database,
    &query_embedding,
    &self.effective_settings.graph,
)
.await;

tracing::Span::current().record(
    "graph_augmentation",
    match &graph_outcome {
        GraphAugmentationOutcome::Succeeded { .. } => "succeeded",
        GraphAugmentationOutcome::NoMatchFound => "no_match_found",
        GraphAugmentationOutcome::AttemptedAndFailed { .. } => "attempted_and_failed",
    },
);

let graph_facts: Vec<prompt::GraphFactBlock> = match graph_outcome {
    GraphAugmentationOutcome::Succeeded { facts } => facts
        .into_iter()
        .map(|fact| prompt::GraphFactBlock { fact })
        .collect(),
    _ => vec![],
};
```
`attempt_graph_augmentation` is already infallible-by-construction (returns an outcome enum, never `Err`) — it has **no internal timeout of its own today**. Per RESEARCH.md's resolution recommendation (Common Pitfalls #2 / Open Question 1): give `ExtractGraphContextNode::run` its own inner `tokio::select!`/`timeout()` race around this call, and treat a timeout exactly like `AttemptedAndFailed` (empty `graph_context`, `Ok(())` returned to the runner) — this keeps D-09's "always runs, never required" contract uniform across both failure sub-cases. This is a semantic reading of D-09 flagged for confirmation, not a locked fact — call it out in the plan.

---

### `engine/src/workflow/nodes/retrieve.rs` (pipeline stage, transform)

**Analog:** `engine/src/retrieval/fusion.rs::fuse_candidates` + `engine/src/main.rs:1450-1495`

**Existing single-pass call site (VERIFIED live)**:
```rust
let dense_retriever = DenseRetriever::new(self.nodes.clone());
let dense_candidates = dense_retriever
    .query(&query_embedding, &query_request, &self.effective_settings.retrieval)
    .await?; // (error mapping omitted, see main.rs:1451-1476 for exact Status mapping)

let bm25_guard = self.bm25_index.read().await;
let bm25_candidates = bm25_guard
    .retrieve(&query_request, &self.effective_settings.retrieval)
    .await?;
drop(bm25_guard);

let fused = retrieval::fusion::fuse_candidates(
    dense_candidates,
    bm25_candidates,
    &self.effective_settings.retrieval,
)?;
```
D-07 requires looping this over the `QueryReformulator`'s `Vec<String>` and RRF-merging across variants (RESEARCH.md Pitfall #5 / Open Question 2 — explicit design choice needed: flatten-then-fuse vs. two-pass merge; NoOp reformulator (999.3 D-02) makes this behaviorally inert in v1, but the node shape must support N variants per D-07's rationale). D-08: only variant `[0]` is embedded (`main.rs:1395`, unchanged).

---

### `engine/src/workflow/nodes/generate.rs` (pipeline stage, request-response, owns D-12 retry)

**Analog:** `engine/src/main.rs:1561-1597` (existing call site + error-kind mapping) + `FakeGenerator` (reuse for tests, see Node pattern section above)

**Existing generation call + error mapping (VERIFIED live)**:
```rust
let model_output = self.generator.generate(gen_req).await.map_err(|err| {
    let (code, err_kind_str) = match err.kind {
        generation::GenerationErrorKind::InvalidRequest => (tonic::Code::InvalidArgument, "invalid_request"),
        generation::GenerationErrorKind::SupportedParameters => (tonic::Code::Internal, "supported_parameters"),
        generation::GenerationErrorKind::ProviderError => (tonic::Code::Internal, "provider_error"),
        generation::GenerationErrorKind::SchemaValidation => (tonic::Code::Internal, "schema_validation"),
        generation::GenerationErrorKind::Timeout => (tonic::Code::Internal, "timeout"),
        generation::GenerationErrorKind::Cancelled => (tonic::Code::Internal, "cancelled"),
        generation::GenerationErrorKind::SessionCorrelation => (tonic::Code::Internal, "session_correlation"),
    };
    d1_status(code, err.message(), &session_id, &correlation_id, err_kind_str)
})?;
```
`GenerateAnswerNode::run` should call `self.generator.generate(gen_req.clone()).await`, and on `Err`, retry exactly once with the byte-identical request (D-12) before mapping to `NodeError{ kind: LlmGenerationFailed, .. }`. No "retrying" event fires (D-15) — client sees nothing until the final `NodeCompleted`/`NodeFailed`. D-01: the `response_format`/`json_schema` structured-output call itself (`openrouter.rs:289-458`) stays unchanged — only the retry wrapper is new.

---

### `engine/src/main.rs` `query_rag` handler (controller, streaming)

**Analog:** itself, `engine/src/main.rs:1346-1708` (refactor in place)

**D-04 boundary to preserve exactly (ReceiveQuery stays synchronous, pre-stream)** — session/correlation ID minting + `QueryRequest::from_values` validation (lines 1354-1393) must remain before the `mpsc::channel`/`ReceiverStream` is opened. Malformed requests still return `d1_status`'s trailer-bearing `Status`:
```rust
fn d1_status(
    code: tonic::Code,
    message: impl Into<String>,
    session_id: &str,
    correlation_id: &str,
    error_kind: &str,
) -> Status {
    let msg = message.into();
    tracing::warn!(%session_id, %correlation_id, %error_kind, "QueryRAG infrastructure failure: {msg}");
    let mut status = Status::new(code, msg);
    let metadata = status.metadata_mut();
    if let Ok(val) = session_id.parse() { metadata.insert("x-lancet-session-id", val); }
    if let Ok(val) = correlation_id.parse() { metadata.insert("x-lancet-correlation-id", val); }
    if let Ok(val) = error_kind.parse() { metadata.insert("x-lancet-error-kind", val); }
    status
}
```
Do NOT extend this trailer mechanism to in-stream failures — those go through `NodeFailed`/`WorkflowCompleted(failed)` (D-05), an entirely separate in-band path.

**D-03 zero-evidence early return to preserve as runner-level short-circuit (NOT a no-op node)** (lines 1508-1547): when `final_candidates.is_empty()`, skip straight to `Complete` — `AssemblePrompt`/`GenerateAnswer` never even receive a `NodeStarted`. This must be `WorkflowRunner`-level control flow, not a node that immediately returns `Ok(())` (RESEARCH.md Anti-Pattern).

**embedder call + validation (lines 1395-1424)** — reuse as-is inside `ReformulateQueryNode`/embedding step, only variant `[0]` embedded per D-08.

---

### `gateway/main.go` `engine.QueryRAG` interface + `grpcEngine.QueryRAG` (streaming adapter)

**Analog:** `gateway/main.go:212-254` (`grpcEngine.Ingest`, only existing streaming client call, client-streaming shape) + `gateway/main.go:263-287` (`trailerError`, current unary `QueryRAG`)

**Current unary shape to replace** (lines 280-287):
```go
func (e grpcEngine) QueryRAG(ctx context.Context, req *pb.QueryRAGRequest) (*pb.QueryRAGResponse, error) {
    var trailer metadata.MD
    resp, err := e.client.QueryRAG(ctx, req, grpc.Trailer(&trailer))
    if err != nil {
        return resp, trailerError{err: err, trailer: trailer}
    }
    return resp, nil
}
```
`trailerError`/`trailerError.GRPCStatus()`/`.Trailer()` (lines 263-278) must be preserved for D-04's pre-stream-open failure path — a server-streaming client call still returns an `error` synchronously from `client.QueryRAG(ctx, req, ...)` if the stream itself fails to open (e.g. `InvalidArgument`), and that error should still be wrapped in `trailerError` exactly as today.

**Streaming client shape precedent (client-streaming `Ingest`, adapt to server-streaming)**:
```go
func (e grpcEngine) Ingest(ctx context.Context, id, filename, strategy string, chunkSize, chunkOverlap int, src io.Reader) IngestOutcome {
    stream, err := e.client.IngestDocument(ctx)
    if err != nil {
        return IngestOutcome{Err: err}
    }
    // ... stream.Send() loop ...
    resp, err := stream.CloseAndRecv()
    if err != nil {
        return IngestOutcome{Ambiguous: true, Err: err}
    }
    return IngestOutcome{}
}
```
For the new server-streaming `QueryRAG`, the analogous shape is `stream, err := e.client.QueryRAG(ctx, req)` returning a `grpc.ServerStreamingClient[WorkflowEvent]`-shaped stream, then the HTTP handler drives a `stream.Recv()` loop (see next section) instead of a single `stream.CloseAndRecv()`.

---

### `gateway/main.go` `queryRAG` HTTP handler (SSE forwarding — NO ANALOG, see below)

**Closest reference:** `gateway/main.go:653-715` (current unary handler, refactor in place) for the request-decode prefix (body decode, `DisallowUnknownFields`, `MaxBytesReader`) which is UNCHANGED by this phase:
```go
r.Body = http.MaxBytesReader(w, r.Body, maxRAGQueryBodyBytes)
defer r.Body.Close()

var body ragQueryRequestBody
dec := json.NewDecoder(r.Body)
dec.DisallowUnknownFields()
if err := dec.Decode(&body); err != nil { /* ... */ }
```
**Error-trailer-to-header forwarding (preserve for pre-stream-open failures only)**:
```go
resp, err := a.engine.QueryRAG(r.Context(), req)
if err != nil {
    if te, ok := err.(interface{ Trailer() metadata.MD }); ok {
        tr := te.Trailer()
        if vals := tr.Get("x-lancet-session-id"); len(vals) > 0 && vals[0] != "" {
            w.Header().Set("X-Lancet-Session-ID", vals[0])
        }
        // ... correlation-id, error-kind ...
    }
    if status.Code(err) == codes.InvalidArgument {
        http.Error(w, status.Convert(err).Message(), http.StatusBadRequest)
        return
    }
    http.Error(w, "engine query failed", http.StatusBadGateway)
    return
}
```
This block runs BEFORE any SSE headers are written — preserve exactly for D-04's boundary.

**No in-codebase SSE precedent** — RESEARCH.md Pattern 2 (net-new, web-sourced, MEDIUM confidence) is the pattern to follow:
```go
w.Header().Set("Content-Type", "text/event-stream")
w.Header().Set("Cache-Control", "no-cache")
w.Header().Set("Connection", "keep-alive")
w.WriteHeader(http.StatusOK)
flusher, ok := w.(http.Flusher)
if !ok {
    http.Error(w, "streaming unsupported", http.StatusInternalServerError)
    return
}
for {
    select {
    case <-r.Context().Done():
        return
    default:
    }
    event, err := stream.Recv()
    if err == io.EOF {
        return
    }
    if err != nil {
        return // no standard SSE error frame; close connection (D-21: no reconnect anyway)
    }
    if cp := event.GetCheckpoint(); cp != nil {
        go a.persistCheckpoint(cp) // D-27: fire-and-forget
    }
    payload, _ := json.Marshal(toWorkflowEventDTO(event))
    fmt.Fprintf(w, "data: %s\n\n", payload)
    flusher.Flush()
}
```
Spot-check A3 (RESEARCH.md Assumptions Log) during Wave 0: verify chi's `middleware.Timeout` doesn't double-write/corrupt an already-headers-sent SSE stream — not verified against chi source this session.

---

### `gateway/main.go` route registration (`/rag/query` route-scoped timeout)

**Analog:** `gateway/main.go:462-470`

**Current global timeout (VERIFIED live) — must NOT apply unmodified to `/rag/query`**:
```go
func (a app) routes() http.Handler {
    r := chi.NewRouter()
    r.Use(middleware.RequestID, middleware.RealIP, middleware.Recoverer, middleware.Timeout(60*time.Second))
    r.Get("/health", a.health)
    r.Post("/documents", a.createDocument)
    r.Get("/documents/{id}", a.getDocument)
    r.Post("/rag/query", a.queryRAG)
    return r
}
```
This is RESEARCH.md's highest-priority Go-side finding (Common Pitfall #1): `GenerateAnswer`'s node budget (~65s incl. retry) already exceeds the blanket 60s. Use chi's per-route grouping (`r.With(middleware.Timeout(d)).Post("/rag/query", a.queryRAG)` inside a route group, or exempt `/rag/query` from the blanket `r.Use` and apply the other three middlewares directly) sized to exceed the sum of all five D-17 node timeouts plus slack — must be an explicit planning decision, not left as a residual default.

---

### `gateway/db/schema.hcl` (+ `workflow_checkpoints` table)

**Analog:** `gateway/db/schema.hcl` (`document_reconciliation_intents`, lines 82-134; `documents`, lines 29-80)

**Existing table-block convention (VERIFIED live)**:
```hcl
table "document_reconciliation_intents" {
  schema = schema.public
  column "document_id" {
    null = false
    type = varchar(255)
  }
  column "desired_status" {
    null = false
    type = varchar(50)
  }
  column "created_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  primary_key {
    columns = [column.document_id]
  }
}
```
New `workflow_checkpoints` table per RESEARCH.md Pattern 3 (net-new `jsonb` column, no existing precedent — `pgx/v5` supports `jsonb` natively via `pgtype.JSONB`, no new Go dependency):
```hcl
table "workflow_checkpoints" {
  schema = schema.public
  column "trace_id" {
    null = false
    type = varchar(255)   # = correlation_id, D-29
  }
  column "node_name" {
    null = false
    type = varchar(100)
  }
  column "context_snapshot" {
    null = false
    type = jsonb            # D-28: full accumulated snapshot, not a diff
  }
  column "created_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  # No single-column PK -- composite (trace_id, node_name, created_at), or a
  # surrogate serial id column following the `users` table's precedent
  # (schema.hcl lines 5-27) if a surrogate key is preferred -- Claude's Discretion.
}
```

---

### `gateway/db/query.sql` (+ `InsertWorkflowCheckpoint`)

**Analog:** `gateway/db/query.sql:10-30` (`InsertDocument`)

**Existing single-row insert convention (VERIFIED live)**:
```sql
-- name: InsertDocument :one
INSERT INTO documents (
  id,
  filename,
  file_size,
  status,
  chunk_count,
  chunk_strategy,
  chunk_size,
  chunk_overlap
) VALUES (
  $1, $2, $3, 'queued', 0, $4, $5, $6
)
RETURNING *;
```
Mirror this shape for `InsertWorkflowCheckpoint :one` (`trace_id`, `node_name`, `context_snapshot` jsonb param, `created_at` defaulted). No `ON CONFLICT`/upsert needed — D-28 appends one row per node boundary (multiple rows share a `trace_id`), unlike `CreateReconciliationIntent`'s `ON CONFLICT (document_id) DO UPDATE` (query.sql:48-75), which does NOT apply here.

## Shared Patterns

### Error taxonomy / typed error structs (Rust)
**Source:** `engine/src/generation/mod.rs:404-456` (`GenerationError`/`GenerationErrorKind`)
**Apply to:** `NodeError`/`NodeErrorKind` (all workflow node files) — same `kind` enum + `message`/`session_id`/`correlation_id` struct shape, `Display`, `std::error::Error`, no `thiserror`/`anyhow` (matches `M-ERRORS-CANONICAL-STRUCTS`, `rust-guidelines.md:2966`).

### Correlation-ID-scoped tracing on failure (Rust)
**Source:** `engine/src/main.rs:885` (inside `d1_status`)
```rust
tracing::warn!(%session_id, %correlation_id, %error_kind, "QueryRAG infrastructure failure: {msg}");
```
**Apply to:** every `NodeFailed` emission path in `WorkflowRunner` — log with the same `%session_id, %correlation_id` structured-field convention before emitting the event.

### `Arc<dyn Trait>` dependency injection (Rust)
**Source:** `engine/src/main.rs:863-875` (`LancetServiceImpl` struct fields: `generator: Arc<dyn generation::Generator>`, `embedder: Arc<dyn EmbeddingProvider>`, `reranker: Arc<dyn rerank::Reranker>`)
**Apply to:** `QueryReformulator` port (ORCH-05) — constructed once, shared across requests, same `Arc<dyn Trait>` shape.

### Pre-stream vs. in-stream error reporting boundary (Rust + Go)
**Source:** `engine/src/main.rs:877-898` (`d1_status`, trailer metadata) + `gateway/main.go:693-704` (trailer-to-header forwarding)
**Apply to:** `query_rag` handler (Rust) and `queryRAG` HTTP handler (Go) — `d1_status`'s trailer mechanism covers ONLY `ReceiveQuery`'s pre-stream validation failures (D-04); everything after the stream opens uses the new in-band `NodeFailed`/`WorkflowCompleted(failed)` WorkflowEvent path (D-05) instead. Do not conflate the two mechanisms in either language.

### TOML + env-var config override convention
**Source:** `config/config.toml`'s existing `generation_timeout_secs = 30` key (grep-verified per RESEARCH.md)
**Apply to:** all five new per-node timeout keys (D-17), retry count, and checkpoint-related config. RESEARCH.md Common Pitfall #4: the existing `_secs` whole-integer convention blocks sub-second test overrides — planner must explicitly choose `*_timeout_ms` (u64 milliseconds) or fractional-`_secs` (f64) for the new keys, not silently inherit the old convention as-is.

### Fire-and-forget goroutine dispatch (Go)
**Source:** no direct existing precedent (closest is `durableReconciler`'s background-loop shape, `gateway/main.go:350-460`, though that's a ticker-driven loop, not per-event fire-and-forget)
**Apply to:** checkpoint persistence inside the SSE forwarding loop — `go a.persistCheckpoint(cp)` per D-27, must not block `stream.Recv()`/`flusher.Flush()`.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `gateway/main.go` SSE-forwarding loop body (`http.Flusher` + `r.Context().Done()` select) | controller | streaming | Zero existing SSE precedent in this codebase — the only existing streaming RPC (`IngestDocument`) is client-streaming, not server-streaming/SSE. Follow `05-RESEARCH.md` Pattern 2 (web-sourced, MEDIUM confidence) instead of an in-repo analog. |
| `engine/src/workflow/runner.rs`'s `tokio::select! { cancel vs. timeout }` race | service | event-driven | No existing multi-step orchestrator in this codebase; `05-AI-SPEC.md` Section 3 is the authoritative source for this exact shape, not a live-code analog. |

## Metadata

**Analog search scope:** `engine/src/main.rs`, `engine/src/generation/mod.rs`, `engine/src/generation/openrouter.rs`, `engine/src/retrieval/fusion.rs`, `gateway/main.go`, `gateway/db/schema.hcl`, `gateway/db/query.sql`, `proto/lancet/v1/lancet.proto`
**Files scanned:** 8 (all directly cited and verified live in `05-RESEARCH.md`; no additional Glob/Grep sweep was needed since RESEARCH.md's Sources section already enumerates the exhaustive, line-verified set of existing files relevant to this phase)
**Pattern extraction date:** 2026-08-10
