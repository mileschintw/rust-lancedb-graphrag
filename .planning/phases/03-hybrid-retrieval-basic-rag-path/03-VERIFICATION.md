---
phase: "03-hybrid-retrieval-basic-rag-path"
verified: "2026-08-05T21:00:38Z"
status: gaps_found
score: "98/101 plan must-haves verified; roadmap 4/4 success criteria verified"
behavior_unverified: 1
overrides_applied: 0
requirements:
  - id: RAG-02
    status: blocked
  - id: RAG-04
    status: satisfied
plans_checked: 23
plan_files_checked: 23
summary_files_checked: 23
findings:
  blockers: 5
  warnings: 13
  info: 1
  total: 19
next_action: "Plan focused Phase 03 gap closure for bounded provider reads, atomic staging generations, and the live transport/endpoint security findings; keep Phase 03 pending."
next_command: "/gsd:plan-phase 03 --gaps"
re_verification:
  previous_status: gaps_found
  previous_score: "76/79"
  gaps_closed:
    - "The single GroundingLimits carrier is now constructed and consumed by evidence packing, provider generation, and grounding validation."
    - "Retrieval ceilings, bounded BM25 workspace, finite fusion, gateway request limits, and gateway JSON pre-encoding are present and covered by focused tests."
    - "Plans 03-19 through 03-23 now exist in the checkout and were independently checked."
  gaps_remaining:
    - "Provider body reading still uses reqwest Response::chunk and aggregates each chunk before the max-plus-one check."
    - "Raw staging generation allocation is read-max-then-append without per-document serialization or a uniqueness/CAS guard."
    - "Committed configuration and configurable provider/engine transports do not enforce the reviewed security boundary."
  regressions:
    - "The current provider resource and staging concurrency findings remain live after the late plans."
gaps:
  - truth: "03-20: every provider response is bounded while streamed, before untrusted response allocation."
    status: failed
    reason: "The shared reader checks Content-Length and aggregate buffer length, but response.chunk can materialize an oversized frame before the guard runs; the plan's required pre-materialization stream bound is absent."
    artifacts:
      - path: "engine/src/client/mod.rs:40-59"
        issue: "read_body_limited uses response.chunk, Vec::new, and only then rejects buffer.len plus chunk.len greater than 262144."
      - path: "engine/src/generation/openrouter.rs:297-318"
        issue: "Model metadata depends on the incomplete shared-reader invariant."
      - path: "engine/src/generation/openrouter.rs:469-490"
        issue: "Chat depends on the same incomplete shared-reader invariant."
    missing:
      - "Use a bounded stream/reader that does not retain an over-limit frame before rejection, and add an oversized-single-frame regression."
  - truth: "03-23: raw staging replacement allocates a monotonic generation safely for each stable document identity."
    status: failed
    reason: "Two replacements can read the same maximum generation and append the same successor generation; the latest-row selector then rejects equal generations instead of providing atomic allocation."
    artifacts:
      - path: "engine/src/main.rs:839-902"
        issue: "persist_raw_with_boundary reads old_max_gen and computes new_gen before append, with no per-document lock, compare-and-swap, or uniqueness guard."
      - path: "engine/src/main.rs:683-687"
        issue: "Duplicate equal generations are rejected during selection, showing the race's observable failure mode."
    missing:
      - "Serialize generation allocation or enforce a Lance-native uniqueness/CAS invariant, then test concurrent replacement of one document_id."
  - truth: "Committed provider and service transports remain within the intended security boundary."
    status: failed
    reason: "Live code confirms the advisory CR-03/CR-04/CR-05 findings: committed plaintext database credentials/TLS-disabled config, insecure Go-to-Rust gRPC, and arbitrary configurable provider endpoints receiving bearer credentials."
    artifacts:
      - path: "config/config.toml:3"
        issue: "Committed database_url contains postgres:postgres and sslmode=disable."
      - path: "config/config.example.toml:7"
        issue: "The example repeats the reusable plaintext credential and disabled TLS default."
      - path: "gateway/main.go:890"
        issue: "The gateway uses insecure.NewCredentials for the engine connection."
      - path: "engine/src/main.rs:359-372"
        issue: "Effective settings validate endpoints only for nonblank strings."
      - path: "engine/src/generation/openrouter.rs:262-269,277-278,440-444"
        issue: "with_endpoints accepts arbitrary values while model and chat requests attach the API bearer token."
    missing:
      - "Remove committed reusable credentials and define the supported local-only/TLS boundary."
      - "Add authenticated/TLS engine transport or enforce a safe local-only deployment boundary."
      - "Validate provider endpoint scheme/host/allowlist before any bearer-authenticated request."
