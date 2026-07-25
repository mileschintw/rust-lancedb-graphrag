# Phase 2: Ingestion, Chunking & Vector Storage - Pattern Map

**Mapped:** 2026-07-25  
**Mode:** Verification gap closure  
**Files analyzed:** 7 implicated source/test artifacts  
**Analogs found:** 7 / 7 (one capability has no exact repository analog)

## Scope Derived from Verification

The gap-closure plan should stay focused on:

1. DATA-08: make edge `summary` and `summary_vector` nullable and persist null placeholders.
2. Make document replacement recoverable across the `documents`, `nodes`, and `edges` write boundaries, with deterministic failure-injection coverage.
3. Reconcile gateway metadata when engine enqueue fails and when a conditional terminal update loses a race.
4. Exercise the existing live PostgreSQL/engine/gateway/OpenRouter verifier.

The broader Phase 2 ingestion, chunking, embedding, queueing, and configuration decisions are already implemented and verified. They are context, not new work.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `engine/src/db/mod.rs` | model/config | transform + CRUD | `nodes_schema()` in the same file, lines 111-136 | exact |
| `engine/src/db/tests.rs` | test | CRUD + transform | schema initialization/drift tests in the same file, lines 21-57 | exact |
| `engine/src/main.rs` | service + test | batch + CRUD | `EmbeddingProvider` seam and worker replacement tests in the same file, lines 283-297 and 684-813 | role-match |
| `gateway/main.go` | controller + service | request-response + CRUD | `postgresStore.UpdateStatus` and `getDocument` in the same file, lines 99-116 and 223-248 | exact |
| `gateway/main_test.go` | test | request-response | `fakeStore`, `engineFunc`, and handler tests in the same file, lines 24-46 and 67-163 | exact |
| `gateway/db/document_test.go` | test | CRUD | transaction-isolated PostgreSQL integration test in the same file, lines 12-70 | exact |
| `verify-ingestion.sh` | test/utility | batch + request-response | existing upload/poll/PostgreSQL reconciliation flow, lines 22-68 | exact |

## Pattern Assignments

### `engine/src/db/mod.rs` (model/config, transform + CRUD)

**Modification locus:** `edges_schema()`, lines 139-150.

**Analog:** nullable node placeholder fields in `nodes_schema()`, lines 123-135.

**Schema pattern to copy:**

```rust
Field::new("title", DataType::Utf8, true),
Field::new("section_path", DataType::Utf8, true),
// ...
Field::new("summary", DataType::Utf8, true),
Field::new("summary_vector", vector(), true),
Field::new("unsummarized_refs", list(DataType::Utf8), true),
```

Apply the same third-argument nullability convention to the edge placeholder fields:

```rust
Field::new("summary", DataType::Utf8, true),
Field::new("summary_vector", vector(), true),
```

**Shared vector type pattern** (lines 93-98):

```rust
fn vector() -> DataType {
    DataType::FixedSizeList(
        Arc::new(Field::new("item", DataType::Float32, true)),
        EMBEDDING_DIMENSIONS,
    )
}
```

Do not duplicate the 2048-dimension type inline; keep using `vector()` so nodes, edges, and schema validation remain aligned.

**Schema drift error pattern** (lines 78-90):

```rust
if actual.fields() != expected.fields() {
    return Err(format!(
        "LanceDB schema drift detected for {name}: expected {:?}, found {:?}",
        expected.fields(),
        actual.fields()
    ));
}
```

Changing nullability intentionally causes existing incompatible tables to fail fast, which is the locked D-22 behavior.

---

### `engine/src/db/tests.rs` (test, CRUD + transform)

**Analog:** direct schema setup plus fail-fast assertion, lines 35-57.

**Test structure to copy:**

```rust
#[tokio::test]
async fn schema_drift_fails_database_initialization() {
    let path = database_path("drift");
    let connection = lancedb::connect(&path).execute().await.unwrap();
    connection
        .create_empty_table(
            "documents",
            Arc::new(Schema::new(vec![Field::new(
                "wrong_column",
                DataType::Utf8,
                false,
            )])),
        )
        .execute()
        .await
        .unwrap();

    let error = match DatabaseManager::initialize(&path).await {
        Ok(_) => panic!("schema drift must fail initialization"),
        Err(error) => error,
    };
    assert!(error.contains("schema drift detected for documents"));
    let _ = std::fs::remove_dir_all(path);
}
```

