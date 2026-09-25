//! OI-02 P0 diagnostic bin (06.3.4.1-03, D-64/D-65): a read-only, API-free, production-faithful
//! soak that reproduces (or rules out) in-process RetrieveHybrid latency growth.
//!
//! Mirrors `main.rs`'s startup exactly (`#[tokio::main]` multi-thread runtime,
//! `engine::telemetry::init`, settings loading, startup snapshot build) so the soak carries the
//! same background telemetry/runtime overhead as production. It never calls a provider API:
//! query vectors and text come from rows already stored in the `nodes`/`entities` tables, opened
//! read-only via `DatabaseManager::open_and_validate` (no `add`/`delete`/`optimize`).
//!
//! Five arms drive `RetrieveHybridNode::execute` directly (R, RP, RG, RGT) or through the
//! production `WorkflowRunner` (W), with the production dense, BM25 and graph ports built
//! exactly as `service::build_production_workflow` builds them. Only the embedding and
//! generation ports are replaced by deterministic in-bin stand-ins (`FixedEmbeddingPort`,
//! `FixedGenerator`) so arm W never calls a provider either.
//!
//! Stdout carries exactly one header JSON object followed by one JSON object per iteration
//! (an inspect-bin CLI, per M-LOG-NOT-PRINT's exception — see `inspect_lancedb.rs`). Tracing
//! output from `engine::telemetry::init` goes to stderr (see `telemetry/mod.rs`), so it never
//! interleaves with this bin's stdout JSONL.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use arrow_array::{Array, FixedSizeListArray, Float32Array, RecordBatch, StringArray};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use lancedb::Table;
use serde::Serialize;
use tokio_util::sync::CancellationToken;

use engine::config::{load_settings, EffectiveRagSettings, GraphSettings};
use engine::db::DatabaseManager;
use engine::generation::{
    self, AnswerBasis, GenerationError, GenerationRequest, Generator, ModelOutput, ModelUsage,
};
use engine::graph::escape_sql_literal;
use engine::pb::lancet::v1::QueryRagRequest;
use engine::prompt;
use engine::rerank;
use engine::retrieval::Bm25Index;
use engine::service::{
    attempt_graph_augmentation, ProductionBm25RetrievalPort, ProductionDenseRetrievalPort,
    ProductionGraphQueryPort,
};
use engine::workflow::node::{BoxFuture, NodeError};
use engine::workflow::nodes::retrieve::RetrieveSubStageReport;
use engine::workflow::nodes::{
    AssemblePromptNode, ExtractGraphContextNode, GenerateAnswerNode, ReformulateQueryNode,
    RetrieveHybridNode,
};
use engine::workflow::ports::{
    corpus_generation_from_nodes_version, DenseRetrievalPort, NoOpQueryReformulator,
};
use engine::workflow::{EventSequence, WorkflowContext, WorkflowEventSink, WorkflowRunner};

const USAGE: &str = "\
retrieval_soak --arm <R|RP|RG|RGT|W> [--iterations N] [--graph-timeout-ms N] [--lancedb-path PATH]
                [--pace-ms N] [--duration-secs N]

  --arm              R (retrieval only), RP (+prompt pack), RG (+graph, no timeout),
                      RGT (+graph, tokio::time::timeout), or W (full production node sequence)
  --iterations       default 300. In fixed mode (no --duration-secs) this is both the seeded
                      sample size and the exact loop count. In duration mode (--duration-secs
                      given) this becomes only the seeded sample size to fetch up front; pass a
                      value comfortably above the expected iteration count to avoid cycling
                      through the sample (06.3.4.1-03 long-duration soak, round 3).
  --graph-timeout-ms default 200 (RGT only)
  --lancedb-path     overrides the configured store path
  --pace-ms          idle delay after each iteration, via `tokio::time::sleep` (not a blocking
                      thread sleep, per M-YIELD-POINTS: a thread sleep would distort the very
                      `alive_tasks`/`global_queue_depth` counters this bin reports). Default 0
                      (no pacing, matches the original P0 soak behaviour exactly).
  --duration-secs    when set, overrides --iterations as the loop's stop condition: the soak
                      runs until this many wall-clock seconds have elapsed instead of a fixed
                      iteration count. The seeded sample is cycled (wrapped modulo its size) if
                      the run outlives it; the header's `requested_sample_size` and each run's
                      stderr summary report whether cycling occurred.";

/// Fixed seed for the deterministic chunk/entity sample (06.3.4.1-03 Task 1). Recorded in the
/// header line of every run so the exact sample is reproducible against the same store state.
const SOAK_SEED: u64 = 0x4C414E43_45543033; // "LANCET03" in hex-ish, arbitrary but stable

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Arm {
    R,
    Rp,
    Rg,
    Rgt,
    W,
}

impl Arm {
    fn parse(raw: &str) -> Result<Self, String> {
        match raw {
            "R" => Ok(Arm::R),
            "RP" => Ok(Arm::Rp),
            "RG" => Ok(Arm::Rg),
            "RGT" => Ok(Arm::Rgt),
            "W" => Ok(Arm::W),
            other => Err(format!("unknown --arm '{other}', expected R|RP|RG|RGT|W\n{USAGE}")),
        }
    }

