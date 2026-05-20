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
   - method_primary: 本论文【提出或主要贡献】的方法或技术，1-2 个
   - domain: 本论文【应用于哪个问题/任务/场景】，1-3 个
   - tags: 自由标签，用于检索（3-5 个），允许更宽泛
3. 概念名要规范化：
   - 用学界通用术语，不要论文自创花名（"OurMethod" → 转写成它的技术本质）
   - 用英文小写短语，连字符或空格连接（如 "in-context learning"、"chain-of-thought"）
   - 不写大段描述，每个 concept 5 词以内
4. side 判断：
   - "ai": cs.LG / cs.CL / cs.AI / cs.MA / 普通 ML & DL & RL & Agent 论文
   - "fin": q-fin.* / SSRN / 论文核心讨论金融市场、投资、资产定价、量化交易
   - "both": 显式跨界论文（AI 方法 + 金融实证），如 ML-based asset pricing、LLM for finance
5. 如果摘要信息不足以判断某字段，返回空数组，不要硬编

正面例子（好的抽取）：
- 论文是关于用 LLM agent 做代码生成 →
  method_primary: ["LLM agent", "tree search"]
  domain: ["code generation"]
  tags: ["agent", "tool use", "planning", "LLM"]
- 论文是关于 Transformer 在因子预测的应用 →
  method_primary: ["transformer for factor prediction"]
  domain: ["factor investing", "return forecasting"]
  tags: ["deep learning", "asset pricing", "time series"]

反面例子（避免）：
- method_primary 写 "we propose a novel method" ← 没有信息量
- domain 写 "machine learning" ← 这是 method 不是 domain
- tags 写 "important", "interesting" ← 不可检索
- side 输出 "AI" / "Finance" ← 必须小写 "ai" / "fin" / "both"
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
  "tags": [string]               // 3-5 个
}
```

## Output Schema (JSON)

```json
{
  "side": "ai",
  "method_primary": ["verifier-based self-correction"],
  "domain": ["code generation", "mathematical reasoning"],
  "tags": ["LLM agent", "self-correction", "reasoning", "verifier"]
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