Add explicit field-level assertions against `edges_schema()`:

- `field_with_name("summary").unwrap().is_nullable()`
- `field_with_name("summary_vector").unwrap().is_nullable()`
- retain a negative assertion for a required edge field such as `document_id`

This avoids the verification failure where initialization tests merely validated code against the same incorrect expected schema.

**Temporary database convention** (lines 10-19):

```rust
std::env::temp_dir()
    .join(format!("lancet-{test_name}-{nonce}"))
    .to_string_lossy()
    .into_owned()
```

Use unique temporary paths and preserve the existing explicit cleanup style.

---

### `engine/src/main.rs` (service + test, batch + CRUD)

**Modification loci:** `replace_document()`, lines 320-549; worker tests, lines 720-851.

#### Nullable persistence pattern

**Analog:** schema-driven null-array creation for node placeholders, lines 396-402 and 461-464.

```rust
let node_schema = nodes.schema().await.map_err(|error| error.to_string())?;
let nullable = |name: &str| {
    let field = node_schema
        .field_with_name(name)
        .expect("validated nodes schema must contain field");
    new_null_array(field.data_type(), chunks.len())
};

// ...
nullable("community_ids"),
Arc::new(StringArray::from(vec![Some(""); chunks.len()])),
nullable("summary_vector"),
nullable("unsummarized_refs"),
```

For edges, load the edge schema once, create null arrays from the schema field types, and place those arrays in the `summary` and `summary_vector` positions. Do not use empty strings or copied embedding vectors as stand-ins for missing summaries.

#### Failure-injection seam pattern

**Analog:** object-safe async dependency seam, lines 283-297.

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

Use this same dependency-seam style for the replacement commit boundary if failure injection cannot be expressed cleanly through LanceDB itself. The test double should fail at named boundaries (for example, after staging documents, nodes, or edges), not by timing.

**Test-double pattern** (lines 684-710):

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

Keep tests deterministic and local; no OpenRouter calls belong in worker persistence tests.

#### Replacement behavior test pattern

**Analog:** same-ID replacement test, lines 755-813.

```rust
for raw_data in [
    b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
    b"replacement".to_vec(),
] {
    sender
        .send(IngestionJob {
            document_id: document_id.clone(),
            filename: "document.md".into(),
            raw_data,
            metadata: HashMap::new(),
        })
        .await
        .unwrap();
}
// ...
assert_eq!(state.status, "completed");
assert_eq!(state.chunk_count, 1);
```

Extend this shape with a write-boundary failure and assert both:

1. the prior complete version remains queryable after the failed replacement, and
2. retrying the same document ID converges to one document version with no stale nodes/edges.

**Do not copy:** the current delete-first sequence at lines 342-354. Verification identified it as the integrity risk being closed.

---

### `gateway/main.go` (controller + service, request-response + CRUD)

**Modification loci:** `createDocument()`, lines 184-221; `getDocument()`, lines 223-249.

#### Transactional status write pattern

**Analog:** `postgresStore.UpdateStatus`, lines 102-116.

```go
tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{})
if err != nil {
    return db.Document{}, err
}
defer tx.Rollback(ctx)
doc, err := db.New(tx).UpdateDocumentStatus(ctx, p)
if err != nil {
    return db.Document{}, err
}
if err := tx.Commit(ctx); err != nil {
    return db.Document{}, err
}
return doc, nil
```

On any engine enqueue/stream failure after `Insert`, use the store status operation to compensate the queued row to `failed`, with a useful error message. Preserve the externally required mappings:

- gRPC `ResourceExhausted` → HTTP 429
- other engine ingestion errors → HTTP 502

The compensation failure should be logged with document ID and the original engine error; it must not erase the original HTTP mapping.

#### Lost-race recovery pattern

