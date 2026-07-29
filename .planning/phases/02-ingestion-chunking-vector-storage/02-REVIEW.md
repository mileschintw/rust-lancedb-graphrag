---
phase: 02-ingestion-chunking-vector-storage
reviewed: 2026-07-29T02:12:56Z
depth: standard
files_reviewed: 31
files_reviewed_list:
  - .gitignore
  - config/config.toml
  - config/config.verify.toml
  - engine/Cargo.toml
  - engine/Cargo.lock
  - engine/src/lib.rs
  - engine/src/main.rs
  - engine/src/tests.rs
  - engine/src/db/mod.rs
  - engine/src/db/tests.rs
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
  - engine/src/bin/inspect_lancedb.rs
  - engine/src/inspect_lancedb_tests.rs
  - gateway/go.mod
  - gateway/go.sum
  - gateway/main.go
  - gateway/main_test.go
  - gateway/db/query.sql
  - gateway/db/query.sql.go
  - gateway/db/schema.hcl
  - gateway/db/schema.sql
  - gateway/db/document_test.go
  - proto/lancet/v1/lancet.proto
  - scripts/phase02_live_evidence.py
  - scripts/test_phase02_live_evidence.py
  - scripts/test_phase02_privacy_prohibition.cjs
  - scripts/fixtures/phase02_privacy_clean.json
  - scripts/fixtures/phase02_privacy_violation.json
  - verify-ingestion.sh
  - verify-live-evidence.sh
findings:
  critical: 6
  warning: 5
  info: 0
  total: 11
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-29T02:12:56Z
**Depth:** standard
**Files Reviewed:** 31
**Status:** issues_found

## Narrative Findings (AI reviewer)

### Summary

The refreshed review covered all supplied Phase 02 files and rechecked the intent and closure history in Plans 02-01 through 02-16. Nine of the prior report's ten findings are closed in current production code. Prior CR-02 remains only partially fixed: compensation now retries, but a fixed five-attempt cap can still permanently strand metadata.

Six blockers and five warnings remain. The most consequential issues are inconsistent chunk metadata across PostgreSQL and Rust, non-durable failed-admission reconciliation, an unauthenticated all-interface upload endpoint backed by a provider credential, and resource exhaustion before bounded queue admission.

Verification results:

- `cargo fmt --manifest-path engine/Cargo.toml -- --check` — PASS
- `cargo test --manifest-path engine/Cargo.toml` — PASS (37 tests)
- `cargo clippy --manifest-path engine/Cargo.toml --all-targets -- -D warnings` — PASS
- `go test -count=1 ./...` and `go vet ./...` from `gateway` — PASS
- `python -O -I scripts/test_phase02_live_evidence.py` with `PYTHONOPTIMIZE=1` — PASS (7 tests)
- Privacy fixture behavior — clean fixture PASS; known-bad fixture rejected
- Git Bash syntax checks for both verification scripts — PASS

These suites do not exercise the blocker paths below. The `LANCET_CONFIG_DIR` startup defect was reproduced by launching the built engine outside the repository with the variable pointing at the real config directory; it exited with `configuration file "config/config" not found`.

### Critical Issues

#### CR-01: The Rust engine ignores the supported `LANCET_CONFIG_DIR`

**Classification:** BLOCKER

**File:** `engine/src/main.rs:58-73`

**Issue:** The Go gateway honors `LANCET_CONFIG_DIR`, but the Rust engine chooses configuration only from `../config` or `./config`. A deployment that uses the documented shared configuration-directory override can start the gateway while the engine fails before serving. This was reproduced from a config-less working directory with `LANCET_CONFIG_DIR` pointing to the repository config directory.

**Fix:** Resolve the base file from `LANCET_CONFIG_DIR` first, then apply the optional environment overlay and `LANCET_` overrides to that same directory. Add a process-level startup/config test from a config-less working directory.

```rust
let config_dir = std::env::var_os("LANCET_CONFIG_DIR")
    .map(PathBuf::from)
    .unwrap_or_else(discover_default_config_dir);
let base = config_dir.join("config.toml");
let mut builder = config::Config::builder()
    .add_source(config::File::from(base));
```

#### CR-02: PostgreSQL records a chunk strategy the engine never receives or executes

**Classification:** BLOCKER

**File:** `gateway/main.go:134-160, 260-266`; `engine/src/main.rs:173-199, 255-269`

**Issue:** The gateway stores `ChunkStrategy: "recursive"`, but `"recursive"` is not a Rust strategy. The gRPC client also omits `metadata` entirely, so Rust defaults to `"structure-aware"` and default sizes regardless of the PostgreSQL metadata. The durable API record therefore lies about how the document was chunked, and future per-document settings would silently be ignored at the engine boundary.

**Fix:** Use the canonical strategy name and pass the persisted strategy, size, and overlap in the first streamed request (or every request with equality validation). Make the engine reject unknown strategies instead of silently treating them as structure-aware.

```go
metadata := map[string]string{
    "chunk_strategy": doc.ChunkStrategy,
    "chunk_size": strconv.Itoa(int(doc.ChunkSize)),
    "chunk_overlap": strconv.Itoa(int(doc.ChunkOverlap)),
}
```

#### CR-03: Failed-admission compensation is still not eventually durable

**Classification:** BLOCKER

**File:** `gateway/main.go:187-217, 267-287`

**Issue:** Compensation retries only five times and then returns without recording any durable reconciliation intent or failure result. An outage lasting longer than those attempts leaves the row `queued` even though the gateway has returned 429/502 and the engine did not admit the job. A later GET can repair the row only if a client happens to poll and the engine returns NotFound; without that external action the stale row remains indefinitely. This is the core failure mode from prior CR-02.

