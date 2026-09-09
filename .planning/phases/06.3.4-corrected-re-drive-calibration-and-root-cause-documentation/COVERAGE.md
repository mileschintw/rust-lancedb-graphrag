# API Coverage Declaration — Phase 06.3.4

**No external API integration: this phase drives an already-integrated provider through an existing
harness and wraps no new external API surface.**

## Why the detector fired

The deterministic detector returned `detected: true` on two signals, both of which are prose about
an internal wire vocabulary rather than an integration:

| Signal | Snippet | Reading |
|---|---|---|
| `wire` + `api` | "…how a typed code becomes the wire string an API client sees…" | 06.3.4-06 documenting how `gateway/main.go` trims `NOTICE_CODE_` before a notice reaches a client. This describes an **existing** first-party gRPC/proto surface that Phase 06.3.1 already landed (`NOTICE_CODE_RETRIEVAL_FAILED = 19` at `proto/lancet/v1/lancet.proto:96`); nothing is being integrated. |
| `wire` + `rest` | "The rest of the wire vocabulary, for the omissions this plan must enumerate" | The word "rest" here is the ordinary English noun, not REST. Same 06.3.4-06 notice-code enumeration. |

## Why no capability matrix is built

The one external, metered service this phase touches is the OpenRouter-backed generation and judge
provider. It is consumed through `eval/src/lancet_eval/` — `run.py`'s `drive()`, `judge.py`'s
`judge_once()`, and `measure.py`'s allowance check — all of which were integrated by earlier phases
in the 06.3 family and are already under test. Phase 06.3.4 changes *how much* that existing
integration is allowed to spend and *which population* it is pointed at; it adds no new provider, no
new endpoint, no new auth flow and no new SDK.

Two changes in this phase touch provider-facing code and are worth naming explicitly, because both
are refinements of an existing call path rather than new surface:

- **`run.py` bounded-window dispatch (06.3.4-01).** Replaces a submit-all `ThreadPoolExecutor`
  comprehension with an in-flight window so the stage spend cap can stop dispatch. Same endpoint,
  same client, same request shape — only the scheduling around it changes.
- **`judge.py` usage-token return (06.3.4-05).** `judge_once` already receives the full provider
  response and reads only `choices`; it will additionally read the `usage` object the provider
  already sends. This consumes a field of a response already being received. No new call is made.

New Python dependencies are forbidden by this phase's stated evaluation contract, and
`uv lock --project eval --check` is a verification step in 06.3.4-01 and 06.3.4-02 — an integration
requiring a new client library would fail that check by construction.

## Disposition

No capability matrix required. Recorded rather than skipped silently, because the detector's
`detected: true` is a real signal that deserves a reasoned answer a later reader can audit.
