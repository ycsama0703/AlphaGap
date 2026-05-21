# Prompt 01: Concept Extraction — Layer 1（必抽，所有候选论文）

**用途**：从论文 title + abstract + 作者机构 中抽出最核心的结构化字段。每篇候选论文都跑。

**模型建议**：DeepSeek-V3.5（便宜、JSON 输出稳）  
**温度**：0  
**预期输出长度**：~200 tokens

---

## System Prompt

```
你是一个学术论文结构化抽取助手。你的任务是从论文标题和摘要中提取核心方法、应用域和标签。

抽取规则：
1. 只输出严格 JSON，不要任何解释文字、markdown 代码块、前后缀
2. 字段语义必须严格区分：
   - method_primary: 本论文【提出或主要贡献】的方法名（1-2 个，可包含品牌名/缩写）
   - domain: 本论文【应用于哪个问题/任务/场景】，1-3 个
   - tags: 自由标签，用于检索（3-5 个），允许更宽泛
   - **mechanism_description: 本论文【机制级别】描述（核心字段，最重要）** —— 详见 3
3. mechanism_description（必填，4 个子字段）：
   这是 method_primary 的【功能本质描述】，**不允许只重复品牌名**。
   - one_liner: 一句话讲清楚【做什么】+【怎么做】，必须在功能层面描述（≤ 60 字）
       ✅ 好："用 future-KL 散度作为 per-token advantage 信号实现密集 credit assignment"
       ✅ 好："多智能体协作 + 错误归因模块定位失败子任务"
       ❌ 烂："使用 FIPO 方法" ← 只是品牌名
       ❌ 烂："改进 RL" ← 不具体
   - what_problem: 解决什么【具体技术问题】（≤ 50 字，必须比 domain 更具体）
       ✅ "长程序列 RL 中 trajectory-level reward 太稀疏导致 credit assignment 失败"
       ❌ "做得更好" / "解决限制"
   - contrast: 与【前作 / 主流做法】的差异，必须命名 prior approach（≤ 60 字）
       ✅ "比 trajectory-level REINFORCE 更密集；不需要 PRM 那样的人工标注"
       ❌ "比之前的方法更好"
   - prerequisites: 应用此机制的【关键前提条件】（≤ 40 字）
       ✅ "模型输出 distributional logits；可采样未来轨迹"
       ❌ "需要数据" / ""
4. 概念名要规范化：
   - method_primary 可保留 paper 自创名（"FIPO"），mechanism_description 必须功能化
   - 用英文小写短语，连字符或空格连接
5. side 判断：
   - "ai": cs.LG / cs.CL / cs.AI / cs.MA / 普通 ML & DL & RL & Agent 论文
   - "fin": q-fin.* / SSRN / 论文核心讨论金融市场、投资、资产定价、量化交易
   - "both": 显式跨界论文（AI 方法 + 金融实证）
6. 如果摘要信息不足以判断某字段，返回空字符串或空数组，不要硬编

正面例子（好的抽取）：
论文 abstract："We propose FIPO, which uses KL divergence between current and future policies as 
a per-token advantage signal, enabling dense credit assignment in long-horizon RL..."
→ {
    "side": "ai",
    "method_primary": ["FIPO"],
    "domain": ["long-horizon RL", "policy optimization"],
    "tags": ["RL", "credit assignment", "policy gradient", "advantage estimation"],
    "mechanism_description": {
      "one_liner": "用未来 KL 散度作为 per-token advantage 信号实现密集 credit assignment",
      "what_problem": "长程 RL 中 trajectory-level reward 太稀疏，token 级 credit attribution 失败",
      "contrast": "比 trajectory-level REINFORCE 更密集；不需要 PRM 的人工 reward 标注",
      "prerequisites": "模型输出 distributional logits；当前与未来策略可采样"
    }
  }

反面例子（避免）：
- mechanism_description.one_liner 写 "我们的方法" / "提出新方案" ← 没有信息量
- mechanism_description.contrast 留空 ← 必须有 prior approach 对比
- mechanism_description.one_liner 写 "FIPO 方法" ← 品牌名不算 mechanism
```

## User Prompt Template

```
请抽取以下论文的核心结构化字段。

【标题】
{title}

【摘要】
{abstract}

【作者机构】
{affiliations}   # 例如 "Google Research; Stanford University"

【arxiv 分类】
{arxiv_categories}   # 例如 "cs.LG, cs.CL" 或 "q-fin.PM"

输出严格 JSON，schema：
{
  "side": "ai" | "fin" | "both",
  "method_primary": [string],   // 1-2 个
  "domain": [string],            // 1-3 个
  "tags": [string],              // 3-5 个
  "mechanism_description": {
    "one_liner": string,         // 功能层面描述，禁止只重复品牌名
    "what_problem": string,
    "contrast": string,
    "prerequisites": string
  }
}
```

## Output Schema (JSON)

```json
{
  "side": "ai",
  "method_primary": ["verifier-based self-correction"],
  "domain": ["code generation", "mathematical reasoning"],
  "tags": ["LLM agent", "self-correction", "reasoning", "verifier"],
  "mechanism_description": {
    "one_liner": "用独立 verifier 模型对生成结果打分后触发反思重写循环",
    "what_problem": "LLM 生成代码 / 推理的 false positive 率高，单 pass 无内置纠错",
    "contrast": "比 self-consistency 投票多了 critic 信号；比外部 PRM 不需训练 reward model",
    "prerequisites": "可获得 verifier 模型且其判断与最终正确性相关"
  }
}
```

## 失败模式 & 对策

| 失败 | 表现 | 对策 |
|---|---|---|
| 不是合法 JSON | 输出带 ```json 包裹或解释 | pipeline 用 robust JSON parser 剥壳；连续 2 次失败标记论文 `extraction_failed` |
| concept 太长 | "a novel method for ..." | pipeline 后置 truncate + 在下次迭代强化 5-词限制 |
| side 误判 | 把 "ML for trading" 标成 "ai" | pipeline 后置规则：q-fin.* arXiv 类别强制 ≥ "both" |
| 抽 0 个 method | LLM 不自信 | 接受，标记为 `low_signal`，但仍入库（tags 还能用） |

## 调用示例（伪代码）

```python
result = deepseek.chat(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(**paper)}
    ],
    temperature=0,
    response_format={"type": "json_object"}
)
extracted = json.loads(result.choices[0].message.content)
```
