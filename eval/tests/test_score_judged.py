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


def _get_valid_doc_id() -> str:
    try:
        from lancet_eval.seed import load_document_map

        doc_map = load_document_map("multihop_rag")
        return next(iter(doc_map.entries.keys()))
    except Exception:
        return "0abbe020-d26d-41e6-8d5f-f7867a3608db"


def _setup_fixtures(tmp_path: Path) -> list[str]:
    """Return list of valid question IDs."""
    questions = load_sample_questions("multihop_rag")
    return [q.question_id for q in questions]


def test_score_no_judge_skips_judged_dimensions(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves score --no-judge skips judged dimensions with zero HTTP calls."""
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
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
                    document_id=doc_id,
                    excerpt="Paris is capital",
                    rank=1,
                )
            ],
        ),
        structured_citations=[
            StructuredCitation(
                chunk_id="c1",
                document_id=doc_id,
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
    doc_id = _get_valid_doc_id()
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
                        document_id=doc_id,
                        excerpt="Paris is capital",
                        rank=1,
                    )
                ],
            ),
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
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
        stage_spend_cap=10.0,
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
        stage_spend_cap=10.0,
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
        stage_spend_cap=10.0,
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
        lambda: "meta-llama/llama-3.3-70b-instruct",
    )

    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=tmp_path, no_judge=False, stage_spend_cap=10.0)

    assert "equals engine generation model" in str(exc_info.value)


def test_calibration_worksheet_emission_and_ingestion(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves worksheet emission, human scoring, and calibration agreement."""
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
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
                        document_id=doc_id,
                        excerpt="Evidence text",
                        rank=1,
                    )
                ],
            ),
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
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
        stage_spend_cap=10.0,
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
        stage_spend_cap=10.0,
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


def test_worksheet_rows_are_drawn_from_the_judged_subset(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves worksheet rows are from judged subset and exclude uncited records."""
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # Populate 2 uncited records first in p_records
    uncited_qids = {qids[0], qids[1]}
    for qid in [qids[0], qids[1]]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Uncited answer for {qid}",
            index_generation="gen-test-1",
            structured_citations=[],  # Empty citations -> skipped from judging
        )
        journal.append(rec)

    # Populate 30 cited primary arm records
    for qid in qids[2:32]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer for {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
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

    # Run score with full primary arm population
    score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=None,
        emit_calibration_worksheet=worksheet_path,
        stage_spend_cap=10.0,
        api_key="test-key",
        client=client,
    )

    # Load judge_cache.json
    cache_path = tmp_path / "judge_cache.json"
    assert cache_path.is_file()
    with open(cache_path, encoding="utf-8") as f:
        cache_data = json.load(f)

    # Load emitted worksheet
    assert worksheet_path.is_file()
    with open(worksheet_path, encoding="utf-8") as f:
        ws_lines = [json.loads(line_text) for line_text in f if line_text.strip()]

    # Header + data rows
    header = ws_lines[0]
    data_rows = ws_lines[1:]

    assert header["type"] == "header"
    assert len(data_rows) == 20

    # Emitted worksheet must never contain uncited records
    emitted_qids = {row["question_id"] for row in data_rows}
    assert not (uncited_qids & emitted_qids)

    # Every data row's cache_key must be present in judge_cache.json with a verdict
    for row in data_rows:
        assert row["cache_key"] in cache_data
        assert cache_data[row["cache_key"]]["verdict"] is not None


def test_worksheet_excludes_judge_errored_records(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves records with judge errors (verdict: null) are excluded from worksheet."""
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    qid = qids[0]
    rec = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        answer=f"Answer for {qid}",
        index_generation="gen-test-1",
        structured_citations=[
            StructuredCitation(
                chunk_id="c1",
                document_id=doc_id,
                excerpt="Evidence text",
                rank=1,
            )
        ],
    )
    journal.append(rec)

    # Mock two malformed responses to exhaust the single re-ask
    bad_payload_1 = json.dumps({
        "groundedness": 6,
        "faithfulness": 4,
        "unsupported_claims": [],
        "rationale": "Score 6 is invalid",
    })
    bad_payload_2 = json.dumps({
        "groundedness": 0,
        "faithfulness": 4,
        "unsupported_claims": [],
        "rationale": "Score 0 is invalid",
    })
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": bad_payload_1}}]}
    )
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": bad_payload_2}}]}
    )

    client = httpx.Client()
    worksheet_path = tmp_path / "calibration_ws.jsonl"

    score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=None,
        emit_calibration_worksheet=worksheet_path,
        stage_spend_cap=10.0,
        api_key="test-key",
        client=client,
    )

    cache_path = tmp_path / "judge_cache.json"
    assert cache_path.is_file()
    with open(cache_path, encoding="utf-8") as f:
        cache_data = json.load(f)

    # Entry exists in judge_cache.json with verdict=None and error recorded
    assert len(cache_data) == 1
    cache_entry = next(iter(cache_data.values()))
    assert cache_entry["verdict"] is None
    assert cache_entry["error"] is not None

    # Emitted worksheet must not contain the errored record
    assert worksheet_path.is_file()
    with open(worksheet_path, encoding="utf-8") as f:
        ws_lines = [json.loads(line_text) for line_text in f if line_text.strip()]

    header = ws_lines[0]
    data_rows = ws_lines[1:]
    assert header["type"] == "header"
    assert len(data_rows) == 0


