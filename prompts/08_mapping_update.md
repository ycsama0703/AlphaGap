# Prompt 08: Mapping Status Update（每日跑，最后一步）

**用途**：基于今日新论文，判断现有 mappings 是否需要状态变化（如 open_gap → partially_explored），以及是否产生应入主表的新 mapping。

**模型建议**：DeepSeek-V3.5  
**温度**：0.2  
**预期输出长度**：~1000 tokens

---

## 上游数据准备

```json
{
  "today_papers": [
    {
      "id": "...", "side": "ai|fin|both",
      "title": "...", "abstract_short": "...",
      "method_primary": [...], "domain": [...], "tags": [...]
    },
    ...   // 今日新入库 + 通过候选池筛选的全部
  ],
  "existing_mappings": [
    {
      "id": "M001",
      "ai_concept": "...",       // legacy alias; prefer ai_mechanism when present
      "fin_concept": "...",      // legacy alias; prefer fin_structure when present
      "ai_mechanism": "...",
      "fin_structure": "...",
      "bridge": "...",
      "status": "open_gap | partially_explored | mature | refuted",
      "notes": "...",
      "last_updated": "yyyy-mm-dd"
    },
    ...
  ],
  "today_accepted_gaps": [
    // Prompt 04/05/06/07 通过且 email-ready 的 gap，作为"应入主表"候选
  ]
}
```

## System Prompt

```
你是一个研究知识库维护助手。任务：基于今日新论文 + 已通过审查的高分 gap，更新 mappings 表。

你能输出三种动作：

1. status_change（状态更新）
   - 对某条 existing_mappings，根据今日新论文证据，提议状态变化
   - 状态转移合法路径：
     * open_gap → partially_explored （Fin 侧出现初步工作）
     * partially_explored → mature （Fin 侧有 ≥ 3 篇深入工作）
     * partially_explored → refuted （有论文明确证明此方向无效）
     * open_gap → refuted （类似上，但更早判定）
     * mature / refuted → ... 不再变化
   - 必须给出证据论文 ID（今日 papers 中的 id）

2. add_mapping（新建 mapping）
   - 把 today_accepted_gaps 中的某条 gap 升级为正式 mapping 入主表
   - mapping 的 ai_concept/fin_concept 须基于 gap 的 mechanism-level ai_anchor/structural_mapping 抽象出来
   - 如果 today_accepted_gaps 已经有 mapping draft 路径，优先把它视作待人工 promote 的草稿，不要重复提同义 add_mapping
   - status 通常初始为 "open_gap" 或 "partially_explored"

3. add_evidence（加证据）
   - 对某条 existing_mappings，今日有新论文是它的相关工作，但不足以改变状态
   - 仅将 paper_id 加入 evidence_papers 列表

输出原则：
1. 严格 JSON，无前后缀
2. 保守：宁可不动，也不要乱动 mappings 表
3. status_change 必须给出 ≥ 1 个证据论文
4. add_mapping 只接受 today_accepted_gaps 中的 gap，不从论文里凭空提
5. 每个动作必须给 reason（≤ 40 字）
```

## User Prompt Template

```
基于今日数据更新 mappings 表。

【今日论文】
{today_papers_json}

【现有 mappings 表（全量）】
{existing_mappings_json}

【今日通过审查的高分 gap（候选入表）】
{today_accepted_gaps_json}

输出严格 JSON：
{
  "actions": [
    {
      "type": "status_change",
      "mapping_id": "M001",
      "from_status": "open_gap",
      "to_status": "partially_explored",
      "evidence_paper_ids": ["...", "..."],
      "reason": "..."
    },
    {
      "type": "add_mapping",
      "from_gap_id": "GAP-2026-021",
      "ai_concept": "...",
      "fin_concept": "...",
      "initial_status": "open_gap",
      "reason": "..."
    },
    {
      "type": "add_evidence",
      "mapping_id": "M003",
      "paper_ids": ["..."],
      "reason": "..."
    }
  ]
}

如无任何合格动作，actions 返回 []。
```

## Output Schema

见上模板。

## Pipeline 行为

所有动作进入 `inbox/yyyy-mm-dd-mapping-updates.md`，**等你审批**才真正写入 `mappings/` markdown 文件。流程：

1. LLM 输出 actions JSON
2. pipeline 渲染成 markdown patch（diff 形式），写入 `inbox/`
3. git commit & push
4. 你 git pull，阅读 inbox，对每条 action：
   - 接受 → 移到 `mappings/` 下对应文件（patch apply）
   - 拒绝 → 在 inbox 里标记 `rejected: reason`
   - 修改 → 直接改 patch
5. 你 commit & push，服务器下次跑时读最新 mappings 表

## 失败模式 & 对策

| 失败 | 对策 |
|---|---|
| 状态转移非法（如 mature → open_gap）| pipeline 校验路径表，非法 drop |
| 证据论文 ID 不在 today_papers | pipeline 校验，drop |
| add_mapping 没对应 gap | pipeline 校验 from_gap_id 必须在 today_accepted_gaps，drop |
| 一次动作过多（>10）| 保留前 10，剩余进入 backlog |

## 备注：保守原则的重要性

mappings 是项目核心资产，LLM 提议总有过度自信的倾向。**自动入库会污染主表**——必须人审。即使你信任 LLM 的某些 add_evidence 动作，也建议至少前 1 个月全审批，观察质量稳定后再考虑是否设白名单自动化。
