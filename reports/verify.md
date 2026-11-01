# Lane verify 報告（#165 #166 #168 #169）

- **分支與 head：** `claude/lane-verify-d0e712`，head `8e591424`（已 push）。從 `origin/main` `68f0009c` 開出。之後 main 前進到 `0313af73`（#170、#171），沒有碰到本 lane 的檔案，所以沒有 merge。

## 不再成立的 issue 前提

- **#165：** 「一律答 Yes 約 0.66」只在 D-237 dev 那 100 題（S1/S2/S2X/S3M 共用）上成立，是 0.661。#149 C 的 fresh dev 上只有 **0.537**（287 Yes / 247 No）。v1.0 的 500 題 sample 是 0.603。部落格若寫 0.66，要註明是哪個題池。
- **#168：** issue 預設原本的 CI 是常態近似，其實 `explore_readout` 用的就是 question-level percentile bootstrap。重算後結論不變。

## 各檔案變更

- `eval/src/lancet_eval/constant_baseline.py` + 測試（#165）：每個題池把 `Answer: Yes` / `Answer: No` 丟給 `answer_usable` 計分，並和 `answer_kinds` 的 better constant 對照。
- `eval/src/lancet_eval/paired_ci.py` + 測試（#168）：配對差異的 exact sign-flip p、反轉檢定得到的 permutation 95% CI（20,000 組 seeded 符號向量）、bootstrap、常態近似。另有和單一 deepseek replicate 配對的列（處理 K=1 對 K=2 的差異）。
- `eval/src/lancet_eval/official_scorer.py` + 測試（#166）：從路徑載入官方 `qa_evaluate.py`（缺 tqdm 時用替身，不安裝），逐答案和 `answer_usable` 比較，也實際跑官方 `main`。
- `eval/src/lancet_eval/relation_precision.py` + 測試（#169）：抽 Haiku 有、deepseek 沒有的 relation（每 chunk 一條），用 OpenRouter 便宜模型判斷，產出報告。
- `experiments/v1.1/EXPLORE-S2-MERGED.md`：yes/no 表下加一行 always-Yes 0.661。
- `experiments/v1.1/EXPLORE-C-MHR-FULL.md`：
  - always-Yes 0.537（並說明表中 0.538 的來源）；
  - C 的 permutation CI；
  - 官方 scorer 小節（#166）。
- `experiments/v1.1/EXPLORE-B-2WIKI-READERS.md`：+14.0 的三種讀法表（#168）。
- `experiments/v1.1/WRITER-PILOT.md`：Haiku 多抽出 relation 的精確度小節（#169）。
- `experiments/v1.1/relation-precision/sample.jsonl`：150 條判過的 relation。

## 主要結果

- **#168：** 2Wiki Opus − deepseek +14.0，exact p 1.5e-05，permutation CI [+7.5, +20.5]，bootstrap CI [+8.0, +20.5]，常態近似 [+7.6, +20.4]。和 deepseek r1 或 r2 單獨配對時，下界都還在 +7 以上。C 的 Opus +5.0，permutation CI [+2.3, +7.7]。
- **#166：**
  - 官方 scorer 用空白切 token，有交集就算對，沒有處理棄答的分支。
  - 對可回答的題，「Insufficient information」得 0 分，和 `answer_usable` 一樣。
  - 兩者的差異只來自標點：`Yes,` 和 gold `Google.` 都會被判錯。這讓 C 上 Sonnet 變成低於 deepseek（0.743 對 0.756）。
  - 如果餵整段回答，9–37% 的棄答會因為共用「the」之類的字而被算對。
- **#169：** Haiku 多抽出的 relation 精確度：agent 標註（看不到 writer）0.85 [0.77, 0.91]，Llama 3.3 70B 判 0.91。對照組 deepseek 多抽出的分別是 0.78 和 0.90。兩個判斷一致 128/150。這個精確度是 chunk 平均，不能直接換算成條數。

## 本來就失敗的 check 的修正

無。

## Checks 與 lane tests

