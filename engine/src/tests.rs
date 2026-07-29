use std::collections::BTreeSet;

use super::*;
use arrow_array::{Array, BinaryArray, Int64Array, StringArray};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase};
use tokio::sync::Notify;

struct FakeEmbedder;

impl EmbeddingProvider for FakeEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move { Ok(texts.iter().map(|_| vec![0.25; 2048]).collect()) })
    }
}

struct BlockingEmbedder {
    started: Arc<Notify>,
    release: Arc<Notify>,
}

impl EmbeddingProvider for BlockingEmbedder {
    fn get_embeddings<'a>(
        &'a self,
        texts: &'a [String],
    ) -> BoxFuture<'a, Result<Vec<Vec<f32>>, String>> {
        Box::pin(async move {
            self.started.notify_one();
            self.release.notified().await;
            Ok(texts.iter().map(|_| vec![0.25; 2048]).collect())
        })
    }
}

struct FaultingReplacementMutationBoundary {
    fail_at: ReplacementMutation,
}

impl FaultingReplacementMutationBoundary {
    fn new(fail_at: ReplacementMutation) -> Self {
        Self { fail_at }
    }
}

impl ReplacementMutationBoundary for FaultingReplacementMutationBoundary {
    fn delete<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        predicate: &'a str,
    ) -> BoxFuture<'a, Result<(), String>> {
        if boundary == self.fail_at {
            return Box::pin(async move {
                Err(format!("injected replacement failure at {boundary:?}"))
            });
        }
        LanceDbReplacementMutationBoundary.delete(boundary, table, predicate)
    }

    fn add<'a>(
        &self,
        boundary: ReplacementMutation,
        table: &'a Table,
        batch: RecordBatch,
    ) -> BoxFuture<'a, Result<(), String>> {
        if boundary == self.fail_at {
            return Box::pin(async move {
                Err(format!("injected replacement failure at {boundary:?}"))
            });
        }
        LanceDbReplacementMutationBoundary.add(boundary, table, batch)
    }
}

