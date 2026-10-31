# run-s01 報告：S0 執行（**blocked**：3.2 被 rerank tripwire 停在 50/351）

- 狀態：**blocked**（無人值守模式）。重開機後 3.1 通過，3.2 跑到 50 筆時 rerank degrade tripwire（O10、D-174）觸發，drive 以 **exit 0** 提前停止（正是 #75 預告的情況）。依 #75 計數：**50/351，不足**，所以停下，沒有跑 3.3–3.7。**held-out read 1/2 已開始（50 題已送出）**。stack 已停。
- 續跑需要使用者同意；見文末「給 coordinator／使用者的選項」。
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

| 重開機後 | Docker Desktop、`docker start lancet-postgres`、`pg_isready`；engine（debug）+ gateway（`go run .`，`search_path=lancet_eval`） | 0 | `serving addr=127.0.0.1:50051`、`gateway listening 127.0.0.1:8080` | 0 |
| 3.1 | `PYTHONUTF8=1 uv run --project eval lancet-eval preflight --corpus multihop_rag_s0_heldout`（02:14 -0700） | 0 | 9 項全 PASS，generation `lance-703` | < $0.01 |
| 3.2 | `PYTHONUTF8=1 uv run --project eval lancet-eval run --corpus multihop_rag_s0_heldout --arms hybrid+rerank+metadata --out eval/runs/2026-10-31-s0-multihop_rag_s0_heldout/journal.jsonl --stage-cap 100`（02:14:50–02:20:27） | **0** | **tripwire 停止**：`rerank degraded on 12 of 50 attempts (0.24), above the 0.2 tripwire rate`。journal 51 行 = 1 header + **50 筆 success**；`context_export.jsonl` 50 列（`PYTHONUTF8=1` 繞過 #84 有效）。12 筆 degraded 依工具說明「stay journalled off-arm」 | observed spend **$0.0461** |
| 3.3–3.7 | 未執行 | — | 因 3.2 計數不足（#75 規則）停下 | 0 |

目前總花費：約 $0.20-0.21（含 3.2 的 $0.0461；先前約 $0.15-0.16，2.2 為估計值）。

## 重要發現：#84（cp950）— S0 前必須處理

本機 Python 的 `locale.getpreferredencoding(False)` 是 `cp950`。`run_psql`（`seed.py:181`）`text=True` 沒給 `encoding`，讀 checkpoint 時遇到 UTF-8 位元組就崩。**不處理的話，3.2 付費 drive 跑完 351 題後會在 context export 失敗並 exit 1**（紀錄仍在 journal，可用 `export-context` 補）。

已驗證的繞法（不改任何追蹤檔）：**步驟 3 的每個 `lancet-eval` 指令前加 `PYTHONUTF8=1`**。建議重開機後照此執行；或者先由另一個 lane 修 #84 再跑（需 coordinator 決定，會動到 `eval/src`）。

## 3.2 tripwire 的原因（只讀 log，免費）

- engine log（`scratchpad/engine2.log`）：12 筆 `rerank_degraded; the fused order is kept error_class=timeout`，多數 `latency_ms=0`；成功的 38 次 `rerank_call` 延遲約 260–310 ms，OpenRouter／voyage 本身正常。
- 被降級的 query 本地檢索很慢：例如 `dense_ms=1159 bm25_ms=2071`、`dense_ms=1246 bm25_ms=1536`。config：`retrieve_timeout_ms` 3080 = 搜尋額度 294 + rerank 2286 + 500 slack。本地搜尋吃掉超過 3 秒後，rerank 剩下的 deadline 約 0，於是記為 timeout。
- 全部 51 次 median：dense 580 ms、bm25 25 ms，可見是**間歇性尖峰**，不是一直慢。當時機器上有 `cargo`、2 個 `rustc`、`go`、56 個 `python` 在跑（lane 50／81／84 等的 build/test），加上剛重開機時 LanceDB 檔案快取還沒熱。判斷：**本機 CPU／IO 競爭**，不是 provider 問題。
- 工具說明：drive 預設 `resume=True`，同一個 `--out` 再跑會從已記錄的 50 筆接續；degraded 的 12 筆是否重跑是 owner 的決定。

