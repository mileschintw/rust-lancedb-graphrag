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