fn database_path(test_name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-worker-{test_name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

async fn query_rows(table: &Table, predicate: &str) -> Vec<RecordBatch> {
    table
        .query()
        .only_if(predicate)
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap()
}

fn row_count(rows: &[RecordBatch]) -> usize {
    rows.iter().map(RecordBatch::num_rows).sum()
}

fn string_values(rows: &[RecordBatch], column: &str) -> BTreeSet<String> {
    rows.iter()
        .flat_map(|batch| {
            batch
                .column_by_name(column)
                .unwrap()
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap()
                .iter()
                .map(|value| value.unwrap().to_owned())
                .collect::<Vec<_>>()
        })
        .collect()
}

fn int64_values(rows: &[RecordBatch], column: &str) -> BTreeSet<i64> {
    rows.iter()
        .flat_map(|batch| {
            batch
                .column_by_name(column)
                .unwrap()
                .as_any()
                .downcast_ref::<Int64Array>()
                .unwrap()
                .iter()
                .map(|value| value.unwrap())
                .collect::<Vec<_>>()
        })
        .collect()
}

fn int32_values(rows: &[RecordBatch], column: &str) -> BTreeSet<i32> {
    rows.iter()
        .flat_map(|batch| {
            batch
                .column_by_name(column)
                .unwrap()
                .as_any()
                .downcast_ref::<Int32Array>()
                .unwrap()
                .iter()
                .map(|value| value.unwrap())
                .collect::<Vec<_>>()
        })
        .collect()
}

fn null_count(rows: &[RecordBatch], column: &str) -> usize {
    rows.iter()
        .map(|batch| batch.column_by_name(column).unwrap().null_count())
        .sum()
}

fn binary_hash(rows: &[RecordBatch], column: &str) -> u64 {
    let values = rows
        .iter()
        .flat_map(|batch| {
            batch
                .column_by_name(column)
                .unwrap()
                .as_any()
                .downcast_ref::<BinaryArray>()
                .unwrap()
                .iter()
                .map(|value| {
                    let mut hasher = DefaultHasher::new();
                    value.unwrap().hash(&mut hasher);
                    hasher.finish()
                })
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();
    assert_eq!(values.len(), 1);
    values[0]
}

#[derive(Debug, Eq, PartialEq)]
struct CanonicalState {
    raw_hash: u64,
    node_ids: BTreeSet<String>,
    node_indexes: BTreeSet<i32>,
    edge_ids: BTreeSet<String>,
    edge_sources: BTreeSet<String>,
    edge_targets: BTreeSet<String>,
    generations: BTreeSet<i64>,
    summary_null_count: usize,
}

async fn canonical_state(database: &DatabaseManager, document_id: &str) -> CanonicalState {
    let predicate = format!("document_id = '{}'", sql_string(document_id));
    let documents = query_rows(&database.documents_table().await.unwrap(), &predicate).await;
    let nodes = query_rows(&database.nodes_table().await.unwrap(), &predicate).await;
    let edges = query_rows(&database.edges_table().await.unwrap(), &predicate).await;
    assert_eq!(row_count(&documents), 1);
    CanonicalState {
        raw_hash: binary_hash(&documents, "raw_content"),
        node_ids: string_values(&nodes, "chunk_id"),
        node_indexes: int32_values(&nodes, "chunk_index"),
        edge_ids: string_values(&edges, "edge_id"),
        edge_sources: string_values(&edges, "source_node_id"),
        edge_targets: string_values(&edges, "target_node_id"),
        generations: int64_values(&nodes, "ingested_at"),
        summary_null_count: null_count(&nodes, "summary"),
    }
}

async fn stage_document(database: &DatabaseManager, document_id: &str, raw_data: &[u8]) {
    let table = database.staged_documents_table().await.unwrap();
    let batch = RecordBatch::try_new(
        table.schema().await.unwrap(),
        vec![
            Arc::new(StringArray::from(vec![document_id])),
            Arc::new(BinaryArray::from_vec(vec![raw_data])),
        ],
    )
    .unwrap();
    table.add(batch).execute().await.unwrap();
}

#[tokio::test]
async fn replacement_documents_add_failure_rolls_back_and_retry_converges() {
    let path = database_path("documents-add-failure");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let document_id = Uuid::new_v4().to_string();
    let old_job = IngestionJob::new(
        document_id.clone(),
        "old.md".into(),
        b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
        HashMap::new(),
    );
    let (_, old_chunks) = chunk_ingestion_job(&old_job);
    let old_embeddings = vec![vec![0.25; 2048]; old_chunks.len()];
    replace_document(&database, &old_job, &old_chunks, &old_embeddings)
        .await
        .unwrap();
    stage_document(&database, &document_id, b"replacement staging row").await;
    let old_state = canonical_state(&database, &document_id).await;

    let replacement_job = IngestionJob::new(
        document_id.clone(),
        "replacement.md".into(),
        b"# Replacement\n\nnew content\n\n# Other\n\nmore content".to_vec(),
        HashMap::new(),
    );
    let (_, replacement_chunks) = chunk_ingestion_job(&replacement_job);
    let replacement_embeddings = vec![vec![0.75; 2048]; replacement_chunks.len()];
    let failure = FaultingReplacementMutationBoundary::new(ReplacementMutation::DocumentsAdd);

    let error = replace_document_with_faults(
        &database,
        &replacement_job,
        &replacement_chunks,
        &replacement_embeddings,
        &failure,
    )
    .await
    .unwrap_err();
    assert!(error.contains("DocumentsAdd"));
    assert_eq!(canonical_state(&database, &document_id).await, old_state);
    assert_eq!(
        database
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{document_id}'")))
            .await
            .unwrap(),
        1
    );

    std::thread::sleep(std::time::Duration::from_millis(2));
    replace_document(
        &database,
        &replacement_job,
        &replacement_chunks,
        &replacement_embeddings,
    )
    .await
    .unwrap();
    let replacement_state = canonical_state(&database, &document_id).await;
    assert_ne!(replacement_state.raw_hash, old_state.raw_hash);
    assert_ne!(replacement_state.generations, old_state.generations);
    assert_eq!(replacement_state.node_ids.len(), replacement_chunks.len());
    assert_eq!(replacement_state.generations.len(), 1);
    assert_eq!(
        database
            .staged_documents_table()
            .await
            .unwrap()
            .count_rows(Some(format!("document_id = '{document_id}'")))
            .await
            .unwrap(),
        0
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn replacement_failure_boundaries_preserve_prior_generation_and_retry_converges() {
    let boundaries = [
        ReplacementMutation::EdgesDelete,
        ReplacementMutation::NodesDelete,
        ReplacementMutation::DocumentsDelete,
        ReplacementMutation::DocumentsAdd,
        ReplacementMutation::NodesAdd,
        ReplacementMutation::EdgesAdd,
        ReplacementMutation::StagingDelete,
    ];
    for boundary in boundaries {
        let path = database_path(&format!("boundary-{boundary:?}"));
        let database = DatabaseManager::initialize(&path).await.unwrap();
        let document_id = Uuid::new_v4().to_string();
        let old_job = IngestionJob::new(
            document_id.clone(),
            "old.md".into(),
            b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
            HashMap::new(),
        );
        let (_, old_chunks) = chunk_ingestion_job(&old_job);
        let old_embeddings = vec![vec![0.25; 2048]; old_chunks.len()];
        replace_document(&database, &old_job, &old_chunks, &old_embeddings)
            .await
            .unwrap();
        stage_document(&database, &document_id, b"replacement staging row").await;
        let old_state = canonical_state(&database, &document_id).await;
        assert_eq!(old_state.edge_ids.len(), 3);
        assert_eq!(old_state.summary_null_count, old_state.node_ids.len());

        let replacement_job = IngestionJob::new(
            document_id.clone(),
            "replacement.md".into(),
            b"# Three\n\nnew content\n\n# Four\n\nmore content".to_vec(),
            HashMap::new(),
        );
        let (_, replacement_chunks) = chunk_ingestion_job(&replacement_job);
        let replacement_embeddings = vec![vec![0.75; 2048]; replacement_chunks.len()];
        let failure = FaultingReplacementMutationBoundary::new(boundary);
        let error = replace_document_with_faults(
            &database,
            &replacement_job,
            &replacement_chunks,
            &replacement_embeddings,
            &failure,
        )
        .await
        .unwrap_err();
        assert!(error.contains(&format!("{boundary:?}")));
        assert_eq!(canonical_state(&database, &document_id).await, old_state);
        assert_eq!(
            database
                .staged_documents_table()
                .await
                .unwrap()
                .count_rows(Some(format!("document_id = '{document_id}'")))
                .await
                .unwrap(),
            1
        );

        std::thread::sleep(std::time::Duration::from_millis(2));
        replace_document(
            &database,
            &replacement_job,
            &replacement_chunks,
            &replacement_embeddings,
        )
        .await
        .unwrap();
        let current = canonical_state(&database, &document_id).await;
        let expected_indexes = (0..replacement_chunks.len())
            .map(|index| i32::try_from(index).unwrap())
            .collect::<BTreeSet<_>>();
        assert_ne!(current.raw_hash, old_state.raw_hash);
        assert_eq!(current.node_indexes, expected_indexes);
        assert_eq!(current.node_ids.len(), replacement_chunks.len());
        assert_eq!(current.edge_ids.len(), current.edge_sources.len());
        assert_eq!(current.edge_ids.len(), current.edge_targets.len());
        assert!(current.edge_sources.is_subset(&current.node_ids));
        assert!(current.edge_targets.is_subset(&current.node_ids));
        assert_eq!(current.generations.len(), 1);
        assert_eq!(current.summary_null_count, current.node_ids.len());
        assert_eq!(
            database
                .staged_documents_table()
                .await
                .unwrap()
                .count_rows(Some(format!("document_id = '{document_id}'")))
                .await
                .unwrap(),
            0
        );
        let _ = std::fs::remove_dir_all(path);
    }
}

#[tokio::test]
async fn persisted_node_summary_is_arrow_null() {
    let path = database_path("summary-null");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let _repeated = DatabaseManager::initialize(&path).await.unwrap();
    let first_connection = lancedb::connect(&path).execute().await.unwrap();
    let second_connection = lancedb::connect(&path).execute().await.unwrap();
    assert_eq!(
        first_connection
            .open_table("communities")
            .execute()
            .await
            .unwrap()
            .count_rows(None)
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        second_connection
            .open_table("communities")
            .execute()
            .await
            .unwrap()
            .count_rows(None)
            .await
            .unwrap(),
        0
    );
    let empty_job = IngestionJob::new(
        Uuid::new_v4().to_string(),
        "empty.md".into(),
        Vec::new(),
        HashMap::new(),
    );
    let (_, empty_chunks) = chunk_ingestion_job(&empty_job);
    assert!(empty_chunks.is_empty());
    replace_document(&database, &empty_job, &empty_chunks, &[])
        .await
        .unwrap();
    let empty_predicate = format!("document_id = '{}'", sql_string(&empty_job.document_id));
    assert_eq!(
        database
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(empty_predicate.clone()))
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        database
            .nodes_table()
            .await
            .unwrap()
            .count_rows(Some(empty_predicate.clone()))
            .await
            .unwrap(),
        0
    );
    assert_eq!(
        database
            .edges_table()
            .await
            .unwrap()
            .count_rows(Some(empty_predicate))
            .await
            .unwrap(),
        0
    );
    let document_id = Uuid::new_v4().to_string();
    let job = IngestionJob::new(
        document_id,
        "summary.md".into(),
        b"# Summary\n\ncontent".to_vec(),
        HashMap::new(),
    );
    let (_, chunks) = chunk_ingestion_job(&job);
    let embeddings = vec![vec![0.25; 2048]; chunks.len()];
    replace_document(&database, &job, &chunks, &embeddings)
        .await
        .unwrap();
    let rows = query_rows(
        &database.nodes_table().await.unwrap(),
        &format!("document_id = '{}'", sql_string(&job.document_id)),
    )
    .await;
    let summary = rows[0]
        .column_by_name("summary")
        .unwrap()
        .as_any()
        .downcast_ref::<StringArray>()
        .unwrap();
    assert_eq!(summary.null_count(), row_count(&rows));
    let summary_field = database
        .nodes_table()
        .await
        .unwrap()
        .schema()
        .await
        .unwrap()
        .field_with_name("summary")
        .unwrap()
        .clone();
    assert!(summary_field.is_nullable());
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn worker_indexes_jobs_and_records_real_chunk_count() {
    let path = database_path("indexes");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(FakeEmbedder),
        shutdown_rx,
    );
    let document_id = Uuid::new_v4().to_string();
    sender
        .send(IngestionJob::new(
            document_id.clone(),
            "document.md".into(),
            b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    drop(sender);
    worker.await.unwrap();
    let state = statuses.get(&document_id).unwrap();
    assert_eq!(state.status, "completed");
    assert_eq!(state.chunk_count, 4);
    drop(state);
    let nodes = database.nodes_table().await.unwrap();
    assert_eq!(nodes.count_rows(None).await.unwrap(), 4);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn worker_replaces_existing_document_rows() {
    let path = database_path("replace");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (_shutdown_tx, shutdown_rx) = watch::channel(false);
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database.clone(),
        Arc::new(FakeEmbedder),
        shutdown_rx,
    );
    let document_id = Uuid::new_v4().to_string();
    for raw_data in [
        b"# One\n\nfirst\n\n# Two\n\nsecond".to_vec(),
        b"replacement".to_vec(),
    ] {
        sender
            .send(IngestionJob::new(
                document_id.clone(),
                "document.md".into(),
                raw_data,
                HashMap::new(),
            ))
            .await
            .unwrap();
    }
    drop(sender);
    worker.await.unwrap();

    let predicate = format!("document_id = '{document_id}'");
    assert_eq!(
        database
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(predicate.clone()))
            .await
            .unwrap(),
        1
    );
    assert_eq!(
        database
            .nodes_table()
            .await
            .unwrap()
            .count_rows(Some(predicate))
            .await
            .unwrap(),
        1
    );
    let state = statuses.get(&document_id).unwrap();
    assert_eq!(state.status, "completed");
    assert_eq!(state.chunk_count, 1);
    drop(state);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn schema_field_lookup_failure_rolls_back_and_retry_converges() {
    let path = database_path("schema-lookup-fault");
    let database = DatabaseManager::initialize(&path).await.unwrap();

    let document_id = Uuid::new_v4().to_string();
    let job = IngestionJob::new(
        document_id.clone(),
        "doc.md".into(),
        b"# Section\n\ncontent".to_vec(),
        HashMap::new(),
    );
    let (_, chunks) = chunk_ingestion_job(&job);
    let embeddings = vec![vec![0.25; 2048]; chunks.len()];

    replace_document(&database, &job, &chunks, &embeddings)
        .await
        .unwrap();

    let predicate = format!("document_id = '{document_id}'");
    assert_eq!(
        database
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(predicate.clone()))
            .await
            .unwrap(),
        1
    );

    let failure = FaultingReplacementMutationBoundary::new(ReplacementMutation::NodesAdd);
    let res = replace_document_with_faults(&database, &job, &chunks, &embeddings, &failure).await;
    assert!(res.is_err());
    let err = res.unwrap_err();
    assert!(err.contains("NodesAdd"));

    assert_eq!(
        database
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(predicate.clone()))
            .await
            .unwrap(),
        1
    );

    replace_document(&database, &job, &chunks, &embeddings)
        .await
        .unwrap();

    assert_eq!(
        database
            .documents_table()
            .await
            .unwrap()
            .count_rows(Some(predicate.clone()))
            .await
            .unwrap(),
        1
    );

    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn shutdown_waits_for_active_document_to_finish() {
    let path = database_path("shutdown");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let statuses = Arc::new(DashMap::new());
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let (shutdown_tx, shutdown_rx) = watch::channel(false);
    let started = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let worker = spawn_worker(
        receiver,
        statuses.clone(),
        database,
        Arc::new(BlockingEmbedder {
            started: started.clone(),
            release: release.clone(),
        }),
        shutdown_rx,
    );
    let document_id = Uuid::new_v4().to_string();
    sender
        .send(IngestionJob::new(
            document_id.clone(),
            "document.md".into(),
            b"active document".to_vec(),
            HashMap::new(),
        ))
        .await
        .unwrap();
    started.notified().await;
    shutdown_tx.send(true).unwrap();
    release.notify_one();
    worker.await.unwrap();

    assert_eq!(statuses.get(&document_id).unwrap().status, "completed");
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn bounded_queue_rejects_work_when_full() {
    let (sender, _receiver) = mpsc::channel(1);
    sender
        .try_send(IngestionJob::new(
            "one".into(),
            "one.txt".into(),
            vec![b'x'],
            HashMap::new(),
        ))
        .unwrap();
    assert!(sender
        .try_send(IngestionJob::new(
            "two".into(),
            "two.txt".into(),
            vec![b'y'],
            HashMap::new(),
        ))
        .is_err());
}

#[test]
fn json_forces_fixed_size_and_populates_token_counts() {
    let job = IngestionJob::new(
        "json".into(),
        "DATA.JSON".into(),
        br##"{"heading":"# not markdown"}"##.to_vec(),
        HashMap::from([
            ("chunk_strategy".into(), "structure-aware".into()),
            ("chunk_size".into(), "10".into()),
            ("chunk_overlap".into(), "2".into()),
        ]),
    );
    let (strategy, chunks) = chunk_ingestion_job(&job);
    assert_eq!(strategy, "fixed-size");
    assert!(chunks.len() > 1);
    assert!(chunks.iter().all(|chunk| chunk.section_path.is_none()));
    assert!(chunks.iter().all(|chunk| chunk.estimated_tokens > 0));
}

#[test]
fn empty_strategy_defaults_to_structure_aware() {
    let job = IngestionJob::new(
        "markdown".into(),
        "guide.md".into(),
        b"# Setup\n\nInstall it.".to_vec(),
        HashMap::new(),
    );
    let (strategy, chunks) = chunk_ingestion_job(&job);
    assert_eq!(strategy, "structure-aware");
    assert!(chunks
        .iter()
        .any(|chunk| chunk.section_path.as_deref() == Some("/Setup")));
}

#[test]
fn rejects_non_v4_document_ids() {
    assert!(validate_document_id("not-a-uuid").is_err());
    assert!(validate_document_id("00000000-0000-1000-8000-000000000000").is_err());
    assert!(validate_document_id(&Uuid::new_v4().to_string()).is_ok());
}

#[test]
fn chunk_metadata_contract_valid_custom_settings() {
    let metadata = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "800".into()),
        ("chunk_overlap".into(), "100".into()),
    ]);
    let settings = parse_chunk_settings(&metadata).unwrap();
    assert_eq!(
        settings,
        ChunkSettings {
            strategy: "fixed-size".into(),
            size: 800,
            overlap: 100,
        }
    );
    let job = IngestionJob::new(
        "doc-1".into(),
        "notes.txt".into(),
        b"some long content for chunking test".to_vec(),
        metadata,
    );
    let (strategy, chunks) = chunk_ingestion_job(&job);
    assert_eq!(strategy, "fixed-size");
    assert!(!chunks.is_empty());
}

#[test]
fn chunk_metadata_contract_invalid_metadata_rejected() {
    let missing_key = HashMap::from([("chunk_strategy".into(), "fixed-size".into())]);
    assert!(parse_chunk_settings(&missing_key).is_err());

    let invalid_strategy = HashMap::from([
        ("chunk_strategy".into(), "recursive".into()),
        ("chunk_size".into(), "500".into()),
        ("chunk_overlap".into(), "50".into()),
    ]);
    assert!(parse_chunk_settings(&invalid_strategy).is_err());

    let zero_size = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "0".into()),
        ("chunk_overlap".into(), "0".into()),
    ]);
    assert!(parse_chunk_settings(&zero_size).is_err());

    let overlap_too_large = HashMap::from([
        ("chunk_strategy".into(), "fixed-size".into()),
        ("chunk_size".into(), "500".into()),
        ("chunk_overlap".into(), "500".into()),
    ]);
    assert!(parse_chunk_settings(&overlap_too_large).is_err());
}

