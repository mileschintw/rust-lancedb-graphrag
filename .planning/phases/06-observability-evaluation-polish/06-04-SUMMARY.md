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
  - "gateway/internal/sse/sse_test.go"
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
    - "gateway/internal/sse/sse_test.go"
    - "gateway/internal/telemetry/telemetry.go"
  modified:
    - "gateway/main.go"
    - "gateway/main_test.go"
key-decisions:
  - "Extracted gateway/internal/config with Load() and Config struct; removed viper dependency and definitions from main.go."
  - "Extracted gateway/internal/sse containing WriteWorkflowEvent, WriteStreamError, and all response DTO types (QueryRAGResponseDTO, StructuredCitationDTO, NoticeDTO, DocumentFilterDTO, RetrievalSnapshotDTO, ToQueryRAGResponseDTO)."
  - "Established gateway/internal/telemetry as a no-op placeholder with zero external dependencies, reserving it for Phase 6.2 OpenTelemetry integration."
  - "Relocation preserved the 67-test baseline exactly (gateway: 60, gateway/db: 7); no test was lost or gained by the package split."
  - "Added 8 package-local tests to gateway/internal/sse pinning the seven event names, both stream_error codes, the notice-list precedence rule and the response DTO JSON key set — the wire contract plan 06-07 extends. Total invariant is now 75."
  - "scripts/gateway-test-targets.sh counts from `go test -list`, not from grepping source, so a package that stops compiling into the test run fails by name (threat T-06-04-05); it asserts per-package counts and names the moved package on mismatch."
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
  - deliverable: "SSE wire-contract regression tests (gateway/internal/sse/sse_test.go)"
    verification:
      kind: command
      ref: "(cd gateway && go test ./internal/sse/...)"
      status: pass
    human_judgment: false
  - deliverable: "Gate proven to fail by name on count drift, package build failure, and undeclared test package"
    verification:
      kind: command
      ref: "sh scripts/gateway-test-targets.sh (three negative-path runs, each exit 1)"
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

## Export Decisions (old unexported name → new exported name)

Required by the plan's `<output>` block so plans 06-05 and 06-07 can reuse these without
re-deriving them. Everything on the left lived in `package main` before commit `c7e107ec`.

| Pre-commit (`package main`) | Post-commit | Note |
|---|---|---|
| `loadConfig()` | `config.Load()` | unexported → exported across the package boundary |
| `Config` | `config.Config` | name unchanged; nested `Gateway` struct and all three `mapstructure` tags unchanged |
| `(app).writeWorkflowEventSSE` | `sse.WriteWorkflowEvent` | method → free function; `app` stayed in `package main` |
| `(app).writeStreamErrorSSE` | `sse.WriteStreamError` | method → free function |
| `toQueryRAGResponseDTO` | `sse.ToQueryRAGResponseDTO` | |
| `queryRAGResponseDTO` | `sse.QueryRAGResponseDTO` | 7 JSON keys; 06-07 adds the `metadata` object alongside |
| `structuredCitationDTO` | `sse.StructuredCitationDTO` | |
| `noticeDTO` | `sse.NoticeDTO` | **06-07 adds `TypedCode` here** |
| `documentFilterDTO` | `sse.DocumentFilterDTO` | |
| `retrievalSnapshotDTO` | `sse.RetrievalSnapshotDTO` | `variant_count` / `variant_identities` remain proto-only by design |
| — | `(app).writeWorkflowEvent` | **new** thin wrapper in `package main` retaining checkpoint dispatch before delegating to `sse` |
| — | `sse.ErrCodeStreamEOFWithoutTerminal`, `sse.ErrCodeGRPCRecvError` | **added at close-out**; `main.go` call sites use these instead of raw literals |
| — | `sse.eventStreamError` (unexported) | **added at close-out**; the `stream_error` event name, previously only inside a format string |

Stayed in `package main` deliberately: `app`, the four HTTP handlers, `ragQueryRequestBody` and
its `DisallowUnknownFields` decoder (06-07 adds the two request flags there),
`(app).handlePreStreamError`, the document store and the reconciler. `internal/engineclient`
is plan 06-05.

## Verification and Metrics

### Test Target Distribution
Verbatim output from `scripts/gateway-test-targets.sh` at close:
```
gateway 60
gateway/db 7
gateway/internal/config 0
gateway/internal/sse 8
gateway/internal/telemetry 0
gateway/proto/lancet/v1 0
TOTAL: 75
Go test target invariants verified successfully.
```

Before the split the gate printed `gateway 60` / `gateway/db 7` / `TOTAL: 67`. The relocation
itself moved **no** tests — the distribution was byte-identical before and after, which is the
correct result for a pure refactor. The 8 tests in `gateway/internal/sse` are new coverage added
during plan close-out, not relocated coverage; the invariant is therefore `67 + 8 = 75`, with 67
retained in the script as the documented relocation baseline.

### Automated Verification Gates
All verification commands succeeded:
- `(cd gateway && go build ./... && go vet ./...)` passed
- `(cd gateway && go test ./...)` with `TEST_DATABASE_URL` exported against live `lancet-postgres`:
  **75 passed / 0 failed / 0 skipped**
