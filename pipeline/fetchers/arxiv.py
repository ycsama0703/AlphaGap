"""arXiv RSS / API fetcher.

Pulls recent papers from arXiv categories specified in whitelist.yaml.
Uses feedparser for the RSS feeds (no rate limit issues).

TODO:
  - implement fetch_recent(categories, since_date) -> list[PaperRecord]
  - dedup by arxiv_id
  - parse authors and affiliations (arxiv often lacks affils, may need S2 to enrich)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class PaperRecord:
    id: str
    source: str
    arxiv_id: str | None
    title: str
    abstract: str
    authors: list[dict]    # [{"name": ..., "affiliations": [...]}, ...]
    publication_date: date
    arxiv_categories: list[str]
    url: str
    raw_meta: dict


def fetch_recent(categories: list[str], since_date: date) -> list[PaperRecord]:
    raise NotImplementedError
