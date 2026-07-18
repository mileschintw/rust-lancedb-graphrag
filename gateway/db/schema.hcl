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
