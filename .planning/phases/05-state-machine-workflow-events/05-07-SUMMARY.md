---
phase: 05-state-machine-workflow-events
plan: 07
subsystem: infra
tags: [protobuf, buf, grpc, rust, go, wire-contract]

# Dependency graph
requires:
  - phase: 05-state-machine-workflow-events (05-01)
    provides: NodeErrorKind enum and NodeFailedEvent/WorkflowCompletedEvent client-facing event machinery (ORCH-02)
  - phase: 05-state-machine-workflow-events (05-06)
    provides: proven buf generate pipeline against these same four generated output files
provides:
  - "NODE_ERROR_KIND_INPUT_VALIDATION = 9 appended to the shipped NodeErrorKind proto enum (D-22 taxonomy completion)"
  - "Regenerated Rust NodeErrorKind::InputValidation variant (engine::pb::lancet::v1::NodeErrorKind) with as_str_name/from_str_name support"
  - "Regenerated Go NodeErrorKind_NODE_ERROR_KIND_INPUT_VALIDATION constant and complete NodeErrorKind_name/NodeErrorKind_value maps"
affects: [05-02]

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - proto/lancet/v1/lancet.proto
    - engine/src/pb/lancet/v1/lancet.v1.rs
    - engine/src/pb/mod.rs
    - gateway/proto/lancet/v1/lancet.pb.go

key-decisions:
  - "Appended NODE_ERROR_KIND_INPUT_VALIDATION = 9 as a pure additive member after INTERNAL=8, preserving all nine prior variants' names and numbers for wire backward compatibility."
  - "Restored the hand-written engine/src/pb/mod.rs (module glue for the generated lancet.v1.rs include!) after buf generate's clean:true wiped it, since neither buf remote plugin regenerates it."

patterns-established: []

requirements-completed: [ORCH-02]

coverage:
  - id: D1
    description: "NodeErrorKind enum gains NODE_ERROR_KIND_INPUT_VALIDATION = 9 in proto/lancet/v1/lancet.proto; nine prior variants (0-8) unchanged"
    requirement: "ORCH-02"
    verification:
      - kind: unit
        ref: "cargo check --manifest-path engine/Cargo.toml --locked"
        status: pass
      - kind: other
        ref: "grep of proto/lancet/v1/lancet.proto NodeErrorKind enum (0-9 present, no renumbering)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Regenerated engine/src/pb/lancet/v1/lancet.v1.rs exposes NodeErrorKind::InputValidation = 9 with as_str_name()/from_str_name() entries; cargo check and cargo test --no-run both compile cleanly"
    requirement: "ORCH-02"
    verification:
      - kind: unit
        ref: "cargo check --manifest-path engine/Cargo.toml --locked"
        status: pass
      - kind: unit
        ref: "cargo test --manifest-path engine/Cargo.toml --locked --no-run"
        status: pass
    human_judgment: false
  - id: D3
    description: "Regenerated gateway/proto/lancet/v1/lancet.pb.go NodeErrorKind_name/NodeErrorKind_value maps include the 9 <-> NODE_ERROR_KIND_INPUT_VALIDATION pair; gateway/main.go and gateway/main_test.go remain byte-for-byte unchanged"
    requirement: "ORCH-02"
    verification:
      - kind: unit
        ref: "go build ./... (gateway)"
        status: pass
      - kind: unit
        ref: "go vet ./... (gateway)"
        status: pass
      - kind: other
        ref: "git diff --name-only -- gateway/main.go gateway/main_test.go engine/src/workflow engine/src/main.rs engine/src/tests.rs (empty)"
        status: pass
    human_judgment: false

duration: ~25min
completed: 2026-08-13
status: complete
---

# Phase 05 Plan 07: Complete NodeErrorKind wire taxonomy Summary

**Appended `NODE_ERROR_KIND_INPUT_VALIDATION = 9` to the shipped `NodeErrorKind` proto enum and regenerated the Rust (prost/tonic) and Go (protoc-gen-go/grpc-go) bindings via `buf generate`, closing the D-22 taxonomy gap blocking 05-02.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-08-13T04:54:32Z
- **Tasks:** 1
- **Files modified:** 4 (proto/lancet/v1/lancet.proto, engine/src/pb/lancet/v1/lancet.v1.rs, engine/src/pb/mod.rs, gateway/proto/lancet/v1/lancet.pb.go)

## Accomplishments
- `NodeErrorKind` enum now has ten members (`UNSPECIFIED..INTERNAL` unchanged at 0-8, `INPUT_VALIDATION` newly appended at 9), completing D-22's decided taxonomy.
- `engine::pb::lancet::v1::NodeErrorKind::InputValidation` is now a valid, constructible Rust path with matching `as_str_name()`/`from_str_name()` arms — proven by `cargo check` and full test-binary compilation (`cargo test --no-run`).
- `gateway/proto/lancet/v1/lancet.pb.go`'s `NodeErrorKind_name`/`NodeErrorKind_value` maps and the `NodeErrorKind_NODE_ERROR_KIND_INPUT_VALIDATION` constant round-trip the same discriminant on the Go side — proven by `go build ./...` and `go vet ./...`.
- 05-02 can now construct and reject a ninth-or-later reformulation variant with a typed `InputValidation` wire error without any further proto or codegen work.

