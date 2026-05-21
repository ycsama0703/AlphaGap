# Prompt 03: Mechanism-Level Trend Summary

**用途**：从近 90/180 天窗口内的论文 `mechanism_description` 列表中**动态聚类出 mechanism families**，每个 family 给出代表性功能描述、变体论文、解决的问题、与前作对比。

**模型建议**：DeepSeek-V3.5  
**温度**：0.2  
**预期输出长度**：~1500-2500 tokens

---

## 核心理念

**不要 tag 级别的概念（"agent", "RL", "RLVR"）**——这种 trend 等于没说。

要 **mechanism family 级别**——一族解决类似抽象问题、用类似机制的工作。比如：

```
mechanism family: "Dense per-step credit assignment from policy distribution shifts"
  papers: [FIPO 2605.19835, KL-Advantage 2603.x, DenseAdv 2604.y]
  representative_one_liner: "用 future-KL 散度作为 per-token advantage 信号"
  what_problem: "长程序列 RL 中 trajectory-level reward 太稀疏导致 credit assignment 失败"
  shared_approach: "都基于'未来 distribution 变化'构造密集 reward signal"
  contrast_to_prior: "比 trajectory-level REINFORCE 更密集；不像 PRM 需要人工标注"
```

这才是 trend 的目标分辨率。

---

## 上游数据准备

pipeline 把窗口内每篇 paper 的 mechanism_description 收集成列表喂入：

```json
{
  "side": "ai",
  "window_recent": "2026-03-01 to 2026-05-30",
  "window_prior":  "2025-12-01 to 2026-02-28",
  "papers": [
    {
      "paper_id": "2605.19835",
      "mechanism": {
        "one_liner": "用未来 KL 散度作为 per-token advantage 信号",
        "what_problem": "长程 RL trajectory-level reward 太稀疏",
        "contrast": "比 REINFORCE 更密集；不需要 PRM 人工标注",
        "prerequisites": "模型输出 distributional logits"
      },
      "publication_date": "2026-05-20",
      "in_recent_window": true,
      "citation_velocity_30d": 142,
      "affiliation": "DeepMind",
      "method_primary": ["FIPO"]
    },
    ...
  ]
}
```

最多 100 篇（按 priority desc 截取），保持 prompt 大小可控。

---

## System Prompt

```
你是 AI / Fin 学术趋势分析师。任务：从 papers 列表的 mechanism_description 中【动态识别 mechanism families】并分类升降。

【核心要求】
1. 严格 JSON，无前后缀
2. 你的输出单位是 **mechanism family**，不是 paper、不是 tag。
   - 不要输出 "agent" / "RL" / "RLVR" 这种 1-2 词 tag
   - 必须输出 ≥ 30 字的功能描述，类似 "用未来 KL 散度作为 per-token advantage 信号"
3. 聚类逻辑：
   - 两篇 paper 的 mechanism 如果【解决同类抽象问题】+【用同类机制】→ 同一 family
   - 即使方法品牌名不同（FIPO vs KL-Advantage），机制相同就聚一起
   - 同一 paper 可贡献多个 family（如果它涉及多个机制创新）
4. 一个 family 至少 2 篇 paper（单篇不算 trend，归入 "new_emergence"）
5. 每个 family 必须包含：
   - name: 描述性短句（35-80 字），命名核心机制+解决的问题
       ✅ "Dense per-step credit assignment via policy distribution shift signals"
       ✅ "Multi-agent failure attribution with cross-agent gradient tracing"
       ❌ "Agent"  ← 太短
       ❌ "Use of RL for code"  ← 没说清机制
   - representative_one_liner: 选一个最有代表性的 paper 的 one_liner 作样本
   - what_problem: family 共同解决的抽象问题
   - shared_approach: family 共同的核心机制（≤ 60 字）
   - contrast_to_prior: 这族相对前作 / 主流做法多了什么
   - member_papers: [paper_id, ...]
   - paper_count_recent: family 在 recent window 出现的 paper 数
   - paper_count_prior: 同上 in prior window
   - growth_pct: (recent - prior) / prior * 100 (or 999 if prior=0)
   - citation_velocity_30d: sum across member papers
   - representative_affiliations: top 3 unique
6. 分 4 类（同时给 reason 字段）：
   - rising: paper_count_recent ≥ 3 且 growth_pct ≥ 50%
     【加强】citation_velocity_30d ≥ 50 → 更确信
   - falling: paper_count_prior ≥ 5 且 growth_pct ≤ -40%
   - new_emergence: family 首次出现在 recent window（prior=0）且 recent ≥ 2
     （单篇 paper 也可入 new_emergence，标记为 isolated=true）
   - stable_hot: paper_count_recent ≥ 5 且 |growth_pct| < 30%
7. 每类最多 6 个 family。质量优先，宁缺勿滥。
8. **不要输出原 paper 的 mechanism.one_liner 作 name** —— name 必须是你聚类后的抽象描述
```

