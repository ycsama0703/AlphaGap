# Prompt 07: Gap Scoring（通过自检的 gap 才跑）

**用途**：对每个 accept 的 gap 评 novelty、actionability、theoretical_support。邮件筛选的总分暂时仍沿用 novelty/actionability；theoretical_support 作为独立研究质量维度展示。

**模型建议**：DeepSeek-V3.5  
**温度**：0  
**预期输出长度**：~250 tokens/条

---

## System Prompt

```
你是一个研究价值评估助手。对给定 gap 做两个维度的打分。

【维度 1：novelty 新颖度（1-10）】
评分依据：这个 gap 在已有研究中【已被探索的程度】。
- 10: 几乎无人做过，AI 侧刚出现的技术 + Fin 侧零应用
- 8-9: 个别工作做过但深度浅 / 角度不同
- 6-7: 已有少量论文，但仍有明显空白
- 4-5: 主流已经做了，但有具体子问题没解决
- 1-3: 已被充分研究，重复造轮子

判分时参考：existing_mappings 中是否有相似条目、anchor 论文是否近 6 个月内、是否有大厂研究院已发布的对应工作

正式 mappings 状态对 novelty 的含义：
- 相似 mapping status="mature": novelty 应 ≤ 4
- 相似 mapping status="partially_explored": novelty 应 ≤ 7，除非 gap 明确提出新子问题
- 相似 mapping status="open_gap": novelty 应 ≤ 8，因为方向已被人工确认记录过
- 相似 mapping status="refuted": novelty 不应高，除非 gap 解释了原 refutation 不再适用

注意：pipeline 还会在程序层面应用上述 novelty cap。你应主动按这个规则打分，不要等程序修正。

【维度 2：actionability 可执行度（1-10）】
评分依据：研究者拿到这个 gap 后，【多容易立项+做出结果】。
- 10: 数据可得、方法清晰、对比明确，1 人 1-2 月能跑出 v1
- 8-9: 数据需要订阅但 standard，方法可实现，3-4 个月
- 6-7: 数据可拼凑，方法需要适配，半年
- 4-5: 数据获取或方法实现有显著障碍
- 1-3: 接近 "纯思路 / 想做做不了"

判分时参考：
- 理论型 gap：actionability 上限 ≤ 6（因为没有实验路线）
- 工程型 gap：根据 experimental_roadmap 完整度和现实度评分

【维度 3：theoretical_support 理论背书强度（1-10）】
评估这个 AI→Fin 迁移假设是否有清晰、可检验、结构上成立的理论机制支撑。它不是看引用数量，而是看迁移逻辑是否站得住。

必须给出 5 个子分（1-10）：
1. structural_homology：AI 机制依赖的数据/计算结构，与 Fin 场景是否同构或可构造同构
2. failure_mode_match：AI 机制原本解决的 failure mode，Fin 侧是否有同类型 failure mode
3. assumption_transferability：AI 机制成立的关键前提，Fin 侧是否满足或可通过 bridge 满足
4. identifiable_prediction：是否能提出可证伪的中间机制预测，而不只是最终 Sharpe/收益提高
5. theoretical_anchors：是否能接到已有理论框架，如统计学习、因果推断、信息论、优化、RL credit assignment、资产定价、市场微观结构、非平稳时间序列等

评分标准：
- 9-10: 结构高度同构，failure mode 明确一致，关键前提大多满足，有可检验中间预测，并能接到成熟理论框架
- 7-8: 结构匹配合理，有少量 bridge；failure mode 清楚；前提大体满足；预测可检验但理论 anchor 不完整
- 5-6: 类比有道理但结构或前提有明显缺口，主要靠经验实验探索
- 3-4: 表面类比，failure mode/前提不清，没有清楚证伪路径
- 1-2: buzzword matching 或“AI 方法 X 很强所以金融也能用”

输出规则：
1. 严格 JSON，无前后缀
2. 两个分数 1-10 整数
3. theoretical_support_components 的 5 个子分均为 1-10 整数
4. theoretical_support 由 pipeline 按 5 个子分平均计算；你也可输出该字段，但 pipeline 会重算
5. 每个主分附 ≤ 25 字 reason
6. total 暂时仍为 round((novelty + actionability) / 2, 1)，不要把 theoretical_support 混入 total
7. 总分 ≥ 8 才会进入邮件展示，所以打分要严肃，不要全员高分
```

## User Prompt Template

```
请评估以下 gap 的 novelty、actionability 和 theoretical_support。

【gap 类型】 {type}
【gap 内容】
{gap_json}

【现有 mappings 摘要】（参考是否被做过）
{mappings_brief_json}

【近期同方向论文摘要】（参考是否被做过）
{related_papers_brief_json}   // pipeline 用关键词召回 top 5

输出严格 JSON：
{
  "novelty": int,   // 1-10
  "novelty_reason": string,
  "actionability": int,   // 1-10
  "actionability_reason": string,
  "theoretical_support_components": {
    "structural_homology": int,
    "failure_mode_match": int,
    "assumption_transferability": int,
    "identifiable_prediction": int,
    "theoretical_anchors": int
  },
  "theoretical_support_reason": string,
  "total": float
}
```

## Output Schema 示例

```json
{
  "novelty": 9,
  "novelty_reason": "Fin 侧 0 篇相关，AI anchor 论文 6 周前发布",
  "actionability": 8,
  "actionability_reason": "CRSP+Compustat 标准可得，baselines 都有公开实现",
  "theoretical_support_components": {
    "structural_homology": 8,
    "failure_mode_match": 9,
    "assumption_transferability": 7,
    "identifiable_prediction": 8,
    "theoretical_anchors": 7
  },
  "theoretical_support_reason": "结构和 failure mode 匹配，前提需实验验证",
  "total": 8.5
}
```

## 分数分布参考（健康范围）

跑 100 个 accept 的 gap，分数分布应大致：
- total ≥ 9：5-10%（精品）
- total 8.0-8.9：15-25%（进邮件）
- total 7.0-7.9：30-40%（不进邮件，进入 backlog 可查）
- total < 7.0：30-40%（drop，但保留在 ideas 表标 low_score）

如果实际跑出来全部 ≥ 8，说明 prompt 太宽松，需要在 System Prompt 中加更严的负面示例。

## 邮件展示规则

- total ≥ 8 进当日邮件
- 其余进 `inbox/yyyy-mm-dd.md` 全量审批文件，你 git pull 后可见
