---
phase: 6
reviewers: [antigravity, cursor]
reviewed_at: 2026-08-20T21:43:42Z
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md, 06-08-PLAN.md, 06-09-PLAN.md, 06-10-PLAN.md, 06-11-PLAN.md, 06-12-PLAN.md]
models:
  antigravity: "unknown"
  cursor: "unknown"
model_sources:
  antigravity: "unknown"
  cursor: "unknown"
---

# Cross-AI Plan Review — Phase 6

Both lanes ran source-grounded against `D:/Repos/lancet` and cited `file:line` evidence.
Neither output carries a `[reviewed-without-repo-access]` or
`[reviewed-without-source-citations]` marker, so both verdicts count at full consensus
weight. The prompt was budget-assembled at 200000 tokens with `planTruncationPct: 0` and
`omitted: []` — all twelve plans, plus roadmap, requirements, project context, phase
context and research, reached both reviewers intact. No `trimmed_reviewers` block is
recorded because nothing was trimmed.

## Consensus Summary

The twelve plans are architecturally sound and unusually well grounded in the real module
graph. Both reviewers independently confirmed that the plans correctly identify subtle
existing mechanisms — the dual grounding guards in `engine/src/generation/mod.rs:172-201`,
the asymmetric zero-evidence gates at `engine/src/workflow/runner.rs:427-430` versus
`:481`, the silent degradation branches at `engine/src/workflow/nodes/graph_context.rs:112-115`
and `:147-150`, and `add_notice` de-duplication at `engine/src/workflow/mod.rs:79-86`.
Both endorse the wave ordering (module graph → fixtures → single wire edit → behavior →
matrix last).

The defects both found are concentrated in **verification scripting, not design** — with
one exception (06-10) that is a genuine scope gap and is the single most important finding
in this review.

Every finding below marked CONFIRMED was independently verified against source during
review assembly, not taken on the reviewer's word.

### Agreed Strengths

- **Wave sequencing is correct.** Both reviewers independently endorsed
  restructure → testkit/fakes → one proto edit → behavior → bad-input matrix, and both
  noted the matrix landing last avoids dual-writing the two count-gate scripts.
- **Claimed source sites are real.** Cursor: "Almost every claimed site matches source."
  Antigravity reached the same conclusion independently. The plans are not hallucinating
  line references.
- **D-74's single-wire-edit discipline** (one additive protobuf edit, both binding trees,
  gateway body types in the same plan) is the right lesson carried forward from 05-17/05-23.
- **Fail-closed isolation of new config keys** (`LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS`,
  `..._CITATION_REPAIR_ENABLED`) errors on invalid input while deliberately preserving
  existing fail-open behavior, so legacy deployments with typos do not break.

### Agreed Concerns

- **[HIGH — CONFIRMED] `06-05` test-count gate is wrong and fails on HEAD.**
  Both reviewers flagged this independently.
  [06-05-PLAN.md:173](.planning/phases/06-observability-evaluation-polish/06-05-PLAN.md:173)
  asserts `grep -c '^func Test' gateway/main_test.go` = `67`; the file contains **60**.
  67 is the gateway-wide total (60 in `main_test.go` + 7 in `gateway/db/document_test.go`).
  The plan's own prose at line 159 conflates the package total with the per-file count, and
  the threat-model row T-06-05-04 at line 210 repeats the same wrong number. The plan adds
  no Go tests, so the gate is red before any work starts.
  *Fix:* assert 60 against `main_test.go` and verify the 67 aggregate through
  `scripts/gateway-test-targets.sh`.

- **[MEDIUM] `buf generate` depends on remote plugins.** `buf.gen.yaml` references
  `buf.build/grpc/go`, `buf.build/protocolbuffers/go`, `buf.build/community/neoeinstein-prost`
  and `buf.build/community/neoeinstein-tonic`. Plan 06-07 Task 1 is blocked in an offline or
  network-restricted environment. Antigravity rated this MEDIUM, cursor LOW; both call it an
  external blocker rather than a plan defect.
  *Fix:* dry-run `buf lint && buf generate` before Wave 5 to confirm plugins are cached.


### Single-Reviewer Findings That Verified

These were raised by one lane only, but were confirmed against source during assembly and
should be treated at full weight. That only one reviewer found each is a statement about
reviewer coverage, not about severity.

- **[HIGH — CONFIRMED, cursor only] `06-10` never edits the empty-evidence hard fail, so SC3 cannot be met.**
  This is the most consequential finding in the review. Plan 06-10 lifts the model-only
  restriction in the runner and in `generation/mod.rs`, but
  [assemble_prompt.rs:70-75](engine/src/workflow/nodes/assemble_prompt.rs:70) still returns
  `PromptAssemblyFailed` whenever `ctx.evidence_blocks.is_empty()`, and
  [prompt.rs:333](engine/src/prompt.rs:333) independently returns
  `PromptAssemblyError::EmptyEvidence`. **Neither `assemble_prompt.rs` nor `prompt.rs`
  appears anywhere in plan 06-10** — grepping the whole plan for either filename returns
  nothing. As written, an opted-in zero-evidence request still terminates in
  `PromptAssemblyFailed`, so the model-only answer path D-11 requires never runs.
  *Fix:* add both files to Task 3; when `ctx.allow_model_only` and evidence is empty, skip
  the hard fail and pack a zero-evidence prompt — without relaxing the packer
  unconditionally, since existing `EmptyEvidence` tests depend on the current behavior.

- **[HIGH — CONFIRMED, cursor only] `06-06`'s `QueryRagRequest {` gate matches generated code and can never pass.**
  [06-06-PLAN.md:170](.planning/phases/06-observability-evaluation-polish/06-06-PLAN.md:170)
  and `:179` require
  `grep -rn --include=*.rs 'QueryRagRequest {' engine/src | grep -v 'engine/src/testkit.rs'`
  to produce no output. That pattern matches `pub struct QueryRagRequest {` at
  [lancet.v1.rs:59](engine/src/pb/lancet/v1/lancet.v1.rs:59) — generated prost code that is
  neither testkit nor migratable. The gate is red on an untouched tree and stays red after a
  perfect migration. Note the plan carries a `planner-discipline-allow` comment for this
  literal at line 141, so the planner was aware of the literal but not of the generated-code
  collision.
  *Fix:* exclude `engine/src/pb/` from the grep as well as testkit.

