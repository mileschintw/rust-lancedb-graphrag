---
phase: 03-hybrid-retrieval-basic-rag-path
reviewed: 2026-08-04T08:15:37Z
depth: deep
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
  - gateway/main_test.go
  - gateway/main.go
  - gateway/proto/lancet/v1/lancet_grpc.pb.go
  - gateway/proto/lancet/v1/lancet.pb.go
  - proto/lancet/v1/lancet.proto
findings:
  critical: 9
  warning: 6
  info: 0
  total: 15
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-08-04T08:15:37Z  
**Depth:** deep  
**Files Reviewed:** 29  
**Status:** issues_found

## Summary

The current checkout was reviewed across the gateway-to-engine query path, ingestion and replay lifecycle, dense/BM25 retrieval, fusion, reranking, prompt assembly, provider generation, protobuf boundaries, configuration, and tests. The implementation has the nominal RAG-02/RAG-04 components, but several failure paths silently fabricate or weaken retrieval results, and the lexical index is not kept current after ingestion. The resulting path can return apparently grounded answers from invalid or incomplete evidence, while valid no-match queries are reported as client errors.

Validation performed: go test ./... passed. The serial Rust engine binary suite passed (71 passed, 1 ignored), but the full parallel Rust run exposed the test-order/random-fixture defect reported as WR-05.

## Critical Issues

### CR-01 [BLOCKER]: Embedding failures are converted into a plausible constant query vector

**File:** engine/src/main.rs:967-974

**Issue:** Any embedding error, empty response, or wrong-dimensional response is replaced with vec![0.25; 2048]. A provider outage or malformed provider response therefore continues into dense retrieval using an unrelated vector, and the generator can present arbitrary retrieved chunks as a valid hybrid answer.

**Fix:**

~~~rust
let query_embedding = self
    .embedder
    .get_embeddings(std::slice::from_ref(&request.question))
    .await
    .map_err(|err| Status::unavailable(format!("query embedding failed: {err}")))?
    .into_iter()
    .next()
    .filter(|embedding| {
        embedding.len() == 2048 && embedding.iter().all(|value| value.is_finite())
    })
    .ok_or_else(|| Status::internal("embedding provider returned an invalid vector"))?;
~~~

Only use a deliberately configured degraded mode if it is disclosed and cannot be mistaken for retrieval-backed output.

### CR-02 [BLOCKER]: Dense retrieval errors are silently treated as an empty dense branch

**File:** engine/src/main.rs:976-984

**Issue:** DenseRetriever::query errors, including snapshot, filter, and LanceDB failures, are converted with unwrap_or_default(). BM25 can then supply candidates and the service still executes generation as if the hybrid retrieval succeeded. This violates RAG-02’s requirement that the dense and lexical branches both form the retrieval chain and hides infrastructure failures as valid answers.

**Fix:** Propagate the dense error as a typed Unavailable/Internal gRPC error (and log its correlation identity). Return an empty branch only when the retriever successfully returns zero matches.

### CR-03 [BLOCKER]: The BM25 snapshot never includes documents ingested after startup

**File:** engine/src/main.rs:1710-1713, 1530-1568, 1641-1658

**Issue:** Bm25Index is built once before the worker starts. The worker writes canonical documents/nodes/edges and marks jobs completed, but no code updates or republishes the BM25 index afterward. Newly completed documents can therefore be found by the dense branch but are absent from BM25, so the advertised hybrid RAG-02 path is stale immediately after ingestion. Startup replay has the same ordering issue: the index is built before replayed jobs complete.

**Fix:** Make completion transactional with retrieval readiness: build the lexical representation for the new/replaced document, atomically publish a new BM25 snapshot (or an equivalent synchronized update), and mark the document completed only after both dense and BM25 views contain it. Apply the same ordering to replay, replacement, and deletion.

### CR-04 [BLOCKER]: Grounding validation permits retrieval-backed answers with no citations

**File:** engine/src/generation/mod.rs:70-126

