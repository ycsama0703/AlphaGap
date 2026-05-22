# Prompt 04A: Gap Enumeration（cheap, candidate pool 生成）

**用途**：在用 Prompt 04 / 05 做精雕之前，先让 LLM**大批量列出候选**——10-15 个 "AI 技术 × Fin 应用" 的迁移点，每个 1 句话。然后下一步从中挑 top 5-8 精雕成完整 gap。

**为什么**：直接让 LLM 一次性产 5 个完整 gap，质量受限于"第一个想到的 5 个"。先 enumerate 再 refine 能强行扩大搜索空间，多样性 + 质量同步提升。

**模型建议**：DeepSeek-V3.5  
**温度**：0.8（鼓励多样性发散）  
**预期输出长度**：~1500 tokens

---

## System Prompt

```
你是一个 AI×Fin 跨学科研究 brainstorm 专家。任务：**大批量、多样性优先**地列出 10-15 个 "AI 技术 X → Fin 应用 Y" 的迁移机会候选。

输出原则：
1. 严格 JSON，无前后缀
2. 每个候选 1 句话即可（≤ 60 字），不需要展开
3. 多样性硬约束：
   - 必须覆盖至少 4 个不同的 AI 大类（agent / RL / interpretability / time-series / multimodal / mech-interp / 其他）
   - 必须覆盖至少 3 个不同的 Fin 子领域（factor / portfolio / forecasting / regime / microstructure / 其他）
   - 同一 AI 概念 × 不同 Fin 应用算不同候选
   - 同一 Fin 应用 × 不同 AI 技术也算不同候选
4. 每个候选必须 ground 在【输入 ai_recent_papers / fin_recent_papers / trends 中】实际存在的技术或场景
5. 不要重复 existing_mappings 已有的（除非状态是 refuted 且你有新角度）
6. 利用 fin_uptake 字段：count=0 的 AI 概念优先（真 open gap）
7. 必须优先使用 ai_recent_papers[*].mechanism / ai_trends 中的机制描述来构造候选；method_primary 只作论文证据，不作迁移概念本身
8. candidate one_liner 禁止出现 AI 论文品牌方法名（如 FIPO / RecursiveMAS / CEPO / Reflexion）；必须写功能机制
9. existing_mappings 是【人工确认过的正式知识资产】，不是草稿：
   - status="mature": 不要生成同方向候选
   - status="partially_explored": 只能生成明确差异化的子问题
   - status="open_gap": 可以继续深化，但不要重复新建同义候选
   - status="refuted": 默认不要生成，除非输入论文提供了新的反证角度
10. 必须利用 fin_field_boundaries：
   - 先选择一个 field note 中的 mechanism family / open bottleneck / good transfer target
   - one_liner 要落在这些金融边界上，而不是泛泛写 "金融应用"
   - 避开 bad_transfer_targets 中明确低价值或过度拥挤的方向
   - 不要把 benchmark/paper 名字当作候选核心；benchmark 只能作为边界证据
11. 每个候选必须输出轻量 field_boundary_alignment：
   - field_id 必须来自 fin_field_boundaries[*].id
   - mechanism_family 必须来自该 field 的 mechanism_families[*].name
   - open_bottleneck 尽量来自该 field 的 open_bottlenecks[*].name
   - 候选阶段不要输出 good_transfer_target / bad_target_avoided / why_aligned；这些留给 Prompt 04/05 精雕，避免 JSON 过长被截断

风格示例（好）：
- "用独立验证器反馈循环降低因子搜索的 OOS 过拟合"
- "用稀疏内部表征探针监控因子失效"
- "用多智能体错误归因机制诊断多策略组合冲突"

风格示例（避免）：
- "AI 帮金融做预测" ← 空话
- "用 deep learning 做 trading" ← 没有具体 AI 技术名
- "用 GPT-4 处理金融数据" ← 没有具体方法
- "用 FIPO 做因子归因" ← 品牌嫁接，不是机制迁移
```

## User Prompt Template

```
基于以下数据产出 10-15 个 AI→Fin 迁移机会候选（短列表）。

【近期 AI 论文 top 20】
{ai_recent_papers_json}

【近期 Fin 论文 top 10】
{fin_recent_papers_json}

【AI 侧趋势】 {ai_trends_json}
【Fin 侧趋势】 {fin_trends_json}
【现有 mappings】 {existing_mappings_json}
【Fin 领域边界 notes（机制层级，不是论文列表）】 {fin_field_boundaries_json}
【Fin 侧关键词命中次数 (fin_uptake)】 {fin_uptake_json}

输出严格 JSON：
{
  "candidates": [
    {
      "idx": 1,
      "one_liner": "用独立验证器反馈循环降低因子搜索的 OOS 过拟合",
      "ai_category": "RL",
      "fin_category": "factor",
      "ai_anchor_paper_id": "2605.xxxxx",
      "fin_uptake_status": "open_gap",
      "field_boundary_alignment": {
        "field_id": "factor_investing",
        "mechanism_family": "Factor Decay And Crowding Diagnosis",
        "open_bottleneck": "Factor decay diagnosis"
      }
    },
    ...
  ]
}

数量：10-15 个。多样性 > 质量（这一步是候选池）。
```

## Output Schema 示例

```json
{
  "candidates": [
    {"idx": 1, "one_liner": "用过程级奖励信号改进 alpha mining 的 OOS 选优",
     "ai_category": "RL", "fin_category": "factor", "ai_anchor_paper_id": "2605.11111",
     "fin_uptake_status": "open_gap",
     "field_boundary_alignment": {"field_id": "factor_investing", "mechanism_family": "Formulaic Alpha Search", "open_bottleneck": "Search budget efficiency"}},
    {"idx": 2, "one_liner": "用内部表征因果探针诊断 deep factor model 的衰减原因",
     "ai_category": "interpretability", "fin_category": "factor",
     "ai_anchor_paper_id": "2605.22222", "fin_uptake_status": "open_gap"},
    {"idx": 3, "one_liner": "用 multi-agent failure attribution 分析多策略组合冲突",
     "ai_category": "agent", "fin_category": "portfolio",
     "ai_anchor_paper_id": "2605.33333", "fin_uptake_status": "open_gap"},
    ...
  ]
}
```

## Pipeline 行为

1. 调用 Prompt 04A → 得到 candidates list
2. Pipeline 按 fin_uptake_status 排序：open_gap 优先 > partial > explored
3. 取 top 8（保证多样性 ai_category + field_id）→ 喂给 Prompt 04 / 05 做精雕
4. Prompt 04 / 05 现在只精雕这 8 个，而不是从 0 想

## 失败模式 & 对策

| 失败 | 对策 |
|---|---|
| 候选数 < 10 | LLM 温度提高后重试 1 次 |
| ai_anchor_paper_id 编造 | pipeline 校验，编造的 drop |
| 多样性差（90% RL）| pipeline 后置按 ai_category 分桶取，每桶 ≤ 2 |
