"""SSRN Financial Economics Network (FEN) weekly digest fetcher.

SSRN has no official API; we scrape the FEN weekly digest pages.
Alternative: subscribe to FEN email and parse those.

TODO:
  - implement fetch_recent_fin_papers(since_date) -> list[PaperRecord]
  - may need to handle login / rate limits gracefully
"""
from __future__ import annotations

from datetime import date

from .arxiv import PaperRecord


def fetch_recent_fin_papers(since_date: date) -> list[PaperRecord]:
    raise NotImplementedError