deferred:
  - truth: "RAG-03 degraded/model-only behavior and its citation/lifecycle/negative-input/graph hardening contracts"
    addressed_in: "Phase 06"
    evidence: "ROADMAP.md Phase 03 explicitly defers RAG-03 to Phase 06; Phase 06 success criterion 7 names DEBT-RAG-01, DEBT-RAG-03, DEBT-RAG-04, DEBT-RAG-05, and DEBT-RAG-06."
  - truth: "Conditional security/resource review gates DEBT-CR-04 and DEBT-CR-05"
    addressed_in: "Phase 06 unless an earlier trigger applies"
    evidence: "ROADMAP.md Phase 06 success criterion 6 says these gates are reviewed later only when they have not triggered earlier. The current committed credentials, insecure transport, and bearer-endpoint behavior are reported as live findings rather than silently classified as RAG-03 debt."
  - truth: "D1 full-message logging and other explicitly accepted safe-log/deferred ledger items"
    addressed_in: "Recorded follow-up hardening"
    evidence: "engine/src/main.rs:824-825 logs the full D1 message, and deferred-items.md records the accepted DEBT-D1-SAFE-LOG waiver."
behavior_unverified_items:
  - truth: "03-23: after successor verification, an old-generation deletion failure leaves both physical rows present while the operation fails visibly."
    test: "Inject append, verification, and old-generation deletion failures, then inspect staged_documents_v2 physical rows and payloads rather than only calling the latest-row reader."
    expected: "Append or verification failure leaves the old row; deletion failure leaves both old and successor rows, returns an error, and does not delete the successor."
    why_human: "The existing deletion-failure test reads through latest-generation selection and asserts only the selected filename; it does not prove that the old physical row remains, and no concurrent/physical-row assertion exercises the full invariant."
---

# Phase 03: Hybrid Retrieval and Basic RAG Path Verification Report

Phase Goal: As a chat service API user, I want to ask a question using hybrid vector and BM25 retrieval, so that the LLM returns an answer grounded in completed corpus evidence.

Verified: 2026-08-05T21:00:38Z

Status: gaps_found

Re-verification: Yes. A prior verification existed with status gaps_found and score 76/79. This report re-checks the current checkout, including Plans 03-19 through 03-23; prior claims are historical context only.

## Verdict

The MVP happy path is implemented and independently runnable: a Go request reaches Rust over gRPC, dense and BM25 retrieval are fused, evidence is packed, the provider-neutral grounding validator enforces retrieval citations, and the cross-runtime test returns a structured response. Initial BM25 construction also gates readiness, and the async reranker/NoOp contract is present.

The Phase 03 goal is not accepted as complete. Two plan-level safety invariants are not achieved: provider body bounding is post-chunk rather than pre-materialization, and raw staging generation allocation is racy. The refreshed review's three transport/configuration findings are also confirmed in live source. These are current findings, not the explicitly deferred RAG-03 behavior. Phase 03 must remain pending.

## MVP User Flow Coverage

The roadmap goal validates as a proper MVP user story. The observable flow is:

| User-flow step | Expected result | Live evidence | Status |
| --- | --- | --- | --- |
| Submit a valid query over a completed corpus | Go validates the body and calls typed Rust QueryRAG | gateway/main.go:645-715; gateway/main.go:875-906 | VERIFIED |
| Retrieve with both sources | Dense Lance retrieval and local BM25 produce candidates under shared settings | engine/src/retrieval/dense.rs:41-133; engine/src/retrieval/bm25.rs:233-336 | VERIFIED |
| Fuse and ground evidence | Finite deterministic RRF, bounded evidence, exact citation IDs, retrieval/mixed-only validation | engine/src/retrieval/fusion.rs:35-197; engine/src/generation/mod.rs:156-311 | VERIFIED |
| Return one structured answer | Rust returns the typed response and Go preserves basis, notices, warnings, citations, and snapshot | engine/src/main.rs:1200-1320; gateway/main.go:633-715; TestRAGQueryCrossRuntime | VERIFIED |

