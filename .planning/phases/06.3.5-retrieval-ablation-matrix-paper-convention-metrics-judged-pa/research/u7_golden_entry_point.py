"""U7 research: AI-SPEC section 3 entry-point block, extracted verbatim and re-executed in this research session."""
import importlib.util, random, sys
from lancet_eval.agreement import bootstrap_agreement_ci, quadratic_weighted_kappa, spearman_rank_correlation

# 1. D-113/D-114 agreement path on a toy 20-item slice (owner vs judge, one dimension).
human = [5, 4, 5, 3, 2, 5, 4, 1, 3, 5, 4, 5, 2, 3, 5, 4, 5, 3, 4, 5]
judge = [5, 5, 5, 3, 3, 5, 4, 2, 3, 4, 4, 5, 2, 4, 5, 4, 5, 3, 5, 5]
qwk = quadratic_weighted_kappa(human, judge, min_rating=1, max_rating=5)
rho = spearman_rank_correlation(human, judge)
ci = bootstrap_agreement_ci(human, judge, "kappa", min_rating=1, max_rating=5, seed=42)  # b defaults to 1000
print(f"QWK={qwk.value:.4f} ({qwk.state}) rho={rho.value:.4f} kappa95CI={ci}")
# Critical failure mode 1, made concrete: 18/20 exact agreement at the ceiling gives QWK ~ -0.05.
print("ceiling-heavy QWK:", quadratic_weighted_kappa([5] * 18 + [4, 5], [5] * 18 + [5, 4]))

# 2. Official MultiHop-RAG calculate_metrics (pinned c1c1287), loaded from a local copy.
spec = importlib.util.spec_from_file_location("official", sys.argv[1])
official = importlib.util.module_from_spec(spec); spec.loader.exec_module(official)

def paper_metrics_by_id(ranked_ids, gold_chunk_sets):
    """(PROPOSED) calculate_metrics over chunk IDs. gold_chunk_sets[q][i] = chunk IDs of evidence fact i."""
    h10 = h4 = 0; ap, rr = [], []
    for ranked, gold in zip(ranked_ids, gold_chunk_sets, strict=True):
        found, ap_sum, first = set(), 0.0, None
        for rank, cid in enumerate(ranked[:10], start=1):            # official: retrieved[:11] and rank <= 10
            if any(cid in s for s in gold):                           # relevant = holds ANY gold fact
                new = [i for i, s in enumerate(gold) if cid in s and i not in found]
                first = first or rank; found.update(new)
                ap_sum += len(new) / rank                             # NON-STANDARD: facts first found here / rank
        h10 += first is not None; h4 += first is not None and first <= 4
        ap.append(ap_sum / min(len(gold), 10)); rr.append(1 / first if first else 0)
    n = len(gold_chunk_sets)
    return {"Hits@10": h10 / n, "Hits@4": h4 / n, "MAP@10": sum(ap) / n, "MRR@10": sum(rr) / n}

# 3. Golden vectors: synthetic chunk texts -> the official function on text, ours on IDs.
rng, words, bad, trials, queries = random.Random(42), "alpha beta gamma delta eps zeta eta theta iota kappa lam mu".split(), 0, 0, 0
strip = lambda s: s.replace(" ", "").replace("\n", "")
for _ in range(500):
    chunks = {f"c{i}": " ".join(rng.choice(words) for _ in range(12)) for i in range(40)}
    R, T, G, I = [], [], [], []
    for _ in range(rng.randint(1, 6)):
        facts = []
        for _ in range(rng.randint(2, 4)):
            src = chunks[rng.choice(list(chunks))].split(); s = rng.randint(0, 8)
            facts.append(" ".join(src[s:s + rng.randint(3, 4)]))
        # The 500 sample has no duplicate fact and no fact inside another (checked); keep the generator honest.
        if len({strip(f) for f in facts}) < len(facts) or any(a != b and strip(a) in strip(b) for a in facts for b in facts):
            continue
        ranked = rng.sample(list(chunks), rng.randint(0, 14))
        R.append(ranked); T.append([chunks[c] for c in ranked]); G.append(facts)
        I.append([frozenset(c for c, t in chunks.items() if strip(f) in strip(t)) for f in facts])
    if R:
        a, b = official.calculate_metrics(T, G), paper_metrics_by_id(R, I)
        bad += any(abs(a[m] - b[m]) > 1e-12 for m in a); trials += 1; queries += len(R)
print(f"golden-vector: {trials} trials / {queries} queries evaluated, {bad} with mismatch")
