# audit-s2 報告：S2 run guide 紙上稽核＋免費預演

- 分支：`claude/audit-s2-c1dcbd`，head = `origin/main` = `7aa4c50c`（PR #132 lane 123 與 PR #131 lane 124 合併後）。本 lane 唯讀：沒有程式變更、沒有 commit、沒有 PR、沒有 PR body、沒有付費呼叫、沒有啟動 engine stack、沒有寫任何 store、沒有寫 `eval/runs/`、沒有讀 held-out 內容。
- 方法：
  - **第一部分（紙上）**：我自己沿 RUN-S2.md 步驟 0-8 走一遍，另有兩個 subagent 平行查（A：指令、旗標、片段、D-73、交接、D-274/275/276；B：provider pin、BYOK、成本）。下表的每個 blocker，我都親自讀過程式碼，或在預演中重現過。
  - **第二部分（預演）**：在 scratchpad 的 repo clone（`7aa4c50c`）裡照指南把 K=5 全程跑一遍（見〈免費預演〉）。

## 結論

**目前不能開始付費 pilot。** 有兩個程式 blocker 和兩個指南 blocker，四個都免費就能發現，也免費就能修：

- **B1（程式，擋 2.2 與 6.1）**：deepseek replicate 的 `batch submit` 一定被拒（`the body pins no provider`）。lane 123 的測試用的是假的 `client_factory`，沒有跑到真的 `OpenRouterBatchClient`，所以沒抓到。
- **B2（程式，擋 7.1）**：Sonnet 裁判不檢查 `is_byok`。一旦 BYOK 沒生效，最多約 $6.3 會記到 OpenRouter credit，連同其他項目會超過 $7.6。
- **B3（指南）**：步驟 5 之後，`git status --short` 不可能是空的，照字面執行的人會停在 6.1。
- **B4（指南）**：#108 仍是 OPEN。步驟 0 規定它關閉、且修正在 main 上才能進 pilot，但正是 pilot 要去驗證 #108。

另有一項**建議在步驟 4 之前由使用者看過**（P1）：D-275 讓「誰最便宜」直接決定起始人選。可是 deepseek 的價格基準（2026-10-09 牌價，輸出 $1.28/M）在 S1 的 token 數下與 Haiku 幾乎打平；用 Wafer 實際價格算，deepseek 便宜一半。

其他都對得上：指令、旗標、片段、常數型別、D-274、D-275、D-276、D-73、S1→S2 交接、Claude 的 `provider.only` 與 `is_byok` 子句、deepseek 的 D-271 pin 與子句。修掉 B1 之後，預演從 replay-init 一路跑到 `judge-answers` 都沒有錯。

## Blockers（每項附修法與檔案；issue 由 coordinator 開。我用 `gh issue list --search` 查過，沒有重複的）

