# Deferred Items

## Accepted Phase 03 MVP scope debt

Source of record: accepted MVP scope decision during Phase 03 planning (2026-07-31). The MVP proves one runnable happy path: a valid query searches the completed corpus through vector and BM25 retrieval, fuses bounded evidence, and receives one structured LLM answer. The items below are intentionally excluded from the current implementation plan; safeguards that are necessary to make that happy path trustworthy remain in scope.

The revised five-plan execution order distributes that same scope across retrieval/dependencies, provider contracts, gRPC/startup readiness, gateway/embedding configuration, and the isolated local cross-runtime proof. This split does not promote any item below into implementation; initial BM25 construction/readiness remains in scope, while dynamic restart/re-ingestion recovery remains `DEBT-RAG-04`.

## ADR-03-001 deferred-confirmed boundaries

The gap closure plans 03-13 through 03-18 implement specific accepted ADR-03-001 decisions; no Phase 03 runtime implementation claim is made for D3, D4, or D5.

### Deferred decision mapping

| Future target contract | Current source-of-record debt |
|---|---|
| D-11 through D-16: degraded retrieval, model-only behavior, and degraded answer-basis/warning semantics | DEBT-RAG-01 |
| D-24: citation repair, unsupported-marker removal, and transparent downgrade | DEBT-RAG-03 |
| D-41 through D-43: re-ingestion atomic visibility and restart rebuild/failure behavior | DEBT-RAG-04 |

These mappings preserve the target behavior and decision IDs for later work; none is a Phase 03 implementation task or acceptance gate.

### DEBT-RAG-01 — Degraded retrieval and model-only fallback

D1 infrastructure failures now fail closed with session, correlation, and error-kind identity; disclosed surviving-path continuation and model-only behavior remain Phase 06.

- **Rationale:** The first usable slice must prove retrieval-grounded generation before expanding behavior for missing, weak, unnecessary, or failed evidence.
- **Known risk:** A vector or BM25 failure, empty result, or weak result may currently fail the request or lack an explicit `model_only` answer basis instead of degrading transparently.
- **Current constraints:** MVP verification uses a valid query over a query-ready completed corpus where both retrieval paths succeed; do not claim degraded-mode support.
- **Trigger:** Any claim that RAG-03 is fully implemented, any deployment with unreliable indexes/providers, or any shared/public use.
- **Target:** Phase 06 hardening/evaluation, or earlier if the trigger occurs.
- **Future acceptance criteria:** One-path failure returns a useful surviving-path answer with a machine-readable warning; both-path failure returns an explicit model-only basis and notice with no citations; weak/empty evidence follows the documented answer-basis contract.

### DEBT-D1-SAFE-LOG — Preserved full-message tracing under accepted D1-LOG waiver

D1 infrastructure failures fail closed with session, correlation, and error-kind identity; full-message tracing text is preserved as an accepted MVP override under ADR-03-002.

- **Rationale:** Phase 03 MVP prioritizes fail-closed error classification and session/correlation identity over strict log-body stripping.
- **Known risk:** Detailed provider error messages may appear in engine trace logs.
- **Current constraints:** Preserves response session, correlation, and error-kind identity; full message tracing text is allowed by the Phase 03 MVP waiver without changing `engine/src/main.rs`.
- **Trigger:** Phase 06 hardening or multi-tenant/shared-log-sink deployment.
- **Target:** Phase 06 hardening/evaluation.
- **Future acceptance criteria:** Identity-only structured logging without raw provider detail leakage across shared log sinks.

### DEBT-RAG-02 — Provider failure, timeout, retry, and fallback behavior

- **Rationale:** The MVP needs one successful provider call to prove the vertical path; orchestration retries and alternate-provider policy belong outside the first slice.
- **Known risk:** Provider timeout, cancellation, structured-output rejection, or transport failure may not yet have the final structured error and retry/fallback behavior.
- **Current constraints:** Use one bounded generation attempt with an injectable test provider; do not add retries or alternate-provider orchestration.
- **Trigger:** Provider instability, workflow orchestration, or a requirement for production-grade availability.
- **Target:** Phase 05 orchestration for retry/fallback policy, with Phase 06 hardening for evaluation.
- **Future acceptance criteria:** Timeout/cancellation and provider errors are classified and surfaced with session/correlation identity; retry and fallback policy is explicit, bounded, and tested without fabricating answers.

### DEBT-RAG-03 — Citation repair and transparent downgrade

