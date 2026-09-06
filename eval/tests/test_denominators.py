"""Tests for shared quality and path-health denominators.
Covers retrieval and answer metrics.
"""

from pathlib import Path

import pytest

from lancet_eval.client import NodeFailed, Notice
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


def test_scorable_payload_exclusion_and_reconciliation(tmp_path: Path) -> None:
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.seed import load_document_map

    doc_map = load_document_map("multihop_rag")
    valid_doc_id = next(iter(doc_map.entries.keys()))
    questions = [q for q in load_sample_questions("multihop_rag") if not q.is_null][:8]
    assert len(questions) == 8

    # 8 records: 6 fully-populated, 2 usable but payload-less (answer="", snapshot=None)
    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    for i in range(8):
        is_payload_less = i >= 6
        q = questions[i]
        fact = q.gold_facts[0] if q.gold_facts else "fact"
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="success",
            answer="" if is_payload_less else (q.gold_answer or "Sam Altman"),
            snapshot=None
            if is_payload_less
            else {
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
                        "chunk_id": f"c_{i}",
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
            node_failures=[],
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}

    target_dims = [
        "retrieval_evidence_coverage",
        "answer_exact_match",
        "answer_f1",
        "context_precision_at_k",
        "ranking_quality",
    ]
    for name in target_dims:
        assert name in dim_map, f"Missing dimension {name}"
        d = dim_map[name]
        assert d.status == "ok"
        assert d.n == 6, f"{name}.n expected 6, got {d.n}"
        assert "excluded_payload_records" in d.detail, (
            f"Detail for {name} missing excluded_payload_records"
        )
        assert d.detail["excluded_payload_records"] == 2.0, (
            f"{name} excluded count expected 2.0, got "
            f"{d.detail['excluded_payload_records']}"
        )
        # Reconciliation identity: n + excluded_payload_records == 8
        assert d.n + int(d.detail["excluded_payload_records"]) == 8


def test_whitespace_only_answer_treated_as_payload_less(tmp_path: Path) -> None:
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.seed import load_document_map

    doc_map = load_document_map("multihop_rag")
    valid_doc_id = next(iter(doc_map.entries.keys()))
    questions = [q for q in load_sample_questions("multihop_rag") if not q.is_null][:8]
    assert len(questions) == 8

    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    for i in range(8):
        is_payload_less = i >= 6
        q = questions[i]
        fact = q.gold_facts[0] if q.gold_facts else "fact"
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="success",
            answer="   \n\t  " if is_payload_less else (q.gold_answer or "Sam Altman"),
            snapshot=None
            if is_payload_less
            else {
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
                        "chunk_id": f"c_{i}",
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
            node_failures=[],
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}

    target_dims = [
        "retrieval_evidence_coverage",
        "answer_exact_match",
        "answer_f1",
        "context_precision_at_k",
        "ranking_quality",
    ]
    for name in target_dims:
        d = dim_map[name]
        assert d.n == 6
        assert d.detail["excluded_payload_records"] == 2.0


def test_empty_retrieved_chunks_snapshot_is_scorable_zero_recall(
    tmp_path: Path,
) -> None:
    from lancet_eval.corpus import load_sample_questions

    questions = [q for q in load_sample_questions("multihop_rag") if not q.is_null][:2]
    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    for q in questions:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="success",
            answer=q.gold_answer or "An answer",
            snapshot={
                "index_generation": "gen-1",
                "embedding_model": "bge",
                "vector_weight": 1.0,
                "bm25_weight": 0.8,
                "rrf_k": 60,
                "candidate_limit": 32,
                "final_limit": 8,
                "result_hash": "h",
                "retrieved_chunks": [],  # NO_EVIDENCE carve-out
            },
            node_failures=[],
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}
    cov_dim = dim_map["retrieval_evidence_coverage"]
    assert cov_dim.status == "ok"
    assert cov_dim.n == 2
    assert cov_dim.score == 0.0
    assert cov_dim.detail.get("excluded_payload_records", 0.0) == 0.0


