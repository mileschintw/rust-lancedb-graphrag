"""Drive-1 unpark gate readings: SC-1, SC-2, the D-69 companion tripwire, and SC-3.

Every gate reading here is a COMPUTED PASS/MISS against literals committed to
`thresholds.py` before the drive that tests them (D-73), never a judgement call
made at read time. The D-84 checkpoint that halts before graph work on an SC-3
miss presents this module's output verbatim.

No function here adds a flag, keyword, or bypass to `score_run`/`report` --
`evaluate_sc1` only reads their outputs (D-87a).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lancet_eval import thresholds
from lancet_eval.corpus import load_sample_questions
from lancet_eval.diagnostic import build_rows, classify_record
from lancet_eval.flatness import flatness_verdict, records_from_run_journal
from lancet_eval.journal import completeness_comparison, load_records
from lancet_eval.stats import wilson_ci
from lancet_eval.thresholds import (
    CITATION_REJECTION_NULL_BASELINE,
    CITATION_REJECTION_TRIPWIRE,
)

_D69_REJECTION_CLASSES = frozenset(
    {
        "citation_basis_mixed",
        "citation_basis_retrieval",
        "model_only_unsupported",
        "citation_marker_mismatch",
    }
)
_TIMEOUT_CLASS = "timeout"
_BINARY_GOLD_ANSWERS = frozenset({"yes", "no"})


@dataclass(frozen=True)
class GateReading:
    """A computed PASS/MISS reading for a single unpark gate."""

    gate: str
    status: str  # "PASS" | "MISS"
    reason: str
    value: float | None = None
    ci: tuple[float, float] | None = None
    n: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


def _reached_generate_answer(record: Any) -> bool:
    return any(nt.node_name == "GenerateAnswer" for nt in record.node_timings) or any(
        nf.node_name == "GenerateAnswer" for nf in record.node_failures
    )


def evaluate_sc1(run_dir: Path | str) -> GateReading:
    """SC-1 / D-87a: header `partial` equals `not completeness_comparison(...)` AND
    (when non-partial) `report.json` exists via the unmodified fail-closed path."""
    raise NotImplementedError("RED stub not yet implemented")


def evaluate_sc2(
    journal_path: Path | str,
    engine_pid_before: int,
    engine_pid_after: int,
) -> GateReading:
    """SC-2: PASS only when the error-mode clause (timeout not the plurality/tied
    error class) AND the RetrieveHybrid flatness clause both pass. An engine
    restart (PID mismatch) between drive start and end is an immediate MISS."""
    raise NotImplementedError("RED stub not yet implemented")


def citation_rejection_rate(
    journal_path: Path | str, questions: list[Any]
) -> GateReading:
    """D-69 companion tripwire (SC-2 companion, AI-SPEC #4)."""
    raise NotImplementedError("RED stub not yet implemented")


def evaluate_sc3(rows: list[Any], populations_path: Path | str) -> GateReading:
    """SC-3 (AI-SPEC #5): answer_usable rate over G against the committed
    VECTOR_BASELINE_USABLE_FLOOR (D-73); never supplies a default."""
    raise NotImplementedError("RED stub not yet implemented")


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m lancet_eval.unpark_gates --stage drive1 --run <dir> ...`."""
    raise NotImplementedError("RED stub not yet implemented")


if __name__ == "__main__":
    raise SystemExit(main())
