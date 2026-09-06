use std::collections::{HashMap, HashSet};

use arrow_array::{
    Array, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch, StringArray,
};
use engine::db::DatabaseManager;
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

#[derive(Debug, PartialEq, Eq, Clone)]
pub enum InspectMode {
    Document(String),
    GraphPopulation,
    EntityNeighborhood { seed: String, max_hops: u32 },
    EntityName(String),
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct InspectConfig {
    pub mode: InspectMode,
    pub lancedb_path: Option<String>,
}

pub const USAGE: &str = "usage: inspect_lancedb [--document-id UUID | --graph-population | --entity UUID [--max-hops N] | --entity-name NAME] [--lancedb-path PATH]";

pub fn parse_args<I: IntoIterator<Item = String>>(args: I) -> Result<InspectConfig, String> {
    let mut iter = args.into_iter();
    let mut document_id = None;
    let mut graph_population = false;
    let mut entity_id = None;
    let mut max_hops = None;
    let mut entity_name = None;
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

    let mode_count = (document_id.is_some() as usize)
        + (graph_population as usize)
        + (entity_id.is_some() as usize)
        + (entity_name.is_some() as usize);

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
    }
    Ok(())
}
