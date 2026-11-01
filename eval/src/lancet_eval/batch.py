"""S2 reader arms over a batch API: `batch submit` and `batch fetch` (#53, D-254).

An S2 run directory starts as `replay-init` leaves it (``lancet_eval.replay``): the
carried deepseek arm's records and export rows on the S2 corpus. Each reader arm
(``<arm>@<reader>``, D-257) is then read in batches:

``submit`` packs the base arm's export rows with ``generate_from_context pack``, under
the levers each base record echoes (``snapshot.levers``), and refuses a row whose
packed user message is not its ``assembled_prompt`` or whose hash is not the one the
journal header carried. It rewrites each body for the arm's declared reader
(``reader_request.rewrite_pack_body``, #51), prints a cost estimate (D-258: it never
refuses), writes the manifest, then submits one batch whose ``custom_id`` is the
question ID. Questions are taken in the base arm's journal order:

- by default, every base success question the arm holds no record of; ``--limit N``
  takes the first N, so a pilot and a later submit read disjoint questions. ``--limit``
  is for a pilot run only (``replay-init --pilot``, #109): a pilot's records could not
  be replaced in a run of record once the pilot moves a reader to another target
  (D-260), and no arm of a run of record is run halfway (D-258);
- with ``retry_errors``, only the questions whose latest record is a request that
  produced no answer (``RETRYABLE``: errored, expired, canceled, or missing from the
  results); never a ``base_error``, an answer ``render`` rejected, or a response that
  arrived unreadable, since those were billed.

In a run of record it first refuses unless D-73 holds against the journal header's
``created_at`` (``replay.require_d73``), the gate ``compare-levers`` applies after the
spend, so a constant committed or edited after ``replay-init`` stops the submit, not
the report. It refuses while the arm has a pending batch, and when nothing is left to
submit (every question already has a record). Each base error record gets one reader
error record (``BASE_ERROR``), since there is no row to pack and completeness needs
every question under every arm. They are journalled once the endpoint accepts the batch,
so a refused submit writes nothing to the journal; the one exception is a submit
with nothing to send, which journals them and then refuses.

The manifest (``<run>/batches/<arm slug>-<n>.json``) is written before the submit,
with ``batch_id`` null and state ``submitting``, then updated to ``submitted`` with
the batch ID. A crash or network failure between the two leaves it ``submitting``,
which counts as pending: check the endpoint for a batch, then edit or delete the
manifest by hand. A submit the endpoint answered with an error marks it ``rejected``.
Per request it records the body hash (SHA-256 of the exact JSON text sent, the hash
the ``body_hash`` replay clause recomputes), the ``pack`` body, the rewritten fields,
the base row's hash and the levers.

``fetch`` reads each ``submitted`` batch's results; a batch still processing is left
for a later run. Succeeded requests are rendered by ``generate_from_context render``
under the request's levers (#50), the Anthropic stop reason already mapped. Each
result becomes one record under the resume key, with the base record's
``correlation_id`` and ``index_generation``, and ``session_id`` set to the batch ID:

- a rendered answer: a success record, its ``replay`` block (``ReplayProvenance``)
  and usage, and its export row (the base row under the reader label) appended before
  the record;
- an answer ``render`` rejects: an error record that keeps the ``replay`` block and
  usage, because the request was billed (``measure.reader_record_usd``);
- an errored, expired or canceled request, or one the batch returned no result for:
  an error record with no ``replay`` block, since nothing was billed;
- a response that arrived but cannot be read (``batch_unreadable_response``): an
  error record with no ``replay`` block, since it has no usage to price; it was
  probably billed, so ``--retry-errors`` leaves it.

A fetch skips a request the journal already holds a record of from the same batch,
then marks the manifest ``fetched``, so a re-run adds nothing.

D-274 replicates: when the pre-registration declares ``replicates`` K above 1, every
arm answers each question K times, each answer its own request and its own record
(``RunRecord.replicate``, 1 to K), and ``custom_id`` is ``<question ID>_r<k>``. A
reader arm submits replicates 1 to K. The carried deepseek arm already holds
replicate 1 (S1's answer), so ``submit`` on that arm sends replicates 2 to K: the
``pack`` body itself, unrewritten, through OpenRouter's sync chat-completions API
one request at a time (D-278: the Batch API cannot carry the pin, and the model has
no batch variant), journalled every ``SYNC_CHUNK`` requests under a ``sync-`` ID, so a
rerun sends only what holds no record yet. That body carries the engine's provider
pin (D-271: one ``order`` entry, ``allow_fallbacks: false`` and a ``max_price``, with
``config.toml``'s values), and a body without it is refused. Each such record carries a
``replay`` block like a reader record's, which ``provenance.replay_run_failures``
checks. A reader arm's export row is appended once per question, whatever its
replicates; the deepseek arm's is the carried row. With K at 1 every request, manifest
and record is as before.

D-280: a reader declared ``between_tools`` on OpenRouter (Sonnet 5.5) takes the same
sync path, since the Batch API refuses ``between_tools``: its rewritten body goes to
the sync API one request at a time, and each record's ``is_byok`` is its own reply's.
A sync chunk whose answers break ``is_byok``, the provider or ``reasoning_tokens``
stops the run (``SYNC_STOP_CODES``).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lancet_eval import batch_client, parity, preregistration
from lancet_eval.arms import (
    arm_reader,
    arm_slug,
    canonical_arm,
    is_closed_book_arm,
    is_reader_arm,
    reader_base_arm,
)
from lancet_eval.batch_client import (
    BatchClient,
    BatchClientError,
    BatchRequest,
    BatchResult,
    ReaderOutput,
)
from lancet_eval.context_export import (
    CONTEXT_EXPORT_FILE,
    ContextExportError,
    ContextExportRow,
    read_export,
)
from lancet_eval.corpus import CorpusError, load_corpus
from lancet_eval.journal import (
    Journal,
    ReplayProvenance,
    RunRecord,
    WorkflowWireMeta,
    load_records,
    read_journal_header,
)
from lancet_eval.measure import (
    BATCH_PRICE_FACTOR,
    GENERATION_LIST_INPUT_PRICE_PER_1M,
    GENERATION_LIST_OUTPUT_PRICE_PER_1M,
    compute_spend,
    tokens_usd,
)
from lancet_eval.provenance import deepseek_pin_problem, routing_failures
from lancet_eval.reader_request import (
    ReaderDeclaration,
    ReaderPrice,
    ReaderRequest,
    ReaderRequestError,
    Target,
    rewrite_pack_body,
)
from lancet_eval.replay import (
    JOURNAL_FILE,
    REPLAY_SOURCE_KEY,
    ReplayError,
    export_row_sha256,
    is_pilot_run,
    require_d73,
    source_row_hashes,
)

MANIFEST_DIR = "batches"
#: The error type of a reader record whose base record is an error (nothing packed).
BASE_ERROR = "base_error"
#: The error type of a request by its batch status.
RESULT_ERRORS: Mapping[str, str] = {
    "errored": "batch_errored",
    "expired": "batch_expired",
    "canceled": "batch_canceled",
    "unreadable": "batch_unreadable_response",
}
#: The error type of a request the finished batch returned no result for.
NO_RESULT = "batch_no_result"
#: The error types `--retry-errors` resubmits: requests that produced no answer. An
#: answer `render` rejected, or a response that arrived but could not be read, was
#: billed and is the reader's result; resubmitting it would buy a second answer.
RETRYABLE = frozenset({
    RESULT_ERRORS["errored"],
    RESULT_ERRORS["expired"],
    RESULT_ERRORS["canceled"],
    NO_RESULT,
})
#: The error type of a rendered request `render` wrote no line for.
NO_RENDER_LINE = "render_no_line"
PENDING_STATES = frozenset({"submitting", "submitted"})
#: Anthropic's `custom_id` pattern.
_ANTHROPIC_CUSTOM_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_LISTED = 10

#: `parity.run_bin`'s signature: mode, rows, levers and, for `render`, the results.
BinRunner = Callable[..., list[dict[str, Any]]]
ClientFactory = Callable[[Target], BatchClient]

#: The seams the tests replace: the bin, the batch endpoint and the sync endpoint.
bin_runner: BinRunner = parity.run_bin
client_factory: ClientFactory = batch_client.client_for
chat_client_factory: Callable[[], batch_client.OpenRouterChatClient] = (
    batch_client.chat_client
)
#: The manifest target of the sync path: deepseek's replicates (D-278) and a
#: `between_tools` reader (D-280).
SYNC_TARGET = "openrouter-sync"
#: The clauses a sync chunk is stopped on (#133 L5, D-280): where it was routed, who
#: paid, and whether a reader that must not think did.
SYNC_STOP_CODES = frozenset({"is_byok", "provider", "reasoning_tokens"})


class BatchError(ValueError):
    """A batch submit or fetch was refused."""


@dataclass(frozen=True)
class SubmitResult:
    """What `submit` sent."""

    manifest_path: Path
    batch_id: str
    requests: int
    base_errors: int


@dataclass(frozen=True)
class FetchResult:
    """What `fetch` journalled, and which batches are still processing."""

    successes: int
    errors: int
    pending: tuple[str, ...]


#: The engine's deepseek list price (`measure`), the price a deepseek replicate is
#: estimated and costed at when the pre-registration declares no `reference_price`
#: (D-277), like the carried arm (D-257).
DEEPSEEK_PRICE = ReaderPrice(
    GENERATION_LIST_INPUT_PRICE_PER_1M, GENERATION_LIST_OUTPUT_PRICE_PER_1M
)


@dataclass(frozen=True)
class _Run:
    journal: Path
    corpus: str
    header: dict[str, Any]
    readers: dict[str, ReaderDeclaration]
    records: list[RunRecord]
    arms: set[str]
    token: str
    #: D-274: answers per question and arm (K); 1 before replicates.
    replicates: int = 1
    #: The carried deepseek arm (the constant's ``replay_source_arm``).
    source_arm: str | None = None
    #: D-277: deepseek's price, the constant's ``reference_price`` or the list price.
    reference_price: ReaderPrice = DEEPSEEK_PRICE
    #: #149: a reader's own K, below ``replicates`` (``reader_replicates``).
    reader_replicates: dict[str, int] = field(default_factory=dict)


#: One request's unit: a question and its replicate (D-274).
Unit = tuple[str, int]


def custom_id(qid: str, replicate: int, replicates: int) -> str:
    """A request's ``custom_id``: the question ID, or ``<qid>_r<k>`` with K above 1."""
    return qid if replicates == 1 else f"{qid}_r{replicate}"


