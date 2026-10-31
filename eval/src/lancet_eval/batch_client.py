"""Batch client port for the S2 reader arms (#53, D-254, D-255).

`batch submit` and `batch fetch` (``lancet_eval.batch``) talk to a reader's batch
endpoint through ``BatchClient``, so the tests use a fake and no paid call. Two
implementations exist, one per ``reader_request.Target``:

- ``OpenRouterBatchClient``: ``POST /api/v1/batches`` with inline
  ``{custom_id, body}`` requests; ``GET /api/v1/batches/{id}`` returns the status
  and, once finished, each request's chat-completions response or error.
- ``AnthropicBatchClient``: the Message Batches API. ``POST /v1/messages/batches``
  with ``{custom_id, params}`` requests; ``GET /v1/messages/batches/{id}`` gives the
  processing status and, once ended, a ``results_url`` of JSON lines.

Each request body is sent as the exact JSON text the rewrite produced
(``reader_request.ReaderRequest.body_json``): the payload is assembled around that
text and never re-serialised, so the body hash in the manifest is the hash of the
bytes sent.

A finished result is normalised into a ``ReaderOutput``, the fields `render` and the
replay record need (``ReplayProvenance``), whatever the target:

- OpenRouter: ``choices[0].message.content`` and ``finish_reason``; ``usage``'s
  token counts, ``usage.is_byok`` and
  ``usage.completion_tokens_details.reasoning_tokens``; the response's ``model`` and
  ``provider``.
- Anthropic: the text blocks of the message joined; ``stop_reason`` mapped to the
  chat-completions value (``end_turn`` → ``stop``, ``max_tokens`` → ``length``);
  ``input_tokens`` and ``output_tokens``; the message's ``model``; the endpoint host as
  the provider, ``is_byok`` ``None`` and 0 reasoning tokens, since that response
  reports neither (#82); and the content block types in order.

A value the response does not report fails closed rather than being guessed: a
missing OpenRouter reasoning count is recorded as ``MISSING_REASONING_TOKENS``, so
the ``reasoning_tokens`` clause refuses it for a reader whose thinking is not ``on``
(a thinking-on reader is exempt from that clause, so the -1 stands unchecked there).
A response with null content is read as empty content, which `render` rejects while
the record keeps its usage; one with no usage or choice is ``unreadable``. Completion
tokens include reasoning tokens on both targets.

The OpenRouter batch response shape is not documented at the time of writing; the
paid pilot (``batch submit --limit N``, the owner's) confirms it. Neither client sends
anything until the owner runs a submit.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from lancet_eval.provenance import REPLAY_PROVIDERS
from lancet_eval.reader_request import Target

#: `unreadable`: a response arrived, but not one `ReaderOutput` can be read from.
ResultStatus = Literal["succeeded", "errored", "expired", "canceled", "unreadable"]

#: Recorded when an OpenRouter response reports no reasoning token count; the
#: ``reasoning_tokens`` clause then fails for a reader that must report 0 (D-260).
MISSING_REASONING_TOKENS = -1

OPENROUTER_BATCHES_URL = "https://openrouter.ai/api/v1/batches"
ANTHROPIC_BATCHES_URL = "https://api.anthropic.com/v1/messages/batches"
ANTHROPIC_VERSION = "2023-06-01"

#: Anthropic `stop_reason` → the chat-completions `finish_reason` `render` reads.
_STOP_REASONS = {"end_turn": "stop", "max_tokens": "length", "refusal": "refusal"}
_TIMEOUT_S = 120.0
#: OpenRouter batch statuses after which no result changes. A request the results
#: omit becomes an error record that `--retry-errors` resubmits.
_OPENROUTER_FINISHED = frozenset({
    "completed",
    "ended",
    "expired",
    "cancelled",
    "canceled",
    "failed",
    "error",
})


class BatchClientError(RuntimeError):
    """A batch endpoint refused a request or answered with something unreadable."""


@dataclass(frozen=True)
class BatchRequest:
    """One request of a batch: its ``custom_id`` (the question ID) and body text."""

    custom_id: str
    body_json: str


@dataclass(frozen=True)
class ReaderOutput:
    """A finished request's response, normalised across targets (module docstring)."""

    content: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    provider: str
    is_byok: bool | None
    reasoning_tokens: int
    content_block_types: tuple[str, ...] | None


@dataclass(frozen=True)
class BatchResult:
    """One request's outcome. ``output`` is set exactly when it ``succeeded``."""

    custom_id: str
    status: ResultStatus
    output: ReaderOutput | None = None
    error: str | None = None