This proves the happy path, not the full phase-quality contract. The failed plan truths below prevent a PASS verdict.

## Roadmap Success Criteria

| # | Success criterion | Evidence | Status |
| --- | --- | --- | --- |
| 1 | Valid query over completed corpus uses vector and BM25 retrieval, deterministic bounded fusion, and returns one grounded structured answer with resolving citations | Cross-runtime Go test; Rust retrieval/fusion/generation tests; engine/src/main.rs:1200-1320 | VERIFIED |
| 2 | Go /rag/query receives the structured grounded answer through Rust gRPC | gateway/main.go:645-715,875-906; proto/lancet/v1/lancet.proto; TestRAGQueryCrossRuntime | VERIFIED |
| 3 | Initial BM25 build completes before readiness; failure prevents serving | engine/src/main.rs:1981-2049; engine/tests/config_startup.rs:297-375 | VERIFIED |
| 4 | Async pluggable Reranker and NoOpReranker pass-through exist | engine/src/rerank.rs; engine/src/retrieval/fusion.rs; reranker tests | VERIFIED |

The success criteria are satisfied on the exercised happy path, but they are not sufficient to override failed plan-level safety and security must-haves.

## Requirements Verdict

| Requirement | Roadmap assignment | Verdict | Evidence and reconciliation |
| --- | --- | --- | --- |
| RAG-02 | Phase 03 current MVP acceptance | BLOCKED | Dense/BM25 retrieval, filters, deterministic fusion, deduplication, grounding, and zero-match behavior are implemented and tested. The Plan 03-20 provider boundary and Plan 03-23 staging-generation safety gaps leave the complete RAG-02 contract unverified. REQUIREMENTS.md:12,49 remains unchecked. |
| RAG-04 | Phase 03 current MVP acceptance | SATISFIED | Reranker is async/object-safe, NoOpReranker preserves order, startup wiring uses it, and focused/full Rust tests pass. REQUIREMENTS.md:14,51. |
| RAG-03 | Phase 06, not a Phase 03 requirement | DEFERRED, NOT A GAP | ROADMAP.md and deferred-items.md explicitly exclude degraded/model-only fallback, citation repair/downgrade, re-ingestion/restart recovery, graph fallback, and exhaustive negative-input coverage from Phase 03. |

03-03-SUMMARY.md and 03-21-SUMMARY.md list RAG-01/RAG-03 as completed in summary metadata even though the Phase 03 roadmap requirements are RAG-02/RAG-04 and RAG-03 is explicitly Phase 06. Those claims were not accepted over the roadmap and live evidence.

## Must-Have Matrix

Every plan frontmatter truth was checked in plan order. V means source, wiring, and available behavioral evidence support the truth. F means a blocker. P means implementation is present and wired but the required invariant is not behaviorally proven by the existing test.