- **[HIGH — CONFIRMED, antigravity only] `06-07`'s `Notice {` gate has a floor of 2 and targets 1.**
  [06-07-PLAN.md:293](.planning/phases/06-observability-evaluation-polish/06-07-PLAN.md:293)
  asserts the four-file concatenation yields `grep -c 'Notice {'` = `1` after the change.
  But `CheckpointNotice {` at [events.rs:113](engine/src/workflow/events.rs:113) (struct
  definition) and [events.rs:119](engine/src/workflow/events.rs:119) (`impl From<&Notice> for
  CheckpointNotice`) both match the bare pattern, and neither is a notice constructor that
  06-07 removes. The minimum achievable count is 2, so the gate can never pass.
  *Correction to the reviewer:* antigravity predicted the count would be 3; the actual
  current count is **6**. Its arithmetic was wrong, its mechanism was right.
  *Fix:* word-boundary match — `grep -cE '\bNotice \{'` — or explicitly exclude
  `CheckpointNotice`.
  **Note this is a direct reviewer disagreement:** cursor examined the same gate and
  described it as a strength ("Task 2 verify `Notice {` count = 1 ... prevents a second
  inline literal"), missing the `CheckpointNotice` collision. Verification sides with
  antigravity.

- **[MEDIUM — CONFIRMED, cursor only] `06-01`'s env-key gate uses `-ge 18`, not equality.**
  A rename preserves the count and passes the gate, which is precisely threat T-06-01-01
  that the plan itself names. *Fix:* assert equality against a pre-move count recorded in
  the SUMMARY.

### Unverified Reviewer Claims

Recorded for completeness; each is hedged in its own source review and was **not** confirmed
during assembly.

- **[MEDIUM, antigravity] Windows path separators in `scripts/engine-test-targets.sh`.**
  Stated conditionally ("if the script uses strict regex matching ... with forward slashes").
  The script's actual matching was not inspected. Worth a look given this is a Windows
  development host, but do not treat it as an established defect.
- **[LOW, antigravity] `FakeGenerator` structural-guard fragility** at
  `engine/src/tests/workflow_phase5.rs:2435-2446` — a formatting change above
  `generation/mod.rs:504` trips the assertion. Plans 06 and 10 already warn about this.

### Divergent Views

- **Overall risk.** Antigravity: **LOW-to-MEDIUM** ("risks are isolated to test-verification
  scripting rather than architectural flaws"). Cursor: **MEDIUM**, driven specifically by
  06-10. The divergence is explained entirely by coverage — antigravity did not find the
  06-10 prompt-assembly gap, which is a scope defect rather than a scripting defect. Since
  that finding verified, **cursor's MEDIUM is the better-supported verdict.**
- **`06-07`'s `Notice {` gate** — flagged as HIGH by antigravity, cited as a strength by
  cursor. Verification confirms antigravity (see above).
- **Wire-contract breaks (cursor only, MEDIUM each).** Two deliberate breaks worth an
  explicit human decision rather than a silent default: ROADMAP SC4 still names a single
  `RETRIEVAL_DEGRADED` notice while 06-07 publishes `RETRIEVAL_DEGRADED_DENSE` /
  `RETRIEVAL_DEGRADED_BM25`; and renaming the on-the-wire `NOTICE` / `WARNING` codes at
  `workflow/mod.rs:117-126` to `MODEL_NOTICE` / `MODEL_WARNING` is invisible in-repo but
  visible to any out-of-repo client.

### Reviewer Coverage Note

Each lane found HIGH-severity defects the other missed — two for cursor, one for
antigravity — and they contradicted each other on a third. Neither review alone would have
surfaced the full set. Cursor reviewed plan-by-plan (27KB, per-plan risk ratings);
antigravity reviewed cross-cutting (10KB, single consolidated verdict). The two shapes are
complementary rather than redundant.

---

## Antigravity Review


### 1. Summary

Phase 6 addresses architectural debt and degraded-mode resilience across Lancet's Rust RAG engine and Go API gateway. The 12-plan sequence is structured with disciplined wave dependencies: modularizing the dual-compilation Rust crate (`DEBT-P3-MODULE-GRAPH`) and Go gateway monolith (`D-82`), establishing a test harness with constructor fixtures (`engine::testkit`, `D-83`), consolidating wire contract changes into a single additive protobuf edit (`D-74`), and systematically implementing RAG-03 degraded-mode behaviors (`DEBT-RAG-01`, `DEBT-RAG-03`, `DEBT-RAG-05`, `DEBT-RAG-06`). 

Source verification against `D:/Repos/lancet` confirms that the plans correctly identify subtle implementation details—such as the dual grounding guards in `engine/src/generation/mod.rs:172-201`, the asymmetric zero-evidence gates in `engine/src/workflow/runner.rs:427-483`, and the silent degradation paths in `engine/src/workflow/nodes/graph_context.rs:112-150`. However, verification revealed two critical verification command defects in Plans 05 and 07 regarding test counts and grep patterns that will cause automated verification steps to fail unless corrected.

---

### 2. Strengths

- **Surgical Module Restructuring Sequence (Plans 01–03, 04–05):**
  - Moving `chunker` (`engine/src/main.rs:29`, `main.rs:39`) and `config` (`main.rs:50-705`) to `engine::chunker` and `engine::config` before relocating `ingest` and `service` (`main.rs:1040-1880`) prevents circular references and preserves item reachability under `rust-guidelines.md` (`M-SINGLE-ITEM-PATH`).
  - Rehoming `engine/src/tests.rs` (which currently binds to the binary root via `use super::*;` at line 9 and declares `workflow_phase5_production` at line 11) to `engine/src/lib.rs:15-18` cleanly resolves the test/binary divergence without leaving phantom alias re-exports.
  - Symmetrically refactoring `gateway/main.go:49-98` and `gateway/main.go:803-1021` into `gateway/internal/config`, `gateway/internal/sse`, and `gateway/internal/engineclient` maintains `handlePreStreamError`'s structural interface assertion (`interface{ Trailer() metadata.MD }` at `gateway/main.go:783`) across package boundaries.

- **Precise Identification of Dual Validation Guards & Runner Gates (Plans 09, 10):**
  - In `engine/src/generation/mod.rs`, model-only responses are rejected at two distinct points: `AnswerBasis::ModelOnly` check at `generation/mod.rs:172-177` and `cited_evidence_ids.is_empty()` check at `generation/mod.rs:193-201`. Plan 10 correctly conditions both guards on `GroundingLimits.allow_model_only`, ensuring model-only responses validate while retrieval-backed responses are still required to cite evidence.
  - In `engine/src/workflow/runner.rs`, Plan 10 correctly identifies that `run_workflow` has a compound zero-evidence gate with two disjuncts (`n.code == "NO_EVIDENCE" || (ctx.final_candidates.is_empty() && ctx.evidence_blocks.is_empty())` at `runner.rs:427-430`) whereas `run_tracer` at `runner.rs:481-487` only checks the notice code. Bypassing both disjuncts in `run_workflow` ensures consistency across production and tracer paths.

- **Accurate Remediation of Silent Degradation Branches (Plan 08):**
  - In `engine/src/workflow/nodes/graph_context.rs`, the success branch with empty facts (`graph_context.rs:112-115`) and the absent-port branch (`graph_context.rs:147-150`) silently zero out context without emitting notices, while errors at `graph_context.rs:134-144` emit `GRAPH_TIMEOUT` or `GRAPH_DEGRADED`. Plan 08 instruments both silent paths with distinct, typed `GRAPH_UNAVAILABLE` notice messages without altering execution flow.

- **Strict Pre-Work Rejection Verification in Bad-Input Matrix (Plan 12):**
  - In `engine/src/main.rs:1839-1872`, `QueryRequest::from_values` runs during gRPC request admission before creating channels or spawning tokio tasks. Plan 12 validates that invalid inputs fail at admission via `d1_status` (`main.rs:1186-1215`) by verifying call counts remain zero on `FakeDenseRetrievalPort`, `FakeBm25RetrievalPort`, and `FakeGenerator`.

- **Fail-Closed New Key Isolation (D-84 / Plans 09, 10):**
  - New environment variables (`LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS` and `LANCET_ENGINE__WORKFLOW__CITATION_REPAIR_ENABLED`) enforce fail-closed parsing on invalid inputs while strictly preserving existing fail-open behavior in `engine/src/config.rs` to avoid breaking deployments with legacy typos.

- **Local, Network-Free Citation Normalization & Repair (Plan 11):**
  - Implementing deterministic normalization (syntax stripping, Unicode normalization, case folding) with exact-match resolution and tie-breaking drops in `engine::generation::citations` satisfies `DEBT-RAG-03` without introducing secondary LLM round-trips.

---

### 3. Concerns

- **[HIGH] Flawed Test Count Acceptance Criterion in Plan 05 (06-05):**
  - **Evidence:** `gateway/main_test.go` defines exactly 60 `func Test` functions. The remaining 7 gateway tests reside in `gateway/db/document_test.go` (`package db`). Total test count across `gateway/` is 67.
  - **Mechanism:** Plan 05 Task 2 Acceptance Criteria (line 1493) and automated verification script (line 1501) state:
    `test "$(grep -c '^func Test' gateway/main_test.go)" = "67"`
  - **Impact:** Running this check will return `60 = 67`, resulting in an immediate failure (exit code 1) during automated task verification.
  - **Remediation:** Update the criterion to check `main_test.go` for 60 tests (`test "$(grep -c '^func Test' gateway/main_test.go)" = "60"`) and verify the package total via `sh scripts/gateway-test-targets.sh`.

- **[HIGH] False Grep Match on `CheckpointNotice` in Plan 07 (06-07) Verification:**
  - **Evidence:** `engine/src/workflow/events.rs:113` contains `pub struct CheckpointNotice {` and line 119 contains `impl From<&Notice> for CheckpointNotice {`.
  - **Mechanism:** Plan 07 Task 2 verification (line 2187) runs:
    `test "$(cat engine/src/workflow/mod.rs engine/src/workflow/events.rs engine/src/workflow/nodes/graph_context.rs engine/src/workflow/nodes/retrieve.rs | grep -c 'Notice {')" = "1"`
  - **Impact:** The grep pattern `Notice {` matches `CheckpointNotice {` twice in `events.rs`. Together with the 1 legitimate notice constructor in `mod.rs`, the count will be 3 (`3 != 1`), causing the automated task gate to fail.
  - **Remediation:** Use word-boundary matching `grep -cE '\bNotice \{'` or explicitly exclude `CheckpointNotice`.

- **[MEDIUM] Remote Plugin Dependency for Protobuf Codegen in Plan 07 (06-07):**
  - **Evidence:** `buf.gen.yaml` references remote plugins: `buf.build/grpc/go`, `buf.build/protocolbuffers/go`, `buf.build/community/neoeinstein-prost`, and `buf.build/community/neoeinstein-tonic`.
  - **Mechanism:** Plan 07 Task 1 requires running `buf generate` on execution. If running in an offline or restricted network environment without cached plugins, code generation will fail.
  - **Impact:** Plan 07 will be blocked at Task 1 if internet access to `buf.build` is unavailable.

- **[MEDIUM] Windows vs. POSIX Path Separator Handling in `scripts/engine-test-targets.sh`:**
  - **Evidence:** `cargo test -- --list` on Windows produces output containing backslashes (e.g., `Running unittests src\lib.rs (...)` and `Running tests\config_startup.rs (...)`).
  - **Mechanism:** If `scripts/engine-test-targets.sh` uses strict regex matching `src/lib.rs` and `tests/config_startup.rs` with forward slashes, target detection will fail on native Windows runners.
  - **Impact:** Test enumeration script may report 0 matched targets on Windows runners.

- **[LOW] Structural Guard Test Fragility in `engine/src/tests/workflow_phase5.rs`:**
  - **Evidence:** `engine/src/tests/workflow_phase5.rs:2435-2446` locates `pub struct FakeGenerator` in `engine/src/generation/mod.rs` by reading the raw source string and asserting that the immediately preceding non-empty line contains `#[cfg(test)]`.
  - **Mechanism:** Adding doc comments, helper annotations, or reformatted whitespace immediately above `pub struct FakeGenerator` in `engine/src/generation/mod.rs:504` will trip this assertion.
  - **Impact:** While Plans 06 and 10 explicitly warn about this pitfall, any accidental formatting adjustment above line 504 will fail the test suite.

---

### 4. Suggestions

1. **Fix Plan 05 Acceptance Criteria:**
   Update Plan 05 Task 2 acceptance criteria and verification command to check for 60 tests in `gateway/main_test.go` and 7 tests in `gateway/db/document_test.go`, verifying the aggregate 67 count through `scripts/gateway-test-targets.sh`.

2. **Fix Plan 07 Verification Regex:**
   Replace `grep -c 'Notice {'` in Plan 06 Task 1 and Plan 07 Task 2 with `grep -cE '\bNotice \{'` to avoid matching `CheckpointNotice {` in `engine/src/workflow/events.rs`.

3. **Make `scripts/engine-test-targets.sh` Path-Agnostic:**
   In `scripts/engine-test-targets.sh`, normalize backslashes to forward slashes (e.g., via `tr '\\' '/'` or regex `[\\/]`) before pattern matching target names to ensure seamless execution on both Windows native (Git Bash/pwsh) and Linux/WSL.

4. **Verify Protobuf Plugin Availability Ahead of Wave 5:**
   Execute a dry-run `buf lint && buf generate` before Wave 5 begins to confirm that remote plugins from `buf.build` are accessible and cached locally.

---

### 5. Risk Assessment

**Overall Risk Level: LOW to MEDIUM**

**Justification:**
- The architectural design, modular decomposition, and error-handling state machines across Rust and Go are exceptionally thorough, sound, and closely aligned with the existing codebase structure.
- The sequencing (Restructure → Testkit/Fakes → Wire Contract → Behavior → Matrix) ensures each step builds upon an invariant-verified foundation.
- Identified risks are isolated to test-verification scripting syntax (grep boundaries and file-level test count expectations) rather than architectural flaws or data-plane regressions. Once the minor script assertions in Plans 05 and 07 are adjusted, the execution path is clear and reliable.


---

## Cursor Review


Verified against `D:/Repos/lancet` at the current tree (`engine/src/lib.rs` 17 lines; `engine/src/main.rs` still owns `mod chunker`, config, ingest, and `LancetServiceImpl`; `gateway/main.go` still flat). Line citations below are that tree, not the plans’ projected post-move paths.

**Overall:** The twelve plans match Phase 6’s seven success criteria and are unusually well grounded in the real module graph, fail-closed sites, and D-74/D-76 sequencing. Three defects will fail execution or the user-facing contract if left as written: 06-10 never edits the empty-evidence hard fails in prompt assembly; 06-06’s `QueryRagRequest {` grep matches generated prost code; 06-05 asserts `67` tests in `main_test.go` which only has `60`. Overall risk **MEDIUM**, driven by 06-10.

---

### Cross-plan

**What holds.** Wave order is right: module graph (06-01…06-05) → fixtures (06-06) → one proto edit (06-07) → behavior (06-08…06-11) → matrix last (06-12) so the two count-gate scripts are not dual-written. D-74’s “one edit, both binding trees, gateway body types in the same plan” is the correct lesson from 05-17/05-23. The tracer-first split (06-08) plus horizontal expansion is real, not decorative.

**Shared strengths.** Almost every claimed site matches source: ModelOnly guard at `engine/src/generation/mod.rs:172-175`; both runner gates at `engine/src/workflow/runner.rs:427-430` and `:481`; retrieve fail-closed at `engine/src/workflow/nodes/retrieve.rs:76` and `:107`; graph silent paths at `engine/src/workflow/nodes/graph_context.rs:112-115` and `:147-150`; `DisallowUnknownFields` at `gateway/main.go:677`; `add_notice` de-dup on `(code, message)` at `engine/src/workflow/mod.rs:79-86`; next proto tags really are free (`QueryRAGRequest` 1–3, `Notice` 1–3, `WorkflowCompletedEvent` 1–6).

**Shared test-count facts.** `#[test]`/`#[tokio::test]` attributes sum to **288** (including one `#[ignore]` in `engine/src/generation/tests.rs:674`). Go `^func Test` is **60** in `gateway/main_test.go` + **7** in `gateway/db/document_test.go` = **67**. VALIDATION.md’s 133/128/18/0/9 split is consistent with combined lib+bin = 261.

---

### 06-01 — Rust module graph, step 1

#### Summary
Sound first move: `chunker` then the whole config surface into the library, with a per-target count gate that deliberately does **not** pin the lib/bin split. Matches D-80/D-81 and the actual layout (`lib.rs` has no `chunker`/`config`; `main.rs:29` is `mod chunker`; `load_settings` is `main.rs:591`).

#### Strengths
- Smallest revertible steps; `LancetServiceImpl` correctly deferred to 06-02.
- `::config::` disambiguation is required: the module will be named `config` and the crate already is (`engine/Cargo.toml` `config = { version = "~0.15", features = ["toml"] }`).
- Combined 261 lib+bin invariant survives the chunker move: `engine/src/chunker/tests.rs` has 6 tests that will migrate lib←bin without changing the sum.
- `chunker/mod.rs` has no `crate::` paths today, so the “rewrite crate paths” instruction is a no-op, not a hidden rewrite.

#### Concerns
- **MEDIUM** — Task 2’s automated verify uses `LANCET_` distinct-literal count `-ge 18`, not equality with the pre-move count. Current `load_settings` has exactly 18 `LANCET_*` names (`main.rs:592-696`). A rename keeps the count and would silently break deployments (the threat the plan itself names as T-06-01-01).
- **LOW** — `cargo clippy -- -D warnings` on today’s ~3.3k-line `main.rs` is unproven here; if the tree is not already clippy-clean, Wave 1 dies before any move.

#### Suggestions
- Make the LANCET gate `test "$after" -eq "$before"` with the before-count recorded in the SUMMARY, not `-ge 18`.
- Run clippy once on HEAD and record the result in 06-01-SUMMARY before calling it a gate.

#### Risk Assessment
**LOW.** Mechanical, well scoped, counts match.

---

### 06-02 — Rust module graph, step 2

#### Summary
Correctly isolated as “the large step.” Ingest-before-service ordering matches the real dependency (`LancetServiceImpl` holds embedding/ingest types). Leaving the five per-target counts unmoved so 06-03 owns the redistribution is the right attribution story.

#### Strengths
- Explicit D1 identity preservation (`d1_status` at `main.rs:1186`, kinds at `:1847-1869`) is load-bearing for 06-12.
- `use engine::ingest::{…}` in `main.rs` so `engine/src/tests.rs:9` `use super::*` keeps compiling is the actual Rust visibility rule, not a shortcut.
- Constants `MAX_DOCUMENT_BYTES` / `QUEUE_CAPACITY` (`main.rs:53-54`) are listed to move; they would otherwise fail 06-03’s “one top-level item” grep.

#### Concerns
- **MEDIUM** — `CancelOnDropStream` is a **local item inside** `query_rag` (`main.rs:1874-1895`, immediately after `_query_request … ?;`). The plan talks about it as a sibling of `LancetServiceImpl`. A naive cut of “the impl block” drops it or splits the function. It must be un-nested into `engine/src/service.rs`.
- **LOW** — Relocating ~2.3k lines in one task is honest `confidence: low`; the safety net is the suite, which is appropriate, not sufficient to make the diff reviewable in one sitting.

#### Suggestions
- State explicitly: lift `CancelOnDropStream` out of `query_rag` to module scope in `service.rs`, then continue the function body.
- Split the service move’s file map in the SUMMARY (admission vs ports vs stream) so review is possible.

#### Risk Assessment
**MEDIUM.** Right design; the nested type is the execution trap.

---

### 06-03 — Test-root rehoming

#### Summary
This is the step that actually closes DEBT-P3-MODULE-GRAPH. `tests.rs` really does open with `use super::*;` (`engine/src/tests.rs:9`), and `workflow_phase5_production.rs` uses `crate::` against the binary. Pinning the measured lib/bin split only after this plan is correct.

#### Strengths
- Forbids a second `workflow_phase5` declaration; `lib.rs:15-17` already owns it via `#[path]`.
- Source-text guard at `engine/src/tests/workflow_phase5.rs:2392-2445` is real; leaving `generation/mod.rs` untouched is mandatory.
- Gate-script comment (“values are measurements, update in the same commit”) is the protocol every later plan depends on.

#### Concerns
- **MEDIUM** — `src/tests.rs` + `src/tests/` is legal, but `workflow_phase5.rs` lives in that directory while being declared from `lib.rs` via `#[path]`, not from `tests.rs`. Easy to double-declare during the import rewrite.
- **LOW** — “128 cases follow them” is the pre-06-01 binary count. After 06-01’s 6 chunker tests move, the remaining binary mass is ~122. Harmless if the script records measurements.

#### Suggestions
- Add a negative grep: `engine/src/tests.rs` must not contain `mod workflow_phase5;`.
- Do not treat 261/0 as forceable; keep the plan’s “record what was measured” rule.

#### Risk Assessment
**MEDIUM.** Highest mechanical churn in the restructure; design is sound.

---

### 06-04 — Go package split, part A

#### Summary
Low-churn half of D-82 is correctly chosen. `loadConfig` is `gateway/main.go:57-80` with the three `BindEnv` names byte-for-byte as claimed. SSE/DTO types are unused by tests, so this half really is ~five test edits. Go 1.25 pin matches `gateway/go.mod:3`.

#### Strengths
- Telemetry stub with **no** OTel import matches D-82/D-36 (6.2 owns contents).
- Fail-closed `database_url` / prod `sslmode=disable` stay in the moved loader.
- “Do not assert per-package distribution yet” is the right analogue of 06-01.

#### Concerns
- **MEDIUM** — Task 1 prose says the before-state is a single row `gateway 67` because `main_test.go` is the only test file. It is not: `gateway/db/document_test.go` has 7 `Test` functions. A TOTAL of 67 is correct (60+7); a per-package `gateway == 67` assertion is not.
- **LOW** — `writeWorkflowEventSSE` → exported `WriteWorkflowEvent` is a rename across the package boundary; production call sites in `queryRAG` must all move or the build fails. Tests don’t name the old identifier, so that’s production-only.

#### Suggestions
- Script before-state must print `gateway 60` and `gateway/db 7` (or equivalent paths). Never write `gateway 67` as a per-package expected value.
- Keep Task 1’s “TOTAL only” rule; do not let the prose override it.

#### Risk Assessment
**LOW.** Prose is wrong; the specified TOTAL gate is right.

---

### 06-05 — Go package split, part B

#### Summary
High-churn half belongs alone. Insecure dial stays in `run()` (`gateway/main.go:1082`, `insecure.NewCredentials()`), matching D-03/D-06. `handlePreStreamError`’s structural `Trailer()` assertion (`:783`) will keep matching if the relocated error keeps that method (`:287`).

#### Strengths
- Constructor instead of cross-package struct literals is the right Go seam for 06-07 and 6.2 `otelgrpc`.
- Test doubles stay in `package main`; not exported from the production package.
- Task 1 expected to break `go test` until Task 2 is explicit and correct.

#### Concerns
- **HIGH** — Task 2 acceptance/verify: `grep -c '^func Test' gateway/main_test.go` equals **67**. Current file has **60**. This plan adds no tests. The gate fails on HEAD.
- **LOW** — `grpcEngine` appears as a composite literal in tests; qualifying it as `engineclient.GRPCEngine{…}` is fine only if the constructor is not the only legal construction. If Task 1 unexports fields, Task 2’s 5 sites need the constructor, which the plan does not say.

#### Suggestions
- Change the 67 assertion to the **suite** total (`scripts/gateway-test-targets.sh` TOTAL) or to `60` in `main_test.go`.
- If `GRPCEngine` fields are unexported, require tests to use the constructor (or keep a test-local stub, which the plan already prefers via `engineFunc`).

#### Risk Assessment
**MEDIUM.** Design is right; the 67-in-`main_test.go` gate is a false red.

---

### 06-06 — Wave-0 test surface

#### Summary
Necessary containment: exhaustive `QueryRagRequest {` literals are real (32 / 37 / 11 in the three named files ≈ 80). Fake ports already have error + stall (`ports.rs:278-313`); empty is unnamed; malformed-citation on `FakeGenerator` does not exist (`generation/mod.rs:504-527` is `new` / `with_responses` / `calls` only). Go has no whole-payload key-set assertion today, so 06-07’s new JSON keys would be invisible.

#### Strengths
- Migrating tests **before** the proto edit is the whole point of D-74’s reviewability.
- Leaves the six production `Notice {` sites for 06-07. Current production sites are `workflow/mod.rs` (2), `graph_context.rs` (1), `retrieve.rs` (1); confirm events.rs in-plan.
- `Default::default()` + field assignment (not struct-update) is mechanically grepable.
- Source-text guard: append-only on `FakeGenerator`’s inherent impl is the only safe edit.

#### Concerns
- **HIGH** — Acceptance: `grep -rn 'QueryRagRequest {' engine/src | grep -v testkit` must be empty. That pattern matches `pub struct QueryRagRequest {` in `engine/src/pb/lancet/v1/lancet.v1.rs:59`. The gate is red on an untouched tree and stays red after a perfect migration.
- **MEDIUM** — `engine/src/retrieval/tests.rs:896` is an extra `QueryRagRequest {` outside the three migration files. Research’s “80” missed it. After Task 1 it still fails the (even repaired) grep.
- **LOW** — Task 3’s Go exact-key tests must land **before** 06-07 adds keys, or they snapshot the post-change set and never prove the addition. Ordering vs 06-07 is correct; the tests must freeze the **current** key set.

#### Suggestions
- Exclude `engine/src/pb/**` (and maybe `**/lancet.v1.rs`) from the grep, or match construction (`let … QueryRagRequest {`, `&QueryRagRequest {`).
- Add `engine/src/retrieval/tests.rs` to the migration file list.
- Record the exact current SSE key set in the SUMMARY so 06-07 has a before/after.

#### Risk Assessment
**HIGH** until the grep is fixed; **LOW** after. The work itself is right.

---

### 06-07 — Consolidated additive wire contract

#### Summary
This is the one-way contract plan, and it is shaped correctly: blocking-human checkpoint on vocabulary, then proto+regen, then Rust derivation, then Go plumbing in the **same** plan because `DisallowUnknownFields` (`gateway/main.go:677`) turns an unwired field into HTTP 400. `optional bool` is required for request-then-config-then-default. Next tags are free. Regenerating both trees together is the 05-17/05-23 fix.

#### Strengths
- Checkpoint option `research-corrected` matches the code: `retrieve.rs` has no graph port (struct fields at `:13-19`), so `NOTICE_CODE_RETRIEVAL_DEGRADED_GRAPH` is unemittable.
- `GRAPH_CONTEXT_DISABLED` vs `GRAPH_UNAVAILABLE` is required for 06-08/6.3.
- Migrating runner gates from `n.code == "NO_EVIDENCE"` (`runner.rs:427`, `:481`) in the same commit as the constructor prevents dual representations.
- Task 1 expected Rust compile break (exhaustive `Notice {`) is called out; Go should still build.

#### Concerns
- **MEDIUM** — ROADMAP Phase 6 SC4 still names a single `RETRIEVAL_DEGRADED` notice. This plan publishes `RETRIEVAL_DEGRADED_DENSE` / `RETRIEVAL_DEGRADED_BM25` and reserves graph. That is the better contract, but SC4’s wording is now false until 6.4. An auto-select of `ai-spec-literal` would ship the dead enum value D-76 forbids removing.
- **MEDIUM** — `NOTICE` / `WARNING` string codes at `workflow/mod.rs:117-126` are on the wire today. Renaming them to `MODEL_NOTICE` / `MODEL_WARNING` is a deliberate break; the checkpoint says nothing in-repo reads them. Any out-of-repo client would see it. Keep that as an explicit human choice, not a silent default.
- **LOW** — Task 1 requires `buf generate` against remote plugins and a clean `git diff` on the **untouched** tree. If committed bindings already drifted, this plan must stop; that is correct, but it is an external blocker.

#### Suggestions
- Do not let `--auto` skip the checkpoint; the gate_rationale is right.
- Add one sentence to the SUMMARY mapping ROADMAP SC4’s `RETRIEVAL_DEGRADED` onto the two path-specific codes.
- After regen, assert prost `Option<bool>` and Go `*bool` before starting Task 2 (already in acceptance — keep it).

#### Risk Assessment
**MEDIUM.** One-way, but the checkpoint and the three-column-in-one-plan rule are the right controls.

---

### 06-08 — Graph ablation + GRAPH_UNAVAILABLE

#### Summary
Correct first behavior plan. D-08’s two silent sites are exactly `graph_context.rs:112-115` (empty facts) and `:147-150` (no port); failure notices at `:134-143` should stay untouched. Distinct ablation vs unavailability codes are required for Phase 6.3. Engine-process “e2e” via `query_rag` is honestly scoped; HTTP was 06-07’s job.

#### Strengths
- Early return **before** port-presence and timeout, asserted via fake call counters, distinguishes “never called” from “empty result.”
- Distinct messages on the two `GRAPH_UNAVAILABLE` sites match de-dup on `(code, message)`.
- No config key for ablation (measurement affordance, default false) avoids conflating it with model-only.

#### Concerns
- **LOW** — CONTEXT.md D-08 cited absent-port as `:145-148`; the `else` is `:147-150`. Harmless drift.
- **LOW** — No two-process test. Acceptable given 06-07’s decoder test, but 6.3 is the first real HTTP ablation client.

#### Suggestions
- Pin the two unavailability **message** strings in the SUMMARY; 06-12/6.4 will need them.
- One workflow-level test that ablation and unavailability never co-occur (early return) is already in the behavior block — keep it as an ordered assertion, not `any()`.

#### Risk Assessment
**LOW.** Notice-only on existing branches plus one new early return.

---

### 06-09 — Retrieval degrade (D-13)

#### Summary
This is the real behavior change: both retrieve call sites currently `return Err(err)` (`retrieve.rs:76`, `:107`), which fails the node. Converting them to the graph-node degrade shape is what D-13 actually requires. Per-variant BM25 tolerance is the non-obvious part (loop at `:90-132`). Ordering before 06-10 is correct: both-paths-failed converges on empty candidates + `NO_EVIDENCE`.

#### Strengths
- Asserting **absence** of `node_failed` / failed terminal, not just notice presence, is the right test (otherwise the old fail-closed path still passes).
- Three-notice order (dense, lexical, `NO_EVIDENCE`) follows source order and is what 06-10 consumes.
- Same-kind per-variant failures collapsing via `(code, message)` de-dup is specified, not left to chance.
- Absent-dense-port branch (`:78-80`) explicitly out of scope — flagged rather than silently “fixed.”

#### Concerns
- **MEDIUM** — Fusion and rerank still fail the node (`retrieve.rs:123-128`, `:140-145`, `:152-157`). A healthy dense/BM25 pair with a fusion error still produces a failed terminal. D-13 is about **retrieval paths**, so this may be intended residue; it is not named in the plan, and a reviewer of SC4 could think “one path failing” includes fusion.
- **LOW** — Task 1 verify `return Err(err)` count = 1 assumes the remaining one is BM25. Cancellation uses `return Err(NodeError::cancelled())`, which would not match. Fine, but brittle if someone writes `return Err(err)` in a new arm.

#### Suggestions
- Record fusion/rerank fail-closed as explicit leftover in the SUMMARY (backlog or accepted).
- Keep the both-paths test as a sequence, not a set.

#### Risk Assessment
**MEDIUM.** Highest-consequence production change in the phase; tests as specified would actually catch a no-op.

---

### 06-10 — Model-only opt-in

#### Summary
The two-guard and two-gate findings are confirmed in source and are the difference between a plan that compiles and a feature that works. Fail-closed env parsing for the new key only, request-then-config-then-false, and default off are all right. **The plan still cannot deliver D-10/D-11 as written**, because bypassing the runner does not reach generation: prompt assembly hard-fails on empty evidence.

#### Strengths
- Second grounding guard at `generation/mod.rs:193-200` (`cited_evidence_ids.is_empty()`) really would reject every model-only answer if only the ModelOnly arm were lifted.
- Production gate’s second disjunct (`final_candidates.is_empty() && evidence_blocks.is_empty()`, `runner.rs:428`) is real; the tracer gate (`:481`) lacks it. Bypassing only the notice test is the silent bug the plan names.
- `GroundingLimits` is already the validation policy object (`generation/mod.rs:88-92`); extending it avoids a third parameter. Fields are private — executor will need a setter/`with_allow_model_only`. Populate from **context** at `generate.rs:134-137`, not from the startup `Arc<GroundingLimits>` on `EffectiveRagSettings` (`main.rs:489-498`), or the per-request flag never arrives.

#### Concerns
- **HIGH** — After the runner bypass, `AssemblePromptNode` still does this:

```70:75:engine/src/workflow/nodes/assemble_prompt.rs
            if ctx.evidence_blocks.is_empty() {
                return Err(NodeError::new(
                    NodeErrorKind::PromptAssemblyFailed,
                    "No evidence blocks provided for prompt assembly",
                ));
            }
```

  `pack_evidence_and_graph_prompt` also returns `PromptAssemblyError::EmptyEvidence` (`prompt.rs:333`, tests at `tests.rs:6278` and `workflow_phase5.rs:2299` **require** that error). Task 3’s `files` list is `runner.rs`, `generate.rs`, `workflow/mod.rs`, `workflow_phase5.rs` — not `assemble_prompt.rs` or `prompt.rs`. D-11 says AssemblePrompt/GenerateAnswer **run**. As written, opted-in zero-evidence still ends in `PromptAssemblyFailed`.
- **MEDIUM** — Task 3 says “ensure a well-formed prompt with an empty evidence set” in prose but gives no algorithm (skip the empty check when opted in vs change packer vs separate model-only prompt). Existing EmptyEvidence tests will fail if the packer is relaxed unconditionally.
- **LOW** — Threading a request flag through `GroundingLimits` (a numeric ceiling type) is a bit muddy; documented, but easy to bake the config default into the node at startup and forget the overlay.

#### Suggestions
- Add `assemble_prompt.rs` (and likely `prompt.rs`) to Task 3. When `ctx.allow_model_only` and evidence is empty: skip the hard fail, pack a prompt with zero evidence blocks (or a dedicated empty-evidence template), do **not** change the non-opt-in `EmptyEvidence` tests.
- Construct per-call `GroundingLimits` (Copy) with `allow_model_only` copied from `ctx` at the `validate_grounding_with_limits` site.
- Keep D-16: no score cutoff.

#### Risk Assessment
**HIGH.** Without the prompt-assembly change, SC3 is not met. The rest of the plan is the right shape.

---

### 06-11 — Citation repair + reconciliation + precedence text

#### Summary
Matches D-14/D-17/D-18/D-19. Today’s fail-closed branch is `generate.rs:154-164` (resolved count ≠ cited count → `LlmGenerationFailed`). Unicode crates are already in `engine/Cargo.toml`. Default `citation_repair_enabled = true` is a production behavior change for all clients; off restores today. Reconciliation-before-repair-integration is the right seam (`update_from_model_output` at `workflow/mod.rs:107-114` is the single basis copy).

#### Strengths
- Tie = drop (never first-match) is the honesty rule the prohibition requires.
- Repair notices keyed on **marker text** so two drops survive de-dup.
- “Never strengthen” (model-only stays model-only even if citations resolve) is specified and testable.
- Prompt append in `base_system_policy()` (`prompt.rs:205-210`) with schema frozen in `openrouter.rs` matches D-19.
- No new crate; `git diff engine/Cargo.toml` empty is the right anti-scope-creep gate.
- Task 2 verify `Notice {` count = 1 in `workflow/mod.rs` (the 06-07 constructor) prevents a second inline literal.

#### Concerns
- **MEDIUM** — Task 2’s engine assessment mentions “whether repair stripped markers,” but repair is Task 3. Task 2 can only reconcile on resolve/no-resolve; Task 3 must **call the same seam** after stripping, not invent a second `answer_basis` assignment. The plan says “exactly one site” — Task 3’s files omit `workflow/mod.rs`, which is good only if generate.rs goes through `update_from_model_output` after mutating citations.
- **MEDIUM** — Default-on repair will fail every existing test that expects the current error string `"failed to resolve all cited evidence identities completely"` (`generate.rs:159`). The plan says update those tests; the SUMMARY must list each by name (same discipline as 06-09).
- **LOW** — Precedence text increases trust in retrieved evidence, including hostile corpus content. The plan records the trade; 6.4 limitations should too (already D-71).

#### Suggestions
- Task 3: after strip, re-enter the Task 2 seam with the post-repair citation set so total-drop downgrades without a second assignment site.
- Keep repair **off** in any test that is asserting the old fail-closed message.
- Do not put `reqwest`/`async` in `citations.rs` (already gated).

#### Risk Assessment
**MEDIUM.** Behavior change is well specified; default-on plus the one-basis-site constraint need careful Task 3 wiring.

---

### 06-12 — Bad-input matrix

#### Summary
Correctly test-only over existing admission. `QueryRequest::from_values` already rejects empty/whitespace (`retrieval/mod.rs:365-370`), oversize, and filter bounds; `query_rag` maps those kinds at `main.rs:1839-1872` **with `?`**, so invalid input **is** rejected. The `_query_request` name means the **Ok** value is unused, not that validation is skipped. Unmatched filter as success+`NO_EVIDENCE` matches shipped Phase 03. Last wave because of the count-gate scripts is the right dependency reason.

#### Strengths
- Table as the artifact Phase 6.4 publishes; tests generated from it, not the reverse.
- Zero fake-port call counts on rejecting rows prove “before retrieval/provider,” which the discarded-Ok value makes slightly subtle.
- No duplicated Go validator; HTTP 400 comes from `handlePreStreamError` mapping `InvalidArgument` (`main.go:796-798`).
- Negative bound: filter has no numeric field; mapping onto config `invalid_settings` is honest.
- Analog table already exists at `gateway/main_test.go:1041-1061`.

#### Concerns
- **LOW** — “Validation result is discarded” undersells that `?` still rejects. Do not “fix” by using `_query_request` downstream unless a later plan needs the normalized query; changing that here would be production scope.
- **LOW** — HTTP unmatched-filter rows need a stub engine that returns success, not InvalidArgument. Specify that or the non-rejection rows 400 via a mis-stub.

#### Suggestions
- Header table: include `invalid_settings` as the negative-bound stand-in, as the action already says.
- Drive gRPC tests through the real `query_rag` (plan already does) so a future move of validation cannot skip the matrix.

#### Risk Assessment
**LOW.** Enumeration over a working surface; unmatched-filter disposition is the important product call.

---

### Phase-goal coverage

| SC | Claim | Plans | Verdict |
|----|--------|-------|---------|
| 1 Module graph | Binary imports lib; Go split four packages | 06-01…06-05 | Achievable |
| 2 Wire contract | One additive proto + both bindings + flags on HTTP | 06-07 (after 06-06) | Achievable; checkpoint is load-bearing |
| 3 Model-only | Opt-in, default off, zero citations | 06-10 | **Not as written** — AssemblePrompt empty-evidence fail |
| 4 One-path degrade | `answer_basis = RETRIEVAL` + path-named notice | 06-09 (+ 06-07 enum split) | Achievable; ROADMAP still says one `RETRIEVAL_DEGRADED` token |
| 5 Citation repair | Normalize-then-strip, no second call | 06-11 | Achievable |
| 6 Bad-input matrix | Table-driven gRPC+HTTP, reject before work | 06-12 | Achievable; validation already exists |
| 7 Graph unavailable | Empty + absent-port notices; source-chunk proof | 06-08 | Achievable |

D-77…D-86 (no ROADMAP/REQUIREMENTS edits, no CI, no v1 closure) are consistently restated and not violated.

---

### Priority fixes before execution

1. **06-10** — Put `assemble_prompt.rs` / empty-evidence packing in Task 3; gate the new path on the resolved opt-in so existing `EmptyEvidence` tests stay green. (HIGH)
2. **06-06** — Exclude generated `engine/src/pb/**` from the `QueryRagRequest {` grep; migrate `retrieval/tests.rs:896`. (HIGH)
3. **06-05** — Assert 60 tests in `main_test.go` or 67 across the gateway module tree, not 67 in `main_test.go`. (HIGH)
4. **06-04** — Document before-state as `gateway` 60 + `gateway/db` 7. (MEDIUM)
5. **06-02** — Un-nest `CancelOnDropStream` from `query_rag`. (MEDIUM)
6. **06-01** — LANCET literal gate by equality to the recorded before-count. (MEDIUM)
7. **06-09** — Name fusion/rerank fail-closed as leftover. (MEDIUM)
8. **06-07** — Human checkpoint required; map SC4’s wording onto the two path-specific codes. (MEDIUM)


---

