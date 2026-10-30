# LlamaIndex baseline

The MultiHop-RAG paper's LlamaIndex pipeline as an external arm for v1.1 S0 (D-248). It indexes the 346 documents
Lancet seeds, retrieves for each question, and writes a context export plus a pipeline-config echo. It never calls a
reader: the engine's generate-only bin answers over the export, as it does for every arm (D-247), and
`lancet-eval run-external` (#14) drives that step and journals the result.

This is its own uv project so LlamaIndex's dependencies never enter the harness. It depends on `../../eval` by path
and checks its rows with the harness's own `validate_row` and `read_export`; it has no copy of the contract.

## Configuration

| Value | Setting |
|---|---|
| Framework | `llama-index-core` 0.14.25, pinned |
| Splitter | `SentenceSplitter(chunk_size=256, chunk_overlap=25)`, LlamaIndex's default tokenizer |
| Index | in-memory `VectorStoreIndex` |
| Dense retrieval | top 20 |
| Embeddings | `voyageai/voyage-4-large` through `https://openrouter.ai/api/v1/embeddings`, `dimensions = 2048` |
| Rerank | `voyageai/rerank-2.5-lite` through `https://openrouter.ai/api/v1/rerank`, keep 8 |
| Embedded metadata | `title`, `source`, `published_at`, raw values from the corpus row |

- **Documents.** `documents.subset.jsonl` and `document_map.json` from the corpus's `map_corpus` directory, the files
  `lancet-eval seed` reads and writes. Each article's ID is its Lancet document ID, looked up by the corpus ID the
  seeder records (the title). An article with no map entry fails the run.
- **Metadata.** LlamaIndex embeds the three metadata keys with the text by default, as in the paper. In the export the
  node text holds only the chunk text, and the metadata is the entry's `document_metadata`, normalised by
  `lancet_eval.evidence_meta.normalise` exactly as Lancet ingests it. The packer then shows it to the reader in the
  same DocMeta tags as Lancet's metadata lever.
- **Rerank.** A custom `VoyageRerankPostprocessor` sends Lancet's rerank body (`model`, `query`, `documents`,
  `top_n` = candidate count, `provider.allow_fallbacks = false`) and refuses a reply the engine would refuse: another
  model, or indices missing, repeated or out of range. It sends each node's chunk text only, with no metadata
  header, as Lancet sends its chunk text (fairness rule 5; owner's ruling 2026-10-29). LlamaIndex's own rerank
  postprocessors would send the metadata header too.
- **k = 8.** A question whose reranked list is not exactly 8 entries fails the run (fairness rule 3).
- **Chunk IDs** are `<document ID>#<chunk index>`, so a rebuild gives the same IDs and the same `index_fingerprint`.

## Embedding `input_type` (fairness rule 7)

Voyage's own API takes `input_type` (`query` or `document`) and prepends a different prompt for each. The question is
whether the two arms' embeddings could differ because one sends it and the other cannot.

- **What Lancet sends.** No `input_type`, for documents or queries. `engine/src/client/mod.rs` sends
  `{model, input, dimensions: 2048}` and nothing else.
- **What this project sends.** The same three fields, and no `input_type`. `tests/test_providers.py` pins the body.
- **Whether OpenRouter forwards it.** Not documented. OpenRouter's embeddings documentation lists `model`, `input`
  and `provider` and does not mention `input_type` (checked 2026-10-29). Whether it would forward the field is
  therefore unknown, and it does not matter for this comparison: neither arm sends it, so both get Voyage's no-prompt
  embedding for queries and documents alike.

The live check below was **not run**: it makes paid OpenRouter calls and needs the owner's yes. It embeds one text
with and without `input_type: "query"`; identical vectors mean OpenRouter drops the field.

```bash
uv run --project baselines/llamaindex python -c "import httpx,os; k=os.environ['OPENROUTER_API_KEY']; f=lambda **x: httpx.post('https://openrouter.ai/api/v1/embeddings', headers={'Authorization':'Bearer '+k}, json={'model':'voyageai/voyage-4-large','input':['Who won the match?'],'dimensions':2048,**x}, timeout=30).json()['data'][0]['embedding']; a,b=f(),f(input_type='query'); print('forwarded' if a!=b else 'dropped or ignored', max(abs(x-y) for x,y in zip(a,b)))"
```

## Running it

```bash
uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag --arm <pre-registered arm label> --out <dir>
```

It writes `<dir>/context_export.jsonl` (one row per question, arm `--arm`, 8 ranked entries, no graph facts) and
`<dir>/pipeline_config.json` (every value above, the installed framework version, document and chunk counts, and the
index fingerprint). Nothing is written unless every row passes the harness validator.

A live run is a paid run: it embeds every chunk of the 346 documents and every question, and reranks every question.
It needs `OPENROUTER_API_KEY`, and the stage's D-246 spend cap applies. The questions come from the corpus config, so
`--corpus multihop_rag_heldout` (or any held-out corpus) is a held-out read under D-237.

`--questions`, `--documents` and `--document-map` override the corpus files, for a fixture run.

## Tests

```bash
uv run --project baselines/llamaindex pytest
```

Offline, with no API key: a three-document fixture corpus with a stubbed embedding and reranker (seam S-E), and the
OpenRouter clients against `httpx.MockTransport`. One test also loads the real 346-document map.
