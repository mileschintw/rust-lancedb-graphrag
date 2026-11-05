# pplx-decider 當後置 gate 的可行性

2026-11-05 整理。延續 [`agentic檢索決策點調查.md`](agentic檢索決策點調查.md)：想用一個非 reader 的 decision model，在檢索之後判斷證據夠不夠、下一步做什麼。目前沒有開 issue，也還沒實測。

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
- **OpenRouter 上的價格未確認。** 背景 agent 抓 OpenRouter 的模型頁面得到 404，公開的 `/api/v1/models` 列表裡也沒有這兩個模型，但業主在 OpenRouter 上看得到。
- **能不能釘住 provider 未確認。** 這會影響「LLM provider 不是受控變數」這個已知限制，gate 模型同樣適用。
- **Lancet 現有的 OpenRouter client 只走 chat、embed、rerank。** 接 decisions 端點需要新增一個 port，形狀要另外設計。
- **權重：** 搜尋結果說早期的 v1-27b 以 Apache 2.0 開源在 Hugging Face，基底是 Qwen3.8-27B，但官方文件沒有提到，v1.2 是否開源也不知道。如果有開源，之後可以本地跑來消掉延遲，也能把 provider 變成受控變數。

## 下一步（免費或極便宜）

- 用業主的 key 呼叫一次 `alpha/decisions`，記下三件事：實際延遲、回應的 `usage`、計費金額。
- 從 MHR 的 dev 結果抽幾題，分別放 `answer_usable` 為是和否的證據，看看 `noul` 的機率能不能把兩組分開。

## 來源

- [Decisions API quickstart](https://docs.perplexity.ai/docs/decisions/quickstart)
- [Decisions API reference](https://docs.perplexity.ai/api-reference/decisions-post.md)
- [Perplexity pricing](https://docs.perplexity.ai/docs/getting-started/pricing.md)
- [Denis Yarats 在 X 上的貼文（開源 v1-27b）](https://x.com/denisyarats/status/2105766073866113318)
- 業主提供的 OpenRouter 官方範例（`https://openrouter.ai/api/alpha/decisions`），2026-11-05
