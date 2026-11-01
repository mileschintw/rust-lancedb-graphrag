//! Loads another writer's recorded extraction answers into a graph table set (#148).
//!
//! The store's own tables are read and never written. The bin creates the set named by
//! `[engine.graph] table_set` (`entities__<set>`, `entity_edges__<set>`), then runs the
//! engine's own graph write path, `ingest::extract_and_persist_entities`, over every document
//! of the store, with the recorded answers in place of live extraction calls. Entity names are
//! embedded with the configured embedding model, as at ingest.
//!
//! Each document's chunks are recomputed from its `documents.raw_content` with the given chunk
//! settings and must equal the store's `nodes` content for that document, chunk for chunk; any
//! difference stops the import before anything is written to the set.
//!
//! ```text
//! LANCET_ENV=<overlay naming lancedb_path and graph.table_set> \
//!   import_graph_extractions --extractions <answers.jsonl> \
//!   --chunk-strategy structure-aware --chunk-size 500 --chunk-overlap 50
//! ```
//!
//! `--check` stops after the counts line (documents, extractable chunks, chunks with a recorded
//! answer) and writes nothing. `--replace` first drops the set's two tables where they exist
//! (a failed import's partial set); without it an existing set is refused.
//!
//! `answers.jsonl` holds one `{"text": <chunk text>, "content": <answer>}` object a line.
//! Needs `OPENROUTER_API_KEY` for the embeddings.

use std::{
    collections::{BTreeMap, HashMap},
    io::BufRead,
    sync::Arc,
};

use arrow_array::{Array, BinaryArray, Int32Array, RecordBatch, StringArray};
use engine::client::{OpenRouterClient, OpenRouterEmbeddingConfig};
use engine::config::{load_settings, EffectiveRagSettings};
use engine::db::{DatabaseManager, GraphTableSet};
use engine::graph::extraction::{RecordedExtractions, MIN_CHUNK_CONTENT_LENGTH};
use engine::ingest::{
    chunk_ingestion_job, extract_and_persist_entities, ChunkSettings, IngestionJob,
};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase};

struct Args {
    extractions: String,
    chunk_settings: ChunkSettings,
    check: bool,
    replace: bool,
}

fn parse_args() -> Result<Args, String> {
    let mut values: HashMap<String, String> = HashMap::new();
    let mut check = false;
    let mut replace = false;
    let mut args = std::env::args().skip(1);
    while let Some(flag) = args.next() {
        let key = match flag.as_str() {
            "--check" => {
                check = true;
                continue;
            }
            "--replace" => {
                replace = true;
                continue;
            }
            "--extractions" | "--chunk-strategy" | "--chunk-size" | "--chunk-overlap" => flag,
            other => return Err(format!("unknown argument: {other}")),
        };
        let value = args
            .next()
            .ok_or_else(|| format!("{key} requires a value"))?;
        values.insert(key, value);
    }
    let take = |key: &str| {
        values
            .get(key)
            .cloned()
            .ok_or_else(|| format!("{key} is required"))
    };
    let number = |key: &str| -> Result<usize, String> {
        take(key)?.parse().map_err(|err| format!("{key}: {err}"))
    };
    Ok(Args {
        extractions: take("--extractions")?,
        chunk_settings: ChunkSettings {
            strategy: take("--chunk-strategy")?,
            size: number("--chunk-size")?,
            overlap: number("--chunk-overlap")?,
        },
        check,
        replace,
    })
}

fn read_extractions(path: &str) -> Result<RecordedExtractions, String> {
    let file = std::fs::File::open(path).map_err(|err| format!("{path}: {err}"))?;
    let mut pairs = Vec::new();
    for (index, line) in std::io::BufReader::new(file).lines().enumerate() {
        let line = line.map_err(|err| format!("{path}: {err}"))?;
        if line.trim().is_empty() {
            continue;
        }
        let value: serde_json::Value = serde_json::from_str(&line)
            .map_err(|err| format!("{path} line {}: {err}", index + 1))?;
        let field = |name: &str| {
            value[name]
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| format!("{path} line {}: no string {name:?}", index + 1))
        };
        pairs.push((field("text")?, field("content")?));
    }
    Ok(RecordedExtractions::new(pairs))
}

async fn batches(
    database: &DatabaseManager,
    table: &str,
    columns: &[&str],
) -> Result<Vec<RecordBatch>, String> {
    let table = match table {
        "documents" => database.documents_table().await?,
        _ => database.nodes_table().await?,
    };
    table
        .query()
        .select(lancedb::query::Select::columns(columns))
        .execute()
        .await
        .map_err(|err| err.to_string())?
        .try_collect()
        .await
        .map_err(|err| err.to_string())
}

