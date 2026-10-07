"""RED stub of the four-arm comparison (06.3.5-13). Replaced by the implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

LABEL_UNADJUSTED = ""
APPROXIMATION_LABEL = ""
FWER_STATEMENT = ""
D124_IDS: tuple[str, ...] = ()
D124_DISCLOSURE = ""
NON_COMPARABILITY_CAVEAT: tuple[str, ...] = ()
PAPER_REFERENCE_TABLE5: dict[str, Any] = {}
SECONDARY_DELTA_BASES: tuple[str, ...] = ()


class ComparisonError(Exception):
    """Raised when the comparison cannot be built."""


class Comparison(BaseModel):
    """Placeholder."""

    model_config = ConfigDict(extra="forbid")


def coverage_evaluable(n_p4: int, n_g: int, floor: float | None = None) -> bool:
    raise NotImplementedError


def holm_family(*args: Any, **kwargs: Any) -> Any:
    raise NotImplementedError


def format_stratum_cell(*args: Any, **kwargs: Any) -> str:
    raise NotImplementedError


def build_comparison(
    run_dir: Path | str, *, gold_chunks_path: Path | str | None = None
) -> Comparison:
    raise NotImplementedError


def write_comparison(
    run_dir: Path | str, *, gold_chunks_path: Path | str | None = None
) -> Comparison:
    raise NotImplementedError
