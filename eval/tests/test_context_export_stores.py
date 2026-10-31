"""The context export of a two-store S1 journal (#65, D-249, D-251).

An S1 journal holds `small/` arms driven on the v1.0 store and `merged/` arms driven
on the S1 store. Each record's checkpoint lives in its own store's schema, so the
export reads each record from the store its arm label declares.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from lancet_eval.cli import app
from lancet_eval.config import EvalSettings, pg_schema_of
from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    CheckpointRow,
    CheckpointSource,
    ContextExportError,
    InMemoryCheckpointSource,
    export_context,
    read_export,
    store_checkpoint_sources,
)
from lancet_eval.journal import Journal, RunRecord, load_records
from lancet_eval.run import drive, write_context_export

SMALL = "small/hybrid+rerank+metadata"
MERGED = "merged/hybrid+rerank+metadata"


def _snapshot(trace_id: str) -> dict[str, object]:
    return {
        "trace_id": trace_id,
        "original_query": f"question of {trace_id}",
        "evidence_blocks": [],
        "graph_facts": [],
        "assembled_prompt": f"prompt of {trace_id}",
    }


def _record(question_id: str, arm: str, correlation_id: str) -> RunRecord:
    return RunRecord(
        corpus="multihop_rag_s1_dev",
        question_id=question_id,
        graph_arm=arm,
        outcome="success",
        answer="Answer: x",
        correlation_id=correlation_id,
    )


def _journal(tmp_path: Path, *records: RunRecord) -> Path:
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    journal.write_header(corpus="multihop_rag_s1_dev", partial=False)
    for record in records:
        journal.append(record)
    return path


def _source(*trace_ids: str) -> InMemoryCheckpointSource:
    return InMemoryCheckpointSource([
        CheckpointRow(trace_id=t, snapshot=_snapshot(t)) for t in trace_ids
    ])


def _two_store_journal(tmp_path: Path) -> Path:
    return _journal(
        tmp_path,
        _record("q1", SMALL, "trace-small-1"),
        _record("q1", MERGED, "trace-merged-1"),
        _record("q2", SMALL, "trace-small-2"),
        _record("q2", MERGED, "trace-merged-2"),
    )


def _two_store_sources() -> dict[str, CheckpointSource]:
    return {
        "eval": _source("trace-small-1", "trace-small-2"),
        "eval-s1": _source("trace-merged-1", "trace-merged-2"),
    }


def test_a_two_store_journal_reads_each_record_from_its_own_store(
    tmp_path: Path,
) -> None:
    journal = _two_store_journal(tmp_path)

    rows = read_export(export_context(journal, _two_store_sources()))

    assert [(r.question_id, r.arm, r.correlation_id) for r in rows] == [
        ("q1", SMALL, "trace-small-1"),
        ("q1", MERGED, "trace-merged-1"),
        ("q2", SMALL, "trace-small-2"),
        ("q2", MERGED, "trace-merged-2"),
    ]


def test_a_record_is_not_read_from_the_other_store(tmp_path: Path) -> None:
    journal = _two_store_journal(tmp_path)
    swapped = {
        "eval": _source("trace-merged-1", "trace-merged-2"),
        "eval-s1": _source("trace-small-1", "trace-small-2"),
    }

    with pytest.raises(ContextExportError) as exc:
        export_context(journal, swapped)

    assert f"q1/{SMALL}" in str(exc.value)
    assert f"q1/{MERGED}" in str(exc.value)
    assert not (tmp_path / CONTEXT_EXPORT_FILE).exists()


def test_an_unprefixed_arm_reads_from_the_v1_store(tmp_path: Path) -> None:
    journal = _journal(tmp_path, _record("q1", "hybrid", "trace-1"))

    [row] = read_export(
        export_context(journal, {"eval": _source("trace-1"), "eval-s1": _source()})
    )

    assert row.correlation_id == "trace-1"


def test_an_arm_whose_store_has_no_source_fails_closed(tmp_path: Path) -> None:
    journal = _two_store_journal(tmp_path)

    with pytest.raises(ContextExportError) as exc:
        export_context(journal, {"eval": _source("trace-small-1", "trace-small-2")})

    message = str(exc.value)
    assert f"q1/{MERGED}" in message and f"q2/{MERGED}" in message
    assert "'eval-s1'" in message
    assert f"q1/{SMALL}" not in message
    assert not (tmp_path / CONTEXT_EXPORT_FILE).exists()


@pytest.mark.parametrize(
    "records",
    [
        pytest.param(
            [_record("q1", "hybrid", "t-1"), _record("q2", "dense-only", "t-2")],
            id="unprefixed",
        ),
        pytest.param(
            [_record("q1", MERGED, "t-1"), _record("q2", MERGED, "t-2")],
            id="merged",
        ),
    ],
)
def test_a_one_store_journal_exports_byte_identically_to_one_source(
    tmp_path: Path, records: list[RunRecord]
) -> None:
    one_dir, map_dir = tmp_path / "one", tmp_path / "map"
    one_dir.mkdir()
    map_dir.mkdir()
    single = export_context(_journal(one_dir, *records), _source("t-1", "t-2"))
    mapped = export_context(
        _journal(map_dir, *records),
        {"eval": _source("t-1", "t-2"), "eval-s1": _source("t-1", "t-2")},
    )

    assert mapped.read_bytes() == single.read_bytes()


# --- the per-store Postgres sources -------------------------------------------------


def test_store_checkpoint_sources_read_each_store_from_its_own_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lancet_eval.context_export as context_export_mod

    monkeypatch.setattr(
        context_export_mod,
        "PostgresCheckpointSource",
        lambda settings: settings,
    )
    settings = EvalSettings(
        database_url="postgres://u@db:5432/lancet?search_path=lancet_eval_s1",
        lancedb_path="./data/lancedb-eval-s1",
    )

    sources = store_checkpoint_sources(settings)

    assert {
        name: pg_schema_of(s.database_url)  # type: ignore[attr-defined]
        for name, s in sources.items()
    } == {"eval": "lancet_eval", "eval-s1": "lancet_eval_s1"}
    assert sources["eval-s1"] is settings


def test_store_checkpoint_sources_keep_the_drive_settings_for_their_own_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lancet_eval.context_export as context_export_mod

    monkeypatch.setattr(
        context_export_mod, "PostgresCheckpointSource", lambda settings: settings
    )
    settings = EvalSettings(
        database_url="postgres://u@db:5432/lancet?search_path=custom_v1"
    )

    sources = store_checkpoint_sources(settings)

    assert sources["eval"] is settings
    assert pg_schema_of(sources["eval-s1"].database_url) == "lancet_eval_s1"  # type: ignore[attr-defined]


# --- the end-of-drive export after the second store's drive ------------------------


class _StoreEchoSource:
    """Echoes a checkpoint for each trace asked, and remembers what it was asked."""

    def __init__(self) -> None:
        self.asked: set[str] = set()

    def terminal_success(self, trace_ids: Collection[str]) -> list[CheckpointRow]:
        self.asked |= set(trace_ids)
        return [CheckpointRow(trace_id=t, snapshot=_snapshot(t)) for t in trace_ids]


def _correlated_gateway(httpx_mock: HTTPXMock) -> httpx.Client:
    """A gateway answering every arm well, each response under its own trace ID."""
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        answer = {"answer": "Paris", "snapshot": {"index_generation": "gen1"}}
        completed = {
            "success": True,
            "duration_ms": 100,
            "metadata": {"graph_node_count": 3, "graph_seed_count": 1},
        }
        text = (
            f"event: final_answer\ndata: {json.dumps(answer)}\n\n"
            f"event: workflow_completed\ndata: {json.dumps(completed)}\n\n"
        )
        headers = {
            "content-type": "text/event-stream",
            "X-Lancet-Correlation-ID": f"trace-{calls}",
        }
        return httpx.Response(200, headers=headers, text=text)

    httpx_mock.add_callback(respond, is_reusable=True)
    return httpx.Client(base_url="http://testserver")


def test_the_second_stores_drive_ends_with_a_complete_export(
    tmp_path: Path, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LANCET_ENV", raising=False)
    monkeypatch.setattr("lancet_eval.run.require_index_identity", lambda *a, **k: None)
    journal = tmp_path / "journal.jsonl"
    client = _correlated_gateway(httpx_mock)
    small, merged = _StoreEchoSource(), _StoreEchoSource()
    sources = {"eval": small, "eval-s1": merged}
    common = {
        "corpus": "multihop_rag_s1_dev",
        "journal_path": journal,
        "stage_spend_cap": 10.0,
        "limit": 2,
        "client": client,
        "checkpoint_source": sources,
    }

    first = drive(**common, settings=EvalSettings(), arms=[SMALL])
    second = drive(
        **common,
        settings=EvalSettings(
            lancedb_path="./data/lancedb-eval-s1",
            database_url="postgres://localhost/lancet?search_path=lancet_eval_s1",
        ),
        arms=[MERGED],
    )

    assert first.context_export_error is None
    assert second.context_export_error is None
    records = [r for r in load_records(journal) if r.outcome == "success"]
    assert {r.graph_arm for r in records} == {SMALL, MERGED}
    rows = read_export(tmp_path / CONTEXT_EXPORT_FILE)
    assert sorted((r.question_id, r.arm) for r in rows) == sorted(
        (r.question_id, r.graph_arm) for r in records
    )
    assert small.asked == {r.correlation_id for r in records if r.graph_arm == SMALL}
    assert merged.asked == {r.correlation_id for r in records if r.graph_arm == MERGED}


# --- `lancet-eval export-context` ----------------------------------------------------


def test_export_context_command_rebuilds_a_two_store_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lancet_eval.context_export as context_export_mod

    journal = _two_store_journal(tmp_path)
    expected = write_context_export(journal, _two_store_sources()).read_bytes()
    (tmp_path / CONTEXT_EXPORT_FILE).write_text("stale\n", encoding="utf-8")
    by_schema = {
        "lancet_eval": _source("trace-small-1", "trace-small-2"),
        "lancet_eval_s1": _source("trace-merged-1", "trace-merged-2"),
    }
    monkeypatch.setattr(
        context_export_mod,
        "PostgresCheckpointSource",
        lambda settings: by_schema[pg_schema_of(settings.database_url)],
    )

    result = CliRunner().invoke(app, ["export-context", "--run", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / CONTEXT_EXPORT_FILE).read_bytes() == expected
    assert len(json.loads(f"[{','.join(expected.decode().splitlines())}]")) == 4
