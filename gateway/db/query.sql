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
RETURNING *;

-- name: GetDocument :one
SELECT * FROM documents
WHERE id = $1
LIMIT 1;
