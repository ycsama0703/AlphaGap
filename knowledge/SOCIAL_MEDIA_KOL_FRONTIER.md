# 社媒金融 / KOL 数据前沿扫描（2022–2026）

**用途**：判断任何"用我们 KOL 推特护城河"的 gap 时先读此文。回答两个问题——(1) 文献做到哪了、什么死了；(2) 我们 16年×3712识别KOL 的数据能挖什么文献做不了的。
**最后更新**：2026-06-23（4 个并行文献 agent 扫描合成）。

---

## 0. 一句话结论

别再做"文本→情绪→预测大盘收益"（已知低 SNR，bag-of-embeddings 打赢 fancy time-encoder，与我们编码 gap 的死法一致）。文献反复留白、且恰好吃我们护城河的，是**把 KOL 当作被识别的、可纵向追踪的个体/网络对象**——因为别家数据要么匿名、要么只有 4 年、要么 <1 年加密圈。

---

## 1. 五条线现状

### 线1：情绪/收益预测（饱和，勿碰）
- **无条件情绪不预测次日收益**；只有 event-conditioned（成交量峰值）极性有微弱用处 —— *Event-Aware Sentiment Factors from LLM-Augmented Financial Tweets* (arXiv 2508.07408)。
- 方法天花板就是 bag-of-embeddings + 简单分类器；fancy 编码打不过。代表 *Explainable Tweets MoE* (2507.20535)、FNSPID 系。

### 线2：Finfluencer / 技能（最活跃，最贴我们数据）
- **Finfluencers** | Kakhbod, Kazempour, Livdan, Schürhoff | SSRN 4428232 / AEA 2025 | StockTwits, **~4年**(2013–17)。28% skilled (+2.6%/月), 16% unskilled, 56% **antiskilled** (−2.3%/月)。**反常核心结论：antiskilled 的 follower 反而更多、更强驱动散户 order imbalance**；contrarian 策略 +1.2%/月 OOS。**局限**：技能是**事后全样本静态打标**，非滚动 OOS；follower 当被解释的结果，不当预测特征；无 KOL 间网络。
- **VideoConviction** | KDD 2025 | YouTube 22频道288视频。独立复现：finfluencer 组合跑输 QQQ/SPY，**inverse 策略反赢 (17.9% vs 11.3%)**。无个体纵向技能追踪。
- **Unleashing Expert Opinion from Social Media** | arXiv 2504.10078 | 动态识别 true/inverse expert + 双图注意力(DualGAT)。**局限**：图建在**股票**间非 influencer 间；专家信号只覆盖 ~4% 股票天；**完全不用账号元数据**(无 follower/verified)。
- **StockTwits 2008–2022 数据集** | J. Quantitative Description | 7M+用户550M+帖14年，但**纯匿名ID**。发现：多数人随机水平，少数持续 skilled/unskilled，**技能在月频可检测、日频不行**。这是现存最接近"纵向面板"的基建，但缺身份/follower/verified 层——正是我们有的。

### 线3：信念 / 分歧 / 网络（经济学顶刊）
- **Why Don't We Agree?** | Cookson-Niessner | JF 2020 | 分歧↔异常成交量，within-group 分歧为主因。证券层面。
- **Echo Chambers** | Cookson-Engelberg-Mullins | RFS 2023 | ~40万用户 follow 图：选择性曝光→回音室信念→**事后收益更低**、更多成交。关于 follower 侧信念形成，非 influencer 间分歧当前向信号。

### 线4：注意力 / 扩散 / 跨资产 spillover
- **The Social Signal** | Cookson-Lu-Mullins-Niessner | JFE 2024 | Google Trends 的现代继任者 = cashtag 量 + 自标情绪；"注意力分量"与情绪可分离，且承载新闻周围多数预测内容。
- **Attention Spillover in Asset Pricing** | Chen-An-Wang-Yu | JF 2023 | 注意力跨股溢出有**因果证据**，但链是**屏幕相邻**(listing-code 准随机 UI 链，故意无经济含义)。
- **Joint News, Attention Spillover** (NNTA) | SSRN 2927561 | **新闻共现**网络→共同注意力→反转；NNTA 负向 OOS 预测市场。最接近"共现注意力图"但用新闻、无作者维度。
- **News Diffusion in Social Networks** | RFS 2025 / NBER w30860 | **扩散越快→吸收越快→后续 drift 越低**（正是 Hong-Stein 的检验）。但扩散用**静态地理** SCI 代理，非观测到的推文级传播速度。
- 基线：**原始 mention 量 / abnormal volume / 自标情绪比 / NNTA**——任何网络主张须打赢 NNTA + 自股 abnormal mention。

