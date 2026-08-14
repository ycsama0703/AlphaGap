# Brief — MECH-AI-1 评分器的语义授权：benchmark 报告的能力里，有多少是 scorer 干的？

> Type: `counter_narrative / evaluation-attribution` · anchored to *AI4AI at Test-Time* (2608.12307, M12「严格解析消除与核心推理无关的失败」) · 由 2026-08-14 日报 gap #1 (composite 8.1 · nov 7 · ai 8 · pos 9 · feas 9 · pub 8) 演化而来
> **status: PHASE-0 DONE · 诊断对象已确认存在 · 原假设方向被证伪、主张改写 · 致命风险=生成式模型的效应可能和抽取式一样接近 0**
> ⚠️ **本文件取代日报邮件自动附带的 `2026-08-14-MECH-AI-1.md`**。那一版写于 lit-gate 和 Phase-0 之前，其核心假设（parser 虚增能力）方向已被实测推翻。
> 📉 承重前提不是「parser 会改答案」（已证实会），而是**「生成式 LLM 触发评分器语义授权的频率显著高于抽取式模型」**——这一步若塌，效应量就停在抽取式那个 −1.8pp，撑不起论文。

---

## 1. The Core Insight

所有 LLM benchmark 的报告成绩都是 `模型输出 → 后处理 → 判定` 三段式的**端到端**产物，但榜单只署模型的名。

中间那段后处理拥有多少**语义权限**，从来没被当成变量。它可以只做语法归一化（空白、大小写、标点），也可以插入负号、换算量纲、转百分比、四舍五入——后面这些**改变了答案的指称**，不是格式清理。

文献目前卡在一个自相矛盾的位置：

| 论文 | 结论 |
|---|---|
| **Let Me Speak Freely?** (2408.02442) | 格式约束**显著损害**推理。LLaMA-3-8B / Last Letter 差 **38.15%** |
| **JSONSchemaBench** (2501.10868) | 约束解码**consistently improves** 下游任务 **up to 4%**，**含 GSM8K** |

同一个 benchmark，相反符号，无人调和。

而三篇相关工作（含 2510.14773 的 Answer Regeneration）**都用 LLM 提取答案，都默认它语义中立，都没验证过**。

**本 gap 的操作化**：把后处理按权限分成 P0（原始串）/ P1（纯语法）/ P2（语义字段归一化）/ P3（数值强制），
对**冻结的**模型输出做 replay，测量报告成绩里有多少依赖语义授权。

**关键运气**：这个阶梯不用我们设计——**TAT-QA 的官方评分器里已经实现好了**（见 §4）。

---

## 2. Conceptual Mapping (AI ↔ Fin)

**AI 侧结构**：`surface syntax → typed semantic fields → task value` 三层。约束解码 / 结构化输出的
文献默认第一层和第二层可分离（M12 的核心假设：「严格解析消除与核心推理无关的失败」）。

**Fin 侧结构**：金融答案天然是 typed object——`value / sign / scale / unit / period / accounting concept`。
`-3.14%`、`(134) thousand`、`$77.673B` 这些表示里，**符号在词里、量纲在表头里**，不在数字里。
所以金融是这条边界上**密度最高、且可自动核验**的测量基质。

**诚实的 mismatch（重要，别自欺）**：金融在这里是**测量基质，不是承重性质**。
按 `PUBLISHABLE_SHAPES.md`，如果讲不出「哪个金融性质导致了机制失败」，这就滑向
`none-generic` 那个最弱子类（27 篇 mechanism_transfer 里的 7 篇）。
**缓解**：本 gap 的定位是 **Shape D（LLM-behavior 评估审计）**，不是 Shape C（机制迁移）。
Shape D 的护城河是「first-to-measure」，不要求金融性质承重。但必须补一个非金融 benchmark
（GSM8K，因为它正是 §1 那个矛盾的发生地）来证明结论不是金融特产。

---

## 3. Data Requirements (shape, not acquisition)

**主战场：TAT-QA**（已下载，MD5 对官网校验一致，CC BY 4.0）

| 项 | 值 |
|---|---|
| 规模 | 16,552 题 / 2,757 个混合上下文（表 + ≥2 段文字） |
| dev | 1,668 题 |
| `answer_type` | span 5722 / arithmetic 5543 / multi-span 1645 / count 305（train） |
| `scale` | **结构化字段**：`""` 6457 / thousand 2481 / million 2153 / percent 2104 / billion 20 |
| `derivation` | 可执行推导串（`"(924+967) / 2"`）→ 值和符号可确定性推出 |
| 官方预测格式 | `{uid: [answer, scale]}` —— **值和量纲天然分成两个字段** |
| 现成预测 | `sample_prediction.json`（TagOp 基线，dev） |

