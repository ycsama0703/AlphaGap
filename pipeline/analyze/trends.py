"""Trend summary — Prompt 03.

Pipeline:
  1. Aggregate method_primary concept counts from paper_extractions for two
     14-day windows: recent (last 14 days ending today) vs prior (14 days before that).
  2. Filter to concepts with count_recent >= MIN_COUNT.
  3. Compute growth_pct and first_seen.
  4. Call Prompt 03 once per side (ai / fin) → returns rising/falling/new/stable buckets.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from .. import db
from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient


log = logging.getLogger(__name__)

WINDOW_DAYS = 14
MIN_COUNT_RECENT = 3        # concepts with < 3 papers in window are noise


def _canonicalize(name: str) -> str:
    """Lowercase + collapse whitespace. Keeps concept distinct enough."""
    return " ".join((name or "").lower().split())


def aggregate_concept_counts(side: str, recent_end: date,
                              window_days: int = WINDOW_DAYS) -> dict:
    """Build the prompt input dict for one side."""
    recent_start = recent_end - timedelta(days=window_days - 1)
    prior_end = recent_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=window_days - 1)

    counts_recent: dict[str, int] = {}
    counts_prior: dict[str, int] = {}
    first_seen: dict[str, date] = {}
    rep_papers: dict[str, list[tuple[float, str, str, str]]] = {}

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.publication_date, p.affiliations,
                   e.method_primary_json, e.domain_json, e.tags_json,
                   e.side as ext_side, s.priority_score
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            LEFT JOIN paper_signals s ON s.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND p.publication_date IS NOT NULL
              AND (e.side = ? OR e.side = 'both')
              AND date(p.publication_date) >= ?
              AND date(p.publication_date) <= ?
            """,
            (side, prior_start.isoformat(), recent_end.isoformat()),
        ).fetchall()

    for r in rows:
        pub = r["publication_date"][:10] if r["publication_date"] else None
        if not pub:
            continue
        try:
            pub_d = date.fromisoformat(pub)
        except ValueError:
            continue

        in_recent = recent_start <= pub_d <= recent_end
        in_prior = prior_start <= pub_d <= prior_end
        if not (in_recent or in_prior):
            continue

        # Trend signal aggregates across method_primary + domain + tags
        # (method names are usually paper-unique; domain + tags repeat and form the actual trend signal)
        concept_names: set[str] = set()
        for field in ("method_primary_json", "domain_json", "tags_json"):
            for raw in json.loads(r[field] or "[]"):
                n = _canonicalize(raw)
                if n:
                    concept_names.add(n)

        for name in concept_names:
            if in_recent:
                counts_recent[name] = counts_recent.get(name, 0) + 1
                rep_papers.setdefault(name, []).append(
                    ((r["priority_score"] or 0.0), r["id"], r["title"],
                     r["affiliations"] or "")
                )
            else:
                counts_prior[name] = counts_prior.get(name, 0) + 1
            if name not in first_seen or pub_d < first_seen[name]:
                first_seen[name] = pub_d

    concepts = []
    for name, n_recent in counts_recent.items():
        if n_recent < MIN_COUNT_RECENT:
            continue
        n_prior = counts_prior.get(name, 0)
        growth = (
            ((n_recent - n_prior) / n_prior) * 100 if n_prior > 0
            else 999.0
        )
        reps = sorted(rep_papers[name], reverse=True)[:3]
        concepts.append({
            "name": name,
            "count_recent": n_recent,
            "count_prior": n_prior,
            "growth_pct": round(growth, 1),
            "first_seen": first_seen[name].isoformat(),
            "representative_papers": [
                {
                    "arxiv_id": pid,
                    "title": (title or "")[:120],
                    "affiliation": (affil.split(";")[0] or "").strip(),
                }
                for _, pid, title, affil in reps
            ],
        })

    concepts.sort(key=lambda c: c["growth_pct"], reverse=True)

    return {
        "side": side,
        "window_recent": f"{recent_start} to {recent_end}",
        "window_prior": f"{prior_start} to {prior_end}",
        "concepts": concepts,
    }


def summarize_trends(side: str, recent_end: date | None = None,
                     client: LLMClient | None = None,
                     window_days: int = WINDOW_DAYS) -> dict:
    """Run Prompt 03 for one side."""
    recent_end = recent_end or date.today()
    payload = aggregate_concept_counts(side, recent_end, window_days=window_days)

    if not payload["concepts"]:
        log.info("No concepts above MIN_COUNT for side=%s; skipping LLM trend call", side)
        return {"rising": [], "falling": [], "new_emergence": [], "stable_hot": [],
                "_meta": {"reason": "no_data", **payload}}

    client = client or LLMClient()
    system, user_template = parse_prompt("03_trend_summary")
    user = render_template(
        user_template,
        side=side,
        window_recent=payload["window_recent"],
        window_prior=payload["window_prior"],
        concepts_json=json.dumps(payload["concepts"], ensure_ascii=False, indent=2),
    )
    result = client.chat_json(system=system, user=user, temperature=0.2)

    for key in ("rising", "falling", "new_emergence", "stable_hot"):
        result.setdefault(key, [])
        if not isinstance(result[key], list):
            result[key] = []

    result["_meta"] = {
        "side": side,
        "window_recent": payload["window_recent"],
        "concept_count": len(payload["concepts"]),
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
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    payload = aggregate_concept_counts(args.side, end, window_days=args.window)
    print(f"\n=== Aggregation: side={args.side}, window={args.window}d, end={end} ===")
    print(f"Recent: {payload['window_recent']} | Prior: {payload['window_prior']}")
    print(f"Concepts with count_recent >= {MIN_COUNT_RECENT}: {len(payload['concepts'])}")
    for c in payload["concepts"][:15]:
        print(f"  - {c['name']}: recent={c['count_recent']} prior={c['count_prior']} growth={c['growth_pct']}%")

    if not payload["concepts"]:
        print("\n(not enough data to call LLM yet — need more extracted papers)")
        sys.exit(0)

    print(f"\n=== Calling Prompt 03 ===")
    result = summarize_trends(args.side, end, window_days=args.window)
    for bucket in ("rising", "falling", "new_emergence", "stable_hot"):
        items = result.get(bucket, [])
        print(f"\n{bucket} ({len(items)}):")
        for it in items:
            print(f"  - {it.get('name')}: {it.get('comment')}")
