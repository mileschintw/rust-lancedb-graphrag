---
phase: 03-hybrid-retrieval-basic-rag-path
reviewed: 2026-08-02T22:48:42Z
depth: standard
files_reviewed: 28
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
  critical: 13
  warning: 5
  info: 0
  total: 18
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-08-02T22:48:42Z
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

The Phase 03 implementation has a working exercised path, but it is not safe to ship in its current form. The review found 13 ship-blocking correctness or security defects and 5 robustness/maintainability warnings. The most consequential defects are fail-open retrieval, a prompt-boundary injection path through provenance metadata, permissive provider output validation, incorrect structured citations, ignored safety/provider configuration, and unbounded HTTP request bodies.

Automated checks passed: 82 Rust tests passed with 2 ignored, all Go packages passed, buf lint passed, and git diff --check passed. The Rust build emitted numerous dead-code/unused warnings. Passing tests do not exercise the adversarial cases below; in one case, the integration test explicitly locks in json_object rather than the required strict JSON Schema contract.

## Narrative Findings (AI reviewer)

### Critical Issues

#### CR-01: Untrusted provenance can forge prompt boundaries

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/prompt.rs:35-40, D:/Repos/lancet/engine/src/prompt.rs:84-93, D:/Repos/lancet/engine/src/prompt.rs:129-133
**Issue:** Title and section metadata are corpus-controlled, but they are interpolated verbatim into a quoted provenance attribute. A title containing a quote plus closing markup can terminate the attribute and inject SYSTEM or EVIDENCE blocks. Only chunk content is partially escaped, and that escape handles only exact uppercase/lowercase tag spellings. This defeats the prompt-boundary isolation that is supposed to treat the corpus as untrusted data.
**Fix:** Never concatenate corpus metadata into markup attributes. Serialize provenance into a structured object and XML-escape every metadata and content field, including ampersand, angle brackets, both quote characters, and mixed-case delimiter variants. Add tests using malicious title and section values, not only malicious content. For example:

    fn escape_xml(value: &str) -> String {
        value.replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
            .replace('\'', "&apos;")
    }

#### CR-02: The first evidence block bypasses the token budget

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/prompt.rs:121-144
**Issue:** The over-budget branch is conditional on packed_evidence already being non-empty. Consequently, the first evidence block is appended even when it exceeds the entire remaining budget, including when the available evidence budget is zero. A maximum-size ingested chunk can therefore overrun the provider context and make the valid RAG path fail unpredictably.
**Fix:** Check every block against the remaining budget, including the first, and fail closed before generation when no complete block fits:

    let remaining = allowed_evidence_tokens.saturating_sub(current_tokens);
    if block_tokens > remaining {
        break;
    }

Add boundary tests where the first block is one token over budget and where the answer/base reservation consumes the whole context.

#### CR-03: Unicode citation excerpts can panic the request task

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/prompt.rs:171-180
**Issue:** Excerpts use a byte length and then slice at byte 200. For valid UTF-8 where byte 200 falls inside a multibyte character, the slice panics. Corpus text is untrusted and Unicode is explicitly supported, so a document can reliably crash its QueryRAG request during citation assembly.
**Fix:** Truncate on character boundaries and return the truncation state. Thread the configured character limit into the resolver:

    let mut chars = block.text.chars();
    let excerpt: String = chars.by_ref().take(max_chars).collect();
    let is_truncated = chars.next().is_some();

Add tests with CJK and emoji strings whose 200th byte is not a character boundary.

#### CR-04: Structured citation metadata is assigned from the wrong candidate

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/main.rs:889-914
**Issue:** Resolved citations are enumerated in model-provided citation order, but score and rank are taken from final_candidates at the same enumeration index. If the model cites only [3], the response returns chunk/document data for evidence 3 with the score and rank of candidate 1. The title is also filled with the whole provenance string, section_path and content_type are erased, and is_truncated is always false even when the resolver appended an ellipsis. The result is internally contradictory and cannot serve as machine-verifiable provenance.
**Fix:** Resolve each citation back to its originating fused candidate by engine-issued evidence ID or chunk ID, and populate every protobuf field from that same candidate. Preserve the retrieval rank separately from citation display order and propagate the actual truncation flag:

    let source = by_chunk_id.get(&citation.chunk_id)
        .ok_or_else(|| schema_error("citation source disappeared"))?;
    // title, section_path, content_type, score, and retrieval rank all come from source.

