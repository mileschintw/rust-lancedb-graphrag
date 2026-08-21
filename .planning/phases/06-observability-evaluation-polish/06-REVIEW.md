---
phase: 06-observability-evaluation-polish
reviewed: 2026-08-21T00:00:00Z
depth: standard
files_reviewed: 57
files_reviewed_list:
  - README.md
  - config/config.toml
  - engine/src/bin/seed_rag_fixture.rs
  - engine/src/chunker/mod.rs
  - engine/src/client/mod.rs
  - engine/src/client/tests.rs
  - engine/src/config.rs
  - engine/src/db/mod.rs
  - engine/src/db/tests.rs
  - engine/src/generation/citations.rs
  - engine/src/generation/mod.rs
  - engine/src/generation/openrouter.rs
  - engine/src/generation/tests.rs
  - engine/src/graph/bridge.rs
  - engine/src/graph/context_strategy.rs
  - engine/src/graph/extraction.rs
  - engine/src/graph/mod.rs
  - engine/src/graph/tests.rs
  - engine/src/ingest.rs
  - engine/src/lib.rs
  - engine/src/main.rs
  - engine/src/pb/lancet/v1/lancet.v1.rs
  - engine/src/prompt.rs
  - engine/src/retrieval/bm25.rs
  - engine/src/retrieval/fusion.rs
  - engine/src/retrieval/mod.rs
  - engine/src/retrieval/tests.rs
  - engine/src/service.rs
  - engine/src/testkit.rs
  - engine/src/tests.rs
  - engine/src/tests/bad_input_matrix.rs
  - engine/src/tests/workflow_phase5.rs
  - engine/src/tests/workflow_phase5_production.rs
  - engine/src/workflow/events.rs
  - engine/src/workflow/mod.rs
  - engine/src/workflow/node.rs
  - engine/src/workflow/nodes/assemble_prompt.rs
  - engine/src/workflow/nodes/generate.rs
  - engine/src/workflow/nodes/graph_context.rs
  - engine/src/workflow/nodes/mod.rs
  - engine/src/workflow/nodes/reformulate.rs
  - engine/src/workflow/nodes/retrieve.rs
  - engine/src/workflow/ports.rs
  - engine/src/workflow/runner.rs
  - engine/tests/config_startup.rs
  - gateway/internal/config/config.go
  - gateway/internal/engineclient/engineclient.go
  - gateway/internal/sse/dto.go
  - gateway/internal/sse/sse.go
  - gateway/internal/sse/sse_test.go
  - gateway/internal/telemetry/telemetry.go
  - gateway/main.go
  - gateway/main_test.go
  - gateway/proto/lancet/v1/lancet.pb.go
  - proto/lancet/v1/lancet.proto
  - scripts/engine-test-targets.sh
  - scripts/gateway-test-targets.sh
findings:
  critical: 5
  warning: 13
  info: 0
  total: 18
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-08-21
**Depth:** standard
**Files Reviewed:** 57
**Status:** issues_found

## Summary

Reviewed the Phase 6 product-source scope: the Rust module-graph restructure, the Go gateway
package split, the consolidated additive protobuf change, and the RAG-03 degraded-mode
hardening (model-only opt-in, degrade-and-continue retrieval, citation repair, bad-input
matrix, GRAPH_UNAVAILABLE notices).

**What holds up.**

*Protobuf additivity is clean.* `proto/lancet/v1/lancet.proto` adds only new tags
(`QueryRAGRequest` 4/5, `Notice` 4, `WorkflowCompletedEvent` 7, `WorkflowMetadata` 1-10,
`NoticeCode` 10-22 with 17 explicitly `reserved`). No tag is renumbered or reused, and both
generated bindings (`engine/src/pb/lancet/v1/lancet.v1.rs`,
`gateway/proto/lancet/v1/lancet.pb.go`) agree with the source on every tag and enum value.

*The `allow_model_only` precedence chain is correct.* `optional bool` gives real field
presence; `service.rs:824` resolves request → config → `false`; the config default
(`config.rs:140-142`) and the shipped `config/config.toml` are both `false`; the env override
fails closed on unparseable values (`config.rs:652-665`), and `engine/tests/config_startup.rs`
pins all three. No path defaults it to true.

*Retrieval degrade-and-continue does not fabricate grounding.* A failed dense or BM25 path
degrades to an empty candidate list with a typed notice, the zero-evidence path emits
`NOTICE_CODE_NO_EVIDENCE`, and `runner.rs:419-428` skips AssemblePrompt/GenerateAnswer, so
`answer_basis = RETRIEVAL` with no evidence is not reachable that way.

