"""The 06.3.5 blinded calibration worksheet and its commit-reveal key (D-113, D-120).

The emit is the second step of D-120's ordered judged pass. It runs after the judge
stage (`judge_stage.run_judge_stage`) has finished and before any judged number exists:

1. `emit_worksheet` draws 20 items, seeded and arm-stratified (`draw_slice`), and writes
   the owner-facing worksheet `calibration-worksheet.jsonl` into the run directory.
2. The key file (`slice_id` -> arm, question ID, question type, cache key) and a random
   salt are written only under the gitignored `data/calibration-keys/<run-dir-name>/`.
   The worksheet header carries `key_sha256 = key_digest(salt, key_rows)`.
3. The worksheet is committed (with that digest). The owner scores it and commits the
   scores. Only then are the key and salt revealed (06.3.5-17), and anyone can check
   that `key_digest(salt, key_rows)` still equals the header's digest, so the mapping
   was fixed before scoring. There is never a redraw: the emit refuses to overwrite a
   worksheet, a key or a salt.

`key_digest` is the one hashing function the ingest reuses: it hashes the salt and the
canonical JSON of the PARSED key rows, never file bytes, so an LF or a CRLF checkout of
the key file gives the same digest.

The draw never reads a verdict. An item is eligible whether its cached verdict succeeded
or errored, so judge-error items are not filtered out, and a cache full of errors draws
the same 20 items as a cache full of verdicts. This module makes no API call, computes
no judged statistic and writes no `report.json`.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval import gitcheck, thresholds
from lancet_eval.arms import ARM_REGISTRY, ArmLabel, canonical_arm
from lancet_eval.config import repo_root
from lancet_eval.judge import (
    JUDGE_SYSTEM_V1,
    JudgeCache,
    Score5,
    cache_key,
    truncate_evidence,
)
from lancet_eval.judge_stage import (
    CACHE_FILE,
    STAGE_FILE,
    JudgeStageError,
    JudgeStageRecord,
    load_inputs,
    require_floor_ordering,
    select_population,
)
from lancet_eval.p4 import build_p4
from lancet_eval.score import _is_judgeable

if TYPE_CHECKING:
    from lancet_eval.corpus import GoldQuestion
    from lancet_eval.journal import RunRecord
    from lancet_eval.split import HeldOutSplit

WORKSHEET_FILE = "calibration-worksheet.jsonl"
KEY_FILE = "calibration-key.jsonl"
SALT_FILE = "calibration-salt.txt"

MECHANICS_LINE = (
    "Integers 1–5 for both scores. 2 and 4 lie between the printed anchors. "
    "Grade only against the evidence shown."
)

# AI-SPEC 5 "Draw": per arm, 2 comparison, 2 inference and 1 temporal, so 8 / 8 / 4.
QUOTA: tuple[tuple[str, int], ...] = (
    ("comparison_query", 2),
    ("inference_query", 2),
    ("temporal_query", 1),
)
PER_ARM = sum(n for _, n in QUOTA)
_FILL_ORDER = tuple(t for t, _ in QUOTA)
_RUBRIC_START = "Your job is to grade"
_RUBRIC_END = "\nOutput Format:"


class CalibrationError(Exception):
    """Raised when the calibration emit refuses; nothing is written."""


class CalibrationWorksheetRow(BaseModel):
    """One owner-facing worksheet row (AI-SPEC 4b).

    It has no arm, verdict, cache key, question ID or question type, and
    `extra="forbid"` keeps it that way.

    Attributes:
        slice_id: Opaque `S01`..`S20`.
        question: The gold question text.
        answer: The answer the arm gave.
        evidence: Exactly `truncate_evidence(...)`: what the judge saw.
        human_groundedness: The owner's 1-5 score, blank until scored.
        human_faithfulness: The owner's 1-5 score, blank until scored.
        notes: Free text.
    """

    model_config = ConfigDict(extra="forbid")

    slice_id: str = Field(pattern=r"^S\d{2}$")
    question: str
    answer: str
    evidence: str
    human_groundedness: Score5 | None = None
    human_faithfulness: Score5 | None = None
    notes: str = ""


class CalibrationKeyRow(BaseModel):
    """One key row: which arm, question and cache key a slice ID stands for.

    Attributes:
        slice_id: The worksheet's opaque ID.
        arm: The arm the item was drawn from.
        question_id: The gold question ID.
        question_type: The gold question type.
        cache_key: The judge cache key of the item.
        notes: The empty-cell substitution, if the draw made one.
        shared_arms: Every arm whose eligible record carries the same cache key.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    slice_id: str = Field(pattern=r"^S\d{2}$")
    arm: ArmLabel
    question_id: str
    question_type: str
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    notes: str = ""
    shared_arms: list[str] = Field(default_factory=list)


