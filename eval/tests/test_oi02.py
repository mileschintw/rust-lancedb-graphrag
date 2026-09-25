"""Tests for OI-02 full-pipeline forensics tooling (06.3.4.1-07 Task 1).

Synthetic journals under pytest tmp_path; no live Prometheus/Loki/git dependency. The
`forensics` subcommand's git-derived facts (`compute_drive_era_facts`) are exercised
separately, against the real repo, only for a smoke-level "does not raise" check.
"""

from __future__ import annotations

import json
from pathlib import Path

from lancet_eval.oi02 import (
    TimelineRow,
    build_stub_vectors,
    extract_chunk_ids_for_replay,
    hidden_gaps,
    idle_recovery,
    journal_timeline,
    load_chunk_embeddings,
    load_question_texts,
    load_timeline_records,
    run_forensics,
    slice_table,
)


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _header_line() -> dict:
    return {"type": "header", "corpus": "multihop_rag", "partial": False, "created_at": "2026-01-01T00:00:00Z"}


def _run_record_line(
    question_id: str,
    *,
    started_at_ms: int,
    completed_at_ms: int,
    retrieve_ms: float,
    duration_ms: float | None = None,
    graph_arm: str = "graph-on",
    outcome: str = "success",
    error_type: str | None = None,
    reformulation_used: bool = False,
    prompt_tokens: int = 100,
    notices: list[dict] | None = None,
) -> dict:
    """A 06.3.4 `RunRecord`-shaped journal line (no ordinal/segment fields)."""
    return {
        "corpus": "multihop_rag",
        "question_id": question_id,
        "graph_arm": graph_arm,
        "outcome": outcome,
        "answer": "answer text" if outcome == "success" else None,
        "notices": notices or [],
        "node_failures": [],
        "duration_ms": duration_ms if duration_ms is not None else (completed_at_ms - started_at_ms),
        "session_id": "",
        "correlation_id": "",
        "index_generation": "lance-701",
        "partial": False,
        "error_type": error_type,
        "error": None,
        "node_timings": [
            {"node_name": "ReformulateQuery", "duration_ms": 1.0},
            {"node_name": "RetrieveHybrid", "duration_ms": retrieve_ms},
            {"node_name": "AssemblePrompt", "duration_ms": 5.0},
        ],
        "workflow_meta": {
            "started_at_ms": started_at_ms,
            "completed_at_ms": completed_at_ms,
            "reformulation_used": reformulation_used,
            "vector_count": 10,
            "bm25_count": 10,
            "graph_node_count": 0,
            "graph_edge_count": 0,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 50,
            "degraded_mode": False,
            "graph_prompt_fact_count": None,
        },
    }


def _measurement_record_line(
    question_id: str,
    *,
    ordinal: int,
    segment: str,
    started_at_ms: int,
    completed_at_ms: int,
    retrieve_ms: float,
) -> dict:
    """A 06.3.3 `MeasurementRecord`-shaped journal line (carries ordinal/segment)."""
    line = _run_record_line(
        question_id,
        started_at_ms=started_at_ms,
        completed_at_ms=completed_at_ms,
        retrieve_ms=retrieve_ms,
    )
    line["ordinal"] = ordinal
    line["segment"] = segment
    line["warm_up"] = False
    line["question_type"] = "multihop"
    line["dropped_node_timings"] = 0
    return line


# --- load_timeline_records / journal_timeline --------------------------------------------


def test_journal_timeline_skips_header_and_assigns_ordinals_in_line_order(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            _header_line(),
            _run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0),
            _run_record_line("q2", started_at_ms=1_200, completed_at_ms=1_400, retrieve_ms=60.0),
        ],
    )
    rows = journal_timeline(path)
    assert [r.ordinal for r in rows] == [1, 2]
    assert [r.question_id for r in rows] == ["q1", "q2"]
    assert rows[0].segment == "segment-1"


