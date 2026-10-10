//! Evidence-metadata backfill for the `nodes` table of a LanceDB store (06.3.6-14, D-144).
//!
//! The engine never upgrades a legacy `nodes` table: a store written before the `doc_title`,
//! `source` and `published_date` columns fails closed until this bin migrates it. The bin has four
//! modes, each guarded so the eval store is only ever written by a verified `--apply`:
//!
//! - **dry run** (the default, `--lancedb-path` and `--sidecar`): reports the schema state, the
//!   sidecar coverage and every table's version, and writes nothing. The path must resolve to the
//!   configured eval store.
//! - **`--apply`**: runs the backfill. It needs `--snapshot-dir` holding a copy of `nodes.lance`
//!   outside the live store, and refuses any `--lancedb-path` other than the configured eval store.
//!   The report lists the version of every table before and after, so a caller can check that only
//!   `nodes` moved.
//! - **`--verify-on-copy <dir>`** (with `--sidecar`): runs the backfill on a copy of a store and
//!   prints the five COPY assertions as JSON. It refuses the configured eval and dev stores.
//! - **`--migrate-only`** (with `--lancedb-path`): adds the three columns as nulls to a store that is
//!   not the eval store, so a dev store opens again.
//!
//! The store is opened with a raw `lancedb::connect`, because the validating opener
//! would refuse the legacy schema this bin exists to migrate. The bin never calls the table
//! optimiser, compaction or version cleanup, so every earlier version stays available for a
//! restore, and it never re-runs entity extraction: `nodes` is the only table it changes.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use engine::db::backfill::{
    backfill_nodes_metadata, classify_nodes_schema, verify_backfill_on_copy, BackfillOutcome,
    NodesSchemaState, Sidecar,
};
use lancedb::Connection;
use serde::Serialize;

/// The command line, parsed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Command {
    /// Report only; the default.
    DryRun {
        /// The store to inspect.
        lancedb_path: String,
        /// The sidecar file.
        sidecar: PathBuf,
    },
    /// Apply the backfill to the eval store.
    Apply {
        /// The store to change.
        lancedb_path: String,
        /// The sidecar file.
        sidecar: PathBuf,
        /// The directory holding a copy of `nodes.lance`.
        snapshot_dir: Option<PathBuf>,
    },
    /// Run the backfill on a copy and report the COPY assertions.
    VerifyOnCopy {
        /// The copied store directory.
        dir: String,
        /// The sidecar file.
        sidecar: PathBuf,
    },
    /// Add three null columns to a store that is not the eval store.
    MigrateOnly {
        /// The store to migrate.
        lancedb_path: String,
    },
}

/// The two configured store paths a command is checked against.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Isolation {
    /// `engine.lancedb_path` of `config/config.toml` layered with `config/config.eval.toml`.
    pub eval: String,
    /// `engine.lancedb_path` of `config/config.toml` alone.
    pub dev: String,
}

/// The usage text.
pub const USAGE: &str = "usage: backfill_evidence_metadata --lancedb-path PATH --sidecar PATH [--apply --snapshot-dir PATH]\n       backfill_evidence_metadata --verify-on-copy DIR --sidecar PATH\n       backfill_evidence_metadata --migrate-only --lancedb-path PATH";

fn flag_value(iter: &mut impl Iterator<Item = String>, flag: &str) -> Result<String, String> {
    iter.next()
        .ok_or_else(|| format!("{flag} requires a value\n{USAGE}"))
}

