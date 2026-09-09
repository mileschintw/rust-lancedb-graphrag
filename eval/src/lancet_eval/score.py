"""Offline deterministic and cached LLM-judged evaluation scorer."""

from __future__ import annotations

import json
import logging
import os
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from lancet_eval.agreement import (
    CALIBRATION_STATE_BELOW_TARGET,
    CALIBRATION_STATE_NONE,
    CALIBRATION_STATE_SATISFIED,
    KAPPA_STATE_COMPUTED,
    KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT,
    SPEARMAN_STATE_COMPUTED,
    SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE,
    bootstrap_agreement_ci,
    quadratic_weighted_kappa,
    spearman_rank_correlation,
)
from lancet_eval.config import get_commit_sha
from lancet_eval.corpus import (
    load_corpus_config,
    load_sample_questions,
    sample_questions,
)
from lancet_eval.dimensions import (
    NOTICE_CODE_GRAPH_ABLATION,
    NOTICE_CODE_GRAPH_UNAVAILABLE,
    OBS_04_PLACEHOLDER,
    DimensionResult,
    make_bm25_yield,
    make_faithfulness_result,
    make_graph_influence_rate,
    make_graph_latency_ms,
    make_graph_presence_rate,
    make_groundedness_result,
    make_paired_ablation_delta,
    make_retrieve_latency_ms,
    make_unusable_record_rate,
    make_vector_yield,
    make_wire_contract_conformance,
)
from lancet_eval.gate import AGREEMENT_TARGET
from lancet_eval.journal import RunRecord
from lancet_eval.judge import (
    JudgeCache,
    JudgeCacheEntry,
    cache_key,
    judge_once,
    truncate_evidence,
)
from lancet_eval.metrics import (
    abstention_rate,
    context_precision_at_k,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    squad_em,
    squad_f1,
)
from lancet_eval.pairing import (
    compute_paired_delta,
    deduplicate_by_arm,
    form_pairs,
)
from lancet_eval.report import (
    CorpusReport,
    RunMetadata,
    compute_result_hash,
    get_lock_hash,
    render_json,
)
from lancet_eval.seed import load_document_map
from lancet_eval.usability import (
    has_arm_provenance,
    has_scorable_payload,
    is_usable,
)

logger = logging.getLogger(__name__)


