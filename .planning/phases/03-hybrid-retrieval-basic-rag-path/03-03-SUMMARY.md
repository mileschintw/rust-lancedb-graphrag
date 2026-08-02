---
phase: 03-hybrid-retrieval-basic-rag-path
plan: 03
subsystem: query-rag-coordination
tags: [rust, grpc, proto, rag, openrouter, bm25, lancedb, fusion]

# Dependency graph
requires:
  - plan: 03-01
    provides: Full-Unicode BM25, dense retrieval, RRF fusion, and NoOpReranker
  - plan: 03-02
    provides: OpenRouterGenerator client and prompt evidence assembly/packing
provides:
  - Additive proto extension for QueryRAG typed filters, citations, answer basis, notices, and snapshot
  - Complete Rust engine query_rag gRPC pipeline integrating retrieval, fusion, prompt packing, OpenRouter generation, and snapshot generation
  - Configurable retrieval and OpenRouter generation settings with safe defaults in config.toml
  - Startup BM25 snapshot initialization before gRPC listener readiness
affects: [03-04, 03-05, Go Gateway gRPC client]

# Tech tracking
tech-stack:
  added: [buf, tonic, prost, serde, config]
  patterns: [additive proto extension, non-secret default configuration, synchronous startup BM25 indexing, gRPC typed RAG coordination]

key-files:
  created:
    - .planning/phases/03-hybrid-retrieval-basic-rag-path/03-03-SUMMARY.md
  modified:
    - proto/lancet/v1/lancet.proto
    - engine/src/pb/lancet/v1/lancet.v1.rs
    - engine/src/pb/lancet/v1/lancet.v1.tonic.rs
    - gateway/proto/lancet/v1/lancet.pb.go
    - gateway/proto/lancet/v1/lancet_grpc.pb.go
    - config/config.toml
    - config/config.example.toml
    - engine/src/main.rs
    - engine/src/tests.rs
    - engine/tests/config_startup.rs

key-decisions:
  - "Extend lancet.v1 QueryRAG request/response additively without renumbering existing fields 1-3."
  - "Construct BM25 index synchronously from LanceDB completed nodes during startup before listening for gRPC requests."
  - "Return typed AnswerBasis, StructuredCitation, Notice, and RetrievalSnapshot in QueryRAGResponse."
  - "Validate UUIDv4 session identifiers in engine and supply non-secret configuration defaults for retrieval/generation settings."

requirements-completed: [RAG-01, RAG-02, RAG-03, RAG-04]

coverage:
  - id: D1
    description: "Additive gRPC proto schema extension with buf lint/generate validation"
    requirement: RAG-01
    verification:
      - kind: build
        ref: "buf lint && buf generate"
        status: pass
    human_judgment: false
  - id: D2
    description: "Complete Rust engine QueryRAG gRPC coordination pipeline"
    requirement: RAG-01
    verification:
      - kind: integration
        ref: "engine/src/tests.rs#query_rag_happy_path_service"
        status: pass
    human_judgment: false
  - id: D3
    description: "Synchronous BM25 startup indexing before gRPC serving readiness"
    requirement: RAG-02
    verification:
      - kind: integration
        ref: "engine/tests/config_startup.rs#initial_bm25_ready_before_serving"
        status: pass
      - kind: integration
        ref: "engine/tests/config_startup.rs#initial_bm25_failure_blocks_readiness"
        status: pass
    human_judgment: false

# Metrics
duration: 35min
completed: 2026-08-02
status: complete
---

# Phase 03 Plan 03: QueryRAG Pipeline Integration & gRPC Wiring Summary

**End-to-end QueryRAG gRPC pipeline integrating dense & BM25 retrieval, RRF fusion, evidence packing, OpenRouter generation, and startup BM25 indexing**

## Performance

- **Duration:** 35 min
- **Started:** 2026-08-02T02:15:00Z
- **Completed:** 2026-08-02T02:33:00Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

1. **Proto Schema Additive Extension (Task 1)**:
   - Extended `proto/lancet/v1/lancet.proto` with `DocumentFilter`, `AnswerBasis`, `NoticeSeverity`, `Notice`, `StructuredCitation`, and `RetrievalSnapshot`.
   - Preserved backward compatibility on existing fields 1–3 of `QueryRAGRequest` and `QueryRAGResponse`.
   - Verified code generation across Rust (`engine/src/pb/lancet/v1/`) and Go (`gateway/proto/lancet/v1/`) with `buf lint` and `buf generate`.

2. **Rust Engine `query_rag` Service Wiring & Configuration (Task 2)**:
   - Added retrieval and OpenRouter generation configuration sections with defaults to `config/config.toml` and `config/config.example.toml`.
   - Updated `Settings` deserialization in `engine/src/main.rs` with safe Serde default functions.
   - Wired `LancetServiceImpl` with `nodes: Table`, `bm25_index: Arc<RwLock<Bm25Index>>`, `retrieval_settings`, `generator`, and `embedder`.
   - Implemented full `query_rag` handler validating UUIDv4 session IDs, executing dense & BM25 retrieval, RRF fusion, prompt evidence packing, OpenRouter model generation, citation resolution, and retrieval snapshot construction.
   - Added `query_rag_happy_path_service` test in `engine/src/tests.rs`.

3. **BM25 Startup Readiness & Verification (Task 3)**:
   - Built BM25 snapshot from LanceDB `nodes` table in `main()` prior to starting gRPC server listener.
   - Added `initial_bm25_ready_before_serving` and `initial_bm25_failure_blocks_readiness` integration tests in `engine/tests/config_startup.rs`.
   - Verified clean cargo check, cargo fmt, and git diff check.

## Key Commit History

- `5e379c1`: `feat(proto): add QueryRAG typed filters, citations, answer basis, notices, and snapshot`
- `6a12b85`: `feat(engine): wire QueryRAG hybrid retrieval, OpenRouter generator, and typed responses`
- `cd439b9`: `test(engine): verify BM25 startup readiness and failure blocking`

## Next Steps

- Execute Phase 03 Wave 4 (Plan 03-04: Gateway gRPC client wiring & HTTP handler integration).
