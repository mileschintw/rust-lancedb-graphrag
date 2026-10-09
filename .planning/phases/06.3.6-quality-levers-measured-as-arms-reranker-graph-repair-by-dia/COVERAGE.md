# API Coverage — OpenRouter rerank (POST /api/v1/rerank)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

Planning artifact written at `/gsd-plan-phase 06.3.6` (2026-10-09). Source: `06.3.6-RESEARCH.md` "API Coverage Input"
and `research/fetched/openrouter-submit-a-rerank-request-2026-10-09.md` (sha256 `f8d3629d...e806`). Model
`voyageai/rerank-2.5-lite` (D-131). The adapter that implements the INTEGRATE rows is `engine/src/rerank/openrouter.rs`
(plan 06.3.6-09); the D-131 probe (plan 06.3.6-01) verifies the authenticated 200 before any lever-1 code.

| capability | decision | reason |
|---|---|---|
| `model` (required): `voyageai/rerank-2.5-lite` | INTEGRATE | D-131 owner choice; config `[openrouter] rerank_model`; the live reply carries the bare model name `rerank-2.5-lite` (`06.3.6-PROBE.md`); the reply `model` must start with the requested slug or with its bare name after the vendor prefix (D-186, 2026-10-09) |
| `query` (required): the search query | INTEGRATE | `ctx.original_query`, the same text retrieval used |
| `documents` (required, `minItems: 1`) as plain strings | INTEGRATE | `candidate.content` verbatim, fused order, at most `candidate_limit` = 32 (D-132); an empty candidate list returns without a call |
| `documents` as `{text, image}` objects / image documents | OPT-OUT | Text corpus; no image content exists in the eval store or the ingest path |
| `top_n` (optional, `minimum: 1`) | INTEGRATE | `top_n = n`, so the reply is a full permutation the engine can validate |
| `provider` (`ProviderPreferences`): `allow_fallbacks: false` | INTEGRATE | D-131 "no silent fallback": the key is never spent on a re-routed provider |
| `provider`: other routing fields (order, only, ignore, sort) | OPT-OUT | One model, one provider listed ("VoyageAI by MongoDB"); `allow_fallbacks: false` is the only routing control the lever needs |
| `session_id` (max 256) | OPT-OUT | Observability grouping on OpenRouter's side; attribution is carried by the engine's own correlation id and the journal |
| `user` (max 256) | OPT-OUT | No end-user identity exists in the local-only system (6.4 limitations); nothing to attribute |
| `trace` (`TraceConfig`, Broadcast metadata) | OPT-OUT | The engine uses its own OpenTelemetry stack (OBS-01); a second trace sink adds a data path with no measurement value |
| Streaming | OPT-OUT | Not offered: the OpenAPI states rerank does not support streaming |
| 200 body `id` | OPT-OUT | Not needed for reconciliation; spend is read from `usage.cost` and the account delta |
| 200 body `model` | INTEGRATE | Validated: must start with the requested slug or with its bare name after the vendor prefix (D-186, 2026-10-09; the live reply carries `rerank-2.5-lite`), else `MalformedResponse` and the record degrades (D-134) |
| 200 body `provider` | OPT-OUT | Ignored on purpose (may be logged as a bounded field); `allow_fallbacks: false` already pins routing |
| 200 body `results[].index` | INTEGRATE | Must be a permutation of `0..n`; anything else is `MalformedResponse` |
| 200 body `results[].relevance_score` | INTEGRATE | Must be finite; overwrites `fused_score` under the rerank lever (D-166); ties broken by `(relevance_score desc, index asc)` |
| 200 body `results[].document` | OPT-OUT | Echo of the input text; ignored (and it is why the body cap is raised above 256 KiB, RESEARCH C11) |
| 200 body `usage.cost` | INTEGRATE | Carried as `RerankMetadata.cost_credits` / `cost_reported`; summed into `compute_spend` (O15); never replaced by a constant |
| 200 body `usage.search_units`, `usage.total_tokens` | OPT-OUT | Not a billing input for the harness; `usage.cost` is the reconciled figure, the account delta the settled one |
| Error 400 (bad request) | INTEGRATE | `RerankError` class, degrade with `RERANK_DEGRADED` (D-134); message carries class and status only |
| Error 401 (auth) | INTEGRATE | `RerankError` class; degrade; key never in the message |
| Error 402 (insufficient credits) | INTEGRATE | `RerankError` class; degrade; in the drive this is infrastructure under D-110 |
| Error 403 (forbidden / moderation) | INTEGRATE | `RerankError` class; degrade |
| Error 404 (model or route not found) | INTEGRATE | `RerankError` class; degrade |
| Error 413 (request too large) | INTEGRATE | `RerankError` class; degrade; the engine never truncates a document to make it fit |
| Error 429 (rate limited) | INTEGRATE | `RerankError` class; degrade; no retry (a retry cannot fit the node budget) |
| Error 500 / 502 / 503 / 524 / 529 (provider or edge failure) | INTEGRATE | `RerankError` classes; degrade; no retry |
| Price per call | INTEGRATE | Read per call from `usage.cost` (D-131), never a price constant (the listing shows 0/0); `RERANK_UNREPORTED_CALL_CEILING_USD` covers only calls that omit `usage.cost` |