def _listed(problems: Sequence[str]) -> str:
    more = len(problems) - _LISTED
    return "; ".join(problems[:_LISTED]) + (f" (and {more} more)" if more > 0 else "")


def _load_run(run: Path) -> _Run:
    journal = run / JOURNAL_FILE
    header = read_journal_header(journal)
    if header is None or REPLAY_SOURCE_KEY not in header:
        raise BatchError(
            f"{journal} is not an S2 replay journal (no {REPLAY_SOURCE_KEY!r} header); "
            "run replay-init first"
        )
    corpus = str(header.get("corpus") or "")
    try:
        config = load_corpus(corpus)
    except CorpusError as exc:
        raise BatchError(f"the run's corpus {corpus!r} does not load: {exc}") from exc
    try:
        prereg = preregistration.resolve_corpus(config)
        readers = preregistration.readers_of(prereg)
    except preregistration.PreregistrationError as exc:
        raise BatchError(f"the S2 pre-registration: {exc}") from exc
    run_arms = {canonical_arm(a) for a in config.arms}
    return _Run(
        journal,
        corpus,
        header,
        readers,
        load_records(journal),
        run_arms,
        config.preregistration_token,
        int(getattr(prereg, "replicates", 1)),
        getattr(prereg, "replay_source_arm", None) or None,
        getattr(prereg, "reference_price", None) or DEEPSEEK_PRICE,
        dict(getattr(prereg, "reader_replicates", ())),
    )


