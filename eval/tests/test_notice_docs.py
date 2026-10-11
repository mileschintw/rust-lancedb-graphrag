"""SC-5 drift test: `docs/api-contract.md` against the proto and `derive_degraded_mode`.

06-CONTEXT D-76 and ROADMAP 6.4 SC-5 (amended by 06.4 D-226) publish the notice-code vocabulary
and the request fields as API contract. These tests keep the published tables in step with
`proto/lancet/v1/lancet.proto` and with the three arms of `derive_degraded_mode` in
`engine/src/workflow/mod.rs`, so neither a new proto value nor a moved match arm can land
without the doc changing too.
"""

from __future__ import annotations

import re

from lancet_eval.config import repo_root

_ROOT = repo_root()
_PROTO = _ROOT / "proto" / "lancet" / "v1" / "lancet.proto"
_WORKFLOW = _ROOT / "engine" / "src" / "workflow" / "mod.rs"
_DOC = _ROOT / "docs" / "api-contract.md"

_UNSPECIFIED = "NOTICE_CODE_UNSPECIFIED"
_DEGRADED_CLASSES = ("yes", "no", "conditional")
_ANSWER_BASIS_FRAGMENT = "whenever `answer_basis` is not `retrieval`"


def _read(path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _proto_enum(name: str) -> list[tuple[str, int]]:
    """The `(NAME, number)` members of one proto enum, in declaration order.

    Copied from `test_wire_contract.py` rather than imported across test modules.
    """
    text = _read(_PROTO)
    block = re.search(rf"enum {name} \{{(.*?)\n\}}", text, re.DOTALL)
    assert block is not None, f"enum {name} not found in {_PROTO}"
    return [
        (m.group(1), int(m.group(2)))
        for m in re.finditer(
            r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(\d+);", block.group(1), re.MULTILINE
        )
    ]


def _proto_message_fields(name: str) -> set[str]:
    """The field names declared directly in one proto message body."""
    text = _read(_PROTO)
    block = re.search(rf"message {name} \{{(.*?)\n\}}", text, re.DOTALL)
    assert block is not None, f"message {name} not found in {_PROTO}"
    return {
        m.group(1)
        for m in re.finditer(
            r"^\s*(?:optional\s+|repeated\s+)?[A-Za-z_][\w.]*\s+([a-z_][a-z0-9_]*)\s*=\s*\d+;",
            block.group(1),
            re.MULTILINE,
        )
    }


def _norm(name: str) -> str:
    """One spelling for a proto name and its prost CamelCase variant."""
    return name.removeprefix("NOTICE_CODE_").replace("_", "").lower()


def _doc_text() -> str:
    assert _DOC.is_file(), f"{_DOC} is missing: SC-5 needs the notice and request-field contract"
    return _read(_DOC)


def _doc_notice_rows() -> list[tuple[str, int, str]]:
    """`(NAME, number, degraded_mode)` for every notice-table row in the doc."""
    rows = [
        (m.group(1), int(m.group(2)), m.group(3).strip())
        for m in re.finditer(
            r"^\|\s*`?(NOTICE_CODE_[A-Z0-9_]+)`?\s*\|\s*(\d+)\s*\|[^|\n]*\|([^|\n]*)\|",
            _doc_text(),
            re.MULTILINE,
        )
    ]
    assert rows, "docs/api-contract.md holds no notice-code table rows"
    return rows


def _doc_request_fields() -> list[str]:
    """The first-column field names of the doc's request-field table."""
    text = _doc_text()
    section = re.search(r"^## Request fields\n(.*?)(?=^## )", text, re.DOTALL | re.MULTILINE)
    assert section is not None, "docs/api-contract.md has no '## Request fields' section"
    table = re.search(r"^\| field \|.*?\n((?:\|.*\n)+)", section.group(1), re.MULTILINE)
    assert table is not None, "the request-field table must start with a '| field |' header"
    names = [
        m.group(1)
        for m in re.finditer(r"^\|\s*`([a-z_][a-z0-9_]*)`\s*\|", table.group(1), re.MULTILINE)
    ]
    assert names, "the request-field table lists no fields"
    return names


def _engine_degraded_classes() -> dict[str, set[str]]:
    """The three arms of `derive_degraded_mode`, keyed `yes` / `no` / `conditional`.

    The match on the notice code is sliced from `match code {` inside the function to the
    function's closing `false`. Splitting on `=>` leaves arm k's codes in piece k and its body at
    the start of piece k+1: `return true` is the unconditional arm, `{}` the excluded arm, and any
    other `{` block a conditional arm.
    """
    text = _read(_WORKFLOW)
    start = text.find("pub fn derive_degraded_mode")
    assert start != -1, "derive_degraded_mode not found in engine/src/workflow/mod.rs"
    body = text[start:]
    match_at = body.find("match code {")
    assert match_at != -1, "derive_degraded_mode no longer matches on `code`"
    end = body.find("\n    false\n}", match_at)
    assert end != -1, "the end of derive_degraded_mode was not found"
    pieces = body[match_at + len("match code {") : end].split("=>")
    classes: dict[str, set[str]] = {k: set() for k in _DEGRADED_CLASSES}
    for codes_piece, arm_body in zip(pieces, pieces[1:]):
        codes = re.findall(r"NoticeCode::([A-Z]\w*)", codes_piece)
        assert codes, f"an arm of derive_degraded_mode names no NoticeCode: {codes_piece!r}"
        head = arm_body.lstrip()
        if head.startswith("return true"):
            kind = "yes"
        elif re.match(r"\{\s*\}", head):
            kind = "no"
        elif head.startswith("{"):
            kind = "conditional"
        else:
            raise AssertionError(f"unrecognised arm body in derive_degraded_mode: {head[:60]!r}")
        classes[kind].update(_norm(c) for c in codes)
    for members in classes.values():
        members.discard(_norm(_UNSPECIFIED))
    return classes


_BASIS_EARLY_RETURN = re.compile(
    r"if\s+answer_basis\s*!=\s*AnswerBasis::Retrieval\s*\{\s*return\s+true;\s*\}"
)


def _has_basis_early_return(text: str) -> bool:
    """Whether `derive_degraded_mode` still returns true for a non-retrieval basis before its
    notice match. The doc's `_ANSWER_BASIS_FRAGMENT` sentence states this early return; the
    match-arm slice in `_engine_degraded_classes` starts after it and never sees it.
    """
    start = text.find("pub fn derive_degraded_mode")
    assert start != -1, "derive_degraded_mode not found in engine/src/workflow/mod.rs"
    body = text[start:]
    match_at = body.find("match code {")
    assert match_at != -1, "derive_degraded_mode no longer matches on `code`"
    return _BASIS_EARLY_RETURN.search(body[:match_at]) is not None


def test_d76_notice_table_matches_the_proto_enum() -> None:
    proto = {(n, v) for n, v in _proto_enum("NoticeCode") if n != _UNSPECIFIED}
    rows = _doc_notice_rows()
    doc = [(n, v) for n, v, _ in rows]
    assert len(doc) == len(set(doc)), "a notice code appears twice in the doc's table"
    assert set(doc) == proto, (
        f"missing from the doc: {sorted(proto - set(doc))}; "
        f"not in the proto: {sorted(set(doc) - proto)}"
    )
    assert [v for _, v in doc] == sorted(v for _, v in doc), "the table must be in number order"
    assert ("NOTICE_CODE_DEFAULT_LEVER_UNAVAILABLE", 24) in doc
    assert ("NOTICE_CODE_GRAPH_DISABLED_BY_CONFIG", 25) in doc


def test_d76_degraded_mode_column_matches_derive_degraded_mode() -> None:
    rows = _doc_notice_rows()
    for name, _, cell in rows:
        assert cell in _DEGRADED_CLASSES, f"{name}: degraded_mode cell {cell!r} is not yes/no/conditional"
    doc = {k: {_norm(n) for n, _, c in rows if c == k} for k in _DEGRADED_CLASSES}
    engine = _engine_degraded_classes()
    for kind in _DEGRADED_CLASSES:
        assert doc[kind] == engine[kind], (
            f"degraded_mode '{kind}': doc-only {sorted(doc[kind] - engine[kind])}, "
            f"engine-only {sorted(engine[kind] - doc[kind])}"
        )
    assert not (engine["yes"] & engine["no"])
    assert not (engine["yes"] & engine["conditional"])
    assert not (engine["no"] & engine["conditional"])
    proto = {_norm(n) for n, _ in _proto_enum("NoticeCode") if n != _UNSPECIFIED}
    assert engine["yes"] | engine["no"] | engine["conditional"] == proto
    assert engine["conditional"] == {_norm("NOTICE_CODE_BASIS_RECONCILED")}
    assert _norm("NOTICE_CODE_GRAPH_DISABLED_BY_CONFIG") in engine["no"]
    assert _norm("NOTICE_CODE_GRAPH_ABLATION") in engine["no"]
    assert _has_basis_early_return(_read(_WORKFLOW)), (
        "derive_degraded_mode lost its answer_basis early return, which the doc states"
    )
    assert _ANSWER_BASIS_FRAGMENT in _doc_text()


def test_d76_basis_early_return_check_fails_a_deleted_or_inverted_guard() -> None:
    """The early-return check has teeth, on in-memory copies of the engine source only."""
    text = _read(_WORKFLOW)
    assert _has_basis_early_return(text)
    guard = _BASIS_EARLY_RETURN.search(text, text.find("pub fn derive_degraded_mode"))
    assert guard is not None
    deleted = text[: guard.start()] + text[guard.end() :]
    inverted = text[: guard.start()] + guard.group(0).replace("!=", "==") + text[guard.end() :]
    assert not _has_basis_early_return(deleted)
    assert not _has_basis_early_return(inverted)


def test_d76_reserved_and_unused_values_are_stated() -> None:
    text = _doc_text()
    proto_text = _read(_PROTO)
    assert re.search(r"^\s*reserved 17;", proto_text, re.MULTILINE), "the proto no longer reserves 17"
    assert "17 is reserved." in text
    assert "6-9 are unused and not reserved." in text
    numbers = {v for _, v in _proto_enum("NoticeCode")}
    assert not numbers & {6, 7, 8, 9, 17}, "a value the doc calls unused or reserved is now declared"


def test_d198_d207_request_field_table_names_exist_in_the_proto() -> None:
    proto = _proto_message_fields("QueryRAGRequest")
    names = _doc_request_fields()
    assert len(names) == len(set(names)), "a request field appears twice in the doc's table"
    assert set(names) <= proto, f"not in QueryRAGRequest: {sorted(set(names) - proto)}"
    assert set(names) == proto, f"QueryRAGRequest fields the doc omits: {sorted(proto - set(names))}"
    for field in ("disable_default_levers", "disable_graph_context", "levers"):
        assert field in names
