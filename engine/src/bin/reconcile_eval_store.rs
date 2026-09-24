//! Cascade reconcile for the eval LanceDB/PostgreSQL store (06.3.4.1-04, OI-03).
//!
//! Deletes every document not present in a `document_map.json` `entries` allow-list
//! (aliases do not count) from `edges`, `nodes`, `documents`, `staged_documents_v2`
//! and `entity_edges`, then prunes `entities.source_chunk_ids` down to the
//! surviving-chunk allow-list — deleting orphaned entities (no surviving chunk)
//! and rewriting partially-orphaned ones while preserving every other column
//! byte-for-byte (RESEARCH §D; D-58).
//!
//! `--dry-run` is the default; `--apply` requires an existing `--snapshot-dir`
//! containing a copy of `nodes.lance`, and refuses any `--lancedb-path` other
//! than the configured eval store (never the dev store). This bin never calls
//! `optimize`, compaction or `cleanup_old_versions`, so LanceDB version restore
//! stays available as a second rollback layer (D-58 reversibility).

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use arrow_array::builder::{ListBuilder, StringBuilder};
use arrow_array::{Array, ArrayRef, BooleanArray, ListArray, RecordBatch, StringArray};
use arrow_select::filter::filter_record_batch;
use engine::db::DatabaseManager;
use engine::graph::escape_sql_literal;
use futures::TryStreamExt;
use lancedb::{
    query::{ExecutableQuery, QueryBase, Select},
    Table,
};
use serde::Serialize;
use uuid::Uuid;

/// Maximum number of IDs per generated `IN (...)` / endpoint predicate batch.
/// Matches the `ingest.rs`/`inspect_lancedb.rs` batching convention for this
/// codebase's LanceDB delete predicates.
const DELETE_CHUNK_SIZE: usize = 500;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    #[default]
    DryRun,
    Apply,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct PerTableCounts {
    pub before: usize,
    pub to_delete: usize,
    pub after: usize,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct EntitiesReport {
    pub total: usize,
    pub rewrite: usize,
    pub orphan: usize,
    pub untouched: usize,
    pub isolated_untouched: usize,
}

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct ReconcileReport {
    pub mode: Mode,
    pub allow_count: usize,
    pub extras: Vec<String>,
    pub per_table: BTreeMap<String, PerTableCounts>,
    pub entities: EntitiesReport,
    pub orphan_incident_entity_edges: usize,
    pub versions_before: BTreeMap<String, u64>,
    pub versions_after: BTreeMap<String, u64>,
}

fn string_column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a StringArray, String> {
    batch
        .column_by_name(name)
        .ok_or_else(|| format!("LanceDB query did not return {name}"))?
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| format!("LanceDB column {name} has an unexpected type"))
}

fn list_column<'a>(batch: &'a RecordBatch, name: &str) -> Result<&'a ListArray, String> {
    batch
        .column_by_name(name)
        .ok_or_else(|| format!("LanceDB query did not return {name}"))?
        .as_any()
        .downcast_ref::<ListArray>()
        .ok_or_else(|| format!("LanceDB column {name} has an unexpected type"))
}

/// Reads `source_chunk_ids[row]` as an owned `Vec<String>` (empty if null or 0-length).
fn list_string_values(list_col: &ListArray, row: usize) -> Result<Vec<String>, String> {
    if list_col.is_null(row) {
        return Ok(Vec::new());
    }
    let values = list_col.value(row);
    let str_values = values
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| "LanceDB list column values have unexpected type".to_owned())?;
    let mut out = Vec::with_capacity(str_values.len());
    for i in 0..str_values.len() {
        if !str_values.is_null(i) {
            out.push(str_values.value(i).to_owned());
        }
    }
    Ok(out)
}

async fn query_all(table: &Table, columns: &[&str]) -> Result<Vec<RecordBatch>, String> {
    table
        .query()
        .select(Select::columns(columns))
        .execute()
        .await
        .map_err(|error| error.to_string())?
        .try_collect()
        .await
        .map_err(|error| error.to_string())
}

