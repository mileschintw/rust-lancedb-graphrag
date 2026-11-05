# Adaptive-RAG 與 agentic retrieval 的分階段規劃

2026-11-05，在一個唯讀的討論 session 裡整理。目前沒有開 issue，也沒有開 lane。之後 grill agentic retrieval 時，這份和 [`agentic與社群摘要優先度.md`](agentic與社群摘要優先度.md) 一起當起點。

## 論文摘要

**Adaptive-RAG: Learning to Adapt Retrieval-Augmented Large Language Models through Question Complexity**
Jeong, Baek, Cho, Hwang, Park（KAIST），NAACL 2024，arXiv [2403.14403](https://arxiv.org/abs/2403.14403)。

**方法。** 用一個小分類器把問題按複雜度分成三級，再交給三種現成策略。LLM 和檢索器都不改。

| 級別 | 策略 |
|---|---|
| A | 不檢索，LLM 直接回答 |
| B | 單次檢索後生成 |
| C | 多步迭代檢索 |

**分類器標籤不用人工標註。** 每題都跑過三種策略，取答對的策略裡最便宜的那個。三種都答錯的題目，依資料集類型給標籤：單跳資料集給 B，多跳資料集給 C。

**實驗設定。** 單跳資料集：SQuAD、NQ、TriviaQA。多跳資料集：MuSiQue、HotpotQA、2WikiMultiHopQA。檢索器只用 BM25。Reader 用 FLAN-T5-XL、FLAN-T5-XXL 和 GPT-3.5-Turbo-Instruct。

**主要結果**（Table 1，各資料集平均）：

| Reader | 方法 | F1 | 每題步數 | 相對時間 |
|---|---|---|---|---|
| GPT-3.5 | Adaptive-RAG | 50.91 | 1.03 | 1.46 |
| GPT-3.5 | Multi-step | 50.87 | 2.81 | 3.33 |
| GPT-3.5 | Single-step | 46.99 | — | 1.00 |
| GPT-3.5 | Oracle 路由 | 62.80 | — | — |
| FLAN-T5-XL | Adaptive-RAG | 46.94 | 2.17 | 3.60 |
| FLAN-T5-XL | Multi-step | 48.85 | 4.69 | 8.81 |

用 GPT-3.5 時，Adaptive-RAG 的 F1 和 multi-step 一樣，花的時間不到一半。實際路由器和 oracle 路由差了約 12 個 F1，表示分類器本身還有很大的進步空間。

**限制。** 作者自己承認：沒有現成資料集可以訓練複雜度分類器，自動產生的標籤可能有錯；只分三級。另外，評估只看 EM/F1，沒有 paired 統計檢定。

**資料來源備註。** Table 1 的數字是從 arXiv HTML v2 逐字讀出來的。分類器規格（T5-Large，770M）、標籤細節和限制，則來自模型對 HTML 後半段的摘要，可信度較低。論文的 C 策略我推測是 IRCoT，但沒有核對。

## 跟 Lancet 的關係

**用得上的部分：**
- **按題路由昂貴的 lever。** graph 在 held-out 上平均沒有顯著增益，每次請求卻多 +198.9 個 prompt tokens。平均沒賺，不代表每一題都沒賺。
- **標籤可以從 paired-arm harness 直接取得。** harness 本來就讓每題在每個 arm 各跑一次並逐題記錄，所以「最便宜且答對的 arm」不用再花錢重跑就能算出來。

**不適用的部分：**
- **A 級（不檢索）跟 Lancet 的設計衝突。** Lancet 預設 fail-closed，沒有證據就短路，不呼叫 LLM。MultiHop-RAG 又是新聞語料，靠模型自身知識答對的空間很小。
- **C 級（多步迭代檢索）目前不存在。** 現在的 5 節點狀態機只做一次 hybrid 檢索加 rerank。
- **按資料集類型分級在 MultiHop-RAG 上會失效。** 這個資料集幾乎全是多跳題。不過論文的標籤看的是「便宜策略實際上有沒有答對」，不是題目名義上幾跳，所以按實際結果切，還是可能有路由空間。

**論文完全沒處理的部分：** query rewriting、在 dense／BM25／graph 之間選工具、依檢索信心決定要不要重試。這些更接近 IRCoT、Self-RAG、CRAG 這一類，grill 前可以補一份文獻。Lancet 已經有的 rerank 分數和 `NO_EVIDENCE` 短路，算是 CRAG 式「檢索不佳時改走另一條路」的天然觸發點。

## 對 agentic grill 議題的補充

對照 [`agentic與社群摘要優先度.md`](agentic與社群摘要優先度.md) 列的 grill 議題：

| grill 議題 | 這篇論文提供的東西 |
|---|---|
| 誰判斷資訊夠不夠 | 第三種選項：在進 loop **之前**用小分類器判斷要不要進。這是成本最低的作法，應該當作要先排除的對照方案 |
| 評測：要比的固定檢索基準 | agentic arm 只贏過 hybrid+rerank+metadata 還不夠，也要跟「路由器」或「oracle 路由」比，否則多花的輪數說不過去 |
| 指標：準確率，或準確率對成本 | 論文本來就用 F1 對每題步數和時間來比，可以直接沿用這個框架 |

## 對 S3 分析計畫的建議（凍結前）

這是一個免費、可以考慮放進 D-291 的探索性分析：

- **Oracle 路由上界。** 用現有的 paired-arm 結果，逐題取 graph 開或關裡答對的那個，算出「按題路由 graph」最多能拿到多少。
- 如果上界只比 hybrid+rerank+metadata 高一點點，按題路由 graph 和讓 agent 決定要不要用 graph 的空間都很小。這會影響 agentic 的動作設計，也影響它和社群摘要誰先做。
- **注意事項。** 單一 seed 下，逐題取較好的那個一定會因為雜訊而偏高，所以只能當**探索性**分析，不能放進主要假說和 Holm family。而且必須在 D-291 凍結前寫進去，否則就算事後分析。
- 這一項和 #167（graph 按題型拆開）性質一樣，都是決定下一步方向的免費訊號。

## 分階段建議：前置分類器和後置 decision model 分開

**結論：分成兩個 phase。** Phase A 做後置 decision model，也就是 agentic loop。Phase B 做前置分類器，而且列為有條件的 phase，看 Phase A 的數據再決定做不做。

**為什麼要分開：**

1. **有依賴關係。** 分類器的標籤要逐題比較「單次檢索有沒有答對」和「agentic loop 有沒有答對」。loop 沒做出來、沒在 dev 上跑過，就沒有 C 級可以路由，也沒有標籤可以訓練。
2. **放在一起，效果會分不清是誰帶來的。**
   - Phase A 問：agentic loop 比固定的 hybrid+rerank+metadata 好多少、多花多少？
   - Phase B 問：在不明顯損失效果的情況下，路由能省多少成本？它的比較基準是「每題都走 agentic」，不是固定檢索。
   - 兩者的預先註冊和 Holm family 應該分開。
3. **Phase A 的結果就是 Phase B 的 go/no-go 閘門。**

   | Phase A 的結果 | Phase B |
   |---|---|
   | agentic 在 dev 上沒贏過固定檢索 | 取消，沒有東西可以路由 |
   | agentic 贏了，成本也還能接受 | 價值很小 |
   | agentic 贏了，但輪數或成本很高 | 值得做 |

4. **後置模型可能已經涵蓋前置分類器的大部分功能。** Lancet 不允許不檢索就回答，所以 A 級本來就不存在。剩下的 B 和 C 之分，等於第一次檢索之後問一句「夠不夠」，而這正是後置 decision model 在做的事，而且它看得到實際撈回來的證據，資訊比只看問題的分類器多。前置分類器剩下的唯一好處，是省掉第一輪判斷呼叫的成本和延遲。這筆帳要等 Phase A 量出那次呼叫的實際花費才算得出來。

**Phase A 要先留好的東西**（成本很低，Phase B 就不用回頭改架構）：

- **路由的介面。** 在狀態機裡留一個「進不進 loop」的決策點，設計成 port（比照 `Reranker` port）。Phase A 先放一個「永遠進」的實作。
- **逐題特徵寫進 journal。** 例如題型、第一次檢索的 rerank 分數分布、loop 跑了幾輪、每輪的花費。Phase B 就能直接拿來訓練和評估，不用再重跑付費的 run。
- **事先切好 split。** Phase B 的分類器要用 dev 的結果訓練、在 held-out 上評估。Phase A 預先註冊時就把這個切分講清楚，避免同一批題目又訓練又評估。

## 待決事項

- 要不要把 oracle 路由上界列進 S3 分析計畫的探索性分析（D-291 凍結前）？
- grill agentic 時，Phase B 是否要寫成正式的條件式 phase，連同觸發門檻（例如每題平均輪數或成本超過多少）一起定下來？

## 後續更新（2026-11-05）

本文的分階段結論已經被 [`agentic檢索決策點調查.md`](agentic檢索決策點調查.md) 第 5 節修正：前置路由不再列為獨立的 Phase B，降級為第一個 agentic phase 的可能優化；「不一定要檢索」改列為獨立的後續議題。文獻調查和評測設計也都在那份文件裡。
