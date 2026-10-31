"""S2 reader arms (#52, D-257): labels, the replay record kind and `replay-init`.

Seam S-F: a fixture S1 run (`replay_fixture`) is carried into an S2 journal by
`replay-init`; a reader arm's records are then appended as `batch fetch` (#53) will
write them, and the run scores with the deepseek arm and the reader arm paired.
"""

from __future__ import annotations

import re
from pathlib import Path

import levers_fixture as fx
import pytest
import replay_fixture as rf
from typer.testing import CliRunner

from lancet_eval import preregistration, thresholds
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
from lancet_eval.journal import read_journal_header
from lancet_eval.provenance import provenance_failures, replay_run_failures
from lancet_eval.replay import (
    REPLAY_SOURCE_KEY,
    ReplayError,
    export_row_sha256,
    replay_init,
)

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


def _s1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs):  # type: ignore[no-untyped-def]
    """A corpus of the deepseek arm and the reader arm, and an S1 run of two arms."""
    qs = fx.make_questions(10, 5)
    root = tmp_path / "repo"
    gold = fx.write_corpus(root, qs, (rf.BASE, rf.READER_ARM))
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr(thresholds, fx.TOKEN, rf.s2_prereg(), raising=False)
    s1 = tmp_path / "s1"
    rf.write_s1_run(s1, qs, **kwargs)
    return s1, gold, qs


def _s2(tmp_path, monkeypatch, *, build=None, row_fn=None):  # type: ignore[no-untyped-def]
    s1, gold, qs = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=s2)
    rf.append_reader_arm(s2, qs, build=build, row_fn=row_fn)
    return s2, gold, qs


def _score(run: Path, gold: Path):  # type: ignore[no-untyped-def]
    from lancet_eval.score import score_run

    return score_run(run_dir=run, no_judge=True, gold_chunks_path=gold)


def test_replay_init_carries_the_arm_records_and_rows_with_their_hashes(
    tmp_path, monkeypatch
) -> None:
    s1, _, qs = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    result = replay_init(source_run=s1, arms=[rf.BASE], run=s2)
    n = len(qs.g_ids) + len(qs.nulls)
    assert (result.records, result.rows) == (n, n)

    source_lines = (s1 / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    carried_lines = (s2 / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    base_lines = [line for line in source_lines[1:] if f'"{rf.BASE}"' in line]
    assert carried_lines[1:] == base_lines

    header = read_journal_header(s2 / "journal.jsonl")
    assert header is not None
    assert header["corpus"] == fx.CORPUS and header["context_export"] is True
    source = header[REPLAY_SOURCE_KEY]
    assert source["run"] == str(s1)
    assert source["arms"] == [rf.BASE]
    rows = rf.read_rows(s1)
    assert source["row_sha256"] == {
        rf.BASE: {
            qid: export_row_sha256(rows[(qid, rf.BASE)])
            for qid in [*qs.g_ids, *qs.nulls]
        }
    }
    assert set(rf.read_rows(s2)) == {(q, rf.BASE) for q in [*qs.g_ids, *qs.nulls]}


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
        replay_init(source_run=s1, arms=[rf.BASE], run=tmp_path / "s2")
    assert "export row" in str(excinfo.value)
    assert not (tmp_path / "s2" / "journal.jsonl").exists()


def test_replay_init_refuses_a_second_init_into_a_populated_journal(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    replay_init(source_run=s1, arms=[rf.BASE], run=s2)
    before = (s2 / "journal.jsonl").read_bytes()
    with pytest.raises(ReplayError, match="already holds"):
        replay_init(source_run=s1, arms=[rf.BASE], run=s2)
    assert (s2 / "journal.jsonl").read_bytes() == before


def test_replay_init_refuses_an_arm_the_source_run_does_not_hold(
    tmp_path, monkeypatch
) -> None:
    s1, _, _ = _s1(tmp_path, monkeypatch)
    with pytest.raises(ReplayError, match="hybrid\\+graph"):
        replay_init(source_run=s1, arms=["hybrid+graph"], run=tmp_path / "s2")
    with pytest.raises(ReplayError, match="reader arm"):
        replay_init(source_run=s1, arms=[rf.READER_ARM], run=tmp_path / "s2")
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
        replay_init(source_run=s1, arms=[rf.BASE], run=tmp_path / "s2")


def test_the_replay_init_command_carries_and_refuses(tmp_path, monkeypatch) -> None:
    from lancet_eval.cli import app

    s1, _, _ = _s1(tmp_path, monkeypatch)
    s2 = tmp_path / "s2"
    args = ["replay-init", "--source-run", str(s1), "--arms", rf.BASE, "--run", str(s2)]
    ok = CliRunner().invoke(app, args)
    assert ok.exit_code == 0, ok.output
    assert "15 record(s)" in ok.output
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
    source = validate_row(fx.make_evidence_export_row(rf.BASE, qid, qs))
    return qs, qid, source


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