**为什么 TAT-QA 是唯一合适的**：它的官方评分器要求模型同时提交 `answer` 和 `scale`，
于是「怎么把两者合并成一个判定」必须由 scorer 明确决定——**权限问题被逼到台面上**，且代码公开可读。

**泛化验证**：FinQA（8,281 题，带标注推理程序）、GSM8K（非金融对照，矛盾发生地）。

**不需要 findata**。那条线（`preflight_findata.py`）暂时搁置。

---

## 4. Benchmark Landscape

### 4.1 TAT-QA 官方评分器的语义授权（读过源码逐条确认）

`tatqa_utils.py`：

| 级别 | 函数 | 行为 |
|---|---|---|
| P1 | `lower` / `white_space_fix` / `remove_articles` / `remove_punc` | 标准 SQuAD/DROP 归一化 |
| P2 | `word_scale_handle` | 读单位词 → `1 million` = 1,000,000 |
| P2 | `scale_to_num` | scale 串 → 乘数（含 `percent → 0.01`） |
| P3 | `negative_num_handle` | **会计括号 `(134)` → `-134`，插入负号** |
| P3 | `percent_num_handle` | `12%` → ×0.01 |
| P3 | `to_number` | `round(num * scale_val * negative_flag * percent_flag, 4)` |

`tatqa_metric.py` 的 `get_answer_str` 另有两条：
```python
ans_str = '%.4f' % (round(ans_num, 2) * scale_to_num(scale))
```
① 两位四舍五入；② **把 (值, scale) 相乘成单一规范数**。

外加 `add_percent_pred` 多塞候选 + `metric_max_over_ground_truths` 取最大 = 多次机会取最优。

**一行死代码**：`_align_bags` 里 `_match_numbers_if_present` 定义了但**从不调用**——
DROP 原版要求数字匹配才给 F1，TAT-QA 主动关掉了。（仅影响 span/multi-span。）

### 4.2 榜单

27 个条目，**EM 50.1（TagOp, 2021 抽取式）→ 81.4（TAT-LLM-70B, 2024 生成式）**，human 84.1。
**未到天花板**（躲开 `FAILURE_PREMORTEM` #16）。相邻名次差距小到 1.2 EM——3pp 的评分器效应足以重排。

**没有任何一个条目报告过纯语法评分下的成绩。**

### 4.3 已被占的方向（不要重复）

- **假阴性方向已满**：2510.14773（提取规则改分数并重排名次）、2408.02442（0.148% 解析错 vs 38.15% 差距）、
  公开记录的 53% 假阴性 / 52pp 偏移、2603.10044 的 48pp parse bug。
- **冻结生成 + 多 parser replay**：2510.14773 已做（同批输出跑 5 套规则）。
- 剩下真正属于本 gap 的：**权限的分级**、**SCA 指标**、**"LLM parser 中立性"审计**、**跨模型世代的授权承重变化**。

---

## 5. Where to Start (Reading + Replication Order)

1. **读源码**（30 分钟，比读论文有用）：`tatqa_utils.py` → `tatqa_metric.py` → `tatqa_eval.py`
2. 2408.02442 §「Perfect Text Parser」——他们用 LLM 当 parser 并假设中立，这是要审计的对象
3. 2501.10868 finding (3)——「+4% 含 GSM8K」，矛盾的另一侧
4. 2510.14773 附录 A.2——5 套提取正则的原始实现，可直接当 P1 参照
5. 复现官方分数：`tatqa_eval.py --gold_path=dev --pred_path=sample_prediction.json` → 应得 **45.92 / 58.88 / 90.95**

---

## 6. The True Contribution

**不是**「我们提出了一个更好的评分器」。**是**：

> 报告的 benchmark 成绩是 `模型 × 后处理` 的联合产物，而后处理的语义授权从未被当作变量报告。
> 我们给出一个权限受控的归因协议，在冻结生成上量化这一项，并证明它随模型世代（抽取式 → 生成式）
> 变得越来越承重——恰恰是榜单跨越的那个转变。

三个可交付资产：
1. **权限阶梯协议**（P0–P3 + SCA 指标），可移植到任何有后处理的 benchmark
2. **TAT-QA 评分器审计**：五种语义强制的逐项归因
3. **矛盾的调和**：解释 2408.02442 与 2501.10868 为何得到相反符号

---

## 7. Conceptual Risks

**R1（致命）· 生成式效应可能也接近 0。** 抽取式实测 SCA = **−1.80pp**，各单项权限 Δ 接近 0，
因为 TagOp 触发率极低（百分号 42 / 单位词 33 / 会计括号 17，共 1668 条）。
若生成式触发率没有显著上升，整条线的效应量就撑不起论文。**Phase-1 第一件事就测这个。**