class ScoreError(Exception):
    """Raised when score encounters corrupt, invalid, or unmapped data."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _get_engine_generation_model() -> str:
    """Read generation_model from config/config.toml, logging warning on failure."""
    cfg_path = _repo_root() / "config" / "config.toml"
    if not cfg_path.is_file():
        logger.warning("Config file not found at %s (FileNotFoundError)", cfg_path)
        return ""
    try:
        with open(cfg_path, "rb") as f:
            data = tomllib.load(f)
        return str(data.get("openrouter", {}).get("generation_model", ""))
    except Exception as e:
        logger.warning(
            "Failed to read engine generation model from %s (%s)",
            cfg_path,
            type(e).__name__,
        )
        return ""


def _check_provenance(record: RunRecord) -> bool:
    """Verify that a graph-off record carries ablation notice and not unavailable."""
    has_ablation = any(
        n.typed_code == NOTICE_CODE_GRAPH_ABLATION or n.code == "GRAPH_ABLATION"
        for n in record.notices
    )
    has_unavailable = any(
        n.typed_code == NOTICE_CODE_GRAPH_UNAVAILABLE or n.code == "GRAPH_UNAVAILABLE"
        for n in record.notices
    )
    return has_ablation and not has_unavailable


def score_run(
    *,
    run_dir: Path | str,
    no_judge: bool = True,
    sample: int | None = None,
    emit_calibration_worksheet: Path | str | None = None,
    calibration_file: Path | str | None = None,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> CorpusReport:
    """Read a run journal and produce a scored evaluation report."""
    dir_path = Path(run_dir)
    journal_path = dir_path / "journal.jsonl"
    if not journal_path.is_file():
        journal_path = dir_path / "journal.json"
    if not journal_path.is_file():
        raise ScoreError(f"No journal file found in {dir_path}")

    # Read journal records
    records: list[RunRecord] = []
    header_corpus: str | None = None
    header_partial: bool = False
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
                header_partial = bool(data.get("partial", False))
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

    # WR-02: Deduplicate records journal-wide per (question_id, graph_arm)
    records, collapsed_records_n = deduplicate_by_arm(records)

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
                if (
                    chunk.document_id not in doc_map.entries
                    and chunk.document_id not in doc_map.aliases
                ):
                    raise ScoreError(
                        f"Unmapped document_id '{chunk.document_id}' in record "
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

    # Compute deterministic scores for graph-on and graph-off
    arm_metrics: dict[str, dict[str, Any]] = {}

    for arm, arm_records in records_by_arm.items():
        total_records = len(arm_records)
        unusable_records = [r for r in arm_records if not is_usable(r)]
        usable_records = [r for r in arm_records if is_usable(r)]

        recalls: list[float] = []
        precisions: list[float] = []
        mrrs: list[float] = []
        ndcgs: list[float] = []
        ems: list[float] = []
        f1s: list[float] = []
        abstentions: list[float] = []
        payload_excluded_answerable_count = 0
        payload_excluded_unanswerable_count = 0
        provenance_error_count = 0

        for rec in usable_records:
            gold = gold_map.get(rec.question_id)
            if not gold:
                continue

            # Provenance check on graph-off
            if arm == "graph-off" and not has_arm_provenance(rec):
                provenance_error_count += 1
                continue

            # Scorable payload guard: must carry retrieval snapshot and non-blank answer
            if not has_scorable_payload(rec):
                if gold.is_null:
                    payload_excluded_unanswerable_count += 1
                else:
                    payload_excluded_answerable_count += 1
                continue

            # Retrieval dimensions strictly read snapshot.retrieved_chunks
            chunks = rec.snapshot.retrieved_chunks
            if not gold.is_null:
                # Recall@4
                r_out = recall_at_k(gold, chunks, k=4, chunk_size=config.chunk_size)
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
                n_out = ndcg_at_k(gold, chunks, k=10, chunk_size=config.chunk_size)
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
                snap_chunks = rec.snapshot.retrieved_chunks if rec.snapshot else None
                abs_out = abstention_rate(
                    gold, rec.answer or "", snap_chunks, rec.notices
                )
                if abs_out.status == "ok" and abs_out.score is not None:
                    abstentions.append(abs_out.score)

        arm_metrics[arm] = {
            "total": total_records,
            "errors": len(unusable_records) + provenance_error_count,
            "success": len(usable_records) - provenance_error_count,
            "provenance_excluded": provenance_error_count,
            "payload_excluded_answerable": payload_excluded_answerable_count,
            "payload_excluded_unanswerable": payload_excluded_unanswerable_count,
            "recalls": recalls,
            "precisions": precisions,
            "mrrs": mrrs,
            "ndcgs": ndcgs,
            "ems": ems,
            "f1s": f1s,
            "abstentions": abstentions,
            "usable_records": [
                r for r in usable_records if arm != "graph-off" or has_arm_provenance(r)
            ],
        }

    # WR-03: Primary scoring arm is chosen from the arm that actually has records
    if arm_metrics.get("graph-on", {}).get("total", 0) > 0:
        primary_arm = "graph-on"
    elif arm_metrics.get("graph-off", {}).get("total", 0) > 0:
        primary_arm = "graph-off"
    else:
        # Belt-and-suspenders fallback if neither has records
        # (though score_run refuses empty journals)
        primary_arm = "graph-on"
    p_data = arm_metrics[primary_arm]
    p_records = records_by_arm.get(primary_arm, [])

    # LLM-as-judge evaluation pass
    groundedness_scores: list[int | float] = []
    faithfulness_scores: list[int | float] = []
    judge_errors = 0
    skipped_no_evidence = 0
    judged_sample_count = 0
    cache_path = dir_path / "judge_cache.json"
    cache = JudgeCache(cache_path)
    judged_qids: set[str] = set()

    if calibration_file is not None:
        cached_verdict_count = sum(
            1 for e in cache.entries.values() if e.verdict is not None
        )
        if no_judge and cached_verdict_count > 0:
            raise ScoreError(
                "calibration_file was provided with --no-judge, but "
                f"judge_cache.json already has {cached_verdict_count} cached "
                "verdict(s) from a prior --judge invocation. Running without "
                "--judge here would silently discard that judged population "
                "when report.json is rewritten (score_run always rewrites "
                "report.json on a non-partial run). Re-run with --judge "
                "(same --sample scope used to build the cache) to feed "
                "calibration scores back safely."
            )
        if sample is not None and sample < cached_verdict_count:
            raise ScoreError(
                f"calibration_file was provided with --sample {sample}, "
                f"narrower than the {cached_verdict_count} verdict(s) already "
                "cached in judge_cache.json from a prior, larger judging "
                "invocation. This would silently shrink the judged population "
                "report.json records. Re-run without --sample (or with a "
                "value >= the cached verdict count) before feeding back "
                "calibration scores."
            )

    if not no_judge:
        # Check judge model distinctness from generator model
        gen_model = _get_engine_generation_model()
        if not gen_model or not gen_model.strip():
            raise ScoreError(
                "Could not read engine generation model from configuration. "
                "Judging cannot proceed because distinctness of judge and generation "
                "models cannot be verified."
            )
        judge_model = config.judge_model
        if judge_model and gen_model.strip() == judge_model.strip():
            raise ScoreError(
                f"Configured judge model '{judge_model}' equals engine generation "
                f"model '{gen_model}'. A judge cannot evaluate its own model family."
            )

        api_key_val = api_key or os.environ.get("OPENROUTER_API_KEY", "")

        # Select judged question subset
        if sample is not None and sample > 0:
            distinct_qids = [
                {"question_id": q.question_id}
                for q in sampled_questions
                if any(r.question_id == q.question_id for r in p_records)
            ]
            sampled_q_dicts = sample_questions(
                distinct_qids, n=sample, seed=config.sample_seed
            )
            judged_qids = {d["question_id"] for d in sampled_q_dicts}
        else:
            judged_qids = {r.question_id for r in p_records}

        for rec in p_records:
            if rec.question_id not in judged_qids:
                continue
            gold = gold_map.get(rec.question_id)
            if not gold:
                continue

            judged_sample_count += 1

            if not rec.structured_citations:
                skipped_no_evidence += 1
                continue

            ev = truncate_evidence(rec.structured_citations)
            k = cache_key(
                prompt_version=config.judge_prompt_version,
                judge_model=judge_model,
                question=gold.question,
                answer=rec.answer or "",
                post_truncation_evidence=ev,
            )

            cached_entry = cache.get(k)
            if cached_entry is not None:
                if cached_entry.verdict is not None:
                    groundedness_scores.append(cached_entry.verdict.groundedness)
                    faithfulness_scores.append(cached_entry.verdict.faithfulness)
                elif cached_entry.error is not None:
                    judge_errors += 1
            else:
                verdict, err = judge_once(
                    client=client,
                    api_key=api_key_val,
                    model=judge_model,
                    question=gold.question,
                    answer=rec.answer or "",
                    evidence=ev,
                    prompt_version=config.judge_prompt_version,
                    temperature=config.judge_temperature,
                    max_tokens=config.judge_max_tokens,
                )
                entry = JudgeCacheEntry(
                    cache_key=k,
                    prompt_version=config.judge_prompt_version,
                    judge_model=judge_model,
                    question=gold.question,
                    answer=rec.answer or "",
                    evidence=ev,
                    verdict=verdict,
                    error=err,
                )
                cache.set(k, entry)
                if verdict is not None:
                    groundedness_scores.append(verdict.groundedness)
                    faithfulness_scores.append(verdict.faithfulness)
                else:
                    judge_errors += 1

    # Calibration evaluation
    g_calibration_em: float | None = None
    g_calibration_mad: float | None = None
    f_calibration_em: float | None = None
    f_calibration_mad: float | None = None

    g_calibration_kappa: float | None = None
    g_calibration_spearman: float | None = None
    g_calibration_kappa_state: float | None = None
    g_calibration_spearman_state: float | None = None
    g_calibration_state: float | None = None
    g_calibration_kappa_ci_lower: float | None = None
    g_calibration_kappa_ci_upper: float | None = None
    g_calibration_spearman_ci_lower: float | None = None
    g_calibration_spearman_ci_upper: float | None = None
    g_calibration_pairs_n: float | None = None
    g_calibration_excluded_n: float | None = None

    f_calibration_kappa: float | None = None
    f_calibration_spearman: float | None = None
    f_calibration_kappa_state: float | None = None
    f_calibration_spearman_state: float | None = None
    f_calibration_state: float | None = None
    f_calibration_kappa_ci_lower: float | None = None
    f_calibration_kappa_ci_upper: float | None = None
    f_calibration_spearman_ci_lower: float | None = None
    f_calibration_spearman_ci_upper: float | None = None
    f_calibration_pairs_n: float | None = None
    f_calibration_excluded_n: float | None = None

    completed_dual_scores: int = 0
    calibration_notes: str = ""

    if calibration_file is None:
        g_calibration_state = CALIBRATION_STATE_NONE
        f_calibration_state = CALIBRATION_STATE_NONE
        calibration_notes = (
            "No judge-versus-human calibration was performed; "
            "judged dimensions are uncalibrated."
        )
    else:
        calib_path = Path(calibration_file)
        if not calib_path.is_file():
            raise ScoreError(f"Calibration file not found at {calib_path}")

        g_matches: list[float] = []
        g_diffs: list[float] = []
        f_matches: list[float] = []
        f_diffs: list[float] = []

        g_human: list[int] = []
        g_judge: list[int] = []
        f_human: list[int] = []
        f_judge: list[int] = []
        g_excluded = 0
        f_excluded = 0

        with open(calib_path, encoding="utf-8") as f:
            for line_idx, line in enumerate(f, 1):
                clean_l = line.strip()
                if not clean_l:
                    continue
                row = json.loads(clean_l)
                if row.get("type") == "header":
                    hdr_ver = row.get("judge_prompt_version")
                    if hdr_ver != config.judge_prompt_version:
                        raise ScoreError(
                            f"Calibration prompt version '{hdr_ver}' does not match "
                            f"configured '{config.judge_prompt_version}'"
                        )
                    continue

                row_id = row.get("question_id") or f"line-{line_idx}"
                hg = row.get("human_groundedness")
                hf = row.get("human_faithfulness")

                hg_blank = hg is None or str(hg).strip() == ""
                hf_blank = hf is None or str(hf).strip() == ""
                if hg_blank or hf_blank:
                    raise ScoreError(
                        f"Row '{row_id}' in calibration worksheet has blank human score"
                    )

                try:
                    hg_val = int(hg)
                    hf_val = int(hf)
                except ValueError as e:
                    raise ScoreError(
                        f"Row '{row_id}' has invalid human score: {hg}, {hf}"
                    ) from e

                if not (1 <= hg_val <= 5 and 1 <= hf_val <= 5):
                    raise ScoreError(
                        f"Row '{row_id}' human score outside 1..5: {hg_val}, {hf_val}"
                    )

                completed_dual_scores += 1

                c_key = row.get("cache_key", "")
                cached = cache.get(c_key)
                if cached and cached.verdict:
                    g_matches.append(
                        1.0 if hg_val == cached.verdict.groundedness else 0.0
                    )
                    g_diffs.append(abs(hg_val - cached.verdict.groundedness))
                    f_matches.append(
                        1.0 if hf_val == cached.verdict.faithfulness else 0.0
                    )
                    f_diffs.append(abs(hf_val - cached.verdict.faithfulness))

                    g_human.append(hg_val)
                    g_judge.append(cached.verdict.groundedness)
                    f_human.append(hf_val)
                    f_judge.append(cached.verdict.faithfulness)
                else:
                    g_excluded += 1
                    f_excluded += 1

        if g_matches:
            g_calibration_em = sum(g_matches) / len(g_matches)
            g_calibration_mad = sum(g_diffs) / len(g_diffs)
            f_calibration_em = sum(f_matches) / len(f_matches)
            f_calibration_mad = sum(f_diffs) / len(f_diffs)

        g_calibration_pairs_n = float(len(g_human))
        g_calibration_excluded_n = float(g_excluded)
        if g_human:
            res_kappa = quadratic_weighted_kappa(
                g_human, g_judge, min_rating=1, max_rating=5
            )
            if res_kappa.value is not None:
                g_calibration_kappa = res_kappa.value
                g_calibration_kappa_state = KAPPA_STATE_COMPUTED
                ci_k = bootstrap_agreement_ci(
                    g_human,
                    g_judge,
                    "kappa",
                    min_rating=1,
                    max_rating=5,
                    seed=config.sample_seed,
                )
                if ci_k is not None:
                    g_calibration_kappa_ci_lower, g_calibration_kappa_ci_upper = ci_k
            else:
                g_calibration_kappa = None
                if res_kappa.state == "undefined_expected_agreement":
                    g_calibration_kappa_state = KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT

            res_spearman = spearman_rank_correlation(g_human, g_judge)
            if res_spearman.value is not None:
                g_calibration_spearman = res_spearman.value
                g_calibration_spearman_state = SPEARMAN_STATE_COMPUTED
                ci_s = bootstrap_agreement_ci(
                    g_human,
                    g_judge,
                    "spearman",
                    seed=config.sample_seed,
                )
                if ci_s is not None:
                    g_calibration_spearman_ci_lower, g_calibration_spearman_ci_upper = (
                        ci_s
                    )
            else:
                g_calibration_spearman = None
                if res_spearman.state == "undefined_zero_variance":
                    g_calibration_spearman_state = (
                        SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE
                    )

        f_calibration_pairs_n = float(len(f_human))
        f_calibration_excluded_n = float(f_excluded)
        if f_human:
            res_kappa = quadratic_weighted_kappa(
                f_human, f_judge, min_rating=1, max_rating=5
            )
            if res_kappa.value is not None:
                f_calibration_kappa = res_kappa.value
                f_calibration_kappa_state = KAPPA_STATE_COMPUTED
                ci_k = bootstrap_agreement_ci(
                    f_human,
                    f_judge,
                    "kappa",
                    min_rating=1,
                    max_rating=5,
                    seed=config.sample_seed,
                )
                if ci_k is not None:
                    f_calibration_kappa_ci_lower, f_calibration_kappa_ci_upper = ci_k
            else:
                f_calibration_kappa = None
                if res_kappa.state == "undefined_expected_agreement":
                    f_calibration_kappa_state = KAPPA_STATE_UNDEFINED_EXPECTED_AGREEMENT

            res_spearman = spearman_rank_correlation(f_human, f_judge)
            if res_spearman.value is not None:
                f_calibration_spearman = res_spearman.value
                f_calibration_spearman_state = SPEARMAN_STATE_COMPUTED
                ci_s = bootstrap_agreement_ci(
                    f_human,
                    f_judge,
                    "spearman",
                    seed=config.sample_seed,
                )
                if ci_s is not None:
                    f_calibration_spearman_ci_lower, f_calibration_spearman_ci_upper = (
                        ci_s
                    )
            else:
                f_calibration_spearman = None
                if res_spearman.state == "undefined_zero_variance":
                    f_calibration_spearman_state = (
                        SPEARMAN_STATE_UNDEFINED_ZERO_VARIANCE
                    )

        if completed_dual_scores == 0:
            g_calibration_state = CALIBRATION_STATE_NONE
            f_calibration_state = CALIBRATION_STATE_NONE
            calibration_notes = (
                "No judge-versus-human calibration was performed; "
                "judged dimensions are uncalibrated."
            )
        else:
            g_kappa_satisfied = (
                g_calibration_kappa is not None
                and g_calibration_kappa >= AGREEMENT_TARGET
            )
            g_spearman_satisfied = (
                g_calibration_spearman is not None
                and g_calibration_spearman >= AGREEMENT_TARGET
            )
            f_kappa_satisfied = (
                f_calibration_kappa is not None
                and f_calibration_kappa >= AGREEMENT_TARGET
            )
            f_spearman_satisfied = (
                f_calibration_spearman is not None
                and f_calibration_spearman >= AGREEMENT_TARGET
            )

            g_calibration_state = (
                CALIBRATION_STATE_SATISFIED
                if (g_kappa_satisfied and g_spearman_satisfied)
                else CALIBRATION_STATE_BELOW_TARGET
            )
            f_calibration_state = (
                CALIBRATION_STATE_SATISFIED
                if (f_kappa_satisfied and f_spearman_satisfied)
                else CALIBRATION_STATE_BELOW_TARGET
            )

            shortfalls = []
            if not g_kappa_satisfied:
                val_repr = (
                    f"{g_calibration_kappa:.4f}"
                    if g_calibration_kappa is not None
                    else "undefined"
                )
                shortfalls.append(f"groundedness kappa={val_repr}")
            if not g_spearman_satisfied:
                val_repr = (
                    f"{g_calibration_spearman:.4f}"
                    if g_calibration_spearman is not None
                    else "undefined"
                )
                shortfalls.append(f"groundedness spearman={val_repr}")
            if not f_kappa_satisfied:
                val_repr = (
                    f"{f_calibration_kappa:.4f}"
                    if f_calibration_kappa is not None
                    else "undefined"
                )
                shortfalls.append(f"faithfulness kappa={val_repr}")
            if not f_spearman_satisfied:
                val_repr = (
                    f"{f_calibration_spearman:.4f}"
                    if f_calibration_spearman is not None
                    else "undefined"
                )
                shortfalls.append(f"faithfulness spearman={val_repr}")

            if shortfalls:
                prefix = (
                    f"Calibration agreement fell below target "
                    f"({AGREEMENT_TARGET:.2f}) for: "
                )
                calibration_notes = f"{prefix}{', '.join(shortfalls)}."
            else:
                calibration_notes = ""

    # Emit calibration worksheet if requested
    if emit_calibration_worksheet is not None:
        # CR-01: Refuse to emit worksheet without judging enabled
        if no_judge:
            raise ScoreError(
                "Cannot emit calibration worksheet (--emit-calibration-worksheet) "
                "when judging is disabled (--no-judge). Generating a valid "
                "calibration worksheet requires cache-verified verdicts from "
                "the judge model. Re-run with judging enabled (--judge) to "
                "produce a valid calibration worksheet."
            )
        out_ws_path = Path(emit_calibration_worksheet)
        out_ws_path.parent.mkdir(parents=True, exist_ok=True)

        worksheet_rows: list[dict[str, Any]] = [
            {
                "type": "header",
                "corpus": corpus_name,
                "judge_prompt_version": config.judge_prompt_version,
                "judge_model": config.judge_model,
                "generated_at": datetime.now(UTC).isoformat(),
            }
        ]

        # Select up to 20 representative items across query types
        selected_records = []
        if judged_qids:
            for r in p_records:
                if r.question_id not in judged_qids:
                    continue
                gold = gold_map.get(r.question_id)
                if not gold:
                    continue
                if not r.structured_citations:
                    continue
                ev = truncate_evidence(r.structured_citations)
                k = cache_key(
                    prompt_version=config.judge_prompt_version,
                    judge_model=config.judge_model,
                    question=gold.question,
                    answer=r.answer or "",
                    post_truncation_evidence=ev,
                )
                entry = cache.get(k)
                if entry is not None and entry.verdict is not None:
                    selected_records.append(r)
                if len(selected_records) == 20:
                    break

        for r in selected_records:
            gold = gold_map.get(r.question_id)
            if not gold:
                continue
            ev = (
                truncate_evidence(r.structured_citations)
                if r.structured_citations
                else ""
            )
            k = cache_key(
                prompt_version=config.judge_prompt_version,
                judge_model=config.judge_model,
                question=gold.question,
                answer=r.answer or "",
                post_truncation_evidence=ev,
            )
            worksheet_rows.append({
                "question_id": r.question_id,
                "query_type": gold.question_type,
                "cache_key": k,
                "question": gold.question,
                "answer": r.answer or "",
                "evidence": ev,
                "human_groundedness": None,
                "human_faithfulness": None,
                "notes": "",
            })

        with open(out_ws_path, "w", encoding="utf-8", newline="\n") as f:
            for w_row in worksheet_rows:
                f.write(json.dumps(w_row, ensure_ascii=False) + "\n")

        count_emitted = len(worksheet_rows) - 1
        print(f"Emitted {count_emitted} calibration worksheet rows to {out_ws_path}")

    dimensions: list[DimensionResult] = []

    # 0. Integrity & path health dimensions
    dimensions.append(
        make_unusable_record_rate(
            records=records, collapsed_records_n=collapsed_records_n
        )
    )

    usable_primary_records = p_data.get("usable_records", [])

    # Extract RetrieveHybrid durations once from usable primary records
    retrieve_latencies: list[float] = []
    for r in usable_primary_records:
        for nt in r.node_timings:
            if nt.node_name == "RetrieveHybrid":
                retrieve_latencies.append(nt.duration_ms)
                break

    dimensions.append(
        make_vector_yield(
            records=usable_primary_records,
            retrieve_latencies=retrieve_latencies,
        )
    )
    dimensions.append(
        make_bm25_yield(
            records=usable_primary_records,
            retrieve_latencies=retrieve_latencies,
        )
    )
    dimensions.append(make_retrieve_latency_ms(records=usable_primary_records))
    dimensions.append(make_graph_presence_rate(records=usable_primary_records))
    dimensions.append(make_graph_influence_rate(records=usable_primary_records))
    dimensions.append(make_graph_latency_ms(records=usable_primary_records))

    # Helper for building mean score dimension

    def _build_mean_dim(
        name: str,
        values: list[float],
        errors: int,
        total: int,
        extra_detail: dict[str, float] | None = None,
    ) -> DimensionResult:
        merged_detail = dict(extra_detail) if extra_detail else {}
        if not values:
            if errors == total and total > 0:
                return DimensionResult(
                    name=name,
                    status="error",
                    reason=f"All {total} records failed execution with errors",
                    detail=merged_detail,
                    n=0,
                )
            return DimensionResult(
                name=name,
                status="skipped",
                reason="No valid records available to compute metric",
                detail=merged_detail,
                n=0,
            )
        mean_val = sum(values) / len(values)
        ok_detail = {
            "errors": float(errors),
            "sample_size": float(len(values)),
        }
        if extra_detail:
            ok_detail.update(extra_detail)
        return DimensionResult(
            name=name,
            status="ok",
            score=mean_val,
            detail=ok_detail,
            n=len(values),
        )

    answerable_payload_detail = {
        "excluded_payload_records": float(p_data.get("payload_excluded_answerable", 0))
    }

    # 1. retrieval_evidence_coverage
    dimensions.append(
        _build_mean_dim(
            "retrieval_evidence_coverage",
            p_data["recalls"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 2. context_precision_at_k
    dimensions.append(
        _build_mean_dim(
            "context_precision_at_k",
            p_data["precisions"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 3. ranking_quality (MRR@10)
    dimensions.append(
        _build_mean_dim(
            "ranking_quality",
            p_data["mrrs"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 4. answer_exact_match
    dimensions.append(
        _build_mean_dim(
            "answer_exact_match",
            p_data["ems"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 5. answer_f1
    dimensions.append(
        _build_mean_dim(
            "answer_f1",
            p_data["f1s"],
            p_data["errors"],
            p_data["total"],
            extra_detail=answerable_payload_detail,
        )
    )

    # 6. answer_faithfulness
    if no_judge:
        dimensions.append(
            DimensionResult(
                name="answer_faithfulness",
                status="skipped",
                reason="Deferred to LLM-as-judge scoring pass (--no-judge specified)",
                n=0,
            )
        )
    else:
        dimensions.append(
            make_faithfulness_result(
                verdicts=faithfulness_scores,
                judge_errors=judge_errors,
                skipped_no_evidence=skipped_no_evidence,
                total_sampled=judged_sample_count,
                calibration_exact_match=f_calibration_em,
                calibration_mad=f_calibration_mad,
                calibration_kappa=f_calibration_kappa,
                calibration_spearman=f_calibration_spearman,
                calibration_kappa_state=f_calibration_kappa_state,
                calibration_spearman_state=f_calibration_spearman_state,
                calibration_state=f_calibration_state,
                calibration_kappa_ci_lower=f_calibration_kappa_ci_lower,
                calibration_kappa_ci_upper=f_calibration_kappa_ci_upper,
                calibration_spearman_ci_lower=f_calibration_spearman_ci_lower,
                calibration_spearman_ci_upper=f_calibration_spearman_ci_upper,
                calibration_pairs_n=f_calibration_pairs_n,
                calibration_excluded_n=f_calibration_excluded_n,
            )
        )

    # 7. answer_groundedness
    if no_judge:
        dimensions.append(
            DimensionResult(
                name="answer_groundedness",
                status="skipped",
                reason="Deferred to LLM-as-judge scoring pass (--no-judge specified)",
                n=0,
            )
        )
    else:
        dimensions.append(
            make_groundedness_result(
                verdicts=groundedness_scores,
                judge_errors=judge_errors,
                skipped_no_evidence=skipped_no_evidence,
                total_sampled=judged_sample_count,
                calibration_exact_match=g_calibration_em,
                calibration_mad=g_calibration_mad,
                calibration_kappa=g_calibration_kappa,
                calibration_spearman=g_calibration_spearman,
                calibration_kappa_state=g_calibration_kappa_state,
                calibration_spearman_state=g_calibration_spearman_state,
                calibration_state=g_calibration_state,
                calibration_kappa_ci_lower=g_calibration_kappa_ci_lower,
                calibration_kappa_ci_upper=g_calibration_kappa_ci_upper,
                calibration_spearman_ci_lower=g_calibration_spearman_ci_lower,
                calibration_spearman_ci_upper=g_calibration_spearman_ci_upper,
                calibration_pairs_n=g_calibration_pairs_n,
                calibration_excluded_n=g_calibration_excluded_n,
            )
        )

    # 8. graph_ablation_delta (redefined paired difference of evidence coverage)
    # Form pairs once from deduplicated records
    join_res = form_pairs(records, gold_map)
    pairs = join_res.pairs

    # Distinct questions attempted in this journal across both arms
    coverage_denom = join_res.total_distinct_questions
    answerable_n = sum(1 for q in sampled_questions if not q.is_null)

    # 8a. Evidence coverage (primary ablation delta)
    def _score_evidence_coverage(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec):
            return None
        out = recall_at_k(
            gold, rec.snapshot.retrieved_chunks, k=4, chunk_size=config.chunk_size
        )
        return out.score if out.status == "ok" else None

    res_coverage = compute_paired_delta(
        pairs,
        _score_evidence_coverage,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
        join_result=join_res,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta",
            paired_result=res_coverage,
        )
    )

    # 8b. Exact Match delta
    def _score_em(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec) or gold.is_null:
            return None
        out = squad_em(gold, rec.answer)
        return out.score if out.status == "ok" else None

    res_em = compute_paired_delta(
        pairs,
        _score_em,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta_exact_match",
            paired_result=res_em,
        )
    )

    # 8c. F1 delta
    def _score_f1(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec) or gold.is_null:
            return None
        out = squad_f1(gold, rec.answer)
        return out.score if out.status == "ok" else None

    res_f1 = compute_paired_delta(
        pairs,
        _score_f1,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta_f1",
            paired_result=res_f1,
        )
    )

    # 8d. Context Precision delta
    def _score_cp(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec):
            return None
        out = context_precision_at_k(gold, rec.snapshot.retrieved_chunks, k=4)
        return out.score if out.status == "ok" else None

    res_cp = compute_paired_delta(
        pairs,
        _score_cp,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta_context_precision",
            paired_result=res_cp,
        )
    )

    # 8e. Ranking Quality (MRR@10) delta
    def _score_mrr(rec: RunRecord, gold: Any) -> float | None:
        if not has_scorable_payload(rec):
            return None
        out = mrr_at_k(gold, rec.snapshot.retrieved_chunks, k=10)
        return out.score if out.status == "ok" else None

    res_mrr = compute_paired_delta(
        pairs,
        _score_mrr,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_delta_ranking_quality",
            paired_result=res_mrr,
        )
    )

    # 8f. Latency delta (duration_ms)
    def _score_latency(rec: RunRecord, gold: Any) -> float | None:
        return float(rec.duration_ms)

    res_lat = compute_paired_delta(
        pairs,
        _score_latency,
        coverage_denominator=coverage_denom,
        answerable_count=answerable_n,
    )
    dimensions.append(
        make_paired_ablation_delta(
            name="graph_ablation_latency_delta",
            paired_result=res_lat,
        )
    )

    # 8g. Prompt token delta
    has_any_tokens = any(
        (
            p.graph_on.workflow_meta is not None
            and p.graph_on.workflow_meta.prompt_tokens > 0
        )
        or (
            p.graph_off.workflow_meta is not None
            and p.graph_off.workflow_meta.prompt_tokens > 0
        )
        for p in pairs
    )
    if pairs and not has_any_tokens:
        dimensions.append(
            DimensionResult(
                name="graph_ablation_prompt_token_delta",
                status="skipped",
                reason="No records in join carry workflow_meta.prompt_tokens",
                detail={
                    "n_pairs": float(len(pairs)),
                    "pairing_coverage": float(len(pairs) / coverage_denom)
                    if coverage_denom > 0
                    else 0.0,
                },
                n=0,
            )
        )
    else:

        def _score_tokens(rec: RunRecord, gold: Any) -> float | None:
            if rec.workflow_meta is None:
                return None
            return float(rec.workflow_meta.prompt_tokens)

        res_tokens = compute_paired_delta(
            pairs,
            _score_tokens,
            coverage_denominator=coverage_denom,
            answerable_count=answerable_n,
        )
        dimensions.append(
            make_paired_ablation_delta(
                name="graph_ablation_prompt_token_delta",
                paired_result=res_tokens,
            )
        )

    # 9. abstention_on_unanswerable
    unanswerable_payload_excluded = float(
        p_data.get("payload_excluded_unanswerable", 0)
    )
    if p_data["abstentions"]:
        abs_mean = sum(p_data["abstentions"]) / len(p_data["abstentions"])
        dimensions.append(
            DimensionResult(
                name="abstention_on_unanswerable",
                status="ok",
                score=abs_mean,
                detail={
                    "null_samples": float(len(p_data["abstentions"])),
                    "excluded_payload_records": unanswerable_payload_excluded,
                },
                n=len(p_data["abstentions"]),
            )
        )
    else:
        if unanswerable_payload_excluded > 0:
            skip_reason = (
                "All unanswerable-question records lacked scorable payload "
                "(excluded by the payload rule); none were scored"
            )
        else:
            skip_reason = "Corpus contains no unanswerable questions"
        dimensions.append(
            DimensionResult(
                name="abstention_on_unanswerable",
                status="skipped",
                reason=skip_reason,
                detail={
                    "excluded_payload_records": unanswerable_payload_excluded,
                },
                n=0,
            )
        )

    # 10. wire_contract_conformance
    dimensions.append(make_wire_contract_conformance(records=records))

    # 11. community_summary_quality (placeholder)
    dimensions.append(OBS_04_PLACEHOLDER)

    # 12. run_traceability
    total_recs = len(records)
    traced_count = sum(
        1 for r in records if r.session_id and r.correlation_id and r.index_generation
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

    res_hash = compute_result_hash(dimensions)
    lock_hash = get_lock_hash()
    index_gen = sorted(distinct_gens)[0] if distinct_gens else "unknown-gen"
    gen_model_name = _get_engine_generation_model() or "unknown-generation-model"

    # Find embedding model from first available snapshot or fallback
    emb_model = "unknown-embedding-model"
    for r in records:
        if r.snapshot and getattr(r.snapshot, "embedding_model", None):
            if r.snapshot.embedding_model and r.snapshot.embedding_model.strip():
                emb_model = r.snapshot.embedding_model
                break

    metadata = RunMetadata(
        corpus=corpus_name,
        run_date=datetime.now(UTC).isoformat(),
        commit_sha=os.environ.get("GIT_COMMIT_SHA") or get_commit_sha(),
        generation_model=gen_model_name,
        embedding_model=emb_model,
        judge_model=config.judge_model,
        judge_temperature=config.judge_temperature,
        judge_prompt_version=config.judge_prompt_version,
        sampling_seed=config.sample_seed,
        sample_size_deterministic=len(sampled_questions),
        sample_size_judged=judged_sample_count,
        calibration_completed_n=completed_dual_scores,
        index_generation=index_gen,
        result_hash=res_hash,
        arm_labels=config.arms,
        dependency_lock_hash=lock_hash,
        partial=header_partial,
        notes=calibration_notes,
    )

    report = CorpusReport(
        corpus=corpus_name,
        metadata=metadata,
        dimensions=dimensions,
    )

    # Write report.json to run_dir if not partial
    if not header_partial:
        report_json_path = dir_path / "report.json"
        with open(report_json_path, "w", encoding="utf-8") as f:
            f.write(render_json(report))

    return report
