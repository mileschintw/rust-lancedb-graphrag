# spare-1 報告：#163 S3 held-out 讀者網格（免費階段：凍結與 harness）

- **分支與 head**：`claude/lane-spare-1-c7ab76`，head `10dda4ee`（起點 origin/main `68f0009c`）。共六個 commit：
  - `f9b26754`：harness（run-plan 型別、closed-book 欄、held-out replay 閘門、盲化拒絕）與 D-291
  - `99b9d29e`：D-73 凍結 commit，只含常數 `RUN_PLAN_S3_HELDOUT`
  - `e39546e9`：六個欄 corpus、四個 graph overlay、RUN-S3-HELDOUT.md
  - `927d5460`：第 1 輪 review 修正
  - `879bbd0e`：第 2 輪 review 修正
  - `10dda4ee`：CI ruff 修正（兩行換行）
- **PR 本文草稿**：`pr-bodies/spare-1.md`。依 brief 寫 `Refs #163`，不寫 Closes；Closes 留給最終紀錄 PR。

## Issue 項目中已不成立者

無。#163 免費階段的四項（D-ID、run-plan 常數與其獨立 freeze commit、corpus config、RUN-S3-HELDOUT.md）都已完成。付費提交（步驟 3、4）與「不在本 issue 評分」屬之後的階段。

## 各檔變更

- `experiments/v1.1/PLAN.md`：新增 D-291，內容是兩段凍結（先 run plan、後分析計畫）、盲化規則，以及 harness 如何強制執行。
- `eval/src/lancet_eval/thresholds.py`：
  - 新增 `ReaderGridRunPlan`、`GridColumn`、`ColumnRunPlan` 三個類別，沒有 Holm family。
  - 新增常數 `RUN_PLAN_S3_HELDOUT`，只在 `99b9d29e` 這一個 commit 中出現。
- `preregistration.py`：
  - `resolve(token, column)`：run plan 必須帶 column，否則拒絕。
  - 新增 `resolve_corpus`、`require_unblinded`、`blinded_corpus_problem`。
- `corpus.py`：新增 `[preregistration] column`。
- `replay.py`：
  - held-out corpus 只有在 token 與 column 能解析成 run-plan 欄時才放行（pilot 也一樣）。
  - 來源 run 必須來自同一個 corpus；run-plan 的來源 run 不能帶進其他 corpus。
  - `_dev_corpus` 改名為 `_replayable_corpus`。
- `arms.py`：新增 closed-book arm（`twowiki/closed-book`），不在引擎 registry 內，不會送 gateway 請求。
- 新檔 `closed_book.py`，新 CLI 指令 `lancet-eval closed-book-init`：每題寫一列無 evidence 的 export row，用引擎的 model-only prompt 打包；寫 replay header，不寫任何 record。
- `batch.py`：
  - closed-book 的 base 由 export row 代替。
  - deepseek 的 replicate 1..K 走 sync。
  - 只有 closed-book 列的 bin 呼叫會帶 `model_only`。
  - 成本估計使用 deepseek 的 usage；還沒有 usage 時改用輸出上限。
- `parity.py`：`run_bin(..., model_only=True)` 只在子程序環境中設定 `LANCET_ENGINE__WORKFLOW__ALLOW_MODEL_ONLY_ANSWERS=true`。
- `run.py`、`preflight.py`：改為讀取 corpus 所指的欄（arm 集合與 tripwire）。
- 盲化拒絕：`score.py`、`explore_readout.py`、`evidence_split.py`、`answer_judge.py`、`judge_stage.py`、`unpark_gates.py`、`diagnostic.py` 遇到 run-plan corpus 一律拒絕，訊息標 D-291。`compare-levers` 經由 resolve 間接拒絕。
- 新檔 `twowiki_h.py` 與 `eval/corpora/twowiki/s3h_split.json`：
  - D-243 split，900 題 held-out 全部歸 G，只從 ID 推導；split sha 為 `7590e2b3…`。
  - 另寫 gitignored 的 held-out 題目檔，以及題型對照表（不含答案，#167）。
- `eval/corpora/twowiki_s3h_{closed_book,hybrid,graph_deepseek,graph_haiku,graph_sonnet,graph_opus}.toml`：每欄一個 corpus。
- `config/config.eval-2wiki-s3h-{deepseek,haiku,sonnet,opus}.toml`：步驟 3 的 graph table set（`s3h_<writer>`）。這些是新增的 overlay，沒有更改既有的 config 預設值。
- `.gitignore`、`eval/tests/test_journal.py`：加入 `*-twowiki_s3h_*` 與 `-s3h-` 標記。
- `experiments/v1.1/RUN-S3-HELDOUT.md`：執行指南，含成本表與盲化規則。
- 測試：
  - 新檔：`test_reader_grid_run_plan.py`、`test_reader_grid_resolution.py`、`test_closed_book.py`、`test_twowiki_h.py`、`test_s3_heldout_run_plan.py`
  - 擴充：`test_arms.py`、`test_replay.py`

