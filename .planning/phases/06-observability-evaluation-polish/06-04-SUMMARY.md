---
phase: 06-observability-evaluation-polish
plan: 04
subsystem: gateway
tags: [refactor, package-split, go, config, sse, telemetry]
requires: []
provides:
  - "gateway/internal/config"
  - "gateway/internal/sse"
  - "gateway/internal/telemetry"
  - "scripts/gateway-test-targets.sh"
affects:
  - "gateway/main.go"
  - "gateway/main_test.go"
  - "gateway/internal/config/config.go"
  - "gateway/internal/sse/sse.go"
  - "gateway/internal/sse/dto.go"
  - "gateway/internal/telemetry/telemetry.go"
  - "scripts/gateway-test-targets.sh"
tech-stack:
  added: []
  patterns:
    - "Internal package modularization for Go gateway"
    - "scripts/gateway-test-targets.sh package invariant checker"
key-files:
  created:
    - "scripts/gateway-test-targets.sh"
    - "gateway/internal/config/config.go"
    - "gateway/internal/sse/sse.go"
    - "gateway/internal/sse/dto.go"
    - "gateway/internal/telemetry/telemetry.go"
  modified:
    - "gateway/main.go"
    - "gateway/main_test.go"
key-decisions:
  - "Extracted gateway/internal/config with Load() and Config struct; removed viper dependency and definitions from main.go."
  - "Extracted gateway/internal/sse containing WriteWorkflowEvent, WriteStreamError, and all response DTO types (QueryRAGResponseDTO, StructuredCitationDTO, NoticeDTO, DocumentFilterDTO, RetrievalSnapshotDTO, ToQueryRAGResponseDTO)."
  - "Established gateway/internal/telemetry as a no-op placeholder with zero external dependencies, reserving it for Phase 6.2 OpenTelemetry integration."
  - "Maintained exact 67 Go test invariant (gateway: 60, gateway/db: 7) enforced by scripts/gateway-test-targets.sh."
requirements-completed:
  - RAG-03
coverage:
  - deliverable: "Gateway test target invariant gate"
    verification:
      kind: command
      ref: "sh scripts/gateway-test-targets.sh"
      status: pass
    human_judgment: false
  - deliverable: "Gateway internal config, sse, and telemetry packages"
    verification:
      kind: command
      ref: "(cd gateway && go build ./... && go vet ./... && go test ./...)"
      status: pass
    human_judgment: false
duration: "10 min"
completed: "2026-08-20T18:53:00Z"
---

# Phase 06 Plan 04: Go Gateway Modularization (Config, SSE, Telemetry) Summary

Extracted `gateway/internal/config`, `gateway/internal/sse`, and the reserved stub `gateway/internal/telemetry` from `gateway/main.go`, establishing the per-package test invariant gate `scripts/gateway-test-targets.sh`.

## Accomplishments

1. **Per-Package Test Invariant Gate (`scripts/gateway-test-targets.sh`)**:
   - Implemented POSIX shell script counting `^func Test` occurrences per directory in `gateway/`.
   - Asserts total test count equals 67 without requiring live PostgreSQL database connection.

2. **Configuration Package (`gateway/internal/config`)**:
   - Extracted `Config` struct and `Load()` function into `gateway/internal/config/config.go`.
   - Relocated Viper bindings and fail-closed validation rules for database URL and prod TLS.
   - Removed `Config` struct and `loadConfig()` from `gateway/main.go`.

3. **SSE and DTO Package (`gateway/internal/sse`)**:
   - Extracted `WriteWorkflowEvent` and `WriteStreamError` into `gateway/internal/sse/sse.go`.
   - Extracted DTO structs (`QueryRAGResponseDTO`, `StructuredCitationDTO`, `NoticeDTO`, `DocumentFilterDTO`, `RetrievalSnapshotDTO`) and `ToQueryRAGResponseDTO` mapping function into `gateway/internal/sse/dto.go`.
   - Preserved notice precedence rules and all 7 SSE event-name literals.

4. **Telemetry Package Stub (`gateway/internal/telemetry`)**:
   - Created `gateway/internal/telemetry/telemetry.go` as a lightweight zero-dependency stub reserving the package for Phase 6.2 OpenTelemetry integration.

## Verification and Metrics

### Test Target Distribution Invariant
Verbatim output from `scripts/gateway-test-targets.sh`:
```
gateway 60
gateway/db 7
TOTAL: 67
Go test target invariants verified successfully.
```

### Automated Verification Gates
All verification commands succeeded:
- `(cd gateway && go build ./... && go vet ./...)` passed
- `(cd gateway && go test ./...)` passed (67 tests passing)
- `cargo test --manifest-path engine/Cargo.toml --locked` passed (288 tests passing)
- `scripts/gateway-test-targets.sh` passed
- `scripts/engine-test-targets.sh` passed

## Deviations from Plan

### Auto-fixed Lint Adjustments
- **[Rule 1 - Bug/Lint Fix] Fixed copylocks in `gateway/main_test.go`**:
  - Replaced value copy of `pb.RetrievalSnapshot` with pointers `&roundtrip, &orig` in `t.Fatalf` on line 3699 to satisfy `go vet`.

## Self-Check: PASSED
