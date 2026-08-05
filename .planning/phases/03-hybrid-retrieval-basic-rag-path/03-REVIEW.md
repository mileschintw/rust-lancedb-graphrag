---
phase: 03-hybrid-retrieval-basic-rag-path
reviewed: 2026-08-05T20:26:26Z
depth: standard
files_reviewed: 31
files_reviewed_list:
  - config/config.example.toml
  - config/config.toml
  - engine/Cargo.lock
  - engine/Cargo.toml
  - engine/src/bin/seed_rag_fixture.rs
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
  - engine/src/db/mod.rs
  - engine/src/db/tests.rs
  - engine/src/generation/mod.rs
  - engine/src/generation/openrouter.rs
  - engine/src/generation/tests.rs
  - engine/src/lib.rs
  - engine/src/main.rs
  - engine/src/pb/lancet/v1/lancet.v1.rs
  - engine/src/pb/lancet/v1/lancet.v1.tonic.rs
  - engine/src/prompt.rs
  - engine/src/rerank/mod.rs
  - engine/src/rerank/tests.rs
  - engine/src/retrieval/bm25.rs
  - engine/src/retrieval/dense.rs
  - engine/src/retrieval/fusion.rs
  - engine/src/retrieval/mod.rs
  - engine/src/retrieval/tests.rs
  - engine/src/tests.rs
  - engine/tests/config_startup.rs
  - gateway/main.go
  - gateway/main_test.go
  - gateway/proto/lancet/v1/lancet_grpc.pb.go
  - gateway/proto/lancet/v1/lancet.pb.go
  - proto/lancet/v1/lancet.proto
findings:
  critical: 5
  warning: 12
  info: 0
  total: 17
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-08-05T20:26:26Z  
**Depth:** standard  
**Files Reviewed:** 31  
**Status:** issues_found

## Summary

This is a live-checkout refresh after plans 03-19 through 03-23. The new aggregate retrieval ceilings, per-source fusion deduplication, bounded BM25 candidate workspace, shared provider-body guard, and append-before-delete replacement ordering are present. The checkout still has 5 blocker-level defects and 12 warnings, concentrated in transport security, staged-generation concurrency, provider resource enforcement, and fail-closed/API consistency.

## Critical Issues

### CR-01: [BLOCKER] Provider body limit is checked after an unbounded response chunk is materialized

**Severity:** BLOCKER  
**File:** `engine/src/client/mod.rs:37-56`

**Issue:** `read_body_limited` checks `Content-Length` early, but for responses without that header it calls `reqwest::Response::chunk()` and only checks the aggregate size after the returned chunk has already been materialized. A provider can therefore deliver a single transport frame larger than 256 KiB and force that allocation before the guard rejects it. This does not implement the phase contract's hard `bytes_stream()` boundary before untrusted response allocation and leaves a provider-controlled memory-exhaustion path.

**Fix:** Consume the response through the bounded streaming path specified by the contract, enforce the remaining byte budget before retaining each frame, and make the transport reader reject an over-sized individual frame without copying it into the accumulated body. Add a regression using one over-limit frame, not only multiple small chunks.

### CR-02: [BLOCKER] Concurrent staged writes can allocate the same generation and poison replay

**Severity:** BLOCKER  
**File:** `engine/src/main.rs:872-902, 993-1047`

**Issue:** `persist_raw_with_boundary` reads the current maximum generation and then appends `old_max + 1` without a per-document lock, transactional compare-and-swap, or unique constraint. Tonic serves concurrent `IngestDocument` calls, so two callers using the same valid document UUID can observe the same maximum and append duplicate successor rows. The verification only checks that at least one matching row exists (`engine/src/main.rs:904-924`), while replay explicitly fails on equal-generation rows (`engine/src/main.rs:683-687`). A concurrent upload can therefore turn durable staging into an ambiguous state that prevents startup replay or status recovery.

**Fix:** Serialize staging mutations per document or implement an atomic generation allocation with a uniqueness guarantee. Verify exactly one successor and its expected identity/payload before deleting older generations; test concurrent same-document ingestion and all append/verify/delete failure combinations.

### CR-03: [BLOCKER] Committed database configuration contains a reusable password and disables TLS

**Severity:** BLOCKER  
**File:** `config/config.toml:1-4`; `config/config.example.toml:5-8`

**Issue:** Both committed configuration files contain `postgres:postgres` and `sslmode=disable`. The example is explicitly intended to be copied into environment-specific configuration, so this default is easy to deploy unchanged and permits database credentials and traffic to travel without transport protection.

**Fix:** Remove credentials from committed files and require an environment/secret-manager supplied database URL. Require TLS verification for non-local connections, and make an explicitly insecure local-development mode opt-in rather than the committed default.

### CR-04: [BLOCKER] Gateway-to-engine gRPC is always plaintext and unauthenticated

**Severity:** BLOCKER  
**File:** `gateway/main.go:875-894`