def test_worksheet_never_sources_graph_off_records(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves the calibration worksheet only ever draws from the graph-on (primary) arm.

    06.3-11-PLAN.md's must_haves.prohibitions: calibration measures agreement on the
    population the judge actually scores for the headline dimensions (graph-on only);
    sourcing rows from graph-off would produce an agreement figure that does not
    describe what the report claims it describes. This is a distinct regression guard
    from test_worksheet_rows_are_drawn_from_the_judged_subset (which proves uncited
    graph-on records are excluded) and test_worksheet_excludes_judge_errored_records
    (which proves judge-errored records are excluded) -- both of those fixtures are
    entirely graph-on and so cannot catch a primary-arm-scoping regression.
    """
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # Cited graph-off records with their own distinct question_ids. If the selector
    # ever iterated over all records instead of the primary-arm-scoped p_records,
    # these would look exactly as eligible as the graph-on records below.
    graph_off_qids = set(qids[:5])
    for qid in qids[:5]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-off",
            outcome="success",
            answer=f"Graph-off answer for {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Graph-off evidence text",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    # Cited graph-on records -- the only population the worksheet should ever draw from.
    for qid in qids[5:10]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Graph-on answer for {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Graph-on evidence text",
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

    score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=None,
        emit_calibration_worksheet=worksheet_path,
        stage_spend_cap=10.0,
        api_key="test-key",
        client=client,
    )

    # judge_cache.json must only ever contain entries for the 5 graph-on records --
    # the 5 graph-off records must never reach the judge at all.
    cache_path = tmp_path / "judge_cache.json"
    assert cache_path.is_file()
    with open(cache_path, encoding="utf-8") as f:
        cache_data = json.load(f)
    assert len(cache_data) == 5
    for entry in cache_data.values():
        assert entry["answer"].startswith("Graph-on answer for")

    assert worksheet_path.is_file()
    with open(worksheet_path, encoding="utf-8") as f:
        ws_lines = [json.loads(line_text) for line_text in f if line_text.strip()]

    header = ws_lines[0]
    data_rows = ws_lines[1:]
    assert header["type"] == "header"

    # All 5 graph-on records are cited and judged successfully -> all 5 emitted.
    assert len(data_rows) == 5

    emitted_qids = {row["question_id"] for row in data_rows}
    assert not (graph_off_qids & emitted_qids)
    assert emitted_qids == set(qids[5:10])


def _judge_five_records(
    httpx_mock: HTTPXMock,
    tmp_path: Path,
    journal: Journal,
    doc_id: str,
    qids: list[str],
) -> None:
    """Populate journal + judge_cache.json with 5 cited, judged graph-on records."""
    for qid in qids[:5]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer for {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
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
    score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=None,
        stage_spend_cap=10.0,
        api_key="test-key",
        client=client,
    )


def test_calibration_file_rejects_no_judge_when_cache_populated(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves --calibration-file with --no-judge is rejected once judge_cache.json
    already holds verdicts from a prior --judge invocation.

    06.3-11-PLAN.md's must_haves.prohibitions: the final --calibration-file score
    invocation MUST NOT omit --judge, because score_run rewrites report.json on
    every non-partial invocation -- omitting --judge here would silently discard
    the enlarged judged pass a prior invocation produced.
    """
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    _judge_five_records(httpx_mock, tmp_path, journal, doc_id, qids)

    cache_path = tmp_path / "judge_cache.json"
    with open(cache_path, encoding="utf-8") as f:
        cache_data = json.load(f)
    assert len(cache_data) == 5

    calib_path = tmp_path / "calibration_completed.jsonl"
    with open(calib_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "header", "judge_prompt_version": "v1"}) + "\n")
        for qid in qids[:5]:
            f.write(json.dumps({
                "question_id": qid,
                "cache_key": next(iter(cache_data.keys())),
                "human_groundedness": 5,
                "human_faithfulness": 5,
            }) + "\n")

    with pytest.raises(ScoreError) as exc_info:
        score_run(
            run_dir=tmp_path,
            no_judge=True,
            calibration_file=calib_path,
        )
    assert "--no-judge" in str(exc_info.value)
    assert "5 cached verdict" in str(exc_info.value)


