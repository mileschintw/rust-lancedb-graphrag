---
status: complete
phase: 05-state-machine-workflow-events
source: [05-VERIFICATION.md]
started: 2026-08-18T10:06:50Z
updated: 2026-08-19T09:51:19Z
regapped: 2026-08-19T03:20:00Z  # merged fresh human_verification items from the 05-VERIFICATION.md re-verification at HEAD 721485c; Tests 2-4 and their recorded human resolutions preserved verbatim
status_note: |
  status stays `diagnosed` (the controlled vocabulary is diagnosed | partial | complete, per
  gsd-core/workflows/progress.md:230-235 and verify-work.md:637). The `## Gaps` block for G-05-1
  is still open: its root cause is closed in code by e831be3, which is exactly the
  gap-already-fixed case verify-work.md:427-429 reconciles, so `diagnosed` routes correctly.
  An earlier edit in this session briefly set `in_progress`; that token is not in the vocabulary
  and was reverted.
regapped_2: 2026-08-19T07:05:00Z  # MERGE, not regeneration. Tests 1-6 preserved verbatim including every `result:` line and every recorded `resolution:`; the `## Gaps` block for G-05-1 preserved intact. Added Tests 7-10 from the full re-verification at HEAD bb58a60. Test 1 keeps `result: issue` -- its root cause is now closed in code by e831be3, which UNBLOCKS the re-test but does not perform it. Summary counts recomputed.
---

## Current Test

[testing complete]

## Tests

### 1. Live OpenRouter end-to-end SSE run

expected: node_started/node_completed for all five nodes, one answer_chunk, one final_answer, one workflow_completed, no stream_error; the answer is grounded with real citations.
why_human: Every automated proof of the pipeline — including the decisive TestRAGQueryCrossRuntime — substitutes an httptest mock for OpenRouter's /embeddings, /models, and /chat/completions. The one live-provider test in the repo (generation::tests::openrouter_structured_output_smoke) is `#[ignore]` and did not run. Real provider latency, streaming semantics, and structured-output conformance have never been exercised against this state machine.
result: pass
resolution: "Live run against real OpenRouter (LANCET_GATEWAY__DATABASE_URL + OPENROUTER_API_KEY set) produced the full expected frame sequence: node_started/node_completed for all five nodes (ReformulateQuery, ExtractGraphContext, RetrieveHybrid, AssemblePrompt, GenerateAnswer), one answer_chunk (is_final: true), one final_answer, one workflow_completed (success: true), no stream_error. Citations present and structured (chunk_id/document_id backed). Note: cited source was a local fixture document (\"Dense retrieval fixture\", DENSE_FIXTURE_MARKER excerpt) since the dev LanceDB store holds fixture data, not a real corpus — pipeline mechanics (grounding, citation wiring, SSE framing) are fully proven end-to-end; user confirmed this matches expectations."
prior_result: issue
prior_reported: "Error: \"LanceDB schema drift detected for nodes: expected [...19 fields ending in content_type...], found [...same 19 fields plus community_ids, summary, summary_vector, unsummarized_refs]\" — engine.exe exits with code 1 on startup, before the gateway or /rag/query could even be reached."
prior_severity: blocker
unblocked_by: |
  Both G-05-1 root causes are now closed in code (plans 05-25 and 05-26, commits 967a897 and c815af1):
    - Blocker A: validate_schema carries an actionable remediation clause (engine/src/db/mod.rs:167-172);
      the stale local store was rebuilt. Verified empirically this pass — inspect_lancedb.exe reaches and
      passes DatabaseManager::open_and_validate against ./data/lancedb. data/lancedb.pre-05-25.bak preserved.
    - Blocker B: explicit LANCET_OPENROUTER__GENERATION_MODEL / __EMBEDDING_MODEL overrides added
      (engine/src/main.rs:661-668); gateway real-engine tests no longer read ambient config.toml for the model.
  Closing the blockers UNBLOCKS this test; it does not constitute it. The run still needs a real
  OPENROUTER_API_KEY and a human observer.
added_risk: |
  Per 05-VERIFICATION.md WARN-NEW-01: after 05-26 the real-engine tests pin openai/gpt-4o-mini while
  production ships dots-studio/dots-3-note-preview:free, so the structured-output capability preflight
  at engine/src/generation/openrouter.rs:425-434 is now exercised by NO automated test. This makes the
  live run more necessary, not less.

