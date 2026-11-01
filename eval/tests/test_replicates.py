"""D-274: K replicates per question and arm in an S2 run (#123).

Every arm answers each question K times. A record is one unit per (question, arm,
replicate); a journal written before D-274 has no `replicate` field and reads as
replicate 1. `batch submit` sends replicates 1 to K of a reader arm and 2 to K of the
carried deepseek arm, whose request is the `pack` body unrewritten with the D-271
pin. `compare-levers` scores a question by its replicate mean and tests it with the
exact sign-flip permutation, with a paired t-test beside it.

The S2 run is the seam S-F fixture (`replay_fixture`), driven through `batch` with a
fake endpoint and a fake bin; nothing is sent anywhere.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from fractions import Fraction
from math import comb
from pathlib import Path
from typing import Any

import levers_fixture as fx
import pytest
import replay_fixture as rf
from test_batch import FakeBin, openrouter_row

from lancet_eval import batch, provenance, thresholds
from lancet_eval.batch_client import (
    BatchRequest,
    BatchResult,
    _openrouter_result,
    openrouter_output,
)
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.lever_comparison import build_lever_comparison, replicate_p
from lancet_eval.pairing import deduplicate_by_arm
from lancet_eval.replay import replay_init
from lancet_eval.stats import (
    exact_signflip_p,
    exact_signflip_p_integer,
    paired_t_p,
    t_two_sided_p,
)

K = 3
PIN = {
    "require_parameters": True,
    "order": ["wafer/us"],
    "allow_fallbacks": False,
    "max_price": {"prompt": 0.07, "completion": 0.45},
}

pytestmark = pytest.mark.usefixtures("preregistered_clean_tree")


# ---- statistics --------------------------------------------------------------------


@pytest.mark.parametrize(("n_pos", "n_neg"), [(0, 0), (3, 0), (4, 5), (12, 2), (7, 7)])
def test_the_integer_permutation_is_the_sign_test_on_unit_differences(
    n_pos: int, n_neg: int
) -> None:
    diffs = [1] * n_pos + [-1] * n_neg + [0] * 4
    assert exact_signflip_p_integer(diffs) == exact_signflip_p(n_pos, n_neg)


def test_the_integer_permutation_enumerates_every_sign_vector() -> None:
    diffs = [3, -1, 2, 0, 1]
    observed = abs(sum(diffs))
    sizes = [abs(d) for d in diffs if d]
    hits = sum(
        abs(sum(s if (mask >> i) & 1 else -s for i, s in enumerate(sizes))) >= observed
        for mask in range(2 ** len(sizes))
    )
    assert exact_signflip_p_integer(diffs) == Fraction(hits, 2 ** len(sizes))


def test_replicate_p_scales_mean_differences_to_integers() -> None:
    vx = {"a": 1.0, "b": 2 / 3, "c": 1 / 3}
    vr = {"a": 0.0, "b": 1 / 3, "c": 1 / 3}
    assert replicate_p(vx, vr, 3) == float(exact_signflip_p_integer([3, 1, 0]))
    with pytest.raises(ValueError, match="not a mean of 3"):
        replicate_p({"a": 0.5}, {"a": 0.0}, 3)


def test_the_paired_t_matches_closed_forms() -> None:
    # df = 1 is Cauchy: P(|T| >= 1) = 1/2. df = 2: 1 - t / sqrt(t^2 + 2).
    assert t_two_sided_p(1.0, 1) == pytest.approx(0.5, abs=1e-12)
    assert t_two_sided_p(1.5, 2) == pytest.approx(1 - 1.5 / (1.5**2 + 2) ** 0.5)
    # The two-sided 5% critical value at df = 10 (2.228138852).
    assert t_two_sided_p(2.228138852, 10) == pytest.approx(0.05, abs=1e-8)
    assert paired_t_p([1.0, -1.0, 3.0]) == pytest.approx(
        t_two_sided_p(1 / (2 / 3**0.5), 2)
    )
    assert paired_t_p([0.0, 0.0]) == 1.0
    assert paired_t_p([0.5]) is None


# ---- the unit key --------------------------------------------------------------------


def _record(qid: str = "q1", **changes: Any) -> RunRecord:
    return RunRecord(
        corpus="c", question_id=qid, graph_arm="hybrid", outcome="success", **changes
    )


def test_replicate_1_is_left_out_of_the_journal_line() -> None:
    assert "replicate" not in json.loads(_record().model_dump_json())
    line = _record(replicate=3).model_dump_json()
    assert json.loads(line)["replicate"] == 3
    assert RunRecord.model_validate_json(line).replicate == 3
    with pytest.raises(ValueError):
        _record(replicate=0)


def test_deduplication_keeps_each_replicate_and_the_later_record_of_one() -> None:
    first = _record(answer="first")
    later = _record(answer="later")
    third = _record(replicate=3)
    kept, collapsed = deduplicate_by_arm([first, third, later])
    assert collapsed == 1
    assert [(r.replicate, r.answer) for r in kept] == [(1, "later"), (3, None)]


def test_a_replicated_constant_needs_the_permutation_test() -> None:
    base = _prereg()
    assert base.replicates == K and base.test == thresholds.REPLICATE_TEST
    with pytest.raises(thresholds.ThresholdError, match="need test"):
        dataclasses.replace(base, test="paired_sign_flip_exact_two_sided")
    with pytest.raises(thresholds.ThresholdError, match="at least 1"):
        dataclasses.replace(base, replicates=0)


# ---- the S2 run ----------------------------------------------------------------------


def _pinned_body(qid: str) -> str:
    body = json.loads(rf.pack_body(qid))
    body["provider"] = PIN
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


class PinnedBin(FakeBin):
    """`pack` emits the fixture body with the D-271 pin; `render` as `FakeBin`."""

    def __init__(self, body: Any = _pinned_body) -> None:
        super().__init__()
        self.body = body

    def __call__(self, mode, rows, levers, results=None):  # type: ignore[no-untyped-def]
        lines = super().__call__(mode, rows, levers, results)
        if mode == "pack":
            for line in lines:
                line["body"] = self.body(line["question_id"])
        return lines


class Endpoint:
    """One fake batch endpoint for both arms: a deepseek body is answered as deepseek
    on OpenRouter credit, a Claude body as Haiku over BYOK. `answers` maps (whether
    the body is deepseek's, custom_id) to its answer text; the default is the gold
    answer."""

    endpoint = "https://fake.test/api/v1/batches"

    def __init__(self, gold: dict[str, str]) -> None:
        self.batches: dict[str, list[BatchRequest]] = {}
        self.gold = gold
        self.answers: dict[tuple[bool, str], str] = {}
        #: (deepseek, custom_id) of the requests that come back errored.
        self.errored: set[tuple[bool, str]] = set()
        #: deepseek requests sent through the sync API, in order (D-278).
        self.sync_calls: list[BatchRequest] = []

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        batch_id = f"batch-{len(self.batches) + 1}"
        self.batches[batch_id] = list(requests)
        return batch_id

    def results(self, batch_id: str) -> list[BatchResult]:
        return [self.complete(req) for req in self.batches[batch_id]]

    def complete(self, req: BatchRequest) -> BatchResult:
        """One reply; deepseek's replicates come one at a time (D-278)."""
        body = json.loads(req.body_json)
        deepseek = body["model"].startswith("deepseek/")
        qid = req.custom_id.rpartition("_r")[0] or req.custom_id
        content = self.answers.get((deepseek, req.custom_id)) or fx._answer(
            "ok" if qid in self.gold else "abstain", self.gold.get(qid, "")
        )
        if (deepseek, req.custom_id) in self.errored:
            return BatchResult(req.custom_id, "errored", error="boom")
        if deepseek:
            self.sync_calls.append(req)
        row = openrouter_row(
            req.custom_id,
            content,
            model=body["model"],
            provider="Wafer" if deepseek else "Anthropic",
        )
        if deepseek:
            # A sync reply reports is_byok itself (D-278): OpenRouter credit.
            reply = row["response"]["body"]
            reply["usage"]["is_byok"] = False
            return BatchResult(
                req.custom_id, "succeeded", output=openrouter_output(reply)
            )
        # A batch row, read as the real client reads it (#137, D-279).
        return _openrouter_result(row, True)


def _prereg() -> thresholds.ReplayStagePreRegistration:
    base = rf.s2_prereg()
    fields = {
        f.name: getattr(base, f.name)
        for f in dataclasses.fields(base)
        if f.name != "replay_source_arm"
    }
    fields["test"] = thresholds.REPLICATE_TEST
    return thresholds.ReplayStagePreRegistration(
        **fields, replay_source_arm=rf.BASE, replicates=K
    )


@pytest.fixture
def s2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    qs = fx.make_questions(10, 5)
    root = tmp_path / "repo"
    gold = rf.write_corpora(root, qs)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, _prereg(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs)
    run = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=run, corpus=fx.CORPUS)
    endpoint = Endpoint({q: a for q, _, a in qs.g})
    binary = PinnedBin()
    monkeypatch.setattr(batch, "client_factory", lambda target: endpoint)
    monkeypatch.setattr(batch, "chat_client_factory", lambda: endpoint)
    monkeypatch.setattr(batch, "bin_runner", binary)
    return run, qs, gold, endpoint, binary


