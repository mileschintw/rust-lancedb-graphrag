"""Context export from engine checkpoints (D-249), via the in-memory checkpoint source.

Seam S-B: a fixture journal plus in-memory `terminal_success` checkpoints, then the
exported rows and the fail-closed refusals. No test here needs Postgres.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Collection
from pathlib import Path
from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from lancet_eval.cli import app
from lancet_eval.config import EvalSettings
from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    CheckpointRow,
    ContextExportError,
    InMemoryCheckpointSource,
    PostgresCheckpointSource,
    export_context,
    read_export,
    require_export_rows,
    validate_row,
)
from lancet_eval.journal import Journal, RunRecord, read_journal_header
from lancet_eval.run import drive
from lancet_eval.score import ScoreError, score_run

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "context_export"


def _snapshot(trace_id: str = "trace-q1-on", **overrides: Any) -> dict[str, Any]:
    raw = json.loads(
        (FIXTURES / "terminal_success_snapshot.json").read_text(encoding="utf-8")
    )
    snapshot = copy.deepcopy(raw)
    snapshot["trace_id"] = trace_id
    snapshot.update(overrides)
    return snapshot


def _record(
    question_id: str = "q1",
    arm: str = "graph-on",
    *,
    correlation_id: str = "trace-q1-on",
    outcome: str = "success",
) -> RunRecord:
    return RunRecord(
        corpus="multihop_rag",
        question_id=question_id,
        graph_arm=arm,
        outcome=outcome,  # type: ignore[arg-type]
        answer="Answer: The Verge" if outcome == "success" else None,
        correlation_id=correlation_id,
    )


def _journal(tmp_path: Path, *records: RunRecord) -> Path:
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    journal.write_header(corpus="multihop_rag", partial=False)
    for record in records:
        journal.append(record)
    return path


def _rows(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_export_writes_one_row_per_success_record_from_its_checkpoint(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path, _record())
    source = InMemoryCheckpointSource([
        CheckpointRow(trace_id="trace-q1-on", snapshot=_snapshot())
    ])

    written = export_context(journal, source)

    assert written == tmp_path / CONTEXT_EXPORT_FILE
    [row] = _rows(written)
    assert row["corpus"] == "multihop_rag"
    assert row["question_id"] == "q1"
    assert row["arm"] == "graph-on"
    assert row["question"] == "Which outlet reported the merger first?"
    assert row["correlation_id"] == "trace-q1-on"
    assert row["assembled_prompt"] == "<evidence>[1] Acme announced ...</evidence>"
    assert row["evidence"] == [
        {
            "rank": 1,
            "chunk_id": "c-1",
            "document_id": "doc-a",
            "text": "Acme announced on Monday that it will buy Globex.",
            "title": "acme-globex.md",
            "section_path": "Root",
            "content_type": "text/markdown",
            "score": 0.91,
            "suspicious": False,
            "document_metadata": {
                "source": "The Verge",
                "doc_title": "Acme to buy Globex",
                "published_date": "2023-10-02",
            },
        },
        {
            "rank": 2,
            "chunk_id": "c-2",
            "document_id": "doc-b",
            "text": "Globex shareholders approved the deal.",
            "title": None,
            "section_path": None,
            "content_type": None,
            "score": 0.42,
            "suspicious": False,
            "document_metadata": {
                "source": None,
                "doc_title": None,
                "published_date": None,
            },
        },
    ]
    assert row["graph_facts"] == [
        {
            "fact": {
                "entity_a_name": "Acme",
                "relation_type": "ACQUIRED",
                "entity_b_name": "Globex",
                "edge_summary": "Acme acquired Globex in 2023.",
                "score": 0.8,
            }
        }
    ]


def test_a_success_record_with_no_checkpoint_fails_closed_naming_question_and_arm(
    tmp_path: Path,
) -> None:
    journal = _journal(
        tmp_path,
        _record(),
        _record("q2", "graph-off", correlation_id="trace-q2-off"),
    )
    source = InMemoryCheckpointSource([
        CheckpointRow(trace_id="trace-q1-on", snapshot=_snapshot())
    ])

    with pytest.raises(ContextExportError, match=r"q2/graph-off.*no terminal_success"):
        export_context(journal, source)

    assert not (tmp_path / CONTEXT_EXPORT_FILE).exists()


def _broken_block_snapshot() -> dict[str, Any]:
    snapshot = _snapshot()
    del snapshot["evidence_blocks"][0]["chunk_id"]
    return snapshot


@pytest.mark.parametrize(
    ("record", "checkpoints", "reason"),
    [
        pytest.param(
            _record(correlation_id=""),
            [CheckpointRow(trace_id="trace-q1-on", snapshot=_snapshot())],
            "no correlation_id",
            id="record-without-correlation-id",
        ),
        pytest.param(
            _record(),
            [
                CheckpointRow(trace_id="trace-q1-on", snapshot=_snapshot()),
                CheckpointRow(trace_id="trace-q1-on", snapshot=_snapshot()),
            ],
            "2 terminal_success checkpoints",
            id="two-checkpoints-for-one-trace",
        ),
        pytest.param(
            _record(),
            [
                CheckpointRow(
                    trace_id="trace-q1-on", snapshot=_snapshot(trace_id="trace-other")
                )
            ],
            "snapshot trace_id",
            id="snapshot-names-another-trace",
        ),
        pytest.param(
            _record(),
            [CheckpointRow(trace_id="trace-q1-on", snapshot=_broken_block_snapshot())],
            "contract",
            id="snapshot-breaks-the-row-contract",
        ),
    ],
)
def test_an_unjoinable_success_record_fails_closed_naming_question_and_arm(
    tmp_path: Path, record: RunRecord, checkpoints: list[CheckpointRow], reason: str
) -> None:
    journal = _journal(tmp_path, record)

    with pytest.raises(ContextExportError, match=rf"q1/graph-on: .*{reason}"):
        export_context(journal, InMemoryCheckpointSource(checkpoints))

    assert not (tmp_path / CONTEXT_EXPORT_FILE).exists()


def test_error_records_get_no_row(tmp_path: Path) -> None:
    journal = _journal(
        tmp_path,
        _record(),
        _record("q2", "graph-off", correlation_id="trace-q2-off", outcome="error"),
    )
    source = InMemoryCheckpointSource([
        CheckpointRow(trace_id="trace-q1-on", snapshot=_snapshot())
    ])

    rows = _rows(export_context(journal, source))

    assert [(r["question_id"], r["arm"]) for r in rows] == [("q1", "graph-on")]


def test_a_record_that_ended_with_no_evidence_exports_an_empty_list(
    tmp_path: Path,
) -> None:
    journal = _journal(tmp_path, _record())
    source = InMemoryCheckpointSource([
        CheckpointRow(
            trace_id="trace-q1-on",
            snapshot=_snapshot(evidence_blocks=[], graph_facts=[]),
        )
    ])

    [row] = _rows(export_context(journal, source))

    assert row["evidence"] == []
    assert validate_row(row).evidence == []


def _valid_row() -> dict[str, Any]:
    return {
        "corpus": "multihop_rag",
        "question_id": "q1",
        "arm": "graph-on",
        "question": "Which outlet reported the merger first?",
        "evidence": [
            {
                "rank": rank,
                "chunk_id": f"c-{rank}",
                "document_id": "doc-a",
                "text": f"evidence {rank}",
                "title": None,
                "section_path": None,
                "content_type": None,
                "score": 1.0 / rank,
                "suspicious": False,
                "document_metadata": {
                    "source": None,
                    "doc_title": None,
                    "published_date": None,
                },
            }
            for rank in (1, 2, 3)
        ],
        "graph_facts": [],
        "assembled_prompt": "prompt",
        "correlation_id": "trace-q1-on",
    }


def _with(**changes: Any) -> dict[str, Any]:
    row = _valid_row()
    row.update(changes)
    return row


def _ranks(*ranks: int) -> dict[str, Any]:
    row = _valid_row()
    for entry, rank in zip(row["evidence"], ranks, strict=True):
        entry["rank"] = rank
    return row


def _without(key: str) -> dict[str, Any]:
    row = _valid_row()
    del row[key]
    return row


def test_the_validator_accepts_a_lancet_row_and_an_external_row() -> None:
    external = _with(assembled_prompt=None, correlation_id=None)

    assert validate_row(_valid_row()).correlation_id == "trace-q1-on"
    assert validate_row(external).assembled_prompt is None


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        pytest.param(_without("question"), "question", id="missing-question"),
        pytest.param(_without("evidence"), "evidence", id="missing-evidence"),
        pytest.param(_without("graph_facts"), "graph_facts", id="missing-graph-facts"),
        pytest.param(_with(question_id=""), "question_id", id="empty-question-id"),
        pytest.param(_with(unexpected=1), "unexpected", id="unknown-field"),
        pytest.param(_ranks(1, 3, 2), "ranks", id="unordered-ranks"),
        pytest.param(_ranks(1, 2, 2), "ranks", id="duplicate-ranks"),
        pytest.param(_ranks(0, 1, 2), "ranks", id="rank-below-one"),
        pytest.param(
            _with(correlation_id=None), "both or neither", id="prompt-without-id"
        ),
        pytest.param(
            _with(assembled_prompt=None), "both or neither", id="id-without-prompt"
        ),
    ],
)
def test_the_validator_rejects_a_row_that_breaks_the_contract(
    row: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ContextExportError, match=reason):
        validate_row(row)


def test_read_export_rejects_two_rows_for_one_question_and_arm(tmp_path: Path) -> None:
    path = tmp_path / CONTEXT_EXPORT_FILE
    line = json.dumps(_valid_row())
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ContextExportError, match=r"line 2: .*q1/graph-on"):
        read_export(path)


def test_read_export_names_the_line_of_a_bad_row(tmp_path: Path) -> None:
    path = tmp_path / CONTEXT_EXPORT_FILE
    path.write_text(
        json.dumps(_valid_row()) + "\n" + json.dumps(_ranks(2, 1, 3)) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ContextExportError, match=r"(?s)line 2: .*ranks"):
        read_export(path)


def test_read_export_returns_the_rows_of_an_export_it_wrote(tmp_path: Path) -> None:
    journal = _journal(tmp_path, _record())
    source = InMemoryCheckpointSource([
        CheckpointRow(trace_id="trace-q1-on", snapshot=_snapshot())
    ])

    [row] = read_export(export_context(journal, source))

    assert (row.question_id, row.arm, [e.rank for e in row.evidence]) == (
        "q1",
        "graph-on",
        [1, 2],
    )


def test_the_postgres_source_reads_terminal_success_rows_from_psql_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter's query and parsing, against canned psql output (no Postgres)."""
    import lancet_eval.context_export as context_export_mod

    sent: list[str] = []
    snapshot = _snapshot()

    def fake_run_psql(settings: EvalSettings, sql: str, **kwargs: object) -> str:
        sent.append(sql)
        line = json.dumps({"trace_id": "trace-q1-on", "snapshot": snapshot})
        return f"{line}\n\n"

    monkeypatch.setattr(context_export_mod, "run_psql", fake_run_psql)
    source = PostgresCheckpointSource(EvalSettings())

    rows = source.terminal_success(["trace-q1-on"])

    assert rows == [CheckpointRow(trace_id="trace-q1-on", snapshot=snapshot)]
    [sql] = sent
    assert "lancet_eval.workflow_checkpoints" in sql
    assert "node_name = 'terminal_success'" in sql
    assert "'trace-q1-on'" in sql