def test_journal_timeline_reads_06_3_3_measurement_record_shape_keeping_ordinal_and_segment(
    tmp_path: Path,
):
    path = tmp_path / "measure-journal.jsonl"
    _write_jsonl(
        path,
        [
            _header_line(),
            _measurement_record_line(
                "q1", ordinal=7, segment="segment-2", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0
            ),
        ],
    )
    rows = journal_timeline(path)
    assert len(rows) == 1
    assert rows[0].ordinal == 7
    assert rows[0].segment == "segment-2"


def test_journal_timeline_node_durations_include_retrieve_hybrid(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [_run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=42.5)],
    )
    rows = journal_timeline(path)
    assert rows[0].node_durations["RetrieveHybrid"] == 42.5


def test_journal_timeline_first_record_has_no_hidden_gap(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [_run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)],
    )
    rows = journal_timeline(path)
    assert rows[0].hidden_gap_ms is None


def test_journal_timeline_hidden_gap_is_next_started_minus_prev_completed(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            _run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0),
            _run_record_line("q2", started_at_ms=5_000, completed_at_ms=5_200, retrieve_ms=60.0),
        ],
    )
    rows = journal_timeline(path)
    assert rows[1].hidden_gap_ms == 5_000 - 1_100


def test_journal_timeline_missing_file_returns_empty(tmp_path: Path):
    rows = journal_timeline(tmp_path / "does-not-exist.jsonl")
    assert rows == []


def test_journal_timeline_skips_unparseable_trailing_line(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    good = _run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)
    path.write_text(json.dumps(good) + "\n" + '{"corpus": "multihop_rag", "question_id":', encoding="utf-8")
    rows = journal_timeline(path)
    assert len(rows) == 1


# --- hidden_gaps -----------------------------------------------------------------------


def test_hidden_gaps_flags_gap_over_threshold(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            _run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0),
            _run_record_line("q2", started_at_ms=10_000, completed_at_ms=10_200, retrieve_ms=60.0),
        ],
    )
    rows = journal_timeline(path)
    gaps = hidden_gaps(rows, threshold_ms=2_000)
    assert len(gaps) == 1
    assert gaps[0]["ordinal"] == 2
    assert gaps[0]["hidden_gap_ms"] == 10_000 - 1_100


def test_hidden_gaps_empty_when_no_gap_exceeds_threshold(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            _run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0),
            _run_record_line("q2", started_at_ms=1_200, completed_at_ms=1_400, retrieve_ms=60.0),
        ],
    )
    rows = journal_timeline(path)
    assert hidden_gaps(rows, threshold_ms=2_000) == []


# --- slice_table -------------------------------------------------------------------------