def _units(run: Path, arm: str) -> dict[tuple[str, int], RunRecord]:
    records, _ = deduplicate_by_arm(load_records(run / "journal.jsonl"))
    return {(r.question_id, r.replicate): r for r in records if r.graph_arm == arm}


def _all(qs: fx.Questions) -> list[str]:
    return [*qs.g_ids, *qs.nulls]


def _drive(run: Path) -> None:
    for arm in (rf.READER_ARM, rf.BASE):
        batch.submit(run=run, arm=arm, echo=lambda _: None)
    batch.fetch(run=run, echo=lambda _: None)


def test_a_reader_arm_sends_k_requests_per_question(s2) -> None:
    run, qs, _, endpoint, _ = s2
    sent = batch.submit(run=run, arm=rf.READER_ARM, echo=lambda _: None)
    ids = [r.custom_id for r in endpoint.batches[sent.batch_id]]
    assert ids == [f"{q}_r{k}" for q in _all(qs) for k in range(1, K + 1)]
    batch.fetch(run=run, echo=lambda _: None)
    units = _units(run, rf.READER_ARM)
    assert sorted(units) == sorted((q, k) for q in _all(qs) for k in range(1, K + 1))
    assert all(r.outcome == "success" for r in units.values())
    rows = rf.read_rows(run)
    assert sorted(q for q, a in rows if a == rf.READER_ARM) == sorted(_all(qs))
    manifest = batch.read_manifest(sent.manifest_path)
    assert manifest["requests"][f"{qs.g_ids[0]}_r2"]["replicate"] == 2


