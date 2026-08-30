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
            console.print(f"[green]Corpus '{corpus}' fetched successfully.[/green]")
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
        console.print(f"[green]Corpus '{corpus}' sampled successfully.[/green]")
    except Exception as exc:
        console.print(f"[bold red]Sampling error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("preflight")
def preflight_command(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus to preflight check (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
    judged: Annotated[
        bool,
        typer.Option(
            "--judged",
            help="Include judge checks and OpenRouter API key validation",
        ),
    ] = False,
) -> None:
    """Run preflight health, isolation, and model checks."""
    from rich.table import Table

    from lancet_eval.preflight import run_preflight_checks

    results = run_preflight_checks(corpus_name=corpus, judged=judged)

    table = Table(title=f"Preflight Health Checks — {corpus}")
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    all_passed = True
    for r in results:
        status_str = "[green]PASS[/green]" if r.passed else "[bold red]FAIL[/bold red]"
        if not r.passed:
            all_passed = False
        table.add_row(r.name, status_str, r.message)

    console.print(table)

    if not all_passed:
        console.print(
            "[bold red]Preflight failed. "
            "Address the issues above before running benchmark.[/bold red]"
        )
        raise typer.Exit(code=1)

    console.print("[green]All preflight checks passed successfully.[/green]")


@app.command("seed")
def seed_command(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus to seed (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
) -> None:
    """Seed benchmark documents into evaluation store."""
    try:
        from lancet_eval.seed import seed_corpus

        doc_map = seed_corpus(corpus)
        console.print(
            f"[green]Corpus '{corpus}' seeded successfully "
            f"({len(doc_map.entries)} documents mapped).[/green]"
        )
    except Exception as exc:
        console.print(f"[bold red]Seeding error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("reseed")
def reseed_command(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus to reseed (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
    confirm: Annotated[
        bool,
        typer.Option(
            "--confirm",
            help="Confirm destructive drop and recreation of evaluation store",
        ),
    ] = False,
) -> None:
    """Reseed evaluation store with clean schema."""
    try:
        from lancet_eval.seed import reseed_corpus

        doc_map = reseed_corpus(corpus, confirmation=confirm)
        console.print(
            f"[green]Corpus '{corpus}' reseeded successfully "
            f"({len(doc_map.entries)} documents mapped).[/green]"
        )
    except Exception as exc:
        console.print(f"[bold red]Reseeding error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("run")
def run_benchmark(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus to drive (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="Path to output journal file",
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-l",
            help="Limit number of questions (smoke test only, marks partial)",
        ),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume/--no-resume",
            help="Resume from existing journal and skip completed questions",
        ),
    ] = True,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            "-w",
            help="Number of concurrent worker threads",
        ),
    ] = 1,
) -> None:
    """Run evaluation benchmark questions across graph-on and graph-off arms."""
    try:
        from lancet_eval.run import drive

        if out is None:
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            out = repo_root() / "eval" / "runs" / f"{corpus}_{ts}" / "journal.jsonl"

        msg = (
            f"[bold blue]Driving corpus '{corpus}' "
            f"(limit={limit}, resume={resume}, workers={workers})...[/bold blue]"
        )
        console.print(msg)
        count = drive(
            corpus=corpus,
            journal_path=out,
            limit=limit,
            resume=resume,
            workers=workers,
        )
        console.print(
            f"[green]Successfully recorded {count} new work units to {out}[/green]"
        )
    except Exception as exc:
        console.print(f"[bold red]Run error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("score")
def score_benchmark(
    run: Annotated[
        Path,
        typer.Option(
            "--run",
            "-r",
            help="Path to run directory containing journal.jsonl",
        ),
    ],
    no_judge: Annotated[
        bool,
        typer.Option(
            "--no-judge",
            help="Compute offline deterministic metrics only without LLM judge calls",
        ),
    ] = True,
    sample: Annotated[
        int | None,
        typer.Option(
            "--sample",
            "-s",
            help="Sample size for judged evaluation pass",
        ),
    ] = None,
) -> None:
    """Score journaled evaluation runs offline."""
    try:
        from lancet_eval.score import score_run

        console.print(f"[bold blue]Scoring run at {run}...[/bold blue]")
        report = score_run(run_dir=run, no_judge=no_judge, sample=sample)
        md = render_markdown(report)
        console.print(md)
        console.print(
            f"[green]Score report written to {run / 'report.json'}[/green]"
        )
    except Exception as exc:
        console.print(f"[bold red]Score error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


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
        str | None,
        typer.Option("--question", "-q", help="Probe question to evaluate"),
    ] = None,
    gold_facts: Annotated[
        list[str] | None,
        typer.Option("--gold-fact", "-f", help="Gold evidence fact(s)"),
    ] = None,
    gold_answer: Annotated[
        str | None,
        typer.Option("--gold-answer", "-a", help="Gold answer for EM/F1 evaluation"),
    ] = None,
    corpus: Annotated[
        str | None,
        typer.Option("--corpus", "-c", help="Corpus to draw probe question from"),
    ] = None,
    question_id: Annotated[
        str | None,
        typer.Option("--question-id", "-i", help="Question ID in corpus"),
    ] = None,
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
    from lancet_eval.corpus import GoldQuestion, load_corpus
    from lancet_eval.metrics import (
        context_precision_at_k,
        em_f1,
        mrr_at_k,
        recall_at_k,
    )

    if arm not in ("graph-on", "graph-off"):
        console.print(
            f"[bold red]Error:[/bold red] invalid arm {arm!r}. "
            "Must be 'graph-on' or 'graph-off'."
        )
        raise typer.Exit(code=1)

    target_q = question
    target_facts = list(gold_facts or [])
    target_answer = gold_answer or ""
    q_id = question_id or "probe-001"

    if corpus:
        corpus_cfg = load_corpus(corpus)
        questions = corpus_cfg.questions
        if question_id:
            matched = [q for q in questions if q.question_id == question_id]
            if not matched:
                console.print(
                    f"[bold red]Error:[/bold red] question ID '{question_id}' "
                    f"not found in corpus '{corpus}'."
                )
                raise typer.Exit(code=1)
            selected_q = matched[0]
        else:
            if not questions:
                console.print(
                    f"[bold red]Error:[/bold red] corpus '{corpus}' is empty."
                )
                raise typer.Exit(code=1)
            selected_q = questions[0]

        target_q = target_q or selected_q.question
        if not target_facts:
            target_facts = selected_q.gold_facts
        if not target_answer:
            target_answer = selected_q.gold_answer
        q_id = selected_q.question_id

    if not target_q:
        console.print(
            "[bold red]Error:[/bold red] must provide either --question or --corpus."
        )
        raise typer.Exit(code=1)

    q_obj = GoldQuestion(
        question_id=q_id,
        question=target_q,
        gold_facts=target_facts,
        gold_answer=target_answer,
        evidence_list=[{"fact": f} for f in target_facts],
    )

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
                query=target_q,
                disable_graph_context=disable_graph,
                deadline_s=settings.question_deadline_secs,
            )
    except (HarnessStreamError, httpx.TransportError, ValidationError) as exc:
        stream_error = f"{type(exc).__name__}: {exc}"

    dim_name = f"probe_evidence_recall_at_{k}"
    retrieved_chunks = (
        outcome.answer.snapshot.retrieved_chunks
        if outcome and outcome.answer and outcome.answer.snapshot
        else None
    )

    dimensions: list[DimensionResult] = []

    if stream_error is not None:
        dimensions.append(
            DimensionResult(
                name=dim_name,
                status="error",
                reason=stream_error,
                n=len(target_facts),
            )
        )
    elif q_obj.is_null:
        dimensions.append(
            DimensionResult(
                name=dim_name,
                status="skipped",
                reason="null-query items excluded from retrieval evaluation",
                n=len(target_facts),
            )
        )
    else:
        rec_out = recall_at_k(q_obj, retrieved_chunks, k=k)
        if rec_out.status == "ok":
            dimensions.append(
                DimensionResult(
                    name=dim_name,
                    status="ok",
                    score=rec_out.score,
                    detail=rec_out.detail,
                    n=rec_out.n,
                )
            )
        else:
            dimensions.append(
                DimensionResult(
                    name=dim_name,
                    status=rec_out.status,  # type: ignore[arg-type]
                    reason=rec_out.reason,
                    n=rec_out.n,
                )
            )

        prec_out = context_precision_at_k(q_obj, retrieved_chunks, k=k)
        if prec_out.status == "ok":
            dimensions.append(
                DimensionResult(
                    name=f"probe_context_precision_at_{k}",
                    status="ok",
                    score=prec_out.score,
                    detail=prec_out.detail,
                    n=prec_out.n,
                )
            )

        mrr_out = mrr_at_k(q_obj, retrieved_chunks, k=10)
        if mrr_out.status == "ok":
            dimensions.append(
                DimensionResult(
                    name="probe_mrr_at_10",
                    status="ok",
                    score=mrr_out.score,
                    detail=mrr_out.detail,
                    n=mrr_out.n,
                )
            )

        if target_answer and outcome and outcome.answer:
            em, f1 = em_f1(target_answer, outcome.answer.answer)
            dimensions.append(
                DimensionResult(
                    name="probe_answer_exact_match",
                    status="ok",
                    score=em,
                    n=1,
                )
            )
            dimensions.append(
                DimensionResult(
                    name="probe_answer_f1",
                    status="ok",
                    score=f1,
                    n=1,
                )
            )

    dimensions.append(OBS_04_PLACEHOLDER)
    corr_id = outcome.correlation_id if outcome else ""
    metadata = RunMetadata(
        corpus=corpus or "probe",
        generated_at=datetime.now(UTC).isoformat(),
        commit_sha=get_commit_sha(),
        sample_size_deterministic=1,
        sample_size_judged=0,
        notes=f"Single question probe (arm={arm}, correlation_id={corr_id})",
    )
    report = CorpusReport(
        corpus=corpus or "probe",
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