**Issue:** The gateway unconditionally creates its engine connection with `insecure.NewCredentials()` at line 890 even though `engine_addr` is configurable. A network observer can read or modify ingestion and query traffic, and any reachable peer can impersonate the engine. This also exposes the gateway's database-backed workflow to an unauthenticated engine endpoint.

**Fix:** Configure TLS with certificate and hostname validation, preferably mutual TLS or an equivalent engine authentication mechanism. Bind and validate a loopback-only plaintext mode solely as an explicit development option, and fail startup when a remote address is paired with insecure credentials.

### CR-05: [BLOCKER] Configurable provider endpoints can exfiltrate bearer credentials

**Severity:** BLOCKER  
**File:** `engine/src/main.rs:352-372`; `engine/src/client/mod.rs:249-254`; `engine/src/generation/openrouter.rs:262-278`

**Issue:** Effective settings validate provider endpoints only for non-blank strings, while both embedding and generation clients attach the API key as a bearer token. `OpenRouterGenerationConfig::with_endpoints` can also replace already-validated endpoints after construction. An operator typo, compromised configuration, or arbitrary test/integration caller can point an endpoint at an attacker-controlled HTTP/HTTPS host and receive the credential.

**Fix:** Parse and validate every endpoint at the final construction boundary, require HTTPS except for an explicitly enabled loopback development mode, and restrict hosts to an approved provider allowlist. Revalidate after `with_endpoints` or remove that mutating escape hatch; never send a bearer token to an endpoint that has not passed the same policy.

## Warnings

### WR-01: [WARNING] Fixture seeder is not idempotent

**Severity:** WARNING  
**File:** `engine/src/bin/seed_rag_fixture.rs:69-91, 157-185`

**Issue:** Every run appends the same fixed document, nodes, and edges to the target LanceDB tables. Re-running the seeder creates duplicate canonical rows, changes BM25 statistics, and makes dense results depend on how many times the fixture was seeded.

**Fix:** Make the fixture command explicitly reset its owned document before inserting, or use an upsert keyed by the stable document/chunk/edge identifiers. At minimum, refuse to run against a non-empty fixture unless a reset flag is supplied.

### WR-02: [WARNING] Mixed answer basis is accepted without the required conflict disclosure

**Severity:** WARNING  
**File:** `engine/src/generation/mod.rs:182-235`; `engine/src/generation/tests.rs:701-713`

**Issue:** Grounding validation requires a citation for every answer basis but never requires a notice or warning when `answer_basis` is `Mixed`. The test at lines 701-713 explicitly accepts a Mixed answer with both disclosure arrays empty, despite the prompt contract requiring the model to disclose conflicting corpus evidence.

**Fix:** In `validate_grounding_with_limits`, require a non-empty, bounded notice or warning describing the conflict whenever the basis is `Mixed`, and add a rejection test for an undisclosed Mixed response.

### WR-03: [WARNING] Prompt-capacity failures are misclassified as invalid client requests

**Severity:** WARNING  
**File:** `engine/src/prompt.rs:132-152`; `engine/src/main.rs:1262-1270`; `gateway/main.go:691-711`

**Issue:** `PromptAssemblyError::NoEvidenceFits` represents a bounded service capacity failure, but `query_rag` maps every prompt assembly error to `Status::invalid_argument`. The gateway consequently returns HTTP 400 for a valid query whose complete evidence cannot fit, causing clients and operators to treat a server capacity condition as malformed input.

**Fix:** Map `NoEvidenceFits` to a capacity-appropriate gRPC status such as `ResourceExhausted` (and preserve D1 identity metadata), while retaining `InvalidArgument` only for malformed caller input. Map that status to a distinct HTTP 413/503 response as appropriate.

### WR-04: [WARNING] Retrieval and reranker failures drop D1 response identity

**Severity:** WARNING  
**File:** `engine/src/main.rs:816-836, 1194-1215`

**Issue:** The dense and generation paths use `d1_status`, which attaches session, correlation, and error-kind metadata, but BM25, fusion, and reranker errors are converted directly to `Status::internal`. The gateway already reads those trailers (`gateway/main.go:693-703`), so failures in three core pipeline stages lose the identity required for diagnosis and cross-runtime correlation.

**Fix:** Route every retrieval-pipeline infrastructure error through `d1_status`, assigning stable error-kind values for BM25, fusion, and reranking and preserving the original safe client-facing message.

### WR-05: [WARNING] Rust production modules are maintained in two module graphs

**Severity:** WARNING  
**File:** `engine/src/lib.rs:3-8`; `engine/src/main.rs:28-34`

**Issue:** The library exports `generation`, `prompt`, `rerank`, and `retrieval`, but the binary redeclares those same modules locally. Production `main` therefore compiles and uses a second set of types and implementations from the library/test graph, allowing fixes, traits, and tests to diverge silently across the Rust/Go integration boundary.

