"""One arm-provenance conformance check for a journal record (D-99/D-100/D-101).

This is AI-SPEC 5 Dimensions row #1.

``provenance_failures`` reports one coded failure per broken clause, on every record
whose RetrieveHybrid completed (a snapshot with a non-empty ``result_hash``):

* **a** the snapshot's ``retrieval_mode`` echo differs from the arm's mode;
* **b** the D-100 ranking is absent beside non-empty ``retrieved_chunks``, or is longer
  than ``candidate_limit``;
* **c** the ranking's prefix differs from ``retrieved_chunks`` in order, ``rank`` or
  ``graph_boosted``, ``fused_rank`` is not 1..n, or the final list is not
  ``min(final_limit, len(ranking))`` long;
* **d** the per-arm rank shape is wrong (a ``bm25_rank`` on dense-only, a
  ``vector_rank`` on bm25-only, a ``graph_rank`` on any graph-off arm);
* **e** a graph-off arm lacks the GRAPH_ABLATION notice or carries GRAPH_UNAVAILABLE,
  or a graph-on arm carries GRAPH_ABLATION (06.3.6 D-134);
* **f** the snapshot config differs from the drive-2 values in
  ``SNAPSHOT_EXPECTATIONS``;
* **g** a non-zero ``bm25_count`` on dense-only or ``vector_count`` on bm25-only
  (corroboration only);
* **h** (06.3.6 D-134) the snapshot's ``levers`` echo differs from the arm's levers;
* **i** (06.3.6 D-134, D-161) a rerank-bearing arm's record carries RERANK_DEGRADED
  (typed code 23): the record is off-arm, counted per arm, and leaves only the
  comparison that arm feeds;
* **j** (06.3.6 D-134) a rerank leak: a non-rerank arm carries rerank telemetry or code
  23, or a rerank-bearing arm carries neither the telemetry nor the notice.

Clause (a) calls ``arms.echo_failures``, clause (h) ``arms.lever_echo_failures`` and
clause (e) reads ``has_arm_provenance`` and ``carries_graph_ablation``; none matches on
message text (D-158 IN-04), so rewording a message in ``arms`` moves no failure
between clauses.

A legacy label (``graph-off``, ``graph-on``) carries no mode echo and no ranking, so
it is held to (e), (f), (h) and (j) only (the last two are vacuous on a journal that
predates the fields). A record whose RetrieveHybrid never completed (no snapshot, or a
partial snapshot with an empty ``result_hash``) has nothing to check for (a) to (d),
(f), (h) and (j); (e) and (i), which read notices, still apply.

``is_ok(record)`` is ok(r) of AI-SPEC 5 Populations: the record is D-34 usable and has
no failure in (a) to (f), (h), (i) or (j). (g) never changes ok.

Drive-time rule (AI-SPEC 6, "Provenance in the paid drive"): in the paid drive, a
failure in ``ZERO_TOLERANCE_CODES`` (a, b, c, d, f, h, j) makes ``score`` refuse
(06.3.5-10), it is not counted as an exclusion. (e) keeps its inherited
count-and-exclude rule: the record leaves P4. (i) is count-and-exclude per arm too: a
degraded rerank record is never silently dropped and never enters the rerank arm's
decisional population. (g) is corroboration only.

An unknown arm label raises ``ValueError`` from the arm registry (fail closed).

External records (v1.1 D-247) have a clause set of their own, and no engine clause
(a to j) runs on them: their retrieval ran outside Lancet, so they carry no snapshot,
notices or telemetry to check, and none is faked. Every external clause is zero
tolerance: ``score`` refuses the run and names the clause.

* **external_record** (per record, ``provenance_failures``): an external success
  record lacks its ``external`` provenance block, or an external record carries an
  engine snapshot; or an engine record carries an ``external`` block;
* **export_k8**: an external success record has no context-export row, or its row
  does not hold exactly ``EXTERNAL_K`` ranked evidence entries;
* **document_map**: an external row's evidence names a ``document_id`` the document
  map does not hold;
* **pipeline_echo**: the record's pipeline echo differs from the pipeline the
  pre-registration fixed for its arm;
* **index_fingerprint**: one external arm's records carry more than one index
  fingerprint;
* **generation_model**: the record's generation model or provider order differs from
  the one the Lancet arms were generated with.

The last five need the run directory, so ``external_run_failures`` checks them over
all records at once, from inputs its caller loads.

Replay records (v1.1 S2, D-257), a reader arm's records, have a clause set of their
own too, and neither the engine nor the external clauses run on them: their context is
the base arm's export row, replayed to another reader, so they carry no snapshot or
notices. Every replay clause is zero tolerance.

* **replay_record** (per record): a reader arm's record carries an engine snapshot or
  an ``external`` block, or its success record lacks its ``replay`` block; or an
  engine or external record carries a ``replay`` block;
* **batch_id** (per record): no batch ID is recorded;
* **row_hash**: the record's export-row hash differs from the carried base row's (the
  journal header's ``replay_source`` hash), or the run's export lacks the base row or
  the reader arm's row, or either row hashes otherwise;
* **prompt** (#82): the ``pack`` body's user message is not, byte for byte, the
  carried base row's ``assembled_prompt``, the prompt the deepseek reader saw (a
  ``pack`` with the wrong levers or after a config change would differ);
* **body_hash**: the sent body's hash is not that of the #51 rewrite of the record's
  ``pack`` body for its declared reader, or the rewrite refuses that body;
* **rewritten_fields**: the recorded field list is not the rewrite's;
* **model**: the response's model is not the declared reader's slug;
* **is_byok**: per the reader's ``target`` (#82, Q4). OpenRouter: the response does
  not report the owner's own key. Native Anthropic: the record carries an
  ``is_byok`` value, which that response never reports;
* **provider**: the record's provider is not ``REPLAY_PROVIDERS[target]``: the
  provider OpenRouter routed to, or the native endpoint's host;
* **reasoning_tokens**: a reader whose thinking is not ``on`` shows thinking (D-260:
  ``off`` and ``between_tools`` must report 0 reasoning tokens; a thinking-on reader,
  Opus 5.5 at effort low, is exempt). The native target's usage has no reasoning
  count, so its record must also list the response's content block types, none of
  them ``THINKING_BLOCK_TYPES``.

The first two are per record (``provenance_failures``); ``replay_run_failures``
checks all ten over every reader-arm record, from inputs its caller loads, since the
target-dependent clauses need the reader's declaration.
"""