/// Full read of `document_id` values from `table` (with duplicates, unlike
/// `inspect_lancedb`'s de-duplicated `--document-ids` probe — every row is
/// needed here to compute accurate per-table before/to_delete/after counts).
async fn collect_document_id_rows(table: &Table) -> Result<Vec<String>, String> {
    let batches = query_all(table, &["document_id"]).await?;
    let mut out = Vec::new();
    for batch in &batches {
        let col = string_column(batch, "document_id")?;
        for row in 0..batch.num_rows() {
            if !col.is_null(row) {
                out.push(col.value(row).to_owned());
            }
        }
    }
    Ok(out)
}

/// Full read of `(document_id, chunk_id)` pairs from `nodes`.
async fn collect_node_document_chunk_rows(table: &Table) -> Result<Vec<(String, String)>, String> {
    let batches = query_all(table, &["document_id", "chunk_id"]).await?;
    let mut out = Vec::new();
    for batch in &batches {
        let doc_col = string_column(batch, "document_id")?;
        let chunk_col = string_column(batch, "chunk_id")?;
        for row in 0..batch.num_rows() {
            if !doc_col.is_null(row) && !chunk_col.is_null(row) {
                out.push((doc_col.value(row).to_owned(), chunk_col.value(row).to_owned()));
            }
        }
    }
    Ok(out)
}

/// Full read of `(source_node_id, target_node_id, document_id)` from `entity_edges`.
async fn collect_entity_edge_rows(table: &Table) -> Result<Vec<(String, String, String)>, String> {
    let batches = query_all(table, &["source_node_id", "target_node_id", "document_id"]).await?;
    let mut out = Vec::new();
    for batch in &batches {
        let src = string_column(batch, "source_node_id")?;
        let tgt = string_column(batch, "target_node_id")?;
        let doc = string_column(batch, "document_id")?;
        for row in 0..batch.num_rows() {
            if !src.is_null(row) && !tgt.is_null(row) && !doc.is_null(row) {
                out.push((
                    src.value(row).to_owned(),
                    tgt.value(row).to_owned(),
                    doc.value(row).to_owned(),
                ));
            }
        }
    }
    Ok(out)
}

fn per_table_counts(document_ids: &[String], to_delete: &BTreeSet<String>) -> PerTableCounts {
    let before = document_ids.len();
    let deleted = document_ids.iter().filter(|id| to_delete.contains(*id)).count();
    PerTableCounts {
        before,
        to_delete: deleted,
        after: before - deleted,
    }
}

fn in_predicate(column: &str, ids: &[String]) -> String {
    let list = ids
        .iter()
        .map(|id| format!("'{}'", escape_sql_literal(id)))
        .collect::<Vec<_>>()
        .join(", ");
    format!("{column} IN ({list})")
}

async fn delete_by_column_chunked<'a, I>(table: &Table, column: &str, ids: I) -> Result<(), String>
where
    I: IntoIterator<Item = &'a String>,
{
    let ids: Vec<String> = ids.into_iter().cloned().collect();
    if ids.is_empty() {
        return Ok(());
    }
    for chunk in ids.chunks(DELETE_CHUNK_SIZE) {
        let predicate = in_predicate(column, chunk);
        table.delete(&predicate).await.map_err(|error| error.to_string())?;
    }
    Ok(())
}

async fn delete_entity_edges_by_endpoint_chunked(
    table: &Table,
    orphan_ids: &HashSet<String>,
) -> Result<(), String> {
    if orphan_ids.is_empty() {
        return Ok(());
    }
    let ids: Vec<String> = orphan_ids.iter().cloned().collect();
    for chunk in ids.chunks(DELETE_CHUNK_SIZE) {
        let list = chunk
            .iter()
            .map(|id| format!("'{}'", escape_sql_literal(id)))
            .collect::<Vec<_>>()
            .join(", ");
        let predicate = format!("(source_node_id IN ({list}) OR target_node_id IN ({list}))");
        table.delete(&predicate).await.map_err(|error| error.to_string())?;
    }
    Ok(())
}

