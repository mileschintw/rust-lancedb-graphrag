---
phase: 03-hybrid-retrieval-basic-rag-path
reviewed: 2026-08-05T06:19:41Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - config/config.example.toml
  - config/config.toml
  - engine/Cargo.toml
  - engine/src/bin/seed_rag_fixture.rs
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
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
  critical: 4
  warning: 14
  info: 0
  total: 18
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-08-05T06:19:41Z
**Depth:** standard
**Files Reviewed:** 27
**Status:** issues_found

## Summary

The complete source/configuration/protobuf scope extracted from all 18 Phase 03 SUMMARY files was reviewed against the live checkout, including plans 03-16 through 03-18. `cargo test --locked` and `go test ./...` pass, but the implementation still has four blocker-level issues and fourteen warnings involving provider response limits, replay data integrity, retrieval bounds, API contracts, transport/configuration security, and duplicated Rust module ownership.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: [BLOCKER] Provider response limits are checked after unbounded buffering

**File:** `engine/src/generation/openrouter.rs:279-287, 438-456`; `engine/src/client/mod.rs:232-237`
**Issue:** Model metadata and embedding responses are passed directly to `response.json`, and chat responses are fully materialized by `response.bytes()` before the 256 KiB check. A provider or intermediary can therefore return an arbitrarily large successful body and force allocation/deserialization before the code rejects it, allowing memory exhaustion in the Engine process.
**Fix:** Enforce `Content-Length` when present and read every provider response through a bounded streaming reader (for example, `MAX_RESPONSE_BODY_BYTES + 1`), aborting as soon as the limit is exceeded, before JSON deserialization.

### CR-02: [BLOCKER] Raw replay data is deleted before the replacement write is durable

**File:** `engine/src/main.rs:786-811`
**Issue:** `persist_raw` deletes the existing staged row at line 788, then performs schema lookup, `RecordBatch` construction, and the new `add` at lines 789-811. Any failure after the delete leaves neither the previous replay payload nor the replacement row, so a retry or restart cannot recover the document.
**Fix:** Use an atomic/versioned replacement: write and verify the new row first, then remove the old generation only after the durable write succeeds, or perform both operations under a transactional manifest with rollback.

### CR-03: [BLOCKER] Non-finite fused scores can produce a successful HTTP response with invalid JSON

**File:** `engine/src/retrieval/fusion.rs:123-134`; `gateway/main.go:845-849`
**Issue:** RRF contribution and accumulator arithmetic are not checked for finiteness. Finite but unbounded configured weights, combined with enough duplicate candidate contributions, can overflow `fused_score` to `Inf`. The gateway commits the HTTP status before encoding and ignores the encoder error; Go JSON encoding then rejects the non-finite float after a 200 response has already been sent, yielding an empty or malformed successful response.
**Fix:** Bound the accepted RRF weights, reject non-finite contributions/accumulators before constructing the response, and encode into a buffer before calling `WriteHeader`; return a controlled 500 if encoding fails.

### CR-04: [BLOCKER] Retrieval limits have no service-safe ceiling

**File:** `engine/src/retrieval/mod.rs:236-265`; `engine/src/retrieval/dense.rs:70-101`; `config/config.example.toml:14-24`
**Issue:** Validation only limits values to `i32::MAX`. The configured candidate limit is then passed to LanceDB and collected into memory, while BM25 and fusion also build result vectors. A misconfigured service can therefore accept effectively unbounded retrieval work and become unavailable instead of rejecting the configuration at startup. This is an availability/resource-exhaustion risk, not merely an optimization concern.
**Fix:** Add explicit service ceilings for candidate/final limits, query bytes, and filter cardinalities; validate them in the effective startup settings and request path, and keep the documented configuration within those ceilings.

## Warnings

### WR-01: [WARNING] Duplicate candidates from one source inflate RRF scores

