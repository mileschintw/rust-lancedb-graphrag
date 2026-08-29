"""Tests for the probe CLI command and unimplemented sub-command surface."""

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from lancet_eval.cli import app

runner = CliRunner()


def test_cli_help_lists_all_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in (
        "corpus",
        "preflight",
        "seed",
        "reseed",
        "run",
        "score",
        "report",
        "probe",
    ):
        assert cmd in result.output

    corpus_result = runner.invoke(app, ["corpus", "--help"])
    assert corpus_result.exit_code == 0
    assert "fetch" in corpus_result.output
    assert "sample" in corpus_result.output


@pytest.mark.parametrize(
    "args,expected_plan",
    [
        (["run"], "06.3-05"),
        (["score"], "06.3-05"),
        (["report"], "06.3-07"),
    ],
)
def test_unimplemented_subcommands_exit_nonzero_naming_plan(
    args: list[str], expected_plan: str
) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code != 0
    assert expected_plan in result.output


def test_corpus_fetch_print_urls() -> None:
    result = runner.invoke(
        app, ["corpus", "fetch", "--corpus", "multihop_rag", "--print-urls"]
    )
    assert result.exit_code == 0
    assert "MultiHopRAG.json" in result.output
    assert "corpus.json" in result.output


def test_probe_matching_hit(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    raw_sse = (
        "event: final_answer\n"
        'data: {"answer":"CEO is Sam Altman.",'
        '"snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[{"chunk_id":"c1","document_id":"d1","rank":1,'
        '"excerpt":"Sam Altman serves as CEO of OpenAI."}]}}\n\n'
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"CEO is Sam Altman.",'
        '"snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[{"chunk_id":"c1","document_id":"d1","rank":1,'
        '"excerpt":"Sam Altman serves as CEO of OpenAI."}]}}}\n\n'
    )
    httpx_mock.add_response(
        url="http://localhost:8080/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    out_dir = tmp_path / "probe_hit"
    result = runner.invoke(
        app,
        [
            "probe",
            "-q",
            "Who is CEO?",
            "-f",
            "Sam Altman",
            "-o",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0
    assert (out_dir / "report.md").is_file()
    assert (out_dir / "report.json").is_file()

    with open(out_dir / "report.json", encoding="utf-8") as f:
        data = json.load(f)

    dims = {d["name"]: d for d in data["dimensions"]}
    assert "probe_evidence_recall_at_4" in dims
    assert dims["probe_evidence_recall_at_4"]["status"] == "ok"
    assert dims["probe_evidence_recall_at_4"]["score"] == 1.0

    assert "community_summary_quality" in dims
    assert dims["community_summary_quality"]["status"] == "skipped"


def test_probe_matching_miss(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    raw_sse = (
        "event: final_answer\n"
        'data: {"answer":"CEO is someone else.",'
        '"snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[{"chunk_id":"c1","document_id":"d1","rank":1,'
        '"excerpt":"Greg Brockman is the president."}]}}\n\n'
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"CEO is someone else.",'
        '"snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[{"chunk_id":"c1","document_id":"d1","rank":1,'
        '"excerpt":"Greg Brockman is the president."}]}}}\n\n'
    )
    httpx_mock.add_response(
        url="http://localhost:8080/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    out_dir = tmp_path / "probe_miss"
    result = runner.invoke(
        app,
        [
            "probe",
            "-q",
            "Who is CEO?",
            "-f",
            "Sam Altman",
            "-o",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0

    with open(out_dir / "report.json", encoding="utf-8") as f:
        data = json.load(f)

    dims = {d["name"]: d for d in data["dimensions"]}
    assert dims["probe_evidence_recall_at_4"]["status"] == "ok"
    assert dims["probe_evidence_recall_at_4"]["score"] == 0.0


def test_probe_stream_error_frame(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    raw_sse = (
        'event: node_started\ndata: {"node_name":"Retrieve"}\n\n'
        'event: stream_error\ndata: {"code":"STREAM_EOF_WITHOUT_TERMINAL",'
        '"message":"connection reset"}\n\n'
    )
    httpx_mock.add_response(
        url="http://localhost:8080/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    out_dir = tmp_path / "probe_err"
    result = runner.invoke(
        app,
        [
            "probe",
            "-q",
            "Who is CEO?",
            "-f",
            "Sam Altman",
            "-o",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0

    with open(out_dir / "report.json", encoding="utf-8") as f:
        data = json.load(f)

    dims = {d["name"]: d for d in data["dimensions"]}
    assert dims["probe_evidence_recall_at_4"]["status"] == "error"
    assert dims["probe_evidence_recall_at_4"]["score"] is None
    assert "StreamAborted" in dims["probe_evidence_recall_at_4"]["reason"]


def test_probe_scores_retrieved_chunks_not_structured_citations(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    # structured_citations has match, retrieved_chunks does NOT -> must score 0.0
    raw_sse = (
        "event: final_answer\n"
        'data: {"answer":"CEO is Sam Altman.",'
        '"structured_citations":[{"chunk_id":"c-cited","document_id":"d1","rank":1,'
        '"excerpt":"Sam Altman is the CEO."}],'
        '"snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[{"chunk_id":"c-other","document_id":"d2","rank":1,'
        '"excerpt":"Unrelated company history."}]}}\n\n'
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"CEO is Sam Altman.",'
        '"structured_citations":[{"chunk_id":"c-cited","document_id":"d1","rank":1,'
        '"excerpt":"Sam Altman is the CEO."}],'
        '"snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[{"chunk_id":"c-other","document_id":"d2","rank":1,'
        '"excerpt":"Unrelated company history."}]}}}\n\n'
    )
    httpx_mock.add_response(
        url="http://localhost:8080/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=raw_sse,
    )

    out_dir = tmp_path / "probe_retrieved_check"
    result = runner.invoke(
        app,
        [
            "probe",
            "-q",
            "Who is CEO?",
            "-f",
            "Sam Altman",
            "-o",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0

    with open(out_dir / "report.json", encoding="utf-8") as f:
        data = json.load(f)

    dims = {d["name"]: d for d in data["dimensions"]}
    assert dims["probe_evidence_recall_at_4"]["score"] == 0.0


def _build_probe_sse(chunks: list[dict[str, object]]) -> str:
    payload = {
        "answer": "CEO is Sam Altman.",
        "snapshot": {
            "index_generation": "gen-1",
            "retrieved_chunks": chunks,
        },
    }
    dumped = json.dumps(payload)
    wc_data = json.dumps({"success": True, "final_response": payload})
    return (
        f"event: final_answer\ndata: {dumped}\n\n"
        f"event: workflow_completed\ndata: {wc_data}\n\n"
    )


def test_probe_rank_le_k_rule_discriminator(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    # Entry with match is rank=9 -> outside k=4 -> 0.0
    chunks_rank9 = [
        {"chunk_id": "c1", "document_id": "d1", "rank": 1, "excerpt": "Overview."},
        {"chunk_id": "c2", "document_id": "d2", "rank": 9, "excerpt": "Altman CEO."},
    ]
    # Same entry carrying rank=3 -> within k=4 -> 1.0
    chunks_rank3 = [
        {"chunk_id": "c1", "document_id": "d1", "rank": 1, "excerpt": "Overview."},
        {"chunk_id": "c2", "document_id": "d2", "rank": 3, "excerpt": "Altman CEO."},
    ]

    httpx_mock.add_response(
        url="http://localhost:8080/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=_build_probe_sse(chunks_rank9),
    )
    httpx_mock.add_response(
        url="http://localhost:8080/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=_build_probe_sse(chunks_rank3),
    )

    out_dir_9 = tmp_path / "probe_rank9"
    res9 = runner.invoke(
        app,
        ["probe", "-q", "Who?", "-f", "Altman CEO", "-k", "4", "-o", str(out_dir_9)],
    )
    assert res9.exit_code == 0
    with open(out_dir_9 / "report.json", encoding="utf-8") as f:
        data9 = json.load(f)
    assert data9["dimensions"][0]["score"] == 0.0

    out_dir_3 = tmp_path / "probe_rank3"
    res3 = runner.invoke(
        app,
        ["probe", "-q", "Who?", "-f", "Altman CEO", "-k", "4", "-o", str(out_dir_3)],
    )
    assert res3.exit_code == 0
    with open(out_dir_3 / "report.json", encoding="utf-8") as f:
        data3 = json.load(f)
    assert data3["dimensions"][0]["score"] == 1.0


def test_probe_arm_flag_and_validation(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    resp_sse = (
        "event: final_answer\n"
        'data: {"answer":"ok","snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[]}}\n\n'
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"ok",'
        '"snapshot":{"index_generation":"gen-1","retrieved_chunks":[]}}}\n\n'
    )
    httpx_mock.add_response(
        url="http://localhost:8080/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=resp_sse,
    )

    out_dir = tmp_path / "probe_arm"
    res = runner.invoke(
        app,
        [
            "probe",
            "-q",
            "q",
            "-f",
            "f",
            "--arm",
            "graph-off",
            "-o",
            str(out_dir),
        ],
    )
    assert res.exit_code == 0

    reqs = httpx_mock.get_requests()
    assert len(reqs) == 1
    req_body = json.loads(reqs[0].read().decode("utf-8"))
    assert req_body.get("disable_graph_context") is True

    # Invalid arm fails
    res_bad = runner.invoke(
        app,
        ["probe", "-q", "q", "-f", "f", "--arm", "invalid-arm"],
    )
    assert res_bad.exit_code != 0


def test_probe_with_corpus_and_question_id(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    resp_sse = (
        "event: final_answer\n"
        'data: {"answer":"Dr. Jane Doe",'
        '"snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[{"chunk_id":"c1","document_id":"d1","rank":1,'
        '"excerpt":"Project Delta is directed by Dr. Jane Doe."}]}}\n\n'
        "event: workflow_completed\n"
        'data: {"success":true,"final_response":{"answer":"Dr. Jane Doe",'
        '"snapshot":{"index_generation":"gen-1",'
        '"retrieved_chunks":[{"chunk_id":"c1","document_id":"d1","rank":1,'
        '"excerpt":"Project Delta is directed by Dr. Jane Doe."}]}}}\n\n'
    )
    httpx_mock.add_response(
        url="http://localhost:8080/rag/query",
        status_code=200,
        headers={"content-type": "text/event-stream"},
        text=resp_sse,
    )

    out_dir = tmp_path / "probe_corpus"
    res = runner.invoke(
        app,
        [
            "probe",
            "--corpus",
            "graphrag_bench",
            "--question-id",
            "grb-003",
            "-o",
            str(out_dir),
        ],
    )
    assert res.exit_code == 0

    with open(out_dir / "report.json", encoding="utf-8") as f:
        data = json.load(f)

    dims = {d["name"]: d for d in data["dimensions"]}
    assert dims["probe_evidence_recall_at_4"]["score"] == 1.0
    assert dims["probe_context_precision_at_4"]["score"] == 1.0
    assert dims["probe_mrr_at_10"]["score"] == 1.0
    assert dims["probe_answer_exact_match"]["score"] == 1.0
    assert dims["probe_answer_f1"]["score"] == 1.0
