"""AI-agent × finance opportunity map — AI is the PROTAGONIST, finance is the scenario.

Distinct from fin_opportunity (which is finance-driven: text→predict-returns, AI as a feature extractor).
Here the paper's skeleton is an AI/agent contribution — a new agent mechanism / system / evaluation /
benchmark — and finance is the demanding application that motivates and stresses it. Target venues are
AI (NeurIPS/ICML/ICLR/ACL), with finance as the killer app. Explicitly NOT return/vol prediction.

Each opportunity is grounded in: real agent mechanisms we mined (L3), findata's real surfaces (tools,
docs, market data as the environment), and the publishable-positive lens — but the WIN is an AI-method
result (capability/reliability/efficiency/benchmark gain), not a Sharpe ratio.
"""
from __future__ import annotations

import json

# findata as an AGENT ENVIRONMENT (tools + data the agent acts on), not as features-for-regression
_FINDATA_ENV = {
    "tool_surface": "~67 get_* endpoints (ohlc, fundamentals, ratios, filings, transcripts, news, "
                    "earnings, holders, macro, ...) = a real, ambiguous, multi-step financial TOOL SET "
                    "an agent must route/compose over",
    "documents": "filings (10-K/10-Q urls), transcripts (full body), news — multi-doc evidence to retrieve/verify",
    "ground_truth": "fundamentals/earnings/prices = checkable answers → automatic correctness + evidence labels",
    "multi_step": "real financial questions need decompose → tool calls → compute → cite (a genuine agent task)",
}

_SYSTEM = """你为【AI agent × 金融】找能发【AI 论文】的机会角度。关键定位:**AI 是主角,金融是它发力/被压力测试的场景**。
论文骨架是一个 AI/agent 贡献——新机制 / 新系统 / 新评估 / 新 benchmark——投 NeurIPS/ICML/ICLR/ACL,金融是 killer app。
**绝对不是**"用 agent 预测收益/波动"(那是金融实证披皮,不是你要的)。

什么算"AI 论文级贡献"(positive result 必须是这类,不是 Sharpe):
- 一个新的 agent 机制让某能力↑(任务成功率、工具路由准确率、推理可靠性、样本/调用效率)
- 一个新的可审计/可验证/拒答机制让 agent 更可信(检测幻觉、证据充分、轨迹可审计)——金融是高风险场景所以有说服力
- 一个新的评估范式 / benchmark 暴露现有 agent 的失败模式(AI 圈认 benchmark 论文)
- 一个多智能体协作/记忆/经济对齐机制的新结果

【硬约束】
1. 贡献和 positive_result 必须是【AI 方法层面】的赢(能力/可靠性/效率/评估),不是金融收益指标
2. 金融场景要解释【为什么金融让这个 AI 问题更难/更有意义】(高风险、需可追溯、工具歧义、多步、监管)——金融是 motivation 不是目的
3. 数据/环境落在给定 findata 真实面(工具集/文档/可核验答案);标 findata_native + 要自建什么(agent harness/标注通常要自建,如实写)
4. 机制【任务驱动】:用给定已挖 agent 机制仅当真适配,标 mechanism_source=mined;否则 general;没合适填 (mechanism_gap)+source=gap。绝不硬塞
5. prior_work 点名真实 agent 工作(ReAct/Reflexion/Toolformer/FinToolBench 等),说清比它新在哪
6. positive_result 可证伪、带方向和粗略量级
7. 【评分,适配 AI 主角】每条给 scores(各 1-10 整数)+ 综合 + 一行判词:
   - novelty: 真新还是增量/借壳(最重要;最接近 prior 就是被迁移那篇本身 → ≤4)
   - ai_contribution: 是真 AI 方法/系统/benchmark 贡献,还是金融实证披皮(借壳 → 低)
   - positive_attainability: 做出【正向、可发】结果的把握(信号/任务可得性)
   - feasibility: 数据/harness/标注可得性(越要自建越低)
   - publishability: AI venue 接受度(贡献+novelty 综合)
   composite = round(0.35*novelty + 0.25*ai_contribution + 0.2*positive_attainability + 0.1*feasibility + 0.1*publishability, 1)
   verdict_line: 一句话给人的判词(像"角度新但要自建大标注集,med")

输出严格 JSON:
{
  "opportunities": [
    {
      "subtask": "AI/agent 角度(≤30字)",
      "ai_contribution_type": "new_mechanism|reliability_audit|new_benchmark|multi_agent|efficiency",
      "why_finance_makes_it_hard": "金融为什么让这个 AI 问题更难/更值得做",
      "classical_baseline": "现有 agent 做法(点名:ReAct/Reflexion/FinToolBench…)",
      "prior_work": "代表 agent 工作 + 已做到哪",
      "why_ai_wins": "新机制凭什么提升(AI 能力/可靠性/效率,机制级)",
      "candidate_mechanism": "任务真正需要的机制(功能描述);没合适填 (mechanism_gap)",
      "mechanism_source": "mined|general|gap",
      "findata_env": "用 findata 哪些工具/文档/答案当 agent 环境 + findata_native + 要自建什么(harness/标注)",
      "positive_result_shape": "AI 方法层面的赢(成功率/路由准确/幻觉检出/调用效率,可证伪带量级)——不是Sharpe",
      "novelty_angle": "比 prior agent 工作新在哪",
      "publishability": "AI venue 量级 + 主要风险",
      "feasibility": "cheap|med|heavy + 关键前提(常是 harness/标注成本)",
      "scores": {"novelty": int, "ai_contribution": int, "positive_attainability": int,
                 "feasibility": int, "publishability": int, "composite": float, "verdict_line": "一句话判词"}
    }
  ]
}
产出 5-6 条,覆盖 new_mechanism / reliability_audit / new_benchmark / multi_agent 几类。宁缺勿滥。"""


