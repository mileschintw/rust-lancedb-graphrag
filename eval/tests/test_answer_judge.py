"""D-276 dual answer judge, the secondary beside the normalised `answer_usable` (#124).

Two judges, gpt-4o-mini and Sonnet 5.5, each see only the question, the gold answer
and the extracted final line, and say whether the line is equivalent to the gold.
The run gets per-arm judged rates for both judges and a list of every disagreement
(judge against judge, judge against the primary). The transport is stubbed: no test
makes a network call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import levers_fixture as fx
import pytest
from typer.testing import CliRunner

from lancet_eval import answer_judge as aj
from lancet_eval.cli import app

ARMS = ("hybrid", "hybrid+rerank")
WRONG_QID = "lv-g001"  # gold "No"; hybrid+rerank answers "Wrong guess" there


class StubTransport:
    """Answers each judge request; records every payload it was sent."""

    def __init__(self, sonnet_says_wrong_is_fine: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.sonnet_lenient = sonnet_says_wrong_is_fine

    def __call__(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        self.calls.append(payload)
        user = payload["messages"][-1]["content"]
        line = user.split("Answer to judge:", 1)[1].strip()
        gold = user.split("Gold answer:", 1)[1].split("\n", 1)[0].strip()
        equivalent = line.lower() == gold.lower()
        if payload["model"] == aj.SONNET.slug and self.sonnet_lenient:
            equivalent = True
        content = json.dumps({"equivalent": equivalent, "rationale": "stub"})
        reply: dict[str, Any] = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 20},
        }
        if payload["model"] == aj.SONNET.slug:
            # What OpenRouter reports for a BYOK request routed to Anthropic.
            reply["provider"] = "Anthropic"
            reply["usage"]["is_byok"] = True
        return reply


def _spec(arm: str, qid: str) -> fx.Spec:
    return (
        fx.Spec(kind="wrong")
        if (arm, qid) == ("hybrid+rerank", WRONG_QID)
        else fx.Spec()
    )


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    qs = fx.make_questions(6, 2)
    root = tmp_path / "repo"
    fx.write_corpus(root, qs, ARMS, role="dev")
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    fx.write_journal(run_dir, qs, _spec, ARMS)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    return run_dir


def test_each_judge_sees_only_the_question_the_gold_and_the_line(run: Path) -> None:
    stub = StubTransport()
    aj.judge_answers(run, transport=stub)
    assert stub.calls
    for payload in stub.calls:
        text = json.dumps(payload["messages"])
        assert "Answer to judge:" in text and "Gold answer:" in text
        for arm in ARMS:
            assert arm not in text
        assert "Based on the evidence" not in text  # the extracted line, not the prose
    models = {p["model"] for p in stub.calls}
    assert models == {aj.GPT_4O_MINI.slug, aj.SONNET.slug}
    sonnet = next(p for p in stub.calls if p["model"] == aj.SONNET.slug)
    assert sonnet["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}


def test_the_judge_reads_the_line_as_written(run: Path) -> None:
    """The line as written: D-70's normalisation would drop "." and "," from numbers."""
    answer = "Reasoning." + fx.NL + "**Answer:** $3.5 billion [1]"
    assert aj.final_line(answer) == "$3.5 billion"
    assert aj.final_line("no answer line") is None
    stub = StubTransport()
    aj.judge_answers(run, transport=stub)
    assert any("Answer to judge: Paris" in json.dumps(c) for c in stub.calls)


def test_one_call_per_judge_and_distinct_prompt_and_none_on_a_rerun(run: Path) -> None:
    stub = StubTransport()
    aj.judge_answers(run, transport=stub)
    # 6 G questions; the two arms give the same line except on WRONG_QID: 7 prompts.
    assert len(stub.calls) == 2 * 7
    again = StubTransport()
    aj.judge_answers(run, transport=again)
    assert again.calls == []


def test_the_report_holds_rates_and_every_disagreement(run: Path) -> None:
    aj.judge_answers(run, transport=StubTransport())
    report = json.loads((run / aj.REPORT_FILE).read_text(encoding="utf-8"))

    rates = {(r["judge"], r["arm"]): r for r in report["rates"]}
    assert rates[("primary", "hybrid")]["n_equivalent"] == 6
    assert rates[("primary", "hybrid+rerank")]["n_equivalent"] == 5
    assert rates[("gpt-4o-mini", "hybrid+rerank")]["n_equivalent"] == 5
    assert rates[("sonnet-5.5", "hybrid+rerank")]["n_equivalent"] == 6
    assert rates[("sonnet-5.5", "hybrid+rerank")]["rate"] == pytest.approx(1.0)

    (row,) = report["disagreements"]
    assert (row["question_id"], row["arm"]) == (WRONG_QID, "hybrid+rerank")
    assert row["final_line"] == "Wrong guess"  # as written, not normalised
    assert row["verdicts"] == {
        "primary": False,
        "gpt-4o-mini": False,
        "sonnet-5.5": True,
    }
    assert report["rule"].startswith("D-276")


