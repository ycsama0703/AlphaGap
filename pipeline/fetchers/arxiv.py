"""arXiv API fetcher.

Uses the official arXiv Atom API: http://export.arxiv.org/api/query
Recommended rate limit: 1 request per 3 seconds.

The API gives us title / abstract / authors / dates / categories.
It does NOT reliably give author affiliations — that's enriched later via S2.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterator

import feedparser
import requests


log = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"
RATE_LIMIT_SECONDS = 3.1


@dataclass
class PaperRecord:
    id: str
    source: str
    arxiv_id: str | None
    title: str
    abstract: str
    authors: list[dict]            # [{"name": str, "affiliations": [str]}, ...]
    publication_date: date
    arxiv_categories: list[str]
    url: str
    raw_meta: dict = field(default_factory=dict)


def fetch_recent(
    categories: list[str],
    since_date: date,
    *,
    max_per_category: int = 200,
) -> list[PaperRecord]:
    """Fetch papers submitted on/after since_date from given arXiv categories.

    Dedups by arxiv_id (a paper cross-listed in cs.LG and cs.CL appears once).
    """
    seen: set[str] = set()
    results: list[PaperRecord] = []

    for cat in categories:
        log.info("Fetching arXiv category %s since %s", cat, since_date)
        for paper in _fetch_category(cat, since_date, max_per_category):
            if paper.arxiv_id in seen:
                continue
            seen.add(paper.arxiv_id)
            results.append(paper)
        time.sleep(RATE_LIMIT_SECONDS)

    log.info("arXiv: %d unique papers across %d categories", len(results), len(categories))
    return results


def _fetch_category(category: str, since_date: date, max_results: int) -> Iterator[PaperRecord]:
    params = {
        "search_query": f"cat:{category}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    resp = requests.get(ARXIV_API_URL, params=params, timeout=30)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    if feed.bozo and feed.entries == []:
        log.warning("arXiv parse issue for %s: %s", category, feed.bozo_exception)
        return

    for entry in feed.entries:
        pub_date = _parse_iso_date(entry.get("published"))
        if pub_date is None:
            continue
        if pub_date < since_date:
            # Results are sorted desc, so we're done with this category
            return
        yield _entry_to_record(entry, category)


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _entry_to_record(entry, search_category: str) -> PaperRecord:
    # entry.id looks like "http://arxiv.org/abs/2401.12345v2"
    raw_id = entry.id.rsplit("/", 1)[-1]
    arxiv_id = raw_id.split("v")[0]   # strip version suffix

    authors = [
        {"name": (a.get("name") or "").strip(), "affiliations": []}
        for a in entry.get("authors", [])
        if a.get("name")
    ]

    categories: list[str] = []
    if hasattr(entry, "tags"):
        categories = [t.get("term") for t in entry.tags if t.get("term")]
    if search_category not in categories:
        categories.append(search_category)

    return PaperRecord(
        id=arxiv_id,
        source="arxiv",
        arxiv_id=arxiv_id,
        title=" ".join(entry.title.split()),
        abstract=" ".join(entry.summary.split()),
        authors=authors,
        publication_date=_parse_iso_date(entry.get("published")) or date.today(),
        arxiv_categories=categories,
        url=f"https://arxiv.org/abs/{arxiv_id}",
        raw_meta={
            "updated": entry.get("updated"),
            "doi": entry.get("arxiv_doi"),
            "comment": entry.get("arxiv_comment"),
            "primary_category": (
                getattr(entry, "arxiv_primary_category", {}).get("term")
                if hasattr(entry, "arxiv_primary_category") else None
            ),
        },
    )


# ----- CLI for quick manual testing -----
if __name__ == "__main__":
    import sys
    from datetime import timedelta

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cats = sys.argv[1:] if len(sys.argv) > 1 else ["cs.LG", "q-fin.PM"]
    since = date.today() - timedelta(days=3)
    papers = fetch_recent(cats, since, max_per_category=20)

    for p in papers[:10]:
        print(f"  [{p.arxiv_id}] {p.publication_date} | {p.title[:80]}")
        print(f"      authors: {', '.join(a['name'] for a in p.authors[:4])}{'...' if len(p.authors) > 4 else ''}")
        print(f"      cats: {p.arxiv_categories}")
        print()
    print(f"Total: {len(papers)} papers")
