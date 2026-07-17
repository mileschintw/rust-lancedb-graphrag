# Phase 2: Ingestion, Chunking & Vector Storage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-17
**Phase:** 2-Ingestion, Chunking & Vector Storage
**Areas discussed:** Go HTTP Ingestion API Design, Selection and configuration of chunking strategies, Synchronous vs. Asynchronous Ingestion Model, Vector embedding generation strategy, PostgreSQL database access architecture, LanceDB table schema initialization, PostgreSQL shared connection pool, OpenRouter rate limit handling, Tokio worker concurrency, OpenRouter API key validation, Text ingestion file parsing, Go database transactions, Docker-compose config mounts

---

## Go HTTP Ingestion API Design

| Option | Description | Selected |
|--------|-------------|----------|
| multipart/form-data | Standard multipart file uploads supporting filename and metadata form fields | ✓ |
| POST raw binary | Simple payload, metadata/filename passed via custom HTTP headers | |

**User's choice:** multipart/form-data
**Notes:** Reuses standard file upload mechanisms for easy client integration.

---

## PostgreSQL Metadata Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Comprehensive metadata | Store ID, filename, file size, status, chunk count, and timestamps | ✓ |
| Minimal metadata | Store only ID, filename, and status | |

**User's choice:** Comprehensive metadata
**Notes:** Provides detailed document lifecycle tracking for users and admin queries.

---

## gRPC Streaming Chunk Size

| Option | Description | Selected |
|--------|-------------|----------|
| Small fixed-size buffers | Stream 64KB blocks sequentially to optimize memory | ✓ |
| Single large chunk | Send the entire file in one gRPC message frame | |

**User's choice:** Small fixed-size buffers
**Notes:** Prevents Go/Rust service memory ballooning for larger documents.

---

## Corpus Session Isolation

| Option | Description | Selected |
|--------|-------------|----------|
| Global access | Ingested documents added to a shared global corpus | ✓ |
| Session-isolated | Restrict document retrieval to specific session IDs | |

**User's choice:** Global access
**Notes:** All files are ingested into a shared knowledge base queried by all sessions.

---

## Configuration of Chunking Parameters

| Option | Description | Selected |
|--------|-------------|----------|
| Configurable per-document | Pass chunk_size, overlap, and strategy via request metadata | ✓ |
| Global configuration | Use engine-wide settings in config files | |

**User's choice:** Configurable per-document
**Notes:** Allows client applications to control indexing granularity for different document structures.

---

## Fallback Chunking Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Structure-aware chunking | Markdown headers/paragraphs first, recursive character splits fallback | ✓ |
| Fixed-size recursive | Separator-based splits aiming for fixed character limits | |

**User's choice:** Structure-aware chunking
**Notes:** Targets markdown natively, preserving paragraph and header contexts.

---

## Markdown Chunking Markers

| Option | Description | Selected |
|--------|-------------|----------|
| Markdown headers and paragraphs | Split at H1/H2/H3 levels, and double newlines | ✓ |
| Strict Markdown parsing | Support lists and code blocks as distinct non-splittable blocks | |

**User's choice:** Markdown headers and paragraphs
**Notes:** Keeps chunk boundary detection simple and robust.

---

## Default Chunk Size and Overlap

| Option | Description | Selected |
|--------|-------------|----------|
| 500 chars size, 50 chars overlap | Standard balanced size for prompt context windows | ✓ |
| 1000 chars size, 100 chars overlap| Larger blocks preserving more context | |

**User's choice:** 500 characters size, 50 characters overlap
**Notes:** Aligned with default RAG indexing practices.

---

## Ingestion Execution Model

| Option | Description | Selected |
|--------|-------------|----------|
| Asynchronous processing | Queue to Tokio channel background worker, return immediately | ✓ |
| Synchronous processing | Block gRPC handler thread until DB storage finishes | |

**User's choice:** Asynchronous processing
**Notes:** Decouples upload latency from indexing/embedding API response latency.

---

## PostgreSQL Access: Rust + Go vs. Go-Only

| Option | Description | Selected |
|--------|-------------|----------|
| Go-only database access | Only Go connects to PostgreSQL; Rust uses gRPC to report status | ✓ |
| Shared database access | Both Go and Rust connect to PostgreSQL | |

**User's choice:** Go-only database access
**Notes:** Isolates database logic to the Go gateway control plane. Rust remains strictly data-plane.

---

## Go Ingestion Status Discovery

| Option | Description | Selected |
|--------|-------------|----------|
| Go polls Rust via gRPC | Define GetIngestionStatus RPC; Rust maps active ingestions in-memory | ✓ |
| Rust calls Go callback | Rust acts as a gRPC client calling Go status endpoint | |

