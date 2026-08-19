use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use arrow_array::{
    builder::{ListBuilder, StringBuilder},
    new_null_array,
    types::Float32Type,
    Array, BinaryArray, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch,
    StringArray,
};
use engine::db::DatabaseManager;
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase};

const EMBEDDING_MODEL: &str = "nvidia/llama-nemotron-embed-vl-1b-v2:free";
const DOCUMENT_ID: &str = "00000000-0000-4000-8000-000000000005";

// GRAPH_SEED_ENTITY_ID = "00000000-0000-4000-8000-000000000101"
const GRAPH_SEED_ENTITY_ID: &str = "00000000-0000-4000-8000-000000000101";
// GRAPH_NEIGHBOR_ENTITY_ID = "00000000-0000-4000-8000-000000000102"
const GRAPH_NEIGHBOR_ENTITY_ID: &str = "00000000-0000-4000-8000-000000000102";
// GRAPH_EDGE_ID = "00000000-0000-4000-8000-000000000103"
const GRAPH_EDGE_ID: &str = "00000000-0000-4000-8000-000000000103";

const GRAPH_FIXTURE_MARKER_SEED: &str = "GRAPH_FIXTURE_MARKER_SEED";
const GRAPH_FIXTURE_MARKER_NEIGHBOR: &str = "GRAPH_FIXTURE_MARKER_NEIGHBOR";
const GRAPH_FIXTURE_MARKER_RELATION: &str = "GRAPH_FIXTURE_MARKER_RELATION";

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
    let mut hasher = blake3::Hasher::new();
    hasher.update(content.as_bytes());
    hasher.finalize().to_hex().to_string()
}

