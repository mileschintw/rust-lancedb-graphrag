use std::collections::BTreeSet;
use std::sync::Arc;

use arrow_array::builder::{ListBuilder, StringBuilder};
use arrow_array::new_null_array;
use arrow_array::types::Float32Type;
use arrow_array::{
    BinaryArray, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch, StringArray,
};
use uuid::Uuid;

use super::{
    chunk_id_predicates, inspect_chunk_text, inspect_document, inspect_document_ids,
    inspect_entity_name, inspect_entity_neighborhood, inspect_gold_chunks, inspect_graph_dump,
    inspect_graph_population, parse_args, parse_generation, read_chunk_id_file,
    render_chunk_text_jsonl, sha256_hex, ChunkTextFailure, ChunkTextRow, DegreeDistribution,
    DegreeHistogramBucket, DocumentIdsReport, EntityMatch, EntityNameReport, GraphDumpMeta,
    GraphPopulationReport, InspectMode, Inspection, NeighborhoodEdge, NeighborhoodReport,
    EMBEDDING_MODEL, GRAPH_DUMP_EDGES_FILE, GRAPH_DUMP_ENTITIES_FILE, GRAPH_DUMP_META_FILE,
    IN_PREDICATE_BATCH_SIZE,
};
use engine::db::DatabaseManager;

#[derive(Clone)]
struct NodeFixture {
    chunk_id: String,
    chunk_index: i32,
    embedding_model: Option<String>,
    ingested_at: Option<i64>,
    content: String,
}

#[derive(Clone)]
struct EdgeFixture {
    edge_id: String,
    source_node_id: String,
    target_node_id: String,
}

fn valid_nodes(document_id: &str) -> Vec<NodeFixture> {
    (0..3)
        .map(|index| NodeFixture {
            chunk_id: format!("{document_id}:{index}"),
            chunk_index: index,
            embedding_model: Some(EMBEDDING_MODEL.to_owned()),
            ingested_at: Some(42),
            content: "fixture".to_owned(),
        })
        .collect()
}

/// Builds one node per entry in `contents`, at contiguous `chunk_index` 0.., for
/// `--gold-chunks` probe tests that need real, differentiated chunk text.
fn gold_chunk_nodes(document_id: &str, contents: &[&str]) -> Vec<NodeFixture> {
    contents
        .iter()
        .enumerate()
        .map(|(index, content)| NodeFixture {
            chunk_id: format!("{document_id}:{index}"),
            chunk_index: index as i32,
            embedding_model: Some(EMBEDDING_MODEL.to_owned()),
            ingested_at: Some(42),
            content: (*content).to_owned(),
        })
        .collect()
}

fn valid_edges(document_id: &str) -> Vec<EdgeFixture> {
    vec![
        EdgeFixture {
            edge_id: format!("{document_id}:edge:0"),
            source_node_id: format!("{document_id}:1"),
            target_node_id: format!("{document_id}:0"),
        },
        EdgeFixture {
            edge_id: format!("{document_id}:edge:1"),
            source_node_id: format!("{document_id}:2"),
            target_node_id: format!("{document_id}:1"),
        },
    ]
}

fn database_path(test_name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-inspector-{test_name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

/// Appends `nodes`, all belonging to `document_id`, to the `nodes` table as one new version.
async fn add_nodes(database: &DatabaseManager, document_id: &str, nodes: &[NodeFixture]) {
    let node_table = database.nodes_table().await.unwrap();
    let node_schema = node_table.schema().await.unwrap();
    let node_count = nodes.len();
    let nullable = |name: &str| {
        new_null_array(
            node_schema.field_with_name(name).unwrap().data_type(),
            node_count,
        )
    };
    let embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        nodes.iter().map(|_| Some((0..2048).map(|_| Some(0.25)))),
        2048,
    );
    let node_batch = RecordBatch::try_new(
        node_schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![document_id; node_count])),
            Arc::new(StringArray::from(
                nodes
                    .iter()
                    .map(|node| node.chunk_id.as_str())
                    .collect::<Vec<_>>(),
            )),
            Arc::new(Int32Array::from_iter_values(
                nodes.iter().map(|node| node.chunk_index),
            )),
            Arc::new(Int32Array::from_iter_values(
                nodes
                    .iter()
                    .enumerate()
                    .map(|(index, _)| (index * 10) as i32),
            )),
            Arc::new(Int32Array::from_iter_values(
                nodes
                    .iter()
                    .enumerate()
                    .map(|(index, _)| (index * 10 + 9) as i32),
            )),
            Arc::new(StringArray::from(
                nodes
                    .iter()
                    .map(|node| node.content.as_str())
                    .collect::<Vec<_>>(),
            )),
            Arc::new(embeddings),
            Arc::new(Int32Array::from(vec![1; node_count])),
            Arc::new(StringArray::from(vec!["o200k_base"; node_count])),
            Arc::new(StringArray::from(vec!["1"; node_count])),
            nullable("title"),
            nullable("section_path"),
            nullable("page_start"),
            nullable("page_end"),
            nullable("content_hash"),
            nullable("chunker_version"),
            Arc::new(StringArray::from(
                nodes
                    .iter()
                    .map(|node| node.embedding_model.as_deref())
                    .collect::<Vec<_>>(),
            )),
            Arc::new(Int64Array::from(
                nodes
                    .iter()
                    .map(|node| node.ingested_at)
                    .collect::<Vec<_>>(),
            )),
            nullable("content_type"),
        ],
    )
    .unwrap();
    node_table.add(node_batch).execute().await.unwrap();
}

async fn fixture(
    test_name: &str,
    nodes: &[NodeFixture],
    edges: &[EdgeFixture],
) -> (DatabaseManager, String, String) {
    let path = database_path(test_name);
    let document_id = Uuid::new_v4().to_string();
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let documents = database.documents_table().await.unwrap();
    documents
        .add(
            RecordBatch::try_new(
                documents.schema().await.unwrap(),
                vec![
                    Arc::new(StringArray::from(vec![document_id.as_str()])),
                    Arc::new(BinaryArray::from_vec(vec![b"fixture"])),
                ],
            )
            .unwrap(),
        )
        .execute()
        .await
        .unwrap();

    add_nodes(&database, &document_id, nodes).await;

    let edge_table = database.edges_table().await.unwrap();
    let edge_schema = edge_table.schema().await.unwrap();
    let edge_count = edges.len();
    let edge_nullable = |name: &str| {
        new_null_array(
            edge_schema.field_with_name(name).unwrap().data_type(),
            edge_count,
        )
    };
    let edge_batch = RecordBatch::try_new(
        edge_schema.clone(),
        vec![
            Arc::new(StringArray::from(
                edges
                    .iter()
                    .map(|edge| edge.edge_id.as_str())
                    .collect::<Vec<_>>(),
            )),
            Arc::new(StringArray::from(
                edges
                    .iter()
                    .map(|edge| edge.source_node_id.as_str())
                    .collect::<Vec<_>>(),
            )),
            Arc::new(StringArray::from(
                edges
                    .iter()
                    .map(|edge| edge.target_node_id.as_str())
                    .collect::<Vec<_>>(),
            )),
            Arc::new(StringArray::from(vec!["next_chunk"; edge_count])),
            Arc::new(Float32Array::from(vec![1.0; edge_count])),
            Arc::new(StringArray::from(vec![document_id.as_str(); edge_count])),
            edge_nullable("summary"),
            edge_nullable("summary_vector"),
        ],
    )
    .unwrap();
    edge_table.add(edge_batch).execute().await.unwrap();

    (database, path, document_id)
}

async fn assert_rejected(test_name: &str, nodes: Vec<NodeFixture>, edges: Vec<EdgeFixture>) {
    let (database, path, document_id) = fixture(test_name, &nodes, &edges).await;
    let result = inspect_document(&database, &document_id).await;
    assert!(result.is_err());
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn valid_generation_derives_all_inspector_facts() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = valid_nodes(&document_id);
    let edges = valid_edges(&document_id);
    let (database, path, stored_document_id) = fixture("valid", &nodes, &edges).await;

    let inspection: Inspection = inspect_document(&database, &stored_document_id)
        .await
        .unwrap();

    assert_eq!(inspection.provider, "openrouter");
    assert_eq!(inspection.embedding_model, EMBEDDING_MODEL);
    assert_eq!(inspection.document_rows, 1);
    assert_eq!(inspection.staged_document_rows, 0);
    assert_eq!(inspection.node_rows, 3);
    assert_eq!(inspection.edge_rows, 2);
    assert_eq!(inspection.embedding_width, 2048);
    assert_eq!(inspection.generation_count, 1);
    assert!(!inspection.duplicate_generation);
    assert!(!inspection.stale_generation);
    assert!(inspection.chunk_indexes_contiguous);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn mixed_models_fail_closed() {
    let document_id = Uuid::new_v4().to_string();
    let mut nodes = valid_nodes(&document_id);
    nodes[1].embedding_model = Some("other/model".into());
    assert_rejected("mixed-models", nodes, valid_edges(&document_id)).await;
}

#[tokio::test]
async fn missing_model_fails_closed() {
    let document_id = Uuid::new_v4().to_string();
    let mut nodes = valid_nodes(&document_id);
    nodes[1].embedding_model = None;
    assert_rejected("missing-model", nodes, valid_edges(&document_id)).await;
}

#[tokio::test]
async fn multiple_generation_timestamps_fail_closed() {
    let document_id = Uuid::new_v4().to_string();
    let mut nodes = valid_nodes(&document_id);
    nodes[1].ingested_at = Some(43);
    assert_rejected("multiple-generations", nodes, valid_edges(&document_id)).await;
}

#[tokio::test]
async fn duplicate_chunk_id_fails_closed() {
    let document_id = Uuid::new_v4().to_string();
    let mut nodes = valid_nodes(&document_id);
    nodes[1].chunk_id = nodes[0].chunk_id.clone();
    assert_rejected("duplicate-chunk-id", nodes, valid_edges(&document_id)).await;
}

#[tokio::test]
async fn duplicate_chunk_index_fails_closed() {
    let document_id = Uuid::new_v4().to_string();
    let mut nodes = valid_nodes(&document_id);
    nodes[1].chunk_index = nodes[0].chunk_index;
    assert_rejected("duplicate-chunk-index", nodes, valid_edges(&document_id)).await;
}

#[tokio::test]
async fn non_contiguous_chunk_indexes_fail_closed() {
    let document_id = Uuid::new_v4().to_string();
    let mut nodes = valid_nodes(&document_id);
    nodes[1].chunk_index = 3;
    assert_rejected(
        "non-contiguous-chunk-index",
        nodes,
        valid_edges(&document_id),
    )
    .await;
}

#[tokio::test]
async fn duplicate_edge_id_fails_closed() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = valid_nodes(&document_id);
    let mut edges = valid_edges(&document_id);
    edges[1].edge_id = edges[0].edge_id.clone();
    assert_rejected("duplicate-edge-id", nodes, edges).await;
}