Add a test that cites [3] without [1] or [2] and asserts every structured field.

#### CR-05: Provider output is neither schema-constrained nor semantically validated

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/generation/mod.rs:51-64, D:/Repos/lancet/engine/src/generation/openrouter.rs:171-195, D:/Repos/lancet/engine/src/generation/openrouter.rs:243-265, D:/Repos/lancet/engine/src/generation/openrouter.rs:323-337, D:/Repos/lancet/engine/src/generation/tests.rs:183-235, D:/Repos/lancet/gateway/main_test.go:1556-1570
**Issue:** The OpenRouter request asks only for json_object, ModelOutput accepts unknown fields, cited IDs that do not resolve are silently deleted, and ChatChoice does not even deserialize/check finish_reason. No post-generation invariant requires a non-empty answer, a retrieval-backed basis, a normal stop reason, at least one valid citation, agreement between inline markers and cited_evidence_ids, or a disclosure for mixed basis. The current unit test even supplies the invalid ID Format-1 and still expects success. A provider can therefore return a truncated, retrieval-labelled but uncited or unsupported answer and the engine will publish it as valid.
**Fix:** Send a strict JSON Schema with required fields and additionalProperties false, add serde deny_unknown_fields, and reject rather than retain-away any unsupported citation. Validate the complete output before constructing QueryRAGResponse:

    #[serde(deny_unknown_fields)]
    struct ModelOutput { /* required closed fields */ }

    if output.answer.trim().is_empty()
        || !all_citations_resolve(&output, &packed_evidence)
        || !inline_markers_match(&output)
    {
        return Err(GenerationError::schema_validation("invalid grounded output"));
    }

Model-only behavior should fail for this MVP; mixed basis must retain citations and a typed disclosure. Update both Rust and cross-runtime tests to assert a json_schema payload and rejection of unknown fields, invalid IDs, missing citations, and mismatched markers.

#### CR-06: Embedding and dense-retrieval failures silently degrade to fabricated retrieval

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/main.rs:832-859
**Issue:** Any embedding error or wrong-sized response is replaced with a fabricated constant vector, and every dense-query error is replaced with an empty candidate list. Generation then proceeds with arbitrary dense rankings or BM25-only evidence while the response still advertises the configured hybrid snapshot. Degraded retrieval is not implemented for this MVP, and provider/storage failures must not be presented as successful grounded retrieval.
**Fix:** Require exactly one finite embedding of the expected dimension and propagate both provider and dense-store errors as typed failures. Do not invoke fusion or generation after either path fails:

    let embeddings = self.embedder.get_embeddings(&[query.clone()])
        .await
        .map_err(|_| Status::unavailable("embedding provider unavailable"))?;
    let query_embedding = exactly_one_valid_embedding(embeddings)?;
    let dense_candidates = dense.query(...).await
        .map_err(|_| Status::unavailable("dense retrieval unavailable"))?;

Add tests proving zero provider calls to generation after embedding or dense failure.

#### CR-07: Configured evidence and excerpt safety bounds are ignored

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/main.rs:193-196, D:/Repos/lancet/engine/src/main.rs:630-635, D:/Repos/lancet/engine/src/main.rs:866-872, D:/Repos/lancet/engine/src/prompt.rs:175-180
**Issue:** evidence_token_budget and excerpt_max_chars are deserialized and documented in both committed configs, but neither value reaches LancetServiceImpl. QueryRAG uses fixed prompt constants, while citation resolution hard-codes 200 bytes. Operators cannot lower safety limits, and the response does not honor its declared character bound.
**Fix:** Validate the bounds at startup, store them in an immutable runtime configuration carried by the service, and pass them explicitly to evidence packing and citation resolution. Test non-default values at the service boundary, including zero/invalid startup values and exact character limits.

#### CR-08: OpenRouter generation and embedding settings are mostly inert

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/main.rs:235-268, D:/Repos/lancet/engine/src/main.rs:1213-1230, D:/Repos/lancet/engine/src/client/mod.rs:27-30, D:/Repos/lancet/engine/src/client/mod.rs:133-141, D:/Repos/lancet/engine/src/generation/openrouter.rs:20-28, D:/Repos/lancet/engine/src/generation/openrouter.rs:171-195, D:/Repos/lancet/engine/src/generation/openrouter.rs:278-284
**Issue:** The configuration exposes embedding_model, generation_timeout_secs, temperature, top_p, and max_output_tokens, but runtime requests use a compile-time embedding model, a fixed 30-second timeout, temperature 0, top_p 1, and 2048 output tokens. Ingested node metadata is also stamped with the compile-time model constant. Valid configuration is accepted while the engine silently executes and records different settings.
**Fix:** Introduce validated EmbeddingConfig and GenerationConfig values and pass them into the adapter constructors. Store the embedding model as a String, make EmbeddingRequest.model a borrowed string, configure the reqwest and outer timeout from the same validated duration, and source sampling/output parameters from the effective configuration. Add request-capture tests with deliberately non-default values.

