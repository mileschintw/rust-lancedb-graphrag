"""Contract-asserting SSE client for Lancet's /rag/query endpoint."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    import httpx


class StructuredCitation(BaseModel):
    """Structured citation representing a cited or retrieved evidence chunk."""

    model_config = ConfigDict(extra="ignore")
    chunk_id: str
    document_id: str
    title: str = ""
    section_path: str = ""
    excerpt: str = ""
    is_truncated: bool = False
    score: float = 0.0
    rank: int = 0
    content_type: str = ""


class Notice(BaseModel):
    """Execution notice emitted during query workflow execution."""

    model_config = ConfigDict(extra="ignore")
    code: str
    message: str
    severity: int = 0
    typed_code: int = 0


class DocumentFilter(BaseModel):
    """Filter applied to retrieval candidates."""

    model_config = ConfigDict(extra="ignore")
    document_ids: list[str] = Field(default_factory=list)
    content_types: list[str] = Field(default_factory=list)


class RetrievalSnapshot(BaseModel):
    """Retrieval state snapshot including the candidate result set."""

    model_config = ConfigDict(extra="ignore")
    index_generation: str = ""
    embedding_model: str = ""
    vector_weight: float = 0.0
    bm25_weight: float = 0.0
    rrf_k: int = 0
    candidate_limit: int = 0
    final_limit: int = 0
    active_filter: DocumentFilter | None = None
    result_hash: str = ""
    retrieved_chunks: list[StructuredCitation] = Field(default_factory=list)


class RagAnswer(BaseModel):
    """Final answer DTO corresponding to QueryRAGResponseDTO."""

    model_config = ConfigDict(extra="ignore")
    answer: str = ""
    citations: list[str] = Field(default_factory=list)
    session_id: str = ""
    answer_basis: int = 0
    structured_citations: list[StructuredCitation] = Field(default_factory=list)
    notices: list[Notice] = Field(default_factory=list)
    snapshot: RetrievalSnapshot | None = None


class NodeFailed(BaseModel):
    """Diagnostic event describing a failed node execution."""

    model_config = ConfigDict(extra="ignore")
    node_name: str
    error_kind: int
    error_message: str
    retryable: bool


class WorkflowCompleted(BaseModel):
    """Terminal event signalling end of workflow."""

    model_config = ConfigDict(extra="ignore")
    success: bool
    total_duration_ms: int = 0
    error_kind: int = 0
    error_message: str = ""
    final_response: RagAnswer | None = None
    notices: list[Notice] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _remap_duration(cls, data: object) -> object:
        if isinstance(data, dict):
            if "total_duration_ms" not in data and "duration_ms" in data:
                data["total_duration_ms"] = data["duration_ms"]
        return data


class StreamErrorFrame(BaseModel):
    """In-stream error frame."""

    model_config = ConfigDict(extra="ignore")
    code: str
    message: str


class HarnessStreamError(Exception):
    """Base exception for harness stream parsing failures."""


class PreStreamError(HarnessStreamError):
    """Raised on non-SSE 4xx/5xx responses before streaming starts."""


class StreamAborted(HarnessStreamError):
    """Raised when stream ends without terminal event or carries stream_error frame."""


class ContractViolation(HarnessStreamError):
    """Raised when SSE event sequence or frame shapes violate the wire contract."""


class StreamDeadlineExceeded(HarnessStreamError):
    """Raised when per-question wall-clock deadline is exceeded."""


class QueryOutcome(BaseModel):
    """Parsed and validated outcome of a RAG query execution."""

    model_config = ConfigDict(extra="ignore")
    status: Literal["ok", "degraded", "failed"]
    answer: RagAnswer | None
    completion: WorkflowCompleted
    notices: list[Notice] = Field(default_factory=list)
    node_failures: list[NodeFailed] = Field(default_factory=list)
    session_id: str = ""
    correlation_id: str = ""
    duration_ms: int = 0


def run_query(
    client: httpx.Client,
    *,
    query: str,
    session_id: str = "",
    disable_graph_context: bool = False,
    deadline_s: float = 600.0,
) -> QueryOutcome:
    """Drive gateway /rag/query endpoint with SSE streaming and contract assertions."""
    import httpx
    from httpx_sse import SSEError, connect_sse

    started = time.monotonic()
    body: dict[str, object] = {"query": query, "session_id": session_id}
    if disable_graph_context:
        body["disable_graph_context"] = True

    eval_timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)

    try:
        with connect_sse(
            client,
            "POST",
            "/rag/query",
            json=body,
            timeout=eval_timeout,
        ) as event_source:
            resp = event_source.response
            if resp.status_code != httpx.codes.OK:
                resp.read()
                raise PreStreamError(f"HTTP {resp.status_code}: {resp.text[:500]!r}")

            session = resp.headers.get("X-Lancet-Session-ID", "")
            correlation = resp.headers.get("X-Lancet-Correlation-ID", "")

            final_answer_count = 0
            answer: RagAnswer | None = None
            completion: WorkflowCompleted | None = None
            node_failures: list[NodeFailed] = []

            for sse in event_source.iter_sse():
                if time.monotonic() - started > deadline_s:
                    raise StreamDeadlineExceeded(
                        f"exceeded {deadline_s}s wall-clock deadline"
                    )

                match sse.event:
                    case "final_answer":
                        final_answer_count += 1
                        answer = RagAnswer.model_validate_json(sse.data)
                    case "workflow_completed":
                        raw_wc = json.loads(sse.data)
                        if (
                            "final_response" in raw_wc
                            and raw_wc.get("final_response") is not None
                            and "notices" in raw_wc
                            and raw_wc.get("notices") is not None
                        ):
                            raise ContractViolation(
                                "workflow_completed cannot carry both "
                                "final_response and top-level notices"
                            )
                        completion = WorkflowCompleted.model_validate(raw_wc)
                    case "node_failed":
                        node_failures.append(NodeFailed.model_validate_json(sse.data))
                    case "stream_error":
                        f = StreamErrorFrame.model_validate_json(sse.data)
                        raise StreamAborted(f"{f.code}: {f.message}")
                    case "answer_chunk" | "node_started" | "node_completed":
                        pass
                    case other:
                        raise ContractViolation(f"unknown SSE event {other!r}")

    except SSEError as exc:
        raise PreStreamError(str(exc)) from exc

    if completion is None:
        raise StreamAborted("stream ended without workflow_completed")
    if final_answer_count > 1:
        raise ContractViolation(
            f"{final_answer_count} final_answer frames, expected <= 1"
        )

    if not completion.success:
        return QueryOutcome(
            status="failed",
            answer=completion.final_response,
            completion=completion,
            notices=completion.notices,
            node_failures=node_failures,
            session_id=session,
            correlation_id=correlation,
            duration_ms=completion.total_duration_ms,
        )

    # Success path
    if final_answer_count == 1:
        assert answer is not None
        return QueryOutcome(
            status="ok",
            answer=answer,
            completion=completion,
            notices=answer.notices,
            node_failures=node_failures,
            session_id=session,
            correlation_id=correlation,
            duration_ms=completion.total_duration_ms,
        )

    # final_answer_count == 0 with success == True
    if completion.final_response is not None:
        return QueryOutcome(
            status="degraded",
            answer=completion.final_response,
            completion=completion,
            notices=completion.final_response.notices,
            node_failures=node_failures,
            session_id=session,
            correlation_id=correlation,
            duration_ms=completion.total_duration_ms,
        )

    if completion.notices:
        return QueryOutcome(
            status="degraded",
            answer=None,
            completion=completion,
            notices=completion.notices,
            node_failures=node_failures,
            session_id=session,
            correlation_id=correlation,
            duration_ms=completion.total_duration_ms,
        )

    raise ContractViolation(
        "workflow_completed.success with no answer payload and no notices"
    )