/// Parses the command line.
///
/// # Errors
/// Returns the usage text with the reason for an unknown flag, a missing value or a combination
/// of flags no mode accepts.
pub fn parse_args<I: IntoIterator<Item = String>>(args: I) -> Result<Command, String> {
    let mut iter = args.into_iter();
    let mut lancedb_path = None;
    let mut sidecar = None;
    let mut apply = false;
    let mut snapshot_dir = None;
    let mut verify_on_copy = None;
    let mut migrate_only = false;

    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--lancedb-path" => lancedb_path = Some(flag_value(&mut iter, &arg)?),
            "--sidecar" => sidecar = Some(flag_value(&mut iter, &arg)?),
            "--snapshot-dir" => snapshot_dir = Some(flag_value(&mut iter, &arg)?),
            "--verify-on-copy" => verify_on_copy = Some(flag_value(&mut iter, &arg)?),
            "--apply" => apply = true,
            "--migrate-only" => migrate_only = true,
            _ => return Err(format!("unknown argument '{arg}'\n{USAGE}")),
        }
    }

    if snapshot_dir.is_some() && !apply {
        return Err(format!(
            "--snapshot-dir is only valid with --apply\n{USAGE}"
        ));
    }
    let modes = [apply, migrate_only, verify_on_copy.is_some()];
    if modes.iter().filter(|mode| **mode).count() > 1 {
        return Err(format!(
            "--apply, --migrate-only and --verify-on-copy are mutually exclusive\n{USAGE}"
        ));
    }
    let need_sidecar = |sidecar: Option<String>| {
        sidecar
            .map(PathBuf::from)
            .ok_or_else(|| format!("--sidecar is required\n{USAGE}"))
    };
    let need_path =
        |path: Option<String>| path.ok_or_else(|| format!("--lancedb-path is required\n{USAGE}"));

    if let Some(dir) = verify_on_copy {
        if lancedb_path.is_some() {
            return Err(format!(
                "--verify-on-copy names the store itself; --lancedb-path is not valid with it\n{USAGE}"
            ));
        }
        return Ok(Command::VerifyOnCopy {
            dir,
            sidecar: need_sidecar(sidecar)?,
        });
    }
    if migrate_only {
        if sidecar.is_some() {
            return Err(format!(
                "--sidecar is not valid with --migrate-only\n{USAGE}"
            ));
        }
        return Ok(Command::MigrateOnly {
            lancedb_path: need_path(lancedb_path)?,
        });
    }
    let lancedb_path = need_path(lancedb_path)?;
    let sidecar = need_sidecar(sidecar)?;
    Ok(if apply {
        Command::Apply {
            lancedb_path,
            sidecar,
            snapshot_dir: snapshot_dir.map(PathBuf::from),
        }
    } else {
        Command::DryRun {
            lancedb_path,
            sidecar,
        }
    })
}

fn canonical(path: &str, what: &str) -> Result<PathBuf, String> {
    std::fs::canonicalize(path)
        .map_err(|error| format!("refused: cannot canonicalize {what} {path} ({error})"))
}

/// The dev store may not exist on this machine, so a lexical comparison stands in for it.
fn canonical_dev(dev: &str) -> PathBuf {
    std::fs::canonicalize(dev).unwrap_or_else(|_| PathBuf::from(dev))
}

/// Requires `target` to resolve to the configured eval store and not to the dev store.
///
/// # Errors
/// Returns the refusal text when the target is missing, is not the eval store, or is the dev store.
pub fn check_eval_target(target: &str, isolation: &Isolation) -> Result<(), String> {
    let target_path = canonical(target, "--lancedb-path")?;
    let eval = canonical(&isolation.eval, "the configured eval lancedb_path")?;
    if target_path != eval {
        return Err(format!(
            "refused --lancedb-path {target}: does not resolve to the configured eval lancedb_path {}",
            isolation.eval
        ));
    }
    if target_path == canonical_dev(&isolation.dev) {
        return Err(format!(
            "refused --lancedb-path {target}: matches the dev lancedb_path {}",
            isolation.dev
        ));
    }
    Ok(())
}

/// Refuses a copy that is the configured eval store or the dev store.
///
/// The check compares canonical paths, not names: a copy made under any other directory passes,
/// including one that keeps the directory name `lancedb-eval`.
///
/// # Errors
/// Returns the refusal text when the copy is missing or is the eval or dev store.
pub fn check_copy_target(target: &str, isolation: &Isolation) -> Result<(), String> {
    let target_path = canonical(target, "--verify-on-copy")?;
    if let Ok(eval) = std::fs::canonicalize(&isolation.eval) {
        if target_path == eval {
            return Err(format!(
                "refused --verify-on-copy {target}: that is the configured eval store, not a copy"
            ));
        }
    }
    if target_path == canonical_dev(&isolation.dev) {
        return Err(format!(
            "refused --verify-on-copy {target}: that is the dev store, not a copy"
        ));
    }
    Ok(())
}

/// Refuses the configured eval store; any other existing store may be migrated.
///
/// # Errors
/// Returns the refusal text when the target is missing or is the eval store.
pub fn check_migrate_target(target: &str, isolation: &Isolation) -> Result<(), String> {
    let target_path = canonical(target, "--lancedb-path")?;
    if let Ok(eval) = std::fs::canonicalize(&isolation.eval) {
        if target_path == eval {
            return Err(format!(
                "refused --migrate-only {target}: that is the configured eval store, which only a verified --apply may change"
            ));
        }
    }
    Ok(())
}

