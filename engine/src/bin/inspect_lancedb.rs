use std::collections::{BTreeSet, HashMap, HashSet};
use std::path::{Path, PathBuf};

use arrow_array::{
    Array, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch, StringArray,
};
use engine::db::DatabaseManager;
use engine::graph::escape_sql_literal;
use engine::retrieval::dense::is_valid_chunk_id;
use futures::TryStreamExt;
use lancedb::{
    query::{ExecutableQuery, QueryBase, Select},
    Table,
};
use serde::Serialize;
use uuid::Uuid;

const EMBEDDING_MODEL: &str = "voyageai/voyage-4-large";

#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq)]
pub struct DegreeDistribution {
    pub min: usize,
    pub median: f64,
    pub upper_percentile: f64,
    pub p95: f64,
    /// 99th percentile entity degree, linear-interpolated the same way as `p95`
    /// (RESEARCH's `(n-1)*q` rule): D-77 derives its production traversal caps
    /// from this value, so it must reflect the real sorted-degree vector rather
    /// than being estimated from `p95`/`max` alone.
    pub p99: f64,
    pub max: usize,
}

/// One bucket of a 10-bucket, equal-count (decile) histogram over the sorted
/// entity-degree vector. Equal-width buckets over a heavy-tailed degree
/// distribution (most entities near-isolated, a few hub entities with
/// hundreds of edges) would put nearly every entity in the first bucket;
/// decile buckets instead guarantee a roughly even entity count per row,
/// showing the shape of the tail via each bucket's own `min_degree`/`max_degree`.
#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq)]
pub struct DegreeHistogramBucket {
    /// 0-based decile index (0 = lowest-degree tenth of entities).
    pub index: usize,
    pub count: usize,
    pub min_degree: usize,
    pub max_degree: usize,
}

#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq)]
pub struct GraphPopulationReport {
    pub document_rows: usize,
    pub staged_document_rows: usize,
    pub node_rows: usize,
    pub edge_rows: usize,
    pub entity_rows: usize,
    pub entity_edge_rows: usize,
    pub degree_distribution: Option<DegreeDistribution>,
    /// 10-bucket decile histogram over entity degree, `None` under the same
    /// condition as `degree_distribution` (no entities).
    pub degree_histogram: Option<Vec<DegreeHistogramBucket>>,
    pub isolated_entity_count: usize,
    pub highest_degree_entity_id: Option<String>,
    /// `entities.name` of `highest_degree_entity_id`, resolved from the same
    /// entities read that already fetches `entity_id` (no extra table scan).
    pub highest_degree_entity_name: Option<String>,
    pub unpopulated: bool,
}

#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct NeighborhoodEdge {
    pub edge_id: String,
    pub source_node_id: String,
    pub target_node_id: String,
    pub relation_type: String,
    pub neighbor_id: String,
}

#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq)]
pub struct NeighborhoodReport {
    pub seed_entity_id: String,
    pub status: String,
    pub hop_bound: u32,
    pub edge_count: usize,
    pub edges: Vec<NeighborhoodEdge>,
}

#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct EntityMatch {
    pub entity_id: String,
    pub name: String,
    pub entity_type: String,
}

#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq)]
pub struct EntityNameReport {
    pub queried_name: String,
    pub match_count: usize,
    pub matches: Vec<EntityMatch>,
}

#[derive(Serialize, serde::Deserialize, Debug)]
struct Inspection {
    document_id: String,
    provider: String,
    embedding_model: String,
    document_rows: usize,
    staged_document_rows: usize,
    node_rows: usize,
    edge_rows: usize,
    embedding_width: i32,
    generation_count: usize,
    duplicate_generation: bool,
    stale_generation: bool,
    chunk_indexes_contiguous: bool,
}

#[derive(Debug)]
struct DurableFacts {
    provider: String,
    embedding_model: String,
    node_rows: usize,
    edge_rows: usize,
    embedding_width: i32,
    generation_count: usize,
    duplicate_generation: bool,
    stale_generation: bool,
    chunk_indexes_contiguous: bool,
}

fn string_column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a StringArray, String> {
    batch
        .column_by_name(name)
        .ok_or_else(|| format!("LanceDB query did not return {name}"))?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| format!("LanceDB column {name} has an unexpected type"))
}

fn int32_column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a Int32Array, String> {
    batch
        .column_by_name(name)
        .ok_or_else(|| format!("LanceDB query did not return {name}"))?
        .as_any()
        .downcast_ref::<Int32Array>()
        .ok_or_else(|| format!("LanceDB column {name} has an unexpected type"))
}

fn int64_column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a Int64Array, String> {
    batch
        .column_by_name(name)
        .ok_or_else(|| format!("LanceDB query did not return {name}"))?
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| format!("LanceDB column {name} has an unexpected type"))
}

fn embedding_column<'a>(
    batch: &'a RecordBatch,
    name: &str,
) -> Result<&'a FixedSizeListArray, String> {
    batch
        .column_by_name(name)
        .ok_or_else(|| format!("LanceDB query did not return {name}"))?
        .as_any()
        .downcast_ref::<FixedSizeListArray>()
        .ok_or_else(|| format!("LanceDB column {name} has an unexpected type"))
}

async fn query_columns(
    table: &Table,
    filter: &str,
    columns: &[&str],
) -> Result<Vec<RecordBatch>, String> {
    table
        .query()
        .only_if(filter)
        .select(Select::columns(columns))
        .execute()
        .await
        .map_err(|error| error.to_string())?
        .try_collect()
        .await
        .map_err(|error| error.to_string())
}

fn row_count(batches: &[RecordBatch]) -> usize {
    batches.iter().map(RecordBatch::num_rows).sum()
}