def test_the_deepseek_arm_sends_replicates_2_to_k_unrewritten(s2) -> None:
    run, qs, _, endpoint, _ = s2
    sent = batch.submit(run=run, arm=rf.BASE, echo=lambda _: None)
    # D-278: one sync request per answer, no batch.
    assert endpoint.batches == {}
    assert sent.batch_id.startswith("sync-")
    requests = endpoint.sync_calls
    assert [r.custom_id for r in requests] == [
        f"{q}_r{k}" for q in _all(qs) for k in range(2, K + 1)
    ]
    assert all(
        r.body_json == _pinned_body(r.custom_id.rpartition("_r")[0]) for r in requests
    )
    batch.fetch(run=run, echo=lambda _: None)
    units = _units(run, rf.BASE)
    assert sorted(units) == sorted((q, k) for q in _all(qs) for k in range(1, K + 1))
    carried = units[(qs.g_ids[0], 1)]
    assert carried.replay is None and carried.snapshot is not None
    replicate = units[(qs.g_ids[0], 2)]
    assert replicate.replay is not None
    assert replicate.replay.rewritten_fields == []
    assert provenance.provenance_failures(replicate) == []


def test_the_deepseek_arm_refuses_a_body_without_the_d271_pin(
    s2, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, *_ = s2
    monkeypatch.setattr(batch, "bin_runner", PinnedBin(rf.pack_body))
    with pytest.raises(batch.BatchError, match="D-271"):
        batch.submit(run=run, arm=rf.BASE, echo=lambda _: None)


def test_without_replicates_the_deepseek_arm_is_no_batch_arm(
    s2, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, *_ = s2
    monkeypatch.setattr(thresholds, fx.TOKEN, rf.s2_prereg(), raising=False)
    with pytest.raises(batch.BatchError, match="not a reader arm"):
        batch.submit(run=run, arm=rf.BASE, echo=lambda _: None)


def test_limit_takes_every_replicate_of_the_first_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = fx.make_questions(4, 1)
    root = tmp_path / "repo"
    rf.write_corpora(root, qs)
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, _prereg(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs)
    run = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=run, corpus=fx.CORPUS, pilot=True)
    endpoint = Endpoint({q: a for q, _, a in qs.g})
    monkeypatch.setattr(batch, "client_factory", lambda target: endpoint)
    monkeypatch.setattr(batch, "chat_client_factory", lambda: endpoint)
    monkeypatch.setattr(batch, "bin_runner", PinnedBin())
    batch.submit(run=run, arm=rf.BASE, limit=2, echo=lambda _: None)
    assert [r.custom_id for r in endpoint.sync_calls] == [
        f"{q}_r{k}" for q in qs.g_ids[:2] for k in range(2, K + 1)
    ]


def _replay_failures(run: Path) -> list[provenance.ProvenanceFailure]:
    from lancet_eval.context_export import read_export
    from lancet_eval.journal import read_journal_header
    from lancet_eval.preregistration import readers_of
    from lancet_eval.replay import source_row_hashes

    records, _ = deduplicate_by_arm(load_records(run / "journal.jsonl"))
    rows = {
        (r.question_id, r.arm): r for r in read_export(run / "context_export.jsonl")
    }
    return provenance.replay_run_failures(
        records,
        export_rows=rows,
        source_row_sha256=source_row_hashes(read_journal_header(run / "journal.jsonl")),
        readers=readers_of(_prereg()),
    )


def test_a_driven_run_passes_every_replay_clause_and_scores(s2) -> None:
    from lancet_eval.score import score_run

    run, _, gold, _, _ = s2
    _drive(run)
    assert _replay_failures(run) == []
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"provider": "Anthropic"}, "provider"),
        ({"is_byok": True}, "is_byok"),
        ({"model": "deepseek/other"}, "model"),
        ({"sent_body_sha256": "0" * 64}, "body_hash"),
        ({"rewritten_fields": ["provider"]}, "rewritten_fields"),
        ({"reasoning_tokens": 7}, "reasoning_tokens"),
    ],
)
def test_a_deepseek_replicate_breaking_a_clause_is_refused(
    s2, change: dict[str, Any], code: str
) -> None:
    run, qs, *_ = s2
    _drive(run)
    path = run / "journal.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    target = next(
        i
        for i, line in enumerate(lines)
        if json.loads(line).get("graph_arm") == rf.BASE
        and json.loads(line).get("replicate") == 2
    )
    data = json.loads(lines[target])
    data["replay"].update(change)
    lines[target] = json.dumps(data)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert {f.code for f in _replay_failures(run)} == {code}


