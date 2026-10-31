"""OpenRouter embedding and rerank clients, with the request bodies Lancet sends.

Both mirror the engine's clients so the comparison isolates retrieval design
(fairness rules 5 and 7):

- Embeddings (`engine/src/client/mod.rs`): `POST /api/v1/embeddings` with `model`,
  `input` and `dimensions = 2048`, and no `input_type`. Lancet sends none for
  documents or queries, so neither does this client; see the README.
- Rerank (`engine/src/rerank/openrouter.rs`): `POST /api/v1/rerank` with `model`,
  `query`, `documents`, `top_n` = the candidate count and
  `provider.allow_fallbacks = false`. A reply naming another model, or with indices
  that are missing, repeated or out of range, is refused, as the engine refuses it.

`endpoints_from_env` reads the engine's endpoint overrides, so a rehearsal can point
both clients at the loopback provider stub. Both read the key from
`OPENROUTER_API_KEY` and take an injectable `httpx.Client`, so
the tests run against `httpx.MockTransport` with no network.
"""

from __future__ import annotations

import math
import os
import time

import httpx
from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import PrivateAttr

EMBEDDING_ENDPOINT = "https://openrouter.ai/api/v1/embeddings"
EMBEDDING_MODEL = "voyageai/voyage-4-large"
EMBEDDING_DIMENSIONS = 2048
RERANK_ENDPOINT = "https://openrouter.ai/api/v1/rerank"
RERANK_MODEL = "voyageai/rerank-2.5-lite"

# The variables the engine reads its endpoints from (`engine/src/config.rs`), so one
# set points both the Lancet arm and this export at `lancet_eval.provider_stub` (#76).
# Unlike the engine, a blank value here means OpenRouter rather than an error.
EMBEDDING_ENDPOINT_ENV = "LANCET_OPENROUTER__EMBEDDING_ENDPOINT"
RERANK_ENDPOINT_ENV = "LANCET_OPENROUTER__RERANK_ENDPOINT"

_MAX_RETRIES = 6
_INITIAL_BACKOFF_S = 2.0
_MAX_BACKOFF_S = 30.0
_TIMEOUT_S = 30.0


class ProviderError(Exception):
    """A provider call failed or its reply was refused."""


def api_key_from_env() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ProviderError("OPENROUTER_API_KEY is not configured")
    return key


def endpoints_from_env() -> tuple[str, str]:
    """The `(embedding, rerank)` endpoints: each variable's value when set and not
    blank, else OpenRouter's."""
    embedding = os.environ.get(EMBEDDING_ENDPOINT_ENV, "").strip()
    rerank = os.environ.get(RERANK_ENDPOINT_ENV, "").strip()
    return embedding or EMBEDDING_ENDPOINT, rerank or RERANK_ENDPOINT


def _post(
    http: httpx.Client, url: str, api_key: str, body: dict, backoff_s: float
) -> dict:
    """POSTs `body`, retrying transport errors, 429 and 5xx with doubling backoff."""
    delay = backoff_s
    for attempt in range(_MAX_RETRIES + 1):
        last = attempt == _MAX_RETRIES
        try:
            response = http.post(
                url, json=body, headers={"Authorization": f"Bearer {api_key}"}
            )
        except httpx.TransportError as exc:
            if last:
                raise ProviderError(f"{url}: {type(exc).__name__}") from exc
        else:
            status = response.status_code
            if status == 429 or status >= 500:
                if last:
                    raise ProviderError(f"{url}: HTTP {status}")
            elif status >= 400:
                raise ProviderError(f"{url}: HTTP {status}")
            else:
                try:
                    return response.json()
                except ValueError as exc:
                    raise ProviderError(f"{url}: reply is not JSON") from exc
        time.sleep(delay)
        delay = min(delay * 2, _MAX_BACKOFF_S)
    raise AssertionError("retry loop always returns or raises")


class OpenRouterEmbedding(BaseEmbedding):
    """`voyageai/voyage-4-large` through OpenRouter, sent as Lancet sends it."""

    model_name: str = EMBEDDING_MODEL
    endpoint: str = EMBEDDING_ENDPOINT
    dimensions: int = EMBEDDING_DIMENSIONS
    backoff_s: float = _INITIAL_BACKOFF_S
    _api_key: str = PrivateAttr()
    _http: httpx.Client = PrivateAttr()

    def __init__(
        self, api_key: str, http: httpx.Client | None = None, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=_TIMEOUT_S, follow_redirects=False)

    @classmethod
    def class_name(cls) -> str:
        return "OpenRouterEmbedding"

    def _embed(self, texts: list[str]) -> list[list[float]]:
        body = {"model": self.model_name, "input": texts, "dimensions": self.dimensions}
        reply = _post(self._http, self.endpoint, self._api_key, body, self.backoff_s)
        try:
            data = sorted(reply["data"], key=lambda d: d.get("index", 0))
            vectors = [[float(x) for x in d["embedding"]] for d in data]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("embedding reply has no usable data") from exc
        if len(vectors) != len(texts):
            raise ProviderError(
                f"{len(vectors)} embeddings returned for {len(texts)} inputs"
            )
        for vector in vectors:
            if len(vector) != self.dimensions or not all(map(math.isfinite, vector)):
                raise ProviderError(
                    f"embedding of dimension {len(vector)} refused, expected "
                    f"{self.dimensions} finite values"
                )
        return vectors

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed([query])[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)


def _reply_model_matches(requested: str, reply: str) -> bool:
    # The engine's `reply_model_matches`: the reply may drop the vendor prefix.
    bare = requested.split("/", 1)[1] if "/" in requested else requested
    return reply.startswith(requested) or (bool(bare) and reply.startswith(bare))


class OpenRouterReranker:
    """`voyageai/rerank-2.5-lite` through the endpoint Lancet's rerank client uses."""

    def __init__(
        self,
        api_key: str,
        http: httpx.Client | None = None,
        *,
        model: str = RERANK_MODEL,
        endpoint: str = RERANK_ENDPOINT,
        backoff_s: float = _INITIAL_BACKOFF_S,
    ) -> None:
        self._api_key = api_key
        self._http = http or httpx.Client(timeout=_TIMEOUT_S, follow_redirects=False)
        self.model = model
        self.endpoint = endpoint
        self._backoff_s = backoff_s

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        if not documents:
            return []
        body = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "provider": {"allow_fallbacks": False},
        }
        reply = _post(self._http, self.endpoint, self._api_key, body, self._backoff_s)
        model = reply.get("model")
        if not isinstance(model, str) or not _reply_model_matches(self.model, model):
            raise ProviderError(f"rerank reply from model {model!r}, not {self.model}")
        try:
            ranked = [
                (int(r["index"]), float(r["relevance_score"])) for r in reply["results"]
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("rerank reply has no usable results") from exc
        indices = sorted(index for index, _ in ranked)
        if indices != list(range(len(documents))):
            raise ProviderError(
                f"rerank reply indices {indices} do not cover {len(documents)} "
                "documents once each"
            )
        if not all(math.isfinite(score) for _, score in ranked):
            raise ProviderError("rerank reply has a non-finite score")
        return sorted(ranked, key=lambda pair: (-pair[1], pair[0]))