**R2 · 金融性质不承重** → `none-generic` 风险。缓解见 §2：定位为 Shape D，且必须补 GSM8K 对照。

**R3 · 方向已被推翻一次。** 原假设是「parser 虚增能力」，实测是**扣分**（见 §10）。
写作必须诚实地以「授权是承重的、方向依模型而变」立论，不能硬拗成虚增叙事。

**R4 · 解析器设计本身是自由度。** 我们定义的 P1「纯语法」有多种合理实现，
结论不能依赖某一种。**对策**：至少两版 P1（吃会计括号 / 保留括号），报告区间而非点值。

**R5 · 饱和风险。** 若 DeepSeek V4 在 dev 上直接打到 85+（超 human 84.1），benchmark 已饱和，
效应被压扁。届时改用 FinQA 或 TAT-QA 的困难子集。

---

## 8. Success Story (Paper Headline)

> **Who Earned That Score? Auditing the Semantic Authority of Benchmark Scorers**
>
> TAT-QA 的官方评分器在比较前施加至少五种语义强制：会计括号插符号、单位词缩放、百分比换算、
> 两位四舍五入、多候选取最优。其 headline EM 还通过一次乘法把「算对数」与「判对量纲」耦合成单一判定。
> 27 个榜单条目跨越了从抽取式到生成式的模型世代转变，**没有一个报告过纯语法评分下的成绩**。
> 我们在冻结生成上做权限受控 replay，量化这一项：对 2021 年的抽取式基线它值 −1.8pp，
> 对现代生成式 LLM 值 X pp；并据此解释此前关于「格式约束帮还是害推理」的相反结论。

---

## 9. Falsifiable Hypothesis（预注册）

**H1（主）**：生成式 LLM 的 SCA（|P1→官方 EM 落差|）**≥ 5pp**，且**显著大于**抽取式基线的 1.80pp。
- 证伪：生成式落差 < 3pp，或与抽取式无显著差异 → 本线终止。

**H2（机制）**：生成式模型触发 P2/P3 权限的样本比例 **≥ 抽取式的 3 倍**
（抽取式基线：会计括号 17/1668 = 1.0%、单位词 33/1668 = 2.0%、百分号 42/1668 = 2.5%）。
- 证伪：触发率相当 → H1 即便成立也缺机制解释。

**H3（调和）**：`free` 与 `json` 两条件的 EM 差，**其中 ≥40% 可由评分器语义授权解释**
（两条件各跑完整阶梯，比较各自 P1→官方 落差）。
- 证伪：两条件的落差相同 → 评分器不是那个矛盾的调节变量，只能退回单纯的审计叙事。

**H4（泛化）**：同一协议在 GSM8K 上给出方向一致的结论。
- 证伪：只在金融数据上成立 → 降级为领域特定结果。

---

## 10. Pre-validation Signal (Phase 0)

**已完成，两轮，$0。**

### 10.1 自有数据（`evidence_sufficiency/out/results_p1.jsonl`，370 行冻结输出）

- 判定规则跨度：严格相等 **34.1%** → 绝对容差 0.1pp **96.5%**，**62.4pp**
- **但 94% 的跨度是四舍五入**（gold 1 位小数、模型 2 位）→ 属已被占的假阴性方向
- 剥掉之后的真信号：P1 最强版本 90.8% vs P2/P3 实际输出 96.5%，**Δ +5.7pp**
- **净增益 21 例，100% 是符号插入，零损失**：文本写「下降 3.14%」，结构化字段给 `-3.14`
- 有效 N 只有 24 个负增长 task / 15 家公司 → 样本不足，且五个 typed 维度只有 sign 被行使

### 10.2 TAT-QA（官方 scorer + TagOp 冻结预测）

| 条件 | EM | ΔEM |
|---|---|---|
| 官方完整实现 | 45.92 | — |
| −scale 乘算 | **48.80** | **+2.88** |
| −两位四舍五入 | 44.78 | −1.14 |
| −负号 / −百分比 / −单位词 | 45.92 / 45.98 / 45.98 | ~0 |
| **P1 纯语法** | **47.72** | **+1.80** |
| P0 原始串比较 | 47.24 | +1.32 |

**方向与原假设相反**：语义授权在扣分。机制是 scale 乘算把两种能力耦合进单一 EM——
107/1668 (6.4%) 预测 scale 错配，其中 **23 例值本身正确**，全靠这次乘法被判错。

**判据**：诊断对象存在（授权承重、量级 ~3pp、足以重排相邻名次）→ **GO**。
但方向须改写，且效应量依赖模型世代 → 进 Phase 1 验 H1/H2。

---

## 11. Paper-level Implementation Plan（逐步实施）

目标不是只得到一个 `P1→official` 的 EM 差，而是把报告分数拆成三个可独立干预、可冻结 replay 的部分：

