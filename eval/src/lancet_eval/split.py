"""D-105 held-out split model and hashing helpers.

The split file `eval/corpora/multihop_rag/heldout_split.json` is committed before
any paid request. Every sha256 recorded in it is computed over LF-normalised
bytes by one function, `lf_sha256`, because a Windows working tree with
`core.autocrlf=true` holds CRLF bytes that differ from the committed git object
(06.3.5 RESEARCH Pitfall 1).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"

# The three files the split was derived from, repo-relative (the dev IDs come from the
# split's own `dev_source`). `select_heldout_split.py` reads the same paths.
POPULATIONS_REL = (
    ".planning/phases/06.3.4.1-retrieval-diagnosis-index-identity-and-graph-yield-repair"
    "/diagnostic/post-reconcile/populations.json"
)
QUESTIONS_SAMPLE_REL = "eval/corpora/multihop_rag/questions.sample.jsonl"


class HeldOutSplit(BaseModel):
    """The committed dev / held-out partition of the 500-question sample (D-105).

    Attributes:
        derivation_rule: Prose rule that produced the held-out lists.
        populations_sha256: LF-normalised sha256 of `populations.json`.
        diag_selection_sha256: LF-normalised sha256 of `diag_selection.json`.
        questions_sample_sha256: LF-normalised sha256 of `questions.sample.jsonl`.
        dev_source: Repo-relative path the dev IDs were read from.
        order_seed: Seed of the D-107 question and arm rotation.
        dev_ids: The dev question IDs (never sent to the held-out drive).
        heldout_g_ids: Non-dev sample questions in G (308 expected).
        heldout_null_ids: Non-dev null questions, an abstention-only stratum
            (43 expected).
        heldout_ids: Held-out IDs not yet sorted into G and null, because the split
            never read their content (#149's fresh split). Empty in the D-105 split.
        inputs: #149: ``{repo-relative path: LF-normalised sha256}`` of the files a
            split of another dataset was derived from (2Wiki's D-243 split file). Such
            a split sets none of the three MultiHop-RAG hashes nor `dev_source`; a
            MultiHop-RAG split sets all four and leaves this empty.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    derivation_rule: str
    populations_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    diag_selection_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    questions_sample_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    dev_source: str | None = None
    order_seed: int
    dev_ids: list[str]
    heldout_g_ids: list[str]
    heldout_null_ids: list[str]
    heldout_ids: list[str] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _inputs(self) -> HeldOutSplit:
        multihop = (
            self.populations_sha256,
            self.diag_selection_sha256,
            self.questions_sample_sha256,
            self.dev_source,
        )
        if self.inputs:
            if any(value is not None for value in multihop):
                raise ValueError(
                    "a split with `inputs` records none of the MultiHop-RAG inputs"
                )
            for rel, sha in self.inputs.items():
                if not re.fullmatch(SHA256_PATTERN, sha):
                    raise ValueError(f"inputs[{rel!r}] is not a sha256: {sha!r}")
        elif any(value is None for value in multihop):
            raise ValueError(
                "a MultiHop-RAG split records populations_sha256, "
                "diag_selection_sha256, questions_sample_sha256 and dev_source"
            )
        return self

    @model_validator(mode="after")
    def _disjoint(self) -> HeldOutSplit:
        lists = (
            self.dev_ids,
            self.heldout_g_ids,
            self.heldout_null_ids,
            self.heldout_ids,
        )
        sets = [set(ids) for ids in lists]
        if sum(len(ids) for ids in sets) != len(set().union(*sets)):
            raise ValueError(
                "dev, held-out G, held-out null and unsorted held-out sets must be "
                "disjoint"
            )
        if any(len(ids) != len(seen) for ids, seen in zip(lists, sets, strict=True)):
            raise ValueError("duplicate question IDs in the split")
        return self


_MULTIHOP_INPUT_KEYS = (
    "populations_sha256",
    "diag_selection_sha256",
    "questions_sample_sha256",
    "dev_source",
)


def lf_sha256(path: str | Path) -> str:
    """Returns the sha256 of a file's bytes with every CRLF folded to LF.

    Args:
        path: File to hash.

    Returns:
        Lower-case hex digest, identical for an LF or a CRLF checkout.
    """
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def load_split(path: str | Path) -> HeldOutSplit:
    """Parses and validates a committed split file.

    Args:
        path: Path to `heldout_split.json`.

    Returns:
        The validated, frozen split.

    Raises:
        pydantic.ValidationError: On unknown keys, a malformed sha256, an
            overlap between sets or a duplicated ID.
    """
    return HeldOutSplit.model_validate_json(Path(path).read_text(encoding="utf-8"))


def split_input_problems(split: HeldOutSplit, repo: str | Path) -> list[str]:
    """Names every input file whose LF-normalised hash differs from the split's record.

    The split stores `populations_sha256`, `diag_selection_sha256` and
    `questions_sample_sha256`, or another dataset's `inputs` (#149), so a change to
    any file it was derived from is detectable. This is the reader of those fields.

    Args:
        split: The parsed split.
        repo: Repository root the recorded paths are relative to.

    Returns:
        One message per missing or changed input; empty when all three match.
    """
    root = Path(repo)
    inputs: tuple[tuple[str, str | None, str | None], ...] = (
        ("populations", POPULATIONS_REL, split.populations_sha256),
        ("diag_selection", split.dev_source, split.diag_selection_sha256),
        ("questions_sample", QUESTIONS_SAMPLE_REL, split.questions_sample_sha256),
    )
    if split.inputs:
        inputs = tuple((rel, rel, sha) for rel, sha in split.inputs.items())
    problems: list[str] = []
    for name, rel, recorded in inputs:
        assert rel is not None and recorded is not None  # the model validates it
        path = root / rel
        if not path.is_file():
            problems.append(f"{name} input {rel} is missing")
        elif lf_sha256(path) != recorded:
            problems.append(
                f"{name} input {rel} no longer hashes to the split's recorded "
                f"{recorded[:12]}"
            )
    return problems


def split_sha256(split: HeldOutSplit) -> str:
    """Returns the sha256 of the split's canonical JSON.

    The canonical form is the parsed model dumped with sorted keys and compact
    separators, so the digest does not depend on file whitespace or line
    endings. #149's fields (`heldout_ids`, `inputs`, and the MultiHop-RAG inputs
    a split with `inputs` leaves unset) are left out while empty or unset, so a
    split written before they existed keeps its digest.

    Args:
        split: The parsed split.

    Returns:
        Lower-case hex digest.
    """
    dumped = split.model_dump()
    for key in ("heldout_ids", "inputs"):
        if not dumped[key]:
            del dumped[key]
    if split.inputs:
        for key in _MULTIHOP_INPUT_KEYS:
            del dumped[key]
    canonical = json.dumps(dumped, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
