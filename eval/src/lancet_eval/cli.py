"""Command-line interface for the Lancet evaluation harness."""

from __future__ import annotations

import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console

from lancet_eval.client import (
    HarnessStreamError,
    QueryOutcome,
    run_query,
)
from lancet_eval.config import load_settings, repo_root
from lancet_eval.dimensions import OBS_04_PLACEHOLDER, DimensionResult
from lancet_eval.report import (
    CorpusReport,
    RunMetadata,
    render_json,
    render_markdown,
)

app = typer.Typer(
    name="lancet-eval",
    help="Lancet RAG / GraphRAG evaluation harness CLI.",
    no_args_is_help=True,
)

corpus_app = typer.Typer(
    name="corpus",
    help="Corpus management commands.",
    no_args_is_help=True,
)
app.add_typer(corpus_app, name="corpus")

console = Console()


class NotImplementedInThisPlan(Exception):
    """Raised when an unimplemented sub-command is called."""


def _unimplemented(plan_msg: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {plan_msg}")
    raise typer.Exit(code=1)


@corpus_app.command("fetch")
def corpus_fetch(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus to fetch (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
    print_urls: Annotated[
        bool,
        typer.Option(
            "--print-urls",
            help="Print source URLs and exit without downloading",
        ),
    ] = False,
) -> None:
    """Fetch benchmark corpus datasets."""
    try:
        from lancet_eval.corpus import fetch_corpus

        fetch_corpus(corpus, print_urls_only=print_urls)
        if not print_urls:
            console.print(
                f"[green]Corpus '{corpus}' fetched successfully.[/green]"
            )
    except Exception as exc:
        console.print(f"[bold red]Fetch error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@corpus_app.command("sample")
def corpus_sample(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus to sample (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
) -> None:
    """Sample questions from benchmark corpus."""
    try:
        from lancet_eval.corpus import sample_corpus

        sample_corpus(corpus)
        console.print(
            f"[green]Corpus '{corpus}' sampled successfully.[/green]"
        )
    except Exception as exc:
        console.print(f"[bold red]Sampling error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("preflight")
def preflight() -> None:
    """Run preflight health and isolation checks."""
    _unimplemented("preflight will be implemented in plan 06.3-04")


@app.command("seed")
def seed() -> None:
    """Seed benchmark documents into evaluation store."""
    _unimplemented("seed will be implemented in plan 06.3-04")


@app.command("reseed")
def reseed() -> None:
    """Reseed evaluation store with clean schema."""
    _unimplemented("reseed will be implemented in plan 06.3-04")


@app.command("run")
def run_benchmark() -> None:
    """Run evaluation benchmark questions against gateway."""
    _unimplemented("run will be implemented in plan 06.3-05")


@app.command("score")
def score_benchmark() -> None:
    """Score journaled evaluation runs."""
    _unimplemented("score will be implemented in plan 06.3-05 and 06.3-06")


@app.command("report")
def generate_report() -> None:
    """Generate markdown and JSON report from scored results."""
    _unimplemented("report will be implemented in plan 06.3-07")


def get_commit_sha() -> str:
    """Get current git commit SHA or return 'unknown'."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def _normalize_ws(text: str) -> str:
    """Whitespace and case normalization for containment matching."""
    return " ".join(text.split()).lower()


@app.command("probe")
def probe(
    question: Annotated[
        str,
        typer.Option("--question", "-q", help="Probe question to evaluate"),
    ],
    gold_facts: Annotated[
        list[str],
        typer.Option("--gold-fact", "-f", help="Gold evidence fact(s)"),
    ],
    arm: Annotated[
        str,
        typer.Option(
            "--arm",
            help="Graph ablation arm (graph-on or graph-off)",
        ),
    ] = "graph-on",
    k: Annotated[
        int,
        typer.Option("--k", "-k", help="Cut-off rank for top-k retrieval evaluation"),
    ] = 4,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output directory for reports"),
    ] = None,
) -> None:
    """Probe a single question end-to-end through the evaluation harness."""
    if arm not in ("graph-on", "graph-off"):
        console.print(
            f"[bold red]Error:[/bold red] invalid arm {arm!r}. "
            "Must be 'graph-on' or 'graph-off'."
        )
        raise typer.Exit(code=1)

    disable_graph = arm == "graph-off"
    settings = load_settings()

    out_dir = out or Path(tempfile.mkdtemp(prefix="lancet-probe-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    outcome: QueryOutcome | None = None
    stream_error: str | None = None

    try:
        limits = httpx.Limits(
            max_connections=settings.max_workers,
            max_keepalive_connections=settings.max_workers,
        )
        with httpx.Client(
            base_url=settings.gateway_url,
            limits=limits,
            timeout=settings.gateway_timeout_secs,
        ) as client:
            outcome = run_query(
                client,
                query=question,
                disable_graph_context=disable_graph,
                deadline_s=settings.question_deadline_secs,
            )
    except (HarnessStreamError, httpx.TransportError, ValidationError) as exc:
        stream_error = f"{type(exc).__name__}: {exc}"

    dim_name = f"probe_evidence_recall_at_{k}"
    if stream_error is not None:
        retrieval_dim = DimensionResult(
            name=dim_name,
            status="error",
            reason=stream_error,
            n=len(gold_facts),
        )
    elif outcome is None or outcome.answer is None or outcome.answer.snapshot is None:
        retrieval_dim = DimensionResult(
            name=dim_name,
            status="skipped",
            reason="no retrieval snapshot on the response",
            n=len(gold_facts),
        )
    else:
        snapshot = outcome.answer.snapshot
        # Primary k-selection rule: rank <= k in wire order
        top_k_chunks = [c for c in snapshot.retrieved_chunks if c.rank <= k]

        matched_count = 0
        for fact in gold_facts:
            norm_fact = _normalize_ws(fact)
            if any(norm_fact in _normalize_ws(c.excerpt) for c in top_k_chunks):
                matched_count += 1

        score = (matched_count / len(gold_facts)) if gold_facts else 0.0
        retrieval_dim = DimensionResult(
            name=dim_name,
            status="ok",
            score=score,
            detail={
                "hits": float(matched_count),
                "gold_facts": float(len(gold_facts)),
            },
            n=len(gold_facts),
        )

    dimensions = [retrieval_dim, OBS_04_PLACEHOLDER]
    corr_id = outcome.correlation_id if outcome else ""
    metadata = RunMetadata(
        corpus="probe",
        generated_at=datetime.now(UTC).isoformat(),
        commit_sha=get_commit_sha(),
        sample_size_deterministic=1,
        sample_size_judged=0,
        notes=f"Single question probe (arm={arm}, correlation_id={corr_id})",
    )
    report = CorpusReport(
        corpus="probe",
        metadata=metadata,
        dimensions=dimensions,
    )

    md_content = render_markdown(report)
    json_content = render_json(report)

    with open(out_dir / "report.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(md_content)

    with open(out_dir / "report.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json_content)

    console.print(md_content)
    console.print(f"[green]Probe reports written to:[/green] {out_dir}")


def main() -> None:
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()
