"""Placeholder for the RED step; replaced by the D-104 retro."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_report(
    journal_path: Path,
    gold_chunks_path: Path,
    populations_path: Path,
) -> str:
    """Placeholder."""
    return ""


def main(argv: list[str] | None = None) -> int:
    """Placeholder CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