def test_the_cost_estimate_is_printed_before_any_call(run: Path) -> None:
    events: list[str] = []
    stub = StubTransport()

    def transport(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        events.append("call")
        return stub(payload, api_key)

    aj.judge_answers(run, transport=transport, echo=lambda line: events.append(line))
    first_call = events.index("call")
    estimates = [e for e in events[:first_call] if "Cost estimate (D-258" in e]
    assert len(estimates) == 1
    assert "gpt-4o-mini" in estimates[0] and "sonnet-5.5" in estimates[0]


def test_estimate_only_calls_nothing_and_writes_nothing(run: Path) -> None:
    stub = StubTransport()
    lines: list[str] = []
    aj.judge_answers(run, transport=stub, estimate_only=True, echo=lines.append)
    assert stub.calls == []
    assert not (run / aj.REPORT_FILE).exists()
    assert any("Cost estimate (D-258" in line for line in lines)


def test_a_record_without_a_final_line_is_not_equivalent_and_not_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = fx.make_questions(3, 0)
    root = tmp_path / "repo"
    fx.write_corpus(root, qs, ARMS, role="dev")
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    fx.write_journal(
        run_dir,
        qs,
        lambda arm, qid: fx.Spec(kind="noline" if arm == "hybrid" else "ok"),
        ARMS,
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    stub = StubTransport()
    aj.judge_answers(run_dir, transport=stub)
    report = json.loads((run_dir / aj.REPORT_FILE).read_text(encoding="utf-8"))
    rates = {(r["judge"], r["arm"]): r for r in report["rates"]}
    assert rates[("gpt-4o-mini", "hybrid")]["n_equivalent"] == 0
    assert rates[("gpt-4o-mini", "hybrid")]["n_no_final_line"] == 3
    assert len(stub.calls) == 2 * 3  # only hybrid+rerank's lines


def test_null_token_counts_do_not_stop_the_run(run: Path) -> None:
    def no_usage(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        reply = StubTransport()(payload, api_key)
        reply["usage"].update(prompt_tokens=None, completion_tokens=None)
        return reply

    report = aj.judge_answers(run, transport=no_usage)
    assert report is not None
    assert report["spend_this_invocation"]["gpt-4o-mini"]["prompt_tokens"] == 0


def test_a_bad_reply_is_an_error_kept_out_of_the_cache(run: Path) -> None:
    def broken(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        reply = StubTransport()(payload, api_key)
        reply["choices"] = [{"message": {"content": "not json"}}]
        return reply

    aj.judge_answers(run, transport=broken)
    report = json.loads((run / aj.REPORT_FILE).read_text(encoding="utf-8"))
    rates = {(r["judge"], r["arm"]): r for r in report["rates"]}
    assert rates[("gpt-4o-mini", "hybrid")]["n_error"] == 6
    assert rates[("gpt-4o-mini", "hybrid")]["rate"] is None  # nothing was judged
    stub = StubTransport()
    aj.judge_answers(run, transport=stub)
    assert len(stub.calls) == 2 * 7  # errors were not cached, so they are asked again


def test_a_missing_api_key_refuses_after_the_estimate(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY")
    lines: list[str] = []
    with pytest.raises(aj.AnswerJudgeError, match="OPENROUTER_API_KEY"):
        aj.judge_answers(run, transport=StubTransport(), echo=lines.append)
    assert any("Cost estimate (D-258" in line for line in lines)


def test_the_cli_runs_the_judges(run: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aj, "openrouter_transport", StubTransport())
    result = CliRunner().invoke(app, ["judge-answers", "--run", str(run)])
    assert result.exit_code == 0, result.output
    assert "Cost estimate (D-258" in result.output
    assert (run / aj.REPORT_FILE).is_file()
    estimate = CliRunner().invoke(
        app, ["judge-answers", "--run", str(run), "--estimate-only"]
    )
    assert estimate.exit_code == 0, estimate.output


def test_each_replicate_of_a_question_and_arm_is_judged(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lane 123 adds `RunRecord.replicate`: records key by (qid, arm, replicate)."""
    from types import SimpleNamespace

    from lancet_eval.journal import load_records

    records = load_records(run / "journal.jsonl")
    hybrid = [r for r in records if r.graph_arm == "hybrid"]
    second = [
        SimpleNamespace(**{**r.model_dump(), "replicate": 2, "answer": "Answer: Lyon"})
        for r in hybrid
    ]
    first = [SimpleNamespace(**{**r.model_dump(), "replicate": 1}) for r in hybrid]
    monkeypatch.setattr(aj, "load_records", lambda path: [*first, *second])
    stub = StubTransport()  # Sonnet calls every line equivalent: replicate 2 disagrees
    aj.judge_answers(run, transport=stub)
    report = json.loads((run / aj.REPORT_FILE).read_text(encoding="utf-8"))
    rates = {(r["judge"], r["arm"]): r for r in report["rates"]}
    assert rates[("primary", "hybrid")]["n"] == 12  # 6 G questions x 2 replicates
    assert rates[("primary", "hybrid")]["n_equivalent"] == 6
    assert rates[("gpt-4o-mini", "hybrid")]["n_equivalent"] == 6
    assert any("Answer to judge: Lyon" in json.dumps(c) for c in stub.calls)
    assert {
        d["replicate"] for d in report["disagreements"] if d["arm"] == "hybrid"
    } == {2}


@pytest.mark.parametrize(
    ("provider", "is_byok"),
    [("Anthropic", False), ("Anthropic", None), ("Amazon Bedrock", True)],
)
def test_the_sonnet_judge_stops_off_byok_and_caches_nothing_of_it(
    run: Path, provider: str, is_byok: bool | None
) -> None:
    """B2 (#133): a Sonnet verdict billed off the owner's key, or routed off
    Anthropic, stops the run at once and is never cached."""
    stub = StubTransport()

    def off_byok(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        reply = stub(payload, api_key)
        if payload["model"] == aj.SONNET.slug:
            reply["provider"] = provider
            reply["usage"]["is_byok"] = is_byok
        return reply

    with pytest.raises(aj.AnswerJudgeError, match="BYOK"):
        aj.judge_answers(run, transport=off_byok)
    sonnet = [c for c in stub.calls if c["model"] == aj.SONNET.slug]
    assert len(sonnet) == 1
    cache_path = run / aj.CACHE_FILE
    cache = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.is_file()
        else {}
    )
    assert all(v["judge"] != aj.SONNET.name for v in cache.values())
