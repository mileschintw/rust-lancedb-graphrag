# spare-2 報告（#164）

#128 已以 PR #171 合併（merge commit `0313af73`），報告見該 PR。以下是第二個 PR，處理 #164。

- **分支與 head：** `lane-spare-2-164` 已推送到 `084746bb`，從 origin/main `0313af73` 分出。依序有三個 commit：
  - `b5f9932e`：v1.0 map 改為用到時才載入。
  - `31c1da79`：新增 `external_store`。
  - `084746bb`：review 修正。
- **狀態：** `done`。

## 已不成立的 issue 項目

無。

## 變更（依檔案）

- `eval/src/lancet_eval/score.py`：
  - 不再一律載入 v1.0 document map；每個 store 的 map 在第一筆讀它的紀錄時才載入。
  - 只有 journal 裡有 external arm 時才載入它的 map，用的是 `[documents] external_store` 指定的 store，沒設就用 v1.0。
- `eval/src/lancet_eval/corpus.py`：新增 `[documents] external_store`。值是 store prefix，存成 store name；未知的 prefix 或非字串會丟 `CorpusError`。
- `eval/src/lancet_eval/lever_comparison.py`：compare-levers 重查 external 條款時用同一個 store 的 map。
- 測試：
  - `eval/tests/test_score_store_maps.py`（2 個）。
  - `eval/tests/test_score_external_store.py`（5 個；其中包括協調者要求的「另一個 store 的 ID 會被拒絕」，score 與 compare-levers 各一個）。

## 對 default branch 上已失敗檢查的修正

無。

## 檢查與 lane 測試

- fast tier（eval-only，依 brief 略過 cargo 和 Go）：在 `31c1da79` 執行 `PYTHONUTF8=1 uv run --project eval pytest -n auto --dist loadfile`，結果 3222 passed、14 skipped、42 subtests passed（2 分 04 秒），沒有失敗。
- review 修正後，在 `084746bb` 重跑受影響的檔案（external_store、store_maps、provenance、lever_comparison、corpus*、s1_store_arms）：239 passed。
- slow tier：這次的改動不影響 v1.0 lever run（它沒有 external arm，又有 v1 arm，map 照樣載入），所以沒有跑。

## 衝突

無。

## Review 發現與處理

一輪（Standards 與 Spec 合併由一個 subagent 做），沒有 blocker。
- 已修：註解說明屬性存的是 store name、非字串值會被拒絕並加了測試、移除不需要的 `getattr`、改掉一個名不副實的測試名稱。
- 保留不改：
  - store 解析的那一行在 score 和 lever_comparison 各寫一次。
  - 測試從 `test_run_external` 等其他測試模組 import fixture 和 helper，沒有搬進 conftest。
  - `external_store = "small"` 會讓 v1 map 以另一個 cache key 再載入一次，無害。

## 開出的 issue

無。

## tracker 已記錄的 lane 外問題

無。

## repo 與 scratchpad 外的建立、安裝、移除

無。

## 本 session 使用者與協調者的決定（原話）

- 協調者："GO #164"；以及 "go with (A), a corpus-file key `[documents] external_store`; unset keeps the v1.0 map. Say it in the PR body, and add a test showing an ID from the other store is refused."

## 無人值守期間的決定

- **external arm 的 store 怎麼指定（設計問題）：** 這是設計問題，已先問協調者。回覆是選項 A，見上。
- **`external_store` 的值用 store prefix（`full`）而不是 store name：** 選擇 prefix，與 arm label 和 `[stores.<prefix>]` 的用法一致。

## 給協調者的未決問題

無。
