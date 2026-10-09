"""D-101 arm registry: the label -> request-flags table for the retrieval ablation.

``ARM_REGISTRY`` is the sole durable arm-to-flag mapping in the evaluation harness.
The ``[arms]`` section of a corpus TOML, ``--arm`` on ``lancet-eval probe``, the
request the drive sends and the provenance check all derive from it.

Aliases are read-only. ``graph-off`` and ``graph-on`` are the labels drives 1, 1b
and 2 stored; they resolve to ``hybrid`` and ``hybrid+graph`` at lookup only.
``RunRecord.graph_arm`` is never rewritten, because ``legacy_records_digest`` hashes
the stored value and a rewritten label would also break every historical journal.
An unknown label fails closed.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from lancet_eval.client import Notice
    from lancet_eval.corpus import GoldQuestion

RetrievalMode = Literal["dense_only", "bm25_only", "hybrid"]
ArmLabel = Literal["dense-only", "bm25-only", "hybrid", "hybrid+graph"]


class ArmSpec(BaseModel):
    """One D-101 registry row.

    Attributes:
        label: Canonical arm label.
        retrieval_mode: Value of the request's ``retrieval_mode`` field.
        disable_graph_context: Whether the request switches graph context off.
        legacy_aliases: Read-only lookup aliases (drives 1, 1b and 2 labels).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: ArmLabel
    retrieval_mode: RetrievalMode
    disable_graph_context: bool
    legacy_aliases: tuple[str, ...] = ()


ARM_REGISTRY: dict[str, ArmSpec] = {
    a.label: a
    for a in (
        ArmSpec(
            label="dense-only",
            retrieval_mode="dense_only",
            disable_graph_context=True,
        ),
        ArmSpec(
            label="bm25-only",
            retrieval_mode="bm25_only",
            disable_graph_context=True,
        ),
        ArmSpec(
            label="hybrid",
            retrieval_mode="hybrid",
            disable_graph_context=True,
            legacy_aliases=("graph-off",),
        ),
        ArmSpec(
            label="hybrid+graph",
            retrieval_mode="hybrid",
            disable_graph_context=False,
            legacy_aliases=("graph-on",),
        ),
    )
}

_ALIAS: dict[str, str] = {
    al: a.label for a in ARM_REGISTRY.values() for al in a.legacy_aliases
}


def canonical_arm(stored_label: str) -> str:
    """Resolves a stored label or alias to its canonical registry label.

    Lookup only: never write the result back to ``RunRecord.graph_arm``.

    Args:
        stored_label: A canonical label or a legacy alias.

    Returns:
        The canonical label.

    Raises:
        ValueError: If the label is neither canonical nor an alias.
    """
    if stored_label in ARM_REGISTRY:
        return stored_label
    if stored_label in _ALIAS:
        return _ALIAS[stored_label]
    raise ValueError(f"unknown arm label {stored_label!r}")


def resolve_arm(label: str) -> ArmSpec:
    """Returns the registry row for a canonical label or an alias.

    Args:
        label: A canonical label or a legacy alias.

    Returns:
        The matching ``ArmSpec``.

    Raises:
        ValueError: With the ``Unknown arm '...'. Expected one of:`` prefix.
    """
    if label in ARM_REGISTRY:
        return ARM_REGISTRY[label]
    if label in _ALIAS:
        return ARM_REGISTRY[_ALIAS[label]]
    valid = [*ARM_REGISTRY, *_ALIAS]
    raise ValueError(f"Unknown arm {label!r}. Expected one of: {valid}")


def is_legacy_label(label: str) -> bool:
    """Whether a label is one of the two read-only legacy aliases."""
    return label in _ALIAS


def arm_slug(label: str) -> str:
    """Filesystem-safe slug: the canonical label with ``+`` and ``-`` as ``_``.

    Args:
        label: A canonical label or an alias.

    Returns:
        The slug of the canonical label.
    """
    return canonical_arm(label).replace("+", "_").replace("-", "_")


def request_fields(label: str) -> dict[str, object]:
    """Returns the ``run_query`` keyword fields that make a request for an arm.

    The two legacy labels return exactly the bodies drives 1, 1b and 2 sent, so a
    legacy request stays byte-identical. A canonical label also names its retrieval
    mode and asks for the pre-truncation ranking (D-100).

    Args:
        label: A canonical label or an alias.

    Returns:
        Keyword fields for ``client.run_query``.

    Raises:
        ValueError: If the label is unknown.
    """
    spec = resolve_arm(label)
    if is_legacy_label(label):
        return {"disable_graph_context": True} if spec.disable_graph_context else {}
    fields: dict[str, object] = {"retrieval_mode": spec.retrieval_mode}
    if spec.disable_graph_context:
        fields["disable_graph_context"] = True
    fields["include_pre_truncation_ranking"] = True
    return fields