unblocked_by_2: |
  Re-verification at HEAD bb58a60 (2026-08-19): the reported failure -- "model capabilities
  response exceeds maximum body limit of 262144 bytes" -- is CLOSED IN CODE by plan 05-27,
  commit e831be3. Verified from source, not from the summary:
    - engine/src/client/mod.rs:16 defines MAX_MODELS_METADATA_BODY_BYTES = 10 * 1024 * 1024.
    - engine/src/generation/openrouter.rs:386-388 applies it via read_body_limited_with_limit on
      the /api/v1/models capability-preflight path (the 256KB MAX_PROVIDER_RESPONSE_BODY_BYTES is
      correctly retained for chat/embeddings).
  This test therefore remains `result: issue` DELIBERATELY. All three of its root causes (G-05-1
  Blocker A, Blocker B, and the models body limit) are now closed in code, so the run is fully
  UNBLOCKED -- but it still requires a real OPENROUTER_API_KEY and a human observer, and a
  verifier cannot perform it. Correct next action: re-run and record the observed frame sequence.

### 2. Decide and apply the disposition of the WR-05 `x-lancet-*` trailer regression

expected: Either engine/src/main.rs::query_rag re-attaches x-lancet-session-id / x-lancet-correlation-id / x-lancet-error-kind to its Status errors, or gateway/main.go:771-783 and the doubles at gateway/main_test.go:1089-1241 are deleted. Not both left as-is.
why_human: This is a cross-runtime contract ownership decision, not a defect with one correct fix. The engine side was deliberately deleted with the inline remainder in af42b10; whether the D-1 status metadata contract from Phase 03 is still wanted is a product/architecture call.
result: pass
resolution: "User chose option 1 (restore emission). Reinstated a `d1_status` helper in engine/src/main.rs and wired it into query_rag's two pre-stream error paths (invalid session_id; QueryRequest::from_values validation failures), re-attaching x-lancet-session-id / x-lancet-correlation-id / x-lancet-error-kind to the returned Status. gateway/main.go:771-783 and its test doubles at gateway/main_test.go:1089-1241 left as-is (contract restored, not deleted). Verified: cargo build clean; full engine suite 280/280 passing; go build/vet clean; TestQueryRAGRealInvalidRequestAndDisconnect and TestRAGQuerySSEFirstFrame still pass. Not exercised live end-to-end (blocked by the same engine-startup issue as Test 1)."

### 3. Reconcile Phase 05 traceability bookkeeping

expected: 05-11-SUMMARY's GATE-01/GATE-02/GATE-03 are corrected (or added to 05-12-TRACEABILITY-ERRATA.md), and REQUIREMENTS.md ORCH-01 and ORCH-05 are checked.
why_human: Requires a human decision on whether GATE-* were intended as new requirement IDs or were transcription noise; a verifier cannot invent the intent.
result: pass
resolution: "User chose: GATE-01/GATE-02 are new requirement IDs. Added both to REQUIREMENTS.md under Orchestration & State (marked satisfied, Phase 05), with descriptions from 05-11-SUMMARY's D2/D3 coverage. GATE-03 had zero coverage backing it in 05-11-SUMMARY.md — removed from its requirements-completed list rather than inventing a definition. Checked ORCH-01 and ORCH-05 in REQUIREMENTS.md (both evidenced complete). Documented the full reconciliation in 05-12-TRACEABILITY-ERRATA.md §8."

### 4. Review the 15 judgment-tier prohibitions carried forward from plans 05-01 through 05-07

expected: Each prohibition listed in the 05-VERIFICATION.md Prohibitions section is explicitly accepted or rejected by a human.
why_human: None declares a `verification:` tier, so all 15 are judgment-tier per ADR-550 D4. The verifier's spot-verdicts in the report are NON-AUTHORITATIVE and must never be absorbed into a silent pass.
result: pass
resolution: "User accepted all 15 prohibitions as-is, including the two flagged non-authoritative spot-verdicts (#7 DB tests silently skip in default go test ./... run; #15 05-07's file-touch prohibition cannot be re-derived at HEAD since later plans legitimately modified those files). No rejections; no new gaps from this test."

### 5. Restore Postgres and run the 11 TEST_DATABASE_URL-gated tests

expected: All 11 PASS — `TestWorkflowCheckpointPersistence`, `TestWorkflowCheckpointCancellationAtomicity`, `TestWorkflowCheckpointPendingDrainAndPersistence`, `TestEmbeddingFailureRestartConvergesAcrossRuntime`, plus the 7 gateway/db document/reconciliation-intent tests.
command: |
  docker compose up -d postgres
  cd gateway && TEST_DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable go test . ./db -count=1
