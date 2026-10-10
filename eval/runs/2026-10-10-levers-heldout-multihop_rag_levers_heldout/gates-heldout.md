# Unpark Gates (heldout)

## Gates

| Reading | hybrid | hybrid+graph | hybrid+rerank | hybrid+metadata | hybrid+answer-format | hybrid+graph-v2 | hybrid+all | pooled |
|---|---|---|---|---|---|---|---|---|
| SC-1 | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (2457) |
| SC-2 | PASS (351) | PASS (351) | MISS (351): arm hybrid+rerank: flatness decay_present; reported: RetrieveHybrid minus rerank.latency_ms flatness flat | PASS (351) | PASS (351) | PASS (351) | MISS (351): arm hybrid+all: flatness decay_present; reported: RetrieveHybrid minus rerank.latency_ms flatness flat | MISS (2457): flatness decay_present |

## Re-reported as a disclosure (not a gate)

| Reading | hybrid | hybrid+graph | hybrid+rerank | hybrid+metadata | hybrid+answer-format | hybrid+graph-v2 | hybrid+all | pooled |
|---|---|---|---|---|---|---|---|---|
| D-69 companion | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (2457) |

Retry provenance: header marker: gate_stage=heldout, max_retries=0

SC-3, SC-4, SC-5 are not computed for the heldout stage (not computed for the heldout stage (D-109): SC-3, SC-4 and SC-5 need the dev populations and the two-arm graph pairing, which the four-arm held-out drive does not carry).
