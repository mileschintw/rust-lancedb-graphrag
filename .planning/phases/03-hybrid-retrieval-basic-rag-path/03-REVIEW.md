---
phase: 03-hybrid-retrieval-basic-rag-path
reviewed: 2026-08-04T12:46:05Z
depth: standard
files_reviewed: 29
files_reviewed_list:
  - config/config.example.toml
  - config/config.toml
  - engine/Cargo.lock
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
  critical: 7
  warning: 11
  info: 0
  total: 18
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-08-04T12:46:05Z
**Depth:** standard
**Files Reviewed:** 29  
**Status:** issues_found

## Summary

The review covered all 29 explicitly scoped source, configuration, generated-binding, lock, and test files. The gateway-to-engine query path, ingestion staging/replay path, provider response handling, retrieval fusion, grounding validation, and resource-bound behavior were traced across modules.

Seven blocker-level issues remain, including silent embedding and dense-retrieval failure, an incorrect HTTP status for valid zero-result queries, provider response limits that are enforced only after unbounded buffering, destructive replacement of replay data, unconstrained configured resource limits, and non-finite fused scores that can produce malformed successful HTTP responses. Eleven warnings cover configuration security, lifecycle consistency, disclosure enforcement, idempotency, module duplication, and validation gaps.

The scoped mutable-row integration tests use per-test UUID-backed schemas and fatal external snapshot query failures; no violation of the repository review convention was found. Tests were not executed as part of this read-only review.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01 [BLOCKER]: Embedding failures are replaced with a plausible constant vector

**File:** engine/src/main.rs:967-974

**Issue:** Any embedding-provider error, empty result, wrong dimension, or multi-vector response falls through to vec![0.25; 2048]. The dense retriever therefore runs on a fabricated but valid-looking embedding and can return unrelated evidence, after which the generation path may present the answer as retrieval-grounded. The branch also does not verify that every value is finite or that exactly one vector was returned.

**Fix:**

```rust
let vectors = self
    .embedder
    .get_embeddings(&[query_request.query.clone()])
    .await
    .map_err(|err| Status::unavailable(format!("embedding unavailable: {err}")))?;

let [embedding] = vectors.as_slice() else {
    return Err(Status::internal("embedding provider returned the wrong vector count"));
};
if embedding.len() != 2048 || embedding.iter().any(|value| !value.is_finite()) {
    return Err(Status::internal("embedding provider returned an invalid vector"));
}
let query_embedding = embedding.clone();
```

### CR-02 [BLOCKER]: Dense retrieval errors are silently converted to an empty branch

**File:** engine/src/main.rs:976-984

**Issue:** unwrap_or_default() erases every DenseRetriever error, including snapshot, filter, and LanceDB query failures. BM25 and generation then continue as if the hybrid query succeeded, so a backend failure is indistinguishable from a successful zero-result dense search and can silently weaken grounding.

**Fix:** Propagate the retrieval error through the typed gRPC error mapping. Treat Ok(empty) as a legitimate zero-result branch only after the query itself succeeds. If degraded retrieval is ever supported, return an explicit degraded basis and disclosure rather than silently continuing.

### CR-03 [BLOCKER]: Valid zero-result queries are reported as malformed HTTP 400 requests

**File:** engine/src/main.rs:1006-1019; engine/src/prompt.rs:202-204; gateway/main.go:705-710

**Issue:** A syntactically valid query whose filters match no rows produces an empty final candidate list. Prompt assembly returns EmptyEvidence, the engine maps that to Status::invalid_argument, and the gateway maps InvalidArgument to HTTP 400. The phase contract requires valid filters with no matches to produce empty evidence rather than a caller-validation error, so clients cannot distinguish “no results” from malformed input.

**Fix:** Add an explicit no-results/no-answer outcome before prompt assembly, or introduce a dedicated typed status/result that is not mapped to HTTP 400. Reserve InvalidArgument for malformed query and filter input.

### CR-04 [BLOCKER]: Provider response-size limits are enforced after unbounded buffering

**File:** engine/src/generation/openrouter.rs:223-250, 407-423; engine/src/client/mod.rs:232-237

**Issue:** Model-capability responses and embedding responses are deserialized with response.json(), which buffers the complete remote body without a size limit. Chat responses call response.bytes() and check the length only after the full body has been read and allocated. A compromised or misconfigured provider can therefore force memory allocation far beyond the intended 256 KiB bound before the request is rejected.

**Fix:** Apply the same bounded reader to every provider response, including model metadata and embeddings. Reject a Content-Length above the limit before reading, and for chunked responses stop reading and fail as soon as the accumulator would exceed the limit, then deserialize only the bounded buffer.