def test_slice_table_by_ordinal_reports_medians_per_node(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    lines = [
        _run_record_line(f"q{i}", started_at_ms=1_000 + i * 100, completed_at_ms=1_050 + i * 100, retrieve_ms=float(i))
        for i in range(1, 4)
    ]
    _write_jsonl(path, lines)
    rows = journal_timeline(path)
    slices = slice_table(rows, by="ordinal", size=50)
    assert len(slices) == 1
    assert slices[0]["n"] == 3
    assert slices[0]["RetrieveHybrid"] == 2.0  # median of 1.0, 2.0, 3.0


def test_slice_table_by_ordinal_splits_across_slice_boundary(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    lines = [
        _run_record_line(f"q{i}", started_at_ms=1_000 + i, completed_at_ms=1_050 + i, retrieve_ms=float(i))
        for i in range(1, 61)  # 60 records, size=50 -> 2 slices (50, 10)
    ]
    _write_jsonl(path, lines)
    rows = journal_timeline(path)
    slices = slice_table(rows, by="ordinal", size=50)
    assert len(slices) == 2
    assert slices[0]["n"] == 50
    assert slices[1]["n"] == 10


def test_slice_table_reports_none_not_zero_when_node_absent_from_slice(tmp_path: Path):
    """A slice with no completed RetrieveHybrid reports it as unavailable (None), never 0."""
    path = tmp_path / "journal.jsonl"
    line = _run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)
    # Strip RetrieveHybrid entirely from this record's node_timings (censored observation).
    line["node_timings"] = [t for t in line["node_timings"] if t["node_name"] != "RetrieveHybrid"]
    _write_jsonl(path, [line])
    rows = journal_timeline(path)
    slices = slice_table(rows, by="ordinal", size=50)
    assert slices[0]["RetrieveHybrid"] is None


def test_slice_table_by_wallclock_groups_into_minute_windows(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    base = 1_700_000_000_000
    lines = [
        _run_record_line("q1", started_at_ms=base, completed_at_ms=base + 100, retrieve_ms=10.0),
        _run_record_line("q2", started_at_ms=base + 5 * 60_000, completed_at_ms=base + 5 * 60_000 + 100, retrieve_ms=20.0),
        _run_record_line("q3", started_at_ms=base + 20 * 60_000, completed_at_ms=base + 20 * 60_000 + 100, retrieve_ms=30.0),
    ]
    _write_jsonl(path, lines)
    rows = journal_timeline(path)
    slices = slice_table(rows, by="wallclock", minutes=15)
    # q1/q2 fall in the first 15-minute window (offsets 0 and 5min), q3 in the second (offset 20min).
    assert len(slices) == 2
    assert slices[0]["n"] == 2
    assert slices[1]["n"] == 1


# --- idle_recovery -------------------------------------------------------------------------


def test_idle_recovery_compares_medians_around_largest_gap(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    lines = []
    # 5 records before a big gap (low retrieve_ms), then a big gap, then 5 after (high retrieve_ms).
    t = 1_000
    for i in range(5):
        lines.append(_run_record_line(f"before{i}", started_at_ms=t, completed_at_ms=t + 100, retrieve_ms=10.0))
        t += 200
    t += 20_000  # large idle gap
    for i in range(5):
        lines.append(_run_record_line(f"after{i}", started_at_ms=t, completed_at_ms=t + 100, retrieve_ms=90.0))
        t += 200
    _write_jsonl(path, lines)
    rows = journal_timeline(path)
    recovery = idle_recovery(rows, window=5, threshold_ms=2_000)
    assert len(recovery) == 1
    assert recovery[0]["before_median_ms"] == 10.0
    assert recovery[0]["after_median_ms"] == 90.0


def test_idle_recovery_empty_when_no_gaps(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            _run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0),
            _run_record_line("q2", started_at_ms=1_200, completed_at_ms=1_400, retrieve_ms=60.0),
        ],
    )
    rows = journal_timeline(path)
    assert idle_recovery(rows, threshold_ms=2_000) == []


# --- run_forensics: forensics.json merge contract (Trap 1) -------------------------------


def test_run_forensics_writes_timeline_and_slice_artifacts(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(
        journal,
        [_run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)],
    )
    out_dir = tmp_path / "forensics"
    result = run_forensics(journal=journal, raw_events=None, contrast=None, out=out_dir)
    assert (out_dir / "timeline.json").exists()
    assert (out_dir / "slices_ordinal.json").exists()
    assert (out_dir / "forensics.json").exists()
    assert result["journal_record_count"] == 1


def test_run_forensics_seeds_external_evidence_keys_as_unknown_on_first_write(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(
        journal,
        [_run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)],
    )
    out_dir = tmp_path / "forensics"
    result = run_forensics(journal=journal, raw_events=None, contrast=None, out=out_dir)
    for key in ("fresh_process", "m1_reference_ms", "m1_prod_ratio", "stub_delay_defaults", "production_launch"):
        assert key in result
        assert result[key] == "unknown"


def test_run_forensics_never_clobbers_preexisting_external_evidence(tmp_path: Path):
    """Trap 1: a second run (after a human has hand-populated fresh_process/m1_reference_ms/
    etc. into forensics.json from Prometheus/Loki/git evidence) must preserve those values,
    not overwrite them back to "unknown" or drop them."""
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(
        journal,
        [_run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)],
    )
    out_dir = tmp_path / "forensics"
    out_dir.mkdir(parents=True)
    seeded = {
        "fresh_process": True,
        "prior_query_count": 1,
        "m1_reference_ms": 4910.5,
        "m1_reference_provenance": "06.3.4 slice 0 median",
        "m1_alt_reference_ms": None,
        "m1_prod_ratio": {"debug": 66.0},
        "stub_delay_defaults": {"embedding_ms": 100, "chat_ms": 200},
        "production_launch": {"build_profile": "debug"},
    }
    (out_dir / "forensics.json").write_text(json.dumps(seeded), encoding="utf-8")

    result = run_forensics(journal=journal, raw_events=None, contrast=None, out=out_dir)

    assert result["fresh_process"] is True
    assert result["prior_query_count"] == 1
    assert result["m1_reference_ms"] == 4910.5
    assert result["m1_reference_provenance"] == "06.3.4 slice 0 median"
    assert result["m1_prod_ratio"] == {"debug": 66.0}
    assert result["stub_delay_defaults"] == {"embedding_ms": 100, "chat_ms": 200}
    assert result["production_launch"] == {"build_profile": "debug"}
    # journal-derived keys still refreshed on top of the preserved evidence keys.
    assert result["journal_record_count"] == 1