| # | 檔案:行 | 影響步驟 | 內容 | 修法 |
|---|---|---|---|---|
| **B1** | `eval/src/lancet_eval/batch_client.py:239-275`（`_openrouter_head`） | 2.2 最後一行、6.1 的 `<WINNER>` arm | `_openrouter_head` 要求每個 body 都有 `provider.only`，batch 層的 `provider` 也只複製 `only`、`allow_fallbacks`。deepseek 的 `pack` body（D-271）是 `{"require_parameters":true,"order":["wafer/us"],"allow_fallbacks":false,"max_price":{"prompt":0.07,"completion":0.45}}`，沒有 `only`，所以 `batch submit` 印出 `Batch submit refused: mhr-…_r2: the body pins no provider`，exit 1。這發生在 HTTP 之前，不會花錢；manifest 標成 `rejected`，不會擋住修好之後的重送（預演已確認）。**後面還有第二個問題**：即使放行，batch 層的 `provider` 也帶不上 `order` 與 `max_price`。OpenRouter batch 是否尊重每個 body 自己的 `provider`，文件沒寫（`PLAN.md:493`）。測試漏掉的原因：`test_replicates.py:235` 換掉了 `client_factory`，`test_batch.py` 的 `FakeClient` 也一樣，沒有任何測試把 deepseek body 送進真的 `_openrouter_head`。 | 對通過 `deepseek_pin_problem` 的 body，batch 層改送 OpenRouter batch schema 接受的 pin（例如 `only: ["wafer"]` 或 `order`，加上 `allow_fallbacks: false`；schema 若接受，也帶 `max_price`），body 內的完整 pin 保留。另加一個測試，用真的 `_openrouter_head` 和 `OpenRouterBatchClient`（httpx 打樁）送 deepseek body。pilot 3 的 `provider == Wafer` 與 `is_byok False` 會確認實際路由。如果 batch 層無法強制 `max_price`，需要使用者給新 D-ID 接受這一點。檔案：`batch_client.py`、`tests/test_batch.py`。 |
| **B2** | `eval/src/lancet_eval/answer_judge.py:165-186`（`_parse`）、`:340-360` | 7.1 | Sonnet 裁判的 request 有 pin `provider: {only: ["anthropic"], allow_fallbacks: false}`（`:106-109`），但 `_parse` 只讀 content 和 token，從不讀 `is_byok`、`provider`、`model`，任何判決都照樣寫進 cache。唯一的保護是使用者在 OpenRouter 的設定。這和 reader 的做法不一致：reader 在 score 時對 `is_byok` 零容忍。BYOK 一旦失效，Sonnet 裁判會改扣 OpenRouter credit：估計約 $2.2，上限 $6.31（1,800 次 × 252 in／300 out）。加上 deepseek 與 gpt-4o-mini 的上限約 $1.55，合計約 $7.9，超過 $7.6。 | Sonnet 裁判要求 `usage.is_byok is True` 且 `provider == "Anthropic"`。第一筆不符就停掉整次執行，該筆不寫進 cache（gpt-4o-mini 本來就扣 OpenRouter credit，不必檢查）。檔案：`answer_judge.py`、`tests/test_answer_judge.py`。另一個做法是使用者明確接受「只靠伺服器端設定」。 |
| **B3** | `experiments/v1.1/RUN-S2.md:14-15, 272`；`.gitignore:71`；`gitcheck.py:26` | 5 → 6.1 | 規則寫「步驟 5 起，每次 `replay-init` 與 `batch submit` 之前，`git status --short` 必須沒有輸出」。可是步驟 5 會建立 `<S2_RUN>`，而 `.gitignore:71` 刻意不忽略它（`!eval/runs/*-multihop_rag_s2_dev/`），所以第一次 submit 之前就會印出 `?? eval/runs/…-s2-multihop_rag_s2_dev/`，照字面執行的人會停下。程式的 D-73 只檢查 `eval/src/lancet_eval`（`gitcheck.py:26` `SOURCE_DIR`）。 | 規則與步驟 5 改成 `git status --short -- eval/src/lancet_eval` 必須沒有輸出（RUN-S0-S1.md:11 已經這樣寫）。檔案：`RUN-S2.md`。 |
| **B4** | `experiments/v1.1/RUN-S2.md:80-87` | 0 → 2 | 步驟 0 的表把 #108 列為步驟 2-7 的 blocker，並規定「issue 關閉、且修正在 main 上」才算清除。我用 `gh` 確認：#107 CLOSED、#109 CLOSED、**#108 OPEN**。但指南步驟 2、3 本來就是要讓 pilot 去驗證 #108（Anthropic 是否接受 `maxLength`／`maxItems`；預演確認 pack body 的 schema 仍帶著這兩個欄位）。照字面讀，步驟 0 會擋住正要回答 #108 的那個 pilot。 | #108 那一列改成「由 pilot（步驟 3）確認；被拒則停下，等使用者給 D-ID」，從步驟 0 的清除條件移除。檔案：`RUN-S2.md`。 |

## 建議在步驟 4 之前由使用者看過

