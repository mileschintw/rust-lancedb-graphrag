# API Coverage — OpenRouter

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

| capability | decision | reason |
|---|---|---|
| embeddings request | INTEGRATE | |
| bearer-token authentication | INTEGRATE | |
| configured embedding-model selection | INTEGRATE | |
| 2048-dimension response validation | INTEGRATE | |
| batching and bounded concurrency | INTEGRATE | |
| timeout, retry, and rate-limit handling | INTEGRATE | |
| live embedding E2E verification | INTEGRATE | |
| model catalog discovery | OPT-OUT | D-18 locks the phase to `nvidia/llama-nemotron-embed-vl-1b-v2:free`; dynamic selection is outside the phase boundary. |
| chat completions and answer generation | OPT-OUT | Phase 3 owns RAG answer generation; Phase 2 only integrates embeddings. |
| image/audio generation | OPT-OUT | The ingestion phase handles lightweight text-like sources and has no media-generation requirement. |
