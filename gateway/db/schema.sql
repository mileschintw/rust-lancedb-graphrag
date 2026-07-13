-- Add new schema named "public"
CREATE SCHEMA IF NOT EXISTS "public";
-- Set comment to schema: "public"
COMMENT ON SCHEMA "public" IS 'public schema';
-- Create "users" table
CREATE TABLE "public"."users" (
  "id" serial NOT NULL,
  "username" character varying(255) NOT NULL,
  "created_at" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY ("id")
);
-- Create index "users_username_key" to table: "users"
CREATE UNIQUE INDEX "users_username_key" ON "public"."users" ("username");
