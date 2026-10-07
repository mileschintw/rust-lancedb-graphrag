# Lancet: next steps after Phase 06.3.4.1 (analyst plan, 2026-10-06)

**Status of this file:** decision record for the user's 2026-10-06 request ("give me a plan to push this project further; promote the backlog items that add the most value the quickest"). It inserts two evaluation phases before Phase 6.4 and triages the `999.x` backlog. Phase 6.4 stays parked until the two new phases publish.

## 1. Where the project stands

Phase 06.3.4.1 closed `all-pass-close` on the run of record `eval/runs/2026-10-06-drive2-multihop_rag_diag/` (see `06.3.4.1-RUN-OF-RECORD.md`). What that run proves, and what it does not:

| Established | Not established |
|---|---|
| The measurement system is trustworthy: pre-committed gates, complete journal, spend reconciled to the provider bill, verifier re-derived every gate from source | That the graph helps. Every paired answer-quality delta is within its CI of zero; `ranking_quality` is significantly negative (-0.08, CI excludes 0) |
| The graph path is mechanically alive: path found on 66% of answerable questions, zero `GRAPH_TIMEOUT`, retrieved-set composition changes on 54% of pairs | Any standard-RAG baseline. The contract has one ablation flag (`disable_graph_context`). Dense-only, BM25-only and hybrid have never been compared |
| Hybrid retrieval is fast and flat: p50 116 ms, p95 166 ms, slope -0.02 ms/query | Judged dimensions. Faithfulness and groundedness are `skipped`; human calibration was never performed (06.3.4 SC-3 still deferred) |
| The 2026-09-03 collapse is fully explained (90% of queries clipped at the retrieval timeout; ablation over arms sharing 1.6% of questions) | Chunking strategy comparison (DATA-02): no measurement exists |
| | A sample larger than 100 questions on the repaired system. CIs are about +/-10 points |

The graph-off baseline itself is weak and uneven: `answer_usable` 0.58 overall, with inference 0.90, comparison 0.58, binary-gold 0.43 and temporal 0.13. On 26 questions the gold chunk was in the vector top 4 and the answer was still unusable, so a large share of the loss is in prompting and generation, not retrieval. The corpus carries `published_at` on every document and ingestion does not use it.

**Verdict:** procedurally sufficient to close; not sufficient for the data-driven story the project exists to tell. Phase 6.4 writes docs after the implementation they document, so the evaluation work has to land first or the docs get rewritten.

## 2. The plan: two bounded phases, then close

### Phase 06.3.5: Retrieval ablation matrix, paper-convention metrics, judged pass and calibration

Answers "how much do vector, BM25, hybrid and graph each contribute" on the same questions, with the paper's own retrieval convention beside Lancet's, and finally runs the judged pass with a human-calibrated slice. No new corpus. No engine quality change: the system under test is the drive-2 system, so results are comparable to the run of record.

Key design points:

- A `retrieval_mode` on the request (dense-only / BM25-only / hybrid), orthogonal to `disable_graph_context`. The harness arm registry maps an arm label to request flags; four arms: `dense-only`, `bm25-only`, `hybrid`, `hybrid+graph`.
- MultiHop-RAG's own Hits@k and MRR@10 (document-level evidence match) as additive, labelled figures, so Lancet can be placed on the paper's retrieval table.
- A dev / held-out split committed before any paid drive. The 100 diagnostic questions become the dev set. A fresh seeded held-out sample is drawn from the remaining 400 of the 500-question sample, gold-in-index verified by the D-61 coverage table. Nothing is tuned after a held-out reading.
- Judged pass (faithfulness, groundedness) on the held-out sample, cached; a human calibration slice of at least 20 items scored by the user; kappa and rho reported with the 06.3.4 machinery.
- One published run of record; a four-arm comparison table with paired deltas and bootstrap CIs against `hybrid` as the reference arm; one eval-results chart artifact for the README.

Estimated cost: drive 2 cost about $0.07 for 200 records, so four arms on 200 held-out questions is roughly $0.30 plus the judge pass. Budget cap authorised per stage as before.

### Phase 06.3.6: Quality levers measured as arms

Each candidate improvement is a switchable arm measured once on the held-out split against the 06.3.5 reference, so attribution is clean and a lever that does not pay is recorded, not shipped.

Levers, in priority order:

