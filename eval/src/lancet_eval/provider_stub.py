"""Loopback-only OpenRouter provider stub -- RED stub (06.3.4.1-07 Task 2)."""
from __future__ import annotations
from pathlib import Path
from typing import Any


class HostNotAllowedError(ValueError):
    pass


def assert_loopback_host(host: str) -> None:
    return None


def hash_vector(text: str, dimensions: int = 2048) -> list[float]:
    return [0.0] * dimensions


def load_vector_map(path):
    return {}


def embedding_for(text, vector_map, dimensions: int = 2048):
    return [0.0] * dimensions, False


def build_models_response(model_id: str) -> dict[str, Any]:
    return {}


def build_chat_completion_response(prompt_tokens_estimate: int) -> dict[str, Any]:
    return {}


def build_embeddings_response(inputs, vector_map, dimensions: int = 2048):
    return {}, 0


def run_server(**kwargs):
    raise NotImplementedError


def main(argv=None) -> int:
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
