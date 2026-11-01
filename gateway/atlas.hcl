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

variable "eval_full_db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_full"
}

variable "eval_2wiki_db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_2wiki"
}

variable "eval_full_merged_db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval_full_merged"
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

// #149: the hybrid-only stores of the exploratory runs B and C, each schema.eval.hcl renamed.
env "eval-full" {
  src = "file://db/schema.eval-full.hcl"
  url = var.eval_full_db_url
  dev = "postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"
}

env "eval-2wiki" {
  src = "file://db/schema.eval-2wiki.hcl"
  url = var.eval_2wiki_db_url
  dev = "postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"
}

// #146: the 609 MultiHop-RAG documents in merged chunks, schema.eval.hcl renamed.
env "eval-full-merged" {
  src = "file://db/schema.eval-full-merged.hcl"
  url = var.eval_full_merged_db_url
  dev = "postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"
}
