# run-s01 報告：S0 執行（暫停於步驟 3.2 前，等重開機）

- 狀態：**paused**（使用者要先重開機釋放記憶體）。步驟 0、2、#76 付費彩排已完成；**步驟 3（S0 本體）尚未開始，held-out read 尚未發生**。
- checkout：主 checkout `D:\Repos\lancet`，`main` @ `c69d4868`（= `origin/main`，未 pull），樹乾淨（只有不屬於本 lane 的 `scratch_new.txt`）。無分支、無 commit、無 PR。
- 注意：app 把本 session 開在 coordinator 的 worktree（`vigorous-elgamal-87e693`），但每個指令都以 `cd D:/Repos/lancet` 開頭，在主 checkout 執行；worktree 內沒有寫入任何東西（`git status` 乾淨、無 `engine/target`）。

## 各步驟

| 步驟 | 指令 | exit | 結果 | 實際花費 |
|---|---|---|---|---|
| 0 build | `CARGO_BUILD_JOBS=4 cargo build --manifest-path engine/Cargo.toml --locked` 然後 `... --release --bin inspect_lancedb --bin generate_from_context`（#74） | 0 / 0 | debug 5m02s；release 2m24s（sccache） | 0 |
| 0 Postgres | `docker start lancet-postgres`（Docker Desktop 原本沒開，已啟動） | 0 | `pg_isready` OK | 0 |
| 2.1 | `input_type` 轉送測試（指南原指令） | 0 | **`forwarded`**，最大差 0.03655211 | < $0.0001 |
| 2.2 | `uv run --project baselines/llamaindex lancet-llamaindex export --corpus multihop_rag_s1_dev --arm llamaindex --out eval/runs/llamaindex-check` | 0 | 100 列；`pipeline_config.json`：`framework_version` 0.14.25、`documents` 346、`chunk_size` 256、`chunk_overlap` 25、`dense_top_k` 20、`rerank_model` `voyageai/rerank-2.5-lite`、`keep` 8，全部符合 `PREREGISTRATION_S0`；chunks 4701 | 工具未印花費；估 ~$0.15，請看 OpenRouter activity |
| 彩排 a | `uv run --project eval lancet-eval preflight --corpus multihop_rag_s0_heldout`（v1.0 stack） | **1** | 只有 `corpus_generation` FAIL：probe 回 0 vector / 0 bm25、degraded（engine log 有 `query_embedding_retry`）。當時 2.2 export 正用同一把 key 大量打 embedding，判斷為競爭／限流 | < $0.01 |
| 彩排 a 重跑 | 同上（使用者同意後） | 0 | 全部 PASS，generation `lance-703` | < $0.01 |
| 彩排 b | `uv run --project eval lancet-eval run --corpus multihop_rag_s1_dev --arms small/hybrid+rerank+metadata --limit 3 --out eval/runs/rehearsal-s0-2026-10-31/journal.jsonl --stage-cap 100` | **1** | 3 筆皆 `success`、已入 journal；**結尾 context export 失敗**：`run_psql` 以 cp950 解碼 psql 輸出 → `UnicodeDecodeError` → `'NoneType' object has no attribute 'splitlines'`。開 #84 | observed spend $0.0026 |
| 彩排 b 補 export | `PYTHONUTF8=1 uv run --project eval lancet-eval export-context --run eval/runs/rehearsal-s0-2026-10-31`（離線免費） | 0 | 寫出 3 列 | 0 |
| 彩排 c | `PYTHONUTF8=1 uv run --project eval lancet-eval check-prompt-parity --run eval/runs/rehearsal-s0-2026-10-31` | 0 | "Prompt parity holds for 3 Lancet row(s)"；release `generate_from_context` 可用 | 0 |

目前總花費：約 $0.15-0.16（2.2 為估計值，其餘為 observed／上限）。

## 重要發現：#84（cp950）— S0 前必須處理

本機 Python 的 `locale.getpreferredencoding(False)` 是 `cp950`。`run_psql`（`seed.py:181`）`text=True` 沒給 `encoding`，讀 checkpoint 時遇到 UTF-8 位元組就崩。**不處理的話，3.2 付費 drive 跑完 351 題後會在 context export 失敗並 exit 1**（紀錄仍在 journal，可用 `export-context` 補）。

