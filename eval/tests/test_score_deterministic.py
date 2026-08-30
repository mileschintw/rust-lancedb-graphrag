"""Tests for offline deterministic scorer and ablation provenance."""

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.client import Notice, RetrievalSnapshot, StructuredCitation
from lancet_eval.corpus import load_sample_questions
from lancet_eval.dimensions import (
    NOTICE_CODE_GRAPH_ABLATION,
    NOTICE_CODE_GRAPH_UNAVAILABLE,
)
from lancet_eval.journal import Journal, RunRecord
from lancet_eval.score import ScoreError, score_run


def _get_valid_doc_id() -> str:
    try:
        from lancet_eval.seed import load_document_map

        doc_map = load_document_map("multihop_rag")
        return next(iter(doc_map.entries.keys()))
    except Exception:
        return "0abbe020-d26d-41e6-8d5f-f7867a3608db"


def _setup_mock_corpus_files(tmp_path: Path) -> tuple[Path, str]:
    """Return run directory and first question id."""
    questions = load_sample_questions("multihop_rag")
    q1 = questions[0]
    return tmp_path, q1.question_id


def test_score_offline_guarantee_zero_http_calls(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves score --no-judge makes zero HTTP requests."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec_on = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        answer="London",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="London is the capital",
                    rank=1,
                )
            ],
        ),
    )
    rec_off = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-off",
        outcome="success",
        answer="London",
        index_generation="gen-test-1",
        notices=[
            Notice(
                code="GRAPH_ABLATION",
                message="",
                typed_code=NOTICE_CODE_GRAPH_ABLATION,
            )
        ],
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="London is the capital",
                    rank=1,
                )
            ],
        ),
    )
    journal.append(rec_on)
    journal.append(rec_off)

    report = score_run(run_dir=tmp_path, no_judge=True)
    assert report.corpus == "multihop_rag"
    assert len(httpx_mock.get_requests()) == 0


def test_discriminating_retrieval_input_assertion(tmp_path: Path) -> None:
    """Proves retrieval dimensions strictly read snapshot.retrieved_chunks."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # Gold fact in structured_citations but NOT in retrieved_chunks -> must score 0.0
    rec_a = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Irrelevant content about apples and oranges",
                    rank=1,
                )
            ],
        ),
        structured_citations=[
            StructuredCitation(
                chunk_id="c9",
                document_id=doc_id,
                excerpt="This text matches gold fact exactly",
                rank=1,
            )
        ],
    )
    journal.append(rec_a)

    report_a = score_run(run_dir=tmp_path, no_judge=True)
    recall_dim_a = next(
        d for d in report_a.dimensions if d.name == "retrieval_evidence_coverage"
    )
    assert recall_dim_a.status == "ok"
    assert recall_dim_a.score == 0.0


def test_discriminating_retrieval_input_mirror(tmp_path: Path) -> None:
    """Mirror test: Gold facts in retrieved_chunks but not in citations -> score 1.0."""
    questions = load_sample_questions("multihop_rag")
    q1 = questions[0]

    _setup_mock_corpus_files(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # Build retrieved chunks matching all gold facts in q1
    chunks = [
        StructuredCitation(
            chunk_id=f"c{idx}",
            document_id=doc_id,
            excerpt=f"Context containing {fact} verbatim",
            rank=idx + 1,
        )
        for idx, fact in enumerate(q1.gold_facts)
    ]

    rec_b = RunRecord(
        corpus="multihop_rag",
        question_id=q1.question_id,
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=chunks,
        ),
        structured_citations=[],  # Empty model citations
    )
    journal.append(rec_b)

    report_b = score_run(run_dir=tmp_path, no_judge=True)
    recall_dim_b = next(
        d for d in report_b.dimensions if d.name == "retrieval_evidence_coverage"
    )
    assert recall_dim_b.status == "ok"
    assert recall_dim_b.score == 1.0


def test_mixed_index_generations_fails_loud(tmp_path: Path) -> None:
    """Proves a journal mixing two index_generation values raises ScoreError."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec1 = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-1",
    )
    rec2 = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-2",
    )
    journal.append(rec1)
    journal.append(rec2)

    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=tmp_path, no_judge=True)

    msg = str(exc_info.value)
    assert "gen-1" in msg
    assert "gen-2" in msg


