"""Usability and provenance predicates for evaluation records."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lancet_eval.journal import RunRecord

NOTICE_CODE_GRAPH_UNAVAILABLE = 10
NOTICE_CODE_GRAPH_ABLATION = 18

UNUSABLE_NODE_NAMES = {"RetrieveHybrid", "AssemblePrompt", "GenerateAnswer"}


def is_usable(record: RunRecord) -> bool:
    """Determine if a RunRecord represents a usable query for quality and path health.

    Per D-34:
    UNUSABLE if:
      - record.outcome == "error"
      - hard (retryable=False) failure of RetrieveHybrid, AssemblePrompt,
        or GenerateAnswer
      - RetrieveHybrid failed (even if snapshot exists, e.g. D-33 partial
        empty-chunk snapshot)

    NOT unusable:
      - ONLY retryable failures on an otherwise successful workflow
        (outcome == "success")
      - Graph node failures (ExtractGraphContext), graph ablation, or graph
        timeouts/unavailable
      - NO_EVIDENCE after a completed RetrieveHybrid
    """
    if record.outcome == "error":
        return False

    for nf in record.node_failures:
        if nf.node_name in UNUSABLE_NODE_NAMES:
            if not nf.retryable:
                return False

    return True


def has_arm_provenance(record: RunRecord) -> bool:
    """Verify that a graph-off record carries ablation notice and not unavailable."""
    has_ablation = any(
        n.typed_code == NOTICE_CODE_GRAPH_ABLATION or n.code == "GRAPH_ABLATION"
        for n in record.notices
    )
    has_unavailable = any(
        n.typed_code == NOTICE_CODE_GRAPH_UNAVAILABLE
        or n.code == "GRAPH_UNAVAILABLE"
        for n in record.notices
    )
    return has_ablation and not has_unavailable
