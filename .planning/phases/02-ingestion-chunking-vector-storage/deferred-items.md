# Deferred Items

## Pre-existing production stubs found during the 02-07 audit

- `engine/src/main.rs:329-330`: `query_rag` still returns a placeholder answer and empty citations. This predates 02-07 and belongs to the Phase 03 RAG implementation; it does not affect replacement rollback, retry convergence, or failed-ingest compensation.
- `engine/src/main.rs:340`: `query_graph` still returns a scaffolding status payload. This predates 02-07 and belongs to the Phase 04 graph-query implementation; it does not affect replacement rollback, retry convergence, or failed-ingest compensation.

## Accepted Phase 02 verification debt

Source of record for every item below: accepted ADR `.discussion/decisions/phase-02-verification-disposition.md` (2026-07-29). These records override the older blocker disposition in `02-REVIEW.md` and `02-VERIFICATION.md`. They are non-blocking for Phase 02 only while their triggers remain false.

### DEBT-CR-04 — Network authentication, authorization, TLS, and quotas

- **ADR rationale:** Lancet is presently a personal, trusted, local-first side project; internet-facing access control and transport complexity are outside the current runtime boundary.
- **Known risk:** A network-reachable caller could submit content using the service's private embedding-provider credential and consume local storage or provider quota; plaintext HTTP would expose traffic.
- **Current constraints:** The Phase 02 guardrail binds the gateway explicitly to loopback. Do not use a reverse proxy, tunnel, port-forward, container/VM/cloud ingress, non-loopback bind, shared user, external process, or remote caller.
- **Trigger:** Any shared, network, remote, public, multi-user, container-ingress, VM, cloud, tunnel, proxy, or external-caller deployment.
- **Target:** Before the trigger; if still untriggered, review at Phase 6 / v1 MVP closure.
- **Future acceptance criteria:** Ingestion requires authentication and authorization; ingress uses TLS; request-rate and per-principal ingestion/storage/provider quotas exist; unauthorized/over-quota callers are behaviorally proven unable to consume provider or durable-storage resources.

### DEBT-CR-05 — Resource bounds before queue admission

- **ADR rationale:** Hostile slow clients and concurrent upload pressure are outside the present trusted single-user loopback threat model.
- **Known risk:** Accidental parallel or large local uploads can consume memory or hold connections before the Rust queue accounts for them.
- **Current constraints:** One trusted local user; loopback only; manual ingestion; no intentional bulk, scheduled, concurrent, or automated ingestion; inputs stay within current intended local limits.
- **Trigger:** External/shared access, background bulk ingestion, scheduled/automated/concurrent ingestion, or larger/uncontrolled uploads.
- **Target:** Before the trigger; if still untriggered, review at Phase 6 / v1 MVP closure.
- **Future acceptance criteria:** Gateway `ReadTimeout`, `WriteTimeout`, and `IdleTimeout`; a bounded upload semaphore acquired before multipart body reads; Rust admission capacity reserved or accounted before full buffering; slow-body, concurrent-stream, permit-release, and memory-bound tests pass.

### DEBT-BU-01 — Complete run-window behavioral proof

- **ADR rationale:** The unproven exact duration branch affects live-evidence rigor, not normal local ingestion or durable indexing; current freshness and identity checks retain partial protection.
- **Known risk:** An overlong evidence run may not be rejected for the intended complete-run-window reason.
- **Current constraints:** Do not describe the live-evidence gate as fully verified release/audit evidence.
- **Trigger:** The live gate becomes release criteria, CI release criteria, public/shared-deployment evidence, or external-audit evidence.
- **Target:** Phase 6 / v1 MVP closure.
- **Future acceptance criteria:** Use a controlled clock; keep challenge/evidence identity and issue times matching; exceed only `issued_at` to `generated_at`; assert the dedicated complete-run-window error classification.

### DEBT-BU-02 — Caller-owned input preservation across all paths

- **ADR rationale:** The destructive ownership bug is fixed; exhaustive live-success and representative failure-path proof requires broader provider/service state than current local iteration needs.
- **Known risk:** A future shell change could delete an irreplaceable caller-owned input on an untested path.
- **Current constraints:** Never pass the only copy of an important document; use a copied fixture, version-controlled sample, or script-created temporary input.
- **Trigger:** Before documenting the live runner as safe for arbitrary user-owned source files.
- **Target:** Phase 6 / v1 MVP closure.
- **Future acceptance criteria:** Successful plus representative early and post-upload failures preserve caller fixture SHA-256 and bytes; script-created temporary files are removed only when owned by the script.
