variable "db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable"
}

variable "eval_db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval"
}

env "local" {
  src = "file://db/schema.hcl"
  url = var.db_url
  dev = "postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"
}

// Branch 3: generated schema.eval.hcl rewriting schema to lancet_eval
// Probe A demonstrated that Atlas rejects search_path scoped URLs when the HCL declares 'schema "public"'
env "eval" {
  src = "file://db/schema.eval.hcl"
  url = var.eval_db_url
  dev = "postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"
}
