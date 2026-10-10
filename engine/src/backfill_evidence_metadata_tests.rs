use std::path::{Path, PathBuf};
use std::sync::Arc;

use arrow_array::types::Float32Type;
use arrow_array::{FixedSizeListArray, Int32Array, Int64Array, RecordBatch, StringArray};
use engine::db::backfill::legacy_nodes_schema_v19;
use engine::db::{nodes_schema, DatabaseManager};
use uuid::Uuid;

use super::{
    all_versions, check_copy_target, check_eval_target, check_migrate_target, check_snapshot,
    connect, parse_args, run, Command, Isolation, USAGE,
};

fn temp_path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!("lancet-backfill-bin-{name}-{}", Uuid::new_v4()))
}

fn as_str(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

fn fixture_doc(index: usize) -> String {
    format!("{index:08x}-0000-4000-8000-{index:012x}")
}

/// A store with a 19-column `nodes` of one chunk per document in three fragments.
async fn legacy_store(path: &Path, docs: usize) {
    let path = as_str(path);
    drop(DatabaseManager::initialize(&path).await.unwrap());
    let connection = lancedb::connect(&path).execute().await.unwrap();
    connection.drop_table("nodes", &[]).await.unwrap();
    let table = connection
        .create_empty_table("nodes", legacy_nodes_schema_v19())
        .execute()
        .await
        .unwrap();
    let step = docs / 3 + 1;
    let mut start = 0;
    while start < docs {
        let end = (start + step).min(docs);
        let rows = end - start;
        let ids: Vec<String> = (start..end).map(fixture_doc).collect();
        let chunk_ids: Vec<String> = ids.iter().map(|id| format!("{id}:0")).collect();
        let embeddings = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
            (0..rows).map(|row| Some((0..2048).map(move |k| Some(((row + k) % 31) as f32 / 31.0)))),
            2048,
        );
        let batch = RecordBatch::try_new(
            legacy_nodes_schema_v19(),
            vec![
                Arc::new(StringArray::from(ids)),
                Arc::new(StringArray::from(chunk_ids)),
                Arc::new(Int32Array::from(vec![0; rows])),
                Arc::new(Int32Array::from(vec![0; rows])),
                Arc::new(Int32Array::from(vec![9; rows])),
                Arc::new(StringArray::from(vec!["fixture content"; rows])),
                Arc::new(embeddings),
                Arc::new(Int32Array::from(vec![3; rows])),
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
        .unwrap();
        table.add(batch).execute().await.unwrap();
        start = end;
    }
}

fn write_sidecar(dir: &Path, docs: impl IntoIterator<Item = usize>) -> PathBuf {
    std::fs::create_dir_all(dir).unwrap();
    let rows: Vec<String> = docs
        .into_iter()
        .map(|doc| {
            format!(
                "\"{}\": {{\"doc_title\": \"Title {doc}\", \"source\": \"Source {}\", \"published_date\": \"2023-10-{:02}\"}}",
                fixture_doc(doc),
                doc % 5,
                1 + doc % 28
            )
        })
        .collect();
    let path = dir.join("sidecar.json");
    std::fs::write(
        &path,
        format!("{{\"schema\": 1, \"rows\": {{{}}}}}", rows.join(", ")),
    )
    .unwrap();
    path
}

fn copy_dir(from: &Path, to: &Path) {
    std::fs::create_dir_all(to).unwrap();
    for entry in std::fs::read_dir(from).unwrap() {
        let entry = entry.unwrap();
        let target = to.join(entry.file_name());
        if entry.path().is_dir() {
            copy_dir(&entry.path(), &target);
        } else {
            std::fs::copy(entry.path(), target).unwrap();
        }
    }
}

fn args(items: &[&str]) -> Vec<String> {
    items.iter().map(|item| (*item).to_owned()).collect()
}

/// Isolation whose eval and dev stores are two directories that exist.
fn isolation(eval: &Path, dev: &Path) -> Isolation {
    Isolation {
        eval: as_str(eval),
        dev: as_str(dev),
    }
}

fn json(finished: &super::Finished) -> serde_json::Value {
    serde_json::from_str(&finished.json).unwrap()
}

// ---- command line ---------------------------------------------------------------------------

#[test]
fn the_default_mode_is_a_dry_run() {
    let command = parse_args(args(&["--lancedb-path", "store", "--sidecar", "side.json"])).unwrap();
    assert_eq!(
        command,
        Command::DryRun {
            lancedb_path: "store".into(),
            sidecar: PathBuf::from("side.json"),
        }
    );
}

#[test]
fn the_four_modes_parse_with_their_flags() {
    assert_eq!(
        parse_args(args(&[
            "--lancedb-path",
            "store",
            "--sidecar",
            "s.json",
            "--apply",
            "--snapshot-dir",
            "snap"
        ]))
        .unwrap(),
        Command::Apply {
            lancedb_path: "store".into(),
            sidecar: PathBuf::from("s.json"),
            snapshot_dir: Some(PathBuf::from("snap")),
        }
    );
    assert_eq!(
        parse_args(args(&["--verify-on-copy", "copy", "--sidecar", "s.json"])).unwrap(),
        Command::VerifyOnCopy {
            dir: "copy".into(),
            sidecar: PathBuf::from("s.json"),
        }
    );
    assert_eq!(
        parse_args(args(&["--migrate-only", "--lancedb-path", "dev"])).unwrap(),
        Command::MigrateOnly {
            lancedb_path: "dev".into(),
        }
    );
    // --apply parses without --snapshot-dir; the run refuses it (see the snapshot tests).
    assert!(matches!(
        parse_args(args(&[
            "--lancedb-path",
            "store",
            "--sidecar",
            "s.json",
            "--apply"
        ]))
        .unwrap(),
        Command::Apply {
            snapshot_dir: None,
            ..
        }
    ));
}

#[test]
fn bad_flag_combinations_are_refused_with_the_usage_text() {
    let cases: [&[&str]; 9] = [
        &["--bogus"],
        &["--lancedb-path"],
        &["--lancedb-path", "store"],
        &["--sidecar", "s.json"],
        &[
            "--lancedb-path",
            "store",
            "--sidecar",
            "s.json",
            "--snapshot-dir",
            "snap",
        ],
        &["--apply", "--migrate-only", "--lancedb-path", "store"],
        &[
            "--verify-on-copy",
            "copy",
            "--lancedb-path",
            "store",
            "--sidecar",
            "s.json",
        ],
        &["--verify-on-copy", "copy"],
        &[
            "--migrate-only",
            "--lancedb-path",
            "store",
            "--sidecar",
            "s.json",
        ],
    ];
    for case in cases {
        let error = parse_args(args(case)).expect_err(&format!("{case:?}"));
        assert!(error.contains("usage:"), "{case:?}: {error}");
    }
    assert!(USAGE.contains("--verify-on-copy") && USAGE.contains("--migrate-only"));
}

// ---- isolation ------------------------------------------------------------------------------

#[test]
fn apply_and_dry_run_accept_only_the_configured_eval_store() {
    let root = temp_path("eval-target");
    let (eval, dev, other) = (root.join("eval"), root.join("dev"), root.join("other"));
    for dir in [&eval, &dev, &other] {
        std::fs::create_dir_all(dir).unwrap();
    }
    let isolation = isolation(&eval, &dev);

    assert!(check_eval_target(&as_str(&eval), &isolation).is_ok());
    let refused = check_eval_target(&as_str(&other), &isolation).unwrap_err();
    assert!(
        refused.contains("does not resolve to the configured eval"),
        "{refused}"
    );
    assert!(check_eval_target(&as_str(&dev), &isolation).is_err());
    assert!(check_eval_target(&as_str(&root.join("missing")), &isolation).is_err());
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn a_copy_is_checked_by_path_never_by_name() {
    let root = temp_path("copy-target");
    let (eval, dev) = (root.join("lancedb-eval"), root.join("dev"));
    // A verified copy keeps the directory name `lancedb-eval` but lives elsewhere.
    let copy = root.join("store-verify").join("lancedb-eval");
    for dir in [&eval, &dev, &copy] {
        std::fs::create_dir_all(dir).unwrap();
    }
    let isolation = isolation(&eval, &dev);

    assert!(check_copy_target(&as_str(&copy), &isolation).is_ok());
    let eval_refusal = check_copy_target(&as_str(&eval), &isolation).unwrap_err();
    assert!(
        eval_refusal.contains("configured eval store"),
        "{eval_refusal}"
    );
    let dev_refusal = check_copy_target(&as_str(&dev), &isolation).unwrap_err();
    assert!(dev_refusal.contains("dev store"), "{dev_refusal}");
    assert!(check_copy_target(&as_str(&root.join("missing")), &isolation).is_err());
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn migrate_only_refuses_the_eval_store_and_accepts_any_other_store() {
    let root = temp_path("migrate-target");
    let (eval, dev, other) = (root.join("eval"), root.join("dev"), root.join("other"));
    for dir in [&eval, &dev, &other] {
        std::fs::create_dir_all(dir).unwrap();
    }
    let isolation = isolation(&eval, &dev);

    assert!(check_migrate_target(&as_str(&other), &isolation).is_ok());
    assert!(check_migrate_target(&as_str(&dev), &isolation).is_ok());
    let refused = check_migrate_target(&as_str(&eval), &isolation).unwrap_err();
    assert!(refused.contains("configured eval store"), "{refused}");
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn the_snapshot_must_hold_nodes_lance_outside_the_live_store() {
    let root = temp_path("snapshot");
    let live = root.join("live");
    let snapshot = root.join("snap");
    std::fs::create_dir_all(live.join("nodes.lance")).unwrap();
    std::fs::create_dir_all(&snapshot).unwrap();
    let live_path = as_str(&live);

    let missing = check_snapshot(None, &live_path).unwrap_err();
    assert!(
        missing.contains("--apply requires --snapshot-dir"),
        "{missing}"
    );
    let empty = check_snapshot(Some(&snapshot), &live_path).unwrap_err();
    assert!(empty.contains("no nodes.lance copy"), "{empty}");
    let inside = check_snapshot(Some(&live), &live_path).unwrap_err();
    assert!(inside.contains("inside the live store"), "{inside}");

    std::fs::create_dir_all(snapshot.join("nodes.lance")).unwrap();
    assert!(check_snapshot(Some(&snapshot), &live_path).is_ok());
    let _ = std::fs::remove_dir_all(root);
}

// ---- runs over temporary stores --------------------------------------------------------------

#[tokio::test]
async fn a_dry_run_reports_the_state_and_writes_nothing() {
    let root = temp_path("dry-run");
    let (store, dev) = (root.join("eval"), root.join("dev"));
    std::fs::create_dir_all(&dev).unwrap();
    legacy_store(&store, 12).await;
    let sidecar = write_sidecar(&root.join("side"), 0..11);
    let connection = connect(&as_str(&store)).await.unwrap();
    let before = all_versions(&connection).await.unwrap();

    let finished = run(
        Command::DryRun {
            lancedb_path: as_str(&store),
            sidecar,
        },
        &isolation(&store, &dev),
    )
    .await
    .unwrap();

    let report = json(&finished);
    assert!(finished.success);
    assert_eq!(report["mode"], "dry_run");
    assert_eq!(report["nodes_schema"], "legacy19");
    assert_eq!(report["sidecar_documents"], 11);
    assert_eq!(report["nodes_documents"], 12);
    assert_eq!(
        report["uncovered_document_ids"],
        serde_json::json!([fixture_doc(11)])
    );
    assert_eq!(
        report["sidecar_ids_absent_from_nodes"],
        serde_json::json!([])
    );
    assert_eq!(
        all_versions(&connection).await.unwrap(),
        before,
        "no table moved"
    );
    let schema = connection
        .open_table("nodes")
        .execute()
        .await
        .unwrap()
        .schema()
        .await
        .unwrap();
    assert_eq!(schema.fields(), legacy_nodes_schema_v19().fields());
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn apply_is_refused_without_a_snapshot_and_for_a_store_that_is_not_the_eval_store() {
    let root = temp_path("apply-refused");
    let (store, dev, other) = (root.join("eval"), root.join("dev"), root.join("other"));
    std::fs::create_dir_all(&dev).unwrap();
    legacy_store(&store, 6).await;
    legacy_store(&other, 6).await;
    let sidecar = write_sidecar(&root.join("side"), 0..6);
    let isolation = isolation(&store, &dev);

    let no_snapshot = run(
        Command::Apply {
            lancedb_path: as_str(&store),
            sidecar: sidecar.clone(),
            snapshot_dir: None,
        },
        &isolation,
    )
    .await
    .unwrap_err();
    assert!(
        no_snapshot.contains("--apply requires --snapshot-dir"),
        "{no_snapshot}"
    );

    let empty_snapshot = root.join("empty-snapshot");
    std::fs::create_dir_all(&empty_snapshot).unwrap();
    let no_nodes = run(
        Command::Apply {
            lancedb_path: as_str(&store),
            sidecar: sidecar.clone(),
            snapshot_dir: Some(empty_snapshot),
        },
        &isolation,
    )
    .await
    .unwrap_err();
    assert!(no_nodes.contains("no nodes.lance copy"), "{no_nodes}");

    let snapshot = root.join("snapshot");
    copy_dir(&other.join("nodes.lance"), &snapshot.join("nodes.lance"));
    let wrong_store = run(
        Command::Apply {
            lancedb_path: as_str(&other),
            sidecar,
            snapshot_dir: Some(snapshot),
        },
        &isolation,
    )
    .await
    .unwrap_err();
    assert!(
        wrong_store.contains("does not resolve to the configured eval"),
        "{wrong_store}"
    );

    for path in [&store, &other] {
        let connection = connect(&as_str(path)).await.unwrap();
        let nodes = connection.open_table("nodes").execute().await.unwrap();
        assert_eq!(
            nodes.schema().await.unwrap().fields(),
            legacy_nodes_schema_v19().fields()
        );
    }
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn apply_moves_only_the_nodes_version_and_reports_every_table() {
    let root = temp_path("apply");
    let (store, dev) = (root.join("eval"), root.join("dev"));
    std::fs::create_dir_all(&dev).unwrap();
    legacy_store(&store, 9).await;
    let snapshot = root.join("snapshot");
    copy_dir(&store.join("nodes.lance"), &snapshot.join("nodes.lance"));
    let sidecar = write_sidecar(&root.join("side"), 0..9);

    let finished = run(
        Command::Apply {
            lancedb_path: as_str(&store),
            sidecar,
            snapshot_dir: Some(snapshot),
        },
        &isolation(&store, &dev),
    )
    .await
    .unwrap();

    let report = json(&finished);
    assert!(finished.success);
    assert_eq!(report["mode"], "apply");
    let (before, after) = (&report["versions_before"], &report["versions_after"]);
    assert_eq!(
        before.as_object().unwrap().len(),
        7,
        "every table of the store is listed"
    );
    assert_eq!(after.as_object().unwrap().len(), 7);
    for (table, version) in before.as_object().unwrap() {
        let expected = version.as_u64().unwrap() + u64::from(table == "nodes");
        assert_eq!(after[table].as_u64().unwrap(), expected, "{table}");
    }
    assert_eq!(report["outcome"]["rows"], 9);
    let connection = connect(&as_str(&store)).await.unwrap();
    let nodes = connection.open_table("nodes").execute().await.unwrap();
    assert_eq!(
        nodes.schema().await.unwrap().fields(),
        nodes_schema().fields()
    );
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn verify_on_copy_prints_the_five_assertions_and_refuses_the_eval_and_dev_stores() {
    let root = temp_path("verify");
    let (eval, dev, copy) = (root.join("eval"), root.join("dev"), root.join("copy"));
    legacy_store(&eval, 3).await;
    legacy_store(&dev, 3).await;
    legacy_store(&copy, 10).await;
    let sidecar = write_sidecar(&root.join("side"), 0..10);
    let isolation = isolation(&eval, &dev);

    for refused in [&eval, &dev] {
        let error = run(
            Command::VerifyOnCopy {
                dir: as_str(refused),
                sidecar: sidecar.clone(),
            },
            &isolation,
        )
        .await
        .unwrap_err();
        assert!(error.contains("not a copy"), "{error}");
    }

    let finished = run(
        Command::VerifyOnCopy {
            dir: as_str(&copy),
            sidecar,
        },
        &isolation,
    )
    .await
    .unwrap();
    let report = json(&finished);
    assert!(finished.success, "{}", finished.json);
    for assertion in [
        "schema_strict_22_columns",
        "rows_unchanged_and_no_indices",
        "digests_versions_and_files",
        "scan_stable_and_sidecar_covered",
        "uncovered_null_and_second_run_refused",
    ] {
        assert_eq!(report["assertions"][assertion], true, "{assertion}");
    }
    assert_eq!(report["column_digests_equal"], 19);
    assert!(finished.json.contains("already exists"));
    // The eval and dev stores were only read for their path: still 19 columns.
    for store in [&eval, &dev] {
        let connection = connect(&as_str(store)).await.unwrap();
        let nodes = connection.open_table("nodes").execute().await.unwrap();
        assert_eq!(
            nodes.schema().await.unwrap().fields(),
            legacy_nodes_schema_v19().fields()
        );
    }
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn a_failing_assertion_finishes_unsuccessfully_with_the_full_report() {
    let root = temp_path("verify-fail");
    let (eval, dev, copy) = (root.join("eval"), root.join("dev"), root.join("copy"));
    std::fs::create_dir_all(&eval).unwrap();
    std::fs::create_dir_all(&dev).unwrap();
    legacy_store(&copy, 6).await;
    let sidecar = write_sidecar(&root.join("side"), 0..5);

    let finished = run(
        Command::VerifyOnCopy {
            dir: as_str(&copy),
            sidecar,
        },
        &isolation(&eval, &dev),
    )
    .await
    .unwrap();

    assert!(!finished.success, "an uncovered document fails assertion 4");
    let report = json(&finished);
    assert_eq!(
        report["assertions"]["scan_stable_and_sidecar_covered"],
        false
    );
    assert_eq!(
        report["uncovered_document_ids"],
        serde_json::json!([fixture_doc(5)])
    );
    let _ = std::fs::remove_dir_all(root);
}

#[tokio::test]
async fn migrate_only_adds_null_columns_elsewhere_and_refuses_the_eval_store() {
    let root = temp_path("migrate");
    let (eval, dev, other) = (root.join("eval"), root.join("dev"), root.join("other"));
    legacy_store(&eval, 4).await;
    std::fs::create_dir_all(&dev).unwrap();
    legacy_store(&other, 7).await;
    let isolation = isolation(&eval, &dev);

    let refused = run(
        Command::MigrateOnly {
            lancedb_path: as_str(&eval),
        },
        &isolation,
    )
    .await
    .unwrap_err();
    assert!(refused.contains("configured eval store"), "{refused}");

    let finished = run(
        Command::MigrateOnly {
            lancedb_path: as_str(&other),
        },
        &isolation,
    )
    .await
    .unwrap();
    let report = json(&finished);
    assert_eq!(report["mode"], "migrate_only");
    assert_eq!(report["outcome"]["rows"], 7);
    let connection = connect(&as_str(&other)).await.unwrap();
    let nodes = connection.open_table("nodes").execute().await.unwrap();
    assert_eq!(
        nodes.schema().await.unwrap().fields(),
        nodes_schema().fields()
    );
    let nulls = nodes
        .count_rows(Some(
            "doc_title IS NULL AND source IS NULL AND published_date IS NULL".to_owned(),
        ))
        .await
        .unwrap();
    assert_eq!(nulls, 7, "every row reads null in the three new columns");
    let eval_nodes = connect(&as_str(&eval))
        .await
        .unwrap()
        .open_table("nodes")
        .execute()
        .await
        .unwrap();
    assert_eq!(
        eval_nodes.schema().await.unwrap().fields(),
        legacy_nodes_schema_v19().fields(),
        "the refused eval store is untouched"
    );
    let _ = std::fs::remove_dir_all(root);
}

#[test]
fn the_bin_names_both_new_modes_and_calls_nothing_it_must_not() {
    let source = include_str!("bin/backfill_evidence_metadata.rs");
    assert!(source.contains("--verify-on-copy"));
    assert!(source.contains("--migrate-only"));
    for forbidden in [
        concat!("extract_and_persist", "_entities"),
        concat!(".opti", "mize("),
        concat!("cleanup_old", "_versions"),
        concat!("compact", "_files"),
        concat!("DatabaseManager::", "open_and_validate"),
        concat!("DatabaseManager::", "initialize"),
    ] {
        assert!(
            !source.contains(forbidden),
            "the bin must not call {forbidden}"
        );
    }
}
