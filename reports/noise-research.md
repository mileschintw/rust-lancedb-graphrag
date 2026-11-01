# LLM 輸出非決定性與抽樣雜訊：小題集 paired 評估的做法（研究報告）

日期：2026-10-31。標記：**[來源]** 表示可直接追到下方 URL 的陳述；**[推論]** 表示依來源與我們的數字推出、未經外部驗證的結論。

## 1. 簡答

- **[來源]** 現行做法（Anthropic / Miller 2024）是把「題目」當成抽樣單位：每題對同一模型重抽 K 次，取每題平均分當題目分數，再對兩模型的每題分數差做 paired 分析（paired SE、CI、相關係數），並用含 K 的 power 公式決定題數與 K。題目彼此相關時用 clustered SE。不要為了降低變異去調低 temperature。
- **[來源]** temperature 0 在 hosted 推論上本來就不保證決定性：主因是 kernel 缺乏 batch invariance，伺服器負載會改變 batch size，進而改變數值結果。只有 provider 端改用 batch-invariant kernel 才能消除，client 端做不到。
- **[推論]** 對我們（n=90、二元指標、成本約 $2.5/全 arm 一輪）來說：每題每 arm 抽 K=5（預算允許可到 10），用每題平均分的差 d_i 做 paired permutation（sign-flip）檢定或 paired t，再做 Holm。Resampling 只能把 MDE 從約 10 pt 壓到約 8 pt。要偵測 2–5 pt 的差距，只能加題目，加 K 沒用。

## 2. 證據

### 2.1 Miller (Anthropic), "Adding Error Bars to Evals" (2024)
URL：https://arxiv.org/abs/2411.00640（全文 https://arxiv.org/html/2411.00640），部落格：https://www.anthropic.com/research/statistical-approach-to-model-evals
- [來源] 題目分數 = 題目的真實平均 + 抽樣雜訊。依 law of total variance，每題取 K 次平均時，條件變異項變為 E[σ_i²]/K。
- [來源] 部落格建議：有 CoT 時，"resampling answers from the same model several times, and using the question-level averages as the question scores"。沒有 CoT 時，改用 next-token 機率。
- [來源] Paired SE：SE_paired = sqrt(Var(s_A − s_B)/n) = sqrt(SE_A² + SE_B² − 2·SE_A·SE_B·Corr)。作者建議 "using the paired version ... wherever practicable"。前沿模型間的題目分數相關約 0.3–0.7。
- [來源] Power / sample size：n = (z_{α/2}+z_β)² · (ω² + σ_A²/K_A + σ_B²/K_B) / δ²，其中 ω² 是「真實」題目分數差的變異。論文範例中，K 由 1 增到 10 時，MDE 由 13.2% 降到 7.5%（n=198）。
- [來源] K 的選法：取到 E[σ_i²]/K ≪ Var(x) 即可，再往上加 K 對 SE 幾乎沒有幫助。
- [來源] "In neither case should the sampling temperature be adjusted for the sake of reducing variance in the scores."
- [來源] 題目成群（例如同一篇文章出多題）時用 clustered SE，實例中可大到 naive SE 的 3 倍。Bootstrap 只在抽樣設計或 estimator 複雜時才需要。
- [來源] 論文的 SE 與 CI 以 CLT/z 為基礎，沒有討論 t-test 或 sign test。

### 2.2 小樣本下 CLT 不可靠
- [來源] Bowyer, Aitchison, Ivanova, "Position: Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints"（ICML 2025）：在小型 benchmark 上，CLT 型 error bar 通常會低估不確定性，作者建議改用其他 frequentist 或 Bayesian 方法。https://arxiv.org/abs/2503.01747
- [推論] n=90 落在這個範圍，因此主檢定應採用不依賴 CLT 的方法：exact sign-flip permutation，或 bootstrap 作為輔助。

### 2.3 Thinking Machines Lab, "Defeating Nondeterminism in LLM Inference" (2025)
URL：https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/
- [來源] 常見的「浮點非結合性加上並行」解釋並不完整。單次 forward pass 本身是決定性的，真正的原因是 kernel 不具 batch invariance：同一請求的數值結果取決於當下 batch size，而 batch size 隨伺服器負載而變。
- [來源] 實驗：Qwen3-235B 在 temperature 0 下跑 1000 次，得到 80 種不同 completion，在第 103 個 token 開始分岔。改用 batch-invariant kernel 後，1000 次完全相同，但有效能代價（26s → 42s）。
- [推論] 這篇文章沒有談 hosted API。依其機制，client 端無法消除這個雜訊，必須由 provider 部署 batch-invariant kernel。

