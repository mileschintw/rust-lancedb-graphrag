use std::{
    fs,
    io::{BufRead, BufReader},
    net::{SocketAddr, TcpListener, TcpStream},
    path::Path,
    process::{Child, Command, Stdio},
    sync::{mpsc, Arc},
    thread,
    time::Duration,
};

use arrow_array::{
    new_null_array, types::Float32Type, FixedSizeListArray, Int32Array, Int64Array, RecordBatch,
    StringArray,
};
use engine::db::DatabaseManager;
use uuid::Uuid;

fn spawn_engine_full(
    cwd: &Path,
    env_vars: &[(&str, &str)],
    remove_vars: &[&str],
) -> Result<(Child, Vec<String>, String), String> {
    let mut command = Command::new(env!("CARGO_BIN_EXE_engine"));
    command.current_dir(cwd);
    for var in remove_vars {
        command.env_remove(var);
    }
    for (k, v) in env_vars {
        command.env(k, v);
    }
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());

    let mut child = command.spawn().expect("failed to spawn engine binary");
    let stdout = child.stdout.take().expect("stdout piped");
    let stderr = child.stderr.take().expect("stderr piped");

    let (tx, rx) = mpsc::channel();
    let tx_out = tx.clone();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut lines = Vec::new();
        for line in reader.lines().map_while(Result::ok) {
            lines.push(line.clone());
            if line.contains("Rust RAG Engine serving") {
                let _ = tx_out.send(Ok((lines, line)));
                return;
            }
        }
    });

    let tx_err = tx;
    thread::spawn(move || {
        let reader = BufReader::new(stderr);
        let mut lines = Vec::new();
        for line in reader.lines().map_while(Result::ok) {
            lines.push(line.clone());
            if line.contains("Rust RAG Engine serving") {
                let _ = tx_err.send(Ok((lines.clone(), line)));
                return;
            }
        }
        let _ = tx_err.send(Err(lines.join("\n")));
    });

    match rx.recv_timeout(Duration::from_secs(10)) {
        Ok(Ok((logs, line))) => Ok((child, logs, line)),
        Ok(Err(output)) => {
            let status = child
                .wait()
                .map_err(|error| format!("failed to wait for engine: {error}\n{output}"))?;
            let termination = if status.success() {
                "process exited successfully"
            } else {
                "process exited nonzero"
            };
            Err(format!(
                "{termination} ({status}) without readiness\n{output}"
            ))
        }
        Err(_) => {
            let _ = child.kill();
            let status = child
                .wait()
                .map_err(|error| format!("failed to wait after startup timeout: {error}"))?;
            Err(format!(
                "engine startup timeout after 10 seconds (status {status})"
            ))
        }
    }
}

fn spawn_engine(cwd: &Path, env_vars: &[(&str, &str)], remove_vars: &[&str]) -> (Child, String) {
    match spawn_engine_full(cwd, env_vars, remove_vars) {
        Ok((child, _logs, line)) => (child, line),
        Err(err) => panic!("engine exited without ready signal. Stderr:\n{err}"),
    }
}