| # | 檔案:行 | 內容 |
|---|---|---|
| **P1** | `measure.py:73-77`（`GENERATION_LIST_*_PRICE_PER_1M` = 0.0137 / 1.28）；`batch.py:591-595`；`lever_comparison.py:1539-1551, 1605-1645` | D-275 用「每個答對問題的成本」（sync 牌價 × token）挑起始人選。deepseek 的價格是 D-257 定的 2026-10-09 OpenRouter 牌價。以 S1 勝出 arm 的實際 token（平均 2,536 in／297 out）計算，每次 request：deepseek 0.0137/1.28 → 約 $0.000415；Haiku 0.10/0.50 → 約 $0.000402（假設 token 相同）。兩者只差約 3%，起始人選會由 Claude 的 tokenizer、答案長短和可用率決定。若改用 Wafer 實際價格（0.0448/0.30，D-271），deepseek 約 $0.000203，便宜一半。（預演用的是假答案和相同 token，deepseek 每個答對問題 $0.00049，Haiku $0.00054。）另外，這個價格不在 `PREREGISTRATION_S2` 裡，D-73 不會凍結它：只要在步驟 4 之後 commit 改動 `measure.py`，D-73 照樣會過。建議：由使用者確認 deepseek 的價格基準（維持 D-257，或改用 Wafer 價格並給新 D-ID），寫進常數或 EXPERIMENT-S2 › Readers，再進步驟 4。 |

## 記錄的發現（不擋）

| # | 檔案:行 | 內容與修法 |
|---|---|---|
| L1 | `RUN-S2.md:364` | 7.1 徵詢同意時說「約 $0.5（90 G × 4 arms 一輪）」。但裁判對每個 replicate 都判（`answer_judge.py:193, 227-236`），實際會印出約 $2.2-2.5。表格（`:72`）是對的。修法：徵詢時用「約 $2.50，上限約 $6.70」。 |
| L2 | `RUN-S2.md:72-73` | 7.1 的上限寫成和估計一樣（$2.50）。實際上限約 $6.70：Sonnet $6.31（`MAX_TOKENS = 300`，sync 全價），gpt-4o-mini $0.39。上限總和寫成 $34.50，但三列相加是 1.50 + 30.10 + 2.50 = **$34.10**。「Claude 約 $13」沒有算到 Sonnet 裁判，它走 BYOK，扣的是 Claude credit。指南也沒有寫出 OpenRouter credit 的總額。修法：表格依 credit 分兩欄（見下方成本表）。 |
| L3 | `RUN-S2.md:71`；`PLAN.md:417` | deepseek 的估計 $0.70 用指南自己的方法重算不出來。依 `measure` 牌價和 S1 實際 token，`batch submit` 會印出約 **$0.17**（預演印出 `about $0.1659`）。上限 $1.10 是對的。修法：估計改為約 $0.20。 |
| L4 | `batch.py:686-692` | Opus 的印出估計沿用 deepseek 的 completion token，沒有加 reasoning：印出約 $4.02，上限約 $12.78；指南是 $10 與 $19。印出值較低，不會誤觸「超過上限」的規則，但指南應該先說明「印出值會低於本表」。 |
| L5 | `provenance.py:688-737`；`batch.py:876-1050` | `is_byok`、provider 子句只在 `score`／`compare-levers` 時檢查，`batch fetch` 只記錄不檢查。步驟 6 四個 arm 平行送出，路由錯了要等全部花完才會發現。修法：`fetch` 結束時，按 arm 印出 `is_byok` 或 provider 不符的筆數。 |
| L6 | `provenance.py:799-800` | 被 `render` 拒絕的計費紀錄（outcome error）不跑 target 子句，所以路由錯又 render 失敗的那筆不會被標出。修法：凡有 `replay` 區塊的紀錄都跑 target 子句。 |
| L7 | `RUN-S2.md:139` | 步驟 1 寫「每個測試都要過」，但 snippet 一跑，`test_the_fill_snippet_inserts_the_draft_and_fills_the_corpus` 就會 skip（預演：22 passed、1 skipped，訊息 `RUN-S2.md step 1 has run`）。步驟 4.2 有寫這個 skip，步驟 1 沒寫。修法：步驟 1 也寫「22 passed、1 skipped」。 |
| L8 | 全指南 | 沒有 `PYTHONUTF8=1`。S1 每個指令都帶它（`EXPERIMENT-S1.md:130`，#84）；這台機器 stdout 是 cp950，2.4 的片段與計數片段遇到非 ASCII 的 `error` 字串可能拋 `UnicodeEncodeError`。預演在 Git Bash 下沒有碰到。修法：每個指令前加 `PYTHONUTF8=1`。 |
| L9 | 分支 `claude/peaceful-robinson-2e31dd`（`f3af6ee3`） | 一個舊分支已經把 `PREREGISTRATION_S2` 加進 `thresholds.py`（我已確認該分支存在於 origin）。它若被合併，`git log -S --reverse`（`gitcheck.py:108`）會以那個 commit 為常數定日期，D-73 會拒絕 run。修法：刪掉這個分支或加註。 |
| L10 | `lever_comparison.py:1700-1712` | `reader_comparison` 的 readers 列用共同母體，母體包含 Opus（描述性 arm）。Opus 有一題失敗，deepseek、Haiku、Sonnet 的成本列也會少掉那一題。pairs 各有自己的母體，所以 Holm 的輸入不受影響。修法：候選人的列不計描述性 arm，或在指南註明。 |
| L11 | `lever_comparison.py:1645` | `per_answered_usd` 的分母是 5 個 replicate 中可用答案的數量，不是題數。排序不受影響，只要改措辭。 |
| L12 | `answer_judge.py:94-100, 106-109` | gpt-4o-mini 沒有 provider routing（OpenRouter 預設可 fallback，扣 OpenRouter credit，金額小）。Sonnet 裁判送 `between_tools`，但沒有 `reasoning_tokens` 檢查；若 pilot 顯示 OpenRouter 丟掉 `between_tools`，裁判會思考，花費會高於估計。7.1 應註明這一點。 |
| L13 | `RUN-S2.md:166, 288` | 「先讀成本估算行」做不到：估算在同一個指令裡印出，接著立刻送出（`batch.py:776-777`）。改成「印出時就讀」。 |
| L14 | `RUN-S2.md:265-267` | 4.3 說在 run lane 自己的分支上 commit，但規則要求 main checkout、在 `main` 上，中間缺了切分支、開 PR、切回的步驟。另外，步驟 1 會把 CRLF 的 `thresholds.py` 和 corpus 寫成 LF（預演 commit 時 git 有警告）。D-73 比對的是 AST，所以無害。 |
| L15 | `RUN-S2.md:37`；`batch_client.py:364-372` | native Sonnet 扣的是 `ANTHROPIC_API_KEY` 所屬的帳戶。指南沒說這把 key 必須屬於有 $200 credit 的那個 org。 |
| L16 | `answer_judge.py`（`_report`） | 用 cache 重跑會用「0 calls、$0」覆寫 `answer-judge.json` 的 `estimate` 欄位，第一次的估計就看不到了。這只影響外觀；執行報告應記下第一次的估算行。 |
| L17 | `lever-comparison.json` | null guard 的欄位名稱是 `n_heldout_null`，但 dev run 用的是 dev nulls（S1 也有同樣的外觀問題，audit-s1b S1-5）。 |
| L18 | `PLAN.md:487` | BYOK 費用（列價的 5%，扣 OpenRouter credit，每月有 $25,000 免費額度）只寫在 PLAN，指南沒提。在額度內實際上是 $0；若不在額度內，約 $1.4，上限約 $3.4。我無法離線確認額度。 |

