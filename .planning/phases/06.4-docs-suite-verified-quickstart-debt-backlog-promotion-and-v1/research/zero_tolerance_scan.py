"""Zero-tolerance provenance scan of the three committed run journals (06.4-03, note 10).

Run from the repo root as
``uv run --project eval python <this file>``.

Plan 06.4-03 added per-arm checks (`arms.explicit_field_failures`, the drive-environment
refusal, the gate-stage first-record gate) and changed the request fields of every
canonical arm. None of that may disturb `score`, which scans every record of a journal
with `score._provenance_scan` and refuses on any zero-tolerance clause. This script loads
the records of each committed run journal the way `score` does (header lines skipped,
records validated, then `deduplicate_by_arm`), runs the post-change `_provenance_scan`
over them, and prints per journal:

* the record count;
* the pooled per-clause tally (`a` to `j`) and the per-arm tally;
* the records carrying a code in `provenance.ZERO_TOLERANCE_CODES`.

It exits 1 if any journal has a fatal record. All three runs scored successfully when
they were recorded, so the recorded count is zero. The script only reads: it opens
nothing under eval/runs/ for writing.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from lancet_eval import provenance
from lancet_eval.journal import RunRecord
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.score import _provenance_scan

REPO = Path(__file__).resolve().parents[4]
JOURNALS = (
    "eval/runs/2026-10-06-drive2-multihop_rag_diag/journal.jsonl",
    "eval/runs/2026-10-07-heldout-multihop_rag_heldout/journal.jsonl",
    "eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout/journal.jsonl",
)


def load_like_score(path: Path) -> list[RunRecord]:
    """Reads the records of a journal the way `score.score_run` does."""
    records: list[RunRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            data = json.loads(text)
            if isinstance(data, dict) and data.get("type") == "header":
                continue
            if isinstance(data, dict) and "question_id" in data:
                try:
                    records.append(RunRecord.model_validate(data))
                except Exception as exc:
                    raise SystemExit(f"{path}:{line_num}: invalid RunRecord: {exc}")
    return records


def main() -> int:
    print(f"ZERO_TOLERANCE_CODES = {''.join(sorted(provenance.ZERO_TOLERANCE_CODES))}")
    exit_code = 0
    for rel in JOURNALS:
        path = REPO / rel
        print(f"\n== {rel}")
        if not path.is_file():
            print("  MISSING journal")
            exit_code = 1
            continue
        raw = load_like_score(path)
        records, collapsed = deduplicate_by_arm(raw)
        counts, failing = _provenance_scan(records)
        per_arm: dict[str, Counter[str]] = {}
        for rec in records:
            codes = sorted({f.code for f in provenance.provenance_failures(rec)})
            tally = per_arm.setdefault(rec.graph_arm, Counter())
            tally["records"] += 1
            for code in codes:
                tally[code] += 1
        print(f"  records read: {len(raw)}; scanned after dedup: {len(records)}"
              f" (collapsed {collapsed})")
        print(f"  pooled clause tally: {dict(counts)}")
        for arm in sorted(per_arm):
            tally = per_arm[arm]
            shown = {k: tally[k] for k in sorted(tally) if k != "records"}
            print(f"  arm {arm}: records={tally['records']} clauses={shown}")
        print(f"  fatal records (zero-tolerance codes): {len(failing)}")
        for question_id, arm, codes in failing:
            print(f"    FATAL {question_id} / {arm} / {codes}")
        if failing:
            exit_code = 1
    print(f"\nresult: {'FAIL' if exit_code else 'OK, zero fatal records in every journal'}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