### CR-05 [BLOCKER]: Raw ingestion data is deleted before replacement is durable

**File:** engine/src/main.rs:751-776

**Issue:** persist_raw deletes the existing staged_documents_v2 row before reading the schema, constructing the new RecordBatch, or executing the add. Any failure after line 753 permanently removes the old replayable payload, making the document unrecoverable and preventing startup replay.

**Fix:** Write the new staged record first and delete the previous version only after the add succeeds, using the database's transactional/atomic replacement primitive if available. Preserve the old row when schema construction or insertion fails.

### CR-06 [BLOCKER]: Configurable retrieval and generation limits have no service-safe upper bounds

**File:** engine/src/main.rs:238-250, 335-370; engine/src/retrieval/mod.rs:250-280; engine/src/generation/openrouter.rs:114-125

**Issue:** Validation permits candidate, final, query, filter, evidence, and output limits up to broad integer/usize ranges, and permits arbitrarily large finite retrieval weights. The effective values feed candidate collection, evidence packing, provider requests, and response validation. A deployment can therefore configure values that create unbounded-in-practice allocations or oversized provider requests/responses, defeating the service's grounding and resource-bound guarantees. Nonzero and i32-fit checks are not operational ceilings.

**Fix:** Define explicit service maximums for every count, byte, token, and evidence setting and enforce them at startup and at the request boundary. Keep provider body limits independent of operator-configured output limits, and reject configurations above the safe ceilings with a clear startup error.

### CR-07 [BLOCKER]: Accepted RRF weights can overflow fused scores and yield malformed HTTP 200 responses

**File:** engine/src/retrieval/mod.rs:267-280; engine/src/retrieval/fusion.rs:123-134; engine/src/main.rs:1095-1107; gateway/main.go:723-726

**Issue:** Retrieval settings accept any finite non-negative vector_weight and bm25_weight. With values near f64::MAX, contributions for a chunk present in both branches can be finite individually but their accumulator addition becomes +Inf. That non-finite score is copied into the protobuf citation and reaches the gateway, where encoding/json rejects it. writeJSON has already committed status 200 and ignores the encode error, producing an empty or malformed successful response.

**Fix:**

```rust
let contribution = weight / (rrf_k + rank as f64);
let score = entry.fused_score + contribution;
if !contribution.is_finite() || !score.is_finite() {
    return Err(RetrievalError::new(
        RetrievalErrorKind::Snapshot,
        "non-finite fused score",
    ));
}
entry.fused_score = score;
```

Also cap configured weights and validate every score before response conversion. Marshal the Go response into a buffer before WriteHeader so JSON encoding failures can return an error status instead of a committed 200.

## Warnings

### WR-01 [WARNING]: Evidence-budget failure is misclassified as caller InvalidArgument

**File:** engine/src/main.rs:1011-1019; engine/src/prompt.rs:132-153, 246-250

**Issue:** A valid query with evidence that cannot fit within the configured budget returns InvalidArgument and is exposed as HTTP 400. This conflates a server/configuration resource failure with malformed client input and gives clients no stable way to diagnose the condition.

**Fix:** Map NoEvidenceFits to a distinct FailedPrecondition or ResourceExhausted status, include the effective budget in structured metadata, and keep InvalidArgument for invalid query data.

### WR-02 [WARNING]: Usage validation is hardcoded to defaults instead of effective limits

**File:** engine/src/generation/mod.rs:157-181; engine/src/generation/openrouter.rs:468-492

**Issue:** Generation response validation compares prompt and completion usage against DEFAULT_EVIDENCE_TOKEN_BUDGET, DEFAULT_MAX_OUTPUT_TOKENS, and a default total budget. The runtime request uses effective configured settings, so custom values above the defaults can reject valid provider responses, while values below the defaults are not enforced consistently during response validation.

**Fix:** Pass one effective GroundingLimits/output-limits value into response validation and the OpenRouter adapter. Remove duplicate default constants from the validation path.

### WR-03 [WARNING]: BM25 remains stale after queued ingestion is marked completed

**File:** engine/src/main.rs:1568-1607, 1686-1695, 1748-1751, 1775-1782

**Issue:** The BM25 snapshot is built once at startup. The ingestion worker persists replacement vector nodes and marks the document completed, but no code rebuilds or republishes the BM25 snapshot. Replayed staged documents can therefore be visible to dense retrieval while remaining absent from lexical retrieval even though their status is completed.

The phase context lists dynamic BM25 refresh/restart recovery as deferred, so this is recorded as a warning rather than a blocker; the current completion state nevertheless exposes a cross-index consistency gap.

**Fix:** Rebuild and atomically publish the BM25 snapshot before reporting completion, or make the status explicitly indicate lexical index lag and persist the refresh debt for the next lifecycle boundary.