```text
题目与上下文
    ↓
[G] Generation：模型如何生成答案（free / constrained JSON）
    ↓ 冻结 raw output
[E] Extraction：如何从输出中取得 answer / scale（literal / regex / schema / LLM）
    ↓ 冻结 scorer input
[S] Scoring：允许哪些等价和语义变换（P0 / P1 / P2 / P3 / official）
    ↓
逐题判定 + 汇总成绩 + 模型排名
```

核心实验对象因此是 `Score(model, benchmark, G, E, S)`，而不是把 generation、parser 和 scorer
混成一个端到端数字。每次只改变一个轴，其余两轴冻结。

### 11.1 Step 0 — 先修识别设计，不立即全量调用模型

当前脚本可用于保存原始输出，但在付费全量运行前必须完成以下修正：

1. `json` 条件使用 API 的真实 `response_format/json_schema`，不能只靠提示词要求 JSON；否则测到的是
   format instruction，不是 constrained decoding。
2. `free` 与 `json` 必须支持同一组答案类型。TAT-QA dev 中 span/multi-span 占比很高；不能让 free parser
   只取最后一个数字，而 JSON parser 支持 string/list。快速 pilot 可先预注册只分析 arithmetic/count，
   完整实验再覆盖所有 answer type。
3. 真正实现 P0 和 P1：P0 不经过 `to_number/get_answer_str`；P1 只处理大小写、空白、冠词和明确预注册的
   标点规则，不做数值解析、scale 相乘、符号插入、百分比换算或四舍五入。
4. gold 的规范表示固定一次；权限阶梯主要施加在 prediction 侧。另保留“官方 scorer 对称处理 gold/prediction”
   作为复现实验，避免把 scorer 政策变化误写成 parser 单向修复。
5. raw substring 触发与 scorer 有效触发分开统计。只有某权限在实际 scorer input 上被调用，且改变规范值或
   最终判定，才算 causal trigger。
6. 输出写入 `model_id / provider / prompt_hash / schema_hash / parser_version / scorer_version / seed / timestamp`；
   `__ERROR__` 不得被断点续跑永久视为完成。

**Step 0 gate**：用手工构造的 sign/scale/percent/rounding/multi-span 单元测试证明每一级只行使声明的权限；
否则不进入付费 pilot。

### 11.2 Step 1 — 单模型 × TAT-QA 小样本 pilot

- 模型：先用 DeepSeek V4 Flash 0731。
- 样本：100–200 题；按 answer type、非空 scale、负号/百分比潜在触发分层抽样，不能只取数据集前 N 题。
- 生成条件：`free` 与真正 constrained `json`。
- 抽取条件：至少 `literal/regex` 与 `schema field`；原始文本永久保存，允许离线重放，不重复调用模型。
- 评分条件：P0、P1、P2、P3、official。

pilot 不看 headline EM，先看四个质量门：

1. 两种生成条件的有效回答覆盖率和 answer-type 覆盖率是否可比；
2. parser failure 是否低于预注册阈值，并逐题可追踪；
3. P2/P3 的**有效触发率**是否高于 TagOp，而非只在 raw text 中出现；
4. 每个权限是否确实产生可解释的逐题状态变化。

**Step 1 gate**：解析覆盖对称、有效触发足够、无明显实现伪影后，才跑完整 1,668 题。

### 11.3 Step 2 — TAT-QA 全量 + 3–5 个跨世代/架构模型

模型面板不按“方便调用”随意挑，而按预注册角色选择：

| 角色 | 最低数量 | 目的 |
|---|---:|---|
| 抽取式历史基线（TagOp 冻结预测） | 1 | 已知低自由度输出、作为世代锚点 |
| 小/中型 dense instruction model | 1 | 检查效应是否只是规模现象 |
| MoE 或不同架构的开放模型 | 1 | 检查架构/训练家族异质性 |
| frontier proprietary model | 1 | 检查现代强模型与饱和风险 |
| 可选的 reasoning model | 0–1 | 检查长自由文本是否增加权限承重 |

最终至少 **3 个生成式模型**，理想为 **4–5 个**，再加 TagOp 历史锚点。所有模型跑相同题集、相同
generation 条件和同一组 frozen replay。模型选择和版本在看到完整结果前锁定。

每个模型至少报告：

- official EM/F1 与 P0–P3 全阶梯；
- free/json 的格式效应及其置信区间；
- 各权限的 raw trigger、effective trigger、decision-changing trigger；
- answer type、gold scale、难度和输出格式分层结果；
- paired bootstrap CI 或配对置换检验，避免只比较点估计。

### 11.4 Step 3 — 逐题 `错→对 / 对→错` 分解