#[tokio::test]
async fn stale_edge_endpoint_fails_closed() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = valid_nodes(&document_id);
    let mut edges = valid_edges(&document_id);
    edges[1].target_node_id = format!("{document_id}:stale");
    assert_rejected("stale-edge-endpoint", nodes, edges).await;
}

#[tokio::test]
async fn explicit_path_works_from_configless_working_directory() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = valid_nodes(&document_id);
    let edges = valid_edges(&document_id);
    let (database, path, stored_document_id) = fixture("configless", &nodes, &edges).await;
    drop(database);

    let mut inspector_bin = std::env::current_exe().unwrap();
    inspector_bin.pop();
    if inspector_bin.ends_with("deps") {
        inspector_bin.pop();
    }
    inspector_bin.push("inspect_lancedb");
    if cfg!(windows) {
        inspector_bin.set_extension("exe");
    }
    if !inspector_bin.exists() {
        let status = std::process::Command::new("cargo")
            .args([
                "build",
                "--manifest-path",
                concat!(env!("CARGO_MANIFEST_DIR"), "/Cargo.toml"),
                "--bin",
                "inspect_lancedb",
            ])
            .status()
            .unwrap();
        assert!(status.success(), "cargo build inspect_lancedb failed");
    }
    let temp_dir = std::env::temp_dir().join(format!("configless-workdir-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&temp_dir).unwrap();

    let output = std::process::Command::new(inspector_bin)
        .current_dir(&temp_dir)
        .arg("--document-id")
        .arg(&stored_document_id)
        .arg("--lancedb-path")
        .arg(&path)
        .output()
        .unwrap();

    let _ = std::fs::remove_dir_all(&temp_dir);
    let _ = std::fs::remove_dir_all(&path);

    assert!(
        output.status.success(),
        "inspector failed from config-less dir: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let inspection: Inspection = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(inspection.document_id, stored_document_id);
}

#[tokio::test]
async fn unknown_model_with_sentinel_fails_without_echoing_value() {
    let document_id = Uuid::new_v4().to_string();
    let mut nodes = valid_nodes(&document_id);
    nodes
        .iter_mut()
        .for_each(|n| n.embedding_model = Some("SENTINEL_SECRET_TOKEN_9999".to_string()));
    let (database, path, stored_id) =
        fixture("sentinel-model", &nodes, &valid_edges(&document_id)).await;
    let res = inspect_document(&database, &stored_id).await;
    assert!(res.is_err());
    let err = res.unwrap_err();
    assert!(err.contains("unknown embedding_model class"));
    assert!(!err.contains("SENTINEL_SECRET_TOKEN_9999"));
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn healthy_store_pre_post_inspection_identical() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = valid_nodes(&document_id);
    let edges = valid_edges(&document_id);
    let (database, path, stored_id) = fixture("non-mutation", &nodes, &edges).await;

    let connection = lancedb::connect(&path).execute().await.unwrap();
    let pre_tables = connection.table_names().execute().await.unwrap();
    let pre_doc_rows = database
        .documents_table()
        .await
        .unwrap()
        .count_rows(None)
        .await
        .unwrap();
    let pre_node_rows = database
        .nodes_table()
        .await
        .unwrap()
        .count_rows(None)
        .await
        .unwrap();
    let pre_edge_rows = database
        .edges_table()
        .await
        .unwrap()
        .count_rows(None)
        .await
        .unwrap();

    let _inspection = inspect_document(&database, &stored_id).await.unwrap();

    let post_tables = connection.table_names().execute().await.unwrap();
    let post_doc_rows = database
        .documents_table()
        .await
        .unwrap()
        .count_rows(None)
        .await
        .unwrap();
    let post_node_rows = database
        .nodes_table()
        .await
        .unwrap()
        .count_rows(None)
        .await
        .unwrap();
    let post_edge_rows = database
        .edges_table()
        .await
        .unwrap()
        .count_rows(None)
        .await
        .unwrap();

    assert_eq!(pre_tables, post_tables);
    assert_eq!(pre_doc_rows, post_doc_rows);
    assert_eq!(pre_node_rows, post_node_rows);
    assert_eq!(pre_edge_rows, post_edge_rows);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn missing_required_table_fails_and_remains_absent() {
    let path = database_path("missing-table");
    let connection = lancedb::connect(&path).execute().await.unwrap();
    connection
        .create_empty_table("documents", engine::db::documents_schema())
        .execute()
        .await
        .unwrap();
    connection
        .create_empty_table("staged_documents_v2", engine::db::staged_documents_schema())
        .execute()
        .await
        .unwrap();
    connection
        .create_empty_table("nodes", engine::db::nodes_schema())
        .execute()
        .await
        .unwrap();
    connection
        .create_empty_table("edges", engine::db::edges_schema())
        .execute()
        .await
        .unwrap();

    let pre_tables = connection.table_names().execute().await.unwrap();
    assert!(!pre_tables.contains(&"communities".to_string()));

    let res = DatabaseManager::open_and_validate(&path).await;
    assert!(res.is_err());
    assert!(res
        .err()
        .unwrap()
        .contains("missing required table class: communities"));

    let post_tables = connection.table_names().execute().await.unwrap();
    assert_eq!(pre_tables, post_tables);
    assert!(!post_tables.contains(&"communities".to_string()));

    let _ = std::fs::remove_dir_all(path);
}

async fn test_embedding_child_fixture(
    test_name: &str,
    child_values: Vec<Option<f32>>,
) -> Result<Inspection, String> {
    let path = database_path(test_name);
    let document_id = Uuid::new_v4().to_string();
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let documents = database.documents_table().await.unwrap();
    documents
        .add(
            RecordBatch::try_new(
                documents.schema().await.unwrap(),
                vec![
                    Arc::new(StringArray::from(vec![document_id.as_str()])),
                    Arc::new(BinaryArray::from_vec(vec![b"fixture"])),
                ],
            )
            .unwrap(),
        )
        .execute()
        .await
        .unwrap();

    let node_table = database.nodes_table().await.unwrap();
    let node_schema = node_table.schema().await.unwrap();
    let embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        vec![Some(child_values)],
        2048,
    );

    let nullable =
        |name: &str| new_null_array(node_schema.field_with_name(name).unwrap().data_type(), 1);

    let node_batch = RecordBatch::try_new(
        node_schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![document_id.as_str()])),
            Arc::new(StringArray::from(vec![format!("{document_id}:0")])),
            Arc::new(Int32Array::from(vec![0])),
            Arc::new(Int32Array::from(vec![0])),
            Arc::new(Int32Array::from(vec![9])),
            Arc::new(StringArray::from(vec!["fixture"])),
            Arc::new(embeddings),
            Arc::new(Int32Array::from(vec![1])),
            Arc::new(StringArray::from(vec!["o200k_base"])),
            Arc::new(StringArray::from(vec!["1"])),
            nullable("title"),
            nullable("section_path"),
            nullable("page_start"),
            nullable("page_end"),
            nullable("content_hash"),
            nullable("chunker_version"),
            Arc::new(StringArray::from(vec![Some(EMBEDDING_MODEL)])),
            Arc::new(Int64Array::from(vec![Some(42)])),
            nullable("content_type"),
        ],
    )
    .unwrap();

    if let Err(error) = node_table.add(node_batch).execute().await {
        let _ = std::fs::remove_dir_all(path);
        return Err(format!(
            "LanceDB embedding values contain non-finite child values: {error}"
        ));
    }
    let res = inspect_document(&database, &document_id).await;
    let _ = std::fs::remove_dir_all(path);
    res
}

#[tokio::test]
async fn embedding_child_null_fails_closed() {
    let mut values = vec![Some(0.25f32); 2048];
    values[10] = None;
    let res = test_embedding_child_fixture("child-null", values).await;
    assert!(res.is_err());
    assert!(res.unwrap_err().contains("null child values"));
}

#[tokio::test]
async fn embedding_child_nan_fails_closed() {
    let mut values = vec![Some(0.25f32); 2048];
    values[10] = Some(f32::NAN);
    let res = test_embedding_child_fixture("child-nan", values).await;
    assert!(res.is_err());
    assert!(res.unwrap_err().contains("non-finite child values"));
}

#[tokio::test]
async fn embedding_child_pos_infinity_fails_closed() {
    let mut values = vec![Some(0.25f32); 2048];
    values[10] = Some(f32::INFINITY);
    let res = test_embedding_child_fixture("child-pos-inf", values).await;
    assert!(res.is_err());
    assert!(res.unwrap_err().contains("non-finite child values"));
}

#[tokio::test]
async fn embedding_child_neg_infinity_fails_closed() {
    let mut values = vec![Some(0.25f32); 2048];
    values[10] = Some(f32::NEG_INFINITY);
    let res = test_embedding_child_fixture("child-neg-inf", values).await;
    assert!(res.is_err());
    assert!(res.unwrap_err().contains("non-finite child values"));
}

#[tokio::test]
async fn embedding_child_finite_control_passes() {
    let values = vec![Some(0.25f32); 2048];
    let res = test_embedding_child_fixture("child-finite", values).await;
    assert!(res.is_ok());
}

#[derive(Clone)]
struct EntityFixture {
    entity_id: String,
    name: String,
    entity_type: String,
}

#[derive(Clone)]
struct EntityEdgeFixture {
    edge_id: String,
    source_node_id: String,
    target_node_id: String,
    relation_type: String,
}

