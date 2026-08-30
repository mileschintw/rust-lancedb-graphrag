"""Corpus loading, question schemas, sampling, and dataset fetching."""

from __future__ import annotations

import hashlib
import json
import random
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


class CorpusError(Exception):
    """Raised when corpus configuration or dataset files cannot be loaded."""


class GoldQuestion(BaseModel):
    """Normalized gold question with gold evidence facts and answer."""

    model_config = ConfigDict(extra="ignore")

    question_id: str
    question: str
    question_type: str = "unknown"
    gold_facts: list[str] = Field(default_factory=list)
    gold_answer: str = ""
    evidence_list: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def id(self) -> str:
        """Alias for question_id."""
        return self.question_id

    @property
    def is_null(self) -> bool:
        """True if the query has no gold evidence (the null-query slice)."""
        return len(self.evidence_list) == 0 or len(self.gold_facts) == 0


def _adapt_multihop_rag(raw: dict[str, Any]) -> GoldQuestion:
    qid = str(raw.get("question_id") or raw.get("query_id") or raw.get("id") or "")
    query = raw.get("query") or raw.get("question") or ""
    if not qid and query:
        h = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
        qid = f"mhr-{h}"
    qtype = raw.get("question_type") or "unknown"
    ev_list = raw.get("evidence_list") or []
    gold_facts = [
        str(e["fact"]).strip()
        for e in ev_list
        if isinstance(e, dict) and "fact" in e and str(e["fact"]).strip()
    ]
    gold_ans = str(raw.get("answer") or "")
    return GoldQuestion(
        question_id=qid,
        question=query,
        question_type=qtype,
        gold_facts=gold_facts,
        gold_answer=gold_ans,
        evidence_list=ev_list if isinstance(ev_list, list) else [],
    )


def _adapt_graphrag_bench(raw: dict[str, Any]) -> GoldQuestion:
    qid = str(raw.get("id") or raw.get("question_id") or raw.get("query_id") or "")
    query = raw.get("question") or raw.get("query") or ""
    qtype = raw.get("type") or raw.get("question_type") or "unknown"
    ev = raw.get("evidence") or raw.get("evidence_list") or []
    gold_facts: list[str] = []
    if isinstance(ev, list):
        for item in ev:
            if isinstance(item, str):
                if item.strip():
                    gold_facts.append(item.strip())
            elif isinstance(item, dict):
                fact = item.get("fact") or item.get("text") or ""
                if str(fact).strip():
                    gold_facts.append(str(fact).strip())
    gold_ans = str(raw.get("answer") or "")
    return GoldQuestion(
        question_id=qid,
        question=query,
        question_type=qtype,
        gold_facts=gold_facts,
        gold_answer=gold_ans,
        evidence_list=ev if isinstance(ev, list) else [],
    )


LABEL_ADAPTERS: dict[str, Callable[[dict[str, Any]], GoldQuestion]] = {
    "multihop_rag": _adapt_multihop_rag,
    "graphrag_bench": _adapt_graphrag_bench,
}


