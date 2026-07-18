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
-- Create "documents" table
CREATE TABLE "public"."documents" (
  "id" character varying(255) NOT NULL,
  "filename" character varying(255) NOT NULL,
  "file_size" bigint NOT NULL,
  "status" character varying(50) NOT NULL,
  "chunk_count" integer NOT NULL,
  "error_message" text NULL,
  "chunk_strategy" character varying(50) NOT NULL,
  "chunk_size" integer NOT NULL,
  "chunk_overlap" integer NOT NULL,
  "created_at" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY ("id")
);
