"""Claude reader requests rewritten from the engine's `pack` body (#51, D-255, D-256).

`generate_from_context pack` emits the exact chat-completions body the engine posts
for the deepseek reader. A Claude reader arm (D-257) must see the same prompt, so its
request is that body with a declared set of fields rewritten, and nothing else:

- **OpenRouter target.** `model` becomes the reader slug; `provider` becomes
  `{only: ["anthropic"], allow_fallbacks: false}` (no `require_parameters`, no
  `order`); `temperature` and `top_p` are deleted, since Anthropic rejects them;
  `reasoning` follows the reader's thinking setting. Every other byte is the `pack`
  body's.
- **Anthropic target.** The body becomes a Messages request: `system` and one user
  message carry the `pack` message text byte for byte, `max_tokens` is
  `max_completion_tokens`, `output_config.format` is the strict `json_schema`, and
  `thinking` follows the declaration.

Thinking settings, per target:

- `off`: OpenRouter `reasoning: {enabled: false}`; Anthropic
  `thinking: {type: "disabled"}`.
- `between_tools`: both targets send `thinking: {type: "between_tools"}`; on
  OpenRouter it takes the place of `reasoning`.
- `on` with an effort: OpenRouter `reasoning: {effort: <effort>}`; Anthropic sends no
  `thinking` and sets `output_config.effort`.

OpenRouter documents no `between_tools`; the S2 pilot finds out whether the top-level
`thinking` field passes through (D-255). No `cache_control` is ever added (D-256).

The module does no I/O. `ReaderDeclaration` is a frozen value, so a pre-registration
constant can hold one; `rewrite_pack_body` returns the request body, its exact JSON
text and the list of fields it rewrote. A `pack` body with an unexpected or missing
top-level field, or one this module could not reproduce byte for byte, is refused.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

Target = Literal["openrouter", "anthropic"]
Thinking = Literal["off", "between_tools", "on"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]

# The top-level fields of the engine's chat request body (`OpenRouterChatPayload`).
PACK_FIELDS = frozenset({
    "model",
    "messages",
    "temperature",
    "top_p",
    "max_completion_tokens",
    "reasoning",
    "response_format",
    "provider",
})

ANTHROPIC_PROVIDER: dict[str, Any] = {"only": ["anthropic"], "allow_fallbacks": False}


class ReaderRequestError(ValueError):
    """A reader declaration or a `pack` body this module refuses."""


@dataclass(frozen=True)
class ReaderPrice:
    """Sync list price in USD per million tokens; D-257 costs every reader at it."""

    input_per_mtok: float
    output_per_mtok: float

    def __post_init__(self) -> None:
        if self.input_per_mtok < 0 or self.output_per_mtok < 0:
            raise ReaderRequestError(f"a price cannot be negative: {self}")


@dataclass(frozen=True)
class ReaderDeclaration:
    """One Claude reader as a pre-registration declares it.

    `slug` is the model name the target expects: an OpenRouter slug or an Anthropic
    model ID.
    `effort` is set exactly when `thinking` is `on`.
    """

    slug: str
    target: Target
    thinking: Thinking
    price: ReaderPrice
    effort: Effort | None = None

    def __post_init__(self) -> None:
        if not self.slug:
            raise ReaderRequestError("a reader declaration needs a slug")
        if self.target not in get_args(Target):
            raise ReaderRequestError(f"unknown target {self.target!r}")
        if self.thinking not in get_args(Thinking):
            raise ReaderRequestError(f"unknown thinking value {self.thinking!r}")
        if self.thinking == "on":
            if self.effort not in get_args(Effort):
                raise ReaderRequestError(
                    f"thinking 'on' needs an effort out of {get_args(Effort)}, "
                    f"got {self.effort!r}"
                )
        elif self.effort is not None:
            raise ReaderRequestError(
                f"an effort goes with thinking 'on' only, not {self.thinking!r}"
            )


@dataclass(frozen=True)
class ReaderRequest:
    """A rewritten request: the body, its exact JSON text, and the fields that changed.

    `rewritten_fields` names the `pack` body's top-level fields that were replaced or
    deleted, then the fields that were added. For the Anthropic target every field is
    rewritten, since the request shape changes; the message text stays byte for byte.
    """

    reader: ReaderDeclaration
    body: Mapping[str, Any] = field(compare=False)
    body_json: str
    rewritten_fields: tuple[str, ...]


def rewrite_pack_body(pack_body: str, reader: ReaderDeclaration) -> ReaderRequest:
    """The request sent to `reader` for one `pack` success line's `body` string."""
    pack = _read_pack_body(pack_body)
    if reader.target == "openrouter":
        body, fields = _openrouter_body(pack, reader)
    else:
        body, fields = _anthropic_body(pack, reader)
    return ReaderRequest(
        reader=reader,
        body=body,
        body_json=_dumps(body),
        rewritten_fields=fields,
    )


