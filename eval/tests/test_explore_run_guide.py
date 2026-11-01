"""RUN-EXPLORE-BC.md (#149) names only corpora, arms, stores and Atlas envs that exist,
and its Python snippets compile as pasted."""

from __future__ import annotations

import re

from lancet_eval.config import EVAL_STORES, repo_root
from lancet_eval.corpus import load_corpus

GUIDE = repo_root() / "experiments" / "v1.1" / "RUN-EXPLORE-BC.md"
TEXT = GUIDE.read_text(encoding="utf-8")


def test_every_corpus_and_arm_the_guide_names_exists() -> None:
    corpora = set(re.findall(r"--corpus (\w+)", TEXT)) - {"multihop_rag"}
    assert corpora == {"multihop_rag_full_dev", "twowiki_s3b_dev"}
    arms = {a for corpus in corpora for a in load_corpus(corpus).arms}
    named = set(re.findall(r"--arms? ((?:full|twowiki)/[\w+.@-]+)", TEXT))
    assert named and named <= arms


def test_every_store_and_atlas_env_the_guide_names_exists() -> None:
    atlas = (repo_root() / "gateway" / "atlas.hcl").read_text(encoding="utf-8")
    for store in set(re.findall(r"--store ([\w-]+)", TEXT)):
        assert store in EVAL_STORES
    for env in set(re.findall(r"--env ([\w-]+)", TEXT)):
        assert f'env "{env}"' in atlas
    for env in set(re.findall(r"LANCET_ENV=([\w-]+)", TEXT)):
        assert env in EVAL_STORES
    for schema in set(re.findall(r"search_path=(\w+)", TEXT)):
        assert schema in {s.pg_schema for s in EVAL_STORES.values()}


def test_python_snippets_compile_as_written() -> None:
    snippets = re.findall(r'python -c "(.*?)"\n', TEXT)
    assert snippets
    for snippet in snippets:
        compile(snippet, "<guide>", "exec")
