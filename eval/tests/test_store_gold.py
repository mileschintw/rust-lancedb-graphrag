"""#128: gold chunk sets built from a store's own chunk text."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lancet_eval.client import RankedCandidate, RetrievalSnapshot
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import RunRecord
from lancet_eval.store_gold import (
    StoreGold,
    StoreGoldError,
    build_store_gold_sets,
    load_chunk_text_dump,
    load_store_gold,
    reads_gold_chunk_table,
    unmatched_units,
    write_ranked_ids,
)

FACT_A = "The committee approved the budget on Tuesday."
FACT_B = "Shares of Acme rose four percent."


def _gold(qid: str = "q1", facts: tuple[str, ...] = (FACT_A, FACT_B)) -> GoldQuestion:
    return GoldQuestion(
        question_id=qid,
        question="?",
        question_type="inference_query",
        gold_facts=[f for f in facts if f],
        gold_answer="Yes",
        evidence_list=[{"title": "t", "fact": f} for f in facts],
    )


def _row(chunk_id: str, text: str, digest: str | None = None) -> str:
    sha = digest or hashlib.sha256(text.encode("utf-8")).hexdigest()
    return json.dumps({
        "chunk_id": chunk_id,
        "document_id": "d",
        "chunk_index": 0,
        "content_sha256": sha,
        "text": text,
    })


def _dump(path: Path, rows: dict[str, str]) -> Path:
    path.write_text("".join(_row(c, t) + "\n" for c, t in rows.items()), "utf-8")
    return path


def _record(arm: str, ids: list[str], qid: str = "q1") -> RunRecord:
    return RunRecord(
        corpus="c",
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer="Answer: Yes",
        index_generation="g",
        snapshot=RetrievalSnapshot(
            pre_truncation_ranking=[
                RankedCandidate(chunk_id=c, document_id="d", fused_rank=i)
                for i, c in enumerate(ids, start=1)
            ]
        ),
    )


def test_a_fact_matches_the_ranked_chunks_that_contain_it() -> None:
    texts = {
        "m:1": f"Intro. {FACT_A} More text.",
        "m:2": "Unrelated filler.",
        # D-276 folds: case, punctuation and a plural still contain the fact.
        "m:3": "shares of acme rose four percents, analysts said",
    }
    sets = build_store_gold_sets({"q1": _gold()}, {"q1": list(texts)}, texts)
    assert sets == {"q1": [frozenset({"m:1"}), frozenset({"m:3"})]}


def test_an_unmatched_fact_keeps_its_unit_and_an_empty_fact_has_none() -> None:
    texts = {"m:1": FACT_A}
    sets = build_store_gold_sets(
        {"q1": _gold(facts=(FACT_A, "", FACT_B))}, {"q1": ["m:1"]}, texts
    )
    # The gold-chunk table's probe writes no row for an empty fact.
    assert sets["q1"] == [frozenset({"m:1"}), frozenset()]
    assert unmatched_units(_gold(facts=(FACT_A, "", FACT_B))) == [frozenset()] * 2


def test_a_ranked_chunk_missing_from_the_dump_refuses() -> None:
    with pytest.raises(StoreGoldError, match="lacks 1 ranked chunk ID"):
        build_store_gold_sets({"q1": _gold()}, {"q1": ["m:1", "m:9"]}, {"m:1": FACT_A})


def test_the_dump_digest_is_checked(tmp_path: Path) -> None:
    path = tmp_path / "dump.jsonl"
    path.write_text(_row("m:1", FACT_A, digest="0" * 64) + "\n", "utf-8")
    with pytest.raises(StoreGoldError, match="content_sha256"):
        load_chunk_text_dump(path)


def test_each_record_reads_its_own_store(tmp_path: Path) -> None:
    v1 = {"q1": [frozenset({"v:1"}), frozenset({"v:2"})]}
    records = [
        _record("small/hybrid+rerank+metadata", ["v:1", "v:2"]),
        _record("merged/hybrid+rerank+metadata", ["m:2", "m:1"]),
    ]
    dump = _dump(tmp_path / "merged.jsonl", {"m:1": FACT_A, "m:2": FACT_B})
    gold = load_store_gold(v1, records, {"q1": _gold()}, {"merged": dump})
    assert gold.sets_for(records[0]) == v1["q1"]
    assert gold.sets_for(records[1]) == [frozenset({"m:1"}), frozenset({"m:2"})]
    assert gold.sets_for(_record("hybrid+rerank+metadata", ["v:1"])) == v1["q1"]


def test_a_store_without_a_dump_is_not_evaluable() -> None:
    gold = StoreGold(v1={"q1": [frozenset({"v:1"})]}, stores={})
    assert gold.sets_for(_record("merged/hybrid+rerank+metadata", ["m:1"])) is None
    assert gold.sets_for(_record("full/hybrid+rerank+metadata", ["f:1"])) is None


def test_a_dump_key_must_name_a_non_v1_store(tmp_path: Path) -> None:
    dump = _dump(tmp_path / "d.jsonl", {"m:1": FACT_A})
    for key in ("small", "eval", "nowhere"):
        with pytest.raises(StoreGoldError):
            load_store_gold({}, [], {}, {key: dump})
    # A store name works as well as its prefix.
    load_store_gold({}, [], {}, {"eval-s1": dump})


def test_only_lancet_arms_on_the_v1_store_read_the_table() -> None:
    assert reads_gold_chunk_table("hybrid+rerank+metadata")
    assert reads_gold_chunk_table("small/hybrid+rerank+metadata")
    assert not reads_gold_chunk_table("merged/hybrid+rerank+metadata")
    assert not reads_gold_chunk_table("full/hybrid+rerank+metadata")
    assert not reads_gold_chunk_table("small/hybrid+rerank+metadata@haiku-5.5")


def test_the_cli_passes_each_chunk_text_dump_by_store(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    from lancet_eval import lever_comparison
    from lancet_eval.cli import app

    seen: dict[str, object] = {}

    def fake_write(run, *, chunk_text=None):  # type: ignore[no-untyped-def]
        seen["chunk_text"] = chunk_text
        raise lever_comparison.LeverComparisonError("stop here")

    monkeypatch.setattr(lever_comparison, "write_lever_comparison", fake_write)
    args = ["compare-levers", "--run", str(tmp_path)]
    result = CliRunner().invoke(
        app, [*args, "--chunk-text", "merged=m.jsonl", "--chunk-text", "full=f.jsonl"]
    )
    assert result.exit_code == 1
    assert seen["chunk_text"] == {"merged": Path("m.jsonl"), "full": Path("f.jsonl")}
    bad = CliRunner().invoke(app, [*args, "--chunk-text", "merged"])
    assert bad.exit_code == 2
    assert "STORE=PATH" in bad.output


def test_chunk_ids_lists_one_stores_ranked_ids_and_its_generation(tmp_path) -> None:
    from typer.testing import CliRunner

    from lancet_eval.cli import app
    from lancet_eval.journal import Journal

    run = tmp_path / "run"
    journal = Journal(run / "journal.jsonl")
    journal.write_header(corpus="c", partial=False)
    journal.append(_record("small/hybrid+rerank+metadata", ["v:1", "v:2"]))
    journal.append(_record("merged/hybrid+rerank+metadata", ["m:2", "m:1"]))
    journal.append(_record("merged/hybrid+rerank+metadata", ["m:1", "m:3"], "q2"))
    out = tmp_path / "ids.jsonl"
    args = ["chunk-ids", "--run", str(run), "--out", str(out)]
    result = CliRunner().invoke(app, [*args, "--store", "merged"])
    assert result.exit_code == 0, result.output
    assert "index_generation g" in result.output
    lines = out.read_text("utf-8").splitlines()
    assert [json.loads(line)["chunk_id"] for line in lines] == ["m:2", "m:1", "m:3"]
    assert CliRunner().invoke(app, [*args, "--store", "full"]).exit_code == 1


def test_chunk_ids_refuses_mixed_index_generations(tmp_path) -> None:
    a = _record("merged/hybrid+rerank+metadata", ["m:1"])
    b = _record("merged/hybrid+rerank+metadata", ["m:2"], "q2")
    b = b.model_copy(update={"index_generation": "other"})
    with pytest.raises(StoreGoldError, match="a dump pins exactly one"):
        write_ranked_ids([a, b], "merged", tmp_path / "ids.jsonl")


def test_the_cli_refuses_a_store_named_twice(tmp_path) -> None:
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    for command in ("score", "compare-levers"):
        result = CliRunner().invoke(
            app,
            [command, "--run", str(tmp_path), "--chunk-text", "merged=a.jsonl"]
            + ["--chunk-text", "merged=b.jsonl"],
        )
        assert result.exit_code == 2, command
        assert "twice" in result.output, command


def test_score_passes_each_chunk_text_dump_by_store(monkeypatch, tmp_path) -> None:
    from typer.testing import CliRunner

    from lancet_eval import score
    from lancet_eval.cli import app

    seen: dict[str, object] = {}

    def fake_score(**kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        raise score.ScoreError("stop here")

    monkeypatch.setattr(score, "score_run", fake_score)
    result = CliRunner().invoke(
        app, ["score", "--run", str(tmp_path), "--chunk-text", "full=f.jsonl"]
    )
    assert result.exit_code == 1
    assert seen["chunk_text"] == {"full": Path("f.jsonl")}
