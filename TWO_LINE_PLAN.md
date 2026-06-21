# 改造方案 — 双线并行:应用线(AI×金融) + 理论线(底层机制×金融结构)

> 目标:在不放弃现有"AI 应用×金融"线的前提下,**新增一条平行的"底层理论机制×金融结构"线**。
> 两条线各有自己的"识别眼睛"和每日名额,互不挤占,汇入同一个后端(挖机制→出 gap→brief)。
> **这是重新瞄准,不是推倒重建**:抓取→筛选→挖机制→出 gap→brief 的骨架不变。

---

## 0. 一句话设计

```
                ┌─ 应用线(现有,不动):AI×金融应用 battlefield ──┐
 抓取 ──分流──► │                                                ├──► 共用后端(挖机制/gap/brief)
                └─ 理论线(新增):可移植底层机制 × 金融结构 ──────┘     premortem/verify 两线通用
```

核心轴的改变:
- 应用线 = "AI 应用能帮金融什么"(保留)
- 理论线 = "**一个【近期的】底层机制(数学/统计/CS 理论,含学习/RL 理论)的归纳偏置,正好对上哪个被忽略的金融结构、要打败哪个现有 incumbent**"

---

## 1. 现状诊断(为什么"只加抓取分类"没用)

三道关卡都是按"AI 应用 battlefield"设计的,理论论文被结构性排除:

| 关卡 | 文件 | 现状 | 对理论论文的后果 |
|---|---|---|---|
| ① 抓取分类 | `ingest.py:25` | 仅 `cs.LG/CL/AI/MA` + `q-fin.*` | 理论类根本没抓 |
| ② 候选资格 | `filter.py:67` | 必须命中 HF热门/q-fin/金融大牛/**应用关键词** 之一 | 理论论文一条都不沾 → 不是候选 → 静默丢弃 |
| ③ priority 打分 | `filter.py:78` | 全靠应用信号(HF票/q-fin/应用 battlefield) | 理论论文 battlefield 全不命中 → 卡在 `L2_PRIORITY_THRESHOLD=5.0` 以下 → 不深挖 |
| ④ 深挖+生成器 | `research_gap_stage.py:102` / `agent_opportunity.py` | 写死 "AI-PROTAGONIST"(AI主角、金融场景) | 即使理论论文进来,生成框架也不会按"理论机制×金融结构"出 gap |

> 结论:理论论文现在是被**设计性**排除的。要喂进去,必须给①②③④都装上"理论线"的并行通道。

---

## 2. 文件级改动清单

### 2.1 抓取(`pipeline/ingest.py`)
- `DEFAULT_ARXIV_CATEGORIES` 增加理论类(分组标注,便于后续按线分流):
  ```python
  AI_APPLIED_CATEGORIES = ["cs.LG", "cs.CL", "cs.AI", "cs.MA"]
  FIN_CATEGORIES        = ["q-fin.PM", "q-fin.ST", "q-fin.TR", "q-fin.CP"]
  THEORY_CATEGORIES     = ["stat.ML", "stat.ME", "math.ST", "math.OC", "math.PR", "q-fin.MF"]
  DEFAULT_ARXIV_CATEGORIES = AI_APPLIED_CATEGORIES + FIN_CATEGORIES + THEORY_CATEGORIES
  ```
- 说明:`stat.ML`/`math.ST` 是高产类。靠 `lookback_days=1` + 下面的 priority 名额控制体量,不会爆。

### 2.2 候选资格 + priority(`pipeline/filter.py`)— **核心改动**
给 `CandidateSignals` 增加理论维度,让理论论文能"过①过③":

- 新字段:
  ```python
  is_theory: bool = False              # 命中理论 arxiv 类
  theory_mechanisms: list[str] = []    # 命中"可移植机制"词
  ```
- `is_candidate`:加 `or self.is_theory`(理论类自动算候选,过关卡②)。
- `_THEORY_CATEGORIES = {"stat.ML","stat.ME","math.ST","math.OC","math.PR","q-fin.MF"}`;`compute_signals` 里命中即 `is_theory=True`。
- 新增"可移植机制"词典 `_THEORY_MECHANISM_PATTERNS`(给 priority 加分,过关卡③),**只收"本身就是一个可拎出来用的机制"的词**,初版建议:
  ```
  估计/收缩:   shrinkage, james-stein, ledoit-wolf, ridge/elastic-net, empirical bayes
  鲁棒/重尾:   robust statistics, huber, M-estimator, heavy-tail, median-of-means, trimmed
  高维/RMT:    high-dimensional, random matrix, spectral, sparse precision, graphical lasso
  分布鲁棒:    distributionally robust, DRO, wasserstein, optimal transport
  不确定性:    conformal, distribution-free, coverage guarantee, calibration
  泛化/界:     PAC-Bayes, generalization bound, minimax, concentration, Rademacher
  在线/非平稳: online learning, regret, change-point, non-stationary, sequential
  RL 理论:     offline RL, pessimism, conservative, sample complexity, bellman error bound
  随机过程:    rough volatility, fractional, neural SDE, stochastic control, HJB, mean-field
  因果:        causal inference, identification, instrumental variable, confounding, do-calculus
  ```
- priority 加分(与应用 battlefield 同量级,不喧宾夺主):
  ```python
  score += 1.5 * min(len(self.theory_mechanisms), 3)   # 每个可移植机制 +1.5,cap 3
  score += 1.0 if self.is_theory else 0.0              # 理论类基础分
  ```
- `_OFFFIELD_PATTERN` 惩罚保持不变(理论论文本就不触发)。

### 2.3 按线分流 + 各自名额(`ingest.py` + 后端 context)
防止"两条线在同一打分池里互相挤占",给理论线**独立名额**:
- L2 深抽:现 `max_l2=30` 单池。改为按线各取:`max_l2_applied` + `max_l2_theory`(初版建议 22 + 8),各自按本线 priority 排序取 top。
- 深挖出 gap:`research_gap_papers=4`(现 env)拆成两个名额:
  - `RESEARCH_GAP_PAPERS_AI=3`(应用线)
  - `RESEARCH_GAP_PAPERS_THEORY=2`(理论线)
  - (体量小、precision-first;数字可调)
- context 里 `ai_recent_papers` 旁边新增 `theory_recent_papers`(由 `side`/`is_theory` 分流),供后端两个生成器分别取用。

### 2.4 后端生成器(`research_gap_stage.py` + `agent_opportunity.py`)— **第二大改动**
现有 `generate_agent_opportunity_map` 是 "AI 主角"。两种实现方式,推荐 B:
- **A(分叉)**:复制一个 `generate_theory_opportunity_map`,framing 换成"理论机制×金融结构"。简单但重复代码。
- **B(参数化,推荐)**:把生成器加一个 `track="ai"|"theory"` 参数,共用打分骨架(novelty/story/composite),只切换:
  - 主角设定(AI 机制 vs 底层数学/统计机制)
  - 必答约束(见 §2.5 的"指名 incumbent + 理论自筛")
  - few-shot 例子
- `run_research_gap_stage` 跑两遍:对 `ai_recent_papers` 跑 track="ai",对 `theory_recent_papers` 跑 track="theory",结果合并后按 composite 排序、共享 brief 名额。
- `mine_paper`(L3 全文挖机制)是通用的(抽 `transferable_sub_mechanisms`),理论论文可直接复用,无需改。

### 2.5 Prompt 改动(两线共用 + 理论专属)
- `prompts/01_concept_extract_l1.md`(side 规则,小改):
  `side` 规则加 `stat.* / math.*` → 归为 `"ai"`(理论内核仍属 AI/方法侧),或新增 `"theory"` 值(更干净,但要同步 db/分流逻辑)。建议先用 `"ai"` 不动 schema,靠 `is_theory` 分流。
- `prompts/05_*`、`07_*`、`09_*`(生成/打分/brief,两线共用,加两句硬约束):
  1. **指名 incumbent**:每个 gap 必须写明"要打败的现有方法是谁"(HAR-RV?样本协方差?卡尔曼?经验分位数?)及其归纳偏置在哪个金融结构上不如本机制。
  2. **理论自筛(前置 premortem)**:生成时先自检——任务是否低信噪比 / 机制是否高容量无归纳偏置(踩 #8/#10/#15),若是则标注预判死法,而非等跑完才发现。
  3. **盯前沿不盯经典**:理论线明确要求"近期、尚未被计量/quant 搬进金融"的进展;经典结果(如 Ledoit-Wolf 2004)视为 incumbent,不作为创新。

---

## 3. 不变的部分(继续复用,无需改)
- premortem 全套(#8/#10/#11/#13/#14/#15/#16)、verify-the-kill / verify-the-GO 纪律 → **两线通用**,换源后更贴合。
- findata 数据可测性闸 + `FINDATA_VERIFICATION.md` 流程 → 任何 gap 仍须能在 findata 上便宜实测。
- kill-memory(findings bank dedup)→ 两线各自的 killed 都喂回生成器。
- 邮件/cron/输出骨架不动。

---

## 4. 两个必须带着做的风险(写进 prompt 与本人判断)
1. **换源不改"低信噪比死亡定律"**:金融信号弱是金融的属性,不是料的属性。理论线候选质量更高、故事更好,但**仍会杀掉大多数**。换源是"更好的猎场",不是"更容易的猎物"。
2. **数学/统计金融是成熟领域**:经典统计早被搬过去了。边只在"**近期、未被搬进金融的底层进展**"。所以理论线 priority 词典要持续更新到前沿,且生成约束强制"盯前沿不盯经典"(见 §2.5.3)。
   - 附带:防 **theory-washing**(贴一个不 bind 的漂亮 bound)。规矩:机制必须在真实数据上真的打败 incumbent,装饰性引用不算。

---

## 5. 体量与成本(precision-first,不爆)
- 抓取:+6 类,但 `lookback=1` + priority 名额控制 → L2/深挖总量基本不变。
- 深挖名额:AI 3 + 理论 2 = 5 篇/天(现为 4)。深挖走 gpt-chat-latest,brief ~$0.2/篇,日增成本可忽略。
- 体量旋钮全部 env 化(`RESEARCH_GAP_PAPERS_AI/THEORY`、`max_l2_*`),随时调。

---

## 6. 落地顺序(每步可单独验证)
1. **§2.1 抓取分类** + **§2.2 filter 理论维度** → 本地跑一次 ingest,确认理论论文进了候选、priority 排上来了(看 top-N 里有没有 stat/math 论文)。
2. **§2.3 分流 + 名额** → 确认 `theory_recent_papers` 非空。
3. **§2.4 生成器 track 参数** + **§2.5 prompt** → 本地跑一次完整 pipeline,看理论线出的 gap 长什么样、是否带 incumbent。
4. 本地满意 → **git commit + push**,luyao4 `git pull`(数据/部署只走 git,不用 ssh 传数据)。
5. 先观察 1–2 天理论线的 gap 质量,再调名额/词典。

---

## 7. 待你拍板的开放项
- **A. 名额比例**:AI 深挖 3 + 理论 2?还是对半 2+2?或理论线先小(1)跑通再加?
- **B. side 字段**:理论论文先并入 `"ai"`(零 schema 改动,靠 is_theory 分流),还是新增 `"theory"` 值(更干净,但要改 db + L1 schema)?我倾向先并入 `"ai"`。
- **C. 生成器**:参数化(B,推荐)还是分叉复制(A)?
- **D. 机制词典**:§2.2 的初版词表你要加/删哪些方向?(比如要不要现在就纳入 rough-vol / neural-SDE 这类偏数学金融的)
