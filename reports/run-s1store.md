# run-s1store 報告：S1 store build（完成）

- 位置：主 checkout `D:\Repos\lancet`，`main` @ `971094f5`（= `origin/main`；seed 時是 `aedd4723`，含 PR #119 / #118）。沒有 lane 分支、沒有 commit、沒有 PR、沒有 PR body。
- 狀態：**done**。S1 store 建好，1.4 與 1.5 preflight 全部通過（1.5 在 #120 / PR #121 合併後重跑，`main` @ `971094f5`）。stack 已停。步驟 4（付費 S1 drive）要等使用者另外同意。
- 未讀 held-out。沒碰 `data/lancedb-eval`、`lancet_eval` schema 或 `config/`。

## 使用者在本 session 的決定（原話）

- `scratch_new.txt`：「刪除 (Recommended)」→ 已從主 checkout 刪除（未追蹤的 ruff 輸出，998 bytes）。
- 步驟 1（約 $1.9-2.9，上限約 $10.8，不含 extraction 重試）：「開始步驟 1」。
- 經 coordinator 轉達：額外免費檢查（重試率、供應商）：「照做 (Recommended)」。
- 經 coordinator 轉達（2026-10-31）：「停、修、重建 (Recommended)」→ 中止 seed，等 #118 合併後重建。重建（清掉 `data/lancedb-eval-s1`、`lancet_eval_s1` 內容與 `document_map.eval-s1.json`）已核准；付費 seed 前要用新估算再問使用者一次。

## 各步驟（第一次嘗試，d943d558）

| 步驟 | 指令 | exit | 結果 |
|---|---|---|---|
| 0 pull | `git fetch` 後 `main` 已 = `origin/main` `d943d558` | 0 | 不需 ff |
| 0 clean | 刪 `scratch_new.txt`；`git status --short` | 0 | 乾淨 |
| 0 debug build | `CARGO_BUILD_JOBS=2 cargo build --manifest-path engine/Cargo.toml --locked` | 0 | `engine.exe` 15:10 |
| 0 release build | `CARGO_BUILD_JOBS=2 cargo build --manifest-path engine/Cargo.toml --locked --release --bin inspect_lancedb --bin generate_from_context` | 0 | 兩個 bin 15:12 |
| 1.1 | `docker exec lancet-postgres psql ... "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"` | 0 | `CREATE SCHEMA` |
| 1.1 | `(cd gateway && atlas schema apply --env eval-s1 --auto-approve)` | 0 | 1 migration、7 statements；`lancet_eval_s1` 4 張表 |
| 1.2 engine | `LANCET_ENV=eval-s1 ./engine/target/debug/engine` | （背景，後來停止） | 新建 `./data/lancedb-eval-s1`；serving `127.0.0.1:50051` |
| 1.2 A2 檢查 | engine 啟動 log | — | **通過**：`BM25 snapshot built document_count=0 ... graph_entities=0 doc_meta_documents=0` |
| 1.2 gateway | `(cd gateway && LANCET_ENV=eval-s1 LANCET_GATEWAY__DATABASE_URL='...search_path=lancet_eval_s1' go run .)` | （背景，後來停止） | `gateway listening 127.0.0.1:8080` |
| 1.3 seed | `LANCET_ENV=eval-s1 PYTHONUTF8=1 uv run --project eval lancet-eval seed --corpus multihop_rag_s1_dev --store eval-s1` | 依使用者決定中斷（15:14 開始，約 15:56 停） | 見下 |
| 1.4、1.5 | — | 未跑 | 中止 |

stack 已停（8080、50051 已釋放）。OTel 匯出錯誤（4317 沒有 collector）無害。

## 重建（`GO rebuild`，2026-10-31）