def test_calibration_file_rejects_narrower_sample_than_cache(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves --calibration-file with a --sample narrower than the already-cached
    verdict count is rejected, matching the same prohibition as the --no-judge case
    above -- a narrower --sample would re-judge a smaller subset and silently
    shrink the judged population report.json records.
    """
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    _judge_five_records(httpx_mock, tmp_path, journal, doc_id, qids)

    cache_path = tmp_path / "judge_cache.json"
    with open(cache_path, encoding="utf-8") as f:
        cache_data = json.load(f)
    assert len(cache_data) == 5

    calib_path = tmp_path / "calibration_completed.jsonl"
    with open(calib_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "header", "judge_prompt_version": "v1"}) + "\n")
        f.write(json.dumps({
            "question_id": qids[0],
            "cache_key": next(iter(cache_data.keys())),
            "human_groundedness": 5,
            "human_faithfulness": 5,
        }) + "\n")

    client = httpx.Client()
    with pytest.raises(ScoreError) as exc_info:
        score_run(
            run_dir=tmp_path,
            no_judge=False,
            sample=2,
            calibration_file=calib_path,
            api_key="test-key",
            client=client,
            stage_spend_cap=10.0,
        )
    assert "narrower" in str(exc_info.value)
    assert "5 verdict" in str(exc_info.value)


def test_compute_judge_spend_arithmetic_and_distinct_from_generation() -> None:
    """Proves compute_judge_spend computes correct arithmetic and differs from generation."""
    from lancet_eval.measure import (
        JUDGE_INPUT_PRICE_PER_1M,
        JUDGE_OUTPUT_PRICE_PER_1M,
        compute_judge_spend,
        compute_spend,
    )

    prompt_toks = 1000
    comp_toks = 200

    judge_spend = compute_judge_spend(prompt_toks, comp_toks)
    expected = (
        (prompt_toks * JUDGE_INPUT_PRICE_PER_1M)
        + (comp_toks * JUDGE_OUTPUT_PRICE_PER_1M)
    ) / 1_000_000.0
    assert abs(judge_spend - expected) < 1e-12

    # Generation pricing for same tokens:
    gen_dummy = RunRecord(
        corpus="multihop_rag",
        question_id="dummy",
        graph_arm="graph-on",
        outcome="success",
        workflow_meta={"prompt_tokens": prompt_toks, "completion_tokens": comp_toks},
    )
    gen_spend, _ = compute_spend([gen_dummy], include_embeddings=False)
    assert judge_spend != gen_spend


def test_score_run_judging_enabled_without_cap_raises_score_error(
    tmp_path: Path,
) -> None:
    """Proves score_run with no_judge=False and no stage_spend_cap raises ScoreError."""
    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(
        RunRecord(
            corpus="multihop_rag",
            question_id=qids[0],
            graph_arm="graph-on",
            outcome="success",
            answer="Answer",
            index_generation="gen-test-1",
        )
    )

    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=tmp_path, no_judge=False, api_key="dummy")
    assert "stage_spend_cap" in str(exc_info.value).lower()


def test_score_run_judging_disabled_without_cap_does_not_raise(
    tmp_path: Path,
) -> None:
    """Proves score_run with no_judge=True and no stage_spend_cap does not raise."""
    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(
        RunRecord(
            corpus="multihop_rag",
            question_id=qids[0],
            graph_arm="graph-on",
            outcome="success",
            answer="Answer",
            index_generation="gen-test-1",
        )
    )

    report = score_run(run_dir=tmp_path, no_judge=True)
    assert report is not None


def test_judge_loop_breaks_at_spend_cap(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves judge loop stops dispatching when accumulated spend reaches cap."""
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:3]:
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
                        document_id=doc_id,
                        excerpt="Paris is capital",
                        rank=1,
                    )
                ],
            ),
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
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
        ],
        # Usage costing $0.0024: 15000 prompt tokens @ $0.12/1M + 2000 comp tokens @ $0.30/1M
        "usage": {"prompt_tokens": 15000, "completion_tokens": 2000},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    from lancet_eval.measure import estimate_judge_cost_per_question
    cost_per_q = estimate_judge_cost_per_question()
    # Cap set to allow 3 questions estimated (~$0.00158), but 1st call costs $0.0024 -> breaks before 2nd call!
    cap = cost_per_q * 3.5

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    requests = httpx_mock.get_requests()
    assert len(requests) == 1  # Exactly 1 call made!
    # Distinguishable in report outcome
    assert "cap" in report.metadata.notes.lower() or report.dimensions[0].detail.get("cap_stopped", 0.0) == 1.0


