"""The 2WikiMultiHopQA corpus of S3 (#145, D-234, D-243).

S3 uses HippoRAG 2's packaging of the 2WikiMultiHopQA subset (1,000 questions, 6,119
passages), fetched from the Hugging Face dataset `osunlp/HippoRAG_2` at one pinned
revision. Run as ``python -m lancet_eval.twowiki <command>``:

- ``fetch`` downloads the two files into ``eval/corpora/twowiki/.cache/`` (gitignored)
  and refuses any whose bytes differ from the sha256 recorded here. They are never
  committed: the passages are Wikipedia text (`eval/corpora/ATTRIBUTION.md`).
- ``split`` writes the D-243 dev / held-out split. It reads only each question's
  ``_id`` (D-237: no held-out content is read to build it).

A passage is one extraction unit: its title and text joined by a newline, HippoRAG 2's
own form (``passage_unit``), with no further chunking.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lancet_eval.config import repo_root
from lancet_eval.split import SHA256_PATTERN

DATASET = "osunlp/HippoRAG_2"
#: The dataset's git revision on Hugging Face, read 2026-11-01 (last modified
#: 2025-04-02).
REVISION = "5ec05b38deecc3318bb432c69865959c56058990"
QUESTIONS_FILE = "2wikimultihopqa.json"
PASSAGES_FILE = "2wikimultihopqa_corpus.json"
#: sha256 of each file's bytes as served at REVISION.
SOURCE_SHA256 = {
    QUESTIONS_FILE: "895cba294064df0c3302c76847b1fc08d99b5619f7663dfaa3b65cd780f1cac4",
    PASSAGES_FILE: "9d6e352952aafb18dab22bf8195039461321a44a949df902ae83bce134ad238a",
}
QUESTION_COUNT = 1_000
PASSAGE_COUNT = 6_119

#: D-243: the split is drawn once with this seed; DEV_SIZE questions go to dev (the
#: pilot and preflight only, D-252), the rest to held-out (read once).
SPLIT_SEED = 243
DEV_SIZE = 100
SPLIT_REL = "twowiki/split.json"

CACHE_DIR = repo_root() / "eval" / "corpora" / "twowiki" / ".cache"
SPLIT_PATH = repo_root() / "eval" / "corpora" / SPLIT_REL

app = typer.Typer(add_completion=False, no_args_is_help=True)


class SourceError(RuntimeError):
    """Raised when a source file is missing or differs from the pinned bytes."""


class TwoWikiSplit(BaseModel):
    """The committed D-243 split of the 1,000 questions.

    Attributes:
        dataset: The Hugging Face dataset the IDs come from.
        revision: Its git revision.
        questions_sha256: sha256 of the questions file the IDs were read from.
        derivation_rule: Prose rule that produced the split (``build_split``).
        seed: The seed of that rule.
        dev_size: How many questions went to dev.
        dev_ids: The dev question IDs, sorted.
        heldout_ids: The held-out question IDs, sorted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str
    revision: str
    questions_sha256: str = Field(pattern=SHA256_PATTERN)
    derivation_rule: str
    seed: int
    dev_size: int
    dev_ids: list[str]
    heldout_ids: list[str]

    @model_validator(mode="after")
    def _disjoint(self) -> TwoWikiSplit:
        dev, heldout = set(self.dev_ids), set(self.heldout_ids)
        if dev & heldout:
            raise ValueError("dev and held-out IDs overlap")
        if len(dev) != len(self.dev_ids) or len(heldout) != len(self.heldout_ids):
            raise ValueError("duplicate question IDs in the split")
        if len(self.dev_ids) != self.dev_size:
            raise ValueError(f"{len(self.dev_ids)} dev IDs, dev_size {self.dev_size}")
        return self


DERIVATION_RULE = (
    "sort every question _id; random.Random(seed).sample(sorted_ids, dev_size) is dev; "
    "every other ID is held-out; both lists sorted"
)


