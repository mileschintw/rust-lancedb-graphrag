"""Tests for lancet_eval.diagnostic: the per-question diagnostic table builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lancet_eval.client import NodeFailed
from lancet_eval.diagnostic import (
    ArmResult,
    DiagnosticError,
    DiagnosticRow,
    _compose_label,
    _question_c,
    build_gold_coverage_rows,
    build_rows,
    classify_record,
    compute_populations,
    main,
    summarize_seed_probe,
    write_gold_coverage,
    write_table,
)
from lancet_eval.journal import RunRecord
from lancet_eval.seed import load_document_map

FIXTURES = Path(__file__).parent / "fixtures" / "diagnostic"
GOLD_CHUNKS = FIXTURES / "gold_chunks.jsonl"
JOURNAL_SLICE = FIXTURES / "journal_slice.jsonl"
VECTOR_TOP4 = FIXTURES / "vector_top4.jsonl"
CORPUS = "multihop_rag"


def _row(rows: list[DiagnosticRow], question_id: str) -> DiagnosticRow:
    for row in rows:
        if row.question_id == question_id:
            return row
    raise AssertionError(f"question_id {question_id!r} not found in built rows")


def test_build_rows_covers_full_corpus_sorted_by_question_id() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    assert len(rows) == 500
    ids = [row.question_id for row in rows]
    assert ids == sorted(ids)


def test_all_in_chunk_question_is_yes_yes() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-0073ab564e55")

    assert row.is_null is False
    assert row.a_gold_doc_in_map is True
    assert row.b_items == ["in_chunk", "in_chunk"]
    assert row.b_gold_chunk_in_lancedb is True
    assert row.in_gold_in_index_subset is True

    assert row.arms["graph-off"].outcome == "success"
    assert row.arms["graph-on"].outcome == "error"
    # graph-off fixture answer ends "Answer: Yes"; real gold_answer is "Yes".
    assert row.arms["graph-off"].answer_usable is True
    assert row.arms["graph-off"].final_answer_missing is False
    assert row.arms["graph-off"].final_answer == "yes"
    assert row.arms["graph-off"].error_class is None
    # graph-on fixture record has error_type="StreamDeadlineExceeded".
    assert row.arms["graph-on"].error_class == "timeout"
    assert row.e_answer_usable is True


def test_split_item_question_fails_b_and_index_subset() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-0085f76defbe")

    assert row.is_null is False
    assert row.a_gold_doc_in_map is True
    assert row.b_items == ["in_chunk", "split_across_chunks"]
    # D-63: question-level (b) is yes only when EVERY item is in_chunk.
    assert row.b_gold_chunk_in_lancedb is False
    # A split fact can never be a Recall@4 hit, so it must not enter G.
    assert row.in_gold_in_index_subset is False

    assert row.arms["graph-off"].outcome == "success"
    # No graph-on record exists for this question in the fixture journal.
    assert row.arms["graph-on"].outcome == "not_run"


def test_null_question_has_none_ab_and_excluded_from_subset() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-0279d4a349c3")

    assert row.is_null is True
    assert row.a_gold_doc_in_map is None
    assert row.b_items == []
    assert row.b_gold_chunk_in_lancedb is None
    # D-72: null questions are always excluded from the G/SC-3 subset.
    assert row.in_gold_in_index_subset is False

    assert row.arms["graph-off"].outcome == "success"
    assert row.arms["graph-on"].outcome == "not_run"
    # D-72: null questions never get answer_usable populated...
    assert row.arms["graph-off"].answer_usable is None
    # ...but final_answer/final_answer_missing still are (abstention context).
    assert row.arms["graph-off"].final_answer == "insufficient information"
    assert row.arms["graph-off"].final_answer_missing is False
    assert row.e_answer_usable is None


def test_question_with_no_journal_record_is_not_run_on_every_arm() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-012f1f51ac88")

    assert row.is_null is False
    assert row.a_gold_doc_in_map is True
    assert row.b_gold_chunk_in_lancedb is True
    assert row.in_gold_in_index_subset is True

    assert row.arms["graph-off"].outcome == "not_run"
    assert row.arms["graph-on"].outcome == "not_run"


def test_build_rows_without_journal_leaves_arms_empty() -> None:
    rows = build_rows(CORPUS, None, GOLD_CHUNKS)
    row = _row(rows, "mhr-0073ab564e55")
    assert row.arms == {}
    # (a)/(b) are independent of the journal and still populate.
    assert row.a_gold_doc_in_map is True
    assert row.b_gold_chunk_in_lancedb is True


def test_duplicate_journal_record_raises_diagnostic_error(tmp_path: Path) -> None:
    lines = JOURNAL_SLICE.read_text(encoding="utf-8").splitlines()
    # Duplicate the graph-off record for mhr-0073ab564e55 (line index 1).
    duplicated = lines + [lines[1]]
    dup_path = tmp_path / "journal_with_duplicate.jsonl"
    dup_path.write_text("\n".join(duplicated) + "\n", encoding="utf-8")

    with pytest.raises(DiagnosticError):
        build_rows(CORPUS, dup_path, GOLD_CHUNKS)


def test_write_table_emits_one_jsonl_line_per_row_and_md_header(tmp_path: Path) -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    subset = rows[:5]

    write_table(
        subset,
        tmp_path,
        label="unit-test",
        journal_path=JOURNAL_SLICE,
        gold_chunks_path=GOLD_CHUNKS,
    )

    jsonl_path = tmp_path / "table.jsonl"
    md_path = tmp_path / "table.md"
    assert jsonl_path.is_file()
    assert md_path.is_file()

    jsonl_lines = jsonl_path.read_text(encoding="utf-8").strip("\n").split("\n")
    assert len(jsonl_lines) == len(subset)
    for line, row in zip(jsonl_lines, subset, strict=True):
        parsed = json.loads(line)
        assert parsed["question_id"] == row.question_id

    md_lines = md_path.read_text(encoding="utf-8").splitlines()
    assert md_lines[0] == "unit-test"
    assert "records=5" in md_lines[1]
    assert "question_id" in md_lines[3]
    assert "graph-on outcome" in md_lines[3]
    assert "final_answer_missing (graph-off)" in md_lines[3]


def test_compose_label_discloses_partial_run_with_count() -> None:
    label = _compose_label("pre-reconcile", JOURNAL_SLICE, row_count=500)
    assert "partial-run diagnostic" in label
    assert "n=500" in label
    assert label.startswith("pre-reconcile")


def test_compose_label_passthrough_without_journal() -> None:
    assert _compose_label("pre-reconcile", None, row_count=500) == "pre-reconcile"


def test_compose_label_passthrough_when_journal_not_partial(tmp_path: Path) -> None:
    non_partial = tmp_path / "journal_complete.jsonl"
    header = {"type": "header", "corpus": "multihop_rag", "partial": False}
    non_partial.write_text(json.dumps(header) + "\n", encoding="utf-8")
    assert _compose_label("full-run", non_partial, row_count=500) == "full-run"


def test_arm_result_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ArmResult(arm="graph-off", outcome="success", not_a_real_field=True)  # type: ignore[call-arg]


# --- D-69/RESEARCH §B: classify_record error-class mapping ---


def _base_record(**overrides: object) -> RunRecord:
    fields: dict[str, object] = {
        "corpus": "multihop_rag",
        "question_id": "q-1",
        "graph_arm": "graph-off",
        "outcome": "error",
    }
    fields.update(overrides)
    return RunRecord(**fields)  # type: ignore[arg-type]


def test_classify_record_none_for_success_outcome() -> None:
    record = RunRecord(
        corpus="multihop_rag",
        question_id="q-1",
        graph_arm="graph-off",
        outcome="success",
        answer="Answer: Yes",
    )
    assert classify_record(record) is None


def test_classify_record_citation_basis_mixed() -> None:
    message = "answer basis 'mixed' requires at least one cited evidence ID"
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message=message,
                retryable=False,
            )
        ]
    )
    assert classify_record(record) == "citation_basis_mixed"


def test_classify_record_citation_basis_retrieval() -> None:
    message = "answer basis 'retrieval' requires at least one cited evidence ID"
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message=message,
                retryable=False,
            )
        ]
    )
    assert classify_record(record) == "citation_basis_retrieval"


def test_classify_record_model_only_unsupported() -> None:
    message = "ModelOnly answer basis is not supported on Phase 03 QueryRAG path"
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message=message,
                retryable=False,
            )
        ]
    )
    assert classify_record(record) == "model_only_unsupported"


def test_classify_record_citation_marker_mismatch() -> None:
    message = "mismatch between cited_evidence_ids ({'1'}) and inline markers (set())"
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="GenerateAnswer",
                error_kind=3,
                error_message=message,
                retryable=False,
            )
        ]
    )
    assert classify_record(record) == "citation_marker_mismatch"


def test_classify_record_node_timeout_error_kind_one() -> None:
    record = _base_record(
        node_failures=[
            NodeFailed(
                node_name="RetrieveHybrid",
                error_kind=1,
                error_message="node timeout",
                retryable=True,
            )
        ]
    )
    assert classify_record(record) == "timeout"


def test_classify_record_harness_deadline_is_timeout() -> None:
    record = _base_record(error_type="StreamDeadlineExceeded", error="exceeded 600.0s")
    assert classify_record(record) == "timeout"


def test_classify_record_read_timeout_is_timeout() -> None:
    record = _base_record(error_type="ReadTimeout", error="read timed out")
    assert classify_record(record) == "timeout"


def test_classify_record_other_error_type_is_transport() -> None:
    record = _base_record(error_type="ConnectError", error="connection refused")
    assert classify_record(record) == "transport"


def test_classify_record_no_node_failure_or_error_type_is_other() -> None:
    record = _base_record()
    assert classify_record(record) == "other"


# --- (c) join: build_rows with vector_top4_path, and _question_c directly ---


def test_build_rows_without_vector_top4_leaves_c_none() -> None:
    """Default parameter: every existing caller of build_rows is unaffected."""
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS)
    row = _row(rows, "mhr-0073ab564e55")
    assert row.c_gold_in_vector_top4 is None


def test_question_c_true_when_gold_in_chunk_id_is_in_top4() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS, VECTOR_TOP4)
    row = _row(rows, "mhr-0073ab564e55")
    # Fixture's top4 for this question includes chunk 11111111...:0, one of its
    # two in_chunk gold chunk_ids.
    assert row.c_gold_in_vector_top4 is True


def test_question_c_false_when_top4_present_but_no_intersection() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS, VECTOR_TOP4)
    row = _row(rows, "mhr-0085f76defbe")
    # This question's only in_chunk gold chunk_id (33333333...:1) is absent from
    # its fixture top4 list; its other item is split_across_chunks (no chunk_ids).
    assert row.c_gold_in_vector_top4 is False


def test_question_c_none_when_question_missing_from_vector_top4_file() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS, VECTOR_TOP4)
    row = _row(rows, "mhr-012f1f51ac88")
    # Present in gold_chunks.jsonl but absent from the fixture vector_top4.jsonl,
    # e.g. because a cap-stopped probe run never reached it.
    assert row.c_gold_in_vector_top4 is None


def test_question_c_none_for_null_question_even_with_vector_top4() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS, VECTOR_TOP4)
    row = _row(rows, "mhr-0279d4a349c3")
    assert row.is_null is True
    assert row.c_gold_in_vector_top4 is None


def test_load_vector_top4_by_question_skips_trailing_summary_line() -> None:
    """The summary line `{spend_usd, questions, cached, stopped_by_cap}` carries no
    `question_id` and must not be misread as a question with an empty chunk_ids list."""
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS, VECTOR_TOP4)
    ids = {row.question_id for row in rows}
    assert "mhr-0073ab564e55" in ids  # sanity: the fixture's real rows still built


def test_question_c_direct_true() -> None:
    items = [{"state": "in_chunk", "chunk_ids": ["a:0", "a:1"]}]
    assert _question_c(items, ["a:1", "z:9"]) is True


def test_question_c_direct_false_no_in_chunk_items() -> None:
    items = [{"state": "split_across_chunks", "chunk_ids": []}]
    assert _question_c(items, ["a:1"]) is False


def test_question_c_direct_none_when_top4_is_none() -> None:
    items = [{"state": "in_chunk", "chunk_ids": ["a:1"]}]
    assert _question_c(items, None) is None


# --- compute_populations: G and V ---


def test_compute_populations_g_excludes_null_and_b_no() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS, VECTOR_TOP4)
    populations = compute_populations(rows)

    g_ids = set(populations["g_question_ids"])
    # in_gold_in_index_subset True cases land in G.
    assert "mhr-0073ab564e55" in g_ids
    assert "mhr-012f1f51ac88" in g_ids
    # Null question and the split-item question are excluded from G (D-63/D-72).
    assert "mhr-0279d4a349c3" not in g_ids
    assert "mhr-0085f76defbe" not in g_ids
    assert populations["g_count"] == len(g_ids)


def test_compute_populations_v_requires_g_and_c_true() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS, VECTOR_TOP4)
    populations = compute_populations(rows)

    v_ids = set(populations["v_question_ids"])
    # In G, and c is True.
    assert "mhr-0073ab564e55" in v_ids
    # In G, but c is None (missing from the vector file) -- must not count as V.
    assert "mhr-012f1f51ac88" not in v_ids
    assert populations["v_count"] == len(v_ids)
    assert v_ids.issubset(set(populations["g_question_ids"]))


def test_compute_populations_by_type_breakdown_sums_to_totals() -> None:
    rows = build_rows(CORPUS, JOURNAL_SLICE, GOLD_CHUNKS, VECTOR_TOP4)
    populations = compute_populations(rows)

    assert sum(populations["g_by_type"].values()) == populations["g_count"]
    assert sum(populations["v_by_type"].values()) == populations["v_count"]


# --- gold coverage table (D-61): build_gold_coverage_rows / write_gold_coverage ---


class _FakeEvalSettings:
    lancedb_path = "./data/lancedb-eval"


def test_build_gold_coverage_rows_marks_presence_from_live_probe(monkeypatch) -> None:
    live_ids = {
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        # 33333333... intentionally absent from the live set.
    }
    monkeypatch.setattr(
        "lancet_eval.config.load_settings", lambda *a, **kw: _FakeEvalSettings()
    )
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: {"documents": sorted(live_ids)},
    )

    rows = build_gold_coverage_rows(CORPUS, GOLD_CHUNKS)

    by_key = {(r["question_id"], r["evidence_index"]): r for r in rows}
    present = by_key[("mhr-0073ab564e55", 0)]
    assert present["document_id"] == "11111111-1111-4111-8111-111111111111"
    assert present["document_present_in_lancedb"] is True
    assert present["state"] == "in_chunk"

    absent = by_key[("mhr-0085f76defbe", 0)]
    assert absent["document_id"] == "33333333-3333-4333-8333-333333333333"
    assert absent["document_present_in_lancedb"] is False


def test_build_gold_coverage_rows_sorted_by_question_then_evidence_index(monkeypatch) -> None:
    monkeypatch.setattr(
        "lancet_eval.config.load_settings", lambda *a, **kw: _FakeEvalSettings()
    )
    monkeypatch.setattr(
        "lancet_eval.identity.list_lancedb_document_ids",
        lambda path: {"documents": []},
    )
    rows = build_gold_coverage_rows(CORPUS, GOLD_CHUNKS)
    keys = [(r["question_id"], r["evidence_index"]) for r in rows]
    assert keys == sorted(keys)


def test_write_gold_coverage_emits_jsonl_and_markdown(tmp_path: Path) -> None:
    rows = [
        {
            "question_id": "q-1",
            "evidence_index": 0,
            "title": "t",
            "document_id": "d-1",
            "document_present_in_lancedb": True,
            "state": "in_chunk",
        },
        {
            "question_id": "q-1",
            "evidence_index": 1,
            "title": "t2",
            "document_id": None,
            "document_present_in_lancedb": None,
            "state": "unmapped_title",
        },
    ]
    jsonl_dir = tmp_path / "post-reconcile"
    md_path = tmp_path / "phase" / "06.3.4.1-GOLD-COVERAGE.md"

    write_gold_coverage(rows, jsonl_dir, md_path)

    jsonl_path = jsonl_dir / "gold_coverage.jsonl"
    assert jsonl_path.is_file()
    lines = jsonl_path.read_text(encoding="utf-8").strip("\n").split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["question_id"] == "q-1"

    assert md_path.is_file()
    content = md_path.read_text(encoding="utf-8")
    assert "Gold-doc / document_map.json Coverage Table" in content
    assert "in_chunk" in content
    assert "unmapped title (no document_id)" in content


# --- 06.3.4.1-13: column (d), seed count and path found from the graph-seeds probe ---

_MICHIGAN_TITLE_PREFIX = "Michigan State hires Jonathan Smith"


def _document_id_for(title_prefix: str) -> str:
    for document_id, entry in load_document_map(CORPUS).entries.items():
        if entry.title.startswith(title_prefix):
            return document_id
    raise AssertionError(f"no document_map entry starts with {title_prefix!r}")


def _seed(name: str, kind: str, degree: int, documents: list[str]) -> dict:
    return {
        "entity_id": f"entity-{name}",
        "name": name,
        "match_kind": kind,
        "score": 1.0,
        "degree": degree,
        "source_document_ids": documents,
        "source_chunk_count": len(documents),
    }


def _path(entities: list[str], tokens: int) -> dict:
    return {
        "entities": entities,
        "relations": ["r"] * (len(entities) - 1),
        "rendered": " - ".join(entities),
        "score": 1.0,
        "tokens": tokens,
    }


def _probe_record(question_id: str, **overrides: object) -> dict:
    record: dict[str, object] = {
        "question_id": question_id,
        "mentions": [],
        "seeds": [],
        "seed_count": 0,
        "path_found": False,
        "paths": [],
        "candidate_chunk_ids": [],
        "seed_chunk_candidate_ids": [],
        "degree_capped_count": 0,
    }
    record.update(overrides)
    return record


_PROBE_SUMMARY = {
    "spend_usd": 0.0004,
    "questions": 4,
    "stopped_by_cap": False,
    "degree_p95": 10.0,
    "degree_p99": 33.0,
    "evidence_token_budget": 8192,
    "max_output_tokens": 2048,
}


def _write_probe(tmp_path: Path, records: list[dict], summary: dict | None) -> Path:
    path = tmp_path / "seed_probe.jsonl"
    lines = [json.dumps(record) for record in records]
    if summary is not None:
        lines.append(json.dumps(summary))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _probe_fixture(tmp_path: Path) -> Path:
    michigan = _document_id_for(_MICHIGAN_TITLE_PREFIX)
    prime_day = _document_id_for("The best October Prime Day gaming deals")
    records = [
        # In G: a seed sits in a gold document, a path exists, one intermediate was
        # degree-capped.
        _probe_record(
            "mhr-0073ab564e55",
            seeds=[
                _seed("CBSSports.com", "exact", 5, [michigan]),
                _seed("Jonathan Smith", "normalized", 2, ["unrelated-doc"]),
            ],
            seed_count=2,
            path_found=True,
            paths=[
                _path(["entity-CBSSports.com", "entity-Jonathan Smith"], 30),
                _path(["entity-CBSSports.com", "x", "entity-Jonathan Smith"], 50),
            ],
            candidate_chunk_ids=[
                "11111111-1111-4111-8111-111111111111:0",
                "zzzzzzzz-zzzz-4zzz-8zzz-zzzzzzzzzzzz:5",
            ],
            seed_chunk_candidate_ids=["99999999-9999-4999-8999-999999999999:0"],
            degree_capped_count=1,
        ),
        # Not in G (a split gold fact): one hub vector seed, no path; the seed chunks
        # lie outside the dense top-4.
        _probe_record(
            "mhr-0085f76defbe",
            seeds=[_seed("Obscure", "vector", 50, ["unrelated-doc"])],
            seed_count=1,
            seed_chunk_candidate_ids=["55555555-5555-4555-8555-555555555555:3"],
        ),
        # In G: its only seed is a degenerate nameless entity that happens to sit in a
        # gold document, so (d) reads yes only because of it.
        _probe_record(
            "mhr-012f1f51ac88",
            seeds=[_seed("  ", "vector", 0, [prime_day])],
            seed_count=1,
        ),
        # A null question: seed count and path are still recorded, (d) is not.
        _probe_record("mhr-0279d4a349c3"),
    ]
    return _write_probe(tmp_path, records, _PROBE_SUMMARY)


def test_build_rows_fills_d_seed_count_and_path_found_from_the_seed_probe(
    tmp_path: Path,
) -> None:
    rows = build_rows(
        CORPUS, None, GOLD_CHUNKS, VECTOR_TOP4, seed_probe_path=_probe_fixture(tmp_path)
    )

    hit = _row(rows, "mhr-0073ab564e55")
    assert hit.d_graph_seed_hit is True, (
        "a seed sourced from a gold document is a hit (D-79)"
    )
    assert hit.seed_count == 2
    assert hit.path_found is True

    miss = _row(rows, "mhr-0085f76defbe")
    assert miss.d_graph_seed_hit is False
    assert (miss.seed_count, miss.path_found) == (1, False)

    nameless_only = _row(rows, "mhr-012f1f51ac88")
    assert (
        nameless_only.d_graph_seed_hit,
        nameless_only.seed_count,
        nameless_only.path_found,
    ) == (True, 1, False)

    null = _row(rows, "mhr-0279d4a349c3")
    assert null.d_graph_seed_hit is None, "a null question has no gold document to hit"
    assert (null.seed_count, null.path_found) == (0, False)


def test_question_missing_from_the_seed_probe_stays_unmeasured(tmp_path: Path) -> None:
    rows = build_rows(
        CORPUS, None, GOLD_CHUNKS, seed_probe_path=_probe_fixture(tmp_path)
    )
    unmeasured = _row(rows, "mhr-00fc91a80765")
    assert unmeasured.d_graph_seed_hit is None
    assert unmeasured.seed_count is None
    assert unmeasured.path_found is None


def test_build_rows_without_a_seed_probe_leaves_the_graph_columns_none() -> None:
    rows = build_rows(CORPUS, None, GOLD_CHUNKS)
    assert all(
        row.d_graph_seed_hit is None
        and row.seed_count is None
        and row.path_found is None
        for row in rows
    )


def test_a_seed_from_another_document_is_not_a_hit(tmp_path: Path) -> None:
    # The question's own gold documents come from the map, never from the probe, so a
    # seed whose only source document is some other article must not read "yes".
    records = [
        _probe_record(
            "mhr-0073ab564e55",
            seeds=[_seed("Other", "exact", 3, ["not-a-gold-document"])],
            seed_count=1,
        )
    ]
    probe = _write_probe(tmp_path, records, None)
    rows = build_rows(CORPUS, None, GOLD_CHUNKS, seed_probe_path=probe)
    assert _row(rows, "mhr-0073ab564e55").d_graph_seed_hit is False


def test_write_table_renders_the_graph_columns(tmp_path: Path) -> None:
    rows = build_rows(
        CORPUS, None, GOLD_CHUNKS, VECTOR_TOP4, seed_probe_path=_probe_fixture(tmp_path)
    )
    out_dir = tmp_path / "table"
    write_table(rows, out_dir, label="seed-probe", gold_chunks_path=GOLD_CHUNKS)
    lines = (out_dir / "table.jsonl").read_text(encoding="utf-8").splitlines()
    by_id = {row["question_id"]: row for row in map(json.loads, lines)}
    assert by_id["mhr-0073ab564e55"]["d_graph_seed_hit"] is True
    assert by_id["mhr-0073ab564e55"]["seed_count"] == 2
    md = (out_dir / "table.md").read_text(encoding="utf-8")
    assert "| mhr-0073ab564e55 | comparison_query | yes | yes | yes | yes |" in md


def test_table_cli_accepts_seed_probe_and_writes_columns(tmp_path: Path) -> None:
    out_dir = tmp_path / "cli-table"
    code = main([
        "table",
        "--corpus",
        CORPUS,
        "--gold-chunks",
        str(GOLD_CHUNKS),
        "--seed-probe",
        str(_probe_fixture(tmp_path)),
        "--out-dir",
        str(out_dir),
        "--label",
        "cli",
    ])
    assert code == 0
    lines = (out_dir / "table.jsonl").read_text(encoding="utf-8").splitlines()
    assert {row["question_id"]: row["path_found"] for row in map(json.loads, lines)}[
        "mhr-0073ab564e55"
    ] is True


# --- 06.3.4.1-13: the seed-probe summary that feeds 06.3.4.1-SEED-PROBE.md ---


def test_summarize_seed_probe_computes_every_headline_number(tmp_path: Path) -> None:
    summary = summarize_seed_probe(
        CORPUS, _probe_fixture(tmp_path), GOLD_CHUNKS, VECTOR_TOP4
    )

    assert summary["questions"] == 4
    assert summary["non_null"] == 3
    assert summary["gold_in_index_subset"] == 2
    assert summary["seed_count_distribution"] == {"0": 1, "1": 2, "2": 1}
    assert summary["seeds_total"] == 4
    assert summary["match_kind_counts"] == {"exact": 1, "normalized": 1, "vector": 2}

    assert summary["d_graph_seed_hit"]["gold_in_index_subset"] == {
        "yes": 2,
        "n": 2,
        "rate": 1.0,
    }
    assert summary["d_graph_seed_hit"]["all_non_null"]["yes"] == 2
    assert summary["d_graph_seed_hit"]["all_non_null"]["n"] == 3

    assert summary["path_found"]["overall"] == {"yes": 1, "n": 4, "rate": 0.25}
    by_type = summary["path_found"]["by_question_type"]
    assert (by_type["comparison_query"]["yes"], by_type["comparison_query"]["n"]) == (
        1,
        3,
    )
    assert by_type["null_query"] == {"yes": 0, "n": 1, "rate": 0.0}

    assert summary["hub_seeds"]["seeds_over_p95"]["yes"] == 1, (
        "only the degree-50 seed is over p95"
    )
    assert summary["publisher_seeds"]["seeds_that_are_publishers"]["yes"] == 1, (
        "CBSSports.com"
    )
    assert summary["degree_capped"]["total"] == 1


def test_summarize_seed_probe_separates_what_publisher_and_nameless_seeds_contribute(
    tmp_path: Path,
) -> None:
    summary = summarize_seed_probe(
        CORPUS, _probe_fixture(tmp_path), GOLD_CHUNKS, VECTOR_TOP4
    )

    # One degenerate seed, in one question.
    assert summary["nameless_seeds"]["seeds"] == 1
    assert summary["nameless_seeds"]["questions"] == 1

    # Raw (d) is 2 of 2 on G, but one of those hits comes only from the nameless seed.
    without = summary["d_graph_seed_hit_without"]
    assert without["nameless_seeds"]["gold_in_index_subset"]["yes"] == 1
    assert without["nameless_seeds"]["gold_in_index_subset"]["n"] == 2
    assert without["nameless_seeds"]["all_non_null"]["yes"] == 1
    # The CBSSports.com seed (a publisher) is the only source of the other hit.
    assert without["publisher_seeds"]["gold_in_index_subset"]["yes"] == 1
    assert without["publisher_and_hub_seeds"]["gold_in_index_subset"]["yes"] == 1


def test_summarize_seed_probe_classifies_path_ends_by_publisher_name(
    tmp_path: Path,
) -> None:
    summary = summarize_seed_probe(
        CORPUS, _probe_fixture(tmp_path), GOLD_CHUNKS, VECTOR_TOP4
    )

    ends = summary["path_endpoints"]
    # Both fixture paths join CBSSports.com (a publisher) to a person.
    classes = (ends["both_publisher"], ends["one_publisher"], ends["neither_publisher"])
    assert classes == (0, 2, 0)
    assert ends["questions_with_a_path_with_no_publisher_end"] == {
        "yes": 0,
        "n": 1,
        "rate": 0.0,
    }


def test_summarize_seed_probe_compares_candidates_with_dense_top4_for_both_options(
    tmp_path: Path,
) -> None:
    summary = summarize_seed_probe(
        CORPUS, _probe_fixture(tmp_path), GOLD_CHUNKS, VECTOR_TOP4
    )

    counts = summary["candidate_chunks"]
    assert counts["paths_only"]["distribution"] == {"0": 3, "2": 1}
    assert counts["paths_plus_seed_chunks"]["distribution"] == {"0": 2, "1": 1, "2": 1}

    proxy = summary["composition_change_proxy"]["all_probed"]
    # Only the two questions that the (c) probe covers are measured.
    assert proxy["paths_only"]["n"] == 2
    assert proxy["paths_only"]["yes"] == 1, "only the path chunk outside top-4 counts"
    assert proxy["paths_plus_seed_chunks"]["yes"] == 2, (
        "seed chunks reach the second question"
    )
    assert proxy["paths_plus_seed_chunks"]["n"] == 2


def test_summarize_seed_probe_derives_the_d77_cap_inputs(tmp_path: Path) -> None:
    summary = summarize_seed_probe(
        CORPUS, _probe_fixture(tmp_path), GOLD_CHUNKS, VECTOR_TOP4
    )

    tokens = summary["path_fact_tokens"]
    assert (tokens["paths"], tokens["one_hop_paths"], tokens["two_hop_paths"]) == (
        2,
        1,
        1,
    )
    assert (tokens["p50"], tokens["p95"], tokens["max"]) == (30, 50, 50)

    caps = summary["d77_caps"]
    assert caps["degree_cap"] == 33
    assert caps["p95_fact_tokens"] == 50
    # min(16, floor(0.10 * (8192 - 2048) / 50)) = min(16, 12)
    assert caps["max_path_facts"] == 12


def test_d77_max_path_facts_is_undefined_when_no_path_was_found(tmp_path: Path) -> None:
    probe = _write_probe(tmp_path, [_probe_record("mhr-0073ab564e55")], _PROBE_SUMMARY)
    summary = summarize_seed_probe(CORPUS, probe, GOLD_CHUNKS, VECTOR_TOP4)
    assert summary["path_fact_tokens"]["paths"] == 0
    assert summary["d77_caps"]["p95_fact_tokens"] is None
    assert summary["d77_caps"]["max_path_facts"] is None, (
        "no measured fact, no invented cap"
    )


def test_seed_summary_cli_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "summary.json"
    code = main([
        "seed-summary",
        "--corpus",
        CORPUS,
        "--seed-probe",
        str(_probe_fixture(tmp_path)),
        "--gold-chunks",
        str(GOLD_CHUNKS),
        "--vector-top4",
        str(VECTOR_TOP4),
        "--out",
        str(out),
    ])
    assert code == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["questions"] == 4
    assert written["probe"]["degree_p99"] == 33.0