## 重開機後要重做的事（已完成）

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

- held-out read 1/2（S0：3.2、3.4、3.5）：**已開始** 2026-10-31 02:14:50 -0700（3.2）。3.2 送出 50 題（另 12 次 attempt 因 rerank degraded 標為 off-arm）後被 tripwire 停下；3.4、3.5 尚未執行。續跑同一個 run dir 仍算這一次 held-out read（S0），不是第 2 次。
- 兩次 `preflight --corpus multihop_rag_s0_heldout` 不讀 held-out 題目內容（程式確認）：`CorpusConfig.questions` 是 lazy property，`preflight_command`（`cli.py:140`）與 `run_preflight_checks`（`preflight.py:1708`）都沒碰它；probe 題目是 document map 第一筆的標題；兩個 arm 時 `run_arm_canaries` 為 false（需 `len(arms) > 2`），legacy canary 因 `legacy_canaries = false` 跳過。
- 彩排只用 dev 題目（`multihop_rag_s1_dev`，`questions.diag.jsonl`，role dev）。
- run-external（3.5）無法在不讀 held-out 的情況下彩排（唯一含 `llamaindex` arm 的 corpus 是 held-out），所以它會在正式 run 第一次執行。

- 新 run dir：`eval/runs/2026-10-31-s0-multihop_rag_s0_heldout/`（在 `D:/Repos/lancet`；`journal.jsonl`、`context_export.jsonl`、`raw_events/`）。
uns6-10-31-s0-multihop_rag_s0_heldout\`（`journal.jsonl`、`context_export.jsonl`、`raw_events/`）。

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

6. 重開機後（本 session，繁中問句，列出 3.2 約 $0.40／上限 $1.5、3.4 約 $0.25、3.5 約 $0.30／上限 $1.5，合計約 $1、上限約 $3.5）：「開跑 S0 (Recommended)」
7. 經 coordinator 轉述：無人值守 —「我離開前在 run-s01 同意，讓它跑完 (Recommended)」。非零 exit／計數不足／步驟 3 以外的付費呼叫 → 停下、blocked、通知 coordinator。

## Decided while unattended

- 3.2 計數 50/351 不足 → 依規則停下，未重跑、未接續、未跑 3.3–3.7。
- 停掉 engine 與 gateway（8080、50051 已無 listener）；`lancet-postgres` 與 Docker 保留。

註：前兩題問句誤用英文撰寫（應為繁中），之後改正。

## 給 coordinator／使用者的選項（續跑需要使用者同意）

1. **（建議）等其他 lane 的 build／test 停下、機器閒置後，重啟 stack，先暖一下 LanceDB 快取，再用同一個 `--out` 重跑 3.2**（`resume=True` 從 50 筆接續，仍是 held-out read 1/2）。剩約 301 題，估約 $0.30，上限 $1.5。12 筆 degraded 是否要重跑，請 owner 決定（工具不會自動重跑）。
2. 換新 run dir 從頭重跑 3.2（拋棄這 50 筆）。仍算 S0 同一次 read，但 50 題已經看過，乾淨度不如選項 1。
3. 先不跑，交由 coordinator 調查（例如要不要調 tripwire 或 timeout；這會改 `config/` 或 `eval/src`，屬 off-limits，S0 期間不能中途改）。

## 給 coordinator 的問題（舊）

- #84：S0 用 `PYTHONUTF8=1` 繞過即可，還是要先開 lane 修完再跑？（建議：繞過，修補另排；S0 的 D-73 乾淨樹檢查只看 `eval/src`，修 #84 會改 `eval/src`，需在 S0 前合併或之後再修，不能中途改。）