/// Deletes rewritten entity rows and re-adds them with `source_chunk_ids`
/// replaced by `kept_by_entity`, preserving every other column byte-for-byte
/// by filtering the ORIGINAL batches (`entity_batches`, read before any
/// mutation) rather than reconstructing rows from typed fields.
async fn rewrite_entities(
    entities: &Table,
    entity_batches: &[RecordBatch],
    rewrite_ids: &HashSet<String>,
    kept_by_entity: &HashMap<String, Vec<String>>,
) -> Result<(), String> {
    if rewrite_ids.is_empty() {
        return Ok(());
    }
    delete_by_column_chunked(entities, "entity_id", rewrite_ids.iter()).await?;

    let schema = entities.schema().await.map_err(|error| error.to_string())?;
    // source_chunk_ids is column index 8 in entities_schema() (db/mod.rs):
    // entity_id, name, entity_type, name_vector, summary, summary_vector,
    // unsummarized_refs, community_ids, source_chunk_ids.
    const SOURCE_CHUNK_IDS_COLUMN: usize = 8;

    for batch in entity_batches {
        let entity_id_col = string_column(batch, "entity_id")?;
        let mask = BooleanArray::from(
            (0..batch.num_rows())
                .map(|row| Some(rewrite_ids.contains(entity_id_col.value(row))))
                .collect::<Vec<_>>(),
        );
        let filtered = filter_record_batch(batch, &mask).map_err(|error| error.to_string())?;
        if filtered.num_rows() == 0 {
            continue;
        }
        let filtered_ids = string_column(&filtered, "entity_id")?;
        let mut builder = ListBuilder::new(StringBuilder::new());
        for row in 0..filtered.num_rows() {
            let id = filtered_ids.value(row);
            let kept = kept_by_entity.get(id).cloned().unwrap_or_default();
            for chunk_id in &kept {
                builder.values().append_value(chunk_id);
            }
            builder.append(true);
        }
        let new_chunk_ids: ArrayRef = Arc::new(builder.finish());
        let mut columns: Vec<ArrayRef> = filtered.columns().to_vec();
        columns[SOURCE_CHUNK_IDS_COLUMN] = new_chunk_ids;
        let new_batch = RecordBatch::try_new(schema.clone(), columns).map_err(|error| error.to_string())?;
        entities.add(new_batch).execute().await.map_err(|error| error.to_string())?;
    }
    Ok(())
}

/// Refuses any `--lancedb-path` other than the configured eval store, and
/// refuses the dev store. Pure (aside from `canonicalize`'s filesystem read)
/// so it can be unit-tested against synthetic temp directories without
/// touching the real `config/config*.toml` files (T-06.3.4.1-04-01).
pub fn check_isolation(target: &str, eval_lancedb_path: &str, dev_lancedb_path: &str) -> Result<(), String> {
    let target_canon = std::fs::canonicalize(target).map_err(|error| {
        format!("reconcile refuses --lancedb-path {target}: cannot canonicalize ({error}); the store must exist")
    })?;
    let eval_canon = std::fs::canonicalize(eval_lancedb_path).map_err(|error| {
        format!(
            "reconcile refuses: cannot canonicalize configured eval lancedb_path {eval_lancedb_path} ({error})"
        )
    })?;
    if target_canon != eval_canon {
        return Err(format!(
            "reconcile refuses --lancedb-path {target}: does not resolve to the configured eval lancedb_path {eval_lancedb_path}"
        ));
    }
    // Dev-path comparison is defense-in-depth. The dev store may not exist on
    // this machine, so fall back to a lexical comparison rather than failing
    // the whole isolation check on a canonicalize error for the SIDE check.
    let dev_canon =
        std::fs::canonicalize(dev_lancedb_path).unwrap_or_else(|_| PathBuf::from(dev_lancedb_path));
    if target_canon == dev_canon {
        return Err(format!(
            "reconcile refuses --lancedb-path {target}: matches the dev lancedb_path {dev_lancedb_path}"
        ));
    }
    Ok(())
}

