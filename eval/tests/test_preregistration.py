"""Tests for the 06.3.5 pre-registration constants and the D-73 ordering gates."""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from lancet_eval import gitcheck, thresholds
from lancet_eval import score as score_mod
from lancet_eval.run import drive
from lancet_eval.score import ScoreError, score_run


def test_the_preregistration_values_are_the_owner_decisions() -> None:
    pre = thresholds.PREREGISTRATION_06_3_5
    assert isinstance(pre, thresholds.AblationPreRegistration)
    assert pre.primaries == ("paper_hits_at_4", "answer_usable")
    assert pre.reference_arm == "hybrid"
    assert pre.comparison_arms == ("dense-only", "bm25-only", "hybrid+graph")
    assert pre.family == "per_primary"
    assert pre.family_alpha == 0.05
    assert pre.test == "paired_sign_flip_exact_two_sided"
    assert pre.population.startswith("P4")
    assert pre.matching_rule == "chunk_id_via_gold_chunks"
    assert pre.complete_case_floor == 0.80
    assert pre.bootstrap_b == 10_000
    assert pre.bootstrap_seed == 42


def test_the_preregistration_provenance_names_its_decisions() -> None:
    provenance = thresholds.PREREGISTRATION_06_3_5.provenance
    for token in ("D-111", "D-121", "D-122", "D-123", "2026-10-06"):
        assert token in provenance
    assert "never changed after data is seen" in provenance


def test_the_preregistration_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        thresholds.PREREGISTRATION_06_3_5.reference_arm = "dense-only"  # type: ignore[misc]


def test_the_primaries_and_bootstrap_agree_with_the_harness_constants() -> None:
    from lancet_eval import stats

    pre = thresholds.PREREGISTRATION_06_3_5
    assert pre.bootstrap_b == stats.BOOTSTRAP_B
    assert pre.bootstrap_seed == stats.BOOTSTRAP_SEED


def test_the_judge_and_calibration_constants() -> None:
    assert thresholds.JUDGE_QWK_TRUST_FLOOR == 0.70
    assert thresholds.CALIBRATION_MIN_SCORED_PAIRS == 16
    assert thresholds.CALIBRATION_DRAW_SEED == 42
    assert thresholds.JUDGE_ERROR_RATE_TRIPWIRE == 0.05
    assert thresholds.JUDGE_ERROR_TRIPWIRE_MIN_CALLS == 50
    assert thresholds.JUDGE_CONSECUTIVE_ERROR_HALT == 5


def test_the_trust_floor_keeps_continuity_with_the_legacy_target() -> None:
    from lancet_eval import gate

    # Continuity (D-119): the same number in a separate constant; gate.py is untouched.
    assert thresholds.JUDGE_QWK_TRUST_FLOOR == gate.AGREEMENT_TARGET
    assert gate.CALIBRATION_SIZE == 12


# --- gitcheck over a throwaway repository (never the live one) ----------------------

THRESHOLDS = "eval/src/lancet_eval/thresholds.py"
OTHER = "eval/src/lancet_eval/other.py"
T0 = 1_700_000_000