def build_split(
    ids: list[str], *, seed: int, dev_size: int
) -> tuple[list[str], list[str]]:
    """Draws the dev / held-out split from question IDs alone (DERIVATION_RULE).

    Args:
        ids: Every question ID, in any order.
        seed: The split seed.
        dev_size: How many IDs go to dev.

    Returns:
        The sorted dev IDs and the sorted held-out IDs.

    Raises:
        ValueError: On a duplicated ID, or a dev_size that leaves no held-out ID.
    """
    ordered = sorted(ids)
    if len(set(ordered)) != len(ordered):
        raise ValueError("duplicate question IDs")
    if not 0 < dev_size < len(ordered):
        raise ValueError(f"dev_size {dev_size} must be within 1..{len(ordered) - 1}")
    dev = sorted(random.Random(seed).sample(ordered, dev_size))
    chosen = set(dev)
    return dev, [i for i in ordered if i not in chosen]


def question_ids(path: Path) -> list[str]:
    """Returns each question's ``_id``, in file order, and nothing else of it."""
    rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return [str(row["_id"]) for row in rows]


def passage_unit(passage: dict[str, Any]) -> str:
    """One passage as one extraction unit: ``title`` and ``text`` on two lines."""
    return f"{passage['title']}\n{passage['text']}"


def load_split(path: Path) -> TwoWikiSplit:
    """Parses and validates the committed split file."""
    return TwoWikiSplit.model_validate_json(path.read_text(encoding="utf-8"))


def check_source(path: Path) -> None:
    """Refuses a cached source file that is missing or differs from the pinned bytes.

    Raises:
        SourceError: When the file is missing or its sha256 is not the pinned one.
    """
    if not path.is_file():
        raise SourceError(
            f"{path} is missing; run `python -m lancet_eval.twowiki fetch`"
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = SOURCE_SHA256[path.name]
    if digest != expected:
        raise SourceError(
            f"{path.name} has sha256 {digest[:12]}, not the pinned {expected[:12]} "
            f"of {DATASET}@{REVISION[:12]}"
        )


def load_passages(cache_dir: Path = CACHE_DIR) -> list[dict[str, Any]]:
    """The 6,119 passages, in file order, from the checked cache."""
    path = cache_dir / PASSAGES_FILE
    check_source(path)
    passages: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    if len(passages) != PASSAGE_COUNT:
        raise SourceError(f"{len(passages)} passages, expected {PASSAGE_COUNT}")
    return passages


def source_url(name: str) -> str:
    """The download URL of one source file at the pinned revision."""
    return f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{name}"


@app.command()
def fetch(cache_dir: Path = CACHE_DIR) -> None:
    """Downloads both source files at REVISION and checks their sha256."""
    import httpx

    cache_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        for name in SOURCE_SHA256:
            dest = cache_dir / name
            if not dest.is_file():
                resp = client.get(source_url(name))
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            check_source(dest)
            typer.echo(f"{name}: sha256 ok")


@app.command()
def split(cache_dir: Path = CACHE_DIR, out: Path = SPLIT_PATH) -> None:
    """Writes the D-243 split from the cached questions' IDs."""
    path = cache_dir / QUESTIONS_FILE
    check_source(path)
    ids = question_ids(path)
    if len(ids) != QUESTION_COUNT:
        raise SourceError(f"{len(ids)} questions, expected {QUESTION_COUNT}")
    dev, heldout = build_split(ids, seed=SPLIT_SEED, dev_size=DEV_SIZE)
    record = TwoWikiSplit(
        dataset=DATASET,
        revision=REVISION,
        questions_sha256=SOURCE_SHA256[QUESTIONS_FILE],
        derivation_rule=DERIVATION_RULE,
        seed=SPLIT_SEED,
        dev_size=DEV_SIZE,
        dev_ids=dev,
        heldout_ids=heldout,
    )
    out.write_text(
        json.dumps(record.model_dump(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    typer.echo(f"{out}: {len(dev)} dev, {len(heldout)} held-out")


if __name__ == "__main__":
    app()
