# audit-s1b 報告：S1 步驟 4 與 S2 路徑紙上稽核

- 分支：`claude/lane-audit-s1b-21c21c`，head = `origin/main` = `ae4aca66`（PR #101 合併後）。本 lane 唯讀：無程式變更、無 commit、無 PR、無 PR body、無付費呼叫、未啟動 live stack、未寫任何 store、未讀 held-out 題目內容。
- 執行過的東西（全部離線、免費）：`--help`、離線 import 與 `gitcheck` 唯讀呼叫、既有離線測試（S1 相關 5 個測試檔 164 passed；`test_replay.py` 54 passed）、scratchpad 裡一個用暫存 fixture run 測 `replay_init` 的小探針（3 passed）。
- 收尾時 `origin/main` 已前進到 `d943d558`（PR #102 lane 76、#103 lane 77、#104 lane 64）。我看過這段 diff：`run`／`run-external` 改為在送出前印出 D-258 成本估算（`drive_estimate.py`，永不拒絕），另外新增 S0 rehearsal、stub `/rerank` 與 LlamaIndex endpoint override。步驟 4 的指令與 S2 路徑都沒有被改到，以下發現不受影響。
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

### 結論

S2 的程式（#49 的子票）都已在 main 上。指令串 `replay-init` → `batch submit/fetch` → `render` → `score` → `compare-levers` 都存在，帶著需要的旗標，前一步的輸出也接得上下一步。reader arm 標籤 `<S1 arm>@<reader>` 在每一層都完整保留。離線 S2 測試結果：138 passed、1 skipped（skipped 的是需要 build 好 bin 的整合測試）。

但**以目前狀態送出 S2 前，有四件事要先處理**（都已開 issue）：

1. **#107**：OpenRouter batch 的 payload 缺頂層的 `endpoint`、`model`、`provider` 三個欄位。最壞情況是 batch 在共享容量上付費跑完，結果每一筆都過不了 `is_byok`。
2. **#108**：引擎的 strict 答案 schema 用了 `maxLength`／`maxItems`，Anthropic structured outputs 可能拒收。2026-10-25 的測試只用了單一欄位的 schema，真正的 schema 從沒送過 Claude。
3. **#109**：pilot 的紀錄在正式 run 裡無法被取代。若 pilot 之後改了 Sonnet 的 target，整個 run 都無法計分。另外 D-73 要到付費之後才檢查。修法：pilot 改在一個丟棄用的 run 目錄跑，先 commit prereg，再 `replay-init` 正式 run，並在 `replay-init` 與 `submit` 加 D-73 檢查。
4. **#110**：還沒有 S2 的 pre-registration（`PREREGISTRATION_S2`、`EXPERIMENT-S2.md`，含各 reader 的 thinking 表與價格表）、S2 corpus toml、S2 run guide，`.gitignore` 也沒有 S2 run 目錄的例外。S1→S2 交接是沒有任何檢查的人工步驟（見下節）。

我親自抽查了 #107（`batch_client.py:217-223` 只送 `{"requests":[...]}`；`PLAN.md:325` 記載需要這三個欄位）、#108（`openrouter.rs:517-549` 有 5 個 `maxLength`、3 個 `maxItems`）、#109（`batch.py:363-367` 不重送已有 success 的題目；`replay.py`／`batch.py` 都沒有呼叫 `preregistration_problems`）、#110（`thresholds.py` 沒有 S2，`eval/corpora/` 沒有 S2 toml，`experiments/v1.1/` 只有 `RUN-S0-S1.md`）。#108 對 Anthropic 規格的判斷，來自 subagent 讀的 claude-api 參考資料（2026-10-06 快取），未經實際呼叫驗證；pilot 用真正的 schema 一試就知道。

### 發現（S2）

