"""Tests for LLM-as-judge scoring pass, sampling, calibration, and cache integration."""

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.client import RetrievalSnapshot, StructuredCitation
from lancet_eval.corpus import load_sample_questions
from lancet_eval.journal import Journal, RunRecord
from lancet_eval.score import ScoreError, score_run


def _setup_fixtures(tmp_path: Path) -> list[str]:
    """Return list of valid question IDs."""
    questions = load_sample_questions("multihop_rag")
    return [q.question_id for q in questions]


def test_score_no_judge_skips_judged_dimensions(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves score --no-judge skips judged dimensions with zero HTTP calls."""
    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec = RunRecord(
        corpus="multihop_rag",
        question_id=qids[0],
        graph_arm="graph-on",
        outcome="success",
        answer="Paris is capital of France",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id="0abbe020-d26d-41e6-8d5f-f7867a3608db",
                    excerpt="Paris is capital",
                    rank=1,
                )
            ],
        ),
        structured_citations=[
            StructuredCitation(
                chunk_id="c1",
                document_id="0abbe020-d26d-41e6-8d5f-f7867a3608db",
                excerpt="Paris is capital",
                rank=1,
            )
        ],
    )
    journal.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")

    assert g_dim.status == "skipped"
    assert "no-judge" in (g_dim.reason or "").lower()
    assert f_dim.status == "skipped"
    assert "no-judge" in (f_dim.reason or "").lower()
    assert len(httpx_mock.get_requests()) == 0


def test_score_sample_judged_and_caching(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves score --sample judges seeded subset and caches verdicts for second run."""
    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:5]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer="Paris is capital of France",
            index_generation="gen-test-1",
            snapshot=RetrievalSnapshot(
                index_generation="gen-test-1",
                retrieved_chunks=[
                    StructuredCitation(
                        chunk_id="c1",
                        document_id="0abbe020-d26d-41e6-8d5f-f7867a3608db",
                        excerpt="Paris is capital",
                        rank=1,
                    )
                ],
            ),
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id="0abbe020-d26d-41e6-8d5f-f7867a3608db",
                    excerpt="Paris is capital",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    verdict_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "groundedness": 5,
                        "faithfulness": 4,
                        "unsupported_claims": [],
                        "rationale": "High quality answer",
                    })
                }
            }
        ]
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    client = httpx.Client()

    # First run: score sample of 3
    report1 = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        api_key="test-api-key",
        client=client,
    )
    g_dim1 = next(d for d in report1.dimensions if d.name == "answer_groundedness")
    assert g_dim1.status == "ok"
    assert g_dim1.score == 5.0
    assert g_dim1.detail["judged_n"] == 3.0

    requests1 = httpx_mock.get_requests()
    assert len(requests1) == 3

    # Second run with same sample: must hit cache and issue 0 new requests
    report2 = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        api_key="test-api-key",
        client=client,
    )
    g_dim2 = next(d for d in report2.dimensions if d.name == "answer_groundedness")
    assert g_dim2.status == "ok"
    assert g_dim2.score == 5.0

    requests2 = httpx_mock.get_requests()
    assert len(requests2) == 3  # Zero additional HTTP requests


def test_zero_citations_record_skipped_from_judged(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves records with empty citations are skipped without judge calls."""
    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec = RunRecord(
        corpus="multihop_rag",
        question_id=qids[0],
        graph_arm="graph-on",
        outcome="success",
        answer="I don't know",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=[],
        ),
        structured_citations=[],  # Empty citations
    )
    journal.append(rec)

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=1,
        api_key="test-api-key",
        client=client,
    )
    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    assert g_dim.status == "skipped"
    assert "no evidence" in (g_dim.reason or "").lower()
    assert len(httpx_mock.get_requests()) == 0


def test_judge_model_equals_generator_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves scoring aborts with ScoreError when judge model matches generator."""
    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec = RunRecord(
        corpus="multihop_rag",
        question_id=qids[0],
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-test-1",
    )
    journal.append(rec)

    from lancet_eval import score

    # Simulate generator model equal to judge model
    monkeypatch.setattr(
        score,
        "_get_engine_generation_model",
        lambda: "meta-llama/llama-3.3-70b-instruct:free",
    )

    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=tmp_path, no_judge=False)

    assert "equals engine generation model" in str(exc_info.value)


def test_calibration_worksheet_emission_and_ingestion(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves worksheet emission, human scoring, and calibration agreement."""
    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:3]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer="Answer text",
            index_generation="gen-test-1",
            snapshot=RetrievalSnapshot(
                index_generation="gen-test-1",
                retrieved_chunks=[
                    StructuredCitation(
                        chunk_id="c1",
                        document_id="0abbe020-d26d-41e6-8d5f-f7867a3608db",
                        excerpt="Evidence text",
                        rank=1,
                    )
                ],
            ),
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id="0abbe020-d26d-41e6-8d5f-f7867a3608db",
                    excerpt="Evidence text",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    verdict_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "groundedness": 5,
                        "faithfulness": 5,
                        "unsupported_claims": [],
                        "rationale": "High quality answer",
                    })
                }
            }
        ]
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    client = httpx.Client()
    worksheet_path = tmp_path / "calibration_ws.jsonl"

    # Step 1: Run score with worksheet emission
    score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        emit_calibration_worksheet=worksheet_path,
        api_key="test-key",
        client=client,
    )

    assert worksheet_path.is_file()
    with open(worksheet_path, encoding="utf-8") as f:
        ws_lines = [json.loads(line_text) for line_text in f if line_text.strip()]

    assert ws_lines[0]["type"] == "header"
    assert len(ws_lines) >= 3

    # Step 2: Human scores worksheet (simulate human grading)
    completed_ws_path = tmp_path / "calibration_completed.jsonl"
    with open(completed_ws_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(ws_lines[0]) + "\n")
        for row in ws_lines[1:]:
            row["human_groundedness"] = 5
            row["human_faithfulness"] = 4
            f.write(json.dumps(row) + "\n")

    # Step 3: Run score with calibration file
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        calibration_file=completed_ws_path,
        api_key="test-key",
        client=client,
    )

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")

    assert g_dim.status == "ok"
    assert g_dim.detail["calibration_exact_match"] == 1.0
    assert g_dim.detail["calibration_mad"] == 0.0

    assert f_dim.status == "ok"
    assert f_dim.detail["calibration_exact_match"] == 0.0
    assert f_dim.detail["calibration_mad"] == 1.0


def test_calibration_blank_human_score_fails_loud(tmp_path: Path) -> None:
    """Proves blank human score in calibration worksheet raises ScoreError."""
    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec = RunRecord(
        corpus="multihop_rag",
        question_id=qids[0],
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-test-1",
    )
    journal.append(rec)

    ws_path = tmp_path / "incomplete_calib.jsonl"
    with open(ws_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "header",
            "judge_prompt_version": "v1",
        }) + "\n")
        f.write(json.dumps({
            "question_id": "mhr-bad-row-99",
            "human_groundedness": None,  # Blank score
            "human_faithfulness": 5,
        }) + "\n")

    with pytest.raises(ScoreError) as exc_info:
        score_run(
            run_dir=tmp_path,
            no_judge=True,
            calibration_file=ws_path,
        )

    assert "mhr-bad-row-99" in str(exc_info.value)
    assert "blank human score" in str(exc_info.value)
