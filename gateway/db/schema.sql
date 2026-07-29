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

-- Create "document_reconciliation_intents" table
CREATE TABLE "public"."document_reconciliation_intents" (
  "document_id" character varying(255) NOT NULL,
  "desired_status" character varying(50) NOT NULL,
  "reason_class" character varying(100) NOT NULL,
  "retry_count" integer NOT NULL DEFAULT 0,
  "next_attempt_at" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "last_error_class" character varying(100) NULL,
  "created_at" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY ("document_id"),
  CONSTRAINT "document_reconciliation_intents_document_id_fkey" FOREIGN KEY ("document_id") REFERENCES "public"."documents" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "check_desired_status" CHECK ((desired_status)::text = 'failed'::text),
  CONSTRAINT "check_retry_count" CHECK (retry_count >= 0)
);

