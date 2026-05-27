"""Quantified Fin-side uptake measurement.

Replaces LLM intuition for "Fin hasn't used X" with concrete DB counts.

For each AI concept (from trends or anchor papers), counts how many Fin papers
in the last N days mention it. Feeds the result into gap-generation prompts as
hard negative-evidence ground truth.

Why: LLM looking at 10 Fin papers and claiming "Fin hasn't used X" is unreliable.
     Counting against the full Fin DB (180-365 days) is.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from .. import db


log = logging.getLogger(__name__)

DEFAULT_UPTAKE_WINDOW_DAYS = 365


def measure_fin_uptake(concepts: list[str],
                       end_date: date | None = None,
                       window_days: int = DEFAULT_UPTAKE_WINDOW_DAYS) -> dict[str, dict]:
    """For each AI concept, count Fin paper mentions in the window.

    Returns:
      {
        "verifier-based self-correction": {
            "count": 0,
            "matched_paper_ids": [],
            "match_strength": "open_gap",   # open_gap / partial / explored
        },
        "factor mining": {
            "count": 23,
            "matched_paper_ids": ["...", ...],
            "match_strength": "explored",
        },
        ...
      }
    """
    end_date = end_date or date.today()
    start = end_date - timedelta(days=window_days)

    result: dict[str, dict] = {}
    with db.connect() as conn:
        for concept in concepts:
            kw = _canon_keyword(concept)
            if not kw:
                continue
            like_pattern = f"%{kw}%"
            rows = conn.execute(
                f"""
                SELECT p.id, p.title, p.publication_date
                FROM papers p
                JOIN paper_extractions e ON e.paper_id = p.id
                WHERE (e.side = 'fin' OR e.side = 'both')
                  AND date(p.publication_date) >= ?
                  AND date(p.publication_date) <= ?
                  AND (LOWER(p.title) LIKE ? OR LOWER(p.abstract) LIKE ?
                       OR LOWER(e.method_primary_json) LIKE ?
                       OR LOWER(e.domain_json) LIKE ?
                       OR LOWER(e.tags_json) LIKE ?)
                  AND {db.TRIGGER_ELIGIBILITY_GUARD}
                ORDER BY p.publication_date DESC
                LIMIT 20
                """,
                (start.isoformat(), end_date.isoformat(),
                 like_pattern, like_pattern, like_pattern, like_pattern, like_pattern),
            ).fetchall()

            count = len(rows)
            if count == 0:
                strength = "open_gap"
            elif count <= 3:
                strength = "partial"
            else:
                strength = "explored"

            result[concept] = {
                "count": count,
                "matched_paper_ids": [r["id"] for r in rows[:10]],
                "match_strength": strength,
            }
    return result


def _canon_keyword(s: str) -> str:
    """Lower + strip + drop unhelpful tokens. Keep multi-word phrases."""
    s = (s or "").lower().strip()
    # Remove things like "(2024)" or "[paper]" markup
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = " ".join(s.split())
    # Skip very short tokens that match too broadly
    if len(s) < 4:
        return ""
    return s


def extract_ai_concepts_for_uptake(ai_trends: dict, ai_papers: list[dict],
                                    max_concepts: int = 30) -> list[str]:
    """Pick the most relevant AI concepts to check Fin uptake for.

    Sources: ai_trends (rising/new_emergence top) + method_primary from top papers.
    """
    seen: set[str] = set()
    out: list[str] = []

    # From trends — focus on rising and new (these are the "what's new" candidates)
    for bucket in ("rising", "new_emergence", "stable_hot"):
        for item in (ai_trends.get(bucket, []) or []):
            name = (item.get("name") or "").lower().strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
                if len(out) >= max_concepts:
                    return out

    # From top papers' method_primary (catches things that aren't in trends yet)
    for p in ai_papers:
        for m in (p.get("method_primary") or []):
            m_l = (m or "").lower().strip()
            if m_l and m_l not in seen:
                seen.add(m_l)
                out.append(m_l)
                if len(out) >= max_concepts:
                    return out
    return out


# ----- CLI -----
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("concepts", nargs="*", help="Specific concepts to test")
    parser.add_argument("--window", type=int, default=DEFAULT_UPTAKE_WINDOW_DAYS)
    args = parser.parse_args()

    test_concepts = args.concepts or [
        "verifier-based self-correction",
        "factor mining",
        "in-context learning",
        "portfolio optimization",
        "agent",
        "reinforcement learning",
    ]
    result = measure_fin_uptake(test_concepts, window_days=args.window)
    print(json.dumps(result, indent=2, ensure_ascii=False))
