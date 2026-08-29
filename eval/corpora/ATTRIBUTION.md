# Dataset Attribution and Licensing Notices

## MultiHop-RAG

- **Authors:** Yixuan Tang and Yi Yang (2024)
- **Dataset:** *MultiHop-RAG: Benchmarking Retrieval-Augmented Generation for Multi-Hop Queries*
- **Source:** [https://huggingface.co/datasets/yixuantt/MultiHopRAG](https://huggingface.co/datasets/yixuantt/MultiHopRAG)
- **License:** [Open Data Commons Attribution License (ODC-BY 1.0)](https://opendatacommons.org/licenses/by/1-0/)

### Licensing & Subset Rationale
The ODC-BY 1.0 license applies to the MultiHop-RAG database, query set, and evidence structure. To respect intellectual property boundaries regarding the third-party news article texts aggregated in `corpus.json`, the Lancet evaluation repository commits only a minimal, reproducible subset (`eval/corpora/multihop_rag/documents.subset.jsonl` and `questions.sample.jsonl`) required to evaluate the sampled 500 questions, plus a documented distractor draw (`subset_selection.json`). Full raw dataset files are downloaded locally to `.cache/` by `lancet-eval corpus fetch` and are never committed.

---

## GraphRAG-Bench

- **Repository:** [https://github.com/GraphRAG-Bench/GraphRAG-Bench](https://github.com/GraphRAG-Bench/GraphRAG-Bench)
- **Code License:** MIT License
- **Dataset License:** Unspecified

### Licensing & Fixture Rationale
Because the GraphRAG-Bench dataset card does not specify an explicit dataset license, no raw or sampled article texts from the original dataset are committed to this repository. The file `eval/corpora/graphrag_bench/questions.sample.jsonl` contains only hand-authored synthetic schema fixtures (`fixture_only = true`) used to test and verify corpus-agnostic loader support offline without network calls.
