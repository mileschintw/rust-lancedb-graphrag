//! Layer-4 vector-diagnosis probe (06.3.4.1-09 Task 1, D-59/D-63): read-only checks against the
//! reconciled eval store to answer "is the gold chunk in the index, and does plain vector
//! retrieval find it?" without touching graph architecture (ROADMAP constraint 4).
//!
//! Three independent modes, selected by mutually exclusive flags:
//!
//! - `--vector-top-k K --questions PATH [--stage-cap USD] [--cache PATH] [--estimate-only]`:
//!   embeds each question (batches of 32, cached by `(question_id, embedding_model)` in a JSONL
//!   file so re-runs are free) and runs a dense-only top-K search through the exact
//!   `ProductionDenseRetrievalPort` production uses, at the engine's startup `nodes_version`
//!   (column (c), RESEARCH §E/§F). `--estimate-only` never opens the store, never reads
//!   `OPENROUTER_API_KEY`, and never calls the embedding provider: it only tokenizes the question
//!   text (via the same `cl100k_base_singleton()` the production prompt path already reuses,
//!   `prompt.rs`) to project embedding spend at $0.12/M (RESEARCH §L, `measure.py`'s
//!   `EMBEDDING_PRICE_PER_1M`). The real path meters spend the same way — the OpenRouter
//!   embeddings response carries no `usage` field, so spend here is always the estimated case,
//!   never provider-reported — and stops dispatching further batches (not just reporting) once a
//!   batch would exceed `--stage-cap` (D-86).
//! - `--rechunk-check DOC_IDS.json`: for each listed document, reads `documents.raw_content`,
//!   re-chunks it with the exact same production chunker (`engine::ingest::chunk_ingestion_job`)
//!   and the eval corpus's known ingest-time settings (structure-aware, size 500, overlap 50 —
//!   `gateway/main.go`'s upload defaults, confirmed unmodified by `eval/src/lancet_eval/seed.py`,
//!   which sends no `chunk_size`/`chunk_overlap` override), and compares the result to the stored
//!   `nodes.content` ordered by `chunk_index`. `DOC_IDS.json` carries two lists: `candidates`
//!   (the absent/split-fact documents under diagnosis) and `controls` (documents whose evidence
//!   items are already known-`in_chunk`) — the controls exist so a non-identical control result
//!   surfaces a rechunk-config or raw-byte mismatch *before* a candidate's `identical: false` is
//!   misread as "re-ingestion would reproduce the gap" (it would instead mean the check itself is
//!   miscalibrated). It is read-only: no `add`/`delete`/`optimize` call anywhere in this bin.
//! - `--graph-seeds --questions PATH --stage-cap USD [--degree-cap N] [--mention-cache PATH]`
//!   (06.3.4.1-13, OI-01 probe, D-75..D-79): runs the exact library functions that production
//!   graph retrieval will call (`engine::graph::seeding::{extract_mentions, match_seeds}` and
//!   `engine::graph::paths::find_seed_paths`) over each question's original text, against the
//!   reconciled eval store, and prints one JSON line per question (mentions, seeds with their
//!   match kind and source documents, paths with their cl100k token cost, candidate chunk IDs and
//!   the degree-capped count) followed by a summary line that carries spend. The store is opened
//!   with `DatabaseManager::open_and_validate` before `GraphIndex::build` touches any table
//!   accessor, because the accessors create an empty table when one is missing. The only paid call
//!   is one batched mention-embedding request per question for the mentions that no entity name
//!   matched; embeddings are cached by `(mention, embedding_model)` in a separate JSONL file, spend
//!   is estimated per request exactly as the vector mode does (the provider reports no usage), and
//!   dispatch stops before a request that would exceed `--stage-cap` (D-86). It never writes the
//!   store, and the path-fact cap is left unbounded here so every found path is reported.
//!
//! Every mode refuses to run against a store path that does not look like the eval store
//! (`lancedb-eval`), because a missing `LANCET_ENV=eval` would otherwise silently point this bin
//! at the dev store and misreport `index_generation`. Opens the store via
//! `DatabaseManager::open_and_validate` (never `::initialize`, which creates tables — a write).
//! No `#[cfg(test)]` module here, so `scripts/engine-test-targets.sh`'s enumerated bin-test
//! targets are unaffected by this new bin (mirrors `retrieval_soak.rs`, which the same script
//! also does not enumerate).

use std::collections::{HashMap, HashSet};
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use arrow_array::{Array, BinaryArray, Int32Array, RecordBatch, StringArray};
use futures::future::BoxFuture;
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use lancedb::Table;
use serde::{Deserialize, Serialize};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use engine::config::{load_settings, EffectiveRagSettings};
use engine::client::{OpenRouterClient, OpenRouterEmbeddingConfig};
use engine::db::DatabaseManager;
use engine::graph::escape_sql_literal;
use engine::graph::context_strategy::{ContextAssemblyStrategy, GraphFact};
use engine::graph::index::GraphIndex;
use engine::graph::paths::{find_seed_paths, seed_chunk_candidates, PathSettings, DEGREE_CAP};
use engine::graph::seeding::{
    extract_mentions, match_seeds, LanceMentionVectorSearch, Seed, SeedSettings,
};
use engine::ingest::{
    chunk_ingestion_job, EmbeddingProvider, IngestionJob, DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE,
};
use engine::pb::lancet::v1;
use engine::service::ProductionDenseRetrievalPort;
use engine::workflow::ports::{corpus_generation_from_nodes_version, DenseRetrievalPort};

