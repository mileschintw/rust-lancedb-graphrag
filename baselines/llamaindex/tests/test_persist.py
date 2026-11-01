"""#146: the index is built once, persisted, and loaded by a later export.

A loaded index answers exactly as the one built in memory, embeds no document text,
and is refused when its chunks are not the ones the current documents split into.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lancet_llamaindex.corpus import load_documents
from lancet_llamaindex.pipeline import (
    INDEX_MANIFEST_FILE,
    IndexMismatchError,
    Pipeline,
)

from .conftest import HashEmbedding
from .test_export import _questions


class _QueryOnlyEmbedding(HashEmbedding):
    """Embeds queries only: a loaded index must never embed a document again."""

    def _get_text_embedding(self, text: str) -> list[float]:
        raise AssertionError(f"embedded a document text: {text[:40]!r}")


def _documents(corpus_dir: Path):
    return load_documents(
        corpus_dir / "documents.jsonl", corpus_dir / "document_map.json"
    )


def _persisted(corpus_dir: Path, index_dir: Path, embedding, reranker) -> Pipeline:
    built = Pipeline.build(
        _documents(corpus_dir), embed_model=embedding, reranker=reranker
    )
    built.persist(index_dir)
    return built


def test_a_loaded_index_exports_the_rows_of_the_built_one(
    corpus_dir, tmp_path, embedding, reranker
):
    built = _persisted(corpus_dir, tmp_path / "index", embedding, reranker)

    loaded = Pipeline.load(
        _documents(corpus_dir),
        tmp_path / "index",
        embed_model=_QueryOnlyEmbedding(seen_texts=[], seen_queries=[]),
        reranker=reranker,
    )

    questions = _questions(corpus_dir)
    assert loaded.export_rows("fixture", "llamaindex", questions) == (
        built.export_rows("fixture", "llamaindex", questions)
    )
    assert loaded.index_fingerprint() == built.index_fingerprint()
    assert loaded.chunk_ids() == built.chunk_ids()


def test_the_manifest_records_the_index_identity(
    corpus_dir, tmp_path, embedding, reranker
):
    built = _persisted(corpus_dir, tmp_path / "index", embedding, reranker)

    manifest = json.loads((tmp_path / "index" / INDEX_MANIFEST_FILE).read_text())

    echo = built.config_echo()
    assert manifest["index_fingerprint"] == echo["index_fingerprint"]
    assert manifest["chunks"] == echo["chunks"]
    assert manifest["documents"] == echo["documents"] == 3
    assert manifest["embedding_model"] == echo["embedding"]["model"]
    assert manifest["embedding_dimensions"] == echo["embedding"]["dimensions"]


def test_an_index_of_other_documents_is_refused(
    corpus_dir, tmp_path, embedding, reranker
):
    _persisted(corpus_dir, tmp_path / "index", embedding, reranker)

    with pytest.raises(IndexMismatchError, match="index_fingerprint"):
        Pipeline.load(
            _documents(corpus_dir)[:2],
            tmp_path / "index",
            embed_model=embedding,
            reranker=reranker,
        )


def test_a_directory_with_no_manifest_is_refused(corpus_dir, tmp_path, embedding):
    (tmp_path / "index").mkdir()

    with pytest.raises(IndexMismatchError, match=INDEX_MANIFEST_FILE):
        Pipeline.load(
            _documents(corpus_dir),
            tmp_path / "index",
            embed_model=embedding,
            reranker=None,
        )