fn cleanup_child(mut child: Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn unused_loopback_addr() -> SocketAddr {
    let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind an ephemeral test port");
    listener.local_addr().expect("read the ephemeral test port")
}

fn assert_not_listening(addr: SocketAddr) {
    let result = TcpStream::connect_timeout(&addr, Duration::from_millis(250));
    assert!(
        result.is_err(),
        "engine must not open a listening socket at {addr}"
    );
}

struct Bm25FailureFixture {
    document_id: String,
    chunk_id: String,
}

async fn seed_schema_valid_bm25_failure_fixture(
    lancedb_path: &Path,
) -> Result<Bm25FailureFixture, String> {
    let path = lancedb_path
        .to_str()
        .ok_or_else(|| "fixture path must be valid UTF-8".to_owned())?;
    let database = DatabaseManager::initialize(path).await?;
    let nodes = database.nodes_table().await?;
    let schema = nodes
        .schema()
        .await
        .map_err(|error| format!("read BM25 failure fixture schema: {error}"))?;
    let document_id = Uuid::new_v4().to_string();
    let chunk_id = format!("{document_id}:0");
    let nullable = |name: &str| -> Result<Arc<dyn arrow_array::Array>, String> {
        let field = schema
            .field_with_name(name)
            .map_err(|error| format!("fixture schema missing {name}: {error}"))?;
        Ok(new_null_array(field.data_type(), 1))
    };
    let embedding = FixedSizeListArray::from_iter_primitive::<Float32Type, _, _>(
        std::iter::once(Some((0..2048).map(|_| Some(0.0f32)))),
        2048,
    );
    let invalid_content = " \t\n";
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(StringArray::from(vec![document_id.as_str()])),
            Arc::new(StringArray::from(vec![chunk_id.as_str()])),
            Arc::new(Int32Array::from(vec![0])),
            Arc::new(Int32Array::from(vec![0])),
            Arc::new(Int32Array::from(vec![3])),
            Arc::new(StringArray::from(vec![invalid_content])),
            Arc::new(embedding),
            Arc::new(Int32Array::from(vec![1])),
            Arc::new(StringArray::from(vec!["o200k_base"])),
            Arc::new(StringArray::from(vec!["1"])),
            Arc::new(StringArray::from(vec![Some("BM25 failure fixture")])),
            Arc::new(StringArray::from(vec![Some("Readiness failure")])),
            nullable("page_start")?,
            nullable("page_end")?,
            Arc::new(StringArray::from(vec![Some("bm25-failure-fixture")])),
            Arc::new(StringArray::from(vec![Some("1")])),
            Arc::new(StringArray::from(vec![Some("test-embedding-model")])),
            Arc::new(Int64Array::from(vec![Some(1)])),
            Arc::new(StringArray::from(vec![Some("text/plain")])),
        ],
    )


    .map_err(|error| format!("build BM25 failure fixture row: {error}"))?;
    nodes
        .add(batch)
        .execute()
        .await
        .map_err(|error| format!("insert BM25 failure fixture row: {error}"))?;

    let predicate = format!("document_id = '{document_id}'");
    let inserted = nodes
        .count_rows(Some(predicate.clone()))
        .await
        .map_err(|error| format!("count inserted BM25 failure fixture row: {error}"))?;
    if inserted != 1 {
        return Err(format!(
            "expected one inserted BM25 failure fixture row, found {inserted}"
        ));
    }

    drop(nodes);
    drop(database);
    let reopened = DatabaseManager::open_and_validate(path).await?;
    let reopened_nodes = reopened.nodes_table().await?;
    let reopened_count = reopened_nodes
        .count_rows(Some(predicate))
        .await
        .map_err(|error| format!("count reopened BM25 failure fixture row: {error}"))?;
    if reopened_count != 1 {
        return Err(format!(
            "expected one reopened BM25 failure fixture row, found {reopened_count}"
        ));
    }
    Ok(Bm25FailureFixture {
        document_id,
        chunk_id,
    })
}

#[test]
fn engine_starts_from_config_less_cwd_with_lancet_config_dir() {
    let temp_dir = std::env::temp_dir().join(format!("lancet-cfg-test-1-{}", uuid::Uuid::new_v4()));
    let config_dir = temp_dir.join("isolated_config");
    let cwd_dir = temp_dir.join("empty_cwd");
    let lancedb_dir = temp_dir.join("lancedb");

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();

    let config_toml = format!(
        "[engine]\ngrpc_addr = \"127.0.0.1:0\"\nlancedb_path = \"{}\"\n",
        lancedb_dir.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.toml"), config_toml).unwrap();

    let env_vars = [
        ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
        ("OPENROUTER_API_KEY", "test-key"),
    ];

    let (child, line) = spawn_engine(&cwd_dir, &env_vars, &[]);
    assert!(line.contains("Rust RAG Engine serving"));
    cleanup_child(child);
    let _ = fs::remove_dir_all(temp_dir);
}

#[test]
fn engine_starts_with_repository_fallback_when_variable_absent() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let temp_dir = std::env::temp_dir().join(format!("lancet-cfg-test-2-{}", uuid::Uuid::new_v4()));
    let lancedb_dir = temp_dir.join("lancedb");

    let lancedb_path = lancedb_dir.to_str().unwrap().replace('\\', "/");
    let env_vars = [
        ("LANCET_ENGINE__GRPC_ADDR", "127.0.0.1:0"),
        ("LANCET_ENGINE__LANCEDB_PATH", lancedb_path.as_str()),
        ("OPENROUTER_API_KEY", "test-key"),
    ];
    let remove_vars = ["LANCET_CONFIG_DIR", "LANCET_ENV"];

    let (child, line) = spawn_engine(repo_root, &env_vars, &remove_vars);
    assert!(line.contains("Rust RAG Engine serving"));
    cleanup_child(child);
    let _ = fs::remove_dir_all(temp_dir);
}

