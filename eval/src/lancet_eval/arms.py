"""D-101 arm registry: the label -> request-flags table for the retrieval ablation.

``ARM_REGISTRY`` is the sole durable arm-to-flag mapping in the evaluation harness.
The ``[arms]`` section of a corpus TOML, ``--arm`` on ``lancet-eval probe``, the
request the drive sends and the provenance check all derive from it.

Aliases are read-only. ``graph-off`` and ``graph-on`` are the labels drives 1, 1b
and 2 stored; they resolve to ``hybrid`` and ``hybrid+graph`` at lookup only.
``RunRecord.graph_arm`` is never rewritten, because ``legacy_records_digest`` hashes
the stored value and a rewritten label would also break every historical journal.
An unknown label fails closed.

v1.1 (D-247) adds a second kind of arm. An external arm retrieves outside Lancet and
hands the reader a context export; its retrieval mode, ``external``, is none of the
three engine modes. External rows live in ``EXTERNAL_ARMS``, not in ``ARM_REGISTRY``,
so every caller that iterates the registry to build gateway requests (the drive, the
preflight canaries) never sees one. ``resolve_arm`` and ``canonical_arm`` know both
tables, and ``request_fields`` refuses an external label.

v1.1 S1 (D-251) pairs arms from two eval stores in one journal. A label may carry a
store prefix, ``<prefix>/<registry label>`` (``small/hybrid+rerank+metadata``), that
declares the store the arm runs on (``STORE_PREFIXES``). The prefix is part of the arm:
``canonical_arm`` keeps it, so the same row on two stores is two arms, while
``resolve_arm`` and ``request_fields`` read the base row. A legacy alias or an external
arm is never prefixed, and an unknown prefix fails closed. An unprefixed label declares
no store and behaves exactly as before.

v1.1 S2 (D-257) adds reader arms. ``<base>@<reader>``
(``merged/hybrid+rerank+metadata@haiku-5.5``) is the base arm's context replayed to
another reader. The base is any canonical label above, store-prefixed or not, but never
a legacy alias; the reader is one of ``READERS``, and anything else fails closed.
``canonical_arm`` keeps the suffix, so each reader is its own arm, and ``resolve_arm``
returns the base row. A reader arm's records are replay records (``journal.
ReplayProvenance``): they carry no engine snapshot, send no gateway request
(``request_fields`` refuses one) and are never judged.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass as pydantic_dataclass

from lancet_eval.client import LEVER_ORDER, LeverName

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from lancet_eval.client import Notice
    from lancet_eval.corpus import GoldQuestion
    from lancet_eval.journal import RunRecord

RetrievalMode = Literal["dense_only", "bm25_only", "hybrid"]
ArmKind = Literal["engine", "external"]
ArmLabel = Literal[
    "dense-only",
    "bm25-only",
    "hybrid",
    "hybrid+graph",
    "hybrid+rerank",
    "hybrid+metadata",
    "hybrid+answer-format",
    "hybrid+graph-v2",
    "hybrid+all",
    "hybrid+rerank+metadata",
    "hybrid+graph+rerank+metadata",
    "llamaindex",
]

#: The four 06.3.5 labels, in registry order. Judged-stage and calibration code that
#: was sized for the four-arm ablation iterates this tuple, never the whole registry,
#: so the 06.3.6 lever arms (which issue no judge call, D-153) change none of its sizes.
LEGACY_ARM_LABELS: tuple[str, ...] = (
    "dense-only",
    "bm25-only",
    "hybrid",
    "hybrid+graph",
)


class ArmSpec(BaseModel):
    """One D-101 registry row.

    Attributes:
        label: Canonical arm label.
        retrieval_mode: Value of the request's ``retrieval_mode`` field, or
            ``external`` for an arm whose retrieval runs outside Lancet.
        disable_graph_context: Whether the request switches graph context off.
        legacy_aliases: Read-only lookup aliases (drives 1, 1b and 2 labels).
        levers: The 06.3.6 quality levers the arm names on its request, in the
            canonical ``LEVER_ORDER`` (D-136). Empty for the 06.3.5 arms.
        kind: ``engine`` (driven through the gateway) or ``external`` (D-247: answered
            by the generate-only bin over the arm's own context export).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: ArmLabel
    retrieval_mode: RetrievalMode | Literal["external"]
    disable_graph_context: bool
    legacy_aliases: tuple[str, ...] = ()
    levers: tuple[LeverName, ...] = ()
    kind: ArmKind = "engine"

    @model_validator(mode="after")
    def _levers_are_canonical(self) -> Self:
        if (self.kind == "external") != (self.retrieval_mode == "external"):
            raise ValueError(
                f"arm {self.label!r}: kind {self.kind!r} with retrieval_mode "
                f"{self.retrieval_mode!r}; an external arm and only an external arm "
                "has retrieval_mode 'external' (D-247)"
            )
        if self.kind == "external" and (self.levers or self.legacy_aliases):
            raise ValueError(
                f"arm {self.label!r}: an external arm names no engine lever and no "
                "legacy alias (D-247)"
            )
        names = list(self.levers)
        if len(set(names)) != len(names):
            raise ValueError(f"arm {self.label!r}: duplicate levers {names}")
        canonical = [name for name in LEVER_ORDER if name in names]
        if names != canonical:
            raise ValueError(
                f"arm {self.label!r}: levers {names} are not in the canonical "
                f"order {canonical} (D-136)"
            )
        if "graph_v2" in names and self.disable_graph_context:
            raise ValueError(
                f"arm {self.label!r}: graph_v2 cannot be combined with a switched-off "
                "graph (D-165)"
            )
        return self


def _registry_rows() -> tuple[ArmSpec, ...]:
    """The registry rows: the four 06.3.5 arms, then the 06.3.6 lever arms.

    ``hybrid+graph-v2`` exists only when ``graph_v2`` is a declared lever, which the
    committed graph diagnosis selection decides (D-141; a test pins the two together).
    ``hybrid+all`` carries every declared lever, with the graph on iff ``graph_v2``
    is among them (D-149). The v1.1 S0 default, ``hybrid+rerank+metadata`` (D-247),
    follows, so every 06.3.5 and 06.3.6 index keeps its position, and S1's graph-on arm,
    ``hybrid+graph+rerank+metadata``, comes last: the S0 default with the basic graph
    context on, never ``graph_v2`` (D-251).
    """
    rows = [
        ArmSpec(
            label="dense-only",
            retrieval_mode="dense_only",
            disable_graph_context=True,
        ),
        ArmSpec(
            label="bm25-only",
            retrieval_mode="bm25_only",
            disable_graph_context=True,
        ),
        ArmSpec(
            label="hybrid",
            retrieval_mode="hybrid",
            disable_graph_context=True,
            legacy_aliases=("graph-off",),
        ),
        ArmSpec(
            label="hybrid+graph",
            retrieval_mode="hybrid",
            disable_graph_context=False,
            legacy_aliases=("graph-on",),
        ),
        ArmSpec(
            label="hybrid+rerank",
            retrieval_mode="hybrid",
            disable_graph_context=True,
            levers=("rerank",),
        ),
        ArmSpec(
            label="hybrid+metadata",
            retrieval_mode="hybrid",
            disable_graph_context=True,
            levers=("evidence_metadata",),
        ),
        ArmSpec(
            label="hybrid+answer-format",
            retrieval_mode="hybrid",
            disable_graph_context=True,
            levers=("binary_answer_format",),
        ),
    ]
    if "graph_v2" in LEVER_ORDER:
        rows.append(
            ArmSpec(
                label="hybrid+graph-v2",
                retrieval_mode="hybrid",
                disable_graph_context=False,
                levers=("graph_v2",),
            )
        )
    rows.append(
        ArmSpec(
            label="hybrid+all",
            retrieval_mode="hybrid",
            disable_graph_context="graph_v2" not in LEVER_ORDER,
            levers=LEVER_ORDER,
        )
    )
    rows.append(
        ArmSpec(
            label="hybrid+rerank+metadata",
            retrieval_mode="hybrid",
            disable_graph_context=True,
            levers=("rerank", "evidence_metadata"),
        )
    )
    rows.append(
        ArmSpec(
            label="hybrid+graph+rerank+metadata",
            retrieval_mode="hybrid",
            disable_graph_context=False,
            levers=("rerank", "evidence_metadata"),
        )
    )
    return tuple(rows)


ARM_REGISTRY: dict[str, ArmSpec] = {a.label: a for a in _registry_rows()}

#: D-247 external arms. ``llamaindex`` is the MultiHop-RAG paper's LlamaIndex pipeline
#: (D-248). It has no graph, so it counts as graph-off for the graph predicates.
EXTERNAL_ARMS: dict[str, ArmSpec] = {
    a.label: a
    for a in (
        ArmSpec(
            label="llamaindex",
            retrieval_mode="external",
            disable_graph_context=True,
            kind="external",
        ),
    )
}

_ALIAS: dict[str, str] = {
    al: a.label for a in ARM_REGISTRY.values() for al in a.legacy_aliases
}

#: D-251 store prefixes: ``<prefix>/<label>`` runs on the eval store named here
#: (``config.EVAL_STORES``). ``small`` is the v1.0 store, ``merged`` the S1 store.
STORE_PREFIXES: dict[str, str] = {"small": "eval", "merged": "eval-s1"}

#: D-257 reader names: ``<base>@<reader>`` replays the base arm's context to this
#: reader. A pre-registration declares each reader it uses
#: (``preregistration.readers_of``).
READERS: tuple[str, ...] = ("haiku-5.5", "sonnet-5.5", "opus-5.5")


def _split_reader(label: str) -> tuple[str, str | None]:
    """Splits a label into its base label and its reader (None when it has none).

    Raises:
        ValueError: If the reader is unknown, or the base is not a canonical label (a
            legacy alias, a second reader or an unknown label), naming the label.
    """
    base, sep, reader = label.partition("@")
    if not sep:
        return label, None
    if reader not in READERS:
        raise ValueError(
            f"unknown reader in arm label {label!r}; known readers: {list(READERS)} "
            "(D-257)"
        )
    if base in _ALIAS or canonical_arm(base) != base:
        raise ValueError(
            f"arm label {label!r}: a reader suffix takes a canonical arm label, not a "
            "legacy alias (D-257)"
        )
    return base, reader


def arm_reader(label: str) -> str | None:
    """The reader a label's suffix names; None for a label without one.

    Raises:
        ValueError: If the label carries a bad reader suffix (``_split_reader``).
    """
    return _split_reader(label)[1]


def reader_base_arm(label: str) -> str:
    """The base arm a reader arm replays; the label itself when it names no reader.

    Raises:
        ValueError: If the label carries a bad reader suffix (``_split_reader``).
    """
    return _split_reader(label)[0]


def is_reader_arm(label: str) -> bool:
    """Whether a label names a reader arm (D-257); an unknown label is not one."""
    try:
        return _split_reader(label)[1] is not None
    except ValueError:
        return False


def _split_store(label: str) -> tuple[str | None, str]:
    """Splits a label into its store prefix (None when unprefixed) and its base label.

    Raises:
        ValueError: If the prefix is unknown or the base is not a registry row (a
            legacy alias, an external arm or an unknown label), naming the label.
    """
    prefix, sep, base = label.partition("/")
    if not sep:
        return None, label
    if prefix not in STORE_PREFIXES:
        raise ValueError(
            f"unknown store prefix in arm label {label!r}; known prefixes: "
            f"{sorted(STORE_PREFIXES)} (D-251)"
        )
    if base not in ARM_REGISTRY:
        raise ValueError(
            f"arm label {label!r}: a store prefix takes a registry label, not a legacy "
            "alias, an external arm or an unknown label (D-251)"
        )
    return prefix, base


def arm_store(label: str) -> str | None:
    """The eval store name a label's prefix declares; None for an unprefixed label.

    A reader arm runs on its base arm's store (D-257).

    Raises:
        ValueError: If the label carries a bad store prefix (``_split_store``) or a
            bad reader suffix (``_split_reader``).
    """
    prefix, _ = _split_store(_split_reader(label)[0])
    return None if prefix is None else STORE_PREFIXES[prefix]


@pydantic_dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class ExternalPipeline:
    """An external arm's retrieval pipeline, as pre-registered and as echoed (D-247).

    A stage's pre-registration fixes one per external arm (``preregistration.
    external_pipelines_of``), and every external record echoes the one it ran
    (``journal.ExternalProvenance``); the two must be equal. It is a stdlib dataclass
    validated by pydantic, so ``dataclasses.asdict`` of a pre-registration serialises
    it and a journal line parses it with unknown keys refused.

    Attributes:
        framework: The retrieval framework's package name (``llama-index-core``).
        framework_version: Its installed version.
        chunk_size: The splitter's chunk size, in the framework's own units.
        chunk_overlap: The splitter's overlap, in the same units.
        dense_top_k: Candidates the dense retriever returns.
        rerank_model: The rerank model the candidates are reordered by.
        keep: Evidence entries kept after the rerank (fairness rule 3: k = 8).
    """

    framework: Annotated[str, Field(min_length=1)]
    framework_version: Annotated[str, Field(min_length=1)]
    chunk_size: int
    chunk_overlap: int
    dense_top_k: int
    rerank_model: Annotated[str, Field(min_length=1)]
    keep: int


def canonical_arm(stored_label: str) -> str:
    """Resolves a stored label or alias to its canonical registry label.

    Lookup only: never write the result back to ``RunRecord.graph_arm``. A
    store-prefixed label keeps its prefix (D-251), and a reader arm its suffix (D-257).

    Args:
        stored_label: A canonical label or a legacy alias.

    Returns:
        The canonical label.

    Raises:
        ValueError: If the label is neither canonical nor an alias.
    """
    if _split_reader(stored_label)[1] is not None:
        return stored_label
    if _split_store(stored_label)[0] is not None:
        return stored_label
    if stored_label in ARM_REGISTRY or stored_label in EXTERNAL_ARMS:
        return stored_label
    if stored_label in _ALIAS:
        return _ALIAS[stored_label]
    raise ValueError(f"unknown arm label {stored_label!r}")


def resolve_arm(label: str) -> ArmSpec:
    """Returns the registry row for a canonical label or an alias.

    A store-prefixed label returns its base row (D-251), and so does a reader arm
    (D-257): a caller that reads a record's snapshot or notices checks
    ``is_reader_arm`` first.

    Args:
        label: A canonical label or a legacy alias.

    Returns:
        The matching ``ArmSpec``.

    Raises:
        ValueError: With the ``Unknown arm '...'. Expected one of:`` prefix, or from a
            bad reader suffix.
    """
    label = _split_reader(label)[0]
    prefix, base = _split_store(label)
    if prefix is not None:
        return ARM_REGISTRY[base]
    if label in ARM_REGISTRY:
        return ARM_REGISTRY[label]
    if label in EXTERNAL_ARMS:
        return EXTERNAL_ARMS[label]
    if label in _ALIAS:
        return ARM_REGISTRY[_ALIAS[label]]
    valid = [*ARM_REGISTRY, *EXTERNAL_ARMS, *_ALIAS]
    raise ValueError(f"Unknown arm {label!r}. Expected one of: {valid}")


def in_registry_order(labels: Iterable[str]) -> list[str]:
    """Canonical labels in report order: registry rows, then external arms, unprefixed
    first, then each store's prefixed arms in ``STORE_PREFIXES`` order (D-251). Each
    reader arm follows its base arm, readers in ``READERS`` order (D-257).

    Args:
        labels: Canonical labels (``canonical_arm`` output).

    Returns:
        The labels, sorted.
    """
    position = {label: i for i, label in enumerate((*ARM_REGISTRY, *EXTERNAL_ARMS))}
    stores = list(STORE_PREFIXES)

    def key(label: str) -> tuple[int, int, int]:
        arm, reader = _split_reader(label)
        prefix, base = _split_store(arm)
        return (
            0 if prefix is None else 1 + stores.index(prefix),
            position[base],
            0 if reader is None else 1 + READERS.index(reader),
        )

    return sorted(labels, key=key)


def judged_arms(labels: Iterable[str]) -> list[str]:
    """The labels the judged pass covers, in report order: every label but an external
    arm (D-247 arms are never judged) or a reader arm (D-257: its records carry no
    evidence of their own), store-prefixed ones included (D-251, #30).

    Args:
        labels: Canonical labels.

    Returns:
        The judged labels, in ``in_registry_order``.
    """
    return [
        a
        for a in in_registry_order(labels)
        if not is_external_arm(a) and not is_reader_arm(a)
    ]


def judged_report_arms(labels: Iterable[str]) -> list[str]:
    """The rows the judge stage and the per-arm agreement list.

    A corpus of the four 06.3.5 labels lists all four, as v1.0 did; any other corpus
    lists its ``judged_arms``.

    Args:
        labels: Canonical labels.

    Returns:
        The labels to list, in report order.
    """
    arms = set(labels)
    if arms <= set(LEGACY_ARM_LABELS):
        return list(LEGACY_ARM_LABELS)
    return judged_arms(arms)


def is_external_arm(label: str) -> bool:
    """Whether a label names an external arm (D-247); an unknown label is not one."""
    return label in EXTERNAL_ARMS


def is_legacy_label(label: str) -> bool:
    """Whether a label is one of the two read-only legacy aliases."""
    return label in _ALIAS


def arm_slug(label: str) -> str:
    """Filesystem-safe slug: the canonical label with ``+``, ``-``, ``/``, ``@`` and
    ``.`` as ``_`` (only a reader arm, D-257, carries the last two).

    Args:
        label: A canonical label or an alias.

    Returns:
        The slug of the canonical label.
    """
    slug = canonical_arm(label)
    for char in "+-/@.":
        slug = slug.replace(char, "_")
    return slug


def request_fields(label: str) -> dict[str, object]:
    """Returns the ``run_query`` keyword fields that make a request for an arm.

    The two legacy labels return exactly the bodies drives 1, 1b and 2 sent, so a
    legacy request stays byte-identical; they exist for re-scoring only and no live
    command sends them (06.4 D-198). A canonical label says exactly what it means
    (06.4 D-198, D-207): it names its retrieval mode, states its graph state with
    ``disable_graph_context`` (``False`` is sent too, because an absent field now means
    the engine's configured default), opts out of the configured default levers with
    ``disable_default_levers`` and asks for the pre-truncation ranking (D-100). A lever
    arm adds the ``levers`` it names (06.3.6 D-136), and no other arm sends the field.

    Args:
        label: A canonical label or an alias.

    Returns:
        Keyword fields for ``client.run_query``.

    Raises:
        ValueError: If the label is unknown, or names an external arm (D-247) or a
            reader arm (D-257), neither of which sends a gateway request.
    """
    if is_reader_arm(label):
        raise ValueError(
            f"arm {label!r} is a reader arm: it replays its base arm's context and "
            "sends no gateway request (D-257)"
        )
    spec = resolve_arm(label)
    if spec.kind == "external":
        raise ValueError(
            f"arm {label!r} is an external arm: it sends no gateway request (D-247)"
        )
    if is_legacy_label(label):
        return {"disable_graph_context": True} if spec.disable_graph_context else {}
    fields: dict[str, object] = {
        "retrieval_mode": spec.retrieval_mode,
        "disable_graph_context": spec.disable_graph_context,
        "disable_default_levers": True,
        "include_pre_truncation_ranking": True,
    }
    if spec.levers:
        fields["levers"] = list(spec.levers)
    return fields


def explicit_default_fields(label: str) -> dict[str, object]:
    """Returns only the two explicit fields for a legacy measurement or canary label.

    ``lancet-eval measure`` and the legacy preflight canaries keep the labels
    ``graph-off`` and ``graph-on`` as record labels, because they key the budget
    derivation and the committed canary rows. They are live requests, so they must not
    inherit the engine's configured defaults (06.4 D-198, D-207): the graph state is
    sent explicitly (``False`` included) and the configured default levers are opted
    out of. No retrieval mode or ranking field is added, which keeps the wire size and
    the measured latency semantics unchanged.

    Args:
        label: ``"graph-off"`` for the graph-off request; any other label is graph-on.

    Returns:
        Keyword fields for ``client.run_query``.
    """
    return {
        "disable_graph_context": label == "graph-off",
        "disable_default_levers": True,
    }


def echo_failures(label: str, retrieval_mode_echo: str | None) -> list[str]:
    """Checks that a record's snapshot echoes the retrieval mode the arm requested.

    A canonical label must see its own retrieval mode echoed in the snapshot. A legacy
    label is not checked, because legacy journals carry no mode echo. This is
    provenance clause (a); callers branch on this function, never on message text
    (D-158 IN-04).

    Args:
        label: The stored arm label (canonical or legacy alias).
        retrieval_mode_echo: ``RetrievalSnapshot.retrieval_mode`` of the record, if any.

    Returns:
        Failure strings that each name the label; empty when the echo holds.
    """
    spec = resolve_arm(label)
    if is_legacy_label(label) or retrieval_mode_echo == spec.retrieval_mode:
        return []
    return [
        f"arm {label!r}: expected retrieval_mode {spec.retrieval_mode!r} "
        f"echoed in the snapshot, observed {retrieval_mode_echo!r}"
    ]


def lever_echo_failures(label: str, levers_echo: Sequence[str] | None) -> list[str]:
    """Checks that a record's snapshot echoes exactly the levers the arm requested.

    The engine echoes the admitted levers in canonical order (D-136), and a registry
    row stores its levers in that same order, so the two lists must be equal: an arm
    without levers must see an empty echo, a lever arm its own levers and nothing more
    or less. A journal written before the field existed echoes none, which is exactly
    right for every arm that names no lever. This is provenance clause (h); callers
    branch on this function, never on message text (D-158 IN-04).

    Args:
        label: The stored arm label (canonical or legacy alias).
        levers_echo: ``RetrievalSnapshot.levers`` of the record, if any.

    Returns:
        Failure strings that each name the label; empty when the echo holds.
    """
    expected = list(resolve_arm(label).levers)
    observed = list(levers_echo or ())
    if observed == expected:
        return []
    return [
        f"arm {label!r}: expected levers {expected!r} echoed in the snapshot, "
        f"observed {observed!r}"
    ]


def ablation_failures(label: str, notices: Sequence[Notice]) -> list[str]:
    """Checks the graph notices of an arm against its graph switch.

    An arm that disables graph context must carry the GRAPH_ABLATION notice and not
    GRAPH_UNAVAILABLE. Legacy labels are held to this check too. An arm that leaves
    the graph on (the graph-on arms, 06.3.6 D-134) must not carry GRAPH_ABLATION.
    This is provenance clause (e).

    Args:
        label: The stored arm label (canonical or legacy alias).
        notices: The record's notices.

    Returns:
        Failure strings that each name the label; empty when the notices hold.
    """
    from lancet_eval.journal import RunRecord
    from lancet_eval.usability import carries_graph_ablation, has_arm_provenance

    spec = resolve_arm(label)
    record = RunRecord(
        corpus="",
        question_id="",
        graph_arm=label,
        outcome="success",
        notices=list(notices),
    )
    if not spec.disable_graph_context:
        if carries_graph_ablation(record):
            return [
                f"arm {label!r}: graph-on arm carries the GRAPH_ABLATION notice"
            ]
        return []
    if has_arm_provenance(record):
        return []
    return [
        f"arm {label!r}: graph-off arm lacks the GRAPH_ABLATION notice "
        "or carries GRAPH_UNAVAILABLE"
    ]


def _graph_counter_failures(meta: object | None) -> list[str]:
    """Names each non-zero graph counter of a workflow metadata record."""
    if meta is None:
        return []
    observed: list[str] = []
    for name in ("graph_node_count", "graph_edge_count", "graph_seed_count"):
        value = getattr(meta, name, None)
        if value:
            observed.append(f"{name}={value}")
    return observed


def explicit_field_failures(record: RunRecord, spec: ArmSpec) -> list[str]:
    """Checks that a live response proves the explicit request fields arrived.

    This is the per-arm echo check of 06.4 D-199 (and the code 24 consumer of review
    IN-04). It is NOT a provenance clause: it is called only where a live response
    exists, by the arm-mode canary check and the gate-stage first-record gate, and never
    by ``provenance.provenance_failures`` or ``score``. A new clause there would be
    evaluated on every record of the committed run journals, which could make ``score``
    refuse the runs of record (D-201). Callers branch on this function, never on
    message text (D-158 IN-04).

    * Any DEFAULT_LEVER_UNAVAILABLE notice (typed code 24) is a failure: with an
      explicit opt-out or named levers it can only appear if the field never reached
      the engine.
    * An arm with ``disable_graph_context`` True must carry GRAPH_ABLATION (18) and
      none of GRAPH_DISABLED_BY_CONFIG (25), GRAPH_UNAVAILABLE or a non-zero graph
      counter.
    * An arm with ``disable_graph_context`` False must show its graph node ran (a
      non-zero ``graph_node_count``, a ``graph_seed_count`` the engine reported, or a
      GRAPH_UNAVAILABLE, GRAPH_TIMEOUT or GRAPH_DEGRADED notice) and must carry neither
      18 nor 25. That last condition is what proves an explicit ``false`` reached the
      engine under a default-off configuration. The seed count is always on the
      gateway's wire when metadata exists, so the notices are the authoritative half.

    Notices are identified by ``typed_code``, falling back to ``code``.

    Args:
        record: A live response as a journal record (its notices and workflow
            metadata are read).
        spec: The registry row of the arm that made the request.

    Returns:
        Failure strings of the form ``arm 'X': expected ..., observed ...``; empty when
        every declared field is echoed.
    """
    from lancet_eval.dimensions import (
        NOTICE_CODE_DEFAULT_LEVER_UNAVAILABLE,
        NOTICE_CODE_GRAPH_ABLATION,
        NOTICE_CODE_GRAPH_DEGRADED,
        NOTICE_CODE_GRAPH_DISABLED_BY_CONFIG,
        NOTICE_CODE_GRAPH_TIMEOUT,
        NOTICE_CODE_GRAPH_UNAVAILABLE,
    )

    label = record.graph_arm

    def carries(number: int, name: str) -> bool:
        return any(n.typed_code == number or n.code == name for n in record.notices)

    meta = record.workflow_meta
    failures: list[str] = []
    if carries(NOTICE_CODE_DEFAULT_LEVER_UNAVAILABLE, "DEFAULT_LEVER_UNAVAILABLE"):
        failures.append(
            f"arm {label!r}: expected no DEFAULT_LEVER_UNAVAILABLE notice (code "
            f"{NOTICE_CODE_DEFAULT_LEVER_UNAVAILABLE}), observed one: the explicit "
            "lever fields did not reach the engine"
        )
    ablation = carries(NOTICE_CODE_GRAPH_ABLATION, "GRAPH_ABLATION")
    by_config = carries(
        NOTICE_CODE_GRAPH_DISABLED_BY_CONFIG, "GRAPH_DISABLED_BY_CONFIG"
    )
    unavailable = carries(NOTICE_CODE_GRAPH_UNAVAILABLE, "GRAPH_UNAVAILABLE")
    failed_open = (
        unavailable
        or carries(NOTICE_CODE_GRAPH_TIMEOUT, "GRAPH_TIMEOUT")
        or carries(NOTICE_CODE_GRAPH_DEGRADED, "GRAPH_DEGRADED")
    )
    if spec.disable_graph_context:
        if not ablation:
            failures.append(
                f"arm {label!r}: expected GRAPH_ABLATION (18) on an arm that sends "
                "disable_graph_context=true, observed none"
            )
        if by_config:
            failures.append(
                f"arm {label!r}: expected no GRAPH_DISABLED_BY_CONFIG (25) on an arm "
                "that sends disable_graph_context=true, observed one"
            )
        if unavailable:
            failures.append(
                f"arm {label!r}: expected no GRAPH_UNAVAILABLE (10) on a graph-off "
                "arm, observed one"
            )
        counters = _graph_counter_failures(meta)
        if counters:
            failures.append(
                f"arm {label!r}: expected zero graph counters on a graph-off arm, "
                f"observed {', '.join(counters)}"
            )
        return failures
    if ablation:
        failures.append(
            f"arm {label!r}: expected no GRAPH_ABLATION (18) on an arm that sends "
            "disable_graph_context=false, observed one"
        )
    if by_config:
        failures.append(
            f"arm {label!r}: expected no GRAPH_DISABLED_BY_CONFIG (25) on an arm "
            "that sends disable_graph_context=false, observed one: the explicit "
            "false did not reach the engine"
        )
    ran = failed_open or (
        meta is not None
        and (meta.graph_node_count > 0 or meta.graph_seed_count is not None)
    )
    if not ran:
        failures.append(
            f"arm {label!r}: expected evidence that the graph node ran (a graph "
            "node count, a graph seed count or a graph failure notice), observed none"
        )
    return failures


def mode_provenance_failures(
    label: str,
    snapshot_mode: str | None,
    notices: Sequence[Notice],
) -> list[str]:
    """Checks that a record's echo and notices match the arm that was requested.

    A thin composition of ``echo_failures`` and ``ablation_failures``, kept for the
    callers that want both lists in one call. The lever echo is its own clause (h),
    ``lever_echo_failures``, and is not part of this composition.

    Args:
        label: The stored arm label (canonical or legacy alias).
        snapshot_mode: ``RetrievalSnapshot.retrieval_mode`` of the record, if any.
        notices: The record's notices.

    Returns:
        Failure strings that each name the label; empty when provenance holds.
    """
    return echo_failures(label, snapshot_mode) + ablation_failures(label, notices)


def plan_work_units(
    questions: Sequence[GoldQuestion],
    arms: Sequence[str],
    order_seed: int,
) -> list[tuple[GoldQuestion, str]]:
    """Plans the D-107 seeded, balanced arm rotation over a question set.

    The questions are sorted by ID and shuffled with ``random.Random(order_seed)``.
    The per-question offsets ``i % len(arms)`` are then shuffled with the same
    stream, and each question's arm list is rotated by its offset. Every arm of a
    question therefore runs back to back, and over N questions each arm is first,
    and holds each later position, ``N // len(arms)`` or one more times. The function
    is pure, so ``--resume`` rebuilds the identical order.

    Args:
        questions: The questions to drive, in any order.
        arms: The arm labels, in registry order.
        order_seed: Seed of the rotation, recorded in the journal header.

    Returns:
        The ``(question, arm)`` work units, question-major in rotated order.
    """
    arm_list = list(arms)
    ordered = sorted(questions, key=lambda q: q.question_id)
    rng = random.Random(order_seed)
    rng.shuffle(ordered)
    offsets = [i % len(arm_list) for i in range(len(ordered))]
    rng.shuffle(offsets)
    units: list[tuple[GoldQuestion, str]] = []
    for question, offset in zip(ordered, offsets, strict=True):
        for arm in arm_list[offset:] + arm_list[:offset]:
            units.append((question, arm))
    return units