D3 retains fail-closed citation validation: illegal markers do not produce a public success; citation repair and transparent downgrade remain Phase 06.

- **Rationale:** The happy path can validate structured citation IDs against the supplied evidence; repair of malformed or unsupported model markers is a separate failure path.
- **Known risk:** Malformed or unsupported citation markers may be rejected or left without the final repair-and-downgrade behavior.
- **Current constraints:** Happy-path tests use valid structured citations that resolve to selected bounded evidence.
- **Trigger:** Any invalid-marker production trace or a requirement to claim full citation-integrity coverage.
- **Target:** Phase 06 hardening/evaluation.
- **Future acceptance criteria:** One bounded repair attempt is made without another provider call; unresolved markers are removed, the answer basis is downgraded transparently, and a machine-readable warning is emitted.

### DEBT-RAG-04 — Re-ingestion/restart recovery and cross-index atomic visibility

D4 preserves initial BM25 build-before-readiness; after in-process ingest, an engine restart may be required because document completed does not imply presence in live BM25.

- **Rationale:** The MVP must build the initial BM25 snapshot before the first query-ready state, but replacement and restart recovery are broader lifecycle paths.
- **Known risk:** A future re-ingestion or restart could expose mixed vector/BM25 generations or serve before the lexical index is rebuilt.
- **Current constraints:** Build and verify the initial BM25 snapshot before accepting the first query; query tests use one completed corpus and must not claim replacement/restart freshness coverage.
- **Trigger:** Re-ingestion, engine restart during index updates, or any deployment where stale or mixed evidence is unacceptable.
- **Target:** Phase 06 hardening/evaluation.
- **Future acceptance criteria:** BM25 rebuild completes before readiness; old and new representations switch together; generation metadata proves no mixed evidence is served during replacement or recovery.

### DEBT-RAG-06 — Graph-extraction unavailability in RAG-03

D5 keeps Phase 03 source-chunk-only; the graph seam belongs to Phase 04 and graph-unavailable fallback remains Phase 06.

- **Rationale:** Graph context extraction belongs to Phase 04; the Phase 03 happy path uses completed source chunks and does not depend on graph context.
- **Known risk:** If graph extraction is unavailable, the eventual full RAG-03 contract may not yet describe or test the resulting degraded response.
- **Current constraints:** Do not implement graph extraction or graph-failure fallback in Phase 03. The happy path must remain runnable from source chunks alone.
- **Trigger:** Phase 04 graph context becomes part of the query path, or RAG-03 is claimed complete across graph and retrieval failures.
- **Target:** Phase 06 hardening/evaluation for full degraded behavior.
- **Future acceptance criteria:** Graph-unavailable queries retain a useful typed response or documented model-only/degraded basis, with machine-readable warning behavior and tests that do not require graph data for source-chunk queries.

This item is part of the explicit RAG-03 deferred scope. Phase 03 may preserve typed warning/answer-basis fields, but it must not claim graph-extraction failure handling or graph-backed degraded answers.

### DEBT-RAG-05 — Full invalid-input and filter edge coverage

Only D2's valid zero-match success branch is shipped; the malformed, bound, unmatched, and combinatorial filter matrix remains deferred.

- **Rationale:** The MVP exercises valid query and filter inputs needed for the end-to-end slice; exhaustive malformed, oversized, unmatched, and combinatorial input behavior can follow after the path is runnable.
- **Known risk:** Invalid requests may not yet receive every final HTTP/gRPC classification or bound-specific error.
- **Current constraints:** Keep basic contract validation and bounded evidence in the happy path; do not claim exhaustive negative-input coverage.
- **Trigger:** External callers, fuzzing/property testing, or a requirement for complete public API contract coverage.
- **Target:** Phase 06 hardening/evaluation.
- **Future acceptance criteria:** Empty/oversized queries, malformed IDs, unsupported content types, and filter limits are rejected before retrieval/provider work with stable HTTP 400 and gRPC `InvalidArgument` behavior.

### DEFERRED-03-11-01 — Pre-existing citation test working-tree edit

- **Found during:** Plan 03-11 overall verification.
- **Evidence:** The mandated full engine suite passed 63 tests and failed only `query_rag_citation_identity_and_notices` at `engine/src/tests.rs:2754`, where the existing unstaged edit expects `Root` but the generated citation is `/Document Beta`.
- **Scope:** This edit predates the 03-11 continuation and was explicitly requested to remain untouched; no plan commit includes it.
- **Resolution:** Preserve the working-tree edit and defer its test reconciliation to the owner of that change. The six focused 03-11 verification tests pass.

