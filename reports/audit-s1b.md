# audit-s1b 報告：S1 步驟 4 與 S2 路徑紙上稽核

- 分支：`claude/lane-audit-s1b-21c21c`，head = `origin/main` = `ae4aca66`（PR #101 合併後）。本 lane 唯讀：無程式變更、無 commit、無 PR、無 PR body、無付費呼叫、未啟動 live stack、未寫任何 store、未讀 held-out 題目內容。
- 執行過的東西（全部離線、免費）：`--help`、離線 import 與 `gitcheck` 唯讀呼叫、既有離線測試（S1 相關 5 個測試檔 164 passed；`test_replay.py` 54 passed）、scratchpad 裡一個用暫存 fixture run 測 `replay_init` 的小探針（3 passed）。
- 方法：三個 subagent 平行查（S1 步驟 4、S2 路徑、S1→S2 交接），每一項發現我再親自讀碼抽查（見各節）。

## S1 步驟 4（先報）

### 結論

**沒有擋住 S1 的程式問題。** 4.1-4.8 的每個指令、旗標與兩段 python 片段都在 main 上存在，行為也和指南一致。成本重算約 $0.47，上限約 $1.74，符合指南的「約 $0.5，上限約 $1.8」。步驟 4 不讀 held-out。

有一項**建議在 4.2 產生資料前先處理**（S1-2，已開 #105）：決策規則沒寫「比較本身 not evaluable」時怎麼讀。另外指南仍把 #65 當成未關閉（S1-1），只需改指南文字，不會造成損失。

### 發現（S1 步驟 4）

| # | 檔案:行 | 影響的步驟 | 擋住 | 內容 |
|---|---|---|---|---|
| S1-2 → **#105** | `experiments/v1.1/EXPERIMENT-S1.md:55-70`；`eval/src/lancet_eval/lever_comparison.py:829-851`；`provenance.py:769-779` | 4.8 | S1（軟性：4.2 前定案） | 規則寫了 null guard 失敗或 not evaluable 時怎麼辦（否決），**沒寫比較列 not evaluable 時怎麼辦**。成對題數低於 0.80 floor（90 題 G 中少於 72 對）時，該列是 `evaluable: false`、`delta: null`。rerank degrade 的紀錄會被 `provenance.is_ok` 排除；#75 的「每 arm 100 筆」只數 success 加 error，擋不住這種情況。dev 沒有 tripwire，degrade 會一路跑完。這時「delta > 0」與「≥ +0.05」都無從判讀。修法：在規則加一句「`evaluable: false` 時保留 small，graph 不加入」（屬於 pre-registration 修訂，由使用者定，可給新 D-ID）；4.8 在 `delta` 旁一併引用 `evaluable`、`n_pairs`、`coverage`。我已抽查原始碼確認。 |
| S1-3（併入 #105） | `eval/src/lancet_eval/p4.py:317` | 4.8 graph 規則 | 不擋（邊界） | `delta = fmean(x) - fmean(ref)`。在 n_pairs = 80、淨增恰好 4 題（恰為 +5.0 點）時，印出值可能是 `0.049999999999999996`。subagent 離線重現：77 種排列中有 39 種如此。人工判讀「≥ 0.05」會誤判 graph 不加入；72-90 對之間只有 n = 80 受影響。修法：graph 以整數欄位判斷，即 `n_pos - n_neg >= ceil(0.05 × n_pairs)`。 |
| S1-1 | `RUN-S0-S1.md:22-24, 87, 331-335, 338-361`；`EXPERIMENT-S1.md:92-93`；`run.py:989-1007`；`context_export.py:195-216, 404-437` | 規則、0、4.4、4.5 | 不擋（規則漏洞） | **#65 已關閉**（`b026132c`、`679e1fb2`），#68 也已關閉（我已用 `gh` 確認）。現在 drive 經 `store_checkpoint_sources` 從各 arm 自己的 schema 讀 checkpoint，所以正常情況下 4.4 會 **exit 0**，並直接寫出完整的兩 store export。指南仍說 4.4 的非零結束是「唯一預期的非零結束」，這條豁免現在只會掩蓋真正的失敗（例如缺 checkpoint）。不會造成金錢損失：4.5 的 `export-context` 會失敗並停下，#75 的計數也會抓到。修法（只改指南）：刪除 4.4 的豁免與「規則」一節中的那句，刪除 4.5 的 stopgap，並在步驟 0 的表與 EXPERIMENT-S1 › Run constraints 把 #65、#68 標為已清除。未開 issue（不是 blocker；要不要另開指南小修由 coordinator 決定）。 |
| S1-4 | `RUN-S0-S1.md:363-367`；`context_export.py:318-321` | 4.5 | 不擋（備註） | 4.5 的 success 計數用原始的 `load_records`，export 存的則是去重後的 success。目前兩者相等：resume 不會重 drive 已有 error 的題目，重試也都在同一筆紀錄內。為了與 #75 的片段一致，可改用 `deduplicate_by_arm(...)[0]`。 |
| S1-5 | `eval/src/lancet_eval/cli.py:1508-1511` | 4.6 | 不擋（外觀） | dev run 的 `compare-levers` 在 console 印 `|H_G| = 90, |H_N| = 10`，沒標示這是 dev 母體（`.md` 有標示）。列入已知的外觀問題。 |

