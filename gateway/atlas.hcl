variable "db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable"
}

variable "eval_db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval"
}

variable "eval_s1_db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_s1"
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

// D-251: the S1 store's schema. schema.eval-s1.hcl is schema.eval.hcl with the schema
// renamed to lancet_eval_s1, so both eval schemas get the same tables.
env "eval-s1" {
  src = "file://db/schema.eval-s1.hcl"
  url = var.eval_s1_db_url
  dev = "postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"
}
