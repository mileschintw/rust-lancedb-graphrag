use std::sync::Arc;

use arrow_array::new_null_array;
use arrow_array::types::Float32Type;
use arrow_array::{
    BinaryArray, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch, StringArray,
};
use uuid::Uuid;

use super::{inspect_document, Inspection, EMBEDDING_MODEL};
use engine::db::DatabaseManager;

#[derive(Clone)]
struct NodeFixture {
    chunk_id: String,
    chunk_index: i32,
    embedding_model: Option<String>,
    ingested_at: Option<i64>,
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
            Arc::new(StringArray::from(vec![document_id.as_str(); node_count])),
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
            Arc::new(StringArray::from(vec!["fixture"; node_count])),
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
