# audit-s1a 報告：S1 store build（RUN-S0-S1.md 步驟 1）紙上稽核

- 分支：`claude/lane-audit-s1a-59b000`，head = `origin/main` = `d3c01d2a`（PR #96、#97 合併後）。本 lane 唯讀：無程式變更、無 commit、無 PR、無 PR body、無付費呼叫、未啟動 live stack、未寫任何 store、未讀 held-out 題目。
- 唯一執行的東西：在 scratchpad 用 tiktoken o200k 離線模擬 `structure-merge` 256/25 切 `documents.subset.jsonl`（346 篇文件本文，非題目），以核對呼叫數。免費、只讀。

## 結論

**通過：沒有擋住 S1 store build 的問題。** 步驟 1 的每個指令與旗標都在 main 上存在且行為與指南一致；成本估算經重算成立（約 $1.9-2.9，上限約 $11）；S1 路徑在程式層面不會寫 `data/lancedb-eval` 或 `lancet_eval`。#74、#75 已在指南中用到該用的地方。

以下四項不擋，但建議開跑前處理（前兩項都只是 run lane 的操作，不需改碼）：

1. 步驟 1.2 直接執行預先 build 好的 `./engine/target/debug/engine`，而主 checkout 的 binary 比 main 舊：**pull 之後必須重跑步驟 0 的兩個 cargo build**（A1）。
2. 主 checkout 有未追蹤檔 `scratch_new.txt`，步驟 0 的「`git status` 乾淨」會停下（A5）。
3. seed 寫入前沒有任何即時檢查確認 8080 上跑的是 S1 stack；建議加一個免費的開跑前檢查（A2）。
4. 上限 $11 未計 extraction 重試（A3）。

## 發現

| # | 檔案:行 | 影響的步驟 | 擋住 S1 | 內容 |
|---|---|---|---|---|
| A1 | `experiments/v1.1/RUN-S0-S1.md:93-98,126-130`；`D:\Repos\lancet\engine\target\debug\engine.exe`（2026-10-31 01:05） | 1.2、1.3 | 不擋（前提：重做步驟 0 build） | 步驟 1.2 直接執行 `./engine/target/debug/engine`，不經 `cargo run`，所以舊 binary 不會被重新編譯就直接用。主 checkout 的 `engine.exe` 建於 01:05，之後 main 合入的 engine 變更有 `engine/src/generation/openrouter.rs`（+304/-…，#50 render mode）、`engine/Cargo.toml`（profile）、`ingest.rs`（僅測試）。release 的 `inspect_lancedb.exe`、`generate_from_context.exe` 也是 01:08-01:09 的版本。指南寫「build the engine once」，若 run lane 視步驟 0 為 S0 時已做過而跳過，S1 store 會由非 main 版本的 engine 建出，且無任何檢查會發現。建議：開跑步驟 1 前，在 pull 後重跑步驟 0 的 `cargo build --locked` 與 release 的兩個 bin（sccache 下應為增量）。 |
| A2 | `eval/src/lancet_eval/seed.py:85-102,436-449`；`config.py:129-175`；`engine/src/main.rs:72-79` | 1.3 | 不擋（風險：寫壞 v1.0 store） | `seed --store eval-s1` 的隔離檢查（`assert_store_target`）只看 harness 自己的 settings、`LANCET_ENV` 與 overlay 檔，不探測 8080 上實際的 gateway/engine 用哪個 store。若 v1.0 stack 仍在跑（或 engine shell 設了 `LANCET_ENGINE__LANCEDB_PATH`），seed 會把 346 篇以 256/25 切法寫進 `data/lancedb-eval` 與 `lancet_eval`，要到 1.4 查詢或 1.5 identity 才會發現，而那時 v1.0 store 已被改動（它不便宜重建）。指南的「只能同時跑一個 stack」與 port 衝突讓這在流程上不太會發生。建議在 1.2 之後、1.3 之前加一個免費檢查：S1 engine 啟動 log 的 `BM25 snapshot built` 行必須是 `document_count=0`、`graph_entities=0`（全新 S1 store；v1.0 store 會是數千）。未開 issue（流程已防；是否補指南由 coordinator 決定）。 |
| A3 | `engine/src/graph/extraction.rs:80-149`；`seed.py:528-588`；`RUN-S0-S1.md:137-140` | 1.3（成本） | 不擋 | 上限「每次呼叫都打到 2,048 output 上限一次」約 $11 成立，但未計重試：每個 chunk 的 extraction 最多 3 次嘗試（output 被截斷導致 JSON 驗證失敗也會重試），seed 對失敗文件最多重傳 5 次並重新 extract 該文件所有 chunk。極端最壞情況會超過 $11。指南對 drive 已有同樣的但書（`RUN-S0-S1.md:66-68`），步驟 1 沒有。建議在 1.3 估算後加一句。 |
| A4 | `eval/src/lancet_eval/cli.py:320-343`；#77 | 1.3 | 不擋 | seed（S1 最大的一筆花費）不印 D-258 成本估算；#77 的範圍是 `run`、`run-external` 與 LlamaIndex export，不含 seed，lane 77 的 brief 也沒提 seed。指南步驟 1.3 的手算估算補上了這個缺口，所以照指南跑沒問題。D-258 的「不設中途上限」與 seed 一致（seed 無 cap）。未開 issue、未留言（避免改動 lane 77 進行中的範圍）；是否要在 #77 加 seed 由 coordinator 決定。 |
| A5 | `D:\Repos\lancet\scratch_new.txt`（未追蹤，2026-10-29 19:34，998 bytes，內容是一段 ruff 輸出） | 0 → 1 | 不擋（但步驟 0 會停） | 步驟 0 要求 `git status` 乾淨；這個檔會讓它不乾淨。它不在 `eval/src/`，不影響 D-73。是使用者或某個 session 留下的暫存，本 lane 不刪（不是本 lane 的檔）。 |
| A6 | `eval/src/lancet_eval/measure.py:58-78`；`RUN-S0-S1.md:59` | 1.3（成本） | 不擋（估算偏保守） | 指南的 $0.14/M input 是 `GENERATION_INPUT_PRICE_PER_1M`（預算上限）；列價 `GENERATION_LIST_INPUT_PRICE_PER_1M` 是 $0.0137。以列價計，extraction input 約 $0.03，而非 $0.29-0.31。估算因此偏高約 $0.27，對使用者無害。 |

