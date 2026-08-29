"""Evaluation store seeding and document mapping."""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.config import EvalSettings, load_settings, repo_root
from lancet_eval.corpus import load_corpus

if TYPE_CHECKING:
    import httpx


class SeedError(Exception):
    """Raised when seeding fails or is blocked by an isolation error."""


class DocumentMapEntry(BaseModel):
    """Mapping from a gateway document_id to a benchmark corpus article."""

    model_config = ConfigDict(extra="ignore")

    corpus_id: str
    document_id: str
    title: str = ""
    url: str = ""


class DocumentMap(BaseModel):
    """Committed document map capturing seed-time IDs and index generation."""

    model_config = ConfigDict(extra="ignore")

    corpus: str
    seeded_at: str = ""
    index_generation: str = ""
    entries: dict[str, DocumentMapEntry] = Field(default_factory=dict)

    def get_by_document_id(self, doc_id: str) -> DocumentMapEntry:
        """Resolve gateway document_id to its corpus entry, raising if unmapped."""
        if doc_id not in self.entries:
            raise KeyError(
                f"Document ID {doc_id!r} not found in map for corpus {self.corpus!r}"
            )
        return self.entries[doc_id]

    def get_by_corpus_id(self, corpus_id: str) -> DocumentMapEntry | None:
        """Find entry by corpus article identifier."""
        for entry in self.entries.values():
            if entry.corpus_id == corpus_id:
                return entry
        return None


def get_document_map_path(corpus_name: str) -> Path:
    """Return the absolute path to a corpus's document_map.json."""
    return repo_root() / "eval" / "corpora" / corpus_name / "document_map.json"