def echo_failures(label: str, retrieval_mode_echo: str | None) -> list[str]:
    """Checks that a record's snapshot echoes the retrieval mode the arm requested.

    A canonical label must see its own retrieval mode echoed in the snapshot. A legacy
    label is not checked, because legacy journals carry no mode echo. This is
    provenance clause (a); callers branch on this function, never on message text
    (D-158 IN-04).

    Args:
        label: The stored arm label (canonical or legacy alias).
        retrieval_mode_echo: ``RetrievalSnapshot.retrieval_mode`` of the record, if any.

    Returns:
        Failure strings that each name the label; empty when the echo holds.
    """
    spec = resolve_arm(label)
    if is_legacy_label(label) or retrieval_mode_echo == spec.retrieval_mode:
        return []
    return [
        f"arm {label!r}: expected retrieval_mode {spec.retrieval_mode!r} "
        f"echoed in the snapshot, observed {retrieval_mode_echo!r}"
    ]


def ablation_failures(label: str, notices: Sequence[Notice]) -> list[str]:
    """Checks that a graph-off arm carries the ablation notice and no unavailable one.

    An arm that disables graph context must carry the GRAPH_ABLATION notice and not
    GRAPH_UNAVAILABLE. Legacy labels are held to this check too. This is provenance
    clause (e).

    Args:
        label: The stored arm label (canonical or legacy alias).
        notices: The record's notices.

    Returns:
        Failure strings that each name the label; empty when the notices hold.
    """
    from lancet_eval.journal import RunRecord
    from lancet_eval.usability import has_arm_provenance

    if not resolve_arm(label).disable_graph_context:
        return []
    record = RunRecord(
        corpus="",
        question_id="",
        graph_arm=label,
        outcome="success",
        notices=list(notices),
    )
    if has_arm_provenance(record):
        return []
    return [
        f"arm {label!r}: graph-off arm lacks the GRAPH_ABLATION notice "
        "or carries GRAPH_UNAVAILABLE"
    ]


def mode_provenance_failures(
    label: str,
    snapshot_mode: str | None,
    notices: Sequence[Notice],
) -> list[str]:
    """Checks that a record's echo and notices match the arm that was requested.

    A thin composition of ``echo_failures`` and ``ablation_failures``, kept for the
    callers that want both lists in one call.

    Args:
        label: The stored arm label (canonical or legacy alias).
        snapshot_mode: ``RetrievalSnapshot.retrieval_mode`` of the record, if any.
        notices: The record's notices.

    Returns:
        Failure strings that each name the label; empty when provenance holds.
    """
    return echo_failures(label, snapshot_mode) + ablation_failures(label, notices)


def plan_work_units(
    questions: Sequence[GoldQuestion],
    arms: Sequence[str],
    order_seed: int,
) -> list[tuple[GoldQuestion, str]]:
    """Plans the D-107 seeded, balanced arm rotation over a question set.

    The questions are sorted by ID and shuffled with ``random.Random(order_seed)``.
    The per-question offsets ``i % len(arms)`` are then shuffled with the same
    stream, and each question's arm list is rotated by its offset. Every arm of a
    question therefore runs back to back, and over N questions each arm is first,
    and holds each later position, ``N // len(arms)`` or one more times. The function
    is pure, so ``--resume`` rebuilds the identical order.

    Args:
        questions: The questions to drive, in any order.
        arms: The arm labels, in registry order.
        order_seed: Seed of the rotation, recorded in the journal header.

    Returns:
        The ``(question, arm)`` work units, question-major in rotated order.
    """
    arm_list = list(arms)
    ordered = sorted(questions, key=lambda q: q.question_id)
    rng = random.Random(order_seed)
    rng.shuffle(ordered)
    offsets = [i % len(arm_list) for i in range(len(ordered))]
    rng.shuffle(offsets)
    units: list[tuple[GoldQuestion, str]] = []
    for question, offset in zip(ordered, offsets, strict=True):
        for arm in arm_list[offset:] + arm_list[:offset]:
            units.append((question, arm))
    return units
