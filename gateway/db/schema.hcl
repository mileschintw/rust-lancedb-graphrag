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
