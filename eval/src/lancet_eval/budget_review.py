"""Pass-A budget derivation options and hazards (06.3.4.1-24, G2).

Skeleton: signatures only, returning empty shapes, so the RED tests fail on assertions.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

_NODES = (
    "ReformulateQuery",
    "RetrieveHybrid",
    "ExtractGraphContext",
    "AssemblePrompt",
    "GenerateAnswer",
)
_KEYS = (
    "reformulate_timeout_ms",
    "query_embedding_timeout_ms",
    "retrieve_timeout_ms",
    "graph_operation_timeout_ms",
    "graph_node_timeout_ms",
    "prompt_timeout_ms",
    "generation_node_timeout_ms",
)

INNER_SOURCE_OPTIONS: dict[str, tuple[int | None, int | None, bool, str]] = {
    "config_rs_0633": (645, 38595, True, ""),
    "toml_33e774b": (15000, 40000, True, ""),
    "measurement_ceiling_passA": (30000, 120000, True, ""),
    "substage_measured": (None, None, True, ""),
}


def substage_status(
    *, measured: int, events: int, timed: Sequence[str]
) -> tuple[bool, str]:
    return True, ""


def node_exceedances(records: Sequence[Any], budgets: dict[str, int]) -> dict[str, Any]:
    return {
        node: {"budget_key": "", "budget_ms": 0, "n": 0, "above": 0, "max_ms": None}
        for node in _NODES
    }


def derive_option(
    records: Sequence[Any], measurement: dict[str, Any], inner: tuple[int, int]
) -> dict[str, Any]:
    zero = dict.fromkeys(_KEYS, 0)
    return {
        "inner": {},
        "rule": dict(zero),
        "resolved": dict(zero),
        "nesting": {"has_violations": False, "groups": []},
        "ceiling_report": {},
        "census": {},
    }


def noise_summary(noise: dict[str, Any]) -> dict[str, Any]:
    return {
        "windows": 0,
        "fired_fraction": 1.0,
        "escalate": True,
        "nearest_slope_miss": {"offset": -1, "percent_of_threshold": 0.0},
        "nearest_window_miss": {"offset": -1, "percent_of_threshold": 0.0},
        "first_window": {"offset": -1},
        "last_window": {"offset": -1},
    }


def hazards_report(
    journal: Path,
    measurement_path: Path,
    regate_path: Path,
    *,
    noise_path: Path | None = None,
    loki_manifest_path: Path | None = None,
) -> dict[str, Any]:
    return {"options": {}, "n_measured": 0, "brief_mismatch": [], "noise": {}}


def main(argv: Sequence[str] | None = None) -> int:
    return 0
