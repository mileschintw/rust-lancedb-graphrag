//! Throwaway verification of `lancedb` 0.31.0 `Table::add_columns` on a `nodes`-shaped table.
//!
//! Builds a synthetic table with the engine's 19-column `nodes` schema (embedding dimension reduced from
//! 2048 to 16), appends it in five batches so it has several fragments, then adds `doc_title`, `source`
//! and `published_date`. Attempt 1 is the `SqlExpressions` call of `CASE document_id WHEN '<uuid>' THEN
//! '<value>' ... ELSE NULL END` that `06.3.6-AI-SPEC.md` section 4 item 4f proposes; attempt 2 is
//! `NewColumnTransform::Reader`. It never touches the eval store; the table lives under the directory named
//! by the first argument.
//!
//! Output is a sequence of `CHECK <name>: <value>` lines on stdout.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

use arrow_array::{
    Array, ArrayRef, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch,
    RecordBatchIterator, StringArray,
};
use arrow_schema::{DataType, Field, Schema, SchemaRef};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use lancedb::table::NewColumnTransform;
use lancedb::Table;

const DIM: i32 = 16;
const DOCS: usize = 346;

/// The engine's `nodes_schema()` as of HEAD `0ab2dd0d` (engine/src/db/mod.rs:221-243), embedding dimension reduced.
fn nodes_schema_19() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("document_id", DataType::Utf8, false),
        Field::new("chunk_id", DataType::Utf8, false),
        Field::new("chunk_index", DataType::Int32, false),
        Field::new("char_start", DataType::Int32, false),
        Field::new("char_end", DataType::Int32, false),
        Field::new("content", DataType::Utf8, false),
        Field::new(
            "embedding",
            DataType::FixedSizeList(Arc::new(Field::new("item", DataType::Float32, true)), DIM),
            false,
        ),
        Field::new("token_estimate", DataType::Int32, false),
        Field::new("token_estimate_scheme", DataType::Utf8, false),
        Field::new("token_estimate_version", DataType::Utf8, false),
        Field::new("title", DataType::Utf8, true),
        Field::new("section_path", DataType::Utf8, true),
        Field::new("page_start", DataType::Int32, true),
        Field::new("page_end", DataType::Int32, true),
        Field::new("content_hash", DataType::Utf8, true),
        Field::new("chunker_version", DataType::Utf8, true),
        Field::new("embedding_model", DataType::Utf8, true),
        Field::new("ingested_at", DataType::Int64, true),
        Field::new("content_type", DataType::Utf8, true),
    ]))
}

fn doc_id(i: usize) -> String {
    format!("{:08x}-0000-4000-8000-{:012x}", i, i)
}

/// A title that exercises the escape rule: quotes, a backslash, a percent sign, non-ASCII, 177 characters.
fn doc_title(i: usize) -> String {
    let base = format!("Doc {i}: it's a \"test\" \\ 100% caf\u{e9} \u{2013} {}", "x".repeat(160));
    base.chars().take(177).collect()
}

fn doc_source(i: usize) -> String {
    format!("Publisher {} | Latest News's", i % 44)
}

fn doc_date(i: usize) -> String {
    format!("2023-{:02}-{:02}", 1 + i % 12, 1 + i % 28)
}

fn batch_for(docs: std::ops::Range<usize>, schema: &SchemaRef) -> RecordBatch {
    let mut document_id = Vec::new();
    let mut chunk_id = Vec::new();
    let mut chunk_index = Vec::new();
    let mut content = Vec::new();
    for i in docs {
        let chunks = 1 + (i % 6);
        for c in 0..chunks {
            document_id.push(doc_id(i));
            chunk_id.push(format!("{}:{}", doc_id(i), c));
            chunk_index.push(c as i32);
            content.push(format!("content of {i} chunk {c}"));
        }
    }
    let n = document_id.len();
    let values: Vec<f32> = (0..n * DIM as usize).map(|k| (k % 97) as f32 / 97.0).collect();
    let embedding = FixedSizeListArray::try_new(
        Arc::new(Field::new("item", DataType::Float32, true)),
        DIM,
        Arc::new(Float32Array::from(values)) as ArrayRef,
        None,
    )
    .expect("embedding");
    let cols: Vec<ArrayRef> = vec![
        Arc::new(StringArray::from(document_id)),
        Arc::new(StringArray::from(chunk_id)),
        Arc::new(Int32Array::from(chunk_index)),
        Arc::new(Int32Array::from(vec![0; n])),
        Arc::new(Int32Array::from(vec![10; n])),
        Arc::new(StringArray::from(content)),
        Arc::new(embedding),
        Arc::new(Int32Array::from(vec![5; n])),
        Arc::new(StringArray::from(vec!["o200k_base"; n])),
        Arc::new(StringArray::from(vec!["1"; n])),
        Arc::new(StringArray::from(vec![Some("file_name.txt"); n])),
        Arc::new(StringArray::from(vec![None::<&str>; n])),
        Arc::new(Int32Array::from(vec![None::<i32>; n])),
        Arc::new(Int32Array::from(vec![None::<i32>; n])),
        Arc::new(StringArray::from(vec![Some("hash"); n])),
        Arc::new(StringArray::from(vec![Some("1"); n])),
        Arc::new(StringArray::from(vec![Some("voyage"); n])),
        Arc::new(Int64Array::from(vec![Some(1_700_000_000_i64); n])),
        Arc::new(StringArray::from(vec![Some("text/plain"); n])),
    ];
    RecordBatch::try_new(schema.clone(), cols).expect("batch")
}

