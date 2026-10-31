"""Prompt parity with the generate-only bin (D-247).

The offline tests drive `check_prompt_parity` with a fake packer that answers as the
bin's `pack` mode does. The integration tests build and run the real bin; they are
skipped unless `LANCET_EVAL_INTEGRATION=1`, and they call only the loopback
`provider_stub`, never OpenRouter.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lancet_eval import parity
from lancet_eval.cli import app
from lancet_eval.client import RetrievalSnapshot
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, ContextExportRow
from lancet_eval.journal import Journal, RunRecord
from lancet_eval.parity import PromptParityError, check_prompt_parity
from lancet_eval.provider_stub import run_server

PROMPT = (
    "System Policy: ...\n"
    '<EVIDENCE id="[1]" suspicious="false">\nAcme</EVIDENCE>\n'
)

integration = pytest.mark.skipif(
    os.environ.get("LANCET_EVAL_INTEGRATION") != "1",
    reason="integration test (seam S-C): set LANCET_EVAL_INTEGRATION=1 to build "
    "and run the generate_from_context bin against provider_stub",
)


def _row(
    question_id: str = "q1", arm: str = "graph-on", *, prompt: str | None = PROMPT
) -> dict[str, Any]:
    return {
        "corpus": "multihop_rag",
        "question_id": question_id,
        "arm": arm,
        "question": "Who bought Globex?",
        "evidence": [
            {
                "rank": 1,
                "chunk_id": "doc-a:0",
                "document_id": "doc-a",
                "text": "Acme announced that it will buy Globex.",
                "title": "acme-globex.md",
                "section_path": "Root",
                "content_type": "text/markdown",
                "score": 0.9,
                "suspicious": False,
                "document_metadata": {
                    "source": "The Verge",
                    "doc_title": "Acme to buy Globex",
                    "published_date": "2023-10-02",
                },
            }
        ],
        "graph_facts": [],
        "assembled_prompt": prompt,
        "correlation_id": None if prompt is None else f"trace-{question_id}-{arm}",
    }


def _record(
    question_id: str, arm: str, levers: list[str] | None = None
) -> RunRecord:
    return RunRecord(
        corpus="multihop_rag",
        question_id=question_id,
        graph_arm=arm,
        outcome="success",
        answer="Answer: Acme",
        correlation_id=f"trace-{question_id}-{arm}",
        snapshot=None if levers is None else RetrievalSnapshot(levers=levers),
    )


def _run(tmp_path: Path, rows: list[dict[str, Any]], records: list[RunRecord]) -> Path:
    journal = Journal(tmp_path / "journal.jsonl")
    journal.write_header(corpus="multihop_rag", partial=False)
    for record in records:
        journal.append(record)
    with open(tmp_path / CONTEXT_EXPORT_FILE, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return tmp_path


class FakePacker:
    """Answers as `pack` does, with the row's own prompt as the user message."""

    def __init__(self, tamper: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[list[str], list[str]]] = []
        self.tamper = tamper or {}

    def __call__(
        self, rows: Sequence[ContextExportRow], levers: Sequence[str]
    ) -> list[dict[str, Any]]:
        self.calls.append(([r.question_id for r in rows], list(levers)))
        lines = []
        for row in rows:
            user = self.tamper.get(row.question_id, row.assembled_prompt)
            body = {
                "model": "m",
                "messages": [
                    {"role": "system", "content": "You are a precise RAG engine."},
                    {"role": "user", "content": user},
                ],
            }
            lines.append({
                "question_id": row.question_id,
                "arm": row.arm,
                "outcome": "success",
                "body": json.dumps(body),
            })
        return lines


def test_parity_passes_when_every_lancet_prompt_matches(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        [_row("q1"), _row("q2"), _row("q3", "llamaindex", prompt=None)],
        [_record("q1", "graph-on", ["rerank"]), _record("q2", "graph-on", ["rerank"])],
    )
    packer = FakePacker()

    result = check_prompt_parity(run, packer=packer)

    assert result == parity.ParityResult(checked=2, external=1)
    assert packer.calls == [(["q1", "q2"], ["rerank"])], "external rows stay unpacked"


def test_one_byte_difference_fails_closed_and_names_the_record(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        [_row("q1"), _row("q2")],
        [_record("q1", "graph-on", []), _record("q2", "graph-on", [])],
    )
    tampered = PROMPT.replace("Acme", "Acmf")

    with pytest.raises(PromptParityError) as exc:
        check_prompt_parity(run, packer=FakePacker(tamper={"q2": tampered}))

    message = str(exc.value)
    assert "q2/graph-on" in message
    assert "q1/graph-on" not in message
    assert f"character {PROMPT.index('Acme') + 3}" in message


