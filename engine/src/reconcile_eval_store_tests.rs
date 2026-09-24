use std::collections::HashSet;
use std::sync::Arc;

use arrow_array::builder::{Int32Builder, ListBuilder, StringBuilder};
use arrow_array::new_null_array;
use arrow_array::types::Float32Type;
use arrow_array::{
    Array, BinaryArray, FixedSizeListArray, Float32Array, Int32Array, Int64Array, RecordBatch,
    StringArray,
};
use futures::TryStreamExt;
use lancedb::query::{ExecutableQuery, QueryBase, Select};
use uuid::Uuid;

use super::{
    check_isolation, check_snapshot, load_allow_list, load_target_ids, run_reconcile, Mode,
    ReconcileReport,
};
use engine::db::DatabaseManager;

fn database_path(test_name: &str) -> String {
    std::env::temp_dir()
        .join(format!("lancet-reconcile-{test_name}-{}", Uuid::new_v4()))
        .to_string_lossy()
        .into_owned()
}

async fn new_store(test_name: &str) -> (DatabaseManager, String) {
    let path = database_path(test_name);
    let database = DatabaseManager::initialize(&path).await.unwrap();
    (database, path)
}

async fn write_documents(database: &DatabaseManager, ids: &[&str]) {
    if ids.is_empty() {
        return;
    }
    let documents = database.documents_table().await.unwrap();
    let n = ids.len();
    let batch = RecordBatch::try_new(
        documents.schema().await.unwrap(),
        vec![
            Arc::new(StringArray::from(ids.to_vec())),
            Arc::new(BinaryArray::from_vec(vec![b"fixture" as &[u8]; n])),
        ],
    )
    .unwrap();
    documents.add(batch).execute().await.unwrap();
}

/// `(document_id, chunk_id)` pairs.
async fn write_nodes(database: &DatabaseManager, pairs: &[(&str, &str)]) {
    if pairs.is_empty() {
        return;
    }
    let nodes = database.nodes_table().await.unwrap();
    let schema = nodes.schema().await.unwrap();
    let n = pairs.len();
    let nullable = |name: &str| new_null_array(schema.field_with_name(name).unwrap().data_type(), n);
    let embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        (0..n).map(|_| Some((0..2048).map(|_| Some(0.1f32)))),
        2048,
    );
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(pairs.iter().map(|(d, _)| *d).collect::<Vec<_>>())),
            Arc::new(StringArray::from(pairs.iter().map(|(_, c)| *c).collect::<Vec<_>>())),
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

async fn write_edges(database: &DatabaseManager, document_ids: &[&str]) {
    if document_ids.is_empty() {
        return;
    }
    let edges = database.edges_table().await.unwrap();
    let schema = edges.schema().await.unwrap();
    let n = document_ids.len();
    let nullable = |name: &str| new_null_array(schema.field_with_name(name).unwrap().data_type(), n);
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from((0..n).map(|i| format!("edge-{i}-{}", Uuid::new_v4())).collect::<Vec<_>>())),
            Arc::new(StringArray::from((0..n).map(|i| format!("src-{i}")).collect::<Vec<_>>())),
            Arc::new(StringArray::from((0..n).map(|i| format!("tgt-{i}")).collect::<Vec<_>>())),
            Arc::new(StringArray::from(vec!["next_chunk"; n])),
            Arc::new(Float32Array::from(vec![1.0; n])),
            Arc::new(StringArray::from(document_ids.to_vec())),
            nullable("summary"),
            nullable("summary_vector"),
        ],
    )
    .unwrap();
    edges.add(batch).execute().await.unwrap();
}

/// `(source_node_id, target_node_id, document_id)` rows.
async fn write_entity_edges(database: &DatabaseManager, rows: &[(&str, &str, &str)]) {
    if rows.is_empty() {
        return;
    }
    let entity_edges = database.entity_edges_table().await.unwrap();
    let schema = entity_edges.schema().await.unwrap();
    let n = rows.len();
    let nullable = |name: &str| new_null_array(schema.field_with_name(name).unwrap().data_type(), n);
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from((0..n).map(|i| format!("ee-{i}-{}", Uuid::new_v4())).collect::<Vec<_>>())),
            Arc::new(StringArray::from(rows.iter().map(|(s, _, _)| *s).collect::<Vec<_>>())),
            Arc::new(StringArray::from(rows.iter().map(|(_, t, _)| *t).collect::<Vec<_>>())),
            Arc::new(StringArray::from(vec!["relates_to"; n])),
            Arc::new(Float32Array::from(vec![1.0; n])),
            Arc::new(StringArray::from(rows.iter().map(|(_, _, d)| *d).collect::<Vec<_>>())),
            nullable("summary"),
            nullable("summary_vector"),
        ],
    )
    .unwrap();
    entity_edges.add(batch).execute().await.unwrap();
}

