"""Shared pytest fixtures for lancet_eval tests."""

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the fixtures directory path."""
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def load_sse_fixture(fixtures_dir: Path):
    """Load an SSE fixture file as text with explicit UTF-8 encoding."""

    def _loader(name: str) -> str:
        target = fixtures_dir / "sse" / name
        with open(target, encoding="utf-8") as f:
            return f.read()

    return _loader


@pytest.fixture
def censored_2026_09_03_sample() -> list[dict]:
    """Censored sample drawn from the 2026-09-03 journal.

    904 of 1000 retrieval observations in this run sat at the 10000ms
    retrieve_timeout_ms ceiling, making it a censored distribution rather
    than clean latency data.
    """
    import json

    journal_path = (
        Path(__file__).resolve().parents[1]
        / "runs"
        / "2026-09-03-multihop_rag"
        / "journal.jsonl"
    )
    if not journal_path.exists():
        # Fallback synthetic censored sample if run directory is absent
        return [
            {
                "corpus": "multihop_rag",
                "question_id": f"q_{i}",
                "graph_arm": "graph-on" if i % 2 == 0 else "graph-off",
                "outcome": "success",
                "node_timings": [
                    {"node_name": "RetrieveHybrid", "duration_ms": 10000.0}
                ],
                "node_failures": [],
                "notices": [],
            }
            for i in range(50)
        ]

    sample = []
    with open(journal_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 50:
                break
            if line.strip():
                sample.append(json.loads(line))
    return sample


@pytest.fixture
def synthetic_flat_latencies() -> list[float]:
    """Synthetic flat latency distribution with minimal random variance."""
    import random

    rng = random.Random(42)
    return [150.0 + rng.uniform(-5.0, 5.0) for _ in range(100)]


@pytest.fixture
def synthetic_upward_latencies() -> list[float]:
    """Synthetic upward-trending latency distribution with positive slope."""
    import random

    rng = random.Random(42)
    return [100.0 + 2.5 * i + rng.uniform(-5.0, 5.0) for i in range(100)]


@pytest.fixture
def synthetic_all_at_ceiling_latencies() -> list[float]:
    """Synthetic observation set where all values sit at the 10000ms ceiling."""
    return [10000.0] * 50
