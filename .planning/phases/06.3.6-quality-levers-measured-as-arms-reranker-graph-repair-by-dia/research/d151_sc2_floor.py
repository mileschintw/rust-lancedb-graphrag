"""D-151 SC-2 error-mode materiality floor for 06.3.6-AI-SPEC.md section 5: the rule, then the
re-read of every recorded SC-2 gate reading under it.

Written by the 06.3.6 eval-planner, 2026-10-09. Offline, read-only (D-74): it opens the four
committed `gates-*.json` files and writes nothing under `eval/runs/`. No network, no paid call.

    PYTHONUTF8=1 uv run --project eval python -I \
      .planning/phases/06.3.6-.../research/d151_sc2_floor.py > .../research/d151_sc2_floor.out

Order (D-129, D-73 spirit): section 1 fixes the floor from committed constants that predate
06.3.5. Section 2 then re-reads the recorded verdicts. Nothing in section 2 feeds section 1.
The floor's EXISTENCE was motivated by the 06.3.5 held-out SC-2 MISS (ROADMAP carry-forward 1,
which quotes 12 timeouts, 0.85% of records); its VALUE is not derived from any held-out number.

The re-read is a labelled disclosure, not a re-adjudication (the UNPARK_GATE_COVERAGE_FLOOR
pattern, thresholds.py:146-157): the recorded gates-*.{md,json} are never rewritten, and the
floor governs only drives whose journal header `created_at` follows its commit.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from lancet_eval.thresholds import (
    COMMITTED_DECAY_THRESHOLDS_06341,
    COMMITTED_THRESHOLDS,
    SC2_TIMEOUT_DOMINANCE_RULE,
)

REPO = Path(__file__).resolve().parents[4]

# ---------------------------------------------------------------------------------------
# 1. The floor, from committed constants only.
# ---------------------------------------------------------------------------------------
# 06.3.3 budget rule: budget = ceil(p95 x 1.5). A node whose latency still follows the
# distribution its budget was derived on exceeds its derivation p95 on at most
# (1 - 0.95) = 5% of records, and exceeds the 1.5x budget (a timeout) on fewer still. A
# timeout rate of 5% therefore means the budget protects no better than the bare p95 it was
# built from: the 50% headroom is used up.
TAIL = Fraction(1) - Fraction(str(COMMITTED_THRESHOLDS.derivation_percentile))  # 1/20
# D-89: "decay is material once it would use half of that headroom"; D-89 encodes it as
# relative_materiality_fraction 0.25 of p95 against the 0.5 headroom of the 1.5x multiplier.
HALF = Fraction(str(COMMITTED_DECAY_THRESHOLDS_06341.relative_materiality_fraction)) / (
    Fraction(str(COMMITTED_THRESHOLDS.multiplier)) - 1
)  # 0.25 / 0.5 = 1/2
RATE_FLOOR = TAIL * HALF  # 1/40 = 0.025
# Alternative, not recommended: a count floor on all classified errors, reusing the
# committed minimum cell size (thresholds.py COMMITTED_THRESHOLDS.min_stratum_cell_size 10).
COUNT_FLOOR = COMMITTED_THRESHOLDS.min_stratum_cell_size


def error_mode_today(timeout_dominant: bool) -> bool:
    """06.3.4.1 SC-2 error-mode clause as committed: PASS iff timeout not dominant."""
    return not timeout_dominant


def error_mode_rate_floor(timeout_dominant: bool, timeouts: int, n: int) -> tuple[bool, str]:
    """RECOMMENDED: the clause FAILS only if timeout is dominant AND timeouts / n >= 1/40."""
    if not timeout_dominant:
        return True, "pass"
    if Fraction(timeouts, n) >= RATE_FLOOR:
        return False, "fail (dominant and material)"
    return True, "reported (dominant, not material)"


def error_mode_count_floor(timeout_dominant: bool, total_errors: int) -> tuple[bool, str]:
    """ALTERNATIVE: the clause FAILS only if timeout is dominant AND classified errors >= 10."""
    if not timeout_dominant:
        return True, "pass"
    if total_errors >= COUNT_FLOOR:
        return False, "fail (dominant, >= 10 errors)"
    return True, "reported (dominant, < 10 errors)"


GATES = {
    "drive1": REPO / "eval/runs/2026-09-30-drive1-multihop_rag_diag/gates-drive1.json",
    "drive1b": REPO / "eval/runs/2026-10-01-drive1b-multihop_rag_diag/gates-drive1b.json",
    "drive2": REPO / "eval/runs/2026-10-06-drive2-multihop_rag_diag/gates-drive2.json",
    "06.3.5 heldout": REPO / "eval/runs/2026-10-07-heldout-multihop_rag_heldout/gates-heldout.json",
}


def readings(name: str, data: dict) -> list[tuple[str, dict]]:
    sc2 = data["SC-2"]
    if "status" in sc2:  # one pooled reading (drives 1, 1b, 2)
        return [(f"{name} pooled", sc2)]
    return [(f"{name} {label}", reading) for label, reading in sc2.items()]


def flatness_passed(reading: dict) -> bool:
    """SC-2 = error mode AND flatness. evaluate_sc2/_arm append a 'flatness ...' reason
    fragment exactly when the flatness clause fails (unpark_gates.py:455-456, :630-631)."""
    return not any(
        part.strip().split(": ", 1)[-1].startswith("flatness")
        for part in reading["reason"].split(";")
    )


def main() -> None:
    print("== 1. Floor (fixed before any gate file is read)")
    print(f"tail = 1 - derivation_percentile {COMMITTED_THRESHOLDS.derivation_percentile} = {TAIL}")
    print(f"half = relative_materiality_fraction {COMMITTED_DECAY_THRESHOLDS_06341.relative_materiality_fraction}"
          f" / (multiplier {COMMITTED_THRESHOLDS.multiplier} - 1) = {HALF}")
    print(f"RATE_FLOOR = {RATE_FLOOR} = {float(RATE_FLOOR):.3f}  (timeouts / records in the reading)")
    print(f"dominance rule unchanged: {SC2_TIMEOUT_DOMINANCE_RULE!r}")
    for n in (100, 200, 351, 1404, 2106, 2457):
        k = 0
        while Fraction(k, n) < RATE_FLOOR:
            k += 1
        print(f"  n={n:<5}: a dominant timeout class is material at >= {k} timeouts")
    print(f"alternative COUNT_FLOOR = {COUNT_FLOOR} classified errors (min_stratum_cell_size)")

    print()
    print("== 2. Re-read of every recorded SC-2 reading (read-only)")
    hdr = (f"{'reading':<28} {'n':>5} {'timeouts':>8} {'errors':>6} {'rate':>7} {'dominant':>8} "
           f"{'flat':>5} {'recorded':>8} | {'rate floor (rec.)':<34} | {'count floor (alt.)':<30}")
    print(hdr)
    changed_rate, changed_count = [], []
    for name, path in GATES.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        for label, r in readings(name, data):
            det = r["detail"]
            counts = {k: int(v) for k, v in det.get("class_counts", {}).items()}
            timeouts = counts.get("timeout", 0)
            errors = sum(counts.values())
            n = int(r["n"])
            dom = bool(det.get("timeout_dominant", False))
            flat = flatness_passed(r)
            recorded = r["status"]
            em_today = error_mode_today(dom)
            assert (recorded == "PASS") == (em_today and flat), (label, recorded, em_today, flat)
            ok_r, why_r = error_mode_rate_floor(dom, timeouts, n)
            ok_c, why_c = error_mode_count_floor(dom, errors)
            v_r = "PASS" if (ok_r and flat) else "MISS"
            v_c = "PASS" if (ok_c and flat) else "MISS"
            if v_r != recorded:
                changed_rate.append(label)
            if v_c != recorded:
                changed_count.append(label)
            print(f"{label:<28} {n:>5} {timeouts:>8} {errors:>6} {timeouts / n:>7.2%} {str(dom):>8} "
                  f"{str(flat):>5} {recorded:>8} | {v_r + ' ' + why_r:<34} | {v_c + ' ' + why_c:<30}")
    print()
    print("verdicts that differ from the recorded ones:")
    print("  rate floor (recommended):", changed_rate or "none")
    print("  count floor (alternative):", changed_count or "none")
    for label in changed_rate + changed_count:
        assert label.startswith("06.3.5"), f"a drive-1/1b/2 verdict moved: {label}"
    print("drives 1, 1b and 2: unchanged under both rules (asserted)")
    print(json.dumps({"d151_sc2_floor": "ok"}))


if __name__ == "__main__":
    main()
