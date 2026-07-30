#!/usr/bin/env python3
"""Tests for the Phase 02 live-evidence validation helper."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
HELPER = Path(__file__).with_name("phase02_live_evidence.py")
EXPECTED_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
CHALLENGE_RUNTIME_PATH = ".planning/phases/02-ingestion-chunking-vector-storage/.02-LIVE-CHALLENGE.json"
EVIDENCE_RUNTIME_PATH = ".planning/phases/02-ingestion-chunking-vector-storage/02-LIVE-EVIDENCE.json"

if str(HELPER.parent) not in sys.path:
    sys.path.insert(0, str(HELPER.parent))

from phase02_live_evidence import classify_sensitive_field

REAL_CANONICAL_PATHS = (
    (ROOT / CHALLENGE_RUNTIME_PATH).resolve(),
    (ROOT / EVIDENCE_RUNTIME_PATH).resolve(),
)


def assert_not_real_runtime_path(path: Path | str) -> None:
    target = Path(path).resolve()
    if target in REAL_CANONICAL_PATHS:
        raise RuntimeError(f"Prohibited mutation of real runtime path: {path}")


def timestamp(offset_seconds: int = 0) -> str:
    value = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_seconds)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_bash_path(path: Path | str, base: Path | None = None) -> str:
    target = Path(path).resolve()
    if base is not None:
        try:
            return os.path.relpath(target, base.resolve()).replace("\\", "/")
        except ValueError:
            pass
    posix = target.as_posix()
    if len(posix) >= 2 and posix[1] == ":":
        drive = posix[0].lower()
        if Path("/mnt").exists():
            return f"/mnt/{drive}{posix[2:]}"
        return f"/{drive}{posix[2:]}"
    return posix


def fixture_pair(
    embedding_model: str = EXPECTED_MODEL,
) -> tuple[dict[str, object], dict[str, object]]:
    issued_at = timestamp(-5)
    run_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    challenge = {
        "schema_version": 1,
        "challenge": "sanitized-challenge-value-0123456789abcdef",
        "run_id": run_id,
        "issued_at": issued_at,
    }
    evidence = {
        "schema_version": 1,
        "success_sentinel": "Ingestion validation: SUCCESS",
        "challenge": challenge["challenge"],
        "run_id": run_id,
        "issued_at": issued_at,
        "run_started_at": timestamp(-4),
        "generated_at": timestamp(-1),
        "document_id": document_id,
        "provider": "openrouter",
        "embedding_model": embedding_model,
        "gateway_chunk_count": 1,
        "postgres_status": "completed",
        "postgres_chunk_count": 1,
        "document_rows": 1,
        "staged_document_rows": 0,
        "node_rows": 1,
        "edge_rows": 0,
        "embedding_width": 2048,
        "generation_count": 1,
        "duplicate_generation": False,
        "stale_generation": False,
        "chunk_indexes_contiguous": True,
    }
    return challenge, evidence


def inspection_fixture(evidence: dict[str, object]) -> dict[str, object]:
    return {
        "document_id": evidence["document_id"],
        "provider": "openrouter",
        "embedding_model": EXPECTED_MODEL,
        "document_rows": 1,
        "staged_document_rows": 0,
        "node_rows": 1,
        "edge_rows": 0,
        "embedding_width": 2048,
        "generation_count": 1,
        "duplicate_generation": False,
        "stale_generation": False,
        "chunk_indexes_contiguous": True,
    }


def write_json_fixtures(
    challenge: dict[str, object],
    evidence: dict[str, object],
    test_case: unittest.TestCase | None = None,
) -> tuple[Path, Path, list[Path]]:
    temporary_paths: list[Path] = []
    challenge_fd, challenge_name = tempfile.mkstemp(
        dir=Path(__file__).parent,
        prefix=".phase02-live-test-",
        suffix="-challenge.json",
    )
    evidence_fd, evidence_name = tempfile.mkstemp(
        dir=Path(__file__).parent,
        prefix=".phase02-live-test-",
        suffix="-evidence.json",
    )
    os.close(challenge_fd)
    os.close(evidence_fd)
    challenge_path = Path(challenge_name)
    evidence_path = Path(evidence_name)
    assert_not_real_runtime_path(challenge_path)
    assert_not_real_runtime_path(evidence_path)
    temporary_paths.extend((challenge_path, evidence_path))
    if test_case is not None:
        test_case.addCleanup(lambda: challenge_path.unlink(missing_ok=True))
        test_case.addCleanup(lambda: evidence_path.unlink(missing_ok=True))
    challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return challenge_path, evidence_path, temporary_paths


def run_helper(*arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONOPTIMIZE"] = "1"
    return subprocess.run(
        [sys.executable, "-O", "-I", str(HELPER), *arguments],
        cwd=ROOT,
        env=environment,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class Phase02LiveEvidenceTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        for p in Path(__file__).parent.glob(".phase02-live-test-*"):
            p.unlink(missing_ok=True)

    def test_wrong_model_is_rejected_in_optimized_isolated_subprocess(self) -> None:
        self.assertEqual(sys.flags.optimize, 1, "the optimized test gate must run with -O")
        challenge, evidence = fixture_pair(embedding_model="not-the-locked-model")
        challenge_fd, challenge_name = tempfile.mkstemp(
            dir=Path(__file__).parent,
            prefix=".phase02-live-test-",
            suffix="-challenge.json",
        )
        evidence_fd, evidence_name = tempfile.mkstemp(
            dir=Path(__file__).parent,
            prefix=".phase02-live-test-",
            suffix="-evidence.json",
        )
        os.close(challenge_fd)
        os.close(evidence_fd)
        challenge_path = Path(challenge_name)
        evidence_path = Path(evidence_name)
        self.addCleanup(lambda: challenge_path.unlink(missing_ok=True))
        self.addCleanup(lambda: evidence_path.unlink(missing_ok=True))
        challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

        environment = os.environ.copy()
        environment["PYTHONOPTIMIZE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-O",
                "-I",
                str(HELPER),
                "validate-gate",
                "--challenge",
                str(challenge_path),
                "--evidence",
                str(evidence_path),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)

    def test_all_structured_failures_are_rejected_under_optimized_isolated_python(self) -> None:
        challenge, evidence = fixture_pair()
        cases: list[tuple[str, dict[str, object], dict[str, object]]] = []

        missing_field = dict(evidence)
        missing_field.pop("node_rows")
        cases.append(("missing field", challenge, missing_field))

        extra_field = dict(evidence)
        extra_field["unexpected"] = "sanitized"
        cases.append(("extra field", challenge, extra_field))

        bad_uuid = dict(challenge)
        bad_uuid["run_id"] = "not-a-uuid"
        cases.append(("bad UUID", bad_uuid, evidence))

        bad_timestamp = dict(challenge)
        bad_timestamp["issued_at"] = "not-a-timestamp"
        cases.append(("bad timestamp", bad_timestamp, evidence))

        replayed = dict(evidence)
        replayed["challenge"] = "replayed-challenge-value-0123456789abcdef"
        cases.append(("challenge replay", challenge, replayed))

        stale = dict(evidence)
        stale["generated_at"] = timestamp(-31 * 60)
        cases.append(("stale evidence", challenge, stale))

        future = dict(evidence)
        future["generated_at"] = timestamp(6 * 60)
        cases.append(("future evidence", challenge, future))

        wrong_provider = dict(evidence)
        wrong_provider["provider"] = "other-provider"
        cases.append(("wrong provider", challenge, wrong_provider))

        wrong_model = dict(evidence)
        wrong_model["embedding_model"] = "other-model"
        cases.append(("wrong model", challenge, wrong_model))

        wrong_width = dict(evidence)
        wrong_width["embedding_width"] = 1024
        cases.append(("wrong width", challenge, wrong_width))

        wrong_count = dict(evidence)
        wrong_count["gateway_chunk_count"] = 2
        cases.append(("wrong count", challenge, wrong_count))

        duplicate_generation = dict(evidence)
        duplicate_generation["duplicate_generation"] = True
        cases.append(("duplicate generation", challenge, duplicate_generation))

        stale_generation = dict(evidence)
        stale_generation["stale_generation"] = True
        cases.append(("stale generation", challenge, stale_generation))

        broken_continuity = dict(evidence)
        broken_continuity["chunk_indexes_contiguous"] = False
        cases.append(("broken continuity", challenge, broken_continuity))

        secret_field = dict(evidence)
        secret_field["api_key"] = "sanitized-secret-value"
        cases.append(("secret field", challenge, secret_field))

        content_field = dict(evidence)
        content_field["stored_document_text"] = "sanitized-content-value"
        cases.append(("content field", challenge, content_field))

        stale_challenge = dict(challenge)
        stale_challenge["issued_at"] = timestamp(-31 * 60)
        cases.append(("stale challenge", stale_challenge, evidence))

        overlong_run = dict(evidence)
        overlong_run["issued_at"] = timestamp(-36 * 60)
        cases.append(("overlong run", challenge, overlong_run))

        for name, case_challenge, case_evidence in cases:
            with self.subTest(name=name):
                challenge_path, evidence_path, temporary_paths = write_json_fixtures(
                    case_challenge, case_evidence
                )
                try:
                    completed = run_helper(
                        "validate-gate",
                        "--challenge",
                        str(challenge_path),
                        "--evidence",
                        str(evidence_path),
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    if name in {"secret field", "content field"}:
                        self.assertNotIn(
                            "sanitized-secret-value", completed.stdout + completed.stderr
                        )
                        self.assertNotIn(
                            "sanitized-content-value", completed.stdout + completed.stderr
                        )
                    self.assertTrue(challenge_path.exists())
                    self.assertTrue(evidence_path.exists())
                finally:
                    for path in temporary_paths:
                        path.unlink(missing_ok=True)

    def test_current_store_drift_is_rejected_and_facts_are_copied_from_inspection(self) -> None:
        challenge, evidence = fixture_pair()
        inspection = inspection_fixture(evidence)
        drifted_inspection = dict(inspection)
        drifted_inspection["node_rows"] = 2
        challenge_path, evidence_path, temporary_paths = write_json_fixtures(challenge, evidence)
        try:
            drifted = run_helper(
                "compare-live-state",
                "--challenge",
                str(challenge_path),
                "--evidence",
                str(evidence_path),
                "--postgres",
                "completed:1",
                "--inspection-json",
                "-",
                input_text=json.dumps(drifted_inspection),
            )
            self.assertNotEqual(drifted.returncode, 0)

            built = run_helper(
                "build-evidence",
                "--challenge",
                str(challenge_path),
                "--inspection-json",
                "-",
                "--document-id",
                str(evidence["document_id"]),
                "--gateway-count",
                "1",
                "--postgres",
                "completed:1",
                "--run-started-at",
                str(evidence["run_started_at"]),
                input_text=json.dumps(inspection),
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            rebuilt = json.loads(built.stdout)
            for key in (
                "provider",
                "embedding_model",
                "generation_count",
                "duplicate_generation",
                "stale_generation",
                "chunk_indexes_contiguous",
            ):
                self.assertEqual(rebuilt[key], inspection[key])
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)

    def test_exact_runtime_paths_are_ignored(self) -> None:
        for path in (CHALLENGE_RUNTIME_PATH, EVIDENCE_RUNTIME_PATH):
            with self.subTest(path=path):
                completed = subprocess.run(
                    ["git", "check-ignore", "-q", "--", path],
                    cwd=ROOT,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0)

    def test_shell_gate_uses_isolated_helper_and_no_inline_acceptance_assertions(self) -> None:
        ingestion = (ROOT / "verify-ingestion.sh").read_text(encoding="utf-8")
        final = (ROOT / "verify-live-evidence.sh").read_text(encoding="utf-8")
        for script in (ingestion, final):
            self.assertNotRegex(script, r"(^|[^A-Za-z])assert\b")
            self.assertIn("phase02_live_evidence.py", script)
            self.assertIn("-I", script)
        for field in (
            "duplicate_generation",
            "stale_generation",
            "chunk_indexes_contiguous",
            "generation_count",
        ):
            self.assertIn(field, ingestion + (ROOT / "scripts/phase02_live_evidence.py").read_text(encoding="utf-8"))
        self.assertNotIn("'duplicate_generation': False", ingestion)
        self.assertIn('rm -f -- "$challenge" "$evidence"', final)
        self.assertLess(final.index("compare-live-state"), final.index('rm -f -- "$challenge" "$evidence"'))

    def test_privacy_clean_nested_metadata_passes(self) -> None:
        clean_payload = {
            "meta": {
                "source": "test",
                "items": [{"id": 1, "name": "clean_item"}],
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump(clean_payload, tmp)
            tmp_path = Path(tmp.name)
        try:
            completed = run_helper("check-privacy", "--file", str(tmp_path))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("PASS", completed.stdout)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_privacy_per_category_forbidden_fields_fail(self) -> None:
        categories = [
            ("credential", {"meta": {"user_credential": "secret_val_123"}}),
            ("secret", {"api_key": "secret_val_123"}),
            ("bearer", {"nested": [{"bearer_token": "secret_val_123"}]}),
            ("authorization_header", {"meta": {"authorization_header": "secret_val_123"}}),
            ("raw_content", {"data": {"raw_content": "secret_val_123"}}),
            ("document_text", {"doc": {"stored_document_text": "secret_val_123"}}),
            ("chunk_content", {"chunk": {"stored_chunk_content": "secret_val_123"}}),
        ]
        for category, payload in categories:
            with self.subTest(category=category):
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(payload, tmp)
                    tmp_path = Path(tmp.name)
                try:
                    completed = run_helper("check-privacy", "--file", str(tmp_path))
                    self.assertNotEqual(completed.returncode, 0)
                    output = completed.stdout + completed.stderr
                    self.assertIn(category, output.lower())
                    self.assertNotIn("secret_val_123", output)
                finally:
                    tmp_path.unlink(missing_ok=True)

    def test_privacy_mixed_case_separators_and_recursive_placement(self) -> None:
        cases = [
            {"Nested": [{"cReDeNtIaL": "secret_val_123"}]},
            {"RAW-CONTENT": "secret_val_123"},
            {"stored.document.text": "secret_val_123"},
            {"meta": {"sub": [{"authorization_header": "secret_val_123"}]}},
        ]
        for idx, payload in enumerate(cases):
            with self.subTest(idx=idx):
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(payload, tmp)
                    tmp_path = Path(tmp.name)
                try:
                    completed = run_helper("check-privacy", "--file", str(tmp_path))
                    self.assertNotEqual(completed.returncode, 0)
                    output = completed.stdout + completed.stderr
                    self.assertNotIn("secret_val_123", output)
                finally:
                    tmp_path.unlink(missing_ok=True)

    def test_privacy_camel_case_aliases_classify(self) -> None:
        self.assertEqual(classify_sensitive_field("rawContent"), "raw_content")
        self.assertEqual(classify_sensitive_field("storedDocumentText"), "document_text")
        self.assertEqual(classify_sensitive_field("authorizationHeader"), "authorization_header")
        self.assertEqual(classify_sensitive_field("bearerToken"), "bearer")
        self.assertEqual(classify_sensitive_field("chunkContent"), "chunk_content")
        self.assertEqual(classify_sensitive_field("credentialValue"), "credential")

    def test_privacy_camel_case_aliases_fail_first_and_omit_values(self) -> None:
        aliases = [
            ("rawContent", "raw_content", {"data": {"rawContent": "do-not-publish-raw-content"}}),
            ("storedDocumentText", "document_text", {"doc": {"storedDocumentText": "do-not-publish-doc-text"}}),
            ("authorizationHeader", "authorization_header", {"meta": {"authorizationHeader": "do-not-publish-auth-header"}}),
            ("bearerToken", "bearer", {"nested": [{"bearerToken": "do-not-publish-bearer-token"}]}),
            ("chunkContent", "chunk_content", {"chunk": {"chunkContent": "do-not-publish-chunk-content"}}),
            ("credentialValue", "credential", {"meta": {"credentialValue": "do-not-publish-credential"}}),
        ]
        for alias, category, payload in aliases:
            with self.subTest(alias=alias):
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tmp:
                    json.dump(payload, tmp)
                    tmp_path = Path(tmp.name)
                try:
                    completed = run_helper("check-privacy", "--file", str(tmp_path))
                    self.assertNotEqual(completed.returncode, 0)
                    output = completed.stdout + completed.stderr
                    self.assertIn(category, output.lower())
                    self.assertNotIn("do-not-publish", output)
                finally:
                    tmp_path.unlink(missing_ok=True)

    def test_raw_content_cli_probe_fails_first_without_value_disclosure(self) -> None:
        completed = run_helper("check-privacy", "--file", "-", input_text='{"rawContent":"do-not-publish"}')
        self.assertNotEqual(completed.returncode, 0)
        output = completed.stdout + completed.stderr
        self.assertIn("raw_content", output.lower())
        self.assertNotIn("do-not-publish", output)

    def test_privacy_node_is_absent_from_verification(self) -> None:
        node_test = ROOT / "scripts/test_phase02_privacy_prohibition.cjs"
        self.assertFalse(node_test.exists(), "Node privacy test script must be removed")
        final_script = (ROOT / "verify-live-evidence.sh").read_text(encoding="utf-8")
        self.assertNotIn("node", final_script)
        self.assertNotIn("test_phase02_privacy_prohibition", final_script)

    def test_resolve_store_path_strict_validation(self) -> None:
        # Valid config resolves from repository root even from unrelated CWD
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as unrelated_cwd:
            env = os.environ.copy()
            env["PYTHONOPTIMIZE"] = "1"
            completed = subprocess.run(
                [sys.executable, "-O", "-I", str(HELPER), "resolve-store-path"],
                cwd=unrelated_cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            expected_abs = (ROOT / "data" / "lancedb-verify-02-06").resolve()
            self.assertEqual(Path(completed.stdout.strip()).resolve(), expected_abs)

        # Invalid config options fail
        invalid_configs = [
            ("invalid TOML", "this is not [valid toml"),
            ("missing engine table", "[other]\nkey = 'val'"),
            ("missing lancedb_path", "[engine]\nother_key = 'val'"),
            ("empty lancedb_path", "[engine]\nlancedb_path = ''"),
            ("non-string lancedb_path", "[engine]\nlancedb_path = 123"),
        ]
        for name, content in invalid_configs:
            with self.subTest(config_case=name):
                with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as tmp:
                    tmp.write(content)
                    tmp_path = Path(tmp.name)
                try:
                    completed = run_helper("resolve-store-path", "--config", str(tmp_path))
                    self.assertNotEqual(completed.returncode, 0)
                finally:
                    tmp_path.unlink(missing_ok=True)

    def test_captured_inspector_arguments_explicit_path(self) -> None:
        doc_id = str(uuid.uuid4())
        challenge, evidence = fixture_pair()
        evidence["document_id"] = doc_id
        challenge["challenge"] = "injected-sentinel-temp-challenge-0123456789abcdef"
        evidence["challenge"] = challenge["challenge"]

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent, prefix=".phase02-live-test-") as fixture_dir:
            fixture_path = Path(fixture_dir)
            challenge_path = fixture_path / "injected-challenge.json"
            evidence_path = fixture_path / "injected-evidence.json"
            assert_not_real_runtime_path(challenge_path)
            assert_not_real_runtime_path(evidence_path)
            challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            with tempfile.TemporaryDirectory(dir=ROOT, ignore_cleanup_errors=True) as fake_bin_dir:
                capture_file = Path(fake_bin_dir) / "cargo_capture.txt"
                fake_cargo = Path(fake_bin_dir) / "cargo"
                dummy_inspection = inspection_fixture(evidence)
                dummy_inspection["document_id"] = doc_id
                
                script_content = f"""#!/usr/bin/env bash
