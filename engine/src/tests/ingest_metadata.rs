//! Tests for the evidence-metadata store side of lever 3 (Phase 06.3.6 plan 14, D-144, D-168).
//!
//! Every test runs on a temporary store: nothing here opens a configured store. The module covers
//! the 22-column `nodes` schema, ingest persistence, the 10-column staging schema with both legacy
//! upgrades, the engine's re-validation of the three ingest keys, and the production scan that
//! builds the per-snapshot `DocMetaMap`.

use std::collections::HashMap;
use std::sync::Arc;

use arrow_array::types::Float32Type;
use arrow_array::{
    Array, BinaryArray, FixedSizeListArray, Int32Array, Int64Array, RecordBatch, StringArray,
};
use arrow_schema::DataType;
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use uuid::Uuid;

use crate::chunker::Chunk;
use crate::config::EffectiveRagSettings;
use crate::db::backfill::{
    backfill_nodes_metadata, backfill_with, classify_nodes_schema, column_digest, data_file_hashes,
    legacy_nodes_schema_v19, verify_backfill_on_copy, NodesSchemaState, Sidecar, SidecarRow,
};
use crate::db::{
    legacy_staged_documents_v2_schema, nodes_schema, staged_documents_v2_pre_metadata_schema,
    staged_documents_v2_schema, DatabaseManager,
};
use crate::doc_meta::{DocMeta, DocMetaMap};
use crate::ingest::{
    load_doc_meta, persist_raw_with_boundary, process_job, read_staged_jobs, replace_document,
    IngestionJob, LanceDbReplacementMutationBoundary,
};
use crate::pb::lancet::v1::Lever;
use crate::rerank;
use crate::service::{validate_ingest_metadata, MAX_DOC_TITLE_CHARS, MAX_SOURCE_CHARS};
use crate::tests::{configured_service, FakeEmbedder, RecordingGenerator};

const DOC: &str = "00000000-0000-4000-8000-0000000000e1";
const METADATA_COLUMNS: [&str; 3] = ["doc_title", "source", "published_date"];

