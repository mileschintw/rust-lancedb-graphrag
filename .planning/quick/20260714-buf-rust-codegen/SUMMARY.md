---
status: complete
completed_at: "2026-07-14T12:24:00Z"
---

# Summary: Migrate Rust Protobuf Generation to Buf

We successfully migrated the Rust engine's Protobuf code generation from build-time compilation (`build.rs` using `tonic_prost_build`) to static code generation via Buf using community BSR plugins.

## Changes Made

### 1. Buf Configuration Migration (v2)
- Migrated [proto/buf.yaml](file:///c:/Users/user3/repos/lancet/proto/buf.yaml) and [proto/buf.gen.yaml](file:///c:/Users/user3/repos/lancet/proto/buf.gen.yaml) to Buf v2 configuration format.
- Kept the Buf configuration isolated inside the `proto/` directory to keep the project root clean.
- Configured BSR community plugins `neoeinstein-prost` and `neoeinstein-tonic` (version `v0.5.0` for Tonic 0.14 compatibility) to output generated Rust files into `engine/src/pb/`.
- Configured the `neoeinstein-tonic` plugin with `no_client=true` option since the Rust engine only serves the server side.
- Configured `clean: true` in the generation template to prevent stale code generation artifacts.

### 2. Rust Engine Codebase Scaffolding Updates
- Removed the [engine/build.rs](file:///c:/Users/user3/repos/lancet/engine/build.rs) build script completely.
- Removed the `tonic-prost-build` dependency from `[build-dependencies]` in [engine/Cargo.toml](file:///c:/Users/user3/repos/lancet/engine/Cargo.toml).
- Updated [engine/src/main.rs](file:///c:/Users/user3/repos/lancet/engine/src/main.rs) to include the generated `lancet.v1.rs` file directly via standard `include!("pb/lancet/v1/lancet.v1.rs")` inside the module structure.
- Removed duplicate includes because the `neoeinstein-prost` plugin automatically generates an `include!("lancet.v1.tonic.rs");` directive inside `lancet.v1.rs`.

### 3. Verification & Compilation
- Ran `buf generate` successfully from the `proto/` directory.
- Verified that the Rust engine compiles successfully (`cargo check` passes in 0.74s).
- Verified that the Go gateway compiles successfully (`go build ./...` inside `gateway` passes).