def test_the_postgres_source_refuses_a_trace_id_it_cannot_quote_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lancet_eval.context_export as context_export_mod

    monkeypatch.setattr(
        context_export_mod,
        "run_psql",
        lambda *a, **k: pytest.fail("psql must not run"),
    )

    with pytest.raises(ContextExportError, match="trace_id"):
        PostgresCheckpointSource(EvalSettings()).terminal_success(["x'); DROP"])


# --- score's refusal (seam S-A: an offline run directory) ---------------------------


def _v11_journal(tmp_path: Path, *records: RunRecord) -> Path:
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    journal.write_header(corpus="multihop_rag", partial=False, context_export=True)
    for record in records:
        journal.append(record)
    return path


def _export_rows(tmp_path: Path, *rows: dict[str, Any]) -> None:
    (tmp_path / CONTEXT_EXPORT_FILE).write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )


def test_a_new_journal_header_declares_that_its_run_needs_a_context_export(
    tmp_path: Path,
) -> None:
    header = read_journal_header(_v11_journal(tmp_path))

    assert header is not None and header["context_export"] is True


def test_score_refuses_a_v11_run_with_no_context_export(tmp_path: Path) -> None:
    _v11_journal(tmp_path, _record())

    with pytest.raises(ScoreError, match=rf"(?s){CONTEXT_EXPORT_FILE}.*q1/graph-on"):
        score_run(run_dir=tmp_path)


