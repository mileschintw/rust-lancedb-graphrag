"""D-137 graph-repair diagnosis: class predicates, selection rule, 38-question table.

The pre-registered rule is the constant `thresholds.GRAPH_REPAIR_RULE_06_3_6`; this
module is the code that applies it. Every predicate here is parameter-free (D-167): the
only comparison of two names is token containment of their normalised forms, and the
first-match order of the four classes is the rule's `precedence` (D-171).

Each of the 38 `GRAPH_UNAVAILABLE` dev questions gets exactly one label (the first
class, in precedence order, whose predicate holds; `other` is the residual) and the full
set of classes whose predicate holds (the multi-membership matrix). The table is a
regenerated artifact, never hand-edited, and `table` refuses to write unless the D-73
ordering gate passes, so the rule's commit provably precedes the table.

Everything is read-only: the journal, the seed probe, the gold-chunk probe, the question
file and the graph dump (`inspect_lancedb --graph-dump` on a store copy) are only read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lancet_eval import gitcheck
from lancet_eval.arms import canonical_arm
from lancet_eval.config import repo_root
from lancet_eval.diagnostic import _load_gold_chunks_by_question, _normalize_name
from lancet_eval.journal import RunRecord, load_records
from lancet_eval.thresholds import GRAPH_REPAIR_RULE_06_3_6, GraphRepairRule
from lancet_eval.usability import NOTICE_CODE_GRAPH_UNAVAILABLE

DiagnosisClass = Literal["absent", "alias_split", "missing_edge", "other"]
Lever2 = Literal["entity_resolution", "graph_list_precision", "none"]

RULE_TOKEN = "GRAPH_REPAIR_RULE_06_3_6"
MODULE_PATH = "eval/src/lancet_eval/graph_diagnosis.py"
TABLE_FIELDS = (
    "question_id",
    "question_text",
    "mentions",
    "label",
    "memberships",
    "evidence_ids",
)
SPOT_CHECK_PER_CLASS = 2
BIAS_DISCLOSURE = (
    "D-167 bias disclosure: the `alias_split` predicate is parameter-free "
    "(normalised-name token containment with the same entity_type, no similarity "
    "threshold), so it can under-detect vector-only aliases. That biases the plurality "
    "against selecting entity resolution. The entity-resolution arm itself may still "
    "use vectors (D-138)."
)

EMPTY_GOLD_DISCLOSURE = (
    "D-187 disclosure: a population question with no gold-chunk row and an empty "
    "`evidence_list` in the questions file (a `null_query` question) has the empty "
    "gold set, the literal reading of the rule's \"the gold chunk ids of the "
    'question". For those questions `alias_split` cannot hold (it needs an entity '
    'citing a gold chunk) and `absent` reduces to "some mention has no '
    'token-matching entity", which can tilt the plurality toward `absent` and so '
    "toward `none`."
)
MATRIX_DIAGONAL_NOTE = (
    "The three non-residual predicates are pairwise disjoint as pre-registered "
    "(plan 06.3.6-02 SUMMARY): `alias_split` needs an entity citing a gold chunk and "
    "`absent` needs none; `missing_edge` requires `alias_split` false and every "
    "mention seeded, which makes some entity name each mention and so `absent` "
    "false. The D-171 precedence therefore never changes a label and this matrix is "
    "diagonal by construction."
)

_BRANCH: dict[str, Lever2] = {
    "alias_split": "entity_resolution",
    "missing_edge": "graph_list_precision",
    "other": "graph_list_precision",
    "absent": "none",
}


class GraphDiagnosisError(ValueError):
    """Raised when an input of the diagnosis table breaks a precondition of the rule."""


def select_lever2(counts: Mapping[str, int]) -> Lever2:
    """Applies the D-137 plurality rule to the four class counts.

    A strict plurality picks its branch; any tie, or a `missing_edge` or `other`
    plurality, picks graph-list precision. Only a strict plurality of `absent` or
    `alias_split` moves off it.

    Args:
        counts: Exactly the four classes, each with a count of at least zero.

    Returns:
        The selected lever-2 branch.

    Raises:
        ValueError: If a class is missing or extra, or a count is negative.
    """
    if set(counts) != set(_BRANCH) or any(v < 0 for v in counts.values()):
        raise ValueError(
            f"need exactly the four classes with counts >= 0, got {dict(counts)!r}"
        )
    top = max(counts.values())
    leaders = [name for name, v in counts.items() if v == top]
    if len(leaders) != 1:
        return "graph_list_precision"
    return _BRANCH[leaders[0]]


def normalize_tokens(name: str) -> tuple[str, ...]:
    """Splits a name into the tokens of the engine's `normalize_name`.

    Reuses `diagnostic._normalize_name` (the Python twin of
    `graph::index::normalize_name`): lower-case, runs of non-alphanumerics (including
    `_`) are separators, a leading "the" is dropped when more words remain.

    Args:
        name: An entity name or a question mention.

    Returns:
        The normalised tokens in order; empty when the name has no alphanumerics.
    """
    return tuple(_normalize_name(name).split())


def tokens_contained(a: Iterable[str], b: Iterable[str]) -> bool:
    """Whether one token set is a subset of the other (token, not substring).

    Both sets must be non-empty. "disney" is contained in "walt disney company";
    "disney" is not contained in "disneyland".

    Args:
        a: Tokens of the first name.
        b: Tokens of the second name.

    Returns:
        True when `set(a) <= set(b)` or `set(b) <= set(a)` with both non-empty.
    """
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return False
    return sa <= sb or sb <= sa


@dataclass(frozen=True)
class DumpEntity:
    """One row of the v1 `entities` dump (no vectors)."""

    entity_id: str
    name: str
    entity_type: str
    source_chunk_ids: tuple[str, ...]


class GraphDump:
    """The v1 entity and edge tables as read from an `inspect_lancedb --graph-dump`."""

    def __init__(
        self,
        entities: Iterable[DumpEntity],
        edges: Iterable[tuple[str, str]],
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        """Indexes entities by id, by cited chunk and by edge endpoint.

        Args:
            entities: The dumped entity rows.
            edges: `(source_node_id, target_node_id)` of every dumped edge.
            meta: The dump's `dump_meta.json`, kept for the table header.
        """
        self.meta: Mapping[str, Any] = dict(meta or {})
        self.entities: dict[str, DumpEntity] = {}
        self.tokens: dict[str, tuple[str, ...]] = {}
        self.by_chunk: dict[str, set[str]] = {}
        for ent in entities:
            self.entities[ent.entity_id] = ent
            self.tokens[ent.entity_id] = normalize_tokens(ent.name)
            for chunk_id in ent.source_chunk_ids:
                self.by_chunk.setdefault(chunk_id, set()).add(ent.entity_id)
        self.neighbours: dict[str, set[str]] = {}
        for src, dst in edges:
            self.neighbours.setdefault(src, set()).add(dst)
            self.neighbours.setdefault(dst, set()).add(src)

    @classmethod
    def from_dir(cls, directory: Path | str) -> GraphDump:
        """Reads a dump directory and verifies it against its `dump_meta.json`.

        Args:
            directory: Holds `entities.jsonl`, `entity_edges.jsonl`, `dump_meta.json`.

        Returns:
            The indexed dump.

        Raises:
            GraphDiagnosisError: If a file is missing or its sha256 or row count
                differs from the meta.
        """
        root = Path(directory)
        try:
            meta = json.loads((root / "dump_meta.json").read_text(encoding="utf-8"))
            ent_rows = _read_jsonl(root / "entities.jsonl")
            edge_rows = _read_jsonl(root / "entity_edges.jsonl")
        except OSError as exc:
            raise GraphDiagnosisError(f"graph dump unreadable: {exc}") from exc
        for fname, rows in (("entities", ent_rows), ("entity_edges", edge_rows)):
            want = meta.get("sha256", {}).get(f"{fname}.jsonl")
            got = sha256_file(root / f"{fname}.jsonl")
            if want != got:
                raise GraphDiagnosisError(
                    f"{fname}.jsonl sha256 {got} differs from dump_meta.json {want}"
                )
            if meta.get("row_counts", {}).get(fname) != len(rows):
                raise GraphDiagnosisError(
                    f"{fname}.jsonl has {len(rows)} rows, dump_meta.json says "
                    f"{meta.get('row_counts', {}).get(fname)}"
                )
        entities = (
            DumpEntity(
                entity_id=r["entity_id"],
                name=r["name"],
                entity_type=r["entity_type"],
                source_chunk_ids=tuple(r["source_chunk_ids"]),
            )
            for r in ent_rows
        )
        edges = ((r["source_node_id"], r["target_node_id"]) for r in edge_rows)
        return cls(entities, edges, meta)

    def citing(self, chunk_ids: Iterable[str]) -> set[str]:
        """Ids of the entities whose `source_chunk_ids` intersect `chunk_ids`."""
        found: set[str] = set()
        for chunk_id in chunk_ids:
            found |= self.by_chunk.get(chunk_id, set())
        return found

    def names_any(self, tokens: Sequence[str]) -> bool:
        """Whether any entity's name tokens are contained in or contain `tokens`."""
        return any(tokens_contained(t, tokens) for t in self.tokens.values())


