variable "db_url" {
  type    = string
  default = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable"
}

env "local" {
  src = "file://db/schema.hcl"
  url = var.db_url
  dev = "postgres://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable"
}
