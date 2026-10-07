"""Tests for `eval/scripts/provider_format_map.py` (06.3.5-09 Task 3, D-107, D-96).

The script is the per-arm successor of the 06.3.4.1 forensics script: it joins the
engine's `generation_served` stderr lines to the run journal by `correlation_id`, one
row per journal record in journal order, with `provider: null` for an unmatched record.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from lancet_eval.config import repo_root
from lancet_eval.journal import RunRecord

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "provider_format_map.py"
ARMS = ["dense-only", "bm25-only", "hybrid", "hybrid+graph"]
CORPUS = "multihop_rag_heldout"
MODEL = "deepseek/deepseek-v4-flash-0731"


def _load_script() -> Any:
    """Loads the script by file path (a standalone script, not a package member)."""
    spec = importlib.util.spec_from_file_location("provider_format_map", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["provider_format_map"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _record(index: int, *, kind: str = "answered") -> RunRecord:
    """Record `index`: arm `ARMS[index % 4]`, correlation id `cid-<index>`."""
    base: dict[str, Any] = {
        "corpus": CORPUS,
        "question_id": f"q{index // 4}",
        "graph_arm": ARMS[index % 4],
        "correlation_id": f"cid-{index}",
    }
    if kind == "no_evidence":
        return RunRecord(
            **base,
            outcome="success",
            answer="I cannot find evidence.",
            notices=[
                {"code": "NO_EVIDENCE", "typed_code": 1, "message": "no evidence"}
            ],
        )
    if kind == "errored":
        return RunRecord(
            **base, outcome="error", error_type="ReadTimeout", error="deadline"
        )
    if kind == "errored_after_generation":
        return RunRecord(
            **base,
            outcome="error",
            node_timings=[{"node_name": "GenerateAnswer", "duration_ms": 5.0}],
            node_failures=[
                {
                    "node_name": "GenerateAnswer",
                    "error_kind": 0,
                    "error_message": "citation basis rejected",
                    "retryable": False,
                }
            ],
        )
    return RunRecord(
        **base,
        outcome="success",
        answer="Some reasoning.\nAnswer: Yes",
        node_timings=[{"node_name": "GenerateAnswer", "duration_ms": 5.0}],
    )


def _served_line(cid: str, provider: str | None, n: int) -> str:
    fields = (
        f'generation_served=true correlation_id="{cid}" generation_id="gen-{n}" '
        f'gen_ai.response.model="{MODEL}"'
    )
    if provider is not None:
        fields += f' provider="{provider}"'
    return (
        f"2026-10-07T10:00:{n % 60:02d}.000000Z  INFO "
        f"engine::generation::openrouter: generation_served {fields}"
    )


def _write_run(
    tmp_path: Path,
    records: list[RunRecord],
    served: list[str],
    *,
    noise: bool = True,
) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with open(run_dir / "journal.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "header", "corpus": CORPUS}) + "\n")
        for rec in records:
            f.write(rec.model_dump_json() + "\n")
    log = tmp_path / "engine-stderr.log"
    lines = list(served)
    if noise:
        lines = [
            "2026-10-07T09:59:59.000000Z  INFO engine::server: listening",
            # The right message from a different logger is not a served line.
            '2026-10-07T10:00:00.000000Z  INFO engine::other: generation_served '
            'correlation_id="cid-0" provider="Elsewhere"',
            # A served line with no correlation id cannot be joined.
            "2026-10-07T10:00:00.000000Z  INFO engine::generation::openrouter: "
            'generation_served generation_served=true provider="NoCid"',
            *lines,
        ]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_dir, log


def _all_served(first_half: str = "OpenInference", second_half: str = "Sail Research"):
    """Eight answered records, the provider switching after the fourth."""
    records = [_record(i) for i in range(8)]
    served = [
        _served_line(f"cid-{i}", first_half if i < 4 else second_half, i)
        for i in range(8)
    ]
    return records, served


def test_every_arm_is_counted_under_both_providers(tmp_path: Path) -> None:
    records, served = _all_served()
    run_dir, log = _write_run(tmp_path, records, served)

    rows, summary = script.build_map(run_dir, log)

    assert len(rows) == 8
    assert list(summary["by_arm_provider"]) == ARMS
    for arm in ARMS:
        assert summary["by_arm_provider"][arm] == {
            "OpenInference": 1,
            "Sail Research": 1,
        }
    assert summary["provider_sequence_rle"] == [
        ["OpenInference", 4],
        ["Sail Research", 4],
    ]
    assert summary["per_provider"]["OpenInference"]["records"] == 4
    assert summary["per_provider"]["Sail Research"]["records"] == 4
    assert summary["distinct_providers"] == ["OpenInference", "Sail Research"]
    assert summary["distinct_models"] == [MODEL]
    assert summary["format_counts"] == {"L": 8}
    assert summary["format_by_arm"]["dense-only"] == {"L": 2}


def test_rows_are_one_per_journal_record_in_journal_order(tmp_path: Path) -> None:
    records, served = _all_served()
    run_dir, log = _write_run(tmp_path, records, served)

    rows, _ = script.build_map(run_dir, log)

    assert [r["index"] for r in rows] == list(range(8))
    assert [r["correlation_id"] for r in rows] == [f"cid-{i}" for i in range(8)]
    assert [r["graph_arm"] for r in rows] == [ARMS[i % 4] for i in range(8)]
    assert [r["provider"] for r in rows] == ["OpenInference"] * 4 + [
        "Sail Research"
    ] * 4
    assert all(r["served"] and r["served"][0]["generation_id"] for r in rows)


def test_no_evidence_and_errored_records_are_unmatched_and_reconciled(
    tmp_path: Path,
) -> None:
    records, served = _all_served()
    records[5] = _record(5, kind="no_evidence")  # bm25-only, skips generation
    records[6] = _record(6, kind="errored")  # hybrid, never reached generation
    records[7] = _record(7, kind="errored_after_generation")  # has a served line
    served = [s for s in served if 'correlation_id="cid-5"' not in s]
    served = [s for s in served if 'correlation_id="cid-6"' not in s]
    served.append(_served_line("ghost", "Sail Research", 9))
    run_dir, log = _write_run(tmp_path, records, served)

    rows, summary = script.build_map(run_dir, log)

    assert len(rows) == 8
    assert rows[5]["provider"] is None and rows[5]["served"] == []
    assert rows[6]["provider"] is None and rows[6]["served"] == []
    assert rows[7]["provider"] == "Sail Research"
    assert summary["unmatched_count"] == 2
    assert summary["unmatched_no_evidence"] == 1
    assert summary["unmatched_errored"] == 1
    assert summary["unmatched_unexplained"] == 0
    assert summary["unmatched_count"] == (
        summary["unmatched_no_evidence"] + summary["unmatched_errored"]
    )
    assert summary["by_arm"]["bm25-only"]["no_evidence"] == 1
    assert summary["by_arm"]["hybrid"]["errored"] == 1
    assert summary["by_arm"]["hybrid+graph"]["errored"] == 1
    assert summary["by_arm"]["hybrid+graph"]["unmatched"] == 0
    assert {u["index"] for u in summary["unmatched"]} == {5, 6}
    # NO_EVIDENCE skips generation, so it is not in the generation join denominator.
    assert summary["join_coverage"] == {
        "reached_generate_answer": 6,
        "with_served_line": 6,
    }
    assert summary["provider_sequence_rle"] == [
        ["OpenInference", 4],
        ["Sail Research", 1],
        ["null", 2],
        ["Sail Research", 1],
    ]


def test_a_served_line_outside_the_journal_is_counted(tmp_path: Path) -> None:
    records, served = _all_served()
    served.append(_served_line("ghost", "Sail Research", 20))
    served.append(_served_line("ghost-2", "OpenInference", 21))
    run_dir, log = _write_run(tmp_path, records, served)

    _, summary = script.build_map(run_dir, log)

    assert summary["served_lines_total"] == 10
    assert summary["served_lines_not_in_journal"] == 2
    assert summary["unmatched_count"] == 0


def test_a_record_with_two_served_lines_reads_the_last_and_is_listed(
    tmp_path: Path,
) -> None:
    records, served = _all_served()
    served.append(_served_line("cid-0", "Sail Research", 30))
    run_dir, log = _write_run(tmp_path, records, served)

    rows, summary = script.build_map(run_dir, log)

    assert rows[0]["provider"] == "Sail Research"
    assert [s["provider"] for s in rows[0]["served"]] == [
        "OpenInference",
        "Sail Research",
    ]
    assert summary["two_served_lines"] == [
        {
            "index": 0,
            "question_id": "q0",
            "graph_arm": "dense-only",
            "providers": ["OpenInference", "Sail Research"],
        }
    ]


def test_a_served_line_with_no_provider_is_not_an_unmatched_record(
    tmp_path: Path,
) -> None:
    records, served = _all_served()
    served[2] = _served_line("cid-2", None, 2)
    run_dir, log = _write_run(tmp_path, records, served)

    rows, summary = script.build_map(run_dir, log)

    assert rows[2]["provider"] == "unknown"
    assert rows[2]["served"]
    assert summary["unmatched_count"] == 0


def test_an_unknown_arm_label_fails_closed(tmp_path: Path) -> None:
    records, served = _all_served()
    records[0] = records[0].model_copy(update={"graph_arm": "mystery-arm"})
    run_dir, log = _write_run(tmp_path, records, served)

    with pytest.raises(ValueError, match="mystery-arm"):
        script.build_map(run_dir, log)


def test_a_legacy_journal_is_grouped_under_the_canonical_labels(
    tmp_path: Path,
) -> None:
    records = [
        _record(0).model_copy(update={"graph_arm": "graph-off"}),
        _record(1).model_copy(update={"graph_arm": "graph-on"}),
    ]
    served = [
        _served_line("cid-0", "OpenInference", 0),
        _served_line("cid-1", "OpenInference", 1),
    ]
    run_dir, log = _write_run(tmp_path, records, served)

    rows, summary = script.build_map(run_dir, log)

    assert [r["graph_arm"] for r in rows] == ["graph-off", "graph-on"]
    assert list(summary["by_arm_provider"]) == ["hybrid", "hybrid+graph"]


def test_main_writes_the_rows_and_the_summary_and_leaves_the_run_alone(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    records, served = _all_served()
    run_dir, log = _write_run(tmp_path, records, served)
    journal = run_dir / "journal.jsonl"
    before = hashlib.sha256(journal.read_bytes()).hexdigest()

    code = script.main([str(run_dir), str(log)])

    assert code == 0
    out_dir = run_dir / "diagnostic"
    lines = (out_dir / "provider_format_map.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in lines.splitlines()]
    assert len(rows) == 8
    summary = json.loads(
        (out_dir / "provider_format_map-summary.json").read_text(encoding="utf-8")
    )
    for key in (
        "served_lines_not_in_journal",
        "unmatched_count",
        "by_arm_provider",
        "provider_sequence_rle",
        "join_coverage",
        "served_lines_total",
    ):
        assert key in summary, key
    assert list(summary["by_arm_provider"]) == ARMS
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in run_dir.iterdir()) == [
        "diagnostic",
        "journal.jsonl",
    ]
    assert json.loads(capsys.readouterr().out)["records"] == 8


def test_main_honours_out_dir(tmp_path: Path) -> None:
    records, served = _all_served()
    run_dir, log = _write_run(tmp_path, records, served)
    out_dir = tmp_path / "elsewhere"

    assert script.main([str(run_dir), str(log), "--out-dir", str(out_dir)]) == 0

    assert (out_dir / "provider_format_map.jsonl").is_file()
    assert (out_dir / "provider_format_map-summary.json").is_file()
    assert not (run_dir / "diagnostic").exists()


def test_the_script_is_read_only_by_construction() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "journal.jsonl" in source
    assert "read-only" in source.lower()
    assert "06.3.4.1" in source