对题目 `i`，记低权限政策下判定为 `C_i^low`，高权限政策下为 `C_i^high`。每一对相邻权限都生成
完整转移矩阵：

| 转移 | 含义 | 必报数量 |
|---|---|---:|
| `0→0` | 两级都错 | N00 |
| `0→1` | 加权限后错→对 | N01 |
| `1→0` | 加权限后对→错 | N10 |
| `1→1` | 两级都对 | N11 |

并验证：

```text
ΔEM(low→high) = (N01 − N10) / N
```

只报净 ΔEM 会把两个方向抵消，不能解释机制。所有 `0→1` 和 `1→0` 样本须保存：raw output、抽取结果、
gold、触发权限、变换前后规范值和最终判定。对 decision-changing 样本做盲审，进一步分为：

1. 合法语义等价恢复（如明确会计语境中的 `(134) = -134`）；
2. scorer 造成的错误接受；
3. scorer 造成的错误拒绝；
4. parser/实现伪影；
5. 无法判定。

主张“能力虚增/扣减”必须基于第 2/3 类；第 1 类只能称为表示等价恢复。

### 11.5 Step 4 — FinQA + GSM8K 泛化

三个 benchmark 承担不同角色，不能只机械复制同一 scorer：

| Benchmark | 角色 | 重点权限 |
|---|---|---|
| TAT-QA | 主战场；typed `(answer, scale)` | sign / scale / percent / rounding / span |
| FinQA | 金融域复制；带可执行推理程序 | 数值答案、单位与程序执行结果的一致性 |
| GSM8K | 非金融对照；格式约束矛盾发生地 | final-answer extraction、数字格式、单位与容差 |

先为每个 benchmark 写一份 permission manifest：列出官方 scorer 已有的规则、对应 P0–P3 的映射，以及哪些
权限不可比较。跨 benchmark 比较共同权限族和状态转移，不强行要求函数实现完全一致。

**泛化 gate**：若效应只在 TAT-QA 的 scale 字段上出现，则降级为 TAT-QA scorer audit；若金融任务一致但
GSM8K 不成立，则降级为领域特定结论；只有跨域出现共同模式，才保留一般 benchmark-evaluation 主张。

### 11.6 Step 5 — 证明“排名或格式结论反转”

论文级结果不能只说“分数移动了 X pp”，至少争取以下一种反转：

1. **模型排名反转**：存在模型对 `(A, B)`，在低权限政策下 `A>B`，在高权限政策下 `B>A`；报告全部 pairwise
   inversion、Kendall/Spearman 排名稳定性和 bootstrap 置信度。
2. **格式结论反转**：`free−json` 的效应在某评分政策下为正、另一政策下为负，且配对区间支持符号变化。
3. **世代趋势反转/增强**：抽取式与生成式模型的权限依赖方向或幅度系统不同，并可由 effective trigger
   与 decision transition 中介解释。

若没有任何稳健反转，但存在可重复的小幅 score sensitivity，论文应诚实降级为测量审计，不声称解释
structured-output 文献矛盾。

### 11.7 Step 6 — 可复用权限审计工具

最终代码产物暂名 `scorer-audit`，最小接口为：

```text
inputs/
  gold.jsonl              # benchmark gold adapter 的统一格式
  generations.jsonl       # 冻结 raw outputs + run manifest
extractors/
  literal.py
  regex.py
  schema.py
  llm.py                  # 可选，缓存输出与调用记录
policies/
  p0_raw.py
  p1_syntax.py
  p2_semantic.py
  p3_numeric.py
  official.py
adapters/
  tatqa.py
  finqa.py
  gsm8k.py
reports/
  item_transitions.jsonl
  trigger_summary.csv
  score_cube.csv
  ranking_stability.csv
  audit_report.html
```

工具必须支持：冻结生成离线 replay、权限逐项/累积消融、逐题 provenance、任意两政策的转移矩阵、分层统计、
配对置信区间和模型排名稳定性。benchmark-specific 逻辑只放 adapter/manifest，核心 audit engine 不绑定 TAT-QA。

### 11.8 实施顺序与停止条件

| 阶段 | 内容 | 预计成本 | 继续条件 |
|---|---|---:|---|
| **Phase 0** ✅ | 自有数据 + TagOp scorer 复现 | $0 / CPU | 诊断对象存在；但解释仍属 provisional |
| **Phase 0.5** ✅ | 修正三段识别、真实 JSON schema、真正 P0/P1、单元测试 | $0 | 每一级权限边界测试通过 |
| **Phase 1A** ✅ | 单模型、TAT-QA 分层 100–200 题 pilot | 低 | parser 对称、有效触发充分、逐题转移可解释 |
| **Phase 1B** | 单模型、TAT-QA 全量 1,668 题 | ~$1–5 | H1/H2 或明确的双向 decision movement |
| **Phase 2** | TAT-QA 扩到 3–5 个生成式模型 + TagOp | ~$10–30 | 跨模型规律或稳健异质性；非单模型怪癖 |
| **Phase 3** | FinQA + GSM8K | ~$5–20 | 至少一个共同权限机制跨 benchmark 复现 |
| **Phase 4** | 排名/格式反转分析 + scorer-audit 工具 | CPU | 至少一种稳健反转，或诚实降级为审计论文 |
| **Phase 5** | 系统 lit gate、人工审计、成文 | — | `FAILURE_PREMORTEM` #7 承重区分点通过 |

