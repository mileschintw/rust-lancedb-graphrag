"""The Claude reader request rewrite (#51, D-255, D-256).

One fixture `pack` body, shaped as `engine/src/generation/openrouter.rs` serialises
it, is rewritten for four reader declarations. Each result is compared with a golden
body under `fixtures/reader_request/`; the other tests pin the contract the goldens
rely on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lancet_eval.reader_request import (
    ReaderDeclaration,
    ReaderPrice,
    ReaderRequestError,
    rewrite_pack_body,
)

FIXTURES = Path(__file__).parent / "fixtures" / "reader_request"
PACK_BODY = (FIXTURES / "pack_body.json").read_text(encoding="utf-8").rstrip("\r\n")

HAIKU_OPENROUTER = ReaderDeclaration(
    slug="anthropic/claude-haiku-5.5",
    target="openrouter",
    thinking="off",
    price=ReaderPrice(input_per_mtok=0.10, output_per_mtok=0.50),
)
SONNET_OPENROUTER = ReaderDeclaration(
    slug="anthropic/claude-sonnet-5.5",
    target="openrouter",
    thinking="between_tools",
    price=ReaderPrice(input_per_mtok=2.0, output_per_mtok=10.0),
)
SONNET_ANTHROPIC = ReaderDeclaration(
    slug="claude-sonnet-5-5",
    target="anthropic",
    thinking="between_tools",
    price=ReaderPrice(input_per_mtok=2.0, output_per_mtok=10.0),
)
OPUS_ANTHROPIC = ReaderDeclaration(
    slug="claude-opus-5-5",
    target="anthropic",
    thinking="on",
    effort="low",
    price=ReaderPrice(input_per_mtok=5.0, output_per_mtok=25.0),
)

GOLDENS = {
    "openrouter_haiku_5_5": HAIKU_OPENROUTER,
    "openrouter_sonnet_5_5": SONNET_OPENROUTER,
    "anthropic_sonnet_5_5": SONNET_ANTHROPIC,
    "anthropic_opus_5_5": OPUS_ANTHROPIC,
}
OPENROUTER_READERS = [HAIKU_OPENROUTER, SONNET_OPENROUTER]
OPENROUTER_FIELDS = {
    HAIKU_OPENROUTER.slug: ("model", "temperature", "top_p", "reasoning", "provider"),
    SONNET_OPENROUTER.slug: (
        "model",
        "temperature",
        "top_p",
        "reasoning",
        "provider",
        "thinking",
    ),
}
ANTHROPIC_READERS = [SONNET_ANTHROPIC, OPUS_ANTHROPIC]


def _pack() -> dict[str, Any]:
    return json.loads(PACK_BODY)


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _without(body: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in fields}


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_body_matches_its_golden(name: str) -> None:
    request = rewrite_pack_body(PACK_BODY, GOLDENS[name])
    golden = (FIXTURES / f"{name}.json").read_text(encoding="utf-8").rstrip("\r\n")
    assert request.body_json == golden


def test_haiku_reasoning_is_disabled_on_openrouter() -> None:
    request = rewrite_pack_body(PACK_BODY, HAIKU_OPENROUTER)
    assert request.body["reasoning"] == {"enabled": False}
    assert request.body["model"] == "anthropic/claude-haiku-5.5"
    assert request.body["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}


@pytest.mark.parametrize("reader", OPENROUTER_READERS, ids=lambda r: r.slug)
def test_openrouter_rewrite_touches_only_the_reported_fields(
    reader: ReaderDeclaration,
) -> None:
    request = rewrite_pack_body(PACK_BODY, reader)
    fields = request.rewritten_fields
    assert fields == OPENROUTER_FIELDS[reader.slug]
    assert _without(request.body, fields) == _without(_pack(), fields)
    for name in fields:
        assert request.body.get(name) != _pack().get(name), name


@pytest.mark.parametrize("reader", OPENROUTER_READERS, ids=lambda r: r.slug)
def test_openrouter_untouched_bytes_are_the_pack_bytes(
    reader: ReaderDeclaration,
) -> None:
    request = rewrite_pack_body(PACK_BODY, reader)
    messages = _compact(_pack()["messages"])
    schema = _compact(_pack()["response_format"])
    assert messages in PACK_BODY
    assert messages in request.body_json
    assert schema in request.body_json


@pytest.mark.parametrize("reader", ANTHROPIC_READERS, ids=lambda r: r.slug)
def test_anthropic_body_keeps_the_message_text(reader: ReaderDeclaration) -> None:
    pack = _pack()
    request = rewrite_pack_body(PACK_BODY, reader)
    body = request.body
    assert body["system"] == pack["messages"][0]["content"]
    assert body["messages"] == [
        {"role": "user", "content": pack["messages"][1]["content"]}
    ]
    assert body["max_tokens"] == pack["max_completion_tokens"]
    assert body["output_config"]["format"] == {
        "type": "json_schema",
        "schema": pack["response_format"]["json_schema"]["schema"],
    }
    assert body["model"] == reader.slug


def test_anthropic_sonnet_thinks_between_tools() -> None:
    body = rewrite_pack_body(PACK_BODY, SONNET_ANTHROPIC).body
    assert body["thinking"] == {"type": "between_tools"}
    assert "effort" not in body["output_config"]


def test_anthropic_opus_omits_thinking_and_sets_effort() -> None:
    body = rewrite_pack_body(PACK_BODY, OPUS_ANTHROPIC).body
    assert "thinking" not in body
    assert body["output_config"]["effort"] == "low"


def test_anthropic_off_disables_thinking() -> None:
    reader = ReaderDeclaration(
        slug="claude-haiku-5-5",
        target="anthropic",
        thinking="off",
        price=ReaderPrice(input_per_mtok=0.10, output_per_mtok=0.50),
    )
    body = rewrite_pack_body(PACK_BODY, reader).body
    assert body["thinking"] == {"type": "disabled"}


def test_anthropic_rewrite_reports_every_pack_field() -> None:
    request = rewrite_pack_body(PACK_BODY, SONNET_ANTHROPIC)
    assert set(request.rewritten_fields) == set(_pack()) | set(request.body)


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_no_body_carries_cache_control_or_sampling(name: str) -> None:
    request = rewrite_pack_body(PACK_BODY, GOLDENS[name])
    for key in ("cache_control", "temperature", "top_p"):
        assert f'"{key}"' not in request.body_json


@pytest.mark.parametrize("name", sorted(GOLDENS))
def test_body_json_is_the_body(name: str) -> None:
    request = rewrite_pack_body(PACK_BODY, GOLDENS[name])
    assert json.loads(request.body_json) == request.body


def test_unexpected_pack_field_is_refused() -> None:
    body = _pack()
    body["seed"] = 7
    with pytest.raises(ReaderRequestError, match="seed"):
        rewrite_pack_body(_compact(body), HAIKU_OPENROUTER)


def test_missing_pack_field_is_refused() -> None:
    body = _pack()
    del body["response_format"]
    with pytest.raises(ReaderRequestError, match="response_format"):
        rewrite_pack_body(_compact(body), HAIKU_OPENROUTER)


def test_non_compact_pack_body_is_refused() -> None:
    # A body this module cannot reproduce byte for byte breaks "every other byte".
    with pytest.raises(ReaderRequestError, match="byte"):
        rewrite_pack_body(json.dumps(_pack(), indent=1), HAIKU_OPENROUTER)


def test_unreadable_pack_body_is_refused() -> None:
    with pytest.raises(ReaderRequestError):
        rewrite_pack_body("{not json", HAIKU_OPENROUTER)


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": "q"}],
        [{"role": "user", "content": "a"}, {"role": "system", "content": "b"}],
        [{"role": "system", "content": "a"}, {"role": "user", "content": 3}],
    ],
)
def test_anthropic_refuses_messages_it_cannot_convert(messages: list[Any]) -> None:
    body = _pack()
    body["messages"] = messages
    raw = _compact(body)
    with pytest.raises(ReaderRequestError, match="messages"):
        rewrite_pack_body(raw, SONNET_ANTHROPIC)


def test_anthropic_refuses_a_non_strict_schema() -> None:
    body = _pack()
    body["response_format"]["json_schema"]["strict"] = False
    raw = _compact(body)
    with pytest.raises(ReaderRequestError, match="strict"):
        rewrite_pack_body(raw, SONNET_ANTHROPIC)


def test_unknown_target_is_refused() -> None:
    with pytest.raises(ReaderRequestError, match="target"):
        ReaderDeclaration(
            slug="x",
            target="bedrock",  # type: ignore[arg-type]
            thinking="off",
            price=ReaderPrice(input_per_mtok=1.0, output_per_mtok=1.0),
        )


def test_unknown_thinking_is_refused() -> None:
    with pytest.raises(ReaderRequestError, match="thinking"):
        ReaderDeclaration(
            slug="x",
            target="openrouter",
            thinking="adaptive",  # type: ignore[arg-type]
            price=ReaderPrice(input_per_mtok=1.0, output_per_mtok=1.0),
        )


@pytest.mark.parametrize(
    ("thinking", "effort"),
    [("on", None), ("off", "low"), ("between_tools", "low"), ("on", "extreme")],
)
def test_effort_goes_with_thinking_on_only(thinking: str, effort: str | None) -> None:
    with pytest.raises(ReaderRequestError, match="effort"):
        ReaderDeclaration(
            slug="x",
            target="anthropic",
            thinking=thinking,  # type: ignore[arg-type]
            effort=effort,  # type: ignore[arg-type]
            price=ReaderPrice(input_per_mtok=1.0, output_per_mtok=1.0),
        )


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_bad_price_is_refused(value: float) -> None:
    with pytest.raises(ReaderRequestError, match="price"):
        ReaderPrice(input_per_mtok=value, output_per_mtok=1.0)


def test_requests_share_no_mutable_state() -> None:
    first = rewrite_pack_body(PACK_BODY, HAIKU_OPENROUTER)
    first.body["provider"]["only"].append("other")
    second = rewrite_pack_body(PACK_BODY, HAIKU_OPENROUTER)
    assert second.body["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}


def test_declaration_is_a_frozen_constant() -> None:
    with pytest.raises(AttributeError):
        HAIKU_OPENROUTER.slug = "other"  # type: ignore[misc]
    assert hash(HAIKU_OPENROUTER) == hash(
        ReaderDeclaration(
            slug="anthropic/claude-haiku-5.5",
            target="openrouter",
            thinking="off",
            price=ReaderPrice(input_per_mtok=0.10, output_per_mtok=0.50),
        )
    )


def test_fixture_schema_has_the_engine_key_order() -> None:
    # The engine's serde_json has no `preserve_order`: `json!` objects come out sorted.
    schema = _pack()["response_format"]["json_schema"]["schema"]
    assert _compact(schema) == json.dumps(
        schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