class CalibrationHeader(BaseModel):
    """The first line of the worksheet.

    Attributes:
        type: Always `header`; the rows carry no `type`.
        corpus: The held-out corpus.
        judge_prompt_version: The judge prompt version.
        judge_model: The judge model.
        seed: The draw seed (`CALIBRATION_DRAW_SEED`).
        emitted_at_sha: HEAD when the worksheet was emitted.
        d114_floor: The trust floor parsed from the blob at `emitted_at_sha`.
        key_sha256: `key_digest(salt, key_rows)`.
        rubric: The rubric block sliced verbatim from the judge prompt.
        mechanics: The one mechanics line.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["header"] = "header"
    corpus: str
    judge_prompt_version: str
    judge_model: str
    seed: int
    emitted_at_sha: str
    d114_floor: float
    key_sha256: str
    rubric: str
    mechanics: str


class DrawnItem(BaseModel):
    """One drawn item with everything the worksheet row and the key row need."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slice_id: str
    arm: str
    question_id: str
    question_type: str
    cache_key: str
    question: str
    answer: str
    evidence: str
    shared_arms: tuple[str, ...]
    notes: str = ""


class EmitResult(BaseModel):
    """What an emit wrote.

    Attributes:
        worksheet_path: The worksheet in the run directory (commit this).
        key_path: The key file under `keys_root` (never committed before the reveal).
        salt_path: The salt file beside it.
        key_sha256: The digest in the worksheet header.
        emitted_at_sha: HEAD at emit.
        n_items: Worksheet rows.
        git_add: The pathspec of the worksheet only.
    """

    model_config = ConfigDict(extra="forbid")

    worksheet_path: Path
    key_path: Path
    salt_path: Path
    key_sha256: str
    emitted_at_sha: str
    n_items: int
    git_add: str


def default_keys_root() -> Path:
    """The gitignored directory the key and salt are written under."""
    return repo_root() / "data" / "calibration-keys"


def rubric_block() -> str:
    """The rubric the owner sees, sliced from the judge's system prompt at emit time.

    It runs from "Your job is to grade" through the faithfulness anchors, so it cannot
    drift from what the judge is shown, and carries nothing the judge never saw.

    Raises:
        CalibrationError: If the prompt no longer holds the two markers.
    """
    start = JUDGE_SYSTEM_V1.find(_RUBRIC_START)
    end = JUDGE_SYSTEM_V1.find(_RUBRIC_END)
    if start < 0 or end <= start:
        raise CalibrationError(
            "JUDGE_SYSTEM_V1 no longer holds the rubric markers the worksheet slices"
        )
    return JUDGE_SYSTEM_V1[start:end].rstrip()


