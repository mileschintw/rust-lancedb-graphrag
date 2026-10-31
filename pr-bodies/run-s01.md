## Summary

Records v1.1 S0, the external LlamaIndex comparison on the held-out split (held-out read 1 of 2, D-237), and fills
`EXPERIMENT-S0.md › Result`.

**Reading: no significant difference.** `llamaindex` minus `hybrid+rerank+metadata` on `answer_usable` is -0.34
points, 95% CI [-5.05, +4.38], raw p = Holm p = 1.0. Coverage is 297 of 308 G questions (0.964). The null guard
passes in both directions (42 pairs, b = 0, c = 1).

- `eval/runs/2026-10-31-s0-multihop_rag_s0_heldout/`: the run of record. It holds the journal (351 Lancet + 351
  `llamaindex` records, all `success`), both context exports, the LlamaIndex `pipeline_config.json`, `report.json`,
  `lever-comparison.{json,md}` and `raw_events/`. It was driven on `main` at `c69d4868`, following `RUN-S0-S1.md`
  step 3.
- `experiments/v1.1/EXPERIMENT-S0.md`: the Result section. Nothing above it changes.
- `eval/tests/test_journal.py`: the committed-journal test exempted only `-levers-` sessions from its no-levers
  assertions. It now exempts `-s0-` and `-s1-` run directories too, which drive lever arms by design. Without this,
  committing the S0 run fails the eval suite, and S1's run would fail it too.

**Caveat for the reader.** The rerank tripwire (D-262) stopped the first drive segment at 50 attempts with 12
rerank `timeout` degrades. The cause was local search latency under load from concurrent builds; the provider's rerank
calls were fast. With the other lanes paused, the drive resumed into the same journal and finished the last 301
questions with 0 degrades. The degraded records were not re-driven. `compare-levers` excluded 11 of them as reference
provenance, which is why 297 of 308 pairs are compared.

Every `lancet-eval` command ran with `PYTHONUTF8=1` to work around #84. Observed spend was $1.01, plus about $0.25
estimated for the LlamaIndex export, which prints no cost.

Closes: none

Refs #84
Refs #75

## Review

- Self-review of the diff, inline; the `code-review` skill was not run, since the change is a docs section, run data
  and a 3-line test exemption. Every number in the Result section was checked against `lever-comparison.json`. The
  pushed run directory was compared with the original by sha256: 31 of 33 files match byte for byte, and
  `journal.jsonl` and `report.json` match after CRLF-to-LF normalisation (`core.autocrlf=true`). The run dir was
  scanned for API keys and none were found.
- The eval fast tier on the branch head reported `2786 passed, 8 skipped`. Before the test fix, the one failure was
  `test_every_committed_journal_parses_with_the_new_defaulted_fields`, which the exemption above resolves.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
