"""Tests for the 06.3.5 cache-only, counts-only judge stage (D-112, D-120, D-86).

No test makes a network call: `judge_once` is replaced by a recording fake. The
fixtures run on the real `multihop_rag_heldout` and `multihop_rag_rehearsal` corpora
and the committed split, so the judge configuration read from the corpus TOML is the
real one. The D-73 ordering gates read the `preregistered_clean_tree` fixture, never
the working tree.
"""

from __future__ import annotations

import ast
import functools
import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from lancet_eval import gitcheck, judge_stage
from lancet_eval import score as score_mod
from lancet_eval.arms import ARM_REGISTRY
from lancet_eval.cli import app
from lancet_eval.client import (
    Notice,
    RankedCandidate,
    RetrievalSnapshot,
    StructuredCitation,
)
from lancet_eval.config import repo_root
from lancet_eval.corpus import GoldQuestion, load_sample_questions
from lancet_eval.journal import Journal, RunRecord, WorkflowWireMeta
from lancet_eval.judge import (
    JudgeCache,
    JudgeCacheEntry,
    JudgeUsage,
    JudgeVerdict,
    cache_key,
)
from lancet_eval.judge_stage import JudgeStageError, run_judge_stage
from lancet_eval.measure import estimate_judge_cost_per_question
from lancet_eval.split import HeldOutSplit, load_split

ARMS = ("dense-only", "bm25-only", "hybrid", "hybrid+graph")
HELDOUT = "multihop_rag_heldout"
REHEARSAL = "multihop_rag_rehearsal"
API_KEY = "sk-test-secret-key-0123456789"
ABLATION = Notice(code="GRAPH_ABLATION", message="", typed_code=18)
NO_EVIDENCE = Notice(code="NO_EVIDENCE", message="", typed_code=1)
FORBIDDEN = re.compile(
    r"groundedness|faithfulness|mean|kappa|qwk|spearman|delta", re.IGNORECASE
)
COST = estimate_judge_cost_per_question(400)


# --- fixtures and builders (also imported by test_calibration.py) --------------------


@functools.cache
def _gold(corpus: str) -> dict[str, GoldQuestion]:
    return {q.question_id: q for q in load_sample_questions(corpus)}


@functools.cache
def real_split() -> HeldOutSplit:
    path = repo_root() / "eval" / "corpora" / "multihop_rag" / "heldout_split.json"
    return load_split(path)


def g_ids(
    n_comparison: int = 4, n_inference: int = 4, n_temporal: int = 4
) -> list[str]:
    """Real held-out G question IDs: the first n of each type, sorted by ID."""
    gold = _gold(HELDOUT)
    pool = sorted(real_split().heldout_g_ids)
    out: list[str] = []
    for qtype, n in (
        ("comparison_query", n_comparison),
        ("inference_query", n_inference),
        ("temporal_query", n_temporal),
    ):
        out += [q for q in pool if gold[q].question_type == qtype][:n]
    return out


def _ranking(arm: str, n: int) -> list[RankedCandidate]:
    mode = ARM_REGISTRY[arm].retrieval_mode
    return [
        RankedCandidate(
            chunk_id=f"d{i}:0",
            document_id=f"d{i}",
            fused_rank=i,
            vector_rank=i if mode != "bm25_only" else None,
            bm25_rank=i if mode != "dense_only" else None,
            graph_rank=None,
            graph_boosted=False,
        )
        for i in range(1, n + 1)
    ]


def _final(
    ranking: list[RankedCandidate], excerpt: str, limit: int = 8
) -> list[StructuredCitation]:
    return [
        StructuredCitation(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            rank=r.fused_rank,
            graph_boosted=r.graph_boosted,
            excerpt=excerpt,
        )
        for r in ranking[:limit]
    ]


