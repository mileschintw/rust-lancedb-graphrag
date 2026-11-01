"""The CLI wires the corpus files to the pipeline; the live providers need a key."""

from __future__ import annotations

import json

import pytest
from lancet_eval import gitcheck
from lancet_eval.config import repo_root
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, read_export

from lancet_llamaindex import cli
from lancet_llamaindex.cli import _parser, main, run_export
from lancet_llamaindex.corpus import load_documents
from lancet_llamaindex.pipeline import PIPELINE_CONFIG_FILE

from .conftest import QUESTIONS, HashEmbedding


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


# --- #77: the D-258 estimate; #78: the split gates ------------------------------------

SPLIT_CORPUS = "split_fixture"


def _write_split_corpus(root, role):
    """A `[split]` corpus of the conftest questions under `root/eval/corpora`."""
    corpora = root / "eval" / "corpora"
    (corpora / "split").mkdir(parents=True)
    (corpora / f"{SPLIT_CORPUS}.toml").write_text(
        "\n".join([
            "[documents]",
            'map_corpus = "multihop_rag"',
            "chunk_size = 500",
            "[questions]",
            'file = "split/questions.jsonl"',
            'label_format = "multihop_rag"',
            "sample_seed = 42",
            "sample_size = 100",
            "[models]",
            'judge_model = "meta-llama/llama-3.3-70b-instruct"',
            "[arms]",
            'arms = ["hybrid+rerank+metadata", "llamaindex"]',
            "[split]",
            'file = "split/split.json"',
            f'role = "{role}"',
            "[preregistration]",
            'token = "PREREGISTRATION_06_3_6"',
            "",
        ]),
        encoding="utf-8",
    )
    ids = [q["query_id"] for q in QUESTIONS]
    (corpora / "split" / "questions.jsonl").write_text(
        "".join(
            json.dumps({
                "question_id": q["query_id"],
                "query": q["query"],
                "question_type": "inference_query",
                "answer": "Yes",
                "evidence_list": [{"title": "t", "fact": "f"}],
            })
            + "\n"
            for q in QUESTIONS
        ),
        encoding="utf-8",
    )
    (corpora / "split" / "split.json").write_text(
        json.dumps({
            "derivation_rule": "test",
            "populations_sha256": "0" * 64,
            "diag_selection_sha256": "0" * 64,
            "questions_sample_sha256": "0" * 64,
            "dev_source": "dev.json",
            "order_seed": 42,
            "dev_ids": ids if role == "dev" else ["dev-1"],
            "heldout_g_ids": ["held-1"] if role == "dev" else ids,
            "heldout_null_ids": [],
        }),
        encoding="utf-8",
    )


@pytest.fixture
def split_corpus(tmp_path, monkeypatch):
    """Points both packages at a tmp repo; returns a writer for its `[split]` corpus."""
    root = tmp_path / "repo"
    monkeypatch.setattr("lancet_eval.corpus._repo_root", lambda: root)
    monkeypatch.setattr("lancet_llamaindex.cli.repo_root", lambda: root)
    # The fixture split records placeholder input hashes.
    monkeypatch.setattr("lancet_eval.run.split_input_problems", lambda *_a: [])
    return lambda role: _write_split_corpus(root, role)


def _split_argv(corpus_dir, out):
    return [
        "export",
        "--corpus",
        SPLIT_CORPUS,
        "--arm",
        "llamaindex",
        "--out",
        str(out),
        "--documents",
        str(corpus_dir / "documents.jsonl"),
        "--document-map",
        str(corpus_dir / "document_map.json"),
    ]


class _FirstRequest(Exception):
    pass


class _RefusingEmbedding(HashEmbedding):
    """Fails on the first text it is asked to embed: the first paid request."""

    def _get_text_embedding(self, text: str) -> list[float]:
        raise _FirstRequest(text)


def test_the_export_prints_the_estimate_before_any_request(
    corpus_dir, tmp_path, reranker, capsys
):
    args = _parser().parse_args(_argv(corpus_dir, tmp_path / "out"))

    with pytest.raises(_FirstRequest):
        run_export(
            args,
            embed_model=_RefusingEmbedding(seen_texts=[], seen_queries=[]),
            reranker=reranker,
        )

    err = capsys.readouterr().err
    assert "D-258" in err
    assert "3 question(s) x 1 arm" in err


def test_a_heldout_corpus_whose_gates_fail_is_refused_before_any_request(
    corpus_dir, tmp_path, split_corpus, embedding, reranker, monkeypatch, capsys
):
    split_corpus("heldout")
    monkeypatch.setattr(
        gitcheck, "preregistration_problems", lambda *_a, **_k: ["tree is dirty"]
    )
    args = _parser().parse_args(_split_argv(corpus_dir, tmp_path / "out"))

    with pytest.raises(gitcheck.PreregistrationError, match="D-73"):
        run_export(args, embed_model=embedding, reranker=reranker)

    assert embedding.seen_texts == [] and embedding.seen_queries == []
    assert reranker.calls == []
    assert not (tmp_path / "out").exists()
    assert "D-258" not in capsys.readouterr().err


