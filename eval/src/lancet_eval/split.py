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
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    derivation_rule: str
    populations_sha256: str = Field(pattern=SHA256_PATTERN)
    diag_selection_sha256: str = Field(pattern=SHA256_PATTERN)
    questions_sample_sha256: str = Field(pattern=SHA256_PATTERN)
    dev_source: str
    order_seed: int
    dev_ids: list[str]
    heldout_g_ids: list[str]
    heldout_null_ids: list[str]

    @model_validator(mode="after")
    def _disjoint(self) -> HeldOutSplit:
        dev = set(self.dev_ids)
        g = set(self.heldout_g_ids)
        null = set(self.heldout_null_ids)
        if dev & g or dev & null or g & null:
            raise ValueError("dev, held-out G and held-out null sets must be disjoint")
        if (
            len(dev) != len(self.dev_ids)
            or len(g) != len(self.heldout_g_ids)
            or len(null) != len(self.heldout_null_ids)
        ):
            raise ValueError("duplicate question IDs in the split")
        return self


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
    `questions_sample_sha256` so a change to any file it was derived from is
    detectable. This is the reader of those fields.

    Args:
        split: The parsed split.
        repo: Repository root the recorded paths are relative to.

    Returns:
        One message per missing or changed input; empty when all three match.
    """
    root = Path(repo)
    inputs = (
        ("populations", POPULATIONS_REL, split.populations_sha256),
        ("diag_selection", split.dev_source, split.diag_selection_sha256),
        ("questions_sample", QUESTIONS_SAMPLE_REL, split.questions_sample_sha256),
    )
    problems: list[str] = []
    for name, rel, recorded in inputs:
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
    endings.

    Args:
        split: The parsed split.

    Returns:
        Lower-case hex digest.
    """
    canonical = json.dumps(split.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