class BatchClient(Protocol):
    """A reader's batch endpoint."""

    @property
    def endpoint(self) -> str:
        """The URL batches are submitted to; the manifest records it."""
        ...

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        """Submits one batch; returns its batch ID."""
        ...

    def results(self, batch_id: str) -> list[BatchResult] | None:
        """The batch's results, or None while it is still processing."""
        ...


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BatchClientError(f"{what} is not an integer: {value!r}")
    return value


def openrouter_output(response: Mapping[str, Any]) -> ReaderOutput:
    """A chat-completions response from OpenRouter as a ``ReaderOutput``.

    Raises:
        BatchClientError: If the response has no choice, message content or usage.
    """
    try:
        choice = response["choices"][0]
        content = choice["message"]["content"]
        usage = response["usage"]
    except (KeyError, IndexError, TypeError) as exc:
        raise BatchClientError(f"unreadable OpenRouter response: {exc!r}") from exc
    if content is None:
        content = ""  # `render` rejects it, and the record keeps the usage
    if not isinstance(content, str):
        raise BatchClientError("the OpenRouter response's content is not text")
    details = usage.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    is_byok = usage.get("is_byok")
    return ReaderOutput(
        content=content,
        finish_reason=choice.get("finish_reason"),
        prompt_tokens=_int(usage.get("prompt_tokens"), "usage.prompt_tokens"),
        completion_tokens=_int(
            usage.get("completion_tokens"), "usage.completion_tokens"
        ),
        total_tokens=_int(usage.get("total_tokens"), "usage.total_tokens"),
        model=str(response.get("model") or ""),
        provider=str(response.get("provider") or ""),
        is_byok=is_byok if isinstance(is_byok, bool) else None,
        reasoning_tokens=(
            MISSING_REASONING_TOKENS
            if reasoning is None
            else _int(reasoning, "reasoning_tokens")
        ),
        content_block_types=None,
    )


def anthropic_output(message: Mapping[str, Any]) -> ReaderOutput:
    """A Messages API response as a ``ReaderOutput``.

    Raises:
        BatchClientError: If the message has no content list or usage.
    """
    try:
        blocks = message["content"]
        usage = message["usage"]
    except (KeyError, TypeError) as exc:
        raise BatchClientError(f"unreadable Anthropic message: {exc!r}") from exc
    if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
        raise BatchClientError("the Anthropic message's content is not a block list")
    prompt = _int(usage.get("input_tokens"), "usage.input_tokens")
    completion = _int(usage.get("output_tokens"), "usage.output_tokens")
    stop = message.get("stop_reason")
    return ReaderOutput(
        content="".join(
            str(b.get("text", "")) for b in blocks if b.get("type") == "text"
        ),
        finish_reason=_STOP_REASONS.get(stop, stop) if isinstance(stop, str) else None,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        model=str(message.get("model") or ""),
        provider=REPLAY_PROVIDERS["anthropic"],
        is_byok=None,
        reasoning_tokens=0,
        content_block_types=tuple(str(b.get("type")) for b in blocks),
    )


def _payload(requests: Sequence[BatchRequest], body_key: str) -> bytes:
    # Each body is embedded as the exact text whose hash the manifest records.
    items = ",".join(
        f'{{"custom_id":{json.dumps(r.custom_id)},"{body_key}":{r.body_json}}}'
        for r in requests
    )
    return f'{{"requests":[{items}]}}'.encode()


def _error_text(error: Any) -> str:
    if isinstance(error, dict):
        inner = error.get("error", error)
        if isinstance(inner, dict):
            kind = inner.get("type") or inner.get("code") or "error"
            return f"{kind}: {inner.get('message', '')}".strip()
    return str(error)


def _json(response: httpx.Response, what: str) -> Any:
    if response.status_code >= 400:
        raise BatchClientError(
            f"{what}: HTTP {response.status_code}: {response.text[:500]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise BatchClientError(f"{what}: the response is not JSON") from exc


class OpenRouterBatchClient:
    """OpenRouter's batch endpoint (module docstring)."""

    def __init__(self, api_key: str, *, url: str = OPENROUTER_BATCHES_URL) -> None:
        if not api_key.strip():
            raise BatchClientError("OPENROUTER_API_KEY is not set")
        self._url = url
        self._headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        }

    @property
    def endpoint(self) -> str:
        return self._url

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        res = httpx.post(
            self._url,
            content=_payload(requests, "body"),
            headers=self._headers,
            timeout=_TIMEOUT_S,
        )
        data = _json(res, "OpenRouter batch submit")
        batch_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(batch_id, str) or not batch_id:
            raise BatchClientError("OpenRouter batch submit returned no batch ID")
        return batch_id

    def results(self, batch_id: str) -> list[BatchResult] | None:
        res = httpx.get(
            f"{self._url}/{batch_id}", headers=self._headers, timeout=_TIMEOUT_S
        )
        data = _json(res, f"OpenRouter batch {batch_id}")
        if not isinstance(data, dict):
            raise BatchClientError(f"OpenRouter batch {batch_id}: not an object")
        if data.get("status") not in _OPENROUTER_FINISHED:
            return None
        items = data.get("results") or []
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise BatchClientError(f"OpenRouter batch {batch_id}: unreadable results")
        return [_openrouter_result(item) for item in items]