def test_a_v11_run_needs_an_export_row_for_every_success_record(
    tmp_path: Path,
) -> None:
    journal = _v11_journal(
        tmp_path,
        _record(),
        _record("q2", "graph-off", correlation_id="trace-q2-off"),
        _record("q3", "graph-on", correlation_id="trace-q3-on", outcome="error"),
    )
    _export_rows(tmp_path, _valid_row())

    with pytest.raises(ContextExportError, match=r"q2/graph-off") as exc_info:
        require_export_rows(journal)

    assert "q3" not in str(exc_info.value)


def test_a_v11_run_refuses_an_export_row_from_another_attempt(tmp_path: Path) -> None:
    journal = _v11_journal(tmp_path, _record(correlation_id="trace-retried"))
    _export_rows(tmp_path, _valid_row())

    with pytest.raises(ContextExportError, match=r"q1/graph-on.*trace-q1-on"):
        require_export_rows(journal)


def test_a_v11_run_with_a_complete_export_passes(tmp_path: Path) -> None:
    journal = _v11_journal(tmp_path, _record())
    _export_rows(tmp_path, _valid_row())

    require_export_rows(journal)


def test_a_run_whose_header_predates_the_context_export_needs_none(
    tmp_path: Path,
) -> None:
    require_export_rows(_journal(tmp_path, _record()))


