# Phase 6: Observability, Evaluation & Polish (module graph, wire contract, RAG-03 core) - Research

**Researched:** 2026-08-20
**Domain:** Rust crate/module-graph refactor · Go package extraction · additive protobuf contract evolution · RAG degraded-mode behavior
**Confidence:** HIGH (nearly every claim is grounded in a file read this session; the two `[ASSUMED]` items are listed in the Assumptions Log)

> **Scope fence.** This document covers **Phase 6 proper only**: the Rust module-graph restructure
> (D-80/D-81), the Go `main.go` package split (D-82), the single consolidated additive wire-contract
> change (D-74/D-76), and the four RAG-03 behavior clauses (DEBT-RAG-01 → D-10..D-13, DEBT-RAG-03 →
> D-14, DEBT-RAG-05 → D-15, DEBT-RAG-06 → D-08). Index rebuild-and-swap (6.1), OTel (6.2), the eval
> harness (6.3) and the docs suite (6.4) are **out of scope** and are mentioned only where a Phase 6
> decision must not foreclose them.

> **Relationship to `06-AI-SPEC.md`.** The AI-SPEC already owns the *design*: §4.1/§4.2 are the
> complete D-74 wire delta (proto verbatim, field numbers, the `NoticeCode` value table, the
> `degraded_mode` derivation rule), §4.3 is the observable HTTP/SSE surface and the notice-list
> precedence rule, §4.5 is the four behavior changes. **This RESEARCH.md does not restate any of
> that** — it supplies what the AI-SPEC leaves open: the *codebase mechanics*, the *churn numbers*,
> the *acceptance-criteria traceability*, and the *empirically verified codegen shapes* the planner
> needs to size and sequence plans.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

`06-CONTEXT.md` governs Phases 6, 6.1, 6.2, 6.3 and 6.4 (D-77). The decisions below are the subset
scoped to **Phase 6 proper**. All are copied verbatim from
`.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` `<decisions>`.

### Locked Decisions

**Section B — Degraded-mode behavior (RAG-03), Phase 6**

- **D-10:** **Model-only answers are supported, opt-in per request, default off.** When both retrieval paths fail (or evidence is absent) and the caller opted in, the workflow generates an answer with `answer_basis = MODEL_ONLY`, an explicit notice, and **zero citations**. With the flag off, today's fail-closed behavior stands. This requires lifting the hard guard at `engine/src/generation/mod.rs:172-175` ("ModelOnly answer basis is not supported on Phase 03 QueryRAG path") — a deliberate act, not a side effect. *User rationale, recorded as data:* the eventual goal is for the system to decide per question whether RAG is needed at all; retrieval legitimately returns nothing and an answer is still wanted. The load-bearing principle is that **when retrieved data contradicts model knowledge, our data wins**. — **Reversibility:** one-way — the opt-in becomes a published field on `QueryRAGRequest` and on `/rag/query`; removing it breaks any client that sets it.
- **D-11:** **The opt-in flag overrides Phase 05 D-03's zero-evidence short-circuit.** When the caller has opted in, a zero-evidence query no longer skips `AssemblePrompt`/`GenerateAnswer` — it runs them and returns `MODEL_ONLY` + notice + no citations. With the flag off, D-03's short-circuit is exactly as shipped. **This is an explicit amendment to Phase 05 D-03.** — **Reversibility:** costly — the runner's zero-evidence branch (`engine/src/workflow/runner.rs:427,481`) and its tests both change shape.
- **D-12:** The opt-in is **config default (off) + per-request override** — a TOML/env key following the Phase 2 D-26–D-30 convention, plus an additive `QueryRAGRequest` field plumbed through the gateway's `/rag/query`.
- **D-13:** **One retrieval path failing keeps `answer_basis = RETRIEVAL`**, with a machine-readable notice naming the failed path (e.g. `RETRIEVAL_DEGRADED`). `answer_basis` keeps meaning *what grounded this answer*, not *how healthy the pipeline was* — consistent with how `GRAPH_DEGRADED` already behaves.
- **D-14:** **Citation repair (DEBT-RAG-03) is normalize-then-strip.** One *local* pass attempts to resolve near-miss markers (whitespace/case/format normalization, index-vs-id confusion). Anything still unresolved is stripped from the answer text, a notice is emitted (`CITATION_REPAIRED` / `CITATION_DROPPED`), and the basis downgrades if the answer loses all grounding. **No second provider call**, per the debt's own criteria.
- **D-15:** **DEBT-RAG-05 gets an enumerated, table-driven matrix**: empty/whitespace/oversized query, malformed session and document IDs, unsupported content type, and each filter bound (over-limit, negative, contradictory, unmatched). One table-driven test per surface (gRPC and HTTP), all rejecting **before** retrieval or provider work, with stable HTTP 400 / gRPC `InvalidArgument`. The table doubles as API-contract documentation in Phase 6.4.
- **D-16:** **"Weak evidence" gets no threshold — the concept is dropped.** RRF fusion scores are not calibrated across queries, so any fixed cutoff would be arbitrary. Recorded as deliberately not implemented, closing that clause of DEBT-RAG-01 by explicit narrowing.
- **D-17:** The **evidence-over-priors principle is enforced by prompt contract**: an explicit precedence instruction in the assembled prompt ("when evidence contradicts your prior knowledge, the evidence is authoritative; say so"). **The eval metric for it is deferred** (see D-45) — v1 ships the behavior unmeasured, recorded as an accepted gap.
- **D-18:** **`MIXED` is decided by model self-report plus engine validation, with a reconciliation rule.** The model declares `answer_basis` in the existing structured output; the engine validates against observable facts (citations present and resolving, markers stripped by repair, evidence partiality); on disagreement the **more conservative basis wins** and a notice records the reconciliation.
- **D-19:** The prompt change in D-17 is **prompt text only — the JSON schema is untouched.** Phase 3 D-28's `response_format`/`json_schema` contract and Phase 05 D-01 both hold. The reconciliation rule in D-18 works off `answer_basis`, which the schema already carries.

**Section A — Debt ledger scope (the one Phase-6 item)**

- **D-08:** **DEBT-RAG-06 closes by adding the missing notice, not by changing behavior.** `GRAPH_TIMEOUT` / `GRAPH_DEGRADED` already fire on graph *failure* (`engine/src/workflow/nodes/graph_context.rs:135-137`). What degrades **silently** is the empty-result path (`:112-115`) and the absent-`graph_port` path (`:145-148`) — those get a machine-readable notice (e.g. `GRAPH_UNAVAILABLE`). 04.1 D-32 and Phase 05 D-09 behavior is unchanged. Tests prove source-chunk queries never require graph data.

**Section G — Wire contract & phase sequencing**

- **D-74:** **One consolidated additive wire-contract change, landed first.** Define the complete Phase 6 wire delta up front — the model-only request flag (D-12), the graph-ablation request flag (D-47), `WorkflowCompletedEvent` workflow-metadata fields (D-41), and the notice-code enum (D-76) — and land it as a single additive protobuf change with regenerated Rust and Go bindings **before** the behavior plans start. Phase 05 spent plans 05-17 and 05-23 repairing generated-field drift from incremental changes; one regeneration, one review, one settled contract. — **Reversibility:** one-way — published gRPC and HTTP contract surface.
- **D-75:** **Sequence: module graph → wire contract → behavior → telemetry → eval → docs.** Each stage's output is the next stage's input, and documentation is written against shipped reality.
- **D-76:** **Notice codes are promoted to a typed proto enum** (string form retained for forward compatibility) with the full table documented in `docs/` as part of the API contract. The vocabulary is now real and client-facing — `NO_EVIDENCE`, `GRAPH_DEGRADED`, `GRAPH_TIMEOUT`, plus new `RETRIEVAL_DEGRADED`, `CITATION_REPAIRED`/`CITATION_DROPPED`, `MODEL_ONLY`, `GRAPH_UNAVAILABLE` and index-staleness codes. Ad-hoc invention is already happening (`GRAPH_TIMEOUT` appears as a bare literal three times in `graph_context.rs`). — **Reversibility:** one-way — enum values become part of the published contract.

**Section H — Engineering surface & test strategy**

- **D-80:** **DEBT-P3-MODULE-GRAPH is closed in Phase 6** — a **deliberate exception** to the ROADMAP-named-only scope of D-01. The binary imports all production modules from the library crate; the dual `lib.rs`/`main.rs` declaration ends. Justification: phases 6–6.4 add substantial engine code across exactly that seam, which is the debt's own stated trigger ("next large engine module change"). — **Reversibility:** costly — touches the module declarations of both targets, though the 285-test suite is the safety net.
- **D-81:** **The module-graph restructure is the first Phase 6 plan**, alongside or just before the D-74 wire-contract change, so all five phases of new engine code land on a settled foundation. Front-loaded as a pure-refactor plan.
- **D-82:** **The Go gateway is restructured first too**, symmetric with the engine — `main.go` split into packages (telemetry setup, SSE handling, engine client, config) before the telemetry work lands, rather than growing past 1,500 lines.
- **D-83:** **Fault testing extends Phase 05's `cfg(test)` fake-port seam** (built by 05-15 and 05-18) with failure modes — error, timeout, empty, malformed citation — rather than inventing a new mechanism. Deterministic, fast, no infrastructure, **no production fault-injection switch**.
- **D-84:** **Config knobs added by Phase 6 fail closed on present-but-invalid values**; existing keys keep today's behavior until the backlog Config & settings hygiene phase fixes them. This contains DEBT-P3-WARN-SETTINGS rather than multiplying it — a mistyped OTLP endpoint or sampler ratio must fail loudly, not silently disable telemetry.
- **D-85:** **No CI.** The existing local-gate model stands (the build/test commands already in `.planning/config.json`), documented in the README as the verification path. CI remains available as a future backlog item.

**Cross-phase constraint that binds Phase 6's proto edit (D-47, owned by 6.3, landed by Phase 6):**

- **D-47:** **The graph ablation uses a per-request flag**, so one running engine serves both arms and the eval interleaves them without a restart. **Kept distinct from the D-10/D-12 model-only opt-in** — "answer without evidence" and "answer without graph" are different concepts and must not share a field. — **Reversibility:** one-way — another published request field.
- **D-41:** **Phase 05 D-30's workflow metadata lands in both places** — as span attributes *and* as additive `WorkflowCompletedEvent` protobuf fields (same additive pattern as Phase 05's tags 10/11). D-30 listed them as response-contract fields, so a traces-only implementation would silently drop half the commitment.

### Claude's Discretion

