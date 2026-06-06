"""Minimal PIT-aware tool agent for Phase-0.

Answers a finance QA over findata and returns atomic claims + the evidence each claim leans on, so a
human can later judge *evidence sufficiency* (the whole point of Phase-0). Deliberately small: a JSON
ReAct loop, ~4 findata tools, observations truncated hard to keep token cost in the cents. Runs on the
cheap default model (deepseek) via the AlphaGap LLMClient unless you pass another client.
"""
from __future__ import annotations

import json
import logging

from . import findata_adapter as fa

log = logging.getLogger("phase0.agent")

MAX_STEPS = 8
_OBS_CHARS = 1800          # cap each tool observation fed back to the model
_TRANSCRIPT_SNIPPETS = 4   # paragraphs returned by search_transcript
_SNIPPET_CHARS = 600


# ── tools (all PIT-truncated to the task's as_of) ───────────────────────────
def _t_fundamentals(c, symbol, as_of, statement="income", **_):
    rows = c.get_fundamentals_history(symbol, statement=statement, period="quarter", limit=8) or []
    return fa.truncate(rows, as_of)[:6]


def _t_earnings(c, symbol, as_of, **_):
    rows = c.get_earnings_history(symbol, limit=16) or []
    return fa.truncate(rows, as_of)[:8]


def _t_news(c, symbol, as_of, query="", **_):
    rows = fa.truncate(c.get_news(symbol, limit=40) or [], as_of)
    if query:
        q = query.lower()
        rows = [r for r in rows if q in (str(r.get("headline", "")) + str(r.get("summary", ""))).lower()] or rows
    return [{"published_at": r.get("published_at"), "headline": r.get("headline"),
             "summary": str(r.get("summary", ""))[:240]} for r in rows[:6]]


def _t_search_transcript(c, symbol, as_of, year=None, quarter=None, query="", **_):
    if not year or not quarter:
        return {"error": "need year and quarter"}
    tr = c.get_transcript(symbol, int(year), int(quarter))
    if not isinstance(tr, dict) or not tr.get("transcript"):
        return {"error": "no transcript"}
    if fa.row_date(tr) and fa.row_date(tr) > as_of:
        return {"error": "transcript after as_of (look-ahead blocked)"}
    body = tr["transcript"]
    paras = [p.strip() for p in body.split("\n") if p.strip()]
    q = (query or "").lower()
    hits = [p for p in paras if q and q in p.lower()] if q else paras
    hits = (hits or paras)[:_TRANSCRIPT_SNIPPETS]
    return {"call_date": tr.get("call_date"), "query": query,
            "snippets": [p[:_SNIPPET_CHARS] for p in hits]}


TOOLS = {
    "get_fundamentals": _t_fundamentals,
    "get_earnings_history": _t_earnings,
    "get_news": _t_news,
    "search_transcript": _t_search_transcript,
}

_TOOLDOC = (
    "get_fundamentals(symbol) -> recent quarterly income-statement rows (revenue, net_income, eps, ...)\n"
    "get_earnings_history(symbol) -> recent rows (actual_eps, estimated_eps, surprise_pct, actual_revenue, report_date)\n"
    "get_news(symbol, query) -> recent headlines+summaries (optionally filtered by query)\n"
    "search_transcript(symbol, year, quarter, query) -> earnings-call snippets matching query"
)

_SYSTEM = """你是一个金融研究 agent。用给的工具回答问题,然后把回答拆成原子 claim,并标注每个 claim 依据哪条证据。
只能用 as_of 之前的信息(工具已自动截断)。每步严格输出 JSON,二选一:
  {"thought": "...", "tool": "<name>", "args": {...}}            # 调一个工具
  {"thought": "...", "final": {                                  # 给最终答案
      "answer": "一段话回答",
      "numeric_answers": {"revenue_yoy_pct": <数或null>, "eps_surprise_pct": <数或null>},
      "claims": [{"text": "一个原子主张", "evidence_ref": "支撑它的工具+内容(如 search_transcript: 'CEO提到...')",
                  "kind": "numeric|qualitative"}]
  }}
可用工具:
""" + _TOOLDOC + """
规则:数值类 claim 必须来自 get_fundamentals/get_earnings_history。营收同比(revenue_yoy_pct)=get_fundamentals 里 ≤as_of 的最近一季 revenue 对比约四个季度前同季 revenue,(新-旧)/旧×100。定性类(原因/驱动/管理层说法)必须引 transcript/news 的具体内容。
不要编造证据;若工具查不到支撑,claim 的 evidence_ref 写 "无直接证据"。最多 8 步,尽快给 final。"""


def run_agent(task: dict, *, client) -> dict:
    """Run the ReAct loop for one task. Returns {answer, numeric_answers, claims, trajectory, n_tool_calls}."""
    c = fa.load_client()
    sym, as_of = task["symbol"], task["as_of"]
    msg = (f"问题: {task['question']}\nsymbol: {sym} | as_of: {as_of} | "
           f"fiscal: FY{task.get('fiscal_year')}Q{task.get('quarter')}")
    traj, n_calls, nudged = [], 0, False
    for step in range(MAX_STEPS):
        try:
            out = client.chat_json(system=_SYSTEM, user=msg, temperature=0.0, max_tokens=1400)
        except Exception as e:
            traj.append({"error": f"llm: {str(e)[:120]}"})
            break
        if "final" in out:
            if n_calls == 0 and not nudged:   # force ≥1 real retrieval before answering
                nudged = True
                msg += ("\n[系统] 你还没成功取到任何证据,不能直接作答。先调用工具取证:"
                        "数值用 get_fundamentals/get_earnings_history,定性用 search_transcript,再给 final。")
                traj.append({"forced_retrieval": True})
                continue
            fin = out.get("final") or {}
            return {"answer": fin.get("answer", ""), "numeric_answers": fin.get("numeric_answers", {}),
                    "claims": fin.get("claims", []) or [], "trajectory": traj, "n_tool_calls": n_calls}
        tool = out.get("tool")
        # strip injected keys — symbol/as_of are fixed by the task, never overridable by the model
        args = {k: v for k, v in (out.get("args") or {}).items() if k not in ("symbol", "as_of")}
        if tool not in TOOLS:
            msg += f"\n[观察] 未知工具 {tool};可用: {list(TOOLS)}"
            traj.append({"thought": out.get("thought"), "bad_tool": tool})
            continue
        try:
            obs = TOOLS[tool](c, sym, as_of, **args)
            n_calls += 1
        except Exception as e:
            obs = {"error": str(e)[:120]}
        obs_s = json.dumps(obs, ensure_ascii=False)[:_OBS_CHARS]
        traj.append({"thought": out.get("thought"), "tool": tool, "args": args, "obs_chars": len(obs_s)})
        msg += f"\n[调用] {tool}({args})\n[观察] {obs_s}"
    return {"answer": "", "numeric_answers": {}, "claims": [], "trajectory": traj,
            "n_tool_calls": n_calls, "incomplete": True}
