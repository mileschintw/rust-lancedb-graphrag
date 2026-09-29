"""D-89 decay materiality for 06.3.4.1 (06.3.4.1-21).

06.3.3's committed decay rule (`decay.analyze_decay`) has no size floor on its slope
prong, so a +0.033 ms/query slope on a ~160 ms node fired it in pass A. D-89 amends D-64
for every decay and flatness reading in this phase: decay is present only when it is
material relative to the node's own speed, on both prongs. This module is a pure
function over `decay.analyze_decay`'s output; `decay.py` and 06.3.3's
`COMMITTED_THRESHOLDS` are untouched.

Censoring is unchanged (RESEARCH Pitfall 6): a censored or too-small set reads
`unavailable` on both D-89 prongs, never flat. Because the materiality threshold is
derived from the early-window p95, an unavailable window prong also makes the slope
prong unavailable.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lancet_eval import decay
from lancet_eval.thresholds import (
    COMMITTED_DECAY_THRESHOLDS_06341,
    MaterialDecayThresholds,
)


@dataclass(frozen=True)
class MaterialDecayVerdict:
    """The D-89 reading of one record set, with each prong's availability and inputs."""

    decay_present: bool
    slope_prong_available: bool
    slope_prong_fired: bool
    window_prong_available: bool
    window_prong_fired: bool
    slope_ms_per_query: float
    slope_p_value: float
    projected_growth_ms: float
    early_p95_ms: float
    late_p95_ms: float
    window_delta_ms: float
    materiality_threshold_ms: float | None
    censored_count: int
    unusable_dropped_count: int
    base_verdict: decay.DecayVerdict
    rule_provenance: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable projection (the base verdict is summarized, not nested)."""
        return {
            "decay_present": self.decay_present,
            "slope_prong_available": self.slope_prong_available,
            "slope_prong_fired": self.slope_prong_fired,
            "window_prong_available": self.window_prong_available,
            "window_prong_fired": self.window_prong_fired,
            "slope_ms_per_query": self.slope_ms_per_query,
            "slope_p_value": self.slope_p_value,
            "projected_growth_ms": self.projected_growth_ms,
            "early_p95_ms": self.early_p95_ms,
            "late_p95_ms": self.late_p95_ms,
            "window_delta_ms": self.window_delta_ms,
            "materiality_threshold_ms": self.materiality_threshold_ms,
            "censored_count": self.censored_count,
            "unusable_dropped_count": self.unusable_dropped_count,
            "reason": self.reason,
            "base_trend_reason": self.base_verdict.trend_result.reason,
            "base_window_reason": self.base_verdict.window_result.reason,
        }


def evaluate_material_decay(
    verdict: decay.DecayVerdict,
    rule: MaterialDecayThresholds = COMMITTED_DECAY_THRESHOLDS_06341,
) -> MaterialDecayVerdict:
    """Apply D-89 to an already-computed `decay.DecayVerdict` (pure, no I/O).

    Reads only `trend_result.is_available/.is_significant/.slope/.p_value` and
    `window_result.is_available/.early_percentile_ms/.late_percentile_ms/.delta_ms`.
    """
    trend = verdict.trend_result
    window = verdict.window_result
    censored_count = max(trend.censored_count, window.censored_count)

    if not window.is_available:
        # The threshold needs the early-window p95, so neither prong can be read. An
        # unavailable set is never flat.
        return MaterialDecayVerdict(
            decay_present=False,
            slope_prong_available=False,
            slope_prong_fired=False,
            window_prong_available=False,
            window_prong_fired=False,
            slope_ms_per_query=trend.slope,
            slope_p_value=trend.p_value,
            projected_growth_ms=0.0,
            early_p95_ms=window.early_percentile_ms,
            late_p95_ms=window.late_percentile_ms,
            window_delta_ms=window.delta_ms,
            materiality_threshold_ms=None,
            censored_count=censored_count,
            unusable_dropped_count=verdict.unusable_dropped_count,
            base_verdict=verdict,
            rule_provenance=rule.provenance,
            reason="unavailable",
        )

    threshold = rule.materiality_threshold_ms(window.early_percentile_ms)
    projected = trend.slope * rule.projection_horizon_records
    window_fired = window.delta_ms >= threshold
    slope_available = trend.is_available
    slope_fired = slope_available and trend.is_significant and projected >= threshold
    decay_present = slope_fired or window_fired

    return MaterialDecayVerdict(
        decay_present=decay_present,
        slope_prong_available=slope_available,
        slope_prong_fired=slope_fired,
        window_prong_available=True,
        window_prong_fired=window_fired,
        slope_ms_per_query=trend.slope,
        slope_p_value=trend.p_value,
        projected_growth_ms=projected,
        early_p95_ms=window.early_percentile_ms,
        late_p95_ms=window.late_percentile_ms,
        window_delta_ms=window.delta_ms,
        materiality_threshold_ms=threshold,
        censored_count=censored_count,
        unusable_dropped_count=verdict.unusable_dropped_count,
        base_verdict=verdict,
        rule_provenance=rule.provenance,
        reason=(
            "decay_present"
            if decay_present
            else "flat"
            if slope_available
            else "unavailable"
        ),
    )


def analyze_material_decay(
    records: Sequence[Any],
    rule: MaterialDecayThresholds = COMMITTED_DECAY_THRESHOLDS_06341,
    node_name: str = "RetrieveHybrid",
) -> MaterialDecayVerdict:
    """`decay.analyze_decay` under the rule's base inputs, then the D-89 test."""
    rule.validate()
    base = decay.analyze_decay(
        records, rule.base, restart_ordinal=None, node_name=node_name
    )
    return evaluate_material_decay(base, rule)