def test_run_forensics_computes_drive_era_commit_and_proto_flag_from_real_repo(tmp_path: Path):
    """Smoke-level: the git-derived facts run against the real repository (not tmp_path) and
    must not raise, returning a non-empty commit sha and a boolean proto flag."""
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(
        journal,
        [_run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)],
    )
    out_dir = tmp_path / "forensics"
    result = run_forensics(journal=journal, raw_events=None, contrast=None, out=out_dir)
    assert isinstance(result["drive_era_commit"], str)
    assert len(result["drive_era_commit"]) == 40
    assert isinstance(result["proto_changed_since_drive_era"], bool)


def test_run_forensics_includes_contrast_when_provided(tmp_path: Path):
    journal = tmp_path / "journal.jsonl"
    _write_jsonl(
        journal,
        [_run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)],
    )
    contrast = tmp_path / "contrast.jsonl"
    _write_jsonl(
        contrast,
        [_run_record_line("c1", started_at_ms=1_000, completed_at_ms=1_050, retrieve_ms=10.0)],
    )
    out_dir = tmp_path / "forensics"
    result = run_forensics(journal=journal, raw_events=None, contrast=contrast, out=out_dir)
    assert (out_dir / "contrast_timeline.json").exists()
    assert result["contrast_record_count"] == 1


# --- load_timeline_records: shape preference --------------------------------------------


def test_load_timeline_records_prefers_measurement_record_when_ordinal_segment_present(
    tmp_path: Path,
):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [
            _measurement_record_line(
                "q1", ordinal=3, segment="segment-1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0
            )
        ],
    )
    loaded = load_timeline_records(path)
    assert len(loaded) == 1
    rec, is_measurement = loaded[0]
    assert is_measurement is True
    assert rec.ordinal == 3


def test_load_timeline_records_falls_back_to_run_record_when_no_ordinal(tmp_path: Path):
    path = tmp_path / "journal.jsonl"
    _write_jsonl(
        path,
        [_run_record_line("q1", started_at_ms=1_000, completed_at_ms=1_100, retrieve_ms=50.0)],
    )
    loaded = load_timeline_records(path)
    assert len(loaded) == 1
    rec, is_measurement = loaded[0]
    assert is_measurement is False


# --- stub vector-map builder (06.3.4.1-07 Task 3 checkpoint resolution: rerun-primary) --------


def _prod_record_with_chunks(
    question_id: str, *, graph_arm: str, chunks: list[tuple[str, int]]
) -> dict:
    """A production-journal-shaped record carrying `snapshot.retrieved_chunks` with the given
    (chunk_id, rank) pairs -- the only fields `extract_chunk_ids_for_replay` reads."""
    return {
        "corpus": "multihop_rag",
        "question_id": question_id,
        "graph_arm": graph_arm,
        "outcome": "success",
        "snapshot": {
            "retrieved_chunks": [
                {"chunk_id": chunk_id, "rank": rank} for chunk_id, rank in chunks
            ]
        },
    }


