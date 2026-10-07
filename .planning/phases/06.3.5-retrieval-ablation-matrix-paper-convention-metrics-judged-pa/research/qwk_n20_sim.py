"""How noisy is a 20-item QWK? Uses the repo's own agreement.py (the D-113 path).

Run: cd eval && uv run python <this file>
Generative model (synthetic, NOT repo data):
  human ~ categorical over 1..5 with probs P_HUMAN
  judge = clip(human + e), e in {-2..2} with probs from a noise level
  'ceiling' scenarios: a fraction A of items are abstention-like, both raters give 5
  with prob q_both5, else judge drifts to 4.
For each scenario: population QWK (n=200k), then 2000 slices of n=20 ->
  percentiles of the point estimate, P(point < 0.6 / 0.7 / 0.8), undefined rate,
  and for 200 of those slices the b=1000 seeded percentile bootstrap CI
  (bootstrap_agreement_ci) width and the share of resamples dropped as undefined.
"""
import random, statistics
from lancet_eval.agreement import quadratic_weighted_kappa, bootstrap_agreement_ci

P_HUMAN = [0.10, 0.15, 0.20, 0.25, 0.30]

def draw_pair(rng, noise, abst=0.0, q_both5=1.0):
    if rng.random() < abst:
        return 5, (5 if rng.random() < q_both5 else 4)
    h = rng.choices([1, 2, 3, 4, 5], P_HUMAN)[0]
    e = rng.choices([-2, -1, 0, 1, 2], noise)[0]
    return h, min(5, max(1, h + e))

def qwk(h, j):
    return quadratic_weighted_kappa(h, j, min_rating=1, max_rating=5).value

def dropped_share(h, j, seed=42, b=1000):
    rng, n, bad = random.Random(seed), len(h), 0
    for _ in range(b):
        idx = [rng.randrange(n) for _ in range(n)]
        if quadratic_weighted_kappa([h[i] for i in idx], [j[i] for i in idx]).value is None:
            bad += 1
    return bad / b

SCEN = {
    # name: (noise probs for e=-2..2, abstention share, q_both5)
    "spread, light noise":  ([0.02, 0.14, 0.68, 0.14, 0.02], 0.0, 1.0),
    "spread, medium noise": ([0.05, 0.20, 0.50, 0.20, 0.05], 0.0, 1.0),
    "spread, heavy noise":  ([0.10, 0.22, 0.36, 0.22, 0.10], 0.0, 1.0),
    "40% ceiling (both 5), medium noise on rest": ([0.05, 0.20, 0.50, 0.20, 0.05], 0.40, 1.0),
    "40% ceiling (judge 5, human 5 or 4 at 80/20), medium noise": ([0.05, 0.20, 0.50, 0.20, 0.05], 0.40, 0.80),
    "80% ceiling (both 5), medium noise on rest": ([0.05, 0.20, 0.50, 0.20, 0.05], 0.80, 1.0),
}

def pct(xs, q):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]

rng = random.Random(20261006)
for name, (noise, abst, qb5) in SCEN.items():
    big = [draw_pair(rng, noise, abst, qb5) for _ in range(200_000)]
    pop = qwk([a for a, _ in big], [b for _, b in big])
    pts, undef, widths, drops = [], 0, [], []
    for s in range(2000):
        sl = [draw_pair(rng, noise, abst, qb5) for _ in range(20)]
        h, j = [a for a, _ in sl], [b for _, b in sl]
        v = qwk(h, j)
        if v is None:
            undef += 1; continue
        pts.append(v)
        if s < 200:
            ci = bootstrap_agreement_ci(h, j, "kappa", min_rating=1, max_rating=5, seed=42)
            if ci: widths.append(ci[1] - ci[0])
            drops.append(dropped_share(h, j))
    print(f"\n{name}\n  population QWK={pop:.3f}  n=20 slices: undefined {undef}/2000")
    print(f"  point estimate p5={pct(pts,.05):.3f} p50={pct(pts,.50):.3f} p95={pct(pts,.95):.3f}")
    for f in (0.6, 0.7, 0.8):
        print(f"  P(point < {f}) = {sum(p < f for p in pts)/len(pts):.3f}")
    print(f"  bootstrap 95% CI width (b=1000): median={statistics.median(widths):.3f} "
          f"p10={pct(widths,.1):.3f} p90={pct(widths,.9):.3f}; "
          f"resamples dropped undefined: median={statistics.median(drops):.3f} max={max(drops):.3f}")

# Single-slice illustrations
print("\nIllustrations (single fixed slices):")
h = [5] * 18 + [4, 5]; j = [5] * 18 + [5, 4]
print("  18/20 exact at ceiling, 2 swapped 4/5:", qwk(h, j), "CI", bootstrap_agreement_ci(h, j, "kappa", seed=42), "dropped", dropped_share(h, j))
h = [5] * 12 + [1, 2, 3, 4, 2, 3, 4, 5]; j = [5] * 12 + [1, 2, 3, 4, 3, 3, 4, 4]
print("  12 ceiling + 8 spread, 18/20 exact:", round(qwk(h, j), 4), "CI", bootstrap_agreement_ci(h, j, "kappa", seed=42), "dropped", dropped_share(h, j))