# --- the end-of-drive export ---------------------------------------------------------


class _EchoSource:
    """A checkpoint source with a `terminal_success` checkpoint for each trace asked."""

    def terminal_success(self, trace_ids: Collection[str]) -> list[CheckpointRow]:
        return [
            CheckpointRow(trace_id=t, snapshot=_snapshot(trace_id=t)) for t in trace_ids
        ]


def _gateway(httpx_mock: HTTPXMock, *, correlation: bool = True) -> httpx.Client:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = (
            "event: final_answer\n"
            'data: {"answer": "Paris", "snapshot": {"index_generation": "gen1"}}\n\n'
            "event: workflow_completed\n"
            'data: {"success": true, "duration_ms": 100}\n\n'
        )
        headers = {"content-type": "text/event-stream"}
        if correlation:
            headers["X-Lancet-Correlation-ID"] = f"trace-{calls}"
        return httpx.Response(200, headers=headers, text=body)

    httpx_mock.add_callback(respond, is_reusable=True)
    return httpx.Client(base_url="http://testserver")


def test_drive_writes_the_context_export_at_the_end_of_the_drive(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    journal = tmp_path / "journal.jsonl"

    result = drive(
        corpus="graphrag_bench",
        journal_path=journal,
        stage_spend_cap=10.0,
        limit=1,
        client=_gateway(httpx_mock),
        checkpoint_source=_EchoSource(),
    )

    assert result.context_export_error is None
    rows = read_export(tmp_path / CONTEXT_EXPORT_FILE)
    assert sorted(r.correlation_id for r in rows) == ["trace-1", "trace-2"]
    header = read_journal_header(journal)
    assert header is not None and header["context_export"] is True
    require_export_rows(journal)


def test_a_failed_end_of_drive_export_keeps_the_records_and_reports_the_failure(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    journal = tmp_path / "journal.jsonl"

    result = drive(
        corpus="graphrag_bench",
        journal_path=journal,
        stage_spend_cap=10.0,
        limit=1,
        client=_gateway(httpx_mock),
        checkpoint_source=InMemoryCheckpointSource([]),
    )

    assert result == 2
    assert result.context_export_error is not None
    assert "no terminal_success checkpoint" in result.context_export_error
    assert not (tmp_path / CONTEXT_EXPORT_FILE).exists()
    with pytest.raises(ContextExportError):
        require_export_rows(journal)


def test_a_resumed_drive_with_nothing_left_rewrites_the_export(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    journal = tmp_path / "journal.jsonl"
    args: dict[str, Any] = {
        "corpus": "graphrag_bench",
        "journal_path": journal,
        "stage_spend_cap": 10.0,
        "limit": 1,
        "client": _gateway(httpx_mock),
    }
    drive(**args, checkpoint_source=InMemoryCheckpointSource([]))

    result = drive(**args, resume=True, checkpoint_source=_EchoSource())

    assert result == 0
    assert result.context_export_error is None
    assert len(read_export(tmp_path / CONTEXT_EXPORT_FILE)) == 2


# --- `lancet-eval export-context` ----------------------------------------------------


def test_export_context_command_rewrites_the_export_from_the_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lancet_eval.context_export as context_export_mod

    _v11_journal(tmp_path, _record())
    (tmp_path / CONTEXT_EXPORT_FILE).write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(
        context_export_mod, "PostgresCheckpointSource", lambda settings: _EchoSource()
    )

    result = CliRunner().invoke(app, ["export-context", "--run", str(tmp_path)])

    assert result.exit_code == 0, result.output
    [row] = read_export(tmp_path / CONTEXT_EXPORT_FILE)
    assert row.correlation_id == "trace-q1-on"


def test_export_context_command_exits_non_zero_naming_the_unjoinable_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lancet_eval.context_export as context_export_mod

    _v11_journal(tmp_path, _record("q7", "graph-off", correlation_id="trace-q7"))
    monkeypatch.setattr(
        context_export_mod,
        "PostgresCheckpointSource",
        lambda settings: InMemoryCheckpointSource([]),
    )

    result = CliRunner(env={"COLUMNS": "400"}).invoke(
        app, ["export-context", "--run", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "q7/graph-off" in result.output
    assert not (tmp_path / CONTEXT_EXPORT_FILE).exists()
