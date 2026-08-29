"""Report models, markdown/JSON renderers, and schema generation."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field

from lancet_eval.dimensions import DimensionResult

ROUND_RATIO_DP: int = 3
ROUND_JUDGED_DP: int = 2


class RunMetadata(BaseModel):
    """Execution metadata stamped on every evaluation report."""

    model_config = ConfigDict(extra="forbid")

    corpus: str
    generated_at: str
    commit_sha: str = "unknown"
    sample_size_deterministic: int = 0
    sample_size_judged: int = 0
    notes: str = ""


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


def render_markdown(report: CorpusReport) -> str:
    """Render a CorpusReport to GitHub-flavored Markdown via Jinja2."""
    template_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        autoescape=False,
    )
    template = env.get_template("report.md.j2")
    return template.render(
        report=report,
        format_score=format_score,
        format_details=format_details,
    )


def render_json(report: CorpusReport) -> str:
    """Render a CorpusReport to JSON with full float precision."""
    return report.model_dump_json(indent=2)


def emit_schema() -> str:
    """Emit the JSON Schema definition of CorpusReport."""
    return json.dumps(CorpusReport.model_json_schema(), indent=2) + "\n"
