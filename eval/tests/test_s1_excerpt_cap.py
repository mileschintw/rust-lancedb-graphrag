"""D-273: the S1 overlay's excerpt cap holds the longest S1 merged chunk.

v1.0 stays at 512. The engine cuts each retrieved and cited excerpt at
`[engine.retrieval] excerpt_max_chars` Unicode characters at query time and flags it
`is_truncated`, and `fact_matches_excerpt` reads a truncated excerpt as UNDECIDABLE.
The cap shapes only those excerpts, never the prompt (the reader sees the full evidence
block text), so raising it for S1 changes the measurement and not the arm.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from lancet_eval.config import S1_STORE, V1_STORE, EvalStore, repo_root

# Longest `nodes.content` in the built S1 store (`data/lancedb-eval-s1`, 3,953 chunks),
# in Unicode characters, measured read-only on 2026-10-31 (D-273). p50 990, p99 1,339.
# A rebuilt S1 store with longer chunks needs a new measurement here.
S1_LONGEST_CHUNK_CHARS = 1489


def _retrieval_cap(path: Path) -> int | None:
    with path.open("rb") as f:
        retrieval = tomllib.load(f).get("engine", {}).get("retrieval", {})
    return retrieval.get("excerpt_max_chars")


def _excerpt_max_chars(store: EvalStore | None) -> int:
    """The engine's layering of the cap: config.toml, then `store`'s overlay."""
    base = _retrieval_cap(repo_root() / "config" / "config.toml")
    assert base is not None, "excerpt_max_chars must be set in config.toml"
    if store is None:
        return base
    overlay = _retrieval_cap(store.overlay_path)
    return base if overlay is None else overlay


def test_s1_overlay_excerpt_cap_holds_the_longest_s1_chunk() -> None:
    cap = _excerpt_max_chars(S1_STORE)
    assert cap >= S1_LONGEST_CHUNK_CHARS * 5 // 4, (
        f"S1 excerpt_max_chars {cap} must hold the longest S1 chunk "
        f"({S1_LONGEST_CHUNK_CHARS} chars) with a 25% margin"
    )


def test_v1_arm_keeps_the_512_character_excerpt() -> None:
    assert _excerpt_max_chars(None) == 512
    assert _excerpt_max_chars(V1_STORE) == 512
