"""Shared pytest fixtures for lancet_eval tests."""

from pathlib import Path

import pytest

from lancet_eval.client import NodeFailed
from lancet_eval.journal import NodeTiming
from lancet_eval.measure import MeasurementRecord

CEILING_CENSORED_RETRIEVE_MS = 10000.0


def _measurement_record(
    ordinal: int,
    *,
    timings: list[NodeTiming],
    failures: list[NodeFailed] | None = None,
) -> MeasurementRecord:
    return MeasurementRecord(
        corpus="multihop_rag",
        question_id=f"q_{ordinal}",
        graph_arm="graph-on" if ordinal % 2 else "graph-off",
        outcome="success",
        ordinal=ordinal,
        segment="segment-1",
        question_type="bridge",
        node_timings=timings,
        node_failures=failures or [],
    )


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


@pytest.fixture
def ceiling_censored_retrieve_ceilings() -> dict[str, float]:
    """Ceilings map the ceiling-censored measurement fixture was built against."""
    return {"RetrieveHybrid": CEILING_CENSORED_RETRIEVE_MS}


@pytest.fixture
def ceiling_censored_measurement_records() -> list[MeasurementRecord]:
    """MeasurementRecord objects with ceiling-clipped and node-timer-expired retrieval.

    Mirrors the 904-of-1000 RetrieveHybrid-at-ceiling shape from 2026-09-03,
    scaled to 50 timed records (40 exactly at the retrieve_timeout_ms ceiling,
    10 genuinely observed sub-ceiling values) plus 5 NodeFailed timeout records
    with no RetrieveHybrid timing.
    """
    records: list[MeasurementRecord] = []
    ordinal = 1
    sub_ceiling = [
        120.0,
        480.0,
        910.0,
        1500.0,
        2100.0,
        3400.0,
        5100.0,
        7200.0,
        8800.0,
        9999.0,
    ]
    for dur in sub_ceiling:
        records.append(
            _measurement_record(
                ordinal,
                timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=dur)],
            )
        )
        ordinal += 1
    for _ in range(40):
        records.append(
            _measurement_record(
                ordinal,
                timings=[
                    NodeTiming(
                        node_name="RetrieveHybrid",
                        duration_ms=CEILING_CENSORED_RETRIEVE_MS,
                    )
                ],
            )
        )
        ordinal += 1
    for _ in range(5):
        records.append(
            _measurement_record(
                ordinal,
                timings=[],
                failures=[
                    NodeFailed(
                        node_name="RetrieveHybrid",
                        error_kind=1,
                        error_message="node timeout",
                        retryable=True,
                    )
                ],
            )
        )
        ordinal += 1
    return records