def _git(repo: Path, *args: str, when: int | None = None) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(repo.parent / "empty.gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if when is not None:
        env["GIT_AUTHOR_DATE"] = f"{when} +0000"
        env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    res = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=repo,
        shell=False,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return res.stdout.strip()


def _write(repo: Path, rel: str, data: bytes) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _commit(repo: Path, message: str, when: int) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, when=when)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Two commits: the first has no token, the second adds both constants."""
    root = tmp_path / "throwaway"
    root.mkdir()
    (tmp_path / "empty.gitconfig").write_text("", encoding="utf-8")
    _git(root, "init", "-q")
    _write(root, THRESHOLDS, b"BASELINE = 1\r\n")
    _write(root, OTHER, b"X = 0\n")
    _commit(root, "first", T0)
    _write(
        root,
        THRESHOLDS,
        b"BASELINE = 1\r\nPREREGISTRATION_06_3_5 = 2\r\n"
        b"JUDGE_QWK_TRUST_FLOOR = 0.7\r\n",
    )
    _commit(root, "second", T0 + 100)
    return root


def _shas(repo: Path) -> tuple[str, str]:
    second, first = _git(repo, "log", "--format=%H").splitlines()
    return first, second


def test_introducing_commit_returns_the_first_commit_that_added_the_token(
    repo: Path,
) -> None:
    first, second = _shas(repo)
    found = gitcheck.introducing_commit("PREREGISTRATION_06_3_5", THRESHOLDS, repo=repo)
    assert found == second
    assert gitcheck.introducing_commit("BASELINE", THRESHOLDS, repo=repo) == first
    assert gitcheck.introducing_commit("NOT_THERE", THRESHOLDS, repo=repo) is None


def test_head_sha_commit_time_and_ancestry(repo: Path) -> None:
    first, second = _shas(repo)
    assert gitcheck.head_sha(repo=repo) == second
    assert gitcheck.commit_time(first, repo=repo) == T0
    assert gitcheck.commit_time(second, repo=repo) == T0 + 100
    assert gitcheck.is_ancestor(first, second, repo=repo) is True
    assert gitcheck.is_ancestor(second, first, repo=repo) is False
    assert gitcheck.is_ancestor(second, second, repo=repo) is True


def test_is_tracked_is_false_for_an_untracked_file(repo: Path) -> None:
    _write(repo, "eval/src/lancet_eval/new.py", b"Y = 1\n")
    assert gitcheck.is_tracked(THRESHOLDS, repo=repo) is True
    assert gitcheck.is_tracked("eval/src/lancet_eval/new.py", repo=repo) is False


def test_is_clean_is_false_with_a_modified_tracked_file(repo: Path) -> None:
    assert gitcheck.is_clean(gitcheck.SOURCE_DIR, repo=repo) is True
    _write(repo, OTHER, b"X = 1\n")
    assert gitcheck.is_clean(gitcheck.SOURCE_DIR, repo=repo) is False
    assert gitcheck.is_clean("some/other/dir", repo=repo) is True


def test_is_clean_counts_an_untracked_file_under_the_path(repo: Path) -> None:
    _write(repo, "eval/src/lancet_eval/new.py", b"Y = 1\n")
    assert gitcheck.is_clean(gitcheck.SOURCE_DIR, repo=repo) is False


def test_show_blob_returns_lf_content_of_a_crlf_blob(repo: Path) -> None:
    first, _ = _shas(repo)
    blob = gitcheck.show_blob(first, THRESHOLDS, repo=repo)
    assert blob == "BASELINE = 1\n"
    assert "\r" not in blob


def test_last_commit_touching_a_path(repo: Path) -> None:
    first, second = _shas(repo)
    assert gitcheck.last_commit_touching(THRESHOLDS, repo=repo) == second
    assert gitcheck.last_commit_touching(OTHER, repo=repo) == first
    assert gitcheck.last_commit_touching("never/existed.py", repo=repo) is None


def test_repo_defaults_to_repo_root(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gitcheck, "repo_root", lambda: repo)
    assert gitcheck.head_sha() == _shas(repo)[1]


def test_a_leaking_git_dir_does_not_redirect_a_call(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _shas(repo)[1]
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nowhere" / ".git"))
    assert gitcheck.head_sha(repo=repo) == expected


@pytest.mark.parametrize("bad", ["", "-Sevil", "--output=x"])
def test_a_token_or_path_that_looks_like_an_option_is_refused(
    repo: Path, bad: str
) -> None:
    with pytest.raises(gitcheck.GitCheckError):
        gitcheck.introducing_commit(bad, THRESHOLDS, repo=repo)
    with pytest.raises(gitcheck.GitCheckError):
        gitcheck.introducing_commit("BASELINE", bad, repo=repo)


def test_a_revision_that_is_not_a_commit_id_is_refused(repo: Path) -> None:
    with pytest.raises(gitcheck.GitCheckError):
        gitcheck.commit_time("--all", repo=repo)
    with pytest.raises(gitcheck.GitCheckError):
        gitcheck.is_ancestor("HEAD;rm", "HEAD", repo=repo)


def test_an_unexpected_git_failure_raises_gitcheckerror(tmp_path: Path) -> None:
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    with pytest.raises(gitcheck.GitCheckError):
        gitcheck.head_sha(repo=not_a_repo)


def test_gitcheck_uses_list_form_subprocess_only() -> None:
    source = Path(gitcheck.__file__).read_text(encoding="utf-8")
    assert "shell=False" in source
    assert "shell=True" not in source
    assert "os.system" not in source


def test_run_and_score_reach_git_only_through_gitcheck() -> None:
    import lancet_eval.run as run_mod

    for mod in (run_mod, score_mod):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        literals = {
            n.value
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }
        # the token is only ever named by gitcheck's constants, never as a literal here
        assert "PREREGISTRATION_06_3_5" not in literals
        assert "JUDGE_QWK_TRUST_FLOOR" not in literals
        assert "shell=True" not in source
        assert "gitcheck." in source


# --- preregistration_problems -------------------------------------------------------

BOTH = (gitcheck.PREREGISTRATION_TOKEN, gitcheck.TRUST_FLOOR_TOKEN)


def test_no_problem_when_the_commit_is_an_older_ancestor_of_a_clean_head(
    repo: Path,
) -> None:
    problems = gitcheck.preregistration_problems(
        BOTH, created_at=float(T0 + 200), require_clean_tree=True, repo=repo
    )
    assert problems == []


def test_a_missing_token_is_a_problem(repo: Path) -> None:
    problems = gitcheck.preregistration_problems(("NOT_THERE",), repo=repo)
    assert len(problems) == 1
    assert "NOT_THERE" in problems[0]


@pytest.mark.parametrize("created_at", [float(T0 + 100), float(T0 + 50), float(T0)])
def test_a_commit_not_strictly_older_than_the_data_is_a_problem(
    repo: Path, created_at: float
) -> None:
    problems = gitcheck.preregistration_problems(BOTH, created_at=created_at, repo=repo)
    assert len(problems) == 2
    assert all("created_at" in p for p in problems)


def test_a_dirty_source_tree_is_a_problem_only_when_clean_is_required(
    repo: Path,
) -> None:
    _write(repo, OTHER, b"X = 99\n")
    assert gitcheck.preregistration_problems(BOTH, repo=repo) == []
    problems = gitcheck.preregistration_problems(
        BOTH, require_clean_tree=True, repo=repo
    )
    assert problems == [f"{gitcheck.SOURCE_DIR} has an uncommitted change"]


def test_a_token_committed_after_head_is_not_found_from_head(repo: Path) -> None:
    first, _ = _shas(repo)
    _git(repo, "checkout", "-q", first)
    problems = gitcheck.preregistration_problems(BOTH, repo=repo)
    # git log -S walks HEAD's history only: a later commit is invisible
    assert len(problems) == 2


def test_an_introducing_commit_beyond_head_is_not_an_ancestor(repo: Path) -> None:
    first, second = _shas(repo)
    _git(repo, "checkout", "-q", "-b", "side", first)
    _write(repo, OTHER, b"X = 2\n")
    side = _commit(repo, "side", T0 + 300)
    assert gitcheck.head_sha(repo=repo) == side
    assert gitcheck.is_ancestor(second, side, repo=repo) is False


# --- the D-73 refusal in drive ------------------------------------------------------


def _drive_args(tmp_path: Path, corpus: str) -> dict[str, object]:
    return {
        "corpus": corpus,
        "journal_path": tmp_path / "journal.jsonl",
        "stage_spend_cap": 10.0,
        "workers": 1,
        "max_retries": 0,
        "client": httpx.Client(base_url="http://testserver"),
    }


def test_drive_refuses_a_split_corpus_without_a_committed_preregistration(
    tmp_path: Path,
) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    (tmp_path / "empty.gitconfig").write_text("", encoding="utf-8")
    _git(bare, "init", "-q")
    _write(bare, THRESHOLDS, b"BASELINE = 1\n")
    _commit(bare, "only", T0)
    args = _drive_args(tmp_path, "multihop_rag_heldout")

    with pytest.raises(ValueError, match="PREREGISTRATION_06_3_5") as excinfo:
        drive(**args, git_repo=bare)  # type: ignore[arg-type]
    assert "D-73" in str(excinfo.value)
    assert isinstance(excinfo.value, gitcheck.PreregistrationError)
    assert not (tmp_path / "journal.jsonl").exists()


def test_drive_refuses_a_split_corpus_when_the_source_tree_is_dirty(
    tmp_path: Path, repo: Path
) -> None:
    _write(repo, OTHER, b"X = 99\n")
    args = _drive_args(tmp_path, "multihop_rag_heldout")

    with pytest.raises(gitcheck.PreregistrationError, match="uncommitted") as excinfo:
        drive(**args, git_repo=repo)  # type: ignore[arg-type]
    assert "D-73" in str(excinfo.value)
    assert not (tmp_path / "journal.jsonl").exists()


def test_drive_refuses_the_rehearsal_split_corpus_too(
    tmp_path: Path, repo: Path
) -> None:
    _write(repo, OTHER, b"X = 99\n")
    args = _drive_args(tmp_path, "multihop_rag_rehearsal")
    with pytest.raises(gitcheck.PreregistrationError):
        drive(**args, git_repo=repo)  # type: ignore[arg-type]
    assert not (tmp_path / "journal.jsonl").exists()


def test_drive_never_checks_a_legacy_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> list[str]:
        raise AssertionError("a legacy corpus must never reach the D-73 check")

    monkeypatch.setattr(gitcheck, "preregistration_problems", boom)
    args = _drive_args(tmp_path, "graphrag_bench")
    result = drive(**args, limit=0)  # type: ignore[arg-type]
    assert result == 0


# --- the D-73 refusal in score ------------------------------------------------------


def _split_journal(tmp_path: Path, created_at: object) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    header: dict[str, object] = {
        "type": "header",
        "corpus": "multihop_rag_rehearsal",
        "partial": False,
    }
    if created_at is not None:
        header["created_at"] = created_at
    record = {
        "corpus": "multihop_rag_rehearsal",
        "question_id": "q1",
        "graph_arm": "hybrid",
        "outcome": "success",
        "answer": "Answer: Yes",
    }
    with open(run_dir / "journal.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(header) + "\n")
        f.write(json.dumps(record) + "\n")
    return run_dir


def test_score_refuses_a_split_report_when_the_data_predates_the_commit(
    tmp_path: Path, repo: Path
) -> None:
    run_dir = _split_journal(tmp_path, float(T0 + 50))
    with pytest.raises(ScoreError, match="D-73") as excinfo:
        score_run(run_dir=run_dir, no_judge=True, git_repo=repo)
    assert "PREREGISTRATION_06_3_5" in str(excinfo.value)


def test_score_refuses_a_split_report_whose_header_has_no_created_at(
    tmp_path: Path, repo: Path
) -> None:
    run_dir = _split_journal(tmp_path, None)
    with pytest.raises(ScoreError, match="created_at"):
        score_run(run_dir=run_dir, no_judge=True, git_repo=repo)


def test_a_later_created_at_passes_the_score_ordering_check(repo: Path) -> None:
    score_mod._require_preregistered_before(float(T0 + 200), repo)
    with pytest.raises(ScoreError, match="D-73"):
        score_mod._require_preregistered_before(float(T0 + 100), repo)
    with pytest.raises(ScoreError, match="created_at"):
        score_mod._require_preregistered_before("yesterday", repo)
    with pytest.raises(ScoreError, match="created_at"):
        score_mod._require_preregistered_before(True, repo)


def test_the_fixture_makes_the_gates_independent_of_the_working_tree(
    preregistered_clean_tree: str,
) -> None:
    problems = gitcheck.preregistration_problems(
        BOTH, created_at=float(time.time()), require_clean_tree=True
    )
    assert problems == []
    found = gitcheck.introducing_commit("anything", "any/path")
    assert found == preregistered_clean_tree


# --- WR-02: a pre-registered value must be unchanged since its introducing commit ---

_V2 = b"BASELINE = 1\nPREREGISTRATION_06_3_5 = 2\nJUDGE_QWK_TRUST_FLOOR = 0.7\n"
_V3 = b"BASELINE = 1\nPREREGISTRATION_06_3_5 = 3\nJUDGE_QWK_TRUST_FLOOR = 0.7\n"


def test_unchanged_values_pass_the_since_introduction_check(repo: Path) -> None:
    problems = gitcheck.preregistration_problems(
        BOTH, unchanged_since_introduction=True, repo=repo
    )
    assert problems == []


def test_a_value_changed_in_a_later_commit_is_a_problem(repo: Path) -> None:
    _write(repo, THRESHOLDS, _V3)
    _commit(repo, "tweak", T0 + 200)
    problems = gitcheck.preregistration_problems(
        BOTH, unchanged_since_introduction=True, repo=repo
    )
    assert len(problems) == 1
    assert "PREREGISTRATION_06_3_5" in problems[0]
    assert "differs" in problems[0]
    # the ordering alone still passes, which is the gap WR-02 names
    assert gitcheck.preregistration_problems(BOTH, repo=repo) == []


def test_an_uncommitted_edit_of_a_value_is_a_problem(repo: Path) -> None:
    _write(
        repo,
        THRESHOLDS,
        b"BASELINE = 1\nPREREGISTRATION_06_3_5 = 2\nJUDGE_QWK_TRUST_FLOOR = 0.9\n",
    )
    problems = gitcheck.preregistration_problems(
        BOTH, unchanged_since_introduction=True, repo=repo
    )
    assert len(problems) == 1
    assert "JUDGE_QWK_TRUST_FLOOR" in problems[0]


def test_a_formatting_or_comment_change_is_not_a_difference(repo: Path) -> None:
    _write(
        repo,
        THRESHOLDS,
        b"# a note\nBASELINE = 1\nPREREGISTRATION_06_3_5   =   (2)  # unchanged\n"
        b"JUDGE_QWK_TRUST_FLOOR: float = 0.70\n",
    )
    problems = gitcheck.preregistration_problems(
        BOTH, unchanged_since_introduction=True, repo=repo
    )
    assert problems == []


def test_a_token_with_no_readable_assignment_is_a_problem(repo: Path) -> None:
    _write(
        repo,
        THRESHOLDS,
        b"BASELINE = 1\n# PREREGISTRATION_06_3_5 JUDGE_QWK_TRUST_FLOOR\n",
    )
    problems = gitcheck.preregistration_problems(
        BOTH, unchanged_since_introduction=True, repo=repo
    )
    assert len(problems) == 2
    assert all("no readable assignment" in p for p in problems)


def test_drive_refuses_a_split_corpus_whose_preregistered_value_changed(
    tmp_path: Path, repo: Path
) -> None:
    _write(repo, THRESHOLDS, _V3)
    _commit(repo, "tweak", T0 + 200)
    args = _drive_args(tmp_path, "multihop_rag_heldout")

    with pytest.raises(gitcheck.PreregistrationError, match="differs") as excinfo:
        drive(**args, git_repo=repo)  # type: ignore[arg-type]
    assert "D-73" in str(excinfo.value)
    assert not (tmp_path / "journal.jsonl").exists()


def test_score_refuses_a_split_report_whose_preregistered_value_changed(
    repo: Path,
) -> None:
    _write(repo, THRESHOLDS, _V3)
    _commit(repo, "tweak", T0 + 200)
    with pytest.raises(ScoreError, match="differs"):
        score_mod._require_preregistered_before(float(T0 + 1000), repo)


def test_the_live_repository_values_match_their_introducing_commit() -> None:
    """The closed run of record passes the new check against the real history."""
    live = gitcheck.introducing_commit(
        gitcheck.PREREGISTRATION_TOKEN, gitcheck.THRESHOLDS_PATH
    )
    if live is None:
        pytest.skip("the git history that introduced the pre-registration is absent")
    problems = gitcheck.preregistration_problems(
        BOTH, unchanged_since_introduction=True
    )
    assert problems == []


def test_score_refuses_a_split_report_when_the_source_tree_is_dirty(
    repo: Path,
) -> None:
    _write(repo, OTHER, b"X = 99\n")
    with pytest.raises(ScoreError, match="uncommitted"):
        score_mod._require_preregistered_before(float(T0 + 1000), repo)


# --- 06.3.6-03: score gates on the configured token; no judge for a 06.3.6 corpus ---


def _record_gate_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, ...]]:
    seen: list[tuple[str, ...]] = []

    def refuse(tokens: tuple[str, ...], **_kwargs: object) -> list[str]:
        seen.append(tokens)
        return ["stop here"]

    monkeypatch.setattr(gitcheck, "preregistration_problems", refuse)
    return seen


def test_score_on_a_judged_corpus_gates_on_its_token_and_the_trust_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval.corpus import load_corpus_config

    config = load_corpus_config("multihop_rag_rehearsal")
    assert config.has_judge
    config.preregistration_token = "PREREGISTRATION_X_FOR_TEST"
    monkeypatch.setattr(score_mod, "load_corpus_config", lambda _name: config)
    seen = _record_gate_tokens(monkeypatch)
    run_dir = _split_journal(tmp_path, float(T0 + 100))

    with pytest.raises(ScoreError, match="D-73"):
        score_run(run_dir=run_dir, no_judge=True)
    assert seen == [("PREREGISTRATION_X_FOR_TEST", gitcheck.TRUST_FLOOR_TOKEN)]


def test_score_on_a_corpus_without_a_judge_section_gates_on_its_token_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lancet_eval.corpus import load_corpus_config

    config = load_corpus_config("multihop_rag_rehearsal")
    config.has_judge = False
    config.judge_protocol = "legacy"
    monkeypatch.setattr(score_mod, "load_corpus_config", lambda _name: config)
    seen = _record_gate_tokens(monkeypatch)
    run_dir = _split_journal(tmp_path, float(T0 + 100))

    with pytest.raises(ScoreError, match="D-73"):
        score_run(run_dir=run_dir, no_judge=True)
    assert seen == [("PREREGISTRATION_06_3_5",)]


def test_require_preregistered_before_defaults_to_the_06_3_5_pair(
    repo: Path,
) -> None:
    score_mod._require_preregistered_before(float(T0 + 200), repo)
    with pytest.raises(ScoreError, match="NOT_THERE"):
        score_mod._require_preregistered_before(
            float(T0 + 200), repo, ("NOT_THERE",)
        )


def test_the_judged_path_is_refused_for_a_06_3_6_token_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-153: no paid judge call can be issued for a 06.3.6 corpus."""
    from lancet_eval.corpus import load_corpus_config

    config = load_corpus_config("multihop_rag_rehearsal")
    config.preregistration_token = "PREREGISTRATION_06_3_6"
    config.has_judge = False
    monkeypatch.setattr(score_mod, "load_corpus_config", lambda _name: config)
    seen = _record_gate_tokens(monkeypatch)
    run_dir = _split_journal(tmp_path, float(T0 + 100))

    with pytest.raises(ScoreError, match="D-153"):
        score_run(
            run_dir=run_dir,
            judged=True,
            calibration_file=tmp_path / "worksheet.json",
            calibration_key=tmp_path / "key.json",
        )
    assert seen == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"no_judge": False},
        {"emit_calibration_worksheet": "worksheet.json"},
        {"calibration_file": "worksheet.json"},
    ],
    ids=["legacy-judge", "emit-worksheet", "calibration-file"],
)
def test_no_judge_path_at_all_is_open_to_a_06_3_6_token_corpus(
    kwargs: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-153: legacy `--judge`, the worksheet and a calibration input are refused."""
    from lancet_eval.corpus import load_corpus_config

    config = load_corpus_config("multihop_rag_rehearsal")
    config.preregistration_token = "PREREGISTRATION_06_3_6"
    config.has_judge = False
    config.judge_protocol = "legacy"
    monkeypatch.setattr(score_mod, "load_corpus_config", lambda _name: config)
    seen = _record_gate_tokens(monkeypatch)
    run_dir = _split_journal(tmp_path, float(T0 + 100))

    with pytest.raises(ScoreError, match="D-153"):
        score_run(run_dir=run_dir, **kwargs)  # type: ignore[arg-type]
    assert seen == []


# --- 06.3.6-07: the pre-registration resolver (D-73, D-149) ----------------------------


def test_resolve_returns_the_object_a_corpus_token_names() -> None:
    from lancet_eval import preregistration

    assert (
        preregistration.resolve("PREREGISTRATION_06_3_5")
        is thresholds.PREREGISTRATION_06_3_5
    )


@pytest.mark.parametrize(
    "token",
    [
        "PREREGISTRATION_NOT_THERE",
        "UNPARK_GATE_COVERAGE_FLOOR",
        "COMMITTED_THRESHOLDS",
        "",
    ],
)
def test_resolve_fails_closed_on_an_absent_or_non_preregistration_token(
    token: str,
) -> None:
    from lancet_eval import preregistration

    with pytest.raises(preregistration.PreregistrationError):
        preregistration.resolve(token)


def test_resolve_raises_the_gitcheck_error_type() -> None:
    from lancet_eval import preregistration

    assert preregistration.PreregistrationError is gitcheck.PreregistrationError


def test_arms_of_an_ablation_preregistration_is_reference_then_comparisons() -> None:
    from lancet_eval import preregistration

    assert preregistration.arms_of(thresholds.PREREGISTRATION_06_3_5) == (
        "hybrid",
        "dense-only",
        "bm25-only",
        "hybrid+graph",
    )


def test_arms_of_a_lever_preregistration_lists_reference_families_descriptive() -> None:
    from types import SimpleNamespace

    from lancet_eval import preregistration

    prereg = SimpleNamespace(
        reference_arm="hybrid",
        families=(
            SimpleNamespace(arms=("hybrid+rerank", "hybrid+metadata")),
            SimpleNamespace(arms=("hybrid+rerank", "hybrid+answer-format")),
        ),
        descriptive_arms=("hybrid+all",),
    )
    assert preregistration.arms_of(prereg) == (
        "hybrid",
        "hybrid+rerank",
        "hybrid+metadata",
        "hybrid+answer-format",
        "hybrid+all",
    )


def test_the_lever_classes_are_frozen_dataclasses_with_the_spec_fields() -> None:
    family = [f.name for f in dataclasses.fields(thresholds.FamilySpec)]
    assert family == ["primary", "role", "arms", "alpha"]
    lever = [f.name for f in dataclasses.fields(thresholds.LeverPreRegistration)]
    assert lever == [
        "reference_arm",
        "families",
        "descriptive_arms",
        "test",
        "non_evaluable_rule",
        "population",
        "complete_case_floor",
        "matching_rule",
        "bootstrap_b",
        "bootstrap_seed",
        "null_guard_arms",
        "null_guard_predicate",
        "null_guard_margin",
        "null_guard_min_pair_fraction",
        "answer_mix_strata",
        "sc2_timeout_rate_floor",
        "rerank_degrade_tripwire_rate",
        "rerank_degrade_tripwire_min_calls",
        "rerank_consecutive_degrade_halt",
        "default_rule",
        "provenance",
    ]
    spec = thresholds.FamilySpec(
        primary="answer_usable", role="decisional", arms=("hybrid+rerank",), alpha=0.05
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.alpha = 0.10  # type: ignore[misc]
    assert thresholds.LeverPreRegistration.__dataclass_params__.frozen is True


def test_a_lever_preregistration_is_resolvable_and_names_its_arms() -> None:
    from lancet_eval import preregistration

    prereg = thresholds.LeverPreRegistration(
        reference_arm="hybrid",
        families=(
            thresholds.FamilySpec(
                primary="answer_usable",
                role="decisional",
                arms=("hybrid+rerank", "hybrid+metadata"),
                alpha=0.05,
            ),
            thresholds.FamilySpec(
                primary="paper_hits_at_4",
                role="supporting",
                arms=("hybrid+rerank",),
                alpha=0.05,
            ),
        ),
        descriptive_arms=("hybrid+all", "hybrid+graph"),
        test="paired_sign_flip_exact_two_sided",
        non_evaluable_rule="p=1_m_unchanged",
        population="pairwise_per_comparison",
        complete_case_floor=0.80,
        matching_rule="chunk_id_via_gold_chunks",
        bootstrap_b=10_000,
        bootstrap_seed=42,
        null_guard_arms=("hybrid+metadata",),
        null_guard_predicate="metrics.is_abstention",
        null_guard_margin=0.10,
        null_guard_min_pair_fraction=0.80,
        answer_mix_strata=("comparison_query",),
        sc2_timeout_rate_floor=0.025,
        rerank_degrade_tripwire_rate=0.20,
        rerank_degrade_tripwire_min_calls=50,
        rerank_consecutive_degrade_halt=5,
        default_rule="test",
        provenance="test",
    )
    assert preregistration.arms_of(prereg) == (
        "hybrid",
        "hybrid+rerank",
        "hybrid+metadata",
        "hybrid+all",
        "hybrid+graph",
    )
