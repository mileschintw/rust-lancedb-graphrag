# Deferred Items

- **Pre-existing formatting debt (out of scope for 05-21):** `cargo fmt --manifest-path engine/Cargo.toml -- --check` reports baseline formatting differences across unrelated engine files. No formatting-only changes were made outside the two planned retrieval files.
- **Pre-existing binary dead-code warnings (out of scope for 05-21):** `cargo check --bin engine --manifest-path engine/Cargo.toml --locked` passes while warning that `d1_status` and `AttemptedAndFailed::reason` are unused in `engine/src/main.rs`. The warnings are unrelated to typed fusion provenance and were not changed.
