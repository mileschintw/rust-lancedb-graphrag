"""OI-02 full-pipeline diagnosis tooling (06.3.4.1-07) -- RED stub.

Placeholder signatures only, so pytest collection succeeds and the target tests fail on
their own assertions (not an ImportError/collection crash) per the #3770 RED-evidence rule.
Real implementation lands in the matching GREEN commit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class TimelineRow:  # pragma: no cover - stub
    pass


def load_timeline_records(journal_path: str | Path) -> list[tuple[Any, bool]]:
    raise NotImplementedError


def journal_timeline(journal_path: str | Path, **kwargs: Any) -> list[Any]:
    return []


def hidden_gaps(rows: list[Any], **kwargs: Any) -> list[dict[str, Any]]:
    return []


def slice_table(rows: list[Any], **kwargs: Any) -> list[dict[str, Any]]:
    return []


def idle_recovery(rows: list[Any], **kwargs: Any) -> list[dict[str, Any]]:
    return []


def run_forensics(**kwargs: Any) -> dict[str, Any]:
    return {}


def main(argv: list[str] | None = None) -> int:
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