@dataclass(frozen=True)
class SeedInfo:
    """One seed of the seed probe: the entity and its name."""

    entity_id: str
    name: str


@dataclass(frozen=True)
class QuestionEvidence:
    """Everything the class predicates read about one question.

    Attributes:
        question_id: The question id.
        mentions: The probe's extracted mentions.
        seeds: The probe's seeds.
        paths: Per probe path, the set of entity ids on it.
        gold_chunk_ids: The question's gold chunk ids.
        path_found: The journal's `graph_path_found` (None when not recorded).
        degree_capped_count: The journal's `graph_degree_capped_count`.
    """

    question_id: str
    mentions: tuple[str, ...]
    seeds: tuple[SeedInfo, ...]
    paths: tuple[frozenset[str], ...]
    gold_chunk_ids: frozenset[str]
    path_found: bool | None
    degree_capped_count: int | None


def _usable_mentions(q: QuestionEvidence) -> list[tuple[str, tuple[str, ...]]]:
    out = []
    for mention in q.mentions:
        toks = normalize_tokens(mention)
        if toks:
            out.append((mention, toks))
    return out


def _seed_tokens(q: QuestionEvidence) -> dict[str, tuple[str, ...]]:
    return {s.entity_id: normalize_tokens(s.name) for s in q.seeds}


