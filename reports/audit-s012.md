# audit-s012 報告：S0／S1／S2 管線紙上稽核

- 分支：`claude/lane-audit-s012-ce867a`，head 與 `origin/main` 相同（`c69d4868`；S0 段對照 `5aedae9f`，兩者在 S0 路徑無差異）。本 lane 唯讀：無程式變更、無 PR、無付費呼叫、未啟動 live stack、未讀 held-out 題目內容（只數了行數）。
- 稽核對象：`main` @ `5aedae9f`（PR #70 合併後；與 `claude/lane-prereg-s01-73d291` @ `5e7f0232` 在 `eval/src`、`baselines`、`engine/src`、`config` 上無差異）。

## S0（RUN 步驟 2 與 3）——先報

### 結論

S0 的程式路徑在紙上走得通：沒有找到會讓步驟 2、3 的指令崩潰或算錯 S0 讀數的程式錯誤。但**執行指南有兩個缺口應先補**（#74、#75，都只需改指南），另外**原定的免費 `provider_stub` 彩排照現狀跑不起來**（#76）。

建議：先在 `RUN-S0-S1.md` 補上 #74 的 release build 指令與 #75 的筆數檢查，再跑 S0。彩排要嘛先做 #76 的程式改動，要嘛改用真 provider 跑 3 題彩排（幾美分，需使用者同意）。

### 發現（S0）

| # | 檔案:行 | 破壞的 RUN 步驟 | 擋住 | 內容 |
|---|---|---|---|---|
| #74 | `experiments/v1.1/RUN-S0-S1.md:75-78`；`eval/src/lancet_eval/identity.py:63-82`；`parity.py:45-56` | 3.1、3.2、3.3、3.5（S1 的 1.5、4.1-4.4 亦同） | S0（軟性） | 步驟 0 只 build debug；`inspect_lancedb` 與 `generate_from_context` 經 `cargo run --release` 以 1800 秒逾時編譯，而本機冷 release build 約 70-74 分鐘（`docs/testing.md:79`、#56）。3.1 preflight 會因 `index_identity` 失敗（免費）；更糟是 3.3 在付費的 3.2 之後逾時，held-out read 中途停下。修法：步驟 0 加 `cargo build --manifest-path engine/Cargo.toml --locked --release --bin inspect_lancedb --bin generate_from_context`。 |
| #75 | `eval/src/lancet_eval/cli.py:655-669`；`journal.py:298-299`；`RUN-S0-S1.md:16` | 3.2、3.5 → 3.6 | S0（結果錯誤風險） | (1) `PREREGISTRATION_S0` 有 rerank tripwire；觸發時 `run` 印黃字並 **exit 0**，指南只在非零時停，會帶著半套 Lancet arm 進 3.3-3.6。(2) `run-external` 無重試，錯誤紀錄被 `load_done` 視為完成、resume 不重讀；Lancet arm 有 `--retries 2`，兩 arm 重試預算不對稱。修法：3.2、3.5 後數每 arm 的紀錄數（應各 351）與 error，見 "Drive stopped early" 即停。 |
| #76 | `eval/src/lancet_eval/provider_stub.py:272,312`；`baselines/llamaindex/src/lancet_llamaindex/providers.py:28,31`；`cli.py:98-99` | 彩排（Before and after） | 免費彩排 | stub 沒有 `/rerank`（S0 Lancet arm 每筆都 rerank degrade，5 筆連續即 tripwire 停）；LlamaIndex export 的 embedding／rerank endpoint 寫死 openrouter.ai，無法指向 stub（索引 346 篇約 $0.12，非免費）；也沒有 S0 arm 組合的 rehearsal corpus。 |
| #77 | `cli.py`（`run_benchmark`、`run_external_command`）；`baselines/.../cli.py` | 3.2、3.4、3.5 | 不擋 | D-258 要求 drive 前印成本估算；只有 batch submit（#53）有涵蓋。S0/S1 由指南手算估算補上。 |
| #78 | `baselines/llamaindex/src/lancet_llamaindex/cli.py:67-90` | 3.4 | 不擋 | D-237 held-out read 沒有任何程式計數；LlamaIndex export 讀 held-out 卻不跑 `require_split_gates`（D-73、split hash、role）。在步驟 3 中它排在 3.2 之後，gate 已過一次，故不擋 S0；但單獨或重跑時無 gate。 |

### 查過、沒問題的（S0）

