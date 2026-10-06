# Superseded Run Notice: 2026-09-09-multihop_rag

> [!WARNING]
> This evaluation run is **SUPERSEDED** and retained strictly as primary forensic evidence.
> It is a halted partial run, not a run of record. Its EM, Token-F1 and graph-presence figures are **NON-COMPARABLE** with the Phase 06.3.4.1 run of record.

**Run of record:** [`eval/runs/2026-10-06-drive2-multihop_rag_diag/`](../2026-10-06-drive2-multihop_rag_diag/) (readings and decision in [`06.3.4.1-RUN-OF-RECORD.md`](../../../.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/06.3.4.1-RUN-OF-RECORD.md)).

This directory has no `report.md` or `report.json`: the run is a halted partial, and only `journal.jsonl`, `raw_events/`, `STAGED-GATE.md` and `STAGED-GATE.json` exist. Nothing here was published as a report.

## Why This Run Is Superseded

1. **Halted and incomplete.** The drive stopped at 658 of 1,000 work units and its journal header carries `partial: true`. It never reached a complete journal, so it cannot be cited as a result.
2. **Index identity drift (OI-03).** The run was driven against the pre-reconcile store at index generation `lance-701`. Phase 06.3.4.1 reconciled the store and advanced it to **`lance-702`** (4 LanceDB documents, 634 nodes, 630 edges and 1,040 entity edges removed; see `06.3.4.1-STORE-BASELINE.md` section 3). The run of record's journal, `report.json` and preflight all carry `lance-702`.
3. **Prompt change (D-71).** The production prompt now asks for a final `Answer: <short answer>` line after the full cited answer, so EM and Token-F1 are no longer scored on the same output shape.
4. **Seeding redesign (D-75, D-76).** Graph seeding is now per-mention entity matching with seed-to-seed paths (at most 2 hops) and a chunk boost, replacing the single nearest-entity seed on the whole-question embedding. Graph presence is measured on a different mechanism.
5. **Re-derived budgets.** The per-node timeout budgets were re-derived from pass A and pass B measurements (`06.3.4.1-BUDGETS.md`), so the failure and degradation behaviour of every node differs.

## Forensic References

- [06.3.4-FINDINGS.md](../../../.planning/phases/06.3.4-corrected-re-drive-calibration-and-root-cause-documentation/06.3.4-FINDINGS.md): the halted drive's findings, including the 14/143 graph-presence reading.
- [06.3.4.1-RUN-OF-RECORD.md](../../../.planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair/06.3.4.1-RUN-OF-RECORD.md): the run that supersedes it, with its gate readings and disclosures.
