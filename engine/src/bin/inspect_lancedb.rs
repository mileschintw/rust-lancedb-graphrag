use std::collections::{BTreeSet, HashMap, HashSet};
use std::path::{Path, PathBuf};

use arrow_array::{
    Array, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch, StringArray,
};
use engine::db::DatabaseManager;
use engine::graph::escape_sql_literal;
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
    pub max: usize,
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
    pub isolated_entity_count: usize,
    pub highest_degree_entity_id: Option<String>,
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
    if entity_rows > 0 {
        let batches = entities
            .query()
            .select(Select::columns(&["entity_id"]))
            .execute()
            .await
            .map_err(|error| error.to_string())?
            .try_collect::<Vec<RecordBatch>>()
            .await
            .map_err(|error| error.to_string())?;
        for batch in &batches {
            let col = string_column(batch, "entity_id")?;
            for row in 0..batch.num_rows() {
                all_entity_ids.push(col.value(row).to_string());
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

    let (degree_distribution, isolated_entity_count, highest_degree_entity_id) = if entity_rows == 0 {
        (None, 0, None)
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
        let p95 = if n == 1 {
            degrees[0] as f64
        } else {
            let idx = (n - 1) as f64 * 0.95;
            let lower = idx.floor() as usize;
            let upper = idx.ceil() as usize;
            let frac = idx - lower as f64;
            degrees[lower] as f64 * (1.0 - frac) + degrees[upper] as f64 * frac
        };

        all_entity_ids.sort();
        let highest = all_entity_ids
            .iter()
            .max_by_key(|id| (edge_counts.get(*id).copied().unwrap_or(0), std::cmp::Reverse(*id)))
            .cloned();

        (
            Some(DegreeDistribution {
                min,
                median,
                upper_percentile: p95,
                p95,
                max,
            }),
            isolated,
            highest,
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
        isolated_entity_count,
        highest_degree_entity_id,
        unpopulated,
    })
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

/// Classifies one evidence item's gold fact against a document's chunks.
///
/// Tri-state per RESEARCH §E: `in_chunk` when the normalized fact is a substring
/// of a single chunk's normalized content; else `split_across_chunks` when it is
/// contained in the normalized concatenation of two adjacent `chunk_index`
/// chunks; else `absent`. Returns `unmapped_title` when `document_id` is `None`.
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
        let concatenated = format!("{content_a} {content_b}");
        if concatenated.contains(&normalized_fact) {
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

#[derive(Debug, PartialEq, Eq, Clone)]
pub enum InspectMode {
    Document(String),
    GraphPopulation,
    EntityNeighborhood { seed: String, max_hops: u32 },
    EntityName(String),
    GoldChunks { questions: PathBuf, map: PathBuf },
    DocumentIds,
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct InspectConfig {
    pub mode: InspectMode,
    pub lancedb_path: Option<String>,
}

pub const USAGE: &str = "usage: inspect_lancedb [--document-id UUID | --graph-population | --entity UUID [--max-hops N] | --entity-name NAME | --gold-chunks QUESTIONS_JSONL --map DOCUMENT_MAP_JSON | --document-ids] [--lancedb-path PATH]";

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

    let mode_count = (document_id.is_some() as usize)
        + (graph_population as usize)
        + (entity_id.is_some() as usize)
        + (entity_name.is_some() as usize)
        + (gold_chunks_questions.is_some() as usize)
        + (document_ids as usize);

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
    }
    Ok(())
}