| 步驟 | 指令 | exit | 結果 |
|---|---|---|---|
| 0 pull | `git -C D:/Repos/lancet pull --ff-only` | 0 | `d943d558` → `aedd4723`（PR #119，11 檔） |
| 0 clean | `git status --short` | 0 | 只有待清的 `document_map.eval-s1.json`；`scratch_new.txt` 已不存在 |
| 0 debug build | `CARGO_BUILD_JOBS=2 cargo build --manifest-path engine/Cargo.toml --locked` | 0 | 48 秒，`engine.exe` 17:02 |
| 0 release build | `CARGO_BUILD_JOBS=2 cargo build --manifest-path engine/Cargo.toml --locked --release --bin inspect_lancedb --bin generate_from_context` | 0 | 60 秒，兩個 bin 17:03 |
| 清除 | `docker exec lancet-postgres psql -U postgres -d lancet -c "DROP SCHEMA lancet_eval_s1 CASCADE;"` | 0 | 刪 4 張表（documents 118 completed + 1 queued、users、workflow_checkpoints、document_reconciliation_intents） |
| 清除 | `rm -rf data/lancedb-eval-s1` | 0 | 刪 94 MB |
| 清除 | `rm eval/corpora/multihop_rag/document_map.eval-s1.json` | 0 | 刪 118 筆的 map |
| 1.1 | `psql ... "CREATE SCHEMA IF NOT EXISTS lancet_eval_s1;"` | 0 | `CREATE SCHEMA` |
| 1.1 | `(cd gateway && atlas schema apply --env eval-s1 --auto-approve)` | 0 | 1 migration、7 statements；4 張表 |
| 1.2 engine | `LANCET_ENV=eval-s1 ./engine/target/debug/engine` | 啟動成功，後來停止 | 新建 `./data/lancedb-eval-s1`，serving `127.0.0.1:50051` |
| 1.2 A2 檢查 | engine 啟動 log | — | **通過**：`BM25 snapshot built document_count=0 generation=lance-1 nodes_version=1 graph_entities=0 doc_meta_documents=0` |
| 1.2 gateway | `(cd gateway && LANCET_ENV=eval-s1 LANCET_GATEWAY__DATABASE_URL='...search_path=lancet_eval_s1' go run .)` | 啟動成功，後來停止 | `gateway listening 127.0.0.1:8080` |
| 1.3 seed | — | **未跑** | 等使用者同意 |

- 沒碰 `data/lancedb-eval`（728 MB，未動）或 `lancet_eval` schema。
- stack 已停（8080、50051 已釋放），seed 前會重新啟動並再檢查一次 A2。

## 重建：付費 seed 前的新估算

前提：
- chunk 數：第一次 119 篇切出 1,297 個（每篇約 10.9），346 篇約 3,770；audit 模擬 3,953。以下用約 3,900。
- 價格：extraction 已 pin `wafer/us`，列價 $0.0448 / $0.30 per M（input / output），上限 $0.07 / $0.45（D-271）。Embedding $0.12 per M。
- 每 chunk output：第一次有 27% 的第一次嘗試超過 768 token。假設沒超過的約 450，超過的實際約 1,200，平均約 650（範圍 550-800）。log 不記 token 用量，這是推估。

| 項目 | 預期 | 依 price cap |
|---|---|---|
| Extraction output：3,900 × 約 650 ≈ 2.5 M | 約 $0.76（$0.64-0.94） | 約 $1.14 |
| Extraction input：3,900 × 約 520 ≈ 2.0 M | 約 $0.09 | 約 $0.14 |
| Embedding：約 0.85 M | 約 $0.10 | 約 $0.10 |
| **合計** | **約 $1.0-1.2** | **約 $1.4** |

- **上限（16,384 cap）**：3,953 chunk 每個都輸出滿 16,384 token ≈ 64.8 M × $0.45 ≈ $29.1，加 input 與 embedding 約 **$29.4**。**這個上限不含 extraction 重試**（每 chunk 最多 3 次，全部重試且都滿的極端情況約 $88）。
- 截斷已修，重試應該很少；seed 時我會盯 `extraction call failed` 的比率，明顯異常就停下回報。
- **第一次已花**：約 $1.4-1.7（更正後，見上方「花費」）。加上這次預期，步驟 1 合計約 **$2.4-3.1**；指南原估 $2-3、上限約 $11。
- 請到 OpenRouter activity page 核對第一次的實際花費（2026-10-31 15:14-15:56 PDT）。

## 付費 seed 與 1.4、1.5（使用者：「跑 seed (Recommended)」）