#[test]
fn engine_honors_env_overlay_and_environment_override_precedence() {
    let temp_dir = std::env::temp_dir().join(format!("lancet-cfg-test-3-{}", uuid::Uuid::new_v4()));
    let config_dir = temp_dir.join("custom_config");
    let cwd_dir = temp_dir.join("empty_cwd");
    let lancedb_dir = temp_dir.join("lancedb");

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();

    let base_config = "[engine]\ngrpc_addr = \"127.0.0.1:1\"\nlancedb_path = \"invalid\"\n";
    fs::write(config_dir.join("config.toml"), base_config).unwrap();

    let overlay_config = format!(
        "[engine]\ngrpc_addr = \"127.0.0.1:0\"\nlancedb_path = \"{}\"\n",
        lancedb_dir.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.staging.toml"), overlay_config).unwrap();

    let override_lancedb = temp_dir.join("lancedb_override");
    let override_path = override_lancedb.to_str().unwrap().replace('\\', "/");

    let env_vars = [
        ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
        ("LANCET_ENV", "staging"),
        ("LANCET_ENGINE__LANCEDB_PATH", override_path.as_str()),
        ("OPENROUTER_API_KEY", "test-key"),
    ];

    let (child, line) = spawn_engine(&cwd_dir, &env_vars, &[]);
    assert!(line.contains("Rust RAG Engine serving"));
    cleanup_child(child);
    let _ = fs::remove_dir_all(temp_dir);
}

#[test]
fn initial_bm25_ready_before_serving() {
    let temp_dir = std::env::temp_dir().join(format!("lancet-cfg-test-4-{}", uuid::Uuid::new_v4()));
    let config_dir = temp_dir.join("isolated_config");
    let cwd_dir = temp_dir.join("empty_cwd");
    let lancedb_dir = temp_dir.join("lancedb");

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();

    let config_toml = format!(
        "[engine]\ngrpc_addr = \"127.0.0.1:0\"\nlancedb_path = \"{}\"\n",
        lancedb_dir.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.toml"), config_toml).unwrap();

    let env_vars = [
        ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
        ("OPENROUTER_API_KEY", "test-key"),
    ];

    let (child, logs, ready_line) = spawn_engine_full(&cwd_dir, &env_vars, &[]).unwrap();
    assert!(ready_line.contains("Rust RAG Engine serving"));

    let bm25_pos = logs.iter().position(|l| l.contains("BM25 snapshot built"));
    let serving_pos = logs
        .iter()
        .position(|l| l.contains("Rust RAG Engine serving"));

    assert!(
        bm25_pos.is_some(),
        "BM25 snapshot built log must be present"
    );
    assert!(
        serving_pos.is_some(),
        "Rust RAG Engine serving log must be present"
    );
    assert!(
        bm25_pos.unwrap() <= serving_pos.unwrap(),
        "BM25 snapshot build must precede Rust RAG Engine serving log"
    );

    cleanup_child(child);
    let _ = fs::remove_dir_all(temp_dir);
}

#[test]
fn initial_bm25_failure_blocks_readiness() {
    let temp_dir = std::env::temp_dir().join(format!("lancet-cfg-test-5-{}", uuid::Uuid::new_v4()));
    let config_dir = temp_dir.join("isolated_config");
    let cwd_dir = temp_dir.join("empty_cwd");
    let lancedb_dir = temp_dir.join("lancedb");
    let grpc_addr = unused_loopback_addr();

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();
    let fixture = tokio::runtime::Runtime::new()
        .expect("create fixture runtime")
        .block_on(seed_schema_valid_bm25_failure_fixture(&lancedb_dir))
        .expect("seed and reopen schema-valid BM25 failure fixture");

    let config_toml = format!(
        "[engine]\ngrpc_addr = \"{grpc_addr}\"\nlancedb_path = \"{}\"\n",
        lancedb_dir.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.toml"), config_toml).unwrap();

    let env_vars = [
        ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
        ("OPENROUTER_API_KEY", "test-key"),
    ];

    let result = spawn_engine_full(&cwd_dir, &env_vars, &[]);
    let err_msg = match result {
        Ok((child, _, _)) => {
            cleanup_child(child);
            panic!("engine must fail while building the initial BM25 snapshot")
        }
        Err(error) => error,
    };
    assert!(
        err_msg.contains("process exited nonzero"),
        "engine must terminate nonzero: {err_msg}"
    );
    assert!(
        err_msg.contains("BM25 snapshot"),
        "diagnostic must identify BM25 construction: {err_msg}"
    );
    assert!(
        err_msg.contains("content"),
        "diagnostic must identify invalid content: {err_msg}"
    );
    assert!(
        err_msg.contains(&fixture.document_id) && err_msg.contains(&fixture.chunk_id),
        "diagnostic must identify the unique completed row: {err_msg}"
    );
    assert!(
        !err_msg.contains("Rust RAG Engine serving"),
        "engine must never serve if startup fails"
    );
    assert_not_listening(grpc_addr);

    let _ = fs::remove_dir_all(temp_dir);
}

#[test]
fn invalid_rag_settings_block_readiness() {
    let temp_dir =
        std::env::temp_dir().join(format!("lancet-cfg-test-invalid-{}", uuid::Uuid::new_v4()));
    let config_dir = temp_dir.join("isolated_config");
    let cwd_dir = temp_dir.join("empty_cwd");
    let lancedb_dir = temp_dir.join("lancedb");
    let grpc_addr = unused_loopback_addr();

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();
    let config_toml = format!(
        "[engine]\ngrpc_addr = \"{grpc_addr}\"\nlancedb_path = \"{}\"\n\n[engine.retrieval]\nevidence_token_budget = 0\n",
        lancedb_dir.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.toml"), config_toml).unwrap();

    let env_vars = [
        ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
        ("OPENROUTER_API_KEY", "test-key"),
    ];

    let result = spawn_engine_full(&cwd_dir, &env_vars, &[]);
    let err_msg = match result {
        Ok((child, _, _)) => {
            cleanup_child(child);
            panic!("engine must reject invalid RAG settings before readiness")
        }
        Err(error) => error,
    };
    assert!(
        err_msg.contains("process exited nonzero"),
        "engine must terminate nonzero: {err_msg}"
    );
    assert!(
        err_msg.contains("evidence_token_budget"),
        "diagnostic must name the invalid setting: {err_msg}"
    );
    assert!(
        !err_msg.contains("Rust RAG Engine serving"),
        "engine must never serve with invalid settings"
    );
    assert_not_listening(grpc_addr);

    let _ = fs::remove_dir_all(temp_dir);
}

#[test]
fn missing_openrouter_api_key_blocks_readiness() {
    let temp_dir =
        std::env::temp_dir().join(format!("lancet-cfg-test-no-key-{}", uuid::Uuid::new_v4()));
    let config_dir = temp_dir.join("isolated_config");
    let cwd_dir = temp_dir.join("empty_cwd");
    let lancedb_dir = temp_dir.join("lancedb");
    let grpc_addr = unused_loopback_addr();

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();
    let config_toml = format!(
        "[engine]\ngrpc_addr = \"{grpc_addr}\"\nlancedb_path = \"{}\"\n",
        lancedb_dir.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.toml"), config_toml).unwrap();

    let env_vars = [("LANCET_CONFIG_DIR", config_dir.to_str().unwrap())];
    let remove_vars = ["OPENROUTER_API_KEY"];

    let result = spawn_engine_full(&cwd_dir, &env_vars, &remove_vars);
    let err_msg = match result {
        Ok((child, _, _)) => {
            cleanup_child(child);
            panic!("engine must reject missing OPENROUTER_API_KEY before readiness")
        }
        Err(error) => error,
    };
    assert!(
        err_msg.contains("process exited nonzero"),
        "engine must terminate nonzero: {err_msg}"
    );
    assert!(
        err_msg.contains("OPENROUTER_API_KEY"),
        "diagnostic must name missing OPENROUTER_API_KEY: {err_msg}"
    );
    assert!(
        !err_msg.contains("Rust RAG Engine serving"),
        "engine must never serve without OPENROUTER_API_KEY"
    );
    assert_not_listening(grpc_addr);

    let _ = fs::remove_dir_all(temp_dir);
}

#[test]
fn blank_openrouter_api_key_blocks_readiness() {
    let temp_dir = std::env::temp_dir().join(format!(
        "lancet-cfg-test-blank-key-{}",
        uuid::Uuid::new_v4()
    ));
    let config_dir = temp_dir.join("isolated_config");
    let cwd_dir = temp_dir.join("empty_cwd");
    let lancedb_dir = temp_dir.join("lancedb");
    let grpc_addr = unused_loopback_addr();

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();
    let config_toml = format!(
        "[engine]\ngrpc_addr = \"{grpc_addr}\"\nlancedb_path = \"{}\"\n",
        lancedb_dir.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.toml"), config_toml).unwrap();

    for blank_val in ["", "   \t\n  "] {
        let env_vars = [
            ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
            ("OPENROUTER_API_KEY", blank_val),
        ];

        let result = spawn_engine_full(&cwd_dir, &env_vars, &[]);
        let err_msg = match result {
            Ok((child, _, _)) => {
                cleanup_child(child);
                panic!("engine must reject blank OPENROUTER_API_KEY before readiness")
            }
            Err(error) => error,
        };
        assert!(
            err_msg.contains("process exited nonzero"),
            "engine must terminate nonzero: {err_msg}"
        );
        assert!(
            err_msg.contains("OPENROUTER_API_KEY"),
            "diagnostic must name blank OPENROUTER_API_KEY: {err_msg}"
        );
        assert!(
            !err_msg.contains("Rust RAG Engine serving"),
            "engine must never serve with blank OPENROUTER_API_KEY"
        );
        assert_not_listening(grpc_addr);
    }

    let _ = fs::remove_dir_all(temp_dir);
}

#[test]
fn service_ceiling_rejects_above_effective_limits() {
    // 1. Direct boundary assertions for exact ceiling values (inclusive contract)
    let valid_at_ceilings = engine::generation::GroundingLimits::new(16384, 4096)
        .expect("exact ceilings 16,384 evidence and 4,096 output must be accepted");
    assert_eq!(valid_at_ceilings.evidence_token_budget(), 16384);
    assert_eq!(valid_at_ceilings.max_output_tokens(), 4096);
    assert_eq!(valid_at_ceilings.total_tokens_ceiling(), 20480);

    assert!(
        engine::generation::GroundingLimits::new(16385, 4096).is_err(),
        "evidence_token_budget 16,385 must be rejected above ceiling"
    );
    assert!(
        engine::generation::GroundingLimits::new(16384, 4097).is_err(),
        "max_output_tokens 4,097 must be rejected above ceiling"
    );

    // 2. Process-level integration tests
    let temp_dir =
        std::env::temp_dir().join(format!("lancet-cfg-test-ceiling-{}", uuid::Uuid::new_v4()));
    let config_dir = temp_dir.join("isolated_config");
    let cwd_dir = temp_dir.join("empty_cwd");
    let lancedb_dir = temp_dir.join("lancedb");
    let grpc_addr = unused_loopback_addr();

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();
    let config_toml = format!(
        "[engine]\ngrpc_addr = \"{grpc_addr}\"\nlancedb_path = \"{}\"\n",
        lancedb_dir.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.toml"), config_toml).unwrap();

    // Rejection 1: evidence_token_budget above ceiling (16,385)
    let env_vars_ev = [
        ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
        ("OPENROUTER_API_KEY", "test-key"),
        ("LANCET_ENGINE__RETRIEVAL__EVIDENCE_TOKEN_BUDGET", "16385"),
    ];
    let result_ev = spawn_engine_full(&cwd_dir, &env_vars_ev, &[]);
    let err_ev = match result_ev {
        Ok((child, _, _)) => {
            cleanup_child(child);
            panic!("engine must reject evidence_token_budget 16,385 before readiness");
        }
        Err(err) => err,
    };
    assert!(
        err_ev.contains("process exited nonzero"),
        "must exit nonzero: {err_ev}"
    );
    assert!(
        err_ev.contains("exceeds service ceiling"),
        "must state ceiling error: {err_ev}"
    );
    assert_not_listening(grpc_addr);

    // Rejection 2: max_output_tokens above ceiling (4,097)
    let env_vars_out = [
        ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
        ("OPENROUTER_API_KEY", "test-key"),
        ("LANCET_OPENROUTER__MAX_OUTPUT_TOKENS", "4097"),
    ];
    let result_out = spawn_engine_full(&cwd_dir, &env_vars_out, &[]);
    let err_out = match result_out {
        Ok((child, _, _)) => {
            cleanup_child(child);
            panic!("engine must reject max_output_tokens 4,097 before readiness");
        }
        Err(err) => err,
    };
    assert!(
        err_out.contains("process exited nonzero"),
        "must exit nonzero: {err_out}"
    );
    assert!(
        err_out.contains("exceeds service ceiling"),
        "must state ceiling error: {err_out}"
    );
    assert_not_listening(grpc_addr);

    let _ = fs::remove_dir_all(temp_dir);
}
