# spare-1 報告：#163 S3 held-out 讀者網格（免費階段：凍結與 harness）

- **分支與 head**：`claude/lane-spare-1-c7ab76`，head `e664121d`（起點 origin/main `68f0009c`）。共五個 commit：
  - `f9b26754`：harness（run-plan 型別、closed-book 欄、held-out replay 閘門、盲化拒絕）與 D-291
  - `4f0b3bc1`：D-73 凍結 commit，只含常數 `RUN_PLAN_S3_HELDOUT`
  - `79ace56d`：六個欄 corpus、四個 graph overlay、RUN-S3-HELDOUT.md
  - `aa2b0428`：第 1 輪 review 修正
  - `e664121d`：第 2 輪 review 修正
- **PR 本文草稿**：`pr-bodies/spare-1.md`。依 brief 寫 `Refs #163`，不寫 Closes；Closes 留給最終紀錄 PR。

## Issue 項目中已不成立者

無。#163 免費階段的四項（D-ID、run-plan 常數與其獨立 freeze commit、corpus config、RUN-S3-HELDOUT.md）都已完成。付費提交（步驟 3、4）與「不在本 issue 評分」屬之後的階段。

## 各檔變更

- `experiments/v1.1/PLAN.md`：新增 D-291，內容是兩段凍結（先 run plan、後分析計畫）、盲化規則，以及 harness 如何強制執行。
- `eval/src/lancet_eval/thresholds.py`：
  - 新增 `ReaderGridRunPlan`、`GridColumn`、`ColumnRunPlan` 三個類別，沒有 Holm family。
  - 新增常數 `RUN_PLAN_S3_HELDOUT`，只在 `4f0b3bc1` 這一個 commit 中出現。
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

## 預設分支上本來就失敗的檢查

無。

## 檢查與 lane 測試

- `PYTHONUTF8=1 uv run --project eval pytest -n auto --dist loadfile`（在 head `e664121d` 上）：**3252 passed, 14 skipped, 42 subtests passed**（194.84 秒）。
- D-73 漂移檢查：`gitcheck.preregistered_value_problem('RUN_PLAN_S3_HELDOUT', '4f0b3bc1')` 回傳 `None`。`git log -S RUN_PLAN_S3_HELDOUT -- thresholds.py` 只列出 `4f0b3bc1`。
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
2. 第 2 輪（只看 `aa2b0428`）：
   - 阻斷 1：unpark 測試缺必要參數，argparse 先退出，測試等於空測。→ 補上 pid 參數，並檢查 stderr 含 D-291。
   - 阻斷 2：`diagnostic.build_rows` 仍能讀答案與 gold。→ 已改為拒絕。
   - 附註：`twowiki_h` docstring 寫「每個 run 目錄都有副本」，但這次 diff 沒有任何東西複製它。→ 改寫為「由 RUN 指南的紀錄步驟複製」。
   - 附註（未處理）：unpark 的 `--baseline-run` 沒有檢查；風險低。
3. 第 3 輪（只看 `e664121d`）：沒有阻斷。
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

本 session 中沒有使用者本人的決定。

## Decided while unattended

無。依 coordinator 指示，模式是 normal，scope 決定記在上面的「Coordinator 的裁示」。

## 給 coordinator 的待決問題（付費階段之前）

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
