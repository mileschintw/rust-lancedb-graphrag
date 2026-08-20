# Phase 2: Ingestion, Chunking & Vector Storage - Context

**Gathered:** 2026-07-17
**Status:** Gap closure replanning; refreshed review disposition ADR accepted 2026-07-29

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
- **D-19:** HTTP client retry policy for OpenRouter calls: timeout of 10 seconds per call, then three retries after the initial request for four maximum attempts total, with 1/2/4-second exponential backoff.
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

### Accepted Verification Disposition (2026-07-29)
- **D-31:** The accepted ADR at `.discussion/decisions/phase-02-verification-disposition.md` is authoritative over the older severity/disposition text in `02-REVIEW.md` and `02-VERIFICATION.md`.
- **D-32:** Phase 02 ships CR-01, CR-02, CR-03, and CR-06 with the ADR's concrete behavioral acceptance criteria.
- **D-33:** Phase 02 ships WR-01 and WR-02 by consolidating privacy validation and fixtures in Python, removing the Node verification dependency and deleting the superseded Node test.
- **D-34:** Phase 02 ships WR-03 only for the exact Phase 02 behaviors still in scope, including actual inspector-argument capture, non-finite embedding fixtures (BU-03), and real missing-schema-field rollback/worker-survival proof (BU-04); it does not pull deferred BU-01 or BU-02 proof into Phase 02.
- **D-35:** Phase 02 ships WR-04 by parsing committed TOML strictly, requiring a non-empty `engine.lancedb_path`, resolving relative paths from the repository root, and failing closed without invoking the inspector on any configuration error.
- **D-36:** Phase 02 ships WR-05 through a read-only LanceDB open-and-validate path that cannot create, restore, or mutate tables.
- **D-37:** CR-04 receives only the accepted local-first guardrail in Phase 02: bind the gateway explicitly to loopback and document local-only exposure. Authentication, authorization, TLS, quotas, and non-loopback deployment remain `DEBT-CR-04`.
- **D-38:** CR-05 resource bounds remain `DEBT-CR-05` while the service is loopback-only, trusted, single-user, manually invoked, and limited to intended local uploads.
- **D-39:** Complete run-window behavioral proof remains `DEBT-BU-01` until v1 MVP closure or until the live gate becomes release, CI-release, public/shared-deployment, or audit evidence.
- **D-40:** Full caller-owned input preservation proof remains `DEBT-BU-02` until v1 MVP closure or before claiming safety for arbitrary user-owned source files.
- **D-41:** Production runtime remains Go gateway, Rust engine, PostgreSQL, LanceDB, and configured embedding-provider access. Python is verification-only; Node is not a runtime or verification dependency after WR-01/WR-02.
- **D-42:** The four deferred records are accepted known debt and are non-blocking for Phase 02 while their triggers remain false; an immediate trigger overrides their Phase 6/v1 target.

### Refreshed Review Disposition (ADR-02-002, 2026-07-29)
- **D-43 (CR-01):** Ship camel-case boundary canonicalization in the Python privacy classifier. `rawContent`, `storedDocumentText`, `authorizationHeader`, `bearerToken`, `chunkContent`, and `credentialValue` must map to the existing prohibited field classes; the fail-first probe must reject `{"rawContent":"do-not-publish"}` without printing the value.
- **D-44 (CR-02):** Ship fixture-scoped database cleanup. No test may issue an unqualified `DELETE FROM documents`; cleanup is limited to test-created IDs (or an isolated temporary database/schema), and a sentinel-row regression must prove unrelated rows survive.
- **D-45 (CR-03):** Supersede D-15's pending-request discard behavior. Graceful shutdown must stop new sends and drain or durably requeue every acknowledged job; engine startup must recover unprocessed durable staging, and gateway polling must not translate engine `NotFound` into PostgreSQL `failed` while matching unprocessed durable staging exists.
- **D-46 (WR-01):** Ship an engine-owned `MAX_CHUNK_SIZE = 1048576` enforced by Rust with gRPC `InvalidArgument`; the Go gateway mirrors the same ceiling only as a thin pre-persistence interface guard using bounded integer parsing so no `int32` wrap can be stored.
- **D-47 (WR-02):** Ship parameterized live-evidence runtime paths. Tests must inject temporary challenge/evidence paths, preserve any real-path sentinel byte-for-byte, and never write outside their fixture paths.
- **D-48 (architecture):** All chunking, RAG, vector, ingestion-queue, and recovery semantics remain owned by the Rust engine. The Go gateway remains a thin HTTP/gRPC/PostgreSQL-status interface and must not acquire chunking semantics.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Decisions
- [.discussion/final_implementation_decision_document.md](../../../.discussion/final_implementation_decision_document.md) — Main architecture split, boundaries, and tech stack choices.
- [.discussion/lightweight_state_machine_plan.md](../../../.discussion/lightweight_state_machine_plan.md) — Reference for future orchestration states and integration patterns.
- [.discussion/decisions/phases/02/2026-07-29-ADR-02-002-refreshed-review-disposition.md](../../../.discussion/decisions/phases/02/2026-07-29-ADR-02-002-refreshed-review-disposition.md) — Accepted source of truth for the five refreshed review findings, their concrete acceptance criteria, and the Rust-engine/Go-gateway responsibility boundary.

