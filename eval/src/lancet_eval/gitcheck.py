"""List-form git helpers for the D-73 pre-registration ordering gates (06.3.5-08).

Every git call of the pre-registration and calibration ordering gates goes through this
module: `subprocess.run([...], cwd=<repo>, shell=False, ...)`, with no argument ever
interpolated into a shell string. Every function takes a keyword-only `repo` that
defaults to `config.repo_root()`, so a test points it at a throwaway repository in
`tmp_path` and never queries the live one.

Committed blobs are read with `git show`, never from the working copy, because a
Windows checkout with `core.autocrlf=true` holds CRLF bytes that differ from the
committed object (06.3.5 RESEARCH Pitfall 1). The ordering gates read module attributes
at call time (`gitcheck.is_clean(...)`), so a test can monkeypatch them.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from lancet_eval.config import repo_root

THRESHOLDS_PATH = "eval/src/lancet_eval/thresholds.py"
SOURCE_DIR = "eval/src/lancet_eval"
# The tokens whose introducing commit is the D-73 pre-registration (06.3.5-08). They are
# looked up by `git log -S`, so they name constants in THRESHOLDS_PATH.
PREREGISTRATION_TOKEN = "PREREGISTRATION_06_3_5"
TRUST_FLOOR_TOKEN = "JUDGE_QWK_TRUST_FLOOR"

_GIT_TIMEOUT_S = 60
_REV = re.compile(r"^(HEAD|[0-9a-f]{4,64})$")
# These override `cwd` and would point a call at the live repository from a test that
# runs inside a git hook.
_LEAKY_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


class GitCheckError(RuntimeError):
    """Raised when a git call fails unexpectedly, so an ordering cannot be proven."""


class PreregistrationError(ValueError):
    """Raised by `drive` when the D-73 pre-registration ordering does not hold."""


def _run(
    args: list[str], *, repo: Path | None, ok_codes: tuple[int, ...] = (0,)
) -> subprocess.CompletedProcess[str]:
    cwd = repo_root() if repo is None else Path(repo)
    env = {k: v for k, v in os.environ.items() if k not in _LEAKY_ENV}
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=cwd,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitCheckError(f"git {' '.join(args)} could not run: {exc}") from exc
    if res.returncode not in ok_codes:
        raise GitCheckError(
            f"git {' '.join(args)} exited {res.returncode}: {res.stderr.strip()}"
        )
    return res


def _require_rev(rev: str) -> str:
    if not _REV.fullmatch(rev):
        raise GitCheckError(f"not a commit id or HEAD: {rev!r}")
    return rev


def _require_plain(value: str, what: str) -> str:
    if not value or value.startswith("-") or "\x00" in value:
        raise GitCheckError(f"invalid {what}: {value!r}")
    return value


def head_sha(*, repo: Path | None = None) -> str:
    """Returns the full sha of HEAD."""
    return _run(["rev-parse", "HEAD"], repo=repo).stdout.strip()


def introducing_commit(
    token: str, path: str, *, repo: Path | None = None
) -> str | None:
    """Returns the oldest commit that added `token` to `path`, or None.

    Uses `git log -S <token> --reverse`, so the first line is the commit where the
    token first appeared.

    Args:
        token: The literal string to look for.
        path: Repo-relative path the search is limited to.
        repo: Repository to query; the live repository when None.

    Returns:
        The full sha, or None when no commit changed the token's occurrence count.
    """
    _require_plain(token, "token")
    _require_plain(path, "path")
    res = _run(["log", f"-S{token}", "--format=%H", "--reverse", "--", path], repo=repo)
    lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
    return lines[0] if lines else None


def commit_time(sha: str, *, repo: Path | None = None) -> int:
    """Returns a commit's committer time as epoch seconds."""
    res = _run(["show", "-s", "--format=%ct", _require_rev(sha)], repo=repo)
    try:
        return int(res.stdout.strip())
    except ValueError as exc:
        raise GitCheckError(
            f"unreadable commit time for {sha}: {res.stdout!r}"
        ) from exc


