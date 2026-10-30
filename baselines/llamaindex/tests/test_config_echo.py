"""The pipeline-config echo names every D-248 value and the installed framework."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

from llama_index.core import Settings
from llama_index.core.llms import CustomLLM, LLMMetadata

from lancet_llamaindex.corpus import load_documents
from lancet_llamaindex.pipeline import PIPELINE_CONFIG_FILE, Pipeline, write_outputs

from .test_export import _questions


def _pipeline(corpus_dir: Path, embedding, reranker) -> Pipeline:
    documents = load_documents(
        corpus_dir / "documents.jsonl", corpus_dir / "document_map.json"
    )
    return Pipeline.build(documents, embed_model=embedding, reranker=reranker)


def test_echo_names_every_value_and_the_installed_version(
    corpus_dir, tmp_path, embedding, reranker
):
    pipeline = _pipeline(corpus_dir, embedding, reranker)
    rows = pipeline.export_rows("fixture", "llamaindex", _questions(corpus_dir))
    _, echo_path = write_outputs(tmp_path / "out", rows, pipeline.config_echo())

    echo = json.loads(echo_path.read_text("utf-8"))

    assert echo_path.name == PIPELINE_CONFIG_FILE
    assert echo["framework"] == "llama-index-core"
    assert echo["framework_version"] == version("llama-index-core") == "0.14.25"
    assert echo["splitter"]["type"] == "SentenceSplitter"
    assert (echo["splitter"]["chunk_size"], echo["splitter"]["chunk_overlap"]) == (
        256,
        25,
    )
    assert echo["dense_top_k"] == 20
    assert echo["embedding"]["model"] == "voyageai/voyage-4-large"
    assert echo["embedding"]["endpoint"] == "https://openrouter.ai/api/v1/embeddings"
    assert echo["embedding"]["input_type"] is None
    assert echo["rerank"]["model"] == "voyageai/rerank-2.5-lite"
    assert echo["rerank"]["endpoint"] == "https://openrouter.ai/api/v1/rerank"
    assert echo["keep"] == 8
    assert echo["embedded_metadata_keys"] == ["title", "source", "published_at"]
    assert echo["documents"] == 3
    assert len(echo["index_fingerprint"]) == 64


class _GuardLLM(CustomLLM):
    """An LLM that fails the test if anything asks it for a completion."""

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata()

    def complete(self, prompt, formatted=False, **kwargs):
        raise AssertionError("the baseline called a reader")

    def stream_complete(self, prompt, formatted=False, **kwargs):
        raise AssertionError("the baseline called a reader")


def test_the_pipeline_never_calls_a_reader(corpus_dir, embedding, reranker):
    previous = Settings._llm
    Settings.llm = _GuardLLM()
    try:
        pipeline = _pipeline(corpus_dir, embedding, reranker)
        rows = pipeline.export_rows("fixture", "llamaindex", _questions(corpus_dir))
    finally:
        Settings._llm = previous

    assert len(rows) == 3
