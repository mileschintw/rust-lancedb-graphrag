Follow `relay:work` and `project.md`; this brief holds only what is specific to this lane.
User's go-ahead: "Confirm and start" (2026-11-01), confirming the S3 grid scope and blinding rule relayed from side session local_31cb9ac6 ("新規定我同意"; "可以，就這樣，先不說死不跑，但先確認重要的一定要跑").
Depends on: none
Waits for (same section): none

- **Lane:** key `spare-1`, now #163: the S3 held-out reader grid on 2Wiki. The issue body is the spec. Branch from origin/main (68f0009c or later) in your own worktree.
- **Order:**
  1. Free work: the next D-ID after D-290 (blinding rule), the run-plan constant (own D-73 freeze commit), the corpus config, `RUN-S3-HELDOUT.md`. Push, write `done`; I open the PR and merge on green, then send "continue".
  2. Paid, in the main checkout `D:/Repos/lancet` (free now; no other lane holds it): submit the closed-book and hybrid Claude cells first (Batch API; Haiku off, Sonnet and Opus effort low; BYOK checks as in S2/#149). deepseek cells via OpenRouter.
  3. Graph cells after lane 145's deepseek extraction merges (#145): import the four writers' graphs into the 2Wiki store as new side tables with `import_graph_extractions` (#148's path; never write existing tables), Opus x graph-deepseek first.
- **Never score held-out runs** in this lane. Record run dirs and spend only.
- **Ceilings:** Claude credit $34.50 (owner's balance $37.52, keep ~$3 margin); OpenRouter $3. Print each estimate; over a ceiling, ask. Every Claude batch must be submitted before 2026-11-03 (Pacific), ideally today.
- **Held-out:** use the D-243 split (`eval/corpora/twowiki/split.json`) as frozen; no reading of held-out answers.
- **Run artifacts:** commit full run dirs (owner: "全都公開repo備份全文"); gzip files over 50 MB.
- **Rules:** no keys or env values in any record; prefix commands with `PYTHONUTF8=1`.
- **Closes:** #163 (in the final record PR; the freeze PR says Refs #163)
