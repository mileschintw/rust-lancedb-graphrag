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