### 查過、沒問題的（S1 步驟 4）

- **指令**：
  - 4.1 `preflight` 不帶 `--store` 時預設 `V1_STORE`（`cli.py:209-215`），只對 `small/` arm 送 canary（`preflight.py:1761, 1833-1836`）。
  - 4.2、4.4 的 `run --arms a,b` 以逗號切分（`cli.py:610-614`），`--stage-cap 100` 通過驗證（`cli.py:479-494`）。
  - 4.3 的 `--store eval-s1` 對應到 `S1_STORE`，並加跑 `store_chunking`（`preflight.py:1785`）。
  - 4.6 的 `score --no-judge`（`cli.py:1102-1118`）與 `compare-levers --run` 都存在。
  - 4.5 與 4.7 片段引用的名稱與簽章都存在：`read_journal_header` 的 `created_at`（`journal.py:482-487`）、`preregistration_problems` 的 kwargs（`gitcheck.py:265-272`）、`build_lever_comparison(run, prereg=)`（`lever_comparison.py:1697-1705`）。`test_run_guide.py:42-50` 會在 CI 編譯每段片段。三個 prereg token 都在 `1a79535b` 引入，完整的 D-73 檢查在本 checkout 回傳 `[]`。
- **`small/`、`merged/` 標籤**：
  - 前綴對應到 store（`arms.py:248, 329-339`）。`select_arms` 拒絕混合 store（`run.py:753-802`），`check_arm_store` 對照 `LANCET_ENV`（`preflight.py:271-331`）。
  - 一個 journal 兩次 drive：header 只在檔案為空時寫（`journal.py:482`），resume key 含 arm，4 arm × 100 齊全才轉成 publishable（`run.py:1171`）。
  - `score` 依各 arm 的 store 讀 document map（`score.py:2116-2142`）。`compare-levers` 兩份 prereg 的 reference arm、列與 guard 都正確（`test_stage_preregistrations.py:125-160`）。
- **#75 計數片段**：兩次 drive 的 key 不重疊，去重無害。「四個 arm 都要到 100」成立：`questions.diag.jsonl` 有 100 題（90 G、10 null）。
- **決策規則對程式**：
  - `delta` 是 arm 減 reference；0.80 floor 對 90 題 G 是精確分數。
  - null guard 在 `n_pairs ≥ 8` 且 `(b−c)/n ≤ 0.10` 時通過，與 D-264 一致。
  - bootstrap 10,000 次、seed 42。SC-2 與 gate 不用於 S1。
  - 4.8 的「列與 guard」對應到 `families[0].comparisons` 與 `null_guards` 這兩個真實欄位。
- **#68**：已關閉；`test_dev_role_scoring.py` 通過。預設的 gold-chunk 表涵蓋全部 90 題 dev G（comparison 36、inference 31、temporal 23），補上了 audit-s012 留下未驗證的那一項。
- **成本**：
  - `measure.py` 的價格與指南一致。每題約 $0.0011（small）、$0.0012（merged）。
  - 4.2 約 $0.22，4.4 約 $0.24，兩次 preflight 約 $0.015，合計約 $0.47。
  - graph-on arm 最多多 8 條路徑事實（約 550 token），在 8,192 的證據預算內，graph seeding 不呼叫 LLM。
  - 上限約 $1.74（不含重試）。
- **Held-out**：題目來自 `questions.diag.jsonl`；`_enforce_split_role` 會拒絕 dev corpus 裡的任何 held-out ID；split 的輸入檔只算 hash，沒有任何模組開啟 `questions.heldout.jsonl`。
- **D-73**：
  - dev drive 不做 D-73（`run.py:436`）。`score`（`score.py:403-445`）與 `compare-levers`（`lever_comparison.py:481-509`）要求 token 在 `created_at` 之前已 commit、`eval/src/lancet_eval` 乾淨、值未變。
  - 寫進 `eval/runs/` 的檔不會弄髒原始碼樹。S1 run 目錄沒被 gitignore 排除，跑完可以 commit。

## S2 路徑

（進行中）

## S1→S2 交接

（進行中）
