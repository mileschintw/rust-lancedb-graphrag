# Phase 5 Wave 9: Generation Preflight Separation & Single-Flight Cache Summary

## What Was Done
1. **Separated OpenRouter Preflight from Generation Calls**:
   - Capabilities preflight (`/models`) is decoupled from runtime generation execution (`/chat/completions`).
   - `execute_one_call` no longer issues preflight requests inline during attempt execution.
   - Dedicated preflight timeout (`DEFAULT_PREFLIGHT_TIMEOUT` = 5s, configurable via `with_preflight_timeout`) ensures rapid capability discovery without blocking on generation timeout budgets.
   - Capability errors are strictly classified: network timeouts / resets / 5xx map to retryable `GenerationErrorKind::ProviderError`, while 4xx / unsupported capabilities / schema errors map to non-retryable `GenerationErrorKind::SupportedParameters`.

2. **Single-Flight Cache for Capabilities**:
   - Implemented composite cache keyed by `(models_endpoint, model)` using `Arc<tokio::sync::Mutex<HashMap<CapabilityKey, Arc<tokio::sync::OnceCell<ModelCapabilities>>>>>`.
   - Thread-safe deduplication guarantees exactly one in-flight `/models` request among concurrent preparation callers.
   - Successful discovery responses are cached permanently; failures, cancellations, and resets are not cached, allowing subsequent retries to attempt fresh discovery.

3. **Cancellation Token Propagation & Cooperative Prompt Packing**:
   - `GenerationRequest` now carries `pub cancel: Option<tokio_util::sync::CancellationToken>` (skipped during serde, excluded from value equality).
   - Cancellation tokens are propagated from `GenerateAnswerNode` down through prompt assembly and HTTP request send futures via `tokio::select!`.
   - Verified no spurious `CancellationToken::new()` constructions exist in `openrouter.rs`.

4. **Transient Retry & Honest Failure Contract**:
   - `NodeError` now includes `pub retryable: bool` and builder `with_retryable(bool)`.
   - `GenerateAnswerNode` records a request snapshot, attempts generation, and upon encountering transient errors (`Timeout` or transient `ProviderError`), retries once with the byte-identical request snapshot.
   - If retries are exhausted or non-retryable errors occur, honest failure is returned with `retryable: false` without fabricating responses or events.

5. **Test Fixtures & Acceptance Hardening**:
   - 11 models-first test fixtures in `engine/src/generation/tests.rs` upgraded to use `accept_with_deadline` across all 24 total socket accepts.
   - Added unit tests for preflight transport retryability, success-only capability caching, single-flight concurrent deduplication, and pre-request cancellation.
   - Added production workflow tests in `engine/src/tests/workflow_phase5_production.rs` verifying byte-identical retry tracing, cancellation propagation, and retry exhaustion behavior.

## Verification Results
- `cargo check --lib --manifest-path engine/Cargo.toml --locked`: Passed
- `cargo check --bin engine --manifest-path engine/Cargo.toml --locked`: Passed
- `cargo test --lib --manifest-path engine/Cargo.toml --locked`: 87 passed; 0 failed
- `cargo test --bin engine --manifest-path engine/Cargo.toml --locked -- workflow_phase5`: 18 passed; 0 failed
- Models-first fixture count: 11 fixtures, 24 socket accepts, 100% bounded with `accept_with_deadline`
