---
phase: 05-state-machine-workflow-events
plan: 08
subsystem: workflow
tags: [workflow, state-machine, production, query_rag, adapters]

# Dependency graph
requires:
  - phase: 05-state-machine-workflow-events (05-02)
    provides: Five-node state machine workflow runner and event streaming architecture
  - phase: 05-state-machine-workflow-events (05-04)
    provides: Node error taxonomy and timeout configuration
provides:
  - "Production build_production_workflow builder wiring real adapters (EmbeddingProvider, GraphQueryPort, DenseRetrievalPort, Bm25RetrievalPort, Reranker, Generator)"
  - "Production query_rag handler routing requests directly to runner.run_workflow(ctx, cancel, sink)"
  - "Typed graph_facts Vec<GraphFactBlock> population on WorkflowContext"
  - "Production workflow regression test suite in engine/src/tests/workflow_phase5_production.rs"
affects: [05-12, 05-22]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Concrete port adapter structs wrapping shared Arc services for workflow nodes"

key-files:
  created:
    - engine/src/tests/workflow_phase5_production.rs
  modified:
    - engine/src/main.rs
    - engine/src/workflow/mod.rs
    - engine/src/workflow/ports.rs
    - engine/src/workflow/nodes/graph_context.rs
    - engine/src/workflow/nodes/retrieve.rs
    - engine/src/tests.rs

key-decisions:
  - "Wired LancetServiceImpl::build_production_workflow to instantiate ProductionEmbeddingPort, ProductionGraphQueryPort, ProductionDenseRetrievalPort, ProductionBm25RetrievalPort, reranker, and generator adapters."
  - "Updated query_rag to construct runner and dependencies via build_production_workflow and execute via runner.run_workflow."
  - "Populated typed graph_facts vector on WorkflowContext from GraphQueryPort to enable structured prompt context formatting."

patterns-established:
  - "Production port adapters decouple gRPC service fields from node execution signatures while sharing underlying thread-safe database and index handles."

requirements-completed: [ORCH-01, ORCH-02, ORCH-03]

coverage:
  - id: D-06
    description: "Production five-node state machine workflow execution order (ReformulateQuery, ExtractGraphContext, RetrieveHybrid, AssemblePrompt, GenerateAnswer)"
    requirement: "ORCH-01"
    verification:
      - kind: automated
        ref: "cargo test --bin engine -- --nocapture workflow_phase5_production_five_node"
        status: pass
      - kind: automated
        ref: "cargo test --bin engine -- --nocapture workflow_phase5_production_dependencies_are_real"
        status: pass
      - kind: automated
        ref: "cargo test --bin engine -- --nocapture workflow_phase5_production_context_population"
        status: pass
---

# Plan 05-08 Summary: Production Five-Node State Machine Query Reachability

## Work Accomplished
1. **Production Port Adapters & Workflow Builder**:
   - Implemented `ProductionEmbeddingPort`, `ProductionGraphQueryPort`, `ProductionDenseRetrievalPort`, and `ProductionBm25RetrievalPort` in `engine/src/main.rs`.
   - Added `LancetServiceImpl::build_production_workflow(&self)` returning `(workflow::WorkflowRunner, workflow::WorkflowDependencies)` with all five nodes registered in D-06 order with timeouts: `ReformulateQuery` (5s), `ExtractGraphContext` (15s), `RetrieveHybrid` (10s), `AssemblePrompt` (2s), `GenerateAnswer` (65s).
   - Updated `query_rag` in `engine/src/main.rs` to call `build_production_workflow()` and dispatch via `runner.run_workflow(ctx, cancel, sink)`.

2. **Typed Context Population**:
   - Added `pub graph_facts: Vec<crate::prompt::GraphFactBlock>` to `WorkflowContext`.
   - Updated `GraphQueryPort::query_graph` to return `Vec<GraphFactBlock>` and implemented `IntoGraphFacts` conversion helpers.
   - Updated `ExtractGraphContextNode` to populate both `ctx.graph_facts` and `ctx.graph_context`.

3. **Testing & Verification**:
   - Created `engine/src/tests/workflow_phase5_production.rs` covering five-node execution, real dependency handle reuse without reinitialization, and typed context population.
   - Verified that all workflow unit tests and production tests pass cleanly.