| Plan | Truths checked in plan order | Score | Evidence |
| --- | --- | --- | --- |
| 03-01 | T1 V Unicode BM25 snapshot/metadata; T2 V shared filters, weighted finite RRF, dedup; T3 V async object-safe NoOp; T4 V deterministic normalized query behavior | 4/4 | retrieval/bm25.rs, fusion.rs, rerank.rs and focused tests |
| 03-02 | T1 V bounded evidence/request; T2 V valid markers/citations; T3 V suspicious text stays non-executable; T4 V one timeout-bounded provider call; T5 V typed basis/notices with no Phase 03 model-only branch | 5/5 | generation/mod.rs, prompt.rs, openrouter.rs and generation tests |
| 03-03 | T1 V typed QueryRAG contract; T2 V gRPC reaches retrieval/generation; T3 V BM25 startup gate; T4 V validated TOML/env settings | 4/4 | proto contract, engine/main.rs, startup tests |
| 03-04 | T1 V bounded strict gateway POST and caller validation; T2 V identity/basis/notices/warnings/citations/snapshot preservation; T3 V configurable embedding transport seam | 3/3 | gateway/main.go:645-715; engine/main.rs; client/mod.rs |
| 03-05 | T1 V isolated real-process smoke; T2 V local mock provider exercises dense/BM25/fusion/evidence/generation; T3 V startup milestone and Ping; T4 V child environment/teardown; T5 V isolated fixture/process cleanup with live provider optional | 5/5 | gateway cross-runtime test, startup tests, scripts and fixtures |
| 03-06 | T1 V untrusted corpus stays outside executable prompt semantics; T2 V over-budget/Unicode evidence is omitted safely; T3 V provider output requires valid IDs/notices/usage and exact markers | 3/3 | generation/prompt.rs, generation/mod.rs and tests |
| 03-07 | T1 V settings control retrieval/evidence/citations/provider; T2 V evidence/citation character budgets; T3 V provider model identity; T4 V exact settings/index snapshot; T5 V invalid settings fail before readiness/provider | 5/5 | engine/main.rs, openrouter.rs, retrieval settings tests |
| 03-08 | T1 V 32 KiB gateway bound/413; T2 V locked request capacity; T3 V body close and timeout; T4 V strict provider JSON; T5 V no RAG-03 scope expansion | 5/5 | gateway/main.go:36-38,645-715; gateway tests; provider tests |
| 03-09 | T1 V citation IDs resolve to evidence; T2 V citation identity/title/section/content/score/rank/excerpt/truncation; T3 V notice/warning severity; T4 V unknown identity fails closed | 4/4 | generation/prompt.rs, engine/main.rs and service tests |
| 03-10 | T1 V nondefault embedding model identity; T2 V generation model/endpoint/timeout/sampling/max completion effective | 2/2 | engine/main.rs, client/mod.rs, openrouter.rs |
| 03-11 | T1 V one effective startup settings object; T2 V embedding identity/stable generation; T3 V BM25 before readiness; T4 V invalid settings/BM25 fail without listen; T5 V example keys/ranges | 5/5 | engine/main.rs:1981-2049; config example; startup tests |
| 03-12 | T1 V exactly-one reranker after fusion; T2 V NoOp order; T3 V zero source weights; T4 V finite deterministic RRF; T5 V reranked IDs flow to validation/citations; T6 V reranker error stops generation | 6/6 | rerank.rs, retrieval/fusion.rs and engine tests |
| 03-13 | T1 V only nonempty Retrieval/Mixed valid-marker output assembles; T2 V ModelOnly rejected; T3 V answer/IDs/notices/warnings/usage/wrapper fields bounded before public response; T4 V valid local answer uses shared generator/validator/citation path | 4/4 | generation/mod.rs:156-311; openrouter.rs:485-565; tests |
| 03-14 | T1 V production OpenRouter uses effective settings; T2 V provider errors retain session/correlation and do not fabricate; T3 V gateway preserves identity/classification; T4 V missing/blank API key refuses startup | 4/4 | main.rs:1991-2049; openrouter.rs:569-585; gateway/main.go |
| 03-15 | T1 V citation identity test isolation; T2 V fail-closed doubles; T3 V locked Rust gate in serial/parallel modes | 3/3 | Rust test modules and both full cargo runs |
| 03-16 | T1 V one GroundingLimits carrier; T2 V 16384/4096/20480 ceilings; T3 V in-limit nondefault and above-limit rejection; T4 V grounded RAG-02 and no RAG-03 | 4/4 | generation/mod.rs:79-149; main.rs:299-347,1262-1306; ceiling tests |
| 03-17 | T1 V transport failures map Unavailable/no generation; T2 V invalid embedding payloads map Internal/no generation; T3 V dense infrastructure failure differs from valid empty; T4 V error identity crosses Go boundary | 4/4 | client/mod.rs, retrieval/dense.rs, main.rs and fail-closed tests |
| 03-18 | T1 V zero-match success/no provider; T2 V exact gRPC empty response; T3 V exact HTTP 200; T4 V malformed input remains 400; T5 V D3-D5 deferred/chunk-only scope; T6 V RAG-04/no RAG-03 | 6/6 | engine/main.rs query path; gateway/main.go; zero-match/fail-closed tests |
| 03-19 | T1 V one GroundingLimits carrier with defaults 8192/2048/10240; T2 V nondefault carrier through pack/provider/usage/grounding; T3 V private carrier/no clamp/pre-ready rejection; T4 V D1 identity and recorded waiver; T5 V coverage opt-outs/ownership | 5/5 | generation/mod.rs; main.rs; deferred ledger; settings tests |
| 03-20 | T1 F all provider bodies bounded before response-frame materialization; T2 V Content-Length and chunked over-limit rejection; T3 V exact 262144 acceptance; T4 V typed fail-closed paths; T5 V unary/no public streaming | 4/5 | Tests pass the rejection cases, but client/mod.rs:48-56 uses response.chunk before checking aggregate size. |
| 03-21 | T1 V exact service ceilings; T2 V reject above ceilings/no clamp; T3 V defaults and absolute 100 limit; T4 V dense sends validated limit; T5 V BM25 bounded workspace; T6 V incremental filter normalization/dedup/rejection | 6/6 | retrieval/mod.rs:30-36,109-121,229-318; dense.rs:85; bm25.rs:233-336 |
| 03-22 | T1 V one contribution per source/chunk with overlap retained; T2 V finite RRF contributions/accumulators; T3 V gateway buffers JSON before status; T4 V deterministic finite grounded response | 4/4 | retrieval/fusion.rs:35-197; gateway/main.go:846-857; tests |
| 03-23 | T1 F monotonic generation allocation under replacement concurrency; T2 P physical failure-retention invariant unproven; T3 V latest non-deleted readers/replay; T4 V Int64 legacy compatibility/fail-closed schema; T5 V append/verify precedes old deletion/no in-place mutation | 3/5 | main.rs:683-687,839-936; db/mod.rs:74-157,230-250; staging tests |

