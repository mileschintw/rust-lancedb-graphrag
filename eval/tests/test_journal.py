"""Unit and contract tests for append-only journal and resume key management."""

import json
from pathlib import Path

from lancet_eval.client import RetrievalSnapshot, StructuredCitation
from lancet_eval.config import repo_root
from lancet_eval.journal import Journal, RunRecord, journal_key, load_done


def test_run_record_fields_and_attribute_access() -> None:
    rec = RunRecord(
        corpus="multihop_rag",
        question_id="mhr-0001",
        graph_arm="graph-on",
        outcome="success",
        answer="Paris is the capital.",
        snapshot=RetrievalSnapshot(
            index_generation="gen-1",
            retrieved_chunks=[
                StructuredCitation(chunk_id="c1", document_id="d1", rank=1),
                StructuredCitation(chunk_id="c2", document_id="d1", rank=2),
            ],
        ),
        structured_citations=[
            StructuredCitation(chunk_id="c1", document_id="d1", rank=1)
        ],
    )
    assert rec.snapshot is not None
    assert len(rec.snapshot.retrieved_chunks) == 2
    assert rec.snapshot.retrieved_chunks[0].chunk_id == "c1"
    assert len(rec.structured_citations) == 1
    assert rec.structured_citations[0].chunk_id == "c1"


def test_distinct_lists_round_trip(tmp_path: Path) -> None:
    """Proves retrieved_chunks and structured_citations round-trip distinctly."""
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
        snapshot=RetrievalSnapshot(
            retrieved_chunks=[
                StructuredCitation(chunk_id="c1", document_id="d1", rank=1),
                StructuredCitation(chunk_id="c2", document_id="d1", rank=2),
                StructuredCitation(chunk_id="c3", document_id="d1", rank=3),
            ]
        ),
        structured_citations=[
            StructuredCitation(chunk_id="c9", document_id="d2", rank=1)
        ],
    )
    journal.append(rec)

    with open(j_path, encoding="utf-8") as f:
        line = f.readline()
    loaded_data = json.loads(line)
    reloaded = RunRecord.model_validate(loaded_data)

    assert reloaded.snapshot is not None
    loaded_retrieved = [c.chunk_id for c in reloaded.snapshot.retrieved_chunks]
    loaded_cited = [c.chunk_id for c in reloaded.structured_citations]

    assert loaded_retrieved == ["c1", "c2", "c3"]
    assert loaded_cited == ["c9"]
    assert loaded_retrieved != loaded_cited


