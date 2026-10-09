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
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any

from lancet_eval import thresholds
from lancet_eval.gitcheck import PreregistrationError

__all__ = ["PreregistrationError", "arms_of", "resolve"]


def resolve(token: str) -> Any:
    """Returns the pre-registration object the token names.

    Args:
        token: The name of a pre-registration constant in ``thresholds``.

    Returns:
        The object: an ``AblationPreRegistration`` (06.3.5) or a lever pre-registration
        (06.3.6). Both carry a ``reference_arm``.

    Raises:
        PreregistrationError: If ``thresholds`` has no such attribute, or the attribute
            is not a pre-registration.
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