**Phase 0.5 平台和 Phase 1A pilot 已于 2026-08-14 完成**：生成/抽取/评分已拆分，真实 JSON schema、
分层抽样、run manifest、可靠续跑、真正 P0/P1、fixed-gold/symmetric replay、逐题 `0→1/1→0` 和官方 scorer
精确复现入口均已落地；指定模型的 200 题付费 pilot 和 exact 归因结果见 §12。下一步先做逐题盲审，
不立即扩到完整 1,668 题。具体复现命令见 `phase0/tatqa_ladder/HANDOFF.md` §2。后续需要 LLM API 的阶段
仍在本地运行；冻结输出之后的非 LLM extractor、scorer replay 和统计分析都应离线完成。

---

## 12. Phase 1A Numeric Pilot Results（2026-08-14）

### 12.1 设置

- TAT-QA dev 分层抽取 200 题：arithmetic 168（有/无 scale 各 84）、count 32（dev 全部 count）。
- 模型固定 `deepseek/deepseek-v4-flash-0731`；OpenRouter provider 固定 `DeepInfra`，禁止 fallback。
- generation 两条件使用相同 `reasoning=high / max_tokens=2000 / temperature=0 / seed`。
- free 200/200 正常；constrained JSON 191/200 正常，9/200 在相同 token budget 下
  `finish_reason=length`、无 final content，作为格式条件失败计错，不事后提高 JSON 独占预算。
- 生成调用记录费用下限约 **$0.0446**；早期 length 重试的 usage 未被旧日志保存，真实账单略高。
- 冻结输出、manifest、逐题 trace 和报告见 `phase0/tatqa_out/tatqa_pilot_numeric_v1/`。

### 12.2 同一份 free generation，仅改变 extractor

| free extractor | 官方 EM | 相对前一级 | 解释 |
|---|---:|---:|---|
| literal surface | 0.0 | — | 官方 scorer 不能直接从完整句子取得 final answer |
| digit/cue regex | 39.5 | +39.5 | 抽数字、scale；不读 number words/sign language |
| typed regex | 52.0 | +12.5 | 额外允许 `one/two/three → 1/2/3` |
| **LLM parser，自由两行标签** | **67.5** | **+15.5** | 语义抽取 asserted answer；199/200 成功 |
| LLM parser + JSON schema | 25.0 | −42.5 vs labeled | 大量 arithmetic 输出字面占位符 `value/number` |

**LLM parser 不是中立搬运器。** `typed regex → labeled LLM` 的逐题转移为：

- `0→1 = 32`，`1→0 = 1`，净 **+15.5pp**；
- 32 个增益中 **26 个是 sign insertion**（如 `decreased by 21.7 → -21.7`）；
- 其余 6 个是从完整句中定位 final value；
- 唯一损失：`1,226,114 fewer rights` 被 parser 变成负数，但 gold 将 difference 标为正数。

这批增益主要不是重新计算，而是 parser 行使 sign/selection 权限；它通常恢复合法语义等价，但也会越过
benchmark 的标注约定产生 `1→0`。这正是权限审计需要逐题报告双向转移、不能只报净 EM 的原因。

### 12.3 free vs constrained JSON

| 评测接口 | 官方 EM |
|---|---:|
| free + digit regex | 39.5 |
| free + typed regex | 52.0 |
| **free + labeled LLM parser** | **67.5** |
| **constrained JSON generation** | **76.5** |

最公平的当前比较 `JSON − free+labeled-LLM` 为 **+9.0pp**，paired bootstrap 95% CI
**[+3.0, +15.0]pp**，McNemar exact `p=0.0051`。若只用 digit regex，会错误地报告 +37pp；其中 28pp
来自 extractor 选择，而不是 generation 推理差异。

同一 LLM parser 的输出协议本身也承重：schema 25.0 vs labeled 67.5，差 **42.5pp**。因此文献中的
“perfect LLM parser”必须连 parser model、prompt、decoding/output contract 和预算一起报告，不能只写
“用 LLM 抽取答案”。

### 12.4 Exact 权限阶梯与预注册判据

