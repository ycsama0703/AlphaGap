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


# THEORY line — the protagonist is a FOUNDATIONAL mechanism (math/stats/optimization/probability/
# learning-&-RL theory), finance is the structure it must serve. Same JSON schema as _SYSTEM (so
# scoring/rendering are unchanged), but the framing and hard constraints differ: name the incumbent
# you must beat, self-screen for low-SNR/no-inductive-bias deaths, target the FRONTIER not the classics.
_SYSTEM_THEORY = """你从【今天挖到的具体底层机制清单】出发,找"把一个**底层数学/统计/优化/概率/学习理论机制**移植进金融"的研究角度。机制是主角,金融的真实**结构**(低信噪比/非平稳/regime切换/重尾/不能实盘探索/训练≠实盘的分布漂移/归因混淆)是它要服务的场景。可投 AI(NeurIPS/ICML/ICLR)或计量/统计金融 venue。**绝对不是**"再训一个大模型预测收益"。

【最重要的规则——角度必须从机制长出来,不准套模板】
- 我给你一份【今天挖到的机制清单】(M1, M2, …,每条来自一篇具体论文)。
- 对清单里**每一条机制**问:"它的归纳偏置,正好对上哪个被现有方法服务不足的金融结构?要打败谁?"——机制是主语,角度从这条机制生长。
- **每条 opportunity 必须 anchor 到清单里一条具体机制**(anchor.mechanism_id + 复述 + 来自哪篇)。长不出有料角度的机制就**跳过**。宁缺勿滥。

【角度的三种 flavor(angle_type)】
- `positive`: 机制的归纳偏置正好对上某金融结构,预期在公平对照下**打败现有 incumbent**(HAR-RV / 样本协方差 / 卡尔曼 / 经验分位数 / 均值方差 / last-value)。
- `counter_narrative`: 领域相信"某 incumbent 已经够好"或"某花哨法有效",而这个机制(或一个更简单基线)在某结构上公平对照能**翻**它。负向结果合法且有价值。
- `transfer_failure`: 机制在 iid / 理论假设下成立,但某金融性质(低 SNR / 非平稳 / 重尾 / 无 ground-truth)很可能让它**崩** → 找出具体归因。

【硬约束——理论线专属,必须逐条满足】
1. **指名 incumbent(必填 classical_baseline)**:点名这个机制要打败的现有方法是谁,以及它的归纳偏置在哪个金融结构上不如本机制。没有指名的角度=废角度。
2. **理论自筛(前置 premortem,写进 positive_result_shape / publishability)**:先自检——这任务是不是低信噪比?机制是不是高容量、无金融特定归纳偏置(会踩"优化者诅咒"/无 inductive-bias 空间/打不过最笨基线)?若是,**如实标注预判死法**,别假装会赢。
3. **盯前沿不盯经典**:经典结果(如 Ledoit-Wolf 2004 收缩、标准卡尔曼)一律视为 **incumbent**,不算创新。创新点必须是"**近期、尚未被计量/quant 搬进金融**的底层进展"。若该机制其实早被搬过 → 标 counter_narrative 或跳过。
4. **防 theory-washing**:机制必须能在真实数据上**真的打败 incumbent**;只起装饰作用、其实不 bind 的漂亮 bound 不算贡献。
5. **可测**:环境落在 findata 真实**数值**面(深数值:基本面40年/价格20年/transcript全文~15年/宏观),标 findata_native + 要自建什么。
6. positive_result_shape 可证伪、带方向和量级(负向角度写"预期推翻成什么/归因到哪个金融性质")。
7. 【评分】每条给 scores(各 1-10 整数)+ 综合 + 一行判词:
   - novelty: 真新还是借壳(借现成数学没问题,但若机制早被搬进金融 → ≤4)
   - story: 故事性——能连载几章?推翻/照亮一个被信的 incumbent 说法吗?
   - ai_contribution: 此处指【机制贡献】——是真有移植价值的底层机制,还是套壳/装饰性 bound
   - feasibility: findata 上可测性(越要外部数据越低)
   - publishability: venue 接受度
   - positive_attainability: 拿到【可发】结果的把握(负向角度=能否干净证伪)
   composite = round(0.30*novelty + 0.25*story + 0.20*ai_contribution + 0.15*feasibility + 0.10*publishability, 1)
   verdict_line: 一句话判词

输出严格 JSON(schema 同 AI 线,语义按理论线理解):
{
  "opportunities": [
    {
      "anchor": {"mechanism_id": "M? (清单编号)", "paper_id": "来自哪篇", "mechanism": "复述这条被锚定的底层机制"},
      "angle_type": "positive|counter_narrative|transfer_failure",
      "subtask": "研究角度(≤30字)",
      "ai_contribution_type": "estimator_transplant|robustness_mechanism|uncertainty_quantification|optimization_objective|counter_narrative|transfer_failure",
      "why_finance_makes_it_hard": "这条机制对上哪个金融结构 / 被什么压力测",
      "classical_baseline": "【必填】要打败的 incumbent(点名:HAR-RV/样本协方差/卡尔曼/经验分位数/...)+ 它差在哪",
      "prior_work": "代表工作 + 已做到哪 / 信了什么 / 是否已被搬进金融",
      "why_ai_wins": "机制的归纳偏置凭什么在这个金融结构上胜过 incumbent;或(迁移失败)哪个金融性质会让它崩",
      "candidate_mechanism": "锚定的底层机制(功能描述)",
      "mechanism_source": "mined|gap",
      "findata_env": "用 findata 哪些数值面当数据 + findata_native + 要自建什么",
      "positive_result_shape": "可证伪带量级的结果 + 理论自筛预判(低SNR/无归纳偏置是否触发死法)",
      "novelty_angle": "比 prior 新在哪 / 为什么是前沿而非经典",
      "publishability": "venue 量级 + 主要风险(含 theory-washing 风险)",
      "feasibility": "cheap|med|heavy + 关键前提",
      "scores": {"novelty": int, "story": int, "ai_contribution": int, "positive_attainability": int,
                 "feasibility": int, "publishability": int, "composite": float, "verdict_line": "一句话判词"}
    }
  ]
}
记住:**每个角度锚定一条具体机制、必须指名要打败的 incumbent、盯前沿不盯经典、低SNR/无归纳偏置如实预判死法。**"""


