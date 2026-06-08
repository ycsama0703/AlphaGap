"""KB access layer — lets AlphaGap ACTIVELY consult the two local knowledge banks at gap-finding time:
  - EXPERIENCE bank (fin_kb/experience.jsonl): #1-#11 premortem rules + reflections + meta-patterns (避坑)
  - EXEMPLAR bank  (fin_kb/exemplars_full.json): 248 accepted fin×AI papers, option-C strict_tier (目标范本)

Two consumers:
  generation (research_gap):  experience_block() + retrieve_exemplars() injected into the prompt
  scoring    (research_gap_critic): score_against_kb() = hard-gate(experience) + taxonomy-novelty(exemplars)
                                    + strict_tier resemblance + multi-dim — deterministic, $0, no LLM.
Both read the live files, so adding a reflection / re-mining papers updates AlphaGap next run (no hand-editing prompts).
"""
from __future__ import annotations
import json, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "fin_kb" / "experience.jsonl"
EXM = ROOT / "fin_kb" / "exemplars_full.json"
FIN_PROPS = {"non-stationarity","heavy-tails","no-arbitrage-accounting","microstructure",
             "pit-restatement","cross-sectional-dependence","regime"}
# keywords that betray a FILTERABLE LATENT target (premortem #11) or a hard-coded closed-form (#10)
_FILTERABLE = ["hidden state","latent state","conditional variance","volatility","posterior belief","belief state",
               "regime","隐状态","条件方差","波动率","后验信念","信念","regime","状态滤波","latent regime"]
_CLASSICAL = ["kalman","hmm","forward algorithm","前向算法","garch","har","ledoit","markowitz","almgren",
              "black-scholes","sabr","gls","blue","particle filter","em ","baum-welch","inverse-variance","逆方差"]


def load_experience():
    return [json.loads(l) for l in open(EXP, encoding="utf-8") if l.strip()] if EXP.exists() else []


def load_exemplars():
    return json.load(open(EXM, encoding="utf-8")) if EXM.exists() else []


def experience_block(max_chars=4000):
    """compact 避坑 text for prompt injection: the meta-patterns + premortem rules (trigger + $0 precheck)."""
    rows = load_experience()
    order = {"meta_pattern": 0, "premortem_rule": 1, "reflection": 2}
    rows.sort(key=lambda r: order.get(r.get("type"), 3))
    lines = ["【避坑经验库 = 注意点,不是否决闸】这些是历史踩过的坑。**不要因为触发某条就放弃一个有想象力的 idea**——",
             "最有价值的 gap 常常正是'看起来踩了某条死法、其实恰好绕过去了'的那种。若你的 gap 触发某条,",
             "不要自我审查删掉,而是在 `escape_note` 里正面回答'我怎么绕过它/为何它在这不适用'。撞坑+给不出反驳=才是真高风险。"]
    for r in rows:
        t = r.get("type")
        if t == "reflection":
            continue  # rules + meta-patterns carry the actionable triggers; reflections are case detail
        tag = "元模式" if t == "meta_pattern" else "规则"
        trig = (r.get("trigger_condition", "") or "")[:120]
        chk = (r.get("cheap_precheck", "") or "")[:120]
        lines.append(f"· [{tag}] {r.get('title','')[:46]} | 触发:{trig} | $0查:{chk}")
    txt = "\n".join(lines)
    return txt[:max_chars]


def retrieve_exemplars(shape=None, finance_property=None, label_type=None, k=6):
    """retrieve the most relevant accepted-paper exemplars for a candidate (by cell match), prefer strong_tier."""
    xs = load_exemplars()
    def score(r):
        s = 0
        if shape and r.get("publishable_shape") == shape: s += 2
        if finance_property and r.get("finance_property") == finance_property: s += 2
        if label_type and r.get("label_type") == label_type: s += 1
        if r.get("strict_tier") == "strong": s += 1
        return s
    return sorted(xs, key=score, reverse=True)[:k]


def taxonomy_lookup(shape, finance_property, label_type=None):
    """cell occupancy + incumbents for a candidate's (shape × finance_property [× label_type]) cell."""
    xs = load_exemplars()
    cell = [r for r in xs if r.get("publishable_shape") == shape and r.get("finance_property") == finance_property
            and (label_type is None or r.get("label_type") == label_type)]
    incumbents = [r.get("incumbent_beaten", "") for r in cell if r.get("incumbent_beaten")]
    strong = [r for r in cell if r.get("strict_tier") == "strong"]
    return {"cell_count": len(cell), "strong_in_cell": len(strong),
            "incumbents": incumbents[:8],
            "crowded": len(cell) >= 6,
            "empty": len(cell) == 0}


def strict_tier(finance_property, label_type, has_classical_optimum):
    named = (finance_property or "").strip().lower() in FIN_PROPS
    nonret = (label_type or "") != "return-SNR"
    noopt = str(has_classical_optimum or "").strip().lower().startswith("no")
    p = sum([named, nonret, noopt])
    fails = [n for n, ok in [("named-finance", named), ("non-return", nonret), ("no-classical-optimum", noopt)] if not ok]
    return ("strong" if p == 3 else "borderline" if p == 2 else "weak"), fails


