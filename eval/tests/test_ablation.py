"""Tests for paired ablation deltas, coverage, stratification, and cost deltas."""

from pathlib import Path

import pytest

from lancet_eval.client import Notice
from lancet_eval.corpus import GoldQuestion
from lancet_eval.dimensions import (
    REGISTERED_DIMENSIONS,
    make_paired_ablation_delta,
)
from lancet_eval.journal import (
    Journal,
    RetrievalSnapshot,
    RunRecord,
    StructuredCitation,
    WorkflowWireMeta,
)
from lancet_eval.pairing import (
    ArmPair,
    compute_paired_delta,
)
from lancet_eval.report import render_markdown
from lancet_eval.score import score_run


def _make_gold(
    qid: str,
    qtype: str = "comparison",
    is_null: bool = False,
    facts: list[str] | None = None,
) -> GoldQuestion:
    f = [] if is_null else (facts or ["fact1", "fact2"])
    ev = [] if is_null else [{"fact": x} for x in f]
    return GoldQuestion(
        question_id=qid,
        question=f"Question {qid}?",
        question_type=qtype,
        gold_facts=f,
        gold_answer="expected answer",
        evidence_list=ev,
    )


def _make_record(
    qid: str,
    arm: str,
    *,
    outcome: str = "success",
    notices: list[Notice] | None = None,
    answer: str = "expected answer",
    duration_ms: float = 100.0,
    chunks: list[StructuredCitation] | None = None,
    workflow_meta: WorkflowWireMeta | None = None,
    index_generation: str = "gen-1",
) -> RunRecord:
    ns = (
        notices
        if notices is not None
        else (
            [Notice(code="GRAPH_ABLATION", message="", typed_code=18)]
            if arm == "graph-off"
            else []
        )
    )
    doc_id = "01070ac6-0fc0-464d-9f1f-756573b99c0e"
    snap = RetrievalSnapshot(
        index_generation=index_generation,
        retrieved_chunks=chunks
        if chunks is not None
        else [
            StructuredCitation(
                chunk_id="c1", document_id=doc_id, excerpt="fact1", rank=1
            )
        ],
    )
    return RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm=arm,
        outcome=outcome,
        index_generation=index_generation,
        notices=ns,
        answer=answer,
        duration_ms=duration_ms,
        snapshot=snap,
        workflow_meta=workflow_meta,
    )


def test_ablation_ten_questions_six_pairs() -> None:
    """Proves 10 attempted questions with 6 paired yields coverage=0.6."""
    gold_map = {f"q{i}": _make_gold(f"q{i}") for i in range(10)}
    pairs: list[ArmPair] = []
    for i in range(6):
        qid = f"q{i}"
        pairs.append(
            ArmPair(
                qid,
                _make_record(qid, "graph-on"),
                _make_record(qid, "graph-off"),
                gold_map[qid],
            )
        )

    # Compute paired delta for a dummy score function
    res = compute_paired_delta(
        pairs,
        lambda rec, gold: 1.0 if rec.graph_arm == "graph-on" else 0.5,
        coverage_denominator=10,
        answerable_count=10,
    )
    assert res.pair_count == 6
    assert res.pairing_coverage == 0.6
    assert res.answerable_count == 10

    dim = make_paired_ablation_delta(paired_result=res)
    assert dim.status == "ok"
    assert dim.detail["n_pairs"] == 6.0
    assert dim.detail["pairing_coverage"] == 0.6
    assert dim.detail["n_answerable_in_sample"] == 10.0


def test_ablation_zero_pairs_error_and_rendered() -> None:
    """Proves 0 pairs yields status=error, score=None, with counts in detail."""
    res = compute_paired_delta(
        [],
        lambda rec, gold: 1.0,
        coverage_denominator=10,
        answerable_count=10,
    )
    dim = make_paired_ablation_delta(name="graph_ablation_delta", paired_result=res)
    assert dim.status == "error"
    assert dim.score is None
    assert dim.detail["n_pairs"] == 0.0
    assert dim.detail["pairing_coverage"] == 0.0

    # Test rendering of report containing this dimension
    from lancet_eval.report import CorpusReport, RunMetadata

    meta = RunMetadata(
        corpus="multihop_rag",
        run_date="2026-09-05T12:00:00Z",
        commit_sha="abcdef1234567890123456789012345678901234",
        generation_model="deepseek/v3",
        embedding_model="voyage/v4",
        judge_model="meta-llama/70b",
        judge_prompt_version="v1",
        index_generation="gen-1",
        result_hash="hash-1",
        dependency_lock_hash="lock-1",
        sample_size_deterministic=10,
        sample_size_judged=0,
        arm_labels=["graph-on", "graph-off"],
    )
    report = CorpusReport(corpus="multihop_rag", metadata=meta, dimensions=[dim])
    md = render_markdown(report)
    assert "graph_ablation_delta" in md
    assert "error" in md