# 06.3.4.1 D-89 noise check: escalation rule committed before the check runs
# (06.3.4.1-21).
NOISE_WINDOW_RECORDS = 200
NOISE_ESCALATION_FRACTION = 0.05


NOISE_ESCALATION_RULE = (
    "escalate when the first-200 window fires, or the last-200 window fires, or at "
    f"least {NOISE_ESCALATION_FRACTION:.0%} of the contiguous {NOISE_WINDOW_RECORDS}-"
    "record windows fire (either prong)"
)

#: Records fed to the 06.3.4 drive's historical reading (D-89 fixtures).
HISTORICAL_FIRST_N = 350


def _has_retrieve_timing(record: Any, node_name: str) -> bool:
    timings = getattr(record, "node_timings", []) or []
    return any(
        getattr(t, "node_name", "") == node_name
        and getattr(t, "duration_ms", None) is not None
        for t in timings
    )


def _is_censored(record: Any, node_name: str) -> bool:
    failures = getattr(record, "node_failures", []) or []
    return any(
        getattr(f, "node_name", "") == node_name
        and getattr(f, "error_kind", None) == 1
        for f in failures
    )


def _renumbered(records: Sequence[Any]) -> list[Any]:
    """Fresh copies with ordinals 1..n in the given order (`FlatnessRecord`-shaped)."""
    return [
        dataclasses.replace(record, ordinal=index)
        for index, record in enumerate(records, start=1)
    ]


def first_uncensored(
    records: Sequence[Any], n: int, node_name: str = "RetrieveHybrid"
) -> list[Any]:
    """The first `n` records with a `node_name` timing and no censoring failure.

    Records are taken in ordinal order; censored records and records without a timing
    for the node are skipped, not stopped at. The result is fresh copies renumbered
    1..n, so the series is gap-free for `decay.analyze_decay`. Fewer than `n` are
    returned when the series is shorter.
    """
    ordered = sorted(records, key=lambda record: int(record.ordinal))
    kept = [
        record
        for record in ordered
        if _has_retrieve_timing(record, node_name)
        and not _is_censored(record, node_name)
    ]
    return _renumbered(kept[:n])


def noise_escalation(
    windows: int, fired_either: int, first_fired: bool, last_fired: bool
) -> bool:
    """The committed escalation rule for the noise check (D-89)."""
    if windows <= 0:
        return False
    return (
        first_fired
        or last_fired
        or fired_either / windows >= NOISE_ESCALATION_FRACTION
    )


