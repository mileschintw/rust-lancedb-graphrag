# Plan: Check Dependency Upgradability (Rust Cargo & Jaeger Image)

## Goal
Verify whether the dependencies of the Lancet project (specifically Rust cargo dependencies and the Jaeger docker image, plus Go gateway dependencies) can be updated to their latest versions, and confirm if the project remains functional/compilable after doing so.

## Tasks
1. Establish baseline by running `cargo check` on the existing Rust engine.
2. Research current latest versions for:
   - Rust dependencies: `tokio`, `tonic`, `prost`, `tracing`, `tracing-subscriber`, `tonic-build`
   - Go dependencies: `go-chi/chi`, `pgx`, `zap`, `grpc`, `protobuf`
   - Jaeger docker image (currently `jaegertracing/all-in-one:latest`)
3. Upgrade Rust cargo dependencies to their latest compatible/stable versions.
4. Compile/check the Rust engine with updated dependencies to identify any breaking changes or deprecation warnings.
5. Identify any potential upgrades or compatibility changes for the Jaeger image.
6. Revert dependency modifications (or keep if desired, but default is to check and report, keeping the workspace clean or proposing updates).
7. Document the findings in `SUMMARY.md`.
8. Update `.planning/STATE.md` to record the quick task.
