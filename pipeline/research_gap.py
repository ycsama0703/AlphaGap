"""Research-gap generation — consumes L3 mined fuel, OUTPUTS runnable experiment slices.

Design stance (deliberate, see feedback_precision_over_breadth + the "don't over-fit on paper-depth"
decision): depth/novelty are decided by EXPERIMENTS, not by a reviewer score. So this layer does NOT
optimize paper-arc narrative or run a revise-to-impress-a-critic loop. Its job is to turn the mined
mechanisms of a paper into the MOST runnable, findata-native experiment slices, gated by the empirical
pre-mortem (the real "can this experiment even pan out" filter), not by a prose-depth judge.

A research gap here = a thin connective wrapper (a core question + which mined mechanisms it uses)
around one or more EXPERIMENT SLICES. The slices are the product. Generation modes still matter for
NOVELTY of what we test (cross-paper composition / problem_first / reframe / frontier > 1:1 transfer),
but we keep the framing light and push the budget into "what concrete experiment, on what findata,
with what go/no-go" + the precondition check.

Pair with research_gap_critic.critique_research_gap() only as OPTIONAL display info (never a gate).
"""
from __future__ import annotations

import json

_SYSTEM = """你把一篇(或几篇)AI 论文的【深度挖掘机制】转成金融研究里【真能跑出来的实验切片】。
核心信条:gap 深不深、行不行,是【做实验】裁决的,不是审稿人打分裁决的。所以不要堆论文级叙事,
把力气全花在"这个机制能切出什么具体、findata 能跑、有明确 go/no-go 的实验"上。

【生成模式(决定测什么的 novelty,优先靠后的)】
- single_transfer: 单个挖掘机制 → 一个金融 failure(最浅,兜底)
- composition: 跨【不同论文】2+ 机制的交互解决一个金融问题(给多篇时优先;组合本身更新)
- problem_first: 从金融一个最硬的 open_bottleneck 出发,反推哪个(可组合)AI 机制能撬动
- reframe: 用挖掘出的某个 boundary_condition / failure_mode,丢掉金融一个被默认的前提
- frontier_extension: 挖掘的边界/失败揭示现有 transfer cell 装不下的新问题(可提,带 proposed_cell)

【每个 gap 必须输出(重心在 experiment_slices)】
- title / core_question: 一句话说清要回答什么(轻,不用写成论文摘要)
- generation_mode + anchor_mechanisms: 用到挖掘结果里的哪些机制(功能描述,非品牌名)
- fin_target: {field_id, mechanism_family_or_bottleneck}(+frontier 填 proposed_cell)
- experiment_slices: 【产品本体,1-3 个】每个必须:
    * hypothesis: 可证伪的一句话(干预 X → 指标 Y 变化 Z)
    * data: 具体到 findata 能给什么(对照 FINDATA_CATALOG:价格/基本面/宏观/文本…),或注明要自建什么
    * findata_native: true/false
    * method: 怎么做(baseline + 干预),≤2 句
    * metric_and_gono: 主指标 + 明确的 go/no-go 阈值
    * cost: 粗估(API$ / 算力 / 数据在不在)
- empirical_preconditions: 【真门槛】机制要成立必须为真的 2-3 个经验事实,各配一个 $0 体检,对照:
    可学习下限(信号独立强度够吗)/ 诊断对象先存在 / 因果杠杆≠结构同构 / 主约束体检 /
    承重区分点先验证("≠已知工作X"的直接实验先跑,只有否定式证据=高风险)/
    换皮的低-SNR选择(核心是"在收益上做选择/搜索"→默认塌回 optimizer's curse gap∝√(logN/T))/
    诚实null(probe/表征类要赢一个**看得到同样滞后历史**的公平基线,赢只看当前快照的弱基线不算)/
    闭式最优=无归纳偏置余量(若机制改动本质是把闭式/定理最优形式——逆方差/Kalman/BLUE/解析滤波——
      硬编码进可学组件gate/权重/attention,则同信息的公平LEARNED基线基本都能学到→无可发表余量;
      承重对比必须是 hand-derived vs LEARNED(同信息),不是 vs uniform/plug-in 稻草人)/
    可滤波潜变量=滤波器incumbent两头堵死(若目标量是有已知最优估计器的潜变量——隐状态/条件方差/后验信念,
      经典解=Kalman/HMM前向算法/GLS/粒子滤波/EM——则可计算处经典滤波器已最优(AI机制顶多打平、无余量),
      不可计算处又无ground-truth label可监督;选题先问①目标量有无经典最优滤波器②方法label在真实数据上存不存在
      还是只在模拟里;有滤波器或label只在模拟里→不产出。活得下的AI机制须针对没有经典最优解的东西
      ——开放式生成/policy/表征本身即产物,而非"估计一个可滤波潜变量")
  哪条明显过不了 → 标 precondition_risk="high" 并说明(不否决,呈现给人)
- publishable_shape + finance_property: 【可发表性门槛】(蒸馏自 250 篇已接收 fin×AI 论文)
    * publishable_shape ∈ {A 新benchmark揭示SOTA失败 / B 决策感知·约束优化 / C 机制迁移到硬金融属性 /
      D LLM行为审计 / E 结构感知表征(数据病理,尤其PIT/restatement=250篇仅3篇白区) / F agent系统+评测 / theory}
      —— **优先 B / E / D**(高headroom、低撞车、不踩收益跑步机)
    * finance_property: **必须点名倚重的金融结构属性**(non-stationarity/heavy-tails/no-arbitrage-accounting/
      microstructure/PIT-restatement)。说不出=none-generic="就是个应用"弱类 → 降权,别当主推
    * 机制迁移(C)仅当该属性是 baseline 失败之因、且可消融(去掉→优势塌)才提

规则:
0. 【注意点,非硬闸】历史经验(避坑库)是**提醒不是枷锁**——别因为一个 idea 触发某条死法就自我审查删掉。
   最有价值的 gap 常是"看似踩了死法、实则绕过"的那种。若触发(如卖点疑似落在低-SNR 噪声收益上、或目标量
   疑似可滤波潜变量),**不要弃用,在该 gap 的 `escape_note` 里正面回答"我怎么绕过/为何它在这不适用"**;
   给不出反驳才算真高风险。大胆产出有想象力的 gap,把风险点如实标注。
1. 机制级、功能化,禁品牌名(品牌名只可进 anchor_mechanisms 的 evidence 引述)
2. 实验切片必须有【明确 go/no-go 阈值】,否则没用——这是可跑性的硬要求
3. 数字只用挖掘结果真报告过的;预测结果标"(预期)",不写成事实
4. 给多篇论文时优先跨论文 composition
5. 切片优先 findata-native + 便宜;贵/要自建数据的也可提,但 cost 和 data_build 写清楚
6. 产出 1-3 个 gap,宁缺勿滥;每个的价值 = 它的切片真能跑 + 前提体检过得去

输出严格 JSON:
{
  "research_gaps": [
    {
      "title": "", "core_question": "", "generation_mode": "",
      "publishable_shape": "A|B|C|D|E|F|theory", "finance_property": "点名属性 或 none-generic",
      "anchor_mechanisms": ["机制功能描述"],
      "label_type": "return-SNR|structural-deterministic|calibration|decision-quality|representation-geometry|behavioral-audit|other",
      "target_quantity": "被预测/优化/度量的量(供硬闸判'是否可滤波潜变量')",
      "has_classical_optimum": "yes|no|partial + 3词理由(目标量有无经典最优估计器:Kalman/前向算法/GARCH/Markowitz/Almgren/BS-SABR)",
      "escape_note": "若本 gap 触发了某条避坑死法(低-SNR/可滤波潜变量/闭式最优/弱类等),在此正面反驳:我怎么绕过它、为何它在这不适用(没触发可留空)",
      "fin_target": {"field_id": "", "mechanism_family_or_bottleneck": "", "proposed_cell": "仅frontier"},
      "experiment_slices": [
        {"hypothesis": "", "data": "", "findata_native": true, "method": "",
         "metric_and_gono": "", "cost": ""}
      ],
      "empirical_preconditions": [
        {"must_be_true": "", "cheap_check": "", "rule": "可学习下限|诊断对象先存在|因果杠杆|主约束",
         "precondition_risk": "low|med|high", "note": ""}
      ]
    }
  ]
}"""


