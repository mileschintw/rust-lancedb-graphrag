# Lane prereg-s01 報告

- **分支與 head：** `claude/lane-prereg-s01-73d291`，head `5e7f02329f6adb94b3eea0e82328126133dc0f79`（已推送；在 `5d8fcf7f` 合併 origin/main `f06a020b`）。
- **不再成立的 issue 項目：** 無（本 lane 沒有 Closes）。

## 每個檔案的變更

- `eval/src/lancet_eval/thresholds.py`：新增 `PREREGISTRATION_S0`、`PREREGISTRATION_S1`、`PREREGISTRATION_S1_MERGED_GRAPH`。三個常數放在 `PREREGISTRATION_06_3_6` 之前，因為既有測試 `test_a_moved_preregistered_number_fails_the_ast_gate` 假設 06.3.6 是檔案最後一個 assignment。06.3.6 的內容 byte-identical。`ExternalPipeline` 從 `TYPE_CHECKING` 改為 runtime import；`arms.py` 不 import thresholds，沒有循環。
- `eval/corpora/multihop_rag_s0_heldout.toml`（新）：S0 corpus。held-out 351 題，兩臂，token 為 `PREREGISTRATION_S0`。brief 的「Your files」沒列它，但 D-73 token 必須掛在 corpus 上，S0 少了它就跑不起來。
- `eval/tests/test_stage_preregistrations.py`（新，13 個測試）：每個常數都能 resolve；corpus 的臂與常數一致；S0 走 held-out、S1 走 dev 100；命名未宣告臂的副本 fail closed；S0 缺 LlamaIndex pipeline 時 fail closed；兩個 S1 讀法都能通過 `build_lever_comparison`。
- `experiments/v1.1/EXPERIMENT-S0.md`、`EXPERIMENT-S1.md`（新）：寫明 arms、metrics、決策規則、最小可偵測效應，以及執行限制。
- `experiments/v1.1/RUN-S0-S1.md`（新）：依序列出 S1 store build、LlamaIndex live checks、S0、S1 的每一條指令，附成本估計、讀取內容（是否 held-out）與寫出內容。總估計約 $4-5，上限約 $16。
- `experiments/v1.1/PLAN.md`：新增「S0 and S1 pre-registration decisions」小節（D-261 至 D-264）。既有 D-ID 未動。
- `.gitignore`：S0、S1 的 run 目錄改為可 track（原本會被 `eval/runs/*` 忽略）。brief 沒列這個檔案；改動只有兩行，不屬於其他 lane。

## 修好既有失敗的 check

無。基準時 `scripts/test_phase02_live_evidence.py` 有 1 個失敗（`'future evidence'` subtest），不在 eval 模組內；最終那次全量跑就通過了，看起來是 flaky。我沒有動它。

## Checks 與 lane tests

- Eval fast tier，在 `5d8fcf7f` 跑：`uv run --project eval pytest -n auto --dist loadfile` → `2739 passed, 8 skipped, 42 subtests passed in 632.05s`，EXIT 0。之後的 `5e7f0232` 只改 Markdown。
- Lane tests：`uv run --project eval pytest eval/tests/test_stage_preregistrations.py eval/tests/test_preregistration.py eval/tests/test_corpus.py eval/tests/test_s1_store_arms.py eval/tests/test_run_external.py` → `184 passed, 1 skipped`。
- `ruff check --preview`：新檔案 0 錯誤。`thresholds.py` 10 個 E501，和 main 一樣，都在既有的 06.3.6 行上；新增行 0 錯誤。
- D-73：`gitcheck.preregistration_problems(('PREREGISTRATION_S1_MERGED_GRAPH','PREREGISTRATION_S0','PREREGISTRATION_S1'), created_at=now, unchanged_since_introduction=True)` → `[]`。
- RUN-S0-S1.md 的 4 段 `python -c` 都能 parse，lancet_eval import 全部存在（scratch 腳本驗證）。
- Cargo、Go：沒有跑，本 lane 只動 eval。沒有 main-checkout-only 的 check。

## 衝突

無。合併 origin/main（lane 54 的 #66）沒有衝突。

## Review 結果與處理

第 1 輪有三位 reviewer：standards、spec，以及 RUN guide 的 writing-for-agents。
- Spec blocker：`score` 和 `compare-levers` 只讀 held-out IDs，dev-role run（S1、S2）都無法評分。不在本 lane 檔案內，開成 **#68**，並寫進 guide Step 0。
- Guide blocker：shell 變數在 tool call 之間不會保留，改成字面路徑 `<S0_RUN>`/`<S1_RUN>`。已修。
- Guide blocker：stack 改用背景程序啟動，並禁止兩個 stack 同時跑。已修。
- Guide blocker：每個 step 只問一次，用繁中問。已修。
- Guide blocker：除 4.4 外任何非 0 結束都停下；付費 resume 要重新取得同意。已修。
- Note：`PREREGISTRATION_S1_MERGED_GRAPH` 不受 D-73 檢查保護，4.7 的 recipe 會先跑 gitcheck。已修。
- Note：D-264 的門檻措辭改成依配對數而定（10 對時 2 題以上、8 或 9 對時 1 題以上）。已修。
- Note：dev 不套用 tripwire、S0 preflight 不送 canary、成本上限的措辭。已修。
- Note，留下：eval/README.md 的 canonical corpus 清單沒列 S0/S1。
- Note，留下：三個常數重複相同的數值欄位，D-73 要求每個數字寫在各自的 assignment 裡。
- Note，留下：S1 的測試 fixture 是 held-out role（dev scoping 交給 #68）。

第 2 輪：7 個 blocker 全部修好，沒有新 blocker。
- Note：S0 preflight 會送一次 probe，措辭改為「under a cent」。已修。
- Note，留下：journal 沒有 header 時，recipe 以 TypeError 停下，而不是 D-73 訊息。

## 開的 issue

- **#65** 兩個 store 的 S1 journal，context export 只讀一個 schema（lane 65 處理中）。
- **#67** `seed --store eval-s1` 沒有送 chunking，「merged」store 會變成 v1.0 的切法（lane 67 處理中，連同協調者開的 #69）。
- **#68** score 和 compare-levers 只讀 held-out IDs，dev run（S1、S2）無法評分（lane 68 處理中）。
- 協調者另開了 #69（identity check 只讀 `lancet_eval`），guide 已列入。

## repo 和 scratchpad 以外建立、安裝或移除的東西

無（只開了 GitHub issues #65、#67、#68）。

## 本 session 使用者的決定（原話）

2026-10-30，AskUserQuestion：
1. S0 null guard 的讀法：「雙向讀，勝方須過 (Recommended)」→ D-261
2. S0 數值門檻：「全部沿用 v1.0 (Recommended)」→ D-262（也適用於 S1）
3. S1 保留 small 時的 graph 規則：「在選中的 store 上套用 (Recommended)」→ D-263
4. S1 dev 的 null guard：「沿用 0.10/0.80，兩個選擇都否決 (Recommended)」→ D-264

## 給協調者的未決問題

- S1 要能付費跑分，得等 #67、#69（store build、preflight）、#65（export，有 stopgap）、#68（評分）。S0 不受影響，step 2 和 step 3 現在就能跑。
- `PREREGISTRATION_S1_MERGED_GRAPH` 是本 lane 為 D-263 另加的常數。它不是 corpus token，靠 guide 的 recipe 自行做 D-73 檢查。如果希望工具內建檢查，可以另開 issue。