    fn label(&self) -> &'static str {
        match self {
            Arm::R => "R",
            Arm::Rp => "RP",
            Arm::Rg => "RG",
            Arm::Rgt => "RGT",
            Arm::W => "W",
        }
    }

    /// R and RP draw query vectors from `nodes.embedding` (no graph touch). RG, RGT and W draw
    /// from `entities.name_vector` instead: using an entity's own vector as the query embedding
    /// guarantees `attempt_graph_augmentation`'s seed match trivially succeeds (near-zero
    /// distance to itself), so every iteration deterministically exercises the graph path these
    /// arms exist to profile, rather than depending on incidental proximity between an
    /// arbitrary chunk embedding and the nearest entity.
    fn uses_entity_seed(&self) -> bool {
        matches!(self, Arm::Rg | Arm::Rgt | Arm::W)
    }
}

struct Args {
    arm: Arm,
    iterations: usize,
    graph_timeout_ms: u64,
    lancedb_path: Option<String>,
    pace_ms: u64,
    duration_secs: Option<u64>,
}

fn parse_args(args: Vec<String>) -> Result<Args, String> {
    let mut arm: Option<Arm> = None;
    let mut iterations: usize = 300;
    let mut graph_timeout_ms: u64 = 200;
    let mut lancedb_path: Option<String> = None;
    let mut pace_ms: u64 = 0;
    let mut duration_secs: Option<u64> = None;

    let mut iter = args.into_iter();
    while let Some(flag) = iter.next() {
        match flag.as_str() {
            "--arm" => {
                let value = iter.next().ok_or_else(|| format!("--arm requires a value\n{USAGE}"))?;
                arm = Some(Arm::parse(&value)?);
            }
            "--iterations" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--iterations requires a value\n{USAGE}"))?;
                iterations = value
                    .parse()
                    .map_err(|_| format!("--iterations must be a positive integer\n{USAGE}"))?;
            }
            "--graph-timeout-ms" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--graph-timeout-ms requires a value\n{USAGE}"))?;
                graph_timeout_ms = value
                    .parse()
                    .map_err(|_| format!("--graph-timeout-ms must be a positive integer\n{USAGE}"))?;
            }
            "--lancedb-path" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--lancedb-path requires a value\n{USAGE}"))?;
                lancedb_path = Some(value);
            }
            "--pace-ms" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--pace-ms requires a value\n{USAGE}"))?;
                pace_ms = value
                    .parse()
                    .map_err(|_| format!("--pace-ms must be a non-negative integer\n{USAGE}"))?;
            }
            "--duration-secs" => {
                let value = iter
                    .next()
                    .ok_or_else(|| format!("--duration-secs requires a value\n{USAGE}"))?;
                let parsed_secs: u64 = value
                    .parse()
                    .map_err(|_| format!("--duration-secs must be a positive integer\n{USAGE}"))?;
                if parsed_secs == 0 {
                    return Err(format!("--duration-secs must be greater than 0\n{USAGE}"));
                }
                duration_secs = Some(parsed_secs);
            }
            other => return Err(format!("unrecognized flag '{other}'\n{USAGE}")),
        }
    }

    let arm = arm.ok_or_else(|| format!("--arm is required\n{USAGE}"))?;
    if iterations == 0 {
        return Err(format!("--iterations must be greater than 0\n{USAGE}"));
    }
    Ok(Args {
        arm,
        iterations,
        graph_timeout_ms,
        lancedb_path,
        pace_ms,
        duration_secs,
    })
}

/// Minimal deterministic PRNG (SplitMix64) used only to pick the fixed seeded row sample.
/// Avoids a new `rand` dependency for a single, recorded, non-cryptographic seed.
struct SplitMix64(u64);

impl SplitMix64 {
    fn new(seed: u64) -> Self {
        Self(seed)
    }

    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }
}

/// Seeded, order-preserving partial Fisher-Yates pick of `k` distinct indices from `0..n`.
/// The returned order IS the soak's iteration order (ordinal 1..k), so the same seed always
/// reproduces the same sample in the same order against the same store state.
fn seeded_sample_indices(n: usize, k: usize, seed: u64) -> Vec<usize> {
    let mut idx: Vec<usize> = (0..n).collect();
    let mut rng = SplitMix64::new(seed);
    let take = k.min(n);
    for i in 0..take {
        let remaining = n - i;
        let j = i + (rng.next_u64() as usize) % remaining;
        idx.swap(i, j);
    }
    idx.truncate(take);
    idx
}

fn build_in_predicate(column: &str, values: &[String]) -> String {
    let quoted: Vec<String> = values
        .iter()
        .map(|v| format!("'{}'", escape_sql_literal(v)))
        .collect();
    format!("{column} IN ({})", quoted.join(","))
}

fn embedding_at(list: &FixedSizeListArray, row: usize) -> Result<Vec<f32>, String> {
    let value = list.value(row);
    let floats = value
        .as_any()
        .downcast_ref::<Float32Array>()
        .ok_or_else(|| "embedding value column is not Float32Array".to_string())?;
    Ok(floats.values().to_vec())
}