def _require_record_ready(run: _Run, limit: int | None) -> None:
    """Refuses ``--limit`` and a failed D-73 in a run of record (#109)."""
    if limit is not None:
        raise BatchError(
            "--limit is for a pilot run: a run of record submits every question, and "
            "a pilot's records could not be replaced in it; make the pilot with "
            "replay-init --pilot in its own run directory"
        )
    created_at = run.header.get("created_at")
    if isinstance(created_at, bool) or not isinstance(created_at, int | float):
        raise BatchError(
            "D-73: the journal header must carry a numeric created_at to prove the "
            f"pre-registration predates the data (got {created_at!r})"
        )
    try:
        require_d73(run.token, created_at=float(created_at))
    except ReplayError as exc:
        raise BatchError(str(exc)) from exc


def _batch_arm(label: str, run: _Run) -> tuple[str, ReaderDeclaration | None]:
    """A batch arm and its reader's declaration; None for the carried deepseek arm.

    The carried arm is a batch arm only with replicates (D-274): its replicates 2 to K
    are new deepseek answers, declared by each request's ``pack`` body
    (``deepseek_request``). Without replicates it is refused as no reader arm.
    """
    try:
        arm = canonical_arm(label)
    except ValueError as exc:
        raise BatchError(str(exc)) from exc
    if arm == run.source_arm and (run.replicates > 1 or is_closed_book_arm(arm)):
        return arm, None
    return _reader_arm(arm, run)


def _target(declaration: ReaderDeclaration | None) -> Target:
    """The endpoint a batch arm's requests go to: deepseek's is OpenRouter."""
    return "openrouter" if declaration is None else declaration.target


def _reader_arm(label: str, run: _Run) -> tuple[str, ReaderDeclaration]:
    try:
        arm = canonical_arm(label)
    except ValueError as exc:
        raise BatchError(str(exc)) from exc
    if not is_reader_arm(arm):
        raise BatchError(f"{label!r} is not a reader arm (<arm>@<reader>, D-257)")
    if arm not in run.arms:
        raise BatchError(f"the corpus {run.corpus!r} does not list the arm {arm!r}")
    declaration = run.readers.get(arm_reader(arm) or "")
    if declaration is None:
        raise BatchError(f"the pre-registration declares no reader for {arm!r}")
    return arm, declaration


def _export_rows(run_dir: Path) -> dict[tuple[str, str], ContextExportRow]:
    """The run's export rows by ``(question_id, arm)``."""
    try:
        return {
            (r.question_id, r.arm): r
            for r in read_export(run_dir / CONTEXT_EXPORT_FILE)
        }
    except ContextExportError as exc:
        raise BatchError(str(exc)) from exc


def _run_bin(
    runner: BinRunner,
    mode: str,
    rows: Sequence[ContextExportRow],
    levers: Sequence[str],
    results: Sequence[dict[str, Any]] | None = None,
    *,
    model_only: bool = False,
) -> list[dict[str, Any]]:
    """Runs the bin; a bin failure is a refusal (``BatchError``). ``model_only`` is
    passed to the runner only when set (closed-book rows, D-291)."""
    args: list[Any] = [mode, rows, list(levers)]
    if results is not None:
        args.append(results)
    try:
        if model_only:
            return runner(*args, model_only=True)
        return runner(*args)
    except parity.PromptParityError as exc:
        raise BatchError(str(exc)) from exc


def _latest(records: Iterable[RunRecord], arm: str) -> dict[str, RunRecord]:
    """The latest replicate-1 record of each question under `arm`, in first-seen
    order: for the base arm, the carried record every replicate replays."""
    latest: dict[str, RunRecord] = {}
    for rec in records:
        if rec.graph_arm == arm and rec.replicate == 1:
            latest[rec.question_id] = rec
    return latest


def _base_records(run: _Run, base_arm: str) -> dict[str, RunRecord]:
    """The record each question's requests replay: ``_latest`` of the base arm.

    The closed-book arm (D-291) has no drive and so no carried record. Each of its
    export rows (``closed_book.closed_book_init``) stands in as a success with the
    row's correlation ID, never journalled: every question is replayed, and deepseek's
    replicates 1 to K are sent like a reader's.
    """
    if not is_closed_book_arm(base_arm):
        return _latest(run.records, base_arm)
    return {
        qid: RunRecord(
            corpus=run.corpus,
            question_id=qid,
            graph_arm=base_arm,
            outcome="success",
            correlation_id=row.correlation_id,
        )
        for (qid, arm), row in _export_rows(run.journal.parent).items()
        if arm == base_arm
    }


def _latest_units(records: Iterable[RunRecord], arm: str) -> dict[Unit, RunRecord]:
    """The latest record of each question and replicate under `arm`."""
    latest: dict[Unit, RunRecord] = {}
    for rec in records:
        if rec.graph_arm == arm:
            latest[(rec.question_id, rec.replicate)] = rec
    return latest


def _replicates_of(run: _Run, arm: str) -> range:
    """The replicates a submit of `arm` sends: 1 to K, or 2 to K for the carried arm.

    A reader with its own K (#149) sends 1 to that K. The closed-book arm (D-291)
    carries no answer, so its deepseek replicates are 1 to K.
    """
    if not is_reader_arm(arm):
        return range(1 if is_closed_book_arm(arm) else 2, run.replicates + 1)
    reader = arm.rpartition("@")[2]
    return range(1, run.reader_replicates.get(reader, run.replicates) + 1)


