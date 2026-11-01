"""S2 reader arms (#52, D-257): labels, the replay record kind and `replay-init`.

Seam S-F: a fixture S1 run (`replay_fixture`) is carried into an S2 journal by
`replay-init`; a reader arm's records are then appended as `batch fetch` (#53) will
write them, and the run scores with the deepseek arm and the reader arm paired.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import levers_fixture as fx
import pytest
import replay_fixture as rf
from typer.testing import CliRunner

from lancet_eval import gitcheck, preregistration, thresholds
from lancet_eval.arms import (
    READERS,
    arm_reader,
    arm_slug,
    arm_store,
    canonical_arm,
    in_registry_order,
    is_external_arm,
    is_reader_arm,
    judged_arms,
    reader_base_arm,
    request_fields,
    resolve_arm,
)
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, validate_row
from lancet_eval.journal import RunRecord, read_journal_header
from lancet_eval.parity import user_message
from lancet_eval.provenance import provenance_failures, replay_run_failures
from lancet_eval.replay import (
    REPLAY_SOURCE_KEY,
    ReplayError,
    export_row_sha256,
    is_pilot_run,
    replay_init,
)

# Every replay-init into a run of record runs the D-73 check (#109); the tests that
# are about it replace `gitcheck.preregistration_problems` themselves.
pytestmark = pytest.mark.usefixtures("preregistered_clean_tree")

# ---- reader-arm labels ------------------------------------------------------------


def test_a_reader_arm_keeps_its_suffix_and_resolves_to_the_base_row() -> None:
    label = "merged/hybrid+rerank+metadata@haiku-5.5"
    assert canonical_arm(label) == label
    assert resolve_arm(label) == resolve_arm("hybrid+rerank+metadata")
    assert arm_store(label) == "eval-s1"
    assert arm_reader(label) == "haiku-5.5"
    assert reader_base_arm(label) == "merged/hybrid+rerank+metadata"
    assert is_reader_arm(label)
    assert not is_external_arm(label)


def test_the_base_arm_resolves_as_before() -> None:
    assert canonical_arm("graph-off") == "hybrid"
    assert arm_reader("merged/hybrid+rerank+metadata") is None
    assert not is_reader_arm("merged/hybrid+rerank+metadata")
    assert not is_reader_arm("no-such-arm@haiku-5.5")


@pytest.mark.parametrize(
    "label",
    [
        "hybrid@gpt-9",  # unknown reader
        "hybrid@",  # empty reader
        "no-such-arm@haiku-5.5",  # unknown base
        "graph-off@haiku-5.5",  # a legacy alias is never a base
        "hybrid@haiku-5.5@sonnet-5.5",  # two readers
        "tiny/hybrid@haiku-5.5",  # unknown store prefix
    ],
)
def test_a_bad_reader_arm_fails_closed_naming_the_label(label: str) -> None:
    with pytest.raises(ValueError, match="reader|arm|prefix"):
        canonical_arm(label)


def test_every_declared_reader_name_is_accepted() -> None:
    assert {"haiku-5.5", "sonnet-5.5", "opus-5.5"} <= set(READERS)
    for reader in READERS:
        assert arm_reader(f"hybrid+rerank+metadata@{reader}") == reader


def test_a_reader_arm_sends_no_gateway_request() -> None:
    with pytest.raises(ValueError, match="reader arm"):
        request_fields("hybrid+rerank+metadata@haiku-5.5")


def test_reader_arms_sort_after_their_base_and_are_never_judged() -> None:
    base = "merged/hybrid+rerank+metadata"
    labels = [f"{base}@sonnet-5.5", f"{base}@haiku-5.5", base, "hybrid"]
    assert in_registry_order(labels) == [
        "hybrid",
        base,
        f"{base}@haiku-5.5",
        f"{base}@sonnet-5.5",
    ]
    assert judged_arms(labels) == ["hybrid", base]


def test_a_reader_arm_slug_is_filesystem_safe() -> None:
    slug = arm_slug("merged/hybrid+rerank+metadata@haiku-5.5")
    assert slug == "merged_hybrid_rerank_metadata_haiku_5_5"


# ---- seam S-F: carry, replay, score -----------------------------------------------


def _s1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, roles=None, **kwargs):  # type: ignore[no-untyped-def]
    """The S1 and S2 corpora, and an S1 run of two arms on the S1 corpus.

    `roles` passes the corpora's `[split]` roles to `replay_fixture.write_corpora`.
    """
    qs = fx.make_questions(10, 5)
    root = tmp_path / "repo"
    gold = rf.write_corpora(root, qs, **(roles or {}))
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, rf.s2_prereg(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs, **kwargs)
    return s1, gold, qs


def _init(  # type: ignore[no-untyped-def]
    s1: Path, s2: Path, arms=(rf.BASE,), corpus: str = fx.CORPUS, *, pilot=False
):
    return replay_init(
        source_run=s1, arms=list(arms), run=s2, corpus=corpus, pilot=pilot
    )


def _s2(tmp_path, monkeypatch, *, build=None, row_fn=None):  # type: ignore[no-untyped-def]
    s1, gold, qs = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    _init(s1, s2)
    rf.append_reader_arm(s2, qs, build=build, row_fn=row_fn)
    return s2, gold, qs


def _score(run: Path, gold: Path):  # type: ignore[no-untyped-def]
    from lancet_eval.score import score_run

    return score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)


def test_replay_init_carries_the_arm_records_and_rows_under_the_s2_corpus(
    tmp_path, monkeypatch
) -> None:
    s1, _, qs = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    result = _init(s1, s2)
    n = len(qs.g_ids) + len(qs.nulls)
    assert (result.records, result.rows) == (n, n)

    source_lines = (s1 / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    carried_lines = (s2 / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    base_lines = [line for line in source_lines[1:] if f'"{rf.BASE}"' in line]
    carried = [RunRecord.model_validate_json(line) for line in carried_lines[1:]]
    assert carried == [
        RunRecord.model_validate_json(line).model_copy(update={"corpus": fx.CORPUS})
        for line in base_lines
    ]

    header = read_journal_header(s2 / "journal.jsonl")
    assert header is not None
    assert header["corpus"] == fx.CORPUS and header["context_export"] is True
    source = header[REPLAY_SOURCE_KEY]
    assert source["run"] == str(s1)
    assert source["corpus"] == rf.S1_CORPUS
    assert source["arms"] == [rf.BASE]
    s1_rows = rf.read_rows(s1)
    s2_rows = rf.read_rows(s2)
    assert set(s2_rows) == {(q, rf.BASE) for q in [*qs.g_ids, *qs.nulls]}
    for key, row in s2_rows.items():
        assert row == s1_rows[key].model_copy(update={"corpus": fx.CORPUS})
    # The hash covers the row as carried; the S1 row is that row with the source corpus.
    assert source["row_sha256"] == {
        rf.BASE: {
            qid: export_row_sha256(s2_rows[(qid, rf.BASE)])
            for qid in [*qs.g_ids, *qs.nulls]
        }
    }


def test_replay_init_refuses_a_source_run_whose_corpus_is_not_dev(
    tmp_path, monkeypatch
) -> None:
    # An S0 run reads the held-out split: carrying it would spend a third read (D-237).
    s1, _, _ = _s1(tmp_path, monkeypatch, roles={"s1_role": "heldout"})
    with pytest.raises(ReplayError, match="D-237") as excinfo:
        _init(s1, tmp_path / "s2")
    assert rf.S1_CORPUS in str(excinfo.value) and "'heldout'" in str(excinfo.value)
    assert not (tmp_path / "s2" / "journal.jsonl").exists()


def test_replay_init_refuses_an_s2_corpus_that_is_not_dev(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch, roles={"s2_role": "heldout"})
    with pytest.raises(ReplayError, match="D-237"):
        _init(s1, tmp_path / "s2")
    assert not (tmp_path / "s2" / "journal.jsonl").exists()


def test_replay_init_refuses_an_unknown_s2_corpus_or_one_without_the_arms(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    with pytest.raises(ReplayError, match="no-such-corpus"):
        _init(s1, tmp_path / "s2", corpus="no-such-corpus")
    # The S2 corpus lists BASE and its reader arm, not OTHER.
    with pytest.raises(ReplayError, match="does not list"):
        _init(s1, tmp_path / "s2", arms=(rf.BASE, rf.OTHER))
    assert not (tmp_path / "s2" / "journal.jsonl").exists()


def test_replay_init_refuses_a_source_arm_with_a_missing_export_row(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    export = s1 / CONTEXT_EXPORT_FILE
    kept = [
        line
        for line in export.read_text(encoding="utf-8").splitlines(keepends=True)
        if not ('"lv-g002"' in line and f'"{rf.BASE}"' in line)
    ]
    export.write_text("".join(kept), encoding="utf-8")
    with pytest.raises(ReplayError, match="lv-g002") as excinfo:
        _init(s1, tmp_path / "s2")
    assert "export row" in str(excinfo.value)
    assert not (tmp_path / "s2" / "journal.jsonl").exists()


def test_replay_init_refuses_a_second_init_into_a_populated_journal(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    _init(s1, s2)
    before = (s2 / "journal.jsonl").read_bytes()
    with pytest.raises(ReplayError, match="already holds"):
        _init(s1, s2)
    assert (s2 / "journal.jsonl").read_bytes() == before


def test_replay_init_refuses_an_arm_the_source_run_does_not_hold(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    with pytest.raises(ReplayError, match="hybrid\\+graph"):
        _init(s1, tmp_path / "s2", arms=["hybrid+graph"])
    with pytest.raises(ReplayError, match="reader arm"):
        _init(s1, tmp_path / "s2", arms=[rf.READER_ARM])
    assert not (tmp_path / "s2" / "journal.jsonl").exists()


def test_replay_init_refuses_a_source_record_it_cannot_read_naming_the_line(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    journal = s1 / "journal.jsonl"
    with open(journal, "a", encoding="utf-8") as f:
        f.write('{"corpus": "c", "question_id": "q", "graph_arm": "no-such-arm",')
        f.write(' "outcome": "success"}\n')
    with pytest.raises(ReplayError, match="line 32: unknown arm label"):
        _init(s1, tmp_path / "s2")


# ---- #109: D-73 and the S1 handoff before any paid call ----------------------------


def _d73_fails(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Makes the D-73 check report a problem; returns the calls it saw."""
    calls: list[dict[str, object]] = []

    def problems(tokens, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"tokens": tokens, **kwargs})
        return [f"no commit in thresholds.py introduces {tokens[0]}"]

    monkeypatch.setattr(gitcheck, "preregistration_problems", problems)
    return calls


