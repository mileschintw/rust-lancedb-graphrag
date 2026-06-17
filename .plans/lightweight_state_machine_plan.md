# Lightweight State Machine Plan

This document records the tentative plan for the lightweight Rust state machine that will orchestrate Lancet's RAG pipeline.

The intent is **not** to rebuild LangGraph, Dify, or a general-purpose agent framework. The goal is to implement a small, typed, observable, retryable workflow layer for Lancet's fixed RAG path.

## Design Position

Lancet should study graph-workflow systems such as LangGraph and workflow products such as Dify for useful concepts, but should only implement the subset needed for this project.

A good framing for the project is:

> Lancet uses a lightweight Rust state machine inspired by graph-workflow systems such as LangGraph and workflow products such as Dify, but implements only the fixed RAG orchestration path needed for hybrid retrieval, GraphRAG context extraction, prompt assembly, and streaming generation.

This supports the project's main story:

- custom RAG data-plane engineering
- explicit orchestration boundaries
- production-like tracing and fallback behavior
- no dependence on a black-box orchestration framework
- no attempt to rebuild a full workflow engine

## Fixed Workflow

The first version should use a fixed pipeline:

```text
ReceiveQuery
  -> ReformulateQuery
  -> RetrieveHybrid
  -> ExtractGraphContext
  -> AssemblePrompt
  -> GenerateAnswer
  -> Complete
  -> Failed
```

The state machine should coordinate these steps. Individual nodes should own their domain logic.

## Core Features

### 1. Explicit Workflow States

Use a simple enum-like state model:

```text
ReceiveQuery
ReformulateQuery
RetrieveHybrid
ExtractGraphContext
AssemblePrompt
GenerateAnswer
Complete
Failed
```

This keeps the orchestration layer auditable and avoids an ad-hoc chain of `if/else` logic.

### 2. Typed Workflow Context

Carry a single context object through the workflow.

Example fields:

```text
session_id
trace_id
original_query
reformulated_query
vector_results
bm25_results
graph_context
assembled_prompt
answer
metadata
```

This makes the pipeline debuggable, testable, and observable.

### 3. Node Abstraction

Each workflow step should be implemented as a node.

Example nodes:

```text
ReformulateQueryNode
HybridRetrievalNode
GraphExtractionNode
PromptAssemblyNode
AnswerGenerationNode
```

The state machine should decide what runs next. Nodes should execute their own logic.

### 4. Transition Table

Use an explicit transition model rather than hardcoded nested control flow.

Initial transition plan:

```text
ReceiveQuery -> ReformulateQuery
ReformulateQuery -> RetrieveHybrid
RetrieveHybrid -> ExtractGraphContext
ExtractGraphContext -> AssemblePrompt
AssemblePrompt -> GenerateAnswer
GenerateAnswer -> Complete
Any -> Failed
```

Later, conditional transitions can be added without turning the system into a full graph engine.

### 5. Async Execution

The workflow runner should be async because the main steps are asynchronous:

- LLM calls
- vector retrieval
- BM25 retrieval
- graph queries
- streaming generation

### 6. Event Streaming

The state machine should emit workflow events so the API can stream progress to clients.

Example events:

```text
NodeStarted
NodeCompleted
NodeFailed
AnswerChunk
FinalAnswer
WorkflowCompleted
```

Example client-facing progress:

```text
Reformulating query...
Retrieved vector chunks...
Retrieved BM25 chunks...
Extracted graph context...
Generating answer...
```

### 7. Per-Node Tracing

Each node should create its own trace span.

Recommended spans:

```text
query_reformulation
hybrid_retrieval
graph_context_extraction
prompt_assembly
llm_generation
```

This is one of the main reasons to build a lightweight state machine ourselves: it gives clear visibility into latency and failure points.

### 8. Retry and Fallback Behavior

Not every failure should be fatal.

Recommended policy:

```text
Max retries: 1 or 2
Backoff: small exponential backoff
Timeout: per-node timeout
```

Example fallback:

```text
GraphRAG extraction fails
  -> continue with vector + BM25 context
  -> mark graph step as skipped/degraded
```

### 9. Timeout and Cancellation

Each node should have a timeout.

Example timeouts:

```text
ReformulateQuery: 5s
HybridRetrieval: 10s
GraphExtraction: 15s
PromptAssembly: 2s
LLMGeneration: 30s
```

Cancellation should be supported by `session_id` or `trace_id`, especially when a client closes the stream.

### 10. Error Classification

Use typed errors instead of generic strings.

Example categories:

```text
InputValidation
RetrievalFailed
GraphQueryFailed
PromptAssemblyFailed
LlmGenerationFailed
Timeout
Cancelled
Internal
```

Each error should indicate whether it is retryable, fatal, or eligible for fallback.

## Useful Supporting Features

### Workflow Metadata

Track metadata that helps with debugging and evaluation:

```text
started_at
completed_at
reformulation_used
vector_count
bm25_count
graph_node_count
graph_edge_count
llm_model
prompt_tokens
completion_tokens
degraded_mode
```

### Degraded Mode

The system should try to return a useful result even when one component fails.

Examples:

```text
GraphRAG unavailable:
  use vector + BM25 only

Retriever partially failed:
  use whatever results are available

LLM failed:
  return structured error or cached fallback
```

### Retrieval Quality Guard

Before answering, check whether enough evidence was retrieved.

Example behavior:

```text
If retrieved context is too weak:
  reformulate query again
  or return "not enough context"
```

This can start as a simple heuristic.

### Prompt Assembly Boundary

Prompt assembly should be separate from answer generation.

```text
Retrieve context
  -> Assemble prompt
  -> Generate answer
```

This makes it easier to test:

- prompt templates
- context formatting
- citation formatting
- system/user message construction

### Citation and Evidence Packaging

The answer should include references, not just text.

Example structure:

```text
Answer
  text
  citations[]
    chunk_id
    source
    score
```

### Token Budget Control

Before calling the LLM, enforce or estimate token limits.

If context is too large:

```text
truncate lower-scored chunks
keep graph context
keep top vector/BM25 chunks
```

This is especially important for GraphRAG because graph context can grow quickly.

### Lightweight Checkpointing

For the first version, checkpoints can be simple snapshots saved after each node.

Example checkpoint fields:

```text
trace_id
state
context
created_at
```

Possible storage options:

```text
memory for development
PostgreSQL for production-like behavior
JSON snapshot for debugging/tests
```

This gives useful observability without building a full LangGraph-style persistence system.

## Nice-to-Have Later

These features are useful but should not be part of the initial MVP.

### Conditional Transitions

Example:

```text
RetrieveHybrid
  -> ExtractGraphContext if enough evidence exists
  -> AssemblePrompt if graph extraction is disabled
```

### Answer Quality Gate

After generation, optionally evaluate:

```text
answer length
citation count
whether citations exist
whether the answer includes uncertainty when appropriate
whether retrieved context supports the answer
```

Start with heuristics. LLM-as-a-judge can come later.

### Config-Driven Pipeline

A small workflow config may be useful later:

```yaml
workflow:
  enable_query_reformulation: true
  enable_graph_context: true
  enable_bm25: true
  max_retries: 2
  llm_model: claude-sonnet-4-6
```

Do not overbuild this early.

### Tool Abstraction

If later features require web search, SQL lookup, or external APIs, define a generic tool interface.

Do not build a full dynamic tool planner in the first version.

### Circuit Breaker

A production-like circuit breaker can be added later.

Example:

```text
If LLM fails 5 times in 10 minutes:
  stop calling it temporarily
  return degraded response
```

## Features to Avoid

The lightweight state machine should avoid becoming a full framework.

Do not build these in the first version:

```text
arbitrary graph builder
visual workflow editor
full workflow DSL
dynamic node loading
full multi-agent framework
complex human-in-the-loop system
full checkpoint database
distributed workflow execution
plugin marketplace
generic tool planner
full LangGraph clone
```

These features would pull the project away from its main purpose.

## Recommended MVP Scope

The first version should implement:

```text
1. Receive query
2. Reformulate query
3. Run hybrid retrieval
4. Try GraphRAG context extraction
5. Assemble prompt
6. Stream LLM answer
7. Emit workflow events
8. Record tracing metadata
9. Handle retry/fallback
10. Save lightweight checkpoint
```

## Suggested Architecture

```text
API Gateway
  |
  v
Rust Engine
  |
  v
WorkflowRunner
  |
  +--> ReformulateQueryNode
  +--> HybridRetrievalNode
  +--> GraphContextNode
  +--> PromptAssemblyNode
  +--> AnswerGenerationNode
  |
  v
Event Stream + Trace Metadata
```

The state machine should not know the details of LanceDB, BM25, graph traversal, or LLM calls. It should only coordinate the steps.

## Legal and Attribution Note

Referencing public docs, architecture, and concepts from LangGraph or Dify is fine.

Copying code is different. If code is ever copied directly, the current license of each project must be checked and required notices must be preserved. The safer engineering rule is:

> Borrow ideas, do not port code unless the license clearly allows it and attribution requirements are satisfied.
