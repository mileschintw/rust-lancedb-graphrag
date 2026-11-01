# run-s2 報告：RUN-S2 步驟 0-3（pilot）— **blocked**

- 分支：`claude/lane-run-s2-464f82`，head = `origin/main` = `f3f036ee`（本 lane 沒有 commit）。run 在 main checkout `D:/Repos/lancet` 的 `main` 上跑。
- 狀態：**blocked**。pilot 揭露兩個問題，都要先處理才能繼續：一個是程式問題（#137），一個需要 owner 給新 D-ID（#138）。步驟 3 的判讀沒辦法完成，因為三個 reader 都沒有任何一筆 `success` 紀錄。

## 路徑

- `<S1_RUN>` = `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`
- `<WINNER>` = `small/hybrid+rerank+metadata`
- `<PILOT_RUN>` = `eval/runs/2026-10-31-s2-pilot`（gitignore；**還沒刪**，保留作證據。重做 pilot 前要先刪）
- `<S2_RUN>`：還沒定（步驟 5 才定）

## 步驟 0、1（免費）

- Blockers：#107、#109 是 CLOSED；#133、#134 是 CLOSED；#108 是 OPEN，本來就要由 pilot 回答。
- 前提 1：EXPERIMENT-S1 › Result 寫明勝出者是 `small/hybrid+rerank+metadata`，run 是上面的 `<S1_RUN>`。
- 前提 2：`context_export.jsonl` 有 400 列，S1 journal 去重後有 400 筆 success（4 個 arm 各 100）。
- 前提 3：使用者確認 BYOK 設定為「Never use shared capacity」（見〈使用者的決定〉）。
- `OPENROUTER_API_KEY` 已設定（只檢查有沒有，沒有印出來）。
- `git pull --ff-only`：Already up to date；`git status` 乾淨。
- `cargo build --release --bin generate_from_context`：`Finished release profile … in 1.00s`，exit 0（bin 是 17:03 的，本來就是最新的）。
- 步驟 1 的片段：照原文執行，`thresholds.py` 和 S2 corpus 已填入 `<WINNER>`，**留在 main checkout 的工作樹裡，沒有 commit**（`git status --short`：` M eval/corpora/multihop_rag_s2_dev.toml`、` M eval/src/lancet_eval/thresholds.py`）。檢查結果：`22 passed, 1 skipped in 7.20s`。

## 步驟 2（付費 pilot）

- 2.1 `replay-init --pilot`：`Carried 100 record(s) and 100 export row(s)`；計數為 `small/hybrid+rerank+metadata success 100`。
- 2.2 送出四個 arm，各自印出的估計：

| arm | 送出 | 印出的估計 | 印出的上限 |
|---|---|---|---|
| Haiku 5.5 | `batch-1793513172-NhwtnmeA5URdHsPsd9jp`，25 筆 | about $0.0051 | $0.0159 |
| Sonnet 5.5 | `batch-1793513178-DuI7z1ga0my7I5nYA8N2`，25 筆 | about $0.1025 | $0.3178 |
| Opus 5.5 | `batch-1793513183-UANxDGyr1uRrJb2Y8eEf`，25 筆 | about $0.2051 | $0.6356 |
| deepseek r2-r5（sync） | `sync-small_hybrid_rerank_metadata-1-1793513187`，20 筆 | about $0.0042（Wafer 價 $0.0448/$0.3） | $0.0145 |

  deepseek 那一筆印出：`Routing (small/hybrid+rerank+metadata): 0 of 20 billed record(s) break is_byok or the provider`。

- 2.3 fetch：
  - 第一次 fetch：Sonnet 有 25 筆 `batch_no_result`。
  - 23:17 的 fetch：`Journalled 0 success and 50 error record(s); 0 batch(es) still pending`。Haiku 與 Opus 各 25 筆，全部是 `batch_unreadable_response`（`unreadable OpenRouter response: KeyError('choices')`）。
  - 兩次的 `Routing` 行都是 0 of 0。
- 2.4 provenance：
  - deepseek 的 20 筆全部是 `success deepseek/deepseek-v4-flash-0731 Wafer False 0 None`。
  - reader 沒有 success 紀錄，沒有東西可以印。