async fn graph_fixture(
    test_name: &str,
    entities: &[EntityFixture],
    edges: &[EntityEdgeFixture],
) -> (DatabaseManager, String) {
    let path = database_path(test_name);
    let database = DatabaseManager::initialize(&path).await.unwrap();

    if !entities.is_empty() {
        let entity_table = database.entities_table().await.unwrap();
        let entity_schema = entity_table.schema().await.unwrap();
        let entity_count = entities.len();
        let entity_nullable = |name: &str| {
            new_null_array(
                entity_schema.field_with_name(name).unwrap().data_type(),
                entity_count,
            )
        };
        let name_vectors = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
            (0..entity_count).map(|_| Some((0..2048).map(|_| Some(0.1f32)))),
            2048,
        );
        let mut list_builder = ListBuilder::new(StringBuilder::new());
        for _ in 0..entity_count {
            list_builder.append(true);
        }
        let source_chunk_ids = Arc::new(list_builder.finish());

        let entity_batch = RecordBatch::try_new(
            entity_schema.clone(),
            vec![
                Arc::new(StringArray::from(
                    entities
                        .iter()
                        .map(|e| e.entity_id.as_str())
                        .collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    entities.iter().map(|e| e.name.as_str()).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    entities
                        .iter()
                        .map(|e| e.entity_type.as_str())
                        .collect::<Vec<_>>(),
                )),
                Arc::new(name_vectors),
                entity_nullable("summary"),
                entity_nullable("summary_vector"),
                entity_nullable("unsummarized_refs"),
                entity_nullable("community_ids"),
                source_chunk_ids,
            ],
        )
        .unwrap();
        entity_table.add(entity_batch).execute().await.unwrap();
    }

    if !edges.is_empty() {
        let edge_table = database.entity_edges_table().await.unwrap();
        let edge_schema = edge_table.schema().await.unwrap();
        let edge_count = edges.len();
        let edge_nullable = |name: &str| {
            new_null_array(
                edge_schema.field_with_name(name).unwrap().data_type(),
                edge_count,
            )
        };

        let edge_batch = RecordBatch::try_new(
            edge_schema.clone(),
            vec![
                Arc::new(StringArray::from(
                    edges
                        .iter()
                        .map(|e| e.edge_id.as_str())
                        .collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    edges
                        .iter()
                        .map(|e| e.source_node_id.as_str())
                        .collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    edges
                        .iter()
                        .map(|e| e.target_node_id.as_str())
                        .collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    edges
                        .iter()
                        .map(|e| e.relation_type.as_str())
                        .collect::<Vec<_>>(),
                )),
                Arc::new(Float32Array::from(vec![1.0; edge_count])),
                Arc::new(StringArray::from(vec!["doc:dummy"; edge_count])),
                edge_nullable("summary"),
                edge_nullable("summary_vector"),
            ],
        )
        .unwrap();
        edge_table.add(edge_batch).execute().await.unwrap();
    }

    (database, path)
}

