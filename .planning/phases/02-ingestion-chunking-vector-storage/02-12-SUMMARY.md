# Plan 02-12 Summary: Live Tooling Freshness, Ownership & Ignores

Completed the implementation of maximum challenge age and complete-run window enforcement in live evidence tools, caller-owned sample preservation in `verify-ingestion.sh`, and root-anchored build ignores in `.gitignore`.

## Changes Made

- **`scripts/phase02_live_evidence.py`**:
  - Added `MAX_CHALLENGE_AGE` (30m) and `MAX_RUN_WINDOW` (35m) constants.
  - Enforced `MAX_CHALLENGE_AGE` in `validate_challenge` so any challenge older than 30 minutes is rejected.
  - Enforced `MAX_RUN_WINDOW` in `validate_evidence` and `build_evidence` to bound the total elapsed duration from challenge issuance to evidence generation.

- **`scripts/test_phase02_live_evidence.py`**:
  - Added test cases for stale challenge and overlong run durations under optimized isolated Python (`PYTHONOPTIMIZE=1` with `python -O -I`).
  - Added `test_caller_sample_preservation_on_early_failure` to verify caller-owned samples are preserved byte-for-byte during early script failures.

- **`verify-ingestion.sh`**:
  - Introduced explicit `sample_owned` flag. Set to `true` only when the script creates a temporary sample file.
  - Updated `cleanup()` to remove `$sample_file` only when `sample_owned` is true, ensuring caller-supplied input files are never deleted on failure.

- **`.gitignore`**:
  - Anchored `bin/` to `/bin/` to prevent nested Rust binaries under `engine/src/bin` from being mistakenly ignored by Git (WR-03).

## Verification

- Ran `$env:PYTHONOPTIMIZE='1'; python -O -I scripts/test_phase02_live_evidence.py`: 6 tests PASS.
- Ran `bash -n verify-ingestion.sh`: PASS.
- Ran `git check-ignore` probes for `/bin/placeholder` (matched) and `engine/src/bin/future_inspector.rs` (not matched): PASS.