| # | 檔案:行 | 影響的步驟 | 擋住 | 內容 |
|---|---|---|---|---|
| S2-2 → **#107** | `eval/src/lancet_eval/batch_client.py:217-223, 262-268`；`experiments/v1.1/PLAN.md:325` | `batch submit`（OpenRouter） | S2（可能） | 見上文 1。修法：在 `requests` 之前加 `endpoint`、`model`、`provider`；manifest 的 body hash 不變。 |
| S2-3 → **#108** | `engine/src/generation/openrouter.rs:517-549`；`reader_request.py:212-215, 252-268` | submit，兩個 target 都受影響 | S2（native 很可能；OpenRouter 未知） | 見上文 2。拿掉這些關鍵字屬於 D-255 不允許的改寫，需要使用者定一個新 D-ID。`render` 事後仍會檢查同樣的長度上限。 |
| S2-1 → **#109** | `batch.py:15-16, 363-367`；`provenance.py:620-640, 719-747`；`lever_comparison.py:495-500`；`replay.py:96-100` | pilot → Sonnet 改走 native → score | S2 | pilot 紀錄留在 run 裡，已有 success 的題目永遠不會重送。改 Sonnet 的 target 之後，pilot 紀錄過不了 `body_hash`、`rewritten_fields`、`is_byok`、`provider`，`score` 會拒絕整個 run（連 Haiku 也一起），常數改動也會讓 D-73 拒絕。 |
| S2-5 → **#109**（與 H-4 相同） | `journal.py:483-487`；`replay.py:240-253`；`batch.py:203-207`；`lever_comparison.py:479-506`；`run.py:435` | replay-init／submit → compare-levers | S2 | `replay-init` 會蓋 `created_at` 時戳，compare-levers 要求 token 在那之前已 commit。`replay-init` 與 `submit` 都不檢查這點，dev 的 drive 也跳過 gate。晚一步 commit 常數，付費紀錄就永遠無法報告，也無法搬到新的 run。 |
| S2-4 → **#110** | `thresholds.py:557, 640, 708`；`eval/corpora/`；`experiments/v1.1/` | 每個 S2 指令 | S2 | 沒有 `PREREGISTRATION_S2`、S2 corpus toml、`EXPERIMENT-S2.md`。預期內容：Haiku 5.5 thinking off、$0.10/$0.50；Sonnet 5.5 `between_tools`、$2/$10；Opus 5.5 若加入則 thinking on、effort low、$4/$20。S2 toml 必須沿用 S1 的 `map_corpus`、`[questions]`、`[split]`（dev）與 `[stores]`。 |
| S2-6 → **#110** | `experiments/v1.1/`（只有 `RUN-S0-S1.md`） | 執行者 | S2 | **沒有 S2 run guide**；S2 只出現在 PLAN.md 的 D-254 至 D-265。缺少的步驟大綱見下方。 |
| S2-7 | `provenance.py:597-616, 719-735`；`batch.py:430-438` | 「送出的 body = pack body + 改寫」 | 不擋 | `body_hash` 對照的是 S2 當下重新產生的 `pack` body；system message、`max_completion_tokens`、schema 從沒和 S1 的請求比對過。目前風險低：`LANCET_ENV` 的 overlay 只改 `lancedb_path`。修法：`replay-init` 存下每題 `pack` body 的 hash。 |
| S2-8 | `provenance.py:701-702`；`batch.py:771-785` | score | 不擋 | 被 `render` 拒絕、但已計費的 error 紀錄不檢查 `model`、`is_byok`、`provider`、`reasoning_tokens`。 |
| S2-9 | `provenance.py:243-244` | 「記錄 batch ID」 | 不擋 | `batch_id` 子句只檢查非空，不比對 manifest 裡的 batch ID。 |
| S2-10 | `batch_client.py:263, 276, 341, 350`；`cli.py:903, 946` | submit／fetch | 不擋 | `httpx` 的網路錯誤不是 `BatchClientError`，CLI 會印出 traceback。manifest 會正確停在 `submitting`，但執行者看不到「去查 endpoint」的提示。 |

### 缺少的 S2 run guide 大綱（S2-6；未撰寫，已寫進 #110）

