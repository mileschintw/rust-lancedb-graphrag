"""Seam S-E fixtures: a three-document corpus with stubbed embedding and rerank.

Nothing here touches the network or needs an API key. The documents use the raw
MultiHop-RAG row shape (`title`, `source`, `published_at`, `body`, ...) and the
document map uses the shape `lancet-eval seed` writes, so the loaders run unchanged.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pytest
from llama_index.core.embeddings import BaseEmbedding

DOCS = [
    {
        "id": "doc-acme-0000-0000-000000000001",
        "title": "Acme&#039;s quarterly results",
        "source": "Business Wire",
        "published_at": "2023-10-07T15:37:43+00:00",
        "topic": "Acme widgets revenue",
    },
    {
        "id": "doc-globex-000-0000-000000000002",
        "title": "Globex opens a new plant",
        "source": "The Verge",
        "published_at": "2023-11-02T08:00:00-05:00",
        "topic": "Globex factory workers",
    },
    {
        "id": "doc-initech-00-0000-000000000003",
        "title": "Initech settles its lawsuit",
        "source": "Reuters",
        "published_at": "2023-12-15",
        "topic": "Initech lawsuit settlement",
    },
]

QUESTIONS = [
    {"query_id": "q-1", "query": "How did Acme widgets revenue change?"},
    {"query_id": "q-2", "query": "How many Globex factory workers were hired?"},
    {"query_id": "q-3", "query": "What did the Initech lawsuit settlement cost?"},
]


def _body(topic: str) -> str:
    """About 2,000 tokens of distinct sentences, so each document splits into chunks."""
    paragraphs = []
    for p in range(12):
        sentences = [
            f"Report {p}.{s} on {topic} records figure {p * 31 + s * 7} "
            f"for the period, and analysts compared it with prior quarters."
            for s in range(8)
        ]
        paragraphs.append(" ".join(sentences))
    return "\n\n".join(paragraphs)


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
    """Writes `documents.jsonl`, `document_map.json` and `questions.jsonl`."""
    with open(tmp_path / "documents.jsonl", "w", encoding="utf-8") as f:
        for doc in DOCS:
            row = {
                "title": doc["title"],
                "author": "Staff",
                "source": doc["source"],
                "published_at": doc["published_at"],
                "category": "business",
                "url": f"https://example.test/{doc['id']}",
                "body": _body(doc["topic"]),
            }
            f.write(json.dumps(row) + "\n")
    entries = {
        doc["id"]: {
            "corpus_id": doc["title"],
            "document_id": doc["id"],
            "title": doc["title"],
            "url": f"https://example.test/{doc['id']}",
        }
        for doc in DOCS
    }
    doc_map = {"corpus": "fixture", "index_generation": "lance-1", "entries": entries}
    with open(tmp_path / "document_map.json", "w", encoding="utf-8") as f:
        json.dump(doc_map, f)
    with open(tmp_path / "questions.jsonl", "w", encoding="utf-8") as f:
        for q in QUESTIONS:
            f.write(json.dumps(q) + "\n")
    return tmp_path


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class HashEmbedding(BaseEmbedding):
    """A bag-of-words hash embedding: offline, deterministic, roughly topical.

    Records every text it embeds so tests can see what LlamaIndex sent.
    """

    dim: int = 64
    seen_texts: list[str] = []
    seen_queries: list[str] = []

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in _words(text):
            vec[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _get_query_embedding(self, query: str) -> list[float]:
        self.seen_queries.append(query)
        return self._vector(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        self.seen_texts.append(text)
        return self._vector(text)


class OverlapReranker:
    """Scores each document by word overlap with the query; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        self.calls.append((query, list(documents)))
        q = set(_words(query))
        scored = [
            (i, len(q & set(_words(d))) / (len(q) or 1))
            for i, d in enumerate(documents)
        ]
        return sorted(scored, key=lambda pair: (-pair[1], pair[0]))


@pytest.fixture
def embedding() -> HashEmbedding:
    return HashEmbedding(seen_texts=[], seen_queries=[])


@pytest.fixture
def reranker() -> OverlapReranker:
    return OverlapReranker()