- `multihop_rag_s0_heldout.toml` 與 `PREREGISTRATION_S0`：arm 集合 `{hybrid+rerank+metadata, llamaindex}` 等於 `arms_of(prereg)`，`_enforce_preregistered_arm_set` 通過；split role `heldout`、351 題，`_enforce_split_role` 要求與 split 完全相等。
- `run --arms hybrid+rerank+metadata`：`select_arms` 接受未加前綴的子集，store 為 v1.0；request 帶 `levers=["rerank","evidence_metadata"]`、`disable_graph_context=True`、`disable_default_levers=True`。context export 從 `lancet_eval` 讀（S0 只有一個 store，#65 不影響）。
- preflight：兩 arm 不送 arm canary（`len(arms) > 2` 才送）；corpus-generation probe 用文件標題，不是 held-out 題目；document map 經 `map_corpus` 解析到 `document_map.json`（346 筆）。
- LlamaIndex export：文件為 `documents.subset.jsonl` 346 篇，經 `document_map.json` 對到 Lancet document ID；provider 呼叫有 6 次退避重試；任何一題失敗整個 export 不寫（重跑會重付約 $0.25，可接受）；`pipeline_config.json` 的平面鍵與 `ExternalPipeline` 一致。
- `run-external`：跑 `require_split_gates`、arm 屬於 corpus、export 每列 k=8、pipeline echo 必需鍵；bin 讀 `config/config.toml`（`config.eval.toml` 只改 `lancedb_path`），生成模型、provider 順序、溫度與 Lancet arm 相同；`--stage-cap 100` 不會觸發。
- `score` / `compare-levers`：外部 arm 跳過 chunk-ID 檢索指標（D-250）、外部條款在兩處都檢查；S0 是 held-out role，#68 不影響。
- 步驟 2.1、2.2：不讀 held-out；2.2 的 `multihop_rag_s1_dev` 用 `questions.diag.jsonl`（100 題，dev role）。
- 不依賴 #65、#67、#68、#69（指南所述正確；#65、#67、#69 在稽核期間已關閉）。

### 給 coordinator 的問題（S0）

- #74、#75 是指南修改（`RUN-S0-S1.md`，PR #70 已合併）：要由 run lane 開跑前順手改，還是另開小 lane？
- 免費彩排（#76）：先做程式改動，或改為付費 3 題彩排？需使用者決定。

## S1（RUN 步驟 1 與 4）

對照 `main` @ `c69d4868`（#72 修 #65、#73 修 #67 與 #69，兩者稽核期間已合併）。由 subagent 逐步追蹤，兩個 blocker 我已親自讀碼確認。

### 發現（S1）

| # | 檔案:行 | 破壞的 RUN 步驟 | 擋住 | 內容 |
|---|---|---|---|---|
| #79-1 | `eval/src/lancet_eval/seed.py:486-549`；`gateway/main.go`（`compensateFailedIngest`）；`identity.py:198-205` | 1.4、1.5、4.3、4.4 | S1 | seed 某篇 ingestion 失敗時以新 ID 重傳，gateway 留下 `failed` 列。1.4 的查詢不過濾 status，會印 347 以上，指南叫人停；`index_identity` 也因 `extra_in_pg` 與 "rows not completed" 失敗。約 4,000 次 extraction 中只要一次暫時性失敗就會發生。修法：1.4 加 `status = 'completed'`，並加一步 `lancet-eval identity pg-delete-extras --store eval-s1`。 |
| #79-2 | `RUN-S0-S1.md:342-346` | After the run | 不擋（可重現性） | `document_map.eval-s1.json` 不在 gitignore，卻不在提交清單；`score` 讀它來評 `merged/` 紀錄，換 checkout 就無法重評。 |
| #79-3 | `run.py`（`require_split_gates`，dev role 跳過 D-73）；指南 Rules | 4.2、4.4 | 不擋 | dev role 的 drive 不檢查乾淨樹（D-170），與指南「drive 拒絕髒 `eval/src/`」不符；只有 score 會擋，那時已付費。建議 4 前先看 `git status`；harness shell 也 export `LANCET_ENV`；D-263 snippet 的 JSON 寫法（NaN、CRLF）與 `compare-levers` 不一致。 |
| （已修） | `seed.py:416-424`（舊） | 1.3 | — | seed 到 `corpora/multihop_rag_s1_dev/` 找文件而該目錄不存在；PR #73（已合併）改走 `map_corpus`。不另開 issue。 |
| 併入 #77 | `run.py`、`external_run.py` | 1.3、4.x | 不擋 | seed 與 drive 都不印 D-258 成本估算。cap 程式仍在但 `--stage-cap 100` 不會觸發，符合 D-258 的「stays built」。 |

