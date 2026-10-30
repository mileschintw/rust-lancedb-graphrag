# Lancet evaluation

Language for measuring Lancet's retrieval and answers against benchmarks, and for the v1.1 experiments that compare
it with outside pipelines.

## Runs and arms

**Arm**:
One pipeline configuration evaluated on every question of a reading, identified by a fixed label.
_Avoid_: variant, condition, setting

**Reading**:
One paid evaluation of a fixed set of arms on one question pool, with its decision rule fixed before it runs.
_Avoid_: experiment run, trial

**Pre-registration**:
The committed statement of a reading's arms, primary metric and decision rule, made before the reading is paid for.
_Avoid_: plan, protocol

**Pair**:
The records of two arms for the same question, compared with each other.

**External arm**:
An arm whose retrieval runs outside Lancet, such as the LlamaIndex paper configuration, but whose answers are
written by Lancet's own reader step and scored like every other arm.
_Avoid_: baseline run, foreign arm

**Context export**:
The record of exactly what a reader saw for one question in one arm: the question and the ranked evidence with full
text and document metadata.
_Avoid_: prompt dump, evidence dump

**Decisional reading**:
A reading whose pre-registered comparisons support a claim, tested with paired comparisons in a Holm family.
_Avoid_: final run

**Direction-finding reading**:
A reading on the dev pool that chooses between options by point estimate. It makes no significance claim.
_Avoid_: pilot, tuning run

**Null guard**:
The check that an arm does not abstain less often on null questions than the arm it is compared with.
_Avoid_: abstention check

## Questions

**Dev pool**:
The questions that every v1.1 choice is made on.
_Avoid_: train set, tuning set

**Held-out pool**:
The questions kept back from every choice and read only a fixed number of times.
_Avoid_: test set

**G population**:
The questions in a pool that have gold evidence and a gold answer. The primary metric is scored on these questions.
_Avoid_: gold set, answerable questions

**Null question**:
A question that has no gold evidence. The correct behaviour is to abstain.
_Avoid_: unanswerable, negative

## Models

**Writer**:
The model that extracts the entity graph from chunks at ingest.
_Avoid_: extractor model, indexer

**Reader**:
The model that writes the answer from the packed evidence.
_Avoid_: generator, answerer

## Metrics

**Answer usable**:
A record whose final `Answer:` line contains the gold answer, token for token. This is the primary metric of every
decisional reading.
_Avoid_: accuracy, correctness

**Evidence Hits@4**:
A G-population question whose gold evidence text appears in at least one of the top four evidence chunks handed to
the reader. It works for every arm, whatever its chunking.
_Avoid_: substring hits, text hits

**Chunk-ID Hits@4**:
The older form of Hits@4 that matches gold evidence by Lancet chunk ID. It applies only to Lancet arms on the v1.0
store.
_Avoid_: paper Hits@4

**Context tokens**:
The o200k token count of the evidence text in an arm's context export.
_Avoid_: prompt tokens
