"""#166: MultiHop-RAG's official `qa_evaluate.py` against `answer_usable`, per answer.

The fake scorer below copies the two functions the official file scores with (commit
c1c1287a), and imports `tqdm` at the top as it does, so the loader's stub is exercised.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lancet_eval import official_scorer
from lancet_eval.corpus import GoldQuestion
from lancet_eval.journal import RunRecord

FAKE = """
import argparse
import json
import re
from collections import defaultdict

from tqdm import tqdm


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--queries")
    return parser.parse_args()


def has_intersection(prediction, gold):
    return bool(set(prediction.split()).intersection(gold.split()))


def extract_answer(text):
    match = re.search(r'The answer to the question is "(.*?)"', text)
    return match.group(1) if match else text


def main():
    args = parse_args()
    with open(args.file, "r", encoding="utf-8") as file:
        doc_data = json.load(file)
    correct = 0
    for item in tqdm(doc_data, desc="Evaluating answers"):
        prediction = extract_answer(item["model_answer"]).lower()
        correct += has_intersection(prediction, item["gold_answer"].lower())
    print("Overall Metrics:")
    print(f" Accuracy: {correct / len(doc_data):.4f}")


if __name__ == "__main__":
    main()
"""

BASE = "small/hybrid+rerank+metadata"
SONNET = f"{BASE}@sonnet-5.5"


def _question(qid: str, answer: str, null: bool = False) -> GoldQuestion:
    facts = [] if null else ["a fact"]
    return GoldQuestion(
        question_id=qid,
        question=f"{qid}?",
        question_type="null_query" if null else "comparison_query",
        gold_facts=facts,
        gold_answer=answer,
        evidence_list=[{"fact": f} for f in facts],
    )


def _record(qid: str, arm: str, answer: str, replicate: int = 1) -> RunRecord:
    return RunRecord(
        corpus="c",
        question_id=qid,
        graph_arm=arm,
        outcome="success",
        answer=answer,
        replicate=replicate,
    )


QUESTIONS = {
    "yes": _question("yes", "Yes"),
    "verge": _question("verge", "The Verge"),
    "null": _question("null", "Insufficient information.", null=True),
}


@pytest.fixture
def official(tmp_path: Path):  # type: ignore[no-untyped-def]
    path = tmp_path / "qa_evaluate.py"
    path.write_text(FAKE, encoding="utf-8")
    return official_scorer.load_official(path)


def test_an_abstention_scores_zero_under_both_on_a_yes_no_question(official) -> None:  # type: ignore[no-untyped-def]
    record = _record("yes", BASE, "Not stated.\nAnswer: Insufficient information")
    row = official_scorer.score_answer(official, QUESTIONS["yes"], record)
    assert (row.ours, row.official_line, row.official_full, row.abstained) == (
        False,
        False,
        False,
        True,
    )


def test_a_shared_stopword_in_the_prose_passes_the_official_scorer(official) -> None:  # type: ignore[no-untyped-def]
    text = "The context does not name the outlet.\nAnswer: Insufficient information"
    row = official_scorer.score_answer(
        official, QUESTIONS["verge"], _record("verge", BASE, text)
    )
    # "the" is in the prose and in the gold; the final line alone shares no token.
    assert (row.ours, row.official_line, row.official_full) == (False, False, True)


def test_trailing_punctuation_fails_the_official_token_match(official) -> None:  # type: ignore[no-untyped-def]
    row = official_scorer.score_answer(
        official, QUESTIONS["yes"], _record("yes", BASE, "Answer: Yes.")
    )
    assert (row.ours, row.official_line) == (True, False)


def test_the_comparison_counts_each_reader_and_leaves_null_questions_apart(
    official,
) -> None:  # type: ignore[no-untyped-def]
    records = [
        _record("yes", BASE, "Answer: Yes"),
        _record("yes", BASE, "Answer: Insufficient information", replicate=2),
        _record("verge", SONNET, "Answer: The Verge"),
        _record("null", SONNET, "Answer: Insufficient information"),
    ]
    rows = {r.reader: r for r in official_scorer.compare(official, records, QUESTIONS)}
    deepseek, sonnet = rows["deepseek"], rows["sonnet-5.5"]
    assert (deepseek.g_answers, deepseek.ours, deepseek.official_line) == (2, 1, 1)
    assert deepseek.abstained == 1 and deepseek.abstained_official_line == 0
    assert (sonnet.g_answers, sonnet.null_answers, sonnet.null_official_line) == (
        1,
        1,
        1,
    )


def test_the_official_main_reproduces_the_per_answer_score(
    official, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    records = [
        _record("yes", BASE, "Answer: Yes"),
        _record("verge", BASE, "Answer: Insufficient information"),
    ]
    printed = official_scorer.run_official_main(
        official.__file__, records, QUESTIONS, tmp_path / "work", variant="line"
    )
    assert " Accuracy: 0.5000" in printed
    written = json.loads((tmp_path / "work" / "line.json").read_text(encoding="utf-8"))
    assert written[0] == {
        "query": "yes?",
        "model_answer": "Yes",
        "gold_answer": "Yes",
        "question_type": "comparison_query",
    }
