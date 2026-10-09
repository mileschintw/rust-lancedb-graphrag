"""D-86 / D-154 / D-155 stage-cap arithmetic for 06.3.6-AI-SPEC.md sections 5-6.

Written by the 06.3.6 eval-planner, 2026-10-09. Offline, read-only, no network, no paid call.

    PYTHONUTF8=1 uv run --project eval python -I \
      .planning/phases/06.3.6-.../research/cost_caps_06_3_6.py > .../research/cost_caps_06_3_6.out

D-129: the 06.3.5 held-out figures used here are COST figures only (token totals and spend from
`06.3.5-DRIVE.md` "Spend against the cap"), which the orchestrator allowed for cost. No quality
number is read. The per-record maximum comes from the DEV drive-2 journal.

`run.py` enforces `--stage-cap` against `measure.compute_spend` (run.py:508-587), the harness
estimate, NOT the account delta. So every cap below is in harness-estimate dollars, and is shown
under both values of the open price question (GENERATION_OUTPUT_PRICE_PER_1M 0.32 today, 1.28 if
raised to today's listing, AI-SPEC section 4 item 7f).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from lancet_eval import measure
from lancet_eval.journal import load_records

REPO = Path(__file__).resolve().parents[4]
DRIVE2 = REPO / "eval/runs/2026-10-06-drive2-multihop_rag_diag/journal.jsonl"

# 06.3.5-DRIVE.md "Spend against the cap" (cost only).
H_RECORDS = 1404
H_PROMPT = 3_185_955
H_COMPLETION = 404_899
H_HARNESS = 0.59762
H_ACCOUNT = 0.234784
H_ARM = {"dense-only": 0.14839, "bm25-only": 0.14707, "hybrid": 0.14638, "hybrid+graph": 0.15578}

IN = measure.GENERATION_INPUT_PRICE_PER_1M  # 0.14
OUT_NOW = measure.GENERATION_OUTPUT_PRICE_PER_1M  # 0.32
OUT_RAISED = 1.28  # today's listing, section 4 item 7f (owner question 6)
EMB = measure.EMBEDDING_PRICE_PER_1M * measure.ESTIMATED_EMBEDDING_TOKENS_PER_QUERY / 1e6
FAIL_IN = measure.FAILED_GENERATION_PROMPT_TOKENS
FAIL_OUT = measure.FAILED_GENERATION_COMPLETION_TOKENS

METADATA_TOKENS = 700  # section 4 item 4c: ASSUMED worst case per record (8 blocks x ~85 tokens)
RERANK_CALL_ILLUSTRATIVE = 0.00035  # section 4b: IF billed like Voyage direct; NOT verified


def per_record(prompt: float, completion: float, out_price: float) -> float:
    return prompt * IN / 1e6 + completion * out_price / 1e6 + EMB


def fail_ceiling(out_price: float) -> float:
    return FAIL_IN * IN / 1e6 + FAIL_OUT * out_price / 1e6


def record_cost(rec, out_price: float) -> float:
    total = 0.0
    for att in [*rec.prior_attempts, rec]:
        wm = att.workflow_meta
        if wm is not None:
            total += wm.prompt_tokens * IN / 1e6 + wm.completion_tokens * out_price / 1e6
        total += EMB
    total += measure.count_failed_generation_attempts([rec]) * fail_ceiling(out_price)
    return total


def main() -> None:
    p_tok = H_PROMPT / H_RECORDS
    c_tok = H_COMPLETION / H_RECORDS
    print("== 06.3.5 held-out drive, cost inputs (06.3.5-DRIVE.md)")
    print(f"tokens per record: prompt {p_tok:.1f}, completion {c_tok:.1f}")
    base_now = per_record(p_tok, c_tok, OUT_NOW)
    recon = base_now * H_RECORDS + fail_ceiling(OUT_NOW)
    print(f"harness per record at drive-time constants: ${base_now:.6f} "
          f"(x1404 + one failed-generation ceiling = ${recon:.5f}; recorded ${H_HARNESS})")
    print(f"account per record: ${H_ACCOUNT / H_RECORDS:.6f} (disclosure; the cap does not read it)")
    graph_delta_usd = (H_ARM["hybrid+graph"] - H_ARM["hybrid"]) / 351
    graph_delta_tokens = graph_delta_usd / (IN / 1e6)
    print(f"graph-on arm extra per record: ${graph_delta_usd:.7f} ~ {graph_delta_tokens:.0f} prompt tokens")

    print()
    print("== Dev drive-2 per-record harness cost (D-129: dev), for the all-max case")
    recs = load_records(DRIVE2)
    for out in (OUT_NOW, OUT_RAISED):
        costs = sorted(record_cost(r, out) for r in recs)
        n = len(costs)
        print(f"  out ${out}/1M: n={n} mean ${sum(costs) / n:.6f} p99 ${costs[math.ceil(0.99 * n) - 1]:.6f} "
              f"max ${costs[-1]:.6f}; failed-generation ceiling ${fail_ceiling(out):.6f}")

    for out, label in ((OUT_NOW, "constants as today (out 0.32)"), (OUT_RAISED, "output raised to 1.28")):
        print()
        print(f"== Estimates, {label}")
        base = per_record(p_tok, c_tok, out)
        ceiling = fail_ceiling(out)
        dev_max = max(record_cost(r, out) for r in recs)
        per_max = max(dev_max, ceiling)
        for arms, graph_on_arms, meta_arms, rerank_arms in ((7, 3, 2, 2), (6, 2, 2, 2)):
            n = arms * 351
            gen = n * base
            meta = meta_arms * 351 * METADATA_TOKENS * IN / 1e6
            graph = graph_on_arms * 351 * graph_delta_tokens * IN / 1e6
            rerank = rerank_arms * 351 * RERANK_CALL_ILLUSTRATIVE
            reserve = math.ceil(0.01 * n) * ceiling
            mean = gen + meta + graph + rerank + reserve
            allmax = n * per_max + meta + rerank
            print(f"  drive {arms} arms = {n} records: generation ${gen:.2f} + metadata ${meta:.3f} + "
                  f"graph ${graph:.3f} + rerank (illustrative) ${rerank:.3f} + 1% failed-ceiling reserve "
                  f"${reserve:.3f} = ${mean:.2f}; all-max (every record at max(dev max, failed ceiling) "
                  f"${per_max:.5f}) ${allmax:.2f}")
        # Dev blanket (D-154): session 1 = hybrid + 4 lever arms + hybrid+graph control;
        # session 2 = hybrid + up to 4 revised lever arms. 100 dev questions each.
        dev_records = (1 + 4 + 1) * 100 + (1 + 4) * 100
        dev_meta = 2 * 100 * METADATA_TOKENS * IN / 1e6
        dev_rerank = 2 * 100 * RERANK_CALL_ILLUSTRATIVE
        dev_mean = dev_records * base + dev_meta + dev_rerank + math.ceil(0.01 * dev_records) * ceiling
        dev_allmax = dev_records * per_max + dev_meta + dev_rerank
        print(f"  dev blanket <= {dev_records} records: mean ${dev_mean:.2f}; all-max ${dev_allmax:.2f}; "
              f"one 100-record lever read ~ ${100 * base:.3f}")
        reh = 3 * 7 + 3 * 7  # rehearsal questions x arms + arm canaries x arms
        print(f"  rehearsal {reh} queries (+ the probe): mean ${reh * base:.3f}; all-max ${reh * per_max:.3f}")
    print(json.dumps({"cost_caps": "ok"}))


if __name__ == "__main__":
    main()
