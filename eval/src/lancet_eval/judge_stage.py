"""The 06.3.5 cache-only, counts-only judge stage (RED stub)."""

from __future__ import annotations

from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict

from lancet_eval.corpus import load_corpus_config, load_sample_questions
from lancet_eval.judge import judge_once
from lancet_eval.score import _get_engine_generation_model
from lancet_eval.split import load_split

_STUB_NAMES = (
    load_corpus_config,
    load_sample_questions,
    judge_once,
    _get_engine_generation_model,
    load_split,
)


class JudgeStageError(Exception):
    """Raised when the judge stage refuses to run or cannot continue."""


class JudgeArmCounts(BaseModel):
    """Counts of one arm."""

    model_config = ConfigDict(extra="forbid")

    judgeable: int = 0
    unique_keys: int = 0
    cached_before: int = 0
    judged_now: int = 0
    errors: int = 0
    re_attempted: int = 0
    not_attempted: int = 0


class JudgeStageRecord(BaseModel):
    """Counts and timings of one judge stage."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "heldout"
    judge_model: str = ""
    judge_prompt_version: str = ""
    stage_cap: float = 0.0
    calls: int = 0
    keys_attempted: int = 0
    unique_keys_total: int = 0
    spend_usd: float = 0.0
    wall_clock_s: float = 0.0
    arms: dict[str, JudgeArmCounts] = {}
    stop_reason: str | None = None
    per_call_latency_ms_p50: float | None = None
    per_call_latency_ms_p95: float | None = None


def run_judge_stage(
    *,
    run_dir: Path | str,
    stage_cap: float,
    rehearsal: bool = False,
    client: httpx.Client | None = None,
    api_key: str | None = None,
    git_repo: Path | None = None,
) -> JudgeStageRecord:
    """Judge every judgeable record of every arm (not implemented yet)."""
    raise NotImplementedError
