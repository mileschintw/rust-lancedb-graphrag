Owner decision 2026-11-01 (coordinator session): "Add to roadmap". The idea came from a side session (owner there: "可以轉告").

## Why

With 90 G questions, the S0-S2 dev readings detect only gaps of about 8 points. A variance decomposition of S2's 5 replicates shows that 600 to 1,000 questions get down to about 3 points, and that more questions help far more than more replicates.

## Ask

A confirmation stage on the full MultiHop-RAG, after S3. It reruns only the key S0-S2 comparisons that were not significant. Candidates:
- S1 small vs merged chunking;
- Sonnet 5.5 vs deepseek as reader;
- the merged store with Claude readers, if #143 supports it.

It does not replace S3's 2Wiki (D-234): the graph cannot help on MultiHop-RAG.

Open points to settle before it runs:
- **Held-out budget (D-237):** S0 already used one read. A new split, designed and pre-registered as a new confirmatory experiment, is needed.
- **Store:** a full 609-document rebuild, plus graph extraction if the graph is in scope.
- **Metric:** fix `answer_usable`'s reward for guessing on yes/no questions first. Report yes/no and open questions separately, or pre-register an adjustment.
- **K:** 2-3 replicates, with the budget going to more questions.

## Files

To be set when the stage is designed: a new corpus config and split, a pre-registration constant, a run guide and an EXPERIMENT file.
