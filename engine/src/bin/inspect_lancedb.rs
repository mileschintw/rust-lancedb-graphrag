#[path = "../db/mod.rs"]
mod db;

use std::collections::HashSet;

use arrow_array::{Array, FixedSizeListArray, Int32Array, Int64Array, RecordBatch, StringArray};
use db::DatabaseManager;
use futures::TryStreamExt;
use lancedb::{
    query::{ExecutableQuery, QueryBase, Select},
    Table,
};
use serde::Serialize;
use uuid::Uuid;

const EMBEDDING_MODEL: &str = "nvidia/llama-nemotron-embed-vl-1b-v2:free";

#[derive(Serialize, Debug)]
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
        other => return Err(format!("LanceDB contains unknown embedding_model {other}")),
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

#[cfg(test)]
#[path = "inspect_lancedb_tests.rs"]
mod tests;

#[tokio::main]
async fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let mut document_id = None;
    let mut path = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--document-id" => document_id = args.next(),
            "--lancedb-path" => path = args.next(),
            _ => {
                return Err(
                    "usage: inspect_lancedb --document-id UUID [--lancedb-path PATH]".to_owned(),
                )
            }
        }
    }
    let document_id = document_id.ok_or_else(|| "--document-id is required".to_owned())?;
    let id = Uuid::parse_str(&document_id).map_err(|_| "document_id must be a UUID".to_owned())?;
    if id.get_version_num() != 4 {
        return Err("document_id must be a UUIDv4".to_owned());
    }
    let database = DatabaseManager::initialize(&path.unwrap_or(settings_path()?)).await?;
    let inspection = inspect_document(&database, &document_id).await?;
    println!(
        "{}",
        serde_json::to_string(&inspection).map_err(|error| error.to_string())?
    );
    Ok(())
}