why_human: These 11 tests are TEST_DATABASE_URL-gated and SKIPPED in the 2026-08-19 regression-gate run (Docker Desktop not running; nothing listening on 127.0.0.1:5432). SC4's persistence half — FIFO drain ordering (primary -> overflow -> pending) and cancellation atomicity — is a state-transition invariant. The presence of InsertWorkflowCheckpoint (gateway/checkpoint_sink.go:106-115) and RetainPending (main.go:802) proves the code is wired, not that the ordering invariant holds. The prior verification counted these as PASS against a container that is no longer up; that evidence is not reproducible at HEAD.
result: pass
resolution: "All 11 TEST_DATABASE_URL-gated tests ran and passed against local Postgres (TestWorkflowCheckpointPersistence, TestWorkflowCheckpointCancellationAtomicity, TestWorkflowCheckpointPendingDrainAndPersistence, TestEmbeddingFailureRestartConvergesAcrossRuntime, and 7 gateway/db tests)."

### 6. Decide the disposition of CR-01 + WR-12 (coupled cancellation-path defects in engine/src/workflow/runner.rs)

expected: Either the `capacity()` fast path at runner.rs:90-98 is deleted in favour of the unconditional biased select (the review's recommended fix, with the failure event emitted before `cancel.cancel()`), or the current behaviour is explicitly accepted with the buffer-depth invariant recorded as a load-bearing assumption.
why_human: Not a gap today. The verifier re-derived the arithmetic from source at HEAD — the sink channel is per-request `mpsc::channel(100)` (main.rs:1861) with no production `.clone()`, and a workflow emits at most ~19 events (~30 with every node retried), so `capacity()` never reaches 0, the biased arm is never entered, and SC3 is not compromised. But that guard is an emergent property of a size constant, not an enforced invariant. It becomes live if per-token streaming AnswerChunks are added (planned 999.x), the 100-slot buffer is reduced, or the sink is cloned/shared. This is a design-debt acceptance decision, not a defect with one correct fix.
result: pass
resolution: "User accepted Option 1: current behaviour accepted with the buffer-depth invariant (mpsc::channel(100) vs ~19 events) recorded as a load-bearing assumption."

### 7. Re-confirm the CR-01 / WR-12 cancellation-path disposition against the code shape at HEAD

expected: Either `send_terminal_event`'s permit acquisition gains a bounded timeout arm, or the buffer-depth invariant is explicitly re-accepted against `engine/src/workflow/runner.rs:161-170` specifically.
why_human: |
  Test 6 above records a human acceptance of "the `capacity()` fast path at runner.rs:90-98".
  **That code no longer exists at HEAD bb58a60.** Commit 5354d1e deleted both capacity() fast
  paths -- applying the code review's own recommended fix -- and runner.rs:86-101 and :107-128 are
  now unconditional `tokio::select! { biased; cancel.cancelled() => .., tx.reserve() => .. }`.
  The same commit introduced a NEW un-cancellable, un-timeouted `self.tx.reserve().await` at
  runner.rs:167, plus `flush_pending_checkpoints(&uncancelled)` at :166 which loops the same
  unbounded reserve per pending envelope.
  So the artifact that was accepted is gone; only the buffer-depth premise carries over. And the
  new site has a DIFFERENT reachability story: `send_terminal_event` is deliberately
  cancellation-immune (that immunity is what actually closes prior CR-01's tail and guarantees a
  terminal frame reaches the client), so it cannot simply inherit the old acceptance.
  Verifier's re-derivation at HEAD: the sink channel is a per-request `mpsc::channel(100)`
  (main.rs:1885) feeding exactly one `WorkflowEventSink::new` (main.rs:1894) with no production
  `.clone()`; one workflow emits ~19 events on the clean path (~30 with every node retried), and
  `send_terminal_event` short-circuits on `tx.is_closed()`, so a dropped receiver is safe. The
  channel cannot fill at HEAD and no success criterion is compromised. The exposure is a receiver
  that is alive but not draining -- which becomes live if per-token AnswerChunks are added
  (planned 999.x), the 100-slot buffer shrinks, or the sink is cloned/shared across workflows.
result: pass
resolution: "User chose Option B: explicitly re-accepted the buffer-depth invariant against the current code shape (engine/src/workflow/runner.rs:161-170 / send_terminal_event's reserve at :167). Same call as Test 6, re-pointed at the new post-5354d1e code location. Rationale: risk profile unchanged from Test 6 (still cannot occur at HEAD -- 100-slot channel vs ~19-30 events, receiver-dropped case already handled via tx.is_closed() short-circuit); only becomes live if planned 999.x per-token AnswerChunk streaming ships, the buffer shrinks, or the sink is cloned/shared. No code change; invariant re-recorded as load-bearing."

### 8. Decide the disposition of the gateway bind-failure exit-code regression

expected: Either the `ListenAndServe` error path restores a non-zero process exit, or exit 0 on bind failure is explicitly accepted and recorded.
command: |
  # occupy the configured port, then:
  cd gateway && go run . ; echo "exit=$?"
why_human: |
  REGRESSION introduced by e8982d0 (the fix for prior WR-01). gateway/main.go:1094-1098 is now
  `go func() { if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
  logger.Error("gateway stopped", ...); stop() } }()`. `stop()` cancels sigCtx, `<-sigCtx.Done()`
  returns, Shutdown runs, and main returns normally -> **exit 0**. Before e8982d0 this path was a
  `logger.Fatal` (exit 1). A supervisor (systemd `Restart=on-failure`, a k8s liveness contract,
  CI) now reads "port already in use" as a clean shutdown.
  This is a product/ops decision, not a defect with one correct fix: the naive repair
  (`logger.Fatal`) reintroduces exactly the defect e8982d0 was written to close, because
  `os.Exit` skips the deferred `dispatcher.Close()` and loses buffered checkpoints. A correct fix
  needs an exit-code variable propagated after the defers run, or an equivalent restructure.
  Outside all five success criteria and outside ORCH-01..05 -- not a gap against the phase goal,
  but a real behaviour regression introduced by this phase's own remediation work.
result: pass
resolution: "User chose Option A: restore non-zero exit on bind failure via a correctly-ordered fix (exit code decided after deferred cleanup runs, not via logger.Fatal/os.Exit which would skip dispatcher.Close() and lose buffered checkpoints). Discovered this was ALREADY implemented by commit fe83e71 (fix(05): WR-04 WR-05 WR-08 WR-09..., landed earlier this session, prior to this UAT re-verification pass being drafted): main() now calls run() error and os.Exit(1) only after run() returns, so all defers (pool.Close, conn.Close, dispatcher.Close, etc.) execute first; ListenAndServe errors are routed through a serveErr channel into a `fatal` return value instead of calling stop() directly. Verified empirically: occupied port 8080, ran `cd gateway && go run .`, observed 'bind: Only one usage of each socket address...' followed by `exit=1`. No further code change needed."

### 9. Decide the disposition of terminal-event suppression on FinalAnswer delivery failure

expected: Either `emit_terminal_once` falls through to `send_terminal_event` when `FinalAnswer` delivery fails (mirroring the fix already applied one line later for the terminal checkpoint), or the early return is explicitly accepted as unreachable-with-a-live-client.
why_human: |
  engine/src/workflow/runner.rs:499-505 still `return`s before `WorkflowCompleted` when
  `send_event_or_cancel(final_answer)` fails, with `terminal_emitted` already latched at 488-494
  -- so no later call can emit the terminal event either. Commit 7ea20f2 (prior WR-02) removed the
  *checkpoint* early-return at :506-508, replacing it with a `tracing::warn!` fall-through, but
  left this one. The class of defect (an upstream delivery failure suppressing the protocol
  terminal event) survives one step earlier in the same function.
  Verifier's re-derivation at HEAD: currently benign. `send_event_or_cancel` returns Err only on
  Closed (the receiver is gone, so no client can observe anything) or Cancelled -- and the only
  canceller on the request path is `CancelOnDropStream::drop` (main.rs:1878-1882), which fires
  *because* the receiver was dropped, which also closes the channel. So no live client can observe
  the loss today. But that is an emergent property of there being exactly one canceller, not an
  enforced invariant, and it is one added cancel source away from being a real dropped-terminal
  bug on the SUCCESS path.
result: pass
resolution: "User chose Option A. Discovered ALREADY implemented by commit 0c96720a (fix(05): WR-01 WR-02 WR-03 WR-12 event sink concurrency, lazy ordinals, and terminal delivery, landed 2026-08-19T01:50:00-07:00, prior to this UAT pass being drafted). engine/src/workflow/runner.rs:513 now reads `let _ = sink.send_event_or_cancel(events::final_answer(response.clone()), cancel).await;` -- discarding the delivery error instead of early-returning -- so execution unconditionally falls through the checkpoint send (already a warn-and-continue per 7ea20f2) to `sink.send_terminal_event(event).await` at :527. Verified via git show 0c96720a and git blame on the line. No further code change needed; the described suppression defect does not exist at HEAD."

### 10. Decide the disposition of sequence-ordinal burning on failed delivery

expected: Either `wrap_next_event` and `send_checkpoint` allocate the ordinal lazily inside the successful-permit arm -- the idiom `send_terminal_event:168` already uses -- or ordinal gaps under failed delivery are accepted and documented as expected behaviour.
why_human: |
  Prior WR-09 was never fixed (5354d1e's commit message names only WR-10 and WR-12). At HEAD,
  runner.rs:71-79 (`wrap_next_event`) calls `self.sequence.next()` and builds the envelope
  *before* `send_envelope` is attempted (:141), and `send_checkpoint:179` allocates the ordinal
  before `try_send`. When delivery then fails, the ordinal is burned, producing a hole in the
  sequence that a debugging consumer of `workflow_checkpoints` cannot distinguish from a lost
  event. Note that both idioms now sit in the same file: `send_terminal_event:168` allocates
  lazily inside `if let Ok(permit)`, i.e. the correct pattern was applied in exactly one place.
  Verifier's re-derivation at HEAD: contiguity IS behaviourally proven on the paths that matter --
  `engine/src/tests/workflow_phase5.rs:507` asserts `event.sequence_ordinal == index + 1` across
  the whole happy-path event stream, and `gateway/main_test.go:3849`
  (TestWorkflowCheckpointPendingDrainAndPersistence, which ran against live Postgres this pass)
  asserts exactly 10 persisted rows with contiguous ordinals 1..10 in FIFO node order THROUGH the
  backpressure/pending path. The exposure is confined to the failed-delivery edge, which is
  untested. SC4 is not compromised; this is a debt-acceptance call about failure-path
  debuggability.
result: pass
resolution: "Split finding: wrap_next_event (client events, runner.rs:71-79) is ALREADY lazy -- the 0c96720a refactor (same commit that fixed Test 9) moved its call site inside send_event_lazy's Ok(permit) success arm at :128, matching the send_terminal_event:174 idiom. send_checkpoint (runner.rs:185) remains eager -- sequence.next() runs before the try_send/pending/OwnershipFailure branch is known, so a checkpoint lost to OwnershipFailure or Closed still burns its ordinal. User chose Option B for the remaining send_checkpoint gap: accepted as documented behaviour, confined to the failed-delivery edge (pending-queue exhaustion or an already-closing channel, which coincides with cancel.cancel() anyway); happy-path contiguity including the backpressure/pending-drain path remains proven by engine/src/tests/workflow_phase5.rs:507 and gateway/main_test.go:3849 (TestWorkflowCheckpointPendingDrainAndPersistence, verified against live Postgres this session). No code change to send_checkpoint."

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0
blocked: 0

recount_note: |
  Recomputed 2026-08-19T07:05:00Z after merging Tests 7-10 from the HEAD bb58a60
  re-verification. Tests 1-6 are unchanged: Test 1 remains the single `issue` (live run, now
  unblocked by e831be3 but still unperformed), Tests 2-6 remain `pass` with their original
  human-recorded resolutions verbatim. The 4 new items are design-debt / regression dispositions
  requiring a human decision -- none is a code gap against a success criterion, and the phase
  scored 5/5 on the ROADMAP success criteria with all four of these open.

## Gaps

- gap_id: G-05-1
  truth: "Engine starts cleanly and completes a live /rag/query with node_started/node_completed for all five nodes, one answer_chunk, one final_answer, one workflow_completed, no stream_error."
  status: resolved
  resolved_by: "05-25-PLAN.md, 05-26-PLAN.md, 05-27-PLAN.md (05-27 closed the models-body-limit root cause reported by this test; 05-25/05-26 closed the two earlier root causes recorded in the test's unblocked_by note)"
  resolved_at: 2026-08-19
  reason: "User reported: GenerateAnswer failed: model capabilities response exceeds maximum body limit of 262144 bytes; workflow_completed success: false"
  severity: blocker
  test: 1
  debug_session: ".planning/debug/g-05-1-models-metadata-body-limit.md"
  root_cause: |
    Live OpenRouter /api/v1/models response body exceeds MAX_PROVIDER_RESPONSE_BODY_BYTES (262,144 bytes / 256 KB) in engine/src/generation/openrouter.rs:387-401 via read_body_limited, causing GenerateAnswer capability check to fail on live runs.
  artifacts:
    - path: "engine/src/generation/openrouter.rs"
      issue: "model capability preflight uses read_body_limited with 256KB ceiling; OpenRouter full models list is larger than 256KB"
  missing:
    - "Increase body limit for models metadata endpoint or stream/filter OpenRouter models response"