已将 P1–Official 统一到 `exact_tatqa_single_path`：同一 matcher 和逐题判定路径只切换权限开关；
`exact_official` 在完整 TAT-QA dev 1,668 题上与未修改官方 scorer 的逐题 EM/F1 **零 mismatch**，并严格复现
`EM 45.92 / F1 58.88`。下表不再混用独立 audit engine 和官方 scorer：

| 条件 | P1 | 官方 | P1→官方 |
|---|---:|---:|---:|
| free + digit regex | 7.0 | 39.5 | +32.5pp |
| free + typed regex | 19.5 | 52.0 | +32.5pp |
| free + labeled LLM parser | 61.5 | 67.5 | +6.0pp |
| constrained JSON | 65.5 | 76.5 | **+11.0pp** |

- **H1 通过但具有 extractor 异质性**：JSON 的 11pp 和最强 free parser 的 6pp 均通过 ≥5pp；digit/typed
  extractor 的 32.5pp 说明 SCA 不能脱离 extractor 单独报告。
- **H2 raw-trigger 通过**：free 中会计括号 7/200=3.5%、单位词 78/200=39%、百分号 36/200=18%，
  分别约为 TagOp 基线的 3.5× / 19.5× / 7.2×。但 effective/decision-changing trigger 仍需作为主结果。
- **H3 exact 通过**：JSON SCA 11pp vs free+labeled SCA 6pp，difference-in-SCA=5pp，约占最终 9pp
  格式差的 **55.6%**，仍超过预注册的 40% gate。free+labeled 从 P1 到官方直接发生 12 个 `0→1`、
  0 个 `1→0`；相邻阶梯中 rounding 一步另有 3 个 `0→1`、1 个 `1→0`，须进入盲审。

旧的独立-engine provisional 估计为 83.3%，现仅保存在报告的 `legacy_attributions` 中用于追溯，不能再作为
主结果。

### 12.5 当前判决

**继续 GO，但不直接把 200 题结果外推到完整榜单。** 这轮已经验证：

1. 生成式输出显著提高权限触发密度；
2. extractor 选择可移动 28–42.5pp，远大于常见模型差；
3. LLM parser 的净增益主要可追溯到明确的 sign 权限；
4. scorer 权限在 JSON / 最强 free 条件下分别承重 11pp / 6pp，exact difference-in-SCA 为 5pp。

盲审包和双模型 blinded LLM audit 已完成，详见 §12.6。下一步按顺序：① 裁决仅剩的 3 条核心分歧
（2 个 UID）并抽样做人类校验；② 扩到 TAT-QA 全部 numeric 题验证效应；③ 再加入第二、第三个生成模型。
exact 归因已经跨过 40% gate；若后续人类校验推翻双 judge 对 extraction faithfulness 的高一致结论，则退回
“LLM parser 非中立 + evaluation-policy sensitivity”审计叙事。

### 12.6 双模型 Blinded LLM Audit

使用与生成模型不同家族的 `openai/gpt-5.6-terra-pro` 和 `google/gemini-3.7-flash` 独立审核公开盲包；
两者均固定原生 provider、medium reasoning、strict JSON schema，并在全部输出冻结后才解盲。每个 judge
完成 264/264 条，零截断；总记录费用 **$2.6678**。

关键一致性：

| 字段 | Agreement | Cohen's κ |
|---|---:|---:|
| Pass 1 asserted answer | 89.5% | 0.894 |
| Pass 1 asserted sign | 86.8% | 0.632 |
| Pass 2 extraction faithful | 99.1% | 0.000* |
| Pass 2 benchmark-correct candidate | 99.1% | 0.961 |
| Pass 2 semantic transformation justified | 96.5% | 0.810 |
| Pass 2 error source | 96.5% | 0.860 |
| Mechanism decision-change justified | 94.4% | -0.029* |

`*` 为 prevalence paradox：extraction 几乎全为 exact、decision-change 几乎全为 no，κ 在边际分布退化时失真，
必须与原始一致率及标签分布并报。

解盲后，34/34 个 P1↔Official 直接变判案例中，两 judge 一致认为 extraction 为 exact，且 P1 与 Official
候选都在语义上正确。36 个相邻 mechanism edge 中：34 个一致判定不应因表示转换而改变 correctness，2 个
分歧来自同一 `-16.458 million` 案例的 scale/rounding 两条边。另一个核心分歧是 “1,226,114 fewer rights”
应抽取正 magnitude 还是 signed negative。若把 candidate surface fidelity 等全部实质字段计入，共有 97 条记录
至少一项不一致；预设需裁决字段的队列为 60 条（多为 sign、soft error-source/semantic-justification），而真正
影响核心结论的队列只有 **3 条记录 / 2 个 UID**。