**Analogs:** `postgresStore.Get`, lines 99-101, and conditional SQL in `gateway/db/query.sql`, lines 32-46.

```go
func (s postgresStore) Get(ctx context.Context, id string) (db.Document, error) {
    return db.New(s.pool).GetDocument(ctx, id)
}
```

```sql
UPDATE documents
SET
  status = $2,
  chunk_count = $3,
  error_message = $4,
  updated_at = CURRENT_TIMESTAMP
WHERE id = $1
  AND status IN ('queued', 'processing')
RETURNING *;
```

`UpdateDocumentStatus` can return `pgx.ErrNoRows` when another request already made the row terminal. In that specific case, re-read with `Get` and return the terminal row. Continue treating other update errors as HTTP 500.

#### Existing handler flow to preserve

From lines 233-248:

```go
if doc.Status == "queued" || doc.Status == "processing" {
    state, err := a.engine.IngestionStatus(r.Context(), doc.ID)
    // ...
    if state.GetStatus() == "completed" || state.GetStatus() == "failed" {
        errText := pgtype.Text{String: state.GetErrorMessage(), Valid: state.GetErrorMessage() != ""}
        doc, err = a.store.UpdateStatus(r.Context(), db.UpdateDocumentStatusParams{
            ID: doc.ID, Status: state.GetStatus(),
            ChunkCount: state.GetChunkCount(), ErrorMessage: errText,
        })
        // ...
    }
}
```

Keep terminal-only PostgreSQL reconciliation; do not begin persisting intermediate `processing` results as part of this gap closure.

---

### `gateway/main_test.go` (test, request-response)

**Analog:** stateful fake store, lines 24-46.

```go
type fakeStore struct {
    document db.Document
    inserted *db.InsertDocumentParams
    updated  *db.UpdateDocumentStatusParams
}

func (s *fakeStore) UpdateStatus(_ context.Context, p db.UpdateDocumentStatusParams) (db.Document, error) {
    s.updated = &p
    s.document.Status = p.Status
    s.document.ChunkCount = p.ChunkCount
    s.document.ErrorMessage = p.ErrorMessage
    return s.document, nil
}
```

Extend this fake minimally with configurable `insert`, `get`, or `update` errors/call counts needed by the new cases. Keep assertions at the HTTP boundary plus state-change assertions on the fake.

**Engine failure injection pattern** (lines 67-83 and 142-155):

```go
engine := engineFunc{ingest: func(context.Context, string, string, []byte) error {
    return status.Error(codes.ResourceExhausted, "full")
}}
```

Add handler tests for:

- full queue marks the inserted row failed and still returns 429;
- non-`ResourceExhausted` enqueue failure marks it failed and returns 502;
- compensation failure is observable to the logger/test seam without changing the original response mapping;
- `UpdateStatus` returning `pgx.ErrNoRows` triggers `Get`, and the handler returns the concurrently written terminal document with HTTP 200;
- a non-race update error still returns HTTP 500.

Follow the existing `httptest.NewRecorder()` + real router invocation style rather than calling handlers directly.

---

### `gateway/db/document_test.go` (test, CRUD)

**Analog:** environment-gated, rollback-isolated live PostgreSQL test, lines 12-33.

```go
databaseURL := os.Getenv("TEST_DATABASE_URL")
if databaseURL == "" {
    t.Skip("TEST_DATABASE_URL is required for database integration tests")
}

ctx := context.Background()
pool, err := pgxpool.New(ctx, databaseURL)
// ...
tx, err := pool.Begin(ctx)
// ...
defer func() {
    if rollbackErr := tx.Rollback(ctx); rollbackErr != nil && rollbackErr != pgx.ErrTxClosed {
        t.Errorf("rollback transaction: %v", rollbackErr)
    }
}()
```

Use this fixture to verify the conditional-update race contract against real PostgreSQL:

1. insert a queued document;
2. make it terminal once;
3. prove a second conditional update returns `pgx.ErrNoRows`;
4. re-read and verify the first terminal result is intact.

Keep cleanup transaction-scoped so the suite remains repeatable.

---