class CorpusConfig:
    """Loaded configuration and question loader for a benchmark corpus."""

    def __init__(self, corpus_name: str) -> None:
        root = _repo_root()
        toml_path = root / "eval" / "corpora" / f"{corpus_name}.toml"
        if not toml_path.is_file():
            raise CorpusError(f"Corpus config not found at {toml_path}")

        with open(toml_path, "rb") as f:
            try:
                data = tomllib.load(f)
            except Exception as exc:
                raise CorpusError(f"Invalid TOML in {toml_path}: {exc}") from exc

        self.name = corpus_name
        self.documents = data.get("documents", {})
        self.chunk_size = int(self.documents.get("chunk_size", 500))
        self.commit_documents = bool(self.documents.get("commit_documents", False))
        self.documents_source = str(self.documents.get("source", ""))
        self.license = str(self.documents.get("license", "unspecified"))

        q_sec = data.get("questions", {})
        self.questions_file_rel = q_sec.get(
            "file", f"{corpus_name}/questions.sample.jsonl"
        )
        self.questions_path = root / "eval" / "corpora" / self.questions_file_rel
        self.label_format = q_sec.get("label_format", corpus_name)
        self.sample_seed = int(q_sec.get("sample_seed", 42))
        self.sample_size = int(q_sec.get("sample_size", 500))
        self.fixture_only = bool(q_sec.get("fixture_only", False))

        self.document_subset = data.get("document_subset", {})
        self.models = data.get("models", {})
        self.arms = list(data.get("arms", {}).get("arms", ["graph-on", "graph-off"]))

    @property
    def judge_model(self) -> str:
        return str(
            self.models.get(
                "judge_model", "meta-llama/llama-3.3-70b-instruct:free"
            )
        )

    @property
    def judge_temperature(self) -> float:
        return float(self.models.get("judge_temperature", 0.0))

    @property
    def judge_max_tokens(self) -> int:
        return int(self.models.get("judge_max_tokens", 400))

    @property
    def judge_prompt_version(self) -> str:
        return str(self.models.get("judge_prompt_version", "v1"))

    @property
    def adapter(self) -> Callable[[dict[str, Any]], GoldQuestion]:
        if self.label_format not in LABEL_ADAPTERS:
            raise CorpusError(
                f"Unknown label_format '{self.label_format}' for corpus '{self.name}'"
            )
        return LABEL_ADAPTERS[self.label_format]

    @property
    def questions(self) -> list[GoldQuestion]:
        """Parse and return gold questions from the questions sample file."""
        if not self.questions_path.is_file():
            raise CorpusError(f"Questions file not found at {self.questions_path}")

        questions: list[GoldQuestion] = []
        with open(self.questions_path, encoding="utf-8") as f:
            for line_idx, line in enumerate(f, 1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                try:
                    raw = json.loads(clean_line)
                    q = self.adapter(raw)
                    questions.append(q)
                except Exception as exc:
                    raise CorpusError(
                        f"Error parsing line {line_idx} in {self.questions_path}: {exc}"
                    ) from exc
        return questions


def load_corpus(corpus_name: str) -> CorpusConfig:
    """Load a corpus by name (e.g. 'multihop_rag' or 'graphrag_bench')."""
    return CorpusConfig(corpus_name)


def load_corpus_config(corpus_name: str) -> CorpusConfig:
    """Alias for load_corpus."""
    return load_corpus(corpus_name)


def load_sample_questions(corpus_name: str) -> list[GoldQuestion]:
    """Load sampled gold questions for a corpus."""
    return load_corpus(corpus_name).questions


def _question_sort_key(raw: dict[str, Any]) -> str:
    return str(raw.get("query_id") or raw.get("id") or raw.get("question_id") or "")


def sample_questions(
    all_questions: list[dict[str, Any]], n: int, seed: int
) -> list[dict[str, Any]]:
    """Deterministically sample questions by sorting before and after sampling."""
    sorted_input = sorted(all_questions, key=_question_sort_key)
    if len(sorted_input) <= n:
        return sorted_input
    rng = random.Random(seed)
    sampled = rng.sample(sorted_input, n)
    return sorted(sampled, key=_question_sort_key)


def fetch_corpus(corpus_name: str, print_urls_only: bool = False) -> None:
    """Download source dataset files for a corpus into its .cache directory."""
    root = _repo_root()
    cache_dir = root / "eval" / "corpora" / corpus_name / ".cache"

    urls = {
        "multihop_rag": [
            (
                "MultiHopRAG.json",
                "https://huggingface.co/datasets/yixuantt/MultiHopRAG/resolve/main/MultiHopRAG.json",
            ),
            (
                "corpus.json",
                "https://huggingface.co/datasets/yixuantt/MultiHopRAG/resolve/main/corpus.json",
            ),
        ]
    }

    file_list = urls.get(corpus_name)
    if not file_list:
        raise CorpusError(f"No fetch URLs configured for corpus '{corpus_name}'")

    if print_urls_only:
        for filename, url in file_list:
            print(f"{filename}: {url}")
        return

    cache_dir.mkdir(parents=True, exist_ok=True)
    import httpx

    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        for filename, url in file_list:
            dest_file = cache_dir / filename
            if dest_file.is_file() and dest_file.stat().st_size > 0:
                continue
            resp = client.get(url)
            if resp.status_code != 200:
                raise CorpusError(
                    f"Failed to download {url} (HTTP {resp.status_code}). "
                    f"You may download it manually to {dest_file}."
                )
            # Verify JSON validity before saving
            try:
                json.loads(resp.text)
            except Exception as exc:
                raise CorpusError(
                    f"Downloaded payload from {url} is not valid JSON: {exc}"
                ) from exc

            with open(dest_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(resp.text)


def sample_corpus(corpus_name: str) -> None:
    """Run deterministic sampling and document subset extraction from cached files."""
    root = _repo_root()
    corpus_cfg = load_corpus(corpus_name)
    cache_dir = root / "eval" / "corpora" / corpus_name / ".cache"

    if corpus_name == "multihop_rag":
        questions_raw_path = cache_dir / "MultiHopRAG.json"
        corpus_raw_path = cache_dir / "corpus.json"
        if not questions_raw_path.is_file() or not corpus_raw_path.is_file():
            raise CorpusError(
                f"Missing cached dataset files in {cache_dir}. "
                f"Run 'lancet-eval corpus fetch' first."
            )

        with open(questions_raw_path, encoding="utf-8") as f:
            all_questions = json.load(f)

        for q in all_questions:
            if "question_id" not in q and "query_id" not in q and "id" not in q:
                query = q.get("query") or q.get("question") or ""
                h = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
                q["question_id"] = f"mhr-{h}"

        sampled_questions = sample_questions(
            all_questions, n=corpus_cfg.sample_size, seed=corpus_cfg.sample_seed
        )

        out_dir = root / "eval" / "corpora" / corpus_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # Write questions.sample.jsonl
        sample_file = corpus_cfg.questions_path
        with open(sample_file, "w", encoding="utf-8", newline="\n") as f:
            for q in sampled_questions:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")

        # Extract referenced articles
        referenced_titles = set()
        for q in sampled_questions:
            for ev in q.get("evidence_list", []):
                if isinstance(ev, dict) and "title" in ev and ev["title"]:
                    referenced_titles.add(ev["title"].strip())

        with open(corpus_raw_path, encoding="utf-8") as f:
            full_corpus = json.load(f)

        referenced_docs = []
        unreferenced_docs = []
        for doc in full_corpus:
            title = str(doc.get("title", "")).strip()
            if title in referenced_titles:
                referenced_docs.append(doc)
            else:
                unreferenced_docs.append(doc)

        distractor_count = int(corpus_cfg.document_subset.get("distractor_count", 25))
        rng = random.Random(corpus_cfg.sample_seed)
        unref_sorted = sorted(unreferenced_docs, key=lambda d: str(d.get("title", "")))
        selected_distractors = (
            rng.sample(unref_sorted, min(distractor_count, len(unref_sorted)))
            if unref_sorted
            else []
        )

        subset_docs = referenced_docs + selected_distractors
        subset_docs_sorted = sorted(subset_docs, key=lambda d: str(d.get("title", "")))

        # Write documents.subset.jsonl
        subset_file = out_dir / "documents.subset.jsonl"
        with open(subset_file, "w", encoding="utf-8", newline="\n") as f:
            for doc in subset_docs_sorted:
                f.write(json.dumps(doc, ensure_ascii=False) + "\n")

        # Write subset_selection.json
        selection_meta = {
            "algorithm": corpus_cfg.document_subset.get(
                "selection_algorithm", "referenced_plus_distractors"
            ),
            "seed": corpus_cfg.sample_seed,
            "referenced_count": len(referenced_docs),
            "distractor_count": len(selected_distractors),
            "total_count": len(subset_docs_sorted),
            "articles": [str(d.get("title", "")) for d in subset_docs_sorted],
        }
        with open(
            out_dir / "subset_selection.json", "w", encoding="utf-8", newline="\n"
        ) as f:
            json.dump(selection_meta, f, indent=2)
            f.write("\n")
    else:
        raise CorpusError(f"Sampling is not implemented for corpus '{corpus_name}'")