def test_ablation_one_pair_degenerate() -> None:
    """Proves 1 pair yields status=ok, equal bounds, and degenerate marker."""
    g = _make_gold("q1")
    pair = ArmPair(
        "q1", _make_record("q1", "graph-on"), _make_record("q1", "graph-off"), g
    )
    res = compute_paired_delta(
        [pair],
        lambda rec, gold: 0.8 if rec.graph_arm == "graph-on" else 0.3,
        coverage_denominator=1,
        answerable_count=1,
    )
    dim = make_paired_ablation_delta(paired_result=res)
    assert dim.status == "ok"
    assert dim.score == pytest.approx(0.5)
    assert dim.detail["ci_lower"] == pytest.approx(0.5)
    assert dim.detail["ci_upper"] == pytest.approx(0.5)
    assert dim.detail["degenerate_ci"] == 1.0


def test_ablation_stratification_present_and_absent() -> None:
    """Proves stratification keys appear for populated types and absent for empty."""
    g_comp = _make_gold("q1", qtype="comparison")
    g_temp = _make_gold("q2", qtype="temporal")
    p1 = ArmPair(
        "q1", _make_record("q1", "graph-on"), _make_record("q1", "graph-off"), g_comp
    )
    p2 = ArmPair(
        "q2", _make_record("q2", "graph-on"), _make_record("q2", "graph-off"), g_temp
    )

    res = compute_paired_delta(
        [p1, p2],
        lambda rec, gold: 0.9 if rec.graph_arm == "graph-on" else 0.4,
        coverage_denominator=2,
        answerable_count=2,
    )
    dim = make_paired_ablation_delta(paired_result=res)
    assert "delta_comparison" in dim.detail
    assert "delta_temporal" in dim.detail
    assert "delta_inference" not in dim.detail


def test_ablation_null_question_never_contributes() -> None:
    """Proves null gold question is excluded from diffs and strata."""
    g_null = _make_gold("q_null", is_null=True)
    p_null = ArmPair(
        "q_null",
        _make_record("q_null", "graph-on"),
        _make_record("q_null", "graph-off"),
        g_null,
    )

    res = compute_paired_delta(
        [p_null],
        lambda rec, gold: 1.0,
        coverage_denominator=1,
        answerable_count=0,
    )
    assert res.pair_count == 0
    assert res.excluded_count == 1


def test_wr02_end_to_end_all_three_consumers(tmp_path: Path) -> None:
    """Proves deduplication yields 1 pair and reports collapsed_records_n."""
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    qid = "mhr-0073ab564e55"

    # Question q1 with 2 graph-on records and 1 graph-off record
    r1_on = _make_record(qid, "graph-on", answer="ans1")
    r2_on = _make_record(qid, "graph-on", answer="ans2")
    r_off = _make_record(qid, "graph-off", answer="ans_off")

    journal.append(r1_on)
    journal.append(r2_on)
    journal.append(r_off)

    report = score_run(run_dir=tmp_path, no_judge=True)

    # 1. Integrity dimension reports collapsed_records_n = 1
    unusable_dim = next(
        d for d in report.dimensions if d.name == "unusable_record_rate"
    )
    assert unusable_dim.detail["collapsed_records_n"] == 1.0

    # 2. Pairing reports 1 pair
    ablation_dim = next(
        d for d in report.dimensions if d.name == "graph_ablation_delta"
    )
    assert ablation_dim.status == "ok"
    assert ablation_dim.detail["n_pairs"] == 1.0


def test_wr02_journal_wide_placement_behavioral(tmp_path: Path) -> None:
    """Proves deduplication precedes arm grouping so each quality dim counts 1."""
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    qid = "mhr-0073ab564e55"

    r1_on = _make_record(qid, "graph-on", answer="old_ans")
    r2_on = _make_record(qid, "graph-on", answer="new_ans")
    journal.append(r1_on)
    journal.append(r2_on)

    report = score_run(run_dir=tmp_path, no_judge=True)

    for dim_name in ["answer_exact_match", "answer_f1", "retrieval_evidence_coverage"]:
        dim = next(d for d in report.dimensions if d.name == dim_name)
        assert dim.n == 1


def test_additional_paired_deltas_hand_computed_three_pairs() -> None:
    """Proves 4 additional deltas equal hand-computed means on 3-pair fixture."""
    g1 = _make_gold("q1", facts=["f1", "f2"])
    g2 = _make_gold("q2", facts=["f1", "f2"])
    g3 = _make_gold("q3", facts=["f1", "f2"])

    # q1: on=1.0, off=0.0 -> diff=1.0
    # q2: on=0.5, off=0.5 -> diff=0.0
    # q3: on=0.2, off=0.8 -> diff=-0.6
    # mean diff = (1.0 + 0.0 - 0.6) / 3 = 0.4 / 3 ≈ 0.13333333333333333
    pairs = [
        ArmPair(
            "q1", _make_record("q1", "graph-on"), _make_record("q1", "graph-off"), g1
        ),
        ArmPair(
            "q2", _make_record("q2", "graph-on"), _make_record("q2", "graph-off"), g2
        ),
        ArmPair(
            "q3", _make_record("q3", "graph-on"), _make_record("q3", "graph-off"), g3
        ),
    ]

    scores_on = {"q1": 1.0, "q2": 0.5, "q3": 0.2}
    scores_off = {"q1": 0.0, "q2": 0.5, "q3": 0.8}

    def score_fn(rec: RunRecord, gold: GoldQuestion) -> float | None:
        return (
            scores_on[gold.question_id]
            if rec.graph_arm == "graph-on"
            else scores_off[gold.question_id]
        )

    res = compute_paired_delta(
        pairs, score_fn, coverage_denominator=3, answerable_count=3
    )
    assert res.mean == pytest.approx(0.4 / 3)


