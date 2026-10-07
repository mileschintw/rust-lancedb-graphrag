"""Eval-planner extension of qwk_n20_sim.py: pass rates at candidate D-114 floors.
Same generative family (synthetic, NOT repo data): human ~ P_HUMAN over 1..5;
judge = with prob r an independent uniform 1..5 draw, else clip(human + e), e ~ medium noise.
Population QWK from 200k draws; 2000 slices of n=20; seed 20261006. Uses the repo's agreement.py."""
import random
from lancet_eval.agreement import quadratic_weighted_kappa
P_HUMAN = [0.10, 0.15, 0.20, 0.25, 0.30]
MED = [0.05, 0.20, 0.50, 0.20, 0.05]
def draw(rng, r):
    h = rng.choices([1,2,3,4,5], P_HUMAN)[0]
    if rng.random() < r:
        return h, rng.randint(1,5)
    e = rng.choices([-2,-1,0,1,2], MED)[0]
    return h, min(5, max(1, h+e))
def q(h,j): return quadratic_weighted_kappa(h,j).value
rng = random.Random(20261006)
for r in (0.0, 0.10, 0.20, 0.30, 0.40, 0.50):
    big=[draw(rng,r) for _ in range(200_000)]
    pop=q([a for a,_ in big],[b for _,b in big])
    pts=[]; und=0
    for _ in range(2000):
        sl=[draw(rng,r) for _ in range(20)]
        v=q([a for a,_ in sl],[b for _,b in sl])
        if v is None: und+=1; continue
        pts.append(v)
    n=len(pts)
    print(f"r={r:.2f} population QWK={pop:.3f} undefined={und} "
          f"P(pt>=0.60)={sum(p>=0.60 for p in pts)/n:.3f} P(pt>=0.70)={sum(p>=0.70 for p in pts)/n:.3f}")