## CI 修正（PR #173，run 41360565244）

- CI 的 ruff 檢查失敗，原因是本分支新增了 3 行過長的行（line-too-long）：
  - `preregistration.py`、`test_arms.py` 各 1 行，另開 commit `10dda4ee` 修正。
  - `thresholds.py` 有 1 行在 `RUN_PLAN_S3_HELDOUT` 常數內。
- 依 coordinator 指示改寫未 merge 的分支，讓凍結 commit 仍是常數唯一的 commit：
  - 新的凍結 commit 是 `99b9d29e`，取代 `4f0b3bc1`，只改了該行的換行。
  - 已確認常數的 AST 與舊凍結 commit 相同，`preregistered_value_problem` 回傳 `None`。
  - 之後的 commit 以 cherry-pick 重放，hash 都變了。
  - 用 `--force-with-lease`（以舊 head `e664121d` 為基準）force-push，只推本分支。
- 本機照 CI 的方式比對「changed files 新增的 ruff 規則數」，已無新發現。

## 預設分支上本來就失敗的檢查

無。

## 檢查與 lane 測試

- `PYTHONUTF8=1 uv run --project eval pytest -n auto --dist loadfile`（在 head `10dda4ee` 上）：**3252 passed, 14 skipped, 42 subtests passed**（194.84 秒）。
- D-73 漂移檢查：`gitcheck.preregistered_value_problem('RUN_PLAN_S3_HELDOUT', '99b9d29e')` 回傳 `None`（force-push 後重驗）。`git log -S RUN_PLAN_S3_HELDOUT -- thresholds.py` 只列出 `99b9d29e`。
- **未執行**：
  - cargo（`cargo test --manifest-path engine/Cargo.toml --locked && sh scripts/engine-test-targets.sh`）與 Go（`(cd gateway && go test -count=1 -short ./...) && sh scripts/gateway-test-targets.sh`）。原因：沒有改到 Rust 或 Go 程式碼，只新增引擎在各自 `LANCET_ENV` 下讀的 overlay 檔。若要保險，可在 merge 前跑這兩條。
  - ruff：repo 整體本來就有大量 E501 與排版問題；新檔與新測試都已 ruff 乾淨。
- 主 checkout 才能做的檢查：無；免費階段沒有用到主 checkout。

## 衝突與解法

無。期間 origin/main 沒有移動到本 lane 的檔案。

## Review 發現與處理

1. 第 1 輪（標準與 spec 雙軸，fixed point 為 origin/main）：
   - Spec 阻斷 1：`judge-answers`、judge stage、unpark gates 能讀 run-plan run。→ 已改為拒絕。
   - Spec 阻斷 2：held-out replay 閘門只檢查 `column` 鍵存在，pilot 會略過 token 檢查；dev corpus 也能帶入 run-plan 來源。→ 兩者都已封閉，並加了測試。
   - Spec 阻斷 3：closed-book 成本估計把輸出算成 0。→ 改用 deepseek 的 usage，或輸出上限。
   - 標準軸：沒有硬性違規。
     - 已處理：`_dev_corpus` 改名；`ColumnRunPlan` docstring 補全；`score._refuse_blinded` 的 fail-open 加上註解說明。
     - 保留：其餘 smell（字串三元組的 cells、`batch.py` 中五處 closed-book 分支、從 `replay.py` import 私有 helper）。理由是 repo 本來就這樣寫，而且只有單一特例。
2. 第 2 輪（只看 `927d5460`）：
   - 阻斷 1：unpark 測試缺必要參數，argparse 先退出，測試等於空測。→ 補上 pid 參數，並檢查 stderr 含 D-291。
   - 阻斷 2：`diagnostic.build_rows` 仍能讀答案與 gold。→ 已改為拒絕。
   - 附註：`twowiki_h` docstring 寫「每個 run 目錄都有副本」，但這次 diff 沒有任何東西複製它。→ 改寫為「由 RUN 指南的紀錄步驟複製」。
   - 附註（未處理）：unpark 的 `--baseline-run` 沒有檢查；風險低。
