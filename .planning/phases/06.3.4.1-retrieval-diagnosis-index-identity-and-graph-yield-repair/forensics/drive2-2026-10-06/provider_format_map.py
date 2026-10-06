"""Drive 1b provider and format map (06.3.4.1-30 Task 3 step 4).

Joins the engine's `generation_served` log lines (06.3.4.1-29, D-96) to the journal by
correlation_id. One output line per journal record, in journal order. Unmatched
records (no served line) are counted and kept with provider null, never dropped.

Usage: python provider_format_map.py <RUN> <engine-stderr.log> [<summary-out.json>]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from lancet_eval.metrics import extract_final_answer

_KV = re.compile(r'([A-Za-z_][\w.]*)="((?:[^"\\]|\\.)*)"')


def _unescape(value: str) -> str:
    return value.encode("utf-8").decode("unicode_escape", errors="replace") if "\\" in value else value


def parse_served(log_path: Path) -> list[dict[str, str | None]]:
    served: list[dict[str, str | None]] = []
    with open(log_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "generation_served" not in line or "engine::generation::openrouter" not in line:
                continue
            fields = {k: _unescape(v) for k, v in _KV.findall(line)}
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


def fmt_of(answer: str | None) -> str:
    text = answer or ""
    if not text.strip():
        return "."
    if extract_final_answer(text) is not None:
        return "L"
    if "answer:" in text.lower():
        return "i"
    return "n"


def reached_generate(rec: dict) -> bool:
    for t in rec.get("node_timings") or []:
        if isinstance(t, dict) and t.get("node_name") == "GenerateAnswer":
            return True
    return rec.get("outcome") == "success"


def rle(seq: list[str]) -> list[list[object]]:
    out: list[list[object]] = []
    for item in seq:
        if out and out[-1][0] == item:
            out[-1][1] = int(out[-1][1]) + 1  # type: ignore[arg-type]
        else:
            out.append([item, 1])
    return out


def main() -> int:
    run = Path(sys.argv[1])
    log = Path(sys.argv[2])
    summary_out = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    journal = [
        json.loads(line)
        for line in open(run / "journal.jsonl", encoding="utf-8")
        if line.strip()
    ]
    records = [r for r in journal if isinstance(r, dict) and r.get("question_id")]

    table: dict[str, dict] = {}
    table_path = run / "diagnostic" / "table.jsonl"
    if table_path.exists():
        for line in open(table_path, encoding="utf-8"):
            if line.strip():
                row = json.loads(line)
                table[row["question_id"]] = row

    served = parse_served(log)
    by_cid: dict[str, list[dict]] = defaultdict(list)
    for s in served:
        by_cid[str(s["correlation_id"])].append(s)

    out_dir = run / "diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for index, rec in enumerate(records):
        cid = rec.get("correlation_id")
        lines = by_cid.get(str(cid), []) if cid else []
        provider = lines[-1]["provider"] if lines else None
        rows.append(
            OrderedDict(
                index=index,
                question_id=rec.get("question_id"),
                graph_arm=rec.get("graph_arm"),
                correlation_id=cid,
                outcome=rec.get("outcome"),
                format=fmt_of(rec.get("answer")),
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
    with open(out_dir / "provider_format_map.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    fmt_string = "".join(r["format"] for r in rows)
    providers_seq = [r["provider"] or "null" for r in rows]
    graph_off_g_usable: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_provider: dict[str, dict] = {}
    for rec, row in zip(records, rows):
        prov = row["provider"] or "null"
        entry = per_provider.setdefault(
            prov, {"records": 0, "L": 0, "i": 0, "n": 0, ".": 0, "errors": 0, "graph_off_G_usable": 0, "graph_off_G_n": 0}
        )
        entry["records"] += 1
        entry[row["format"]] += 1
        if row["outcome"] != "success":
            entry["errors"] += 1
        trow = table.get(str(rec.get("question_id")))
        if trow and not trow.get("is_null") and rec.get("graph_arm") == "graph-off":
            arm = (trow.get("arms") or {}).get("graph-off") or {}
            if arm.get("outcome") == "success" and arm.get("answer_usable") is not None:
                entry["graph_off_G_n"] += 1
                entry["graph_off_G_usable"] += 1 if arm.get("answer_usable") else 0

    reached = [r for r in records if reached_generate(r)]
    reached_matched = [r for r in reached if by_cid.get(str(r.get("correlation_id")))]
    unmatched = [row for row in rows if not row["served"]]
    two_served = [row for row in rows if len(row["served"]) > 1]
    journal_cids = {str(r.get("correlation_id")) for r in records}
    served_not_in_journal = [s for s in served if str(s["correlation_id"]) not in journal_cids]

    summary = {
        "records": len(rows),
        "format_counts": dict(Counter(r["format"] for r in rows)),
        "format_by_arm": {
            arm: dict(Counter(r["format"] for r in rows if r["graph_arm"] == arm))
            for arm in ("graph-off", "graph-on")
        },
        "format_map": fmt_string,
        "provider_sequence_rle": rle(providers_seq),
        "per_provider": per_provider,
        "unmatched_count": len(unmatched),
        "unmatched": [
            {"index": r["index"], "question_id": r["question_id"], "graph_arm": r["graph_arm"], "outcome": r["outcome"]}
            for r in unmatched
        ],
        "two_served_lines": [
            {"index": r["index"], "question_id": r["question_id"], "graph_arm": r["graph_arm"], "providers": [s["provider"] for s in r["served"]]}
            for r in two_served
        ],
        "join_coverage": {
            "reached_generate_answer": len(reached),
            "with_served_line": len(reached_matched),
        },
        "served_lines_total": len(served),
        "served_lines_not_in_journal": len(served_not_in_journal),
        "distinct_models": sorted({str(s["model"]) for s in served}),
        "distinct_providers": sorted({str(s["provider"]) for s in served}),
    }
    text = json.dumps(summary, indent=1, ensure_ascii=False)
    print(text)
    if summary_out is not None:
        summary_out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