def _unseeded_mentions(q: QuestionEvidence) -> list[tuple[str, tuple[str, ...]]]:
    """Mentions that no seed's name tokens are contained in or contain."""
    seed_toks = list(_seed_tokens(q).values())
    return [
        (m, toks)
        for m, toks in _usable_mentions(q)
        if not any(tokens_contained(toks, st) for st in seed_toks)
    ]


def _connected(q: QuestionEvidence, a: str, b: str) -> bool:
    return any(a in path and b in path for path in q.paths)


def alias_split_witnesses(q: QuestionEvidence, dump: GraphDump) -> list[str]:
    """Entity ids that make `alias_split` hold for `q` (empty when it does not).

    Pair case: seeds a and b with no probe path through both, and an entity E (not a,
    not b) that cites a gold chunk, has the same `entity_type` as a, whose name tokens
    are contained in or contain a's, and which has an edge to b. Mention case: a
    mention no seed names, and an entity E that cites a gold chunk, whose name tokens
    are contained in or contain the mention's, with an edge to some seed.

    Args:
        q: The question's evidence.
        dump: The v1 graph dump.

    Returns:
        Sorted unique ids of the witnessing entities E.

    Raises:
        GraphDiagnosisError: If a seed's entity id is not in the dump.
    """
    gold_citing = dump.citing(q.gold_chunk_ids)
    seed_toks = _seed_tokens(q)
    seed_ids = list(dict.fromkeys(s.entity_id for s in q.seeds))
    for sid in seed_ids:
        if sid not in dump.entities:
            raise GraphDiagnosisError(
                f"seed entity {sid} of {q.question_id} not in dump"
            )
    witnesses: set[str] = set()
    for a in seed_ids:
        for b in seed_ids:
            if a == b or _connected(q, a, b):
                continue
            a_type = dump.entities[a].entity_type
            for eid in gold_citing:
                if eid in (a, b) or b not in dump.neighbours.get(eid, ()):
                    continue
                if dump.entities[eid].entity_type != a_type:
                    continue
                if tokens_contained(dump.tokens[eid], seed_toks[a]):
                    witnesses.add(eid)
    seeds = set(seed_ids)
    for _mention, toks in _unseeded_mentions(q):
        for eid in gold_citing:
            if not tokens_contained(dump.tokens[eid], toks):
                continue
            if dump.neighbours.get(eid, set()) & seeds:
                witnesses.add(eid)
    return sorted(witnesses)