## 免費預演（第二部分）

**環境**
- 我在 scratchpad 裡 `git clone`（`core.longpaths=true`）出 `7aa4c50c`。run 目錄放在 clone 的 `scratchruns/`，不在 `eval/runs/` 底下。clone 用的 `.git/info/exclude` 是預演自己的設定。
- `pack`／`render` 直接執行 main checkout 已 build 的 `engine/target/release/generate_from_context.exe`，只讀不寫。它在 17:03 build，最後一個 engine commit 是 16:08（`a72ef8d5`），所以是最新的；`render` 會依 engine 的規則驗證答案。
- 打樁的位置是 **HTTP 層**：`batch_client.httpx.post/get` 換成假的 OpenRouter batch 端點和 Anthropic Message Batches 端點，`answer_judge.openrouter_transport` 換成假 transport。所以真的 `OpenRouterBatchClient`、`AnthropicBatchClient`、`_openrouter_head`、`openrouter_output`、`anthropic_output` 都有跑到。
- 假答案取自 S1 勝出 arm 各題的答案，並在 5% 的 replicate 改成「Insufficient information」當雜訊。
- API key 用的是假值，`sk-fake`。沒有任何網路呼叫。
- driver：`…\scratchpad\reh\driver.py`。

| 步驟 | 結果 |
|---|---|
| 1 填入片段 | 照原文執行成功；`test_s2_preregistration` 與 `test_s2_run_guide` 22 passed、1 skipped（L7）；`ruff` 對 `thresholds.py` 貼上前後都是 10 個 E501，沒有新增 finding。 |
| 2.1 `replay-init --pilot` | 搬入 100 筆紀錄與 100 列 export；計數片段印出 `small/hybrid+rerank+metadata success 100`。 |
| 2.2 submit ×4（`--limit 5`） | Haiku、Sonnet、Opus 各 25 筆，`custom_id` 為 `<qid>_r1..r5`。batch 層和 body 都 pin `{"only":["anthropic"],"allow_fallbacks":false}`。Haiku 送 `reasoning: {enabled:false}`，Sonnet 送 `thinking`，Opus 送 `reasoning: {effort: low}`。**deepseek 被 B1 拒絕**（exit 1）；我在 driver 裡繞過 B1 之後，20 筆（r2-r5）順利送出。 |
| 2.3 fetch | 95 筆 success，0 pending。第一輪我的假答案沒有引用 evidence，真的 `render` 判它們為 error（`answer basis 'retrieval' requires at least one cited evidence ID`），表示 render 的驗證有作用。改正假答案後重跑。 |
| 2.4 出處片段 | 每個 reader 25 筆：model 正確、`Anthropic`、`True`、`0`；deepseek 20 筆：`deepseek/deepseek-v4-flash-0731`、`Wafer`、`False`、`0`。 |
| 2.5 replay 子句（常數未 commit） | `0 replay clause failure(s)`。**反向測試**：Claude 的 `is_byok` 為 False 或 None 時，每筆都有 `is_byok … expected True` 失敗；deepseek 的 provider 為 `WaferAI` 時，出現 `provider 'WaferAI', expected the pinned 'wafer'`；Claude 的 provider 為 `Amazon Bedrock` 時也失敗。fail-closed 成立，但要到 score 時才會發現（L5）。 |
| 3 native Sonnet 備案 | 依步驟 3.1 改常數（未 commit），開新 pilot，`--limit 2`：送往 `api.anthropic.com/v1/messages/batches`，`params` 有 `thinking: between_tools`、`output_config`，沒有 temperature；fetch 經 `results_url` 取回結果，子句 0 失敗。 |
| 4 凍結 | 改 status 行、刪 corpus 的 DRAFT 註解，在 clone 裡 commit。測試 22 passed、1 skipped（就是指南說的那一個）。 |
| 5 `replay-init`（run of record） | 搬入 100 筆。**拒絕檢查**：換別的 arm 被拒（`corpus … does not list the carried arm(s)`）；`eval/src/lancet_eval` 有改動時，`replay-init` 與 `batch submit` 都被 D-73 拒絕（`refused before any paid call`）；run of record 帶 `--limit` 被拒。 |
| 6 submit ×4、fetch、計數 | reader 各 500 筆，deepseek 400 筆（繞過 B1 後），印出的估計：Haiku $0.1005、Sonnet $2.0101、Opus $4.0203、deepseek $0.1659。fetch 後 1,900 筆 success；計數四個 arm 都是 500。`--retry-errors` 只在 D-73 拒絕的路徑上跑過，沒有真的重送錯誤的 request。 |
| 7 `score --no-judge`、`compare-levers` | 兩者都成功；`score` 在沒有 `data/` store 的 clone 裡也能跑。`lever-comparison.json` 的內容：family 列有 `raw_p`（sign-flip）、`paired_t_p`，bootstrap CI；null guard 計 50 對答案、`min_pairs` 40；`reader_comparison.groups[0].pairs` 有全部 6 對（含 Opus），各帶 `raw_p`；readers 列有 `n_answers` 450、`cost.per_answered_usd`、`batch_spend`，deepseek 的價格來源是 `measure.GENERATION_LIST_*`（P1）。 |
| 7.1 `judge-answers` | `--estimate-only` 只印估算、不寫檔。沒有 key 時，印出估算後被拒。正式執行：gpt-4o-mini 104 次（沒有 `provider`），Sonnet 104 次（`only: anthropic`），寫出 `answer-judge.json`，含 primary 與兩個裁判在各 arm 的比率（每 arm n = 450）和 `disagreements`。用 cache 重跑：0 次呼叫。 |

