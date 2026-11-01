# spare-2 報告（#128）

- **分支與 head：** `claude/lane-spare-2-6b3626` 已推送到 `2ca7193c`，從 origin/main `68f0009c` 分出。依序有三個 commit：
  - `cbca1eda`：compare-levers 改用各 store 自己的 gold sets。
  - `4bcbc003`：score、`--chunk-text` 和 `chunk-ids`。
  - `2ca7193c`：review 修正。
- **狀態：** `done`。暫停後依擁有者「可以，就這麼辦」恢復。#164 等 #128 合併後，另開新分支做。

## 已不成立的 issue 項目

- `comparison.py`：`compare` 遇到 store-prefixed arm 一律拒絕（`comparison.py` 約 1439 行），merged arm 進不了它的 paper metrics，所以不需要修改。

## 變更（依檔案）

- `eval/src/lancet_eval/store_gold.py`（新檔）：
  - 讀 `inspect_lancedb --chunk-text` dump，並驗 sha256。
  - `build_store_gold_sets`：每個非空 evidence fact 一個集合，收該 store 排過的 chunk 中以 `gold_contained`（含 D-276 folds）包含該 fact 的 chunk。
  - `StoreGold`：讀 v1.0 store 的 arm 用 gold-chunk 表，有 dump 的 store 用 dump 建出的集合，沒有 dump 的 store 不可評估。
  - `reads_gold_chunk_table`、`store_chunking_by_name`、`coverage_inputs`（從 #125 的 `lever_comparison` 搬來）、`unmatched_units`、`write_ranked_ids`。
- `eval/src/lancet_eval/score.py`：
  - four-arm 的 paper hits@4/@10、MRR@10、MAP@10 讀各 arm 自己 store 的 gold sets，沒有 sets 的 arm 不列入，reference 不在時跳過 delta。
  - script-faithful 列：該 store 沒有紀錄的題目以全不匹配的單位計分。
  - `coverage_at_4` 和舊式 per-arm 的 Recall@4、nDCG@10 用各 arm 自己 store 的 chunk size。
  - `score_run(chunk_text=...)`；只有讀 v1.0 store 的 arm 才要求 gold-chunk 表有每題的 row。
- `eval/src/lancet_eval/lever_comparison.py`：secondaries 和 hit4 改讀各 store 的 gold sets；新增 `chunk_text` 參數；v1 檢查放寬方式同上。
- `eval/src/lancet_eval/cli.py`：`score` 和 `compare-levers` 新增可重複的 `--chunk-text STORE=PATH`；新增 `chunk-ids` 指令。
- 測試：
  - `eval/tests/test_store_gold.py`（13 個）。
  - `eval/tests/test_score_store_gold.py`（6 個）。
  - `eval/tests/test_lever_comparison_stores.py`（新增 2 個）。

## 對 default branch 上已失敗檢查的修正

無。

## 檢查與 lane 測試

- **fast tier（eval-only lane，依 brief 略過 cargo 和 Go）：**
  - 執行 `PYTHONUTF8=1 uv run --project eval pytest -n auto --dist loadfile`，結果 4 failed、3206 passed、14 skipped（10 分 54 秒）。當時機器同時在 build cargo、跑兩個 re-score，負載很高。
  - 4 個失敗（`test_measure::test_d211_override_drifted…`、`test_calibration::test_the_key_and_salt…`、`scripts/test_test_targets::test_the_engine_gate_fails…`、`scripts/test_phase02_live_evidence` 的 subtest）都是 git 逾時或負載造成。單獨重跑結果：27 passed、1 skipped、42 subtests passed。
  - 基線（main）也有同類不穩定：`test_phase02_live_evidence` 在平行執行時因 PermissionError 失敗，單獨重跑會過。
- **slow：v1.0 lever run 重算**（`eval/runs/2026-10-10-levers-heldout-multihop_rag_levers_heldout`，在副本上算）：
  - 用本分支和 `origin/main`（scratchpad 裡暫時建的 detached worktree，已移除）各跑一次 `score_run` 和 `build_lever_comparison`，做法與 slow test 相同（只偽造 is_clean）。
  - 306 個 dimensions 完全相同，lever payload 也完全相同。
  - 與 recorded `report.json` 相比，只有 `gold_containment` 和 `gold_containment_delta` 不同，即 #152 已知的 D-276 drift。所以 `test_the_v1_0_lever_run_re_scores_and_re_compares_unchanged` 在本分支和 main 上一樣會失敗，依 brief 不在本 lane 修。