**User's choice:** Go polls Rust status via gRPC
**Notes:** Avoids circular gRPC client dependency; Go manages status updates.

---

## Original Document Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Store in LanceDB | Rust stores raw document binary blob in LanceDB | ✓ |
| Store in PostgreSQL | Go stores raw text in PostgreSQL | |
| Do not store | Discard raw text after chunking | |

**User's choice:** Store in LanceDB as a Binary Blob
**Notes:** Enables self-contained retrieval of raw documents by the Rust engine.

---

## Duplicate ID Resolution in LanceDB

| Option | Description | Selected |
|--------|-------------|----------|
| Overwrite/Upsert | Delete existing document and chunks before inserting new ones | ✓ |
| Reject duplicate | Return failure if document ID already exists | |

**User's choice:** Overwrite/Upsert
**Notes:** Prevents duplicate chunks when updating document files.

---

## Chunk Metadata Table Columns

| Option | Description | Selected |
|--------|-------------|----------|
| Structured schema columns | Explicit columns for document_id, chunk_id, index, start, end, etc. | ✓ |
| Semi-structured schema | JSON column for most attributes | |

**User's choice:** Structured schema columns
**Notes:** User expanded the fields to include `embedding`, `title`, `section_path`, `page_start`, `page_end`, `content_hash`, `chunker_version`, `embedding_model`, `ingested_at`, `token_estimate` (using `tiktoken-rs` and `o200k_base` with scheme/version auxiliary columns), and `content_type`.

---

## gRPC Queue Full Response

| Option | Description | Selected |
|--------|-------------|----------|
| gRPC error status | Return gRPC RESOURCE_EXHAUSTED status code | ✓ |
| Return success=false response| Standard IngestDocumentResponse with success=false | |

**User's choice:** gRPC error status (RESOURCE_EXHAUSTED)
**Notes:** Mapped to HTTP 429 Too Many Requests by the Go gateway.

---

## Configuration Files and overrides

| Option | Description | Selected |
|--------|-------------|----------|
| TOML Config Files | config.toml, config.dev.toml, config.prod.toml in root /config | ✓ |
| Env Var Overrides | Overwrite values with same name in environment (LANCET_ prefix) | ✓ |

**User's choice:** TOML files in `/config` root, Viper in Go, config crate in Rust, overrides using `LANCET_` and double underscores `__`.
**Notes:** Look up directory via `LANCET_CONFIG_DIR`, fallback to workspace root.

---

## OpenRouter Rate Limit Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Exponential backoff with jitter | Retry up to 3 times, sleep 2^retry + jitter seconds | ✓ |
| Fixed cooldown delay | Sleep constant 5 seconds on each HTTP 429 | |

**User's choice:** Exponential backoff with jitter, fail document and continue on exhaustion.
**Notes:** Employs concurrent batch calls with a maximum concurrency limit of 5.

---

## Tokio Background Worker Concurrency

| Option | Description | Selected |
|--------|-------------|----------|
| Single consumer | Spawn 1 worker task to process sequentially | ✓ |
| Multiple consumers | Spawn pool of 3 worker tasks | |

**User's choice:** Single consumer spawned via `tokio::spawn` at startup. Graceful shutdown on termination. Context-rich tracing spans for observability.

---

## OpenRouter API Key Validation

| Option | Description | Selected |
|--------|-------------|----------|
| Simple presence check | Verify API key configuration is present and non-empty | ✓ |
| Startup test request | Active ping to OpenRouter | |

**User's choice:** Simple presence check on startup.

---

## Text Ingestion File Parsing

| Option | Description | Selected |
|--------|-------------|----------|
| Markdown AST parsing | Use pulldown-cmark in Rust to extract markdown nodes | ✓ |
| UTF-8 validation | Direct std::str::from_utf8 conversion | |

**User's choice:** Markdown AST parsing using pulldown-cmark in Rust.

---

## Go Database Transactions

| Option | Description | Selected |
|--------|-------------|----------|
| Wrap in SQL transactions | Use DB transactions for all Go document metadata operations | ✓ |
| Direct inserts | Plain queries | |

**User's choice:** Wrap in SQL transactions.

---

## Docker-compose Config Mounts

| Option | Description | Selected |
|--------|-------------|----------|
| Volume mounting | Mount host /config directory as read-only volume in containers | ✓ |
| Image copy | Copy config files into container images during build | |

**User's choice:** Volume mounting.

---

## the agent's Discretion

- Standard library selection, CLI routing packages, standard utility libraries, and concrete Rust/Go file structures are left to the agent's best engineering discretion.
