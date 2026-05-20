"""HuggingFace Daily Papers fetcher.

API: https://huggingface.co/api/daily_papers?date=YYYY-MM-DD
Returns a list of community-curated papers for the given date, each with an
arxiv_id, summary, authors, upvotes, and HF's own ai_keywords extraction.

We treat HF Daily as a community signal: a paper appearing here gets a boost
in the candidate-pool filter (regardless of whitelist hits). The upvote count
and ai_keywords are kept in raw_meta for downstream use.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import requests

from .arxiv import PaperRecord


log = logging.getLogger(__name__)

HF_DAILY_URL = "https://huggingface.co/api/daily_papers"


def fetch_for_date(d: date) -> list[PaperRecord]:
    """Fetch HF Daily Papers for a specific date."""
    log.info("Fetching HF Daily Papers for %s", d)
    params = {"date": d.isoformat()}
    resp = requests.get(HF_DAILY_URL, params=params, timeout=30)
    resp.raise_for_status()

    items = resp.json()
    if not isinstance(items, list):
        log.warning("Unexpected HF response shape: %r", type(items))
        return []

    papers: list[PaperRecord] = []
    for item in items:
        rec = _item_to_record(item)
        if rec is not None:
            papers.append(rec)

    log.info("HF Daily: %d papers on %s", len(papers), d)
    return papers


def fetch_recent(since_date: date, until_date: date | None = None) -> list[PaperRecord]:
    """Fetch HF Daily Papers over a date range. Dedup by arxiv_id."""
    from datetime import timedelta

    until_date = until_date or date.today()
    seen: set[str] = set()
    results: list[PaperRecord] = []

    d = since_date
    while d <= until_date:
        try:
            for p in fetch_for_date(d):
                if p.arxiv_id and p.arxiv_id in seen:
                    continue
                if p.arxiv_id:
                    seen.add(p.arxiv_id)
                results.append(p)
        except requests.HTTPError as e:
            log.warning("HF Daily fetch failed for %s: %s", d, e)
        d += timedelta(days=1)

    return results


def _item_to_record(item: dict) -> PaperRecord | None:
    paper = item.get("paper") or {}
    arxiv_id = paper.get("id")
    if not arxiv_id:
        return None

    pub_iso = paper.get("publishedAt") or item.get("publishedAt") or ""
    pub_date = _parse_iso(pub_iso) or date.today()

    authors = [
        {"name": (a.get("name") or "").strip(), "affiliations": []}
        for a in paper.get("authors", [])
        if a.get("name")
    ]

    return PaperRecord(
        id=arxiv_id,
        source="hf_daily",
        arxiv_id=arxiv_id,
        title=" ".join((paper.get("title") or item.get("title") or "").split()),
        abstract=" ".join((paper.get("summary") or item.get("summary") or "").split()),
        authors=authors,
        publication_date=pub_date,
        arxiv_categories=[],   # HF doesn't expose arxiv categories; enrich later
        url=f"https://arxiv.org/abs/{arxiv_id}",
        raw_meta={
            "hf_upvotes": paper.get("upvotes", 0),
            "hf_ai_keywords": paper.get("ai_keywords") or [],
            "hf_ai_summary": paper.get("ai_summary"),
            "hf_github_repo": paper.get("githubRepo"),
            "hf_github_stars": paper.get("githubStars"),
            "hf_organization": paper.get("organization") or item.get("organization"),
            "hf_num_comments": item.get("numComments", 0),
            "hf_submitted_by": (item.get("submittedBy") or {}).get("user"),
        },
    )


def _parse_iso(s: str) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


# ----- CLI -----
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    papers = fetch_for_date(target)

    # Sort by upvotes desc to highlight community-signal-strong ones
    papers.sort(key=lambda p: p.raw_meta.get("hf_upvotes", 0), reverse=True)

    for p in papers[:10]:
        up = p.raw_meta.get("hf_upvotes", 0)
        kws = p.raw_meta.get("hf_ai_keywords", [])
        print(f"  [{p.arxiv_id}] ↑{up} | {p.title[:75]}")
        print(f"      authors: {', '.join(a['name'] for a in p.authors[:4])}{'...' if len(p.authors) > 4 else ''}")
        print(f"      keywords: {kws[:5]}")
        print()
    print(f"Total: {len(papers)} papers on {target}")