- **merged-store 示範：**
  - 步驟：`lancet-eval chunk-ids` 列出 S1 run 的 merged ID（703 個，`lance-693`）；用本 worktree build 的 `inspect_lancedb --chunk-text` 唯讀 dump `D:/Repos/lancet/data/lancedb-eval-s1`（找到 703 個、缺 0，耗時約 2 秒）；在 S1 run 的副本上執行 score 和 compare-levers。
  - 結果（90 題 dev G）：
    - Hits@10：merged 0.967，small 0.956。
    - MRR@10：merged 0.746，small 0.773。
    - Hits@4：兩者都是 0.900。
    - MAP@10：merged 0.407，small 0.409。
    - all-gold@4（compare-levers）：merged 0.267，small 0.244。
    - 沒有 dump 時 merged 不可評估；small 的數字有沒有 dump 都一樣。
- **規則交叉驗證：** 以既有的 v1.0 dump（`data/heldout-crosscheck-levers/2026-10-10/chunk_text.jsonl`，唯讀）重建 v1 lever run 的 sets，在排過的 chunk 上與 gold-chunk 表比對。804 個單位中 803 個相同；剩下 1 個是 text rule 多匹配一個 chunk。2,156 筆紀錄中，Hits@4、Hits@10、MRR@10 完全相同，只有 4 筆的 MAP@10 不同。
- **沒跑的：** `lancedb-eval-full` 的示範沒做。run C 沒有 report，且 `score` 會因 #164 拒絕它。

## 衝突

無，origin/main 仍是 `68f0009c`。

## Review 發現與處理

- **第 1 輪**（Standards 與 Spec 兩個 subagent）：
  - Blocker：script-faithful 在題目缺紀錄時會崩潰。已修，並加測試。
  - Blocker：缺多項測試（per-store coverage、delta guard、重複 store、mixed generation、`score --chunk-text`）。已全部補上。
  - Note：空 fact 處理和 Rust probe 對齊。已修。
  - Note：重複的 helper 已共用，純 reformat 的 hunk 已還原。
  - Note，保留不改：`_coverage_inputs` 現在只是轉呼叫、測試跨模組 import 私有 helper、dump 的 generation 沒有比對、`graph_ablation_delta` 仍用 run-wide chunk size（它只配對 v1 store 的 arm）。
- **第 2 輪**（只看修正 commit）：沒有 blocker。兩個潛在 note：只有空白的 fact，以及 fact 全空的題目；目前的題目檔都沒有這兩種情況。
- writing-for-agents：沒有改到給 agent 讀的檔案，不需要。

## 開出的 issue

無。

## tracker 已記錄的 lane 外問題

- #152：v1.0 重算的 D-276 drift，已記錄，不需動作。
- #164：score 永遠載入 v1.0 document map，下一個 PR 處理。

## repo 與 scratchpad 外的建立、安裝、移除

- 在 scratchpad 建了 `origin/main` 的 detached git worktree（附帶 `eval/.venv`），已用 `git worktree remove` 加 `prune` 移除。
- 本 worktree 的 `engine/target`（cargo release build），屬於被 gitignore 的 build 輸出。
- dump 都寫在 scratchpad。對 `data/lancedb-eval-s1` 只做唯讀讀取；沒有碰 `data/lancedb-eval`。

## 本 session 使用者的決定（原話）

- 協調者轉達：「可以，先暫停」以及 "Pause #146"，之後恢復：「可以，就這麼辦」。
- 協調者准許唯讀 dump：「read-only dumps from D:/Repos/lancet/data/lancedb-eval-s1 and data/lancedb-eval-full are fine…」。

## 無人值守期間的決定

- **lever_comparison.py 不在 brief 的檔案清單內：** 選擇照樣修改。理由是 S1 的 merged Hits@10 出現在 compare-levers，而且 #125 的規則本來就在這個檔案。
- **比對範圍：** 選擇只比對該 store 排過的前 10 名 chunk，不比對整個 store。兩者數值相同，dump 只需要排過的 ID。另外不限制 chunk 必須屬於 evidence 文件，與官方 text rule 相同。
- **evidence 單位：** 選擇每個非空 fact 一個單位（第 1 輪 review 後由「每個 evidence entry 一個單位」改過來），與 gold-chunk 表的 probe 一致。
- **四臂交集規則：** 選擇保留。merged 的 coverage 沒有值時，依既有設計，所有 arm 的該格一起變成 `n_unscorable`。
- **chunk-ids 指令：** 選擇新增。既有的 `paper_text_crosscheck --emit-ids` 遇到混合 store 的 journal 會拒絕。

## 給協調者的未決問題

- 示範用的是 S1 dev run（merged store）。full store（`eval-full`）的示範要等 #164 修好，score 才能讀 run C。