# ---- manifests --------------------------------------------------------------------


def manifest_paths(run: Path, arm: str | None = None) -> list[Path]:
    """The run's batch manifests, oldest first; only `arm`'s when given."""
    folder = run / MANIFEST_DIR
    if not folder.is_dir():
        return []
    prefix = f"{arm_slug(arm)}-" if arm is not None else ""
    paths = [p for p in folder.glob(f"{prefix}*.json") if p.is_file()]
    return sorted(paths, key=lambda p: (p.stem.rsplit("-", 1)[0], _seq(p)))


def _seq(path: Path) -> int:
    tail = path.stem.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def read_manifest(path: Path) -> dict[str, Any]:
    """A manifest's JSON object.

    Raises:
        BatchError: If the file is unreadable or not a JSON object.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BatchError(f"unreadable manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BatchError(f"manifest {path} is not a JSON object")
    return data


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def _new_manifest_path(run: Path, arm: str) -> Path:
    existing = [_seq(p) for p in manifest_paths(run, arm)]
    return run / MANIFEST_DIR / f"{arm_slug(arm)}-{max(existing, default=0) + 1}.json"


def _pending(run: Path, arm: str) -> list[str]:
    found = []
    for path in manifest_paths(run, arm):
        manifest = read_manifest(path)
        if manifest.get("arm") == arm and manifest.get("state") in PENDING_STATES:
            found.append(
                f"{path.name} ({manifest.get('state')}, batch "
                f"{manifest.get('batch_id')})"
            )
    return found


# ---- submit -----------------------------------------------------------------------


def _base_error_records(
    run: _Run,
    arm: str,
    base: Mapping[str, RunRecord],
    held: Mapping[Unit, RunRecord],
    replicates: range,
) -> list[RunRecord]:
    return [
        RunRecord(
            corpus=run.corpus,
            question_id=qid,
            graph_arm=arm,
            outcome="error",
            error_type=BASE_ERROR,
            error=f"the base arm's record is an error ({rec.error_type}): nothing "
            "to replay",
            correlation_id=rec.correlation_id,
            index_generation=rec.index_generation,
            replicate=k,
        )
        for qid, rec in base.items()
        if rec.outcome == "error"
        for k in replicates
        if (qid, k) not in held
    ]


def _select(
    arm: str,
    base: Mapping[str, RunRecord],
    held: Mapping[Unit, RunRecord],
    replicates: range,
    *,
    retry_errors: bool,
    limit: int | None,
) -> list[Unit]:
    """The units to send; ``limit`` takes every replicate of the first N questions."""
    if retry_errors:
        chosen = [
            (qid, k)
            for qid in base
            for k in replicates
            if (rec := held.get((qid, k))) is not None
            and rec.outcome == "error"
            and rec.error_type in RETRYABLE
        ]
    else:
        chosen = [
            (qid, k)
            for qid, rec in base.items()
            if rec.outcome == "success"
            for k in replicates
            if (qid, k) not in held
        ]
    if not chosen:
        successes = sum(r.outcome == "success" for r in held.values())
        retryable = sum(
            r.outcome == "error" and r.error_type in RETRYABLE for r in held.values()
        )
        final = len(held) - successes - retryable
        hint = " (use --retry-errors)" if retryable and not retry_errors else ""
        raise BatchError(
            f"nothing to submit for {arm}: {successes} question(s) already have a "
            f"success record, {retryable} a retryable error record{hint} and "
            f"{final} a final error record (base error, or a billed answer that "
            "failed render)"
        )
    if limit is None:
        return chosen
    first = set(list(dict.fromkeys(qid for qid, _ in chosen))[:limit])
    return [unit for unit in chosen if unit[0] in first]


@dataclass(frozen=True)
class _Packed:
    qid: str
    row: ContextExportRow
    levers: tuple[str, ...]
    pack_body: str
    request: ReaderRequest
    row_sha256: str


def _pack(
    qids: Sequence[str],
    base_arm: str,
    base: Mapping[str, RunRecord],
    run: _Run,
    declaration: ReaderDeclaration | None,
    runner: BinRunner,
    custom_ids: Sequence[str],
) -> list[_Packed]:
    """One packed request per question; ``declaration`` None packs deepseek's."""
    rows = _export_rows(run.journal.parent)
    carried = source_row_hashes(run.header)
    # D-291: a closed-book row names no lever and packs the model-only prompt.
    closed_book = is_closed_book_arm(base_arm)
    problems: list[str] = []
    groups: dict[tuple[str, ...], list[ContextExportRow]] = {}
    for qid in qids:
        row = rows.get((qid, base_arm))
        snapshot = base[qid].snapshot
        if row is None:
            problems.append(f"{qid}: no {base_arm!r} export row")
        elif snapshot is None and not closed_book:
            problems.append(f"{qid}: the base record has no snapshot to read levers")
        elif export_row_sha256(row) != carried.get((qid, base_arm)):
            problems.append(f"{qid}: the base row differs from the carried row's hash")
        else:
            levers = () if snapshot is None else tuple(snapshot.levers)
            groups.setdefault(levers, []).append(row)
    packed: dict[str, _Packed] = {}
    for levers, group in groups.items():
        lines = {
            (str(line.get("question_id")), str(line.get("arm"))): line
            for line in _run_bin(
                runner, "pack", group, levers, model_only=closed_book
            )
        }
        for row in group:
            qid = row.question_id
            line = lines.get((qid, base_arm))
            if line is None or line.get("outcome") != "success":
                why = "no line" if line is None else line.get("error")
                problems.append(f"{qid}: pack failed: {why}")
                continue
            try:
                body = str(line["body"])
                if parity.user_message(body) != row.assembled_prompt:
                    problems.append(
                        f"{qid}: the packed user message is not the row's "
                        "assembled_prompt (engine config or levers changed)"
                    )
                    continue
                request = (
                    deepseek_request(body, run.reference_price)
                    if declaration is None
                    else rewrite_pack_body(body, declaration)
                )
            except (KeyError, TypeError, ValueError, ReaderRequestError) as exc:
                problems.append(f"{qid}: {exc}")
                continue
            packed[qid] = _Packed(
                qid, row, levers, body, request, export_row_sha256(row)
            )
    if _target(declaration) == "anthropic":
        problems += [
            f"{cid}: not a valid Anthropic custom_id"
            for cid in custom_ids
            if not _ANTHROPIC_CUSTOM_ID.match(cid)
        ]
    if problems:
        raise BatchError(
            f"submit refused before any request: {len(problems)} problem(s): "
            f"{_listed(problems)}"
        )
    return [packed[qid] for qid in qids]


