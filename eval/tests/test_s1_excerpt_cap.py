"""D-273: the S1 overlay's excerpt cap holds the longest S1 merged chunk; v1.0 stays at 512.

The engine cuts each retrieved and cited excerpt at `[engine.retrieval] excerpt_max_chars`
Unicode characters at query time and flags it `is_truncated`, and `fact_matches_excerpt`
reads a truncated excerpt as UNDECIDABLE. The cap shapes only those excerpts, never the
prompt (the reader sees the full evidence block text), so raising it for S1 changes the
measurement and not the arm.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "config"

# Longest `nodes.content` in the built S1 store (`data/lancedb-eval-s1`, 3,953 chunks),
# in Unicode characters, measured read-only on 2026-10-31 (D-273). p50 990, p99 1,339.
S1_LONGEST_CHUNK_CHARS = 1489


def _excerpt_max_chars(*overlays: str) -> int:
    """`engine.retrieval.excerpt_max_chars` of config.toml layered with `overlays`."""
    value = None
    for name in ("config.toml", *overlays):
        with (CONFIG / name).open("rb") as f:
            retrieval = tomllib.load(f).get("engine", {}).get("retrieval", {})
        value = retrieval.get("excerpt_max_chars", value)
    assert value is not None, "excerpt_max_chars must be set in config.toml"
    return value


def test_s1_overlay_excerpt_cap_holds_the_longest_s1_chunk() -> None:
    cap = _excerpt_max_chars("config.eval-s1.toml")
    assert cap >= S1_LONGEST_CHUNK_CHARS * 5 // 4, (
        f"S1 excerpt_max_chars {cap} must hold the longest S1 chunk "
        f"({S1_LONGEST_CHUNK_CHARS} chars) with a 25% margin"
    )


def test_v1_arm_keeps_the_512_character_excerpt() -> None:
    assert _excerpt_max_chars() == 512
    assert _excerpt_max_chars("config.eval.toml") == 512