方法边界：这是 blinded **LLM-as-a-judge** audit，不是人工盲审。当前结果强力支持“权限在识别语义等价表示，
同时使报告分数依赖 scorer policy”，但正式成文仍应对核心 2 UID 和一小部分一致样本做人类 spot-check。

### 12.7 三生成模型扩展：异质格式效应与 Policy-dependent Inference

在同一冻结 200 题 numeric selection、同一 free/JSON prompt、同一 labeled LLM extractor 和同一 exact
scorer 上，加入 `anthropic/claude-sonnet-5:batch` 与 `minimax/minimax-m3:batch`。加上原 DeepSeek pilot，
当前已有三个可完整分析的生成模型；`openai/gpt-5.6-luna-pro` 已在 luyao4 运行，但因 SSH 跳板
`kv.run:10020` 离线尚未回收，不能把它计入下表。

| Generator | Free P1 | Free Official | JSON P1 | JSON Official | Free SCA | JSON SCA |
|---|---:|---:|---:|---:|---:|---:|
| DeepSeek V4 Flash | 61.5 | 67.5 | 65.5 | 76.5 | +6.0 | +11.0 |
| Claude Sonnet 5 | 69.5 | 74.5 | 78.0 | 80.5 | +5.0 | +2.5 |
| MiniMax M3 | 69.0 | 75.0 | 44.0 | 59.5 | +6.0 | +15.5 |

格式效应（JSON − free）不是一个可跨模型外推的常数：

| Generator | P1 gap (95% bootstrap CI; McNemar p) | Official gap (95% CI; p) | Policy effect |
|---|---:|---:|---|
| DeepSeek | +4.0pp [−2.5,+10.5]; .280 | +9.0pp [+3,+15]; .0051 | 不显著 → 显著；scorer 放大 +5pp |
| Claude | +8.5pp [+3,+14]; .0060 | +6.0pp [+0.5,+11.5]; .0576 | 显著 → 边界不显著；scorer 缩小 −2.5pp |
| MiniMax | −25.0pp [−33,−17]; 8.6e−9 | −15.5pp [−23,−8]; 8.8e−5 | 均显著为负；scorer 救回 +9.5pp |

因此目前最强结论不是“JSON 总是提高/损害推理”，而是：**格式约束效应的符号依赖生成模型，效应量和统计
结论又依赖评分政策。** MiniMax 与 DeepSeek/Claude 的效应符号相反；DeepSeek 和 Claude 还分别出现
`non-significant→significant` 与 `significant→non-significant` 的 policy-dependent inference flip。

存在一个严格的 descriptive model-rank reversal：free/P1 为 Claude 69.5 > MiniMax 69.0，free/Official
为 MiniMax 75.0 > Claude 74.5。但两边只差 0.5pp，配对 McNemar 均 `p=1`；三个 model×format pipeline
的其他数值反转也均不显著，**不得写成稳定模型排名被评分器颠覆**。当前 gate 应记为：

- 3 个跨厂商 generator：通过；
- scorer-policy significance flip：通过；
- format-effect cross-model heterogeneity：强通过；
- 稳健/显著的 model-rank reversal：未通过；
- 第四模型 Luna：生成已部署，待跳板恢复后回收并统一抽取/评分。

Claude/MiniMax Batch generation 均为 400/400 success、零截断，exact scorer 四组共 800/800 与未修改官方
实现逐题一致。按冻结单价与实际 tokens 重算，两模型生成费用约 `$0.59143`；统一 free extractor 费用
`$0.01821`。MiniMax extractor 有 1/200 条固定 2000-token 截断，按 extraction failure 计错，未暗中重跑。
完整三模型机器可读结果：`phase0/tatqa_out/tatqa_multimodel_3model_v1.json`。

---

## 附：文件地图

```
briefs/2026-08-14-MECH-AI-1-scorer-permissions.md   # 本文件（研究说明）
phase0/tatqa_ladder/HANDOFF.md                      # 操作交接（怎么跑）
phase0/tatqa_run.py                                 # Phase-1 推理，双条件，存原文
phase0/tatqa_batch_run.py                           # OpenRouter Batch 提交/轮询/恢复
phase0/tatqa_multimodel_report.py                   # 排名、格式效应与 policy flip 汇总
phase0/scorer_audit/                                # 三段式权限审计平台（Phase 0.5）
tests/test_scorer_audit.py                          # 权限边界、schema、转移和抽样测试
phase0/tatqa_ladder/tatqa_ladder.py                 # 权限阶梯消融
phase0/tatqa_ladder/RESULT_tagop_dev.txt            # 抽取式基线完整结果
phase0/tatqa_ladder/phase0_sca{,2}.py               # Phase-0 自有数据分析
knowledge/LIT_GATE_LOG.md §4 方向C / §C-6           # 撞车情况 + 可复用基线 + 已确立事实
```
