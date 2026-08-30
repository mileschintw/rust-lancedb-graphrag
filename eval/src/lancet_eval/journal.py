"""Append-only evaluation run journal and resume key management."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.client import (
    NodeFailed,
    Notice,
    RetrievalSnapshot,
    StructuredCitation,
)


class RunRecord(BaseModel):
    """Durable record of a single question execution under one experimental arm."""

    model_config = ConfigDict(extra="forbid")

    corpus: str
    question_id: str
    graph_arm: str
    outcome: Literal["success", "error"]
    answer: str | None = None
    snapshot: RetrievalSnapshot | None = None
    structured_citations: list[StructuredCitation] = Field(default_factory=list)
    notices: list[Notice] = Field(default_factory=list)
    node_failures: list[NodeFailed] = Field(default_factory=list)
    duration_ms: float = 0.0
    session_id: str = ""
    correlation_id: str = ""
    index_generation: str = ""
    partial: bool = False
    error_type: str | None = None
    error: str | None = None


def journal_key(corpus: str, question_id: str, graph_arm: str) -> str:
    """Generate the durable resume key for a work unit."""
    return f"{corpus}:{question_id}:{graph_arm}"


def load_done(journal_path: Path | str) -> set[str]:
    """Load the set of already recorded work unit keys from a journal file.

    Skips any half-written or unparseable trailing lines so interrupted work units
    are re-driven rather than treated as done.
    """
    path = Path(journal_path)
    done: set[str] = set()
    if not path.exists():
        return done

    with open(path, encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                if (
                    isinstance(data, dict)
                    and "corpus" in data
                    and "question_id" in data
                    and "graph_arm" in data
                ):
                    rec = RunRecord.model_validate(data)
                    done.add(journal_key(rec.corpus, rec.question_id, rec.graph_arm))
            except Exception:
                continue
    return done


class Journal:
    """Append-only thread-safe manager for JSONL evaluation records."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_header(self, *, corpus: str, partial: bool) -> None:
        """Write journal metadata header if file is empty or new."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            header = {
                "type": "header",
                "corpus": corpus,
                "partial": partial,
                "created_at": time.time(),
            }
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(header, ensure_ascii=False) + "\n")
                f.flush()

    def append(self, record: RunRecord) -> None:
        """Append one compact JSON record and immediately flush."""
        line = record.model_dump_json() + "\n"
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
