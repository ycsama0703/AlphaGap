"""Build the EXPERIENCE bank (避坑经验) — the symmetric half of fin_exemplars (目标范本).
Assembles, $0/no-LLM, from our accumulated experiment records:
  (1) ~/.xp/findings/reflections.jsonl  — per-gap failure post-mortems (already structured)
  (2) knowledge/FAILURE_PREMORTEM.md     — premortem rules #1..N (with case studies)
  (3) authored META-PATTERNS + survived-furthest frontier (distilled from the running log)
Outputs: fin_kb/experience.jsonl + fin_kb/experience.sqlite (table `experience`).
Each record teaches AlphaGap, at gap-finding time: a death/standing-conclusion, when it applies, the $0 precheck, the rule.
Run: python3 fin_kb/build_experience.py
"""
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFL = Path.home() / ".xp/findings/reflections.jsonl"
PREM = ROOT / "knowledge/FAILURE_PREMORTEM.md"
OUTJ = ROOT / "fin_kb/experience.jsonl"
DB = ROOT / "fin_kb/experience.sqlite"

recs = []

# (1) reflections -> lesson records
for l in open(REFL):
    if not l.strip():
        continue
    d = json.loads(l)
    recs.append({
        "id": d.get("gap_id", "?"), "type": "reflection",
        "title": d.get("mechanism_family", d.get("gap_id", "")),
        "verdict": d.get("verdict", ""),
        "death_category": d.get("failure_category", ""),
        "broken_link": d.get("broken_link", ""),
        "trigger_condition": d.get("early_sign_missed", ""),
        "cheap_precheck": d.get("cheap_precheck", ""),
        "distilled_rule": d.get("distilled_rule", ""),
        "caveat": d.get("caveat", ""),
        "source": "reflections.jsonl",
    })

# (2) premortem rules -> rule records (parse the numbered list)
txt = PREM.read_text(encoding="utf-8")
body = txt.split("## How it feeds back")[0]
# each rule starts with "N. **<header>**"; capture number, header, and the body up to the next "N. **"
for m in re.finditer(r"(?m)^(\d+)\.\s+\*\*(.+?)\*\*(.*?)(?=^\d+\.\s+\*\*|\Z)", body, re.S):
    num, header, rest = m.group(1), m.group(2).strip(), m.group(3).strip()
    caught = re.findall(r"caught \*\*(.+?)\*\*", rest)
    rest1 = re.sub(r"\s+", " ", rest)
    recs.append({
        "id": f"premortem-{num}", "type": "premortem_rule",
        "title": header, "verdict": "rule",
        "death_category": header,
        "broken_link": "", "trigger_condition": rest1[:280],
        "cheap_precheck": (re.search(r"\*Check[^*]*?:\*?(.+?)(?:—|$)", rest1) or [None, ""])[1][:220] if "Check" in rest1 else "",
        "distilled_rule": rest1[:400],
        "caveat": "caught: " + "; ".join(caught) if caught else "",
        "source": "FAILURE_PREMORTEM.md",
    })