def key_digest(salt: str, rows: Sequence[CalibrationKeyRow]) -> str:
    """The commit-reveal digest: sha256 over the salt and the parsed key rows.

    The input is `salt`, then for each row sorted by `slice_id` a newline and the
    compact, key-sorted JSON of the row. It is computed over the parsed rows, never over
    file bytes, so line endings do not matter.

    Args:
        salt: The hex salt kept beside the key file.
        rows: The key rows, in any order.

    Returns:
        The lower-case hex digest.
    """
    digest = hashlib.sha256()
    digest.update(salt.encode("utf-8"))
    for row in sorted(rows, key=lambda r: r.slice_id):
        canonical = json.dumps(
            row.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest.update(b"\n")
        digest.update(canonical.encode("utf-8"))
    return digest.hexdigest()


def read_key_file(path: Path | str) -> list[CalibrationKeyRow]:
    """Parses a key file, whatever its line endings.

    Args:
        path: A `calibration-key.jsonl`.

    Returns:
        The key rows in file order.
    """
    text = Path(path).read_text(encoding="utf-8")
    return [
        CalibrationKeyRow.model_validate_json(line)
        for line in text.splitlines()
        if line.strip()
    ]


def draw_slice(
    records: Sequence[RunRecord],
    split: HeldOutSplit,
    arms: Sequence[str],
    gold_map: dict[str, GoldQuestion],
    *,
    seed: int,
    prompt_version: str,
    judge_model: str,
) -> list[DrawnItem]:
    """The seeded, arm-stratified draw of the calibration slice (D-113, D-118).

    The pool of each arm is its records whose question is in P4 and that pass
    `_is_judgeable(policy="06.3.5")`, restricted to the three question types. The draw
    uses one `random.Random(seed)` stream, takes arms in registry order and, within an
    arm, comparison, inference, then temporal (2 / 2 / 1), choosing among the arm's
    candidates sorted by question ID whose question and cache key are not yet drawn.
    An empty cell is filled from the arm's other types in the order comparison,
    inference, temporal, and the substitution is recorded in `notes`. Finally the items
    are shuffled with the same stream and named `S01`...

    Args:
        records: Deduplicated journal records of every arm.
        split: The committed held-out split.
        arms: The arms of the corpus (labels or aliases).
        gold_map: Gold questions by ID.
        seed: The draw seed.
        prompt_version: The judge prompt version, part of the cache key.
        judge_model: The judge model, part of the cache key.

    Returns:
        The drawn items, in slice order.

    Raises:
        CalibrationError: If an arm has fewer than 5 eligible items, or the distinctness
            rule leaves an arm with nothing to draw.
    """
    wanted = {canonical_arm(a) for a in arms}
    ordered = [a for a in ARM_REGISTRY if a in wanted]
    if not ordered:
        raise CalibrationError("no arms to draw from")
    p4 = build_p4(records, split, ordered, reference_arm=ordered[0])
    in_p4 = set(p4.question_ids)
    by_slot: dict[tuple[str, str], RunRecord] = {}
    for rec in records:
        arm = canonical_arm(rec.graph_arm)
        if rec.question_id in in_p4 and arm in wanted:
            by_slot[(rec.question_id, arm)] = rec

    quota_types = {t for t, _ in QUOTA}
    candidates: dict[str, list[DrawnItem]] = {arm: [] for arm in ordered}
    key_arms: dict[str, set[str]] = {}
    for arm in ordered:
        for qid in sorted(in_p4):
            rec = by_slot[(qid, arm)]
            if not _is_judgeable(rec, gold_map, policy="06.3.5"):
                continue
            gold = gold_map[qid]
            if gold.question_type not in quota_types:
                continue
            answer = rec.answer or ""
            evidence = truncate_evidence(rec.structured_citations)
            key = cache_key(
                prompt_version=prompt_version,
                judge_model=judge_model,
                question=gold.question,
                answer=answer,
                post_truncation_evidence=evidence,
            )
            key_arms.setdefault(key, set()).add(arm)
            candidates[arm].append(
                DrawnItem(
                    slice_id="S00",
                    arm=arm,
                    question_id=qid,
                    question_type=gold.question_type,
                    cache_key=key,
                    question=gold.question,
                    answer=answer,
                    evidence=evidence,
                    shared_arms=(),
                )
            )

    rng = random.Random(seed)
    used_questions: set[str] = set()
    used_keys: set[str] = set()
    drawn: list[DrawnItem] = []

    def pool(arm: str, qtype: str) -> list[DrawnItem]:
        return [
            c
            for c in candidates[arm]
            if c.question_type == qtype
            and c.question_id not in used_questions
            and c.cache_key not in used_keys
        ]

    for arm in ordered:
        if len(candidates[arm]) < PER_ARM:
            raise CalibrationError(
                f"arm {arm!r} has {len(candidates[arm])} eligible item(s), fewer "
                f"than {PER_ARM}; the slice cannot be drawn"
            )
        for qtype, quota in QUOTA:
            for _ in range(quota):
                options = pool(arm, qtype)
                note = ""
                if not options:
                    for other in _FILL_ORDER:
                        if other == qtype:
                            continue
                        options = pool(arm, other)
                        if options:
                            note = f"empty {qtype} cell filled from {other}"
                            break
                if not options:
                    raise CalibrationError(
                        f"arm {arm!r}: no eligible item left for the {qtype} cell "
                        "after the distinct-question and distinct-key rule"
                    )
                pick = rng.choice(options)
                used_questions.add(pick.question_id)
                used_keys.add(pick.cache_key)
                drawn.append(
                    pick.model_copy(
                        update={
                            "notes": note,
                            "shared_arms": tuple(
                                a for a in ordered if a in key_arms[pick.cache_key]
                            ),
                        }
                    )
                )
    rng.shuffle(drawn)
    return [
        item.model_copy(update={"slice_id": f"S{i:02d}"})
        for i, item in enumerate(drawn, 1)
    ]


def _parse_floor(blob: str, sha: str) -> float:
    """Reads the trust floor out of a committed thresholds.py without running it."""
    try:
        tree = ast.parse(blob)
    except SyntaxError as exc:
        raise CalibrationError(
            f"thresholds.py at {sha[:12]} does not parse, so the calibration floor "
            "cannot be read"
        ) from exc
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name, value = node.targets[0].id, node.value
        else:
            continue
        if (
            name == gitcheck.TRUST_FLOOR_TOKEN
            and isinstance(value, ast.Constant)
            and isinstance(value.value, int | float)
            and not isinstance(value.value, bool)
        ):
            return float(value.value)
    raise CalibrationError(
        f"thresholds.py at {sha[:12]} defines no calibration floor "
        f"({gitcheck.TRUST_FLOOR_TOKEN})"
    )


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    tmp.replace(path)


def _read_stage(run: Path) -> JudgeStageRecord:
    path = run / STAGE_FILE
    if not path.is_file():
        raise CalibrationError(
            f"{STAGE_FILE} is missing from {run}: run `lancet-eval judge` to "
            "completion first (D-120 step 1)"
        )
    try:
        stage = JudgeStageRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CalibrationError(f"{STAGE_FILE} cannot be read: {exc}") from exc
    if stage.mode != "heldout":
        raise CalibrationError(
            f"{STAGE_FILE} records a {stage.mode} stage; the worksheet is drawn from "
            "the held-out stage only"
        )
    if stage.stop_reason is not None:
        raise CalibrationError(
            f"the judge stage stopped early ({stage.stop_reason}); finish it under a "
            "new D-86 checkpoint before emitting"
        )
    return stage


def emit_worksheet(
    run_dir: Path | str,
    *,
    keys_root: Path | None = None,
    git_repo: Path | None = None,
) -> EmitResult:
    """Draws the slice and writes the worksheet, the key and the salt (D-113, D-120).

    Nothing is written unless every check passes; the worksheet goes in last, and a
    failure to write it removes the key and salt again.

    Args:
        run_dir: A closed run directory whose judge stage completed.
        keys_root: Where `<run-dir-name>/` holds the key and salt; the gitignored
            `data/calibration-keys/` when None.
        git_repo: Repository `emitted_at_sha` and the floor blob are read from; the live
            repository when None.

    Returns:
        The paths, the key digest and the worksheet's `git add` pathspec.

    Raises:
        CalibrationError: If a worksheet, key or salt already exists, the journal is
            open, the judge stage is missing, a rehearsal or stopped early, a judgeable
            held-out record has no cache entry, the D-73 ordering or the floor check
            fails, or the draw is impossible.
    """
    run = Path(run_dir)
    root = Path(keys_root) if keys_root is not None else default_keys_root()
    worksheet_path = run / WORKSHEET_FILE
    key_dir = root / run.name
    key_path = key_dir / KEY_FILE
    salt_path = key_dir / SALT_FILE
    for existing in (worksheet_path, key_path, salt_path):
        if existing.exists():
            raise CalibrationError(
                f"{existing} already exists: the slice is drawn once and never "
                "redrawn (D-113)"
            )
    try:
        inputs = load_inputs(run, rehearsal=False)
        _read_stage(run)
        require_floor_ordering(inputs.header, git_repo)
    except JudgeStageError as exc:
        raise CalibrationError(str(exc)) from exc

    cache = JudgeCache(run / CACHE_FILE)
    missing = {i.key for i in select_population(inputs) if cache.get(i.key) is None}
    if missing:
        raise CalibrationError(
            f"{len(missing)} judgeable held-out key(s) have no cache entry: the judge "
            "stage is incomplete (D-120 step 3)"
        )

    config = inputs.config
    items = draw_slice(
        inputs.records,
        inputs.split,
        config.arms,
        inputs.gold_map,
        seed=thresholds.CALIBRATION_DRAW_SEED,
        prompt_version=config.judge_prompt_version,
        judge_model=config.judge_model,
    )
    try:
        sha = gitcheck.head_sha(repo=git_repo)
        blob = gitcheck.show_blob(sha, gitcheck.THRESHOLDS_PATH, repo=git_repo)
    except gitcheck.GitCheckError as exc:
        raise CalibrationError(f"git could not supply the floor blob: {exc}") from exc
    floor = _parse_floor(blob, sha)
    if floor != thresholds.JUDGE_QWK_TRUST_FLOOR:
        raise CalibrationError(
            f"the calibration floor at {sha[:12]} ({floor}) differs from the "
            f"committed constant ({thresholds.JUDGE_QWK_TRUST_FLOOR})"
        )

    key_rows = [
        CalibrationKeyRow(
            slice_id=i.slice_id,
            arm=i.arm,
            question_id=i.question_id,
            question_type=i.question_type,
            cache_key=i.cache_key,
            notes=i.notes,
            shared_arms=list(i.shared_arms),
        )
        for i in items
    ]
    salt = secrets.token_hex(32)
    digest = key_digest(salt, key_rows)
    header = CalibrationHeader(
        corpus=config.name,
        judge_prompt_version=config.judge_prompt_version,
        judge_model=config.judge_model,
        seed=thresholds.CALIBRATION_DRAW_SEED,
        emitted_at_sha=sha,
        d114_floor=floor,
        key_sha256=digest,
        rubric=rubric_block(),
        mechanics=MECHANICS_LINE,
    )
    worksheet_lines = [header.model_dump_json()] + [
        CalibrationWorksheetRow(
            slice_id=i.slice_id,
            question=i.question,
            answer=i.answer,
            evidence=i.evidence,
        ).model_dump_json()
        for i in items
    ]

    key_dir.mkdir(parents=True, exist_ok=True)
    try:
        _write_atomic(salt_path, salt + "\n")
        _write_atomic(
            key_path, "".join(r.model_dump_json() + "\n" for r in key_rows)
        )
        _write_atomic(worksheet_path, "\n".join(worksheet_lines) + "\n")
    except BaseException:
        for partial in (salt_path, key_path, worksheet_path):
            partial.unlink(missing_ok=True)
        raise
    try:
        shown = worksheet_path.resolve().relative_to(repo_root().resolve()).as_posix()
    except ValueError:
        shown = str(worksheet_path)
    return EmitResult(
        worksheet_path=worksheet_path,
        key_path=key_path,
        salt_path=salt_path,
        key_sha256=digest,
        emitted_at_sha=sha,
        n_items=len(items),
        git_add=f"git add {shown}",
    )