### `verify-ingestion.sh` (test/utility, batch + request-response)

**Existing artifact to run; modification is not required unless the plan adds diagnostics.**

**Upload and polling pattern** (lines 22-58):

```bash
response="$(curl --fail --silent --show-error \
  -X POST \
  -F "file=@${sample_file};filename=$(basename "$sample_file")" \
  "${gateway_url}/documents")"
document_id="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ID"])')"
status_url="${gateway_url}/documents/${document_id}"

for ((attempt = 1; attempt <= poll_limit; attempt++)); do
  response="$(curl --fail --silent --show-error "$status_url")"
  status="$(printf '%s' "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["Status"])')"
  # terminal-state assertions...
done
```

**PostgreSQL reconciliation assertion** (lines 60-66):

```bash
database_status="$(docker compose exec -T db \
  psql -U postgres -d lancet -Atc \
  "SELECT status || ':' || chunk_count FROM documents WHERE id = '${document_id}'")"
if [[ "$database_status" != "completed:${chunk_count}" ]]; then
  echo "PostgreSQL state mismatch: expected completed:${chunk_count}, got ${database_status:-<missing>}" >&2
  exit 1
fi
```

Run this only when PostgreSQL, engine, gateway, and a real `OPENROUTER_API_KEY` are available. It is the exact live behavior check missing from verification.

## Shared Patterns

### Error Propagation

**Rust source:** `engine/src/main.rs`, lines 166-168 and 326-335.  
Use `Result<_, String>` inside worker/persistence code, convert external library errors with contextual `map_err`, and let `spawn_worker` record the final `failed` status.

**Go source:** `gateway/main.go`, lines 205-217 and 223-248.  
Map known gRPC/database conditions explicitly at the handler boundary; log operational detail, return stable client-facing messages.

### Transaction Boundaries

**Source:** `gateway/main.go`, lines 84-116.  
All PostgreSQL mutations begin a transaction, defer rollback, execute through `db.New(tx)`, and commit explicitly.

### Schema-Driven Nullable Arrays

**Source:** `engine/src/main.rs`, lines 396-402.  
Derive null arrays from the validated Arrow field type with `new_null_array`; this prevents a placeholder array from drifting from its schema.

### Test Isolation

**Rust sources:** `engine/src/db/tests.rs`, lines 10-19; `engine/src/main.rs`, lines 713-718.  
Use a unique temporary LanceDB directory per test and remove it after all handles are dropped.

**Go source:** `gateway/db/document_test.go`, lines 12-33.  
Gate live tests on `TEST_DATABASE_URL` and roll back the test transaction.

## No Exact Analog Found

| Capability | Affected File | Reason | Planner Guidance |
|---|---|---|---|
| Recoverable multi-table LanceDB replacement | `engine/src/main.rs` | The repository has no staging/version-switch or transaction abstraction across `documents`, `nodes`, and `edges`. The only current implementation is the delete-first sequence verification rejected. | Use the verification recommendation: staged/versioned rows with an active switch, or another protocol that demonstrably preserves the old version through any injected write-boundary failure. Reuse the existing dependency-seam and deterministic test-double patterns above. |

No new third-party dependency is justified solely by existing patterns. If the chosen LanceDB API supports a native atomic primitive, verify its behavior against the pinned crate before planning around it.

## Planner Guardrails

- Do not broaden this plan into reworking chunking, OpenRouter retry/concurrency, queue capacity, protobuf contracts, or config loading; those behaviors already passed verification.
- Do not treat empty strings or copied embeddings as nullable edge summary placeholders.
- Do not weaken fail-fast schema drift detection to accommodate old tables.
- Do not turn a conditional-update race into an unconditional overwrite; recover by re-reading the winning terminal row.
- Do not claim live E2E verification unless `verify-ingestion.sh` actually runs against the full service stack and real OpenRouter credentials.

## Metadata

**Analog search scope:** `engine/src`, `gateway`, `gateway/db`, repository-root verification scripts  
**Files scanned:** 18 source/test/config candidates; stopped after 5 strong pattern families  
**Pattern extraction date:** 2026-07-25