async fn write_staged(database: &DatabaseManager, document_ids: &[&str]) {
    if document_ids.is_empty() {
        return;
    }
    let staged = database.staged_documents_table().await.unwrap();
    let schema = staged.schema().await.unwrap();
    let n = document_ids.len();
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(document_ids.to_vec())),
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

#[derive(Clone)]
struct EntityRow {
    entity_id: String,
    name_vector_seed: f32,
    summary: Option<String>,
    summary_vector_seed: Option<f32>,
    unsummarized_refs: Option<Vec<String>>,
    community_ids: Option<Vec<i32>>,
    source_chunk_ids: Vec<String>,
}

impl EntityRow {
    fn new(entity_id: &str, source_chunk_ids: &[&str]) -> Self {
        Self {
            entity_id: entity_id.to_owned(),
            name_vector_seed: 0.1,
            summary: None,
            summary_vector_seed: None,
            unsummarized_refs: None,
            community_ids: None,
            source_chunk_ids: source_chunk_ids.iter().map(|s| (*s).to_owned()).collect(),
        }
    }

    /// Non-null, distinctive values for every optional column — used by tests
    /// that must prove byte-equal preservation on rewrite (not a tautological
    /// null-equals-null pass).
    fn distinctive(entity_id: &str, source_chunk_ids: &[&str]) -> Self {
        Self {
            entity_id: entity_id.to_owned(),
            name_vector_seed: 0.42,
            summary: Some(format!("distinctive summary for {entity_id}")),
            summary_vector_seed: Some(0.777),
            unsummarized_refs: Some(vec!["ref-a".to_owned(), "ref-b".to_owned()]),
            community_ids: Some(vec![42, 43]),
            source_chunk_ids: source_chunk_ids.iter().map(|s| (*s).to_owned()).collect(),
        }
    }
}

async fn write_entities(database: &DatabaseManager, rows: &[EntityRow]) {
    if rows.is_empty() {
        return;
    }
    let entities = database.entities_table().await.unwrap();
    let n = rows.len();

    let name_vectors = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        rows.iter()
            .map(|r| Some((0..2048).map(move |_| Some(r.name_vector_seed)))),
        2048,
    );
    let summary_vectors = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        rows.iter()
            .map(|r| r.summary_vector_seed.map(|seed| (0..2048).map(move |_| Some(seed)))),
        2048,
    );

    let mut refs_builder = ListBuilder::new(StringBuilder::new());
    for row in rows {
        match &row.unsummarized_refs {
            Some(values) => {
                for v in values {
                    refs_builder.values().append_value(v);
                }
                refs_builder.append(true);
            }
            None => refs_builder.append(false),
        }
    }

    let mut community_builder = ListBuilder::new(Int32Builder::new());
    for row in rows {
        match &row.community_ids {
            Some(values) => {
                for v in values {
                    community_builder.values().append_value(*v);
                }
                community_builder.append(true);
            }
            None => community_builder.append(false),
        }
    }

    let mut chunk_builder = ListBuilder::new(StringBuilder::new());
    for row in rows {
        for cid in &row.source_chunk_ids {
            chunk_builder.values().append_value(cid);
        }
        chunk_builder.append(true);
    }

    let batch = RecordBatch::try_new(
        entities.schema().await.unwrap(),
        vec![
            Arc::new(StringArray::from(rows.iter().map(|r| r.entity_id.as_str()).collect::<Vec<_>>())),
            Arc::new(StringArray::from(vec!["Fixture Entity"; n])),
            Arc::new(StringArray::from(vec!["concept"; n])),
            Arc::new(name_vectors),
            Arc::new(StringArray::from(rows.iter().map(|r| r.summary.as_deref()).collect::<Vec<_>>())),
            Arc::new(summary_vectors),
            Arc::new(refs_builder.finish()),
            Arc::new(community_builder.finish()),
            Arc::new(chunk_builder.finish()),
        ],
    )
    .unwrap();
    entities.add(batch).execute().await.unwrap();
}