/// Requires `--snapshot-dir` to hold a copy of `nodes.lance` outside the live store.
///
/// # Errors
/// Returns the refusal text when the directory is absent, has no `nodes.lance`, or resolves inside
/// the live store.
pub fn check_snapshot(snapshot_dir: Option<&Path>, lancedb_path: &str) -> Result<PathBuf, String> {
    let Some(dir) = snapshot_dir else {
        return Err(format!("--apply requires --snapshot-dir\n{USAGE}"));
    };
    if !dir.join("nodes.lance").exists() {
        return Err(format!(
            "refused --apply: --snapshot-dir {} does not exist or has no nodes.lance copy",
            dir.display()
        ));
    }
    let snapshot = std::fs::canonicalize(dir).map_err(|error| {
        format!(
            "refused --snapshot-dir {}: cannot canonicalize ({error})",
            dir.display()
        )
    })?;
    let live = canonical(lancedb_path, "--lancedb-path")?;
    if snapshot.starts_with(&live) {
        return Err(format!(
            "refused --snapshot-dir {}: resolves inside the live store {lancedb_path}",
            dir.display()
        ));
    }
    Ok(snapshot)
}

async fn connect(path: &str) -> Result<Connection, String> {
    lancedb::connect(path)
        .execute()
        .await
        .map_err(|error| format!("failed to connect to LanceDB at {path}: {error}"))
}

/// The version of every table in the store, read through fresh handles.
async fn all_versions(connection: &Connection) -> Result<BTreeMap<String, u64>, String> {
    let mut versions = BTreeMap::new();
    for name in connection
        .table_names()
        .execute()
        .await
        .map_err(|error| format!("failed to list tables: {error}"))?
    {
        let table = connection
            .open_table(&name)
            .execute()
            .await
            .map_err(|error| format!("failed to open table {name}: {error}"))?;
        let version = table
            .version()
            .await
            .map_err(|error| format!("failed to read the version of {name}: {error}"))?;
        versions.insert(name, version);
    }
    Ok(versions)
}

#[derive(Serialize)]
struct DryRunReport {
    mode: &'static str,
    nodes_schema: NodesSchemaState,
    sidecar_documents: usize,
    nodes_documents: usize,
    uncovered_document_ids: Vec<String>,
    sidecar_ids_absent_from_nodes: Vec<String>,
    versions: BTreeMap<String, u64>,
}

#[derive(Serialize)]
struct ApplyReport {
    mode: &'static str,
    outcome: BackfillOutcome,
    versions_before: BTreeMap<String, u64>,
    versions_after: BTreeMap<String, u64>,
}

#[derive(Serialize)]
struct MigrateReport {
    mode: &'static str,
    outcome: BackfillOutcome,
    versions_before: BTreeMap<String, u64>,
    versions_after: BTreeMap<String, u64>,
}

fn to_json<T: Serialize>(report: &T) -> Result<String, String> {
    serde_json::to_string(report).map_err(|error| error.to_string())
}

/// A finished command: its JSON report and whether it succeeded.
///
/// Only `--verify-on-copy` can finish unsuccessfully: the report is complete and readable, and a
/// failed assertion sets `success` to false so the exit status carries the verdict.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finished {
    /// The report, one JSON object.
    pub json: String,
    /// Whether the command's own pass criterion held.
    pub success: bool,
}

impl Finished {
    fn passed(json: String) -> Self {
        Self {
            json,
            success: true,
        }
    }
}

/// Runs one command and returns its JSON report.
///
/// # Errors
/// Returns the refusal or failure text.
pub async fn run(command: Command, isolation: &Isolation) -> Result<Finished, String> {
    match command {
        Command::DryRun {
            lancedb_path,
            sidecar,
        } => {
            check_eval_target(&lancedb_path, isolation)?;
            let sidecar = Sidecar::load(&sidecar)?;
            dry_run(&lancedb_path, &sidecar).await.map(Finished::passed)
        }
        Command::Apply {
            lancedb_path,
            sidecar,
            snapshot_dir,
        } => {
            check_eval_target(&lancedb_path, isolation)?;
            check_snapshot(snapshot_dir.as_deref(), &lancedb_path)?;
            let sidecar = Sidecar::load(&sidecar)?;
            let connection = connect(&lancedb_path).await?;
            let versions_before = all_versions(&connection).await?;
            let outcome = backfill_on(&connection, &sidecar).await?;
            let versions_after = all_versions(&connection).await?;
            to_json(&ApplyReport {
                mode: "apply",
                outcome,
                versions_before,
                versions_after,
            })
            .map(Finished::passed)
        }
        Command::VerifyOnCopy { dir, sidecar } => {
            check_copy_target(&dir, isolation)?;
            let sidecar = Sidecar::load(&sidecar)?;
            let report = verify_backfill_on_copy(&dir, &sidecar).await?;
            Ok(Finished {
                json: to_json(&report)?,
                success: report.all_passed(),
            })
        }
        Command::MigrateOnly { lancedb_path } => {
            check_migrate_target(&lancedb_path, isolation)?;
            let connection = connect(&lancedb_path).await?;
            let versions_before = all_versions(&connection).await?;
            let outcome = backfill_on(&connection, &Sidecar::empty()).await?;
            let versions_after = all_versions(&connection).await?;
            to_json(&MigrateReport {
                mode: "migrate_only",
                outcome,
                versions_before,
                versions_after,
            })
            .map(Finished::passed)
        }
    }
}