**Fix:** Remove the duplicate binary declarations and import the library modules (`engine::{generation, prompt, rerank, retrieval}`), keeping only genuinely binary-local modules such as `chunker` local.

### WR-06: [WARNING] Invalid numeric environment overrides are silently ignored

**Severity:** WARNING  
**File:** `engine/src/main.rs:451-459`

**Issue:** If an operator sets an invalid `LANCET_ENGINE__RETRIEVAL__EVIDENCE_TOKEN_BUDGET` or `LANCET_OPENROUTER__MAX_OUTPUT_TOKENS`, parsing simply fails and the prior file/default value remains in effect. This makes a typo look like a successful configuration load and is inconsistent with the otherwise fail-closed startup ceilings.

**Fix:** Return a configuration error for a present-but-invalid override, including the variable name and expected type. Only an absent variable should leave the file/default value unchanged.

### WR-07: [WARNING] Public ingestion paths silently substitute or saturate invalid chunk settings

**Severity:** WARNING  
**File:** `engine/src/main.rs:501-542, 553-567, 889-896`

**Issue:** `IngestionJob::new` converts any invalid metadata into default chunk settings, hiding the caller's error. Separately, direct `IngestionJob` construction can provide `usize` values that do not fit in the staging `i32` columns, and persistence silently converts those values to `i32::MAX`. The durable staging record can therefore describe a different chunking policy than the request supplied.

**Fix:** Make `IngestionJob::new` return a validation error (or expose only a validated constructor), validate `ChunkSettings` at every public boundary, and make the `usize` to `i32` conversions checked and fallible instead of saturating.

### WR-08: [WARNING] Staging readers do not handle null required fields fail-closed

**Severity:** WARNING  
**File:** `engine/src/main.rs:750-775, 839-861`

**Issue:** Replay and generation discovery call `.value(i)` on document ID, filename, raw content, chunk metadata, and generation arrays without checking `is_null(i)`. A malformed or partially written Lance row is not converted into the intended typed error; depending on the Arrow array, it can panic or feed invalid data into later validation and abort startup/replay.

**Fix:** Check nullability before every required-field access, return a staging-corruption error naming the table/column/row, and add a regression with nulls in each required staging column.

### WR-09: [WARNING] Ingestion does not reject non-finite embedding components before persistence

**Severity:** WARNING  
**File:** `engine/src/client/mod.rs:287-306`; `engine/src/main.rs:1544-1553, 1615-1621`

**Issue:** The provider response path and canonical replacement path check embedding count and dimension but not `f32::is_finite()`. A provider implementation or test double can return NaN or infinity, which then enters the fixed-size Lance vector array. Subsequent dense distance calculations may fail or produce invalid rankings even though ingestion was reported as accepted.

**Fix:** Validate every embedding component for finiteness at the provider boundary and again immediately before building the Lance vector array; return a permanent ingestion error without mutating canonical tables when validation fails.

### WR-10: [WARNING] Finite BM25 boosts can still produce non-finite scores

**Severity:** WARNING  
**File:** `engine/src/retrieval/bm25.rs:49-67, 266-298`

**Issue:** BM25 validation accepts any finite non-negative field boost, including values large enough for the score arithmetic to overflow to infinity. The standalone BM25 query can return that non-finite score; fusion later rejects it, but direct retrieval callers and intermediate state have already crossed the finite-score contract.

**Fix:** Apply a service-safe upper bound to field boosts and check the accumulated score for finiteness before returning each candidate, converting overflow into a typed retrieval error rather than returning an invalid score.

### WR-11: [WARNING] Effective settings retain mutable duplicate grounding budgets

**Severity:** WARNING  
**File:** `engine/src/main.rs:299-315, 326-346`

**Issue:** `EffectiveRagSettings` stores public `evidence_token_budget` and `max_output_tokens` fields alongside the private `Arc<GroundingLimits>` carrier. The constructor initializes both copies, but callers can mutate or read the public scalars independently of the carrier used by prompt packing, the provider, and validation. This undermines the plan's single-authority settings contract and creates stale-budget behavior for library consumers.

**Fix:** Remove the duplicate public fields or replace them with read-only accessors that delegate to `grounding_limits`; make all consumers use that carrier as the sole source of truth.

### WR-12: [WARNING] Empty multipart uploads become ambiguous gateway failures

**Severity:** WARNING  
**File:** `gateway/main.go:212-249`; `engine/src/main.rs:1004-1030`

**Issue:** `grpcEngine.Ingest` sends the first frame only when `Read` returns bytes. An empty upload therefore sends no metadata frame, and the Rust stream rejects it as `empty ingestion stream`. The gateway marks the close error ambiguous and can return a reconciliation/502 failure instead of a deterministic client-facing validation response.

**Fix:** Reject zero-byte multipart files with HTTP 400 before opening the engine stream, or send a zero-byte first frame containing the document ID, filename, and chunk metadata and explicitly support empty documents in the Rust ingestion contract.

---

_Reviewed: 2026-08-05T20:26:26Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: standard_
