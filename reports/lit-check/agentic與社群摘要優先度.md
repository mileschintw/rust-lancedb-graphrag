# Agentic retrieval 與社群摘要：優先度分析

2026-11-01，在 coordinator 的分叉 session 裡和業主討論。目前兩者都**不做**；等之後正式 grill 時，拿這份當起點。

## 背景決定

- 業主的方向：應用 AI／LLM 工程師（不走研究職）。對外以部落格和 LinkedIn 為主，不寫論文。
- 主線：先跑完 S3 核心（#163，只跑必跑的格子），再寫結果摘要，接著做 agentic 或社群摘要。
- 下個月 credit 的使用順序（業主：「可以，就這樣做」）：
  1. 優先評測 agentic；
  2. agentic 還沒開始的話，跑 #146，同時並行做 agentic；
  3. 有剩再補 S3 選配的 Sonnet 格子。
- 兩者框架都已經準備好，但實作前都要先正式 grill。

## 兩者各要決定的事（grill 議題）

**Agentic retrieval**
- 誰判斷資訊夠不夠：reader 自己，或另一個較便宜的判斷模型。
- 不夠時的動作：改寫查詢、換一種檢索（hybrid 或 graph）、擴大範圍。
- 停止條件：最多幾輪、每題的成本上限。
- 評測：哪個 dev set、要比的固定檢索基準、指標（準確率，或準確率對成本）。

**社群摘要**
- 分群演算法（例如 Leiden）和分幾層。
- 摘要用哪個模型、成本估算。
- 查詢時怎麼用：只回答全域問題，或和現有檢索混用，以及由誰來決定走哪條路。
- 評測：Local 模式可以直接用 MultiHop-RAG，對照 Han et al.；全域問題則可能需要另一個資料集。
- 摘要要帶發布日期（見下方「日期問題」）。

兩者的評測都比照現行規則：事先凍結、寫成 D-ID，規模可以小一些。

## 比較

| | Agentic retrieval | 社群摘要 |
|---|---|---|
| 故事 | 接續「Claude 因證據不全而選擇不答」：讓它自己把證據補齊 | 檢驗「論文裡 GraphRAG 的提升，換成強基準還在不在」 |
| 發現的銳利度 | 中等，偏向「做出解法」 | 較高，可能挑戰已發表的結果 |
| 面試熱度 | 最高 | 中等 |
| 現成資料 | MHR、2Wiki 的 dev set 都能直接用 | MHR 可以直接對照 Han et al. |
| credit | 多輪呼叫 Claude，自然會用掉 credit | 產生摘要需要一次性的成本 |

**社群摘要的關鍵文獻：**
- Han et al. 2025（arXiv 2502.11371）在 MultiHop-RAG、70B reader 下：Community-GraphRAG Local 71.2，naive RAG 65.8。
- 提升幾乎都來自時間類題目。
- 他們的 RAG 基準只有 dense 向量，沒有 BM25 和 rerank，比我們的 hybrid+rerank+metadata 弱。

## 目前結論

- 稍微偏向 **agentic retrieval 先做**：對履歷和面試最直接，也能把故事接成一條線。不過兩者差距不大。
- **決定前，先做一個免費檢查：** 把 MHR 現有的 graph 結果按題型拆開（文獻缺口 c，已轉告 coordinator 開 issue）。
  - 時間類題目上 graph 已經有提升 → 社群摘要的優先度上升。
  - 完全沒有提升 → 先做 agentic，社群摘要等 S3 的 2Wiki 結果。

## 日期問題（2026-11-01 查證）

- `evidence_metadata` lever 會在每段證據前加上 `<PUBLISHED>` 標頭（`engine/src/prompt.rs` 的 `attach_evidence_meta`）。S2X 匯出的 context 裡，3,200 段全部帶日期，所以主要的 run 沒有缺時間資料。
- 疑點：graph 事實區塊走 `PackCandidate::Graph(fact_block)`，看起來沒有掛 `DocMeta`，也就是不帶日期。這可能讓 graph 在時間類題目上吃虧。
- 推測（未驗證）：Han et al. 在時間類題目上的提升，可能有一部分是因為 graph 那一側帶了時間、naive RAG 那一側沒有。
- 已請 coordinator 併進缺口 c 的 issue 去驗證。修正本身要另開 issue，而且不能更動 S3 已凍結的設定。
