"""Tests proving that API keys are never leaked to any artifact."""

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from lancet_eval.client import RetrievalSnapshot, StructuredCitation
from lancet_eval.corpus import load_sample_questions
from lancet_eval.journal import Journal, RunRecord
from lancet_eval.report import render_markdown
from lancet_eval.score import score_run

SENTINEL_API_KEY = "SECRET_SENTINEL_KEY_DO_NOT_LEAK_12345"


def test_no_api_key_leak_in_any_artifact(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Proves OPENROUTER_API_KEY is never serialized to any artifact."""
    monkeypatch.setenv("OPENROUTER_API_KEY", SENTINEL_API_KEY)

    questions = load_sample_questions("multihop_rag")
    qid = questions[0].question_id

    try:
        from lancet_eval.seed import load_document_map

        doc_map = load_document_map("multihop_rag")
        doc_id = next(iter(doc_map.entries.keys()))
    except Exception:
        doc_id = "0abbe020-d26d-41e6-8d5f-f7867a3608db"

    j_path = tmp_path / "journal.jsonl"
    journal = Journal(j_path)

    rec = RunRecord(
        corpus="multihop_rag",
        question_id=qid,
        graph_arm="graph-on",
        outcome="success",
        answer="Paris is capital of France",
        index_generation="gen-test-1",
        snapshot=RetrievalSnapshot(
            index_generation="gen-test-1",
            retrieved_chunks=[
                StructuredCitation(
                    chunk_id="c1",
                    document_id=doc_id,
                    excerpt="Paris is capital",
                    rank=1,
                )
            ],
        ),
        structured_citations=[
            StructuredCitation(
                chunk_id="c1",
                document_id=doc_id,
                excerpt="Paris is capital",
                rank=1,
            )
        ],
    )
    journal.append(rec)

    verdict_resp = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({
                        "groundedness": 5,
                        "faithfulness": 5,
                        "unsupported_claims": [],
                        "rationale": "High quality answer",
                    })
                }
            }
        ]
    }
    httpx_mock.add_response(json=verdict_resp, is_reusable=True)

    client = httpx.Client()
    report = score_run(
        run_dir=tmp_path,
        no_judge=False,
        sample=1,
        api_key=SENTINEL_API_KEY,
        client=client,
    )

    # Render Markdown report
    md_content = render_markdown(report)
    md_path = tmp_path / "report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Assert sentinel absent from all 6 artifact types
    artifacts = [
        tmp_path / "report.json",
        tmp_path / "report.md",
        tmp_path / "judge_cache.json",
        tmp_path / "journal.jsonl",
        Path(__file__).resolve().parents[2] / "report.schema.json",
    ]

    for artifact in artifacts:
        if artifact.is_file():
            content_bytes = artifact.read_bytes()
            assert SENTINEL_API_KEY.encode("utf-8") not in content_bytes, (
                f"API Key leaked into artifact {artifact}"
            )
