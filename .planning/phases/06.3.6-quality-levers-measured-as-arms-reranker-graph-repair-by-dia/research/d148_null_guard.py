"""D-148 guard 1 (null-abstention) for 06.3.6-AI-SPEC.md section 5: dev evidence and the
operating characteristics of the candidate decision procedures.

Written by the 06.3.6 eval-planner, 2026-10-09. Offline, read-only, no network, no paid call.

    PYTHONUTF8=1 uv run --project eval python -I \
      .planning/phases/06.3.6-.../research/d148_null_guard.py > .../research/d148_null_guard.out

D-129: this script reads DEV journals only (drive 1, 1b, 2 on the 100 dev questions) and the
corpus document file. It never opens a held-out journal or `06.3.5-RUN-OF-RECORD.md`. The
margin below is fixed in section B, BEFORE section C computes anything, and section C does
not feed back into it.

Stdlib only (`math.comb`, `fractions`): scipy is not in the eval environment, so section D
re-derives the researcher's `ni_margin_arithmetic.py` Clopper-Pearson figures by bisection on
the exact binomial tail, as a cross-check of the [computed] figures quoted in section 1b.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from fractions import Fraction
from pathlib import Path

from lancet_eval.journal import load_records
from lancet_eval.metrics import is_abstention
from lancet_eval.usability import is_usable

REPO = Path(__file__).resolve().parents[4]
CORPUS = REPO / "eval" / "corpora" / "multihop_rag"
DEV_DRIVES = {
    "drive1": REPO / "eval/runs/2026-09-30-drive1-multihop_rag_diag/journal.jsonl",
    "drive1b": REPO / "eval/runs/2026-10-01-drive1b-multihop_rag_diag/journal.jsonl",
    "drive2": REPO / "eval/runs/2026-10-06-drive2-multihop_rag_diag/journal.jsonl",
}
N_HELDOUT_NULL = 43  # heldout_split.json heldout_null_ids (design count, D-105), not a reading

# ---------------------------------------------------------------------------------------
# B. The rule, fixed here before anything below is computed (D-73 spirit, D-129).
# ---------------------------------------------------------------------------------------
MARGIN = Fraction(1, 10)  # max tolerated paired net-loss RATE on held-out null pairs
MIN_PAIR_FRACTION = Fraction(4, 5)  # gate.py STAGED_PAIRING_COVERAGE_FLOOR convention, 0.80
MARGIN_DERIVATION = (
    "0.10 = (i) the repo's committed 'material rate' convention (thresholds.py "
    "FINAL_ANSWER_MISSING_REVIEW_RATE 0.10; COMMITTED_THRESHOLDS "
    "max_tolerated_graph_timeout_rate 0.10); (ii) about the smallest margin a 43-question "
    "paired reading can resolve at all (section 1b [computed], cross-checked in section D). "
    "Dev cannot set it: section A shows the 10 dev nulls at the ceiling with no discordance. "
    "(A first draft of this comment cited a dev null-error rate of 1/10 for drive 2; section A "
    "shows 9/9 usable, so that reason was dropped. The value did not change.)"
)


def count_rule_fails(b: int, c: int, n_pairs: int, margin: Fraction = MARGIN) -> bool:
    """Guard 1 FAILS iff the paired net loss rate (b - c) / n_pairs exceeds the margin.

    b: null pairs where the reference abstains and the arm does not; c: the reverse.
    Equality passes ("drops by MORE than a margin", D-148).
    """
    return Fraction(b - c, n_pairs) > margin


def min_failing_net_loss(n_pairs: int, margin: Fraction = MARGIN) -> int:
    k = 0
    while not count_rule_fails(k, 0, n_pairs, margin):
        k += 1
    return k


# ---------------------------------------------------------------------------------------
# Exact binomial helpers (stdlib).
# ---------------------------------------------------------------------------------------
def binom_pmf(k: int, n: int, p: float) -> float:
    return math.comb(n, k) * p**k * (1 - p) ** (n - k)


def binom_cdf(k: int, n: int, p: float) -> float:
    return sum(binom_pmf(i, n, p) for i in range(0, k + 1))


def cp_upper(b: int, d: int, alpha: float = 0.05) -> float:
    """One-sided (1 - alpha) Clopper-Pearson upper bound on p given b successes of d."""
    if b >= d:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if binom_cdf(b, d, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def ni_formal_fails(b: int, c: int, n_pairs: int, margin: Fraction = MARGIN) -> bool:
    """Formal non-inferiority, conditional on d = b + c (the section 1b approximation):
    PASS only if the one-sided 95% upper bound on the net loss rate is <= margin."""
    d = b + c
    if d == 0:
        return False
    p_u = cp_upper(b, d)
    net_upper = d * (2 * p_u - 1)
    return net_upper / n_pairs > float(margin)


def p_fail_no_effect(d: int, rule, n_pairs: int = N_HELDOUT_NULL) -> float:
    """P(guard fails | no true effect, d discordant pairs): b ~ Binomial(d, 1/2)."""
    return sum(binom_pmf(b, d, 0.5) for b in range(d + 1) if rule(b, d - b, n_pairs))


def p_fail_true_harm(h: int, d0: int, rule, n_pairs: int = N_HELDOUT_NULL) -> float:
    """h abstentions turned into answers by the lever (always b), plus d0 symmetric
    background discordant pairs split Binomial(d0, 1/2)."""
    return sum(
        binom_pmf(x, d0, 0.5) for x in range(d0 + 1) if rule(h + x, d0 - x, n_pairs)
    )


def main() -> None:
    print("== B. Rule (fixed before sections A, C, D are computed)")
    print(f"margin = {MARGIN} = {float(MARGIN):.2f}; min pair fraction = {MIN_PAIR_FRACTION}")
    print("derivation:", MARGIN_DERIVATION)
    min_pairs = math.ceil(MIN_PAIR_FRACTION * N_HELDOUT_NULL)
    print(f"evaluable iff n_pairs >= ceil(0.80 x 43) = {min_pairs}")
    for n_pairs in (43, 40, 35):
        print(f"  n_pairs={n_pairs}: guard fails iff net loss b-c >= "
              f"{min_failing_net_loss(n_pairs)} questions "
              f"({min_failing_net_loss(n_pairs)}/{n_pairs} = "
              f"{min_failing_net_loss(n_pairs) / n_pairs:.4f} > 0.10)")
    print(f"  one null question = {100 / N_HELDOUT_NULL:.2f} points")

    print()
    print("== A. Dev evidence (drives 1, 1b, 2; the same 10 dev null questions; D-129: dev only)")
    dev = [json.loads(l) for l in open(CORPUS / "questions.diag.jsonl", encoding="utf-8")]
    null_ids = {q["question_id"] for q in dev if q["question_type"] == "null_query"}
    print(f"dev null questions: {len(null_ids)}")
    tot_pairs = tot_disc = 0
    for name, path in DEV_DRIVES.items():
        recs = [r for r in load_records(path) if r.question_id in null_ids]
        by = {}
        for r in recs:
            by[(r.question_id, r.graph_arm)] = r
        arms = sorted({r.graph_arm for r in recs})
        line = [f"{name}: arms {arms}"]
        for arm in arms:
            usable = [by[(q, arm)] for q in sorted(null_ids) if (q, arm) in by and is_usable(by[(q, arm)])]
            k = sum(1 for r in usable if is_abstention(r))
            line.append(f"{arm} abstained {k}/{len(usable)} usable")
        if len(arms) == 2:
            a0, a1 = arms
            b = c = n = 0
            for q in sorted(null_ids):
                r0, r1 = by.get((q, a0)), by.get((q, a1))
                if r0 is None or r1 is None or not is_usable(r0) or not is_usable(r1):
                    continue
                n += 1
                x0, x1 = is_abstention(r0), is_abstention(r1)
                if x0 and not x1:
                    b += 1
                elif x1 and not x0:
                    c += 1
            line.append(f"paired n={n}, discordant: {a0}-only abstains {b}, {a1}-only abstains {c}")
            tot_pairs += n
            tot_disc += b + c
        print("  " + "; ".join(line))
    print(f"  pooled over the three drives: {tot_disc} discordant of {tot_pairs} dev null pairs "
          "(graph-on vs graph-off, the same prompt; a lever that edits the prompt can perturb more)")

    # Do the dev null questions name a publication that IS in the corpus? (the metadata-lever mechanism)
    docs = [json.loads(l) for l in open(CORPUS / "documents.subset.jsonl", encoding="utf-8")]
    sources = sorted({d["source"].split(" | ")[0].strip() for d in docs if d.get("source")})
    named = Counter()
    hits_per_q = []
    for q in dev:
        if q["question_type"] != "null_query":
            continue
        text = q["query"].lower()
        hit = [s for s in sources if s.lower() in text]
        hits_per_q.append(len(hit))
        named.update(hit)
    print(f"  corpus publications (name before ' | '): {len(sources)} distinct")
    print(f"  dev null questions naming >= 1 corpus publication: "
          f"{sum(1 for h in hits_per_q if h)} of {len(hits_per_q)}; names matched: {dict(named)}")

    print()
    print("== C. Operating characteristics at n_pairs = 43 (arithmetic; no repo data)")
    rules = {
        "count rule, margin 0.10 (fail iff b-c >= 5)": lambda b, c, n: count_rule_fails(b, c, n, Fraction(1, 10)),
        "count rule, margin 0.05 (fail iff b-c >= 3)": lambda b, c, n: count_rule_fails(b, c, n, Fraction(1, 20)),
        "formal NI, margin 0.10 (fail iff 95% upper bound > 0.10)": lambda b, c, n: ni_formal_fails(b, c, n, Fraction(1, 10)),
    }
    print("P(guard FAILS | no true effect), by d discordant null pairs:")
    header = "  d    " + " | ".join(f"{k[:40]:<40}" for k in rules)
    print(header)
    for d in (0, 2, 4, 6, 8, 10, 12, 16):
        print(f"  {d:<4} " + " | ".join(f"{p_fail_no_effect(d, r):<40.3f}" for r in rules.values()))
    print("P(guard FAILS | the lever converts h abstentions, plus d0 symmetric background pairs):")
    for h in (2, 3, 5, 7, 10):
        for d0 in (0, 4, 8):
            print(f"  h={h:<2} d0={d0:<2} " + " | ".join(
                f"{p_fail_true_harm(h, d0, r):<6.3f}" for r in rules.values()))

    print()
    print("== D. Cross-check of section 1b's [computed] figures (balanced b = c = d/2)")
    for d in (4, 8, 12, 16):
        b = d // 2
        p_u = cp_upper(b, d)
        net = d * (2 * p_u - 1)
        print(f"  d={d:<2} b=c={b}: one-sided 95% upper net loss ~ {net:.1f} q = {100 * net / 43:.1f} pts")
    print(json.dumps({"d148_null_guard": "ok"}))


if __name__ == "__main__":
    main()