### DEFERRED-03-12-01 — Preserved citation-test edit and repository formatting drift

- **Found during:** Plan 03-12 overall verification.
- **Evidence:** The full Rust suite passed all 24 library tests and 70 of 71 binary tests; `query_rag_citation_identity_and_notices` failed at `engine/src/tests.rs:2842` because the preserved unstaged edit expects `Root` while the fixture produces `/Document Beta`. Repository-wide `cargo fmt --check` also reports pre-existing drift in `engine/src/generation/*` and `engine/src/prompt.rs`; the 03-12 Rust files pass file-local rustfmt.
- **Scope:** Both conditions are outside the 03-12 production changes. The citation edit was explicitly requested to remain untouched, and unrelated formatting changes were not applied.
- **Resolution:** Defer reconciliation to the owner of the citation edit and a dedicated formatting cleanup; do not claim the full repository gate passed.

### DEFERRED-03-12-02 — User-stopped Go and protobuf gates

- **Found during:** Plan 03-12 overall verification.
- **Evidence:** The Go, cross-runtime `TestRAGQueryCrossRuntime`, `buf lint`, and `buf format --diff --exit-code` gates were not completed after the user directed execution to stop phase-final gates.
- **Scope:** No production defect was inferred; the remaining verification was intentionally stopped by the user after all substantive 03-12 commits were present.
- **Resolution:** Run these gates only when the user requests phase-final/regression verification.

## ADR-03-003 Force-Close Deferred Items Ledger

Accepted force-close disposition recorded in `.discussion/decisions/phases/03/2026-08-05-ADR-03-003-all-the-way-to-ship-mvp.md`.

### DEBT-P3-BODY-BOUND — Provider body bound post-chunk (Plan 03-20 T1)
- **Rationale:** `reqwest::Response::chunk` limit check is post-materialization. Local MVP trusts the configured provider; full stream cap is Phase 06 hardening.
- **Known risk:** Untrusted or malicious upstream can force large frame allocation before reject.
- **Current constraints:** MVP trusts configured provider transport. Do not expose Engine provider egress to untrusted networks.
- **Trigger:** Non-loopback deployment, untrusted provider path, or security review of provider I/O.
- **Target:** Phase 06 resource/security hardening.
- **Future acceptance criteria:** Reader never retains frame exceeding remaining budget; shared 256 KiB policy enforced pre-materialization.

### DEBT-P3-STAGING-GEN-RACE — Staging generation allocation race (Plan 03-23 T1)
- **Rationale:** `persist_raw_with_boundary` max generation RMW lacks lock/CAS. Single-writer per doc local MVP avoids concurrent ingest of same doc.
- **Known risk:** Duplicate generation values; fail-closed read sticks document requiring manual repair.
- **Current constraints:** Single writer per document_id at a time. Int64 generation column & append-verify-delete protocol unchanged.
- **Trigger:** Concurrent same-document_id ingest, multi-replica Engine, or production incident with stuck staging docs.
- **Target:** Phase 06 ingestion hardening.
- **Future acceptance criteria:** Generation allocation atomic/serialized per document; concurrent replace test passes.

### DEBT-P3-STAGING-PHYSICAL-BU — Physical row retention after delete failure (Plan 03-23 T2)
- **Rationale:** Delete failure leaving both physical rows unproven under injected delete faults.
- **Known risk:** Unproven physical row retention under fault paths.
- **Current constraints:** Rely on sequential happy-path replace only for confidence.
- **Trigger:** Staging failure-injection work starts or write protocol modified.
- **Target:** Phase 06 test hardening.
- **Future acceptance criteria:** Injected delete failure leaves old + successor physical rows; error returned; successor not deleted.

### DEBT-P3-CONFIG-DB-PLAINTEXT — Committed database credentials and disabled TLS
- **Rationale:** `config.toml` contains plaintext dev credentials and `sslmode=disable` for local docker-style MVP defaults under R4.
- **Known risk:** Unencrypted DB traffic if remote; credential exposure if mis-copied.
- **Current constraints:** Single-host local Postgres only. Do not deploy committed defaults to shared/prod databases.
- **Trigger:** Non-local Postgres, shared environment, or secrets review.
- **Target:** Phase 06 secrets/config hygiene.
- **Future acceptance criteria:** No live credentials in committed config; placeholders used; TLS required for non-local.