fn derive_durable_facts(
    node_batches: &[RecordBatch],
    edge_batches: &[RecordBatch],
) -> Result<DurableFacts, String> {
    let mut models = HashSet::new();
    let mut generations = HashSet::new();
    let mut chunk_ids = HashSet::new();
    let mut chunk_indexes = HashSet::new();
    let mut embedding_width = None;
    let node_rows = row_count(node_batches);

    if node_rows == 0 {
        return Err("LanceDB inspection found no node rows".to_owned());
    }

    for batch in node_batches {
        let embeddings = embedding_column(batch, "embedding")?;
        if embeddings.null_count() != 0 {
            return Err("LanceDB embedding rows contain null values".to_owned());
        }
        let child_values = embeddings
            .values()
            .as_any()
            .downcast_ref::<Float32Array>()
            .ok_or_else(|| "LanceDB embedding values have unexpected type".to_owned())?;
        if child_values.null_count() != 0 {
            return Err("LanceDB embedding values contain null child values".to_owned());
        }
        for i in 0..child_values.len() {
            if child_values.is_null(i) {
                return Err("LanceDB embedding values contain null child values".to_owned());
            }
            if !child_values.value(i).is_finite() {
                return Err("LanceDB embedding values contain non-finite child values".to_owned());
            }
        }
        let width = embeddings.value_length();
        if width != 2048 {
            return Err(format!(
                "LanceDB persisted embedding width {width}, expected 2048"
            ));
        }
        if let Some(previous) = embedding_width {
            if previous != width {
                return Err("LanceDB embedding widths are inconsistent".to_owned());
            }
        }
        embedding_width = Some(width);

        let model_values = string_column(batch, "embedding_model")?;
        let generation_values = int64_column(batch, "ingested_at")?;
        let chunk_id_values = string_column(batch, "chunk_id")?;
        let chunk_index_values = int32_column(batch, "chunk_index")?;
        for row in 0..batch.num_rows() {
            if model_values.is_null(row) {
                return Err("LanceDB embedding_model is null".to_owned());
            }
            models.insert(model_values.value(row).to_owned());

            if generation_values.is_null(row) {
                return Err("LanceDB ingested_at is null".to_owned());
            }
            generations.insert(generation_values.value(row));

            if chunk_id_values.is_null(row) {
                return Err("LanceDB chunk_id is null".to_owned());
            }
            if !chunk_ids.insert(chunk_id_values.value(row).to_owned()) {
                return Err("LanceDB contains duplicate chunk_id values".to_owned());
            }

            if chunk_index_values.is_null(row) {
                return Err("LanceDB chunk_index is null".to_owned());
            }
            if !chunk_indexes.insert(chunk_index_values.value(row)) {
                return Err("LanceDB contains duplicate chunk_index values".to_owned());
            }
        }
    }

    if models.len() != 1 {
        return Err(format!(
            "LanceDB must contain exactly one embedding_model, found {}",
            models.len()
        ));
    }
    let embedding_model = models
        .into_iter()
        .next()
        .ok_or_else(|| "LanceDB embedding_model could not be derived".to_owned())?;
    let provider = match embedding_model.as_str() {
        EMBEDDING_MODEL => "openrouter".to_owned(),
        _ => return Err("LanceDB contains unknown embedding_model class".to_owned()),
    };

    let generation_count = generations.len();
    let duplicate_generation = generation_count > 1;
    let stale_generation = generation_count > 1;
    if generation_count != 1 {
        return Err(format!(
            "LanceDB must contain exactly one ingested_at generation, found {generation_count}"
        ));
    }

    let expected_indexes = (0..node_rows)
        .map(|index| {
            i32::try_from(index).map_err(|_| "LanceDB node count exceeds int32 range".to_owned())
        })
        .collect::<Result<HashSet<_>, _>>()?;
    let chunk_indexes_contiguous = chunk_indexes == expected_indexes;
    if !chunk_indexes_contiguous {
        return Err("LanceDB chunk_index values are not contiguous from zero".to_owned());
    }

    let mut edge_ids = HashSet::new();
    for batch in edge_batches {
        let edge_id_values = string_column(batch, "edge_id")?;
        let source_values = string_column(batch, "source_node_id")?;
        let target_values = string_column(batch, "target_node_id")?;
        for row in 0..batch.num_rows() {
            if edge_id_values.is_null(row)
                || source_values.is_null(row)
                || target_values.is_null(row)
            {
                return Err("LanceDB edge identity columns contain null values".to_owned());
            }
            if !edge_ids.insert(edge_id_values.value(row).to_owned()) {
                return Err("LanceDB contains duplicate edge_id values".to_owned());
            }
            if !chunk_ids.contains(source_values.value(row))
                || !chunk_ids.contains(target_values.value(row))
            {
                return Err("LanceDB edge endpoint is not a current node".to_owned());
            }
        }
    }

    Ok(DurableFacts {
        provider,
        embedding_model,
        node_rows,
        edge_rows: row_count(edge_batches),
        embedding_width: embedding_width
            .ok_or_else(|| "LanceDB embedding width could not be derived".to_owned())?,
        generation_count,
        duplicate_generation,
        stale_generation,
        chunk_indexes_contiguous,
    })
}

fn settings_path() -> Result<String, String> {
    let base = if std::path::Path::new("../config/config.toml").exists() {
        "../config/config"
    } else {
        "config/config"
    };
    let mut builder = config::Config::builder().add_source(config::File::with_name(base));
    if let Ok(environment) = std::env::var("LANCET_ENV") {
        if !environment.is_empty() {
            builder = builder.add_source(config::File::with_name(&format!("{base}.{environment}")));
        }
    }
    builder
        .add_source(config::Environment::with_prefix("LANCET").separator("__"))
        .build()
        .map_err(|error| error.to_string())?
        .get_string("engine.lancedb_path")
        .map_err(|error| error.to_string())
}

fn predicate(id: &str) -> String {
    format!("document_id = '{}'", id.replace('\'', "''"))
}

async fn inspect_document(
    database: &DatabaseManager,
    document_id: &str,
) -> Result<Inspection, String> {
    let filter = predicate(document_id);
    let documents = database.documents_table().await?;
    let staged = database.staged_documents_table().await?;
    let nodes = database.nodes_table().await?;
    let edges = database.edges_table().await?;
    let document_rows = documents
        .count_rows(Some(filter.clone()))
        .await
        .map_err(|error| error.to_string())?;
    let staged_document_rows = staged
        .count_rows(Some(filter.clone()))
        .await
        .map_err(|error| error.to_string())?;
    if document_rows != 1 || staged_document_rows != 0 {
        return Err("LanceDB document or staging row invariant failed".to_owned());
    }

    let node_batches = query_columns(
        &nodes,
        &filter,
        &[
            "embedding",
            "embedding_model",
            "ingested_at",
            "chunk_id",
            "chunk_index",
        ],
    )
    .await?;
    let edge_batches = query_columns(
        &edges,
        &filter,
        &["edge_id", "source_node_id", "target_node_id"],
    )
    .await?;
    let facts = derive_durable_facts(&node_batches, &edge_batches)?;
    Ok(Inspection {
        document_id: document_id.to_owned(),
        provider: facts.provider,
        embedding_model: facts.embedding_model,
        document_rows,
        staged_document_rows,
        node_rows: facts.node_rows,
        edge_rows: facts.edge_rows,
        embedding_width: facts.embedding_width,
        generation_count: facts.generation_count,
        duplicate_generation: facts.duplicate_generation,
        stale_generation: facts.stale_generation,
        chunk_indexes_contiguous: facts.chunk_indexes_contiguous,
    })
}

