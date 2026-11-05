# Agentic retrieval 的決策點：文獻調查與 Lancet 的取捨

2026-11-05 整理。前一份是 [`Adaptive-RAG與agentic分階段.md`](Adaptive-RAG與agentic分階段.md)，本文補充並部分修正它的分階段結論。目前沒有開 issue，也沒有開 lane。

文獻部分由一個背景調查 agent 完成。它用 arXiv API 核對了下列 37 個 arXiv ID 的標題、第一作者和日期。標 **[記憶]** 的內容是 agent 憑記憶寫的，沒有讀原文確認；其餘都讀過原始來源。

## 1. 「要不要檢索／夠不夠」在哪裡決定

### (a) 檢索前的獨立路由器或分類器

| 作法 | 機制 |
|---|---|
| Adaptive-RAG（2403.14403，2024） | 小分類器把題目分成不檢索／單步／多步 |
| SKR（2310.05002，2023） | 用模型的自我知識判斷要不要檢索 |
| SlimPLM（2402.12052，2024） | 小代理模型先寫草稿答案，用草稿的缺口決定要不要檢索、檢索什麼 |
| RouteLLM（2406.18665，2024） | 在強弱兩個 LLM 之間路由以節省成本，不是在檢索方式之間路由 |
| LlamaIndex RouterQueryEngine | 由 LLM 或 Pydantic selector 從多個 query engine 選一個（[文件](https://developers.llamaindex.ai/python/examples/query_engine/routerqueryengine/)） |
| semantic-router（aurelio-labs） | 用 embedding 相似度路由 **[記憶]** |

### (b) 檢索後的評估器或 gate

| 作法 | 機制 |
|---|---|
| CRAG（2401.15884，2024） | 評估器把撈回來的文件分成正確／錯誤／模糊三類，再精煉文件或改用網路搜尋 |
| LangGraph agentic RAG 教學 | `grade_documents` 這條條件邊：相關就去 `generate_answer`，不相關就去 `rewrite_question`（[文件](https://docs.langchain.com/oss/python/langgraph/agentic-rag)） |

### (c) LLM 在 loop 的每一步自己決定，包括第 0 步

| 作法 | 機制 |
|---|---|
| ReAct（2210.03629，2022） | 推理和工具呼叫交錯進行 |
| Search-o1（2501.05366，2025） | 推理模型在思考鏈中途發出搜尋 |
| LangGraph 的 `generate_query_or_respond` | 「agent 的決策點」：檢索器綁成工具，模型不呼叫工具就直接結束、不檢索 |
| Deep research agents | 兩篇 2025 年綜述（2508.05668、2506.18959）都這樣描述 |
| IRCoT（2212.10509，2022） | 前身作法：按固定節奏交錯檢索和推理，不是學出來的決策 |

### (d) 生成過程中觸發檢索

| 作法 | 觸發條件 |
|---|---|
| FLARE（2305.06983，2023） | 接下來要生成的 token 信心低 |
| Self-RAG（2310.11511，2023） | 生成時輸出 Retrieve 等 reflection tokens |
| DRAGIN（2403.10081，2024） | 用 token 不確定度和 attention 衡量即時的資訊需求 |
| Rowen（2402.10612，2024） | 跨語言或跨模型的答案不一致 |
| ADAPT-LLM（2404.19705，2024） | 模型被訓練成不知道答案時輸出檢索 token |

### (e) 用強化學習訓練的搜尋 agent

- **Search-R1（2503.09516）、R1-Searcher（2503.05592）、ReSearch（2503.19470）、DeepResearcher（2504.03160），都是 2025 年。** 策略在推理中學會何時搜尋，獎勵主要看最後答案。
- **新一批工作改成獎勵「不搜尋」。** R1-Searcher++（2505.17005）讓模型動態選擇用內部知識還是外部知識。IKEA（2505.07596）用「知識邊界感知獎勵」壓低不必要的檢索，論文說檢索次數「顯著減少」。
- **[記憶]** 基本款的 Search-R1 類 agent 在第 0 步幾乎一定會搜尋。

### (f) 不確定度和內部狀態探針（2024–2025）

| 作法 | 機制 |
|---|---|
| SeaKR（2406.19215） | 從內部狀態讀出自我覺察的不確定度 |
| CtrlA（2405.18727） | 用內在表徵方向控制檢索 |
| UAR（2406.12534） | 在 hidden states 上接輕量分類器，並提出 AR-Bench |
| Probing-RAG（2410.13339） | 在中間層接 probe |
| DeepRAG（2502.01142） | 把「檢索或用參數知識」建模成逐步的 MDP |
| Self-Routing RAG（2504.01018） | 一次 pass 內選擇知識來源，包括模型自己 |

## 2. 「主流是後置 gate」的說法站得住嗎

**原本的說法要修正。** 之前對話裡說過兩個版本：「主流是後置 gate」，以及「獨立前置路由器多半只是成本優化」。兩者都不夠準確。

**支持的證據：**
- **Li et al.（2507.09477，2025）** 把 RAG 分成 Reasoning-Enhanced、RAG-Enhanced Reasoning 和 Synergized（agentic）三類，後者是「LLM 迭代交錯搜尋與推理，達到 SOTA」。
- **Singh et al.（2501.09136）** 把 agentic RAG 描述為內建 reflection、planning、tool use，並按 agent 數量、控制結構、自主程度、知識表示來分類。只讀過摘要。
- **使用最廣的框架教學（LangGraph）** 正是這個形狀：第 0 步由 LLM 決定，檢索後再評分。

**需要小心的地方：**
1. **前置路由器在產品中仍然常見。** LlamaIndex router 和 semantic-router 常用來決定查**哪個來源**，不只是要不要檢索。說它「只是成本優化」低估了它。
2. **嚴謹的比較反而偏向便宜的決策方法。** Moskvoretskii et al.（2501.12835，2025）比較了 35 種方法，發現不確定度估計在效率和自我知識上常常勝過複雜的 pipeline，而 Adaptive-RAG 在複雜的多跳題上表現最好。所以獨立的決策組件不是過時的作法，它們的競爭力很強。
3. **在 loop 裡做決定，不代表第 0 步決定得好。** RL 搜尋 agent 普遍檢索過多，所以 2025 年才有 IKEA、R1-Searcher++ 專門加上不檢索的訓練壓力。
4. **這個三分法不是任何一篇綜述的原話**，引用時不要掛在它們名下。

**建議的說法：**

> 近期的 agentic RAG 系統，從 LangGraph 這類框架範本到 Search-R1 這類 RL 訓練的搜尋 agent，通常讓 LLM 透過工具呼叫在每一步決定要不要檢索、檢索什麼，常見的作法是檢索後再檢查文件是否相關。檢索前的獨立路由器（Adaptive-RAG、LlamaIndex router）和基於不確定度或 probe 的觸發（SeaKR、UAR、DRAGIN）仍然是活躍的替代方案；評測顯示它們往往更便宜，而且能追上甚至勝過 loop 內的 LLM 判斷（Moskvoretskii et al., 2025）。

## 3. 「把 gate 也放到最前端」是不是就等於 Adaptive-RAG

**架構上是同一個決策點，但不等於這篇論文的貢獻。**

- **結構一樣：** 檢索前只看題目就決定走哪條路。
- **差別在成本：** Adaptive-RAG 的重點是用便宜的分類器做這個決定，判斷本身幾乎不花錢。LLM gate 放在最前端，每題都多一次 LLM 呼叫。
- **它其實就是 (c) 類：** 前後兩端的判斷交給同一個 LLM，就是工具呼叫式 agent 的第 0 步。比較準確的描述是「統一的 agent loop，第 0 步也由模型決定」，Adaptive-RAG 則當成對照組：把第 0 步換成便宜分類器，看能省多少、會掉多少。
- **調查補上的另一類對照：** 不確定度和 probe 類方法（(f) 類），以及 Moskvoretskii et al. 的結論。這類方法需要讀 logprobs 或 hidden states。Lancet 透過 OpenRouter 呼叫託管模型，最多拿得到 logprobs，拿不到 hidden states，所以 (f) 類裡只有基於 token 不確定度的作法可行。這點還沒有驗證。

## 4. 「不一定要檢索」怎麼評測、怎麼證明成果

### Lancet 目前的狀態

Lancet 已經有一條 model-only 路徑：`allow_model_only`，回答時帶 `NOTICE_CODE_MODEL_ONLY`（`docs/api-contract.md`）。但它只在檢索撈不到東西時才觸發，而且預設是關的（`config/config.toml` 的 `allow_model_only_answers = false`，D-10/D-12）。「主動跳過檢索」會改變 fail-closed 的預設，需要新的 D-ID，很可能也要一份 ADR。

### 為什麼 MultiHop-RAG 證明不了

- **題目全是語料題。** 最好的 gate 就是「永遠檢索」，MHR 頂多能證明 gate 沒有誤跳。
- **有記憶污染的疑慮。** 調查 agent 說 MHR 的新聞在模型訓練截止日之後，這只對 2023–2024 年的模型成立。MHR 的新聞是 2023 年底的，而 `deepseek-v4-flash-0731` 的訓練資料很可能已經涵蓋那段時間，所以不檢索也答對，可能只是背過。
- **一個便宜的診斷可以順便做。** 在 MHR 上跑一個「永遠不檢索」的 arm，就能量出 reader 對這個語料記得多少。這是之後所有 adaptive 結論的背景值。

### 文獻怎麼做

**評測集：**

| 資料集 | 內容 |
|---|---|
| PopQA（2212.10511） | 題目按實體熱門度分層；原論文只在熱門度低於門檻時才檢索 |
| RetrievalQA（2402.16457） | 1,271 題需要檢索（RealTimeQA、FreshQA、ToolQA、長尾 PopQA、TriviaQA），另有 1,514 題 GPT-2 閉卷就能答，當作不檢索的題目 |
| FreshQA（2310.03214） | 變動快的事實和前提錯誤的題目 |
| AR-Bench（2406.12534） | 專門評估檢索時機判斷得準不準 |
| Adaptive-RAG 的混合集 | Moskvoretskii et al. 沿用同樣六個資料集，每個 500 題 |

調查沒有找到 2025 年專門針對「需不需要檢索」的新 benchmark，但這是用搜尋找的，可能有遺漏。

**怎麼衡量決策品質：**
- **準確率對成本。** 準確率或 EM，搭配每題的檢索次數（RC）和 LLM 呼叫次數（LMC）。
- **對照 oracle 標籤，把決策當二元分類。** Moskvoretskii et al. 的標籤是「模型閉卷有沒有答錯」，報告 ROC-AUC、準確率、過度自信和信心不足。他們的 oracle 上界顯示還有很大進步空間。
- **檢索決策的準確度。** RetrievalQA 報告該檢索時有沒有檢索，以及 macro precision、recall、F1。它也顯示 Self-RAG 的閾值從 0.25 調到 0.75，檢索率會從 100% 掉到 0%。所以閾值類方法一定要校準。

**怎麼處理記憶污染：**
- **標籤按模型定義。** 「需不需要檢索」看的是**這個** reader 閉卷有沒有答對，所以標籤本來就和模型綁在一起。
- **用強模型過濾。** RetrievalQA 只保留 GPT-4 閉卷 token F1 = 0 的題目。
- **選模型不可能看過的資料。** 例如即時資訊、合成的私有資料，或長尾題目。

### 建議給 Lancet 的評測設計

**題目組成：**
- **語料題：** MHR，或比 reader 訓練截止日更新、或合成的私有文件，確保非檢索不可。
- **一般知識題：** 例如 PopQA 高熱門度題目、TriviaQA。
- **（選配）超出範圍的題目和閒聊。**

**標籤：** 用我們自己的 reader 閉卷跑一次，答對的題目標為「不需檢索」。

**Paired arms：** 永遠檢索、永遠不檢索、gate 路由、oracle 路由。

**指標：**
- 準確率對 RC/LMC 的曲線。
- gate 對 oracle 的 ROC-AUC、precision、recall。

**事先註冊的失敗門檻：** 語料題被誤跳的比例上限。跳過檢索又答錯，就是一個沒有引用的自信錯答，所以門檻要比照 null-abstention guard 定得嚴一點。

**要證明的主張：** 省下的成本和多出來的無引用錯答之間的取捨，落在事先定好的門檻內。

## 5. 對規劃的影響（修正前一份文件的分階段結論）

1. **第一個 agentic phase 只做 loop 本身**（何時停、怎麼補證據、換哪種檢索），完全在 MHR 上評估，維持一定要先檢索的 fail-closed 設計。第 0 步固定為「先做一次 hybrid+rerank」。
2. **前置路由降級為那個 phase 的可能優化，不再列為獨立的 Phase B。** 只有 journal 顯示第一輪經常白花、而且白花的題目從題目本身就能預測時，才值得獨立做。比較便宜的替代作法是把題型當 gate 的輸入特徵。
3. **「不一定要檢索」列為獨立的後續議題。** 它需要新的混合資料集、閉卷標籤和新的預先註冊，還要改動 D-10/D-12 的 fail-closed 預設，工作量比 agentic loop 大一個等級。
4. **評測的對照組要包含一個便宜的決策方法。** 根據 Moskvoretskii et al.，至少要有一個基於 token 不確定度（logprobs）的觸發，或一個小分類器。否則「agentic loop 比較好」的結論只贏過固定檢索，沒有贏過便宜的替代方案。

## 待決事項

- 要不要開一個獨立議題做「不一定要檢索」？如果要做，資料集選哪個（RetrievalQA 或自己混合）？
- OpenRouter 上的 reader 能不能拿到 logprobs，以決定第 4 點的便宜對照組是否可行？這可以免費驗證。