const USAGE: &str = "\
usage: diag_probe --vector-top-k K --questions QUESTIONS.jsonl [--stage-cap USD] [--cache PATH] [--estimate-only]
   or: diag_probe --rechunk-check DOC_IDS.json
   or: diag_probe --graph-seeds --questions QUESTIONS.jsonl --stage-cap USD [--degree-cap N] [--mention-cache PATH]

  --vector-top-k     dense-only top-K at the pinned startup nodes_version (RESEARCH §E/§F, column c).
  --questions        JSONL, one question per line, each carrying question_id and query|question.
  --stage-cap        USD ceiling checked before each 32-question embedding batch is dispatched
                      (D-86); required unless --estimate-only.
  --cache            embedding cache JSONL keyed by (question_id, embedding_model); default
                      data/probe-cache/question_embeddings.jsonl (gitignored).
  --estimate-only     print the projected embedding spend and exit; opens no store, calls no
                      provider, reads no OPENROUTER_API_KEY.
  --rechunk-check    read-only production-chunker replay for the documents named in DOC_IDS.json
                      (a JSON object with `candidates` and `controls` string arrays).
  --graph-seeds      OI-01 offline seed/path probe (06.3.4.1-13): mention seeds, seed-to-seed
                      paths and candidate chunks per question; requires --questions and --stage-cap.
  --degree-cap       largest degree a two-hop intermediate may have (default: the committed
                      DEGREE_CAP of engine::graph::paths).
  --mention-cache    mention embedding cache JSONL keyed by (mention, embedding_model); default
                      data/probe-cache/mention_embeddings.jsonl (gitignored).";

const EMBEDDING_PRICE_PER_1M: f64 = 0.12; // RESEARCH §L / measure.py EMBEDDING_PRICE_PER_1M.
const EMBED_BATCH_SIZE: usize = 32;
const EXPECTED_EMBEDDING_DIM: usize = 2048;
const DEFAULT_CACHE_PATH: &str = "data/probe-cache/question_embeddings.jsonl";
const DEFAULT_MENTION_CACHE_PATH: &str = "data/probe-cache/mention_embeddings.jsonl";

#[derive(Debug, Clone, PartialEq)]
enum Mode {
    VectorTopK {
        k: usize,
        questions: PathBuf,
        stage_cap: Option<f64>,
        cache: PathBuf,
        estimate_only: bool,
    },
    RechunkCheck {
        doc_ids_path: PathBuf,
    },
    GraphSeeds {
        questions: PathBuf,
        stage_cap: f64,
        degree_cap: u32,
        mention_cache: PathBuf,
    },
}

fn parse_args<I: IntoIterator<Item = String>>(args: I) -> Result<Mode, String> {
    let mut vector_top_k: Option<usize> = None;
    let mut questions: Option<PathBuf> = None;
    let mut stage_cap: Option<f64> = None;
    let mut cache: Option<PathBuf> = None;
    let mut estimate_only = false;
    let mut rechunk_check: Option<PathBuf> = None;
    let mut graph_seeds = false;
    let mut degree_cap: Option<u32> = None;
    let mut mention_cache: Option<PathBuf> = None;

    let mut iter = args.into_iter();
    while let Some(flag) = iter.next() {
        match flag.as_str() {
            "--vector-top-k" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--vector-top-k requires a value\n{USAGE}"))?;
                let parsed: usize = value
                    .parse()
                    .map_err(|_| format!("--vector-top-k must be a positive integer\n{USAGE}"))?;
                if parsed == 0 {
                    return Err(format!("--vector-top-k must be greater than 0\n{USAGE}"));
                }
                vector_top_k = Some(parsed);
            }
            "--questions" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--questions requires a value\n{USAGE}"))?;
                questions = Some(PathBuf::from(value));
            }
            "--stage-cap" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--stage-cap requires a value\n{USAGE}"))?;
                let parsed: f64 = value
                    .parse()
                    .map_err(|_| format!("--stage-cap must be a non-negative number\n{USAGE}"))?;
                if !parsed.is_finite() || parsed < 0.0 {
                    return Err(format!(
                        "--stage-cap must be a non-negative finite number\n{USAGE}"
                    ));
                }
                stage_cap = Some(parsed);
            }
            "--cache" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--cache requires a value\n{USAGE}"))?;
                cache = Some(PathBuf::from(value));
            }
            "--estimate-only" => estimate_only = true,
            "--graph-seeds" => graph_seeds = true,
            "--degree-cap" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--degree-cap requires a value\n{USAGE}"))?;
                let parsed: u32 = value
                    .parse()
                    .map_err(|_| format!("--degree-cap must be a positive integer\n{USAGE}"))?;
                if parsed == 0 {
                    return Err(format!("--degree-cap must be greater than 0\n{USAGE}"));
                }
                degree_cap = Some(parsed);
            }
            "--mention-cache" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--mention-cache requires a value\n{USAGE}"))?;
                mention_cache = Some(PathBuf::from(value));
            }
            "--rechunk-check" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--rechunk-check requires a value\n{USAGE}"))?;
                rechunk_check = Some(PathBuf::from(value));
            }
            other => return Err(format!("unrecognized flag '{other}'\n{USAGE}")),
        }
    }

    let selected = usize::from(vector_top_k.is_some())
        + usize::from(rechunk_check.is_some())
        + usize::from(graph_seeds);
    if selected > 1 {
        return Err(format!(
            "--vector-top-k, --rechunk-check and --graph-seeds are mutually exclusive\n{USAGE}"
        ));
    }
    if graph_seeds {
        let questions =
            questions.ok_or_else(|| format!("--graph-seeds requires --questions\n{USAGE}"))?;
        let stage_cap =
            stage_cap.ok_or_else(|| format!("--graph-seeds requires --stage-cap\n{USAGE}"))?;
        if estimate_only {
            return Err(format!(
                "--estimate-only is not supported with --graph-seeds\n{USAGE}"
            ));
        }
        return Ok(Mode::GraphSeeds {
            questions,
            stage_cap,
            degree_cap: degree_cap.unwrap_or(DEGREE_CAP),
            mention_cache: mention_cache
                .unwrap_or_else(|| PathBuf::from(DEFAULT_MENTION_CACHE_PATH)),
        });
    }
    match (vector_top_k, rechunk_check) {
        (Some(_), Some(_)) => unreachable!("mutual exclusion is checked above"),
        (None, None) => Err(format!(
            "one of --vector-top-k, --rechunk-check or --graph-seeds is required\n{USAGE}"
        )),
        (None, Some(doc_ids_path)) => Ok(Mode::RechunkCheck { doc_ids_path }),
        (Some(k), None) => {
            let questions = questions
                .ok_or_else(|| format!("--vector-top-k requires --questions\n{USAGE}"))?;
            if !estimate_only && stage_cap.is_none() {
                return Err(format!(
                    "--vector-top-k requires --stage-cap unless --estimate-only is set\n{USAGE}"
                ));
            }
            let cache = cache.unwrap_or_else(|| PathBuf::from(DEFAULT_CACHE_PATH));
            Ok(Mode::VectorTopK {
                k,
                questions,
                stage_cap,
                cache,
                estimate_only,
            })
        }
    }
}