def _openrouter_result(item: Mapping[str, Any]) -> BatchResult:
    custom_id = str(item.get("custom_id"))
    status = item.get("status")
    if status in {"expired", "canceled", "cancelled"}:
        return BatchResult(
            custom_id,
            "expired" if status == "expired" else "canceled",
            error=f"the request {status}",
        )
    if item.get("error") is not None or not isinstance(item.get("response"), dict):
        return BatchResult(
            custom_id, "errored", error=_error_text(item.get("error") or "no response")
        )
    try:
        output = openrouter_output(item["response"])
    except BatchClientError as exc:
        return BatchResult(custom_id, "unreadable", error=str(exc))
    return BatchResult(custom_id, "succeeded", output=output)


class AnthropicBatchClient:
    """The Anthropic Message Batches API (module docstring)."""

    def __init__(self, api_key: str, *, url: str = ANTHROPIC_BATCHES_URL) -> None:
        if not api_key.strip():
            raise BatchClientError("ANTHROPIC_API_KEY is not set")
        self._url = url
        self._headers = {
            "x-api-key": api_key.strip(),
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    @property
    def endpoint(self) -> str:
        return self._url

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        res = httpx.post(
            self._url,
            content=_payload(requests, "params"),
            headers=self._headers,
            timeout=_TIMEOUT_S,
        )
        data = _json(res, "Anthropic batch submit")
        batch_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(batch_id, str) or not batch_id:
            raise BatchClientError("Anthropic batch submit returned no batch ID")
        return batch_id

    def results(self, batch_id: str) -> list[BatchResult] | None:
        res = httpx.get(
            f"{self._url}/{batch_id}", headers=self._headers, timeout=_TIMEOUT_S
        )
        data = _json(res, f"Anthropic batch {batch_id}")
        if not isinstance(data, dict) or data.get("processing_status") != "ended":
            return None
        url = data.get("results_url")
        if not isinstance(url, str) or not url:
            raise BatchClientError(f"Anthropic batch {batch_id} has no results_url")
        lines = httpx.get(url, headers=self._headers, timeout=_TIMEOUT_S)
        if lines.status_code >= 400:
            raise BatchClientError(
                f"Anthropic batch {batch_id} results: HTTP {lines.status_code}"
            )
        return [
            _anthropic_result(_object(line, batch_id))
            for line in lines.text.splitlines()
            if line.strip()
        ]


def _object(line: str, batch_id: str) -> dict[str, Any]:
    try:
        item = json.loads(line)
    except ValueError as exc:
        raise BatchClientError(
            f"Anthropic batch {batch_id}: a results line is not JSON"
        ) from exc
    if not isinstance(item, dict):
        raise BatchClientError(
            f"Anthropic batch {batch_id}: a results line is not an object"
        )
    return item


def _anthropic_result(item: Mapping[str, Any]) -> BatchResult:
    custom_id = str(item.get("custom_id"))
    result = item.get("result") or {}
    kind = result.get("type") if isinstance(result, dict) else None
    if kind == "succeeded":
        try:
            return BatchResult(
                custom_id, "succeeded", output=anthropic_output(result["message"])
            )
        except (BatchClientError, KeyError) as exc:
            return BatchResult(custom_id, "unreadable", error=str(exc))
    if kind in {"expired", "canceled"}:
        return BatchResult(custom_id, kind, error=f"the request {kind}")
    return BatchResult(
        custom_id, "errored", error=_error_text(result.get("error") or result)
    )


def client_for(target: Target) -> BatchClient:
    """The real client for a reader's target, keyed from the environment.

    Raises:
        BatchClientError: If the target's API key (`ANTHROPIC_API_KEY` or
            `OPENROUTER_API_KEY`) is not set.
    """
    if target == "anthropic":
        return AnthropicBatchClient(os.environ.get("ANTHROPIC_API_KEY", ""))
    return OpenRouterBatchClient(os.environ.get("OPENROUTER_API_KEY", ""))