echo "$@" >> "$(dirname "$0")/cargo_capture.txt"
if [[ "$*" == *"inspect_lancedb"* ]]; then
  cat << 'EOF'
{json.dumps(dummy_inspection)}
EOF
fi
exit 0
"""
                script_bytes = script_content.replace("\r\n", "\n").encode("utf-8")
                fake_cargo.write_bytes(script_bytes)
                fake_cargo.chmod(0o755)

                fake_cargo_cmd = Path(fake_bin_dir) / "cargo.cmd"
                cargo_cmd_content = f"""@echo off
echo %* >> "%~dp0cargo_capture.txt"
echo {json.dumps(dummy_inspection)}
exit /b 0
"""
                fake_cargo_cmd.write_text(cargo_cmd_content, encoding="utf-8")

                fake_docker = Path(fake_bin_dir) / "fake_docker"
                docker_script = """#!/usr/bin/env bash
echo "completed:1"
exit 0
"""
                docker_bytes = docker_script.replace("\r\n", "\n").encode("utf-8")
                fake_docker.write_bytes(docker_bytes)
                fake_docker.chmod(0o755)

                fake_docker_cmd = Path(fake_bin_dir) / "fake_docker.cmd"
                docker_cmd_content = """@echo off
echo completed:1
exit /b 0
"""
                fake_docker_cmd.write_text(docker_cmd_content, encoding="utf-8")

                env = os.environ.copy()
                env["PATH"] = str(Path(fake_bin_dir).resolve()) + os.pathsep + env.get("PATH", "")
                env["DOCKER_CMD"] = "fake_docker"
                env["PYTHONOPTIMIZE"] = "1"
                env["LANCET_ENV"] = "verify"

                with tempfile.TemporaryDirectory(dir=ROOT, ignore_cleanup_errors=True) as unrelated_cwd:
                    unrelated_path = Path(unrelated_cwd)
                    rel_script = to_bash_path(ROOT / "verify-live-evidence.sh", base=unrelated_path)
                    bash_challenge = to_bash_path(challenge_path, base=ROOT)
                    bash_evidence = to_bash_path(evidence_path, base=ROOT)
                    completed = subprocess.run(
                        [
                            "bash",
                            "-c",
                            f'DOCKER_CMD=fake_docker bash "{rel_script}" --validate-gate --challenge "{bash_challenge}" --evidence "{bash_evidence}"',
                        ],
                        cwd=unrelated_cwd,
                        env=env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=False,
                    )
                    out = (completed.stderr or "") + (completed.stdout or "")
                    self.assertEqual(completed.returncode, 0, out)
                    self.assertTrue(capture_file.exists(), "fake cargo should have been invoked")
                    captured_text = capture_file.read_text(encoding="utf-8")
                    self.assertIn("inspect_lancedb", captured_text)
                    self.assertIn(doc_id, captured_text)
                    expected_store = (ROOT / "data" / "lancedb-verify-02-06").resolve()
                    self.assertIn("--lancedb-path", captured_text)
                    self.assertTrue(
                        str(expected_store) in captured_text or to_bash_path(expected_store) in captured_text,
                        f"{expected_store} or {to_bash_path(expected_store)} not in captured text: {captured_text}",
                    )

    def test_caller_sample_preservation_on_early_failure(self) -> None:
        sample_path = ROOT / ".test-caller-sample.tmp"
        sample_path.write_bytes(b"caller sample data 12345")
        try:
            completed = subprocess.run(
                ["bash", "verify-ingestion.sh", str(sample_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertTrue(sample_path.exists(), "caller sample file must not be deleted on early failure")
            self.assertEqual(sample_path.read_bytes(), b"caller sample data 12345")
        finally:
            sample_path.unlink(missing_ok=True)

    def test_secret_bearing_key_is_rejected_without_disclosure(self) -> None:
        token = "INERT_SECRET_TOKEN_9999"
        raw_key = f"Bearer_{token}"
        payload = {raw_key: "sanitized_value_123"}
        completed = run_helper("check-privacy", "--file", "-", input_text=json.dumps(payload))
        self.assertNotEqual(completed.returncode, 0)
        output = completed.stdout + completed.stderr
        expected_category = classify_sensitive_field(raw_key)
        self.assertIsNotNone(expected_category)
        self.assertIn(expected_category, output.lower())
        self.assertNotIn(raw_key, output)
        self.assertNotIn(token, output)

    def test_foreign_matching_fixture_survives_suite_cleanup(self) -> None:
        foreign_file = Path(__file__).parent / ".phase02-live-test-foreign-process.json"
        assert_not_real_runtime_path(foreign_file)
        foreign_file.write_text('{"foreign": true}', encoding="utf-8")
        self.addCleanup(lambda: foreign_file.unlink(missing_ok=True))

        challenge, evidence = fixture_pair()
        c_path, e_path, temp_paths = write_json_fixtures(challenge, evidence, test_case=self)
        try:
            self.assertTrue(c_path.exists())
            self.assertTrue(e_path.exists())
        finally:
            for p in temp_paths:
                p.unlink(missing_ok=True)

        self.assertTrue(foreign_file.exists())

    def test_owned_directory_and_file_cleanup_on_assertion_failure(self) -> None:
        owned_dir = Path(tempfile.mkdtemp(dir=Path(__file__).parent, prefix=".phase02-live-test-dir-"))
        owned_file = owned_dir / "nested_fixture.json"
        owned_file.write_text('{"nested": true}', encoding="utf-8")
        assert_not_real_runtime_path(owned_dir)
        assert_not_real_runtime_path(owned_file)

        self.addCleanup(lambda: shutil.rmtree(owned_dir, ignore_errors=True))

        self.assertTrue(owned_dir.exists())
        self.assertTrue(owned_file.exists())


if __name__ == "__main__":
    unittest.main()

