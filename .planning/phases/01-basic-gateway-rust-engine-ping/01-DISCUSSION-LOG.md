# Phase 1: Basic Gateway & Rust Engine Ping - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-19T01:04:20Z
**Phase:** 01-Basic Gateway & Rust Engine Ping
**Areas discussed:** Protobuf Compilation Workflow, Ping Protocol & HTTP Health Check Format, Database Driver & Query Style, Logging Libraries

---

## Protobuf Compilation Workflow

| Option | Description | Selected |
|--------|-------------|----------|
| `buf` CLI | Modern tool for linting and code generation with plugin configuration | ✓ |
| Local shell script with `protoc` | Traditional toolchain utilizing global compiler installation | |

**User's choice:** `buf` CLI
**Notes:** Prefer modern protobuf tooling to keep plugin configuration clean and reproducible via `buf.gen.yaml`.

---

## Generated Protobuf Location

| Option | Description | Selected |
|--------|-------------|----------|
| Generate in-place inside services | Generated code resides inside `/gateway/proto` and `/engine/src/proto` | ✓ |
| Shared `/proto/gen` directory | Shared root-level folder imported as local packages/crates | |

**User's choice:** Generate in-place inside each service
**Notes:** Makes service compilation self-contained and allows simple, clean package imports.

---

## Ping Protocol & HTTP Health Check Format

| Option | Description | Selected |
|--------|-------------|----------|
| Structured JSON with latency | `{"status":"ok","engine":{"status":"ok","latency_ms":5}}` | ✓ |
| Simple plain text | "OK" or "FAIL" plain text responses | |

**User's choice:** Structured JSON with latency
**Notes:** Structured metadata helps in debugging service health and analyzing latency between Go and Rust.

---

## Connectivity Failure Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Return HTTP 503 | Standard degraded status code for proxy/gateway layers | ✓ |
| Return HTTP 200 with unreachable status | Gateway returns success but payload marks engine unreachable | |

**User's choice:** Return HTTP 503 Service Unavailable
**Notes:** Correctly signals connection drop down the line to load balancers or orchestrators.

---

## Database Driver & Query Style

| Option | Description | Selected |
|--------|-------------|----------|
| `pgx/v5` + stdlib `database/sql` | Write raw SQL queries, scan results manually | |
| `sqlx` | Adds nice struct scanning helpers on top of raw SQL | |
| `gorm` | Active-record style complete ORM | |
| `sqlc` + `pgx/v5` + `atlas` | Write-in: type-safe Go SQL compiler + pgx + Atlas declarative migration tool | ✓ |

**User's choice:** `sqlc` + `pgx/v5` + `atlas`
**Notes:** Write-in choice selected by the user. Retains systems-oriented feel with type-safety and declarative migrations.

---

## Logging Libraries

| Option | Description | Selected |
|--------|-------------|----------|
| Go `slog` + Rust `tracing`/`tracing-subscriber` | Structured logging (Go stdlib) + tracing (Rust standard) | |
| Go `uber-go/zap` + Rust `tracing` and `tracing-subscriber` | High-performance Zap structured logging (Go) + Rust tracing | ✓ |

**User's choice:** Go `uber-go/zap` + Rust `tracing` and `tracing-subscriber`
**Notes:** Leverages standard high-performance structured logging libraries across both languages.

---

## the agent's Discretion

- Choice of Go HTTP router (e.g. `go-chi/chi`).
- Rust async runtime setup (e.g. `tokio`).
- Rust gRPC server framework (e.g. `tonic`).
- Directory scaffolding layout inside the monorepo.

---

## Deferred Ideas

- PostgreSQL database migration tooling configuration and schema execution (Deferred to later database migration requirements).
