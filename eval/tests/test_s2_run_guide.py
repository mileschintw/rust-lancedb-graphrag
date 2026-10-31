"""The S2 run guide agrees with the code (#110).

Its Python snippets compile, every `lancet-eval` command it gives names options the
CLI has, and its step-1 snippet, run on copies of the files it reads and edits,
appends the EXPERIMENT-S2.md draft to `thresholds.py` with the winner filled in, fills
the corpus, and refuses to run twice.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import textwrap
from dataclasses import asdict
from pathlib import Path

import pytest
import typer
from test_s2_preregistration import TOKEN, build_draft

from lancet_eval.cli import app
from lancet_eval.config import repo_root
from lancet_eval.corpus import load_corpus

GUIDE = repo_root() / "experiments" / "v1.1" / "RUN-S2.md"
THRESHOLDS = Path("eval") / "src" / "lancet_eval" / "thresholds.py"
EXPERIMENT = Path("experiments") / "v1.1" / "EXPERIMENT-S2.md"
#: Options the guide uses that lane 109 (#109) adds; drop each once it is on main.
PENDING = {("replay-init", "--pilot")}
S2_TOML = Path("eval") / "corpora" / "multihop_rag_s2_dev.toml"


def _snippets() -> list[str]:
    text = GUIDE.read_text(encoding="utf-8")
    return [
        textwrap.dedent(s)
        for s in re.findall(r'python -c "(.*?)"\n', text, flags=re.DOTALL)
    ]


def _commands() -> list[list[str]]:
    text = GUIDE.read_text(encoding="utf-8")
    lines = re.findall(r"^\s*uv run --project eval lancet-eval (.+)$", text, re.M)
    return [shlex.split(line) for line in lines]


def test_python_snippets_compile() -> None:
    snippets = _snippets()
    assert len(snippets) >= 3
    for snippet in snippets:
        compile(snippet, "<guide>", "exec")


def test_every_command_names_options_the_cli_has() -> None:
    root = typer.main.get_command(app)
    commands = _commands()
    assert {tuple(c[:2]) for c in commands} >= {
        ("replay-init", "--source-run"),
        ("batch", "submit"),
        ("batch", "fetch"),
        ("score", "--run"),
        ("compare-levers", "--run"),
    }
    for argv in commands:
        command = root
        while argv and argv[0] in getattr(command, "commands", {}):
            command = command.commands[argv.pop(0)]  # type: ignore[attr-defined]
        known = {opt for p in command.params for opt in p.opts}
        known |= {opt for name, opt in PENDING if name == command.name}
        used = {a for a in argv if a.startswith("--")}
        assert used <= known, f"{command.name}: unknown {sorted(used - known)}"


def test_the_fill_snippet_appends_the_draft_and_fills_the_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (fill,) = [s for s in _snippets() if "S1_WINNER_UNSET" in s]
    winner = "merged/hybrid+graph+rerank+metadata"
    for rel in (THRESHOLDS, S2_TOML, EXPERIMENT):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes((repo_root() / rel).read_bytes())
    run = [sys.executable, "-I", "-c", fill.replace("<WINNER>", winner)]
    subprocess.run(run, cwd=tmp_path, check=True)

    before = (repo_root() / THRESHOLDS).read_text(encoding="utf-8")
    after = (tmp_path / THRESHOLDS).read_text(encoding="utf-8")
    assert after.startswith(before.rstrip())
    namespace: dict[str, object] = {}
    exec(compile(after, str(THRESHOLDS), "exec"), namespace)  # noqa: S102
    # A fresh exec defines its own classes, so compare the values field by field.
    assert asdict(namespace[TOKEN]) == asdict(build_draft(winner))  # type: ignore[call-overload]

    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: tmp_path)
    corpus = load_corpus("multihop_rag_s2_dev")
    assert corpus.arms == [winner, f"{winner}@haiku-5.5", f"{winner}@sonnet-5.5"]

    again = subprocess.run(run, cwd=tmp_path, check=False, capture_output=True)
    assert again.returncode != 0, "a second fill must refuse"