def test_rows_are_packed_under_the_levers_their_record_echoes(tmp_path: Path) -> None:
    run = _run(
        tmp_path,
        [_row("q1"), _row("q2"), _row("q3")],
        [
            _record("q1", "graph-on", ["rerank", "evidence_metadata"]),
            _record("q2", "graph-on", []),
            _record("q3", "graph-on", ["rerank", "evidence_metadata"]),
        ],
    )
    packer = FakePacker()

    check_prompt_parity(run, packer=packer)

    assert packer.calls == [
        (["q1", "q3"], ["rerank", "evidence_metadata"]),
        (["q2"], []),
    ]


def test_a_row_without_a_record_or_lever_echo_fails_closed(tmp_path: Path) -> None:
    run = _run(tmp_path, [_row("q1"), _row("q2")], [_record("q2", "graph-on")])

    with pytest.raises(PromptParityError) as exc:
        check_prompt_parity(run, packer=FakePacker())

    message = str(exc.value)
    assert "q1/graph-on: no success record" in message
    assert "q2/graph-on: the record has no snapshot" in message


def test_a_row_the_bin_cannot_pack_fails_closed(tmp_path: Path) -> None:
    run = _run(tmp_path, [_row("q1")], [_record("q1", "graph-on", [])])

    def refusing(rows: Sequence[ContextExportRow], levers: Sequence[str]) -> list[dict]:
        return [
            {
                "question_id": "q1",
                "arm": "graph-on",
                "outcome": "error",
                "error_type": "NODE_ERROR_KIND_PROMPT_ASSEMBLY_FAILED",
                "error": "No complete evidence block fit",
            }
        ]

    with pytest.raises(PromptParityError, match=r"q1/graph-on: pack failed"):
        check_prompt_parity(run, packer=refusing)


def test_cli_reports_parity_and_exits_non_zero_on_a_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _run(tmp_path, [_row("q1")], [_record("q1", "graph-on", [])])
    runner = CliRunner()

    monkeypatch.setattr(parity, "cargo_packer", FakePacker())
    ok = runner.invoke(app, ["check-prompt-parity", "--run", str(run)])
    assert ok.exit_code == 0, ok.output
    assert "1 Lancet row" in ok.output

    monkeypatch.setattr(parity, "cargo_packer", FakePacker(tamper={"q1": "different"}))
    bad = runner.invoke(app, ["check-prompt-parity", "--run", str(run)])
    assert bad.exit_code == 1
    assert "q1/graph-on" in bad.output


# --- Integration (seam S-C): the real bin, the loopback provider stub ---------------


@pytest.fixture
def stub_reader(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Points the bin's reader at a loopback `provider_stub`; never at OpenRouter."""
    model = "stub/reader-model"
    server = run_server(
        host="127.0.0.1",
        port=0,
        model_id=model,
        vectors_path=None,
        embed_delay_ms=0,
        chat_delay_ms=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("OPENROUTER_API_KEY", "stub-key")
    monkeypatch.setenv("LANCET_OPENROUTER__GENERATION_MODEL", model)
    monkeypatch.setenv("LANCET_OPENROUTER__CHAT_ENDPOINT", f"{base}/chat/completions")
    monkeypatch.setenv("LANCET_OPENROUTER__MODEL_METADATA_ENDPOINT", f"{base}/models")
    yield base
    server.shutdown()
    server.server_close()


@integration
def test_generate_against_provider_stub_ends_with_an_answer_line(
    stub_reader: str,
) -> None:
    row = ContextExportRow.model_validate(_row("q1"))

    [line] = parity.run_bin("generate", [row], ["rerank", "evidence_metadata"])

    assert line["outcome"] == "success", line
    assert line["answer"].splitlines()[-1].startswith("Answer:")
    assert line["citations"] == ["[1]"]
    assert line["usage"]["prompt_tokens"] == 2000


@integration
def test_pack_of_a_real_row_renders_the_engine_prompt() -> None:
    row = ContextExportRow.model_validate(_row("q1"))

    [line] = parity.cargo_packer([row], ["evidence_metadata"])

    assert line["outcome"] == "success", line
    user = parity.user_message(line["body"])
    assert "<SOURCE>The Verge</SOURCE>" in user
    assert "Who bought Globex?" in user


@integration
def test_pack_shows_the_chunk_index_of_both_chunk_id_shapes() -> None:
    engine = _row("q1")
    external = _row("q2", arm="llamaindex", prompt=None)
    external["evidence"][0]["chunk_id"] = "doc-a#3"

    lines = parity.cargo_packer(
        [ContextExportRow.model_validate(r) for r in (engine, external)],
        ["evidence_metadata"],
    )

    shown = [parity.user_message(line["body"]) for line in lines]
    assert "document_id=doc-a, chunk_index=0," in shown[0]
    assert "document_id=doc-a, chunk_index=3," in shown[1]