pub async fn inspect_graph_population(
    database: &DatabaseManager,
) -> Result<GraphPopulationReport, String> {
    let documents = database.documents_table().await?;
    let staged = database.staged_documents_table().await?;
    let nodes = database.nodes_table().await?;
    let edges = database.edges_table().await?;
    let entities = database.entities_table().await?;
    let entity_edges = database.entity_edges_table().await?;

    let document_rows = documents
        .count_rows(None)
        .await
        .map_err(|error| error.to_string())?;
    let staged_document_rows = staged
        .count_rows(None)
        .await
        .map_err(|error| error.to_string())?;
    let node_rows = nodes
        .count_rows(None)
        .await
        .map_err(|error| error.to_string())?;
    let edge_rows = edges
        .count_rows(None)
        .await
        .map_err(|error| error.to_string())?;
    let entity_rows = entities
        .count_rows(None)
        .await
        .map_err(|error| error.to_string())?;
    let entity_edge_rows = entity_edges
        .count_rows(None)
        .await
        .map_err(|error| error.to_string())?;

    let mut all_entity_ids = Vec::new();
    let mut entity_names: HashMap<String, String> = HashMap::new();
    if entity_rows > 0 {
        let batches = entities
            .query()
            .select(Select::columns(&["entity_id", "name"]))
            .execute()
            .await
            .map_err(|error| error.to_string())?
            .try_collect::<Vec<RecordBatch>>()
            .await
            .map_err(|error| error.to_string())?;
        for batch in &batches {
            let id_col = string_column(batch, "entity_id")?;
            let name_col = string_column(batch, "name")?;
            for row in 0..batch.num_rows() {
                let id = id_col.value(row).to_string();
                entity_names.insert(id.clone(), name_col.value(row).to_string());
                all_entity_ids.push(id);
            }
        }
    }

    let mut edge_counts: HashMap<String, usize> = HashMap::new();
    if entity_edge_rows > 0 {
        let batches = entity_edges
            .query()
            .select(Select::columns(&["source_node_id", "target_node_id"]))
            .execute()
            .await
            .map_err(|error| error.to_string())?
            .try_collect::<Vec<RecordBatch>>()
            .await
            .map_err(|error| error.to_string())?;
        for batch in &batches {
            let src_col = string_column(batch, "source_node_id")?;
            let tgt_col = string_column(batch, "target_node_id")?;
            for row in 0..batch.num_rows() {
                *edge_counts.entry(src_col.value(row).to_string()).or_insert(0) += 1;
                *edge_counts.entry(tgt_col.value(row).to_string()).or_insert(0) += 1;
            }
        }
    }

    let unpopulated = entity_rows == 0 || entity_edge_rows == 0;

    let (
        degree_distribution,
        degree_histogram,
        isolated_entity_count,
        highest_degree_entity_id,
        highest_degree_entity_name,
    ) = if entity_rows == 0 {
        (None, None, 0, None, None)
    } else {
        let mut degrees = Vec::with_capacity(all_entity_ids.len());
        let mut isolated = 0;
        for id in &all_entity_ids {
            let deg = edge_counts.get(id).copied().unwrap_or(0);
            degrees.push(deg);
            if deg == 0 {
                isolated += 1;
            }
        }
        degrees.sort_unstable();
        let min = degrees[0];
        let max = degrees[degrees.len() - 1];
        let n = degrees.len();
        let median = if n % 2 == 1 {
            degrees[n / 2] as f64
        } else {
            (degrees[n / 2 - 1] + degrees[n / 2]) as f64 / 2.0
        };
        let p95 = linear_interpolated_percentile(&degrees, 0.95);
        let p99 = linear_interpolated_percentile(&degrees, 0.99);
        let histogram = decile_histogram(&degrees);

        all_entity_ids.sort();
        let highest = all_entity_ids
            .iter()
            .max_by_key(|id| (edge_counts.get(*id).copied().unwrap_or(0), std::cmp::Reverse(*id)))
            .cloned();
        let highest_name = highest
            .as_ref()
            .and_then(|id| entity_names.get(id))
            .cloned();

        (
            Some(DegreeDistribution {
                min,
                median,
                upper_percentile: p95,
                p95,
                p99,
                max,
            }),
            Some(histogram),
            isolated,
            highest,
            highest_name,
        )
    };

    Ok(GraphPopulationReport {
        document_rows,
        staged_document_rows,
        node_rows,
        edge_rows,
        entity_rows,
        entity_edge_rows,
        degree_distribution,
        degree_histogram,
        isolated_entity_count,
        highest_degree_entity_id,
        highest_degree_entity_name,
        unpopulated,
    })
}

/// Linear-interpolated percentile over an already-sorted slice, using the
/// same `(n-1)*q` rule `inspect_graph_population`'s `p95` has always used.
/// `q` is a fraction in `[0.0, 1.0]` (`0.95` for p95, `0.99` for p99).
fn linear_interpolated_percentile(sorted: &[usize], q: f64) -> f64 {
    if sorted.len() == 1 {
        return sorted[0] as f64;
    }
    let idx = (sorted.len() - 1) as f64 * q;
    let lower = idx.floor() as usize;
    let upper = idx.ceil() as usize;
    let frac = idx - lower as f64;
    sorted[lower] as f64 * (1.0 - frac) + sorted[upper] as f64 * frac
}

/// Splits an already-sorted degree vector into 10 equal-count (decile)
/// buckets rather than 10 equal-width buckets: this codebase's degree
/// distributions are heavy-tailed (thousands of near-isolated entities, a
/// handful of hub entities with hundreds of edges), so equal-width buckets
/// over `0..=max` would put nearly every entity in the first bucket and
/// convey nothing about the tail's shape. Any remainder from `len() % 10` is
/// distributed one-per-bucket to the first buckets, so bucket sizes differ by
/// at most one entity.
fn decile_histogram(sorted: &[usize]) -> Vec<DegreeHistogramBucket> {
    let n = sorted.len();
    let base = n / 10;
    let remainder = n % 10;
    let mut buckets = Vec::with_capacity(10);
    let mut start = 0;
    for index in 0..10 {
        let size = base + usize::from(index < remainder);
        if size == 0 {
            buckets.push(DegreeHistogramBucket {
                index,
                count: 0,
                min_degree: 0,
                max_degree: 0,
            });
            continue;
        }
        let end = start + size;
        buckets.push(DegreeHistogramBucket {
            index,
            count: size,
            min_degree: sorted[start],
            max_degree: sorted[end - 1],
        });
        start = end;
    }
    buckets
}

pub async fn inspect_entity_neighborhood(
    database: &DatabaseManager,
    seed_entity_id: &str,
    hop_bound: u32,
) -> Result<NeighborhoodReport, String> {
    if Uuid::parse_str(seed_entity_id).is_err() {
        return Err(format!(
            "seed entity '{seed_entity_id}' is not a valid UUID; use --entity-name to look up an entity ID by name"
        ));
    }

    if hop_bound == 0 || hop_bound > 3 {
        return Err(format!("max-hops must be between 1 and 3, got {hop_bound}"));
    }

    let entities = database.entities_table().await?;
    let filter = format!("entity_id = '{}'", seed_entity_id.replace('\'', "''"));
    let seed_count = entities
        .count_rows(Some(filter))
        .await
        .map_err(|error| error.to_string())?;

    if seed_count == 0 {
        return Ok(NeighborhoodReport {
            seed_entity_id: seed_entity_id.to_string(),
            status: "absent".to_string(),
            hop_bound,
            edge_count: 0,
            edges: Vec::new(),
        });
    }

    let (_entities_batch, edges_batch) =
        engine::graph::fetch_neighborhood(database, seed_entity_id, hop_bound, true)
            .await
            .map_err(|error| format!("fetch_neighborhood failed: {error}"))?;

    let mut edges = Vec::new();
    if edges_batch.num_rows() > 0 {
        let edge_id_col = string_column(&edges_batch, "edge_id")?;
        let src_col = string_column(&edges_batch, "source_node_id")?;
        let tgt_col = string_column(&edges_batch, "target_node_id")?;
        let rel_col = string_column(&edges_batch, "relation_type")?;

        let mut seen = HashSet::new();
        for row in 0..edges_batch.num_rows() {
            let edge_id = edge_id_col.value(row).to_string();
            if !seen.insert(edge_id.clone()) {
                continue;
            }
            let source_node_id = src_col.value(row).to_string();
            let target_node_id = tgt_col.value(row).to_string();
            let relation_type = rel_col.value(row).to_string();
            let neighbor_id = if source_node_id == seed_entity_id {
                target_node_id.clone()
            } else {
                source_node_id.clone()
            };
            edges.push(NeighborhoodEdge {
                edge_id,
                source_node_id,
                target_node_id,
                relation_type,
                neighbor_id,
            });
        }
    }

    edges.sort_by(|a, b| {
        (&a.neighbor_id, &a.relation_type, &a.edge_id)
            .cmp(&(&b.neighbor_id, &b.relation_type, &b.edge_id))
    });

    let status = if edges.is_empty() {
        "isolated".to_string()
    } else {
        "populated".to_string()
    };

    Ok(NeighborhoodReport {
        seed_entity_id: seed_entity_id.to_string(),
        status,
        hop_bound,
        edge_count: edges.len(),
        edges,
    })
}

