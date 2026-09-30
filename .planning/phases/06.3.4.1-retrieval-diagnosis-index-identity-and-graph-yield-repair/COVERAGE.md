| capability | decision | reason |
|---|---|---|
| OpenRouter chat completions with strict json_schema output (model_output) | INTEGRATE | Existing engine path; D-95 (plan 29) adds the required final_answer property that the engine renders as the last Answer line |
| OpenRouter provider routing: require_parameters | INTEGRATE | D-96 (plan 29): route only to endpoints that support every parameter sent, with fallback among them kept on |
| OpenRouter provider routing: single-provider pin | OPT-OUT | D-96 not chosen: an outage would become SC-2 errors, and the provider that served drive 1's good answers is unknown |
| OpenRouter response metadata: id, model, provider | INTEGRATE | D-96 (plan 29): read as optional values and logged with correlation_id; a missing or non-string value never fails a generation |
| OpenRouter models metadata (supported_parameters check) | INTEGRATE | Existing structured-output capability check before generation, unchanged by this phase |
| OpenRouter embeddings (query embedding) | INTEGRATE | Existing query-embedding path, unchanged by this phase |
| OpenRouter auth/key usage reading | INTEGRATE | Existing spend metering by the settled account delta for every paid stage (D-86), unchanged |
| OpenRouter activity API (GET /api/v1/activity) | INTEGRATE | G11 (plan 29): one read-only operator reading of drive 1's provider split; not an engine code path |
| OpenRouter generation stats (GET /api/v1/generation) | OPT-OUT | Not called by the engine; drive 1 kept no generation IDs, and D-96's logged IDs allow a later manual lookup |