/// Refuses `--apply` without an existing `--snapshot-dir` containing a copy
/// of `nodes.lance`, and refuses a `--snapshot-dir` that resolves inside the
/// live store itself (T-06.3.4.1-04-03).
pub fn check_snapshot(snapshot_dir: Option<&Path>, lancedb_path: &str) -> Result<PathBuf, String> {
    let Some(dir) = snapshot_dir else {
        return Err(format!("--apply requires --snapshot-dir\n{USAGE}"));
    };
    let nodes_lance = dir.join("nodes.lance");
    if !nodes_lance.exists() {
        return Err(format!(
            "reconcile refuses --apply: --snapshot-dir {} does not exist or has no nodes.lance copy",
            dir.display()
        ));
    }
    let snapshot_canon = std::fs::canonicalize(dir).map_err(|error| {
        format!("reconcile refuses --snapshot-dir {}: cannot canonicalize ({error})", dir.display())
    })?;
    let live_canon = std::fs::canonicalize(lancedb_path).map_err(|error| {
        format!("reconcile refuses: cannot canonicalize --lancedb-path {lancedb_path} ({error})")
    })?;
    if snapshot_canon == live_canon || snapshot_canon.starts_with(&live_canon) {
        return Err(format!(
            "reconcile refuses --snapshot-dir {}: resolves inside the live store {lancedb_path}",
            dir.display()
        ));
    }
    Ok(snapshot_canon)
}

#[derive(serde::Deserialize)]
struct DocumentMapFileRaw {
    #[serde(default)]
    entries: HashMap<String, serde_json::Value>,
}

/// Loads `document_map.json` `entries` keys as the delete-cascade allow-list,
/// refusing any non-UUIDv4 key before any query runs (T-06.3.4.1-04-02).
/// Aliases are never consulted here — an alias document_id is therefore not
/// in the allow-list and is swept up as an extra automatically (D-58/D-60).
pub fn load_allow_list(path: &Path) -> Result<HashSet<String>, String> {
    let bytes = std::fs::read_to_string(path)
        .map_err(|error| format!("failed to read --document-map {}: {error}", path.display()))?;
    let map: DocumentMapFileRaw = serde_json::from_str(&bytes)
        .map_err(|error| format!("failed to parse --document-map {}: {error}", path.display()))?;

    let mut allow = HashSet::with_capacity(map.entries.len());
    for key in map.entries.keys() {
        let parsed = Uuid::parse_str(key).map_err(|_| format!("document_map entry '{key}' is not a valid UUID"))?;
        if parsed.get_version_num() != 4 {
            return Err(format!("document_map entry '{key}' is not a UUIDv4"));
        }
        allow.insert(key.clone());
    }
    Ok(allow)
}

/// Loads and validates a `--target-document-ids` JSON array: every ID must be
/// a UUIDv4 AND a member of `allow` (T-06.3.4.1-04-02).
pub fn load_target_ids(path: &Path, allow: &HashSet<String>) -> Result<HashSet<String>, String> {
    let bytes = std::fs::read_to_string(path)
        .map_err(|error| format!("failed to read --target-document-ids {}: {error}", path.display()))?;
    let raw: Vec<String> = serde_json::from_str(&bytes)
        .map_err(|error| format!("failed to parse --target-document-ids {}: {error}", path.display()))?;

    let mut ids = HashSet::with_capacity(raw.len());
    for id in raw {
        let parsed = Uuid::parse_str(&id)
            .map_err(|_| format!("--target-document-ids entry '{id}' is not a valid UUID"))?;
        if parsed.get_version_num() != 4 {
            return Err(format!("--target-document-ids entry '{id}' is not a UUIDv4"));
        }
        if !allow.contains(&id) {
            return Err(format!(
                "--target-document-ids entry '{id}' is not a document_map.json entries key"
            ));
        }
        ids.insert(id);
    }
    Ok(ids)
}

