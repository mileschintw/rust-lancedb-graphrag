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
    assert!(!ent_schema.field_with_name("entity_id").unwrap().is_nullable());
    assert!(!ent_schema.field_with_name("name").unwrap().is_nullable());
    assert!(!ent_schema.field_with_name("entity_type").unwrap().is_nullable());
    assert!(!ent_schema.field_with_name("name_vector").unwrap().is_nullable());
    assert!(ent_schema.field_with_name("summary").unwrap().is_nullable());
    assert!(ent_schema.field_with_name("summary_vector").unwrap().is_nullable());
    assert!(ent_schema.field_with_name("unsummarized_refs").unwrap().is_nullable());
    assert!(ent_schema.field_with_name("community_ids").unwrap().is_nullable());
    assert!(!ent_schema.field_with_name("source_chunk_ids").unwrap().is_nullable());

    let ee_schema = entity_edges_schema();
    assert!(!ee_schema.field_with_name("edge_id").unwrap().is_nullable());
    assert!(!ee_schema.field_with_name("source_node_id").unwrap().is_nullable());
    assert!(!ee_schema.field_with_name("target_node_id").unwrap().is_nullable());
    assert!(!ee_schema.field_with_name("relation_type").unwrap().is_nullable());
    assert!(!ee_schema.field_with_name("weight").unwrap().is_nullable());
    assert!(!ee_schema.field_with_name("document_id").unwrap().is_nullable());
    assert!(ee_schema.field_with_name("summary").unwrap().is_nullable());
    assert!(ee_schema.field_with_name("summary_vector").unwrap().is_nullable());
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
    assert!(error.contains("Remediation: schema reconciliation is fail-closed by design"));
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
