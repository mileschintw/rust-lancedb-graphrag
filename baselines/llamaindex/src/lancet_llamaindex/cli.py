"""`lancet-llamaindex export`: index the corpus, retrieve per question, export.

The questions come from the harness corpus config (`lancet_eval.corpus.load_corpus`),
so question IDs match the journal's. The documents and document map default to the
corpus's `map_corpus` directory, the files `lancet-eval seed` reads and writes. Each
path can be overridden for a fixture run.

A live run embeds every chunk and every question and reranks every question through
OpenRouter: it is a paid call and needs `OPENROUTER_API_KEY`. Before the first one it
runs the corpus's split gates (`lancet_eval.run.require_split_gates`: D-73, the split
hash and the role) when the corpus has a `[split]` (#78), then prints a D-258 cost
estimate to stderr, which never refuses (#77).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from lancet_eval.config import repo_root
from lancet_eval.corpus import LABEL_ADAPTERS, GoldQuestion, load_corpus
from lancet_eval.drive_estimate import export_estimate
from lancet_eval.run import require_split_gates
from llama_index.core.base.embeddings.base import BaseEmbedding

from lancet_llamaindex.corpus import CorpusLoadError, load_documents
from lancet_llamaindex.pipeline import ExportError, Pipeline, Reranker, write_outputs
from lancet_llamaindex.providers import (
    OpenRouterEmbedding,
    OpenRouterReranker,
    ProviderError,
    api_key_from_env,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lancet-llamaindex")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser(
        "export", help="write context_export.jsonl and pipeline_config.json"
    )
    export.add_argument("--corpus", required=True, help="harness corpus name")
    export.add_argument("--arm", required=True, help="the pre-registered arm label")
    export.add_argument("--out", required=True, type=Path, help="output directory")
    export.add_argument(
        "--questions", type=Path, help="override the questions file (MultiHop-RAG rows)"
    )
    export.add_argument("--documents", type=Path, help="override the documents file")
    export.add_argument("--document-map", type=Path, help="override the document map")
    return parser


def _read_questions(path: Path) -> list[GoldQuestion]:
    adapt = LABEL_ADAPTERS["multihop_rag"]
    questions: list[GoldQuestion] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        questions.append(adapt(json.loads(line)))
                    except ValueError as exc:
                        raise CorpusLoadError(f"{path} line {line_num}: {exc}") from exc
    except OSError as exc:
        raise CorpusLoadError(f"{path}: {exc}") from exc
    return questions


def run_export(
    args: argparse.Namespace,
    *,
    embed_model: BaseEmbedding,
    reranker: Reranker,
    git_repo: Path | None = None,
) -> tuple[Path, Path]:
    """Runs `export` with the given providers; the CLI passes the OpenRouter ones.

    `git_repo` is the repository the D-73 gate reads; the live one when None.
    """
    corpus_toml = repo_root() / "eval" / "corpora" / f"{args.corpus}.toml"
    config = load_corpus(args.corpus) if corpus_toml.is_file() else None
    if args.questions is not None:
        questions = _read_questions(args.questions)
        map_dir = None
    elif config is None:
        raise CorpusLoadError(f"Corpus config not found at {corpus_toml}")
    else:
        questions = config.questions
        map_dir = repo_root() / "eval" / "corpora" / config.map_corpus
    if config is not None:
        # #78: the gates `run` and `run-external` pass, on the questions this export
        # reads (an override included), before any request. A corpus with no
        # `[split]` has none.
        require_split_gates(config, questions, git_repo=git_repo)
    documents_path = args.documents or (
        map_dir / "documents.subset.jsonl" if map_dir else None
    )
    map_path = args.document_map or (map_dir / "document_map.json" if map_dir else None)
    if documents_path is None or map_path is None:
        raise CorpusLoadError(
            "--questions needs --documents and --document-map as well"
        )
    documents = load_documents(documents_path, map_path)
    print(
        export_estimate(len(questions), sum(len(d.text) for d in documents)),
        file=sys.stderr,
    )
    pipeline = Pipeline.build(documents, embed_model=embed_model, reranker=reranker)
    rows = pipeline.export_rows(args.corpus, args.arm, questions)
    return write_outputs(args.out, rows, pipeline.config_echo())


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        key = api_key_from_env()
        paths = run_export(
            args,
            embed_model=OpenRouterEmbedding(api_key=key),
            reranker=OpenRouterReranker(api_key=key),
        )
    # ValueError: a split gate's refusal (#78), `PreregistrationError` included.
    except (CorpusLoadError, ExportError, ProviderError, OSError, ValueError) as exc:
        print(f"lancet-llamaindex: {exc}", file=sys.stderr)
        return 1
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
