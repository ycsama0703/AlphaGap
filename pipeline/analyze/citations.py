"""Daily citation snapshot job + concept-level velocity aggregation.

Snapshot flow (run once/day, ideally before trends):
  1. Get all paper_ids in DB
  2. Batch-query S2 for current citation_count
  3. Write to citation_snapshots(paper_id, snapshot_date, count)

Velocity computation per concept (used by trends.py):
  For each (concept, recent_paper) pair, sum citation_velocity(paper, 30d).
  Output: concept's citation_velocity_30d aggregate.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from .. import db
from ..fetchers.semantic_scholar import fetch_citation_counts


log = logging.getLogger(__name__)


def snapshot_all_citations(*, limit: int | None = None,
                           as_of: date | None = None) -> dict:
    """Pull current citation counts for all papers in DB, write to snapshots table.

    Returns stats dict {requested, found, written}.
    """
    as_of = as_of or date.today()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id FROM papers WHERE arxiv_id IS NOT NULL OR id IS NOT NULL"
        ).fetchall()
    all_ids = [r["id"] for r in rows]
    if limit:
        all_ids = all_ids[:limit]

    log.info("Citation snapshot: %d papers to query S2", len(all_ids))
    s2_results = fetch_citation_counts(all_ids)

    written = 0
    with db.connect() as conn:
        for aid, paper in s2_results.items():
            db.upsert_citation_snapshot(
                conn, aid, paper.citation_count, paper.influential_citation_count,
                snapshot_date=as_of.isoformat(),
            )
            written += 1
    log.info("Citation snapshot: %d papers found in S2, %d written", len(s2_results), written)
    return {"requested": len(all_ids), "found": len(s2_results), "written": written}


def concept_velocity_map(side: str, recent_end: date,
                          window_days: int,
                          velocity_window_days: int = 30) -> dict[str, int]:
    """For each concept in the recent window for `side`, compute aggregate citation velocity.

    Returns dict canonical_concept_name → total_citations_added_in_velocity_window.
    """
    recent_start = recent_end - timedelta(days=window_days - 1)

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT p.id, e.method_primary_json, e.domain_json, e.tags_json
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND (e.side = ? OR e.side = 'both')
              AND date(p.publication_date) >= ?
              AND date(p.publication_date) <= ?
            """,
            (side, recent_start.isoformat(), recent_end.isoformat()),
        ).fetchall()

        velocity_by_concept: dict[str, int] = {}
        for r in rows:
            v, _ = db.citation_velocity(conn, r["id"], window_days=velocity_window_days,
                                         as_of=recent_end.isoformat())
            if v is None:
                continue
            concept_set: set[str] = set()
            for field in ("method_primary_json", "domain_json", "tags_json"):
                for raw in json.loads(r[field] or "[]"):
                    if raw:
                        concept_set.add(" ".join(raw.lower().split()))
            for name in concept_set:
                velocity_by_concept[name] = velocity_by_concept.get(name, 0) + v
    return velocity_by_concept


# CLI
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["snapshot", "velocity"])
    parser.add_argument("--side", default="ai")
    parser.add_argument("--window", type=int, default=90)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.command == "snapshot":
        stats = snapshot_all_citations(limit=args.limit)
        print(json.dumps(stats, indent=2))
    elif args.command == "velocity":
        result = concept_velocity_map(args.side, date.today(), window_days=args.window)
        # show top 20 by velocity
        top = sorted(result.items(), key=lambda kv: kv[1], reverse=True)[:20]
        for name, v in top:
            print(f"  {v:6d}  {name}")
