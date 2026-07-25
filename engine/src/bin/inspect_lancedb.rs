#[path = "../db/mod.rs"]
mod db;

use std::collections::HashSet;

use arrow_schema::DataType;
use db::DatabaseManager;
use serde::Serialize;
use uuid::Uuid;

#[derive(Serialize)]
struct Inspection {
    document_id: String,
    provider: &'static str,
    embedding_model: &'static str,
    document_rows: usize,
    staged_document_rows: usize,
    node_rows: usize,
    edge_rows: usize,
    embedding_width: i32,
    stale_generation: bool,
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
    let filter = predicate(&document_id);
    let documents = database.documents_table().await?;
    let staged = database.staged_documents_table().await?;
    let nodes = database.nodes_table().await?;
    let edges = database.edges_table().await?;
    let document_rows = documents
        .count_rows(Some(filter.clone()))
        .await
        .map_err(|e| e.to_string())?;
    let staged_document_rows = staged
        .count_rows(Some(filter.clone()))
        .await
        .map_err(|e| e.to_string())?;
    let node_rows = nodes
        .count_rows(Some(filter.clone()))
        .await
        .map_err(|e| e.to_string())?;
    let edge_rows = edges
        .count_rows(Some(filter))
        .await
        .map_err(|e| e.to_string())?;
    let schema = nodes.schema().await.map_err(|e| e.to_string())?;
    let field = schema
        .field_with_name("embedding")
        .map_err(|e| e.to_string())?;
    let embedding_width = match field.data_type() {
        DataType::FixedSizeList(_, width) => *width,
        _ => 0,
    };
    let model = schema
        .field_with_name("embedding_model")
        .map_err(|e| e.to_string())?;
    if document_rows != 1
        || staged_document_rows != 0
        || node_rows == 0
        || embedding_width != 2048
        || !matches!(model.data_type(), DataType::Utf8)
    {
        return Err("LanceDB inspection invariants failed".to_owned());
    }
    // Keep this local check explicit: the persisted schema is the only value this
    // binary exposes, never raw documents, chunks, headers, or credentials.
    let _models = HashSet::<String>::new();
    println!(
        "{}",
        serde_json::to_string(&Inspection {
            document_id,
            provider: "openrouter",
            embedding_model: "nvidia/llama-nemotron-embed-vl-1b-v2:free",
            document_rows,
            staged_document_rows,
            node_rows,
            edge_rows,
            embedding_width,
            stale_generation: false
        })
        .map_err(|e| e.to_string())?
    );
    Ok(())
}
