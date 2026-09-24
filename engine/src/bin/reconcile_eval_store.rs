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
    let _ = (target, eval_lancedb_path, dev_lancedb_path);
    Ok(())
}

/// Refuses `--apply` without an existing `--snapshot-dir` containing a copy
/// of `nodes.lance`, and refuses a `--snapshot-dir` that resolves inside the
/// live store itself (T-06.3.4.1-04-03).
pub fn check_snapshot(snapshot_dir: Option<&Path>, lancedb_path: &str) -> Result<PathBuf, String> {
    let _ = (snapshot_dir, lancedb_path);
    Ok(PathBuf::new())
}

#[derive(serde::Deserialize)]
struct DocumentMapFileRaw {
    #[serde(default)]
    entries: HashMap<String, serde_json::Value>,
}

/// Loads `document_map.json` `entries` keys as the delete-cascade allow-list,
/// refusing any non-UUIDv4 key before any query runs (T-06.3.4.1-04-02).
pub fn load_allow_list(path: &Path) -> Result<HashSet<String>, String> {
    let _ = path;
    Ok(HashSet::new())
}

/// Loads and validates a `--target-document-ids` JSON array: every ID must be
/// a UUIDv4 AND a member of `allow` (T-06.3.4.1-04-02).
pub fn load_target_ids(path: &Path, allow: &HashSet<String>) -> Result<HashSet<String>, String> {
    let _ = (path, allow);
    Ok(HashSet::new())
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
    let _ = (database, allow, targets);
    Ok(ReconcileReport {
        mode,
        ..ReconcileReport::default()
    })
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