from __future__ import annotations

import hashlib
from collections.abc import Container, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from lancet_eval.arms import (
    arm_reader,
    echo_failures,
    is_external_arm,
    is_reader_arm,
    lever_echo_failures,
    reader_base_arm,
    resolve_arm,
)
from lancet_eval.reader_request import (
    ReaderDeclaration,
    ReaderRequestError,
    Target,
    rewrite_pack_body,
)
from lancet_eval.usability import (
    carries_graph_ablation,
    carries_rerank_degraded,
    has_arm_provenance,
    has_rerank_telemetry,
    is_usable,
)

if TYPE_CHECKING:
    from lancet_eval.arms import ExternalPipeline
    from lancet_eval.client import RankedCandidate, StructuredCitation
    from lancet_eval.context_export import ContextExportRow
    from lancet_eval.journal import ReplayProvenance, RunRecord

#: The external clause set (D-247), in the order a refusal lists it.
EXTERNAL_CODES: tuple[str, ...] = (
    "external_record",
    "export_k8",
    "document_map",
    "pipeline_echo",
    "index_fingerprint",
    "generation_model",
)
#: The replay clause set (D-257), in the order a refusal lists it.
REPLAY_CODES: tuple[str, ...] = (
    "replay_record",
    "row_hash",
    "prompt",
    "body_hash",
    "rewritten_fields",
    "model",
    "is_byok",
    "provider",
    "reasoning_tokens",
    "batch_id",
)
#: The provider a replay record must name, by its reader's target (D-257, #82): the
#: provider OpenRouter's response names, or the native endpoint's host, since a native
#: Message Batches result names no provider.
REPLAY_PROVIDERS: Mapping[Target, str] = {
    "openrouter": "Anthropic",
    "anthropic": "api.anthropic.com",
}
#: Native content block types that show the reader thought (#82, D-260).
THINKING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})
#: Ranked evidence entries an external success record's export row must hold
#: (fairness rule 3: k = 8 on every arm).
EXTERNAL_K = 8

