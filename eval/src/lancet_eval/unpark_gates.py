"""Unpark gate readings: SC-1, SC-2, the D-69 companion tripwire and SC-3 (drive 1),
then SC-4, SC-5 and graph-off invariance (drive 2).

Every gate reading here is a COMPUTED PASS/MISS against literals committed to
`thresholds.py` before the drive that tests them (D-73), never a judgement call
made at read time. The D-84 checkpoint that halts before graph work on an SC-3
miss presents this module's output verbatim.

No function here adds a flag, keyword, or bypass to `score_run`/`report` --
`evaluate_sc1` only reads their outputs (D-87a).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, NamedTuple

from lancet_eval import thresholds
from lancet_eval.corpus import load_corpus_config, load_sample_questions
from lancet_eval.diagnostic import build_rows, classify_record
from lancet_eval.dimensions import make_graph_presence_rate
from lancet_eval.flatness import flatness_verdict, records_from_run_journal
from lancet_eval.journal import (
    completeness_comparison,
    first_attempt_view,
    load_records,
)
from lancet_eval.metrics import answer_usable as compute_answer_usable
from lancet_eval.metrics import final_answer_em, recall_at_k
from lancet_eval.pairing import compute_paired_delta, deduplicate_by_arm, form_pairs
from lancet_eval.stats import wilson_ci
from lancet_eval.thresholds import (
    CITATION_REJECTION_NULL_BASELINE,
    CITATION_REJECTION_TRIPWIRE,
    FINAL_ANSWER_MISSING_REVIEW_RATE,
    SC2_TIMEOUT_DOMINANCE_RULE,
    SC5_VISIBILITY_RULE,
)
from lancet_eval.usability import has_scorable_payload, is_usable

_D69_REJECTION_CLASSES = frozenset(
    {
        "citation_basis_mixed",
        "citation_basis_retrieval",
        "model_only_unsupported",
        "citation_marker_mismatch",
    }
)
_TIMEOUT_CLASS = "timeout"
#: The stage label that adds SC-4, SC-5 and graph-off invariance; any other label keeps
#: the drive-1 readings unchanged (D-95).
DRIVE2_STAGE = "drive2"
#: The gate drives written before the gate-stage marker existed (06.3.4.1-33), read
#: without it. Each maps the header's own `(corpus, created_at)` to the stage label it
#: was driven as, its retry evidence (the `retries=0` banner in that run's
#: `drive-console.txt`; D-67, the operator typed `--retries 0` on each), and the content
#: it was recorded with: the record count and `legacy_records_digest` of its records.
#:
#: The registry is closed. These three journals have no marker to read and their retry
#: provenance is on record; every other journal without a marker, the `--retries 2`
#: 06.3.4-era ones included, MISSes (G-06.3.4.1-2). Entries are never added: no
#: wildcard, no data-driven loading, and the mapping is read-only. The header alone does
#: not earn the exemption (WR-01): a journal that copies a registered header line but
#: holds other records, or more or fewer of them, is not that drive. The digest hashes
#: the parsed record values, not file bytes, so a CRLF checkout cannot change it (a file
#: hash would).
class _LegacyDrive(NamedTuple):
    label: str
    evidence: str
    n_records: int
    records_sha256: str


_LEGACY_UNMARKED_GATE_DRIVES: Mapping[tuple[str, float], _LegacyDrive] = (
    MappingProxyType(
        {
            ("multihop_rag_diag", 1790752043.476702): _LegacyDrive(
                "drive1",
                "eval/runs/2026-09-30-drive1-multihop_rag_diag/drive-console.txt "
                "records retries=0",
                200,
                "84c8adf801e89a057c5b6ea3c1f5fd473b48f25c95d5e4fb5364484a2e3e44cd",
            ),
            ("multihop_rag_diag", 1790892253.3635316): _LegacyDrive(
                "drive1b",
                "eval/runs/2026-10-01-drive1b-multihop_rag_diag/drive-console.txt "
                "records retries=0",
                200,
                "d27780299a6a64b6c66b3b9b0b909be814037d1ee9b3c2235366f688c1125bad",
            ),
            ("multihop_rag_diag", 1791278008.6136012): _LegacyDrive(
                "drive2",
                "eval/runs/2026-10-06-drive2-multihop_rag_diag/drive-console.txt "
                "records retries=0",
                200,
                "a5f9bb5a75a989530caa9e5666f15685cd39b12adb717310600513dbc19171b8",
            ),
        }
    )
)
_BINARY_GOLD_ANSWERS = frozenset({"yes", "no"})
#: D-73: the only dominance reading this phase committed to thresholds.py. A
#: literal that doesn't match this is a signal the committed policy changed
#: without unpark_gates.py being updated to interpret it -- refuse, don't guess.
_KNOWN_SC2_DOMINANCE_RULES = frozenset({"plurality_tie_is_dominant"})


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


def _coverage_clause(
    n: int, expected: int | None, label: str
) -> tuple[str | None, dict[str, Any]]:
    """The coverage floor (CR-02, WR-04; D-73, D-82) shared by SC-3, SC-4 and SC-5.

    `n` is the population a gate scored and `expected` the sample-scoped population it
    should have scored (|sample & G| or |sample & V|, computed once by `main`, never
    the corpus-wide G or V and never a journal-relative denominator). Returns the MISS
    reason (None when the clause passes or is skipped) and the `detail` fields. At or
    above `UNPARK_GATE_COVERAGE_FLOOR` passes. `expected` None skips the clause and
    says so: only a direct evaluator call omits it, `main` always passes an integer.
    """
    floor = thresholds.UNPARK_GATE_COVERAGE_FLOOR
    detail: dict[str, Any] = {
        "coverage_n": n,
        "coverage_expected": expected,
        "coverage": None,
        "coverage_floor": float(floor),
    }
    if expected is None:
        detail["coverage_note"] = "coverage not assessed"
        return None, detail
    if expected <= 0:
        return "expected population is empty", detail
    coverage = n / expected
    detail["coverage"] = coverage
    if coverage < floor:
        return (
            f"coverage {n}/{expected} = {coverage:.4f} < floor {floor:.2f} ({label})",
            detail,
        )
    return None, detail


def _read_journal_header(journal_path: Path) -> dict[str, Any] | None:
    """The journal's header line, or None when the first line is not one."""
    with open(journal_path, encoding="utf-8") as f:
        first_line = f.readline().strip()
    if not first_line:
        return None
    try:
        parsed = json.loads(first_line)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and parsed.get("type") == "header":
        return parsed
    return None


def evaluate_sc1(
    run_dir: Path | str,
    *,
    is_complete: bool | None = None,
    missing_count: int | None = None,
) -> GateReading:
    """SC-1 / D-87a: the journal is COMPLETE, header `partial` equals
    `not completeness_comparison(...)` AND (when non-partial) `report.json` exists via
    the unmodified fail-closed path.

    Reads only the journal header, `completeness_comparison`, and the presence of
    `report.json` on disk -- never calls `score_run`/`render_json` and adds no flag
    to either (a plan prohibition).

    `main` measures completeness once and passes it in as `is_complete` and
    `missing_count`; called directly without them, this measures it itself. A journal
    honestly labelled `partial: true` with no `report.json` is still MISS: honest
    metadata about an incomplete run does not make the run a complete scored one
    (CR-02; D-87a "a halted drive is never reported as complete").
    """
    dir_path = Path(run_dir)
    journal_path = dir_path / "journal.jsonl"
    if not journal_path.is_file():
        journal_path = dir_path / "journal.json"
    if not journal_path.is_file():
        return GateReading(
            gate="SC-1", status="MISS", reason="no journal file", n=0, detail={}
        )

    header = _read_journal_header(journal_path)
    if header is None:
        return GateReading(
            gate="SC-1", status="MISS", reason="no header", n=0, detail={}
        )

    header_partial = bool(header.get("partial", True))
    records = load_records(journal_path)
    corpus_name = header.get("corpus") or (records[0].corpus if records else None)
    if not corpus_name:
        return GateReading(
            gate="SC-1",
            status="MISS",
            reason="no corpus in header or records",
            n=len(records),
            detail={},
        )

    if is_complete is None:
        is_complete, missing = completeness_comparison(journal_path, corpus_name)
        missing_count = len(missing)
    missing_count = missing_count or 0
    expected_partial = not is_complete
    header_matches = header_partial == expected_partial

    report_json_path = dir_path / "report.json"
    report_exists = report_json_path.is_file()

    reasons: list[str] = []
    if not is_complete:
        reasons.append(f"journal incomplete: {missing_count} work unit(s) missing")
    if not header_matches:
        reasons.append(
            f"header partial={header_partial} != not completeness_comparison()="
            f"{expected_partial} (missing {missing_count} work unit(s))"
        )
    if header_partial and report_exists:
        reasons.append(
            "report.json exists for a partial run (fail-closed path violation)"
        )
    if not header_partial and not report_exists:
        reasons.append("report.json missing for a non-partial run")

    status = "PASS" if not reasons else "MISS"
    reason = (
        "; ".join(reasons)
        if reasons
        else (
            "header partial matches completeness_comparison() and report.json "
            "state is consistent"
        )
    )

    detail: dict[str, Any] = {
        "header_partial": header_partial,
        "expected_partial": expected_partial,
        "journal_complete": is_complete,
        "missing_units": float(missing_count),
        "report_json_exists": report_exists,
    }
    return GateReading(
        gate="SC-1", status=status, reason=reason, n=len(records), detail=detail
    )


