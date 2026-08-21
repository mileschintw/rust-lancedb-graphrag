---
phase: 06-observability-evaluation-polish
plan: 05
subsystem: gateway
tags: [refactor, module-graph, go, engineclient, grpc]
requires:
  - "06-04"
provides:
  - "gateway/internal/engineclient"
affects:
  - "gateway/internal/engineclient/engineclient.go"
  - "gateway/main.go"
  - "gateway/main_test.go"
tech-stack:
  added: []
  patterns:
    - "Internal engineclient package with Engine interface, GRPCEngine client, and TrailerError"
    - "Preserved insecure gRPC dial credentials in main.go run()"
key-files:
  created:
    - "gateway/internal/engineclient/engineclient.go"
  modified:
    - "gateway/main.go"
    - "gateway/main_test.go"
key-decisions:
  - "Extracted Engine interface, GRPCEngine struct, IngestOutcome, and TrailerError into gateway/internal/engineclient."
  - "Retained grpc.WithTransportCredentials(insecure.NewCredentials()) unchanged in gateway/main.go run() per D-03 / D-06."
  - "Maintained exact Go test counts across targets (gateway: 60, gateway/db: 7, gateway/internal/sse: 8, total: 75)."
  - "Updated test doubles in main_test.go to implement engineclient.Engine without publishing test doubles to the production engineclient package."
requirements-completed:
  - RAG-03
coverage:
  - deliverable: "Engine client extraction and gateway test target verification"
    verification:
      kind: command
      ref: "sh scripts/gateway-test-targets.sh"
      status: pass
      human_judgment: false
  - deliverable: "Full suite test execution across Rust and Go targets"
    verification:
      kind: command
      ref: "go test ./... (in gateway/) && cargo test --manifest-path engine/Cargo.toml --locked"
      status: pass
      human_judgment: false
duration: "10 min"
completed: "2026-08-20T22:25:00Z"
---

# Phase 06 Plan 05: Go Module-Graph Restructure (Engine Client Relocation) Summary

Completed the second half of the Go module-graph restructure (D-82) by extracting the gRPC engine client into `gateway/internal/engineclient`.

## Accomplishments

1. **Created `gateway/internal/engineclient`**:
   - Authored `gateway/internal/engineclient/engineclient.go` with complete package doc comment.
   - Defined exported `Engine` interface, `GRPCEngine` implementation, `New` constructor, `IngestOutcome` struct, and `TrailerError` with `GRPCStatus()` and `Trailer()` metadata accessors.
   - Preserved streaming buffer size, gRPC call mechanics, and error propagation semantics.

2. **Rewired `gateway/main.go`**:
   - Removed `IngestOutcome`, `engine`, `grpcEngine`, `trailerError` definitions.
   - Updated `app` struct to use `engineclient.Engine`.
   - Updated `run()` to instantiate `engineclient.New(pb.NewLancetServiceClient(conn))`.
   - Preserved `insecure.NewCredentials()` gRPC dial in `main.go run()` without alteration per D-03 / D-06.

3. **Migrated `gateway/main_test.go`**:
   - Qualified all `IngestOutcome`, `engineFunc`, and `grpcEngine` sites with `engineclient`.
   - Updated `trailerError` occurrences to `engineclient.NewTrailerError`.
   - Verified that `engineFunc` test stub remains test-local in `main_test.go`.

## Relocation & Export Mapping

| Old Identifier (in `main.go`) | New Identifier (in `internal/engineclient`) | Scope |
|---|---|---|
| `type IngestOutcome struct` | `engineclient.IngestOutcome` | Exported struct |
| `type engine interface` | `engineclient.Engine` | Exported interface |
| `type grpcEngine struct` | `engineclient.GRPCEngine` | Exported struct (`engineclient.New` constructor) |
| `type trailerError struct` | `engineclient.TrailerError` | Exported struct (`engineclient.NewTrailerError`) |
| `(trailerError) Error()` | `(TrailerError) Error()` | Exported method |
| `(trailerError) GRPCStatus()` | `(TrailerError) GRPCStatus()` | Exported method |
| `(trailerError) Trailer()` | `(TrailerError) Trailer()` | Exported method |

## Insecure Dial Statement
The Gateway -> Engine gRPC dial connection in `gateway/main.go:run()` uses `grpc.WithTransportCredentials(insecure.NewCredentials())`. Per D-03 and D-06, this is documented and accepted as `DEBT-CR-04-EXT` for local loopback operation. This refactoring moved the surrounding code without changing transport credentials or adding artificial security parameters.

## Verification and Metrics

### Test Target Invariant Check (`scripts/gateway-test-targets.sh`)
```
gateway 60
gateway/db 7
gateway/internal/config 0
gateway/internal/engineclient 0
gateway/internal/sse 8
gateway/internal/telemetry 0
gateway/proto/lancet/v1 0
TOTAL: 75
Go test target invariants verified successfully.
```

### Rust Invariant Check (`scripts/engine-test-targets.sh`)
```
engine (lib): 139
engine (bin): 122
inspect_lancedb (bin): 18
seed_rag_fixture (bin): 0
config_startup (test): 9
TOTAL: 288 (lib+bin: 261, inspect_lancedb: 18, seed_rag_fixture: 0, config_startup: 9)
All 5 Rust test target invariants verified successfully.
```

### Verification Matrix
- `go build ./...` in `gateway/` — passed (0 errors)
- `go vet ./...` in `gateway/` — passed (0 warnings)
- `go test ./...` in `gateway/` — passed (60 gateway + 7 db + 8 sse = 75 tests)
- `cargo test --manifest-path engine/Cargo.toml --locked` — passed (288 tests)
- `gateway/go.mod` — untouched (0 added dependencies)

## Self-Check: PASSED