3. 第 3 輪（只看 `879bbd0e`）：沒有阻斷。
4. 留下的已知落差：凍結常數 `blinding_rule` 的文字只列出 score、compare-levers 和兩個 readout，實際拒絕的指令更多。常數凍結後不能修改，D-291 與 RUN 指南已列出完整清單。

## 開出的 issue

無。

## Tracker 或 Roadmap 已記錄的 lane 外問題

- #167（S3 分析計畫要有依題型的次要指標）：本 lane 只確保題型對照表會進每個 run 目錄，分析計畫本身不在本 lane。

## repo 與 scratchpad 以外建立、安裝或移除的東西

無。另外，我一度執行了 `git stash push -- unpark_gates.py`，但該檔沒有未提交的變更，所以沒有產生任何 stash 項目（`git stash list` 確認為空）。

## Coordinator 的裁示（含原話）

- harness 程式碼範圍，2026-11-01：「Yes, include the harness code in this lane, guarded as you propose: only a run-plan corpus under the new D-ID may replay held-out; score and compare-levers refuse held-out runs. It is in #163's scope (needed to run the cells). Keep the D-73 freeze commit to the constant alone (code in separate commits), and the held-out question file must not carry gold answers into anything a reader or you read before scoring. Mode is normal (not unattended): log it as a coordinator ruling, not under Decided while unattended.」
  - 依此執行：freeze commit 只含常數。
  - gold 答案只存在 gitignored 的 `questions.heldout.jsonl` 裡，供日後 score 讀取。
  - 讀者 prompt 只含題目文字：closed-book 列只有 question，drive 只送 query。
  - 我沒有開啟或讀過任何 held-out 答案；`twowiki_h` 也還沒在任何地方跑完整寫檔（只跑了 `split`，它只讀 ID）。
- #167，2026-11-01：「Keep the run plan's cells unchanged; just make sure the per-question type is recorded in the run dirs so the analysis can split by it.」
  - 依此執行：cells 沒有改動；`twowiki_h` 寫出題型對照表，RUN 指南的紀錄步驟把它複製進每個 run 目錄。

- 付費階段開始（2026-11-01）：「continue」。PR #173 已 merge（512a48a6），可進主 checkout 跑付費步驟 2–3。

## 使用者（owner）本人的決定（由 coordinator 轉述，2026-11-01 在 coordinator session 輸入）

1. Claude 上限：「Raise cap to ~$36.5」。新上限 $36.50（餘額 $37.52，2026-11-03 到期）。closed-book 與 hybrid 全部讀者先跑（約 $22），接著完整跑 Opus × graph-deepseek。其他 graph 格（含 Haiku、Sonnet 的 graph 格與 Opus 的其他三個 graph 格）等下一筆額度；不跑部分格，所以不改 harness。
2. OpenRouter 上限：「Raise to $6 (Recommended)」。涵蓋所有 deepseek 格（含 replicate）。

本 session 中使用者沒有直接對我下的決定。

## Decided while unattended

無。依 coordinator 指示，模式是 normal，scope 決定記在上面的「Coordinator 的裁示」。

## 給 coordinator 的待決問題（付費階段之前；1、2 已由上面 owner 裁示解決，3 由本 lane 處理）

（#172 的四個 writer 抽取結果已 merge 進 main，步驟 3 可在 continue 後匯入。）

1. **Claude 額度不夠跑完 must-run 的 cells。** 依 run B 實測單價估算：
   - closed-book 與 hybrid 兩欄全部讀者：約 $22。
   - 加上 Opus × graph-deepseek（約 $14）後約 $36，已超過 $34.50 上限。
   - 全部 core cells 約 $80 以上。
   - 選項：
     - (a) 照順序跑到上限即停。我建議這個。
     - (b) 提高上限或等新額度。
     - (c) 讓 Opus × graph-deepseek 只跑部分題目。
   - 選 (c) 前要注意：目前 `batch submit --limit` 只允許 pilot run；run of record 要跑部分 cell，需要另外加 harness 支援。
2. **OpenRouter 上限 $3 不夠。** 五次 deepseek drive（每次約 $0.70）加上各欄 replicate 2，約 $5。請決定是否提高上限，或只先跑 hybrid 與 deepseek 的 graph 欄。
3. **步驟 3 的前置工作還沒做**，等 #145 deepseek 抽取 merge 後由本 lane 補上：把各 writer 的抽取結果轉成 `import_graph_extractions` 讀的 `answers.jsonl`（`{text, content}`）。

## 付費階段紀錄（進行中，2026-11-01 起，主 checkout `D:/Repos/lancet`，main `19998782`）

Run 目錄日期 `<D>` = 2026-11-01。下表是 Claude 額度的累計估計，上限 $36.50；OpenRouter 上限 $6，步驟開始前餘額 $17.85。

