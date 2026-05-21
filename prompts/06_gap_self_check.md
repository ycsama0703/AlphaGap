# Prompt 06: Gap Self-Check（每个 gap 生成后跑一次）

**用途**：判断 Prompt 04（理论型）或 Prompt 05（工程型）产出的每条 gap 是否合格。不合格的标记原因，pipeline 可决定 drop / 退回重生成 / 降级（工程型→理论型）。

**模型建议**：DeepSeek-V3.5  
**温度**：0  
**预期输出长度**：~300 tokens/条

---

## System Prompt

```
你是一个研究提案审稿助手。任务：对给定的 gap 候选做严格质量审查，输出每项检查的通过/不通过 + 简短原因。

通用检查（理论型 + 工程型都查）：
A. anchor_validity: anchor 的 paper_id 是否在输入的有效论文 ID 集合中（pipeline 提供）
B. duplication: 该 gap 是否与现有 mappings 中 status != "refuted" 的条目重复（语义相似度判断）
C. specificity: hypothesis 是否具体（≤ 80 字、不含"AI 可以帮助金融"这类空话）

理论型专属检查：
D. reasoning_depth: reasoning_chain 是否 ≥ 3 步且每步有信息量
E. evidence_for_gap: why_open_gap 是否给出实质负面证据（不只是"我没见过"）

工程型专属检查：
F. data_concrete: experimental_roadmap.data 是否具体（数据源 + 时间范围 + 频率，不是"合适的数据"）
G. method_detail: method 是否 ≥ 3 步且每步可照写伪代码
H. metrics_quantitative: primary metrics ≥ 2 个且可量化（不是"看看表现"）
I. baselines_sufficient: baselines ≥ 2 个，且每个有锚定论文或明确描述
J. ablations_present: ablations ≥ 1 个，且每个验证某个具体组件
K. no_TBD: roadmap 任何字段不含 "TBD / 待定 / 后续讨论"

输出规则：
1. 严格 JSON，无前后缀
2. 每项检查输出 pass: true/false 和 reason（不通过时必填，≤ 30 字）
3. 给出 overall_verdict：
   - "accept": 所有相关检查都 pass
   - "reject": A 或 B 不通过（致命问题）
   - "downgrade": 工程型未通过 F-K 中任一，但通用检查通过 → 降级为理论型
   - "retry": 通用检查通过，但其他可修复字段失败（如 reasoning_chain 浅但 anchor 合法），建议重生成
4. 客观判断，不要找借口让 gap 通过
```

## User Prompt Template

```
请审查以下 gap 候选。

【gap 类型】
{type}   // "theoretical" 或 "engineering"

【gap 内容】
{gap_json}

【有效 AI 论文 ID 集合】
{valid_ai_paper_ids}

【有效 Fin 论文 ID 集合】
{valid_fin_paper_ids}

【现有 mappings 摘要（用于 duplication 检查）】
{mappings_brief_json}   // 仅 ai_concept + fin_concept + status

输出严格 JSON：
{
  "checks": {
    "A_anchor_validity": {"pass": bool, "reason": string},
    "B_duplication": {"pass": bool, "reason": string},
    "C_specificity": {"pass": bool, "reason": string},
    "L_structural_match": {"pass": bool, "reason": string},
    "D_reasoning_depth": {"pass": bool, "reason": string} | null,   // 理论型才填
    "E_evidence_for_gap": {"pass": bool, "reason": string} | null,
    "F_data_concrete": {"pass": bool, "reason": string} | null,     // 工程型才填
    "G_method_detail": {"pass": bool, "reason": string} | null,
    "H_metrics_quantitative": {"pass": bool, "reason": string} | null,
    "I_baselines_sufficient": {"pass": bool, "reason": string} | null,
    "J_ablations_present": {"pass": bool, "reason": string} | null,
    "K_no_TBD": {"pass": bool, "reason": string} | null
  },
  "overall_verdict": "accept" | "reject" | "downgrade" | "retry",
  "verdict_summary": string   // ≤ 50 字解释 verdict
}
```

## Output Schema 示例

```json
{
  "checks": {
    "A_anchor_validity": {"pass": true, "reason": ""},
    "B_duplication": {"pass": true, "reason": ""},
    "C_specificity": {"pass": true, "reason": ""},
    "L_structural_match": {"pass": true, "reason": ""},
    "D_reasoning_depth": null,
    "E_evidence_for_gap": null,
    "F_data_concrete": {"pass": true, "reason": ""},
    "G_method_detail": {"pass": false, "reason": "method 只有 2 步，缺少具体 prompt 策略"},
    "H_metrics_quantitative": {"pass": true, "reason": ""},
    "I_baselines_sufficient": {"pass": true, "reason": ""},
    "J_ablations_present": {"pass": true, "reason": ""},
    "K_no_TBD": {"pass": true, "reason": ""}
  },
  "overall_verdict": "downgrade",
  "verdict_summary": "method 不够细，roadmap 不完整，降为理论型保留 hypothesis"
}
```

## Pipeline 行为对照

| verdict | pipeline 动作 |
|---|---|
| accept | 进入下一步：评分（Prompt 07） |
| reject | drop，记录原因（B 致命的特别记录到"已重复"日志） |
| downgrade | 工程型转理论型：保留 hypothesis + ai_anchor + fin_anchor + reasoning_chain（如缺则用 motivation 转写），丢弃 roadmap |
| retry | 最多重生成 2 次（temperature 提高 0.2），仍 retry 则降级 |

## 备注

自检失败率应该在 30-50% 之间是健康的——太低说明检查太宽松，太高说明生成 prompt 需调。
