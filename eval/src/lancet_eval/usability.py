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


def attempted_graph(record: RunRecord) -> bool:
    """Determine if a usable record attempted the graph node.

    Per D-02 / D-29 / Task 2 behavior:
    - Arm must be 'graph-on'
    - Must NOT carry graph ablation notice
    - Must have EITHER a graph node timing (ExtractGraphContext) OR a graph node failure
      (e.g. inner GRAPH_TIMEOUT notice on completed node satisfies the timing half).
    """
    if record.graph_arm != "graph-on":
        return False

    has_ablation = any(
        n.typed_code == NOTICE_CODE_GRAPH_ABLATION or n.code == "GRAPH_ABLATION"
        for n in record.notices
    )
    if has_ablation:
        return False

    has_graph_timing = any(
        nt.node_name == "ExtractGraphContext" for nt in record.node_timings
    )
    has_graph_failure = any(
        nf.node_name == "ExtractGraphContext" for nf in record.node_failures
    )

    return has_graph_timing or has_graph_failure


def is_self_contradictory(record: RunRecord) -> bool:
    """Determine if record violates wire contract via self-contradiction/frame break.

    Per D-35 / AI-SPEC §5 / Task 3:
    Violation if ANY of:
      (a) shape/sequence contract break (keyed on record.error_type is not None)
      (b) outcome == 'success' AND hard RetrieveHybrid failure
      (c) outcome == 'success' AND (snapshot is None OR retrieved_chunks is empty)
          AND RetrieveHybrid failed
      (d) outcome == 'success' AND empty answer AND non-empty node_failures
      (e) outcome == 'success' AND degraded_mode == False while a hard node failure
          is present (only applies when workflow_meta is present)

    NO_EVIDENCE carve-out:
      A completed retrieve with an empty chunk list (and no RetrieveHybrid failure)
      is NOT a violation.
    """
    # (a) Harness parse/stream exception or frame sequence break
    if record.error_type is not None:
        return True

    has_hard_retrieve_failure = any(
        nf.node_name == "RetrieveHybrid" and not nf.retryable
        for nf in record.node_failures
    )
    has_any_retrieve_failure = any(
        nf.node_name == "RetrieveHybrid" for nf in record.node_failures
    )

    empty_or_no_chunks = (
        record.snapshot is None or len(record.snapshot.retrieved_chunks) == 0
    )

    if record.outcome == "success":
        # (b) outcome == 'success' AND hard RetrieveHybrid failure
        if has_hard_retrieve_failure:
            return True

        # (c) outcome == 'success' AND empty/no chunks AND RetrieveHybrid failed
        if empty_or_no_chunks and has_any_retrieve_failure:
            return True

        # (d) outcome == 'success' AND empty answer AND node_failures non-empty
        if not record.answer and len(record.node_failures) > 0:
            return True

        # (e) degraded_mode == False while hard node failure is present
        if record.workflow_meta is not None and not record.workflow_meta.degraded_mode:
            has_any_hard_failure = any(
                not nf.retryable for nf in record.node_failures
            )
            if has_any_hard_failure:
                return True

    return False

