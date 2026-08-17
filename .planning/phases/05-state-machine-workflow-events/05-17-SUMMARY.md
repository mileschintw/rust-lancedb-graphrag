---
phase: 05-state-machine-workflow-events
plan: 17
type: execute
status: completed
executed_at: "2026-08-17T21:35:00.000Z"
requirements:
  - ORCH-01
  - ORCH-02
  - ORCH-04
files_modified:
  - proto/lancet/v1/lancet.proto
  - buf.gen.yaml
  - buf.yaml
  - engine/src/pb/lancet/v1/lancet.v1.rs
  - gateway/proto/lancet/v1/lancet.pb.go
---

# Plan 05-17 Execution Summary: Additive Protobuf Fields & Synchronized Generated Bindings

## Overview

Plan 05-17 (Wave 11) successfully introduced additive protobuf wire fields and synchronized checked-in Rust and Go bindings without schema drift or breaking wire changes.

## Key Changes

1. **Protobuf Schema (`proto/lancet/v1/lancet.proto`)**:
   - Added `uint32 variant_count = 10` and `repeated string variant_identities = 11` to `RetrievalSnapshot`, preserving historical tags 1 through 9.
   - Added `repeated Notice notices = 6` to `WorkflowCompletedEvent`, preserving historical tags 1 through 5 and existing oneof event tags.
2. **Buf Configuration (`buf.gen.yaml` & `buf.yaml`)**:
   - Set `clean: false` in `buf.gen.yaml` to protect the hand-written Rust module glue in `engine/src/pb/mod.rs` from cleanup during generation.
   - Configured `RPC_RESPONSE_STANDARD_NAME` exception under `lint.use = [STANDARD]` in `buf.yaml` for the streaming `WorkflowEvent` RPC response.
3. **Generated Bindings**:
   - Generated Rust prost/tonic bindings in `engine/src/pb/lancet/v1/lancet.v1.rs` including the new fields.
   - Generated Go protobuf bindings in `gateway/proto/lancet/v1/lancet.pb.go` including the new fields.
   - Verified that `engine/src/pb/mod.rs` remained intact and byte-for-byte unchanged across generation.

## Verification & Determinism

- **Inventory Check**: Checked-in output inventory strictly matched the allowlist (`engine/src/pb/mod.rs`, `engine/src/pb/lancet/v1/lancet.v1.rs`, `engine/src/pb/lancet/v1/lancet.v1.tonic.rs`, `gateway/proto/lancet/v1/lancet.pb.go`, `gateway/proto/lancet/v1/lancet_grpc.pb.go`).
- **Compatibility**: `buf breaking --against '.git#branch=main'` passed with 0 errors.
- **Linting**: `buf lint` passed with 0 errors.
- **Determinism**: Hash verification across repeated `buf generate` executions confirmed identical SHA256 hashes for all generated files.
- **Ownership Hand-off**: Rust struct literal compile repairs in `engine/src/workflow/events.rs` and `engine/src/workflow/nodes/retrieve.rs` and Rust wire round-trip proof are cleanly delegated to Plan 05-23 (Wave 12) per plan design.

## Commit

- `feat(05-17): wire additive protobuf schema and synchronized Rust/Go bindings`
