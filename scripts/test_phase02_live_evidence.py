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


def timestamp(offset_seconds: int = 0) -> str:
    value = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_seconds)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def fixture_pair() -> tuple[dict[str, object], dict[str, object]]:
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
        "embedding_model": "not-the-locked-model",
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


class Phase02LiveEvidenceTests(unittest.TestCase):
    def test_wrong_model_is_rejected_in_optimized_isolated_subprocess(self) -> None:
        self.assertEqual(sys.flags.optimize, 1, "the optimized test gate must run with -O")
        challenge, evidence = fixture_pair()
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


if __name__ == "__main__":
    unittest.main()
