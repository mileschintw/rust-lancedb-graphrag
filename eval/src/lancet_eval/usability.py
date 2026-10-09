"""Usability and provenance predicates for evaluation records."""

from __future__ import annotations

from typing import TYPE_CHECKING

from lancet_eval.arms import canonical_arm, resolve_arm

if TYPE_CHECKING:
    from lancet_eval.journal import RunRecord

NOTICE_CODE_GRAPH_UNAVAILABLE = 10
NOTICE_CODE_GRAPH_ABLATION = 18
NOTICE_CODE_RERANK_DEGRADED = 23

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


def has_scorable_payload(record: RunRecord) -> bool:
    """Determine if a usable record carries scorable retrieval and answer payload.

    Per D-34 / CR-01:
    A record is scorable if and only if:
      - record.snapshot is not None (retrieval snapshot exists)
      - record.answer is not None and record.answer.strip() != ""
        (answer text is non-blank)

    Boundaries:
      - NO_EVIDENCE carve-out: A present snapshot with an empty retrieved_chunks
        list is scorable. It yields an honest zero recall rather than being
        excluded from the denominator.
      - Blank answers: An answer of None, empty string "", or whitespace-only
        string are treated identically as lacking an answer payload.
    """
    if record.snapshot is None:
        return False
    if record.answer is None or not record.answer.strip():
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


def carries_graph_ablation(record: RunRecord) -> bool:
    """Whether a record carries the GRAPH_ABLATION notice (typed code 18)."""
    return any(
        n.typed_code == NOTICE_CODE_GRAPH_ABLATION or n.code == "GRAPH_ABLATION"
        for n in record.notices
    )


def carries_rerank_degraded(record: RunRecord) -> bool:
    """Whether a record carries the RERANK_DEGRADED notice (typed code 23, D-134)."""
    return any(
        n.typed_code == NOTICE_CODE_RERANK_DEGRADED or n.code == "RERANK_DEGRADED"
        for n in record.notices
    )


def has_rerank_telemetry(record: RunRecord) -> bool:
    """Whether a record's workflow metadata carries rerank latency, cost and outcome."""
    return record.workflow_meta is not None and record.workflow_meta.rerank is not None


def is_graph_on_arm(label: str) -> bool:
    """Whether a stored arm label leaves graph context on (06.3.6 D-134).

    Read from the registry, so `hybrid+graph`, its alias `graph-on`, `hybrid+graph-v2`
    and a `hybrid+all` that carries `graph_v2` are graph-on arms. A label the registry
    does not know is not (the reader never raises). `is_graph_arm` keeps its 06.3.5
    meaning: only the v1 graph-on arm.
    """
    try:
        return not resolve_arm(label).disable_graph_context
    except ValueError:
        return False


def is_graph_arm(label: str) -> bool:
    """Whether a stored arm label is the graph-on arm (D-101).

    Lookup only: `hybrid+graph` and its legacy alias `graph-on` are the graph-on arm.
    A label the registry does not know is not (the reader never raises; `score_run`
    is the fail-closed point that refuses an unattributable label).
    """
    try:
        return canonical_arm(label) == "hybrid+graph"
    except ValueError:
        return False


def attempted_graph(record: RunRecord) -> bool:
    """Determine if a usable record attempted the graph node.

    Per D-02 / D-29 / Task 2 behavior:
    - Arm must be the graph-on arm (`hybrid+graph`, or its legacy alias `graph-on`)
    - Must NOT carry graph ablation notice
    - Must have EITHER a graph node timing (ExtractGraphContext) OR a graph node failure
      (e.g. inner GRAPH_TIMEOUT notice on completed node satisfies the timing half).
    """
    if not is_graph_arm(record.graph_arm):
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