#: The share of list price a deepseek replicate is estimated and spent at: 1, since
#: it goes through the sync API at full price (D-278; the Claude readers' half price is
#: the BYOK Batch API's, `BATCH_PRICE_FACTOR`).
DEEPSEEK_PRICE_FACTOR = 1.0
#: D-278: deepseek replicates journalled after every this many sync requests, so a
#: crash loses at most this many billed answers and a rerun sends only the rest.
SYNC_CHUNK = 20


def price_factor(arm: str, *, sync: bool = False) -> float:
    """The share of list price a request of `arm` is billed at: the Batch API's half
    for a batched reader, full price through the sync API (D-278, D-280)."""
    if not is_reader_arm(arm):
        return DEEPSEEK_PRICE_FACTOR
    return 1.0 if sync else BATCH_PRICE_FACTOR


def sync_reader(declaration: ReaderDeclaration) -> bool:
    """Whether a reader goes through the sync API rather than a batch (D-280).

    OpenRouter's Batch API refuses ``thinking: {type: "between_tools"}`` (the S2
    pilot's Sonnet 5.5 batch failed whole on it, #138), so an OpenRouter reader
    declared ``between_tools`` is sent one request at a time to the sync API, with
    its ``provider.only`` pin and ``thinking`` kept.
    """
    return (
        declaration.target == "openrouter" and declaration.thinking == "between_tools"
    )


def deepseek_request(
    pack_body: str, price: ReaderPrice = DEEPSEEK_PRICE
) -> ReaderRequest:
    """A deepseek replicate's request (D-274): the ``pack`` body, nothing rewritten,
    estimated at `price` (the constant's ``reference_price``, D-277).

    Raises:
        ReaderRequestError: If the body is not a JSON object, or does not carry the
            D-271 provider pin (``provenance.deepseek_pin_problem``) with
            ``config.toml``'s values (``configured_pin_problem``).
    """
    try:
        body = json.loads(pack_body)
    except ValueError as exc:
        raise ReaderRequestError(f"unreadable pack body: {exc}") from exc
    if not isinstance(body, dict):
        raise ReaderRequestError("the pack body is not a JSON object")
    problem = deepseek_pin_problem(body) or configured_pin_problem(body)
    if problem is not None:
        raise ReaderRequestError(problem)
    declaration = ReaderDeclaration(
        slug=str(body.get("model")),
        target="openrouter",
        thinking="off",
        price=price,
    )
    return ReaderRequest(
        reader=declaration, body=body, body_json=pack_body, rewritten_fields=()
    )


def configured_pin_problem(body: Mapping[str, Any]) -> str | None:
    """Why a pinned deepseek body's pin is not D-271's as configured, or None.

    D-271's values live in ``config/config.toml`` ``[openrouter]``
    (``generation_provider_order`` and the ``generation_max_price_*`` caps); the
    engine's ``pack`` body must carry exactly those, so a deepseek replicate goes to
    the provider and under the cap the engine's own generation does.
    """
    from lancet_eval.config import repo_root

    with (repo_root() / "config" / "config.toml").open("rb") as f:
        openrouter = tomllib.load(f).get("openrouter", {})
    caps = {
        key: openrouter[f"generation_max_price_{key}"]
        for key in ("prompt", "completion")
        if f"generation_max_price_{key}" in openrouter
    }
    provider = body["provider"]
    if provider["order"] != openrouter.get("generation_provider_order"):
        return (
            f"D-271: the pack body's provider order {provider['order']!r} is not "
            f"config.toml's {openrouter.get('generation_provider_order')!r}"
        )
    if provider["max_price"] != caps:
        return (
            f"D-271: the pack body's max_price {provider['max_price']!r} is not "
            f"config.toml's {caps!r}"
        )
    return None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cost_estimate(
    packed: Sequence[_Packed],
    base: Mapping[str, RunRecord],
    declaration: ReaderDeclaration,
    spent: float,
    rate: float = BATCH_PRICE_FACTOR,
) -> str:
    """The D-258 estimate printed before a submit; it never refuses.

    Each request is priced at the reader's sync list price times `rate`
    (`price_factor`), with the deepseek record's token counts as the expected usage
    and the body's `max_completion_tokens` as the output bound.
    """
    price = declaration.price
    expected = bound = 0.0
    for item in packed:
        meta = base[item.qid].workflow_meta
        # A closed-book stand-in (D-291) has no usage: about 4 characters a token.
        prompt = meta.prompt_tokens if meta else len(item.request.body_json) // 4
        completion = meta.completion_tokens if meta else 0
        body = item.request.body
        max_out = int(body.get("max_completion_tokens", body.get("max_tokens", 0)))
        expected += prompt * price.input_per_mtok + completion * price.output_per_mtok
        bound += prompt * price.input_per_mtok + max_out * price.output_per_mtok
    factor = rate / 1_000_000.0
    return (
        f"Cost estimate (D-258, never refuses): {len(packed)} request(s) to "
        f"{declaration.slug} at {rate} x ${price.input_per_mtok}/"
        f"${price.output_per_mtok} per MTok: about ${expected * factor:.4f} at the "
        f"deepseek arm's token counts, at most ${bound * factor:.4f} if every answer "
        f"reached its output limit. Spent on this arm so far: ${spent:.4f}."
    )