| 步驟 | 指令 | exit | 結果 |
|---|---|---|---|
| 1.2 重啟 | engine、gateway（同上） | 啟動成功，後來停止 | A2 再檢查**通過**：`document_count=0 ... graph_entities=0`；8080、50051 都在 listen |
| 1.3 seed | `LANCET_ENV=eval-s1 PYTHONUTF8=1 uv run --project eval lancet-eval seed --corpus multihop_rag_s1_dev --store eval-s1` | **0** | 17:06-18:18 PDT（約 72 分鐘）；`Corpus 'multihop_rag_s1_dev' seeded successfully (346 documents mapped).` |
| 1.4 chunking | `SELECT chunk_strategy, chunk_size, chunk_overlap, count(*) ... WHERE status = 'completed' GROUP BY 1, 2, 3;` | 0 | **一列：`structure-merge`、256、25、346** ✅ |
| 1.4 未完成 | `SELECT id, status, error_message ... WHERE status <> 'completed';` | 0 | **0 列** ✅（不需要 pg-delete-extras） |
| 1.5 preflight | `LANCET_ENV=eval-s1 PYTHONUTF8=1 uv run --project eval lancet-eval preflight --store eval-s1 --corpus multihop_rag_s1_dev` | **1** | 11 PASS、**1 FAIL（`corpus_generation`）**，見下 |
| 停 stack | TaskStop engine、gateway | — | 8080、50051 已釋放 |

### Seed 結果

- 文件：346 篇 indexed，PG 346 `completed`，0 `failed`、0 `queued`；沒有文件被重傳。
- chunk：**3,953 個**（與 audit 模擬的 3,953 完全一致），346 篇全部 `chunk_strategy="structure-merge"`。
- Extraction：`extraction call failed` **0 次**，`entity extraction failed for chunk` **0 次**，`EOF while parsing` 0 次，panic 0 次 → **圖譜覆蓋 3,953/3,953 chunk（100%）**；呼叫數 = 3,953（沒有重試）。
- `dropping relation with unmapped entity endpoint`：4,988 次（已知的 relation 過濾，不是失敗）。
- `inspect_lancedb --graph-population`：document 346、node 3,953、edge 3,607、**entity 24,187**、entity_edge 36,649、孤立 entity 3,337；最高 degree 是「Google」（551）。
- `data/lancedb-eval-s1`：421 MB。`document_map.eval-s1.json`：346 筆，`index_generation = lance-693`。

### 1.5 preflight

| Check | 狀態 |
|---|---|
| drive_environment、store_isolation、arm_store | PASS |
| **index_identity** | **PASS**（PG、LanceDB、document map 的 ID 一致） |
| **store_chunking** | **PASS**（346 篇都是 structure-merge 256/25） |
| canary_manifest、canary_floors | PASS（skipped，D-124） |
| gateway_reachable、engine_reachable | PASS |
| **corpus_generation** | **FAIL**：`Retrieved chunk excerpt arrived truncated (is_truncated=true)` |
| arm_mode_canaries | PASS（6 個：3 rehearsal × 2 arm） |
| openrouter_api | PASS |

原因（只讀 code，沒有再打任何付費呼叫）：
- `config/config.eval-s1.toml` 設 `excerpt_max_chars = 512`（與 `config.toml:102` 相同）。engine 在查詢時用 `bounded_unicode_excerpt`（`engine/src/prompt.rs:778`）把每個 retrieved chunk 截到 512 個字元，超過就設 `is_truncated=true`。
- S1 的 chunk 是 256 token 的 structure-merge，約 1,000-1,300 個字元，幾乎每個都超過 512。v1.0 store 的 chunk 約 55 token，所以 512 夠用。
- `preflight.py:556`（`corpus_generation`）只要有一個 retrieved chunk 被截斷就 FAIL。
- **影響比 preflight 更大**：`metrics.py:211` `fact_matches_excerpt` 遇到 `is_truncated` 直接回 `UNDECIDABLE`，所以步驟 4 的 S1 評分幾乎所有 fact 比對都會變成 undecidable。
- **store 本身沒問題**：excerpt 是查詢時才截，不存在 store 裡。修法是把 `config.eval-s1.toml` 的 `excerpt_max_chars` 調到大於 S1 最長 chunk 的字元數（例如 2,048，具體值要先量最長 chunk），重啟 engine 再跑一次 1.5，**不需要重新 seed**。`config/` 是我這個 lane 不能碰的路徑，也沒有找到現成 issue（`gh issue list --search "is_truncated OR excerpt_max_chars OR corpus_generation"` 沒結果）。