def test_main_reports_a_gate_refusal_and_exits_1(
    corpus_dir, tmp_path, split_corpus, monkeypatch, capsys
):
    split_corpus("heldout")
    monkeypatch.setattr(
        gitcheck, "preregistration_problems", lambda *_a, **_k: ["tree is dirty"]
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")

    code = main(_split_argv(corpus_dir, tmp_path / "out"))

    assert code == 1
    assert "D-73" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_a_dev_corpus_runs_without_the_preregistration_gate(
    corpus_dir, tmp_path, split_corpus, embedding, reranker, monkeypatch
):
    split_corpus("dev")

    def no_d73(*_a, **_k):
        raise AssertionError("a dev corpus skips the D-73 gate (D-170)")

    monkeypatch.setattr(gitcheck, "preregistration_problems", no_d73)
    args = _parser().parse_args(_split_argv(corpus_dir, tmp_path / "out"))

    export_path, _ = run_export(args, embed_model=embedding, reranker=reranker)

    rows = read_export(export_path)
    assert sorted(r.question_id for r in rows) == ["q-1", "q-2", "q-3"]


def test_a_split_role_breach_is_refused_before_any_request(
    corpus_dir, tmp_path, split_corpus, embedding, reranker
):
    # A dev corpus whose questions are not all dev IDs (D-170).
    split_corpus("dev")
    argv = _split_argv(corpus_dir, tmp_path / "out")
    args = _parser().parse_args([*argv, "--questions", str(_extra(tmp_path))])

    with pytest.raises(ValueError, match="D-170"):
        run_export(args, embed_model=embedding, reranker=reranker)

    assert embedding.seen_texts == [] and reranker.calls == []


def _extra(tmp_path):
    path = tmp_path / "extra_questions.jsonl"
    path.write_text(
        json.dumps({"query_id": "held-1", "query": "A held-out question?"}) + "\n",
        encoding="utf-8",
    )
    return path


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


# --- #146: the 609-document corpus and a persisted index ------------------------------


def test_a_full_corpus_reads_its_pinned_file_and_its_stores_map():
    from lancet_eval.config import get_eval_store
    from lancet_eval.corpus import load_corpus

    files = cli.corpus_files(
        load_corpus("multihop_rag_confirm_dev"),
        "multihop_rag_confirm_dev",
        get_eval_store("eval-full"),
    )

    corpora = repo_root() / "eval" / "corpora"
    assert files == (
        corpora / "multihop_rag" / ".cache" / "corpus.json",
        corpora / "multihop_rag_full" / "document_map.eval-full.json",
        "20b61b5ab84de84a927420c5d265b7ec8d859ae49980699958a787ade9e4d28f",
    )


def test_the_v1_corpus_keeps_its_subset_file_and_map():
    from lancet_eval.config import V1_STORE
    from lancet_eval.corpus import load_corpus

    files = cli.corpus_files(load_corpus("multihop_rag"), "multihop_rag", V1_STORE)

    corpus = repo_root() / "eval" / "corpora" / "multihop_rag"
    assert files == (
        corpus / "documents.subset.jsonl",
        corpus / "document_map.json",
        None,
    )


def _build_argv(corpus_dir, index_dir):
    return [
        "build",
        "--corpus",
        "fixture",
        "--index-dir",
        str(index_dir),
        "--documents",
        str(corpus_dir / "documents.jsonl"),
        "--document-map",
        str(corpus_dir / "document_map.json"),
    ]


class _QueryOnlyEmbedding(HashEmbedding):
    def _get_text_embedding(self, text: str) -> list[float]:
        raise AssertionError("an export over a persisted index embedded a document")


def test_build_persists_an_index_that_export_reads_without_embedding_documents(
    corpus_dir, tmp_path, embedding, reranker, capsys
):
    index_dir = tmp_path / "index"
    manifest = cli.run_build(
        _parser().parse_args(_build_argv(corpus_dir, index_dir)), embed_model=embedding
    )
    assert "D-258" in capsys.readouterr().err
    assert embedding.seen_queries == []
    built = json.loads(manifest.read_text(encoding="utf-8"))

    argv = [*_argv(corpus_dir, tmp_path / "out"), "--index-dir", str(index_dir)]
    _, echo_path = run_export(
        _parser().parse_args(argv),
        embed_model=_QueryOnlyEmbedding(seen_texts=[], seen_queries=[]),
        reranker=reranker,
    )

    echo = json.loads(echo_path.read_text(encoding="utf-8"))
    assert echo["index_fingerprint"] == built["index_fingerprint"]
    assert "indexing about $0.0000" in capsys.readouterr().err


def test_build_without_a_key_stops_before_any_call(
    corpus_dir, tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    code = main(_build_argv(corpus_dir, tmp_path / "index"))

    assert code == 1
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "index").exists()


def test_an_unknown_store_is_reported_and_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")

    code = main([
        "build",
        "--corpus",
        "multihop_rag_confirm_dev",
        "--store",
        "eval-nowhere",
        "--index-dir",
        str(tmp_path / "index"),
    ])

    assert code == 1
    assert "eval-nowhere" in capsys.readouterr().err
    assert not (tmp_path / "index").exists()