**Fix:** Persist an admission/reconciliation intent transactionally with the queued row and process it in a background reconciler until a terminal update or verified terminal winner is observed. The request path may use bounded retries, but exhausting them must hand off to durable work rather than silently stop.

#### CR-04: The upload API is unauthenticated and listens on every interface

**Classification:** BLOCKER

**File:** `gateway/main.go:219-225, 369-391`; `engine/src/main.rs:803`

**Issue:** `POST /documents` has no authentication or authorization middleware, and the server address `":<port>"` binds all interfaces. Any network-reachable caller can submit content that is forwarded to the engine and processed with the service's private OpenRouter credential, consuming provider quota and local PostgreSQL/LanceDB storage. Upload contents also travel over plaintext HTTP.

**Fix:** If this phase is local-only, bind explicitly to loopback and reject non-local deployment configuration. Otherwise require authentication/authorization, TLS at the ingress, request-rate quotas, and per-principal ingestion limits before exposing the endpoint.

#### CR-05: Bounded queue admission does not bound concurrent upload memory or connection lifetime

**Classification:** BLOCKER

**File:** `gateway/main.go:221, 239-266, 389`; `engine/src/main.rs:255-288`

**Issue:** The gateway has no body read deadline or concurrency limiter, and Rust buffers the entire stream into a `Vec` before reserving a queue slot. An attacker can hold multipart bodies open indefinitely or create many concurrent streams, each consuming up to 10 MiB, without consuming any of the queue's 100 permits. The bounded queue therefore does not provide the claimed ingestion-exhaustion protection.

**Fix:** Add HTTP `ReadTimeout`/`WriteTimeout`/`IdleTimeout`, enforce a bounded upload semaphore before body streaming, and reserve engine admission capacity before buffering the full document. Release permits on every parse/stream failure.

#### CR-06: Inspector errors can disclose an untrusted persisted model value

**Classification:** BLOCKER

**File:** `engine/src/bin/inspect_lancedb.rs:186-199`

**Issue:** When a persisted `embedding_model` is unknown, the inspector interpolates the value into its error. That column is untrusted durable input; a corrupted row containing a credential or stored content would be printed to terminal/service logs during live validation, violating the phase's no-content/no-secret evidence contract.

**Fix:** Return a class-only error and never serialize the stored value.

```rust
let provider = match embedding_model.as_str() {
    EMBEDDING_MODEL => "openrouter".to_owned(),
    _ => return Err("LanceDB contains an unknown embedding_model".to_owned()),
};
```

### Warnings

#### WR-01: Final privacy enforcement is skipped when Node is unavailable

**Classification:** WARNING

**File:** `verify-live-evidence.sh:129-139`

**Issue:** `--validate-gate` runs the descriptor-backed privacy test only inside `if command -v node`; an environment without Node silently skips a mandatory acceptance check and continues toward cleanup.

**Fix:** Treat Node as a required command during preparation and validation, and exit nonzero if the privacy test cannot run.

#### WR-02: The Node privacy check covers fewer field classes than production validation

**Classification:** WARNING

**File:** `scripts/test_phase02_privacy_prohibition.cjs:6-26`; `scripts/phase02_live_evidence.py:84-97`

**Issue:** The descriptor-backed test recognizes only seven exact keys. It misses production classes such as `credential`, `secret`, `bearer`, `authorization_header`, `raw_content`, `document_text`, and `chunk_content`. A subject containing those keys can pass the advertised machine-wired prohibition even though the Python validator would reject it.

**Fix:** Share one canonical forbidden-field vocabulary or implement the same normalized substring classification in both checks. Add one bad fixture per prohibited class.

#### WR-03: Several closure tests are false positives for their named behavior

**Classification:** WARNING

**File:** `engine/src/tests.rs:601-665`; `engine/src/inspect_lancedb_tests.rs:357-430`; `scripts/test_phase02_live_evidence.py:244-250, 359-364`

**Issue:** The schema-lookup regression injects `NodesAdd`, not a missing schema field, and does not prove worker survival. The embedding-child test checks only a null child despite claiming null and NaN/positive-infinity/negative-infinity coverage. The overlong-run case changes only `evidence.issued_at`, so it fails on challenge mismatch rather than the run-window bound. The explicit-path live-script test only searches source text and never captures the actual inspector arguments.

**Fix:** Add dedicated injection seams/fixtures for the exact failure classes and assert the expected error reason, persisted state, and process arguments. Avoid relying on test names or generic `is_err()` assertions as evidence.

#### WR-04: Verification store selection silently falls back after configuration errors

**Classification:** WARNING

**File:** `verify-ingestion.sh:153-166`; `verify-live-evidence.sh:140-153`

**Issue:** Both scripts catch every TOML error, use a permissive regex, and finally default to a hardcoded store path. A malformed or incomplete verification config can therefore inspect a different or stale store instead of failing closed. The returned relative path is also interpreted from the caller's working directory rather than resolved against the repository root.

**Fix:** Parse the committed TOML strictly, require a non-empty `engine.lancedb_path`, resolve it against the repository root, require the intended directory/store contract, and abort on every parse/key/path error.

#### WR-05: The verification inspector mutates the store it is supposed to inspect

**Classification:** WARNING

**File:** `engine/src/bin/inspect_lancedb.rs:362-367`; `engine/src/db/mod.rs:14-49`

**Issue:** The inspector calls `DatabaseManager::initialize`, which creates any missing tables before inspection. A missing `staged_documents` table can be silently recreated as empty and then reported as the required zero-row state, masking the original durable-store condition. Diagnostic verification should not change evidence before evaluating it.

**Fix:** Add a read-only `open_and_validate` path that requires all expected tables to exist and validates their schemas without creating or restoring anything. Keep table creation exclusive to engine startup.

---

_Reviewed: 2026-07-29T02:12:56Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