def test_abstention_on_unanswerable_payload_exclusion_population_scoped(
    tmp_path: Path,
) -> None:
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.seed import load_document_map

    doc_map = load_document_map("multihop_rag")
    valid_doc_id = next(iter(doc_map.entries.keys()))

    ans_questions = [
        q for q in load_sample_questions("multihop_rag") if not q.is_null
    ][:8]
    null_questions = [q for q in load_sample_questions("multihop_rag") if q.is_null][
        :3
    ]
    assert len(ans_questions) == 8
    assert len(null_questions) == 3

    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    # In answerable population: 6 populated, 2 payload-less -> exclusion count = 2
    for i, q in enumerate(ans_questions):
        is_bad = i >= 6
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="success",
            answer="" if is_bad else (q.gold_answer or "ans"),
            snapshot=None
            if is_bad
            else {
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
                        "chunk_id": f"c_{i}",
                        "document_id": valid_doc_id,
                        "title": "t",
                        "section_path": "s",
                        "excerpt": "Evidence fact is: fact",
                        "is_truncated": False,
                        "score": 1.0,
                        "rank": 1,
                        "content_type": "text",
                    }
                ],
            },
            node_failures=[],
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    # In null-gold population: 2 populated, 1 payload-less -> exclusion count = 1
    for i, q in enumerate(null_questions):
        is_bad = i == 2
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="success",
            answer="" if is_bad else "I do not have enough information to answer.",
            snapshot=None
            if is_bad
            else {
                "index_generation": "gen-1",
                "embedding_model": "bge",
                "vector_weight": 1.0,
                "bm25_weight": 0.8,
                "rrf_k": 60,
                "candidate_limit": 32,
                "final_limit": 8,
                "result_hash": "h",
                "retrieved_chunks": [],
            },
            node_failures=[],
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}

    # Answerable dimensions must have excluded_payload_records == 2.0
    cov_dim = dim_map["retrieval_evidence_coverage"]
    assert cov_dim.n == 6
    assert cov_dim.detail["excluded_payload_records"] == 2.0

    # Abstention dimension must have excluded_payload_records == 1.0
    # (scoped to null population)
    abs_dim = dim_map["abstention_on_unanswerable"]
    assert abs_dim.status == "ok"
    assert abs_dim.n == 2
    assert abs_dim.detail["excluded_payload_records"] == 1.0
    # Reconciliation identity for null-gold population: n + excluded == 3
    assert abs_dim.n + int(abs_dim.detail["excluded_payload_records"]) == 3


def test_abstention_credits_notice_based_no_evidence_over_text_match(
    tmp_path: Path,
) -> None:
    """CR-01 regression: score.py must pass rec.notices into abstention_rate so
    a NOTICE_CODE_NO_EVIDENCE (typed_code=1) notice credits correct_abstention
    even when the answer text matches neither hardcoded refusal phrase."""
    from lancet_eval.corpus import load_sample_questions

    null_questions = [q for q in load_sample_questions("multihop_rag") if q.is_null]
    assert len(null_questions) >= 1
    q = null_questions[0]

    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    rec = RunRecord(
        corpus="multihop_rag",
        question_id=q.question_id,
        graph_arm="graph-on",
        outcome="success",
        # Deliberately matches neither "insufficient information" nor "cannot
        # answer" — only the typed notice should credit this as abstention.
        answer="The requested information isn't present.",
        snapshot={
            "index_generation": "gen-1",
            "embedding_model": "bge",
            "vector_weight": 1.0,
            "bm25_weight": 0.8,
            "rrf_k": 60,
            "candidate_limit": 32,
            "final_limit": 8,
            "result_hash": "h",
            "retrieved_chunks": [],
        },
        notices=[
            Notice(code="NO_EVIDENCE", message="no evidence found", typed_code=1)
        ],
        node_failures=[],
        duration_ms=100.0,
        session_id="sess",
        correlation_id="corr",
        index_generation="gen-1",
    )
    j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}

    abs_dim = dim_map["abstention_on_unanswerable"]
    assert abs_dim.status == "ok"
    assert abs_dim.n == 1
    assert abs_dim.score == 1.0


