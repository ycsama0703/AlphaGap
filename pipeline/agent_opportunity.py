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

_SYSTEM = """你从【今天挖到的具体机制清单】出发,找能发【AI 论文】的研究角度。投 NeurIPS/ICML/ICLR/ACL,金融是 killer app / 压力测试场景。**绝对不是**"用 agent 预测收益/波动"。

【最重要的规则——角度必须从机制长出来,不准套模板】
- 我会给你一份【今天挖到的机制清单】(M1, M2, …,每条来自一篇具体论文)。
- 你的任务:**对清单里的每一条机制,问"它在金融场景下逼出什么研究角度?"**——机制是主语,角度从这条机制生长出来。
- **每条 opportunity 必须 anchor 到清单里的一条具体机制**(给 anchor.mechanism_id + 复述那条机制 + 它来自哪篇)。不许凭空造、不许回退到通用 agent 套路(工具路由/证据充分/多agent审计这类**通用模板,除非今天的某条机制真的逼出它,否则不要提**)。
- 一条机制最多产一个角度;某条机制长不出有料角度就**跳过它**。数量 = 有料的机制数,不凑固定类别、不强求覆盖某几类。宁缺勿滥。

【角度的三种 flavor(angle_type)——鼓励多样,不是配额】
- `positive`: 新机制让某 AI 能力↑(成功率/工具路由/推理可靠/样本调用效率/benchmark 暴露失败模式)。
- `counter_narrative`: 领域广泛相信"X 有效/X 是某机制起作用",而一个公平对照(**同模型 ablation / 复杂度对齐 / blind 基线**)很可能**推翻**它。**负向/打脸结果是合法且有价值的——kill 本身就是贡献。**
- `transfer_failure`: 这机制在 AI/别的领域 work,但某个**金融性质**(低 SNR / 非平稳 / regime 切换 / 重尾 / 无 ground-truth)很可能让它崩 → 找出**具体归因**。
（鼓励出现 counter_narrative / transfer_failure,别清一色 positive。）

【硬约束】
1. 贡献/结果是【AI 方法层面】(能力/可靠性/效率/评估/归因),不是 Sharpe;但**结果可以是负向**(counter_narrative/transfer_failure)。
2. why_finance_makes_it_hard 要针对【这条具体机制】说金融用什么压力测它,不要泛泛"金融高风险"。
3. 环境落在 findata 真实面(工具/文档/可核验答案);标 findata_native + 要自建什么(harness/标注如实写)。
4. mechanism_source: 锚定机制来自清单=mined;清单机制逼出但需补一块=gap;别硬塞。
5. prior_work 点名真实工作,说清比它新在哪 / 它信了什么(counter_narrative 尤其要点名"谁信 X")。
6. positive_result_shape 可证伪、带方向和量级(负向角度就写"预期推翻成什么/归因到哪个性质")。
7. 【评分】每条给 scores(各 1-10 整数)+ 综合 + 一行判词:
   - novelty: 真新还是增量/借壳(最接近 prior=被迁移那篇本身 → ≤4)
   - story: **故事性**——这角度能连载几章吗?推翻/照亮一个被信的说法吗?正负向都有趣吗?安全无聊的增量 → 低;有线可钻/反直觉/能写出叙事 → 高
   - ai_contribution: 真 AI 方法/系统/benchmark/归因贡献,还是披皮
   - feasibility: 数据/harness/标注可得性(越要自建越低)
   - publishability: AI venue 接受度
   - positive_attainability: 拿到【可发】结果的把握(注:负向角度此项指"能否干净地证伪")
   composite = round(0.30*novelty + 0.25*story + 0.20*ai_contribution + 0.15*feasibility + 0.10*publishability, 1)
   verdict_line: 一句话判词(像"反叙事角度,有线可钻,med")

输出严格 JSON:
{
  "opportunities": [
    {
      "anchor": {"mechanism_id": "M? (清单里的编号)", "paper_id": "来自哪篇", "mechanism": "复述这条被锚定的机制"},
      "angle_type": "positive|counter_narrative|transfer_failure",
      "subtask": "研究角度(≤30字)",
      "ai_contribution_type": "new_mechanism|reliability_audit|new_benchmark|multi_agent|efficiency|counter_narrative|transfer_failure",
      "why_finance_makes_it_hard": "这条具体机制在金融里被什么压力测试",
      "classical_baseline": "现有做法/被打脸的对象(点名)",
      "prior_work": "代表工作 + 已做到哪 / 信了什么",
      "why_ai_wins": "新机制凭什么提升;或(反叙事)凭什么公平对照会翻;或(迁移失败)哪个金融性质会崩",
      "candidate_mechanism": "锚定的机制(功能描述)",
      "mechanism_source": "mined|gap",
      "findata_env": "用 findata 哪些工具/文档/答案当环境 + findata_native + 要自建什么",
      "positive_result_shape": "可证伪带量级的结果(正向=能力↑;负向=推翻成X/归因到某性质)",
      "novelty_angle": "比 prior 新在哪",
      "publishability": "AI venue 量级 + 主要风险",
      "feasibility": "cheap|med|heavy + 关键前提",
      "scores": {"novelty": int, "story": int, "ai_contribution": int, "positive_attainability": int,
                 "feasibility": int, "publishability": int, "composite": float, "verdict_line": "一句话判词"}
    }
  ]
}
记住:**有几条有料的机制就产几个角度,每个都锚定一条具体机制;不套通用模板、不凑类别。**"""


