# Unpark Gates (heldout)

## Gates

| Reading | dense-only | bm25-only | hybrid | hybrid+graph | pooled |
|---|---|---|---|---|---|
| SC-1 | PASS (351) | PASS (351) | PASS (351) | PASS (351) | PASS (1404) |
| SC-2 | MISS (351): arm dense-only: timeout is a dominant error class (tied or plurality): {'timeout': 4, 'other': 1} | PASS (351) | MISS (351): arm hybrid: timeout is a dominant error class (tied or plurality): {'timeout': 6} | MISS (351): arm hybrid+graph: timeout is a dominant error class (tied or plurality): {'timeout': 2} | MISS (1404): timeout is a dominant error class (tied or plurality): {'timeout': 12, 'other': 1} |

## Re-reported as a disclosure (not a gate)

| Reading | dense-only | bm25-only | hybrid | hybrid+graph | pooled |
|---|---|---|---|---|---|
| D-69 companion | PASS (347) | PASS (351) | PASS (345) | PASS (349) | PASS (1392) |

Retry provenance: header marker: gate_stage=heldout, max_retries=0

SC-3, SC-4, SC-5 are not computed for the heldout stage (not computed for the heldout stage (D-109): SC-3, SC-4 and SC-5 need the dev populations and the two-arm graph pairing, which the four-arm held-out drive does not carry).