pub async fn inspect_entity_name(
    database: &DatabaseManager,
    queried_name: &str,
) -> Result<EntityNameReport, String> {
    let entities = database.entities_table().await?;
    let batches = entities
        .query()
        .select(Select::columns(&["entity_id", "name", "entity_type"]))
        .execute()
        .await
        .map_err(|error| error.to_string())?
        .try_collect::<Vec<RecordBatch>>()
        .await
        .map_err(|error| error.to_string())?;

    let target = queried_name.to_lowercase();
    let mut matches = Vec::new();
    for batch in &batches {
        let id_col = string_column(batch, "entity_id")?;
        let name_col = string_column(batch, "name")?;
        let type_col = string_column(batch, "entity_type")?;
        for row in 0..batch.num_rows() {
            let name_val = name_col.value(row);
            if name_val.to_lowercase() == target {
                matches.push(EntityMatch {
                    entity_id: id_col.value(row).to_string(),
                    name: name_val.to_string(),
                    entity_type: type_col.value(row).to_string(),
                });
            }
        }
    }

    matches.sort_by(|a, b| a.entity_id.cmp(&b.entity_id));

    Ok(EntityNameReport {
        queried_name: queried_name.to_string(),
        match_count: matches.len(),
        matches,
    })
}

/// One `document_map.json` entry, keeping only the `title` field.
///
/// The `aliases` object (if present in the file) is intentionally never parsed
/// here: `--gold-chunks` matches evidence titles against primary map entries
/// only (RESEARCH §E scope for Task 1 of this plan).
#[derive(serde::Deserialize)]
struct DocumentMapEntryRaw {
    #[serde(default)]
    title: String,
}

#[derive(serde::Deserialize)]
struct DocumentMapFileRaw {
    #[serde(default)]
    entries: HashMap<String, DocumentMapEntryRaw>,
}

#[derive(serde::Deserialize)]
struct EvidenceItemRaw {
    #[serde(default)]
    title: String,
    #[serde(default)]
    fact: String,
}

#[derive(serde::Deserialize)]
struct QuestionRaw {
    question_id: String,
    #[serde(default)]
    evidence_list: Vec<EvidenceItemRaw>,
}

/// Per-evidence-item classification of whether a gold fact is present in the
/// live eval LanceDB store, emitted as one JSON line per evidence item by
/// `--gold-chunks` (RESEARCH §E).
#[derive(Serialize, Debug, Clone, PartialEq)]
pub struct GoldChunkRecord {
    pub question_id: String,
    pub evidence_index: usize,
    pub title: String,
    pub document_id: Option<String>,
    pub state: &'static str,
    pub chunk_ids: Vec<String>,
}

