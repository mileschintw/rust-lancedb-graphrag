"""The CLI wires the corpus files to the pipeline; the live providers need a key."""

from __future__ import annotations

from lancet_eval.config import repo_root
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, read_export

from lancet_llamaindex import cli
from lancet_llamaindex.cli import _parser, main, run_export
from lancet_llamaindex.corpus import load_documents
from lancet_llamaindex.pipeline import PIPELINE_CONFIG_FILE


def _argv(corpus_dir, out):
    return [
        "export",
        "--corpus",
        "fixture",
        "--arm",
        "llamaindex-paper",
        "--out",
        str(out),
        "--questions",
        str(corpus_dir / "questions.jsonl"),
        "--documents",
        str(corpus_dir / "documents.jsonl"),
        "--document-map",
        str(corpus_dir / "document_map.json"),
    ]


def test_export_command_writes_both_files(corpus_dir, tmp_path, embedding, reranker):
    out = tmp_path / "out"
    args = _parser().parse_args(_argv(corpus_dir, out))

    export_path, echo_path = run_export(args, embed_model=embedding, reranker=reranker)

    assert export_path == out / CONTEXT_EXPORT_FILE
    assert echo_path == out / PIPELINE_CONFIG_FILE
    assert {r.arm for r in read_export(export_path)} == {"llamaindex-paper"}


def test_a_live_run_without_a_key_stops_before_any_call(
    corpus_dir, tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    code = main(_argv(corpus_dir, tmp_path / "out"))

    assert code == 1
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_every_seeded_document_maps_to_a_lancet_document_id():
    corpus = repo_root() / "eval" / "corpora" / "multihop_rag"

    documents = load_documents(
        corpus / "documents.subset.jsonl", corpus / "document_map.json"
    )

    assert len(documents) == len({d.doc_id for d in documents}) == 346


def _capture_providers(monkeypatch, tmp_path):
    seen = {}

    def fake_run_export(args, *, embed_model, reranker):
        seen["embedding"] = embed_model.endpoint
        seen["rerank"] = reranker.endpoint
        return tmp_path / "a", tmp_path / "b"

    monkeypatch.setattr(cli, "run_export", fake_run_export)
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    return seen


def test_the_export_sends_to_openrouter_by_default(corpus_dir, tmp_path, monkeypatch):
    monkeypatch.delenv("LANCET_OPENROUTER__EMBEDDING_ENDPOINT", raising=False)
    monkeypatch.delenv("LANCET_OPENROUTER__RERANK_ENDPOINT", raising=False)
    seen = _capture_providers(monkeypatch, tmp_path)

    assert main(_argv(corpus_dir, tmp_path / "out")) == 0

    assert seen == {
        "embedding": "https://openrouter.ai/api/v1/embeddings",
        "rerank": "https://openrouter.ai/api/v1/rerank",
    }


def test_the_export_sends_to_the_endpoint_override(
    corpus_dir, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv(
        "LANCET_OPENROUTER__EMBEDDING_ENDPOINT", "http://127.0.0.1:8099/embeddings"
    )
    monkeypatch.setenv(
        "LANCET_OPENROUTER__RERANK_ENDPOINT", "http://127.0.0.1:8099/rerank"
    )
    seen = _capture_providers(monkeypatch, tmp_path)

    assert main(_argv(corpus_dir, tmp_path / "out")) == 0

    assert seen == {
        "embedding": "http://127.0.0.1:8099/embeddings",
        "rerank": "http://127.0.0.1:8099/rerank",
    }
    # An override is never silent: a paid run left pointing at the stub would be wasted.
    assert "http://127.0.0.1:8099/embeddings" in capsys.readouterr().err
