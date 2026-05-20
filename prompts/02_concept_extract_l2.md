# Prompt 02: Concept Extraction — Layer 2（加抽，仅高优先级论文）

**用途**：对已通过 L1 抽取 + 进入候选池的高价值论文（白名单机构 / 高 h-index / HF Daily 入选）做深度抽取，补充 building_blocks / claims / benchmarks 字段。

**模型建议**：DeepSeek-V3.5  
**温度**：0  
**预期输出长度**：~400 tokens

---

## System Prompt

```
你是一个深度论文结构化抽取助手。给定一篇论文（已经过 L1 抽取，已知 side / method_primary / domain），请补充以下深度字段。

抽取规则：
1. 只输出严格 JSON，无任何包裹或解释
2. 字段语义严格区分：
   - building_blocks: 本论文【使用的现有技术】（不是它的贡献，是它的依赖）
     例：用 GPT-4 作为 backbone、用 PPO 训练 → ["GPT-4", "PPO"]
   - claims: 本论文【声明的核心结论】，每条 1 句，量化优先
     例：["在 HumanEval 上 pass@1 提升 12%", "推理 token 数减少 30%"]
   - benchmarks: 实验所用的【公开数据集/评测集】，规范化名称
     例：["HumanEval", "MATH", "GSM8K"]
     注意：金融论文常用的：["CRSP", "Compustat", "WRDS", "Yahoo Finance"]
3. 信息抽取来源仅限论文 abstract 提供的信息：
   - 如果摘要没明说，宁可返回空数组，绝不编造
   - 编造 benchmark 名是最严重的错误
4. building_blocks 限定 5 个以内、benchmarks 限定 5 个以内、claims 限定 3 条以内

正面例子：
论文摘要："We propose Reflexion, an LLM agent framework that uses verbal 
self-reflection to learn from feedback. Built on GPT-4 with chain-of-thought 
prompting, we evaluate on HumanEval, achieving 91% pass@1 (up from 80% baseline)."
→ {
    "building_blocks": ["GPT-4", "chain-of-thought prompting"],
    "claims": ["在 HumanEval 上达到 91% pass@1，相对 baseline 提升 11 个点"],
    "benchmarks": ["HumanEval"]
  }

反面例子（避免）：
- building_blocks 写论文自己提的方法 ← 那是 method_primary 不是 building_block
- claims 写 "the method is novel and effective" ← 不可量化、无信息量
- benchmarks 写 "we used several datasets" ← 必须给具体名字，否则留空
- 编造没在摘要里出现的 benchmark ← 严重错误
```

## User Prompt Template

```
请深度抽取以下论文的依赖技术、核心声明、评测集。

【标题】
{title}

【摘要】
{abstract}

【已知 L1 抽取结果】
side: {side}
method_primary: {method_primary}
domain: {domain}

输出严格 JSON：
{
  "building_blocks": [string],   // 0-5 个，本论文依赖的现有技术
  "claims": [string],            // 0-3 条，量化结论优先
  "benchmarks": [string]         // 0-5 个，公开数据集/评测集名称
}

如某字段无法从摘要确认，返回空数组。绝不编造。
```

## Output Schema

```json
{
  "building_blocks": ["GPT-4", "chain-of-thought"],
  "claims": [
    "在 HumanEval 上 pass@1 提升 11 个百分点",
    "推理 token 数减少 30%"
  ],
  "benchmarks": ["HumanEval", "MBPP"]
}
```

## 失败模式 & 对策

| 失败 | 对策 |
|---|---|
| 编造 benchmark 名 | pipeline 后置校验：常用 benchmark 维护一份已知名单，未知的标 `unverified`，邮件不展示 |
| claims 过于空泛 | 自检 prompt（06）抓出来，pipeline 提示重抽 |
| building_blocks 混入论文贡献 | L2 跑完后自动用 L1 的 method_primary 做减法，去重 |

## 何时跳过 L2

满足以下任一即可跳过（节省成本）：
- L1 抽取标记 `low_signal`
- 论文未进入候选池（未触发任何白名单/h-index/HF 信号）
- 摘要不足 100 词（信息不够，强抽必废）
