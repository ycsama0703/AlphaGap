# Prompt 03: Trend Summary（每日跑，分 AI/Fin 两侧各跑一次）

**用途**：拿 concept 频率统计表（最近 14 天 vs 前 14 天），让 LLM 输出方向升降的人类可读总结。

**模型建议**：DeepSeek-V3.5  
**温度**：0.2（轻微解释空间）  
**预期输出长度**：~500 tokens

---

## 上游数据准备（pipeline 算好再喂给 LLM）

pipeline 在调用前应已聚合好：

```json
{
  "side": "ai",
  "window_recent": "2026-05-07 to 2026-05-20",
  "window_prior":  "2026-04-23 to 2026-05-06",
  "concepts": [
    {
      "name": "verifier-based self-correction",
      "count_recent": 12,
      "count_prior": 4,
      "growth_pct": 200,
      "citation_velocity_30d": 142,
      "first_seen": "2026-04-15",
      "representative_papers": [
        {"title": "...", "arxiv_id": "2605.xxxxx", "affiliation": "DeepMind"}
      ]
    },
    ...
  ]
}
```

仅传入近 14 天出现 ≥ 3 次的 concept（否则噪声太多）。

## System Prompt

```
你是一个学术趋势分析助手。给定某个领域（AI 或 Fin）的概念出现频率统计，请输出方向升降的简洁总结。

输出原则：
1. 严格 JSON，无任何前后缀
2. 分四类：rising / falling / new_emergence / stable_hot
   - rising: growth_pct ≥ 50% 且 count_recent ≥ 5
     【加强信号】若 citation_velocity_30d ≥ 50，更确信是 rising（社区真在用）
   - falling: growth_pct ≤ -40% 且 count_prior ≥ 5
     【加强信号】若 citation_velocity_30d 也低（≤ 5），降温更可靠
   - new_emergence: first_seen 在 window_recent 内 且 count_recent ≥ 3
   - stable_hot: count_recent ≥ 10 且 |growth_pct| < 30%
3. 关键区分（两个信号叠加才是真信号）：
   - paper count 增长 = "更多人在写"（可能 hype）
   - citation_velocity_30d 高 = "工作真在被引用"（已认真使用）
   - 两者都高 → 真热点；只 paper count 高 → 仍在 hype 阶段；只 citation 高 → 经典 revisit
3. 每类最多 5 条
4. 每条 concept 配一句【为什么值得关注】的简评（≤ 30 字）
   - 简评要点：技术性质（是新方法还是旧方法变种？）、生态信号（来自哪些机构？）
   - 不要复述 count 数字（pipeline 会显示）
5. 如果某分类下没有合格项，返回空数组

正面例子：
{
  "name": "verifier-based self-correction",
  "comment": "Reflexion 思路的工业化版本，DeepMind/OpenAI 同期发力"
}

反面例子（避免）：
{
  "name": "verifier-based self-correction",
  "comment": "近期出现 12 篇，增长 200%"   ← 重复 pipeline 已有数据
}
```

## User Prompt Template

```
分析以下 {side} 领域的概念趋势。

【时间窗口】
近期：{window_recent}（14 天）
对比：{window_prior}（14 天）

【概念统计】（已按 growth_pct 降序）
{concepts_json}   # 上文 JSON 结构，仅 count_recent ≥ 3 的 concept

请输出趋势分类与简评。Schema:
{
  "rising": [{"name": string, "comment": string}],
  "falling": [{"name": string, "comment": string}],
  "new_emergence": [{"name": string, "comment": string}],
  "stable_hot": [{"name": string, "comment": string}]
}
```

## Output Schema

```json
{
  "rising": [
    {
      "name": "verifier-based self-correction",
      "comment": "Reflexion 工业化版本，DeepMind 同期发力"
    },
    {
      "name": "time series foundation model",
      "comment": "Chronos/Moirai 之后新一批 zero-shot 模型涌现"
    }
  ],
  "falling": [
    {
      "name": "long context techniques",
      "comment": "随 GPT-4-128k 类模型普及，单项研究热度退潮"
    }
  ],
  "new_emergence": [
    {
      "name": "mechanistic interpretability for safety",
      "comment": "Anthropic Sparse Autoencoder 工作引发的集中跟进"
    }
  ],
  "stable_hot": [
    {
      "name": "RLHF / DPO",
      "comment": "持续热点，方法已成熟、应用扩张中"
    }
  ]
}
```

## 失败模式 & 对策

| 失败 | 对策 |
|---|---|
| 简评写成数字描述 | 后置校验：comment 中含 "%" / "篇" / "增长" 则触发重写 |
| 分类规则被忽略 | pipeline 在调用前已按规则筛选，LLM 只是命名和点评，不重新分类 |
| 输出超出 5 条 | pipeline 后置截断 top 5 |

## 双侧调用

每日跑两次，side 分别为 "ai" 和 "fin"，结果分两个 section 进邮件。
