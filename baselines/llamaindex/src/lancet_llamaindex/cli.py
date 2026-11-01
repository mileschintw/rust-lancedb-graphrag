"""`lancet-llamaindex export`: index the corpus, retrieve per question, export.

The questions come from the harness corpus config (`lancet_eval.corpus.load_corpus`),
so question IDs match the journal's. The documents default to the corpus's documents
file (pinned by its sha256 when the corpus pins it) and the document map to the one
`lancet-eval seed` wrote for `--store` (#146), so document IDs are that store's. Each
path can be overridden for a fixture run.

`lancet-llamaindex build` embeds the documents once and persists the index to
`--index-dir`; `export --index-dir` then loads it and embeds only the questions (#146).

A live run embeds every chunk and every question and reranks every question through
OpenRouter: it is a paid call and needs `OPENROUTER_API_KEY`. Setting
`LANCET_OPENROUTER__EMBEDDING_ENDPOINT` and `LANCET_OPENROUTER__RERANK_ENDPOINT` (the
engine's overrides) sends both to another endpoint instead, such as the free
`lancet_eval.provider_stub`; the key must still be set, to any value. Before the first
request it runs the corpus's split gates (`lancet_eval.run.require_split_gates`: D-73,
the split hash and the role) when the corpus has a `[split]` (#78), then prints a D-258
cost estimate to stderr, which never refuses (#77).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from lancet_eval.config import (
    V1_STORE,
    EvalConfigError,
    EvalStore,
    get_eval_store,
    repo_root,
)
from lancet_eval.corpus import LABEL_ADAPTERS, CorpusConfig, GoldQuestion, load_corpus
from lancet_eval.drive_estimate import export_estimate
from lancet_eval.run import require_split_gates
from lancet_eval.seed import get_document_map_path
from llama_index.core import Document
from llama_index.core.base.embeddings.base import BaseEmbedding

from lancet_llamaindex.corpus import CorpusLoadError, load_documents
from lancet_llamaindex.pipeline import ExportError, Pipeline, Reranker, write_outputs
from lancet_llamaindex.providers import (
    EMBEDDING_ENDPOINT,
    RERANK_ENDPOINT,
    OpenRouterEmbedding,
    OpenRouterReranker,
    ProviderError,
    api_key_from_env,
    endpoints_from_env,
)


def _add_document_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--corpus", required=True, help="harness corpus name")
    command.add_argument(
        "--store",
        default=V1_STORE.name,
        help="the eval store whose document map names the documents (default: eval)",
    )
    command.add_argument("--documents", type=Path, help="override the documents file")
    command.add_argument("--document-map", type=Path, help="override the document map")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lancet-llamaindex")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser(
        "export", help="write context_export.jsonl and pipeline_config.json"
    )
    _add_document_args(export)
    export.add_argument("--arm", required=True, help="the pre-registered arm label")
    export.add_argument("--out", required=True, type=Path, help="output directory")
    export.add_argument(
        "--questions", type=Path, help="override the questions file (MultiHop-RAG rows)"
    )
    export.add_argument(
        "--index-dir", type=Path, help="read the index `build` persisted there"
    )
    build = sub.add_parser("build", help="embed the documents and persist the index")
    _add_document_args(build)
    build.add_argument(
        "--index-dir", required=True, type=Path, help="where to persist the index"
    )
    return parser


def corpus_files(
    config: CorpusConfig, corpus: str, store: EvalStore
) -> tuple[Path, Path, str | None]:
    """The corpus's documents file, `store`'s document map, and the documents' pin."""
    return (
        config.documents_path,
        get_document_map_path(corpus, store),
        config.documents_sha256,
    )


def _config(corpus: str) -> CorpusConfig | None:
    corpus_toml = repo_root() / "eval" / "corpora" / f"{corpus}.toml"
    # No corpus config is a fixture run, which needs every file overridden.
    return load_corpus(corpus) if corpus_toml.is_file() else None


def _documents(args: argparse.Namespace, config: CorpusConfig | None) -> list[Document]:
    """The documents an override or the corpus names, keyed by `--store`'s map."""
    if config is None:
        if args.documents is None or args.document_map is None:
            raise CorpusLoadError(
                "a corpus with no config needs --documents and --document-map"
            )
        return load_documents(args.documents, args.document_map)
    documents_path, map_path, sha256 = corpus_files(
        config, args.corpus, get_eval_store(args.store)
    )
    if args.documents is not None:
        documents_path, sha256 = args.documents, None
    return load_documents(documents_path, args.document_map or map_path, sha256)


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
    # No corpus config is a fixture run, which needs `--questions`; it has no gates.
    config = _config(args.corpus)
    if args.questions is not None:
        questions = _read_questions(args.questions)
    elif config is None:
        raise CorpusLoadError(f"Corpus config not found for {args.corpus!r}")
    else:
        questions = config.questions
    if config is not None:
        # #78: the gates `run` and `run-external` pass, on the questions this export
        # reads (an override included), before any request. A corpus with no
        # `[split]` has none.
        require_split_gates(config, questions, git_repo=git_repo)
    documents = _documents(args, config)
    if args.index_dir is not None:
        # A persisted index embeds no document text: only the questions cost.
        print(export_estimate(len(questions), 0), file=sys.stderr)
        pipeline = Pipeline.load(
            documents, args.index_dir, embed_model=embed_model, reranker=reranker
        )
    else:
        print(
            export_estimate(len(questions), sum(len(d.text) for d in documents)),
            file=sys.stderr,
        )
        pipeline = Pipeline.build(documents, embed_model=embed_model, reranker=reranker)
    rows = pipeline.export_rows(args.corpus, args.arm, questions)
    return write_outputs(args.out, rows, pipeline.config_echo())


def run_build(args: argparse.Namespace, *, embed_model: BaseEmbedding) -> Path:
    """Runs `build`: embeds the documents and persists the index; returns its manifest.

    It reads no question, so it passes no split gate and calls no reranker.
    """
    documents = _documents(args, _config(args.corpus))
    print(export_estimate(0, sum(len(d.text) for d in documents)), file=sys.stderr)
    pipeline = Pipeline.build(documents, embed_model=embed_model, reranker=_NoRerank())
    return pipeline.persist(args.index_dir)


class _NoRerank:
    """`build` retrieves nothing, so it never reranks."""

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        raise AssertionError("build never reranks")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        key = api_key_from_env()
        embedding_endpoint, rerank_endpoint = endpoints_from_env()
        overridden = (embedding_endpoint, rerank_endpoint) != (
            EMBEDDING_ENDPOINT,
            RERANK_ENDPOINT,
        )
        if overridden:
            # Never silent: a paid run left pointing at the stub would be wasted.
            print(
                "lancet-llamaindex: endpoint override: embeddings "
                f"{embedding_endpoint}, rerank {rerank_endpoint}",
                file=sys.stderr,
            )
        embed_model = OpenRouterEmbedding(api_key=key, endpoint=embedding_endpoint)
        if args.command == "build":
            paths: tuple[Path, ...] = (run_build(args, embed_model=embed_model),)
        else:
            paths = run_export(
                args,
                embed_model=embed_model,
                reranker=OpenRouterReranker(api_key=key, endpoint=rerank_endpoint),
            )
    # ValueError: a split gate's refusal (#78), `PreregistrationError` included.
    # EvalConfigError: an unknown `--store`.
    except (
        CorpusLoadError,
        EvalConfigError,
        ExportError,
        ProviderError,
        OSError,
        ValueError,
    ) as exc:
        print(f"lancet-llamaindex: {exc}", file=sys.stderr)
        return 1
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
