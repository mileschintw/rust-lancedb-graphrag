# spare-2 報告（#128）：已依擁有者指示暫停

- **分支與 head：** `claude/lane-spare-2-6b3626`，已推送到 `4bcbc003`（從 origin/main `68f0009c` 分出）。
- **狀態：** `blocked`，"paused by owner (#146/#128)"。擁有者在協調 session 裡說："Pause #146"，#128 隨之暫停。目前還沒做 review（第 3 步）、完整檢查（第 4 步）和 PR body 草稿，也沒有讀過任何 store。

## 已不成立的 issue 項目

- `comparison.py`：`compare` 遇到 store-prefixed arm 一律拒絕（`comparison.py` 約 1439 行），merged arm 根本進不了它的 paper metrics，所以不需要修改。

## 已完成（依檔案）

- `eval/src/lancet_eval/store_gold.py`（新檔）：
  - 讀 `inspect_lancedb --chunk-text` dump，並驗 sha256。
  - 對每個非 v1.0 store，把每題的 evidence fact 用 `gold_contained`（含 D-276 folds）比對該 store 的 arm 排過的前 10 個 chunk，建出 gold sets。chunk-ID 指標只讀前 10 名，所以結果和比對整個 store 相同。
  - `StoreGold.sets_for` / `sets` / `evaluable`：沒有 dump 的 store 一律不可評估（#125 的規則）。
  - `#125` 的 `coverage_inputs`（各 store 自己的 chunk size，structure-merge 以 o200k token 計）從 `lever_comparison.py` 搬到這裡共用。
  - `write_ranked_ids`：列出某個 store 排過的 chunk ID，並回傳它的 index generation。
- `lever_comparison.py`（compare-levers）：chunk-ID secondaries 和 hit4 讀各 arm 自己 store 的 gold sets；新增 `chunk_text` 參數。只有讀 v1.0 store 的 arm 才要求 gold-chunk 表有每題的 row，所以全 609 篇的 store 用新題目也能評估。
- `score.py`：
  - four-arm 的 paper_hits@4/@10、MRR@10、MAP@10 和 script-faithful 列讀各 arm 自己 store 的 sets；沒有 sets 的 arm 不列入這些指標，不再算成 0，reference 不在時也跳過 delta。
  - `coverage_at_4` 和舊式 per-arm 的 Recall@4、nDCG@10 用各 arm 自己 store 的 chunk size。
  - `score_run(chunk_text=...)`，v1 表的檢查放寬方式與上面相同。
- `cli.py`：`score` 和 `compare-levers` 新增可重複的 `--chunk-text STORE=PATH`；新增 `chunk-ids --run --store --out` 指令。
- 測試：
  - `tests/test_store_gold.py`：9 個單元測試加 CLI 參數傳遞測試。
  - `tests/test_lever_comparison_stores.py`：加 2 個 merged dump 測試。
  - `tests/test_score_store_gold.py`：3 個 score 兩 store 測試。

## 尚未完成（恢復時接著做）

- `chunk-ids` 指令還沒有測試：要寫的測試在加入時被中斷，沒寫進檔案。
- 第 3 步 review（code-review 加上 writing-for-agents）。
- 第 4 步：完整 fast tier；`LANCET_SLOW_TESTS=1` 的 v1.0 lever 重算測試，用來確認 v1 數字不變（#152 的 D-276 drift 已知，不在本 lane 修）。
- merged store dump 示範：協調者已准許唯讀 dump `data/lancedb-eval-s1` 和 `data/lancedb-eval-full`，後來因暫停撤回，所以沒有讀任何 store。
  - 恢復時的步驟：`lancet-eval chunk-ids --run eval/runs/2026-10-31-s1-multihop_rag_s1_dev --store merged --out <scratchpad>/ids.jsonl`，接著用本 worktree build 的 `inspect_lancedb --chunk-text … --generation … --lancedb-path D:/Repos/lancet/data/lancedb-eval-s1`。
  - 然後在 run 的副本上執行 `score --chunk-text merged=…`，報告 merged 的 Hits@10 / MRR@10。
  - 也可以用 `data/heldout-crosscheck-levers/2026-10-10/chunk_text.jsonl` 交叉驗證：從 v1 dump 建出的 sets，在已排序的 chunk 上應與 v1 表一致。
- PR body 草稿，以及 `done` 狀態。

## 檢查

- 基線（origin/main）：`PYTHONUTF8=1 uv run --project eval pytest -n auto --dist loadfile` 的結果是 1 failed、3188 passed、14 skipped。失敗的是 `scripts/test_phase02_live_evidence.py` 的 'wrong width' subtest，原因是 Windows 上的 PermissionError；單獨重跑 24 passed，屬平行執行下的不穩定，與本 lane 無關。
- WIP head 上的目標測試：`tests/test_store_gold.py tests/test_score_store_gold.py tests/test_lever_comparison_stores.py tests/test_s1_store_arms.py` 共 24 passed；`tests/test_lever_comparison.py` 在第一個 commit 時 70 passed。暫停後沒有再跑完整 fast tier。
- ruff：新檔通過；`score.py` 和 `cli.py` 的 E501/I001 錯誤數不多於 main。

## 無人值守期間的決定

- **lever_comparison.py 不在 brief 的檔案清單內：** 選擇照樣修改。理由是 S1 的 merged Hits@10 出現在 compare-levers，brief 要求這些指標「可評估」，而且 #125 的規則本來就在這個檔案。
- **store gold sets 的比對範圍：** 選擇只比對該 store 排過的 chunk，不比對整個 store。chunk-ID 指標只讀前 10 名，兩者數值相同，而且 dump 只需要排過的 ID。另外沒有限制 chunk 必須屬於 evidence 文件，與官方 text rule 相同。
- **evidence 單位：** 選擇以 `evidence_list` 的每一筆為一個單位，空 fact 對應空集合，與 gold-chunk 表的 `evidence_index` 計數一致。

## 開出的 issue

無。

## repo 外的變更

無。scratchpad 只有一個 patch 腳本。