**預演沒涵蓋的（沒有免費途徑；都留給 pilot，指南步驟 3 已涵蓋）**
- OpenRouter 和 Anthropic 是否真的接受這些請求：#108 的 schema、batch 層 pin、`between_tools` 能否透過、真實的 `is_byok`／provider 名稱，以及 deepseek 在 batch 裡是否真的走 wafer/us 並受 `max_price` 限制（B1 的第二個問題）。
- D-275 的 Holm 與 step-up 是手算的，沒有程式可以預演。
- 步驟 0 的 build 沒有跑，因為 bin 已經存在且是最新的。
- 步驟 8 只是文件，沒有預演。

## 成本（依 credit 分開；token 用指南的 3,500/300，上限 8,692/2,048）

| 步驟 | Claude credit 估計 | Claude credit 上限 | OpenRouter credit 估計 | OpenRouter credit 上限 |
|---|---|---|---|---|
| 2 pilot readers（75 筆） | $0.63 | $1.44 | – | – |
| 2 pilot deepseek（20 筆） | – | – | ≈$0.01（印出值），指南 $0.035 | $0.055 |
| 3 native Sonnet 重做 pilot（如需要） | $0.13 | $0.47 | – | – |
| 6 Haiku（500） | $0.13 | $0.47 | – | – |
| 6 Sonnet（500） | $2.50 | $9.47 | – | – |
| 6 Opus（500） | $10.00 | $18.93 | – | – |
| 6 deepseek r2-r5（400） | – | – | ≈$0.17（印出值），指南 $0.70 | $1.10 |
| 7.1 Sonnet 裁判（sync 全價，≤1,800） | ≤$2.21 | $6.31 | – | – |
| 7.1 gpt-4o-mini 裁判（≤1,800） | – | – | ≤$0.14 | $0.39 |
| BYOK 費用 | – | – | 在免費額度內約 $0 | 同左 |
| **合計** | **約 $15.5**（native 另加 $0.13） | **約 $36.6** | **約 $0.3-0.9** | **約 $1.55** |