0. **前置條件**：
   - S1 的勝出 arm 已寫進 EXPERIMENT-S1 › Result，S1 run 已做過 `export-context`。
   - 已 release build `generate_from_context`。
   - 已設 `OPENROUTER_API_KEY`；走 native 時還要 `ANTHROPIC_API_KEY`（`.env.example` 沒有這一項）。
   - BYOK key 設為「Never use shared capacity」。
1. **Pilot**（在丟棄用的目錄、prereg commit 之前）：`replay-init`，然後對 `@haiku-5.5` 與 `@sonnet-5.5` 各跑 `batch submit --limit N`。
2. 用 `batch fetch` 輪詢，直到沒有 pending。
3. **判讀 pilot**：跑 `score --no-judge`，再人工檢查：
   - `is_byok`、`provider`；
   - `reasoning_tokens`（要是 0，不是 -1）；
   - `model` 是否等於宣告的 slug，或回傳了帶日期的版本；
   - strict schema 造成的 render 錯誤。
4. 決定 Sonnet 走 OpenRouter 還是 native。
5. 撰寫 `EXPERIMENT-S2.md`、`PREREGISTRATION_S2` 與 S2 toml，在乾淨的工作樹上 commit。
6. **正式 run**：
   - 從 S1 的正式 run 重新 `replay-init`，每個 arm 的筆數須等於 S1 的 100。
   - 每個 reader arm：submit（先看成本估算）→ fetch → `--retry-errors` → fetch，直到沒有剩下的題目。
7. `score --no-judge` → `compare-levers`，人工套用規則。
8. commit run 目錄，記錄 batch ID 與實際花費。

### audit-s012 的 S2 發現，現況

| 項目 | 現況 |
|---|---|
| #80（replay-init 寫入 S1 corpus；沒有 role 檢查） | 已由 PR #90（`c4686f7c`）修好 |
| #81（deepseek 用上限價計；各 reader 的母體不一致） | 已由 PR #87 修好 |
| #82（native fallback 過不了；prompt 從沒比對過） | 已由 PR #90（`7a36a08f`）修好；D-265 在 PR #97 |
| #53 留言中的各項 | 已由 PR #92（`af8d20a9`）修好；`model` 對上帶日期版本的問題仍是 pilot 要看的項目（`provenance.py:745`）；`COST_BASIS` 仍沒說明失敗的呼叫算不算（`lever_comparison.py:1324-1333`） |
| #49（Opus 條件 arm；D-73 只看常數本身的賦值） | 仍成立：#49 已關，但沒有 D-ID 定案。#109 處理其中的一般情況 |

### 查過、沒問題的（S2）

- **reader arm 標籤**：解析（`arms.py:250-305, 386, 500-514`）、manifest 命名與 pending 檢查（`batch.py:267-279, 315`）、紀錄與 export 列（`batch.py:716, 747`）、render（`generate_from_context.rs:618-644`）、score（`score.py:2091, 2158`）、compare-levers 分組（`lever_comparison.py:1513-1547`）都正確。
- **reference arm**：是搬過來的 deepseek 紀錄，帶 row hash（`replay.py:231-260`、`lever_comparison.py:1528`）。
- **Q10 每題成本**：以列價 × token 數，在共同母體上計算，再除以可用答案數；batch 實際花費另以 0.5 倍列出（`lever_comparison.py:1421-1464`）。
- **改寫**：只動宣告過的欄位，`pack` body 須能完整往返，由 golden 檔固定（`reader_request.py:149-205`）。
- **native converter 已建好**（`reader_request.py:208-268`）：thinking 設定對 Haiku、Sonnet、Opus 5.5 都有效，不送 `temperature`／`top_p`，100 個 dev 題 ID 都是合法的 `custom_id`。
- **replay 子句**：`row_hash`、`prompt`、`body_hash`、`rewritten_fields`、`model`、`is_byok`、`provider`、`reasoning_tokens`、`batch_id` 都以零容忍執行（`provenance.py:664-760`），缺 reasoning 計數記為 -1 並判為失敗。例外是 S2-7 至 S2-9。
- **submit 前的檢查**：prompt 相符、row hash 相符、`pack` 成功（`batch.py:402-456`）。
- **Q11 生命週期**：
  - submit 前先寫 manifest；有 pending 時拒絕再送；失敗時進入 `rejected` 狀態（`batch.py:127-135, 311-381`）。
  - fetch 可重跑；失敗的請求成為 error 紀錄；`--retry-errors` 只重送沒計費的錯誤（`batch.py:549-582, 689-740`）。
