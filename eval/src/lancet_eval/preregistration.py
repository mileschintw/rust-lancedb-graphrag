"""Resolves the pre-registration a corpus token names (D-73, 06.3.6 D-149).

A corpus names its pre-registration by the name of a constant in
``lancet_eval.thresholds`` (``[preregistration] token``). ``gitcheck`` proves that the
commit introducing that constant predates the paid drive; this module reads the
constant itself, so the drive can refuse a corpus whose arm list is not the one the
pre-registration fixed, and the gates and the preflight can read the numbers it fixed.

The lookup fails closed: a token that names nothing, or names something that is not a
pre-registration (a float, a rule object, a dataclass without a reference arm), raises
``PreregistrationError``. It never returns a default, because a default is a value
nobody pre-registered.

v1.1 (D-247, D-253): a stage constant may list external arms. It declares each one's
retrieval pipeline in an ``external_pipelines`` attribute, a tuple of
``(arm label, arms.ExternalPipeline)`` pairs; ``external_pipelines_of`` reads it and
fails closed when an external arm has no pipeline. Constants without the attribute (the
v1.0 ones) declare none. A label may carry a store prefix (D-251,
``small/hybrid+rerank+metadata``); ``resolve`` refuses a constant naming a label the arm
registry does not know, a bad prefix included.

v1.1 S2 (D-257): a label may be a reader arm (``<arm>@<reader>``). The constant
declares each reader its arms name in a ``readers`` attribute, a tuple of
``(reader name, reader_request.ReaderDeclaration)`` pairs; ``readers_of`` reads it, and
``resolve`` refuses a constant whose reader arm names a reader it does not declare.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any

from lancet_eval import thresholds
from lancet_eval.arms import (
    READERS,
    ExternalPipeline,
    arm_reader,
    canonical_arm,
    is_external_arm,
)
from lancet_eval.gitcheck import PreregistrationError
from lancet_eval.reader_request import ReaderDeclaration

__all__ = [
    "PreregistrationError",
    "arms_of",
    "external_pipelines_of",
    "readers_of",
    "resolve",
]


def resolve(token: str) -> Any:
    """Returns the pre-registration object the token names.

    Args:
        token: The name of a pre-registration constant in ``thresholds``.

    Returns:
        The object: an ``AblationPreRegistration`` (06.3.5) or a lever pre-registration
        (06.3.6). Both carry a ``reference_arm``.

    Raises:
        PreregistrationError: If ``thresholds`` has no such attribute, the attribute
            is not a pre-registration, it names an arm label the registry does not
            know (a bad store prefix or reader included), or its reader declarations
            fail ``readers_of``.
    """
    if not token or not token.isidentifier():
        raise PreregistrationError(
            f"pre-registration token {token!r} is not a constant name"
        )
    if not hasattr(thresholds, token):
        raise PreregistrationError(
            f"pre-registration {token} is not defined in {thresholds.__name__}"
        )
    prereg = getattr(thresholds, token)
    if not hasattr(prereg, "reference_arm") or isinstance(prereg, type):
        raise PreregistrationError(
            f"{token} in {thresholds.__name__} is not a pre-registration "
            f"(no reference arm; got {type(prereg).__name__}"
            f"{', a dataclass' if is_dataclass(prereg) else ''})"
        )
    labels = [
        prereg.reference_arm,
        *getattr(prereg, "comparison_arms", ()),
        *(a for family in getattr(prereg, "families", ()) for a in family.arms),
        *getattr(prereg, "descriptive_arms", ()),
    ]
    for label in labels:
        try:
            canonical_arm(label)
        except ValueError as exc:
            raise PreregistrationError(f"{token} names an unknown arm: {exc}") from exc
    try:
        readers_of(prereg)
    except PreregistrationError as exc:
        raise PreregistrationError(f"{token}: {exc}") from exc
    return prereg


def arms_of(prereg: Any) -> tuple[str, ...]:
    """Every arm a pre-registration fixes, reference first, without duplicates.

    A lever pre-registration (it has ``families``) names its reference arm, every arm
    of every family, then its descriptive arms. An ablation pre-registration names its
    reference arm then its comparison arms.

    Args:
        prereg: The object ``resolve`` returned.

    Returns:
        The arm labels in the order above.
    """
    arms: list[str] = [prereg.reference_arm]
    if hasattr(prereg, "families"):
        for family in prereg.families:
            arms.extend(family.arms)
        arms.extend(prereg.descriptive_arms)
    else:
        arms.extend(prereg.comparison_arms)
    return tuple(dict.fromkeys(arms))


def external_pipelines_of(prereg: Any) -> dict[str, ExternalPipeline]:
    """The retrieval pipeline a pre-registration fixes for each of its external arms.

    Args:
        prereg: The object ``resolve`` returned.

    Returns:
        ``{arm label: pipeline}``; empty for a constant that lists no external arm.

    Raises:
        PreregistrationError: If a declared label is not an external arm or is
            declared twice, a declared value is not an ``ExternalPipeline``, or an
            external arm of ``arms_of(prereg)`` has no declared pipeline.
    """
    pipelines: dict[str, ExternalPipeline] = {}
    for label, pipeline in getattr(prereg, "external_pipelines", ()):
        if not is_external_arm(label):
            raise PreregistrationError(
                f"external_pipelines names {label!r}, which is not an external arm"
            )
        if label in pipelines:
            raise PreregistrationError(f"external_pipelines declares {label!r} twice")
        if not isinstance(pipeline, ExternalPipeline):
            raise PreregistrationError(
                f"external_pipelines[{label!r}] is not an ExternalPipeline "
                f"(got {type(pipeline).__name__})"
            )
        pipelines[label] = pipeline
    missing = [a for a in arms_of(prereg) if is_external_arm(a) and a not in pipelines]
    if missing:
        raise PreregistrationError(
            f"external arm(s) {missing} have no pre-registered pipeline "
            "(external_pipelines, D-247)"
        )
    return pipelines


def readers_of(prereg: Any) -> dict[str, ReaderDeclaration]:
    """The reader declaration a pre-registration fixes for each reader (D-257).

    Args:
        prereg: A pre-registration object.

    Returns:
        ``{reader name: declaration}``; empty for a constant that declares none.

    Raises:
        PreregistrationError: If a declared name is not a known reader or is declared
            twice, a declared value is not a ``ReaderDeclaration``, or a reader arm of
            ``arms_of(prereg)`` names a reader with no declaration.
    """
    readers: dict[str, ReaderDeclaration] = {}
    for name, declaration in getattr(prereg, "readers", ()):
        if name not in READERS:
            raise PreregistrationError(
                f"readers names {name!r}, which is not a known reader "
                f"{list(READERS)} (D-257)"
            )
        if name in readers:
            raise PreregistrationError(f"readers declares {name!r} twice")
        if not isinstance(declaration, ReaderDeclaration):
            raise PreregistrationError(
                f"readers[{name!r}] is not a ReaderDeclaration "
                f"(got {type(declaration).__name__})"
            )
        readers[name] = declaration
    undeclared = sorted({
        reader
        for arm in arms_of(prereg)
        if (reader := arm_reader(arm)) is not None and reader not in readers
    })
    if undeclared:
        raise PreregistrationError(
            f"reader arm(s) name reader(s) {undeclared} with no declaration "
            "(readers, D-257)"
        )
    return readers