**Issue:** validate_grounding checks that supplied citation IDs are known and that inline markers match the supplied set, but it does not require a non-empty citation set for Retrieval or Mixed answers. It also accepts ModelOnly output without requiring the contract’s explicit model-only disclosure. engine/src/main.rs:1036-1044 relies on this validator before returning the answer, so a model can label an uncited answer retrieval-backed and pass the gate.

**Fix:** Enforce basis-specific invariants: Retrieval and Mixed must cite at least one selected evidence ID and use the exact inline marker set; ModelOnly must carry the required explicit disclosure and must not be returned on a retrieval path unless that mode is intentionally selected. Reject any output that violates those rules.

### CR-05 [BLOCKER]: Provider output and notice fields have no enforced size bounds

**File:** engine/src/generation/mod.rs:54-68; engine/src/generation/openrouter.rs:377-427; engine/src/main.rs:1078-1090

**Issue:** The closed JSON schema declares unbounded answer, citation arrays, notices, warnings, and usage fields. The OpenRouter adapter deserializes response.json::<OpenRouterChatResponse>() without a response-body cap, and the service forwards notices/warnings into the protobuf without a local limit. A provider or intermediary can therefore cause unbounded parsing/allocation and oversized downstream responses; max_completion_tokens is only a provider request parameter, not a validation boundary.

**Fix:** Read provider responses through a bounded body/byte limit before deserialization, reject over-limit payloads, and validate answer length, citation count, citation ID length, notice/warning count and size, and usage values against explicit constants/configuration before constructing the gRPC response.

### CR-06 [BLOCKER]: Provider failure correlation/session identity is discarded at the API boundary

**File:** engine/src/generation/mod.rs:187-214; engine/src/main.rs:1021-1034; gateway/main.go:261-263, 667-674

**Issue:** GenerationError carries session and correlation identity, and the OpenRouter path attaches it, but the query handler creates a request with no correlation_id, maps the error to a plain tonic status containing only err.message(), and the gateway reduces every non-InvalidArgument error to a generic 502. Clients and operators cannot correlate provider failures with the request, contrary to the structured provider-error contract.

**Fix:** Generate/propagate a request correlation ID through the gateway metadata and GenerationRequest, preserve it in gRPC status details or a typed protobuf error, and return a stable HTTP error shape containing the same identity without exposing provider secrets.

### CR-07 [BLOCKER]: Missing OpenRouter credentials are replaced with a fake production key

**File:** engine/src/main.rs:1715-1720

**Issue:** OPENROUTER_API_KEY is read with a fake-key fallback even though both the client and adapter constructors otherwise reject a missing/blank key (engine/src/client/mod.rs:119-134 and engine/src/generation/openrouter.rs:179-200). A misconfigured deployment starts successfully and only fails later during requests, producing misleading readiness and opaque provider failures instead of failing closed.

**Fix:**

~~~rust
let api_key = std::env::var("OPENROUTER_API_KEY")
    .map_err(|_| anyhow::anyhow!("OPENROUTER_API_KEY is required"))?;
if api_key.trim().is_empty() {
    return Err(anyhow::anyhow!("OPENROUTER_API_KEY must not be blank"));
}
~~~

Keep test credentials confined to test-only setup.

### CR-08 [BLOCKER]: Valid zero-match filters are returned as HTTP 400

**File:** engine/src/main.rs:1006-1019; engine/src/prompt.rs:195-203; gateway/main.go:667-674

**Issue:** A syntactically valid filter that matches no rows produces no fused evidence. Prompt assembly then returns EmptyEvidence, and the query handler maps that condition to Status::invalid_argument; the gateway exposes it as HTTP 400. The phase contract explicitly distinguishes valid no-match filters from malformed input and requires an empty evidence result rather than a validation error.

**Fix:** Handle a successful zero-result retrieval before prompt assembly and return the contract’s successful zero-evidence/no-results response (without invoking a retrieval-backed generator), or use a distinct typed no-results status that the gateway does not map to 400. Reserve InvalidArgument for malformed questions, IDs, and filters.

### CR-09 [BLOCKER]: Staging data is deleted before the replacement payload is durably written

**File:** engine/src/main.rs:751-776

**Issue:** persist_raw deletes the existing staged row before adding the new schema/raw payload. If schema creation or the subsequent add fails, the old replayable payload is already gone. A transient storage failure during replacement can therefore lose the document and its recovery data.