- **D-258**：送出前先印成本估算，永不拒絕（`batch.py:463-492, 543-548`）。
- **`render` 模式**：重用 `generate` 的檢查，只接受 `stop`，不會重問（`generate_from_context.rs:395-700`）。
- **預算**：S2 只用 dev（`replay.py:147-158`），不佔 D-237 的兩次 held-out。

## S1→S2 交接

### 直接回答

- **重放哪個 arm**：S1 選出的 `<store>/hybrid+rerank+metadata`；若 graph 加入，則是它的 graph-on arm（`RUN-S0-S1.md:409-410`、`EXPERIMENT-S1.md:75-76`、`PLAN.md:235-236`）。
- **S2 從哪裡讀這個選擇**：沒有任何程式讀 S1 的結果。這個選擇要**人工抄三次**：
  1. 寫進 EXPERIMENT-S1 › Result（自由文字，目前寫「Not run yet.」，`EXPERIMENT-S1.md:98-100`）；
  2. 寫進 S2 的 prereg 與 stage 檔（兩者都還不存在）；
  3. 填進 `replay-init --source-run <S1_RUN> --arms <arm> --run <S2_RUN> --corpus <S2>`（`cli.py:802-853`）。

  搬過來的是 `<source>/journal.jsonl` 中該 arm 的所有紀錄（含 error）與 `<source>/context_export.jsonl`（`replay.py:195-260`）。
- **什麼會拒絕錯的或缺的選擇**：
  - **`replay-init` 會拒絕**：來源沒有的 arm、S2 corpus 沒列的 arm、reader arm、非 dev 的來源或 corpus、沒有 export 列的 success 紀錄、已有內容的 S2 目錄。
  - **永遠不拒絕**：stage 檔有列出、但不是 S1 勝出者的 arm；不是 S1 正式 run 的來源（探針實際搬了 15 筆）；不滿 100 筆或 header 標為 partial 的 S1 arm（探針搬了 15 筆中的 10 筆，並沿用 `partial: true`）；Result 未寫或未 commit。
  - **要到 Claude 付費之後的 `score` 才拒絕**：常數在 replay-init 之後才 commit 或修改；S2 corpus 的題目、split 或 `map_corpus` 與 S1 不同；stage 檔列了兩個 base arm 卻只搬了一個。

  **這是沒有檢查的人工步驟，因此列為發現**（併入 #110）。
- **其他**：
  - merged store 在 S2 期間不必啟動（`pack` 只讀 export 列），但 `score` 需要磁碟上有 `document_map.eval-s1.json`，S2 corpus 也要設 `map_corpus = "multihop_rag"`。
  - S2 支援 graph-on 與 graph-off 兩種 arm，但沒有任何 S2 測試用帶 store 前綴或 graph-on 的 base arm。

### 發現（交接）

