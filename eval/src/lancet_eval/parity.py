"""Prompt parity: re-pack a run's Lancet rows with the generate-only bin (D-247).

External arms reach the reader through `generate_from_context`, the engine bin that
reruns the engine's own prompt assembly over a context-export row. That route is fair
only if the bin builds the prompt the live engine built. `check_prompt_parity`
re-packs every Lancet row of a run's `context_export.jsonl` (a row that carries
`assembled_prompt`) with the bin's `pack` mode and requires the user message of the
emitted request body to equal the row's `assembled_prompt` byte for byte.

Each row is packed under the levers its journal record echoes (`snapshot.levers`),
since the levers select prompt sentences. The check fails closed: a row with no
success record, a record with no lever echo, a row the bin cannot pack, or a single
differing byte names its question and arm, and the whole check fails.

The bin packs under today's engine configuration (`config/config.toml` and `LANCET_*`
overrides). A budget, `graph_weight` or lever-sentence change since the run therefore
fails parity too, reported as a differing prompt.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lancet_eval.config import repo_root
from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    ContextExportRow,
    read_export,
)
from lancet_eval.journal import load_records
from lancet_eval.pairing import deduplicate_by_arm

#: Packs rows under one lever set; returns one decoded `pack` output line per row,
#: in order.
Packer = Callable[[Sequence[ContextExportRow], Sequence[str]], list[dict[str, Any]]]

#: Builds the bin through cargo, as `identity.py` runs `inspect_lancedb`; the first call
#: compiles it, which is why the timeout is long.
BIN_COMMAND = (
    "cargo",
    "run",
    "--manifest-path",
    "engine/Cargo.toml",
    "--release",
    "--quiet",
    "--bin",
    "generate_from_context",
    "--",
)
_BIN_TIMEOUT_S = 1800

#: How many failing rows a refusal lists before it says how many more.
_MAX_LISTED = 10


class PromptParityError(Exception):
    """The bin's prompt differs from a checkpointed one, or parity cannot be checked."""


@dataclass(frozen=True)
class ParityResult:
    """How many Lancet rows matched and how many external rows were not checked."""

    checked: int
    external: int


def write_rows(rows: Sequence[ContextExportRow], path: Path) -> None:
    """Writes `rows` as context-export JSON lines, the bin's input format."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n")


def run_bin(
    mode: str, rows: Sequence[ContextExportRow], levers: Sequence[str]
) -> list[dict[str, Any]]:
    """Runs `generate_from_context <mode>` over `rows`; returns its output lines.

    Raises `PromptParityError` when the bin exits non-zero, times out or writes a line
    that is not JSON.
    """
    with tempfile.TemporaryDirectory(prefix="lancet-parity-") as tmp:
        input_path = Path(tmp) / "rows.jsonl"
        write_rows(rows, input_path)
        cmd = [
            *BIN_COMMAND,
            mode,
            "--input",
            str(input_path),
            "--levers",
            ",".join(levers),
        ]
        try:
            res = subprocess.run(
                cmd,
                cwd=repo_root(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_BIN_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PromptParityError(
                f"generate_from_context {mode} failed: {exc}"
            ) from exc
    if res.returncode != 0:
        raise PromptParityError(
            f"generate_from_context {mode} exited {res.returncode}: "
            f"{(res.stderr or '').strip()[-2000:]}"
        )
    try:
        return [json.loads(line) for line in res.stdout.splitlines() if line.strip()]
    except ValueError as exc:
        raise PromptParityError(
            f"generate_from_context {mode} wrote a line that is not JSON: {exc}"
        ) from exc


def cargo_packer(
    rows: Sequence[ContextExportRow], levers: Sequence[str]
) -> list[dict[str, Any]]:
    """The real packer: the bin's `pack` mode."""
    return run_bin("pack", rows, levers)


def user_message(body: str) -> str:
    """The content of the one `user` message of a chat-completions request body."""
    messages = json.loads(body)["messages"]
    users = [m["content"] for m in messages if m.get("role") == "user"]
    if len(users) != 1:
        raise ValueError(f"expected one user message, found {len(users)}")
    return users[0]


def first_difference(a: str, b: str) -> int:
    """The index of the first character where `a` and `b` differ."""
    for index, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return index
    return min(len(a), len(b))


def _row_failure(row: ContextExportRow, line: dict[str, Any]) -> str | None:
    unit = f"{row.question_id}/{row.arm}"
    if (line.get("question_id"), line.get("arm")) != (row.question_id, row.arm):
        return (
            f"{unit}: the bin answered for "
            f"{line.get('question_id')}/{line.get('arm')} instead"
        )
    if line.get("outcome") != "success":
        return f"{unit}: pack failed ({line.get('error_type')}): {line.get('error')}"
    try:
        packed = user_message(line["body"])
    except (KeyError, TypeError, ValueError) as exc:
        return f"{unit}: unreadable pack body: {exc}"
    expected = row.assembled_prompt or ""
    if packed != expected:
        at = first_difference(packed, expected)
        return (
            f"{unit}: the packed user message differs from assembled_prompt at "
            f"character {at} (packed {len(packed)} chars, "
            f"checkpointed {len(expected)}; an engine config change since the run "
            "also shows here)"
        )
    return None


def check_prompt_parity(
    run_dir: Path | str, packer: Packer = cargo_packer
) -> ParityResult:
    """Re-packs each Lancet row of `run_dir`'s export and checks its prompt.

    Raises `PromptParityError` naming every failing row (up to `_MAX_LISTED`).
    """
    run = Path(run_dir)
    rows = read_export(run / CONTEXT_EXPORT_FILE)
    lancet_rows = [row for row in rows if row.assembled_prompt is not None]
    records, _ = deduplicate_by_arm(load_records(run / "journal.jsonl"))
    successes = {
        (r.question_id, r.graph_arm): r for r in records if r.outcome == "success"
    }
    failures: list[str] = []
    groups: dict[tuple[str, ...], list[ContextExportRow]] = {}
    for row in lancet_rows:
        unit = f"{row.question_id}/{row.arm}"
        record = successes.get((row.question_id, row.arm))
        if record is None:
            failures.append(f"{unit}: no success record in the journal")
        elif record.snapshot is None:
            failures.append(
                f"{unit}: the record has no snapshot to read its levers from"
            )
        else:
            groups.setdefault(tuple(record.snapshot.levers), []).append(row)
    for levers, group in groups.items():
        lines = packer(group, list(levers))
        if len(lines) != len(group):
            raise PromptParityError(
                f"the bin wrote {len(lines)} line(s) for {len(group)} row(s) "
                f"under levers {list(levers)}"
            )
        for row, line in zip(group, lines, strict=True):
            failure = _row_failure(row, line)
            if failure is not None:
                failures.append(failure)
    if failures:
        more = len(failures) - _MAX_LISTED
        listed = "; ".join(failures[:_MAX_LISTED])
        raise PromptParityError(
            f"prompt parity failed on {len(failures)} of {len(lancet_rows)} Lancet "
            f"row(s): {listed}" + (f" (and {more} more)" if more > 0 else "")
        )
    return ParityResult(checked=len(lancet_rows), external=len(rows) - len(lancet_rows))
