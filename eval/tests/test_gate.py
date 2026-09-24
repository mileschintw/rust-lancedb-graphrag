"""Tests for staged-gate evaluation, committed thresholds, and budget caps."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from lancet_eval import thresholds as thresholds_module
from lancet_eval.dimensions import (
    DimensionResult,
    make_graph_presence_rate,
    make_paired_ablation_delta,
)
from lancet_eval.gate import (
    AGREEMENT_TARGET,
    CALIBRATION_SIZE,
    COMPLEMENT_TRIGGER,
    GRAPH_YIELD_INVESTIGATION_FLOOR,
    STAGED_PAIRING_COVERAGE_FLOOR,
    STAGED_SIZE,
    StagedGateVerdict,
    _find_budgets_file,
    _find_store_baseline_file,
    derive_judged_slice_size,
    evaluate_staged_gate,
    get_stage_cap,
    read_stage_caps,
    read_store_suspension,
)
from lancet_eval.journal import NodeTiming, RunRecord, WorkflowWireMeta
from lancet_eval.report import CorpusReport, RunMetadata


def _make_dummy_metadata() -> RunMetadata:
    return RunMetadata(
        corpus="multihop_rag",
        run_date="2026-09-09T00:00:00Z",
        commit_sha="dummy-sha",
        generation_model="gen-model",
        embedding_model="emb-model",
        judge_model="judge-model",
        judge_temperature=0.0,
        judge_prompt_version="v1",
        sampling_seed=42,
        sample_size_deterministic=50,
        sample_size_judged=0,
        index_generation="gen1",
        result_hash="hash1",
        arm_labels=["graph-on", "graph-off"],
        dependency_lock_hash="lock1",
        partial=True,
    )


def test_coverage_exactly_at_floor_satisfies() -> None:
    """Proves that a coverage value exactly at the 0.80 floor passes."""
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 40.0,  # 40 / 50 = 0.80
                    "pairing_coverage": 0.80,
                    "null_gold_drops": 5.0,
                    "n_answerable_in_sample": 45.0,
                },
                n=50,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.25,
                detail={"no_match_rate": 0.50},
                n=50,
            ),
        ],
    )
    verdict = evaluate_staged_gate(report, distinct_questions_in_journal=50)
    assert verdict.d44_staged_coverage == pytest.approx(0.80)
    assert verdict.coverage_outcome == "pass"


def test_presence_exactly_at_floor_satisfies() -> None:
    """Proves that presence rate exactly at the 0.20 floor passes."""
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 45.0,
                    "pairing_coverage": 0.90,
                    "null_gold_drops": 5.0,
                    "n_answerable_in_sample": 45.0,
                },
                n=50,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.20,  # Exactly at 0.20 floor
                detail={"no_match_rate": 0.50},
                n=50,
            ),
        ],
    )
    verdict = evaluate_staged_gate(report, distinct_questions_in_journal=50)
    assert verdict.presence_rate == pytest.approx(0.20)
    assert verdict.yield_outcome == "pass"


def test_complement_trigger_boundary() -> None:
    """Proves complement trigger does NOT fire at 0.80, and DOES fire above 0.80."""
    # Test at exactly 0.80
    report1 = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 45.0,
                    "pairing_coverage": 0.90,
                    "null_gold_drops": 5.0,
                    "n_answerable_in_sample": 45.0,
                },
                n=50,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.25,
                detail={"no_match_rate": 0.80},  # Exactly 0.80 -> trigger strictly above
                n=50,
            ),
        ],
    )
    verdict1 = evaluate_staged_gate(report1, distinct_questions_in_journal=50)
    assert not verdict1.complement_trigger_fired

    # Test strictly above 0.80
    report2 = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 45.0,
                    "pairing_coverage": 0.90,
                    "null_gold_drops": 5.0,
                    "n_answerable_in_sample": 45.0,
                },
                n=50,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.25,
                detail={"no_match_rate": 0.8001},  # > 0.80
                n=50,
            ),
        ],
    )
    verdict2 = evaluate_staged_gate(report2, distinct_questions_in_journal=50)
    assert verdict2.complement_trigger_fired


def test_zero_pairs_yields_empty_verdict_without_ratio() -> None:
    """Proves zero pairs yields empty verdict naming empty input and no computed ratio."""
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.0,
                detail={
                    "n_pairs": 0.0,
                    "pairing_coverage": 0.0,
                    "null_gold_drops": 0.0,
                    "n_answerable_in_sample": 50.0,
                },
                n=50,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.25,
                detail={"no_match_rate": 0.10},
                n=50,
            ),
        ],
    )
    verdict = evaluate_staged_gate(report, distinct_questions_in_journal=50)
    assert verdict.coverage_outcome == "empty"
    assert verdict.d44_staged_coverage is None
    assert "Empty input" in (verdict.reason or "")


def test_suspension_determination_skips_yield_comparison() -> None:
    """Proves suspension determination marks yield as suspended regardless of presence score."""
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 45.0,
                    "pairing_coverage": 0.90,
                    "null_gold_drops": 5.0,
                    "n_answerable_in_sample": 45.0,
                },
                n=50,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.05,  # Below 0.20, but suspended
                detail={"no_match_rate": 0.95},
                n=50,
            ),
        ],
    )
    verdict = evaluate_staged_gate(report, is_suspended=True, distinct_questions_in_journal=50)
    assert verdict.yield_outcome == "suspended"
    assert verdict.yield_suspended is True
    assert "suspended" in (verdict.reason or "").lower()


def test_absent_dimension_or_detail_key_raises() -> None:
    """Proves missing dimension or detail key raises ValueError instead of defaulting."""
    # Missing graph_presence_rate
    report_missing_dim = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 45.0,
                    "pairing_coverage": 0.90,
                    "null_gold_drops": 5.0,
                    "n_answerable_in_sample": 45.0,
                },
                n=50,
            ),
        ],
    )
    with pytest.raises(ValueError, match="Missing required dimension: graph_presence_rate"):
        evaluate_staged_gate(report_missing_dim, distinct_questions_in_journal=50)

    # Missing detail key in ablation
    report_missing_key = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={"pairing_coverage": 0.90},  # Missing n_pairs
                n=50,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.25,
                detail={"no_match_rate": 0.50},
                n=50,
            ),
        ],
    )
    with pytest.raises(ValueError, match="Missing required detail key in graph_ablation_delta: n_pairs"):
        evaluate_staged_gate(report_missing_key, distinct_questions_in_journal=50)


def test_key_lookups_match_dimensions_module_builders() -> None:
    """Proves key lookups bind to the actual names emitted by dimensions.py builders."""
    dummy_paired = type(
        "PairedResult",
        (),
        {
            "diffs": [0.1, 0.2],
            "mean": 0.15,
            "mean_diff": 0.15,
            "ci_lower": 0.1,
            "ci_upper": 0.2,
            "is_degenerate": False,
            "pair_count": 42,
            "pairing_coverage": 0.84,
            "answerable_count": 45,
            "strata": {},
            "strata_counts": {},
            "excluded_count": 0,
            "join_result": type(
                "JR",
                (),
                {
                    "single_arm_usable_drops": 1,
                    "missing_arm_drops": 2,
                    "null_gold_drops": 5,
                    "provenance_drops": 0,
                },
            )(),
        },
    )()
    dim_ablation = make_paired_ablation_delta(paired_result=dummy_paired)

    records = [
        RunRecord(
            corpus="multihop_rag",
            question_id=f"q{i}",
            graph_arm="graph-on",
            outcome="success",
            node_timings=[NodeTiming(node_name="ExtractGraphContext", duration_ms=100.0)],
            workflow_meta=WorkflowWireMeta(graph_node_count=1, graph_edge_count=1),
        )
        for i in range(10)
    ]
    dim_presence = make_graph_presence_rate(records=records)

    report = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[dim_ablation, dim_presence],
    )
    verdict = evaluate_staged_gate(report, distinct_questions_in_journal=50)
    assert verdict.d44_staged_coverage == pytest.approx(42 / 50.0)
    assert verdict.harness_pairing_coverage == pytest.approx(0.84)
    assert verdict.presence_rate == pytest.approx(1.0)


def test_coverage_statistic_separation_and_recomputation() -> None:
    """Proves d44_staged_coverage and harness_pairing_coverage are distinct and floor checks D-44."""
    # 8 pairs on a journal of 10 distinct questions:
    # Landed pairing_coverage = 8 / 10 = 0.80 (clears 0.80)
    # D-44 figure = 8 / 50 = 0.16 (fails 0.80)
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 8.0,
                    "pairing_coverage": 0.80,  # Journal-relative
                    "null_gold_drops": 1.0,
                    "n_answerable_in_sample": 9.0,
                },
                n=10,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.25,
                detail={"no_match_rate": 0.50},
                n=10,
            ),
        ],
    )
    verdict = evaluate_staged_gate(report, distinct_questions_in_journal=10)
    assert verdict.d44_staged_coverage == pytest.approx(8.0 / 50.0)  # 0.16
    assert verdict.harness_pairing_coverage == pytest.approx(0.80)
    assert verdict.d44_staged_coverage != verdict.harness_pairing_coverage
    # Must NOT produce a coverage pass!
    assert verdict.coverage_outcome != "pass"


def test_short_journal_fail_closed_hold() -> None:
    """Proves short journal (< 50 distinct questions) yields coverage outcome of hold."""
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 42.0,  # 42 / 50 = 0.84, would pass if evaluated solely on ratio
                    "pairing_coverage": 0.95,
                    "null_gold_drops": 2.0,
                    "n_answerable_in_sample": 44.0,
                },
                n=45,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.25,
                detail={"no_match_rate": 0.50},
                n=45,
            ),
        ],
    )
    verdict = evaluate_staged_gate(report, distinct_questions_in_journal=45)
    assert verdict.coverage_outcome == "hold"
    assert "Short journal" in (verdict.reason or "")
    assert "45 distinct questions in journal < locked stage size 50" in (verdict.reason or "")


def test_ceiling_arithmetic_rendered() -> None:
    """Proves achievable ceiling is (locked_size - null_gold) / locked_size and headroom is calculated."""
    report = CorpusReport(
        corpus="multihop_rag",
        metadata=_make_dummy_metadata(),
        dimensions=[
            DimensionResult(
                name="graph_ablation_delta",
                status="ok",
                score=0.05,
                detail={
                    "n_pairs": 40.0,
                    "pairing_coverage": 0.80,
                    "null_gold_drops": 5.0,
                    "n_answerable_in_sample": 45.0,
                },
                n=50,
            ),
            DimensionResult(
                name="graph_presence_rate",
                status="ok",
                score=0.25,
                detail={"no_match_rate": 0.50},
                n=50,
            ),
        ],
    )
    verdict = evaluate_staged_gate(report, distinct_questions_in_journal=50)
    assert verdict.d44_coverage_ceiling == pytest.approx(45.0 / 50.0)  # 0.90
    # Headroom = (0.90 - 0.80) * 50 = 5 drops
    assert verdict.headroom_answerable_drops == 5


def test_per_stage_caps_read_from_budgets() -> None:
    """Proves read_stage_caps parses 06.3.3-BUDGETS.md and raises on missing cap."""
    caps = read_stage_caps()
    assert caps["staged"] == 2.0
    assert caps["full"] == 5.0
    assert caps["judging"] == 5.0

    assert get_stage_cap("staged") == 2.0
    assert get_stage_cap("full_drive") == 5.0
    assert get_stage_cap("judging") == 5.0

    # Test error when file missing stage
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write("### Per-stage caps for 06.3.4 (D-47)\n| Stage | Cap (USD) | Notes |\n| Staged drive | $2.00 | locked |\n")
        tmp_name = f.name

    try:
        with pytest.raises(ValueError, match="Stage cap for 'Full two-arm drive' missing"):
            read_stage_caps(tmp_name)
    finally:
        import os
        os.unlink(tmp_name)


def test_derive_judged_slice_size_refusal_when_zero_judgeable_with_cached_verdicts() -> None:
    """Proves derive_judged_slice_size raises ValueError naming cached count when judgeable=0."""
    with pytest.raises(ValueError) as exc_info:
        derive_judged_slice_size(
            judgeable_count=0,
            stage_spend_cap=5.0,
            cost_per_question=0.01,
            cached_verdict_count=3,
        )
    assert "3" in str(exc_info.value)
    assert "cached verdict count" in str(exc_info.value)


def test_derive_judged_slice_size_zero_judgeable_zero_cached() -> None:
    """Proves genuinely empty population with 0 cached returns judgeable_count_is_zero."""
    chosen, reason = derive_judged_slice_size(
        judgeable_count=0,
        stage_spend_cap=5.0,
        cost_per_question=0.01,
        cached_verdict_count=0,
    )
    assert chosen == 0
    assert reason == "judgeable_count_is_zero"


def test_derive_judged_slice_size_coincident_bound() -> None:
    """Proves cap-derived bound exactly equal to judgeable count returns coincident."""
    chosen, reason = derive_judged_slice_size(
        judgeable_count=10,
        stage_spend_cap=0.10,
        cost_per_question=0.01,
        cached_verdict_count=0,
    )
    assert chosen == 10
    assert reason == "coincident"


def test_find_budgets_and_baseline_files_ambiguity_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Proves _find_budgets_file and _find_store_baseline_file raise naming all candidates on ambiguity."""
    monkeypatch.setattr("lancet_eval.gate.repo_root", lambda: tmp_path)
    p1 = tmp_path / ".planning" / "phases" / "06.3.3-first"
    p2 = tmp_path / ".planning" / "phases" / "06.3.3-second"
    p1.mkdir(parents=True)
    p2.mkdir(parents=True)

    b1 = p1 / "06.3.3-BUDGETS.md"
    b2 = p2 / "06.3.3-BUDGETS.md"
    b1.write_text("dummy budgets 1", encoding="utf-8")
    b2.write_text("dummy budgets 2", encoding="utf-8")

    s1 = p1 / "06.3.3-STORE-BASELINE.md"
    s2 = p2 / "06.3.3-STORE-BASELINE.md"
    s1.write_text("dummy store 1", encoding="utf-8")
    s2.write_text("dummy store 2", encoding="utf-8")

    with pytest.raises(FileNotFoundError) as exc_info:
        _find_budgets_file()
    msg = str(exc_info.value)
    assert "06.3.3-first" in msg
    assert "06.3.3-second" in msg

    with pytest.raises(FileNotFoundError) as exc_info:
        _find_store_baseline_file()
    msg = str(exc_info.value)
    assert "06.3.3-first" in msg
    assert "06.3.3-second" in msg


