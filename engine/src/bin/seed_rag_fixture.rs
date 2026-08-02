use std::{
    collections::hash_map::DefaultHasher,
    hash::{Hash, Hasher},
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use arrow_array::{
    new_null_array, types::Float32Type, BinaryArray, FixedSizeListArray, Int32Array, Int64Array,
    RecordBatch, StringArray,
};
use engine::db::DatabaseManager;

const EMBEDDING_MODEL: &str = "nvidia/llama-nemotron-embed-vl-1b-v2:free";
const DOCUMENT_ID: &str = "00000000-0000-4000-8000-000000000005";

struct FixtureChunk {
    id: &'static str,
    content: &'static str,
    title: &'static str,
    section: &'static str,
    embedding: f32,
}

const CHUNKS: [FixtureChunk; 3] = [
    FixtureChunk {
        id: "00000000-0000-4000-8000-000000000005:0",
        content: "DENSE_FIXTURE_MARKER: Lancet combines dense retrieval with grounded evidence.",
        title: "Dense retrieval fixture",
        section: "Hybrid retrieval",
        embedding: 1.0,
    },
    FixtureChunk {
        id: "00000000-0000-4000-8000-000000000005:1",
        content: "LEXICAL_FIXTURE_IDENTIFIER_2026: the lexical identifier proves BM25 coverage.",
        title: "Lexical identifier fixture",
        section: "BM25 identifier coverage",
        embedding: 0.0,
    },
    FixtureChunk {
        id: "00000000-0000-4000-8000-000000000005:2",
        content: "CITATION_ORDER_FIXTURE: stable chunk ordering preserves citation provenance.",
        title: "Citation ordering fixture",
        section: "Evidence ordering",
        embedding: 0.0,
    },
];

fn lancedb_path() -> Result<String, String> {
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == "--lancedb-path" {
            return args
                .next()
                .filter(|path| !path.trim().is_empty())
                .ok_or_else(|| "--lancedb-path requires a non-empty path".to_owned());
        }
        return Err(format!("unknown argument: {arg}"));
    }
    Err("usage: seed_rag_fixture --lancedb-path <path>".to_owned())
}

fn content_hash(content: &str) -> String {
    let mut hasher = DefaultHasher::new();
    content.hash(&mut hasher);
    format!("{:016x}", hasher.finish())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = lancedb_path()?;
    let database = DatabaseManager::initialize(&path).await?;
    let documents = database.documents_table().await?;
    let nodes = database.nodes_table().await?;
    let edges = database.edges_table().await?;
    let raw_content = CHUNKS
        .iter()
        .map(|chunk| chunk.content)
        .collect::<Vec<_>>()
        .join("\n");

    documents
        .add(RecordBatch::try_new(
            documents.schema().await?,
            vec![
                Arc::new(StringArray::from(vec![DOCUMENT_ID])),
                Arc::new(BinaryArray::from_vec(vec![raw_content.as_bytes()])),
            ],
        )?)
        .execute()
        .await?;

    let node_schema = nodes.schema().await?;
    let nullable = |name: &str| -> Arc<dyn arrow_array::Array> {
        new_null_array(
            node_schema
                .field_with_name(name)
                .expect("canonical field")
                .data_type(),
            CHUNKS.len(),
        )
    };
    let ingested_at = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as i64;
    let embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        CHUNKS.iter().map(|chunk| {
            Some((0..2048).map(move |index| Some(if index == 0 { chunk.embedding } else { 0.0 })))
        }),
        2048,
    );
    let node_batch = RecordBatch::try_new(
        node_schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![DOCUMENT_ID; CHUNKS.len()])),
            Arc::new(StringArray::from(
                CHUNKS.iter().map(|chunk| chunk.id).collect::<Vec<_>>(),
            )),
            Arc::new(Int32Array::from_iter_values(0..CHUNKS.len() as i32)),
            Arc::new(Int32Array::from(vec![0, 80, 160])),
            Arc::new(Int32Array::from(vec![79, 159, 239])),
            Arc::new(StringArray::from(
                CHUNKS.iter().map(|chunk| chunk.content).collect::<Vec<_>>(),
            )),
            Arc::new(embeddings),
            Arc::new(Int32Array::from(vec![12, 14, 13])),
            Arc::new(StringArray::from(vec!["o200k_base"; CHUNKS.len()])),
            Arc::new(StringArray::from(vec!["1"; CHUNKS.len()])),
            Arc::new(StringArray::from(
                CHUNKS
                    .iter()
                    .map(|chunk| Some(chunk.title))
                    .collect::<Vec<_>>(),
            )),
            Arc::new(StringArray::from(
                CHUNKS
                    .iter()
                    .map(|chunk| Some(chunk.section))
                    .collect::<Vec<_>>(),
            )),
            nullable("page_start"),
            nullable("page_end"),
            Arc::new(StringArray::from(
                CHUNKS
                    .iter()
                    .map(|chunk| Some(content_hash(chunk.content)))
                    .collect::<Vec<_>>(),
            )),
            Arc::new(StringArray::from(vec![Some("1"); CHUNKS.len()])),
            Arc::new(StringArray::from(vec![Some(EMBEDDING_MODEL); CHUNKS.len()])),
            Arc::new(Int64Array::from(vec![Some(ingested_at); CHUNKS.len()])),
            Arc::new(StringArray::from(vec![Some("text/plain"); CHUNKS.len()])),
            nullable("community_ids"),
            nullable("summary"),
            nullable("summary_vector"),
            nullable("unsummarized_refs"),
        ],
    )?;
    nodes.add(node_batch).execute().await?;

    let edge_schema = edges.schema().await?;
    let edge_nullable = |name: &str| -> Arc<dyn arrow_array::Array> {
        new_null_array(
            edge_schema
                .field_with_name(name)
                .expect("canonical field")
                .data_type(),
            2,
        )
    };
    let edge_batch = RecordBatch::try_new(
        edge_schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![
                "00000000-0000-4000-8000-000000000005:edge:0",
                "00000000-0000-4000-8000-000000000005:edge:1",
            ])),
            Arc::new(StringArray::from(vec![CHUNKS[1].id, CHUNKS[2].id])),
            Arc::new(StringArray::from(vec![CHUNKS[0].id, CHUNKS[1].id])),
            Arc::new(StringArray::from(vec!["next_chunk", "next_chunk"])),
            Arc::new(arrow_array::Float32Array::from(vec![1.0, 1.0])),
            Arc::new(StringArray::from(vec![DOCUMENT_ID; 2])),
            edge_nullable("summary"),
            edge_nullable("summary_vector"),
        ],
    )?;
    edges.add(edge_batch).execute().await?;

    drop(edges);
    drop(nodes);
    drop(documents);
    drop(database);
    Ok(())
}
