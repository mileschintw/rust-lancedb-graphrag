# Plan: Migrate Rust Protobuf Generation to Buf

## Goal
Replace the build-time Protobuf compilation in Rust (`build.rs` using `tonic_prost_build`) with static code generation via Buf using community plugins (`neoeinstein-prost` and `neoeinstein-tonic`). This will centralize all API generation in `buf.gen.yaml`, improve Rust IDE support, speed up compile times, and remove the build-time dependency on `protoc`.

## Tasks
1. Update `proto/buf.gen.yaml` to include Rust code generation using Buf's community plugins.
2. Run `buf generate` inside the `proto` directory to generate the Rust and Go files.
3. Modify `engine/Cargo.toml` to remove the `build-dependencies` and `tonic-prost-build` dependency.
4. Remove `engine/build.rs`.
5. Update `engine/src/main.rs` to include the generated files directly from the module path instead of `tonic::include_proto!`.
6. Verify that the Rust project compiles successfully (`cargo check` / `cargo build`).
7. Verify that the Go project compiles successfully (`go build ./...` inside `gateway`).
8. Document changes in `SUMMARY.md` and update `.planning/STATE.md`.