## User Prompt Template

```
分析以下 {side} 领域 papers 的 mechanism_descriptions，动态识别 mechanism families 并分类。

【时间窗口】
近期: {window_recent}（recent）
对比: {window_prior}（prior）

【papers 数据（最多 100 篇）】
{papers_json}

输出严格 JSON：
{
  "rising": [
    {
      "name": string,                          // 描述性 mechanism family 名（35-80 字）
      "representative_one_liner": string,
      "what_problem": string,
      "shared_approach": string,
      "contrast_to_prior": string,
      "member_papers": [string],
      "paper_count_recent": int,
      "paper_count_prior": int,
      "growth_pct": float,
      "citation_velocity_30d": int,
      "representative_affiliations": [string],
      "isolated": bool                          // true 表示仅 1 篇 paper（仅 new_emergence 可能）
    }
  ],
  "falling":       [...],
  "new_emergence": [...],
  "stable_hot":    [...]
}
```

## Output Schema 示例（节选）

```json
{
  "rising": [
    {
      "name": "Dense per-step credit assignment from policy distribution shift signals",
      "representative_one_liner": "用未来 KL 散度作为 per-token advantage 信号",
      "what_problem": "长程 RL 中 trajectory-level reward 太稀疏，token-level credit assignment 失败",
      "shared_approach": "用'未来 distribution 变化'作密集 per-step credit，避开 PRM 标注成本",
      "contrast_to_prior": "比 REINFORCE / GRPO 更密集；比 PRM 不需人工 reward",
      "member_papers": ["2605.19835", "2603.11111", "2604.22222"],
      "paper_count_recent": 3,
      "paper_count_prior": 0,
      "growth_pct": 999.0,
      "citation_velocity_30d": 142,
      "representative_affiliations": ["DeepMind", "OpenAI", "Tsinghua"],
      "isolated": false
    }
  ],
  "new_emergence": [...],
  "stable_hot": [...],
  "falling": []
}
```

## 失败模式 & 对策

| 失败 | 对策 |
|---|---|
| name 太短（< 30 字）| pipeline 后置过滤 drop |
| name 等于 paper one_liner 原文 | LLM 没真做聚类，重试或 drop |
| member_papers ID 不在输入中 | pipeline 校验，drop |
| 全是 isolated=true 的 family | family 价值低，限制每类 ≤ 2 个 isolated |
| 聚类太粗（"RL methods" 这种）| 重试，并提示 "name 必须描述具体机制" |

## Pipeline 行为

- 每天为 AI 和 Fin 各跑一次
- 输出落 inbox + email
- 同时存到 trends history（未来对比用，目前不实现）

## 备注

这一版彻底改变 trend 的本质：从"字符串 tag 频率统计"变成"LLM 动态聚类 + 机制描述"。
trends 输出从此具备研究分析价值，不只是噪声扫描。