#[tokio::test]
async fn delegation_call_site_and_neighborhood_fetch() {
    let seed_id = Uuid::new_v4().to_string();
    let n1_id = Uuid::new_v4().to_string();
    let n2_id = Uuid::new_v4().to_string();

    let entities = vec![
        EntityFixture {
            entity_id: seed_id.clone(),
            name: "Seed Entity".into(),
            entity_type: "concept".into(),
        },
        EntityFixture {
            entity_id: n1_id.clone(),
            name: "Neighbor 1".into(),
            entity_type: "concept".into(),
        },
        EntityFixture {
            entity_id: n2_id.clone(),
            name: "Neighbor 2".into(),
            entity_type: "concept".into(),
        },
    ];

    let edges = vec![
        EntityEdgeFixture {
            edge_id: Uuid::new_v4().to_string(),
            source_node_id: seed_id.clone(),
            target_node_id: n1_id.clone(),
            relation_type: "relates_to".into(),
        },
        EntityEdgeFixture {
            edge_id: Uuid::new_v4().to_string(),
            source_node_id: n2_id.clone(),
            target_node_id: seed_id.clone(),
            relation_type: "points_to".into(),
        },
    ];

    let (database, path) = graph_fixture("delegation-test", &entities, &edges).await;
    let report = inspect_entity_neighborhood(&database, &seed_id, 1)
        .await
        .unwrap();

    assert_eq!(report.status, "populated");
    assert_eq!(report.edge_count, 2);
    assert_eq!(report.seed_entity_id, seed_id);
    let neighbors: Vec<String> = report.edges.iter().map(|e| e.neighbor_id.clone()).collect();
    assert!(neighbors.contains(&n1_id));
    assert!(neighbors.contains(&n2_id));

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn non_uuid_seed_rejected_with_helpful_message() {
    let (database, path) = graph_fixture("non-uuid-test", &[], &[]).await;
    let res = inspect_entity_neighborhood(&database, "not-a-valid-uuid", 1).await;
    assert!(res.is_err());
    let err = res.unwrap_err();
    assert!(
        err.contains("not-a-valid-uuid"),
        "error message must name the seed"
    );
    assert!(
        err.contains("--entity-name"),
        "error message must point to --entity-name"
    );
    assert!(
        !err.contains("GraphSpikeError"),
        "error message must not contain raw GraphSpikeError"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn entity_name_case_insensitive() {
    let entity_id = Uuid::new_v4().to_string();
    let entities = vec![EntityFixture {
        entity_id: entity_id.clone(),
        name: "Albert Einstein".into(),
        entity_type: "person".into(),
    }];

    let (database, path) = graph_fixture("case-fold-test", &entities, &[]).await;

    let r_lower = inspect_entity_name(&database, "albert einstein")
        .await
        .unwrap();
    let r_upper = inspect_entity_name(&database, "ALBERT EINSTEIN")
        .await
        .unwrap();

    assert_eq!(r_lower.match_count, 1);
    assert_eq!(r_upper.match_count, 1);
    assert_eq!(r_lower.matches[0].entity_id, entity_id);
    assert_eq!(r_upper.matches[0].entity_id, entity_id);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn entity_name_miss_emits_empty_result() {
    let (database, path) = graph_fixture("name-miss-test", &[], &[]).await;
    let report = inspect_entity_name(&database, "Unknown Entity")
        .await
        .unwrap();

    assert_eq!(report.queried_name, "Unknown Entity");
    assert_eq!(report.match_count, 0);
    assert!(report.matches.is_empty());

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn entity_name_ambiguity_emits_all_matches_sorted() {
    let id_a = "00000000-0000-4000-8000-000000000001";
    let id_b = "00000000-0000-4000-8000-000000000002";

    let entities = vec![
        EntityFixture {
            entity_id: id_b.into(),
            name: "John Smith".into(),
            entity_type: "person".into(),
        },
        EntityFixture {
            entity_id: id_a.into(),
            name: "John Smith".into(),
            entity_type: "person".into(),
        },
    ];

    let (database, path) = graph_fixture("ambiguity-test", &entities, &[]).await;
    let report = inspect_entity_name(&database, "john smith").await.unwrap();

    assert_eq!(report.match_count, 2);
    assert_eq!(report.matches[0].entity_id, id_a);
    assert_eq!(report.matches[1].entity_id, id_b);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn empty_store_emits_zero_counts_empty_distribution_unpopulated_marker() {
    let (database, path) = graph_fixture("empty-store-test", &[], &[]).await;
    let report = inspect_graph_population(&database).await.unwrap();

    assert_eq!(report.node_rows, 0);
    assert_eq!(report.edge_rows, 0);
    assert_eq!(report.entity_rows, 0);
    assert_eq!(report.entity_edge_rows, 0);
    assert!(report.degree_distribution.is_none());
    assert_eq!(report.isolated_entity_count, 0);
    assert!(report.unpopulated);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn isolated_entity_counted_in_isolated_total() {
    let seed_id = Uuid::new_v4().to_string();
    let entities = vec![EntityFixture {
        entity_id: seed_id,
        name: "Lonely Node".into(),
        entity_type: "concept".into(),
    }];

    let (database, path) = graph_fixture("isolated-test", &entities, &[]).await;
    let report = inspect_graph_population(&database).await.unwrap();

    assert_eq!(report.entity_rows, 1);
    assert_eq!(report.isolated_entity_count, 1);
    assert!(report.degree_distribution.is_some());
    let dist = report.degree_distribution.unwrap();
    assert_eq!(dist.min, 0);
    assert_eq!(dist.max, 0);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn empty_store_has_no_degree_histogram() {
    let (database, path) = graph_fixture("empty-store-histogram-test", &[], &[]).await;
    let report = inspect_graph_population(&database).await.unwrap();

    assert!(report.degree_histogram.is_none());
    assert!(report.highest_degree_entity_name.is_none());

    let _ = std::fs::remove_dir_all(path);
}

/// A hub-and-spoke fixture (one hub with 9 spokes, each spoke otherwise
/// isolated) exercises the properties the plan's D-77 cap derivation and
/// §4 histogram actually depend on: `p99 >= p95` (both must reflect the same
/// heavy tail, not be independently miscomputed), the histogram partitions
/// every entity exactly once, and the resolved highest-degree name matches
/// the id `highest_degree_entity_id` itself already names.
#[tokio::test]
async fn hub_and_spoke_percentiles_and_histogram_partition_every_entity() {
    let hub_id = Uuid::new_v4().to_string();
    let spoke_ids: Vec<String> = (0..9).map(|_| Uuid::new_v4().to_string()).collect();

    let mut entities = vec![EntityFixture {
        entity_id: hub_id.clone(),
        name: "Hub Entity".into(),
        entity_type: "concept".into(),
    }];
    entities.extend(spoke_ids.iter().enumerate().map(|(i, id)| EntityFixture {
        entity_id: id.clone(),
        name: format!("Spoke {i}"),
        entity_type: "concept".into(),
    }));

    let edges: Vec<EntityEdgeFixture> = spoke_ids
        .iter()
        .map(|spoke_id| EntityEdgeFixture {
            edge_id: Uuid::new_v4().to_string(),
            source_node_id: hub_id.clone(),
            target_node_id: spoke_id.clone(),
            relation_type: "relates_to".into(),
        })
        .collect();

    let (database, path) = graph_fixture("hub-spoke-histogram-test", &entities, &edges).await;
    let report = inspect_graph_population(&database).await.unwrap();

    assert_eq!(report.entity_rows, 10);
    let dist = report.degree_distribution.expect("populated store has a distribution");
    assert_eq!(dist.max, 9, "hub touches all 9 spoke edges");
    assert!(
        dist.p99 >= dist.p95,
        "p99 ({}) must be at least p95 ({}) on the same monotonically sorted degree vector",
        dist.p99,
        dist.p95
    );
    assert!(
        dist.p95 >= dist.median,
        "p95 ({}) must be at least median ({})",
        dist.p95,
        dist.median
    );

    let histogram = report
        .degree_histogram
        .expect("populated store has a histogram");
    assert_eq!(histogram.len(), 10, "always exactly 10 decile buckets");
    let total: usize = histogram.iter().map(|b| b.count).sum();
    assert_eq!(
        total, report.entity_rows,
        "every entity accounted for exactly once across all buckets"
    );
    // The hub is the single highest-degree entity, so it must land in the
    // last non-empty bucket, and that bucket's max must equal dist.max.
    let last_nonempty = histogram
        .iter()
        .rev()
        .find(|b| b.count > 0)
        .expect("at least one non-empty bucket");
    assert_eq!(last_nonempty.max_degree, dist.max);

    assert_eq!(report.highest_degree_entity_id, Some(hub_id.clone()));
    assert_eq!(
        report.highest_degree_entity_name,
        Some("Hub Entity".to_string()),
        "resolved name must belong to the same entity highest_degree_entity_id names"
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn seed_absent_and_seed_isolated_are_distinguishable() {
    let present_id = Uuid::new_v4().to_string();
    let absent_id = Uuid::new_v4().to_string();

    let entities = vec![EntityFixture {
        entity_id: present_id.clone(),
        name: "Present Entity".into(),
        entity_type: "concept".into(),
    }];

    let (database, path) = graph_fixture("absent-isolated-test", &entities, &[]).await;

    let rep_absent = inspect_entity_neighborhood(&database, &absent_id, 1)
        .await
        .unwrap();
    let rep_isolated = inspect_entity_neighborhood(&database, &present_id, 1)
        .await
        .unwrap();

    assert_eq!(rep_absent.status, "absent");
    assert_eq!(rep_absent.seed_entity_id, absent_id);

    assert_eq!(rep_isolated.status, "isolated");
    assert_eq!(rep_isolated.seed_entity_id, present_id);

    assert_ne!(rep_absent.status, rep_isolated.status);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn neighborhood_byte_identical_on_unchanged_fixture() {
    let seed_id = Uuid::new_v4().to_string();
    let n1_id = Uuid::new_v4().to_string();

    let entities = vec![
        EntityFixture {
            entity_id: seed_id.clone(),
            name: "Seed".into(),
            entity_type: "concept".into(),
        },
        EntityFixture {
            entity_id: n1_id.clone(),
            name: "N1".into(),
            entity_type: "concept".into(),
        },
    ];

    let edges = vec![EntityEdgeFixture {
        edge_id: Uuid::new_v4().to_string(),
        source_node_id: seed_id.clone(),
        target_node_id: n1_id.clone(),
        relation_type: "rel".into(),
    }];

    let (database, path) = graph_fixture("byte-identical-test", &entities, &edges).await;

    let rep1 = inspect_entity_neighborhood(&database, &seed_id, 1)
        .await
        .unwrap();
    let rep2 = inspect_entity_neighborhood(&database, &seed_id, 1)
        .await
        .unwrap();

    let json1 = serde_json::to_string(&rep1).unwrap();
    let json2 = serde_json::to_string(&rep2).unwrap();

    assert_eq!(json1, json2);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn raising_hop_bound_never_returns_fewer_edges() {
    let a_id = Uuid::new_v4().to_string();
    let b_id = Uuid::new_v4().to_string();
    let c_id = Uuid::new_v4().to_string();

    let entities = vec![
        EntityFixture {
            entity_id: a_id.clone(),
            name: "A".into(),
            entity_type: "concept".into(),
        },
        EntityFixture {
            entity_id: b_id.clone(),
            name: "B".into(),
            entity_type: "concept".into(),
        },
        EntityFixture {
            entity_id: c_id.clone(),
            name: "C".into(),
            entity_type: "concept".into(),
        },
    ];

    let edges = vec![
        EntityEdgeFixture {
            edge_id: Uuid::new_v4().to_string(),
            source_node_id: a_id.clone(),
            target_node_id: b_id.clone(),
            relation_type: "step1".into(),
        },
        EntityEdgeFixture {
            edge_id: Uuid::new_v4().to_string(),
            source_node_id: b_id.clone(),
            target_node_id: c_id.clone(),
            relation_type: "step2".into(),
        },
    ];

    let (database, path) = graph_fixture("hop-bound-test", &entities, &edges).await;

    let rep_hop1 = inspect_entity_neighborhood(&database, &a_id, 1)
        .await
        .unwrap();
    let rep_hop2 = inspect_entity_neighborhood(&database, &a_id, 2)
        .await
        .unwrap();

    assert!(rep_hop1.edge_count <= rep_hop2.edge_count);
    assert_eq!(rep_hop1.hop_bound, 1);
    assert_eq!(rep_hop2.hop_bound, 2);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn document_scoped_output_unchanged() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = valid_nodes(&document_id);
    let edges = valid_edges(&document_id);
    let (database, path, stored_document_id) = fixture("doc-scoped-unchanged", &nodes, &edges).await;

    let inspection: Inspection = inspect_document(&database, &stored_document_id)
        .await
        .unwrap();

    assert_eq!(inspection.document_id, stored_document_id);
    assert_eq!(inspection.provider, "openrouter");
    assert_eq!(inspection.embedding_model, EMBEDDING_MODEL);
    assert_eq!(inspection.document_rows, 1);
    assert_eq!(inspection.staged_document_rows, 0);
    assert_eq!(inspection.node_rows, 3);
    assert_eq!(inspection.edge_rows, 2);

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn usage_error_when_zero_or_multiple_modes() {
    let res_zero = parse_args(Vec::<String>::new());
    assert!(res_zero.is_err());
    let err0 = res_zero.unwrap_err();
    assert!(err0.contains("--document-id"));
    assert!(err0.contains("--graph-population"));
    assert!(err0.contains("--entity"));
    assert!(err0.contains("--entity-name"));

    let res_multi = parse_args(vec![
        "--graph-population".to_string(),
        "--entity-name".to_string(),
        "Alice".to_string(),
    ]);
    assert!(res_multi.is_err());
    let err_m = res_multi.unwrap_err();
    assert!(err_m.contains("--document-id"));
    assert!(err_m.contains("--graph-population"));
    assert!(err_m.contains("--entity"));
    assert!(err_m.contains("--entity-name"));
}

#[tokio::test]
async fn no_content_or_vector_columns_in_serialized_output() {
    let pop_report = GraphPopulationReport {
        document_rows: 1,
        staged_document_rows: 0,
        node_rows: 3,
        edge_rows: 2,
        entity_rows: 2,
        entity_edge_rows: 1,
        degree_distribution: Some(DegreeDistribution {
            min: 1,
            median: 1.0,
            upper_percentile: 1.0,
            p95: 1.0,
            p99: 1.0,
            max: 1,
        }),
        degree_histogram: Some(vec![DegreeHistogramBucket {
            index: 0,
            count: 2,
            min_degree: 1,
            max_degree: 1,
        }]),
        isolated_entity_count: 0,
        highest_degree_entity_id: Some("00000000-0000-4000-8000-000000000001".into()),
        highest_degree_entity_name: Some("Alice".into()),
        unpopulated: false,
    };

    let neigh_report = NeighborhoodReport {
        seed_entity_id: "00000000-0000-4000-8000-000000000001".into(),
        status: "populated".into(),
        hop_bound: 1,
        edge_count: 1,
        edges: vec![NeighborhoodEdge {
            edge_id: "00000000-0000-4000-8000-000000000003".into(),
            source_node_id: "00000000-0000-4000-8000-000000000001".into(),
            target_node_id: "00000000-0000-4000-8000-000000000002".into(),
            relation_type: "relates_to".into(),
            neighbor_id: "00000000-0000-4000-8000-000000000002".into(),
        }],
    };

    let name_report = EntityNameReport {
        queried_name: "Alice".into(),
        match_count: 1,
        matches: vec![EntityMatch {
            entity_id: "00000000-0000-4000-8000-000000000001".into(),
            name: "Alice".into(),
            entity_type: "person".into(),
        }],
    };

    let forbidden = [
        "raw_content",
        "summary_vector",
        "name_vector",
        "embedding",
        "summary",
        "unsummarized_refs",
        "source_chunk_ids",
    ];

    let json_pop = serde_json::to_string(&pop_report).unwrap();
    let json_neigh = serde_json::to_string(&neigh_report).unwrap();
    let json_name = serde_json::to_string(&name_report).unwrap();

    for f in &forbidden {
        assert!(
            !json_pop.contains(f),
            "pop_report JSON must not contain '{f}': {json_pop}"
        );
        assert!(
            !json_neigh.contains(f),
            "neigh_report JSON must not contain '{f}': {json_neigh}"
        );
        assert!(
            !json_name.contains(f),
            "name_report JSON must not contain '{f}': {json_name}"
        );
    }
}

#[test]
fn normalize_ws_matches_python_rule() {
    // Mirrors `lancet_eval.metrics.normalize_ws`: " ".join(text.split()).lower()
    assert_eq!(super::normalize_ws("  Hello   World  "), "hello world");
    assert_eq!(super::normalize_ws("Tab\tSeparated\nWords"), "tab separated words");
    assert_eq!(super::normalize_ws(""), "");
    assert_eq!(super::normalize_ws("MiXeD Case"), "mixed case");
}

#[test]
fn merge_overlapping_chunks_removes_the_duplicated_overlap_once() {
    // "golf hotel" is the shared (overlapping) suffix/prefix; a naive space-join would
    // duplicate it and insert an artificial space that never existed in the source document.
    let merged =
        super::merge_overlapping_chunks("alpha bravo golf hotel", "golf hotel india juliet");
    assert_eq!(merged, "alpha bravo golf hotel india juliet");
}

#[test]
fn merge_overlapping_chunks_falls_back_to_space_join_without_overlap() {
    let merged = super::merge_overlapping_chunks("alpha bravo", "charlie delta");
    assert_eq!(merged, "alpha bravo charlie delta");
}

#[test]
fn merge_overlapping_chunks_picks_the_longest_matching_overlap() {
    // "b golf hotel" (12 chars) is a longer valid suffix/prefix match than "golf hotel" (10
    // chars) alone; the longest match must win so the merge removes the true full overlap.
    let merged = super::merge_overlapping_chunks(
        "alpha b golf hotel",
        "b golf hotel india juliet",
    );
    assert_eq!(merged, "alpha b golf hotel india juliet");
}

#[tokio::test]
async fn gold_chunks_flags_parse_and_require_pairing() {
    let cfg = parse_args(vec![
        "--gold-chunks".to_string(),
        "questions.jsonl".to_string(),
        "--map".to_string(),
        "map.json".to_string(),
    ])
    .unwrap();
    match cfg.mode {
        super::InspectMode::GoldChunks { questions, map } => {
            assert_eq!(questions, std::path::PathBuf::from("questions.jsonl"));
            assert_eq!(map, std::path::PathBuf::from("map.json"));
        }
        other => panic!("expected GoldChunks mode, got {other:?}"),
    }

    let map_only = parse_args(vec!["--map".to_string(), "map.json".to_string()]);
    assert!(map_only.is_err());
    assert!(map_only
        .unwrap_err()
        .contains("--map is only valid with --gold-chunks"));

    let missing_map = parse_args(vec![
        "--gold-chunks".to_string(),
        "questions.jsonl".to_string(),
    ]);
    assert!(missing_map.is_err());
    assert!(missing_map.unwrap_err().contains("--gold-chunks requires --map"));
}

#[tokio::test]
async fn gold_chunks_probe_classifies_evidence_states() {
    let document_id = Uuid::new_v4().to_string();
    let contents = [
        "Alpha corp shipped their first product in the year twenty twenty",
        "one to great fanfare across the industry",
        "Unrelated filler content chunk three. Product   Widget    Zeta   Released today.",
    ];
    let nodes = gold_chunk_nodes(&document_id, &contents);
    let (database, path, stored_document_id) = fixture("gold-chunks", &nodes, &[]).await;

    let questions_jsonl = serde_json::json!({
        "question_id": "q-1",
        "evidence_list": [
            {"title": "Widget Launch", "fact": "Unrelated filler content"},
            {"title": "Widget Launch", "fact": "twenty twenty one to great fanfare"},
            {"title": "Widget Launch", "fact": "This exact phrase does not exist anywhere"},
            {"title": "Unmapped Article", "fact": "some fact"},
            {"title": "Widget Launch", "fact": "product widget zeta released"},
            {"title": "Widget Launch", "fact": ""}
        ]
    })
    .to_string();

    let map = serde_json::json!({
        "corpus": "test",
        "entries": {
            stored_document_id.clone(): {
                "corpus_id": "widget-launch",
                "document_id": stored_document_id.clone(),
                "title": "Widget Launch",
                "url": "https://example.com"
            }
        },
        "aliases": {
            "some-other-id": stored_document_id.clone()
        }
    });

    let dir = std::env::temp_dir();
    let questions_path = dir.join(format!("gold-chunks-questions-{}.jsonl", Uuid::new_v4()));
    let map_path = dir.join(format!("gold-chunks-map-{}.json", Uuid::new_v4()));
    std::fs::write(&questions_path, &questions_jsonl).unwrap();
    std::fs::write(&map_path, serde_json::to_string(&map).unwrap()).unwrap();

    let records = inspect_gold_chunks(&database, &questions_path, &map_path)
        .await
        .unwrap();

    // The 6th evidence item has an empty fact and is skipped entirely.
    assert_eq!(records.len(), 5);

    assert_eq!(records[0].question_id, "q-1");
    assert_eq!(records[0].evidence_index, 0);
    assert_eq!(records[0].state, "in_chunk");
    assert_eq!(
        records[0].document_id.as_deref(),
        Some(stored_document_id.as_str())
    );
    assert_eq!(records[0].chunk_ids, vec![format!("{document_id}:2")]);

    assert_eq!(records[1].evidence_index, 1);
    assert_eq!(records[1].state, "split_across_chunks");
    assert!(records[1].chunk_ids.is_empty());

    assert_eq!(records[2].evidence_index, 2);
    assert_eq!(records[2].state, "absent");
    assert!(records[2].chunk_ids.is_empty());

    assert_eq!(records[3].evidence_index, 3);
    assert_eq!(records[3].state, "unmapped_title");
    assert_eq!(records[3].document_id, None);
    assert!(records[3].chunk_ids.is_empty());

    // Whitespace/case rule: fact normalized differently from stored content, still matches.
    assert_eq!(records[4].evidence_index, 4);
    assert_eq!(records[4].state, "in_chunk");
    assert_eq!(records[4].chunk_ids, vec![format!("{document_id}:2")]);

    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_file(&questions_path);
    let _ = std::fs::remove_file(&map_path);
}

#[tokio::test]
async fn gold_chunks_probe_split_across_chunks_crossing_the_overlap_boundary() {
    // Regression (06.3.4.1-09 Task 3): `classify_evidence_item`'s adjacent-window check used to
    // naive-space-join two overlapping chunks (`format!("{a} {b}")`), duplicating the shared
    // overlap region and inserting an artificial space that never existed in the source
    // document. A fact whose true span starts before the overlap and ends after it could then
    // never be found as a substring of that naive join, and was misclassified `absent` instead
    // of `split_across_chunks` -- exactly the bug that produced 49 false `absent` states on the
    // reconciled live store. These two synthetic chunks share the overlapping "golf hotel" span,
    // mirroring production's `DEFAULT_CHUNK_OVERLAP`-sized shared text between adjacent chunks.
    let document_id = Uuid::new_v4().to_string();
    let contents = [
        "alpha bravo charlie delta echo foxtrot golf hotel",
        "golf hotel india juliet kilo lima mike november",
    ];
    let nodes = gold_chunk_nodes(&document_id, &contents);
    let (database, path, stored_document_id) = fixture("gold-chunks-overlap", &nodes, &[]).await;

    let questions_jsonl = serde_json::json!({
        "question_id": "q-overlap",
        "evidence_list": [
            {"title": "Overlap Article", "fact": "delta echo foxtrot golf hotel india juliet"}
        ]
    })
    .to_string();

    let map = serde_json::json!({
        "corpus": "test",
        "entries": {
            stored_document_id.clone(): {
                "corpus_id": "overlap-article",
                "document_id": stored_document_id.clone(),
                "title": "Overlap Article",
                "url": "https://example.com"
            }
        }
    });

    let dir = std::env::temp_dir();
    let questions_path = dir.join(format!("gold-chunks-overlap-questions-{}.jsonl", Uuid::new_v4()));
    let map_path = dir.join(format!("gold-chunks-overlap-map-{}.json", Uuid::new_v4()));
    std::fs::write(&questions_path, &questions_jsonl).unwrap();
    std::fs::write(&map_path, serde_json::to_string(&map).unwrap()).unwrap();

    let records = inspect_gold_chunks(&database, &questions_path, &map_path)
        .await
        .unwrap();

    assert_eq!(records.len(), 1);
    assert_eq!(
        records[0].state, "split_across_chunks",
        "a fact crossing the overlap boundary must be split_across_chunks, not absent"
    );
    assert!(records[0].chunk_ids.is_empty());

    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_file(&questions_path);
    let _ = std::fs::remove_file(&map_path);
}

#[tokio::test]
async fn gold_chunks_probe_rejects_non_uuid_document_id() {
    let document_id = Uuid::new_v4().to_string();
    let contents = ["Alpha content chunk zero."];
    let nodes = gold_chunk_nodes(&document_id, &contents);
    let (database, path, _stored_document_id) = fixture("gold-chunks-bad-uuid", &nodes, &[]).await;

    let questions_jsonl = serde_json::json!({
        "question_id": "q-1",
        "evidence_list": [{"title": "Doc Title", "fact": "Alpha content chunk zero"}]
    })
    .to_string();
    let map = serde_json::json!({
        "corpus": "test",
        "entries": {
            "not-a-uuid": {
                "corpus_id": "doc-title",
                "document_id": "not-a-uuid",
                "title": "Doc Title",
                "url": ""
            }
        }
    });

    let dir = std::env::temp_dir();
    let questions_path = dir.join(format!("gold-chunks-bad-uuid-questions-{}.jsonl", Uuid::new_v4()));
    let map_path = dir.join(format!("gold-chunks-bad-uuid-map-{}.json", Uuid::new_v4()));
    std::fs::write(&questions_path, &questions_jsonl).unwrap();
    std::fs::write(&map_path, serde_json::to_string(&map).unwrap()).unwrap();

    let result = inspect_gold_chunks(&database, &questions_path, &map_path).await;
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("not a valid UUID"));

    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_file(&questions_path);
    let _ = std::fs::remove_file(&map_path);
}

#[tokio::test]
async fn gold_chunks_probe_does_not_mutate_table_versions() {
    let document_id = Uuid::new_v4().to_string();
    let contents = ["Alpha content chunk zero.", "Beta content chunk one."];
    let nodes = gold_chunk_nodes(&document_id, &contents);
    let (database, path, stored_document_id) = fixture("gold-chunks-versions", &nodes, &[]).await;

    let questions_jsonl = serde_json::json!({
        "question_id": "q-1",
        "evidence_list": [{"title": "Doc Title", "fact": "Alpha content chunk zero"}]
    })
    .to_string();
    let map = serde_json::json!({
        "corpus": "test",
        "entries": {
            stored_document_id.clone(): {
                "corpus_id": "doc-title",
                "document_id": stored_document_id.clone(),
                "title": "Doc Title",
                "url": ""
            }
        }
    });

    let dir = std::env::temp_dir();
    let questions_path = dir.join(format!("gold-chunks-versions-questions-{}.jsonl", Uuid::new_v4()));
    let map_path = dir.join(format!("gold-chunks-versions-map-{}.json", Uuid::new_v4()));
    std::fs::write(&questions_path, &questions_jsonl).unwrap();
    std::fs::write(&map_path, serde_json::to_string(&map).unwrap()).unwrap();

    let nodes_table = database.nodes_table().await.unwrap();
    let documents_table = database.documents_table().await.unwrap();
    let version_before_nodes = nodes_table.version().await.unwrap();
    let version_before_documents = documents_table.version().await.unwrap();

    let records = inspect_gold_chunks(&database, &questions_path, &map_path)
        .await
        .unwrap();
    assert_eq!(records.len(), 1);

    let version_after_nodes = nodes_table.version().await.unwrap();
    let version_after_documents = documents_table.version().await.unwrap();
    assert_eq!(version_before_nodes, version_after_nodes);
    assert_eq!(version_before_documents, version_after_documents);

    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_file(&questions_path);
    let _ = std::fs::remove_file(&map_path);
}

/// Builds a synthetic store with arbitrary `document_id` values written into
/// `documents`, `nodes`, `edges`, `entity_edges` (one row per supplied ID,
/// duplicates allowed to prove dedup) and `staged_count` `staged_documents_v2`
/// rows, for `--document-ids` probe tests (06.3.4.1-04 Task 1).
async fn document_ids_store(
    test_name: &str,
    document_ids: &[&str],
    node_document_ids: &[&str],
    edge_document_ids: &[&str],
    entity_edge_document_ids: &[&str],
    staged_count: usize,
) -> (DatabaseManager, String) {
    let path = database_path(test_name);
    let database = DatabaseManager::initialize(&path).await.unwrap();

    if !document_ids.is_empty() {
        let documents = database.documents_table().await.unwrap();
        let n = document_ids.len();
        let batch = RecordBatch::try_new(
            documents.schema().await.unwrap(),
            vec![
                Arc::new(StringArray::from(document_ids.to_vec())),
                Arc::new(BinaryArray::from_vec(vec![b"fixture" as &[u8]; n])),
            ],
        )
        .unwrap();
        documents.add(batch).execute().await.unwrap();
    }

    if !node_document_ids.is_empty() {
        let nodes = database.nodes_table().await.unwrap();
        let schema = nodes.schema().await.unwrap();
        let n = node_document_ids.len();
        let nullable = |name: &str| {
            new_null_array(schema.field_with_name(name).unwrap().data_type(), n)
        };
        let embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
            (0..n).map(|_| Some((0..2048).map(|_| Some(0.1f32)))),
            2048,
        );
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(node_document_ids.to_vec())),
                Arc::new(StringArray::from(
                    (0..n).map(|i| format!("chunk-{i}")).collect::<Vec<_>>(),
                )),
                Arc::new(Int32Array::from_iter_values((0..n).map(|i| i as i32))),
                Arc::new(Int32Array::from_iter_values((0..n).map(|_| 0))),
                Arc::new(Int32Array::from_iter_values((0..n).map(|_| 9))),
                Arc::new(StringArray::from(vec!["fixture"; n])),
                Arc::new(embeddings),
                Arc::new(Int32Array::from(vec![1; n])),
                Arc::new(StringArray::from(vec!["o200k_base"; n])),
                Arc::new(StringArray::from(vec!["1"; n])),
                nullable("title"),
                nullable("section_path"),
                nullable("page_start"),
                nullable("page_end"),
                nullable("content_hash"),
                nullable("chunker_version"),
                nullable("embedding_model"),
                nullable("ingested_at"),
                nullable("content_type"),
            ],
        )
        .unwrap();
        nodes.add(batch).execute().await.unwrap();
    }

    if !edge_document_ids.is_empty() {
        let edges = database.edges_table().await.unwrap();
        let schema = edges.schema().await.unwrap();
        let n = edge_document_ids.len();
        let nullable = |name: &str| {
            new_null_array(schema.field_with_name(name).unwrap().data_type(), n)
        };
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(
                    (0..n).map(|i| format!("edge-{i}")).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    (0..n).map(|i| format!("src-{i}")).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    (0..n).map(|i| format!("tgt-{i}")).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(vec!["next_chunk"; n])),
                Arc::new(Float32Array::from(vec![1.0; n])),
                Arc::new(StringArray::from(edge_document_ids.to_vec())),
                nullable("summary"),
                nullable("summary_vector"),
            ],
        )
        .unwrap();
        edges.add(batch).execute().await.unwrap();
    }

    if !entity_edge_document_ids.is_empty() {
        let entity_edges = database.entity_edges_table().await.unwrap();
        let schema = entity_edges.schema().await.unwrap();
        let n = entity_edge_document_ids.len();
        let nullable = |name: &str| {
            new_null_array(schema.field_with_name(name).unwrap().data_type(), n)
        };
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(
                    (0..n).map(|i| format!("ee-{i}")).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    (0..n).map(|i| format!("esrc-{i}")).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    (0..n).map(|i| format!("etgt-{i}")).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(vec!["relates_to"; n])),
                Arc::new(Float32Array::from(vec![1.0; n])),
                Arc::new(StringArray::from(entity_edge_document_ids.to_vec())),
                nullable("summary"),
                nullable("summary_vector"),
            ],
        )
        .unwrap();
        entity_edges.add(batch).execute().await.unwrap();
    }

    if staged_count > 0 {
        let staged = database.staged_documents_table().await.unwrap();
        let schema = staged.schema().await.unwrap();
        let n = staged_count;
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(
                    (0..n).map(|i| format!("staged-doc-{i}")).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(vec!["fixture.txt"; n])),
                Arc::new(BinaryArray::from_vec(vec![b"fixture" as &[u8]; n])),
                Arc::new(StringArray::from(vec!["fixed_size"; n])),
                Arc::new(Int32Array::from(vec![500; n])),
                Arc::new(Int32Array::from(vec![50; n])),
                Arc::new(Int64Array::from(vec![1i64; n])),
            ],
        )
        .unwrap();
        staged.add(batch).execute().await.unwrap();
    }

    (database, path)
}

fn ids(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|v| (*v).to_owned()).collect()
}

#[tokio::test]
async fn document_ids_lists_sorted_dedup_sets() {
    let (database, path) = document_ids_store(
        "document-ids-populated",
        &["B", "A"],
        &["A", "B", "C", "A"],
        &["B"],
        &["A"],
        2,
    )
    .await;

    let report = inspect_document_ids(&database).await.unwrap();

    assert_eq!(
        report,
        DocumentIdsReport {
            documents: ids(&["A", "B"]),
            nodes: ids(&["A", "B", "C"]),
            edges: ids(&["B"]),
            entity_edges: ids(&["A"]),
            staged_documents_v2_rows: 2,
        }
    );

    let json = serde_json::to_string(&report).unwrap();
    assert_eq!(
        json,
        r#"{"documents":["A","B"],"nodes":["A","B","C"],"edges":["B"],"entity_edges":["A"],"staged_documents_v2_rows":2}"#
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn document_ids_empty_store_yields_empty() {
    let (database, path) = document_ids_store("document-ids-empty", &[], &[], &[], &[], 0).await;

    let report = inspect_document_ids(&database).await.unwrap();

    assert!(report.documents.is_empty());
    assert!(report.nodes.is_empty());
    assert!(report.edges.is_empty());
    assert!(report.entity_edges.is_empty());
    assert_eq!(report.staged_documents_v2_rows, 0);

    let _ = std::fs::remove_dir_all(path);
}

// ---- --chunk-text (06.3.5-01 Task 3, D-102) ---------------------------------------------------

fn parse_chunk_text_args(extra: &[&str]) -> Result<super::InspectConfig, String> {
    parse_args(extra.iter().map(|arg| (*arg).to_owned()))
}

fn chunk_id_line(chunk_id: &str) -> String {
    serde_json::json!({ "chunk_id": chunk_id }).to_string()
}

fn write_id_file(test_name: &str, lines: &[String]) -> std::path::PathBuf {
    let path = std::env::temp_dir().join(format!("chunk-text-{test_name}-{}.jsonl", Uuid::new_v4()));
    std::fs::write(&path, lines.join("\n")).unwrap();
    path
}

fn extra_node(chunk_id: String, chunk_index: i32, content: &str) -> NodeFixture {
    NodeFixture {
        chunk_id,
        chunk_index,
        embedding_model: Some(EMBEDDING_MODEL.to_owned()),
        ingested_at: Some(42),
        content: content.to_owned(),
    }
}

/// The current version of the `nodes`, `documents` and `edges` tables, in that order.
async fn table_versions(database: &DatabaseManager) -> Vec<u64> {
    let mut versions = Vec::new();
    for table in [
        database.nodes_table().await.unwrap(),
        database.documents_table().await.unwrap(),
        database.edges_table().await.unwrap(),
    ] {
        versions.push(table.version().await.unwrap());
    }
    versions
}

#[test]
fn chunk_text_flags_parse_and_require_a_canonical_generation() {
    let parsed = parse_chunk_text_args(&[
        "--chunk-text",
        "ids.jsonl",
        "--generation",
        "lance-702",
        "--out",
        "rows.jsonl",
        "--lancedb-path",
        "store",
    ])
    .unwrap();
    assert_eq!(
        parsed.mode,
        InspectMode::ChunkText {
            ids: std::path::PathBuf::from("ids.jsonl"),
            version: 702,
            out: Some(std::path::PathBuf::from("rows.jsonl")),
        }
    );
    assert_eq!(parsed.lancedb_path.as_deref(), Some("store"));

    let without_out =
        parse_chunk_text_args(&["--chunk-text", "ids.jsonl", "--generation", "lance-1"]).unwrap();
    assert_eq!(
        without_out.mode,
        InspectMode::ChunkText {
            ids: std::path::PathBuf::from("ids.jsonl"),
            version: 1,
            out: None,
        }
    );

    let missing = parse_chunk_text_args(&["--chunk-text", "ids.jsonl"]).unwrap_err();
    assert!(missing.contains("--chunk-text requires --generation"), "{missing}");
    let stray_generation =
        parse_chunk_text_args(&["--document-ids", "--generation", "lance-1"]).unwrap_err();
    assert!(
        stray_generation.contains("--generation is only valid with --chunk-text"),
        "{stray_generation}"
    );
    let stray_out = parse_chunk_text_args(&["--document-ids", "--out", "o"]).unwrap_err();
    assert!(
        stray_out.contains("--out is only valid with --chunk-text"),
        "{stray_out}"
    );
    let combined = parse_chunk_text_args(&[
        "--chunk-text",
        "ids.jsonl",
        "--generation",
        "lance-1",
        "--document-ids",
    ])
    .unwrap_err();
    assert!(combined.contains("multiple modes"), "{combined}");

    for bad in [
        "702",
        "lance-",
        "lance-x",
        "lance--1",
        "lance-+7",
        "lance-0702",
        "lance-702 ",
        "LANCE-702",
        "lance-18446744073709551616",
    ] {
        let err =
            parse_chunk_text_args(&["--chunk-text", "ids.jsonl", "--generation", bad]).unwrap_err();
        assert!(err.contains("lance-<N>"), "{bad:?} should be refused, got: {err}");
        assert!(parse_generation(bad).is_err(), "{bad:?} must not parse");
    }
    assert_eq!(parse_generation("lance-0"), Ok(0));
    assert_eq!(parse_generation("lance-18446744073709551615"), Ok(u64::MAX));
}

#[test]
fn chunk_text_refuses_a_malformed_id_by_line_number_without_echoing_it() {
    let good = format!("{}:0", Uuid::new_v4());
    let hostile = "x' OR '1'='1";
    let upper = format!("{}:0", Uuid::new_v4().to_string().to_uppercase());
    let cases: Vec<(Vec<String>, &str)> = vec![
        (vec![chunk_id_line(&good), chunk_id_line(hostile)], "line 2"),
        (
            vec![chunk_id_line(&good), String::new(), chunk_id_line(&upper)],
            "line 3",
        ),
        (vec![chunk_id_line(&good), "not json at all".to_owned()], "line 2"),
        (vec![serde_json::json!({ "document_id": "d" }).to_string()], "line 1"),
        (vec![serde_json::json!({ "chunk_id": 5 }).to_string()], "line 1"),
    ];
    for (lines, expected_line) in cases {
        let path = write_id_file("malformed", &lines);
        let err = read_chunk_id_file(&path).unwrap_err();
        let _ = std::fs::remove_file(&path);
        assert!(matches!(err, ChunkTextFailure::Input(_)), "{err:?}");
        assert_eq!(err.exit_code(), 2);
        let message = err.to_string();
        assert!(message.contains(expected_line), "{message}");
        assert!(!message.contains(hostile), "{message}");
        assert!(!message.contains("OR '1'"), "{message}");
        assert!(!message.contains(&upper), "{message}");
        assert!(!message.contains("not json at all"), "{message}");
    }

    let empty = write_id_file("empty", &[]);
    let err = read_chunk_id_file(&empty).unwrap_err();
    let _ = std::fs::remove_file(&empty);
    assert_eq!(err.exit_code(), 2);

    let absent = std::env::temp_dir().join(format!("chunk-text-absent-{}.jsonl", Uuid::new_v4()));
    assert_eq!(read_chunk_id_file(&absent).unwrap_err().exit_code(), 2);
}

#[test]
fn chunk_text_reads_ids_in_batches_of_at_most_the_in_predicate_limit() {
    let document_id = Uuid::new_v4().to_string();
    let ids: Vec<String> = (0..1201)
        .map(|index| format!("{document_id}:{index}"))
        .collect();
    let predicates = chunk_id_predicates(&ids);
    assert_eq!(IN_PREDICATE_BATCH_SIZE, 500);
    assert_eq!(predicates.len(), 3);
    let sizes: Vec<usize> = predicates
        .iter()
        .map(|predicate| predicate.matches('\'').count() / 2)
        .collect();
    assert_eq!(sizes, vec![500, 500, 201]);
    for predicate in &predicates {
        assert!(predicate.starts_with("chunk_id IN ('"), "{predicate}");
        assert!(predicate.ends_with("')"), "{predicate}");
    }
    assert!(predicates[0].contains(&format!("'{document_id}:0'")));
    assert!(predicates[2].contains(&format!("'{document_id}:1200'")));
    assert!(chunk_id_predicates(&[]).is_empty());
}

#[tokio::test]
async fn chunk_text_reads_rows_at_the_pinned_version_in_request_order() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = gold_chunk_nodes(&document_id, &["Alpha zero ünï.", "Beta one."]);
    let (database, path, stored_document_id) = fixture("chunk-text-pinned", &nodes, &[]).await;
    let pinned = database.nodes_table().await.unwrap().version().await.unwrap();
    add_nodes(
        &database,
        &stored_document_id,
        &[extra_node(format!("{document_id}:2"), 2, "Gamma two.")],
    )
    .await;
    let latest = database.nodes_table().await.unwrap().version().await.unwrap();
    assert!(latest > pinned, "adding a row opened a new table version");

    // Repeated and out-of-order IDs: the first sighting fixes the order, the repeat is dropped.
    let lines = vec![
        chunk_id_line(&format!("{document_id}:1")),
        chunk_id_line(&format!("{document_id}:0")),
        chunk_id_line(&format!("{document_id}:1")),
        chunk_id_line(&format!("{document_id}:2")),
    ];
    let id_file = write_id_file("pinned", &lines);
    let ids = read_chunk_id_file(&id_file).unwrap();
    let _ = std::fs::remove_file(&id_file);
    assert_eq!(
        ids,
        vec![
            format!("{document_id}:1"),
            format!("{document_id}:0"),
            format!("{document_id}:2")
        ]
    );

    let at_pinned = inspect_chunk_text(&database, &ids, pinned).await.unwrap();
    assert_eq!(at_pinned.requested, 3);
    assert_eq!(
        at_pinned.rows,
        vec![
            ChunkTextRow {
                chunk_id: format!("{document_id}:1"),
                document_id: stored_document_id.clone(),
                chunk_index: 1,
                content_sha256:
                    "e1426f99e3dd8b08d523fce71370ce0dbccd331b1672e2c6a4d766567cc6fae8".to_owned(),
                text: "Beta one.".to_owned(),
            },
            ChunkTextRow {
                chunk_id: format!("{document_id}:0"),
                document_id: stored_document_id.clone(),
                chunk_index: 0,
                content_sha256:
                    "15cdbf5bb1f7eac75ceb56c27f1f838cb1b216b6242a887a3d17f5b2f3cac797".to_owned(),
                text: "Alpha zero ünï.".to_owned(),
            },
        ],
        "the row added after the pinned version is not read"
    );
    assert_eq!(at_pinned.missing_count(), 1);
    assert_eq!(at_pinned.exit_code(), 3);

    let at_latest = inspect_chunk_text(&database, &ids, latest).await.unwrap();
    assert_eq!(at_latest.missing_count(), 0);
    assert_eq!(at_latest.exit_code(), 0);
    assert_eq!(
        at_latest
            .rows
            .iter()
            .map(|row| row.chunk_id.clone())
            .collect::<Vec<_>>(),
        vec![
            format!("{document_id}:1"),
            format!("{document_id}:0"),
            format!("{document_id}:2")
        ]
    );
    assert_eq!(
        at_latest.rows[2].content_sha256,
        "ced3ff086a9c8ada770249b776dbcd49ba000a56eb2e4da5ad1c9ee3fd2ba75b"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn chunk_text_an_absent_table_version_is_an_error() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = gold_chunk_nodes(&document_id, &["Alpha content."]);
    let (database, path, _) = fixture("chunk-text-absent-version", &nodes, &[]).await;
    let latest = database.nodes_table().await.unwrap().version().await.unwrap();

    let ids = vec![format!("{document_id}:0")];
    let err = inspect_chunk_text(&database, &ids, latest + 100)
        .await
        .unwrap_err();
    assert!(matches!(err, ChunkTextFailure::Store(_)), "{err:?}");
    assert_eq!(err.exit_code(), 1);
    let message = err.to_string();
    assert!(message.contains(&format!("{}", latest + 100)), "{message}");
    assert!(!message.contains("Alpha content"), "{message}");
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn chunk_text_a_valid_id_absent_at_the_version_exits_3_and_the_summary_has_no_text() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = gold_chunk_nodes(&document_id, &["Alpha content."]);
    let (database, path, _) = fixture("chunk-text-missing-id", &nodes, &[]).await;
    let latest = database.nodes_table().await.unwrap().version().await.unwrap();

    let absent = format!("{}:0", Uuid::new_v4());
    let ids = vec![format!("{document_id}:0"), absent.clone()];
    let report = inspect_chunk_text(&database, &ids, latest).await.unwrap();
    assert_eq!(report.requested, 2);
    assert_eq!(report.rows.len(), 1);
    assert_eq!(report.missing_count(), 1);
    assert_eq!(report.exit_code(), 3);
    let summary = report.summary();
    assert!(summary.contains('2') && summary.contains('1'), "{summary}");
    assert!(!summary.contains("Alpha content"), "{summary}");
    assert!(!summary.contains(&absent), "{summary}");
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn chunk_text_does_not_mutate_table_versions() {
    let document_id = Uuid::new_v4().to_string();
    let nodes = gold_chunk_nodes(&document_id, &["Alpha content.", "Beta content."]);
    let (database, path, stored_document_id) = fixture("chunk-text-versions", &nodes, &[]).await;
    let early = database.nodes_table().await.unwrap().version().await.unwrap();
    add_nodes(
        &database,
        &stored_document_id,
        &[extra_node(format!("{document_id}:2"), 2, "Gamma content.")],
    )
    .await;
    let before = table_versions(&database).await;

    let ids: Vec<String> = (0..3)
        .map(|index| format!("{document_id}:{index}"))
        .collect();
    inspect_chunk_text(&database, &ids, early).await.unwrap();
    inspect_chunk_text(&database, &ids, before[0]).await.unwrap();
    assert!(inspect_chunk_text(&database, &ids, before[0] + 50)
        .await
        .is_err());

    assert_eq!(table_versions(&database).await, before);
    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn chunk_text_sha256_matches_the_published_vectors() {
    assert_eq!(
        sha256_hex(b""),
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
    assert_eq!(
        sha256_hex(b"abc"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    // 56 bytes: the length field no longer fits in the first block, so a second block is needed.
    assert_eq!(
        sha256_hex(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
    );
    // Multi-byte UTF-8 across several blocks: 200 bytes.
    assert_eq!(
        sha256_hex("é".repeat(100).as_bytes()),
        "f42ec48e1e4b487e590e0b3d4e58437c8327efa855d769709f4942a4f73a7eb6"
    );
    assert_eq!(
        sha256_hex("line one\nline two ☃".as_bytes()),
        "4acbce6e7e8b1d1af1e6cedb4dfb2386a182e29e066dc29dc81b8d6a1353954b"
    );
}

#[test]
fn chunk_text_jsonl_has_one_object_per_row_with_exactly_the_five_keys() {
    let rows = vec![
        ChunkTextRow {
            chunk_id: "c:0".to_owned(),
            document_id: "d".to_owned(),
            chunk_index: 0,
            content_sha256: sha256_hex("line one\nline two ☃".as_bytes()),
            text: "line one\nline two ☃".to_owned(),
        },
        ChunkTextRow {
            chunk_id: "c:1".to_owned(),
            document_id: "d".to_owned(),
            chunk_index: 1,
            content_sha256: sha256_hex(b""),
            text: String::new(),
        },
    ];
    let rendered = render_chunk_text_jsonl(&rows).unwrap();
    assert!(rendered.ends_with('\n'));
    let lines: Vec<&str> = rendered.lines().collect();
    assert_eq!(lines.len(), 2, "an embedded newline is escaped, not a line break");
    for (line, row) in lines.iter().zip(&rows) {
        let value: serde_json::Value = serde_json::from_str(line).unwrap();
        let mut keys: Vec<&str> = value
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        keys.sort_unstable();
        assert_eq!(
            keys,
            vec!["chunk_id", "chunk_index", "content_sha256", "document_id", "text"]
        );
        assert_eq!(&serde_json::from_str::<ChunkTextRow>(line).unwrap(), row);
    }
    assert!(render_chunk_text_jsonl(&[]).unwrap().is_empty());
}

// ---- --graph-dump (06.3.6-02 Task 2, D-137) ---------------------------------------------------

struct DumpEntityFixture {
    entity_id: &'static str,
    name: &'static str,
    entity_type: &'static str,
    source_chunk_ids: &'static [&'static str],
}

struct DumpEdgeFixture {
    edge_id: &'static str,
    source_node_id: &'static str,
    target_node_id: &'static str,
    summary: Option<&'static str>,
}

/// A store whose entity rows carry `source_chunk_ids`, which `graph_fixture` leaves empty.
async fn graph_dump_store(
    test_name: &str,
    entities: &[DumpEntityFixture],
    edges: &[DumpEdgeFixture],
) -> (DatabaseManager, String) {
    let path = database_path(test_name);
    let database = DatabaseManager::initialize(&path).await.unwrap();

    if !entities.is_empty() {
        let table = database.entities_table().await.unwrap();
        let schema = table.schema().await.unwrap();
        let count = entities.len();
        let nullable = |name: &str| {
            new_null_array(schema.field_with_name(name).unwrap().data_type(), count)
        };
        let name_vectors = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
            (0..count).map(|_| Some((0..2048).map(|_| Some(0.1f32)))),
            2048,
        );
        let mut chunk_ids = ListBuilder::new(StringBuilder::new());
        for entity in entities {
            for chunk_id in entity.source_chunk_ids {
                chunk_ids.values().append_value(chunk_id);
            }
            chunk_ids.append(true);
        }
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(
                    entities.iter().map(|e| e.entity_id).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    entities.iter().map(|e| e.name).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    entities.iter().map(|e| e.entity_type).collect::<Vec<_>>(),
                )),
                Arc::new(name_vectors),
                nullable("summary"),
                nullable("summary_vector"),
                nullable("unsummarized_refs"),
                nullable("community_ids"),
                Arc::new(chunk_ids.finish()),
            ],
        )
        .unwrap();
        table.add(batch).execute().await.unwrap();
    }

    if !edges.is_empty() {
        let table = database.entity_edges_table().await.unwrap();
        let schema = table.schema().await.unwrap();
        let count = edges.len();
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(
                    edges.iter().map(|e| e.edge_id).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    edges.iter().map(|e| e.source_node_id).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(
                    edges.iter().map(|e| e.target_node_id).collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(vec!["owns"; count])),
                Arc::new(Float32Array::from(vec![0.5; count])),
                Arc::new(StringArray::from(vec!["doc:dummy"; count])),
                Arc::new(StringArray::from(
                    edges.iter().map(|e| e.summary).collect::<Vec<_>>(),
                )),
                new_null_array(
                    schema.field_with_name("summary_vector").unwrap().data_type(),
                    count,
                ),
            ],
        )
        .unwrap();
        table.add(batch).execute().await.unwrap();
    }

    (database, path)
}

/// The current version of the `entities`, `entity_edges` and `nodes` tables, in that order.
async fn graph_table_versions(database: &DatabaseManager) -> Vec<u64> {
    let mut versions = Vec::new();
    for table in [
        database.entities_table().await.unwrap(),
        database.entity_edges_table().await.unwrap(),
        database.nodes_table().await.unwrap(),
    ] {
        versions.push(table.version().await.unwrap());
    }
    versions
}

fn read_json_lines(path: &std::path::Path) -> Vec<serde_json::Value> {
    std::fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

fn sorted_keys(value: &serde_json::Value) -> Vec<&str> {
    let mut keys: Vec<&str> = value
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    keys.sort_unstable();
    keys
}

fn dump_fixture_entities() -> Vec<DumpEntityFixture> {
    vec![
        DumpEntityFixture {
            entity_id: "e-b",
            name: "Pixar",
            entity_type: "ORG",
            source_chunk_ids: &["d1:0", "d2:3"],
        },
        DumpEntityFixture {
            entity_id: "e-a",
            name: "Disney",
            entity_type: "ORG",
            source_chunk_ids: &["d1:0"],
        },
        DumpEntityFixture {
            entity_id: "e-c",
            name: "Nobody",
            entity_type: "PERSON",
            source_chunk_ids: &[],
        },
    ]
}

fn dump_fixture_edges() -> Vec<DumpEdgeFixture> {
    vec![
        DumpEdgeFixture {
            edge_id: "x-2",
            source_node_id: "e-b",
            target_node_id: "e-a",
            summary: None,
        },
        DumpEdgeFixture {
            edge_id: "x-1",
            source_node_id: "e-a",
            target_node_id: "e-b",
            summary: Some("Disney owns Pixar"),
        },
    ]
}

#[test]
fn graph_dump_flags_parse_and_require_out() {
    let parsed = parse_chunk_text_args(&["--graph-dump", "--out", "dump", "--lancedb-path", "store"])
        .unwrap();
    assert_eq!(
        parsed.mode,
        InspectMode::GraphDump {
            out: std::path::PathBuf::from("dump"),
        }
    );
    assert_eq!(parsed.lancedb_path.as_deref(), Some("store"));

    let missing_out = parse_chunk_text_args(&["--graph-dump"]).unwrap_err();
    assert!(missing_out.contains("--graph-dump requires --out"), "{missing_out}");

    let combined =
        parse_chunk_text_args(&["--graph-dump", "--out", "dump", "--document-ids"]).unwrap_err();
    assert!(
        combined.contains("multiple modes specified; select exactly one"),
        "{combined}"
    );
    let with_chunk_text = parse_chunk_text_args(&[
        "--graph-dump",
        "--chunk-text",
        "ids.jsonl",
        "--generation",
        "lance-1",
        "--out",
        "o",
    ])
    .unwrap_err();
    assert!(with_chunk_text.contains("multiple modes"), "{with_chunk_text}");

    let stray_generation =
        parse_chunk_text_args(&["--graph-dump", "--out", "dump", "--generation", "lance-1"])
            .unwrap_err();
    assert!(
        stray_generation.contains("--generation is only valid with --chunk-text"),
        "{stray_generation}"
    );
    let stray_max_hops =
        parse_chunk_text_args(&["--graph-dump", "--out", "dump", "--max-hops", "2"]).unwrap_err();
    assert!(
        stray_max_hops.contains("--max-hops is only valid with --entity"),
        "{stray_max_hops}"
    );
    let stray_out = parse_chunk_text_args(&["--graph-population", "--out", "dump"]).unwrap_err();
    assert!(
        stray_out.contains("--out is only valid with --chunk-text or --graph-dump"),
        "{stray_out}"
    );
}

#[tokio::test]
async fn graph_dump_writes_both_tables_sorted_without_vectors_and_a_matching_meta() {
    let (database, path) = graph_dump_store(
        "graph-dump-files",
        &dump_fixture_entities(),
        &dump_fixture_edges(),
    )
    .await;
    let out = std::path::PathBuf::from(database_path("graph-dump-out"));

    let meta = inspect_graph_dump(&database, &out).await.unwrap();

    let entities = read_json_lines(&out.join(GRAPH_DUMP_ENTITIES_FILE));
    assert_eq!(entities.len(), 3);
    let ids: Vec<&str> = entities
        .iter()
        .map(|row| row["entity_id"].as_str().unwrap())
        .collect();
    assert_eq!(ids, vec!["e-a", "e-b", "e-c"], "rows are sorted by entity_id");
    for row in &entities {
        assert_eq!(
            sorted_keys(row),
            vec!["entity_id", "entity_type", "name", "source_chunk_ids"]
        );
    }
    assert_eq!(entities[1]["name"], "Pixar");
    assert_eq!(entities[1]["entity_type"], "ORG");
    assert_eq!(
        entities[1]["source_chunk_ids"],
        serde_json::json!(["d1:0", "d2:3"])
    );
    assert_eq!(entities[2]["source_chunk_ids"], serde_json::json!([]));

    let edges = read_json_lines(&out.join(GRAPH_DUMP_EDGES_FILE));
    assert_eq!(edges.len(), 2);
    assert_eq!(edges[0]["edge_id"], "x-1");
    assert_eq!(edges[0]["source_node_id"], "e-a");
    assert_eq!(edges[0]["target_node_id"], "e-b");
    assert_eq!(edges[0]["summary"], "Disney owns Pixar");
    assert!(edges[1]["summary"].is_null());
    for row in &edges {
        assert_eq!(
            sorted_keys(row),
            vec![
                "document_id",
                "edge_id",
                "relation_type",
                "source_node_id",
                "summary",
                "target_node_id",
                "weight",
            ]
        );
    }

    let on_disk: GraphDumpMeta = serde_json::from_str(
        &std::fs::read_to_string(out.join(GRAPH_DUMP_META_FILE)).unwrap(),
    )
    .unwrap();
    assert_eq!(on_disk, meta);
    let raw_meta: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(out.join(GRAPH_DUMP_META_FILE)).unwrap())
            .unwrap();
    assert_eq!(
        sorted_keys(&raw_meta),
        vec![
            "entities_version",
            "entity_edges_version",
            "row_counts",
            "sha256"
        ]
    );
    assert_eq!(
        sorted_keys(&raw_meta["row_counts"]),
        vec!["entities", "entity_edges"]
    );
    assert_eq!(
        sorted_keys(&raw_meta["sha256"]),
        vec!["entities.jsonl", "entity_edges.jsonl"]
    );
    assert_eq!(raw_meta["row_counts"]["entities"], 3);
    assert_eq!(raw_meta["row_counts"]["entity_edges"], 2);
    let versions = graph_table_versions(&database).await;
    assert_eq!(raw_meta["entities_version"], versions[0]);
    assert_eq!(raw_meta["entity_edges_version"], versions[1]);
    assert_eq!(
        raw_meta["sha256"]["entities.jsonl"],
        sha256_hex(&std::fs::read(out.join(GRAPH_DUMP_ENTITIES_FILE)).unwrap())
    );
    assert_eq!(
        raw_meta["sha256"]["entity_edges.jsonl"],
        sha256_hex(&std::fs::read(out.join(GRAPH_DUMP_EDGES_FILE)).unwrap())
    );
    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_dir_all(out);
}

#[tokio::test]
async fn graph_dump_does_not_mutate_table_versions_and_is_deterministic() {
    let (database, path) = graph_dump_store(
        "graph-dump-versions",
        &dump_fixture_entities(),
        &dump_fixture_edges(),
    )
    .await;
    let before = graph_table_versions(&database).await;
    let first = std::path::PathBuf::from(database_path("graph-dump-first"));
    let second = std::path::PathBuf::from(database_path("graph-dump-second"));

    inspect_graph_dump(&database, &first).await.unwrap();
    inspect_graph_dump(&database, &second).await.unwrap();

    assert_eq!(graph_table_versions(&database).await, before);
    for name in [
        GRAPH_DUMP_ENTITIES_FILE,
        GRAPH_DUMP_EDGES_FILE,
        GRAPH_DUMP_META_FILE,
    ] {
        assert_eq!(
            std::fs::read(first.join(name)).unwrap(),
            std::fs::read(second.join(name)).unwrap(),
            "{name} differs between two runs over the same versions"
        );
    }
    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_dir_all(first);
    let _ = std::fs::remove_dir_all(second);
}

#[tokio::test]
async fn graph_dump_refuses_to_overwrite_an_existing_dump() {
    let (database, path) = graph_dump_store(
        "graph-dump-overwrite",
        &dump_fixture_entities(),
        &dump_fixture_edges(),
    )
    .await;
    let out = std::path::PathBuf::from(database_path("graph-dump-twice"));
    inspect_graph_dump(&database, &out).await.unwrap();
    let kept = std::fs::read(out.join(GRAPH_DUMP_ENTITIES_FILE)).unwrap();

    let error = inspect_graph_dump(&database, &out).await.unwrap_err();

    assert!(error.contains("refusing to overwrite"), "{error}");
    assert_eq!(std::fs::read(out.join(GRAPH_DUMP_ENTITIES_FILE)).unwrap(), kept);
    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_dir_all(out);
}

#[tokio::test]
async fn graph_dump_of_an_empty_store_writes_empty_files_and_zero_counts() {
    let (database, path) = graph_dump_store("graph-dump-empty", &[], &[]).await;
    let out = std::path::PathBuf::from(database_path("graph-dump-empty-out"));

    let meta = inspect_graph_dump(&database, &out).await.unwrap();

    assert_eq!(meta.row_counts.entities, 0);
    assert_eq!(meta.row_counts.entity_edges, 0);
    assert!(std::fs::read(out.join(GRAPH_DUMP_ENTITIES_FILE)).unwrap().is_empty());
    assert!(std::fs::read(out.join(GRAPH_DUMP_EDGES_FILE)).unwrap().is_empty());
    assert_eq!(meta.sha256.entities, sha256_hex(b""));
    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_dir_all(out);
}