## 成本重算（步驟 1）

- **Chunk 數**：用 o200k 依 `chunk_structure_merge` 的規則（`engine/src/chunker/mod.rs:117-226`：依空行分段，貪婪合併至 256 token，超過 256 的段落切 256/25 視窗；這批文件沒有 markdown 標題）模擬：**3,953 個 chunk，平均 206 token**，本文 812,734 token、chunk 總計 814,974 token，82 個段落超過 256。指南的「約 4,000 次呼叫、平均約 200 token」成立。
- **Extraction 請求**（`engine/src/graph/extraction.rs:190-253`）：每 chunk 一次呼叫，system 約 45 token、user 前綴約 8 token、chunk 206 token、strict JSON schema 約 250 token（若供應商計入），合計約 500-550 token；`reasoning: none`；`max_completion_tokens` = `config/config.toml` 的 `max_output_tokens = 2048`；schema 上限 32 個 entity、64 個 relation，最大輸出會碰到 2,048。
- **價格**（`measure.py:72-95`）：deepseek $0.14/M input（上限價；列價 $0.0137）、$1.28/M output；embedding $0.12/M。與指南表格一致。
- **估算**：
  - Embedding：0.815 M token ≈ **$0.10**，加上 entity 名稱 embedding（`ingest.rs:1234`，量很小）。
  - Extraction input：3,953 × ~520 ≈ 2.06 M × $0.14 ≈ **$0.29**（列價約 $0.03）。
  - Extraction output：3,953 × 300-500 ≈ 1.19-1.98 M × $1.28 ≈ **$1.52-2.53**。
  - 其他：`record_index_generation` 的一次 `/rag/query` 與 1.5 preflight（3 個 canary × 2 個 merged arm + 1 個 corpus probe），合計幾美分。
  - **合計約 $1.9-2.9**（指南：約 $2-3）。
- **上限**：3,953 × (2,048 × $1.28 + 520 × $0.14)/M + $0.10 ≈ **$10.8**（指南：約 $11）。不含重試（A3）。

## 查過、沒問題的

