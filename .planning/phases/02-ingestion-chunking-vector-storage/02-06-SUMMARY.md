---
phase: 02-ingestion-chunking-vector-storage
plan: 06
subsystem: testing
tags: [openrouter, lancedb, postgresql, live-verification, replay-resistance]

requires:
  - phase: 02-ingestion-chunking-vector-storage
    provides: ingestion pipeline, integrity-hardened LanceDB schemas, and live evidence tooling from Plans 02-01 through 02-05
provides:
  - Challenge-bound proof of a new production OpenRouter ingestion run
  - Direct PostgreSQL and isolated LanceDB reconciliation evidence
  - Dedicated verification-store configuration isolated from local development data
affects: [phase-03-hybrid-retrieval, ingestion-verification, local-development]

tech-stack:
  added: []
  patterns: [single-use challenge provenance, isolated live-verification store, direct dual-store reconciliation]

key-files:
  created:
    - config/config.verify.toml
  modified:
    - .gitignore
    - verify-ingestion.sh
    - verify-live-evidence.sh

key-decisions:
  - "Run the final live gate against a dedicated verification LanceDB store so pre-existing schema generations cannot influence acceptance."
  - "Preserve only the fresh validated run as the canonical local verification dataset; remove all stale Phase 02 rows, old LanceDB files, challenges, and evidence artifacts."

patterns-established:
  - "Credentialed live gates use synthetic input, sanitized evidence, exact challenge provenance, and independent durable-store reinspection."
  - "Live verification selects a committed environment overlay rather than sharing the default embedded database path."

requirements-completed: [DATA-01, DATA-02, DATA-03, DATA-06, DATA-07, DATA-08, RAG-06]

coverage:
  - id: D1
    description: "A new production OpenRouter-backed upload completed through the Go gateway and Rust worker."
    requirement: DATA-01
    verification:
      - kind: e2e
        ref: "verify-ingestion.sh --managed-services with a freshly issued challenge"
        status: pass
    human_judgment: false
  - id: D2
    description: "PostgreSQL and isolated LanceDB agreed on completed status, positive chunk counts, canonical/staging rows, model, provider, and vector width."
    requirement: DATA-03
    verification:
      - kind: integration
        ref: "verify-live-evidence.sh --validate-gate direct store reinspection"
        status: pass
    human_judgment: false
  - id: D3
    description: "Replay-resistant evidence matched the exact challenge and the challenge was consumed only after successful validation."
    requirement: RAG-06
    verification:
      - kind: other
        ref: "verify-live-evidence.sh --validate-gate provenance and freshness checks"
        status: pass
    human_judgment: false

duration: 2h 24m
completed: 2026-07-25
status: complete
---

# Phase 2 Plan 6: Live Final-Pass Gate Summary

**A fresh OpenRouter-backed ingestion run completed against an isolated LanceDB store and passed challenge-bound PostgreSQL/LanceDB reconciliation.**

## Performance

- **Duration:** 2h 24m
- **Started:** 2026-07-25T20:39:02Z
- **Completed:** 2026-07-25T23:02:50Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Issued a fresh unpredictable single-use challenge immediately before the credentialed live run and accepted only exact, fresh, sanitized evidence.
- Completed one production OpenRouter ingestion with provider `openrouter`, model `nvidia/llama-nemotron-embed-vl-1b-v2:free`, and 2048-wide persisted embeddings.
- Directly reconciled the completed PostgreSQL row with one canonical LanceDB document, zero staged documents, two nodes, one edge, and no duplicate or stale generation.
- Removed stale Phase 02 PostgreSQL document rows and the old configured LanceDB files, then retained the fresh isolated store as the canonical verification dataset.
- Consumed the challenge on successful validation and removed the short-lived evidence artifact.

## Task Commits