未開 issue（外觀）：`lever-comparison.md` 參考 arm 仍寫 "hybrid"；`merged/` arm 印 chunk-ID Hits@4 而沒標「不讀」；report.json 的 graph 維度不認得 S1 的 graph arm（決策不讀它們）。

### 與已知 issue 的依賴（S1）

- #67、#69：PR #73 已合併，步驟 0 的表可更新為已解除；步驟 1.5 的 `store_chunking` 檢查已存在。
- #65：PR #72 已合併；4.5 可直接用 `export-context`，stopgap 不再需要，4.4 的「預期非零 exit」也應不再出現（請 run lane 依新 main 確認）。
- #68：仍開著，4.6、4.7 等它。合併後 gold-chunk 表也要涵蓋 dev 題目（subagent 未開該檔，未驗證）。

### 查過、沒問題的（S1）

Atlas env `eval-s1` 與其 schema 檔；engine overlay `./data/lancedb-eval-s1`；gateway schema 由 env URL 決定，未設時 fail closed；`load_settings(store=...)` 與分 store 的 document map；`small/`、`merged/` 標籤在解析、子集、journal key、raw-events 目錄、score 的分 store map、兩個 prereg arm 集、null guard、分 store preflight canary 都接受；兩次 drive 寫同一 journal 的 header 與 resume key 不衝突；`.gitignore` 例外涵蓋 S1 run 目錄；4.5、4.7 的 Python snippet 函式名稱與簽名都存在；S1 不讀 held-out 題目內容（D-237）。

## S2（`replay-init` → rewrite → batch → `render` → `score` / `compare-levers`）

對照 `main` @ `c69d4868`。#51、#52、#54 已合併；#50（render）與 #53（batch）未建，只稽核它們必須接上的介面。subagent 追蹤；F1、F4、F5、F6 與 `correlation_id` 檢查我已讀碼確認。

### 發現（S2）

| # | 檔案:行 | 破壞的步驟 | 擋住 | 內容 |
|---|---|---|---|---|
| #80 | `eval/src/lancet_eval/replay.py:214-224`；`cli.py`（`replay_init_command`，無 `--corpus`） | replay-init → score | S2 | 新 journal 的 header 與每筆搬來的紀錄都寫 S1 的 corpus；`PREREGISTRATION_S1` 沒宣告 reader，reader 紀錄全被拒；手改 header 也會因 corpus 不一致使報告 partial、不寫 `report.json`。測試用同一 corpus 所以沒抓到。同 issue 附：replay-init 不檢查來源 run 的 role，可把 S0 held-out run 送進 Claude（D-237）。 |
| #53 留言 | `context_export.py:349-360` | batch fetch → score | S2（#53 介面） | reader 的 export 列等於 base 列，帶 base 的 `correlation_id`，所以 reader 紀錄也必須帶同一個，否則 `require_export_rows` 拒收。base 為 error 的題目須寫 error 紀錄，否則 run 不完整。另列 levers、usage、render 失敗仍計費等要求。 |
| #81 | `lever_comparison.py:1359-1367`；`measure.py:60-72` | compare-levers（成本） | 結果錯誤 | deepseek 以預算上限 $0.14/M input 計價，列價為 $0.0137（約 10 倍）；prereg 也無法登錄 deepseek 價格。以 v1.0 dev 平均 token 算，Haiku 看似便宜 45%，用列價則 deepseek 稍便宜：D-245 的成本條件會反過來。另：per-reader `answer_usable` 列的題目集合不同（deepseek 排除 rerank degrade，reader 不排除），差距與 D-252 的 2 點門檻同量級；成對列正確。 |
| #82 | `provenance.py:157,222-234` | batch fetch → score | Sonnet fallback | D-255/D-260 的原生 Anthropic fallback 沒有 `provider`、`is_byok`，`reasoning_tokens == 0` 檢查形同虛設；另沒有任何條款比對 reader 收到的 prompt 與 deepseek 的 `assembled_prompt`。 |
| #49 留言 | `replay.py:88-92`；`gitcheck._assigned_value` | Opus 條件 arm | 條件步驟 | D-252 的 Opus 條件 arm 沒有可行路徑（先登錄不跑 → 不完整；後加 → D-73 拒；新 run 不能搬 reader arm），只能重買 Haiku/Sonnet（約 $0.5）。D-73 只比對常數本身的賦值，reader 表要寫在常數內。 |

