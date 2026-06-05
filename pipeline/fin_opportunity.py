"""Fin opportunity map — publishable AI+finance angles, NOT a neutral boundary KB.

Goal (see the publication reframe): find "small breakthroughs / new angles" that can become AI+finance
papers — innovation + POSITIVE result, not boundary mapping, not debunks. First block: financial NLP
(the prime AI-advantage battlefield), two legs: non-event (cross-sectional text signals + text-
understanding tasks) and event (text → event surprise/reaction).

Each opportunity entry is grounded in: (a) findata's REAL text endpoints (verified), (b) our actually-
mined recent AI mechanisms, (c) the financial-NLP literature for novelty positioning. Oriented at the
publishable-positive lens: classical baseline AI beats · why AI wins HERE · what a positive result looks
like · novelty vs prior work · feasibility.

Prototype: generate → human judges the FORM → then scale to agent/event/crypto blocks.
"""
from __future__ import annotations

import json

# verified-available findata text endpoints (probed) — ground data-availability, don't hallucinate it
_FINDATA_TEXT = {
    "transcripts": "earnings-call transcripts, FULL BODY via get_transcript(sym,year,quarter); list via get_transcripts",
    "filings": "SEC filing links (10-K/10-Q): accession, form, filed_date, report_url, filing_url (body fetched from url)",
    "news": "news articles: published_at, publisher, headline, summary, url, category",
    "social_sentiment": "news + social sentiment time series per symbol",
    "earnings_history": "actual/estimated EPS + surprise + surprise_pct + revenue (event labels for event-NLP)",
    "price_for_labels": "get_ohlc → returns/CAR around dates = the predictive target / event-reaction label",
}

_SYSTEM = """你为 AI+金融 NLP 找【能发论文的机会角度】(小突破/新角度,创新+正向结果,不是边界综述、不是 debunk)。
产出"机会条目",每条必须经过【可发表性透镜】审视:经典基线弱在哪、新 AI 机制凭什么在这儿赢、正向结果长什么样。

两条腿都要覆盖:
- non-event(更宽): 横截面文本信号(从文本抽信号→预测横截面收益/风险)+ 文本理解任务本身(数值推理/要素抽取/分歧度)
- event(更窄但 event window 干净、好发): 文本 → 事件 surprise/反应(earnings surprise、并购、宏观)

【硬约束:每条都要 ground,不许空谈】
1. 数据必须落在给定的 findata 真实文本接口上(标 findata_native: true/false + 要不要自建)
2. 经典基线要点名真实方法(如 Loughran-McDonald 词典、bag-of-words 情绪、FinBERT、人工读),AI 要能明确超过它
3. prior_work 要点出这方向已有的代表工作(用于 novelty 定位),并说清你比它新在哪
4. why_ai_wins 要具体到【哪类机制】(功能描述,如"长文档的稀疏关键句归因""多步数值推理 agent"),不要泛说"用 LLM"
5. positive_result_shape 要写出"什么算赢"(可证伪、带方向),且是【正向】(不是"发现X无效")
6. 【机制由任务驱动,绝不硬塞】candidate_mechanism 必须是【这个任务真正需要】的机制类别(功能描述)。
   - 给定的【已挖 AI 机制】只有在【真的适配该任务】时才 anchor,并在 mechanism_source 标 "mined";
   - 不适配就用任务本身需要的机制类别(通识即可),mechanism_source 标 "general";
   - 如果这个任务目前【没有明显合适的成熟机制】,诚实写 candidate_mechanism="(mechanism_gap)" + 说明缺什么,
     mechanism_source 标 "gap"。**宁可标 gap,也绝不把不相干的机制掰上去。**

输出严格 JSON:
{
  "opportunities": [
    {
      "leg": "non-event|event",
      "subtask": "具体 NLP 任务/角度(≤30字)",
      "fin_outcome": "服务什么金融结果(横截面收益/风险/理解任务/事件反应)",
      "classical_baseline": "现在怎么做(点名真实弱基线)",
      "prior_work": "代表 prior + 已做到哪",
      "why_ai_wins": "哪类机制凭什么在这儿赢(机制级,具体)",
      "candidate_mechanism": "任务真正需要的机制类别(功能描述);没合适的填 (mechanism_gap)",
      "mechanism_source": "mined|general|gap",
      "findata": "用哪些接口 + findata_native(true/false) + 要自建什么",
      "positive_result_shape": "什么算赢(可证伪、正向、带方向和粗略量级)",
      "novelty_angle": "比 prior 新在哪",
      "publishability": "贡献类型(empirical/methodological)+ 粗略 venue 量级 + 主要风险",
      "feasibility": "cheap|med|heavy + 关键前提"
    }
  ]
}
产出 5-6 条高质量机会(非事件多几条,事件 1-2 条),宁缺勿滥。"""


def generate_nlp_opportunity_map(mined_mechanisms: list[dict] | None = None, *, client=None) -> list[dict]:
    """Generate the financial-NLP opportunity map (prototype). mined_mechanisms = a few L3 records to
    anchor 'why AI wins' on real recent mechanisms; optional."""
    import sys
    from pathlib import Path
    if str(Path(__file__).resolve().parent.parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pipeline.llm_client import LLMClient
    client = client or LLMClient()

    mech_brief = []
    for m in (mined_mechanisms or [])[:4]:
        for sm in (m.get("transferable_sub_mechanisms") or [])[:3]:
            mech_brief.append(sm.get("mechanism") if isinstance(sm, dict) else str(sm))
    parts = [f"【findata 真实文本接口(数据 ground truth,只能用这些)】\n{json.dumps(_FINDATA_TEXT, ensure_ascii=False, indent=2)}"]
    if mech_brief:
        parts.append("【我们近期 L3 挖到的 AI 机制(仅当真适配某个 NLP 任务时才用,不适配就忽略,绝不硬塞)】\n- "
                     + "\n- ".join(mech_brief))
    parts.append("产出金融 NLP 机会地图(JSON),两条腿都覆盖,每条过可发表性透镜。")
    out = client.chat_json(system=_SYSTEM, user="\n\n".join(parts), temperature=0.5,
                           reasoning=True, max_tokens=6000) or {}
    return out.get("opportunities", []) or []