def make_record(
    arm: str,
    qid: str,
    *,
    answer: str | None = None,
    excerpt: str | None = None,
    error: bool = False,
    no_evidence: bool = False,
    drop_ablation: bool = False,
    uncited: bool = False,
    corpus: str = HELDOUT,
) -> RunRecord:
    """A well-formed record of a canonical arm, with the knobs the tests turn.

    The default answer differs per arm and question, so no two records share a
    cache key unless a test makes them.
    """
    spec = ARM_REGISTRY[arm]
    ranking = [] if no_evidence else _ranking(arm, 12)
    text = excerpt if excerpt is not None else f"Evidence text for question {qid}."
    final = _final(ranking, text)
    snapshot = RetrievalSnapshot(
        index_generation="gen1",
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
    notices: list[Notice] = []
    if spec.disable_graph_context and not drop_ablation:
        notices.append(ABLATION)
    if no_evidence:
        notices.append(NO_EVIDENCE)
    return RunRecord(
        corpus=corpus,
        question_id=qid,
        graph_arm=arm,
        outcome="error" if error else "success",
        answer=""
        if no_evidence
        else (answer or f"Reasoning for {qid} under {arm}. Answer: Yes"),
        snapshot=snapshot,
        notices=notices,
        structured_citations=[] if (no_evidence or uncited) else final[:2],
        workflow_meta=WorkflowWireMeta(
            vector_count=0 if spec.retrieval_mode == "bm25_only" else 8,
            bm25_count=0 if spec.retrieval_mode == "dense_only" else 8,
        ),
    )


def standard_records(
    qids: list[str], **overrides: RunRecord
) -> list[RunRecord]:
    """Every arm answers every question; `overrides` replace `arm|qid` records."""
    out: list[RunRecord] = []
    for qid in qids:
        for arm in ARMS:
            out.append(overrides.get(f"{arm}|{qid}") or make_record(arm, qid))
    return out


def build_run(
    tmp_path: Path,
    records: list[RunRecord],
    *,
    corpus: str = HELDOUT,
    partial: bool = False,
    name: str = "run",
) -> Path:
    """Write a journal (header, then records) into `tmp_path/name` and return it."""
    run = tmp_path / name
    run.mkdir(parents=True, exist_ok=True)
    journal = Journal(run / "journal.jsonl")
    journal.write_header(corpus=corpus, partial=partial)
    for rec in records:
        journal.append(rec)
    return run


class FakeJudge:
    """A recording stand-in for `judge_once`; it never touches the network.

    The n-th DISTINCT cache key seen (1-based) fails its first `fail_times`
    invocations when n is in `fail_at`; every other invocation returns a verdict.
    """

    def __init__(
        self,
        *,
        fail_at: set[int] | None = None,
        fail_times: int = 2,
        usage: JudgeUsage | None = None,
        error_text: str = "judge failed",
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_at = fail_at or set()
        self.fail_times = fail_times
        self.usage = usage
        self.error_text = error_text
        self._order: dict[str, int] = {}
        self._attempts: dict[str, int] = {}

    def __call__(
        self, client: Any = None, **kwargs: Any
    ) -> tuple[JudgeVerdict | None, str | None, JudgeUsage | None]:
        key = cache_key(
            prompt_version=kwargs["prompt_version"],
            judge_model=kwargs["model"],
            question=kwargs["question"],
            answer=kwargs["answer"],
            post_truncation_evidence=kwargs["evidence"],
        )
        self.calls.append(kwargs)
        position = self._order.setdefault(key, len(self._order) + 1)
        attempt = self._attempts[key] = self._attempts.get(key, 0) + 1
        if position in self.fail_at and attempt <= self.fail_times:
            return (None, self.error_text, None)
        return (JudgeVerdict(groundedness=4, faithfulness=3), None, self.usage)


def install_fake(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> FakeJudge:
    fake = FakeJudge(**kwargs)
    monkeypatch.setattr(judge_stage, "judge_once", fake)
    return fake


@pytest.fixture
def stage_env(
    monkeypatch: pytest.MonkeyPatch, preregistered_clean_tree: str
) -> FakeJudge:
    """A key in the environment, the D-73 gates passing, and a recording fake judge."""
    monkeypatch.setenv("OPENROUTER_API_KEY", API_KEY)
    return install_fake(monkeypatch)


def _stage(run: Path, cap: float = 1.0, **kwargs: Any) -> judge_stage.JudgeStageRecord:
    return run_judge_stage(run_dir=run, stage_cap=cap, **kwargs)


def _stage_json(run: Path) -> dict[str, Any]:
    return json.loads((run / "judge-stage.json").read_text(encoding="utf-8"))


# --- the happy path -------------------------------------------------------------------


def test_every_judgeable_record_of_every_arm_is_judged_and_cached(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    qids = g_ids()
    null_id = real_split().heldout_null_ids[0]
    records = standard_records(
        qids,
        **{
            f"dense-only|{qids[0]}": make_record(
                "dense-only", qids[0], no_evidence=True
            ),
            f"bm25-only|{qids[1]}": make_record("bm25-only", qids[1], uncited=True),
            f"hybrid|{qids[2]}": make_record("hybrid", qids[2], drop_ablation=True),
            f"hybrid+graph|{qids[3]}": make_record(
                "hybrid+graph", qids[3], error=True
            ),
        },
    )
    records.append(make_record("hybrid", null_id))  # a null question: never judged
    run = build_run(tmp_path, records)

    result = _stage(run)

    assert result.stop_reason is None
    # 48 records minus an abstention, an uncited, a provenance failure and an error
    assert len(stage_env.calls) == 44
    cache = JudgeCache(run / "judge_cache.json")
    assert len(cache.entries) == 44
    assert all(e.verdict is not None for e in cache.entries.values())
    for arm in ARMS:
        counts = result.arms[arm]
        assert counts.judgeable == 11
        assert counts.unique_keys == 11
        assert counts.judged_now == 11
        assert counts.cached_before == 0
        assert counts.errors == 0
        assert counts.re_attempted == 0
    assert list(result.arms) == list(ARMS)  # registry order
    assert not (run / "report.json").exists()


def test_the_judge_config_comes_from_the_corpus_toml(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    result = _stage(run)
    assert result.judge_model == "meta-llama/llama-3.3-70b-instruct"
    assert result.judge_prompt_version == "v1"
    assert stage_env.calls
    for call in stage_env.calls:
        assert call["model"] == "meta-llama/llama-3.3-70b-instruct"
        assert call["temperature"] == 0.0
        assert call["max_tokens"] == 400
        assert call["prompt_version"] == "v1"
        assert call["api_key"] == API_KEY


def test_the_cache_key_matches_the_legacy_judge_loop(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    from lancet_eval.judge import truncate_evidence

    qid = g_ids(1, 0, 0)[0]
    rec = make_record("hybrid", qid)
    run = build_run(tmp_path, [rec])
    _stage(run)
    expected = cache_key(
        prompt_version="v1",
        judge_model="meta-llama/llama-3.3-70b-instruct",
        question=_gold(HELDOUT)[qid].question,
        answer=rec.answer or "",
        post_truncation_evidence=truncate_evidence(rec.structured_citations),
    )
    assert expected in JudgeCache(run / "judge_cache.json").entries


def test_arms_with_an_identical_answer_and_evidence_share_one_call(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    qids = g_ids(2, 2, 2)
    shared = "Shared answer text. Answer: Yes"
    records = standard_records(
        qids,
        **{
            f"hybrid|{qids[0]}": make_record("hybrid", qids[0], answer=shared),
            f"hybrid+graph|{qids[0]}": make_record(
                "hybrid+graph", qids[0], answer=shared
            ),
        },
    )
    run = build_run(tmp_path, records)

    result = _stage(run)

    assert len(stage_env.calls) == 23  # 24 records, one shared key
    assert result.unique_keys_total == 23
    assert result.arms["hybrid"].judgeable == 6
    assert result.arms["hybrid+graph"].judgeable == 6
    assert result.arms["hybrid"].unique_keys == 6
    assert result.arms["hybrid+graph"].unique_keys == 6
    # a shared key is judged once and counted for the first arm in registry order
    assert result.arms["hybrid"].judged_now == 6
    assert result.arms["hybrid+graph"].judged_now == 5
    assert len(JudgeCache(run / "judge_cache.json").entries) == 23


def test_judge_stage_json_holds_the_per_arm_counts_and_timings(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 1)))
    _stage(run, cap=0.5)
    data = _stage_json(run)
    assert data["mode"] == "heldout"
    assert data["stage_cap"] == 0.5
    assert data["stop_reason"] is None
    assert data["calls"] == 12
    assert data["spend_usd"] == pytest.approx(12 * COST)
    assert isinstance(data["wall_clock_s"], float)
    assert 0.0 <= data["per_call_latency_ms_p50"] <= data["per_call_latency_ms_p95"]
    assert set(data["arms"]) == set(ARMS)
    assert set(data["arms"]["hybrid"]) == {
        "judgeable",
        "unique_keys",
        "cached_before",
        "judged_now",
        "errors",
        "re_attempted",
        "not_attempted",
    }


def test_a_second_stage_reuses_the_cache_and_makes_no_call(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 1)))
    _stage(run)
    first = len(stage_env.calls)
    result = _stage(run)
    assert len(stage_env.calls) == first
    assert result.calls == 0
    assert result.per_call_latency_ms_p50 is None
    for arm in ARMS:
        assert result.arms[arm].cached_before == 3
        assert result.arms[arm].judged_now == 0


def test_a_cached_error_entry_is_attempted_again(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _stage(run)
    calls_before = len(stage_env.calls)
    cache = JudgeCache(run / "judge_cache.json")
    key, entry = next(iter(sorted(cache.entries.items())))
    cache.set(
        key,
        JudgeCacheEntry(
            cache_key=key,
            prompt_version=entry.prompt_version,
            judge_model=entry.judge_model,
            question=entry.question,
            answer=entry.answer,
            evidence=entry.evidence,
            error="an earlier stage failed",
        ),
    )
    result = _stage(run)
    assert len(stage_env.calls) == calls_before + 1
    assert JudgeCache(run / "judge_cache.json").get(key).verdict is not None
    assert sum(a.judged_now for a in result.arms.values()) == 1


# --- the refusals, each before the first call ---------------------------------


def _refused(run: Path, fake: FakeJudge, match: str, **kwargs: Any) -> None:
    with pytest.raises(JudgeStageError, match=match):
        _stage(run, **kwargs)
    assert fake.calls == []
    assert not (run / "judge_cache.json").exists()
    assert not (run / "judge-stage.json").exists()


def test_an_open_journal_is_refused(tmp_path: Path, stage_env: FakeJudge) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)), partial=True)
    _refused(run, stage_env, "open")


def test_a_journal_without_a_header_is_refused(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    journal = Journal(run / "journal.jsonl")
    for rec in standard_records(g_ids(1, 0, 0)):
        journal.append(rec)
    _refused(run, stage_env, "header")


@pytest.mark.parametrize("key", [None, "", "   "])
def test_an_empty_api_key_is_refused(
    tmp_path: Path,
    stage_env: FakeJudge,
    monkeypatch: pytest.MonkeyPatch,
    key: str | None,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "OPENROUTER_API_KEY", api_key=key)


def test_a_missing_environment_key_is_refused(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "OPENROUTER_API_KEY")


def test_an_uncommitted_trust_floor_is_refused(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gitcheck, "introducing_commit", lambda token, path, *, repo=None: None
    )
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "D-73")


def test_a_trust_floor_that_is_not_an_ancestor_of_head_is_refused(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gitcheck, "is_ancestor", lambda a, b, *, repo=None: False)
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "ancestor")


