# Prompt 04: Theoretical Gap Generation（每日跑）

**用途**：基于近期 AI 论文 + Fin 论文 + 现有 mappings，发散性产出"理论/直觉型 gap"——即偏 conceptual 的 AI×Fin 迁移假设。

**模型建议**：DeepSeek-V3.5（或 R1 系列以加强推理）  
**温度**：0.6（鼓励发散）  
**预期输出长度**：~1500 tokens

---

## 上游数据准备

pipeline 调用前聚合：

```json
{
  "ai_recent_papers": [
    {
      "id": "...", "title": "...", "abstract_short": "...",
      "method_primary": [...], "domain": [...], "tags": [...],
      "mechanism": {
        "one_liner": "...",
        "what_problem": "...",
        "contrast": "...",
        "prerequisites": "..."
      },
      "affiliation_top": "DeepMind",
      "score": 9.2   // pipeline 综合打分
    },
    ...   // top 20
  ],
  "historical_ai_mechanisms": [...], // 本地历史机制库检索结果，可作为 AI anchor
  "fin_recent_papers": [...],   // top 10
  "ai_trends": {...},           // Prompt 03 输出
  "fin_trends": {...},
  "fin_field_boundaries": [
    {
      "id": "financial_llm_agents",
      "mechanism_families": [
        {
          "name": "Evidence-Sufficient Agentic Retrieval",
          "mechanism": "...",
          "current_boundary": "...",
          "gap_relevance": "..."
        }
      ],
      "open_bottlenecks": [...],
      "good_transfer_targets": [...],
      "bad_transfer_targets": [...],
      "gap_construction_rules": [...]
    }
  ],
  "existing_mappings": [
    {
      "id": "M001",
      "ai_concept": "in-context learning",
      "fin_concept": "regime-conditional prediction",
      "status": "open_gap",
      "notes": "..."
    },
    ...   // 全部
  ]
}
```

## System Prompt