# The engine clause sets stay literal: the frozen runs of record are pinned to them
# (test_drive_environment). Every external clause is zero tolerance and breaks ok;
# `is_zero_tolerance` and `is_ok` read both sets.
ZERO_TOLERANCE_CODES = frozenset("abcdfhj")
_OK_CODES = frozenset("abcdefhij")


@dataclass(frozen=True)
class ProvenanceFailure:
    """One broken provenance clause of one record.

    Attributes:
        code: The clause, ``"a"`` to ``"j"``.
        label: The record's stored arm label.
        detail: What differed, in prose.
    """

    code: str
    label: str
    detail: str


def _external_record_failures(record: RunRecord) -> list[ProvenanceFailure]:
    """The per-record external clause of an external arm's record."""
    problems: list[str] = []
    if record.snapshot is not None:
        problems.append("an external record carries an engine snapshot")
    if record.outcome == "success" and record.external is None:
        problems.append("an external success record lacks its external block")
    failures: list[ProvenanceFailure] = []
    if problems:
        failures.append(
            ProvenanceFailure(
                code="external_record",
                label=record.graph_arm,
                detail="; ".join(problems),
            )
        )
    if record.replay is not None:
        failures.append(
            ProvenanceFailure(
                code="replay_record",
                label=record.graph_arm,
                detail="an external record carries a replay block",
            )
        )
    return failures


def _replay_record_failures(record: RunRecord) -> list[ProvenanceFailure]:
    """The per-record replay clauses of a reader arm's record (D-257)."""
    details: dict[str, list[str]] = {}

    def fail(code: str, detail: str) -> None:
        details.setdefault(code, []).append(detail)

    if record.snapshot is not None:
        fail("replay_record", "a replay record carries an engine snapshot")
    if record.external is not None:
        fail("replay_record", "a replay record carries an external block")
    replay = record.replay
    if record.outcome == "success" and replay is None:
        fail("replay_record", "a replay success record lacks its replay block")
    if replay is not None and not replay.batch_id.strip():
        fail("batch_id", "no batch ID recorded")
    return [
        ProvenanceFailure(code=code, label=record.graph_arm, detail="; ".join(found))
        for code, found in sorted(
            details.items(), key=lambda item: REPLAY_CODES.index(item[0])
        )
    ]


@dataclass(frozen=True)
class SnapshotExpectations:
    """The snapshot config every arm of the ablation must report (clause f)."""

    rrf_k: int
    candidate_limit: int
    final_limit: int
    vector_weight: float
    bm25_weight: float


# config/config.toml [engine.retrieval]: rrf_k 60, candidate_limit 32, final_limit 8 and
# weights 1.0/1.0 are the values drive 2 recorded. This phase never changes them.
SNAPSHOT_EXPECTATIONS = SnapshotExpectations(
    rrf_k=60,
    candidate_limit=32,
    final_limit=8,
    vector_weight=1.0,
    bm25_weight=1.0,
)


def _config_failure(
    snapshot_config: SnapshotExpectations, expected: SnapshotExpectations
) -> str:
    diffs = [
        f"{name} {getattr(snapshot_config, name)!r} != {getattr(expected, name)!r}"
        for name in (
            "rrf_k",
            "candidate_limit",
            "final_limit",
            "vector_weight",
            "bm25_weight",
        )
        if getattr(snapshot_config, name) != getattr(expected, name)
    ]
    return "; ".join(diffs)


def _prefix_details(
    ranking: list[RankedCandidate],
    final: list[StructuredCitation],
    final_limit: int,
) -> list[str]:
    """Clause (c): the ranking's prefix is the final list."""
    details: list[str] = []
    gaps = [i + 1 for i, r in enumerate(ranking) if r.fused_rank != i + 1]
    if gaps:
        details.append(
            f"fused_rank is not 1..{len(ranking)} (first break at position {gaps[0]})"
        )
    if len(ranking) < len(final):
        details.append(
            f"ranking holds {len(ranking)} rows, fewer than the "
            f"{len(final)} final chunks"
        )
    if len(final) != min(final_limit, len(ranking)):
        details.append(
            f"{len(final)} final chunks, expected min(final_limit={final_limit}, "
            f"{len(ranking)}) = {min(final_limit, len(ranking))}"
        )
    for i, (row, chunk) in enumerate(zip(ranking, final, strict=False)):
        if row.chunk_id != chunk.chunk_id:
            details.append(
                f"position {i + 1}: ranking {row.chunk_id!r} != "
                f"chunk {chunk.chunk_id!r}"
            )
        elif chunk.rank != row.fused_rank:
            details.append(
                f"position {i + 1}: chunk rank {chunk.rank} != "
                f"fused_rank {row.fused_rank}"
            )
        elif row.graph_boosted != bool(chunk.graph_boosted):
            details.append(
                f"position {i + 1}: ranking graph_boosted {row.graph_boosted} != "
                f"chunk graph_boosted {bool(chunk.graph_boosted)}"
            )
    return details


