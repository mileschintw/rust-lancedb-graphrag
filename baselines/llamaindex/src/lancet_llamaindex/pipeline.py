"""The LlamaIndex paper configuration, ending in a context export (D-248).

`SentenceSplitter(256, 25)` chunks the documents, a `VectorStoreIndex` in memory
retrieves the dense top 20, and `VoyageRerankPostprocessor` reranks them through the
same `voyageai/rerank-2.5-lite` endpoint as Lancet's rerank client and keeps 8. The
pipeline stops there: it never builds a query engine or calls a reader. The reader
step is the engine's generate-only bin, shared with Lancet's arms (D-247).

Each question becomes one context-export row, checked with the harness's own
`validate_row`, and `write_outputs` writes the rows plus a pipeline-config echo only
when every row passes `read_export`. A question whose reranked list is shorter than
8 fails the export, because k = 8 is fixed across arms (fairness rule 3).

Chunk IDs are `<document ID>#<chunk index>`, so a rebuild gives the same IDs and the
same `index_fingerprint`.

`Pipeline.persist` writes the index and an `index_manifest.json` to a directory, and
`Pipeline.load` reads them back (#146): the documents are embedded once, by
`lancet-llamaindex build`, and an export over a loaded index embeds only its questions.
`load` splits the current documents again (free) and refuses an index whose manifest
does not match them.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol

from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    ContextExportError,
    read_export,
    validate_row,
)
from lancet_eval.corpus import GoldQuestion
from lancet_eval.evidence_meta import normalise
from llama_index.core import (
    Document,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import BaseNode, MetadataMode, NodeWithScore, QueryBundle
from pydantic import Field

from lancet_llamaindex.corpus import EMBEDDED_METADATA_KEYS
from lancet_llamaindex.providers import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_ENDPOINT,
    EMBEDDING_MODEL,
    RERANK_ENDPOINT,
    RERANK_MODEL,
)

PIPELINE_CONFIG_FILE = "pipeline_config.json"
#: What `Pipeline.persist` writes beside the index files (#146).
INDEX_MANIFEST_FILE = "index_manifest.json"

CHUNK_SIZE = 256
CHUNK_OVERLAP = 25
DENSE_TOP_K = 20
KEEP = 8
#: What every export entry's `content_type` says: the articles are plain text, as
#: `lancet-eval seed` uploads them.
CONTENT_TYPE = "text/plain"


class ExportError(Exception):
    """The export cannot be built or a row breaks the context-export contract."""


class IndexMismatchError(ExportError):
    """A persisted index is missing, or was built from other chunks or settings."""


class Reranker(Protocol):
    """Scores documents against a query."""

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        """`(index into documents, relevance score)` pairs, best first."""
        ...


class VoyageRerankPostprocessor(BaseNodePostprocessor):
    """Reranks the retrieved nodes with a `Reranker` and keeps the best `top_n`.

    The reranker sees each node's chunk text only, with no metadata header, as
    Lancet's rerank client sends `candidate.content` (fairness rule 5: the difference
    stays in Lancet's hybrid retrieval and graph, not in what the reranker reads).
    """

    reranker: Any = Field(description="A Reranker; the OpenRouter client or a stub.")
    top_n: int = KEEP

    @classmethod
    def class_name(cls) -> str:
        return "VoyageRerankPostprocessor"

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: QueryBundle | None = None,
    ) -> list[NodeWithScore]:
        if query_bundle is None:
            raise ValueError("reranking needs a query")
        if not nodes:
            return []
        texts = [n.node.get_content(metadata_mode=MetadataMode.NONE) for n in nodes]
        ranked = self.reranker.rerank(query_bundle.query_str, texts)
        indices = [index for index, _ in ranked]
        if len(set(indices)) != len(indices) or any(
            not 0 <= i < len(nodes) for i in indices
        ):
            raise ValueError(f"reranker returned bad indices {indices}")
        return [
            NodeWithScore(node=nodes[index].node, score=score)
            for index, score in ranked[: self.top_n]
        ]


def _chunk_id(i: int, doc: BaseNode) -> str:
    return f"{doc.node_id}#{i}"


def _evidence(rank: int, scored: NodeWithScore) -> dict[str, Any]:
    node = scored.node
    meta = normalise(node.metadata)
    return {
        "rank": rank,
        "chunk_id": node.node_id,
        "document_id": node.ref_doc_id,
        "text": node.get_content(metadata_mode=MetadataMode.NONE),
        "title": meta["doc_title"],
        "section_path": None,
        "content_type": CONTENT_TYPE,
        "score": scored.score,
        "suspicious": False,
        "document_metadata": meta,
    }


def _split(documents: Sequence[Document]) -> list[BaseNode]:
    splitter = SentenceSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, id_func=_chunk_id
    )
    return splitter.get_nodes_from_documents(list(documents))


def _fingerprint(nodes: Sequence[BaseNode]) -> str:
    digest = hashlib.sha256()
    for node in nodes:
        embedded = node.get_content(metadata_mode=MetadataMode.EMBED)
        record = [node.node_id, node.ref_doc_id, embedded]
        digest.update(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _manifest(nodes: Sequence[BaseNode]) -> dict[str, Any]:
    """What a persisted index must match before an export reads it (#146)."""
    return {
        "framework_version": version("llama-index-core"),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "embedded_metadata_keys": list(EMBEDDED_METADATA_KEYS),
        "documents": len({node.ref_doc_id for node in nodes}),
        "chunks": len(nodes),
        "index_fingerprint": _fingerprint(nodes),
    }


class Pipeline:
    """An index over the documents plus the retriever and reranker that read it."""

    def __init__(
        self,
        nodes: list[BaseNode],
        index: VectorStoreIndex,
        embed_model: BaseEmbedding,
        reranker: Reranker,
    ) -> None:
        self._nodes = nodes
        self._index = index
        self._embed_model = embed_model
        self._reranker = reranker
        self._retriever = index.as_retriever(similarity_top_k=DENSE_TOP_K)
        self._postprocessor = VoyageRerankPostprocessor(reranker=reranker, top_n=KEEP)

    @classmethod
    def build(
        cls,
        documents: Sequence[Document],
        *,
        embed_model: BaseEmbedding,
        reranker: Reranker,
    ) -> Pipeline:
        """Chunks and embeds `documents` into an in-memory vector index."""
        nodes = _split(documents)
        index = VectorStoreIndex(nodes, embed_model=embed_model)
        return cls(nodes, index, embed_model, reranker)

    @classmethod
    def load(
        cls,
        documents: Sequence[Document],
        index_dir: Path,
        *,
        embed_model: BaseEmbedding,
        reranker: Reranker,
    ) -> Pipeline:
        """Loads the index `persist` wrote for `documents`; embeds no document.

        Raises `IndexMismatchError` when `index_dir` has no manifest, or its manifest
        is not the one these documents and this configuration would write.
        """
        nodes = _split(documents)
        manifest_path = index_dir / INDEX_MANIFEST_FILE
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise IndexMismatchError(f"{manifest_path}: {exc}") from exc
        expected = _manifest(nodes)
        wrong = sorted(
            key
            for key in {*manifest, *expected}
            if manifest.get(key) != expected.get(key)
        )
        if wrong:
            raise IndexMismatchError(
                f"{manifest_path} differs from the current documents and "
                f"configuration in {wrong}; rebuild the index"
            )
        storage = StorageContext.from_defaults(persist_dir=str(index_dir))
        index = load_index_from_storage(storage, embed_model=embed_model)
        return cls(nodes, index, embed_model, reranker)

    def persist(self, index_dir: Path) -> Path:
        """Writes the index and its manifest into `index_dir`; returns the manifest."""
        index_dir.mkdir(parents=True, exist_ok=True)
        self._index.storage_context.persist(persist_dir=str(index_dir))
        manifest_path = index_dir / INDEX_MANIFEST_FILE
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(_manifest(self._nodes), f, indent=2)
            f.write("\n")
        return manifest_path

    def chunk_ids(self) -> list[str]:
        return [node.node_id for node in self._nodes]

    def index_fingerprint(self) -> str:
        """SHA-256 over every chunk's ID, document ID and embedded text."""
        return _fingerprint(self._nodes)

    def export_row(self, corpus: str, arm: str, question: GoldQuestion) -> dict:
        """One question's context-export row; raises `ExportError` naming it."""
        unit = f"{question.question_id}/{arm}"
        retrieved = self._retriever.retrieve(question.question)
        try:
            kept = self._postprocessor.postprocess_nodes(
                retrieved, query_str=question.question
            )
        except ValueError as exc:
            raise ExportError(f"{unit}: {exc}") from exc
        if len(kept) != KEEP:
            raise ExportError(
                f"{unit}: {len(kept)} reranked entries from {len(retrieved)} "
                f"retrieved, need exactly {KEEP}"
            )
        row = {
            "corpus": corpus,
            "question_id": question.question_id,
            "arm": arm,
            "question": question.question,
            "evidence": [_evidence(rank, n) for rank, n in enumerate(kept, 1)],
            "graph_facts": [],
        }
        try:
            validate_row(row)
        except ContextExportError as exc:
            raise ExportError(f"{unit}: {exc}") from exc
        return row

    def export_rows(
        self, corpus: str, arm: str, questions: Iterable[GoldQuestion]
    ) -> list[dict]:
        return [self.export_row(corpus, arm, q) for q in questions]

    def config_echo(self) -> dict[str, Any]:
        """The pipeline-config echo the harness compares with the pre-registration."""
        return {
            "framework": "llama-index-core",
            "framework_version": version("llama-index-core"),
            # Flat copies of the nested values: the keys the harness's external
            # clause compares with the pre-registration (#12, #14).
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "rerank_model": RERANK_MODEL,
            "splitter": {
                "type": "SentenceSplitter",
                "chunk_size": CHUNK_SIZE,
                "chunk_overlap": CHUNK_OVERLAP,
                "tokenizer": "tiktoken gpt-3.5-turbo (LlamaIndex default)",
            },
            "dense_top_k": DENSE_TOP_K,
            "embedding": {
                "model": EMBEDDING_MODEL,
                # The endpoint the provider sent to, which an override (#76) changes.
                "endpoint": getattr(self._embed_model, "endpoint", EMBEDDING_ENDPOINT),
                "dimensions": EMBEDDING_DIMENSIONS,
                "input_type": None,
                "class": self._embed_model.class_name(),
            },
            "embedded_metadata_keys": list(EMBEDDED_METADATA_KEYS),
            "rerank": {
                "model": RERANK_MODEL,
                "endpoint": getattr(self._reranker, "endpoint", RERANK_ENDPOINT),
                "document_text": "chunk text only (MetadataMode.NONE), as Lancet sends",
                "class": type(self._reranker).__name__,
            },
            "keep": KEEP,
            "documents": len({node.ref_doc_id for node in self._nodes}),
            "chunks": len(self._nodes),
            "index_fingerprint": self.index_fingerprint(),
        }


def write_outputs(
    out_dir: Path, rows: Sequence[Mapping[str, Any]], echo: Mapping[str, Any]
) -> tuple[Path, Path]:
    """Writes `context_export.jsonl` and `pipeline_config.json` into `out_dir`.

    The rows are written to a temporary file and read back with the harness's
    `read_export` first; on any failure nothing is written and `ExportError` is raised.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    tmp_export = out_dir / f".{CONTEXT_EXPORT_FILE}.tmp.{stamp}"
    tmp_echo = out_dir / f".{PIPELINE_CONFIG_FILE}.tmp.{stamp}"
    export_path = out_dir / CONTEXT_EXPORT_FILE
    echo_path = out_dir / PIPELINE_CONFIG_FILE
    try:
        with open(tmp_export, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        try:
            read_export(tmp_export)
        except (ContextExportError, ValueError) as exc:
            raise ExportError(str(exc)) from exc
        with open(tmp_echo, "w", encoding="utf-8", newline="\n") as f:
            json.dump(echo, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_export, export_path)
        os.replace(tmp_echo, echo_path)
    finally:
        tmp_export.unlink(missing_ok=True)
        tmp_echo.unlink(missing_ok=True)
    return export_path, echo_path
