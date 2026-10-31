"""Subprocess output is decoded as UTF-8, whatever the locale's code page (#84).

On the Windows GPU box `text=True` with no `encoding=` decodes with cp950, and a
UTF-8 typographic quote in psql output (`0xe2 0x80 0x9c`) breaks the read. Each
test forces subprocess's default text encoding to cp950, swaps the real command for
a child process that writes UTF-8 bytes, and checks the caller gets them back intact.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any

import pytest

from lancet_eval import config, gitcheck, oi02, seed
from lancet_eval.config import EvalSettings

# Bound at import: conftest replaces `identity.list_lancedb_document_ids` per test.
from lancet_eval.identity import list_lancedb_document_ids

TEXT = "“quoted” — 新聞"


@pytest.fixture
def cp950_child(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Return a setter: every `subprocess.run` then emits the given text as UTF-8.

    Patching `subprocess._text_encoding` (what `text=True` falls back to) also beats
    `PYTHONUTF8=1`, so the test fails without `encoding="utf-8"` on any machine.
    """
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp950")
    real_run = subprocess.run

    def install(out: str) -> None:
        script = (
            "import sys; sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))"
        )

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            kwargs.pop("input", None)
            child = [sys.executable, "-I", "-c", script, out.encode("utf-8").hex()]
            return real_run(child, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)

    return install


def test_run_psql_decodes_utf8_under_cp950(
    cp950_child: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seed.shutil, "which", lambda name: f"/usr/bin/{name}")
    cp950_child(f"doc-1|{TEXT}\n")
    settings = EvalSettings(
        dev_database_url="postgres://postgres:postgres@127.0.0.1:5432/lancet",
    )

    assert seed.run_psql(settings, "SELECT 1;") == f"doc-1|{TEXT}\n"


def test_list_lancedb_document_ids_decodes_utf8_under_cp950(
    cp950_child: Callable[[str], None],
) -> None:
    payload = {
        "documents": [TEXT],
        "nodes": [],
        "edges": [],
        "entity_edges": [],
        "staged_documents_v2_rows": 0,
    }
    cp950_child(json.dumps(payload, ensure_ascii=False))

    assert list_lancedb_document_ids("data/x")["documents"] == [TEXT]


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(config.get_commit_sha, id="config.get_commit_sha"),
        pytest.param(lambda: oi02._git("log"), id="oi02._git"),
        pytest.param(
            lambda: gitcheck._run(["log"], repo=None).stdout.strip(),
            id="gitcheck._run",
        ),
    ],
)
def test_git_reads_decode_utf8_under_cp950(
    cp950_child: Callable[[str], None], call: Callable[[], str]
) -> None:
    cp950_child(f"{TEXT}\n")

    assert call() == TEXT