def provenance_failures(
    record: RunRecord,
    *,
    expected: SnapshotExpectations = SNAPSHOT_EXPECTATIONS,
) -> list[ProvenanceFailure]:
    """Checks a record against its arm's provenance clauses (a) to (j).

    An external arm's record is checked by the per-record external clause only
    (D-247); the run-level external clauses are ``external_run_failures``.

    Args:
        record: A journal record, under a canonical or legacy arm label.
        expected: The snapshot config clause (f) compares against.

    Returns:
        One failure per broken clause, ordered by code. Empty when provenance holds.

    Raises:
        ValueError: If the record's arm label is unknown.
    """
    label = record.graph_arm
    if is_reader_arm(label):
        return _replay_record_failures(record)
    spec = resolve_arm(label)
    if is_external_arm(spec.label):
        return _external_record_failures(record)
    legacy = label != spec.label
    details: dict[str, list[str]] = {}

    def fail(code: str, detail: str) -> None:
        details.setdefault(code, []).append(detail)

    if record.external is not None:
        fail("external_record", "an engine record carries an external block")
    if record.replay is not None:
        fail("replay_record", "an engine record carries a replay block")

    # (e) composed from has_arm_provenance: notices exist even without a snapshot.
    if spec.disable_graph_context and not has_arm_provenance(record):
        fail(
            "e",
            "graph-off arm lacks the GRAPH_ABLATION notice "
            "or carries GRAPH_UNAVAILABLE",
        )
    if not spec.disable_graph_context and carries_graph_ablation(record):
        fail("e", "graph-on arm carries the GRAPH_ABLATION notice")

    # (i) reads notices, so it applies without a snapshot: a degraded rerank record is
    # off-arm and counted, never dropped silently (D-161).
    rerank_arm = "rerank" in spec.levers
    degraded = carries_rerank_degraded(record)
    if rerank_arm and degraded:
        fail("i", "rerank degraded (RERANK_DEGRADED, typed code 23): off-arm record")

    snapshot = record.snapshot
    completed = snapshot is not None and snapshot.result_hash != ""
    if snapshot is not None and completed:
        # (h) the levers echo equals the arm's levers; D-158 IN-04: the function, not
        # message text.
        for message in lever_echo_failures(label, snapshot.levers):
            fail("h", message)
        # (j) no rerank leak onto a non-rerank arm, and no rerank arm without rerank
        # telemetry or the degraded notice.
        telemetry = has_rerank_telemetry(record)
        if rerank_arm and not (telemetry or degraded):
            fail(
                "j",
                "rerank arm record carries neither workflow_meta.rerank nor the "
                "RERANK_DEGRADED notice",
            )
        if not rerank_arm and (telemetry or degraded):
            fail("j", "non-rerank arm record carries rerank telemetry or code 23")
        # (f) the config every arm of the ablation must report.
        observed = SnapshotExpectations(
            rrf_k=snapshot.rrf_k,
            candidate_limit=snapshot.candidate_limit,
            final_limit=snapshot.final_limit,
            vector_weight=snapshot.vector_weight,
            bm25_weight=snapshot.bm25_weight,
        )
        config = _config_failure(observed, expected)
        if config:
            fail("f", config)

        if not legacy:
            # (a) the retrieval_mode echo; the GRAPH_ABLATION check is clause (e),
            # reported above, not twice. D-158 IN-04: clause (a) calls echo_failures
            # directly, so rewording either message moves no failure between clauses.
            for message in echo_failures(label, snapshot.retrieval_mode):
                fail("a", message)

            ranking = snapshot.pre_truncation_ranking
            final = snapshot.retrieved_chunks
            # (b) the ranking is present (omitempty: none beside no chunks is valid).
            if not ranking and final:
                fail(
                    "b",
                    f"no pre_truncation_ranking beside {len(final)} retrieved_chunks",
                )
            if len(ranking) > snapshot.candidate_limit:
                fail(
                    "b",
                    f"ranking holds {len(ranking)} rows, more than "
                    f"candidate_limit {snapshot.candidate_limit}",
                )
            # (c) the prefix is the final list.
            if ranking:
                for detail in _prefix_details(ranking, final, snapshot.final_limit):
                    fail("c", detail)
            # (d) the per-arm rank shape; a rank of 0 or None is absent.
            if spec.retrieval_mode == "dense_only" and any(
                r.bm25_rank for r in ranking
            ):
                fail("d", "dense-only ranking carries a bm25_rank")
            if spec.retrieval_mode == "bm25_only" and any(
                r.vector_rank for r in ranking
            ):
                fail("d", "bm25-only ranking carries a vector_rank")
            if spec.disable_graph_context and any(r.graph_rank for r in ranking):
                fail("d", "graph-off ranking carries a graph_rank")
            # (g) corroboration from the workflow counts.
            meta = record.workflow_meta
            if meta is not None:
                if spec.retrieval_mode == "dense_only" and meta.bm25_count != 0:
                    fail("g", f"dense-only record has bm25_count {meta.bm25_count}")
                if spec.retrieval_mode == "bm25_only" and meta.vector_count != 0:
                    fail("g", f"bm25-only record has vector_count {meta.vector_count}")

    return [
        ProvenanceFailure(code=code, label=label, detail="; ".join(details[code]))
        for code in sorted(details)
    ]


