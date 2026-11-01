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

---

## Lancet quickstart sample

- **Files:** `eval/corpora/quickstart/` (five Markdown documents, `documents.json` and `canary.arms.jsonl`)
- **Author:** the Lancet project
- **License:** the repository's own [MIT License](../../LICENSE)

### Provenance
The quickstart sample is project-authored fiction (06.4 D-221). Every person, company, place and event in it is invented, and it contains no third-party text, no MultiHop-RAG article text and no text from any other dataset. It is bundled so that a reader can ingest a small, licence-clean corpus with document metadata and ask a question that needs three of the five documents. The MultiHop-RAG article texts are not used here because their redistribution terms are unclear.

---

## 2WikiMultiHopQA (HippoRAG 2 subset)

- **Authors:** Xanh Ho, Anh-Khoa Duong Nguyen, Saku Sugawara and Akiko Aizawa (2020)
- **Dataset:** *Constructing A Multi-hop QA Dataset for Comprehensive Evaluation of Reasoning Steps* (COLING 2020)
- **Original source:** [https://github.com/Alab-NII/2wikimultihop](https://github.com/Alab-NII/2wikimultihop), licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) (the repository's `LICENSE` file, read 2026-11-01)
- **Packaging used:** [https://huggingface.co/datasets/osunlp/HippoRAG_2](https://huggingface.co/datasets/osunlp/HippoRAG_2) at revision `5ec05b38deecc3318bb432c69865959c56058990` (`2wikimultihopqa.json`, 1,000 questions; `2wikimultihopqa_corpus.json`, 6,119 passages), from the HippoRAG 2 authors (Bernal Jiménez Gutiérrez et al., 2025). The dataset card states no licence of its own; the HippoRAG code repository is MIT.

### Licensing & Fixture Rationale
The passages are paragraphs of English Wikipedia, whose text is licensed CC BY-SA ([Wikipedia:Copyrights](https://en.wikipedia.org/wiki/Wikipedia:Copyrights)). `python -m lancet_eval.twowiki fetch` downloads both source files into the gitignored `eval/corpora/twowiki/.cache/` and refuses any file whose sha256 differs from the pinned bytes; neither file is committed. `eval/corpora/twowiki/split.json`, the D-243 dev / held-out split, holds question IDs and no question content. No question text is committed. The passage text is committed in one place, the S3 writer extraction under `experiments/v1.1/s3-extract/` (owner, 2026-11-01): `chunks.jsonl` holds every passage as `title` and text, and each `<writer>.results.jsonl` (deepseek's also in `deepseek.shard<i>.results.jsonl`) holds a model's extraction from those passages. Both stay under Wikipedia's CC BY-SA terms, with the attribution above.
