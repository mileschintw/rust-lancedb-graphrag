"""Loopback-only OpenRouter provider stub for the OI-02 full-stack replay (06.3.4.1-07 Task 2).

Python stdlib only (`http.server.ThreadingHTTPServer`, `json`) -- no new dependency (AI-SPEC
§2). Serves the three endpoints the engine's OpenRouter client actually calls:
`/models` (capability check at startup, before any query runs), `/embeddings`, and
`/chat/completions`. All responses are synthetic; no request body is logged beyond its length
(T-06.3.4.1-07-04/09).

The stub refuses to bind to any host other than ``127.0.0.1``/``::1`` -- this is enforced in
``run_server`` before the socket is ever opened, not just documented.

Run as ``python -m lancet_eval.provider_stub --host 127.0.0.1 --port <p> --model <id>
--vectors <jsonl> --embed-delay-ms <n> --chat-delay-ms <n>``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

#: Hosts this stub is ever permitted to bind (T-06.3.4.1-07-04: never a non-loopback address).
_ALLOWED_HOSTS = ("127.0.0.1", "::1", "localhost")

#: Fixed embedding dimensionality (matches `voyage-4-large`'s configured `dimensions`, engine/src/client/mod.rs).
EMBEDDING_DIMENSIONS = 2048

#: The `ModelOutput` shape the engine's strict `response_format` JSON schema requires
#: (`engine/src/generation/mod.rs`, `#[serde(deny_unknown_fields)]`), matching
#: `retrieval_soak.rs`'s `FixedGenerator`'s known-valid answer citing `[1]`.
_VALID_MODEL_OUTPUT_ANSWER = "Answer: full-stack replay stub answer [1]"
_VALID_MODEL_OUTPUT_CITED_IDS = ["[1]"]
_VALID_MODEL_OUTPUT_BASIS = "retrieval"


class HostNotAllowedError(ValueError):
    """Raised when a caller asks the stub to bind a non-loopback host."""


def assert_loopback_host(host: str) -> None:
    """Raises `HostNotAllowedError` unless `host` is a loopback address/name."""
    if host not in _ALLOWED_HOSTS:
        raise HostNotAllowedError(
            f"provider_stub refuses to bind non-loopback host {host!r}; "
            f"allowed: {_ALLOWED_HOSTS!r}"
        )


def load_vector_map(path: str | Path | None) -> dict[str, list[float]]:
    """Loads a `{text: [float, ...]}` map from a JSONL file of `{"text": ..., "embedding": [...]}`
    lines. Returns an empty map if `path` is None or the file does not exist."""
    vectors: dict[str, list[float]] = {}
    if path is None:
        return vectors
    p = Path(path)
    if not p.exists():
        return vectors
    with open(p, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = data.get("text") or data.get("chunk_id")
            embedding = data.get("embedding")
            if isinstance(text, str) and isinstance(embedding, list):
                vectors[text] = [float(x) for x in embedding]
    return vectors


def hash_vector(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    """A deterministic unit vector seeded by a hash of `text`, used when `text` is absent from
    the loaded vector map. Deterministic across runs given the same input text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand the 32-byte digest into `dimensions` floats via repeated re-hashing, cheaply.
    values: list[float] = []
    seed = digest
    while len(values) < dimensions:
        seed = hashlib.sha256(seed).digest()
        for i in range(0, len(seed) - 1, 2):
            if len(values) >= dimensions:
                break
            raw = struct.unpack(">H", seed[i : i + 2])[0]
            values.append((raw / 65535.0) * 2.0 - 1.0)
    norm = sum(v * v for v in values) ** 0.5
    if norm == 0:
        return values
    return [v / norm for v in values]


def embedding_for(
    text: str, vector_map: dict[str, list[float]], dimensions: int = EMBEDDING_DIMENSIONS
) -> tuple[list[float], bool]:
    """Returns `(embedding, from_map)`. `from_map` is False when the hash fallback was used --
    the replay script's fallback-count accounting reads this."""
    vec = vector_map.get(text)
    if vec is not None:
        return vec, True
    return hash_vector(text, dimensions), False


def build_models_response(model_id: str) -> dict[str, Any]:
    """The `/models` response body: `supported_parameters` must include `response_format` and
    `structured_outputs`, or the engine's startup `validate_against_provider` fails closed
    (`engine/src/config.rs`, `engine/src/generation/openrouter.rs:394-500`)."""
    return {
        "data": [
            {
                "id": model_id,
                "supported_parameters": [
                    "response_format",
                    "json_schema",
                    "structured_outputs",
                ],
            }
        ]
    }