/// Collapses whitespace runs and lowercases `text`.
///
/// Mirrors `lancet_eval.metrics.normalize_ws` exactly (`" ".join(text.split()).lower()`
/// in Python) so column (b) classification agrees between this probe and any
/// Python-side recomputation of the same evidence-containment rule.
fn normalize_ws(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

/// Maximum number of `document_id` values per `IN (...)` predicate batch.
///
/// Keeps generated LanceDB/DataFusion predicates from growing unbounded when a
/// large question set references many distinct documents; matches the
/// RESEARCH §E batching note for this probe.
const IN_PREDICATE_BATCH_SIZE: usize = 500;

fn document_id_in_predicate(ids: &[String]) -> String {
    let list = ids
        .iter()
        .map(|id| format!("'{}'", escape_sql_literal(id)))
        .collect::<Vec<_>>()
        .join(", ");
    format!("document_id IN ({list})")
}

/// Merges two adjacent, potentially-overlapping normalized chunk strings into the single
/// contiguous span they represent in the original document.
///
/// Production chunking (`DEFAULT_CHUNK_OVERLAP`) makes adjacent chunks share a trailing/leading
/// span of identical text. A naive `format!("{a} {b}")` join duplicates that shared span (and
/// inserts an artificial space that was never in the source document), so a fact whose true
/// span starts before the overlap and ends after it can never be found as a substring of the
/// naive join — the duplicated overlap plus the inserted space breaks the match (06.3.4.1-09
/// Task 3 regression: this produced 49 false `absent` classifications on the reconciled store,
/// every one of them a genuine cross-chunk split).
///
/// Finds the longest suffix of `a` that equals a prefix of `b` (the duplicated overlap) and
/// removes it from `a` before concatenating directly with the full `b` — no separator is
/// inserted, since the removed suffix is presumed identical to the corresponding prefix of `b`
/// it is being replaced by. Falls back to a single-space join when no such overlap exists (e.g.
/// adjacent chunks with no configured overlap, or a paragraph/heading boundary reset).
///
/// Operates on `char` boundaries throughout, never on raw byte offsets, so a multi-byte UTF-8
/// character in normalized chunk content is never split mid-codepoint.
fn merge_overlapping_chunks(a: &str, b: &str) -> String {
    let a_chars: Vec<char> = a.chars().collect();
    let b_chars: Vec<char> = b.chars().collect();
    let max_overlap = a_chars.len().min(b_chars.len());

    let mut overlap_len = 0;
    for candidate in (1..=max_overlap).rev() {
        if a_chars[a_chars.len() - candidate..] == b_chars[..candidate] {
            overlap_len = candidate;
            break;
        }
    }

    if overlap_len == 0 {
        return format!("{a} {b}");
    }

    let mut merged: String = a_chars[..a_chars.len() - overlap_len].iter().collect();
    merged.push_str(b);
    merged
}

/// Classifies one evidence item's gold fact against a document's chunks.
///
/// Tri-state per RESEARCH §E: `in_chunk` when the normalized fact is a substring
/// of a single chunk's normalized content; else `split_across_chunks` when it is
/// contained in the overlap-aware merge (`merge_overlapping_chunks`) of two
/// adjacent `chunk_index` chunks; else `absent`. Returns `unmapped_title` when
/// `document_id` is `None`.
fn classify_evidence_item(
    fact: &str,
    document_id: Option<&str>,
    chunks_by_document: &HashMap<String, Vec<(i32, String, String)>>,
) -> (&'static str, Vec<String>) {
    let Some(document_id) = document_id else {
        return ("unmapped_title", Vec::new());
    };
    let Some(chunks) = chunks_by_document.get(document_id) else {
        return ("absent", Vec::new());
    };

    let normalized_fact = normalize_ws(fact);

    let mut matching_chunk_ids: Vec<String> = chunks
        .iter()
        .filter(|(_, _, content)| content.contains(&normalized_fact))
        .map(|(_, chunk_id, _)| chunk_id.clone())
        .collect();
    if !matching_chunk_ids.is_empty() {
        matching_chunk_ids.sort();
        return ("in_chunk", matching_chunk_ids);
    }

    for window in chunks.windows(2) {
        let (index_a, _, content_a) = &window[0];
        let (index_b, _, content_b) = &window[1];
        if index_b - index_a != 1 {
            continue;
        }
        let merged = merge_overlapping_chunks(content_a, content_b);
        if merged.contains(&normalized_fact) {
            return ("split_across_chunks", Vec::new());
        }
    }

    ("absent", Vec::new())
}

struct PendingEvidenceItem {
    question_id: String,
    evidence_index: usize,
    title: String,
    document_id: Option<String>,
    fact: String,
}

/// Runs the `--gold-chunks` probe: for every non-empty-fact evidence item across
/// `questions_path`, classifies whether the gold fact is present in the live
/// `nodes` table content for its mapped document.
///
/// Opens no write path: `database` is expected to already be a validated,
/// read-only-use `DatabaseManager` (see `DatabaseManager::open_and_validate`),
/// and this function issues only `query()` calls against `nodes`.
///
/// # Errors
/// Returns an error if either input file cannot be read or parsed, or if a
/// mapped `document_id` is not a valid UUIDv4 — untrusted document-map content
/// is never interpolated into a predicate unvalidated.
pub async fn inspect_gold_chunks(
    database: &DatabaseManager,
    questions_path: &Path,
    map_path: &Path,
) -> Result<Vec<GoldChunkRecord>, String> {
    let map_bytes = std::fs::read_to_string(map_path)
        .map_err(|error| format!("failed to read document map {}: {error}", map_path.display()))?;
    let map_file: DocumentMapFileRaw = serde_json::from_str(&map_bytes)
        .map_err(|error| format!("failed to parse document map {}: {error}", map_path.display()))?;

    let mut title_to_document_id: HashMap<String, String> =
        HashMap::with_capacity(map_file.entries.len());
    for (document_id, entry) in &map_file.entries {
        title_to_document_id.insert(entry.title.clone(), document_id.clone());
    }

    let questions_bytes = std::fs::read_to_string(questions_path).map_err(|error| {
        format!(
            "failed to read questions file {}: {error}",
            questions_path.display()
        )
    })?;

    let mut pending: Vec<PendingEvidenceItem> = Vec::new();
    let mut referenced_document_ids: HashSet<String> = HashSet::new();

    for (line_number, line) in questions_bytes.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let question: QuestionRaw = serde_json::from_str(trimmed).map_err(|error| {
            format!(
                "failed to parse questions file {} at line {}: {error}",
                questions_path.display(),
                line_number + 1
            )
        })?;

        for (evidence_index, item) in question.evidence_list.iter().enumerate() {
            if item.fact.is_empty() {
                continue;
            }
            let document_id = title_to_document_id.get(&item.title).cloned();
            if let Some(id) = &document_id {
                referenced_document_ids.insert(id.clone());
            }
            pending.push(PendingEvidenceItem {
                question_id: question.question_id.clone(),
                evidence_index,
                title: item.title.clone(),
                document_id,
                fact: item.fact.clone(),
            });
        }
    }

    let mut validated_ids: Vec<String> = Vec::with_capacity(referenced_document_ids.len());
    for id in &referenced_document_ids {
        let parsed = Uuid::parse_str(id)
            .map_err(|_| format!("document map entry '{id}' is not a valid UUID"))?;
        if parsed.get_version_num() != 4 {
            return Err(format!("document map entry '{id}' is not a UUIDv4"));
        }
        validated_ids.push(id.clone());
    }
    validated_ids.sort();

    let nodes = database.nodes_table().await?;

    // document_id -> (chunk_index, chunk_id, normalized content), sorted by chunk_index below.
    let mut chunks_by_document: HashMap<String, Vec<(i32, String, String)>> = HashMap::new();

    for batch_ids in validated_ids.chunks(IN_PREDICATE_BATCH_SIZE) {
        let predicate = document_id_in_predicate(batch_ids);
        let batches = query_columns(
            &nodes,
            &predicate,
            &["document_id", "chunk_id", "chunk_index", "content"],
        )
        .await?;
        for batch in &batches {
            let document_id_col = string_column(batch, "document_id")?;
            let chunk_id_col = string_column(batch, "chunk_id")?;
            let chunk_index_col = int32_column(batch, "chunk_index")?;
            let content_col = string_column(batch, "content")?;
            for row in 0..batch.num_rows() {
                let document_id = document_id_col.value(row).to_owned();
                let chunk_id = chunk_id_col.value(row).to_owned();
                let chunk_index = chunk_index_col.value(row);
                let content = normalize_ws(content_col.value(row));
                chunks_by_document
                    .entry(document_id)
                    .or_default()
                    .push((chunk_index, chunk_id, content));
            }
        }
    }
    for chunks in chunks_by_document.values_mut() {
        chunks.sort_by_key(|(chunk_index, _, _)| *chunk_index);
    }

    let mut records = Vec::with_capacity(pending.len());
    for item in pending {
        let (state, chunk_ids) = classify_evidence_item(
            &item.fact,
            item.document_id.as_deref(),
            &chunks_by_document,
        );
        records.push(GoldChunkRecord {
            question_id: item.question_id,
            evidence_index: item.evidence_index,
            title: item.title,
            document_id: item.document_id,
            state,
            chunk_ids,
        });
    }

    records.sort_by(|a, b| {
        (a.question_id.as_str(), a.evidence_index).cmp(&(b.question_id.as_str(), b.evidence_index))
    });

    Ok(records)
}

/// Sorted, de-duplicated `document_id` sets across the four document-linked
/// LanceDB tables, plus the `staged_documents_v2` row count.
///
/// Emitted by `--document-ids` as the JSON contract `eval/src/lancet_eval/identity.py`
/// consumes (`documents, nodes, edges, entity_edges, staged_documents_v2_rows`).
/// `BTreeSet` guarantees sorted, de-duplicated output on serialization.
#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq, Eq, Default)]
pub struct DocumentIdsReport {
    pub documents: BTreeSet<String>,
    pub nodes: BTreeSet<String>,
    pub edges: BTreeSet<String>,
    pub entity_edges: BTreeSet<String>,
    pub staged_documents_v2_rows: usize,
}

/// Collects the distinct, non-null `document_id` values from `table` via a
/// full read-only column scan (`Select::columns(&["document_id"])`).
async fn collect_document_ids(table: &Table) -> Result<BTreeSet<String>, String> {
    let batches = table
        .query()
        .select(Select::columns(&["document_id"]))
        .execute()
        .await
        .map_err(|error| error.to_string())?
        .try_collect::<Vec<RecordBatch>>()
        .await
        .map_err(|error| error.to_string())?;

    let mut ids = BTreeSet::new();
    for batch in &batches {
        let col = string_column(batch, "document_id")?;
        for row in 0..batch.num_rows() {
            if !col.is_null(row) {
                ids.insert(col.value(row).to_owned());
            }
        }
    }
    Ok(ids)
}

