# Phase 6.3 — API Coverage Decision

**Verdict: No external API integration in the sense this checkpoint means.**

No external API integration: this phase builds an offline evaluation harness that drives Lancet's own already-integrated internal HTTP surface, and its single provider-facing call reuses the engine's existing OpenRouter integration pattern for a second purpose rather than wrapping a new external API.

---

## Why the detector fired, and why it is a false positive here

The `api-coverage` detector returned `detected: true` on a single thin signal — a prohibition sentence in the plan set reading "MUST NOT reach the live OpenRouter API...". That is a *negative* constraint on test code, not a description of a new external surface being wrapped. Re-reading the actual phase scope against the "capability enumeration" question this checkpoint exists to answer:

| Candidate surface | Is it a new external API integration? | Why |
|---|---|---|
| Gateway `/rag/query` (SSE) | **No — internal** | Lancet's own endpoint, integrated and fully exercised since Phase 6. The harness is a client of the system under test, which is the point of D-48 ("drive it like a real client"). Enumerating its capabilities is what the phase's own success criteria already do. |
| Gateway `/documents` (multipart upload) and `GET /documents/{id}` | **No — internal** | Same. The seeder deliberately uses the shipped ingestion path (D-56) with no new parameters; plan 06.3-04 already pins the full request surface it touches, including the fields it deliberately omits. |
| Gateway `/health` | **No — internal** | Same. Plan 06.3-04's preflight consumes both its 200 and 503 shapes. |
| HuggingFace dataset download (`corpus fetch`) | **No — file fetch, not an API** | Two unauthenticated HTTPS GETs for static dataset files, with a documented by-hand fallback. There is no API surface with capabilities to enumerate: there is one verb (fetch a file) and it is fully covered. |
| **OpenRouter, called directly by the LLM judge (plan 06.3-06)** | **No — reuse of an existing integration** | This is the one genuinely new provider-facing call site in the phase, and it is the case worth arguing. See below. |

## The judge call: reuse, not a new integration

The engine already integrates OpenRouter fully (`engine/src/generation/openrouter.rs`), including the chat-completions call, structured-output/`response_format` negotiation, the `supported_parameters` capability preflight, model pinning, and rate-limit and error handling. Phase 6.3's judge is a **second consumer of that same provider, over the same chat-completions verb**, from a different runtime.

The judge's surface is deliberately and irreducibly one call: a temperature-0, bounded-`max_tokens` chat completion against a pinned model, whose response is validated against a Pydantic model with one bounded re-ask. Plan 06.3-06 already pins every dimension of that surface as executable contract — the model pin and its distinctness from the generator (D-62), temperature and token bounds, the retry and `retry-after` handling, the fence-stripping-plus-Pydantic guarantee rather than trusting `response_format`, the cache key, and the failure accounting.

Producing a capability matrix here would enumerate exactly one capability — "chat completion" — and would restate contract that is already executable in 06.3-06. This checkpoint exists to surface *invisible holes* in a newly-wrapped API's surface. There is no hole: no other OpenRouter capability (embeddings, streaming, tool calling, image input, the models endpoint beyond the existing preflight) is in this phase's scope, and none is silently omitted — they are simply not what a groundedness judge does.

**Explicitly not built, so the omission is visible rather than invisible:** streaming judge responses, tool/function calling in the judge, batch or async job submission, embeddings from the judge provider, multi-turn judge conversations, and any provider capability negotiation beyond the model pin. Each is out of scope by design, and none is required by D-50, D-52 or D-62.

## Where the real coverage guarantee lives

This phase's equivalent of an API coverage matrix is `06.3-VALIDATION.md`'s Per-Requirement Verification Map, which enumerates every task, its requirement, its threat reference and its automated command — and `06.3-01-PLAN.md`'s § "Multi-source coverage audit", which maps every GOAL, REQ, ROADMAP, RESEARCH, CONTEXT and REVIEWS item to an owning plan with no item deferred or dropped.

---

*Recorded during the `/gsd-plan-phase 6.3 --reviews` replan pass, 2026-08-29.*