/// Runs the cascade: computes (or takes, for `--target-document-ids`) the
/// delete set, deletes dependent rows in `edges, nodes, documents,
/// staged_documents_v2, entity_edges` order, then prunes `entities` by the
/// surviving-chunk allow-list. In `Mode::DryRun`, computes everything with
/// read-only queries and writes nothing.
///
/// # Errors
/// Returns an error if any table cannot be opened, queried or (in
/// `Mode::Apply`) mutated.
pub async fn run_reconcile(
    database: &DatabaseManager,
    allow: &HashSet<String>,
    targets: Option<&HashSet<String>>,
    mode: Mode,
) -> Result<ReconcileReport, String> {
    let documents = database.documents_table().await?;
    let nodes = database.nodes_table().await?;
    let edges = database.edges_table().await?;
    let staged = database.staged_documents_table().await?;
    let entity_edges = database.entity_edges_table().await?;
    let entities = database.entities_table().await?;
    let communities = database.communities_table().await?;

    let versions_before = read_all_versions(&documents, &nodes, &edges, &staged, &entity_edges, &entities, &communities)
        .await?;

    // Up-front, read-only reads. Used for BOTH the report's counts and (in
    // apply mode) the mutation targeting below — never re-derived from a
    // post-delete query, so dry-run and apply compute identical sets.
    let documents_ids = collect_document_id_rows(&documents).await?;
    let nodes_pairs = collect_node_document_chunk_rows(&nodes).await?;
    let edges_ids = collect_document_id_rows(&edges).await?;
    let staged_ids = collect_document_id_rows(&staged).await?;
    let entity_edges_rows = collect_entity_edge_rows(&entity_edges).await?;

    let extras: BTreeSet<String> = {
        let mut set: BTreeSet<String> = BTreeSet::new();
        set.extend(documents_ids.iter().cloned());
        set.extend(nodes_pairs.iter().map(|(doc, _)| doc.clone()));
        set.extend(edges_ids.iter().cloned());
        set.extend(entity_edges_rows.iter().map(|(_, _, doc)| doc.clone()));
        set.retain(|id| !allow.contains(id));
        set
    };

    let to_delete: BTreeSet<String> = match targets {
        Some(explicit) => explicit.iter().cloned().collect(),
        None => extras.clone(),
    };

    let surviving_chunks: HashSet<String> = nodes_pairs
        .iter()
        .filter(|(doc, _)| !to_delete.contains(doc))
        .map(|(_, chunk)| chunk.clone())
        .collect();

    let mut per_table = BTreeMap::new();
    per_table.insert("documents".to_owned(), per_table_counts(&documents_ids, &to_delete));
    let node_doc_ids: Vec<String> = nodes_pairs.iter().map(|(doc, _)| doc.clone()).collect();
    per_table.insert("nodes".to_owned(), per_table_counts(&node_doc_ids, &to_delete));
    per_table.insert("edges".to_owned(), per_table_counts(&edges_ids, &to_delete));
    per_table.insert(
        "staged_documents_v2".to_owned(),
        per_table_counts(&staged_ids, &to_delete),
    );

    // Entity classification, from a single full read of the ORIGINAL rows
    // (before any mutation) so the rewrite step can filter these same
    // in-memory batches instead of reconstructing rows from typed fields.
    let entity_batches = query_all(
        &entities,
        &[
            "entity_id",
            "name",
            "entity_type",
            "name_vector",
            "summary",
            "summary_vector",
            "unsummarized_refs",
            "community_ids",
            "source_chunk_ids",
        ],
    )
    .await?;

    let mut kept_by_entity: HashMap<String, Vec<String>> = HashMap::new();
    let mut orphan_ids: HashSet<String> = HashSet::new();
    let mut rewrite_ids: HashSet<String> = HashSet::new();
    let mut untouched_ids: HashSet<String> = HashSet::new();
    let mut total_entities = 0usize;

    for batch in &entity_batches {
        let entity_id_col = string_column(batch, "entity_id")?;
        let source_chunk_ids_col = list_column(batch, "source_chunk_ids")?;
        for row in 0..batch.num_rows() {
            total_entities += 1;
            let entity_id = entity_id_col.value(row).to_owned();
            let original = list_string_values(source_chunk_ids_col, row)?;
            let kept: Vec<String> = original
                .iter()
                .filter(|chunk_id| surviving_chunks.contains(*chunk_id))
                .cloned()
                .collect();
            if kept.is_empty() {
                orphan_ids.insert(entity_id);
            } else if kept.len() != original.len() {
                kept_by_entity.insert(entity_id.clone(), kept);
                rewrite_ids.insert(entity_id);
            } else {
                untouched_ids.insert(entity_id);
            }
        }
    }

    // entity_edges: step 2 (document_id-based) removes rows whose OWN
    // document is being deleted; step 5 (orphan-incident) additionally
    // removes rows whose document is untouched but one endpoint entity was
    // just orphaned. orphan_incident is scoped to rows NOT already counted
    // by step 2, so the two counts never double-count the same row.
    let step2_entity_edges = entity_edges_rows
        .iter()
        .filter(|(_, _, doc)| to_delete.contains(doc))
        .count();
    let remaining_after_step2: Vec<&(String, String, String)> = entity_edges_rows
        .iter()
        .filter(|(_, _, doc)| !to_delete.contains(doc))
        .collect();
    let orphan_incident_entity_edges = remaining_after_step2
        .iter()
        .filter(|(source, target, _)| orphan_ids.contains(source) || orphan_ids.contains(target))
        .count();
    let entity_edges_to_delete = step2_entity_edges + orphan_incident_entity_edges;
    per_table.insert(
        "entity_edges".to_owned(),
        PerTableCounts {
            before: entity_edges_rows.len(),
            to_delete: entity_edges_to_delete,
            after: entity_edges_rows.len() - entity_edges_to_delete,
        },
    );

    let surviving_entity_edges: Vec<&(String, String, String)> = remaining_after_step2
        .into_iter()
        .filter(|(source, target, _)| !orphan_ids.contains(source) && !orphan_ids.contains(target))
        .collect();
    let mut degree: HashMap<&str, usize> = HashMap::new();
    for (source, target, _) in &surviving_entity_edges {
        *degree.entry(source.as_str()).or_insert(0) += 1;
        *degree.entry(target.as_str()).or_insert(0) += 1;
    }
    let isolated_untouched = untouched_ids
        .iter()
        .filter(|id| degree.get(id.as_str()).copied().unwrap_or(0) == 0)
        .count();

    let entities_report = EntitiesReport {
        total: total_entities,
        rewrite: rewrite_ids.len(),
        orphan: orphan_ids.len(),
        untouched: untouched_ids.len(),
        isolated_untouched,
    };

    if mode == Mode::Apply {
        delete_by_column_chunked(&edges, "document_id", to_delete.iter()).await?;
        delete_by_column_chunked(&nodes, "document_id", to_delete.iter()).await?;
        delete_by_column_chunked(&documents, "document_id", to_delete.iter()).await?;
        delete_by_column_chunked(&staged, "document_id", to_delete.iter()).await?;
        delete_by_column_chunked(&entity_edges, "document_id", to_delete.iter()).await?;

        rewrite_entities(&entities, &entity_batches, &rewrite_ids, &kept_by_entity).await?;
        delete_by_column_chunked(&entities, "entity_id", orphan_ids.iter()).await?;
        delete_entity_edges_by_endpoint_chunked(&entity_edges, &orphan_ids).await?;
    }

    let versions_after = read_all_versions(&documents, &nodes, &edges, &staged, &entity_edges, &entities, &communities)
        .await?;

    Ok(ReconcileReport {
        mode,
        allow_count: allow.len(),
        extras: to_delete.into_iter().collect(),
        per_table,
        entities: entities_report,
        orphan_incident_entity_edges,
        versions_before,
        versions_after,
    })
}

