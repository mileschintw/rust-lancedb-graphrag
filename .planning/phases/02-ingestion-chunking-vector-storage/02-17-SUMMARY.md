# Phase 02-17 Summary: Configuration Discovery, Chunk Settings Contract, and Loopback Guardrail

## Summary
- **Plan File:** [02-17-PLAN.md](./02-17-PLAN.md)
- **Status:** Completed
- **Findings Addressed:** CR-01, CR-02, CR-04 (local guardrail)

## Work Completed

### Task 1: Shared Configuration Contract (`CR-01`)
- Updated `load_settings()` in `engine/src/main.rs` to resolve `LANCET_CONFIG_DIR` first when present before falling back to repository-relative `config/config` paths.
- Applied `config.{LANCET_ENV}` overlay file resolution from the chosen configuration directory and enforced `LANCET_` double-underscore environment variable overrides as highest precedence.
- Created process-level integration test suite in `engine/tests/config_startup.rs` asserting:
  - Rust engine starts cleanly from a config-less working directory when `LANCET_CONFIG_DIR` points to an isolated configuration directory.
  - Rust engine preserves repository-relative discovery when `LANCET_CONFIG_DIR` is absent.
  - Overlay loading and environment variable override precedence behave as required.

### Task 2: Exact Chunk Settings Contract & Loopback Guardrail (`CR-02` & `CR-04`)
- Aligned Go gateway and Rust engine on canonical strategy identifiers `structure-aware` and `fixed-size`.
- Implemented optional multipart parameter parsing (`chunk_strategy`, `chunk_size`, `chunk_overlap`) in `createDocument`:
  - Enforced strategy validation (`structure-aware` or `fixed-size`), positive integer check for size, non-negative integer check for overlap, and `overlap < size`.
  - Enforced locked JSON strategy rule: `.json` files persist and stream as `fixed-size`.
- Updated gRPC streaming boundary in Go to transmit persisted chunk settings (`chunk_strategy`, `chunk_size`, `chunk_overlap`) on the first streamed frame.
- Enforced stream admission validation in Rust:
  - First frame must supply valid metadata keys and values; invalid settings are rejected with `Status::invalid_argument`.
  - Subsequent stream frames must not contain metadata.
- Implemented CR-04 local-only exposure guardrail:
  - Configured Go gateway server address binding explicitly to `127.0.0.1:<port>`.
  - Documented local-only constraint and `DEBT-CR-04` review triggers in `README.md`.

## Verification Results

### Automated Tests
- `cargo test --manifest-path engine/Cargo.toml --test config_startup -- --test-threads=1`: **PASS** (3/3 passed in 0.30s)
- `cargo test --manifest-path engine/Cargo.toml`: **PASS** (42/42 passed in 12.82s)
- `cargo clippy --manifest-path engine/Cargo.toml --all-targets -- -D warnings`: **PASS** (0 warnings)
- `go test -count=1 ./...` (gateway): **PASS** (all tests passed in 1.03s)
- `go vet ./...` (gateway): **PASS** (0 issues)

## Key Files Modified
- [engine/src/main.rs](../../../engine/src/main.rs): `load_settings()`, `ChunkSettings`, `parse_chunk_settings`, `ingest_document` first-frame metadata validation.
- [engine/src/tests.rs](../../../engine/src/tests.rs): `IngestionJob::new` helper and `chunk_metadata_contract` unit tests.
- [engine/tests/config_startup.rs](../../../engine/tests/config_startup.rs): Process-level configuration discovery & precedence regression suite.
- [gateway/main.go](../../../gateway/main.go): Multipart chunk settings parsing, gRPC first-frame metadata streaming, `formatListenAddr` loopback bind.
- [gateway/main_test.go](../../../gateway/main_test.go): `TestCreateDocumentChunkSettingsContract`, `TestGrpcEngineStreamsChunkSettings`, `TestGatewayAddressIsLoopback`.
- [README.md](../../../README.md): Documented local-only exposure constraint and `DEBT-CR-04` triggers.
