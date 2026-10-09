"""One arm-provenance conformance check for a journal record (D-99/D-100/D-101).

This is AI-SPEC 5 Dimensions row #1.

``provenance_failures`` reports one coded failure per broken clause, on every record
whose RetrieveHybrid completed (a snapshot with a non-empty ``result_hash``):

* **a** the snapshot's ``retrieval_mode`` echo differs from the arm's mode;
* **b** the D-100 ranking is absent beside non-empty ``retrieved_chunks``, or is longer
  than ``candidate_limit``;
* **c** the ranking's prefix differs from ``retrieved_chunks`` in order, ``rank`` or
  ``graph_boosted``, ``fused_rank`` is not 1..n, or the final list is not
  ``min(final_limit, len(ranking))`` long;
* **d** the per-arm rank shape is wrong (a ``bm25_rank`` on dense-only, a
  ``vector_rank`` on bm25-only, a ``graph_rank`` on any graph-off arm);
* **e** a graph-off arm lacks the GRAPH_ABLATION notice or carries GRAPH_UNAVAILABLE,
  or a graph-on arm carries GRAPH_ABLATION (06.3.6 D-134);
* **f** the snapshot config differs from the drive-2 values in
  ``SNAPSHOT_EXPECTATIONS``;
* **g** a non-zero ``bm25_count`` on dense-only or ``vector_count`` on bm25-only
  (corroboration only);
* **h** (06.3.6 D-134) the snapshot's ``levers`` echo differs from the arm's levers;
* **i** (06.3.6 D-134, D-161) a rerank-bearing arm's record carries RERANK_DEGRADED
  (typed code 23): the record is off-arm, counted per arm, and leaves only the
  comparison that arm feeds;
* **j** (06.3.6 D-134) a rerank leak: a non-rerank arm carries rerank telemetry or code
  23, or a rerank-bearing arm carries neither the telemetry nor the notice.

Clause (a) calls ``arms.echo_failures``, clause (h) ``arms.lever_echo_failures`` and
clause (e) reads ``has_arm_provenance`` and ``carries_graph_ablation``; none matches on
message text (D-158 IN-04), so rewording a message in ``arms`` moves no failure
between clauses.

A legacy label (``graph-off``, ``graph-on``) carries no mode echo and no ranking, so
it is held to (e), (f), (h) and (j) only (the last two are vacuous on a journal that
predates the fields). A record whose RetrieveHybrid never completed (no snapshot, or a
partial snapshot with an empty ``result_hash``) has nothing to check for (a) to (d),
(f), (h) and (j); (e) and (i), which read notices, still apply.

``is_ok(record)`` is ok(r) of AI-SPEC 5 Populations: the record is D-34 usable and has
no failure in (a) to (f), (h), (i) or (j). (g) never changes ok.

Drive-time rule (AI-SPEC 6, "Provenance in the paid drive"): in the paid drive, a
failure in ``ZERO_TOLERANCE_CODES`` (a, b, c, d, f, h, j) makes ``score`` refuse
(06.3.5-10), it is not counted as an exclusion. (e) keeps its inherited
count-and-exclude rule: the record leaves P4. (i) is count-and-exclude per arm too: a
degraded rerank record is never silently dropped and never enters the rerank arm's
decisional population. (g) is corroboration only.

An unknown arm label raises ``ValueError`` from the arm registry (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lancet_eval.arms import echo_failures, lever_echo_failures, resolve_arm
from lancet_eval.usability import (
    carries_graph_ablation,
    carries_rerank_degraded,
    has_arm_provenance,
    has_rerank_telemetry,
    is_usable,
)

if TYPE_CHECKING:
    from lancet_eval.client import RankedCandidate, StructuredCitation
    from lancet_eval.journal import RunRecord

ZERO_TOLERANCE_CODES = frozenset("abcdfhj")
_OK_CODES = frozenset("abcdefhij")


@dataclass(frozen=True)
class ProvenanceFailure:
    """One broken provenance clause of one record.

    Attributes:
        code: The clause, ``"a"`` to ``"j"``.
        label: The record's stored arm label.
        detail: What differed, in prose.
    """

    code: str
    label: str
    detail: str


@dataclass(frozen=True)
class SnapshotExpectations:
    """The snapshot config every arm of the ablation must report (clause f)."""

    rrf_k: int
    candidate_limit: int
    final_limit: int
    vector_weight: float
    bm25_weight: float


# config/config.toml [engine.retrieval]: rrf_k 60, candidate_limit 32, final_limit 8 and
# weights 1.0/1.0 are the values drive 2 recorded. This phase never changes them.
SNAPSHOT_EXPECTATIONS = SnapshotExpectations(
    rrf_k=60,
    candidate_limit=32,
    final_limit=8,
    vector_weight=1.0,
    bm25_weight=1.0,
)


def _config_failure(
    snapshot_config: SnapshotExpectations, expected: SnapshotExpectations
) -> str:
    diffs = [
        f"{name} {getattr(snapshot_config, name)!r} != {getattr(expected, name)!r}"
        for name in (
            "rrf_k",
            "candidate_limit",
            "final_limit",
            "vector_weight",
            "bm25_weight",
        )
        if getattr(snapshot_config, name) != getattr(expected, name)
    ]
    return "; ".join(diffs)


def _prefix_details(
    ranking: list[RankedCandidate],
    final: list[StructuredCitation],
    final_limit: int,
) -> list[str]:
    """Clause (c): the ranking's prefix is the final list."""
    details: list[str] = []
    gaps = [i + 1 for i, r in enumerate(ranking) if r.fused_rank != i + 1]
    if gaps:
        details.append(
            f"fused_rank is not 1..{len(ranking)} (first break at position {gaps[0]})"
        )
    if len(ranking) < len(final):
        details.append(
            f"ranking holds {len(ranking)} rows, fewer than the "
            f"{len(final)} final chunks"
        )
    if len(final) != min(final_limit, len(ranking)):
        details.append(
            f"{len(final)} final chunks, expected min(final_limit={final_limit}, "
            f"{len(ranking)}) = {min(final_limit, len(ranking))}"
        )
    for i, (row, chunk) in enumerate(zip(ranking, final, strict=False)):
        if row.chunk_id != chunk.chunk_id:
            details.append(
                f"position {i + 1}: ranking {row.chunk_id!r} != "
                f"chunk {chunk.chunk_id!r}"
            )
        elif chunk.rank != row.fused_rank:
            details.append(
                f"position {i + 1}: chunk rank {chunk.rank} != "
                f"fused_rank {row.fused_rank}"
            )
        elif row.graph_boosted != bool(chunk.graph_boosted):
            details.append(
                f"position {i + 1}: ranking graph_boosted {row.graph_boosted} != "
                f"chunk graph_boosted {bool(chunk.graph_boosted)}"
            )
    return details