fn dense_score(distance: f32) -> f32 {
    1.0 / (1.0 + distance.max(0.0))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = lancedb_path()?;
    let database = DatabaseManager::initialize(&path).await?;
    let documents = database.documents_table().await?;
    let nodes = database.nodes_table().await?;
    let edges = database.edges_table().await?;
    let entities = database.entities_table().await?;
    let entity_edges = database.entity_edges_table().await?;

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
            Arc::new(Float32Array::from(vec![1.0, 1.0])),
            Arc::new(StringArray::from(vec![DOCUMENT_ID; 2])),
            edge_nullable("summary"),
            edge_nullable("summary_vector"),
        ],
    )?;
    edges.add(edge_batch).execute().await?;

    // Seed entities table
    let entity_schema = entities.schema().await?;
    assert!(entity_schema.field_with_name("entity_id").is_ok());
    assert!(entity_schema.field_with_name("name").is_ok());
    assert!(entity_schema.field_with_name("entity_type").is_ok());
    assert!(entity_schema.field_with_name("name_vector").is_ok());
    assert!(entity_schema.field_with_name("summary").is_ok());
    assert!(entity_schema.field_with_name("summary_vector").is_ok());
    assert!(entity_schema.field_with_name("unsummarized_refs").is_ok());
    assert!(entity_schema.field_with_name("community_ids").is_ok());
    assert!(entity_schema.field_with_name("source_chunk_ids").is_ok());

    let entity_nullable = |name: &str| -> Arc<dyn arrow_array::Array> {
        new_null_array(
            entity_schema
                .field_with_name(name)
                .expect("canonical entity field")
                .data_type(),
            2,
        )
    };
    let entity_embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        (0..2).map(|_| {
            Some((0..2048).map(|index| Some(if index == 0 { 1.0 } else { 0.0 })))
        }),
        2048,
    );

    let mut chunk_ids_builder = ListBuilder::new(StringBuilder::new());
    for _ in 0..2 {
        chunk_ids_builder.values().append_value(CHUNKS[0].id);
        chunk_ids_builder.values().append_value(CHUNKS[1].id);
        chunk_ids_builder.append(true);
    }
    let source_chunk_ids = Arc::new(chunk_ids_builder.finish());

    let entity_batch = RecordBatch::try_new(
        entity_schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![
                GRAPH_SEED_ENTITY_ID,
                GRAPH_NEIGHBOR_ENTITY_ID,
            ])),
            Arc::new(StringArray::from(vec![
                GRAPH_FIXTURE_MARKER_SEED,
                GRAPH_FIXTURE_MARKER_NEIGHBOR,
            ])),
            Arc::new(StringArray::from(vec!["concept", "concept"])),
            Arc::new(entity_embeddings),
            entity_nullable("summary"),
            entity_nullable("summary_vector"),
            entity_nullable("unsummarized_refs"),
            entity_nullable("community_ids"),
            source_chunk_ids,
        ],
    )?;
    entities.add(entity_batch).execute().await?;

    // Seed entity_edges table
    let entity_edge_schema = entity_edges.schema().await?;
    assert!(entity_edge_schema.field_with_name("edge_id").is_ok());
    assert!(entity_edge_schema.field_with_name("source_node_id").is_ok());
    assert!(entity_edge_schema.field_with_name("target_node_id").is_ok());
    assert!(entity_edge_schema.field_with_name("relation_type").is_ok());
    assert!(entity_edge_schema.field_with_name("weight").is_ok());
    assert!(entity_edge_schema.field_with_name("document_id").is_ok());
    assert!(entity_edge_schema.field_with_name("summary").is_ok());
    assert!(entity_edge_schema.field_with_name("summary_vector").is_ok());

    let entity_edge_nullable = |name: &str| -> Arc<dyn arrow_array::Array> {
        new_null_array(
            entity_edge_schema
                .field_with_name(name)
                .expect("canonical entity edge field")
                .data_type(),
            1,
        )
    };
    let entity_edge_batch = RecordBatch::try_new(
        entity_edge_schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![GRAPH_EDGE_ID])),
            Arc::new(StringArray::from(vec![GRAPH_SEED_ENTITY_ID])),
            Arc::new(StringArray::from(vec![GRAPH_NEIGHBOR_ENTITY_ID])),
            Arc::new(StringArray::from(vec![GRAPH_FIXTURE_MARKER_RELATION])),
            Arc::new(Float32Array::from(vec![1.0])),
            Arc::new(StringArray::from(vec![DOCUMENT_ID])),
            entity_edge_nullable("summary"),
            entity_edge_nullable("summary_vector"),
        ],
    )?;
    entity_edges.add(entity_edge_batch).execute().await?;

    // Read back entity and edge rows and assert linkage and dense score
    let mock_vector: Vec<f32> = std::iter::once(1.0f32)
        .chain(std::iter::repeat(0.0f32).take(2047))
        .collect();

    let entity_results = entities
        .query()
        .nearest_to(mock_vector.as_slice())?
        .column("name_vector")
        .limit(2)
        .execute()
        .await?
        .try_collect::<Vec<_>>()
        .await?;
    assert!(!entity_results.is_empty(), "entities table read back empty");
    let total_entities: usize = entity_results.iter().map(|b| b.num_rows()).sum();
    assert_eq!(total_entities, 2, "must find 2 entities");

    let first_batch = &entity_results[0];
    let entity_ids = first_batch
        .column_by_name("entity_id")
        .expect("entity_id column")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("StringArray");
    let entity_names = first_batch
        .column_by_name("name")
        .expect("name column")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("StringArray");
    assert!(
        entity_ids.value(0) == GRAPH_SEED_ENTITY_ID
            || entity_ids.value(0) == GRAPH_NEIGHBOR_ENTITY_ID,
        "unexpected entity id: {}",
        entity_ids.value(0)
    );
    assert!(
        entity_names.value(0) == GRAPH_FIXTURE_MARKER_SEED
            || entity_names.value(0) == GRAPH_FIXTURE_MARKER_NEIGHBOR,
        "unexpected entity name: {}",
        entity_names.value(0)
    );

    let edge_results = entity_edges
        .query()
        .limit(10)
        .execute()
        .await?
        .try_collect::<Vec<_>>()
        .await?;
    assert!(!edge_results.is_empty(), "entity_edges table read back empty");
    let total_edges: usize = edge_results.iter().map(|b| b.num_rows()).sum();
    assert_eq!(total_edges, 1, "must find 1 entity edge");

    let edge_batch_read = &edge_results[0];
    let edge_ids = edge_batch_read
        .column_by_name("edge_id")
        .expect("edge_id column")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("StringArray");
    let source_ids = edge_batch_read
        .column_by_name("source_node_id")
        .expect("source_node_id column")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("StringArray");
    let target_ids = edge_batch_read
        .column_by_name("target_node_id")
        .expect("target_node_id column")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("StringArray");
    let rel_types = edge_batch_read
        .column_by_name("relation_type")
        .expect("relation_type column")
        .as_any()
        .downcast_ref::<StringArray>()
        .expect("StringArray");

    assert_eq!(edge_ids.value(0), GRAPH_EDGE_ID);
    assert_eq!(source_ids.value(0), GRAPH_SEED_ENTITY_ID);
    assert_eq!(target_ids.value(0), GRAPH_NEIGHBOR_ENTITY_ID);
    assert_eq!(rel_types.value(0), GRAPH_FIXTURE_MARKER_RELATION);

    assert_eq!(dense_score(0.0), 1.0);
    assert!(dense_score(0.0) >= 0.5, "dense_score must be at least 0.5");

    drop(entity_edges);
    drop(entities);
    drop(edges);
    drop(nodes);
    drop(documents);
    drop(database);
    Ok(())
}
