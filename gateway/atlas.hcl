variable "db_url" {
  type    = string
  default = "postgres://postgres:postgres@localhost:5432/lancet?sslmode=disable"
}

env "local" {
  src = "file://db/schema.hcl"
  url = var.db_url
  dev = "postgres://postgres:postgres@localhost:5432/postgres?sslmode=disable"
}
