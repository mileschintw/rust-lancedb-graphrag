"""#169: sampling relations one writer has and the other lacks; judging; reporting."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from lancet_eval import relation_precision as rp


def _answer(*relations: tuple[str, str]) -> dict[str, object]:
    return {
        "entities": [],
        "relations": [
            {"source": s, "target": t, "relation_type": "rel", "confidence": 0.9}
            for s, t in relations
        ],
    }


def test_an_extra_relation_is_an_end_pair_the_other_writer_lacks() -> None:
    writer = {
        "c1": _answer(("Bears", "Johnson"), ("Bears", "NFL"), ("nfl", "bears")),
        "c2": _answer(("A", "B")),
        "c3": _answer(("X", "Y")),
    }
    # Reversed and re-cased ends are the same pair; c3 has no answer from the other.
    other = {"c1": _answer(("johnson", "BEARS")), "c2": _answer(("A", "B"))}
    extra = rp.extra_relations(writer, other)
    assert list(extra) == ["c1"]
    # "nfl"-"bears" repeats the Bears-NFL pair, so it is one extra relation.
    assert [(r["source"], r["target"]) for r in extra["c1"]] == [("Bears", "NFL")]


def test_the_sample_takes_one_relation_from_each_of_n_distinct_chunks() -> None:
    extra = {
        f"c{i}": [{"source": "a", "target": f"b{i}", "relation_type": "r"}] * 3
        for i in range(10)
    }
    rows = rp.stratified_sample(
        extra, 4, writer="haiku-5.5", other="deepseek", rng=random.Random(1), prefix="h"
    )
    assert [r.id for r in rows] == ["h001", "h002", "h003", "h004"]
    assert len({r.custom_id for r in rows}) == 4
    again = rp.stratified_sample(
        extra, 4, writer="haiku-5.5", other="deepseek", rng=random.Random(1), prefix="h"
    )
    assert again == rows


def test_the_judge_body_carries_the_text_and_the_relation_at_temperature_0() -> None:
    relation = rp.Relation(
        "h001", "c1", "haiku-5.5", "deepseek", "Bears", "plays_for", "Johnson"
    )
    body = json.loads(rp.judge_body(relation, "Johnson plays for the Bears."))
    assert body["model"] == rp.JUDGE_MODEL and body["temperature"] == 0
    prompt = body["messages"][0]["content"]
    assert "Johnson plays for the Bears." in prompt
    assert "(Bears) -[plays_for]-> (Johnson)" in prompt


@pytest.mark.parametrize(
    ("content", "verdict"),
    [
        ('{"supported": true}', True),
        ('```json\n{"supported": false}\n```', False),
        ("yes", None),
        ('{"supported": "yes"}', None),
    ],
)
def test_the_verdict_is_read_from_the_json_reply(
    content: str, verdict: bool | None
) -> None:
    assert rp.parse_verdict(content) is verdict


def test_the_report_gives_precision_per_writer_and_judge_and_agreement(
    tmp_path: Path,
) -> None:
    rows = [
        rp.Relation(
            "h001", "c1", "haiku-5.5", "deepseek", "a", "r", "b", judge=True, hand=True
        ),
        rp.Relation(
            "h002", "c2", "haiku-5.5", "deepseek", "a", "r", "b", judge=False, hand=True
        ),
        rp.Relation(
            "d001", "c3", "deepseek", "haiku-5.5", "a", "r", "b", judge=True, hand=None
        ),
    ]
    path = tmp_path / "sample.jsonl"
    rp.write_sample(path, rows)
    assert rp.read_sample(path) == rows
    by = {
        (p.writer, p.judge): p
        for p in rp.precision(rows, "judge") + rp.precision(rows, "hand")
    }
    assert (
        by[("haiku-5.5", "judge")].judged,
        by[("haiku-5.5", "judge")].supported,
    ) == (2, 1)
    assert by[("haiku-5.5", "hand")].supported == 2
    assert ("deepseek", "hand") not in by
    assert rp.agreement(rows) == (1, 2)
    assert rp.usd(1_000_000, 1_000_000) == pytest.approx(sum(rp.JUDGE_PRICE))
    text = rp.render_markdown(rows)
    assert "| haiku-5.5 (over deepseek) | agent, writer hidden | 2 | 2 |" in text