/// Refuses to operate against a store path that does not look like the eval store, so a missing
/// `LANCET_ENV=eval` fails loudly instead of silently diagnosing (and mis-labelling the
/// `index_generation` of) the dev store.
fn ensure_eval_store(lancedb_path: &str) -> Result<(), String> {
    let normalized = lancedb_path.replace('\\', "/");
    if !normalized.contains("lancedb-eval") {
        return Err(format!(
            "refusing to run diag_probe against '{lancedb_path}': this bin diagnoses the eval \
             store only. Set LANCET_ENV=eval before running.\n{USAGE}"
        ));
    }
    Ok(())
}

/// Estimates token count for embedding-spend projection using the same `cl100k_base_singleton()`
/// tokenizer the production prompt-packing path already reuses (`prompt.rs`), avoiding a second
/// tokenizer allocation per call.
fn estimate_tokens_cl100k(text: &str) -> u64 {
    tiktoken_rs::cl100k_base_singleton().encode_ordinary(text).len() as u64
}

/// Reads a questions JSONL file into `(question_id, query_text)` pairs, in file order.
///
/// Accepts either `query` (the corpus's on-disk field name, e.g.
/// `questions.sample.jsonl`) or `question` per line, so this bin works against either field name
/// without assuming which one a given fixture uses.
fn load_questions(path: &Path) -> Result<Vec<(String, String)>, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|error| format!("failed to read questions file {}: {error}", path.display()))?;
    let mut out = Vec::new();
    for (line_number, line) in content.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let value: serde_json::Value = serde_json::from_str(line).map_err(|error| {
            format!(
                "failed to parse questions file {} at line {}: {error}",
                path.display(),
                line_number + 1
            )
        })?;
        let question_id = value
            .get("question_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| {
                format!(
                    "questions file {} line {} missing question_id",
                    path.display(),
                    line_number + 1
                )
            })?
            .to_string();
        let text = value
            .get("query")
            .and_then(|v| v.as_str())
            .or_else(|| value.get("question").and_then(|v| v.as_str()))
            .ok_or_else(|| {
                format!(
                    "questions file {} line {} missing query/question text",
                    path.display(),
                    line_number + 1
                )
            })?
            .to_string();
        out.push((question_id, text));
    }
    Ok(out)
}

#[derive(Serialize, Deserialize, Clone)]
struct CacheEntry {
    question_id: String,
    embedding_model: String,
    embedding: Vec<f32>,
}

/// Loads the embedding cache JSONL (if present) into `(question_id, embedding_model) -> vector`.
///
/// A missing cache file is not an error — the cache starts empty on the first run.
fn load_cache(cache_path: &Path) -> Result<HashMap<(String, String), Vec<f32>>, String> {
    let mut map = HashMap::new();
    if !cache_path.exists() {
        return Ok(map);
    }
    let content = std::fs::read_to_string(cache_path)
        .map_err(|error| format!("failed to read cache {}: {error}", cache_path.display()))?;
    for (line_number, line) in content.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let entry: CacheEntry = serde_json::from_str(line).map_err(|error| {
            format!(
                "failed to parse cache {} at line {}: {error}",
                cache_path.display(),
                line_number + 1
            )
        })?;
        map.insert(
            (entry.question_id.clone(), entry.embedding_model.clone()),
            entry.embedding,
        );
    }
    Ok(map)
}

/// Loads just the set of `question_id`s already cached for `embedding_model`, for the
/// `--estimate-only` uncached-projection breakdown. Best-effort: any read/parse failure yields an
/// empty set rather than blocking a pure cost estimate.
fn load_cached_question_ids(cache_path: &Path, embedding_model: &str) -> HashSet<String> {
    let Ok(map) = load_cache(cache_path) else {
        return HashSet::new();
    };
    map.into_keys()
        .filter(|(_, model)| model == embedding_model)
        .map(|(question_id, _)| question_id)
        .collect()
}

/// Appends newly-fetched cache entries to `cache_path`, creating its parent directory if needed.
fn append_cache<T: Serialize>(cache_path: &Path, entries: &[T]) -> Result<(), String> {
    if let Some(parent) = cache_path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).map_err(|error| {
                format!("failed to create cache directory {}: {error}", parent.display())
            })?;
        }
    }
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(cache_path)
        .map_err(|error| format!("failed to open cache {} for append: {error}", cache_path.display()))?;
    for entry in entries {
        let line = serde_json::to_string(entry).map_err(|error| error.to_string())?;
        writeln!(file, "{line}")
            .map_err(|error| format!("failed to write cache {}: {error}", cache_path.display()))?;
    }
    Ok(())
}

#[derive(Serialize)]
struct EstimateReport {
    estimate_only: bool,
    vector_top_k: usize,
    questions: usize,
    already_cached: usize,
    embedding_model: String,
    tokenizer: &'static str,
    price_per_million_usd: f64,
    total_tokens_estimated: u64,
    total_spend_usd_estimate: f64,
    uncached_tokens_estimated: u64,
    uncached_spend_usd_estimate: f64,
}