**File:** `engine/src/retrieval/fusion.rs:123-154`
**Issue:** The contribution is added before the source rank is checked. Repeated rows for the same chunk from the same source add multiple RRF contributions, while only the first source rank/score is retained. The fused score consequently depends on duplicate row count rather than rank.
**Fix:** Deduplicate each source/chunk before calculating the contribution, or skip a source contribution when its rank is already populated.

### WR-02: [WARNING] The fixture seeder is not idempotent

**File:** `engine/src/bin/seed_rag_fixture.rs:82-91, 157, 169-185`
**Issue:** Re-running the fixture seeder appends documents, nodes, and edges with stable IDs using `add` and performs no cleanup, upsert, or existing-fixture check. Repeated cross-runtime smoke setup therefore creates duplicate corpus rows and feeds the fusion defect above.
**Fix:** Make seeding an explicit replace/upsert operation in a transaction, or refuse to seed a non-empty fixture path unless the caller explicitly requests a reset.

### WR-03: [WARNING] Mixed answer basis is not required to disclose the conflict

**File:** `engine/src/prompt.rs:208-212`; `engine/src/generation/mod.rs:149-175`; `engine/src/generation/tests.rs:701-713`
**Issue:** The prompt tells the model to disclose conflicts for a `Mixed` answer, but grounding validation checks only that the answer has citations and never requires a notice or warning. The test explicitly accepts `Mixed` with both `notices` and `warnings` empty, so a response can claim mixed grounding without explaining the conflict.
**Fix:** Require a nonblank conflict disclosure in `notices` or `warnings` whenever `answer_basis == Mixed`, and add a rejection test for the empty-disclosure case.

### WR-04: [WARNING] Prompt packing failures are misclassified as caller-invalid requests

**File:** `engine/src/main.rs:1130-1136`; `gateway/main.go:705-706`
**Issue:** A valid query whose evidence cannot fit the configured prompt budget is mapped to gRPC `InvalidArgument`, which the gateway exposes as HTTP 400. This blames the caller for a service/model capacity condition and prevents clients from distinguishing malformed input from a retryable or operator-tunable limit.
**Fix:** Map `NoEvidenceFits` to an appropriate capacity status such as `ResourceExhausted` (and reserve `InvalidArgument` for malformed query input), with a corresponding gateway mapping and test.

### WR-05: [WARNING] BM25 bypasses the shared request-boundary validation

**File:** `engine/src/retrieval/bm25.rs:233-263`; compare `engine/src/retrieval/dense.rs:48-55`
**Issue:** `Bm25Index::query` validates settings but never calls `QueryRequest::validate(settings)`. Direct callers can therefore bypass query-byte and filter-cardinality limits on the BM25 path even though the dense path enforces them.
**Fix:** Validate and use the normalized request at the start of `Bm25Index::query`, matching the dense retriever’s boundary contract.

### WR-06: [WARNING] Committed database configuration contains a password and disables TLS

**File:** `config/config.toml:1-4`; `config/config.example.toml:5-8`
**Issue:** Both the live config and copyable example commit `postgres://postgres:postgres@...sslmode=disable`. Even if intended for local development, this normalizes plaintext credentials and unencrypted database connections and can be copied into a non-local deployment.
**Fix:** Read the complete URL from an environment/secret reference, use a placeholder without credentials in examples, and require TLS outside an explicitly local-development mode.

### WR-07: [WARNING] Gateway-to-Engine gRPC transport is always plaintext and unauthenticated

**File:** `gateway/main.go:882-885`
**Issue:** The gateway always uses `insecure.NewCredentials()` for the configured Engine address. If that address is remote or traffic leaves the host, query contents, ingestion data, and provider-related results are exposed and the peer is not authenticated.
**Fix:** Use configured TLS credentials and peer authentication for non-loopback addresses, or reject non-loopback Engine addresses when running in the local-only mode that permits insecure transport.

### WR-08: [WARNING] Empty multipart uploads send no ingestion frame

