"""Loads the documents Lancet seeds as LlamaIndex `Document`s (D-248).

The rows are the raw MultiHop-RAG articles in `documents.subset.jsonl`, the same file
`lancet-eval seed` uploads. Each one is matched to its Lancet document ID through the
committed `document_map.json`, by the same corpus ID the seeder records (the article's
title, else its URL or ID), so the export's document IDs pass the harness's
document-map check. A row with no map entry fails the load: the baseline indexes the
same documents as Lancet or none.

The paper's three metadata keys, `title`, `source` and `published_at`, go into the
document metadata with their raw values, and LlamaIndex embeds them with the text by
default. Every other key (author, URL, category) is left out.
"""

from __future__ import annotations

import json
from pathlib import Path

from lancet_eval.seed import DocumentMap
from llama_index.core import Document

#: The metadata keys embedded with the text, as in the MultiHop-RAG paper.
EMBEDDED_METADATA_KEYS = ("title", "source", "published_at")


class CorpusLoadError(Exception):
    """The documents or the document map cannot be read, or they do not match."""


def _corpus_id(row: dict) -> str:
    # The same key `lancet_eval.seed.seed_corpus` maps an article by.
    return str(row.get("title") or row.get("url") or row.get("id") or "").strip()


def load_documents(documents_path: Path, document_map_path: Path) -> list[Document]:
    """Reads every article as a `Document` whose ID is its Lancet document ID.

    Raises `CorpusLoadError` for an unreadable map or row, and for a row with no map
    entry, a repeated document or no body.
    """
    try:
        with open(document_map_path, encoding="utf-8") as f:
            doc_map = DocumentMap.model_validate(json.load(f))
    except (OSError, ValueError) as exc:
        raise CorpusLoadError(f"{document_map_path}: {exc}") from exc
    by_corpus_id = {e.corpus_id: e.document_id for e in doc_map.entries.values()}
    documents: list[Document] = []
    seen: set[str] = set()
    with open(documents_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("a row must be a JSON object")
            except ValueError as exc:
                raise CorpusLoadError(
                    f"{documents_path} line {line_num}: {exc}"
                ) from exc
            corpus_id = _corpus_id(row)
            document_id = by_corpus_id.get(corpus_id)
            if document_id is None:
                raise CorpusLoadError(
                    f"{documents_path} line {line_num}: article {corpus_id!r} has no "
                    f"entry in {document_map_path}"
                )
            if document_id in seen:
                raise CorpusLoadError(
                    f"{documents_path} line {line_num}: document {document_id} "
                    "appears twice"
                )
            body = str(row.get("text") or row.get("body") or row.get("content") or "")
            if not body.strip():
                raise CorpusLoadError(
                    f"{documents_path} line {line_num}: article {corpus_id!r} has no "
                    "body"
                )
            seen.add(document_id)
            metadata = {key: row[key] for key in EMBEDDED_METADATA_KEYS if row.get(key)}
            documents.append(
                Document(
                    id_=document_id,
                    text=body,
                    metadata=metadata,
                    excluded_llm_metadata_keys=list(metadata),
                )
            )
    return documents