def build_chat_completion_response(prompt_tokens_estimate: int) -> dict[str, Any]:
    """The `/chat/completions` response body: `choices[0].message.content` is a JSON string
    that must parse as the engine's strict `ModelOutput` schema (deny_unknown_fields)."""
    model_output = {
        "answer": _VALID_MODEL_OUTPUT_ANSWER,
        "cited_evidence_ids": _VALID_MODEL_OUTPUT_CITED_IDS,
        "answer_basis": _VALID_MODEL_OUTPUT_BASIS,
        "notices": [],
        "warnings": [],
        "usage": None,
    }
    completion_tokens = 40
    return {
        "choices": [
            {
                "message": {"content": json.dumps(model_output)},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens_estimate,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens_estimate + completion_tokens,
        },
    }


def build_embeddings_response(
    inputs: list[str], vector_map: dict[str, list[float]], dimensions: int = EMBEDDING_DIMENSIONS
) -> tuple[dict[str, Any], int]:
    """Returns `(response_body, fallback_count)` -- `fallback_count` is how many of `inputs`
    missed the loaded vector map and used the hash fallback."""
    data = []
    fallback_count = 0
    total_tokens = 0
    for text in inputs:
        vec, from_map = embedding_for(text, vector_map, dimensions)
        if not from_map:
            fallback_count += 1
        data.append({"embedding": vec})
        total_tokens += max(1, len(text) // 4)
    body = {
        "data": data,
        "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
    }
    return body, fallback_count


class StubStats:
    """Thread-safe per-endpoint request counters, served at `GET /__stub/stats`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {"models": 0, "embeddings": 0, "chat_completions": 0}
        self._fallback_count = 0

    def increment(self, endpoint: str) -> None:
        with self._lock:
            self._counts[endpoint] = self._counts.get(endpoint, 0) + 1

    def add_fallback(self, n: int) -> None:
        with self._lock:
            self._fallback_count += n

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**self._counts, "embedding_fallback_count": self._fallback_count}


def make_handler(
    *,
    model_id: str,
    vector_map: dict[str, list[float]],
    embed_delay_ms: int,
    chat_delay_ms: int,
    stats: StubStats,
) -> type[BaseHTTPRequestHandler]:
    """Builds a `BaseHTTPRequestHandler` subclass closing over the stub's configuration --
    `http.server` handlers are classes, not instances, so configuration must be closed over
    at class-construction time."""

    class Handler(BaseHTTPRequestHandler):
        # No per-request access log line beyond the standard library's own (which logs the
        # request line, not the body) -- never log a request body (T-06.3.4.1-07-04).
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b""
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def _write_json(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path.endswith("/models"):
                stats.increment("models")
                self._write_json(200, build_models_response(model_id))
                return
            if path.endswith("/__stub/stats"):
                self._write_json(200, stats.snapshot())
                return
            self._write_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            body = self._read_json_body()
            if path.endswith("/embeddings"):
                if embed_delay_ms:
                    time.sleep(embed_delay_ms / 1000.0)
                raw_input = body.get("input", [])
                inputs = raw_input if isinstance(raw_input, list) else [raw_input]
                inputs = [str(x) for x in inputs]
                resp, fallback = build_embeddings_response(inputs, vector_map)
                stats.increment("embeddings")
                stats.add_fallback(fallback)
                self._write_json(200, resp)
                return
            if path.endswith("/chat/completions"):
                if chat_delay_ms:
                    time.sleep(chat_delay_ms / 1000.0)
                # Body length only, never content (T-06.3.4.1-07-04/09).
                _ = len(json.dumps(body))
                prompt_tokens_estimate = 2000
                stats.increment("chat_completions")
                self._write_json(200, build_chat_completion_response(prompt_tokens_estimate))
                return
            self._write_json(404, {"error": "not found"})

    return Handler


def run_server(
    *,
    host: str,
    port: int,
    model_id: str,
    vectors_path: str | Path | None,
    embed_delay_ms: int,
    chat_delay_ms: int,
) -> ThreadingHTTPServer:
    """Builds and returns a bound (not yet `serve_forever`-running) `ThreadingHTTPServer`.
    Raises `HostNotAllowedError` before any socket is opened if `host` is not loopback."""
    assert_loopback_host(host)
    vector_map = load_vector_map(vectors_path)
    stats = StubStats()
    handler_cls = make_handler(
        model_id=model_id,
        vector_map=vector_map,
        embed_delay_ms=embed_delay_ms,
        chat_delay_ms=chat_delay_ms,
        stats=stats,
    )
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    server = ThreadingHTTPServer((host, port), handler_cls)
    if family == socket.AF_INET6:  # pragma: no cover - platform dependent, not exercised in CI
        pass
    server.stub_stats = stats  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lancet_eval.provider_stub")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", required=True, dest="model_id")
    parser.add_argument("--vectors", default=None)
    parser.add_argument("--embed-delay-ms", type=int, default=0)
    parser.add_argument("--chat-delay-ms", type=int, default=0)
    args = parser.parse_args(argv)

    try:
        server = run_server(
            host=args.host,
            port=args.port,
            model_id=args.model_id,
            vectors_path=args.vectors,
            embed_delay_ms=args.embed_delay_ms,
            chat_delay_ms=args.chat_delay_ms,
        )
    except HostNotAllowedError as exc:
        print(str(exc))
        return 1

    print(f"provider_stub listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
