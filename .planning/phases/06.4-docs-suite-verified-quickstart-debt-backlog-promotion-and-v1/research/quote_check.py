"""Never-re-derive check for the Phase 6.4 docs (D-214, D-228, D-210).

Usage (from the repo root)::

    uv run --project eval python <phase>/research/quote_check.py --doc docs/evaluation.md \
        --allow <phase>/research/quote_check_allow.txt --source <file> [--source <file> ...] \
        [--roadmap .planning/ROADMAP.md]

Every decimal number in the doc's prose and tables must occur, as a whole token, in the
concatenated raw text of the ``--source`` files. A number is a run of digits, a decimal
point and digits, with an optional exponent (``2.36163e-09`` is one token) and an
optional leading sign or unicode minus. It must not touch a word character or a dot before
it, a word character after it, or a dot followed by a digit after it, so a dotted version
such as ``1.2.3`` is not a number while a sentence-final ``0.0812.`` is.

Skipped, and nothing else: fenced code blocks, inline code spans, Markdown link targets,
autolinks, HTML comments, the README quickstart block between ``<!-- quickstart:start -->``
and ``<!-- quickstart:end -->``, backlog phase IDs (``999.N``), real phase IDs inside a
phase run ("Phase 6.4", "Phases 6.1 to 6.3"; real means a ``### Phase <id>:`` heading in
``--roadmap``, compared with any leading zero of the first component dropped), and the
literal phrases of the ``--allow`` file (``<phrase>  # <reason>`` per line).

A leading ``+`` is dropped and a unicode minus becomes ``-``, in the doc and the sources
alike, and an unsigned number never matches a negative source value (a flipped sign fails).
The check is a whole-token search, so a short figure can still be matched by an unrelated
occurrence of the same token in a large source file; quoting at the source's own precision
keeps that rare. Every file is read as UTF-8 whatever the locale, and everything printed is ASCII.
Exit 0 when every number is sourced, 1 with one ``line <n>: unsourced <token>`` line per
unsourced number, 2 on a usage or input error.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

UNICODE_MINUS = "\u2212"

# A thousands-grouped integer part (``1,032.5``) is part of the number, so the token is
# ``1,032.5``, never its tail ``032.5``.
NUMBER = re.compile(
    r"(?<![\w.])[-+\u2212]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d+(?:[eE][+-]?\d+)?(?!\w)(?!\.\d)"
)
BACKLOG_ID = re.compile(r"999\.\d+")
PHASE_ID = r"\d+(?:\.\d+)*"
PHASE_SEP = r"(?:\s*[-\u2013/,&]\s*|\s+(?:and|to)\s+)+"
PHASE_RUN = re.compile(
    rf"\bphases?\s+{PHASE_ID}(?:{PHASE_SEP}{PHASE_ID})*", re.IGNORECASE
)
PHASE_ID_IN_RUN = re.compile(rf"(?<![\w.]){PHASE_ID}(?![\w])(?!\.\d)")
ROADMAP_HEADING = re.compile(r"^### Phase (\d+(?:\.\d+)*):", re.MULTILINE)

QUICKSTART_BLOCK = re.compile(
    r"<!-- quickstart:start -->.*?<!-- quickstart:end -->", re.DOTALL
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+)(?!`).*?(?<!`)\1(?!`)", re.DOTALL)
LINK_TARGET = re.compile(r"\]\([^)\n]*\)")
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]\n]+\]:[^\n]*$", re.MULTILINE)
AUTOLINK = re.compile(r"<(?:https?|file|mailto):[^>\s]*>")


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _read(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        return handle.read()


def _blank(match: re.Match[str]) -> str:
    """Spaces in place of the match, keeping its newlines so line numbers hold."""
    return "".join("\n" if ch == "\n" else " " for ch in match.group(0))


def _blank_fences(text: str) -> str:
    out: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        opener = FENCE_OPEN.match(line)
        if fence is None and opener:
            fence = opener.group(1)
            out.append(_blank_line(line))
            continue
        if fence is not None:
            closer = FENCE_OPEN.match(line)
            if closer and closer.group(1)[0] == fence[0] and len(closer.group(1)) >= len(fence) \
                    and line.strip() == closer.group(1):
                fence = None
            out.append(_blank_line(line))
            continue
        out.append(line)
    return "".join(out)


def _blank_line(line: str) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in line)


def normalise(text: str) -> str:
    return text.replace(UNICODE_MINUS, "-")


def roadmap_phase_ids(roadmap_text: str) -> set[str]:
    return {_phase_key(m.group(1)) for m in ROADMAP_HEADING.finditer(roadmap_text)}


def _phase_key(identifier: str) -> str:
    first, _, rest = identifier.partition(".")
    key = str(int(first))
    return f"{key}.{rest}" if rest else key


def load_allow(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for number, raw in enumerate(_read(path).splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        phrase, sep, reason = raw.partition("  #")
        if not sep or not phrase.strip() or not reason.strip():
            raise ValueError(
                f"{_ascii(str(path))}:{number}: expected '<phrase>  # <reason>'"
            )
        entries.append((phrase.strip(), reason.strip()))
    return entries


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?<!\d\.){re.escape(phrase)}(?!\w)(?!\.\d)")


def prepare(doc: str, allow: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """The doc with every skipped region blanked, and the allow phrases that matched nothing."""
    text = QUICKSTART_BLOCK.sub(_blank, doc)
    text = HTML_COMMENT.sub(_blank, text)
    text = _blank_fences(text)
    text = INLINE_CODE.sub(_blank, text)
    text = LINK_TARGET.sub(lambda m: "]" + _blank_line(m.group(0)[1:]), text)
    text = REFERENCE_LINK.sub(_blank, text)
    text = AUTOLINK.sub(_blank, text)
    text = normalise(text)
    unmatched: list[str] = []
    for phrase, _reason in allow:
        pattern = _phrase_pattern(normalise(phrase))
        text, count = pattern.subn(_blank, text)
        if count == 0:
            unmatched.append(phrase)
    return text, unmatched


def exempt_spans(text: str, phase_ids: set[str]) -> set[tuple[int, int]]:
    """Spans of real phase IDs inside phase runs; only those spans are skipped."""
    spans: set[tuple[int, int]] = set()
    for run in PHASE_RUN.finditer(text):
        for ident in PHASE_ID_IN_RUN.finditer(run.group(0)):
            if _phase_key(ident.group(0)) in phase_ids:
                start = run.start() + ident.start()
                spans.add((start, start + len(ident.group(0))))
    return spans


def doc_tokens(text: str, phase_ids: set[str]) -> list[tuple[int, str]]:
    """(line, token) for every checked number, in document order."""
    exempt = exempt_spans(text, phase_ids)
    found: list[tuple[int, str]] = []
    for match in NUMBER.finditer(text):
        if match.span() in exempt:
            continue
        token = match.group(0)
        if token.startswith("+"):
            token = token[1:]
        if BACKLOG_ID.fullmatch(token):
            continue
        line = text.count("\n", 0, match.start()) + 1
        found.append((line, token))
    return found


def is_sourced(token: str, sources: str, cache: dict[str, bool]) -> bool:
    """Whole-token search. An unsigned token must not match a negative source value, so a
    dropped or flipped sign is caught as well as a re-rounded figure."""
    if token not in cache:
        before = r"(?<![\w.])" if token.startswith("-") else r"(?<![\w.\-])"
        pattern = re.compile(rf"{before}{re.escape(token)}(?!\w)(?!\.\d)")
        cache[token] = pattern.search(sources) is not None
    return cache[token]


def check(doc: str, sources: str, allow: list[tuple[str, str]], phase_ids: set[str]) -> tuple[list[tuple[int, str]], list[str]]:
    text, unmatched = prepare(doc, allow)
    cache: dict[str, bool] = {}
    unsourced = [(line, token) for line, token in doc_tokens(text, phase_ids)
                 if not is_sourced(token, sources, cache)]
    return unsourced, unmatched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail on any doc decimal not quoted from a cited source.")
    parser.add_argument("--doc", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--allow", type=Path)
    parser.add_argument("--roadmap", type=Path, default=Path(".planning/ROADMAP.md"))
    args = parser.parse_args(argv)
    try:
        doc = _read(args.doc)
        sources = normalise("\n".join(_read(path) for path in args.source))
        allow = load_allow(args.allow) if args.allow else []
        phase_ids = roadmap_phase_ids(_read(args.roadmap))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"quote_check: {_ascii(str(error))}")
        return 2
    unsourced, unmatched = check(doc, sources, allow, phase_ids)
    for phrase in unmatched:
        print(f"note: allow phrase matched nothing: {_ascii(phrase)}")
    for line, token in unsourced:
        print(f"line {line}: unsourced {_ascii(token)}")
    if unsourced:
        print(f"{len(unsourced)} unsourced number(s) in {_ascii(str(args.doc))}")
        return 1
    print(f"ok: every decimal number in {_ascii(str(args.doc))} is quoted from a cited source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
