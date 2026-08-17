# Phase 5 Wave 10: Exhaustive Typed NodeKind Contract & Early Variant Admission Summary

## What Was Done
1. **Defined Closed `NodeKind` Enum**:
   - Added closed `NodeKind` enum to `engine/src/workflow/node.rs` with exactly five variants: `ReformulateQuery`, `ExtractGraphContext`, `RetrieveHybrid`, `AssemblePrompt`, `GenerateAnswer`.
   - Implemented `ALL` array, `name(&self)`, `checkpoint_label(&self)`, `fmt::Display`, and derived traits (`Debug`, `Clone`, `Copy`, `PartialEq`, `Eq`, `Hash`).
   - Updated `Node` trait to require `fn kind(&self) -> NodeKind;` with a default `fn name(&self) -> &'static str { self.kind().name() }`.
   - Re-exported `NodeKind` in `engine/src/workflow/mod.rs`.

2. **Implemented `Node::kind` for All Five Workflow Nodes**:
   - `ReformulateQueryNode::kind` returns `NodeKind::ReformulateQuery`.
   - `ExtractGraphContextNode::kind` returns `NodeKind::ExtractGraphContext`.
   - `RetrieveHybridNode::kind` returns `NodeKind::RetrieveHybrid`.
   - `AssemblePromptNode::kind` returns `NodeKind::AssemblePrompt`.
   - `GenerateAnswerNode::kind` returns `NodeKind::GenerateAnswer`.

3. **Early Nine-Variant Admission Rejection**:
   - Moved the maximum-variant admission check into `ReformulateQueryNode::run` before `NodeCompleted` and before any downstream adapter calls.
   - When variants exceed 8, `ReformulateQueryNode::run` immediately returns a typed `NodeError::new(NodeErrorKind::InputValidation, ...)` with `retryable: false`.
   - Behavioral verification confirms: 1 `NodeStarted(ReformulateQuery)`, 1 `NodeFailed(ReformulateQuery, InputValidation)`, 0 `NodeCompleted`, 0 `Checkpoint(post_reformulatequery)`, 0 downstream port calls, and 1 terminal failed `WorkflowCompleted`.

4. **Exhaustive Typed Runner Dispatch**:
   - Replaced stringly dispatch in `WorkflowRunner` with `timeout_for_kind(&self, kind: NodeKind)` and exhaustive matches.
   - Node timeout lookup, checkpoint label assignment, answer chunk emission, and zero-evidence skip (`AssemblePrompt` / `GenerateAnswer`) dispatch cleanly via `NodeKind`.
   - Forwarded `err.retryable` directly from `NodeError` into `events::node_failed` without inventing an extra retrying event.

5. **Regression & Acceptance Tests**:
   - Added `workflow_phase5_nodekind_tracer` verifying early variant rejection and zero downstream port invocations.
   - Added `workflow_phase5_nodekind_dispatch` verifying D-06 ordering, D-08 variant-zero embedding, D-07 all-variant BM25 retrieval, D-09 graph degradation, and typed retryability forwarding.
   - Added `workflow_phase5_nodekind_exhaustive` verifying the complete 5-variant closed enum, exhaustive timeouts and checkpoint labels, and D-03 zero-evidence skipping.

## Verification Results
- `cargo check --lib --manifest-path engine/Cargo.toml --locked`: Passed (0 errors)
- `cargo check --bin engine --manifest-path engine/Cargo.toml --locked`: Passed (0 errors)
- `cargo test --lib --manifest-path engine/Cargo.toml --locked`: Passed (87 passed, 0 failed)
- `cargo test --bin engine --manifest-path engine/Cargo.toml --locked --no-run`: Passed (0 errors)
- Task 1, 2, and 3 automated verification scripts: 100% Passed