/// `--estimate-only`: projects embedding spend without opening the store, reading
/// `OPENROUTER_API_KEY`, or calling the embedding provider (RESEARCH §L, D-86 stage-cap gate).
async fn run_estimate_only(
    k: usize,
    questions_path: &Path,
    cache_path: &Path,
) -> Result<(), String> {
    let questions = load_questions(questions_path)?;

    // Reading settings only to report the configured embedding model id is safe here: it opens
    // no store and requires no API key. Falls back to "unknown" if config loading itself fails,
    // so a cost projection never depends on a fully-valid deployment config being present.
    let embedding_model = load_settings()
        .ok()
        .and_then(|settings| EffectiveRagSettings::try_from_settings(&settings).ok())
        .map(|effective| effective.embedding_model)
        .unwrap_or_else(|| "unknown".to_string());

    let cached_ids = load_cached_question_ids(cache_path, &embedding_model);

    let mut total_tokens: u64 = 0;
    let mut uncached_tokens: u64 = 0;
    let mut already_cached = 0usize;
    for (question_id, text) in &questions {
        let tokens = estimate_tokens_cl100k(text);
        total_tokens += tokens;
        if cached_ids.contains(question_id) {
            already_cached += 1;
        } else {
            uncached_tokens += tokens;
        }
    }

    let total_spend = (total_tokens as f64 / 1_000_000.0) * EMBEDDING_PRICE_PER_1M;
    let uncached_spend = (uncached_tokens as f64 / 1_000_000.0) * EMBEDDING_PRICE_PER_1M;

    let report = EstimateReport {
        estimate_only: true,
        vector_top_k: k,
        questions: questions.len(),
        already_cached,
        embedding_model,
        tokenizer: "cl100k_base",
        price_per_million_usd: EMBEDDING_PRICE_PER_1M,
        total_tokens_estimated: total_tokens,
        total_spend_usd_estimate: total_spend,
        uncached_tokens_estimated: uncached_tokens,
        uncached_spend_usd_estimate: uncached_spend,
    };
    println!(
        "{}",
        serde_json::to_string(&report).map_err(|error| error.to_string())?
    );
    Ok(())
}

#[derive(Serialize)]
struct VectorTopKRecord {
    question_id: String,
    chunk_ids: Vec<String>,
    scores: Vec<f64>,
    index_generation: String,
    embedding_model: String,
}

#[derive(Serialize)]
struct VectorTopKSummary {
    spend_usd: f64,
    questions: usize,
    cached: usize,
    stopped_by_cap: bool,
}

/// Full (paid) `--vector-top-k` run: embeds cache misses in batches of 32, stopping dispatch
/// before a batch would exceed `stage_cap` (D-86), then runs a dense-only top-K through the exact
/// `ProductionDenseRetrievalPort` production uses, at the engine's startup `nodes_version`.
async fn run_vector_top_k(
    k: usize,
    questions_path: &Path,
    stage_cap: f64,
    cache_path: &Path,
) -> Result<(), String> {
    let settings = load_settings().map_err(|error| format!("failed to load settings: {error}"))?;
    let lancedb_path = settings.engine.lancedb_path.clone();
    ensure_eval_store(&lancedb_path)?;
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings)
        .map_err(|error| format!("invalid RAG configuration: {error}"))?;

    let api_key = std::env::var("OPENROUTER_API_KEY")
        .map_err(|_| "OPENROUTER_API_KEY environment variable is not set".to_string())?;
    if api_key.trim().is_empty() {
        return Err("OPENROUTER_API_KEY environment variable must not be empty or blank".to_string());
    }

    let database = DatabaseManager::open_and_validate(&lancedb_path)
        .await
        .map_err(|error| format!("failed to open LanceDB read-only: {error}"))?;
    let nodes = database
        .nodes_table()
        .await
        .map_err(|error| format!("failed to open nodes table: {error}"))?;
    let nodes_version = nodes
        .version()
        .await
        .map_err(|error| format!("failed to read nodes version: {error}"))?;
    let generation = corpus_generation_from_nodes_version(nodes_version);
    tracing::info!(
        lancedb_path = %lancedb_path,
        index_generation = %generation,
        embedding_model = %effective_settings.embedding_model,
        "diag_probe vector-top-k starting"
    );

    // The production `RetrievalSettings` (candidate_limit/final_limit) are left exactly as
    // configured — shrinking `candidate_limit` to `k` would change what the ANN index searches,
    // not just how many results are kept, so this is not a faithful "production top-k" probe.
    // The result is truncated to `k` after retrieval instead.
    let dense_port = ProductionDenseRetrievalPort {
        database: database.clone(),
        nodes_version,
        retrieval_settings: effective_settings.retrieval.clone(),
    };

    let embedding_config = OpenRouterEmbeddingConfig::new_with_concurrency(
        effective_settings.embedding_model.clone(),
        effective_settings.embedding_endpoint.clone(),
        effective_settings.embedding_concurrency,
    )
    .map_err(|error| format!("invalid embedding config: {error}"))?;
    let embedder = OpenRouterClient::new_with_config(api_key, embedding_config)
        .map_err(|error| format!("failed to build embedding client: {error}"))?;

    let questions = load_questions(questions_path)?;
    let mut cache = load_cache(cache_path)?;

    let model = effective_settings.embedding_model.clone();
    let mut cached_count = 0usize;
    let mut misses: Vec<usize> = Vec::new();
    for (index, (question_id, _text)) in questions.iter().enumerate() {
        if cache.contains_key(&(question_id.clone(), model.clone())) {
            cached_count += 1;
        } else {
            misses.push(index);
        }
    }

    let mut spend_usd: f64 = 0.0;
    let mut stopped_by_cap = false;

    for batch in misses.chunks(EMBED_BATCH_SIZE) {
        let batch_tokens: u64 = batch
            .iter()
            .map(|&index| estimate_tokens_cl100k(&questions[index].1))
            .sum();
        let batch_cost = (batch_tokens as f64 / 1_000_000.0) * EMBEDDING_PRICE_PER_1M;
        if spend_usd + batch_cost > stage_cap {
            stopped_by_cap = true;
            break;
        }

        let texts: Vec<String> = batch.iter().map(|&index| questions[index].1.clone()).collect();
        let embeddings = embedder
            .get_embeddings(&texts)
            .await
            .map_err(|error| format!("embedding request failed: {error}"))?;
        if embeddings.len() != batch.len() {
            return Err(format!(
                "embedding provider returned {} vectors for {} inputs",
                embeddings.len(),
                batch.len()
            ));
        }

        let mut new_entries = Vec::with_capacity(batch.len());
        for (&index, embedding) in batch.iter().zip(embeddings.into_iter()) {
            if embedding.len() != EXPECTED_EMBEDDING_DIM || embedding.iter().any(|value| !value.is_finite()) {
                return Err(format!(
                    "embedding provider returned an invalid payload for question {}",
                    questions[index].0
                ));
            }
            let question_id = questions[index].0.clone();
            cache.insert((question_id.clone(), model.clone()), embedding.clone());
            new_entries.push(CacheEntry {
                question_id,
                embedding_model: model.clone(),
                embedding,
            });
        }
        append_cache(cache_path, &new_entries)?;
        spend_usd += batch_cost;
    }

    let cancel = CancellationToken::new();
    let mut processed = 0usize;
    for (question_id, text) in &questions {
        let Some(embedding) = cache.get(&(question_id.clone(), model.clone())) else {
            // Cache miss beyond a cap stop: not embedded this run, so it cannot be retrieved.
            continue;
        };
        let candidates = dense_port
            .retrieve_dense(text, embedding.as_slice(), None::<&v1::DocumentFilter>, &cancel)
            .await
            .map_err(|error| format!("dense retrieval failed for question {question_id}: {error}"))?;
        let top_k: Vec<_> = candidates.into_iter().take(k).collect();
        let record = VectorTopKRecord {
            question_id: question_id.clone(),
            chunk_ids: top_k.iter().map(|candidate| candidate.chunk_id.clone()).collect(),
            scores: top_k.iter().map(|candidate| candidate.score).collect(),
            index_generation: generation.clone(),
            embedding_model: model.clone(),
        };
        println!(
            "{}",
            serde_json::to_string(&record).map_err(|error| error.to_string())?
        );
        processed += 1;
    }

    let summary = VectorTopKSummary {
        spend_usd,
        questions: processed,
        cached: cached_count,
        stopped_by_cap,
    };
    println!(
        "{}",
        serde_json::to_string(&summary).map_err(|error| error.to_string())?
    );
    Ok(())
}