#### CR-09: BM25 configuration is validated at query time but never applied to the index

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/main.rs:1513-1517, D:/Repos/lancet/engine/src/main.rs:1554-1561, D:/Repos/lancet/engine/src/retrieval/bm25.rs:233-263
**Issue:** Startup always builds the BM25 snapshot with Bm25Config::default(), while requests validate the separately configured BM25 values held in RetrievalSettings. A valid non-default configuration therefore changes no scores, while an invalid one lets the service become ready and only fails later on every request. This makes retrieval behavior differ from the accepted configuration.
**Fix:** Build and validate the effective retrieval settings before opening the serving socket, then construct the index with the exact same BM25 config:

    let retrieval_settings = settings.engine.retrieval.to_retrieval_settings();
    retrieval_settings.validate()?;
    let bm25_index = Bm25Index::from_table(
        &nodes,
        retrieval_settings.bm25.clone(),
    ).await?;

Add a startup/query test showing that non-default boosts change the ranking and invalid settings prevent readiness.

#### CR-10: Retrieval snapshots misreport effective configuration

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/main.rs:932-950, D:/Repos/lancet/proto/lancet/v1/lancet.proto:91-100
**Issue:** The snapshot hard-codes the default embedding model even when another model is configured, and casts full-precision f64 rrf_k to protobuf int32. A valid value such as 60.5 is used for fusion but reported as 60. These fields are intended to make retrieval reproducible, so the current response records false provenance.
**Fix:** Carry the effective embedding model into the service and response. Change RetrievalSnapshot.rrf_k to double (then regenerate Rust and Go bindings), or reject non-integer values at configuration load if the wire type must remain integral. Add a non-default configuration test that compares every snapshot field to the values actually used.

#### CR-11: A zero retrieval weight does not disable that source

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/retrieval/mod.rs:256-267, D:/Repos/lancet/engine/src/retrieval/fusion.rs:35-91, D:/Repos/lancet/engine/src/retrieval/fusion.rs:100-128
**Issue:** Settings intentionally allow one source weight to be zero, but fusion still inserts all candidates from that source with a zero contribution. If the enabled source returns fewer than final_limit candidates, zero-score candidates from the disabled source fill the response and become generation evidence. A weight of zero therefore does not actually disable a retriever.
**Fix:** Skip a source loop when its weight is zero, or filter accumulators that never receive a positive contribution before sorting/truncation:

    if settings.vector_weight > 0.0 {
        add_ranked(vector_candidates, Source::Vector, ...)?;
    }

Add symmetric tests for vector_weight = 0 and bm25_weight = 0 where the disabled source has otherwise unique candidates.

#### CR-12: The public RAG endpoint accepts an unbounded JSON body

**Classification:** BLOCKER
**File:** D:/Repos/lancet/gateway/main.go:629-640, D:/Repos/lancet/gateway/main.go:712-716
**Issue:** queryRAG decodes directly from r.Body without MaxBytesReader. The engine's 8 KiB query check runs only after Go has read and allocated the submitted JSON strings and filter arrays. The HTTP server also has no body ReadTimeout, so an unauthenticated client can send an arbitrarily large or indefinitely slow body and consume gateway memory/connections, creating a straightforward denial-of-service path.
**Fix:** Bound the body before decoding, close it, distinguish an over-limit body with HTTP 413, and configure a request-body deadline appropriate for the upload and query routes:

    r.Body = http.MaxBytesReader(w, r.Body, maxRAGQueryBodyBytes)
    defer r.Body.Close()

Choose the limit from the query/filter contract plus JSON overhead, and test a body one byte above the limit and a huge filter array.

#### CR-13: Non-finite embeddings can be persisted into the canonical vector index

