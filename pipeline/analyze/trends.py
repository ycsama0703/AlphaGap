"""Trend summary — Prompt 03 (mechanism-level dynamic clustering).

Pipeline:
  1. Fetch papers in 90d (AI) / 180d (Fin) window with mechanism_description.
  2. Sort by priority + citation_velocity, cap at 100 to control prompt size.
  3. Feed to Prompt 03: LLM dynamically clusters mechanism descriptions into
     families and classifies rising/falling/new_emergence/stable_hot.
  4. Output families are mechanism-level (35-80 char names), not tags.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from .. import db
from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient
from . import citations as cite_mod


log = logging.getLogger(__name__)

# Asymmetric windows reflect different publication cadences:
#   AI:  arxiv daily + conference batches every 2-3 months → 90d covers one cycle
#   Fin: SSRN slow + annual journals → 180d for meaningful negative evidence
WINDOW_DAYS_AI = 90
WINDOW_DAYS_FIN = 180
WINDOW_DAYS = WINDOW_DAYS_AI    # legacy default for backwards compat
MIN_COUNT_RECENT = 3            # concepts with < 3 papers in window are noise


def window_for_side(side: str) -> int:
    """Return the trend observation window for a given side."""
    if side == "fin":
        return WINDOW_DAYS_FIN
    return WINDOW_DAYS_AI   # ai or both


def _canonicalize(name: str) -> str:
    """Lowercase + collapse whitespace. Keeps concept distinct enough."""
    return " ".join((name or "").lower().split())


def aggregate_mechanism_papers(side: str, recent_end: date,
                                window_days: int = WINDOW_DAYS,
                                max_papers: int = 100) -> dict:
    """Pull papers with mechanism_description in window, sorted by priority desc.

    Returns:
      {
        side, window_recent, window_prior,
        papers: [{paper_id, mechanism, publication_date, in_recent_window,
                  citation_velocity_30d, affiliation, method_primary}, ...]
      }
    """
    recent_start = recent_end - timedelta(days=window_days - 1)
    prior_end = recent_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=window_days - 1)

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.publication_date, p.affiliations,
                   e.method_primary_json, e.mechanism_description_json,
                   e.side as ext_side,
                   s.priority_score
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            LEFT JOIN paper_signals s ON s.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND p.publication_date IS NOT NULL
              AND (e.side = ? OR e.side = 'both')
              AND date(p.publication_date) >= ?
              AND date(p.publication_date) <= ?
              AND e.mechanism_description_json IS NOT NULL
              AND e.mechanism_description_json != ''
              AND e.mechanism_description_json != '{}'
            ORDER BY s.priority_score DESC NULLS LAST
            LIMIT ?
            """,
            (side, prior_start.isoformat(), recent_end.isoformat(), max_papers),
        ).fetchall()

    papers_out = []
    for r in rows:
        pub = r["publication_date"][:10] if r["publication_date"] else None
        if not pub:
            continue
        try:
            pub_d = date.fromisoformat(pub)
        except ValueError:
            continue

        mech = json.loads(r["mechanism_description_json"] or "{}")
        if not mech.get("one_liner"):
            continue       # drop papers without mechanism content

        # Per-paper citation velocity
        with db.connect() as c2:
            v, _ = db.citation_velocity(c2, r["id"], window_days=30,
                                         as_of=recent_end.isoformat())

        papers_out.append({
            "paper_id": r["id"],
            "mechanism": {
                "one_liner": mech.get("one_liner", ""),
                "what_problem": mech.get("what_problem", ""),
                "contrast": mech.get("contrast", ""),
                "prerequisites": mech.get("prerequisites", ""),
            },
            "publication_date": pub,
            "in_recent_window": recent_start <= pub_d <= recent_end,
            "citation_velocity_30d": v or 0,
            "affiliation": (r["affiliations"] or "").split(";")[0].strip(),
            "method_primary": json.loads(r["method_primary_json"] or "[]"),
            "priority_score": r["priority_score"] or 0.0,
        })

    return {
        "side": side,
        "window_recent": f"{recent_start} to {recent_end}",
        "window_prior": f"{prior_start} to {prior_end}",
        "papers": papers_out,
    }


# Legacy function name kept for callers; redirects to new aggregation
def aggregate_concept_counts(side: str, recent_end: date,
                              window_days: int = WINDOW_DAYS) -> dict:
    return aggregate_mechanism_papers(side, recent_end, window_days)


