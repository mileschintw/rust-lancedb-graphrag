"""Batch client port for the S2 reader arms (#53, D-254, D-255).

`batch submit` and `batch fetch` (``lancet_eval.batch``) talk to a reader's batch
endpoint through ``BatchClient``, so the tests use a fake and no paid call. Two
implementations exist, one per ``reader_request.Target``:

- ``OpenRouterBatchClient``: ``POST /api/v1/batches`` with the batch-level
  ``endpoint``, ``model`` and ``provider`` ahead of inline ``{custom_id, body}``
  requests (#107; model and provider pin read from the bodies);
  ``GET /api/v1/batches/{id}`` returns the status and, once finished,
  each request's chat-completions response or error.
- ``AnthropicBatchClient``: the Message Batches API. ``POST /v1/messages/batches``
  with ``{custom_id, params}`` requests; ``GET /v1/messages/batches/{id}`` gives the
  processing status and, once ended, a ``results_url`` of JSON lines.

deepseek's replicates take neither (D-278): ``OpenRouterChatClient`` posts each body
to the sync chat-completions API, since the Batch API's ``provider`` takes only
``only`` and ``allow_fallbacks`` and ``deepseek/deepseek-v4-flash-0731`` has no batch
variant.

Each request body is sent as the exact JSON text the rewrite produced
(``reader_request.ReaderRequest.body_json``): the payload is assembled around that
text and never re-serialised, so the body hash in the manifest is the hash of the
bytes sent.

A finished result is normalised into a ``ReaderOutput``, the fields `render` and the
replay record need (``ReplayProvenance``), whatever the target:

- OpenRouter: ``choices[0].message.content`` and ``finish_reason``; ``usage``'s
  token counts, ``usage.is_byok`` and
  ``usage.completion_tokens_details.reasoning_tokens``; the response's ``model`` and
  ``provider``. A batch row wraps that chat completion in ``response.body``, beside
  its ``status_code``, and its usage reports no ``is_byok``: the batch-level
  ``usage.is_byok`` is every row's (#137, D-279). A failed batch names why in one
  batch-level ``error.message`` and returns no rows (``BatchResults.error``).
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

import dataclasses
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
#: The Batch API's batch-level ``endpoint``: every body is a chat-completions body.
OPENROUTER_ENDPOINT = "/v1/chat/completions"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
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


class BatchResults(list[BatchResult]):
    """A finished batch's results, with the batch-level error when it failed.

    OpenRouter fails a whole batch with one ``error.message`` and no ``results``
    (#137); ``error`` carries that message to the requests the batch returned
    nothing for.
    """

    def __init__(self, items: Sequence[BatchResult] = (), *, error: str | None = None):
        super().__init__(items)
        self.error = error


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


def _payload(
    requests: Sequence[BatchRequest],
    body_key: str,
    head: Mapping[str, Any] | None = None,
) -> bytes:
    # Each body is embedded as the exact text whose hash the manifest records;
    # `head`'s batch-level fields go first, in order.
    fields = "".join(
        f"{json.dumps(k)}:{json.dumps(v, separators=(',', ':'))},"
        for k, v in (head or {}).items()
    )
    items = ",".join(
        f'{{"custom_id":{json.dumps(r.custom_id)},"{body_key}":{r.body_json}}}'
        for r in requests
    )
    return f'{{{fields}"requests":[{items}]}}'.encode()


def _openrouter_head(requests: Sequence[BatchRequest]) -> dict[str, Any]:
    """The batch-level fields OpenRouter's Batch API wants ahead of `requests`.

    One model and one provider pin per batch, read from the bodies (the rewrite
    sets both from the reader's declaration). The batch-level ``provider`` takes
    only the keys that schema allows (``only``, ``allow_fallbacks``).

    Raises:
        BatchClientError: If the bodies name no model, or no ``provider.only`` pin,
            or disagree on either: a batch without the pin may run, and be billed,
            on shared capacity.
    """
    head: dict[str, Any] | None = None
    for r in requests:
        try:
            body = json.loads(r.body_json)
        except ValueError as exc:
            raise BatchClientError(f"{r.custom_id}: the body is not JSON") from exc
        if not isinstance(body, dict):
            raise BatchClientError(f"{r.custom_id}: the body is not an object")
        model, provider = body.get("model"), body.get("provider")
        if not isinstance(model, str) or not model:
            raise BatchClientError(f"{r.custom_id}: the body names no model")
        if not isinstance(provider, dict) or not provider.get("only"):
            raise BatchClientError(f"{r.custom_id}: the body pins no provider")
        pin = {k: provider[k] for k in ("only", "allow_fallbacks") if k in provider}
        this = {"endpoint": OPENROUTER_ENDPOINT, "model": model, "provider": pin}
        if head is not None and this != head:
            raise BatchClientError(
                f"{r.custom_id}: an OpenRouter batch needs one model and one "
                "provider pin"
            )
        head = this
    if head is None:
        raise BatchClientError("an OpenRouter batch needs at least one request")
    return head


def _batch_error(error: Any) -> str | None:
    """A failed batch's own ``error.message`` (#137), as the endpoint wrote it."""
    if error is None:
        return None
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    return _error_text(error)


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
            content=_payload(requests, "body", _openrouter_head(requests)),
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
        usage = data.get("usage")
        is_byok = usage.get("is_byok") if isinstance(usage, dict) else None
        error = data.get("error")
        return BatchResults(
            [
                _openrouter_result(item, is_byok if isinstance(is_byok, bool) else None)
                for item in items
            ],
            error=_batch_error(error),
        )


def _openrouter_result(item: Mapping[str, Any], is_byok: bool | None) -> BatchResult:
    """One row of an OpenRouter batch's ``results`` (#137).

    A row is in the OpenAI batch output shape: ``{"id", "custom_id", "response":
    {"status_code", "request_id", "body": <chat completion>}, "error"}``. A row with
    an error, no ``response``, a non-2xx ``status_code`` or no ``body`` is
    ``errored``. A row's usage reports no ``is_byok``; the batch's does, and it is
    the row's (D-279).
    """
    custom_id = str(item.get("custom_id"))
    status = item.get("status")
    if status in {"expired", "canceled", "cancelled"}:
        return BatchResult(
            custom_id,
            "expired" if status == "expired" else "canceled",
            error=f"the request {status}",
        )
    response = item.get("response")
    if item.get("error") is not None or not isinstance(response, dict):
        return BatchResult(
            custom_id, "errored", error=_error_text(item.get("error") or "no response")
        )
    code = response.get("status_code")
    body = response.get("body")
    if not isinstance(code, int) or not 200 <= code < 300:
        detail = _error_text(body.get("error", body)) if isinstance(body, dict) else ""
        return BatchResult(
            custom_id, "errored", error=f"status_code {code!r} {detail}".strip()
        )
    if not isinstance(body, dict):
        return BatchResult(custom_id, "errored", error="the response has no body")
    try:
        output = openrouter_output(body)
    except BatchClientError as exc:
        return BatchResult(custom_id, "unreadable", error=str(exc))
    return BatchResult(
        custom_id, "succeeded", output=dataclasses.replace(output, is_byok=is_byok)
    )


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


class OpenRouterChatClient:
    """OpenRouter's sync chat-completions endpoint, for deepseek's replicates (D-278).

    The Batch API cannot carry D-271's pin (its batch-level ``provider`` takes only
    ``only`` and ``allow_fallbacks``, and a body's own ``provider`` does not route the
    batch), and ``deepseek/deepseek-v4-flash-0731`` has no batch variant. Each body
    is posted alone as the exact JSON text the manifest hashes, so its pin (``order``,
    ``allow_fallbacks: false``, ``max_price``) routes the request. A request that
    fails comes back as a result, never a refusal, so the others still run:
    ``errored`` for a transport failure or an HTTP or API error (nothing billed), and
    ``unreadable`` for a reply ``openrouter_output`` cannot read or a read timeout
    after the request was sent (probably billed, so ``--retry-errors`` leaves it).
    """

    def __init__(self, api_key: str, *, url: str = OPENROUTER_CHAT_URL) -> None:
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

    def complete(self, request: BatchRequest) -> BatchResult:
        """Posts one body and reads its reply as a result."""
        cid = request.custom_id
        try:
            res = httpx.post(
                self._url,
                content=request.body_json.encode("utf-8"),
                headers=self._headers,
                timeout=_TIMEOUT_S,
            )
        except httpx.ReadTimeout as exc:
            # Sent, but the reply never came: it may have been answered and billed,
            # so it is not retried by default (`unreadable`, like a garbled reply).
            return BatchResult(
                cid, "unreadable", error=f"no reply within {_TIMEOUT_S} s: {exc!r}"
            )
        except httpx.HTTPError as exc:
            return BatchResult(cid, "errored", error=f"transport failure: {exc!r}")
        if res.status_code >= 400:
            return BatchResult(
                cid, "errored", error=f"HTTP {res.status_code}: {res.text[:300]}"
            )
        try:
            data = res.json()
        except ValueError:
            return BatchResult(cid, "unreadable", error="the reply is not JSON")
        if not isinstance(data, dict):
            return BatchResult(cid, "unreadable", error="the reply is not an object")
        if data.get("error") is not None:
            return BatchResult(cid, "errored", error=_error_text(data["error"]))
        try:
            output = openrouter_output(data)
        except BatchClientError as exc:
            return BatchResult(cid, "unreadable", error=str(exc))
        return BatchResult(cid, "succeeded", output=output)


def chat_client() -> OpenRouterChatClient:
    """The real sync client, keyed from ``OPENROUTER_API_KEY`` (D-278).

    Raises:
        BatchClientError: If ``OPENROUTER_API_KEY`` is not set.
    """
    return OpenRouterChatClient(os.environ.get("OPENROUTER_API_KEY", ""))


def client_for(target: Target) -> BatchClient:
    """The real client for a reader's target, keyed from the environment.

    Raises:
        BatchClientError: If the target's API key (`ANTHROPIC_API_KEY` or
            `OPENROUTER_API_KEY`) is not set.
    """
    if target == "anthropic":
        return AnthropicBatchClient(os.environ.get("ANTHROPIC_API_KEY", ""))
    return OpenRouterBatchClient(os.environ.get("OPENROUTER_API_KEY", ""))