def is_ancestor(ancestor: str, descendant: str, *, repo: Path | None = None) -> bool:
    """Whether `ancestor` is an ancestor of (or equal to) `descendant`."""
    res = _run(
        [
            "merge-base",
            "--is-ancestor",
            _require_rev(ancestor),
            _require_rev(descendant),
        ],
        repo=repo,
        ok_codes=(0, 1),
    )
    return res.returncode == 0


def is_tracked(path: str, *, repo: Path | None = None) -> bool:
    """Whether `path` is tracked in the index."""
    _require_plain(path, "path")
    res = _run(["ls-files", "--error-unmatch", "--", path], repo=repo, ok_codes=(0, 1))
    return res.returncode == 0


def is_clean(*paths: str, repo: Path | None = None) -> bool:
    """Whether `git status --porcelain` is empty for `paths` (all of the tree if none).

    An untracked file under a path counts as a change.
    """
    for p in paths:
        _require_plain(p, "path")
    args = ["status", "--porcelain"]
    if paths:
        args += ["--", *paths]
    return _run(args, repo=repo).stdout.strip() == ""


def show_blob(sha: str, path: str, *, repo: Path | None = None) -> str:
    """Returns a committed file's text, LF-normalised, read from the git object."""
    _require_plain(path, "path")
    res = _run(["show", f"{_require_rev(sha)}:{path}"], repo=repo)
    return res.stdout.replace("\r\n", "\n")


def last_commit_touching(path: str, *, repo: Path | None = None) -> str | None:
    """Returns the newest commit that touched `path`, or None when none did."""
    _require_plain(path, "path")
    res = _run(["log", "-1", "--format=%H", "--", path], repo=repo)
    sha = res.stdout.strip()
    return sha or None


def first_commit_adding(path: str, *, repo: Path | None = None) -> str | None:
    """Returns the oldest commit that added `path`, or None when none did.

    Uses `git log --diff-filter=A --reverse`, so it is the commit where the file first
    entered history, whatever later commits changed it.

    Args:
        path: Repo-relative path.
        repo: Repository to query; the live repository when None.

    Returns:
        The full sha, or None when `path` was never added.
    """
    _require_plain(path, "path")
    res = _run(
        ["log", "--diff-filter=A", "--reverse", "--format=%H", "--", path], repo=repo
    )
    lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
    return lines[0] if lines else None


def preregistration_problems(
    tokens: tuple[str, ...],
    *,
    created_at: float | None = None,
    require_clean_tree: bool = False,
    repo: Path | None = None,
) -> list[str]:
    """Why the D-73 ordering does not hold, one sentence per problem (empty if it does).

    For each token: a commit in THRESHOLDS_PATH introduces it, that commit is an
    ancestor of HEAD, and, when `created_at` is given, its commit time is strictly
    earlier than `created_at` (the journal header's epoch seconds). With
    `require_clean_tree`, SOURCE_DIR must have no uncommitted change.

    Args:
        tokens: Constants of THRESHOLDS_PATH that must have been committed first.
        created_at: Epoch seconds the data was created; None skips the time check.
        require_clean_tree: Also refuse a dirty SOURCE_DIR.
        repo: Repository to query; the live repository when None.

    Returns:
        The problems found.

    Raises:
        GitCheckError: If a git call fails, so the ordering cannot be proven.
    """
    problems: list[str] = []
    head = head_sha(repo=repo)
    for token in tokens:
        sha = introducing_commit(token, THRESHOLDS_PATH, repo=repo)
        if sha is None:
            problems.append(f"no commit in {THRESHOLDS_PATH} introduces {token}")
            continue
        if not is_ancestor(sha, head, repo=repo):
            problems.append(
                f"the commit introducing {token} ({sha[:12]}) is not an ancestor "
                "of HEAD"
            )
        if created_at is not None and not commit_time(sha, repo=repo) < created_at:
            problems.append(
                f"the commit introducing {token} ({sha[:12]}) is not older than the "
                "journal header's created_at"
            )
    if require_clean_tree and not is_clean(SOURCE_DIR, repo=repo):
        problems.append(f"{SOURCE_DIR} has an uncommitted change")
    return problems
