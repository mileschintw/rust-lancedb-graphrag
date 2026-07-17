# Phase 2: Ingestion, Chunking & Vector Storage - Context

**Gathered:** 2026-07-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Ingest text/markdown files asynchronously, parse structure-aware markdown elements, generate vector embeddings using OpenRouter's API, and store chunks/documents in embedded LanceDB instance, managing document metadata and state updates within the Go API gateway.

</domain>

<decisions>
## Implementation Decisions

### Ingestion API & Go Database Operations
- **D-01:** Go gateway HTTP upload API accepts file uploads via `multipart/form-data`.
- **D-02:** Go gateway persists comprehensive metadata in PostgreSQL: document ID, filename, file size, status (`processing`/`completed`/`failed`), chunk count, and timestamps.
- **D-03:** Go gateway reads file bytes and streams them over gRPC using 64KB fixed-size buffers to optimize memory usage.
- **D-04:** Ingested documents are added to a shared global corpus (global access, not session-isolated).
- **D-05:** SQL transactions are used in the Go gateway for all document metadata operations to ensure atomic commits and prepare for future relational complexity.

### Chunking Strategy & Configuration
- **D-06:** Chunking parameters (strategy, size, overlap) are configurable per-document via request metadata.
- **D-07:** The default fallback chunking strategy is `Structure-aware chunking` (splits by markdown sections/paragraphs first).
- **D-08:** Chunker uses Markdown AST parsing (using the `pulldown-cmark` library in Rust) to recognize headers (H1/H2/H3) and paragraphs/double newlines as splitting markers.
- **D-09:** Default chunk size is 500 characters and default overlap is 50 characters.

### Execution Model & Background Worker
- **D-10:** Ingestion is asynchronous. The gRPC `IngestDocument` handler queues requests to a bounded Tokio channel (capacity 100) and returns immediately with a `success=true` and `message="queued"` status.
- **D-11:** If the bounded queue is full, the gRPC server returns a `RESOURCE_EXHAUSTED` status code with the message "Ingestion queue full", which the Go gateway maps to an HTTP 429 Too Many Requests status code.
- **D-12:** Go-only database access is enforced: only Go connects to PostgreSQL. The Rust engine does not touch PostgreSQL.
- **D-13:** Go gateway polls the ingestion status from the Rust engine using a new gRPC endpoint `GetIngestionStatus` (which returns status `queued`/`processing`/`completed`/`failed` and optional `error_message`), updating PostgreSQL state accordingly.
- **D-14:** Background worker queue runs a single sequential consumer task spawned via `tokio::spawn` at startup to prevent race conditions on storage writes.
- **D-15:** Background worker queue supports graceful shutdown: allows the currently processing document to finish indexing and write before shutting down, while discarding pending requests in the queue.
- **D-16:** Background worker logs progress and errors using context-rich tracing spans (with document ID and step details) via the `tracing` library.

### Vector Embedding & LanceDB Schema
- **D-17:** OpenRouter API is the sole provider for generating embeddings, with no mock fallback.
- **D-18:** Target embedding model is `nvidia/llama-nemotron-embed-vl-1b-v2:free` which produces embeddings with a dimension of 2048.
- **D-19:** HTTP client retry policy for OpenRouter calls: timeout of 10s per call, retry up to 3 times with exponential backoff starting at 1 second.
- **D-20:** OpenRouter calls are sent concurrently in batches (up to 5 concurrent HTTP requests per document ingestion) to speed up ingestion, relying on the retry logic to handle rate limits.
- **D-21:** LanceDB table connection and schemas (for `nodes` and `edges`) are initialized on Rust engine startup, failing fast on configuration errors.
- **D-22:** If existing LanceDB schemas drift or mismatch with code definitions, the engine fails fast on startup with a clear error message, requiring manual user intervention (no auto-wipe).
- **D-23:** LanceDB `nodes` table schema explicitly defines structured columns: `document_id` (string), `chunk_id` (string), `chunk_index` (int32), `char_start` (int32), `char_end` (int32), `embedding` (FixedSizeList of 32-bit floats with dimension 2048), `token_estimate` (int32), `token_estimate_scheme` (string), `token_estimate_version` (string), and optional/nullable columns: `title` (string), `section_path` (string), `page_start` (int32), `page_end` (int32), `content_hash` (string), `chunker_version` (string), `embedding_model` (string), `ingested_at` (int64), `content_type` (string).
- **D-24:** LanceDB `documents` table stores raw uploaded document contents as a Binary Blob column to support non-text files in future phases. Chunks link to this table via the `document_id` string column. Re-uploading a document with an existing `document_id` performs an Overwrite/Upsert (deletes the old document and associated chunks before writing new ones).
- **D-25:** Token count estimation uses `tiktoken-rs` with the `o200k_base` encoding, saved under the column `token_estimate`, with auxiliary tracking columns `token_estimate_scheme` and `token_estimate_version`.

### Configuration Management
- **D-26:** Config files are stored in TOML format in a shared `/config` root directory: `config.toml`, `config.dev.toml`, `config.prod.toml`, and `config.example.toml`.
- **D-27:** Binaries look up the config folder via environment variable `LANCET_CONFIG_DIR`, falling back to the workspace root if unset.
- **D-28:** Active configuration environment is selected via the environment variable `LANCET_ENV` (defaults to dev; if set to `prod`, overrides are loaded from `config.prod.toml`).
- **D-29:** Configurations are managed using `viper` in Go and the `config` crate in Rust. Values are overwritten if environment variables with the same name (prefixed with `LANCET_` and using nested double underscores, e.g. `LANCET_STORAGE__PATH`) exist.
- **D-30:** In Docker Compose, the host `/config` directory is shared with containers via read-only volume mounts.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Decisions
- [.discussion/final_implementation_decision_document.md](file:///c:/Users/user3/repos/lancet/.discussion/final_implementation_decision_document.md) — Main architecture split, boundaries, and tech stack choices.
- [.discussion/lightweight_state_machine_plan.md](file:///c:/Users/user3/repos/lancet/.discussion/lightweight_state_machine_plan.md) — Reference for future orchestration states and integration patterns.

### Requirements & Roadmap
- [.planning/REQUIREMENTS.md](file:///c:/Users/user3/repos/lancet/.planning/REQUIREMENTS.md) — Main project requirements list.
- [.planning/ROADMAP.md](file:///c:/Users/user3/repos/lancet/.planning/ROADMAP.md) — Milestone roadmap and phase success criteria.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `engine/src/main.rs`: Contains the tonic gRPC service implementation template which will be modified to support the asynchronous Tokio channel ingestion worker.

### Established Patterns
- gRPC Protobuf definitions: Defined in `proto/lancet/v1/lancet.proto` and compiled using `buf`.

### Integration Points
- `/gateway`: The Go API gateway will need routes for document upload (`POST /documents`) and querying status, using `viper` for config.
- `/engine`: The Rust engine will implement the background Toko task, using the `config` crate for config.
- `/proto`: The shared Protobuf contract will be extended to add the `GetIngestionStatus` RPC call and its request/response messages.

</code_context>

<specifics>
## Specific Ideas

- OpenRouter API integration uses `nvidia/llama-nemotron-embed-vl-1b-v2:free` model with 2048-dimension embeddings.
- Concurrency limit is set to 5 concurrent HTTP calls to OpenRouter per ingestion request, with exponential backoff on retry.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope.

</deferred>

---

*Phase: 2-Ingestion, Chunking & Vector Storage*
*Context gathered: 2026-07-17*
