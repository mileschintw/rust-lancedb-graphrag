# Plan 02-11 Summary: Gateway Admission & Eventual Reconciliation

Completed the implementation of typed admission outcomes, authoritative ambiguity resolution, retrying terminal compensation, engine NotFound repair, and gRPC response identity verification in the gateway API.

## Changes Made

- **`gateway/main.go`**:
  - Introduced `IngestOutcome` struct returned by `engine.Ingest` to distinguish ambiguous transport errors (e.g. lost `CloseAndRecv`) from definitive rejections.
  - Implemented authoritative admission resolution in `createDocument`: when `Ingest` returns an ambiguous result, `IngestionStatus` is queried under a fresh detached context. Admitted jobs (queued/processing/completed/failed) return HTTP 202 without writing a failed state to PostgreSQL.
  - Implemented retrying reconciliation in `compensateFailedIngest`: uses finite per-attempt contexts, exponential backoff via an injectable seam, and handles concurrent terminal race winners.
  - Implemented gRPC NotFound repair in `getDocument`: when polling a queued or processing document yields `codes.NotFound`, it repairs the row to `failed` and returns HTTP 200 with the repaired document.
  - Implemented `DocumentId` identity validation on `IngestionStatus` responses per WR-02.

- **`gateway/main_test.go`**:
  - Added unit test `TestCreateDocumentConvergesLostAcknowledgement` proving lost final ACKs converge to HTTP 202 without compensation failure.
  - Added unit test `TestCreateDocumentRejectsMismatchedAdmissionIdentity` and `TestGetDocumentRejectsMismatchedStatusIdentity`.
  - Added unit test `TestCompensationRetriesUntilTerminalConvergence` and `TestCompensationAcceptsTerminalRaceWinner`.
  - Added unit test `TestGetDocumentRepairsAuthoritativeEngineNotFound` and `TestGetDocumentLeavesTransientEngineFailureQueued`.

## Verification

- Ran `go test -count=1 ./...` in `gateway`: PASS.
- Ran `go vet ./...` in `gateway`: PASS.
