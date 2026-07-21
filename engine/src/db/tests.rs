use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use arrow_schema::{DataType, Field, Schema};

use super::{DatabaseManager, EntityResolver, ExactMatchResolver};

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
    assert_eq!(names, ["communities", "documents", "edges", "nodes"]);

    DatabaseManager::initialize(&path).await.unwrap();
    drop(manager);
    let _ = std::fs::remove_dir_all(path);
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