def submit(
    *,
    run: Path | str,
    arm: str,
    limit: int | None = None,
    retry_errors: bool = False,
    echo: Callable[[str], None] = print,
) -> SubmitResult:
    """Packs, rewrites and submits one batch of a reader arm (module docstring).

    Raises:
        BatchError: If the run is not an S2 replay run, the arm is not a declared
            reader arm of its corpus, a run of record gets ``limit`` or fails D-73, a
            batch of the arm is pending, nothing is left to submit, the bin fails, or
            a row fails to pack, match its prompt or rewrite.
        BatchClientError: If the endpoint refuses the batch, or its API key is not
            set.
    """
    if limit is not None and limit < 1:
        raise BatchError("--limit must be at least 1")
    run_dir = Path(run)
    state = _load_run(run_dir)
    label, declaration = _batch_arm(arm, state)
    pilot = is_pilot_run(state.header)
    if not pilot:
        _require_record_ready(state, limit)
    pending = _pending(run_dir, label)
    if pending:
        raise BatchError(
            f"{label} has a pending batch: {'; '.join(pending)}; fetch it first"
        )
    base_arm = reader_base_arm(label)
    base = _base_records(state, base_arm)
    replicates = _replicates_of(state, label)
    held = {
        unit: rec
        for unit, rec in _latest_units(state.records, label).items()
        if unit[1] in replicates
    }
    journal = Journal(state.journal)
    base_errors = _base_error_records(state, label, base, held, replicates)
    for rec in base_errors:
        held[(rec.question_id, rec.replicate)] = rec
    try:
        units = _select(
            label, base, held, replicates, retry_errors=retry_errors, limit=limit
        )
    except BatchError as exc:
        # Nothing to send, but the base errors still complete the arm.
        for rec in base_errors:
            journal.append(rec)
        if base_errors:
            raise BatchError(
                f"{exc}; journalled {len(base_errors)} base error record(s)"
            ) from exc
        raise
    ids = {unit: custom_id(*unit, state.replicates) for unit in units}
    by_qid = {
        item.qid: item
        for item in _pack(
            list(dict.fromkeys(qid for qid, _ in units)),
            base_arm,
            base,
            state,
            declaration,
            bin_runner,
            list(ids.values()),
        )
    }
    packed = [by_qid[qid] for qid, _ in units]
    reader = packed[0].request.reader

    # D-278: deepseek's replicates go through the sync API; D-280: so does a
    # `between_tools` reader. The other readers go through a batch.
    sync = declaration is None or sync_reader(declaration)
    if sync:
        spent = price_factor(label, sync=True) * sum(
            tokens_usd(r.workflow_meta, reader.price)
            for r in held.values()
            if r.replay is not None and r.workflow_meta is not None
        )
    else:
        spent, _ = compute_spend(
            list(held.values()), include_embeddings=False, readers=state.readers
        )
    if pilot:
        echo(
            "This is a pilot run (replay-init --pilot): its records are never the S2 "
            "result; start the run of record with a fresh replay-init."
        )
    echo(cost_estimate(packed, base, reader, spent, price_factor(label, sync=sync)))

    chat = chat_client_factory() if sync else None
    client = None if sync else client_factory(reader.target)
    path = _new_manifest_path(run_dir, label)
    manifest: dict[str, Any] = {
        "arm": label,
        "reader": arm_reader(label),
        "target": SYNC_TARGET if sync else reader.target,
        "endpoint": (chat or client).endpoint,  # type: ignore[union-attr]
        "model": reader.slug,
        "batch_id": f"sync-{path.stem}-{int(time.time())}" if sync else None,
        "state": "syncing" if sync else "submitting",
        "retry_errors": retry_errors,
        "partial": limit is not None,
        "created_at": time.time(),
        "requests": {
            ids[unit]: {
                "levers": list(item.levers),
                "body_sha256": _sha256(item.request.body_json),
                "export_row_sha256": item.row_sha256,
                "rewritten_fields": list(item.request.rewritten_fields),
                "pack_body": item.pack_body,
                # D-274: the unit, only once a question has more than one answer.
                **(
                    {"question_id": unit[0], "replicate": unit[1]}
                    if state.replicates > 1
                    else {}
                ),
            }
            for unit, item in zip(units, packed, strict=True)
        },
    }
    _write_manifest(path, manifest)
    if chat is not None:
        return _submit_sync(
            run_dir,
            label,
            manifest,
            path,
            chat,
            units,
            ids,
            packed,
            base_errors,
            echo,
        )
    assert client is not None
    try:
        batch_id = client.submit([
            BatchRequest(ids[unit], item.request.body_json)
            for unit, item in zip(units, packed, strict=True)
        ])
    except BatchClientError:
        manifest["state"] = "rejected"
        _write_manifest(path, manifest)
        raise
    manifest.update(batch_id=batch_id, state="submitted", submitted_at=time.time())
    _write_manifest(path, manifest)
    for rec in base_errors:
        journal.append(rec)
    return SubmitResult(path, batch_id, len(packed), len(base_errors))