def summarize_trends(side: str, recent_end: date | None = None,
                     client: LLMClient | None = None,
                     window_days: int | None = None,
                     max_papers: int = 100) -> dict:
    """Run Prompt 03 (mechanism-level clustering) for one side.

    Returns {rising, falling, new_emergence, stable_hot} where each item is
    a mechanism family (not a tag).
    """
    recent_end = recent_end or date.today()
    if window_days is None:
        window_days = window_for_side(side)
    payload = aggregate_mechanism_papers(side, recent_end, window_days=window_days,
                                          max_papers=max_papers)

    if not payload["papers"]:
        log.info("No papers with mechanism descriptions for side=%s; skipping LLM trend call", side)
        return {"rising": [], "falling": [], "new_emergence": [], "stable_hot": [],
                "_meta": {"reason": "no_data", **{k: v for k, v in payload.items() if k != "papers"}}}

    client = client or LLMClient()
    system, user_template = parse_prompt("03_trend_summary")
    user = render_template(
        user_template,
        side=side,
        window_recent=payload["window_recent"],
        window_prior=payload["window_prior"],
        papers_json=json.dumps(payload["papers"], ensure_ascii=False, indent=2),
    )
    # mechanism-clustering can produce long output; give it more headroom
    try:
        result = client.chat_json(system=system, user=user, temperature=0.2, max_tokens=8192)
    except Exception as e:
        log.warning("Trend LLM call failed for side=%s: %s (returning empty trends)", side, e)
        return {"rising": [], "falling": [], "new_emergence": [], "stable_hot": [],
                "_meta": {"reason": "llm_error", "error": str(e),
                          "paper_count": len(payload["papers"])}}

    for key in ("rising", "falling", "new_emergence", "stable_hot"):
        result.setdefault(key, [])
        if not isinstance(result[key], list):
            result[key] = []

    # Post-filter: drop families where name is too short (LLM didn't really do
    # mechanism-level clustering — fell back to tags)
    for key in ("rising", "falling", "new_emergence", "stable_hot"):
        filtered = []
        for item in result[key]:
            name = (item.get("name") or "").strip()
            if len(name) < 25:
                log.debug("Drop short-name trend family: %r", name)
                continue
            filtered.append(item)
        result[key] = filtered

    result["_meta"] = {
        "side": side,
        "window_recent": payload["window_recent"],
        "paper_count": len(payload["papers"]),
    }
    return result


# ---------- CLI smoke test ----------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("side", nargs="?", default="ai", choices=["ai", "fin", "both"])
    parser.add_argument("--window", type=int, default=WINDOW_DAYS,
                        help="Window size in days (use smaller for early-data testing)")
    parser.add_argument("--end-date", help="ISO date, default today")
    parser.add_argument("--max-papers", type=int, default=100,
                        help="Max mechanism papers to include in Prompt 03")
    parser.add_argument("--no-llm", action="store_true",
                        help="Only print aggregation payload; skip Prompt 03")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    payload = aggregate_mechanism_papers(
        args.side,
        end,
        window_days=args.window,
        max_papers=args.max_papers,
    )
    print(f"\n=== Aggregation: side={args.side}, window={args.window}d, end={end} ===")
    print(f"Recent: {payload['window_recent']} | Prior: {payload['window_prior']}")
    print(f"Mechanism papers: {len(payload['papers'])} (cap={args.max_papers})")
    for p in payload["papers"][:15]:
        mech = p["mechanism"]
        methods = ", ".join(p.get("method_primary") or [])
        recent_flag = "recent" if p["in_recent_window"] else "prior"
        print(f"  - [{p['paper_id']}] {p['publication_date']} · {recent_flag}")
        if methods:
            print(f"      method: {methods}")
        print(f"      mechanism: {mech.get('one_liner', '')}")
        if mech.get("what_problem"):
            print(f"      problem: {mech['what_problem']}")

    if not payload["papers"]:
        print("\n(not enough data to call LLM yet — need more extracted papers)")
        sys.exit(0)
    if args.no_llm:
        sys.exit(0)

    print(f"\n=== Calling Prompt 03 ===")
    result = summarize_trends(
        args.side,
        end,
        window_days=args.window,
        max_papers=args.max_papers,
    )
    for bucket in ("rising", "falling", "new_emergence", "stable_hot"):
        items = result.get(bucket, [])
        print(f"\n{bucket} ({len(items)}):")
        for it in items:
            print(f"  - {it.get('name')}: {it.get('comment')}")
