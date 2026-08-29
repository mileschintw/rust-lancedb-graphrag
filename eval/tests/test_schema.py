"""Tests for report schema identity, field constraints, and rendering."""

import json

from lancet_eval.config import repo_root
from lancet_eval.dimensions import OBS_04_PLACEHOLDER, DimensionResult
from lancet_eval.report import (
    CorpusReport,
    RunMetadata,
    emit_schema,
    render_json,
    render_markdown,
)


def test_schema_file_byte_identical() -> None:
    schema_path = repo_root() / "eval" / "report.schema.json"
    assert schema_path.is_file(), f"Missing schema file at {schema_path}"
    with open(schema_path, encoding="utf-8") as f:
        committed_schema = f.read()

    generated_schema = emit_schema()
    assert committed_schema == generated_schema


def test_corpus_report_forbids_cross_corpus_fields() -> None:
    forbidden_substrings = ("aggregate", "combined", "overall")
    for field_name in CorpusReport.model_fields:
        for sub in forbidden_substrings:
            assert sub not in field_name.lower(), (
                f"CorpusReport field {field_name!r} contains forbidden "
                f"substring {sub!r}"
            )


def test_render_markdown_obs_04_row() -> None:
    metadata = RunMetadata(
        corpus="multihop_rag",
        generated_at="2026-08-29T12:00:00Z",
        commit_sha="abcdef123456",
        sample_size_deterministic=500,
        sample_size_judged=50,
    )
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=metadata,
        dimensions=[OBS_04_PLACEHOLDER],
    )

    md = render_markdown(report)
    lines = md.splitlines()

    # Find the table row for community_summary_quality
    obs_rows = [line for line in lines if "community_summary_quality" in line]
    assert len(obs_rows) == 1
    obs_row = obs_rows[0]

    # Verify status is skipped, reason present, no numeric score cell
    cells = [c.strip() for c in obs_row.split("|") if c.strip()]
    assert cells[0] == "`community_summary_quality`"
    assert cells[1] == "skipped"
    assert cells[2] == "—"
    assert "999.1" in cells[3]


def test_render_precision_and_rounding() -> None:
    metadata = RunMetadata(
        corpus="multihop_rag",
        generated_at="2026-08-29T12:00:00Z",
    )
    dim = DimensionResult(
        name="evidence_recall_at_4",
        status="ok",
        score=0.123456,
    )
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=metadata,
        dimensions=[dim],
    )

    md = render_markdown(report)
    assert "0.123" in md
    assert "0.123456" not in md
    assert "banker's rounding" in md

    json_str = render_json(report)
    data = json.loads(json_str)
    assert data["dimensions"][0]["score"] == 0.123456