## Task Commits

Each task was committed atomically:

1. **Task 1: Append NODE_ERROR_KIND_INPUT_VALIDATION to the proto contract and regenerate Rust/Go bindings** - `d59bd0c` (feat)

**Plan metadata:** (this SUMMARY.md commit, following)

## Files Created/Modified
- `proto/lancet/v1/lancet.proto` - `NodeErrorKind` enum gains `NODE_ERROR_KIND_INPUT_VALIDATION = 9;` appended after `NODE_ERROR_KIND_INTERNAL = 8;`
- `engine/src/pb/lancet/v1/lancet.v1.rs` - regenerated via `buf generate`; `NodeErrorKind::InputValidation = 9` with `as_str_name`/`from_str_name` arms
- `engine/src/pb/mod.rs` - restored hand-written module glue (`pub mod lancet { pub mod v1 { include!(...) } }`) that buf's `clean: true` output-directory wipe deleted; content is byte-identical to the pre-existing committed version
- `gateway/proto/lancet/v1/lancet.pb.go` - regenerated via `buf generate`; `NodeErrorKind_NODE_ERROR_KIND_INPUT_VALIDATION NodeErrorKind = 9` constant plus matching name/value map entries
- `engine/src/pb/lancet/v1/lancet.v1.tonic.rs` and `gateway/proto/lancet/v1/lancet_grpc.pb.go` were regenerated by the same `buf generate` invocation (required because `buf.gen.yaml` has `clean: true` for these output directories) but came back byte-identical to their prior committed content, exactly as the plan predicted for an enum-only proto change with no service-level changes — confirmed empirically via `git diff` (no hunks) after generation, so neither was re-staged.

## Decisions Made
- Appended the new variant as a pure addition (value 9, after INTERNAL=8) with no renumbering, matching D-22's already-decided taxonomy and the plan's explicit prohibition against touching the nine existing variants.
- Restored `engine/src/pb/mod.rs` after buf's `clean: true` pipeline deleted it (see Deviations below) rather than changing `buf.gen.yaml`'s clean behavior, since altering codegen-cleanup semantics was out of this plan's narrow scope.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Restored engine/src/pb/mod.rs after buf generate's clean:true deleted it**
- **Found during:** Task 1 (immediately after running `buf generate`)
- **Issue:** `buf.gen.yaml` has `clean: true` for the `engine/src/pb` output directory. `engine/src/pb/mod.rs` is a hand-written file (created during the 05-01/05-06 wave) providing the Rust module glue (`pub mod lancet { pub mod v1 { include!("lancet/v1/lancet.v1.rs"); } }`) that `engine/src/lib.rs`'s `pub mod pb;` depends on. Neither the neoeinstein-prost nor neoeinstein-tonic remote plugin regenerates this file, so buf's clean step deleted it, which would have broken `cargo check`/`cargo test --no-run` compilation for the entire crate (not just this plan's scope).
- **Fix:** Recreated `engine/src/pb/mod.rs` with content identical to the pre-existing committed version (verified via `git show HEAD:engine/src/pb/mod.rs` before restoring).
- **Files modified:** `engine/src/pb/mod.rs`
- **Verification:** `git diff -- engine/src/pb/mod.rs` shows no content difference from HEAD after restoration (only Windows CRLF-normalization warning, no hunks); `cargo check` and `cargo test --no-run` both pass with the file present.
- **Committed in:** `d59bd0c` (part of Task 1 commit) — note the file was staged but, being byte-identical to HEAD, produced no diff in the commit; it exists on disk and in the index unchanged.

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to keep the crate compiling after buf's `clean: true` regeneration; no scope creep — the restored file's content is unchanged from what 05-01/05-06 already established, and no hand-written business logic was touched.

## Issues Encountered
None beyond the auto-fixed deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 05-02 can now reference `NodeErrorKind::InputValidation` (Rust) and `NodeErrorKind_NODE_ERROR_KIND_INPUT_VALIDATION` (Go) directly; the wire-contract gap blocking its typed ninth-variant rejection is closed.
- No blockers identified for 05-02.

---
*Phase: 05-state-machine-workflow-events*
*Completed: 2026-08-13*

## Self-Check: PASSED

- FOUND: proto/lancet/v1/lancet.proto
- FOUND: engine/src/pb/lancet/v1/lancet.v1.rs
- FOUND: gateway/proto/lancet/v1/lancet.pb.go
- FOUND: engine/src/pb/mod.rs
- FOUND: .planning/phases/05-state-machine-workflow-events/05-07-SUMMARY.md
- FOUND: commit d59bd0c (Task 1)
- FOUND: commit 98ee10f (SUMMARY.md)
