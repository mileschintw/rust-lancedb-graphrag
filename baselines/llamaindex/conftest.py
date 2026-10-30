"""Keeps the harness's root `pytest` run from collecting this project's tests.

`uv run --project eval pytest` at the repo root runs in the harness's environment,
which has no LlamaIndex, and would fail to import `tests/conftest.py`. This project's
tests run in its own environment: `uv run --project baselines/llamaindex pytest`.
"""

import importlib.util

if importlib.util.find_spec("llama_index") is None:
    collect_ignore = ["tests"]