def test_a_dirty_harness_source_tree_is_refused(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gitcheck, "is_clean", lambda *paths, repo=None: False)
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "uncommitted")


def test_the_trust_floor_commit_must_predate_the_journal(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gitcheck, "commit_time", lambda sha, *, repo=None: 4_000_000_000
    )
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "created_at")


def test_git_calls_are_pointed_at_the_given_repository(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Path | None] = []

    def clean(*paths: str, repo: Path | None = None) -> bool:
        seen.append(repo)
        return True

    monkeypatch.setattr(gitcheck, "is_clean", clean)
    run = build_run(tmp_path, standard_records(g_ids(1, 0, 0)))
    elsewhere = tmp_path / "elsewhere"
    _stage(run, git_repo=elsewhere)
    assert seen == [elsewhere]


@pytest.mark.parametrize(
    "cap", [float("nan"), 0.0, -1.0, float("inf"), float("-inf")]
)
def test_an_invalid_cap_is_refused(
    tmp_path: Path, stage_env: FakeJudge, cap: float
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "cap", cap=cap)


def test_a_cap_below_the_uncached_estimate_is_refused(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))  # 8 keys
    _refused(run, stage_env, "cap", cap=8 * COST * 0.99)


def test_a_cap_at_the_uncached_estimate_is_accepted(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    result = _stage(run, cap=8 * COST * 1.001)
    assert result.stop_reason is None
    assert len(stage_env.calls) == 8


def test_the_estimate_counts_only_the_uncached_keys(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _stage(run)
    # everything is cached, so a cap far below the full estimate is enough
    result = _stage(run, cap=COST / 100)
    assert result.calls == 0


def test_a_record_of_an_unknown_arm_fails_closed(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    qids = g_ids(1, 1, 0)
    records = standard_records(qids)
    records.append(
        make_record("hybrid", qids[0]).model_copy(
            update={"graph_arm": "graph-sideways", "question_id": qids[1]}
        )
    )
    run = build_run(tmp_path, records)
    _refused(run, stage_env, "graph-sideways")


def test_a_legacy_arm_alias_resolves_through_the_registry(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    qids = g_ids(1, 0, 0)
    rec = make_record("hybrid", qids[0]).model_copy(update={"graph_arm": "graph-off"})
    run = build_run(tmp_path, [rec])
    result = _stage(run)
    assert result.arms["hybrid"].judgeable == 1


def test_a_judge_that_is_the_generator_is_refused(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        judge_stage,
        "_get_engine_generation_model",
        lambda: "meta-llama/llama-3.3-70b-instruct",
    )
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "generation model")


def test_an_unreadable_generation_model_is_refused(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(judge_stage, "_get_engine_generation_model", lambda: "")
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "generation model")


def test_a_rehearsal_corpus_is_refused_without_the_rehearsal_flag(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    qids = [q.question_id for q in load_sample_questions(REHEARSAL)]
    run = build_run(
        tmp_path, standard_records(qids), corpus=REHEARSAL
    )
    _refused(run, stage_env, "heldout")


# --- retries and tripwires ----------------------------------------------------


def test_an_error_that_succeeds_on_re_attempt_leaves_a_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    fake = install_fake(monkeypatch, fail_at={1}, fail_times=1)
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    result = _stage(run)
    assert len(fake.calls) == 9  # 8 keys and one re-attempt
    assert result.calls == 9
    assert result.arms["dense-only"].re_attempted == 1
    assert sum(a.errors for a in result.arms.values()) == 0
    entries = JudgeCache(run / "judge_cache.json").entries
    assert len(entries) == 8
    assert all(e.verdict is not None and e.error is None for e in entries.values())


def test_two_failures_leave_an_error_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    fake = install_fake(monkeypatch, fail_at={1}, fail_times=2)
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    result = _stage(run)
    assert len(fake.calls) == 9
    assert result.arms["dense-only"].errors == 1
    assert result.arms["dense-only"].re_attempted == 1
    assert result.stop_reason is None
    entries = JudgeCache(run / "judge_cache.json").entries
    assert sum(1 for e in entries.values() if e.error is not None) == 1
    assert sum(1 for e in entries.values() if e.verdict is not None) == 7


def test_six_consecutive_errors_halt_after_the_fifth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    fake = install_fake(monkeypatch, fail_at=set(range(1, 7)), fail_times=2)
    run = build_run(tmp_path, standard_records(g_ids(2, 2, 2)))
    result = _stage(run)
    assert result.stop_reason is not None
    assert "consecutive" in result.stop_reason
    assert len(fake.calls) == 10  # five keys, each tried and re-attempted
    assert result.keys_attempted == 5
    assert sum(a.errors for a in result.arms.values()) == 5
    assert sum(a.not_attempted for a in result.arms.values()) == 24 - 5
    assert _stage_json(run)["stop_reason"] == result.stop_reason


def test_five_scattered_errors_do_not_halt_on_consecutiveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    install_fake(monkeypatch, fail_at={2, 4, 6, 8, 10}, fail_times=2)
    run = build_run(tmp_path, standard_records(g_ids(2, 2, 2)))
    result = _stage(run)
    # 5 of 12 keys is above the rate, but the rate is not checked below 50 keys
    assert result.stop_reason is None
    assert result.keys_attempted == 24


def test_four_errors_in_the_first_fifty_calls_trip_the_rate_at_fifty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    fake = install_fake(monkeypatch, fail_at={3, 9, 15, 20}, fail_times=2)
    run = build_run(tmp_path, standard_records(g_ids(7, 7, 6)))  # 80 keys
    result = _stage(run)
    assert result.stop_reason is not None
    assert "error rate" in result.stop_reason
    assert result.keys_attempted == 50  # 4 / 50 = 0.08 > 0.05, first checked at 50
    assert len(fake.calls) == 54  # the four failed keys were re-attempted
    assert sum(a.errors for a in result.arms.values()) == 4
    assert sum(a.not_attempted for a in result.arms.values()) == 30


def test_two_errors_in_sixty_calls_do_not_trip_the_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    install_fake(monkeypatch, fail_at={10, 40}, fail_times=2)
    run = build_run(tmp_path, standard_records(g_ids(7, 7, 6)))
    result = _stage(run)
    assert result.stop_reason is None
    assert result.keys_attempted == 80
    assert sum(a.errors for a in result.arms.values()) == 2


def test_an_error_rate_exactly_at_the_tripwire_does_not_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    # 3 errors in 60 keys is exactly 0.05, which does not exceed it; the plan's
    # "4 errors in 60" example is 0.067 and cannot be both under 0.05 and a count.
    install_fake(monkeypatch, fail_at={55, 58, 60}, fail_times=2)
    run = build_run(tmp_path, standard_records(g_ids(7, 7, 6)))
    result = _stage(run)
    assert result.stop_reason is None
    assert result.keys_attempted == 80


def test_the_in_loop_spend_check_stops_before_a_call_that_would_exceed_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    fake = install_fake(
        monkeypatch, usage=JudgeUsage(prompt_tokens=100_000, completion_tokens=0)
    )
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))  # 8 keys
    result = _stage(run, cap=8 * COST * 1.01)
    assert len(fake.calls) == 1  # one call costs 0.012, far above the cap
    assert result.stop_reason is not None
    assert "spend cap" in result.stop_reason
    assert result.spend_usd == pytest.approx(0.012)
    assert sum(a.not_attempted for a in result.arms.values()) == 7
    assert sum(a.judged_now for a in result.arms.values()) == 1
    assert _stage_json(run)["stop_reason"] == result.stop_reason


def test_a_cap_stop_leaves_the_stage_incomplete_for_a_later_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    install_fake(
        monkeypatch, usage=JudgeUsage(prompt_tokens=100_000, completion_tokens=0)
    )
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _stage(run, cap=8 * COST * 1.01)
    assert len(JudgeCache(run / "judge_cache.json").entries) == 1
    fake = install_fake(monkeypatch)
    result = _stage(run)
    assert len(fake.calls) == 7
    assert result.stop_reason is None
    assert len(JudgeCache(run / "judge_cache.json").entries) == 8


# --- the stage shows counts only ----------------------------------------------


def test_the_stage_computes_no_judged_statistic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage_env: FakeJudge,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("score_run must never be called by the judge stage")

    monkeypatch.setattr(score_mod, "score_run", boom)
    install_fake(
        monkeypatch,
        fail_at={2},
        error_text="validation failed: groundedness and faithfulness missing",
    )
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 1)))
    report = run / "report.json"
    report.write_text('{"sentinel": 1}\n', encoding="utf-8")

    _stage(run)

    out = capsys.readouterr()
    assert FORBIDDEN.search(out.out + out.err) is None
    text = (run / "judge-stage.json").read_text(encoding="utf-8")
    assert FORBIDDEN.search(text) is None
    assert report.read_text(encoding="utf-8") == '{"sentinel": 1}\n'