async fn backfill_on(
    connection: &Connection,
    sidecar: &Sidecar,
) -> Result<BackfillOutcome, String> {
    let table = connection
        .open_table("nodes")
        .execute()
        .await
        .map_err(|error| format!("failed to open nodes: {error}"))?;
    backfill_nodes_metadata(&table, sidecar).await
}

async fn dry_run(lancedb_path: &str, sidecar: &Sidecar) -> Result<String, String> {
    use futures::TryStreamExt;
    use lancedb::query::{ExecutableQuery, QueryBase, Select};

    let connection = connect(lancedb_path).await?;
    let table = connection
        .open_table("nodes")
        .execute()
        .await
        .map_err(|error| format!("failed to open nodes: {error}"))?;
    let schema = table
        .schema()
        .await
        .map_err(|error| format!("failed to read the nodes schema: {error}"))?;
    let batches: Vec<arrow_array::RecordBatch> = table
        .query()
        .select(Select::columns(&["document_id"]))
        .execute()
        .await
        .map_err(|error| format!("nodes scan failed: {error}"))?
        .try_collect()
        .await
        .map_err(|error| format!("nodes scan collection failed: {error}"))?;
    let mut documents = std::collections::BTreeSet::new();
    for batch in &batches {
        let ids = batch
            .column(0)
            .as_any()
            .downcast_ref::<arrow_array::StringArray>()
            .ok_or("nodes document_id is not a string column")?;
        for row in 0..batch.num_rows() {
            documents.insert(ids.value(row).to_owned());
        }
    }
    let uncovered = documents
        .iter()
        .filter(|id| sidecar.get(id).is_none())
        .cloned()
        .collect();
    let absent = sidecar
        .document_ids()
        .filter(|id| !documents.contains(*id))
        .map(str::to_owned)
        .collect();
    to_json(&DryRunReport {
        mode: "dry_run",
        nodes_schema: classify_nodes_schema(&schema),
        sidecar_documents: sidecar.len(),
        nodes_documents: documents.len(),
        uncovered_document_ids: uncovered,
        sidecar_ids_absent_from_nodes: absent,
        versions: all_versions(&connection).await?,
    })
}

fn base_config_path() -> &'static str {
    if Path::new("../config/config.toml").exists() {
        "../config/config"
    } else {
        "config/config"
    }
}

/// Reads `engine.lancedb_path` from `config/config.toml` alone (the dev store path): no
/// `LANCET_ENV` and no environment source, so no variable can redirect the comparison target.
fn configured_dev_lancedb_path() -> Result<String, String> {
    config::Config::builder()
        .add_source(config::File::with_name(base_config_path()))
        .build()
        .map_err(|error| error.to_string())?
        .get_string("engine.lancedb_path")
        .map_err(|error| error.to_string())
}

/// Reads `engine.lancedb_path` from `config/config.toml` layered with `config/config.eval.toml`
/// (the eval store path), again with no environment source.
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
#[path = "../backfill_evidence_metadata_tests.rs"]
mod tests;

#[tokio::main]
async fn main() -> Result<(), String> {
    let command = parse_args(std::env::args().skip(1))?;
    let isolation = Isolation {
        eval: configured_eval_lancedb_path()?,
        dev: configured_dev_lancedb_path()?,
    };
    let finished = run(command, &isolation).await?;
    println!("{}", finished.json);
    if finished.success {
        Ok(())
    } else {
        Err(
            "COPY verification failed: at least one assertion is false (see the report above)"
                .to_owned(),
        )
    }
}