# --- 06.3.4.1 D-69/D-73 drive-1 companion literals ------------------------------------


def test_citation_rejection_tripwire_committed() -> None:
    """CITATION_REJECTION_TRIPWIRE is committed as a float before paid drive 1."""
    assert hasattr(thresholds_module, "CITATION_REJECTION_TRIPWIRE")
    value = thresholds_module.CITATION_REJECTION_TRIPWIRE
    assert isinstance(value, float)
    assert value == pytest.approx(0.159)


def test_citation_rejection_null_baseline_committed() -> None:
    """CITATION_REJECTION_NULL_BASELINE is committed as (numerator, denominator)."""
    assert hasattr(thresholds_module, "CITATION_REJECTION_NULL_BASELINE")
    value = thresholds_module.CITATION_REJECTION_NULL_BASELINE
    assert isinstance(value, tuple)
    assert value == (29, 42)


def test_sc2_timeout_dominance_rule_committed() -> None:
    """SC2_TIMEOUT_DOMINANCE_RULE is committed as a string reading of 'dominant'."""
    assert hasattr(thresholds_module, "SC2_TIMEOUT_DOMINANCE_RULE")
    value = thresholds_module.SC2_TIMEOUT_DOMINANCE_RULE
    assert isinstance(value, str)
    assert value == "plurality_tie_is_dominant"


def test_final_answer_missing_review_rate_committed() -> None:
    """FINAL_ANSWER_MISSING_REVIEW_RATE is committed as a float review trigger."""
    assert hasattr(thresholds_module, "FINAL_ANSWER_MISSING_REVIEW_RATE")
    value = thresholds_module.FINAL_ANSWER_MISSING_REVIEW_RATE
    assert isinstance(value, float)
    assert value == pytest.approx(0.10)


def test_vector_baseline_usable_floor_not_yet_committed() -> None:
    """D-73: VECTOR_BASELINE_USABLE_FLOOR must NOT exist yet -- 06.3.4.1-10 commits it
    after G is fixed. unpark_gates.evaluate_sc3 must never default it."""
    assert not hasattr(thresholds_module, "VECTOR_BASELINE_USABLE_FLOOR")