def test_a_pack_body_without_the_pin_fails_the_provider_clause() -> None:
    body = json.loads(rf.pack_body("q"))
    assert "D-271" in (provenance.deepseek_pin_problem(body) or "")
    body["provider"] = PIN
    assert provenance.deepseek_pin_problem(body) is None
    body["provider"] = {**PIN, "allow_fallbacks": True}
    assert "fallbacks" in (provenance.deepseek_pin_problem(body) or "")


# ---- the comparison ------------------------------------------------------------------


def _wrong(endpoint: Endpoint, cid: str, *, deepseek: bool = False) -> None:
    endpoint.answers[(deepseek, cid)] = fx._answer("wrong", "")


def test_the_comparison_reads_replicate_means_and_the_permutation_test(s2) -> None:
    from lancet_eval.score import score_run

    run, qs, gold, endpoint, _ = s2
    # The reader misses replicate 1 of three questions and all of a fourth;
    # deepseek misses replicate 2 of one question.
    g = qs.g_ids
    for qid in g[:3]:
        _wrong(endpoint, f"{qid}_r1")
    for k in range(1, K + 1):
        _wrong(endpoint, f"{g[3]}_r{k}")
    _wrong(endpoint, f"{g[5]}_r2", deepseek=True)
    _drive(run)
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    payload = build_lever_comparison(run, gold_chunks_path=gold)

    (family,) = payload["families"]
    (row,) = family["comparisons"]
    reader = {q: 1.0 for q in g} | {q: 2 / 3 for q in g[:3]} | {g[3]: 0.0}
    deepseek = {q: 1.0 for q in g} | {g[5]: 2 / 3}
    assert row["n_pairs"] == len(g)
    assert row["mean_arm"] == pytest.approx(sum(reader.values()) / len(g))
    assert row["mean_reference"] == pytest.approx(sum(deepseek.values()) / len(g))
    assert (row["n_pos"], row["n_neg"]) == (1, 4)
    assert row["raw_p"] == replicate_p(reader, deepseek, K)
    diffs = [reader[q] - deepseek[q] for q in sorted(g)]
    assert row["paired_t_p"] == pytest.approx(paired_t_p(diffs))

    (group,) = payload["reader_comparison"]["groups"]
    rows = {r["arm"]: r for r in group["readers"]}
    assert rows[rf.READER_ARM]["answer_usable"]["n_answers"] == len(g) * K
    assert rows[rf.READER_ARM]["answer_usable"]["n_usable"] == len(g) * K - 6
    assert rows[rf.BASE]["batch_spend"]["n_records"] == len(_all(qs)) * (K - 1)


