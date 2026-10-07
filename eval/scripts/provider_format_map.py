"""Per-arm provider and format map of a run (06.3.5-09, D-107, D-96).

Joins the engine's `generation_served` stderr lines (logger
`engine::generation::openrouter`; fields `correlation_id`, `provider`,
`gen_ai.response.model`, `generation_id`) to the run journal by `correlation_id`, so a
provider switch in the middle of a drive can be disclosed per arm.

This is the 06.3.5 successor of the 06.3.4.1 forensics script
`forensics/drive2-2026-10-06/provider_format_map.py`, which stays unchanged: that copy
hard-codes the two legacy arm labels, and this one groups by the canonical arm labels
(`lancet_eval.arms.canonical_arm`, registry order) found in the journal, so a four-arm
held-out journal reads per arm. An arm label the registry does not know raises
`ValueError`; nothing is silently regrouped.

It is read-only. It never writes to the run journal and opens no run file for writing:
its only outputs are `provider_format_map.jsonl` and `provider_format_map-summary.json`
under `--out-dir` (default `<RUN_DIR>/diagnostic`).

One output row per journal record, in journal order, and no record is dropped. A record
with no served line has `provider: null`. A NO_EVIDENCE record skips generation and an
errored record may never reach it, so both appear as unmatched; the summary reconciles
`unmatched_count` against the NO_EVIDENCE and errored records and names any unexplained
remainder in `unmatched_unexplained`. `served_lines_not_in_journal` counts served lines
whose `correlation_id` no journal record carries.

Usage: python eval/scripts/provider_format_map.py RUN_DIR ENGINE_STDERR_LOG
           [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lancet_eval.arms import ARM_REGISTRY, canonical_arm
from lancet_eval.dimensions import NOTICE_CODE_NO_EVIDENCE
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.metrics import extract_final_answer

_KV = re.compile(r'([A-Za-z_][\w.]*)="((?:[^"\\]|\\.)*)"')
_ESCAPE = re.compile(r"\\([\"'\\nrt])")
_ESCAPES = {'"': '"', "'": "'", "\\": "\\", "n": "\n", "r": "\r", "t": "\t"}
_SERVED_LOGGER = "engine::generation::openrouter"
#: Sequence label of a record with no served line (its row carries `provider: null`).
_UNMATCHED = "null"
#: A served line that names no provider is not an unmatched record.
_NO_PROVIDER = "unknown"

ROWS_NAME = "provider_format_map.jsonl"
SUMMARY_NAME = "provider_format_map-summary.json"


def _unescape(value: str) -> str:
    """Undoes the `Debug` escapes the engine puts on every logged field."""
    return _ESCAPE.sub(lambda m: _ESCAPES[m.group(1)], value)


def parse_served(log_path: Path) -> list[dict[str, str | None]]:
    """The `generation_served` lines of an engine log that carry a correlation id."""
    served: list[dict[str, str | None]] = []
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "generation_served" not in line or _SERVED_LOGGER not in line:
                continue
            fields = {key: _unescape(val) for key, val in _KV.findall(line)}
            cid = fields.get("correlation_id")
            if not cid:
                continue
            served.append(
                {
                    "correlation_id": cid,
                    "provider": fields.get("provider"),
                    "model": fields.get("gen_ai.response.model"),
                    "generation_id": fields.get("generation_id"),
                    "ts": line.split(" ", 1)[0],
                }
            )
    return served


def format_of(answer: str | None) -> str:
    """`.` no answer, `L` line-start `Answer:`, `i` an inline one, `n` neither."""
    text = answer or ""
    if not text.strip():
        return "."
    if extract_final_answer(text) is not None:
        return "L"
    if "answer:" in text.lower():
        return "i"
    return "n"


def has_no_evidence(record: RunRecord) -> bool:
    """Whether the record carries the NO_EVIDENCE notice (generation was skipped)."""
    return any(
        n.code == "NO_EVIDENCE" or n.typed_code == NOTICE_CODE_NO_EVIDENCE
        for n in record.notices
    )


def reached_generate(record: RunRecord) -> bool:
    """Whether the record reached GenerateAnswer, so a served line is expected."""
    if any(t.node_name == "GenerateAnswer" for t in record.node_timings):
        return True
    if any(f.node_name == "GenerateAnswer" for f in record.node_failures):
        return True
    return record.outcome == "success" and not has_no_evidence(record)


def run_length_encode(sequence: Sequence[str]) -> list[list[Any]]:
    """`[[value, run length], ...]` in order."""
    out: list[list[Any]] = []
    for item in sequence:
        if out and out[-1][0] == item:
            out[-1][1] += 1
        else:
            out.append([item, 1])
    return out


def _unmatched_reason(record: RunRecord) -> str:
    if has_no_evidence(record):
        return "no_evidence"
    if record.outcome == "error":
        return "errored"
    return "unexplained"


def build_map(
    run_dir: Path, log_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The provider and format rows of a run, and their summary.

    Args:
        run_dir: A run directory holding `journal.jsonl`.
        log_path: The engine's stderr log.

    Returns:
        One row per journal record in journal order, and the summary.

    Raises:
        FileNotFoundError: If the run has no journal.
        ValueError: If a record's arm label is not in the registry.
    """
    journal_path = Path(run_dir) / "journal.jsonl"
    if not journal_path.is_file():
        raise FileNotFoundError(f"no journal at {journal_path}")
    records = load_records(journal_path)
    canonical = [canonical_arm(rec.graph_arm) for rec in records]
    arms = [arm for arm in ARM_REGISTRY if arm in set(canonical)]

    served = parse_served(Path(log_path))
    by_cid: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for entry in served:
        by_cid[str(entry["correlation_id"])].append(entry)

    rows: list[dict[str, Any]] = []
    for index, (rec, arm) in enumerate(zip(records, canonical, strict=True)):
        lines = by_cid.get(rec.correlation_id, []) if rec.correlation_id else []
        provider = (lines[-1]["provider"] or _NO_PROVIDER) if lines else None
        rows.append(
            OrderedDict(
                index=index,
                question_id=rec.question_id,
                graph_arm=rec.graph_arm,
                arm=arm,
                correlation_id=rec.correlation_id,
                outcome=rec.outcome,
                no_evidence=has_no_evidence(rec),
                format=format_of(rec.answer),
                served=[
                    {
                        "provider": s["provider"],
                        "gen_ai.response.model": s["model"],
                        "generation_id": s["generation_id"],
                    }
                    for s in lines
                ],
                provider=provider,
            )
        )

    labels = [
        row["provider"] if row["provider"] is not None else _UNMATCHED
        for row in rows
    ]
    by_arm_provider: dict[str, dict[str, int]] = {arm: {} for arm in arms}
    per_provider: dict[str, dict[str, int]] = {}
    by_arm: dict[str, dict[str, int]] = {
        arm: {
            "records": 0,
            "no_evidence": 0,
            "errored": 0,
            "unmatched": 0,
            "unmatched_no_evidence": 0,
            "unmatched_errored": 0,
        }
        for arm in arms
    }
    reasons: Counter[str] = Counter()
    unmatched: list[dict[str, Any]] = []
    for rec, row, label in zip(records, rows, labels, strict=True):
        arm = row["arm"]
        arm_counts = by_arm_provider[arm]
        arm_counts[label] = arm_counts.get(label, 0) + 1
        entry = per_provider.setdefault(
            label,
            {"records": 0, "L": 0, "i": 0, "n": 0, ".": 0, "errors": 0},
        )
        entry["records"] += 1
        entry[row["format"]] += 1
        if rec.outcome != "success":
            entry["errors"] += 1
        counts = by_arm[arm]
        counts["records"] += 1
        counts["no_evidence"] += 1 if row["no_evidence"] else 0
        counts["errored"] += 1 if rec.outcome == "error" else 0
        if not row["served"]:
            reason = _unmatched_reason(rec)
            reasons[reason] += 1
            counts["unmatched"] += 1
            if reason == "no_evidence":
                counts["unmatched_no_evidence"] += 1
            elif reason == "errored":
                counts["unmatched_errored"] += 1
            unmatched.append(
                {
                    "index": row["index"],
                    "question_id": row["question_id"],
                    "graph_arm": row["graph_arm"],
                    "outcome": row["outcome"],
                    "reason": reason,
                }
            )

    reached = [rec for rec in records if reached_generate(rec)]
    reached_matched = [rec for rec in reached if by_cid.get(rec.correlation_id)]
    two_served = [row for row in rows if len(row["served"]) > 1]
    journal_cids = {rec.correlation_id for rec in records if rec.correlation_id}
    not_in_journal = [s for s in served if str(s["correlation_id"]) not in journal_cids]

    summary: dict[str, Any] = {
        "records": len(rows),
        "arms": arms,
        "format_counts": dict(Counter(row["format"] for row in rows)),
        "format_by_arm": {
            arm: dict(Counter(r["format"] for r in rows if r["arm"] == arm))
            for arm in arms
        },
        "format_map": "".join(row["format"] for row in rows),
        "provider_sequence_rle": run_length_encode(labels),
        "per_provider": per_provider,
        "by_arm_provider": by_arm_provider,
        "by_arm": by_arm,
        "unmatched_count": len(unmatched),
        "unmatched_no_evidence": reasons["no_evidence"],
        "unmatched_errored": reasons["errored"],
        "unmatched_unexplained": reasons["unexplained"],
        "unmatched": unmatched,
        "two_served_lines": [
            {
                "index": row["index"],
                "question_id": row["question_id"],
                "graph_arm": row["graph_arm"],
                "providers": [s["provider"] for s in row["served"]],
            }
            for row in two_served
        ],
        "join_coverage": {
            "reached_generate_answer": len(reached),
            "with_served_line": len(reached_matched),
        },
        "served_lines_total": len(served),
        "served_lines_not_in_journal": len(not_in_journal),
        "distinct_models": sorted({str(s["model"]) for s in served if s["model"]}),
        "distinct_providers": sorted(
            {str(s["provider"]) for s in served if s["provider"]}
        ),
    }
    return rows, summary


def main(argv: Sequence[str] | None = None) -> int:
    """Writes the rows and the summary under `--out-dir` and prints the summary."""
    parser = argparse.ArgumentParser(
        description="Per-arm provider and format map (read-only over the run)."
    )
    parser.add_argument("run_dir", metavar="RUN_DIR", type=Path)
    parser.add_argument("engine_stderr_log", metavar="ENGINE_STDERR_LOG", type=Path)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <RUN_DIR>/diagnostic).",
    )
    args = parser.parse_args(argv)

    rows, summary = build_map(args.run_dir, args.engine_stderr_log)
    out_dir = args.out_dir if args.out_dir is not None else args.run_dir / "diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / ROWS_NAME, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(out_dir / SUMMARY_NAME, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    # ASCII only: a redirected Windows stdout in a legacy code page rejects the rest.
    print(json.dumps(summary, indent=1, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