def generate_agent_opportunity_map(mined_agent_mechs: list[dict] | None = None, *, client=None,
                                   killed: list[dict] | None = None) -> list[dict]:
    """mined agent-paper L3 records → AI-agent×finance opportunities (AI-paper contributions, not return prediction)."""
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.llm_client import LLMClient
    client = client or LLMClient()

    # Enumerate today's mined mechanisms as M1, M2, … — the PRIMARY material. Each opportunity must
    # anchor to one of these ids, so the output tracks the day's specific papers (not a static template).
    mech_lines, n = [], 0
    for m in (mined_agent_mechs or [])[:6]:
        title = m.get("_title", "") or m.get("arxiv_id", "")
        pid = m.get("arxiv_id", "") or title[:30]
        for sm in (m.get("transferable_sub_mechanisms") or [])[:3]:
            n += 1
            mech = sm.get("mechanism") if isinstance(sm, dict) else str(sm)
            mech_lines.append(f"M{n} (paper={pid} · {title[:50]}): {mech}")
    if not mech_lines:
        return []
    parts = [
        "【今天挖到的机制清单——你的主材料。对每一条问:它在金融里逼出什么研究角度?每个角度必须 anchor 到一条 M 编号。】\n"
        + "\n".join(mech_lines),
        f"【findata 可作为环境(工具/文档/可核验答案),仅当某条机制的角度需要时引用】\n{json.dumps(_FINDATA_ENV, ensure_ascii=False)}",
    ]
    # KILL MEMORY: agent gaps we already TESTED/SHELVED — do NOT re-propose them (this generator otherwise
    # never sees the findings bank, so it kept regenerating dead directions like evidence-computation
    # separation / capability-fragility). Mechanism-level + why-dead; the model must avoid or clearly beat them.
    kbrief = []
    for k in (killed or [])[:14]:
        why = (k.get("notes") or k.get("content") or "")[:160]
        kbrief.append(f"- [{k.get('fin_concept') or k.get('mechanism_family','?')}] {k.get('ai_mechanism','')[:80]} — DEAD: {why}")
    if kbrief:
        parts.append("【已测过/已毙的 agent×金融 角度——不要重提这些机制/角度(除非你能明确写清比它【新在哪】且死因不适用)。"
                     "尤其:别再提'证据-计算分离/PAL'、'更多agent/工具的能力-脆弱性权衡'、'谱半径/失败归因'、'验证器分歧拒答'这类已毙方向。】\n"
                     + "\n".join(kbrief))
    parts.append("产出 JSON。每个角度从清单里某条具体机制生长出来(填 anchor.mechanism_id),"
                 "不套通用模板、不凑固定类别、不重提上面已毙方向;鼓励 counter_narrative / transfer_failure。有几条有料就产几个。")
    out = client.chat_json(system=_SYSTEM, user="\n\n".join(parts), temperature=0.6,
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