### 2.4 Hosted API 的 temperature 0 實測
- [來源] Atil et al., "Non-Determinism of 'Deterministic' LLM Settings"：5 個模型、8 個任務，在 temperature 0 加固定 seed 下各跑 10 次，accuracy 差距最高約 15%。解析後答案的一致率（TARa）明顯高於原始字串的一致率（TARr）。輸出越長越不穩定。作者建議報告多次執行的 max–min。https://arxiv.org/html/2408.04667v5
- [推論] 我們觀察到 answer line 有約 13% 改變、二元結果只有約 4% 翻轉，正是 TARr 和 TARa 的差異，屬於預期中的現象。
- [來源] Hochlehnert et al., "A Sober Look at Progress in LM Reasoning"：AIME（30 題）上 Pass@1 跨 seed 的標準差達 5–15 pt。作者建議小 benchmark 至少跑 30 個 seed 並報告 mean±std。即使開啟 deterministic 演算法，硬體與後端差異仍造成高達 6–8% 的差異。作者也建議比較時每個模型各用其最佳 sampling 設定。https://arxiv.org/html/2504.07086v2
- [來源] 2025 年 reasoning 論文常見 avg@32 至 avg@128 的做法，其中 Markovian Thinker 建議 k≥64（Var ≈ p(1−p)/(Q·k)）。https://arxiv.org/pdf/2510.06557。注意：這些都是 30 題級、純 sampling 雜訊很大的數學 benchmark，題目分數本身就接近 0/1 之間的中段。
- [來源] lm-evaluation-harness 提供 `repeats`（每題重跑次數，預設 1），並搭配 `majority_vote` / `take_first_k` filter，但沒有給出建議次數。https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/task_guide.md

### 2.5 其他變異研究（相關度較低）
- [來源] Madaan et al. 2024, "Quantifying Variance in Evaluation Benchmarks"：研究對象是 **pretraining seed** 的變異，不是推論抽樣雜訊。小題集（COPA、HumanEval）的 seed std 與 CI 最大。作者建議改進幅度必須超過 seed variance，並優先使用連續指標。https://arxiv.org/html/2406.10229v1
- [來源] Heineman et al. 2025, "Signal and Noise"（AI2）：提出以 signal-to-noise ratio 選 benchmark 與指標，連續指標（如 perplexity）的 SNR 優於 accuracy。https://arxiv.org/abs/2508.13144
- [推論] 這兩篇與我們的關聯在於一個共同原則：二元指標雜訊大，把每題 K 次平均變成 [0,1] 的連續分數，本身就是一種提高 SNR 的做法。

### 2.6 Claude 5.5 系列的 temperature / thinking 限制（官方文件）
- [來源] Opus 5.5：必須省略 `temperature`/`top_p`/`top_k`。Adaptive thinking 永遠開啟，送 `thinking: {type: "disabled"}` 會得到 400。官方原文："If you were using `temperature = 0` for determinism, note that it never guaranteed identical outputs on prior models." https://platform.claude.com/docs/en/models/opus-5-5/migration-guide
- [來源] Sonnet 5.5：sampling 參數會回錯誤。`disabled` 回 400，最低的設定是 `thinking: {type: "between_tools"}`，沒有 tools 時回應只含文字。https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide
- [來源] Haiku 5.5：移除 sampling 參數。Adaptive thinking 預設開啟，以 `effort` 控制思考深度，低 effort 時簡單題可能完全不思考。https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide
- [來源] OpenRouter 預設路由會依權重隨機選 provider。要固定單一 provider，需設 `provider.order: [slug]` 並加 `allow_fallbacks: false`，也可以用 `quantizations` 過濾量化版本。https://openrouter.ai/docs/features/provider-routing

## 3. 對我們的具體建議（以下全為 [推論]，數字是粗估）

**3.1 雜訊量級估算。** 對一題正確機率為 p 的題目，兩次獨立抽樣翻轉的機率是 2p(1−p)。由 deepseek 的 3/68 ≈ 4.4% 翻轉率，可得 E[σ²] ≈ 0.022。由 MDE 10 pt（n=90、α=.05、power .8，係數 2.8）反推，每題差異的總變異 V ≈ 0.10²·90/2.8² ≈ 0.115。若兩 arm 的 σ² 都約 0.022，雜訊占 V 的約 0.044（38%），真實差異的變異 ω² ≈ 0.071。Claude arm 跑的是預設 temperature 加 adaptive thinking，σ² 很可能大於 deepseek 的 temp-0 數值，雜訊占比會更高。這一點需要用試跑資料實測。

**3.2 每題每 arm 的樣本數 K。**

| K | 雜訊項 0.044/K | V | MDE（n=90） | 一輪全 arm 成本 |
|---|---|---|---|---|
| 1 | 0.044 | 0.115 | ~10.0 pt | $2.5 |
| 3 | 0.015 | 0.086 | ~8.7 pt | $7.5 |
| 5 | 0.009 | 0.080 | ~8.4 pt | $12.5 |
| 10 | 0.004 | 0.075 | ~8.2 pt | $25 |
| ∞ | 0 | 0.071 | ~7.9 pt（下限） | — |

建議所有 arm（含 deepseek 參考 arm）都用 **K=5**。若第一輪實測的 Claude σ² 明顯大於 0.022（例如 >0.05），就升到 K=10，預算仍在 $25 以內。K=5 時雜訊項約為 ω² 的 12%，已符合 Miller 的「σ²/K ≪ ω²」條件。2025 reasoning 論文常用的 k=32–64 是為了 30 題、p 接近 0.5 的數學題，套用在我們身上會浪費成本。所有 arm 用相同的 K，可以讓 paired 設計保持對稱。