def test_no_judged_metric_paired_in_registry() -> None:
    """Proves registry never pairs judged dimensions (groundedness, faithfulness)."""
    paired_names = [n for n in REGISTERED_DIMENSIONS if n.startswith("graph_ablation")]
    for n in paired_names:
        assert "groundedness" not in n
        assert "faithfulness" not in n


def test_latency_delta_includes_graph_off_early_return() -> None:
    """Proves latency delta computes duration diff with graph-off early return."""
    g1 = _make_gold("q1")
    # on: duration 250ms, off: early return 50ms -> diff = 200ms
    r_on = _make_record("q1", "graph-on", duration_ms=250.0)
    r_off = _make_record("q1", "graph-off", duration_ms=50.0)
    pairs = [ArmPair("q1", r_on, r_off, g1)]

    res = compute_paired_delta(
        pairs,
        lambda rec, gold: float(rec.duration_ms),
        coverage_denominator=1,
        answerable_count=1,
    )
    assert res.mean == pytest.approx(200.0)
    dim = make_paired_ablation_delta(
        name="graph_ablation_latency_delta", paired_result=res
    )
    assert dim.status == "ok"
    assert dim.score == pytest.approx(200.0)


def test_prompt_token_delta_skipped_when_no_metadata(tmp_path: Path) -> None:
    """Proves prompt token delta is skipped when no record carries workflow metadata."""
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    qid = "mhr-0073ab564e55"

    r_on = _make_record(qid, "graph-on", workflow_meta=None)
    r_off = _make_record(qid, "graph-off", workflow_meta=None)
    journal.append(r_on)
    journal.append(r_off)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim = next(
        d for d in report.dimensions if d.name == "graph_ablation_prompt_token_delta"
    )
    assert dim.status == "skipped"
    assert "workflow_meta" in (dim.reason or "")
    assert dim.score is None


def test_report_renders_all_ablation_family_rows(tmp_path: Path) -> None:
    """Proves rendered report contains rows for all 7 ablation family dimensions."""
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    qid = "mhr-0073ab564e55"

    r_on = _make_record(
        qid, "graph-on", workflow_meta=WorkflowWireMeta(prompt_tokens=100)
    )
    r_off = _make_record(
        qid, "graph-off", workflow_meta=WorkflowWireMeta(prompt_tokens=80)
    )
    journal.append(r_on)
    journal.append(r_off)

    report = score_run(run_dir=tmp_path, no_judge=True)
    md = render_markdown(report)

    ablation_names = [
        n for n in REGISTERED_DIMENSIONS if n.startswith("graph_ablation")
    ]
    assert len(ablation_names) >= 7
    for name in ablation_names:
        assert name in md


def test_paired_ablation_payload_exclusion_across_all_five_metrics(
    tmp_path: Path,
) -> None:
    from lancet_eval.corpus import load_sample_questions

    questions = [
        q for q in load_sample_questions("multihop_rag") if not q.is_null
    ][:5]
    assert len(questions) == 5

    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.write_header(corpus="multihop_rag", partial=False)

    # 3 fully-populated pairs (i = 0, 1, 2)
    # 2 pairs where graph-off is payload-less (i = 3, 4)
    for i, q in enumerate(questions):
        r_on = _make_record(
            q.question_id,
            "graph-on",
            answer=q.gold_answer or "expected answer",
        )
        journal.append(r_on)

        if i < 3:
            r_off = _make_record(
                q.question_id,
                "graph-off",
                answer=q.gold_answer or "expected answer",
            )
        else:
            r_off = RunRecord(
                corpus="multihop_rag",
                question_id=q.question_id,
                graph_arm="graph-off",
                outcome="success",
                answer="",
                snapshot=None,
                node_failures=[],
                notices=[
                    Notice(code="GRAPH_ABLATION", message="", typed_code=18)
                ],
                duration_ms=100.0,
                index_generation="gen-1",
            )
        journal.append(r_off)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}

    five_paired_metrics = [
        "graph_ablation_delta",
        "graph_ablation_delta_exact_match",
        "graph_ablation_delta_f1",
        "graph_ablation_delta_context_precision",
        "graph_ablation_delta_ranking_quality",
    ]

    for name in five_paired_metrics:
        assert name in dim_map, f"Missing paired dimension {name}"
        d = dim_map[name]
        assert d.n == 3, f"{name}.n expected 3, got {d.n}"
        assert d.detail.get("excluded_unscorable_pairs") == 2.0, (
            f"{name} excluded_unscorable_pairs expected 2.0, got "
            f"{d.detail.get('excluded_unscorable_pairs')}"
        )

