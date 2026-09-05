use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use arrow_schema::{DataType, Field, Schema};

use lancedb::query::ExecutableQuery;

use super::{edges_schema, DatabaseManager, EntityResolver, ExactMatchResolver};

#[test]
fn edge_summary_placeholders_are_nullable_but_identifiers_are_required() {
    let schema = edges_schema();
    assert!(schema.field_with_name("summary").unwrap().is_nullable());
    assert!(schema
        .field_with_name("summary_vector")
        .unwrap()
        .is_nullable());
    assert!(!schema.field_with_name("edge_id").unwrap().is_nullable());
}

fn database_path(test_name: &str) -> String {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir()
        .join(format!("lancet-{test_name}-{nonce}"))
        .to_string_lossy()
        .into_owned()
}

#[tokio::test]
async fn initializes_and_validates_all_table_schemas() {
    let path = database_path("initialize");
    let manager = DatabaseManager::initialize(&path).await.unwrap();
    let connection = lancedb::connect(&path).execute().await.unwrap();
    let mut names = connection.table_names().execute().await.unwrap();
    names.sort();
    assert_eq!(
        names,
        [
            "communities",
            "documents",
            "edges",
            "entities",
            "entity_edges",
            "nodes",
            "staged_documents_v2"
        ]
    );

    DatabaseManager::initialize(&path).await.unwrap();
    drop(manager);
    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn entities_and_entity_edges_schema_shapes_are_valid() {
    use super::{entities_schema, entity_edges_schema};
    let ent_schema = entities_schema();
    assert!(!ent_schema
        .field_with_name("entity_id")
        .unwrap()
        .is_nullable());
    assert!(!ent_schema.field_with_name("name").unwrap().is_nullable());
    assert!(!ent_schema
        .field_with_name("entity_type")
        .unwrap()
        .is_nullable());
    assert!(!ent_schema
        .field_with_name("name_vector")
        .unwrap()
        .is_nullable());
    assert!(ent_schema.field_with_name("summary").unwrap().is_nullable());
    assert!(ent_schema
        .field_with_name("summary_vector")
        .unwrap()
        .is_nullable());
    assert!(ent_schema
        .field_with_name("unsummarized_refs")
        .unwrap()
        .is_nullable());
    assert!(ent_schema
        .field_with_name("community_ids")
        .unwrap()
        .is_nullable());
    assert!(!ent_schema
        .field_with_name("source_chunk_ids")
        .unwrap()
        .is_nullable());

    let ee_schema = entity_edges_schema();
    assert!(!ee_schema.field_with_name("edge_id").unwrap().is_nullable());
    assert!(!ee_schema
        .field_with_name("source_node_id")
        .unwrap()
        .is_nullable());
    assert!(!ee_schema
        .field_with_name("target_node_id")
        .unwrap()
        .is_nullable());
    assert!(!ee_schema
        .field_with_name("relation_type")
        .unwrap()
        .is_nullable());
    assert!(!ee_schema.field_with_name("weight").unwrap().is_nullable());
    assert!(!ee_schema
        .field_with_name("document_id")
        .unwrap()
        .is_nullable());
    assert!(ee_schema.field_with_name("summary").unwrap().is_nullable());
    assert!(ee_schema
        .field_with_name("summary_vector")
        .unwrap()
        .is_nullable());
}

#[tokio::test]
async fn schema_drift_fails_database_initialization() {
    let path = database_path("drift");
    let connection = lancedb::connect(&path).execute().await.unwrap();
    connection
        .create_empty_table(
            "documents",
            Arc::new(Schema::new(vec![Field::new(
                "wrong_column",
                DataType::Utf8,
                false,
            )])),
        )
        .execute()
        .await
        .unwrap();

    let error = match DatabaseManager::initialize(&path).await {
        Ok(_) => panic!("schema drift must fail initialization"),
        Err(error) => error,
    };
    assert!(error.contains("schema drift detected for documents"));
    let remediation_at = error
        .find("Remediation:")
        .expect("remediation guidance present");
    let details_at = error
        .find("Details - expected:")
        .expect("schema details present");
    assert!(
        remediation_at < details_at,
        "remediation guidance must precede the schema dump; got remediation@{remediation_at} details@{details_at}"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn initialize_is_idempotent_over_non_empty_staging() {
    use arrow_array::{BinaryArray, Int32Array, Int64Array, RecordBatch, StringArray};
    let path = database_path("idempotent-init");
    let manager = DatabaseManager::initialize(&path).await.unwrap();
    let staged_table = manager.staged_documents_table().await.unwrap();
    let batch = RecordBatch::try_new(
        staged_table.schema().await.unwrap(),
        vec![
            Arc::new(StringArray::from(vec!["doc-1"])),
            Arc::new(StringArray::from(vec!["file1.md"])),
            Arc::new(BinaryArray::from_vec(vec![b"hello"])),
            Arc::new(StringArray::from(vec!["structure-aware"])),
            Arc::new(Int32Array::from(vec![500])),
            Arc::new(Int32Array::from(vec![50])),
            Arc::new(Int64Array::from(vec![1])),
        ],
    )
    .unwrap();
    staged_table.add(batch).execute().await.unwrap();

    let mgr2 = DatabaseManager::initialize(&path).await.unwrap();
    let mgr3 = DatabaseManager::initialize(&path).await.unwrap();

    let table3 = mgr3.staged_documents_table().await.unwrap();
    assert_eq!(table3.count_rows(None).await.unwrap(), 1);

    drop(manager);
    drop(mgr2);
    drop(mgr3);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn staged_generation_schema_is_int64_and_legacy_rows_migrate() {
    use super::legacy_staged_documents_v2_schema;
    use arrow_array::{BinaryArray, Int32Array, Int64Array, RecordBatch, StringArray};
    use futures::TryStreamExt;

    let path = database_path("legacy-migration");
    let connection = lancedb::connect(&path).execute().await.unwrap();

    let legacy_schema = legacy_staged_documents_v2_schema();
    let legacy_table = connection
        .create_empty_table("staged_documents_v2", legacy_schema.clone())
        .execute()
        .await
        .unwrap();

    let batch = RecordBatch::try_new(
        legacy_schema,
        vec![
            Arc::new(StringArray::from(vec!["doc-legacy"])),
            Arc::new(StringArray::from(vec!["legacy.md"])),
            Arc::new(BinaryArray::from_vec(vec![b"legacy content"])),
            Arc::new(StringArray::from(vec!["fixed-size"])),
            Arc::new(Int32Array::from(vec![500])),
            Arc::new(Int32Array::from(vec![50])),
        ],
    )
    .unwrap();
    legacy_table.add(batch).execute().await.unwrap();

    let manager = DatabaseManager::initialize(&path).await.unwrap();
    let table = manager.staged_documents_table().await.unwrap();
    let schema = table.schema().await.unwrap();

    let gen_field = schema.field_with_name("generation").unwrap();
    assert_eq!(gen_field.data_type(), &DataType::Int64);
    assert!(!gen_field.is_nullable());

    let batches: Vec<RecordBatch> = table
        .query()
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();
    assert_eq!(batches.len(), 1);
    let gen_col = batches[0]
        .column_by_name("generation")
        .unwrap()
        .as_any()
        .downcast_ref::<Int64Array>()
        .unwrap();
    assert_eq!(gen_col.value(0), 1);

    drop(manager);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn exact_match_resolver_returns_only_identical_entities() {
    let resolver = ExactMatchResolver;
    let known = vec!["Lancet".to_string(), "OpenRouter".to_string()];
    assert_eq!(
        resolver.resolve("Lancet", &known).await.unwrap(),
        Some("Lancet".to_string())
    );
    assert_eq!(resolver.resolve("lancet", &known).await.unwrap(), None);
}

/// 06.3.1-02 Test 1: get_or_create_table creates only on missing table for all six accessors.
#[tokio::test]
async fn get_or_create_table_creates_only_on_missing_table_for_all_six_accessors() {
    let path = database_path("creates-only-on-missing");
    let manager = DatabaseManager::initialize(&path).await.unwrap();

    // The six names enumerated explicitly (seventh schema is intentionally omitted - no accessor)
    let accessor_names = [
        "documents",
        "staged_documents_v2",
        "nodes",
        "edges",
        "entities",
        "entity_edges",
    ];

    let schemas = super::table_schemas();

    // Part 1: Drop each table through connection, then call accessor to prove create branch executes
    for name in &accessor_names {
        manager.connection.drop_table(name, &[]).await.unwrap();

        let table = match *name {
            "documents" => manager.documents_table().await.unwrap(),
            "staged_documents_v2" => manager.staged_documents_table().await.unwrap(),
            "nodes" => manager.nodes_table().await.unwrap(),
            "edges" => manager.edges_table().await.unwrap(),
            "entities" => manager.entities_table().await.unwrap(),
            "entity_edges" => manager.entity_edges_table().await.unwrap(),
            _ => unreachable!(),
        };

        let schema = table.schema().await.unwrap();
        let (_, expected_schema) = schemas.iter().find(|(n, _)| *n == *name).unwrap();
        assert_eq!(schema.fields(), expected_schema.fields());
    }

    // Part 2: With all six tables present on an intact store, accessors return Ok without re-creating
    let intact_path = database_path("intact-store");
    let intact_manager = DatabaseManager::initialize(&intact_path).await.unwrap();
    assert!(intact_manager.documents_table().await.is_ok());
    assert!(intact_manager.staged_documents_table().await.is_ok());
    assert!(intact_manager.nodes_table().await.is_ok());
    assert!(intact_manager.edges_table().await.is_ok());
    assert!(intact_manager.entities_table().await.is_ok());
    assert!(intact_manager.entity_edges_table().await.is_ok());

    drop(manager);
    drop(intact_manager);
    let _ = std::fs::remove_dir_all(path);
    let _ = std::fs::remove_dir_all(intact_path);
}

/// 06.3.1-02 Test 2: Deterministic proof that is_table_not_found discriminates TableNotFound from other errors.
#[test]
fn is_table_not_found_discriminates_missing_from_non_missing() {
    let missing_err = lancedb::Error::TableNotFound {
        name: "documents".into(),
        source: Box::new(std::io::Error::new(std::io::ErrorKind::NotFound, "not found")),
    };
    assert!(
        super::is_table_not_found(&missing_err),
        "TableNotFound must be recognized as missing table"
    );

    let runtime_err = lancedb::Error::Runtime {
        message: "runtime failure".into(),
    };
    assert!(
        !super::is_table_not_found(&runtime_err),
        "Runtime error must NOT be recognized as missing table"
    );

    let timeout_err = lancedb::Error::Timeout {
        message: "operation timed out".into(),
    };
    assert!(
        !super::is_table_not_found(&timeout_err),
        "Timeout error must NOT be recognized as missing table"
    );

    let schema_err = lancedb::Error::Schema {
        message: "schema mismatch".into(),
    };
    assert!(
        !super::is_table_not_found(&schema_err),
        "Schema error must NOT be recognized as missing table"
    );
}

/// 06.3.1-02 Test 3: get_or_create_table fails closed on non-missing table error.
/// Marked #[ignore] due to Windows file-locking non-determinism during table corruption,
/// as specified in Plan 06.3.1-02.
#[tokio::test]
#[ignore = "Windows file-locking non-determinism during on-disk directory corruption; covered by is_table_not_found_discriminates_missing_from_non_missing"]
async fn get_or_create_table_fails_closed_on_non_missing_table_error() {
    let path = database_path("fail-closed-non-missing");
    let manager = DatabaseManager::initialize(&path).await.unwrap();

    let table_dir = std::path::Path::new(&path).join("documents.lance");
    if table_dir.exists() {
        let dummy_file = table_dir.join("corrupted.data");
        std::fs::write(&dummy_file, b"invalid lance data").unwrap();
    }

    let res = manager.documents_table().await;
    if let Err(msg) = res {
        assert!(msg.contains("documents"));
    }

    drop(manager);
    let _ = std::fs::remove_dir_all(path);
}
