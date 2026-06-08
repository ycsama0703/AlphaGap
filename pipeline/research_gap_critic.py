"""Research-gap critic — OPTIONAL display info, NOT a gate.

Decision (see the "don't over-fit on paper-depth" steer): depth/novelty are decided by EXPERIMENTS,
not a reviewer score. So this critic NEVER gates generation — it's a one-shot, human-facing sanity
read you can run when you want a second opinion. Its still-useful job is the FABRICATION check:
predicted numbers stated as fact, unverifiable benchmark names, "novel" claims that aren't — grounded
against the local paper corpus. The depth/novelty scores are advisory only (like significance / cost).

There is intentionally NO revise loop: polishing prose to satisfy a critic over-fits paper-narrative,
which is exactly what we decided not to do. critique_research_gap(gap, mined, client) -> dict.
"""
from __future__ import annotations

import json
import re


def _corpus_grounding(gap: dict) -> dict:
    """Pull benchmark/prior-work names the gap cites; check if each appears in the local paper corpus.
    Not-found ≠ fabricated (corpus is partial), but it's a 'verify' flag — and a name found nowhere
    that's stated as an established benchmark is a red flag."""
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    text = " ".join(str(gap.get(k, "")) for k in ("novelty_argument", "contribution", "paper_figures",
                                                   "experiment_slices", "core_question"))
    # candidate named entities: CamelCase / ALLCAPS / *Bench / *QA tokens
    names = set(re.findall(r"\b([A-Z][A-Za-z]+(?:Bench|QA|Eval|Bank)|[A-Z]{2,}(?:-[A-Za-z0-9]+)?)\b", text))
    names = {n for n in names if len(n) >= 3 and n not in {"JSON", "AI", "RL", "KL", "MDP", "GAE", "PPO"}}
    if not names:
        return {"checked": [], "not_in_corpus": []}
    from pipeline import db
    found, missing = [], []
    with db.connect() as c:
        for n in list(names)[:12]:
            hit = c.execute("SELECT 1 FROM papers WHERE title LIKE ? OR abstract LIKE ? LIMIT 1",
                            (f"%{n}%", f"%{n}%")).fetchone()
            (found if hit else missing).append(n)
    return {"checked": found, "not_in_corpus": missing}


_SYSTEM = """你是顶会(NeurIPS/ICML 级)的【对抗性】审稿人,专门戳穿"装深"的研究 gap。默认怀疑。
一个"漂亮叙事 + 编造数字/基准"的 gap 比一个老实承认浅的 gap 更糟——你的任务是把这两者分开。

逐项严格审:

【depth(1-10)】这是论文还是 workshop note?
- core_question 是真有赌注的问题,还是"验证 X 在 Y 有效"换皮?
- sub_questions 是真的彼此独立、合起来 > 单实验,还是一个实验拆成几句话凑数?
- contribution 真超出"X 在 Y 有效"吗?theoretical 那条是真命题还是空话?
- 三张图真能撑起论文,还是一张图的事拆成三张?
减分:单实验伪装 / 子问题互相依赖其实是一个 / 贡献=增量验证 / theoretical 是 buzzword。

【novelty(1-10)】真新还是换皮?
- novelty_argument 给的"最接近 prior work"是真存在的工作吗?它真比那个新吗?
- 还是只是"金融没人做过"这种琐碎 novelty(冷僻≠创新)?

【fabrication_flags(最重要)】列出所有:
- 说成既有事实、但其实是【预测/未做】的数字(如"Sharpe 提升0.2-0.4""成功率+10-15%"——这些是实验还没做的预测,不能当卖点写成事实)
- 【可能不存在】的基准名/数据集名/prior work 名(尤其 *Bench / *QA 这类,很可能是编的)
- mined 证据里没有、却被当论文已报告结果引用的数字
注:corpus_grounding.not_in_corpus 里的名字是"本地语料没搜到"的,优先怀疑这些是编造的基准。

【verdict】"paper_grade" | "needs_work" | "dressed_up_thin"
- paper_grade: 真研究弧,novelty 站得住,无严重编造
- dressed_up_thin: 叙事漂亮但内核是单实验/换皮,或有编造基准/把预测当事实

输出严格 JSON:
{
  "depth_score": int, "depth_reasoning": "≤60字",
  "novelty_score": int, "novelty_reasoning": "≤60字,点名最接近的真实 prior 或指出 novelty 琐碎",
  "fabrication_flags": ["每条:哪个数字/名字是编的或预测当事实"],
  "verdict": "paper_grade|needs_work|dressed_up_thin",
  "required_fixes": ["要砍掉或补实的具体项"],
  "one_line": "一句话给人的判决"
}"""


def critique_research_gap(gap: dict, mined: dict | None = None, *, client=None) -> dict:
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.llm_client import LLMClient
    client = client or LLMClient()
    grounding = _corpus_grounding(gap)
    # LAYER 0 — KB hard-gate + taxonomy-novelty (deterministic, $0): consult experience + exemplar banks
    try:
        from pipeline import kb
        kb_score = kb.score_against_kb(gap)
    except Exception as e:
        kb_score = {"verdict": "n/a", "error": str(e)[:80]}
    mined_numbers = (mined or {}).get("key_quant_results", []) if mined else []
    user = (f"【研究 gap】\n{json.dumps(gap, ensure_ascii=False, indent=2)}\n\n"
            f"【KB 分层评分(经验库注意点 + 范本库 taxonomy;**advisory,非否决**)】\n"
            f"{json.dumps(kb_score, ensure_ascii=False)}\n\n"
            f"读法:considerations 是历史死法提醒,不是自动毙。撞 high-weight 死法但 gap 给了成立的 escape_note(正面反驳)→ "
            f"不降级、甚至该加分(它可能正是绕过已知陷阱的新点);撞了又给不出/反驳不成立 → 才降为 dressed_up_thin。"
            f"empty/sparse cell=可能新但查'为何空';crowded cell=novelty 偏低。\n\n"
            f"【corpus_grounding(本地语料是否搜到这些名字)】\n{json.dumps(grounding, ensure_ascii=False)}\n\n"
            f"【挖掘结果里真实报告过的数字(只有这些才是'已知事实',其余数字都是预测)】\n"
            f"{json.dumps(mined_numbers, ensure_ascii=False)}\n\n对抗性审这个 gap,输出 JSON。")
    out = client.chat_json(system=_SYSTEM, user=user, temperature=0.0, reasoning=True, max_tokens=2000) or {}
    out["_corpus_grounding"] = grounding
    out["_kb_score"] = kb_score
    return out