def test_a_question_short_of_a_replicate_leaves_the_population(s2) -> None:
    from lancet_eval.score import score_run

    run, qs, gold, endpoint, _ = s2
    _drive(run)
    path = run / "journal.jsonl"
    kept = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not (
            json.loads(line).get("question_id") == qs.g_ids[0]
            and json.loads(line).get("graph_arm") == rf.READER_ARM
            and json.loads(line).get("replicate") == K
        )
    ]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    (row,) = build_lever_comparison(run, gold_chunks_path=gold)["families"][0][
        "comparisons"
    ]
    assert row["n_pairs"] == len(qs.g_ids) - 1


def test_the_null_guard_counts_replicate_matched_pairs(s2) -> None:
    from lancet_eval.score import score_run

    run, qs, gold, endpoint, _ = s2
    # The reader answers one null question on two of its three replicates.
    for k in (1, 2):
        endpoint.answers[(False, f"{qs.nulls[0]}_r{k}")] = fx._answer("answer_yes", "")
    _drive(run)
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    (guard,) = build_lever_comparison(run, gold_chunks_path=gold)["null_guards"]
    assert (guard["b"], guard["c"]) == (2, 0)
    assert guard["n_pairs"] == len(qs.nulls) * K
    assert guard["n_heldout_null"] == len(qs.nulls) * K