/// One cached mention embedding, keyed by `(mention, embedding_model)`.
#[derive(Serialize, Deserialize, Clone)]
struct MentionCacheEntry {
    mention: String,
    embedding_model: String,
    embedding: Vec<f32>,
}

/// Loads the mention embedding cache JSONL (if present) for `embedding_model`.
///
/// A missing cache file is not an error; entries for another embedding model are ignored, so a
/// model change can never serve a stale vector.
fn load_mention_cache(
    cache_path: &Path,
    embedding_model: &str,
) -> Result<HashMap<String, Vec<f32>>, String> {
    let mut map = HashMap::new();
    if !cache_path.exists() {
        return Ok(map);
    }
    let content = std::fs::read_to_string(cache_path)
        .map_err(|error| format!("failed to read cache {}: {error}", cache_path.display()))?;
    for (line_number, line) in content.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let entry: MentionCacheEntry = serde_json::from_str(line).map_err(|error| {
            format!(
                "failed to parse cache {} at line {}: {error}",
                cache_path.display(),
                line_number + 1
            )
        })?;
        if entry.embedding_model == embedding_model {
            map.insert(entry.mention, entry.embedding);
        }
    }
    Ok(map)
}

/// What the mention embedder has spent and holds, behind one lock.
struct MeterState {
    cache: HashMap<String, Vec<f32>>,
    spend_usd: f64,
}

/// Wraps the production embedding client with a mention cache, the in-process spend estimate and
/// the `--stage-cap` check, so the seed and path code under test is the exact library path
/// (`LanceMentionVectorSearch`) and only the paid dispatch is metered here (D-86).
///
/// The OpenRouter embeddings response carries no `usage` field, so spend is always the estimated
/// case: cl100k tokens of the uncached mentions at `EMBEDDING_PRICE_PER_1M`, charged per request
/// and checked before the request is dispatched.
struct MeteredEmbedder {
    inner: OpenRouterClient,
    model: String,
    cache_path: PathBuf,
    stage_cap: f64,
    state: Mutex<MeterState>,
    stopped_by_cap: AtomicBool,
    embedded_mentions: AtomicUsize,
    cache_hits: AtomicUsize,
}

impl MeteredEmbedder {
    fn lock(&self) -> Result<std::sync::MutexGuard<'_, MeterState>, String> {
        self.state
            .lock()
            .map_err(|_| "mention embedder state lock was poisoned".to_string())
    }
}

