## Deferred Items

- The eval full-suite command `uv run --project eval pytest`, run from the repo root, also collects `scripts/test_phase02_live_evidence.py`, whose test `test_wrong_model_is_rejected_in_optimized_isolated_subprocess` asserts `sys.flags.optimize == 1` ("the optimized test gate must run with -O") and fails under a plain `pytest` run (1 failed, 2200 passed). It is unrelated to plan 06.3.6-23 (no file it reads changed) and was found at plan 06.3.6-23 Task 1. Run it as the script's own gate does (`python -O`), or exclude `scripts/`, to read the suite as green.
  status: open
