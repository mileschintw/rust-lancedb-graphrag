"""`RUN_PLAN_S3_HELDOUT` and its six column corpora (#163, D-291).

The constant is the owner's grid as #163 states it: four readers by six columns over
2Wiki's 900 held-out questions, every deepseek, Haiku and Opus cell core, Sonnet core
on closed-book, hybrid and graph-deepseek only. Each column has one corpus that names
the constant and the column, lists exactly the column's arms, and reads the held-out
split; each graph column has an engine overlay naming its writer's graph table set.
"""

from __future__ import annotations

import tomllib

import pytest

from lancet_eval import preregistration, thresholds, twowiki, twowiki_h
from lancet_eval.arms import canonical_arm
from lancet_eval.config import repo_root
from lancet_eval.corpus import CorpusConfig
from lancet_eval.split import lf_sha256, load_split, split_sha256

PLAN = thresholds.RUN_PLAN_S3_HELDOUT
TOKEN = "RUN_PLAN_S3_HELDOUT"
READERS = ("deepseek", "haiku-5.5", "sonnet-5.5", "opus-5.5")
COLUMNS = (
    "closed-book",
    "hybrid",
    "graph-deepseek",
    "graph-haiku",
    "graph-sonnet",
    "graph-opus",
)
WRITERS = {
    "graph-deepseek": "deepseek",
    "graph-haiku": "haiku-5.5",
    "graph-sonnet": "sonnet-5.5",
    "graph-opus": "opus-5.5",
}


def _corpus(column: str) -> CorpusConfig:
    return CorpusConfig(f"twowiki_s3h_{column.replace('-', '_')}")


def test_the_grid_is_four_readers_by_six_columns() -> None:
    assert [name for name, _ in PLAN.columns] == list(COLUMNS)
    assert {(c, r) for c, r, _ in PLAN.cells} == {
        (c, r) for c in COLUMNS for r in READERS
    }
    assert len(PLAN.cells) == 24
    assert PLAN.question_count == 900


def test_only_three_sonnet_graph_cells_are_optional() -> None:
    optional = {(c, r) for c, r, tier in PLAN.cells if tier == "optional"}
    assert optional == {
        ("graph-haiku", "sonnet-5.5"),
        ("graph-sonnet", "sonnet-5.5"),
        ("graph-opus", "sonnet-5.5"),
    }


def test_readers_k_transports_and_thinking_are_the_owners_rule() -> None:
    readers = dict(PLAN.readers)
    assert readers["haiku-5.5"].thinking == "off"
    for name in ("sonnet-5.5", "opus-5.5"):
        assert (readers[name].thinking, readers[name].effort) == ("on", "low")
    assert PLAN.replicates == 2
    assert dict(PLAN.reader_replicates) == {"sonnet-5.5": 1, "opus-5.5": 1}
    assert dict(PLAN.transports) == {
        "deepseek": "engine_drive_then_openrouter_sync",
        "haiku-5.5": "openrouter_batch",
        "sonnet-5.5": "openrouter_batch",
        "opus-5.5": "openrouter_batch",
    }
    explore_b = dict(thresholds.PREREGISTRATION_EXPLORE_B.readers)
    for name, declaration in readers.items():
        assert declaration.slug == explore_b[name].slug
        assert declaration.price == explore_b[name].price
    assert PLAN.reference_price == thresholds.PREREGISTRATION_EXPLORE_B.reference_price


def test_the_columns_read_the_pinned_split() -> None:
    assert PLAN.split_file == f"eval/corpora/{twowiki.SPLIT_REL}"
    assert PLAN.split_sha256 == lf_sha256(twowiki.SPLIT_PATH)
    split = load_split(repo_root() / "eval" / "corpora" / twowiki_h.HELDOUT_SPLIT_REL)
    assert split_sha256(split) in PLAN.population


def test_a_column_and_a_graph_writer_go_together() -> None:
    columns = dict(PLAN.columns)
    assert columns["closed-book"].source_arm == "twowiki/closed-book"
    assert columns["hybrid"].source_arm == "twowiki/hybrid+rerank+metadata"
    for column, writer in WRITERS.items():
        assert columns[column].graph_writer == writer


@pytest.mark.parametrize("column", COLUMNS)
def test_each_column_corpus_reads_its_column_on_the_heldout_split(column: str) -> None:
    config = _corpus(column)
    assert config.preregistration_token == TOKEN
    assert config.preregistration_column == column
    view = preregistration.resolve_corpus(config)
    assert {canonical_arm(a) for a in config.arms} == set(preregistration.arms_of(view))
    assert config.split_role == "heldout"
    assert config.split_file == twowiki_h.HELDOUT_SPLIT_REL
    assert config.questions_file_rel == twowiki_h.HELDOUT_QUESTIONS_REL
    assert (config.sample_seed, config.sample_size) == (243, 900)
    explore_b = CorpusConfig("twowiki_s3b_dev")
    assert config.documents == explore_b.documents
    assert config.store_chunking == explore_b.store_chunking


@pytest.mark.parametrize(("column", "writer"), sorted(WRITERS.items()))
def test_each_graph_column_has_its_writers_overlay(column: str, writer: str) -> None:
    short = writer.partition("-")[0]
    overlay = repo_root() / "config" / f"config.eval-2wiki-s3h-{short}.toml"
    with overlay.open("rb") as f:
        data = tomllib.load(f)
    assert data["engine"]["lancedb_path"] == "./data/lancedb-eval-2wiki"
    assert data["engine"]["graph"] == {
        "ingest_extraction": False,
        "table_set": f"s3h_{short}",
    }


def test_the_preflight_reads_the_columns_drive_guards() -> None:
    from lancet_eval.preflight import canary_preregistration

    view = canary_preregistration(_corpus("hybrid"))
    assert isinstance(view, thresholds.ColumnRunPlan)
    assert view.rerank_consecutive_degrade_halt == PLAN.rerank_consecutive_degrade_halt