def test_judge_loop_cached_verdicts_consume_no_cap_headroom(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves fully-cached verdicts judge to completion with zero HTTP calls under tiny cap."""
    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:3]:
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
                        document_id=doc_id,
                        excerpt="Paris is capital",
                        rank=1,
                    )
                ],
            ),
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Paris is capital",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    # First pass with sufficient cap to fill cache
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
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    client = httpx.Client()
    score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        stage_spend_cap=1.0,
        api_key="test-api-key",
        client=client,
    )
    assert len(httpx_mock.get_requests()) == 3

    # Second pass with microscopic cap: cached calls consume 0 cap headroom
    report2 = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        stage_spend_cap=0.000001,
        api_key="test-api-key",
        client=client,
    )
    # Zero new HTTP requests issued
    assert len(httpx_mock.get_requests()) == 3
    g_dim = next(d for d in report2.dimensions if d.name == "answer_groundedness")
    assert g_dim.status == "ok"
    assert g_dim.detail["judged_n"] == 3.0


def test_score_run_judged_subset_bounded_by_cap(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves score_run with sample=None sizes judged subset to cap-derived bound."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:5]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
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
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question()
    # Bound cap to exactly 2 questions
    cap = cost_per_q * 2.5

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=None,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )
    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    assert g_dim.detail["judged_n"] == 2.0
    assert len(httpx_mock.get_requests()) == 2


def test_score_run_sample_exceeds_cap_derived_bound_raises(
    tmp_path: Path,
) -> None:
    """Proves explicit --sample larger than cap-derived slice size raises ScoreError."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:5]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    cost_per_q = estimate_judge_cost_per_question()
    # Bound cap to 2 questions
    cap = cost_per_q * 2.5

    with pytest.raises(ScoreError) as exc_info:
        score_run(
            run_dir=tmp_path,
            no_judge=False,
            sample=4,
            stage_spend_cap=cap,
            api_key="test-api-key",
        )
    msg = str(exc_info.value)
    assert "4" in msg
    assert "2" in msg
    assert "exceeds" in msg or "cap-derived" in msg


def test_score_run_sample_at_or_below_bound_honoured(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves explicit --sample at or below cap-derived slice size is honoured."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:5]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
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
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question()
    # Cap allows 4 questions; sample is 2
    cap = cost_per_q * 4.5

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=2,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )
    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    assert g_dim.detail["judged_n"] == 2.0
    assert len(httpx_mock.get_requests()) == 2


def test_score_run_publishes_judged_slice_provenance(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves score_run publishes judged_slice_committed, verdicts_obtained, and judged_slice_state."""
    from lancet_eval.dimensions import JUDGED_SLICE_STATE_COMPLETED
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:3]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
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
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question()
    cap = cost_per_q * 5.0

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    assert report.metadata.judged_slice_committed == 3
    assert report.metadata.verdicts_obtained == 3
    assert report.metadata.judged_slice_state == "completed"

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")

    assert g_dim.detail["judged_slice_committed"] == 3.0
    assert g_dim.detail["verdicts_obtained"] == 3.0
    assert g_dim.detail["judged_slice_state"] == JUDGED_SLICE_STATE_COMPLETED

    assert f_dim.detail["judged_slice_committed"] == 3.0
    assert f_dim.detail["verdicts_obtained"] == 3.0
    assert f_dim.detail["judged_slice_state"] == JUDGED_SLICE_STATE_COMPLETED


def test_score_run_cap_stopped_publishes_provenance(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves cap-stopped judged pass publishes cap_stopped state and verdicts_obtained < committed."""
    from lancet_eval.dimensions import JUDGED_SLICE_STATE_CAP_STOPPED
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:3]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    # 1st call usage costs $0.0024
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
        ],
        "usage": {"prompt_tokens": 15000, "completion_tokens": 2000},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question()
    cap = cost_per_q * 3.5

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    assert report.metadata.judged_slice_committed == 3
    assert report.metadata.verdicts_obtained == 1
    assert report.metadata.verdicts_obtained < report.metadata.judged_slice_committed
    assert report.metadata.judged_slice_state == "cap_stopped"

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    assert g_dim.detail["judged_slice_committed"] == 3.0
    assert g_dim.detail["verdicts_obtained"] == 1.0
    assert g_dim.detail["judged_slice_state"] == JUDGED_SLICE_STATE_CAP_STOPPED