/// Feeds one array into a hasher, type by type, so two scans compare bit for bit.
fn feed(hasher: &mut blake3::Hasher, array: &dyn Array) {
    match array.data_type() {
        DataType::Utf8 => {
            let a = array.as_any().downcast_ref::<StringArray>().expect("utf8");
            for i in 0..a.len() {
                if a.is_null(i) {
                    hasher.update(&[0]);
                } else {
                    hasher.update(&[1]);
                    hasher.update(a.value(i).as_bytes());
                    hasher.update(&[0xff]);
                }
            }
        }
        DataType::Int32 => {
            let a = array.as_any().downcast_ref::<Int32Array>().expect("i32");
            for i in 0..a.len() {
                if a.is_null(i) {
                    hasher.update(&[0]);
                } else {
                    hasher.update(&a.value(i).to_le_bytes());
                }
            }
        }
        DataType::Int64 => {
            let a = array.as_any().downcast_ref::<Int64Array>().expect("i64");
            for i in 0..a.len() {
                if a.is_null(i) {
                    hasher.update(&[0]);
                } else {
                    hasher.update(&a.value(i).to_le_bytes());
                }
            }
        }
        DataType::FixedSizeList(_, _) => {
            let a = array.as_any().downcast_ref::<FixedSizeListArray>().expect("fsl");
            let v = a.values().as_any().downcast_ref::<Float32Array>().expect("f32");
            for i in 0..v.len() {
                hasher.update(&v.value(i).to_le_bytes());
            }
        }
        other => panic!("unhandled type {other:?}"),
    }
}

async fn column_digest(table: &Table, column: &str) -> String {
    let mut hasher = blake3::Hasher::new();
    let mut stream = table
        .query()
        .select(Select::columns(&[column]))
        .execute()
        .await
        .expect("scan");
    while let Some(batch) = stream.try_next().await.expect("batch") {
        feed(&mut hasher, batch.column(0).as_ref());
    }
    hasher.finalize().to_hex().to_string()
}

fn data_files(table_dir: &Path) -> BTreeMap<String, (u64, String)> {
    let mut out = BTreeMap::new();
    if let Ok(read) = std::fs::read_dir(table_dir.join("data")) {
        for entry in read.flatten() {
            let path = entry.path();
            if path.is_file() {
                let bytes = std::fs::read(&path).expect("read data file");
                out.insert(
                    entry.file_name().to_string_lossy().to_string(),
                    (bytes.len() as u64, blake3::hash(&bytes).to_hex().to_string()),
                );
            }
        }
    }
    out
}

/// `CASE document_id WHEN '<id>' THEN '<value>' ... ELSE NULL END`, values escaped as `escape_sql_literal` does
/// (engine/src/graph/mod.rs:335: `value.replace('\'', "''")`).
fn case_expression(values: &[(String, Option<String>)]) -> String {
    let esc = |s: &str| s.replace('\'', "''");
    let mut sql = String::from("CASE document_id");
    for (id, value) in values {
        if let Some(value) = value {
            sql.push_str(&format!(" WHEN '{}' THEN '{}'", esc(id), esc(value)));
        }
    }
    sql.push_str(" ELSE NULL END");
    sql
}

