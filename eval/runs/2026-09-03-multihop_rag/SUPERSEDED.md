# Superseded Run Notice: 2026-09-03-multihop_rag

> [!WARNING]
> This evaluation run is **SUPERSEDED** and retained strictly as primary forensic evidence.
> The published metrics in `report.md` and `report.json` are **NON-COMPARABLE** with subsequent runs.

## Why This Run Is Superseded

1. **False-Green Success Reporting**: 966 of the 1,000 queries in `journal.jsonl` produced empty answer strings (`answer: ""`) due to early node timeouts in `RetrieveHybrid` and `AssemblePrompt`. Because stream aborts were not classified as errors, all 1,000 records were falsely marked with `outcome: "success"`.
2. **Unpaired Ablation Delta**: The graph ablation delta was computed across global averages of two nearly empty pools rather than strictly paired question IDs.
3. **Forensic Reference**: The comprehensive investigation detailing the failure mechanisms and corrections is documented in [06.3.1-ROOT-CAUSE.md](file:///d:/Repos/lancet/.planning/phases/06.3.1-fix-retrieval-citation-collapse-and-graph-ablation-measureme/06.3.1-ROOT-CAUSE.md).