def contiguous_window_noise(
    records: Sequence[Any],
    window: int = NOISE_WINDOW_RECORDS,
    rule: MaterialDecayThresholds = COMMITTED_DECAY_THRESHOLDS_06341,
) -> dict[str, Any]:
    """D-89 on every contiguous `window`-record slice of `records`.

    Each slice is renumbered 1..window and read by `analyze_material_decay`. The
    result carries one row per offset and the counts that feed `noise_escalation`. A
    window that reads unavailable is counted in `unavailable` and makes the check
    inconclusive (`conclusive` False); it is never counted as quiet.
    """
    ordered = sorted(records, key=lambda record: int(record.ordinal))
    total = len(ordered)
    if window <= 0 or total < window:
        raise ValueError(
            f"noise check needs at least one full window: {total} records, "
            f"window {window}"
        )

    rows: list[dict[str, Any]] = []
    for offset in range(total - window + 1):
        verdict = analyze_material_decay(
            _renumbered(ordered[offset : offset + window]), rule
        )
        rows.append(
            {
                "offset": offset,
                "decay_present": verdict.decay_present,
                "slope_prong_available": verdict.slope_prong_available,
                "slope_prong_fired": verdict.slope_prong_fired,
                "window_prong_available": verdict.window_prong_available,
                "window_prong_fired": verdict.window_prong_fired,
                "slope_ms_per_query": verdict.slope_ms_per_query,
                "slope_p_value": verdict.slope_p_value,
                "projected_growth_ms": verdict.projected_growth_ms,
                "early_p95_ms": verdict.early_p95_ms,
                "late_p95_ms": verdict.late_p95_ms,
                "window_delta_ms": verdict.window_delta_ms,
                "materiality_threshold_ms": verdict.materiality_threshold_ms,
            }
        )

    windows = len(rows)
    fired_either = sum(1 for row in rows if row["decay_present"])
    first_fired = bool(rows[0]["decay_present"])
    last_fired = bool(rows[-1]["decay_present"])
    unavailable = sum(
        1
        for row in rows
        if not (row["slope_prong_available"] and row["window_prong_available"])
    )
    return {
        "rule": "D-89",
        "rule_thresholds": rule.to_dict(),
        "records": total,
        "window": window,
        "windows": windows,
        "rows": rows,
        "fired_either": fired_either,
        "fired_slope": sum(1 for row in rows if row["slope_prong_fired"]),
        "fired_window": sum(1 for row in rows if row["window_prong_fired"]),
        "unavailable": unavailable,
        "conclusive": unavailable == 0,
        "fired_fraction": fired_either / windows,
        "first_window_fired": first_fired,
        "last_window_fired": last_fired,
        "escalation_fraction": NOISE_ESCALATION_FRACTION,
        "escalation_rule": NOISE_ESCALATION_RULE,
        "escalate": noise_escalation(windows, fired_either, first_fired, last_fired),
    }


# --- readings shared by the report writers --------------------------------------------


def _flatness_summary(result: Any) -> dict[str, Any]:
    """The `FlatnessResult` fields a verdict comparison needs."""
    return {
        "passed": result.passed,
        "reason": result.reason,
        "trend_available": result.trend_available,
        "window_available": result.window_available,
        "decay_present": result.decay_present,
        "slope_ms_per_query": result.slope_ms_per_query,
        "window_delta_ms": result.window_delta_ms,
        "projected_growth_ms": result.projected_growth_ms,
        "materiality_threshold_ms": result.materiality_threshold_ms,
        "censored_count": result.censored_count,
        "n": result.n,
    }


def _load_old_verdict(arm_dir: Path) -> dict[str, Any] | None:
    """The `flatness_verdict_full` an arm's committed `summary.json` recorded."""
    summary_path = arm_dir / "summary.json"
    if not summary_path.is_file():
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    old = summary.get("flatness_verdict_full") if isinstance(summary, dict) else None
    return old if isinstance(old, dict) else None


def _first_n_reading(
    journal_path: Path, first_n: int, rule: MaterialDecayThresholds
) -> dict[str, Any]:
    from lancet_eval.flatness import records_from_run_journal

    kept = first_uncensored(records_from_run_journal(journal_path), first_n)
    verdict = analyze_material_decay(kept, rule)
    reading = verdict.to_dict()
    reading.update(
        {
            "journal": str(journal_path),
            "requested_n": first_n,
            "n": len(kept),
            "rule": "D-89",
        }
    )
    return reading