def is_alias_split(q: QuestionEvidence, dump: GraphDump) -> bool:
    """Whether the `alias_split` predicate holds for `q`."""
    return bool(alias_split_witnesses(q, dump))


def is_absent(q: QuestionEvidence, dump: GraphDump) -> bool:
    """Whether the `absent` predicate holds for `q`.

    Some mention has no entity anywhere whose name tokens are contained in or contain
    the mention's, and no entity's `source_chunk_ids` intersects the gold chunks.
    """
    if dump.citing(q.gold_chunk_ids):
        return False
    return any(not dump.names_any(toks) for _m, toks in _usable_mentions(q))


def is_missing_edge(q: QuestionEvidence, dump: GraphDump) -> bool:
    """Whether the `missing_edge` predicate holds for `q`.

    At least two seeds, every mention seeded, `alias_split` false, `path_found` false
    and `degree_capped_count == 0`. A journal field that was not recorded (None) does
    not satisfy the predicate.
    """
    if len({s.entity_id for s in q.seeds}) < 2 or _unseeded_mentions(q):
        return False
    if q.path_found is not False or q.degree_capped_count != 0:
        return False
    return not is_alias_split(q, dump)


def memberships(
    q: QuestionEvidence, dump: GraphDump, rule: GraphRepairRule | None = None
) -> tuple[str, ...]:
    """Every class whose predicate holds for `q`, in the rule's precedence order.

    `other` is the residual: it is a member exactly when no other predicate holds.

    Args:
        q: The question's evidence.
        dump: The v1 graph dump.
        rule: The rule whose precedence orders the result; the committed one if None.

    Returns:
        The member classes; never empty.
    """
    rule = rule or GRAPH_REPAIR_RULE_06_3_6
    holds = {
        "alias_split": is_alias_split(q, dump),
        "absent": is_absent(q, dump),
        "missing_edge": is_missing_edge(q, dump),
    }
    holds["other"] = not any(holds.values())
    return tuple(cls for cls in rule.precedence if holds[cls])


def classify_question(
    q: QuestionEvidence, dump: GraphDump, rule: GraphRepairRule | None = None
) -> DiagnosisClass:
    """First-match class of `q` in the rule's precedence (D-171).

    Args:
        q: The question's evidence.
        dump: The v1 graph dump.
        rule: The rule; the committed one if None.

    Returns:
        The first member class in precedence order.
    """
    return memberships(q, dump, rule)[0]  # type: ignore[return-value]