**3.3 統計量與檢定。**
- 題目分數 s_{a,i} = 該題 K 次 answer_usable 的平均，d_i = s_{A,i} − s_{B,i}，點估計為 mean(d_i)（百分點）。
- 主檢定改用 **exact / Monte Carlo sign-flip permutation test on d_i**。sign test 只看正負號，丟掉了 d_i 的大小，而在 K>1 時 d_i 是分數，丟掉大小等於白白損失 resampling 帶來的 power。permutation 檢定也不依賴 CLT，可以回應 §2.2 的警告。paired t-test（`ttest_rel`）列為交叉檢查，兩者應該接近。Holm 校正照舊。
- CI 用 paired bootstrap，**以題目為重抽單位**，題內 K 個樣本整組帶走，不要把 K 個樣本攤平當作 90·K 個獨立觀測。如果多題共用同一份來源文件或同一個 hop 鏈，就以該群組做 cluster bootstrap 或 clustered SE。
- 一併報告：mean diff、SE、95% CI、Corr(s_A, s_B)，以及每 arm 的平均 within-question 變異 σ̂² = mean(s(1−s)·K/(K−1))。
- 10 題 null 與 90 題 answerable 分開報告。null 題太少，無法單獨檢定，只做描述。

**3.4 2-point 決策邊界。** 差異的 SE 約 sqrt(0.08/90) ≈ 3 pt，MDE 約 8 pt，所以 2 pt 遠小於量測雜訊，「最高點估計」本身就不穩定，換一次抽樣就可能改變排名。建議改寫規則：預設選最便宜的 reader，除非較貴的 reader 在 Holm 校正後顯著較好；或者把邊界放寬到約 1 SE（≈3 pt）。保留 2 pt 也可以，但要明說它是成本偏好的 tie-break 規則，不是統計上的等價證明。以 n=90 不可能證明 2 pt 的 non-inferiority，那需要上百到上千題。

**3.5 加題目還是加 K。** K=1 時要把 MDE 從 10 pt 降到 8 pt，需要 n ≈ 90·(10/8)² ≈ 140 題。K 設到無限大也停在 8 pt 左右。要偵測 3 pt，即使 K→∞ 也需要 n ≈ 7.84·0.071/0.03² ≈ 620 題。結論：K=5 便宜，能拿到約 15–20% 的 MDE 改善，值得做；但若決策真的取決於 2–5 pt 的差距，唯一的出路是擴充題集。

**3.6 temperature / thinking 的處理。**
- Claude 5.5 三個模型都無法設 temperature，thinking 也無法完全關閉（Opus/Sonnet 的 `disabled` 會回 400）。因此 Claude arm 必然是隨機抽樣，只能靠 resampling 處理，不能靠 temp 0。每個 arm 要固定並記錄 `effort` 等級（Opus/Haiku 5.5 預設 medium），以及 Sonnet 是否用 `between_tools`。effort 應視為 arm 定義的一部分，不能混用。
- deepseek 參考 arm 可以維持 temp 0（如果那是正式設定；Sober Look 建議每個模型用自己的最佳設定），但同樣跑 K=5。temp 0 也有約 4% 翻轉，不應把它當成決定性的 arm。另外要用 `provider.order` 加 `allow_fallbacks: false` 固定 OpenRouter provider，以免把 provider 和量化差異混入比較。
- Batch API：每題送 K 個獨立 request，用不同的 `custom_id`（例如 `q017#r3`）。不要在同一個 request 裡要求模型產生多個答案。
- 在報告中寫明：各 arm 的 sampling 條件不同（deepseek temp 0 對上 Claude 預設 sampling 加 adaptive thinking），比較的對象是「各自在可用設定下的 reader」，不是在相同解碼條件下的比較。

## 4. 未解的不確定性

- [推論] 表中的 ω² 與 σ² 是從 3/68 翻轉率和 MDE 10 pt 反推，兩者的估算方式可能不一致。Claude 在預設 sampling 加 thinking 下的 σ² 完全未知，應先跑 K=5 一輪實測，再重算 MDE 與是否升到 K=10。
- [推論] 3/68 是很小的樣本，翻轉率的 95% CI 約為 1%–12%。
- [來源未涵蓋] 找不到 Anthropic 或 OpenRouter 對其服務端 batch invariance 的公開聲明。不同時段的負載可能讓雜訊不是 i.i.d.，因此建議把 K 次抽樣分散在不同時間送出，或至少在報告中記錄送出時間。
- [來源未涵蓋] Haiku 5.5 的 migration guide 沒有明說 `thinking: disabled` 是否會被拒絕，使用前需實測。
- [推論] Permutation 檢定與 Holm 在 3 個比較下的 power 損失沒有計算進 MDE 表。實際 MDE 會再略大一些（Holm 最嚴格的一步相當於 α=.0167，係數約 3.2 而非 2.8，MDE 約放大 14%）。
- [來源未涵蓋] Bowyer et al. 具體推薦哪些小樣本方法，我只讀到摘要，沒有核對全文。