- Claude credit 遠低於 $200。
- OpenRouter credit（$7.6）的上限約 $1.55，餘裕足夠。只有 B2（Sonnet 裁判脫離 BYOK，+$6.31）會讓它超過；如果 BYOK 費用不在免費額度內，再加約 $3.4。
- 用 S1 的實際 token 算（2,536/297），reader 的金額會再低約 20%（印出值：Haiku $0.10、Sonnet $2.01、Opus $4.02，Opus 未含 reasoning）。

## 查過、沒問題的

- **指令與旗標**：`replay-init`（`cli.py:825-863`）、`batch submit/fetch`（`:901-1001`）、`score --no-judge`、`compare-levers --run`、`judge-answers --run/--estimate-only`（`:1127-1160`）都存在，預演也全部跑過。`--limit` 只限 pilot 使用（`batch.py:267-274, 727`）。`judge-answers` 不需要 D-73 或乾淨的工作樹。
- **片段**：步驟 1 的三個 replace 字串都存在（`thresholds.py:9, 11, 814`）；2.4、2.5 和計數片段引用的名稱與簽章都存在，預演實際跑過。
- **常數對型別與 D-274/275/276**：
  - 草稿欄位符合 `ReplayStagePreRegistration`（`thresholds.py:559-614`），`REPLICATE_TEST` 一致，`replicates > 1` 搭配別的檢定會被拒（`:592-596`）。
  - D-274：一題只有在兩個 arm 的 5 個答案都 ok 時才進比較（`lever_comparison.py:646-671`）；用 exact sign-flip（`stats.py:128-155`）加 paired t（`:158`）；bootstrap 以題為單位，10,000 次、seed 42；null guard 以 replicate k 配對 replicate k，floor 計題數（`lever_comparison.py:1045-1067`）。
  - D-275：`reader_comparison` 列出每一對候選的 `raw_p`（`:1653-1716`）；成本是 sync 牌價 × 5 個 replicate 的 token。
  - D-276：`gold_contained` 預設 `d276`（`metrics.py:106`），對每個 arm 都適用。