- `cargo test --manifest-path engine/Cargo.toml --locked` passed: **287 passed / 0 failed /
  1 ignored** across 288 targets, exit 0. No engine file is in this plan's diff.
- `sh scripts/gateway-test-targets.sh` passed (TOTAL 75)
- `sh scripts/engine-test-targets.sh` passed (TOTAL 288)
- Plan Task 1 / Task 2 / Task 3 `<verify>` blocks re-run individually; all pass except the two
  criteria recorded as plan-authoring defects below (one superseded, one fixed in code)
- `gofmt -l gateway/internal scripts` clean

### Gate Negative-Path Proof
`scripts/gateway-test-targets.sh` was exercised against three induced failures, each exiting 1
with the package named:

| Induced failure | Gate output |
|---|---|
| `TestStreamErrorCodeConstants` renamed away | `FAIL: package gateway/internal/sse test count moved: expected 8, got 7` |
| Undefined symbol added to `sse_test.go` | `FAIL: package gateway/internal/sse is absent from the test run (expected 8 tests)` — it no longer compiles into the test run |
| Test added to undeclared `internal/telemetry` | `FAIL: package gateway/internal/telemetry reports 1 tests but is not in the expected distribution` |

The second case is the one the original source-grep implementation could not detect: the file
still contained 8 `^func Test` lines, so a grep-based count would have reported TOTAL 75 and
passed while the package silently stopped being tested. This closes threat T-06-04-05, which the
original gate claimed but did not deliver.

## Post-Execution Review and Refinement

A behavior-preservation review of commit `c7e107ec` was run against the pre-commit tree. The
package split itself was faithful — the top-level declaration diff of `main.go` shows exactly the
intended eight declarations moved, all 25 `json:"…"` tags are byte-identical, the seven event
names and both `stream_error` codes are unchanged, and checkpoint dispatch is preserved (the
`dispatcher.Submit` / `RetainPending` path was retained in the renamed `app.writeWorkflowEvent`
wrapper at `gateway/main.go:720` rather than moved into the `sse` package). One behavioral
regression and three gaps were found and closed:

| Item | Finding | Resolution |
|---|---|---|
| REG-06-04-01 | `gateway/internal/config/config.go:57` truncated the fail-closed error to `gateway.database_url must not be empty`, dropping the `(set LANCET_GATEWAY__DATABASE_URL)` hint an operator reads on a failed start. Task 2 required the string byte-for-byte. | String restored. `TestLoadConfigValidation` now asserts the **full** string instead of the prefix. |
| GAP-06-04-01 | Both gates were prefix-shaped (`grep -q` in the plan, `strings.Contains` in the test), so neither could detect suffix truncation. | Assertion tightened to the full literal. **Carry-forward for plan 06-05:** use `grep -qF "<full string>"` for operator- and wire-facing literals when relocating `engineclient`. |
| GAP-06-04-02 | The gate counted `^func Test` from source text, so it could not detect a package dropping out of the test run — the mitigation threat T-06-04-05 claimed. Its failure message also named no package, failing Task 1's acceptance criterion. | Rewritten on `go test -list` with per-package assertions and named failures; proven against three induced failures above. Now symmetric with `scripts/engine-test-targets.sh`, which already used `cargo test --list`. |
| GAP-06-04-03 | `internal/sse` owns the `/rag/query` JSON wire contract that plan 06-07 extends, but had no package-local test; all coverage reached across the boundary from `main_test.go`. | `gateway/internal/sse/sse_test.go` added (8 tests). |

### Closure Ledger: the four acceptance criteria that no longer hold as written

Every plan 06-04 acceptance criterion was re-run individually. Four do not pass as literally
written. Two were unsatisfiable by *any* faithful execution; two are mechanically false but
substantively correct. None indicates missing work.

| # | Criterion | Why it does not hold | Disposition |
|---|---|---|---|
| 1 | Task 2: "`LANCET_GATEWAY__DATABASE_URL` appears **exactly once** in `gateway/internal/config/config.go`" | The pre-commit source contains it **twice** — `main.go:75` (`BindEnv`) and `main.go:91` (the operator hint inside the fail-closed error string). Task 2's action text simultaneously required "Keep both error message strings byte-for-byte." Mutually exclusive: a faithful move yields two. | **Superseded — needs sign-off.** Correct count is 2. The executor satisfied the machine-checkable grep by deleting the hint; that is precisely how REG-06-04-01 was introduced. |
| 2 | Task 3: "the seven event-name literals … each appear in `gateway/internal/sse/sse.go`", gated as `grep -q "\"stream_error\""` | Six names appear as standalone quoted literals (`eventType = "node_started"` …). `stream_error` only ever existed embedded in `"event: stream_error
data: %s

"`, so the quoted-literal grep matched neither the pre-commit nor the as-committed code. The gate could not have passed as this summary originally claimed. | **Fixed in code.** `stream_error` is now `const eventStreamError`, used in the `Fprintf`. The plan's gate now genuinely passes. |
| 3 | Task 1: "`sh scripts/gateway-test-targets.sh` prints a TOTAL of `67`" | Prints 75. The relocation preserved 67 exactly — which is what the invariant existed to prove — and 8 tests were then added deliberately to `internal/sse`. | **Raised 67 → 75 — needs sign-off.** 67 retained in the script as `RELOCATION_BASELINE`. |
| 4 | `<success_criteria>`: "the per-package gate reports the redistribution" | There was no redistribution to report: a pure production-code move leaves the test distribution untouched (`gateway 60` / `gateway/db 7` before *and* after). | **Unverifiable as stated; satisfied in spirit.** The gate now reports a real distribution across four packages and asserts each by name. |