impl EmbeddingProvider for MeteredEmbedder {
    fn model_id(&self) -> &str {
        &self.model
    }

    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move {
            let misses: Vec<String> = {
                let state = self.lock()?;
                let mut seen: HashSet<&String> = HashSet::new();
                texts
                    .iter()
                    .filter(|text| !state.cache.contains_key(*text) && seen.insert(*text))
                    .cloned()
                    .collect()
            };
            if !misses.is_empty() {
                let tokens: u64 = misses.iter().map(|text| estimate_tokens_cl100k(text)).sum();
                let cost = (tokens as f64 / 1_000_000.0) * EMBEDDING_PRICE_PER_1M;
                {
                    let state = self.lock()?;
                    if state.spend_usd + cost > self.stage_cap {
                        self.stopped_by_cap.store(true, Ordering::SeqCst);
                        return Err(format!(
                            "stage cap ${:.4} would be exceeded by a ${cost:.6} mention-embedding \
                             request after ${:.6} spent; no further request dispatched",
                            self.stage_cap, state.spend_usd
                        ));
                    }
                }
                let vectors = self
                    .inner
                    .get_embeddings(&misses)
                    .await
                    .map_err(|error| format!("mention embedding request failed: {error}"))?;
                if vectors.len() != misses.len() {
                    return Err(format!(
                        "embedding provider returned {} vectors for {} mentions",
                        vectors.len(),
                        misses.len()
                    ));
                }
                if vectors.iter().any(|vector| {
                    vector.len() != EXPECTED_EMBEDDING_DIM
                        || vector.iter().any(|value| !value.is_finite())
                }) {
                    return Err("embedding provider returned an invalid mention payload".to_string());
                }
                let entries: Vec<MentionCacheEntry> = misses
                    .iter()
                    .cloned()
                    .zip(vectors)
                    .map(|(mention, embedding)| MentionCacheEntry {
                        mention,
                        embedding_model: self.model.clone(),
                        embedding,
                    })
                    .collect();
                append_cache(&self.cache_path, &entries)?;
                let mut state = self.lock()?;
                for entry in entries {
                    state.cache.insert(entry.mention, entry.embedding);
                }
                state.spend_usd += cost;
                self.embedded_mentions
                    .fetch_add(misses.len(), Ordering::SeqCst);
            }
            self.cache_hits
                .fetch_add(texts.len().saturating_sub(misses.len()), Ordering::SeqCst);
            let state = self.lock()?;
            texts
                .iter()
                .map(|text| {
                    state
                        .cache
                        .get(text)
                        .cloned()
                        .ok_or_else(|| "mention embedding missing after dispatch".to_string())
                })
                .collect()
        })
    }
}

/// One matched seed as printed by the probe, with its source documents for column (d).
#[derive(Serialize)]
struct SeedRecord<'a> {
    #[serde(flatten)]
    seed: &'a Seed,
    source_document_ids: Vec<String>,
    source_chunk_count: usize,
}

#[derive(Serialize)]
struct PathRecord {
    entities: Vec<String>,
    relations: Vec<String>,
    rendered: String,
    score: f64,
    /// cl100k tokens of the `<GRAPH_FACT>` block the prompt packer would emit for this path.
    tokens: u64,
}

#[derive(Serialize)]
struct GraphSeedRecord<'a> {
    question_id: String,
    mentions: Vec<String>,
    seeds: Vec<SeedRecord<'a>>,
    seed_count: usize,
    path_found: bool,
    paths: Vec<PathRecord>,
    /// Ranked source chunks of the entities on the found paths (the `paths-only` option).
    candidate_chunk_ids: Vec<String>,
    /// Ranked source chunks of the seeds themselves (the length-0 paths of `paths-plus-seed-chunks`).
    seed_chunk_candidate_ids: Vec<String>,
    degree_capped_count: u32,
}

#[derive(Serialize)]
struct ProbeSettings {
    max_seeds: usize,
    mention_vector_top_k: usize,
    seed_match_min_score: f64,
    degree_cap: u32,
    max_graph_chunk_candidates: usize,
    max_path_facts: &'static str,
}

#[derive(Serialize)]
struct GraphSeedsSummary {
    /// In-process spend estimate in USD (the provider reports no usage).
    spend_usd: f64,
    stage_cap_usd: f64,
    questions: usize,
    mentions_embedded: usize,
    mention_cache_hits: usize,
    stopped_by_cap: bool,
    index_generation: String,
    embedding_model: String,
    entity_count: usize,
    degree_p95: f64,
    degree_p99: f64,
    degree_max: f64,
    evidence_token_budget: usize,
    max_output_tokens: u32,
    settings: ProbeSettings,
    error: Option<String>,
}

/// cl100k tokens of the `<GRAPH_FACT>` block `prompt::pack_evidence_and_graph_prompt` builds for a
/// fact (`prompt.rs`, the `PackCandidate::Graph` arm), counted with the same tokenizer. The
/// section header is counted once per prompt there and is not part of the per-fact figure.
fn graph_fact_block_tokens(fact: &GraphFact) -> u64 {
    let rendered = ContextAssemblyStrategy::PrecomputedSemantics.assemble(fact);
    let block = format!(
        "<GRAPH_FACT entity_a=\"{}\" relation=\"{}\" entity_b=\"{}\" score=\"{:.4}\">\n{}\n</GRAPH_FACT>\n\n",
        fact.entity_a_name(),
        fact.relation_type(),
        fact.entity_b_name(),
        fact.score,
        rendered
    );
    estimate_tokens_cl100k(&block)
}