### 花費（估算；以 OpenRouter activity page 為準）

- 這次 seed：3,953 次 extraction 呼叫，0 次重試；embedding 約 0.85 M token。依先前的模型預期約 **$1.0-1.2**（price cap 下約 $1.4）。log 不記 token 用量，請核對 OpenRouter activity page 2026-10-31 17:06-18:18 PDT。
- 1.5 preflight：1 個 probe 查詢 + 6 個 arm canary，約幾分錢（< $0.03）。
- 第一次嘗試（更正後）約 $1.4-1.7。步驟 1 合計約 **$2.4-3.0**。

## 1.5 重跑（#120 修好後，GO 2026-10-31）

| 步驟 | 指令 | exit | 結果 |
|---|---|---|---|
| pull | `git -C D:/Repos/lancet pull --ff-only` | 0 | `aedd4723` → `971094f5`（PR #121：`config.eval-s1.toml` `excerpt_max_chars = 2048`（D-273）、測試、PLAN.md；沒有 engine code 變更，不需重 build） |
| 重啟 stack | engine、gateway（同上） | 啟動成功，後來停止 | `BM25 snapshot built document_count=3953 generation=lance-693 nodes_version=693 graph_entities=24187 doc_meta_documents=346`（就是剛 seed 的 S1 store）；gateway listen 8080 |
| 1.5 preflight | `LANCET_ENV=eval-s1 PYTHONUTF8=1 uv run --project eval lancet-eval preflight --store eval-s1 --corpus multihop_rag_s1_dev` | **0** | **12/12 PASS**，`All preflight checks passed successfully.`；`corpus_generation` PASS（generation `lance-693` 一致，沒有截斷）；`index_identity`、`store_chunking`、`arm_mode_canaries`（6 個）都 PASS |
| 停 stack | TaskStop engine、gateway | — | 8080、50051 已釋放 |

## 步驟 1 總花費（估算；以 OpenRouter activity page 為準）

| 項目 | 時段（2026-10-31 PDT） | 估算 |
|---|---|---|
| 第一次嘗試（中止，768 截斷） | 15:14-15:56 | 約 $1.4-1.7 |
| 第二次 seed（3,953 次 extraction，0 重試；embedding 約 0.85 M） | 17:06-18:18 | 約 $1.0-1.2 |
| 1.5 preflight × 2（各 1 個 probe + 6 個 canary） | 約 18:20、18:42 | 合計 < $0.06 |
| **合計** | | **約 $2.4-3.0** |

指南原估步驟 1 約 $2-3、上限約 $11。log 不記 token 用量，所以以上都是推估。

## 交接

- S1 store 完成：`data/lancedb-eval-s1`（421 MB，generation `lance-693`）、`lancet_eval_s1`（346 `completed`）、`eval/corpora/multihop_rag/document_map.eval-s1.json`（346 筆，未追蹤）。
- 步驟 2-4 不在本 lane 範圍；步驟 4 要使用者另外同意。
- 給 coordinator 的問題：無。

# 第一次嘗試（d943d558，已中止）

## seed 中止時的狀態

- PG `lancet_eval_s1.documents`：118 `completed`、1 `queued`（`567408ee-a92c-4568-a2ea-fcb1fd44a040`；engine log 顯示它在 22:55:30Z 已 `indexing completed`，但 seed 中斷後 PG 狀態沒更新）。0 `failed`，沒有文件被重傳。
- engine log：119 篇切塊、119 篇索引，全部 `chunk_strategy="structure-merge"`；共 **1,297 個 chunk**（平均約 10.9 個/篇）。
- `data/lancedb-eval-s1`：94 MB。`eval/corpora/multihop_rag/document_map.eval-s1.json`：118 筆（未追蹤，`index_generation` 為空）。三者都保留，等重建時清掉。

## Extraction 失敗與重試率（coordinator 要求的免費檢查 1）

