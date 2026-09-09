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


class NodeTiming(BaseModel):
    """Durable record of completed node timing."""

    model_config = ConfigDict(extra="forbid")
    node_name: str
    duration_ms: float


class WorkflowWireMeta(BaseModel):
    """Durable record of workflow execution metadata from wire."""

    model_config = ConfigDict(extra="forbid")
    started_at_ms: int = 0
    completed_at_ms: int = 0
    reformulation_used: bool = False
    vector_count: int = 0
    bm25_count: int = 0
    graph_node_count: int = 0
    graph_edge_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    degraded_mode: bool = False
    graph_prompt_fact_count: int | None = None


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
    node_timings: list[NodeTiming] = Field(default_factory=list)
    workflow_meta: WorkflowWireMeta | None = None


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


def load_records(journal_path: Path | str) -> list[RunRecord]:
    """Load the list of RunRecord objects from a journal file.

    Skips header lines and any half-written or unparseable lines exactly
    as load_done does, guaranteeing consistency between the resume key set
    and the loaded record objects.
    """
    path = Path(journal_path)
    records: list[RunRecord] = []
    if not path.exists():
        return records

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
                    records.append(rec)
            except Exception:
                continue
    return records


def completeness_comparison(
    journal_path: Path | str, corpus: str
) -> tuple[bool, set[str]]:
    """Compare journal work units against the full cross-product of sample questions and arms.

    Delegates to load_done() to ensure consistency with the resume predicate.
    Returns (is_complete, missing_keys).
    """
    from lancet_eval.corpus import load_corpus_config, load_sample_questions

    config = load_corpus_config(corpus)
    questions = load_sample_questions(corpus)

    expected_keys = {
        journal_key(corpus, q.id, arm)
        for q in questions
        for arm in config.arms
    }

    done_keys = load_done(journal_path)
    missing = expected_keys - done_keys
    return len(missing) == 0, missing


def reconcile_header(
    journal_path: Path | str, corpus: str
) -> tuple[bool, str]:
    """Reconcile a journal header from partial to publishable when complete.

    Conditioned on completeness_comparison. If incomplete, makes no change.
    Rewrites ONLY the header line (clearing partial: false), preserving all record lines byte-identical.
    Uses an atomic write via temporary file beside the journal.
    """
    import os

    path = Path(journal_path)
    if not path.is_file():
        return False, f"Journal file does not exist: {path}"

    is_complete, missing = completeness_comparison(path, corpus)
    if not is_complete:
        return False, f"Journal is incomplete: missing {len(missing)} work unit(s)"

    # Read all lines
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if not lines:
        return False, "Journal file is empty"

    header_line = lines[0].strip()
    try:
        header_data = json.loads(header_line)
    except Exception as e:
        return False, f"Failed to parse journal header: {e}"

    if not isinstance(header_data, dict) or header_data.get("type") != "header":
        return False, "First line of journal is not a valid header"

    if not header_data.get("partial", False):
        return True, "Journal is already publishable (partial is False); no-op"

    header_data["partial"] = False
    new_header_line = json.dumps(header_data, ensure_ascii=False) + "\n"

    # Write atomically via temp file in same directory
    tmp_path = path.parent / f".{path.name}.tmp.{time.time_ns()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(new_header_line)
            for rec_line in lines[1:]:
                f.write(rec_line)
            f.flush()
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    return True, "Successfully reconciled journal header to publishable"


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