/// `--graph-seeds`: the OI-01 offline seed/path probe (06.3.4.1-13). Read-only against the store.
async fn run_graph_seeds(
    questions_path: &Path,
    stage_cap: f64,
    degree_cap: u32,
    mention_cache: &Path,
) -> Result<(), String> {
    let settings = load_settings().map_err(|error| format!("failed to load settings: {error}"))?;
    let lancedb_path = settings.engine.lancedb_path.clone();
    ensure_eval_store(&lancedb_path)?;
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings)
        .map_err(|error| format!("invalid RAG configuration: {error}"))?;

    let api_key = std::env::var("OPENROUTER_API_KEY")
        .map_err(|_| "OPENROUTER_API_KEY environment variable is not set".to_string())?;
    if api_key.trim().is_empty() {
        return Err("OPENROUTER_API_KEY environment variable must not be empty or blank".to_string());
    }

    // The store is validated first: `DatabaseManager`'s table accessors create an empty table when
    // one is missing, so nothing may call one before `open_and_validate` has succeeded. `initialize`
    // is never called.
    let database = DatabaseManager::open_and_validate(&lancedb_path)
        .await
        .map_err(|error| format!("failed to open LanceDB read-only: {error}"))?;
    let nodes = database
        .nodes_table()
        .await
        .map_err(|error| format!("failed to open nodes table: {error}"))?;
    let nodes_version = nodes
        .version()
        .await
        .map_err(|error| format!("failed to read nodes version: {error}"))?;
    let generation = corpus_generation_from_nodes_version(nodes_version);

    let index = GraphIndex::build(&database).await?;
    tracing::info!(
        index_generation = %generation,
        entity_count = index.entity_count(),
        "diag_probe graph-seeds index built"
    );

    let embedding_config = OpenRouterEmbeddingConfig::new_with_concurrency(
        effective_settings.embedding_model.clone(),
        effective_settings.embedding_endpoint.clone(),
        effective_settings.embedding_concurrency,
    )
    .map_err(|error| format!("invalid embedding config: {error}"))?;
    let client = OpenRouterClient::new_with_config(api_key, embedding_config)
        .map_err(|error| format!("failed to build embedding client: {error}"))?;
    let model = effective_settings.embedding_model.clone();
    let embedder = Arc::new(MeteredEmbedder {
        inner: client,
        model: model.clone(),
        cache_path: mention_cache.to_path_buf(),
        stage_cap,
        state: Mutex::new(MeterState {
            cache: load_mention_cache(mention_cache, &model)?,
            spend_usd: 0.0,
        }),
        stopped_by_cap: AtomicBool::new(false),
        embedded_mentions: AtomicUsize::new(0),
        cache_hits: AtomicUsize::new(0),
    });
    let search = LanceMentionVectorSearch {
        database: database.clone(),
        embedder: embedder.clone(),
    };

    let seed_settings = SeedSettings {
        seed_match_min_score: effective_settings.graph.seed_match_min_score,
        ..SeedSettings::default()
    };
    let path_settings = PathSettings {
        degree_cap,
        // Unbounded for the probe only, so every found path is reported and its token cost can
        // inform the cap. Production applies `MAX_PATH_FACTS`.
        max_path_facts: usize::MAX,
        max_graph_chunk_candidates: effective_settings.retrieval.final_limit,
    };

    let questions = load_questions(questions_path)?;
    let mut processed = 0usize;
    let outcome: Result<(), String> = async {
        for (question_id, text) in &questions {
            let mentions = extract_mentions(text);
            let seeds = match_seeds(&index, &mentions, &search, &seed_settings).await?;
            let result = find_seed_paths(&database, &index, &seeds, &path_settings).await?;
            let seed_chunk_candidate_ids =
                seed_chunk_candidates(&index, &seeds, path_settings.max_graph_chunk_candidates);

            let paths: Vec<PathRecord> = result
                .paths
                .iter()
                .zip(result.facts.iter())
                .map(|(path, fact)| PathRecord {
                    entities: path.entities.clone(),
                    relations: path.relations.clone(),
                    rendered: path.rendered.clone(),
                    score: path.score,
                    tokens: graph_fact_block_tokens(fact),
                })
                .collect();
            let record = GraphSeedRecord {
                question_id: question_id.clone(),
                mentions,
                seed_count: seeds.len(),
                seeds: seeds
                    .iter()
                    .map(|seed| SeedRecord {
                        seed,
                        source_document_ids: index.seed_document_ids(&seed.entity_id),
                        source_chunk_count: index.source_chunk_ids(&seed.entity_id).len(),
                    })
                    .collect(),
                path_found: result.path_found,
                paths,
                candidate_chunk_ids: result.candidate_chunk_ids,
                seed_chunk_candidate_ids,
                degree_capped_count: result.degree_capped_count,
            };
            println!(
                "{}",
                serde_json::to_string(&record).map_err(|error| error.to_string())?
            );
            processed += 1;
        }
        Ok(())
    }
    .await;

    let spend_usd = embedder.lock().map(|state| state.spend_usd).unwrap_or(0.0);
    let summary = GraphSeedsSummary {
        spend_usd,
        stage_cap_usd: stage_cap,
        questions: processed,
        mentions_embedded: embedder.embedded_mentions.load(Ordering::SeqCst),
        mention_cache_hits: embedder.cache_hits.load(Ordering::SeqCst),
        stopped_by_cap: embedder.stopped_by_cap.load(Ordering::SeqCst),
        index_generation: generation,
        embedding_model: model,
        entity_count: index.entity_count(),
        degree_p95: index.degree_percentile(0.95),
        degree_p99: index.degree_percentile(0.99),
        degree_max: index.degree_percentile(1.0),
        evidence_token_budget: effective_settings.evidence_token_budget,
        max_output_tokens: effective_settings.max_output_tokens,
        settings: ProbeSettings {
            max_seeds: seed_settings.max_seeds,
            mention_vector_top_k: seed_settings.mention_vector_top_k,
            seed_match_min_score: seed_settings.seed_match_min_score,
            degree_cap,
            max_graph_chunk_candidates: path_settings.max_graph_chunk_candidates,
            max_path_facts: "unbounded",
        },
        error: outcome.as_ref().err().cloned(),
    };
    println!(
        "{}",
        serde_json::to_string(&summary).map_err(|error| error.to_string())?
    );
    outcome
}

#[derive(Deserialize, Default)]
struct RechunkCheckInput {
    #[serde(default)]
    candidates: Vec<String>,
    #[serde(default)]
    controls: Vec<String>,
}

#[derive(Serialize)]
struct RechunkCheckRecord {
    document_id: String,
    /// True for a known-`in_chunk` document included only to validate the check itself: if a
    /// control comes back `identical: false`, the rechunk config or input bytes have drifted
    /// from ingest-time, and no candidate result in the same run should be trusted yet.
    control: bool,
    identical: bool,
    stored_chunks: usize,
    rechunked_chunks: usize,
}

