# API Contract: Request Fields and Notice Codes

> [!NOTE]
> [`proto/lancet/v1/lancet.proto`](../proto/lancet/v1/lancet.proto) is the source of truth for everything on this page.
> A test, [`eval/tests/test_notice_docs.py`](../eval/tests/test_notice_docs.py), keeps the tables in step: it fails if
> the notice table's names and numbers differ from the proto's `NoticeCode`, if the `degraded_mode` column differs from
> the three arms of `derive_degraded_mode` in [`engine/src/workflow/mod.rs`](../engine/src/workflow/mod.rs), or if the
> request-field table names a field `QueryRAGRequest` does not declare.

A client talks to Lancet in one of two ways:

- **gRPC:** `LancetService.QueryRAG` on the engine, with a `QueryRAGRequest`.
- **HTTP:** `POST /rag/query` on the gateway, with a JSON body. The response is a stream of server-sent events.

The gateway decodes the JSON body, checks the few things it owns, and forwards a `QueryRAGRequest`. Both paths reach the
same admission code in the engine (`query_rag` in [`engine/src/service.rs`](../engine/src/service.rs)).

This page is the contract a client can rely on. It covers:

- [Request fields](#request-fields)
- [Refusals](#refusals)
- [Notice codes](#notice-codes)
- [The bad-input matrix](#the-bad-input-matrix)

## Request fields

The HTTP body uses the same field names as the proto. Every field is optional except `query`. The gateway rejects any
key it does not know.

| field | gRPC type | HTTP JSON | absent means | values |
|---|---|---|---|---|
| `query` | `string` | string | an empty query, refused as `empty_query` | the question. It is refused when it is empty, whitespace-only or longer than the configured `query_max_bytes`. |
| `session_id` | `string` | string | the engine assigns one | a UUIDv4. A malformed id, or a UUID of another version, is refused as `invalid_session_id`. |
| `filter` | `DocumentFilter` | object `{"document_ids": [...], "content_types": [...]}` | no filter | restricts retrieval to the named documents and content types. A filter that matches nothing is not refused: the response carries `NO_EVIDENCE`. |
| `allow_model_only` | `optional bool` | bool | the configured default (`[engine.workflow] allow_model_only_answers`) | `true` lets the engine answer from the model's own knowledge when retrieval finds nothing, with a `MODEL_ONLY` notice. `false` turns that off for this request (06-CONTEXT D-10, D-12). |
| `disable_graph_context` | `optional bool` | bool | the configured default, `[engine.graph] context_default_enabled`, which ships `false`, so the graph is off and the response carries `GRAPH_DISABLED_BY_CONFIG` | `false` turns graph context on for this request. `true` turns it off and the response carries `GRAPH_ABLATION` (06.4 D-207). |
| `retrieval_mode` | `RetrievalMode` | string: `hybrid`, `dense_only` or `bm25_only` | `hybrid` | which retrieval paths run (06.3.5 D-99). A path the mode excludes is skipped and emits no `RETRIEVAL_DEGRADED_*` notice. The chosen mode is echoed on the snapshot. |
| `include_pre_truncation_ranking` | `bool` | bool | `false` | `true` adds the pre-rerank, pre-truncation candidate ranking (ids and ranks only) to the snapshot (06.3.5 D-100). |
| `levers` | `repeated Lever` | array of strings: `rerank`, `evidence_metadata`, `binary_answer_format`, `graph_v2` | the configured default levers, `[engine.levers] defaults` (shipped: `rerank` and `evidence_metadata`) | the quality levers this request runs. A request that names levers runs exactly those, never the union with the configured defaults (06.3.6 D-136, D-157). |
| `disable_default_levers` | `optional bool` | bool | `false` | `true` runs exactly the named levers, even none, and adds no configured default (06.4 D-198). |

### `disable_graph_context`: three states

`disable_graph_context` follows the same presence pattern as `allow_model_only`. Phase 06.4 changed what an absent
field means (D-207), and that amends 06-CONTEXT D-47, which made absent mean "graph on".

| What the request sends | Graph context | Notice on the response |
|---|---|---|
| nothing (field absent) | the configured default: off as shipped (`context_default_enabled = false`) | `GRAPH_DISABLED_BY_CONFIG` (25), informational |
| `"disable_graph_context": false` | on | none from this field |
| `"disable_graph_context": true` | off | `GRAPH_ABLATION` (18), informational |

The two "off" codes say why the graph did not run. `GRAPH_ABLATION` means the caller turned it off, which is what the
evaluation's graph-off arms send. `GRAPH_DISABLED_BY_CONFIG` means the caller left the field out and the configured
default is off. Neither code sets `degraded_mode`: the graph being off is the expected state, not a fault.

### Levers and the snapshot echo

The snapshot on every response carries a `levers` list with the levers that actually ran, in ascending enum order. Over
gRPC it is `RetrievalSnapshot.levers`; over HTTP it is `snapshot.levers`, as lever names. The echo never claims a lever
that did not run:

- **A request that names levers** runs exactly those. If one of them cannot be served, the whole request is refused with
  `lever_unavailable` (see [Refusals](#refusals)).
- **A request that names no lever** runs the configured defaults. A default whose resource the engine does not hold is
  dropped, not refused. The echo leaves it out, and the response carries one `DEFAULT_LEVER_UNAVAILABLE` (24) notice per
  dropped lever (06.3.6 D-194).
- **`"disable_default_levers": true`** runs exactly the named levers. With no levers named, the request runs lever-free
  and the echo is empty.

## Refusals

A refused request never reaches retrieval or the model. The engine refuses with gRPC status `INVALID_ARGUMENT` and puts
a stable error kind in the `x-lancet-error-kind` trailer. The gateway turns that into HTTP 400, with the engine's message
as the body and the kind in the `X-Lancet-Error-Kind` response header. Any other engine status before the stream
starts becomes HTTP 502 ("engine query failed").

**Lever and graph refusals:**

| error kind | when | gRPC | HTTP |
|---|---|---|---|
| `invalid_levers` | `levers` holds an integer outside the declared `Lever` values, a negative value, `LEVER_UNSPECIFIED` (0), or a lever named twice | `INVALID_ARGUMENT` | not reachable over HTTP: the gateway refuses an unknown lever name, a duplicate or more than four levers itself (see below) |
| `lever_unavailable` | the request names a lever whose resource this engine does not hold: `rerank` with no rerank provider configured, `evidence_metadata` while the index holds no document metadata, `graph_v2` while `[engine.graph] graph_v2_chunk_precision` is the no-op `all` | `INVALID_ARGUMENT` | 400, `X-Lancet-Error-Kind: lever_unavailable` |
| `invalid_lever_combination` | the request's lever set holds `graph_v2` while the graph resolves to off: either `disable_graph_context` is `true`, or it is absent and the configured default is off. To run `graph_v2`, send `"disable_graph_context": false`. | `INVALID_ARGUMENT` | 400, `X-Lancet-Error-Kind: invalid_lever_combination` |
| `invalid_retrieval_mode` | `retrieval_mode` is an integer outside the four declared values | `INVALID_ARGUMENT` | not reachable over HTTP: the gateway refuses an unknown mode name itself |

The combination check runs before the availability check, so `graph_v2` with the graph off is always
`invalid_lever_combination`, whatever the engine holds. `invalid_lever_combination` reads the lever set the request
will run: a configured default of `graph_v2` would trip it too, though the shipped defaults do not include it.

**Gateway-only refusals.** The gateway checks the body before it calls the engine. These come back with no error-kind
header:

| condition | HTTP |
|---|---|
| a body that is not one JSON object, has trailing data, or holds an unknown key | 400 "invalid request body" |
| a `retrieval_mode` other than `hybrid`, `dense_only` or `bm25_only` | 400 "invalid request body" |
| a `levers` entry that is not one of the four names (wrong case, empty string and `unspecified` included), a duplicate name, or more than four entries | 400 "invalid request body" |
| a body larger than 32 KiB | 413 "request body too large" |

The input-validation refusals (`empty_query`, `query_too_long`, `invalid_session_id`, the filter kinds) are in
[the bad-input matrix](#the-bad-input-matrix).

## Notice codes

A notice is how the engine tells a client what it did not do, or did differently. Each notice on the wire carries:

- `typed_code`, the `NoticeCode` number. This is canonical.
- `code`, a string derived from it: the enum name without the `NOTICE_CODE_` prefix, for example `GRAPH_ABLATION`.
- `severity`: 1 info, 2 warning, 3 error.
- `message`: human-readable text.

Values 1-3 kept the string spellings they had before the enum existed (06-CONTEXT D-76).

**`degraded_mode`.** Each response's workflow metadata carries a `degraded_mode` boolean. In the table below, the
`degraded_mode` column says what one notice does to it:

- `yes`: the code always sets `degraded_mode`;
- `no`: it never does;
- `conditional`: it depends on the message (only `BASIS_RECONCILED`).

The severity column gives the severity the shipped engine emits the code with.

| name | number | severity | degraded_mode | meaning |
|---|---|---|---|---|
| `NOTICE_CODE_NO_EVIDENCE` | 1 | info | no | Retrieval completed and matched nothing. The answer abstains unless model-only answers are allowed. |
| `NOTICE_CODE_GRAPH_TIMEOUT` | 2 | info | yes | The graph context node timed out. The answer is built from source chunks only. |
| `NOTICE_CODE_GRAPH_DEGRADED` | 3 | info | yes | The graph context node failed for a reason other than a timeout. The answer is built from source chunks only. |
| `NOTICE_CODE_MODEL_NOTICE` | 4 | info | no | A notice the model itself reported in its output, passed through. |
| `NOTICE_CODE_MODEL_WARNING` | 5 | warning | no | A warning the model itself reported in its output, passed through. |
| `NOTICE_CODE_GRAPH_UNAVAILABLE` | 10 | info | yes | Graph context was asked for but produced nothing: the graph query returned no facts for this query, or no graph is configured. The answer is built from source chunks only. |
| `NOTICE_CODE_RETRIEVAL_DEGRADED_DENSE` | 11 | info | yes | The dense (vector) retrieval path failed. The other paths still ran. |
| `NOTICE_CODE_CITATION_REPAIRED` | 12 | info | no | A citation marker in the answer did not equal an evidence id exactly, but normalised onto exactly one evidence block the model saw, and was rewritten to that id. |
| `NOTICE_CODE_CITATION_DROPPED` | 13 | info | yes | A citation marker matched no evidence block the model saw, or more than one, and was removed from the answer and its citations. |
| `NOTICE_CODE_MODEL_ONLY` | 14 | info | yes | The answer came from the model's own knowledge without corpus evidence. Only possible when model-only answers are allowed. |
| `NOTICE_CODE_BASIS_RECONCILED` | 15 | info | conditional | The model's self-reported answer basis disagreed with what the engine observed, and the engine kept the more conservative basis. It sets `degraded_mode` unless its message is exactly the grounded-abstention normalisation notice (`GROUNDED_ABSTENTION_NORMALISED_NOTICE`): an "Insufficient information" answer that cites the evidence it checked, whose basis the engine normalised to retrieval (06.3.6 D-158 IN-02). |
| `NOTICE_CODE_RETRIEVAL_DEGRADED_BM25` | 16 | info | yes | The BM25 (lexical) retrieval path failed. The other paths still ran. |
| `NOTICE_CODE_GRAPH_ABLATION` | 18 | info | no | Graph context is off because the request sent `disable_graph_context: true`. |
| `NOTICE_CODE_RETRIEVAL_FAILED` | 19 | error | yes | The retrieval node failed rather than completed (06-CONTEXT D-28). The "completed but matched nothing" case keeps `NO_EVIDENCE`. |
| `NOTICE_CODE_INDEX_REBUILD_FAILED` | 20 | warning | yes | The last index rebuild failed, so the engine is serving the prior index generation. |
| `NOTICE_CODE_INDEX_STALE` | 21 | not emitted | yes | Declared for Phase 6.1 (06-CONTEXT D-24, D-25). The shipped engine does not emit it. |
| `NOTICE_CODE_INDEX_GENERATION_MISMATCH` | 22 | not emitted | yes | Declared for Phase 6.1 (06-CONTEXT D-24, D-25). The shipped engine does not emit it. |
| `NOTICE_CODE_RERANK_DEGRADED` | 23 | info | yes | The `rerank` lever's reranker was attempted and failed, and the fused order was kept (06.3.6 D-134). |
| `NOTICE_CODE_DEFAULT_LEVER_UNAVAILABLE` | 24 | warning | yes | A configured default lever was dropped from a request that named no lever, because this engine lacks its resource (06.3.6 D-194). One notice per dropped lever. |
| `NOTICE_CODE_GRAPH_DISABLED_BY_CONFIG` | 25 | info | no | Graph context did not run because the request left `disable_graph_context` absent and the configured default (`[engine.graph] context_default_enabled = false`) is off (06.4 D-207). |

`degraded_mode` is true whenever `answer_basis` is not `retrieval`, whatever the notices say: a `mixed` or
`model_only` answer is degraded even with no notice in the `yes` column. This is the early return in
`derive_degraded_mode`.

**Values that are not codes.** 17 is reserved. In-fusion graph retrieval would have used it, and it is unreachable
because hybrid retrieval holds no graph port; a reserved number is never reused. 6-9 are unused and not reserved. They
are a gap left between the codes that existed before Phase 6 and the Phase 6 block, and a later code may take one.
`NOTICE_CODE_UNSPECIFIED` (0) is the proto3 zero value and is never emitted.

**The `DEFAULT_LEVER_UNAVAILABLE` message.** Its message names the lever and gives a fixed reason phrase, which names
no server configuration key (06.4 D-204 IN-03; `lever_unavailable_notice_text` in
[`engine/src/service.rs`](../engine/src/service.rs)). The message reads
`configured default lever <name> was not applied: <phrase>`, with these phrases:

| lever | phrase |
|---|---|
| `rerank` | `rerank provider not configured` |
| `evidence_metadata` | `the index holds no document metadata` |
| `graph_v2` | `graph v2 chunk selection not enabled` |

The engine's startup log gives the operator-facing reason and remedy for the same lever. That text is server-side only.

**`GRAPH_ABLATION` versus `GRAPH_DISABLED_BY_CONFIG`.** Both mean "the graph context node returned early and the
answer used source chunks only". Both are informational and both are outside the `degraded_mode` set. They differ only
in who decided:

- `GRAPH_ABLATION` (18): the caller, with `disable_graph_context: true`. Its message is
  `Graph context disabled by caller request`, byte for byte as before Phase 06.4, so the evaluation's ablation arms
  are unchanged.
- `GRAPH_DISABLED_BY_CONFIG` (25): the configuration, for a request that left the field absent. Its message is
  `Graph context disabled by configured default`.

`GRAPH_UNAVAILABLE` (10) is different: the graph was on and produced nothing, which is a degradation.

**`RETRIEVAL_FAILED`.** Code 19, severity error, is added when the hybrid retrieval node itself fails (a timeout or an
error, but not a cancellation). Its message names the error kind and the error text. A request whose retrieval
completed with zero results gets `NO_EVIDENCE` (1) instead, so a client can tell "the corpus has nothing" from "the
search did not run".

**Which notice list to read.** Over HTTP, notices reach a client in up to two places, and the gateway never fills
both for one request:

- The `final_answer` event carries the answer and its `notices`. When the workflow produced an answer, the terminal
  `workflow_completed` event also carries the same response under `final_response`.
- When there is no final response, `workflow_completed` carries a top-level `notices` list instead.

So the authoritative list is the response's `notices` when a final response exists (`final_answer`, or
`workflow_completed.final_response`), and `workflow_completed.notices` only when it does not. Never merge the two.
`degraded_mode` is in `workflow_completed.metadata`. This is the precedence the evaluation harness uses
(`eval/src/lancet_eval/client.py`), and it was fixed in Phase 6 (`06-AI-SPEC.md`, "Notice-list precedence").

## The bad-input matrix

Phase 6 enumerated the bad-input surface of `query_rag` as a table-driven matrix (06-CONTEXT D-15, `DEBT-RAG-05`).
Plan 06-12 wrote the table as the `//!` header of
[`engine/src/tests/bad_input_matrix.rs`](../engine/src/tests/bad_input_matrix.rs), and `06-12-SUMMARY.md` designates
that header as the table Phase 6.4 publishes. It is reproduced here verbatim from commit `83c37f9`, the plan 06-12
commit that created it. Every row is driven over gRPC by `bad_input_matrix_rejects_and_dispositions_are_stable` and
over HTTP by `TestBadInputMatrixHTTP` in `gateway/main_test.go`, where each rejecting row is a 400 with the error kind
in `X-Lancet-Error-Kind`.

| Row | Input class | Status | Error kind | Reason (non-rejection rows only) |
|---|---|---|---|---|
| `empty_query` | empty query string | `InvalidArgument` | `empty_query` | — |
| `whitespace_only_query` | whitespace-only query | `InvalidArgument` | `empty_query` | — |
| `query_too_long` | query exceeding the configured `query_max_bytes` bound | `InvalidArgument` | `query_too_long` | — |
| `malformed_session_id` | syntactically invalid session id | `InvalidArgument` | `invalid_session_id` | — |
| `wrong_version_session_id` | syntactically valid UUID, wrong version/variant | `InvalidArgument` | `invalid_session_id` | — |
| `invalid_document_id` | malformed document id inside the filter | `InvalidArgument` | `invalid_document_id` | — |
| `unsupported_content_type` | unsupported content type inside the filter | `InvalidArgument` | `unsupported_content_type` | — |
| `empty_filter_value` | empty/whitespace-only document-id filter value | `InvalidArgument` | `empty_filter_value` | — |
| `filter_limit_exceeded_document_ids` | `document_ids` filter exceeds the configured count bound | `InvalidArgument` | `filter_limit_exceeded` | — |
| `filter_limit_exceeded_content_types` | `content_types` filter exceeds the configured count bound | `InvalidArgument` | `filter_limit_exceeded` | — |
| `unmatched_filter` | a well-formed, valid UUIDv4 `document_ids` filter that names no ingested document | success (not rejected) | n/a | Phase 03 shipped a valid zero-match success branch (the `NO_EVIDENCE` notice); rejecting this would contradict shipped behavior and would remove the abstention signal Phase 6.3's scoring depends on. |
| `contradictory_filter` | `document_ids` names the one ingested document but `content_types` names a type it does not have, so no candidate can satisfy both constraints at once | success (not rejected) | n/a | No rejection rule exists in the codebase for a document/content-type combination that cannot both be satisfied, and none is added here; it behaves identically to the unmatched case. |

The same header records why there is no "negative filter bound" row. `DocumentFilter` carries only two lists of strings,
so a caller cannot put a negative number on the request. The numeric bounds are configuration, validated at startup and
reported as `invalid_settings` (an internal status, because it is an operator error, not a caller error).

### Rows added since Phase 6

Later phases added rows to the same header as they added request fields. These rows are read from the current
`bad_input_matrix.rs` header, verbatim:

| Row | Input class | Status | Error kind | Reason (non-rejection rows only) |
|---|---|---|---|---|
| `invalid_retrieval_mode` | `retrieval_mode` integer outside the four known `RetrievalMode` values (99) | `InvalidArgument` | `invalid_retrieval_mode` | — |
| `negative_retrieval_mode` | negative `retrieval_mode` integer (-1) | `InvalidArgument` | `invalid_retrieval_mode` | — |
| `retrieval_mode_unspecified_admitted` | `retrieval_mode` 0 (the default), unmatched filter | success (not rejected) | n/a | Every known mode value is admitted; the zero-match filter keeps the row independent of corpus content. |
| `retrieval_mode_hybrid_admitted` | `retrieval_mode` 1, unmatched filter | success (not rejected) | n/a | As above. |
| `retrieval_mode_dense_only_admitted` | `retrieval_mode` 2, unmatched filter | success (not rejected) | n/a | As above. |
| `retrieval_mode_bm25_only_admitted` | `retrieval_mode` 3, unmatched filter | success (not rejected) | n/a | As above. |
| `invalid_lever` | `levers` holds an integer outside the declared `Lever` values (99) | `InvalidArgument` | `invalid_levers` | — |
| `negative_lever` | `levers` holds a negative integer (-1) | `InvalidArgument` | `invalid_levers` | — |
| `duplicate_lever` | `levers` names `binary_answer_format` twice | `InvalidArgument` | `invalid_levers` | — |
| `lever_unspecified_member` | `levers` holds `LEVER_UNSPECIFIED` (0) | `InvalidArgument` | `invalid_levers` | — |
| `lever_unavailable_rerank` | `levers` names `rerank` and this service holds no lever reranker (D-131; `levers_pins` admits it once one is wired) | `InvalidArgument` | `lever_unavailable` | — |
| `lever_unavailable_evidence_metadata` | `levers` names `evidence_metadata` while the snapshot's `DocMetaMap` is empty (D-136; the `levers_metadata_admitted` check below admits it once the snapshot holds metadata) | `InvalidArgument` | `lever_unavailable` | — |
| `lever_unavailable_graph_v2` | `levers` names `graph_v2` while `[engine.graph] graph_v2_chunk_precision` is held at the no-op `all` by the test (D-139, D-154: the shipped default is the frozen `edge_evidence`; the `levers_graph_v2_admitted` check below admits it once a variant is configured) | `InvalidArgument` | `lever_unavailable` | — |
| `lever_unavailable_when_mixed_with_an_available_lever` | `levers` names `binary_answer_format` and `rerank` with no lever reranker wired | `InvalidArgument` | `lever_unavailable` | — |
| `graph_v2_with_graph_disabled` | `levers` names `graph_v2` and `disable_graph_context` is true (D-165) | `InvalidArgument` | `invalid_lever_combination` | — |
| `levers_admitted` | `levers` names `binary_answer_format`, unmatched filter | success (not rejected) | n/a | `binary_answer_format` needs no resource and is admitted; the zero-match filter keeps the row independent of corpus content. |
| `levers_metadata_admitted` | `levers` names `evidence_metadata`, unmatched filter, after the service's snapshot is replaced by one whose `DocMetaMap` holds an entry | success (not rejected) | n/a | Run after the table above, on the same service, so the one request is refused on the empty map and admitted on the non-empty one. |
| `levers_graph_v2_admitted` | `levers` names `graph_v2`, unmatched filter, after the service's `graph_v2_chunk_precision` is set to `edge_evidence` | success (not rejected) | n/a | Run after the two checks above, on the same service, so the one request is refused on the no-op `all` and admitted once a variant is configured; with `disable_graph_context` it is still refused as `invalid_lever_combination` (D-165). |
| `graph_v2_with_graph_default_off` | `levers` names `graph_v2`, `disable_graph_context` is absent and `[engine.graph] context_default_enabled` is false (06.4 D-207, D-84: the combination check reads the graph state resolved at admission) | `InvalidArgument` | `invalid_lever_combination` | — |
| `levers_default_degraded` | `[engine.levers] defaults` names `rerank` and `evidence_metadata`, the request names no lever, and this service holds no lever reranker (D-157, D-194) | success (not rejected) | n/a | Run after the checks above, on the same service: the unavailable default is dropped, never refused. The echo lists only the lever that ran (`evidence_metadata`), and the response carries one DEFAULT_LEVER_UNAVAILABLE notice (typed code 24) naming `rerank`. |
| `levers_default_admitted` | the same defaults; a request that names `binary_answer_format` is admitted with the defaults unused, and a request that names no lever echoes both defaults and carries no code-24 notice once a lever reranker is wired (D-157, D-194) | success (not rejected) | n/a | Run last, on the same service, so the one request degrades without the reranker and runs both defaults with it. |

The unprefixed D-IDs in these rows from D-131 to D-194 are 06.3.6 decisions, and D-84 is 06-CONTEXT's fail-closed
configuration rule. Over HTTP, the `retrieval_mode` and lever-name rows above that the gateway
can express are refused by the gateway first, as described in [Refusals](#refusals).

## Related pages

- The [README](../README.md): what Lancet is and how to run it.
- The [observability walkthrough](observability.md): one request followed through its spans, including the notices
  above as they appear in a trace.
- The [evaluation results](evaluation.md): the measured value and cost of the levers and the graph.
- The [design narrative](design-narrative.md): why the contract has typed notices and fails closed.