| # | 檔案:行 | 影響的步驟 | 擋住 | 內容 |
|---|---|---|---|---|
| H-1 → **#110** | `EXPERIMENT-S1.md:98-100`；`replay.py:147-260`；`cli.py:802-853` | 4.8 → S2 replay-init | 不擋（結果錯誤風險） | 沒有任何東西把重放的 arm 綁到 S1 的勝出者。修法：在 Result 加一行機器可讀的勝出 arm，用測試把 `PREREGISTRATION_S2` 的 base arm 釘在它上面；`replay-init` 要求搬過來的 arm 等於 prereg 的 base arm。 |
| H-2 → #110 | `replay.py:195-260` | replay-init | 不擋（出處） | 任何含該 arm 的 dev run 都會被接受為來源；路徑照原樣存（探針裡是絕對路徑），來源檔不算 hash，`replay_source.run` 與 `.corpus` 寫了卻從不回讀。 |
| H-3 → #110 | `replay.py:195-260` | replay-init | 不擋（浪費花費的風險） | 不完整或 partial 的 S1 arm 照樣搬過來，要到 batch 付費之後才以 partial 分數的形式出現。 |
| H-4 = S2-5 → **#109** | 同 S2-5 | | S2 | 同 S2-5。這也表示 S2 stage 檔不能先用 placeholder arm 寫好，必須在 S1 Result 之後、`replay-init` 之前新寫並 commit。 |
| H-5 → #110 | `eval/corpora/`；`replay.py` | S2 準備 | S2（預期中的準備工作） | 沒有交接指南與 stage 檔；`replay-init` 不檢查 S2 corpus 的 `map_corpus`、題目、split 是否與 S1 一致。 |
| H-6 → #110 | `.gitignore:61-70` | S2 之後 commit | 不擋 | 沒有 S2 run 目錄的例外（我已確認），不加 `-f` 無法 commit。 |
| H-7 | `RUN-S0-S1.md` 4.7-4.8 | 4.8 | 不擋 | merged-graph 那一半的選擇來自一個沒有程式讀取的檔案（`lever-comparison-merged-graph.json`）。風險低：漏跑 4.7 時，`lever-comparison.json` 裡沒有 merged graph 那一列，結果是缺一個數字，不是錯的數字。 |

## 其他

- 每項變更：無（唯讀）。
- Checks 與 lane tests：本 lane 沒有 lane test，也沒有程式變更，所以未跑 `project.md` 的 checks。跑過的離線測試：S1 相關 5 個測試檔 164 passed；S2 的 `test_batch`、`test_replay`、`test_reader_request`、`test_reader_comparison` 共 138 passed、1 skipped（需要 build 好 bin 的整合測試，預設跳過）；交接探針 3 passed（scratchpad 的 `test_handoff_probe.py`，不在 repo 內）。
- 衝突：無。
- Review：唯讀稽核，未跑 code-review。三個 subagent 的發現，凡是開成 issue 的我都親自抽查過（見各節）；不擋的備註（S1-4、S1-5、S2-7 至 S2-10、H-2、H-3、H-7）採用 subagent 的證據，未逐一重讀。
- 已開 issue：
  - #105（S1 決策規則：比較列 not evaluable 時的讀法、0.05 的浮點判讀）
  - #107（OpenRouter batch payload 缺頂層欄位）
  - #108（schema 的 `maxLength`／`maxItems`）
  - #109（pilot 紀錄無法取代；D-73 在付費後才檢查）
  - #110（S2 沒有 prereg、stage 檔、run guide；交接沒有檢查）

  開之前都用 `gh issue list --search` 查過重複，也查過 plan.md 的 Roadmap，沒有找到。
- 已追蹤、不需動作：#65、#68（已關；指南還沒跟上，見 S1-1）、#74 至 #78、#100、audit-s1a 的 A1 至 A6。
- repo 與 scratchpad 外建立的東西：GitHub 上的 5 個 issue（如上）；records 資料夾的本報告與 status 檔。未建立或安裝其他東西。
- 使用者在本 session 的決定：無（本 session 未向使用者提問）。

## 給 coordinator 的問題

1. **#105** 需要使用者在 S1 步驟 4.2 之前決定規則的措辭（屬於 pre-registration 修訂，可能需要新 D-ID）。
2. **S1-1**（指南仍把 #65 當成未關閉）要不要另開一個指南小修？不擋 S1。
3. **S2 的順序**：#107、#108 要在 pilot 之前或靠 pilot 確認。#109 的「pilot 用丟棄目錄」與 #110 的 prereg 和指南，是 2026-11-02 早上之前的關鍵路徑。#108 若 Anthropic 拒收，需要使用者定一個新 D-ID。