def test_one_replicate_reproduces_the_sign_test() -> None:
    vx = {"a": 1.0, "b": 0.0, "c": 1.0, "d": 1.0}
    vr = {"a": 0.0, "b": 1.0, "c": 1.0, "d": 0.0}
    assert replicate_p(vx, vr, 1) == float(exact_signflip_p(2, 1))
    assert float(exact_signflip_p(2, 1)) == sum(comb(3, k) for k in range(4)) / 8


def test_a_question_with_a_failed_replicate_leaves_the_reader_rows(s2) -> None:
    """Cost per answered question and the reader's usable share count only questions
    whose every answer is ok, as the pairs do (D-274, D-275)."""
    from lancet_eval.score import score_run

    run, qs, gold, endpoint, _ = s2
    endpoint.errored.add((False, f"{qs.g_ids[0]}_r3"))
    _drive(run)
    score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)
    (group,) = build_lever_comparison(run, gold_chunks_path=gold)["reader_comparison"][
        "groups"
    ]
    n = len(qs.g_ids) - 1
    assert group["population"]["n"] == n
    rows = {r["arm"]: r for r in group["readers"]}
    for arm in (rf.BASE, rf.READER_ARM):
        usable = rows[arm]["answer_usable"]
        assert (usable["n"], usable["n_answers"], usable["n_usable"]) == (
            n,
            n * K,
            n * K,
        )


def test_the_deepseek_arm_refuses_a_pin_other_than_config_tomls(
    s2, monkeypatch: pytest.MonkeyPatch
) -> None:
    run, *_ = s2

    def other(qid: str) -> str:
        body = json.loads(_pinned_body(qid))
        body["provider"]["order"] = ["sail-research"]
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    monkeypatch.setattr(batch, "bin_runner", PinnedBin(other))
    with pytest.raises(batch.BatchError, match="config.toml"):
        batch.submit(run=run, arm=rf.BASE, echo=lambda _: None)


def test_a_deepseek_replicate_whose_body_keeps_reasoning_on_is_refused(s2) -> None:
    run, *_ = s2
    _drive(run)
    path = run / "journal.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        data = json.loads(line)
        if data.get("graph_arm") == rf.BASE and data.get("replicate") == 2:
            body = json.loads(data["replay"]["pack_body"])
            body["reasoning"] = {"effort": "high"}
            data["replay"]["pack_body"] = json.dumps(body, separators=(",", ":"))
            lines[i] = json.dumps(data)
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert "reasoning_tokens" in {f.code for f in _replay_failures(run)}


def test_a_reader_with_its_own_k_sends_that_many_answers(
    s2, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#149: a reader's own K (`reader_replicates`) caps its replicates below the
    stage's K; the custom_id keeps the stage's `_r<k>` form."""
    run, qs, _, endpoint, _ = s2
    own = dataclasses.replace(_prereg(), reader_replicates=((rf.READER, 1),))
    monkeypatch.setattr(thresholds, fx.TOKEN, own, raising=False)
    sent = batch.submit(run=run, arm=rf.READER_ARM, echo=lambda _: None)
    ids = [r.custom_id for r in endpoint.batches[sent.batch_id]]
    assert ids == [f"{q}_r1" for q in _all(qs)]
    batch.fetch(run=run, echo=lambda _: None)
    assert sorted(_units(run, rf.READER_ARM)) == sorted((q, 1) for q in _all(qs))


@pytest.mark.parametrize(
    "own", [(("nobody", 1),), ((rf.READER, 0),), ((rf.READER, K + 1),)]
)
def test_reader_replicates_names_a_declared_reader_within_k(
    own: tuple[tuple[str, int], ...],
) -> None:
    with pytest.raises(thresholds.ThresholdError, match="reader_replicates"):
        dataclasses.replace(_prereg(), reader_replicates=own)