def generate_research_gaps(mined, fin_fields: list[dict], *, modes_hint: str = "", client=None) -> list[dict]:
    """mined record OR list of records (a list enables cross-paper composition) + fin field boundaries
    → research gaps whose product is runnable experiment slices, gated by the empirical pre-mortem."""
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.llm_client import LLMClient
    client = client or LLMClient()

    fin_brief = [{"field_id": n.get("id"),
                  "mechanism_families": [m.get("name") if isinstance(m, dict) else m
                                         for m in (n.get("mechanism_families") or [])][:6],
                  "open_bottlenecks": [o.get("name") if isinstance(o, dict) else o
                                       for o in (n.get("open_bottlenecks") or [])][:5]}
                 for n in fin_fields]
    pool = mined if isinstance(mined, list) else [mined]
    pool_label = (f"【{len(pool)} 篇 AI 论文深度挖掘(优先跨论文组合机制)】"
                  if len(pool) > 1 else "【AI 论文深度挖掘】")
    parts = [f"{pool_label}\n{json.dumps(pool, ensure_ascii=False, indent=2)}",
             f"【金融领域边界(机制族 + 最硬 open bottlenecks)】\n{json.dumps(fin_brief, ensure_ascii=False)}"]
    # ACTIVELY consult the two local KBs (避坑经验 + 目标范本) so generation is grounded, not blind
    try:
        from pipeline import kb
        parts.append(kb.experience_block())
        strong = kb.retrieve_exemplars(label_type="structural-deterministic", k=10) + \
                 kb.retrieve_exemplars(label_type="behavioral-audit", k=6)
        seen = set(); ex_lines = ["【目标范本(已接收且过严格bar的 STRONG-tier 论文长这样;往这些格子靠)】"]
        for r in strong:
            if r.get("strict_tier") != "strong" or r["slug"] in seen:
                continue
            seen.add(r["slug"])
            ex_lines.append(f"· [{r.get('publishable_shape')}|{r.get('finance_property')}|{r.get('label_type')}] {str(r.get('title',''))[:52]}")
        if len(ex_lines) > 1:
            parts.append("\n".join(ex_lines[:18]))
    except Exception:
        pass
    if modes_hint:
        parts.append(f"【模式提示】{modes_hint}")
    parts.append("把机制转成真能跑的实验切片(JSON)。重心:切片的 data/metric/go-no-go + 前提体检。")
    out = client.chat_json(system=_SYSTEM, user="\n\n".join(parts), temperature=0.4,
                           reasoning=True, max_tokens=6000) or {}
    return out.get("research_gaps", []) or []