def replay_arm_flips(
    replay_root: Path | str,
    contrast_journal: Path | str | None = None,
    contrast_first_n: int = HISTORICAL_FIRST_N,
    rule: MaterialDecayThresholds = COMMITTED_DECAY_THRESHOLDS_06341,
) -> dict[str, Any]:
    """Re-read each replay arm under D-89 and compare with its committed summary.

    Only top-level `<arm>/journal.jsonl` files are read (not nested `warmup/`). Each
    arm's old reading is the `flatness_verdict_full` in its committed `summary.json`.
    A flip is any change in `passed` or `decay_present`; no direction is asserted.
    Nothing is written.
    """
    from lancet_eval.flatness import flatness_verdict, records_from_run_journal

    root = Path(replay_root)
    arms: list[dict[str, Any]] = []
    for arm_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        journal = arm_dir / "journal.jsonl"
        if not journal.is_file():
            continue
        new = _flatness_summary(flatness_verdict(records_from_run_journal(journal)))
        old = _load_old_verdict(arm_dir)
        if old is None:
            flipped: bool | None = None
            flip_fields: list[str] = []
        else:
            flip_fields = [
                name
                for name in ("passed", "decay_present")
                if old.get(name) != new[name]
            ]
            flipped = bool(flip_fields)
        arms.append(
            {
                "arm": arm_dir.name,
                "journal": str(journal),
                "n": new["n"],
                "old": old,
                "new": new,
                "flipped": flipped,
                "flip_fields": flip_fields,
            }
        )

    report: dict[str, Any] = {
        "rule": "D-89",
        "rule_thresholds": rule.to_dict(),
        "replay_root": str(root),
        "arms": arms,
        "flipped_arms": [row["arm"] for row in arms if row["flipped"]],
        "direction_asserted": False,
    }
    if contrast_journal is not None:
        report["contrast_first_n"] = _first_n_reading(
            Path(contrast_journal), contrast_first_n, rule
        )
    return report


# --- CLI ------------------------------------------------------------------------------


class _RefusedOutputError(ValueError):
    """Raised when a report would be written where evidence lives."""


def _check_out_path(
    out: Path, protected_roots: Sequence[Path], protected_files: Sequence[Path]
) -> None:
    """Refuse an `--out` under a protected root or equal to an input file."""
    from lancet_eval.config import repo_root

    resolved = out.resolve()
    roots = [(repo_root() / "eval" / "runs").resolve()]
    roots += [root.resolve() for root in protected_roots]
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            raise _RefusedOutputError(f"--out {out} is under protected root {root}")
    for path in protected_files:
        if resolved == path.resolve():
            raise _RefusedOutputError(f"--out {out} is an input file")


def _write_json(out: Path, payload: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _regate_payload(journal: Path) -> dict[str, Any]:
    from lancet_eval.flatness import (
        flatness_verdict,
        records_from_run_journal,
        slice_medians,
    )

    records = records_from_run_journal(journal)
    result = flatness_verdict(records)
    material = analyze_material_decay(records)
    available = material.slope_prong_available and material.window_prong_available
    payload = material.to_dict()
    payload.update(
        {
            "rule": "D-89",
            "thresholds": COMMITTED_DECAY_THRESHOLDS_06341.to_dict(),
            "rule_provenance": COMMITTED_DECAY_THRESHOLDS_06341.provenance,
            "journal": str(journal),
            "node": "RetrieveHybrid",
            "n": result.n,
            "passed": result.passed,
            "flatness_reason": result.reason,
            "slice_medians_ms": slice_medians(records) if records else [],
            "may_derive_budgets": available and not material.decay_present,
        }
    )
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lancet_eval.decay_materiality",
        description="D-89 decay readings for 06.3.4.1 (read-only over run evidence).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    regate = subparsers.add_parser(
        "regate", help="D-89 verdict for one journal (pass A re-gate)."
    )
    regate.add_argument("--journal", required=True)
    regate.add_argument("--out", required=True)

    noise = subparsers.add_parser(
        "noise", help="D-89 on every contiguous window of one journal."
    )
    noise.add_argument("--journal", required=True)
    noise.add_argument("--window", type=int, default=NOISE_WINDOW_RECORDS)
    noise.add_argument("--out", required=True)

    arms = subparsers.add_parser(
        "arms", help="Re-read replay arms under D-89 and report verdict flips."
    )
    arms.add_argument("--replay-root", required=True)
    arms.add_argument("--contrast")
    arms.add_argument("--contrast-first-n", type=int, default=HISTORICAL_FIRST_N)
    arms.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Every subcommand writes only its `--out` file."""
    args = _build_parser().parse_args(argv)
    out = Path(args.out)
    try:
        if args.command == "arms":
            root = Path(args.replay_root)
            _check_out_path(out, [root], [])
            payload = replay_arm_flips(
                root,
                Path(args.contrast) if args.contrast else None,
                args.contrast_first_n,
            )
        else:
            journal = Path(args.journal)
            _check_out_path(out, [], [journal])
            if args.command == "regate":
                payload = _regate_payload(journal)
            else:
                from lancet_eval.flatness import records_from_run_journal

                payload = contiguous_window_noise(
                    records_from_run_journal(journal), window=args.window
                )
                payload["journal"] = str(journal)
    except _RefusedOutputError as error:
        print(f"refusing to write: {error}", file=sys.stderr)
        return 2
    _write_json(out, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
