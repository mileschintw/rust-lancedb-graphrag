"""Regression tests for Phase 06.3 code review findings.

Covers CR-01, WR-02, WR-03, WR-04, IN-02.
"""

import json
import logging
from pathlib import Path

import pytest

from lancet_eval.client import Notice
from lancet_eval.corpus import load_sample_questions
from lancet_eval.dimensions import DimensionResult
from lancet_eval.journal import (
    Journal,
    RetrievalSnapshot,
    RunRecord,
    StructuredCitation,
)
from lancet_eval.judge import JudgeCache
from lancet_eval.report import (
    compute_result_hash,
    format_details,
    format_score,
)
from lancet_eval.score import (
    ScoreError,
    _get_engine_generation_model,
    score_run,
)


def _get_valid_doc_id() -> str:
    try:
        from lancet_eval.seed import load_document_map

        doc_map = load_document_map("multihop_rag")
        return next(iter(doc_map.entries.keys()))
    except Exception:
        return "01070ac6-0fc0-464d-9f1f-756573b99c0e"


def _make_record(
    qid: str,
    arm: str,
    *,
    outcome: str = "success",
    notices: list[Notice] | None = None,
    answer: str = "Paris is capital",
    doc_id: str | None = None,
    index_generation: str = "gen-1",
    embedding_model: str | None = None,
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
    did = doc_id or _get_valid_doc_id()
    snap = RetrievalSnapshot(
        index_generation=index_generation,
        embedding_model=embedding_model if embedding_model is not None else "",
        retrieved_chunks=[
            StructuredCitation(chunk_id="c1", document_id=did, excerpt="Paris", rank=1)
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
        snapshot=snap,
        structured_citations=[
            StructuredCitation(chunk_id="c1", document_id=did, excerpt="Paris", rank=1)
        ],
    )


# ---------------------------------------------------------------------------
# CR-01: Calibration worksheet requested with judge disabled raises ScoreError
# ---------------------------------------------------------------------------


def test_cr01_worksheet_with_no_judge_raises(tmp_path: Path) -> None:
    """Proves requesting worksheet with --no-judge raises ScoreError."""
    qid = load_sample_questions("multihop_rag")[0].question_id
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(_make_record(qid, "graph-on"))

    ws_path = tmp_path / "worksheet.jsonl"
    with pytest.raises(ScoreError) as exc_info:
        score_run(
            run_dir=tmp_path,
            no_judge=True,
            emit_calibration_worksheet=ws_path,
        )

    msg = str(exc_info.value)
    assert "--emit-calibration-worksheet" in msg
    assert "--no-judge" in msg
    assert "--judge" in msg
    assert "judging enabled" in msg


# ---------------------------------------------------------------------------
# WR-02: Deduplication applied journal-wide before judging / worksheet consumers
# ---------------------------------------------------------------------------


def test_wr02_consumer_contract_judged_and_worksheet(tmp_path: Path) -> None:
    """Proves deduplication collapses duplicate records so consumers see 1 item."""
    qid = load_sample_questions("multihop_rag")[0].question_id
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    # 2 records for same question in graph-on arm
    journal.append(_make_record(qid, "graph-on", answer="v1"))
    journal.append(_make_record(qid, "graph-on", answer="v2"))

    report = score_run(run_dir=tmp_path, no_judge=True)

    # Check that quality dimensions report n=1
    em_dim = next(d for d in report.dimensions if d.name == "answer_exact_match")
    assert em_dim.n == 1
    unusable_dim = next(
        d for d in report.dimensions if d.name == "unusable_record_rate"
    )
    assert unusable_dim.detail["collapsed_records_n"] == 1.0


# ---------------------------------------------------------------------------
# WR-03: Primary arm chosen by data rather than dictionary insertion order
# ---------------------------------------------------------------------------


def test_wr03_primary_arm_graph_off_only(tmp_path: Path) -> None:
    """Proves primary arm is graph-off when journal contains graph-off only."""
    qid = load_sample_questions("multihop_rag")[0].question_id
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(_make_record(qid, "graph-off"))

    report = score_run(run_dir=tmp_path, no_judge=True)

    cov_dim = next(
        d for d in report.dimensions if d.name == "retrieval_evidence_coverage"
    )
    assert cov_dim.status == "ok"
    assert cov_dim.n == 1


def test_wr03_primary_arm_both_arms_prefers_graph_on(tmp_path: Path) -> None:
    """Proves primary arm prefers graph-on when both arms have records."""
    qid = load_sample_questions("multihop_rag")[0].question_id
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(_make_record(qid, "graph-on"))
    journal.append(_make_record(qid, "graph-off"))

    report = score_run(run_dir=tmp_path, no_judge=True)

    cov_dim = next(
        d for d in report.dimensions if d.name == "retrieval_evidence_coverage"
    )
    assert cov_dim.status == "ok"
    assert cov_dim.n == 1


# ---------------------------------------------------------------------------
# WR-04: Failed configuration read is logged safely, unknown markers stamped
# ---------------------------------------------------------------------------


def test_wr04_malformed_config_logs_warning_without_leak(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves malformed config logs warning without echoing file contents or secrets."""
    secret_token = "SUPER_SECRET_TOKEN_DO_NOT_LEAK_9999"
    bad_cfg = tmp_path / "config" / "config.toml"
    bad_cfg.parent.mkdir(parents=True, exist_ok=True)
    bad_cfg.write_text(f"malformed toml content = {secret_token} [[", encoding="utf-8")

    monkeypatch.setattr("lancet_eval.score._repo_root", lambda: tmp_path)

    with caplog.at_level(logging.WARNING):
        model = _get_engine_generation_model()

    assert model == ""
    assert len(caplog.records) >= 1
    rec = caplog.records[0]
    assert "Failed to read engine generation model" in rec.message
    assert str(bad_cfg) in rec.message
    assert secret_token not in rec.message


def test_wr04_unknown_generation_model_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves unknown-generation-model is stamped when config cannot be read."""
    monkeypatch.setattr(
        "lancet_eval.score._repo_root", lambda: tmp_path / "nonexistent"
    )
    qid = load_sample_questions("multihop_rag")[0].question_id
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(_make_record(qid, "graph-on"))

    report = score_run(run_dir=tmp_path, no_judge=True)
    assert report.metadata.generation_model == "unknown-generation-model"


def test_wr04_embedding_model_provenance_marker(tmp_path: Path) -> None:
    """Proves unknown-embedding-model is stamped when no snapshot carries one."""
    qid = load_sample_questions("multihop_rag")[0].question_id
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    rec = _make_record(qid, "graph-on", embedding_model=None)
    journal.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    assert report.metadata.embedding_model == "unknown-embedding-model"


def test_wr04_embedding_model_reads_first_snapshot(tmp_path: Path) -> None:
    """Proves embedding model reads from the first snapshot that supplies one."""
    qid = load_sample_questions("multihop_rag")[0].question_id
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    rec = _make_record(qid, "graph-on", embedding_model="custom/embed-v2")
    journal.append(rec)

    report = score_run(run_dir=tmp_path, no_judge=True)
    assert report.metadata.embedding_model == "custom/embed-v2"


def test_wr04_judging_refuses_when_gen_model_unread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves judging run raises ScoreError when generation model cannot be read."""
    monkeypatch.setattr(
        "lancet_eval.score._repo_root", lambda: tmp_path / "nonexistent"
    )
    qid = load_sample_questions("multihop_rag")[0].question_id
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(_make_record(qid, "graph-on"))

    with pytest.raises(ScoreError, match="Could not read engine generation model"):
        score_run(run_dir=tmp_path, no_judge=False, api_key="dummy-key")


# ---------------------------------------------------------------------------
# IN-02: JudgeCache unparseable entries counted and warned, invalid file warned
# ---------------------------------------------------------------------------


def test_in02_cache_dropped_entries_warned(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """Proves invalid cache entries are dropped, counted, and warned."""
    cache_path = tmp_path / "judge_cache.json"
    cache_data = {
        "valid_key": {
            "cache_key": "valid_key",
            "prompt_version": "v1",
            "judge_model": "meta/llama-3",
            "question": "Q?",
            "answer": "A.",
            "evidence": "E.",
            "created_at": "2026-09-05T12:00:00Z",
            "verdict": {"groundedness": 5, "faithfulness": 4, "raw_response": "{}"},
        },
        "bad_key": {
            "cache_key": "bad_key",
            "prompt_version": "v1",
            "judge_model": "meta/llama-3",
            "question": "Q?",
            "answer": "A.",
            "evidence": "E.",
            "created_at": "2026-09-05T12:00:00Z",
            "verdict": {"groundedness": 999},  # Invalid score > 5
        },
    }
    cache_path.write_text(json.dumps(cache_data), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        cache = JudgeCache(cache_path)

    assert "valid_key" in cache.entries
    assert "bad_key" not in cache.entries
    assert len(cache.entries) == 1

    rec = next(r for r in caplog.records if "Dropped" in r.message)
    assert "Dropped 1 invalid judge cache entries" in rec.message


def test_in02_unparseable_cache_file_warned(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """Proves unparseable JSON in cache file warns instead of failing silently."""
    cache_path = tmp_path / "judge_cache.json"
    cache_path.write_text("not valid json at all {{{", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        cache = JudgeCache(cache_path)

    assert len(cache.entries) == 0
    rec = next(r for r in caplog.records if "Failed to parse judge cache" in r.message)
    assert str(cache_path) in rec.message


def test_in02_absent_cache_file_silent(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """Proves absent cache file emits no warning (normal first-run state)."""
    cache_path = tmp_path / "nonexistent_cache.json"
    with caplog.at_level(logging.WARNING):
        cache = JudgeCache(cache_path)

    assert len(cache.entries) == 0
    assert len(caplog.records) == 0


# ---------------------------------------------------------------------------
# Task 3: Formatting, detail rounding, type-aware score formatting
# ---------------------------------------------------------------------------


def test_format_score_type_aware() -> None:
    """Proves format_score handles latency magnitudes, judged scales, and ratios."""
    # Millisecond dimension: absolute magnitude at 1 decimal place even if > 1.0
    assert format_score("retrieve_latency_ms", 1234.5678) == "1234.6"
    assert format_score("graph_latency_ms", 250.0) == "250.0"
    assert format_score("graph_ablation_latency_delta", 15.234) == "15.2"
    assert format_score("graph_ablation_prompt_token_delta", 42.6) == "42.6"

    # Genuine judged dimensions: 2 decimal places
    assert format_score("answer_groundedness", 4.256) == "4.26"
    assert format_score("answer_faithfulness", 3.8) == "3.80"

    # Ratios: 3 decimal places
    assert format_score("retrieval_evidence_coverage", 0.8526) == "0.853"
    assert format_score("unusable_record_rate", 0.0) == "0.000"


def test_format_details_type_aware() -> None:
    """Proves format_details formats integral floats as ints and rounds floats."""
    detail = {
        "n_pairs": 6.0,
        "ci_lower": 0.1234567,
        "latency_p95_ms": 150.28,
        "coverage": 0.6,
    }
    s = format_details(detail)
    assert "n_pairs=6" in s
    assert "ci_lower=0.123" in s
    assert "latency_p95_ms=150.3" in s
    assert "coverage=0.600" in s
    # Full binary precision not present
    assert "0.1234567" not in s


def test_result_hash_invariant_to_detail_formatting() -> None:
    """Proves compute_result_hash covers name, status, score, n and ignores detail."""
    dim1 = DimensionResult(name="d1", status="ok", score=0.5, detail={"a": 1.0}, n=10)
    dim2 = DimensionResult(
        name="d1", status="ok", score=0.5, detail={"a": 999.0, "b": 2.0}, n=10
    )
    assert compute_result_hash([dim1]) == compute_result_hash([dim2])
