schema "public" {
  comment = "public schema"
}

table "users" {
  schema = schema.public
  column "id" {
    null = false
    type = serial
  }
  column "username" {
    null = false
    type = varchar(255)
  }
  column "created_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  primary_key {
    columns = [column.id]
  }
  index "users_username_key" {
    unique  = true
    columns = [column.username]
  }
}

table "documents" {
  schema = schema.public
  column "id" {
    null = false
    type = varchar(255)
  }
  column "filename" {
    null = false
    type = varchar(255)
  }
  column "file_size" {
    null = false
    type = bigint
  }
  column "status" {
    null = false
    type = varchar(50)
  }
  column "chunk_count" {
    null = false
    type = integer
  }
  column "error_message" {
    null = true
    type = text
  }
  column "chunk_strategy" {
    null = false
    type = varchar(50)
  }
  column "chunk_size" {
    null = false
    type = integer
  }
  column "chunk_overlap" {
    null = false
    type = integer
  }
  column "created_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  column "updated_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  primary_key {
    columns = [column.id]
  }
}

table "document_reconciliation_intents" {
  schema = schema.public
  column "document_id" {
    null = false
    type = varchar(255)
  }
  column "desired_status" {
    null = false
    type = varchar(50)
  }
  column "reason_class" {
    null = false
    type = varchar(100)
  }
  column "retry_count" {
    null    = false
    type    = integer
    default = 0
  }
  column "next_attempt_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  column "last_error_class" {
    null = true
    type = varchar(100)
  }
  column "created_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  column "updated_at" {
    null    = false
    type    = timestamp
    default = sql("CURRENT_TIMESTAMP")
  }
  primary_key {
    columns = [column.document_id]
  }
  foreign_key "document_reconciliation_intents_document_id_fkey" {
    columns     = [column.document_id]
    ref_columns = [table.documents.column.id]
    on_delete   = CASCADE
  }
  check "check_desired_status" {
    expr = "desired_status::text = 'failed'::text"
  }
  check "check_retry_count" {
    expr = "retry_count >= 0"
  }
}