fn column<'a, T: 'static>(batch: &'a RecordBatch, name: &str) -> Result<&'a T, String> {
    batch
        .column_by_name(name)
        .and_then(|c| c.as_any().downcast_ref::<T>())
        .ok_or_else(|| format!("column {name} is missing or of another type"))
}

/// Every document's raw content, by document ID (sorted, the ingest replay's order).
async fn documents(database: &DatabaseManager) -> Result<BTreeMap<String, Vec<u8>>, String> {
    let mut out = BTreeMap::new();
    for batch in batches(database, "documents", &["document_id", "raw_content"]).await? {
        let ids = column::<StringArray>(&batch, "document_id")?;
        let raw = column::<BinaryArray>(&batch, "raw_content")?;
        for i in 0..batch.num_rows() {
            out.insert(ids.value(i).to_owned(), raw.value(i).to_vec());
        }
    }
    Ok(out)
}

/// The store's chunk contents per document, in chunk order.
async fn stored_chunks(database: &DatabaseManager) -> Result<HashMap<String, Vec<String>>, String> {
    let mut indexed: HashMap<String, Vec<(i32, String)>> = HashMap::new();
    for batch in batches(
        database,
        "nodes",
        &["document_id", "chunk_index", "content"],
    )
    .await?
    {
        let ids = column::<StringArray>(&batch, "document_id")?;
        let index = column::<Int32Array>(&batch, "chunk_index")?;
        let content = column::<StringArray>(&batch, "content")?;
        for i in 0..batch.num_rows() {
            indexed
                .entry(ids.value(i).to_owned())
                .or_default()
                .push((index.value(i), content.value(i).to_owned()));
        }
    }
    Ok(indexed
        .into_iter()
        .map(|(id, mut chunks)| {
            chunks.sort_by_key(|(index, _)| *index);
            (id, chunks.into_iter().map(|(_, text)| text).collect())
        })
        .collect())
}

async fn row_count(table: lancedb::Table) -> Result<usize, String> {
    table.count_rows(None).await.map_err(|err| err.to_string())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = parse_args()?;
    let settings = load_settings()?;
    let set = GraphTableSet::new(&settings.engine.graph.table_set)?;
    let effective = EffectiveRagSettings::try_from_settings(&settings)
        .map_err(|err| format!("invalid RAG configuration: {err}"))?;
    let api_key = std::env::var("OPENROUTER_API_KEY")
        .map_err(|_| "OPENROUTER_API_KEY must be set for the entity name embeddings")?;
    let embedder = OpenRouterClient::new_with_config(
        api_key,
        OpenRouterEmbeddingConfig::new_with_concurrency(
            effective.embedding_model.clone(),
            effective.embedding_endpoint.clone(),
            effective.embedding_concurrency,
        )?,
    )?;
    let recorded = Arc::new(read_extractions(&args.extractions)?);

    let database = DatabaseManager::open_and_validate(&settings.engine.lancedb_path).await?;
    let documents = documents(&database).await?;
    let stored = stored_chunks(&database).await?;

    // Every check runs before the set is created, so a mismatch writes nothing.
    let mut jobs = Vec::with_capacity(documents.len());
    let (mut extractable, mut answered) = (0usize, 0usize);
    for (document_id, raw) in documents {
        let mut job = IngestionJob::new(
            document_id.clone(),
            "document.md".to_owned(),
            raw,
            HashMap::new(),
        );
        job.chunk_settings = args.chunk_settings.clone();
        let (_, chunks) = chunk_ingestion_job(&job);
        let texts: Vec<&str> = chunks.iter().map(|c| c.content.as_str()).collect();
        let expected: Vec<&str> = stored
            .get(&document_id)
            .map(|v| v.iter().map(String::as_str).collect())
            .unwrap_or_default();
        if texts != expected {
            return Err(format!(
                "document {document_id}: {} recomputed chunks differ from the store's {} \
                 (chunk settings or chunker changed); nothing was written",
                texts.len(),
                expected.len()
            )
            .into());
        }
        for text in texts {
            if text.trim().len() >= MIN_CHUNK_CONTENT_LENGTH {
                extractable += 1;
                answered += usize::from(recorded.contains(text));
            }
        }
        jobs.push(job);
    }
    println!(
        "{} documents, {extractable} extractable chunks, {answered} with a recorded answer, \
         {} recorded answers",
        jobs.len(),
        recorded.len()
    );
    if args.check {
        return Ok(());
    }

    if args.replace {
        database.drop_graph_table_set(&set).await?;
    }
    database.create_graph_table_set(&set).await?;
    let database = database.with_graph_table_set(set.clone()).await?;
    let mut written_edges = 0usize;
    for (index, job) in jobs.iter().enumerate() {
        let summary =
            extract_and_persist_entities(&database, job, recorded.as_ref(), &embedder).await?;
        written_edges += summary.written_entity_edges_count;
        if (index + 1) % 25 == 0 {
            println!("{} of {} documents", index + 1, jobs.len());
        }
    }
    println!(
        "graph table set {}: {} entities, {} entity edges ({written_edges} written)",
        set.name(),
        row_count(database.entities_table().await?).await?,
        row_count(database.entity_edges_table().await?).await?,
    );
    Ok(())
}