def generate_agent_opportunity_map(mined_agent_mechs: list[dict] | None = None, *, client=None) -> list[dict]:
    """mined agent-paper L3 records → AI-agent×finance opportunities (AI-paper contributions, not return prediction)."""
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.llm_client import LLMClient
    client = client or LLMClient()

    mech_brief = []
    for m in (mined_agent_mechs or [])[:5]:
        title = m.get("_title", "") or m.get("arxiv_id", "")
        for sm in (m.get("transferable_sub_mechanisms") or [])[:3]:
            mech_brief.append(f"[{title[:40]}] " + (sm.get("mechanism") if isinstance(sm, dict) else str(sm)))
    parts = [f"【findata 作为 agent 环境(工具/文档/可核验答案,不是回归特征)】\n{json.dumps(_FINDATA_ENV, ensure_ascii=False, indent=2)}"]
    if mech_brief:
        parts.append("【我们 L3 挖到的 agent 机制(仅当真适配某角度才用,不适配就忽略,绝不硬塞)】\n- " + "\n- ".join(mech_brief))
    parts.append("产出 AI-agent×金融 机会地图(JSON)。记住:AI 是主角,贡献是 AI 方法/系统/评估,不是收益预测。")
    out = client.chat_json(system=_SYSTEM, user="\n\n".join(parts), temperature=0.5,
                           reasoning=True, max_tokens=6000) or {}
    return out.get("opportunities", []) or []


# ---------------------------------------------------------------------------
# Deep brief for a selected mechanism gap — the downloadable, TEST-facing artifact.
# AI-protagonist analogue of the engineering 09 brief: full experimental setup + Phase-0,
# so a chosen mechanism gap goes straight to TEST (not a half-finished card).
# ---------------------------------------------------------------------------

_BRIEF_SYSTEM = """你把一个【AI-agent×金融 机制 gap】展开成一份完整、可对接 TEST 的研究 brief(markdown)。
AI 是主角:贡献是 AI 方法/系统/评估,金融是高风险场景,指标是 AI 能力(不是收益)。详细度对标工程 brief,
但维度是 AI 主角的。诚实:数字标(预期);要自建的 harness/标注如实写;novelty 不吹。

输出严格 JSON(每个字段是 markdown 文本):
{
  "title": "≤40字",
  "core_question": "有赌注的 AI 研究问题(一句)",
  "ai_contribution": "empirical/methodological/benchmark 至少一项,超出'把X用到金融'",
  "why_finance_scenario": "金融为何让这个 AI 问题更难/更有说服力(高风险/可追溯/工具歧义/多步)",
  "transfer_rationale": {"structural": "AI侧结构 ↔ Fin侧结构 对应", "why_holds": "为什么这个迁移成立", "credibility": "match|partial|weak + 一句"},
  "novelty_positioning": "最接近的真实 prior work + 我们比它新在哪(related-work式,别吹)",
  "first_experiment": {"question": "最小 go/no-go 问题", "minimal_setup": "最小设置", "go": "达到什么算 go", "stop_pivot": "什么时候停/转向", "runtime": "粗估"},
  "dataset_env": {"sources": "findata 哪些工具/文档 + 要自建什么", "unit": "样本/单位", "split": "划分", "leakage_controls": "防泄漏"},
  "metrics": {"primary": ["AI能力主指标+阈值(如 unsafe-trace 检出≥X、路由准确≥Y)"], "secondary": ["误报/延迟/调用成本"]},
  "baselines_ablations": [{"class": "standard_baseline|control|ablation", "comparator": "比谁/去掉什么", "purpose": "证明什么"}],
  "phase0_preconditions": [{"must_be_true": "机制成立的经验前提", "cheap_check": "$0 体检法", "rule": "可学习下限|诊断对象先存在|因果杠杆|主约束", "risk": "low|med|high"}],
  "feasibility": {"api_cost": "~$X", "compute": "cpu/gpu", "data_build": "要建什么", "main_bottleneck": ""},
  "key_risks": ["1-3 条致命/重要风险 + 降级路径"]
}"""


