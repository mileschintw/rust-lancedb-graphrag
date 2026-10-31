# audit-s012 報告：S0／S1／S2 管線紙上稽核

- 分支：`claude/lane-audit-s012-ce867a`，head 與 `origin/main` 相同（`5aedae9f`，PR #70 已合併）。本 lane 唯讀：無程式變更、無 PR、無付費呼叫、未啟動 live stack、未讀 held-out 題目內容（只數了行數）。
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
- 不依賴 #65、#67、#68、#69（指南所述正確）。

### 給 coordinator 的問題（S0）

- #74、#75 是指南修改（`RUN-S0-S1.md`，PR #70 已合併）：要由 run lane 開跑前順手改，還是另開小 lane？
- 免費彩排（#76）：先做程式改動，或改為付費 3 題彩排？需使用者決定。

## S1（RUN 步驟 1 與 4）

稽核中（subagent 進行中），完成後補上。

## S2

稽核中（subagent 進行中），完成後補上。

## 已開 issue

#74、#75、#76、#77、#78（S0）。

## 使用者在本 session 的決定

無（本 session 未向使用者提問）。