def evaluate_sc2(
    journal_path: Path | str,
    engine_pid_before: int,
    engine_pid_after: int,
) -> GateReading:
    """SC-2: PASS only when the error-mode clause (timeout not the plurality/tied
    error class) AND the RetrieveHybrid flatness clause both pass. An engine
    restart (PID mismatch) between drive start and end is an immediate MISS.

    Uses `diagnostic.classify_record` for the error-mode tally and
    `flatness.flatness_verdict(flatness.records_from_run_journal(...))` for the
    flatness clause (D-64). Prints (in `detail`) the both-arm-error question count
    and the error class counts, per AI-SPEC #2.
    """
    if engine_pid_before != engine_pid_after:
        return GateReading(
            gate="SC-2",
            status="MISS",
            reason="engine restarted",
            n=0,
            detail={
                "engine_pid_before": float(engine_pid_before),
                "engine_pid_after": float(engine_pid_after),
            },
        )

    records = load_records(journal_path)
    if not records:
        return GateReading(gate="SC-2", status="MISS", reason="n=0", n=0, detail={})

    # D-73: the dominance reading is itself a committed literal, not a hardcoded
    # assumption -- refuse rather than silently reinterpret an unrecognised value.
    if SC2_TIMEOUT_DOMINANCE_RULE not in _KNOWN_SC2_DOMINANCE_RULES:
        return GateReading(
            gate="SC-2",
            status="MISS",
            reason=(
                f"unknown dominance rule {SC2_TIMEOUT_DOMINANCE_RULE!r} "
                f"(known: {sorted(_KNOWN_SC2_DOMINANCE_RULES)})"
            ),
            n=len(records),
            detail={"sc2_timeout_dominance_rule": SC2_TIMEOUT_DOMINANCE_RULE},
        )

    # D-67: each work unit counts its first attempt once, exactly what a `--retries 0`
    # drive would have journaled, so a retry cannot clear a timeout from the tally. The
    # flatness clause below keeps the final outcome (a gate reading never reaches it on
    # a retried journal: `_journal_preconditions` MISSes every reading first).
    class_counts: dict[str, int] = {}
    error_arms_by_qid: dict[str, set[str]] = {}
    retried_records = 0
    for rec in records:
        if rec.prior_attempts:
            retried_records += 1
        cls = classify_record(first_attempt_view(rec))
        if cls is None:
            continue
        class_counts[cls] = class_counts.get(cls, 0) + 1
        error_arms_by_qid.setdefault(rec.question_id, set()).add(rec.graph_arm)

    both_arm_error_pairs = sorted(
        (qid, tuple(sorted(arms)))
        for qid, arms in error_arms_by_qid.items()
        if len(arms) >= 2
    )

    if class_counts:
        max_count = max(class_counts.values())
        dominant_classes = sorted(c for c, v in class_counts.items() if v == max_count)
    else:
        dominant_classes = []
    # SC2_TIMEOUT_DOMINANCE_RULE == "plurality_tie_is_dominant" (the only
    # committed reading, checked above): a tie at the plurality count still
    # counts timeout as dominant.
    timeout_dominant = _TIMEOUT_CLASS in dominant_classes
    error_mode_pass = not timeout_dominant

    flatness = flatness_verdict(records_from_run_journal(journal_path))
    flatness_pass = flatness.passed

    reasons: list[str] = []
    if not error_mode_pass:
        reasons.append(
            f"timeout is a dominant error class (tied or plurality): {class_counts}"
        )
    if not flatness_pass:
        reasons.append(f"flatness {flatness.reason}")

    status = "PASS" if (error_mode_pass and flatness_pass) else "MISS"
    reason = (
        "; ".join(reasons)
        if reasons
        else "error mode and RetrieveHybrid flatness both pass"
    )

    detail: dict[str, Any] = {
        "class_counts": {k: float(v) for k, v in class_counts.items()},
        "dominant_classes": dominant_classes,
        "timeout_dominant": timeout_dominant,
        "sc2_timeout_dominance_rule": SC2_TIMEOUT_DOMINANCE_RULE,
        "both_arm_error_question_count": float(len(both_arm_error_pairs)),
        "both_arm_error_class_pairs": both_arm_error_pairs,
        "retried_records": float(retried_records),
        "flatness_reason": flatness.reason,
        "flatness_trend_available": flatness.trend_available,
        "flatness_window_available": flatness.window_available,
        "flatness_decay_present": flatness.decay_present,
        "flatness_slope_ms_per_query": flatness.slope_ms_per_query,
        "flatness_window_delta_ms": flatness.window_delta_ms,
    }

    return GateReading(
        gate="SC-2", status=status, reason=reason, n=len(records), detail=detail
    )


def citation_rejection_rate(
    journal_path: Path | str, questions: list[Any]
) -> GateReading:
    """D-69 companion tripwire (SC-2 companion, AI-SPEC #4).

    PASS iff `citation_marker_mismatch` count is 0 AND the total rejection rate is
    <= `CITATION_REJECTION_TRIPWIRE` AND the null-query rejection rate does not
    rise above `CITATION_REJECTION_NULL_BASELINE`. Denominator is records that
    reached GenerateAnswer (a node timing or a node failure named GenerateAnswer);
    numerator is GenerateAnswer failures classified into one of the D-69 classes
    or `citation_marker_mismatch`. Null and non-null are reported separately.
    """
    gold_map = {q.question_id: q for q in questions}
    records = load_records(journal_path)

    null_total = 0
    null_rejections = 0
    nonnull_total = 0
    nonnull_rejections = 0
    marker_mismatch_count = 0
    class_counts: dict[str, int] = {}
    retried_records = 0

    for rec in records:
        if rec.prior_attempts:
            retried_records += 1
        # D-67, D-69: the first attempt of each work unit, so a rejection a retry
        # answered still counts and a first attempt that never reached GenerateAnswer
        # stays outside the denominator. Null-ness comes from the gold question.
        view = first_attempt_view(rec)
        if not _reached_generate_answer(view):
            continue
        gold = gold_map.get(rec.question_id)
        is_null = bool(gold.is_null) if gold is not None else False
        cls = classify_record(view)
        is_rejection = cls in _D69_REJECTION_CLASSES
        if cls:
            class_counts[cls] = class_counts.get(cls, 0) + 1
        if cls == "citation_marker_mismatch":
            marker_mismatch_count += 1
        if is_null:
            null_total += 1
            if is_rejection:
                null_rejections += 1
        else:
            nonnull_total += 1
            if is_rejection:
                nonnull_rejections += 1

    total = null_total + nonnull_total
    if total == 0:
        return GateReading(
            gate="citation_rejection_rate",
            status="MISS",
            reason="n=0",
            n=0,
            detail={"class_counts": {}, "retried_records": float(retried_records)},
        )

    total_rejections = null_rejections + nonnull_rejections
    total_rate = total_rejections / total
    null_rate = (null_rejections / null_total) if null_total else 0.0
    nonnull_rate = (nonnull_rejections / nonnull_total) if nonnull_total else 0.0
    p, ci_lo, ci_hi = wilson_ci(total_rejections, total)

    baseline_num, baseline_den = CITATION_REJECTION_NULL_BASELINE
    baseline_rate = baseline_num / baseline_den

    reasons: list[str] = []
    status = "PASS"
    if marker_mismatch_count > 0:
        status = "MISS"
        reasons.append(f"citation_marker_mismatch count={marker_mismatch_count}")
    if total_rate > CITATION_REJECTION_TRIPWIRE:
        status = "MISS"
        reasons.append(
            f"total rejection rate {total_rate:.4f} > tripwire "
            f"{CITATION_REJECTION_TRIPWIRE:.3f}"
        )
    if null_total > 0 and null_rate > baseline_rate:
        status = "MISS"
        reasons.append(
            f"null rejection rate {null_rate:.4f} > baseline {baseline_rate:.4f} "
            f"({baseline_num}/{baseline_den})"
        )

    reason = (
        "; ".join(reasons)
        if reasons
        else "citation_marker_mismatch=0, total and null rates within committed bounds"
    )

    detail: dict[str, Any] = {
        "class_counts": {k: float(v) for k, v in class_counts.items()},
        "marker_mismatch_count": float(marker_mismatch_count),
        "total": float(total),
        "total_rejections": float(total_rejections),
        "total_rate": float(total_rate),
        "null_total": float(null_total),
        "null_rejections": float(null_rejections),
        "null_rate": float(null_rate),
        "nonnull_total": float(nonnull_total),
        "nonnull_rejections": float(nonnull_rejections),
        "nonnull_rate": float(nonnull_rate),
        "retried_records": float(retried_records),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
    }

    return GateReading(
        gate="citation_rejection_rate",
        status=status,
        reason=reason,
        value=total_rate,
        ci=(ci_lo, ci_hi),
        n=total,
        detail=detail,
    )


