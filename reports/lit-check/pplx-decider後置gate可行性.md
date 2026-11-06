# pplx-decider 當後置 gate 的可行性

2026-11-05 整理。延續 [`agentic檢索決策點調查.md`](agentic檢索決策點調查.md)：想用一個非 reader 的 decision model，在檢索之後判斷證據夠不夠、下一步做什麼。目前沒有開 issue。2026-11-05 做了一次單次呼叫和一次小規模區分測試，結果見「實測結果」。

## 結論

**作為後置 gate 可行，而且形狀很合適。** 輸入是「問題加上 rerank 後的證據」，輸出是固定選項上的機率分布。這樣可以凍結閾值、算 ROC-AUC，符合 Lancet 預先註冊的規則。判斷本身的成本幾乎可以忽略，主要代價是每一輪 loop 多一次 API 來回的延遲。

## 模型與價格（Perplexity 官方文件）

| | `pplx-decider-v1.2` | `pplx-decider-flash-v1.2` |
|---|---|---|
| 別名 | `pplx-decider-latest` | `pplx-decider-flash-latest` |
| 規模 | 27B | 4B |
| 輸入價格（Perplexity 直連） | 每 1M token $0.02 | 每 1M token $0.01 |
| 輸出 | 免費，不收單次請求費 | 同左 |
| 多題處理 | 所有問題一起回答，彼此可能互相影響 | 每題分開回答，`state` 每題計費一次 |
| 速率上限 | 每分鐘 15M token | 每分鐘 4M token |

- 兩個模型共用一個組織每秒 10 個請求的上限。
- 別名可能會被移到更新的版本，所以實驗要寫死明確的版本 ID。

## API 形狀

- **它不是 chat completions。**
  - Perplexity 直連：`POST https://api.perplexity.ai/v1/decisions`
  - OpenRouter：`POST https://openrouter.ai/api/alpha/decisions`。這是業主提供的 OpenRouter 官方範例，模型 ID 寫成 `perplexity/pplx-decider-flash-v1.2`。注意路徑裡有 **alpha**。
- **請求格式：** `state` 可以是字串、物件或陣列，能放文字和圖片。`questions` 是一個以名稱為 key 的物件。
- **三種題型：**

  | 題型 | 用途 | 回傳 |
  |---|---|---|
  | `noul` | 是／否 | 0 到 1 的機率 |
  | `choice` | 1 到 255 個選項，每個選項附 `criteria` 說明 | 最可能的選項、`confidence`、`probabilities` |
  | `score` | 有序等級，最多 10 級 | 機率加權的分數和完整分布 |

- **它不生成文字，也不解釋理由。**
- **上下文：** `state` 加上任一個問題的上限是 256K token，請求本體上限 32 MiB。
- **預設不做網路搜尋。** 只有設定 `mode: "web_grounding"` 才會搜尋，Lancet 不該開。
- **官方推薦用途之一**是拿長篇原文檢查某個說法，這正是判斷證據夠不夠。不過文件裡沒有這個任務的完整範例。

## 延遲（官方數據，不同日期、不同模型，只能當量級參考）

| 輸入規模 | 延遲 |
|---|---|
| 幾百 token | 不到 2 秒 |
| 約 190K token | 14 秒 |
| 約 248K token | v1.2 約 53 秒，flash 約 16 秒 |

逾時會在大約一分鐘後回傳 504。官方沒有給百分位數。

## 成本估算

- **前提假設：** 一輪判斷大約 3 到 5K token 的證據，這是估計，還沒實測。
- **金額：** v1.2 每次約 $0.0001，幾乎可以忽略。
- **真正的成本在延遲。** 小輸入時大約 1 到 2 秒，比 rerank 的 +289 ms 高很多，而且每一輪 loop 都要付一次。

## 在 Lancet 的建議用法

- **用 `choice` 題型**，選項設成 {足夠、改寫查詢、換 graph、語料裡沒有}，一次呼叫就同時決定「夠不夠」和「下一步做什麼」。也可以用 `noul` 只判斷夠不夠，把動作選擇交給另一層。
- **`state` 放什麼：** 問題本身，加上 rerank 後的 top-k 證據，證據要保留 `<PUBLISHED>` 日期標頭，這樣時間類題目才判斷得出來。
- **閾值：** 在 dev set 上選定，寫進預先註冊並凍結。
- **評估：**
  - **標準答案**是逐題的「reader 用這批證據有沒有答對」，可以直接用現有的 `answer_usable`。拿 decider 的機率對它算 ROC-AUC。
  - **事先定上限的是誤判證據已夠的比例**，也就是證據缺一塊卻被放行。comparison 和 temporal 題型特別容易出這種錯。
  - **對照組：** reader 自己判斷；logprob 不確定度（見調查文件附錄的 logprobs 驗證）；不用 gate、固定只跑一輪。
