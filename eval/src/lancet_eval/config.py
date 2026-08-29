"""Configuration management for the Lancet evaluation harness."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Self
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvalConfigError(Exception):
    """Raised when evaluation configuration is invalid or missing required values."""


def repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parents[3]


def pg_schema_of(dsn: str) -> str:
    """Extract PostgreSQL search_path schema from DSN query parameters."""
    if not dsn or not dsn.strip():
        return ""
    try:
        parsed = urlparse(dsn)
        params = parse_qs(parsed.query)
        schemas = params.get("search_path")
        if schemas and schemas[0].strip():
            return schemas[0].strip()
        return "public"
    except Exception:
        return "public"


class EvalSettings(BaseSettings):
    """Evaluation harness settings with fail-closed validation."""

    model_config = SettingsConfigDict(
        env_prefix="LANCET_EVAL__",
        env_nested_delimiter="__",
        extra="forbid",
    )

    gateway_url: str = "http://localhost:8080"
    gateway_timeout_secs: float = 300.0
    question_deadline_secs: float = 600.0
    lancedb_path: str = "./data/lancedb-eval"
    database_url: str = "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval"
    dev_lancedb_path: str = "./data/lancedb"
    dev_database_url: str = (
        "postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable"
    )
    judge_model: str = "openai/gpt-4o-mini"
    judge_temperature: float = 0.0
    judge_max_tokens: int = 2048
    judge_prompt_version: str = "v1"
    judge_endpoint: str = "https://openrouter.ai/api/v1/chat/completions"
    max_workers: int = 1
    sample_seed: int = 42

    def __init__(self, **values: object) -> None:
        try:
            super().__init__(**values)
        except (ValidationError, ValueError) as exc:
            raise EvalConfigError(f"Invalid eval configuration: {exc}") from exc

    @model_validator(mode="after")
    def _validate_fields(self) -> Self:
        if not (
            self.gateway_url.startswith("http://")
            or self.gateway_url.startswith("https://")
        ):
            raise EvalConfigError(
                f"gateway_url must be an HTTP(S) URL, got {self.gateway_url!r}"
            )
        if self.gateway_timeout_secs <= 0:
            raise EvalConfigError(
                "gateway_timeout_secs must be positive, got "
                f"{self.gateway_timeout_secs}"
            )
        if self.question_deadline_secs <= 0:
            raise EvalConfigError(
                "question_deadline_secs must be positive, got "
                f"{self.question_deadline_secs}"
            )
        if self.max_workers < 1:
            raise EvalConfigError(f"max_workers must be >= 1, got {self.max_workers}")
        if not (0.0 <= self.judge_temperature <= 2.0):
            raise EvalConfigError(
                f"judge_temperature must be in [0.0, 2.0], got {self.judge_temperature}"
            )
        if not self.judge_endpoint.startswith("https://"):
            raise EvalConfigError(
                f"judge_endpoint must start with https://, got {self.judge_endpoint!r}"
            )

        # Store isolation validations (D-56, D-84)
        if self.lancedb_path and self.dev_lancedb_path:
            norm_eval_lance = str(Path(self.lancedb_path).resolve())
            norm_dev_lance = str(Path(self.dev_lancedb_path).resolve())
            if norm_eval_lance == norm_dev_lance:
                raise EvalConfigError(
                    f"Eval LanceDB path '{self.lancedb_path}' "
                    f"collides with dev path '{self.dev_lancedb_path}'"
                )

        if self.database_url and self.dev_database_url:
            eval_schema = pg_schema_of(self.database_url)
            dev_schema = pg_schema_of(self.dev_database_url)
            if eval_schema and dev_schema and eval_schema == dev_schema:
                raise EvalConfigError(
                    f"Eval PostgreSQL schema '{eval_schema}' "
                    f"collides with dev schema '{dev_schema}'"
                )

        return self


def load_settings(config_path: Path | None = None) -> EvalSettings:
    """Load settings from optional TOML file and environment variables."""
    target_path = config_path or (repo_root() / "eval" / "config.toml")
    file_values: dict[str, object] = {}
    if target_path.is_file():
        with open(target_path, "rb") as f:
            file_values = tomllib.load(f)
    return EvalSettings(**file_values)