def evaluate_sc3(
    rows: list[Any],
    populations_path: Path | str,
    *,
    corpus: str | None = None,
    expected_g: int | None = None,
) -> GateReading:
    """SC-3 (AI-SPEC #5): answer_usable rate over G against the committed
    VECTOR_BASELINE_USABLE_FLOOR (D-73); never supplies a default when the floor
    is absent -- returns MISS "floor not committed" instead. G is read from the
    `g_question_ids` list in the committed selection file (`populations_path`) --
    the real `diag_selection.json` written by 06.3.4.1-10 carries no `corpus` key
    (`method`/`seed`/`quotas`/`g_question_ids`/... only), so `corpus` is a
    keyword-only override the caller (typically `main`, from the journal header)
    supplies; the selection file's own `corpus` key is used only as a fallback for
    callers that provide one there instead. An empty population is MISS "n=0",
    never PASS. When a corpus is resolved, strata by `question_type` and
    binary-vs-entity gold (each with its constant-Yes baseline) are added to
    `detail["strata"]` on a best-effort basis.

    `expected_g` is |sample & G| (keyword-only, supplied by `main`): scored n below
    `UNPARK_GATE_COVERAGE_FLOOR` of it is MISS however high the usable rate. Omitted,
    the coverage clause is skipped and `detail` says `coverage not assessed`.
    """
    pop_path = Path(populations_path)
    if not pop_path.is_file():
        return GateReading(
            gate="SC-3",
            status="MISS",
            reason="n=0",
            n=0,
            detail={"error": f"populations file not found: {pop_path}"},
        )

    with open(pop_path, encoding="utf-8") as f:
        selection = json.load(f)
    g_ids = set(selection.get("g_question_ids") or [])
    corpus_name = corpus or selection.get("corpus")

    if not g_ids:
        return GateReading(gate="SC-3", status="MISS", reason="n=0", n=0, detail={})

    g_rows = [r for r in rows if r.question_id in g_ids]
    scored_rows = [r for r in g_rows if getattr(r, "e_answer_usable", None) is not None]

    floor = getattr(thresholds, "VECTOR_BASELINE_USABLE_FLOOR", None)
    if floor is None:
        return GateReading(
            gate="SC-3",
            status="MISS",
            reason="floor not committed",
            n=len(scored_rows),
            detail={},
        )

    n = len(scored_rows)
    if n == 0:
        return GateReading(gate="SC-3", status="MISS", reason="n=0", n=0, detail={})

    usable_n = sum(1 for r in scored_rows if r.e_answer_usable)
    p, ci_lo, ci_hi = wilson_ci(usable_n, n)
    status = "PASS" if p >= floor else "MISS"
    reason = (
        f"usable rate {p:.4f} >= floor {floor:.4f}"
        if status == "PASS"
        else f"usable rate {p:.4f} < floor {floor:.4f}"
    )

    # D-34: count GenerateAnswer failures on graph-off excluded from `answer_usable`'s
    # denominator -- specifically the D-69/marker-mismatch classes classify_record
    # only ever emits for the GenerateAnswer node, so a rise here (e.g. from D-71)
    # shrinks n instead of silently lowering (e) (AI-SPEC #5).
    excluded_generate_answer_failures = 0
    excluded_by_class: dict[str, int] = {}
    missing_flags: list[bool] = []
    for r in g_rows:
        arms = getattr(r, "arms", None)
        if not arms:
            continue
        graph_off = arms.get("graph-off")
        if graph_off is None:
            continue
        is_d69_rejection = graph_off.error_class in _D69_REJECTION_CLASSES
        if graph_off.outcome == "error" and is_d69_rejection:
            excluded_generate_answer_failures += 1
        if graph_off.outcome == "error":
            # WR-04: every graph-off error class over G shrinks n, not only D-69's.
            error_class = graph_off.error_class or "unclassified"
            excluded_by_class[error_class] = excluded_by_class.get(error_class, 0) + 1
        if graph_off.final_answer_missing is not None:
            missing_flags.append(bool(graph_off.final_answer_missing))

    detail: dict[str, Any] = {
        "usable_n": float(usable_n),
        "n": float(n),
        "floor": float(floor),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
        "excluded_generate_answer_failures": float(excluded_generate_answer_failures),
        "excluded_by_class": excluded_by_class,
    }
    coverage_reason, coverage_detail = _coverage_clause(n, expected_g, "sample & G")
    detail.update(coverage_detail)
    if coverage_reason is not None:
        reason = coverage_reason if status == "PASS" else f"{reason}; {coverage_reason}"
        status = "MISS"

    # D-70/D-74/AI-SPEC #6: final_answer_missing rate over G (graph-off), reported
    # beside SC-3 (context, not gated) -- a rise above the committed review rate
    # flags a table review, per FINAL_ANSWER_MISSING_REVIEW_RATE (D-73).
    if missing_flags:
        missing_rate = sum(1 for m in missing_flags if m) / len(missing_flags)
        detail["final_answer_missing_rate"] = float(missing_rate)
        detail["final_answer_missing_review_rate_threshold"] = float(
            FINAL_ANSWER_MISSING_REVIEW_RATE
        )
        detail["final_answer_missing_review_triggered"] = (
            missing_rate > FINAL_ANSWER_MISSING_REVIEW_RATE
        )

    gold_map: dict[str, Any] = {}
    if corpus_name:
        try:
            gold_map = {q.question_id: q for q in load_sample_questions(corpus_name)}
        except Exception:
            gold_map = {}

    if gold_map:
        by_type: dict[str, list[tuple[Any, Any]]] = {}
        by_binary: dict[str, list[tuple[Any, Any]]] = {}
        for r in scored_rows:
            gold = gold_map.get(r.question_id)
            if gold is None:
                continue
            qtype = getattr(r, "question_type", "unknown")
            by_type.setdefault(qtype, []).append((r, gold))
            is_binary = gold.gold_answer.strip().lower() in _BINARY_GOLD_ANSWERS
            key = "binary" if is_binary else "entity"
            by_binary.setdefault(key, []).append((r, gold))

        def _stratum(entries: list[tuple[Any, Any]]) -> dict[str, float]:
            stratum_n = len(entries)
            stratum_usable = sum(1 for r, _ in entries if r.e_answer_usable)
            yes_count = sum(
                1 for _, g in entries if g.gold_answer.strip().lower() == "yes"
            )
            baseline = float(yes_count / stratum_n) if stratum_n else 0.0
            return {
                "n": float(stratum_n),
                "usable_n": float(stratum_usable),
                "rate": float(stratum_usable / stratum_n) if stratum_n else 0.0,
                "constant_yes_baseline": baseline,
            }

        strata = {
            f"type_{qtype}": _stratum(entries) for qtype, entries in by_type.items()
        }
        strata.update(
            {f"gold_{key}": _stratum(entries) for key, entries in by_binary.items()}
        )
        detail["strata"] = strata
    else:
        detail["strata"] = {}

    return GateReading(
        gate="SC-3",
        status=status,
        reason=reason,
        value=p,
        ci=(ci_lo, ci_hi),
        n=n,
        detail=detail,
    )


