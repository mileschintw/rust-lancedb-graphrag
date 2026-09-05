"""Tests for evaluation report rendering, metadata, and comparisons."""

import json
from pathlib import Path

import pytest

from lancet_eval.dimensions import (
    OBS_04_PLACEHOLDER,
    REGISTERED_DIMENSIONS,
    DimensionResult,
)
from lancet_eval.report import (
    CorpusReport,
    ReportError,
    RunMetadata,
    render_json,
    render_markdown,
)


def _valid_metadata() -> dict[str, object]:
    return {
        "corpus": "multihop_rag",
        "run_date": "2026-08-29T12:00:00Z",
        "commit_sha": "abcdef123456",
        "generation_model": "deepseek/deepseek-v4-flash-0731",
        "embedding_model": "voyageai/voyage-4-large",
        "judge_model": "meta-llama/llama-3.3-70b-instruct",
        "judge_prompt_version": "v1",
        "index_generation": "gen-01",
        "result_hash": "res-hash-01",
        "dependency_lock_hash": "lock-hash-01",
        "sample_size_deterministic": 500,
        "sample_size_judged": 100,
        "arm_labels": ["graph-on", "graph-off"],
        "partial": False,
    }


@pytest.mark.parametrize(
    "blank_field",
    [
        "corpus",
        "run_date",
        "commit_sha",
        "generation_model",
        "embedding_model",
        "judge_model",
        "judge_prompt_version",
        "index_generation",
        "result_hash",
        "dependency_lock_hash",
    ],
)
def test_run_metadata_blanks_raise_validation_error(blank_field: str) -> None:
    """Proves RunMetadata rejects missing or blank required pin fields."""
    data = _valid_metadata()
    data[blank_field] = ""
    with pytest.raises(ValueError) as exc_info:
        RunMetadata.model_validate(data)
    assert blank_field in str(exc_info.value)


def test_partial_run_refuses_to_render() -> None:
    """Proves rendering a partial run raises ReportError naming partial: true flag."""
    data = _valid_metadata()
    data["partial"] = True
    metadata = RunMetadata.model_validate(data)
    report = CorpusReport(corpus="multihop_rag", metadata=metadata)

    with pytest.raises(ReportError) as exc_info_md:
        render_markdown(report)
    assert "partial: true" in str(exc_info_md.value)

    with pytest.raises(ReportError) as exc_info_json:
        render_json(report)
    assert "partial: true" in str(exc_info_json.value)


def test_no_cross_corpus_aggregation() -> None:
    """Proves rendering two corpora produces two independent reports."""
    m1 = RunMetadata.model_validate(_valid_metadata())
    data2 = _valid_metadata()
    data2["corpus"] = "graphrag_bench"
    m2 = RunMetadata.model_validate(data2)

    r1 = CorpusReport(corpus="multihop_rag", metadata=m1)
    r2 = CorpusReport(corpus="graphrag_bench", metadata=m2)

    assert r1.corpus != r2.corpus
    for field in CorpusReport.model_fields:
        for forbidden in ("aggregate", "combined", "overall"):
            assert forbidden not in field.lower()


def test_registered_dimensions_rendered_with_status_and_reasons() -> None:
    """Proves all registered dimensions appear in report with scores and details."""
    metadata = RunMetadata.model_validate(_valid_metadata())
    dims: list[DimensionResult] = []

    for name in REGISTERED_DIMENSIONS:
        if name == "community_summary_quality":
            dims.append(OBS_04_PLACEHOLDER)
        elif name == "abstention_on_unanswerable":
            dims.append(
                DimensionResult(
                    name=name,
                    status="skipped",
                    reason="Corpus contains no unanswerable questions",
                    n=0,
                )
            )
        else:
            dims.append(
                DimensionResult(
                    name=name,
                    status="ok",
                    score=0.85,
                    detail={"sample_diagnostic": 1.0},
                    n=50,
                )
            )

    report = CorpusReport(corpus="multihop_rag", metadata=metadata, dimensions=dims)
    md = render_markdown(report)

    for name in REGISTERED_DIMENSIONS:
        assert f"`{name}`" in md
        # Check that rows with detail render at least one detail key
        if name not in ("community_summary_quality", "abstention_on_unanswerable"):
            row = next(line for line in md.splitlines() if f"`{name}`" in line)
            assert "sample_diagnostic=" in row

    # Assert OBS-04 placeholder renders reason without number
    obs_rows = [
        line_text
        for line_text in md.splitlines()
        if "community_summary_quality" in line_text
    ]
    assert len(obs_rows) == 1
    assert "—" in obs_rows[0]
    assert "999.1" in obs_rows[0]


