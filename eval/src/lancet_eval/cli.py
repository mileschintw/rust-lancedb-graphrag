"""Command-line interface for the Lancet evaluation harness."""

from __future__ import annotations

import math
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console

from lancet_eval.client import (
    HarnessStreamError,
    QueryOutcome,
    run_query,
)
from lancet_eval.config import get_commit_sha, load_settings, repo_root
from lancet_eval.dimensions import OBS_04_PLACEHOLDER, DimensionResult
from lancet_eval.report import (
    CorpusReport,
    RunMetadata,
    compute_result_hash,
    get_lock_hash,
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

identity_app = typer.Typer(
    name="identity",
    help="Index identity gate commands.",
    no_args_is_help=True,
)
app.add_typer(identity_app, name="identity")

calibration_app = typer.Typer(
    name="calibration",
    help="Judge calibration commands (D-113).",
    no_args_is_help=True,
)
app.add_typer(calibration_app, name="calibration")

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
    accept_known_miss: Annotated[
        list[str] | None,
        typer.Option(
            "--accept-known-miss",
            help=(
                "D-94: report one named floor miss instead of failing. Format "
                "<question_id>:<graph_arm>:<check>:<decision_id>."
            ),
        ),
    ] = None,
) -> None:
    """Run preflight health, isolation, and model checks."""
    from rich.markup import escape
    from rich.table import Table

    from lancet_eval import preflight as preflight_module

    accepted = _parse_accepted_known_misses(accept_known_miss or [], preflight_module)
    if accepted:
        results = preflight_module.run_preflight_checks(
            corpus_name=corpus, judged=judged, accepted_known_misses=accepted
        )
    else:
        results = preflight_module.run_preflight_checks(
            corpus_name=corpus, judged=judged
        )

    table = Table(title=f"Preflight Health Checks — {corpus}")
    table.add_column("Check", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    status_labels = {
        "pass": "[green]PASS[/green]",
        "fail": "[bold red]FAIL[/bold red]",
        "accepted_known_miss": "[bold yellow]ACCEPTED KNOWN MISS[/bold yellow]",
    }
    all_passed = True
    accepted_count = 0
    for r in results:
        status_str = status_labels[r.status or ("pass" if r.passed else "fail")]
        if not r.passed:
            all_passed = False
        # The accepted-miss message holds a literal "[D-94]" that Rich would drop.
        message = escape(r.message) if r.status == "accepted_known_miss" else r.message
        if r.status == "accepted_known_miss":
            accepted_count += 1
        table.add_row(r.name, status_str, message)

    console.print(table)

    for r in results:
        for entry in r.detail.get("accepted_known_misses", []):
            console.print(_known_miss_line(entry), soft_wrap=True)

    if not all_passed:
        console.print(
            "[bold red]Preflight failed. "
            "Address the issues above before running benchmark.[/bold red]"
        )
        raise typer.Exit(code=1)

    if accepted_count:
        console.print(
            "[bold yellow]Preflight cleared with accepted known misses "
            f"(not passes): {accepted_count}. Every other check passed.[/bold yellow]"
        )
        return

    console.print("[green]All preflight checks passed successfully.[/green]")


def _parse_accepted_known_misses(values: list[str], preflight_module: Any) -> list[Any]:
    """Parse and validate every --accept-known-miss value; exit 2 on any rejection."""
    from rich.markup import escape

    if not values:
        return []
    try:
        parsed = [preflight_module.parse_accepted_known_miss(v) for v in values]
        return list(preflight_module.validate_accepted_known_misses(parsed))
    except (ValueError, preflight_module.PreflightError) as exc:
        registered = ", ".join(preflight_module.registered_accepted_known_miss_values())
        console.print(
            "[bold red]Rejected --accept-known-miss:[/bold red] "
            f"{escape(str(exc))}. The only accepted value is {escape(registered)}."
        )
        raise typer.Exit(code=2) from exc


def _known_miss_line(entry: dict[str, Any]) -> str:
    """One console line for a D-94 accepted-known-miss outcome."""
    from rich.markup import escape

    who = f"canary {entry['question_id']} ({entry['graph_arm']})"
    count = entry["observed_graph_node_count"]
    if entry["outcome"] == "accepted_known_miss":
        return escape(
            f"Accepted known miss ({entry['decision_id']}): {who} {entry['check']} "
            f"observed {count} graph nodes. Reported, not passed."
        )
    return escape(
        f"Canary {entry['question_id']} ({entry['graph_arm']}) met its "
        f"{entry['check']} floor: observed {count} graph nodes; "
        f"{entry['decision_id']} exception not used."
    )


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


@identity_app.command("check")
def identity_check(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus to check identity for (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
) -> None:
    """Run the three-way index identity comparison and print the report."""
    from lancet_eval.identity import compute_identity

    settings = load_settings()
    report = compute_identity(settings, corpus)
    console.print_json(data=report.model_dump())

    if not report.passed:
        console.print("[bold red]Identity gate FAILED.[/bold red]")
        raise typer.Exit(code=1)

    console.print("[green]Identity gate passed.[/green]")


@identity_app.command("pg-delete-extras")
def identity_pg_delete_extras(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus whose document map defines the allowed document IDs",
        ),
    ] = "multihop_rag",
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help="Apply the delete (default: dry-run, prints extras only)",
        ),
    ] = False,
    pg_dump: Annotated[
        Path | None,
        typer.Option(
            "--pg-dump",
            help=(
                "Path to an existing non-empty pg_dump backup file, "
                "required with --apply"
            ),
        ),
    ] = None,
) -> None:
    """Delete PostgreSQL documents outside the corpus's map (dry-run by default)."""
    from lancet_eval.identity import delete_pg_extras
    from lancet_eval.seed import load_document_map

    settings = load_settings()
    try:
        doc_map = load_document_map(corpus)
        allow_ids = set(doc_map.entries.keys())
        result = delete_pg_extras(
            settings, allow_ids, apply=apply, pg_dump_path=pg_dump
        )
    except Exception as exc:
        console.print(f"[bold red]pg-delete-extras error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if apply:
        console.print(
            f"[green]Deleted {len(result)} extra document(s): {result}[/green]"
        )
    else:
        console.print(
            f"[yellow]Dry run: {len(result)} extra document(s) would be deleted: "
            f"{result}[/yellow]"
        )


def resolve_run_dir(corpus: str, resume: bool, runs_root: Path | None = None) -> Path:
    """Resolve the run-record directory for a drive.

    When resume is True and one or more directories matching ????-??-??-<corpus>
    exist under runs_root, reuses the lexicographically newest (latest ISO date).
    Otherwise returns runs_root / f"{today}-{corpus}".
    """
    root = runs_root if runs_root is not None else repo_root() / "eval" / "runs"
    if resume and root.exists():
        matching = [p for p in root.glob(f"????-??-??-{corpus}") if p.is_dir()]
        if matching:
            return max(matching, key=lambda p: p.name)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return root / f"{today}-{corpus}"


def _validate_stage_cap(value: float | None) -> float | None:
    """Reject a --stage-cap that cannot fire (WR-02, D-86).

    A NaN makes every ``spend >= cap`` comparison false, infinity is never reached,
    and a non-positive cap is meaningless as a spend ceiling, so each would silently
    disable the stop rule. ``None`` passes through for commands where the cap is
    optional (``score``). Runs during parameter parsing, before any command body.
    """
    if value is None:
        return None
    if not (math.isfinite(value) and value > 0):
        raise typer.BadParameter(
            "the stage spend cap must be a finite positive USD amount "
            f"(got {value!r})"
        )
    return value


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
    retries: Annotated[
        int,
        typer.Option(
            "--retries",
            "-r",
            help="Maximum retries per work unit if query early terminates or fails",
        ),
    ] = 2,
    stage_cap: Annotated[
        float,
        typer.Option(
            "--stage-cap",
            help="Stage spend cap in USD (fail-closed, required with no silent default)",
            callback=_validate_stage_cap,
        ),
    ] = ...,
    gate_stage: Annotated[
        str | None,
        typer.Option(
            "--gate-stage",
            help=(
                "Declare this a gate-stage drive: the label that "
                "'unpark_gates --stage' will be given. Recorded in the journal "
                "header (with max_retries) and requires --retries 0."
            ),
        ),
    ] = None,
) -> None:
    """Run evaluation benchmark questions across the corpus's arms."""
    if gate_stage is not None:
        if not gate_stage.strip() or any(ch.isspace() for ch in gate_stage):
            raise typer.BadParameter(
                "the gate-stage label must be non-empty and contain no whitespace",
                param_hint="'--gate-stage'",
            )
        if retries != 0:
            raise typer.BadParameter(
                f"a gate-stage drive requires --retries 0 (got {retries}); "
                "a retry would replace an attempt the gates must see (D-67)",
                param_hint="'--retries'",
            )
    try:
        from lancet_eval.run import drive

        if out is None:
            run_dir = resolve_run_dir(corpus=corpus, resume=resume)
            out = run_dir / "journal.jsonl"

        console.print(f"[dim]Resolved run directory: {out.parent}[/dim]")
        msg = (
            f"[bold blue]Driving corpus '{corpus}' "
            f"(limit={limit}, resume={resume}, workers={workers}, retries={retries}, "
            f"gate_stage={gate_stage}, stage_cap=${stage_cap:.2f})...[/bold blue]"
        )
        console.print(msg)
        settings = load_settings()
        count = drive(
            corpus=corpus,
            journal_path=out,
            stage_spend_cap=stage_cap,
            settings=settings,
            limit=limit,
            resume=resume,
            workers=workers,
            max_retries=retries,
            gate_stage=gate_stage,
        )
        stopped = getattr(count, "stopped_by_cap", False)
        spend = getattr(count, "observed_spend", 0.0)
        if stopped:
            console.print(
                f"[yellow]Drive stopped early: reached stage spend cap (${stage_cap:.2f}); "
                f"recorded {count} work units (observed spend: ${spend:.4f})[/yellow]"
            )
        else:
            console.print(
                f"[green]Successfully recorded {count} new work units to {out} "
                f"(observed spend: ${spend:.4f})[/green]"
            )
    except Exception as exc:
        console.print(f"[bold red]Run error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("staged-gate")
def staged_gate(
    run: Annotated[
        Path,
        typer.Option(
            "--run",
            "-r",
            help="Run directory containing journal to evaluate against staged gate",
        ),
    ],
) -> None:
    """Evaluate staged run against committed floors and render verdict."""
    try:
        from lancet_eval.gate import (
            evaluate_staged_gate,
            read_store_suspension,
            render_staged_gate_verdict,
        )
        from lancet_eval.journal import load_records
        from lancet_eval.score import score_run

        console.print(f"[bold blue]Evaluating staged gate for {run}...[/bold blue]")
        report = score_run(
            run_dir=run,
            no_judge=True,
        )
        is_suspended = read_store_suspension()
        journal_path = run / "journal.jsonl"
        records = load_records(journal_path) if journal_path.exists() else []
        distinct_q = len({r.question_id for r in records})

        verdict = evaluate_staged_gate(
            report=report,
            is_suspended=is_suspended,
            distinct_questions_in_journal=distinct_q,
        )
        json_path, md_path = render_staged_gate_verdict(verdict, run)
        console.print(f"[green]Staged gate verdict: {verdict.overall_status}[/green]")
        console.print(f"Machine-readable verdict: {json_path}")
        console.print(f"Human-readable verdict: {md_path}")
        if verdict.overall_status not in ("pass", "investigate"):
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[bold red]Staged gate error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("reconcile")
def reconcile_run(
    run: Annotated[
        Path,
        typer.Option(
            "--run",
            "-r",
            help="Run directory containing journal to reconcile",
        ),
    ],
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus name (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
) -> None:
    """Reconcile journal header to reflect measured completeness. Non-zero exit indicates run is not publishable, but does not imply nothing was written."""
    try:
        from lancet_eval.journal import reconcile_header

        journal_path = run / "journal.jsonl"
        publishable, header_changed, msg = reconcile_header(journal_path=journal_path, corpus=corpus)
        if publishable:
            console.print(f"[green]{msg}[/green]")
        elif header_changed:
            # Header was corrected to staged on disk; non-zero exit signifies run is unpublishable
            console.print(f"[bold yellow]Header corrected to staged:[/bold yellow] {msg}. Run remains unpublishable.")
            raise typer.Exit(code=1)
        else:
            console.print(f"[bold red]Reconciliation rejected:[/bold red] {msg}")
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[bold red]Reconcile error:[/bold red] {exc}")
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
            "--no-judge/--judge",
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
    emit_calibration_worksheet: Annotated[
        Path | None,
        typer.Option(
            "--emit-calibration-worksheet",
            help="Path to write calibration worksheet JSONL file",
        ),
    ] = None,
    calibration_file: Annotated[
        Path | None,
        typer.Option(
            "--calibration-file",
            help="Path to human-scored calibration worksheet JSONL file",
        ),
    ] = None,
    stage_cap: Annotated[
        float | None,
        typer.Option(
            "--stage-cap",
            help="Stage spend cap in USD. Required when --judge is enabled to bound accumulated judged spend.",
            callback=_validate_stage_cap,
        ),
    ] = None,
    judged: Annotated[
        bool,
        typer.Option(
            "--judged/--no-judged",
            help=(
                "Compute the judged aggregates of an ordered-protocol corpus from "
                "the cached stage and the owner-scored worksheet (D-113, D-120). "
                "Needs --calibration-file and --calibration-key; the salt is read "
                "from calibration-salt.txt beside the key."
            ),
        ),
    ] = False,
    calibration_key: Annotated[
        Path | None,
        typer.Option(
            "--calibration-key",
            help=(
                "Path to the revealed calibration-key.jsonl (with --judged); "
                "calibration-salt.txt must sit beside it"
            ),
        ),
    ] = None,
) -> None:
    """Score journaled evaluation runs offline or with LLM judge."""
    # Usage errors are raised outside the try block so they keep exit code 2.
    if judged:
        missing = [
            flag
            for flag, value in (
                ("--calibration-file", calibration_file),
                ("--calibration-key", calibration_key),
            )
            if value is None
        ]
        if missing:
            raise typer.BadParameter(f"--judged also needs {' and '.join(missing)}")
        if not no_judge or emit_calibration_worksheet is not None:
            raise typer.BadParameter(
                "--judged is cache-only and cannot be combined with --judge or "
                "--emit-calibration-worksheet"
            )
        if sample is not None or stage_cap is not None:
            raise typer.BadParameter(
                "--judged judges nothing new, so --sample and --stage-cap do not apply"
            )
    elif calibration_key is not None:
        raise typer.BadParameter("--calibration-key only applies with --judged")
    try:
        from lancet_eval.score import score_run

        if judged and calibration_key is not None:
            from lancet_eval.calibration import SALT_FILE

            salt_path = calibration_key.parent / SALT_FILE
            if not salt_path.is_file():
                raise FileNotFoundError(
                    f"the salt file {salt_path} is missing; the reveal copies "
                    f"{SALT_FILE} beside the key"
                )
        console.print(f"[bold blue]Scoring run at {run}...[/bold blue]")
        report = score_run(
            run_dir=run,
            no_judge=no_judge,
            sample=sample,
            emit_calibration_worksheet=emit_calibration_worksheet,
            calibration_file=calibration_file,
            stage_spend_cap=stage_cap,
            judged=judged,
            calibration_key=calibration_key,
        )
        md = render_markdown(report)
        console.print(md)
        console.print(f"[green]Score report written to {run / 'report.json'}[/green]")
    except Exception as exc:
        console.print(f"[bold red]Score error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


def _print_judge_stage(record: Any) -> None:
    """Prints the judge stage's counts, spend and timings. Never a score (D-120)."""

    def line(text: str, **kwargs: Any) -> None:
        console.print(text, markup=False, highlight=False, soft_wrap=True, **kwargs)

    line(
        f"Judge stage ({record.mode}): {record.judge_model}, "
        f"prompt {record.judge_prompt_version}"
    )
    line(
        f"{'arm':<14}{'judgeable':>10}{'unique':>8}{'cached':>8}{'judged':>8}"
        f"{'errors':>8}{'retried':>9}{'pending':>9}"
    )
    for arm, c in record.arms.items():
        line(
            f"{arm:<14}{c.judgeable:>10}{c.unique_keys:>8}{c.cached_before:>8}"
            f"{c.judged_now:>8}{c.errors:>8}{c.re_attempted:>9}{c.not_attempted:>9}"
        )
    line(
        f"calls {record.calls}, unique keys {record.unique_keys_total}, "
        f"spend ${record.spend_usd:.6f} of cap ${record.stage_cap:.6f}, "
        f"wall-clock {record.wall_clock_s:.1f}s"
    )
    if record.per_call_latency_ms_p50 is not None:
        line(
            f"per-call latency p50 {record.per_call_latency_ms_p50:.0f} ms, "
            f"p95 {record.per_call_latency_ms_p95:.0f} ms"
        )


@app.command("judge")
def judge_benchmark(
    run: Annotated[
        Path,
        typer.Option(
            "--run",
            "-r",
            help="Closed run directory holding journal.jsonl",
        ),
    ],
    stage_cap: Annotated[
        float,
        typer.Option(
            "--stage-cap",
            help="Stage spend cap in USD, as authorised at the D-86 checkpoint",
            callback=_validate_stage_cap,
        ),
    ],
    rehearsal: Annotated[
        bool,
        typer.Option(
            "--rehearsal/--no-rehearsal",
            help="Judge a rehearsal-role corpus's own records (D-106 c); prints "
            "counts and per-call latency only",
        ),
    ] = False,
) -> None:
    """Judge every judgeable record of every arm into judge_cache.json (D-112).

    Cache-only and counts-only: the stage writes the judge cache and judge-stage.json
    and shows counts, spend and latency. It never computes a judged score, mean, delta
    or agreement figure, and never writes report.json (D-120 step 1).
    """
    from lancet_eval.judge_stage import run_judge_stage

    try:
        record = run_judge_stage(run_dir=run, stage_cap=stage_cap, rehearsal=rehearsal)
    except Exception as exc:
        console.print(
            f"Judge stage refused: {exc}",
            style="bold red",
            markup=False,
            soft_wrap=True,
        )
        raise typer.Exit(code=1) from exc
    _print_judge_stage(record)
    if record.stop_reason is not None:
        console.print(
            f"Judge stage stopped early: {record.stop_reason}",
            style="bold yellow",
            markup=False,
            soft_wrap=True,
        )
        console.print(
            "Resuming needs a new D-86 checkpoint.", markup=False, soft_wrap=True
        )
        raise typer.Exit(code=1)
    console.print("Wrote judge-stage.json and judge_cache.json.", markup=False)


@calibration_app.command("emit")
def calibration_emit(
    run: Annotated[
        Path,
        typer.Option(
            "--run",
            "-r",
            help="Closed run directory whose judge stage completed",
        ),
    ],
) -> None:
    """Draw the blinded 20-item calibration slice and write its worksheet (D-113).

    Makes no API call and shows counts only. The worksheet is written into the run
    directory; the key file and salt go under the gitignored data/calibration-keys/ and
    stay uncommitted until the reveal (D-120 step 2).
    """
    from lancet_eval.calibration import emit_worksheet

    def line(text: str, **kwargs: Any) -> None:
        console.print(text, markup=False, highlight=False, soft_wrap=True, **kwargs)

    try:
        result = emit_worksheet(run)
    except Exception as exc:
        line(f"Calibration emit refused: {exc}", style="bold red")
        raise typer.Exit(code=1) from exc
    line(f"Calibration worksheet emitted: {result.n_items} rows.")
    line(f"Emitted at {result.emitted_at_sha}; key_sha256 {result.key_sha256}.")
    line(f"Commit the worksheet only: {result.git_add}")
    line(
        "The key file and salt stay uncommitted under data/calibration-keys/ until "
        "the owner's scores are committed (06.3.5-17)."
    )


@app.command("report")
def generate_report(
    run: Annotated[
        Path,
        typer.Option(
            "--run",
            "-r",
            help="Path to run directory containing report.json or journal.jsonl",
        ),
    ],
    compare_to: Annotated[
        Path | None,
        typer.Option(
            "--compare-to",
            "-c",
            help="Optional path to previous run directory for sample size comparison",
        ),
    ] = None,
) -> None:
    """Generate final Markdown and JSON evaluation report from a run directory."""
    try:
        import json

        from lancet_eval.report import (
            CorpusReport,
            ReportError,
            RunMetadata,
            render_json,
            render_markdown,
        )

        report_json_path = run / "report.json"
        if not report_json_path.is_file():
            from lancet_eval.score import score_run

            report = score_run(run_dir=run, no_judge=True)
        else:
            with open(report_json_path, encoding="utf-8") as f:
                data = json.load(f)
            report = CorpusReport.model_validate(data)

        if report.metadata.partial:
            raise ReportError(
                "Cannot render report for incomplete run (partial: true): "
                "completeness comparison did not confirm every committed work unit was driven. "
                "Use 'lancet-eval reconcile' to re-check and correct header."
            )

        compare_meta: RunMetadata | None = None
        if compare_to is not None:
            comp_report_path = compare_to / "report.json"
            comp_meta_path = compare_to / "metadata.json"
            if comp_report_path.is_file():
                with open(comp_report_path, encoding="utf-8") as f:
                    comp_data = json.load(f)
                compare_meta = CorpusReport.model_validate(comp_data).metadata
            elif comp_meta_path.is_file():
                with open(comp_meta_path, encoding="utf-8") as f:
                    comp_meta_data = json.load(f)
                compare_meta = RunMetadata.model_validate(comp_meta_data)

        md_text = render_markdown(report, compare_to_metadata=compare_meta)
        report_md_path = run / "report.md"
        with open(report_md_path, "w", encoding="utf-8") as f:
            f.write(md_text)

        with open(run / "report.json", "w", encoding="utf-8") as f:
            f.write(render_json(report))

        with open(run / "metadata.json", "w", encoding="utf-8") as f:
            f.write(report.metadata.model_dump_json(indent=2) + "\n")

        console.print(md_text)
        console.print(
            f"[green]Report successfully rendered to {report_md_path}[/green]"
        )
    except Exception as exc:
        console.print(f"[bold red]Report error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command("compare")
def compare_benchmark(
    run: Annotated[
        Path,
        typer.Option(
            "--run",
            "-r",
            help=(
                "Run directory that `score --judged` has passed (it holds report.json "
                "and judged-result.json)"
            ),
        ),
    ],
) -> None:
    """Write the four-arm comparison sidecars of a scored, judged run (D-115, D-126).

    Offline and read-only on the run's inputs: it writes comparison.json,
    comparison.md, chart.json and chart.svg into the run directory, never opens the
    judge cache and never modifies report.json. It refuses unless report.json carries
    the judged dimensions and judged-result.json exists.
    """
    from lancet_eval.comparison import write_comparison

    def line(text: str, **kwargs: Any) -> None:
        console.print(text, markup=False, highlight=False, soft_wrap=True, **kwargs)

    try:
        comparison = write_comparison(run)
    except Exception as exc:
        line(f"Compare refused: {exc}", style="bold red")
        raise typer.Exit(code=1) from exc
    p4 = comparison.p4
    line(
        f"Four-arm comparison of {comparison.run.corpus}: |P4| = {p4.n_p4} of "
        f"{p4.n_heldout_g} held-out G questions (coverage {p4.coverage:.4f}, "
        f"evaluable: {'yes' if p4.evaluable else 'no'})."
    )
    for family in comparison.families:
        reads = ", ".join(f"{c.arm}: {c.decision}" for c in family.comparisons)
        line(f"Holm family {family.primary}: {reads}")
    for name in comparison_files():
        line(f"Wrote {run / name}")


def comparison_files() -> tuple[str, ...]:
    """The sidecars `compare` writes into the run directory."""
    return ("comparison.json", "comparison.md")


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
            help=(
                "Retrieval arm: dense-only, bm25-only, hybrid, hybrid+graph "
                "(aliases: graph-off = hybrid, graph-on = hybrid+graph)"
            ),
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
    from lancet_eval.arms import request_fields, resolve_arm
    from lancet_eval.corpus import GoldQuestion, load_corpus
    from lancet_eval.metrics import (
        context_precision_at_k,
        em_f1,
        mrr_at_k,
        recall_at_k,
    )

    try:
        resolve_arm(arm)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] invalid arm. {exc}")
        raise typer.Exit(code=2) from exc

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
                deadline_s=settings.question_deadline_secs,
                **request_fields(arm),
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
    res_hash = compute_result_hash(dimensions)
    lock_hash = get_lock_hash()
    index_gen = (
        outcome.answer.snapshot.index_generation
        if outcome and outcome.answer and outcome.answer.snapshot
        else "gen-probe"
    )
    metadata = RunMetadata(
        corpus=corpus or "probe",
        run_date=datetime.now(UTC).isoformat(),
        commit_sha=get_commit_sha(),
        generation_model="deepseek/deepseek-v4-flash-0731",
        embedding_model="voyageai/voyage-4-large",
        judge_model="meta-llama/llama-3.3-70b-instruct",
        judge_prompt_version="v1",
        index_generation=index_gen,
        result_hash=res_hash,
        dependency_lock_hash=lock_hash,
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


@app.command("measure")
def measure_latency(
    corpus: Annotated[
        str,
        typer.Option(
            "--corpus",
            "-c",
            help="Corpus to measure (e.g. multihop_rag)",
        ),
    ] = "multihop_rag",
    sample_size: Annotated[
        int,
        typer.Option(
            "--sample-size",
            "-n",
            help=(
                "Number of questions to measure "
                "(issues two queries per question across both arms)"
            ),
        ),
    ] = 10,
    segment_boundary: Annotated[
        int,
        typer.Option(
            "--segment-boundary",
            help="Ordinal boundary at which to switch from segment-1 to segment-2",
        ),
    ] = 500,
    cheap_model: Annotated[
        str,
        typer.Option(
            "--cheap-model",
            help="Generation model to use for measurement pass",
        ),
    ] = "deepseek/deepseek-v4-flash-0731",
    stage_cap: Annotated[
        float,
        typer.Option(
            "--stage-cap",
            help=(
                "Maximum spend cap in USD for this measurement stage "
                "(required, no default; a finite positive amount)"
            ),
            callback=_validate_stage_cap,
        ),
    ] = ...,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="Output directory for measurement pass",
        ),
    ] = None,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            "-w",
            help="Number of concurrent worker threads",
        ),
    ] = 1,
) -> None:
    """Run two-armed latency measurement pass and derive proposed timeout budgets."""
    from lancet_eval.measure import run_measurement_pass

    try:
        run_dir, summary = run_measurement_pass(
            corpus_name=corpus,
            sample_size_questions=sample_size,
            segment_boundary_ordinal=segment_boundary,
            stage_spend_cap=stage_cap,
            output_dir=out,
            workers=workers,
        )
        console.print(
            f"[green]Measurement pass complete. Results written to:[/green] {run_dir}"
        )
        console.print(f"Total queries: {summary.get('total_records_emitted')}")
        spend_usd = summary.get("spend_summary", {}).get("spend_usd", 0.0)
        console.print(f"Observed spend: ${spend_usd:.4f}")
        if summary.get("stopped_by_cap"):
            console.print(
                "[yellow]Measurement pass stopped early at the stage spend cap "
                f"(${stage_cap:.4f}): measured "
                f"{summary.get('total_records_emitted')} of "
                f"{summary.get('work_units_planned')} planned work units.[/yellow]"
            )
    except Exception as exc:
        console.print(f"[red]Measurement pass failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc


def main() -> None:
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()