def external_run_failures(
    records: Sequence[RunRecord],
    *,
    export_rows: Mapping[tuple[str, str], ContextExportRow],
    document_ids: Container[str],
    pipelines: Mapping[str, ExternalPipeline],
    generation_model: str,
    generation_provider_order: Sequence[str],
) -> list[ProvenanceFailure]:
    """Checks the run-level external clauses over every external record (D-247).

    Engine records and error records are skipped. A success record without an
    ``external`` block fails the per-record clause, so only ``export_k8`` and
    ``document_map`` are checked for it here.

    Args:
        records: The journal's records, one per question and arm.
        export_rows: The context-export rows by ``(question_id, arm)``.
        document_ids: Every ID and alias of the document map.
        pipelines: The pre-registered pipeline of each external arm.
        generation_model: The model the Lancet arms were generated with.
        generation_provider_order: The provider order they were generated with.

    Returns:
        One failure per broken clause and record, in ``EXTERNAL_CODES`` order, then
        by question; ``index_fingerprint`` is reported once per arm. Each detail
        starts with the question ID (``*`` for a whole arm).
    """
    found: list[tuple[int, str, ProvenanceFailure]] = []

    def fail(code: str, label: str, qid: str, detail: str) -> None:
        failure = ProvenanceFailure(code=code, label=label, detail=f"{qid}: {detail}")
        found.append((EXTERNAL_CODES.index(code), qid, failure))

    fingerprints: dict[str, set[str]] = {}
    for rec in records:
        label = rec.graph_arm
        if not is_external_arm(label) or rec.outcome != "success":
            continue
        qid = rec.question_id
        row = export_rows.get((qid, label))
        if row is None:
            fail("export_k8", label, qid, "no context-export row")
        else:
            if len(row.evidence) != EXTERNAL_K:
                fail(
                    "export_k8",
                    label,
                    qid,
                    f"{len(row.evidence)} ranked evidence entries, expected "
                    f"{EXTERNAL_K}",
                )
            unmapped = sorted({
                e.document_id for e in row.evidence if e.document_id not in document_ids
            })
            if unmapped:
                fail(
                    "document_map",
                    label,
                    qid,
                    f"document_id(s) not in the document map: {unmapped}",
                )
        echo = rec.external
        if echo is None:
            continue
        fingerprints.setdefault(label, set()).add(echo.index_fingerprint)
        expected = pipelines.get(label)
        if expected is None:
            fail("pipeline_echo", label, qid, "no pre-registered pipeline for the arm")
        elif echo.pipeline != expected:
            observed, wanted = asdict(echo.pipeline), asdict(expected)
            diffs = [
                f"{key} {observed[key]!r} != {wanted[key]!r}"
                for key in wanted
                if observed[key] != wanted[key]
            ]
            fail("pipeline_echo", label, qid, "; ".join(diffs))
        if echo.generation_model != generation_model:
            fail(
                "generation_model",
                label,
                qid,
                f"generation model {echo.generation_model!r} != the Lancet arms' "
                f"{generation_model!r}",
            )
        if list(echo.generation_provider_order) != list(generation_provider_order):
            fail(
                "generation_model",
                label,
                qid,
                f"provider order {echo.generation_provider_order!r} != the Lancet "
                f"arms' {list(generation_provider_order)!r}",
            )
    for label, values in sorted(fingerprints.items()):
        if len(values) > 1:
            fail(
                "index_fingerprint",
                label,
                "*",
                f"{len(values)} index fingerprints in one arm: {sorted(values)}",
            )
    found.sort(key=lambda item: (item[0], item[1], item[2].label))
    return [failure for _, _, failure in found]


