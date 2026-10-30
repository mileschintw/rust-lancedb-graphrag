"""The OpenRouter clients send Lancet's request bodies, offline via MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from lancet_llamaindex.providers import (
    OpenRouterEmbedding,
    OpenRouterReranker,
    ProviderError,
)


def _client(handler) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(record)), seen


def _embedding_reply(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    data = [
        {"index": i, "embedding": [0.5] * body["dimensions"]}
        for i in range(len(body["input"]))
    ]
    return httpx.Response(200, json={"data": data})


def test_embedding_body_matches_lancet_and_sends_no_input_type():
    http, seen = _client(_embedding_reply)
    embed = OpenRouterEmbedding(api_key="test-key", http=http)

    vectors = embed.get_text_embedding_batch(["alpha", "beta"])
    embed.get_query_embedding("a question")

    assert [len(v) for v in vectors] == [2048, 2048]
    bodies = [json.loads(r.content) for r in seen]
    assert bodies[0] == {
        "model": "voyageai/voyage-4-large",
        "input": ["alpha", "beta"],
        "dimensions": 2048,
    }
    assert bodies[1]["input"] == ["a question"]
    assert all("input_type" not in b for b in bodies)
    assert str(seen[0].url) == "https://openrouter.ai/api/v1/embeddings"
    assert seen[0].headers["authorization"] == "Bearer test-key"


def test_embedding_of_the_wrong_dimension_is_refused():
    http, _ = _client(
        lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
    )

    with pytest.raises(ProviderError, match="dimension 1"):
        OpenRouterEmbedding(api_key="k", http=http).get_query_embedding("q")


def test_embedding_retries_a_429_then_succeeds():
    replies = iter([httpx.Response(429), None])

    def handler(request):
        reply = next(replies)
        return reply if reply is not None else _embedding_reply(request)

    http, seen = _client(handler)
    embed = OpenRouterEmbedding(api_key="k", http=http, backoff_s=0.0)

    assert len(embed.get_query_embedding("q")) == 2048
    assert len(seen) == 2


def _rerank_reply(results, model="voyageai/rerank-2.5-lite"):
    return lambda request: httpx.Response(
        200, json={"model": model, "results": results}
    )


def test_rerank_body_matches_lancet_and_sorts_best_first():
    http, seen = _client(
        _rerank_reply([
            {"index": 0, "relevance_score": 0.1},
            {"index": 2, "relevance_score": 0.9},
            {"index": 1, "relevance_score": 0.9},
        ])
    )

    ranked = OpenRouterReranker(api_key="k", http=http).rerank("q", ["a", "b", "c"])

    assert ranked == [(1, 0.9), (2, 0.9), (0, 0.1)]
    assert json.loads(seen[0].content) == {
        "model": "voyageai/rerank-2.5-lite",
        "query": "q",
        "documents": ["a", "b", "c"],
        "top_n": 3,
        "provider": {"allow_fallbacks": False},
    }
    assert str(seen[0].url) == "https://openrouter.ai/api/v1/rerank"


@pytest.mark.parametrize(
    "reply",
    [
        _rerank_reply([{"index": 0, "relevance_score": 1.0}]),  # one of two
        _rerank_reply([
            {"index": 0, "relevance_score": 1.0},
            {"index": 0, "relevance_score": 0.5},
        ]),
        _rerank_reply([
            {"index": 0, "relevance_score": 1.0},
            {"index": 5, "relevance_score": 0.5},
        ]),
        _rerank_reply(
            [
                {"index": 0, "relevance_score": 1.0},
                {"index": 1, "relevance_score": 0.5},
            ],
            model="cohere/rerank-v3.5",
        ),
        lambda r: httpx.Response(
            200, json={"results": [{"index": 0, "relevance_score": 1.0}]}
        ),
        lambda r: httpx.Response(400),
    ],
    ids=["short", "repeated", "out-of-range", "other-model", "no-model", "http-400"],
)
def test_a_bad_rerank_reply_is_refused(reply):
    http, _ = _client(reply)

    with pytest.raises(ProviderError):
        OpenRouterReranker(api_key="k", http=http, backoff_s=0.0).rerank(
            "q", ["a", "b"]
        )


def test_a_bare_model_name_in_the_reply_is_accepted():
    http, _ = _client(
        _rerank_reply(
            [
                {"index": 0, "relevance_score": 0.2},
                {"index": 1, "relevance_score": 0.4},
            ],
            model="rerank-2.5-lite",
        )
    )

    ranked = OpenRouterReranker(api_key="k", http=http).rerank("q", ["a", "b"])

    assert ranked == [(1, 0.4), (0, 0.2)]