def generate_agent_opportunity_map(mined_agent_mechs: list[dict] | None = None, *, client=None,
                                   killed: list[dict] | None = None, track: str = "ai") -> list[dict]:
    """mined L3 records → opportunities. track="ai": AI-agent×finance (AI-method contributions).
    track="theory": foundational-mechanism (math/stats/opt) × finance-structure transplant."""
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.llm_client import LLMClient
    client = client or LLMClient()
    is_theory = track == "theory"
    system = _SYSTEM_THEORY if is_theory else _SYSTEM

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
    if is_theory:
        hdr = ("【今天挖到的底层机制清单——你的主材料。对每一条问:它的归纳偏置对上哪个金融结构?要打败哪个 incumbent?"
               "每个角度必须 anchor 到一条 M 编号。】\n")
        env_note = f"【findata 真实数值面(深数值/价格/基本面/transcript/宏观)可作为可测环境】\n{json.dumps(_FINDATA_ENV, ensure_ascii=False)}"
    else:
        hdr = "【今天挖到的机制清单——你的主材料。对每一条问:它在金融里逼出什么研究角度?每个角度必须 anchor 到一条 M 编号。】\n"
        env_note = f"【findata 可作为环境(工具/文档/可核验答案),仅当某条机制的角度需要时引用】\n{json.dumps(_FINDATA_ENV, ensure_ascii=False)}"
    parts = [hdr + "\n".join(mech_lines), env_note]
    # KILL MEMORY: agent gaps we already TESTED/SHELVED — do NOT re-propose them (this generator otherwise
    # never sees the findings bank, so it kept regenerating dead directions like evidence-computation
    # separation / capability-fragility). Mechanism-level + why-dead; the model must avoid or clearly beat them.
    kbrief = []
    for k in (killed or [])[:14]:
        why = (k.get("notes") or k.get("content") or "")[:160]
        kbrief.append(f"- [{k.get('fin_concept') or k.get('mechanism_family','?')}] {k.get('ai_mechanism','')[:80]} — DEAD: {why}")
    if kbrief:
        if is_theory:
            parts.append("【已测过/已毙的角度——不要重提(除非明确写清比它【新在哪】且死因不适用)。】\n" + "\n".join(kbrief))
        else:
            parts.append("【已测过/已毙的 agent×金融 角度——不要重提这些机制/角度(除非你能明确写清比它【新在哪】且死因不适用)。"
                         "尤其:别再提'证据-计算分离/PAL'、'更多agent/工具的能力-脆弱性权衡'、'谱半径/失败归因'、'验证器分歧拒答'这类已毙方向。】\n"
                         + "\n".join(kbrief))
    if is_theory:
        parts.append("产出 JSON。每个角度锚定清单里一条具体底层机制(填 anchor.mechanism_id)、"
                     "**必须指名要打败的 incumbent(classical_baseline)**、盯前沿不盯经典、对低SNR/无归纳偏置如实预判死法;"
                     "鼓励 counter_narrative / transfer_failure。有几条有料就产几个。")
    else:
        parts.append("产出 JSON。每个角度从清单里某条具体机制生长出来(填 anchor.mechanism_id),"
                     "不套通用模板、不凑固定类别、不重提上面已毙方向;鼓励 counter_narrative / transfer_failure。有几条有料就产几个。")
    out = client.chat_json(system=system, user="\n\n".join(parts), temperature=0.6,
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


_BRIEF_SYSTEM_THEORY_HEAD = """你把一个【底层机制×金融结构 的 gap】展开成一份完整、可对接 TEST 的研究 brief(markdown)。
主角是一个**底层数学/统计/优化/概率/学习理论机制**,金融的真实结构(低信噪比/非平稳/重尾/无探索/分布漂移)是它要服务的场景。
**核心要求**:novelty_positioning 必须点名【要打败的 incumbent】(HAR-RV/样本协方差/卡尔曼/经验分位数/...)并说明本机制的归纳偏置在哪个金融结构上胜过它;
盯前沿不盯经典(经典=incumbent);first_experiment 的 go 必须是"在真实数据上公平对照打败该 incumbent",而非装饰性 bound(防 theory-washing)。
指标是机制层面的可证伪结果(不是 Sharpe)。诚实:数字标(预期)、要自建的如实写、对低SNR/无归纳偏置的死法风险写进 key_risks。

输出严格 JSON(字段同下,语义按理论线理解)。"""


def generate_agent_gap_brief(opportunity: dict, *, mined_anchor: dict | None = None, client=None,
                             track: str = "ai") -> dict:
    """Expand ONE mechanism gap into a full TEST-facing brief (dict of markdown fields).
    track="theory" swaps the framing to foundational-mechanism × finance-structure (incumbent-anchored)."""
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.llm_client import LLMClient
    client = client or LLMClient()
    # theory track: reuse the same JSON schema (so render is unchanged) but swap the protagonist framing.
    brief_system = (_BRIEF_SYSTEM_THEORY_HEAD + _BRIEF_SYSTEM[_BRIEF_SYSTEM.index("输出严格 JSON"):]
                    if track == "theory" else _BRIEF_SYSTEM)
    anchor = ""
    if mined_anchor:
        anchor = (f"\n【锚定论文机制(L3 深挖)】{mined_anchor.get('_title','')} "
                  f"({mined_anchor.get('arxiv_id','')}): {mined_anchor.get('main_claim','')}")
    user = (f"【要展开的机制 gap】\n{json.dumps({k: v for k, v in opportunity.items() if k != 'scores'}, ensure_ascii=False, indent=2)}"
            f"{anchor}\n\n【findata 环境】\n{json.dumps(_FINDATA_ENV, ensure_ascii=False)}\n\n"
            "展开成完整可对接 TEST 的 brief(JSON)。重心:first_experiment 的 go/no-go + metrics + phase0。")
    return client.chat_json(system=brief_system, user=user, temperature=0.3, reasoning=True, max_tokens=6000) or {}


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