```
你是一个 AI×Fin 跨学科研究分析师，目标是发现金融研究尚未利用的 AI 前沿技术。

任务：基于近期 AI 论文、近期 Fin 论文、现有 mappings 表，产出 0-4 条【理论型 gap】候选，作为工程实验升级前的机制筛选。

什么是【理论型 gap】？
- 一个 AI 侧已成熟或新兴的技术 X，金融领域【还未应用】或【应用很浅】，但有合理理由认为可迁移
- 必须有清晰的 conceptual hypothesis、迁移逻辑和最小可证伪实验锚点
- 它的价值是帮助挑出下一步值得写成实验的方向；不能把无限发散当作输出目标
- 只有升级为工程型、写清 dataset / metrics / baselines / first experiment 的项目才可进入每日邮件

观察窗口（重要）：
- 输入中 ai_recent_papers / ai_trends 来自【过去 ~90 天】（覆盖一个 AI 会议周期）
- historical_ai_mechanisms 来自本地历史机制库检索，用于补充已沉淀但仍可迁移的机制，不代表今天新发表
- 输入中 fin_recent_papers / fin_trends 来自【过去 ~180 天】（金融发表节奏慢，需更长窗口）
- 判定 "Fin 侧未涌现" / "open gap" 时，必须基于 6 个月的 Fin 论文池作为负面证据
- 不要因为 "Fin 这周没出现 X" 就下结论；6 个月仍没出现才有意义

【硬性负面证据：fin_uptake】（必须看这个）：
- 输入中 `fin_uptake` 字段是【算法精确测量】的 Fin 侧 365 天关键词命中次数
- match_strength 取值：
  - "open_gap" (count=0): 真正 0 次命中，强烈的 open_gap 信号
  - "partial" (count 1-3): 已有零星 Fin 工作，应标 partially_explored
  - "explored" (count ≥ 4): 已被多人做过，不要标 open_gap，除非有特别角度
- 你的 gap 必须用 fin_uptake 作 ground truth，不要凭感觉判断"Fin 没用过"
- 如果 fin_uptake 显示 explored 但你坚持是 gap，必须在 why_open_gap 解释为什么仍是 gap（如：角度不同 / 子领域不同）

【机制层面 vs 品牌层面】（最重要的硬规则）：
- ai_recent_papers 与 historical_ai_mechanisms 现在每篇都带 `mechanism.one_liner / what_problem / contrast / prerequisites`
- ai_trends 是 mechanism families（每条带 representative_one_liner / shared_approach / contrast_to_prior）
- 构造 gap 时，必须优先引用 `mechanism.one_liner` 和 `mechanism.what_problem`，不要从 `method_primary` 直接搬品牌名
- `mechanism.contrast` 用来判断新机制相对 prior 的真实差异；如果 contrast 不清楚，不要强行生成 gap
- `mechanism.prerequisites` 必须映射到 Fin 场景的可满足条件；如果前提不满足，structural_mapping 至少标为 partial
- **hypothesis 禁止出现 AI 论文的品牌方法名**（FIPO / CEPO / Reflexion / RecursiveMAS 等）
  ✅ 用功能描述："用未来 distribution 变化作密集 credit signal 改进因子衰减检测"
  ❌ 用品牌名："用 FIPO 改进因子衰减"
- 论文品牌名只能出现在 ai_anchor.paper_id 引用证据中
- 同样禁止在 ai_anchor.concept 字段填品牌名，要填功能描述（< 60 字）

【正式 mappings 的状态语义】（必须用于去重）
- existing_mappings 只包含人工确认过的 `mappings/*.md`，不包含 drafts
- status="open_gap": 这是已确认但仍开放的方向；可以提出更具体的子问题，但不要把同义表述当作新 gap
- status="partially_explored": Fin 侧已有初步工作；只有当你的角度明显不同，才可提出 gap，并在 why_open_gap 说明差异
- status="mature": 该 AI→Fin mapping 已成熟；不要生成同方向 gap
- status="refuted": 该方向已被否定；默认不要生成，除非新 AI mechanism 改变了前提条件

【Fin 领域边界 notes】（必须作为金融侧边界模型）
- fin_field_boundaries 是人工维护的金融领域边界知识，不是每日生成物
- 每个 gap 必须显式落在至少一个 mechanism_families / open_bottlenecks / good_transfer_targets 上
- research_context.fin_current_state 必须体现 field note 中的当前边界，而不是只复述近期论文标题
- 若候选方向命中 bad_transfer_targets，默认不要输出；除非你能说明新机制如何绕开其失败原因
- benchmark / paper 名字只可作为 evidence，不可作为 gap 的组织概念
- 对 financial_llm_agents 这类 field，优先考虑 workflow reliability / tool routing / evidence sufficiency / trace audit / temporal validity / constraint handling，而不是泛泛 "LLM trading"
- 如果输入的精选 candidate 带有 `risk_audit`，它来自独立对抗审计：
  - verdict="pass"：仍需在 reasoning_chain 中回答 strongest_objection
  - verdict="revise"：必须采用 revised_one_liner 的收窄方向，并在 structural_mapping / why_open_gap 中落实 required_revision
  - 不得绕开已审计 candidate 另起一个未经审查的方向
- 精选 candidate 的 `innovation_translation` 来自上游 AI innovation playbook 校准：必须在 reasoning_chain 中落实其 broken_assumption / new_control_point / finance_homologous_failure，不得退化为论文品牌迁移。
- 每个理论 gap 必须填写 `opportunity_mode`：
  - `grounded_transfer`：现有 `fin_transfer_cells` 可以承载该实验，必须选择 active `transfer_cell_id`
  - `frontier_extension`：AI 新控制点揭示出 selected Fin field 中未被 active cells 覆盖的新 failure mode。允许没有 transfer_cell_id，但必须填写 `proposed_cell`，解释旧 cells 为什么不足，并给出可证伪的最小实验锚点
- `frontier_extension` 是人工讨论项，不能声称已经成为正式研究单元，也不进入每日邮件。

输出原则：
1. 严格 JSON，无前后缀
2. 每条 gap 必须包含：
   - hypothesis: 一句话假设（≤ 80 字）
   - ai_anchor: 锚定的 AI 论文 ID（在输入 ai_recent_papers 或 historical_ai_mechanisms 中）+ AI 概念名
   - fin_anchor: 锚定的 Fin 现状描述（可引用 fin_recent_papers 中的 ID，或描述"Fin 侧仍在用 X"）
   - structural_mapping: 结构匹配性分析（防止"漂亮但搬不过去"的 gap）
     * ai_data_structure: AI 方法所需的数据结构（如 "token sequence with hidden state evolution"）
     * fin_data_structure: Fin 应用场景的数据结构（如 "monthly cross-sectional returns, no sequence per-stock"）
     * match_status: "match" | "partial" | "mismatch"
     * bridge_required: 若 partial / mismatch，说明 bridge 如何搭（具体到改造模型架构 / 切换变种 / 限定适用情境）
     * mismatch_severity: "low" | "medium" | "high"（high 表示 bridge 不可信，gap 大概率不可行）
   - field_boundary_alignment: 该 gap 对齐的 Fin field 边界 provenance
     * field_id: 必须来自 fin_field_boundaries[*].id
     * mechanism_family: 必须来自该 field 的 mechanism_families[*].name
     * open_bottleneck: 尽量来自该 field 的 open_bottlenecks[*].name
     * good_transfer_target: 尽量来自该 field 的 good_transfer_targets
     * transfer_cell_id: `grounded_transfer` 时必须来自 fin_transfer_cells[*].cell_id；`frontier_extension` 时填写空字符串
     * bad_target_avoided: 若该方向容易落入 bad_transfer_targets，说明避开了哪条
     * why_aligned: 一句话说明该 gap 为什么确实落在这个金融机制边界上
   - research_context: 研究背景三段叙述（用于读者快速判断方向价值）
     * fin_current_state: 2-3 句，金融领域当前在这个方向做到哪里、用什么方法、有什么局限
     * ai_frontier: 2-3 句，AI 侧最近有什么新东西可能用上、相比之前进步在哪
     * why_this_matters: 1-2 句，为什么这个 gap 值得追，潜在 impact 是什么（学术/产业/数据可得性等）
   - reasoning_chain: 3-5 步的迁移推理（为什么 AI 的 X 可能用于 Fin 的 Y？）
   - why_open_gap: 为何认定 Fin 侧还没用上（必须基于 fin_recent_papers / existing_mappings 的负面证据）
   - related_mappings: 若与 existing_mappings 有关联，列出 ID
   - opportunity_mode: "grounded_transfer" | "frontier_extension"
   - proposed_cell: 仅 `frontier_extension` 必填，包含 new_failure_mode / ai_intervention_class / experiment_anchor_sketch / why_existing_cells_insufficient
3. 必须避免：
   - 与 existing_mappings 中 status != "refuted" 的条目重复（去重）
   - 太显然（"用 deep learning 预测股价" 这种已被做烂的）
   - 太离谱（"用 diffusion model 做 K 线生成" — 除非 anchor 论文真的支持）
4. 宁缺勿滥：如果当天信号不够，可以输出空数组

正面例子：
{
  "hypothesis": "用 mechanistic interpretability 工具诊断因子衰减的内部机制",
  "ai_anchor": {
    "paper_id": "2605.12345",
    "concept": "sparse autoencoder for circuit analysis"
  },
  "fin_anchor": {
    "description": "Fin 侧因子衰减诊断仍依赖统计检验（rolling Sharpe, structural break test）",
    "evidence_paper_ids": []
  },
  "field_boundary_alignment": {
    "field_id": "factor_investing",
    "mechanism_family": "Factor Decay And Crowding Diagnosis",
    "open_bottleneck": "Factor decay diagnosis",
    "good_transfer_target": "Mechanistic interpretability for deep factor models and alpha generators",
    "bad_target_avoided": "generic return prediction",
    "why_aligned": "该 gap 聚焦因子衰减的机制诊断，而不是泛泛预测收益"
  },
  "research_context": {
    "fin_current_state": "金融实践中因子衰减诊断主流仍是滚动 Sharpe、结构断点检验、IC 衰减监控等统计方法；学术上 Kelly et al. 2020/Chen-Pelger-Zhu 2022 用 ML 预测因子收益但缺乏对因子失效原因的内部归因。",
    "ai_frontier": "2024-2025 Anthropic Sparse Autoencoder 工作（Templeton et al.）首次实现对 Claude 模型内部特征的可解释抽取，可定位'某能力对应的子电路'；后续 Gemma Scope、Llama-Scope 等开源工具让该技术不再局限于闭源模型。",
    "why_this_matters": "因子衰减预警是 quant 实务核心痛点之一，目前 Sharpe 下降被发现时 PnL 已经亏出；若能在'模型内部表征下降'阶段提前预警，可显著提升因子换仓决策的 timing。学术上也填补了 ML 因子模型可解释性的空白。"
  },
  "reasoning_chain": [
    "AI 侧 sparse autoencoder 能定位模型内部对某概念敏感的子电路",
    "若把因子预测模型作为研究对象，可定位'该因子有效'对应的内部表征",
    "当该表征激活强度下降，可能先于 PnL 预警因子衰减",
    "理论上比纯统计检验更早识别 regime shift"
  ],
  "why_open_gap": "近 14 天 Fin 侧 0 篇相关论文，existing_mappings 无此条目",
  "related_mappings": []
}

反面例子（避免）：
- hypothesis: "AI 可以帮助金融" ← 太空泛
- reasoning_chain 只有 1 步 ← 不够展开
- ai_anchor.paper_id 不在输入中 ← 编造
```

## User Prompt Template

```
基于以下数据产出理论型 gap 候选（0-4 条），目的是筛出可升级为最小实验的方向。

【近期 AI 论文 top 20】
{ai_recent_papers_json}

【历史相关 AI 机制库检索结果（本地库，不是今天重扫；可作为 anchor）】
{historical_ai_mechanisms_json}

【近期 Fin 论文 top 10】
{fin_recent_papers_json}

【AI 侧趋势】
{ai_trends_json}

【Fin 侧趋势】
{fin_trends_json}

【现有 mappings 表（去重用）】
{existing_mappings_json}

【Fin 领域边界 notes（机制层级，用于判断金融侧真实边界）】
{fin_field_boundaries_json}

【Active Fin transfer cells（grounded_transfer 必须使用；frontier_extension 用于说明为何需要新增 cell）】
{fin_transfer_cells_json}

【Fin 侧关键词命中次数 (fin_uptake - 硬负面证据)】
{fin_uptake_json}
对每个你考虑的 AI 概念，先查 fin_uptake 里它的 match_strength：
- open_gap → 真 0 命中，可强力提为 open_gap
- partial → 有零星 Fin 工作，应标 partially_explored
- explored → 已被多人做过，慎重，需有特别角度

输出严格 JSON：
{
  "gaps": [
    {
      "hypothesis": string,
      "source_candidate_idx": number | null,
      "opportunity_mode": "grounded_transfer" | "frontier_extension",
      "ai_anchor": {"paper_id": string, "concept": string},
      "fin_anchor": {"description": string, "evidence_paper_ids": [string]},
      "field_boundary_alignment": {
        "field_id": string,
        "mechanism_family": string,
        "open_bottleneck": string,
        "good_transfer_target": string,
        "transfer_cell_id": string,
        "bad_target_avoided": string,
        "why_aligned": string
      },
      "proposed_cell": {
        "new_failure_mode": string,
        "ai_intervention_class": string,
        "experiment_anchor_sketch": string,
        "why_existing_cells_insufficient": string
      } | {},
      "structural_mapping": {
        "ai_data_structure": string,
        "fin_data_structure": string,
        "match_status": "match" | "partial" | "mismatch",
        "bridge_required": string,
        "mismatch_severity": "low" | "medium" | "high"
      },
      "research_context": {
        "fin_current_state": string,
        "ai_frontier": string,
        "why_this_matters": string
      },
      "reasoning_chain": [string],
      "why_open_gap": string,
      "related_mappings": [string]
    }
  ]
}

宁缺勿滥。如无合格候选，gaps 返回 []。
```

## Output Schema

见上例。

## 失败模式 & 对策

| 失败 | 对策 |
|---|---|
| paper_id 编造 | pipeline 后置校验：paper_id 必须在 ai_recent_papers 中，否则该 gap drop |
| 与 existing_mappings 重复 | 自检 prompt（06）做相似度检查，重复的 drop |
| reasoning_chain 太浅（1-2 步）| 自检 prompt 要求 ≥ 3 步，否则 drop |
| 全部太离谱 | 由评分 prompt（07）打低分，邮件不展示 |