#[allow(clippy::too_many_arguments)]
async fn read_all_versions(
    documents: &Table,
    nodes: &Table,
    edges: &Table,
    staged: &Table,
    entity_edges: &Table,
    entities: &Table,
    communities: &Table,
) -> Result<BTreeMap<String, u64>, String> {
    let mut versions = BTreeMap::new();
    versions.insert(
        "documents".to_owned(),
        documents.version().await.map_err(|error| error.to_string())?,
    );
    versions.insert("nodes".to_owned(), nodes.version().await.map_err(|error| error.to_string())?);
    versions.insert("edges".to_owned(), edges.version().await.map_err(|error| error.to_string())?);
    versions.insert(
        "staged_documents_v2".to_owned(),
        staged.version().await.map_err(|error| error.to_string())?,
    );
    versions.insert(
        "entity_edges".to_owned(),
        entity_edges.version().await.map_err(|error| error.to_string())?,
    );
    versions.insert(
        "entities".to_owned(),
        entities.version().await.map_err(|error| error.to_string())?,
    );
    versions.insert(
        "communities".to_owned(),
        communities.version().await.map_err(|error| error.to_string())?,
    );
    Ok(versions)
}

pub struct CliConfig {
    pub document_map: PathBuf,
    pub lancedb_path: String,
    pub apply: bool,
    pub snapshot_dir: Option<PathBuf>,
    pub target_document_ids: Option<PathBuf>,
}