**Classification:** BLOCKER
**File:** D:/Repos/lancet/engine/src/client/mod.rs:163-183, D:/Repos/lancet/engine/src/main.rs:1080-1096, D:/Repos/lancet/engine/src/main.rs:1158-1164
**Issue:** Provider responses and the persistence boundary validate only embedding count and dimension. They never reject NaN or infinity before building the Arrow array. Non-finite vectors can corrupt nearest-neighbor behavior and leave durable rows that the separate inspector later rejects, turning one malformed provider response into a data-integrity incident.
**Fix:** Reject non-finite values both in OpenRouterClient and immediately before any database mutation:

    if embeddings.iter().flatten().any(|value| !value.is_finite()) {
        return Err("embeddings must contain only finite values".into());
    }

Add provider-response and replacement-boundary tests for NaN, positive infinity, and negative infinity, plus a finite control.

### Warnings

#### WR-01: BM25 retrieval skips request normalization and validation

**Classification:** WARNING
**File:** D:/Repos/lancet/engine/src/retrieval/bm25.rs:233-246, D:/Repos/lancet/engine/src/retrieval/mod.rs:114-129, D:/Repos/lancet/engine/src/retrieval/mod.rs:337-339
**Issue:** Dense retrieval revalidates QueryRequest, but BM25 validates only settings. QueryRequest and its filter vectors are publicly mutable, while QueryFilters::matches assumes sorted vectors for binary_search. A manually constructed or subsequently mutated request can bypass query/filter bounds or silently fail to match valid rows.
**Fix:** Normalize a local request before analyzing or matching:

    let request = request.validate(settings)?;

Add a test using unsorted/mixed-case public filter vectors and an over-limit query.

#### WR-02: The reranker seam is not connected to QueryRAG

**Classification:** WARNING
**File:** D:/Repos/lancet/engine/src/rerank/mod.rs:10-34, D:/Repos/lancet/engine/src/main.rs:854-864, D:/Repos/lancet/engine/src/main.rs:630-635
**Issue:** NoOpReranker and its provider-neutral trait exist, but the service never stores or invokes a reranker; it takes fused candidates directly. Current no-op ordering is unchanged, but the advertised replacement seam is dead and a later reranker cannot be injected without rewriting the handler.
**Fix:** Add Arc<dyn Reranker> to LancetServiceImpl, invoke it after fusion and before final truncation/evidence assembly, wire NoOpReranker at startup, and assert the handler calls an injected recording reranker exactly once.

#### WR-03: Generation warnings are discarded and all notices lose severity

**Classification:** WARNING
**File:** D:/Repos/lancet/engine/src/generation/mod.rs:53-63, D:/Repos/lancet/engine/src/main.rs:922-930
**Issue:** ModelOutput defines separate notices and warnings, but the response assembler ignores warnings entirely and converts every notice to code NOTICE with INFO severity. A caller cannot observe a generation warning or distinguish a disclosure/error class even though the protobuf exposes typed notice severity.
**Fix:** Make provider-neutral notices typed (code, message, severity), or at minimum map warnings to NOTICE_SEVERITY_WARNING and notices to their declared types. Add tests for both arrays and preserve deterministic ordering.

#### WR-04: The BM25 startup-failure test never reaches BM25 construction

**Classification:** WARNING
**File:** D:/Repos/lancet/engine/tests/config_startup.rs:214-245, D:/Repos/lancet/engine/src/main.rs:1513-1517
**Issue:** initial_bm25_failure_blocks_readiness points lancedb_path at a corrupt ordinary file and asserts that database initialization fails. The test still passes if BM25 construction is removed or its errors are ignored, so it does not verify the failure boundary named by the test and gives a false readiness signal.
**Fix:** Arrange a database that initializes successfully but makes Bm25Index::from_table fail, or extract startup assembly behind an injectable BM25 builder and inject a deterministic failure. Assert the database-open stage succeeded and the serving log/socket was never reached.

#### WR-05: Retrieval and generation modules are compiled as duplicate library and binary modules

**Classification:** WARNING
**File:** D:/Repos/lancet/engine/src/main.rs:25-30
**Issue:** generation, prompt, rerank, and retrieval are already library modules, but main.rs declares fresh binary-local copies from the same files. This creates separate type universes, duplicates unit tests, and contributes substantial dead-code/unused warning noise that can hide real regressions. The standard test run emitted warnings for unused retrieval APIs, reranker types, imports, and constants.
**Fix:** Export the runtime modules through engine/src/lib.rs and import them from the engine crate in main.rs instead of redeclaring them. Keep one owner for each module, then make cargo check/test warning-clean.

---

_Reviewed: 2026-08-02T22:48:42Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