- 2.5 replay 子句：`0 replay clause failure(s)`。但 error 紀錄不跑子句，所以這個 0 只代表 deepseek 那 20 筆通過。

### 直接查 endpoint（免費的 GET；原始 JSON 不含 key，存在 `side-session-notes/local_e5497074-…/run-s2-pilot-raw/`）

| 項目 | Haiku 5.5 | Sonnet 5.5（OpenRouter） | Opus 5.5 | deepseek r2-r5 |
|---|---|---|---|---|
| batch status | `completed` 25/25 | **`failed` 0/25**，`usage: null`（沒有計費） | `completed` 25/25 | sync 20/20 success |
| 每筆的 model | `anthropic/claude-haiku-5.5`（batch 層是 dated 的 `…-20261007`） | – | `anthropic/claude-opus-5.5`（batch 層是 `…-20260921`） | `deepseek/deepseek-v4-flash-0731` |
| provider | `Anthropic`（每筆與 batch 層一致） | batch 層是 `Anthropic` | `Anthropic` | `Wafer` |
| `is_byok` | **每筆都沒有這個欄位**；只有 batch 層 `usage.is_byok: true` | – | 同 Haiku | `False` |
| `reasoning_tokens` | 0（25 筆都是） | – | 0（effort low，25 筆都是） | 0 |
| #108 strict schema | **接受**：25 筆都是 200、`finish_reason stop`，content 是合法 JSON | 沒有跑到（batch 先失敗） | **接受**：同 Haiku | 接受 |
| Sonnet `between_tools` | – | **Batch API 拒絕**：`uses thinking.type: "between_tools", which is not supported on the Batch API. Remove it and resubmit, or use the sync API for this feature.` | – | – |
| 實際花費 | upstream $0.008492（BYOK，Claude credit，OpenRouter `cost` 0） | $0 | upstream $0.32976（同上） | 最多 $0.0145（印出的上限；確切金額看 OpenRouter activity） |

- 每筆 prompt tokens 約 4,100-5,050，高於指南假設的 3,500（Claude tokenizer）。Opus 25 筆實際花 $0.33，高於印出的 $0.2051，但低於印出的上限 $0.6356。
- **pilot 合計**：約 $0.34（Claude credit）加上不到 $0.015（OpenRouter），在同意的上限 $1.50 之內。

## 步驟 3：不能判讀，只能停下

三個 reader 都沒有任何 `success` 紀錄，原因有兩個：

1. **#137（程式，所有 Claude reader 都擋）**：OpenRouter batch 結果的每一筆是 `{"response": {"status_code", "request_id", "body": <chat completion>}}`，但 `batch_client._openrouter_result` 把 `response` 本身當成 completion 解析，所以 Haiku、Opus 的 50 筆答案（已計費）全部變成 unreadable。即使把 `body` 拆出來，每筆的 usage 也沒有 `is_byok`（只有 batch 層有），score 的 `is_byok == True` 子句仍會擋下每一筆。另外，batch 層的失敗訊息沒有寫進 error 紀錄。測試用的假 endpoint 用了錯誤的格式，所以 audit-s2 的預演沒抓到。
2. **#138（要 owner 給 D-ID）**：Sonnet 的 `thinking: between_tools` 被 Anthropic Batch API 拒絕。D-260 的 native 備案走的也是 Message Batches API，送的是同一個欄位，所以步驟 3 的 native 重做幾乎一定會用同樣的原因失敗。**我沒有做 native 重做**，因為它不在同意範圍內，而且看起來不會成功。

步驟 3 表格目前能確定的部分：
- Haiku、Opus：model 正確且沒有日期、provider `Anthropic`、reasoning 0、schema 被接受。`is_byok` 在 batch 層是 True，每筆沒有。
- deepseek：每一列都通過（model、`Wafer`、`False`、0；Routing 0 of 20）。
- Sonnet：沒有資料。

## 每個檔案的變更

- repo（本 lane 分支）：無。
- main checkout 的工作樹：步驟 1 修改了 `thresholds.py` 和 `multihop_rag_s2_dev.toml`，沒有 commit。另外 `eval/runs/2026-10-31-s2-pilot/`（gitignore）。

## Checks