def provenance_failures(
    record: RunRecord,
    *,
    expected: SnapshotExpectations = SNAPSHOT_EXPECTATIONS,
) -> list[ProvenanceFailure]:
    """Checks a record against its arm's provenance clauses (a) to (j).

    Args:
        record: A journal record, under a canonical or legacy arm label.
        expected: The snapshot config clause (f) compares against.

    Returns:
        One failure per broken clause, ordered by code. Empty when provenance holds.

    Raises:
        ValueError: If the record's arm label is unknown.
    """
    label = record.graph_arm
    spec = resolve_arm(label)
    legacy = label != spec.label
    details: dict[str, list[str]] = {}

    def fail(code: str, detail: str) -> None:
        details.setdefault(code, []).append(detail)

    # (e) composed from has_arm_provenance: notices exist even without a snapshot.
    if spec.disable_graph_context and not has_arm_provenance(record):
        fail(
            "e",
            "graph-off arm lacks the GRAPH_ABLATION notice "
            "or carries GRAPH_UNAVAILABLE",
        )
    if not spec.disable_graph_context and carries_graph_ablation(record):
        fail("e", "graph-on arm carries the GRAPH_ABLATION notice")

    # (i) reads notices, so it applies without a snapshot: a degraded rerank record is
    # off-arm and counted, never dropped silently (D-161).
    rerank_arm = "rerank" in spec.levers
    degraded = carries_rerank_degraded(record)
    if rerank_arm and degraded:
        fail("i", "rerank degraded (RERANK_DEGRADED, typed code 23): off-arm record")

    snapshot = record.snapshot
    completed = snapshot is not None and snapshot.result_hash != ""
    if snapshot is not None and completed:
        # (h) the levers echo equals the arm's levers; D-158 IN-04: the function, not
        # message text.
        for message in lever_echo_failures(label, snapshot.levers):
            fail("h", message)
        # (j) no rerank leak onto a non-rerank arm, and no rerank arm without rerank
        # telemetry or the degraded notice.
        telemetry = has_rerank_telemetry(record)
        if rerank_arm and not (telemetry or degraded):
            fail(
                "j",
                "rerank arm record carries neither workflow_meta.rerank nor the "
                "RERANK_DEGRADED notice",
            )
        if not rerank_arm and (telemetry or degraded):
            fail("j", "non-rerank arm record carries rerank telemetry or code 23")
        # (f) the config every arm of the ablation must report.
        observed = SnapshotExpectations(
            rrf_k=snapshot.rrf_k,
            candidate_limit=snapshot.candidate_limit,
            final_limit=snapshot.final_limit,
            vector_weight=snapshot.vector_weight,
            bm25_weight=snapshot.bm25_weight,
        )
        config = _config_failure(observed, expected)
        if config:
            fail("f", config)

        if not legacy:
            # (a) the retrieval_mode echo; the GRAPH_ABLATION check is clause (e),
            # reported above, not twice. D-158 IN-04: clause (a) calls echo_failures
            # directly, so rewording either message moves no failure between clauses.
            for message in echo_failures(label, snapshot.retrieval_mode):
                fail("a", message)

            ranking = snapshot.pre_truncation_ranking
            final = snapshot.retrieved_chunks
            # (b) the ranking is present (omitempty: none beside no chunks is valid).
            if not ranking and final:
                fail(
                    "b",
                    f"no pre_truncation_ranking beside {len(final)} retrieved_chunks",
                )
            if len(ranking) > snapshot.candidate_limit:
                fail(
                    "b",
                    f"ranking holds {len(ranking)} rows, more than "
                    f"candidate_limit {snapshot.candidate_limit}",
                )
            # (c) the prefix is the final list.
            if ranking:
                for detail in _prefix_details(ranking, final, snapshot.final_limit):
                    fail("c", detail)
            # (d) the per-arm rank shape; a rank of 0 or None is absent.
            if spec.retrieval_mode == "dense_only" and any(
                r.bm25_rank for r in ranking
            ):
                fail("d", "dense-only ranking carries a bm25_rank")
            if spec.retrieval_mode == "bm25_only" and any(
                r.vector_rank for r in ranking
            ):
                fail("d", "bm25-only ranking carries a vector_rank")
            if spec.disable_graph_context and any(r.graph_rank for r in ranking):
                fail("d", "graph-off ranking carries a graph_rank")
            # (g) corroboration from the workflow counts.
            meta = record.workflow_meta
            if meta is not None:
                if spec.retrieval_mode == "dense_only" and meta.bm25_count != 0:
                    fail("g", f"dense-only record has bm25_count {meta.bm25_count}")
                if spec.retrieval_mode == "bm25_only" and meta.vector_count != 0:
                    fail("g", f"bm25-only record has vector_count {meta.vector_count}")

    return [
        ProvenanceFailure(code=code, label=label, detail="; ".join(details[code]))
        for code in sorted(details)
    ]


def is_ok(record: RunRecord) -> bool:
    """ok(r) of AI-SPEC 5 Populations.

    The record is D-34 usable and has no failure in clauses (a) to (f). Clause (g) is
    corroboration only and never changes the result.
    """
    return is_usable(record) and not any(
        f.code in _OK_CODES for f in provenance_failures(record)
    )