def test_detail_float_renders_rounded() -> None:
    """Proves long-precision detail float is rounded without binary precision."""
    metadata = RunMetadata.model_validate(_valid_metadata())
    dims = [
        DimensionResult(
            name="retrieval_evidence_coverage",
            status="ok",
            score=0.75,
            detail={"ci_lower": 0.1234567890123},
            n=50,
        )
    ]
    report = CorpusReport(corpus="multihop_rag", metadata=metadata, dimensions=dims)
    md = render_markdown(report)
    assert "0.1234567890123" not in md
    assert "ci_lower=0.123" in md


def test_integral_detail_float_renders_without_decimal() -> None:
    """Proves integral detail float renders as integer without trailing zeros."""
    metadata = RunMetadata.model_validate(_valid_metadata())
    dims = [
        DimensionResult(
            name="graph_ablation_f1_delta",
            status="ok",
            score=0.05,
            detail={"n_pairs": 6.0},
            n=6,
        )
    ]
    report = CorpusReport(corpus="multihop_rag", metadata=metadata, dimensions=dims)
    md = render_markdown(report)
    assert "n_pairs=6" in md
    assert "n_pairs=6.0" not in md
    assert "n_pairs=6.000" not in md


def test_latency_dimension_above_one_renders_one_decimal() -> None:
    """Proves millisecond/latency dimension > 1.0 renders at 1 decimal place, not 2."""
    metadata = RunMetadata.model_validate(_valid_metadata())
    dims = [
        DimensionResult(
            name="retrieve_latency_ms",
            status="ok",
            score=1234.5678,
            n=100,
        )
    ]
    report = CorpusReport(corpus="multihop_rag", metadata=metadata, dimensions=dims)
    md = render_markdown(report)
    row = next(line for line in md.splitlines() if "`retrieve_latency_ms`" in line)
    assert "1234.6" in row
    assert "1234.57" not in row


def test_genuine_judged_dimension_renders_two_decimals() -> None:
    """Proves genuine judged dimensions still render at 2 decimal places."""
    metadata = RunMetadata.model_validate(_valid_metadata())
    dims = [
        DimensionResult(
            name="answer_groundedness",
            status="ok",
            score=4.256,
            n=50,
        )
    ]
    report = CorpusReport(corpus="multihop_rag", metadata=metadata, dimensions=dims)
    md = render_markdown(report)
    row = next(line for line in md.splitlines() if "`answer_groundedness`" in line)
    assert "4.26" in row


def test_rounding_caveat_describes_all_three_conventions() -> None:
    """Proves methodology caveat covers ratios, judged scales, and magnitudes."""
    metadata = RunMetadata.model_validate(_valid_metadata())
    report = CorpusReport(corpus="multihop_rag", metadata=metadata)
    md = render_markdown(report)
    assert "3 decimals for ratios" in md
    assert "2 decimals for judged scales" in md
    assert (
        "1 decimal for absolute magnitudes such as latency milliseconds "
        "and prompt token counts" in md
    )


def test_all_normative_caveats_present_in_markdown() -> None:
    """Proves all required caveat statements appear in rendered report."""
    metadata = RunMetadata.model_validate(_valid_metadata())
    report = CorpusReport(corpus="multihop_rag", metadata=metadata)
    md = render_markdown(report)

    required_caveats = [
        "A retrieved chunk matches a gold fact if and only if",
        "Every retrieval metric is computed over the response's retrieved-chunk list",
        "Gold facts longer than the corpus's chunk size cannot appear verbatim",
        "Lancet's answer metrics are not comparable to the MultiHop-RAG paper",
        "Neither reported ranking metric is the MultiHop-RAG paper's own convention",
        (
            "Infrastructure-failed records (unusable records) are excluded "
            "from every quality denominator"
        ),
        "A graph-off record that fails provenance verification is excluded",
        "This report is advisory only with no automated pass/fail gate",
    ]

    for caveat in required_caveats:
        assert caveat in md, f"Missing required caveat in markdown: {caveat}"


def test_comparison_to_previous_run_sample_size_diff() -> None:
    """Proves comparing to a previous run with different sample size renders diff."""
    current_meta = RunMetadata.model_validate(_valid_metadata())
    prev_data = _valid_metadata()
    prev_data["sample_size_deterministic"] = 300
    prev_data["sample_size_judged"] = 50
    prev_meta = RunMetadata.model_validate(prev_data)

    report = CorpusReport(corpus="multihop_rag", metadata=current_meta)
    md = render_markdown(report, compare_to_metadata=prev_meta)

    assert "Sample Size Differences Detected" in md
    assert "Deterministic sample size changed from 300 to 500" in md
    assert "Judged sample size changed from 50 to 100" in md


