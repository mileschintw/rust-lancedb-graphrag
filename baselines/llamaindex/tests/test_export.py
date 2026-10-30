"""Seam S-E: the LlamaIndex export passes the harness's own context-export validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, read_export
from lancet_eval.corpus import LABEL_ADAPTERS
from lancet_eval.evidence_meta import normalise

from lancet_llamaindex.corpus import CorpusLoadError, load_documents
from lancet_llamaindex.pipeline import (
    KEEP,
    PIPELINE_CONFIG_FILE,
    ExportError,
    Pipeline,
    write_outputs,
)

from .conftest import DOCS


def _questions(corpus_dir: Path):
    adapt = LABEL_ADAPTERS["multihop_rag"]
    with open(corpus_dir / "questions.jsonl", encoding="utf-8") as f:
        return [adapt(json.loads(line)) for line in f if line.strip()]


def _pipeline(corpus_dir: Path, embedding, reranker) -> Pipeline:
    documents = load_documents(
        corpus_dir / "documents.jsonl", corpus_dir / "document_map.json"
    )
    return Pipeline.build(documents, embed_model=embedding, reranker=reranker)


def _export(corpus_dir: Path, tmp_path: Path, embedding, reranker):
    pipeline = _pipeline(corpus_dir, embedding, reranker)
    rows = pipeline.export_rows("fixture", "llamaindex", _questions(corpus_dir))
    out = tmp_path / "out"
    write_outputs(out, rows, pipeline.config_echo())
    return pipeline, out


def test_export_passes_the_harness_validator_with_eight_entries(
    corpus_dir, tmp_path, embedding, reranker
):
    _, out = _export(corpus_dir, tmp_path, embedding, reranker)

    rows = read_export(out / CONTEXT_EXPORT_FILE)

    assert [(r.question_id, r.arm) for r in rows] == [
        ("q-1", "llamaindex"),
        ("q-2", "llamaindex"),
        ("q-3", "llamaindex"),
    ]
    for row in rows:
        assert len(row.evidence) == KEEP == 8
        assert row.corpus == "fixture"
        assert row.graph_facts == []
        assert row.assembled_prompt is None and row.correlation_id is None


def test_export_uses_lancet_document_ids_and_normalised_metadata(
    corpus_dir, tmp_path, embedding, reranker
):
    _, out = _export(corpus_dir, tmp_path, embedding, reranker)
    by_id = {d["id"]: d for d in DOCS}

    for row in read_export(out / CONTEXT_EXPORT_FILE):
        for entry in row.evidence:
            doc = by_id[entry.document_id]
            meta = normalise(doc)
            assert entry.document_metadata.model_dump() == meta
            assert entry.title == meta["doc_title"]
            # Metadata reaches the reader as document metadata, never in the text.
            assert doc["source"] not in entry.text
            assert "published_at" not in entry.text


def test_each_question_keeps_the_reranker_top_eight_in_order(
    corpus_dir, tmp_path, embedding, reranker
):
    _, out = _export(corpus_dir, tmp_path, embedding, reranker)

    rows = read_export(out / CONTEXT_EXPORT_FILE)

    calls = list(reranker.calls)
    assert len(calls) == len(rows)
    for row, (query, documents) in zip(rows, calls, strict=True):
        assert query == row.question
        assert len(documents) == 20  # dense top 20 goes to the reranker
        scores = [entry.score for entry in row.evidence]
        assert scores == sorted(scores, reverse=True)
        best = reranker.rerank(query, documents)[:KEEP]
        assert scores == [score for _, score in best]


def test_embedded_text_carries_title_source_and_published_at(
    corpus_dir, tmp_path, embedding, reranker
):
    _export(corpus_dir, tmp_path, embedding, reranker)

    for doc in DOCS:
        embedded = [t for t in embedding.seen_texts if doc["source"] in t]
        assert embedded, f"no embedded text names {doc['source']}"
        for text in embedded:
            assert f"title: {doc['title']}" in text
            assert f"published_at: {doc['published_at']}" in text
            assert "url:" not in text and "author:" not in text


def test_chunk_ids_are_stable_across_builds(corpus_dir, tmp_path, embedding, reranker):
    first = _pipeline(corpus_dir, embedding, reranker)
    second = _pipeline(corpus_dir, embedding, reranker)

    assert (
        first.config_echo()["index_fingerprint"]
        == (second.config_echo()["index_fingerprint"])
    )
    assert first.chunk_ids() == second.chunk_ids()


def test_fewer_than_eight_reranked_entries_fail_closed(corpus_dir, embedding):
    class ShortReranker:
        def rerank(self, query, documents):
            return [(0, 1.0), (1, 0.5)]

    pipeline = _pipeline(corpus_dir, embedding, ShortReranker())

    with pytest.raises(ExportError, match="q-1"):
        pipeline.export_rows("fixture", "llamaindex", _questions(corpus_dir))


def test_a_document_missing_from_the_map_fails_closed(corpus_dir):
    doc_map = json.loads((corpus_dir / "document_map.json").read_text("utf-8"))
    doc_map["entries"].pop(DOCS[1]["id"])
    (corpus_dir / "document_map.json").write_text(json.dumps(doc_map), "utf-8")

    with pytest.raises(CorpusLoadError, match="Globex"):
        load_documents(corpus_dir / "documents.jsonl", corpus_dir / "document_map.json")


def test_outputs_are_written_only_when_every_row_validates(tmp_path):
    bad = [{"corpus": "fixture", "question_id": "q-1", "arm": "llamaindex"}]

    with pytest.raises(ExportError):
        write_outputs(tmp_path / "out", bad, {"framework": "llama-index-core"})

    assert not (tmp_path / "out" / CONTEXT_EXPORT_FILE).exists()
    assert not (tmp_path / "out" / PIPELINE_CONFIG_FILE).exists()