def test_unmapped_document_id_fails_loud(tmp_path: Path) -> None:
    """Proves an unknown document_id in retrieved chunks raises ScoreError."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id="unmapped-doc-uuid-9999",
                    excerpt="Some text",
                    rank=1,
                )
            ],
        ),
    )
    journal.append(rec)

    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=tmp_path, no_judge=True)

    assert "unmapped-doc-uuid-9999" in str(exc_info.value)


def test_graph_ablation_provenance_failure(tmp_path: Path) -> None:
    """Proves graph-off record missing ablation notice is recorded as error."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec_on = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1", retrieved_chunks=[]
        ),
    )
    # graph-off record with graph-unavailable notice (invalid provenance)
    rec_off_bad = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-off",
        outcome="success",
        index_generation="gen-test-1",
        notices=[
            Notice(
                code="GRAPH_UNAVAILABLE",
                message="",
                typed_code=NOTICE_CODE_GRAPH_UNAVAILABLE,
            )
        ],
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1", retrieved_chunks=[]
        ),
    )
    journal.append(rec_on)
    journal.append(rec_off_bad)

    report = score_run(run_dir=tmp_path, no_judge=True)
    ablation_dim = next(
        d for d in report.dimensions if d.name == "graph_ablation_delta"
    )
    assert ablation_dim.status == "ok"
    assert ablation_dim.detail["graph_off_errors"] == 1.0


def test_negative_ablation_delta_reported_as_ok(tmp_path: Path) -> None:
    """Proves an honest negative ablation delta is published as-is with status='ok'."""
    questions = load_sample_questions("multihop_rag")
    q1 = questions[0]

    _setup_mock_corpus_files(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # graph-on gets 0.0 recall
    rec_on = RunRecord(
        corpus="multihop_rag",
        question_id=q1.question_id,
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="irrelevant",
                    rank=1,
                )
            ],
        ),
    )

    # graph-off gets 1.0 recall by matching all gold facts
    chunks_off = [
        StructuredCitation(
            chunk_id=f"c{idx}",
            document_id=doc_id,
            excerpt=f"match {fact}",
            rank=idx + 1,
        )
        for idx, fact in enumerate(q1.gold_facts)
    ]

    rec_off = RunRecord(
        corpus="multihop_rag",
        question_id=q1.question_id,
        graph_arm="graph-off",
        outcome="success",
        index_generation="gen-test-1",
        notices=[
            Notice(
                code="GRAPH_ABLATION",
                message="",
                typed_code=NOTICE_CODE_GRAPH_ABLATION,
            )
        ],
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=chunks_off,
        ),
    )
    journal.append(rec_on)
    journal.append(rec_off)

    report = score_run(run_dir=tmp_path, no_judge=True)
    ablation_dim = next(
        d for d in report.dimensions if d.name == "graph_ablation_delta"
    )
    assert ablation_dim.status == "ok"
    assert ablation_dim.score == -1.0
    assert ablation_dim.detail["delta"] == -1.0


def test_score_run_stamps_real_commit_sha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves score_run stamps a real 40-char SHA when GIT_COMMIT_SHA is unset."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(
        RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer="ans",
            index_generation="gen-test-1",
        )
    )

    # 1. Unset GIT_COMMIT_SHA -> resolves git commit SHA
    monkeypatch.delenv("GIT_COMMIT_SHA", raising=False)
    report = score_run(run_dir=tmp_path, no_judge=True)
    sha = report.metadata.commit_sha
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha.lower())
    assert sha != "local"
    assert sha != "unknown"

    # 2. Set GIT_COMMIT_SHA -> explicit override wins
    monkeypatch.setenv("GIT_COMMIT_SHA", "custom_sha_1234567890abcdef")
    report_override = score_run(run_dir=tmp_path, no_judge=True)
    assert report_override.metadata.commit_sha == "custom_sha_1234567890abcdef"