Plan-level score: 98/101 truths verified. The F truths are Plan 03-20 T1 and Plan 03-23 T1. The P truth is Plan 03-23 T2 and is excluded from the verified count.

## Required Artifacts

All 23 plan files and all 23 matching summaries exist and were read. Summary completion, test, and probe claims were treated as hypotheses; no summary PASS was counted without live source or test evidence. The artifact verifier returned substantive artifacts for every plan that declared them, with two literal-pattern false negatives manually reconciled:

| Plans | Artifact query result | Independent disposition |
| --- | --- | --- |
| 03-01 through 03-03 | 13/13 passed | Existence, substantive implementation, and wiring verified |
| 03-04 | 3/4 passed | The missing embedding_endpoint pattern is a tool false negative: the client uses a generic endpoint field and main.rs wires EffectiveRagSettings.embedding_endpoint into it. Manually verified. |
| 03-05 through 03-13 | 39/39 passed | Existence, substantive implementation, wiring, and data flow verified |
| 03-14 and 03-15 | No artifact blocks | Truths and tests checked directly |
| 03-16 through 03-20 | 22/22 passed | Plan 03-20's helper exists and is used, but its streaming invariant is incomplete; the key link remains a gap |
| 03-21 | 5/6 passed | The missing MAX_SERVICE pattern is a tool false negative: ceilings are defined in retrieval/mod.rs and reached through EffectiveRagSettings.validate. Manually verified. |
| 03-22 | 6/6 passed | Existence, substantive implementation, wiring, and data flow verified |
| 03-23 | 4/4 passed | Symbol-style key-link checks were invalid for this plan; source and tests were traced manually |

The artifact query cannot turn a present helper into a verified streaming bound. Level 3 wiring exists for the helper, but Level 4 behavior is incomplete because a chunk can exceed the remaining allowance before the check.

## Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Gateway /rag/query | Rust QueryRAG | typed gRPC client and response mapping | VERIFIED | gateway/main.go:645-715; TestRAGQueryCrossRuntime |
| QueryRAG service | dense, BM25, fusion, evidence, generator | normalize, retrieve, rerank, pack, validate, assemble | VERIFIED | engine/main.rs:1200-1320 |
| EffectiveRagSettings | GroundingLimits | one validated Arc carrier | VERIFIED | engine/main.rs:299-347,1262-1306 |
| Dense settings | Lance query | validated candidate limit and normalized filters | VERIFIED | retrieval/dense.rs:48-96 |
| BM25 settings | candidate workspace | candidate-limit capacity and bounded insertion | VERIFIED | retrieval/bm25.rs:233-336 |
| Provider body reader | chat, metadata, embeddings | shared read_body_limited helper | PARTIAL | All paths call it, but client/mod.rs:48-56 uses chunk aggregation rather than a pre-materialization stream bound |
| Staged append verification | old-generation deletion | add, verify at current version, then delete | VERIFIED for sequential ordering | main.rs:902-934; concurrent allocation is a separate failed link |
| Staged rows | replay/status reader | maximum non-deleted generation per document_id | VERIFIED with race exposure | main.rs:668-801; equal-generation duplicates fail at 683-687 |
| Go JSON response | HTTP status commitment | buffer encode before WriteHeader | VERIFIED | gateway/main.go:846-857; TestWriteJSONEncodeFailureReturns500 |