- **D-73 陷阱**：main 的 `thresholds.py` 沒有 `PREREGISTRATION_S2` 這個字面（grep 與 `git log -S` 都是空的，唯一的例外是 L9 的舊分支）。pilot 會跳過 D-73，run of record 的 `replay-init` 和 `batch submit` 都會在付費前檢查（預演確認）。
- **S1→S2 交接**：`EXPERIMENT-S1.md:107-110` 寫明勝出者是 `small/hybrid+rerank+metadata`，run 是 `eval/runs/2026-10-31-s1-multihop_rag_s1_dev`，目錄存在；export 400 列 = 去重後 400 筆 success，勝出 arm 100 筆；S2 corpus 用 placeholder，store 段與 S1 相同；`replay-init` 會檢查 `replay_source_arm` 與完整性（`replay.py:221-266`）。
- **Claude 請求**：
  - 三個 reader 的 body 與 batch 層都 pin `only: ["anthropic"], allow_fallbacks: false`（`reader_request.py:197-198`、`batch_client.py:262-265`），缺 pin 或各 body 不一致時拒送。
  - score 時要求 `is_byok` 為 True 且 provider 為 `Anthropic`（`provenance.py:181-184, 724-737`）；native 要求 `is_byok` 為 None 且 provider 為 `api.anthropic.com`，不得有 thinking block。
  - 例外是 B2 的裁判。
- **deepseek 的 D-271 pin**：送出前有 `deepseek_pin_problem` 和 `configured_pin_problem`（`batch.py:607-663`），比對的是 `config/config.toml` 的 `["wafer/us"]`、0.07、0.45（eval-s1 overlay 不碰 `[openrouter]`）。replicate 的子句要求 `is_byok` False、provider 為 Wafer（不分大小寫）、reasoning 為 0（`provenance.py:688-715`）。
- **既有離線測試**（worktree，`7aa4c50c`）：`test_batch`、`test_replicates`、`test_answer_judge`、`test_reader_comparison`、`test_s2_preregistration`、`test_s2_run_guide`、`test_replay`，**185 passed、1 skipped**。

## 其他

- 每個檔案的變更：無（唯讀）。worktree 的 `git status` 是乾淨的。
- Checks：本 lane 沒有程式變更、沒有 lane test，所以沒跑 `project.md` 的完整 checks；跑過的離線測試見上。
- 衝突：無。
- Review：唯讀稽核，沒跑 code-review。
  - B1：我先在預演中重現，subagent B 也獨立找到。
  - B2：我讀過 `_parse` 確認。
  - B3：我讀過 `.gitignore:71` 和 `gitcheck.py:26` 確認。
  - B4：我用 `gh` 確認 #108 是 OPEN。
  - P1：我讀過 `measure.py`，並看了預演的輸出。
  - L1-L18 大多採用 subagent 的證據；其中 L7、L13、L16、L17 我在預演中親眼看到。
- 已開 issue：無（brief：由 coordinator 開）。
- 已追蹤、不需動作：#108（OPEN，pilot 會驗證，見 B4）。
- repo 與 scratchpad 以外建立的東西：
  - records 資料夾的本報告與 status 檔。
  - subagent A 的 `uv run` 在 worktree 建立了 `eval/.venv`（被 gitignore，不影響 status）。
  - 預演的 clone、venv、run 目錄都在 scratchpad 裡。
  - 沒有安裝任何東西，也沒有建立 GitHub 物件。
- 使用者在本 session 的決定：無（本 session 沒有向使用者提問）。

## 給 coordinator 的問題

1. **B1-B4** 要在 pilot 之前修。B1、B2 是程式（`batch_client.py`、`answer_judge.py`，可以合成一個 lane）；B3、B4 只改 `RUN-S2.md`，L1-L3、L7、L8、L13 可以一起改。B1 的 batch 層 pin 用什麼格式，需要查 OpenRouter batch schema；如果 `max_price` 在 batch 裡無法強制，需要使用者給 D-ID。
2. **P1**：deepseek 的成本價格基準要不要在步驟 4 前請使用者確認？它可能決定 D-275 的起始人選，而且 D-73 不保護它。
3. **L9**：舊分支 `claude/peaceful-robinson-2e31dd` 要不要刪掉？
