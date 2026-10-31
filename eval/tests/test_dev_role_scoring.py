"""`score` and `compare-levers` on a dev-role corpus (#68, D-237, D-252, D-259).

S1 and S2 run on the dev pool. On a corpus whose `[split] role` is `dev`, both read
the dev population the way `dev_reads.py` scopes it: G = the dev IDs with gold
evidence, null = the dev null IDs. The fixture's dev split names held-out IDs that are
not in the corpus's question file, so a read of the held-out lists fails loudly.
Held-out corpora keep today's reading (the rest of the suite, and the slow v1.0
re-score).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
import replay_fixture as rf
import test_reader_comparison as s2
import test_s1_store_arms as s1

from lancet_eval.lever_comparison import build_lever_comparison, render_markdown
from lancet_eval.score import ScoreError, score_run
from lancet_eval.split import load_split, split_sha256

N_G, N_NULL = 10, 5
MIN_PAIR_FRACTION = 0.80


def _split_marker(gold: Path) -> dict[str, Any]:
    """The header marker a dev drive writes (D-107), from the fixture's split file."""
    split = load_split(gold.parent / "eval" / "corpora" / "levers" / "split.json")
    return {"order_seed": split.order_seed, "split_sha256": split_sha256(split)}


def _sizes(report: Any) -> dict[str, float]:
    (size,) = [d for d in report.dimensions if d.name == "p4_size"]
    return size.detail


def _assert_dev_populations(payload: dict[str, Any]) -> None:
    pops = payload["populations"]
    assert (pops["n_heldout_g"], pops["n_heldout_null"]) == (N_G, N_NULL)
    assert pops["population"] == "dev"
    floor = math.ceil(MIN_PAIR_FRACTION * N_NULL)
    for guard in payload["null_guards"]:
        assert guard["n_heldout_null"] == N_NULL
        assert guard["min_pairs"] == floor
    md = render_markdown(payload)
    assert f"dev population: |H_G| = {N_G}, |H_N| = {N_NULL}" in md


def test_s1_dev_run_is_scored_and_compared_on_the_dev_population(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = s1._build(tmp_path, monkeypatch, role="dev")
    report = score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    sizes = _sizes(report)
    assert (sizes["n_heldout_g"], sizes["n_heldout_null"]) == (N_G, N_NULL)
    assert f"of {N_G} dev G questions" in (report.metadata.notes or "")
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    _assert_dev_populations(payload)
    assert {c["arm"] for f in payload["families"] for c in f["comparisons"]} == {
        s1.MERGED_OFF,
        s1.MERGED_ON,
    }


def test_a_dev_header_marker_is_checked_against_the_split_file(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # The marker hashes the split file as written, not the dev-scoped view of it.
    _, probe, _ = s1._build(tmp_path / "probe", monkeypatch, role="dev")
    header = _split_marker(probe)
    run, gold, _ = s1._build(tmp_path / "run", monkeypatch, role="dev", header=header)
    assert '"split_sha256"' in (run / "journal.jsonl").read_text(encoding="utf-8")
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)


def test_a_dev_id_missing_from_the_question_file_is_refused(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = s1._build(tmp_path, monkeypatch, role="dev")
    split_file = gold.parent / "eval" / "corpora" / "levers" / "split.json"
    data = json.loads(split_file.read_text(encoding="utf-8"))
    data["dev_ids"].append("lv-gone")
    split_file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ScoreError, match=r"lv-gone: not in the corpus's question"):
        score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)


def test_s2_dev_run_with_reader_arms_is_scored_and_compared_on_the_dev_population(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = s2._s2(tmp_path, monkeypatch, role="dev")
    report = score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    sizes = _sizes(report)
    assert (sizes["n_heldout_g"], sizes["n_heldout_null"]) == (N_G, N_NULL)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    _assert_dev_populations(payload)
    (group,) = payload["reader_comparison"]["groups"]
    assert {r["arm"] for r in group["readers"]} == {rf.BASE, *s2.READER_ARMS}


def test_a_heldout_payload_carries_no_population_label(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    run, gold, _ = s1._build(tmp_path, monkeypatch)
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    payload = build_lever_comparison(run, gold_chunks_path=gold)
    assert "population" not in payload["populations"]
    assert "dev population" not in render_markdown(payload)