def load_document_map(corpus_name: str) -> DocumentMap:
    """Load the committed document map for a corpus."""
    path = get_document_map_path(corpus_name)
    if not path.is_file():
        raise SeedError(f"Document map not found at {path}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    entries = {k: DocumentMapEntry(**v) for k, v in data.get("entries", {}).items()}
    return DocumentMap(
        corpus=data.get("corpus", corpus_name),
        seeded_at=data.get("seeded_at", ""),
        index_generation=data.get("index_generation", ""),
        entries=entries,
    )


def save_document_map_atomic(doc_map: DocumentMap) -> None:
    """Atomically write the document map to disk."""
    path = get_document_map_path(doc_map.corpus)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")

    payload = {
        "corpus": doc_map.corpus,
        "seeded_at": doc_map.seeded_at,
        "index_generation": doc_map.index_generation,
        "entries": {k: v.model_dump() for k, v in sorted(doc_map.entries.items())},
    }

    with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    tmp_path.replace(path)


def _sanitize_filename(name: str) -> str:
    """Sanitize string for multipart filename header."""
    clean = re.sub(r"[^\w\-_.]", "_", name.strip())
    if not clean:
        clean = "doc"
    return clean[:60] + ".txt"


def seed_corpus(
    corpus_name: str,
    client: httpx.Client | None = None,
    settings: EvalSettings | None = None,
) -> DocumentMap:
    """Seed documents for a corpus into the isolated evaluation store."""
    import httpx

    settings = settings or load_settings()
    _ = load_corpus(corpus_name)
    subset_path = (
        repo_root() / "eval" / "corpora" / corpus_name / "documents.subset.jsonl"
    )

    if not subset_path.is_file():
        raise SeedError(
            f"Documents subset not found at {subset_path}. "
            "Run 'lancet-eval corpus sample' first."
        )

    # Load existing map for resume capability
    try:
        doc_map = load_document_map(corpus_name)
    except Exception:
        doc_map = DocumentMap(
            corpus=corpus_name,
            seeded_at=datetime.now(UTC).isoformat(),
            entries={},
        )

    documents: list[dict[str, Any]] = []
    with open(subset_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                documents.append(json.loads(line.strip()))

    should_close_client = False
    if client is None:
        client = httpx.Client(
            base_url=settings.gateway_url,
            timeout=settings.gateway_timeout_secs,
        )
        should_close_client = True

    try:
        total_docs = len(documents)
        for idx, doc in enumerate(documents):
            corpus_id = str(
                doc.get("title") or doc.get("url") or doc.get("id") or ""
            ).strip()
            if not corpus_id:
                continue

            # Skip if already mapped
            if doc_map.get_by_corpus_id(corpus_id) is not None:
                continue

            title = str(doc.get("title", "")).strip()
            url = str(doc.get("url", "")).strip()
            body_text = str(
                doc.get("text") or doc.get("body") or doc.get("content") or ""
            )

            # Check 10MB ceiling
            content_bytes = body_text.encode("utf-8")
            if len(content_bytes) > 10 * 1024 * 1024:
                continue

            # Multipart file upload without chunk_size / chunk_overlap overrides
            safe_name = _sanitize_filename(corpus_id)
            files = {
                "file": (safe_name, content_bytes, "text/plain"),
            }

            resp = client.post("/documents", files=files)
            if resp.status_code not in (200, 201, 202):
                raise SeedError(
                    f"Upload failed for article '{corpus_id}' "
                    f"(HTTP {resp.status_code}): {resp.text}"
                )

            data = resp.json()
            gw_doc_id = str(data.get("id") or data.get("ID") or "")
            if not gw_doc_id:
                raise SeedError(f"No document id returned for article '{corpus_id}'")

            # Poll for completion if status is not completed
            status = str(data.get("status") or data.get("Status") or "")
            max_poll_time = 300.0
            start_poll = time.monotonic()
            poll_interval = 0.5

            while status not in ("completed", "failed"):
                if time.monotonic() - start_poll > max_poll_time:
                    raise SeedError(
                        f"Timed out polling '{gw_doc_id}' for '{corpus_id}'"
                    )
                time.sleep(poll_interval)
                poll_interval = min(2.0, poll_interval * 1.5)

                poll_resp = client.get(f"/documents/{gw_doc_id}")
                if poll_resp.status_code == 200:
                    poll_data = poll_resp.json()
                    status = str(
                        poll_data.get("status") or poll_data.get("Status") or ""
                    )
                    if status == "failed":
                        err = (
                            poll_data.get("error_message")
                            or poll_data.get("ErrorMessage")
                            or "unknown error"
                        )
                        raise SeedError(
                            f"Ingestion failed for '{corpus_id}' "
                            f"(document '{gw_doc_id}'): {err}"
                        )
                elif poll_resp.status_code == 404:
                    time.sleep(0.5)

            # Record entry and save incrementally
            doc_map.entries[gw_doc_id] = DocumentMapEntry(
                corpus_id=corpus_id,
                document_id=gw_doc_id,
                title=title,
                url=url,
            )
            save_document_map_atomic(doc_map)

            if (idx + 1) % 10 == 0 or (idx + 1) == total_docs:
                print(
                    f"[{corpus_name}] Seeded {idx + 1}/{total_docs} articles "
                    f"({len(doc_map.entries)} mapped)",
                    flush=True,
                )

        # Issue throwaway query to extract index_generation
        query_resp = client.post("/rag/query", json={"query": "ping index generation"})
        if query_resp.status_code == 200:
            for line in query_resp.text.splitlines():
                if line.startswith("data:"):
                    try:
                        event_data = json.loads(line[5:].strip())
                        snap = event_data.get("snapshot") or (
                            event_data.get("final_response", {}).get("snapshot")
                        )
                        if snap and snap.get("index_generation"):
                            doc_map.index_generation = snap["index_generation"]
                            save_document_map_atomic(doc_map)
                            break
                    except Exception:
                        pass
    finally:
        if should_close_client:
            client.close()

    return doc_map


def reseed_corpus(
    corpus_name: str,
    confirmation: bool = False,
    client: httpx.Client | None = None,
    settings: EvalSettings | None = None,
) -> DocumentMap:
    """Drop the eval store and re-seed from scratch."""
    if not confirmation:
        raise SeedError(
            "Reseeding is destructive and clears the evaluation store. "
            "Pass confirmation=True (--confirm) to proceed."
        )

    settings = settings or load_settings()

    # Verify store isolation before destroying anything
    eval_lance = Path(settings.lancedb_path).resolve()
    dev_lance = Path(settings.dev_lancedb_path).resolve()
    if eval_lance == dev_lance:
        raise SeedError(
            f"Eval LanceDB path '{eval_lance}' equals dev path '{dev_lance}'. Aborting."
        )

    # Clean eval LanceDB directory
    if eval_lance.exists():
        shutil.rmtree(eval_lance, ignore_errors=True)

    # Delete existing document map
    map_path = get_document_map_path(corpus_name)
    if map_path.is_file():
        map_path.unlink()

    return seed_corpus(corpus_name, client=client, settings=settings)