fn allow_set(ids: &[&str]) -> HashSet<String> {
    ids.iter().map(|s| (*s).to_owned()).collect()
}

fn document_ids_from(report: &ReconcileReport) -> Vec<String> {
    let mut ids = report.extras.clone();
    ids.sort();
    ids
}

async fn entity_ids_in_table(database: &DatabaseManager) -> Vec<String> {
    let entities = database.entities_table().await.unwrap();
    let batches: Vec<RecordBatch> = entities
        .query()
        .select(Select::columns(&["entity_id"]))
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();
    let mut out = Vec::new();
    for batch in &batches {
        let col = batch
            .column_by_name("entity_id")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        for row in 0..batch.num_rows() {
            out.push(col.value(row).to_owned());
        }
    }
    out.sort();
    out
}

async fn document_ids_in_table(database: &DatabaseManager, table_name: &str) -> Vec<String> {
    let table = match table_name {
        "documents" => database.documents_table().await.unwrap(),
        "nodes" => database.nodes_table().await.unwrap(),
        "edges" => database.edges_table().await.unwrap(),
        "entity_edges" => database.entity_edges_table().await.unwrap(),
        "staged_documents_v2" => database.staged_documents_table().await.unwrap(),
        other => panic!("unknown table {other}"),
    };
    let batches: Vec<RecordBatch> = table
        .query()
        .select(Select::columns(&["document_id"]))
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();
    let mut out = Vec::new();
    for batch in &batches {
        let col = batch
            .column_by_name("document_id")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        for row in 0..batch.num_rows() {
            out.push(col.value(row).to_owned());
        }
    }
    out.sort();
    out
}

struct FetchedEntity {
    source_chunk_ids: Vec<String>,
    summary: Option<String>,
    summary_vector: Option<Vec<f32>>,
    unsummarized_refs: Option<Vec<String>>,
    community_ids: Option<Vec<i32>>,
}

async fn fetch_entity(database: &DatabaseManager, entity_id: &str) -> Option<FetchedEntity> {
    let entities = database.entities_table().await.unwrap();
    let predicate = format!("entity_id = '{entity_id}'");
    let batches: Vec<RecordBatch> = entities
        .query()
        .only_if(predicate)
        .execute()
        .await
        .unwrap()
        .try_collect()
        .await
        .unwrap();
    for batch in &batches {
        if batch.num_rows() == 0 {
            continue;
        }
        let summary_col = batch
            .column_by_name("summary")
            .unwrap()
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        let summary_vector_col = batch
            .column_by_name("summary_vector")
            .unwrap()
            .as_any()
            .downcast_ref::<FixedSizeListArray>()
            .unwrap();
        let refs_col = batch
            .column_by_name("unsummarized_refs")
            .unwrap()
            .as_any()
            .downcast_ref::<arrow_array::ListArray>()
            .unwrap();
        let community_col = batch
            .column_by_name("community_ids")
            .unwrap()
            .as_any()
            .downcast_ref::<arrow_array::ListArray>()
            .unwrap();
        let chunk_col = batch
            .column_by_name("source_chunk_ids")
            .unwrap()
            .as_any()
            .downcast_ref::<arrow_array::ListArray>()
            .unwrap();

        let source_chunk_ids = {
            let values = chunk_col.value(0);
            let str_values = values.as_any().downcast_ref::<StringArray>().unwrap();
            (0..str_values.len()).map(|i| str_values.value(i).to_owned()).collect::<Vec<_>>()
        };
        let summary = if summary_col.is_null(0) {
            None
        } else {
            Some(summary_col.value(0).to_owned())
        };
        let summary_vector = if summary_vector_col.is_null(0) {
            None
        } else {
            let values = summary_vector_col.value(0);
            let f32_values = values.as_any().downcast_ref::<Float32Array>().unwrap();
            Some((0..f32_values.len()).map(|i| f32_values.value(i)).collect::<Vec<_>>())
        };
        let unsummarized_refs = if refs_col.is_null(0) {
            None
        } else {
            let values = refs_col.value(0);
            let str_values = values.as_any().downcast_ref::<StringArray>().unwrap();
            Some((0..str_values.len()).map(|i| str_values.value(i).to_owned()).collect::<Vec<_>>())
        };
        let community_ids = if community_col.is_null(0) {
            None
        } else {
            let values = community_col.value(0);
            let i32_values = values.as_any().downcast_ref::<Int32Array>().unwrap();
            Some((0..i32_values.len()).map(|i| i32_values.value(i)).collect::<Vec<_>>())
        };

        return Some(FetchedEntity {
            source_chunk_ids,
            summary,
            summary_vector,
            unsummarized_refs,
            community_ids,
        });
    }
    None
}