def _replay_row_failures(
    label: str,
    expected: str | None,
    recorded: str,
    rows: Mapping[str, ContextExportRow | None],
) -> list[str]:
    """The ``row_hash`` details of one reader-arm record (D-257)."""
    from lancet_eval.replay import export_row_sha256

    base = reader_base_arm(label)
    if expected is None:
        return [f"the journal header records no hash of the {base!r} row"]
    details: list[str] = []
    if recorded != expected:
        details.append(
            f"export row hash {recorded!r} != the carried {base!r} row's {expected!r}"
        )
    for which, row in rows.items():
        if row is None:
            details.append(f"no {which} export row")
        elif export_row_sha256(row.model_copy(update={"arm": base})) != expected:
            details.append(f"the {which} export row differs from the carried row")
    return details


def _prompt_failure(pack_body: str, base_row: ContextExportRow | None) -> str | None:
    """The ``prompt`` detail of one reader-arm record, or None when it holds (#82)."""
    from lancet_eval.parity import first_difference, user_message

    if base_row is None:
        return "no base export row to compare the prompt with"
    if base_row.assembled_prompt is None:
        return "the base export row records no assembled_prompt"
    try:
        sent = user_message(pack_body)
    except (KeyError, TypeError, ValueError) as exc:
        return f"the pack body's user message is unreadable: {exc}"
    if sent != base_row.assembled_prompt:
        at = first_difference(sent, base_row.assembled_prompt)
        return (
            "the pack body's user message differs from the base row's "
            f"assembled_prompt at character {at}"
        )
    return None


def _target_failures(
    replay: ReplayProvenance, declaration: ReaderDeclaration
) -> list[tuple[str, str]]:
    """The ``is_byok``, ``provider`` and ``reasoning_tokens`` details (D-257, #82)."""
    found: list[tuple[str, str]] = []
    native = declaration.target == "anthropic"
    if native and replay.is_byok is not None:
        found.append((
            "is_byok",
            f"is_byok is {replay.is_byok!r}, but a native Anthropic response reports "
            "none; expected None",
        ))
    elif not native and replay.is_byok is not True:
        found.append(("is_byok", f"is_byok is {replay.is_byok!r}, expected True"))
    provider = REPLAY_PROVIDERS[declaration.target]
    if replay.provider != provider:
        found.append((
            "provider",
            f"provider {replay.provider!r}, expected {provider!r} for target "
            f"{declaration.target!r}",
        ))
    if declaration.thinking == "on":
        return found
    thinking = f"thinking {declaration.thinking!r}"
    if replay.reasoning_tokens != 0:
        found.append((
            "reasoning_tokens",
            f"{replay.reasoning_tokens} reasoning tokens from a reader with "
            f"{thinking}, expected 0 (D-260)",
        ))
    if native:
        blocks = replay.content_block_types
        if blocks is None:
            found.append((
                "reasoning_tokens",
                "no content block types recorded; a native response's thinking is "
                "checked from them",
            ))
        elif shown := sorted(THINKING_BLOCK_TYPES.intersection(blocks)):
            found.append((
                "reasoning_tokens",
                f"{shown} content block(s) from a reader with {thinking} (D-260)",
            ))
    return found


