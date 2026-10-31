"""The opt-in slow test tier (#44).

A test marked `@pytest.mark.slow` is skipped unless `LANCET_SLOW_TESTS=1`. The default
run is the fast tier every lane runs; the slow tier runs before merge or in the main
checkout.
`conftest.py` imports these hooks, so they apply to every test under `eval/tests`.
"""

from __future__ import annotations

import os

import pytest

ENV = "LANCET_SLOW_TESTS"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", f"slow: slow tier (#44); skipped unless {ENV}=1")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get(ENV) == "1":
        return
    skip = pytest.mark.skip(reason=f"slow tier (#44): set {ENV}=1 to run it")
    for item in items:
        if item.get_closest_marker("slow") is not None:
            item.add_marker(skip)