/// Runs the `--document-ids` probe: read-only `document_id` sets over
/// `documents`, `nodes`, `edges` and `entity_edges`, plus the
/// `staged_documents_v2` row count (RESEARCH §D `--document-ids` mode).
///
/// # Errors
/// Returns an error if any table cannot be opened or queried.
pub async fn inspect_document_ids(
    database: &DatabaseManager,
) -> Result<DocumentIdsReport, String> {
    let documents = database.documents_table().await?;
    let nodes = database.nodes_table().await?;
    let edges = database.edges_table().await?;
    let entity_edges = database.entity_edges_table().await?;
    let staged = database.staged_documents_table().await?;

    let documents_ids = collect_document_ids(&documents).await?;
    let nodes_ids = collect_document_ids(&nodes).await?;
    let edges_ids = collect_document_ids(&edges).await?;
    let entity_edges_ids = collect_document_ids(&entity_edges).await?;
    let staged_documents_v2_rows = staged
        .count_rows(None)
        .await
        .map_err(|error| error.to_string())?;

    Ok(DocumentIdsReport {
        documents: documents_ids,
        nodes: nodes_ids,
        edges: edges_ids,
        entity_edges: entity_edges_ids,
        staged_documents_v2_rows,
    })
}

/// Columns the `--chunk-text` dump reads from the `nodes` table.
const CHUNK_TEXT_COLUMNS: [&str; 4] = ["chunk_id", "document_id", "chunk_index", "content"];

/// One `--chunk-text` output line: the exact text of a chunk and a digest of it.
///
/// `content_sha256` is the lowercase hex SHA-256 of the UTF-8 bytes of `text`, so a reader can
/// check that the text it holds is the text that was ranked.
#[derive(Serialize, serde::Deserialize, Debug, Clone, PartialEq, Eq)]
pub struct ChunkTextRow {
    pub chunk_id: String,
    pub document_id: String,
    pub chunk_index: i32,
    pub content_sha256: String,
    pub text: String,
}

/// Why a `--chunk-text` run produced no usable output.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ChunkTextFailure {
    /// The ID file is unreadable or holds a malformed line (exit status 2).
    ///
    /// The message names a line number and never the offending text.
    Input(String),
    /// The store, the requested table version or a read failed (exit status 1).
    Store(String),
}

impl std::fmt::Display for ChunkTextFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Input(message) | Self::Store(message) => f.write_str(message),
        }
    }
}

impl ChunkTextFailure {
    /// The process exit status for this failure: 2 for malformed input, 1 otherwise.
    pub fn exit_code(&self) -> i32 {
        match self {
            Self::Input(_) => 2,
            Self::Store(_) => 1,
        }
    }
}

/// What a `--chunk-text` run found at the pinned table version.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChunkTextReport {
    /// How many distinct, valid IDs were asked for.
    pub requested: usize,
    /// The rows that exist at the version, in request order.
    pub rows: Vec<ChunkTextRow>,
}

impl ChunkTextReport {
    /// How many requested IDs have no row at the pinned version.
    pub fn missing_count(&self) -> usize {
        self.requested.saturating_sub(self.rows.len())
    }

    /// The process exit status for a completed read: 3 when any requested ID is missing.
    pub fn exit_code(&self) -> i32 {
        if self.missing_count() > 0 {
            3
        } else {
            0
        }
    }

    /// Counts only, so it can be printed without exposing chunk text or IDs.
    pub fn summary(&self) -> String {
        format!(
            "chunk-text: requested {}, found {}, missing {}",
            self.requested,
            self.rows.len(),
            self.missing_count()
        )
    }
}

/// Parses a corpus generation of the form `lance-<N>` into the nodes-table version `N`.
///
/// `N` must be an unsigned integer in canonical form (no sign, no leading zeros, except `0`
/// itself), which is the only spelling `corpus_generation_from_nodes_version` produces.
///
/// # Errors
/// Returns an error naming the expected form when `generation` is anything else.
pub fn parse_generation(generation: &str) -> Result<u64, String> {
    let invalid = || {
        format!("--generation must be of the form lance-<N>, N an unsigned integer without leading zeros\n{USAGE}")
    };
    let digits = generation.strip_prefix("lance-").ok_or_else(invalid)?;
    let canonical = !digits.is_empty()
        && digits.bytes().all(|byte| byte.is_ascii_digit())
        && (digits == "0" || !digits.starts_with('0'));
    if !canonical {
        return Err(invalid());
    }
    digits.parse::<u64>().map_err(|_| invalid())
}

/// One line of a `--chunk-text` ID file. Other keys on the line are ignored.
#[derive(serde::Deserialize)]
struct ChunkIdLine {
    chunk_id: String,
}

/// Reads the chunk IDs of a JSONL file, one object with a `chunk_id` key per line.
///
/// Blank lines are skipped but still counted in line numbers. An ID is validated with the same
/// rule the retrieval node applies before it builds a predicate, and a repeated ID is kept once at
/// its first position.
///
/// # Errors
/// Returns [`ChunkTextFailure::Input`] when the file cannot be read, when a line is not a JSON
/// object with a string `chunk_id`, when an ID is malformed, or when the file holds no ID. The
/// message names the line number and never the text of the line.
pub fn read_chunk_id_file(path: &Path) -> Result<Vec<String>, ChunkTextFailure> {
    let text = std::fs::read_to_string(path).map_err(|error| {
        ChunkTextFailure::Input(format!(
            "failed to read chunk ID file {}: {error}",
            path.display()
        ))
    })?;
    let mut seen = HashSet::new();
    let mut ids = Vec::new();
    for (index, line) in text.trim_start_matches('\u{feff}').lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let line_number = index + 1;
        let parsed: ChunkIdLine = serde_json::from_str(trimmed).map_err(|_| {
            ChunkTextFailure::Input(format!(
                "chunk ID file line {line_number} is not a JSON object with a string chunk_id"
            ))
        })?;
        if !is_valid_chunk_id(&parsed.chunk_id) {
            return Err(ChunkTextFailure::Input(format!(
                "chunk ID file line {line_number} holds a malformed chunk_id"
            )));
        }
        if seen.insert(parsed.chunk_id.clone()) {
            ids.push(parsed.chunk_id);
        }
    }
    if ids.is_empty() {
        return Err(ChunkTextFailure::Input(
            "chunk ID file holds no chunk IDs".to_owned(),
        ));
    }
    Ok(ids)
}

/// `chunk_id IN (...)` predicates over `ids`, at most [`IN_PREDICATE_BATCH_SIZE`] IDs each.
///
/// Callers validate every ID first; each is also escaped as a SQL literal here.
fn chunk_id_predicates(ids: &[String]) -> Vec<String> {
    ids.chunks(IN_PREDICATE_BATCH_SIZE)
        .map(|batch| {
            let list = batch
                .iter()
                .map(|id| format!("'{}'", escape_sql_literal(id)))
                .collect::<Vec<_>>()
                .join(", ");
            format!("chunk_id IN ({list})")
        })
        .collect()
}