1. **Task 1: Prepare a single-use live-gate challenge** — `49e363a`, `f912675`, `1d2d11d`, `14b7f7b`, `be34e80`, `7119948`, `490809a` (gate hardening and Windows managed-service fixes)
2. **Task 2: Run one private credential-dependent OpenRouter ingestion command** — execution-only; runtime artifacts were intentionally not committed
3. **Task 3: Validate exact challenge provenance and current live store state** — execution-only; validator passed and consumed the challenge

## Files Created/Modified

- `config/config.verify.toml` - Pins live verification to `./data/lancedb-verify-02-06`.
- `.gitignore` - Excludes the isolated store and scoped cleanup quarantine from Git.
- `verify-ingestion.sh` - Runs managed services under the verification environment.
- `verify-live-evidence.sh` - Reinspects the same isolated verification environment.

## Decisions Made

- Used a separate isolated verification LanceDB store because the pre-existing default store contained an older incompatible edge schema.
- Cleared only the Lancet `public.documents` rows and exact repository-contained LanceDB storage targets; schemas, users, containers, Docker volumes, and unrelated resources were preserved.
- Kept the fresh validated run as canonical local verification data while removing stale stores and all short-lived provenance artifacts.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Hardened the live evidence gate for Windows managed execution**
- **Found during:** Tasks 1-2
- **Issue:** Strict evidence handling, existing PostgreSQL schema reuse, managed binary selection, gateway module launch, Windows-readable upload paths, and engine readiness were required for a bounded live run.
- **Fix:** Hardened the scripts across the continuation commits listed above.
- **Files modified:** `verify-ingestion.sh`, `verify-live-evidence.sh`
- **Verification:** Script self-test, Git Bash syntax checks, successful managed live run, and final validator pass.
- **Committed in:** `49e363a`, `f912675`, `1d2d11d`, `14b7f7b`, `be34e80`, `7119948`

**2. [Rule 3 - Blocking] Isolated verification from stale LanceDB schema generations**
- **Found during:** Task 2
- **Issue:** The default LanceDB store contained pre-02-05 non-nullable edge summary fields, and the engine correctly refused schema drift.
- **Fix:** Added a dedicated `verify` overlay and pinned both live ingestion and final inspection to a newly created isolated store.
- **Files modified:** `config/config.verify.toml`, `.gitignore`, `verify-ingestion.sh`, `verify-live-evidence.sh`
- **Verification:** Empty-store overlay resolution, successful OpenRouter run, and direct final store reinspection.
- **Committed in:** `490809a`

---

**Total deviations:** 2 auto-fixed blocking issues
**Impact on plan:** The fixes preserved the planned production path and evidence contract while preventing stale local data from producing false failures or false acceptance.

## Issues Encountered

- The Windows `bash` command resolved to the unavailable WSL launcher; the installed Git Bash executable was selected explicitly and syntax-checked before live execution.
- A root-level `go test ./...` invocation was outside the Go module; the correct `go -C gateway test ./...` command passed.

## Verification

- Rust: 21 engine tests and 4 inspector-linked tests passed.
- Go: gateway and database packages passed; generated protobuf package has no tests.
- Live gate: managed OpenRouter ingestion reported success.
- Final validator: exact challenge provenance, freshness, PostgreSQL state, and isolated LanceDB state passed.
- Cleanup: application ports 8080 and 50051 were clear; PostgreSQL was stopped; challenge and evidence files were absent.

## User Setup Required

None - the inherited private OpenRouter credential was used without printing, inspecting, persisting, or committing it.

## Next Phase Readiness

- Phase 2 ingestion, chunking, storage integrity, and live-provider verification are complete.
- The isolated canonical dataset is ready for Phase 3 retrieval work.
- No blockers remain.

## Self-Check: PASSED

- Summary key files and all seven Plan 02-06 implementation commits exist.
- Runtime challenge and evidence artifacts are absent and untracked.
- The validated isolated LanceDB dataset remains present; the stale default LanceDB store is absent.

---
*Phase: 02-ingestion-chunking-vector-storage*
*Completed: 2026-07-25*