**Where it breaks.** Five critical defects, concentrated in the two newest subsystems.

The headline one is CR-02: **the model-only opt-in cannot produce an answer in production at
all.** When it is enabled and evidence is empty, the provider adapter unconditionally calls
`pack_evidence_and_graph_prompt`, which returns `EmptyEvidence` on an empty evidence slice, so
the run fails before the model is ever contacted. `pack_model_only_prompt` — the function the
phase added for this path — is written into `ctx.assembled_prompt` and then read by nothing
except the checkpoint serializer. The feature is dead on the wire, and the test that covers it
passes only because it disables grounding limits and uses a fake that ignores the prompt.

Alongside that: citation repair fails valid answers whenever the same evidence is cited twice
(CR-01) while simultaneously opening a hole in the model-only opt-out (CR-03); the engine's
declarative environment-override source is misconfigured and silently matches no documented
variable, so most config keys cannot be overridden at all (CR-04); and the new
`WorkflowMetadata`/`degraded_mode` observability channel is never populated while the gateway
zero-fills it into an actively false report (CR-05).

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Citation repair fails the entire run when the same evidence is cited twice

**File:** `engine/src/workflow/nodes/generate.rs:185-231` (with `engine/src/generation/mod.rs:320-329`)

**Issue:** With repair enabled (the shipped default — `config.rs:143-145`,
`config/config.toml`), `repaired_citations` is built with **one entry per extracted marker
occurrence**, not per distinct evidence id:

```rust
for outcome in &outcomes {
    match &outcome.resolution {
        Resolution::Unchanged(id) => { repaired_citations.push(id.clone()); }
        Resolution::Repaired(id)  => { repaired_citations.push(id.clone()); ... }
        Resolution::Dropped => { ... }
    }
}
```

That list is then handed to `validate_grounding_with_limits`, which rejects duplicates:

```rust
let mut seen_cited = HashSet::new();
for id in &self.cited_evidence_ids {
    if !seen_cited.insert(id.as_str()) {
        return Err(... format!("cited_evidence_ids contains duplicate ID '{id}'"));
    }
}
```

Two independent reproductions, both extremely common in real model output:

1. **Repeated marker** — answer `"Per [1] ... and [1] also states ..."`, evidence `["[1]"]` →
   two `Unchanged("[1]")` outcomes → `["[1]", "[1]"]` → duplicate → run fails with
   `NODE_ERROR_KIND_LLM_GENERATION_FAILED`.
2. **Mixed spellings** — answer containing both `[ 7 ]` and `[7]`, evidence `["[7]"]` → one
   `Repaired("[7]")` plus one `Unchanged("[7]")` → same duplicate failure. This case is
   exactly what the widened extractor (`generation/citations.rs:82-118`) was added to catch,
   so repair converts its own target case into a hard failure.

This is a **regression against the pre-D-14 path**: with `citation_repair_enabled = false`
(`generate.rs:311-371`), `cited_evidence_ids` comes from the model's JSON list and inline
markers are compared as a `HashSet` (`generation/mod.rs:344-357`), so a repeated marker
passed. No test in `engine/src/tests/workflow_phase5.rs:5805-6010` exercises a repeated or
mixed-spelling marker — every repair test uses distinct markers.

**Fix:** Deduplicate at construction, preserving first-occurrence order, before validation:

```rust
Resolution::Unchanged(id) | Resolution::Repaired(id) => {
    if !repaired_citations.iter().any(|existing| existing == id) {
        repaired_citations.push(id.clone());
    }
    // keep the per-occurrence span edit / notice logic unchanged
}
```

Fixing this only downstream is not sufficient: `resolve_citations_with_max_chars`
(`engine/src/prompt.rs:576-614`) also does not deduplicate, so a naive fix elsewhere would
convert "run fails" into "duplicate `StructuredCitation` entries on the wire."

---

### CR-02: The model-only opt-in fails 100% of the time in production; `pack_model_only_prompt` never reaches the provider

**File:** `engine/src/generation/openrouter.rs:477-495, 504, 521-524`, `engine/src/prompt.rs:334-340, 215-217`, `engine/src/workflow/nodes/assemble_prompt.rs:70-79`, `engine/src/workflow/nodes/generate.rs:102-108`

**Issue:** Trace an actual model-only run — `allow_model_only = true`, retrieval returned zero
evidence — from the workflow to the wire.

