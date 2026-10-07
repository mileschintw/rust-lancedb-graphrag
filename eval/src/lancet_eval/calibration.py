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
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lancet_eval import agreement, gitcheck, thresholds
from lancet_eval.agreement import (
    AgreementResult,
    quadratic_weighted_kappa,
    spearman_rank_correlation,
)
from lancet_eval.arms import ARM_REGISTRY, ArmLabel, canonical_arm
from lancet_eval.config import repo_root
from lancet_eval.gate import AGREEMENT_TARGET
from lancet_eval.judge import (
    JUDGE_SYSTEM_V1,
    JudgeCache,
    JudgeVerdict,
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
from lancet_eval.stats import BOOTSTRAP_B, BOOTSTRAP_SEED

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


# --- 06.3.5-12: the ordered ingest, agreement and the D-114 labels -------------
#
# `ingest_and_verify` is step 7 of D-120. It proves from git, never from a timestamp,
# that the worksheet was emitted first, scored second and had its key revealed third,
# with the trust floor committed before the worksheet existed. Only a slice that passes
# is handed to `agreement_summary`, which computes judge-human agreement and labels each
# dimension by the D-114 rule alone. Nothing here makes an API call or writes a report.

SLICE_SIZE = PER_ARM * len(ARM_REGISTRY)

LABEL_CALIBRATED = "calibrated"
LABEL_UNCALIBRATED = "uncalibrated"
LABEL_ATTRITION = "uncalibrated: slice attrition"
LABEL_QWK_UNDEFINED = "uncalibrated: QWK undefined"
# D-126: the report carries the label only as a float code; the text is in the sidecar.
LABEL_CODES: dict[str, float] = {
    LABEL_CALIBRATED: 1.0,
    LABEL_UNCALIBRATED: 0.0,
    LABEL_ATTRITION: -1.0,
    LABEL_QWK_UNDEFINED: -2.0,
}
DIMENSIONS = ("groundedness", "faithfulness")
_NO_PAIRS_STATE = "undefined_no_pairs"
_LEGACY_PREFIX = "legacy (06.3), non-governing"


class SlicePair(BaseModel):
    """One scored slice item joined to its key row (06.3.5-12).

    Attributes:
        slice_id: The worksheet's opaque ID.
        arm: The arm the item was drawn from (revealed by the key).
        question_id: The gold question ID.
        question_type: The gold question type.
        cache_key: The judge cache key of the item.
        human_groundedness: The owner's integer 1-5 score.
        human_faithfulness: The owner's integer 1-5 score.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    slice_id: str
    arm: str
    question_id: str
    question_type: str
    cache_key: str
    human_groundedness: int
    human_faithfulness: int


class VerifiedSlice(BaseModel):
    """A worksheet whose emit, scoring and reveal order is proven from git.

    Attributes:
        header: The worksheet header.
        pairs: The scored items joined to the key, in worksheet order.
        floor: The trust floor, equal in the header, at the emit commit and now.
        emitted_at_sha: HEAD when the worksheet was emitted.
        worksheet_commit: The commit that first added the worksheet (all scores null).
        scores_commit: The last commit touching the worksheet (the owner's scores).
        key_commit: The commit that first added the key file.
        salt_commit: The commit that first added the salt file.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CalibrationHeader
    pairs: tuple[SlicePair, ...]
    floor: float
    emitted_at_sha: str
    worksheet_commit: str = ""
    scores_commit: str = ""
    key_commit: str = ""
    salt_commit: str = ""


class LegacyLine(BaseModel):
    """The legacy `calibration_state` of one dimension, for display only (D-119).

    Attributes:
        text: The printed line, labelled "legacy (06.3), non-governing".
        satisfied: Whether QWK and Spearman are both at or above `AGREEMENT_TARGET`.
        divergence: The one-line disagreement notice, or None when the gates agree.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    satisfied: bool
    divergence: str | None = None


def d114_label(qwk_result: AgreementResult, n_pairs: int, floor: float) -> str:
    """The D-114 label of one dimension, from the rule alone (AI-SPEC 5, D-119).

    The conditions are checked in this order: an undefined QWK, fewer than
    `CALIBRATION_MIN_SCORED_PAIRS` scored pairs, a QWK point estimate below `floor`,
    otherwise calibrated. The point estimate at exactly `floor` reads calibrated. The
    CI is disclosed elsewhere and never decides.

    Args:
        qwk_result: The QWK point estimate and its state.
        n_pairs: Scored pairs after judge-error attrition.
        floor: The trust floor (`JUDGE_QWK_TRUST_FLOOR`).

    Returns:
        One of the four `LABEL_*` strings.
    """
    if qwk_result.state == "undefined_expected_agreement":
        return LABEL_QWK_UNDEFINED
    if n_pairs < thresholds.CALIBRATION_MIN_SCORED_PAIRS:
        return LABEL_ATTRITION
    if qwk_result.value is None or qwk_result.value < floor:
        return LABEL_UNCALIBRATED
    return LABEL_CALIBRATED


def label_code(label: str) -> float:
    """The float code `report.json` carries for a D-114 label (D-126).

    Raises:
        KeyError: If `label` is not one of the four labels.
    """
    return LABEL_CODES[label]


def _fmt(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.4f}"


def legacy_calibration_line(
    dimension: str, qwk: float | None, spearman: float | None, label: str
) -> LegacyLine:
    """The legacy gate for one dimension, for display only, and where it disagrees.

    The legacy `calibration_state` (06.3) is satisfied when QWK and Spearman are both at
    or above `gate.AGREEMENT_TARGET`. It gates nothing in 06.3.5 (D-119); this only
    prints it and says so when it differs from the D-114 label.

    Args:
        dimension: `groundedness` or `faithfulness`.
        qwk: The QWK point estimate, or None when undefined.
        spearman: Spearman rho, or None when undefined.
        label: The D-114 label of the dimension.

    Returns:
        The printed line, whether the legacy rule is satisfied, and the divergence line.
    """
    satisfied = (
        qwk is not None
        and spearman is not None
        and qwk >= AGREEMENT_TARGET
        and spearman >= AGREEMENT_TARGET
    )
    state = "satisfied" if satisfied else "below_target"
    text = (
        f"{_LEGACY_PREFIX}: calibration_state for {dimension} = {state} "
        f"(QWK {_fmt(qwk)}, Spearman {_fmt(spearman)}, target {AGREEMENT_TARGET:.2f})"
    )
    divergence = None
    if satisfied != (label == LABEL_CALIBRATED):
        divergence = (
            f"legacy calibration_state and D-114 disagree for {dimension}; "
            "D-114 governs"
        )
    return LegacyLine(text=text, satisfied=satisfied, divergence=divergence)


def _human(pair: SlicePair, dimension: str) -> int:
    return (
        pair.human_groundedness
        if dimension == "groundedness"
        else pair.human_faithfulness
    )


def _dimension_summary(
    dimension: str, scored: Sequence[tuple[SlicePair, int]], floor: float
) -> dict[str, Any]:
    """Agreement of one dimension over the scored pairs `(pair, judge score)`."""
    human = [_human(p, dimension) for p, _ in scored]
    judge = [j for _, j in scored]
    n = len(scored)
    if n:
        qwk_res = quadratic_weighted_kappa(human, judge, min_rating=1, max_rating=5)
        rho_res = spearman_rank_correlation(human, judge)
        qwk_ci, qwk_dropped = agreement.bootstrap_agreement_ci_counted(
            human,
            judge,
            "kappa",
            min_rating=1,
            max_rating=5,
            seed=BOOTSTRAP_SEED,
            b=BOOTSTRAP_B,
        )
        rho_ci, rho_dropped = agreement.bootstrap_agreement_ci_counted(
            human,
            judge,
            "spearman",
            seed=BOOTSTRAP_SEED,
            b=BOOTSTRAP_B,
        )
    else:
        qwk_res = AgreementResult(value=None, state=_NO_PAIRS_STATE)
        rho_res = AgreementResult(value=None, state=_NO_PAIRS_STATE)
        qwk_ci = rho_ci = None
        qwk_dropped = rho_dropped = 0
    label = d114_label(qwk_res, n, floor)
    legacy = legacy_calibration_line(dimension, qwk_res.value, rho_res.value, label)
    per_arm: dict[str, dict[str, int]] = {}
    for arm in ARM_REGISTRY:
        in_arm = [
            (h, j) for (p, j), h in zip(scored, human, strict=True) if p.arm == arm
        ]
        per_arm[arm] = {
            "n": len(in_arm),
            "exact": sum(1 for h, j in in_arm if h == j),
        }
    pairs = list(zip(human, judge, strict=True))
    return {
        "n_pairs": n,
        "qwk": qwk_res.value,
        "qwk_state": qwk_res.state,
        "qwk_ci_lower": qwk_ci[0] if qwk_ci else None,
        "qwk_ci_upper": qwk_ci[1] if qwk_ci else None,
        "qwk_dropped_resamples": qwk_dropped,
        "spearman": rho_res.value,
        "spearman_state": rho_res.state,
        "spearman_ci_lower": rho_ci[0] if rho_ci else None,
        "spearman_ci_upper": rho_ci[1] if rho_ci else None,
        "spearman_dropped_resamples": rho_dropped,
        "exact_agreement": (sum(h == j for h, j in pairs) / n) if n else None,
        "mad": (sum(abs(h - j) for h, j in pairs) / n) if n else None,
        "mean_signed_difference": (sum(j - h for h, j in pairs) / n) if n else None,
        "judge_marginals": {str(v): judge.count(v) for v in range(1, 6)},
        "human_marginals": {str(v): human.count(v) for v in range(1, 6)},
        "joint_5_5_share": (sum(h == 5 and j == 5 for h, j in pairs) / n)
        if n
        else None,
        "per_arm_exact_agreement": per_arm,
        "floor": floor,
        "label": label,
        "label_code": label_code(label),
        "legacy_line": legacy.text,
        "legacy_satisfied": legacy.satisfied,
        "divergence_line": legacy.divergence,
    }


def agreement_summary(verified: VerifiedSlice, cache: JudgeCache) -> dict[str, Any]:
    """Judge-human agreement per dimension on a verified slice (D-113, D-114, D-119).

    A slice item whose cache entry is an error is dropped (attrition) and its slice ID
    listed; nothing is redrawn. Both CIs are the seeded percentile bootstrap at
    `stats.BOOTSTRAP_B` resamples, passed explicitly, with the count of resamples
    dropped as undefined. Each dimension carries its D-114 label and its float code.

    Args:
        verified: The result of `ingest_and_verify`.
        cache: The run's judge cache.

    Returns:
        `{n_slice, dropped_slice_ids, dimensions: {groundedness, faithfulness},
        legacy_lines, divergence_lines}`; every value is JSON-serialisable.

    Raises:
        CalibrationError: If a pair's cache key has no entry in the cache.
    """
    verdicts: dict[str, JudgeVerdict | None] = {}
    for pair in verified.pairs:
        entry = cache.get(pair.cache_key)
        if entry is None:
            raise CalibrationError(
                f"slice item {pair.slice_id} has no judge cache entry for cache_key "
                f"{pair.cache_key[:12]}"
            )
        verdicts[pair.slice_id] = entry.verdict
    dropped = [p.slice_id for p in verified.pairs if verdicts[p.slice_id] is None]
    dimensions: dict[str, dict[str, Any]] = {}
    for dimension in DIMENSIONS:
        scored: list[tuple[SlicePair, int]] = []
        for pair in verified.pairs:
            verdict = verdicts[pair.slice_id]
            if verdict is None:
                continue
            judge = (
                verdict.groundedness
                if dimension == "groundedness"
                else verdict.faithfulness
            )
            scored.append((pair, judge))
        dimensions[dimension] = _dimension_summary(dimension, scored, verified.floor)
    return {
        "n_slice": len(verified.pairs),
        "dropped_slice_ids": dropped,
        "dimensions": dimensions,
        "legacy_lines": [dimensions[d]["legacy_line"] for d in DIMENSIONS],
        "divergence_lines": [
            dimensions[d]["divergence_line"]
            for d in DIMENSIONS
            if dimensions[d]["divergence_line"] is not None
        ],
    }


def _repo_relative(path: Path, repo: Path, what: str) -> str:
    """The repo-relative POSIX path git needs; refuses a path outside the repository."""
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise CalibrationError(
            f"the {what} {path} is not inside the repository {repo}, so git cannot "
            "prove when it was committed"
        ) from exc


def _score_problem(row: dict[str, Any]) -> str | None:
    """Why a worksheet row's two scores are not both integers 1-5, or None."""
    for field in ("human_groundedness", "human_faithfulness"):
        value = row.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= 5
        ):
            return (
                f"the human score of {row.get('slice_id')} ({field}) is {value!r}; "
                "every score must be an integer from 1 to 5"
            )
    return None


def _split_worksheet(
    text: str, what: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    try:
        header_raw = json.loads(lines[0])
        rows = [json.loads(ln) for ln in lines[1:]]
    except (IndexError, ValueError) as exc:
        raise CalibrationError(
            f"the {what} is not a header line then JSONL rows"
        ) from exc
    if not isinstance(header_raw, dict) or not all(isinstance(r, dict) for r in rows):
        raise CalibrationError(f"the {what} is not a header line then JSONL rows")
    return header_raw, rows


def ingest_and_verify(
    run_dir: Path | str,
    worksheet_path: Path | str,
    key_path: Path | str,
    salt_path: Path | str,
    *,
    repo: Path | None = None,
) -> VerifiedSlice:
    """Step 7 of D-120: proves emit -> owner scores -> reveal from git, then joins.

    The ordering evidence is commit ancestry. The worksheet's first commit E holds all
    scores null and its header and row texts never change afterwards; its last commit C
    (the owner's scores) is a descendant of E and of the header's `emitted_at_sha`; the
    key file and the salt file were each first committed strictly after C; and
    `key_digest(salt, key rows)` equals the header's `key_sha256`. The trust floor
    parsed from `git show <emitted_at_sha>:thresholds.py` must equal the header's and
    the current constant. Every `slice_id` must join the key and every key `cache_key`
    the cache, and every judgeable held-out record must have a cache entry (today's
    legacy ingest silently excludes an unmatched row; here it is a refusal).

    A slice item whose cache entry is an error is not a refusal: `agreement_summary`
    drops it as attrition. Nothing is written and no API call is made.

    Args:
        run_dir: The closed run directory holding the journal and `judge_cache.json`.
        worksheet_path: The scored `calibration-worksheet.jsonl`, tracked and clean.
        key_path: The revealed key file, tracked and clean.
        salt_path: The revealed salt file, tracked and clean.
        repo: Repository the evidence is read from; the live repository when None.

    Returns:
        The joined, scored pairs with the commits that prove the order.

    Raises:
        CalibrationError: Naming the first condition that does not hold.
    """
    run = Path(run_dir)
    root = Path(repo) if repo is not None else repo_root()
    files = {
        "worksheet": Path(worksheet_path),
        "key file": Path(key_path),
        "salt file": Path(salt_path),
    }
    for what, path in files.items():
        if not path.is_file():
            raise CalibrationError(f"the {what} {path} does not exist")
    rel = {what: _repo_relative(path, root, what) for what, path in files.items()}
    try:
        return _verify_order(run, root, files, rel)
    except gitcheck.GitCheckError as exc:
        raise CalibrationError(f"git could not prove the ordering: {exc}") from exc


def _verify_order(
    run: Path, root: Path, files: dict[str, Path], rel: dict[str, str]
) -> VerifiedSlice:
    for what, name in rel.items():
        if not gitcheck.is_tracked(name, repo=root):
            raise CalibrationError(f"the {what} {name} is not tracked by git")
    for what, name in rel.items():
        if not gitcheck.is_clean(name, repo=root):
            raise CalibrationError(f"the {what} {name} has an uncommitted change")

    header_raw, rows = _split_worksheet(
        files["worksheet"].read_text(encoding="utf-8"), "worksheet"
    )
    try:
        header = CalibrationHeader.model_validate(header_raw)
    except ValueError as exc:
        raise CalibrationError(f"the worksheet header is invalid: {exc}") from exc
    if len(rows) != SLICE_SIZE:
        raise CalibrationError(
            f"the worksheet holds {len(rows)} rows; the slice has {SLICE_SIZE}"
        )
    for row in rows:
        problem = _score_problem(row)
        if problem is not None:
            raise CalibrationError(problem)
    try:
        parsed_rows = [CalibrationWorksheetRow.model_validate(r) for r in rows]
    except ValueError as exc:
        raise CalibrationError(f"a worksheet row is invalid: {exc}") from exc
    if len({r.slice_id for r in parsed_rows}) != len(parsed_rows):
        raise CalibrationError("the worksheet repeats a slice_id")

    # emit -> scores: E holds no score, C descends from E and from the emit commit.
    worksheet_rel = rel["worksheet"]
    first = gitcheck.first_commit_adding(worksheet_rel, repo=root)
    last = gitcheck.last_commit_touching(worksheet_rel, repo=root)
    if first is None or last is None:
        raise CalibrationError(f"no commit holds the worksheet {worksheet_rel}")
    first_header, first_rows = _split_worksheet(
        gitcheck.show_blob(first, worksheet_rel, repo=root),
        "worksheet at its first commit",
    )
    if any(
        r.get("human_groundedness") is not None
        or r.get("human_faithfulness") is not None
        for r in first_rows
    ):
        raise CalibrationError(
            f"the worksheet carries scores in {first[:12]}, the commit that first "
            "added it; the scores must be committed after the emit (D-113)"
        )
    if last == first:
        raise CalibrationError(
            "the worksheet was never committed again after it was first added, so "
            "the owner's scores are not in git"
        )
    if not gitcheck.is_ancestor(first, last, repo=root):
        raise CalibrationError(
            f"the scores commit {last[:12]} is not a descendant of the worksheet's "
            f"first commit {first[:12]}"
        )
    if not gitcheck.is_ancestor(header.emitted_at_sha, last, repo=root):
        raise CalibrationError(
            f"the header's emitted_at_sha {header.emitted_at_sha[:12]} is not an "
            f"ancestor of the scores commit {last[:12]}"
        )

    # scores -> reveal: the key and the salt first appear strictly after C.
    revealed: dict[str, str] = {}
    for what in ("key file", "salt file"):
        added = gitcheck.first_commit_adding(rel[what], repo=root)
        if added is None:
            raise CalibrationError(f"no commit adds the {what} {rel[what]}")
        if added == last or not gitcheck.is_ancestor(last, added, repo=root):
            raise CalibrationError(
                f"the {what} was first committed in {added[:12]}, no later than the "
                f"scores commit {last[:12]}; it must be revealed after the scores "
                "(D-120)"
            )
        revealed[what] = added

    # nothing the owner was shown changed between the emit commit and the scores.
    try:
        first_header_model = CalibrationHeader.model_validate(first_header)
    except ValueError as exc:
        raise CalibrationError(f"the first worksheet header is invalid: {exc}") from exc
    if first_header_model != header:
        raise CalibrationError(
            "the worksheet header changed after the first commit; the digest, the "
            "floor and the emit commit must be the ones committed with the emit"
        )
    shown = ("slice_id", "question", "answer", "evidence")
    original = {r.get("slice_id"): {k: r.get(k) for k in shown} for r in first_rows}
    current = {r.slice_id: {k: getattr(r, k) for k in shown} for r in parsed_rows}
    if original != current:
        raise CalibrationError(
            "a worksheet row's question, answer or evidence changed after the first "
            "commit"
        )

    # the floor was committed before the worksheet existed (D-114, D-119).
    blob = gitcheck.show_blob(
        header.emitted_at_sha, gitcheck.THRESHOLDS_PATH, repo=root
    )
    floor = _parse_floor(blob, header.emitted_at_sha)
    if floor != header.d114_floor or floor != thresholds.JUDGE_QWK_TRUST_FLOOR:
        raise CalibrationError(
            f"the calibration floor at the emit commit {header.emitted_at_sha[:12]} "
            f"({floor}) differs from the worksheet header ({header.d114_floor}) or "
            f"from the current JUDGE_QWK_TRUST_FLOOR "
            f"({thresholds.JUDGE_QWK_TRUST_FLOOR})"
        )

    # commit-reveal: the key and salt are the ones the header hashed.
    salt = files["salt file"].read_text(encoding="utf-8").strip()
    try:
        key_rows = read_key_file(files["key file"])
    except ValueError as exc:
        raise CalibrationError(f"the key file cannot be read: {exc}") from exc
    digest = key_digest(salt, key_rows)
    if digest != header.key_sha256:
        raise CalibrationError(
            f"key digest mismatch: sha256 of the revealed salt and key is "
            f"{digest[:16]}..., the worksheet header committed "
            f"{header.key_sha256[:16]}..."
        )

    # every slice_id joins the key and every cache_key joins the cache.
    by_slice = {k.slice_id: k for k in key_rows}
    if len(by_slice) != len(key_rows):
        raise CalibrationError("the key file repeats a slice_id")
    for row in parsed_rows:
        if row.slice_id not in by_slice:
            raise CalibrationError(
                f"slice_id {row.slice_id} is not in the key file; today's legacy "
                "ingest would silently exclude it"
            )
    worksheet_ids = {r.slice_id for r in parsed_rows}
    for slice_id in sorted(by_slice):
        if slice_id not in worksheet_ids:
            raise CalibrationError(f"key slice_id {slice_id} is not in the worksheet")
    cache = JudgeCache(run / CACHE_FILE)
    for row in parsed_rows:
        key = by_slice[row.slice_id]
        if cache.get(key.cache_key) is None:
            raise CalibrationError(
                f"slice item {row.slice_id} (cache_key {key.cache_key[:12]}) has no "
                "judge cache entry"
            )

    # the judge stage was complete: every judgeable held-out record has an entry.
    try:
        inputs = load_inputs(run, rehearsal=False)
    except JudgeStageError as exc:
        raise CalibrationError(str(exc)) from exc
    config = inputs.config
    if (
        header.corpus != config.name
        or header.judge_prompt_version != config.judge_prompt_version
        or header.judge_model != config.judge_model
    ):
        raise CalibrationError(
            "the worksheet header's corpus, judge model or prompt version differs "
            "from the run's corpus configuration"
        )
    missing = {i.key for i in select_population(inputs) if cache.get(i.key) is None}
    if missing:
        raise CalibrationError(
            f"{len(missing)} judgeable held-out key(s) without a judge cache entry: "
            "the judge stage is incomplete (D-120 step 3)"
        )

    pairs = tuple(
        SlicePair(
            slice_id=row.slice_id,
            arm=by_slice[row.slice_id].arm,
            question_id=by_slice[row.slice_id].question_id,
            question_type=by_slice[row.slice_id].question_type,
            cache_key=by_slice[row.slice_id].cache_key,
            human_groundedness=int(row.human_groundedness or 0),
            human_faithfulness=int(row.human_faithfulness or 0),
        )
        for row in parsed_rows
    )
    return VerifiedSlice(
        header=header,
        pairs=pairs,
        floor=floor,
        emitted_at_sha=header.emitted_at_sha,
        worksheet_commit=first,
        scores_commit=last,
        key_commit=revealed["key file"],
        salt_commit=revealed["salt file"],
    )