def test_the_judge_stage_module_never_imports_score_run() -> None:
    source = Path(judge_stage.__file__).read_text(encoding="utf-8")
    names = {
        n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)
    } | {
        a.name
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.ImportFrom | ast.Import)
        for a in n.names
    }
    assert "score_run" not in names


def test_the_api_key_is_never_written_or_printed(
    tmp_path: Path, stage_env: FakeJudge, capsys: pytest.CaptureFixture[str]
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _stage(run)
    captured = capsys.readouterr()
    assert API_KEY not in captured.out + captured.err
    for path in run.iterdir():
        if path.is_file():
            assert API_KEY not in path.read_text(encoding="utf-8")


def test_the_judge_command_prints_counts_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    install_fake(
        monkeypatch,
        fail_at={2},
        error_text="validation failed: groundedness and faithfulness missing",
    )
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 1)))
    result = CliRunner().invoke(app, ["judge", "--run", str(run), "--stage-cap", "1"])
    assert result.exit_code == 0, result.output
    assert FORBIDDEN.search(result.output) is None
    assert API_KEY not in result.output
    for arm in ARMS:
        assert arm in result.output
    assert (run / "judge-stage.json").is_file()
    assert not (run / "report.json").exists()


def test_the_judge_command_requires_a_stage_cap() -> None:
    result = CliRunner().invoke(app, ["judge", "--run", "nowhere"])
    assert result.exit_code == 2
    assert "--stage-cap" in result.output