@dataclass(frozen=True)
class InvarianceReport:
    """Graph-off invariance between a baseline journal and a later one (D-95).

    A disclosure, not a gate: no threshold is committed for "a systematic shift",
    so this reports counts and the question IDs behind them for a human to read.
    """

    n_common: int = 0
    only_in_baseline: list[str] = field(default_factory=list)
    only_in_drive2: list[str] = field(default_factory=list)
    collapsed_duplicates: dict[str, int] = field(default_factory=dict)
    n_comparable: int = 0
    not_comparable_ids: list[str] = field(default_factory=list)
    answer_usable_agree_n: int = 0
    answer_usable_disagree_ids: list[str] = field(default_factory=list)
    answer_usable_not_scored_n: int = 0
    retrieved_set_equal_n: int = 0
    retrieved_set_differ_ids: list[str] = field(default_factory=list)
    retrieved_order_equal_n: int = 0
    any_difference: bool = False


# --- drive 2 (06.3.4.1-17): SC-4, SC-5 and graph-off invariance ----------------------

#: D-73: the only SC-5 reading this phase committed to thresholds.py. A literal that
#: doesn't match this means the committed policy changed without this module being
#: updated to interpret it -- refuse, don't guess.
_KNOWN_SC5_RULES = frozenset({"composition_floor_or_paired_ci_excludes_zero_n_ge_2"})
#: SC-5 branch (b) reads these two paired deltas; `final_answer_em` and the cost
#: deltas are reported beside them (AI-SPEC #12) but never qualify a PASS.
_SC5_QUALIFYING_DELTAS = ("coverage_at_4", "answer_usable")
#: recall_at_k's own default, used only when no corpus config can be resolved.
_DEFAULT_CHUNK_SIZE = 500


def _read_journal_corpus(journal_path: Path | str) -> str | None:
    path = Path(journal_path)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        first_line = f.readline().strip()
    if not first_line:
        return None
    try:
        header = json.loads(first_line)
    except json.JSONDecodeError:
        return None
    return header.get("corpus") if isinstance(header, dict) else None


