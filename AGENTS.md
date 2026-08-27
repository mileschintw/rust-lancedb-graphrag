# Agent Guidelines

## Language-Specific Rules

### Rust Guidelines
- **Trigger**: ONLY read or consult `rust-guidelines.md` when creating, editing, or refactoring Rust code (`.rs` files or Cargo components).
- **Action**: Before writing Rust code, view `rust-guidelines.md` in the root folder and adhere to its guidelines.
- **Scope Restriction**: Do NOT read `rust-guidelines.md` for non-Rust tasks (e.g., Go, HTML/JS, Protobuf, or documentation) to save context and prevent irrelevant rules from being applied.

### Go Guidelines
- **Trigger**: ONLY read or consult `go-guidelines.md` when creating, editing, or refactoring Go code (`.go` files or `go.mod`).
- **Action**: Before writing Go code, view `go-guidelines.md` in the root folder, detect the Go version from `go.mod` (using the pattern in the file), and adhere to its guidelines up to that Go version.
- **Scope Restriction**: Do NOT read `go-guidelines.md` for non-Go tasks (e.g., Rust, HTML/JS, Protobuf, or documentation) to save context and prevent irrelevant rules from being applied.

## Code Review Guidelines

### Claim/Lease Integration Tests (Review Convention)
- **Rule**: Every integration test that globally claims, leases, dequeues, or batch-selects mutable rows must use a unique per-test schema or isolated test database before queries run.
- **Reviewer Checklist**:
  - Verify every fixture and claimant connection uses the isolated per-test schema/database.
  - Verify every external snapshot before/after count query error is fatal (`t.Fatalf`) to prevent false-passing comparisons.
- **Note**: This is a review convention only; no automated linter, hook, or workflow policy is enforced.

## Cursor Cloud specific instructions

Lancet is one product with two required services that talk over gRPC/Protobuf, plus PostgreSQL and an external OpenRouter API. Standard build/run commands live in `README.md`, `docker-compose.yml`, and `verify-ingestion.sh`; the notes below are the non-obvious, per-boot caveats.

### Toolchains (installed in the VM image)
- Go **1.25** (`/usr/local/go`, on PATH ahead of the distro Go 1.22) — `gateway/go.mod` requires `go 1.25.0`.
- Rust **stable ≥1.85** is mandatory (a transitive LanceDB dependency needs the `edition2024` cargo feature); the image ships current stable via rustup. Rust 1.83 fails with `feature edition2024 is required`.
- Native build deps for the engine: `build-essential`, `pkg-config`, `libssl-dev` (transitive `openssl-sys` from LanceDB's object-store stack), and `protobuf-compiler` (`protoc`, needed by a dependency `build.rs`). The engine's own protobufs are pre-generated under `engine/src/pb`, so `buf` is not required just to build.
- `buf` (in `/usr/local/bin`) for Protobuf codegen from `proto/` per `buf.gen.yaml`. `buf lint`, `buf build`, and `buf generate` all run from the repo root. `buf generate` uses **remote** plugins (needs network to `buf.build`) and writes to `engine/src/pb` + `gateway/proto`; regenerating currently produces no diff. If you change `proto/`, run `buf generate` and commit the regenerated Go/Rust stubs.
- `atlas` (in `/usr/local/bin`) for PostgreSQL schema migrations. Config is `gateway/atlas.hcl` (env `local`); run atlas commands from `gateway/`. It needs a reachable Postgres for both the target `url` and the `dev` database (`.../postgres`). `atlas schema apply --env local` reconciles the DB to `gateway/db/schema.hcl` — this is the HCL-driven alternative to piping `gateway/db/schema.sql`; the two definitions are kept in sync. Use `--dry-run` to preview.

### Per-boot startup (NOT in the update script — start these manually each session)
- Docker daemon is not auto-started: `sudo dockerd &` (Docker 29 here uses `fuse-overlayfs` with `containerd-snapshotter=false` in `/etc/docker/daemon.json`).
- PostgreSQL: `sudo docker compose up -d db`, then apply the schema once per fresh volume: `sudo docker compose exec -T db psql -U postgres -d lancet -f - < gateway/db/schema.sql`.
- Engine (from repo root): `OPENROUTER_API_KEY=... ./engine/target/debug/engine` (or `cargo run --manifest-path engine/Cargo.toml --bin engine`). It **fails fast at startup if `OPENROUTER_API_KEY` is unset/blank** and listens on gRPC `[::1]:50051`.
- Gateway (from `gateway/`): `LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable' go run .`. It binds loopback-only `127.0.0.1:8080` by design and dials the engine lazily, so it starts even if the engine is down; `GET /health` returns 200 only once the engine is reachable.

### Gotchas
- Both services print continuous OTLP export **ERROR** lines (`connect: connection refused` to `127.0.0.1:4317`) unless the optional observability stack is running (`docker compose --profile observability up -d`). This is harmless (Phase 6 not started) and does not affect functionality.
- A **valid `OPENROUTER_API_KEY`** is required to actually complete ingestion (embeddings) and `/rag/query` (generation). With a placeholder key the pipeline runs through the custom chunker and LanceDB write, then the OpenRouter call returns HTTP 401 and the document status becomes `failed`.
- Tests: `cargo test --manifest-path engine/Cargo.toml` passes offline (1 OpenRouter smoke test is `#[ignore]`). Gateway unit packages (`db`, `internal/...`) pass offline; the root `github.com/lancet/gateway` package holds cross-runtime integration tests that spawn the engine and need a real `OPENROUTER_API_KEY`.
- Lint: production Rust lint is clean via `cargo clippy --manifest-path engine/Cargo.toml --lib --bins`. `--all-targets` clippy and `cargo fmt --check` report pre-existing findings in test code under current stable — do not treat those as regressions.
