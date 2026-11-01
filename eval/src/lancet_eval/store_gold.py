"""Per-store gold chunk sets and chunk size for the chunk-ID retrieval metrics (#128).

The committed gold-chunk table (D-61) maps gold evidence to v1.0-store chunk IDs, so an
arm on another store (D-251) cannot read it. For such a store this module builds the
gold sets from that store's own chunk text: a chunk belongs to an evidence unit's set
when it contains the unit's fact under `metrics.gold_contained` (D-276 folds). The text
comes from an `inspect_lancedb --chunk-text` dump of the chunks the run ranked
(`ranked_chunk_ids` lists them). Every chunk-ID metric (Hits@k, MRR@10, MAP@10,
all-gold@4) reads only the first ten ranked chunks, so matching the facts against those
chunks gives the same values as matching them against the whole store. A store with no
dump is not evaluable (#125).

The coverage metrics read each arm's own `[stores.<prefix>]` chunk size
(`coverage_inputs`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from lancet_eval.arms import STORE_PREFIXES, arm_store, is_external_arm, is_reader_arm
from lancet_eval.config import V1_STORE
from lancet_eval.corpus import GoldQuestion, StoreChunking
from lancet_eval.journal import RunRecord
from lancet_eval.metrics import context_tokens, gold_contained

#: The ranks every chunk-ID metric reads (`metrics.paper_question_scores`).
RANK_CUTOFF = 10

# D-251: `structure-merge` counts its chunk sizes in o200k tokens, the others in
# characters (`corpus.CHUNK_STRATEGIES`).
_TOKEN_SIZED_STRATEGIES = frozenset({"structure-merge"})

type GoldSets = dict[str, list[frozenset[str]]]


class StoreGoldError(ValueError):
    """A chunk-text dump that cannot be read or does not cover the run's rankings.

    Messages name lines and chunk IDs, never chunk text.
    """


def store_name(label: str) -> str:
    """The store name a `--chunk-text` key names: a store prefix or a store name."""
    return STORE_PREFIXES.get(label, label)


def reads_gold_chunk_table(label: str) -> bool:
    """Whether an arm's chunk-ID metrics read the committed gold-chunk table.

    True for a Lancet arm on the v1.0 store (unprefixed or `small`); an external or a
    reader arm has no ranking of its own (D-250, D-257).
    """
    if is_external_arm(label) or is_reader_arm(label):
        return False
    return _on_v1_store(label)


def _on_v1_store(label: str) -> bool:
    return arm_store(label) in (None, V1_STORE.name)


def store_chunking_by_name(config: object) -> dict[str, StoreChunking]:
    """A corpus's `[stores.<prefix>]` chunking, keyed by store name (#125)."""
    return {
        STORE_PREFIXES[prefix]: chunking
        for prefix, chunking in getattr(config, "store_chunking", {}).items()
    }


def ranked_chunk_ids(rec: RunRecord) -> list[str]:
    """The chunk IDs of the first `RANK_CUTOFF` ranks of a record's own ranking."""
    if rec.snapshot is None:
        return []
    return [c.chunk_id for c in rec.snapshot.pre_truncation_ranking[:RANK_CUTOFF]]


def load_chunk_text_dump(path: Path | str) -> dict[str, str]:
    """Reads an `inspect_lancedb --chunk-text` dump and checks each `content_sha256`.

    Raises:
        StoreGoldError: On an unreadable file, a malformed row, or a text that does
            not match its digest.
    """
    texts: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    chunk_id, text, digest = (
                        row["chunk_id"],
                        row["text"],
                        row["content_sha256"],
                    )
                except (ValueError, KeyError, TypeError) as exc:
                    raise StoreGoldError(
                        f"{path}: line {line_no} is not a chunk-text row"
                    ) from exc
                if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
                    raise StoreGoldError(
                        f"{path}: the text of chunk {chunk_id!r} does not match its "
                        "content_sha256"
                    )
                texts[chunk_id] = text
    except OSError as exc:
        raise StoreGoldError(f"cannot read the chunk-text dump {path}: {exc}") from exc
    return texts


def build_store_gold_sets(
    gold_map: Mapping[str, GoldQuestion],
    ranked: Mapping[str, Iterable[str]],
    texts: Mapping[str, str],
) -> GoldSets:
    """One store's gold sets: per question, one chunk-ID set per evidence entry.

    One set per non-empty evidence fact, in `evidence_list` order, the units the
    gold-chunk table's probe writes (it skips an empty fact), so `min(len(gold), 10)`
    counts the same units. A set holds the question's ranked chunks whose text
    contains its fact (`gold_contained`); a fact no ranked chunk contains gets an empty
    set that never matches.

    Args:
        gold_map: The corpus's gold questions by ID.
        ranked: Per question, the chunk IDs this store's records ranked.
        texts: The store's chunk text by chunk ID.

    Raises:
        StoreGoldError: If a ranked chunk ID is missing from `texts`.
    """
    missing = sorted({c for ids in ranked.values() for c in ids if c not in texts})
    if missing:
        listed = ", ".join(missing[:10])
        raise StoreGoldError(
            f"the chunk-text dump lacks {len(missing)} ranked chunk ID(s): {listed}"
        )
    out: GoldSets = {}
    for qid, ids in ranked.items():
        gold = gold_map.get(qid)
        if gold is None or gold.is_null:
            continue
        candidates = list(dict.fromkeys(ids))
        out[qid] = [
            frozenset(c for c in candidates if gold_contained(fact, texts[c]))
            for fact in _facts(gold)
        ]
    return out