def replay_run_failures(
    records: Sequence[RunRecord],
    *,
    export_rows: Mapping[tuple[str, str], ContextExportRow],
    source_row_sha256: Mapping[tuple[str, str], str],
    readers: Mapping[str, ReaderDeclaration],
) -> list[ProvenanceFailure]:
    """Checks every replay clause over every reader-arm record (D-257).

    Engine and external records are skipped. An error record is checked by the
    per-record clauses only.

    Args:
        records: The journal's records, one per question and arm.
        export_rows: The run's context-export rows by ``(question_id, arm)``.
        source_row_sha256: The carried base rows' hashes by ``(question_id, arm)``,
            as the journal header records them (``replay.source_row_hashes``).
        readers: The pre-registered reader declarations by reader name.

    Returns:
        One failure per broken clause and record, in ``REPLAY_CODES`` order, then by
        question. Each detail starts with the question ID.
    """
    found: list[tuple[int, str, ProvenanceFailure]] = []

    def fail(code: str, label: str, qid: str, detail: str) -> None:
        failure = ProvenanceFailure(code=code, label=label, detail=f"{qid}: {detail}")
        found.append((REPLAY_CODES.index(code), qid, failure))

    for rec in records:
        label = rec.graph_arm
        if not is_reader_arm(label):
            continue
        qid = rec.question_id
        for failure in _replay_record_failures(rec):
            fail(failure.code, label, qid, failure.detail)
        replay = rec.replay
        if rec.outcome != "success" or replay is None:
            continue
        base = reader_base_arm(label)
        row_details = _replay_row_failures(
            label,
            source_row_sha256.get((qid, base)),
            replay.export_row_sha256,
            {
                "base": export_rows.get((qid, base)),
                "reader": export_rows.get((qid, label)),
            },
        )
        if row_details:
            fail("row_hash", label, qid, "; ".join(row_details))
        prompt = _prompt_failure(replay.pack_body, export_rows.get((qid, base)))
        if prompt is not None:
            fail("prompt", label, qid, prompt)
        reader = arm_reader(label)
        declaration = readers.get(reader) if reader is not None else None
        if declaration is None:
            fail("model", label, qid, f"no declaration for reader {reader!r}")
            continue
        try:
            request = rewrite_pack_body(replay.pack_body, declaration)
        except ReaderRequestError as exc:
            fail("body_hash", label, qid, f"the rewrite refuses the pack body: {exc}")
        else:
            sent = hashlib.sha256(request.body_json.encode("utf-8")).hexdigest()
            if replay.sent_body_sha256 != sent:
                fail(
                    "body_hash",
                    label,
                    qid,
                    f"sent body hash {replay.sent_body_sha256!r} != the rewrite's "
                    f"{sent!r}",
                )
            if tuple(replay.rewritten_fields) != request.rewritten_fields:
                fail(
                    "rewritten_fields",
                    label,
                    qid,
                    f"rewritten fields {replay.rewritten_fields!r} != the rewrite's "
                    f"{list(request.rewritten_fields)!r}",
                )
        if replay.model != declaration.slug:
            fail(
                "model",
                label,
                qid,
                f"model {replay.model!r} != the declared reader {declaration.slug!r}",
            )
        details: dict[str, list[str]] = {}
        for code, detail in _target_failures(replay, declaration):
            details.setdefault(code, []).append(detail)
        for code, listed in details.items():
            fail(code, label, qid, "; ".join(listed))
    found.sort(key=lambda item: (item[0], item[1], item[2].label))
    return [failure for _, _, failure in found]


def is_zero_tolerance(code: str) -> bool:
    """Whether a failure code makes ``score`` refuse: (a, b, c, d, f, h, j), any
    external clause (D-247) or any replay clause (D-257)."""
    return (
        code in ZERO_TOLERANCE_CODES or code in EXTERNAL_CODES or code in REPLAY_CODES
    )


def is_ok(record: RunRecord) -> bool:
    """ok(r) of AI-SPEC 5 Populations.

    The record is D-34 usable and has no failure in clauses (a) to (f), (h), (i), (j),
    the per-record external clause or a per-record replay clause. Clause (g) is
    corroboration only and never changes the result.
    """
    return is_usable(record) and not any(
        f.code in _OK_CODES or f.code in EXTERNAL_CODES or f.code in REPLAY_CODES
        for f in provenance_failures(record)
    )
