---
phase: 03
reviewers: [agy]
reviewed_at: 2026-08-05T20:40:47Z
plans_reviewed: [03-01-PLAN.md, 03-02-PLAN.md, 03-03-PLAN.md, 03-04-PLAN.md, 03-05-PLAN.md, 03-06-PLAN.md, 03-07-PLAN.md, 03-08-PLAN.md, 03-09-PLAN.md, 03-10-PLAN.md, 03-11-PLAN.md, 03-12-PLAN.md, 03-13-PLAN.md, 03-14-PLAN.md, 03-15-PLAN.md, 03-16-PLAN.md, 03-17-PLAN.md, 03-18-PLAN.md, 03-19-PLAN.md, 03-20-PLAN.md, 03-21-PLAN.md, 03-22-PLAN.md, 03-23-PLAN.md]
repo_access: granted
review_mode: plan
---

# Cross-AI Plan Review — Phase 03

## AgY Review

### Summary

AgY reviewed all 23 Phase 03 plans and the live implementation, with particular attention to plans 03-19 through 03-23. It found that the core hybrid dense/BM25 retrieval path, RRF fusion, structured answer path, RAG-04 reranker port, provider limits, and deferred RAG-03 boundaries are substantially represented in the checkout. It identified one high-severity data-integrity risk and three additional implementation concerns that should be resolved or independently verified before final sign-off.

### Strengths

- `EffectiveRagSettings` owns one private, validated `Arc<GroundingLimits>` carrier, and configured provider limits are fail-closed (`engine/src/generation/mod.rs:85-131`, `engine/src/generation/openrouter.rs:77-85`).
- A shared 256 KiB streaming response bound covers chat, model metadata, and embeddings (`engine/src/client/mod.rs:15,37-60`, `engine/src/generation/openrouter.rs:297-311,469-483`).
- Retrieval service ceilings and bounded BM25 candidate retention prevent unbounded candidate work (`engine/src/retrieval/mod.rs:30-36,246-319`, `engine/src/retrieval/bm25.rs:310-336`).
- RRF deduplicates per source and rejects non-finite scores; the Go gateway buffers JSON before committing the HTTP status (`engine/src/retrieval/fusion.rs:35-53,137-175`, `gateway/main.go:846-857`).
- Prompt evidence is XML-escaped and injection patterns are surfaced as untrusted evidence diagnostics (`engine/src/prompt.rs:107-114,168-179`).
- AgY found the claim/lease integration tests compliant with the repository convention for isolated schemas and fatal snapshot-query errors (`gateway/db/document_test.go:189-236,249-452`).

### Concerns

#### HIGH — non-atomic staged generation increment

- Plan: `03-23`
- Evidence: `engine/src/main.rs:872-876,902`; latest-row selection at `engine/src/main.rs:683-687`.
- Mechanism: two concurrent replacements for the same `document_id` can read the same maximum generation, both assign `old + 1`, and create duplicate generation rows. The latest-generation reader then treats the duplicate as ambiguous and fails closed, potentially blocking that document until intervention.
- Recommendation: serialize replacement per document or make generation assignment atomic. Add a concurrent replacement regression before closing the phase.

#### MEDIUM — schema matching and migration path are fragile

- Plan: `03-23`
- Evidence: `engine/src/db/mod.rs:35-62,88`.
- Mechanism: exact Arrow `Field` vector equality can reject a compatible legacy table when metadata differs, and a read-only `open_and_validate` path may report schema drift without applying the compatible generation-column migration.
- Recommendation: compare compatible field names/types explicitly and ensure every startup/open path either migrates the legacy schema or reports a deliberate, tested compatibility result.

#### MEDIUM — staging generation queries may load full raw blobs

- Plan: `03-23`
- Evidence: `engine/src/main.rs:841-845,908-916`.
- Mechanism: maximum-generation and successor-verification queries do not project only the generation/identity fields, so LanceDB may deserialize historical `raw_content` payloads while calculating metadata.
- Recommendation: add explicit column projections such as `generation` and `document_id` to the metadata-only queries, with a regression covering the query shape if the API supports it.

#### LOW — positional RecordBatch construction is schema-order dependent

- Plan: `03-23`
- Evidence: `engine/src/main.rs:879-900`.
- Mechanism: arrays are supplied positionally against the table schema. Future field reordering could make the batch invalid or bind values to the wrong fields.
- Recommendation: construct the batch using explicit schema-order helpers or named builders.

#### LOW / live-verification required — reported test and formatting drift

- Plans: `03-11`, `03-12`
- Evidence cited by AgY: `engine/src/tests.rs:2842` and `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md:100-113`.
- Mechanism: AgY reported a citation expectation mismatch and formatting drift. This was not corroborated at report-writing time because the current worktree was clean; the independent verification and test gate must decide whether it is stale or current.
- Recommendation: treat this as a verification item, not as a confirmed blocker, until the current checkout test results establish the fact.

### Overall Risk Assessment

Core MVP scope is structurally strong, but raw-staging concurrency is a moderate-to-high integrity risk because duplicate generations can make a document unreadable. Migration behavior and unnecessary blob reads add operational risk. The explicitly deferred RAG-03 degraded/model-only/citation-repair behaviors remain outside Phase 03 scope and should stay in the debt ledger.

## Consensus Summary

### Agreed Strengths

The current implementation has a coherent provider-neutral RAG boundary, explicit resource ceilings, bounded provider bodies, finite deterministic fusion, safe gateway JSON response commitment, prompt evidence escaping, and a pluggable `NoOpReranker` port. These strengths align with the Phase 03 MVP intent and are corroborated by the source review’s current code inspection.

### Agreed Concerns

1. Close or explicitly accept the 03-23 per-document generation race with a concrete concurrency proof.
2. Make compatible legacy schema detection/migration behavior explicit and tested.
3. Project metadata-only staging queries so replacement checks do not repeatedly load raw payloads.

### Divergent / Uncorroborated Views

AgY described the core phase goal and RAG-02/RAG-04 as achieved, while the current source review and independent verification remain the authoritative quality gates. AgY’s cited citation-test/formatting drift was not treated as confirmed until the live verifier reruns the current checkout. AgY’s positive MVP assessment does not override any current `gaps_found` verification status.

### Highest-Priority Actions Before Sign-Off

Resolve the staged-generation concurrency and migration decisions, rerun the complete Rust/Go gates, and refresh independent verification. Keep Phase 03 pending unless the canonical verifier returns `passed`; do not transition based on this advisory cross-AI review alone.