1. **Reranker (promotes backlog 999.2).** The `Reranker` port with `NoOpReranker` exists (RAG-04). Cross-encoder over the fused top-N to top-k. Most likely single gain for standard-RAG metrics; a standard interview topic (precision at k versus recall).
2. **Graph repair chosen by diagnosis (promotes a lite version of backlog 999.6).** First, a per-question table over the 38 drive-2 `GRAPH_UNAVAILABLE` questions: are the gold documents' entities present, is the missing link an alias split (two nodes for one entity) or a missing edge. That table selects one of two repairs before code is written: entity resolution behind the existing `EntityResolver` port (DATA-09), or restricting the graph RRF list to chunks cited by at least two path entities / the edge-evidence chunk (attacks the ranking regression). **More hops is explicitly not a lever:** paths are already seed-to-seed one-hop and two-hop with a degree cap, MultiHop-RAG questions are mostly two-document questions, and the ranking regression says the graph already injects noise.
3. **Temporal metadata.** Carry `published_at` through ingestion into chunk metadata and the prompt's evidence headers. Targets the 0.13 temporal stratum.
4. **Answer-format prompting for binary gold.** A yes/no format instruction for comparison questions. Targets the 0.43 binary stratum and the 26 "gold in top 4, answer unusable" cases.

Arms for the drive: `hybrid` (reference, re-run same day for provider control), `hybrid+rerank`, `hybrid+graph-v2`, `hybrid+temporal`, `hybrid+answer-format`, `hybrid+all`. Levers whose paired delta CI excludes zero in the positive direction become defaults; the rest stay off and are recorded in the 6.4 limitations section.

### Phase 6.4: unpark after 06.3.6 publishes

Unchanged in scope. Its evaluation-methodology and results pages cite the 06.3.5 matrix and the 06.3.6 lever table beside the 06.3.4.1 run of record. The honest-limitations section gains: chunking comparison unmeasured (DATA-02), community-level questions unmeasured (no GraphRAG-Bench drive), provider not a controlled variable until a local endpoint exists.

## 3. Backlog triage

Criteria: value to the data-driven story and to interviews, divided by time to land. Ports that already exist count as a head start.

| Backlog | Decision | Why |
|---|---|---|
| 999.2 Reranking | **Promote into 06.3.6 (lever 1)** | Port exists; likely largest standard-RAG gain; cheap behind an API or a local ONNX cross-encoder |
| 999.6 Entity resolution / node merging | **Promote a lite version into 06.3.6 (lever 2, conditional on the no-path diagnosis)** | `EntityResolver` port exists; 38% of questions find seeds but no path, which is the signature of alias splits or missing edges |
| 999.3 Query reformulation (HyDE, multi-query) | Hold for v1.1 as a 06.3.5-style arm | `reformulate` node and multi-variant fusion exist; cheap once the arm registry lands, but every drive-2 record shows `reformulation_used=false` and the baseline loss is elsewhere |
| 999.11 Local SGLang / OpenAI-compatible endpoint | Hold for v1.1, high priority | Removes the "provider is not a controlled variable" disclosure and makes runs reproducible; mostly a base-URL and auth abstraction; needs local GPU |
| 999.8 S3-compatible LanceDB storage | Hold for v1.1 | Good cloud-native talking point; LanceDB supports object stores natively; conflicts with the v1 local-first constraint |
| 999.1 Community summaries, 999.5 compile-time node semantics, 999.4 ingestion synthesis | Defer to v2 | Large effort; MultiHop-RAG has no global or summary questions, so the benchmark cannot reward it. Would need a GraphRAG-Bench drive first |
| 999.7 Rayon CPU isolation | Defer | No user-visible or measurable effect on the current bottlenecks |
| 999.9 LLM wiki, 999.10 session memory in LanceDB, 999.12 PageIndex | Defer to v2 | Product features outside the v1 story; PageIndex is interesting for interviews but is a third retrieval paradigm, not a quick win |

## 4. What this buys for the resume and interviews

- Four-arm chart: dense-only versus BM25-only versus hybrid versus hybrid+graph, with CIs, on a public benchmark, placed against the paper's retrieval table.
- A lever table showing which standard improvements paid and which did not, each with its latency and token cost.
- The existing story stays the strongest: a split Go/Rust system whose first benchmark lied, caught by its own harness, root-caused, re-measured under pre-registered gates, and published honestly including a negative graph result with a diagnosis and a tested fix.

## 5. Sequence and ownership

1. 06.3.5 (this document inserts it into ROADMAP.md; discuss-phase then plan-phase next).
2. 06.3.6 (depends on 06.3.5's held-out split and reference arm).
3. 6.4 unpark decision by the user after 06.3.6 publishes.
4. v1.1 candidates: 999.11, 999.3, 999.8.