**File:** `gateway/main.go:211-245`; `engine/src/main.rs:862-899`
**Issue:** The gateway sends a frame only when `Read` returns bytes. A zero-length file sends zero frames, so Engine sees `document_id.is_empty()` and returns `InvalidArgument`; the HTTP layer then treats the stream error as an ambiguous upstream failure instead of deterministically accepting or rejecting the upload.
**Fix:** Either send a first metadata frame with an empty chunk for supported empty documents, or reject zero-length files with a clear HTTP 400 before opening the stream.

### WR-09: [WARNING] Rust production modules are declared in two separate module graphs

**File:** `engine/src/lib.rs:3-7`; `engine/src/main.rs:25-30`
**Issue:** The library exports `generation`, `prompt`, `rerank`, and `retrieval`, while the binary redeclares private copies. The binary therefore uses different type identities and implementations from the library-facing modules; current `cargo test` warnings show library functions such as `QueryRequest::validate` and retriever helpers are dead. Tests against the library can pass while the service executes the duplicate binary modules.
**Fix:** Keep shared modules in the library and import them from the binary with `use engine::...`; declare only binary-specific modules in `main.rs`, then remove duplicate declarations and test the actual service path.

### WR-10: [WARNING] Public grounding limits can bypass their constructor ceilings

**File:** `engine/src/generation/mod.rs:83-130`; `engine/src/generation/openrouter.rs:90-109, 120-157`
**Issue:** `GroundingLimits` exposes all fields publicly, so callers can construct values without `GroundingLimits::new`. `with_grounding_limits` stores those values and `OpenRouterGenerationConfig::validate` never validates them, allowing the public adapter API to bypass service token ceilings.
**Fix:** Make the fields private, expose read-only accessors, add a `validate` method, and call it from every configuration constructor and model-output validation path.

### WR-11: [WARNING] Ingestion accepts non-finite embedding components before persistence

**File:** `engine/src/client/mod.rs:232-253`; `engine/src/main.rs:1410-1419, 1528-1534`
**Issue:** The embedding client and replacement path validate count and dimension only. They do not reject `NaN` or infinities before building the LanceDB array, so a custom provider or alternate embedding implementation can persist invalid vectors that later violate the query path’s finite-vector invariant.
**Fix:** Require every embedding component to be finite at the provider boundary and again before `RecordBatch` construction; fail the ingestion before any replacement write when validation fails.

### WR-12: [WARNING] Corrupt staging nulls can panic replay instead of returning an error

**File:** `engine/src/main.rs:710-724`
**Issue:** Replay calls `.value(i)` on every required Arrow array without checking `is_null`. A corrupt or partially written staging row can therefore panic the replay task/process rather than produce a typed recovery error.
**Fix:** Check required columns for nulls before each access and return a contextual staging-corruption error that follows the normal replay failure policy.

### WR-13: [WARNING] Configured provider endpoints can exfiltrate bearer credentials

**File:** `engine/src/main.rs:350-364`; `engine/src/client/mod.rs:202-207`; `engine/src/generation/openrouter.rs:409-413`
**Issue:** Endpoint validation checks only that URLs are nonblank, while both clients attach the API key as bearer authentication. An accidental `http://` endpoint or an untrusted host receives the credential over an unencrypted or unauthorized connection.
**Fix:** Parse and validate endpoint URLs, require HTTPS by default, allow loopback HTTP only under an explicit local-development flag, and optionally enforce an approved host list for provider endpoints.

### WR-14: [WARNING] `IngestionJob::new` silently hides invalid chunk metadata

**File:** `engine/src/main.rs:544-558`
**Issue:** The public constructor converts any `parse_chunk_settings` error into `ChunkSettings::default()`. Callers receive no indication that requested strategy, size, or overlap was invalid, so the document can be ingested with silently different chunking semantics from the supplied metadata.
**Fix:** Return `Result<Self, String>` (or preserve a construction error) and use the same strict metadata validation for every construction path, including tests and replay.

---

_Reviewed: 2026-08-05T06:19:41Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