@pytest.mark.parametrize("cap", ["nan", "0", "-1"])
def test_the_judge_command_rejects_an_invalid_cap(cap: str) -> None:
    result = CliRunner().invoke(app, ["judge", "--run", "nowhere", "--stage-cap", cap])
    assert result.exit_code == 2


def test_the_judge_command_exits_nonzero_on_a_refusal(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)), partial=True)
    result = CliRunner().invoke(app, ["judge", "--run", str(run), "--stage-cap", "1"])
    assert result.exit_code == 1
    assert stage_env.calls == []


def test_the_judge_command_exits_nonzero_when_the_stage_halts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage_env: FakeJudge
) -> None:
    install_fake(monkeypatch, fail_at=set(range(1, 7)), fail_times=2)
    run = build_run(tmp_path, standard_records(g_ids(2, 2, 2)))
    result = CliRunner().invoke(app, ["judge", "--run", str(run), "--stage-cap", "1"])
    assert result.exit_code == 1
    assert "consecutive" in result.output


# --- --rehearsal (D-106 c, D-108) ---------------------------------------------


def _rehearsal_ids() -> list[str]:
    return [q.question_id for q in load_sample_questions(REHEARSAL)]


def test_rehearsal_judges_the_rehearsal_journal_and_records_latency(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    qids = _rehearsal_ids()
    held_out = set(real_split().heldout_g_ids)
    assert len(qids) == 3 and not held_out & set(qids)
    run = build_run(tmp_path, standard_records(qids), corpus=REHEARSAL)

    result = _stage(run, rehearsal=True)

    assert result.mode == "rehearsal"
    assert len(stage_env.calls) == 12  # 3 questions x 4 arms, no G filter applied
    for arm in ARMS:
        assert result.arms[arm].judgeable == 3
    data = _stage_json(run)
    assert data["mode"] == "rehearsal"
    assert isinstance(data["per_call_latency_ms_p50"], float)
    assert isinstance(data["per_call_latency_ms_p95"], float)
    assert data["per_call_latency_ms_p50"] <= data["per_call_latency_ms_p95"]
    assert FORBIDDEN.search(json.dumps(data)) is None


def test_rehearsal_with_no_judgeable_record_refuses_before_a_call(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    qids = _rehearsal_ids()
    records = [
        make_record(arm, qid, no_evidence=True, corpus=REHEARSAL)
        for qid in qids
        for arm in ARMS
    ]
    run = build_run(tmp_path, records, corpus=REHEARSAL)
    _refused(run, stage_env, "no judgeable rehearsal record", rehearsal=True)


def test_rehearsal_with_only_uncited_records_refuses_before_a_call(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    qids = _rehearsal_ids()
    records = [
        make_record(arm, qid, uncited=True, corpus=REHEARSAL)
        for qid in qids
        for arm in ARMS
    ]
    run = build_run(tmp_path, records, corpus=REHEARSAL)
    _refused(run, stage_env, "no judgeable rehearsal record", rehearsal=True)


def test_rehearsal_refuses_a_non_rehearsal_corpus(
    tmp_path: Path, stage_env: FakeJudge
) -> None:
    run = build_run(tmp_path, standard_records(g_ids(1, 1, 0)))
    _refused(run, stage_env, "rehearsal", rehearsal=True)


@pytest.mark.parametrize("which", ["dev_ids", "heldout_g_ids", "heldout_null_ids"])
def test_rehearsal_refuses_a_journal_record_in_the_split(
    tmp_path: Path, stage_env: FakeJudge, which: str
) -> None:
    qids = _rehearsal_ids()
    stray = getattr(real_split(), which)[0]
    records = standard_records(qids, **{}) + [
        make_record("hybrid", stray, corpus=REHEARSAL)
    ]
    run = build_run(tmp_path, records, corpus=REHEARSAL)
    _refused(run, stage_env, "split", rehearsal=True)


def test_rehearsal_refuses_a_corpus_question_in_the_split(
    tmp_path: Path, stage_env: FakeJudge, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions = load_sample_questions(REHEARSAL)
    dev_id = real_split().dev_ids[0]
    questions.append(questions[0].model_copy(update={"question_id": dev_id}))
    monkeypatch.setattr(judge_stage, "load_sample_questions", lambda corpus: questions)
    run = build_run(
        tmp_path, standard_records(_rehearsal_ids()), corpus=REHEARSAL
    )
    _refused(run, stage_env, "split", rehearsal=True)