- Exact Rust and Go module/package layout produced by the D-80/D-82 restructures.
- Exact protobuf field numbers, message shapes and enum value names in the D-74 consolidated contract change (must carry the fields decided in D-12, D-41, D-47, D-76).
- Exact configuration key names for the new telemetry, model-only, rebuild-debounce and eval knobs (must follow the existing TOML+env convention and D-84's fail-closed rule).
- Exact notice code string values beyond the semantics fixed in D-08, D-13, D-14 and D-76.

*(The remaining discretion bullets — Grafana SDK choice, debounce window, MultiHop-RAG subset algorithm, `eval/` internals — belong to 6.1/6.2/6.3 and are out of Phase 6's scope.)*

### Deferred Ideas (OUT OF SCOPE)

- **Automatic RAG-vs-model routing** — the system deciding per question whether retrieval is needed at all. The user's stated future intent; a new capability warranting its own phase. D-10's opt-in flag is the deliberate first step toward it.
- **Weak-evidence scoring band / calibrated fusion-score threshold** — explicitly dropped (D-16), revisit only if fusion scores become comparable across queries.
- **The evidence-vs-model-priors eval metric** — deferred with the generated test set. v1 ships the prompt precedence contract **unmeasured**; D-71 requires this be stated in the README's limitations section.
- **Multi-provider / backup-model generation fallback** — descoped by Phase 05 D-14, confirmed closed by D-05. Revisit only if reliability requirements change.
- **Identity-only structured logging with no raw provider detail** — DEBT-D1-SAFE-LOG, kept in the backlog per D-09.
- **CI** (`.github/workflows`) — D-85 keeps the local-gate model.
- **Gateway HTTP `ReadTimeout`/`WriteTimeout`/`IdleTimeout` and bounded upload semaphore**; **auth, authorization, TLS ingress, per-principal quotas** — documented-only per D-06 (and reviewed in 6.1, not here).
</user_constraints>

---

<phase_requirements>
## Phase Requirements

**Requirement ID:** RAG-03 — *"Support degraded mode when graph extraction or one retrieval path fails, returning a useful vector/BM25-backed answer. See DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-04, DEBT-RAG-05, and DEBT-RAG-06 for the preserved target contracts."*
[VERIFIED: `.planning/REQUIREMENTS.md:13`]

Traceability row: `| RAG-03 | Phase 06, Phase 06.1 | … DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-05 and DEBT-RAG-06 clauses → Phase 06; DEBT-RAG-04 (index rebuild-and-swap) → Phase 06.1. |`
[VERIFIED: `.planning/REQUIREMENTS.md:52`]

The **acceptance criteria** for RAG-03 live in `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md`,
which `06-CONTEXT.md` `<canonical_refs>` names *"the only written spec for what RAG-03 must do."*
The table below maps each debt item's **`Future acceptance criteria`** bullet, quoted verbatim, to the
Phase 6 decision that satisfies it and the code site that must change. **Every clause must be
traceable to at least one plan** — an implementation that satisfies the AI-SPEC but drops a clause here
leaves RAG-03 un-closeable.

| Debt ID | `Future acceptance criteria` (verbatim) | Satisfied by | Lands in |
|---|---|---|---|
| **DEBT-RAG-01** | "One-path failure returns a useful surviving-path answer with a machine-readable warning; both-path failure returns an explicit model-only basis and notice with no citations; weak/empty evidence follows the documented answer-basis contract." | Clause 1 → **D-13**; clause 2 → **D-10/D-11/D-12**; clause 3 → **D-16** (threshold explicitly dropped) + **D-18** (documented basis contract) | `runner.rs`, `retrieve.rs`, `generation/mod.rs`, `workflow/mod.rs` |
| **DEBT-RAG-03** | "One bounded repair attempt is made without another provider call; unresolved markers are removed, the answer basis is downgraded transparently, and a machine-readable warning is emitted." | **D-14** (normalize-then-strip, no second provider call) + **D-18** (downgrade is the conservative-wins rule) | new `generation/citations.rs`, `generation/mod.rs` |
| **DEBT-RAG-05** | "Empty/oversized queries, malformed IDs, unsupported content types, and filter limits are rejected before retrieval/provider work with stable HTTP 400 and gRPC `InvalidArgument` behavior." | **D-15** (enumerated table-driven matrix, one per surface) | `engine/src/main.rs` `query_rag` + `retrieval/mod.rs` (**validation already exists** — see §"D-15 is mostly test work"), `gateway` HTTP surface |
| **DEBT-RAG-06** | "Graph-unavailable queries retain a useful typed response or documented model-only/degraded basis, with machine-readable warning behavior **and tests that do not require graph data for source-chunk queries**." | **D-08** (notice on the two silent paths; behavior unchanged) | `workflow/nodes/graph_context.rs` |
| **DEBT-P3-MODULE-GRAPH** | "Binary imports shared modules from library crate." | **D-80/D-81** | `engine/src/lib.rs`, `engine/src/main.rs` |

[VERIFIED: `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` — the five
`**Future acceptance criteria:**` bullets under `### DEBT-RAG-01`, `### DEBT-RAG-03`,
`### DEBT-RAG-05`, `### DEBT-RAG-06`, and `### DEBT-P3-MODULE-GRAPH`, read in full this session and
quoted verbatim above.]

**Three clauses easy to drop, called out explicitly:**

1. DEBT-RAG-06's *"tests that do not require graph data for source-chunk queries"* is a **test
   obligation**, not a notice. ROADMAP SC7 restates it ("source-chunk queries are proven to never
   require graph data"). A plan that only adds `GRAPH_UNAVAILABLE` does not close DEBT-RAG-06.
2. DEBT-RAG-01's *"weak/empty evidence follows the documented answer-basis contract"* is closed by
   **explicit narrowing** (D-16 drops the weak-evidence threshold). The plan must **record** that
   narrowing, not silently omit it — otherwise the coverage matrix reads it as missed.
3. DEBT-RAG-03's *"downgraded transparently"* means the downgrade is **observable** (a notice), not
   just internal. D-18's `BASIS_RECONCILED` is what makes it transparent.
</phase_requirements>

---

## Summary

Phase 6 is three structurally different kinds of work wearing one phase number, and the locked
sequence (D-75/D-81/D-82: **module graph → wire contract → behavior**) exists because each stage
would otherwise make the next one's diff unreadable. The research finding that most changes planning
is that **the first two stages are much larger than their one-line descriptions suggest, and the
third is much smaller.**

**The restructure is bigger than "end the dual declaration."** There is no dual declaration: no
production module is declared in both `lib.rs` and `main.rs`. What actually exists is 3,351 lines of
production code — the entire `LancetService` gRPC implementation, `EffectiveRagSettings`, config
loading, and the ingestion worker — living in `main.rs` where the library cannot see it, plus a
`chunker` module compiled only into the binary, plus a test topology split across three targets
(lib 133 tests / bin 128 / integration 9). The 128 binary tests reach into `crate::EffectiveRagSettings`
and `crate::tests::configured_service`, so they cannot move until the items they name move first.
The safety net D-80 names is real but must be asserted **per target**, not as one total, because a
module relocating between targets keeps the total constant while coverage silently migrates.

**The wire change is bigger too — because of struct-literal churn, not proto complexity.** The proto
edit itself is exactly what AI-SPEC §4.2 specifies. But `QueryRagRequest { … }` appears as an
**exhaustive struct literal 80 times** across three Rust test files with **zero** uses of
`..Default::default()`, and `Notice { … }` appears 19 times in hand-written Rust. Adding two request
fields and one notice field breaks all 99 sites at compile time. This is precisely the drift that cost
Phase 05 two repair plans (05-17, 05-23), and D-74 exists to prevent a *second* occurrence — but only
if the D-74 plan budgets for the churn instead of discovering it. The recommended containment is to land
a test-fixture constructor **before** the proto edit, so the 80 sites are migrated once, mechanically,
in a separate reviewable commit.

**The behavior work is smaller than expected in one place and subtler in another.** D-15's bad-input
matrix is **mostly test work**: a typed nine-variant `RetrievalErrorKind` taxonomy already exists, is
already mapped to stable gRPC codes and stable error-kind strings, already runs before any retrieval
or provider work, and the gateway already maps `InvalidArgument` → 400. Conversely, D-10/D-11's
opt-in must thread a resolved boolean from gRPC admission through `WorkflowContext` into
`validate_grounding_with_limits`, which today takes no parameter through which it could arrive — and
the zero-evidence short-circuit it must bypass exists in **two** places in `runner.rs`, both keyed on
a **string** comparison against `"NO_EVIDENCE"`.

**Two corrections to the AI-SPEC that must land before the proto does.** Reading
`RetrieveHybridNode` end-to-end showed that (i) D-13 is not "attach a notice" but **"convert a
fail-closed path into a degrade path"** — both retrieval calls currently `return Err(err)`, failing
the whole workflow — and (ii) **`NOTICE_CODE_RETRIEVAL_DEGRADED_GRAPH` (AI-SPEC §4.2, tag 17) is
unreachable by construction**: the node holds no graph port and the file contains no reference to
graph at all. Since D-76 makes enum values one-way published contract, shipping a permanently-dead
value in the very change that establishes the vocabulary is free to avoid now and impossible to
remove later. **D-13 is two codes, not three.**

**Primary recommendation:** Plan Phase 6 as five sequential plans — (1) Rust module-graph restructure,
pure refactor, per-target test-count invariant asserted; (2) Go `main.go` package split, pure refactor;
(3) struct-literal containment + the single `buf generate` proto change; (4) the two notice-only
behavior clauses (D-08, D-13) which are additive and low-risk; (5) the two threading-heavy clauses
(D-10/D-11/D-12 model-only, D-14/D-18 citation repair + reconciliation), with the D-15 matrix landable
in parallel with (4) because it touches only tests and the existing validation surface.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Module-graph restructure (D-80) | Rust engine (library crate `engine`) | Rust engine (binary target) | The debt's acceptance criterion is literally "binary imports shared modules from library crate" — the library becomes the owner, the binary a thin consumer |
| Package split (D-82) | Go gateway (`internal/` packages) | Go gateway (`main.go` wiring) | `main.go` keeps only `run()`-style wiring; behavior moves behind package boundaries |
| Wire contract definition (D-74/D-76) | `proto/lancet/v1/lancet.proto` | Generated Rust + Go bindings | Single source of truth; both bindings are committed artifacts regenerated by one `buf generate` |
| Request-flag transport (D-12/D-47) | Go gateway HTTP edge (`ragQueryRequestBody` → `pb.QueryRAGRequest`) | Rust engine (resolution + defaulting) | The gateway is a pass-through: it must *carry presence*, not interpret it. Resolution (request → config → false) is engine-side, once, at admission |
| Input validation / bad-input matrix (D-15) | Rust engine (`query_rag` admission, `QueryRequest::from_values`) | Go gateway (body bounds + `InvalidArgument`→400 mapping) | Validation already lives engine-side and is already reached before retrieval; the gateway derives HTTP status from the gRPC code rather than duplicating rules |
| Degraded-mode notices (D-08/D-13) | Rust engine workflow **nodes** | — | A node degrades by mutating `WorkflowContext` and returning `Ok(())`; no other tier can observe what failed |
| Answer-basis reconciliation (D-18) | Rust engine `generation` / `workflow::mod` | — | Requires simultaneous access to the model's self-report and the engine's observable facts; only the engine has both |
| Citation repair (D-14) | Rust engine `generation` | — | Operates on the packed evidence set + model output; the gateway never sees markers |
| Config knob resolution (D-12/D-84) | Rust engine `load_settings` | Go gateway `loadConfig` (gateway-side keys only) | Each service owns its own config surface; the shared convention is TOML + `LANCET_*__*` env |
| Notice serialization to clients | Go gateway (`writeWorkflowEventSSE`, `noticeDTO`) | — | The engine emits typed notices; the gateway is the only place they become JSON |

---

## Project Constraints (from CLAUDE.md)

`./CLAUDE.md` is short and entirely about language-guideline routing. Its directives, extracted:

| Directive | Source | Consequence for Phase 6 |
|---|---|---|
| **Before writing Rust code, read `rust-guidelines.md` in the repo root and adhere to it.** Trigger: creating/editing/refactoring `.rs` files or Cargo components. | `CLAUDE.md` §"Rust Guidelines" | Applies to **every** Phase 6 engine plan. |
| **Do NOT read `rust-guidelines.md` for non-Rust tasks** (Go, HTML/JS, Protobuf, documentation) — to save context and prevent irrelevant rules. | `CLAUDE.md` §"Rust Guidelines" — Scope Restriction | The D-74 proto plan and the Go split plan must **not** load it. Plans should carry the guideline reference only on the tasks that write that language. |
| **Before writing Go code, read `go-guidelines.md`, detect the Go version from `go.mod`, and adhere to guidelines up to that version.** | `CLAUDE.md` §"Go Guidelines" | Applies to the D-82 split and the D-74 gateway-side field plumbing. |
| **Do NOT read `go-guidelines.md` for non-Go tasks.** | `CLAUDE.md` §"Go Guidelines" — Scope Restriction | Same containment as above. |

[VERIFIED: `D:/Repos/lancet/CLAUDE.md` — read in full this session; the four directives above are its
complete actionable content.]

### The Go-version trap this creates (concrete, and it will bite the D-74 plan)

`go-guidelines.md` says: *"Never use features from newer Go versions than the target"* and *"DO NOT
search for go.mod files or try to detect the version yourself. Use ONLY the version shown above"* —
where "above" is a command substitution over `go.mod`. [VERIFIED: `go-guidelines.md`, §"How to Use
This Skill"]

- `gateway/go.mod` declares **`go 1.25.0`** [VERIFIED: `gateway/go.mod:3` — `go 1.25.0`].
- The installed toolchain is **go1.26.5** [VERIFIED: `go version` → `go version go1.26.5 windows/amd64`].

So the **target is Go 1.25**, and Go 1.26 features are forbidden even though they would compile.
The two that matter for Phase 6:

| Go 1.26 feature | Status for Phase 6 | Why it will tempt an implementer |
|---|---|---|
| `new(val)` — pointer to an expression, e.g. `new(true)` | **FORBIDDEN** (1.26 > target 1.25) | D-74 adds `*bool` request fields (`AllowModelOnly`, `DisableGraphContext`). `go-guidelines.md` shows `Debug: new(true)` as the canonical way to populate a `*bool` struct field. On a 1.25 target the correct form is a local (`v := true; …&v`) or a small generic `ptr[T](v T) *T` helper. |
| `errors.AsType[T](err)` | **FORBIDDEN** (1.26 > target 1.25) | `handlePreStreamError` and `queryRAG` both use `errors.As` today; a "modernization" pass would break the target. |

Allowed and idiomatic at 1.25: `wg.Go(fn)`, `t.Context()` in tests, `omitzero` JSON tags,
`strings.SplitSeq`, `slices`/`maps`/`cmp`, `min`/`max`/`clear`, `cmp.Or`.
[VERIFIED: `go-guidelines.md` §§"Go 1.24+", "Go 1.25+", "Go 1.26+"]

> If the planner *wants* Go 1.26 features, the correct move is an explicit, separate decision to bump
> `gateway/go.mod`'s `go` directive — not to silently use them. That is not a Phase 6 decision and is
> not in CONTEXT.md.

### Rust guideline that directly governs the D-80 restructure

**M-SINGLE-ITEM-PATH — "Items are only visible through one path."** Verbatim:

> "Public items within a crate should be reachable only through one path. For example some
> `crate::db::Connection` should not also be visible as `crate::Connection`: […] **This rule is often
> violated by agents creating or refactoring large code bases over several iterations. In an attempt
> to _simplify_ their task, they re-export items under multiple paths, often previous ones from
> before some change, instead of cleanly redesigning structures where it makes sense.**"

[VERIFIED: `rust-guidelines.md:104-137`]

This is the single most relevant guideline in the file for D-80, and it names the exact failure mode:
moving `EffectiveRagSettings` into the library and leaving `pub use` shims in `main.rs` so the 128
existing `crate::…` references keep compiling **satisfies the compiler and violates the guideline** —
and leaves the debt half-closed. The restructure must update call sites, not add aliases.

Note also that `lib.rs` today already carries one re-export:
`pub use pb::lancet::v1::lancet_service_server::LancetService;` [VERIFIED: `engine/src/lib.rs:13`] —
a re-export of a *foreign* (generated) item, which the guideline explicitly exempts
("re-exports of foreign items are not covered by this rule").

**M-TAUTOLOGICAL-TESTS** (`rust-guidelines.md:138-162`) is the second relevant one: it forbids tests
that "re-state the expected value from the same logic the code under test uses." Relevant to D-15's
matrix — a table-driven test whose expectations are generated from the same constant the validator
reads is tautological. The table must assert *stable external contract* (gRPC code, error-kind string,
HTTP status), which is exactly what D-15 specifies.

**Project skills:** `.claude/skills/` contains only GSD workflow skills (69 `gsd-*` directories); there
is no project-specific skill with domain rules. `.agents/skills/` does not exist. No additional
patterns to honor. [VERIFIED: `ls .claude/skills` / `ls .agents/skills` this session]

---

## Standard Stack

**Phase 6 adds no dependencies.** Every tool it needs is already in the repo or on PATH. The tables
below record what the existing stack *is*, with verified versions, because the planner's tasks must
name real commands.

### Core

| Tool / Library | Version | Purpose | Why Standard |
|---|---|---|---|
| `buf` CLI | **1.72.0** | The one code-generation step Phase 6 adds (D-74) | Already the repo's generator: `buf.yaml` + `buf.gen.yaml` at repo root drive both Rust and Go output [VERIFIED: `buf --version` → `1.72.0`; `buf.yaml`, `buf.gen.yaml` read this session] |
| `buf.build/community/neoeinstein-prost` | **v0.5.0** (remote plugin) | Generates `engine/src/pb/lancet/v1/lancet.v1.rs` | Pinned in `buf.gen.yaml` [VERIFIED: `buf.gen.yaml` — `- remote: buf.build/community/neoeinstein-prost:v0.5.0` / `out: engine/src/pb`] |
| `buf.build/community/neoeinstein-tonic` | **v0.5.0** (remote plugin), `opt: no_client=true` | Generates `lancet.v1.tonic.rs` (server only) | [VERIFIED: `buf.gen.yaml`] |
| `buf.build/protocolbuffers/go` | **v1.36.5** (remote plugin), `opt: paths=source_relative` | Generates `gateway/proto/lancet/v1/lancet.pb.go` | [VERIFIED: `buf.gen.yaml`] |
| `buf.build/grpc/go` | **v1.5.1** (remote plugin), `opt: paths=source_relative` | Generates `lancet_grpc.pb.go` | [VERIFIED: `buf.gen.yaml`] |
| `cargo` / rustc | **cargo 1.95.0 (f2d3ce0bd 2026-03-21)** | Engine build + the 285-attribute / 288-case test gate | [VERIFIED: `cargo --version`] |
| Rust edition | **2021** | `engine/Cargo.toml` `edition = "2021"` | [VERIFIED: `engine/Cargo.toml`] |
| `go` toolchain | **go1.26.5** installed; **go.mod target `go 1.25.0`** | Gateway build/test | [VERIFIED: `go version`; `gateway/go.mod:3`] |
| `prost` / `tonic` / `tonic-prost` | `~0.14` / `~0.14` / `~0.14` | Rust protobuf runtime + gRPC | [VERIFIED: `engine/Cargo.toml`] |
| `chi/v5` | `v5.3.1` | Gateway HTTP router | [VERIFIED: `gateway/go.mod`] |
| `spf13/viper` | `v1.21.0` | Gateway TOML+env config | [VERIFIED: `gateway/go.mod`] |
| `go.uber.org/zap` | `v1.28.0` | Gateway structured logging | [VERIFIED: `gateway/go.mod`] |
| `config` (Rust) | `~0.15`, `features = ["toml"]` | Engine TOML+env config | [VERIFIED: `engine/Cargo.toml`] |

### Supporting

| Library | Version | Purpose | When to Use |
|---|---|---|---|
| `uuid` | `~1.24`, `features=["v4"]` | Session/document ID validation — already the mechanism behind `invalid_session_id` and `document_id must be a UUIDv4 string` | D-15's malformed-ID rows |
| `unicode-normalization` / `unicode-casefold` / `unicode-segmentation` | `~0.1.25` / `~0.2.0` / `~1.13.3` | Already-approved Unicode primitives (added by plan 03-01) | **D-14's citation-marker normalization** — whitespace/case folding is exactly what these do. No new dependency is needed for "normalize-then-strip." [VERIFIED: `engine/Cargo.toml`] |
| `blake3` | `1` | Already used for `RetrievalSnapshot.result_hash` | Not needed by Phase 6; listed so the planner does not add a second hasher |
| `tokio-util` | `~0.7` | `CancellationToken` — every node's cancel path | Unchanged |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| `buf generate` with remote plugins | Local `protoc` (**libprotoc 35.1** is on PATH) + local plugin binaries | Remote plugins need network at generation time. `protoc` alone cannot reproduce the pinned `neoeinstein-prost@v0.5.0` output without installing `protoc-gen-prost`/`protoc-gen-tonic` at matching versions — the generated file header (`// This file is @generated by prost-build.`) would drift. **Use `buf generate`.** |
| Adding a `build.rs` to generate Rust bindings at compile time | — | There is **no `build.rs`** in `engine/` [VERIFIED: `ls engine/` — `Cargo.lock`, `Cargo.toml`, `src`, `target`, `tests`]. Bindings are **committed artifacts**. Introducing `build.rs` would be an unrequested architecture change and would break the "one regeneration, one review" review model D-74 depends on. |
| A new normalization crate for D-14 | Existing `unicode-*` crates | Already vendored and already approved through the plan-01 dependency gate. |

**Installation:**

```bash
# Nothing to install. Verified present on this machine:
#   buf 1.72.0 · cargo 1.95.0 · go1.26.5 · protoc 35.1 · docker 28.4.0 · uv 0.11.2
```

**Version verification:** every version above was obtained this session either from a manifest read
with `Read`/`cat` or from the tool's own `--version`. No version is quoted from training data.

---

## Package Legitimacy Audit

**Not applicable — Phase 6 installs zero external packages.**

Every dependency the phase touches is already declared in `engine/Cargo.toml` or `gateway/go.mod` and
has been through this project's prior dependency gates (e.g. plan 03-01 for the Unicode crates). The
four protobuf plugins are **remote buf plugins pinned by exact version in `buf.gen.yaml`**, not
package-manager installs.

| Package | Registry | Verdict | Disposition |
|---|---|---|---|
| *(none)* | — | — | Phase 6 adds no new packages |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

> **Planner note:** if a plan finds itself proposing a new crate or Go module, that is a signal the
> plan has drifted outside Phase 6's scope (D-01 scope discipline). The one legitimate exception the
> phase might surface is a Rust citation-marker parsing helper — and D-14's "normalize-then-strip"
> is deliberately simple enough that the existing `unicode-*` crates cover it. Adding a dependency
> would require a `checkpoint:human-verify` task per the legitimacy protocol.

---

## Architecture Patterns

### System Architecture Diagram

```
                       ┌──────────── HTTP client / eval harness (6.3) ────────────┐
                       │  POST /rag/query  {query, session_id, filter,            │
                       │                    allow_model_only?, disable_graph?}    │
                       └───────────────────────────┬─────────────────────────────┘
                                                   │ JSON, DisallowUnknownFields
                                                   ▼
┌────────────────────────────── Go gateway (package main → internal/*) ───────────────────────┐
│                                                                                              │
│  [config]  loadConfig()  TOML(config/config.toml) + LANCET_GATEWAY__* env                    │
│                                                                                              │
│  [ragapi]  queryRAG()  ── MaxBytesReader(32 KiB) ──► json.Decode(DisallowUnknownFields)      │
│                │                                        │                                    │
│                │  400 "invalid request body"  ◄─────────┘ (unknown field ⇒ hard 400)        │
│                ▼                                                                             │
│           build pb.QueryRAGRequest  (presence-preserving *bool for the two new flags)        │
│                │                                                                             │
│  [engineclient] grpcEngine.QueryRAG(ctx, req) ──────────────────────────────────────────┐   │
│                │                                                                         │   │
│                ├─ pre-stream error ─► handlePreStreamError:                              │   │
│                │      codes.InvalidArgument ⇒ HTTP 400 + X-Lancet-Error-Kind  ◄── D-15   │   │
│                │      otherwise            ⇒ HTTP 502                                    │   │
│                │                                                                         │   │
│  [sse]    writeWorkflowEventSSE(frame) ─► event: node_started|node_completed|node_failed │   │
│                │                                  |answer_chunk|final_answer             │   │
│                │                                  |workflow_completed|stream_error       │   │
│                └─ checkpoint frames ─► CheckpointDispatcher ─► PostgreSQL                │   │
└──────────────────────────────────────────────────────────────────────────────────────────┼──┘
                                                                                            │ gRPC
                       ┌────────────────────────────────────────────────────────────────────┘
                       ▼
┌──────────────────────────── Rust engine (lib crate `engine` + thin binary) ──────────────────┐
│                                                                                               │
│  query_rag() ADMISSION  ── validate session_id (UUIDv4) ──┐                                   │
│                          ── QueryRequest::from_values()  ─┤ 9 RetrievalErrorKind variants     │
│                             (query bounds, doc IDs,       │ → tonic::Code + err_kind string   │
│                              content types, filter caps)  │ → d1_status(...)  ◄──── D-15      │
│                          ── resolve allow_model_only:     │      request → config → false     │
│                             once, into WorkflowContext    │      (NEW, D-10/D-12)             │
│                          ── resolve disable_graph_context │      (NEW, D-47)                  │
│                                                           ▼  ALL BEFORE any retrieval/provider│
│                                                                                               │
│  WorkflowRunner.run_workflow(ctx, cancel, sink)                                               │
│    ├─ ReformulateQuery ────────────────────────────────────────────────────────────┐         │
│    ├─ ExtractGraphContext ── graph_port present? ── timeout/select! ── Ok(facts)    │         │
│    │      ├─ facts.is_empty()      → silent today ⇒ GRAPH_UNAVAILABLE  ◄── D-08     │ each   │
│    │      ├─ graph_port == None    → silent today ⇒ GRAPH_UNAVAILABLE  ◄── D-08     │ node   │
│    │      └─ Err(...)              → GRAPH_TIMEOUT / GRAPH_DEGRADED (unchanged)     │ mutates│
│    ├─ RetrieveHybrid ── dense ⊕ bm25 ⊕ graph → RRF fusion → evidence_blocks         │ ctx &  │
│    │      ├─ one path failed       → keep RETRIEVAL + RETRIEVAL_DEGRADED_* ◄── D-13 │ returns│
│    │      └─ final_candidates == ∅ → NO_EVIDENCE notice                             │ Ok(())│
│    │                                                                                 │        │
│    ├─ ┌── GATE (runner.rs, TWO sites) ─────────────────────────────────────┐        │        │
│    │   │  if NO_EVIDENCE notice present OR candidates+evidence both empty  │        │        │
│    │   │     ⇒ break  (skip AssemblePrompt + GenerateAnswer)               │        │        │
│    │   │  D-11: bypass this gate when allow_model_only resolved true       │        │        │
│    │   └───────────────────────────────────────────────────────────────────┘        │        │
│    ├─ AssemblePrompt ── + D-17 precedence instruction (PROMPT TEXT ONLY)             │        │
│    └─ GenerateAnswer ── OpenRouter (1 bounded retry) ─► ModelOutput                  │        │
│           ├─ validate_grounding_with_limits()  ── ModelOnly hard-reject              │        │
│           │      ⇒ D-10: becomes conditional on the resolved flag                    │        │
│           ├─ D-14 citation repair: normalize → strip → CITATION_REPAIRED/DROPPED     │        │
│           └─ D-18 reconciliation: min(model self-report, engine-observable)          │        │
│                    ⇒ BASIS_RECONCILED notice when they disagree                      │        │
│                                                                                      ▼        │
│  ctx.to_query_rag_response()  ── the SINGLE serialization point ──► FinalAnswerEvent           │
│  emit_terminal_once()         ──────────────────────────────────► WorkflowCompletedEvent      │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

*(Frame/field-level detail for the post-D-74 surface is AI-SPEC §4.3; not duplicated here.)*

### Current project structure — what the D-80/D-82 restructures actually start from

```
engine/
├── Cargo.toml                     # edition 2021; NO build.rs — bindings are committed
├── src/
│   ├── lib.rs          (17 ln)    # 9 pub mod + 1 foreign re-export + 1 cfg(test) #[path] mod
│   ├── main.rs      (3,351 ln)    # ← the actual debt. mod chunker; + #[cfg(test)] mod tests;
│   ├── chunker/                   # PRODUCTION module reachable ONLY from the binary
│   ├── client/  db/  generation/  graph/  prompt.rs  rerank/  retrieval/  workflow/   # in lib
│   ├── pb/lancet/v1/              # committed generated: lancet.v1.rs + lancet.v1.tonic.rs
│   ├── tests.rs      (7,415 ln)   # BINARY test root — `use super::*` on main.rs
│   ├── tests/
│   │   ├── workflow_phase5.rs        (3,199 ln)  # LIB test root, via #[path] in lib.rs
│   │   └── workflow_phase5_production.rs (1,473) # BINARY, declared from tests.rs
│   ├── inspect_lancedb_tests.rs   # test root for the inspect_lancedb bin, via #[path]
│   └── bin/{inspect_lancedb.rs, seed_rag_fixture.rs}
└── tests/config_startup.rs        # the only true integration-test target

gateway/                           # ALL of package main, flat
├── main.go         (1,138 ln)     # config, stores, engine client, handlers, SSE, DTOs, wiring
├── checkpoint_sink.go             # package main
├── main_test.go    (3,919 ln)     # package main, 67 Test funcs
├── proto/lancet/v1/               # committed generated Go bindings
└── db/                            # sqlc-generated + schema (already its own package)

proto/lancet/v1/lancet.proto       # 1 file, the whole contract
buf.yaml · buf.gen.yaml            # repo-root generation config
```

### Pattern 1 — Degrade vs fail: `Ok(())` + notice, never `Err`

**What:** A node signals degradation by leaving `WorkflowContext` usable, adding a de-duplicated
notice, and returning `Ok(())`. `Err(NodeError)` means terminal failure.

**When to use:** every D-08 and D-13 change.

**Example (the live D-08 site, verbatim from the repo):**

```rust
// Source: engine/src/workflow/nodes/graph_context.rs — Err branch (~:130-145)
Err(err) => {
    ctx.graph_context = String::new();
    ctx.graph_facts = Vec::new();
    let (code, msg) = if err.kind == NodeErrorKind::Timeout {
        ("GRAPH_TIMEOUT", if err.message.is_empty() { "GRAPH_TIMEOUT".to_string() } else { err.message })
    } else {
        ("GRAPH_DEGRADED", format!("graph_degrade: {}", err.message))
    };
    ctx.add_notice(Notice {
        code: code.into(),
        message: msg,
        severity: NoticeSeverity::Info as i32,
    });
    return Ok(());
}
```

And the **two silent paths D-08 must fix**, also verbatim:

```rust
// Source: engine/src/workflow/nodes/graph_context.rs — empty-result path (~:112-115)
Ok(facts) => {
    if facts.is_empty() {
        ctx.graph_context = String::new();
        ctx.graph_facts = Vec::new();
    } else { /* … render facts … */ }
}

// Source: engine/src/workflow/nodes/graph_context.rs — absent-graph_port path (~:145-148)
} else {
    ctx.graph_context = String::new();
    ctx.graph_facts = Vec::new();
}
```

Both branches set exactly the same two fields and emit **nothing**. That is the whole of D-08's
defect, and the fix is one `ctx.add_notice(...)` in each. [VERIFIED: `engine/src/workflow/nodes/graph_context.rs:95-155`,
read this session — the three branches above are quoted verbatim.]

### Pattern 2 — Notice de-duplication is on `(code, message)`, and that is load-bearing

```rust
// Source: engine/src/workflow/mod.rs:79-93 (verbatim)
pub fn add_notice(&mut self, notice: Notice) {
    if !self
        .notices
        .iter()
        .any(|n| n.code == notice.code && n.message == notice.message)
    {
        self.notices.push(notice);
    }
}

pub fn merge_notices(&mut self, new_notices: impl IntoIterator<Item = Notice>) {
    for notice in new_notices {
        self.add_notice(notice);
    }
}
```

Consequences the planner must preserve:
- Two notices with the **same code but different messages both survive** — this is what lets D-14
  emit one `CITATION_DROPPED` per marker, and what lets two simultaneously-failed retrieval paths
  produce two distinct D-13 notices.
- The comparison uses `code` (the **string**), not the new `typed_code`. After D-76, `code` is
  derived from the enum, so behavior is preserved — **but only if the derivation is applied at every
  emission site.** A site that sets `typed_code` and leaves `code` empty silently changes the
  de-dup key. This is the highest-value single assertion for the D-74 review.

[VERIFIED: `engine/src/workflow/mod.rs:79-93`]

### Pattern 3 — The zero-evidence gate exists in **two** places, keyed on a string

```rust
// Source: engine/src/workflow/runner.rs, run_workflow() (~:424-433) — verbatim
match kind {
    NodeKind::AssemblePrompt | NodeKind::GenerateAnswer => {
        if ctx.notices.iter().any(|n| n.code == "NO_EVIDENCE")
            || (ctx.final_candidates.is_empty() && ctx.evidence_blocks.is_empty())
        {
            break;
        }
    }
    NodeKind::ReformulateQuery
    | NodeKind::ExtractGraphContext
    | NodeKind::RetrieveHybrid => {}
}

// Source: engine/src/workflow/runner.rs, run_tracer() (~:479-486) — verbatim
if overall_err.is_none() {
    let is_zero_evidence = ctx.notices.iter().any(|n| n.code == "NO_EVIDENCE");

    if !is_zero_evidence {
        if let Err(err) = remainder_bridge(&mut ctx, deps, &sink, &cancel).await {
            overall_err = Some(err);
        }
    }
}
```

[VERIFIED: `engine/src/workflow/runner.rs:413-490`, read this session.]

**Three planner-relevant facts fall out of this:**
1. **D-11 must amend both sites.** CONTEXT.md D-11 names `runner.rs:427,481` — those are exactly
   these two. Amending only `run_workflow` leaves `run_tracer` fail-closed and the two paths diverge.
2. The `run_workflow` gate has a **second disjunct** (`final_candidates.is_empty() && evidence_blocks.is_empty()`)
   that `run_tracer` does not. D-11's bypass must cover **both disjuncts**, or an opted-in query that
   somehow reached zero candidates without a `NO_EVIDENCE` notice still short-circuits.
3. Both compare `n.code == "NO_EVIDENCE"`. After D-76 the enum is canonical; migrating these to
   `n.typed_code == NoticeCode::NoEvidence as i32` is the correct end state, but the string form
   **keeps working** because `code` is derived. The planner may sequence the migration after the
   behavior change; it must not leave *some* sites on `typed_code` and others on `code`.

### Anti-Patterns to Avoid

- **Adding `pub use` aliases in `main.rs` so old `crate::…` paths keep compiling.** Violates
  `rust-guidelines.md` M-SINGLE-ITEM-PATH by name, and leaves DEBT-P3-MODULE-GRAPH half-closed while
  the compiler says "done."
- **Duplicating D-15's validation rules in Go.** The engine already owns the taxonomy and the gateway
  already maps `InvalidArgument` → 400. A Go-side re-implementation creates two sources of truth for
  the same bound and guarantees they drift.
- **Editing `engine/src/pb/lancet/v1/*.rs` or `gateway/proto/lancet/v1/*.go` by hand.** They are
  `// @generated` artifacts. Phase 05 spent 05-23 repairing hand-edited generated fields.
- **Landing the proto edit and the struct-literal migration in one commit.** ~99 mechanical literal
  edits in the same diff as the contract change makes the contract unreviewable — which is the exact
  thing D-74 exists to buy.
- **Mixing the restructure with any behavior change** (AI-SPEC Pitfall 7). A suite regression in a
  mixed commit is unattributable, and D-80's *only* safety net is the suite.
- **Introducing a weak-evidence threshold.** D-16 dropped the concept.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Regenerating Rust + Go bindings after the proto edit | A hand-rolled `protoc` invocation, or a new `build.rs` | `buf generate` at repo root | `buf.gen.yaml` pins all four plugins by exact version; any other path produces different output. There is no `build.rs` and adding one is an architecture change |
| Bad-input classification for D-15 | A new validation module | The existing `RetrievalErrorKind` (9 variants) + `QueryRequest::from_values` + the `d1_status` mapping in `query_rag` | Already typed, already stable, already runs before retrieval, already maps to 400. See §"D-15 is mostly test work" |
| Session-ID validation | New UUID parsing | The existing UUIDv4 + RFC4122-variant check in `query_rag` | Already rejects with `invalid_session_id` |
| Fault injection for D-83 | A production fault-injection switch or a new mock framework | The existing `#[cfg(test)]` fake ports in `engine/src/workflow/ports.rs` | Every port already has `success()` / `failure(NodeError)` / `stall()`. D-83 explicitly forbids a production switch |
| Notice string ↔ enum mapping | A hand-written `match` from `NoticeCode` to `&str` | prost's generated `as_str_name()` / `from_str_name()` | Generated for every prost enum; empirically verified below |
| Citation-marker case/whitespace normalization | A bespoke normalizer | `unicode-normalization` + `unicode-casefold` + `unicode-segmentation`, already in `Cargo.toml` | Approved in plan 03-01; Unicode edge cases are exactly what they exist for |
| Presence-vs-false for the two new request flags | A sentinel value, a wrapper message, or a separate `has_*` field | proto3 `optional` (explicit presence) | Empirically verified below to produce `Option<bool>` / `*bool` |
| Timeouts in fake ports | `tokio::time::sleep` with a real delay in each test | The existing `stall()` constructor (`sleep(Duration::from_secs(3600))`) driven by `tokio`'s `test-util` paused clock | `test-util` is already an enabled tokio feature |

**Key insight:** Phase 6's dominant risk is not *missing* machinery — almost everything it needs
already exists. The risk is **duplicating** machinery that exists in a place the implementer did not
look (the `RetrievalErrorKind` taxonomy, the fake-port failure constructors, `as_str_name()`), and
thereby creating a second source of truth that drifts.

---

## Runtime State Inventory

> Phase 6 contains a **rename/refactor** component (D-80 Rust module relocation, D-82 Go package
> extraction) and a **published-contract change** (D-74). This section answers what survives outside
> the source tree.

| Category | Items Found | Action Required |
|---|---|---|
| **Stored data** | **None affected.** LanceDB tables (`./data/lancedb`, per `config/config.toml` `lancedb_path = "./data/lancedb"`) store chunk/entity rows; PostgreSQL stores documents, reconciliation intents and `workflow_checkpoints`. **No column, table or key encodes a Rust module path or a Go package path.** Adding `typed_code` to `Notice` does affect one stored artifact: `CheckpointEvent.context_snapshot` is a serialized `WorkflowContext` snapshot (Phase 05 D-28, "full accumulated snapshots") and will begin carrying the new field. | **No data migration.** Old checkpoint rows deserialize with the field absent (proto3 default / JSON omitted). Confirm the checkpoint reader tolerates the absent field rather than requiring it |
| **Live service config** | **None.** There is no external SaaS holding a service name. `docker-compose.yml` provides PostgreSQL + Jaeger only, both defined in-repo. Jaeger's OTLP receivers are configured in the committed `jaeger-config.yaml` and nothing is exported to it yet (that is 6.2) | **None** |
| **OS-registered state** | **None — verified by inspection.** No Windows Task Scheduler entries, no `pm2` process names, no systemd units, no launchd plists in the repo. Both services are started by `cargo run` / `go run` per PROJECT.md's local-first constraint | **None** |
| **Secrets / env vars** | **Env-var *names* are contract and must not change.** `LANCET_CONFIG_DIR`, `LANCET_ENV`, `LANCET_GATEWAY__PORT`, `LANCET_GATEWAY__DATABASE_URL`, `LANCET_GATEWAY__ENGINE_ADDR`, `LANCET_ENGINE__GRPC_ADDR`, `LANCET_ENGINE__LANCEDB_PATH`, seven `LANCET_ENGINE__WORKFLOW__*_MS` keys, five `LANCET_OPENROUTER__*` keys, `LANCET_ENGINE__RETRIEVAL__EVIDENCE_TOKEN_BUDGET`, `LANCET_OPENROUTER__MAX_OUTPUT_TOKENS`. **A Go package move relocates `loadConfig()` but must not rename any `v.BindEnv` string.** The OpenRouter API key is supplied out-of-band; `config.toml` ships `database_url = ""` with the comment "Supplied via LANCET_GATEWAY__DATABASE_URL; never commit a real DSN." | **Code move only — zero key renames.** Add the new D-12/D-84 keys alongside |
| **Build artifacts / generated code** | **Two committed generated trees must be regenerated together (D-74):** `engine/src/pb/lancet/v1/{lancet.v1.rs, lancet.v1.tonic.rs}` and `gateway/proto/lancet/v1/{lancet.pb.go, lancet_grpc.pb.go}`. A run that updates only one is exactly the drift D-74 exists to stop. Also: `engine/target/` holds stale `.exe` test binaries whose names encode the old target layout — harmless, replaced on rebuild. `gateway/db/` is sqlc-generated but **untouched** by Phase 6 | **Run `buf generate` once, commit both trees in the same commit, review as one change** |

**Nothing found in a category is stated explicitly above**, not left blank. The two categories with
real content are *secrets/env-var names* (rename-forbidden) and *generated code* (regenerate-together).

---

## The six areas the planner needs, in detail

### 1. The Rust module-graph restructure (D-80/D-81) — what is actually there

#### The ROADMAP's wording does not match the code. Say so in the plan.

ROADMAP SC1 and D-80 both say *"the dual `lib.rs`/`main.rs` declaration ends."* **There is no dual
declaration.** Here is `engine/src/lib.rs` in full — all 17 lines, verbatim:

```rust
extern crate self as engine;

pub mod client;
pub mod db;
pub mod generation;
pub mod graph;
pub mod pb;
pub mod prompt;
pub mod rerank;
pub mod retrieval;
pub mod workflow;

pub use pb::lancet::v1::lancet_service_server::LancetService;

#[cfg(test)]
#[path = "tests/workflow_phase5.rs"]
pub mod workflow_phase5;
```

[VERIFIED: `engine/src/lib.rs:1-17` — complete file, quoted verbatim.]

And here is every `mod` declaration in `engine/src/main.rs`:

```
29:mod chunker;
3347:mod tests;
```

with `:3346` being `#[cfg(test)]`. [VERIFIED: `grep -n "^\s*\(pub \)\?mod " engine/src/main.rs` →
exactly two hits; `sed -n '3340,3351p' engine/src/main.rs` confirms `#[cfg(test)]` immediately
precedes `mod tests;`.]

`main.rs` reaches the library through imports, not re-declarations — verbatim from `main.rs:29-36`:

```rust
mod chunker;
use engine::client;
use engine::db;
use engine::generation;
use engine::graph;
use engine::prompt;
use engine::rerank;
use engine::retrieval;
use engine::workflow::{self, ports::Bm25RetrievalPort};
```

**Zero production modules are declared in both targets.** The debt is real but its shape is different
from its label. Restating it accurately, it is **three** problems:

**(a) `chunker` is production code the library cannot see.** `mod chunker;` at `main.rs:29` is the
only declaration; `lib.rs` does not list it. Grepping the library for `chunker` finds only the
unrelated `"chunker_version"` *column name* in `db/mod.rs:211` and three test fixtures — no library
module uses the chunker. So `chunk_fixed_size`, `chunk_markdown`, `estimate_tokens` and `Chunk` are
untestable from the lib target and invisible to any future library consumer.
[VERIFIED: `grep -rn "chunker" engine/src --include=*.rs` excluding `main.rs` and `chunker/` →
`db/mod.rs:211`, `inspect_lancedb_tests.rs:134,528`, `retrieval/tests.rs:169`, all the string
`"chunker_version"`.]

**(b) ~3,351 lines of production code live in the binary.** The items that matter:

| Item | Site | Why it blocks |
|---|---|---|
| `pub struct EffectiveRagSettings` | `engine/src/main.rs:473` | Referenced as `crate::EffectiveRagSettings` from binary tests |
| `pub struct LancetServiceImpl` | `engine/src/main.rs:1044` | The gRPC service itself |
| `impl LancetService for LancetServiceImpl` | `engine/src/main.rs:1686` | Contains `query_rag` — where D-15's validation and D-10/D-12's flag resolution must land |
| `fn load_settings()` | `engine/src/main.rs:591` | Where D-12/D-84's new keys must land |
| ingestion worker + `Settings`/`default_*` fns | throughout `main.rs` | 6.1's rebuild trigger and 6.2's ingestion spans both attach here |

[VERIFIED: `grep -n "pub struct EffectiveRagSettings\|pub struct LancetServiceImpl\|impl LancetService for\|fn load_settings" engine/src/main.rs` →
`473:pub struct EffectiveRagSettings {`, `1044:pub struct LancetServiceImpl {`,
`1686:impl LancetService for LancetServiceImpl {`, `591:fn load_settings() -> Result<Settings, config::ConfigError> {`.]

**(c) The test topology spans three roots and one of them is welded to `main.rs`.**

| Test root | Belongs to target | Declared by | Lines | `#[test]`/`#[tokio::test]` |
|---|---|---|---|---|
| `src/tests/workflow_phase5.rs` | **lib** | `lib.rs:15-17` `#[cfg(test)] #[path = "tests/workflow_phase5.rs"] pub mod workflow_phase5;` | 3,199 | 37 |
| `src/tests.rs` | **bin (`engine`)** | `main.rs:3346-3347` `#[cfg(test)] mod tests;` | 7,415 | 105 |
| `src/tests/workflow_phase5_production.rs` | **bin (`engine`)**, nested | `tests.rs:11` `pub mod workflow_phase5_production;` | 1,473 | 14 |
| `src/inspect_lancedb_tests.rs` | **bin (`inspect_lancedb`)** | `bin/inspect_lancedb.rs:338-339` `#[path = "../inspect_lancedb_tests.rs"] mod tests;` | — | 18 (target count) |
| `tests/config_startup.rs` | **integration** | cargo convention | — | 9 (target count) |

[VERIFIED: `wc -l` and `grep -c` on each file this session; declaration sites read directly.]

**The hard blocker** is that these two roots reach into the binary crate by name:

```rust
// Source: engine/src/tests.rs:1-11 (verbatim head)
use engine::pb::lancet;
use engine::pb::lancet::v1::*;
use super::*;

pub mod workflow_phase5_production;
```

```rust
// Source: engine/src/tests/workflow_phase5_production.rs:5-17 (verbatim)
use crate::{
    db::DatabaseManager,
    generation::{self, AnswerBasis, ModelOutput},
    rerank,
    tests::{configured_service, database_path, FakeEmbedder, FakeGenerator},
    workflow::{ … },
};
use engine::pb::lancet::v1::{self, QueryRagRequest};
```

`use super::*` binds `tests.rs` to *whatever `main.rs` happens to have in scope*. `crate::…` in
`workflow_phase5_production.rs` resolves to the **binary** crate, and `tests::configured_service`
(`tests.rs:1066`) constructs a real `LancetServiceImpl` from `EffectiveRagSettings` — both binary-only
items. **These 119 tests cannot move to the lib target until `EffectiveRagSettings`,
`LancetServiceImpl` and the config machinery move first.** That ordering is the whole plan.

#### The test-count invariant — per target, not aggregate

An aggregate count is the wrong invariant for a refactor that relocates modules between targets: a
module moving from bin to lib keeps the total constant while coverage silently migrates. The
before-state, obtained by enumeration this session:

```
Running unittests src\lib.rs                    133 tests, 0 benchmarks
Running unittests src\main.rs                   128 tests, 0 benchmarks
Running unittests src\bin\inspect_lancedb.rs     18 tests, 0 benchmarks
Running unittests src\bin\seed_rag_fixture.rs     0 tests, 0 benchmarks
Running tests\config_startup.rs                   9 tests, 0 benchmarks
                                                ─────
                                          TOTAL 288 test cases
```

[VERIFIED: `cargo test --manifest-path engine/Cargo.toml -- --list 2>&1 | grep -E "^\s*Running|^[0-9]+ tests"`,
run this session — output quoted verbatim above.]

> **Note the discrepancy with D-80's "285-test suite."** 285 is the count of `#[test]` / `#[tokio::test]`
> *attributes* in the source (`grep -rn "#\[tokio::test\]\|#\[test\]" engine/src engine/tests --include=*.rs | wc -l`
> → `285`). The **runner** enumerates **288 cases**. Both numbers are correct measurements of
> different things; the runner's is the one a gate can assert. The plan should assert **288 total and
> the five per-target counts**, and state the expected post-restructure redistribution up front
> (e.g. "lib 252 / bin 9 / inspect 18 / seed 0 / integration 9, total unchanged at 288").

**Recommended mechanical sequence** (each step compiles and the suite stays green):

1. Move `chunker` into the library: add `pub mod chunker;` to `lib.rs`, delete `mod chunker;` from
   `main.rs:29`, change `use chunker::{…}` → `use engine::chunker::{…}`. Smallest possible first
   step; proves the pipeline.
2. Move config: `Settings`, `EffectiveRagSettings`, the `default_*` fns and `load_settings()` into a
   new library module (e.g. `engine::config`). Update call sites — **no `pub use` shim in `main.rs`**
   (M-SINGLE-ITEM-PATH).
3. Move `LancetServiceImpl` + `impl LancetService` + the ingestion worker into the library
   (e.g. `engine::service`). This is the large step; do it alone.
4. Move `tests.rs` to a library test root. `use super::*` becomes explicit `use engine::…` imports
   against the now-library items. `workflow_phase5_production.rs`'s `crate::…` becomes `engine::…`.
5. `main.rs` becomes startup wiring only. Re-run the per-target enumeration and assert the
   redistribution.

Steps 1–3 are independently commit-able and independently revertible; step 4 is the one that moves
the counts. Reversibility is **costly** per D-80 — this staging is what makes the cost payable.

---

### 2. The Go `main.go` split (D-82) — the seams and the churn

`gateway/main.go` is **1,138 lines** and everything in it is **unexported**. That is the central fact:
every seam crossing is an export decision, and the export decisions *are* the design work.

[VERIFIED: `wc -l gateway/main.go` → `1138`; outline obtained via
`grep -n "^func \|^type \|^var \|^const " gateway/main.go` this session.]

**Package main today comprises three files** — `main.go`, `checkpoint_sink.go`, `main_test.go`
[VERIFIED: `grep -l "^package main" gateway/*.go`]. `gateway/db/` is already its own package.

#### Natural seams, mapped to D-82's four named packages

| D-82 package | Items to move (site in `main.go`) | Must be exported because | Notes |
|---|---|---|---|
| **`internal/config`** | `Config` (:49), `loadConfig()` (:57) | `run()` needs both | `Config` is *already* exported-shaped (`type Config struct` with exported fields + `mapstructure` tags). The cleanest seam in the file. **All `v.BindEnv` strings must survive verbatim** |
| **`internal/engineclient`** | `engine` interface (:214), `grpcEngine` (:221), `IngestOutcome` (:209), `trailerError` (:274-289) | `app` holds an `engine`; `IngestOutcome` is referenced **24×** in `main_test.go` | `trailerError` implements `GRPCStatus()` + `Trailer()`; `handlePreStreamError` type-asserts on `interface{ Trailer() metadata.MD }` — that assertion is structural, so the split does not break it |
| **`internal/sse`** | `writeWorkflowEventSSE` (:803), `writeStreamErrorSSE` (:769), `queryRAGResponseDTO` (:894), `structuredCitationDTO` (:904), `noticeDTO` (:916), `documentFilterDTO` (:922), `retrievalSnapshotDTO` (:927), `toQueryRAGResponseDTO` (:939) | These are `app` methods today; they need either free functions or a small `Writer` type | **This is where D-74's `typed_code` and `metadata` land.** `noticeDTO` gains `TypedCode int32 \`json:"typed_code"\`` |
| **`internal/telemetry`** | *(nothing exists yet)* | — | Empty in Phase 6; created for 6.2 (D-36/D-38/D-43). Creating the directory now with a stub is legitimate; putting OTel code in it is **out of scope** |
| *(residual, not in D-82's four)* | `documentStore` (:99), `postgresStore` (:110-207), `durableReconciler` (:362-472), `app` (:300), the four handlers, `writeJSON`, `newDocumentID`, `formatListenAddr`, `newHTTPServer` | — | D-82 names only four packages. The store/reconciler are a natural fifth (`internal/store`); `app` + handlers a natural sixth (`internal/ragapi` per AI-SPEC §3). **Layout is Claude's Discretion** — the constraint is only that the four named ones exist |

#### The churn number that decides one plan or two

`gateway/main_test.go` is **3,919 lines**, **`package main`**, with **67 `func Test…`**. Its coupling
to items that would move:

| Identifier | Occurrences in `main_test.go` |
|---|---|
| `app{` (composite literal) | **50** |
| `IngestOutcome` | **24** |
| `grpcEngine` | 5 |
| `queryRAGResponseDTO` | 4 |
| `postgresStore` | 4 |
| `maxRAGQueryBodyBytes` | 3 |
| `loadConfig`, `compensateFailedIngest` | 2 each |
| `toQueryRAGResponseDTO`, `noticeDTO`, `newHTTPServer` | 1 each |
| `ragQueryRequestBody`, `writeWorkflowEventSSE`, `writeStreamErrorSSE`, `handlePreStreamError`, `documentStore`, `durableReconciler`, `newDocumentID`, `structuredCitationDTO`, `retrievalSnapshotDTO` | **0** |

[VERIFIED: per-identifier `grep -c` over `gateway/main_test.go` this session; `grep -c "^func Test" gateway` → 67.]

**Read this as a plan-sizing signal.** The zero rows say the SSE writers, the DTO shapes, the request
body type and the reconciler are **not** directly named by tests — they are exercised through
`app{…}.routes()` and `httptest`. So `internal/sse` and `internal/ragapi` can be extracted with
**little test churn**. The 50 `app{` literals and 24 `IngestOutcome` references say the opposite about
`internal/engineclient`: moving `IngestOutcome` and the `engine` interface out of `package main`
forces ~74 test edits (an import + qualifier on each).

**Recommendation: two plans, split on that line.**
- **Plan A (low churn):** `internal/config` + `internal/sse` (+ an empty `internal/telemetry`).
  ~5 test edits.
- **Plan B (high churn):** `internal/engineclient` (+ store/handlers if desired). ~74 mechanical test
  edits; do it alone so the diff is reviewable.

Both are pure refactors; both must keep `go test ./...` green from `gateway/`.

**Idiomatic layout note:** `internal/` is the correct Go home for these — it is compiler-enforced
non-importable from outside `github.com/lancet/gateway`, which is what you want for a service's
private packages. `main.go` retains `main()` and `run()` and becomes wiring only, matching the
already-clean shape of `run()` today (config → pool → grpc client → reconciler → dispatcher →
`app{…}.routes()` → server → signal → shutdown).

---

### 3. The wire contract (D-74) — toolchain, verified codegen shapes, and the churn

#### How bindings are generated today

- **No `build.rs`.** `ls engine/` returns `Cargo.lock`, `Cargo.toml`, `src`, `target`, `tests` — nothing
  else. [VERIFIED this session.]
- Bindings are **committed artifacts**: `engine/src/pb/lancet/v1/lancet.v1.rs`,
  `engine/src/pb/lancet/v1/lancet.v1.tonic.rs`, `gateway/proto/lancet/v1/lancet.pb.go`,
  `gateway/proto/lancet/v1/lancet_grpc.pb.go`.
- Generation is driven by two repo-root files. `buf.gen.yaml`, verbatim:

```yaml
version: v2
clean: false
plugins:
  - remote: buf.build/community/neoeinstein-prost:v0.5.0
    out: engine/src/pb
  - remote: buf.build/community/neoeinstein-tonic:v0.5.0
    out: engine/src/pb
    opt:
      - no_client=true
  - remote: buf.build/protocolbuffers/go:v1.36.5
    out: gateway/proto
    opt:
      - paths=source_relative
  - remote: buf.build/grpc/go:v1.5.1
    out: gateway/proto
    opt:
      - paths=source_relative
```

and `buf.yaml`, verbatim:

```yaml
version: v2
modules:
  - path: proto
    name: buf.build/lancet/lancet
lint:
  use:
    - STANDARD
  except:
    - RPC_RESPONSE_STANDARD_NAME
```

[VERIFIED: `buf.gen.yaml` and `buf.yaml` read in full this session.]

**The regeneration command is `buf generate`, run from the repo root, once.** Both bindings update
together — which is precisely why D-74 wants one edit and one regeneration.

**Lint gate:** `buf.yaml` enables the `STANDARD` lint set. `STANDARD` includes enum-value-prefix
rules — an enum `NoticeCode` must have every value prefixed `NOTICE_CODE_` and a zero value
`NOTICE_CODE_UNSPECIFIED`. AI-SPEC §4.2's table already complies. The plan should run
`buf lint` **and** `buf format --diff --exit-code` as part of the D-74 gate — note that
`03/deferred-items.md` records `DEFERRED-03-12-02` where exactly these two gates were skipped, so
they are not currently part of the habitual local gate. [VERIFIED: `buf.yaml` lint block quoted above;
`DEFERRED-03-12-02` read from `03/deferred-items.md`.]

#### Codegen shapes — empirically verified, not assumed

AI-SPEC Pitfall 3 hinges on `optional bool` producing three-state presence. **No field in the current
`lancet.proto` uses `optional`** [VERIFIED: the complete proto was read this session; the keyword does
not appear], so that shape had never been generated in this repo. It was verified empirically this
session by generating a throwaway probe proto through **the exact plugin versions pinned in
`buf.gen.yaml`** in a scratch directory (since deleted).

**Rust (`neoeinstein-prost:v0.5.0`) — generated verbatim:**

```rust
#[derive(Clone, PartialEq, Eq, Hash, ::prost::Message)]
pub struct Probe {
    #[prost(string, tag="1")]
    pub a: ::prost::alloc::string::String,
    #[prost(bool, optional, tag="2")]
    pub allow_model_only: ::core::option::Option<bool>,
    #[prost(bool, optional, tag="3")]
    pub disable_graph_context: ::core::option::Option<bool>,
}
```

**Go (`protocolbuffers/go:v1.36.5`) — generated verbatim:**

```go
AllowModelOnly      *bool `protobuf:"varint,2,opt,name=allow_model_only,json=allowModelOnly,proto3,oneof" json:"allow_model_only,omitempty"`
DisableGraphContext *bool `protobuf:"varint,3,opt,name=disable_graph_context,json=disableGraphContext,proto3,oneof" json:"disable_graph_context,omitempty"`

func (x *Probe) GetAllowModelOnly() bool {
	if x != nil && x.AllowModelOnly != nil {
		return *x.AllowModelOnly
	}
	// …
}
```

**Enum helpers — generated verbatim (Rust):**

```rust
impl NoticeCode {
    pub fn as_str_name(&self) -> &'static str {
        match self {
            Self::Unspecified => "NOTICE_CODE_UNSPECIFIED",
            Self::GraphUnavailable => "NOTICE_CODE_GRAPH_UNAVAILABLE",
        }
    }
    pub fn from_str_name(value: &str) -> ::core::option::Option<Self> { /* … */ }
}
```

and Go emits `NoticeCode_NOTICE_CODE_GRAPH_UNAVAILABLE NoticeCode = 10` plus `NoticeCode_name` /
`NoticeCode_value` maps and a `String()` method.

[VERIFIED: generated this session with `buf generate` against `neoeinstein-prost:v0.5.0` and
`protocolbuffers/go:v1.36.5` in a scratch module; output quoted verbatim above.]

**Four consequences for the D-74 plan:**
1. `optional bool` → `Option<bool>` in Rust and `*bool` in Go is **confirmed for these exact plugin
   versions**, not inferred. AI-SPEC §4.5's three-state resolution (request → config → false) is
   implementable as written.
2. The Go tag carries `,oneof` (proto3 optional is a synthetic oneof). This is normal and needs no
   handling, but a reviewer seeing `oneof` on a scalar should not treat it as a mistake.
3. `as_str_name()` exists, so AI-SPEC §3's derivation
   (`code.as_str_name().trim_start_matches("NOTICE_CODE_")`) is real generated API. Note that
   `as_str_name` takes `&self` in this plugin version.
4. Prost enums derive `Copy` and prost messages derive `PartialEq, Eq, Hash` — adding `typed_code: i32`
   to `Notice` preserves all of those.

#### The churn number that will decide how the D-74 plan is shaped

| Struct literal | Hand-written sites | Uses `..Default::default()` |
|---|---|---|
| `QueryRagRequest { … }` | **80** (`tests.rs` 32, `tests/workflow_phase5.rs` 37, `tests/workflow_phase5_production.rs` 11; **0** in `main.rs` or `workflow/mod.rs`) | **0** |
| `Notice { … }` | **19** (`tests/workflow_phase5.rs` 13, `workflow/mod.rs` 2, `workflow/events.rs` 2, `nodes/graph_context.rs` 1, `nodes/retrieve.rs` 1) | — |
| `WorkflowCompletedEvent { … }` | 2 | — |

**And the Go-side churn, which the identifier counts in §2 cannot see.** Adding `TypedCode` to
`noticeDTO` and a `metadata` object to the `workflow_completed` payload changes the **JSON bytes** of
every `final_answer` and terminal frame. Go tests that assert payloads do so through `httptest` +
decoding, not by naming `noticeDTO` or `writeWorkflowEventSSE` — which is why those rows read `0`.
The real measurement:

| Probe in `gateway/main_test.go` | Count |
|---|---|
| `json.Unmarshal` | 9 |
| `workflow_completed` | 10 |
| `final_answer` | 5 |
| `"notices"` | 4 |
| `"answer_basis"` | 3 |
| `"severity"` | **0** |
| `"code"` | **0** |
| `JSONEq` / `reflect.DeepEqual` (whole-payload equality) | **0** |

[VERIFIED: per-pattern `grep -c` over `gateway/main_test.go` this session.]

**Read this as: the Go-side D-74 churn is low.** There is **no whole-payload equality assertion**
anywhere — the tests decode and assert *named keys*. An added key is therefore invisible to all 67
tests. The ~9 `json.Unmarshal` sites are the only ones worth a glance, and only if they decode into a
struct without `json:"-"`-style strictness (Go's decoder ignores unknown keys by default, so even
those are safe). **Contrast with the Rust side's ~101 breaking sites** — the asymmetry exists because
Go's `encoding/json` is tolerant by default while Rust struct literals are exhaustive by default.
The consequence for plan sizing: the D-74 Go column is a handful of *additive* edits
(`ragQueryRequestBody` fields, `noticeDTO.TypedCode`, the `metadata` payload object) plus **new**
tests, not a migration.

[VERIFIED: per-file `grep -c` this session;
`grep -rn -A6 "QueryRagRequest {" engine/src --include=*.rs | grep -c "Default::default()"` → `0`.]

A representative literal, verbatim:

```rust
// Source: engine/src/tests/workflow_phase5.rs:238-242
let request = QueryRagRequest {
    query: "Preparation ordering".into(),
    session_id: "sess-generation-prepare".into(),
    filter: None,
};
```

Exhaustive. Adding two fields breaks it, and 79 others like it. Plus 19 `Notice` literals, plus 2
`WorkflowCompletedEvent` literals: **~101 compile errors from one proto edit.**

This is the same failure Phase 05 hit — CONTEXT.md D-74 records it: *"Phase 05 spent plans 05-17 and
05-23 repairing generated-field drift from incremental changes."* D-74 prevents *repeat*
regenerations; it does not by itself prevent the churn of the **one** regeneration it authorizes.

**Recommended containment — a separate, prior, mechanical plan:**

1. **Before** the proto edit, land a plan that introduces test constructors and rewrites all 80
   `QueryRagRequest` literals and the 13 test-side `Notice` literals to use them, e.g.:
   ```rust
   #[cfg(test)]
   pub fn test_query_request(query: &str, session_id: &str) -> QueryRagRequest {
       QueryRagRequest { query: query.into(), session_id: session_id.into(), ..Default::default() }
   }
   ```
   (prost messages derive `Default`, so `..Default::default()` is available without any new code.)
   This commit changes **no behavior** and **no contract** — it is reviewable by inspection.
2. **Then** edit `lancet.proto`, run `buf generate`, and fix only the ~6 remaining production
   literals (`workflow/mod.rs` ×2, `workflow/events.rs` ×2, `graph_context.rs` ×1, `retrieve.rs` ×1)
   plus the notice-constructor introduction. That diff is small enough that the *contract* is what
   gets reviewed.

Without step 1 the D-74 commit is ~101 mechanical edits plus a published-contract change in one diff,
and the contract review D-74 exists to enable does not happen.

#### Backward compatibility — how to keep the change additive

- **Only append field numbers.** `QueryRAGRequest` currently ends at tag 3, `Notice` at 3,
  `WorkflowCompletedEvent` at 6. [VERIFIED: `proto/lancet/v1/lancet.proto`, read in full.]
- **Never renumber or reuse a tag**, never change a field's type, never remove a value from an
  existing enum. `AnswerBasis`, `NoticeSeverity`, `NodeErrorKind`, `RetrievalSnapshot`,
  `StructuredCitation`, `QueryRAGResponse` and the `WorkflowEvent` `oneof` (tags 5–11) are untouched
  per AI-SPEC §4.1.
- **Adding a `NoticeCode` enum does not change `Notice.code`'s meaning** — the string stays first and
  authoritative-on-the-wire-for-old-clients, derived from the enum.
- **New `optional` fields default to absent** for any client that does not set them, so the current
  gateway, the current engine, and any recorded fixture remain valid.
- **The one non-obvious compatibility trap** is Go-side, not proto-side:
  `dec.DisallowUnknownFields()` at `gateway/main.go:677` means a JSON body containing
  `allow_model_only` is a **hard HTTP 400** until `ragQueryRequestBody` grows the field. A D-74 plan
  that stops at "regenerate bindings" leaves the HTTP surface rejecting the very flag it just
  published. [VERIFIED: `gateway/main.go:671-696` read this session — `dec.DisallowUnknownFields()`
  followed by `http.Error(w, "invalid request body", http.StatusBadRequest)` on decode failure.]

---

### 4. Where the behavior changes land

#### D-10 — the `ModelOnly` guard, verbatim

```rust
// Source: engine/src/generation/mod.rs — validate_grounding_with_limits (~:167-176)
pub fn validate_grounding_with_limits(
    &self,
    packed_evidence: &[EvidenceBlock],
    limits: GroundingLimits,
) -> Result<(), GenerationError> {
    if self.answer_basis == AnswerBasis::ModelOnly {
        return Err(GenerationError::new(
            GenerationErrorKind::SchemaValidation,
            "ModelOnly answer basis is not supported on Phase 03 QueryRAG path",
        ));
    }
```

[VERIFIED: `engine/src/generation/mod.rs:140-220` read this session.]

The signature takes `&self`, `packed_evidence` and `limits` — **no channel for the opt-in**. There is
also a convenience wrapper immediately above it:

```rust
pub fn validate_grounding(&self, packed_evidence: &[EvidenceBlock]) -> Result<(), GenerationError> {
    self.validate_grounding_with_limits(packed_evidence, GroundingLimits::default_limits())
}
```

So **two** call surfaces must be considered. AI-SPEC Pitfall 1 is right that threading the flag here
is a design task; the concrete options are (a) extend `GroundingLimits` with the resolved flag —
smallest signature churn, and `GroundingLimits` is already the "policy" parameter; or (b) add a third
parameter. Option (a) keeps both call surfaces working and is recommended, but the **naming** matters:
`GroundingLimits` currently means numeric ceilings, so a boolean policy field needs a doc comment
(`rust-guidelines.md` M-DOCUMENTED-MAGIC).

A further consequence the plan must handle: immediately after the `ModelOnly` guard,
`validate_grounding_with_limits` also rejects an **empty `cited_evidence_ids`**:

```rust
if self.cited_evidence_ids.is_empty() {
    return Err(GenerationError::new(
        GenerationErrorKind::SchemaValidation,
        format!("answer basis '{}' requires at least one cited evidence ID", self.answer_basis),
    ));
}
```

D-10 requires `MODEL_ONLY` answers to carry **zero citations**. So lifting only the first guard leaves
the second one rejecting every model-only answer. **Both guards must become conditional on the
resolved flag.** This is not stated in the AI-SPEC and is the most likely single cause of a D-10 plan
appearing complete and failing at runtime.

#### D-13 — the retrieval-path failure sites, and the one enum value that is unreachable

> **This subsection corrects two things.** It was the last open assumption in this research and it
> did **not** hold. Both corrections must reach the D-74 plan **before** the proto lands, because one
> of them concerns a published enum value.

**Finding 1 — D-13 is a fail-closed→degrade behavior change, not a notice addition.**

`RetrieveHybridNode::execute` returns `Err` on *either* retrieval path failing. Verbatim, the two
sites:

```rust
// Source: engine/src/workflow/nodes/retrieve.rs — dense path (~:63-77)
let dense_candidates = if let Some(dense_port) = &self.dense_port {
    match dense_port
        .retrieve_dense(&ctx.original_query, embedding, ctx.filter.as_ref(), cancel)
        .await
    {
        Ok(c) => c,
        Err(err) => return Err(err),
    }
} else {
    Vec::new()
};

// Source: engine/src/workflow/nodes/retrieve.rs — BM25 path, inside the per-variant loop (~:97-108)
let bm25_candidates = if let Some(bm25_port) = &self.bm25_port {
    match bm25_port
        .retrieve_bm25(variant, ctx.filter.as_ref(), cancel)
        .await
    {
        Ok(c) => c,
        Err(err) => return Err(err),
    }
} else {
    Vec::new()
};
```

[VERIFIED: `engine/src/workflow/nodes/retrieve.rs:1-200` read in full this session.]

Answering the two questions this raises:

- **(a) Are the two failures individually observable?** **Yes** — they are two distinct `match`
  arms at two distinct call sites, so D-13 can attach `RETRIEVAL_DEGRADED_DENSE` at the first and
  `RETRIEVAL_DEGRADED_BM25` at the second. The split-by-path design is implementable.
- **But the change is larger than attaching a notice.** Today `return Err(err)` produces
  `NodeFailed` + a terminal *failure*. D-13 requires `Ok(())` + notice + an **empty candidate vector
  for that path**, so fusion proceeds on the surviving path. That is a **conversion of a fail-closed
  path into a degrade path** — the single most consequential edit in the phase's behavior work, and
  the one most likely to break existing tests that assert the current failure.
- **Note the asymmetry the loop creates:** the BM25 call is inside `for (variant_index, variant) in
  ctx.variants.iter().enumerate()`. A BM25 failure on variant *k* must not discard variants *0..k*.
  The degrade must be per-variant-tolerant (skip that variant's BM25 contribution), not a
  whole-node abort.
- **`None` ports already degrade silently to `Vec::new()`** in both branches — no notice. That is a
  third silent-degrade path this phase should consider, symmetric with D-08's absent-`graph_port`
  case. It is not named by any decision; flagging it, not scoping it.

**Finding 2 — `RETRIEVAL_DEGRADED_GRAPH` is unreachable by construction. Do not publish it.**

AI-SPEC §4.2 declares `NOTICE_CODE_RETRIEVAL_DEGRADED_GRAPH = 17` with the comment *"graph path
failing within retrieval fusion; distinct from GRAPH_UNAVAILABLE (D-08, node-level)."* **There is no
graph path within retrieval fusion.**

```rust
// Source: engine/src/workflow/nodes/retrieve.rs:13-20 — the node's complete port set
pub struct RetrieveHybridNode {
    dense_port: Option<Arc<dyn DenseRetrievalPort>>,
    bm25_port: Option<Arc<dyn Bm25RetrievalPort>>,
    reranker: Option<Arc<dyn Reranker>>,
    settings: RetrievalSettings,
    index_generation: String,
    embedding_model: String,
}
```

No `GraphQueryPort`. Its imports are `ports::{Bm25RetrievalPort, DenseRetrievalPort}` only, and
`grep -n "graph" engine/src/workflow/nodes/retrieve.rs` returns **zero hits** in the entire file.
Graph facts reach the answer on a different route entirely — `graph_context.rs` sets
`ctx.graph_facts` (`:114`, `:128`, `:133`, `:149`), `assemble_prompt.rs:80,91` packs and
score-interleaves them, `generate.rs:96` sends them. The retrieval node never sees them.

[VERIFIED: `engine/src/workflow/nodes/retrieve.rs:1-235` read in full — struct definition and imports
quoted verbatim; `grep -n "graph" engine/src/workflow/nodes/retrieve.rs` → no output;
`grep -rn "graph_facts" engine/src/workflow --include=*.rs` → the flow above.]

**Recommendation for the D-74 plan — decide this before the proto edit:**

> **D-13 is two codes, not three.** Publish `RETRIEVAL_DEGRADED_DENSE` and `RETRIEVAL_DEGRADED_BM25`.
> **Do not publish `RETRIEVAL_DEGRADED_GRAPH`**, or reserve tag 17 with a `reserved 17;` /
> `// reserved for a future in-fusion graph path` comment rather than defining a value that nothing
> can ever emit. D-76 makes enum values one-way published contract; shipping a permanently-dead value
> in the very change that establishes the vocabulary is exactly the kind of thing that is free to
> avoid now and impossible to remove later. Graph degradation is already fully covered node-level by
> `GRAPH_TIMEOUT` / `GRAPH_DEGRADED` / D-08's `GRAPH_UNAVAILABLE`.

*(This is squarely within "Exact enum value names are Claude's Discretion" — CONTEXT.md D-13 requires
"a machine-readable notice naming the failed path," and there are two failable paths.)*

#### D-13 — where the notice attaches relative to `NO_EVIDENCE`

`retrieve.rs` builds the snapshot and then emits the zero-evidence notice, verbatim:

```rust
// Source: engine/src/workflow/nodes/retrieve.rs (~:191-198)
// 5. Zero evidence check
if ctx.final_candidates.is_empty() {
    ctx.add_notice(Notice {
        code: "NO_EVIDENCE".into(),
        message: "No completed corpus evidence matched the requested filters.".into(),
        severity: NoticeSeverity::Info as i32,
    });
}
```

[VERIFIED: `engine/src/workflow/nodes/retrieve.rs:170-200` read this session.]

D-13's per-path notices attach at the two `Err(err) => return Err(err)` sites quoted above, which run
**before** this block. Note the interaction: if *both* paths degrade, `final_candidates` ends empty
and **`NO_EVIDENCE` also fires** — so a both-paths-failed query carries three notices
(`RETRIEVAL_DEGRADED_DENSE`, `RETRIEVAL_DEGRADED_BM25`, `NO_EVIDENCE`). That is the correct shape,
and it is **exactly the observable state D-10's opt-in consumes**: after D-13, "both retrieval paths
fail" and "evidence is absent" converge, which is what lets one opt-in cover both of D-10's stated
triggers. **Order the plans D-13 → D-10.**

#### D-08 — already covered under Pattern 1 above. Two `ctx.add_notice(...)` calls.

#### D-15 is mostly test work — the validation already exists

The full `RetrievalErrorKind` taxonomy, verbatim:

```rust
// Source: engine/src/retrieval/mod.rs:42-52
pub enum RetrievalErrorKind {
    EmptyQuery,
    QueryTooLong,
    InvalidDocumentId,
    UnsupportedContentType,
    EmptyFilterValue,
    FilterLimitExceeded,
    InvalidSettings,
    NonFiniteScore,
    Snapshot,
}
```

The mapping to stable gRPC codes and stable error-kind strings, verbatim:

```rust
// Source: engine/src/main.rs:1846-1870 (inside query_rag)
let (code, err_kind_str) = match err.kind {
    RetrievalErrorKind::EmptyQuery => (tonic::Code::InvalidArgument, "empty_query"),
    RetrievalErrorKind::QueryTooLong => {
        (tonic::Code::InvalidArgument, "query_too_long")
    }
    RetrievalErrorKind::InvalidDocumentId => {
        (tonic::Code::InvalidArgument, "invalid_document_id")
    }
    RetrievalErrorKind::UnsupportedContentType => {
        (tonic::Code::InvalidArgument, "unsupported_content_type")
    }
    RetrievalErrorKind::EmptyFilterValue => {
        (tonic::Code::InvalidArgument, "empty_filter_value")
    }
    RetrievalErrorKind::FilterLimitExceeded => {
        (tonic::Code::InvalidArgument, "filter_limit_exceeded")
    }
    RetrievalErrorKind::InvalidSettings => {
        (tonic::Code::InvalidArgument, "invalid_settings")
    }
    RetrievalErrorKind::NonFiniteScore => {
        (tonic::Code::Internal, "non_finite_score")
    }
    RetrievalErrorKind::Snapshot => (tonic::Code::Internal, "snapshot"),
};
d1_status(code, err.message(), &session_id, &correlation_id, err_kind_str)
```

The session-ID check, verbatim:

```rust
// Source: engine/src/main.rs:1808-1830 (inside query_rag)
let session_id = if req.session_id.trim().is_empty() {
    Uuid::new_v4().to_string()
} else {
    let raw_session_id = req.session_id.trim().to_string();
    let parsed = Uuid::parse_str(&raw_session_id).map_err(|_| {
        d1_status(
            tonic::Code::InvalidArgument,
            "session_id must be a valid UUIDv4 string",
            &raw_session_id,
            &correlation_id,
            "invalid_session_id",
        )
    })?;
    if parsed.get_version_num() != 4 || parsed.get_variant() != uuid::Variant::RFC4122 {
        return Err(d1_status(
            tonic::Code::InvalidArgument,
            "session_id must be a valid UUIDv4 string",
            &raw_session_id,
            &correlation_id,
            "invalid_session_id",
        ));
    }
    parsed.to_string()
};
```

And the document-ID check on the ingestion path:

```rust
// Source: engine/src/main.rs:1217-1222
fn validate_document_id(document_id: &str) -> Result<(), Status> {
    …
        .map_err(|_| Status::invalid_argument("document_id must be a UUIDv4 string"))?;
```

[VERIFIED: `engine/src/retrieval/mod.rs:42-52`; `engine/src/main.rs:1808-1870`, `:1217-1222` — all
read this session and quoted verbatim.]

**Structural fact that closes DEBT-RAG-05's "before retrieval or provider work" clause:** the
validation call is `let _query_request = QueryRequest::from_values(…)` — the underscore says the
constructed request is **discarded**; it is invoked purely for its validating side effect, and it runs
inside `query_rag` **before** the mpsc channel, the `CancellationToken` and the workflow stream are
created. Rejection therefore happens before any retrieval or provider work by construction.

**On the HTTP side, the gateway performs no field validation at all** — `queryRAG` bounds the body
(`http.MaxBytesReader(w, r.Body, maxRAGQueryBodyBytes)`, `maxRAGQueryBodyBytes = 32 << 10`), rejects
unknown fields and trailing JSON, builds `pb.QueryRAGRequest`, and forwards. HTTP 400 for a bad
*field* arrives via the engine:

```go
// Source: gateway/main.go:796-800 (handlePreStreamError)
if status.Code(err) == codes.InvalidArgument {
    http.Error(w, status.Convert(err).Message(), http.StatusBadRequest)
    return
}
http.Error(w, "engine query failed", http.StatusBadGateway)
```

[VERIFIED: `gateway/main.go:671-700`, `:782-802` read this session.]

**So D-15's plan is:**
- The **table is the artifact** (D-15). Build it from the eight existing `InvalidArgument` error-kind
  strings plus `invalid_session_id`.
- The **gRPC surface test** drives the engine's `query_rag` and asserts `(code, err_kind_str)` per row.
- The **HTTP surface test** drives `/rag/query` through `httptest` and asserts status 400 +
  `X-Lancet-Error-Kind` per row — **deriving** from the gRPC layer, not duplicating rules in Go.
- **Only two of D-15's enumerated rows may lack an existing code path:** "contradictory" and
  "unmatched" filters. `EmptyFilterValue` / `FilterLimitExceeded` / `InvalidDocumentId` /
  `UnsupportedContentType` cover the rest. A plan-time check should confirm whether an *unmatched*
  filter is an error at all — Phase 03 D2 shipped a **valid zero-match success branch**
  (`03/deferred-items.md`: *"Only D2's valid zero-match success branch is shipped"*), which means
  "unmatched" is legitimately a `NO_EVIDENCE` success, **not** a 400. **The plan must record that
  disposition explicitly** rather than adding a rejection that contradicts Phase 03.

---

### 5. The Phase 05 `cfg(test)` fake-port seam (D-83) — what exists and what to add

`engine/src/workflow/ports.rs` defines four production port traits and, under `#[cfg(test)]`, a fake
for each plus a fake reranker. The **constructor vocabulary is uniform**:

| Fake | `success(...)` | `failure(NodeError)` | `stall()` | `calls()` | Extra |
|---|---|---|---|---|---|
| `FakeQueryReformulator` | ✓ (`new(variants)`) | — | — | — | — |
| `FakeQueryEmbeddingPort` | ✓ | ✓ | ✓ | ✓ | — |
| `FakeGraphQueryPort` | ✓ (via `IntoGraphFacts`) | ✓ | ✓ | ✓ | `IntoGraphFacts` accepts `&str`, `String`, `Vec<String>`, `Vec<GraphFactBlock>` |
| `FakeDenseRetrievalPort` | ✓ | ✓ | ✓ | ✓ | — |
| `FakeBm25RetrievalPort` | ✓ | ✓ | ✓ | ✓ | `with_map(Vec<(String, Result<…>)>)` — per-query responses |
| `FakeReranker` (impl of `crate::rerank::Reranker`) | ✓ | ✓ | — | ✓ | — |
| `FakeGenerator` (`engine/src/generation/mod.rs:504`) | `new(Result<ModelOutput, …>)` | same ctor with `Err` | — | — | queue-based; errors with `"FakeGenerator ran out of configured responses"` when exhausted |
| `FakeEmbedder` (`engine/src/tests.rs:526`) | — | — | — | — | binary-target only |

`stall()` is implemented as `tokio::time::sleep(std::time::Duration::from_secs(3600)).await` before
returning — a **timeout** fake driven by tokio's paused clock (`test-util` is an enabled feature in
`engine/Cargo.toml`). [VERIFIED: `engine/src/workflow/ports.rs` read in full this session;
`engine/src/generation/mod.rs:504-545`; `engine/Cargo.toml` tokio features
`["rt-multi-thread", "macros", "time", "sync", "test-util"]`.]

**Mapping D-83's four required failure modes onto what exists:**

| D-83 mode | Status | Action |
|---|---|---|
| **error** | **Exists** — `failure(NodeError)` on every port; `FakeGenerator::new(Err(GenerationError…))` | None. D-13's per-path tests use `FakeDenseRetrievalPort::failure(...)` / `FakeBm25RetrievalPort::failure(...)` directly |
| **timeout** | **Exists** — `stall()` on the four I/O ports | None for the ports. `FakeGenerator` has **no `stall()`** — add one if a generation-timeout test is needed |
| **empty** | **Expressible, not named** — `success(vec![])` / `FakeGraphQueryPort::success(Vec::<GraphFactBlock>::new())` | A named `empty()` constructor would make D-08's empty-result test read as intent rather than as an accident. Cheap and worth it |
| **malformed citation** | **Missing** — this is the one genuinely new fake | Add a `FakeGenerator` constructor producing a `ModelOutput` whose `cited_evidence_ids` do **not** resolve against the packed evidence: near-miss (case/whitespace variants of a real ID) for `CITATION_REPAIRED`, and unresolvable for `CITATION_DROPPED`. This is D-14's entire test surface |

**Two constraints on how the seam is extended:**
1. **No production fault-injection switch** (D-83, verbatim). Everything stays behind `#[cfg(test)]`.
2. There is a **guard test** asserting `FakeGenerator` stays `cfg(test)`-gated:
   `engine/src/tests/workflow_phase5.rs:2435-2440` reads `generation/mod.rs` as text and locates
   `"pub struct FakeGenerator"` relative to a `cfg(test)` marker. **A plan that moves `FakeGenerator`
   or reformats that region will break a test that greps source text.** [VERIFIED:
   `engine/src/tests/workflow_phase5.rs:2435-2440` — `// 2. Verify generation/mod.rs has FakeGenerator gated under cfg(test)`
   and `let fake_gen_pos = gen_src.find("pub struct FakeGenerator")`.] This interacts directly with
   the D-80 restructure: **moving `generation/` is safe** (it is already a library module), but
   reorganizing within it is not free.

---

### 6. Config knob handling (D-84) — the current pattern is fail-**open**, and that is the point

**Engine.** `load_settings()` builds from TOML + `config::Environment::with_prefix("LANCET").separator("__")`,
then applies an explicit per-key override block. The numeric pattern, verbatim:

```rust
// Source: engine/src/main.rs:631-635
if let Ok(value) = std::env::var("LANCET_ENGINE__WORKFLOW__REFORMULATE_TIMEOUT_MS") {
    if let Ok(val) = value.trim().parse::<u64>() {
        settings.engine.workflow.reformulate_timeout_ms = val;
    }
}
```

and the string pattern, verbatim:

```rust
// Source: engine/src/main.rs:621-625
if let Ok(value) = std::env::var("LANCET_ENGINE__GRPC_ADDR") {
    if !value.trim().is_empty() {
        settings.engine.grpc_addr = value;
    }
}
```

with the block's own comment explaining why it exists:

```rust
// Keep the process-test and deployment override names explicit at the
// boundary. This also makes the double-underscore contract independent of
// config crate version-specific environment parsing details.
```

[VERIFIED: `engine/src/main.rs:591-702` read in full this session; the three excerpts are verbatim.]

**Both patterns silently discard an invalid value.** `LANCET_ENGINE__WORKFLOW__RETRIEVE_TIMEOUT_MS=abc`
parses to `Err`, the `if let` does not fire, and the TOML value stands with **no warning**. That is
`DEBT-P3-WARN-SETTINGS` — STATE.md lists it as *"Env ignore, scalar vs carrier dual budget, chunk
limit saturation"* [VERIFIED: `.planning/STATE.md:96`]. D-84 says existing keys **keep** this
behavior; only **new Phase 6 keys** fail closed.

**The idiomatic fail-closed shape for new keys**, matching the file's existing error type
(`load_settings` returns `Result<Settings, config::ConfigError>`):

```rust
// Present-but-invalid ⇒ hard error. Absent ⇒ TOML/default stands.
if let Ok(raw) = std::env::var("LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS") {
    let trimmed = raw.trim();
    if !trimmed.is_empty() {
        settings.engine.workflow.allow_model_only_answers = match trimmed {
            "true"  | "1" => true,
            "false" | "0" => false,
            other => return Err(config::ConfigError::Message(format!(
                "LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS must be true/false, got {other:?}"
            ))),
        };
    }
}
```

Three deliberate properties: (1) `return Err(...)` rather than a silent skip — that *is* D-84;
(2) empty-string is treated as absent, matching the existing string-override convention so an unset
CI-style `VAR=` does not hard-fail; (3) the error names the key and shows the offending value, so the
failure is diagnosable. Note that `config::ConfigError::Message` is the variant already in this
function's return type, so no new error plumbing is needed.

**There is a second validation layer already in place** worth reusing rather than duplicating:
`Settings::validate()` (`main.rs:257`), `validate_against_provider()` (`:291`) and a second
`validate()` at `:534` all return `Result<(), String>` and run **after** deserialization. A new
boolean has nothing to validate, but D-15's `max_query_chars`-style numeric bound belongs here, next
to the existing `query_max_bytes` / `max_document_ids` / `max_content_types` fields (`main.rs:372-377`),
**not** as a fresh constant. [VERIFIED: `grep -n "fn validate" engine/src/main.rs` → `:257`, `:291`,
`:534`; field declarations at `:372-377`.]

**Existing TOML surface for the new keys**, verbatim from `config/config.toml`:

```toml
[engine.workflow]
reformulate_timeout_ms = 5000
query_embedding_timeout_ms = 10000
retrieve_timeout_ms = 10000
graph_operation_timeout_ms = 4000
graph_node_timeout_ms = 15000
prompt_timeout_ms = 2000
generation_node_timeout_ms = 65000

[engine.retrieval]
candidate_limit = 32
final_limit = 8
query_max_bytes = 8192
max_document_ids = 100
max_content_types = 16
…
```

[VERIFIED: `config/config.toml` read in full this session.]

`[engine.workflow]` is the natural home for `allow_model_only_answers` and `citation_repair_enabled`;
`[engine.retrieval]` already owns the input bounds D-15 documents.

**Gateway.** `loadConfig()` uses viper with `SetEnvPrefix("LANCET")`,
`SetEnvKeyReplacer(strings.NewReplacer(".", "__"))`, `AutomaticEnv()`, and **three explicit
`BindEnv` calls** — `gateway.port`, `gateway.database_url`, `gateway.engine_addr`. It already
fails closed on two conditions (empty `database_url`; `sslmode=disable` when `LANCET_ENV=prod`),
both returning `errors.New(...)`. [VERIFIED: `gateway/main.go:49-98` read this session.]

**Phase 6 adds no gateway config keys** — the two new request flags are per-request, and the engine
owns their defaults. The gateway's only config obligation is that the D-82 move preserves the three
`BindEnv` strings byte-for-byte.

---

## Common Pitfalls

> AI-SPEC §3 "Common Pitfalls" lists nine. Those are not repeated. These are the ones this
> session's code reading surfaced that the AI-SPEC does not carry.

### Pitfall A: Lifting only the first `ModelOnly` guard
**What goes wrong:** D-10 lands, the `AnswerBasis::ModelOnly` rejection is made conditional, and every
model-only answer still fails with *"answer basis 'ModelOnly' requires at least one cited evidence ID."*
**Why it happens:** `validate_grounding_with_limits` has **two** guards that a zero-citation
model-only answer trips — the basis check at `:172-175` and the `cited_evidence_ids.is_empty()` check
a few lines below. CONTEXT.md and the AI-SPEC both name only the first.
**How to avoid:** make **both** conditional on the resolved flag; add a test asserting a `MODEL_ONLY`
`ModelOutput` with `cited_evidence_ids: vec![]` validates clean when opted in and is rejected when not.
**Warning signs:** a `SchemaValidation` error mentioning "cited evidence ID" on the opt-in path.

### Pitfall B: Amending only one of the two zero-evidence gates
**What goes wrong:** `run_workflow` honors the opt-in; `run_tracer` still short-circuits. Production
and tracer paths diverge silently.
**Why it happens:** `runner.rs` has the gate twice, in different shapes, ~55 lines apart.
**How to avoid:** amend both; note that `run_workflow`'s gate has a **second disjunct**
(`final_candidates.is_empty() && evidence_blocks.is_empty()`) that must also be bypassed.
**Warning signs:** a test that passes via `run_workflow` and fails via `run_tracer`, or vice versa.

### Pitfall B2: Treating D-13 as "add a notice" when it is "convert fail-closed to degrade"
**What goes wrong:** the plan budgets a one-line `ctx.add_notice(...)` for D-13, then discovers that
both retrieval paths currently `return Err(err)` — a terminal workflow failure — and that turning
either into `Ok(())` changes existing test expectations, changes what the terminal event carries, and
must be per-variant-tolerant inside the BM25 loop.
**Why it happens:** D-13's wording ("keeps `answer_basis = RETRIEVAL` with a machine-readable notice")
describes the *destination*, not the *distance*. The origin is fail-closed.
**How to avoid:** size D-13 as a behavior change on a fail-closed path. Its tests must assert the
**absence** of `NodeFailed` and of a failure terminal, not just the presence of a notice.
**Warning signs:** a D-13 task whose only verification is "notice present."

### Pitfall B3: Publishing a notice-code value nothing can emit
**What goes wrong:** `NOTICE_CODE_RETRIEVAL_DEGRADED_GRAPH = 17` ships in the D-74 change. It is
unreachable — `RetrieveHybridNode` holds no graph port and the file contains no reference to graph at
all. D-76 makes enum values one-way published contract, so a dead value is permanent.
**Why it happens:** AI-SPEC §4.2 declares it, with a plausible-sounding comment about "the graph path
failing within retrieval fusion," and the D-74 plan will implement §4.2 literally.
**How to avoid:** ship two `RETRIEVAL_DEGRADED_*` values, or `reserved 17;`. Graph degradation is
already covered node-level by `GRAPH_TIMEOUT` / `GRAPH_DEGRADED` / `GRAPH_UNAVAILABLE`.
**Warning signs:** a `NoticeCode` variant with no emission site in the same phase.

### Pitfall C: A `pub use` shim that makes the restructure look done
**What goes wrong:** `EffectiveRagSettings` moves to the library, `main.rs` gains
`pub use engine::config::EffectiveRagSettings;`, the 128 binary tests keep compiling, the suite is
green, and DEBT-P3-MODULE-GRAPH is **not** closed — the item is now reachable through two paths.
**Why it happens:** it is the path of least resistance and it compiles.
**How to avoid:** `rust-guidelines.md` M-SINGLE-ITEM-PATH forbids it by name and calls out this exact
agent behavior. Verify by grepping for `pub use` added to `main.rs` — the answer should be zero.
**Warning signs:** any new `pub use` in `main.rs`; test files still saying `crate::` for a library item.

### Pitfall D: Asserting one aggregate test count across the restructure
**What goes wrong:** a module moves from bin to lib, total stays 288, and nobody notices that 40
tests changed target — or that a `#[cfg(test)]` module became unreachable and its tests silently
stopped running.
**How to avoid:** assert the **five per-target counts** before and after, and state the intended
redistribution in the plan up front.
**Warning signs:** total matches but any single target's count changed unexplained.

### Pitfall E: Regenerating one binding tree and not the other
**What goes wrong:** `engine/src/pb/` updates, `gateway/proto/` does not (or vice versa). The Rust
engine sends a field the Go gateway cannot parse.
**Why it happens:** `buf generate` writes to four output paths from one invocation, but a partial
`git add` splits them.
**How to avoid:** one commit containing `proto/lancet/v1/lancet.proto` **and** all four generated
files. `git status` after `buf generate` should show exactly five modified files.
**Warning signs:** a commit touching `engine/src/pb/` without `gateway/proto/`.

### Pitfall F: Breaking the source-text guard test
**What goes wrong:** `workflow_phase5.rs:2435-2440` reads `generation/mod.rs` **as text** and asserts
`"pub struct FakeGenerator"` appears after a `cfg(test)` marker. Reformatting, reordering or moving
that region fails a test with a confusing message.
**How to avoid:** treat `generation/mod.rs`'s `cfg(test)` region as load-bearing text. If D-14 adds a
`generation/citations.rs`, put the new fakes there and leave `FakeGenerator` where it is.

### Pitfall G: Using Go 1.26 idioms on a Go 1.25 target
**What goes wrong:** `new(true)` for the `*bool` request fields compiles locally (toolchain is
go1.26.5) but violates `go-guidelines.md`'s explicit "never use features from newer Go versions than
the target," and `go.mod` targets 1.25.
**How to avoid:** local variable + address-of, or a tiny generic helper.
**Warning signs:** `new(` applied to a value rather than a type; `errors.AsType[`.

### Pitfall H: Publishing the flags without updating `ragQueryRequestBody`
**What goes wrong:** the proto and both bindings land; a client posts `{"allow_model_only": true}`;
`dec.DisallowUnknownFields()` returns HTTP 400 *"invalid request body."* The field is published and
unusable.
**How to avoid:** AI-SPEC §4.1's three-column rule — every row lands in proto **and** Go **and** has a
reader, in the same plan. Add a gateway test posting each new field and asserting 200-or-engine-error,
never 400.

### Pitfall I: Rejecting an "unmatched" filter as bad input
**What goes wrong:** D-15's matrix lists "unmatched" among the filter bounds, and a plan adds a 400
for filters that match no documents — contradicting Phase 03 D2's shipped **valid zero-match success
branch** (`NO_EVIDENCE` + HTTP 200).
**How to avoid:** the matrix row for "unmatched" must be dispositioned as *success with `NO_EVIDENCE`*,
recorded explicitly, not silently converted to a rejection.

### Pitfall J: Setting `typed_code` without deriving `code`
**What goes wrong:** `add_notice` de-duplicates on `(code, message)`. A site that sets
`typed_code: NoticeCode::X as i32` and leaves `code: String::new()` changes the de-dup key for that
notice, so two semantically different notices can collapse — or a repeat can stop collapsing.
**How to avoid:** exactly one notice constructor (AI-SPEC §3), used everywhere; a test asserting
every emitted notice has non-empty `code` and a `typed_code` whose `as_str_name()` derives that `code`.

---

## Code Examples

### Verifying the regeneration touched both trees

```bash
# Source: buf.gen.yaml (repo root) — one invocation writes all four generated files
buf lint
buf format --diff --exit-code
buf generate
git status --porcelain
# Expect EXACTLY these five paths modified:
#   proto/lancet/v1/lancet.proto
#   engine/src/pb/lancet/v1/lancet.v1.rs
#   engine/src/pb/lancet/v1/lancet.v1.tonic.rs
#   gateway/proto/lancet/v1/lancet.pb.go
#   gateway/proto/lancet/v1/lancet_grpc.pb.go
```

### Asserting the per-target test invariant across the restructure

```bash
# Source: cargo, run this session to establish the before-state
cargo test --manifest-path engine/Cargo.toml -- --list 2>&1 \
  | grep -E "^\s*Running|^[0-9]+ tests"
# Before:  lib 133 · bin(engine) 128 · bin(inspect_lancedb) 18 · bin(seed_rag_fixture) 0 · integration 9  = 288
```

### The three-state opt-in resolution (D-10/D-12), using the verified generated shape

```rust
// Generated shape VERIFIED this session against neoeinstein-prost:v0.5.0:
//   pub allow_model_only: ::core::option::Option<bool>
//
// Resolve ONCE, at admission in query_rag, into WorkflowContext (AI-SPEC §4.5).
let allow_model_only: bool = req
    .allow_model_only                                  // Some(true) | Some(false) | None
    .unwrap_or(self.effective_settings.workflow.allow_model_only_answers);
```

### The gateway side, on a Go 1.25 target (no `new(true)`)

```go
// Source shape VERIFIED this session against protocolbuffers/go:v1.36.5:
//   AllowModelOnly *bool `protobuf:"varint,4,opt,...,proto3,oneof" json:"allow_model_only,omitempty"`
type ragQueryRequestBody struct {
	Query     string `json:"query"`
	SessionID string `json:"session_id"`
	Filter    *struct {
		DocumentIDs  []string `json:"document_ids"`
		ContentTypes []string `json:"content_types"`
	} `json:"filter"`
	AllowModelOnly      *bool `json:"allow_model_only"`
	DisableGraphContext *bool `json:"disable_graph_context"`
}

// *bool passes through unchanged — presence is preserved, no Go 1.26 new() needed.
req := &pb.QueryRAGRequest{Query: body.Query, SessionId: body.SessionID}
req.AllowModelOnly = body.AllowModelOnly
req.DisableGraphContext = body.DisableGraphContext
```

### Containing the 80-site struct-literal churn before the proto edit

```rust
// prost messages derive Default, so this needs no new code beyond the helper itself.
#[cfg(test)]
pub fn test_query_request(query: &str, session_id: &str) -> QueryRagRequest {
    QueryRagRequest {
        query: query.into(),
        session_id: session_id.into(),
        ..Default::default()
    }
}

// Before (80 sites like this — VERIFIED verbatim at tests/workflow_phase5.rs:238-242):
//   let request = QueryRagRequest {
//       query: "Preparation ordering".into(),
//       session_id: "sess-generation-prepare".into(),
//       filter: None,
//   };
// After:
let request = test_query_request("Preparation ordering", "sess-generation-prepare");
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact on Phase 6 |
|---|---|---|---|
| Ad-hoc string notice codes (`"NO_EVIDENCE"`, `"GRAPH_TIMEOUT"`, `"NOTICE"`, `"WARNING"`) invented at emission sites | Typed proto enum, string derived from it (D-76) | Phase 6 | Two `pub const` centralizations already exist (`workflow/mod.rs:28-29` — `GRAPH_TIMEOUT`, `GRAPH_DEGRADED`) but are **not used** by `graph_context.rs`, which uses bare literals. The enum finishes the job |
| Incremental proto edits, one field at a time | One consolidated additive change, one regeneration (D-74) | Phase 6 | Phase 05 paid two repair plans (05-17, 05-23) for the old way |
| `bool` request fields | proto3 `optional bool` for explicit presence | Phase 6 | **First use of `optional` in this repo** — the shape was verified empirically this session rather than assumed |
| Production code in `main.rs`, library used as a partial mirror | Library owns all production modules; binary is wiring (D-80) | Phase 6 | Phase 05 plan 05-18 already moved BM25 ownership and built the library test target — D-80 completes that direction |
| `main.go` as a single 1,138-line `package main` | `internal/` packages (D-82) | Phase 6 | Pre-emptive: D-82's stated rationale is "rather than growing past 1,500 lines" once 6.2's telemetry lands |
| Env override silently ignores an unparseable value | New keys `return Err(...)` on present-but-invalid (D-84) | Phase 6 | Contains `DEBT-P3-WARN-SETTINGS` rather than multiplying it; **existing keys deliberately unchanged** |

**Deprecated / superseded within this project:**
- Phase 05 D-03's unconditional zero-evidence short-circuit — **amended** by D-11 (still exact when
  the flag is off).
- The `"ModelOnly answer basis is not supported on Phase 03 QueryRAG path"` guard — **conditionally
  lifted** by D-10.
- The "weak evidence" concept from DEBT-RAG-01 — **dropped** by D-16, not implemented.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| ~~A1~~ | ~~The three retrieval sub-call failure branches inside `RetrieveHybridNode::run` (dense, BM25, graph) are individually distinguishable.~~ **RESOLVED — and partly REFUTED.** `retrieve.rs` was subsequently read in full. Dense and BM25 *are* individually observable (two distinct `Err(err) => return Err(err)` arms), but (i) both currently **fail the node** rather than degrade, and (ii) **there is no graph path in the node at all**, so `RETRIEVAL_DEGRADED_GRAPH` is unreachable. See §4 "D-13 — the retrieval-path failure sites, and the one enum value that is unreachable". | — | No longer an assumption. **The `RETRIEVAL_DEGRADED_GRAPH` correction must reach the D-74 plan before the proto lands** — a published enum value is one-way |
| A2 | `buf generate` will succeed at plan-execution time. `buf.gen.yaml` uses **remote** plugins, so generation requires network access to `buf.build`. `buf --version` confirms the CLI is installed; a generation run against the *real* proto was not performed (that would dirty the repo). A scratch generation with the same plugin versions **did** succeed this session, which is strong evidence the remote plugins are reachable. | §3 Wire contract | If the network is unavailable at execution time, the D-74 plan stalls. Fallback: local `protoc` (35.1 is installed) + locally-installed `protoc-gen-prost`/`protoc-gen-tonic` at matching versions — but generated-header drift is likely. **Recommend the D-74 plan's first task be a no-op `buf generate` + `git diff --exit-code` to prove reproducibility before editing the proto.** |

*(Every other factual claim in this document was read from a file or produced by a command in this
session and is tagged `[VERIFIED: …]` with the path and, where it is a discrete value, quoted
verbatim.)*

---

## Open Questions

1. **Does an "unmatched" filter reject or succeed?**
   - What we know: Phase 03 shipped a *"valid zero-match success branch"* (`03/deferred-items.md`,
     DEBT-RAG-05 preamble) and `retrieve.rs` emits `NO_EVIDENCE` + `Ok(())` for zero candidates.
     D-15 lists "unmatched" among the filter bounds in the matrix.
   - What's unclear: whether D-15 intends "unmatched" as a **400 row** or as a **200 + `NO_EVIDENCE` row**.
   - Recommendation: **200 + `NO_EVIDENCE`**, recorded as an explicit matrix disposition. Rejecting it
     would contradict shipped Phase 03 behavior and would break the eval harness's abstention signal.

2. **Where does the `WorkflowMetadata` field data come from?**
   - What we know: D-41 requires the Phase 05 D-30 metadata as `WorkflowCompletedEvent` fields, and
     AI-SPEC §4.2 fixes the ten field names.
   - What's unclear: `prompt_tokens` / `completion_tokens` require provider usage data; whether the
     OpenRouter client currently surfaces it into `WorkflowContext` was not verified this session.
   - Recommendation: the D-74 plan lands the **proto shape and the Go DTO**; a follow-up task
     populates the fields, with any unavailable field explicitly zero and documented — never
     fabricated. This keeps D-74's "one regeneration" intact even if population lands later.

3. **How far does the D-80 restructure go — `main.rs` to what size?**
   - What we know: the acceptance criterion is *"Binary imports shared modules from library crate."*
     Exact layout is Claude's Discretion.
   - What's unclear: whether `main.rs` should end at ~100 lines (pure wiring) or retain the ingestion
     worker.
   - Recommendation: move everything the **tests** need (`EffectiveRagSettings`, `LancetServiceImpl`,
     config) — that is the criterion's operational meaning, since the debt's stated risk is "test
     library / running binary drift." The ingestion worker should move too, because 6.1's rebuild
     trigger and 6.2's ingestion spans both attach to it; leaving it behind re-creates the debt one
     phase later.

4. **Who implements `disable_graph_context`'s *behavior*? No success criterion owns it.**
   - What we know: Phase 6 SC2 lands the **field** ("the graph-ablation request flag … lands with
     regenerated Rust and Go bindings"). Phase 6.3 SC4 *depends* on the behavior ("the same question
     set run with graph context on and off **via a per-request flag on one running engine**").
     Checked against all success criteria in ROADMAP for phases 6, 6.1, 6.2 and 6.3: **none states
     that the engine skips graph extraction when the flag is set.**
   - What's unclear: whether the honoring logic is Phase 6's or 6.3's. If neither claims it, 6.3
     discovers a published-but-inert field mid-phase and has to open the engine.
   - Recommendation: **Phase 6 owns it, in the D-08 plan.** That plan is already editing
     `graph_context.rs`, and honoring the flag is one early-return in `ExtractGraphContextNode::run`
     that lands on the same silent-degrade branch D-08 is instrumenting — cheapest possible place.
     Note the semantics must be kept distinct from D-08's `GRAPH_UNAVAILABLE`: a *caller-requested*
     ablation is not an unavailability, so it wants its own notice (or none) rather than reusing
     `GRAPH_UNAVAILABLE`, otherwise 6.3's graph-off arm is indistinguishable from a real outage.
     The planner should name this explicitly in the plan's decision-coverage assertion for D-47.

5. **Should the two `NO_EVIDENCE` string comparisons in `runner.rs` migrate to `typed_code` in
   Phase 6 or later?**
   - What we know: both work either way, because `code` is derived from the enum.
   - Recommendation: migrate them **in the D-74 plan**, together, as part of the notice-constructor
     introduction. Leaving mixed string/enum comparisons is how the two representations drift.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| `cargo` / rustc | Engine build + the 288-case gate | ✓ | cargo 1.95.0 (f2d3ce0bd 2026-03-21) | — |
| `go` toolchain | Gateway build + `go test ./...` | ✓ | go1.26.5 (**target is `go 1.25.0` per `go.mod`**) | — |
| `buf` CLI | D-74 regeneration, `buf lint`, `buf format` | ✓ | 1.72.0 | `protoc` 35.1 + local plugins (header drift likely) |
| Network to `buf.build` | Remote plugins in `buf.gen.yaml` | ✓ (scratch generation succeeded this session) | — | Local plugin install — see A2 |
| `protoc` | Not used by the repo's pipeline | ✓ | libprotoc 35.1 | — |
| `docker` / compose | PostgreSQL for gateway integration tests | ✓ | 28.4.0 | Pure-Rust engine tests need no Docker |
| PostgreSQL | Gateway `db` tests, checkpoint sink | via compose | `docker-compose.yml` | Engine-only plans unaffected |
| `uv` | **Phase 6.3 only** — not needed here | ✓ | 0.11.2 | — |
| OpenRouter API key | **Not needed by Phase 6** — all four behavior clauses are testable through `cfg(test)` fakes (D-83) | n/a | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none currently missing; see Assumption A2 for the network
dependency of `buf generate`.

**Platform note:** development is Windows-native (`win32`, PowerShell primary). `.planning/WINDOWS.md`
records platform gotchas. Test binaries under `engine/target/debug/deps/*.exe` confirm the Windows
toolchain. Any shell command in a plan must work in this environment — the configured gate uses
`(cd gateway && go test ./...)` subshell syntax, which is POSIX-shell, so plans should run the gate
through the Bash tool rather than PowerShell.

---

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework (Rust) | Built-in `cargo test` + `#[tokio::test]` (tokio `~1.53`, features include `test-util` for the paused clock) |
| Framework (Go) | Built-in `go test` + `net/http/httptest` |
| Config file | None — cargo and go conventions only. Targets are declared by `engine/Cargo.toml` + `#[path]`/`mod` declarations |
| Quick run command (Rust, single target) | `cargo test --manifest-path engine/Cargo.toml --lib` |
| Quick run command (Go, single package) | `cd gateway && go test ./... -run TestName` |
| Full suite command | `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)` [VERIFIED: `.planning/config.json` `workflow.test_command`] |
| Build command | `cargo build --manifest-path engine/Cargo.toml && (cd gateway && go build ./...)` [VERIFIED: `.planning/config.json` `workflow.build_command`] |
| Supplementary gates (repo habit, not in config.json) | `cargo clippy --manifest-path engine/Cargo.toml -- -D warnings`, `cargo fmt --check`, `go vet ./...`, `buf lint`, `buf format --diff --exit-code` |

**Baseline (measured this session, the invariant every plan must preserve):**

| Target | Cases |
|---|---|
| `unittests src/lib.rs` (library) | **133** |
| `unittests src/main.rs` (bin `engine`) | **128** |
| `unittests src/bin/inspect_lancedb.rs` | **18** |
| `unittests src/bin/seed_rag_fixture.rs` | **0** |
| `tests/config_startup.rs` (integration) | **9** |
| **Total** | **288** |
| Go `func Test…` in `gateway` | **67** |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| **D-80** | Per-target test redistribution preserved; total stays 288 | invariant | `cargo test --manifest-path engine/Cargo.toml -- --list \| grep -E "^\s*Running\|^[0-9]+ tests"` | ✅ (enumeration is the assertion) |
| **D-80** | No `pub use` alias re-introduces a second path to a moved item | static | `grep -c "^pub use" engine/src/main.rs` → expect `0` | ✅ |
| **D-82** | Gateway builds and all 67 tests pass after the package split | regression | `cd gateway && go build ./... && go test ./...` | ✅ |
| **D-74** | Proto edit regenerates exactly five files, reproducibly | contract | `buf lint && buf format --diff --exit-code && buf generate && git status --porcelain` | ❌ Wave 0 — add as a plan verification step |
| **D-74** | `optional bool` round-trips presence (absent ≠ false) over gRPC | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- request_flag_presence` | ❌ Wave 0 |
| **D-74/D-76** | Every emitted notice has non-empty `code` derived from `typed_code` via `as_str_name()` | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- notice_code_derivation` | ❌ Wave 0 |
| **D-74** | Posting `allow_model_only` / `disable_graph_context` to `/rag/query` does **not** 400 (`DisallowUnknownFields`) | integration | `cd gateway && go test ./... -run TestRAGQueryNewRequestFields` | ❌ Wave 0 |
| **D-08** (DEBT-RAG-06 clause 1) | `GRAPH_UNAVAILABLE` fires on the empty-result path | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- graph_unavailable_empty_result` | ❌ Wave 0 |
| **D-08** (clause 1) | `GRAPH_UNAVAILABLE` fires on the absent-`graph_port` path | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- graph_unavailable_no_port` | ❌ Wave 0 |
| **D-08** (clause 2) | `GRAPH_TIMEOUT`/`GRAPH_DEGRADED` behavior is byte-for-byte unchanged | regression | existing tests must stay green | ✅ |
| **D-08** (clause 3, the droppable one) | **Source-chunk queries never require graph data** | unit | `cargo test --manifest-path engine/Cargo.toml --lib -- source_chunk_query_without_graph` | ❌ Wave 0 |
| **D-13** (DEBT-RAG-01 clause 1) | Dense fails → **no `NodeFailed`, no failure terminal**; `answer_basis == RETRIEVAL`; surviving BM25 evidence returned; `RETRIEVAL_DEGRADED_DENSE` notice | unit (`FakeDenseRetrievalPort::failure(...)`) | `cargo test … --lib -- retrieval_degraded_dense` | ❌ Wave 0 |
| **D-13** | BM25 fails → same, distinct notice; **surviving dense evidence returned** | unit (`FakeBm25RetrievalPort::failure(...)`) | `cargo test … --lib -- retrieval_degraded_bm25` | ❌ Wave 0 |
| **D-13** | BM25 fails on variant *k>0* → variants `0..k` still contribute (per-variant tolerance) | unit (`FakeBm25RetrievalPort::with_map`) | `cargo test … --lib -- retrieval_degraded_bm25_per_variant` | ❌ Wave 0 |
| **D-13** | Both fail simultaneously → **two** distinct degrade notices **plus** `NO_EVIDENCE`, all three surviving de-dup, still no failure terminal | unit | `cargo test … --lib -- retrieval_degraded_both` | ❌ Wave 0 |
| **D-13/D-74** | **No emitted notice carries an unreachable code** — every `NoticeCode` variant has ≥1 emission site | static/unit | `cargo test … --lib -- notice_code_all_reachable` | ❌ Wave 0 (**this is the test that would have caught `RETRIEVAL_DEGRADED_GRAPH`**) |
| **D-47** | Engine **honors** `disable_graph_context`: flag set → no graph facts reach the prompt; flag absent → unchanged (see Open Question 4 — ownership gap) | unit | `cargo test … --lib -- disable_graph_context_honored` | ❌ Wave 0 |
| **D-10/D-11/D-12** (DEBT-RAG-01 clause 2) | Opt-in **on**, zero evidence → `MODEL_ONLY` + notice + **zero** citations | unit | `cargo test … --lib -- model_only_opt_in` | ❌ Wave 0 |
| **D-10/D-11** | Opt-in **off**, zero evidence → today's short-circuit, byte-for-byte | regression | existing Phase 05 D-03 tests must stay green | ✅ |
| **D-11** | The bypass applies in **both** `run_workflow` **and** `run_tracer` | unit | `cargo test … --lib -- model_only_tracer_path` | ❌ Wave 0 |
| **D-12/D-84** | Config default `false`; request `Some(true)` overrides; present-but-invalid env → **hard error** | unit | `cargo test --manifest-path engine/Cargo.toml --test config_startup -- allow_model_only` | ⚠️ target exists, cases ❌ Wave 0 |
| **D-14** (DEBT-RAG-03) | Near-miss marker normalized → `CITATION_REPAIRED`, citation retained | unit (new malformed-citation fake) | `cargo test … --lib -- citation_repair_normalizes` | ❌ Wave 0 |
| **D-14** | Unresolvable marker stripped from answer text **and** from `citations[]`/`structured_citations[]` → `CITATION_DROPPED` | unit | `cargo test … --lib -- citation_repair_drops` | ❌ Wave 0 |
| **D-14** | Repair makes **no** second provider call | unit (assert `FakeGenerator` call count) | `cargo test … --lib -- citation_repair_no_second_call` | ❌ Wave 0 |
| **D-14/D-18** | All citations dropped → basis downgrades **transparently** (`BASIS_RECONCILED`) | unit | `cargo test … --lib -- basis_downgrade_on_total_drop` | ❌ Wave 0 |
| **D-18** | Model self-reports `RETRIEVAL`, engine observes no resolving citations → conservative wins | unit | `cargo test … --lib -- basis_reconciliation_conservative` | ❌ Wave 0 |
| **D-16** | Weak-evidence threshold is **absent** (deliberate narrowing) | documentation | recorded in the plan; no test | n/a |
| **D-15** (DEBT-RAG-05) | Table-driven gRPC matrix: each row → expected `tonic::Code` + `err_kind` string | unit, table-driven | `cargo test … -- bad_input_matrix_grpc` | ❌ Wave 0 |
| **D-15** | Table-driven HTTP matrix: each row → 400 + `X-Lancet-Error-Kind` | integration, table-driven | `cd gateway && go test ./... -run TestBadInputMatrixHTTP` | ❌ Wave 0 |
| **D-15** | Every rejection happens **before** retrieval/provider work | unit (assert fake-port `calls() == 0`) | `cargo test … -- bad_input_rejects_before_work` | ❌ Wave 0 |
| **D-83** | Fault modes stay `cfg(test)`; no production fault-injection switch exists | static + existing guard test | `cargo test … --lib -- fake_generator_cfg_test_gated` | ✅ (guard exists at `workflow_phase5.rs:2435`) |

### Sampling Rate

- **Per task commit:** the single most relevant target — `cargo test --manifest-path engine/Cargo.toml --lib`
  for engine work, `cd gateway && go test ./...` for gateway work. Both are well under 30s incremental.
- **Per wave merge:** the full configured gate —
  `cargo test --manifest-path engine/Cargo.toml --locked && (cd gateway && go test ./...)`
- **Per restructure step (D-80/D-82 only):** additionally re-run the **per-target enumeration** and
  diff the five counts against the 133/128/18/0/9 baseline.
- **Per D-74 commit:** additionally `buf lint`, `buf format --diff --exit-code`, and
  `git status --porcelain` showing exactly the five expected paths.
- **Phase gate:** full suite green + `cargo clippy -- -D warnings` + `cargo fmt --check` + `go vet ./...`
  before `/gsd-verify-work`. **D-85: there is no CI — these commands ARE the verification path.**

### Wave 0 Gaps

- [ ] **Test-fixture constructor for `QueryRagRequest`** (`#[cfg(test)]`, `..Default::default()`-based)
      + migration of all **80** exhaustive literals — *must land before the D-74 proto edit*
- [ ] **One notice constructor** deriving `code` from `NoticeCode::as_str_name()` — covers D-08, D-13,
      D-14, D-18 and the 19 existing `Notice { … }` literals
- [ ] **`FakeGenerator` malformed-citation constructors** (near-miss + unresolvable) — the one
      genuinely new D-83 fake; everything else already exists
- [ ] **Named `empty()` constructors** on `FakeGraphQueryPort` / `FakeDenseRetrievalPort` /
      `FakeBm25RetrievalPort` — expressible today as `success(vec![])`, but D-08's test reads as intent only with a name
- [ ] **`FakeGenerator::stall()`** — only if a generation-timeout case is wanted; the four I/O ports
      already have it
- [ ] **The D-15 bad-input table itself** — a single Rust `const` table plus a Go equivalent (or a
      shared fixture), since D-15 says *"The table is the source artifact"* and Phase 6.4 documents it
- [ ] **Per-target enumeration helper** — a short script wrapping
      `cargo test … -- --list | grep -E "^\s*Running|^[0-9]+ tests"` so the D-80 invariant is one command
- [ ] **Gateway test for the two new request fields** — `main_test.go` currently has **zero**
      references to `ragQueryRequestBody`, so this is genuinely new coverage

*Framework install: none required — both test frameworks are built into the toolchains, both of which
are installed and verified.*

---

## Security Domain

`.planning/config.json` sets `"security_enforcement": true`, `"security_asvs_level": 1`,
`"security_block_on": "high"`. [VERIFIED: `.planning/config.json` read this session.]

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| **V2 Authentication** | **no** | Local-only by design. DEBT-CR-04 (network auth/authz/TLS/quotas) is **documented-only** per D-06 and is reviewed in **6.1**, not here. Phase 6 ships no auth and must not claim to |
| **V3 Session Management** | **partial** | `session_id` is a correlation identifier, **not** an authentication token. It is already validated as UUIDv4 + RFC4122 variant at `main.rs:1808-1830` and auto-generated when absent. Phase 6 changes nothing here; D-15's matrix **tests** the existing check |
| **V4 Access Control** | **no** | No principals, no roles. Loopback guardrail only (`DEBT-CR-04`, D-06) |
| **V5 Input Validation** | **yes — this is Phase 6's security surface** | Existing: `RetrievalErrorKind` 9-variant taxonomy in `retrieval/mod.rs:42-52`; `QueryRequest::from_values` bounds (query length, doc-ID format, content types, filter caps); UUIDv4 session/document IDs; `http.MaxBytesReader(32 KiB)` + `DisallowUnknownFields` at the HTTP edge. **D-15 enumerates and proves this surface.** No new validation library — reuse the taxonomy |
| **V6 Cryptography** | **no** | Phase 6 performs no crypto. `blake3` is used for a non-security result hash and is untouched |
| **V7 Error Handling & Logging** | **yes (with an accepted waiver)** | Errors carry session + correlation + error-kind identity (Phase 03 D1 contract) and Phase 6's degraded paths must **preserve** it, not bypass it. **DEBT-D1-SAFE-LOG is an accepted, still-open waiver** — full provider error text appears in engine trace logs; it stays in the backlog per D-09 |
| **V8 Data Protection** | **partial** | `config.toml` ships `database_url = ""` with an explicit "never commit a real DSN" comment; the OpenRouter key is out-of-band. Phase 6 adds **no** secret-bearing config key — the two new knobs are booleans |
| **V13 API & Web Service** | **yes** | D-74 changes a **published** contract (one-way per D-74/D-76). Additive-only discipline is the control: append tags, never renumber, never remove enum values |

### Known Threat Patterns for this stack (Rust engine + Go gateway + gRPC + SSE)

| Pattern | STRIDE | Standard Mitigation | Phase 6 status |
|---|---|---|---|
| Unbounded request body → memory exhaustion | Denial of Service | `http.MaxBytesReader(w, r.Body, 32 KiB)` on `/rag/query`; 10 MiB on uploads | **Already in place**, unchanged by Phase 6 |
| Oversized / malformed query reaching the provider (cost + DoS) | DoS, Tampering | Reject at admission before retrieval/provider work — `EmptyQuery`, `QueryTooLong`, `query_max_bytes = 8192` | **Already in place**; D-15 *proves* it with the matrix |
| Filter-parameter abuse (huge `document_ids`, huge `content_types`) | DoS | `max_document_ids = 100`, `max_content_types = 16` → `FilterLimitExceeded` | **Already in place**; D-15 covers each bound |
| Injection via document/session ID | Tampering | UUIDv4 + RFC4122-variant parse, not string interpolation. `graph::escape_sql_literal` exists for the Cypher/SQL path | **Already in place** |
| **Prompt injection via retrieved evidence** | Tampering, Elevation | Evidence is bounded (Phase 3 D-39 token budget) and the output is schema-constrained (`response_format`/`json_schema`, Phase 3 D-28). **D-17 adds a precedence instruction** — note it *increases* evidence authority over model priors, which is the intended trade but is worth stating: hostile corpus content is trusted more after D-17, not less | **New surface introduced by D-17.** Accepted deliberately per the user's stated principle ("when retrieved data contradicts model knowledge, our data wins"). Mitigation stays: bounded evidence + schema-constrained output + citations resolving to real chunks |
| **Fabricated / unresolvable citations presented as grounding** | Repudiation, Tampering | **D-14 is the mitigation**: markers that do not resolve are stripped and the basis downgrades. This is a *security* control, not only a quality one — it prevents the system asserting provenance it cannot support | **New in Phase 6** |
| **Model-only answers mistaken for grounded ones** | Repudiation | **D-10's contract**: `MODEL_ONLY` + explicit notice + **zero** citations; default **off**; opt-in must be explicit per request. **D-18's conservative-wins rule never strengthens a provenance claim** | **New in Phase 6.** The default-off + explicit-opt-in shape is the control |
| Unvalidated new request flags widening behavior by default | Elevation of Privilege | `optional bool`, config default `false`, resolved once at admission | **New in Phase 6** |
| Silent telemetry/config disablement via a mistyped env value | Tampering | **D-84**: new keys `return Err(...)` on present-but-invalid | **New in Phase 6** |
| Full provider error text in logs | Information Disclosure | **Accepted waiver** — `DEBT-D1-SAFE-LOG`, backlog per D-09. Its shared-log-sink trigger fires in **6.2**, not here | Out of scope; do not "fix" opportunistically |
| Gateway→Engine gRPC dialed insecurely | Information Disclosure, Tampering | `grpc.WithTransportCredentials(insecure.NewCredentials())` at `main.go` `run()` — **`DEBT-CR-04-EXT`, backlogged** under Security & transport (D-03) | Out of scope. **The D-82 package split must move this code unchanged** — do not "improve" it into a TLS dial, which would contradict D-03/D-06 |

**ASVS L1 verdict for Phase 6:** the phase's own security-relevant surface is **V5 (input validation)**
and **V13 (API contract)**, both of which it strengthens. It introduces no authentication, no
cryptography and no new secret-bearing configuration. The two genuinely new risk surfaces are
**D-17's deliberate elevation of evidence authority** and **D-10's model-only path**, both mitigated
by design (default-off opt-in, zero citations, explicit notice, conservative reconciliation) and both
recorded as accepted trade-offs in CONTEXT.md.

---

## Sources

### Primary (HIGH confidence) — repository files read this session

- `.planning/phases/06-observability-evaluation-polish/06-CONTEXT.md` — read in full (all 86 decisions)
- `.planning/phases/06-observability-evaluation-polish/06-AI-SPEC.md` — §§3, 4.1–4.6 read (lines 314–823)
- `.planning/phases/03-hybrid-retrieval-basic-rag-path/deferred-items.md` — DEBT-RAG-01/02/03/04/05/06, DEBT-D1-SAFE-LOG, DEBT-P3-MODULE-GRAPH, DEFERRED-03-12-02
- `.planning/ROADMAP.md` (read in full), `.planning/REQUIREMENTS.md` (RAG-03 + traceability), `.planning/STATE.md` (§Known Issues & Debt), `.planning/config.json`
- `CLAUDE.md` (full), `go-guidelines.md` (full), `rust-guidelines.md` (§M-SINGLE-ITEM-PATH `:104-137`, §M-TAUTOLOGICAL-TESTS `:138-162`, full heading outline)
- `proto/lancet/v1/lancet.proto` (complete), `buf.yaml`, `buf.gen.yaml`
- `engine/Cargo.toml`, `engine/src/lib.rs` (complete), `engine/src/workflow/nodes/retrieve.rs` (**complete, `:1-235`**), `engine/src/main.rs` (`:1-120`, `:591-710`, `:1790-1900`, `:3340-3351`, plus targeted greps), `engine/src/workflow/mod.rs` (`:1-140`), `engine/src/workflow/ports.rs` (complete), `engine/src/workflow/runner.rs` (`:400-500`), `engine/src/workflow/nodes/graph_context.rs` (`:95-160`), `engine/src/workflow/nodes/retrieve.rs` (`:170-215`), `engine/src/generation/mod.rs` (`:140-220`), `engine/src/retrieval/mod.rs` (`:42-67`), `engine/src/tests.rs` (`:1-30`), `engine/src/tests/workflow_phase5_production.rs` (`:1-25`), `engine/src/inspect_lancedb_tests.rs` (`:1-20`)
- `gateway/go.mod`, `gateway/main.go` (`:49-99`, `:474-500`, `:662-810`, `:894-940`, `:1059-1138`, plus full structural outline), `gateway/main_test.go` (header + per-identifier counts)
- `config/config.toml` (complete)

### Primary (HIGH confidence) — commands executed this session

- `cargo test --manifest-path engine/Cargo.toml -- --list` — the five per-target counts
- `buf --version` (1.72.0) · `cargo --version` · `go version` · `protoc --version` · `docker --version` · `uv --version`
- `buf generate` against a scratch probe proto using `neoeinstein-prost:v0.5.0` and `protocolbuffers/go:v1.36.5` — the `optional bool` and enum-helper shapes quoted in §3 (scratch directory deleted after)
- Struct-literal and identifier counts via `grep -c` across `engine/src` and `gateway`

### Secondary (MEDIUM confidence)

- None. Every claim in this document derives from a repository file or a command run in this session.

### Tertiary (LOW confidence)

- None. The two items that could not be confirmed are recorded in the Assumptions Log (A1, A2) rather
  than asserted.

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|---|---|---|
| Standard stack | **HIGH** | Every version read from a manifest or a `--version` invocation this session; zero new packages, so zero package-legitimacy risk |
| Module-graph restructure | **HIGH** | `lib.rs` read complete; `main.rs` `mod` declarations enumerated exhaustively; the five per-target test counts measured, not estimated; the three blocking test roots and their exact `use` statements quoted verbatim |
| Go package split | **HIGH** for the seams and the churn numbers (structural outline + per-identifier counts measured); **MEDIUM** for the final layout, which is explicitly Claude's Discretion |
| Wire contract | **HIGH** | Toolchain read from `buf.gen.yaml`/`buf.yaml`; the `optional bool` and `as_str_name()` shapes **empirically generated** with the pinned plugin versions rather than assumed; the ~101-site churn counted per file |
| Behavior change sites | **HIGH** — all of D-08, D-10 (both guards), D-11, D-13 and D-15 quoted verbatim from source read this session. `retrieve.rs` was read in full (`:1-235`), which resolved the last open assumption and produced the two AI-SPEC corrections (D-13 is fail-closed→degrade; `RETRIEVAL_DEGRADED_GRAPH` unreachable) |
| Wire-contract churn, Go side | **HIGH** — measured directly: **zero** whole-payload equality assertions in `main_test.go`, so added JSON keys are invisible to all 67 tests |
| `cfg(test)` fake-port seam | **HIGH** | `ports.rs` read in full; constructor vocabulary tabulated from the source; the source-text guard test located and quoted |
| Config knob handling | **HIGH** | `load_settings()` read in full; the fail-open pattern quoted verbatim in both its numeric and string forms; the gateway's `loadConfig` and its three `BindEnv` strings read |
| Pitfalls | **HIGH** | Every pitfall traces to a specific quoted code fact, not to general experience |
| Security domain | **MEDIUM-HIGH** | Controls verified in code; the ASVS mapping and the STRIDE table are analytical judgements over verified facts |

**Research date:** 2026-08-20
**Valid until:** 2026-09-19 (30 days) — the repository is the source of truth and is stable; the only
externally-dated facts are the pinned remote buf plugin versions, which are immutable by version.
