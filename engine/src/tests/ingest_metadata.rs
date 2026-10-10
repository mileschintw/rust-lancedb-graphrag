//! Tests for the evidence-metadata store side of lever 3 (Phase 06.3.6 plan 14, D-144, D-168).
//!
//! Every test runs on a temporary store: nothing here opens a configured store. The module covers
//! the 22-column `nodes` schema, ingest persistence, the 10-column staging schema with both legacy
//! upgrades, the engine's re-validation of the three ingest keys, and the production scan that
//! builds the per-snapshot `DocMetaMap`.

use std::collections::HashMap;
use std::sync::Arc;

use arrow_array::{Array, BinaryArray, Int32Array, Int64Array, RecordBatch, StringArray};
use arrow_schema::DataType;
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use uuid::Uuid;

use crate::chunker::Chunk;
use crate::db::backfill::legacy_nodes_schema_v19;
use crate::db::{
    legacy_staged_documents_v2_schema, nodes_schema, staged_documents_v2_pre_metadata_schema,
    staged_documents_v2_schema, DatabaseManager,
};
use crate::ingest::{
    persist_raw_with_boundary, process_job, read_staged_jobs, replace_document, IngestionJob,
    LanceDbReplacementMutationBoundary,
};
use crate::service::{validate_ingest_metadata, MAX_DOC_TITLE_CHARS, MAX_SOURCE_CHARS};
use crate::tests::FakeEmbedder;

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