def generate_agent_gap_brief(opportunity: dict, *, mined_anchor: dict | None = None, client=None) -> dict:
    """Expand ONE mechanism gap into a full TEST-facing brief (dict of markdown fields)."""
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.llm_client import LLMClient
    client = client or LLMClient()
    anchor = ""
    if mined_anchor:
        anchor = (f"\n【锚定论文机制(L3 深挖)】{mined_anchor.get('_title','')} "
                  f"({mined_anchor.get('arxiv_id','')}): {mined_anchor.get('main_claim','')}")
    user = (f"【要展开的机制 gap】\n{json.dumps({k: v for k, v in opportunity.items() if k != 'scores'}, ensure_ascii=False, indent=2)}"
            f"{anchor}\n\n【findata 环境】\n{json.dumps(_FINDATA_ENV, ensure_ascii=False)}\n\n"
            "展开成完整可对接 TEST 的 AI-主角 brief(JSON)。重心:first_experiment 的 go/no-go + metrics + phase0。")
    return client.chat_json(system=_BRIEF_SYSTEM, user=user, temperature=0.3, reasoning=True, max_tokens=6000) or {}


def render_agent_brief_md(brief: dict, opportunity: dict) -> str:
    """Render the brief dict → a downloadable markdown file (mirrors the engineering brief layout)."""
    s = opportunity.get("scores", {}) or {}
    tr = brief.get("transfer_rationale", {}) or {}
    fe = brief.get("first_experiment", {}) or {}
    de = brief.get("dataset_env", {}) or {}
    mt = brief.get("metrics", {}) or {}
    fz = brief.get("feasibility", {}) or {}
    L = [f"# {brief.get('title', opportunity.get('subtask', '?'))}", "",
         f"> **AI-agent × finance mechanism gap** · type: `{opportunity.get('ai_contribution_type','?')}` · "
         f"mechanism source: `{opportunity.get('mechanism_source','?')}`", "",
         f"**Scores** — composite **{s.get('composite','?')}** "
         f"(novelty {s.get('novelty','?')} · ai_contribution {s.get('ai_contribution','?')} · "
         f"positive {s.get('positive_attainability','?')} · feasibility {s.get('feasibility','?')} · "
         f"publishability {s.get('publishability','?')}) — _{s.get('verdict_line','')}_", "",
         "## 1. Core research question", brief.get("core_question", ""), "",
         "## 2. AI contribution", brief.get("ai_contribution", ""), "",
         "## 3. Why finance is the hard scenario", brief.get("why_finance_scenario", ""), "",
         "## 4. Transfer rationale",
         f"- structural: {tr.get('structural','')}",
         f"- why it holds: {tr.get('why_holds','')}",
         f"- credibility: {tr.get('credibility','')}", "",
         "## 5. Novelty positioning", brief.get("novelty_positioning", ""), "",
         "## 6. First experiment (smallest go/no-go)",
         f"- **question**: {fe.get('question','')}",
         f"- **minimal setup**: {fe.get('minimal_setup','')}",
         f"- **GO**: {fe.get('go','')}",
         f"- **STOP / pivot**: {fe.get('stop_pivot','')}",
         f"- **runtime**: {fe.get('runtime','')}", "",
         "## 7. Dataset / environment",
         f"- sources: {de.get('sources','')}",
         f"- unit: {de.get('unit','')} · split: {de.get('split','')}",
         f"- leakage controls: {de.get('leakage_controls','')}", "",
         "## 8. Metrics",
         "- **primary**: " + "; ".join(mt.get("primary", []) or []),
         "- secondary: " + "; ".join(mt.get("secondary", []) or []), "",
         "## 9. Baselines & ablations"]
    for b in brief.get("baselines_ablations", []) or []:
        L.append(f"- [{b.get('class','?')}] {b.get('comparator','')} — {b.get('purpose','')}")
    L += ["", "## 10. Phase-0 empirical preconditions (the real gate)"]
    for p in brief.get("phase0_preconditions", []) or []:
        L.append(f"- [{p.get('risk','?')}] {p.get('rule','')}: {p.get('must_be_true','')} — $0 check: {p.get('cheap_check','')}")
    L += ["", "## 11. Feasibility & risks",
          f"- 💰 {fz.get('api_cost','?')} · 🖥 {fz.get('compute','?')} · 📊 build: {fz.get('data_build','?')} · bottleneck: {fz.get('main_bottleneck','?')}"]
    for r in brief.get("key_risks", []) or []:
        L.append(f"- ⚠ {r}")
    return "\n".join(L)