def unmatched_units(gold: GoldQuestion) -> list[frozenset[str]]:
    """A question's units, none matching any chunk: for a question never ranked."""
    return [frozenset() for _ in _facts(gold)]


def _facts(gold: GoldQuestion) -> list[str]:
    facts = (
        str(e.get("fact", "")).strip() if isinstance(e, dict) else ""
        for e in gold.evidence_list
    )
    return [f for f in facts if f]


@dataclass(frozen=True)
class StoreGold:
    """Which gold sets a record's chunk-ID metrics read, by the record's store.

    `v1` is the committed table, read by unprefixed arms and the `small` prefix.
    `stores` holds the sets built from each other store's chunk-text dump.
    """

    v1: GoldSets
    stores: Mapping[str, GoldSets]

    def _table(self, arm: str) -> GoldSets | None:
        store = arm_store(arm)
        return self.v1 if _on_v1_store(arm) else self.stores.get(store or "")

    def sets(self, arm: str, question_id: str) -> list[frozenset[str]] | None:
        """An arm's gold sets for a question; None when it has none (not evaluable).

        A store built from a dump holds only the questions its arms ranked.
        """
        table = self._table(arm)
        return None if table is None else table.get(question_id)

    def sets_for(self, rec: RunRecord) -> list[frozenset[str]] | None:
        """The record's gold sets; None when its store has none (not evaluable)."""
        return self.sets(rec.graph_arm, rec.question_id)

    def evaluable(self, arm: str) -> bool:
        """Whether an arm's store has gold sets at all."""
        return self._table(arm) is not None


def load_store_gold(
    v1: GoldSets,
    records: Iterable[RunRecord],
    gold_map: Mapping[str, GoldQuestion],
    chunk_text: Mapping[str, Path | str] | None,
) -> StoreGold:
    """Builds the gold sets of every non-v1.0 store that has a chunk-text dump.

    Args:
        v1: The committed gold-chunk table's sets.
        records: The run's records; each store's ranked chunks come from its own.
        gold_map: The corpus's gold questions by ID.
        chunk_text: Dump path by store prefix or store name.

    Raises:
        StoreGoldError: If a dump names an unknown or the v1.0 store, cannot be read,
            or lacks a chunk its store's records ranked.
    """
    stores: dict[str, GoldSets] = {}
    records = list(records)
    for key, path in (chunk_text or {}).items():
        name = store_name(key)
        if name not in STORE_PREFIXES.values():
            raise StoreGoldError(f"--chunk-text names an unknown store {key!r}")
        if name == V1_STORE.name:
            raise StoreGoldError(
                f"--chunk-text {key!r}: the v1.0 store reads the gold-chunk table"
            )
        ranked: dict[str, list[str]] = {}
        for rec in records:
            if arm_store(rec.graph_arm) == name:
                ranked.setdefault(rec.question_id, []).extend(ranked_chunk_ids(rec))
        stores[name] = build_store_gold_sets(
            gold_map, ranked, load_chunk_text_dump(path)
        )
    return StoreGold(v1=v1, stores=stores)


def coverage_inputs(
    store_chunking: Mapping[str, StoreChunking] | None,
    run_chunk_size: int,
    rec: RunRecord,
    gold: GoldQuestion,
) -> tuple[GoldQuestion, int] | None:
    """The gold question and character chunk size `recall_at_k` reads for `rec` (#125).

    A record is scored against its own store's chunk size, keyed by store name; the
    run-wide size is the v1.0 store's. A token-sized store drops the gold facts longer
    than its size in o200k tokens here and passes a character size no remaining fact
    exceeds. None when no gold fact fits that store's chunk.
    """
    chunking = (store_chunking or {}).get(arm_store(rec.graph_arm) or "")
    if chunking is None:
        return gold, run_chunk_size
    if chunking.chunk_strategy not in _TOKEN_SIZED_STRATEGIES:
        return gold, chunking.chunk_size
    facts = [f for f in gold.gold_facts if context_tokens([f]) <= chunking.chunk_size]
    if not facts:
        return None
    return gold.model_copy(update={"gold_facts": facts}), max(map(len, facts))


def write_ranked_ids(records: Iterable[RunRecord], store: str, out: Path) -> str:
    """Writes one store's distinct ranked chunk IDs for `inspect_lancedb --chunk-text`.

    Args:
        records: The run's records.
        store: A store prefix or name.
        out: JSONL file of `{"chunk_id": ...}` lines, in first-seen order.

    Returns:
        The single `index_generation` the store's records ranked at; pass it to
        `inspect_lancedb --generation` so the dump is the text that was ranked.

    Raises:
        StoreGoldError: If no record ranks on the store, or its records name mixed or
            no index generations.
    """
    name = store_name(store)
    mine = [r for r in records if arm_store(r.graph_arm) == name and r.snapshot]
    if not mine:
        raise StoreGoldError(f"no record ranks on store {store!r}")
    generations = {r.index_generation for r in mine if r.index_generation}
    if len(generations) != 1:
        raise StoreGoldError(
            f"store {store!r} records name index generations {sorted(generations)}; "
            "a dump pins exactly one"
        )
    ids = dict.fromkeys(c for r in mine for c in ranked_chunk_ids(r))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps({"chunk_id": c}) + "\n" for c in ids)
    return next(iter(generations))