def _submit_sync(
    run_dir: Path,
    label: str,
    manifest: dict[str, Any],
    path: Path,
    client: batch_client.OpenRouterChatClient,
    units: Sequence[Unit],
    ids: Mapping[Unit, str],
    packed: Sequence[_Packed],
    base_errors: Sequence[RunRecord],
    echo: Callable[[str], None],
) -> SubmitResult:
    """Sends an arm's requests one at a time through the sync API: deepseek's
    replicates (D-278) or a `between_tools` reader's answers (D-280).

    Every `SYNC_CHUNK` requests are rendered and journalled as `fetch` journals a
    batch, under the manifest's sync ID, so a rerun after a crash sends only the
    replicates that hold no record yet. A chunk with a misrouted answer stops the
    run there (#133 L5). The manifest ends `fetched`; one left
    `syncing` is not pending, since every answer it got is already journalled.
    """
    batch_id = str(manifest["batch_id"])
    journal = Journal(run_dir / JOURNAL_FILE)
    for rec in base_errors:
        journal.append(rec)
    echo(
        f"{len(units)} request(s) of {label} go through the sync chat-completions API "
        f"one at a time (D-278, D-280), journalled every {SYNC_CHUNK}."
    )
    pairs = list(zip(units, packed, strict=True))
    for start in range(0, len(pairs), SYNC_CHUNK):
        chunk = pairs[start : start + SYNC_CHUNK]
        results = [
            client.complete(BatchRequest(ids[unit], item.request.body_json))
            for unit, item in chunk
        ]
        part = {
            **manifest,
            "requests": {ids[u]: manifest["requests"][ids[u]] for u, _ in chunk},
        }
        try:
            _journal_batch(run_dir, _load_run(run_dir), label, part, results)
        except (KeyError, TypeError) as exc:
            raise BatchError(f"manifest {path} is malformed: {exc!r}") from exc
        # #133 L5: a misroute stops the run before the rest of the arm is spent.
        state = _load_run(run_dir)
        sent = {ids[u] for u, _ in chunk}
        misrouted = [
            r
            for r in state.records
            if r.graph_arm == label
            and r.session_id == batch_id
            and custom_id(r.question_id, r.replicate, state.replicates) in sent
            and routing_failures(r, state.readers, SYNC_STOP_CODES)
        ]
        if misrouted:
            _routing_summary(state, {label: {batch_id}}, echo)
            raise BatchError(
                f"{len(misrouted)} answer(s) of the last {len(chunk)} break is_byok, "
                "the provider or reasoning_tokens; stopped before sending more "
                "(#133, D-280). "
                "They stay recorded and score will refuse them: tell the owner before "
                f"any rerun. {path.name} stays 'syncing'; a rerun sends only the rest"
            )
    manifest.update(state="fetched", fetched_at=time.time())
    _write_manifest(path, manifest)
    _routing_summary(_load_run(run_dir), {label: {batch_id}}, echo)
    return SubmitResult(path, batch_id, len(packed), len(base_errors))


def _routing_summary(
    state: _Run, fetched: Mapping[str, set[str]], echo: Callable[[str], None]
) -> None:
    """Per arm, the billed records just journalled that break ``is_byok`` or the
    provider (#133 L5): a misroute shows before the other arms have spent."""
    for label, batch_ids in fetched.items():
        records = [
            r
            for r in state.records
            if r.graph_arm == label and r.session_id in batch_ids and r.replay
        ]
        bad = [r for r in records if routing_failures(r, state.readers)]
        echo(
            f"Routing ({label}): {len(bad)} of {len(records)} billed record(s) "
            "break is_byok or the provider"
            + ("; score will refuse them (#133)" if bad else "")
        )


# ---- fetch ------------------------------------------------------------------------


def render_line(qid: str, arm: str, output: ReaderOutput) -> dict[str, Any]:
    """One line of `render`'s results file (#50's schema)."""
    return {
        "question_id": qid,
        "arm": arm,
        "content": output.content,
        "finish_reason": output.finish_reason,
        "usage": {
            "prompt_tokens": output.prompt_tokens,
            "completion_tokens": output.completion_tokens,
            "total_tokens": output.total_tokens,
        },
    }


def _replay(
    request: Mapping[str, Any], batch_id: str, out: ReaderOutput
) -> ReplayProvenance:
    return ReplayProvenance(
        export_row_sha256=request["export_row_sha256"],
        pack_body=request["pack_body"],
        sent_body_sha256=request["body_sha256"],
        rewritten_fields=list(request["rewritten_fields"]),
        model=out.model,
        provider=out.provider,
        is_byok=out.is_byok,
        reasoning_tokens=out.reasoning_tokens,
        batch_id=batch_id,
        content_block_types=(
            None if out.content_block_types is None else list(out.content_block_types)
        ),
    )


def fetch(
    *,
    run: Path | str,
    arms: Sequence[str] | None = None,
    echo: Callable[[str], None] = print,
) -> FetchResult:
    """Journals every finished batch of the run, or of `arms` (module docstring).

    Raises:
        BatchError: If the run is not an S2 replay run, an arm is not a declared
            reader arm, a manifest is unreadable or names a question the run has no
            base record or row of, or the bin fails.
        BatchClientError: If an endpoint cannot be read, or its API key is not set.
    """
    run_dir = Path(run)
    state = _load_run(run_dir)
    wanted = {_batch_arm(a, state)[0] for a in arms or ()}
    successes = errors = 0
    pending: list[str] = []
    #: #133 L5: the batches journalled this fetch, by arm, for the routing summary.
    fetched: dict[str, set[str]] = {}
    for path in manifest_paths(run_dir):
        manifest = read_manifest(path)
        label = str(manifest.get("arm"))
        if wanted and label not in wanted:
            continue
        status = manifest.get("state")
        if status == "submitting":
            echo(
                f"{path.name}: the submit did not record a batch ID; check the "
                "endpoint, then fix or delete the manifest"
            )
            pending.append(path.name)
            continue
        if status != "submitted":
            continue
        _, declaration = _batch_arm(label, state)
        batch_id = manifest.get("batch_id")
        if not isinstance(batch_id, str) or not batch_id:
            raise BatchError(f"manifest {path} is submitted but names no batch ID")
        results = client_factory(_target(declaration)).results(batch_id)
        if results is None:
            echo(f"{label}: batch {batch_id} is still processing")
            pending.append(batch_id)
            continue
        try:
            ok, failed = _journal_batch(run_dir, state, label, manifest, results)
        except (KeyError, TypeError) as exc:
            raise BatchError(f"manifest {path} is malformed: {exc!r}") from exc
        successes += ok
        errors += failed
        manifest.update(state="fetched", fetched_at=time.time())
        _write_manifest(path, manifest)
        state = _load_run(run_dir)
        fetched.setdefault(label, set()).add(batch_id)
    _routing_summary(state, fetched, echo)
    return FetchResult(successes, errors, tuple(pending))