**The discriminator, for plan 06-05.** Rows 1 and 2 are both gate-driven code changes, with
opposite verdicts. The rule separating them: **row 1 altered observable output, row 2 did not.**
Editing production behavior to satisfy a scan is a regression; renaming an internal literal so a
scan can see an unchanged value is not. When relocating `engineclient` under the same style of
literal-presence gates, apply that test — and prefer `grep -qF "<full string>"` over a prefix
match for any operator- or wire-facing literal, which is what would have caught REG-06-04-01.

### Regression and gaps found by the post-execution review

| Item | Finding | Resolution |
|---|---|---|
| REG-06-04-01 | `gateway/internal/config/config.go:57` truncated the fail-closed error to `gateway.database_url must not be empty`, dropping the `(set LANCET_GATEWAY__DATABASE_URL)` hint an operator reads on a failed start. | String restored. `TestLoadConfigValidation` now asserts the **full** string instead of the prefix. Root cause is ledger row 1. |
| GAP-06-04-01 | Both gates were prefix-shaped (`grep -q` in the plan, `strings.Contains` in the test), so neither could detect suffix truncation. | Assertion tightened to the full literal; carry-forward rule recorded above. |
| GAP-06-04-02 | The gate counted `^func Test` from source text, so it could not detect a package dropping out of the test run — the mitigation threat T-06-04-05 claimed. Its failure message also named no package, failing Task 1's acceptance criterion. | Rewritten on `go test -list` with per-package assertions and named failures; proven against three induced failures above. Now symmetric with `scripts/engine-test-targets.sh`, which already used `cargo test --list`. Nothing outside phase 06 invokes the script, so the new compiling-tree requirement breaks no CI step or hook. |
| GAP-06-04-03 | `internal/sse` owns the `/rag/query` JSON wire contract that plan 06-07 extends, but had no package-local test; all coverage reached across the boundary from `main_test.go`. | `gateway/internal/sse/sse_test.go` added (8 tests). |

### Non-regressions confirmed, no change made
- **Checkpoint dispatch.** `sse.WriteWorkflowEvent` opens with `if ev == nil || ev.GetCheckpoint() != nil { return }` and never touches the dispatcher. This is not a live defect — `app.writeWorkflowEvent` handles checkpoints before delegating — but the package now silently *discards* checkpoint frames where the pre-commit function persisted them. A caller contract was documented on the function so a 06-05/06-07 handler restructure cannot route checkpoints straight into `sse` and lose them; `TestWriteWorkflowEventDropsNonClientFrames` pins the drop as deliberate.
- **`RetrievalSnapshot.variant_count` / `variant_identities`** remain present in proto and absent from the DTO. Preserved deliberately per AI-SPEC §4.3; out of Phase 6 scope.

### Additional cleanups
- `ErrCodeStreamEOFWithoutTerminal` / `ErrCodeGRPCRecvError` were declared but unused — `gateway/main.go:701,707` passed raw literals, putting the codes in two places immediately before 06-07 touches them. Call sites now use the constants; `TestStreamErrorCodeConstants` pins their values.
- `gateway/internal/sse/dto.go` was gofmt-unclean (struct tag alignment only). All five files under `gateway/internal/` and `scripts/` are now gofmt-clean. The nine pre-existing unformatted files elsewhere in the module (`main.go`, `main_test.go`, `db/*.go`, generated `proto/**`) are untouched and remain recorded debt.

## Deviations from Plan

### Auto-fixed Lint Adjustments
- **[Rule 1 - Bug/Lint Fix] Fixed copylocks in `gateway/main_test.go`**:
  - Replaced value copy of `pb.RetrievalSnapshot` with pointers `&roundtrip, &orig` in `t.Fatalf` on line 3699 to satisfy `go vet`.

### Deviations recorded at close-out
- **Acceptance criteria.** Four criteria no longer hold as written; see the Closure Ledger above.
  Two of them (raising the invariant 67 → 75, superseding Task 2's "exactly once") are judgment
  calls that require sign-off rather than being self-certifiable.
- **Task 1 said to count from source rather than a test run, for speed and to avoid PostgreSQL.**
  The gate now uses `go test -list`, which compiles test binaries but runs no test — so the
  no-PostgreSQL constraint holds (3.5s cold, cached thereafter) while the compile-coverage
  property the threat model depends on is actually delivered.

## Self-Check: PASSED