### 步驟 1：closed-book（`eval/runs/2026-11-01-s3h-twowiki_s3h_closed_book`）

- `closed-book-init`：900 列。
- deepseek，經 sync API：
  - 1,800 筆請求，sync 批次 `sync-twowiki_closed_book-1-1793575483`。
  - 結果：replicate 1 成功 892、replicate 2 成功 891；另有 17 筆 `NODE_ERROR_KIND_LLM_GENERATION_FAILED`，都是已計費的 render 失敗（`finish_reason 'length'`、notice 超長），列為最終紀錄，不重送。
  - Routing 檢查：0 筆違規。
  - 依 usage 計算的實際花費：$0.0842。
- Claude batches，2026-11-01 送出，估計值以 deepseek 的 usage 為基準：

  | Arm | 批次 ID | 請求數 | 估計 | 最壞上限 |
  |---|---|---|---|---|
  | Opus 5.5 | `batch-1793578463-ZRhDqLcyj0dnjGpGV102` | 900 | $1.41 | $18.57 |
  | Sonnet 5.5 | `batch-1793578469-ft4pcsEQRV5uzXI1hYaI` | 900 | $0.71 | $9.28 |
  | Haiku 5.5 | `batch-1793578474-zHxjRSpMpBLXvaVgEKEZ` | 1,800 | $0.07 | $0.93 |

  Claude 累計估計：約 $2.19。
- closed-book Claude batches fetched：3,600 筆成功、0 錯誤、routing 0 筆違規。依 usage 計算的實際花費：

  | Arm | 筆數 | prompt / completion / reasoning tokens | 實際花費 |
  |---|---|---|---|
  | Haiku 5.5 | 1,800 | 969,268 / 434,620 / 0 | $0.157 |
  | Sonnet 5.5 | 900 | 485,534 / 244,111 / 2,006 | $1.706 |
  | Opus 5.5 | 900 | 485,534 / 325,449 / 127,523 | $4.226 |

  closed-book 的 Claude 合計 $6.09。估計只有 $2.19，原因是 Claude prompt 加上輸出 schema 約 540 tokens，而 deepseek 只有 75 tokens；另外 Opus 在 effort low 下每題仍約有 140 個 reasoning tokens。

### 步驟 2：hybrid（drive 在 `eval/runs/2026-11-01-s3h-drive-twowiki_s3h_hybrid`，run of record 在 `eval/runs/2026-11-01-s3h-twowiki_s3h_hybrid`）

- 開始前 preflight 全部 PASS：store eval-2wiki，generation `lance-12239`。
- drive：900/900 成功，觀察到的花費 $0.7822（OpenRouter）。header 的 partial 欄已手改為 false，其餘 bytes 不變。
- replay-init：900 筆 record、900 列 export row。
- Claude batches 已送出，估計值以 deepseek 的 token 數為基準，依 closed-book 的經驗實際約為 1.5–2.8 倍：

  | Arm | 批次 ID | 估計 | 最壞上限 |
  |---|---|---|---|
  | Opus 5.5 | `batch-1793579350-THfK2ZEuPLAB9L6pGK6l` | $6.34 | $22.95 |
  | Sonnet 5.5 | `batch-1793579358-oJdno8lb1X06n3Mu1eRR` | $3.17 | $11.47 |
  | Haiku 5.5 | `batch-1793579368-4p04yiR2ZhqjbCJaVlQz` | $0.32 | $1.15 |

- deepseek replicate 2 經 sync API 送出，背景執行中。
- deepseek replicate 2，經 sync API：sync 批次 `sync-twowiki_hybrid_rerank_metadata-1-1793579380`，892 筆成功、8 筆錯誤；routing 0 筆違規；花費 $0.157。
- hybrid 的 Claude batches 已 fetch，routing 0 筆違規。依 usage 計算的實際花費：

  | Arm | 筆數（成功 / 錯誤） | prompt / completion / reasoning tokens | 實際花費 |
  |---|---|---|---|
  | Haiku 5.5，K=2 | 1,796 / 4 | 8,306,304 / 465,879 / 0 | $0.532 |
  | Sonnet 5.5 | 898 / 2 | 4,154,052 / 238,286 / 0 | $5.346 |
  | Opus 5.5 | 898 / 2 | 4,154,052 / 241,834 / 2,086 | $10.726 |

