# Evaluation Fidelity and Graph Yield: Operational Note

> [!NOTE]
> This document is a concise technical note cited by Phase 6.4's evaluation methodology and results pages; it serves as a focused summary of evaluation harness fidelity rather than a comprehensive benchmark report.

## Summary of Findings

1. **What broke:** During the initial evaluation run on the MultiHop-RAG corpus, 96.6% of queries terminated prematurely and produced empty answers.
2. **Why it broke:** The production timeout thresholds assigned to individual workflow nodes were derived from unit tests and proved too narrow for multi-hop vector search and graph traversal across LanceDB.
3. **Why numbers looked healthy:** An unhandled stream truncation bug in the gateway caused aborted executions to be recorded as successful queries, while unpaired comparison metrics created a false appearance of high performance.
4. **What changed as a result:** Phase 06.3.1 established fail-closed stream error capture, typed failure notices (`RETRIEVAL_FAILED`), honest un-paired drop counters, and strictly paired ablation comparisons.
5. **Why the corrected run is believed:** Per-record stream truncation capture, typed failure notices, and strictly paired ablation comparisons are verified and active. The earlier claim that the pipeline prevented hidden failures at the run level was overstated: run-level completeness is now derived from an explicit cross-product comparison computed at drive termination and re-verified fail-closed before publication, rather than an unverified header flag. The 2026-09-09 run halted at 658 of 1,000 work units, remains incomplete, and is not a run of record.