def test_report_cli_generates_artifacts_offline(tmp_path: Path) -> None:
    """Proves report command generates report.md, report.json offline."""
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    runner = CliRunner()
    meta = RunMetadata.model_validate(_valid_metadata())
    dim = DimensionResult(name="answer_f1", status="ok", score=0.92, n=100)
    report = CorpusReport(corpus="multihop_rag", metadata=meta, dimensions=[dim])

    # Save initial report.json
    with open(tmp_path / "report.json", "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    res = runner.invoke(app, ["report", "--run", str(tmp_path)])
    assert res.exit_code == 0
    assert (tmp_path / "report.md").is_file()
    assert (tmp_path / "report.json").is_file()
    assert (tmp_path / "metadata.json").is_file()


def test_report_cli_refuses_partial_run(tmp_path: Path) -> None:
    """Proves report command exits non-zero on partial run naming partial: true."""
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    runner = CliRunner()
    data = _valid_metadata()
    data["partial"] = True
    meta = RunMetadata.model_validate(data)
    report = CorpusReport(corpus="multihop_rag", metadata=meta)

    with open(tmp_path / "report.json", "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    res = runner.invoke(app, ["report", "--run", str(tmp_path)])
    assert res.exit_code != 0
    assert "partial: true" in res.output


def test_report_cli_refuses_incomplete_metadata(tmp_path: Path) -> None:
    """Proves report command exits non-zero when metadata has blank required pins."""
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    runner = CliRunner()
    data = _valid_metadata()
    data["commit_sha"] = ""  # Blank required pin

    # Write corrupt report directly
    raw_dict = {
        "corpus": "multihop_rag",
        "metadata": data,
        "dimensions": [],
    }
    with open(tmp_path / "report.json", "w", encoding="utf-8") as f:
        json.dump(raw_dict, f)

    res = runner.invoke(app, ["report", "--run", str(tmp_path)])
    assert res.exit_code != 0
    assert "commit_sha" in res.output


def test_report_cli_compare_to_renders_warning(tmp_path: Path) -> None:
    """Proves report CLI with --compare-to renders sample size diff callouts."""
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    runner = CliRunner()

    # Setup run A
    dir_a = tmp_path / "run_a"
    dir_a.mkdir()
    data_a = _valid_metadata()
    data_a["sample_size_judged"] = 50
    meta_a = RunMetadata.model_validate(data_a)
    report_a = CorpusReport(corpus="multihop_rag", metadata=meta_a)
    with open(dir_a / "report.json", "w", encoding="utf-8") as f:
        f.write(report_a.model_dump_json(indent=2))

    # Setup run B
    dir_b = tmp_path / "run_b"
    dir_b.mkdir()
    data_b = _valid_metadata()
    data_b["sample_size_judged"] = 100
    meta_b = RunMetadata.model_validate(data_b)
    report_b = CorpusReport(corpus="multihop_rag", metadata=meta_b)
    with open(dir_b / "report.json", "w", encoding="utf-8") as f:
        f.write(report_b.model_dump_json(indent=2))

    res = runner.invoke(
        app,
        ["report", "--run", str(dir_b), "--compare-to", str(dir_a)],
    )
    assert res.exit_code == 0
    md_content = (dir_b / "report.md").read_text(encoding="utf-8")
    assert "Sample Size Differences Detected" in md_content
    assert "Judged sample size changed from 50 to 100" in md_content


def test_report_cli_exits_zero_regardless_of_metric_values(tmp_path: Path) -> None:
    """Proves D-54: report is advisory only and exits 0 even on zero scores."""
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    runner = CliRunner()
    meta = RunMetadata.model_validate(_valid_metadata())
    dim_zero = DimensionResult(name="answer_f1", status="ok", score=0.0, n=100)
    report = CorpusReport(corpus="multihop_rag", metadata=meta, dimensions=[dim_zero])

    with open(tmp_path / "report.json", "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    res = runner.invoke(app, ["report", "--run", str(tmp_path)])
    assert res.exit_code == 0


def test_matching_rule_caveat_matches_implemented_rule() -> None:
    """Proves Evidence Matching Rule caveat reflects unidirectional containment."""
    meta = RunMetadata.model_validate(_valid_metadata())
    report = CorpusReport(corpus="multihop_rag", metadata=meta)
    md = render_markdown(report)

    assert "boundary_attributable_misses" in md
    assert (
        "chunk's normalized text contains the fact's normalized text "
        "as a contiguous substring"
    ) in md
    assert "or the fact's normalized text contains the chunk's text" not in md
