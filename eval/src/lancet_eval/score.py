"""Offline deterministic evaluation scorer reading committed journals."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lancet_eval.corpus import (
    load_corpus_config,
    load_sample_questions,
)
from lancet_eval.dimensions import (
    NOTICE_CODE_GRAPH_ABLATION,
    NOTICE_CODE_GRAPH_UNAVAILABLE,
    OBS_04_PLACEHOLDER,
    DimensionResult,
    make_graph_ablation_delta,
)
from lancet_eval.journal import RunRecord
from lancet_eval.metrics import (
    abstention_rate,
    context_precision_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    squad_em,
    squad_f1,
)
from lancet_eval.report import CorpusReport, RunMetadata, render_json
from lancet_eval.seed import load_document_map


class ScoreError(Exception):
    """Raised when score encounters corrupt, invalid, or unmapped journal data."""


def _check_provenance(record: RunRecord) -> bool:
    """Verify that a graph-off record carries ablation notice and not unavailable."""
    has_ablation = any(
        n.typed_code == NOTICE_CODE_GRAPH_ABLATION or n.code == "GRAPH_ABLATION"
        for n in record.notices
    )
    has_unavailable = any(
        n.typed_code == NOTICE_CODE_GRAPH_UNAVAILABLE
        or n.code == "GRAPH_UNAVAILABLE"
        for n in record.notices
    )
    return has_ablation and not has_unavailable


def score_run(
    *,
    run_dir: Path | str,
    no_judge: bool = True,
    sample: int | None = None,
) -> CorpusReport:
    """Read a run journal and produce a scored evaluation report offline."""
    dir_path = Path(run_dir)
    journal_path = dir_path / "journal.jsonl"
    if not journal_path.is_file():
        journal_path = dir_path / "journal.json"
    if not journal_path.is_file():
        raise ScoreError(f"No journal file found in {dir_path}")

    # Read journal records
    records: list[RunRecord] = []
    header_corpus: str | None = None
    with open(journal_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
            except Exception as e:
                raise ScoreError(
                    f"Corrupted JSON in journal at line {line_num}: {e}"
                ) from e

            if isinstance(data, dict) and data.get("type") == "header":
                header_corpus = data.get("corpus")
                continue

            if isinstance(data, dict) and "question_id" in data:
                try:
                    rec = RunRecord.model_validate(data)
                    records.append(rec)
                except Exception as e:
                    raise ScoreError(
                        f"Invalid RunRecord at line {line_num}: {e}"
                    ) from e

    if not records:
        raise ScoreError(f"Journal {journal_path} contains no evaluation records")

    corpus_name = header_corpus or records[0].corpus

    # 1. Structural Guard: Refuse mixed index_generation
    distinct_gens: set[str] = set()
    for rec in records:
        if rec.index_generation:
            distinct_gens.add(rec.index_generation)
    if len(distinct_gens) > 1:
        gens_list = sorted(distinct_gens)
        raise ScoreError(
            f"Mixed index generations detected in journal: "
            f"{gens_list[0]} vs {gens_list[1]}"
        )

    # 2. Structural Guard: Validate all document_ids against document_map.json
    try:
        doc_map = load_document_map(corpus_name)
    except Exception as e:
        raise ScoreError(
            f"Could not load document map for corpus '{corpus_name}': {e}"
        ) from e

    for rec in records:
        if rec.snapshot and rec.snapshot.retrieved_chunks:
            for chunk in rec.snapshot.retrieved_chunks:
                if chunk.document_id not in doc_map.entries:
                    raise ScoreError(
                        f"Unmapped document_id '{chunk.document_id}' in journal record "
                        f"for question '{rec.question_id}'"
                    )

    # Load gold questions and config
    config = load_corpus_config(corpus_name)
    sampled_questions = load_sample_questions(corpus_name)
    gold_map = {q.question_id: q for q in sampled_questions}

    # Group records by arm
    records_by_arm: dict[str, list[RunRecord]] = {"graph-on": [], "graph-off": []}
    for rec in records:
        if rec.graph_arm in records_by_arm:
            records_by_arm[rec.graph_arm].append(rec)

    # Compute scores for graph-on and graph-off
    arm_metrics: dict[str, dict[str, Any]] = {}

    for arm, arm_records in records_by_arm.items():
        total_records = len(arm_records)
        error_records = [r for r in arm_records if r.outcome == "error"]
        success_records = [r for r in arm_records if r.outcome == "success"]

        recalls: list[float] = []
        precisions: list[float] = []
        mrrs: list[float] = []
        ndcgs: list[float] = []
        ems: list[float] = []
        f1s: list[float] = []
        abstentions: list[float] = []
        retrieval_skipped_count = 0
        provenance_error_count = 0

        for rec in success_records:
            gold = gold_map.get(rec.question_id)
            if not gold:
                continue

            # Provenance check on graph-off
            if arm == "graph-off" and not _check_provenance(rec):
                provenance_error_count += 1
                continue

            # Retrieval dimensions strictly read snapshot.retrieved_chunks
            if rec.snapshot is None:
                retrieval_skipped_count += 1
            else:
                chunks = rec.snapshot.retrieved_chunks
                if not gold.is_null:
                    # Recall@4
                    r_out = recall_at_k(
                        gold, chunks, k=4, chunk_size=config.chunk_size
                    )
                    if r_out.status == "ok" and r_out.score is not None:
                        recalls.append(r_out.score)
                    # Precision@4
                    p_out = context_precision_at_k(gold, chunks, k=4)
                    if p_out.status == "ok" and p_out.score is not None:
                        precisions.append(p_out.score)
                    # MRR@10
                    m_out = mrr_at_k(gold, chunks, k=10)
                    if m_out.status == "ok" and m_out.score is not None:
                        mrrs.append(m_out.score)
                    # nDCG@10
                    n_out = ndcg_at_k(
                        gold, chunks, k=10, chunk_size=config.chunk_size
                    )
                    if n_out.status == "ok" and n_out.score is not None:
                        ndcgs.append(n_out.score)

            # Answer metrics
            if rec.answer is not None and not gold.is_null:
                em_out = squad_em(gold, rec.answer)
                if em_out.status == "ok" and em_out.score is not None:
                    ems.append(em_out.score)
                f1_out = squad_f1(gold, rec.answer)
                if f1_out.status == "ok" and f1_out.score is not None:
                    f1s.append(f1_out.score)

            # Abstention on unanswerable
            if gold.is_null:
                snap_chunks = (
                    rec.snapshot.retrieved_chunks if rec.snapshot else None
                )
                abs_out = abstention_rate(gold, rec.answer or "", snap_chunks)
                if abs_out.status == "ok" and abs_out.score is not None:
                    abstentions.append(abs_out.score)

        arm_metrics[arm] = {
            "total": total_records,
            "errors": len(error_records) + provenance_error_count,
            "success": len(success_records) - provenance_error_count,
            "retrieval_skipped": retrieval_skipped_count,
            "recalls": recalls,
            "precisions": precisions,
            "mrrs": mrrs,
            "ndcgs": ndcgs,
            "ems": ems,
            "f1s": f1s,
            "abstentions": abstentions,
        }

    # Primary scoring over graph-on arm
    if "graph-on" in arm_metrics and arm_metrics["graph-on"]["total"] > 0:
        primary_arm = "graph-on"
    else:
        primary_arm = next(iter(arm_metrics.keys()))
    p_data = arm_metrics[primary_arm]

    dimensions: list[DimensionResult] = []

    # Helper for building mean score dimension
    def _build_mean_dim(
        name: str, values: list[float], errors: int, total: int
    ) -> DimensionResult:
        if not values:
            if errors == total and total > 0:
                return DimensionResult(
                    name=name,
                    status="error",
                    reason=f"All {total} records failed execution with errors",
                    n=0,
                )
            return DimensionResult(
                name=name,
                status="skipped",
                reason="No valid records available to compute metric",
                n=0,
            )
        mean_val = sum(values) / len(values)
        return DimensionResult(
            name=name,
            status="ok",
            score=mean_val,
            detail={
                "errors": float(errors),
                "sample_size": float(len(values)),
            },
            n=len(values),
        )

    # 1. retrieval_evidence_coverage
    dimensions.append(
        _build_mean_dim(
            "retrieval_evidence_coverage",
            p_data["recalls"],
            p_data["errors"],
            p_data["total"],
        )
    )

    # 2. context_precision_at_k
    dimensions.append(
        _build_mean_dim(
            "context_precision_at_k",
            p_data["precisions"],
            p_data["errors"],
            p_data["total"],
        )
    )

    # 3. ranking_quality (MRR@10)
    dimensions.append(
        _build_mean_dim(
            "ranking_quality",
            p_data["mrrs"],
            p_data["errors"],
            p_data["total"],
        )
    )

    # 4. answer_exact_match
    dimensions.append(
        _build_mean_dim(
            "answer_exact_match",
            p_data["ems"],
            p_data["errors"],
            p_data["total"],
        )
    )

    # 5. answer_f1
    dimensions.append(
        _build_mean_dim(
            "answer_f1",
            p_data["f1s"],
            p_data["errors"],
            p_data["total"],
        )
    )

    # 6. answer_faithfulness (skipped under --no-judge)
    dimensions.append(
        DimensionResult(
            name="answer_faithfulness",
            status="skipped",
            reason="Deferred to LLM-as-judge scoring pass (--no-judge specified)",
            n=0,
        )
    )

    # 7. answer_groundedness (skipped under --no-judge)
    dimensions.append(
        DimensionResult(
            name="answer_groundedness",
            status="skipped",
            reason="Deferred to LLM-as-judge scoring pass (--no-judge specified)",
            n=0,
        )
    )

    # 8. graph_ablation_delta
    on_data = arm_metrics.get("graph-on", {"recalls": [], "errors": 0, "total": 0})
    off_data = arm_metrics.get(
        "graph-off", {"recalls": [], "errors": 0, "total": 0}
    )

    on_score = (
        (sum(on_data["recalls"]) / len(on_data["recalls"]))
        if on_data["recalls"]
        else 0.0
    )
    off_score = (
        (sum(off_data["recalls"]) / len(off_data["recalls"]))
        if off_data["recalls"]
        else 0.0
    )

    ablation_dim = make_graph_ablation_delta(
        graph_on_score=on_score,
        graph_on_n=len(on_data["recalls"]),
        graph_on_errors=on_data["errors"],
        graph_off_score=off_score,
        graph_off_n=len(off_data["recalls"]),
        graph_off_errors=off_data["errors"],
    )
    dimensions.append(ablation_dim)

    # 9. abstention_on_unanswerable
    if p_data["abstentions"]:
        abs_mean = sum(p_data["abstentions"]) / len(p_data["abstentions"])
        dimensions.append(
            DimensionResult(
                name="abstention_on_unanswerable",
                status="ok",
                score=abs_mean,
                detail={"null_samples": float(len(p_data["abstentions"]))},
                n=len(p_data["abstentions"]),
            )
        )
    else:
        dimensions.append(
            DimensionResult(
                name="abstention_on_unanswerable",
                status="skipped",
                reason="Corpus contains no unanswerable questions",
                n=0,
            )
        )

    # 10. wire_contract_conformance
    total_recs = len(records)
    error_recs = sum(1 for r in records if r.outcome == "error")
    conformance_rate = (
        ((total_recs - error_recs) / total_recs) if total_recs > 0 else 0.0
    )
    dimensions.append(
        DimensionResult(
            name="wire_contract_conformance",
            status="ok",
            score=conformance_rate,
            detail={
                "total_records": float(total_recs),
                "error_records": float(error_recs),
            },
            n=total_recs,
        )
    )

    # 11. community_summary_quality (placeholder)
    dimensions.append(OBS_04_PLACEHOLDER)

    # 12. run_traceability
    traced_count = sum(
        1
        for r in records
        if r.session_id and r.correlation_id and r.index_generation
    )
    traceability_rate = (traced_count / total_recs) if total_recs > 0 else 0.0
    dimensions.append(
        DimensionResult(
            name="run_traceability",
            status="ok",
            score=traceability_rate,
            detail={
                "traced_records": float(traced_count),
                "total_records": float(total_recs),
            },
            n=total_recs,
        )
    )

    metadata = RunMetadata(
        corpus=corpus_name,
        generated_at=datetime.now(UTC).isoformat(),
        commit_sha="local",
        sample_size_deterministic=len(sampled_questions),
        sample_size_judged=0,
    )

    report = CorpusReport(
        corpus=corpus_name,
        metadata=metadata,
        dimensions=dimensions,
    )

    # Write report.json to run_dir
    report_json_path = dir_path / "report.json"
    with open(report_json_path, "w", encoding="utf-8") as f:
        f.write(render_json(report))

    return report