def _with_source_arm(monkeypatch: pytest.MonkeyPatch, arm: str) -> None:
    monkeypatch.setattr(
        thresholds, fx.TOKEN, rf.s2_prereg(replay_source_arm=arm), raising=False
    )


def test_replay_init_into_a_run_of_record_refuses_before_d73_holds(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    calls = _d73_fails(monkeypatch)
    with pytest.raises(ReplayError, match="D-73") as excinfo:
        _init(s1, tmp_path / "s2")
    assert fx.TOKEN in str(excinfo.value)
    assert not (tmp_path / "s2" / "journal.jsonl").exists()
    # The gate score and compare-levers apply later: committed, clean, unchanged.
    assert calls == [
        {
            "tokens": (fx.TOKEN,),
            "require_clean_tree": True,
            "created_at": None,
            "unchanged_since_introduction": True,
        }
    ]


def test_replay_init_refuses_when_git_cannot_prove_d73(tmp_path, monkeypatch) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)

    def broken(tokens, **kwargs):  # type: ignore[no-untyped-def]
        raise gitcheck.GitCheckError("git log failed")

    monkeypatch.setattr(gitcheck, "preregistration_problems", broken)
    with pytest.raises(ReplayError, match="D-73.*git log failed"):
        _init(s1, tmp_path / "s2")