### WR-04 [WARNING]: Mixed-answer conflict disclosure is not machine-enforced

**File:** engine/src/generation/mod.rs:79-231; engine/src/generation/tests.rs:702-713

**Issue:** The validator checks citation identity and answer markers but does not require a disclosure notice when AnswerBasis::Mixed is used. The test suite accepts a Mixed response with citations and empty notices/warnings. The system prompt is not a reliable enforcement boundary, while the phase contract requires corpus conflict disclosure and separation of external knowledge.

**Fix:** Require a stable disclosure code or notice for Mixed responses in the validator, and test that omission is rejected. Keep citation requirements for the corpus-backed portion.

### WR-05 [WARNING]: Duplicate rows from one source inflate RRF scores

**File:** engine/src/retrieval/fusion.rs:103-154; engine/src/bin/seed_rag_fixture.rs:82-91, 157, 185

**Issue:** add_candidate adds the contribution before checking whether the same chunk already has a rank for that source. Duplicate vector or BM25 rows therefore contribute multiple ranks while only the first source rank is retained. The fixture uses fixed IDs and add operations, so repeated seeding can make duplicate rows reachable.

**Fix:** Deduplicate each source result by chunk_id before assigning ranks, or ignore a candidate from a source once that source rank is already recorded.

### WR-06 [WARNING]: Checked-in defaults contain a known plaintext database credential and disable TLS

**File:** config/config.toml:1-4; config/config.example.toml:5-8

**Issue:** The default connection string uses postgres:postgres and sslmode=disable. The gateway loads the configuration by default, so deployments that copy it without overriding the value receive a known credential and plaintext database transport.

**Fix:** Require a secret/environment-provided database URL, use TLS verification outside an explicitly local-development mode, and make the checked-in config a non-secret template rather than an operational credential.

### WR-07 [WARNING]: Gateway-to-engine gRPC transport is always unauthenticated and unencrypted

**File:** gateway/main.go:760

**Issue:** EngineAddr is configurable, but the gateway always creates the client with insecure.NewCredentials(). If the engine is placed on another host or a shared network, query text, answers, citations, and error metadata can be observed or modified without authentication.

**Fix:** Add TLS/mTLS configuration and fail closed for non-loopback addresses when insecure transport is selected. Keep insecure transport as an explicit local-development option only.

### WR-08 [WARNING]: The RAG fixture seeder is not idempotent

**File:** engine/src/bin/seed_rag_fixture.rs:82-91, 157, 185

**Issue:** Every run adds the same document, node, and edge IDs/content rather than upserting or resetting the fixture path. Re-running the command can create duplicates or fail partway through, which changes retrieval ranks and makes smoke-test results dependent on prior runs.

**Fix:** Use a fresh isolated fixture directory per run, or delete/upsert the known fixture IDs and verify the resulting row counts before reporting success.

### WR-09 [WARNING]: The binary and library compile separate production module graphs

**File:** engine/src/lib.rs:3-7; engine/src/main.rs:25-30

**Issue:** The library exports generation, prompt, rerank, and retrieval modules, while the binary redeclares private copies of those modules. Production wiring uses the binary copies, so library consumers and tests can validate different trait/type instances and behavior from the actual service binary.

**Fix:** Define shared modules once in the library and import them from main, or move the service implementation into the library and keep main as a thin entry point. Ensure integration tests exercise that shared graph.

### WR-10 [WARNING]: Empty multipart uploads are admitted by HTTP but dropped before the first gRPC frame

**File:** gateway/main.go:211-252, 482-497; engine/src/main.rs:827-865

**Issue:** The gateway accepts a zero-byte multipart file but sends no streaming frame because it only sends when n > 0. The engine rejects an empty ingestion stream, so the request can be inserted into the gateway database and then fail ambiguously during CloseAndRecv, producing a compensation/502 path instead of a deterministic validation response.

**Fix:** Reject zero-byte files with HTTP 400 before inserting the document, or send a metadata-bearing empty frame and define/document empty-document chunking semantics end to end.

### WR-11 [WARNING]: BM25 query does not normalize and validate the request at its public boundary

**File:** engine/src/retrieval/bm25.rs:233-263; engine/src/retrieval/dense.rs:48-55

**Issue:** Bm25Index::query validates settings but never calls QueryRequest::validate(settings). DenseRetriever does normalize the request, so the two public retrieval paths enforce different query/filter bounds when called directly with a constructed request or with settings different from the caller's normalization context.

**Fix:** Validate and retain the normalized request at the start of BM25 query, matching DenseRetriever, and use that normalized value for filter matching and all limits.

---

_Reviewed: 2026-08-04T12:46:05Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
