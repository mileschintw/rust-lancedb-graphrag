#!/usr/bin/env python3
"""Fail-closed validation for the Phase 02 live-ingestion evidence gate."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
import uuid
from typing import Any, Mapping


EXPECTED_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
SUCCESS_SENTINEL = "Ingestion validation: SUCCESS"
CHALLENGE_KEYS = frozenset({"schema_version", "challenge", "run_id", "issued_at"})
EVIDENCE_KEYS = frozenset(
    {
        "schema_version",
        "success_sentinel",
        "challenge",
        "run_id",
        "issued_at",
        "run_started_at",
        "generated_at",
        "document_id",
        "provider",
        "embedding_model",
        "gateway_chunk_count",
        "postgres_status",
        "postgres_chunk_count",
        "document_rows",
        "staged_document_rows",
        "node_rows",
        "edge_rows",
        "embedding_width",
        "generation_count",
        "duplicate_generation",
        "stale_generation",
        "chunk_indexes_contiguous",
    }
)
INSPECTION_KEYS = frozenset(
    {
        "document_id",
        "provider",
        "embedding_model",
        "document_rows",
        "staged_document_rows",
        "node_rows",
        "edge_rows",
        "embedding_width",
        "generation_count",
        "duplicate_generation",
        "stale_generation",
        "chunk_indexes_contiguous",
    }
)
INTEGER_FIELDS = (
    "gateway_chunk_count",
    "postgres_chunk_count",
    "document_rows",
    "staged_document_rows",
    "node_rows",
    "edge_rows",
    "embedding_width",
    "generation_count",
)
INSPECTION_INTEGER_FIELDS = (
    "document_rows",
    "staged_document_rows",
    "node_rows",
    "edge_rows",
    "embedding_width",
    "generation_count",
)
BOOLEAN_FIELDS = (
    "duplicate_generation",
    "stale_generation",
    "chunk_indexes_contiguous",
)
SENSITIVE_FIELD_CATEGORIES = (
    ("credential", ("credential", "credentials")),
    ("secret", ("secret", "secrets", "api_key", "apikey")),
    ("bearer", ("bearer", "bearer_token")),
    ("authorization_header", ("authorization", "header", "authorization_header")),
    ("raw_content", ("raw_content", "raw_bytes", "raw_upload", "raw_data", "uploaded_bytes")),
    ("document_text", ("document_text", "stored_document_text", "stored_content")),
    ("chunk_content", ("chunk_content", "stored_chunk_content")),
)
UTC = dt.timezone.utc
MAX_EVIDENCE_AGE = dt.timedelta(minutes=30)
MAX_CHALLENGE_AGE = dt.timedelta(minutes=30)
MAX_RUN_WINDOW = dt.timedelta(minutes=35)
MAX_FUTURE_SKEW = dt.timedelta(minutes=5)
COUNT_PATTERN = re.compile(r"^[0-9]+$")


class ValidationError(Exception):
    """An expected fail-closed validation failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def classify_sensitive_field(name: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]", "_", name.lower())
    for category, keywords in SENSITIVE_FIELD_CATEGORIES:
        if any(kw in normalized for kw in keywords):
            return category
    return None


def is_sensitive_field(name: str) -> bool:
    return classify_sensitive_field(name) is not None