### Requirements & Roadmap
- [.planning/REQUIREMENTS.md](../../REQUIREMENTS.md) — Main project requirements list.
- [.planning/ROADMAP.md](../../ROADMAP.md) — Milestone roadmap and phase success criteria.

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
- Refreshed gap closure is complete only when all five ADR-02-002 ship items pass: the full Rust engine suite, the Go gateway test/vet suite, the isolated Python live-evidence suite, the camel-case privacy fail-first probe, no required-path `[TODO]`, and re-verification closing the corresponding five entries in `02-VERIFICATION.md`.

</specifics>

<deferred>
## Deferred Ideas

- **DEBT-CR-04 — network authentication and transport controls.** Source: accepted Phase 02 verification-disposition ADR. Rationale: the current project is personal, trusted, and local-first. Current constraint: explicit loopback binding only; no reverse proxy, tunnel, port-forward, container/VM/cloud ingress, external caller, shared user, or non-loopback exposure. Trigger: any such exposure or caller. Target: before network/shared deployment, with an untriggered review gate no later than Phase 6. Future acceptance: authenticated and authorized ingestion, TLS at ingress, quotas/per-principal limits, and tests proving unauthorized callers cannot consume provider or storage resources.
- **DEBT-CR-05 — pre-admission resource bounds.** Source: accepted Phase 02 verification-disposition ADR. Rationale: hostile slow/concurrent clients are outside the current trusted single-user loopback threat model. Current constraint: one trusted local user, manual ingestion, no intentional concurrent/bulk/scheduled ingestion, and intended uploads within the current limit. Trigger: external/shared access, bulk/scheduled/concurrent ingestion, or larger/uncontrolled uploads. Target: before the trigger, with an untriggered review gate no later than Phase 6. Future acceptance: HTTP read/write/idle timeouts, a pre-body upload semaphore, engine admission accounting before full buffering, and slow/concurrent/permit-release/memory-bound tests.
- **DEBT-BU-01 — complete run-window behavioral proof.** Source: accepted Phase 02 verification-disposition ADR. Rationale: the missing exact-branch proof affects evidence rigor rather than local ingestion correctness. Current constraint: do not claim the live-evidence gate is fully release/audit verified. Trigger: use as release criteria, CI release criteria, public/shared-deployment evidence, or external audit evidence. Target: v1 MVP closure / Phase 6. Future acceptance: controlled clock, matching challenge/evidence identity and issue times, only the allowed run duration exceeded, and assertion of the dedicated complete-run-window error classification.
- **DEBT-BU-02 — full caller-owned input preservation proof.** Source: accepted Phase 02 verification-disposition ADR. Rationale: the destructive ownership bug is fixed, while exhaustive live-success and representative error-path proof needs broader provider/service state. Current constraint: use copied/version-controlled samples and never pass the only copy of an important document. Trigger: before documenting the runner as safe for arbitrary user-owned sources. Target: v1 MVP closure / Phase 6. Future acceptance: successful and representative early/post-upload failures preserve SHA-256 and bytes, while only script-owned temporary files are removed.

</deferred>

---

*Phase: 2-Ingestion, Chunking & Vector Storage*
*Context gathered: 2026-07-17*
