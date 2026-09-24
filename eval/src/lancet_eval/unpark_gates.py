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
    FINAL_ANSWER_MISSING_REVIEW_RATE,
    SC2_TIMEOUT_DOMINANCE_RULE,
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


def evaluate_sc1(run_dir: Path | str) -> GateReading:
    """SC-1 / D-87a: header `partial` equals `not completeness_comparison(...)` AND
    (when non-partial) `report.json` exists via the unmodified fail-closed path.

    Reads only the journal header, `completeness_comparison`, and the presence of
    `report.json` on disk -- never calls `score_run`/`render_json` and adds no flag
    to either (a plan prohibition).
    """
    dir_path = Path(run_dir)
    journal_path = dir_path / "journal.jsonl"
    if not journal_path.is_file():
        journal_path = dir_path / "journal.json"
    if not journal_path.is_file():
        return GateReading(
            gate="SC-1", status="MISS", reason="no journal file", n=0, detail={}
        )

    with open(journal_path, encoding="utf-8") as f:
        first_line = f.readline().strip()
    header: dict[str, Any] | None = None
    if first_line:
        try:
            parsed = json.loads(first_line)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("type") == "header":
            header = parsed
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

    is_complete, missing = completeness_comparison(journal_path, corpus_name)
    expected_partial = not is_complete
    header_matches = header_partial == expected_partial

    report_json_path = dir_path / "report.json"
    report_exists = report_json_path.is_file()

    reasons: list[str] = []
    if not header_matches:
        reasons.append(
            f"header partial={header_partial} != not completeness_comparison()="
            f"{expected_partial} (missing {len(missing)} work unit(s))"
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
        "missing_units": float(len(missing)),
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

    class_counts: dict[str, int] = {}
    error_arms_by_qid: dict[str, set[str]] = {}
    for rec in records:
        cls = classify_record(rec)
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

    for rec in records:
        if not _reached_generate_answer(rec):
            continue
        gold = gold_map.get(rec.question_id)
        is_null = bool(gold.is_null) if gold is not None else False
        cls = classify_record(rec)
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
            detail={"class_counts": {}},
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
    rows: list[Any], populations_path: Path | str, *, corpus: str | None = None
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
        if graph_off.final_answer_missing is not None:
            missing_flags.append(bool(graph_off.final_answer_missing))

    detail: dict[str, Any] = {
        "usable_n": float(usable_n),
        "n": float(n),
        "floor": float(floor),
        "ci_lower": float(ci_lo),
        "ci_upper": float(ci_hi),
        "excluded_generate_answer_failures": float(excluded_generate_answer_failures),
    }

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


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m lancet_eval.unpark_gates --stage drive1 --run <dir>
    --gold-chunks <file> --populations <diag_selection.json> --engine-pid-before N
    --engine-pid-after N --out <md>`.

    Writes a markdown gate table plus a JSON sibling to `--out`, and always exits 0 --
    a MISS verdict is data, not a CLI error.
    """
    parser = argparse.ArgumentParser(prog="python -m lancet_eval.unpark_gates")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--run", required=True)
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

    run_dir = Path(args.run)
    journal_path = run_dir / "journal.jsonl"
    if not journal_path.is_file():
        journal_path = run_dir / "journal.json"

    sc1 = evaluate_sc1(run_dir)
    sc2 = evaluate_sc2(journal_path, args.engine_pid_before, args.engine_pid_after)

    corpus_name: str | None = None
    if journal_path.is_file():
        with open(journal_path, encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line:
            try:
                header = json.loads(first_line)
            except json.JSONDecodeError:
                header = {}
            if isinstance(header, dict):
                corpus_name = header.get("corpus")

    questions = load_sample_questions(corpus_name) if corpus_name else []
    d69 = citation_rejection_rate(journal_path, questions)

    if corpus_name and journal_path.is_file():
        rows = build_rows(corpus_name, str(journal_path), args.gold_chunks)
    else:
        rows = []
    sc3 = evaluate_sc3(rows, args.populations, corpus=corpus_name)

    readings: dict[str, GateReading] = {
        "SC-1": sc1,
        "SC-2": sc2,
        "D-69 companion": d69,
        "SC-3": sc3,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    md_lines = [
        f"# Unpark Gates ({args.stage})",
        "",
        "| Gate | Status | n | Reason |",
        "|---|---|---|---|",
    ]
    for name, reading in readings.items():
        row = f"| {name} | {reading.status} | {reading.n} | {reading.reason} |"
        md_lines.append(row)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md_lines) + "\n")

    json_path = out_path.with_suffix(".json")
    payload = {name: asdict(reading) for name, reading in readings.items()}
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    for name, reading in readings.items():
        print(f"{name}: {reading.status} ({reading.reason})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
