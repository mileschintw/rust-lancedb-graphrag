"""Tests for eval/scripts/paper_text_crosscheck.py: the D-102 text-rule cross-check."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from lancet_eval.arms import ARM_REGISTRY, arm_slug
from lancet_eval.client import (
    Notice,
    RankedCandidate,
    RetrievalSnapshot,
    StructuredCitation,
)
from lancet_eval.config import repo_root
from lancet_eval.journal import Journal, RunRecord

SCRIPT_PATH = repo_root() / "eval" / "scripts" / "paper_text_crosscheck.py"


def _load_script():  # type: ignore[no-untyped-def]
    """Loads the script by file path (a standalone script, not a package member)."""
    spec = importlib.util.spec_from_file_location("paper_text_crosscheck", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["paper_text_crosscheck"] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

ARMS = ("dense-only", "hybrid")
ABLATION = Notice(code="GRAPH_ABLATION", message="", typed_code=18)
HEX = "0" * 64
GENERATION = "lance-7"

FACTS = {
    "q1": ["Alpha one fact text.", "Alpha two fact text."],
    "q2": ["Beta fact text.", "Beta second fact."],
    # an empty second fact: the official function counts it in min(len(gold), 10) and
    # an empty string matches every chunk, so the raw evidence_list must be kept
    "q3": ["Gamma fact text.", ""],
}
G_IDS = list(FACTS)

# gold chunk sets per evidence entry; q3's second entry is split across chunks (empty)
GOLD_SETS = {
    "q1": [["q1:a"], ["q1:b"]],
    "q2": [["q2:a"], ["q2:b"]],
    "q3": [["q3:a"], []],
}

# gold chunk position in each arm's ranking (1-based)
POSITIONS: dict[str, dict[str, dict[str, int]]] = {
    "hybrid": {
        "q1": {"q1:a": 1, "q1:b": 2},
        "q2": {"q2:a": 2},
        "q3": {"q3:a": 3},
    },
    "dense-only": {
        # the duplicate article repeats q1's first fact at rank 1, ahead of the
        # gold chunk, and gold_chunks.jsonl does not list it
        "q1": {"dup:q1": 1, "q1:a": 5, "q1:b": 6},
        "q2": {"q2:a": 2},
        "q3": {"q3:a": 3},
    },
}

TEXTS = {
    "q1:a": f"Intro. {FACTS['q1'][0]} Outro.",
    "q1:b": f"Middle. {FACTS['q1'][1]} End.",
    "q2:a": f"Start. {FACTS['q2'][0]} Finish.",
    "q2:b": "A chunk that does not hold the second beta fact.",
    "q3:a": f"Opening {FACTS['q3'][0]} closing.",
    "q3:b": "Padding chunk for gamma b.",
    "dup:q1": f"Elsewhere another article repeats: {FACTS['q1'][0]}",
}


def _ranking_ids(arm: str, qid: str) -> list[str]:
    ids = [f"{qid}:{arm_slug(arm)}:f{pos}" for pos in range(1, 13)]
    for chunk_id, pos in POSITIONS[arm][qid].items():
        ids[pos - 1] = chunk_id
    return ids


def _text(chunk_id: str) -> str:
    if chunk_id in TEXTS:
        return TEXTS[chunk_id]
    return f"filler {chunk_id}"


def _record(arm: str, qid: str, *, outcome: str = "success") -> RunRecord:
    spec = ARM_REGISTRY[arm]
    ids = _ranking_ids(arm, qid)
    ranking = [
        RankedCandidate(
            chunk_id=cid,
            document_id="doc1",
            fused_rank=i,
            vector_rank=i,
            bm25_rank=i if spec.retrieval_mode != "dense_only" else None,
        )
        for i, cid in enumerate(ids, start=1)
    ]
    final = [
        StructuredCitation(
            chunk_id=r.chunk_id,
            document_id="doc1",
            excerpt=_text(r.chunk_id)[:512],
            rank=r.fused_rank,
        )
        for r in ranking[:8]
    ]
    snapshot = RetrievalSnapshot(
        index_generation=GENERATION,
        vector_weight=1.0,
        bm25_weight=1.0,
        rrf_k=60,
        candidate_limit=32,
        final_limit=8,
        result_hash="abc123",
        retrieved_chunks=final,
        retrieval_mode=spec.retrieval_mode,
        pre_truncation_ranking=ranking,
    )
    if outcome == "error":
        return RunRecord(
            corpus="fx",
            question_id=qid,
            graph_arm=arm,
            outcome="error",
            error_type="timeout",
            error="boom",
            index_generation=GENERATION,
            notices=[ABLATION],
        )
    return RunRecord(
        corpus="fx",
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer="Answer: x",
        index_generation=GENERATION,
        notices=[ABLATION],
        structured_citations=final[:1],
        snapshot=snapshot,
    )


class Fixture:
    """Paths of one tmp cross-check input set."""

    def __init__(self, tmp_path: Path, *, errored: tuple[str, str] | None = None) -> None:
        self.dir = tmp_path
        self.journal = tmp_path / "journal.jsonl"
        self.split = tmp_path / "split.json"
        self.gold = tmp_path / "gold_chunks.jsonl"
        self.questions = tmp_path / "questions.jsonl"
        self.dump = tmp_path / "dump.jsonl"
        self.out = tmp_path / "diagnostic" / "text_crosscheck.json"
        journal = Journal(self.journal)
        journal.write_header(corpus="fx", partial=False)
        for arm in ARMS:
            for qid in G_IDS:
                journal.append(
                    _record(arm, qid, outcome="error" if (arm, qid) == errored else "success")
                )
        self.split.write_text(
            json.dumps(
                {
                    "derivation_rule": "test",
                    "populations_sha256": HEX,
                    "diag_selection_sha256": HEX,
                    "questions_sample_sha256": HEX,
                    "dev_source": "dev.json",
                    "order_seed": 42,
                    "dev_ids": ["dev1"],
                    "heldout_g_ids": G_IDS,
                    "heldout_null_ids": [],
                }
            ),
            encoding="utf-8",
        )
        rows = []
        for qid, sets in GOLD_SETS.items():
            for i, chunk_ids in enumerate(sets):
                rows.append(
                    {
                        "question_id": qid,
                        "evidence_index": i,
                        "title": "t",
                        "document_id": "doc1",
                        "state": "in_chunk" if chunk_ids else "split_across_chunks",
                        "chunk_ids": chunk_ids,
                    }
                )
        self.gold.write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
        self.questions.write_text(
            "".join(
                json.dumps(
                    {
                        "question_id": qid,
                        "query": f"Question {qid}?",
                        "question_type": "comparison_query",
                        "answer": "Yes",
                        "evidence_list": [{"title": "t", "fact": f} for f in facts],
                    }
                )
                + "\n"
                for qid, facts in FACTS.items()
            ),
            encoding="utf-8",
        )
        self.write_dump()

    def write_dump(
        self,
        *,
        drop: set[str] = frozenset(),  # type: ignore[assignment]
        override: dict[str, str] | None = None,
        bad_digest: str | None = None,
    ) -> None:
        ids: dict[str, None] = {}
        for arm in ARMS:
            for qid in G_IDS:
                for cid in _ranking_ids(arm, qid):
                    ids.setdefault(cid)
        rows = []
        for cid in ids:
            if cid in drop:
                continue
            text = (override or {}).get(cid, _text(cid))
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if cid == bad_digest:
                digest = "f" * 64
            rows.append(
                {
                    "chunk_id": cid,
                    "document_id": "doc1",
                    "chunk_index": 0,
                    "content_sha256": digest,
                    "text": text,
                }
            )
        self.dump.write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )

    def args(self) -> list[str]:
        return [
            "--journal",
            str(self.journal),
            "--split",
            str(self.split),
            "--gold-chunks",
            str(self.gold),
            "--questions",
            str(self.questions),
            "--dump",
            str(self.dump),
            "--out",
            str(self.out),
        ]

    def run(self) -> dict[str, Any]:
        assert script.main(self.args()) == 0
        return json.loads(self.out.read_text(encoding="utf-8"))


def _entry(result: dict[str, Any], arm: str, qid: str) -> dict[str, Any]:
    found = [
        e for e in result["records"] if e["arm"] == arm and e["question_id"] == qid
    ]
    assert len(found) == 1
    return found[0]


# ---- --emit-ids --------------------------------------------------------------------


def test_emit_ids_lists_the_distinct_ranked_ids_and_prints_the_single_generation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fx = Fixture(tmp_path)
    ids_path = tmp_path / "ids.jsonl"
    assert script.main(["--journal", str(fx.journal), "--emit-ids", str(ids_path)]) == 0
    assert f"index_generation: {GENERATION}" in capsys.readouterr().out
    rows = [json.loads(line) for line in ids_path.read_text().splitlines()]
    assert all(set(r) == {"chunk_id"} for r in rows)
    got = [r["chunk_id"] for r in rows]
    assert len(got) == len(set(got))
    want = {
        cid for arm in ARMS for qid in G_IDS for cid in _ranking_ids(arm, qid)[:10]
    }
    assert set(got) == want
    assert "dup:q1" in got
    # only ranks 1 to 10 are listed: the gold chunk at rank 11 or 12 would be absent
    assert not [c for c in got if c.endswith(":f11") or c.endswith(":f12")]


def test_emit_ids_exits_non_zero_on_mixed_generations(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    journal = Journal(fx.journal)
    other = _record("hybrid", "q1").model_copy(
        update={"question_id": "q9", "index_generation": "lance-8"}
    )
    journal.append(other)
    assert (
        script.main(
            ["--journal", str(fx.journal), "--emit-ids", str(tmp_path / "ids.jsonl")]
        )
        != 0
    )


# ---- main mode ----------------------------------------------------------------------


def test_main_writes_per_record_verdicts_and_per_arm_disagreement_counts(
    tmp_path: Path,
) -> None:
    result = Fixture(tmp_path).run()
    assert result["index_generation"] == GENERATION
    assert result["n_heldout_g"] == 3
    assert result["n_p4"] == 3
    assert len(result["records"]) == len(ARMS) * len(G_IDS)
    for key in (
        "question_id",
        "arm",
        "text_hit4",
        "text_hit10",
        "text_first_hit_rank",
        "text_ap",
        "disagree_hit4",
        "disagree_hit10",
        "disagree_first_hit_rank",
        "disagree_ap",
    ):
        assert key in result["records"][0]
    hybrid = _entry(result, "hybrid", "q1")
    assert (hybrid["text_hit4"], hybrid["text_first_hit_rank"]) == (1, 1)
    assert hybrid["text_ap"] == pytest.approx((1 + 1 / 2) / 2)
    assert not any(hybrid[f"disagree_{k}"] for k in ("hit4", "hit10", "first_hit_rank", "ap"))
    dense = result["arms"]["dense-only"]["p4"]
    hyb = result["arms"]["hybrid"]["p4"]
    assert dense["n"] == hyb["n"] == 3
    assert dense["disagree_hit4"] == 1
    assert dense["disagree_hit10"] == 0
    assert dense["disagree_first_hit_rank"] == 2  # q1 (duplicate) and q3 (empty fact)
    assert dense["disagree_ap"] == 2
    assert hyb["disagree_hit4"] == 0
    assert hyb["disagree_first_hit_rank"] == 1  # q3 alone
    assert result["arms"]["dense-only"]["script_faithful"]["n"] == 3
    assert result["per_arm_text_hit4_p4"]["dense-only"] == {"q1": 1, "q2": 1, "q3": 1}


def test_a_fact_in_an_unlisted_duplicate_chunk_is_a_text_hit_and_an_id_miss(
    tmp_path: Path,
) -> None:
    result = Fixture(tmp_path).run()
    dense_q1 = _entry(result, "dense-only", "q1")
    assert dense_q1["id_hit4"] == 0
    assert dense_q1["id_first_hit_rank"] == 5
    assert dense_q1["text_hit4"] == 1
    assert dense_q1["text_first_hit_rank"] == 1
    assert dense_q1["disagree_hit4"] is True
    assert dense_q1["disagree_hit10"] is False
    assert dense_q1["text_ap"] == pytest.approx((1 / 1 + 1 / 6) / 2)
    assert dense_q1["id_ap"] == pytest.approx((1 / 5 + 1 / 6) / 2)


def test_the_raw_evidence_list_keeps_an_empty_fact_in_the_divisor(
    tmp_path: Path,
) -> None:
    result = Fixture(tmp_path).run()
    q3 = _entry(result, "hybrid", "q3")
    # the empty fact matches rank 1 (1/1), the gamma fact first matches rank 3 (1/3),
    # and the divisor is min(2, 10); dropping the empty fact would give 1/3
    assert q3["text_first_hit_rank"] == 1
    assert q3["text_ap"] == pytest.approx((1 + 1 / 3) / 2)
    assert q3["id_ap"] == pytest.approx((1 / 3) / 2)


def test_a_record_without_a_valid_ranking_is_a_miss_on_the_script_faithful_line(
    tmp_path: Path,
) -> None:
    result = Fixture(tmp_path, errored=("hybrid", "q2")).run()
    assert result["n_p4"] == 2
    assert "q2" not in result["p4_question_ids"]
    hybrid = result["arms"]["hybrid"]
    assert hybrid["p4"]["n"] == 2
    assert hybrid["script_faithful"]["n"] == 3
    assert hybrid["script_faithful"]["n_no_valid_ranking"] == 1
    missed = _entry(result, "hybrid", "q2")
    assert missed["valid_ranking"] is False
    assert missed["in_p4"] is False
    assert (missed["text_hit4"], missed["id_hit4"]) == (0, 0)
    assert result["arms"]["dense-only"]["script_faithful"]["n_no_valid_ranking"] == 0


# ---- refusals -----------------------------------------------------------------------


def test_a_ranked_id_missing_from_the_dump_exits_3_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fx = Fixture(tmp_path)
    fx.write_dump(drop={"q2:a"})
    assert script.main(fx.args()) == 3
    err = capsys.readouterr().err
    assert "q2:a" in err
    assert not fx.out.exists()


def test_a_final_eight_excerpt_that_drifted_exits_4_naming_the_chunk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fx = Fixture(tmp_path)
    fx.write_dump(override={"q1:b": "The store now holds different text for this chunk."})
    assert script.main(fx.args()) == 4
    err = capsys.readouterr().err
    assert "q1:b" in err
    assert "different text" not in err  # IDs only, never chunk text
    assert not fx.out.exists()


def test_a_dump_text_that_does_not_match_its_digest_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fx = Fixture(tmp_path)
    fx.write_dump(bad_digest="q1:a")
    assert script.main(fx.args()) != 0
    assert "q1:a" in capsys.readouterr().err
    assert not fx.out.exists()


def test_the_excerpt_bound_is_the_engines_code_point_prefix(tmp_path: Path) -> None:
    """A chunk longer than the bound is compared by its first N Unicode code points."""
    fx = Fixture(tmp_path)
    long_text = "é" + "x" * 600  # longer than 512 code points, with a multi-byte start
    fx.write_dump(override={"q1:a": long_text})
    # the journal excerpt is the old short text, so the long dump text is drift
    assert script.main(fx.args()) == 4
    assert script.main([*fx.args(), "--excerpt-max-chars", "5"]) == 4


# ---- no chunk text, no scorer -------------------------------------------------------


def _walk(value: Any):  # type: ignore[no-untyped-def]
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def test_the_output_carries_no_chunk_text(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    result = fx.run()
    leaves = list(_walk(result))
    assert "text" not in [k for k in leaves if isinstance(k, str)]
    assert not [v for v in leaves if isinstance(v, str) and len(v) > 200]
    raw = fx.out.read_text(encoding="utf-8")
    for text in TEXTS.values():
        assert text not in raw
    for fact in FACTS["q1"]:
        assert fact not in raw


def _imported_modules() -> set[str]:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_the_script_imports_neither_the_scorer_nor_the_report_generator() -> None:
    modules = _imported_modules()
    assert "lancet_eval.score" not in modules
    assert "lancet_eval.report" not in modules
    assert "subprocess" not in modules


def test_the_main_mode_needs_its_arguments(tmp_path: Path) -> None:
    fx = Fixture(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        script.main(["--journal", str(fx.journal)])
    assert exc_info.value.code == 2
