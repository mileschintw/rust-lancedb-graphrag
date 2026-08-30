"""Report models, markdown/JSON renderers, and schema generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Self

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lancet_eval.dimensions import DimensionResult

ROUND_RATIO_DP: int = 3
ROUND_JUDGED_DP: int = 2


class ReportError(Exception):
    """Raised when report generation violates publication preconditions."""


class RunMetadata(BaseModel):
    """Execution metadata stamped on every evaluation report."""

    model_config = ConfigDict(extra="forbid")

    corpus: str
    run_date: str
    commit_sha: str
    generation_model: str
    embedding_model: str
    judge_model: str
    judge_temperature: float = 0.0
    judge_prompt_version: str
    sampling_seed: int = 42
    sample_size_deterministic: int = 0
    sample_size_judged: int = 0
    index_generation: str
    result_hash: str
    arm_labels: list[str] = Field(default_factory=lambda: ["graph-on", "graph-off"])
    dependency_lock_hash: str
    partial: bool = False
    notes: str = ""

    @model_validator(mode="after")
    def _validate_non_blank_fields(self) -> Self:
        required_str_fields = [
            ("corpus", self.corpus),
            ("run_date", self.run_date),
            ("commit_sha", self.commit_sha),
            ("generation_model", self.generation_model),
            ("embedding_model", self.embedding_model),
            ("judge_model", self.judge_model),
            ("judge_prompt_version", self.judge_prompt_version),
            ("index_generation", self.index_generation),
            ("result_hash", self.result_hash),
            ("dependency_lock_hash", self.dependency_lock_hash),
        ]
        for name, val in required_str_fields:
            if not val or not val.strip():
                raise ValueError(
                    f"RunMetadata field '{name}' must not be blank or empty"
                )

        if not self.arm_labels:
            raise ValueError("RunMetadata field 'arm_labels' must not be empty")

        return self


class CorpusReport(BaseModel):
    """Scored evaluation report for a single corpus."""

    model_config = ConfigDict(extra="forbid")

    corpus: str
    metadata: RunMetadata
    dimensions: list[DimensionResult] = Field(default_factory=list)


def format_score(name: str, score: float | None) -> str:
    """Format numeric dimension score using banker's rounding."""
    if score is None:
        return "—"
    is_judged = score > 1.0 or any(
        k in name for k in ("judged", "groundedness", "faithfulness")
    )
    if is_judged:
        val = round(score, ROUND_JUDGED_DP)
        return f"{val:.{ROUND_JUDGED_DP}f}"
    val = round(score, ROUND_RATIO_DP)
    return f"{val:.{ROUND_RATIO_DP}f}"


def format_details(detail: dict[str, float]) -> str:
    """Format detail dictionary as comma-separated key-value pairs."""
    if not detail:
        return ""
    return ", ".join(f"{k}={v}" for k, v in detail.items())


def compute_result_hash(dimensions: list[DimensionResult]) -> str:
    """Compute deterministic SHA-256 hash over dimension names and statuses/scores."""
    payload_parts: list[str] = []
    for d in sorted(dimensions, key=lambda x: x.name):
        score_str = f"{d.score:.6f}" if d.score is not None else "none"
        payload_parts.append(f"{d.name}:{d.status}:{score_str}:{d.n}")
    payload = "\n".join(payload_parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def get_lock_hash(lock_path: Path | None = None) -> str:
    """Compute SHA-256 digest of uv.lock."""
    if lock_path is None:
        lock_path = Path(__file__).resolve().parents[2] / "uv.lock"
    if lock_path.is_file():
        try:
            return hashlib.sha256(lock_path.read_bytes()).hexdigest()[:16]
        except Exception:
            return "unknown-lock"
    return "no-lock"


def render_markdown(
    report: CorpusReport,
    compare_to_metadata: RunMetadata | None = None,
) -> str:
    """Render a CorpusReport to GitHub-flavored Markdown via Jinja2."""
    if report.metadata.partial:
        raise ReportError(
            "Cannot render report for partial run "
            "(partial: true set by --limit smoke knob)"
        )

    sample_size_diffs: list[str] = []
    if compare_to_metadata is not None:
        if (
            report.metadata.sample_size_deterministic
            != compare_to_metadata.sample_size_deterministic
        ):
            sample_size_diffs.append(
                f"Deterministic sample size changed from "
                f"{compare_to_metadata.sample_size_deterministic} to "
                f"{report.metadata.sample_size_deterministic}"
            )
        if (
            report.metadata.sample_size_judged
            != compare_to_metadata.sample_size_judged
        ):
            sample_size_diffs.append(
                f"Judged sample size changed from "
                f"{compare_to_metadata.sample_size_judged} to "
                f"{report.metadata.sample_size_judged}"
            )

    template_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=False,
    )
    template = env.get_template("report.md.j2")
    return template.render(
        report=report,
        sample_size_diffs=sample_size_diffs,
        format_score=format_score,
        format_details=format_details,
    )


def render_json(report: CorpusReport) -> str:
    """Render a CorpusReport to JSON with full float precision."""
    if report.metadata.partial:
        raise ReportError(
            "Cannot render report for partial run "
            "(partial: true set by --limit smoke knob)"
        )
    return report.model_dump_json(indent=2)


def emit_schema() -> str:
    """Emit the JSON Schema definition of CorpusReport."""
    return json.dumps(CorpusReport.model_json_schema(), indent=2) + "\n"