- **步驟 1.1 Atlas（含 plan.md › Waiting for the user to be present 的延後步驟）**：`gateway/atlas.hcl` 有 `env "eval-s1"`，URL 預設 `search_path=lancet_eval_s1`，src `db/schema.eval-s1.hcl`；把 schema 名正規化後，它與 `schema.eval.hcl` 只差第一行註解，表完全相同，`documents` 有 `status`、`error_message`、`chunk_strategy`、`chunk_size`、`chunk_overlap`。plan.md 的兩行指令與指南 1.1 一字不差。`atlas`（`~/go/bin/atlas`）與 `docker` 都在本機。`CREATE SCHEMA` 必須先做（scope 在 schema 的 URL 不會建 schema），指南順序正確。
- **步驟 1.2 stack**：engine 的 `load_settings`（`engine/src/config.rs:1120-1145`）以 `config/config.<LANCET_ENV>` 疊加；`config` crate 0.15.25 以 placeholder 副檔名處理 `config.eval-s1`，不會誤讀成 `config.toml`；`config.eval-s1.toml` 設 `lancedb_path = "./data/lancedb-eval-s1"`。engine 不連 Postgres（`engine/src/db` 是 LanceDB）。gateway（`gateway/internal/config/config.go:40-90`）綁 `LANCET_GATEWAY__DATABASE_URL`，空值 fail closed；schema 由 URL 的 `search_path` 決定。
- **步驟 1.3 seed**：`seed --corpus --store` 存在；`--store eval-s1` → `S1_STORE`；`assert_store_target` 拒絕 v1.0 的 path 與 schema，也拒絕 `LANCET_ENV` 指向別的 store；`store_chunking_of` 從 `multihop_rag_s1_dev.toml` 的 `[stores.merged]` 送 `structure-merge`、256、25（#67）；gateway 驗證後（`gateway/main.go:441-494`）engine 走 `chunk_structure_merge`（`.txt` 檔，不會被當 JSON 走 fixed-size）。文件從 `map_corpus = "multihop_rag"` 的 `documents.subset.jsonl`（346 行）讀；map 寫到 `eval/corpora/multihop_rag/document_map.eval-s1.json`（`seed.py:268-284`），與指南相符。主 checkout 目前沒有 `data/lancedb-eval-s1`，也沒有舊的 `document_map.eval-s1.json`，所以 seed 不會從舊 map 續跑。
- **步驟 1.4**：兩個 psql 查詢的欄位都存在；`status = 'completed'` 過濾已加（#79）。`identity pg-delete-extras` 的 `--store`、`--corpus`、`--apply`、`--pg-dump` 都存在（`cli.py:407-460`）；`delete_pg_extras`（`identity.py:282-342`）只接受該 store 自己的 schema、拒絕空 allow-list、`--apply` 要求存在且非空的 dump，並以單一 transaction 刪除；failed 列不在 map 裡，所以 dry run 列的正是它們。`pg_dump -n lancet_eval_s1` 只備份 S1 schema。identity 在非 v1.0 store 會跳過被取代的 `failed` 列（`identity.py:153-181`）。
- **步驟 1.5 preflight**：`--store eval-s1` 帶入 `load_settings(store=S1_STORE)`；檢查依序為 `drive_environment`、`store_isolation`、`arm_store`（只取 `merged/` arm）、`index_identity`（`inspect_lancedb --lancedb-path data/lancedb-eval-s1`，經 `cargo run --release`，即步驟 0 build 的 release bin，#74）、`store_chunking`（#67），再加 gateway/engine 可達性、corpus probe、arm canary（3 列 × 2 個 merged arm；dev corpus 用 `PREFLIGHT_RERANK_DEGRADE_HALT`，不用 prereg 的值），沒有 graph node 下限，不會因 merged store 的圖不同而失敗。
- **不碰 v1.0 store**：步驟 1 的每個指令在程式層面都只指向 `data/lancedb-eval-s1` 與 `lancet_eval_s1`（`config.py:129-175` 拒絕 v1.0 path 與 schema；`delete_pg_extras` 拒絕其他 schema；Atlas env 與 psql 只帶 `lancet_eval_s1`）。唯一的缺口是 seed 不能確認 live stack 是哪一個（A2）。
- **Pre-registration 常數**：`thresholds.py:640-760` 的 `PREREGISTRATION_S1` 與 `PREREGISTRATION_S1_MERGED_GRAPH` 和 `EXPERIMENT-S1.md` 一致：reference arm、兩個 decisional arm 與一個 descriptive arm、null guard margin 0.10 與 pair fraction 0.80、complete-case floor 0.80、bootstrap 10,000 與 seed 42、SC-2 0.025、tripwire 0.20 / 50 / 5、D-241/242/251/252/259/262-264 的出處。步驟 1 本身只用到 store 的切法：`multihop_rag_s1_dev.toml` 的 `[stores.merged]` = `structure-merge`、256、25 與 `[stores.small]` = `structure-aware`、500、50，符合 `EXPERIMENT-S1.md:19-22` 的表與 D-251；split role `dev`、100 題，步驟 1 不讀 held-out。
- **#74、#75 在步驟 1 的使用**：#74 的 release bin build 在步驟 0（`RUN-S0-S1.md:100-109`），步驟 1.5 的 `index_identity` 用到它，指南 101 行把 1.5 列在用途裡。#75 的「每次 drive 後數筆數」只適用於 drive（3.2、3.5、4.2、4.4）；步驟 1 沒有 drive，對應的完整性檢查是 1.4 的「346 筆 completed、一種切法」與 failed 列處理，指南已寫。
- **步驟 0 的 blocker 表**：#65、#67、#68、#69 都已關閉（#79 也已關）。

## 其他

- 每項變更：無。
- Checks 與 lane tests：本 lane 無 lane test；未跑 `project.md` 的 checks（沒有程式變更）。
- 衝突：無。
- Review：唯讀稽核，未跑 code-review；每項發現都由我親自讀碼確認，沒有用 subagent。
- 已開 issue：無（沒有 blocker）。
- 已追蹤、不需動作：#77（D-258 成本估算；不含 seed，見 A4）。
- repo 與 scratchpad 外建立的東西：無。`uv run` 在本 worktree 建了 `eval/.venv`（已 gitignore，留在 worktree 內）。
- 使用者在本 session 的決定：無（本 session 未向使用者提問）。

## 給 coordinator 的問題

- A1、A5：開跑前要提醒 run lane 重跑步驟 0 的 build，並請使用者處理 `scratch_new.txt`。
- A2、A3：要不要在 `RUN-S0-S1.md` 補「1.2 後確認 `document_count=0`」與「上限不含重試」兩句？lane 74 已合併，這要另開小修。