pub const USAGE: &str = "usage: reconcile_eval_store --document-map PATH --lancedb-path PATH [--apply --snapshot-dir PATH] [--target-document-ids PATH]";

pub fn parse_args<I: IntoIterator<Item = String>>(args: I) -> Result<CliConfig, String> {
    let mut iter = args.into_iter();
    let mut document_map = None;
    let mut lancedb_path = None;
    let mut apply = false;
    let mut snapshot_dir = None;
    let mut target_document_ids = None;

    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--document-map" => {
                document_map =
                    Some(iter.next().ok_or_else(|| format!("--document-map requires a value\n{USAGE}"))?);
            }
            "--lancedb-path" => {
                lancedb_path =
                    Some(iter.next().ok_or_else(|| format!("--lancedb-path requires a value\n{USAGE}"))?);
            }
            "--apply" => {
                apply = true;
            }
            "--snapshot-dir" => {
                snapshot_dir =
                    Some(iter.next().ok_or_else(|| format!("--snapshot-dir requires a value\n{USAGE}"))?);
            }
            "--target-document-ids" => {
                target_document_ids = Some(
                    iter.next()
                        .ok_or_else(|| format!("--target-document-ids requires a value\n{USAGE}"))?,
                );
            }
            _ => return Err(format!("unknown argument '{arg}'\n{USAGE}")),
        }
    }

    let document_map = document_map.ok_or_else(|| format!("--document-map is required\n{USAGE}"))?;
    let lancedb_path = lancedb_path.ok_or_else(|| format!("--lancedb-path is required\n{USAGE}"))?;
    if !apply && snapshot_dir.is_some() {
        return Err(format!("--snapshot-dir is only valid with --apply\n{USAGE}"));
    }

    Ok(CliConfig {
        document_map: PathBuf::from(document_map),
        lancedb_path,
        apply,
        snapshot_dir: snapshot_dir.map(PathBuf::from),
        target_document_ids: target_document_ids.map(PathBuf::from),
    })
}

fn base_config_path() -> &'static str {
    if Path::new("../config/config.toml").exists() {
        "../config/config"
    } else {
        "config/config"
    }
}

/// Reads `engine.lancedb_path` from `config/config.toml` alone (the dev store
/// path) — no `LANCET_ENV`, no environment source, so no env var can redirect
/// this comparison target (T-06.3.4.1-04-01).
fn configured_dev_lancedb_path() -> Result<String, String> {
    let base = base_config_path();
    config::Config::builder()
        .add_source(config::File::with_name(base))
        .build()
        .map_err(|error| error.to_string())?
        .get_string("engine.lancedb_path")
        .map_err(|error| error.to_string())
}

/// Reads `engine.lancedb_path` from `config/config.toml` layered with
/// `config/config.eval.toml` (the eval store path) — no `LANCET_ENV`, no
/// environment source.
fn configured_eval_lancedb_path() -> Result<String, String> {
    let base = base_config_path();
    config::Config::builder()
        .add_source(config::File::with_name(base))
        .add_source(config::File::with_name(&format!("{base}.eval")))
        .build()
        .map_err(|error| error.to_string())?
        .get_string("engine.lancedb_path")
        .map_err(|error| error.to_string())
}

#[cfg(test)]
#[path = "../reconcile_eval_store_tests.rs"]
mod tests;

#[tokio::main]
async fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let cli = parse_args(args)?;

    let eval_cfg = configured_eval_lancedb_path()?;
    let dev_cfg = configured_dev_lancedb_path()?;
    check_isolation(&cli.lancedb_path, &eval_cfg, &dev_cfg)?;

    let allow = load_allow_list(&cli.document_map)?;

    let mode = if cli.apply { Mode::Apply } else { Mode::DryRun };
    if cli.apply {
        check_snapshot(cli.snapshot_dir.as_deref(), &cli.lancedb_path)?;
    }

    let targets = match &cli.target_document_ids {
        Some(path) => Some(load_target_ids(path, &allow)?),
        None => None,
    };

    let database = DatabaseManager::open_and_validate(&cli.lancedb_path).await?;
    let report = run_reconcile(&database, &allow, targets.as_ref(), mode).await?;

    println!(
        "{}",
        serde_json::to_string(&report).map_err(|error| error.to_string())?
    );
    Ok(())
}