- `uv run --project eval pytest -n auto --dist loadfile`，在 `8e591424` 上：`3201 passed, 25 skipped, 42 subtests passed in 219.44s`。
- 新檔案跑 `ruff check --preview --no-fix` 與 `ruff format --check`：All checks passed / already formatted。
- 依 brief（eval-only lane），cargo 和 Go 沒有跑。
- 25 個 skipped 都和環境有關，與本 lane 無關：
  - slow tier（`LANCET_SLOW_TESTS`）：test_decay、test_decay_materiality、test_score_levers；
  - integration tier（`LANCET_EVAL_INTEGRATION`）：test_batch、test_run_external、test_prompt_parity ×3；
  - 缺 POSIX sh：scripts/test_test_targets ×11；
  - 缺 corpus 快取：test_explore_c_preregistration、test_fresh_split、test_twowiki_b、test_explore_b_preregistration；
  - `-O` gate：test_phase02_live_evidence；
  - RUN-S2 已跑過：test_s2_run_guide。

## 衝突處理

無衝突。

## Review 發現與處理

- **Spec（blocker，已修）：** #169「scaled to the pools」那行把 chunk 平均精確度乘上條數，不成立。已刪除，正文和 docstring 都改為說明這是 chunk 平均。
- **Spec（已修）：** 原本標為「by hand」，但其實是 agent（Claude Opus 5.5）標的。已改為「agent, writer hidden」。
- **Spec（已修）：** #166 原寫「runs the official `main`」。已改為：逐 reader 的數字是呼叫官方的 `extract_answer` / `has_intersection` 算的，`main` 則重現了合併後的 accuracy（C 0.7697、S2 0.7883）。
- **Standards（已修）：** 成本公式寫了兩次，合併成 `usd()`；補上缺的 docstring。
- **Standards（notes，未改）：**
  - 跨模組使用 private helper：repo 內已有前例。
  - `paired_ci` 和 `explore_readout` 的讀取迴圈形狀重複。
  - CLI 用 `--journal`，`explore_readout` 用 `--run`。
  - `precision(rows, judge: str)` 用 `getattr` 取欄位。
- **Spec scope notes：**
  - #169 另外判了 deepseek 對照組；
  - #166 另外算了整段回答和 null 題；
  - #165 的 Result 補充各 2–3 行，issue 寫的是一行。
- **第 2 輪：** 只看 `1208d33f..8e591424`（約 30 行）。因為範圍小，由我直接對照第 1 輪的 blocker 檢查，沒有另開 subagent。blocker 已消失。

## 開的 issue

無。

## 已追蹤的 lane 外問題

無。

## Repo 與 scratchpad 以外建立的東西

- 從 main checkout 的 gitignored 快取複製 `eval/corpora/twowiki/.cache/questions.dev.jsonl` 到本 worktree 的同一路徑（gitignored，沒有 commit；只讀 dev 題，沒有讀 held-out）。worktree 清掉時會一起消失。
- 官方 `qa_evaluate.py`（yixuantt/MultiHop-RAG `c1c1287a`，sha256 `A518BC37…26AE7`）只抓到 scratchpad，沒有安裝。
- C 的 journal 解壓到 scratchpad，沒有在 run dir 原地解壓。
- `eval/.venv` 是這個 worktree 的 uv 環境（gitignored）。

## 使用者在本 session 的決定

無。本 session 沒有使用者直接發言。

## 花費

OpenRouter 約 $0.003：Llama 3.3 70B 共 150 個 request，輸入 25,832 token、輸出 900 token。事前估計 $0.0062，上限 $1。沒有用到 Claude credit。

## 給 coordinator 的問題

- `experiments/v1.1/PLAN.md` 的 D-286 寫「a constant Yes scored about 0.66 in S2」。這句對 S2 是正確的，但沒有提到 C 題池只有 0.537。依規則我沒有改 decision 文字；是否要新增 D-ID 補註，由你決定。
- `answer_kinds.py` docstring 的「about 0.66 in S2」同樣正確，沒有改。