def _journal_batch(
    run_dir: Path,
    state: _Run,
    label: str,
    manifest: Mapping[str, Any],
    results: Sequence[BatchResult],
) -> tuple[int, int]:
    batch_id = str(manifest["batch_id"])
    requests: Mapping[str, Mapping[str, Any]] = manifest["requests"]
    # D-274: a request names its unit; before replicates its custom_id is the qid.
    unit_of: dict[str, Unit] = {
        cid: (str(req.get("question_id", cid)), int(req.get("replicate", 1)))
        for cid, req in requests.items()
    }
    done = {
        (r.question_id, r.replicate)
        for r in state.records
        if r.graph_arm == label and r.session_id == batch_id
    }
    base_arm = reader_base_arm(label)
    base = _base_records(state, base_arm)
    rows = _export_rows(run_dir)
    unknown = [
        cid
        for cid, (qid, _) in unit_of.items()
        if unit_of[cid] not in done and (qid not in base or (qid, base_arm) not in rows)
    ]
    if unknown:
        raise BatchError(
            f"batch {batch_id} of {label}: no {base_arm!r} record or export row for "
            f"{_listed(unknown)}; the run no longer matches the manifest"
        )
    by_id = {r.custom_id: r for r in results if r.custom_id in requests}
    # #137: a batch the endpoint failed as a whole names why in one message.
    failed = getattr(results, "error", None)
    records: dict[str, RunRecord] = {}
    # One render call per levers and replicate: render keys its lines by question.
    to_render: dict[tuple[tuple[str, ...], int], list[tuple[str, ReaderOutput]]] = {}

    def record_fields(cid: str) -> dict[str, Any]:
        qid, replicate = unit_of[cid]
        rec = base[qid]
        return {
            "corpus": state.corpus,
            "question_id": qid,
            "graph_arm": label,
            "correlation_id": rec.correlation_id,
            "index_generation": rec.index_generation,
            "session_id": batch_id,
            "partial": bool(manifest.get("partial")),
            "replicate": replicate,
        }

    for cid in requests:
        if unit_of[cid] in done:
            continue
        result = by_id.get(cid)
        if result is None:
            records[cid] = RunRecord(
                **record_fields(cid),
                outcome="error",
                error_type=NO_RESULT,
                error=f"batch {batch_id} returned no result for this request"
                + (f": {failed}" if failed else ""),
            )
        elif result.output is None or result.status != "succeeded":
            records[cid] = RunRecord(
                **record_fields(cid),
                outcome="error",
                error_type=RESULT_ERRORS.get(result.status, "batch_errored"),
                error=result.error or f"the request {result.status}",
            )
        else:
            key = (tuple(requests[cid]["levers"]), unit_of[cid][1])
            to_render.setdefault(key, []).append((cid, result.output))

    new_rows: dict[str, ContextExportRow] = {}
    for (levers, _), group in to_render.items():
        reader_rows = [
            rows[(unit_of[cid][0], base_arm)].model_copy(update={"arm": label})
            for cid, _ in group
        ]
        lines = {
            str(line.get("question_id")): line
            for line in _run_bin(
                bin_runner,
                "render",
                reader_rows,
                levers,
                [render_line(unit_of[cid][0], label, out) for cid, out in group],
                model_only=is_closed_book_arm(base_arm),
            )
            if line.get("arm") == label
        }
        for (cid, out), row in zip(group, reader_rows, strict=True):
            qid = unit_of[cid][0]
            replay = _replay(requests[cid], batch_id, out)
            meta = WorkflowWireMeta(
                prompt_tokens=out.prompt_tokens, completion_tokens=out.completion_tokens
            )
            line = lines.get(qid)
            if line is not None and line.get("outcome") == "success":
                records[cid] = _success(record_fields(cid), line, replay, meta)
                if (qid, label) not in rows:
                    new_rows.setdefault(qid, row)
            else:
                records[cid] = RunRecord(
                    **record_fields(cid),
                    outcome="error",
                    error_type=(
                        str(line.get("error_type")) if line else NO_RENDER_LINE
                    ),
                    error=(
                        str(line.get("error"))
                        if line
                        else "generate_from_context render wrote no line"
                    ),
                    workflow_meta=meta,
                    replay=replay,
                )

    if new_rows:
        with open(
            run_dir / CONTEXT_EXPORT_FILE, "a", encoding="utf-8", newline="\n"
        ) as f:
            f.writelines(
                json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n"
                for row in new_rows.values()
            )
    journal = Journal(state.journal)
    for cid in requests:
        if cid in records:
            journal.append(records[cid])
    written = list(records.values())
    return (
        sum(r.outcome == "success" for r in written),
        sum(r.outcome == "error" for r in written),
    )


def _success(
    fields: Mapping[str, Any],
    line: Mapping[str, Any],
    replay: ReplayProvenance,
    meta: WorkflowWireMeta,
) -> RunRecord:
    from lancet_eval.client import Notice, StructuredCitation

    return RunRecord(
        **fields,
        outcome="success",
        answer=line.get("answer") or "",
        structured_citations=[
            StructuredCitation.model_validate(c)
            for c in line.get("structured_citations") or []
        ],
        notices=[Notice.model_validate(n) for n in line.get("notices") or []],
        workflow_meta=meta,
        replay=replay,
    )