- **要記住的限制：** 它判斷的是一般意義上「看起來夠不夠」，不是「這個 reader 答不答得出來」。這正是要跟上面的對照組比的原因。

## 風險與未確認事項

- **OpenRouter 端點是 alpha 版。** 介面可能會變，跑實驗時要記下呼叫當天的端點和請求格式。
- **OpenRouter 上的價格已實測確認（2026-11-05）。** 每 1M 輸入 token $0.02，和 Perplexity 直連相同，回應的 `usage.cost` 有直接列出。公開的 `/api/v1/models` 列表裡仍然沒有這兩個模型。
- **能不能釘住 provider 仍未確認。** 實測回應的 provider 是 Perplexity，模型解析為 `perplexity/pplx-decider-v1.2-20261016`。這種帶日期的版本 ID 應該寫進 journal。這個問題會影響「LLM provider 不是受控變數」這個已知限制，gate 模型同樣適用。
- **Lancet 現有的 OpenRouter client 只走 chat、embed、rerank。** 接 decisions 端點需要新增一個 port，形狀要另外設計。
- **權重：** 搜尋結果說早期的 v1-27b 以 Apache 2.0 開源在 Hugging Face，基底是 Qwen3.8-27B，但官方文件沒有提到，v1.2 是否開源也不知道。如果有開源，之後可以本地跑來消掉延遲，也能把 provider 變成受控變數。

## 實測結果（2026-11-05）

業主說「都做」之後，兩項下一步都做完了。腳本和逐題結果在 [`pplx-decider-smoke/`](pplx-decider-smoke/)（`sep_test.py`、`sep_ref1.jsonl`）。

### 1. 單次呼叫

- **呼叫方式：** `POST https://openrouter.ai/api/alpha/decisions`，直接用現有的 `OPENROUTER_API_KEY`。
- **請求格式：** 跟 Perplexity 官方文件一致。題目文字的欄位叫 `instructions`，不是 `question`。
- **回應：** 帶 `usage.cost`，也就是 OpenRouter 會直接回報花費。
- **127 個輸入 token：** 花費 $0.00000254，延遲 0.48 到 0.64 秒。
- **同一個小請求連送三次，機率完全相同**（0.99805）。但 1K token 的輸入並不是完全確定的：v1.2 在同樣 100 題上重跑一次，逐題機率最多差了 0.112（見下方 flash 比較）。

### 2. MHR dev 的區分測試

- **資料：** S3m dev 的 reference arm，也就是 run `2026-11-01-s3m-ref1-multihop_rag_s3m_dev`：hybrid+rerank+metadata，DeepSeek reader，100 題（90 題非 null、10 題 null），rerank 全部是 `completed`。
- **輸入：** 送給 decider 的 `state` 是問題加上 context export 裡的 8 段證據，每段帶標題、來源和發布日期。**沒有送 reader 的答案或標準答案。**
- **題型：** `noul`，instructions 是「只根據上面的證據，一個仔細的讀者能不能正確且完整地回答這個問題？只有在問題需要的每個事實都在證據裡時才回答 true」。
- **標籤：** reader 答案的 `answer_usable`，在非 null 題目裡 78 題為是、12 題為否。

**區分能力**（非 null 題目，usable 為是 vs 否；95% CI 是逐題 bootstrap 2,000 次）：

| 訊號 | ROC-AUC | 95% CI |
|---|---|---|
| pplx-decider P(足夠) | **0.768** | 0.611 – 0.898 |
| rerank 最高分（免費基準） | 0.613 | 0.442 – 0.769 |
| rerank 第 1、2 名分差 | 0.588 | — |

- **decider 和 rerank 最高分的 AUC 差：** 95% CI 為 -0.051 到 0.343，**沒有顯著差異**。只有 12 個「否」，樣本太小。
- **null 題目分得非常乾淨：** usable 為是 vs null 的 AUC 是 0.994，null 的平均機率只有 0.007。把 null 也算成「不夠」時，AUC 是 0.871。
- **按題型：**

  | 題型 | 題數 | usable | AUC |
  |---|---|---|---|
  | comparison | 36 | 32 | 0.891 |
  | temporal | 23 | 15 | 0.633 |
  | inference | 31 | 31 | 全部 usable，算不出 |

  時間類題目分得最差，跟 #167 的疑點方向一致。

**門檻的取捨**（非 null 90 題，null 10 題）：

| 門檻 | 放行的非 null 題 | 放行裡 usable 的比例 | 被擋下的 usable | 放行的 null |
|---|---|---|---|---|
| 0.5 | 57 | 54/57 | 24 | 0/10 |
| 0.8 | 47 | 45/47 | 33 | 0/10 |
| 0.9 | 38 | 36/38 | 42 | 0/10 |

