use std::{
    fs,
    io::{BufRead, BufReader},
    path::Path,
    process::{Child, Command, Stdio},
    sync::mpsc,
    thread,
    time::Duration,
};

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
            let _ = child.kill();
            let _ = child.wait();
            Err(output)
        }
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            Err("timeout".into())
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
    let corrupt_lancedb = temp_dir.join("corrupt_file.txt");

    fs::create_dir_all(&config_dir).unwrap();
    fs::create_dir_all(&cwd_dir).unwrap();
    fs::write(&corrupt_lancedb, "corrupt data file").unwrap();

    let config_toml = format!(
        "[engine]\ngrpc_addr = \"127.0.0.1:0\"\nlancedb_path = \"{}\"\n",
        corrupt_lancedb.to_str().unwrap().replace('\\', "/")
    );
    fs::write(config_dir.join("config.toml"), config_toml).unwrap();

    let env_vars = [
        ("LANCET_CONFIG_DIR", config_dir.to_str().unwrap()),
        ("OPENROUTER_API_KEY", "test-key"),
    ];

    let result = spawn_engine_full(&cwd_dir, &env_vars, &[]);
    assert!(
        result.is_err(),
        "engine startup must fail when lancedb initialization fails"
    );
    let err_msg = result.err().unwrap();
    assert!(
        !err_msg.contains("Rust RAG Engine serving"),
        "engine must never serve if startup fails"
    );

    let _ = fs::remove_dir_all(temp_dir);
}
