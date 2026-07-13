variable "db_url" {
  type    = string
  default = "postgres://postgres:postgres@localhost:5432/lancet?sslmode=disable"
}

env "local" {
  src = "file://db/schema.sql"
  url = var.db_url
  dev = "docker://postgres/16/dev"
}