def test_a_pilot_replay_init_skips_d73_and_marks_the_run(tmp_path, monkeypatch) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    _d73_fails(monkeypatch)
    s2 = tmp_path / "s2"
    _init(s1, s2, pilot=True)
    header = read_journal_header(s2 / "journal.jsonl")
    assert header is not None and header[REPLAY_SOURCE_KEY]["pilot"] is True
    assert is_pilot_run(header)


def test_a_run_of_record_is_not_a_pilot_run(tmp_path, monkeypatch) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    _init(s1, s2)
    header = read_journal_header(s2 / "journal.jsonl")
    assert header is not None and header[REPLAY_SOURCE_KEY]["pilot"] is False
    assert not is_pilot_run(header)
    assert not is_pilot_run(None)


def test_replay_init_refuses_an_arm_other_than_the_declared_source_arm(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    _with_source_arm(monkeypatch, rf.OTHER)
    with pytest.raises(ReplayError, match="replay_source_arm") as excinfo:
        _init(s1, tmp_path / "s2")
    assert rf.OTHER in str(excinfo.value) and rf.BASE in str(excinfo.value)
    assert not (tmp_path / "s2" / "journal.jsonl").exists()
    # A pilot replays whatever arm it is given.
    _init(s1, tmp_path / "pilot", pilot=True)


@pytest.mark.parametrize("placeholder", ["", "TODO-S1-WINNER", rf.READER_ARM])
def test_replay_init_refuses_a_placeholder_source_arm_in_a_run_of_record(
    tmp_path, monkeypatch, placeholder
) -> None:
    # Lane 110 commits the S2 constant with a placeholder until S1's Result names the
    # winner: no run of record may start from it.
    s1, _, _ = _s1(tmp_path, monkeypatch)
    _with_source_arm(monkeypatch, placeholder)
    with pytest.raises(ReplayError, match="replay_source_arm"):
        _init(s1, tmp_path / "s2")
    assert not (tmp_path / "s2" / "journal.jsonl").exists()
    _init(s1, tmp_path / "pilot", pilot=True)


def test_replay_init_refuses_a_constant_without_a_source_arm(
    tmp_path, monkeypatch
) -> None:
    if "replay_source_arm" in {
        f.name for f in dataclasses.fields(thresholds.StagePreRegistration)
    }:
        pytest.skip("the type declares replay_source_arm (#110)")
    s1, _, _ = _s1(tmp_path, monkeypatch)
    full = rf.s2_prereg()
    plain = thresholds.StagePreRegistration(**{
        f.name: getattr(full, f.name)
        for f in dataclasses.fields(thresholds.StagePreRegistration)
    })
    monkeypatch.setattr(thresholds, fx.TOKEN, plain, raising=False)
    with pytest.raises(ReplayError, match="replay_source_arm"):
        _init(s1, tmp_path / "s2")


def test_replay_init_refuses_a_partial_source_run(tmp_path, monkeypatch) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    journal = s1 / "journal.jsonl"
    lines = journal.read_text(encoding="utf-8").splitlines(keepends=True)
    assert '"partial": false' in lines[0]
    lines[0] = lines[0].replace('"partial": false', '"partial": true')
    journal.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(ReplayError, match="partial"):
        _init(s1, tmp_path / "s2")
    assert not (tmp_path / "s2" / "journal.jsonl").exists()
    _init(s1, tmp_path / "pilot", pilot=True)


def test_replay_init_refuses_a_source_arm_missing_a_question(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    journal = s1 / "journal.jsonl"
    kept = [
        line
        for line in journal.read_text(encoding="utf-8").splitlines(keepends=True)
        if not ('"lv-g004"' in line and f'"{rf.BASE}"' in line)
    ]
    journal.write_text("".join(kept), encoding="utf-8")
    with pytest.raises(ReplayError, match="lv-g004") as excinfo:
        _init(s1, tmp_path / "s2")
    assert "incomplete" in str(excinfo.value)
    assert not (tmp_path / "s2" / "journal.jsonl").exists()
    _init(s1, tmp_path / "pilot", pilot=True)


def test_a_pilot_replay_init_never_writes_into_a_run_of_record(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    _init(s1, s2)
    journal = (s2 / "journal.jsonl").read_bytes()
    export = (s2 / CONTEXT_EXPORT_FILE).read_bytes()
    with pytest.raises(ReplayError, match="already holds"):
        _init(s1, s2, pilot=True)
    assert (s2 / "journal.jsonl").read_bytes() == journal
    assert (s2 / CONTEXT_EXPORT_FILE).read_bytes() == export
    assert not is_pilot_run(read_journal_header(s2 / "journal.jsonl"))


def test_a_pilot_run_with_reader_records_is_never_scored(tmp_path, monkeypatch) -> None:
    from lancet_eval.score import ScoreError

    s1, gold, qs = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    _init(s1, s2, pilot=True)
    rf.append_reader_arm(s2, qs)
    with pytest.raises(ScoreError, match="pilot run"):
        _score(s2, gold)


def test_the_replay_init_command_writes_a_pilot_run(tmp_path, monkeypatch) -> None:
    from lancet_eval.cli import app

    s1, _, _ = _s1(tmp_path, monkeypatch)
    _d73_fails(monkeypatch)
    s2 = tmp_path / "s2"
    args = ["replay-init", "--source-run", str(s1), "--arms", rf.BASE]
    args += ["--run", str(s2), "--corpus", fx.CORPUS]
    refused = CliRunner().invoke(app, args)
    assert refused.exit_code == 1 and "D-73" in refused.output
    ok = CliRunner().invoke(app, [*args, "--pilot"])
    assert ok.exit_code == 0, ok.output
    assert "pilot" in ok.output
    assert is_pilot_run(read_journal_header(s2 / "journal.jsonl"))


def test_the_replay_init_command_carries_and_refuses(tmp_path, monkeypatch) -> None:
    from lancet_eval.cli import app

    s1, _, _ = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    args = ["replay-init", "--source-run", str(s1), "--arms", rf.BASE, "--run", str(s2)]
    no_corpus = CliRunner().invoke(app, args)
    assert no_corpus.exit_code == 2
    assert not (s2 / "journal.jsonl").exists()
    args += ["--corpus", fx.CORPUS]
    ok = CliRunner().invoke(app, args)
    assert ok.exit_code == 0, ok.output
    assert "15 record(s)" in ok.output
    header = read_journal_header(s2 / "journal.jsonl")
    assert header is not None and header["corpus"] == fx.CORPUS
    again = CliRunner().invoke(app, args)
    assert again.exit_code == 1
    assert "already holds" in again.output


def test_s_f_a_carried_deepseek_arm_and_a_reader_arm_score_and_pair(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import build_lever_comparison

    def build(qid, qs, row):  # type: ignore[no-untyped-def]
        wrong = qid in {"lv-g000", "lv-g001"}
        spec = fx.Spec(kind="wrong" if wrong else "ok")
        return rf.make_replay_record(qid, qs, row, spec=spec)

    s2, gold, qs = _s2(tmp_path, monkeypatch, build=build)
    _score(s2, gold)
    # score writes report.json for a complete run only: the carried records name
    # the S2 corpus, so no corpus disagreement forces the report partial.
    assert (s2 / "report.json").is_file()
    payload = build_lever_comparison(s2, gold_chunks_path=gold)
    family = next(f for f in payload["families"] if f["primary"] == "answer_usable")
    row = next(c for c in family["comparisons"] if c["arm"] == rf.READER_ARM)
    assert row["n_pairs"] == len(qs.g_ids)
    assert (row["n_pos"], row["n_neg"]) == (0, 2)


def test_s_f_the_lever_comparison_re_checks_the_replay_clauses(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    from lancet_eval.lever_comparison import (
        LeverComparisonError,
        build_lever_comparison,
    )

    s2, gold, _ = _s2(tmp_path, monkeypatch)
    _score(s2, gold)
    journal = s2 / "journal.jsonl"
    text = journal.read_text(encoding="utf-8")
    journal.write_text(text.replace(rf.BATCH_ID, "", 1), encoding="utf-8")
    with pytest.raises(
        LeverComparisonError, match=re.escape(f"batch_id {rf.READER_ARM}")
    ):
        build_lever_comparison(s2, gold_chunks_path=gold)


def _refusal(tmp_path, monkeypatch, **kwargs) -> str:  # type: ignore[no-untyped-def]
    from lancet_eval.score import ScoreError

    s2, gold, _ = _s2(tmp_path, monkeypatch, **kwargs)
    with pytest.raises(ScoreError) as excinfo:
        _score(s2, gold)
    return str(excinfo.value)


def _one_broken(qid: str, **changes):  # type: ignore[no-untyped-def]
    def build(q, qs, row):  # type: ignore[no-untyped-def]
        return rf.make_replay_record(q, qs, row, **(changes if q == qid else {}))

    return build


REPLAY_CLAUSES = (
    "row_hash",
    "prompt",
    "body_hash",
    "rewritten_fields",
    "model",
    "is_byok",
    "provider",
    "reasoning_tokens",
    "batch_id",
)


@pytest.mark.parametrize(
    ("code", "changes"),
    [
        ("row_hash", {"export_row_sha256": "0" * 64}),
        ("body_hash", {"sent_body_sha256": "f" * 64}),
        ("rewritten_fields", {"rewritten_fields": ["model", "provider"]}),
        ("model", {"model": "anthropic/claude-sonnet-5.5"}),
        ("is_byok", {"is_byok": False}),
        ("provider", {"provider": "Google"}),
        ("reasoning_tokens", {"reasoning_tokens": 12}),
        ("batch_id", {"batch_id": ""}),
    ],
)
def test_s_f_each_replay_clause_refuses_on_its_own(
    tmp_path, monkeypatch, preregistered_clean_tree, code, changes
) -> None:
    message = _refusal(tmp_path, monkeypatch, build=_one_broken("lv-g003", **changes))
    assert f"{code} {rf.READER_ARM} lv-g003" in message
    for other in set(REPLAY_CLAUSES) - {code}:
        assert f"{other} {rf.READER_ARM}" not in message


def test_s_f_a_reader_row_that_differs_from_the_source_row_fails_row_hash(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def row_fn(row):  # type: ignore[no-untyped-def]
        if row.question_id != "lv-g005":
            return row
        evidence = [e.model_copy(update={"text": "changed"}) for e in row.evidence]
        return row.model_copy(update={"evidence": evidence})

    message = _refusal(tmp_path, monkeypatch, row_fn=row_fn)
    assert f"row_hash {rf.READER_ARM} lv-g005" in message


def test_s_f_a_reader_prompt_that_differs_from_the_source_row_fails_prompt(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    # A pack with other levers, or after a config change, would assemble another
    # prompt: here lv-g008's request carries lv-g009's.
    message = _refusal(
        tmp_path,
        monkeypatch,
        build=_one_broken("lv-g008", body=rf.pack_body("lv-g009")),
    )
    assert f"prompt {rf.READER_ARM} lv-g008" in message
    for other in set(REPLAY_CLAUSES) - {"prompt"}:
        assert f"{other} {rf.READER_ARM}" not in message


def test_s_f_a_pack_body_the_rewrite_refuses_fails_body_hash(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    message = _refusal(
        tmp_path, monkeypatch, build=_one_broken("lv-g004", pack_body='{"model":1}')
    )
    assert f"body_hash {rf.READER_ARM} lv-g004" in message


def test_s_f_a_reader_record_with_an_engine_snapshot_fails_replay_record(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def build(qid, qs, row):  # type: ignore[no-untyped-def]
        rec = rf.make_replay_record(qid, qs, row)
        if qid != "lv-g006":
            return rec
        snapshot = fx.make_record(rf.BASE, qid, fx.Spec(), qs).snapshot
        return rec.model_copy(update={"snapshot": snapshot})

    message = _refusal(tmp_path, monkeypatch, build=build)
    assert f"replay_record {rf.READER_ARM} lv-g006" in message


def test_s_f_a_reader_error_record_needs_no_replay_block(
    tmp_path, monkeypatch, preregistered_clean_tree
) -> None:
    def build(qid, qs, row):  # type: ignore[no-untyped-def]
        spec = fx.Spec(errored=qid == "lv-g007")
        return rf.make_replay_record(qid, qs, row, spec=spec)

    s2, gold, _ = _s2(tmp_path, monkeypatch, build=build)
    _score(s2, gold)


def _one_question():  # type: ignore[no-untyped-def]
    qs = fx.make_questions(1, 0)
    qid = qs.g_ids[0]
    row = fx.make_evidence_export_row(rf.BASE, qid, qs)
    row["assembled_prompt"] = user_message(rf.pack_body(qid))
    row["correlation_id"] = f"corr-{qid}"
    return qs, qid, validate_row(row)


def test_a_thinking_on_reader_is_exempt_from_the_reasoning_tokens_clause() -> None:
    qs, qid, source = _one_question()
    opus_arm = f"{rf.BASE}@opus-5.5"
    sonnet_arm = f"{rf.BASE}@sonnet-5.5"
    rows = {(qid, rf.BASE): source}
    for arm in (opus_arm, sonnet_arm, rf.READER_ARM):
        rows[(qid, arm)] = source.model_copy(update={"arm": arm})
    kwargs = {
        "export_rows": rows,
        "source_row_sha256": {(qid, rf.BASE): export_row_sha256(source)},
        "readers": {"opus-5.5": rf.OPUS, "sonnet-5.5": rf.SONNET, rf.READER: rf.HAIKU},
    }

    def thinking(rec):  # type: ignore[no-untyped-def]
        block = rec.replay.model_copy(update={"reasoning_tokens": 300})
        return rec.model_copy(update={"replay": block})

    opus = rf.make_replay_record(qid, qs, source, reader=rf.OPUS, arm=opus_arm)
    haiku = rf.make_replay_record(qid, qs, source)
    assert replay_run_failures([thinking(opus)], **kwargs) == []
    sonnet = rf.make_replay_record(qid, qs, source, reader=rf.SONNET, arm=sonnet_arm)
    for rec in (haiku, sonnet):
        failures = replay_run_failures([thinking(rec)], **kwargs)
        assert [f.code for f in failures] == ["reasoning_tokens"]
        assert replay_run_failures([rec], **kwargs) == []


def _sonnet_failures(rec, reader=rf.SONNET_NATIVE):  # type: ignore[no-untyped-def]
    qs, qid, source = _one_question()
    del qs
    arm = f"{rf.BASE}@sonnet-5.5"
    return replay_run_failures(
        [rec],
        export_rows={
            (qid, rf.BASE): source,
            (qid, arm): source.model_copy(update={"arm": arm}),
        },
        source_row_sha256={(qid, rf.BASE): export_row_sha256(source)},
        readers={"sonnet-5.5": reader},
    )


def _sonnet(reader=rf.SONNET_NATIVE, **changes):  # type: ignore[no-untyped-def]
    qs, qid, source = _one_question()
    arm = f"{rf.BASE}@sonnet-5.5"
    return rf.make_replay_record(qid, qs, source, reader=reader, arm=arm, **changes)


def test_a_native_anthropic_reader_record_passes_the_clauses() -> None:
    # Q4, D-260: the fallback path reports no provider, no is_byok and no reasoning
    # count, and passes without writing values its response does not hold.
    rec = _sonnet()
    assert rec.replay is not None
    assert (rec.replay.provider, rec.replay.is_byok) == ("api.anthropic.com", None)
    assert _sonnet_failures(rec) == []


@pytest.mark.parametrize(
    ("code", "changes"),
    [
        ("is_byok", {"is_byok": True}),
        ("provider", {"provider": "Anthropic"}),
        ("reasoning_tokens", {"content_block_types": ["thinking", "text"]}),
        ("reasoning_tokens", {"content_block_types": ["redacted_thinking", "text"]}),
        ("reasoning_tokens", {"content_block_types": None}),
        ("reasoning_tokens", {"reasoning_tokens": 5}),
    ],
)
def test_a_native_anthropic_reader_record_fails_on_what_its_target_contradicts(
    code, changes
) -> None:
    failures = _sonnet_failures(_sonnet(**changes))
    assert [f.code for f in failures] == [code]


def test_an_openrouter_reader_record_still_must_show_is_byok() -> None:
    for is_byok in (None, False):
        rec = _sonnet(reader=rf.SONNET, is_byok=is_byok)
        failures = _sonnet_failures(rec, reader=rf.SONNET)
        assert [f.code for f in failures] == ["is_byok"]
    # An OpenRouter record naming the native endpoint is off its target.
    rec = _sonnet(reader=rf.SONNET, provider="api.anthropic.com")
    assert [f.code for f in _sonnet_failures(rec, reader=rf.SONNET)] == ["provider"]


def test_a_native_thinking_on_reader_is_exempt_from_the_thinking_check() -> None:
    opus_native = dataclasses.replace(
        rf.OPUS, slug="claude-opus-5-5", target="anthropic"
    )
    rec = _sonnet(reader=opus_native, content_block_types=["thinking", "text"])
    assert _sonnet_failures(rec, reader=opus_native) == []


def test_the_prompt_clause_needs_the_base_row_and_its_assembled_prompt() -> None:
    qs, qid, source = _one_question()
    rec = rf.make_replay_record(qid, qs, source)
    reader_row = source.model_copy(update={"arm": rf.READER_ARM})
    kwargs = {
        "source_row_sha256": {(qid, rf.BASE): export_row_sha256(source)},
        "readers": {rf.READER: rf.HAIKU},
    }
    good = replay_run_failures(
        [rec],
        export_rows={(qid, rf.BASE): source, (qid, rf.READER_ARM): reader_row},
        **kwargs,
    )
    assert good == []
    no_base = replay_run_failures(
        [rec], export_rows={(qid, rf.READER_ARM): reader_row}, **kwargs
    )
    assert "prompt" in [f.code for f in no_base]


def test_engine_and_external_records_carrying_a_replay_block_fail() -> None:
    qs, qid, source = _one_question()
    block = rf.make_replay_record(qid, qs, source).replay
    engine = fx.make_record(rf.BASE, qid, fx.Spec(), qs)
    external = fx.make_external_record(qid, fx.Spec(), qs)
    for rec in (engine, external):
        failures = provenance_failures(rec.model_copy(update={"replay": block}))
        assert "replay_record" in [f.code for f in failures]


# ---- pre-registration -------------------------------------------------------------


def test_a_stage_constant_with_reader_arms_resolves(monkeypatch) -> None:
    monkeypatch.setattr(thresholds, "S2_TEST_TOKEN", rf.s2_prereg(), raising=False)
    prereg = preregistration.resolve("S2_TEST_TOKEN")
    assert preregistration.arms_of(prereg) == (rf.BASE, rf.READER_ARM)
    assert preregistration.readers_of(prereg) == {rf.READER: rf.HAIKU}


@pytest.mark.parametrize(
    ("readers", "arm", "shown"),
    [
        ((("haiku-5.5", rf.HAIKU),), f"{rf.BASE}@sonnet-5.5", "sonnet-5.5"),
        ((), rf.READER_ARM, "haiku-5.5"),
        ((("gpt-9", rf.HAIKU),), rf.READER_ARM, "gpt-9"),
        ((("haiku-5.5", rf.HAIKU), ("haiku-5.5", rf.HAIKU)), rf.READER_ARM, "twice"),
        ((("haiku-5.5", "anthropic/claude-haiku-5.5"),), rf.READER_ARM, "not a"),
    ],
)
def test_a_stage_constant_with_an_undeclared_or_bad_reader_fails_closed(
    monkeypatch, readers, arm, shown
) -> None:
    prereg = rf.s2_prereg(readers=readers, arm=arm)
    monkeypatch.setattr(thresholds, "S2_TEST_TOKEN", prereg, raising=False)
    with pytest.raises(preregistration.PreregistrationError, match=shown):
        preregistration.resolve("S2_TEST_TOKEN")


# ---- D-291: a reader-grid run plan replays held-out ---------------------------------


def _grid_plan() -> thresholds.ReaderGridRunPlan:
    return thresholds.ReaderGridRunPlan(
        benchmark="levers",
        split_file="eval/corpora/levers/split.json",
        split_sha256="a" * 64,
        population="held-out",
        question_count=15,
        columns=(("c", thresholds.GridColumn(source_arm=rf.BASE)),),
        readers=((rf.READER, rf.HAIKU),),
        replicates=1,
        reader_replicates=(),
        reference_price=thresholds.ReaderPrice(0.0448, 0.30),
        cells=(("c", "deepseek", "core"), ("c", rf.READER, "core")),
        transports=(
            ("deepseek", "engine_drive_then_openrouter_sync"),
            (rf.READER, "openrouter_batch"),
        ),
        rerank_degrade_tripwire_rate=0.20,
        rerank_degrade_tripwire_min_calls=50,
        rerank_consecutive_degrade_halt=5,
        blinding_rule="no score",
        order_rule="any",
        report_rule="run dirs",
        provenance="test",
    )


def _grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, column: bool = True):  # type: ignore[no-untyped-def]
    """A held-out S2 corpus under a run plan, and a source run driven on it."""
    qs = fx.make_questions(10, 5)
    root = tmp_path / "repo"
    rf.write_corpora(root, qs, s1_role="heldout", s2_role="heldout")
    toml = root / "eval" / "corpora" / f"{fx.CORPUS}.toml"
    if column:
        toml.write_text(
            toml.read_text(encoding="utf-8") + 'column = "c"\n', encoding="utf-8"
        )
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, _grid_plan(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs, arms=(rf.BASE,), corpus=fx.CORPUS)
    return s1, qs


def test_replay_init_carries_a_heldout_column_of_a_run_plan(
    tmp_path, monkeypatch
) -> None:
    s1, qs = _grid(tmp_path, monkeypatch)
    result = _init(s1, tmp_path / "s2")
    assert result.records == len(qs.g_ids) + len(qs.nulls)
    header = read_journal_header(tmp_path / "s2" / "journal.jsonl")
    assert header[REPLAY_SOURCE_KEY]["arms"] == [rf.BASE]


def test_a_heldout_corpus_without_a_column_is_still_refused(
    tmp_path, monkeypatch
) -> None:
    s1, _ = _grid(tmp_path, monkeypatch, column=False)
    with pytest.raises(ReplayError, match="D-237"):
        _init(s1, tmp_path / "s2")
    assert not (tmp_path / "s2" / "journal.jsonl").exists()


def test_a_run_plan_replays_only_a_source_run_of_its_own_corpus(
    tmp_path, monkeypatch
) -> None:
    s1, qs = _grid(tmp_path, monkeypatch)
    other = tmp_path / "s1-other"
    rf.write_s1_run(other, qs, arms=(rf.BASE,))
    with pytest.raises(ReplayError, match="D-291"):
        _init(other, tmp_path / "s2")
    assert not (tmp_path / "s2" / "journal.jsonl").exists()