**Fix:** Write the new staged/versioned payload first, verify it is durable, then remove the superseded row in the same transaction or use an atomic upsert. Preserve the old staging record until canonical persistence and queue publication have both succeeded.

## Warnings

### WR-01 [WARNING]: OpenRouter repacks evidence with hardcoded budgets

**File:** engine/src/generation/openrouter.rs:287-293; engine/src/main.rs:299-309, 1011-1019

**Issue:** The service assembles evidence using the effective configured evidence/output limits, but the adapter calls pack_evidence_prompt again with hardcoded 8192 and 2048. Runtime settings are therefore not authoritative at the provider boundary: a smaller configured budget can be expanded, and a configured output limit is not carried through consistently.

**Fix:** Pass the effective limits in GenerationRequest or preassemble the prompt once, and use those values in the adapter. Validate that the provider request and response stay within the same limits.

### WR-02 [WARNING]: “No evidence fits” is classified as invalid client input

**File:** engine/src/main.rs:1011-1019; engine/src/prompt.rs:132-153, 246-250

**Issue:** NoEvidenceFits can result from the configured evidence budget and corpus excerpts, but the query handler maps every prompt assembly error to InvalidArgument. A valid query can thus become HTTP 400 because of an operator/corpus budget choice rather than malformed caller input.

**Fix:** Use separate error variants for caller validation and evidence/resource exhaustion. Map the latter to a server-side/configuration error and expose a stable diagnostic/correlation ID.

### WR-03 [WARNING]: Checked-in runtime configuration embeds default database credentials and disables TLS

**File:** config/config.toml:1-4; gateway/main.go:53-70

**Issue:** The gateway loads config/config.toml by default, and the tracked file contains postgres://postgres:postgres@localhost:5432/lancet?sslmode=disable. These defaults are convenient for local development but are unsafe if the file is copied into a non-local deployment or treated as an operational configuration.

**Fix:** Keep credentials and transport security in environment/secret-managed configuration, make TLS the non-development default, and leave only clearly local placeholders in the example file.

### WR-04 [WARNING]: The RAG fixture seeder is not idempotent

**File:** engine/src/bin/seed_rag_fixture.rs:82-91, 157, 185

**Issue:** Each run inserts the same fixed document, nodes, and edges without deleting/upserting the existing IDs or asserting the expected final counts. Re-running the seeder can duplicate fixture rows or fail in a partially populated database, making cross-runtime RAG checks depend on prior state.

**Fix:** Seed into a fresh isolated database/path, or perform an idempotent delete/upsert for the fixture IDs and verify final document/node/edge counts.

### WR-05 [WARNING]: Citation truncation test depends on nondeterministic candidate ranking

**File:** engine/src/tests.rs:2750-2851

**Issue:** The test fixes the fake model citation to [2] and asserts that citation rank 2 is truncated, but the fixture uses runtime-generated IDs and the retrieval order can put a short heading chunk at that position. The full parallel Rust run failed at assert!(sc.is_truncated), while the serial binary suite passed. This is a test-reliability defect and can conceal real citation regressions.

**Fix:** Construct deterministic fixture IDs/content and select the cited evidence by a stable predicate, or assert truncation on a deliberately oversized cited chunk rather than on a positional rank.

### WR-06 [WARNING]: Production and library code maintain duplicate retrieval/generation module graphs

**File:** engine/src/lib.rs:1-7; engine/src/main.rs:25-30, 1000-1004, 1762-1766

**Issue:** The library exports generation, prompt, rerank, and retrieval, while the binary declares private copies of those modules. The production service therefore uses a different Reranker trait/type graph from library consumers and tests; the public NoOpReranker contract is not necessarily the one wired into the running binary. This permits tests and external callers to validate code paths that production does not use.

**Fix:** Consolidate shared modules in the library and import them from the binary, or move the service implementation into the library. Ensure the integration tests exercise the same exported types and actual production wiring.

---

_Reviewed: 2026-08-04T08:15:37Z_  
_Reviewer: the agent (gsd-code-reviewer)_  
_Depth: deep_