- 錯誤明細，都是已計費、被引擎拒絕的答案，列為最終紀錄、不重送：
  - deepseek r2 有 8 筆：6 筆是 `answer basis 'mixed' requires at least one cited evidence ID`，2 筆是 `finish_reason 'length'`。
  - 每個 Claude 讀者在同兩題（`f06252fc…`、`a1d9a65c…`）上被拒，原因是 `OpenRouter prompt_tokens 10218/8702 exceeds budget 8192`：Claude tokenizer 算出的 prompt 超過引擎的 8,192 預算。
- Claude 累計實際花費：$22.70（closed-book $6.09 + hybrid $16.61），距上限 $36.50 還剩 $13.80。

### 步驟 3：graph 欄位

- 圖譜匯入（`import_graph_extractions`，各 writer 一組側表 `entities__s3h_<w>`、`entity_edges__s3h_<w>`）：
  - deepseek：33,811 個實體、41,187 條 entity edges，exit 0（16:37–20:10）。逐份文件寫入，表版本累積上萬個，越跑越慢。
  - Haiku、Sonnet、Opus：18:06 起改為三個並行程序執行（寫不同的側表）。原本的串行迴圈跑到這三組時，因側表已存在而被拒（exit 1，什麼都沒寫），這是預期中的。
- graph-deepseek stack：engine 用 `LANCET_ENV=eval-2wiki-s3h-deepseek`，log 有 `graph_table_set="s3h_deepseek"`。
  - 前兩次 preflight 的 `corpus_generation` FAIL：探測沒帶回 snapshot。直接重放探測三次都正常；第三次 preflight 全部 PASS（`lance-12239`）。推測是 engine 剛起、圖表未暖。
- OpenRouter 餘額 $17.18（起始 $17.85，至今 $0.67，含匯入的 entity embedding）。
- 第一次 graph-deepseek drive 在第 5 題被 rerank tripwire 擋下：5 次連續 `rerank_degraded error_class=timeout`，花費 $0.0052。
  - 原因：dense 檢索花了 2,686 ms，把 3,080 ms 的 retrieve 預算用光，rerank 只剩約 0–300 ms。三個並行匯入正在搶 CPU、磁碟和 embedding API。
  - 處理：`config/` 不改。這 5 筆 record 的目錄已移到 scratchpad（`aborted-drive-graph-deepseek-1`），不進 run of record。等三個匯入跑完再重新 drive。
- store 原有的表未被寫入：匯入前後比對 communities、documents、edges、entities、entity_edges、nodes、staged_documents_v2 這 7 張表的 116,282 個檔案（路徑、大小、mtime），完全一致。只有 `__manifest` 因登記側表而變動。
- Haiku、Sonnet、Opus 的匯入都 exit 0（22:2x 前完成）。背景任務本身回報 exit 1，是收尾那行 `tail -3` 的語法錯誤，與匯入無關：
  - s3h_haiku：36,476 個實體、49,416 條 entity edges
  - s3h_sonnet：35,658 個實體、50,111 條 entity edges
  - s3h_opus：34,108 個實體、47,953 條 entity edges
- 機器空下來後 preflight 再次全部 PASS，dense 檢索回到約 1.2 秒。22:3x 重新 drive graph-deepseek，前 20 題沒有 rerank degrade。
- graph-deepseek drive（`eval/runs/2026-11-01-s3h-drive-twowiki_s3h_graph_deepseek`）：900/900 成功，觀察到的花費 $0.7740（OpenRouter），重試後無錯誤；本次 drive 中 rerank degrade 2 次，不連續。header 的 partial 欄已手改為 false，其餘 bytes 不變。
- replay-init 進 `eval/runs/2026-11-01-s3h-twowiki_s3h_graph_deepseek`：900 筆 record、900 列 export row。
- Opus × graph-deepseek 的估計（送出前印出）：
  - 工具印的估計：$6.36（以 deepseek token 數為基準），最壞上限 $22.95。
  - 校準估計：$10.73。依據是兩次 deepseek drive 的平均 prompt 長度比（graph / hybrid = 1.001，因為兩者都被 8,192 prompt 預算封頂），乘上 hybrid Opus 實際的 input $8.31 + output $2.42。輸出多抓 20% 則為 $11.22。
  - 剩餘 Claude 額度 $13.80，放得下，所以送出。
- Opus × graph-deepseek 批次：`batch-1793605854-cSuRCk8qjIA1WkyU7ZOt`，900 筆。
- graph-deepseek 的 deepseek replicate 2：經 sync API 送出，背景執行中。
- OpenRouter 餘額 $16.81（帳面可能有延遲）。
- graph-haiku：engine 換到 `s3h_haiku`，preflight PASS，drive 執行中（`eval/runs/2026-11-01-s3h-drive-twowiki_s3h_graph_haiku`）。