## Data-Flow Trace

| Artifact | Data variable | Source | Produces real data | Status |
| --- | --- | --- | --- | --- |
| DenseRetriever | vector candidates | embedding client and Lance table query | Yes | FLOWING |
| Bm25Retriever | lexical candidates | completed snapshot and bounded candidate insertion | Yes | FLOWING |
| Fusion | merged candidates/ranks/scores | dense and BM25 vectors | Yes; finite checked | FLOWING |
| Evidence prompt | packed evidence blocks | fused candidate content and metadata | Yes; bounded | FLOWING |
| QueryRAG response | answer/citations/notices/snapshot | generator output validated against evidence | Yes; cross-runtime test | FLOWING |
| Staged replay | latest document generation | staged_documents_v2 rows | Yes, but equal-generation concurrency is unsafe | FLOWING WITH BLOCKER |

No public component was found to render a static or hardcoded empty answer. Zero-match is intentionally a successful typed response with an informational notice and no provider call.

## Automated Checks

Commands were run in the live checkout. No result below is based solely on a filter matching zero tests.

| Check | Result |
| --- | --- |
| cargo test --manifest-path engine/Cargo.toml --locked -- --test-threads=1 | PASS: library 56 passed/1 ignored; binary 96 passed/1 ignored; integration targets 18 and 9 passed |
| cargo test --manifest-path engine/Cargo.toml --locked | PASS: same nonzero test targets passed in parallel |
| cargo test --manifest-path engine/Cargo.toml --locked --lib effective_settings_carries_one_grounding_limits -- --test-threads=1 | PASS: 1 named test |
| cargo test --manifest-path engine/Cargo.toml --locked --lib openrouter_ -- --test-threads=1 | PASS: provider tests ran and passed in each relevant target |
| cargo test --manifest-path engine/Cargo.toml --locked --test config_startup service_ceiling_rejects_above_effective_limits -- --test-threads=1 | PASS: 1 named test |
| cargo test --manifest-path engine/Cargo.toml --locked --test config_startup service_ceiling_rejects_each_absolute_maximum -- --test-threads=1 | PASS: 1 named test |
| cargo test --manifest-path engine/Cargo.toml --locked --lib retrieval_filter_fusion_and_determinism -- --test-threads=1 | PASS: 1 named test |
| cargo test --manifest-path engine/Cargo.toml --locked --lib query_rag_fail_closed_ -- --test-threads=1 | PASS: 6 named tests |
| cargo test --manifest-path engine/Cargo.toml --locked --lib query_rag_valid_zero_match -- --test-threads=1 | PASS: 1 named test |
| cargo test --manifest-path engine/Cargo.toml --locked --lib read_staged_jobs_latest_generation_wins -- --test-threads=1 | PASS: 1 named test |
| cargo test --manifest-path engine/Cargo.toml --locked --lib persist_raw_ -- --test-threads=1 | PASS: 2 named tests |
| go test -count=1 ./... from gateway | PASS: gateway and gateway/db packages |
| go vet ./... from gateway | PASS |
| buf lint | PASS |
| go test -list 'TestRAGQueryCrossRuntime|TestWriteJSONEncodeFailureReturns500|TestRAGQueryRejectsOversizedBody|TestRAGQueryNoResults' ./... from gateway | PASS: all four names listed |
| go test -count=1 -run '^(TestRAGQueryCrossRuntime|TestWriteJSONEncodeFailureReturns500|TestRAGQueryRejectsOversizedBody|TestRAGQueryNoResults)$' ./... from gateway | PASS |
| cargo fmt --manifest-path engine/Cargo.toml --all -- --check | FAIL: formatting drift in current Rust files including engine/src/tests.rs and engine/tests/config_startup.rs; no formatter was run |

Focused staging tests prove sequential append-before-delete ordering and latest-wins selection. They do not prove concurrent generation allocation or physical old-row retention after a delete fault.

