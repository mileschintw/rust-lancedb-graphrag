#!/usr/bin/env python3
"""Tests for the Phase 02 live-evidence validation helper."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
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


def timestamp(offset_seconds: int = 0) -> str:
    value = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_seconds)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    challenge: dict[str, object], evidence: dict[str, object]
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
    temporary_paths.extend((challenge_path, evidence_path))
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
        check=False,
    )


class Phase02LiveEvidenceTests(unittest.TestCase):
    def test_wrong_model_is_rejected_in_optimized_isolated_subprocess(self) -> None:
        self.assertEqual(sys.flags.optimize, 1, "the optimized test gate must run with -O")
        challenge, evidence = fixture_pair(embedding_model="not-the-locked-model")
        temporary_paths: list[Path] = []
        try:
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
            temporary_paths.extend((challenge_path, evidence_path))
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
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("embedding_model", (completed.stdout + completed.stderr).lower())
            self.assertTrue(challenge_path.exists())
            self.assertTrue(evidence_path.exists())
        finally:
            for path in temporary_paths:
                path.unlink(missing_ok=True)

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


if __name__ == "__main__":
    unittest.main()