### 查過、沒問題的（S2）

`small/`、`merged/` 加 `@reader` 的標籤在各層解析正確；#51 的 request rewrite 與 engine body 一致、只動宣告欄位；九條 replay 條款皆 zero tolerance；reader arm 不進 Hits@4、MRR 與 judge；raw-events 目錄名處理新標籤；S2 路徑不碰 Postgres 或 store；D-73 的時間與乾淨樹檢查有效；S2 路徑沒有中途停的 cap（D-258）。

### 與已知 issue 的依賴（S2）

#68 未合併前 S2 完全無法評分；#65（已由 #72 修）影響 replay-init 需要的 S1 export；#50、#53 未建。

## 提案（不實作）：S1/S2 離線端到端 fixture 測試

目的：在付費前用一個 pytest 走完整條管線，抓到本次這類「各段單測都過、串起來才壞」的問題（#80、#53 介面、#75）。

- **位置**：`eval/tests/test_pipeline_e2e.py`，放 slow tier（`@pytest.mark.slow`），不碰網路。
- **Fixture**：一個小的假 corpus 組（例如 6 題 dev：5 G、1 null），兩個 corpus config：`s1_fixture`（四個 `small/`、`merged/` arm，role dev，token 指向測試用 prereg）與 `s2_fixture`（carried arm 加兩個 `@reader` arm）。gateway 用 `httpx.MockTransport` 回放固定 SSE（沿用 `levers_fixture` 的做法），`CheckpointSource` 用記憶體實作，含兩個 store 的 checkpoint，`correlation_id` 為真值；bin 用假 `BinRunner`；batch 與 render 用假 runner，回傳帶 `replay` 區塊的結果。
- **步驟**：`seed`（假 gateway，檢查 `merged` store 收到 `chunk_strategy=structure-merge, 256, 25`）→ `drive --arms small/...` 與 `--arms merged/...` 進同一 journal → `export-context`（兩 store）→ `score` → `compare-levers`（S1 兩個讀數）→ `replay-init --source-run`（新 S2 corpus）→ 假 batch 寫 reader 紀錄 → `score` → `compare-levers`（reader 比較、成本）。
- **斷言**：每一步 exit 與檔案存在；`report.json` 非 partial；reader 列與成對列數量；base error 題目在 reader arm 有 error 紀錄；identity 讀到對的 schema。
- **xfail**：#65、#67、#68 已在測試中以 `pytest.mark.xfail(strict=True, reason="#68")` 標註對應步驟。#65、#67 已合併，這兩步應直接要求通過；#68 合併前，score/compare-levers 步驟 xfail。另外 #80、#53 未修前，S2 段也 xfail（strict），修好後 xfail 轉 XPASS 會提醒拿掉標記。
- **S0 版**：同一檔案可加 S0 形狀（`hybrid+rerank+metadata` + `llamaindex`，held-out role 的假 split），涵蓋 `run` → `run-external` → `score` → `compare-levers`，並斷言 tripwire 停下時 CLI 的 exit 行為（#75）。

## 已開 issue

- S0：#74（release build 逾時）、#75（半套 arm 卻 exit 0）、#76（免費 stub 彩排無法執行）、#77（D-258 未印估算）、#78（D-237 未計數，export 無 split gate）。
- S1：#79（seed 失敗列擋住 identity、S1 document map 未提交、指南措辭）。
- S2：#80（replay-init 寫入 S1 corpus）、#81（reader 價格與母體）、#82（replay 條款）。
- 留言：#53（batch 介面要求）、#49（Opus 條件 arm、D-73 寫法）、#78（replay-init 的 held-out 路徑）。

## 其他

- 每項變更：無（唯讀 lane；repo 未改動、無 commit、無 PR body）。
- Checks 與 lane tests：本 lane 無 lane test；未執行 `project.md` 的 checks（沒有程式變更）。
- 衝突：無。
- Review：唯讀稽核，未跑 code-review；subagent 的每個 blocker 我都親自讀碼確認，未能確認的未開 issue（gold-chunk 表是否涵蓋 dev 題目，未開檔驗證）。
- repo 與 scratchpad 外建立的東西：GitHub issue #74-#82 與三則留言；無安裝。
- 稽核期間 `main` 前進：PR #70、#72、#73 已合併；#65、#67、#69 已關閉，#68 仍開。

## 使用者在本 session 的決定

無（本 session 未向使用者提問）。