### 线5：LLM 嵌入当结构/先验（你关注的"结构而非 prompt"）
- **Understanding LLM Embeddings for Regression** | arXiv 2411.14708 (DeepMind) | 嵌入度量本身保 **Lipschitz 连续性** = 模型；唯一"几何当解释变量"的文章。**无金融、无时序**；几何性质与语义质量解耦（大模型不一定给更好 Lipschitz 常数）。
- **LLM Embedding for Regression Priors** | ICAIF 2025 (10.1145/3768292.3770437) | 把上者搬进金融当贝叶斯先验，但**只在 FRED 宏观**、低维；先验有用性取决于先验质量、不可事前度量。
- **A Financial Brain Scan of the LLM** | arXiv 2508.21285 | LLM 经济预测投到概念方向(情绪/技术/择时)并可 steering。但探的是**生成模型的推理**，非真实语料嵌入，无 OOS 交易验证。
- **Cross-Stock Predictability via LLM Semantic Networks** | arXiv 2604.19476 | 10-K 嵌入建 firm 相似图驱动动量溢出。**作者自承"嵌入相似=话题重叠≠经济因果"的伪相关问题**，须外挂 LLM 分类器补。
- **Chronologically Consistent LLMs** | arXiv 2502.21206 | ⚠️ 方法地雷：现成嵌入把**未来知识泄进过去**(2024知识重塑2020文档编码)；时间一致模型显著跑输有前视偏差的——**任何 16 年语料的嵌入信号不做 point-in-time 就是泄漏假象**。既是危险也是可防御的贡献轴。

---

## 2. 我们数据独有的维度（= 文献做不了的）

**护城河**：16年 × 3712个**被识别**KOL（带 follower 轨迹 + verified + tweet_type）、**cashtag 共现图**、同一批人完整时间线。**已知约束**：覆盖=主流KOL×大盘股×16年；小盘/pump 名稀疏（probe-A 已死于数据）；大盘做收益/RV 预测低 SNR（编码 gap 已死，bag 打赢 fancy）。

### 文献一致的盲区
1. **前向 / point-in-time KOL 技能估计**——所有技能论文都事后全样本打标，没人做滚动真 OOS 排名（StockTwits 数据集发现月频技能持续却从不前向操作化）。
2. **KOL→KOL 引领-滞后/起源网络**（最薄一条线）——现有图都建在股票间；没人用 cashtag 共现+时间戳建持续多年的"谁先发谁跟风"网络。
3. **身份元数据当预测特征而非结果**——follower/verified 全被当被解释的结果（Kakhbod："antiskilled 的 follower 更多"），没人测它们是否条件化/折扣信号质量。
4. **cashtag 共现当有经济含义的注意力链**——只被当垃圾检测或 GNN 特征，从没当跨资产 spillover 的社媒链（对比 JF 用 UI 相邻、Joint-News 用新闻共现、RFS 用静态地理）。
5. **影响力的纵向分解**——拆成"注意力分量(follower/verified)"vs"信息分量(起源位置+收益预测力)"，看哪个随时间持续，没人做过。

### 一个白送的"非平凡基线"（重要）
Kakhbod + VideoConviction 重复验证：**antiskilled 反而 follower 多、跟随它反向亏钱**。→ 这一带**最笨基线(follower 权重/跟群众)是已知会输的**，对我们"必须打赢最笨基线"标准是利好；且可走 **measurement/characterization 叙事原型**（不比 Sharpe），避开大盘收益低 SNR 死法：narrative-locked 指标=分解的可证伪性，非收益率。

---

## 3. 候选方向（仅记录，未排序为待办）

- **旗舰候选**：识别KOL"起源网络"——把影响力分解成"信息(起源、可持续/stable)"vs"注意力(放大、会反转/lucky)"。吃满：结构性 + 我们的 stable-vs-lucky 线 + 白送反常基线 + measurement 叙事。**死因**：大盘股上"谁先发"可能只是对同一外生新闻反应快，非真信息起源（共同外生冲击使"起源"无意义）——须先廉价排除起源结构是否存在。
- **备选 B**：Lipschitz 技能几何（最贴"嵌入几何当结构"+stable-vs-lucky）。死因：技能本身靠低 SNR 收益估，目标噪声大。
- **备选 C**：cashtag 共现跨资产 spillover/扩散速度（新颖性风险最低，现象已被 JF/Joint-News 预验证）。死因：我们 17 标的全大盘+加密，共现是显然板块链(NVDA+AMD、BTC+ETH+MSTR)，实操新颖性低，仍是低 SNR 收益预测。

---

## 关键文献链接
- Finfluencers (Kakhbod et al.): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4428232
- Unleashing Expert Opinion: https://arxiv.org/abs/2504.10078
- StockTwits 2008–2022 dataset: https://journalqd.org/article/view/8780
- Why Don't We Agree? (Cookson-Niessner, JF 2020)
- Echo Chambers (Cookson-Engelberg-Mullins, RFS 2023): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3603107
- The Social Signal (JFE 2024): https://ideas.repec.org/a/eee/jfinec/v158y2024ics0304405x2400093x.html
- Attention Spillover (JF 2023): https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13281
- News Diffusion (RFS 2025 / NBER w30860): https://www.nber.org/papers/w30860
- Understanding LLM Embeddings for Regression: https://arxiv.org/abs/2411.14708
- LLM Embedding for Regression Priors (ICAIF 2025): https://dl.acm.org/doi/10.1145/3768292.3770437
- A Financial Brain Scan of the LLM: https://arxiv.org/pdf/2508.21285
- Cross-Stock Predictability via LLM Semantic Networks: https://arxiv.org/html/2604.19476v1
- Chronologically Consistent LLMs: https://arxiv.org/pdf/2502.21206