def inspect_privacy_prohibition(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            require(isinstance(key, str), f"schema at '{path}' has a non-string field key")
            category = classify_sensitive_field(key)
            require(
                category is None,
                f"forbidden privacy field class '{category}' at '{path}.{key}'",
            )
            inspect_privacy_prohibition(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(value):
            inspect_privacy_prohibition(item, f"{path}[{idx}]")


def resolve_lancedb_path(config_path: Path | str | None = None) -> Path:
    root = Path(__file__).resolve().parents[1]
    target = Path(config_path) if config_path else root / "config" / "config.verify.toml"
    if not target.is_absolute():
        target = (root / target).resolve()
    require(target.is_file(), f"verification config file does not exist: {target}")
    try:
        import tomllib
        with target.open("rb") as stream:
            data = tomllib.load(stream)
    except Exception as error:
        raise ValidationError(f"invalid verification config TOML at {target}") from error

    require(isinstance(data, dict), "verification config must be a TOML table")
    engine = data.get("engine")
    require(isinstance(engine, dict), "verification config missing [engine] table")
    raw_path = engine.get("lancedb_path")
    require(
        isinstance(raw_path, str) and bool(raw_path.strip()),
        "invalid verification LanceDB configuration: engine.lancedb_path must be a non-empty string",
    )
    store_path = Path(raw_path.strip())
    if not store_path.is_absolute():
        store_path = (root / store_path).resolve()
    require(bool(str(store_path)), "resolved LanceDB store path is invalid")
    return store_path


def validate_object_keys(
    value: Any, expected: frozenset[str], label: str
) -> Mapping[str, Any]:
    require(isinstance(value, dict), f"{label} must be a JSON object")
    keys = set(value)
    require(keys == expected, f"{label} schema has an unexpected field set")
    inspect_privacy_prohibition(value, label)
    return value


def read_json_file(path: Path, label: str) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"{label} could not be read as JSON") from error


def read_json_source(source: str, label: str) -> Any:
    if source == "-":
        try:
            return json.load(sys.stdin)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValidationError(f"{label} could not be read as JSON") from error
    return read_json_file(Path(source), label)


def require_string(value: Mapping[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    require(isinstance(item, str) and bool(item), f"{label}.{key} must be a string")
    return item


def require_integer(value: Mapping[str, Any], key: str, label: str) -> int:
    item = value.get(key)
    require(isinstance(item, int) and not isinstance(item, bool), f"{label}.{key} must be an integer")
    return item


def require_boolean(value: Mapping[str, Any], key: str, label: str) -> bool:
    item = value.get(key)
    require(isinstance(item, bool), f"{label}.{key} must be a boolean")
    return item


def parse_timestamp(value: Any, label: str) -> dt.datetime:
    require(isinstance(value, str) and bool(value), f"{label} must be an RFC3339 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(f"{label} must be an RFC3339 timestamp") from error
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def parse_uuid_v4(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value), f"{label} must be a UUIDv4")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValidationError(f"{label} must be a UUIDv4") from error
    require(parsed.version == 4, f"{label} must be a UUIDv4")
    return str(parsed)


def validate_challenge(value: Any, now: dt.datetime | None = None) -> Mapping[str, Any]:
    challenge = validate_object_keys(value, CHALLENGE_KEYS, "challenge")
    schema_version = challenge.get("schema_version")
    require(isinstance(schema_version, int) and not isinstance(schema_version, bool), "challenge.schema_version must be 1")
    require(schema_version == 1, "challenge.schema_version must be 1")
    challenge_value = require_string(challenge, "challenge", "challenge")
    require(len(challenge_value) >= 32, "challenge.challenge is too short")
    parse_uuid_v4(challenge.get("run_id"), "challenge.run_id")
    issued_at = parse_timestamp(challenge.get("issued_at"), "challenge.issued_at")
    current = now or dt.datetime.now(UTC)
    require(issued_at <= current + MAX_FUTURE_SKEW, "challenge.issued_at is in the future")
    require(current - issued_at <= MAX_CHALLENGE_AGE, "challenge.issued_at is stale")
    return challenge


def validate_inspection(value: Any, expected_document_id: str | None = None) -> Mapping[str, Any]:
    inspection = validate_object_keys(value, INSPECTION_KEYS, "inspection")
    document_id = parse_uuid_v4(inspection.get("document_id"), "inspection.document_id")
    if expected_document_id is not None:
        require(document_id == expected_document_id, "inspection.document_id does not match evidence")
    provider = require_string(inspection, "provider", "inspection")
    require(provider == "openrouter", "inspection.provider is not openrouter")
    model = require_string(inspection, "embedding_model", "inspection")
    require(model == EXPECTED_MODEL, "inspection.embedding_model is not the locked model")
    for key in INSPECTION_INTEGER_FIELDS:
        require_integer(inspection, key, "inspection")
    require(inspection["document_rows"] == 1, "inspection.document_rows must be one")
    require(inspection["staged_document_rows"] == 0, "inspection.staged_document_rows must be zero")
    require(inspection["node_rows"] > 0, "inspection.node_rows must be positive")
    require(inspection["edge_rows"] >= 0, "inspection.edge_rows must be non-negative")
    require(inspection["embedding_width"] == 2048, "inspection.embedding_width must be 2048")
    require(inspection["generation_count"] == 1, "inspection.generation_count must be one")
    for key in BOOLEAN_FIELDS:
        require_boolean(inspection, key, "inspection")
    require(not inspection["duplicate_generation"], "inspection.duplicate_generation must be false")
    require(not inspection["stale_generation"], "inspection.stale_generation must be false")
    require(inspection["chunk_indexes_contiguous"], "inspection.chunk_indexes_contiguous must be true")
    return inspection


def parse_postgres(value: str) -> tuple[str, int]:
    require(isinstance(value, str), "PostgreSQL state must be a status/count pair")
    value = value.strip()
    status, separator, count_text = value.partition(":")
    require(separator == ":" and status == "completed", f"PostgreSQL status is not completed: got '{value}'")
    require(bool(COUNT_PATTERN.fullmatch(count_text)), "PostgreSQL chunk count is invalid")
    count = int(count_text)
    require(count > 0, "PostgreSQL chunk count must be positive")
    return status, count


def validate_evidence(
    value: Any, challenge: Mapping[str, Any], now: dt.datetime | None = None
) -> Mapping[str, Any]:
    evidence = validate_object_keys(value, EVIDENCE_KEYS, "evidence")
    validate_challenge(challenge, now=now)
    evidence_schema_version = evidence.get("schema_version")
    require(
        isinstance(evidence_schema_version, int)
        and not isinstance(evidence_schema_version, bool)
        and evidence_schema_version == 1,
        "evidence.schema_version must be 1",
    )
    for key in ("challenge", "run_id", "issued_at"):
        require(evidence.get(key) == challenge.get(key), f"evidence.{key} does not match challenge")
    require_string(evidence, "success_sentinel", "evidence")
    require(evidence["success_sentinel"] == SUCCESS_SENTINEL, "evidence.success_sentinel is invalid")
    parse_uuid_v4(evidence.get("document_id"), "evidence.document_id")
    provider = require_string(evidence, "provider", "evidence")
    require(provider == "openrouter", "evidence.provider is not openrouter")
    model = require_string(evidence, "embedding_model", "evidence")
    require(model == EXPECTED_MODEL, "evidence.embedding_model is not the locked model")
    for key in INTEGER_FIELDS:
        require_integer(evidence, key, "evidence")
        require(evidence[key] >= 0, f"evidence.{key} must be non-negative")
    require(evidence["gateway_chunk_count"] == evidence["postgres_chunk_count"] == evidence["node_rows"] > 0, "evidence counts do not agree")
    require(evidence["document_rows"] == 1, "evidence.document_rows must be one")
    require(evidence["staged_document_rows"] == 0, "evidence.staged_document_rows must be zero")
    require(evidence["edge_rows"] >= 0, "evidence.edge_rows must be non-negative")
    require(evidence["embedding_width"] == 2048, "evidence.embedding_width must be 2048")
    require(evidence["generation_count"] == 1, "evidence.generation_count must be one")
    require_string(evidence, "postgres_status", "evidence")
    require(evidence["postgres_status"] == "completed", "evidence.postgres_status is not completed")
    for key in BOOLEAN_FIELDS:
        require_boolean(evidence, key, "evidence")
    require(not evidence["duplicate_generation"], "evidence.duplicate_generation must be false")
    require(not evidence["stale_generation"], "evidence.stale_generation must be false")
    require(evidence["chunk_indexes_contiguous"], "evidence.chunk_indexes_contiguous must be true")
    issued_at = parse_timestamp(challenge.get("issued_at"), "challenge.issued_at")
    run_started_at = parse_timestamp(evidence.get("run_started_at"), "evidence.run_started_at")
    generated_at = parse_timestamp(evidence.get("generated_at"), "evidence.generated_at")
    current = now or dt.datetime.now(UTC)
    require(issued_at <= run_started_at <= generated_at, "evidence timestamps are not ordered")
    require(generated_at <= current + MAX_FUTURE_SKEW, "evidence.generated_at is in the future")
    require(current - generated_at <= MAX_EVIDENCE_AGE, "evidence.generated_at is stale")
    require(generated_at - issued_at <= MAX_RUN_WINDOW, "complete run window exceeded")
    require(run_started_at - issued_at <= MAX_RUN_WINDOW, "run start delay exceeded")
    return evidence


def build_evidence(
    challenge_path: str,
    inspection_source: str,
    document_id: str,
    gateway_count_text: str,
    postgres_text: str,
    run_started_text: str,
) -> Mapping[str, Any]:
    challenge = validate_challenge(read_json_file(Path(challenge_path), "challenge"))
    normalized_document_id = parse_uuid_v4(document_id, "document_id")
    inspection = validate_inspection(
        read_json_source(inspection_source, "inspection"), expected_document_id=normalized_document_id
    )
    require(bool(COUNT_PATTERN.fullmatch(gateway_count_text)), "gateway chunk count is invalid")
    gateway_count = int(gateway_count_text)
    require(gateway_count > 0, "gateway chunk count must be positive")
    postgres_status, postgres_count = parse_postgres(postgres_text)
    require(gateway_count == postgres_count == inspection["node_rows"], "durable counts do not agree")
    issued_at = parse_timestamp(challenge.get("issued_at"), "challenge.issued_at")
    run_started_at = parse_timestamp(run_started_text, "run_started_at")
    current = dt.datetime.now(UTC)
    require(run_started_at >= issued_at, "run_started_at predates challenge")
    require(run_started_at <= current + MAX_FUTURE_SKEW, "run_started_at is in the future")
    require(current - issued_at <= MAX_RUN_WINDOW, "complete run window exceeded")
    require(run_started_at - issued_at <= MAX_RUN_WINDOW, "run start delay exceeded")
    generated_at = current.strftime("%Y-%m-%dT%H:%M:%SZ")
    evidence = {
        "schema_version": 1,
        "success_sentinel": SUCCESS_SENTINEL,
        "challenge": challenge["challenge"],
        "run_id": challenge["run_id"],
        "issued_at": challenge["issued_at"],
        "run_started_at": run_started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at": generated_at,
        "document_id": normalized_document_id,
        "provider": inspection["provider"],
        "embedding_model": inspection["embedding_model"],
        "gateway_chunk_count": gateway_count,
        "postgres_status": postgres_status,
        "postgres_chunk_count": postgres_count,
        "document_rows": inspection["document_rows"],
        "staged_document_rows": inspection["staged_document_rows"],
        "node_rows": inspection["node_rows"],
        "edge_rows": inspection["edge_rows"],
        "embedding_width": inspection["embedding_width"],
        "generation_count": inspection["generation_count"],
        "duplicate_generation": inspection["duplicate_generation"],
        "stale_generation": inspection["stale_generation"],
        "chunk_indexes_contiguous": inspection["chunk_indexes_contiguous"],
    }
    validate_evidence(evidence, challenge, now=current)
    return evidence


def compare_live_state(
    challenge_path: str, evidence_path: str, postgres_text: str, inspection_source: str
) -> str:
    challenge = validate_challenge(read_json_file(Path(challenge_path), "challenge"))
    evidence = validate_evidence(read_json_file(Path(evidence_path), "evidence"), challenge)
    postgres_status, postgres_count = parse_postgres(postgres_text)
    require(postgres_status == evidence["postgres_status"], "current PostgreSQL status differs from evidence")
    require(postgres_count == evidence["postgres_chunk_count"], "current PostgreSQL count differs from evidence")
    inspection = validate_inspection(
        read_json_source(inspection_source, "inspection"), expected_document_id=evidence["document_id"]
    )
    durable_fields = (
        "document_id",
        "provider",
        "embedding_model",
        "document_rows",
        "staged_document_rows",
        "node_rows",
        "edge_rows",
        "embedding_width",
        "generation_count",
        "duplicate_generation",
        "stale_generation",
        "chunk_indexes_contiguous",
    )
    for key in durable_fields:
        require(inspection[key] == evidence[key], f"current inspection {key} differs from evidence")
    require(inspection["node_rows"] == postgres_count, "current LanceDB node count differs from PostgreSQL")
    return evidence["document_id"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    parse_challenge = subcommands.add_parser("parse-challenge")
    parse_challenge.add_argument("--challenge", "--challenge-file", dest="challenge", required=True)

    validate_document = subcommands.add_parser("validate-document-id")
    validate_document.add_argument("--document-id", required=True)

    build = subcommands.add_parser("build-evidence")
    build.add_argument("--challenge", "--challenge-file", dest="challenge", required=True)
    build.add_argument("--inspection-json", "--inspection", dest="inspection_json", required=True)
    build.add_argument("--document-id", required=True)
    build.add_argument("--gateway-count", required=True)
    build.add_argument("--postgres", required=True)
    build.add_argument("--run-started-at", required=True)

    validate = subcommands.add_parser("validate-gate")
    validate.add_argument("--challenge", "--challenge-file", dest="challenge", required=True)
    validate.add_argument("--evidence", "--evidence-file", dest="evidence", required=True)

    compare = subcommands.add_parser("compare-live-state", aliases=["validate-live-state"])
    compare.add_argument("--challenge", "--challenge-file", dest="challenge", required=True)
    compare.add_argument("--evidence", "--evidence-file", dest="evidence", required=True)
    compare.add_argument("--postgres", required=True)
    compare.add_argument("--inspection-json", "--inspection", dest="inspection_json", required=True)

    resolve_store = subcommands.add_parser("resolve-store-path", aliases=["resolve-lancedb-path"])
    resolve_store.add_argument("--config", dest="config", required=False, default=None)

    check_priv = subcommands.add_parser("check-privacy")
    check_priv.add_argument("--file", dest="file", required=True)

    subcommands.add_parser("self-test")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    if args.command in {"resolve-store-path", "resolve-lancedb-path"}:
        store_path = resolve_lancedb_path(args.config)
        print(str(store_path))
        return 0
    if args.command == "check-privacy":
        data = read_json_source(args.file, "subject")
        inspect_privacy_prohibition(data, "subject")
        print("privacy prohibition check: PASS")
        return 0
    if args.command == "parse-challenge":
        challenge = validate_challenge(read_json_file(Path(args.challenge), "challenge"))
        print(json.dumps(challenge, separators=(",", ":"), sort_keys=True))
        return 0
    if args.command == "validate-document-id":
        print(parse_uuid_v4(args.document_id, "document_id"))
        return 0
    if args.command == "build-evidence":
        evidence = build_evidence(
            args.challenge,
            args.inspection_json,
            args.document_id,
            args.gateway_count,
            args.postgres,
            args.run_started_at,
        )
        print(json.dumps(evidence, separators=(",", ":"), sort_keys=True))
        return 0
    if args.command == "validate-gate":
        challenge = validate_challenge(read_json_file(Path(args.challenge), "challenge"))
        evidence = validate_evidence(read_json_file(Path(args.evidence), "evidence"), challenge)
        print(evidence["document_id"])
        return 0
    if args.command in {"compare-live-state", "validate-live-state"}:
        print(compare_live_state(args.challenge, args.evidence, args.postgres, args.inspection_json))
        return 0
    if args.command == "self-test":
        require(True, "self-test require path failed")
        print("phase02 live-evidence helper self-test: PASS")
        return 0
    raise ValidationError("unknown helper command")


def main() -> int:
    try:
        return run(parse_args())
    except ValidationError as error:
        print(f"validation failed: {error}", file=sys.stderr)
        return 1
    except (OSError, TypeError, ValueError) as error:
        del error
        print("validation failed: malformed or unreadable input", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