本 lane 沒有程式變更，所以沒跑 `project.md` 的 checks。跑過的只有步驟 1 的檢查：`22 passed, 1 skipped`。

## 衝突

無。

## Review

沒有程式變更，沒跑 code-review。

## 已開的 issue

- #137：S2 batch fetch 的 OpenRouter 結果格式（`response.body`），以及 `is_byok` 只在 batch 層。Refs #53。
- #138：Sonnet 的 `between_tools` 被 Batch API 拒絕，D-260 的備案也行不通，需要 D-ID（內附三個選項）。Refs #49、#108。

## 已追蹤、不需動作

- #108：Haiku 和 Opus 的部分由這次 pilot 回答了：schema 被接受。Sonnet 要等 #138 解決。建議 coordinator 在 #108 留言記錄結果。

## repo 與 scratchpad 以外建立的東西

- `D:/Repos/lancet/eval/runs/2026-10-31-s2-pilot/`（gitignore；保留作證據，重做前要刪）。
- main checkout 的工作樹改動（步驟 1，指南要求的）。
- 共用筆記資料夾的 `run-s2-pilot-raw/` 三個 JSON（不含 key）。
- GitHub issue #137、#138。
- 沒有安裝任何東西。

## 使用者在本 session 的決定

- BYOK 前提 3：問「OpenRouter 上 Anthropic 的 BYOK key 是否設為 Never use shared capacity？」，使用者選「已確認，開始 pilot」。
- pilot 的同意來自 brief：「開 run-s2，pilot 同意」。

## Coordinator 更新（2026-10-31）

- #137：已開 lane 137，`is_byok` 改從 batch 層取（D-279；owner：「開 lane，batch 層 is_byok (Recommended)」）。
- #138：owner 還沒選。
- 重做 pilot：owner 同意「同意，約 $0.6（上限 $1.5） (Recommended)」。拿到 GO 之後，刪除 `<PILOT_RUN>`，`git pull`，重跑步驟 1 的片段，再跑 2.1-2.5，不必再問一次。如果印出的估計會讓重做超過 $1.50，就停下來。
- 依 coordinator 的要求，已經用 `git checkout --` 還原 main checkout 中步驟 1 的兩個檔案，`git status --short` 沒有輸出。

## #138 native Sonnet 探測（owner：「先免費試原生 batch (Recommended)」）

- **沒有執行**：`ANTHROPIC_API_KEY` 沒有設定。這個 shell 沒有，Windows 的 Process、User、Machine 環境變數都沒有，repo 和 `eval/` 底下也沒有 `.env`（只檢查有沒有，沒有印出值）。
- 沒有花錢。main checkout 沒有改動，維持乾淨的 `f3f036ee`。步驟 1 的改動之前已經還原，所以這次沒有再貼回去。
- 要執行的話：owner 必須在這個 session 繼承的環境裡設定 `ANTHROPIC_API_KEY`（必須是持有 Claude credit 的那個 org 的 key），之後 coordinator 再給 GO。

## 給 coordinator 的問題

1. **#138 要 owner 給 D-ID**，選項見 issue：(1) Sonnet 改走 sync API 並保留 `between_tools`（約 $5，上限約 $18.9，要寫程式）；(2) Sonnet 走 batch，thinking 改 off（只改常數）；(3) Sonnet 走 batch，thinking 改 on 加 effort（只改常數）。常數還沒 commit，D-73 不受影響。
2. **#137 要開一個修程式的 lane**（`batch_client.py` 加測試，用真實的結果格式）。`is_byok` 改從 batch 層取，是否需要 D-ID？
3. 修好之後要**重做 pilot**：刪掉 `<PILOT_RUN>`，再跑一次 2.1-2.5。Haiku 和 Opus 大約再花 $0.34，Sonnet 依 #138 的選擇而定。這需要使用者再同意一次，因為「pilot 同意」的上限 $1.50 已經用掉約 $0.35。另外，main checkout 工作樹裡步驟 1 的改動要保留，還是先還原，讓修程式的 lane 在乾淨的 main 上合併？（修程式的 lane 會在 worktree 裡做，所以不衝突；重做前 `git pull` 也需要工作樹沒有衝突。）