## Probe Execution

No scripts/*/tests/probe-*.sh files were present, and no Phase 03 plan or summary declared a probe path. Probe execution is not applicable; no probe PASS claim was accepted from summaries.

## Anti-Patterns and Advisory Findings

The source scan found no unreferenced TODO, FIXME, or XXX debt markers in Phase 03 production files. Findings:

| Severity | Live evidence | Finding |
| --- | --- | --- |
| BLOCKER | engine/src/client/mod.rs:48-56 | Post-chunk provider body check can retain an oversized frame before rejection; CR-01 and Plan 03-20 T1. |
| BLOCKER | engine/src/main.rs:872-902 | Read-max-then-append staging generation race; CR-02 and Plan 03-23 T1. |
| BLOCKER | config/config.toml:3; config/config.example.toml:7 | Reusable plaintext database credential and sslmode=disable; CR-03. |
| BLOCKER | gateway/main.go:890 | Go-to-Rust gRPC uses insecure.NewCredentials; CR-04 for non-local/shared deployment. |
| BLOCKER | engine/src/main.rs:359-372; generation/openrouter.rs:262-269,277-278,440-444 | Arbitrary nonblank provider endpoints receive bearer credentials; CR-05. |
| WARNING | cargo fmt check | Current Rust formatting gate fails. |
| WARNING | engine/src/lib.rs:1-8; engine/src/main.rs:28-34 | Overlapping library and binary module graphs increase drift risk. |
| WARNING | engine/src/main.rs:302,312,314 | Public scalar grounding settings coexist with the private carrier. |
| WARNING | engine/src/client/mod.rs:253-306 | Embedding dimension is checked, but finite-value validation is not evident at the client boundary. |
| WARNING | engine/src/main.rs:760-774 | Staged replay reads nullable Arrow values without an explicit null check. |
| WARNING | engine/src/main.rs:889-896 | Raw staging chunk settings saturate to i32::MAX instead of rejecting invalid persisted values. |
| INFO | engine/src/db/tests.rs:13 | “placeholders” is a nullable-field fixture test name, not a production stub or debt marker. |

03-REVIEW.md reports five blocker-level findings and twelve warnings. Live source confirms the five blockers above; the formatting check adds one warning to the report count. 03-REVIEWS.md/AgY was advisory, not evidence: its positive body-bounding assessment conflicts with the actual response.chunk implementation, while its high staged-generation concern is corroborated.

## Human Verification

Automated evidence cannot establish:

1. Plan 03-23 physical failure retention. After repair, inject append/verify/delete faults and inspect physical Lance rows and payloads. The current test only observes latest-wins output, so this invariant remains behavior-unverified.
2. Optional real OpenRouter smoke. With an intentionally supplied OPENROUTER_API_KEY, run the ignored structured-output smoke from Plan 03-02 and confirm one supported structured response with no credential or raw-evidence disclosure. Local mocks and provider-independent tests passed; no live credentialed provider call was made.

These items do not convert the current result to passed. The current status is already gaps_found because failed truths and live blockers take precedence.

## Current Gaps and Targeted Next Action

The closure should be narrow and must not plan the explicitly deferred RAG-03 feature set:

1. Replace the provider response read path with a truly bounded stream/reader that cannot materialize a frame beyond the remaining allowance; retain the shared 262144-byte policy across chat, metadata, and embeddings and add a single-frame regression.
2. Make per-document staged generation allocation atomic or serialized and add a concurrent replacement test. Extend delete-failure tests to count physical old and successor rows, not only latest-wins output.
3. Resolve the live transport/configuration security findings, or record an approved local-only boundary with enforcement that prevents remote/shared deployment from inheriting unsafe defaults.

Targeted next command: /gsd:plan-phase 03 --gaps

## Transition Decision

Do not transition ROADMAP.md or STATE.md to a completed Phase 03 state. The current verification routing is gaps_found, REQUIREMENTS.md correctly leaves RAG-02 and RAG-04 unchecked, and the phase must remain pending until the targeted gaps are closed and re-verified. RAG-03 remains deferred to Phase 06 and must not be promoted into the Phase 03 closure plan.

---

Verified: 2026-08-05T21:00:38Z

Verifier: the agent (gsd-verifier)