1. `AssemblePromptNode` takes its new empty-evidence branch and sets
   `ctx.assembled_prompt = pack_model_only_prompt(&ctx.original_query)`
   (`assemble_prompt.rs:77`).
2. **Nothing ever reads `ctx.assembled_prompt` on the generation path.** Grepping the crate,
   its only non-test consumers are `workflow/mod.rs:266` (the test-only inline remainder) and
   `workflow/events.rs:229` (the checkpoint serializer). `GenerateAnswerNode::run` builds a
   fresh request from the raw query and evidence instead:
   `GenerationRequest::new(ctx.original_query.clone(), ctx.evidence_blocks.clone())`
   (`generate.rs:102-103`).
3. `OpenRouterGenerator::generate` then re-derives the prompt itself and calls, with no
   empty-evidence guard:

   ```rust
   let packed_evidence = pack_evidence_and_graph_prompt(
       &request.question, &request.evidence, /* ... */
   ).await.map_err(|err| match err {
       PromptAssemblyError::Cancelled => GenerationError::new(Cancelled, "prompt assembly cancelled"),
       _ => GenerationError::new(InvalidRequest, format!("prompt assembly failed: {err}")),
   })?;                                            // openrouter.rs:477-495
   ```

4. And `pack_evidence_and_graph_prompt` rejects an empty evidence slice outright:

   ```rust
   if evidence.is_empty() {
       return Err(PromptAssemblyError::EmptyEvidence);   // prompt.rs:338-340
   }
   ```

So every model-only run terminates with
`GenerationErrorKind::InvalidRequest — "prompt assembly failed: No evidence blocks provided
for prompt assembly"`, before the model is ever contacted. `InvalidRequest` is not in the
retryable set (`generate.rs:126-127`), so it converts straight to
`NodeError::new(NodeErrorKind::LlmGenerationFailed, ...)`. **The D-10/D-12 opt-in cannot
produce an answer.**

Two further defects sit behind this one, and each independently breaks the path even if the
`EmptyEvidence` guard is lifted:

* **The outbound JSON schema forbids the required basis.** `openrouter.rs:521-524` pins
  `"answer_basis": { "type": "string", "enum": ["retrieval", "mixed"] }` — `model_only` is not
  an allowed value, so a structured-output provider cannot return it. The result then fails
  `generation/mod.rs:210-220` (*"answer basis 'retrieval' requires at least one cited evidence
  ID"*) because `generate.rs:151-162` validates the **unmodified** output, not
  `into_model_only()`.
* **The prompt text contradicts the mode.** `pack_model_only_prompt` (`prompt.rs:215-217`) is
  just `base_system_policy()` + question, and that policy says *"Answer the user's question
  accurately using ONLY the provided evidence blocks"* and *"Cite evidence using numbered
  markers like [1], [2]"* (`prompt.rs:205-213`) — with no evidence blocks present. Any marker
  the model emits in response is then rejected by `generation/mod.rs:343-354` (*"inline marker
  '…' is not in packed evidence"*).

This is untested. `engine/src/tests/workflow_phase5.rs:5165-5200` is the model-only success
test, and it passes only because (a) it constructs
`GenerateAnswerNode::new(Some(fake_gen))` with no `.with_settings(...)`, leaving
`grounding_limits: None` so validation is skipped entirely, and (b) `FakeGenerator` never
touches `pack_evidence_and_graph_prompt` or the JSON schema. Production always sets limits
and always uses the real adapter (`service.rs:147-157`, `main.rs:95-97`).

**Fix (all four sites, or the feature stays dead):**

```rust
// 1. engine/src/generation/openrouter.rs — branch on empty evidence
let user_msg = if request.evidence.is_empty() {
    crate::prompt::pack_model_only_prompt(&request.question)
} else {
    pack_evidence_and_graph_prompt(/* ... as today ... */).await.map_err(/* ... */)?.prompt
};

// 2. engine/src/generation/openrouter.rs:521-524 — admit the basis the path must return
"answer_basis": { "type": "string", "enum": ["retrieval", "mixed", "model_only"] },
```

```rust
// 3. engine/src/prompt.rs — give the model-only path its own policy
fn model_only_system_policy() -> &'static str {
    "System Policy: You are a precise technical assistant. No corpus evidence was retrieved \
for this question. Answer from your own parametric knowledge only. Do NOT emit numbered \
citation markers such as [1]; there is no evidence to cite. Set answer_basis to \"model_only\" \
and leave cited_evidence_ids empty. State clearly that the answer is not grounded in the corpus."
}
pub fn pack_model_only_prompt(question: &str) -> String {
    format!("{}\n\nQuestion: {}\n", model_only_system_policy(), question)
}
```

4. Either have `GenerateAnswerNode` pass `ctx.assembled_prompt` through on the
   `GenerationRequest` so `AssemblePromptNode`'s output is load-bearing, or delete the
   assembled-prompt branch at `assemble_prompt.rs:77` and own prompt construction solely in
   the adapter — but not the current state, where the workflow builds a prompt the provider
   never sees.

Add a test that drives `GenerateAnswerNode` **with** `.with_settings(limits, …)` against a
generator that actually calls `pack_evidence_and_graph_prompt` on empty evidence.

---

### CR-03: The citation total-drop path yields `ANSWER_BASIS_MODEL_ONLY` with no `MODEL_ONLY` notice, against an explicit `allow_model_only_answers = false`

**File:** `engine/src/workflow/nodes/generate.rs:233-266`

**Issue:**

```rust
let total_drop = !markers.is_empty() && repaired_citations.is_empty();
...
let effective_allow = ctx.allow_model_only || total_drop;
let limits = limits.with_allow_model_only(effective_allow);
```

The `|| total_drop` disjunction is deliberate (the comment above it says so), so the issue is
not that it exists — it is the two consequences that are not defensible as design:

1. **The typed notice contract is broken.** Both routes to `answer_basis = MODEL_ONLY` end at
   the same client-visible value, but only the `should_treat_as_model_only` branch emits
   `NoticeCode::ModelOnly` (`generate.rs:166-170`). The total-drop route emits
   `CITATION_DROPPED` plus `BASIS_RECONCILED` (via `workflow/mod.rs:184-195`) and **never**
   `MODEL_ONLY`. A client filtering on `typed_code == NOTICE_CODE_MODEL_ONLY` — the exact use
   case the Phase 6 enum was added for — silently misses an ungrounded answer.
2. **An operator's opt-out is not honored.** `config.rs:164-169` documents
   `allow_model_only_answers` as *"Whether model-only answers are allowed … Defaults to
   false."* An operator who sets it to `false` (and a caller who sends
   `allow_model_only: false`) still receives a model-only answer any time the model emits
   markers that cannot be resolved — which, with evidence present, means an answer whose every
   citation was hallucinated. Before D-14 this hard-failed.

Confirmed by the shipped test: `workflow_phase5.rs:5845-5876`
(`citation_repair_enabled_drops_unresolvable_marker_and_emits_notice`) runs with
`ctx.allow_model_only == false` and non-empty evidence, and asserts `res.is_ok()` with empty
citations.

**Fix:** Emit the notice on both routes and gate the opt-out honestly. At minimum:

```rust
if total_drop {
    ctx.add_notice(crate::workflow::notice(
        crate::pb::lancet::v1::NoticeCode::ModelOnly,
        "All citation markers were unresolvable; the answer retains no corpus grounding.",
        crate::pb::lancet::v1::NoticeSeverity::Warning,
    ));
}
```

and, when `!ctx.allow_model_only`, either fail the node (pre-D-14 behavior) or make the
total-drop relaxation a separate, explicitly named configuration key rather than an implicit
override of `allow_model_only_answers`.

---

### CR-04: The engine's declarative environment-override source matches no documented variable

**File:** `engine/src/config.rs:600`

**Issue:**

```rust
.add_source(::config::Environment::with_prefix("LANCET").separator("__"))
```

In `config` 0.15.25 (`env.rs`), when `prefix_separator` is not set explicitly it **falls back
to the key separator**:

```rust
let prefix_separator = match (self.prefix_separator.as_deref(), self.separator.as_deref()) {
    (Some(pre), _) => pre,
    (None, Some(sep)) => sep,     // <-- taken here: "__"
    (None, None) => "_",
};
let prefix_pattern = self.prefix.as_ref().map(|p| format!("{p}{prefix_separator}").to_lowercase());
```

So the required prefix is `lancet__`, not `lancet_`. Every variable this project actually uses
and documents — `LANCET_ENGINE__GRPC_ADDR`, `LANCET_OPENROUTER__CHAT_ENDPOINT`, etc. —
lowercases to `lancet_engine__…`, fails `key.starts_with("lancet__")`, and is **skipped
entirely**. The declarative source is dead: it contributes nothing on any supported variable.

The consequence is not cosmetic. Environment overrides work *only* for the hand-written
allowlist at `config.rs:607-714`, and any key outside it is silently dropped with no warning
and no error. Currently unreachable by environment:
`engine.retrieval.candidate_limit`, `final_limit`, `query_max_bytes`, `max_document_ids`,
`max_content_types`, `vector_weight`, `bm25_weight`, `graph_weight`, `rrf_k`,
`excerpt_max_chars`, all of `engine.retrieval.bm25.*`, `engine.graph.seed_match_min_score`,
`engine.graph.max_hop_cap`, `openrouter.generation_timeout_secs`, `openrouter.temperature`,
`openrouter.top_p`. An operator who exports `LANCET_ENGINE__RETRIEVAL__CANDIDATE_LIMIT=64`
gets a clean startup and the old value.

This also explains why the manual block exists at all, and why
`engine/tests/config_startup.rs` only ever asserts variables that appear in that block — the
tests pin the allowlist, not the mechanism, so the misconfiguration is invisible to CI. (The
Go gateway does this correctly: `gateway/internal/config/config.go:37-42` uses viper's
`SetEnvPrefix("LANCET")` with a `"." -> "__"` replacer, yielding `LANCET_GATEWAY__PORT`.)

**Fix:** Set the prefix separator explicitly, then reduce the hand-written block to the two
bool validators that fail closed on non-boolean text:

```rust
.add_source(
    ::config::Environment::with_prefix("LANCET")
        .prefix_separator("_")
        .separator("__"),
)
```

**Caution for the fixer:** turning this source on makes every `LANCET_*` variable in the
environment a live config input, and `WorkflowConfigSettings` carries
`#[serde(deny_unknown_fields)]` (`config.rs:148`). A stray or misspelled
`LANCET_ENGINE__WORKFLOW__*` variable that is silently ignored today will hard-fail startup
after the fix — verify against the deployment environment, and consider whether the same
`deny_unknown_fields` should be added to `Settings`/`OpenRouterSettings` for consistency.

Add an integration test in `engine/tests/config_startup.rs` for a key that is *not* in the
manual allowlist (e.g. `LANCET_ENGINE__RETRIEVAL__CANDIDATE_LIMIT`) so the mechanism itself is
pinned rather than the allowlist.

---

### CR-05: `degraded_mode` is reported as `false` on every run, including degraded ones

**File:** `engine/src/workflow/events.rs:365-374` and `gateway/internal/sse/sse.go:108-136`

**Issue:** The engine hardcodes the new `WorkflowMetadata` field to absent:

```rust
Event::WorkflowCompleted(WorkflowCompletedEvent {
    ...
    metadata: None,      // events.rs:372 — never set to Some(..) anywhere in the crate
})
```

The gateway then converts *absent* into a fully zero-filled object rather than omitting it:

```go
} else {
    metaMap = map[string]any{
        ...
        "degraded_mode":      false,   // sse.go:133
    }
}
wcPayload["metadata"] = metaMap
```

So on exactly the runs Phase 6 built this channel for — a run carrying
`RETRIEVAL_DEGRADED_DENSE`, `RETRIEVAL_DEGRADED_BM25`, `GRAPH_DEGRADED`, `GRAPH_TIMEOUT`,
`GRAPH_UNAVAILABLE`, or `NO_EVIDENCE` — the observability payload asserts
`"degraded_mode": false`. The engine half makes the field dead; the gateway half makes it
actively wrong, and a consumer cannot distinguish "not degraded" from "the engine never told
me." `proto/lancet/v1/lancet.proto:241-242` calls `degraded_mode` "DERIVED, never
independently set", but no derivation exists anywhere. `gateway/internal/sse/sse_test.go`
contains no assertion on `metadata` or `degraded_mode`, so this is an unnoticed gap rather
than a pinned decision.

**Fix (both halves).** Engine — derive it in `runner.rs::emit_terminal_once` using the
comparison idiom already used at `runner.rs:424` and `bad_input_matrix.rs:328`:

```rust
const DEGRADED_CODES: [NoticeCode; 8] = [
    NoticeCode::NoEvidence, NoticeCode::GraphTimeout, NoticeCode::GraphDegraded,
    NoticeCode::GraphUnavailable, NoticeCode::RetrievalDegradedDense,
    NoticeCode::RetrievalDegradedBm25, NoticeCode::ModelOnly, NoticeCode::CitationDropped,
];
let degraded_mode = ctx.notices.iter().any(|n| {
    DEGRADED_CODES.iter().any(|code| n.typed_code == *code as i32)
});
// build and pass Some(WorkflowMetadata { degraded_mode, vector_count, bm25_count, .. })
// through events::workflow_completed instead of the hardcoded `metadata: None`.
```

Gateway — drop the zero-filling `else` branch so absent metadata omits the key instead of
claiming a value:

```go
if meta := e.WorkflowCompleted.GetMetadata(); meta != nil {
    wcPayload["metadata"] = map[string]any{ /* ... as today ... */ }
}
```

---

## Warnings

### WR-01: `run_inline_prompt_generation_remainder` is a public generation path with no grounding validation

**File:** `engine/src/workflow/mod.rs:249-363` (and `engine/src/workflow/runner.rs:445-495`)

**Issue:** Both `run_inline_prompt_generation_remainder` and `WorkflowRunner::run_tracer` are
`pub` on the library crate (not `#[cfg(test)]`), but the remainder function never calls
`validate_grounding_with_limits`, never runs the D-14 repair pass, and never populates
`ctx.structured_citations` — it just calls `ctx.update_from_model_output(&output)`
(`mod.rs:310`). It also carries its own divergent copy of the model-only rule
(`mod.rs:311-323`, `ctx.allow_model_only && (evidence empty || basis == ModelOnly)`) versus
`ModelOutput::should_treat_as_model_only`. Today only tests call it, but as a published API it
is a ready-made fail-open path, and it has already drifted from `GenerateAnswerNode`.

**Fix:** Mark both `#[cfg(test)]` (or move them into a `testkit`-style module), or make the
remainder delegate to `GenerateAnswerNode::run` so there is exactly one generation seam.

### WR-02: Successful zero-evidence responses carry `ANSWER_BASIS_UNSPECIFIED`

**File:** `engine/src/workflow/runner.rs:419-428` with `engine/src/workflow/mod.rs:150-160`

**Issue:** When retrieval yields no evidence and `allow_model_only` is false, the runner
`break`s with `overall_err = None`, so `emit_terminal_once` takes the success branch and
`to_query_rag_response()` serializes `answer_basis: AnswerBasis::Unspecified as i32` — proto
enum value `0`, the "unset" sentinel — inside a `success: true` response. (The success
disposition itself is intended and pinned by `tests/bad_input_matrix.rs:274-299`; only the
basis value is at issue.) A client cannot distinguish "the engine deliberately abstained" from
"this field was never populated by an older peer."

**Fix:** Make the abstention an explicit contract rather than an accident. The lowest-risk
option, given the phase's additive-only protobuf constraint, is to document it at the source:
amend the `AnswerBasis` comment in `proto/lancet/v1/lancet.proto:101-106` to state that
`ANSWER_BASIS_UNSPECIFIED` on a `success: true` response paired with
`NOTICE_CODE_NO_EVIDENCE` is the defined abstention signal, and assert that pairing in the
bad-input matrix rows that already exercise it.

### WR-03: Dead `_disable_graph_context` binding with a comment implying it is load-bearing

**File:** `engine/src/service.rs:763-764`

**Issue:**

```rust
// Resolved once at admission; Phase 6 adds no configuration key for this flag.
let _disable_graph_context = req.disable_graph_context.unwrap_or(false);
```

The value is computed and immediately discarded. The flag does work, but via a completely
different route (`WorkflowContext::new` at `workflow/mod.rs:114`, consumed at
`workflow/nodes/graph_context.rs:96-105`). The dead binding plus its "Resolved once at
admission" comment reads as the admission-time resolution point, inviting a future edit here
that has no effect.

**Fix:** Delete the binding; move the comment to `WorkflowContext::new`, where the resolution
actually happens.

### WR-04: Dead public constants duplicate the derived notice-code strings

**File:** `engine/src/workflow/mod.rs:27-28`

**Issue:** `pub const GRAPH_TIMEOUT: &str = "GRAPH_TIMEOUT";` and `GRAPH_DEGRADED` have zero
references in the crate (verified by grep across `engine/`). They are now a second, unenforced
source of truth for strings that `notice()` (`mod.rs:35-46`) derives from
`NoticeCode::as_str_name()` — exactly the duplication D-76 set out to remove.

**Fix:** Delete both constants.

### WR-05: The gateway's blank telemetry import does nothing

**File:** `gateway/main.go:36`, `gateway/internal/telemetry/telemetry.go:6-8`

**Issue:** `_ "github.com/lancet/gateway/internal/telemetry"` is a blank import for side
effects, but the package has no `func init()` — its only symbol is `Init() error`, which is
never called from anywhere in `gateway/`. The import compiles and reads as "telemetry is
wired," while nothing is initialized and `Init`'s error return is never observed.

**Fix:** Either call it explicitly in `run()` and handle the error, or drop the blank import
until Phase 6.2 lands:

```go
if err := telemetry.Init(); err != nil {
    logger.Error("init telemetry", zap.Error(err))
    return err
}
```

### WR-06: The gateway silently drops two `RetrievalSnapshot` fields

**File:** `gateway/internal/sse/dto.go:46-57, 121-131`

**Issue:** `RetrievalSnapshotDTO` has no fields for `variant_count` (proto tag 10) or
`variant_identities` (tag 11), and `ToQueryRAGResponseDTO` does not map them. The engine
populates both (`engine/src/workflow/nodes/retrieve.rs:225-226`), so multi-variant retrieval
provenance is produced and then thrown away at the HTTP boundary — the opposite of what a
provenance snapshot is for, in an observability phase.

**Fix:** Add `VariantCount uint32 \`json:"variant_count"\`` and
`VariantIdentities []string \`json:"variant_identities"\`` to the DTO and map them, using the
same non-nil `make([]string, 0)` convention already applied to `Citations`.

### WR-07: Checkpoint snapshots lost the typed notice code and two new context fields, while their doc claims completeness

**File:** `engine/src/workflow/events.rs:111-127, 163-208`

**Issue:** `CheckpointNotice` carries only `code`, `message`, `severity` — the Phase 6
`typed_code` (proto `Notice` tag 4) is dropped, so a replayed checkpoint cannot reconstruct
the notice the wire carried. Separately, `CheckpointSnapshot`'s doc comment states *"Every
field is emitted, including empty or absent values"*, but the two new `WorkflowContext` fields
`disable_graph_context` and `allow_model_only` (`workflow/mod.rs:85, 89`) are absent, and
`CHECKPOINT_SNAPSHOT_KEYS` is still `[&str; 19]`. Debugging a model-only or graph-ablated run
from a checkpoint cannot tell which mode it ran in.

**Fix:** Add `typed_code: i32` to `CheckpointNotice`, add both booleans to `CheckpointSnapshot`
and `CHECKPOINT_SNAPSHOT_KEYS` (widening to `[&str; 21]`), or narrow the doc comment to match
reality.

### WR-08: The bad-input matrix documents an `invalid_settings` disposition the code does not implement

**File:** `engine/src/tests/bad_input_matrix.rs:21-28` vs `engine/src/service.rs:790-792`

**Issue:** The matrix header states the numeric bounds are *"already covered by the existing
`invalid_settings` error-kind category (mapped to an internal status, since it identifies an
operator misconfiguration rather than a caller input)."* The code maps it to
`tonic::Code::InvalidArgument`, which `gateway/main.go:668-671` turns into **HTTP 400** — an
operator misconfiguration reported to the caller as a client error, with the raw settings
message echoed back.

This is unreachable in production today: `EffectiveRagSettings::try_from_settings` validates at
startup (`config.rs:514`) and `main.rs:24-25` aborts on failure, so a request can never reach a
failing `RetrievalSettings::validate`. The defect is that the documented contract and the
implemented mapping disagree — and the doc is the artifact Phase 6.4 is slated to lift verbatim
into API documentation.

**Fix:** Either change `service.rs:790-792` to `(tonic::Code::Internal, "invalid_settings")` to
match the stated intent, or correct the matrix header to say `InvalidArgument`/400.

### WR-09: The production TLS guard only matches one of several ways to disable TLS

**File:** `gateway/internal/config/config.go:59-61`

**Issue:** `strings.Contains(cfg.Gateway.DatabaseURL, "sslmode=disable")` is the entire prod
check. `sslmode=allow` and `sslmode=prefer` both permit a plaintext connection and pass, as
does a URL with no `sslmode` at all (the libpq/pgx default is `prefer`, i.e. TLS-optional). A
production DSN can therefore transit credentials in cleartext with the guard green.

**Fix:** Parse the DSN and require an explicitly safe mode:

```go
if os.Getenv("LANCET_ENV") == "prod" {
    u, err := url.Parse(cfg.Gateway.DatabaseURL)
    if err != nil {
        return Config{}, fmt.Errorf("gateway.database_url is not a valid DSN: %w", err)
    }
    switch u.Query().Get("sslmode") {
    case "require", "verify-ca", "verify-full":
    default:
        return Config{}, errors.New("gateway.database_url must set sslmode=require|verify-ca|verify-full in prod")
    }
}
```

### WR-10: New unit tests assert only what the test doubles were constructed to return

**File:** `engine/src/workflow/ports.rs:479-525`

**Issue:** `fake_graph_query_port_failure_with_retryable_flag` builds
`FakeGraphQueryPort::failure_with_retryable(false)` and asserts the returned error has
`retryable == false` and `kind == GraphFailed` — restating the constructor's own literal
(`ports.rs:240-249`). It passes by construction and exercises no production code, which is
what `rust-guidelines.md` M-TAUTOLOGICAL-TESTS warns against. These tests also count toward the
hard-pinned totals in `scripts/engine-test-targets.sh:56-89`, so tautological tests inflate the
number that gate is defending.

**Fix:** Delete the fake-asserting test, or replace it with one that drives
`ExtractGraphContextNode` through the fake and asserts the resulting `GRAPH_DEGRADED` notice
and node outcome — behavior of the code under test, not of the double. Update the pinned counts
in the same commit.

### WR-11: Test-gate script hardcodes a developer's absolute home path and cannot see a build failure

**File:** `scripts/engine-test-targets.sh:7, 29-42`

**Issue:** Two problems in a script that gates CI:

1. `for p in "$HOME/.cargo/bin" "/mnt/c/Users/user3/.cargo/bin" "/c/Users/user3/.cargo/bin"` —
   a specific developer's username is committed into the repository, and the loop
   unconditionally prepends those directories to `PATH` when they exist, so a
   `C:\Users\user3\.cargo\bin\cargo.exe` planted by anything else takes precedence over the
   resolved toolchain.
2. Line 29 is a pipeline (`cargo … | tr … > "$TMP_FILE"`) and `/bin/sh` has no `pipefail`, so
   `set -e` cannot observe a cargo failure. Every `awk` extraction then yields empty, the `:-0`
   defaults engage, and a *build failure* is reported as `TOTAL test count mismatch: expected
   373, got 0` — a misleading diagnosis for the most common red case.

**Fix:** Drop the hardcoded user paths (rely on `$HOME/.cargo/bin` plus the `cargo.exe`
lookup), and check the cargo invocation's status explicitly:

```sh
if ! "$CARGO_CMD" test --manifest-path engine/Cargo.toml -- --list > "$TMP_FILE.raw" 2>&1; then
  echo "FAIL: cargo test --list did not succeed; see output below" >&2
  cat "$TMP_FILE.raw" >&2
  exit 1
fi
tr '\\' '/' < "$TMP_FILE.raw" | tr -d '\r' > "$TMP_FILE"
```

### WR-12: A cancelled run emits a spurious `RETRIEVAL_DEGRADED_*` notice

**File:** `engine/src/workflow/nodes/retrieve.rs:66-97, 119-150`

**Issue:** The dense and BM25 error arms treat every `NodeError` as a degradation, including
`NodeErrorKind::Cancelled`, which the ports return when the token is already cancelled
(`service.rs:511-513, 556-558`). Cancellation itself is not lost — the variant loop's
`cancel.is_cancelled()` check at `retrieve.rs:109-111` still bails out — but by then
`ctx.notices` has picked up a `RETRIEVAL_DEGRADED_DENSE` (or `..._BM25`) entry, which is copied
into the terminal `WorkflowCompletedEvent` (`runner.rs:532-539`). A client that cancelled its
own stream is told the corpus degraded.

**Fix:** Re-raise cancellation instead of degrading:

```rust
Err(err) if err.kind == NodeErrorKind::Cancelled => return Err(err),
Err(err) => { /* existing degrade + notice */ }
```

### WR-13: The README still says Phase 6 has not started

**File:** `README.md:5, 130`

**Issue:** The status callout reads *"Project Status: Phases 1-5 Complete — Phase 6
(Observability, Evaluation & Polish) Next"* and *"Phase 6 … is next and has not yet started"*,
and the plan count is still 89 — in the same commit range that ships Phase 6's engine
restructure, gateway package split, protobuf change, and RAG-03 hardening. The README is the
project's front door and now contradicts the repository contents.

**Fix:** Update the status callout and plan count as part of the phase close-out, and add the
README to the phase completion checklist so it does not drift again.

---

_Reviewed: 2026-08-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