/// `document_id` of every row in the table's scan order.
async fn scan_document_ids(table: &Table) -> Vec<String> {
    let mut out = Vec::new();
    let mut stream = table
        .query()
        .select(Select::columns(&["document_id"]))
        .execute()
        .await
        .expect("scan");
    while let Some(batch) = stream.try_next().await.expect("batch") {
        let a = batch.column(0).as_any().downcast_ref::<StringArray>().expect("utf8");
        for i in 0..a.len() {
            out.push(a.value(i).to_string());
        }
    }
    out
}

#[tokio::main]
async fn main() {
    let root = PathBuf::from(std::env::args().nth(1).expect("usage: probe <scratch-dir>"));
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).expect("mkdir");
    let schema = nodes_schema_19();
    let conn = lancedb::connect(root.to_str().expect("utf8 path"))
        .execute()
        .await
        .expect("connect");
    let table = conn
        .create_empty_table("nodes", schema.clone())
        .execute()
        .await
        .expect("create");
    // Five appends => five fragments, like an ingest that ran in several steps.
    let step = DOCS / 5 + 1;
    let mut start = 0;
    while start < DOCS {
        let end = (start + step).min(DOCS);
        table
            .add(batch_for(start..end, &schema))
            .execute()
            .await
            .expect("append");
        start = end;
    }
    let table_dir = root.join("nodes.lance");

    // The real eval store was reconciled (documents deleted, 06.3.4.1-04), so its fragments carry deletion
    // vectors. Delete three documents spread over different fragments to exercise that case.
    for i in [7_usize, 140, 300] {
        table
            .delete(&format!("document_id = '{}'", doc_id(i)))
            .await
            .expect("delete");
    }

    let rows_before = table.count_rows(None).await.expect("count");
    let version_before = table.version().await.expect("version");
    let schema_before = table.schema().await.expect("schema");
    let indices_before = table.list_indices().await.expect("indices").len();
    let files_before = data_files(&table_dir);
    let mut digests_before = BTreeMap::new();
    for f in schema_before.fields() {
        digests_before.insert(f.name().clone(), column_digest(&table, f.name()).await);
    }
    println!("CHECK rows_before (after 3 document deletions): {rows_before}");
    println!("CHECK version_before: {version_before}");
    println!("CHECK columns_before: {}", schema_before.fields().len());
    println!("CHECK indices_before: {indices_before}");
    println!("CHECK data_files_before: {}", files_before.len());

    // Three expressions. The last document is deliberately left out of every CASE so it reads NULL.
    let ids: Vec<String> = (0..DOCS).map(doc_id).collect();
    let titles: Vec<_> = (0..DOCS).map(|i| (ids[i].clone(), (i != DOCS - 1).then(|| doc_title(i)))).collect();
    let sources: Vec<_> = (0..DOCS).map(|i| (ids[i].clone(), (i != DOCS - 1).then(|| doc_source(i)))).collect();
    let dates: Vec<_> = (0..DOCS).map(|i| (ids[i].clone(), (i != DOCS - 1).then(|| doc_date(i)))).collect();
    let exprs = vec![
        ("doc_title".to_string(), case_expression(&titles)),
        ("source".to_string(), case_expression(&sources)),
        ("published_date".to_string(), case_expression(&dates)),
    ];
    println!(
        "CHECK sql_bytes: {:?}",
        exprs.iter().map(|(n, e)| (n.clone(), e.len())).collect::<Vec<_>>()
    );

    // Attempt 1: the mechanism 06.3.6-AI-SPEC.md section 4 item 4f proposes (SQL CASE). Expected to be rejected.
    let started = Instant::now();
    let case_attempt = table
        .add_columns(
            NewColumnTransform::SqlExpressions(exprs.clone()),
            Some(vec!["document_id".to_string()]),
        )
        .await;
    println!("CHECK case_attempt_elapsed_ms: {}", started.elapsed().as_millis());
    match &case_attempt {
        Ok(r) => println!("CHECK case_expression: ACCEPTED (version {})", r.version),
        Err(e) => {
            let msg = e.to_string();
            let tail: String = msg.chars().rev().take(190).collect::<Vec<_>>().into_iter().rev().collect();
            println!("CHECK case_expression: REJECTED, error tail: ...{tail}");
        }
    }
    let version_after_case = table.version().await.expect("version");
    println!("CHECK version_unchanged_after_rejected_case: {}", version_after_case == version_before);
    if case_attempt.is_ok() {
        println!("CHECK abort: CASE was accepted, the Reader path below is not needed");
        return;
    }

    // Attempt 2: NewColumnTransform::Reader. The reader yields the three new columns for every row, in the
    // table's scan order, so no SQL is involved. document_id is read in the same scan order.
    let ids_in_order = scan_document_ids(&table).await;
    let ids_in_order_again = scan_document_ids(&table).await;
    println!("CHECK scan_order_stable_across_two_scans: {}", ids_in_order == ids_in_order_again);
    println!("CHECK scan_rows: {}", ids_in_order.len());
    let lookup: HashMap<String, usize> = (0..DOCS - 1).map(|i| (doc_id(i), i)).collect();
    let new_schema: SchemaRef = Arc::new(Schema::new(vec![
        Field::new("doc_title", DataType::Utf8, true),
        Field::new("source", DataType::Utf8, true),
        Field::new("published_date", DataType::Utf8, true),
    ]));
    let build_reader = |ids: &[String]| {
        let batches: Vec<Result<RecordBatch, arrow_schema::ArrowError>> = ids
            .chunks(500)
            .map(|chunk| {
                let col = |f: &dyn Fn(usize) -> String| -> ArrayRef {
                    Arc::new(StringArray::from(
                        chunk.iter().map(|id| lookup.get(id).map(|&i| f(i))).collect::<Vec<Option<String>>>(),
                    ))
                };
                RecordBatch::try_new(
                    new_schema.clone(),
                    vec![col(&doc_title), col(&doc_source), col(&doc_date)],
                )
            })
            .collect();
        Box::new(RecordBatchIterator::new(batches, new_schema.clone()))
            as Box<dyn arrow_array::RecordBatchReader + Send>
    };

    // Fail-closed checks first: a reader that is one row short, then one row long.
    let short = table
        .add_columns(NewColumnTransform::Reader(build_reader(&ids_in_order[..ids_in_order.len() - 1])), None)
        .await;
    println!("CHECK reader_one_row_short: {}", match short { Ok(_) => "ACCEPTED (unexpected)".to_string(), Err(e) => format!("REJECTED {e}") });
    let mut longer = ids_in_order.clone();
    longer.push(doc_id(0));
    let long = table.add_columns(NewColumnTransform::Reader(build_reader(&longer)), None).await;
    println!("CHECK reader_one_row_long: {}", match long { Ok(_) => "ACCEPTED (unexpected)".to_string(), Err(e) => format!("REJECTED {e}") });
    println!(
        "CHECK version_unchanged_after_bad_readers: {}",
        table.version().await.expect("version") == version_before
    );
    println!("CHECK data_files_unchanged_after_bad_readers: {}", data_files(&table_dir) == files_before);

    let started = Instant::now();
    let result = table
        .add_columns(NewColumnTransform::Reader(build_reader(&ids_in_order)), None)
        .await;
    println!("CHECK add_columns_elapsed_ms: {}", started.elapsed().as_millis());
    match &result {
        Ok(r) => println!("CHECK add_columns_result_version: {}", r.version),
        Err(e) => {
            println!("CHECK add_columns_error: {e}");
            return;
        }
    }

    let rows_after = table.count_rows(None).await.expect("count");
    let version_after = table.version().await.expect("version");
    let schema_after = table.schema().await.expect("schema");
    let indices_after = table.list_indices().await.expect("indices").len();
    let files_after = data_files(&table_dir);
    println!("CHECK rows_after: {rows_after}");
    println!("CHECK version_after: {version_after}");
    println!("CHECK version_delta: {}", version_after - version_before);
    println!("CHECK indices_after: {indices_after}");

    let new_fields: Vec<_> = schema_after
        .fields()
        .iter()
        .skip(19)
        .map(|f| (f.name().clone(), f.data_type().clone(), f.is_nullable()))
        .collect();
    println!("CHECK new_fields: {new_fields:?}");
    let expected = ["doc_title", "source", "published_date"];
    let ok = new_fields.len() == 3
        && new_fields
            .iter()
            .zip(expected)
            .all(|((name, dt, nullable), want)| name == want && *dt == DataType::Utf8 && *nullable);
    println!("CHECK new_fields_are_utf8_nullable_in_order: {ok}");
    // The strict comparison the engine's `validate_schema` makes (engine/src/db/mod.rs:188-201):
    // `actual.fields() != expected.fields()`, which includes field metadata.
    let mut expected_fields: Vec<Field> = schema_before.fields().iter().map(|f| f.as_ref().clone()).collect();
    expected_fields.push(Field::new("doc_title", DataType::Utf8, true));
    expected_fields.push(Field::new("source", DataType::Utf8, true));
    expected_fields.push(Field::new("published_date", DataType::Utf8, true));
    let expected_schema = Schema::new(expected_fields);
    println!(
        "CHECK schema_fields_equal_expected_22_column_schema_strictly: {}",
        schema_after.fields() == expected_schema.fields()
    );
    let first19_equal = schema_before
        .fields()
        .iter()
        .zip(schema_after.fields().iter())
        .all(|(a, b)| a == b);
    println!("CHECK first_19_fields_unchanged: {first19_equal}");

    let preserved = files_before.iter().all(|(name, meta)| files_after.get(name) == Some(meta));
    println!("CHECK old_data_files_byte_identical: {preserved}");
    println!(
        "CHECK data_files_after: {} (added {})",
        files_after.len(),
        files_after.len() as i64 - files_before.len() as i64
    );

    let mut all_equal = true;
    for f in schema_before.fields() {
        let after = column_digest(&table, f.name()).await;
        if digests_before.get(f.name()) != Some(&after) {
            all_equal = false;
            println!("CHECK column_digest_MISMATCH: {}", f.name());
        }
    }
    println!("CHECK all_19_column_digests_equal: {all_equal}");

    let mut mismatches = 0usize;
    let mut nulls = 0usize;
    let mut seen = 0usize;
    let mut stream = table
        .query()
        .select(Select::columns(&["document_id", "doc_title", "source", "published_date"]))
        .execute()
        .await
        .expect("scan");
    while let Some(batch) = stream.try_next().await.expect("batch") {
        let id = batch.column(0).as_any().downcast_ref::<StringArray>().expect("id");
        let t = batch.column(1).as_any().downcast_ref::<StringArray>().expect("title");
        let s = batch.column(2).as_any().downcast_ref::<StringArray>().expect("source");
        let d = batch.column(3).as_any().downcast_ref::<StringArray>().expect("date");
        for r in 0..batch.num_rows() {
            seen += 1;
            let i = usize::from_str_radix(&id.value(r)[..8], 16).expect("hex");
            if i == DOCS - 1 {
                if t.is_null(r) && s.is_null(r) && d.is_null(r) {
                    nulls += 1;
                } else {
                    mismatches += 1;
                }
            } else if t.value(r) != doc_title(i) || s.value(r) != doc_source(i) || d.value(r) != doc_date(i) {
                mismatches += 1;
            }
        }
    }
    println!("CHECK rows_scanned: {seen}");
    println!("CHECK value_mismatches: {mismatches}");
    println!("CHECK unmapped_document_rows_null: {nulls}");

    // Trap 1: a second add of an existing name must fail (why the engine must not auto-upgrade `nodes`).
    let again = table
        .add_columns(
            NewColumnTransform::SqlExpressions(vec![(
                "doc_title".to_string(),
                "CAST(NULL AS STRING)".to_string(),
            )]),
            None,
        )
        .await;
    println!(
        "CHECK second_add_same_name: {}",
        match again {
            Ok(_) => "OK (unexpected)".to_string(),
            Err(e) => format!("ERR {e}"),
        }
    );

    // Trap 2: a handle pinned with `checkout` must refuse a schema change.
    let pinned = conn.open_table("nodes").execute().await.expect("open");
    pinned.checkout(version_before).await.expect("checkout");
    let on_pinned = pinned
        .add_columns(
            NewColumnTransform::SqlExpressions(vec![(
                "probe_col".to_string(),
                "CAST(NULL AS STRING)".to_string(),
            )]),
            None,
        )
        .await;
    println!(
        "CHECK add_on_checked_out_handle: {}",
        match on_pinned {
            Ok(_) => "OK (unexpected)".to_string(),
            Err(e) => format!("ERR {e}"),
        }
    );

    // Rollback path: checkout + restore, as engine/src/ingest.rs `restore_version` does.
    let before_restore = table.version().await.expect("version");
    let handle = conn.open_table("nodes").execute().await.expect("open");
    handle.checkout(version_before).await.expect("checkout");
    handle.restore().await.expect("restore");
    let after_restore = handle.version().await.expect("version");
    let schema_restored = handle.schema().await.expect("schema");
    println!(
        "CHECK restore: version {before_restore} -> {after_restore}, columns {}",
        schema_restored.fields().len()
    );
}
