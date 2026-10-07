"""The 06.3.5 blinded calibration worksheet and its commit-reveal key (RED stub)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.arms import ArmLabel
from lancet_eval.config import repo_root
from lancet_eval.judge import Score5

if TYPE_CHECKING:
    from lancet_eval.corpus import GoldQuestion
    from lancet_eval.journal import RunRecord
    from lancet_eval.split import HeldOutSplit

MECHANICS_LINE = (
    "Integers 1–5 for both scores. 2 and 4 lie between the printed anchors. "
    "Grade only against the evidence shown."
)


class CalibrationError(Exception):
    """Raised when the calibration emit refuses."""


class CalibrationWorksheetRow(BaseModel):
    """One owner-facing row: no arm, verdict, cache key or question ID."""

    model_config = ConfigDict(extra="forbid")

    slice_id: str = Field(pattern=r"^S\d{2}$")
    question: str
    answer: str
    evidence: str
    human_groundedness: Score5 | None = None
    human_faithfulness: Score5 | None = None
    notes: str = ""


class CalibrationKeyRow(BaseModel):
    """One key row, kept out of the tracked tree until the reveal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slice_id: str = Field(pattern=r"^S\d{2}$")
    arm: ArmLabel
    question_id: str
    question_type: str
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    notes: str = ""
    shared_arms: list[str] = Field(default_factory=list)


class CalibrationHeader(BaseModel):
    """The first line of the worksheet."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["header"] = "header"
    corpus: str
    judge_prompt_version: str
    judge_model: str
    seed: int
    emitted_at_sha: str
    d114_floor: float
    key_sha256: str
    rubric: str
    mechanics: str


class DrawnItem(BaseModel):
    """One drawn slice item with everything the worksheet and the key need."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slice_id: str
    arm: str
    question_id: str
    question_type: str
    cache_key: str
    question: str
    answer: str
    evidence: str
    shared_arms: tuple[str, ...]
    notes: str = ""


class EmitResult(BaseModel):
    """What an emit wrote."""

    model_config = ConfigDict(extra="forbid")

    worksheet_path: Path
    key_path: Path
    salt_path: Path
    key_sha256: str
    emitted_at_sha: str
    n_items: int
    git_add: str


def default_keys_root() -> Path:
    """The gitignored directory the key and salt are written under."""
    return repo_root() / "data" / "calibration-keys"


def rubric_block() -> str:
    """The rubric, sliced from the judge's system prompt (not implemented yet)."""
    raise NotImplementedError


def key_digest(salt: str, rows: Sequence[CalibrationKeyRow]) -> str:
    """The commit-reveal digest (not implemented yet)."""
    raise NotImplementedError


def read_key_file(path: Path | str) -> list[CalibrationKeyRow]:
    """Parses a key file (not implemented yet)."""
    raise NotImplementedError


def draw_slice(
    records: Sequence[RunRecord],
    split: HeldOutSplit,
    arms: Sequence[str],
    gold_map: dict[str, GoldQuestion],
    *,
    seed: int,
    prompt_version: str,
    judge_model: str,
) -> list[DrawnItem]:
    """The seeded, arm-stratified draw (not implemented yet)."""
    raise NotImplementedError


def emit_worksheet(
    run_dir: Path | str,
    *,
    keys_root: Path | None = None,
    git_repo: Path | None = None,
) -> EmitResult:
    """Emits the worksheet and key (not implemented yet)."""
    raise NotImplementedError
