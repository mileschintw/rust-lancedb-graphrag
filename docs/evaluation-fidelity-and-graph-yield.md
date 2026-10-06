# Evaluation Fidelity and Graph Yield: Operational Note

> [!NOTE]
> This document is a concise technical note cited by Phase 6.4's evaluation methodology and results pages; it serves as a focused summary of evaluation harness fidelity rather than a comprehensive benchmark report.

## Summary of Findings

1. **What broke:** During the initial evaluation run on the MultiHop-RAG corpus, 96.6% of queries terminated prematurely and produced empty answers.
2. **Why it broke:** The production timeout thresholds assigned to individual workflow nodes were derived from unit tests and proved too narrow for multi-hop vector search and graph traversal across LanceDB.
3. **Why numbers looked healthy:** An unhandled stream truncation bug in the gateway caused aborted executions to be recorded as successful queries, while unpaired comparison metrics created a false appearance of high performance.
4. **What changed as a result:** Phase 06.3.1 established fail-closed stream error capture, typed failure notices (`RETRIEVAL_FAILED`), honest un-paired drop counters, and strictly paired ablation comparisons.
5. **Why the corrected run is believed:** Per-record stream truncation capture, typed failure notices, and strictly paired ablation comparisons are verified and active. The earlier claim that the pipeline prevented hidden failures at the run level was overstated: run-level completeness is now derived from an explicit cross-product comparison computed at drive termination and re-verified fail-closed before publication, rather than an unverified header flag. The 2026-09-09 run halted at 658 of 1,000 work units, remains incomplete, and is not a run of record.

## Addendum 2026-10-06: Phase 06.3.4.1 run of record

Phase 06.3.4.1 (retrieval diagnosis, index identity and graph-yield repair) changed the system under measurement and then produced the run that replaces the halted 2026-09-09 drive. This addendum records what changed, which older numbers may no longer be compared, and what the run of record measured, including the results that are not flattering.

### What changed

1. **Index generation after the reconcile.** The store was reconciled to the corpus and its index generation moved from `lance-701` to **`lance-702`**. The reconcile removed 4 documents, 634 nodes, 630 edges and 1,040 entity edges. Every earlier run (2026-09-03 and 2026-09-09) was driven against `lance-701`; the run of record is `lance-702` throughout.
2. **Prompt line (D-71).** The production prompt now ends the full cited answer with one final `Answer: <short answer>` line, and the structured output also carries that short answer. Evaluation and production use the same prompt. Answers are scored on the extracted final-answer line as well as on the legacy full-text metrics.
3. **Seeding and chunk boost (D-75, D-76).** Graph seeding no longer takes the single entity nearest to the whole-question embedding. It extracts entity mentions from the question, matches each against entity names (exact or alias first, then per-mention name-vector search), and finds paths of at most 2 hops that connect the seeds. Only path facts are injected into the prompt (capped at 8), hub expansion is degree-capped, and the source chunks of entities on those paths are boosted into the retrieved set so the graph can change retrieval composition. This is the production default; there is no flag and graph-off remains the ablation arm.
4. **Re-derived budgets.** The node timeout budgets were re-derived from two measurement passes: reformulate 5000 ms, query embedding 2000 ms, retrieve 2500 ms, graph operation 2424 ms, graph node 12500 ms, prompt assembly 120 ms and generation 65000 ms. The graph-operation budget is derived from the measured graph-step latency of pass B (a proxy: the `ExtractGraphContext` node duration) rather than from unit-test timings.

### Non-comparability

**EM, Token-F1 and graph-presence figures from the 2026-09-03 run and the 2026-09-09 halted run must not be compared with the run of record.** The index generation, the prompt, the graph seeding and the node budgets all differ, and the answer shape the metrics read has changed. In particular, the 06.3.4 graph-presence reading of 14 of 143 pairs (0.0979) and the run of record's presence reading below use the same presence definition on different systems; they are not a before-and-after measurement of one change. Legacy EM and Token-F1 are still reported by the harness but are not the headline metrics for the run of record. `eval/runs/2026-09-09-multihop_rag/` carries a `SUPERSEDED.md` notice to this effect.

### Run of record

- **Run:** `eval/runs/2026-10-06-drive2-multihop_rag_diag/` (index generation `lance-702`, header `partial` false). Readings and the decision record: `.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/06.3.4.1-RUN-OF-RECORD.md`.
- **Sample:** a 100-question diagnostic selection (seed 42) driven in both arms, graph-on and graph-off, for 200 records: 90 answerable questions and 10 null questions. This is a diagnostic sample, not a full-corpus run.
- **SC-1 (completeness): pass.** 200 of 200 work units journaled, 0 missing.
- **SC-4 (graph presence): pass.** 59 of 89 answerable pairs (0.6629, Wilson 95% interval [0.5598, 0.7526]) against a floor of 0.20.
- **SC-5 (retrieval composition): pass.** 35 of 65 pairs (0.5385, Wilson 95% interval [0.4185, 0.6541]) in which graph-on retrieved at least one graph-provenance chunk that graph-off did not, against a floor of 0.10.
- **Decision (D-83), 2026-10-06:** the user chose `all-pass-close`. No gate was missed, nothing was iterated, and no floor was amended. Phase 6.4 stays parked; unparking it is a separate later decision.

### Disclosures that stand with the result

1. **The paired quality deltas are negative but not significant, and the graph has a cost.** Graph-on minus graph-off over the 65 pairs: coverage@4 -0.0141 [-0.0577, 0.0295], answer usability -0.0308 [-0.0923, 0.0308], final-answer EM -0.0154 [-0.0769, 0.0308]; every interval includes 0. The legacy ranking-quality delta over 89 pairs is -0.0807 with interval [-0.1362, -0.0259], which excludes 0. The graph path adds about 1.2 to 1.6 s of latency (+1596 ms [935, 2261] over the 65 pairs; +1221 ms over the 89) and about 210 prompt tokens per query. The run shows that the graph now reaches and changes retrieval; it does not show that the graph improves answers. Whether it earns its cost is a Phase 6.4 question, and the negative direction is reported rather than hidden.
2. **The provider changed mid-drive.** From request ordinal 165 the served provider switched from OpenInference to Sail Research (one served model, `deepseek/deepseek-v4-flash-0731`, throughout). Graph-off usable answers were 46 of 74 on OpenInference and 6 of 16 on Sail Research. The provider is not a controlled variable in this run.
3. **The graph-off retrieved set differs from the earlier drive on 4 of 100 questions.** The differences are at ranks 6 to 8 only, and the cause is undetermined: two earlier drives with the same retrieval code already differed on 7 of 100 questions, but retrieval files also changed between the two, so a small code effect cannot be separated from run-to-run variation.

### Artifacts

- `eval/runs/2026-10-06-drive2-multihop_rag_diag/` (journal, `report.md`, `report.json`, `gates-drive2.md`)
- `.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/06.3.4.1-RUN-OF-RECORD.md`
- `.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/06.3.4.1-STORE-BASELINE.md` (index generation)
- `.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/06.3.4.1-BUDGETS.md` (budgets and spend)
- `.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/06.3.4.1-SEED-PROBE.md` (seeding)