# (3) authored META-PATTERNS + frontier (distilled from the running log — durable standing conclusions)
META = [
 {"id":"meta-filter-incumbent","title":"可滤波潜变量 = 滤波器 incumbent,预死",
  "death_category":"机制级:目标量有经典最优滤波器→两头堵死",
  "trigger_condition":"AI-机制 gap 的目标量是隐状态/方差/信念等可滤波潜变量(经典解 Kalman/前向算法/GLS/EM)",
  "cheap_precheck":"拟合 HMM/Kalman 恢复真潜变量 R²>0.95 = incumbent 已解;且问 label 在真实数据存不存在还是仅模拟",
  "distilled_rule":"可计算处经典滤波器已最优(AI 机制顶多打平),不可计算处无 ground-truth 监督。B1=逆方差门≈Kalman、A1=残差belief≈前向算法,皆此死法。活得下的形状须针对没有经典最优解的东西(生成/policy/表征即产物)。",
  "caveat":"同 premortem #10/#11"},
 {"id":"meta-data-effectsize-pincer","title":"findata 的 数据×效应 钳形死局",
  "death_category":"战略级:可行数据区效应小,大效应白区数据被封",
  "trigger_condition":"任何只靠 findata(price+fundamentals+macro+text)证明的 gap",
  "cheap_precheck":"问:这个 weak-incumbent 的事件/目标,findata 能不能直接 label?能→多半被数字 telegraph(强 incumbent);不能→数据被封",
  "distilled_rule":"findata 可 label 的事件被 vol/coverage 等数字 telegraph(强 incumbent,效应小);weak-incumbent 的事(restatement/fraud/litigation/survivorship/PIT)恰恰需要被封的数据(CRSP/Compustat/options)。'便宜证明now'与'弱incumbent'在 findata 上互斥。",
  "caveat":"~17 gaps 的共同结构死因"},
 {"id":"meta-return-treadmill","title":"低-SNR 收益跑步机",
  "death_category":"机制级:骑噪声收益目标→方法边际价值塌成0",
  "trigger_condition":"主指标最终落在月度截面 rank-IC ~0.02-0.05 的收益/预测上",
  "cheap_precheck":"最佳单信号 standalone rank-IC 是否 ≥0.05(可学习下限)",
  "distilled_rule":"骑低-SNR 收益的 gap,relMSE/accuracy→1.0 撞噪声天花板,无论架构。优先非收益客观标签,或'研究噪声地板后果'而非打它。",
  "caveat":"同 premortem #6;killed ML-#1/#6,b027/b017/b012"},
 {"id":"meta-fair-baseline","title":"公平基线先行(诚实 null)",
  "death_category":"过程级:赢弱基线/稻草人=假阳性",
  "trigger_condition":"probe/表征'模型表征了X'类,或任何'我们比现状好'的声明",
  "cheap_precheck":"先跑一个看得到同样滞后历史(lags+deltas)的公平对照 / $0 fair-baseline(ACI/deflated-Sharpe/lagged-control)",
  "distilled_rule":"赢只看当前快照/naive 的弱基线不算(ML-#2 死法:GRU'世界模型'其实是趋势编码,加滞后对照后 0/5 存活);C1 conformal naive gap −0.111 但 ACI 已闭合到 −0.023。承重对比必须 vs 公平强基线。",
  "caveat":"同 premortem #7/#9"},
 {"id":"meta-significance-separate","title":"过滤器全过 ≠ 有意义",
  "death_category":"人判级:significance/so-what 是独立的人类门槛",
  "trigger_condition":"一个 gap 过了所有 premortem/shape 闸,看起来可发",
  "cheap_precheck":"自问:做出来能改变什么决策/认知?还是只是'LLM 不会做X'/'刷个 benchmark'?",
  "distilled_rule":"过 premortem ≠ matters。LLM 数字核对 benchmark 被毙='意义有限'(可发但不改变什么)。significance 由人定,不可外包给闸。",
  "caveat":"用户 2026-06 明确:要 consequential/机制,不要 demonstration"},
 {"id":"meta-frontier-survived","title":"活得最久的三个(经验前沿)","verdict":"frontier",
  "death_category":"前沿:最接近成功的尝试及其止步点",
  "trigger_condition":"判断一个新 gap 值不值得做时,对照这三个的止步点",
  "cheap_precheck":"新 gap 是否能越过这些止步:#11 的'机制已知'、E-B 的'效应太小'、#1 的'跨期不稳'",
  "distilled_rule":"#11 backtest-reward-hacking:现象真+可控+leak-free,但机制=已知 optimizer's curse→降为 testbed(ICAIF 级);E-B MNAR:problem 真+verified+可补全,但 RMSE 头room~1%+无下游后果→'真但小';#1 alpha-retention:in-period 真(ρ0.54),但 5×3 split 后 gap SD>mean、符号翻转→跨期不稳。三者=findata 线的能力上限。",
  "caveat":"~14-17 gaps 测试,0 通过完整验证;价值=便宜的 kill + 复利的规则"},
 {"id":"meta-process-discipline","title":"过程纪律:smoke→full→读原始数",
  "death_category":"过程级:自动 verdict 戳会骗人",
  "trigger_condition":"任何实验出'看起来 GO'的结果时",
  "cheap_precheck":"看 per-run 表的方差/符号稳定性/rho,别只看 win% 或 'CONFIRMED' 戳",
  "distilled_rule":"smoke 看似 GO 多为 artifact(crash AUC 0.93@10→0.81@80);#1 auto-verdict 戳 CONFIRMED 但 gap SD>mean、符号翻转、rho≈0=NOT robust。永远跑 full+跨期,gate on 方差+符号+rho 而非 win%。还有:数据断言必须先查/先跑;公平基线零初始化死梯度会伪造'手工赢'。",
  "caveat":"硬规则,血泪"},
]
for m in META:
    m.setdefault("type", "meta_pattern"); m.setdefault("verdict", "standing-conclusion")
    m.setdefault("broken_link", ""); m.setdefault("source", "running-log distillation")
    recs.append(m)

# write jsonl + sqlite
OUTJ.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")
con = sqlite3.connect(DB); con.execute("DROP TABLE IF EXISTS experience")
cols = ["id","type","title","verdict","death_category","broken_link","trigger_condition",
        "cheap_precheck","distilled_rule","caveat","source"]
con.execute(f"CREATE TABLE experience ({','.join(c+' TEXT' for c in cols)})")
con.executemany(f"INSERT INTO experience VALUES ({','.join('?'*len(cols))})",
                [[str(r.get(c,"")) for c in cols] for r in recs])
con.commit()

import collections
print(f"=== experience bank built: {len(recs)} records -> {OUTJ.name} + {DB.name} ===")
print("by type:", collections.Counter(r["type"] for r in recs).most_common())
print("\nreflections:", sum(1 for r in recs if r["type"]=="reflection"),
      "| premortem rules:", sum(1 for r in recs if r["type"]=="premortem_rule"),
      "| meta-patterns:", sum(1 for r in recs if r["type"]=="meta_pattern"))
print("\nmeta-pattern titles:")
for r in recs:
    if r["type"]=="meta_pattern": print("  ·", r["title"])
