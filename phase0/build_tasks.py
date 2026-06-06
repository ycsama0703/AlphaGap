"""Build a Phase-0 micro set from findata, each with auto-verifiable numeric ground truth.

Each task = one earnings quarter for a large/mid-cap:
  (a) NUMERIC part  — revenue YoY % (auto-graded). Computed from get_fundamentals income statement —
      the SAME endpoint the agent reads — matched by period_end_date, so grading is apples-to-apples and
      unit-free (an earlier version computed it from earnings_history → source/quarter mismatch → false fails).
  (b) QUALITATIVE part — "what did management cite as the driver?" (needs the transcript → its evidence
      sufficiency is what humans annotate; this is where "answer-correct-but-evidence-insufficient" shows).
as_of = the later of the call date / report date, so the agent may only use info up to the earnings event.

Run:  python -m phase0.build_tasks            # writes phase0/seed_tasks.jsonl
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from . import findata_adapter as fa

log = logging.getLogger("phase0.build_tasks")

SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM",
           "WMT", "XOM", "PFE", "KO", "NKE", "DIS", "INTC"]
PER_SYMBOL = 3
OUT = Path(__file__).resolve().parent / "seed_tasks.jsonl"


def _d(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except Exception:
        return None


def _nearest_earn(earn: list[dict], call_date: str):
    cd = _d(call_date)
    best, gap = None, 1e9
    for r in earn:
        rd = _d(r.get("report_date") or r.get("fiscal_date"))
        if not rd or not cd:
            continue
        g = abs((rd - cd).days)
        if g < gap:
            best, gap = r, g
    return best if gap <= 21 else None


def _fund_yoy(c, symbol: str, as_of: str):
    """revenue YoY % from get_fundamentals income statement (the agent's own source), PIT-truncated to as_of.
    Compares the most-recent quarter <= as_of against the row ~1 year earlier. Returns (yoy, revenue, period)."""
    rows = fa.truncate(c.get_fundamentals_history(symbol, statement="income",
                                                  period="quarter", limit=12) or [], as_of)
    rows = [r for r in rows if r.get("revenue") and r.get("period_end_date")]
    rows.sort(key=lambda r: r["period_end_date"], reverse=True)
    if not rows:
        return None, None, None
    cur = rows[0]
    cur_d = _d(cur["period_end_date"])
    prior = None
    for r in rows[1:]:
        d = _d(r["period_end_date"])
        if d and cur_d and 330 <= (cur_d - d).days <= 400:
            prior = r
            break
    yoy = (round((cur["revenue"] - prior["revenue"]) / prior["revenue"] * 100, 1)
           if prior and prior.get("revenue") else None)
    return yoy, cur["revenue"], cur["period_end_date"]


def build():
    c = fa.load_client()
    tasks = []
    for sym in SYMBOLS:
        trs = c.get_transcripts(sym, limit=8) or []
        earn = c.get_earnings_history(sym, limit=24) or []
        n = 0
        for tr in sorted(trs, key=lambda t: str(t.get("call_date", "")), reverse=True):
            if n >= PER_SYMBOL:
                break
            fy, q, call_date = tr.get("fiscal_year"), tr.get("quarter"), tr.get("call_date")
            if not (fy and q and call_date):
                continue
            erow = _nearest_earn(earn, call_date)
            report_date = (erow or {}).get("report_date")
            as_of = max(str(call_date)[:10], str(report_date or call_date)[:10])
            yoy, cur_rev, pend = _fund_yoy(c, sym, as_of)
            surprise = (erow or {}).get("surprise_pct")
            if yoy is None and surprise is None:
                continue
            tasks.append({
                "task_id": f"{sym}-FY{fy}Q{q}",
                "symbol": sym, "fiscal_year": fy, "quarter": q, "as_of": as_of,
                "question": (f"针对 {sym} 的 FY{fy}Q{q} 财报: (a) 营收同比增长约百分之多少? "
                             f"(b) 管理层在电话会上把这一季的主要驱动/原因归结为什么? "
                             f"请回答,并为每个主张标注它依据哪条证据。"),
                "ground_truth": {
                    "revenue_yoy_pct": yoy,                       # from get_fundamentals (agent's source)
                    "revenue": cur_rev, "fundamentals_period": pend,
                    "eps_surprise_pct": round(surprise, 1) if isinstance(surprise, (int, float)) else None,
                },
                "evidence_available": ["get_fundamentals", "get_earnings_history",
                                       "search_transcript", "get_news"],
            })
            n += 1
        log.info("built %d tasks for %s", n, sym)
    OUT.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in tasks), encoding="utf-8")
    print(f"wrote {len(tasks)} tasks -> {OUT}")
    return tasks


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    build()
