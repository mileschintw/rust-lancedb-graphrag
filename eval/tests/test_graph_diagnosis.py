"""Tests for lancet_eval.graph_diagnosis: the D-137 rule, predicates and table.

Synthetic fixtures only. No store, no class count of the real 38 questions: the one
read of the real journal is a parse check of the population size.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from lancet_eval import gitcheck, graph_diagnosis, thresholds
from lancet_eval.client import Notice
from lancet_eval.diagnostic import _normalize_name
from lancet_eval.graph_diagnosis import (
    DumpEntity,
    GraphDiagnosisError,
    GraphDump,
    QuestionEvidence,
    SeedInfo,
    build_table,
    class_counts,
    classify_question,
    is_absent,
    is_alias_split,
    is_missing_edge,
    memberships,
    normalize_tokens,
    population,
    select_from_table,
    select_lever2,
    spot_check_sample,
    tokens_contained,
)
from lancet_eval.journal import RunRecord, WorkflowWireMeta

RULE = thresholds.GRAPH_REPAIR_RULE_06_3_6
REAL_JOURNAL = (
    Path(__file__).resolve().parents[2]
    / "eval/runs/2026-10-06-drive2-multihop_rag_diag/journal.jsonl"
)

# --- select_lever2: the seven synthetic shapes and the two refusals ------------------


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        (
            {"alias_split": 10, "absent": 5, "missing_edge": 3, "other": 2},
            "entity_resolution",
        ),
        ({"alias_split": 2, "absent": 10, "missing_edge": 3, "other": 5}, "none"),
        (
            {"alias_split": 2, "absent": 5, "missing_edge": 10, "other": 3},
            "graph_list_precision",
        ),
        (
            {"alias_split": 2, "absent": 5, "missing_edge": 3, "other": 10},
            "graph_list_precision",
        ),
        (
            {"alias_split": 8, "absent": 8, "missing_edge": 3, "other": 2},
            "graph_list_precision",
        ),
        (
            {"alias_split": 8, "absent": 3, "missing_edge": 8, "other": 2},
            "graph_list_precision",
        ),
        (
            {"alias_split": 5, "absent": 5, "missing_edge": 5, "other": 5},
            "graph_list_precision",
        ),
    ],
    ids=[
        "alias-plurality",
        "absent-plurality",
        "missing-edge-plurality",
        "other-plurality",
        "tie-alias-absent",
        "tie-alias-missing-edge",
        "four-way-tie",
    ],
)
def test_select_lever2_seven_shapes(counts: dict[str, int], expected: str) -> None:
    assert select_lever2(counts) == expected


def test_select_lever2_refuses_a_missing_class() -> None:
    with pytest.raises(ValueError, match="exactly the four classes"):
        select_lever2({"alias_split": 1, "absent": 1, "missing_edge": 1})


def test_select_lever2_refuses_an_extra_class() -> None:
    counts = {"alias_split": 1, "absent": 1, "missing_edge": 1, "other": 1, "x": 1}
    with pytest.raises(ValueError, match="exactly the four classes"):
        select_lever2(counts)


def test_select_lever2_refuses_a_negative_count() -> None:
    with pytest.raises(ValueError, match="counts >= 0"):
        select_lever2({"alias_split": -1, "absent": 1, "missing_edge": 1, "other": 1})


# --- the rule constant ----------------------------------------------------------------


def test_the_rule_precedence_is_the_d171_skeleton_order() -> None:
    assert RULE.precedence == ("alias_split", "absent", "missing_edge", "other")
    assert RULE.classes == ("alias_split", "absent", "missing_edge", "other")


def test_the_rule_declares_the_population_and_the_outcomes() -> None:
    assert isinstance(RULE, thresholds.GraphRepairRule)
    assert RULE.expected_count == 38
    assert "typed_code 10" in RULE.population
    assert "graph-on" in RULE.population
    assert set(RULE.outcomes) == {
        "alias_split -> entity_resolution",
        "missing_edge -> graph_list_precision",
        "other -> graph_list_precision",
        "absent -> none",
        "any tie -> graph_list_precision",
    }
    for ref in ("D-137", "D-167", "D-171"):
        assert ref in RULE.provenance
    assert "under-detect vector-only aliases" in RULE.provenance


def test_the_rule_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        RULE.expected_count = 1  # type: ignore[misc]


def test_the_rule_holds_no_similarity_threshold() -> None:
    for field in dataclasses.fields(RULE):
        assert not isinstance(getattr(RULE, field.name), float), field.name


def test_the_predicate_module_holds_no_float_literal() -> None:
    tree = ast.parse(Path(graph_diagnosis.__file__).read_text(encoding="utf-8"))
    floats = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, float)
    ]
    assert floats == []


# --- name normalisation and token containment -----------------------------------------


def _rust_normalize_name(name: str) -> str:
    """A transcription of `graph::index::normalize_name` (engine/src/graph/index.rs)."""
    words: list[str] = []
    current = ""
    for ch in name.lower():
        if ch.isalnum():
            current += ch
        elif current:
            words.append(current)
            current = ""
    if current:
        words.append(current)
    if len(words) > 1 and words[0] == "the":
        words = words[1:]
    return " ".join(words)


@pytest.mark.parametrize(
    "name",
    [
        "The Walt_Disney Co 2023",
        "Société Générale",
        "CBSSports.com",
        "The Beta-Group",
        "the",
        "The The Cat",
        "___",
        "",
        "Zürich 2024_Q3",
    ],
)
def test_normalize_tokens_matches_the_engine_normalize_name(name: str) -> None:
    assert " ".join(normalize_tokens(name)) == _rust_normalize_name(name)
    assert " ".join(normalize_tokens(name)) == _normalize_name(name)


def test_normalize_tokens_examples() -> None:
    assert normalize_tokens("The Walt_Disney Co 2023") == (
        "walt",
        "disney",
        "co",
        "2023",
    )
    assert normalize_tokens("Société Générale") == ("société", "générale")
    assert normalize_tokens("The") == ("the",)


def test_token_containment_is_token_not_substring() -> None:
    assert tokens_contained(
        normalize_tokens("Disney"), normalize_tokens("Walt Disney Company")
    )
    assert tokens_contained(
        normalize_tokens("Walt Disney Company"), normalize_tokens("Disney")
    )
    assert not tokens_contained(
        normalize_tokens("Disney"), normalize_tokens("Disneyland")
    )
    assert not tokens_contained((), normalize_tokens("Disney"))
    assert not tokens_contained((), ())


# --- predicate fixtures ---------------------------------------------------------------


def _ent(
    entity_id: str, name: str, entity_type: str = "ORG", chunks: tuple[str, ...] = ()
) -> DumpEntity:
    return DumpEntity(entity_id, name, entity_type, chunks)


def _q(**overrides: object) -> QuestionEvidence:
    base: dict[str, object] = {
        "question_id": "q",
        "mentions": (),
        "seeds": (),
        "paths": (),
        "gold_chunk_ids": frozenset({"c1"}),
        "path_found": False,
        "degree_capped_count": 0,
    }
    base.update(overrides)
    return QuestionEvidence(**base)  # type: ignore[arg-type]


def _alias_world(
    *, alias_type: str = "ORG", alias_chunks: tuple[str, ...] = ("c1",)
) -> tuple[QuestionEvidence, GraphDump]:
    """Seeds A "Disney Studios" and B "Pixar"; alias E "Disney" has an edge to B."""
    dump = GraphDump(
        [
            _ent("A", "Disney Studios"),
            _ent("B", "Pixar"),
            _ent("E", "Disney", alias_type, alias_chunks),
        ],
        [("E", "B")],
    )
    q = _q(
        mentions=("Disney Studios", "Pixar"),
        seeds=(SeedInfo("A", "Disney Studios"), SeedInfo("B", "Pixar")),
    )
    return q, dump


def test_alias_split_pair_holds_with_a_gold_citing_same_type_alias_edge_to_b() -> None:
    q, dump = _alias_world()
    assert is_alias_split(q, dump)
    assert graph_diagnosis.alias_split_witnesses(q, dump) == ["E"]


def test_alias_split_pair_needs_the_same_entity_type() -> None:
    q, dump = _alias_world(alias_type="PERSON")
    assert not is_alias_split(q, dump)


def test_alias_split_pair_needs_the_alias_to_cite_a_gold_chunk() -> None:
    q, dump = _alias_world(alias_chunks=("c9",))
    assert not is_alias_split(q, dump)


def test_alias_split_pair_is_not_a_split_when_a_probe_path_already_connects_them() -> (
    None
):
    q, dump = _alias_world()
    connected = dataclasses.replace(q, paths=(frozenset({"A", "X", "B"}),))
    assert not is_alias_split(connected, dump)


def test_alias_split_pair_needs_the_edge_to_the_other_seed() -> None:
    dump = GraphDump(
        [
            _ent("A", "Disney Studios"),
            _ent("B", "Pixar"),
            _ent("E", "Disney", "ORG", ("c1",)),
        ],
        [("E", "A")],
    )
    q = _q(seeds=(SeedInfo("A", "Disney Studios"), SeedInfo("B", "Pixar")))
    assert not is_alias_split(q, dump)


def test_alias_split_mention_case_an_unseeded_mention_next_to_a_seed() -> None:
    dump = GraphDump(
        [_ent("S", "Pixar"), _ent("E", "Walt Disney Company", "ORG", ("c1",))],
        [("S", "E")],
    )
    q = _q(mentions=("Disney", "Pixar"), seeds=(SeedInfo("S", "Pixar"),))
    assert is_alias_split(q, dump)
    # The mention is seeded once a seed names it, so the mention case stops applying
    # (and the new seed pair is already connected by a path).
    seeded = dataclasses.replace(
        q,
        seeds=(SeedInfo("S", "Pixar"), SeedInfo("D", "Disney")),
        paths=(frozenset({"D", "S"}),),
    )
    dump_with_d = GraphDump(
        [
            _ent("S", "Pixar"),
            _ent("D", "Disney"),
            _ent("E", "Walt Disney Company", "ORG", ("c1",)),
        ],
        [("S", "E")],
    )
    assert not is_alias_split(seeded, dump_with_d)


def test_alias_split_refuses_a_seed_missing_from_the_dump() -> None:
    dump = GraphDump([_ent("A", "Disney")], [])
    q = _q(seeds=(SeedInfo("ghost", "Ghost"),))
    with pytest.raises(GraphDiagnosisError, match="not in dump"):
        is_alias_split(q, dump)


def test_absent_holds_for_an_unnamed_mention_with_no_gold_citing_entity() -> None:
    dump = GraphDump([_ent("A", "Pixar", "ORG", ("c9",))], [])
    q = _q(mentions=("Zorblax",))
    assert is_absent(q, dump)


def test_absent_fails_when_an_entity_names_every_mention() -> None:
    dump = GraphDump([_ent("A", "Zorblax Inc", "ORG", ("c9",))], [])
    assert not is_absent(_q(mentions=("Zorblax",)), dump)


def test_absent_fails_when_an_entity_cites_a_gold_chunk() -> None:
    dump = GraphDump([_ent("A", "Pixar", "ORG", ("c1",))], [])
    assert not is_absent(_q(mentions=("Zorblax",)), dump)


def test_absent_ignores_a_mention_without_alphanumerics() -> None:
    dump = GraphDump([_ent("A", "Pixar")], [])
    assert not is_absent(_q(mentions=("---",)), dump)


def _missing_edge_world() -> tuple[QuestionEvidence, GraphDump]:
    dump = GraphDump([_ent("A", "Alpha"), _ent("B", "Beta")], [])
    q = _q(
        mentions=("Alpha", "Beta"),
        seeds=(SeedInfo("A", "Alpha"), SeedInfo("B", "Beta")),
    )
    return q, dump


def test_missing_edge_holds_for_two_seeded_mentions_with_no_path_and_no_cap() -> None:
    q, dump = _missing_edge_world()
    assert is_missing_edge(q, dump)
    assert classify_question(q, dump) == "missing_edge"


@pytest.mark.parametrize(
    "change",
    [
        {"path_found": True},
        {"path_found": None},
        {"degree_capped_count": 2},
        {"degree_capped_count": None},
        {"seeds": (SeedInfo("A", "Alpha"),)},
        {"mentions": ("Alpha", "Beta", "Gamma")},
    ],
    ids=[
        "path-found",
        "path-unrecorded",
        "capped",
        "cap-unrecorded",
        "one-seed",
        "unseeded",
    ],
)
def test_missing_edge_fails_when_a_condition_breaks(change: dict[str, object]) -> None:
    q, dump = _missing_edge_world()
    assert not is_missing_edge(dataclasses.replace(q, **change), dump)  # type: ignore[arg-type]


def test_other_is_the_residual() -> None:
    dump = GraphDump([_ent("A", "Pixar")], [])
    q = _q(mentions=())
    assert memberships(q, dump) == ("other",)
    assert classify_question(q, dump) == "other"


def test_alias_split_and_absent_are_exclusive_by_construction() -> None:
    """alias_split needs a gold-citing entity; absent needs there to be none."""
    q, dump = _alias_world()
    with_unnamed = dataclasses.replace(q, mentions=(*q.mentions, "Zorblax"))
    assert is_alias_split(with_unnamed, dump)
    assert not is_absent(with_unnamed, dump)
    assert memberships(with_unnamed, dump) == ("alias_split",)


def test_classification_is_first_match_in_the_rule_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With overlapping predicates the earliest class in precedence wins."""
    dump = GraphDump([], [])
    q = _q()
    monkeypatch.setattr(graph_diagnosis, "is_alias_split", lambda *_: True)
    monkeypatch.setattr(graph_diagnosis, "is_absent", lambda *_: True)
    monkeypatch.setattr(graph_diagnosis, "is_missing_edge", lambda *_: True)
    assert memberships(q, dump) == ("alias_split", "absent", "missing_edge")
    assert classify_question(q, dump) == "alias_split"
    reordered = dataclasses.replace(
        RULE, precedence=("missing_edge", "absent", "alias_split", "other")
    )
    assert memberships(q, dump, reordered) == ("missing_edge", "absent", "alias_split")
    assert classify_question(q, dump, reordered) == "missing_edge"
    monkeypatch.setattr(graph_diagnosis, "is_alias_split", lambda *_: False)
    assert classify_question(q, dump) == "absent"


