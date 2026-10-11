"""Check that a re-scored run reproduces the published values (06.4 D-200, D-201).

Usage: ``python eval/scripts/compare_rescore.py <committed_run_dir> <rescored_dir>``

Both directories hold a ``report.json``. The re-score reproduces the published values
when the ``dimensions`` and ``metadata.result_hash`` are equal and every other metadata
key that differs is one of ``commit_sha``, ``run_date`` and ``dependency_lock_hash``
(a CRLF checkout changes the lock hash). The script reads only; it writes nothing in
either directory. Exit 0 on reproduction, 1 with one line per failing reason, 2 on a
usage error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ALLOWED_METADATA_DIFFERENCES = frozenset({
    "commit_sha",
    "run_date",
    "dependency_lock_hash",
})


def _load_report(directory: Path) -> dict:
    path = directory / "report.json"
    with path.open(encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return report


def compare(committed_dir: Path, rescored_dir: Path) -> list[str]:
    """Return one reason per way the re-score differs; empty means it reproduces."""
    try:
        committed = _load_report(committed_dir)
        rescored = _load_report(rescored_dir)
    except (OSError, ValueError) as exc:
        return [f"cannot read report.json: {exc}"]

    reasons: list[str] = []
    if committed.get("dimensions") != rescored.get("dimensions"):
        reasons.append("scored dimensions differ")

    old_meta = committed.get("metadata")
    new_meta = rescored.get("metadata")
    if not isinstance(old_meta, dict) or not isinstance(new_meta, dict):
        reasons.append("metadata is missing or not an object in a report.json")
        return reasons

    if old_meta.get("result_hash") != new_meta.get("result_hash"):
        reasons.append(
            "metadata.result_hash differs: "
            f"{old_meta.get('result_hash')!r} vs {new_meta.get('result_hash')!r}"
        )
    differing = {
        key
        for key in set(old_meta) | set(new_meta)
        if old_meta.get(key) != new_meta.get(key)
    }
    unexpected = sorted(differing - ALLOWED_METADATA_DIFFERENCES - {"result_hash"})
    if unexpected:
        reasons.append(f"unexpected metadata differences: {unexpected}")
    return reasons


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "usage: compare_rescore.py <committed_run_dir> <rescored_dir>",
            file=sys.stderr,
        )
        return 2
    reasons = compare(Path(args[0]), Path(args[1]))
    if reasons:
        for reason in reasons:
            print(f"re-score does NOT reproduce the published values: {reason}")
        return 1
    print("re-score reproduces the published values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