def _dumps(value: Any) -> str:
    # serde_json's compact form, which `pack` emits.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _read_pack_body(pack_body: str) -> dict[str, Any]:
    try:
        pack = json.loads(pack_body)
    except json.JSONDecodeError as exc:
        raise ReaderRequestError(f"unreadable pack body: {exc}") from exc
    if not isinstance(pack, dict):
        raise ReaderRequestError("the pack body is not a JSON object")
    unexpected = sorted(pack.keys() - PACK_FIELDS)
    missing = sorted(PACK_FIELDS - pack.keys())
    if unexpected or missing:
        raise ReaderRequestError(
            f"the pack body's fields differ from the engine's: "
            f"unexpected {unexpected}, missing {missing}"
        )
    if _dumps(pack) != pack_body:
        raise ReaderRequestError(
            "the pack body does not round-trip byte for byte; "
            "pass the `body` string exactly as `pack` emitted it"
        )
    return pack


def _openrouter_reasoning(reader: ReaderDeclaration) -> tuple[str, dict[str, Any]]:
    match reader.thinking:
        case "off":
            return "reasoning", {"enabled": False}
        case "between_tools":
            return "thinking", {"type": "between_tools"}
        case "on":
            return "reasoning", {"effort": reader.effort}


def _openrouter_body(
    pack: dict[str, Any], reader: ReaderDeclaration
) -> tuple[dict[str, Any], tuple[str, ...]]:
    reasoning_key, reasoning = _openrouter_reasoning(reader)
    body: dict[str, Any] = {}
    for key, value in pack.items():
        match key:
            case "model":
                body[key] = reader.slug
            case "temperature" | "top_p":
                pass
            case "reasoning":
                body[reasoning_key] = reasoning
            case "provider":
                body[key] = ANTHROPIC_PROVIDER
            case _:
                body[key] = value
    fields = tuple(
        key for key in dict.fromkeys([*pack, *body]) if pack.get(key) != body.get(key)
    )
    return body, fields


def _anthropic_body(
    pack: dict[str, Any], reader: ReaderDeclaration
) -> tuple[dict[str, Any], tuple[str, ...]]:
    system, user = _system_and_user(pack["messages"])
    json_schema = _strict_json_schema(pack["response_format"])
    output_config: dict[str, Any] = {
        "format": {"type": "json_schema", "schema": json_schema["schema"]}
    }
    body: dict[str, Any] = {
        "model": reader.slug,
        "max_tokens": pack["max_completion_tokens"],
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    match reader.thinking:
        case "off":
            body["thinking"] = {"type": "disabled"}
        case "between_tools":
            body["thinking"] = {"type": "between_tools"}
        case "on":
            output_config["effort"] = reader.effort
    body["output_config"] = output_config
    fields = tuple(dict.fromkeys([*pack, *body]))
    return body, fields


def _system_and_user(messages: Any) -> tuple[str, str]:
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or not all(
            isinstance(m, dict) and set(m) == {"role", "content"} for m in messages
        )
        or [m["role"] for m in messages] != ["system", "user"]
        or not all(isinstance(m["content"], str) for m in messages)
    ):
        raise ReaderRequestError(
            "the pack body's messages are not one system and one user text message"
        )
    return messages[0]["content"], messages[1]["content"]


def _strict_json_schema(response_format: Any) -> dict[str, Any]:
    json_schema = (
        response_format.get("json_schema")
        if isinstance(response_format, dict)
        else None
    )
    if (
        not isinstance(response_format, dict)
        or response_format.get("type") != "json_schema"
        or not isinstance(json_schema, dict)
        or json_schema.get("strict") is not True
        or not isinstance(json_schema.get("schema"), dict)
    ):
        raise ReaderRequestError(
            "the pack body's response_format is not a strict json_schema"
        )
    return json_schema
