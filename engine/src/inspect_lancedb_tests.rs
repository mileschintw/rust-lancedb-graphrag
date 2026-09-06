use std::sync::Arc;

use arrow_array::builder::{ListBuilder, StringBuilder};
use arrow_array::new_null_array;
use arrow_array::types::Float32Type;
use arrow_array::{
    BinaryArray, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch, StringArray,
};
use uuid::Uuid;

use super::{
    inspect_document, inspect_entity_name, inspect_entity_neighborhood, inspect_graph_population,
    parse_args, DegreeDistribution, EntityMatch, EntityNameReport, GraphPopulationReport,
    Inspection, NeighborhoodEdge, NeighborhoodReport, EMBEDDING_MODEL,
};
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
            max: 1,
        }),
        isolated_entity_count: 0,
        highest_degree_entity_id: Some("00000000-0000-4000-8000-000000000001".into()),
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
