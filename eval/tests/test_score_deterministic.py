"""Tests for offline deterministic scorer and ablation provenance."""

import ast
import hashlib
import json
import shutil
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
        answer="test answer",
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
        answer="test answer",
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
        question_id="qid-1",
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-1",
    )
    rec2 = RunRecord(
        corpus="multihop_rag",
        question_id="qid-2",
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
    """Proves graph-off record missing notice is dropped from join and errors."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec_on = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(index_generation="gen-test-1", retrieved_chunks=[]),
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
        snapshot=RetrievalSnapshot(index_generation="gen-test-1", retrieved_chunks=[]),
    )
    journal.append(rec_on)
    journal.append(rec_off_bad)

    report = score_run(run_dir=tmp_path, no_judge=True)
    ablation_dim = next(
        d for d in report.dimensions if d.name == "graph_ablation_delta"
    )
    assert ablation_dim.status == "error"
    assert ablation_dim.score is None
    assert ablation_dim.detail["provenance_drops"] == 1.0
    assert ablation_dim.detail["n_pairs"] == 0.0


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
        answer="test answer",
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
        answer="test answer",
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
    assert ablation_dim.detail["n_pairs"] == 1.0
    assert ablation_dim.detail["ci_lower"] == -1.0
    assert ablation_dim.detail["ci_upper"] == -1.0


def test_five_answer_dimensions_d70_d72(tmp_path: Path) -> None:
    """D-70/D-72: a fixture journal proves final_answer_em/containment/answer_usable/
    final_answer_missing_rate are computed on the extracted `Answer:` line for non-null
    questions, and legacy answer_exact_match/answer_f1 stay unchanged next to them.
    """
    questions = load_sample_questions("multihop_rag")
    yes_questions = [
        q for q in questions if q.gold_answer.strip() == "Yes" and not q.is_null
    ]
    assert len(yes_questions) >= 3
    q1, q2, q3 = yes_questions[:3]

    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    def _mk(qid: str, answer: str) -> RunRecord:
        return RunRecord(
            corpus="multihop_rag",
            question_id=qid,
            graph_arm="graph-off",
            outcome="success",
            answer=answer,
            index_generation="gen-test-1",
            notices=[
                Notice(
                    code="GRAPH_ABLATION",
                    message="",
                    typed_code=NOTICE_CODE_GRAPH_ABLATION,
                )
            ],
            snapshot=RetrievalSnapshot(
                index_generation="gen-test-1", retrieved_chunks=[]
            ),
        )

    journal.append(_mk(q1.question_id, "Some explanation.\nAnswer: Yes"))
    journal.append(_mk(q2.question_id, "Some explanation.\nAnswer: No"))
    journal.append(_mk(q3.question_id, "Some explanation with no answer line."))

    report = score_run(run_dir=tmp_path, no_judge=True)

    def _dim(name: str):
        dim = next((d for d in report.dimensions if d.name == name), None)
        assert dim is not None, f"missing dimension {name}"
        return dim

    usable = _dim("answer_usable")
    assert usable.status == "ok"
    assert usable.score == pytest.approx(1 / 3)

    missing_rate = _dim("final_answer_missing_rate")
    assert missing_rate.status == "ok"
    assert missing_rate.score == pytest.approx(1 / 3)

    final_em = _dim("final_answer_em")
    assert final_em.status == "ok"
    assert final_em.score == pytest.approx(1 / 3)

    containment = _dim("final_answer_containment")
    assert containment.status == "ok"

    # Legacy EM/F1 are scored on the full explanation text, not the extracted
    # line, and must stay untouched by this plan.
    em = _dim("answer_exact_match")
    f1 = _dim("answer_f1")
    assert em.score is not None
    assert f1.score is not None


def test_null_abstention_correctness_excluded_from_answer_usable_denominator(
    tmp_path: Path,
) -> None:
    """D-72: null_abstention_correctness is scored on null_query records only, and a
    null record never enters answer_usable's denominator.
    """
    questions = load_sample_questions("multihop_rag")
    null_q = next(q for q in questions if q.is_null)

    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)
    journal.append(
        RunRecord(
            corpus="multihop_rag",
            question_id=null_q.question_id,
            graph_arm="graph-off",
            outcome="success",
            answer="Some explanation.\nAnswer: Insufficient information.",
            index_generation="gen-test-1",
            notices=[
                Notice(
                    code="GRAPH_ABLATION",
                    message="",
                    typed_code=NOTICE_CODE_GRAPH_ABLATION,
                )
            ],
            snapshot=RetrievalSnapshot(
                index_generation="gen-test-1", retrieved_chunks=[]
            ),
        )
    )

    report = score_run(run_dir=tmp_path, no_judge=True)

    nac = next(
        (d for d in report.dimensions if d.name == "null_abstention_correctness"),
        None,
    )
    assert nac is not None, "missing dimension null_abstention_correctness"
    assert nac.status == "ok"
    assert nac.score == 1.0
    assert nac.n == 1

    usable = next((d for d in report.dimensions if d.name == "answer_usable"), None)
    assert usable is not None, "missing dimension answer_usable"
    assert usable.n == 0
    assert usable.status == "skipped"


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


# ---------------------------------------------------------------------------
# 06.3.5-06 Task 1: registry-driven arm grouping (D-101, D-120)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DRIVE2 = _REPO_ROOT / "eval" / "runs" / "2026-10-06-drive2-multihop_rag_diag"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ablation_notice() -> Notice:
    return Notice(
        code="GRAPH_ABLATION", message="", typed_code=NOTICE_CODE_GRAPH_ABLATION
    )


def _arm_record(
    qid: str,
    arm: str,
    chunks: list[StructuredCitation] | None = None,
    *,
    ablation: bool = False,
) -> RunRecord:
    return RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer="test answer",
        index_generation="gen-test-1",
        notices=[_ablation_notice()] if ablation else [],
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1", retrieved_chunks=chunks or []
        ),
    )


def _four_arm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Score against a corpus config that configures all four D-101 arms."""
    import lancet_eval.score as score_mod

    real = score_mod.load_corpus_config

    def _load(name: str):  # type: ignore[no-untyped-def]
        cfg = real(name)
        cfg.arms = ["dense-only", "bm25-only", "hybrid", "hybrid+graph"]
        return cfg

    monkeypatch.setattr(score_mod, "load_corpus_config", _load)


def test_rescore_of_the_recorded_drive2_reproduces_its_report(
    tmp_path: Path,
) -> None:
    """D-101 re-score proof: every dimension of the committed drive-2 report is
    reproduced from a tmp copy, and the recorded files are byte-identical."""
    journal = _DRIVE2 / "journal.jsonl"
    report = _DRIVE2 / "report.json"
    before = (_sha(journal), _sha(report))

    copy = tmp_path / "drive2"
    shutil.copytree(_DRIVE2, copy)
    scored = score_run(run_dir=copy, no_judge=True)

    committed = json.loads(report.read_text(encoding="utf-8"))["dimensions"]
    got = [(d.name, d.status, d.score, d.n) for d in scored.dimensions]
    want = [(d["name"], d["status"], d["score"], d["n"]) for d in committed]
    assert got == want
    assert (_sha(journal), _sha(report)) == before


def test_an_unknown_arm_label_fails_closed_naming_label_and_count(
    tmp_path: Path,
) -> None:
    """T-06.3.5-19: a record whose label is not in the registry is refused, never
    dropped (score.py used to drop it)."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(_arm_record(qid, "graph-on"))
    journal.append(_arm_record(qid, "graph-sideways"))

    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=tmp_path, no_judge=True)

    message = str(exc_info.value)
    assert "graph-sideways" in message
    assert "1 record(s)" in message


def test_a_question_under_an_alias_and_its_canonical_label_is_refused(
    tmp_path: Path,
) -> None:
    """T-06.3.5-21: `deduplicate_by_arm` keys on the raw label and would keep both."""
    _, qid = _setup_mock_corpus_files(tmp_path)
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(_arm_record(qid, "graph-off", ablation=True))
    journal.append(_arm_record(qid, "hybrid", ablation=True))

    with pytest.raises(ScoreError) as exc_info:
        score_run(run_dir=tmp_path, no_judge=True)

    message = str(exc_info.value)
    assert qid in message
    assert "graph-off" in message
    assert "hybrid" in message


def test_a_four_arm_journal_keeps_every_arm_and_scores_hybrid_plus_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-101: all four configured arms group under their own label, the primary arm
    is `hybrid+graph`, and the ablation delta pairs it with `hybrid`."""
    _four_arm_config(monkeypatch)
    q1 = load_sample_questions("multihop_rag")[0]
    doc_id = _get_valid_doc_id()
    full = [
        StructuredCitation(
            chunk_id=f"c{i}", document_id=doc_id, excerpt=f"match {fact}", rank=i + 1
        )
        for i, fact in enumerate(q1.gold_facts)
    ]
    none = [
        StructuredCitation(
            chunk_id="c1", document_id=doc_id, excerpt="irrelevant", rank=1
        )
    ]
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(_arm_record(q1.question_id, "dense-only", full, ablation=True))
    journal.append(_arm_record(q1.question_id, "bm25-only", full, ablation=True))
    journal.append(_arm_record(q1.question_id, "hybrid", full, ablation=True))
    journal.append(_arm_record(q1.question_id, "hybrid+graph", none))

    report = score_run(run_dir=tmp_path, no_judge=True)

    coverage = next(
        d for d in report.dimensions if d.name == "retrieval_evidence_coverage"
    )
    assert coverage.status == "ok"
    assert coverage.score == 0.0  # the primary arm is hybrid+graph, not hybrid
    assert coverage.n == 1
    delta = next(d for d in report.dimensions if d.name == "graph_ablation_delta")
    assert delta.status == "ok"
    assert delta.score == -1.0
    assert delta.detail["n_pairs"] == 1.0


def test_graph_off_provenance_applies_to_every_arm_that_disables_graph_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-101: with no `hybrid+graph` records the primary arm is `hybrid`, and a
    `hybrid` record without the GRAPH_ABLATION notice is a provenance exclusion."""
    _four_arm_config(monkeypatch)
    questions = load_sample_questions("multihop_rag")
    journal = Journal(tmp_path / "journal.jsonl")
    journal.append(_arm_record(questions[0].question_id, "hybrid", ablation=True))
    journal.append(_arm_record(questions[1].question_id, "hybrid", ablation=False))
    journal.append(_arm_record(questions[0].question_id, "dense-only"))

    report = score_run(run_dir=tmp_path, no_judge=True)

    coverage = next(
        d for d in report.dimensions if d.name == "retrieval_evidence_coverage"
    )
    assert coverage.detail["errors"] == 1.0


def test_score_module_no_longer_hardcodes_the_two_legacy_arms() -> None:
    """The literal `{"graph-on": [], "graph-off": []}` grouping is gone."""
    source = (_REPO_ROOT / "eval/src/lancet_eval/score.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "canonical_arm(" in source
    assert '{"graph-on": [], "graph-off": []}' not in source