def sha256_file(path: Path | str) -> str:
    """Hex sha256 of a file's bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def population(journal_path: Path | str) -> dict[str, RunRecord]:
    """The D-137 population: graph-on records with GRAPH_UNAVAILABLE (typed code 10).

    Args:
        journal_path: The drive-2 journal.

    Returns:
        The records by question id.

    Raises:
        GraphDiagnosisError: If one question has two such records.
    """
    found: dict[str, RunRecord] = {}
    for rec in load_records(journal_path):
        try:
            is_graph_on = canonical_arm(rec.graph_arm) == "hybrid+graph"
        except ValueError:
            continue
        if not is_graph_on:
            continue
        if not any(n.typed_code == NOTICE_CODE_GRAPH_UNAVAILABLE for n in rec.notices):
            continue
        if rec.question_id in found:
            raise GraphDiagnosisError(f"duplicate population record {rec.question_id}")
        found[rec.question_id] = rec
    return found


def load_questions(path: Path | str) -> dict[str, str]:
    """Reads `question_id -> query` from a question JSONL; nothing else is kept."""
    return {r["question_id"]: r["query"] for r in _read_jsonl(Path(path))}


def load_empty_evidence_ids(path: Path | str) -> frozenset[str]:
    """Question ids whose `evidence_list` is empty; nothing else of a row is kept."""
    return frozenset(
        r["question_id"] for r in _read_jsonl(Path(path)) if not r.get("evidence_list")
    )


def _evidence_for(
    record: RunRecord,
    probe_row: Mapping[str, Any],
    gold_chunk_ids: Iterable[str],
) -> QuestionEvidence:
    meta = record.workflow_meta
    return QuestionEvidence(
        question_id=record.question_id,
        mentions=tuple(probe_row.get("mentions", ())),
        seeds=tuple(
            SeedInfo(entity_id=s["entity_id"], name=s["name"])
            for s in probe_row.get("seeds", ())
        ),
        paths=tuple(frozenset(p["entities"]) for p in probe_row.get("paths", ())),
        gold_chunk_ids=frozenset(gold_chunk_ids),
        path_found=None if meta is None else meta.graph_path_found,
        degree_capped_count=None if meta is None else meta.graph_degree_capped_count,
    )


def diagnose_row(
    q: QuestionEvidence, dump: GraphDump, question_text: str
) -> dict[str, Any]:
    """One table row: exactly the `TABLE_FIELDS`, nothing else from the question."""
    members = memberships(q, dump)
    return {
        "question_id": q.question_id,
        "question_text": question_text,
        "mentions": list(q.mentions),
        "label": members[0],
        "memberships": list(members),
        "evidence_ids": {
            "gold_chunk_ids": sorted(q.gold_chunk_ids),
            "seed_entity_ids": list(dict.fromkeys(s.entity_id for s in q.seeds)),
            "alias_entity_ids": alias_split_witnesses(q, dump),
        },
    }


def class_counts(
    rows: Iterable[Mapping[str, Any]], rule: GraphRepairRule | None = None
) -> dict[str, int]:
    """Single-label counts with every class present (zero when absent)."""
    rule = rule or GRAPH_REPAIR_RULE_06_3_6
    counts = dict.fromkeys(rule.classes, 0)
    for row in rows:
        counts[row["label"]] += 1
    return counts


def membership_matrix(
    rows: Sequence[Mapping[str, Any]], rule: GraphRepairRule | None = None
) -> tuple[dict[tuple[str, ...], int], dict[tuple[str, str], int]]:
    """The multi-membership matrix: per distinct membership set, and per class pair.

    Returns:
        The count of questions per exact membership set, and the count of questions in
        both classes of each (row class, column class) pair (the diagonal is the number
        of questions that hold the class at all).
    """
    rule = rule or GRAPH_REPAIR_RULE_06_3_6
    by_set: dict[tuple[str, ...], int] = {}
    pair = {(a, b): 0 for a in rule.classes for b in rule.classes}
    for row in rows:
        members = tuple(row["memberships"])
        by_set[members] = by_set.get(members, 0) + 1
        for a in members:
            for b in members:
                pair[(a, b)] += 1
    return by_set, pair


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _render_table_md(
    rows: Sequence[Mapping[str, Any]],
    *,
    header: Mapping[str, Any],
    rule: GraphRepairRule,
) -> str:
    counts = class_counts(rows, rule)
    by_set, pair = membership_matrix(rows, rule)
    empty_gold = sorted(header["empty_gold_ids"])
    non_empty = [r for r in rows if r["question_id"] not in set(empty_gold)]
    non_empty_counts = class_counts(non_empty, rule)
    lines = [
        "# Graph diagnosis table (D-137)",
        "",
        "Regenerated by `python -m lancet_eval.graph_diagnosis table`, never "
        "hand-edited.",
        "",
        "## Header",
        "",
        f"- rule_sha: {header['rule_sha']}",
        f"- graph_diagnosis.py last commit: {header['module_commit']}",
        f"- precedence (D-171): {' > '.join(rule.precedence)}",
        f"- questions: {len(rows)}",
        "- input sha256:",
    ]
    for name, digest in header["input_sha256"].items():
        lines.append(f"  - {name}: {digest}")
    meta = header["dump_meta"]
    lines += [
        f"- dump entities_version: {meta.get('entities_version')}",
        f"- dump entity_edges_version: {meta.get('entity_edges_version')}",
        f"- dump row_counts: {json.dumps(meta.get('row_counts'), sort_keys=True)}",
        "",
        f"> {BIAS_DISCLOSURE}",
        "",
        f"> {EMPTY_GOLD_DISCLOSURE}",
        "",
        f"- empty-gold questions (D-187), {len(empty_gold)}: "
        + (", ".join(empty_gold) if empty_gold else "none"),
        "",
        "## Single-label counts (first match in precedence order)",
        "",
        "| class | count |",
        "|---|---|",
    ]
    lines += [f"| {cls} | {counts[cls]} |" for cls in rule.classes]
    lines += [
        "",
        f"Descriptive only: single-label counts over the {len(non_empty)} questions "
        f"with a non-empty gold set (excluding the {len(empty_gold)} empty-gold "
        "questions), beside the counts over all "
        f"{len(rows)} above: "
        + ", ".join(f"{cls} {non_empty_counts[cls]}" for cls in rule.classes)
        + f". The selection follows the pre-registered plurality over all {len(rows)}.",
    ]
    lines += ["", "## Multi-membership matrix", "", "By exact membership set:", ""]
    lines += ["| memberships | questions |", "|---|---|"]
    for members, n in sorted(by_set.items()):
        lines.append(f"| {' + '.join(members)} | {n} |")
    lines += ["", MATRIX_DIAGONAL_NOTE]
    lines += ["", "Pairwise overlap (diagonal: questions holding the class):", ""]
    lines.append("| | " + " | ".join(rule.classes) + " |")
    lines.append("|---|" + "---|" * len(rule.classes))
    for a in rule.classes:
        cells = " | ".join(str(pair[(a, b)]) for b in rule.classes)
        lines.append(f"| {a} | {cells} |")
    lines.append("")
    return "\n".join(lines)


def build_table(
    *,
    journal: Path,
    seed_probe: Path,
    gold_chunks: Path,
    questions: Path,
    graph_dump: Path,
    out_dir: Path,
    expected_count: int | None = None,
    repo: Path | None = None,
) -> dict[str, int]:
    """Writes `graph_diagnosis.jsonl` and `graph_diagnosis.md` after the D-73 gate.

    The gate runs first: no row is written unless the commit introducing the rule is an
    ancestor of HEAD, the rule is unchanged since, and the source tree is clean.

    Args:
        journal: The drive-2 journal.
        seed_probe: The 06.3.4.1 seed probe JSONL.
        gold_chunks: The gold-chunk probe JSONL.
        questions: The dev question JSONL (`question_id`, `query`).
        graph_dump: The `inspect_lancedb --graph-dump` directory.
        out_dir: Where the two files are written.
        expected_count: The required population size; the rule's when None.
        repo: Repository the gate queries; the live one when None.

    Returns:
        The single-label class counts.

    Raises:
        GraphDiagnosisError: On any gate problem or violated precondition.
    """
    rule = GRAPH_REPAIR_RULE_06_3_6
    want = rule.expected_count if expected_count is None else expected_count
    problems = gitcheck.preregistration_problems(
        (RULE_TOKEN,),
        unchanged_since_introduction=True,
        require_clean_tree=True,
        repo=repo,
    )
    if problems:
        raise GraphDiagnosisError("D-73 gate refused: " + "; ".join(problems))
    pop = population(journal)
    if len(pop) != want:
        raise GraphDiagnosisError(
            f"population is {len(pop)} questions, the rule requires exactly {want}"
        )
    question_text = load_questions(questions)
    missing = sorted(q for q in pop if q not in question_text)
    if missing:
        raise GraphDiagnosisError(f"questions file lacks population ids: {missing}")
    probe = {r["question_id"]: r for r in _read_jsonl(seed_probe) if "question_id" in r}
    gold = _load_gold_chunks_by_question(gold_chunks)
    empty_evidence = load_empty_evidence_ids(questions)
    empty_gold_ids: list[str] = []
    for qid in sorted(pop):
        if qid not in probe:
            raise GraphDiagnosisError(f"seed probe has no row for {qid}")
        if qid not in gold:
            # D-187: no gold row AND an empty evidence_list is the empty gold set; a
            # missing row for a question with evidence still refuses.
            if qid not in empty_evidence:
                raise GraphDiagnosisError(f"gold chunks have no row for {qid}")
            gold[qid] = []
            empty_gold_ids.append(qid)
    dump = GraphDump.from_dir(graph_dump)
    for qid in pop:
        for seed in probe[qid].get("seeds", ()):
            if seed["entity_id"] not in dump.entities:
                raise GraphDiagnosisError(
                    f"seed entity {seed['entity_id']} of {qid} is not in the graph dump"
                )
    rows = []
    for qid in sorted(pop):
        chunk_ids = [c for rec in gold[qid] for c in rec.get("chunk_ids", ())]
        evidence = _evidence_for(pop[qid], probe[qid], chunk_ids)
        rows.append(diagnose_row(evidence, dump, question_text[qid]))
    rule_sha = gitcheck.introducing_commit(
        RULE_TOKEN, gitcheck.THRESHOLDS_PATH, repo=repo
    )
    header = {
        "rule_sha": rule_sha,
        "module_commit": gitcheck.last_commit_touching(MODULE_PATH, repo=repo),
        "input_sha256": {
            "journal": sha256_file(journal),
            "seed_probe": sha256_file(seed_probe),
            "gold_chunks": sha256_file(gold_chunks),
            "questions": sha256_file(questions),
            "entities.jsonl": sha256_file(graph_dump / "entities.jsonl"),
            "entity_edges.jsonl": sha256_file(graph_dump / "entity_edges.jsonl"),
            "dump_meta.json": sha256_file(graph_dump / "dump_meta.json"),
        },
        "dump_meta": dump.meta,
        "empty_gold_ids": empty_gold_ids,
    }
    out = Path(out_dir)
    _write_text(
        out / "graph_diagnosis.jsonl",
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
    )
    _write_text(
        out / "graph_diagnosis.md", _render_table_md(rows, header=header, rule=rule)
    )
    return class_counts(rows, rule)


def read_table(path: Path | str) -> list[dict[str, Any]]:
    """Reads the committed table rows and checks each carries exactly `TABLE_FIELDS`."""
    rows = _read_jsonl(Path(path))
    for row in rows:
        if set(row) != set(TABLE_FIELDS):
            raise GraphDiagnosisError(
                f"table row {row.get('question_id')} has keys {sorted(row)}"
            )
    return rows


def spot_check_sample(
    table: Path | str, out: Path | str, *, seed: int = 42
) -> list[str]:
    """Writes the owner spot-check sample, reading only the table.

    Two rows per class (all of a class with fewer than two), drawn with one seeded
    stream over question ids in sorted order, so the same table and seed give
    byte-identical output.

    Args:
        table: The `graph_diagnosis.jsonl` path.
        out: The markdown output path.
        seed: The draw seed.

    Returns:
        The sampled question ids in output order.
    """
    rows = sorted(read_table(table), key=lambda r: r["question_id"])
    rng = random.Random(seed)
    rule = GRAPH_REPAIR_RULE_06_3_6
    lines = [
        "# Graph diagnosis spot-check sample (D-137)",
        "",
        f"Seed {seed}; {SPOT_CHECK_PER_CLASS} rows per class; read from the table "
        "only.",
        "",
    ]
    sampled: list[str] = []
    for cls in rule.classes:
        members = [r for r in rows if r["label"] == cls]
        picked = (
            members
            if len(members) <= SPOT_CHECK_PER_CLASS
            else rng.sample(members, SPOT_CHECK_PER_CLASS)
        )
        lines += [f"## {cls} ({len(members)} questions)", ""]
        for row in sorted(picked, key=lambda r: r["question_id"]):
            sampled.append(row["question_id"])
            ev = row["evidence_ids"]
            lines += [
                f"### {row['question_id']}",
                "",
                f"- question: {row['question_text']}",
                f"- mentions: {json.dumps(row['mentions'], ensure_ascii=False)}",
                f"- label: {row['label']}",
                f"- memberships: {', '.join(row['memberships'])}",
                f"- gold_chunk_ids: {', '.join(ev['gold_chunk_ids'])}",
                f"- seed_entity_ids: {', '.join(ev['seed_entity_ids'])}",
                f"- alias_entity_ids: {', '.join(ev['alias_entity_ids'])}",
                "",
            ]
    _write_text(Path(out), "\n".join(lines))
    return sampled


def select_from_table(
    table: Path | str, out: Path | str, *, repo: Path | None = None
) -> dict[str, Any]:
    """Writes the lever-2 selection from the committed table.

    Args:
        table: The committed `graph_diagnosis.jsonl`.
        out: The selection JSON path.
        repo: Repository for the git lookups; the live one when None.

    Returns:
        The written record.

    Raises:
        GraphDiagnosisError: If the tree is dirty, the table is untracked, or the rule
            has no introducing commit.
    """
    root = repo_root() if repo is None else Path(repo)
    if not gitcheck.is_clean(repo=repo):
        raise GraphDiagnosisError("select refuses: the working tree is dirty")
    table_path = Path(table).resolve()
    try:
        rel = table_path.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise GraphDiagnosisError(f"{table_path} is outside the repository") from exc
    if not gitcheck.is_tracked(rel, repo=repo):
        raise GraphDiagnosisError(f"select refuses: {rel} is not committed")
    rule_sha = gitcheck.introducing_commit(
        RULE_TOKEN, gitcheck.THRESHOLDS_PATH, repo=repo
    )
    if rule_sha is None:
        raise GraphDiagnosisError(f"no commit introduces {RULE_TOKEN}")
    rows = read_table(table_path)
    counts = class_counts(rows)
    record = {
        "selected": select_lever2(counts),
        "counts": counts,
        "rule_sha": rule_sha,
        "table_sha256": sha256_file(table_path),
        "graph_diagnosis_commit": gitcheck.last_commit_touching(rel, repo=repo),
    }
    _write_text(Path(out), json.dumps(record, indent=2) + "\n")
    return record


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python -m lancet_eval.graph_diagnosis <command>`."""
    parser = argparse.ArgumentParser(prog="python -m lancet_eval.graph_diagnosis")
    sub = parser.add_subparsers(dest="command", required=True)

    p_table = sub.add_parser("table", help="Regenerate the D-137 diagnosis table.")
    p_table.add_argument("--journal", required=True)
    p_table.add_argument("--seed-probe", dest="seed_probe", required=True)
    p_table.add_argument("--gold-chunks", dest="gold_chunks", required=True)
    p_table.add_argument("--questions", required=True)
    p_table.add_argument("--graph-dump", dest="graph_dump", required=True)
    p_table.add_argument("--out-dir", dest="out_dir", required=True)

    p_spot = sub.add_parser("spot-check-sample", help="Draw the owner spot-check.")
    p_spot.add_argument("--table", required=True)
    p_spot.add_argument("--seed", type=int, default=42)
    p_spot.add_argument("--out", required=True)

    p_sel = sub.add_parser("select", help="Record the lever-2 selection.")
    p_sel.add_argument("--table", required=True)
    p_sel.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "table":
            counts = build_table(
                journal=Path(args.journal),
                seed_probe=Path(args.seed_probe),
                gold_chunks=Path(args.gold_chunks),
                questions=Path(args.questions),
                graph_dump=Path(args.graph_dump),
                out_dir=Path(args.out_dir),
            )
            print(json.dumps(counts, sort_keys=True))
        elif args.command == "spot-check-sample":
            spot_check_sample(args.table, args.out, seed=args.seed)
        else:
            print(json.dumps(select_from_table(args.table, args.out), sort_keys=True))
    except (GraphDiagnosisError, gitcheck.GitCheckError) as exc:
        print(f"graph_diagnosis: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
