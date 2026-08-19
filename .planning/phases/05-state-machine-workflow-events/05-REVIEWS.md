---
phase: 5
scope: gap-closure
reviewers: [antigravity]
successful_reviewers: [antigravity]
reviewed_at: 2026-08-18T18:00:00Z
plans_reviewed:
  - 05-25-PLAN.md
  - 05-26-PLAN.md
---

# Cross-AI Plan Review — Phase 05 Gap Closure (G-05-1)

Reviewed scope: the 2 pending gap-closure plans for UAT gap G-05-1 (05-25, 05-26). The
prior 05-REVIEWS.md content (covering plans 05-08 through 05-24, all now executed) was
superseded by this run and is not carried forward.

Only one reviewer lane was requested (`--agy`) and ran successfully: Antigravity. No
consensus synthesis across independent reviewers is possible with a single reviewer —
treat the findings below as one grounded, source-verified perspective, not adjudicated
consensus.

## Antigravity Review

### Plan 05-25: Rebuild/Reseed Stale LanceDB Store & Schema Drift Remediation Hint

**Summary:** Resolves Blocker A (stale 23-field local `nodes` table predating commit
`2302f79`) by backing up rather than deleting the existing store
(`data/lancedb.pre-05-25.bak`), reseeding via `seed_rag_fixture.rs`, and adding a
remediation hint to `validate_schema`'s fail-closed error in `engine/src/db/mod.rs`.

**Strengths:**
- Keeps `validate_schema` strict (`actual.fields() != expected.fields()` at
  `engine/src/db/mod.rs:161-174`) rather than adding a runtime auto-migration — preserves
  the Phase 02-03 fail-closed storage-integrity invariant while improving developer
  feedback.
- Renames instead of deletes the stale store, preventing accidental data loss.
- Extends `schema_drift_fails_database_initialization` (`engine/src/db/tests.rs:85-108`)
  to assert the remediation-guidance substring, not just the existing drift message.
- Verified the boot-check ordering in `engine/src/main.rs:3205-3291`:
  `DatabaseManager::initialize` (3205) runs before the `OPENROUTER_API_KEY` presence
  check (3212), which runs before the `"Rust RAG Engine serving"` log line (3291) — a
  dummy key is sufficient to reach the milestone log without a real OpenRouter call.

**Concerns:**
- **LOW** — The automated verify block (`05-25-PLAN.md:75-91`) mixes POSIX tooling
  (`mktemp`, `seq`, `kill`) with a hardcoded `./engine/target/debug/engine.exe` path.
  This matches the project's actual Windows dev environment (git-bash on win32) but is
  the only place in Phase 05's plans hardcoding the `.exe` suffix, so it would break if
  run verbatim on a POSIX runner.
- **LOW** — If `seed_rag_fixture` fails partway through a first run, a retry will find
  `data/lancedb.pre-05-25.bak` already present (so the rename is skipped) but the
  partially-seeded `data/lancedb` is left in place unless manually removed — the plan's
  own non-idempotence warning covers this, but Task 1's action doesn't add an automated
  cleanup step for it.

**Suggestions:**
- Make the verification block portable, or explicitly scope it to the project's Windows
  dev environment.
- Add an explicit clean-up step in Task 1 for the partial-reseed-plus-existing-backup
  case.

**Risk Assessment:** LOW — touches only a local disposable database fixture, one error
message, and one unit test; fully reversible.

### Plan 05-26: Decouple Gateway Real-Engine Integration Tests from `generation_model`

**Summary:** Resolves Blocker B (two gateway integration tests silently depending on
`config.toml`'s live `generation_model` value) by adding an explicit
`LANCET_OPENROUTER__GENERATION_MODEL` override to `engine/src/main.rs`'s
`load_settings()` and pinning both tests' spawned-engine env to the model string their
own httptest mocks already expect.

**Strengths:**
- Structural decoupling (env override) instead of continuously re-syncing the 5
  hardcoded mock call sites in `gateway/main_test.go:2074-2397` — makes both tests immune
  to future `config.toml` edits.
- Matches the existing boundary-override convention at `engine/src/main.rs:601-670`
  (`LANCET_OPENROUTER__EMBEDDING_ENDPOINT`, `MODEL_METADATA_ENDPOINT`, `CHAT_ENDPOINT`,
  etc.).
- Correctly extends the closed-set allowlist in `assertCleanRAGChildEnv`
  (`gateway/main_test.go:2779-2796`) rather than widening it loosely.
- The new `config_openrouter_generation_model_env_override_matches_contract` test
  correctly reuses the `ENV_MUTEX`-guarded save/restore pattern (`engine/src/tests.rs:259,
  311-352`) to avoid leaking env state across parallel tests.

**Concerns:**
- **LOW** — `LANCET_OPENROUTER__EMBEDDING_MODEL` is not given the same explicit-override
  treatment, so the same class of ambient-config coupling could reappear later if a test
  starts asserting on the embedding model. Not a current bug (no test asserts on it
  today), just an asymmetry worth noting.

**Suggestions:**
- Consider adding `LANCET_OPENROUTER__EMBEDDING_MODEL` to `load_settings()` and the
  allowlist in the same pass, for full override parity across OpenRouter model config
  keys.

**Risk Assessment:** LOW — targets the root cause directly, reuses well-tested patterns,
no production-path behavior change (the override is empty-string-guarded, matching its
siblings).

### Overall Assessment

| Plan | Target Gap | Scope | Dependency Ordering | Risk |
|---|---|---|---|---|
| 05-25 | G-05-1 Blocker A | Reseed local LanceDB store + validate_schema hint | Independent (Wave 1) | LOW |
| 05-26 | G-05-1 Blocker B | Explicit generation_model env override + test pin | Independent (Wave 1) | LOW |

Both plans are well-scoped, cite verified codebase mechanisms with `file:line` evidence,
preserve existing architectural invariants (fail-closed schema validation; explicit
boundary-override convention), and are independently landable. Together they unblock the
live end-to-end UAT run for Phase 05.

## Consensus Summary

Single-reviewer run — no cross-reviewer consensus to synthesize. Both concerns raised
are LOW severity and non-blocking:

1. Plan 05-25's boot-check verify block hardcodes a Windows-specific binary path
   (`engine.exe`) alongside POSIX shell tooling.
2. Plan 05-26 doesn't extend the same explicit-override treatment to
   `LANCET_OPENROUTER__EMBEDDING_MODEL`, leaving a parallel (currently dormant) coupling
   risk.

Neither concern blocks execution of either plan.