def test_abstention_skip_reason_distinguishes_payload_excluded_from_absent(
    tmp_path: Path,
) -> None:
    """CR-02 regression: when null-gold records exist but all are payload-
    excluded, the skip reason must say so rather than falsely claiming the
    corpus contains no unanswerable questions."""
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.seed import load_document_map

    doc_map = load_document_map("multihop_rag")
    valid_doc_id = next(iter(doc_map.entries.keys()))

    ans_questions = [
        q for q in load_sample_questions("multihop_rag") if not q.is_null
    ][:2]
    null_questions = [q for q in load_sample_questions("multihop_rag") if q.is_null][
        :2
    ]
    assert len(ans_questions) == 2
    assert len(null_questions) == 2

    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    # Normal, fully scorable answerable records.
    for i, q in enumerate(ans_questions):
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="success",
            answer=q.gold_answer or "ans",
            snapshot={
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
                        "chunk_id": f"c_{i}",
                        "document_id": valid_doc_id,
                        "title": "t",
                        "section_path": "s",
                        "excerpt": "Evidence fact is: fact",
                        "is_truncated": False,
                        "score": 1.0,
                        "rank": 1,
                        "content_type": "text",
                    }
                ],
            },
            node_failures=[],
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    # All null-gold records payload-excluded (blank answer, no snapshot) —
    # unanswerable questions exist but every one was excluded, not absent.
    for q in null_questions:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="success",
            answer="",
            snapshot=None,
            node_failures=[],
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}

    abs_dim = dim_map["abstention_on_unanswerable"]
    assert abs_dim.status == "skipped"
    assert abs_dim.detail["excluded_payload_records"] == 2.0
    assert "no unanswerable questions" not in abs_dim.reason
    assert "payload" in abs_dim.reason.lower()


def test_all_payload_less_journal_non_ok_status_and_rendered_report(
    tmp_path: Path,
) -> None:
    from lancet_eval.corpus import load_sample_questions
    from lancet_eval.report import render_markdown

    questions = [q for q in load_sample_questions("multihop_rag") if not q.is_null][:4]
    journal_file = tmp_path / "journal.jsonl"
    j = Journal(journal_file)
    j.write_header(corpus="multihop_rag", partial=False)

    for q in questions:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=q.question_id,
            graph_arm="graph-on",
            outcome="success",
            answer="",
            snapshot=None,
            node_failures=[],
            duration_ms=100.0,
            session_id="sess",
            correlation_id="corr",
            index_generation="gen-1",
        )
        j.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    dim_map = {d.name: d for d in report.dimensions}

    target_dims = [
        "retrieval_evidence_coverage",
        "answer_exact_match",
        "answer_f1",
        "context_precision_at_k",
        "ranking_quality",
    ]
    for name in target_dims:
        d = dim_map[name]
        assert d.status != "ok"
        assert d.n == 0
        assert "excluded_payload_records" in d.detail
        assert d.detail["excluded_payload_records"] == 4.0

    md = render_markdown(report)
    assert "excluded_payload_records=4" in md


def test_caveat_6_mentions_payload_rule_and_has_no_numerals() -> None:
    import re

    template_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "lancet_eval"
        / "templates"
        / "report.md.j2"
    )
    text = template_path.read_text(encoding="utf-8")

    # Find caveat 6 line
    caveat_line = ""
    for line in text.splitlines():
        if line.strip().startswith("6. "):
            caveat_line = line.strip()
            break
    assert caveat_line, "Caveat 6 not found in template"

    # Assert payload rule mentioned
    assert "payload" in caveat_line.lower()

    # The caveat text (after the '6. ') must contain no numerals [0-9]
    body = caveat_line[3:]
    digits = re.findall(r"\d", body)
    assert not digits, f"Caveat 6 body contains numerals: {digits}"

