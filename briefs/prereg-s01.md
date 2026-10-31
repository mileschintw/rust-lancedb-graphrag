Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "現在開 pre-registration session (Recommended)" (2026-10-30, answering the coordinator; plan relayed from the user's side session local_e7e9c234-5047-4941-bcb7-efff6356162d, where the user said "我完全不care預算了，你可以算給我看但我覺得花不了多少，我怎麼樣可以開始跑？")
Depends on: none
Waits for (same section): none

- **Lane:** key `prereg-s01`. No issue. S0 and S1 cannot run yet: `experiments/v1.1/PLAN.md` › Process requires a pre-registration committed before each paid run, and main has no `EXPERIMENT-S0.md`, no `EXPERIMENT-S1.md` and no S0/S1 stage constant. This lane writes them and a run guide, in one PR. Running anything paid is out of scope: a later run lane does that in the main checkout.
- **The user decides each decision rule.** Draft the arms, the primary metric (`answer_usable` on G), the null guard and the decision rules from PLAN.md, RESEARCH.md and D-234 to D-260. Then ask the user directly in this session (`AskUserQuestion`, in Traditional Chinese, with your recommendation first) for every rule PLAN.md leaves open. Quote each answer with the user's words in the report and the PR body. New decisions get new D-IDs after D-260; edit no existing D-ID.
- **Fixed points (S2 round, `decisions-2026-10-30.md` › Lane 14/15 open points):**
  - The token is named `PREREGISTRATION_S1`, in the `PREREGISTRATION_06_3_6` form (D-253).
  - S1 uses the levers-dev question set (`questions.diag.jsonl`, `heldout_split.json` dev role): the D-237 dev pool of 100 (90 G, 10 null).
  - External reader levers are `evidence_metadata` only; rerank is retrieval-side.
  - S0 uses one of D-237's two held-out reads; the other is reserved for Confirm.
  - D-258: no mid-run spend caps; print a cost estimate before each paid step.
- **Your files:** new `experiments/v1.1/EXPERIMENT-S0.md` and `EXPERIMENT-S1.md`; the S0/S1 stage constants in `eval/src/lancet_eval/thresholds.py`/`preregistration.py` (add only; frozen constants such as `PREREGISTRATION_06_3_6` stay untouched); new D-IDs in `experiments/v1.1/PLAN.md`; a new run guide, `experiments/v1.1/RUN-S0-S1.md`.
- **The run guide:** one numbered step per command, each with its cost estimate (tokens × current list price, from the code's defaults), what it reads (held-out or not), and what it writes. The order:
  1. S1 store build with live Atlas (main checkout; plan.md › Waiting has the Atlas command). Build a second store and never modify `data/lancedb-eval`.
  2. LlamaIndex live checks (`input_type`, the 346-document export).
  3. S0.
  4. S1.
  Write it for a run lane worker to follow step by step, asking the user before each paid call, store build or held-out read.
- **Other lanes' files:** lane 54 owns `score.py`, `measure.py`, `lever_comparison.py`/`comparison.py`; lane 50 the engine bin; lanes 56 and 59 engine files and `docs/testing.md`. Read them only.
- **Lane tests:** a test that each new stage constant resolves through `preregistration.resolve`, and that a constant naming an undeclared arm fails closed. Checks: the eval fast tier; `ruff` reports no new errors.
- **Before and after:** after this merges, the coordinator asks the user to start the run lane in the main checkout. Deadline context: the Claude API credit expires 2026-11-03, and S2 needs S1's chosen chunking. Ask the user's questions early and keep the drafting tight.
- **Closes:** none