def test_distinguishable_absent_vs_empty_snapshot(tmp_path: Path) -> None:
    """Proves snapshot=None is distinct from snapshot with empty retrieved_chunks."""
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec_none = RunRecord(
        corpus="multihop_rag",
        question_id="q_none",
        graph_arm="graph-on",
        outcome="success",
        snapshot=None,
    )
    rec_empty = RunRecord(
        corpus="multihop_rag",
        question_id="q_empty",
        graph_arm="graph-on",
        outcome="success",
        snapshot=RetrievalSnapshot(retrieved_chunks=[]),
    )

    journal.append(rec_none)
    journal.append(rec_empty)

    with open(j_path, encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2
    raw_none = json.loads(lines[0])
    raw_empty = json.loads(lines[1])

    # Assert raw JSON contains explicit "snapshot": null rather than omitting the key
    assert "snapshot" in raw_none
    assert raw_none["snapshot"] is None

    # Assert reloaded models preserve the distinction
    loaded_none = RunRecord.model_validate(raw_none)
    loaded_empty = RunRecord.model_validate(raw_empty)

    assert loaded_none.snapshot is None
    assert loaded_empty.snapshot is not None
    assert loaded_empty.snapshot.retrieved_chunks == []


def test_no_pydantic_exclusion_flags_in_journal() -> None:
    journal_file = repo_root() / "eval" / "src" / "lancet_eval" / "journal.py"
    with open(journal_file, encoding="utf-8") as f:
        lines = [line.strip() for line in f if not line.strip().startswith("#")]

    code = "\n".join(lines)
    for flag in ("exclude_none", "exclude_unset", "exclude_defaults"):
        assert flag not in code, (
            f"Forbidden serializer flag {flag!r} found in {journal_file}"
        )


def test_load_done_skips_truncated_trailing_line(tmp_path: Path) -> None:
    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec1 = RunRecord(
        corpus="multihop_rag",
        question_id="q1",
        graph_arm="graph-on",
        outcome="success",
    )
    rec2 = RunRecord(
        corpus="multihop_rag",
        question_id="q2",
        graph_arm="graph-off",
        outcome="success",
    )
    journal.append(rec1)
    journal.append(rec2)

    # Append a corrupted / truncated line
    with open(j_path, "a", encoding="utf-8") as f:
        f.write(
            '{"corpus": "multihop_rag", "question_id": "q3", "graph_arm": "graph-on"\n'
        )

    done = load_done(j_path)
    assert journal_key("multihop_rag", "q1", "graph-on") in done
    assert journal_key("multihop_rag", "q2", "graph-off") in done
    assert journal_key("multihop_rag", "q3", "graph-on") not in done


# --- 06.3.4.1-33 Task 1: prior_attempts schema and strict back-compat -----------

_RUNS = repo_root() / "eval" / "runs"
_RECORDED_DRIVES = [
    _RUNS / "2026-09-30-drive1-multihop_rag_diag" / "journal.jsonl",
    _RUNS / "2026-10-01-drive1b-multihop_rag_diag" / "journal.jsonl",
    _RUNS / "2026-10-06-drive2-multihop_rag_diag" / "journal.jsonl",
]
_PASS_A = _RUNS / "2026-09-28-passA-measure-multihop_rag" / "journal.jsonl"


def _strict_lines(path: Path) -> list[str]:
    """Every non-empty, non-header line, read raw (never through load_records)."""
    out: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            if json.loads(line).get("type") == "header":
                continue
            out.append(line)
    return out


def test_prior_attempts_defaults_to_empty_and_is_inherited() -> None:
    from lancet_eval.measure import MeasurementRecord

    rec = RunRecord(corpus="c", question_id="q", graph_arm="graph-on", outcome="success")
    assert rec.prior_attempts == []

    meas = MeasurementRecord(
        corpus="c",
        question_id="q",
        graph_arm="graph-on",
        outcome="success",
        ordinal=0,
        segment="s",
    )
    assert meas.prior_attempts == []


def test_attempt_record_is_strict_and_round_trips(tmp_path: Path) -> None:
    import pytest
    from pydantic import ValidationError

    from lancet_eval.journal import AttemptRecord

    with pytest.raises(ValidationError):
        AttemptRecord(attempt=1, outcome="error", surprise="x")  # type: ignore[call-arg]

    rec = RunRecord(
        corpus="c",
        question_id="q",
        graph_arm="graph-on",
        outcome="success",
        prior_attempts=[
            AttemptRecord(
                attempt=1,
                outcome="error",
                error_type="ReadTimeout",
                error="read timed out",
                duration_ms=12.5,
            )
        ],
    )
    j = Journal(tmp_path / "journal.jsonl")
    j.append(rec)
    line = (tmp_path / "journal.jsonl").read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(line)["prior_attempts"][0]["error_type"] == "ReadTimeout"
    assert RunRecord.model_validate_json(line) == rec


def test_recorded_drive_journals_validate_strictly_with_empty_prior_attempts() -> None:
    """Back-compat (T-06.3.4.1-33-05): 200 records per drive journal, none retried."""
    for path in _RECORDED_DRIVES:
        lines = _strict_lines(path)
        assert len(lines) == 200, path
        for line in lines:
            rec = RunRecord.model_validate_json(line)
            assert rec.prior_attempts == []


def test_recorded_pass_a_journal_validates_strictly_with_empty_prior_attempts() -> None:
    from lancet_eval.measure import MeasurementRecord

    lines = _strict_lines(_PASS_A)
    assert len(lines) == 324
    for line in lines:
        rec = MeasurementRecord.model_validate_json(line)
        assert rec.prior_attempts == []


# --- 06.3.4.1-33 Task 3: the gate-stage header marker ---------------------------


def test_write_header_carries_gate_stage_and_max_retries(tmp_path: Path) -> None:
    from lancet_eval.journal import read_journal_header

    path = tmp_path / "journal.jsonl"
    Journal(path).write_header(
        corpus="multihop_rag", partial=True, gate_stage="drive3", max_retries=0
    )

    header = read_journal_header(path)
    assert header is not None
    assert header["type"] == "header"
    assert header["gate_stage"] == "drive3"
    assert header["max_retries"] == 0


def test_write_header_records_a_null_gate_stage_for_a_non_gate_drive(
    tmp_path: Path,
) -> None:
    from lancet_eval.journal import read_journal_header

    path = tmp_path / "journal.jsonl"
    Journal(path).write_header(corpus="multihop_rag", partial=True, max_retries=2)

    header = read_journal_header(path)
    assert header is not None
    assert "gate_stage" in header and header["gate_stage"] is None
    assert header["max_retries"] == 2


def test_write_header_without_max_retries_keeps_the_four_key_header(
    tmp_path: Path,
) -> None:
    path = tmp_path / "journal.jsonl"
    Journal(path).write_header(corpus="multihop_rag", partial=False)

    header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert set(header) == {"type", "corpus", "partial", "created_at"}


def test_write_header_does_not_overwrite_a_non_empty_journal(tmp_path: Path) -> None:
    from lancet_eval.journal import read_journal_header

    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    journal.write_header(
        corpus="multihop_rag", partial=True, gate_stage="drive3", max_retries=0
    )
    journal.write_header(
        corpus="multihop_rag", partial=True, gate_stage="other", max_retries=2
    )

    header = read_journal_header(path)
    assert header is not None
    assert header["gate_stage"] == "drive3"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_read_journal_header_returns_none_when_there_is_no_header(
    tmp_path: Path,
) -> None:
    from lancet_eval.journal import read_journal_header

    assert read_journal_header(tmp_path / "missing.jsonl") is None

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert read_journal_header(empty) is None

    record_first = tmp_path / "record_first.jsonl"
    Journal(record_first).append(
        RunRecord(corpus="c", question_id="q", graph_arm="graph-on", outcome="success")
    )
    assert read_journal_header(record_first) is None

    garbled = tmp_path / "garbled.jsonl"
    garbled.write_text("not json\n", encoding="utf-8")
    assert read_journal_header(garbled) is None
