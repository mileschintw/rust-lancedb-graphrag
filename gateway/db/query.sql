-- name: GetUser :one
SELECT * FROM users
WHERE id = $1 LIMIT 1;

-- name: CreateUser :one
INSERT INTO users (username)
VALUES ($1)
RETURNING *;

-- name: InsertDocument :one
INSERT INTO documents (
  id,
  filename,
  file_size,
  status,
  chunk_count,
  chunk_strategy,
  chunk_size,
  chunk_overlap
) VALUES (
  $1,
  $2,
  $3,
  'queued',
  0,
  $4,
  $5,
  $6
)
RETURNING *;

-- name: UpdateDocumentStatus :one
UPDATE documents
SET
  status = $2,
  chunk_count = $3,
  error_message = $4,
  updated_at = CURRENT_TIMESTAMP
WHERE id = $1
  AND status IN ('queued', 'processing')
RETURNING *;

-- name: GetDocument :one
SELECT * FROM documents
WHERE id = $1
LIMIT 1;

-- name: CreateReconciliationIntent :one
INSERT INTO document_reconciliation_intents (
  document_id,
  desired_status,
  reason_class,
  retry_count,
  next_attempt_at,
  last_error_class,
  created_at,
  updated_at
)
SELECT
  d.id,
  $2,
  $3,
  0,
  CURRENT_TIMESTAMP,
  NULL,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
FROM documents d
WHERE d.id = $1 AND d.status = 'queued'
ON CONFLICT (document_id) DO UPDATE
SET
  desired_status = EXCLUDED.desired_status,
  reason_class = EXCLUDED.reason_class,
  updated_at = CURRENT_TIMESTAMP
RETURNING *;

-- name: ClaimDueReconciliationIntents :many
WITH due AS (
  SELECT document_id
  FROM document_reconciliation_intents
  WHERE next_attempt_at <= CURRENT_TIMESTAMP
  ORDER BY next_attempt_at ASC
  LIMIT $1
  FOR UPDATE SKIP LOCKED
)
UPDATE document_reconciliation_intents dri
SET
  next_attempt_at = $2,
  updated_at = CURRENT_TIMESTAMP
FROM due
WHERE dri.document_id = due.document_id
RETURNING dri.*;

-- name: RescheduleReconciliationIntent :one
UPDATE document_reconciliation_intents
SET
  retry_count = retry_count + 1,
  next_attempt_at = $2,
  last_error_class = $3,
  updated_at = CURRENT_TIMESTAMP
WHERE document_id = $1
RETURNING *;

-- name: DeleteReconciliationIntent :execresult
DELETE FROM document_reconciliation_intents dri
USING documents d
WHERE dri.document_id = d.id
  AND dri.document_id = $1
  AND d.status IN ('completed', 'failed');

-- name: GetReconciliationIntent :one
SELECT * FROM document_reconciliation_intents
WHERE document_id = $1
LIMIT 1;

