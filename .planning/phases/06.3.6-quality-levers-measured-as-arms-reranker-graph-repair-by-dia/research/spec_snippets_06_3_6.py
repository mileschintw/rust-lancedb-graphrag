"""Spec-time snippets for 06.3.6-AI-SPEC.md section 4b (and the arithmetic quoted in section 4).

Run (offline, no network, no paid call, never touches data/lancedb-eval):

    uv run --project eval python .planning/phases/06.3.6-.../research/spec_snippets_06_3_6.py

Everything here is PROPOSED code. It imports nothing from `lancet_eval`, because the phase
adds these names and none exists yet. The snippets are the ones quoted in the AI-SPEC; the
spec records this file's output. If the AI-SPEC and this file disagree, this file wins.
"""

from __future__ import annotations

import json
import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# ---------------------------------------------------------------------------------------
# 1. ArmSpec with `levers` (D-136, D-149). PROPOSED extension of eval/src/lancet_eval/arms.py.
# ---------------------------------------------------------------------------------------

LeverName = Literal["rerank", "graph_v2", "evidence_metadata", "binary_answer_format"]
# Canonical order = ascending proto enum number (PROPOSED LEVER_RERANK = 1 ... = 4). One tuple,
# so a name sort and a number sort cannot diverge. A test must parse the .proto and assert it.
LEVER_ORDER: tuple[LeverName, ...] = (
    "rerank",
    "graph_v2",
    "evidence_metadata",
    "binary_answer_format",
)
RetrievalMode = Literal["dense_only", "bm25_only", "hybrid"]
ArmLabel = Literal[
    "dense-only",
    "bm25-only",
    "hybrid",
    "hybrid+graph",
    "hybrid+rerank",
    "hybrid+graph-v2",
    "hybrid+metadata",
    "hybrid+answer-format",
    "hybrid+all",
]