def test_extract_chunk_ids_prefers_graph_off_arm_and_dedupes_in_replay_order(tmp_path: Path):
    replay_journal = tmp_path / "replay.jsonl"
    _write_jsonl(
        replay_journal,
        [
            _header_line(),
            _run_record_line("q2", started_at_ms=0, completed_at_ms=10, retrieve_ms=1.0),
            _run_record_line("q1", started_at_ms=10, completed_at_ms=20, retrieve_ms=1.0),
            _run_record_line("q2", started_at_ms=20, completed_at_ms=30, retrieve_ms=1.0),
        ],
    )
    prod_journal = tmp_path / "prod.jsonl"
    _write_jsonl(
        prod_journal,
        [
            _header_line(),
            # q1 has both arms; graph-off's rank-1 chunk must win over graph-on's.
            _prod_record_with_chunks("q1", graph_arm="graph-on", chunks=[("chunk-on", 1)]),
            _prod_record_with_chunks("q1", graph_arm="graph-off", chunks=[("chunk-off", 1)]),
            # q2 has only graph-on -- falls back to it.
            _prod_record_with_chunks("q2", graph_arm="graph-on", chunks=[("chunk-q2", 1)]),
            # q3 is in production but never appears in the replay -- must not surface.
            _prod_record_with_chunks("q3", graph_arm="graph-off", chunks=[("chunk-q3", 1)]),
        ],
    )

    question_to_chunk, ordered_chunk_ids = extract_chunk_ids_for_replay(replay_journal, prod_journal)

    assert question_to_chunk == {"q1": "chunk-off", "q2": "chunk-q2"}
    # Replay order is q2 (first seen), q1 -- not production's q1-first order.
    assert ordered_chunk_ids == ["chunk-q2", "chunk-off"]


def test_extract_chunk_ids_omits_question_absent_from_production(tmp_path: Path):
    replay_journal = tmp_path / "replay.jsonl"
    _write_jsonl(
        replay_journal,
        [_header_line(), _run_record_line("q-unknown", started_at_ms=0, completed_at_ms=10, retrieve_ms=1.0)],
    )
    prod_journal = tmp_path / "prod.jsonl"
    _write_jsonl(prod_journal, [_header_line()])

    question_to_chunk, ordered_chunk_ids = extract_chunk_ids_for_replay(replay_journal, prod_journal)

    assert question_to_chunk == {}
    assert ordered_chunk_ids == []


def test_load_chunk_embeddings_reads_export_embeddings_jsonl(tmp_path: Path):
    path = tmp_path / "embeddings.jsonl"
    _write_jsonl(
        path,
        [
            {"chunk_id": "chunk-a", "embedding": [0.1, 0.2]},
            {"chunk_id": "chunk-b", "embedding": [0.3, 0.4]},
        ],
    )
    loaded = load_chunk_embeddings(path)
    assert loaded == {"chunk-a": [0.1, 0.2], "chunk-b": [0.3, 0.4]}


def test_load_question_texts_reads_corpus_query_field(tmp_path: Path):
    path = tmp_path / "questions.jsonl"
    _write_jsonl(
        path,
        [
            {"question_id": "q1", "query": "What is X?", "answer": "ignored"},
            {"question_id": "q2", "query": "What is Y?"},
        ],
    )
    loaded = load_question_texts(path)
    assert loaded == {"q1": "What is X?", "q2": "What is Y?"}


def test_build_stub_vectors_classifies_every_miss_reason():
    question_to_chunk = {"q1": "chunk-1", "q2": "chunk-2", "q3": "chunk-3"}
    # chunk-2 missing (not in reconciled copy); chunk-3 present but q3's text is missing.
    chunk_embeddings = {"chunk-1": [0.1, 0.2], "chunk-3": [0.5, 0.6]}
    question_texts = {"q1": "text one"}  # q3's text missing
    replay_question_ids = ["q1", "q2", "q3", "q4"]  # q4 never had a production top chunk

    rows, counts = build_stub_vectors(
        question_to_chunk, chunk_embeddings, question_texts, replay_question_ids
    )

    assert rows == [{"text": "text one", "embedding": [0.1, 0.2]}]
    assert counts == {
        "total": 4,
        "no_prod_chunk": 1,
        "no_embedding": 1,
        "no_question_text": 1,
        "matched": 1,
    }