fn document_map_json(entries: &[&str]) -> String {
    let mut map = serde_json::Map::new();
    for id in entries {
        map.insert((*id).to_owned(), serde_json::json!({ "title": id }));
    }
    serde_json::to_string(&serde_json::json!({ "entries": map, "aliases": {} })).unwrap()
}

// ---------------------------------------------------------------------------
// Behavior 1: extras computed as the union across all four tables minus allow.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn extras_computed_correctly() {
    let (database, path) = new_store("extras").await;
    write_documents(&database, &["M1", "M2", "X1"]).await;
    write_nodes(&database, &[("M1", "m1-c0"), ("M2", "m2-c0"), ("X2", "x2-c0")]).await;
    write_edges(&database, &["M1", "X3"]).await;
    write_entity_edges(&database, &[("s1", "t1", "M2"), ("s2", "t2", "X4")]).await;

    let allow = allow_set(&["M1", "M2"]);
    let report = run_reconcile(&database, &allow, None, Mode::DryRun).await.unwrap();

    assert_eq!(document_ids_from(&report), vec!["X1", "X2", "X3", "X4"]);
    assert_eq!(report.allow_count, 2);
    assert_eq!(report.mode, Mode::DryRun);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Behavior 2: apply deletes extra-doc rows, leaves mapped rows untouched.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn apply_deletes_extra_rows_leaves_mapped_untouched() {
    let (database, path) = new_store("apply-basic").await;
    write_documents(&database, &["M1", "X1"]).await;
    write_nodes(&database, &[("M1", "m1-c0"), ("X1", "x1-c0")]).await;
    write_edges(&database, &["M1", "X1"]).await;
    write_entity_edges(&database, &[("s1", "t1", "M1"), ("s2", "t2", "X1")]).await;
    write_staged(&database, &["X1"]).await;

    let allow = allow_set(&["M1"]);
    let report = run_reconcile(&database, &allow, None, Mode::Apply).await.unwrap();

    assert_eq!(document_ids_from(&report), vec!["X1"]);
    assert_eq!(document_ids_in_table(&database, "documents").await, vec!["M1"]);
    assert_eq!(document_ids_in_table(&database, "nodes").await, vec!["M1"]);
    assert_eq!(document_ids_in_table(&database, "edges").await, vec!["M1"]);
    assert_eq!(document_ids_in_table(&database, "entity_edges").await, vec!["M1"]);
    assert!(document_ids_in_table(&database, "staged_documents_v2").await.is_empty());

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Behavior 3: entity whose chunks are all extra becomes an orphan; its
// entity_edges (even on a mapped document) are deleted too.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn entity_all_chunks_extra_becomes_orphan_and_deletes_entity_edges() {
    let (database, path) = new_store("orphan").await;
    write_documents(&database, &["M1", "X1"]).await;
    write_nodes(&database, &[("M1", "m1-c0"), ("X1", "x1-c0")]).await;
    write_entities(&database, &[EntityRow::new("E1", &["x1-c0"])]).await;
    // This entity_edges row's OWN document is mapped (M1) -- it must be
    // deleted via orphan-incident pruning (step 5), not the document_id
    // cascade (step 2).
    write_entity_edges(&database, &[("E1", "OTHER", "M1")]).await;

    let allow = allow_set(&["M1"]);
    let report = run_reconcile(&database, &allow, None, Mode::Apply).await.unwrap();

    assert_eq!(report.entities.orphan, 1);
    assert_eq!(report.orphan_incident_entity_edges, 1);
    assert!(entity_ids_in_table(&database).await.is_empty());
    assert!(document_ids_in_table(&database, "entity_edges").await.is_empty());

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Behavior 4: entity with chunks in both a mapped and an extra doc survives
// with only the mapped chunk IDs, other columns byte-equal to before.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn entity_mixed_chunks_rewritten_preserves_other_columns_byte_equal() {
    let (database, path) = new_store("rewrite").await;
    write_documents(&database, &["M1", "X1"]).await;
    write_nodes(&database, &[("M1", "m1-c0"), ("X1", "x1-c0")]).await;
    write_entities(&database, &[EntityRow::distinctive("E1", &["m1-c0", "x1-c0"])]).await;

    let allow = allow_set(&["M1"]);
    let report = run_reconcile(&database, &allow, None, Mode::Apply).await.unwrap();

    assert_eq!(report.entities.rewrite, 1);
    assert_eq!(report.entities.orphan, 0);

    let fetched = fetch_entity(&database, "E1").await.unwrap();
    assert_eq!(fetched.source_chunk_ids, vec!["m1-c0"]);
    assert_eq!(fetched.summary.as_deref(), Some("distinctive summary for E1"));
    assert_eq!(fetched.summary_vector, Some(vec![0.777f32; 2048]));
    assert_eq!(
        fetched.unsummarized_refs,
        Some(vec!["ref-a".to_owned(), "ref-b".to_owned()])
    );
    assert_eq!(fetched.community_ids, Some(vec![42, 43]));

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Behavior 5: degree-0 entity with surviving chunks is untouched (not an
// orphan just because it has no entity_edges).
// ---------------------------------------------------------------------------

#[tokio::test]
async fn degree_zero_entity_with_surviving_chunks_untouched() {
    let (database, path) = new_store("isolated-untouched").await;
    write_documents(&database, &["M1"]).await;
    write_nodes(&database, &[("M1", "m1-c0")]).await;
    write_entities(&database, &[EntityRow::new("E1", &["m1-c0"])]).await;

    let allow = allow_set(&["M1"]);
    let report = run_reconcile(&database, &allow, None, Mode::Apply).await.unwrap();

    assert_eq!(report.entities.untouched, 1);
    assert_eq!(report.entities.orphan, 0);
    assert_eq!(report.entities.rewrite, 0);
    assert_eq!(report.entities.isolated_untouched, 1);
    assert_eq!(entity_ids_in_table(&database).await, vec!["E1"]);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Behavior 5b: stale provenance pointing at a chunk that no longer exists
// ANYWHERE is pruned, even when the entity's document is mapped.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn stale_provenance_chunk_pruned_even_when_document_mapped() {
    let (database, path) = new_store("stale-provenance").await;
    write_documents(&database, &["M1"]).await;
    // Only "m1-current" exists as a real node; "m1-stale" is provenance left
    // over from an earlier re-ingest and has no corresponding node row.
    write_nodes(&database, &[("M1", "m1-current")]).await;
    write_entities(&database, &[EntityRow::new("E1", &["m1-current", "m1-stale"])]).await;

    let allow = allow_set(&["M1"]);
    let report = run_reconcile(&database, &allow, None, Mode::Apply).await.unwrap();

    assert_eq!(report.entities.rewrite, 1);
    let fetched = fetch_entity(&database, "E1").await.unwrap();
    assert_eq!(fetched.source_chunk_ids, vec!["m1-current"]);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Behavior 6: a second apply on an already-reconciled store is a no-op.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn second_apply_is_noop() {
    let (database, path) = new_store("second-apply").await;
    write_documents(&database, &["M1", "X1"]).await;
    write_nodes(&database, &[("M1", "m1-c0"), ("X1", "x1-c0")]).await;
    write_entities(&database, &[EntityRow::distinctive("E1", &["m1-c0", "x1-c0"])]).await;

    let allow = allow_set(&["M1"]);
    let _first = run_reconcile(&database, &allow, None, Mode::Apply).await.unwrap();

    let entities = database.entities_table().await.unwrap();
    let nodes = database.nodes_table().await.unwrap();
    let versions_before_second = (
        entities.version().await.unwrap(),
        nodes.version().await.unwrap(),
    );

    let second = run_reconcile(&database, &allow, None, Mode::Apply).await.unwrap();

    assert!(document_ids_from(&second).is_empty());
    assert_eq!(second.entities.rewrite, 0);
    assert_eq!(second.entities.orphan, 0);
    assert_eq!(second.versions_before, second.versions_after);

    let versions_after_second = (
        entities.version().await.unwrap(),
        nodes.version().await.unwrap(),
    );
    assert_eq!(versions_before_second, versions_after_second);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Behavior 7: apply guards -- snapshot-dir and isolation refusals.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn check_snapshot_refuses_without_snapshot_dir() {
    let result = check_snapshot(None, "./data/lancedb-eval");
    let err = result.unwrap_err();
    assert!(err.contains("--snapshot-dir"));
}

#[tokio::test]
async fn check_snapshot_refuses_snapshot_missing_nodes_lance() {
    let dir = std::env::temp_dir().join(format!("reconcile-snapshot-empty-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&dir).unwrap();
    let live = std::env::temp_dir().join(format!("reconcile-live-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&live).unwrap();

    let result = check_snapshot(Some(&dir), live.to_str().unwrap());
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("nodes.lance"));

    let _ = std::fs::remove_dir_all(&dir);
    let _ = std::fs::remove_dir_all(&live);
}

#[tokio::test]
async fn check_snapshot_accepts_valid_snapshot_dir() {
    let dir = std::env::temp_dir().join(format!("reconcile-snapshot-valid-{}", Uuid::new_v4()));
    std::fs::create_dir_all(dir.join("nodes.lance")).unwrap();
    let live = std::env::temp_dir().join(format!("reconcile-live-valid-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&live).unwrap();

    let result = check_snapshot(Some(&dir), live.to_str().unwrap());
    assert!(result.is_ok(), "{:?}", result.err());

    let _ = std::fs::remove_dir_all(&dir);
    let _ = std::fs::remove_dir_all(&live);
}

#[tokio::test]
async fn check_snapshot_refuses_snapshot_inside_live_store() {
    let live = std::env::temp_dir().join(format!("reconcile-live-nested-{}", Uuid::new_v4()));
    let nested_snapshot = live.join("snapshot");
    std::fs::create_dir_all(nested_snapshot.join("nodes.lance")).unwrap();

    let result = check_snapshot(Some(&nested_snapshot), live.to_str().unwrap());
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("live store"));

    let _ = std::fs::remove_dir_all(&live);
}

#[tokio::test]
async fn check_isolation_refuses_target_not_matching_eval_path() {
    let target = std::env::temp_dir().join(format!("reconcile-iso-target-{}", Uuid::new_v4()));
    let eval = std::env::temp_dir().join(format!("reconcile-iso-eval-{}", Uuid::new_v4()));
    let dev = std::env::temp_dir().join(format!("reconcile-iso-dev-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&target).unwrap();
    std::fs::create_dir_all(&eval).unwrap();
    std::fs::create_dir_all(&dev).unwrap();

    let result = check_isolation(
        target.to_str().unwrap(),
        eval.to_str().unwrap(),
        dev.to_str().unwrap(),
    );
    assert!(result.is_err());

    let _ = std::fs::remove_dir_all(&target);
    let _ = std::fs::remove_dir_all(&eval);
    let _ = std::fs::remove_dir_all(&dev);
}

#[tokio::test]
async fn check_isolation_refuses_target_matching_dev_path() {
    let dev = std::env::temp_dir().join(format!("reconcile-iso-devmatch-{}", Uuid::new_v4()));
    let eval = std::env::temp_dir().join(format!("reconcile-iso-evalmatch-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&dev).unwrap();
    std::fs::create_dir_all(&eval).unwrap();

    // Target equals dev path, which must be refused even if some other
    // eval-path string were (incorrectly) supplied.
    let result = check_isolation(dev.to_str().unwrap(), eval.to_str().unwrap(), dev.to_str().unwrap());
    assert!(result.is_err());

    let _ = std::fs::remove_dir_all(&dev);
    let _ = std::fs::remove_dir_all(&eval);
}

#[tokio::test]
async fn check_isolation_accepts_target_matching_eval_path() {
    let eval = std::env::temp_dir().join(format!("reconcile-iso-evalok-{}", Uuid::new_v4()));
    let dev = std::env::temp_dir().join(format!("reconcile-iso-devok-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&eval).unwrap();
    std::fs::create_dir_all(&dev).unwrap();

    let result = check_isolation(eval.to_str().unwrap(), eval.to_str().unwrap(), dev.to_str().unwrap());
    assert!(result.is_ok(), "{:?}", result.err());

    let _ = std::fs::remove_dir_all(&eval);
    let _ = std::fs::remove_dir_all(&dev);
}

// ---------------------------------------------------------------------------
// document_map.json / --target-document-ids validation.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn load_allow_list_validates_uuidv4_keys() {
    let valid_id = "00000000-0000-4000-8000-000000000001";
    let valid_path = std::env::temp_dir().join(format!("reconcile-map-valid-{}.json", Uuid::new_v4()));
    std::fs::write(&valid_path, document_map_json(&[valid_id])).unwrap();
    let allow = load_allow_list(&valid_path).unwrap();
    assert_eq!(allow, allow_set(&[valid_id]));
    let _ = std::fs::remove_file(&valid_path);

    let invalid_path = std::env::temp_dir().join(format!("reconcile-map-invalid-{}.json", Uuid::new_v4()));
    std::fs::write(&invalid_path, document_map_json(&["not-a-uuid"])).unwrap();
    let err = load_allow_list(&invalid_path).unwrap_err();
    assert!(err.contains("UUID"));
    let _ = std::fs::remove_file(&invalid_path);
}

#[tokio::test]
async fn load_target_ids_refuses_id_not_in_allow() {
    let mapped_id = "00000000-0000-4000-8000-000000000002";
    let unmapped_id = "00000000-0000-4000-8000-000000000003";
    let allow = allow_set(&[mapped_id]);

    let path = std::env::temp_dir().join(format!("reconcile-targets-{}.json", Uuid::new_v4()));
    std::fs::write(&path, serde_json::to_string(&vec![unmapped_id]).unwrap()).unwrap();

    let err = load_target_ids(&path, &allow).unwrap_err();
    assert!(err.contains(unmapped_id));

    let _ = std::fs::remove_file(&path);
}

// ---------------------------------------------------------------------------
// Behavior 8: --target-document-ids deletes exactly the listed mapped IDs
// through the same cascade.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn target_document_ids_deletes_exactly_listed_through_cascade() {
    let (database, path) = new_store("targeted").await;
    write_documents(&database, &["M1", "M2"]).await;
    write_nodes(&database, &[("M1", "m1-c0"), ("M2", "m2-c0")]).await;

    let allow = allow_set(&["M1", "M2"]);
    let targets = allow_set(&["M1"]);
    let report = run_reconcile(&database, &allow, Some(&targets), Mode::Apply).await.unwrap();

    assert_eq!(document_ids_from(&report), vec!["M1"]);
    assert_eq!(document_ids_in_table(&database, "documents").await, vec!["M2"]);
    assert_eq!(document_ids_in_table(&database, "nodes").await, vec!["M2"]);

    let _ = std::fs::remove_dir_all(path);
}

// ---------------------------------------------------------------------------
// Behavior 9 (regression guard, #06.3.4.1-04 advisor review): dry-run's
// reported to_delete for every table must equal (before - after) as measured
// by an independent apply on an identical fixture -- catches double-counting
// bugs that self-consistent internal arithmetic alone would not.
// ---------------------------------------------------------------------------

#[tokio::test]
async fn dry_run_to_delete_matches_apply_before_after_on_identical_fixture() {
    async fn build(name: &str) -> DatabaseManager {
        let (database, _path) = new_store(name).await;
        write_documents(&database, &["M1", "X1"]).await;
        write_nodes(&database, &[("M1", "m1-c0"), ("X1", "x1-c0")]).await;
        write_edges(&database, &["M1", "X1"]).await;
        database
    }

    let allow = allow_set(&["M1"]);

    let dry_run_db = build("cross-check-dry").await;
    let dry_run_report = run_reconcile(&dry_run_db, &allow, None, Mode::DryRun).await.unwrap();

    let apply_db = build("cross-check-apply").await;
    let before_docs = document_ids_in_table(&apply_db, "documents").await.len();
    let before_edges = document_ids_in_table(&apply_db, "edges").await.len();
    let _apply_report = run_reconcile(&apply_db, &allow, None, Mode::Apply).await.unwrap();
    let after_docs = document_ids_in_table(&apply_db, "documents").await.len();
    let after_edges = document_ids_in_table(&apply_db, "edges").await.len();

    assert_eq!(dry_run_report.per_table["documents"].to_delete, before_docs - after_docs);
    assert_eq!(dry_run_report.per_table["edges"].to_delete, before_edges - after_edges);
}
