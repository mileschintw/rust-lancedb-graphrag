"""Loads the documents Lancet seeds as LlamaIndex `Document`s (D-248).

The rows are the raw MultiHop-RAG articles the corpus names, the same file
`lancet-eval seed` uploads: `documents.subset.jsonl` for the 346-document subset, or
the dataset's cached `corpus.json` for all 609 articles (#146). Each one is matched to
its Lancet document ID through the store's committed document map, by the same corpus
ID the seeder records (the article's title, else its URL or ID), so the export's
document IDs pass the harness's document-map check. A row with no map entry fails the
load: the baseline indexes the same documents as Lancet or none.

The paper's three metadata keys, `title`, `source` and `published_at`, go into the
document metadata with their raw values, and LlamaIndex embeds them with the text by
default. Every other key (author, URL, category) is left out.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from lancet_eval.seed import DocumentMap
from lancet_eval.split import lf_sha256
from llama_index.core import Document

#: The metadata keys embedded with the text, as in the MultiHop-RAG paper.
EMBEDDED_METADATA_KEYS = ("title", "source", "published_at")


class CorpusLoadError(Exception):
    """The documents or the document map cannot be read, or they do not match."""


def _corpus_id(row: dict) -> str:
    # The same key `lancet_eval.seed.seed_corpus` maps an article by.
    return str(row.get("title") or row.get("url") or row.get("id") or "").strip()


def _rows(documents_path: Path, sha256: str | None) -> Iterator[tuple[str, dict]]:
    """Each article row with where it sits: a JSONL line, or a `.json` array item.

    The full MultiHop-RAG corpus is the dataset's cached `corpus.json` array (#146),
    pinned by its LF-normalised sha256 as `lancet-eval seed` pins it.
    """
    if sha256 is not None:
        actual = lf_sha256(documents_path)
        if actual != sha256:
            raise CorpusLoadError(
                f"{documents_path} hashes to {actual[:12]}, not the corpus's pinned "
                f"{sha256[:12]}"
            )
    if documents_path.suffix == ".json":
        rows = json.loads(documents_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise CorpusLoadError(f"{documents_path} is not a JSON array")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise CorpusLoadError(
                    f"{documents_path} item {index}: a row must be a JSON object"
                )
            yield f"item {index}", row
        return
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
            yield f"line {line_num}", row


def load_documents(
    documents_path: Path, document_map_path: Path, sha256: str | None = None
) -> list[Document]:
    """Reads every article as a `Document` whose ID is its Lancet document ID.

    `documents_path` is a JSONL file or a `.json` array; with `sha256` it must hash to
    that pin. Raises `CorpusLoadError` for an unreadable map or row, a file off its
    pin, and a row with no map entry, a repeated document or no body.
    """
    try:
        with open(document_map_path, encoding="utf-8") as f:
            doc_map = DocumentMap.model_validate(json.load(f))
    except (OSError, ValueError) as exc:
        raise CorpusLoadError(f"{document_map_path}: {exc}") from exc
    by_corpus_id = {e.corpus_id: e.document_id for e in doc_map.entries.values()}
    documents: list[Document] = []
    seen: set[str] = set()
    try:
        rows = list(_rows(documents_path, sha256))
    except (OSError, ValueError) as exc:
        raise CorpusLoadError(f"{documents_path}: {exc}") from exc
    for where, row in rows:
        corpus_id = _corpus_id(row)
        document_id = by_corpus_id.get(corpus_id)
        if document_id is None:
            raise CorpusLoadError(
                f"{documents_path} {where}: article {corpus_id!r} has no "
                f"entry in {document_map_path}"
            )
        if document_id in seen:
            raise CorpusLoadError(
                f"{documents_path} {where}: document {document_id} appears twice"
            )
        body = str(row.get("text") or row.get("body") or row.get("content") or "")
        if not body.strip():
            raise CorpusLoadError(
                f"{documents_path} {where}: article {corpus_id!r} has no body"
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