fn string_at(batch: &RecordBatch, name: &str, row: usize) -> Result<String, String> {
    let col = batch
        .column_by_name(name)
        .ok_or_else(|| format!("missing column {name}"))?;
    let arr = col
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| format!("column {name} is not StringArray"))?;
    if arr.is_null(row) {
        return Err(format!("column {name} is null at row {row}"));
    }
    Ok(arr.value(row).to_string())
}

fn opt_string_at(batch: &RecordBatch, name: &str, row: usize) -> Option<String> {
    let col = batch.column_by_name(name)?;
    let arr = col.as_any().downcast_ref::<StringArray>()?;
    if arr.is_null(row) {
        None
    } else {
        Some(arr.value(row).to_string())
    }
}

/// A seeded query row: an embedding plus a short, safe (never logged) query text.
struct SeedRow {
    /// Retained for future debugging/correlation against store dumps; not read by this bin
    /// today.
    #[allow(dead_code)]
    id: String,
    embedding: Vec<f32>,
    query_text: String,
}

fn bounded_query_text(candidate: Option<String>, fallback: &str) -> String {
    let raw = candidate.unwrap_or_else(|| fallback.to_string());
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        fallback.to_string()
    } else {
        trimmed.chars().take(200).collect()
    }
}

async fn fetch_all_string_column(table: &Table, column: &str) -> Result<Vec<String>, String> {
    let batches: Vec<RecordBatch> = table
        .query()
        .select(Select::columns(&[column]))
        .execute()
        .await
        .map_err(|error| format!("failed to list {column}: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("failed to collect {column} rows: {error}"))?;
    let mut out = Vec::new();
    for batch in &batches {
        for row in 0..batch.num_rows() {
            out.push(string_at(batch, column, row)?);
        }
    }
    Ok(out)
}

/// Seeded selection of `k` `nodes` rows, in iteration order. Query text is the chunk's own
/// `title` (falling back to a `content` prefix), used only for BM25 tokenization — content is
/// real corpus text, never logged, and this text never leaves the process except as BM25 input.
async fn select_seeded_chunk_rows(
    nodes_table: &Table,
    seed: u64,
    k: usize,
) -> Result<Vec<SeedRow>, String> {
    let all_ids = fetch_all_string_column(nodes_table, "chunk_id").await?;
    if all_ids.is_empty() {
        return Err("nodes table has zero rows; cannot sample a query set".to_string());
    }
    let picked_indices = seeded_sample_indices(all_ids.len(), k, seed);
    let picked_ids: Vec<String> = picked_indices.iter().map(|&i| all_ids[i].clone()).collect();

    let predicate = build_in_predicate("chunk_id", &picked_ids);
    let batches: Vec<RecordBatch> = nodes_table
        .query()
        .only_if(predicate)
        .select(Select::columns(&["chunk_id", "embedding", "title", "content"]))
        .execute()
        .await
        .map_err(|error| format!("failed to fetch seeded chunk rows: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("failed to collect seeded chunk rows: {error}"))?;

    let mut by_id: HashMap<String, (Vec<f32>, Option<String>, Option<String>)> = HashMap::new();
    for batch in &batches {
        let embeddings = batch
            .column_by_name("embedding")
            .ok_or_else(|| "missing embedding column".to_string())?
            .as_any()
            .downcast_ref::<FixedSizeListArray>()
            .ok_or_else(|| "embedding column has unexpected type".to_string())?;
        for row in 0..batch.num_rows() {
            let chunk_id = string_at(batch, "chunk_id", row)?;
            let embedding = embedding_at(embeddings, row)?;
            let title = opt_string_at(batch, "title", row);
            let content = opt_string_at(batch, "content", row);
            by_id.insert(chunk_id, (embedding, title, content));
        }
    }

    let mut rows = Vec::with_capacity(picked_ids.len());
    for id in &picked_ids {
        if let Some((embedding, title, content)) = by_id.get(id) {
            let content_prefix = content.as_ref().map(|c| c.chars().take(120).collect::<String>());
            let query_text = bounded_query_text(title.clone().or(content_prefix), "chunk query");
            rows.push(SeedRow {
                id: id.clone(),
                embedding: embedding.clone(),
                query_text,
            });
        }
    }
    Ok(rows)
}

/// Seeded selection of `k` `entities` rows, in iteration order. See [`Arm::uses_entity_seed`]
/// for why the graph-touching arms use entity vectors rather than chunk vectors.
async fn select_seeded_entity_rows(
    entities_table: &Table,
    seed: u64,
    k: usize,
) -> Result<Vec<SeedRow>, String> {
    let all_ids = fetch_all_string_column(entities_table, "entity_id").await?;
    if all_ids.is_empty() {
        return Err("entities table has zero rows; cannot sample a graph query set".to_string());
    }
    // A distinct seed derivation (not the same raw constant) so the entity sample is
    // independent of the chunk sample rather than picking the same relative positions twice.
    let picked_indices = seeded_sample_indices(all_ids.len(), k, seed ^ 0xA5A5_A5A5_A5A5_A5A5);
    let picked_ids: Vec<String> = picked_indices.iter().map(|&i| all_ids[i].clone()).collect();

    let predicate = build_in_predicate("entity_id", &picked_ids);
    let batches: Vec<RecordBatch> = entities_table
        .query()
        .only_if(predicate)
        .select(Select::columns(&["entity_id", "name", "name_vector"]))
        .execute()
        .await
        .map_err(|error| format!("failed to fetch seeded entity rows: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("failed to collect seeded entity rows: {error}"))?;

    let mut by_id: HashMap<String, (Vec<f32>, Option<String>)> = HashMap::new();
    for batch in &batches {
        let vectors = batch
            .column_by_name("name_vector")
            .ok_or_else(|| "missing name_vector column".to_string())?
            .as_any()
            .downcast_ref::<FixedSizeListArray>()
            .ok_or_else(|| "name_vector column has unexpected type".to_string())?;
        for row in 0..batch.num_rows() {
            let entity_id = string_at(batch, "entity_id", row)?;
            let vector = embedding_at(vectors, row)?;
            let name = opt_string_at(batch, "name", row);
            by_id.insert(entity_id, (vector, name));
        }
    }

    let mut rows = Vec::with_capacity(picked_ids.len());
    for id in &picked_ids {
        if let Some((embedding, name)) = by_id.get(id) {
            let query_text = bounded_query_text(name.clone(), "entity query");
            rows.push(SeedRow {
                id: id.clone(),
                embedding: embedding.clone(),
                query_text,
            });
        }
    }
    Ok(rows)
}

/// Deterministic embedding port returning a pre-selected stored vector regardless of the
/// variant text passed in. No provider call (D-64/D-65 soak fidelity).
struct FixedEmbeddingPort {
    embedding: Vec<f32>,
}

impl engine::workflow::node::QueryEmbeddingPort for FixedEmbeddingPort {
    fn embed_variant_zero<'a>(
        &'a self,
        _variant: &'a str,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<Vec<f32>, NodeError>> {
        let embedding = self.embedding.clone();
        Box::pin(async move { Ok(embedding) })
    }
}

/// Deterministic generator returning one fixed valid `ModelOutput` with an `[1]` citation. No
/// provider call (D-64/D-65 soak fidelity).
struct FixedGenerator;

impl Generator for FixedGenerator {
    fn model_id(&self) -> &str {
        "retrieval-soak-fixed-generator"
    }

    fn generate<'a>(
        &'a self,
        _request: GenerationRequest,
    ) -> generation::BoxFuture<'a, Result<ModelOutput, GenerationError>> {
        Box::pin(async move {
            Ok(ModelOutput {
                answer: "Answer: retrieval_soak fixed answer [1]".to_string(),
                cited_evidence_ids: vec!["[1]".to_string()],
                answer_basis: AnswerBasis::Retrieval,
                notices: vec![],
                warnings: vec![],
                usage: Some(ModelUsage::default()),
            })
        })
    }
}

#[derive(Serialize)]
struct HeaderLine {
    header: bool,
    arm: &'static str,
    iterations: usize,
    graph_timeout_ms: u64,
    build_profile: &'static str,
    binary_path: String,
    binary_mtime_unix_secs: Option<u64>,
    collector_endpoint: String,
    collector_reachable: bool,
    seed: u64,
    pid: u32,
    lancedb_path: String,
    /// Idle delay applied after every iteration (06.3.4.1-03 long-duration soak, round 3).
    /// `0` reproduces the original P0 soak's unpaced behaviour exactly.
    pace_ms: u64,
    /// When set, the loop's stop condition is wall-clock elapsed time rather than a fixed
    /// iteration count; `iterations` above is then only the requested seeded-sample size.
    duration_secs: Option<u64>,
    /// The seeded sample size requested via `--iterations` (identical to `iterations` above;
    /// named separately so a duration-mode header is self-documenting about which of the two
    /// roles `--iterations` played for this run).
    requested_sample_size: usize,
}

#[derive(Serialize, Clone, Copy)]
struct IterationLine {
    arm: &'static str,
    ordinal: usize,
    /// Wall-clock time this iteration finished, milliseconds since UNIX epoch. Correlates a
    /// JSONL row against the PowerShell process sampler's timestamped CSV rows (Task 2), which
    /// has no notion of iteration ordinal of its own.
    unix_ms: u128,
    ok: bool,
    retrieve_ms: f64,
    open_table_ms: f64,
    checkout_ms: f64,
    dense_ms: f64,
    bm25_ms: f64,
    fusion_ms: f64,
    pack_ms: Option<f64>,
    graph_ms: Option<f64>,
    graph_timed_out: Option<bool>,
    alive_tasks: usize,
    global_queue_depth: usize,
    rss_hint: Option<u64>,
    /// `lance::session::Session::size_bytes()` (06.3.4.1-03 long-duration soak, round 3): a
    /// full `deep_size_of` walk over the session's index/metadata caches, per its own doc
    /// comment "not trivial to compute" — not O(1), but cheap relative to this soak's
    /// multi-second iteration pace. `None` only if the table's dataset handle could not be
    /// read (never expected against a stable, already-open connection).
    session_size_bytes: Option<u64>,
    /// `lance::session::Session::approx_num_items()` — a rough, O(1)-ish estimate of index +
    /// metadata cache entry count plus extension count. Class-3 (Lance session cache growth)
    /// discriminator the original profile flagged as "not exercised as a contrast".
    session_approx_num_items: Option<usize>,
}

// `lance_session_stats` moved to `engine::db::lance_session_stats` (06.3.4.1-07 Task 2) so
// both this soak binary and the production service share one implementation. Call sites below
// use `engine::db::lance_session_stats` directly.

async fn probe_collector_reachable(endpoint: &str) -> bool {
    let stripped = endpoint
        .trim()
        .trim_start_matches("http://")
        .trim_start_matches("https://");
    let host_port = stripped.split('/').next().unwrap_or("");
    if host_port.is_empty() {
        return false;
    }
    let attempt = tokio::time::timeout(
        Duration::from_millis(500),
        tokio::net::TcpStream::connect(host_port),
    )
    .await;
    matches!(attempt, Ok(Ok(_)))
}

fn runtime_counters() -> (usize, usize) {
    let metrics = tokio::runtime::Handle::current().metrics();
    (metrics.num_alive_tasks(), metrics.global_queue_depth())
}

/// Milliseconds since UNIX epoch, for correlating a JSONL row against the PowerShell process
/// sampler's timestamped CSV rows (06.3.4.1-03 Task 2).
fn unix_millis_now() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

#[allow(clippy::too_many_arguments)]
async fn run_r_rp_rg_rgt(
    arm: Arm,
    ordinal: usize,
    row: &SeedRow,
    dense_port: Arc<dyn DenseRetrievalPort>,
    bm25_port: Arc<dyn engine::workflow::ports::Bm25RetrievalPort>,
    retrieval_settings: &engine::retrieval::RetrievalSettings,
    generation_label: &str,
    embedding_model: &str,
    excerpt_max_chars: usize,
    graph_weight: f64,
    max_prompt_tokens: usize,
    answer_token_budget: usize,
    database: &DatabaseManager,
    graph_settings: &GraphSettings,
    graph_timeout_ms: u64,
    session_stats_table: &Table,
) -> IterationLine {
    let node = RetrieveHybridNode::new(
        Some(dense_port),
        Some(bm25_port),
        Some(Arc::new(rerank::NoOpReranker::new())),
        retrieval_settings.clone(),
    )
    .with_snapshot_metadata(generation_label.to_string(), embedding_model.to_string())
    .with_rebuild_degraded(false)
    .with_excerpt_max_chars(excerpt_max_chars);
    let report_handle = node.substage_report_handle();

    let req = QueryRagRequest {
        query: row.query_text.clone(),
        ..Default::default()
    };
    let mut ctx = WorkflowContext::new(format!("soak-{}", ordinal), format!("soak-{}", ordinal), &req);
    ctx.query_embedding = Some(row.embedding.clone());
    let cancel = CancellationToken::new();

    let ok = node.execute(&mut ctx, &cancel).await.is_ok();
    let report: RetrieveSubStageReport = *report_handle.lock().unwrap_or_else(|p| p.into_inner());

    let mut pack_ms: Option<f64> = None;
    let mut graph_ms: Option<f64> = None;
    let mut graph_timed_out: Option<bool> = None;

    if ok && matches!(arm, Arm::Rp | Arm::Rg | Arm::Rgt) && !ctx.evidence_blocks.is_empty() {
        let pack_start = Instant::now();
        let packed = prompt::pack_evidence_and_graph_prompt(
            &row.query_text,
            &ctx.evidence_blocks,
            &[],
            graph_weight,
            max_prompt_tokens,
            answer_token_budget,
            &cancel,
        )
        .await;
        pack_ms = Some(pack_start.elapsed().as_secs_f64() * 1000.0);
        drop(packed);
    }

    if ok {
        match arm {
            Arm::Rg => {
                let graph_start = Instant::now();
                let _ = attempt_graph_augmentation(database, &row.embedding, graph_settings).await;
                graph_ms = Some(graph_start.elapsed().as_secs_f64() * 1000.0);
                graph_timed_out = Some(false);
            }
            Arm::Rgt => {
                let graph_start = Instant::now();
                let timed = tokio::time::timeout(
                    Duration::from_millis(graph_timeout_ms),
                    attempt_graph_augmentation(database, &row.embedding, graph_settings),
                )
                .await;
                graph_ms = Some(graph_start.elapsed().as_secs_f64() * 1000.0);
                graph_timed_out = Some(timed.is_err());
            }
            _ => {}
        }
    }

    let (alive_tasks, global_queue_depth) = runtime_counters();
    let (session_size_bytes, session_approx_num_items) =
        engine::db::lance_session_stats(session_stats_table).await;
    let unix_ms = unix_millis_now();

    IterationLine {
        arm: arm.label(),
        ordinal,
        unix_ms,
        ok,
        retrieve_ms: report.total_ms,
        open_table_ms: report.open_table_ms,
        checkout_ms: report.checkout_ms,
        dense_ms: report.dense_ms,
        bm25_ms: report.bm25_ms,
        fusion_ms: report.fusion_ms,
        pack_ms,
        graph_ms,
        graph_timed_out,
        alive_tasks,
        global_queue_depth,
        rss_hint: None,
        session_size_bytes,
        session_approx_num_items,
    }
}

#[allow(clippy::too_many_arguments)]
async fn run_w(
    ordinal: usize,
    row: &SeedRow,
    database: &DatabaseManager,
    effective_settings: &EffectiveRagSettings,
    dense_port: Arc<dyn DenseRetrievalPort>,
    bm25_port: Arc<dyn engine::workflow::ports::Bm25RetrievalPort>,
    generation_label: &str,
    session_stats_table: &Table,
) -> Result<(), String> {
    let wf = &effective_settings.workflow;
    let mut runner = WorkflowRunner::new().with_timeouts(
        wf.reformulate_timeout_ms,
        wf.graph_node_timeout_ms,
        wf.retrieve_timeout_ms,
        wf.prompt_timeout_ms,
        wf.generation_node_timeout_ms,
    );

    runner.add_node(ReformulateQueryNode::with_reformulator(Some(Arc::new(
        NoOpQueryReformulator::new(),
    ))));
    runner.add_node(
        ExtractGraphContextNode::new(
            Some(Arc::new(FixedEmbeddingPort {
                embedding: row.embedding.clone(),
            })),
            Some(Arc::new(ProductionGraphQueryPort {
                database: database.clone(),
                graph_settings: effective_settings.graph.clone(),
            })),
        )
        .with_timeouts(wf.query_embedding_timeout_ms, wf.graph_operation_timeout_ms),
    );
    let retrieve_node = RetrieveHybridNode::new(
        Some(dense_port),
        Some(bm25_port),
        Some(Arc::new(rerank::NoOpReranker::new())),
        effective_settings.retrieval.clone(),
    )
    .with_snapshot_metadata(generation_label.to_string(), effective_settings.embedding_model.clone())
    .with_rebuild_degraded(false)
    .with_excerpt_max_chars(effective_settings.citation_excerpt_max_chars);
    let report_handle = retrieve_node.substage_report_handle();
    runner.add_node(retrieve_node);

    runner.add_node(AssemblePromptNode::with_settings(
        effective_settings.grounding_limits().evidence_token_budget() as usize,
        effective_settings.grounding_limits().max_output_tokens() as usize,
        effective_settings.retrieval.graph_weight,
    ));
    runner.add_node(
        GenerateAnswerNode::new(Some(Arc::new(FixedGenerator)))
            .with_settings(
                *effective_settings.grounding_limits(),
                effective_settings.citation_excerpt_max_chars,
                effective_settings.retrieval.graph_weight,
            )
            .with_citation_repair_enabled(effective_settings.workflow.citation_repair_enabled),
    );

    let req = QueryRagRequest {
        query: row.query_text.clone(),
        ..Default::default()
    };
    let ctx = WorkflowContext::new(format!("soak-{}", ordinal), format!("soak-{}", ordinal), &req);
    let cancel = CancellationToken::new();
    let (tx, _rx) = tokio::sync::mpsc::channel(1024);
    let sequence = Arc::new(EventSequence::new());
    let sink = WorkflowEventSink::new(tx, sequence, format!("soak-{}", ordinal), format!("soak-{}", ordinal));

    let full_start = Instant::now();
    runner.run_workflow(ctx, cancel, sink).await;
    let full_workflow_ms = full_start.elapsed().as_secs_f64() * 1000.0;

    let report: RetrieveSubStageReport = *report_handle.lock().unwrap_or_else(|p| p.into_inner());
    let (alive_tasks, global_queue_depth) = runtime_counters();
    let (session_size_bytes, session_approx_num_items) =
        engine::db::lance_session_stats(session_stats_table).await;

    // AssemblePrompt/ExtractGraphContext node-level durations are not separately instrumented
    // for arm W (out of this task's file scope: only retrieve.rs and service.rs carry new
    // instrumentation). `full_workflow_ms` reports the whole-pipeline wall time as an extra
    // field beyond the plan's minimum schema instead. `pack_ms`/`graph_ms`/`graph_timed_out`
    // are `null` for this arm only.
    let line = serde_json::json!({
        "arm": Arm::W.label(),
        "ordinal": ordinal,
        "unix_ms": unix_millis_now(),
        "ok": report.total_ms > 0.0,
        "retrieve_ms": report.total_ms,
        "open_table_ms": report.open_table_ms,
        "checkout_ms": report.checkout_ms,
        "dense_ms": report.dense_ms,
        "bm25_ms": report.bm25_ms,
        "fusion_ms": report.fusion_ms,
        "pack_ms": serde_json::Value::Null,
        "graph_ms": serde_json::Value::Null,
        "graph_timed_out": serde_json::Value::Null,
        "alive_tasks": alive_tasks,
        "global_queue_depth": global_queue_depth,
        "rss_hint": serde_json::Value::Null,
        "full_workflow_ms": full_workflow_ms,
        "session_size_bytes": session_size_bytes,
        "session_approx_num_items": session_approx_num_items,
    });
    println!(
        "{}",
        serde_json::to_string(&line).map_err(|error| error.to_string())?
    );
    Ok(())
}

/// One output row of `--export-embeddings`: a chunk's own stored vector, JSONL to stdout.
#[derive(Serialize)]
struct ExportedEmbeddingRow {
    chunk_id: String,
    embedding: Vec<f32>,
}

/// `--export-embeddings <chunk_ids.json> --lancedb-path <path>`: read-only mode (06.3.4.1-07
/// Task 2) that opens the store via `DatabaseManager::open_and_validate` (never
/// `initialize`/`get_or_create_table`, so a missing table fails closed instead of silently
/// recreating it over live data) and prints `{chunk_id, embedding}` JSONL, one line per input
/// ID found in `nodes`. IDs absent from `nodes` are silently omitted from the output (the
/// caller -- `oi02-replay.ps1`'s stub-vector-map builder -- is expected to treat a missing ID
/// as a fallback-to-hash-vector case, not a hard error). No `#[cfg(test)]` module is added by
/// this function, so `scripts/engine-test-targets.sh`'s test-count gate is unaffected.
async fn run_export_embeddings(chunk_ids_path: &str, lancedb_path: Option<String>) -> Result<(), String> {
    let ids_json = std::fs::read_to_string(chunk_ids_path)
        .map_err(|error| format!("failed to read {chunk_ids_path}: {error}"))?;
    let chunk_ids: Vec<String> = serde_json::from_str(&ids_json)
        .map_err(|error| format!("failed to parse {chunk_ids_path} as a JSON array of strings: {error}"))?;
    if chunk_ids.is_empty() {
        return Ok(());
    }

    let settings = load_settings().map_err(|error| format!("failed to load settings: {error}"))?;
    let path = lancedb_path.unwrap_or_else(|| settings.engine.lancedb_path.clone());
    let database = DatabaseManager::open_and_validate(&path).await?;
    let nodes_table = database.nodes_table().await?;

    // Batch the IN-predicate lookup the same way select_seeded_* above does, rather than one
    // query per ID -- chunk_ids.json can carry hundreds of IDs for a 175-question replay.
    let predicate = build_in_predicate("chunk_id", &chunk_ids);
    let batches: Vec<RecordBatch> = nodes_table
        .query()
        .only_if(predicate)
        .select(Select::columns(&["chunk_id", "embedding"]))
        .execute()
        .await
        .map_err(|error| format!("failed to query nodes for --export-embeddings: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("failed to collect nodes rows for --export-embeddings: {error}"))?;

    let stdout = std::io::stdout();
    let mut writer = stdout.lock();
    use std::io::Write as _;
    for batch in &batches {
        let embeddings = batch
            .column_by_name("embedding")
            .ok_or_else(|| "missing embedding column".to_string())?
            .as_any()
            .downcast_ref::<FixedSizeListArray>()
            .ok_or_else(|| "embedding column has unexpected type".to_string())?;
        for row in 0..batch.num_rows() {
            let chunk_id = string_at(batch, "chunk_id", row)?;
            let embedding = embedding_at(embeddings, row)?;
            let line = ExportedEmbeddingRow { chunk_id, embedding };
            let json = serde_json::to_string(&line).map_err(|error| error.to_string())?;
            writeln!(writer, "{json}").map_err(|error| format!("failed to write stdout: {error}"))?;
        }
    }
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), String> {
    let raw_args: Vec<String> = std::env::args().skip(1).collect();
    if let Some(pos) = raw_args.iter().position(|a| a == "--export-embeddings") {
        let chunk_ids_path = raw_args
            .get(pos + 1)
            .ok_or_else(|| format!("--export-embeddings requires a value\n{USAGE}"))?
            .clone();
        let lancedb_path = raw_args
            .iter()
            .position(|a| a == "--lancedb-path")
            .and_then(|p| raw_args.get(p + 1))
            .cloned();
        return run_export_embeddings(&chunk_ids_path, lancedb_path).await;
    }

    let args: Vec<String> = raw_args;
    let parsed = parse_args(args)?;

    // Deliberate trade, mirroring `main.rs`: configuration loads before telemetry init so
    // configuration errors surface on stderr before any subscriber exists.
    let settings = load_settings().map_err(|error| format!("failed to load settings: {error}"))?;
    let telemetry_handle = engine::telemetry::init(&settings.engine.telemetry);
    let effective_settings = EffectiveRagSettings::try_from_settings(&settings)
        .map_err(|error| format!("invalid RAG configuration: {error}"))?;

    let lancedb_path = parsed
        .lancedb_path
        .clone()
        .unwrap_or_else(|| settings.engine.lancedb_path.clone());

    let collector_reachable = probe_collector_reachable(&settings.engine.telemetry.otlp_endpoint).await;

    let binary_path = std::env::current_exe()
        .map(|p| p.display().to_string())
        .unwrap_or_else(|_| "<unknown>".to_string());
    let binary_mtime_unix_secs = std::env::current_exe()
        .ok()
        .and_then(|p| std::fs::metadata(p).ok())
        .and_then(|m| m.modified().ok())
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs());

    let header = HeaderLine {
        header: true,
        arm: parsed.arm.label(),
        iterations: parsed.iterations,
        graph_timeout_ms: parsed.graph_timeout_ms,
        build_profile: if cfg!(debug_assertions) { "debug" } else { "release" },
        binary_path,
        binary_mtime_unix_secs,
        collector_endpoint: settings.engine.telemetry.otlp_endpoint.clone(),
        collector_reachable,
        seed: SOAK_SEED,
        pid: std::process::id(),
        lancedb_path: lancedb_path.clone(),
        pace_ms: parsed.pace_ms,
        duration_secs: parsed.duration_secs,
        requested_sample_size: parsed.iterations,
    };
    println!(
        "{}",
        serde_json::to_string(&header).map_err(|error| error.to_string())?
    );

    let database = DatabaseManager::open_and_validate(&lancedb_path)
        .await
        .map_err(|error| format!("failed to open LanceDB read-only: {error}"))?;

    let nodes_table = database
        .nodes_table()
        .await
        .map_err(|error| format!("failed to open nodes table: {error}"))?;
    let nodes_version = nodes_table
        .version()
        .await
        .map_err(|error| format!("failed to read nodes version: {error}"))?;
    let bm25_index = Bm25Index::from_table(&nodes_table, effective_settings.retrieval.bm25.clone())
        .await
        .map_err(|error| format!("failed to build BM25 snapshot: {error}"))?;
    let bm25 = Arc::new(bm25_index);
    let generation_label = corpus_generation_from_nodes_version(nodes_version);

    let dense_port: Arc<dyn DenseRetrievalPort> = Arc::new(ProductionDenseRetrievalPort {
        database: database.clone(),
        nodes_version,
        retrieval_settings: effective_settings.retrieval.clone(),
    });
    let bm25_port: Arc<dyn engine::workflow::ports::Bm25RetrievalPort> =
        Arc::new(ProductionBm25RetrievalPort {
            bm25: Arc::clone(&bm25),
            retrieval_settings: effective_settings.retrieval.clone(),
        });

    let rows: Vec<SeedRow> = if parsed.arm.uses_entity_seed() {
        let entities_table = database
            .entities_table()
            .await
            .map_err(|error| format!("failed to open entities table: {error}"))?;
        select_seeded_entity_rows(&entities_table, SOAK_SEED, parsed.iterations).await?
    } else {
        select_seeded_chunk_rows(&nodes_table, SOAK_SEED, parsed.iterations).await?
    };
    if rows.len() < parsed.iterations {
        return Err(format!(
            "seeded sample produced {} rows, fewer than the requested {} iterations",
            rows.len(),
            parsed.iterations
        ));
    }

    let graph_settings = effective_settings.graph.clone();
    let max_prompt_tokens = effective_settings.evidence_token_budget
        + effective_settings.grounding_limits().max_output_tokens() as usize;
    let answer_token_budget = effective_settings.grounding_limits().max_output_tokens() as usize;

    // 06.3.4.1-03 long-duration soak (round 3): the loop's stop condition is either a fixed
    // iteration count (original P0 behaviour, `duration_secs: None`) or wall-clock elapsed time
    // (`--duration-secs`). In duration mode the seeded sample is indexed modulo its length, so a
    // run that outlives its sample cycles back to the start rather than panicking; whether that
    // happened is reported below so a cycled run is never silently mistaken for a fresh-row run.
    let sample_size = rows.len();
    let pace = Duration::from_millis(parsed.pace_ms);
    let run_start = Instant::now();
    let stop_after = parsed.duration_secs.map(Duration::from_secs);
    let mut ordinal: usize = 0;

    loop {
        match stop_after {
            Some(deadline) => {
                if run_start.elapsed() >= deadline {
                    break;
                }
            }
            None => {
                if ordinal >= parsed.iterations {
                    break;
                }
            }
        }
        let row = &rows[ordinal % sample_size];
        ordinal += 1;

        match parsed.arm {
            Arm::W => {
                run_w(
                    ordinal,
                    row,
                    &database,
                    &effective_settings,
                    Arc::clone(&dense_port),
                    Arc::clone(&bm25_port),
                    &generation_label,
                    &nodes_table,
                )
                .await?;
            }
            _ => {
                let line = run_r_rp_rg_rgt(
                    parsed.arm,
                    ordinal,
                    row,
                    Arc::clone(&dense_port),
                    Arc::clone(&bm25_port),
                    &effective_settings.retrieval,
                    &generation_label,
                    &effective_settings.embedding_model,
                    effective_settings.citation_excerpt_max_chars,
                    effective_settings.retrieval.graph_weight,
                    max_prompt_tokens,
                    answer_token_budget,
                    &database,
                    &graph_settings,
                    parsed.graph_timeout_ms,
                    &nodes_table,
                )
                .await;
                println!(
                    "{}",
                    serde_json::to_string(&line).map_err(|error| error.to_string())?
                );
            }
        }

        // `tokio::time::sleep`, not `std::thread::sleep` (M-YIELD-POINTS): a blocking thread
        // sleep would stall a runtime worker and distort the very `alive_tasks`/
        // `global_queue_depth` counters this bin exists to report.
        if parsed.pace_ms > 0 {
            tokio::time::sleep(pace).await;
        }
    }

    let cycles = if sample_size == 0 {
        0
    } else {
        ordinal.div_ceil(sample_size)
    };
    // Summary goes to stderr (tracing), not stdout: the stdout JSONL contract is one header line
    // plus one iteration line per query, consumed as-is by `flatness.records_from_soak_jsonl`
    // (unmodified this round) — a stdout footer line would be misread as a censored iteration.
    tracing::info!(
        arm = parsed.arm.label(),
        total_iterations = ordinal,
        sample_size,
        cycles,
        cycled = cycles > 1,
        elapsed_secs = run_start.elapsed().as_secs_f64(),
        pace_ms = parsed.pace_ms,
        duration_secs = parsed.duration_secs,
        "retrieval_soak_run_complete"
    );

    telemetry_handle.shutdown();
    Ok(())
}
