---
phase: 2
slug: ingestion-chunking-vector-storage
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-17
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | go test (Go) / cargo test (Rust) |
| **Config file** | none — standard Go / Rust testing setup |
| **Quick run command** | `go test ./gateway/... && cargo test -p engine` |
| **Full suite command** | `go test ./... && cargo test` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `go test ./gateway/... && cargo test -p engine`
- **After every plan wave:** Run `go test ./... && cargo test`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | DATA-01, DATA-02 | — | Go gateway uploads multipart files and stores metadata | integration | `go test -v ./gateway/db` | ✅ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | DATA-03 | — | Go gateway streams file content in 64KB chunks to engine | unit/int | `go test -v ./gateway/proto` | ✅ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | DATA-06, DATA-07 | — | Rust engine parses chunking parameters from upload settings | unit | `cargo test -p engine chunker::tests` | ✅ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | DATA-08, DATA-09 | — | Chunker parses markdown headers using pulldown-cmark | unit | `cargo test -p engine chunker::tests` | ✅ W0 | ⬜ pending |
| 02-02-03 | 02 | 2 | RAG-06 | — | tiktoken-rs estimates tokens with o200k_base encoding | unit | `cargo test -p engine chunker::tests` | ✅ W0 | ⬜ pending |
| 02-03-01 | 03 | 3 | DATA-06 | — | OpenRouter client generates embeddings with retry backoff | unit | `cargo test -p engine client::tests` | ✅ W0 | ⬜ pending |
| 02-03-02 | 03 | 3 | DATA-06 | — | LanceDB node/edge/doc schemas initialized and validated | integration | `cargo test -p engine db::tests` | ✅ W0 | ⬜ pending |
| 02-03-03 | 03 | 3 | DATA-06 | — | Startup schema drift check fails fast on mismatch | unit | `cargo test -p engine db::tests` | ✅ W0 | ⬜ pending |
| 02-04-01 | 04 | 4 | DATA-06 | — | Tokio channel background worker processes jobs sequentially | integration | `cargo test -p engine worker::tests` | ✅ W0 | ⬜ pending |
| 02-04-02 | 04 | 4 | DATA-06 | — | Go gateway polls and updates PostgreSQL from GetIngestionStatus | integration | `go test -v ./gateway/...` | ✅ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `gateway/db/document_test.go` — Test cases for document PostgreSQL metadata creation & updates
- [ ] `engine/src/chunker/tests.rs` — Unit test suite for structure-aware Markdown chunker and tiktoken estimation
- [ ] `engine/src/client/tests.rs` — Mock client test suite verifying OpenRouter retries & concurrency limits
- [ ] `engine/src/db/tests.rs` — Integration test suite verifying LanceDB tables schemas, drift detection, and entity resolver

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Graceful shutdown of Tokio channel background worker | DATA-06 | Hard to simulate timing cleanly in unit test | Boot engine, start large document upload, trigger SIGINT, verify active document finishes indexing in logs, while remainder of queue is discarded. |
| Docker Compose shared config volume mount | DATA-06 | Involves docker runtime containerization | Boot containers using `docker-compose up`, verify host `/config/config.dev.toml` changes are reflected in container log behaviors on container boot. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
