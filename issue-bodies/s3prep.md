Owner decision 2026-11-01 (coordinator session): "Start S3 prep", answering the coordinator's proposal to finish S3's Claude spend before the Claude credit expires on 2026-11-03. Owner goal, relayed from a side session: "照目前進度我看不出來沒辦法在這批credit過期前做完S3的理由？". A new credit grant arrives after.

## Why

S3's reader is fixed to deepseek by S2 (PR #142), so S3's only Claude spend is **writer extraction** of the 2Wiki passages (PLAN.md › S3 details; D-234). Extraction reads passages only, never questions, so it uses no held-out read. Store builds, graph ingestion, deepseek runs, scoring and S3's analysis pre-registration can all follow on later credit.

## Ask

Free preparation, then one paid extraction gate.

1. **Dataset:**
   - Fetch the 2WikiMultiHopQA subset from `osunlp/HippoRAG_2`: 1,000 questions and 6,119 passages.
   - Record the exact dataset revision.
   - Confirm the license from the dataset's original source (PLAN.md › S3 details, open item 1).
   - Raw data stays out of git unless the license and size allow committing it, as MultiHop-RAG's corpus does.
2. **D-243 split:** fix the dev/held-out split of the 1,000 questions with a committed seed and record its SHA-256. Read no held-out question content beyond what is needed to build the split.
3. **Writer pre-registration**, frozen per D-73 before any spend. It covers only what the extraction fixes:
   - writers: deepseek, Haiku 5.5, Sonnet 5.5, plus Opus 5.5 only if the owner adds it after #117;
   - thinking per the owner ruling of 2026-11-01: deepseek off, Haiku off, Sonnet effort low, Opus effort low, all on the Batch API, with each setting and its measured reasoning_tokens reported;
   - the engine's extraction prompt and schema version;
   - passages ingested as given;
   - the dataset revision.
   S3's analysis pre-registration (arms, K, Holm family, metrics) comes later, before any reading.
4. **Extraction:** run each Claude writer over all 6,119 passages through the Batch API. Reuse #117's script, which is merged first. Store raw outputs and usage per passage; build no store yet. Print an estimate based on #117's measured per-chunk tokens, and spend nothing before the owner's yes. Submit every batch by the morning of 2026-11-02. deepseek's extraction (OpenRouter) can run later.

Budget: D-246 caps S3 at $110 of Claude credit. Expected: Haiku under $1 and Sonnet about $7-14, refined by #117's measurements.

## Files

- New: `eval/corpora/twowiki*.toml` and `eval/corpora/twowiki/` (split file, attribution)
- `eval/src/lancet_eval/thresholds.py` › a new writer pre-registration constant (one D-73 freeze commit)
- #117's extraction script: extended for 2Wiki passages (after #117 merges)
- New: `experiments/v1.1/RUN-S3-EXTRACT.md` (run guide and spend record)
- Tests for the corpus config, the split and the pre-registration