async fn query_document_ids(table: &Table, document_id: &str, columns: &[&str]) -> Result<Vec<RecordBatch>, String> {
    let predicate = format!("document_id = '{}'", escape_sql_literal(document_id));
    table
        .query()
        .only_if(predicate)
        .select(Select::columns(columns))
        .execute()
        .await
        .map_err(|error| format!("failed to query {document_id}: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("failed to collect rows for {document_id}: {error}"))
}

/// Re-chunks one document's live `raw_content` with the production chunker at the eval corpus's
/// known ingest-time settings, and compares the result to the stored `nodes.content` ordered by
/// `chunk_index`.
async fn check_single_document(
    documents_table: &Table,
    nodes_table: &Table,
    document_id: &str,
    control: bool,
) -> Result<RechunkCheckRecord, String> {
    let parsed = Uuid::parse_str(document_id)
        .map_err(|_| format!("rechunk-check document_id '{document_id}' is not a valid UUID"))?;
    if parsed.get_version_num() != 4 {
        return Err(format!(
            "rechunk-check document_id '{document_id}' is not a UUIDv4"
        ));
    }

    let doc_batches = query_document_ids(documents_table, document_id, &["raw_content"]).await?;
    let mut raw_content: Option<Vec<u8>> = None;
    for batch in &doc_batches {
        let column = batch
            .column_by_name("raw_content")
            .ok_or_else(|| "documents result missing raw_content column".to_string())?
            .as_any()
            .downcast_ref::<BinaryArray>()
            .ok_or_else(|| "documents raw_content column has an unexpected type".to_string())?;
        for row in 0..batch.num_rows() {
            if !column.is_null(row) {
                raw_content = Some(column.value(row).to_vec());
            }
        }
    }
    let raw_content = raw_content.ok_or_else(|| {
        format!("document '{document_id}' has no raw_content row in the live store")
    })?;

    let node_batches =
        query_document_ids(nodes_table, document_id, &["chunk_index", "content"]).await?;
    let mut stored: Vec<(i32, String)> = Vec::new();
    for batch in &node_batches {
        let index_col = batch
            .column_by_name("chunk_index")
            .ok_or_else(|| "nodes result missing chunk_index column".to_string())?
            .as_any()
            .downcast_ref::<Int32Array>()
            .ok_or_else(|| "nodes chunk_index column has an unexpected type".to_string())?;
        let content_col = batch
            .column_by_name("content")
            .ok_or_else(|| "nodes result missing content column".to_string())?
            .as_any()
            .downcast_ref::<StringArray>()
            .ok_or_else(|| "nodes content column has an unexpected type".to_string())?;
        for row in 0..batch.num_rows() {
            stored.push((index_col.value(row), content_col.value(row).to_owned()));
        }
    }
    stored.sort_by_key(|(index, _)| *index);
    let stored_contents: Vec<String> = stored.into_iter().map(|(_, content)| content).collect();

    // Explicit metadata (rather than relying on `IngestionJob::new`'s empty-metadata default) so
    // the assumed ingest-time settings are visible in this bin's own source, not hidden behind a
    // `Default` impl living in a different module.
    let mut metadata = HashMap::new();
    metadata.insert("chunk_strategy".to_string(), "structure-aware".to_string());
    metadata.insert("chunk_size".to_string(), DEFAULT_CHUNK_SIZE.to_string());
    metadata.insert("chunk_overlap".to_string(), DEFAULT_CHUNK_OVERLAP.to_string());
    let job = IngestionJob::new(
        document_id.to_string(),
        "article.txt".to_string(),
        raw_content,
        metadata,
    );
    let (_strategy, chunks) = chunk_ingestion_job(&job);
    let rechunked_contents: Vec<String> = chunks.into_iter().map(|chunk| chunk.content).collect();

    let identical = stored_contents == rechunked_contents;

    Ok(RechunkCheckRecord {
        document_id: document_id.to_string(),
        control,
        identical,
        stored_chunks: stored_contents.len(),
        rechunked_chunks: rechunked_contents.len(),
    })
}

async fn run_rechunk_check(database: &DatabaseManager, doc_ids_path: &Path) -> Result<(), String> {
    let raw = std::fs::read_to_string(doc_ids_path)
        .map_err(|error| format!("failed to read {}: {error}", doc_ids_path.display()))?;
    let input: RechunkCheckInput = serde_json::from_str(&raw)
        .map_err(|error| format!("failed to parse {}: {error}", doc_ids_path.display()))?;
    if input.candidates.is_empty() && input.controls.is_empty() {
        return Err(format!(
            "{} carries neither candidates nor controls",
            doc_ids_path.display()
        ));
    }

    let documents_table = database
        .documents_table()
        .await
        .map_err(|error| format!("failed to open documents table: {error}"))?;
    let nodes_table = database
        .nodes_table()
        .await
        .map_err(|error| format!("failed to open nodes table: {error}"))?;

    let mut targets: Vec<(String, bool)> =
        Vec::with_capacity(input.candidates.len() + input.controls.len());
    targets.extend(input.candidates.into_iter().map(|id| (id, false)));
    targets.extend(input.controls.into_iter().map(|id| (id, true)));

    for (document_id, control) in targets {
        let record =
            check_single_document(&documents_table, &nodes_table, &document_id, control).await?;
        println!(
            "{}",
            serde_json::to_string(&record).map_err(|error| error.to_string())?
        );
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mode = parse_args(args)?;

    match mode {
        Mode::RechunkCheck { doc_ids_path } => {
            let settings = load_settings().map_err(|error| format!("failed to load settings: {error}"))?;
            let lancedb_path = settings.engine.lancedb_path.clone();
            ensure_eval_store(&lancedb_path)?;
            let database = DatabaseManager::open_and_validate(&lancedb_path)
                .await
                .map_err(|error| format!("failed to open LanceDB read-only: {error}"))?;
            run_rechunk_check(&database, &doc_ids_path).await
        }
        Mode::GraphSeeds {
            questions,
            stage_cap,
            degree_cap,
            mention_cache,
        } => run_graph_seeds(&questions, stage_cap, degree_cap, &mention_cache).await,
        Mode::VectorTopK {
            k,
            questions,
            stage_cap,
            cache,
            estimate_only,
        } => {
            if estimate_only {
                run_estimate_only(k, &questions, &cache).await
            } else {
                let stage_cap = stage_cap.expect("validated non-None by parse_args");
                run_vector_top_k(k, &questions, stage_cap, &cache).await
            }
        }
    }
}
