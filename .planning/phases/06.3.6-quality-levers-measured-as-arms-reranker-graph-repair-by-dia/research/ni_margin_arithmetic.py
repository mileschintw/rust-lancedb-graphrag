# Illustrative arithmetic for the D-148 null-abstention non-inferiority guard (n = 43 nulls).
# Written by the 06.3.6 domain researcher, 2026-10-09. Run: python -I ni_margin_arithmetic.py (needs scipy).
# It proposes NO margin. It shows what a paired exact one-sided bound can and cannot rule out at this n.
# Approximation: conditional on d discordant pairs, losses b ~ Binomial(d, p_loss); Clopper-Pearson one-sided 95% upper bound.
from scipy.stats import beta
n=43
print("one question =", round(100/n,2), "points")
# Paired design: lever loses b questions (ref right, lever wrong), wins c. Discordant d=b+c.
# Conditional on d, b ~ Binomial(d, 1/2) under no difference. One-sided 95% Clopper-Pearson UPPER bound on p_loss given observed b of d:
def upper(b,d,a=0.05):
    return 1.0 if b==d else beta.ppf(1-a, b+1, d-b)
for d in (4,8,12,16):
    b=d//2
    p=upper(b,d)
    # net loss in questions = b-c = d*(2p-1)
    net=d*(2*p-1)
    print(f"d={d} balanced b=c={b}: upper 95% one-sided net loss ~ {net:.1f} q = {100*net/n:.1f} pts")
for m_pts in (5,10,15):
    print(m_pts,"pts =", round(m_pts*n/100,1), "questions")
