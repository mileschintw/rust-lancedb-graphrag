"""Tests for the dev-read analysis, the rerank timeout derivation and the ledger
linter (plan 06.3.6-10, Task 2)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from levers_fixture import (
    ARMS,
    Questions,
    Spec,
    make_questions,
    make_record,
    write_corpus,
)
from test_preregistration import T0, _commit, _git, _write

from lancet_eval import dev_reads
from lancet_eval.client import RerankMeta
from lancet_eval.dev_reads import (
    DEV_PROTOCOL_RULE_ID,
    DevReadsError,
    analyse,
    derive_from_observations,
    derive_rerank_timeout,
    ledger_add,
    lint_ledger,
    read_ledger,
    render_ledger,
)
from lancet_eval.journal import Journal, RunRecord

# ---- the censoring-aware rerank timeout ----------------------------------------------


def test_no_censoring_gives_an_exact_p95() -> None:
    data = [float(v) for v in range(1, 101)]
    rec = derive_from_observations(data, [], retrieve_timeout_ms=2500)
    assert rec["label"] == "exact"
    assert rec["n"] == 100
    assert rec["k"] == 0
    assert rec["p95_ms"] == 95.0
    assert rec["t_ms"] == math.ceil(1.5 * 95.0)
    assert rec["ci_high_unbounded"] is False


def test_five_censored_at_or_above_the_95th_order_statistic_is_exact() -> None:
    uncensored = [float(v) for v in range(100, 195)]  # 95 values, max 194
    rec = derive_from_observations(uncensored, [1706.0] * 5, retrieve_timeout_ms=2500)
    assert rec["label"] == "censored_above_p95_rank(5)"
    assert rec["p95_ms"] == 194.0
    assert rec["is_lower_bound"] is False
    assert rec["ci_high_ms"] is None
    assert rec["ci_high_unbounded"] is True
    assert rec["decision"] == "nests"


def test_six_censored_is_a_lower_bound() -> None:
    uncensored = [float(v) for v in range(100, 194)]  # 94 values
    rec = derive_from_observations(uncensored, [1706.0] * 6, retrieve_timeout_ms=2500)
    assert rec["label"] == "lower_bound"
    assert rec["is_lower_bound"] is True
    assert rec["p95_ms"] == 1706.0


def test_five_censored_but_one_below_the_95th_order_statistic_is_a_lower_bound() -> (
    None
):
    uncensored = [float(v) for v in range(100, 195)]
    rec = derive_from_observations(
        uncensored, [1706.0] * 4 + [120.0], retrieve_timeout_ms=2500
    )
    assert rec["k"] == 5
    assert rec["label"] == "lower_bound"


def test_the_rule_t_is_ceil_1_5_p95_and_nests_at_1137_not_1138() -> None:
    fits = derive_from_observations(
        [float(v) for v in range(1, 95)] + [1137.0] * 6, [], retrieve_timeout_ms=2500
    )
    assert fits["p95_ms"] == 1137.0
    assert fits["t_ms"] == 1706
    assert fits["required_retrieve_ms"] == 294 + 1706 + 500 == 2500
    assert fits["nests"] is True
    assert fits["decision"] == "nests"
    over = derive_from_observations(
        [float(v) for v in range(1, 95)] + [1138.0] * 6, [], retrieve_timeout_ms=2500
    )
    assert over["t_ms"] == 1707
    assert over["required_retrieve_ms"] == 2501
    assert over["nests"] is False
    assert over["decision"] == "does_not_fit"


def test_a_lower_bound_that_already_does_not_fit_is_decided_otherwise_undecided() -> (
    None
):
    low = [float(v) for v in range(100, 194)]
    undecided = derive_from_observations(low, [800.0] * 6, retrieve_timeout_ms=2500)
    assert undecided["label"] == "lower_bound"
    assert undecided["decision"] == "undecided_lower_bound"
    assert undecided["nests"] is None
    decided = derive_from_observations(low, [1706.0] * 6, retrieve_timeout_ms=2500)
    assert decided["decision"] == "does_not_fit"
    assert decided["nests"] is False


def test_too_few_observations_is_unavailable_not_a_number() -> None:
    rec = derive_from_observations([5.0], [], retrieve_timeout_ms=2500)
    assert rec["decision"] == "unavailable"
    assert rec["t_ms"] is None
    assert json.dumps(rec, allow_nan=False)


def _rerank_record(qid: str, outcome: str, latency: int) -> RunRecord:
    qs = Questions(g=[(qid, "comparison_query", "Yes")], nulls=[])
    rec = make_record("hybrid+rerank", qid, Spec(), qs)
    assert rec.workflow_meta is not None
    meta = rec.workflow_meta.model_copy(
        update={
            "rerank": RerankMeta(
                latency_ms=latency,
                cost_credits=0.0003,
                cost_reported=True,
                outcome=outcome,
            )
        }
    )
    return rec.model_copy(update={"workflow_meta": meta})


def test_derive_from_a_journal_excludes_and_counts_non_latency_degrades(
    tmp_path: Path,
) -> None:
    journal = Journal(tmp_path / "journal.jsonl")
    journal.write_header(corpus="levers_dev", partial=False)
    n = 0
    for i in range(90):
        journal.append(_rerank_record(f"d{n:03d}", "completed", 100 + i))
        n += 1
    for _ in range(2):
        journal.append(_rerank_record(f"d{n:03d}", "degraded_timeout", 1706))
        n += 1
    for outcome in ("degraded_status", "degraded_malformed", "degraded_transport"):
        journal.append(_rerank_record(f"d{n:03d}", outcome, 40))
        n += 1
    rec = derive_rerank_timeout(tmp_path, retrieve_timeout_ms=2500)
    assert rec["n"] == 92
    assert rec["k"] == 2
    assert rec["excluded"] == {
        "status": 1,
        "malformed": 1,
        "transport": 1,
        "unspecified": 0,
        "no_telemetry": 0,
    }
    assert rec["label"] == "censored_above_p95_rank(2)"
    assert rec["arm"] == "hybrid+rerank"
    assert rec["required_retrieve_ms"] == math.ceil(294 + rec["t_ms"] + 500)


# ---- the dev-session analysis --------------------------------------------------------

DEV = "levers_dev"
HYB = "hybrid"
RRK = "hybrid+rerank"
META = "hybrid+metadata"
FMT = "hybrid+answer-format"
DEV_ARMS = [a for a in (HYB, RRK, META, FMT) if a in ARMS]


def _dev_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qs: Questions, spec_fn):  # type: ignore[no-untyped-def]
    root = tmp_path / "repo"
    gold = write_corpus(root, qs, DEV_ARMS, token=None, name=DEV, role="dev")
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    run = tmp_path / "run"
    journal = Journal(run / "journal.jsonl")
    journal.write_header(corpus=DEV, partial=False)
    for qid in [*qs.g_ids, *qs.nulls]:
        for arm in DEV_ARMS:
            journal.append(make_record(arm, qid, spec_fn(arm, qid), qs, corpus=DEV))
    return run, gold


def test_analyse_reports_paired_deltas_without_a_p_value(tmp_path, monkeypatch) -> None:
    qs = make_questions(10, 5)

    def spec(a: str, q: str) -> Spec:
        if a == RRK and q in {"lv-g000", "lv-g001"}:
            return Spec(kind="wrong")
        if a == META and q in {"lv-g002"}:
            return Spec(kind="abstain")
        if a == FMT and q.startswith("lv-n") and int(q[4:]) < 2:
            return Spec(kind="answer_yes")
        if a == RRK and q == "lv-g005":
            return Spec(degraded=True, retries=1)
        return Spec()

    run, gold = _dev_setup(tmp_path, monkeypatch, qs, spec)
    out = analyse(run, "s1", gold_chunks_path=gold)
    assert out["session"] == "s1"
    assert out["reference_arm"] == "hybrid"
    arms = {a["arm"]: a for a in out["arms"]}
    assert set(arms) == set(DEV_ARMS) - {"hybrid"}
    # a deterministic order: registry order, not set-iteration order
    from lancet_eval.arms import ARM_REGISTRY

    assert [a["arm"] for a in out["arms"]] == [
        a for a in ARM_REGISTRY if a in set(DEV_ARMS) - {"hybrid"}
    ]
    rr = arms[RRK]
    # lv-g005 is a degrade (off-arm): 9 pairs; lv-g000 and lv-g001 are lost
    assert rr["n_pairs"] == 9
    assert rr["n_neg"] == 2
    assert rr["delta"] == pytest.approx(-2 / 9)
    assert rr["ci_label"] == "unadjusted, estimation only"
    assert "p_value" not in rr and "raw_p" not in rr
    assert rr["no_p_value"] is True
    assert rr["hits_at_4"]["n"] == 9
    assert rr["rerank_outcomes"] == {"completed": 14, "degraded_timeout": 1}
    assert rr["query_embedding_retries"] == 1
    assert arms[META]["hits_at_4"] is None
    assert arms[META]["delta"] == pytest.approx(-1 / 10)
    # two of the five dev nulls answered by the format arm: b = 2 (hybrid abstains)
    assert arms[FMT]["null_pairs"] == {"n": 5, "b": 2, "c": 0}
    shares = arms[FMT]["comparison_shares"]
    assert sum(shares["arm"].values()) == pytest.approx(1.0)
    assert arms[META]["mean_prompt_tokens"] == pytest.approx(500.0)
    assert out["spend_usd"] > 0
    assert json.dumps(out, allow_nan=False)


def test_analyse_refuses_a_journal_holding_a_non_dev_question(
    tmp_path, monkeypatch
) -> None:
    qs = make_questions(4, 2)
    run, gold = _dev_setup(tmp_path, monkeypatch, qs, lambda a, q: Spec())
    stray = make_record(
        "hybrid",
        "lv-h1",
        Spec(),
        Questions(g=[("lv-h1", "comparison_query", "Yes")]),
        corpus=DEV,
    )
    Journal(run / "journal.jsonl").append(stray)
    with pytest.raises(DevReadsError, match="dev IDs only"):
        analyse(run, "s1", gold_chunks_path=gold)


# ---- the ledger ----------------------------------------------------------------------


def test_ledger_add_stores_the_payload_verbatim_under_a_top_level_kind(
    tmp_path: Path,
) -> None:
    path = tmp_path / "diag" / "dev-reads.jsonl"
    payload = {
        "rule_id": DEV_PROTOCOL_RULE_ID,
        "cap_usd": 2.0,
        "triggers": {"rerank": "lower bound only", "metadata": ["a", "b"]},
        "unicode": "café",
    }
    entry = ledger_add(path, "rule", payload)
    assert entry["kind"] == "rule"
    stored = read_ledger(path)
    assert len(stored) == 1
    for key, value in payload.items():
        assert stored[0][key] == value
    assert stored[0]["kind"] == "rule"
    assert isinstance(stored[0]["entry_id"], str)
    again = ledger_add(path, "read", {"lever": "rerank", "read": 1, "run_dir": "r"})
    assert again["entry_id"] != stored[0]["entry_id"]
    assert len(read_ledger(path)) == 2


def test_ledger_add_refuses_an_unknown_kind_and_a_conflicting_kind_key(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dev-reads.jsonl"
    with pytest.raises(DevReadsError):
        ledger_add(path, "note", {})
    with pytest.raises(DevReadsError):
        ledger_add(path, "rule", {"kind": "read"})
    assert not path.exists()


def test_render_ledger_writes_markdown_beside_the_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "dev-reads.jsonl"
    ledger_add(path, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID, "cap_usd": 2.0})
    ledger_add(path, "read", {"lever": "rerank", "read": 1, "run_dir": "eval/runs/x"})
    out = render_ledger(path)
    assert out == tmp_path / "dev-reads.md"
    text = out.read_text(encoding="utf-8")
    assert DEV_PROTOCOL_RULE_ID in text
    assert "rerank" in text


# ---- lint-ledger over a throwaway repository -----------------------------------------

LEDGER_REL = "diag/dev-reads.jsonl"
SPLIT_REL = "eval/corpora/multihop_rag/heldout_split.json"


@pytest.fixture
def lrepo(tmp_path: Path) -> Path:
    root = tmp_path / "throwaway"
    root.mkdir()
    (tmp_path / "empty.gitconfig").write_text("", encoding="utf-8")
    _git(root, "init", "-q")
    _write(root, "README.md", b"x\n")
    _commit(root, "init", T0)
    split = {
        "derivation_rule": "t",
        "populations_sha256": "0" * 64,
        "diag_selection_sha256": "0" * 64,
        "questions_sample_sha256": "0" * 64,
        "dev_source": "dev.json",
        "order_seed": 42,
        "dev_ids": ["dv1", "dv2", "dv3"],
        "heldout_g_ids": ["hg1", "hg2"],
        "heldout_null_ids": ["hn1"],
    }
    _write(root, SPLIT_REL, json.dumps(split).encode())
    _commit(root, "split", T0 + 1)
    return root


def _journal(
    repo: Path, rel: str, created_at: float, qids: list[str], corpus: str = "levers_dev"
) -> None:
    lines = [
        json.dumps({
            "type": "header",
            "corpus": corpus,
            "partial": False,
            "created_at": created_at,
        })
    ]
    for qid in qids:
        rec = RunRecord(
            corpus=corpus, question_id=qid, graph_arm="hybrid", outcome="success"
        )
        lines.append(rec.model_dump_json())
    _write(repo, rel, ("\n".join(lines) + "\n").encode())


def _add(repo: Path, kind: str, payload: dict, when: int) -> dict:  # type: ignore[type-arg]
    entry = ledger_add(repo / LEDGER_REL, kind, payload)
    _commit(repo, f"ledger {kind}", when)
    return entry


def _lint(repo: Path, **kw):  # type: ignore[no-untyped-def]
    return lint_ledger(repo / LEDGER_REL, repo=repo, split_path=repo / SPLIT_REL, **kw)


def _well_formed(repo: Path) -> None:
    _add(repo, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID, "cap_usd": 2.0}, T0 + 10)
    _journal(repo, "eval/runs/s1/journal.jsonl", T0 + 100, ["dv1", "dv2"])
    _commit(repo, "session 1", T0 + 150)
    _add(
        repo,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
        T0 + 200,
    )
    _add(
        repo,
        "read2_reason",
        {"lever": "rerank", "reason": "lower bound"},
        T0 + 300,
    )
    _journal(repo, "eval/runs/s2/journal.jsonl", T0 + 400, ["dv1", "dv3"])
    _commit(repo, "session 2", T0 + 450)
    _add(
        repo,
        "read",
        {"lever": "rerank", "read": 2, "run_dir": "eval/runs/s2"},
        T0 + 500,
    )


def test_a_well_formed_ledger_passes(lrepo: Path) -> None:
    _well_formed(lrepo)
    assert _lint(lrepo) == []


def test_an_empty_or_rule_only_ledger_passes_and_a_missing_one_does_not(
    lrepo: Path,
) -> None:
    missing = _lint(lrepo)
    assert any("cannot read" in p for p in missing)
    _add(lrepo, "rule", {"rule_id": "er-theta1", "theta": 0.8}, T0 + 10)
    assert _lint(lrepo) == []
    _add(lrepo, "derivation", {"note": "x"}, T0 + 20)
    assert _lint(lrepo) == []


def test_a_third_read_of_a_lever_fails(lrepo: Path) -> None:
    _well_formed(lrepo)
    _journal(lrepo, "eval/runs/s3/journal.jsonl", T0 + 600, ["dv1"])
    _commit(lrepo, "session 3", T0 + 650)
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 3, "run_dir": "eval/runs/s3"},
        T0 + 700,
    )
    problems = _lint(lrepo)
    assert any("at most 2 reads" in p for p in problems)


def test_a_read_two_whose_reason_was_committed_late_fails(lrepo: Path) -> None:
    _add(lrepo, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID}, T0 + 10)
    _journal(lrepo, "eval/runs/s1/journal.jsonl", T0 + 100, ["dv1"])
    _journal(lrepo, "eval/runs/s2/journal.jsonl", T0 + 400, ["dv1"])
    _commit(lrepo, "sessions", T0 + 450)
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
        T0 + 500,
    )
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 2, "run_dir": "eval/runs/s2"},
        T0 + 510,
    )
    # the reason is committed AFTER the read-2 journal was created
    _add(lrepo, "read2_reason", {"lever": "rerank", "reason": "late"}, T0 + 520)
    problems = _lint(lrepo)
    assert any("reason" in p and "rerank" in p for p in problems)


def test_a_read_two_with_no_reason_entry_fails(lrepo: Path) -> None:
    _add(lrepo, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID}, T0 + 10)
    _journal(lrepo, "eval/runs/s1/journal.jsonl", T0 + 100, ["dv1"])
    _journal(lrepo, "eval/runs/s2/journal.jsonl", T0 + 400, ["dv1"])
    _commit(lrepo, "sessions", T0 + 450)
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
        T0 + 500,
    )
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 2, "run_dir": "eval/runs/s2"},
        T0 + 510,
    )
    assert any("read2_reason" in p for p in _lint(lrepo))


def test_a_dev_journal_holding_a_held_out_id_fails(lrepo: Path) -> None:
    _add(lrepo, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID}, T0 + 10)
    _journal(lrepo, "eval/runs/s1/journal.jsonl", T0 + 100, ["dv1", "hg1"])
    _commit(lrepo, "session 1", T0 + 150)
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
        T0 + 200,
    )
    problems = _lint(lrepo)
    assert any("dev IDs only" in p and "hg1" in p for p in problems)


def test_a_read_one_before_the_rules_entry_commit_fails(lrepo: Path) -> None:
    _journal(lrepo, "eval/runs/s1/journal.jsonl", T0 + 50, ["dv1"])
    _commit(lrepo, "session 1", T0 + 60)
    _add(lrepo, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID}, T0 + 100)
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
        T0 + 200,
    )
    problems = _lint(lrepo)
    assert any("rules entry" in p for p in problems)


def test_a_read_with_no_dev_protocol_rule_fails_but_er_theta1_does_not_count(
    lrepo: Path,
) -> None:
    _add(lrepo, "rule", {"rule_id": "er-theta1"}, T0 + 10)
    _journal(lrepo, "eval/runs/s1/journal.jsonl", T0 + 100, ["dv1"])
    _commit(lrepo, "session 1", T0 + 150)
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
        T0 + 200,
    )
    assert any(DEV_PROTOCOL_RULE_ID in p for p in _lint(lrepo))


def test_an_uncommitted_rule_entry_fails_a_read_that_needs_it(lrepo: Path) -> None:
    _journal(lrepo, "eval/runs/s1/journal.jsonl", T0 + 100, ["dv1"])
    _commit(lrepo, "session 1", T0 + 150)
    ledger_add(lrepo / LEDGER_REL, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID})
    ledger_add(
        lrepo / LEDGER_REL,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
    )
    assert any("not committed" in p for p in _lint(lrepo))


def test_an_uncommitted_read_entry_alone_is_fine(lrepo: Path) -> None:
    _add(lrepo, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID}, T0 + 10)
    _journal(lrepo, "eval/runs/s1/journal.jsonl", T0 + 100, ["dv1"])
    _commit(lrepo, "session 1", T0 + 150)
    ledger_add(
        lrepo / LEDGER_REL,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
    )
    assert _lint(lrepo) == []


def test_a_held_out_side_journal_created_before_the_freeze_commit_fails(
    lrepo: Path,
) -> None:
    _well_formed(lrepo)
    _journal(
        lrepo,
        "eval/runs/rehearsal/journal.jsonl",
        T0 + 550,
        ["hg1"],
        "levers_rehearsal",
    )
    _commit(lrepo, "rehearsal journal", T0 + 560)
    held = [lrepo / "eval/runs/rehearsal/journal.jsonl"]
    problems = _lint(lrepo, heldout_journals=held)
    assert any("freeze" in p for p in problems)
    _add(lrepo, "freeze", {"note": "freeze"}, T0 + 600)
    assert any("before the freeze" in p for p in _lint(lrepo, heldout_journals=held))
    # a journal created after the freeze commit is fine
    _journal(
        lrepo,
        "eval/runs/drive/journal.jsonl",
        T0 + 700,
        ["hg1", "hn1"],
        "levers_heldout",
    )
    _commit(lrepo, "drive journal", T0 + 710)
    ok = [lrepo / "eval/runs/drive/journal.jsonl"]
    assert _lint(lrepo, heldout_journals=ok) == []


def test_a_dev_read_listed_after_the_freeze_fails(lrepo: Path) -> None:
    _well_formed(lrepo)
    _add(lrepo, "freeze", {"note": "freeze"}, T0 + 600)
    _journal(lrepo, "eval/runs/s9/journal.jsonl", T0 + 700, ["dv1"])
    _commit(lrepo, "late session", T0 + 710)
    _add(
        lrepo,
        "read",
        {"lever": "metadata", "read": 1, "run_dir": "eval/runs/s9"},
        T0 + 720,
    )
    assert any("after the freeze" in p for p in _lint(lrepo))


def test_a_malformed_ledger_line_is_a_problem(lrepo: Path) -> None:
    _write(lrepo, LEDGER_REL, b'{"kind": "rule"\n')
    _commit(lrepo, "bad ledger", T0 + 10)
    assert any("not valid JSON" in p for p in _lint(lrepo))


def test_the_cli_entry_exits_non_zero_on_a_violation(lrepo: Path) -> None:
    _add(lrepo, "rule", {"rule_id": DEV_PROTOCOL_RULE_ID}, T0 + 10)
    _journal(lrepo, "eval/runs/s1/journal.jsonl", T0 + 100, ["dv1", "hg1"])
    _commit(lrepo, "session 1", T0 + 150)
    _add(
        lrepo,
        "read",
        {"lever": "rerank", "read": 1, "run_dir": "eval/runs/s1"},
        T0 + 200,
    )
    args = [
        "lint-ledger",
        "--ledger",
        str(lrepo / LEDGER_REL),
        "--repo",
        str(lrepo),
        "--split",
        str(lrepo / SPLIT_REL),
    ]
    assert dev_reads.main(args) == 1


def test_the_module_names_the_three_command_words() -> None:
    import inspect

    source = inspect.getsource(dev_reads)
    for word in ("censored_above_p95_rank", "lint-ledger", "derive-rerank-timeout"):
        assert word in source


def test_the_dev_reads_command_mirrors_the_module(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from lancet_eval.cli import app

    path = tmp_path / "dev-reads.jsonl"
    add = CliRunner().invoke(
        app,
        [
            "dev-reads",
            "ledger-add",
            "--kind",
            "rule",
            "--json",
            json.dumps({"rule_id": DEV_PROTOCOL_RULE_ID}),
            "--ledger",
            str(path),
        ],
    )
    assert add.exit_code == 0, add.output
    assert read_ledger(path)[0]["rule_id"] == DEV_PROTOCOL_RULE_ID
    missing = CliRunner().invoke(
        app, ["dev-reads", "lint-ledger", "--ledger", str(tmp_path / "nope.jsonl")]
    )
    assert missing.exit_code == 1