def test_score_run_unjudged_publishes_not_judged_provenance(tmp_path: Path) -> None:
    """Proves unjudged run publishes not_judged state with 0 counts."""
    from lancet_eval.dimensions import JUDGED_SLICE_STATE_NOT_JUDGED

    qids = _setup_fixtures(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(
        RunRecord(
            corpus="multihop_rag",
            question_id=qids[0],
            graph_arm="graph-on",
            outcome="success",
            answer="Answer",
            index_generation="gen-test-1",
        )
    )

    report = score_run(run_dir=tmp_path, no_judge=True)
    assert report.metadata.judged_slice_committed == 0
    assert report.metadata.verdicts_obtained == 0
    assert report.metadata.judged_slice_state == "not_judged"

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    assert g_dim.detail["judged_slice_committed"] == 0.0
    assert g_dim.detail["verdicts_obtained"] == 0.0
    assert g_dim.detail["judged_slice_state"] == JUDGED_SLICE_STATE_NOT_JUDGED


def test_run_metadata_judged_slice_state_validation() -> None:
    """Proves RunMetadata validates judged_slice_state against known mapping."""
    from pydantic import ValidationError

    from lancet_eval.report import RunMetadata

    base_args = dict(
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

    # Unknown state string raises ValidationError
    with pytest.raises(ValidationError):
        RunMetadata(**base_args, judged_slice_state="unauthorized_free_text")

    # Blank state string raises ValidationError
    with pytest.raises(ValidationError):
        RunMetadata(**base_args, judged_slice_state="  ")


def test_judge_loop_breaks_at_spend_cap_with_usage_absent_fallback(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves discriminating cap-break: 1 observed call > estimate + usage-absent calls break on spend cap."""
    from lancet_eval.dimensions import JUDGED_SLICE_STATE_CAP_STOPPED
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # 5 primary-arm records, all carrying non-empty structured citations
    for qid in qids[:5]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    # First mocked response costs 3 * cost_per_question:
    # 3600 prompt tokens @ $0.12/1M + 1200 comp tokens @ $0.30/1M = $0.000792
    verdict_resp_with_usage = {
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
        ],
        "usage": {"prompt_tokens": 3600, "completion_tokens": 1200},
    }
    # Subsequent mocked responses omit the usage block
    verdict_resp_no_usage = {
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
        ],
    }
    httpx_mock.add_response(json=verdict_resp_with_usage)
    httpx_mock.add_response(json=verdict_resp_no_usage, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question(judge_max_tokens=400)
    cap = cost_per_q * 4.5  # derived slice is 4

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    requests = httpx_mock.get_requests()
    # Post-fix: 3 requests made (strictly fewer than committed 4)
    assert len(requests) < report.metadata.judged_slice_committed
    assert len(requests) == 3
    assert report.metadata.judged_slice_committed == 4
    assert report.metadata.verdicts_obtained == 3
    assert report.metadata.verdicts_obtained < report.metadata.judged_slice_committed
    assert report.metadata.judged_slice_state == "cap_stopped"

    # Published fallback count equals number of usage-absent dispatches (2)
    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")
    assert g_dim.detail["usage_absent_fallback_count"] == 2.0
    assert f_dim.detail["usage_absent_fallback_count"] == 2.0
    assert g_dim.detail["judged_slice_state"] == JUDGED_SLICE_STATE_CAP_STOPPED

    # Disclosure in notes
    assert "2" in report.metadata.notes
    assert "stopped by spend cap" in report.metadata.notes.lower()


def test_judge_loop_all_usage_absent_exhausts_and_discloses_in_notes(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves all-usage-absent slice runs to exhaustion and discloses fallback in notes."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:3]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    # Every response omits usage
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
        ],
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question(judge_max_tokens=400)
    cap = cost_per_q * 5.0

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    assert report.metadata.judged_slice_committed == 3
    assert report.metadata.verdicts_obtained == 3
    assert len(httpx_mock.get_requests()) == 3
    # Notes names the fallback count of 3
    assert "3" in report.metadata.notes
    assert "estimated" in report.metadata.notes.lower()

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")
    assert g_dim.detail["usage_absent_fallback_count"] == 3.0
    assert f_dim.detail["usage_absent_fallback_count"] == 3.0


def test_judge_loop_usage_absent_distinct_from_observed_zero(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves observed zero tokens charges zero and does not increment fallback count, while absent charges and increments."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:2]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    resp_zero = {
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
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }
    resp_absent = {
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
        ],
    }
    httpx_mock.add_response(json=resp_zero)
    httpx_mock.add_response(json=resp_absent)

    cost_per_q = estimate_judge_cost_per_question(judge_max_tokens=400)
    cap = cost_per_q * 5.0

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=2,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    # Only 1 call was usage-absent, zero was not fallback
    assert g_dim.detail["usage_absent_fallback_count"] == 1.0
    assert "1 judged call" in report.metadata.notes or "1 call" in report.metadata.notes


def test_judge_loop_cap_stop_note_discloses_fallback_count(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves cap-stop sentence names the fallback count when fallback charges occurred."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:3]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
                    rank=1,
                )
            ],
        )
        journal.append(rec)

    # Cost 2.5 * cost_per_q
    verdict_resp_with_usage = {
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
        ],
        "usage": {"prompt_tokens": 3000, "completion_tokens": 1000},
    }
    verdict_resp_no_usage = {
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
        ],
    }
    httpx_mock.add_response(json=verdict_resp_with_usage)
    httpx_mock.add_response(json=verdict_resp_no_usage, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question(judge_max_tokens=400)
    cap = cost_per_q * 3.0

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=3,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    assert report.metadata.judged_slice_state == "cap_stopped"
    # Cap-stop sentence in notes must name the fallback count (1)
    assert "stopped by spend cap" in report.metadata.notes.lower()
    assert "1 call" in report.metadata.notes or "1 judged call" in report.metadata.notes


def test_judge_loop_fully_observed_spend_unchanged(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves fully-observed run publishes fallback count 0 and no estimation disclosure in notes."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    for qid in qids[:2]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
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
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question(judge_max_tokens=400)
    cap = cost_per_q * 5.0

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=2,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    assert g_dim.detail["usage_absent_fallback_count"] == 0.0
    assert "omitted usage" not in (report.metadata.notes or "").lower()
    assert "fallback" not in (report.metadata.notes or "").lower()


def test_judgeable_predicate_parity_and_selection_sizing(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves candidate selection sizes slice against judgeable population only and records selection-time exclusions."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # 4 records: 2 with structured citations, 2 without
    for i, qid in enumerate(qids[:4]):
        has_citations = i % 2 == 0
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
                    rank=1,
                )
            ]
            if has_citations
            else [],
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
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question(judge_max_tokens=400)
    cap = cost_per_q * 10.0

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    # Candidate selection only sized for the 2 judgeable questions
    assert report.metadata.judged_slice_committed == 2
    assert report.metadata.verdicts_obtained == 2
    assert len(httpx_mock.get_requests()) == 2

    g_dim = next(d for d in report.dimensions if d.name == "answer_groundedness")
    f_dim = next(d for d in report.dimensions if d.name == "answer_faithfulness")
    # Selection-time exclusion count preserved in detail
    assert g_dim.detail["skipped_no_evidence"] == 2.0
    assert f_dim.detail["skipped_no_evidence"] == 2.0


def test_score_run_sample_exceeds_data_bound_clamps_and_does_not_raise(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves --sample exceeding data bound clamps to judgeable count rather than raising ScoreError."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # 2 judgeable records
    for qid in qids[:2]:
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
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
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question(judge_max_tokens=400)
    cap = cost_per_q * 10.0  # Cap funds 10 questions, but data only has 2

    client = httpx.Client()
    # sample=5 exceeds data bound (2) but is well within cap (10) -> clamps to 2 and does NOT raise!
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=5,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
    )

    assert report.metadata.judged_slice_committed == 2
    assert report.metadata.verdicts_obtained == 2
    assert len(httpx_mock.get_requests()) == 2


def test_worksheet_selection_parity_with_judgeable_predicate(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    """Proves calibration-worksheet selection uses the single judgeable predicate and never admits zero-citation records."""
    from lancet_eval.measure import estimate_judge_cost_per_question

    qids = _setup_fixtures(tmp_path)
    doc_id = _get_valid_doc_id()
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # 3 records: qids[0] and qids[1] with citations, qids[2] with empty citations
    for i, qid in enumerate(qids[:3]):
        has_citations = (i < 2)
        rec = RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=f"Answer {qid}",
            index_generation="gen-test-1",
            structured_citations=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Excerpt",
                    rank=1,
                )
            ]
            if has_citations
            else [],
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
        ],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    cost_per_q = estimate_judge_cost_per_question(judge_max_tokens=400)
    cap = cost_per_q * 10.0

    ws_path = tmp_path / "calibration_worksheet.jsonl"
    client = httpx.Client()
    score_run(
        run_dir=tmp_path,
        no_judge=False,
        stage_spend_cap=cap,
        api_key="test-api-key",
        client=client,
        emit_calibration_worksheet=ws_path,
    )

    assert ws_path.exists()
    rows = [json.loads(line) for line in ws_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data_rows = [r for r in rows if r.get("type") != "header"]
    ws_qids = {r["question_id"] for r in data_rows}
    assert qids[0] in ws_qids
    assert qids[1] in ws_qids
    assert qids[2] not in ws_qids


def test_cached_verdict_count_scoped_by_prompt_version_and_model(tmp_path: Path) -> None:
    """Proves WR-07: cached_verdict_count ignores entries with different prompt_version or
    judge_model. Extended for WR-03: also proves an entry that matches on prompt_version
    and judge_model but is stale by *content* (answer text changed on a corrected re-drive)
    is excluded too, since reachability is now judged by recomputing each currently-judgeable
    record's real cache_key rather than by comparing stored fields on cache.entries directly.
    """
    from lancet_eval.corpus import GoldQuestion
    from lancet_eval.client import StructuredCitation
    from lancet_eval.journal import RunRecord
    from lancet_eval.judge import (
        JudgeCache,
        JudgeCacheEntry,
        JudgeVerdict,
        cache_key,
        truncate_evidence,
    )
    from lancet_eval.score import _reusable_verdict_count

    cache_path = tmp_path / "judge_cache.json"
    cache = JudgeCache(cache_path)
    v = JudgeVerdict(groundedness=5, faithfulness=5, unsupported_claims=[], rationale="Good")

    citation = StructuredCitation(
        chunk_id="c1", document_id="doc-1", excerpt="Excerpt", rank=1
    )
    gold_map = {
        "q1": GoldQuestion(question_id="q1", question="Question one?"),
        "q2": GoldQuestion(question_id="q2", question="Question two?"),
        "q3": GoldQuestion(question_id="q3", question="Question three?"),
        "q4": GoldQuestion(question_id="q4", question="Question four?"),
        "q5": GoldQuestion(question_id="q5", question="Question five?"),
    }

    def _record(qid: str, answer: str) -> RunRecord:
        return RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-on",
            outcome="success",
            answer=answer,
            index_generation="gen-test-1",
            structured_citations=[citation],
        )

    def _key(qid: str, answer: str, *, prompt_version: str = "v1", judge_model: str = "openai/gpt-4o-mini") -> str:
        return cache_key(
            prompt_version=prompt_version,
            judge_model=judge_model,
            question=gold_map[qid].question,
            answer=answer,
            post_truncation_evidence=truncate_evidence([citation]),
        )

    # q1: reachable — cache_key computed under the CURRENT prompt_version/judge_model/content.
    rec_valid = _record("q1", "a1")
    k_valid = _key("q1", "a1")
    cache.set(
        k_valid,
        JudgeCacheEntry(
            cache_key=k_valid, prompt_version="v1", judge_model="openai/gpt-4o-mini",
            question=gold_map["q1"].question, answer="a1", evidence="e1", verdict=v,
        ),
    )

    # q2: stored under a superseded prompt_version — the current lookup recomputes the key
    # with prompt_version="v1", which hashes differently, so it is unreachable.
    rec_old_version = _record("q2", "a2")
    k_old_version = _key("q2", "a2", prompt_version="superseded_v0")
    cache.set(
        k_old_version,
        JudgeCacheEntry(
            cache_key=k_old_version, prompt_version="superseded_v0", judge_model="openai/gpt-4o-mini",
            question=gold_map["q2"].question, answer="a2", evidence="e2", verdict=v,
        ),
    )

    # q3: stored under a different judge_model — unreachable for the same reason.
    rec_diff_model = _record("q3", "a3")
    k_diff_model = _key("q3", "a3", judge_model="different/model")
    cache.set(
        k_diff_model,
        JudgeCacheEntry(
            cache_key=k_diff_model, prompt_version="v1", judge_model="different/model",
            question=gold_map["q3"].question, answer="a3", evidence="e3", verdict=v,
        ),
    )

    # q4: reachable by key, but has no verdict (e.g. a cached judge error) — excluded.
    rec_err = _record("q4", "a4")
    k_err = _key("q4", "a4")
    cache.set(
        k_err,
        JudgeCacheEntry(
            cache_key=k_err, prompt_version="v1", judge_model="openai/gpt-4o-mini",
            question=gold_map["q4"].question, answer="a4", evidence="e4", error="Some error",
        ),
    )

    # q5 (WR-03): stored under the PRE-correction answer text; the corrected re-drive's
    # record now has different answer content, so its freshly-computed key never matches
    # this stale entry, even though prompt_version and judge_model both still match.
    rec_stale_by_content = _record("q5", "corrected answer after re-drive")
    k_stale = _key("q5", "pre-correction answer")
    cache.set(
        k_stale,
        JudgeCacheEntry(
            cache_key=k_stale, prompt_version="v1", judge_model="openai/gpt-4o-mini",
            question=gold_map["q5"].question, answer="pre-correction answer", evidence="e5", verdict=v,
        ),
    )

    reusable = _reusable_verdict_count(
        cache,
        prompt_version="v1",
        judge_model="openai/gpt-4o-mini",
        records=[rec_valid, rec_old_version, rec_diff_model, rec_err, rec_stale_by_content],
        gold_map=gold_map,
    )
    assert reusable == 1







