"""Synthetic `[split]` journals for the 06.3.6 lever arms (plan 06.3.6-10).

The arm list is read from `arms.ARM_REGISTRY`, never written as a literal list, so the
same builder serves branches A and B (`hybrid+graph-v2` registered: 7 arms) and branch
C (not registered: 6 arms). Every record it builds is provenance-clean unless a
`Spec` says otherwise: the levers echo is the arm's, rerank arms carry telemetry, the
graph-off arms carry GRAPH_ABLATION and the graph-on arms do not.

Shared by `test_lever_comparison.py` and `test_score_levers.py`. The v1.1 external arm
(D-247) gets its records from `make_external_record` and its context export from
`write_external_export`.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lancet_eval.arms import ARM_REGISTRY, ExternalPipeline, arm_slug
from lancet_eval.client import (
    Notice,
    RankedCandidate,
    RerankMeta,
    RetrievalSnapshot,
    StructuredCitation,
)
from lancet_eval.context_export import CONTEXT_EXPORT_FILE, validate_row
from lancet_eval.journal import (
    ExternalProvenance,
    Journal,
    NodeTiming,
    RunRecord,
    WorkflowWireMeta,
)
from lancet_eval.thresholds import FamilySpec, LeverPreRegistration

CORPUS = "levers_split"
REFERENCE = "hybrid"
HEX = "0" * 64
NL = chr(10)
ABLATION = Notice(code="GRAPH_ABLATION", message="", typed_code=18)
NO_EVIDENCE = Notice(code="NO_EVIDENCE", message="", typed_code=1)
RERANK_DEGRADED = Notice(code="RERANK_DEGRADED", message="", typed_code=23)
TOKEN = "PREREGISTRATION_06_3_6"

# Registered arms of a 06.3.6 corpus, in registry order (the two 06.3.5 non-hybrid
# retrieval arms and the v1.1 S0 row, D-247, are not part of it).
ARMS: tuple[str, ...] = tuple(
    a
    for a in ARM_REGISTRY
    if a not in ("dense-only", "bm25-only", "hybrid+rerank+metadata")
)
DECISIONAL: tuple[str, ...] = tuple(
    a
    for a in (
        "hybrid+rerank",
        "hybrid+graph-v2",
        "hybrid+metadata",
        "hybrid+answer-format",
    )
    if a in ARM_REGISTRY
)
SUPPORTING: tuple[str, ...] = tuple(
    a for a in ("hybrid+rerank", "hybrid+graph-v2") if a in ARM_REGISTRY
)
DESCRIPTIVE: tuple[str, ...] = ("hybrid+all", "hybrid+graph")
NULL_GUARD_ARMS = ("hybrid+metadata", "hybrid+answer-format")


def make_prereg(
    arms: Iterable[str] | None = None,
    *,
    floor: float = 0.80,
    b: int = 200,
    margin: float = 0.10,
    min_fraction: float = 0.80,
) -> LeverPreRegistration:
    """A synthetic pre-registration over registered labels (never the real constant).

    `arms` restricts the lever arms (a reduced shape); the registered decisional and
    supporting arms are kept in registry order.
    """
    keep = set(ARMS if arms is None else arms)
    decisional = tuple(a for a in DECISIONAL if a in keep)
    supporting = tuple(a for a in SUPPORTING if a in keep)
    return LeverPreRegistration(
        reference_arm=REFERENCE,
        families=(
            FamilySpec("answer_usable", "decisional", decisional, 0.05),
            FamilySpec("paper_hits_at_4", "supporting", supporting, 0.05),
        ),
        descriptive_arms=tuple(a for a in DESCRIPTIVE if a in keep),
        test="paired_sign_flip_exact_two_sided",
        non_evaluable_rule="p=1_m_unchanged",
        population="pairwise_per_comparison",
        complete_case_floor=floor,
        matching_rule="chunk_id_via_gold_chunks",
        bootstrap_b=b,
        bootstrap_seed=42,
        null_guard_arms=tuple(a for a in NULL_GUARD_ARMS if a in keep),
        null_guard_predicate="metrics.is_abstention",
        null_guard_margin=margin,
        null_guard_min_pair_fraction=min_fraction,
        answer_mix_strata=("comparison_query", "binary_gold"),
        sc2_timeout_rate_floor=0.025,
        rerank_degrade_tripwire_rate=0.20,
        rerank_degrade_tripwire_min_calls=50,
        rerank_consecutive_degrade_halt=5,
        default_rule="synthetic test rule",
        provenance="synthetic test pre-registration",
    )


@dataclass(frozen=True)
class Spec:
    """What one record of one arm looks like.

    Attributes:
        kind: `ok` (exact gold answer line), `wrong`, `abstain` (Insufficient
            information), `noline` (gold in prose, no Answer line), `blank_no_evidence`
            (a blank answer with the NO_EVIDENCE notice) or `answer_yes`.
        ranks: Rank of gold fact a and b in the ranking; None for absent.
        degraded: Rerank degrade by timeout (only meaningful on a rerank arm).
        errored: A failed record (outcome error, no snapshot).
    """

    kind: str = "ok"
    ranks: tuple[int | None, int | None] = (1, 2)
    degraded: bool = False
    errored: bool = False
    retries: int = 0
    prompt_tokens: int = 500


SpecFn = Callable[[str, str], Spec]


@dataclass
class Questions:
    """The synthetic question set."""

    g: list[tuple[str, str, str]] = field(default_factory=list)
    nulls: list[str] = field(default_factory=list)

    @property
    def g_ids(self) -> list[str]:
        return [q for q, _, _ in self.g]

    @property
    def gold(self) -> dict[str, tuple[str, str]]:
        return {q: (t, a) for q, t, a in self.g}


def make_questions(n_g: int = 10, n_null: int = 5) -> Questions:
    """`n_g` G questions cycling the three strata, golds cycling Yes / No / Paris."""
    types = ("comparison_query", "inference_query", "temporal_query")
    golds = ("Yes", "No", "Paris")
    g = [(f"lv-g{i:03d}", types[i % 3], golds[i % 3]) for i in range(n_g)]
    return Questions(g=g, nulls=[f"lv-n{i:03d}" for i in range(n_null)])


def doc_id() -> str:
    from lancet_eval.seed import load_document_map

    return next(iter(load_document_map("multihop_rag").entries))


def fact(qid: str, which: str) -> str:
    return f"Fact {qid} {which} is established in this passage."


def chunk_id(qid: str, which: str) -> str:
    return f"{qid}:{which}"


def _ids(arm: str, qid: str, ranks: tuple[int | None, int | None]) -> list[str]:
    ids = [f"{qid}:{arm_slug(arm)}:f{pos}" for pos in range(1, 13)]
    for which, rank in zip(("a", "b"), ranks, strict=True):
        if rank is not None:
            ids[rank - 1] = chunk_id(qid, which)
    return ids


def _excerpt(cid: str) -> str:
    qid, _, tail = cid.partition(":")
    if tail in ("a", "b"):
        return f"... {fact(qid, tail)} ..."
    return "unrelated filler text"


def _answer(kind: str, gold: str) -> str:
    return {
        "ok": f"Based on the evidence.{NL}Answer: {gold}",
        "wrong": f"Based on the evidence.{NL}Answer: Wrong guess",
        "abstain": f"Evidence is thin.{NL}Answer: Insufficient information",
        "noline": f"I believe it is {gold}.",
        "answer_yes": f"Based on the evidence.{NL}Answer: Yes",
        "blank_no_evidence": "",
    }[kind]


def make_record(
    arm: str, qid: str, spec: Spec, qs: Questions, *, corpus: str = CORPUS
) -> RunRecord:
    """One record of `arm` for `qid`, provenance-clean unless `spec` breaks it."""
    arm_spec = ARM_REGISTRY[arm]
    is_null = qid in qs.nulls
    rerank_arm = "rerank" in arm_spec.levers
    if spec.errored:
        return RunRecord(
            corpus=corpus,
            question_id=qid,
            graph_arm=arm,
            outcome="error",
            error_type="timeout",
            error="boom",
            index_generation="gen1",
        )
    gold = "" if is_null else qs.gold[qid][1]
    doc = doc_id()
    ids = _ids(arm, qid, spec.ranks if not is_null else (None, None))
    ranking = [
        RankedCandidate(
            chunk_id=cid,
            document_id=doc,
            fused_rank=i,
            vector_rank=i if arm_spec.retrieval_mode != "bm25_only" else None,
            bm25_rank=i if arm_spec.retrieval_mode != "dense_only" else None,
            graph_rank=None,
        )
        for i, cid in enumerate(ids, start=1)
    ]
    final = [
        StructuredCitation(
            chunk_id=r.chunk_id,
            document_id=doc,
            excerpt=_excerpt(r.chunk_id),
            rank=r.fused_rank,
        )
        for r in ranking[:8]
    ]
    kind = spec.kind
    if is_null and kind == "ok":
        kind = "abstain"
    blank = kind == "blank_no_evidence"
    notices: list[Notice] = []
    if arm_spec.disable_graph_context:
        notices.append(ABLATION)
    if blank:
        notices.append(NO_EVIDENCE)
    rerank_meta = None
    if rerank_arm:
        if spec.degraded:
            notices.append(RERANK_DEGRADED)
            rerank_meta = RerankMeta(
                latency_ms=1706,
                cost_credits=0.0,
                cost_reported=False,
                outcome="degraded_timeout",
            )
        else:
            rerank_meta = RerankMeta(
                latency_ms=300 + len(qid),
                cost_credits=0.00035,
                cost_reported=True,
                outcome="completed",
            )
    snapshot = RetrievalSnapshot(
        index_generation="gen1",
        vector_weight=1.0,
        bm25_weight=1.0,
        rrf_k=60,
        candidate_limit=32,
        final_limit=8,
        result_hash="abc123",
        retrieved_chunks=[] if blank else final,
        retrieval_mode=arm_spec.retrieval_mode,
        pre_truncation_ranking=[] if blank else ranking,
        levers=list(arm_spec.levers),
    )
    return RunRecord(
        corpus=corpus,
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer=_answer(kind, gold),
        index_generation="gen1",
        duration_ms=1000.0,
        notices=notices,
        structured_citations=[] if (is_null or blank) else final[:1],
        node_timings=[NodeTiming(node_name="RetrieveHybrid", duration_ms=100.0)],
        workflow_meta=WorkflowWireMeta(
            vector_count=0 if arm_spec.retrieval_mode == "bm25_only" else 8,
            bm25_count=0 if arm_spec.retrieval_mode == "dense_only" else 8,
            prompt_tokens=spec.prompt_tokens,
            completion_tokens=50,
            rerank=rerank_meta,
            query_embedding_retries=spec.retries,
        ),
        snapshot=snapshot,
    )


def write_corpus(
    root: Path,
    qs: Questions,
    arms: Iterable[str] = ARMS,
    *,
    token: str | None = TOKEN,
    name: str = CORPUS,
    role: str = "heldout",
) -> Path:
    """Writes the tmp `[split]` corpus under `root/eval/corpora`; returns the gold."""
    corpora = root / "eval" / "corpora"
    (corpora / "levers").mkdir(parents=True, exist_ok=True)
    arm_list = ", ".join(f'"{a}"' for a in arms)
    lines = [
        "[documents]",
        'map_corpus = "multihop_rag"',
        "chunk_size = 500",
        "[questions]",
        'file = "levers/questions.jsonl"',
        'label_format = "multihop_rag"',
        "sample_seed = 42",
        "sample_size = 100",
        "[models]",
        'judge_model = "meta-llama/llama-3.3-70b-instruct"',
        "[arms]",
        f"arms = [{arm_list}]",
        "[split]",
        'file = "levers/split.json"',
        f'role = "{role}"',
    ]
    if token is not None:
        lines += ["[preregistration]", f'token = "{token}"']
    (corpora / f"{name}.toml").write_text("\n".join([*lines, ""]), encoding="utf-8")
    rows = []
    for qid, qtype, answer in qs.g:
        rows.append({
            "question_id": qid,
            "query": f"Question {qid}?",
            "question_type": qtype,
            "answer": answer,
            "evidence_list": [
                {"title": "t", "fact": fact(qid, "a")},
                {"title": "t", "fact": fact(qid, "b")},
            ],
        })
    for qid in qs.nulls:
        rows.append({
            "question_id": qid,
            "query": f"Question {qid}?",
            "question_type": "null_query",
            "answer": "Insufficient information",
            "evidence_list": [],
        })
    (corpora / "levers" / "questions.jsonl").write_text(
        "".join(json.dumps(r) + NL for r in rows), encoding="utf-8"
    )
    (corpora / "levers" / "split.json").write_text(
        json.dumps({
            "derivation_rule": "test",
            "populations_sha256": HEX,
            "diag_selection_sha256": HEX,
            "questions_sample_sha256": HEX,
            "dev_source": "dev.json",
            "order_seed": 42,
            "dev_ids": [*qs.g_ids, *qs.nulls] if role == "dev" else ["lv-dev1"],
            "heldout_g_ids": ["lv-h1"] if role == "dev" else qs.g_ids,
            "heldout_null_ids": ["lv-hn1"] if role == "dev" else qs.nulls,
        }),
        encoding="utf-8",
    )
    gold = root / "gold_chunks.jsonl"
    gold.write_text(
        "".join(
            json.dumps({
                "question_id": qid,
                "evidence_index": i,
                "title": "t",
                "document_id": doc_id(),
                "state": "in_chunk",
                "chunk_ids": [chunk_id(qid, which)],
            })
            + NL
            for qid in qs.g_ids
            for i, which in enumerate(("a", "b"))
        ),
        encoding="utf-8",
    )
    return gold


def write_journal(
    run_dir: Path,
    qs: Questions,
    spec_fn: SpecFn,
    arms: Iterable[str] = ARMS,
    *,
    corpus: str = CORPUS,
) -> list[RunRecord]:
    """Writes a complete journal for `arms`; returns the records written."""
    journal = Journal(run_dir / "journal.jsonl")
    journal.write_header(corpus=corpus, partial=False)
    written: list[RunRecord] = []
    for qid in [*qs.g_ids, *qs.nulls]:
        for arm in arms:
            rec = make_record(arm, qid, spec_fn(arm, qid), qs, corpus=corpus)
            journal.append(rec)
            written.append(rec)
    return written


def default_spec(arm: str, qid: str) -> Spec:
    """Every arm answers correctly with the gold chunk at rank 1 and 2."""
    return Spec()


# ---- v1.1 external arm (D-247) ------------------------------------------------------

EXTERNAL = "llamaindex"
EXTERNAL_FINGERPRINT = "llamaindex-index-1"


def external_pipeline(**changes: object) -> ExternalPipeline:
    """The S0 LlamaIndex pipeline (D-248), with `changes` applied."""
    values: dict[str, object] = {
        "framework": "llama-index-core",
        "framework_version": "0.14.25",
        "chunk_size": 256,
        "chunk_overlap": 25,
        "dense_top_k": 20,
        "rerank_model": "voyageai/rerank-2.5-lite",
        "keep": 8,
    }
    values.update(changes)
    return ExternalPipeline(**values)  # type: ignore[arg-type]


def _engine_generation() -> tuple[str, list[str]]:
    """The generation model and provider order in the committed config.toml."""
    from lancet_eval.config import repo_root

    with open(repo_root() / "config" / "config.toml", "rb") as f:
        openrouter = tomllib.load(f)["openrouter"]
    return openrouter["generation_model"], list(openrouter["generation_provider_order"])


def make_external_record(
    qid: str,
    spec: Spec,
    qs: Questions,
    *,
    arm: str = EXTERNAL,
    corpus: str = CORPUS,
    pipeline: ExternalPipeline | None = None,
    index_fingerprint: str = EXTERNAL_FINGERPRINT,
    generation_model: str | None = None,
    generation_provider_order: list[str] | None = None,
) -> RunRecord:
    """One external record for `qid`: no engine snapshot, provenance-clean by default.

    The generation model and provider order default to the committed engine config's,
    which is what the Lancet arms are compared with.
    """
    if spec.errored:
        return RunRecord(
            corpus=corpus,
            question_id=qid,
            graph_arm=arm,
            outcome="error",
            error_type="timeout",
            error="boom",
        )
    model, order = _engine_generation()
    kind = spec.kind
    if qid in qs.nulls and kind == "ok":
        kind = "abstain"
    gold = "" if qid in qs.nulls else qs.gold[qid][1]
    return RunRecord(
        corpus=corpus,
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer=_answer(kind, gold),
        duration_ms=1000.0,
        workflow_meta=WorkflowWireMeta(
            prompt_tokens=spec.prompt_tokens, completion_tokens=50
        ),
        external=ExternalProvenance(
            pipeline=pipeline or external_pipeline(),
            index_fingerprint=index_fingerprint,
            generation_model=model if generation_model is None else generation_model,
            generation_provider_order=order
            if generation_provider_order is None
            else generation_provider_order,
        ),
    )


def write_external_export(
    run_dir: Path,
    records: Iterable[RunRecord],
    *,
    evidence_count: Callable[[RunRecord], int] = lambda _rec: 8,
    document_id: Callable[[RunRecord, int], str] | None = None,
) -> Path:
    """Writes `context_export.jsonl` with one row per success record; returns its path.

    An engine record's row carries an `assembled_prompt` and the record's
    `correlation_id`; an external record's row carries neither. Each row holds
    `evidence_count(record)` entries whose document is `document_id(record, rank)`
    (the document map's first entry by default).
    """
    doc = doc_id()
    lines: list[str] = []
    for rec in records:
        if rec.outcome != "success":
            continue
        evidence = [
            {
                "rank": rank,
                "chunk_id": f"{rec.question_id}:{arm_slug(rec.graph_arm)}:e{rank}",
                "document_id": doc if document_id is None else document_id(rec, rank),
                "text": fact(rec.question_id, "a") if rank == 1 else "filler text",
                "title": "t",
                "section_path": None,
                "content_type": "text",
                "score": 1.0 / rank,
                "suspicious": False,
                "document_metadata": {
                    "source": "s",
                    "doc_title": "t",
                    "published_date": "2023-01-01",
                },
            }
            for rank in range(1, evidence_count(rec) + 1)
        ]
        row: dict[str, object] = {
            "corpus": rec.corpus,
            "question_id": rec.question_id,
            "arm": rec.graph_arm,
            "question": f"Question {rec.question_id}?",
            "evidence": evidence,
            "graph_facts": [],
        }
        if rec.external is None:
            row["assembled_prompt"] = f"prompt for {rec.question_id}"
            row["correlation_id"] = rec.correlation_id
        lines.append(json.dumps(row) + NL)
    path = run_dir / CONTEXT_EXPORT_FILE
    path.write_text("".join(lines), encoding="utf-8")
    return path


def make_evidence_export_row(
    arm: str,
    qid: str,
    qs: Questions,
    *,
    ranks: tuple[int | None, int | None] = (1, 2),
    texts: Sequence[str] | None = None,
    corpus: str = CORPUS,
) -> dict[str, Any]:
    """One context-export row of `arm` for `qid` that passes #7's validator.

    The eight evidence texts are filler except gold fact a and b at `ranks` (a null
    question gets filler only); `texts` replaces the whole list.
    """
    if texts is None:
        texts = [f"Filler passage {pos} for {qid}." for pos in range(1, 9)]
        if qid not in qs.nulls:
            for which, rank in zip(("a", "b"), ranks, strict=True):
                if rank is not None and rank <= len(texts):
                    texts[rank - 1] = f"Lead sentence. {fact(qid, which)}"
    row = {
        "corpus": corpus,
        "question_id": qid,
        "arm": arm,
        "question": f"Question {qid}?",
        "evidence": [
            {
                "rank": rank,
                "chunk_id": f"{qid}:{arm_slug(arm)}:e{rank}",
                "document_id": doc_id(),
                "text": text,
                "title": "t",
                "section_path": None,
                "content_type": "text",
                "score": 1.0 / rank,
                "suspicious": False,
                "document_metadata": {
                    "source": None,
                    "doc_title": None,
                    "published_date": None,
                },
            }
            for rank, text in enumerate(texts, start=1)
        ],
        "graph_facts": [],
    }
    validate_row(row)
    return row


def write_evidence_export(
    run_dir: Path,
    qs: Questions,
    spec_fn: SpecFn,
    arms: Iterable[str] = ARMS,
    *,
    texts_fn: Callable[[str, str], Sequence[str] | None] | None = None,
) -> Path:
    """Writes `context_export.jsonl` for every non-errored record `write_journal` wrote.

    Each row places the gold facts at the record's `Spec.ranks`; `texts_fn(arm, qid)`,
    when it returns a list, replaces that row's evidence texts.
    """
    rows = []
    for qid in [*qs.g_ids, *qs.nulls]:
        for arm in arms:
            spec = spec_fn(arm, qid)
            if spec.errored:
                continue
            texts = texts_fn(arm, qid) if texts_fn is not None else None
            rows.append(
                make_evidence_export_row(arm, qid, qs, ranks=spec.ranks, texts=texts)
            )
    path = run_dir / CONTEXT_EXPORT_FILE
    path.write_text("".join(json.dumps(r) + NL for r in rows), encoding="utf-8")
    return path
