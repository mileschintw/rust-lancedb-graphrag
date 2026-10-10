//! Evidence-metadata backfill for the `nodes` table of a LanceDB store (06.3.6-14, D-144).
//!
//! Compiling stub for the RED commit: every behaviour is neutral.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use lancedb::Connection;

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
    /// The eval store path.
    pub eval: String,
    /// The dev store path.
    pub dev: String,
}

/// The usage text.
pub const USAGE: &str = "usage: backfill_evidence_metadata (stub)";

/// Parses nothing (stub).
///
/// # Errors
/// Never fails in the stub.
pub fn parse_args<I: IntoIterator<Item = String>>(_args: I) -> Result<Command, String> {
    Ok(Command::MigrateOnly {
        lancedb_path: String::new(),
    })
}

/// Accepts everything (stub).
///
/// # Errors
/// Never fails in the stub.
pub fn check_eval_target(_target: &str, _isolation: &Isolation) -> Result<(), String> {
    Ok(())
}

/// Accepts everything (stub).
///
/// # Errors
/// Never fails in the stub.
pub fn check_copy_target(_target: &str, _isolation: &Isolation) -> Result<(), String> {
    Ok(())
}

/// Accepts everything (stub).
///
/// # Errors
/// Never fails in the stub.
pub fn check_migrate_target(_target: &str, _isolation: &Isolation) -> Result<(), String> {
    Ok(())
}

/// Accepts everything (stub).
///
/// # Errors
/// Never fails in the stub.
pub fn check_snapshot(_snapshot_dir: Option<&Path>, _lancedb_path: &str) -> Result<PathBuf, String> {
    Ok(PathBuf::new())
}

async fn connect(path: &str) -> Result<Connection, String> {
    lancedb::connect(path)
        .execute()
        .await
        .map_err(|error| format!("failed to connect to LanceDB at {path}: {error}"))
}

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

/// A finished command: its JSON report and whether it succeeded.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finished {
    /// The report, one JSON object.
    pub json: String,
    /// Whether the command's own pass criterion held.
    pub success: bool,
}

/// Runs nothing (stub).
///
/// # Errors
/// Always fails in the stub.
pub async fn run(_command: Command, _isolation: &Isolation) -> Result<Finished, String> {
    Err("not implemented".to_owned())
}

#[cfg(test)]
#[path = "../backfill_evidence_metadata_tests.rs"]
mod tests;

#[tokio::main]
async fn main() -> Result<(), String> {
    Err("not implemented".to_owned())
}