來源：engine log（`engine::graph::extraction: extraction call failed` 與 `engine::ingest: entity extraction failed for chunk`）。

| | 次數 | 佔 1,297 chunk |
|---|---|---|
| 第 1 次嘗試失敗 | 354 | 27.3% |
| 第 2 次嘗試失敗 | 270 | 20.8%（重試的 76%） |
| 第 3 次嘗試失敗 → 該 chunk 沒有圖譜抽取 | **230** | **17.7%** |

- 呼叫總數 = 1,297 + 354 + 270 = **1,921**，平均每 chunk 1.48 次；失敗 854 次、成功 1,067 次。
- 230 個失敗 chunk 分布在 74 篇文件（119 篇的 62%）。
- 失敗原因 854 次全部是 `SchemaValidation: failed to deserialize ExtractionOutput schema: EOF while parsing ...`（string 463、value 280、object 99、list 6），也就是輸出 JSON 被截斷。
- 另有 789 筆 `dropping relation with unmapped entity endpoint`（已知的 relation 過濾，不是失敗）。
- 文件層級：0 篇失敗，seed 沒有重傳任何文件。

### 截斷證據（輸出上限）

- log 沒有記 `finish_reason` 或 token 用量，無法直接確認 `length`。
- **更正**：我原本寫上限是 `config/config.toml:182` 的 `max_output_tokens = 2048`，這是錯的。那是 generation 的上限；extraction 用的是 `engine/src/main.rs:145` 寫死的 **768**（`d943d558` 版本，已核對）。#119 把它改成 `EXTRACTION_MAX_COMPLETION_TOKENS = 16_384`（`engine/src/graph/extraction.rs:27`），timeout 120 秒（D-272）。
- 截斷位置：808 筆中，中位數在 JSON 第 130 行，範圍 115-152（1 筆離群在第 1 行），集中在一個窄帶，符合固定約 768 token 的截斷（每行約 6 token），不像供應商隨機斷線。

## 供應商（免費檢查 2）

- extraction 沒有 pin（`generation_provider_order = ["sail-research"]` 只用於 generation），engine log 不記 OpenRouter generation id 或供應商名稱，所以**無法從 log 判斷實際供應商**。沒有呼叫 generation-stats API。#118 會把 extraction pin 到 `wafer/us`。

## 花費（估算；實際請看 OpenRouter activity page，15:14-15:56 PDT）

seed 不印 observed spend，以下依指南價格估算：

- Extraction output（已依 768 上限更正）：失敗 854 次 × 768 token ≈ 0.66 M → 約 $0.84；成功 1,067 次 × 300-500 token → 約 $0.41-0.68。
- Extraction input：1,921 × 約 520 token ≈ 1.0 M × $0.14/M → 約 $0.14（列價約 $0.01）。
- Embedding：119/346 × 0.815 M ≈ 0.28 M × $0.12/M → 約 $0.03。
- **合計約 $1.4-1.7**（更正前寫 $2.8-3.1，誤用了 2,048 上限）。價格用指南的 $0.14 / $1.28 per M；當時 extraction 沒 pin，實際供應商價格不明，以 OpenRouter activity page 為準。

## 其他

- 每項檔案變更：repo 沒有 tracked 檔變更。刪除 `scratch_new.txt`（使用者同意）。新建（gitignored 或未追蹤，保留到重建）：`data/lancedb-eval-s1/`、`lancet_eval_s1` schema 與表、`eval/corpora/multihop_rag/document_map.eval-s1.json`。
- Checks、lane tests、review：本 lane 沒有程式變更，不適用。
- 衝突：無。
- 已開 issue：無。已追蹤：#118（extraction 輸出上限與 pin），#105、#106（步驟 4，不在本 lane 範圍）。
- repo 與 scratchpad 外建立的東西：上述 S1 store、schema 與 map（重建時會清掉）。
- log 保存在 scratchpad：`C:\Users\user3\AppData\Local\Temp\claude\D--Repos-lancet--claude-worktrees-lane-run-s1store-e04537\5b28e8b4-b206-44f2-a129-90133b1a82d1\scratchpad\`（`engine-clean.log`、`gateway.log`、`seed.log`、`build-*.log`）。