def considerations(gap: dict):
    """ADVISORY experience-bank checks — '注意点', NEVER an auto-veto (see FAILURE_PREMORTEM: decision-support
    shown to the human, never an auto-veto). Each is a known historical trap the gap should CONFRONT or REBUT
    (via gap['escape_note']), not silently obey. Returns list of {rule, weight, why, escape_hint}."""
    notes = []
    lt = (gap.get("label_type") or "").lower()
    hco = str(gap.get("has_classical_optimum", "")).strip().lower()
    fp = (gap.get("finance_property") or "none-generic").strip().lower()
    blob = " ".join(str(gap.get(k, "")) for k in ("title", "ai_mechanism", "target_quantity", "core_question")).lower()
    has_escape = bool(str(gap.get("escape_note", "")).strip())

    if "return-snr" in lt or ("return" in lt and "snr" in lt):
        notes.append({"rule": "#6 低-SNR收益跑步机", "weight": "high",
                      "why": "label_type=return-SNR 历史上撞噪声天花板、边际价值塌成0",
                      "escape_hint": "若你的目标其实是高-SNR结构/决策量,或你在'研究地板后果'而非打它,在 escape_note 说明"})
    if hco.startswith("yes"):
        notes.append({"rule": "#11 可滤波潜变量/经典最优", "weight": "high",
                      "why": "目标量似有经典最优滤波器 → 可计算处易被滤波器追平",
                      "escape_hint": "若真实过程不可处理(无闭式)、或你针对的是'表征/生成/policy 本身'而非估计该潜变量,说明为何滤波器在这里不适用"})
    elif hco.startswith("partial"):
        notes.append({"rule": "#11 可滤波潜变量(partial)", "weight": "med",
                      "why": "目标量部分有经典最优",
                      "escape_hint": "承重对比记得 vs 那个经典 incumbent,而非 vs 稻草人"})
    if any(w in blob for w in _FILTERABLE) and any(c in blob for c in _CLASSICAL):
        notes.append({"rule": "#11/#10 滤波器incumbent", "weight": "high",
                      "why": "机制疑似把'可滤波潜变量'往经典最优解(Kalman/前向/GARCH)上估",
                      "escape_hint": "若你恰好绕过了(如目标不可滤波、或学习门学不到该闭式形式),证明给审稿看"})
    if fp == "none-generic":
        notes.append({"rule": "none-generic(弱类)", "weight": "low",
                      "why": "未点名金融结构属性,significance 可能偏低",
                      "escape_hint": "能点名一个倚重的金融结构属性吗?或它的价值在别处(如新benchmark/审计)?"})
    for n in notes:
        n["addressed"] = has_escape  # a gap-level escape_note means the author engaged the trap (reviewer judges quality)
    return notes


# back-compat alias (older callers)
hard_gate = considerations


def score_against_kb(gap: dict) -> dict:
    """ADVISORY layered KB read (deterministic, $0): considerations(注意点) + taxonomy-novelty + strict_tier.
    Produces a RISK read + what-to-address, NOT a verdict/veto. The human + LLM critic make the call."""
    shape = gap.get("publishable_shape")
    fp = (gap.get("finance_property") or "none-generic").strip().lower()
    lt = gap.get("label_type")
    notes = considerations(gap)
    tier, fails = strict_tier(fp, lt, gap.get("has_classical_optimum"))
    tax = taxonomy_lookup(shape, fp, lt)
    highs = [n for n in notes if n["weight"] == "high"]
    has_escape = bool(str(gap.get("escape_note", "")).strip())
    # advisory risk level — never an auto-kill; an addressed (rebutted) trap lowers the risk read
    if highs and not has_escape:
        risk = "high — 触发已知死法且未给 escape_note(请让 gap 正面反驳,而非直接弃用)"
    elif highs and has_escape:
        risk = "med — 触发已知死法但作者给了 escape_note(审稿判反驳是否成立)"
    elif notes:
        risk = "low-med — 有注意点,可带 flag 推进"
    else:
        risk = "low — 无触发"
    if tax["empty"]:
        novelty = "EMPTY cell — 可能新(也查'为何空':没用/数据封/效应小)"
    elif tax["crowded"]:
        novelty = f"CROWDED cell ({tax['cell_count']} 篇) — novelty 偏低,有强 incumbent"
    else:
        novelty = f"sparse cell ({tax['cell_count']} 篇)"
    return {"risk": risk, "advisory_only": True,
            "strict_tier": tier, "strict_fails": fails,
            "considerations": notes, "taxonomy": {**tax, "novelty_read": novelty},
            "exemplar_incumbents": tax["incumbents"],
            "note": "注意点非否决:撞规则的 gap 应给 escape_note 正面反驳;最终取舍由人/LLM-critic 定。"}