def _resolve_gold(
    journal_path: Path | str, corpus: str | None, gold_questions: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Gold questions by ID: the caller's override, else the journal header's corpus."""
    if gold_questions is not None:
        if isinstance(gold_questions, dict):
            return dict(gold_questions), corpus
        return {q.question_id: q for q in gold_questions}, corpus
    corpus_name = corpus or _read_journal_corpus(journal_path)
    if not corpus_name:
        return None, None
    try:
        questions = load_sample_questions(corpus_name)
        return {q.question_id: q for q in questions}, corpus_name
    except Exception:
        return None, corpus_name


def _load_selection(populations_path: Path | str) -> dict[str, Any] | None:
    path = Path(populations_path)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        selection = json.load(f)
    return selection if isinstance(selection, dict) else None


def _ci_fields(k: int, n: int) -> tuple[float | None, float | None, float | None]:
    """(rate, lower, upper), all None for an empty denominator."""
    if n <= 0:
        return None, None, None
    p, lo, hi = wilson_ci(k, n)
    return float(p), float(lo), float(hi)


def _presence_stats(graph_on_records: list[Any]) -> dict[str, Any]:
    """D-06 presence, influence and seeding diagnostics over graph-on records.

    Presence goes through `make_graph_presence_rate`, so the all-usable figure is the
    same number `report.json`'s `graph_presence_rate` carries. A field a record
    predates (None) is left out of its own denominator, never counted as zero.
    """
    presence = make_graph_presence_rate(records=graph_on_records)
    if presence.status == "ok":
        n = int(presence.detail["n_eval"])
        positive_n = int(presence.detail["positive_n"])
        rate: float | None = (
            float(presence.score) if presence.score is not None else None
        )
        ci_lower: float | None = float(presence.detail["ci_lower"])
        ci_upper: float | None = float(presence.detail["ci_upper"])
        no_match_rate: float | None = float(presence.detail["no_match_rate"])
        missing_meta_n = int(presence.detail["missing_meta_n"])
    else:
        n, positive_n, rate, ci_lower, ci_upper = 0, 0, None, None, None
        no_match_rate = None
        missing_meta_n = len(graph_on_records)

    metas = [r.workflow_meta for r in graph_on_records if r.workflow_meta is not None]
    facts = [
        m.graph_prompt_fact_count
        for m in metas
        if m.graph_prompt_fact_count is not None
    ]
    influence_positive_n = sum(1 for count in facts if count > 0)
    influence_rate, influence_lo, influence_hi = _ci_fields(
        influence_positive_n, len(facts)
    )
    seed_counts = [m.graph_seed_count for m in metas if m.graph_seed_count is not None]
    paths = [m.graph_path_found for m in metas if m.graph_path_found is not None]
    capped = [
        m.graph_degree_capped_count
        for m in metas
        if m.graph_degree_capped_count is not None
    ]
    return {
        "n": n,
        "n_records": len(graph_on_records),
        "missing_meta_n": missing_meta_n,
        "positive_n": positive_n,
        "rate": rate,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "no_match_rate": no_match_rate,
        "influence_n": len(facts),
        "influence_positive_n": influence_positive_n,
        "influence_rate": influence_rate,
        "influence_ci_lower": influence_lo,
        "influence_ci_upper": influence_hi,
        "seed_count_n": len(seed_counts),
        "seed_count_mean": (
            (sum(seed_counts) / len(seed_counts)) if seed_counts else None
        ),
        "path_found_n": len(paths),
        "path_found_positive_n": sum(1 for found in paths if found),
        "degree_capped_n": len(capped),
        "degree_capped_total": sum(capped),
    }


def _form_drive2_pairs(
    journal_path: Path | str, gold: dict[str, Any]
) -> tuple[list[Any], Any]:
    """Deduplicated records and the D-34/D-37 `form_pairs` join over them."""
    records, _ = deduplicate_by_arm(load_records(journal_path))
    return records, form_pairs(records, gold)


def evaluate_sc4(
    journal_path: Path | str,
    populations_path: Path | str,
    *,
    corpus: str | None = None,
    gold_questions: Any = None,
    expected_g: int | None = None,
) -> GateReading:
    """SC-4 (AI-SPEC #9/#10, D-81): graph presence over pairs(G) on the drive-2 journal.

    Presence keeps the D-06 definition (`graph_node_count > 0 or graph_edge_count
    > 0` on graph-on), so pairs(A) stays comparable to 06.3.4's 14/143. PASS needs
    the headline at or above `GRAPH_YIELD_INVESTIGATION_FLOOR` (06.3.1 D-32, not
    amended) AND its Wilson lower bound strictly above
    `GRAPH_PRESENCE_WILSON_LOWER_FLOOR`. pairs(A) and every usable graph-on record
    are reported beside it (D-82), with influence, seeding diagnostics and the
    no-match rate; none of those gates. An empty pairs(G) is MISS "n=0".

    `corpus` and `gold_questions` are keyword-only overrides: by default the corpus
    comes from the journal header, as in `evaluate_sc3`. `expected_g` is |sample & G|:
    the pairs(G) headline n below `UNPARK_GATE_COVERAGE_FLOOR` of it is MISS (CR-02).
    """
    selection = _load_selection(populations_path)
    if selection is None:
        return GateReading(
            gate="SC-4",
            status="MISS",
            reason="n=0",
            n=0,
            detail={"error": f"populations file not found: {populations_path}"},
        )
    gold, _corpus_name = _resolve_gold(journal_path, corpus, gold_questions)
    if gold is None:
        return GateReading(
            gate="SC-4",
            status="MISS",
            reason="gold questions unavailable (no corpus in the journal header)",
            n=0,
        )

    g_ids = set(selection.get("g_question_ids") or [])
    records, join = _form_drive2_pairs(journal_path, gold)
    pairs_a = join.pairs
    pairs_g = [p for p in pairs_a if p.question_id in g_ids]
    usable_graph_on = [
        r for r in records if r.graph_arm == "graph-on" and is_usable(r)
    ]

    populations = {
        "pairs_G": _presence_stats([p.graph_on for p in pairs_g]),
        "pairs_A": _presence_stats([p.graph_on for p in pairs_a]),
        "all_usable_graph_on": _presence_stats(usable_graph_on),
    }
    floor = thresholds.GRAPH_YIELD_INVESTIGATION_FLOOR
    wilson_floor = thresholds.GRAPH_PRESENCE_WILSON_LOWER_FLOOR
    headline = populations["pairs_G"]
    detail: dict[str, Any] = {
        "headline_population": "pairs(G)",
        "investigation_floor": float(floor),
        "wilson_lower_floor": float(wilson_floor),
        "populations": populations,
    }
    if headline["influence_rate"] is not None:
        # AI-SPEC #10: SC-4 gates on presence; an influence rate under the floor is
        # disclosed as a packing drop, not gated (06.3.1 D-06).
        detail["influence_below_investigation_floor"] = bool(
            headline["influence_rate"] < floor
        )

    n = headline["n"]
    if n == 0:
        return GateReading(
            gate="SC-4", status="MISS", reason="n=0", n=0, detail=detail
        )

    rate = headline["rate"]
    ci_lower = headline["ci_lower"]
    ci_upper = headline["ci_upper"]
    reasons: list[str] = []
    if rate < floor:
        reasons.append(
            f"presence rate {rate:.4f} < investigation floor {floor:.2f} over pairs(G)"
        )
    if ci_lower <= wilson_floor:
        reasons.append(
            f"Wilson lower bound {ci_lower:.4f} <= committed {wilson_floor:.3f}"
        )
    coverage_reason, coverage_detail = _coverage_clause(n, expected_g, "sample & G")
    detail.update(coverage_detail)
    if coverage_reason is not None:
        reasons.append(coverage_reason)
    status = "MISS" if reasons else "PASS"
    reason = (
        "; ".join(reasons)
        if reasons
        else (
            f"presence rate {rate:.4f} >= floor {floor:.2f} and Wilson lower bound "
            f"{ci_lower:.4f} > {wilson_floor:.3f} over pairs(G)"
        )
    )
    return GateReading(
        gate="SC-4",
        status=status,
        reason=reason,
        value=rate,
        ci=(ci_lower, ci_upper),
        n=n,
        detail=detail,
    )


def _composition_change(pairs: list[Any]) -> dict[str, Any]:
    """D-81 retrieval composition: pairs whose graph-on final set holds a chunk that
    is `graph_boosted` AND absent from graph-off's final set.

    A plain set difference does not count: `reformulation_used` alone moves the set
    between arms, so only the engine's own provenance flag is a graph effect. A pair
    whose graph-on chunks all lack the flag (a record that predates it) is
    unmeasured, not a "no".
    """
    n = 0
    changed_ids: list[str] = []
    unmeasured_ids: list[str] = []
    for pair in pairs:
        on_snapshot = pair.graph_on.snapshot
        on_chunks = on_snapshot.retrieved_chunks if on_snapshot is not None else []
        if on_snapshot is None or (
            on_chunks and all(c.graph_boosted is None for c in on_chunks)
        ):
            unmeasured_ids.append(pair.question_id)
            continue
        off_snapshot = pair.graph_off.snapshot
        off_ids = {
            c.chunk_id
            for c in (off_snapshot.retrieved_chunks if off_snapshot is not None else [])
        }
        n += 1
        if any(
            c.graph_boosted is True and c.chunk_id not in off_ids for c in on_chunks
        ):
            changed_ids.append(pair.question_id)
    rate, ci_lower, ci_upper = _ci_fields(len(changed_ids), n)
    return {
        "n": n,
        "changed_n": len(changed_ids),
        "rate": rate,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "unmeasured_n": len(unmeasured_ids),
        "changed_ids": changed_ids,
    }


def _unpaired_boost_share(records: list[Any]) -> dict[str, Any]:
    """The D-82 "all usable graph-on records" view of retrieval composition.

    Pairs are what D-81's measure needs (a chunk is a composition change only against
    graph-off's set), so this is NOT that measure: it is the unpaired share of usable
    graph-on records whose final set holds a `graph_boosted` chunk, kept visible so the
    G and V restrictions never hide the unrestricted population. Records whose chunks
    all lack the flag (they predate it) are counted apart, never as "no". It does not
    feed the SC-5 PASS rule.
    """
    n = 0
    boosted_n = 0
    unmeasured_n = 0
    for record in records:
        if record.graph_arm != "graph-on" or not is_usable(record):
            continue
        chunks = record.snapshot.retrieved_chunks if record.snapshot else []
        if record.snapshot is None or (
            chunks and all(c.graph_boosted is None for c in chunks)
        ):
            unmeasured_n += 1
            continue
        n += 1
        boosted_n += int(any(c.graph_boosted is True for c in chunks))
    rate, ci_lower, ci_upper = _ci_fields(boosted_n, n)
    return {
        "paired": False,
        "gating": False,
        "n": n,
        "boosted_n": boosted_n,
        "rate": rate,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "unmeasured_n": unmeasured_n,
    }


def _delta_fields(result: Any) -> dict[str, Any]:
    return {
        "mean": result.mean,
        "ci_lower": result.ci_lower,
        "ci_upper": result.ci_upper,
        "n_pairs": result.pair_count,
        "pairing_coverage": result.pairing_coverage,
        "answerable_count": result.answerable_count,
        "excluded_count": result.excluded_count,
        "is_degenerate": result.is_degenerate,
        "strata": result.strata,
        "strata_counts": result.strata_counts,
    }


def _paired_deltas(
    pairs: list[Any],
    *,
    coverage_denominator: int,
    answerable_count: int,
    chunk_size: int,
) -> dict[str, dict[str, Any]]:
    """AI-SPEC #12 paired deltas, each a `compute_paired_delta` (B = 10000, seed 42)
    stratified by `question_type` (D-40). Scorers match `score.py`'s, so coverage@4 is
    the same number `graph_ablation_delta` reports."""

    def coverage(rec: Any, gold: Any) -> float | None:
        if not has_scorable_payload(rec):
            return None
        out = recall_at_k(
            gold, rec.snapshot.retrieved_chunks, k=4, chunk_size=chunk_size
        )
        return out.score if out.status == "ok" else None

    def usable(rec: Any, gold: Any) -> float | None:
        if not has_scorable_payload(rec) or gold.is_null:
            return None
        return 1.0 if compute_answer_usable(gold, rec.answer) else 0.0

    def final_em(rec: Any, gold: Any) -> float | None:
        if not has_scorable_payload(rec) or gold.is_null:
            return None
        out = final_answer_em(gold, rec.answer)
        return out.score if out.status == "ok" else None

    def latency(rec: Any, gold: Any) -> float | None:
        return float(rec.duration_ms)

    def prompt_tokens(rec: Any, gold: Any) -> float | None:
        if rec.workflow_meta is None:
            return None
        return float(rec.workflow_meta.prompt_tokens)

    scorers = {
        "coverage_at_4": coverage,
        "answer_usable": usable,
        "final_answer_em": final_em,
        "latency_ms": latency,
        "prompt_tokens": prompt_tokens,
    }
    return {
        name: _delta_fields(
            compute_paired_delta(
                pairs,
                scorer,
                coverage_denominator=coverage_denominator,
                answerable_count=answerable_count,
            )
        )
        for name, scorer in scorers.items()
    }


def evaluate_sc5(
    journal_path: Path | str,
    populations_path: Path | str,
    *,
    corpus: str | None = None,
    gold_questions: Any = None,
    chunk_size: int | None = None,
    expected_v: int | None = None,
) -> GateReading:
    """SC-5 (AI-SPEC #11/#12, D-81/D-82): does the graph visibly change retrieval on V?

    PASS (the committed `SC5_VISIBILITY_RULE`): n_pairs(V) >= 1 AND either (a) the
    composition change over pairs(V) reaches `GRAPH_COMPOSITION_CHANGE_FLOOR`, or
    (b) a paired delta in coverage@4 or `answer_usable` has a bootstrap CI that
    excludes 0 with at least 2 pairs behind it (at n = 1 the CI collapses to a
    point, so there is no interval). Direction is not part of the rule: a negative
    delta that qualifies is a PASS flagged `negative` (06.3.1 D-49), and it is
    surfaced for the 6.4 unpark decision rather than hidden.

    pairs(G) and pairs(A) are reported beside pairs(V), never instead of it (D-82),
    and so is an unpaired view over all usable graph-on records
    (`unpaired_all_usable_graph_on`), which never feeds the PASS rule.
    V comes from the `v_question_ids` list in `populations_path`; without it the
    reading is MISS, never a guess.

    `expected_v` is |sample & V|: the composition population n over pairs(V) (the
    population rule (a) is computed on) below `UNPARK_GATE_COVERAGE_FLOOR` of it is
    MISS (CR-02). `n_pairs(V)` is reported beside it, and the rule itself is untouched.
    """
    selection = _load_selection(populations_path)
    if selection is None:
        return GateReading(
            gate="SC-5",
            status="MISS",
            reason="n=0",
            n=0,
            detail={"error": f"populations file not found: {populations_path}"},
        )
    if SC5_VISIBILITY_RULE not in _KNOWN_SC5_RULES:
        return GateReading(
            gate="SC-5",
            status="MISS",
            reason=(
                f"unknown SC-5 rule {SC5_VISIBILITY_RULE!r} "
                f"(known: {sorted(_KNOWN_SC5_RULES)})"
            ),
            n=0,
            detail={"sc5_visibility_rule": SC5_VISIBILITY_RULE},
        )
    if selection.get("v_question_ids") is None:
        return GateReading(
            gate="SC-5",
            status="MISS",
            reason="v_question_ids not committed in the populations file",
            n=0,
        )
    gold, corpus_name = _resolve_gold(journal_path, corpus, gold_questions)
    if gold is None:
        return GateReading(
            gate="SC-5",
            status="MISS",
            reason="gold questions unavailable (no corpus in the journal header)",
            n=0,
        )
    if chunk_size is None:
        chunk_size = _DEFAULT_CHUNK_SIZE
        if corpus_name:
            try:
                chunk_size = load_corpus_config(corpus_name).chunk_size
            except Exception:
                chunk_size = _DEFAULT_CHUNK_SIZE

    v_ids = set(selection["v_question_ids"])
    g_ids = set(selection.get("g_question_ids") or [])
    records, join = _form_drive2_pairs(journal_path, gold)
    attempted = {r.question_id for r in records}

    def population(
        pairs: list[Any], attempted_ids: set[str]
    ) -> dict[str, Any]:
        answerable = sum(
            1
            for qid in attempted_ids
            if qid in gold and not gold[qid].is_null
        )
        return {
            "n_pairs": len(pairs),
            "composition": _composition_change(pairs),
            "deltas": _paired_deltas(
                pairs,
                coverage_denominator=len(attempted_ids),
                answerable_count=answerable,
                chunk_size=chunk_size,
            ),
        }

    pairs_a = join.pairs
    pairs_v = [p for p in pairs_a if p.question_id in v_ids]
    pairs_g = [p for p in pairs_a if p.question_id in g_ids]
    populations = {
        "pairs_V": population(pairs_v, attempted & v_ids),
        "pairs_G": population(pairs_g, attempted & g_ids),
        "pairs_A": population(pairs_a, attempted),
    }

    headline = populations["pairs_V"]
    composition = headline["composition"]
    floor = thresholds.GRAPH_COMPOSITION_CHANGE_FLOOR
    negative_metrics = sorted(
        name
        for name in ("coverage_at_4", "answer_usable", "final_answer_em")
        if headline["deltas"][name]["mean"] is not None
        and headline["deltas"][name]["mean"] < 0
    )
    detail: dict[str, Any] = {
        "headline_population": "pairs(V)",
        "composition_floor": float(floor),
        "sc5_visibility_rule": SC5_VISIBILITY_RULE,
        "populations": populations,
        "unpaired_all_usable_graph_on": _unpaired_boost_share(records),
        "negative_metrics": negative_metrics,
        "negative": False,
    }
    if not pairs_v:
        return GateReading(
            gate="SC-5", status="MISS", reason="n=0", n=0, detail=detail
        )

    rule_a = composition["rate"] is not None and composition["rate"] >= floor
    qualifying: list[tuple[str, float]] = []
    for name in _SC5_QUALIFYING_DELTAS:
        delta = headline["deltas"][name]
        if (
            delta["n_pairs"] >= 2
            and not delta["is_degenerate"]
            and delta["ci_lower"] is not None
            and (delta["ci_lower"] > 0 or delta["ci_upper"] < 0)
        ):
            qualifying.append((name, float(delta["mean"])))
    rule_b = bool(qualifying)
    negative = any(mean < 0 for _, mean in qualifying)
    detail.update(
        {
            "composition_rule_met": rule_a,
            "paired_delta_rule_met": rule_b,
            "qualifying_deltas": {name: mean for name, mean in qualifying},
            "negative": negative,
        }
    )

    rate = composition["rate"]
    ci = (
        (composition["ci_lower"], composition["ci_upper"])
        if composition["ci_lower"] is not None
        else None
    )
    if rule_a or rule_b:
        parts: list[str] = []
        if rule_a:
            parts.append(
                f"composition change {rate:.4f} >= floor {floor:.2f} "
                f"({composition['changed_n']}/{composition['n']} pairs(V))"
            )
        if rule_b:
            parts.append(
                "paired delta CI excludes 0 with n_pairs >= 2: "
                + ", ".join(f"{name} {mean:+.4f}" for name, mean in qualifying)
            )
        reason = "; ".join(parts)
        if negative:
            reason += "; negative delta, flag for the unpark decision (06.3.1 D-49)"
        status = "PASS"
    else:
        shown = f"{rate:.4f}" if rate is not None else "unmeasured"
        reason = (
            f"composition change {shown} < floor {floor:.2f} and no paired delta in "
            f"{' or '.join(_SC5_QUALIFYING_DELTAS)} has a CI excluding 0 with "
            f"n_pairs >= 2"
        )
        status = "MISS"
    coverage_reason, coverage_detail = _coverage_clause(
        composition["n"], expected_v, "sample & V"
    )
    coverage_detail["n_pairs"] = len(pairs_v)
    detail.update(coverage_detail)
    if coverage_reason is not None:
        reason = coverage_reason if status == "PASS" else f"{reason}; {coverage_reason}"
        status = "MISS"
    return GateReading(
        gate="SC-5",
        status=status,
        reason=reason,
        value=rate,
        ci=ci,
        n=len(pairs_v),
        detail=detail,
    )


def graph_off_invariance(
    baseline_journal: Path | str,
    drive2_journal: Path | str,
    *,
    corpus: str | None = None,
    gold_questions: Any = None,
) -> InvarianceReport:
    """Graph-off invariance (AI-SPEC §6): the graph-off arm early-returns, so the
    graph work must not reach it. Reports, per question present in both journals,
    whether `answer_usable` agrees and whether the final retrieved set is equal.

    The baseline is drive 1b's journal (06.3.4.1-30): D-95 changed the answer path
    after drive 1, so drive 1b is the first graph-off arm on the current path. Only
    graph-off records are read. A resumed journal can carry duplicate (question,
    arm) records; the later one wins, as everywhere else, and the number collapsed is
    reported. No threshold is committed for a "systematic shift", so none is applied.
    """
    gold, _ = _resolve_gold(baseline_journal, corpus, gold_questions)

    def graph_off(path: Path | str) -> tuple[dict[str, Any], int]:
        off_records = [r for r in load_records(path) if r.graph_arm == "graph-off"]
        deduped, collapsed = deduplicate_by_arm(off_records)
        return {r.question_id: r for r in deduped}, collapsed

    base, base_collapsed = graph_off(baseline_journal)
    drive2, drive2_collapsed = graph_off(drive2_journal)
    common = sorted(set(base) & set(drive2))

    def comparable(rec: Any) -> bool:
        return rec.outcome == "success" and rec.snapshot is not None

    not_comparable: list[str] = []
    agree = 0
    disagree: list[str] = []
    not_scored = 0
    set_equal = 0
    set_differ: list[str] = []
    order_equal = 0
    for qid in common:
        rec_base, rec_d2 = base[qid], drive2[qid]
        if not (comparable(rec_base) and comparable(rec_d2)):
            not_comparable.append(qid)
            continue
        question = gold.get(qid) if gold is not None else None
        if question is None or question.is_null:
            not_scored += 1
        elif compute_answer_usable(question, rec_base.answer or "") == (
            compute_answer_usable(question, rec_d2.answer or "")
        ):
            agree += 1
        else:
            disagree.append(qid)
        base_ids = [c.chunk_id for c in rec_base.snapshot.retrieved_chunks]
        d2_ids = [c.chunk_id for c in rec_d2.snapshot.retrieved_chunks]
        if set(base_ids) == set(d2_ids):
            set_equal += 1
            if base_ids == d2_ids:
                order_equal += 1
        else:
            set_differ.append(qid)

    only_base = sorted(set(base) - set(drive2))
    only_d2 = sorted(set(drive2) - set(base))
    return InvarianceReport(
        n_common=len(common),
        only_in_baseline=only_base,
        only_in_drive2=only_d2,
        collapsed_duplicates={"baseline": base_collapsed, "drive2": drive2_collapsed},
        n_comparable=len(common) - len(not_comparable),
        not_comparable_ids=not_comparable,
        answer_usable_agree_n=agree,
        answer_usable_disagree_ids=disagree,
        answer_usable_not_scored_n=not_scored,
        retrieved_set_equal_n=set_equal,
        retrieved_set_differ_ids=set_differ,
        retrieved_order_equal_n=order_equal,
        any_difference=bool(
            disagree
            or set_differ
            or order_equal != set_equal
            or only_base
            or only_d2
            or not_comparable
        ),
    )


def _drive2_markdown(
    stage: str,
    readings: dict[str, GateReading],
    invariance: InvarianceReport | None,
    *,
    not_computed_reason: str | None = None,
    retry_provenance: str | None = None,
) -> list[str]:
    """Drive 2 is the run of record: SC-1, SC-4 and SC-5 are its gates. SC-2, SC-3
    and the D-69 rate are re-reported as disclosures only (AI-SPEC §5, gate sequence
    D-85), so a regression there is visible without being re-gated.

    `invariance` is None when a precondition failed and no reading was computed
    (CR-02, CR-03): the section then says `not computed: <reason>`. `retry_provenance`
    adds one line below the tables, before the invariance section."""
    gates = ("SC-1", "SC-4", "SC-5")
    disclosures = ("SC-2", "D-69 companion", "SC-3")
    lines = [f"# Unpark Gates ({stage})", "", "## Gates", ""]
    lines += ["| Gate | Status | n | Reason |", "|---|---|---|---|"]
    for name in gates:
        reading = readings[name]
        lines.append(f"| {name} | {reading.status} | {reading.n} | {reading.reason} |")
    lines += [
        "",
        "## Re-reported as disclosures (not gates on drive 2)",
        "",
        "| Reading | Status | n | Reason |",
        "|---|---|---|---|",
    ]
    for name in disclosures:
        reading = readings[name]
        lines.append(f"| {name} | {reading.status} | {reading.n} | {reading.reason} |")
    if retry_provenance is not None:
        lines += ["", f"Retry provenance: {retry_provenance}"]
    lines += [
        "",
        "## Graph-off invariance vs the baseline run (disclosure, no threshold)",
        "",
    ]
    if invariance is None:
        lines.append(f"not computed: {not_computed_reason or 'no reason recorded'}")
        return lines
    lines += [
        f"- questions in both journals: {invariance.n_common} "
        f"(comparable: {invariance.n_comparable})",
        f"- answer_usable agrees: {invariance.answer_usable_agree_n}; differs: "
        f"{len(invariance.answer_usable_disagree_ids)} "
        f"{invariance.answer_usable_disagree_ids}",
        f"- final retrieved set equal: {invariance.retrieved_set_equal_n}; differs: "
        f"{len(invariance.retrieved_set_differ_ids)} "
        f"{invariance.retrieved_set_differ_ids}",
        f"- same set in the same order: {invariance.retrieved_order_equal_n}",
        f"- only in the baseline: {len(invariance.only_in_baseline)}; only in this "
        f"run: {len(invariance.only_in_drive2)}",
        f"- duplicate records collapsed: {invariance.collapsed_duplicates}",
        f"- any difference: {invariance.any_difference}",
    ]
    return lines


def _ascii(value: Any) -> str:
    """`value` as ASCII text: `main` prints every reason, and a redirected Windows
    stdout in a legacy code page raises on anything else (06.3.4.1-32)."""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def legacy_records_digest(records: Sequence[Any]) -> str:
    """The sha256 that binds a legacy-registry entry to a journal's records (WR-01).

    Over the parsed identity fields of every record, in a canonical order and a
    canonical JSON form, so the line endings of the file cannot change it. Each row is
    `[corpus, question_id, graph_arm, outcome, duration_ms, correlation_id]`.
    """
    rows = sorted(
        (
            [
                rec.corpus,
                rec.question_id,
                rec.graph_arm,
                rec.outcome,
                rec.duration_ms,
                rec.correlation_id,
            ]
            for rec in records
        ),
        key=lambda row: json.dumps(row, separators=(",", ":")),
    )
    canonical = json.dumps(rows, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _legacy_registry() -> Mapping[tuple[str, float], _LegacyDrive]:
    """The registered pre-marker drives (the lookup tests patch; never mutated)."""
    return _LEGACY_UNMARKED_GATE_DRIVES


def _legacy_drive(
    header: dict[str, Any], records: Sequence[Any]
) -> _LegacyDrive | None:
    """The registry entry for a pre-marker journal, or None when it is not that drive.

    The header key, the record count and the records' digest must all match (WR-01).
    """
    key: tuple[Any, Any] = (header.get("corpus"), header.get("created_at"))
    try:
        entry = _legacy_registry().get(key)
    except TypeError:  # an unhashable header value is never a registered key
        return None
    if entry is None or len(records) != entry.n_records:
        return None
    if legacy_records_digest(records) != entry.records_sha256:
        return None
    return entry


def _retry_provenance(
    header: dict[str, Any], records: list[Any], stage: str
) -> tuple[str, list[str]]:
    """How the journal was driven, as text, and why it may not be read as `stage`.

    The header's gate-stage marker (06.3.4.1-33) must name `stage` with `max_retries`
    0. A header with no marker is read only when it is one of the three recorded
    pre-marker drives, under its own stage label (`_LEGACY_UNMARKED_GATE_DRIVES`). The
    records are scanned as well, because the header is written once: any record that
    carries a prior attempt means a retry ran (D-67, CR-03).
    """
    failures: list[str] = []
    if "max_retries" in header:
        marker_stage = header.get("gate_stage")
        retries = header["max_retries"]
        text = (
            f"header marker: gate_stage={_ascii(marker_stage)}, "
            f"max_retries={_ascii(retries)}"
        )
        if marker_stage != stage:
            failures.append(
                f"journal header gate_stage={marker_stage!a} is not "
                f"--stage {stage!a} (D-67)"
            )
        if isinstance(retries, bool) or retries != 0:
            failures.append(
                f"journal header max_retries={retries!a}, not 0 (D-67)"
            )
    elif "gate_stage" in header:
        text = "no marker: header carries gate_stage without max_retries"
        failures.append(
            "journal header carries gate_stage without max_retries "
            "(incomplete gate-stage marker)"
        )
    else:
        entry = _legacy_drive(header, records)
        if entry is None:
            text = "no marker: not one of the registered pre-marker gate drives"
            failures.append(
                "journal header carries no gate-stage marker "
                "(driven without --gate-stage)"
            )
        else:
            label, evidence = entry.label, entry.evidence
            if label == stage:
                text = f"legacy: {evidence}"
            else:
                text = (
                    f"legacy: registered as {label!a}, "
                    f"read under {stage!a}"
                )
                failures.append(
                    f"journal is the registered pre-marker drive {label!a}, "
                    f"not --stage {stage!a}"
                )
    retried = sum(1 for rec in records if rec.prior_attempts)
    if retried:
        failures.append(f"{retried} record(s) carry retried attempts (D-67)")
    return text, failures


def _journal_preconditions(
    journal_path: Path, stage: str
) -> tuple[str | None, tuple[bool, int] | None, list[str], str]:
    """The one place that decides whether the journal may be scored at all (CR-02).

    Returns the corpus named by the journal, the measured `(is_complete, missing_count)`
    (None when completeness could not be measured), the failure reasons, and the retry
    provenance text. A journal that is absent, headerless, corpus-less, unmeasurable or
    incomplete fails: no reading may be computed from the records of such a journal
    (D-87a: a halted drive is never reported as complete). So does one that was not
    driven as `stage` with `--retries 0`, or that holds a retried attempt (CR-03, D-67;
    `_retry_provenance`). `completeness_comparison` is called here and nowhere else on
    `main`'s path, so completeness is measured exactly once.
    """
    if not journal_path.is_file():
        return None, None, ["no journal file"], "not assessed: no journal file"
    header = _read_journal_header(journal_path)
    if header is None:
        return None, None, ["no header"], "not assessed: no header"
    records = load_records(journal_path)
    corpus_name = header.get("corpus") or (records[0].corpus if records else None)
    if not corpus_name:
        return (
            None,
            None,
            ["no corpus in header or records"],
            "not assessed: no corpus in header or records",
        )
    failures: list[str] = []
    completeness: tuple[bool, int] | None = None
    try:
        is_complete, missing = completeness_comparison(journal_path, corpus_name)
    except Exception as exc:  # fail closed: an unmeasurable journal is not scored
        failures.append(
            f"journal completeness could not be measured for corpus {corpus_name!r}: "
            f"{type(exc).__name__}: {exc}"
        )
    else:
        completeness = (is_complete, len(missing))
        if not is_complete:
            failures.append(f"journal incomplete: {len(missing)} work unit(s) missing")
    provenance, provenance_failures = _retry_provenance(header, records, stage)
    return corpus_name, completeness, [*failures, *provenance_failures], provenance


def _unmet_precondition_readings(
    run_dir: Path,
    journal_path: Path,
    failures: list[str],
    completeness: tuple[bool, int] | None,
    provenance: str,
    *,
    is_drive2: bool,
) -> dict[str, GateReading]:
    """Every reading for the stage as MISS with the precondition reasons.

    SC-1 keeps its own header and report detail when completeness was measured, forced
    to MISS (a complete, honest journal with a provenance failure would otherwise read
    PASS); every other reading is a bare MISS and nothing is computed from the journal's
    records. SC-1's detail carries the retry provenance text.
    """
    reason = "; ".join(failures)
    n = len(load_records(journal_path)) if journal_path.is_file() else 0
    if completeness is not None:
        sc1 = evaluate_sc1(
            run_dir, is_complete=completeness[0], missing_count=completeness[1]
        )
        absent = [f for f in failures if f not in sc1.reason]
        if absent:
            kept = [sc1.reason] if sc1.status == "MISS" else []
            sc1 = replace(sc1, status="MISS", reason="; ".join([*absent, *kept]))
    else:
        sc1 = GateReading(
            gate="SC-1",
            status="MISS",
            reason=reason,
            n=n,
            detail={
                "journal_complete": False,
                "report_json_exists": (run_dir / "report.json").is_file(),
            },
        )
    sc1 = replace(sc1, detail={**sc1.detail, "retry_provenance": provenance})
    miss_detail: dict[str, Any] = {
        "journal_complete": bool(completeness and completeness[0]),
        "missing_units": completeness[1] if completeness is not None else None,
    }
    gates = [
        ("SC-2", "SC-2"),
        ("D-69 companion", "citation_rejection_rate"),
        ("SC-3", "SC-3"),
    ]
    if is_drive2:
        gates += [("SC-4", "SC-4"), ("SC-5", "SC-5")]
    readings = {"SC-1": sc1}
    for name, gate in gates:
        readings[name] = GateReading(
            gate=gate, status="MISS", reason=reason, n=n, detail=dict(miss_detail)
        )
    return readings


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m lancet_eval.unpark_gates --stage drive1 --run <dir>
    --gold-chunks <file> --populations <diag_selection.json> --engine-pid-before N
    --engine-pid-after N --out <md>`.

    Writes a markdown gate table plus a JSON sibling to `--out`, and always exits 0 --
    a MISS verdict is data, not a CLI error.

    `--stage drive2` adds SC-4, SC-5 and the graph-off invariance report and
    requires `--baseline-run` (drive 1b's run directory, 06.3.4.1-30; D-95). Every
    other stage label, `drive1` and `drive1b` included, writes exactly the SC-1,
    SC-2, D-69 companion and SC-3 readings and needs no baseline.
    """
    parser = argparse.ArgumentParser(prog="python -m lancet_eval.unpark_gates")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--baseline-run", dest="baseline_run", default=None)
    parser.add_argument("--gold-chunks", dest="gold_chunks", required=True)
    parser.add_argument("--populations", required=True)
    parser.add_argument(
        "--engine-pid-before", dest="engine_pid_before", type=int, required=True
    )
    parser.add_argument(
        "--engine-pid-after", dest="engine_pid_after", type=int, required=True
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    is_drive2 = args.stage == DRIVE2_STAGE
    if is_drive2 and not args.baseline_run:
        parser.error(
            "--stage drive2 requires --baseline-run (drive 1b's run directory, the "
            "graph-off invariance baseline under D-95)"
        )

    run_dir = Path(args.run)
    journal_path = run_dir / "journal.jsonl"
    if not journal_path.is_file():
        journal_path = run_dir / "journal.json"

    baseline_journal: Path | None = None
    if is_drive2:
        baseline_dir = Path(args.baseline_run)
        baseline_journal = baseline_dir / "journal.jsonl"
        if not baseline_journal.is_file():
            baseline_journal = baseline_dir / "journal.json"
        if not baseline_journal.is_file():
            parser.error(f"--baseline-run has no journal: {baseline_dir}")

    corpus_name, completeness, failures, provenance = _journal_preconditions(
        journal_path, args.stage
    )

    readings: dict[str, GateReading]
    payload_extra: dict[str, Any] = {}
    invariance: InvarianceReport | None = None
    not_computed_reason: str | None = None
    if failures:
        # CR-02: the journal under gate is not a complete scored run. Every reading is
        # MISS and none is computed from its records.
        not_computed_reason = "; ".join(failures)
        readings = _unmet_precondition_readings(
            run_dir,
            journal_path,
            failures,
            completeness,
            provenance,
            is_drive2=is_drive2,
        )
        if is_drive2:
            payload_extra["graph-off invariance"] = {
                "not_computed": not_computed_reason
            }
    else:
        sc1 = evaluate_sc1(run_dir, is_complete=True, missing_count=0)
        sc1 = replace(sc1, detail={**sc1.detail, "retry_provenance": provenance})
        sc2 = evaluate_sc2(journal_path, args.engine_pid_before, args.engine_pid_after)

        questions = load_sample_questions(corpus_name) if corpus_name else []
        d69 = citation_rejection_rate(journal_path, questions)

        # CR-02/WR-04: the coverage denominators are the SAMPLE's slice of G and V
        # (D-82), computed once here. Never len(g_ids) / len(v_ids), which are
        # corpus-wide, and never a journal-relative figure. A missing list is 0.
        selection = _load_selection(args.populations) or {}
        sample_ids = {q.question_id for q in questions}
        expected_g = len(sample_ids & set(selection.get("g_question_ids") or []))
        expected_v = len(sample_ids & set(selection.get("v_question_ids") or []))

        if corpus_name and journal_path.is_file():
            rows = build_rows(corpus_name, str(journal_path), args.gold_chunks)
        else:
            rows = []
        sc3 = evaluate_sc3(
            rows, args.populations, corpus=corpus_name, expected_g=expected_g
        )

        readings = {
            "SC-1": sc1,
            "SC-2": sc2,
            "D-69 companion": d69,
            "SC-3": sc3,
        }
        if is_drive2 and baseline_journal is not None:
            readings["SC-4"] = evaluate_sc4(
                journal_path,
                args.populations,
                corpus=corpus_name,
                expected_g=expected_g,
            )
            readings["SC-5"] = evaluate_sc5(
                journal_path,
                args.populations,
                corpus=corpus_name,
                expected_v=expected_v,
            )
            invariance = graph_off_invariance(
                baseline_journal, journal_path, corpus=corpus_name
            )
            payload_extra["graph-off invariance"] = asdict(invariance)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if is_drive2:
        md_lines = _drive2_markdown(
            args.stage,
            readings,
            invariance,
            not_computed_reason=not_computed_reason,
            retry_provenance=provenance,
        )
    else:
        md_lines = [
            f"# Unpark Gates ({args.stage})",
            "",
            "| Gate | Status | n | Reason |",
            "|---|---|---|---|",
        ]
        for name, reading in readings.items():
            row = f"| {name} | {reading.status} | {reading.n} | {reading.reason} |"
            md_lines.append(row)
        md_lines += ["", f"Retry provenance: {provenance}"]
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md_lines) + "\n")

    json_path = out_path.with_suffix(".json")
    payload = {name: asdict(reading) for name, reading in readings.items()}
    payload.update(payload_extra)
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    for name, reading in readings.items():
        print(f"{name}: {reading.status} ({reading.reason})")
    print(f"retry provenance: {provenance}")
    if invariance is not None:
        print(
            "graph-off invariance: disclosure "
            f"(any_difference={invariance.any_difference}, "
            f"common={invariance.n_common})"
        )
    elif is_drive2:
        print(f"graph-off invariance: not computed ({not_computed_reason})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