class ArmSpec(BaseModel):
    """One D-101 registry row, extended with the D-136 `levers` request field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: ArmLabel
    retrieval_mode: RetrievalMode
    disable_graph_context: bool
    levers: tuple[LeverName, ...] = ()
    legacy_aliases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _levers_are_canonical(self) -> ArmSpec:
        if len(set(self.levers)) != len(self.levers):
            raise ValueError(f"duplicate lever in {self.levers!r}")
        if tuple(sorted(self.levers, key=LEVER_ORDER.index)) != self.levers:
            raise ValueError(f"levers must be in canonical order {LEVER_ORDER!r}")
        if "graph_v2" in self.levers and self.disable_graph_context:
            raise ValueError("graph_v2 with the graph switched off would be a silent no-op")
        return self


def request_levers(spec: ArmSpec) -> list[str] | None:
    """The `levers` body key, or None so a lever-free request stays byte-identical."""
    return list(spec.levers) if spec.levers else None


def lever_echo_failure(spec: ArmSpec, echoed: list[str]) -> str | None:
    """Provenance clause (h): the snapshot's echo must equal the arm's lever set, exactly."""
    if echoed != list(spec.levers):
        return f"arm {spec.label!r}: expected levers {list(spec.levers)!r}, echoed {echoed!r}"
    return None


# ---------------------------------------------------------------------------------------
# 2. The OpenRouter rerank 200 body, as the engine must read it (D-131, D-134).
#    Source of the shape: research/fetched/openrouter-submit-a-rerank-request-2026-10-09.md.
#    The OpenAPI schema requires only `model` and `results`; `usage.cost` is optional.
# ---------------------------------------------------------------------------------------


class RerankItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: Annotated[int, Field(ge=0)]
    relevance_score: float


class RerankUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cost: float | None = None
    total_tokens: int | None = None
    search_units: int | None = None


class RerankResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    results: list[RerankItem]
    usage: RerankUsage | None = None

    def order_for(self, n_documents: int, requested_model: str) -> list[int]:
        """The candidate order, or raises: a full permutation of range(n), else fail closed."""
        indices = [item.index for item in self.results]
        if sorted(indices) != list(range(n_documents)):
            raise ValueError(
                f"results are not a permutation of 0..{n_documents - 1}: {indices!r}"
            )
        if not self.model.startswith(requested_model.split("-20")[0]):
            raise ValueError(f"response model {self.model!r} != requested {requested_model!r}")
        if any(not math.isfinite(item.relevance_score) for item in self.results):
            raise ValueError("non-finite relevance_score")
        # Our own tie-break, so the order does not depend on the unspecified order of `results`.
        ranked = sorted(self.results, key=lambda item: (-item.relevance_score, item.index))
        return [item.index for item in ranked]


# ---------------------------------------------------------------------------------------
# 3. The rerank timeout against retrieve_timeout_ms (D-135, verified-facts A5/A6).
# ---------------------------------------------------------------------------------------

MULTIPLIER = 1.5  # 06.3.3 committed rule, BUDGETS.md:5
SLACK_MS = 500  # NESTING_SLACK_MS, engine/src/config.rs:1069
RETRIEVE_MS = 2500  # config/config.toml:72
SEARCH_RULE_MS = 294  # config/config.toml:63 "retrieve 2500 (rule 294)"
SEARCH_DEV_P95_MS = 166.15  # drive 2 report.json retrieve_latency_ms.retrieve_p95_ms (dev)


def rerank_timeout_ms(p95_rerank_ms: float) -> int:
    """ceil(p95 x 1.5 + 0), the committed rule with allowance 0."""
    return math.ceil(p95_rerank_ms * MULTIPLIER)


def required_retrieve_ms(search_ms: float, timeout_ms: int) -> int:
    """Smallest retrieve_timeout_ms that nests search + rerank with the committed slack."""
    return math.ceil(search_ms + timeout_ms + SLACK_MS)


def max_p95_that_fits(search_ms: float, retrieve_ms: int = RETRIEVE_MS) -> int:
    """Largest integer p95_rerank for which ceil(1.5 x p95) still nests."""
    p = math.floor((retrieve_ms - search_ms - SLACK_MS) / MULTIPLIER)
    while rerank_timeout_ms(p + 1) + search_ms + SLACK_MS <= retrieve_ms:
        p += 1
    while rerank_timeout_ms(p) + search_ms + SLACK_MS > retrieve_ms:
        p -= 1
    return p


# D-152: one retry on a query-embedding timeout, nested in graph_node_timeout_ms.
QUERY_EMBEDDING_MS = 2000
GRAPH_OPERATION_MS = 2424
GRAPH_NODE_MS = 12500


def graph_node_required_ms(jitter_max_ms: int, attempts: int = 2) -> int:
    return attempts * QUERY_EMBEDDING_MS + jitter_max_ms * (attempts - 1) + GRAPH_OPERATION_MS + SLACK_MS


# ---------------------------------------------------------------------------------------
# 4. A cross-language pin: the lever names and numbers in the .proto equal LEVER_ORDER.
# ---------------------------------------------------------------------------------------

PROPOSED_PROTO = """
enum Lever {
  LEVER_UNSPECIFIED = 0;
  LEVER_RERANK = 1;
  LEVER_GRAPH_V2 = 2;
  LEVER_EVIDENCE_METADATA = 3;
  LEVER_BINARY_ANSWER_FORMAT = 4;
}
"""


def proto_lever_order(proto_text: str) -> tuple[str, ...]:
    body = re.search(r"enum\s+Lever\s*\{(.*?)\}", proto_text, re.S)
    assert body is not None, "no `enum Lever` in the proto"
    pairs = re.findall(r"LEVER_([A-Z0-9_]+)\s*=\s*(\d+)\s*;", body.group(1))
    named = [(int(num), name.lower()) for name, num in pairs if name != "UNSPECIFIED"]
    return tuple(name for _, name in sorted(named))


# ---------------------------------------------------------------------------------------
# 5. The D-137 selection rule as a pure function of the four class counts.
# ---------------------------------------------------------------------------------------

DiagnosisClass = Literal["absent", "alias_split", "missing_edge", "other"]
Lever2 = Literal["entity_resolution", "graph_list_precision", "none"]
_BRANCH: dict[str, Lever2] = {
    "alias_split": "entity_resolution",
    "missing_edge": "graph_list_precision",
    "other": "graph_list_precision",
    "absent": "none",
}


def select_lever2(counts: dict[DiagnosisClass, int]) -> Lever2:
    """D-137: a strict plurality picks its branch; any tie, or a missing-edge/other plurality,
    picks graph-list precision. Only a strict plurality of `absent` or `alias_split` moves off it."""
    if set(counts) != set(_BRANCH) or any(v < 0 for v in counts.values()):
        raise ValueError(f"need exactly the four classes with counts >= 0, got {counts!r}")
    top = max(counts.values())
    leaders = [name for name, v in counts.items() if v == top]
    if len(leaders) != 1:
        return "graph_list_precision"
    return _BRANCH[leaders[0]]


# ---------------------------------------------------------------------------------------
# 6. PREREGISTRATION_06_3_6 shape (D-150, D-148, D-151, D-160): per-family arm sets, and the
#    D-73 AST gate's blind spot for a constant that sits outside the pre-registered block.
#    NO VALUES are proposed here: every number is a placeholder (None / 0.0).
# ---------------------------------------------------------------------------------------

from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True)
class FamilySpec:
    primary: str
    role: Literal["decisional", "supporting"]
    arms: tuple[str, ...]
    alpha: float


@dataclass(frozen=True)
class LeverPreRegistration:
    reference_arm: str
    families: tuple[FamilySpec, ...]
    descriptive_arms: tuple[str, ...]
    population: Literal["complete_case_reference_plus_decisional", "pairwise_per_comparison"]
    complete_case_floor: float | None  # D-160, set by the owner before the freeze commit
    null_abstention_margin: float | None  # D-148 guard 1, set by the owner
    sc2_error_mode_floor: float | None  # D-151, set by the owner

    def m(self, primary: str) -> int:
        return len(next(f for f in self.families if f.primary == primary).arms)


def pre_for(graph_v2_built: bool) -> LeverPreRegistration:
    lever_arms = ("hybrid+rerank", "hybrid+metadata", "hybrid+answer-format")
    if graph_v2_built:
        lever_arms = ("hybrid+rerank", "hybrid+graph-v2", "hybrid+metadata", "hybrid+answer-format")
    hits_arms = tuple(a for a in ("hybrid+rerank", "hybrid+graph-v2") if a in lever_arms)
    return LeverPreRegistration(
        reference_arm="hybrid",
        families=(
            FamilySpec("answer_usable", "decisional", lever_arms, 0.05),
            FamilySpec("paper_hits_at_4", "supporting", hits_arms, 0.05),
        ),
        descriptive_arms=("hybrid+all", "hybrid+graph"),
        population="pairwise_per_comparison",
        complete_case_floor=None,
        null_abstention_margin=None,
        sc2_error_mode_floor=None,
    )


# ---------------------------------------------------------------------------------------
# 7. Order-of-magnitude spend (D-154 caps are the planner's; rerank price is NOT a constant).
# ---------------------------------------------------------------------------------------


def main() -> None:
    # 1. ArmSpec ------------------------------------------------------------------------
    rerank = ArmSpec(
        label="hybrid+rerank", retrieval_mode="hybrid", disable_graph_context=True,
        levers=("rerank",),
    )
    allarm = ArmSpec(
        label="hybrid+all", retrieval_mode="hybrid", disable_graph_context=False,
        levers=("rerank", "graph_v2", "evidence_metadata", "binary_answer_format"),
    )
    ref = ArmSpec(label="hybrid", retrieval_mode="hybrid", disable_graph_context=True)
    assert request_levers(ref) is None and request_levers(rerank) == ["rerank"]
    assert lever_echo_failure(rerank, ["rerank"]) is None
    assert lever_echo_failure(rerank, []) is not None  # a lever arm whose echo is empty fails
    assert lever_echo_failure(ref, []) is None  # a pre-06.3.6 journal passes for lever-free arms
    for bad in (
        dict(levers=("metadata_typo",)),
        dict(levers=("rerank", "rerank")),
        dict(levers=("evidence_metadata", "rerank")),
        dict(levers=("graph_v2",), disable_graph_context=True),
    ):
        kwargs = dict(label="hybrid+all", retrieval_mode="hybrid", disable_graph_context=False)
        kwargs.update(bad)
        try:
            ArmSpec(**kwargs)
        except (ValidationError, ValueError):
            pass
        else:
            raise AssertionError(f"accepted {bad}")
    print("ArmSpec: valid rows accepted; unknown, duplicate, unsorted and graph_v2+graph-off rejected")
    print("  hybrid+all levers:", allarm.levers)

    # 2. Rerank response ----------------------------------------------------------------
    # OpenAPI example, extended to 3 documents. (Not a live response: no authenticated call.)
    ok = RerankResponse.model_validate({
        "id": "gen-rerank-example",
        "model": "voyageai/rerank-2.5-lite",
        "results": [
            {"index": 2, "relevance_score": 0.91, "document": {"text": "c"}},
            {"index": 0, "relevance_score": 0.40, "document": {"text": "a"}},
            {"index": 1, "relevance_score": 0.10, "document": {"text": "b"}},
        ],
        "usage": {"cost": 0.0000004, "total_tokens": 150},
    })
    assert ok.order_for(3, "voyageai/rerank-2.5-lite") == [2, 0, 1]
    assert ok.usage is not None and ok.usage.cost == 0.0000004
    no_usage = RerankResponse.model_validate({
        "model": "voyageai/rerank-2.5-lite-20260727",
        "results": [{"index": 0, "relevance_score": 0.5, "document": {"text": "a"}}],
    })
    assert no_usage.usage is None  # usage.cost may be absent: the spend line must say "unknown"
    assert no_usage.order_for(1, "voyageai/rerank-2.5-lite") == [0]
    tied = RerankResponse.model_validate({"model": "voyageai/rerank-2.5-lite", "results": [
        {"index": 1, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.5},
        {"index": 2, "relevance_score": 0.9}]})
    assert tied.order_for(3, "voyageai/rerank-2.5-lite") == [2, 0, 1]  # best first; ties by index; API order ignored
    for label, body in {
        "missing index": [{"index": 0, "relevance_score": 1.0}, {"index": 2, "relevance_score": 0.5}],
        "duplicate index": [{"index": 0, "relevance_score": 1.0}, {"index": 0, "relevance_score": 0.5},
                            {"index": 1, "relevance_score": 0.1}],
        "out of range": [{"index": 0, "relevance_score": 1.0}, {"index": 1, "relevance_score": 0.5},
                         {"index": 3, "relevance_score": 0.1}],
        "short list": [{"index": 0, "relevance_score": 1.0}],
    }.items():
        resp = RerankResponse.model_validate({"model": "voyageai/rerank-2.5-lite", "results": body})
        try:
            resp.order_for(3, "voyageai/rerank-2.5-lite")
        except ValueError:
            continue
        raise AssertionError(f"accepted a malformed rerank body: {label}")
    try:
        RerankResponse.model_validate({"model": "m", "results": [{"index": "x", "relevance_score": 1}]})
    except ValidationError:
        pass
    else:
        raise AssertionError("accepted a non-integer index")
    print("RerankResponse: permutation accepted; missing/duplicate/out-of-range/short rejected; usage optional")

    # 3. Timeout arithmetic -------------------------------------------------------------
    print(f"rerank room in RetrieveHybrid, rule value S={SEARCH_RULE_MS}: "
          f"{RETRIEVE_MS - SEARCH_RULE_MS - SLACK_MS} ms")
    print(f"rerank room, drive-2 dev p95 S={SEARCH_DEV_P95_MS}: "
          f"{RETRIEVE_MS - SEARCH_DEV_P95_MS - SLACK_MS:.2f} ms")
    for s in (SEARCH_RULE_MS, SEARCH_DEV_P95_MS):
        print(f"  S={s}: largest p95_rerank whose ceil(1.5 x p95) nests in 2500 = {max_p95_that_fits(s)} ms")
    print("  HYPOTHETICAL p95_rerank (not measurements) -> timeout -> required retrieve_timeout_ms:")
    for p95 in (200, 600, 1000, 1137, 1138, 1500, 2500):
        t = rerank_timeout_ms(p95)
        need = required_retrieve_ms(SEARCH_RULE_MS, t)
        print(f"    p95={p95:>5}  timeout={t:>5}  required retrieve={need:>5}  "
              f"{'fits' if need <= RETRIEVE_MS else 'DOES NOT FIT: ceiling moves for every arm'}")
    assert max_p95_that_fits(SEARCH_RULE_MS) == 1137 and rerank_timeout_ms(1137) == 1706
    print(f"D-152: graph_node needs {graph_node_required_ms(250)} ms with 250 ms jitter "
          f"(2 x {QUERY_EMBEDDING_MS} + 250 + {GRAPH_OPERATION_MS} + {SLACK_MS}); "
          f"config has {GRAPH_NODE_MS}; spare {GRAPH_NODE_MS - graph_node_required_ms(250)} ms")
    assert graph_node_required_ms(250, attempts=1) == 4924  # config.rs:299-302 "nesting now needs only 4924"

    # 4. Proto pin ----------------------------------------------------------------------
    assert proto_lever_order(PROPOSED_PROTO) == LEVER_ORDER, proto_lever_order(PROPOSED_PROTO)
    print("proto pin: enum Lever order equals LEVER_ORDER:", proto_lever_order(PROPOSED_PROTO))

    # 5. The D-137 rule, over SYNTHETIC counts (these are not the dev table: it is unknown) --
    cases = {
        "alias plurality": ({"absent": 5, "alias_split": 20, "missing_edge": 8, "other": 5}, "entity_resolution"),
        "absent plurality": ({"absent": 20, "alias_split": 8, "missing_edge": 5, "other": 5}, "none"),
        "edge plurality": ({"absent": 5, "alias_split": 8, "missing_edge": 20, "other": 5}, "graph_list_precision"),
        "other plurality": ({"absent": 5, "alias_split": 8, "missing_edge": 5, "other": 20}, "graph_list_precision"),
        "tie alias/absent": ({"absent": 14, "alias_split": 14, "missing_edge": 5, "other": 5}, "graph_list_precision"),
        "tie alias/edge": ({"absent": 5, "alias_split": 14, "missing_edge": 14, "other": 5}, "graph_list_precision"),
        "four-way tie": ({"absent": 9, "alias_split": 9, "missing_edge": 9, "other": 9}, "graph_list_precision"),
    }
    for name, (counts, want) in cases.items():
        got = select_lever2(counts)  # type: ignore[arg-type]
        assert got == want, (name, got, want)
    try:
        select_lever2({"absent": 1, "alias_split": 1, "missing_edge": 1})  # type: ignore[typeddict-item]
    except ValueError:
        pass
    else:
        raise AssertionError("accepted a table with a missing class")
    print(f"D-137 rule: {len(cases)} synthetic cases pass, incl. three tie shapes; a 3-class table is refused")

    # 6. Pre-registration shape and the D-73 AST gate ------------------------------------
    with_v2, without_v2 = pre_for(True), pre_for(False)
    assert (with_v2.m("answer_usable"), with_v2.m("paper_hits_at_4")) == (4, 2)
    assert (without_v2.m("answer_usable"), without_v2.m("paper_hits_at_4")) == (3, 1)
    from lancet_eval.gitcheck import _assigned_value  # the real D-73 comparison (gitcheck.py:195)

    token = "PREREGISTRATION_06_3_6"
    committed = f"{token} = LeverPreRegistration(null_abstention_margin=0.05)\nLOOSE_MARGIN = 0.05\n"
    inside = committed.replace("margin=0.05", "margin=0.10")
    outside = committed.replace("LOOSE_MARGIN = 0.05", "LOOSE_MARGIN = 0.10")
    assert _assigned_value(committed, token) != _assigned_value(inside, token)  # caught
    assert _assigned_value(committed, token) == _assigned_value(outside, token)  # NOT caught
    print("pre-registration: m = (4, 2) with graph-v2, (3, 1) without; a number inside the block is "
          "caught by the D-73 AST gate, a loose constant beside it is not")

    # 7. Spend order of magnitude -------------------------------------------------------
    per_record = 0.00036  # drive 2 per generation record, as 06.3.5-AI-SPEC section 4b quotes it
    drive_records = 7 * 351
    print(f"held-out drive: {drive_records} records x ${per_record} = ${drive_records * per_record:.2f} generation")
    dev_records = 4 * 2 * 2 * 100  # <= 4 levers x 2 reads x (lever + reference) x 100 dev questions
    print(f"dev reads upper bound: {dev_records} records x ${per_record} = ${dev_records * per_record:.2f}")
    chunk_tokens, query_tokens, n_docs = 500, 40, 32  # ASSUMPTIONS, not measured
    billed = n_docs * query_tokens + n_docs * chunk_tokens
    for price in (0.02,):  # Voyage-direct list price, NOT verified through OpenRouter
        print(f"rerank, if billed like Voyage direct: {billed} tokens/query x ${price}/1M = "
              f"${billed * price / 1e6:.5f}/query; {2 * 351} held-out calls = ${2 * 351 * billed * price / 1e6:.3f}")
    print(json.dumps({"snippets": "ok"}))


if __name__ == "__main__":
    main()