fn store_path(name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-ingestmeta-{name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

fn chunk_settings() -> HashMap<String, String> {
    HashMap::from([
        ("chunk_strategy".to_owned(), "fixed-size".to_owned()),
        ("chunk_size".to_owned(), "500".to_owned()),
        ("chunk_overlap".to_owned(), "50".to_owned()),
    ])
}

fn job_with(document_id: &str, extra: &[(&str, &str)]) -> IngestionJob {
    let mut metadata = chunk_settings();
    for (key, value) in extra {
        metadata.insert((*key).to_owned(), (*value).to_owned());
    }
    IngestionJob::new(
        document_id.to_owned(),
        "report.md".to_owned(),
        b"A short document body that fits one chunk.".to_vec(),
        metadata,
    )
}

fn full_metadata() -> [(&'static str, &'static str); 3] {
    [
        ("doc_title", "Hamas' surprise attack: \"intel failure\""),
        ("source", "The Verge"),
        ("published_date", "2023-10-07"),
    ]
}

fn two_chunks() -> Vec<Chunk> {
    ["first chunk", "second chunk"]
        .iter()
        .enumerate()
        .map(|(index, content)| Chunk {
            content: (*content).to_owned(),
            char_start: index * 20,
            char_end: index * 20 + 11,
            section_path: None,
            estimated_tokens: 2,
        })
        .collect()
}

/// `(chunk_id, title, doc_title, source, published_date)` of every `nodes` row, by chunk id.
type MetadataRow = (
    String,
    Option<String>,
    Option<String>,
    Option<String>,
    Option<String>,
);

async fn metadata_rows(database: &DatabaseManager) -> Vec<MetadataRow> {
    let nodes = database.nodes_table().await.unwrap();
    let schema = nodes.schema().await.unwrap();
    for column in METADATA_COLUMNS {
        assert!(
            schema.field_with_name(column).is_ok(),
            "the nodes table must carry the {column} column"
        );
    }
    let batches: Vec<RecordBatch> = nodes
        .query()
        .select(Select::columns(&[
            "chunk_id",
            "title",
            "doc_title",
            "source",
            "published_date",
        ]))
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();
    let mut rows = Vec::new();
    for batch in &batches {
        let column = |index: usize| {
            batch
                .column(index)
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap()
        };
        let optional = |array: &StringArray, row: usize| {
            (!array.is_null(row)).then(|| array.value(row).to_owned())
        };
        for row in 0..batch.num_rows() {
            rows.push((
                column(0).value(row).to_owned(),
                optional(column(1), row),
                optional(column(2), row),
                optional(column(3), row),
                optional(column(4), row),
            ));
        }
    }
    rows.sort();
    rows
}

// ---- schema ---------------------------------------------------------------------------------

#[test]
fn nodes_schema_ends_with_the_three_nullable_metadata_columns() {
    let schema = nodes_schema();
    assert_eq!(schema.fields().len(), 22, "19 legacy columns plus three");
    assert_eq!(schema.field(18).name(), "content_type");
    for (offset, name) in METADATA_COLUMNS.iter().enumerate() {
        let field = schema.field(19 + offset);
        assert_eq!(field.name(), name);
        assert_eq!(field.data_type(), &DataType::Utf8);
        assert!(field.is_nullable(), "{name} must be nullable (SC-4)");
    }
    assert_eq!(
        &schema.fields()[..19],
        legacy_nodes_schema_v19().fields().as_ref(),
        "the first 19 columns are the legacy schema, unchanged and in order"
    );
}

#[test]
fn the_staging_schema_appends_the_same_three_nullable_columns() {
    let pre = staged_documents_v2_pre_metadata_schema();
    assert_eq!(pre.fields().len(), 7);
    assert_eq!(pre.field(6).name(), "generation");
    let schema = staged_documents_v2_schema();
    assert_eq!(schema.fields().len(), 10);
    assert_eq!(
        &schema.fields()[..7],
        pre.fields().as_ref(),
        "the pre-metadata form is the first seven columns of the current form"
    );
    for (offset, name) in METADATA_COLUMNS.iter().enumerate() {
        let field = schema.field(7 + offset);
        assert_eq!(field.name(), name);
        assert_eq!(field.data_type(), &DataType::Utf8);
        assert!(field.is_nullable());
    }
    assert!(!schema.field_with_name("generation").unwrap().is_nullable());
}

// ---- ingest persistence ---------------------------------------------------------------------

#[tokio::test]
async fn ingest_stores_the_three_values_on_every_chunk_row_and_keeps_the_title() {
    let path = store_path("persist");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let job = job_with(DOC, &full_metadata());
    replace_document(
        &database,
        &job,
        &two_chunks(),
        &vec![vec![0.5; 2048]; 2],
        "model-x",
    )
    .await
    .unwrap();

    let rows = metadata_rows(&database).await;
    assert_eq!(rows.len(), 2);
    for (chunk_id, title, doc_title, source, published) in &rows {
        assert!(chunk_id.starts_with(DOC));
        assert_eq!(
            title.as_deref(),
            Some("report.md"),
            "title is the filename, untouched"
        );
        assert_eq!(
            doc_title.as_deref(),
            Some("Hamas' surprise attack: \"intel failure\"")
        );
        assert_eq!(source.as_deref(), Some("The Verge"));
        assert_eq!(published.as_deref(), Some("2023-10-07"));
    }
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn ingest_without_the_keys_stores_nulls_and_does_not_fail() {
    let path = store_path("absent");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let job = job_with(DOC, &[]);
    replace_document(
        &database,
        &job,
        &two_chunks(),
        &vec![vec![0.5; 2048]; 2],
        "model-x",
    )
    .await
    .unwrap();
    let rows = metadata_rows(&database).await;
    assert_eq!(rows.len(), 2);
    for (_, title, doc_title, source, published) in rows {
        assert_eq!(title.as_deref(), Some("report.md"));
        assert_eq!((doc_title, source, published), (None, None, None));
    }
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn an_empty_value_is_stored_as_null_never_as_an_empty_string() {
    let path = store_path("empty-value");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let job = job_with(
        DOC,
        &[
            ("doc_title", ""),
            ("source", "Wired"),
            ("published_date", ""),
        ],
    );
    replace_document(
        &database,
        &job,
        &two_chunks()[..1],
        &[vec![0.5; 2048]],
        "model-x",
    )
    .await
    .unwrap();
    let rows = metadata_rows(&database).await;
    assert_eq!(rows.len(), 1);
    let (_, _, doc_title, source, published) = rows.into_iter().next().unwrap();
    assert_eq!(doc_title, None);
    assert_eq!(source.as_deref(), Some("Wired"));
    assert_eq!(published, None);
    let _ = std::fs::remove_dir_all(path);
}

// ---- engine re-validation -------------------------------------------------------------------

fn metadata_of(pairs: &[(&str, String)]) -> HashMap<String, String> {
    let mut metadata = chunk_settings();
    for (key, value) in pairs {
        metadata.insert((*key).to_owned(), value.clone());
    }
    metadata
}

#[test]
fn the_engine_refuses_bad_metadata_values_with_invalid_argument() {
    let refused: Vec<(&str, &str, String)> = vec![
        (
            "an impossible calendar date",
            "published_date",
            "2023-02-30".into(),
        ),
        (
            "a date with a time",
            "published_date",
            "2023-10-07T15:37:43".into(),
        ),
        ("a slash date", "published_date", "07/10/2023".into()),
        ("an unpadded date", "published_date", "2023-1-5".into()),
        ("month 13", "published_date", "2023-13-01".into()),
        ("month 0", "published_date", "2023-00-10".into()),
        ("day 0", "published_date", "2023-10-00".into()),
        ("April 31", "published_date", "2023-04-31".into()),
        (
            "February 29 of a common year",
            "published_date",
            "2023-02-29".into(),
        ),
        (
            "century year that is not a leap year",
            "published_date",
            "1900-02-29".into(),
        ),
        (
            "a non-ASCII digit",
            "published_date",
            "2023-1\u{0660}-01".into(),
        ),
        (
            "a title over the limit",
            "doc_title",
            "t".repeat(MAX_DOC_TITLE_CHARS + 1),
        ),
        (
            "a multi-byte title over the limit",
            "doc_title",
            "\u{e9}".repeat(MAX_DOC_TITLE_CHARS + 1),
        ),
        (
            "a source over the limit",
            "source",
            "s".repeat(MAX_SOURCE_CHARS + 1),
        ),
        (
            "a control character in the title",
            "doc_title",
            "bad\u{7}title".into(),
        ),
        ("a newline in the title", "doc_title", "two\nlines".into()),
        (
            "a control character in the source",
            "source",
            "Wired\u{0}".into(),
        ),
    ];
    for (label, key, value) in refused {
        let error =
            validate_ingest_metadata(&metadata_of(&[(key, value.clone())])).expect_err(label);
        assert_eq!(error.code(), tonic::Code::InvalidArgument, "{label}");
        assert!(
            error.message().contains(key),
            "{label}: the error names the key `{key}`: {}",
            error.message()
        );
        let probe: String = value.chars().take(8).collect();
        assert!(
            probe.trim().is_empty() || !error.message().contains(&probe),
            "{label}: the error must not echo the value"
        );
    }
}

#[test]
fn the_engine_accepts_values_at_the_limits_and_absent_keys() {
    assert!(
        validate_ingest_metadata(&chunk_settings()).is_ok(),
        "no keys"
    );
    let accepted: Vec<(&str, String)> = vec![
        ("doc_title", "\u{e9}".repeat(MAX_DOC_TITLE_CHARS)),
        ("source", "s".repeat(MAX_SOURCE_CHARS)),
        ("published_date", "2024-02-29".into()),
        ("published_date", "2000-02-29".into()),
        ("published_date", "2023-12-31".into()),
        ("doc_title", String::new()),
        ("source", String::new()),
        ("published_date", String::new()),
    ];
    for (key, value) in accepted {
        assert!(
            validate_ingest_metadata(&metadata_of(&[(key, value.clone())])).is_ok(),
            "{key} = {:?} must be accepted",
            value.chars().take(12).collect::<String>()
        );
    }
}

#[test]
fn ingest_document_validates_the_metadata_before_any_write() {
    let source = include_str!("../service.rs");
    let start = source
        .find("async fn ingest_document(")
        .expect("ingest_document must exist");
    let body = &source[start..];
    let validate = body
        .find("validate_ingest_metadata(&metadata)?")
        .expect("ingest_document must call validate_ingest_metadata");
    let persist = body
        .find("self.persist_raw(&job)")
        .expect("ingest_document must persist the raw staging row");
    assert!(
        validate < persist,
        "the metadata is validated before the staging row is written"
    );
}

// ---- staging upgrades (D-168) ---------------------------------------------------------------

fn legacy_batch(include_generation: bool, generation: i64) -> RecordBatch {
    let mut columns: Vec<Arc<dyn Array>> = vec![
        Arc::new(StringArray::from(vec![DOC])),
        Arc::new(StringArray::from(vec!["legacy.md"])),
        Arc::new(BinaryArray::from_vec(vec![b"legacy body"])),
        Arc::new(StringArray::from(vec!["fixed-size"])),
        Arc::new(Int32Array::from(vec![500])),
        Arc::new(Int32Array::from(vec![50])),
    ];
    let schema = if include_generation {
        columns.push(Arc::new(Int64Array::from(vec![generation])));
        staged_documents_v2_pre_metadata_schema()
    } else {
        legacy_staged_documents_v2_schema()
    };
    RecordBatch::try_new(schema, columns).unwrap()
}

async fn upgrade_staging(form: &str, populated: bool) {
    let include_generation = form == "seven";
    let path = store_path(&format!("staging-{form}-{populated}"));
    let schema = if include_generation {
        staged_documents_v2_pre_metadata_schema()
    } else {
        legacy_staged_documents_v2_schema()
    };
    let connection = lancedb::connect(&path).execute().await.unwrap();
    let table = connection
        .create_empty_table("staged_documents_v2", schema)
        .execute()
        .await
        .unwrap();
    if populated {
        table
            .add(legacy_batch(include_generation, 3))
            .execute()
            .await
            .unwrap();
    }

    let database = DatabaseManager::initialize(&path).await.unwrap();
    let upgraded = database.staged_documents_table().await.unwrap();
    let actual = upgraded.schema().await.unwrap();
    assert_eq!(
        actual.fields().len(),
        10,
        "{form} form, populated {populated}"
    );
    assert_eq!(
        actual.fields(),
        staged_documents_v2_schema().fields(),
        "{form} form, populated {populated}: strict equality with the 10-column schema"
    );
    assert_eq!(
        upgraded.count_rows(None).await.unwrap(),
        usize::from(populated)
    );
    if populated {
        let batches: Vec<RecordBatch> = upgraded
            .query()
            .execute()
            .await
            .unwrap()
            .try_collect()
            .await
            .unwrap();
        let batch = &batches[0];
        let generation = batch
            .column_by_name("generation")
            .unwrap()
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap()
            .value(0);
        assert_eq!(generation, if include_generation { 3 } else { 1 });
        for column in METADATA_COLUMNS {
            assert!(
                batch.column_by_name(column).unwrap().is_null(0),
                "{column} is null on a legacy row"
            );
        }
    }
    // A second start finds nothing to upgrade.
    DatabaseManager::initialize(&path).await.unwrap();
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn the_six_column_staging_table_upgrades_to_ten_columns_empty() {
    upgrade_staging("six", false).await;
}

#[tokio::test]
async fn the_six_column_staging_table_upgrades_to_ten_columns_with_rows() {
    upgrade_staging("six", true).await;
}

#[tokio::test]
async fn the_seven_column_staging_table_upgrades_to_ten_columns_empty() {
    upgrade_staging("seven", false).await;
}

#[tokio::test]
async fn the_seven_column_staging_table_upgrades_to_ten_columns_with_rows() {
    upgrade_staging("seven", true).await;
}

#[tokio::test]
async fn staged_recovery_carries_the_three_keys_back_into_the_ingest_metadata() {
    let path = store_path("recovery");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let staged = database.staged_documents_table().await.unwrap();
    let job = job_with(DOC, &full_metadata());
    persist_raw_with_boundary(&staged, &job, &LanceDbReplacementMutationBoundary)
        .await
        .unwrap();

    let recovered = read_staged_jobs(&database).await.unwrap();
    assert_eq!(recovered.len(), 1);
    for (key, value) in full_metadata() {
        assert_eq!(
            recovered[0].metadata.get(key).map(String::as_str),
            Some(value),
            "{key} survives staged recovery"
        );
    }

    process_job(&recovered[0], &database, &FakeEmbedder)
        .await
        .unwrap();
    let rows = metadata_rows(&database).await;
    assert!(!rows.is_empty());
    for (_, _, doc_title, source, published) in rows {
        assert_eq!(
            doc_title.as_deref(),
            Some("Hamas' surprise attack: \"intel failure\"")
        );
        assert_eq!(source.as_deref(), Some("The Verge"));
        assert_eq!(published.as_deref(), Some("2023-10-07"));
    }
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_document_staged_without_the_keys_recovers_without_them() {
    let path = store_path("recovery-absent");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    let staged = database.staged_documents_table().await.unwrap();
    persist_raw_with_boundary(
        &staged,
        &job_with(DOC, &[]),
        &LanceDbReplacementMutationBoundary,
    )
    .await
    .unwrap();
    let recovered = read_staged_jobs(&database).await.unwrap();
    assert_eq!(recovered.len(), 1);
    for key in METADATA_COLUMNS {
        assert!(
            !recovered[0].metadata.contains_key(key),
            "{key} stays absent"
        );
    }
    let _ = std::fs::remove_dir_all(path);
}

// ---- fail closed on an old store (C3, C4) ---------------------------------------------------

#[tokio::test]
async fn a_nineteen_column_nodes_table_fails_initialize_and_open_closed_and_leaves_staging_alone() {
    let path = store_path("failclosed");
    DatabaseManager::initialize(&path).await.unwrap();
    // Turn the store into an old one: `nodes` back to 19 columns, staging back to 7 columns.
    let connection = lancedb::connect(&path).execute().await.unwrap();
    connection.drop_table("nodes", &[]).await.unwrap();
    connection
        .create_empty_table("nodes", legacy_nodes_schema_v19())
        .execute()
        .await
        .unwrap();
    connection
        .drop_table("staged_documents_v2", &[])
        .await
        .unwrap();
    let staging = connection
        .create_empty_table(
            "staged_documents_v2",
            staged_documents_v2_pre_metadata_schema(),
        )
        .execute()
        .await
        .unwrap();
    staging.add(legacy_batch(true, 5)).execute().await.unwrap();
    let version_before = staging.version().await.unwrap();

    let initialize_error = DatabaseManager::initialize(&path)
        .await
        .expect_err("a 19-column nodes table must fail initialize");
    assert!(
        initialize_error.contains("schema drift detected for nodes"),
        "{initialize_error}"
    );
    let open_error = DatabaseManager::open_and_validate(&path)
        .await
        .expect_err("a 19-column nodes table must fail open_and_validate");
    assert!(
        open_error.contains("schema drift detected for nodes"),
        "{open_error}"
    );

    let after = lancedb::connect(&path)
        .execute()
        .await
        .unwrap()
        .open_table("staged_documents_v2")
        .execute()
        .await
        .unwrap();
    assert_eq!(
        after.schema().await.unwrap().fields(),
        staged_documents_v2_pre_metadata_schema().fields(),
        "the staging table was not upgraded behind a failed nodes validation"
    );
    assert_eq!(after.version().await.unwrap(), version_before);
    let _ = std::fs::remove_dir_all(path);
}

// ---- the production DocMetaMap scan (Task 2, D-142, D-145) ----------------------------------

const DOC_PLAIN: &str = "00000000-0000-4000-8000-0000000000e2";
const DOC_LATER: &str = "00000000-0000-4000-8000-0000000000e3";

async fn ingest(database: &DatabaseManager, document_id: &str, extra: &[(&str, &str)]) {
    replace_document(
        database,
        &job_with(document_id, extra),
        &two_chunks(),
        &vec![vec![0.5; 2048]; 2],
        "model-x",
    )
    .await
    .unwrap();
}

async fn scan(database: &DatabaseManager) -> DocMetaMap {
    let nodes = database.nodes_table().await.unwrap();
    let version = nodes.version().await.unwrap();
    load_doc_meta(&nodes, version).await.unwrap()
}

fn expected_meta() -> DocMeta {
    DocMeta {
        doc_title: Some("Hamas' surprise attack: \"intel failure\"".to_owned()),
        source: Some("The Verge".to_owned()),
        published_date: Some("2023-10-07".to_owned()),
    }
}

async fn service_over(database: &DatabaseManager) -> crate::service::LancetServiceImpl {
    let settings = EffectiveRagSettings::default();
    configured_service(
        database,
        settings.clone(),
        Arc::new(FakeEmbedder),
        RecordingGenerator::from_effective_settings(&settings),
        Arc::new(rerank::NoOpReranker::new()),
    )
    .await
}

#[tokio::test]
async fn the_scan_holds_one_entry_for_the_document_with_metadata_and_none_for_the_other() {
    let path = store_path("scan-two");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    ingest(&database, DOC, &full_metadata()).await;
    ingest(&database, DOC_PLAIN, &[]).await;

    let map = scan(&database).await;
    assert_eq!(map.len(), 1, "only the document with metadata has an entry");
    assert_eq!(map.get(DOC), Some(&expected_meta()));
    assert!(map.get(DOC_PLAIN).is_none());
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_store_without_any_metadata_scans_to_an_empty_map_and_the_lever_stays_unavailable() {
    let path = store_path("scan-none");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    ingest(&database, DOC_PLAIN, &[]).await;
    let service = service_over(&database).await;

    let map = scan(&database).await;
    assert!(map.is_empty());
    let prior = Arc::clone(&*service.corpus_store.read().await);
    let snapshot = (*prior).clone().with_doc_meta(Arc::new(map));
    assert!(!service
        .lever_availability(&snapshot)
        .is_available(Lever::EvidenceMetadata));
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_scanned_snapshot_admits_the_metadata_lever_when_the_store_has_metadata() {
    let path = store_path("scan-available");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    ingest(&database, DOC, &full_metadata()).await;
    let service = service_over(&database).await;

    let prior = Arc::clone(&*service.corpus_store.read().await);
    let snapshot = (*prior)
        .clone()
        .with_doc_meta(Arc::new(scan(&database).await));
    assert!(service
        .lever_availability(&snapshot)
        .is_available(Lever::EvidenceMetadata));
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn the_scan_refuses_a_handle_that_is_not_at_the_named_version() {
    let path = store_path("scan-version");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    ingest(&database, DOC, &full_metadata()).await;
    let nodes = database.nodes_table().await.unwrap();
    let version = nodes.version().await.unwrap();

    let error = load_doc_meta(&nodes, version + 1)
        .await
        .expect_err("a map for another generation is never built");
    assert!(error.contains("version"), "{error}");
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn the_scan_leaves_the_shared_handle_unpinned() {
    let path = store_path("scan-unpinned");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    ingest(&database, DOC, &full_metadata()).await;
    let nodes = database.nodes_table().await.unwrap();
    let version = nodes.version().await.unwrap();
    load_doc_meta(&nodes, version).await.unwrap();
    // A write through the same handle still succeeds: a checkout would have pinned it.
    nodes.delete("document_id = 'none'").await.unwrap();
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn an_ingest_rebuild_scans_the_store_so_the_new_document_joins_the_map() {
    let _lock = crate::ingest::REBUILD_TEST_MUTEX.lock().await;
    let path = store_path("rebuild-scan");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    ingest(&database, DOC, &full_metadata()).await;
    let service = service_over(&database).await;
    let bm25 = service.effective_settings.retrieval.bm25.clone();

    let first = crate::ingest::rebuild_and_swap(&database, &service.corpus_store, bm25.clone())
        .await
        .expect("the first rebuild succeeds");
    assert_eq!(first.doc_meta.len(), 1);
    assert_eq!(first.doc_meta.get(DOC), Some(&expected_meta()));

    ingest(
        &database,
        DOC_LATER,
        &[("doc_title", "Later title"), ("source", "Wired")],
    )
    .await;
    let second = crate::ingest::rebuild_and_swap(&database, &service.corpus_store, bm25)
        .await
        .expect("the second rebuild succeeds");
    assert_eq!(second.doc_meta.len(), 2);
    assert_eq!(second.doc_meta.get(DOC), Some(&expected_meta()));
    let later = second.doc_meta.get(DOC_LATER).expect("the new document");
    assert_eq!(later.doc_title.as_deref(), Some("Later title"));
    assert_eq!(later.source.as_deref(), Some("Wired"));
    assert_eq!(later.published_date, None);
    assert_eq!(
        first.doc_meta.len(),
        1,
        "the earlier snapshot keeps its own map"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_failed_metadata_scan_degrades_the_rebuild_and_keeps_the_prior_snapshot_whole() {
    let _lock = crate::ingest::REBUILD_TEST_MUTEX.lock().await;
    let path = store_path("rebuild-scan-fail");
    let database = DatabaseManager::initialize(&path).await.unwrap();
    ingest(&database, DOC, &full_metadata()).await;
    let service = service_over(&database).await;
    let bm25 = service.effective_settings.retrieval.bm25.clone();
    let prior = crate::ingest::rebuild_and_swap(&database, &service.corpus_store, bm25.clone())
        .await
        .unwrap();

    crate::ingest::arm_rebuild_doc_meta_fail_next();
    let error = crate::ingest::rebuild_and_swap(&database, &service.corpus_store, bm25)
        .await
        .expect_err("a failed metadata scan fails the rebuild");
    assert!(error.contains("metadata"), "{error}");
    let current = Arc::clone(&*service.corpus_store.read().await);
    assert!(current.rebuild_degraded);
    assert!(
        Arc::ptr_eq(&current.doc_meta, &prior.doc_meta),
        "never an empty map swapped in"
    );
    assert_eq!(current.generation, prior.generation);
    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn main_builds_the_metadata_map_once_after_the_graph_and_before_the_first_snapshot() {
    let main = include_str!("../main.rs");
    let graph = main
        .find("GraphIndex::build(&database)")
        .expect("main builds the graph index");
    let scan = main
        .find("load_doc_meta(")
        .expect("main scans the document metadata");
    let snapshot = main
        .find("CorpusSnapshot::new(")
        .expect("main builds the first snapshot");
    assert_eq!(main.matches("load_doc_meta(").count(), 1);
    assert!(graph < scan, "the scan follows the graph build");
    assert!(scan < snapshot, "the scan precedes the first snapshot");
    assert!(
        main.contains(".with_doc_meta("),
        "the first snapshot holds the scanned map"
    );
}

#[test]
fn the_rebuild_path_attaches_a_freshly_scanned_map() {
    let source = include_str!("../ingest.rs");
    let start = source
        .find("pub async fn rebuild_and_swap_with_graph_builder(")
        .expect("the rebuild function exists");
    let body = &source[start..];
    let scan = body
        .find("load_doc_meta(&nodes_latest, nodes_version)")
        .expect("the rebuild scans at the version it just read");
    let success = body
        .find("rebuild_degraded: false")
        .expect("the success snapshot literal exists");
    let swap = body
        .find("// Swap under a short write lock")
        .expect("the swap follows the success literal");
    assert!(scan < success, "the scan precedes the success snapshot");
    assert!(
        !body[success..swap].contains("Arc::clone(&prior.doc_meta)"),
        "the success snapshot no longer carries the prior map forward"
    );
}

// ---- the backfill library function (Task 3, D-144, C1, C2, C10) -----------------------------

/// A valid UUIDv4 document id for fixture document `index`.
fn fixture_doc(index: usize) -> String {
    format!("{index:08x}-0000-4000-8000-{index:012x}")
}

/// A title that exercises quoting: an apostrophe, double quotes, a backslash, a percent sign.
fn fixture_title(index: usize) -> String {
    format!("Doc {index}: it's a \"test\" \\ 100% caf\u{e9}")
}

fn fixture_row(index: usize) -> SidecarRow {
    SidecarRow {
        doc_title: Some(fixture_title(index)),
        source: Some(format!("Publisher {} | News's", index % 7)),
        published_date: Some(format!("2023-{:02}-{:02}", 1 + index % 12, 1 + index % 28)),
    }
}

/// One 19-column batch holding `1 + doc % 4` chunks of each document in `docs`.
fn nodes_batch_v19(docs: std::ops::Range<usize>) -> RecordBatch {
    let mut document_ids = Vec::new();
    let mut chunk_ids = Vec::new();
    let mut chunk_indexes = Vec::new();
    let mut contents = Vec::new();
    for doc in docs {
        for chunk in 0..=(doc % 4) {
            document_ids.push(fixture_doc(doc));
            chunk_ids.push(format!("{}:{chunk}", fixture_doc(doc)));
            chunk_indexes.push(i32::try_from(chunk).unwrap());
            contents.push(format!("content of {doc} chunk {chunk}"));
        }
    }
    let rows = document_ids.len();
    let embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        (0..rows).map(|row| Some((0..2048).map(move |k| Some(((row * 7 + k) % 97) as f32 / 97.0)))),
        2048,
    );
    RecordBatch::try_new(
        legacy_nodes_schema_v19(),
        vec![
            Arc::new(StringArray::from(document_ids)),
            Arc::new(StringArray::from(chunk_ids)),
            Arc::new(Int32Array::from(chunk_indexes)),
            Arc::new(Int32Array::from(vec![0; rows])),
            Arc::new(Int32Array::from(vec![10; rows])),
            Arc::new(StringArray::from(contents)),
            Arc::new(embeddings),
            Arc::new(Int32Array::from(vec![5; rows])),
            Arc::new(StringArray::from(vec!["o200k_base"; rows])),
            Arc::new(StringArray::from(vec!["1"; rows])),
            Arc::new(StringArray::from(vec![Some("file.txt"); rows])),
            Arc::new(StringArray::from(vec![None::<&str>; rows])),
            Arc::new(Int32Array::from(vec![None::<i32>; rows])),
            Arc::new(Int32Array::from(vec![None::<i32>; rows])),
            Arc::new(StringArray::from(vec![Some("hash"); rows])),
            Arc::new(StringArray::from(vec![Some("1"); rows])),
            Arc::new(StringArray::from(vec![Some("voyage"); rows])),
            Arc::new(Int64Array::from(vec![Some(1_700_000_000_i64); rows])),
            Arc::new(StringArray::from(vec![Some("text/plain"); rows])),
        ],
    )
    .unwrap()
}

/// A store with a 19-column `nodes` of documents `0..docs` in five fragments, with documents 7 and
/// 20 deleted so the fragments carry deletion vectors, like the reconciled eval store.
async fn legacy_store(name: &str, docs: usize) -> (String, lancedb::Table) {
    let path = store_path(name);
    drop(DatabaseManager::initialize(&path).await.unwrap());
    let connection = lancedb::connect(&path).execute().await.unwrap();
    connection.drop_table("nodes", &[]).await.unwrap();
    let table = connection
        .create_empty_table("nodes", legacy_nodes_schema_v19())
        .execute()
        .await
        .unwrap();
    let step = docs / 5 + 1;
    let mut start = 0;
    while start < docs {
        let end = (start + step).min(docs);
        table
            .add(nodes_batch_v19(start..end))
            .execute()
            .await
            .unwrap();
        start = end;
    }
    if docs > 20 {
        for doc in [7, 20] {
            table
                .delete(&format!("document_id = '{}'", fixture_doc(doc)))
                .await
                .unwrap();
        }
    }
    (path, table)
}

/// A sidecar naming every fixture document in `docs`.
fn sidecar_for(docs: impl IntoIterator<Item = usize>) -> Sidecar {
    Sidecar::from_rows(
        docs.into_iter()
            .map(|doc| (fixture_doc(doc), fixture_row(doc)))
            .collect(),
    )
    .unwrap()
}

/// The live fixture documents: everything but the two deleted ones.
fn live_docs(docs: usize) -> Vec<usize> {
    (0..docs).filter(|doc| *doc != 7 && *doc != 20).collect()
}

async fn scan_strings(table: &lancedb::Table, column: &str) -> Vec<Option<String>> {
    let batches: Vec<RecordBatch> = table
        .query()
        .select(Select::columns(&[column]))
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();
    let mut values = Vec::new();
    for batch in &batches {
        let array = batch
            .column(0)
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        values.extend(
            (0..array.len()).map(|row| (!array.is_null(row)).then(|| array.value(row).to_owned())),
        );
    }
    values
}

/// What an untouched table must still look like after a refused or restored operation.
struct Fingerprint {
    rows: usize,
    chunk_ids: Vec<Option<String>>,
    contents: Vec<Option<String>>,
    digests: Vec<String>,
}

async fn fingerprint(table: &lancedb::Table) -> Fingerprint {
    let mut digests = Vec::new();
    for field in legacy_nodes_schema_v19().fields() {
        digests.push(column_digest(table, field.name()).await.unwrap());
    }
    Fingerprint {
        rows: table.count_rows(None).await.unwrap(),
        chunk_ids: scan_strings(table, "chunk_id").await,
        contents: scan_strings(table, "content").await,
        digests,
    }
}

fn assert_same_fingerprint(before: &Fingerprint, after: &Fingerprint) {
    assert_eq!(before.rows, after.rows, "row count");
    assert_eq!(before.chunk_ids, after.chunk_ids, "chunk ids in scan order");
    assert_eq!(before.contents, after.contents, "contents in scan order");
    assert_eq!(before.digests, after.digests, "all 19 column digests");
}

fn nodes_dir(path: &str) -> std::path::PathBuf {
    std::path::Path::new(path).join("nodes.lance")
}

#[tokio::test]
async fn one_call_adds_one_version_and_changes_nothing_but_the_new_columns() {
    let (path, table) = legacy_store("backfill-main", 40).await;
    let covered: Vec<usize> = live_docs(40).into_iter().filter(|doc| *doc != 39).collect();
    let sidecar = sidecar_for(covered.clone());

    let before = fingerprint(&table).await;
    let version_before = table.version().await.unwrap();
    let files_before = data_file_hashes(&nodes_dir(&path)).unwrap();
    assert_eq!(table.list_indices().await.unwrap().len(), 0);
    assert!(files_before.len() >= 5, "five appended fragments");

    let outcome = backfill_nodes_metadata(&table, &sidecar).await.unwrap();

    assert_eq!(outcome.version_before, version_before);
    assert_eq!(
        outcome.version_after,
        version_before + 1,
        "exactly one new version"
    );
    assert_eq!(table.version().await.unwrap(), outcome.version_after);
    assert_eq!(
        table.schema().await.unwrap().fields(),
        nodes_schema().fields(),
        "the strict 22-column schema"
    );
    assert_eq!(table.list_indices().await.unwrap().len(), 0);
    assert_same_fingerprint(&before, &fingerprint(&table).await);
    let files_after = data_file_hashes(&nodes_dir(&path)).unwrap();
    assert!(
        files_before
            .iter()
            .all(|(name, meta)| files_after.get(name) == Some(meta)),
        "old data files are byte-identical"
    );
    assert!(
        files_after.len() > files_before.len(),
        "new column files were added"
    );

    let documents = scan_strings(&table, "document_id").await;
    let titles = scan_strings(&table, "doc_title").await;
    let sources = scan_strings(&table, "source").await;
    let dates = scan_strings(&table, "published_date").await;
    let mut uncovered_rows = 0;
    for row in 0..documents.len() {
        let document = documents[row].as_deref().unwrap();
        let found = (
            titles[row].clone(),
            sources[row].clone(),
            dates[row].clone(),
        );
        match sidecar.get(document) {
            Some(expected) => assert_eq!(
                found,
                (
                    expected.doc_title.clone(),
                    expected.source.clone(),
                    expected.published_date.clone()
                ),
                "values per document id"
            ),
            None => {
                uncovered_rows += 1;
                assert_eq!(found, (None, None, None), "uncovered rows read null");
            }
        }
    }
    assert!(uncovered_rows > 0);
    assert_eq!(outcome.uncovered_document_ids, vec![fixture_doc(39)]);
    assert_eq!(outcome.documents, covered.len() + 1);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_reader_one_row_short_or_long_is_refused_and_leaves_the_table_unchanged() {
    let (path, table) = legacy_store("backfill-bad-reader", 30).await;
    let sidecar = sidecar_for(live_docs(30));
    let ids: Vec<String> = scan_strings(&table, "document_id")
        .await
        .into_iter()
        .map(Option::unwrap)
        .collect();
    let before = fingerprint(&table).await;
    let version_before = table.version().await.unwrap();
    let files_before = data_file_hashes(&nodes_dir(&path)).unwrap();

    let mut longer = ids.clone();
    longer.push(ids[0].clone());
    for (label, reader_ids) in [("short", ids[..ids.len() - 1].to_vec()), ("long", longer)] {
        let error = backfill_with(&table, &sidecar, &nodes_schema(), Some(reader_ids))
            .await
            .expect_err(label);
        assert!(
            error.contains("adding the metadata columns failed"),
            "{label}: {error}"
        );
        assert_eq!(
            table.version().await.unwrap(),
            version_before,
            "{label}: version"
        );
        assert_eq!(
            data_file_hashes(&nodes_dir(&path)).unwrap(),
            files_before,
            "{label}: files"
        );
        assert_eq!(
            table.schema().await.unwrap().fields(),
            legacy_nodes_schema_v19().fields(),
            "{label}: schema"
        );
        assert_same_fingerprint(&before, &fingerprint(&table).await);
    }
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_second_run_fails_loudly_with_already_exists() {
    let (path, table) = legacy_store("backfill-twice", 25).await;
    let sidecar = sidecar_for(live_docs(25));
    backfill_nodes_metadata(&table, &sidecar).await.unwrap();
    let version = table.version().await.unwrap();

    let error = backfill_nodes_metadata(&table, &sidecar)
        .await
        .expect_err("the columns exist");
    assert!(error.contains("already exists"), "{error}");
    assert_eq!(
        table.version().await.unwrap(),
        version,
        "nothing was written"
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_sidecar_id_absent_from_nodes_is_refused_before_any_write() {
    let (path, table) = legacy_store("backfill-absent-id", 25).await;
    let mut docs = live_docs(25);
    docs.push(999);
    let sidecar = sidecar_for(docs);
    let version = table.version().await.unwrap();
    let files = data_file_hashes(&nodes_dir(&path)).unwrap();

    let error = backfill_nodes_metadata(&table, &sidecar)
        .await
        .expect_err("a sidecar id that nodes lacks is refused");
    assert!(error.contains("absent from nodes"), "{error}");
    assert!(error.contains(&fixture_doc(999)), "{error}");
    assert_eq!(table.version().await.unwrap(), version);
    assert_eq!(data_file_hashes(&nodes_dir(&path)).unwrap(), files);
    assert_eq!(
        table.schema().await.unwrap().fields(),
        legacy_nodes_schema_v19().fields()
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn a_post_state_schema_mismatch_restores_the_prior_version() {
    let (path, table) = legacy_store("backfill-restore", 30).await;
    let sidecar = sidecar_for(live_docs(30));
    let before = fingerprint(&table).await;
    let version_before = table.version().await.unwrap();

    // An expected schema that differs from what Lance produces: the last column is renamed.
    let mut fields: Vec<arrow_schema::Field> = nodes_schema()
        .fields()
        .iter()
        .map(|field| field.as_ref().clone())
        .collect();
    let last = fields.len() - 1;
    fields[last] = arrow_schema::Field::new("published", DataType::Utf8, true);
    let mismatched = Arc::new(arrow_schema::Schema::new(fields));

    let error = backfill_with(&table, &sidecar, &mismatched, None)
        .await
        .expect_err("the post-state does not match");
    assert!(error.contains("restored version"), "{error}");
    assert_eq!(
        table.schema().await.unwrap().fields(),
        legacy_nodes_schema_v19().fields(),
        "the 19-column schema is back"
    );
    assert_eq!(
        table.version().await.unwrap(),
        version_before + 2,
        "the backfill and the restore each added a version (C10)"
    );
    assert_same_fingerprint(&before, &fingerprint(&table).await);

    // The restored table is a usable legacy table: the real backfill still applies.
    backfill_nodes_metadata(&table, &sidecar).await.unwrap();
    assert_eq!(
        table.schema().await.unwrap().fields(),
        nodes_schema().fields()
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn an_empty_legacy_table_backfills_to_the_22_column_schema() {
    let (path, table) = legacy_store("backfill-empty", 0).await;
    let outcome = backfill_nodes_metadata(&table, &Sidecar::empty())
        .await
        .unwrap();
    assert_eq!(outcome.rows, 0);
    assert_eq!(
        table.schema().await.unwrap().fields(),
        nodes_schema().fields()
    );
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn backfilled_values_equal_what_a_fresh_ingest_writes() {
    // Store A: the document ingested fresh with the keys (22 columns).
    let path_a = store_path("equal-fresh-a");
    let fresh = DatabaseManager::initialize(&path_a).await.unwrap();
    ingest(&fresh, DOC, &full_metadata()).await;
    let nodes_a = fresh.nodes_table().await.unwrap();

    // Store B: the same document's rows in a 19-column store, backfilled from its sidecar row.
    let path_b = store_path("equal-fresh-b");
    drop(DatabaseManager::initialize(&path_b).await.unwrap());
    let connection = lancedb::connect(&path_b).execute().await.unwrap();
    connection.drop_table("nodes", &[]).await.unwrap();
    let nodes_b = connection
        .create_empty_table("nodes", legacy_nodes_schema_v19())
        .execute()
        .await
        .unwrap();
    let batches: Vec<RecordBatch> = nodes_a
        .query()
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();
    for batch in &batches {
        let legacy_columns: Vec<usize> = (0..19).collect();
        let legacy = batch.project(&legacy_columns).unwrap();
        nodes_b
            .add(
                RecordBatch::try_new(legacy_nodes_schema_v19(), legacy.columns().to_vec()).unwrap(),
            )
            .execute()
            .await
            .unwrap();
    }
    let sidecar = Sidecar::parse(&format!(
        "{{\"schema\": 1, \"rows\": {{\"{DOC}\": {{\"doc_title\": {}, \"source\": {}, \"published_date\": {}}}}}}}",
        serde_json::to_string(full_metadata()[0].1).unwrap(),
        serde_json::to_string(full_metadata()[1].1).unwrap(),
        serde_json::to_string(full_metadata()[2].1).unwrap(),
    ))
    .unwrap();
    backfill_nodes_metadata(&nodes_b, &sidecar).await.unwrap();

    let columns = ["chunk_id", "doc_title", "source", "published_date"];
    let read = |table: lancedb::Table| async move {
        let mut by_column = Vec::new();
        for column in columns {
            by_column.push(scan_strings(&table, column).await);
        }
        let mut rows: Vec<Vec<Option<String>>> = (0..by_column[0].len())
            .map(|row| by_column.iter().map(|column| column[row].clone()).collect())
            .collect();
        rows.sort();
        rows
    };
    let rows_a = read(nodes_a).await;
    let rows_b = read(nodes_b).await;
    assert_eq!(rows_a.len(), two_chunks().len(), "one row per chunk");
    assert_eq!(rows_a, rows_b, "backfilled equals fresh, row by row");
    assert_eq!(rows_b[0][1].as_deref(), Some(full_metadata()[0].1));
    let _ = std::fs::remove_dir_all(path_a);
    let _ = std::fs::remove_dir_all(path_b);
}

#[test]
fn the_sidecar_parses_the_documented_shape_and_refuses_everything_else() {
    let doc = fixture_doc(3);
    let good = format!(
        "{{\"schema\": 1, \"rows\": {{\"{doc}\": {{\"doc_title\": \"T\", \"source\": null, \"published_date\": \"2023-10-07\"}}}}}}"
    );
    let sidecar = Sidecar::parse(&good).unwrap();
    assert_eq!(sidecar.len(), 1);
    let row = sidecar.get(&doc).unwrap();
    assert_eq!(row.doc_title.as_deref(), Some("T"));
    assert_eq!(row.source, None);
    assert_eq!(row.published_date.as_deref(), Some("2023-10-07"));

    let empty_string = format!(
        "{{\"schema\": 1, \"rows\": {{\"{doc}\": {{\"doc_title\": \"\", \"source\": \"S\"}}}}}}"
    );
    let row = Sidecar::parse(&empty_string).unwrap();
    let row = row.get(&doc).unwrap();
    assert_eq!(
        row.doc_title, None,
        "an empty string is stored as absent, as ingest stores it"
    );
    assert_eq!(row.published_date, None, "a missing field is absent");

    let refused = [
        ("schema 2", "{\"schema\": 2, \"rows\": {}}".to_owned()),
        ("not json", "rows".to_owned()),
        ("an unknown top-level field", "{\"schema\": 1, \"rows\": {}, \"extra\": 1}".to_owned()),
        ("a non-UUID key", "{\"schema\": 1, \"rows\": {\"doc-1\": {\"doc_title\": \"T\"}}}".to_owned()),
        (
            "a UUID that is not version 4",
            "{\"schema\": 1, \"rows\": {\"00000000-0000-1000-8000-000000000001\": {\"doc_title\": \"T\"}}}".to_owned(),
        ),
        ("an impossible date", format!("{{\"schema\": 1, \"rows\": {{\"{doc}\": {{\"published_date\": \"2023-02-30\"}}}}}}")),
        (
            "a title over the limit",
            format!("{{\"schema\": 1, \"rows\": {{\"{doc}\": {{\"doc_title\": \"{}\"}}}}}}", "t".repeat(MAX_DOC_TITLE_CHARS + 1)),
        ),
        ("an unknown row field", format!("{{\"schema\": 1, \"rows\": {{\"{doc}\": {{\"title\": \"T\"}}}}}}")),
    ];
    for (label, text) in refused {
        assert!(Sidecar::parse(&text).is_err(), "{label} must be refused");
    }
    assert!(Sidecar::empty().is_empty());
}

#[test]
fn the_schema_classifier_names_the_legacy_current_and_other_shapes() {
    assert_eq!(
        classify_nodes_schema(&legacy_nodes_schema_v19()),
        NodesSchemaState::Legacy19
    );
    assert_eq!(
        classify_nodes_schema(&nodes_schema()),
        NodesSchemaState::Current22
    );
    let mut fields: Vec<arrow_schema::Field> = nodes_schema()
        .fields()
        .iter()
        .map(|field| field.as_ref().clone())
        .collect();
    fields.pop();
    assert_eq!(
        classify_nodes_schema(&arrow_schema::Schema::new(fields)),
        NodesSchemaState::Other
    );
}

#[tokio::test]
async fn verification_on_a_copy_reports_the_five_assertions_true_for_a_fully_covered_store() {
    let (path, table) = legacy_store("verify-copy", 30).await;
    drop(table);
    let sidecar = sidecar_for(live_docs(30));

    let report = verify_backfill_on_copy(&path, &sidecar).await.unwrap();

    assert!(report.all_passed(), "{report:?}");
    assert_eq!(report.column_digests_equal, 19);
    assert!(report.column_digest_mismatches.is_empty());
    assert!(report.old_data_files_byte_identical);
    assert_eq!(report.rows_before, report.rows_after);
    assert_eq!((report.indices_before, report.indices_after), (0, 0));
    assert_eq!(report.version_after, report.version_before + 1);
    assert_eq!(report.value_mismatches, 0);
    assert!(report.uncovered_document_ids.is_empty());
    assert!(
        report.second_run_error.contains("already exists"),
        "{}",
        report.second_run_error
    );
    assert!(report
        .short_reader_error
        .contains("adding the metadata columns failed"));
    assert!(report
        .long_reader_error
        .contains("adding the metadata columns failed"));
    assert!(report.bad_readers_left_state_unchanged);
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn verification_reports_an_uncovered_document_and_still_proves_its_rows_null() {
    let (path, table) = legacy_store("verify-uncovered", 30).await;
    drop(table);
    let covered: Vec<usize> = live_docs(30).into_iter().filter(|doc| *doc != 29).collect();

    let report = verify_backfill_on_copy(&path, &sidecar_for(covered))
        .await
        .unwrap();

    assert_eq!(report.uncovered_document_ids, vec![fixture_doc(29)]);
    assert!(report.uncovered_rows_null);
    assert!(
        !report.assertions.scan_stable_and_sidecar_covered,
        "assertion 4 needs the sidecar to cover every document"
    );
    assert!(report.assertions.uncovered_null_and_second_run_refused);
    assert!(report.assertions.schema_strict_22_columns);
    assert!(!report.all_passed());
    let _ = std::fs::remove_dir_all(path);
}

#[tokio::test]
async fn verification_refuses_a_copy_that_is_not_a_legacy_store() {
    let path = store_path("verify-current");
    drop(DatabaseManager::initialize(&path).await.unwrap());
    let error = verify_backfill_on_copy(&path, &Sidecar::empty())
        .await
        .expect_err("a 22-column copy cannot be verified");
    assert!(error.contains("already exists"), "{error}");
    let _ = std::fs::remove_dir_all(path);
}

#[test]
fn the_backfill_source_holds_the_reader_mechanism_and_no_forbidden_call() {
    let source = include_str!("../db/backfill.rs");
    assert!(source.contains("NewColumnTransform::Reader"));
    assert!(
        !source.contains(concat!("CA", "SE")),
        "no conditional SQL expression"
    );
    for forbidden in [
        concat!("extract_and_persist", "_entities"),
        concat!(".opti", "mize("),
        concat!("cleanup_old", "_versions"),
        concat!("compact", "_files"),
    ] {
        assert!(
            !source.contains(forbidden),
            "backfill.rs must not call {forbidden}"
        );
    }
}
