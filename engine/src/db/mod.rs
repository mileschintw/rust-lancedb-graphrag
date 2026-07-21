use std::{collections::HashSet, sync::Arc};

use arrow_schema::{DataType, Field, Schema, SchemaRef};
use lancedb::{Connection, Table};

const EMBEDDING_DIMENSIONS: i32 = 2048;

#[derive(Clone)]
pub struct DatabaseManager {
    connection: Connection,
}

impl DatabaseManager {
    pub async fn initialize(path: &str) -> Result<Self, String> {
        let connection = lancedb::connect(path)
            .execute()
            .await
            .map_err(|error| format!("failed to connect to LanceDB at {path}: {error}"))?;
        let manager = Self { connection };
        manager.initialize_tables().await?;
        Ok(manager)
    }

    async fn initialize_tables(&self) -> Result<(), String> {
        let existing = self
            .connection
            .table_names()
            .execute()
            .await
            .map_err(|error| format!("failed to list LanceDB tables: {error}"))?
            .into_iter()
            .collect::<HashSet<_>>();

        for (name, expected) in table_schemas() {
            let table = if existing.contains(name) {
                self.connection
                    .open_table(name)
                    .execute()
                    .await
                    .map_err(|error| format!("failed to open LanceDB table {name}: {error}"))?
            } else {
                self.connection
                    .create_empty_table(name, expected.clone())
                    .execute()
                    .await
                    .map_err(|error| format!("failed to create LanceDB table {name}: {error}"))?
            };
            validate_schema(name, &table, &expected).await?;
        }
        Ok(())
    }

    pub async fn documents_table(&self) -> Result<Table, String> {
        self.connection
            .open_table("documents")
            .execute()
            .await
            .map_err(|error| format!("failed to open LanceDB documents table: {error}"))
    }
}

async fn validate_schema(name: &str, table: &Table, expected: &SchemaRef) -> Result<(), String> {
    let actual = table
        .schema()
        .await
        .map_err(|error| format!("failed to read LanceDB schema for {name}: {error}"))?;
    if actual.fields() != expected.fields() {
        return Err(format!(
            "LanceDB schema drift detected for {name}: expected {:?}, found {:?}",
            expected.fields(),
            actual.fields()
        ));
    }
    Ok(())
}

fn vector() -> DataType {
    DataType::FixedSizeList(
        Arc::new(Field::new("item", DataType::Float32, true)),
        EMBEDDING_DIMENSIONS,
    )
}

fn list(data_type: DataType) -> DataType {
    DataType::List(Arc::new(Field::new("item", data_type, true)))
}

pub fn documents_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("raw_content", DataType::Binary, false),
    ]))
}

pub fn nodes_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("chunk_id", DataType::Utf8, false),
        Field::new("chunk_index", DataType::Int32, false),
        Field::new("char_start", DataType::Int32, false),
        Field::new("char_end", DataType::Int32, false),
        Field::new("content", DataType::Utf8, false),
        Field::new("embedding", vector(), false),
        Field::new("token_estimate", DataType::Int32, false),
        Field::new("token_estimate_scheme", DataType::Utf8, false),
        Field::new("token_estimate_version", DataType::Utf8, false),
        Field::new("title", DataType::Utf8, true),
        Field::new("section_path", DataType::Utf8, true),
        Field::new("page_start", DataType::Int32, true),
        Field::new("page_end", DataType::Int32, true),
        Field::new("content_hash", DataType::Utf8, true),
        Field::new("chunker_version", DataType::Utf8, true),
        Field::new("embedding_model", DataType::Utf8, true),
        Field::new("ingested_at", DataType::Int64, true),
        Field::new("content_type", DataType::Utf8, true),
        Field::new("community_ids", list(DataType::Int32), true),
        Field::new("summary", DataType::Utf8, true),
        Field::new("summary_vector", vector(), true),
        Field::new("unsummarized_refs", list(DataType::Utf8), true),
    ]))
}

pub fn edges_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("edge_id", DataType::Utf8, false),
        Field::new("source_node_id", DataType::Utf8, false),
        Field::new("target_node_id", DataType::Utf8, false),
        Field::new("relation_type", DataType::Utf8, false),
        Field::new("weight", DataType::Float32, false),
        Field::new("document_id", DataType::Utf8, false),
        Field::new("summary", DataType::Utf8, false),
        Field::new("summary_vector", vector(), false),
    ]))
}

pub fn communities_schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("community_id", DataType::Int32, false),
        Field::new("level", DataType::Int32, false),
        Field::new("title", DataType::Utf8, false),
        Field::new("summary", DataType::Utf8, false),
        Field::new("summary_vector", vector(), false),
        Field::new("nodes", list(DataType::Utf8), false),
    ]))
}

fn table_schemas() -> [(&'static str, SchemaRef); 4] {
    [
        ("documents", documents_schema()),
        ("nodes", nodes_schema()),
        ("edges", edges_schema()),
        ("communities", communities_schema()),
    ]
}

#[tonic::async_trait]
pub trait EntityResolver: Send + Sync {
    async fn resolve(
        &self,
        entity: &str,
        known_entities: &[String],
    ) -> Result<Option<String>, String>;
}

#[derive(Debug, Default)]
pub struct ExactMatchResolver;

#[tonic::async_trait]
impl EntityResolver for ExactMatchResolver {
    async fn resolve(
        &self,
        entity: &str,
        known_entities: &[String],
    ) -> Result<Option<String>, String> {
        Ok(known_entities
            .iter()
            .find(|known| known.as_str() == entity)
            .cloned())
    }
}

#[cfg(test)]
mod tests;