/// Lowercase hex SHA-256 of `data` (FIPS 180-4).
///
/// Written out here so the inspector adds no dependency: the eval side compares this digest with
/// Python's `hashlib.sha256`, and the unit tests pin it to published vectors.
fn sha256_hex(data: &[u8]) -> String {
    const ROUND_CONSTANTS: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let mut state: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];

    // Pad: a 1 bit, zeros up to 56 mod 64 bytes, then the message length in bits, big-endian.
    let mut padded = Vec::with_capacity(data.len() + 72);
    padded.extend_from_slice(data);
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&((data.len() as u64).wrapping_mul(8)).to_be_bytes());

    for block in padded.chunks_exact(64) {
        let mut schedule = [0u32; 64];
        for (word, bytes) in schedule.iter_mut().zip(block.chunks_exact(4)) {
            *word = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
        }
        for index in 16..64 {
            let w15 = schedule[index - 15];
            let w2 = schedule[index - 2];
            let s0 = w15.rotate_right(7) ^ w15.rotate_right(18) ^ (w15 >> 3);
            let s1 = w2.rotate_right(17) ^ w2.rotate_right(19) ^ (w2 >> 10);
            schedule[index] = schedule[index - 16]
                .wrapping_add(s0)
                .wrapping_add(schedule[index - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = state;
        for index in 0..64 {
            let big_s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let choose = (e & f) ^ (!e & g);
            let temp1 = h
                .wrapping_add(big_s1)
                .wrapping_add(choose)
                .wrapping_add(ROUND_CONSTANTS[index])
                .wrapping_add(schedule[index]);
            let big_s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = big_s0.wrapping_add(majority);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        for (slot, value) in state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *slot = slot.wrapping_add(value);
        }
    }
    state.iter().map(|word| format!("{word:08x}")).collect()
}

/// Renders `rows` as JSONL: one object per line, each newline-terminated.
///
/// # Errors
/// Returns an error if a row cannot be serialized.
pub fn render_chunk_text_jsonl(rows: &[ChunkTextRow]) -> Result<String, String> {
    let mut rendered = String::new();
    for row in rows {
        rendered.push_str(&serde_json::to_string(row).map_err(|error| error.to_string())?);
        rendered.push('\n');
    }
    Ok(rendered)
}

/// Reads the text of `ids` from the `nodes` table as it stood at table version `version`.
///
/// The table handle is checked out at `version` before any read, so rows added or replaced
/// afterwards are not seen, and nothing is ever written. IDs are queried in batches of at most
/// [`IN_PREDICATE_BATCH_SIZE`]. The rows come back in the order of `ids`; an ID with no row at the
/// version is simply absent from them (see [`ChunkTextReport::missing_count`]).
///
/// # Errors
/// Returns [`ChunkTextFailure::Input`] if an ID is malformed, and [`ChunkTextFailure::Store`] if
/// the table cannot be opened, the version does not exist, a read fails, or a requested ID has
/// more than one row.
pub async fn inspect_chunk_text(
    database: &DatabaseManager,
    ids: &[String],
    version: u64,
) -> Result<ChunkTextReport, ChunkTextFailure> {
    if ids.iter().any(|id| !is_valid_chunk_id(id)) {
        return Err(ChunkTextFailure::Input(
            "a requested chunk ID is malformed".to_owned(),
        ));
    }
    let nodes = database
        .nodes_table()
        .await
        .map_err(ChunkTextFailure::Store)?;
    nodes.checkout(version).await.map_err(|error| {
        ChunkTextFailure::Store(format!(
            "nodes table version {version} is not available: {error}"
        ))
    })?;

    let mut found: HashMap<String, ChunkTextRow> = HashMap::with_capacity(ids.len());
    for predicate in chunk_id_predicates(ids) {
        let batches = query_columns(&nodes, &predicate, &CHUNK_TEXT_COLUMNS)
            .await
            .map_err(|error| {
                ChunkTextFailure::Store(format!(
                    "failed to read nodes at version {version}: {error}"
                ))
            })?;
        for batch in &batches {
            let chunk_id_col = string_column(batch, "chunk_id").map_err(ChunkTextFailure::Store)?;
            let document_id_col =
                string_column(batch, "document_id").map_err(ChunkTextFailure::Store)?;
            let chunk_index_col =
                int32_column(batch, "chunk_index").map_err(ChunkTextFailure::Store)?;
            let content_col = string_column(batch, "content").map_err(ChunkTextFailure::Store)?;
            for row in 0..batch.num_rows() {
                if content_col.is_null(row) {
                    return Err(ChunkTextFailure::Store(format!(
                        "nodes at version {version} holds a requested chunk with no content"
                    )));
                }
                let content = content_col.value(row);
                let chunk_id = chunk_id_col.value(row).to_owned();
                let entry = ChunkTextRow {
                    chunk_id: chunk_id.clone(),
                    document_id: document_id_col.value(row).to_owned(),
                    chunk_index: chunk_index_col.value(row),
                    content_sha256: sha256_hex(content.as_bytes()),
                    text: content.to_owned(),
                };
                if found.insert(chunk_id, entry).is_some() {
                    return Err(ChunkTextFailure::Store(format!(
                        "nodes at version {version} holds more than one row for a requested chunk"
                    )));
                }
            }
        }
    }

    let rows = ids.iter().filter_map(|id| found.remove(id)).collect();
    Ok(ChunkTextReport {
        requested: ids.len(),
        rows,
    })
}

/// Runs `--chunk-text` end to end and returns the process exit status.
///
/// Input is validated before the store is opened. Exit status: 0 on success, 1 for a store or
/// output failure, 2 for malformed input, 3 when a requested ID has no row at the version (the
/// rows that were found are still written). Chunk text goes to `out` or stdout; stderr carries
/// counts only.
async fn run_chunk_text(
    lancedb_path: &str,
    ids_path: &Path,
    version: u64,
    out: Option<&Path>,
) -> i32 {
    use std::io::Write as _;

    let ids = match read_chunk_id_file(ids_path) {
        Ok(ids) => ids,
        Err(failure) => {
            eprintln!("{failure}");
            return failure.exit_code();
        }
    };
    let database = match DatabaseManager::open_and_validate(lancedb_path).await {
        Ok(database) => database,
        Err(error) => {
            eprintln!("{error}");
            return 1;
        }
    };
    let report = match inspect_chunk_text(&database, &ids, version).await {
        Ok(report) => report,
        Err(failure) => {
            eprintln!("{failure}");
            return failure.exit_code();
        }
    };
    let rendered = match render_chunk_text_jsonl(&report.rows) {
        Ok(rendered) => rendered,
        Err(error) => {
            eprintln!("failed to render chunk text: {error}");
            return 1;
        }
    };
    let written = match out {
        Some(path) => std::fs::write(path, rendered.as_bytes()),
        None => std::io::stdout().lock().write_all(rendered.as_bytes()),
    };
    if let Err(error) = written {
        eprintln!("failed to write chunk text output: {error}");
        return 1;
    }
    eprintln!("{}", report.summary());
    report.exit_code()
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub enum InspectMode {
    Document(String),
    GraphPopulation,
    EntityNeighborhood { seed: String, max_hops: u32 },
    EntityName(String),
    GoldChunks { questions: PathBuf, map: PathBuf },
    DocumentIds,
    ChunkText {
        ids: PathBuf,
        version: u64,
        out: Option<PathBuf>,
    },
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct InspectConfig {
    pub mode: InspectMode,
    pub lancedb_path: Option<String>,
}

pub const USAGE: &str = "usage: inspect_lancedb [--document-id UUID | --graph-population | --entity UUID [--max-hops N] | --entity-name NAME | --gold-chunks QUESTIONS_JSONL --map DOCUMENT_MAP_JSON | --document-ids | --chunk-text IDS_JSONL --generation lance-N [--out PATH]] [--lancedb-path PATH]";

pub fn parse_args<I: IntoIterator<Item = String>>(args: I) -> Result<InspectConfig, String> {
    let mut iter = args.into_iter();
    let mut document_id = None;
    let mut graph_population = false;
    let mut entity_id = None;
    let mut max_hops = None;
    let mut entity_name = None;
    let mut gold_chunks_questions = None;
    let mut gold_chunks_map = None;
    let mut document_ids = false;
    let mut chunk_text = None;
    let mut generation = None;
    let mut out = None;
    let mut lancedb_path = None;

    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--document-id" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--document-id requires a value\n{USAGE}"))?;
                document_id = Some(val);
            }
            "--graph-population" => {
                graph_population = true;
            }
            "--entity" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--entity requires a value\n{USAGE}"))?;
                entity_id = Some(val);
            }
            "--max-hops" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--max-hops requires a value\n{USAGE}"))?;
                let n: u32 = val
                    .parse()
                    .map_err(|_| format!("--max-hops must be an integer\n{USAGE}"))?;
                max_hops = Some(n);
            }
            "--entity-name" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--entity-name requires a value\n{USAGE}"))?;
                entity_name = Some(val);
            }
            "--gold-chunks" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--gold-chunks requires a value\n{USAGE}"))?;
                gold_chunks_questions = Some(val);
            }
            "--map" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--map requires a value\n{USAGE}"))?;
                gold_chunks_map = Some(val);
            }
            "--document-ids" => {
                document_ids = true;
            }
            "--chunk-text" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--chunk-text requires a value\n{USAGE}"))?;
                chunk_text = Some(val);
            }
            "--generation" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--generation requires a value\n{USAGE}"))?;
                generation = Some(val);
            }
            "--out" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--out requires a value\n{USAGE}"))?;
                out = Some(val);
            }
            "--lancedb-path" => {
                let val = iter
                    .next()
                    .ok_or_else(|| format!("--lancedb-path requires a value\n{USAGE}"))?;
                lancedb_path = Some(val);
            }
            _ => {
                return Err(format!("unknown argument '{arg}'\n{USAGE}"));
            }
        }
    }

    if max_hops.is_some() && entity_id.is_none() {
        return Err(format!("--max-hops is only valid with --entity\n{USAGE}"));
    }
    if gold_chunks_map.is_some() && gold_chunks_questions.is_none() {
        return Err(format!("--map is only valid with --gold-chunks\n{USAGE}"));
    }
    if generation.is_some() && chunk_text.is_none() {
        return Err(format!(
            "--generation is only valid with --chunk-text\n{USAGE}"
        ));
    }
    if out.is_some() && chunk_text.is_none() {
        return Err(format!("--out is only valid with --chunk-text\n{USAGE}"));
    }

    let mode_count = (document_id.is_some() as usize)
        + (graph_population as usize)
        + (entity_id.is_some() as usize)
        + (entity_name.is_some() as usize)
        + (gold_chunks_questions.is_some() as usize)
        + (document_ids as usize)
        + (chunk_text.is_some() as usize);

    if mode_count == 0 {
        return Err(format!("no mode specified\n{USAGE}"));
    }
    if mode_count > 1 {
        return Err(format!(
            "multiple modes specified; select exactly one\n{USAGE}"
        ));
    }

    let mode = if let Some(doc_id) = document_id {
        let id = Uuid::parse_str(&doc_id).map_err(|_| "document_id must be a UUID".to_owned())?;
        if id.get_version_num() != 4 {
            return Err("document_id must be a UUIDv4".to_owned());
        }
        InspectMode::Document(doc_id)
    } else if graph_population {
        InspectMode::GraphPopulation
    } else if let Some(seed) = entity_id {
        let hops = max_hops.unwrap_or(1);
        if hops == 0 || hops > 3 {
            return Err(format!("max-hops must be between 1 and 3, got {hops}"));
        }
        InspectMode::EntityNeighborhood {
            seed,
            max_hops: hops,
        }
    } else if let Some(name) = entity_name {
        InspectMode::EntityName(name)
    } else if let Some(questions) = gold_chunks_questions {
        let map = gold_chunks_map
            .ok_or_else(|| format!("--gold-chunks requires --map\n{USAGE}"))?;
        InspectMode::GoldChunks {
            questions: PathBuf::from(questions),
            map: PathBuf::from(map),
        }
    } else if document_ids {
        InspectMode::DocumentIds
    } else if let Some(ids) = chunk_text {
        let generation = generation
            .ok_or_else(|| format!("--chunk-text requires --generation\n{USAGE}"))?;
        InspectMode::ChunkText {
            ids: PathBuf::from(ids),
            version: parse_generation(&generation)?,
            out: out.map(PathBuf::from),
        }
    } else {
        unreachable!();
    };

    Ok(InspectConfig {
        mode,
        lancedb_path,
    })
}