# --- the table over a synthetic world -------------------------------------------------

UNAVAILABLE = Notice(code="GRAPH_UNAVAILABLE", message="m", typed_code=10)
GOOD_SHA = "a" * 40
MODULE_SHA = "b" * 40


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _record(question_id: str, arm: str, *, unavailable: bool) -> RunRecord:
    return RunRecord(
        corpus="c",
        question_id=question_id,
        graph_arm=arm,
        outcome="success",
        notices=[UNAVAILABLE] if unavailable else [],
        workflow_meta=WorkflowWireMeta(
            graph_seed_count=0, graph_path_found=False, graph_degree_capped_count=0
        ),
    )


def _make_world(root: Path, n: int) -> dict[str, Path]:
    """`n` questions cycling alias_split, absent, missing_edge, other; plus decoys."""
    entities: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    probe: list[dict[str, object]] = [{"spend_usd": 0.0, "questions": n}]
    gold: list[dict[str, object]] = []
    questions: list[dict[str, object]] = []
    journal_lines = ['{"type": "header", "corpus": "c", "partial": false}']
    for i in range(n):
        qid = f"q{i:03d}"
        shape = i % 4
        chunk = f"d{i}:0"
        seeds: list[dict[str, str]] = []
        mentions: list[str] = []
        if shape == 0:  # alias_split
            a, b, e = f"A{i}", f"B{i}", f"E{i}"
            entities += [
                {
                    "entity_id": a,
                    "name": f"Disney{i} Studios",
                    "entity_type": "ORG",
                    "source_chunk_ids": [],
                },
                {
                    "entity_id": b,
                    "name": f"Pixar{i}",
                    "entity_type": "ORG",
                    "source_chunk_ids": [],
                },
                {
                    "entity_id": e,
                    "name": f"Disney{i}",
                    "entity_type": "ORG",
                    "source_chunk_ids": [chunk],
                },
            ]
            edges.append({
                "edge_id": f"e{i}",
                "source_node_id": e,
                "target_node_id": b,
                "relation_type": "owns",
            })
            seeds = [
                {"entity_id": a, "name": f"Disney{i} Studios"},
                {"entity_id": b, "name": f"Pixar{i}"},
            ]
            mentions = [f"Disney{i} Studios", f"Pixar{i}"]
        elif shape == 1:  # absent
            mentions = [f"Zorblax{i}"]
        elif shape == 2:  # missing_edge
            a, b = f"A{i}", f"B{i}"
            entities += [
                {
                    "entity_id": a,
                    "name": f"Alpha{i}",
                    "entity_type": "ORG",
                    "source_chunk_ids": [chunk],
                },
                {
                    "entity_id": b,
                    "name": f"Beta{i}",
                    "entity_type": "ORG",
                    "source_chunk_ids": [],
                },
            ]
            seeds = [
                {"entity_id": a, "name": f"Alpha{i}"},
                {"entity_id": b, "name": f"Beta{i}"},
            ]
            mentions = [f"Alpha{i}", f"Beta{i}"]
        probe.append({
            "question_id": qid,
            "mentions": mentions,
            "seeds": seeds,
            "paths": [],
        })
        gold.append({"question_id": qid, "evidence_index": 0, "chunk_ids": [chunk]})
        questions.append({
            "query": f"question text {i}",
            "answer": "SECRET",
            "question_type": "inference_query",
            "question_id": qid,
            "evidence_list": [],
        })
        journal_lines.append(
            _record(qid, "graph-on", unavailable=True).model_dump_json()
        )
        # Decoys: the graph-off arm and a graph-on record without the notice.
        journal_lines.append(
            _record(qid, "graph-off", unavailable=False).model_dump_json()
        )
        journal_lines.append(
            _record(f"x{i}", "graph-on", unavailable=False).model_dump_json()
        )
    dump_dir = root / "dump"
    _write_jsonl(dump_dir / "entities.jsonl", entities)
    _write_jsonl(dump_dir / "entity_edges.jsonl", edges)
    meta = {
        "entities_version": 7,
        "entity_edges_version": 5,
        "row_counts": {"entities": len(entities), "entity_edges": len(edges)},
        "sha256": {
            "entities.jsonl": _sha256((dump_dir / "entities.jsonl").read_bytes()),
            "entity_edges.jsonl": _sha256(
                (dump_dir / "entity_edges.jsonl").read_bytes()
            ),
        },
    }
    (dump_dir / "dump_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    journal = root / "journal.jsonl"
    journal.write_text("\n".join(journal_lines) + "\n", encoding="utf-8")
    _write_jsonl(root / "seed_probe.jsonl", probe)
    _write_jsonl(root / "gold_chunks.jsonl", gold)
    _write_jsonl(root / "questions.jsonl", questions)
    return {
        "journal": journal,
        "seed_probe": root / "seed_probe.jsonl",
        "gold_chunks": root / "gold_chunks.jsonl",
        "questions": root / "questions.jsonl",
        "graph_dump": dump_dir,
        "out_dir": root / "out",
    }


@pytest.fixture
def open_gate(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Lets the D-73 gate pass and records how it was called."""
    calls: list[dict[str, object]] = []

    def fake_problems(tokens: tuple[str, ...], **kwargs: object) -> list[str]:
        calls.append({"tokens": tokens, **kwargs})
        return []

    monkeypatch.setattr(gitcheck, "preregistration_problems", fake_problems)
    monkeypatch.setattr(gitcheck, "introducing_commit", lambda *a, **k: GOOD_SHA)
    monkeypatch.setattr(gitcheck, "last_commit_touching", lambda *a, **k: MODULE_SHA)
    return calls


def test_the_population_is_the_graph_on_records_with_the_unavailable_notice(
    tmp_path: Path,
) -> None:
    paths = _make_world(tmp_path, 8)
    pop = population(paths["journal"])
    assert sorted(pop) == [f"q{i:03d}" for i in range(8)]


@pytest.mark.skipif(not REAL_JOURNAL.exists(), reason="drive-2 journal not present")
def test_the_real_journal_population_parses_to_the_expected_size() -> None:
    assert len(population(REAL_JOURNAL)) == RULE.expected_count


def test_table_calls_the_d73_gate_first_and_refuses_on_a_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _make_world(tmp_path, 38)
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def refusing(tokens: tuple[str, ...], **kwargs: object) -> list[str]:
        calls.append((tokens, kwargs))
        return ["no commit introduces the rule"]

    monkeypatch.setattr(gitcheck, "preregistration_problems", refusing)
    with pytest.raises(GraphDiagnosisError, match="D-73 gate refused"):
        build_table(**paths)  # type: ignore[arg-type]
    assert calls == [
        (
            ("GRAPH_REPAIR_RULE_06_3_6",),
            {
                "unchanged_since_introduction": True,
                "require_clean_tree": True,
                "repo": None,
            },
        )
    ]
    assert not paths["out_dir"].exists()


def test_table_refuses_unless_the_population_is_exactly_38(
    tmp_path: Path, open_gate: list[dict[str, object]]
) -> None:
    paths = _make_world(tmp_path, 8)
    with pytest.raises(GraphDiagnosisError, match="exactly 38"):
        build_table(**paths)  # type: ignore[arg-type]
    assert not paths["out_dir"].exists()
    assert open_gate[0]["tokens"] == ("GRAPH_REPAIR_RULE_06_3_6",)


def test_table_refuses_when_a_population_question_is_missing_from_the_questions_file(
    tmp_path: Path, open_gate: list[dict[str, object]]
) -> None:
    paths = _make_world(tmp_path, 38)
    rows = [
        json.loads(line)
        for line in paths["questions"].read_text(encoding="utf-8").splitlines()
    ]
    _write_jsonl(paths["questions"], [r for r in rows if r["question_id"] != "q005"])
    with pytest.raises(GraphDiagnosisError, match="q005"):
        build_table(**paths)  # type: ignore[arg-type]
    assert not paths["out_dir"].exists()


def test_table_refuses_a_seed_missing_from_the_dump(
    tmp_path: Path, open_gate: list[dict[str, object]]
) -> None:
    paths = _make_world(tmp_path, 38)
    probe = [
        json.loads(line)
        for line in paths["seed_probe"].read_text(encoding="utf-8").splitlines()
    ]
    for row in probe:
        if row.get("question_id") == "q000":
            row["seeds"][0]["entity_id"] = "ghost"
    _write_jsonl(paths["seed_probe"], probe)
    with pytest.raises(GraphDiagnosisError, match="not in the graph dump"):
        build_table(**paths)  # type: ignore[arg-type]


def test_table_refuses_a_dump_whose_hash_differs_from_its_meta(
    tmp_path: Path, open_gate: list[dict[str, object]]
) -> None:
    paths = _make_world(tmp_path, 38)
    with open(paths["graph_dump"] / "entities.jsonl", "a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(GraphDiagnosisError, match="sha256"):
        build_table(**paths)  # type: ignore[arg-type]


def test_table_rows_hold_exactly_the_declared_fields_and_the_synthetic_counts(
    tmp_path: Path, open_gate: list[dict[str, object]]
) -> None:
    paths = _make_world(tmp_path, 38)
    counts = build_table(**paths)  # type: ignore[arg-type]
    assert counts == {"alias_split": 10, "absent": 10, "missing_edge": 9, "other": 9}
    rows = [
        json.loads(line)
        for line in (paths["out_dir"] / "graph_diagnosis.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rows) == 38
    for row in rows:
        assert set(row) == set(graph_diagnosis.TABLE_FIELDS)
        assert "question_type" not in row
        assert "answer" not in row
        assert "evidence_list" not in row
        assert "SECRET" not in json.dumps(row)
    first = rows[0]
    assert first["question_text"] == "question text 0"
    assert first["mentions"] == ["Disney0 Studios", "Pixar0"]
    assert first["label"] == "alias_split"
    assert first["memberships"] == ["alias_split"]
    assert first["evidence_ids"]["alias_entity_ids"] == ["E0"]
    assert first["evidence_ids"]["gold_chunk_ids"] == ["d0:0"]
    assert class_counts(rows) == counts


def test_table_header_carries_the_rule_sha_the_inputs_and_the_disclosures(
    tmp_path: Path, open_gate: list[dict[str, object]]
) -> None:
    paths = _make_world(tmp_path, 38)
    build_table(**paths)  # type: ignore[arg-type]
    text = (paths["out_dir"] / "graph_diagnosis.md").read_text(encoding="utf-8")
    assert f"rule_sha: {GOOD_SHA}" in text
    assert f"graph_diagnosis.py last commit: {MODULE_SHA}" in text
    for name in ("journal", "seed_probe", "gold_chunks", "questions", "entities.jsonl"):
        assert f"{name}: " in text
    assert _sha256(paths["questions"].read_bytes()) in text
    assert "dump entities_version: 7" in text
    assert "alias_split > absent > missing_edge > other" in text
    assert "under-detect vector-only aliases" in text
    assert "never hand-edited" in text
    assert "Multi-membership matrix" in text


def test_the_table_is_byte_identical_when_regenerated(
    tmp_path: Path, open_gate: list[dict[str, object]]
) -> None:
    paths = _make_world(tmp_path, 38)
    build_table(**paths)  # type: ignore[arg-type]
    first = {p.name: p.read_bytes() for p in paths["out_dir"].iterdir()}
    build_table(**paths)  # type: ignore[arg-type]
    assert {p.name: p.read_bytes() for p in paths["out_dir"].iterdir()} == first


def test_spot_check_sample_reads_only_the_table_and_is_deterministic(
    tmp_path: Path, open_gate: list[dict[str, object]]
) -> None:
    paths = _make_world(tmp_path, 38)
    build_table(**paths)  # type: ignore[arg-type]
    only = tmp_path / "only"
    only.mkdir()
    table = only / "graph_diagnosis.jsonl"
    table.write_bytes((paths["out_dir"] / "graph_diagnosis.jsonl").read_bytes())
    out_a, out_b = only / "a.md", only / "b.md"
    ids_a = spot_check_sample(table, out_a, seed=42)
    ids_b = spot_check_sample(table, out_b, seed=42)
    assert ids_a == ids_b
    assert out_a.read_bytes() == out_b.read_bytes()
    assert len(ids_a) == 2 * len(RULE.classes)
    text = out_a.read_text(encoding="utf-8")
    for needle in (
        "question:",
        "mentions:",
        "label:",
        "memberships:",
        "gold_chunk_ids:",
    ):
        assert needle in text
    assert "SECRET" not in text
    assert "question_type" not in text


def test_spot_check_sample_takes_every_row_of_a_class_with_fewer_than_two(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "question_id": f"q{i}",
            "question_text": "t",
            "mentions": [],
            "label": label,
            "memberships": [label],
            "evidence_ids": {
                "gold_chunk_ids": [],
                "seed_entity_ids": [],
                "alias_entity_ids": [],
            },
        }
        for i, label in enumerate(["alias_split", "other", "other", "other"])
    ]
    table = tmp_path / "t.jsonl"
    _write_jsonl(table, rows)
    sampled = spot_check_sample(table, tmp_path / "o.md", seed=42)
    assert "q0" in sampled
    assert len(sampled) == 3


# --- git order, over a throwaway repository -------------------------------------------

THRESHOLDS = gitcheck.THRESHOLDS_PATH
T0 = 1_700_000_000


def _git(repo: Path, *args: str, when: int | None = None) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(repo.parent / "empty.gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if when is not None:
        env["GIT_AUTHOR_DATE"] = f"{when} +0000"
        env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    res = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=repo,
        shell=False,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return res.stdout.strip()


def _commit(repo: Path, message: str, when: int) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, when=when)


@pytest.fixture
def throwaway(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("repo-parent")
    root = base / "throwaway"
    root.mkdir()
    (base / "empty.gitconfig").write_text("", encoding="utf-8")
    _git(root, "init", "-q")
    path = root / THRESHOLDS
    path.parent.mkdir(parents=True)
    path.write_bytes(b"BASELINE = 1\n")
    _commit(root, "baseline without the rule", T0)
    return root


def test_a_table_generated_before_the_rule_commit_is_refused(
    tmp_path: Path, throwaway: Path
) -> None:
    paths = _make_world(tmp_path, 38)
    with pytest.raises(GraphDiagnosisError, match="no commit .* introduces"):
        build_table(repo=throwaway, **paths)  # type: ignore[arg-type]
    assert not paths["out_dir"].exists()


def test_a_table_after_the_rule_commit_but_with_an_edited_rule_is_refused(
    tmp_path: Path, throwaway: Path
) -> None:
    path = throwaway / THRESHOLDS
    path.write_bytes(b"BASELINE = 1\nGRAPH_REPAIR_RULE_06_3_6 = 2\n")
    _commit(throwaway, "the rule", T0 + 100)
    path.write_bytes(b"BASELINE = 1\nGRAPH_REPAIR_RULE_06_3_6 = 3\n")
    _commit(throwaway, "tuned after data", T0 + 200)
    paths = _make_world(tmp_path, 38)
    with pytest.raises(GraphDiagnosisError, match="must not change after commit"):
        build_table(repo=throwaway, **paths)  # type: ignore[arg-type]
    assert not paths["out_dir"].exists()


def test_the_gate_passes_after_the_rule_commit_over_a_clean_tree(
    throwaway: Path,
) -> None:
    path = throwaway / THRESHOLDS
    path.write_bytes(b"BASELINE = 1\nGRAPH_REPAIR_RULE_06_3_6 = 2\n")
    _commit(throwaway, "the rule", T0 + 100)
    assert (
        gitcheck.preregistration_problems(
            ("GRAPH_REPAIR_RULE_06_3_6",),
            unchanged_since_introduction=True,
            require_clean_tree=True,
            repo=throwaway,
        )
        == []
    )


def test_select_writes_the_selection_from_the_committed_table(
    tmp_path: Path, throwaway: Path
) -> None:
    path = throwaway / THRESHOLDS
    path.write_bytes(b"BASELINE = 1\nGRAPH_REPAIR_RULE_06_3_6 = 2\n")
    _commit(throwaway, "the rule", T0 + 100)
    rows = [
        {
            "question_id": f"q{i}",
            "question_text": "t",
            "mentions": [],
            "label": label,
            "memberships": [label],
            "evidence_ids": {},
        }
        for i, label in enumerate(["alias_split"] * 3 + ["other"] * 2 + ["absent"])
    ]
    table = throwaway / "diagnostic" / "graph_diagnosis.jsonl"
    _write_jsonl(table, rows)
    out = throwaway / "diagnostic" / "selection.json"
    with pytest.raises(GraphDiagnosisError, match="dirty"):
        select_from_table(table, out, repo=throwaway)
    _commit(throwaway, "the table", T0 + 200)
    record = select_from_table(table, out, repo=throwaway)
    assert record["selected"] == "entity_resolution"
    assert record["counts"] == {
        "alias_split": 3,
        "absent": 1,
        "missing_edge": 0,
        "other": 2,
    }
    assert record["rule_sha"] == gitcheck.introducing_commit(
        "GRAPH_REPAIR_RULE_06_3_6", THRESHOLDS, repo=throwaway
    )
    assert record["table_sha256"] == _sha256(table.read_bytes())
    assert record["graph_diagnosis_commit"] == _git(throwaway, "rev-parse", "HEAD")
    assert set(json.loads(out.read_text(encoding="utf-8"))) == {
        "selected",
        "counts",
        "rule_sha",
        "table_sha256",
        "graph_diagnosis_commit",
    }
