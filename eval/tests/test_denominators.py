"""Tests for shared quality and path-health denominators.
Covers retrieval and answer metrics.
"""

from pathlib import Path

import pytest

from lancet_eval.client import NodeFailed
from lancet_eval.dimensions import DimensionResult
from lancet_eval.journal import Journal, RunRecord
from lancet_eval.score import score_run


def test_validator_relaxed_and_surviving_invariants() -> None:
    # Relaxed: error with detail is valid
    d = DimensionResult(
        name="test",
        status="error",
        reason="some error",
        detail={"n_pairs": 0.0},
    )
    assert d.status == "error"
    assert d.detail["n_pairs"] == 0.0

    # Relaxed: skipped with detail is valid
    d2 = DimensionResult(
        name="test",
        status="skipped",
        reason="some reason",
        detail={"info": 1.0},
    )
    assert d2.status == "skipped"

    # Invariant: status error with score raises
    with pytest.raises(ValueError, match="cannot carry a score"):
        DimensionResult(
            name="test",
            status="error",
            score=0.5,
            reason="err",
        )

    # Invariant: status skipped with score raises
    with pytest.raises(ValueError, match="cannot carry a score"):
        DimensionResult(
            name="test",
            status="skipped",
            score=0.5,
            reason="skip",
        )

    # Invariant: status error with blank reason raises
    with pytest.raises(ValueError, match="requires a non-blank reason"):
        DimensionResult(
            name="test",
            status="error",
            reason="   ",
        )


def test_mixed_denominators_gone_and_unusable_rate(tmp_path: Path) -> None:
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.seed import load_document_map

    doc_map = load_document_map("multihop_rag")
    valid_doc_id = next(iter(doc_map.entries.keys()))
    questions = [q for q in load_sample_questions("multihop_rag") if not q.is_null]
    assert len(questions) >= 10

    # 10 records: 6 usable, 4 unusable (hard RetrieveHybrid failure)
    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    for i in range(10):
        is_bad = i < 4
        nf = (
            [
                NodeFailed(
                    node_name="RetrieveHybrid",
                    error_kind=4,
                    error_message="failed",
                    retryable=False,
                )
            ]
            if is_bad
            else []
        )
        q = questions[i]
        fact = q.gold_facts[0] if q.gold_facts else "fact"
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="error" if is_bad else "success",
            answer="" if is_bad else "Sam Altman",
            snapshot=None if is_bad else {
                "index_generation": "gen-1",
                "embedding_model": "bge",
                "vector_weight": 1.0,
                "bm25_weight": 0.8,
                "rrf_k": 60,
                "candidate_limit": 32,
                "final_limit": 8,
                "result_hash": "h",
                "retrieved_chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": valid_doc_id,
                        "title": "t",
                        "section_path": "s",
                        "excerpt": f"Evidence fact is: {fact}",
                        "is_truncated": False,
                        "score": 1.0,
                        "rank": 1,
                        "content_type": "text",
                    }
                ],
            },
            node_failures=nf,
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)

    dim_map = {d.name: d for d in report.dimensions}

    assert "unusable_record_rate" in dim_map
    unusable_dim = dim_map["unusable_record_rate"]
    assert unusable_dim.status == "ok"
    assert unusable_dim.score == 0.4
    assert unusable_dim.detail["unusable_n"] == 4.0
    assert unusable_dim.detail["n_journal"] == 10.0

    assert "retrieval_evidence_coverage" in dim_map
    assert "answer_exact_match" in dim_map
    cov_dim = dim_map["retrieval_evidence_coverage"]
    em_dim = dim_map["answer_exact_match"]

    assert cov_dim.n == 6
    assert em_dim.n == 6


def test_all_unusable_journal(tmp_path: Path) -> None:
    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    for i in range(5):
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=f"q_{i}",
            graph_arm="graph-on",
            outcome="error",
            duration_ms=50.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
            error_type="TransportError",
            error="failed to connect",
        )
        j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}

    unusable_dim = dim_map["unusable_record_rate"]
    assert unusable_dim.status == "ok"
    assert unusable_dim.score == 1.0
    assert unusable_dim.detail["unusable_n"] == 5.0

    # Quality dimensions must be skipped or error, never ok (none publishes 0.000)
    integrity_dims = (
        "unusable_record_rate",
        "wire_contract_conformance",
        "run_traceability",
    )
    for name, d in dim_map.items():
        if name in integrity_dims:
            continue
        assert d.status != "ok", (
            f"Quality dimension {name} had status ok on all-unusable journal"
        )


def test_rendered_report_shows_error_row_detail() -> None:
    from lancet_eval.report import CorpusReport, RunMetadata, render_markdown

    meta = RunMetadata(
        corpus="multihop_rag",
        run_date="2026-08-29T12:00:00Z",
        commit_sha="abcdef123456",
        generation_model="deepseek/deepseek-v4-flash-0731",
        embedding_model="voyageai/voyage-4-large",
        judge_model="meta-llama/llama-3.3-70b-instruct",
        judge_prompt_version="v1",
        index_generation="gen-01",
        result_hash="res-hash-01",
        dependency_lock_hash="lock-hash-01",
        sample_size_deterministic=10,
        sample_size_judged=0,
        arm_labels=["graph-on", "graph-off"],
        partial=False,
    )
    dim_err = DimensionResult(
        name="graph_ablation_delta",
        status="error",
        reason="No valid pairs",
        detail={"n_pairs": 0.0, "pairing_coverage": 0.0},
        n=0,
    )
    report = CorpusReport(corpus="multihop_rag", metadata=meta, dimensions=[dim_err])
    md = render_markdown(report)
    assert "No valid pairs" in md
    assert "n_pairs: 0.0" in md or "n_pairs" in md