**成本與延遲：**
- 平均每題 1,049 個輸入 token，最多 1,346。這比原本估計的 3 到 5K 小很多，因為只有 8 段證據。
- 100 題總共 $0.00208。
- 延遲平均 0.74 秒，p50 0.63、p95 1.44，最大 2.75 秒。

### v1.2 和 flash 的配對比較（2026-11-05）

- **作法：** 同樣 100 題、同樣的 `state` 和 instructions，兩個模型交錯送出，也就是同一時段、逐題配對。腳本是 `sep_test2.py`，結果是 `sep_ref1_both.jsonl`。
- **版本：** 模型解析為 `pplx-decider-v1.2-20261016` 和 `pplx-decider-flash-v1.2-20261016`。

| | v1.2（27B） | flash（4B） |
|---|---|---|
| AUC（非 null，usable 是 vs 否） | **0.774** | 0.737 |
| comparison／temporal 的 AUC | 0.891／0.633 | 0.883／0.650 |
| usable vs null 的 AUC；null 平均機率 | 0.994；0.006 | 0.985；0.030 |
| 門檻 0.5：放行題數；其中 usable；被擋的 usable | 56；53；25 | 58；52；26 |
| 門檻 0.8：放行題數；其中 usable；被擋的 usable | 47；45；33 | 34；33；45 |
| 延遲 p50／p95／最大 | 0.61／1.10／2.38 秒 | **0.35／0.46／0.68 秒** |
| 100 題成本 | $0.00209 | $0.00105 |

- **區分能力沒有顯著差異。** AUC 差（v1.2 減 flash）為 +0.036，95% CI -0.056 到 0.126。兩者逐題機率的 Pearson 相關是 0.904。
- **flash 明顯比較快。** 逐題配對的延遲差，平均 0.32 秒、中位數 0.25 秒，而且尾端穩定得多（p95 0.46 秒，v1.2 是 1.10 秒）。
- **門檻 0.5 時，flash 誤判證據已夠的題數是 v1.2 的兩倍**（6 題對 3 題）。這是 Lancet 最在意的錯誤，但題數太少，還不能下結論。
- **兩者對門檻的反應不一樣**（門檻 0.8 時 flash 放行少很多），所以門檻必須按模型各自校準，不能共用。

**暫定預設：v1.2。**
- 預先設定的規則是「p50 少 0.3 秒以上、而且 AUC 沒有明顯變差就選 flash」。配對差的中位數是 0.25 秒，平均 0.32 秒，剛好卡在邊界上。
- 同一個門檻下，v1.2 誤判證據已夠的題數比較少。
- 每輪多 0.25 到 0.3 秒，在 loop 最多跑三輪時，每題最多多約 1 秒。
- 正式比較時，模型選擇應該用更多「否」的樣本重新判斷，並寫成 D-ID。如果 loop 的延遲預算很緊，flash 是合理的替代。

### 解讀

- **它很少誤判證據已夠，但很常誤判證據不夠。** 門檻 0.5 時，放行的 57 題裡只有 3 題 reader 答錯，可是 78 題 usable 裡有 24 題被擋下。
- **原因很可能是「看起來夠不夠」和「reader 答不答得出來」不一樣。** 例如 inference 題全部 usable，reader 會從證據推論出答案，decider 卻嚴格要求每個事實都要明寫。
- **當作 loop 的 gate 來看：** 誤判不夠的代價是多跑一輪，只花成本，不會答錯。誤判已夠則會直接放行錯答。這個方向的偏差對 Lancet 的 fail-closed 原則是有利的。
- **null 題的表現**表示 decider 很適合當「語料裡沒有」的判斷，也就是 `choice` 題型裡那個選項。

### 限制

- 只有一個 arm、一個 reader、100 題 dev，而且只有 12 題「否」。這是冒煙測試，不是結論。
- 門檻和 instructions 都是在同一批題目上看出來的，沒有凍結。正式比較要在 dev 上凍結，再到 held-out 上確認。
- 還沒試 `choice` 題型，也還沒跟 reader 自我判斷或 logprobs 比較。

## 下一步

- 正式比較時：用更大的 dev（例如合併 S3m 的兩個 ref run，或 S2X），凍結 instructions 和門檻，再對照 reader 自我判斷、DeepSeek logprobs 和 rerank 訊號。
- 試 `choice` 題型（足夠、改寫查詢、換 graph、語料裡沒有），看「語料裡沒有」這個選項能不能接手 null 題。

## 來源

- [Decisions API quickstart](https://docs.perplexity.ai/docs/decisions/quickstart)
- [Decisions API reference](https://docs.perplexity.ai/api-reference/decisions-post.md)
- [Perplexity pricing](https://docs.perplexity.ai/docs/getting-started/pricing.md)
- [Denis Yarats 在 X 上的貼文（開源 v1-27b）](https://x.com/denisyarats/status/2105766073866113318)
- 業主提供的 OpenRouter 官方範例（`https://openrouter.ai/api/alpha/decisions`），2026-11-05