已驗證的繞法（不改任何追蹤檔）：**步驟 3 的每個 `lancet-eval` 指令前加 `PYTHONUTF8=1`**。建議重開機後照此執行；或者先由另一個 lane 修 #84 再跑（需 coordinator 決定，會動到 `eval/src`）。

## 重開機後要重做的事

1. 開 Docker Desktop，`docker start lancet-postgres`，`docker exec lancet-postgres pg_isready -U postgres`。
2. 依指南啟動 v1.0 stack（在 `D:\Repos\lancet`，背景執行，等 engine 印 `serving addr=127.0.0.1:50051`、gateway 印 `listening 127.0.0.1:8080`）：
   - `LANCET_ENV=eval ./engine/target/debug/engine`
   - `(cd gateway && LANCET_ENV=eval LANCET_GATEWAY__DATABASE_URL='postgres://postgres:postgres@127.0.0.1:5432/lancet?sslmode=disable&search_path=lancet_eval' go run .)`
3. 不需重 build：debug engine 與 release `inspect_lancedb`、`generate_from_context` 都在 `D:\Repos\lancet\engine\target`。
4. 不需重跑步驟 2 與彩排。
5. **在 3.2 前再問使用者一次**（held-out read 1/2，約 $1，上限約 $3.5），並先決定 #84 的處理（`PYTHONUTF8=1` 或先修）。
6. 3.1 preflight 不可與其他會打 embedding 的工作同時跑。
7. `<S0_RUN>` = `eval/runs/<開跑日期>-s0-multihop_rag_s0_heldout`（若 11-01 開跑則日期改為 2026-11-01）。

目前沒有任何背景工作在跑；engine 與 gateway 已停（8080、50051 無 listener）。`lancet-postgres` container 仍在跑（重開機會停）。

## Held-out read 紀錄（D-237）

- held-out read 1/2（S0：3.2、3.4、3.5）：**尚未發生**。
- 兩次 `preflight --corpus multihop_rag_s0_heldout` 不讀 held-out 題目內容（程式確認）：`CorpusConfig.questions` 是 lazy property，`preflight_command`（`cli.py:140`）與 `run_preflight_checks`（`preflight.py:1708`）都沒碰它；probe 題目是 document map 第一筆的標題；兩個 arm 時 `run_arm_canaries` 為 false（需 `len(arms) > 2`），legacy canary 因 `legacy_canaries = false` 跳過。
- 彩排只用 dev 題目（`multihop_rag_s1_dev`，`questions.diag.jsonl`，role dev）。
- run-external（3.5）無法在不讀 held-out 的情況下彩排（唯一含 `llamaindex` arm 的 corpus 是 held-out），所以它會在正式 run 第一次執行。

## repo 與 scratchpad 以外建立的東西

- `D:\Repos\lancet\baselines\llamaindex\.venv`（`uv run` 建立，78 個套件；gitignored）— 保留，S0 要用。
- `D:\Repos\lancet\eval\runs\llamaindex-check\`、`eval\runs\rehearsal-s0-2026-10-31\`（gitignored，非 run of record）— 保留供查。
- `engine/target` 新產物（debug + 兩個 release bin）— 保留。
- 啟動了 Docker Desktop 與 `lancet-postgres` — 保留。

## 開的 issue

- #84 eval: run_psql decodes psql output with the locale code page (cp950 on Windows), breaking context export（Refs #75）

## 使用者在本 session 的決定（原話為選項標籤）

1. 步驟 2：「Run step 2 (Recommended)」
2. #76 付費 3 題彩排：「Run the rehearsal (Recommended)」
3. preflight 失敗後重跑並繼續 b、c：「Retry and continue (Recommended)」
4. 經 coordinator 轉述：重開機前暫停 —「可以，通知coordinator」
5. 經 coordinator 轉述（2026-10-31）：#84 —「用 PYTHONUTF8=1 繞道跑 S0 (Recommended)」。S0 每個 `lancet-eval` 指令前加 `PYTHONUTF8=1`；#84 另開 lane，S1 前合併，S0 期間不合併。

註：前兩題問句誤用英文撰寫（應為繁中），之後改正。

## 給 coordinator 的問題

- #84：S0 用 `PYTHONUTF8=1` 繞過即可，還是要先開 lane 修完再跑？（建議：繞過，修補另排；S0 的 D-73 乾淨樹檢查只看 `eval/src`，修 #84 會改 `eval/src`，需在 S0 前合併或之後再修，不能中途改。）
