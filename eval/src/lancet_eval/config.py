"""Configuration management for the Lancet evaluation harness."""

from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from urllib.parse import parse_qs, urlencode, urlparse

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EvalConfigError(Exception):
    """Raised when evaluation configuration is invalid or missing required values."""


def repo_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).resolve().parents[3]


def get_commit_sha() -> str:
    """Get current git commit SHA or return 'unknown'."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


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


def with_search_path(dsn: str, schema: str) -> str:
    """Return `dsn` with its `search_path` query parameter set to `schema`."""
    parsed = urlparse(dsn)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["search_path"] = [schema]
    return parsed._replace(query=urlencode(params, doseq=True, safe="/")).geturl()


@dataclass(frozen=True)
class EvalStore:
    """One isolated eval store (D-251): its LanceDB path and PostgreSQL schema.

    `name` is both the engine's `LANCET_ENV` overlay (`config/config.<name>.toml`) and
    the Atlas env (`gateway/atlas.hcl`) that applies the store's schema.
    """

    name: str
    lancedb_path: str
    pg_schema: str

    @property
    def overlay_path(self) -> Path:
        """The engine overlay that sets this store's LanceDB path."""
        return repo_root() / "config" / f"config.{self.name}.toml"


#: The v1.0 eval store, the default everywhere.
V1_STORE = EvalStore("eval", "./data/lancedb-eval", "lancet_eval")
#: The v1.1 S1 merged-chunk store (D-251). It never touches the v1.0 store.
S1_STORE = EvalStore("eval-s1", "./data/lancedb-eval-s1", "lancet_eval_s1")
EVAL_STORES: dict[str, EvalStore] = {s.name: s for s in (V1_STORE, S1_STORE)}


def get_eval_store(name: str) -> EvalStore:
    """Resolve a store name (`--store`) to its `EvalStore`."""
    try:
        return EVAL_STORES[name]
    except KeyError:
        raise EvalConfigError(
            f"Unknown eval store {name!r}; known stores: {', '.join(EVAL_STORES)}"
        ) from None


def store_for_settings(settings: EvalSettings) -> EvalStore:
    """The known store whose LanceDB path `settings` use; the v1.0 store otherwise.

    Lets a reader that holds only settings pick the store's document map (#18), so
    the map always follows the LanceDB store actually in use.
    """
    for store in EVAL_STORES.values():
        if store != V1_STORE and _same_path(settings.lancedb_path, store.lancedb_path):
            return store
    return V1_STORE


def overlay_lancedb_path(store: EvalStore) -> str | None:
    """Read `[engine].lancedb_path` from the store's overlay; None if absent."""
    if not store.overlay_path.is_file():
        return None
    with open(store.overlay_path, "rb") as f:
        value = tomllib.load(f).get("engine", {}).get("lancedb_path")
    return value if isinstance(value, str) else None


def _same_path(a: str, b: str) -> bool:
    """Whether two LanceDB paths name one directory, from the cwd or the repo root."""
    a_path, b_path = Path(a), Path(b)
    if a_path.resolve() == b_path.resolve():
        return True
    root = repo_root()
    return (root / a_path).resolve() == (root / b_path).resolve()


def store_target_failures(settings: EvalSettings, store: EvalStore) -> list[str]:
    """Why `settings` must not act on `store`; empty when they target it.

    Settings whose LanceDB path is another known store's are refused for every store,
    so one run never mixes two stores' maps (#18). Beyond that the v1.0 store keeps
    its v1.0 checks only. Any other store refuses the v1.0 path and schema outright
    (D-251), then requires the settings and the store's overlay to name exactly the
    store's path and schema.
    """
    in_use = store_for_settings(settings)
    if store == V1_STORE:
        if in_use != V1_STORE:
            return [
                f"settings use store {in_use.name!r}'s LanceDB path "
                f"{settings.lancedb_path!r}; select --store {in_use.name}"
            ]
        return []
    failures: list[str] = []
    schema = pg_schema_of(settings.database_url)
    if _same_path(settings.lancedb_path, V1_STORE.lancedb_path):
        failures.append(
            f"store {store.name!r} refuses the v1.0 LanceDB path "
            f"{V1_STORE.lancedb_path!r} (settings name {settings.lancedb_path!r})"
        )
    elif not _same_path(settings.lancedb_path, store.lancedb_path):
        failures.append(
            f"store {store.name!r} expects LanceDB path {store.lancedb_path!r}, "
            f"settings name {settings.lancedb_path!r}"
        )
    if schema == V1_STORE.pg_schema:
        failures.append(
            f"store {store.name!r} refuses the v1.0 PostgreSQL schema "
            f"{V1_STORE.pg_schema!r}"
        )
    elif schema != store.pg_schema:
        failures.append(
            f"store {store.name!r} expects PostgreSQL schema {store.pg_schema!r}, "
            f"settings name {schema!r}"
        )
    overlay_path = overlay_lancedb_path(store)
    if overlay_path is None:
        failures.append(
            f"overlay {store.overlay_path} sets no [engine].lancedb_path for "
            f"store {store.name!r}"
        )
    elif not _same_path(overlay_path, settings.lancedb_path):
        failures.append(
            f"overlay {store.overlay_path.name} sets LanceDB path {overlay_path!r}, "
            f"the harness uses {settings.lancedb_path!r}"
        )
    return failures


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


def load_settings(
    config_path: Path | None = None, store: EvalStore = V1_STORE
) -> EvalSettings:
    """Load settings from optional TOML file and environment variables.

    For a store other than the v1.0 default, the store's LanceDB path and schema
    replace whatever the file or environment names (D-251).
    """
    target_path = config_path or (repo_root() / "eval" / "config.toml")
    file_values: dict[str, object] = {}
    if target_path.is_file():
        with open(target_path, "rb") as f:
            file_values = tomllib.load(f)
    settings = EvalSettings(**file_values)
    if store == V1_STORE:
        return settings
    return EvalSettings(**{
        **file_values,
        "lancedb_path": store.lancedb_path,
        "database_url": with_search_path(settings.database_url, store.pg_schema),
    })
