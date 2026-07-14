---
status: complete
completed_at: "2026-07-14T17:45:00Z"
---

# Summary: Dependency Upgradability Assessment (Rust Cargo, Go Gateway & Jaeger)

We assessed the upgradability of the Lancet project's dependencies—specifically Rust cargo dependencies, Go gateway dependencies, and the Jaeger docker image. All components are upgradable, but some adjustments are required for Rust and Jaeger.

## Findings & Changes Made

### 1. Rust Cargo Engine Dependencies (Upgraded & Verified)
We successfully upgraded all Rust dependencies in the RAG engine to their latest versions:
- **Tokio:** `1.37.0` $\rightarrow$ `1` (resolves to `1.43.0+`)
- **Tonic:** `0.11.0` $\rightarrow$ `0.14` (resolves to `0.14.6`)
- **Prost:** `0.12.0` $\rightarrow$ `0.14` (resolves to `0.14.4`)
- **Tracing:** `0.1.40` $\rightarrow$ `0.1` (resolves to `0.1.44`)
- **Tracing Subscriber:** `0.3.18` $\rightarrow$ `0.3` (resolves to `0.3.23`)

**Required Code Adjustments Made:**
- **Build Dependency Swap:** Changed `tonic-build = "0.14"` to `tonic-prost-build = "0.14"` in `Cargo.toml` because `tonic-build` 0.14 no longer supports protobuf compilation directly (it decoupled protobuf compilation to `tonic-prost-build`).
- **Build Script Update:** Updated `engine/build.rs` to call `tonic_prost_build::compile_protos` instead of `tonic_build::compile_protos`.
- **Standalone `tonic-prost` Crate:** Added `tonic-prost = "0.14"` to `[dependencies]` in `Cargo.toml`. Since `tonic` 0.14, Prost integration is decoupled into a standalone crate, which is required for generated code.
- **Verification:** Recompiled using `cargo check` and confirmed it compiles successfully.

### 2. Go Gateway Dependencies (Upgraded & Verified)
We upgraded the Go dependencies to their latest minor/patch versions:
- `github.com/go-chi/chi/v5` $\rightarrow$ `v5.2.5`
- `github.com/jackc/pgx/v5` $\rightarrow$ `v5.10.1` (includes fixes for CVE-2026-33816)
- `go.uber.org/zap` $\rightarrow$ `v1.28.0`
- `google.golang.org/grpc` $\rightarrow$ `v1.82.0`
- `google.golang.org/protobuf` $\rightarrow$ `v1.36.11`
- **Verification:** Ran `go mod tidy` and `go build`, which completed successfully without errors.

### 3. Jaeger Docker Image
- **Current image:** `jaegertracing/all-in-one:latest` (v1-based).
- **Status:** **Jaeger v1 reached End-of-Life (EOL) on December 31, 2025.** It is no longer supported or updated.
- **Upgrade Path (Jaeger v2):**
  - Jaeger v2 is based on the OpenTelemetry Collector framework.
  - Image repository is now `cr.jaegertracing.io/jaegertracing/jaeger` (e.g. `cr.jaegertracing.io/jaegertracing/jaeger:2.11.0` or `2.x`).
  - Old environment variables like `COLLECTOR_OTLP_ENABLED=true` are no longer supported. Configuration is now done using an OTel Collector YAML configuration file (e.g., `config.yaml`) mounted into the container.
