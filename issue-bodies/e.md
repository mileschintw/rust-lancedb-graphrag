Owner decision 2026-11-01 (coordinator session): "全部接受" (item E of the coordinator's package). Budget pre-approved within reason: "只要是在合理範圍我們的credit可支付的情況下都直接同意".

## Why

S1 found the graph hurts on MultiHop-RAG (graph on small: -8.9 pt). #126 found junk month and publisher entities in deepseek's extraction. This asks whether the graph's loss there comes from the writer.

## Ask

A dev-only writer grid on MultiHop-RAG, on S1's document subset and small store (structure-aware 500/50). It is exploratory: it decides nothing.

1. **Extraction (tonight; Claude spend before the credit expires on 2026-11-03):**
   - writers: deepseek, Haiku 5.5, Sonnet 5.5 and Opus 5.5, using the engine's extraction prompt and schema;
   - thinking per the owner's ruling: deepseek off, Haiku off, Sonnet effort low, Opus effort low, Claude on the Batch API;
   - reuse #117's script;
   - store raw outputs and usage per chunk.
2. **Graph per writer:** load each writer's extraction into its own graph side tables, as graph-v2 did; entity names re-embedded with Voyage. If the engine has no import path for external extractions, build the smallest one; Rust changes are allowed.
3. **Reading:** for each writer, the `small/hybrid+graph+rerank+metadata` arm against `small/hybrid+rerank+metadata`, with deepseek as reader on S1's dev questions:
   - K=2;
   - `answer_usable`, split by yes/no vs open questions;
   - #126's junk-entity counts per writer.
4. Pre-register the reading (D-73 freeze) before it runs.

Ceiling: Claude $40, OpenRouter $1.50.

## Files

- New: `eval/corpora/multihop_rag_s3m_dev.toml`, and a pre-registration constant in `thresholds.py` (one D-73 freeze)
- #117's extraction script (reuse)
- An engine or eval import path for external extractions, if missing
- New: `experiments/v1.1/EXPLORE-S3-MHR-WRITERS.md`