### DEBT-CR-04 — Insecure Gateway→Engine gRPC (Extended with Phase 03 evidence)
- **Rationale:** `gateway/main.go` dials engine with `insecure.NewCredentials()`. Extended Phase 02 `DEBT-CR-04` with Phase 03 evidence; loopback single-host MVP makes plaintext gRPC acceptable.
- **Known risk:** Plaintext gRPC if `engine_addr` is remote.
- **Current constraints:** Engine reachable only via loopback / single-host path.
- **Trigger:** Non-loopback `engine_addr`, multi-host deployment, or shared network path.
- **Target:** Phase 06 transport hardening.
- **Future acceptance criteria:** TLS with cert validation for non-local; fail startup when insecure dials non-loopback.

### DEBT-P3-PROVIDER-ENDPOINT-TRUST — Provider endpoint trust and bearer exfiltration
- **Rationale:** Effective settings validate endpoints only as non-blank. Bearer token sent to configured URL.
- **Known risk:** Typo/malicious endpoint URL receives API bearer key.
- **Current constraints:** Provider endpoint is operator-trusted input. Do not accept endpoint values from untrusted multi-tenant config.
- **Trigger:** Multi-tenant/untrusted config source or security review.
- **Target:** Phase 06 security hardening.
- **Future acceptance criteria:** HTTPS required except loopback dev; endpoint host allowlist before attaching bearer.

### DEBT-P3-WARN-DX — Fixture and upload DX issues
- **Rationale:** Non-idempotent seeder appends duplicate stable IDs on re-run; empty multipart upload ambiguity.
- **Known risk:** Duplicate corpus rows on re-seed; ambiguous empty file upload error.
- **Current constraints:** Treat seeder as non-idempotent; reset DB/fixtures when re-seeding.
- **Trigger:** CI flake from duplicate seeds or user empty-upload issue.
- **Target:** Phase 06 DX overhaul.
- **Future acceptance criteria:** Seeder reset/upsert; empty upload rejected with 400.

### DEBT-P3-WARN-API — API semantics and D1 identity gaps
- **Rationale:** Mixed answer basis without conflict disclosure; `NoEvidenceFits` mapped to 400 (blaming client for capacity); missing D1 session/correlation identity on some retrieval errors.
- **Known risk:** Misleading status codes; incomplete error correlation.
- **Current constraints:** Do not assume Mixed always carries conflict notices; capacity failure may show as 400.
- **Trigger:** External client integration depending on precise status/identity.
- **Target:** Phase 06 API contract hardening.
- **Future acceptance criteria:** Mixed requires conflict notice; `NoEvidenceFits` maps to capacity status; error kinds attached.

### DEBT-P3-WARN-SETTINGS — Settings consistency warnings
- **Rationale:** Invalid numeric env overrides silently ignored; public scalar grounding budgets vs private carrier; chunk limits saturate to `i32::MAX`.
- **Known risk:** Effective config differs from env override intent.
- **Current constraints:** Validate critical overrides manually when using env.
- **Trigger:** Production config via env at scale or settings incidents.
- **Target:** Phase 06 settings refactor.
- **Future acceptance criteria:** Present-but-invalid env overrides fail startup; carrier is single authority; fail-closed chunk settings.

### DEBT-P3-WARN-VALIDATE — Validation gaps (nulls and non-finite)
- **Rationale:** Staging readers call `value(i)` without null checks on required fields; embeddings missing `f32::is_finite` check; BM25 finite boosts overflow before fusion reject.
- **Known risk:** Panic on corrupt rows or non-finite provider outputs.
- **Current constraints:** Do not feed untrusted embedding providers; treat staging corruption as stop-the-line issue.
- **Trigger:** Untrusted embedding source or numeric retrieval incidents.
- **Target:** Phase 06 validation sweep.
- **Future acceptance criteria:** Required staging fields null-checked; embeddings finite-checked; BM25 boost ceilings.

### DEBT-P3-MODULE-GRAPH — Dual library/binary module graph
- **Rationale:** `lib.rs` and `main.rs` both declare overlapping production modules, risking drift between test library and running binary.
- **Known risk:** Silent dual implementation drift.
- **Current constraints:** Critical fixes must land on the path binary uses.
- **Trigger:** Next large engine module change or observed drift.
- **Target:** Phase 06 engine layout refactor.
- **Future acceptance criteria:** Binary imports shared modules from library crate.