#[cfg(test)]
#[path = "../inspect_lancedb_tests.rs"]
mod tests;

#[tokio::main]
async fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let config = parse_args(args)?;
    let target_path = match config.lancedb_path {
        Some(p) => p,
        None => settings_path()?,
    };
    if let InspectMode::ChunkText { ids, version, out } = &config.mode {
        let status = run_chunk_text(&target_path, ids, *version, out.as_deref()).await;
        if status != 0 {
            std::process::exit(status);
        }
        return Ok(());
    }
    let database = DatabaseManager::open_and_validate(&target_path).await?;
    match config.mode {
        InspectMode::Document(document_id) => {
            let inspection = inspect_document(&database, &document_id).await?;
            println!(
                "{}",
                serde_json::to_string(&inspection).map_err(|error| error.to_string())?
            );
        }
        InspectMode::GraphPopulation => {
            let report = inspect_graph_population(&database).await?;
            println!(
                "{}",
                serde_json::to_string(&report).map_err(|error| error.to_string())?
            );
        }
        InspectMode::EntityNeighborhood { seed, max_hops } => {
            let report = inspect_entity_neighborhood(&database, &seed, max_hops).await?;
            println!(
                "{}",
                serde_json::to_string(&report).map_err(|error| error.to_string())?
            );
        }
        InspectMode::EntityName(name) => {
            let report = inspect_entity_name(&database, &name).await?;
            println!(
                "{}",
                serde_json::to_string(&report).map_err(|error| error.to_string())?
            );
        }
        InspectMode::GoldChunks { questions, map } => {
            let records = inspect_gold_chunks(&database, &questions, &map).await?;
            for record in &records {
                println!(
                    "{}",
                    serde_json::to_string(record).map_err(|error| error.to_string())?
                );
            }
        }
        InspectMode::DocumentIds => {
            let report = inspect_document_ids(&database).await?;
            println!(
                "{}",
                serde_json::to_string(&report).map_err(|error| error.to_string())?
            );
        }
        InspectMode::ChunkText { .. } => {
            unreachable!("--chunk-text returns before the store is opened for the other modes")
        }
    }
    Ok(())
}
