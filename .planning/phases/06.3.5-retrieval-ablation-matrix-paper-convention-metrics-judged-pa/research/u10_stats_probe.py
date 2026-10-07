"""U9/U10/U11 research snippet: executes the claims the RESEARCH.md makes about stats, agreement and flatness.

Read-only; stdlib + lancet_eval only (no scipy). Run from repo root:
uv run --project eval python .planning/phases/06.3.5-*/research/u10_stats_probe.py
Not a deliverable: the proposed implementation lives in eval/src/lancet_eval/stats.py (exact_signflip_p, holm_stepdown).
"""
import random
import time
from fractions import Fraction
from math import comb

from lancet_eval.agreement import bootstrap_agreement_ci, quadratic_weighted_kappa
from lancet_eval.metrics import extract_final_answer
from lancet_eval.stats import bootstrap_mean_ci


def exact_signflip_p(n_pos: int, n_neg: int) -> Fraction:
    """Exact two-sided paired sign-flip p on 0/+-1 differences = exact McNemar (binomial on discordant pairs)."""
    nd = n_pos + n_neg
    if nd == 0:
        return Fraction(1)
    s_obs = abs(n_pos - n_neg)
    # S* = 2K - nd, K ~ Bin(nd, 1/2); P(|S*| >= s_obs)
    tail = sum(comb(nd, k) for k in range(nd + 1) if abs(2 * k - nd) >= s_obs)
    return Fraction(tail, 2**nd)


def mc_signflip_p(n_pos: int, n_neg: int, flips: int = 10_000, seed: int = 42) -> float:
    d = [1] * n_pos + [-1] * n_neg
    s_obs = abs(sum(d))
    rng = random.Random(seed)
    hits = 0
    for _ in range(flips):
        s = sum(x if rng.random() < 0.5 else -x for x in d)
        hits += abs(s) >= s_obs
    return (1 + hits) / (1 + flips)


def holm(ps: list[float], alpha: float = 0.05) -> tuple[list[bool], list[float]]:
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    reject = [False] * m
    adj = [0.0] * m
    running = 0.0
    stop = False
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * ps[i]))
        adj[i] = running
        if not stop and ps[i] <= alpha / (m - rank):
            reject[i] = True
        else:
            stop = True
    return reject, adj


print("p(5,0) =", exact_signflip_p(5, 0), "== 2/32:", exact_signflip_p(5, 0) == Fraction(2, 32))
print("p(0,0) =", exact_signflip_p(0, 0))
for pos, neg in [(12, 3), (30, 18), (20, 20), (9, 2)]:
    e, mc = float(exact_signflip_p(pos, neg)), mc_signflip_p(pos, neg)
    se = (e * (1 - e) / 10_000) ** 0.5
    print(f"({pos},{neg}) exact={e:.5f} mc={mc:.5f} |diff|/SE={abs(e - mc) / max(se, 1e-9):.2f}")
print("holm:", holm([0.001, 0.02, 0.04]), holm([0.02, 0.02, 0.9]))

t = time.perf_counter()
rng = random.Random(1)
diffs = [float(rng.choice([-1, 0, 0, 1])) for _ in range(308)]
bootstrap_mean_ci(diffs)  # B=10_000, n=308
print(f"bootstrap_mean_ci n=308 B=10000: {time.perf_counter() - t:.2f}s")

human = [5, 4, 5, 3, 2, 5, 4, 1, 3, 5, 4, 5, 2, 3, 5, 4, 5, 3, 4, 5]
judge = [5, 5, 5, 3, 3, 5, 4, 2, 3, 4, 4, 5, 2, 4, 5, 4, 5, 3, 5, 5]
t = time.perf_counter()
ci = bootstrap_agreement_ci(human, judge, "kappa", min_rating=1, max_rating=5, seed=42, b=10_000)
print(f"bootstrap_agreement_ci n=20 b=10000: {time.perf_counter() - t:.2f}s", ci, quadratic_weighted_kappa(human, judge).value)

for s in ["x\nAnswer: Insufficient information", "x\nAnswer: Insufficient information.", "**Answer:** insufficient information [2]",
          "Evidence says insufficient information\nAnswer: Yes", "Answer: Yes\nAnswer: Insufficient information", ""]:
    print(repr(s), "->", repr(extract_final_answer(s)), extract_final_answer(s) == "insufficient information")

# flatness: per-arm filtering must renumber ordinals (gap-free requirement)
from lancet_eval.decay import DecayAnalysisError
from lancet_eval.flatness import FlatnessRecord, SoakNodeTiming, flatness_verdict

recs = [FlatnessRecord(ordinal=i, graph_arm="hybrid" if i % 2 else "bm25-only",
                       node_timings=[SoakNodeTiming(node_name="RetrieveHybrid", duration_ms=100.0 + (i % 7))]) for i in range(1, 201)]
one_arm = [r for r in recs if r.graph_arm == "hybrid"]
try:
    flatness_verdict(one_arm)
    print("filtered-without-renumber: no error (unexpected)")
except DecayAnalysisError as e:
    print("filtered-without-renumber ->", type(e).__name__, str(e)[:70])
renum = [FlatnessRecord(ordinal=i, graph_arm=r.graph_arm, node_timings=r.node_timings) for i, r in enumerate(one_arm, 1)]
print("renumbered verdict:", flatness_verdict(renum).reason, "n=", len(renum))
